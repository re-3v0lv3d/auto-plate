"""Resolución de reCAPTCHA v2.

Tres modos (`CAPTCHA_PROVIDER`):

* `none`   -> nunca se resuelve; el proveedor web queda desactivado.
* `manual` -> el token lo aporta el usuario desde la interfaz (widget propio).
* `2captcha` -> se resuelve en servidor con un servicio compatible con la API
  de 2captcha/rucaptcha (`CAPTCHA_API_KEY`).
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time

import requests

from .config import settings
from pathlib import Path

from .errors import ProviderError

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

    def solve_turnstile(self, sitekey: str, page_url: str, action: str | None = None) -> str:
        """Turnstile de Cloudflare.

        - cfsolve: binario Rust local, gratis, sin navegador ni API de pago.
        - 2captcha: servicio de pago.
        """
        if self.provider == "cfsolve":
            return self._solve_cfsolve(sitekey, page_url)
        if self.provider != "2captcha":
            raise ProviderError("No hay resolvedor de Turnstile configurado")
        if not settings.captcha_api_key:
            raise ProviderError("CAPTCHA_API_KEY no configurada")
        return self._solve_2captcha(sitekey, page_url, method="turnstile", action=action)

    def _solve_cfsolve(self, sitekey: str, page_url: str) -> str:
        binary = settings.cfsolve_bin
        profile = settings.cfsolve_profile
        if not binary or not profile:
            raise ProviderError("CFSOLVE_BIN / CFSOLVE_PROFILE no configurados")
        if not shutil.which(binary) and not Path(binary).exists():
            raise ProviderError(f"No se encuentra el binario cfsolve: {binary}")

        workdir = tempfile.mkdtemp(prefix="cfsolve-")
        out_dir = Path(workdir) / "run"
        try:
            process = subprocess.run(
                [
                    binary, "--page", page_url, str(out_dir), "--solve",
                    "--fingerprint", profile, "--sitekey", sitekey, "--blank-page",
                ],
                capture_output=True,
                text=True,
                timeout=settings.cfsolve_timeout,
            )
            token = process.stdout.strip().splitlines()[-1] if process.stdout.strip() else ""
            if process.returncode != 0 or not token.startswith("1."):
                detail = (process.stderr or "").strip().splitlines()[-1:] or ["sin detalle"]
                raise ProviderError(f"cfsolve falló: {detail[0]}")
            return token
        except subprocess.TimeoutExpired as exc:
            raise ProviderError("cfsolve agotó el tiempo") from exc
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def _solve_2captcha(
        self, sitekey: str, page_url: str, method: str = "userrecaptcha", action: str | None = None
    ) -> str:
        if not settings.captcha_api_key:
            raise ProviderError("CAPTCHA_API_KEY no configurada")

        try:
            submit = self.session.post(
                f"{CAPTCHA_BASE}/in.php",
                data={
                    "key": settings.captcha_api_key,
                    "method": method,
                    "pageurl": page_url,
                    "json": 1,
                    **({"sitekey" if method == "turnstile" else "googlekey": sitekey}),
                    **({"action": action} if action else {}),
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
