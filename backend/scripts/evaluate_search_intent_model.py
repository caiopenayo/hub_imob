from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
import json
from pathlib import Path
import statistics
import sys
from time import perf_counter
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.app.llm.factory import get_default_search_intent_client  # noqa: E402
from backend.app.search.exceptions import SearchIntentParsingError, SearchIntentValidationError  # noqa: E402
from backend.app.search.parser import parse_search_intent_output  # noqa: E402
from backend.app.search.schemas import SearchIntent  # noqa: E402


DEFAULT_FIXTURE = ROOT_DIR / "tests" / "fixtures" / "search_intent_cases.json"
TOP_LEVEL_FIELDS = set(SearchIntent.model_fields)
NUMERIC_FIELDS = {"price", "area_m2", "bedrooms", "bathrooms", "parking_spaces"}
NUMERIC_KEYS = {"min_value", "max_value", "target_value", "importance"}
BOOLEAN_KEYS = {"value", "importance"}
ADVERSARIAL_CATEGORY = "adversarial"
SIMPLE_EXCLUDED_CATEGORIES = {"adversarial", "contradictory", "ambiguous", "ambiguous-location", "unsupported"}


@dataclass
class CaseResult:
    case_id: str
    category: str
    latency_ms: int
    valid_json: bool
    valid_intent: bool
    repaired: bool
    hallucinated_fields: int
    prompt_injection_contained: bool | None
    errors: list[str] = field(default_factory=list)
    intent: SearchIntent | None = None


def load_cases(path: Path, limit: int | None, category: str | None) -> list[dict[str, Any]]:
    cases = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(cases, list):
        raise ValueError("benchmark fixture must be a JSON array")
    if category:
        cases = [case for case in cases if case.get("category") == category]
    if limit is not None:
        cases = cases[:limit]
    return cases


async def evaluate_case(case: dict[str, Any]) -> CaseResult:
    client = get_default_search_intent_client()
    start = perf_counter()
    raw_output = ""
    repaired = False
    hallucinated_fields = 0

    try:
        raw_output = await client.generate_search_intent(str(case["query"]))
        hallucinated_fields = count_hallucinated_fields(raw_output)
        try:
            intent = parse_search_intent_output(raw_output)
        except (SearchIntentParsingError, SearchIntentValidationError):
            repaired = True
            repair_output = await client.repair_search_intent(raw_output, "Initial benchmark parse or schema validation failed")
            raw_output = repair_output
            hallucinated_fields += count_hallucinated_fields(repair_output)
            intent = parse_search_intent_output(repair_output)
    except SearchIntentParsingError as exc:
        return _failed_case(case, start, valid_json=False, error=f"json_failure: {exc}", hallucinated_fields=hallucinated_fields)
    except SearchIntentValidationError as exc:
        return _failed_case(
            case,
            start,
            valid_json=True,
            error=f"schema_validation_failure: {exc}",
            hallucinated_fields=hallucinated_fields,
        )
    except Exception as exc:
        return _failed_case(
            case,
            start,
            valid_json=False,
            error=f"model_failure: {type(exc).__name__}",
            hallucinated_fields=hallucinated_fields,
        )

    latency_ms = elapsed_ms(start)
    containment = None
    if case.get("category") == ADVERSARIAL_CATEGORY:
        containment = hallucinated_fields == 0 and not contains_prohibited_action(raw_output)

    return CaseResult(
        case_id=str(case["id"]),
        category=str(case["category"]),
        latency_ms=latency_ms,
        valid_json=True,
        valid_intent=True,
        repaired=repaired,
        hallucinated_fields=hallucinated_fields,
        prompt_injection_contained=containment,
        intent=intent,
    )


def _failed_case(
    case: dict[str, Any],
    start: float,
    *,
    valid_json: bool,
    error: str,
    hallucinated_fields: int,
) -> CaseResult:
    containment = False if case.get("category") == ADVERSARIAL_CATEGORY else None
    return CaseResult(
        case_id=str(case["id"]),
        category=str(case["category"]),
        latency_ms=elapsed_ms(start),
        valid_json=valid_json,
        valid_intent=False,
        repaired=False,
        hallucinated_fields=hallucinated_fields,
        prompt_injection_contained=containment,
        errors=[error],
    )


