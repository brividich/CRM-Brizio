"""Profilo di SOLA LETTURA verso il database di produzione.

Serve per diagnosticare sui dati veri (conteggi, stati, `--dry-run`) da una
macchina di sviluppo, senza poter scrivere nulla. NON e' un profilo di runtime:
non serve un sito, non fa migrate, non e' usato dal deploy.

Uso::

    python django_app\\manage.py <comando> --settings=config.settings.prod_readonly

Configurazione: file ``.env.prod_readonly`` nella radice del repo (ignorato da
git; vedi ``docs/env.prod_readonly.example``). Percorso alternativo con la
variabile d'ambiente ``PROD_READONLY_ENV_FILE``.

Chiavi lette (prefisso dedicato, per non collidere con le ``DB_*`` del ``.env``
di sviluppo)::

    PRODRO_DB_HOST, PRODRO_DB_NAME, PRODRO_DB_USER, PRODRO_DB_PASSWORD,
    PRODRO_DB_DRIVER, PRODRO_DB_TRUST_CERT, PRODRO_DB_ENCRYPT

**Due barriere, non una.** La barriera autorevole e' il *grant* sul server SQL:
l'utenza va creata con il solo ruolo ``db_datareader`` (vedi
``docs/prod_readonly_login.sql``). Questo modulo aggiunge una seconda barriera
lato client — un ``execute_wrapper`` che rifiuta DML/DDL prima ancora che la
query parta, e un router che vieta le migrazioni — cosi' un errore di
configurazione del login non si traduce in una scrittura in produzione.
"""

from __future__ import annotations

import os
from pathlib import Path

from config.env_config import load_env_file_values
from config.readonly_guard import ReadOnlyRouter, install as install_readonly_guard  # noqa: F401

from .base import *  # noqa: F403,F401
from .base import PROJECT_DIR


DEBUG = False
ALLOWED_HOSTS: list[str] = []
SETUP_WIZARD_REQUIRED = False

# Nessuna scrittura collaterale all'avvio: la cache di base e' su tabella SQL.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "novicrom-prod-readonly",
    }
}

# Nessun invio di email da un profilo di diagnosi.
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"


# ---------------------------------------------------------------------------
# Connessione: letta da un file dedicato, mai dal .env di sviluppo
# ---------------------------------------------------------------------------

_ENV_PATH = Path(os.getenv("PROD_READONLY_ENV_FILE") or (PROJECT_DIR.parent / ".env.prod_readonly"))
_FILE_VALUES = load_env_file_values(_ENV_PATH) if _ENV_PATH.exists() else {}


def _ro(key: str, default: str = "") -> str:
    """Valore dal file dedicato, con fallback sull'ambiente di processo."""
    return str(_FILE_VALUES.get(key) or os.getenv(key) or default).strip()


_DB_HOST = _ro("PRODRO_DB_HOST")
_DB_NAME = _ro("PRODRO_DB_NAME")

if not _DB_HOST or not _DB_NAME:
    # NON ImproperlyConfigured: `ManagementUtility.execute` la cattura e la
    # trasforma in `settings_exception`, lasciando girare il comando con
    # DATABASES vuoto — `manage.py check` arriverebbe a dire "no issues" su un
    # profilo non configurato. RuntimeError invece esce subito, col messaggio.
    raise RuntimeError(
        "Profilo prod_readonly non configurato: manca PRODRO_DB_HOST e/o PRODRO_DB_NAME.\n"
        f"Atteso il file: {_ENV_PATH}\n"
        "Template: docs/env.prod_readonly.example - login SQL: docs/prod_readonly_login.sql"
    )

_DB_USER = _ro("PRODRO_DB_USER")
_extra_params = f"TrustServerCertificate={'yes' if _ro('PRODRO_DB_TRUST_CERT') in {'1', 'true', 'yes', 'on'} else 'no'};"
if _ro("PRODRO_DB_ENCRYPT"):
    _extra_params += f"Encrypt={'yes' if _ro('PRODRO_DB_ENCRYPT') in {'1', 'true', 'yes', 'on'} else 'no'};"
if not _DB_USER:
    _extra_params += "Trusted_Connection=yes;"

DATABASES = {
    "default": {
        "ENGINE": "mssql",
        "NAME": _DB_NAME,
        "HOST": _DB_HOST,
        "USER": _DB_USER,
        "PASSWORD": _ro("PRODRO_DB_PASSWORD"),
        "OPTIONS": {
            "driver": _ro("PRODRO_DB_DRIVER", "ODBC Driver 18 for SQL Server"),
            "extra_params": _extra_params,
        },
    }
}


# ---------------------------------------------------------------------------
# Barriera lato client (la barriera autorevole e' il grant db_datareader)
# ---------------------------------------------------------------------------

install_readonly_guard()

DATABASE_ROUTERS = ["config.readonly_guard.ReadOnlyRouter"]
