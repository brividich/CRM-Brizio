"""«Modifica OP»: il controllore corregge i dati di un OP che ha inserito lui.

Vale solo per gli OP creati dal portale («+ Nuovo OP» o al primo salvataggio di
un controllo): hanno ``sharepoint_item_id`` negativo e ``created_by`` = nome di
chi li ha creati, scritto da ``views._crea_op_response`` con la stessa regola di
:func:`nome_autore`. Gli OP del gestionale/SharePoint restano fuori: una
sincronizzazione riscriverebbe la correzione.

Si correggono P/N, capocommessa, CAR, fase, collaudo di benestare e note. Il
numero dell'OP no: anomalie, controlli, NC e code di notifica sono agganciati al
titolo; per un OP sbagliato c'è «Taglia» o «Cambia OP» del controllo.

Ogni modifica chiede una motivazione e finisce nell'AuditLog (prima/dopo) e
nella «Cronologia azioni» dell'OP (``AnomaliaActionLog`` con ``anomalia_id=0``).
"""
from __future__ import annotations

import logging

from django.db import connections, transaction

logger = logging.getLogger(__name__)

OP_ITEM_ID_COL = "sharepoint_item_id"
MOTIVAZIONE_MIN = 5

# campo del modulo -> (colonna, etichetta, lunghezza massima)
CAMPI = {
    "pn": ("part_number", "P/N", 200),
    "capocommessa": ("capocomessa", "Capocommessa", 255),
    "car": ("incaricato", "CAR", 255),
}
STATI_BENESTARE = {"aperto": "Aperto", "benestare": "Benestare"}


