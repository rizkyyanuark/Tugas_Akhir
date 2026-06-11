import os
import traceback
import uuid
from typing import Annotated, Any

import requests
from langgraph.types import interrupt

from yunesa import config, graph_base
from yunesa.agents.toolkits.registry import ToolExtraMetadata, _all_tool_instances, _extra_registry, tool
from yunesa.storage.minio import aupload_file_to_minio
from yunesa.utils import logger
from yunesa.utils.question_utils import normalize_questions

# Lazy initialization for TavilySearch (only when API key is available)
_tavily_search_instance = None

QWEN_IMAGE_CONFIG_GUIDE = """
Before using this tool, configure SiliconFlow image-generation credentials.

Set the following environment variable in the backend runtime:
- `SILICONFLOW_API_KEY`: used to call the SiliconFlow image generation API

After configuration, this tool can generate images.
""".strip()


def _normalize_presented_artifact_path(path: str, runtime) -> str:
    """Normalize an artifact path to a sandbox-visible outputs path.

    Agents may pass either a host-side file path or an existing virtual path.
    Only files under the thread outputs directory are presentable artifacts.
    """

    from pathlib import Path

    from yunesa.agents.backends.sandbox import (
        VIRTUAL_PATH_PREFIX,
        resolve_virtual_path,
        sandbox_outputs_dir,
        virtual_path_for_thread_file,
    )

    raw_path = str(path or "").strip()
    if not raw_path:
        raise ValueError("artifact path is required")

    context = getattr(runtime, "context", None)
    thread_id = str(getattr(context, "thread_id", "") or "").strip()
    user_id = str(getattr(context, "user_id", "") or "").strip()
    if not thread_id or not user_id:
        raise ValueError("runtime context must include thread_id and user_id")

    virtual_prefix = "/" + VIRTUAL_PATH_PREFIX.strip("/")
    if raw_path == virtual_prefix or raw_path.startswith(f"{virtual_prefix}/"):
        normalized = "/" + raw_path.strip().lstrip("/")
        host_path = resolve_virtual_path(thread_id, normalized, user_id=user_id)
    else:
        host_path = Path(raw_path).resolve()
        normalized = virtual_path_for_thread_file(thread_id, host_path, user_id=user_id)

    outputs_root = sandbox_outputs_dir(thread_id).resolve()
    try:
        host_path.resolve().relative_to(outputs_root)
    except ValueError as exc:
        raise ValueError(f"artifact path must be under {virtual_prefix}/outputs/") from exc

    if not normalized.startswith(f"{virtual_prefix}/outputs/"):
        raise ValueError(f"artifact path must be under {virtual_prefix}/outputs/")

    return normalized


def _create_tavily_search():
    """Create and register TavilySearch tool with metadata."""
    global _tavily_search_instance
    if _tavily_search_instance is None:
        from langchain_tavily import TavilySearch

        _tavily_search_instance = TavilySearch()

    return _tavily_search_instance


# Register TavilySearch tool (lazy initialization)
def _register_tavily_tool():
    """Register TavilySearch tool with extra metadata."""
    tavily_instance = _create_tavily_search()
    # Manually register in global registry.
    _extra_registry["tavily_search"] = ToolExtraMetadata(
        category="buildin",
        tags=["search"],
        display_name="Tavily Web Search",
    )
    # Add to tool instance list.
    _all_tool_instances.append(tavily_instance)


# Register when module is loaded.
if config.enable_web_search:
    try:
        _register_tavily_tool()
    except Exception as e:
        logger.warning(f"Failed to register TavilySearch tool: {e}")


@tool(category="buildin", tags=["calculate"], display_name="Calculator")
def calculator(a: float, b: float, operation: str) -> float:
    """Calculator: perform basic arithmetic operations on two numbers."""
    try:
        if operation == "add":
            return a + b
        elif operation == "subtract":
            return a - b
        elif operation == "multiply":
            return a * b
        elif operation == "divide":
            if b == 0:
                raise ZeroDivisionError("Divisor cannot be zero")
            return a / b
        else:
            raise ValueError(
                f"Unsupported operation type: {operation}. Supported: add, subtract, multiply, divide")
    except Exception as e:
        logger.error(f"Calculator error: {e}")
        raise


ASK_USER_QUESTION_DESCRIPTION = """
Use this tool to ask the user questions when you need decisions or additional requirements during execution.

Suitable scenarios:
1. Collect user preferences or requirements (for example style, scope, priority)
2. Clarify ambiguous instructions (when multiple interpretations are reasonable)
3. Let the user choose implementation direction during execution
4. Ask the user to make trade-offs when there are clear alternatives

Usage guidelines:
1. `questions` should include 1-5 questions. Each item contains: `question`, `options`, `multi_select`, `allow_other`
2. Each question should provide 2-5 clearly distinguishable options. Each option contains `label` and `value`
3. If there is a recommended option, place it first and append "(Recommended)" to its label
4. If multi-selection is required, set `multi_select` to `true` for that question
5. Keep `allow_other` as `true` in most cases so users can provide custom answers through Other input

Notes:
1. Do not use this tool to ask workflow-control questions like "whether to continue execution" or "whether the plan is ready"
2. Do not overuse this tool when information is already sufficient and no user decision is required
3. Make decisions based on existing context first; ask only when there is critical uncertainty

Return format:
`answer` is an object formatted as `{question_id: answer}`.
`answer` can be a string (single-select), list (multi-select), or object (Other text).
"""


