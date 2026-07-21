from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
    "msclkid",
}


def none_if_blank(value: str | None) -> str | None:
    if value is None:
        return None
    value = normalize_space(value)
    return value or None


def normalize_space(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def normalize_text(value: str | None) -> str | None:
    return none_if_blank(value)


def normalize_location_part(value: str | None) -> str | None:
    value = none_if_blank(value)
    if not value:
        return None
    return " ".join(part.capitalize() if part.isupper() else part for part in value.split(" "))


def parse_decimal_number(value: str | int | float | Decimal | None) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))

    text = normalize_space(str(value))
    if not text:
        return None

    match = re.search(r"[-+]?\d[\d\.,]*", text)
    if not match:
        return None

    number = match.group(0)
    if "," in number and "." in number:
        number = number.replace(".", "").replace(",", ".")
    elif "," in number:
        number = number.replace(".", "").replace(",", ".")
    elif "." in number:
        parts = number.split(".")
        if len(parts) > 1 and all(len(part) == 3 for part in parts[1:]):
            number = "".join(parts)
    else:
        number = number.replace(",", "")

    try:
        return Decimal(number)
    except InvalidOperation:
        return None


def parse_money(value: str | int | float | Decimal | None) -> Decimal | None:
    number = parse_decimal_number(value)
    if number is None:
        return None
    return number.quantize(Decimal("0.01"))


def parse_area_m2(value: str | int | float | Decimal | None) -> Decimal | None:
    number = parse_decimal_number(value)
    if number is None:
        return None
    return number.quantize(Decimal("0.01"))


def absolute_url(value: str | None, base_url: str) -> str | None:
    value = none_if_blank(value)
    if not value:
        return None
    return strip_tracking_params(urljoin(base_url, value))


def strip_tracking_params(value: str | None) -> str | None:
    value = none_if_blank(value)
    if not value:
        return None
    parts = urlsplit(value)
    query = [(key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True) if key not in TRACKING_PARAMS]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def dedupe_preserve_order(values: list[str | None]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = none_if_blank(value)
        if not normalized:
            continue
        key = normalized.casefold()
        if key not in seen:
            seen.add(key)
            result.append(normalized)
    return result


def dedupe_urls(values: list[str | None], base_url: str | None = None) -> list[str]:
    normalized = []
    for value in values:
        if base_url:
            normalized.append(absolute_url(value, base_url))
        else:
            normalized.append(strip_tracking_params(value))
    return dedupe_preserve_order(normalized)


def dedupe_tags(values: list[str | None]) -> list[str]:
    return dedupe_preserve_order(values)


def stable_content_hash(payload: dict[str, Any]) -> str:
    def normalize(value: Any) -> Any:
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, dict):
            return {key: normalize(value[key]) for key in sorted(value)}
        if isinstance(value, list):
            return [normalize(item) for item in value]
        return value

    encoded = json.dumps(normalize(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def candidate_hash_payload(candidate: Any) -> dict[str, Any]:
    return {
        "title": candidate.title,
        "transaction_type": candidate.transaction_type,
        "property_type": candidate.property_type,
        "property_subtype": candidate.property_subtype,
        "city": candidate.city,
        "state": candidate.state,
        "neighborhood": candidate.neighborhood,
        "address_line": candidate.address_line,
        "price": candidate.price,
        "currency": candidate.currency,
        "bedrooms": candidate.bedrooms,
        "suites": candidate.suites,
        "bathrooms": candidate.bathrooms,
        "parking_spaces": candidate.parking_spaces,
        "area_m2": candidate.area_m2,
        "main_image_url": candidate.main_image_url,
        "offers": [
            {
                "purpose": offer.purpose,
                "price": offer.price,
                "currency": offer.currency,
            }
            for offer in sorted(getattr(candidate, "offers", []) or [], key=lambda item: item.purpose)
        ],
        "tags": sorted(candidate.tags),
    }
