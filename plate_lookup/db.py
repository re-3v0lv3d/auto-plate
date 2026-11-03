"""Capa de persistencia (SQLite).

Diseño: una fila por (matrícula, país). Las filas pueden ser "parciales"
(solo marca/modelo, provenientes de los listados públicos) o "completas"
(cuando una consulta real devuelve el informe del vehículo).
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS vehicles (
    plate_norm        TEXT NOT NULL,
    country           TEXT NOT NULL,
    plate_display     TEXT NOT NULL,
    make              TEXT,
    model             TEXT,
    variant           TEXT,
    year              INTEGER,
    first_registration TEXT,
    vin               TEXT,
    fuel              TEXT,
    engine_cc         INTEGER,
    power_hp          INTEGER,
    color             TEXT,
    body              TEXT,
    doors             INTEGER,
    seats             INTEGER,
    status            TEXT,
    owners_count      INTEGER,
    env_label         TEXT,
    source            TEXT NOT NULL,
    confidence        REAL NOT NULL DEFAULT 0.5,
    complete          INTEGER NOT NULL DEFAULT 0,
    raw_json          TEXT,
    created_at        REAL NOT NULL,
    updated_at        REAL NOT NULL,
    PRIMARY KEY (plate_norm, country)
);

CREATE TABLE IF NOT EXISTS lookup_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    plate_norm  TEXT NOT NULL,
    country     TEXT NOT NULL,
    provider    TEXT NOT NULL,
    status      TEXT NOT NULL,
    detail      TEXT,
    duration_ms INTEGER,
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS reports (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    plate_norm TEXT NOT NULL,
    country    TEXT NOT NULL,
    provider   TEXT NOT NULL,
    html       TEXT NOT NULL,
    fetched_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS crawl_progress (
    report_hash TEXT PRIMARY KEY,
    plate_norm  TEXT,
    country     TEXT,
    status      TEXT NOT NULL,
    detail      TEXT,
    created_at  REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_vehicles_plate ON vehicles(plate_norm);
CREATE INDEX IF NOT EXISTS idx_log_created ON lookup_log(created_at);
"""


@dataclass(slots=True)
class Vehicle:
    plate: str
    country: str
    make: str | None = None
    model: str | None = None
    variant: str | None = None
    year: int | None = None
    first_registration: str | None = None
    vin: str | None = None
    fuel: str | None = None
    engine_cc: int | None = None
    power_hp: int | None = None
    color: str | None = None
    body: str | None = None
    doors: int | None = None
    seats: int | None = None
    status: str | None = None
    owners_count: int | None = None
    env_label: str | None = None
    source: str = "cache"
    confidence: float = 0.5
    complete: bool = False
    extra: dict[str, Any] = field(default_factory=dict)
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["updated_at"] = self.updated_at
        return data


