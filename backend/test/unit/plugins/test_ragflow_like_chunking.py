from __future__ import annotations
from yuxi.knowledge.utils.kb_utils import sanitize_processing_params
from yuxi.knowledge.chunking.ragflow_like.presets import (
    CHUNK_ENGINE_VERSION,
    get_chunk_preset_options,
    map_to_internal_parser_id,
    resolve_chunk_processing_params,
)
from yuxi.knowledge.chunking.ragflow_like.nlp import bullets_category, count_tokens
from yuxi.knowledge.chunking.ragflow_like.dispatcher import chunk_markdown

import os
import sys

sys.path.append(os.getcwd())


def test_general_maps_to_naive() -> None:
    assert map_to_internal_parser_id("general") == "naive"


def test_resolve_chunk_processing_params_priority() -> None:
    resolved = resolve_chunk_processing_params(
        kb_additional_params={
            "chunk_preset_id": "book",
            "chunk_parser_config": {"chunk_token_num": 300, "delimiter": "\\n"},
        },
        file_processing_params={
            "chunk_preset_id": "qa",
            "chunk_parser_config": {"delimiter": "###"},
        },
        request_params={
            "chunk_preset_id": "laws",
            "chunk_parser_config": {"chunk_token_num": 666},
            "chunk_size": 777,
        },
    )

    assert resolved["chunk_preset_id"] == "laws"
    assert resolved["chunk_engine_version"] == CHUNK_ENGINE_VERSION
    # In the current implementation, legacy chunk_size maps to chunk_token_num.
    assert resolved["chunk_parser_config"]["chunk_token_num"] == 777
    assert resolved["chunk_parser_config"]["delimiter"] == "###"


def test_qa_chunking_from_markdown_headings() -> None:
    content = """
# Question 1
This is answer 1.

## Sub-question
This is answer 2.
""".strip()

    chunks = chunk_markdown(
        markdown_content=content,
        file_id="file_1",
        filename="faq.md",
        processing_params={"chunk_preset_id": "qa",
                           "chunk_parser_config": {"language": "English"}},
    )

    assert len(chunks) >= 1
    assert "Question:" in chunks[0]["content"]
    assert "Answer:" in chunks[0]["content"]


def test_book_chunking_hierarchical_merge() -> None:
    content = """
Chapter 1 General Provisions
Section 1 Scope of Application
This specification applies to test scenarios.
Section 2 Basic Principles
The minimal-change principle should be followed.
""".strip()

    chunks = chunk_markdown(
        markdown_content=content,
        file_id="file_2",
        filename="book.txt",
        processing_params={"chunk_preset_id": "book",
                           "chunk_parser_config": {"chunk_token_num": 256}},
    )

    assert len(chunks) >= 1
    assert any("Chapter 1" in ck["content"] for ck in chunks)


def test_markdown_heading_has_higher_weight_in_bullet_category() -> None:
    sections = [
        "# 3.2 Overview of taxable income items and filing methods",
        "1. The following rules continue to apply for seasonal or temporary worker deductions.",
        "2. Under current policy, subsidy income is included in salary income.",
        "(1) Subsidies paid above the statutory ratio are not tax-exempt benefits.",
    ]

    # When markdown-heading patterns match (BULLET_PATTERN index 4), that group should be preferred.
    assert bullets_category(sections) == 4


def test_mid_sentence_bullet_marker_should_not_be_treated_as_heading() -> None:
    sections = [
        "Based on the previous rule: 1. this is an in-sentence list, not a heading level.",
        "Continuing above: (2) this is also inline enumeration, not an independent title.",
        "## 3.4 Tax treatment of transportation allowances",
    ]
    assert bullets_category(sections) == 4


def test_chunk_preset_options_include_description() -> None:
    options = get_chunk_preset_options()
    assert len(options) == 4
    assert all(isinstance(option.get("description"), str)
               and option["description"] for option in options)


