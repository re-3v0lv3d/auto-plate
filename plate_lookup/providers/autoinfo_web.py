"""Proveedor web: flujo de búsqueda pública de auto-info.gratis.

Flujo observado (ver docs/api-autoinfo.md):

1. `GET /es/sprawdzam/` -> crea PHPSESSID.
2. `POST /es/sprawdzam/` con `numer`, `kraj` y `g-recaptcha-response`.
   * Sin token: el servidor vuelve a pintar el formulario con el widget.
   * Con token no vacío: responde una página de espera con un `$.ajax` a
     `POST /es/test/ {numer, kraj}`.
3. `POST /es/test/` devuelve la ruta del informe (`/es/raport/<hash32>/`).
   Tarda ~10 s porque resuelve contra la fuente real.
4. `GET` de esa ruta con la misma sesión devuelve la ficha (200).

El parser no depende de clases CSS concretas: extrae pares etiqueta/valor de
`dt/dd`, `th/td`, `<td scope="row">`/`<td>`, `data-label` y textos "Marca: ...".
"""

from __future__ import annotations

import re
import time
from html import unescape

import requests

from ..captcha import solver
from ..config import settings
from .autoinfo_api import _canonical_key, _to_int, INT_FIELDS
from .base import CaptchaRequired, ProviderError, ProviderResult

RE_CAPTCHA = re.compile(r'class="g-recaptcha"', re.I)

# Hallazgo: el backend solo comprueba que `g-recaptcha-response` no esté vacío.
# Con el modo "site" replicamos la petición del navegador sin resolver el widget.
SITE_PLACEHOLDER_TOKEN = "03AFcWeA-auto-plate"
RE_REPORT_URL = re.compile(r"/(?:[a-z]{2}/)?raport/([a-f0-9]{32})/", re.I)
RE_DT_DD = re.compile(r"<dt[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>", re.S | re.I)
RE_TR = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S | re.I)
RE_CELL = re.compile(r"<t([hd])[^>]*>(.*?)</t\1>", re.S | re.I)
# auto-info usa filas con DOS <td>: el primero con scope="row" es la etiqueta.
RE_ROW_LABEL = re.compile(
    r'<td[^>]*scope="row"[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>', re.S | re.I
)
RE_DATA_LABEL = re.compile(
    r'<(\w+)[^>]*data-label="([^"]+)"[^>]*>(.*?)</\1>', re.S | re.I
)
RE_INLINE_PAIR = re.compile(
    r"<(\w+)[^>]*class=\"[^\"]*(?:label|name|key|title)[^\"]*\"[^>]*>(.*?)</\1>"
    r"\s*<(\w+)[^>]*class=\"[^\"]*(?:value|data|val)[^\"]*\"[^>]*>(.*?)</\3>",
    re.S | re.I,
)
RE_TEXT_PAIR = re.compile(r"([A-Za-zÁÉÍÓÚÜÑáéíóúüñ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ /.]{2,40}):\s*([^<\n]{1,80})")

RE_TAG = re.compile(r"<[^>]+>")
RE_WS = re.compile(r"\s+")


def _text(fragment: str) -> str:
    clean = RE_TAG.sub(" ", fragment or "")
    clean = unescape(clean)
    return RE_WS.sub(" ", clean).strip()


