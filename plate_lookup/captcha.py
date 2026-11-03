"""Resolución de reCAPTCHA v2.

Tres modos (`CAPTCHA_PROVIDER`):

* `none`   -> nunca se resuelve; el proveedor web queda desactivado.
* `manual` -> el token lo aporta el usuario desde la interfaz (widget propio).
* `2captcha` -> se resuelve en servidor con un servicio compatible con la API
  de 2captcha/rucaptcha (`CAPTCHA_API_KEY`).
"""

from __future__ import annotations

import time

import requests

from .config import settings
from .providers.base import ProviderError

CAPTCHA_BASE = "https://2captcha.com"
POLL_INTERVAL = 5
MAX_WAIT = 180


class CaptchaSolver:
    def __init__(self) -> None:
        self.session = requests.Session()

    @property
    def provider(self) -> str:
        return settings.captcha_provider

    def can_solve(self) -> bool:
        return settings.captcha_configured

    def solve(self, sitekey: str, page_url: str) -> str:
        if self.provider == "2captcha":
            return self._solve_2captcha(sitekey, page_url)
        raise ProviderError("No hay resolvedor de captcha configurado")

    def _solve_2captcha(self, sitekey: str, page_url: str) -> str:
        if not settings.captcha_api_key:
            raise ProviderError("CAPTCHA_API_KEY no configurada")

        try:
            submit = self.session.post(
                f"{CAPTCHA_BASE}/in.php",
                data={
                    "key": settings.captcha_api_key,
                    "method": "userrecaptcha",
                    "googlekey": sitekey,
                    "pageurl": page_url,
                    "json": 1,
                },
                timeout=20,
            ).json()
        except (requests.RequestException, ValueError) as exc:
            raise ProviderError(f"No se pudo enviar el captcha: {exc}") from exc

        if submit.get("status") != 1:
            raise ProviderError(f"2captcha rechazó la petición: {submit.get('request')}")

        task_id = submit["request"]
        deadline = time.monotonic() + MAX_WAIT
        while time.monotonic() < deadline:
            time.sleep(POLL_INTERVAL)
            try:
                poll = self.session.get(
                    f"{CAPTCHA_BASE}/res.php",
                    params={
                        "key": settings.captcha_api_key,
                        "action": "get",
                        "id": task_id,
                        "json": 1,
                    },
                    timeout=20,
                ).json()
            except (requests.RequestException, ValueError) as exc:
                raise ProviderError(f"Error consultando el captcha: {exc}") from exc

            if poll.get("status") == 1:
                return str(poll["request"])
            if poll.get("request") != "CAPCHA_NOT_READY":
                raise ProviderError(f"2captcha falló: {poll.get('request')}")

        raise ProviderError("Tiempo de espera agotado resolviendo el captcha")


solver = CaptchaSolver()
