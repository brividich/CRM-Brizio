"""Bridge read-only: assenze già confermate per dipendente in una finestra.

Primo (ed unico) consumatore: l'overlay "abilitati assenti" dei Carichi Macchina,
che — via la Skill Matrix MOD.187 — sa quali ``legacy_anagrafica_id`` operano su
una macchina e qui chiede quali di loro hanno un'assenza **già programmata** nei
giorni della finestra Gantt.

Principi (allineati al resto del modulo assenze):
- **sola lettura**, **fail-safe**: nessuna eccezione propaga; sorgente legacy
  mancante o malformata → ``{}`` (l'overlay semplicemente non mostra nulla);
- il match dipendente→assenza riusa la chiave storica del modulo (``copia_nome`` /
  ``email_esterna``), tollerante all'ordine "Cognome Nome" / "Nome Cognome";
- "confermata" = ``moderation_status`` Approvato (0) o Programmato (4), oppure il
  testo ``consenso`` equivalente per le righe legacy senza ``moderation_status``.

La logica di costruzione delle chiavi nome è pura e testabile (``_name_variants``);
l'accesso DB è isolato in ``_fetch_dict`` / ``_resolve_identities`` per poterlo
mockare nei test senza DDL legacy.
"""
from __future__ import annotations

import logging
from datetime import date, datetime

from django.db import connections

from core.legacy_utils import legacy_table_columns

logger = logging.getLogger(__name__)

# moderation_status considerati "pianificabili" (l'assenza c'è già): Approvato + Programmato.
_STATI_CONFERMATI_MOD = (0, 4)
_STATI_CONFERMATI_TXT = ("APPROVATO", "PROGRAMMATO")


def _as_date(value):
    """date | datetime | 'YYYY-MM-DD[...]' → date, altrimenti None (fail-safe)."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    return None


def _norm_key(text) -> str:
    """Chiave di confronto: spazi compattati + UPPER (omogenea a copia_nome)."""
    return " ".join(str(text or "").split()).upper()


def _name_variants(nome: str, cognome: str) -> set[str]:
    """Varianti normalizzate del nome, per assorbire l'ordine usato in copia_nome."""
    nome = (nome or "").strip()
    cognome = (cognome or "").strip()
    out: set[str] = set()
    if nome or cognome:
        out.add(_norm_key(f"{cognome} {nome}"))
        out.add(_norm_key(f"{nome} {cognome}"))
    out.discard("")
    return out