def extract_pairs(html: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []

    for label, value in RE_DT_DD.findall(html):
        pairs.append((_text(label), _text(value)))

    for label, value in RE_ROW_LABEL.findall(html):
        pairs.append((_text(label), _text(value)))

    for row in RE_TR.findall(html):
        cells = RE_CELL.findall(row)
        if len(cells) == 2 and cells[0][0].lower() == "h" and cells[1][0].lower() == "d":
            pairs.append((_text(cells[0][1]), _text(cells[1][1])))

    for _, label, value in RE_DATA_LABEL.findall(html):
        pairs.append((_text(label), _text(value)))

    for _, label, _, value in RE_INLINE_PAIR.findall(html):
        pairs.append((_text(label), _text(value)))

    for label, value in RE_TEXT_PAIR.findall(_text(html)):
        pairs.append((label.strip(), value.strip()))

    seen: set[tuple[str, str]] = set()
    unique: list[tuple[str, str]] = []
    for label, value in pairs:
        key = (label.lower(), value.lower())
        if not label or not value or key in seen:
            continue
        seen.add(key)
        unique.append((label, value))
    return unique


def _canonical_label(label: str) -> str | None:
    """Mapea la etiqueta; si viene con texto pegado delante, lo recorta."""
    canon = _canonical_key(label)
    if canon:
        return canon
    words = label.split()
    for i in range(1, min(4, len(words))):
        canon = _canonical_key(" ".join(words[i:]))
        if canon:
            return canon
    return None


def parse_report(html: str) -> dict[str, object]:
    data: dict[str, object] = {}
    pairs = extract_pairs(html)
    for label, value in pairs:
        canon = _canonical_label(label)
        if not canon or canon in data:
            continue
        # "Baja: Sí, 12.03.2021" -> el estado lo da la etiqueta, no el valor.
        if canon == "status" and "baja" in label.lower():
            data[canon] = "baja"
        else:
            data[canon] = value

    for key in list(data):
        if key in INT_FIELDS:
            data[key] = _to_int(data[key])

    # VIN: 17 caracteres alfanuméricos sin I/O/Q.
    if "vin" not in data:
        match = re.search(r"\b([A-HJ-NPR-Z0-9]{17})\b", html)
        if match:
            data["vin"] = match.group(1)

    return data


class AutoInfoWebProvider:
    name = "autoinfo-web"

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "es-ES,es;q=0.9",
            }
        )

    def available(self) -> bool:
        return settings.allow_web_provider

    def lookup(self, plate: str, country: str, captcha_token: str | None = None) -> ProviderResult:
        lang = settings.autoinfo_lang
        form_url = f"{settings.autoinfo_base}/{lang}/sprawdzam/"
        test_url = f"{settings.autoinfo_base}/{lang}/test/"

        # Resolvemos el token antes de tocar la red: si no hay forma de
        # obtenerlo, no tiene sentido pedir el formulario.
        token = captcha_token
        if not token:
            if solver.provider == "2captcha":
                token = solver.solve(settings.captcha_sitekey, form_url)
            elif solver.provider == "site":
                token = SITE_PLACEHOLDER_TOKEN
        if not token:
            raise CaptchaRequired(settings.captcha_sitekey, form_url)

        try:
            self.session.get(form_url, timeout=settings.autoinfo_timeout)
            form = self.session.post(
                form_url,
                data={"numer": plate, "kraj": country, "g-recaptcha-response": token},
                headers={"Referer": form_url, "Origin": settings.autoinfo_base},
                timeout=settings.autoinfo_timeout,
                allow_redirects=True,
            )
        except requests.RequestException as exc:
            raise ProviderError(f"No se pudo abrir el formulario: {exc}") from exc

        if RE_CAPTCHA.search(form.text):
            raise ProviderError("El captcha fue rechazado o ha caducado. Inténtalo de nuevo.")

        # Segundo paso: el endpoint que resuelve de verdad la matrícula.
        # Devuelve la ruta del informe, p. ej. "/es/raport/<hash>/".
        try:
            job = self.session.post(
                test_url,
                data={"numer": plate, "kraj": country},
                headers={
                    "Referer": form_url,
                    "Origin": settings.autoinfo_base,
                    "X-Requested-With": "XMLHttpRequest",
                },
                timeout=max(settings.autoinfo_timeout, 90),
            )
        except requests.RequestException as exc:
            raise ProviderError(f"Fallo en la consulta: {exc}") from exc

        report_path = job.text.strip().strip('"').strip("'")
        match = RE_REPORT_URL.search(report_path) or RE_REPORT_URL.search(form.text)
        if not match:
            raise ProviderError(
                "La consulta no devolvió un informe (captcha no aceptado o matrícula sin datos)."
            )

        report_url = report_path if report_path.startswith("http") else f"{settings.autoinfo_base}{report_path}"
        html = ""
        for attempt in range(3):
            try:
                report = self.session.get(report_url, timeout=max(settings.autoinfo_timeout, 90))
            except requests.RequestException as exc:
                raise ProviderError(f"No se pudo descargar el informe: {exc}") from exc
            html = report.text
            if report.status_code == 200 and "tymczasowo niedostępny" not in html:
                break
            time.sleep(5 * (attempt + 1))

        if "tymczasowo niedostępny" in html:
            raise ProviderError(
                "auto-info.gratis devuelve 503 (resultado temporalmente no disponible). "
                "Reintenta más tarde; el resultado se cacheará."
            )

        data = parse_report(html)
        if not data:
            raise ProviderError("Informe recibido pero sin campos reconocibles.")

        return ProviderResult(
            provider=self.name,
            found=True,
            data=data,
            html=html,
            note=f"informe {match.group(1)}",
        )
