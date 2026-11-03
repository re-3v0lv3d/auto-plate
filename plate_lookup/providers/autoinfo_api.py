"""Cliente de la API privada de auto-info.gratis (/api.php).

Ingeniería inversa (ver docs/api-autoinfo.md):

    GET /api.php?version=2
        &pin=<PIN de la cuenta profesional>
        &access=<clave de acceso>
        &plate=<matrícula>
        &country=<código ISO de 2 letras>
        &action=check
        &lang=es

Respuesta:
    {"status": bool, "refid": "...", "results": ..., "job_status": "...",
     "error": {"error": "...", "error_number": N}}

Este proveedor solo se activa si AUTOINFO_PIN y AUTOINFO_ACCESS están
configurados. Sin credenciales válidas la API responde error_number 3
("some variables are missing"), que es su error genérico de autenticación.
"""

from __future__ import annotations

import re
import time
import unicodedata
from typing import Any

import requests

from ..config import settings
from .base import ProviderError, ProviderResult

# Alias de campo -> nombre canónico. Se comparan en minúsculas y sin acentos.
FIELD_ALIASES: dict[str, str] = {
    # marca
    "marka": "make", "marca": "make", "make": "make", "brand": "make",
    "producent": "make", "fabricante": "make", "manufacturer": "make",
    "marke": "make", "marque": "make", "casa": "make", "hersteller": "make",
    # modelo
    "model": "model", "modelo": "model", "modell": "model", "modele": "model",
    # versión
    "wersja": "variant", "version": "variant", "versione": "variant", "variante": "variant",
    "wersja_nadwozia": "variant",
    # año
    "rok": "year", "rok_produkcji": "year", "year": "year", "ano": "year",
    "anno": "year", "baujahr": "year", "anio": "year", "año": "year",
    "ano_de_produccion": "year", "ano_produccion": "year",
    "ano_de_fabricacion": "year",
    # primera matriculación
    "data_pierwszej_rejestracji": "first_registration",
    "pierwsza_rejestracja": "first_registration",
    "data_rejestracji": "first_registration",
    "first_registration": "first_registration",
    "fecha_matriculacion": "first_registration",
    "fecha_de_matriculacion": "first_registration",
    "immatriculation": "first_registration",
    "erstzulassung": "first_registration",
    "inicio_de_produccion": "first_registration",
    "inicio_produccion": "first_registration",
    "fecha_de_inicio_de_produccion": "first_registration",
    # VIN
    "vin": "vin", "nr_vin": "vin", "numer_vin": "vin", "bastidor": "vin",
    # combustible
    "paliwo": "fuel", "fuel": "fuel", "combustible": "fuel", "carburant": "fuel",
    "kraftstoff": "fuel", "combustibile": "fuel",
    "tipo_de_combustible": "fuel", "combustible_tipo": "fuel",
    # cilindrada
    "pojemnosc": "engine_cc", "pojemnosc_silnika": "engine_cc",
    "cilindrada": "engine_cc", "engine_cc": "engine_cc", "displacement": "engine_cc",
    "hubraum": "engine_cc", "cilindrata": "engine_cc", "cylindree": "engine_cc",
    "capacidad_del_motor": "engine_cc", "capacidad_motor": "engine_cc",
    # potencia
    "moc": "power_hp", "moc_silnika": "power_hp", "potencia": "power_hp",
    "power": "power_hp", "power_hp": "power_hp", "leistung": "power_hp",
    "potenza": "power_hp", "puissance": "power_hp",
    "potencia_en_hp": "power_hp", "potencia_hp": "power_hp",
    "potencia_en_kw": "power_kw", "potencia_kw": "power_kw",
    # color
    "kolor": "color", "color": "color", "colour": "color", "farbe": "color",
    "colore": "color", "couleur": "color",
    # carrocería
    "nadwozie": "body", "body": "body", "carroceria": "body", "karosserie": "body",
    "carrozzeria": "body", "carrosserie": "body",
    # puertas / plazas
    "drzwi": "doors", "doors": "doors", "puertas": "doors", "turen": "doors",
    "numero_de_puertas": "doors", "numero_puertas": "doors",
    "miejsca": "seats", "seats": "seats", "plazas": "seats", "sitze": "seats",
    # estado (baja/alta) y titulares
    "baja": "status", "fecha_de_baja": "status_date", "estado": "status",
    "situacion": "status", "situación": "status", "estado_del_vehiculo": "status",
    "titulares": "owners_count", "numero_de_titulares": "owners_count",
    "n_de_titulares": "owners_count", "propietarios": "owners_count",
    "numero_de_propietarios": "owners_count", "historial_de_titulares": "owners_count",
    # país de registro
    "pais_de_registro": "registry_country", "kraj_rejestracji": "registry_country",
    "country_of_registration": "registry_country",
}

