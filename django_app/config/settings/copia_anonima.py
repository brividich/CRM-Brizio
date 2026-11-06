"""Profilo per lavorare sulla copia anonimizzata del database di produzione.

    python django_app\\manage.py runserver --noreload --settings=config.settings.copia_anonima

Procedura completa: ``docs/dr/COPIA_PROD_ANONIMIZZATA.md``.

Nessuna mail e nessuna connessione verso l'esterno, qualunque cosa ci sia nel ``.env``: backend
mail fissato in console, connessioni Python non locali bloccate, ``qcluster`` rifiutato, login LDAP
tolto. Il database deve chiamarsi ``*_ANON`` e stare su questa macchina.
"""
from __future__ import annotations

import sys

from config import rete_guard

from .base import build_sqlserver_database, env
from .dev import *  # noqa: F403,F401

COPIA_ANONIMA = True

_NOME_DB = env("COPIA_DB_NAME", "PN_COPIAPROD_ANON").strip()
_HOST_DB = env("COPIA_DB_HOST", r"localhost\SQLEXPRESS").strip()
if not _NOME_DB.upper().endswith("_ANON"):
    raise RuntimeError(f"Profilo copia_anonima: il database deve finire con _ANON, non {_NOME_DB!r}.")
if _HOST_DB.split("\\")[0].split(",")[0].lower() not in {"localhost", "127.0.0.1", "."}:
    raise RuntimeError("Profilo copia_anonima: il database deve stare su questa macchina.")

DATABASES = {"default": build_sqlserver_database()}
DATABASES["default"].update(NAME=_NOME_DB, HOST=_HOST_DB, USER="", PASSWORD="")
DATABASES["default"]["OPTIONS"]["extra_params"] = "TrustServerCertificate=yes;Trusted_Connection=yes;"

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
EMAIL_HOST = ""
EMAIL_HOST_USER = ""
EMAIL_HOST_PASSWORD = ""
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]
# I campi cifrati della copia vengono sostituiti: la chiave di produzione non serve e non va portata.
DOCUMENT_ENCRYPTION_KEY = ""
DOCUMENT_ENCRYPTION_OLD_KEYS = []

if "qcluster" in sys.argv:
    raise RuntimeError("Profilo copia_anonima: il qcluster non si avvia, le schedule restano ferme.")

rete_guard.install()
