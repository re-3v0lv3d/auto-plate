#!/usr/bin/env python3
"""Recolector de los listados públicos de auto-info.gratis.

Los listados `/{lang}/list/{CC}/?page=N` publican, sin captcha, parejas
matrícula + "MARCA MODELO" (y el hash del informe). Con esto se llena la caché
local y la búsqueda responde al instante para miles de matrículas reales.

Uso:
    python collector/harvest_autoinfo.py --countries ES,PL --pages 1-20
    python collector/harvest_autoinfo.py --countries ES --pages 1-400 --delay 5
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from plate_lookup import db  # noqa: E402
from plate_lookup.config import settings  # noqa: E402
from plate_lookup.normalize import SUPPORTED_COUNTRIES, normalize_plate, split_make_model  # noqa: E402

ROW = re.compile(
    r'href="/(?:[a-z]{2}/)?raport/([a-f0-9]{32})/"\s+title="([^"]*)"[^>]*>([^<]*)<',
    re.I,
)
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def parse_page(html: str, country: str) -> list[tuple[str, str, str, str]]:
    rows: list[tuple[str, str, str, str]] = []
    for report_hash, title, plate in ROW.findall(html):
        plate = plate.strip()
        title = title.strip()
        if not plate or plate == " ":
            continue
        try:
            normalized = normalize_plate(plate, country)
        except ValueError:
            continue
        rows.append((normalized.normalized, plate, title, report_hash))
    return rows


def harvest(countries: list[str], pages: range, delay: float, session: requests.Session) -> int:
    total = 0
    for country in countries:
        for page in pages:
            url = f"{settings.autoinfo_base}/{settings.autoinfo_lang}/list/{country}/?page={page}"
            try:
                response = session.get(url, timeout=25)
            except requests.RequestException as exc:
                print(f"[!] {country} p{page}: {exc}")
                time.sleep(delay * 2)
                continue

            if response.status_code == 429:
                print(f"[!] rate limit en {country} p{page}; esperando 60 s")
                time.sleep(60)
                continue
            if response.status_code != 200:
                print(f"[!] {country} p{page}: HTTP {response.status_code}")
                time.sleep(delay)
                continue

            rows = parse_page(response.text, country)
            if not rows:
                print(f"[.] {country} p{page}: fin del listado")
                break

            for normalized, display, title, report_hash in rows:
                make, model = split_make_model(title)
                vehicle = db.Vehicle(
                    plate=display,
                    country=country,
                    make=make,
                    model=model,
                    source="autoinfo-list",
                    confidence=0.6,
                    complete=False,
                    extra={"report_hash": report_hash},
                )
                db.upsert_vehicle(vehicle, normalized)
            total += len(rows)
            print(f"[+] {country} p{page}: {len(rows)} matrículas (total {total})")
            time.sleep(delay)
    return total


def parse_pages(raw: str) -> range:
    if "-" in raw:
        start, end = raw.split("-", 1)
        return range(int(start), int(end) + 1)
    return range(1, int(raw) + 1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Recolector de listados públicos")
    parser.add_argument("--countries", default="ES", help="lista separada por comas, o ALL")
    parser.add_argument("--pages", default="1-20", help="N o A-B")
    parser.add_argument("--delay", type=float, default=5.0, help="segundos entre peticiones (robots.txt: 5)")
    args = parser.parse_args()

    countries = (
        list(SUPPORTED_COUNTRIES)
        if args.countries.upper() == "ALL"
        else [c.strip().upper() for c in args.countries.split(",") if c.strip()]
    )
    unknown = [c for c in countries if c not in SUPPORTED_COUNTRIES]
    if unknown:
        print(f"[!] países desconocidos: {', '.join(unknown)}")
        return 2

    db.init_db()
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "es-ES,es;q=0.9"})

    started = time.time()
    total = harvest(countries, parse_pages(args.pages), max(args.delay, 0.5), session)
    print(
        f"\nListo: {total} matrículas en {(time.time() - started):.0f}s. "
        f"BD: {settings.db_path}"
    )
    print(db.stats())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