def _connect(path: Path | None = None) -> sqlite3.Connection:
    db_path = Path(path or settings.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def session(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = _connect(path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(path: Path | None = None) -> None:
    with session(path) as conn:
        conn.executescript(SCHEMA)
        # Migración para bases creadas antes de estos campos.
        cols = {row[1] for row in conn.execute("PRAGMA table_info(vehicles)")}
        if "status" not in cols:
            conn.execute("ALTER TABLE vehicles ADD COLUMN status TEXT")
        if "owners_count" not in cols:
            conn.execute("ALTER TABLE vehicles ADD COLUMN owners_count INTEGER")
        if "env_label" not in cols:
            conn.execute("ALTER TABLE vehicles ADD COLUMN env_label TEXT")


def get_vehicle(plate_norm: str, country: str) -> Vehicle | None:
    with session() as conn:
        row = conn.execute(
            "SELECT * FROM vehicles WHERE plate_norm = ? AND country = ?",
            (plate_norm, country),
        ).fetchone()
    if row is None:
        return None
    return _row_to_vehicle(row)


def _row_to_vehicle(row: sqlite3.Row) -> Vehicle:
    extra = json.loads(row["raw_json"]) if row["raw_json"] else {}
    return Vehicle(
        plate=row["plate_display"],
        country=row["country"],
        make=row["make"],
        model=row["model"],
        variant=row["variant"],
        year=row["year"],
        first_registration=row["first_registration"],
        vin=row["vin"],
        fuel=row["fuel"],
        engine_cc=row["engine_cc"],
        power_hp=row["power_hp"],
        color=row["color"],
        body=row["body"],
        doors=row["doors"],
        seats=row["seats"],
        status=row["status"],
        owners_count=row["owners_count"],
        env_label=row["env_label"],
        source=row["source"],
        confidence=row["confidence"],
        complete=bool(row["complete"]),
        extra=extra,
        updated_at=row["updated_at"],
    )


def upsert_vehicle(vehicle: Vehicle, plate_norm: str) -> Vehicle:
    now = time.time()
    with session() as conn:
        existing = conn.execute(
            "SELECT * FROM vehicles WHERE plate_norm = ? AND country = ?",
            (plate_norm, vehicle.country),
        ).fetchone()

        created_at = existing["created_at"] if existing else now

        # No degradar una ficha completa con datos parciales de un listado.
        if existing and existing["complete"] and not vehicle.complete:
            return _row_to_vehicle(existing)

        conn.execute(
            """
            INSERT INTO vehicles (
                plate_norm, country, plate_display, make, model, variant, year,
                first_registration, vin, fuel, engine_cc, power_hp, color, body,
                doors, seats, status, owners_count, env_label, source, confidence, complete,
                raw_json, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(plate_norm, country) DO UPDATE SET
                plate_display=excluded.plate_display,
                make=COALESCE(excluded.make, vehicles.make),
                model=COALESCE(excluded.model, vehicles.model),
                variant=COALESCE(excluded.variant, vehicles.variant),
                year=COALESCE(excluded.year, vehicles.year),
                first_registration=COALESCE(excluded.first_registration, vehicles.first_registration),
                vin=COALESCE(excluded.vin, vehicles.vin),
                fuel=COALESCE(excluded.fuel, vehicles.fuel),
                engine_cc=COALESCE(excluded.engine_cc, vehicles.engine_cc),
                power_hp=COALESCE(excluded.power_hp, vehicles.power_hp),
                color=COALESCE(excluded.color, vehicles.color),
                body=COALESCE(excluded.body, vehicles.body),
                doors=COALESCE(excluded.doors, vehicles.doors),
                seats=COALESCE(excluded.seats, vehicles.seats),
                status=COALESCE(excluded.status, vehicles.status),
                owners_count=COALESCE(excluded.owners_count, vehicles.owners_count),
                env_label=COALESCE(excluded.env_label, vehicles.env_label),
                source=excluded.source,
                confidence=MAX(vehicles.confidence, excluded.confidence),
                complete=MAX(vehicles.complete, excluded.complete),
                raw_json=excluded.raw_json,
                updated_at=excluded.updated_at
            """,
            (
                plate_norm,
                vehicle.country,
                vehicle.plate,
                vehicle.make,
                vehicle.model,
                vehicle.variant,
                vehicle.year,
                vehicle.first_registration,
                vehicle.vin,
                vehicle.fuel,
                vehicle.engine_cc,
                vehicle.power_hp,
                vehicle.color,
                vehicle.body,
                vehicle.doors,
                vehicle.seats,
                vehicle.status,
                vehicle.owners_count,
                vehicle.env_label,
                vehicle.source,
                vehicle.confidence,
                int(vehicle.complete),
                json.dumps(vehicle.extra, ensure_ascii=False) if vehicle.extra else None,
                created_at,
                now,
            ),
        )
    vehicle.updated_at = now
    return vehicle


def log_lookup(
    plate_norm: str,
    country: str,
    provider: str,
    status: str,
    detail: str | None = None,
    duration_ms: int | None = None,
) -> None:
    with session() as conn:
        conn.execute(
            "INSERT INTO lookup_log (plate_norm, country, provider, status, detail, duration_ms, created_at)"
            " VALUES (?,?,?,?,?,?,?)",
            (plate_norm, country, provider, status, detail, duration_ms, time.time()),
        )


def save_report(plate_norm: str, country: str, provider: str, html: str) -> None:
    with session() as conn:
        conn.execute(
            "INSERT INTO reports (plate_norm, country, provider, html, fetched_at) VALUES (?,?,?,?,?)",
            (plate_norm, country, provider, html, time.time()),
        )


def crawl_seen(report_hash: str) -> bool:
    with session() as conn:
        row = conn.execute(
            "SELECT 1 FROM crawl_progress WHERE report_hash = ?", (report_hash,)
        ).fetchone()
    return row is not None


def mark_crawl(
    report_hash: str,
    plate_norm: str | None,
    country: str | None,
    status: str,
    detail: str | None = None,
) -> None:
    with session() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO crawl_progress"
            " (report_hash, plate_norm, country, status, detail, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (report_hash, plate_norm, country, status, detail, time.time()),
        )


def crawl_stats() -> dict[str, int]:
    with session() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM crawl_progress GROUP BY status"
        ).fetchall()
    return {row["status"]: row["n"] for row in rows}


def count_vehicles() -> int:
    with session() as conn:
        return conn.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0]


