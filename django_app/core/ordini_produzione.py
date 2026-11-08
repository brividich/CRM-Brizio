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
        "id AS id", "title AS op", col("sharepoint_item_id", "item_id"), col("part_number", "pn"),
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


def per_id(pk: int) -> dict | None:
    colonne = legacy_table_columns(TABELLA)
    if "title" not in colonne:
        return None
    righe = _righe(f"SELECT {_select(colonne)} FROM {TABELLA} WHERE id = %s", [int(pk)], 1)
    return righe[0] if righe else None


def elenco(testo: str = "", stato: str = "") -> list[dict]:
    """Tutti gli OP, filtrati per testo (titolo, P/N, capocommessa, CAR) e stato, i più recenti prima."""
    colonne = legacy_table_columns(TABELLA)
    if "title" not in colonne:
        return []
    filtri, parametri = [], []
    testo = (testo or "").strip()[:100].lower()
    if testo:
        campi = ["title"] + [c for c in ("part_number", _colonna_capo(colonne), "incaricato") if c and c in colonne]
        filtri.append("(" + " OR ".join(f"LOWER({c}) LIKE %s" for c in campi) + ")")
        parametri += [f"%{testo}%"] * len(campi)
    if stato and "stato" in colonne:
        filtri.append("stato = %s")
        parametri.append(stato[:50])
    where = f"WHERE {' AND '.join(filtri)}" if filtri else ""
    return _righe(f"SELECT {_select(colonne)} FROM {TABELLA} {where} ORDER BY id DESC", parametri)


def stati() -> list[str]:
    if "stato" not in legacy_table_columns(TABELLA):
        return []
    righe = _righe(f"SELECT DISTINCT stato AS stato FROM {TABELLA} WHERE stato IS NOT NULL AND stato <> ''", [])
    return sorted({r["stato"] for r in righe if r["stato"]})


def anomalie_aperte_per_op() -> dict[str, int]:
    """Anomalie aperte per titolo OP (in minuscolo), per l'elenco."""
    colonne = legacy_table_columns("anomalie")
    if "ex_op_nominativo" not in colonne:
        return {}
    aperte = "WHERE COALESCE(chiudere, 0) = 0" if "chiudere" in colonne else ""
    righe = _righe(
        f"SELECT LOWER(ex_op_nominativo) AS op, COUNT(*) AS n FROM anomalie {aperte} GROUP BY LOWER(ex_op_nominativo)", []
    )
    return {r["op"]: int(r["n"] or 0) for r in righe if r["op"]}


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