def _fetch_dict(sql: str, params) -> list[dict]:
    with connections["default"].cursor() as cur:
        cur.execute(sql, list(params or []))
        cols = [str(c[0]) for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _resolve_identities(anagrafica_ids) -> dict[int, dict]:
    """``anagrafica_id`` → {nome, cognome, names:set, emails:set} dall'anagrafica legacy.

    ``email`` legacy è lo *username* (non un indirizzo): si tiene solo ciò che
    contiene "@" (di norma ``email_notifica``).
    """
    ids = sorted({int(i) for i in anagrafica_ids if i is not None})
    if not ids:
        return {}
    cols = set(legacy_table_columns("anagrafica_dipendenti") or [])
    if not {"id", "nome", "cognome"}.issubset(cols):
        return {}
    sel = [c for c in ("id", "nome", "cognome", "email", "email_notifica") if c in cols]
    placeholders = ", ".join(["%s"] * len(ids))
    rows = _fetch_dict(
        f"SELECT {', '.join(sel)} FROM anagrafica_dipendenti WHERE id IN ({placeholders})",
        ids,
    )
    out: dict[int, dict] = {}
    for r in rows:
        aid = r.get("id")
        if aid is None:
            continue
        nome = str(r.get("nome") or "").strip()
        cognome = str(r.get("cognome") or "").strip()
        emails = set()
        for e in (r.get("email_notifica"), r.get("email")):
            e = str(e or "").strip().upper()
            if e and "@" in e:
                emails.add(e)
        out[int(aid)] = {
            "nome": nome,
            "cognome": cognome,
            "names": _name_variants(nome, cognome),
            "emails": emails,
        }
    return out


def assenze_per_anagrafica(anagrafica_ids, start, end) -> dict[int, list[dict]]:
    """Assenze confermate (overlap con ``[start, end]``) raggruppate per anagrafica_id.

    Ritorna ``{anagrafica_id: [{"data_inizio", "data_fine", "tipo", "nome"}, ...]}``.
    Fail-safe: ``{}`` se manca la sorgente o nessun id risolto.
    """
    start = _as_date(start)
    end = _as_date(end)
    ids = sorted({int(i) for i in (anagrafica_ids or []) if i is not None})
    if not ids or not start or not end or start > end:
        return {}
    try:
        identities = _resolve_identities(ids)
        if not identities:
            return {}

        cols = set(legacy_table_columns("assenze") or [])
        if not {"data_inizio", "data_fine"}.issubset(cols):
            return {}

        # Indici inversi chiave→anagrafica_id (un nome può, per omonimia, mappare più id).
        name_to_aids: dict[str, set[int]] = {}
        email_to_aids: dict[str, set[int]] = {}
        for aid, info in identities.items():
            for nm in info["names"]:
                name_to_aids.setdefault(nm, set()).add(aid)
            for em in info["emails"]:
                email_to_aids.setdefault(em, set()).add(aid)
        all_names = sorted(name_to_aids)
        all_emails = sorted(email_to_aids)
        if not all_names and not all_emails:
            return {}

        has_copia = "copia_nome" in cols
        has_email = "email_esterna" in cols
        has_tipo = "tipo_assenza" in cols
        has_mod = "moderation_status" in cols
        has_cons = "consenso" in cols

        sel = ["data_inizio", "data_fine"]
        for opt in ("copia_nome", "email_esterna", "tipo_assenza", "moderation_status", "consenso"):
            if opt in cols:
                sel.append(opt)

        who: list[str] = []
        who_params: list = []
        if has_copia and all_names:
            who.append("UPPER(COALESCE(copia_nome,'')) IN (%s)" % ", ".join(["%s"] * len(all_names)))
            who_params.extend(all_names)
        if has_email and all_emails:
            who.append("UPPER(COALESCE(email_esterna,'')) IN (%s)" % ", ".join(["%s"] * len(all_emails)))
            who_params.extend(all_emails)
        if not who:
            return {}

        status: list[str] = []
        if has_mod:
            status.append("COALESCE(moderation_status, -1) IN (%d, %d)" % _STATI_CONFERMATI_MOD)
        if has_cons:
            status.append(
                "UPPER(COALESCE(consenso,'')) IN (%s)"
                % ", ".join("'%s'" % s for s in _STATI_CONFERMATI_TXT)
            )
        status_sql = "(" + " OR ".join(status) + ")" if status else "1=1"

        sql = (
            f"SELECT {', '.join(sel)} FROM assenze "
            "WHERE data_inizio IS NOT NULL AND data_fine IS NOT NULL "
            "AND data_fine >= %s AND data_inizio <= %s "
            f"AND {status_sql} AND (" + " OR ".join(who) + ")"
        )
        rows = _fetch_dict(sql, [start, end, *who_params])

        out: dict[int, list[dict]] = {}
        seen: set[tuple] = set()  # dedupe (aid, di, df, tipo)
        for r in rows:
            di = _as_date(r.get("data_inizio"))
            df = _as_date(r.get("data_fine"))
            if not di or not df:
                continue
            if df < di:
                di, df = df, di
            tipo = str(r.get("tipo_assenza") or "").strip() or "Assenza"
            display = str(r.get("copia_nome") or "").strip()
            aids: set[int] = set()
            nm = _norm_key(r.get("copia_nome"))
            if nm:
                aids |= name_to_aids.get(nm, set())
            em = _norm_key(r.get("email_esterna"))
            if em:
                aids |= email_to_aids.get(em, set())
            for aid in aids:
                key = (aid, di, df, tipo)
                if key in seen:
                    continue
                seen.add(key)
                info = identities.get(aid) or {}
                nome = display or f"{info.get('cognome', '')} {info.get('nome', '')}".strip() or f"ID {aid}"
                out.setdefault(aid, []).append({
                    "data_inizio": di,
                    "data_fine": df,
                    "tipo": tipo,
                    "nome": nome,
                })
        return out
    except Exception:
        logger.warning("assenze_per_anagrafica fallita (ids=%d)", len(ids), exc_info=True)
        return {}
