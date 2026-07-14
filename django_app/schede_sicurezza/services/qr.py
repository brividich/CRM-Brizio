"""Generazione QR code per il collegamento prodotto -> vista mobile scheda."""
from __future__ import annotations

import io

import qrcode


def genera_qr_png(url: str) -> bytes:
    """Genera un QR code (PNG bytes) che punta a ``url``."""
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
