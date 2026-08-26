"""Barriera lato client contro le scritture, per i profili di sola lettura.

Usata da ``config.settings.prod_readonly``. Vive fuori dal modulo di settings
perche' l'installazione dev'essere un gesto **esplicito** (``install()``):
importare questo modulo non deve poter rendere read-only le connessioni di un
processo che non l'ha chiesto — per esempio la suite di test.

La barriera autorevole resta il grant sul server SQL (``db_datareader``); questa
e' la seconda rete, quella che ferma la query prima che parta.
"""

from __future__ import annotations

import re

from django.db.backends.signals import connection_created


class ReadOnlyViolation(Exception):
    """Una query di scrittura e' stata tentata su una connessione di sola lettura."""


# `create`/`drop`/`alter` inclusi: su un profilo di diagnosi nessuna DDL ha
# motivo di partire. Il `WITH ...` iniziale e' consentito perche' una CTE puo'
# precedere sia una SELECT sia una INSERT: si guarda il verbo che segue.
WRITE_STATEMENT_RE = re.compile(
    r"^\s*(?:with\b.*?\)\s*)?"
    r"(insert|update|delete|merge|truncate|drop|alter|create|grant|revoke|backup|restore)\b",
    re.IGNORECASE | re.DOTALL,
)


def is_write_statement(sql: str | None) -> bool:
    return bool(WRITE_STATEMENT_RE.match(sql or ""))


def reject_writes(execute, sql, params, many, context):
    """``execute_wrapper`` che rifiuta le istruzioni di scrittura."""
    if is_write_statement(sql):
        raise ReadOnlyViolation(
            "Connessione di sola lettura: scrittura bloccata lato client -> "
            f"{' '.join(str(sql).split())[:160]}"
        )
    return execute(sql, params, many, context)


class ReadOnlyRouter:
    """Vieta le migrazioni: `migrate` non deve nemmeno partire."""

    def allow_migrate(self, db, app_label, model_name=None, **hints):  # noqa: ARG002
        return False


def _attach(sender, connection, **kwargs):  # noqa: ARG001
    if reject_writes not in connection.execute_wrappers:
        connection.execute_wrappers.append(reject_writes)


def install() -> None:
    """Aggancia la barriera a ogni connessione creata da qui in avanti."""
    connection_created.connect(_attach, dispatch_uid="config.readonly_guard")
