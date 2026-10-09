"""Segreti del SOC cifrati a riposo (es. API key NVD) in ``SecurityCenterSetting``.

Chiave Fernet derivata da SECRET_KEY con uno scopo dedicato; i fallback di SECRET_KEY
permettono la rotazione. Il valore in chiaro non passa mai da audit, log o template.
"""
import base64
import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

_PREFIX = "fernet:"


def _fernet(key, purpose):
    derived = hmac.new(key.encode(), f"novicrom:security:{purpose}:v1".encode(), hashlib.sha256).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt(value, purpose):
    if not value:
        return ""
    return _PREFIX + _fernet(settings.SECRET_KEY, purpose).encrypt(str(value).encode()).decode()


def decrypt(token, purpose):
    """Testo in chiaro, o "" se assente/non decifrabile (mai un'eccezione verso l'utente)."""
    if not token or not str(token).startswith(_PREFIX):
        return ""
    payload = str(token)[len(_PREFIX):].encode()
    for key in [settings.SECRET_KEY, *getattr(settings, "SECRET_KEY_FALLBACKS", [])]:
        try:
            return _fernet(key, purpose).decrypt(payload).decode()
        except InvalidToken:
            continue
    return ""
