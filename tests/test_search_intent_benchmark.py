import json
from pathlib import Path


FIXTURE_PATH = Path("tests/fixtures/search_intent_cases.json")
ALLOWED_EXPECTED_FIELDS = {
    "transaction_type",
    "property_type",
    "city",
    "neighborhoods",
    "price",
    "area_m2",
    "bedrooms",
    "bathrooms",
    "parking_spaces",
    "balcony",
    "unresolved_terms",
    "clarification_needed",
    "clarification_question",
}


def test_search_intent_benchmark_has_required_coverage():
    cases = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    assert len(cases) >= 50
    assert len({case["id"] for case in cases}) == len(cases)
    assert sum(1 for case in cases if case["category"] == "adversarial") >= 10

    categories = {case["category"] for case in cases}
    assert "rent" in categories
    assert "price-range" in categories
    assert "area-range" in categories
    assert "preferred" in categories
    assert "unsupported" in categories
    assert "contradictory" in categories


def test_search_intent_benchmark_cases_have_expected_shape():
    cases = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    for case in cases:
        assert set(case) == {"id", "category", "query", "expected", "notes"}
        assert isinstance(case["id"], str) and case["id"]
        assert isinstance(case["category"], str) and case["category"]
        assert isinstance(case["query"], str) and case["query"]
        assert isinstance(case["expected"], dict)
        assert isinstance(case["notes"], str)
        assert set(case["expected"]).issubset(ALLOWED_EXPECTED_FIELDS)
