"""Elenco unico degli OP: la tabella ``ordini_produzione``.

La tabella non appartiene a nessun modulo: la usa Gestione anomalie e la leggono gli
altri moduli che citano un OP, per esempio il Registro FAI. Il legame con un OP passa
dal suo titolo («OP/2026/123»), come fa Gestione anomalie quando manca l'id SharePoint.
Qui si legge soltanto: gli OP si creano da Gestione anomalie.
"""
from __future__ import annotations

from django.db import DatabaseError, connections

from core.legacy_utils import legacy_table_columns

TABELLA = "ordini_produzione"
MAX_RISULTATI = 15


def disponibile() -> bool:
    return bool(legacy_table_columns(TABELLA))


def _colonna_capo(colonne: set[str]) -> str | None:
    for nome in ("capocommessa", "capocomessa"):
        if nome in colonne:
            return nome
    return None


def _select(colonne: set[str]) -> str:
    def col(nome, alias):
        return f"{nome} AS {alias}" if nome and nome in colonne else f"NULL AS {alias}"

    return ", ".join((
        "title AS op", col("sharepoint_item_id", "item_id"), col("part_number", "pn"),
        col(_colonna_capo(colonne), "capocommessa"), col("incaricato", "car"), col("stato", "stato"),
    ))


def _righe(sql: str, parametri: list, limite: int | None = None) -> list[dict]:
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute(sql, parametri)
            nomi = [c[0] for c in cursor.description]
            dati = cursor.fetchmany(limite) if limite else cursor.fetchall()
    except DatabaseError:
        return []
    return [
        {k: (str(v).strip() if v is not None else "") for k, v in zip(nomi, riga)}
        for riga in dati
    ]


def cerca(testo: str, limite: int = MAX_RISULTATI) -> list[dict]:
    """OP il cui titolo o P/N contiene il testo, in ordine di titolo."""
    testo = (testo or "").strip()[:100]
    colonne = legacy_table_columns(TABELLA)
    if len(testo) < 2 or "title" not in colonne:
        return []
    filtro = "LOWER(title) LIKE %s"
    parametri = [f"%{testo.lower()}%"]
    if "part_number" in colonne:
        filtro += " OR LOWER(part_number) LIKE %s"
        parametri.append(f"%{testo.lower()}%")
    return _righe(
        f"SELECT {_select(colonne)} FROM {TABELLA} WHERE {filtro} ORDER BY title", parametri, limite
    )


def per_titolo(titolo: str) -> dict | None:
    """L'OP con questo titolo, senza badare a maiuscole e spazi ai lati."""
    titolo = (titolo or "").strip()[:100]
    colonne = legacy_table_columns(TABELLA)
    if not titolo or "title" not in colonne:
        return None
    righe = _righe(
        f"SELECT {_select(colonne)} FROM {TABELLA} WHERE LOWER(title) = %s ORDER BY id DESC",
        [titolo.lower()], 1,
    )
    return righe[0] if righe else None


def conta_anomalie(op: dict) -> dict:
    """Anomalie dell'OP, con lo stesso legame di Gestione anomalie: id SharePoint o titolo."""
    colonne = legacy_table_columns("anomalie")
    if not op or "ex_op_nominativo" not in colonne:
        return {"totale": 0, "aperte": 0}
    legame = "LOWER(ex_op_nominativo) = %s"
    parametri: list = [op["op"].lower()]
    try:
        item_id = int(op.get("item_id") or "")
    except ValueError:
        item_id = None
    if item_id is not None and "op_lookup_id" in colonne:
        legame = f"op_lookup_id = %s OR (op_lookup_id IS NULL AND {legame})"
        parametri.insert(0, item_id)
    aperte = "COALESCE(chiudere, 0) = 0" if "chiudere" in colonne else "1 = 1"
    righe = _righe(
        f"SELECT COUNT(*) AS totale, SUM(CASE WHEN {aperte} THEN 1 ELSE 0 END) AS aperte "
        f"FROM anomalie WHERE {legame}",
        parametri, 1,
    )
    riga = righe[0] if righe else {}
    return {"totale": int(riga.get("totale") or 0), "aperte": int(riga.get("aperte") or 0)}
