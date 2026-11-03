"""Contratos comunes de los proveedores de datos."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ..errors import CaptchaRequired, ProviderError

__all__ = ["CaptchaRequired", "ProviderError", "ProviderResult", "Provider"]


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
