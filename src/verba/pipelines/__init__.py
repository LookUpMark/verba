"""AI pipelines: generation with repair, judge, curriculum, tasks."""

from __future__ import annotations

import json

import jsonschema
from fastapi import HTTPException
from sqlmodel import Session

from ..models import RuntimeRecord
from ..providers.base import Message, provider_for, resolve_roles


def _role_target(session: Session, role: str) -> tuple[str, str, str]:
    """Resolve a role to (runtime_id, endpoint, model_id) or raise 503."""
    roles = resolve_roles(session)
    target = roles.get(role)
    if target is None:
        raise HTTPException(
            status_code=503,
            detail=f"No '{role}' model detected. Start LM Studio or Ollama and POST /api/runtimes/scan.",
        )
    runtime = session.get(RuntimeRecord, target["runtime"])
    if runtime is None:  # pragma: no cover — discovery keeps rows in sync
        raise HTTPException(status_code=503, detail="runtime record missing; run /api/runtimes/scan")
    return runtime.id, runtime.endpoint, target["model"]


def validate_against_schema(payload: object, schema: dict) -> str | None:
    """Validate against the JSON schema; return a repair hint or None when valid."""
    try:
        jsonschema.validate(payload, schema)
        return None
    except jsonschema.ValidationError as e:
        where = "/".join(str(p) for p in e.absolute_path) or "(root)"
        return f"schema violation at {where}: {e.message}"


async def generate_structured(
    session: Session,
    role: str,
    messages: list[Message],
    schema: dict,
    *,
    temperature: float = 0.4,
    max_repair: int = 2,
) -> dict:
    """LLM call constrained to `schema`, validated as JSON, with repair retries.

    Never returns raw model output (architecture.md §5)."""
    runtime_id, endpoint, model = _role_target(session, role)
    provider = provider_for(runtime_id, endpoint, model)
    attempt_messages = list(messages)
    last_error = ""
    for _ in range(max_repair + 1):
        chunks: list[str] = []
        async for chunk in provider.complete(
            attempt_messages, model=model, json_schema=schema, temperature=temperature
        ):
            chunks.append(chunk)
        try:
            parsed = json.loads("".join(chunks))
        except json.JSONDecodeError as e:
            last_error = f"invalid JSON: {e}"
            attempt_messages = attempt_messages + [
                {"role": "user", "content": f"Your reply was not valid JSON ({last_error}). Reply again with JSON only."},
            ]
            continue
        if isinstance(parsed, dict):
            problem = validate_against_schema(parsed, schema)
            if problem is None:
                return parsed
            last_error = problem
            attempt_messages = attempt_messages + [
                {
                    "role": "user",
                    "content": (
                        f"Your reply violated the required schema ({problem}). "
                        "Here is the schema you must satisfy:\n"
                        f"{json.dumps(schema)}\nReply again with a single JSON object that validates."
                    ),
                },
            ]
            continue
        last_error = "reply was not a JSON object"
        attempt_messages = attempt_messages + [
            {"role": "user", "content": "Reply again with a single JSON object."},
        ]
    raise HTTPException(status_code=503, detail=f"model failed structured output after retries: {last_error}")
