"""Summary + ToolResult Offload Middleware.

Implemented on top of LangChain's SummarizationMiddleware with additional tool-result offloading:
- Preserve the existing summary history logic
- Offload ToolMessage results to a virtual file system (default: > 1k characters)
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterable, Mapping
from functools import partial
from pathlib import Path
from typing import Any, Literal, cast
from typing_extensions import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.chat_models import BaseChatModel, init_chat_model
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    MessageLikeRepresentation,
    RemoveMessage,
    ToolMessage,
)
from langchain_core.messages.utils import (
    count_tokens_approximately,
    get_buffer_string,
    trim_messages,
)
from langgraph.graph.message import REMOVE_ALL_MESSAGES
from langgraph.runtime import Runtime

from ta_backend_core.assistant.utils.paths import OUTPUTS_DIR_NAME

TokenCounter = Callable[[Iterable[MessageLikeRepresentation]], int]

DEFAULT_SUMMARY_PROMPT = """<role>
Context Extraction Assistant
</role>

<primary_objective>
Your sole objective in this task is to extract the highest quality/most relevant
context from the conversation history below.
</primary_objective>

<objective_information>
You're nearing the total number of input tokens you can accept, so you must
extract the highest quality/most relevant pieces of information from your conversation
history. This context will then overwrite the conversation history presented below.
Because of this, ensure the context you extract is only the most important information
to your overall goal.
</objective_information>

<instructions>
The conversation history below will be replaced with the context you extract in
this step. Because of this, you must do your very best to extract and record all
of the most important context from the conversation history. You want to ensure
that you don't repeat any actions you've already completed, so the context you
extract from the conversation history should be focused on the most important
information to your overall goal.
</instructions>

The user will message you with the full message history you'll be extracting context
from, to then replace. Carefully read over it all, and think deeply about what
information is most important to your overall goal that should be saved.

With all of this in mind, please carefully read over the entire conversation history,
and extract the most important and relevant context to replace it so that you can
free up space in the conversation history. Respond ONLY with the extracted context.
Do not include any additional information, or text before or after the extracted context.

<messages>
Messages to summarize:
{messages}
</messages>"""

_DEFAULT_MESSAGES_TO_KEEP = 20
_DEFAULT_FALLBACK_MESSAGE_COUNT = 15
_OFFLOAD_DIR = "/summary_offload"  # Virtual file system path

ContextFraction = tuple[Literal["fraction"], float]
ContextTokens = tuple[Literal["tokens"], int]
ContextMessages = tuple[Literal["messages"], int]

ContextSize = ContextFraction | ContextTokens | ContextMessages


def _get_approximate_token_counter(model: BaseChatModel) -> TokenCounter:
    """Tune parameters of approximate token counter based on model type."""
    if model._llm_type == "anthropic-chat":  # noqa: SLF001
        return partial(count_tokens_approximately, chars_per_token=3.3)
    return count_tokens_approximately


def _get_content_str(content: Any) -> str | None:
    """Convert ToolMessage content to string for size checking."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        if len(content) == 1 and isinstance(content[0], dict) and content[0].get("type") == "text":
            return str(content[0].get("text", ""))
        return str(content)
    return str(content)


def _format_offload_placeholder(file_path: str, content_sample: str) -> str:
    """Format the placeholder message for offloaded content."""
    return (
        f"[ToolResultOffloaded]\n\n"
        f"File path: {file_path}\n"
        f"Use the read_file tool to read the full content\n\n"
        f"--- Content Preview ---\n{content_sample}"
    )


def _offload_tool_result(msg: ToolMessage, threshold: int, token_counter: TokenCounter) -> dict[str, Any] | None:
    """Offload a single tool result that exceeds the threshold.

    Args:
        msg: ToolMessage
        threshold: token threshold
        token_counter: token counter function

    Returns:
        A dictionary containing file updates, or None if nothing was offloaded
    """
    content = msg.content
    content_str = _get_content_str(content)

    if content_str is None:
        return None

    # Count tokens
    msg_tokens = token_counter([msg])
    if msg_tokens <= threshold:
        return None

    # Get the tool name and arguments
    tool_name = msg.name or "unknown"
    tool_call_id = msg.tool_call_id or ""

    # Generate the file path (tool-name-xxx)
    message_id = msg.id or str(uuid.uuid4())[:8]
    safe_name = "".join(
        c if c.isalnum() or c in "-_" else "_" for c in tool_name)
    file_path = (Path(OUTPUTS_DIR_NAME) /
                 f"{_OFFLOAD_DIR}/{safe_name}-{message_id}").as_posix()

    # Build header information for the file
    header_lines = [
        "=== Tool Invocation ===",
        f"Tool: {tool_name}",
        f"Tool Call ID: {tool_call_id}",
        "=" * 40,
        "",
    ]
    header = "\n".join(header_lines)

    # Save in files format (including header information)
    from datetime import datetime

    timestamp = datetime.now().isoformat()
    files_update = {
        file_path: {
            "content": [header + content_str],
            "created_at": timestamp,
            "modified_at": timestamp,
        }
    }

    # Create preview content
    preview_lines = content_str.splitlines()[:10]
    content_sample = "\n".join(line[:500] for line in preview_lines)

    # Replace the message content with a placeholder
    msg.content = _format_offload_placeholder(file_path, content_sample)

    return files_update