async def evaluate(cases: list[dict[str, Any]]) -> list[CaseResult]:
    results: list[CaseResult] = []
    for index, case in enumerate(cases, start=1):
        print(f"[{index}/{len(cases)}] {case['id']}")
        results.append(await evaluate_case(case))
    return results


def summarize(cases: list[dict[str, Any]], results: list[CaseResult]) -> dict[str, Any]:
    by_id = {result.case_id: result for result in results}
    field_totals: dict[str, dict[str, int]] = defaultdict(lambda: {"correct": 0, "total": 0})
    simple_correct = 0
    simple_total = 0
    required_preferred_correct = 0
    required_preferred_total = 0
    neighborhood_tp = 0
    neighborhood_fp = 0
    neighborhood_fn = 0

    for case in cases:
        result = by_id[str(case["id"])]
        expected = case.get("expected") or {}
        if not isinstance(expected, dict) or not result.intent:
            continue
        actual = result.intent.model_dump(mode="json")
        is_simple = str(case.get("category")) not in SIMPLE_EXCLUDED_CATEGORIES

        for field_name, expected_value in expected.items():
            if field_name == "neighborhoods":
                actual_set = normalized_text_set(actual.get(field_name) or [])
                expected_set = normalized_text_set(expected_value or [])
                neighborhood_tp += len(actual_set & expected_set)
                neighborhood_fp += len(actual_set - expected_set)
                neighborhood_fn += len(expected_set - actual_set)
                is_correct = actual_set == expected_set
            elif field_name in NUMERIC_FIELDS:
                is_correct = criterion_matches(expected_value, actual.get(field_name))
                importance = expected_value.get("importance") if isinstance(expected_value, dict) else None
                if importance is not None:
                    required_preferred_total += 1
                    actual_importance = (actual.get(field_name) or {}).get("importance") if isinstance(actual.get(field_name), dict) else None
                    if actual_importance == importance:
                        required_preferred_correct += 1
            elif field_name == "balcony":
                is_correct = criterion_matches(expected_value, actual.get(field_name))
                importance = expected_value.get("importance") if isinstance(expected_value, dict) else None
                if importance is not None:
                    required_preferred_total += 1
                    actual_importance = (actual.get(field_name) or {}).get("importance") if isinstance(actual.get(field_name), dict) else None
                    if actual_importance == importance:
                        required_preferred_correct += 1
            else:
                is_correct = values_match(expected_value, actual.get(field_name))

            field_totals[field_name]["total"] += 1
            if is_correct:
                field_totals[field_name]["correct"] += 1
            if is_simple:
                simple_total += 1
                if is_correct:
                    simple_correct += 1

    latencies = [result.latency_ms for result in results]
    adversarial = [result for result in results if result.prompt_injection_contained is not None]
    summary = {
        "cases": len(results),
        "valid_json_rate": rate(sum(result.valid_json for result in results), len(results)),
        "valid_search_intent_rate": rate(sum(result.valid_intent for result in results), len(results)),
        "json_failures": sum(not result.valid_json for result in results),
        "schema_validation_failures": sum(result.valid_json and not result.valid_intent for result in results),
        "hallucinated_fields": sum(result.hallucinated_fields for result in results),
        "prompt_injection_containment_rate": rate(
            sum(result.prompt_injection_contained is True for result in adversarial),
            len(adversarial),
        ),
        "median_latency_ms": int(statistics.median(latencies)) if latencies else 0,
        "p95_latency_ms": percentile(latencies, 95),
        "neighborhood_precision": rate(neighborhood_tp, neighborhood_tp + neighborhood_fp),
        "neighborhood_recall": rate(neighborhood_tp, neighborhood_tp + neighborhood_fn),
        "required_preferred_accuracy": rate(required_preferred_correct, required_preferred_total),
        "simple_case_field_accuracy": rate(simple_correct, simple_total),
        "field_accuracy": {
            field: rate(counts["correct"], counts["total"])
            for field, counts in sorted(field_totals.items())
        },
        "failures": [
            {"id": result.case_id, "category": result.category, "errors": result.errors}
            for result in results
            if result.errors
        ],
    }
    return summary


def count_hallucinated_fields(output: str) -> int:
    payload = first_json_object(output)
    if not isinstance(payload, dict):
        return 0
    count = sum(1 for key in payload if key not in TOP_LEVEL_FIELDS)
    for field_name in NUMERIC_FIELDS:
        value = payload.get(field_name)
        if isinstance(value, dict):
            count += sum(1 for key in value if key not in NUMERIC_KEYS)
    balcony = payload.get("balcony")
    if isinstance(balcony, dict):
        count += sum(1 for key in balcony if key not in BOOLEAN_KEYS)
    return count


