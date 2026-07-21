from __future__ import annotations

from importlib import import_module

from scrapers.core.providers import RealEstateProvider


PROVIDER_ALIASES = {
    "zimmermann": "zimoveis",
}


def normalize_provider_key(key: str) -> str:
    return PROVIDER_ALIASES.get(key, key)


def load_provider(key: str) -> RealEstateProvider | None:
    provider_key = normalize_provider_key(key)
    try:
        module = import_module(f"scrapers.sources.{provider_key}")
    except ModuleNotFoundError:
        return None
    provider = getattr(module, "provider", None)
    return provider if isinstance(provider, RealEstateProvider) else provider


def registered_provider_keys() -> set[str]:
    return {"zimoveis", "localimoveis", "pacheco"}