def test_laws_chunking_should_apply_overlength_protection() -> None:
    lines = ["#### Implementing Regulations for Corporate Income Tax",
             "##### Scan to share"]
    lines.extend(
        [
            f"Article {i} Detailed provisions of corporate income tax law for test scenarios, ensuring each article is long enough to validate chunking behavior."
            for i in range(1, 260)
        ]
    )
    content = "\n".join(lines)

    max_chunk_tokens = 180
    chunks = chunk_markdown(
        markdown_content=content,
        file_id="file_laws_long",
        filename="laws.docx",
        processing_params={
            "chunk_preset_id": "laws",
            "chunk_parser_config": {
                "chunk_token_num": max_chunk_tokens,
                "overlapped_percent": 20,
                "delimiter": "\\n",
            },
        },
    )

    assert len(chunks) > 1
    assert max(count_tokens(ck["content"])
               for ck in chunks) <= max_chunk_tokens


def test_laws_chunking_should_prefer_sentence_boundary_split() -> None:
    line = "Article 1 These implementation details are used to test semantic chunk boundaries."
    content = line * 120

    chunks = chunk_markdown(
        markdown_content=content,
        file_id="file_laws_sentence",
        filename="laws.docx",
        processing_params={
            "chunk_preset_id": "laws",
            "chunk_parser_config": {
                "chunk_token_num": 120,
                "overlapped_percent": 0,
                "delimiter": "\\n",
            },
        },
    )

    assert len(chunks) > 1
    for ck in chunks:
        text = ck["content"].strip()
        assert text
        assert count_tokens(text) <= 120


def test_laws_chunking_should_prefer_article_level_before_item_level() -> None:
    content = """
Chapter VI Special Tax Adjustments
Article 106 Scenarios where a withholding agent may be designated include:
(1) direct or indirect control relationships in funding, operations, or procurement;
(2) the ability to perform other binding actions on behalf of the enterprise.
Article 107 Tax authorities may determine taxable income according to law.
""".strip()

    chunks = chunk_markdown(
        markdown_content=content,
        file_id="file_laws_article",
        filename="laws.docx",
        processing_params={
            "chunk_preset_id": "laws",
            "chunk_parser_config": {
                "chunk_token_num": 1000,
                "overlapped_percent": 0,
                "delimiter": "\\n",
            },
        },
    )

    # If the itemized clauses under one article stay in the same chunk, article-level preference is preserved.
    target_chunks = [ck["content"]
                     for ck in chunks if "Article 106" in ck["content"]]
    assert target_chunks
    assert any("(1)" in chunk and "(2)" in chunk for chunk in target_chunks)


def test_laws_markdown_articles_should_not_collapse_into_chapter_chunk() -> None:
    content = """
## Chapter I General Provisions
- **Article 1** This law is established to regulate guarantee activities and protect creditor rights.
- **Article 2** In lending activities, parties may establish guarantees according to law.
- **Article 3** Guarantee activities shall follow principles of equality, voluntariness, fairness, and good faith.
""".strip()

    chunks = chunk_markdown(
        markdown_content=content,
        file_id="file_laws_markdown_article",
        filename="laws.md",
        processing_params={
            "chunk_preset_id": "laws",
            "chunk_parser_config": {
                "chunk_token_num": 120,
                "overlapped_percent": 0,
                "delimiter": "\\n",
            },
        },
    )

    first_article_chunks = [ck["content"]
                            for ck in chunks if "Article 1" in ck["content"]]
    assert first_article_chunks
    # With article-level splitting, Article 1 and Article 2 should not be merged into one chunk.
    assert all("Article 2" not in chunk for chunk in first_article_chunks)
    assert max(count_tokens(ck["content"]) for ck in chunks) <= 120


def test_sanitize_processing_params_should_drop_batch_only_fields() -> None:
    sanitized = sanitize_processing_params(
        {
            "chunk_preset_id": "general",
            "content_hashes": {"a.md": "hash-a"},
            "_preprocessed_map": {"a.md": {"path": "/tmp/a.md"}},
        }
    )

    assert sanitized == {"chunk_preset_id": "general"}
