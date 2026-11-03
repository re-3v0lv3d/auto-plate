from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from plate_lookup import db  # noqa: E402
from plate_lookup.normalize import InvalidPlate, normalize_plate, split_make_model  # noqa: E402
from plate_lookup.providers.autoinfo_api import normalize_result  # noqa: E402
from plate_lookup.providers.autoinfo_web import parse_report  # noqa: E402


def test_normalize_spanish_plate():
    plate = normalize_plate(" 1234-abc ", "ES")
    assert plate.normalized == "1234ABC"
    assert plate.display == "1234 ABC"
    assert plate.country == "ES"


def test_normalize_rejects_bad_format():
    with pytest.raises(InvalidPlate):
        normalize_plate("abc", "ES")


def test_normalize_unknown_country():
    with pytest.raises(InvalidPlate):
        normalize_plate("1234ABC", "ZZ")


def test_split_make_model_multiword():
    assert split_make_model("ALFA ROMEO 147") == ("ALFA ROMEO", "147")
    assert split_make_model("SEAT IBIZA") == ("SEAT", "IBIZA")
    assert split_make_model("MERCEDES C (205)") == ("MERCEDES", "C (205)")
    assert split_make_model("") == (None, None)


def test_parse_report_dt_dd():
    html = """
    <dl>
      <dt>Marca</dt><dd>SEAT</dd>
      <dt>Modelo</dt><dd>León</dd>
      <dt>Pojemność silnika</dt><dd>1598 cm3</dd>
      <dt>Moc</dt><dd>110 KM</dd>
      <dt>VIN</dt><dd>VSSZZZ1PZ8R012345</dd>
    </dl>
    """
    data = parse_report(html)
    assert data["make"] == "SEAT"
    assert data["model"] == "León"
    assert data["engine_cc"] == 1598
    assert data["power_hp"] == 110
    assert data["vin"] == "VSSZZZ1PZ8R012345"


def test_parse_report_td_scope_row():
    html = """
    <table class="custom-table"><tbody>
      <tr class="spacer"><td colspan="100"></td></tr>
      <tr><td scope="row">Marca</td><td>MERCEDES</td></tr>
      <tr><td scope="row">Modelo</td><td>C (205)</td></tr>
      <tr><td scope="row">Versión</td><td>200 D 9G-TRONIC</td></tr>
      <tr><td scope="row">Año de producción</td><td>2018</td></tr>
      <tr><td scope="row">Inicio de producción</td><td>07.06.2019</td></tr>
      <tr><td scope="row">Tipo de combustible</td><td>Diésel</td></tr>
      <tr><td scope="row">Capacidad del motor</td><td>1597</td></tr>
      <tr><td scope="row">Potencia en kW</td><td>117.7</td></tr>
      <tr><td scope="row">Potencia en hp</td><td>160</td></tr>
      <tr><td scope="row">Número de puertas</td><td>5</td></tr>
    </tbody></table>
    """
    data = parse_report(html)
    assert data["make"] == "MERCEDES"
    assert data["model"] == "C (205)"
    assert data["variant"] == "200 D 9G-TRONIC"
    assert data["year"] == 2018
    assert data["first_registration"] == "07.06.2019"
    assert data["fuel"] == "Diésel"
    assert data["engine_cc"] == 1597
    assert data["power_hp"] == 160
    assert data["power_kw"] == "117.7"
    assert data["doors"] == 5


def test_parse_report_table_and_data_label():
    html = """
    <table>
      <tr><th>Combustible</th><td>Diésel</td></tr>
      <tr><th>Año</th><td>2018</td></tr>
    </table>
    <div data-label="Color">Negro</div>
    """
    data = parse_report(html)
    assert data["fuel"] == "Diésel"
    assert data["year"] == 2018
    assert data["color"] == "Negro"


def test_api_result_mapping_is_flexible():
    payload = {
        "dane": {
            "marka": "OPEL",
            "model": "Corsa",
            "rok_produkcji": "2019",
            "pojemnosc": "1199",
        }
    }
    data = normalize_result(payload)
    assert data == {"make": "OPEL", "model": "Corsa", "year": 2019, "engine_cc": 1199}


def test_parse_report_status_and_owners():
    html = """
    <table><tbody>
      <tr><td scope="row">Baja</td><td>Sí, 12.03.2021</td></tr>
      <tr><td scope="row">Número de titulares</td><td>3</td></tr>
    </tbody></table>
    """
    data = parse_report(html)
    assert data["status"] == "baja"
    assert data["owners_count"] == 3

    from plate_lookup.service import _normalize_status
    assert _normalize_status(data["status"]) == "baja"
    assert _normalize_status("Alta") == "alta"
    assert _normalize_status(None) is None


def test_db_upsert_does_not_downgrade_complete(tmp_path, monkeypatch):
    from plate_lookup.config import settings

    monkeypatch.setattr(settings, "db_path", tmp_path / "t.db")
    db.init_db()

    complete = db.Vehicle(
        plate="1234 ABC", country="ES", make="SEAT", model="León",
        year=2019, complete=True, source="test", status="baja", owners_count=3,
    )
    db.upsert_vehicle(complete, "1234ABC")

    partial = db.Vehicle(
        plate="1234 ABC", country="ES", make="SEAT", model=None,
        complete=False, source="list",
    )
    db.upsert_vehicle(partial, "1234ABC")

    stored = db.get_vehicle("1234ABC", "ES")
    assert stored is not None
    assert stored.year == 2019
    assert stored.model == "León"
    assert stored.complete is True
    assert stored.source == "test"
    assert stored.status == "baja"
    assert stored.owners_count == 3
