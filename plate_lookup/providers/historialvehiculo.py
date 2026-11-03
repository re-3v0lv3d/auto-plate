"""Proveedor HistorialVehículo (api.historialvehiculo.com/v2).

Ingeniería inversa (ver docs/api-historialvehiculo.md):

    GET  /v2/vehicle/{id}   -> {"infoVehicle": {...}}   (gratis, sin captcha)
    POST /v2/vehicle/search -> {identificationNumber, token}  (Turnstile)

El `id` es un SHA-256 (`bastidorItvEncrypt`) que solo se obtiene tras resolver
el Turnstile de la web. Por eso este proveedor no busca por matrícula: recibe
el enlace/ID que el usuario copia después de hacer la consulta a mano.
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any

import requests

from ..captcha import solver
from ..config import settings
from .base import CaptchaRequired, ProviderError, ProviderResult

API = "https://api.historialvehiculo.com/v2"
SITEKEY = "0x4AAAAAAA1fwEz8c6iW2gXh"
SEARCH_URL = "https://www.historialvehiculo.com/informes-gratis-vehiculos"
RE_ID = re.compile(r"\b([a-f0-9]{64})\b", re.I)

FUEL = {
    "0": "Gasolina", "1": "Diésel", "2": "Eléctrico", "3": "Otros",
    "4": "Butano", "5": "Solar", "6": "GLP", "7": "GNC", "8": "GNL",
    "9": "Hidrógeno", "A": "Biometano", "B": "Etanol", "C": "Biodiésel",
}

MOVE = {
    "1": "Matriculación", "2": "Transferencia", "3": "Baja definitiva",
    "4": "Baja definitiva (Plan Renove)", "5": "Rematriculación",
    "6": "Baja temporal", "7": "Baja definitiva por exportación",
    "8": "Matriculación vehículo especial", "9": "Matriculación temporal",
    "A": "Prórroga matrícula temporal", "B": "Paso a matrícula definitiva",
}

OWNER_TYPE = {"D": "Particular", "X": "Empresa"}

BAJA_KEYS = {"3", "4", "7"}


def extract_id(text: str) -> str | None:
    match = RE_ID.search(text or "")
    return match.group(1).lower() if match else None


def _date(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    if re.fullmatch(r"\d{8}", value):
        try:
            return datetime.strptime(value, "%d%m%Y").strftime("%d/%m/%Y")
        except ValueError:
            return value
    return value


def _year(value: str | None) -> int | None:
    if value and re.fullmatch(r"\d{8}", value):
        try:
            return datetime.strptime(value, "%d%m%Y").year
        except ValueError:
            return None
    return None


def _int(value: Any) -> int | None:
    try:
        return int(float(str(value).replace(",", ".")))
    except (TypeError, ValueError):
        return None


def _expand(transfers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cada trámite trae numTransmisiones; se expande como hace su web."""
    rows: list[dict[str, Any]] = []
    for index, transfer in enumerate(transfers):
        times = _int(transfer.get("numTransmisiones")) or 1
        if index != 0:
            times = 1
        for _ in range(max(1, min(times, 10))):
            rows.append(transfer)
    return rows


def map_vehicle(raw: dict[str, Any]) -> dict[str, Any]:
    transfers = raw.get("vehicleTransfers") or []
    rows = _expand(transfers)
    keys = {str(t.get("claveTramite", "")) for t in transfers}

    status = None
    if keys & BAJA_KEYS or any(t.get("indBajaDef") for t in transfers):
        status = "baja"
    elif "6" in keys or any(t.get("indBajaTemp") for t in transfers):
        status = "baja"
    elif transfers:
        status = "alta"

    kw = None
    try:
        kw = float(str(raw.get("kwItv") or "").replace(",", "."))
    except ValueError:
        kw = None

    movements = [
        {
            "fecha": _date(t.get("fecTramitacion") or t.get("fecProceso")),
            "tipo": MOVE.get(str(t.get("claveTramite", "")), "Trámite"),
            "localidad": (t.get("municipio") or "").title() or None,
            "propietario": OWNER_TYPE.get(str(t.get("personaFisicaJuridica", "")), None),
        }
        for t in transfers
    ]

    return {
        "make": raw.get("marcaItv") or raw.get("marcaVehiculoBase"),
        "model": raw.get("modeloItv"),
        "engine_cc": _int(raw.get("cilindradaItv")),
        "power_hp": math.ceil(kw * 1.35962) if kw else None,
        "seats": _int(raw.get("numPlazas")),
        "fuel": FUEL.get(str(raw.get("codPropulsionItv", "")), None),
        "year": _year(raw.get("fecPrimMatriculacion")),
        "first_registration": _date(raw.get("fecPrimMatriculacion")),
        "env_label": raw.get("etiquetaAmbiental") or None,
        "owners_count": len(rows) if rows else None,
        "status": status,
        "extra": {
            "historialvehiculo": {
                "id": raw.get("bastidorItvEncrypt"),
                "registration_spain": _date(raw.get("fecMatricula")),
                "bastidor_masked": raw.get("bastidorItv"),
                "euro": raw.get("nivelEmisionesEuroItv"),
                "co2": _int(raw.get("co2Itv")),
                "power_kw": kw,
                "power_fiscal": raw.get("potenciaItv"),
                "tara": _int(raw.get("tara")),
                "peso_max": _int(raw.get("pesoMax")),
                "masa_orden_marcha": _int(raw.get("masaOrdenMarchaItv")),
                "distancia_ejes": _int(raw.get("distanciaEjes12")),
                "via_anterior": _int(raw.get("viaAnteriorItv")),
                "via_posterior": _int(raw.get("viaPosteriorItv")),
                "homologacion": raw.get("categoriaHomologacionEuropeaItv"),
                "carroceria": raw.get("carroceria"),
                "movimientos": movements,
            }
        },
    }


