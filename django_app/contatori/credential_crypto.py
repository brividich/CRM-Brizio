"""Cifratura delle nuove community con chiave derivata e separata per uso.

Usa SECRET_KEY, come il servizio TOTP esistente; i fallback permettono la
rotazione. Il backup deve conservare anche la chiave, senza pubblicarla.
"""
import base64
import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet(key):
    derived = hmac.new(key.encode(), b"novicrom:contatori:community:v1", hashlib.sha256).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def cifra(value):
    return _fernet(settings.SECRET_KEY).encrypt(value.encode()).decode()


def decifra(value):
    for key in [settings.SECRET_KEY, *settings.SECRET_KEY_FALLBACKS]:
        try:
            return _fernet(key).decrypt(value.encode()).decode()
        except InvalidToken:
            continue
    raise ValueError("Credenziale non decifrabile: aggiornarla nel catalogo.")
