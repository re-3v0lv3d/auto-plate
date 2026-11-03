#!/usr/bin/env python3
"""Crawler de los informes listados en los sitemaps.

Los 64 sitemaps de auto-info.gratis publican ~1,66 millones de URLs
`/raport/<hash>/` (sin matrícula). Una sesión que haya pasado por
`POST /es/test/` puede abrir cualquier informe, y cada informe contiene la
matrícula y la ficha completa.

Este script es reanudable: guarda cada hash procesado en `crawl_progress`.

Uso:
    python collector/crawl_sitemaps.py --sitemaps 1-3 --limit 500
    python collector/crawl_sitemaps.py --sitemaps all --workers 4 --delay 0.5
"""

from __future__ import annotations

import argparse
import gzip
import io
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from plate_lookup import db  # noqa: E402
from plate_lookup.config import settings  # noqa: E402
from plate_lookup.normalize import normalize_plate  # noqa: E402
from plate_lookup.providers.autoinfo_web import parse_report  # noqa: E402

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
BOOTSTRAP_PLATE = "5545LML"
BOOTSTRAP_COUNTRY = "ES"

RE_LOC = re.compile(r"<loc>https://auto-info\.gratis/raport/([a-f0-9]{32})/</loc>")
RE_PLATE = re.compile(r"matr[íi]cula\s+([A-Z0-9]{2,12})", re.I)

COUNTRY_BY_NAME = {
    "españa": "ES", "espana": "ES", "spain": "ES", "hiszpania": "ES",
    "polonia": "PL", "poland": "PL", "polska": "PL",
    "alemania": "DE", "germany": "DE", "niemcy": "DE", "deutschland": "DE",
    "francia": "FR", "france": "FR", "francja": "FR",
    "italia": "IT", "italy": "IT", "włochy": "IT",
    "países bajos": "NL", "paises bajos": "NL", "netherlands": "NL", "holandia": "NL",
    "noruega": "NO", "norway": "NO", "norwegia": "NO",
    "suecia": "SE", "sweden": "SE", "szwecja": "SE",
    "ucrania": "UA", "ukraine": "UA", "ukraina": "UA",
    "república checa": "CZ", "republica checa": "CZ", "czechia": "CZ", "czechy": "CZ",
    "dinamarca": "DK", "denmark": "DK", "dania": "DK",
    "portugal": "PT", "reino unido": "GB", "united kingdom": "GB", "wielka brytania": "GB",
    "bélgica": "BE", "belgica": "BE", "belgium": "BE", "belgia": "BE",
    "austria": "AT", "suiza": "CH", "switzerland": "CH", "szwajcaria": "CH",
}

_local = threading.local()
_lock = threading.Lock()
_delay = 0.5


def thread_session() -> requests.Session:
    session = getattr(_local, "session", None)
    if session is None:
        session = requests.Session()
        session.headers.update({"User-Agent": UA, "Accept-Language": "es-ES,es;q=0.9"})
        _local.session = session
        _local.ready = False
    return session


def bootstrap(session: requests.Session) -> bool:
    """Marca la sesión como verificada haciendo una consulta de prueba."""
    base = settings.autoinfo_base
    form = f"{base}/{settings.autoinfo_lang}/sprawdzam/"
    test = f"{base}/{settings.autoinfo_lang}/test/"
    try:
        session.get(form, timeout=60)
        session.post(
            form,
            data={"numer": BOOTSTRAP_PLATE, "kraj": BOOTSTRAP_COUNTRY, "g-recaptcha-response": "x"},
            headers={"Referer": form},
            timeout=60,
        )
        job = session.post(
            test,
            data={"numer": BOOTSTRAP_PLATE, "kraj": BOOTSTRAP_COUNTRY},
            headers={"Referer": form, "X-Requested-With": "XMLHttpRequest"},
            timeout=120,
        )
        return job.text.strip().startswith("/")
    except requests.RequestException:
        return False


def list_sitemaps(first: int, last: int) -> list[str]:
    return [
        f"{settings.autoinfo_base}/sitemaps/sitemap-raporty-{n:04d}.xml.gz"
        for n in range(first, last + 1)
    ]


def sitemap_hashes(url: str, session: requests.Session) -> list[str]:
    response = session.get(url, timeout=120)
    response.raise_for_status()
    raw = gzip.decompress(response.content) if response.content[:2] == b"\x1f\x8b" else response.content
    return RE_LOC.findall(io.BytesIO(raw).read().decode("utf-8", "replace"))


def parse_country(data: dict) -> str | None:
    name = str(data.get("registry_country") or "").strip().lower()
    if not name:
        return None
    for label, code in sorted(COUNTRY_BY_NAME.items(), key=lambda item: -len(item[0])):
        if name.startswith(label):
            return code
    return None


