import os
from pathlib import Path
from typing import Iterable, Optional

import httpx
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env")


async def fetch_html_from_url(url: str, user_agent: str) -> str:
    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.7,en;q=0.6",
    }
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return response.text


async def get_search_html(prefix: str = "IDEALISTA", fallback_prefixes: Iterable[str] = ()) -> Optional[str]:
    for current_prefix in (prefix, *fallback_prefixes):
        html = os.getenv(f"{current_prefix}_SEARCH_HTML")
        if html:
            return html

        html_path = os.getenv(f"{current_prefix}_HTML_PATH")
        if html_path:
            return Path(html_path).read_text(encoding='utf-8')

        url = os.getenv(f"{current_prefix}_SEARCH_URL")
        if url:
            user_agent = os.getenv(
                "SCRAPER_USER_AGENT",
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
            )
            return await fetch_html_from_url(url, user_agent)

    return None
