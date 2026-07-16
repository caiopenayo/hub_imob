# Placeholder scraper module for a single source

async def scrape_example():
    # Return a list of normalized property dicts matching backend schema (PropertyCreate)
    return [
        {
            "external_id": "example-1",
            "source_id": "00000000-0000-0000-0000-000000000001",
            "title": "Apartamento exemplo 1",
            "description": "Apartamento de exemplo com 3 quartos no centro.",
            "price": 720000.0,
            "url": "https://example.com/anuncio/1",
            "city": "São Paulo",
            "neighborhood": "Centro",
            "bedrooms": 3,
            "bathrooms": 2,
            "area_m2": 110.0,
            "metadata_json": {"source_note": "example data"},
        }
    ]