def _offload_tool_results(
    messages: list[AnyMessage], threshold: int, token_counter: TokenCounter
) -> tuple[dict[str, Any], list[AnyMessage]]:
    """Scan the message list and offload all tool results that exceed the threshold.

    Args:
        messages: Message list
        threshold: token threshold
        token_counter: token counter function

    Returns:
        tuple[files update dict, modified message list]
    """
    files_update: dict[str, Any] = {}
    modified_messages: list[AnyMessage] = []

    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue

        result = _offload_tool_result(msg, threshold, token_counter)
        if result:
            files_update.update(result)
            modified_messages.append(msg)

    return files_update, modified_messages


class SummaryOffloadMiddleware(AgentMiddleware):
        """Summary + tool-result offload middleware.

        Built on LangChain SummarizationMiddleware with extra functionality:
        - Preserve the original summary history logic
        - Offload ToolMessage results to a virtual file system
            1. When Summary is triggered, offload tool results that exceed the threshold
            2. Smart retention strategy:
                - When Summary is triggered, offload first
                - Only clear messages (Summary) when the total token count exceeds max_retention_ratio * trigger
                - Always preserve the System Message
    """

    def __init__(
        self,
        model: str | BaseChatModel,
        *,
        trigger: ContextSize | list[ContextSize] | None = None,
        keep: ContextSize = ("messages", _DEFAULT_MESSAGES_TO_KEEP),
        token_counter: TokenCounter = count_tokens_approximately,
        summary_prompt: str = DEFAULT_SUMMARY_PROMPT,
        trim_tokens_to_summarize: int | None = 4000,
        # Tool-result offload parameters
        summary_offload_threshold: int = 1000,
        max_retention_ratio: float = 0.6,
        **deprecated_kwargs: Any,
    ) -> None:
        """Initialize the middleware.

        Args:
            model: Language model used to generate summaries
            trigger: Threshold condition for triggering summaries (recommended: ("tokens", N))
            keep: Message-count / token policy to keep after summarization (as fallback)
            token_counter: token counter function
            summary_prompt: Prompt template for generating summaries
            trim_tokens_to_summarize: Number of messages kept losslessly during Summary
            summary_offload_threshold: During Summary, offload tool call results that exceed this token threshold to the file system
            max_retention_ratio: After Summary is triggered, do not delete messages unless the total exceeds this ratio (relative to trigger). Default is 0.6
        """
        super().__init__()

        if isinstance(model, str):
            model = init_chat_model(model)

        self.model = model
        if trigger is None:
            self.trigger: ContextSize | list[ContextSize] | None = None
            trigger_conditions: list[ContextSize] = []
        elif isinstance(trigger, list):
            validated_list = [self._validate_context_size(item, "trigger") for item in trigger]
            self.trigger = validated_list
            trigger_conditions = validated_list
        else:
            validated = self._validate_context_size(trigger, "trigger")
            self.trigger = validated
            trigger_conditions = [validated]
        self._trigger_conditions = trigger_conditions

        self.keep = self._validate_context_size(keep, "keep")
        if token_counter is count_tokens_approximately:
            self.token_counter = _get_approximate_token_counter(self.model)
        else:
            self.token_counter = token_counter
        self.summary_prompt = summary_prompt
        self.trim_tokens_to_summarize = trim_tokens_to_summarize

        # Tool-result offload configuration
        self.summary_offload_threshold = summary_offload_threshold
        self.max_retention_ratio = max_retention_ratio

        # Check whether a model profile is required for fractional configuration
        requires_profile = any(condition[0] == "fraction" for condition in self._trigger_conditions)
        if self.keep[0] == "fraction":
            requires_profile = True
        if requires_profile and self._get_profile_limits() is None:
            msg = (
                "Model profile information is required to use fractional token limits, "
                "and is unavailable for the specified model. Please use absolute token "
                "counts instead, or pass "
                '`ChatModel(..., profile={"max_input_tokens": ...})`.'
            )
            raise ValueError(msg)

    def _get_token_trigger_value(self) -> int | None:
        """Helper to get the token trigger value."""
        if not self._trigger_conditions:
            return None

        for kind, value in self._trigger_conditions:
            if kind == "tokens":
                return int(value)
            # Support fractional if needed, converting to tokens using profile
            if kind == "fraction":
                max_input_tokens = self._get_profile_limits()
                if max_input_tokens:
                    return int(max_input_tokens * value)
        return None

    @override
    def before_model(self, state: AgentState[Any], runtime: Runtime) -> dict[str, Any] | None:
        """Process messages before model invocation, potentially triggering summarization."""

        messages = state["messages"]

        self._ensure_message_ids(messages)

        total_tokens = self.token_counter(messages)

        # 1. Check whether Summary should be triggered
        if not self._should_summarize(messages, total_tokens):
            return None

        # 2. Trigger Summary: offload tool results that exceed the threshold
        files_update: dict[str, Any] = {}
        modified_messages: list[AnyMessage] = []

        agg_files, agg_msgs = _offload_tool_results(messages, self.summary_offload_threshold, self.token_counter)
        files_update = agg_files
        modified_messages = agg_msgs

        # 3. Check the retention ratio
        current_tokens = self.token_counter(messages)
        trigger_value = self._get_token_trigger_value()

        retention_limit = float("inf")
        if trigger_value:
            retention_limit = trigger_value * self.max_retention_ratio

        if current_tokens <= retention_limit:
            if files_update:
                return {"files": files_update, "messages": modified_messages}
            return None

        # 4. Exceeding the limit requires eviction (Summary)
        system_msg_count = 0
        messages_to_process = messages

        if messages and messages[0].type == "system":
            system_msg_count = 1
            messages_to_process = messages[1:]

        cutoff_relative = self._find_cutoff_by_token_limit(messages_to_process, int(retention_limit))
        cutoff_index = system_msg_count + cutoff_relative

        if cutoff_index <= system_msg_count:
            if files_update:
                return {"files": files_update, "messages": modified_messages}
            return None

        messages_to_summarize, preserved_messages = self._partition_messages(messages, cutoff_index)
        summary = self._create_summary(messages_to_summarize)
        new_messages = self._build_new_messages(summary)

        # If there is a System Message, keep it at the front
        final_messages = []

        if system_msg_count > 0:
            final_messages.append(messages[0])

        final_messages.extend(new_messages)
        final_messages.extend(preserved_messages)

        result: dict[str, Any] = {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *final_messages]}

        if files_update:
            result["files"] = files_update

        return result

    @override
    async def abefore_model(self, state: AgentState[Any], runtime: Runtime) -> dict[str, Any] | None:
        """Process messages before model invocation, potentially triggering summarization."""

        messages = state["messages"]

        self._ensure_message_ids(messages)

        total_tokens = self.token_counter(messages)

        # 1. Check whether Summary should be triggered
        if not self._should_summarize(messages, total_tokens):
            return None

        # 2. Trigger Summary: offload tool results that exceed the threshold
        files_update: dict[str, Any] = {}
        modified_messages: list[AnyMessage] = []

        agg_files, agg_msgs = _offload_tool_results(messages, self.summary_offload_threshold, self.token_counter)
        files_update = agg_files
        modified_messages = agg_msgs

        # 3. Check the retention ratio
        current_tokens = self.token_counter(messages)
        trigger_value = self._get_token_trigger_value()

        retention_limit = float("inf")
        if trigger_value:
            retention_limit = trigger_value * self.max_retention_ratio

        if current_tokens <= retention_limit:
            if files_update:
                return {"files": files_update, "messages": modified_messages}
            return None

        # 4. Exceeding the limit requires eviction (Summary)
        system_msg_count = 0
        messages_to_process = messages

        if messages and messages[0].type == "system":
            system_msg_count = 1
            messages_to_process = messages[1:]

        cutoff_relative = self._find_cutoff_by_token_limit(messages_to_process, int(retention_limit))
        cutoff_index = system_msg_count + cutoff_relative

        if cutoff_index <= system_msg_count:
            if files_update:
                return {"files": files_update, "messages": modified_messages}
            return None

        messages_to_summarize, preserved_messages = self._partition_messages(messages, cutoff_index)

        summary = await self._acreate_summary(messages_to_summarize)
        new_messages = self._build_new_messages(summary)

        final_messages = []

        if system_msg_count > 0:
            final_messages.append(messages[0])

        final_messages.extend(new_messages)
        final_messages.extend(preserved_messages)

        result: dict[str, Any] = {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *final_messages]}

        if files_update:
            result["files"] = files_update

        return result

    def _should_summarize(self, messages: list[AnyMessage], total_tokens: int) -> bool:
        """Determine whether summarization should run for the current token usage."""
        if not self._trigger_conditions:
            return False

        for kind, value in self._trigger_conditions:
            if kind == "messages" and len(messages) >= value:
                return True
            if kind == "tokens" and total_tokens >= value:
                return True
            if kind == "fraction":
                max_input_tokens = self._get_profile_limits()
                if max_input_tokens is None:
                    continue
                threshold = int(max_input_tokens * value)
                if threshold <= 0:
                    threshold = 1
                if total_tokens >= threshold:
                    return True
        return False

    def _determine_cutoff_index(self, messages: list[AnyMessage]) -> int:
        """Choose cutoff index respecting retention configuration."""
        kind, value = self.keep
        if kind in {"tokens", "fraction"}:
            token_based_cutoff = self._find_token_based_cutoff(messages)
            if token_based_cutoff is not None:
                return token_based_cutoff
            return self._find_safe_cutoff(messages, _DEFAULT_MESSAGES_TO_KEEP)
        return self._find_safe_cutoff(messages, cast("int", value))

    def _find_token_based_cutoff(self, messages: list[AnyMessage]) -> int | None:
        """Find cutoff index based on target token retention."""
        if not messages:
            return 0

        kind, value = self.keep
        if kind == "fraction":
            max_input_tokens = self._get_profile_limits()
            if max_input_tokens is None:
                return None
            target_token_count = int(max_input_tokens * value)
        elif kind == "tokens":
            target_token_count = int(value)
        else:
            return None

        if target_token_count <= 0:
            target_token_count = 1

        if self.token_counter(messages) <= target_token_count:
            return 0

        # Binary search
        left, right = 0, len(messages)
        cutoff_candidate = len(messages)
        max_iterations = len(messages).bit_length() + 1
        for _ in range(max_iterations):
            if left >= right:
                break

            mid = (left + right) // 2
            if self.token_counter(messages[mid:]) <= target_token_count:
                cutoff_candidate = mid
                right = mid
            else:
                left = mid + 1

        if cutoff_candidate == len(messages):
            cutoff_candidate = left

        if cutoff_candidate >= len(messages):
            if len(messages) == 1:
                return 0
            cutoff_candidate = len(messages) - 1

        return self._find_safe_cutoff_point(messages, cutoff_candidate)

    def _find_cutoff_by_token_limit(self, messages: list[AnyMessage], max_tokens: int) -> int:
        """Find cutoff index to ensure total tokens <= max_tokens."""
        if not messages or self.token_counter(messages) <= max_tokens:
            return 0

        # Binary search for cutoff
        left, right = 0, len(messages)
        cutoff_candidate = len(messages)
        max_iterations = len(messages).bit_length() + 1

        for _ in range(max_iterations):
            if left >= right:
                break

            mid = (left + right) // 2
            # Calculate tokens for preserved part: messages[mid:]
            if self.token_counter(messages[mid:]) <= max_tokens:
                cutoff_candidate = mid
                right = mid
            else:
                left = mid + 1

        if cutoff_candidate == len(messages):
            cutoff_candidate = left

        return self._find_safe_cutoff_point(messages, cutoff_candidate)

    def _get_profile_limits(self) -> int | None:
        """Retrieve max input token limit from the model profile."""
        try:
            profile = self.model.profile
        except AttributeError:
            return None

        if not isinstance(profile, Mapping):
            return None

        max_input_tokens = profile.get("max_input_tokens")

        if not isinstance(max_input_tokens, int):
            return None

        return max_input_tokens

    @staticmethod
    def _validate_context_size(context: ContextSize, parameter_name: str) -> ContextSize:
        """Validate context configuration tuples."""
        kind, value = context
        if kind == "fraction":
            if not 0 < value <= 1:
                msg = f"Fractional {parameter_name} values must be between 0 and 1, got {value}."
                raise ValueError(msg)
        elif kind in {"tokens", "messages"}:
            if value <= 0:
                msg = f"{parameter_name} thresholds must be greater than 0, got {value}."
                raise ValueError(msg)
        else:
            msg = f"Unsupported context size type {kind} for {parameter_name}."
            raise ValueError(msg)
        return context

    @staticmethod
    def _build_new_messages(summary: str) -> list[HumanMessage]:
        return [
            HumanMessage(
                content=f"Here is a summary of the conversation to date:\n\n{summary}",
                additional_kwargs={"lc_source": "summarization"},
            )
        ]

    @staticmethod
    def _ensure_message_ids(messages: list[AnyMessage]) -> None:
        """Ensure all messages have unique IDs for the add_messages reducer."""
        for msg in messages:
            if msg.id is None:
                msg.id = str(uuid.uuid4())

    @staticmethod
    def _partition_messages(
        conversation_messages: list[AnyMessage],
        cutoff_index: int,
    ) -> tuple[list[AnyMessage], list[AnyMessage]]:
        """Partition messages into those to summarize and those to preserve."""
        messages_to_summarize = conversation_messages[:cutoff_index]
        preserved_messages = conversation_messages[cutoff_index:]

        return messages_to_summarize, preserved_messages

    def _find_safe_cutoff(self, messages: list[AnyMessage], messages_to_keep: int) -> int:
        """Find safe cutoff point that preserves AI/Tool message pairs."""
        if len(messages) <= messages_to_keep:
            return 0

        target_cutoff = len(messages) - messages_to_keep
        return self._find_safe_cutoff_point(messages, target_cutoff)

    @staticmethod
    def _find_safe_cutoff_point(messages: list[AnyMessage], cutoff_index: int) -> int:
        """Find a safe cutoff point that doesn't split AI/Tool message pairs."""
        if cutoff_index >= len(messages) or not isinstance(messages[cutoff_index], ToolMessage):
            return cutoff_index

        tool_call_ids: set[str] = set()
        idx = cutoff_index
        while idx < len(messages) and isinstance(messages[idx], ToolMessage):
            tool_msg = cast("ToolMessage", messages[idx])
            if tool_msg.tool_call_id:
                tool_call_ids.add(tool_msg.tool_call_id)
            idx += 1

        for i in range(cutoff_index - 1, -1, -1):
            msg = messages[i]
            if isinstance(msg, AIMessage) and msg.tool_calls:
                ai_tool_call_ids = {tc.get("id") for tc in msg.tool_calls if tc.get("id")}
                if tool_call_ids & ai_tool_call_ids:
                    return i

        return idx

    def _create_summary(self, messages_to_summarize: list[AnyMessage]) -> str:
        """Generate summary for the given messages."""
        if not messages_to_summarize:
            return "No previous conversation history."

        trimmed_messages = self._trim_messages_for_summary(messages_to_summarize)
        if not trimmed_messages:
            return "Previous conversation was too long to summarize."

        formatted_messages = get_buffer_string(trimmed_messages)

        try:
            response = self.model.invoke(self.summary_prompt.format(messages=formatted_messages))
            return response.text.strip()
        except Exception as e:
            return f"Error generating summary: {e!s}"

    async def _acreate_summary(self, messages_to_summarize: list[AnyMessage]) -> str:
        """Generate summary for the given messages."""
        if not messages_to_summarize:
            return "No previous conversation history."

        trimmed_messages = self._trim_messages_for_summary(messages_to_summarize)
        if not trimmed_messages:
            return "Previous conversation was too long to summarize."

        formatted_messages = get_buffer_string(trimmed_messages)

        try:
            response = await self.model.ainvoke(self.summary_prompt.format(messages=formatted_messages))
            return response.text.strip()
        except Exception as e:
            return f"Error generating summary: {e!s}"

    def _trim_messages_for_summary(self, messages: list[AnyMessage]) -> list[AnyMessage]:
        """Trim messages to fit within summary generation limits."""
        try:
            if self.trim_tokens_to_summarize is None:
                return messages
            return cast(
                "list[AnyMessage]",
                trim_messages(
                    messages,
                    max_tokens=self.trim_tokens_to_summarize,
                    token_counter=self.token_counter,
                    start_on="human",
                    strategy="last",
                    allow_partial=True,
                    include_system=True,
                ),
            )
        except Exception:
            return messages[-_DEFAULT_FALLBACK_MESSAGE_COUNT:]


# Convenience function: create a middleware instance
def create_summary_offload_middleware(
    model: str | BaseChatModel,
    *,
    trigger: ContextSize | list[ContextSize] | None = None,
    keep: ContextSize = ("messages", _DEFAULT_MESSAGES_TO_KEEP),
    summary_offload_threshold: int = 1000,
    max_retention_ratio: float = 0.6,
) -> SummaryOffloadMiddleware:
    """Convenience function for creating a SummaryOffloadMiddleware instance."""
    return SummaryOffloadMiddleware(
        model=model,
        trigger=trigger,
        keep=keep,
        summary_offload_threshold=summary_offload_threshold,
        max_retention_ratio=max_retention_ratio,
    )
