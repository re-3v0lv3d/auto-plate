from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

pytestmark = pytest.mark.skipif(
    not os.getenv("FIRESTORE_EMULATOR_HOST"),
    reason="requiere el emulador (FIRESTORE_EMULATOR_HOST)",
)


@pytest.fixture()
def storage(monkeypatch):
    from plate_lookup.config import settings
    from plate_lookup.store import FirestoreStorage

    monkeypatch.setattr(settings, "firestore_prefix", f"test-{uuid.uuid4().hex[:8]}-")
    return FirestoreStorage()


def test_roundtrip_and_no_downgrade(storage):
    from plate_lookup import db

    assert storage.get_vehicle("1234ABC", "ES") is None

    full = db.Vehicle(
        plate="1234 ABC", country="ES", make="SEAT", model="León", year=2019,
        engine_cc=1598, complete=True, source="test", confidence=0.9,
    )
    storage.upsert_vehicle(full, "1234ABC")

    partial = db.Vehicle(
        plate="1234 ABC", country="ES", make="SEAT", complete=False,
        source="list", confidence=0.6,
    )
    storage.upsert_vehicle(partial, "1234ABC")

    stored = storage.get_vehicle("1234ABC", "ES")
    assert stored is not None
    assert stored.year == 2019
    assert stored.model == "León"
    assert stored.complete is True
    assert stored.source == "test"


def test_stats_and_seed(storage, tmp_path):
    seed = tmp_path / "seed.jsonl"
    rows = [
        {"plate_norm": "1111AAA", "plate": "1111 AAA", "country": "ES", "make": "SEAT", "complete": False},
        {"plate_norm": "2222BBB", "plate": "2222 BBB", "country": "ES", "make": "OPEL", "complete": True, "year": 2020},
        {"plate_norm": "3333CCC", "plate": "3333 CCC", "country": "PL", "make": "AUDI", "complete": False},
    ]
    seed.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")

    assert storage.seed_if_empty(seed) == 3
    assert storage.seed_if_empty(seed) == 0  # no reimporta

    stats = storage.stats()
    assert stats["vehicles"] == 3
    assert stats["complete"] == 1
    assert stats["by_country"]["ES"] == 2


def test_logs_reports_and_crawl(storage):
    storage.log_lookup("1234ABC", "ES", "test", "ok", None, 10)
    storage.save_report("1234ABC", "ES", "test", "<html></html>")

    assert storage.crawl_seen("hash-1") is False
    storage.mark_crawl("hash-1", "1234ABC", "ES", "ok")
    assert storage.crawl_seen("hash-1") is True
    assert storage.crawl_stats()["ok"] == 1