def fetch(vehicle_id: str) -> dict[str, Any]:
    vehicle_id = extract_id(vehicle_id) or vehicle_id.strip()
    if not re.fullmatch(r"[a-f0-9]{64}", vehicle_id or ""):
        raise ProviderError("El enlace no contiene un ID válido de HistorialVehículo")

    try:
        response = requests.get(
            f"{API}/vehicle/{vehicle_id}",
            headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
            timeout=settings.autoinfo_timeout,
        )
    except requests.RequestException as exc:
        raise ProviderError(f"No se pudo consultar HistorialVehículo: {exc}") from exc

    if response.status_code == 404:
        raise ProviderError("HistorialVehículo no tiene datos para ese ID")
    if response.status_code != 200:
        raise ProviderError(f"HistorialVehículo respondió HTTP {response.status_code}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise ProviderError("Respuesta no JSON de HistorialVehículo") from exc

    info = payload.get("infoVehicle") or {}
    if not info:
        raise ProviderError("HistorialVehículo no devolvió datos del vehículo")
    return info


def search_plate(plate: str, token: str) -> dict[str, Any]:
    """POST /v2/vehicle/search: matrícula + token Turnstile -> id/VIN."""
    try:
        response = requests.post(
            f"{API}/vehicle/search",
            json={"identificationNumber": plate, "token": token},
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
                "Origin": "https://www.historialvehiculo.com",
                "Referer": SEARCH_URL,
            },
            timeout=settings.autoinfo_timeout,
        )
    except requests.RequestException as exc:
        raise ProviderError(f"No se pudo buscar en HistorialVehículo: {exc}") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise ProviderError("Respuesta no JSON en la búsqueda") from exc

    if response.status_code >= 400:
        message = str(payload.get("error") or payload.get("message") or response.status_code)
        if "turnstile" in message.lower():
            raise ProviderError("Turnstile rechazado por HistorialVehículo")
        if "TOO_MANY_REQUESTS" in message:
            raise ProviderError("HistorialVehículo: límite de búsquedas por matrícula")
        if message.startswith("WAIT_SEARCH_"):
            raise ProviderError(f"HistorialVehículo pide esperar ({message})")
        raise ProviderError(f"HistorialVehículo: {message}")
    return payload


class HistorialVehiculoProvider:
    """Flujo completo por matrícula cuando hay resolvedor de Turnstile."""

    name = "historialvehiculo"

    def available(self) -> bool:
        return True

    def lookup(self, plate: str, country: str, captcha_token: str | None = None) -> ProviderResult:
        if country != "ES":
            raise ProviderError("HistorialVehículo solo cubre España")

        token = captcha_token
        if not token:
            if solver.provider in {"2captcha", "cfsolve"} and solver.can_solve():
                token = solver.solve_turnstile(SITEKEY, SEARCH_URL)
            else:
                raise CaptchaRequired(SITEKEY, SEARCH_URL, "Turnstile requerido")

        payload = search_plate(plate, token)
        candidate = payload.get("bastidorItv") or payload.get("id") or ""
        vehicle_id = extract_id(str(candidate))
        if not vehicle_id and isinstance(payload.get("data"), dict):
            vehicle_id = extract_id(str(payload["data"].get("bastidorItvEncrypt") or ""))
        if not vehicle_id:
            message = payload.get("message") or "sin datos"
            raise ProviderError(f"HistorialVehículo no devolvió el ID ({message})")

        info = fetch(vehicle_id)
        mapped = map_vehicle(info)
        extra = mapped.pop("extra", {}) or {}
        return ProviderResult(
            provider=self.name,
            found=True,
            data={**mapped, "extra": extra},
            raw=info,
            note=f"id {vehicle_id[:12]}",
        )
