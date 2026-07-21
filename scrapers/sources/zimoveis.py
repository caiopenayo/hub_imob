from __future__ import annotations

import logging
import json
import re
import unicodedata
from decimal import Decimal
from typing import Any
from urllib.parse import unquote, urlencode, urlsplit

from bs4 import BeautifulSoup, Comment
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
from scrapers.core.types import ListingPage, PropertyCandidate, PropertyDetail, ScrapeRequest

logger = logging.getLogger(__name__)


KNOWN_TAGS = {
    "video": "Vídeo",
    "vídeo": "Vídeo",
    "360": "360º",
    "360º": "360º",
    "permuta": "Permuta",
    "destaque": "Destaque",
    "especial": "Especial",
    "planta modificada": "Planta Modificada",
    "decorado com ia": "Decorado com IA",
    "exclusivo": "Exclusivo",
}

SLUG_LABELS = {
    "padrao": "Padrão",
    "sao-paulo": "Sao Paulo",
}


class ZimoveisProvider(RealEstateProvider):
    source_key = "zimoveis"
    source_name = "Zimmermann Imóveis"
    base_url = "https://www.zimoveis.com.br"
    default_search_scope = {"q": "Sao Paulo"}
    capabilities = ProviderCapabilities(
        supports_sale=True,
        supports_city_scope=True,
        supports_neighborhood_scope=True,
        supports_detail=True,
        supports_full_reconciliation=True,
    )

    def search_scope_for_sale_scope(self, scope: dict[str, Any]) -> dict[str, Any]:
        if scope.get("scope_type") == "full_city":
            return {
                "q": "Sao Paulo",
                **{key: value for key, value in scope.items() if key in {"scope_type", "purpose", "sync_offer_purposes"}},
            }
        if scope.get("scope_type") == "priority_neighborhoods":
            neighborhood_slug = self._neighborhood_slug(scope)
            if neighborhood_slug:
                return {
                    "bairros": neighborhood_slug,
                    **{key: value for key, value in scope.items() if key in {"scope_type", "purpose", "sync_offer_purposes"}},
                }
        return super().search_scope_for_sale_scope(scope)

    def build_search_request(self, page: int, search_scope: dict[str, Any] | None = None) -> ScrapeRequest:
        scope = {**self.default_search_scope, **(search_scope or {})}
        allowed_params = {"bairros"} if scope.get("bairros") else {"q"}
        params = {key: value for key, value in scope.items() if key in allowed_params and value not in (None, "")}
        headers: dict[str, str] = {}
        if page > 1:
            params["newscroll"] = "1"
            params["page"] = page
            headers = {
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": self._search_url(scope),
            }
        return ScrapeRequest(url=f"{self.base_url}/buscar-imoveis?{urlencode(params)}", headers=headers)

    def parse_listing_page(
        self,
        html: str,
        page: int,
        search_scope: dict[str, Any] | None = None,
    ) -> ListingPage:
        html = self._listing_html_from_response(html)
        if not normalize_space(html):
            return ListingPage(candidates=[], next_page=None, is_complete=True)

        soup = BeautifulSoup(html, "html.parser")
        candidates: list[PropertyCandidate] = []
        cards = soup.select("div.cardImovel[data-code]")
        invalid_cards = 0
        for card in cards:
            try:
                candidate = self._parse_card(card)
            except Exception as exc:
                invalid_cards += 1
                identifier = normalize_space(card.get("data-code") or card.get_text(" ", strip=True)[:80])
                logger.warning("zimoveis card parse failed id=%s error=%s", identifier, exc)
                continue
            if candidate is not None:
                candidates.append(candidate)
            else:
                invalid_cards += 1

        logger.info("zimoveis listing parsed page=%s cards=%s", page, len(candidates))
        return ListingPage(
            candidates=candidates,
            next_page=page + 1 if candidates else None,
            is_complete=True,
            raw_cards_count=len(cards),
            invalid_cards_count=invalid_cards,
        )

    def parse_property_detail(self, html: str, candidate: PropertyCandidate) -> PropertyDetail:
        soup = BeautifulSoup(html, "html.parser")
        canonical_url = self._canonical_url(soup) or candidate.source_url
        external_id = self._detail_external_id(soup, canonical_url) or candidate.external_id
        image_urls = self._detail_images(soup)
        og_image = self._meta_content(soup, "og:image")
        if og_image and not image_urls:
            image_urls = dedupe_urls([og_image], self.base_url)
        main_image_url = image_urls[0] if image_urls else absolute_url(og_image, self.base_url)

        description = self._section_text(soup, "Sobre o imóvel")
        property_features = self._section_items(soup, "Detalhes do imóvel")
        condominium_description = self._section_text(soup, "Sobre o condomínio")
        condominium_features = self._section_items(soup, "Detalhes do condomínio")
        nearby_points = self._nearby_points(soup)
        attributes = self._detail_attributes(soup, property_features)
        latitude, longitude = self._map_coordinates(soup)
        video_urls = self._video_urls(soup)
        tags = self._extract_tags(soup)

        detail = PropertyDetail(
            external_id=external_id,
            title=self._public_title(self._title(soup), external_id),
            canonical_url=canonical_url,
            main_image_url=main_image_url,
            price=parse_money(self._value_after_label(soup, "Valor")),
            neighborhood=self._value_after_label(soup, "Bairro") or candidate.neighborhood,
            address_line=self._value_after_label(soup, "Endereço") or candidate.address_line,
            bedrooms=attributes.get("bedrooms"),
            suites=attributes.get("suites"),
            bathrooms=attributes.get("bathrooms"),
            parking_spaces=attributes.get("parking_spaces"),
            area_m2=attributes.get("area_m2"),
            description=description,
            condominium_fee=parse_money(self._value_after_label(soup, "Condomínio")),
            property_tax=parse_money(self._value_after_label(soup, "IPTU")),
            price_per_m2=parse_money(self._value_after_label(soup, "Valor por m²")),
            image_urls=image_urls,
            tags=tags,
            property_features=property_features,
            condominium_description=condominium_description,
            condominium_features=condominium_features,
            nearby_points=nearby_points,
            latitude=latitude,
            longitude=longitude,
            video_urls=video_urls,
            raw_data={
                "og_image": absolute_url(og_image, self.base_url),
                "location_precision": "approximate" if latitude is not None and longitude is not None else None,
                "detail_hash": self._detail_hash(
                    description=description,
                    condominium_fee=parse_money(self._value_after_label(soup, "Condomínio")),
                    property_tax=parse_money(self._value_after_label(soup, "IPTU")),
                    price_per_m2=parse_money(self._value_after_label(soup, "Valor por m²")),
                    image_urls=image_urls,
                    property_features=property_features,
                    condominium_features=condominium_features,
                    latitude=latitude,
                    longitude=longitude,
                    video_urls=video_urls,
                ),
            },
        )
        return detail

    def normalize_listing(self, candidate: PropertyCandidate) -> PropertyCandidate:
        candidate.tags = dedupe_tags(candidate.tags)
        return candidate

    def normalize_detail(self, candidate: PropertyCandidate, detail: PropertyDetail) -> PropertyDetail:
        detail.image_urls = dedupe_urls(detail.image_urls, self.base_url)
        detail.video_urls = dedupe_urls(detail.video_urls, self.base_url)
        detail.tags = dedupe_tags(detail.tags)
        if not detail.main_image_url and detail.image_urls:
            detail.main_image_url = detail.image_urls[0]
        return detail

    def _search_url(self, scope: dict[str, Any] | None) -> str:
        effective_scope = scope or self.default_search_scope
        allowed_params = {"bairros"} if effective_scope.get("bairros") else {"q"}
        params = {key: value for key, value in effective_scope.items() if key in allowed_params and value not in (None, "")}
        return f"{self.base_url}/buscar-imoveis?{urlencode(params)}"

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

    def _listing_html_from_response(self, response_text: str) -> str:
        text = response_text.strip()
        if not text.startswith("{"):
            return response_text
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return response_text
        html = payload.get("html") if isinstance(payload, dict) else None
        return html if isinstance(html, str) else response_text

    def _parse_card(self, card: Tag) -> PropertyCandidate | None:
        source_url = self._card_source_url(card)
        external_id = normalize_space(card.get("data-code")) or self._external_id_from_url(source_url)
        if not external_id or not source_url:
            return None

        url_parts = self._property_url_parts(source_url)
        type_section = self._section_texts_after_comment(card, "Tipo e Valor")
        card_texts = self._visible_texts(card)
        price_text = self._first_money_text(type_section) or self._first_money_text(card_texts)
        attribute_section = self._section_texts_after_comment(card, "Atributos do Imóvel")
        attributes_text = " ".join(attribute_section or card_texts)
        attrs = self._attributes_from_text(attributes_text)
        tags = self._extract_tags(card)

        property_type = self._property_type_from_section(type_section) or self._slug_to_name(url_parts.get("category"))
        property_subtype = self._slug_to_name(url_parts.get("subtype"))
        neighborhood = self._card_neighborhood(card) or self._slug_to_name(url_parts.get("neighborhood"))
        city = self._slug_to_name(url_parts.get("city"))
        address_line = self._card_address(card) or self._slug_to_name(url_parts.get("address"))
        main_image_url = self._card_main_image(card)

        raw_data = {
            "url_parts": url_parts,
            "listing_hash": stable_content_hash(
                {
                    "price": parse_money(price_text),
                    "property_type": property_type,
                    "neighborhood": neighborhood,
                    "address_line": address_line,
                    "area_m2": attrs.get("area_m2"),
                    "bedrooms": attrs.get("bedrooms"),
                    "suites": attrs.get("suites"),
                    "bathrooms": attrs.get("bathrooms"),
                    "parking_spaces": attrs.get("parking_spaces"),
                    "main_image_url": main_image_url,
                    "tags": sorted(tags),
                }
            ),
        }

        return PropertyCandidate(
            source_key=self.source_key,
            external_id=external_id,
            source_url=source_url,
            title=self._card_title(card, property_type, neighborhood),
            transaction_type="sale",
            property_type=property_type,
            property_subtype=property_subtype,
            city=city,
            state="SP" if self._normalize_key(city) == "sao paulo" else None,
            neighborhood=neighborhood,
            address_line=address_line,
            price=parse_money(price_text),
            currency="BRL",
            bedrooms=attrs.get("bedrooms"),
            suites=attrs.get("suites"),
            bathrooms=attrs.get("bathrooms"),
            parking_spaces=attrs.get("parking_spaces"),
            area_m2=attrs.get("area_m2"),
            main_image_url=main_image_url,
            tags=tags,
            raw_data=raw_data,
        )

    def _card_source_url(self, card: Tag) -> str | None:
        link = card.select_one('a[href*="/imovel/"]') or card.select_one("a[href]")
        href = link.get("href") if link else None
        return absolute_url(href, self.base_url)

    def _card_main_image(self, card: Tag) -> str | None:
        img = card.select_one("img")
        if not img:
            return None
        value = img.get("data-src") or img.get("data-original") or img.get("src")
        if not value and img.get("srcset"):
            value = str(img.get("srcset")).split(",")[0].strip().split(" ")[0]
        return absolute_url(value, self.base_url)

    def _card_neighborhood(self, card: Tag) -> str | None:
        link = card.select_one('a[aria-label*="Acessar mais informações"]')
        return normalize_location_part(link.get_text(" ", strip=True)) if link else None

    def _card_address(self, card: Tag) -> str | None:
        address = card.select_one("address")
        if address:
            return normalize_space(address.get_text(" ", strip=True)) or None
        for selector in ('[class*="endereco"]', '[class*="Endereco"]', '[class*="address"]'):
            element = card.select_one(selector)
            if element:
                text = normalize_space(element.get_text(" ", strip=True))
                if text:
                    return text
        texts = self._section_texts_after_comment(card, "Endereço")
        return texts[0] if texts else None

    def _card_title(self, card: Tag, property_type: str | None, neighborhood: str | None) -> str | None:
        heading = card.select_one("h1, h2, h3, h4")
        if heading:
            text = normalize_space(heading.get_text(" ", strip=True))
            if text:
                return text
        if property_type and neighborhood:
            return f"{property_type} em {neighborhood}"
        return property_type

    def _property_type_from_section(self, texts: list[str]) -> str | None:
        for text in texts:
            if not text:
                continue
            if "R$" in text:
                text = normalize_space(re.sub(r"R\$\s*[\d\.\,]+", "", text))
                if not text:
                    continue
            if re.search(r"\b(m[²2]|dorm|su[ií]te|vaga)\b", text, flags=re.IGNORECASE):
                continue
            return normalize_space(text)
        return None

    def _section_texts_after_comment(self, root: Tag, marker: str) -> list[str]:
        marker_key = self._normalize_key(marker)
        for comment in root.find_all(string=lambda value: isinstance(value, Comment)):
            if marker_key in self._normalize_key(str(comment)):
                texts: list[str] = []
                for sibling in comment.next_siblings:
                    if isinstance(sibling, Comment):
                        break
                    if isinstance(sibling, Tag):
                        text = normalize_space(sibling.get_text(" ", strip=True))
                    else:
                        text = normalize_space(str(sibling))
                    if text:
                        texts.append(text)
                if texts:
                    return texts
        return []

    def _visible_texts(self, root: Tag | BeautifulSoup) -> list[str]:
        texts: list[str] = []
        for node in root.find_all(string=True):
            if isinstance(node, Comment):
                continue
            parent = node.parent
            if parent and parent.name in {"script", "style", "noscript", "template", "form"}:
                continue
            text = normalize_space(str(node))
            if text:
                texts.append(text)
        return texts

    def _first_money_text(self, texts: list[str]) -> str | None:
        for text in texts:
            match = re.search(r"R\$\s*[\d\.\,]+", text)
            if match:
                return match.group(0)
        return None

    def _attributes_from_text(self, text: str) -> dict[str, Any]:
        normalized = self._normalize_key(text)
        suites = self._regex_int(normalized, r"(\d+)\s*suites?")
        bathrooms = self._regex_int(normalized, r"(\d+)\s*(?:banheiros?|banhos?|bhs?|wcs?)")
        return {
            "area_m2": self._regex_area(normalized),
            "bedrooms": self._regex_int(normalized, r"(\d+)\s*(?:dorms?|dormitorios?)"),
            "suites": suites,
            "bathrooms": bathrooms if bathrooms is not None else self._infer_bathrooms(suites),
            "parking_spaces": self._regex_int(normalized, r"(\d+)\s*vagas?"),
        }

    def _regex_area(self, text: str) -> Decimal | None:
        match = re.search(r"(\d+(?:[\.,]\d+)?)\s*(?:m\s*[²2]|metros?\s+quadrados?)", text)
        return parse_area_m2(match.group(1)) if match else None

    def _regex_int(self, text: str, pattern: str) -> int | None:
        match = re.search(pattern, text)
        return int(match.group(1)) if match else None

    def _detail_attributes(self, soup: BeautifulSoup, property_features: list[str] | None = None) -> dict[str, Any]:
        bedrooms = self._int_from_attribute_label(soup, "Dormitórios")
        suites = self._int_from_attribute_label(soup, "Suítes")
        bathrooms = (
            self._int_from_attribute_label(soup, "Banheiros")
            or self._int_from_attribute_label(soup, "Banheiro")
            or self._int_from_attribute_label(soup, "Banhos")
        )
        parking_spaces = self._int_from_attribute_label(soup, "Vagas")
        area_m2 = self._area_from_attribute_label(soup, "Área útil")
        return {
            "bedrooms": bedrooms,
            "suites": suites,
            "bathrooms": bathrooms if bathrooms is not None else self._infer_bathrooms(suites, property_features),
            "parking_spaces": parking_spaces,
            "area_m2": area_m2,
        }

    def _int_from_attribute_label(self, soup: BeautifulSoup, label: str) -> int | None:
        text = self._attribute_block_text(soup, label)
        if not text:
            return None
        return self._int_before_or_after_label(text, label)

    def _area_from_attribute_label(self, soup: BeautifulSoup, label: str) -> Decimal | None:
        text = self._attribute_block_text(soup, label)
        if not text:
            return None
        return self._regex_area(self._normalize_key(text))

    def _attribute_block_text(self, soup: BeautifulSoup, label: str) -> str | None:
        label_key = self._normalize_key(label).rstrip(":")
        for node in soup.find_all(string=True):
            if isinstance(node, Comment):
                continue
            parent = node.parent
            if not parent or parent.name in {"script", "style", "noscript", "template", "form"}:
                continue
            text = normalize_space(str(node))
            text_key = self._normalize_key(text).rstrip(":")
            if text_key != label_key and not text_key.startswith(f"{label_key}:"):
                continue

            if parent.name in {"dt", "th"}:
                value = self._next_non_empty_text(parent)
                if value:
                    return normalize_space(f"{value} {label}")

            block = parent.find_parent("div") or parent
            block_text = normalize_space(block.get_text(" ", strip=True))
            if block_text and label_key in self._normalize_key(block_text) and len(block_text) <= 120:
                return block_text

            rest = normalize_space(re.sub(rf"^{re.escape(label)}\s*:?", "", text, flags=re.IGNORECASE))
            if rest:
                return normalize_space(f"{rest} {label}")
        return None

    def _int_before_or_after_label(self, text: str, label: str) -> int | None:
        normalized = self._normalize_key(text)
        label_key = self._normalize_key(label).rstrip(":")
        if label_key in normalized:
            before, after = normalized.split(label_key, 1)
            before_numbers = re.findall(r"\d+", before)
            if before_numbers:
                return int(before_numbers[-1])
            after_numbers = re.findall(r"\d+", after)
            if after_numbers:
                return int(after_numbers[0])
        number = parse_decimal_number(text)
        return int(number) if number is not None else None

    def _infer_bathrooms(self, suites: int | None, property_features: list[str] | None = None) -> int | None:
        base = suites or 0
        features_text = self._normalize_key(" ".join(property_features or []))
        extra = 0
        if "lavabo" in features_text:
            extra += 1
        if re.search(r"\b(?:banheiro|banho|wc)\s+social\b", features_text):
            extra += 1
        if re.search(r"\b(?:banheiro|banho|wc)\s+(?:empregada|servico|auxiliar)\b", features_text):
            extra += 1
        if base or extra:
            return base + extra
        return None

    def _extract_tags(self, root: Tag | BeautifulSoup) -> list[str]:
        values: list[str] = []
        for element in root.select('button, [class*="badge"], [class*="tag"], [class*="selo"], [class*="label"]'):
            text = normalize_space(element.get_text(" ", strip=True))
            tag = self._known_tag(text)
            if tag:
                values.append(tag)
        for text in self._visible_texts(root):
            tag = self._known_tag(text)
            if tag:
                values.append(tag)
        return dedupe_tags(values)

    def _known_tag(self, text: str | None) -> str | None:
        key = self._normalize_key(text)
        if not key:
            return None
        for needle, label in KNOWN_TAGS.items():
            if needle in key:
                return label
        return None

    def _property_url_parts(self, url: str | None) -> dict[str, str | None]:
        if not url:
            return {}
        parts = [unquote(part) for part in urlsplit(url).path.split("/") if part]
        if "imovel" not in parts:
            return {}
        start = parts.index("imovel")
        segments = parts[start + 1 :]
        external_id = next((segment for segment in reversed(segments) if segment.isdigit()), None)
        return {
            "category": self._segment(segments, 0),
            "subtype": self._segment(segments, 1),
            "neighborhood": self._segment(segments, 2),
            "city": self._segment(segments, 3),
            "address": self._segment(segments, 4),
            "external_id": external_id,
        }

    def _segment(self, segments: list[str], index: int) -> str | None:
        return segments[index] if len(segments) > index else None

    def _external_id_from_url(self, url: str | None) -> str | None:
        return self._property_url_parts(url).get("external_id")

    def _slug_to_name(self, value: str | None) -> str | None:
        if not value:
            return None
        if value in SLUG_LABELS:
            return SLUG_LABELS[value]
        return normalize_location_part(value.replace("-", " "))

    def _title(self, soup: BeautifulSoup) -> str | None:
        title = soup.find("title")
        return normalize_space(title.get_text(" ", strip=True)) if title else None

    def _public_title(self, title: str | None, external_id: str | None = None) -> str | None:
        clean_title = normalize_space(title)
        if not clean_title:
            return None
        if external_id:
            clean_title = re.sub(
                rf"\s*[-–—]\s*(?:c[oó]d\.?\s*:?\s*)?{re.escape(str(external_id))}\s*$",
                "",
                clean_title,
                flags=re.IGNORECASE,
            )
        clean_title = re.sub(r"\s*[-–—]\s*(?:c[oó]d\.?\s*:?\s*)?\d{4,}\s*$", "", clean_title, flags=re.IGNORECASE)
        return normalize_space(clean_title) or None

    def _canonical_url(self, soup: BeautifulSoup) -> str | None:
        link = soup.select_one('link[rel="canonical"], link[rel~="canonical"]')
        return absolute_url(link.get("href"), self.base_url) if link else None

    def _meta_content(self, soup: BeautifulSoup, property_name: str) -> str | None:
        meta = soup.select_one(f'meta[property="{property_name}"], meta[name="{property_name}"]')
        value = meta.get("content") if meta else None
        return normalize_space(value) or None

    def _detail_external_id(self, soup: BeautifulSoup, canonical_url: str | None) -> str | None:
        value = self._value_after_label(soup, "Código") or self._value_after_label(soup, "Cód")
        if value:
            match = re.search(r"\d+", value)
            if match:
                return match.group(0)
        return self._external_id_from_url(canonical_url)

    def _detail_images(self, soup: BeautifulSoup) -> list[str]:
        urls = [link.get("href") for link in soup.select('a[data-fancybox="galeria"][href]')]
        return dedupe_urls(urls, self.base_url)

    def _video_urls(self, soup: BeautifulSoup) -> list[str]:
        urls = []
        for iframe in soup.select("iframe[src]"):
            src = iframe.get("src")
            if src and ("youtube" in src or "youtu.be" in src):
                urls.append(src)
        return dedupe_urls(urls, self.base_url)

    def _value_after_label(self, soup: BeautifulSoup, label: str) -> str | None:
        label_key = self._normalize_key(label).rstrip(":")
        for node in soup.find_all(string=True):
            if isinstance(node, Comment):
                continue
            parent = node.parent
            if not parent or parent.name in {"script", "style", "noscript", "template", "form"}:
                continue
            text = normalize_space(str(node))
            text_key = self._normalize_key(text).rstrip(":")
            if text_key != label_key and not text_key.startswith(f"{label_key}:"):
                continue
            rest = normalize_space(re.sub(rf"^{re.escape(label)}\s*:?", "", text, flags=re.IGNORECASE))
            if rest and self._normalize_key(rest) != label_key:
                return rest
            for sibling in node.next_siblings:
                if isinstance(sibling, Tag):
                    sibling_text = normalize_space(sibling.get_text(" ", strip=True))
                else:
                    sibling_text = normalize_space(str(sibling))
                if sibling_text:
                    return sibling_text
            sibling = self._next_non_empty_text(parent)
            if sibling:
                return sibling
        return None

    def _next_non_empty_text(self, element: Tag) -> str | None:
        for sibling in element.next_siblings:
            if isinstance(sibling, Tag):
                if sibling.name in {"script", "style", "noscript", "template", "form"}:
                    continue
                text = normalize_space(sibling.get_text(" ", strip=True))
            else:
                text = normalize_space(str(sibling))
            if text:
                return text
        next_element = element.find_next()
        if isinstance(next_element, Tag) and next_element.name not in {"script", "style", "noscript", "template", "form"}:
            text = normalize_space(next_element.get_text(" ", strip=True))
            return text or None
        return None

    def _int_value_after_label(self, soup: BeautifulSoup, label: str) -> int | None:
        value = self._value_after_label(soup, label)
        number = parse_decimal_number(value)
        return int(number) if number is not None else None

    def _section_container(self, soup: BeautifulSoup, heading: str) -> Tag | None:
        heading_key = self._normalize_key(heading)
        for element in soup.find_all(["h1", "h2", "h3", "h4", "h5", "strong", "span"]):
            if heading_key in self._normalize_key(element.get_text(" ", strip=True)):
                parent = element.find_parent("div")
                return parent if parent else element.parent
        return None

    def _section_text(self, soup: BeautifulSoup, heading: str) -> str | None:
        container = self._section_container(soup, heading)
        if not container:
            return None
        heading_key = self._normalize_key(heading)
        paragraphs = []
        for element in container.find_all(["p", "div"], recursive=True):
            if element.find(["p", "div"]):
                continue
            text = normalize_space(element.get_text(" ", strip=True))
            if text and heading_key not in self._normalize_key(text):
                paragraphs.append(text)
        if not paragraphs:
            paragraphs = [text for text in self._visible_texts(container) if heading_key not in self._normalize_key(text)]
        return "\n\n".join(dedupe_tags(paragraphs)) or None

    def _section_items(self, soup: BeautifulSoup, heading: str) -> list[str]:
        container = self._section_container(soup, heading)
        if not container:
            return []
        values = [normalize_space(item.get_text(" ", strip=True)) for item in container.select("li")]
        if not values:
            heading_key = self._normalize_key(heading)
            values = [text for text in self._visible_texts(container) if heading_key not in self._normalize_key(text)]
        return dedupe_tags(values)

    def _nearby_points(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        container = self._section_container(soup, "Pontos de Interesse") or self._section_container(
            soup, "Pontos de interesse"
        )
        if not container:
            return []
        points = []
        typed_points = container.select(".type")
        for type_el in typed_points:
            item = type_el.find_parent("div")
            if not item:
                continue
            name_el = item.select_one(".name")
            distance_el = item.select_one(".distance")
            distance_text = normalize_space(distance_el.get_text(" ", strip=True)) if distance_el else None
            _, distance_meters = self._distance(distance_text or "")
            points.append(
                {
                    "type": normalize_space(type_el.get_text(" ", strip=True)) or None,
                    "name": normalize_space(name_el.get_text(" ", strip=True)) if name_el else None,
                    "distance_text": distance_text,
                    "distance_meters": distance_meters,
                }
            )
        if points:
            return points
        for item in container.select("li, .nearbyPoint, [data-distance]"):
            text = normalize_space(item.get_text(" ", strip=True))
            if not text:
                continue
            distance_text, distance_meters = self._distance(text)
            point_type = normalize_space(item.get("data-type") or "")
            name = text
            type_el = item.select_one('[class*="tipo"], [class*="type"]')
            name_el = item.select_one('[class*="nome"], [class*="name"]')
            distance_el = item.select_one('[class*="dist"], [data-distance]')
            if type_el:
                point_type = normalize_space(type_el.get_text(" ", strip=True))
            if name_el:
                name = normalize_space(name_el.get_text(" ", strip=True))
            if distance_el:
                distance_text = normalize_space(distance_el.get_text(" ", strip=True) or distance_el.get("data-distance"))
                _, distance_meters = self._distance(distance_text)
            points.append(
                {
                    "type": point_type or None,
                    "name": name,
                    "distance_text": distance_text,
                    "distance_meters": distance_meters,
                }
            )
        return points

    def _distance(self, text: str) -> tuple[str | None, int | None]:
        match = re.search(r"(\d+(?:[\.,]\d+)?)\s*(km|metros?|m)\b", self._normalize_key(text))
        if not match:
            return None, None
        value = parse_decimal_number(match.group(1))
        if value is None:
            return match.group(0), None
        meters = value * (Decimal("1000") if match.group(2) == "km" else Decimal("1"))
        return match.group(0), int(meters)

    def _map_coordinates(self, soup: BeautifulSoup) -> tuple[Decimal | None, Decimal | None]:
        for tag in soup.select("[src], [href], [data-src]"):
            value = tag.get("src") or tag.get("href") or tag.get("data-src")
            if not value or "center=" not in value:
                continue
            match = re.search(r"center=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)", value)
            if match:
                return Decimal(match.group(1)), Decimal(match.group(2))
        return None, None

    def _detail_hash(
        self,
        *,
        description: str | None,
        condominium_fee: Decimal | None,
        property_tax: Decimal | None,
        price_per_m2: Decimal | None,
        image_urls: list[str],
        property_features: list[str],
        condominium_features: list[str],
        latitude: Decimal | None,
        longitude: Decimal | None,
        video_urls: list[str],
    ) -> str:
        return stable_content_hash(
            {
                "description": description,
                "condominium_fee": condominium_fee,
                "property_tax": property_tax,
                "price_per_m2": price_per_m2,
                "image_urls": image_urls,
                "property_features": sorted(property_features),
                "condominium_features": sorted(condominium_features),
                "latitude": latitude,
                "longitude": longitude,
                "video_urls": sorted(video_urls),
            }
        )

    def _normalize_key(self, value: str | None) -> str:
        if not value:
            return ""
        normalized = unicodedata.normalize("NFKD", value)
        ascii_text = "".join(char for char in normalized if not unicodedata.combining(char))
        return normalize_space(ascii_text).casefold()


provider = ZimoveisProvider()
