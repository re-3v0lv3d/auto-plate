"""Contratos comunes de los proveedores de datos."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class ProviderError(RuntimeError):
    """Error recuperable de un proveedor (red, formato, límite...)."""


class CaptchaRequired(ProviderError):
    """El proveedor exige un token de captcha que no tenemos todavía."""

    def __init__(self, sitekey: str, page_url: str, message: str = "Captcha requerido") -> None:
        super().__init__(message)
        self.sitekey = sitekey
        self.page_url = page_url


@dataclass(slots=True)
class ProviderResult:
    provider: str
    found: bool
    data: dict[str, Any] = field(default_factory=dict)
    raw: Any = None
    html: str | None = None
    note: str | None = None


class Provider(Protocol):
    name: str

    def available(self) -> bool: ...

    def lookup(self, plate: str, country: str, captcha_token: str | None = None) -> ProviderResult: ...
