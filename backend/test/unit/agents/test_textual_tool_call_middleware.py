from langchain_core.messages import AIMessage

from yunesa.agents.middlewares.tool_call_text_middleware import (
    _patch_message,
    parse_textual_tool_call,
)


def test_parse_textual_query_kb_call() -> None:
    parsed = parse_textual_tool_call(
        '<function(query_kb){"kb_name":"yunesa_academic_kg","query_text":"authors","include_graph":true}>',
        {"query_kb"},
    )

    assert parsed is not None
    assert parsed["name"] == "query_kb"
    assert parsed["args"]["kb_name"] == "yunesa_academic_kg"
    assert parsed["args"]["include_graph"] is True
    assert parsed["id"].startswith("call_")


def test_patch_ai_message_textual_tool_call() -> None:
    message = AIMessage(
        content='<function(query_kb){"kb_name":"yunesa_academic_kg","query_text":"stress"}>'
    )

    patched = _patch_message(message, {"query_kb"})

    assert isinstance(patched, AIMessage)
    assert patched.content == ""
    assert len(patched.tool_calls) == 1
    assert patched.tool_calls[0]["name"] == "query_kb"
    assert patched.tool_calls[0]["args"]["query_text"] == "stress"


def test_ignore_unknown_textual_tool_call() -> None:
    message = AIMessage(content='<function(unknown_tool){"query":"x"}>')

    patched = _patch_message(message, {"query_kb"})

    assert patched is message
