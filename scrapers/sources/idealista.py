import os
import re
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from scrapers.utils import get_search_html

IDEALISTA_BASE_URL = 'https://www.idealista.it'  # Base URL for Idealista listings


def normalize_url(value: Optional[str]) -> str:
    if not value:
        return ''
    value = value.strip()
    if value.startswith('//'):
        return f'https:{value}'
    if value.startswith('/'):
        return f'{IDEALISTA_BASE_URL}{value}'
    return value


def parse_number(text: str) -> Optional[float]:
    if not text:
        return None
    match = re.search(r'([\d\.,]+)', text.replace(' ', ''))
    if not match:
        return None
    number = match.group(1).replace('.', '').replace(',', '.')
    try:
        return float(number)
    except ValueError:
        return None


def parse_address(text: str) -> Dict[str, str]:
    parts = [part.strip() for part in re.split(r'[–,|]', text) if part.strip()]
    if len(parts) >= 2:
        return {'neighborhood': parts[0], 'city': parts[-1]}
    return {'neighborhood': '', 'city': text.strip()}


def text_from(element) -> str:
    return element.get_text(separator=' ', strip=True) if element else ''


def parse_card(card: Any, source_id: str) -> Optional[Dict[str, Any]]:
    href = card.find('a', href=True)
    original_url = normalize_url(href['href']) if href else ''
    if not original_url:
        return None

    external_id = card.get('data-adid') or card.get('data-listing-id') or original_url
    title = text_from(card.find(['h1', 'h2', 'h3', 'h4', 'h5']))
    if not title:
        title = text_from(card.find('a'))

    price_tag = card.find(string=re.compile(r'R\$'))
    price = parse_number(price_tag) if price_tag else None

    info_text = ' '.join([text_from(item) for item in card.find_all('span')])
    bedroom_match = re.search(r'(\d+)\s+quartos?', info_text.lower())
    bath_match = re.search(r'(\d+)\s+banheiros?', info_text.lower())
    area_match = re.search(r'(\d+[\.,]?\d*)\s*m²', info_text.lower())
    bedrooms = int(bedroom_match.group(1)) if bedroom_match else None
    bathrooms = int(bath_match.group(1)) if bath_match else None
    area = parse_number(area_match.group(1)) if area_match else None

    address_text = text_from(card.find('span', class_=re.compile(r'address|location|item-detail|item-location', re.I)))
    address = parse_address(address_text)

    image = card.find('img')
    main_image = normalize_url(image.get('data-src') or image.get('src') if image else '')

    return {
        'external_id': str(external_id),
        'source_id': source_id,
        'title': title or 'Imóvel Idealista',
        'description': text_from(card.find('p')),
        'price': price or 0.0,
        'url': original_url,
        'city': address['city'] or 'Não informado',
        'neighborhood': address['neighborhood'],
        'bedrooms': int(bedrooms) if bedrooms is not None else None,
        'bathrooms': int(bathrooms) if bathrooms is not None else None,
        'area_m2': area or None,
        'metadata': {'source': 'idealista', 'main_image': main_image},
    }


async def scrape(mode: str = 'delta') -> List[Dict[str, Any]]:
    html = await get_search_html("IDEALISTA")
    if not html:
        return []

    soup = BeautifulSoup(html, 'html.parser')
    cards = soup.find_all('article')
    source_id = '00000000-0000-0000-0000-000000000002'
    if env_id := __import__('os').environ.get('IDEALISTA_SOURCE_ID'):
        source_id = env_id

    results: List[Dict[str, Any]] = []
    for card in cards:
        parsed = parse_card(card, source_id)
        if parsed and parsed['url']:
            results.append(parsed)

    return results
