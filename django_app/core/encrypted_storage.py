"""Mixin per cifratura at rest AES-256 (Fernet) sugli storage privati Django.

Utilizzo:
    class MioStorage(EncryptedStorageMixin, FileSystemStorage):
        ...

Il mixin cifra in scrittura (_save) e decifra in lettura (_open).
I file esistenti non cifrati (privi del magic prefix) vengono restituiti
as-is — compatibilità trasparente durante la migrazione.

Formato su disco: b"NCENC1\\n" + <Fernet token>

Configurazione:
    DOCUMENT_ENCRYPTION_KEY = "<chiave base64 generata con Fernet.generate_key()>"

Se la chiave non è configurata il mixin è trasparente (nessuna cifratura).
In produzione la chiave DEVE essere impostata.

Generazione chiave:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
from __future__ import annotations

import io
import logging

from django.core.files import File
from django.core.files.base import ContentFile

logger = logging.getLogger(__name__)

_MAGIC = b"NCENC1\n"


def _get_fernet():
    """Restituisce un'istanza Fernet o None se la chiave non è configurata."""
    from django.conf import settings
    from cryptography.fernet import Fernet

    key = str(getattr(settings, "DOCUMENT_ENCRYPTION_KEY", "") or "").strip()
    if not key:
        return None
    return Fernet(key.encode())


def encrypt_bytes(data: bytes) -> bytes:
    """Cifra data con AES-256 Fernet. Restituisce data invariato se no chiave."""
    fernet = _get_fernet()
    if fernet is None:
        return data
    return _MAGIC + fernet.encrypt(data)


def decrypt_bytes(data: bytes) -> bytes:
    """Decifra data se ha il magic prefix. Restituisce data invariato se non cifrato."""
    if not data.startswith(_MAGIC):
        return data  # file legacy non cifrato
    fernet = _get_fernet()
    if fernet is None:
        raise ValueError(
            "Il file è cifrato ma DOCUMENT_ENCRYPTION_KEY non è configurata. "
            "Impossibile decifrare."
        )
    return fernet.decrypt(data[len(_MAGIC):])


def is_encrypted(data: bytes) -> bool:
    return data.startswith(_MAGIC)


class EncryptedStorageMixin:
    """Aggiunge cifratura AES-256 Fernet a qualsiasi FileSystemStorage.

    Sovrascrive _save (cifra prima di scrivere su disco) e _open (decifra
    dopo la lettura da disco). I file non cifrati (legacy) vengono letti
    as-is per compatibilità durante la migrazione.
    """

    def _save(self, name, content):
        if hasattr(content, "seek"):
            content.seek(0)
        data = content.read()
        encrypted = encrypt_bytes(data)
        return super()._save(name, ContentFile(encrypted, name=name))

    def _open(self, name, mode="rb"):
        f = super()._open(name, mode)
        data = f.read()
        if hasattr(f, "close"):
            f.close()
        decrypted = decrypt_bytes(data)
        return File(io.BytesIO(decrypted), name=name)