def _txt(value, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def nome_autore(request) -> str:
    """Nome scritto in ``created_by`` alla creazione dell'OP (stessa regola)."""
    from core.legacy_utils import get_legacy_user

    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    return _txt(
        (legacy_user.nome if legacy_user else None) or request.user.get_full_name() or request.user.username,
        255,
    )


def _norm(value) -> str:
    return " ".join(str(value or "").split()).casefold()


def is_op_locale(item_id) -> bool:
    try:
        return int(str(item_id or "").strip()) < 0
    except (TypeError, ValueError):
        return False


def op_modificabili_da(request) -> set[str]:
    """``sharepoint_item_id`` degli OP locali creati da chi fa la richiesta."""
    me = _norm(nome_autore(request))
    if not me:
        return set()
    from core.legacy_utils import legacy_table_columns

    if "created_by" not in (legacy_table_columns("ordini_produzione") or set()):
        return set()
    with connections["default"].cursor() as cur:
        cur.execute(f"SELECT {OP_ITEM_ID_COL}, created_by FROM ordini_produzione WHERE created_by IS NOT NULL")
        righe = cur.fetchall()
    return {str(r[0]).strip() for r in righe if is_op_locale(r[0]) and _norm(r[1]) == me}


def leggi_info(in1text: str) -> dict:
    """Scompone ``in1text`` («Fase X | Collaudo benestare: SI | note») nei campi del modulo."""
    fase, note = "", []
    for pezzo in str(in1text or "").split(" | "):
        pezzo = pezzo.strip()
        if not pezzo:
            continue
        if not fase and pezzo.lower().startswith("fase "):
            fase = pezzo[5:].strip()
        elif pezzo.lower().startswith("collaudo benestare:"):
            continue
        else:
            note.append(pezzo)
    return {"fase": fase, "note": " | ".join(note)}


def componi_info(fase: str, benestare: bool, note: str) -> str:
    pezzi = []
    if fase:
        pezzi.append(f"Fase {fase}")
    if benestare:
        pezzi.append("Collaudo benestare: SI")
    if note:
        pezzi.append(note)
    return _txt(" | ".join(pezzi), 255)


def riga_op(item_id) -> dict | None:
    from core.legacy_utils import legacy_table_columns

    cols = legacy_table_columns("ordini_produzione") or set()
    scelte = [c for c in ("id", OP_ITEM_ID_COL, "title", "part_number", "capocomessa", "incaricato", "stato",
                          "in1text", "created_by") if c in cols]
    with connections["default"].cursor() as cur:
        cur.execute(f"SELECT {', '.join(scelte)} FROM ordini_produzione WHERE {OP_ITEM_ID_COL} = %s",
                    [str(item_id).strip()])
        row = cur.fetchone()
    return dict(zip(scelte, row, strict=True)) if row else None


def dati_modulo(row: dict) -> dict:
    """Valori correnti dell'OP come li mostra il popup."""
    info = leggi_info(row.get("in1text") or "")
    stato = str(row.get("stato") or "").strip()
    return {
        "item_id": str(row.get(OP_ITEM_ID_COL) or ""),
        "op_id": row.get("title") or "",
        "pn": row.get("part_number") or "",
        "capocommessa": row.get("capocomessa") or "",
        "car": row.get("incaricato") or "",
        "fase": info["fase"],
        "note": info["note"],
        "benestare": stato.lower() == "benestare",
        # Il benestare si cambia solo fra «Aperto» e «Benestare»: altri stati restano.
        "benestare_modificabile": stato.lower() in STATI_BENESTARE or not stato,
    }


def puo_modificare(request, row: dict | None) -> bool:
    if not row or not is_op_locale(row.get(OP_ITEM_ID_COL)):
        return False
    me = _norm(nome_autore(request))
    return bool(me) and _norm(row.get("created_by")) == me


def applica(request, row: dict, dati: dict) -> dict:
    """Valida e scrive la modifica. ``{"modifiche": [...], "op": {...}}`` o ``ValueError``."""
    from core.legacy_utils import legacy_table_columns

    motivazione = _txt(dati.get("motivazione"), 500)
    if len(motivazione) < MOTIVAZIONE_MIN:
        raise ValueError("Scrivi il motivo della modifica")
    prima = dati_modulo(row)
    dopo = dict(prima)
    for campo, (_col, etichetta, limite) in CAMPI.items():
        if campo in dati:
            dopo[campo] = _txt(dati.get(campo), limite)
            if not dopo[campo]:
                raise ValueError(f"{etichetta} obbligatorio")
    if "fase" in dati:
        dopo["fase"] = _txt(dati.get("fase"), 30)
    if "note" in dati:
        dopo["note"] = _txt(dati.get("note"), 180)
    if "benestare" in dati and prima["benestare_modificabile"]:
        dopo["benestare"] = bool(dati.get("benestare"))

    etichette = {"pn": "P/N", "capocommessa": "Capocommessa", "car": "CAR", "fase": "Fase", "note": "Note",
                 "benestare": "Collaudo di benestare"}
    modifiche = []
    for campo, etichetta in etichette.items():
        if prima[campo] != dopo[campo]:
            if campo == "benestare":
                da, a = ("Sì" if prima[campo] else "No"), ("Sì" if dopo[campo] else "No")
            else:
                da, a = prima[campo] or "—", dopo[campo] or "—"
            modifiche.append({"campo": campo, "etichetta": etichetta, "da": da, "a": a})
    if not modifiche:
        raise ValueError("Nessun dato cambiato")

    cols = legacy_table_columns("ordini_produzione") or set()
    valori = {col: dopo[campo] for campo, (col, _e, _l) in CAMPI.items()}
    valori["in1text"] = componi_info(dopo["fase"], dopo["benestare"], dopo["note"])
    if prima["benestare_modificabile"] and prima["benestare"] != dopo["benestare"]:
        valori["stato"] = "Benestare" if dopo["benestare"] else "Aperto"
    stato = valori.get("stato") or row.get("stato") or ""
    valori["modified_by"] = nome_autore(request)
    valori = {c: v for c, v in valori.items() if c in cols}
    set_sql = [f"{c} = %s" for c in valori]
    params = list(valori.values())
    if "modified_datetime" in cols:
        adesso = "CURRENT_TIMESTAMP" if connections["default"].vendor == "sqlite" else "SYSUTCDATETIME()"
        set_sql.append(f"modified_datetime = {adesso}")
    with transaction.atomic(using="default"):
        with connections["default"].cursor() as cur:
            cur.execute(
                f"UPDATE ordini_produzione SET {', '.join(set_sql)} WHERE {OP_ITEM_ID_COL} = %s",
                params + [prima["item_id"]],
            )
    return {"modifiche": modifiche, "motivazione": motivazione, "prima": prima, "dopo": dopo, "stato": stato}


def testo_modifiche(modifiche: list[dict]) -> str:
    return "; ".join(f"{m['etichetta']}: {m['da']} → {m['a']}" for m in modifiche)
