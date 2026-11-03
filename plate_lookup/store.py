"""Capa de almacenamiento con dos implementaciones: SQLite y Firestore.

Se elige con `STORAGE=sqlite|firestore`. SQLite es el modo local por defecto;
Firestore es lo que usa Cloud Run (el cliente toma las credenciales del
service account, sin claves en el repositorio).
"""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import db
from .config import settings
from .normalize import SUPPORTED_COUNTRIES

VEHICLE_FIELDS = (
    "make", "model", "variant", "year", "first_registration", "vin", "fuel",
    "engine_cc", "power_hp", "color", "body", "doors", "seats",
)


class Storage(ABC):
    name: str

    @abstractmethod
    def init(self) -> None: ...

    @abstractmethod
    def get_vehicle(self, plate_norm: str, country: str) -> db.Vehicle | None: ...

    @abstractmethod
    def upsert_vehicle(self, vehicle: db.Vehicle, plate_norm: str) -> db.Vehicle: ...

    @abstractmethod
    def log_lookup(self, plate_norm: str, country: str, provider: str, status: str,
                   detail: str | None = None, duration_ms: int | None = None) -> None: ...

    @abstractmethod
    def save_report(self, plate_norm: str, country: str, provider: str, html: str) -> None: ...

    @abstractmethod
    def stats(self) -> dict[str, Any]: ...

    @abstractmethod
    def seed_if_empty(self, path: Path) -> int: ...

    def crawl_seen(self, report_hash: str) -> bool:  # opcional para los recolectores
        return False

    def mark_crawl(self, report_hash: str, plate_norm: str | None, country: str | None,
                   status: str, detail: str | None = None) -> None:
        return None

    def crawl_stats(self) -> dict[str, int]:
        return {}


class SqliteStorage(Storage):
    name = "sqlite"

    def init(self) -> None:
        db.init_db()

    def get_vehicle(self, plate_norm: str, country: str) -> db.Vehicle | None:
        return db.get_vehicle(plate_norm, country)

    def upsert_vehicle(self, vehicle: db.Vehicle, plate_norm: str) -> db.Vehicle:
        return db.upsert_vehicle(vehicle, plate_norm)

    def log_lookup(self, plate_norm: str, country: str, provider: str, status: str,
                   detail: str | None = None, duration_ms: int | None = None) -> None:
        db.log_lookup(plate_norm, country, provider, status, detail, duration_ms)

    def save_report(self, plate_norm: str, country: str, provider: str, html: str) -> None:
        db.save_report(plate_norm, country, provider, html)

    def stats(self) -> dict[str, Any]:
        return db.stats()

    def seed_if_empty(self, path: Path) -> int:
        return db.seed_if_empty(path)

    def crawl_seen(self, report_hash: str) -> bool:
        return db.crawl_seen(report_hash)

    def mark_crawl(self, report_hash: str, plate_norm: str | None, country: str | None,
                   status: str, detail: str | None = None) -> None:
        db.mark_crawl(report_hash, plate_norm, country, status, detail)

    def crawl_stats(self) -> dict[str, int]:
        return db.crawl_stats()


def _strip_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_strip_none(v) for v in value if v is not None]
    return value


