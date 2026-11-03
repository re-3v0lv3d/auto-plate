"""Configuración central leída del entorno.

Todos los valores tienen un default seguro: por defecto el sistema funciona
solo con la caché local (sin llamar a nadie).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "si", "sí"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, ""))
    except ValueError:
        return default


@dataclass(slots=True)
class Settings:
    # auto-info.gratis
    autoinfo_base: str = field(default_factory=lambda: os.getenv("AUTOINFO_BASE", "https://auto-info.gratis"))
    autoinfo_lang: str = field(default_factory=lambda: os.getenv("AUTOINFO_LANG", "es"))
    autoinfo_pin: str = field(default_factory=lambda: os.getenv("AUTOINFO_PIN", ""))
    autoinfo_access: str = field(default_factory=lambda: os.getenv("AUTOINFO_ACCESS", ""))
    autoinfo_action: str = field(default_factory=lambda: os.getenv("AUTOINFO_ACTION", "check"))
    # site = replicar petición del navegador (gratis) | solver = 2captcha
    autoinfo_captcha_mode: str = field(
        default_factory=lambda: os.getenv("AUTOINFO_CAPTCHA_MODE", "site").lower()
    )
    autoinfo_timeout: int = field(default_factory=lambda: _int("AUTOINFO_TIMEOUT", 25))

    # Captcha: site | manual | 2captcha | none
    #  site     -> replica la petición del navegador (el backend del sitio solo
    #              comprueba que el campo no esté vacío)
    #  manual   -> exige un token real aportado por el cliente
    #  2captcha -> se resuelve en servidor con CAPTCHA_API_KEY
    captcha_provider: str = field(default_factory=lambda: os.getenv("CAPTCHA_PROVIDER", "site").lower())
    captcha_api_key: str = field(default_factory=lambda: os.getenv("CAPTCHA_API_KEY", ""))
    # cfsolve (solver libre en Rust, sin navegador)
    cfsolve_bin: str = field(default_factory=lambda: os.getenv("CFSOLVE_BIN", ""))
    cfsolve_profile: str = field(default_factory=lambda: os.getenv("CFSOLVE_PROFILE", ""))
    cfsolve_timeout: int = field(default_factory=lambda: _int("CFSOLVE_TIMEOUT", 120))
    captcha_sitekey: str = field(
        default_factory=lambda: os.getenv(
            "CAPTCHA_SITEKEY", "6LedQaYoAAAAAOxmjCgIZNM1ANwQ1sQfvLtYDFhi"
        )
    )

    # Persistencia
    storage: str = field(default_factory=lambda: os.getenv("STORAGE", "sqlite").lower())
    db_path: Path = field(
        default_factory=lambda: Path(os.getenv("DB_PATH", str(BASE_DIR / "data" / "vehicles.db")))
    )
    gcp_project: str = field(
        default_factory=lambda: os.getenv("GCP_PROJECT") or os.getenv("GOOGLE_CLOUD_PROJECT", "")
    )
    firestore_prefix: str = field(default_factory=lambda: os.getenv("FIRESTORE_PREFIX", ""))
    seed_path: Path = field(
        default_factory=lambda: Path(os.getenv("SEED_PATH", str(BASE_DIR / "seed" / "vehicles.jsonl")))
    )
    cache_ttl_days: int = field(default_factory=lambda: _int("CACHE_TTL_DAYS", 30))

    # Servidor
    allow_web_provider: bool = field(default_factory=lambda: _bool("ALLOW_WEB_PROVIDER", True))
    rate_limit_per_minute: int = field(default_factory=lambda: _int("RATE_LIMIT_PER_MINUTE", 20))
    cors_origins: str = field(default_factory=lambda: os.getenv("CORS_ORIGINS", "*"))
    api_user: str = field(default_factory=lambda: os.getenv("API_USER", ""))
    api_password: str = field(default_factory=lambda: os.getenv("API_PASSWORD", ""))

    @property
    def auth_enabled(self) -> bool:
        return bool(self.api_user and self.api_password)

    @property
    def cors_origin_list(self) -> list[str]:
        raw = self.cors_origins.strip()
        if raw in {"", "*"}:
            return ["*"]
        return [item.strip() for item in raw.split(",") if item.strip()]

    @property
    def pro_api_configured(self) -> bool:
        return bool(self.autoinfo_pin and self.autoinfo_access)

    @property
    def captcha_configured(self) -> bool:
        if self.captcha_provider == "cfsolve":
            return bool(self.cfsolve_bin and self.cfsolve_profile)
        if self.captcha_provider in {"site", "manual"}:
            return True
        if self.captcha_provider == "2captcha":
            return bool(self.captcha_api_key)
        return False


settings = Settings()
