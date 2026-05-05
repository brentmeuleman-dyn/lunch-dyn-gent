import json
import logging
import re
from datetime import datetime

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

GARNISH_CATEGORIES = {"Kazen", "Vleeswaren", "Vis & schaaldieren", "Veggie"}

SUBCATEGORY_PAGES = [
    ("Belegde broodjes", "https://www.keurslagerfilip.be/bestellen/belegde-broodjes", True),
    ("Schotels",         "https://www.keurslagerfilip.be/bestellen/schotels",         False),
]


def scrape_menu() -> list[dict]:
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            items = []
            for category, url, use_subheadings in SUBCATEGORY_PAGES:
                items.extend(_scrape_page(browser, url, category, use_subheadings))
            browser.close()
    except Exception as e:
        logger.error("Scraping mislukt: %s", e)
        return []

    logger.info("Scraping klaar: %d items gevonden", len(items))
    return items


def _scrape_page(browser, url: str, category: str, use_subheadings: bool = False) -> list[dict]:
    now = datetime.utcnow().isoformat()
    try:
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=30000)
        html = page.content()
        page.close()
    except Exception as e:
        logger.error("Fout bij laden %s: %s", url, e)
        return []

    soup = BeautifulSoup(html, "html.parser")
    items = []
    current_category = category
    page_title_seen = False

    for el in soup.find_all(True):
        # Detecteer sub-categorie via H1 met klasse jw-heading-130
        if use_subheadings and el.name == "h1" and "jw-heading-130" in " ".join(el.get("class", [])):
            text = el.get_text(strip=True)
            if not page_title_seen:
                page_title_seen = True  # eerste H1 is de paginatitel, overslaan
            elif text:
                current_category = text

        # Verwerk producten
        if "js-product-container" in " ".join(el.get("class", [])) and el.get("data-webshop-product"):
            item = _parse_product(el, current_category, now)
            if item:
                items.append(item)

    return items


def _parse_product(element, category: str, now: str) -> dict | None:
    try:
        data = json.loads(element["data-webshop-product"])
    except (KeyError, json.JSONDecodeError):
        return None

    name = data.get("title", "").strip()
    if not name:
        return None

    top = element.select_one(".product__top")
    top_text = top.get_text(strip=True) if top else ""
    price = _extract_price(top_text)

    garnish_price = None
    if category in GARNISH_CATEGORIES:
        price_without, price_with = _extract_garnish_prices(element)
        if price_without is not None:
            price = price_without
        if price_with is not None:
            garnish_price = price_with

    desc_el = element.select_one(".product__description")
    description = desc_el.get_text(strip=True) or None if desc_el else None

    return {
        "name": name,
        "category": category,
        "price": price,
        "garnish_price": garnish_price,
        "description": description,
        "available": True,
        "last_scraped": now,
    }


def _extract_garnish_prices(element) -> tuple[float | None, float | None]:
    price_without = None
    price_with = None
    for opt in element.select("option"):
        text = opt.get_text(strip=True)
        text_lower = text.lower()
        price = _extract_price(text)
        if price is None:
            continue
        if "zonder garnituur" in text_lower:
            price_without = price
        elif text_lower.startswith("met garnituur") and "zonder" not in text_lower and price_with is None:
            price_with = price
    return price_without, price_with


def _extract_price(text: str) -> float | None:
    match = re.search(r"(\d+)[,.](\d{2})", text)
    if match:
        try:
            return float(f"{match.group(1)}.{match.group(2)}")
        except ValueError:
            pass
    return None


def _is_product_title(element) -> bool:
    parent = element.parent
    return parent is not None and "product" in " ".join(parent.get("class", []))
