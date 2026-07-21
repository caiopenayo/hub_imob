from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import asdict
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

from bs4 import BeautifulSoup
from bs4.element import Tag

from scrapers.core.normalize import (
    absolute_url,
    dedupe_tags,
    dedupe_urls,
    normalize_location_part,
    normalize_space,
    parse_area_m2,
    parse_decimal_number,
    parse_money,
    stable_content_hash,
)
from scrapers.core.providers import ProviderCapabilities, RealEstateProvider
from scrapers.core.types import ListingPage, PropertyCandidate, PropertyDetail, PropertyOfferCandidate, ScrapeRequest

logger = logging.getLogger(__name__)


REFERENCE_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9]*-\d+)\b")

PURPOSE_TO_PATH = {
    "sale": "comprar",
    "venda": "comprar",
    "vender": "comprar",
    "comprar": "comprar",
    "rent": "alugar",
    "locacao": "alugar",
    "locação": "alugar",
    "aluguel": "alugar",
    "alugar": "alugar",
}

PATH_TO_PURPOSE = {
    "comprar": "sale",
    "vender": "sale",
    "alugar": "rent",
    "locacao": "rent",
    "locação": "rent",
}

CITY_LABELS = {
    "sao paulo": "São Paulo",
    "sao-paulo": "São Paulo",
}

PACHECO_CITY_IDS = {
    "sao-paulo": "72",
}

PACHECO_NEIGHBORHOOD_IDS = {
    "butanta": "139",
    "perdizes": "137",
    "pinheiros": "138",
    "pompeia": "123",
    "sumare": "132",
    "vila-madalena": "119",
}

IMAGE_URL_ATTRIBUTES = (
    "href",
    "data-href",
    "data-src",
    "data-lazy",
    "data-original",
    "data-full",
    "data-large",
    "data-image",
    "src",
)


class UnexpectedListingStructure(ValueError):
    pass


class InvalidPropertyReference(ValueError):
    pass


class ListingIdentityMismatch(ValueError):
    pass


class DetailIdentityMismatch(ValueError):
    pass


class UnsupportedValueLabel(ValueError):
    pass


