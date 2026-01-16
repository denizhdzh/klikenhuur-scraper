#!/usr/bin/env python3
"""
KlikEnHuur Scraper - Yeni ilan bildirimi (ntfy.sh)
"""

import os
import requests
import json
import re
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup

# Dosya yolu
SEEN_FILE = Path(__file__).parent / "seen_listings.json"

# ntfy topic - environment variable veya default
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "klikenhuur-deniz")

# Sadece bu şehirlerden ilan gelsin
ALLOWED_CITIES = ["Nijmegen", "Arnhem"]

def load_seen_listings():
    if not SEEN_FILE.exists():
        return {"seen_ids": [], "last_check": None}
    with open(SEEN_FILE, "r") as f:
        return json.load(f)

def save_seen_listings(data):
    data["last_check"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(SEEN_FILE, "w") as f:
        json.dump(data, f, indent=2)

def fetch_listings():
    """HTML'den ilanları parse et"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    url = "https://www.klikenhuur.nl/woning-overzicht?livingUnitType=Appartement&page=1&pagesize=240"

    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        html = response.text

        soup = BeautifulSoup(html, 'html.parser')
        listings = []

        panels = soup.find_all('a', class_=re.compile(r'panel--listing'))

        for panel in panels:
            href = panel.get('href', '')
            id_match = re.search(r'/listings/([^/]+)/detail', href)
            if not id_match:
                continue

            listing_id = id_match.group(1)

            # Şehir (h4)
            city_el = panel.find('h4')
            city = city_el.get_text(strip=True) if city_el else ""

            # Sokak (h3)
            street_el = panel.find('h3')
            street = street_el.get_text(strip=True) if street_el else ""

            # Fiyat
            price_el = panel.find('p', class_='no-margin')
            price_text = price_el.get_text(strip=True) if price_el else ""
            price_match = re.search(r'€([\d.,]+)', price_text)
            price = price_match.group(1) if price_match else "?"

            # Müsaitlik tarihi
            availability_el = panel.find('div', class_='text--s')
            availability = availability_el.get_text(strip=True) if availability_el else ""
            # "Beschikbaarheid: 01-apr-2026" -> "01-apr-2026"
            availability = availability.replace("Beschikbaarheid:", "").strip()

            # Oda tipi ve m2 (btn--light divleri)
            room_type = ""
            area = ""
            buttons = panel.find_all('div', class_='btn--light')
            for btn in buttons:
                btn_text = btn.get_text(strip=True)
                if 'm' in btn_text and '2' in btn_text:
                    area_match = re.search(r'([\d.,]+)', btn_text)
                    if area_match:
                        area = area_match.group(1)
                elif btn_text in ['Kamer', 'Appartement', 'Studio']:
                    room_type = btn_text

            # Badge'ler (Gereserveerd, Short Stay, vb.)
            badges = []
            badge_wrapper = panel.find('div', class_='listing-item-badge-wrapper')
            if badge_wrapper:
                badge_divs = badge_wrapper.find_all('div', class_=re.compile(r'badge-'))
                for badge_div in badge_divs:
                    badge_text = badge_div.get_text(strip=True)
                    if badge_text:
                        badges.append(badge_text)

            listings.append({
                'id': listing_id,
                'city': city,
                'street': street,
                'price': price,
                'area': area,
                'room_type': room_type,
                'availability': availability,
                'badges': badges,
                'url': f"https://www.klikenhuur.nl{href}"
            })

        return listings

    except requests.RequestException as e:
        print(f"Site istegi basarisiz: {e}")
        return []

def send_ntfy(new_listings):
    if not new_listings:
        return

    for listing in new_listings:
        title = f"{listing['street']}, {listing['city']}"

        # Mesaj oluştur
        lines = [
            f"Fiyat: EUR {listing['price']}/ay",
            f"Alan: {listing['area']} m2",
        ]

        if listing['room_type']:
            lines.append(f"Tip: {listing['room_type']}")

        if listing['availability']:
            lines.append(f"Musait: {listing['availability']}")

        if listing['badges']:
            lines.append(f"Durum: {', '.join(listing['badges'])}")

        message = "\n".join(lines)

        try:
            requests.post(
                f"https://ntfy.sh/{NTFY_TOPIC}",
                data=message.encode('utf-8'),
                headers={
                    "Title": title,
                    "Click": listing['url'],
                    "Tags": "house"
                }
            )
            print(f"Bildirim gonderildi: {listing['street']}, {listing['city']}")
        except Exception as e:
            print(f"Bildirim gonderilemedi: {e}")

def main():
    print(f"Kontrol ediliyor... ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
    print(f"ntfy topic: {NTFY_TOPIC}")

    seen_data = load_seen_listings()
    seen_ids = set(seen_data["seen_ids"])

    listings = fetch_listings()

    if not listings:
        print("Ilan bulunamadi veya site erisilemez")
        return

    print(f"Toplam {len(listings)} ilan bulundu")

    new_listings = []
    for listing in listings:
        if listing['id'] not in seen_ids:
            seen_ids.add(listing['id'])
            # Sadece izin verilen şehirlerden bildirim gönder
            if listing['city'] in ALLOWED_CITIES:
                new_listings.append(listing)

    if new_listings:
        print(f"{len(new_listings)} YENI ILAN!")
        send_ntfy(new_listings)
    else:
        print("Yeni ilan yok")

    seen_data["seen_ids"] = list(seen_ids)
    save_seen_listings(seen_data)

if __name__ == "__main__":
    main()
