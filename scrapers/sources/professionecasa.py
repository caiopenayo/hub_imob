import asyncio
import os
import re
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from scrapers.utils import get_search_html

PROFESSIONECASA_BASE_URL = "https://www.professionecasa.it"
DEFAULT_SOURCE_ID = "00000000-0000-0000-0000-000000000003"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
IMAGE_ATTRS = ("data-src", "data-original", "data-lazy", "data-full", "src")
IGNORED_IMAGE_TOKENS = (
    "professionecasa-y.jpg",
    "logo",
    "trustpilot",
    "facebook",
    "instagram",
    "youtube",
    "linkedin",
    "whatsapp",
    "favicon",
    "sprite",
    "icon",
    "bassa",
    "alta",
)


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def text_from(element: Any) -> str:
    return normalize_space(element.get_text(" ", strip=True)) if element else ""


def parse_number(value: str) -> Optional[float]:
    if not value:
        return None
    match = re.search(r"(\d[\d\.,]*)", value)
    if not match:
        return None
    number = match.group(1).replace(".", "").replace(",", ".")
    try:
        return float(number)
    except ValueError:
        return None


def parse_int(value: str) -> Optional[int]:
    number = parse_number(value)
    return int(number) if number is not None else None


def absolute_url(value: Optional[str]) -> str:
    if not value:
        return ""
    return urljoin(PROFESSIONECASA_BASE_URL, value.strip())


