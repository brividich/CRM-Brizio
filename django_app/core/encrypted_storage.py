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

Rotazione (audit M12):
    1. DOCUMENT_ENCRYPTION_OLD_KEYS = <chiave attuale>; DOCUMENT_ENCRYPTION_KEY = <nuova>
    2. python manage.py rotate_document_encryption_key --apply
    3. tolta la vecchia chiave da DOCUMENT_ENCRYPTION_OLD_KEYS
"""
from __future__ import annotations

import io
import logging

from django.core.files import File
from django.core.files.base import ContentFile

logger = logging.getLogger(__name__)

_MAGIC = b"NCENC1\n"


def _get_fernet():
    """Fernet della chiave corrente, o MultiFernet se ci sono chiavi precedenti.

    Cifra sempre con ``DOCUMENT_ENCRYPTION_KEY``; decifra anche con le chiavi in
    ``DOCUMENT_ENCRYPTION_OLD_KEYS`` (rotazione senza fermo). None se non configurata.
    """
    from django.conf import settings
    from cryptography.fernet import Fernet, MultiFernet

    key = str(getattr(settings, "DOCUMENT_ENCRYPTION_KEY", "") or "").strip()
    if not key:
        return None
    old_keys = [
        str(k).strip()
        for k in (getattr(settings, "DOCUMENT_ENCRYPTION_OLD_KEYS", []) or [])
        if str(k).strip() and str(k).strip() != key
    ]
    if not old_keys:
        return Fernet(key.encode())
    return MultiFernet([Fernet(key.encode()), *(Fernet(k.encode()) for k in old_keys)])


def rotate_bytes(data: bytes) -> bytes | None:
    """Ri-cifra un file cifrato con la chiave corrente. None se il file non è cifrato."""
    if not data.startswith(_MAGIC):
        return None
    fernet = _get_fernet()
    if fernet is None:
        raise ValueError("DOCUMENT_ENCRYPTION_KEY non configurata.")
    token = data[len(_MAGIC):]
    if hasattr(fernet, "rotate"):
        return _MAGIC + fernet.rotate(token)
    return _MAGIC + fernet.encrypt(fernet.decrypt(token))


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
        if not data.startswith(_MAGIC) and _get_fernet() is not None:
            # Audit M12: un file in chiaro in uno storage cifrato va segnalato
            # (manca encrypt_existing_documents o è stato copiato a mano).
            logger.warning("Storage cifrato: letto file NON cifrato %s/%s", type(self).__name__, name)
        decrypted = decrypt_bytes(data)
        return File(io.BytesIO(decrypted), name=name)
