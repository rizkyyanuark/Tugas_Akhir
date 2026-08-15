import os
import traceback

from langchain.chat_models import BaseChatModel, init_chat_model
from pydantic import SecretStr

from yunesa import config
from yunesa.utils import get_docker_safe_url
from yunesa.utils.logging_config import logger


def load_chat_model(fully_specified_name: str, **kwargs) -> BaseChatModel:
    """
    Load a chat model from a fully specified name.
    """
    provider, model = fully_specified_name.split("/", maxsplit=1)

    assert provider != "custom", "[Deprecated] Custom models were removed; please configure them in yunesa/config/static/models.py"

    model_info = config.model_names.get(provider)
    if not model_info:
        raise ValueError(f"Unknown model provider: {provider}")

    env_var = model_info.env

    api_key = os.getenv(env_var) or env_var

    base_url = get_docker_safe_url(model_info.base_url)

    if provider in ["openai", "deepseek"]:
        model_spec = f"{provider}:{model}"
        logger.debug(
            f"[offical] Loading model {model_spec} with kwargs {kwargs}")
        if "api_key" not in kwargs and api_key and not api_key.endswith("_API_KEY"):
            kwargs["api_key"] = SecretStr(api_key)
        if "base_url" not in kwargs and base_url:
            kwargs["base_url"] = base_url
        return init_chat_model(model_spec, **kwargs)

    elif provider in ["dashscope"]:
        from langchain_deepseek import ChatDeepSeek

        return ChatDeepSeek(
            model=model,
            api_key=SecretStr(api_key),
            base_url=base_url,
            api_base=base_url,
            stream_usage=True,
        )

    else:
        # Other providers default to OpenAI-compatible backend (e.g. openai, zhipuai, gemini)
        try:
            import langchain_openai.chat_models.base as langchain_openai_base
            from langchain_openai import ChatOpenAI
            from langchain_core.messages import AIMessage

            # Patch langchain_openai to preserve Gemini's thought_signature metadata in multi-turn tool calls
            if not getattr(langchain_openai_base, "_gemini_thought_patched", False):
                orig_convert_dict = langchain_openai_base._convert_dict_to_message
                orig_convert_msg = langchain_openai_base._convert_message_to_dict

                orig_convert_dict = langchain_openai_base._convert_dict_to_message
                orig_convert_delta = langchain_openai_base._convert_delta_to_message_chunk
                orig_convert_msg = langchain_openai_base._convert_message_to_dict

                def patched_convert_dict_to_message(_dict, *args, **kwargs):
                    msg = orig_convert_dict(_dict, *args, **kwargs)
                    raw_tool_calls = _dict.get("tool_calls") or []
                    if isinstance(msg, AIMessage) and raw_tool_calls:
                        extra_map = {}
                        for raw_tc in raw_tool_calls:
                            if isinstance(raw_tc, dict) and "extra_content" in raw_tc:
                                tc_id = raw_tc.get("id")
                                if tc_id:
                                    extra_map[tc_id] = raw_tc["extra_content"]
                        if extra_map:
                            msg.additional_kwargs["_extra_content_map"] = extra_map
                    return msg

                def patched_convert_delta_to_message_chunk(_dict, default_class, *args, **kwargs):
                    chunk = orig_convert_delta(_dict, default_class, *args, **kwargs)
                    raw_tool_calls = _dict.get("tool_calls") or []
                    if raw_tool_calls:
                        extra_map = getattr(chunk, "additional_kwargs", {}).get("_extra_content_map", {})
                        for raw_tc in raw_tool_calls:
                            if isinstance(raw_tc, dict) and "extra_content" in raw_tc:
                                tc_id = raw_tc.get("id")
                                if tc_id:
                                    extra_map[tc_id] = raw_tc["extra_content"]
                        if extra_map and hasattr(chunk, "additional_kwargs"):
                            chunk.additional_kwargs["_extra_content_map"] = extra_map
                    return chunk

                def patched_convert_message_to_dict(message):
                    res_dict = orig_convert_msg(message)
                    if isinstance(message, AIMessage) and "tool_calls" in res_dict:
                        extra_map = message.additional_kwargs.get("_extra_content_map", {})
                        if extra_map:
                            for tc_dict in res_dict["tool_calls"]:
                                tc_id = tc_dict.get("id")
                                if tc_id and tc_id in extra_map:
                                    tc_dict["extra_content"] = extra_map[tc_id]
                    return res_dict

                langchain_openai_base._convert_dict_to_message = patched_convert_dict_to_message
                langchain_openai_base._convert_delta_to_message_chunk = patched_convert_delta_to_message_chunk
                langchain_openai_base._convert_message_to_dict = patched_convert_message_to_dict
                langchain_openai_base._gemini_thought_patched = True

            return ChatOpenAI(
                model=model,
                api_key=SecretStr(api_key),
                base_url=base_url,
                stream_usage=True,
            )
        except Exception as e:
            raise ValueError(
                f"Model provider {provider} load failed, {e} \n {traceback.format_exc()}")