class PachecoProvider(RealEstateProvider):
    source_key = "pacheco"
    source_name = "Pacheco Imóveis"
    base_url = "https://pacheco.com.br"
    default_search_scope = {"purpose": "sale"}
    uses_offers = True
    capabilities = ProviderCapabilities(
        supports_sale=True,
        supports_city_scope=True,
        supports_neighborhood_scope=True,
        supports_detail=True,
        supports_full_reconciliation=True,
    )
    headers = {
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "pt-BR,pt;q=0.9",
    }

    def build_search_request(self, page: int, search_scope: dict[str, Any] | None = None) -> ScrapeRequest:
        scope = self._scope(search_scope)
        path = self._purpose_path(scope)
        query = self._filter_query(scope)
        url = f"{self.base_url}/{path}/" if page <= 1 else f"{self.base_url}/{path}/page/{page}/"
        if query:
            url = f"{url}?{query}"
        return ScrapeRequest(url=url, headers=self.headers)

    def build_listing_url_request(self, url: str) -> ScrapeRequest:
        return ScrapeRequest(url=absolute_url(url, self.base_url) or url, headers=self.headers)

    def parse_listing_page(
        self,
        html: str,
        page: int,
        search_scope: dict[str, Any] | None = None,
    ) -> ListingPage:
        if not normalize_space(html):
            return ListingPage(candidates=[], next_page=None, is_complete=True)

        soup = BeautifulSoup(html, "html.parser")
        root = soup.select_one(".wrapper-imoveis#sticky") or soup.select_one(".wrapper-imoveis")
        cards = root.select("form.imovel.item") if root else []
        reported_total = self._reported_total(soup)
        if not cards and reported_total:
            raise UnexpectedListingStructure("reported results but no Pacheco listing cards")

        scope = self._scope(search_scope)
        candidates: list[PropertyCandidate] = []
        invalid_cards = 0
        seen_ids: set[str] = set()
        parse_errors: list[dict[str, Any]] = []

        for card in cards:
            try:
                candidate = self._parse_card(card, scope)
            except Exception as exc:
                invalid_cards += 1
                identifier = self._short_card_identifier(card)
                parse_errors.append({"identifier": identifier, "error": str(exc)[:300]})
                logger.warning(
                    "pacheco card parse failed provider=%s page=%s id=%s error=%s",
                    self.source_key,
                    page,
                    identifier,
                    exc,
                )
                continue

            if candidate.external_id in seen_ids:
                invalid_cards += 1
                parse_errors.append({"identifier": candidate.external_id, "error": "duplicate external_id on page"})
                continue
            seen_ids.add(candidate.external_id)
            candidates.append(candidate)

        next_url = self._next_url(soup, page)
        canonical = self._canonical_url(soup)
        return ListingPage(
            candidates=candidates,
            next_page=page + 1 if next_url else None,
            next_url=next_url,
            is_complete=True,
            raw_cards_count=len(cards),
            invalid_cards_count=invalid_cards,
            reported_total=reported_total,
            canonical_url=canonical,
            raw_data={
                "current_page": page,
                "purpose": self._scope_purpose(scope),
                "cards_valid": len(candidates),
                "cards_invalid": invalid_cards,
                "reported_total": reported_total,
                "parse_errors": parse_errors,
            },
        )

    def parse_property_detail(self, html: str, candidate: PropertyCandidate) -> PropertyDetail:
        soup = BeautifulSoup(html, "html.parser")
        root = soup.select_one(".wrapper-single")
        if not root:
            raise ValueError("UnexpectedDetailStructure: missing .wrapper-single")
        main = root.select_one(".content .wrapper-dados") or root

        canonical_url = self._canonical_url(soup)
        og_url = self._meta_content(soup, "og:url")
        detail_url = canonical_url or og_url or candidate.source_url
        identity = self._detail_identity(main, detail_url, og_url, soup)
        external_id = identity.get("external_id") or candidate.external_id
        if external_id != candidate.external_id:
            raise DetailIdentityMismatch(f"expected {candidate.external_id}, got {external_id}")

        property_type = identity.get("property_type") or candidate.property_type
        address = self._detail_address(main, soup, candidate)
        attrs = self._detail_attributes(main)
        values = self._detail_values(root)
        descriptions = self._description_sections(main)
        image_urls = self._detail_images(root)
        og_image = absolute_url(self._meta_content(soup, "og:image"), self.base_url)
        if not image_urls:
            image_urls = dedupe_urls([og_image, *self._json_ld_images(soup)], self.base_url)
        main_image_url = image_urls[0] if image_urls else (og_image or candidate.main_image_url)

        detail_offers = self._detail_offers(values, candidate)
        offers = self._merge_offers(candidate.offers, detail_offers)
        selected_offer = self._selected_offer(offers, candidate.raw_data.get("search_scope") or {})
        features = attrs.get("features") or []
        upstream = self._upstream_metadata(image_urls or [main_image_url])
        wordpress_post_id = self._wordpress_post_id(soup)
        detail_hash = stable_content_hash(
            {
                "description": descriptions.get("description"),
                "neighborhood_description": descriptions.get("neighborhood_description"),
                "attributes": {
                    "bedrooms": attrs.get("bedrooms"),
                    "suites": attrs.get("suites"),
                    "bathrooms": attrs.get("bathrooms"),
                    "parking_spaces": attrs.get("parking_spaces"),
                    "usable_area_m2": attrs.get("usable_area_m2"),
                    "total_area_m2": attrs.get("total_area_m2"),
                    "commercial_rooms": attrs.get("commercial_rooms"),
                    "construction_year": attrs.get("construction_year"),
                    "raw_construction_year": attrs.get("raw_construction_year"),
                },
                "fees": values.get("raw_value_labels"),
                "advertised_monthly_total": values.get("advertised_monthly_total"),
                "features": sorted(features),
                "image_urls": image_urls,
                "canonical_url": detail_url,
                "upstream_reference": identity.get("upstream_reference") or upstream.get("upstream_reference"),
            }
        )

        raw_data = {
            "title_tag": self._title(soup),
            "og_url": og_url,
            "og_title": self._meta_content(soup, "og:title"),
            "og_description": self._meta_content(soup, "og:description"),
            "og_image": og_image,
            "raw_reference_text": identity.get("raw_reference_text"),
            "upstream_reference": identity.get("upstream_reference") or upstream.get("upstream_reference"),
            "upstream_platform": upstream.get("upstream_platform"),
            "upstream_numeric_id": upstream.get("upstream_numeric_id"),
            "wordpress_post_id": wordpress_post_id,
            "city": address.get("city"),
            "usable_area_m2": self._decimal_to_string(attrs.get("usable_area_m2")),
            "total_area_m2": self._decimal_to_string(attrs.get("total_area_m2")),
            "commercial_rooms": attrs.get("commercial_rooms"),
            "rooms": attrs.get("rooms"),
            "construction_year": attrs.get("construction_year"),
            "raw_construction_year": attrs.get("raw_construction_year"),
            "raw_value_labels": values.get("raw_value_labels"),
            "property_tax_period": values.get("property_tax_period"),
            "advertised_monthly_total": self._decimal_to_string(values.get("advertised_monthly_total")),
            "neighborhood_description": descriptions.get("neighborhood_description"),
            "offers": [self._offer_dict(offer) for offer in offers],
            "detail_hash": detail_hash,
        }

        return PropertyDetail(
            external_id=external_id,
            title=self._public_title(property_type, address.get("neighborhood") or candidate.neighborhood),
            canonical_url=detail_url,
            main_image_url=main_image_url,
            price=selected_offer.price if selected_offer else values.get("price") or candidate.price,
            property_type=property_type,
            neighborhood=address.get("neighborhood") or candidate.neighborhood,
            address_line=address.get("address_line") or candidate.address_line,
            city=address.get("city"),
            bedrooms=attrs.get("bedrooms"),
            suites=attrs.get("suites"),
            bathrooms=attrs.get("bathrooms"),
            parking_spaces=attrs.get("parking_spaces"),
            area_m2=attrs.get("usable_area_m2") or attrs.get("total_area_m2") or candidate.area_m2,
            description=descriptions.get("description"),
            condominium_fee=values.get("condominium_fee"),
            property_tax=values.get("property_tax"),
            image_urls=image_urls,
            tags=dedupe_tags(candidate.tags),
            property_features=features,
            latitude=None,
            longitude=None,
            offers=offers,
            raw_data=raw_data,
        )

    def normalize_listing(self, candidate: PropertyCandidate) -> PropertyCandidate:
        candidate.tags = dedupe_tags(candidate.tags)
        return candidate

    def normalize_detail(self, candidate: PropertyCandidate, detail: PropertyDetail) -> PropertyDetail:
        detail.image_urls = dedupe_urls(detail.image_urls, self.base_url)
        detail.tags = dedupe_tags(detail.tags)
        detail.property_features = dedupe_tags(detail.property_features)
        if not detail.main_image_url and detail.image_urls:
            detail.main_image_url = detail.image_urls[0]
        return detail

    def _scope(self, search_scope: dict[str, Any] | None) -> dict[str, Any]:
        return {**self.default_search_scope, **(search_scope or {})}

    def _purpose_path(self, scope: dict[str, Any]) -> str:
        return PURPOSE_TO_PATH.get(self._normalize_key(str(scope.get("purpose") or "sale")), "comprar")

    def _filter_query(self, scope: dict[str, Any]) -> str:
        neighborhood_slug = self._neighborhood_slug(scope)
        if not neighborhood_slug:
            return ""
        city_slug = normalize_space(str(scope.get("city_slug") or "sao-paulo")).lower()
        city_id = PACHECO_CITY_IDS.get(city_slug)
        neighborhood_id = PACHECO_NEIGHBORHOOD_IDS.get(neighborhood_slug)
        if not city_id or not neighborhood_id:
            return ""
        params = [
            ("cidades", city_id),
            ("valor-min", ""),
            ("valor-max", ""),
            ("metragem-min", ""),
            ("metragem-max", ""),
            ("referencia", ""),
            ("bairro[]", neighborhood_id),
            ("order", ""),
        ]
        return urlencode(params, safe="[]")

    def _neighborhood_slug(self, scope: dict[str, Any]) -> str | None:
        value = scope.get("neighborhood_slug")
        if value:
            return normalize_space(str(value)).lower()
        neighborhoods = scope.get("neighborhoods")
        if isinstance(neighborhoods, list) and neighborhoods:
            first = neighborhoods[0]
            if isinstance(first, dict) and first.get("slug"):
                return normalize_space(str(first["slug"])).lower()
        return None

    def _scope_purpose(self, scope: dict[str, Any]) -> str:
        path = self._purpose_path(scope)
        return PATH_TO_PURPOSE.get(path, "sale")

    def _parse_card(self, card: Tag, scope: dict[str, Any]) -> PropertyCandidate:
        source_url = self._card_detail_url(card)
        text_type, text_id, raw_reference_text = self._card_reference(card)
        url_id = self._external_id_from_url(source_url)
        if text_id and url_id and text_id != url_id:
            raise ListingIdentityMismatch(f"external_id mismatch card={text_id} url={url_id}")
        external_id = text_id or url_id
        if not external_id:
            raise InvalidPropertyReference("missing Pacheco reference")
        if not source_url:
            raise InvalidPropertyReference(f"missing detail URL for {external_id}")

        attrs = self._listing_attributes(card)
        address_line, neighborhood = self._listing_address(card)
        price = parse_money(self._card_price_text(card))
        purpose = self._scope_purpose(scope)
        images = self._card_images(card)
        flags = self._card_flags(card)
        upstream = self._upstream_metadata(images)
        wordpress_post_id = self._wordpress_post_id_from_card(card)
        status = self._status_from_card(card)
        offer = self._make_offer(purpose, price, "Valor" if purpose == "sale" else "Aluguel", scope)
        offers = [offer]
        listing_hash = stable_content_hash(
            {
                "external_id": external_id,
                "purpose": purpose,
                "property_type": text_type,
                "address_line": address_line,
                "neighborhood": neighborhood,
                "usable_area_m2": attrs.get("usable_area_m2"),
                "bedrooms": attrs.get("bedrooms"),
                "bathrooms": attrs.get("bathrooms"),
                "commercial_rooms": attrs.get("commercial_rooms"),
                "parking_spaces": attrs.get("parking_spaces"),
                "price": price,
                "image_urls": images,
                "flags": flags,
            }
        )

        city = self._city_from_scope(scope)
        state = self._state_from_scope(scope)
        raw_data = {
            "raw_property_type": text_type,
            "raw_reference_text": raw_reference_text,
            "wordpress_post_id": wordpress_post_id,
            "status": status,
            "upstream_platform": upstream.get("upstream_platform"),
            "upstream_numeric_id": upstream.get("upstream_numeric_id"),
            "upstream_reference": upstream.get("upstream_reference"),
            "listing_image_urls": images,
            "metro_lines": flags.get("metro_lines"),
            "exclusive": flags.get("exclusive"),
            "new_listing": flags.get("new_listing"),
            "commercial_rooms": attrs.get("commercial_rooms"),
            "rooms": attrs.get("rooms"),
            "usable_area_m2": self._decimal_to_string(attrs.get("usable_area_m2")),
            "listing_hash": listing_hash,
            "search_scope": scope,
            "offers": [self._offer_dict(item) for item in offers],
        }
        return PropertyCandidate(
            source_key=self.source_key,
            external_id=external_id,
            source_url=source_url,
            title=self._public_title(text_type, neighborhood),
            transaction_type=purpose,
            property_type=text_type,
            city=city,
            state=state,
            neighborhood=neighborhood,
            address_line=address_line,
            price=price,
            currency="BRL",
            bedrooms=attrs.get("bedrooms"),
            suites=attrs.get("suites"),
            bathrooms=attrs.get("bathrooms"),
            parking_spaces=attrs.get("parking_spaces"),
            area_m2=attrs.get("usable_area_m2"),
            main_image_url=images[0] if images else None,
            offers=offers,
            tags=self._tags_from_flags(flags),
            raw_data=raw_data,
        )

    def _card_reference(self, card: Tag) -> tuple[str | None, str | None, str | None]:
        element = card.select_one(".visitar > p")
        raw = normalize_space(element.get_text(" ", strip=True)) if element else None
        external_id = self._external_id_from_text(raw)
        property_type = None
        if raw and "/" in raw:
            property_type = self._title_case(raw.rsplit("/", 1)[0])
        elif raw:
            property_type = self._title_case(re.sub(REFERENCE_RE, "", raw).strip(" /-"))
        return property_type, external_id, raw

    def _card_detail_url(self, card: Tag) -> str | None:
        for link in card.select('a.box-txt__button[href*="/imoveis/"]'):
            text = self._normalize_key(link.get_text(" ", strip=True))
            if not text or "detalh" in text:
                return absolute_url(link.get("href"), self.base_url)
        for link in card.select('a[href*="/imoveis/"]'):
            href = link.get("href")
            if self._external_id_from_url(href):
                return absolute_url(href, self.base_url)
        return None

    def _listing_address(self, card: Tag) -> tuple[str | None, str | None]:
        element = card.select_one(".box-txt .title h3")
        text = normalize_space(element.get_text(" ", strip=True)) if element else None
        if not text:
            return None, None
        if " - " in text:
            address, neighborhood = text.rsplit(" - ", 1)
            return normalize_location_part(address), normalize_location_part(neighborhood)
        return normalize_location_part(text), None

    def _listing_attributes(self, card: Tag) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        for item in card.select(".box-txt .infos .infos__item p"):
            self._merge_attribute(attrs, item.get_text(" ", strip=True))
        return attrs

    def _card_price_text(self, card: Tag) -> str | None:
        element = card.select_one(".box-txt p.valor")
        return normalize_space(element.get_text(" ", strip=True)) if element else None

    def _card_images(self, card: Tag) -> list[str]:
        box = card.select_one(".box-img")
        if not box:
            return []
        return dedupe_urls(self._image_urls_from_container(box), self.base_url)

    def _card_flags(self, card: Tag) -> dict[str, Any]:
        visible = [normalize_space(text) for text in card.stripped_strings]
        visible_keys = {self._normalize_key(text) for text in visible}
        class_text = " ".join(" ".join(element.get("class") or []) for element in card.find_all(True))
        metro_lines = sorted(set(re.findall(r"linha-[A-Za-zÀ-ÿ-]+", class_text)))
        return {
            "new_listing": "anuncio novo" in visible_keys,
            "exclusive": "exclusivo" in visible_keys,
            "metro_lines": metro_lines,
        }

    def _tags_from_flags(self, flags: dict[str, Any]) -> list[str]:
        tags: list[str | None] = []
        if flags.get("new_listing"):
            tags.append("Anúncio Novo")
        if flags.get("exclusive"):
            tags.append("Exclusivo")
        return dedupe_tags(tags)

    def _status_from_card(self, card: Tag) -> str | None:
        action = card.get("action") or ""
        query = dict(parse_qsl(urlsplit(action).query, keep_blank_values=True))
        return normalize_space(query.get("status"))

    def _wordpress_post_id_from_card(self, card: Tag) -> str | None:
        form_id = normalize_space(card.get("id"))
        match = re.search(r"form-(\d+)", form_id or "")
        if match:
            return match.group(1)
        action = card.get("action") or ""
        query = dict(parse_qsl(urlsplit(action).query, keep_blank_values=True))
        return normalize_space(query.get("imovel_id"))

    def _detail_identity(
        self,
        main: Tag,
        detail_url: str | None,
        og_url: str | None,
        soup: BeautifulSoup,
    ) -> dict[str, str | None]:
        infos = main.select_one(".infos-imovel")
        raw_reference_text = None
        property_type = None
        external_id = None
        upstream_reference = None
        if infos:
            raw_reference_text = self._first_reference_text(infos)
            match = re.search(
                r"([A-Za-zÀ-ÿ0-9 ]+?)\s*-\s*([A-Za-z][A-Za-z0-9]*-\d+)\s*/?\s*([A-Za-z]{1,5}\d+)?",
                raw_reference_text or "",
            )
            if match:
                property_type = self._title_case(match.group(1))
                external_id = self._normalize_external_id(match.group(2))
                upstream_reference = normalize_space(match.group(3))

        return {
            "raw_reference_text": raw_reference_text,
            "property_type": property_type,
            "external_id": external_id
            or self._external_id_from_url(detail_url)
            or self._external_id_from_url(og_url)
            or self._external_id_from_text(self._title(soup)),
            "upstream_reference": upstream_reference,
        }

    def _first_reference_text(self, infos: Tag) -> str | None:
        for text in infos.stripped_strings:
            text = normalize_space(text)
            if REFERENCE_RE.search(text):
                return text
        return normalize_space(infos.get_text(" ", strip=True))

    def _detail_address(self, main: Tag, soup: BeautifulSoup, candidate: PropertyCandidate) -> dict[str, str | None]:
        infos = main.select_one(".infos-imovel")
        address_line = None
        neighborhood = None
        if infos:
            h1 = infos.select_one("h1")
            h2 = infos.select_one("h2")
            address_line = normalize_location_part(h1.get_text(" ", strip=True)) if h1 else None
            neighborhood = normalize_location_part(h2.get_text(" ", strip=True)) if h2 else None
        return {
            "address_line": address_line,
            "neighborhood": neighborhood,
            "city": self._city_from_breadcrumb(soup) or candidate.city,
        }

    def _detail_attributes(self, main: Tag) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        features: list[str | None] = []
        for item in main.select(".wrapper-caracteristicas-imovel .caracteristicas-imovel p"):
            text = normalize_space(item.get_text(" ", strip=True))
            if not text:
                continue
            if ":" in text:
                label, value = text.split(":", 1)
                self._merge_labeled_attribute(attrs, label, value)
            else:
                features.append(self._feature_case(text))
        attrs["features"] = dedupe_tags(features)
        return attrs

    def _merge_attribute(self, attrs: dict[str, Any], text: str) -> None:
        key = self._normalize_key(text)
        if "m2" in key or "m²" in text:
            attrs["usable_area_m2"] = parse_area_m2(text)
        elif "dormitorio" in key:
            attrs["bedrooms"] = self._int_from_text(text)
        elif "suite" in key:
            attrs["suites"] = self._int_from_text(text)
        elif "banheiro" in key:
            attrs["bathrooms"] = self._int_from_text(text)
        elif "vaga" in key:
            attrs["parking_spaces"] = self._int_from_text(text)
        elif "sala" in key:
            rooms = self._int_from_text(text)
            attrs["commercial_rooms"] = rooms
            attrs["rooms"] = rooms

    def _merge_labeled_attribute(self, attrs: dict[str, Any], label: str, value: str) -> None:
        key = self._normalize_key(label)
        raw_value = normalize_space(value)
        text = f"{raw_value} {label}"
        if "dormitorio" in key:
            attrs["bedrooms"] = self._int_from_text(raw_value)
        elif "suite" in key:
            attrs["suites"] = self._int_from_text(raw_value)
        elif "banheiro" in key:
            attrs["bathrooms"] = self._int_from_text(raw_value)
        elif "vaga" in key:
            attrs["parking_spaces"] = self._int_from_text(raw_value)
        elif "sala" in key:
            rooms = self._int_from_text(raw_value)
            attrs["commercial_rooms"] = rooms
            attrs["rooms"] = rooms
        elif "area util" in key:
            attrs["usable_area_m2"] = parse_area_m2(text)
        elif "area total" in key:
            attrs["total_area_m2"] = parse_area_m2(text)
        elif "ano de construcao" in key:
            attrs["raw_construction_year"] = raw_value
            if re.fullmatch(r"\d{4}", raw_value):
                year = int(raw_value)
                if 1800 <= year <= 2100:
                    attrs["construction_year"] = year

    def _detail_values(self, main: Tag) -> dict[str, Any]:
        result: dict[str, Any] = {"raw_value_labels": {}, "unknown_value_labels": {}}
        values = main.select_one(".container-valores .wrapper-valores .valores")
        if not values:
            return result
        for row in values.find_all("div", recursive=False):
            texts = [normalize_space(p.get_text(" ", strip=True)) for p in row.find_all("p", recursive=False)]
            texts = [text for text in texts if text]
            if len(texts) < 2:
                continue
            label = texts[0].rstrip(":")
            value_text = texts[1]
            key = self._normalize_key(label)
            money = parse_money(value_text)
            result["raw_value_labels"][label] = value_text
            if key in {"valor", "venda"}:
                result["price"] = money
                result["sale_price"] = money
            elif key == "aluguel":
                result["price"] = money
                result["rent_price"] = money
            elif key.startswith("iptu"):
                result["property_tax"] = money
                if "mes" in key:
                    result["property_tax_period"] = "monthly"
            elif key == "condominio":
                result["condominium_fee"] = money
            elif key == "total":
                result["advertised_monthly_total"] = money
            else:
                result["unknown_value_labels"][label] = value_text
        return result

    def _detail_offers(self, values: dict[str, Any], candidate: PropertyCandidate) -> list[PropertyOfferCandidate]:
        scope = candidate.raw_data.get("search_scope") if isinstance(candidate.raw_data, dict) else {}
        purpose = self._scope_purpose(scope or {})
        price = values.get("sale_price") if purpose == "sale" else values.get("rent_price")
        if price is None:
            price = values.get("price")
        if price is None:
            return []
        raw_label = "Valor" if purpose == "sale" else "Aluguel"
        return [self._make_offer(purpose, price, raw_label, scope or {})]

    def _description_sections(self, main: Tag) -> dict[str, str | None]:
        result: dict[str, str | None] = {"description": None, "neighborhood_description": None}
        for block in main.select(".wrapper-descricao-imovel"):
            parts = [normalize_space(text) for text in block.stripped_strings]
            parts = [part for part in parts if part]
            if not parts:
                continue
            heading_key = self._normalize_key(parts[0])
            body = "\n\n".join(parts[1:]) if len(parts) > 1 else None
            if "descricao do imovel" in heading_key:
                result["description"] = body
            elif "sobre o bairro" in heading_key:
                result["neighborhood_description"] = body
        return result

    def _detail_images(self, root: Tag) -> list[str]:
        gallery = root.select_one(":scope > .hero-carousel .owl-single-imovel") or root.select_one(
            ".hero-carousel .owl-single-imovel"
        )
        if not gallery:
            return []
        return dedupe_urls(self._image_urls_from_container(gallery), self.base_url)

    def _image_urls_from_container(self, container: Tag) -> list[str | None]:
        urls: list[str | None] = []
        for element in container.find_all(True):
            for attr in IMAGE_URL_ATTRIBUTES:
                urls.append(self._valid_image_url(element.get(attr)))
            urls.append(self._valid_image_url(self._largest_srcset_url(element.get("srcset"))))
        return urls

    def _largest_srcset_url(self, value: str | None) -> str | None:
        if not value:
            return None
        best_url = None
        best_score = Decimal("-1")
        for entry in value.split(","):
            parts = normalize_space(entry).split()
            if not parts:
                continue
            url = parts[0]
            score = Decimal("0")
            if len(parts) > 1:
                descriptor = parts[1].lower()
                parsed = parse_decimal_number(descriptor)
                if parsed is not None:
                    score = parsed
            if best_url is None or score >= best_score:
                best_url = url
                best_score = score
        return best_url

    def _json_ld_images(self, soup: BeautifulSoup) -> list[str]:
        images: list[str | None] = []
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                payload = json.loads(script.get_text(" ", strip=True))
            except json.JSONDecodeError:
                continue
            self._collect_json_images(payload, images)
        return dedupe_urls(images, self.base_url)

    def _collect_json_images(self, value: Any, images: list[str | None]) -> None:
        if isinstance(value, dict):
            for key in ("url", "contentUrl", "image"):
                item = value.get(key)
                if isinstance(item, str):
                    images.append(self._valid_image_url(item))
                elif isinstance(item, list):
                    for entry in item:
                        if isinstance(entry, str):
                            images.append(self._valid_image_url(entry))
            for item in value.values():
                self._collect_json_images(item, images)
        elif isinstance(value, list):
            for item in value:
                self._collect_json_images(item, images)

    def _next_url(self, soup: BeautifulSoup, current_page: int) -> str | None:
        rel_next = soup.select_one('link[rel="next"], link[rel~="next"]')
        if rel_next and rel_next.get("href"):
            return absolute_url(rel_next.get("href"), self.base_url)

        next_anchor = soup.select_one("a.next[href], a.page-numbers.next[href]")
        if next_anchor and next_anchor.get("href"):
            return absolute_url(next_anchor.get("href"), self.base_url)

        target = str(current_page + 1)
        for anchor in soup.select("a.page-numbers[href], a[href]"):
            if normalize_space(anchor.get_text(" ", strip=True)) == target:
                return absolute_url(anchor.get("href"), self.base_url)

        return None

    def _reported_total(self, soup: BeautifulSoup) -> int | None:
        text = normalize_space(soup.get_text(" ", strip=True))
        match = re.search(r"(\d[\d\.]*)\s+im[oó]veis encontrados", text, flags=re.IGNORECASE)
        if not match:
            return None
        number = parse_decimal_number(match.group(1))
        return int(number) if number is not None else None

    def _canonical_url(self, soup: BeautifulSoup) -> str | None:
        link = soup.select_one('link[rel="canonical"], link[rel~="canonical"]')
        return absolute_url(link.get("href"), self.base_url) if link else None

    def _meta_content(self, soup: BeautifulSoup, property_name: str) -> str | None:
        meta = soup.select_one(f'meta[property="{property_name}"], meta[name="{property_name}"]')
        return normalize_space(meta.get("content")) if meta and meta.get("content") else None

    def _title(self, soup: BeautifulSoup) -> str | None:
        return normalize_space(soup.title.get_text(" ", strip=True)) if soup.title else None

    def _external_id_from_text(self, text: str | None) -> str | None:
        match = REFERENCE_RE.search(text or "")
        return self._normalize_external_id(match.group(1)) if match else None

    def _external_id_from_url(self, url: str | None) -> str | None:
        if not url:
            return None
        for part in reversed([part for part in urlsplit(url).path.split("/") if part]):
            external_id = self._external_id_from_text(part)
            if external_id:
                return external_id
        return None

    def _normalize_external_id(self, value: str | None) -> str | None:
        return normalize_space(value).upper() if value else None

    def _valid_image_url(self, value: str | None) -> str | None:
        url = absolute_url(value, self.base_url)
        if not url:
            return None
        path = urlsplit(url).path.lower()
        if not re.search(r"\.(?:jpe?g|png|webp)$", path):
            return None
        return url

    def _upstream_metadata(self, urls: list[str | None]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for url in urls:
            if not url:
                continue
            vista = re.search(r"/vista\.imobi/fotos/(\d+)/", url, flags=re.IGNORECASE)
            if vista:
                result.setdefault("upstream_platform", "vista")
                result.setdefault("upstream_numeric_id", vista.group(1))
            pi = re.search(r"/imovel/PI/(PI\d+)/", url, flags=re.IGNORECASE)
            if pi:
                result.setdefault("upstream_reference", pi.group(1).upper())
        return result

    def _wordpress_post_id(self, soup: BeautifulSoup) -> str | None:
        body = soup.select_one("body")
        classes = " ".join(body.get("class") or []) if body else ""
        match = re.search(r"\bpostid-(\d+)\b", classes)
        if match:
            return match.group(1)
        shortlink = soup.select_one('link[rel="shortlink"], link[rel~="shortlink"]')
        if shortlink:
            query = dict(parse_qsl(urlsplit(shortlink.get("href") or "").query, keep_blank_values=True))
            return normalize_space(query.get("p"))
        return None

    def _city_from_breadcrumb(self, soup: BeautifulSoup) -> str | None:
        for element in soup.select(".current-page"):
            parts = [normalize_space(part) for part in element.get_text(">", strip=True).split(">")]
            parts = [part for part in parts if part and self._normalize_key(part) != "inicio"]
            if parts:
                key = self._normalize_key(parts[0])
                return CITY_LABELS.get(key, normalize_location_part(parts[0]))
        return None

    def _city_from_scope(self, scope: dict[str, Any]) -> str | None:
        value = scope.get("city") or scope.get("city_slug")
        if not value:
            return None
        text = normalize_space(str(value).replace("-", " "))
        return CITY_LABELS.get(self._normalize_key(text), normalize_location_part(text))

    def _state_from_scope(self, scope: dict[str, Any]) -> str | None:
        value = scope.get("state") or scope.get("state_slug")
        return normalize_space(str(value)).upper() if value else None

    def _make_offer(
        self,
        purpose: str,
        price: Decimal | None,
        raw_label: str | None,
        scope: dict[str, Any],
    ) -> PropertyOfferCandidate:
        offer = PropertyOfferCandidate(
            purpose=purpose,
            price=price,
            currency="BRL",
            raw_label=raw_label,
            source_scope=scope,
        )
        offer.content_hash = stable_content_hash(self._offer_hash_payload(offer))
        return offer

    def _merge_offers(
        self,
        listing_offers: list[PropertyOfferCandidate],
        detail_offers: list[PropertyOfferCandidate],
    ) -> list[PropertyOfferCandidate]:
        by_purpose = {offer.purpose: offer for offer in listing_offers}
        for offer in detail_offers:
            by_purpose[offer.purpose] = offer
        return [by_purpose[key] for key in sorted(by_purpose)]

    def _selected_offer(self, offers: list[PropertyOfferCandidate], scope: dict[str, Any]) -> PropertyOfferCandidate | None:
        purpose = self._scope_purpose(scope)
        for offer in offers:
            if offer.purpose == purpose:
                return offer
        return offers[0] if offers else None

    def _offer_hash_payload(self, offer: PropertyOfferCandidate) -> dict[str, Any]:
        return {"purpose": offer.purpose, "price": offer.price, "currency": offer.currency}

    def _offer_dict(self, offer: PropertyOfferCandidate) -> dict[str, Any]:
        data = asdict(offer)
        if offer.price is not None:
            data["price"] = str(offer.price)
        return data

    def _int_from_text(self, text: str | None) -> int | None:
        number = parse_decimal_number(text)
        return int(number) if number is not None else None

    def _public_title(self, property_type: str | None, neighborhood: str | None) -> str | None:
        if property_type and neighborhood:
            return f"{property_type} em {neighborhood}"
        return property_type or neighborhood

    def _feature_case(self, value: str | None) -> str | None:
        value = normalize_space(value)
        if not value:
            return None
        if value.isupper():
            return normalize_location_part(value)
        return value[:1].upper() + value[1:]

    def _title_case(self, value: str | None) -> str | None:
        value = normalize_space(value)
        if not value:
            return None
        if value.isupper() or value.casefold() == value:
            return " ".join(part.capitalize() for part in value.split(" "))
        return value

    def _decimal_to_string(self, value: Any) -> str | None:
        return str(value) if isinstance(value, Decimal) else None

    def _normalize_key(self, value: str | None) -> str:
        if not value:
            return ""
        normalized = unicodedata.normalize("NFKD", value)
        ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
        return normalize_space(ascii_text).casefold()

    def _short_card_identifier(self, card: Tag) -> str:
        _, external_id, raw = self._card_reference(card)
        return external_id or normalize_space(raw) or normalize_space(card.get_text(" ", strip=True)[:80])


provider = PachecoProvider()