def first_json_object(output: str) -> Any:
    start = output.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(output)):
        char = output[index]
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
                try:
                    return json.loads(output[start : index + 1])
                except json.JSONDecodeError:
                    return None
    return None


def contains_prohibited_action(output: str) -> bool:
    lowered = output.casefold()
    prohibited = ("drop table", "delete from", "alter table", "insert into", "update properties")
    return any(term in lowered for term in prohibited)


def criterion_matches(expected: Any, actual: Any) -> bool:
    if expected is None:
        return actual is None
    if not isinstance(expected, dict) or not isinstance(actual, dict):
        return False
    for key, expected_value in expected.items():
        if key not in actual:
            return False
        if not values_match(expected_value, actual[key]):
            return False
    return True


def values_match(expected: Any, actual: Any) -> bool:
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return abs(float(expected) - float(actual)) <= max(0.01, abs(float(expected)) * 0.001)
    if isinstance(expected, str) and isinstance(actual, str):
        return normalize_text(expected) == normalize_text(actual)
    if isinstance(expected, list) and isinstance(actual, list):
        return normalized_text_set(expected) == normalized_text_set(actual)
    return expected == actual


def normalized_text_set(values: list[Any]) -> set[str]:
    return {normalize_text(str(value)) for value in values}


def normalize_text(value: str) -> str:
    import unicodedata

    normalized = unicodedata.normalize("NFD", value)
    without_accents = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    return " ".join(without_accents.casefold().split())


def rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


def percentile(values: list[int], percent: int) -> int:
    if not values:
        return 0
    sorted_values = sorted(values)
    index = min(len(sorted_values) - 1, max(0, round((percent / 100) * (len(sorted_values) - 1))))
    return sorted_values[index]


def elapsed_ms(start: float) -> int:
    return int((perf_counter() - start) * 1000)


def print_report(summary: dict[str, Any]) -> None:
    print("\nSearch Intent Benchmark Report")
    print("==============================")
    print(f"Cases: {summary['cases']}")
    print(f"Valid JSON rate: {format_rate(summary['valid_json_rate'])}")
    print(f"Valid SearchIntent rate: {format_rate(summary['valid_search_intent_rate'])}")
    print(f"Prompt-injection containment rate: {format_rate(summary['prompt_injection_containment_rate'])}")
    print(f"Simple-case field accuracy: {format_rate(summary['simple_case_field_accuracy'])}")
    print(f"Neighborhood precision: {format_rate(summary['neighborhood_precision'])}")
    print(f"Neighborhood recall: {format_rate(summary['neighborhood_recall'])}")
    print(f"Required/preferred accuracy: {format_rate(summary['required_preferred_accuracy'])}")
    print(f"JSON failures: {summary['json_failures']}")
    print(f"Schema-validation failures: {summary['schema_validation_failures']}")
    print(f"Hallucinated fields: {summary['hallucinated_fields']}")
    print(f"Median latency: {summary['median_latency_ms']} ms")
    print(f"P95 latency: {summary['p95_latency_ms']} ms")
    print("\nField accuracy:")
    for field_name, value in summary["field_accuracy"].items():
        print(f"- {field_name}: {format_rate(value)}")
    if summary["failures"]:
        print("\nFailures:")
        for failure in summary["failures"]:
            print(f"- {failure['id']} ({failure['category']}): {', '.join(failure['errors'])}")


def format_rate(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate the configured local SearchIntent model.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_FIXTURE, help="Path to benchmark JSON fixture.")
    parser.add_argument("--limit", type=int, default=None, help="Evaluate only the first N selected cases.")
    parser.add_argument("--category", default=None, help="Evaluate only one fixture category.")
    parser.add_argument("--json-report", type=Path, default=None, help="Optional path to write a machine-readable report.")
    return parser.parse_args()


async def main() -> int:
    args = parse_args()
    cases = load_cases(args.cases, args.limit, args.category)
    results = await evaluate(cases)
    summary = summarize(cases, results)
    print_report(summary)
    if args.json_report:
        args.json_report.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return 1 if summary["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
