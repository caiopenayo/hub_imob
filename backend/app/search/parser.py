from __future__ import annotations

import json
import re
from json import JSONDecodeError
from typing import Any

from pydantic import ValidationError

from .exceptions import SearchIntentParsingError, SearchIntentValidationError
from .schemas import SearchIntent


JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", flags=re.IGNORECASE | re.DOTALL)


def parse_search_intent_output(output: str) -> SearchIntent:
    if not isinstance(output, str) or not output.strip():
        raise SearchIntentParsingError("model output is empty")

    candidates = _candidate_json_strings(output)
    last_decode_error: Exception | None = None
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except JSONDecodeError as exc:
            last_decode_error = exc
            continue
        return validate_search_intent_payload(payload)

    message = "model output does not contain a valid JSON object"
    if last_decode_error:
        message = f"{message}: {last_decode_error}"
    raise SearchIntentParsingError(message)


def validate_search_intent_payload(payload: Any) -> SearchIntent:
    if not isinstance(payload, dict):
        raise SearchIntentValidationError("search intent JSON must be an object")
    try:
        return SearchIntent.model_validate(payload)
    except ValidationError as exc:
        raise SearchIntentValidationError(str(exc)) from exc


def _candidate_json_strings(output: str) -> list[str]:
    text = output.strip()
    candidates: list[str] = []
    candidates.append(_strip_single_json_fence(text))

    for match in JSON_FENCE_RE.finditer(text):
        fenced = match.group(1).strip()
        if fenced and fenced not in candidates:
            candidates.append(fenced)

    extracted = _extract_first_top_level_json_object(text)
    if extracted and extracted not in candidates:
        candidates.append(extracted)
    return candidates


def _strip_single_json_fence(text: str) -> str:
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else text


def _extract_first_top_level_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_string:
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None