def fetch_report(report_hash: str) -> tuple[str, str, dict | None]:
    """Devuelve (hash, estado, datos)."""
    global _delay
    time.sleep(_delay)
    session = thread_session()
    if not getattr(_local, "ready", False):
        if not bootstrap(session):
            return report_hash, "bootstrap_error", None
        _local.ready = True

    url = f"{settings.autoinfo_base}/{settings.autoinfo_lang}/raport/{report_hash}/"
    for attempt in range(3):
        try:
            response = session.get(url, timeout=60)
        except requests.RequestException as exc:
            if attempt == 2:
                return report_hash, f"error:{exc.__class__.__name__}", None
            time.sleep(3)
            continue

        if response.status_code == 200 and "tymczasowo niedostępny" not in response.text:
            break

        # La sesión caducó o el informe aún no está listo: re-verificamos.
        _local.ready = False
        if not bootstrap(session):
            return report_hash, "bootstrap_error", None
        _local.ready = True
        time.sleep(4 * (attempt + 1))
    else:
        return report_hash, "unavailable", None

    html = response.text
    data = parse_report(html)
    plate_match = RE_PLATE.search(html)
    if not plate_match or not data:
        return report_hash, "sin_datos", None

    data["_plate"] = plate_match.group(1).strip().upper()
    return report_hash, "ok", data


def store(report_hash: str, data: dict) -> None:
    raw_plate = data.pop("_plate")
    country = parse_country(data) or "ES"
    try:
        plate = normalize_plate(raw_plate, country)
    except ValueError:
        country = "ES"
        plate = normalize_plate(raw_plate, "ES")

    vehicle = db.Vehicle(
        plate=plate.display,
        country=plate.country,
        make=data.get("make"),
        model=data.get("model"),
        variant=data.get("variant"),
        year=data.get("year"),
        first_registration=data.get("first_registration"),
        vin=data.get("vin"),
        fuel=data.get("fuel"),
        engine_cc=data.get("engine_cc"),
        power_hp=data.get("power_hp"),
        color=data.get("color"),
        body=data.get("body"),
        doors=data.get("doors"),
        seats=data.get("seats"),
        source="autoinfo-report",
        confidence=0.95,
        complete=True,
        extra={"report_hash": report_hash},
    )
    db.upsert_vehicle(vehicle, plate.normalized)
    db.mark_crawl(report_hash, plate.normalized, plate.country, "ok")


def parse_range(raw: str, total: int = 64) -> tuple[int, int]:
    if raw.lower() == "all":
        return 1, total
    if "-" in raw:
        a, b = raw.split("-", 1)
        return int(a), int(b)
    return int(raw), int(raw)


def main() -> int:
    parser = argparse.ArgumentParser(description="Crawler de informes por sitemap")
    parser.add_argument("--sitemaps", default="1", help="N, A-B o all")
    parser.add_argument("--limit", type=int, default=0, help="máximo de informes (0 = sin límite)")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--delay", type=float, default=0.5, help="pausa por worker entre informes")
    parser.add_argument("--fresh", action="store_true", help="no saltar hashes ya procesados")
    args = parser.parse_args()
    global _delay
    _delay = max(args.delay, 0.0)

    db.init_db()
    session = requests.Session()
    session.headers.update({"User-Agent": UA})

    first, last = parse_range(args.sitemaps)
    hashes: list[str] = []
    for url in list_sitemaps(first, last):
        try:
            found = sitemap_hashes(url, session)
        except (requests.RequestException, OSError) as exc:
            print(f"[!] {url}: {exc}")
            continue
        print(f"[+] {url.rsplit('/', 1)[-1]}: {len(found)} URLs")
        hashes.extend(found)

    if not args.fresh:
        pending = [h for h in hashes if not db.crawl_seen(h)]
    else:
        pending = hashes
    if args.limit:
        pending = pending[: args.limit]

    print(f"[i] {len(hashes)} hashes, {len(pending)} pendientes, {args.workers} workers")
    if not pending:
        print("Nada que hacer.")
        return 0

    started = time.time()
    done = ok = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futures = {pool.submit(fetch_report, h): h for h in pending}
        for future in as_completed(futures):
            report_hash = futures[future]
            try:
                _, status, data = future.result()
            except Exception as exc:  # noqa: BLE001 - un hash no debe tumbar el crawl
                status, data = f"exception:{exc.__class__.__name__}", None

            if status == "ok" and data:
                store(report_hash, data)
                ok += 1
            else:
                db.mark_crawl(report_hash, None, None, status)
            done += 1
            if done % 25 == 0 or done == len(pending):
                rate = done / max(time.time() - started, 1e-9)
                print(f"[.] {done}/{len(pending)} · ok {ok} · {rate:.1f}/s")

    print(f"\nListo: {ok}/{done} informes nuevos en {(time.time() - started):.0f}s")
    print(db.stats())
    print("crawl:", db.crawl_stats())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
