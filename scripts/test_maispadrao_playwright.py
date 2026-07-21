from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
    from playwright.async_api import async_playwright
except ImportError:
    print(
        "Playwright is not installed.\n\n"
        "Install with:\n"
        "  pip install playwright\n"
        "  playwright install chromium\n",
        file=sys.stderr,
    )
    raise SystemExit(2)


TEST_URL = "https://www.maispadraoimoveis.com.br/imoveis/a-venda/sao-paulo"
PAGE_2_PATH = "/imoveis/a-venda/sao-paulo?pagina=2"
HOSTNAME = "www.maispadraoimoveis.com.br"

SECURITY_TERMS = [
    "Verificação de segurança",
    "captcha",
    "recaptcha",
    "verify you are human",
    "access denied",
    "forbidden",
    "challenge",
    "gocache-error-page",
]

BLOCKING_SECURITY_TERMS = [
    "Verificação de segurança",
    "Complete o desafio",
    "verify you are human",
    "access denied",
    "forbidden",
    "challenge",
    "gocache-error-page",
]

CAPTCHA_TERMS = [
    "captcha",
    "recaptcha",
    "hcaptcha",
    "cf-turnstile",
    "g-recaptcha",
    "data-sitekey",
]


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError("--headless must be true or false")


def write_json(path: Path, payload: dict[str, Any] | list[dict[str, Any]]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def detect_security_challenge(html: str, text: str) -> dict[str, Any]:
    haystack = f"{html}\n{text}".lower()
    matched_terms = [term for term in SECURITY_TERMS if term.lower() in haystack]
    blocking_terms = [term for term in BLOCKING_SECURITY_TERMS if term.lower() in haystack]
    captcha_terms = [term for term in CAPTCHA_TERMS if term.lower() in haystack]
    return {
        "challenge_detected": bool(blocking_terms),
        "captcha_detected": bool(captcha_terms and blocking_terms),
        "matched_terms": matched_terms,
        "blocking_terms": blocking_terms,
        "captcha_terms": captcha_terms,
    }


async def inspect_page(page, context) -> dict[str, Any]:
    title = await page.title()
    html = await page.content()
    text = await page.locator("body").inner_text(timeout=3000) if await page.locator("body").count() else ""
    cookies = await context.cookies()
    marko_info = await page.evaluate(
        """() => {
          const vars = window.markoVars || null;
          const keys = vars && typeof vars === 'object' ? Object.keys(vars) : [];
          return {
            hasMarkoVars: Boolean(vars),
            keysCount: keys.length,
            listingKeys: keys.filter((key) => key.startsWith('listings-')),
          };
        }"""
    )
    cards_count = await page.locator("a.card-with-buttons").count()
    return {
        "title": title,
        "html": html,
        "text": text,
        "text_sample": text[:2000],
        "cookies": [{"name": cookie.get("name"), "domain": cookie.get("domain")} for cookie in cookies],
        "cards_count": cards_count,
        "has_marko_vars": bool(marko_info.get("hasMarkoVars")),
        "marko_vars_keys_count": int(marko_info.get("keysCount") or 0),
        "listing_keys": marko_info.get("listingKeys") or [],
        "listing_keys_count": len(marko_info.get("listingKeys") or []),
    }


async def test_pagination_endpoint(page) -> dict[str, Any]:
    result = await page.evaluate(
        """async (path) => {
          const response = await fetch(path, {
            method: 'GET',
            headers: {
              Accept: 'application/json, text/javascript, */*; q=0.01',
              'X-Requested-With': 'XMLHttpRequest',
            },
            credentials: 'include',
          });
          const text = await response.text();
          let parsed = null;
          let jsonValid = false;
          try {
            parsed = JSON.parse(text);
            jsonValid = true;
          } catch (_) {
            parsed = null;
          }
          return {
            status: response.status,
            contentType: response.headers.get('content-type') || '',
            text,
            jsonValid,
            parsed,
          };
        }""",
        PAGE_2_PATH,
    )
    parsed = result.get("parsed") if isinstance(result.get("parsed"), dict) else None
    data = parsed.get("data") if parsed else None
    first_item = data[0] if isinstance(data, list) and data else None
    has_identifier_or_url = False
    if isinstance(first_item, dict):
        item_keys = {str(key).lower() for key in first_item}
        has_identifier_or_url = bool(
            item_keys
            & {
                "id",
                "codigo",
                "code",
                "url",
                "link",
                "slug",
                "propertyid",
                "reference",
                "referencia",
            }
        )
    summary = {
        "attempted": True,
        "status": result.get("status"),
        "content_type": result.get("contentType"),
        "json_valid": bool(result.get("jsonValid")),
        "has_data": isinstance(data, list) and len(data) > 0,
        "data_length": len(data) if isinstance(data, list) else 0,
        "count": parsed.get("count") if parsed else None,
        "has_count": parsed is not None and "count" in parsed,
        "has_aggs": parsed is not None and "aggs" in parsed,
        "has_identifier_or_url": has_identifier_or_url,
    }
    return {
        **summary,
        "raw_text": result.get("text"),
        "parsed_json": parsed,
    }


def filtered_response_record(response) -> dict[str, Any] | None:
    url = response.url
    parsed = urlparse(url)
    content_type = response.headers.get("content-type", "")
    resource_type = response.request.resource_type
    is_site_request = parsed.hostname == HOSTNAME and resource_type not in {"image", "media", "font", "stylesheet"}
    is_relevant = (
        resource_type == "document"
        or is_site_request
        or "pagina=" in url
        or "application/json" in content_type
    )
    if not is_relevant:
        return None
    return {
        "kind": "response",
        "url": url,
        "status": response.status,
        "resource_type": resource_type,
        "content_type": content_type,
    }


def classify_result(page_info: dict[str, Any], security: dict[str, Any], endpoint: dict[str, Any]) -> str:
    title = (page_info.get("title") or "").lower()
    has_sale_title = "venda" in title or "à venda" in title or "a venda" in title
    content_success = page_info["cards_count"] > 0 or (page_info["listing_keys_count"] > 0 and has_sale_title)

    if security["captcha_detected"] and not content_success:
        return "CAPTCHA_REQUIRED"
    if security["challenge_detected"] and not content_success:
        return "SECURITY_CHALLENGE"

    if not content_success:
        return "CONTENT_NOT_FOUND"

    if not endpoint.get("attempted"):
        return "SUCCESS"
    if endpoint.get("status") != 200:
        return "ENDPOINT_BLOCKED"
    if not endpoint.get("json_valid") or "application/json" not in (endpoint.get("content_type") or ""):
        return "ENDPOINT_INVALID_RESPONSE"
    if not (endpoint.get("has_data") and endpoint.get("has_count") and endpoint.get("has_aggs")):
        return "ENDPOINT_INVALID_RESPONSE"
    return "SUCCESS"


async def save_artifacts(
    output_dir: Path,
    page,
    result: dict[str, Any],
    network: list[dict[str, Any]],
    html: str | None,
    endpoint: dict[str, Any] | None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    if html is not None:
        (output_dir / "page.html").write_text(html, encoding="utf-8")
    if page is not None and not (output_dir / "screenshot.png").exists():
        try:
            await page.screenshot(path=str(output_dir / "screenshot.png"), full_page=True)
        except Exception as exc:
            result["screenshot_error"] = f"{type(exc).__name__}: {str(exc)[:500]}"
    write_json(output_dir / "result.json", result)
    write_json(output_dir / "network.json", network)
    if endpoint and endpoint.get("json_valid"):
        write_json(
            output_dir / "endpoint_page_2.json",
            {
                "status": endpoint.get("status"),
                "content_type": endpoint.get("content_type"),
                "raw_text": endpoint.get("raw_text"),
                "parsed_json": endpoint.get("parsed_json"),
            },
        )


async def run_mode(headless: bool, timeout_seconds: int, output_dir: Path, settle_seconds: float) -> dict[str, Any]:
    started = time.perf_counter()
    mode = "headless" if headless else "headed"
    network: list[dict[str, Any]] = []
    page = None
    context = None
    browser = None
    html: str | None = None
    endpoint_artifact: dict[str, Any] | None = None
    result: dict[str, Any] = {
        "mode": mode,
        "result": "UNEXPECTED_ERROR",
        "main_navigation": {
            "status": None,
            "final_url": None,
            "title": None,
            "cards_count": 0,
            "has_marko_vars": False,
            "marko_vars_keys_count": 0,
            "listing_keys_count": 0,
        },
        "security": {
            "challenge_detected": False,
            "captcha_detected": False,
            "matched_terms": [],
            "captcha_terms": [],
        },
        "pagination_api": {"attempted": False},
        "cookies": [],
        "duration_seconds": None,
        "error": None,
    }

    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=headless)
            context = await browser.new_context(viewport={"width": 1366, "height": 768})
            page = await context.new_page()

            page.on(
                "response",
                lambda response: network.append(record)
                if (record := filtered_response_record(response)) is not None
                else None,
            )
            page.on(
                "requestfailed",
                lambda request: network.append(
                    {
                        "kind": "requestfailed",
                        "url": request.url,
                        "resource_type": request.resource_type,
                        "failure": str(request.failure),
                    }
                ),
            )

            response = await page.goto(TEST_URL, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
            if settle_seconds > 0:
                await page.wait_for_timeout(int(settle_seconds * 1000))

            page_info = await inspect_page(page, context)
            html = page_info.pop("html")
            security = detect_security_challenge(html, page_info["text"])
            main_navigation = {
                "status": response.status if response else None,
                "final_url": page.url,
                "title": page_info["title"],
                "text_sample": page_info["text_sample"],
                "cards_count": page_info["cards_count"],
                "has_marko_vars": page_info["has_marko_vars"],
                "marko_vars_keys_count": page_info["marko_vars_keys_count"],
                "listing_keys": page_info["listing_keys"],
                "listing_keys_count": page_info["listing_keys_count"],
            }
            result["main_navigation"] = main_navigation
            result["security"] = security
            result["cookies"] = page_info["cookies"]
            output_dir.mkdir(parents=True, exist_ok=True)
            try:
                await page.screenshot(path=str(output_dir / "screenshot.png"), full_page=True)
            except Exception as exc:
                result["screenshot_error"] = f"{type(exc).__name__}: {str(exc)[:500]}"

            provisional = classify_result(main_navigation, security, {"attempted": False})
            if provisional == "CONTENT_NOT_FOUND" or provisional in {"SECURITY_CHALLENGE", "CAPTCHA_REQUIRED"}:
                result["result"] = provisional
            else:
                endpoint = await test_pagination_endpoint(page)
                endpoint_artifact = endpoint
                result["pagination_api"] = {
                    key: value
                    for key, value in endpoint.items()
                    if key not in {"raw_text", "parsed_json"}
                }
                result["result"] = classify_result(main_navigation, security, result["pagination_api"])

    except PlaywrightTimeoutError as exc:
        result["result"] = "TIMEOUT"
        result["error"] = str(exc)[:1000]
    except Exception as exc:
        result["result"] = "UNEXPECTED_ERROR"
        result["error"] = f"{type(exc).__name__}: {str(exc)[:1000]}"
    finally:
        result["duration_seconds"] = round(time.perf_counter() - started, 3)
        try:
            if page is not None:
                await save_artifacts(output_dir, page, result, network, html, endpoint_artifact)
        finally:
            if context is not None:
                try:
                    await context.close()
                except Exception:
                    pass
            if browser is not None:
                try:
                    await browser.close()
                except Exception:
                    pass
        if page is None:
            output_dir.mkdir(parents=True, exist_ok=True)
            write_json(output_dir / "result.json", result)
            write_json(output_dir / "network.json", network)

    return result


def recommended_next_step(headless_result: str | None, headed_result: str | None) -> str:
    if headless_result == "SUCCESS" and headed_result == "SUCCESS":
        return "PROCEED_WITH_PLAYWRIGHT_PROVIDER"
    if headless_result == "SUCCESS" and headed_result is None:
        return "PROCEED_WITH_PLAYWRIGHT_PROVIDER"
    if headless_result != "SUCCESS" and headed_result == "SUCCESS":
        return "HEADED_ONLY_NOT_SUITABLE_FOR_SERVER"
    if "CAPTCHA_REQUIRED" in {headless_result, headed_result}:
        return "CAPTCHA_REQUIRES_OFFICIAL_INTEGRATION"
    if "SECURITY_CHALLENGE" in {headless_result, headed_result}:
        return "BLOCKED_BY_SECURITY"
    return "INCONCLUSIVE"


async def amain() -> int:
    parser = argparse.ArgumentParser(description="Diagnose Mais Padrão access with plain Playwright.")
    parser.add_argument("--headless", type=parse_bool, default=True, help="true or false")
    parser.add_argument("--both", action="store_true", help="Run headless first, then headed")
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--settle-seconds", type=float, default=5.0)
    parser.add_argument("--output-dir", default="output/maispadrao_playwright")
    args = parser.parse_args()

    base_output = Path(args.output_dir)
    if args.both:
        headless = await run_mode(True, args.timeout_seconds, base_output / "headless", args.settle_seconds)
        headed = await run_mode(False, args.timeout_seconds, base_output / "headed", args.settle_seconds)
        comparison = {
            "headless": headless["result"],
            "headed": headed["result"],
            "recommended_next_step": recommended_next_step(headless["result"], headed["result"]),
        }
        write_json(base_output / "comparison.json", comparison)
        print(json.dumps(comparison, ensure_ascii=False, indent=2))
        return 0 if "SUCCESS" in {headless["result"], headed["result"]} else 1

    result = await run_mode(args.headless, args.timeout_seconds, base_output, args.settle_seconds)
    summary = {
        "mode": result["mode"],
        "result": result["result"],
        "status": result["main_navigation"].get("status"),
        "final_url": result["main_navigation"].get("final_url"),
        "cards_count": result["main_navigation"].get("cards_count"),
        "listing_keys_count": result["main_navigation"].get("listing_keys_count"),
        "endpoint_status": result["pagination_api"].get("status"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if result["result"] == "SUCCESS" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(amain()))
