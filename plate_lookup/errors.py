"""Errores compartidos (sin dependencias, evita importaciones circulares)."""

from __future__ import annotations


class ProviderError(RuntimeError):
    """Error recuperable de un proveedor (red, formato, límite...)."""


class CaptchaRequired(ProviderError):
    """El proveedor exige un token de captcha que no tenemos todavía."""

    def __init__(self, sitekey: str, page_url: str, message: str = "Captcha requerido") -> None:
        super().__init__(message)
        self.sitekey = sitekey
        self.page_url = page_url
