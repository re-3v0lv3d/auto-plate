#!/usr/bin/env python3
"""Sonda de reconocimiento de la API privada de auto-info.gratis.

Reproduce el método usado para descubrir los parámetros de /api.php cuando no
hay documentación: se envía cada candidato como array (`param[]=x`). El script
PHP pasa los valores por `mysqli_real_escape_string()`, que en PHP 7 emite un
Warning con el nombre del fichero y la línea. Eso confirma qué nombres existen
y en qué orden se leen.

Uso:
    python tools/probe_api.py            # descubrimiento completo
    python tools/probe_api.py --check    # solo comprueba la firma actual
"""

from __future__ import annotations

import argparse
import re
import sys

import requests

BASE = "https://auto-info.gratis"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

CANDIDATES = [
    "version", "pin", "access", "plate", "country", "action", "lang",
    "numer", "kraj", "vin", "refid", "job", "job_id", "id", "token", "key",
    "hash", "sign", "user", "login", "pass", "password", "email", "uid",
    "base", "nr_bazy", "baza", "db", "source", "server", "matricula", "pais",
    "idioma", "accion", "clave", "usuario", "contrasena", "api_key", "apikey",
    "callback", "data", "format", "type", "mode", "task", "queue", "status",
]

WARNING = re.compile(r"<b>([^<]+)</b>[^<]*line <b>(\d+)</b>")


def probe(session: requests.Session, name: str) -> tuple[str, str] | None:
    response = session.get(f"{BASE}/api.php", params={"version": "2", f"{name}[]": "x"}, timeout=20)
    match = WARNING.search(response.text)
    if match:
        return match.group(1), match.group(2)
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="solo la firma detectada")
    args = parser.parse_args()

    session = requests.Session()
    session.headers.update({"User-Agent": UA})

    if not args.check:
        print("Buscando parámetros por el oráculo de warnings de PHP…\n")
        found: list[tuple[int, str, str]] = []
        for name in CANDIDATES:
            hit = probe(session, name)
            if hit:
                found.append((int(hit[1]), name, hit[0]))
        if not found:
            print("No se detectaron parámetros (¿PHP >= 8 o el aviso está silenciado?).")
            return 1
        for line, name, _file in sorted(found):
            print(f"  línea {line:>3}  {name}")
        print("\nFirma detectada:")

    params = {
        "version": "2",
        "pin": "<PIN>",
        "access": "<CLAVE>",
        "plate": "1234ABC",
        "country": "ES",
        "action": "check",
        "lang": "es",
    }
    print(f"  GET {BASE}/api.php?" + "&".join(f"{k}={v}" for k, v in params.items()))

    response = session.get(f"{BASE}/api.php", params={**params, "pin": "", "access": ""}, timeout=20)
    print(f"\nSin credenciales -> {response.status_code}: {response.text[:200]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