def external_id_from_url(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    return path.rsplit("/", 1)[-1] or url


def feature_value(card: Any, class_name: str) -> Optional[str]:
    item = card.select_one(f".caratteristiche-immobile .{class_name} strong")
    return text_from(item) if item else None


def parse_city(address: str) -> str:
    match = re.search(r"-\s*([^()]+)\s*\([^)]+\)\s*$", address)
    if match:
        return normalize_space(match.group(1))
    if "torino" in address.lower():
        return "Torino"
    return ""


def parse_neighborhood(description: str) -> str:
    first_line = description.split(".")[0]
    first_line = first_line.split(" VENDESI ")[0].strip()
    if len(first_line) <= 80 and re.search(r"\b(ZONA|BORGO|PARELLA|CROCETTA|CRIMEA|MIRAFIORI)\b", first_line, re.I):
        return normalize_space(first_line.title())
    return ""


def unique_urls(values: List[str]) -> List[str]:
    urls: List[str] = []
    seen: set[str] = set()
    for value in values:
        key = image_dedupe_key(value)
        if value and key not in seen:
            seen.add(key)
            urls.append(value)
    return urls


def image_dedupe_key(value: str) -> str:
    parsed = urlparse(value)
    if parsed.path.lower().endswith("getimage.ashx"):
        image_file = parse_qs(parsed.query).get("f", [""])[0]
        if image_file:
            return image_file.lower()
    return value


def parse_srcset(value: str) -> List[str]:
    urls: List[str] = []
    for candidate in value.split(","):
        url = candidate.strip().split(" ")[0]
        if url:
            urls.append(url)
    return urls


def is_property_image(value: str, alt: str = "") -> bool:
    url = absolute_url(value)
    if not url:
        return False

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False

    haystack = f"{url} {alt}".lower()
    if any(token in haystack for token in IGNORED_IMAGE_TOKENS):
        return False

    image_reference = f"{parsed.path}?{parsed.query}".lower()
    return bool(re.search(r"\.(jpg|jpeg|png|webp)($|[?&])", image_reference))


def image_urls(element: Any) -> List[str]:
    raw_urls: List[str] = []
    for image in element.find_all("img"):
        alt = image.get("alt") or ""
        for attr in IMAGE_ATTRS:
            value = image.get(attr)
            if value and is_property_image(value, alt):
                raw_urls.append(absolute_url(value))

        srcset = image.get("srcset") or image.get("data-srcset")
        if srcset:
            for value in parse_srcset(srcset):
                if is_property_image(value, alt):
                    raw_urls.append(absolute_url(value))

    for source in element.find_all("source"):
        srcset = source.get("srcset") or source.get("data-srcset")
        if not srcset:
            continue
        for value in parse_srcset(srcset):
            if is_property_image(value):
                raw_urls.append(absolute_url(value))

    return unique_urls(raw_urls)


def scraper_headers() -> Dict[str, str]:
    user_agent = os.getenv("SCRAPER_USER_AGENT", DEFAULT_USER_AGENT)
    return {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.7,en;q=0.6",
    }


def should_fetch_detail_images() -> bool:
    value = os.getenv("PROFESSIONECASA_FETCH_DETAIL_IMAGES", "true").strip().lower()
    return value not in {"0", "false", "no", "off"}


def detail_concurrency() -> int:
    try:
        return max(1, int(os.getenv("PROFESSIONECASA_DETAIL_CONCURRENCY", "4")))
    except ValueError:
        return 4


def detail_timeout() -> float:
    try:
        return max(1.0, float(os.getenv("PROFESSIONECASA_DETAIL_TIMEOUT", "15")))
    except ValueError:
        return 15.0


def max_detail_pages() -> int:
    try:
        return max(0, int(os.getenv("PROFESSIONECASA_MAX_DETAIL_PAGES", "0")))
    except ValueError:
        return 0


async def fetch_detail_images(client: httpx.AsyncClient, url: str) -> List[str]:
    try:
        response = await client.get(url)
        response.raise_for_status()
    except Exception as exc:
        print(f"professionecasa detail image fetch failed url={url}: {exc}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    return image_urls(soup)


async def enrich_with_detail_images(items: List[Dict[str, Any]]) -> None:
    if not items or not should_fetch_detail_images():
        return

    semaphore = asyncio.Semaphore(detail_concurrency())

    async with httpx.AsyncClient(timeout=detail_timeout(), follow_redirects=True, headers=scraper_headers()) as client:
        async def enrich(item: Dict[str, Any]) -> None:
            async with semaphore:
                detail_images = await fetch_detail_images(client, item["url"])

            metadata = item.setdefault("metadata", {})
            listing_images = metadata.get("images") if isinstance(metadata.get("images"), list) else []
            images = unique_urls([*detail_images, *listing_images])
            if images:
                metadata["images"] = images
                metadata["main_image"] = images[0]

        limit = max_detail_pages()
        targets = items[:limit] if limit else items
        await asyncio.gather(*(enrich(item) for item in targets))


def parse_card(card: Any, source_id: str) -> Optional[Dict[str, Any]]:
    link = card.select_one("a[href*='/appartamento/']")
    url = absolute_url(link.get("href")) if link else ""
    if not url:
        return None

    title = text_from(card.find("h4")) or "Appartamento Professionecasa"
    address = text_from(card.find("h5"))
    price = parse_number(text_from(card.find("h6")))
    description = text_from(card.find("p"))
    images = image_urls(card)

    rooms = parse_int(feature_value(card, "locali") or "")
    bathrooms = parse_int(feature_value(card, "bagni") or "")
    area_m2 = parse_number(feature_value(card, "superficie") or "")
    energy_class = feature_value(card, "energetica")

    return {
        "external_id": external_id_from_url(url),
        "source_id": source_id,
        "title": title,
        "description": description,
        "price": price,
        "price_currency": "EUR",
        "url": url,
        "city": parse_city(address) or "Torino",
        "neighborhood": parse_neighborhood(description),
        "bedrooms": rooms,
        "bathrooms": bathrooms,
        "area_m2": area_m2,
        "metadata": {
            "source": "professionecasa",
            "address_line": address,
            "rooms": rooms,
            "energy_class": energy_class,
            "main_image": images[0] if images else "",
            "images": images,
        },
    }


async def scrape(mode: str = "delta") -> List[Dict[str, Any]]:
    html = await get_search_html("PROFESSIONECASA", fallback_prefixes=("IDEALISTA",))
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    source_id = os.getenv("PROFESSIONECASA_SOURCE_ID", DEFAULT_SOURCE_ID)

    results: List[Dict[str, Any]] = []
    for card in soup.select("div.immobile-item"):
        parsed = parse_card(card, source_id)
        if parsed:
            results.append(parsed)

    await enrich_with_detail_images(results)
    return results
