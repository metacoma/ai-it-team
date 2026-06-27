from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from .client import OpenHandsError
from .models import JsonDict, RoleSummary, SummaryAttempt

DEFAULT_SUMMARY_INSTRUCTIONS = """You are a strict JSON summary generator for an OpenHands role run.

Summarize the OpenHands answer below as ONE valid JSON object.

Hard requirements:
- Return JSON only.
- Do not use Markdown.
- Do not wrap the JSON in a code fence.
- Do not add any text before or after the JSON.
- The JSON must parse with a standard json.loads parser.
- Use null where a value is unknown.

Required JSON object shape:
{
  "valid": true,
  "status": "completed",
  "summary": "short human-readable summary of the answer",
  "action": null,
  "risk_level": null,
  "blocking": false,
  "blocking_summary": []
}

Field guidance:
- valid: true when this is a valid summary object.
- status: one of "completed", "needs_fix", "blocked", "failed", "unknown".
- summary: concise summary of the answer.
- action: short recommended next action, or null.
- risk_level: one of "low", "medium", "high", "critical", or null.
- blocking: true only if the answer reports a blocker.
- blocking_summary: array of short blocker descriptions, empty array if none.
""".strip()


def build_summary_prompt(
    *,
    answer: str,
    instructions: str = DEFAULT_SUMMARY_INSTRUCTIONS,
    previous_text: str | None = None,
    previous_error: str | None = None,
) -> str:
    if previous_text is None and previous_error is None:
        return f"""{instructions}

OpenHands answer to summarize:
<openhands_answer>
{answer}
</openhands_answer>
""".strip()

    return f"""Your previous response was not valid JSON.

JSON/Pydantic parser error:
{previous_error or "unknown error"}

Previous invalid response:
<invalid_response>
{previous_text or ""}
</invalid_response>

Return a corrected valid JSON object only. Do not include Markdown, code fences, comments, or prose.

Original OpenHands answer to summarize:
<openhands_answer>
{answer}
</openhands_answer>

Original JSON-summary instructions:
{instructions}
""".strip()


def _strip_markdown_fence(text: str) -> str:
    stripped = text.strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", stripped, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else stripped


def _extract_first_json_object(text: str) -> str | None:
    """Extract the first JSON object candidate from an LLM response.

    The primary contract is still "JSON only", but local LLMs sometimes return
    otherwise useful JSON with one of these small formatting defects:
    - a markdown fence;
    - diagnostic prose around the object;
    - a missing final closing brace after a long JSON string.

    This extractor is intentionally conservative: it only returns object-like
    text that starts with "{" and does not attempt to invent missing string
    quotes or repair arbitrary malformed JSON.
    """
    start = text.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escape = False
    last_index = None

    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1].strip()
        last_index = idx

    # Common local-model failure: it emitted one complete top-level object but
    # omitted the final closing brace. Only repair that exact case.
    if depth > 0 and not in_string:
        candidate = text[start:].strip() + ("}" * depth)
        return candidate
    return text[start : last_index + 1].strip() if last_index is not None else None


def _json_decode_error(exc: json.JSONDecodeError) -> str:
    return f"invalid JSON: {exc.msg} at line {exc.lineno} column {exc.colno} char {exc.pos}"


def parse_json_strict(text: str) -> JsonDict | list[Any]:
    """Parse a role summary JSON response.

    The summary prompt requires a whole JSON object, but this parser also accepts
    narrowly recoverable JSON-like responses so a useful OpenHands role run does
    not fail the whole LangGraph workflow because of a missing final brace.
    """
    stripped = _strip_markdown_fence(text)
    if not stripped:
        raise OpenHandsError("summary response is empty, expected JSON")

    errors: list[str] = []
    candidates = [stripped]
    extracted = _extract_first_json_object(stripped)
    if extracted and extracted not in candidates:
        candidates.append(extracted)

    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError as exc:
            errors.append(_json_decode_error(exc))
            continue
        if not isinstance(data, (dict, list)):
            raise OpenHandsError(f"summary JSON must be an object or array, got {type(data).__name__}")
        return data

    detail = errors[-1] if errors else "unknown JSON parse error"
    raise OpenHandsError(detail)


def parse_role_summary(text: str) -> RoleSummary:
    """Parse and validate an LLM summary as the public RoleSummary contract."""
    data = parse_json_strict(text)
    if not isinstance(data, dict):
        raise OpenHandsError(f"summary JSON must be an object for RoleSummary, got {type(data).__name__}")
    try:
        return RoleSummary.model_validate(data)
    except ValidationError as exc:
        raise OpenHandsError(f"summary JSON does not match RoleSummary schema: {exc}") from exc


__all__ = [
    "DEFAULT_SUMMARY_INSTRUCTIONS",
    "JsonDict",
    "RoleSummary",
    "SummaryAttempt",
    "build_summary_prompt",
    "parse_json_strict",
    "parse_role_summary",
]
