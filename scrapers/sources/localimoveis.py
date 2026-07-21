from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import asdict
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qsl, unquote, unquote_plus, urlencode, urlsplit

from bs4 import BeautifulSoup
from bs4.element import Tag

from scrapers.core.normalize import (
    absolute_url,
    dedupe_preserve_order,
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


PURPOSE_TO_PATH = {
    "sale": "venda",
    "rent": "locacao",
    "venda": "venda",
    "locacao": "locacao",
}

PURPOSE_LABELS = {
    "venda": "sale",
    "aluguel": "rent",
    "locacao": "rent",
    "locação": "rent",
}

CITY_LABELS = {
    "sao-paulo": "São Paulo",
}


class DetailIdentityMismatch(ValueError):
    pass


class LocalImoveisProvider(RealEstateProvider):
    source_key = "localimoveis"
    source_name = "Local Imóveis"
    base_url = "https://www.localimoveis.com.br"
    default_search_scope = {"purpose": "sale", "state_slug": "sp", "city_slug": "sao-paulo"}
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
        path = self._search_path(scope)
        if page > 1:
            path = f"{path}/{page}"
        return ScrapeRequest(url=f"{self.base_url}{path}", headers=self.headers)

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
        cards = soup.select(".card-imovel")
        reported_total = self._reported_total(soup)
        if not cards and reported_total:
            raise ValueError("UnexpectedListingStructure: reported results but no .card-imovel cards")

        candidates: list[PropertyCandidate] = []
        invalid_cards = 0
        scope = self._scope(search_scope)
        for card in cards:
            try:
                candidate = self._parse_card(card, scope)
            except Exception as exc:
                invalid_cards += 1
                identifier = self._short_card_identifier(card)
                logger.warning(
                    "localimoveis card parse failed provider=%s page=%s id=%s error=%s",
                    self.source_key,
                    page,
                    identifier,
                    exc,
                )
                continue
            if candidate is None:
                invalid_cards += 1
                continue
            candidates.append(candidate)

        canonical = self._canonical_url(soup)
        next_url = self._next_url(soup)
        return ListingPage(
            candidates=candidates,
            next_page=page + 1 if next_url else None,
            next_url=next_url,
            is_complete=True,
            raw_cards_count=len(cards),
            invalid_cards_count=invalid_cards,
            reported_total=reported_total,
            canonical_url=canonical,
            raw_data={"reported_total": reported_total, "canonical_url": canonical},
        )

    def parse_property_detail(self, html: str, candidate: PropertyCandidate) -> PropertyDetail:
        soup = BeautifulSoup(html, "html.parser")
        main = soup.select_one(".bloco-informacoes")
        if not main:
            raise ValueError("UnexpectedDetailStructure: missing .bloco-informacoes")

        canonical_url = self._canonical_url(soup)
        og_url = self._meta_content(soup, "og:url")
        requested_url = candidate.source_url
        detail_url = canonical_url or og_url or requested_url
        external_id = self._detail_external_id(main, detail_url, requested_url, soup) or candidate.external_id
        if external_id != candidate.external_id:
            raise DetailIdentityMismatch(f"expected {candidate.external_id}, got {external_id}")

        heading = normalize_space(main.select_one("h1").get_text(" ", strip=True)) if main.select_one("h1") else None
        type_parts = self._type_category_neighborhood(heading)
        property_type = type_parts.get("property_type") or candidate.property_type
        category = type_parts.get("category") or candidate.raw_data.get("property_category")
        neighborhood = type_parts.get("neighborhood") or candidate.neighborhood
        description = self._description(main)
        offers = self._detail_offers(main, candidate.raw_data.get("search_scope"))
        offers = self._merge_offers(candidate.offers, offers)
        selected_offer = self._selected_offer(offers, candidate.raw_data.get("search_scope") or {})
        fees = self._fees(main)
        attributes = self._detail_attributes(main)
        image_urls = self._detail_images(soup)
        og_image = self._real_image_from_proxy(self._meta_content(soup, "og:image"))
        if not image_urls and og_image:
            image_urls = dedupe_urls([og_image], self.base_url)
        main_image_url = image_urls[0] if image_urls else (og_image or candidate.main_image_url)
        amenities = self._amenities(soup)
        address = self._address_from_scripts(soup, neighborhood=neighborhood)

        detail_hash = stable_content_hash(
            {
                "description": description,
                "condominium_fee": fees.get("condominium_fee"),
                "property_tax": fees.get("property_tax"),
                "attributes": attributes,
                "amenities": sorted(amenities),
                "image_urls": image_urls,
                "address": address,
                "canonical_url": canonical_url,
            }
        )

        raw_data = {
            "canonical_url": canonical_url,
            "og_url": og_url,
            "og_title": self._meta_content(soup, "og:title"),
            "og_description": self._meta_content(soup, "og:description"),
            "property_category": category,
            "usage_type": category,
            "offers": [self._offer_dict(offer) for offer in offers],
            "raw_fee_strings": fees.get("raw_fee_strings"),
            "usable_area_m2": self._decimal_to_string(attributes.get("usable_area_m2")),
            "total_area_m2": self._decimal_to_string(attributes.get("total_area_m2")),
            "address": address,
            "location_precision": "approximate" if address else None,
            "detail_hash": detail_hash,
        }

        return PropertyDetail(
            external_id=external_id,
            title=heading,
            canonical_url=detail_url,
            main_image_url=main_image_url,
            price=selected_offer.price if selected_offer else candidate.price,
            property_type=property_type,
            property_subtype=category,
            neighborhood=address.get("neighborhood") or neighborhood if address else neighborhood,
            address_line=address.get("address_line") if address else candidate.address_line,
            bedrooms=attributes.get("bedrooms"),
            suites=attributes.get("suites"),
            bathrooms=attributes.get("bathrooms"),
            parking_spaces=attributes.get("parking_spaces"),
            area_m2=attributes.get("usable_area_m2") or attributes.get("total_area_m2") or candidate.area_m2,
            description=description,
            condominium_fee=fees.get("condominium_fee"),
            property_tax=fees.get("property_tax"),
            image_urls=image_urls,
            tags=amenities,
            property_features=amenities,
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

    def _search_path(self, scope: dict[str, Any]) -> str:
        purpose = PURPOSE_TO_PATH.get(str(scope.get("purpose") or "sale"), "venda")
        state_slug = normalize_space(str(scope.get("state_slug") or "sp")).lower()
        city_slug = normalize_space(str(scope.get("city_slug") or "sao-paulo")).lower()
        path = f"/imoveis/{purpose}/{state_slug}/{city_slug}"
        neighborhood_slug = self._neighborhood_slug(scope)
        return f"{path}/{neighborhood_slug}" if neighborhood_slug else path

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

    def _parse_card(self, card: Tag, scope: dict[str, Any]) -> PropertyCandidate | None:
        source_url = self._card_url(card)
        if not source_url:
            return None
        card_id = self._card_external_id(card)
        url_id = self._external_id_from_url(source_url)
        if card_id and url_id and card_id != url_id:
            raise ValueError(f"external_id mismatch card={card_id} url={url_id}")
        external_id = card_id or url_id
        if not external_id:
            return None

        type_text = normalize_space(card.select_one(".colunaTipo1 h2").get_text(" ", strip=True)) if card.select_one(".colunaTipo1 h2") else None
        type_parts = self._type_category_neighborhood(type_text)
        neighborhood_el = card.select_one(".info .largura > h3")
        neighborhood = normalize_location_part(neighborhood_el.get_text(" ", strip=True)) if neighborhood_el else None
        attrs = self._listing_attributes(card)
        offers = self._listing_offers(card, scope)
        selected_offer = self._selected_offer(offers, scope)
        main_image_url = self.extract_background_image_url(card.select_one(".card-foto").get("style") if card.select_one(".card-foto") else None)
        reo_reference = self._reo_reference(main_image_url)
        city_slug = str(scope.get("city_slug") or "")
        state_slug = str(scope.get("state_slug") or "").upper()
        city = CITY_LABELS.get(city_slug, normalize_location_part(city_slug.replace("-", " ")))
        listing_hash = stable_content_hash(
            {
                "external_id": external_id,
                "property_type": type_parts.get("property_type"),
                "category": type_parts.get("category"),
                "neighborhood": neighborhood,
                "usable_area_m2": attrs.get("usable_area_m2"),
                "total_area_m2": attrs.get("total_area_m2"),
                "bedrooms": attrs.get("bedrooms"),
                "parking_spaces": attrs.get("parking_spaces"),
                "offers": [self._offer_hash_payload(offer) for offer in sorted(offers, key=lambda item: item.purpose)],
                "main_image_url": main_image_url,
            }
        )
        raw_data = {
            "property_category": type_parts.get("category"),
            "usage_type": type_parts.get("category"),
            "raw_property_type": type_text,
            "usable_area_m2": self._decimal_to_string(attrs.get("usable_area_m2")),
            "total_area_m2": self._decimal_to_string(attrs.get("total_area_m2")),
            "offers": [self._offer_dict(offer) for offer in offers],
            "reo_reference": reo_reference,
            "listing_hash": listing_hash,
            "search_scope": scope,
        }
        return PropertyCandidate(
            source_key=self.source_key,
            external_id=external_id,
            source_url=source_url,
            title=self._card_title(type_parts.get("property_type"), neighborhood),
            transaction_type=selected_offer.purpose if selected_offer else self._scope_purpose(scope),
            property_type=type_parts.get("property_type"),
            property_subtype=type_parts.get("category"),
            city=city,
            state=state_slug or None,
            neighborhood=neighborhood,
            price=selected_offer.price if selected_offer else None,
            currency="BRL",
            bedrooms=attrs.get("bedrooms"),
            parking_spaces=attrs.get("parking_spaces"),
            area_m2=attrs.get("usable_area_m2") or attrs.get("total_area_m2"),
            main_image_url=main_image_url,
            offers=offers,
            raw_data=raw_data,
        )

    def _card_url(self, card: Tag) -> str | None:
        link = card.select_one('a[href*="/imovel/"]')
        href = link.get("href") if link else None
        return absolute_url(href, self.base_url)

    def _card_external_id(self, card: Tag) -> str | None:
        text = normalize_space(card.select_one(".refDireita1").get_text(" ", strip=True)) if card.select_one(".refDireita1") else ""
        match = re.search(r"Cod:\s*(\d+)", text, flags=re.IGNORECASE)
        return match.group(1) if match else None

    def _external_id_from_url(self, url: str | None) -> str | None:
        if not url:
            return None
        parts = [part for part in urlsplit(url).path.split("/") if part]
        for part in reversed(parts):
            if part.isdigit():
                return part
        return None

    def _type_category_neighborhood(self, value: str | None) -> dict[str, str | None]:
        if not value:
            return {"property_type": None, "category": None, "neighborhood": None}
        parts = [normalize_space(part) for part in re.split(r"\s+-\s+", value) if normalize_space(part)]
        return {
            "property_type": self._title_case(parts[0]) if parts else None,
            "category": self._title_case(parts[1]) if len(parts) > 1 else None,
            "neighborhood": normalize_location_part(parts[2]) if len(parts) > 2 else None,
        }

    def _listing_attributes(self, card: Tag) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        for block in card.select(".retorno .texto"):
            labels = [normalize_space(label.get_text(" ", strip=True)) for label in block.select("label")]
            labels = [label for label in labels if label]
            text = normalize_space(" ".join(labels))
            self._merge_attribute(attrs, text)
        return attrs

    def _detail_attributes(self, main: Tag) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        for block in main.select(".bloco-info .info-space"):
            labels = [normalize_space(label.get_text(" ", strip=True)) for label in block.select("label")]
            labels = [label for label in labels if label]
            text = normalize_space(" ".join(labels) or block.get_text(" ", strip=True))
            self._merge_attribute(attrs, text)
        return attrs

    def _merge_attribute(self, attrs: dict[str, Any], text: str) -> None:
        key = self._normalize_key(text)
        if "area util" in key:
            attrs["usable_area_m2"] = self._area_from_text(text)
        elif "area total" in key:
            attrs["total_area_m2"] = self._area_from_text(text)
        elif "quartos" in key or "dormitorios" in key:
            attrs["bedrooms"] = self._int_from_text(text)
        elif "suites" in key:
            attrs["suites"] = self._int_from_text(text)
        elif "banheiros" in key or "banheiro" in key:
            attrs["bathrooms"] = self._int_from_text(text)
        elif "vagas" in key or "vaga" in key:
            attrs["parking_spaces"] = self._int_from_text(text)

    def _area_from_text(self, text: str) -> Decimal | None:
        return parse_area_m2(text.replace("\xa0", " "))

    def _int_from_text(self, text: str) -> int | None:
        number = parse_decimal_number(text)
        return int(number) if number is not None else None

    def _listing_offers(self, card: Tag, scope: dict[str, Any]) -> list[PropertyOfferCandidate]:
        block = card.select_one(".bloco-valores")
        if not block:
            return []
        children = [child for child in block.find_all(["h3", "h2"], recursive=False)]
        return self._offers_from_label_price_elements(children, scope)

    def _detail_offers(self, main: Tag, scope: dict[str, Any] | None) -> list[PropertyOfferCandidate]:
        offers: list[PropertyOfferCandidate] = []
        for block in main.select(".texto-centro"):
            text = normalize_space(block.get_text(" ", strip=True))
            for match in re.finditer(r"(Venda|Aluguel|Loca[cç][aã]o)\s+(R\$\s*[\d\.\,]+)", text, flags=re.IGNORECASE):
                offer = self._offer_from_label(match.group(1), match.group(2), scope or {})
                if offer:
                    offers.append(offer)
        return self._dedupe_offers(offers)

    def _offers_from_label_price_elements(self, elements: list[Tag], scope: dict[str, Any]) -> list[PropertyOfferCandidate]:
        offers: list[PropertyOfferCandidate] = []
        pending_label: str | None = None
        for element in elements:
            text = normalize_space(element.get_text(" ", strip=True))
            if not text:
                continue
            if element.name == "h3":
                pending_label = text
                continue
            if element.name == "h2" and pending_label:
                offer = self._offer_from_label(pending_label, text, scope)
                if offer:
                    offers.append(offer)
                pending_label = None
        return self._dedupe_offers(offers)

    def _offer_from_label(self, label: str, price_text: str | None, scope: dict[str, Any]) -> PropertyOfferCandidate | None:
        purpose = PURPOSE_LABELS.get(self._normalize_key(label))
        price = parse_money(price_text)
        if not purpose:
            return None
        offer = PropertyOfferCandidate(
            purpose=purpose,
            price=price,
            currency="BRL",
            raw_label=normalize_space(label),
            source_scope=scope,
        )
        offer.content_hash = stable_content_hash(self._offer_hash_payload(offer))
        return offer

    def _dedupe_offers(self, offers: list[PropertyOfferCandidate]) -> list[PropertyOfferCandidate]:
        by_purpose: dict[str, PropertyOfferCandidate] = {}
        for offer in offers:
            by_purpose[offer.purpose] = offer
        return [by_purpose[key] for key in sorted(by_purpose)]

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

    def _scope_purpose(self, scope: dict[str, Any]) -> str:
        value = str(scope.get("purpose") or "sale")
        if value in {"venda", "sale"}:
            return "sale"
        if value in {"locacao", "locação", "rent"}:
            return "rent"
        return value

    def _offer_hash_payload(self, offer: PropertyOfferCandidate) -> dict[str, Any]:
        return {"purpose": offer.purpose, "price": offer.price, "currency": offer.currency}

    def _offer_dict(self, offer: PropertyOfferCandidate) -> dict[str, Any]:
        data = asdict(offer)
        if offer.price is not None:
            data["price"] = str(offer.price)
        return data

    def _card_title(self, property_type: str | None, neighborhood: str | None) -> str | None:
        if property_type and neighborhood:
            return f"{property_type} em {neighborhood}"
        return property_type

    def _next_url(self, soup: BeautifulSoup) -> str | None:
        link = soup.select_one('link[rel="next"], link[rel~="next"]')
        href = link.get("href") if link else None
        if not href:
            avanzar = soup.select_one("a.avancar[href]")
            href = avanzar.get("href") if avanzar else None
        return absolute_url(href, self.base_url)

    def _canonical_url(self, soup: BeautifulSoup) -> str | None:
        link = soup.select_one('link[rel="canonical"], link[rel~="canonical"]')
        return absolute_url(link.get("href"), self.base_url) if link else None

    def _meta_content(self, soup: BeautifulSoup, property_name: str) -> str | None:
        meta = soup.select_one(f'meta[property="{property_name}"], meta[name="{property_name}"]')
        return normalize_space(meta.get("content")) if meta and meta.get("content") else None

    def _reported_total(self, soup: BeautifulSoup) -> int | None:
        text = normalize_space(soup.get_text(" ", strip=True))
        match = re.search(r"(\d[\d\.]*)\s+Resultados", text, flags=re.IGNORECASE)
        if not match:
            return None
        number = parse_decimal_number(match.group(1))
        return int(number) if number is not None else None

    def _detail_external_id(self, main: Tag, detail_url: str | None, requested_url: str | None, soup: BeautifulSoup) -> str | None:
        text = normalize_space(main.get_text(" ", strip=True))
        match = re.search(r"Cod:\s*(\d+)", text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
        return (
            self._external_id_from_url(detail_url)
            or self._external_id_from_url(requested_url)
            or self._external_id_from_title(self._meta_content(soup, "og:title"))
            or self._external_id_from_title(self._title(soup))
        )

    def _external_id_from_title(self, title: str | None) -> str | None:
        match = re.search(r"(?:Ref:|Cod:)\s*(\d+)", title or "", flags=re.IGNORECASE)
        return match.group(1) if match else None

    def _title(self, soup: BeautifulSoup) -> str | None:
        return normalize_space(soup.title.get_text(" ", strip=True)) if soup.title else None

    def _description(self, main: Tag) -> str | None:
        element = main.select_one(".promocao .texto")
        if not element:
            return None
        paragraphs = [normalize_space(part) for part in element.stripped_strings]
        return "\n\n".join(dedupe_preserve_order(paragraphs)) or None

    def _fees(self, main: Tag) -> dict[str, Any]:
        result: dict[str, Any] = {"raw_fee_strings": {}}
        for label in ["Condominio", "Condomínio", "IPTU"]:
            value_text = self._value_near_text(main, label)
            if not value_text:
                continue
            key = "property_tax" if self._normalize_key(label) == "iptu" else "condominium_fee"
            result[key] = parse_money(value_text)
            result["raw_fee_strings"][key] = value_text
        return result

    def _value_near_text(self, root: Tag, label: str) -> str | None:
        label_key = self._normalize_key(label)
        for node in root.find_all(string=True):
            text = normalize_space(str(node))
            if self._normalize_key(text) != label_key:
                continue
            parent = node.parent
            if not parent:
                continue
            container = parent.find_parent("div")
            sibling = container.find_next_sibling("div") if container else None
            if sibling:
                value = normalize_space(sibling.get_text(" ", strip=True))
                if value and self._normalize_key(value) != label_key:
                    return value
            value = self._next_non_empty_text(parent)
            if value and self._normalize_key(value) != label_key:
                return value
        return None

    def _next_non_empty_text(self, element: Tag) -> str | None:
        for sibling in element.next_siblings:
            if isinstance(sibling, Tag):
                text = normalize_space(sibling.get_text(" ", strip=True))
            else:
                text = normalize_space(str(sibling))
            if text:
                return text
        return None

    def _detail_images(self, soup: BeautifulSoup) -> list[str]:
        urls: list[str | None] = []
        for card in soup.select(".slider .bloco-foto .card-imovel"):
            style = card.get("style")
            photo = card.select_one(".card-foto")
            if not style and photo:
                style = photo.get("style")
            urls.append(self.extract_background_image_url(style))
        return dedupe_urls(urls, self.base_url)

    def _amenities(self, soup: BeautifulSoup) -> list[str]:
        return dedupe_tags([item.get_text(" ", strip=True) for item in soup.select("#conta-com label.nomes strong")])

    def _address_from_scripts(self, soup: BeautifulSoup, neighborhood: str | None) -> dict[str, Any] | None:
        for script in soup.select("script"):
            content = script.string or script.get_text(" ", strip=False)
            if "&q=" not in content and "?q=" not in content:
                continue
            matches = re.findall(r"[?&]q=([^\"';]+)", content)
            if not matches:
                continue
            raw = sorted(
                matches,
                key=lambda item: (
                    "CEP" in item.upper(),
                    "RUA" in unquote_plus(item).upper(),
                    len(item),
                ),
                reverse=True,
            )[0]
            decoded = normalize_space(unquote_plus(raw))
            decoded = re.sub(r"^.*&q=", "", decoded)
            cep = self._postal_code(decoded)
            state = "SP" if re.search(r"\bSP\b", decoded, flags=re.IGNORECASE) else None
            city = "São Paulo" if "SAO PAULO" in self._normalize_key(decoded).upper() else None
            neighborhood_value = neighborhood
            if neighborhood and self._normalize_key(neighborhood) in self._normalize_key(decoded):
                address_line = normalize_space(
                    re.split(re.escape(neighborhood), decoded, maxsplit=1, flags=re.IGNORECASE)[0]
                )
            else:
                address_line = decoded
            address_line = re.sub(r"^.*\bq=", "", address_line, flags=re.IGNORECASE)
            address_line = re.sub(r"\bCEP\b.*$", "", address_line, flags=re.IGNORECASE)
            address_line = re.sub(r"\bS[AÃ]O PAULO\b.*$", "", address_line, flags=re.IGNORECASE)
            address_line = normalize_space(address_line)
            return {
                "address_line": address_line or None,
                "neighborhood": neighborhood_value,
                "city": city,
                "state": state,
                "postal_code": cep,
                "location_precision": "approximate",
            }
        return None

    def _postal_code(self, text: str) -> str | None:
        match = re.search(r"\b(\d{5})[-\s]?(\d{3})\b", text)
        return f"{match.group(1)}-{match.group(2)}" if match else None

    def _real_image_from_proxy(self, value: str | None) -> str | None:
        url = absolute_url(value, self.base_url)
        if not url:
            return None
        parts = urlsplit(url)
        if parts.path.endswith("/foto.php"):
            query = dict(parse_qsl(parts.query, keep_blank_values=True))
            real = query.get("url")
            if real and real.startswith(("http://", "https://")):
                return unquote(real)
        return url

    def _reo_reference(self, image_url: str | None) -> str | None:
        match = re.search(r"/realestate/(REO\d+)/", image_url or "", flags=re.IGNORECASE)
        return match.group(1).upper() if match else None

    def extract_background_image_url(self, style: str | None) -> str | None:
        if not style:
            return None
        match = re.search(r"background-image\s*:\s*url\(\s*(['\"]?)(.*?)\1\s*\)", style, flags=re.IGNORECASE)
        if not match:
            match = re.search(r"url\(\s*(['\"]?)(.*?)\1\s*\)", style, flags=re.IGNORECASE)
        if not match:
            return None
        value = normalize_space(match.group(2))
        if not re.search(r"\.(?:jpe?g|png|webp)(?:[?#].*)?$", value, flags=re.IGNORECASE):
            return None
        return absolute_url(value, self.base_url)

    def _short_card_identifier(self, card: Tag) -> str:
        code = self._card_external_id(card)
        if code:
            return code
        return normalize_space(card.get_text(" ", strip=True)[:80])

    def _title_case(self, value: str | None) -> str | None:
        if not value:
            return None
        value = normalize_space(value)
        if value.isupper():
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


provider = LocalImoveisProvider()
