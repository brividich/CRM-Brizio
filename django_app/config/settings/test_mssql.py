"""Profilo test su SQL Server vero, per provare i rami di codice che su SQLite non
girano mai (SQL scritto a mano, ``connection.vendor == "microsoft"``, migrazioni).

Uguale a ``config.settings.test`` salvo il database, letto da variabili dedicate e mai
da ``DB_*`` del ``.env`` (che in sviluppo punta al DB locale condiviso tra le sessioni):

    TEST_MSSQL_HOST       obbligatoria, es. ``localhost\\HUBTEST``
    TEST_MSSQL_USER       facoltativa; vuota = autenticazione Windows
    TEST_MSSQL_PASSWORD
    TEST_MSSQL_DRIVER     default ``ODBC Driver 18 for SQL Server``
    TEST_MSSQL_DB         default ``test_hub_mssql`` (deve iniziare con ``test_``)

Django crea e cancella solo il database ``TEST_MSSQL_DB``; serve il ruolo ``dbcreator``.
"""

import os

from .test import *  # noqa: F403,F401

# Il server di produzione non deve mai fare da DB di test, neanche per sbaglio.
_HOSTS_VIETATI = ("NOVISQL", "PCLOGSYS")

_host = os.getenv("TEST_MSSQL_HOST", "").strip()
_db_name = os.getenv("TEST_MSSQL_DB", "test_hub_mssql").strip()
if not _host:
    raise RuntimeError(
        "config.settings.test_mssql: imposta TEST_MSSQL_HOST (es. localhost\\HUBTEST). "
        "Vedi docs/ai/06_TESTING_AND_QUALITY_GATES.md, «Test su SQL Server»."
    )
if any(vietato in _host.upper() for vietato in _HOSTS_VIETATI):
    raise RuntimeError(f"config.settings.test_mssql: {_host!r} e' un server di produzione.")
if not _db_name.lower().startswith("test_"):
    raise RuntimeError(f"config.settings.test_mssql: TEST_MSSQL_DB deve iniziare con 'test_' ({_db_name!r}).")

_user = os.getenv("TEST_MSSQL_USER", "").strip()
_extra_params = "TrustServerCertificate=yes;"
if not _user:
    _extra_params += "Trusted_Connection=yes;"

DATABASES = {
    "default": {
        "ENGINE": "mssql",
        "NAME": _db_name,
        "HOST": _host,
        "USER": _user,
        "PASSWORD": os.getenv("TEST_MSSQL_PASSWORD", ""),
        "CONN_MAX_AGE": 0,
        "OPTIONS": {
            "driver": os.getenv("TEST_MSSQL_DRIVER", "ODBC Driver 18 for SQL Server"),
            "extra_params": _extra_params,
            "query_timeout": 0,
        },
        "TEST": {"NAME": _db_name},
    }
}
