import os
import traceback
import uuid
from pathlib import Path
from typing import Annotated, Any

import requests
from langchain.tools import InjectedToolCallId
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolRuntime
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

from ta_backend_core.assistant import config, graph_base
from ta_backend_core.assistant.agents.toolkits.registry import ToolExtraMetadata, _all_tool_instances, _extra_registry, tool
from ta_backend_core.assistant.storage.minio import aupload_file_to_minio
from ta_backend_core.assistant.utils import logger
from ta_backend_core.assistant.utils.paths import VIRTUAL_PATH_OUTPUTS
from ta_backend_core.assistant.utils.question_utils import normalize_questions

# Lazy initialization for TavilySearch (only when API key is available)
_tavily_search_instance = None

QWEN_IMAGE_CONFIG_GUIDE = """
Before using this tool, configure the SiliconFlow image generation credentials.

Please configure the following environment variable in the backend runtime environment:
- `SILICONFLOW_API_KEY`: used to call the SiliconFlow image generation API

Once configured, you can use this tool to generate images.
""".strip()


def _create_tavily_search():
    """Create and register TavilySearch tool with metadata."""
    global _tavily_search_instance
    if _tavily_search_instance is None:
        from langchain_tavily import TavilySearch

        _tavily_search_instance = TavilySearch()

    return _tavily_search_instance


# Register the TavilySearch tool (lazy initialization)
def _register_tavily_tool():
    """Register TavilySearch tool with extra metadata."""
    tavily_instance = _create_tavily_search()
    # Manually register it in the global registry
    _extra_registry["tavily_search"] = ToolExtraMetadata(
        category="buildin",
        tags=["search"],
        display_name="Tavily Web Search",
    )
    # Add it to the tool instance list
    _all_tool_instances.append(tavily_instance)


# Register on module import
if config.enable_web_search:
    try:
        _register_tavily_tool()
    except Exception as e:
        logger.warning(f"Failed to register TavilySearch tool: {e}")


class PresentArtifactsInput(BaseModel):
    """Expose artifact files to the frontend after the agent finishes."""

    filepaths: list[str] = Field(description=f"List of absolute file paths to show to the user; only files under {VIRTUAL_PATH_OUTPUTS} are allowed")


def _normalize_presented_artifact_path(filepath: str, runtime: ToolRuntime) -> str:
    from ta_backend_core.assistant.agents.backends.sandbox.paths import (
        VIRTUAL_PATH_PREFIX,
        ensure_thread_dirs,
        resolve_virtual_path,
        sandbox_outputs_dir,
    )

    outputs_virtual_prefix = f"{VIRTUAL_PATH_PREFIX}/outputs"
    runtime_context = runtime.context
    thread_id = getattr(runtime_context, "thread_id", None)
    if not thread_id:
        raise ValueError("The current runtime is missing thread_id")
    user_id = getattr(runtime_context, "user_id", None)
    if not user_id:
        raise ValueError("The current runtime is missing user_id")

    ensure_thread_dirs(thread_id, str(user_id))
    outputs_dir = sandbox_outputs_dir(thread_id).resolve()
    normalized_input = str(filepath or "").strip()
    if not normalized_input:
        raise ValueError("File path cannot be empty")

    stripped = normalized_input.lstrip("/")
    virtual_prefix = VIRTUAL_PATH_PREFIX.lstrip("/")
    if stripped == virtual_prefix or stripped.startswith(f"{virtual_prefix}/"):
        actual_path = resolve_virtual_path(thread_id, normalized_input, user_id=str(user_id))
    else:
        actual_path = Path(normalized_input).expanduser().resolve()

    if not actual_path.exists() or not actual_path.is_file():
        raise ValueError(f"File does not exist or is not a regular file: {normalized_input}")

    try:
        relative_path = actual_path.relative_to(outputs_dir)
    except ValueError as exc:
        raise ValueError(f"Only files under {outputs_virtual_prefix}/ are allowed: {normalized_input}") from exc

    return f"{outputs_virtual_prefix}/{relative_path.as_posix()}"


@tool(category="buildin", tags=["math"], display_name="Calculator")
def calculator(a: float, b: float, operation: str) -> float:
    """Calculator: perform basic arithmetic on two numbers"""
    try:
        if operation == "add":
            return a + b
        elif operation == "subtract":
            return a - b
        elif operation == "multiply":
            return a * b
        elif operation == "divide":
            if b == 0:
                raise ZeroDivisionError("The divisor cannot be zero")
            return a / b
        else:
            raise ValueError(f"Unsupported operation type: {operation}. Only add, subtract, multiply, and divide are supported")
    except Exception as e:
        logger.error(f"Calculator error: {e}")
        raise


PRESENT_ARTIFACTS_DESCRIPTION = f"""
Show already generated result files to the user.

Use cases:
1. You have already written the final result files under `{VIRTUAL_PATH_OUTPUTS}`
2. You want the frontend to display result file cards after the conversation ends
3. These files should support download or preview

Notes:
1. Only files under `{VIRTUAL_PATH_OUTPUTS}` may be passed in
2. Do not pass intermediate files; call this only for final files that should be shown to the user
3. Multiple files can be passed at once
"""