@tool(
    category="buildin",
    tags=["interaction"],
    display_name="Ask User Question",
    description=ASK_USER_QUESTION_DESCRIPTION,
)
def ask_user_question(
    questions: Annotated[
        list[dict] | str | None,
        "Question list, each item format: {question, options, multi_select, allow_other, question_id(optional)}",
    ] = None,
    question: Annotated[str,
                        "Compatibility field: single question text (prefer using questions)"] = "",
    options: Annotated[list[dict] | str | None,
                       "Compatibility field: single-question options (prefer using questions)"] = None,
    multi_select: Annotated[bool,
                            "Compatibility field: whether single-question multi-select is allowed"] = False,
    allow_other: Annotated[bool,
                           "Compatibility field: whether custom Other answer is allowed"] = True,
) -> dict:
    """Ask the user a question and wait for an answer."""
    # Parse options parameter: if it is a string, try parsing it as JSON.
    if isinstance(options, str):
        try:
            import json

            options = json.loads(options)
            logger.debug(f"Parsed string options to list: {options}")
        except Exception as e:
            logger.error(
                f"Failed to parse options string: {e}, using empty list")
            options = []

    # Parse questions parameter: if it is a string, try parsing it as JSON.
    if isinstance(questions, str):
        try:
            import json

            questions = json.loads(questions)
            logger.debug(f"Parsed string questions to list: {questions}")
        except Exception as e:
            logger.error(f"Failed to parse questions string: {e}, using None")
            questions = None

    input_questions = questions
    if not input_questions:
        legacy_question = str(question or "").strip()
        if legacy_question:
            input_questions = [
                {
                    "question": legacy_question,
                    "options": options or [],
                    "multi_select": multi_select,
                    "allow_other": allow_other,
                }
            ]

    normalized_questions = normalize_questions(input_questions or [])

    if not normalized_questions:
        raise ValueError("questions must contain at least one valid question")

    interrupt_payload = {
        "questions": normalized_questions,
        "source": "ask_user_question",
    }
    answer = interrupt(interrupt_payload)

    return {
        "questions": normalized_questions,
        "answer": answer,
    }


KG_QUERY_DESCRIPTION = """
Use this tool to query triple information stored in the knowledge graph.
For `query`, use keywords that help answer the question instead of directly using the user's raw input.
"""


@tool(category="buildin", tags=["graph"], display_name="Query Knowledge Graph", description=KG_QUERY_DESCRIPTION)
def query_knowledge_graph(query: Annotated[str, "The keyword to query knowledge graph."]) -> Any:
    """Query triple information stored in the knowledge graph using focused keywords."""
    try:
        logger.debug(f"Querying knowledge graph with: {query}")
        result = graph_base.query_node(query, hops=2, return_format="triples")
        logger.debug(
            f"Knowledge graph query returned "
            f"{len(result.get('triples', [])) if isinstance(result, dict) else 'N/A'} triples"
        )
        return result
    except Exception as e:
        logger.error(
            f"Knowledge graph query error: {e}, {traceback.format_exc()}")
        return f"Knowledge graph query failed: {str(e)}"


@tool(
    category="buildin",
    tags=["image", "generate"],
    display_name="Qwen-Image",
    config_guide=QWEN_IMAGE_CONFIG_GUIDE,
)
async def text_to_img_qwen_image(
    prompt: Annotated[str, "Text prompt used to generate the image"],
    negative_prompt: Annotated[str,
                               "Negative prompt used to describe elements that should not appear"] = "",
    num_inference_steps: Annotated[int, "Inference steps, range 1-100"] = 20,
    guidance_scale: Annotated[float,
                              "Guidance scale controlling prompt adherence"] = 7.5,
    user_id: Annotated[str,
                       "User ID used for image archival path"] = "unknown",
) -> str:
    """Generate an image with Qwen-Image and return its URL.

    Generated results are not shown automatically; the returned URL should be processed and presented explicitly.
    """
    url = "https://api.siliconflow.com/v1/images/generations"

    payload = {
        "model": "Qwen/Qwen-Image",
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "num_inference_steps": num_inference_steps,
        "guidance_scale": guidance_scale,
    }
    headers = {
        "Authorization": f"Bearer {os.getenv('SILICONFLOW_API_KEY')}", "Content-Type": "application/json"}

    try:
        response = requests.post(url, json=payload, headers=headers)
        response_json = response.json()
    except Exception as e:
        logger.error(f"Failed to generate image with: {e}")
        raise ValueError(f"Image generation failed: {e}")

    try:
        image_url = response_json["images"][0]["url"]
    except (KeyError, IndexError, TypeError) as e:
        logger.error(
            f"Failed to parse image URL from response: {e}, {response_json=}")
        raise ValueError(f"Image URL extraction failed: {e}")

    # Upload to MinIO
    response = requests.get(image_url)
    file_data = response.content

    safe_user_id = str(user_id or "unknown").replace(
        "/", "_").replace("\\", "_")
    file_name = f"user/{safe_user_id}/generated-images/{uuid.uuid4()}.jpg"
    image_url = await aupload_file_to_minio(bucket_name="public", file_name=file_name, data=file_data)
    logger.info(f"Image uploaded. URL: {image_url}")
    return image_url