INT_FIELDS = {"year", "engine_cc", "power_hp", "doors", "seats", "owners_count"}


_SPECIAL_LETTERS = str.maketrans(
    {"ł": "l", "ø": "o", "đ": "d", "ß": "ss", "æ": "ae", "œ": "oe", "ı": "i"}
)


def _canonical_key(key: str) -> str | None:
    text = unicodedata.normalize("NFKD", key.strip().lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.translate(_SPECIAL_LETTERS)
    norm = text.replace(" ", "_").replace("-", "_").replace(".", "")
    norm = re.sub(r"_+", "_", norm).strip("_")
    return FIELD_ALIASES.get(norm)


def _walk(value: Any, out: dict[str, Any]) -> None:
    """Recorre la respuesta y recoge pares campo/valor, sea cual sea su forma."""
    if isinstance(value, dict):
        for key, item in value.items():
            canon = _canonical_key(str(key))
            if canon and not isinstance(item, (dict, list)) and item not in (None, ""):
                out.setdefault(canon, item)
            else:
                _walk(item, out)
    elif isinstance(value, list):
        for item in value:
            _walk(item, out)


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value)
    grouped = re.search(r"\d{1,3}(?:[ .]\d{3})+(?!\d)", text)
    if grouped:
        return int(re.sub(r"\D", "", grouped.group()))
    first = re.search(r"\d+", text)
    return int(first.group()) if first else None


def normalize_result(results: Any) -> dict[str, Any]:
    collected: dict[str, Any] = {}
    _walk(results, collected)
    for key in list(collected):
        if key in INT_FIELDS:
            collected[key] = _to_int(collected[key])
    return collected


class AutoInfoApiProvider:
    name = "autoinfo-api"

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
            }
        )

    def available(self) -> bool:
        return settings.pro_api_configured

    def lookup(self, plate: str, country: str, captcha_token: str | None = None) -> ProviderResult:
        params = {
            "version": "2",
            "pin": settings.autoinfo_pin,
            "access": settings.autoinfo_access,
            "plate": plate,
            "country": country,
            "action": settings.autoinfo_action,
            "lang": settings.autoinfo_lang,
        }
        started = time.monotonic()
        try:
            response = self.session.get(
                f"{settings.autoinfo_base}/api.php",
                params=params,
                timeout=settings.autoinfo_timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise ProviderError(f"API no disponible: {exc}") from exc

        if not isinstance(payload, dict):
            raise ProviderError("Respuesta de API con formato inesperado")

        error = payload.get("error") or {}
        if error:
            number = error.get("error_number")
            message = error.get("error", "error desconocido")
            if number == 3:
                raise ProviderError(
                    "La API rechaza las credenciales (error 3). "
                    "Configura AUTOINFO_PIN y AUTOINFO_ACCESS válidos."
                )
            raise ProviderError(f"API error {number}: {message}")

        data = normalize_result(payload.get("results"))
        found = bool(payload.get("status")) and bool(data)
        return ProviderResult(
            provider=self.name,
            found=found,
            data=data,
            raw=payload,
            note=f"{(time.monotonic() - started) * 1000:.0f} ms",
        )