@tool(
    category="buildin",
    tags=["file", "artifact"],
    display_name="Show Artifacts",
    description=PRESENT_ARTIFACTS_DESCRIPTION,
    args_schema=PresentArtifactsInput,
)
def present_artifacts(
    filepaths: list[str],
    runtime: ToolRuntime,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Register artifact files under the current thread's outputs directory so the frontend can show them after the conversation ends."""
    try:
        normalized_paths = [_normalize_presented_artifact_path(filepath, runtime) for filepath in filepaths]
    except ValueError as exc:
        return Command(update={"messages": [ToolMessage(content=f"Error: {exc}", tool_call_id=tool_call_id)]})

    return Command(
        update={
            "artifacts": normalized_paths,
            "messages": [ToolMessage(content="Artifacts have been shown to the user", tool_call_id=tool_call_id)],
        }
    )


ASK_USER_QUESTION_DESCRIPTION = """
Use this tool to ask the user questions when you need a decision or additional requirements during execution.

Applicable scenarios:
1. Collect user preferences or requirements (for example style, scope, priority)
2. Clarify ambiguous instructions (when multiple reasonable interpretations exist)
3. Let the user choose a direction during implementation
4. Ask the user to make tradeoffs when there are clear compromises

Usage rules:
1. questions should provide 1-5 questions, each containing: question, options, multi_select, allow_other
2. Each question's options should provide 2-5 distinct choices, each containing label and value
3. If there is a recommended option: put it first and add "(Recommended)" to the end of the label
4. If multiple selection is needed: set multi_select to true for that question
5. allow_other should usually remain true so the user can provide a custom answer via Other

Notes:
1. Do not use this tool to ask workflow-control questions like "should we continue" or "is the plan ready"
2. Do not abuse this tool when there is already enough information and no user decision is needed
3. Make decisions based on the current context first; only ask questions when there is key uncertainty

Return value:
answer is an object in the format {question_id: answer}.
The answer may be a string (single choice), list (multi-choice), or object (Other text).
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
        "Question list; each item follows the format {question, options, multi_select, allow_other, question_id(optional)}",
    ] = None,
    question: Annotated[str, "Compatibility field: single question text (prefer using questions)"] = "",
    options: Annotated[list[dict] | str | None, "Compatibility field: single question options (prefer using questions)"] = None,
    multi_select: Annotated[bool, "Compatibility field: whether the single question allows multiple selections"] = False,
    allow_other: Annotated[bool, "Compatibility field: whether the single question allows a custom Other answer"] = True,
) -> dict:
    """Ask the user a question and wait for a response."""
    # Parse the options parameter: if it's a string, try to parse it as JSON
    if isinstance(options, str):
        try:
            import json

            options = json.loads(options)
                logger.debug(f"Parsed string options to list: {options}")
        except Exception as e:
                logger.error(f"Failed to parse options string: {e}, using empty list")
            options = []

            # Parse the questions parameter: if it's a string, try to parse it as JSON
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
Use this tool to query triple information in the knowledge graph.
For the keyword (query), use keywords that are likely to help answer the question and do not query directly with the user's original input.
"""


@tool(category="buildin", tags=["graph"], display_name="Query Knowledge Graph", description=KG_QUERY_DESCRIPTION)
def query_knowledge_graph(query: Annotated[str, "The keyword to query knowledge graph."]) -> Any:
    """Use this tool to query triple information in the knowledge graph. For the keyword (query), use keywords that are likely to help answer the question and do not query directly with the user's original input."""
    try:
        logger.debug(f"Querying knowledge graph with: {query}")
        result = graph_base.query_node(query, hops=2, return_format="triples")
        logger.debug(
            f"Knowledge graph query returned "
            f"{len(result.get('triples', [])) if isinstance(result, dict) else 'N/A'} triples"
        )
        return result
    except Exception as e:
        logger.error(f"Knowledge graph query error: {e}, {traceback.format_exc()}")
        return f"Knowledge graph query failed: {str(e)}"


@tool(
    category="buildin",
    tags=["image", "generation"],
    display_name="Qwen-Image",
    config_guide=QWEN_IMAGE_CONFIG_GUIDE,
)
async def text_to_img_qwen_image(
    prompt: Annotated[str, "Text description used to generate the image"],
    negative_prompt: Annotated[str, "Negative prompt used to specify elements that should not appear in the image"] = "",
    num_inference_steps: Annotated[int, "Inference steps, range 1-100"] = 20,
    guidance_scale: Annotated[float, "Guidance scale controlling how closely the image follows the prompt"] = 7.5,
    user_id: Annotated[str, "User ID used for the image archive path"] = "unknown",
) -> str:
    """Generate an image with the Qwen-Image model and return the image URL. Note that the generated result is not displayed by default and the returned URL must be handled for display."""
    url = "https://api.siliconflow.cn/v1/images/generations"

    payload = {
        "model": "Qwen/Qwen-Image",
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "num_inference_steps": num_inference_steps,
        "guidance_scale": guidance_scale,
    }
    headers = {"Authorization": f"Bearer {os.getenv('SILICONFLOW_API_KEY')}", "Content-Type": "application/json"}

    try:
        response = requests.post(url, json=payload, headers=headers)
        response_json = response.json()
    except Exception as e:
        logger.error(f"Failed to generate image with: {e}")
        raise ValueError(f"Image generation failed: {e}")

    try:
        image_url = response_json["images"][0]["url"]
    except (KeyError, IndexError, TypeError) as e:
        logger.error(f"Failed to parse image URL from response: {e}, {response_json=}")
        raise ValueError(f"Image URL extraction failed: {e}")

    # Upload to MinIO
    response = requests.get(image_url)
    file_data = response.content

    safe_user_id = str(user_id or "unknown").replace("/", "_").replace("\\", "_")
    file_name = f"user/{safe_user_id}/generated-images/{uuid.uuid4()}.jpg"
    image_url = await aupload_file_to_minio(bucket_name="public", file_name=file_name, data=file_data)
    logger.info(f"Image uploaded. URL: {image_url}")
    return image_url
