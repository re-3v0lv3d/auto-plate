#!/usr/bin/env python3
"""Exporta la caché actual a un JSONL versionable.

Sirve para hosts con disco efímero (Cloud Run, Render free): al arrancar con la
base vacía, el servidor importa `seed/vehicles.jsonl`.

Uso:
    python tools/export_seed.py --out seed/vehicles.jsonl
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from plate_lookup import db  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="seed/vehicles.jsonl")
    args = parser.parse_args()
    db.init_db()
    total = db.export_seed(Path(args.out))
    print(f"{total} fichas exportadas a {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
