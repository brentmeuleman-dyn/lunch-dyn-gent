import logging
import re
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BESTELLEN_URL = "https://www.keurslagerfilip.be/bestellen"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

KNOWN_CATEGORIES = [
    "Belegde broodjes",
    "Wraps",
    "Koude schotels & maaltijden",
    "Bakkerij",
    "Drankjes",
    "Schotels",
]


def scrape_menu() -> list[dict]:
    """Haal menu-items op van keurslagerfilip.be/bestellen."""
    try:
        response = requests.get(BESTELLEN_URL, headers=HEADERS, timeout=15)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.error("Scraping mislukt: %s", e)
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    items = _parse_products(soup)

    if not items:
        logger.warning(
            "Geen producten gevonden via scraping. "
            "De website gebruikt mogelijk JavaScript-rendering. "
            "Voeg producten handmatig toe via de admin-pagina."
        )

    logger.info("Scraping klaar: %d items gevonden", len(items))
    return items


def _parse_products(soup: BeautifulSoup) -> list[dict]:
    now = datetime.utcnow().isoformat()

    # Probeer WooCommerce-stijl product-lijsten
    products = soup.select("li.product, .product-item, [class*='product-card']")

    if products:
        return [item for p in products if (item := _parse_product_element(p, soup, now))]

    # Fallback: zoek per sectie op categorie-headers
    return _parse_by_sections(soup, now)


def _parse_product_element(element, soup: BeautifulSoup, now: str) -> Optional[dict]:
    name = _first_text(element, [
        ".woocommerce-loop-product__title",
        ".product-title", "h2", "h3", "h4",
        "[class*='title']", "[class*='name']",
    ])
    if not name or len(name) < 2:
        return None

    return {
        "name": name.strip(),
        "category": _detect_category(element, soup) or "Overige",
        "price": _extract_price(element),
        "description": _first_text(element, [
            ".description", ".short-description", "p", "[class*='desc']"
        ]),
        "available": True,
        "last_scraped": now,
    }


def _parse_by_sections(soup: BeautifulSoup, now: str) -> list[dict]:
    """Zoek producten georganiseerd onder categorie-headers."""
    items = []
    current_category = "Overige"

    for el in soup.find_all(["h1", "h2", "h3", "h4", "li"]):
        text = el.get_text(strip=True)
        if not text:
            continue

        # Detecteer categorie-header
        for cat in KNOWN_CATEGORIES:
            if cat.lower() in text.lower() and el.name in ["h1", "h2", "h3", "h4"]:
                current_category = cat
                break

        # Productregels zijn korte <li>-elementen
        if el.name == "li" and 3 < len(text) < 150:
            items.append({
                "name": text.split("€")[0].strip(),
                "category": current_category,
                "price": _extract_price(el),
                "description": None,
                "available": True,
                "last_scraped": now,
            })

    return items


def _first_text(element, selectors: list[str]) -> Optional[str]:
    for sel in selectors:
        found = element.select_one(sel)
        if found:
            text = found.get_text(strip=True)
            if text:
                return text
    return None


def _extract_price(element) -> Optional[float]:
    price_el = element.select_one(
        ".price, .woocommerce-Price-amount, [class*='price']"
    )
    raw = price_el.get_text(strip=True) if price_el else element.get_text()
    match = re.search(r"(\d+)[,.](\d{2})\s*€|€\s*(\d+)[,.](\d{2})", raw)
    if match:
        g = match.groups()
        try:
            return float(f"{g[0] or g[2]}.{g[1] or g[3]}")
        except (TypeError, ValueError):
            pass
    return None


def _detect_category(element, soup: BeautifulSoup) -> Optional[str]:
    # data-attribuut (bijv. WooCommerce)
    cat = element.get("data-category") or element.get("data-product-category")
    if cat:
        return cat

    # Zoek omhoog in de DOM naar een categorie-header
    parent = element.parent
    while parent and parent.name != "body":
        for header in parent.find_all(["h1", "h2", "h3", "h4"], recursive=False):
            text = header.get_text(strip=True)
            for known in KNOWN_CATEGORIES:
                if known.lower() in text.lower():
                    return known
        parent = parent.parent

    return None
