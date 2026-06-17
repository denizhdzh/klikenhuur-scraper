#!/usr/bin/env python3
"""
Nijmegen Werkruimte Scraper
Sources: Marktplaats, CompanySpace, FundaInBusiness
Filters: max €600/m, min 15 m²
"""

import os
import re
import json
import requests
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup

SEEN_FILE = Path(__file__).parent / "seen_listings.json"
LISTINGS_FILE = Path(__file__).parent / "listings.json"

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "klikenhuur-deniz")

MAX_PRICE = 600
MIN_AREA = 15

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
}


def load_seen():
    if not SEEN_FILE.exists():
        return {"seen_ids": [], "last_check": None}
    with open(SEEN_FILE) as f:
        return json.load(f)


def save_seen(data):
    data["last_check"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(SEEN_FILE, "w") as f:
        json.dump(data, f, indent=2)


def save_listings(listings):
    data = {
        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "listings": listings,
    }
    with open(LISTINGS_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def parse_price(text):
    text = text.replace(".", "").replace(",", ".")
    m = re.search(r"(\d+(?:\.\d+)?)", text)
    return float(m.group(1)) if m else None


def parse_area(text):
    m = re.search(r"([\d]+(?:[.,]\d+)?)\s*m", text, re.IGNORECASE)
    return float(m.group(1).replace(",", ".")) if m else None


# ---------------------------------------------------------------------------
# Marktplaats
# ---------------------------------------------------------------------------

def fetch_marktplaats():
    listings = []
    seen_hrefs = set()

    queries = [
        "bedrijfsruimte+nijmegen",
        "werkruimte+nijmegen",
        "atelier+nijmegen",
        "studio+ruimte+nijmegen",
    ]

    for query in queries:
        url = f"https://www.marktplaats.nl/q/{query}/"
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            if resp.status_code != 200:
                print(f"  Marktplaats {query}: HTTP {resp.status_code}")
                continue

            soup = BeautifulSoup(resp.text, "html.parser")

            for a in soup.find_all("a", href=re.compile(r"/v/zakelijke-goederen/bedrijfs-onroerend-goed/")):
                href = a.get("href", "").split("?")[0]
                if href in seen_hrefs:
                    continue
                seen_hrefs.add(href)

                id_match = re.search(r"/([am]\d+)-", href)
                if not id_match:
                    continue
                listing_id = f"mp_{id_match.group(1)}"

                container = a
                for tag in ["li", "article"]:
                    parent = a.find_parent(tag)
                    if parent:
                        container = parent
                        break

                full_text = container.get_text(" ", strip=True)
                title = a.get_text(strip=True)[:120] or full_text[:80]

                price = None
                price_m = re.search(r"€\s*([\d.,]+)", full_text)
                if price_m:
                    price = parse_price(price_m.group(0))

                area = parse_area(title) or parse_area(full_text)

                listings.append({
                    "id": listing_id,
                    "source": "marktplaats",
                    "title": title,
                    "price": price,
                    "area": area,
                    "url": f"https://www.marktplaats.nl{href}" if href.startswith("/") else href,
                    "found_at": datetime.now().strftime("%Y-%m-%d"),
                })

        except Exception as e:
            print(f"  Marktplaats {query} hata: {e}")

    print(f"  Marktplaats: {len(listings)} ilan")
    return listings


# ---------------------------------------------------------------------------
# CompanySpace
# ---------------------------------------------------------------------------

def fetch_companyspace():
    listings = []
    url = "https://www.companyspace.com/netherlands/commercial-space-rent/nijmegen/"

    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        if resp.status_code != 200:
            print(f"  CompanySpace: HTTP {resp.status_code}")
            return listings

        soup = BeautifulSoup(resp.text, "html.parser")

        for a in soup.find_all("a", href=re.compile(r"/rent/.+/nijmegen/\d+")):
            href = a.get("href", "")
            id_match = re.search(r"/(\d+)", href)
            if not id_match:
                continue

            listing_id = f"cs_{id_match.group(1)}"
            full_text = a.get_text(" ", strip=True)

            h4 = a.find("h4")
            title = (h4.get_text(strip=True) if h4 else full_text[:120])[:120]

            price = None
            price_m = re.search(r"(?:Rent|EUR)[:\s]+Ca\.\s*([\d,]+)", full_text, re.IGNORECASE)
            if price_m:
                price = parse_price(price_m.group(1))

            area = parse_area(title) or parse_area(full_text)

            listings.append({
                "id": listing_id,
                "source": "companyspace",
                "title": title,
                "price": price,
                "area": area,
                "url": f"https://www.companyspace.com{href}" if href.startswith("/") else href,
                "found_at": datetime.now().strftime("%Y-%m-%d"),
            })

    except Exception as e:
        print(f"  CompanySpace hata: {e}")

    print(f"  CompanySpace: {len(listings)} ilan")
    return listings


# ---------------------------------------------------------------------------
# FundaInBusiness  (Playwright — Cloudflare bypass)
# ---------------------------------------------------------------------------

def fetch_fundainbusiness():
    listings = []

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  FundaInBusiness: playwright yuklu degil, atlaniyor")
        return listings

    url = "https://www.fundainbusiness.nl/alle-bedrijfsaanbod/nijmegen/huur/0-1000/permaand/sorteer-datum-af/"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="nl-NL",
            )
            page = context.new_page()

            # Stealth: hide webdriver flag
            page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

            page.goto(url, wait_until="networkidle", timeout=60000)
            page.wait_for_timeout(2000)

            html = page.content()
            browser.close()

        soup = BeautifulSoup(html, "html.parser")

        # Try multiple selectors for listing cards
        cards = soup.find_all("div", attrs={"data-object-url-title": True})

        if not cards:
            # Fallback: find all links pointing to individual listings
            cards = soup.find_all("a", href=re.compile(r"/bedrijfsaanbod/\d+"))

        for card in cards:
            a = card if card.name == "a" else card.find("a", href=re.compile(r"/bedrijfsaanbod/\d+"))
            if not a:
                continue

            href = a.get("href", "")
            id_match = re.search(r"/(\d+)", href)
            if not id_match:
                continue

            listing_id = f"funda_{id_match.group(1)}"
            full_text = card.get_text(" ", strip=True)

            title_el = card.find(["h2", "h3", "h4"], class_=re.compile(r"title|adres|object|street", re.IGNORECASE))
            title = (title_el.get_text(strip=True) if title_el else full_text[:120])[:120]

            price = None
            price_m = re.search(r"€\s*([\d.,]+)", full_text)
            if price_m:
                price = parse_price(price_m.group(0))

            area = parse_area(full_text)

            full_url = f"https://www.fundainbusiness.nl{href}" if href.startswith("/") else href

            listings.append({
                "id": listing_id,
                "source": "fundainbusiness",
                "title": title,
                "price": price,
                "area": area,
                "url": full_url,
                "found_at": datetime.now().strftime("%Y-%m-%d"),
            })

    except Exception as e:
        print(f"  FundaInBusiness hata: {e}")

    print(f"  FundaInBusiness: {len(listings)} ilan")
    return listings


# ---------------------------------------------------------------------------
# Filter + Notify
# ---------------------------------------------------------------------------

def apply_filters(listings):
    out = []
    for l in listings:
        price = l.get("price")
        area = l.get("area")
        if price is not None and price > MAX_PRICE:
            continue
        if area is not None and area < MIN_AREA:
            continue
        out.append(l)
    return out


def dedup(listings):
    seen, out = set(), []
    for l in listings:
        if l["id"] not in seen:
            seen.add(l["id"])
            out.append(l)
    return out


def send_ntfy(new_listings):
    source_labels = {
        "marktplaats": "Marktplaats",
        "companyspace": "CompanySpace",
        "fundainbusiness": "Funda in Business",
    }
    for l in new_listings:
        title = l.get("title", "Yeni ilan")[:100]
        lines = []
        if l.get("price"):
            lines.append(f"Fiyat: €{l['price']:.0f}/ay")
        if l.get("area"):
            lines.append(f"Alan: {l['area']:.0f} m²")
        lines.append(f"Kaynak: {source_labels.get(l['source'], l['source'])}")

        try:
            requests.post(
                f"https://ntfy.sh/{NTFY_TOPIC}",
                data="\n".join(lines).encode("utf-8"),
                headers={"Title": title, "Click": l["url"], "Tags": "office"},
            )
            print(f"  Bildirim: {title}")
        except Exception as e:
            print(f"  Bildirim gonderilemedi: {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print(f"Tarama basliyor... ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
    print(f"Filtreler: max €{MAX_PRICE}/ay, min {MIN_AREA} m²")

    seen_data = load_seen()
    seen_ids = set(seen_data["seen_ids"])

    all_listings = []

    print("Marktplaats...")
    all_listings.extend(fetch_marktplaats())

    print("CompanySpace...")
    all_listings.extend(fetch_companyspace())

    print("FundaInBusiness...")
    all_listings.extend(fetch_fundainbusiness())

    all_listings = dedup(all_listings)
    print(f"\nToplam ham ilan: {len(all_listings)}")

    filtered = apply_filters(all_listings)
    print(f"Filtre sonrasi: {len(filtered)} ilan")

    save_listings(filtered)

    new_listings = [l for l in filtered if l["id"] not in seen_ids]
    if new_listings:
        print(f"\n{len(new_listings)} YENI ILAN!")
        send_ntfy(new_listings)
    else:
        print("Yeni ilan yok")

    for l in all_listings:
        seen_ids.add(l["id"])
    seen_data["seen_ids"] = list(seen_ids)
    save_seen(seen_data)


if __name__ == "__main__":
    main()