class FirestoreStorage(Storage):
    """Colecciones: vehicles, lookup_log, reports, crawl_progress."""

    name = "firestore"

    def __init__(self, client: Any | None = None) -> None:
        from google.cloud import firestore
        from google.cloud.firestore_v1 import Query
        from google.cloud.firestore_v1.base_query import FieldFilter

        self._firestore = firestore
        self._FieldFilter = FieldFilter
        self._descending = Query.DESCENDING
        self.client = client or firestore.Client(project=settings.gcp_project or None)
        prefix = settings.firestore_prefix
        self.vehicles = self.client.collection(f"{prefix}vehicles")
        self.logs = self.client.collection(f"{prefix}lookup_log")
        self.reports = self.client.collection(f"{prefix}reports")
        self.progress = self.client.collection(f"{prefix}crawl_progress")

    def init(self) -> None:
        # Firestore crea colecciones al primer documento; nada que migrar.
        return None

    @staticmethod
    def _doc_id(plate_norm: str, country: str) -> str:
        return f"{country}_{plate_norm}"

    def _to_vehicle(self, raw: dict[str, Any]) -> db.Vehicle:
        updated = raw.get("updated_at")
        if isinstance(updated, datetime):
            updated = updated.timestamp()
        return db.Vehicle(
            plate=raw.get("plate_display") or raw.get("plate_norm") or "",
            country=raw.get("country") or "ES",
            make=raw.get("make"),
            model=raw.get("model"),
            variant=raw.get("variant"),
            year=raw.get("year"),
            first_registration=raw.get("first_registration"),
            vin=raw.get("vin"),
            fuel=raw.get("fuel"),
            engine_cc=raw.get("engine_cc"),
            power_hp=raw.get("power_hp"),
            color=raw.get("color"),
            body=raw.get("body"),
            doors=raw.get("doors"),
            seats=raw.get("seats"),
            source=raw.get("source") or "firestore",
            confidence=float(raw.get("confidence") or 0.5),
            complete=bool(raw.get("complete")),
            extra=raw.get("extra") or {},
            updated_at=float(updated or 0.0),
        )

    def get_vehicle(self, plate_norm: str, country: str) -> db.Vehicle | None:
        snapshot = self.vehicles.document(self._doc_id(plate_norm, country)).get()
        if not snapshot.exists:
            return None
        return self._to_vehicle(snapshot.to_dict() or {})

    def upsert_vehicle(self, vehicle: db.Vehicle, plate_norm: str) -> db.Vehicle:
        ref = self.vehicles.document(self._doc_id(plate_norm, vehicle.country))
        incoming = _strip_none(
            {
                "plate_norm": plate_norm,
                "country": vehicle.country,
                "plate_display": vehicle.plate,
                "complete": vehicle.complete,
                "confidence": vehicle.confidence,
                "source": vehicle.source,
                "extra": vehicle.extra or {},
                **{field: getattr(vehicle, field) for field in VEHICLE_FIELDS},
            }
        )
        now = datetime.now(timezone.utc)

        @self._firestore.transactional
        def _apply(transaction):
            snapshot = ref.get(transaction=transaction)
            existing = snapshot.to_dict() if snapshot.exists else {}
            if existing.get("complete") and not vehicle.complete:
                return existing

            merged: dict[str, Any] = dict(existing)
            for key, value in incoming.items():
                if value is not None:
                    merged[key] = value
            merged["complete"] = bool(existing.get("complete") or vehicle.complete)
            merged["confidence"] = max(
                float(existing.get("confidence") or 0.0), float(vehicle.confidence or 0.0)
            )
            merged["created_at"] = existing.get("created_at") or now
            merged["updated_at"] = now
            transaction.set(ref, merged, merge=True)
            return merged

        result = _apply(self.client.transaction())
        vehicle.updated_at = now.timestamp()
        if isinstance(result, dict):
            return self._to_vehicle(result)
        return vehicle

    def log_lookup(self, plate_norm: str, country: str, provider: str, status: str,
                   detail: str | None = None, duration_ms: int | None = None) -> None:
        self.logs.add(
            _strip_none(
                {
                    "plate_norm": plate_norm,
                    "country": country,
                    "provider": provider,
                    "status": status,
                    "detail": detail,
                    "duration_ms": duration_ms,
                    "created_at": datetime.now(timezone.utc),
                }
            )
        )

    def save_report(self, plate_norm: str, country: str, provider: str, html: str) -> None:
        self.reports.add(
            {
                "plate_norm": plate_norm,
                "country": country,
                "provider": provider,
                "html": html,
                "fetched_at": datetime.now(timezone.utc),
            }
        )

    def _count(self, query) -> int:
        result = query.count().get()
        return int(result[0][0].value)

    def stats(self) -> dict[str, Any]:
        total = self._count(self.vehicles)
        complete = self._count(self.vehicles.where(filter=self._FieldFilter("complete", "==", True)))
        by_country: dict[str, int] = {}
        for code in SUPPORTED_COUNTRIES:
            count = self._count(self.vehicles.where(filter=self._FieldFilter("country", "==", code)))
            if count:
                by_country[code] = count
        last = 0.0
        for doc in self.vehicles.order_by("updated_at", direction=self._descending).limit(1).stream():
            value = (doc.to_dict() or {}).get("updated_at")
            if isinstance(value, datetime):
                last = value.timestamp()
        return {
            "vehicles": total,
            "complete": complete,
            "partial": total - complete,
            "by_country": dict(sorted(by_country.items(), key=lambda item: -item[1])),
            "last_update": last,
        }

    def seed_if_empty(self, path: Path) -> int:
        path = Path(path)
        if not path.exists() or self._count(self.vehicles) > 0:
            return 0

        batch = self.client.batch()
        pending = 0
        loaded = 0
        now = datetime.now(timezone.utc)

        for line in path.open(encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except ValueError:
                continue
            plate_norm = raw.get("plate_norm")
            country = raw.get("country") or "ES"
            if not plate_norm:
                continue
            doc = _strip_none(
                {
                    "plate_norm": plate_norm,
                    "country": country,
                    "plate_display": raw.get("plate") or plate_norm,
                    "complete": bool(raw.get("complete")),
                    "confidence": float(raw.get("confidence") or 0.5),
                    "source": raw.get("source") or "seed",
                    "extra": raw.get("extra") or {},
                    "created_at": now,
                    "updated_at": now,
                    **{field: raw.get(field) for field in VEHICLE_FIELDS},
                }
            )
            batch.set(self.vehicles.document(self._doc_id(plate_norm, country)), doc)
            pending += 1
            loaded += 1
            if pending >= 400:
                batch.commit()
                batch = self.client.batch()
                pending = 0
        if pending:
            batch.commit()
        return loaded

    def crawl_seen(self, report_hash: str) -> bool:
        return self.progress.document(report_hash).get().exists

    def mark_crawl(self, report_hash: str, plate_norm: str | None, country: str | None,
                   status: str, detail: str | None = None) -> None:
        self.progress.document(report_hash).set(
            _strip_none(
                {
                    "plate_norm": plate_norm,
                    "country": country,
                    "status": status,
                    "detail": detail,
                    "created_at": datetime.now(timezone.utc),
                }
            )
        )

    def crawl_stats(self) -> dict[str, int]:
        # Firestore no agrupa; se cuenta por estado conocido.
        counts: dict[str, int] = {}
        for status in ("ok", "unavailable", "sin_datos", "bootstrap_error"):
            count = self._count(self.progress.where(filter=self._FieldFilter("status", "==", status)))
            if count:
                counts[status] = count
        return counts


@lru_cache(maxsize=1)
def get_storage() -> Storage:
    if settings.storage == "firestore":
        return FirestoreStorage()
    return SqliteStorage()