def export_seed(path: Path) -> int:
    """Exporta todas las fichas a JSONL (para hosts con disco efímero)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with session() as conn, path.open("w", encoding="utf-8") as handle:
        for row in conn.execute("SELECT * FROM vehicles ORDER BY country, plate_norm"):
            vehicle = _row_to_vehicle(row)
            handle.write(json.dumps({"plate_norm": row["plate_norm"], **vehicle.to_dict()}, ensure_ascii=False) + "\n")
            count += 1
    return count


def seed_if_empty(path: Path) -> int:
    """Carga el JSONL inicial solo si la base está vacía (una sola transacción)."""
    path = Path(path)
    if not path.exists() or count_vehicles() > 0:
        return 0

    rows: list[tuple] = []
    now = time.time()
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except ValueError:
                continue
            plate_norm = raw.pop("plate_norm", None)
            if not plate_norm:
                continue
            rows.append(
                (
                    plate_norm,
                    raw.get("country") or "ES",
                    raw.get("plate") or plate_norm,
                    raw.get("make"),
                    raw.get("model"),
                    raw.get("variant"),
                    raw.get("year"),
                    raw.get("first_registration"),
                    raw.get("vin"),
                    raw.get("fuel"),
                    raw.get("engine_cc"),
                    raw.get("power_hp"),
                    raw.get("color"),
                    raw.get("body"),
                    raw.get("doors"),
                    raw.get("seats"),
                    raw.get("status"),
                    raw.get("owners_count"),
                    raw.get("env_label"),
                    raw.get("source") or "seed",
                    float(raw.get("confidence") or 0.5),
                    int(bool(raw.get("complete"))),
                    json.dumps(raw.get("extra") or {}, ensure_ascii=False),
                    now,
                    now,
                )
            )

    if not rows:
        return 0

    with session() as conn:
        conn.executemany(
            """
            INSERT OR IGNORE INTO vehicles (
                plate_norm, country, plate_display, make, model, variant, year,
                first_registration, vin, fuel, engine_cc, power_hp, color, body,
                doors, seats, status, owners_count, env_label, source, confidence, complete,
                raw_json, created_at, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            rows,
        )
    return len(rows)


def stats() -> dict[str, Any]:
    with session() as conn:
        total = conn.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0]
        complete = conn.execute("SELECT COUNT(*) FROM vehicles WHERE complete = 1").fetchone()[0]
        by_country = {
            row["country"]: row["n"]
            for row in conn.execute(
                "SELECT country, COUNT(*) AS n FROM vehicles GROUP BY country ORDER BY n DESC"
            )
        }
        last = conn.execute("SELECT MAX(updated_at) FROM vehicles").fetchone()[0]
    return {
        "vehicles": total,
        "complete": complete,
        "partial": total - complete,
        "by_country": by_country,
        "last_update": last,
    }
