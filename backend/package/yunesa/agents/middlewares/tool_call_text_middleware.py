"""Normalize provider-emitted textual tool calls into LangChain tool calls.

Some OpenAI-compatible providers/models can emit a tool call as plain text, for
example:

    <function(query_kb){"kb_name": "...", "query_text": "..."}>

Yuxi's UI expects tool invocations to arrive in ``AIMessage.tool_calls`` and
renders them separately from assistant prose. This middleware preserves that
contract for providers that do not return native tool-call payloads.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, BaseMessage


_FUNCTION_CALL_RE = re.compile(
    r"^\s*<function\((?P<name>[A-Za-z_][\w.\-]*)\)\s*(?P<args>\{.*\})\s*(?:</function>)?>\s*$",
    re.DOTALL,
)


def _tool_names(tools: list[Any]) -> set[str]:
    names: set[str] = set()
    for tool in tools or []:
        name = getattr(tool, "name", None)
        if isinstance(name, str) and name:
            names.add(name)
            continue

        if isinstance(tool, dict):
            dict_name = tool.get("name") or tool.get("function", {}).get("name")
            if isinstance(dict_name, str) and dict_name:
                names.add(dict_name)
    return names


def parse_textual_tool_call(content: Any, allowed_tool_names: set[str] | None = None) -> dict[str, Any] | None:
    """Parse a full textual tool-call marker into a LangChain tool-call dict."""
    if not isinstance(content, str):
        return None

    match = _FUNCTION_CALL_RE.match(content)
    if not match:
        return None

    name = match.group("name")
    if allowed_tool_names is not None and name not in allowed_tool_names:
        return None

    try:
        args = json.loads(match.group("args"))
    except json.JSONDecodeError:
        return None

    if not isinstance(args, dict):
        return None

    return {
        "name": name,
        "args": args,
        "id": f"call_{uuid.uuid4().hex}",
    }


def _patch_message(message: BaseMessage, allowed_tool_names: set[str]) -> BaseMessage:
    if not isinstance(message, AIMessage):
        return message

    if message.tool_calls:
        return message

    tool_call = parse_textual_tool_call(message.content, allowed_tool_names)
    if not tool_call:
        return message

    return AIMessage(
        content="",
        tool_calls=[tool_call],
        id=message.id,
        name=message.name,
        response_metadata=message.response_metadata,
        additional_kwargs=message.additional_kwargs,
        usage_metadata=message.usage_metadata,
    )


class TextualToolCallMiddleware(AgentMiddleware):
    """Convert model text that represents a tool call into native tool calls."""

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        response = await handler(request)
        allowed_tool_names = _tool_names(request.tools)
        if not allowed_tool_names:
            return response

        patched_result = [_patch_message(message, allowed_tool_names) for message in response.result]
        return ModelResponse(
            result=patched_result,
            structured_response=response.structured_response,
        )
