"""Copilota AI per i DPI (Ondata 3.3).

Dalla **mansione** (e da eventuali note su attivita'/rischi) propone un **set di
DPI** appropriato, **scegliendo SOLO dal catalogo reale** (CategoriaDPI/TipoDPI
attivi) e includendo sempre le categorie **obbligatorie da mansionario**.

VINCOLO INVALICABILE: l'AI **propone**, il gestore rivede e firma. Questo modulo
non scrive nulla nel DB e non crea richieste: ogni output ha ``proposto=True``.
Fail-safe (AI offline => solo le categorie obbligatorie, ``ai_disponibile=False``).

NB: non esiste (oggi) una tabella rischio->DPI o mansione->DPI nel modulo; la base
deterministica e' il **catalogo** + il flag ``obbligatoria_mansionario``. La mappa
mansione->DPI e' una **proposta** dell'AI vincolata al catalogo, da validare.
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

_MAX_NOTE = 1500


def _chiama_ai(prompt: str, *, runtime_context: str = "") -> str:
    try:
        from ai_assistant.services import chat_with_ollama
        res = chat_with_ollama(prompt, runtime_context=runtime_context)
        return getattr(res, "content", "") or ""
    except Exception as exc:  # pragma: no cover - dipende dall'ambiente
        logger.debug("dpi copilota AI non disponibile: %s", exc)
        return ""


def _parse_json_list(raw: str) -> list[dict]:
    if not raw:
        return []
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    blob = m.group(0) if m else raw
    try:
        data = json.loads(blob)
    except Exception:
        return []
    return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []


def proponi_dpi_mansione(*, mansione: str, note: str, categorie, obbligatorie) -> dict:
    """Proposta (NON salvata) di un set DPI per la mansione. Solo dal catalogo.

    Args:
        mansione: nome mansione (testo libero).
        note: note opzionali su attivita'/rischi.
        categorie: iterabile di dict ``{"nome": str, "tipi": [str, ...]}`` (catalogo attivo).
        obbligatorie: iterabile di nomi-categoria obbligatorie da mansionario.
    """
    mansione = (mansione or "").strip()
    note = (note or "").strip()[:_MAX_NOTE]
    categorie = list(categorie or [])
    obbligatorie_set = {str(n or "").strip().lower() for n in (obbligatorie or []) if str(n or "").strip()}

    # Indici per la validazione: nome-categoria -> nome canonico, e mappa
    # tipo-lowercase -> tipo-originale per ciascuna categoria.
    cat_canon: dict[str, str] = {}
    tipi_canon_per_cat: dict[str, dict[str, str]] = {}
    for c in categorie:
        nome = str(c.get("nome") or "").strip()
        if not nome:
            continue
        cat_canon[nome.lower()] = nome
        tipi_canon_per_cat[nome.lower()] = {
            str(t or "").strip().lower(): str(t or "").strip()
            for t in (c.get("tipi") or [])
            if str(t or "").strip()
        }

    cat_lines = "\n".join(
        f"- {str(c.get('nome') or '').strip()}: " + (", ".join(c.get("tipi") or []) or "(nessun tipo)")
        for c in categorie
        if str(c.get("nome") or "").strip()
    ) or "(catalogo vuoto)"
    obbl_lines = ", ".join(sorted({cat_canon.get(n, n) for n in obbligatorie_set})) or "(nessuna)"

    prompt = (
        "Sei un responsabile sicurezza. Per la MANSIONE indicata proponi i DPI necessari "
        "scegliendo ESCLUSIVAMENTE dal CATALOGO sotto (categorie e relativi tipi). "
        "Rispondi con SOLO JSON: lista di oggetti con chiavi \"categoria\" (un nome dal "
        "catalogo), \"tipi\" (lista di tipi di quella categoria, eventualmente vuota) e "
        "\"motivazione\" (breve, perche' serve per questa mansione). Non inventare DPI fuori "
        "catalogo. Includi sempre le categorie obbligatorie. Nessun testo fuori dal JSON.\n\n"
        f"CATALOGO DPI:\n{cat_lines}\n\n"
        f"CATEGORIE OBBLIGATORIE (mansionario): {obbl_lines}\n\n"
        f"MANSIONE: {mansione[:200]}\n"
        f"NOTE (attivita'/rischi): {note or '(nessuna)'}"
    )
    raw = _chiama_ai(
        prompt,
        runtime_context="Copilota DPI: proposta set DPI per mansione, il gestore rivede e firma.",
    )
    proposte = _parse_json_list(raw)

    # Sanitizzazione: tieni solo categorie nel catalogo; filtra i tipi a quelli reali.
    dpi_per_cat: dict[str, dict] = {}
    for p in proposte:
        nome = str(p.get("categoria") or "").strip()
        key = nome.lower()
        if key not in cat_canon:
            continue  # categoria fuori catalogo -> scartata
        tipi_canon = tipi_canon_per_cat.get(key, {})
        tipi_out = [
            tipi_canon[str(t).strip().lower()]
            for t in (p.get("tipi") or [])
            if str(t).strip().lower() in tipi_canon
        ]
        dpi_per_cat[key] = {
            "categoria": cat_canon[key],
            "tipi": tipi_out,
            "obbligatoria": key in obbligatorie_set,
            "motivazione": str(p.get("motivazione") or "").strip()[:300],
        }

    # Le obbligatorie devono sempre comparire, anche se l'AI le ha omesse o e' offline.
    for key in obbligatorie_set:
        if key not in dpi_per_cat and key in cat_canon:
            dpi_per_cat[key] = {
                "categoria": cat_canon[key],
                "tipi": [],
                "obbligatoria": True,
                "motivazione": "Richiesta dal mansionario.",
            }
        elif key in dpi_per_cat:
            dpi_per_cat[key]["obbligatoria"] = True

    # Ordina: obbligatorie prima, poi per nome.
    dpi = sorted(dpi_per_cat.values(), key=lambda d: (not d["obbligatoria"], d["categoria"].lower()))

    return {
        "proposto": True,
        "fonte": "ai",
        "ai_disponibile": bool(raw),
        "mansione": mansione,
        "dpi": dpi,
    }
