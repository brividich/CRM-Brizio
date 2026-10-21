"""Campo di testo cifrato nel database (GDPR art. 32, checklist E4 del 21/10/2026).

Stessa chiave dei documenti privati (``DOCUMENT_ENCRYPTION_KEY``, Fernet AES; le
chiavi in ``DOCUMENT_ENCRYPTION_OLD_KEYS`` decifrano ancora). Il codice legge e
scrive testo normale: si cifra in scrittura, si decifra in lettura.

- valore vuoto: resta ``""`` (i filtri ``campo=""`` e gli ``update(campo="")``
  continuano a funzionare);
- valore storico in chiaro: letto com'e', cifrato al primo salvataggio (o con
  ``manage.py cifra_campi_esistenti``);
- senza chiave (sviluppo, test): scritto in chiaro, come per i file;
- la cifratura non e' deterministica: niente filtri per valore, ordinamenti o
  ricerche su questi campi. Usarlo solo per campi che si leggono e basta.
"""
from __future__ import annotations

from django import forms
from django.db import models

PREFISSO = "enc1:"


def cifra_testo(valore: str) -> str:
    from core.encrypted_storage import _get_fernet

    if not valore or valore.startswith(PREFISSO):
        return valore
    fernet = _get_fernet()
    if fernet is None:
        return valore
    return PREFISSO + fernet.encrypt(valore.encode("utf-8")).decode("ascii")


def decifra_testo(valore):
    from core.encrypted_storage import _get_fernet

    if not isinstance(valore, str) or not valore.startswith(PREFISSO):
        return valore
    fernet = _get_fernet()
    if fernet is None:
        raise ValueError("Campo cifrato ma DOCUMENT_ENCRYPTION_KEY non configurata.")
    return fernet.decrypt(valore[len(PREFISSO):].encode("ascii")).decode("utf-8")


class CampoCifrato(models.TextField):
    """``TextField`` cifrato. ``max_length`` vale solo per il form (come per TextField);
    ``riga_singola=True`` usa un campo di testo invece della textarea."""

    description = "Testo cifrato (Fernet)"

    def __init__(self, *args, riga_singola: bool = False, **kwargs):
        self.riga_singola = riga_singola
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if self.riga_singola:
            kwargs["riga_singola"] = True
        return name, path, args, kwargs

    def from_db_value(self, value, expression, connection):
        return decifra_testo(value)

    def to_python(self, value):
        return decifra_testo(super().to_python(value))

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        return cifra_testo(value) if isinstance(value, str) else value

    def formfield(self, **kwargs):
        if self.riga_singola:
            kwargs.setdefault("widget", forms.TextInput)
        return super().formfield(**kwargs)
