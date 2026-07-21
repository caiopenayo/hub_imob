from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scrapers.core.types import PropertyCandidate, PropertyOfferCandidate
from scrapers.sources.pacheco import provider


FIXTURES = ROOT / "tests" / "fixtures" / "pacheco"


def _read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _detail_candidate(external_id: str, purpose: str, price: Decimal | None) -> PropertyCandidate:
    return PropertyCandidate(
        source_key="pacheco",
        external_id=external_id,
        source_url=f"https://pacheco.com.br/imoveis/{external_id.lower()}/",
        transaction_type=purpose,
        price=price,
        offers=[PropertyOfferCandidate(purpose=purpose, price=price, currency="BRL")],
        raw_data={"search_scope": {"purpose": purpose}},
    )


def _property_from_candidate(candidate: PropertyCandidate, index: int) -> dict:
    images = candidate.raw_data.get("listing_image_urls") if isinstance(candidate.raw_data, dict) else []
    images = images if isinstance(images, list) else []
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": f"mock-pacheco-{candidate.external_id}",
        "external_id": candidate.external_id,
        "title": candidate.title,
        "description": None,
        "price": float(candidate.price) if candidate.price is not None else None,
        "price_currency": candidate.currency or "BRL",
        "property_type": candidate.property_type,
        "property_subtype": candidate.property_subtype,
        "city": candidate.city or "São Paulo",
        "neighborhood": candidate.neighborhood,
        "address_line": candidate.address_line,
        "bedrooms": candidate.bedrooms,
        "bathrooms": candidate.bathrooms,
        "parking_spaces": candidate.parking_spaces,
        "area_m2": float(candidate.area_m2) if candidate.area_m2 is not None else None,
        "main_image_url": candidate.main_image_url,
        "url": candidate.source_url,
        "source_url": candidate.source_url,
        "updated_at": now,
        "last_seen_at": now,
        "metadata": {
            "source": "pacheco",
            "main_image": candidate.main_image_url,
            "images": images,
            "offers": [
                {
                    "purpose": offer.purpose,
                    "price": float(offer.price) if offer.price is not None else None,
                    "currency": offer.currency,
                }
                for offer in candidate.offers
            ],
            "mock_index": index,
        },
    }


def build_properties() -> list[dict]:
    sale_page = provider.parse_listing_page(_read_fixture("pacheco_listing.html"), 1, {"purpose": "sale"})
    sale_page_2 = provider.parse_listing_page(_read_fixture("pacheco_listing_page2.html"), 2, {"purpose": "sale"})
    rent_page = provider.parse_listing_page(_read_fixture("pacheco_rent_listing.html"), 1, {"purpose": "rent"})
    properties = [
        _property_from_candidate(candidate, index)
        for index, candidate in enumerate([*sale_page.candidates, *sale_page_2.candidates, *rent_page.candidates], start=1)
    ]

    sale_detail = provider.parse_property_detail(
        _read_fixture("pacheco_detail.html"),
        _detail_candidate("Z-268289", "sale", Decimal("2800000.00")),
    )
    rent_detail = provider.parse_property_detail(
        _read_fixture("pacheco_rent_detail.html"),
        _detail_candidate("L1-50943", "rent", Decimal("10000.00")),
    )
    for detail, purpose in [(sale_detail, "sale"), (rent_detail, "rent")]:
        properties.insert(
            0,
            {
                "id": f"mock-pacheco-{detail.external_id}",
                "external_id": detail.external_id,
                "title": detail.title,
                "description": detail.description,
                "price": float(detail.price) if detail.price is not None else None,
                "price_currency": "BRL",
                "property_type": detail.property_type,
                "property_subtype": detail.property_subtype,
                "city": detail.city or "São Paulo",
                "neighborhood": detail.neighborhood,
                "address_line": detail.address_line,
                "bedrooms": detail.bedrooms,
                "bathrooms": detail.bathrooms,
                "parking_spaces": detail.parking_spaces,
                "area_m2": float(detail.area_m2) if detail.area_m2 is not None else None,
                "main_image_url": detail.main_image_url,
                "url": detail.canonical_url,
                "source_url": detail.canonical_url,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "last_seen_at": datetime.now(timezone.utc).isoformat(),
                "metadata": {
                    "source": "pacheco",
                    "main_image": detail.main_image_url,
                    "images": detail.image_urls,
                    "offers": [{"purpose": purpose, "price": float(detail.price) if detail.price else None}],
                    "detail_raw_data": detail.raw_data,
                },
            },
        )
    return properties


PROPERTIES = build_properties()


class Handler(BaseHTTPRequestHandler):
    def _headers(self, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "http://localhost:3000")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_OPTIONS(self) -> None:
        self._headers(204)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._headers()
            self.wfile.write(json.dumps({"status": "ok", "mode": "mock-pacheco"}).encode("utf-8"))
            return
        if parsed.path.rstrip("/") != "/properties":
            self._headers(404)
            self.wfile.write(json.dumps({"detail": "not found"}).encode("utf-8"))
            return

        query = parse_qs(parsed.query)
        page = max(1, int((query.get("page") or ["1"])[0]))
        per_page = max(1, min(100, int((query.get("per_page") or ["20"])[0])))
        items = list(PROPERTIES)

        city = (query.get("city") or [""])[0].strip().casefold()
        if city:
            items = [item for item in items if city in (item.get("city") or "").casefold()]
        max_price = (query.get("max_price") or [""])[0]
        if max_price:
            max_value = float(max_price)
            items = [item for item in items if item.get("price") is not None and item["price"] <= max_value]
        bedrooms = (query.get("bedrooms") or [""])[0]
        if bedrooms:
            min_bedrooms = int(bedrooms)
            items = [item for item in items if (item.get("bedrooms") or 0) >= min_bedrooms]

        total = len(items)
        start = (page - 1) * per_page
        payload = {
            "items": items[start : start + per_page],
            "meta": {"page": page, "per_page": per_page, "total": total},
        }
        self._headers()
        self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def main() -> None:
    port = int(os.getenv("PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Mock Pacheco API running on http://localhost:{port} with {len(PROPERTIES)} properties", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
