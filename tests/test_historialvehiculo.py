from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from plate_lookup.providers import historialvehiculo as hv

FIXTURE = Path(__file__).parent / "fixtures" / "hv_vehicle.json"


def test_extract_id_from_url():
    vid = "ae5df2c0ac06555b89356f1acc66e263409fb32b38cbde9b4d672b297b217bdb"
    assert hv.extract_id(f"https://www.historialvehiculo.com/vehiculo/{vid}") == vid
    assert hv.extract_id(vid.upper()) == vid
    assert hv.extract_id("https://ejemplo.com/otra-cosa") is None


def test_map_vehicle():
    info = json.loads(FIXTURE.read_text())["infoVehicle"]
    data = hv.map_vehicle(info)

    assert data["make"] == "BMW"
    assert data["model"] == "M2 COMPETITION"
    assert data["engine_cc"] == 2979
    assert data["power_hp"] == 411          # 302 kW * 1.35962
    assert data["seats"] == 4
    assert data["fuel"] == "Gasolina"
    assert data["year"] == 2018
    assert data["first_registration"] == "19/12/2018"
    assert data["env_label"] == "C"
    assert data["owners_count"] == 5        # expansión de numTransmisiones
    assert data["status"] == "alta"

    extra = data["extra"]["historialvehiculo"]
    assert extra["registration_spain"] == "08/03/2022"
    assert extra["euro"] == "EURO 6BG"
    assert extra["co2"] == 220
    assert len(extra["movimientos"]) == 4
    assert extra["movimientos"][0]["tipo"] == "Matriculación"
    assert extra["movimientos"][-1]["localidad"] == "Vigo"


def test_map_baja():
    info = {
        "marcaItv": "SEAT", "modeloItv": "IBIZA", "codPropulsionItv": "1",
        "vehicleTransfers": [
            {"claveTramite": "1", "numTransmisiones": "01", "fecTramitacion": "01012020"},
            {"claveTramite": "3", "numTransmisiones": "01", "fecTramitacion": "01012023", "indBajaDef": "S"},
        ],
    }
    data = hv.map_vehicle(info)
    assert data["status"] == "baja"
    assert data["fuel"] == "Diésel"
    assert data["owners_count"] == 2
