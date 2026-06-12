"""Run production GraphRAG questions through the real streaming chat endpoint.

This script is intended to run inside the production API container. It uses the
existing super-admin account and GLOBAL_PASSWORD environment variable, but
never writes credentials or access tokens to the audit output.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any


DEFAULT_QUESTIONS = [
    "Dosen S2 Informatika mana yang menulis paper tentang machine learning di bidang pendidikan?",
    (
        "Metode optimasi apa saja yang dibandingkan dalam penelitian klasifikasi tingkat stres "
        "mahasiswa menggunakan ANN oleh Yuni Yamasari dkk (2024)?"
    ),
    "Apa saja paper yang ditulis oleh Yuni Yamasari?",
    'Siapa saja penulis paper "Optimizing ANN Architecture for Classifying Student Stress Levels"?',
    "Paper apa yang membahas retinopati diabetik dengan EfficientNet dan dataset APTOS?",
    "Dosen mana yang menulis paper tentang student performance dan machine learning?",
    "Apa paper S2 Informatika yang membahas chatbot atau learning style detection?",
    "Paper apa yang menggunakan Optuna dan ensemble learning, serta apa hasil utamanya?",
    "Siapa dosen yang berkolaborasi dengan Ricky Eka Putra dalam publikasi AI atau machine learning?",
    "Topik riset apa saja yang paling sering muncul pada knowledge graph akademik Yunesa?",
]


def request_json(
    url: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 60,
) -> dict[str, Any]:
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def login(api_base: str, username: str, password: str) -> str:
    body = urllib.parse.urlencode({"username": username, "password": password}).encode("utf-8")
    result = request_json(
        f"{api_base}/api/auth/token",
        method="POST",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    token = str(result.get("access_token") or "")
    if not token:
        raise RuntimeError("Production login did not return an access token.")
    return token


def normalize_tool_call(tool_call: Any) -> dict[str, Any]:
    if not isinstance(tool_call, dict):
        return {}
    function = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
    raw_args = tool_call.get("args") or function.get("arguments") or {}
    if isinstance(raw_args, str):
        try:
            raw_args = json.loads(raw_args)
        except json.JSONDecodeError:
            raw_args = {"raw": raw_args[:1000]}
    return {
        "id": tool_call.get("id"),
        "name": tool_call.get("name") or function.get("name"),
        "args": raw_args,
    }


def parse_tool_output(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        payload = content
    elif isinstance(content, str):
        try:
            payload = json.loads(content)
        except json.JSONDecodeError:
            return {"text_preview": content[:2000]}
    else:
        return {"value_type": type(content).__name__}

    if not isinstance(payload, dict):
        return {"value_type": type(payload).__name__}

    academic = payload.get("academic_retrieval") or {}
    graph = payload.get("graph") or {}
    grounding = payload.get("grounding") or {}
    return {
        "type": payload.get("type"),
        "kb_name": payload.get("kb_name"),
        "retrieval_mode": payload.get("retrieval_mode"),
        "found_count": payload.get("found_count"),
        "grounding": grounding,
        "graph_status": graph.get("status") if isinstance(graph, dict) else None,
        "graph_triples": len(graph.get("triples") or []) if isinstance(graph, dict) else 0,
        "paper_chunks": len(academic.get("paper_chunks") or []) if isinstance(academic, dict) else 0,
        "author_publications": (
            len(academic.get("author_publications") or []) if isinstance(academic, dict) else 0
        ),
        "publication_details": (
            len(academic.get("publication_details") or []) if isinstance(academic, dict) else 0
        ),
        "lecturer_topic_publications": (
            len(academic.get("lecturer_topic_publications") or [])
            if isinstance(academic, dict)
            else 0
        ),
        "topic_frequencies": (
            len(academic.get("topic_frequencies") or []) if isinstance(academic, dict) else 0
        ),
        "collaborations": (
            len(academic.get("collaborations") or []) if isinstance(academic, dict) else 0
        ),
        "keywords": len(academic.get("keywords") or []) if isinstance(academic, dict) else 0,
        "entities": len(academic.get("entities") or []) if isinstance(academic, dict) else 0,
        "relationships": (
            len(academic.get("relationships") or []) if isinstance(academic, dict) else 0
        ),
        "context_preview": str(payload.get("context") or "")[:3000],
    }


def audit_question(
    api_base: str,
    token: str,
    question: str,
    *,
    agent_config_id: int,
    timeout: float,
) -> dict[str, Any]:
    request_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    request_body = json.dumps(
        {
            "query": question,
            "agent_config_id": agent_config_id,
            "thread_id": thread_id,
            "meta": {
                "request_id": request_id,
                "audit": "production_graphrag",
            },
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{api_base}/api/chat/agent",
        data=request_body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )

    started = time.perf_counter()
    status_counts: Counter[str] = Counter()
    message_type_counts: Counter[str] = Counter()
    event_count = 0
    answer_chunk_count = 0
    tool_calls: list[dict[str, Any]] = []
    tool_outputs: list[dict[str, Any]] = []
    answer_parts: list[str] = []
    first_tool_seconds: float | None = None
    first_answer_seconds: float | None = None
    error: dict[str, Any] | None = None

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                elapsed = round(time.perf_counter() - started, 3)
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    status_counts["invalid_json"] += 1
                    event_count += 1
                    continue

                status = event.get("status")
                msg = event.get("msg") if isinstance(event.get("msg"), dict) else {}
                msg_type = msg.get("type")
                content = msg.get("content")
                event_tool_calls = msg.get("tool_calls") or []
                event_count += 1
                status_counts[str(status or "unknown")] += 1
                if msg_type:
                    message_type_counts[str(msg_type)] += 1

                if event_tool_calls:
                    if first_tool_seconds is None:
                        first_tool_seconds = elapsed
                    for tool_call in event_tool_calls:
                        normalized = normalize_tool_call(tool_call)
                        if normalized and normalized not in tool_calls:
                            tool_calls.append(normalized)

                if msg_type == "tool":
                    if first_tool_seconds is None:
                        first_tool_seconds = elapsed
                    tool_outputs.append(
                        {
                            "elapsed_seconds": elapsed,
                            "name": msg.get("name"),
                            "tool_call_id": msg.get("tool_call_id"),
                            "output": parse_tool_output(content),
                        }
                    )
                elif isinstance(content, str) and content:
                    if msg_type in {"ai", "AIMessageChunk"} or status == "loading":
                        if first_answer_seconds is None:
                            first_answer_seconds = elapsed
                        answer_parts.append(content)
                        answer_chunk_count += 1
                elif isinstance(event.get("response"), str) and event.get("response"):
                    if first_answer_seconds is None:
                        first_answer_seconds = elapsed
                    answer_parts.append(event["response"])
                    answer_chunk_count += 1

                if status == "error":
                    error = {
                        "error_type": event.get("error_type"),
                        "error_message": event.get("error_message"),
                    }

    except urllib.error.HTTPError as exc:
        error = {"http_status": exc.code, "message": exc.read().decode("utf-8", errors="replace")}
    except Exception as exc:  # noqa: BLE001
        error = {"type": type(exc).__name__, "message": str(exc)}

    duration = round(time.perf_counter() - started, 3)
    answer = "".join(answer_parts).strip()
    return {
        "question": question,
        "request_id": request_id,
        "thread_id": thread_id,
        "duration_seconds": duration,
        "first_tool_seconds": first_tool_seconds,
        "first_answer_seconds": first_answer_seconds,
        "event_count": event_count,
        "status_counts": dict(status_counts),
        "message_type_counts": dict(message_type_counts),
        "answer_chunk_count": answer_chunk_count,
        "tool_calls": tool_calls,
        "tool_outputs": tool_outputs,
        "answer": answer,
        "answer_chars": len(answer),
        "error": error,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base", default="http://127.0.0.1:5050")
    parser.add_argument("--username", default=os.getenv("YUNESA_AUDIT_USER", "rizkyyanuark"))
    parser.add_argument("--agent-config-id", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=240)
    parser.add_argument("--output", type=Path, default=Path("/tmp/yunesa_graphrag_audit.json"))
    parser.add_argument("--limit", type=int, default=len(DEFAULT_QUESTIONS))
    args = parser.parse_args()

    password = os.getenv("GLOBAL_PASSWORD")
    if not password:
        raise RuntimeError("GLOBAL_PASSWORD is required in the production container environment.")

    token = login(args.api_base.rstrip("/"), args.username, password)
    results: list[dict[str, Any]] = []
    for index, question in enumerate(DEFAULT_QUESTIONS[: max(1, args.limit)], start=1):
        print(f"[{index}/{min(args.limit, len(DEFAULT_QUESTIONS))}] {question}", flush=True)
        result = audit_question(
            args.api_base.rstrip("/"),
            token,
            question,
            agent_config_id=args.agent_config_id,
            timeout=args.timeout,
        )
        results.append(result)
        tools = [tool.get("name") for tool in result["tool_calls"] if tool.get("name")]
        print(
            json.dumps(
                {
                    "duration_seconds": result["duration_seconds"],
                    "first_tool_seconds": result["first_tool_seconds"],
                    "first_answer_seconds": result["first_answer_seconds"],
                    "tools": tools,
                    "answer_chars": result["answer_chars"],
                    "error": result["error"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    report = {
        "generated_at_epoch": time.time(),
        "api_base": args.api_base,
        "agent_config_id": args.agent_config_id,
        "question_count": len(results),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Audit written to {args.output}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
