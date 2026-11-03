"""Orquestación: caché -> proveedores -> persistencia."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from . import db
from .config import settings
from .normalize import InvalidPlate, Plate, normalize_plate
from .providers.autoinfo_api import AutoInfoApiProvider
from .providers import historialvehiculo
from .providers.autoinfo_web import AutoInfoWebProvider
from .providers.historialvehiculo import HistorialVehiculoProvider
from .providers.base import CaptchaRequired, ProviderError
from .store import get_storage

PROVIDERS = [AutoInfoApiProvider(), AutoInfoWebProvider(), HistorialVehiculoProvider()]

# Campos que indican que la ficha es un informe real y no solo un listado.
STRONG_FIELDS = ("vin", "year", "first_registration", "engine_cc", "power_hp", "fuel")


@dataclass(slots=True)
class LookupOutcome:
    plate: Plate
    vehicle: db.Vehicle | None = None
    cached: bool = False
    partial: bool = False
    captcha_required: bool = False
    sitekey: str | None = None
    attempts: list[dict[str, Any]] = field(default_factory=list)
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "plate": self.plate.to_dict(),
            "vehicle": self.vehicle.to_dict() if self.vehicle else None,
            "cached": self.cached,
            "partial": self.partial,
            "captcha_required": self.captcha_required,
            "sitekey": self.sitekey,
            "attempts": self.attempts,
            "message": self.message,
        }


def _is_fresh(vehicle: db.Vehicle) -> bool:
    if not vehicle.updated_at:
        return False
    age = time.time() - vehicle.updated_at
    return age < settings.cache_ttl_days * 86400


def _vehicle_from_data(
    plate: Plate, data: dict[str, Any], source: str, extra: dict[str, Any] | None = None
) -> db.Vehicle:
    complete = any(data.get(field) for field in STRONG_FIELDS)
    merged_extra = dict(extra or {})
    merged_extra["unmapped"] = {
        k: v for k, v in data.items() if k not in _KNOWN_FIELDS and k != "extra"
    }
    return db.Vehicle(
        plate=plate.display,
        country=plate.country,
        make=data.get("make"),
        model=data.get("model"),
        variant=data.get("variant"),
        year=data.get("year"),
        first_registration=data.get("first_registration"),
        vin=data.get("vin"),
        fuel=_normalize_fuel(data.get("fuel")),
        engine_cc=data.get("engine_cc"),
        power_hp=data.get("power_hp"),
        color=data.get("color"),
        body=data.get("body"),
        doors=data.get("doors"),
        seats=data.get("seats"),
        status=_normalize_status(data.get("status")),
        owners_count=_to_count(data.get("owners_count")),
        env_label=data.get("env_label"),
        source=source,
        confidence=0.9 if complete else 0.6,
        complete=complete,
        extra=merged_extra,
    )


_KNOWN_FIELDS = {
    "make", "model", "variant", "year", "first_registration", "vin", "fuel",
    "engine_cc", "power_hp", "color", "body", "doors", "seats",
    "status", "owners_count", "env_label",
}

_FUEL_MAP = {
    "petrol": "Gasolina",
    "gasoline": "Gasolina",
    "benzyna": "Gasolina",
    "diesel": "Diésel",
    "oil": "Diésel",
    "hybrid": "Híbrido",
    "hybryda": "Híbrido",
    "electric": "Eléctrico",
    "elektryczny": "Eléctrico",
    "lpg": "GLP",
    "cng": "GNC",
}


def _normalize_status(value: str | None) -> str | None:
    """Normaliza a 'baja' o 'alta' cuando la fuente lo indica."""
    if not value:
        return None
    text = str(value).strip().lower()
    if "baja" in text or text in {"si", "sí", "s"}:
        return "baja"
    if "alta" in text or "circul" in text or text in {"no", "activo"}:
        return "alta"
    return str(value).strip()


def _to_count(value: object) -> int | None:
    if value is None:
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return int(digits) if digits else None


def _normalize_fuel(value: str | None) -> str | None:
    if not value:
        return value
    return _FUEL_MAP.get(value.strip().lower(), value)


def _merge_data(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """Fusiona datos de varias fuentes sin pisar lo bueno con nulos."""
    merged = dict(base)
    for key, value in incoming.items():
        if value is None or value == "":
            continue
        if key == "extra" and isinstance(value, dict):
            current = merged.get("extra") if isinstance(merged.get("extra"), dict) else {}
            merged["extra"] = {**current, **value}
        elif key == "status":
            if merged.get("status") != "baja":
                merged["status"] = value
        elif key == "owners_count":
            merged[key] = max(_to_count(merged.get(key)) or 0, _to_count(value) or 0) or None
        elif merged.get(key) in (None, ""):
            merged[key] = value
    return merged


def lookup(
    raw_plate: str,
    country: str = "ES",
    captcha_token: str | None = None,
    refresh: bool = False,
) -> LookupOutcome:
    plate = normalize_plate(raw_plate, country)
    storage = get_storage()
    cached = storage.get_vehicle(plate.normalized, plate.country)

    if cached and not refresh and _is_fresh(cached) and cached.complete:
        return LookupOutcome(plate=plate, vehicle=cached, cached=True, message="Resultado en caché")

    attempts: list[dict[str, Any]] = []
    captcha_error: CaptchaRequired | None = None
    last_error: str | None = None
    found_any = False
    collected: dict[str, Any] = {}
    sources: list[str] = []

    for provider in PROVIDERS:
        if not provider.available():
            continue
        started = time.monotonic()
        try:
            result = provider.lookup(plate.normalized, plate.country, captcha_token)
        except CaptchaRequired as exc:
            captcha_error = exc
            attempts.append(
                {"provider": provider.name, "status": "captcha_required",
                 "ms": int((time.monotonic() - started) * 1000)}
            )
            storage.log_lookup(plate.normalized, plate.country, provider.name, "captcha_required")
            continue
        except ProviderError as exc:
            last_error = str(exc)
            attempts.append(
                {"provider": provider.name, "status": "error", "detail": last_error,
                 "ms": int((time.monotonic() - started) * 1000)}
            )
            storage.log_lookup(
                plate.normalized, plate.country, provider.name, "error", last_error,
                int((time.monotonic() - started) * 1000),
            )
            continue

        duration = int((time.monotonic() - started) * 1000)
        attempts.append({"provider": provider.name, "status": "ok", "ms": duration})
        storage.log_lookup(plate.normalized, plate.country, provider.name, "ok", None, duration)

        if not result.found:
            continue

        found_any = True
        sources.append(result.provider)
        collected = _merge_data(collected, result.data)
        if result.html:
            storage.save_report(plate.normalized, plate.country, result.provider, result.html)

    if found_any:
        vehicle = _vehicle_from_data(plate, collected, "+".join(sources), collected.get("extra"))
        vehicle = storage.upsert_vehicle(vehicle, plate.normalized)
        return LookupOutcome(
            plate=plate,
            vehicle=vehicle,
            cached=False,
            partial=not vehicle.complete,
            attempts=attempts,
        )

    if cached:
        return LookupOutcome(
            plate=plate,
            vehicle=cached,
            cached=True,
            partial=not cached.complete,
            attempts=attempts,
            captcha_required=captcha_error is not None,
            sitekey=captcha_error.sitekey if captcha_error else None,
            message="Datos en caché (no se pudo actualizar)",
        )

    return LookupOutcome(
        plate=plate,
        cached=False,
        attempts=attempts,
        captcha_required=captcha_error is not None,
        sitekey=captcha_error.sitekey if captcha_error else None,
        message=last_error or "No hay datos para esta matrícula",
    )


def merge_historial(raw_plate: str, country: str, source: str) -> LookupOutcome:
    """Fusiona la ficha de HistorialVehículo a partir de su enlace/ID."""
    plate = normalize_plate(raw_plate, country)
    info = historialvehiculo.fetch(source)
    mapped = historialvehiculo.map_vehicle(info)

    storage = get_storage()
    existing = storage.get_vehicle(plate.normalized, plate.country)
    extra = dict(existing.extra) if existing else {}
    extra.update(mapped.pop("extra", {}) or {})

    fields = {
        key: mapped.get(key)
        for key in (
            "make", "model", "variant", "year", "first_registration", "vin",
            "fuel", "engine_cc", "power_hp", "color", "body", "doors", "seats",
            "status", "owners_count", "env_label",
        )
    }
    vehicle = db.Vehicle(
        plate=plate.display,
        country=plate.country,
        source="historialvehiculo",
        confidence=0.95,
        complete=True,
        extra=extra,
        **fields,
    )
    vehicle = storage.upsert_vehicle(vehicle, plate.normalized)
    return LookupOutcome(plate=plate, vehicle=vehicle, cached=False, attempts=[
        {"provider": "historialvehiculo", "status": "ok", "ms": 0}
    ])
