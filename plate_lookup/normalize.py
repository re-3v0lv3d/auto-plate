"""Normalización y validación de matrículas.

El sistema trabaja siempre con una forma canónica: mayúsculas, sin espacios,
guiones ni puntos. Se guarda además la forma "bonita" para mostrar.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Países soportados por auto-info.gratis en sus listados públicos.
SUPPORTED_COUNTRIES: dict[str, str] = {
    "ES": "España",
    "PL": "Polonia",
    "DE": "Alemania",
    "FR": "Francia",
    "IT": "Italia",
    "NL": "Países Bajos",
    "NO": "Noruega",
    "SE": "Suecia",
    "UA": "Ucrania",
    "CZ": "República Checa",
    "DK": "Dinamarca",
    "PT": "Portugal",
    "GB": "Reino Unido",
    "BE": "Bélgica",
    "AT": "Austria",
    "CH": "Suiza",
}

# Formatos estrictos. El orden importa: el primero que casa se usa.
FORMATS: dict[str, tuple[re.Pattern[str], ...]] = {
    "ES": (
        re.compile(r"^\d{4}[A-Z]{3}$"),          # 1234ABC (desde 2000)
        re.compile(r"^[A-Z]{1,2}\d{4}[A-Z]{1,2}$"),  # M1234AB (provincial)
    ),
    "PL": (re.compile(r"^[A-Z0-9]{4,8}$"),),
    "DE": (re.compile(r"^[A-Z0-9]{4,9}$"),),
    "FR": (re.compile(r"^[A-Z]{2}\d{3}[A-Z]{2}$"), re.compile(r"^[A-Z0-9]{4,9}$")),
    "IT": (re.compile(r"^[A-Z]{2}\d{3}[A-Z]{2}$"), re.compile(r"^[A-Z0-9]{4,8}$")),
    "NL": (re.compile(r"^[A-Z0-9]{4,8}$"),),
    "PT": (re.compile(r"^[A-Z0-9]{4,8}$"),),
    "GB": (re.compile(r"^[A-Z0-9]{2,8}$"),),
}

DEFAULT_FORMAT = re.compile(r"^[A-Z0-9]{2,10}$")

_STRIP = re.compile(r"[^A-Z0-9]")


class InvalidPlate(ValueError):
    """La matrícula no encaja con el formato esperado del país."""

    def __init__(self, message: str, plate: str, country: str) -> None:
        super().__init__(message)
        self.plate = plate
        self.country = country


@dataclass(frozen=True, slots=True)
class Plate:
    raw: str
    country: str
    normalized: str
    display: str

    def to_dict(self) -> dict[str, str]:
        return {
            "raw": self.raw,
            "country": self.country,
            "normalized": self.normalized,
            "display": self.display,
        }


def _clean(raw: str) -> str:
    text = unicodedata.normalize("NFKD", raw or "")
    text = text.upper()
    return _STRIP.sub("", text)


def _pretty(normalized: str, country: str) -> str:
    if country == "ES" and re.fullmatch(r"\d{4}[A-Z]{3}", normalized):
        return f"{normalized[:4]} {normalized[4:]}"
    if country == "ES" and re.fullmatch(r"[A-Z]{1,2}\d{4}[A-Z]{1,2}", normalized):
        return normalized
    if country == "PL" and re.fullmatch(r"[A-Z]{2,3}[A-Z0-9]{4,5}", normalized):
        return normalized
    return normalized


def normalize_plate(raw: str, country: str = "ES") -> Plate:
    country = (country or "ES").strip().upper()
    if country not in SUPPORTED_COUNTRIES:
        raise InvalidPlate(f"País no soportado: {country}", raw, country)

    normalized = _clean(raw)
    if not normalized:
        raise InvalidPlate("Matrícula vacía", raw, country)

    patterns = FORMATS.get(country)
    if patterns and not any(p.match(normalized) for p in patterns):
        raise InvalidPlate(
            f"Formato de matrícula no válido para {SUPPORTED_COUNTRIES[country]}",
            raw,
            country,
        )
    if len(normalized) < 2 or len(normalized) > 10:
        raise InvalidPlate("Longitud de matrícula no válida", raw, country)

    return Plate(raw=raw, country=country, normalized=normalized, display=_pretty(normalized, country))


def split_make_model(title: str) -> tuple[str | None, str | None]:
    """Separa "MARCA MODELO..." en (marca, modelo).

    Los listados públicos de auto-info traen el título así y las marcas pueden
    tener varias palabras (ALFA ROMEO, LAND ROVER, MERCEDES BENZ...).
    """
    clean = re.sub(r"\s+", " ", (title or "").strip())
    if not clean:
        return None, None

    upper = clean.upper()
    for make in sorted(MULTIWORD_MAKES, key=len, reverse=True):
        if upper == make:
            return make, None
        if upper.startswith(make + " "):
            return make, clean[len(make):].strip() or None

    parts = clean.split(" ", 1)
    if len(parts) == 1:
        return parts[0].upper(), None
    return parts[0].upper(), parts[1].strip() or None


MULTIWORD_MAKES: frozenset[str] = frozenset(
    {
        "ALFA ROMEO",
        "ALPINE",
        "ASTON MARTIN",
        "AUDI",
        "BENTLEY",
        "BMW",
        "BYD",
        "CADILLAC",
        "CHEVROLET",
        "CHRYSLER",
        "CITROEN",
        "CUPRA",
        "DACIA",
        "DAEWOO",
        "DAIHATSU",
        "DODGE",
        "DS",
        "FERRARI",
        "FIAT",
        "FORD",
        "GENESIS",
        "GREAT WALL",
        "HONDA",
        "HUMMER",
        "HYUNDAI",
        "INFINITI",
        "ISUZU",
        "IVECO",
        "JAGUAR",
        "JEEP",
        "KIA",
        "LADA",
        "LAMBORGHINI",
        "LANCIA",
        "LAND ROVER",
        "LEXUS",
        "LINCOLN",
        "LOTUS",
        "MASERATI",
        "MAZDA",
        "MCLAREN",
        "MERCEDES",
        "MERCEDES BENZ",
        "MERCEDES-BENZ",
        "MG",
        "MINI",
        "MITSUBISHI",
        "NISSAN",
        "OPEL",
        "PEUGEOT",
        "POLESTAR",
        "PORSCHE",
        "RAM",
        "RENAULT",
        "ROLLS ROYCE",
        "ROVER",
        "SAAB",
        "SEAT",
        "SKODA",
        "SMART",
        "SSANGYONG",
        "SUBARU",
        "SUZUKI",
        "TESLA",
        "TOYOTA",
        "TRIUMPH",
        "VAUXHALL",
        "VOLKSWAGEN",
        "VOLVO",
    }
)
