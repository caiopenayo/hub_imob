from decimal import Decimal

from scrapers.core.normalize import (
    absolute_url,
    candidate_hash_payload,
    dedupe_tags,
    dedupe_urls,
    normalize_space,
    parse_area_m2,
    parse_money,
    stable_content_hash,
)
from scrapers.core.types import PropertyCandidate


def test_parse_money_uses_decimal_without_float():
    assert parse_money("R$ 3.100.000") == Decimal("3100000")
    assert parse_money("R$ 16.929") == Decimal("16929")
    assert parse_money("") is None


def test_parse_area_m2():
    assert parse_area_m2("183 m²") == Decimal("183")
    assert parse_area_m2("183,50 m2") == Decimal("183.50")
    assert parse_area_m2(None) is None


def test_normalize_space_and_relative_url():
    assert normalize_space("  Rua   A\n\n  123  ") == "Rua A 123"
    assert absolute_url("/imovel/123?utm_source=x&id=1", "https://www.zimoveis.com.br") == (
        "https://www.zimoveis.com.br/imovel/123?id=1"
    )


def test_dedupe_urls_and_tags_preserve_order():
    assert dedupe_urls(["/a?utm_campaign=x", "/a", "/b"], "https://site.test") == [
        "https://site.test/a",
        "https://site.test/b",
    ]
    assert dedupe_tags(["Novo", "novo", "  Piscina  ", "Piscina"]) == ["Novo", "Piscina"]


def test_stable_content_hash_is_order_independent_for_dicts():
    first = stable_content_hash({"title": "Apto", "price": "3100000", "attrs": {"b": 2, "a": 1}})
    second = stable_content_hash({"attrs": {"a": 1, "b": 2}, "price": "3100000", "title": "Apto"})
    assert first == second


def test_candidate_hash_payload_changes_when_price_changes():
    candidate = PropertyCandidate(
        source_key="zimoveis",
        external_id="123",
        source_url="https://www.zimoveis.com.br/imovel/123",
        title="Apartamento",
        price=Decimal("3100000"),
    )
    original_hash = stable_content_hash(candidate_hash_payload(candidate))
    candidate.price = Decimal("3200000")
    changed_hash = stable_content_hash(candidate_hash_payload(candidate))
    assert original_hash != changed_hash
