"""Incaricato per singola anomalia: chi ha in carico un ruolo al posto di quello di serie.

Di serie l'anomalia è in carico per ruolo (``decisione_qualita.ruoli_in_carico``):
capocommessa dell'OP, qualità (referenti RDC), controllore (chi l'ha inserita), CAR
segnalati. Capocommessa, CAR e amministratori possono affidare un ruolo a una
persona precisa: da quel momento quel ruolo, su quell'anomalia, tocca solo a lei
(«In carico a me», elenco OP, contatori, richieste di informazioni, mail).

Salvato in ``AnomaliaIncaricato`` (una riga per anomalia e ruolo). In memoria::

    {"cc": {"id": <utenti.id>, "nome": "ROSSI MARIO", "da": "...", "il": "dd/mm/aaaa hh:mm", "nota": "..."}}

Togliere l'incaricato riporta il ruolo alla regola di serie.
"""
from __future__ import annotations

import logging

from django.utils import timezone

logger = logging.getLogger(__name__)

RUOLI = ("cc", "qualita", "controllore", "car", "car_op")
NOMI_RUOLO = {"cc": "capocommessa", "qualita": "qualità", "controllore": "controllore", "car": "CAR segnalato",
              "car_op": "CAR dell'OP"}
# Ordine con cui si sceglie il ruolo «principale» che ha l'anomalia adesso.
PRIORITA = ("cc", "qualita", "controllore", "car_op", "car")


def ruolo_valido(ruolo: str) -> bool:
    return ruolo in RUOLI or (ruolo.startswith("p:") and ruolo[2:].isdigit() and len(ruolo) <= 16)


def nome_ruolo(ruolo: str) -> str:
    return NOMI_RUOLO.get(ruolo) or ("persona indicata" if ruolo.startswith("p:") else ruolo)


def ruolo_attuale(ruoli) -> str:
    """Il ruolo che ha l'anomalia adesso: «Cambia incaricato» lo passa alla persona scelta."""
    ruoli = set(ruoli or ())
    for r in PRIORITA:
        if r in ruoli:
            return r
    persone = sorted(r for r in ruoli if r.startswith("p:"))
    return persone[0] if persone else ""


def per_anomalie(ids) -> dict[int, dict]:
    """``{anomalia_id: {ruolo: {...}}}`` per molte anomalie (una query)."""
    from .quality_models import AnomaliaIncaricato

    out: dict[int, dict] = {}
    ids = sorted({int(i) for i in ids if i is not None})
    for i in range(0, len(ids), 500):
        for x in AnomaliaIncaricato.objects.filter(anomalia_id__in=ids[i:i + 500]):
            if ruolo_valido(x.ruolo):
                out.setdefault(x.anomalia_id, {})[x.ruolo] = _voce(x)
    return out


def _voce(x) -> dict:
    return {"id": x.legacy_user_id, "nome": x.nome, "da": x.assegnato_da, "nota": x.nota,
            "il": timezone.localtime(x.assegnato_il).strftime("%d/%m/%Y %H:%M") if x.assegnato_il else ""}


def e_incaricato(info: dict | None, ruolo: str, legacy_id) -> bool:
    inc = (info or {}).get("incaricati") or {}
    if ruolo not in inc or legacy_id is None:
        return False
    try:
        return int(inc[ruolo]["id"]) == int(legacy_id)
    except (TypeError, ValueError, KeyError):
        return False


# ── Persone ────────────────────────────────────────────────────────────────


def persone(ruolo: str) -> list[dict]:
    """Chi si può scegliere: utenti attivi del portale (la qualità solo fra i
    referenti RDC di Configurazione, gli unici che decidono la qualità)."""
    from core import naming
    from core.legacy_models import AnagraficaDipendente, UtenteLegacy

    from .views import _chiave_persona, _load_anomalie_lists

    nomi = {}
    try:
        for d in AnagraficaDipendente.objects.filter(utente__isnull=False).only("nome", "cognome", "utente_id"):
            n = naming.nome_completo(d.nome, d.cognome)
            if n:
                nomi[d.utente_id] = n
        utenti = list(UtenteLegacy.objects.filter(attivo=True).only("id", "nome"))
    except Exception:
        logger.warning("incaricati: elenco persone non letto", exc_info=True)
        return []
    out = [{"id": u.id, "nome": nomi.get(u.id) or str(u.nome or "").strip()} for u in utenti]
    out = [p for p in out if p["nome"]]
    if ruolo == "qualita_referenti":
        try:
            ref = {_chiave_persona(v) for v in (_load_anomalie_lists().get("referenti_rdc") or []) if v}
        except Exception:
            ref = set()
        out = [p for p in out if _chiave_persona(p["nome"]) in ref]
    return sorted(out, key=lambda p: p["nome"].lower())


def persona(uid) -> dict | None:
    from core import naming
    from core.legacy_models import AnagraficaDipendente, UtenteLegacy

    try:
        u = UtenteLegacy.objects.filter(pk=int(uid), attivo=True).only("id", "nome").first()
    except (TypeError, ValueError):
        return None
    if u is None:
        return None
    d = AnagraficaDipendente.objects.filter(utente_id=u.id).only("nome", "cognome").first()
    nome = (naming.nome_completo(d.nome, d.cognome) if d else "") or str(u.nome or "").strip()
    return {"id": u.id, "nome": nome}


# ── Permessi e OP ──────────────────────────────────────────────────────────


def puo_cambiare_su_op(request, capo, car) -> bool:
    """Amministratori del modulo, capocommessa e CAR dell'OP: su tutte le sue anomalie."""
    from core.acl import user_can_modulo_action

    from .models import AnomalieRoleType
    from .views import _op_role_codes_da_persone

    user = getattr(request, "user", None)
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    try:
        if user_can_modulo_action(request, "anomalie", "admin_anomalie"):
            return True
    except Exception:
        pass
    return bool(set(_op_role_codes_da_persone(request, capo, car))
                & {AnomalieRoleType.CAPO_COMMESSA, AnomalieRoleType.CAR})


def puo_cambiare_su_anomalia(request, info: dict | None) -> bool:
    """CAR segnalati e chi ha già l'incarico di capocommessa o CAR di quell'anomalia."""
    from .views import _chiave_persona, _request_legacy_user_id, _request_name_norms

    info = info or {}
    mie = {_chiave_persona(n) for n in _request_name_norms(request)}
    if mie & {_chiave_persona(n) for n in info.get("car_assegnati") or []}:
        return True
    me = _request_legacy_user_id(request)
    return any(e_incaricato(info, r, me) for r in ("cc", "car"))


def puo_cambiare(request, row: dict, info: dict | None = None) -> bool:
    from . import decisione_qualita as dq
    from .views import _capo_car_di_op

    capo, car = _capo_car_di_op(str((row or {}).get("ex_op_nominativo") or "").strip())
    if puo_cambiare_su_op(request, capo, car):
        return True
    if info is None:
        aid = (row or {}).get("id")
        info = dq.info_per_anomalie([aid]).get(int(aid)) if aid else None
    return puo_cambiare_su_anomalia(request, info)


def incaricato_qualita(request, anomalia_id) -> bool:
    from .views import _request_legacy_user_id

    me = _request_legacy_user_id(request)
    try:
        info = {"incaricati": per_anomalie([anomalia_id]).get(int(anomalia_id)) or {}}
    except Exception:
        return False
    return e_incaricato(info, "qualita", me)


def anomalie_incaricato(legacy_id) -> dict[int, set[str]]:
    """``{anomalia_id: {ruoli}}`` affidati a quell'utente (per visibilità e modifica)."""
    from .quality_models import AnomaliaIncaricato

    out: dict[int, set[str]] = {}
    if legacy_id is None:
        return out
    try:
        for aid, ruolo in AnomaliaIncaricato.objects.filter(legacy_user_id=int(legacy_id)).values_list(
                "anomalia_id", "ruolo"):
            out.setdefault(int(aid), set()).add(ruolo)
    except Exception:
        logger.warning("incaricati: anomalie affidate non lette", exc_info=True)
    return out


def op_incaricato(request, *, ruoli=None) -> set[str]:
    """Titoli OP (minuscoli) con anomalie aperte affidate a chi guarda."""
    from .views import _fetch_all_dict, _request_legacy_user_id

    cache_key = f"_anomalie_op_incaricato_{'-'.join(sorted(ruoli)) if ruoli else 'tutti'}"
    cached = getattr(request, cache_key, None)
    if cached is not None:
        return cached
    me = _request_legacy_user_id(request)
    mie = anomalie_incaricato(me)
    ids = [aid for aid, r in mie.items() if not ruoli or (r & set(ruoli))]
    out: set[str] = set()
    try:
        out |= _op_da_regole(me)
    except Exception:
        logger.warning("incaricati: OP dalla tabella «in carico» non letti", exc_info=True)
    for i in range(0, len(ids), 500):
        blocco = ids[i:i + 500]
        try:
            for r in _fetch_all_dict(
                    f"SELECT ex_op_nominativo FROM anomalie WHERE COALESCE(chiudere, 0) = 0 AND id IN "
                    f"({','.join(['%s'] * len(blocco))})", blocco):
                titolo = str(r.get("ex_op_nominativo") or "").strip().lower()
                if titolo:
                    out.add(titolo)
        except Exception:
            logger.warning("incaricati: OP affidati non letti", exc_info=True)
    try:
        setattr(request, cache_key, out)
    except Exception:
        pass
    return out


def _op_da_regole(me) -> set[str]:
    """OP con anomalie aperte che la tabella «Chi ha in carico l'anomalia» dà a
    questa persona (solo se la tabella la nomina: altrimenti nessuna query)."""
    from . import decisione_qualita as dq
    from .regole_carico import persone_destinazione
    from .views import _fetch_all_dict, legacy_table_columns

    if me is None or int(me) not in persone_destinazione():
        return set()
    cols = legacy_table_columns("anomalie") or set()
    voluti = ("id", "ex_op_nominativo", "chiudere", "aprire_rdc", "numero_rdc", "segnalare_cliente",
              "note_capocommessa", "avanzamento")
    righe = _fetch_all_dict(f"SELECT {', '.join(c for c in voluti if c in cols)} FROM anomalie "
                            "WHERE COALESCE(chiudere, 0) = 0")
    info = dq.info_per_anomalie([r["id"] for r in righe if r.get("id") is not None])
    return {str(r.get("ex_op_nominativo") or "").strip().lower() for r in righe
            if f"p:{me}" in dq.ruoli_in_carico(r, info.get(r.get("id")))}


# ── Cambio ─────────────────────────────────────────────────────────────────


def imposta(anomalia_id: int, ruolo: str, nuova: dict | None, *, chi: str, nota: str = ""):
    """Affida ``ruolo`` a ``nuova`` (``{"id", "nome"}``) o, con ``None``, lo riporta
    alla regola di serie. Ritorna ``(prima, dopo)`` come dict o ``None``."""
    from .quality_models import AnomaliaIncaricato

    attuale = AnomaliaIncaricato.objects.filter(anomalia_id=int(anomalia_id), ruolo=ruolo).first()
    prima = _voce(attuale) if attuale is not None else None
    if nuova is None:
        if attuale is not None:
            attuale.delete()
        return prima, None
    x, _ = AnomaliaIncaricato.objects.update_or_create(
        anomalia_id=int(anomalia_id), ruolo=ruolo,
        defaults={"legacy_user_id": int(nuova["id"]), "nome": str(nuova["nome"] or "")[:200],
                  "assegnato_da": str(chi or "")[:200], "nota": str(nota or "")[:500]},
    )
    return prima, _voce(x)


def togli_anomalia(anomalia_id: int) -> None:
    from .quality_models import AnomaliaIncaricato

    AnomaliaIncaricato.objects.filter(anomalia_id=int(anomalia_id)).delete()


def nome_di_serie(ruolo: str, row: dict, info: dict | None) -> str:
    """Chi ha il ruolo senza incaricato (per il registro: «prima» e «dopo»)."""
    from .views import _capo_car_di_op

    if ruolo == "cc":
        return _capo_car_di_op(str(row.get("ex_op_nominativo") or "").strip())[0] or "capocommessa dell'OP"
    if ruolo == "qualita":
        return "referenti RDC"
    if ruolo == "car":
        return ", ".join((info or {}).get("car_assegnati") or []) or "CAR segnalati"
    if ruolo == "car_op":
        return _capo_car_di_op(str(row.get("ex_op_nominativo") or "").strip())[1] or "CAR dell'OP"
    if ruolo.startswith("p:"):
        from .regole_carico import nomi_persone

        return nomi_persone().get(ruolo[2:]) or "persona indicata"
    try:
        from .automazioni_service import contatto_operatore

        return contatto_operatore(row.get("created_by_user_id"))[1] or "chi l'ha inserita"
    except Exception:
        return "chi l'ha inserita"


def avvisa(*, anomalia_id: int, op_id: str, ruolo: str, persona_id: int, chi: str, nota: str = "",
           seriale: str = "", descrizione: str = "") -> dict:
    """Notifica in-app e mail al nuovo incaricato. Mai bloccante."""
    from core.models import Notifica

    from .automazioni_service import _render_mail, _send, contatto_operatore, op_portal_link, op_url
    from .codice import codice_anomalia

    esito = {"mail": False, "email": ""}
    codice = codice_anomalia(anomalia_id) or "—"
    try:
        Notifica.objects.create(
            legacy_user_id=int(persona_id), tipo="anomalia_da_gestire",
            messaggio=f"OP {op_id}: {chi} ti ha affidato l'anomalia {codice}."[:500],
            url_azione=op_url(op_id),
        )
    except Exception:
        logger.warning("incaricato: notifica non creata id=%s", anomalia_id, exc_info=True)
    email, nome = contatto_operatore(persona_id)
    esito["email"] = email
    if not email:
        return esito
    link = op_portal_link(op_id)
    subject = f"[Novicrom Hub] OP {op_id} — {codice} affidata a te"
    lines = [f"{chi} ti ha affidato l'anomalia {codice} dell'OP {op_id}: ora è in carico a te.", "",
             f"  • S/N {seriale or '—'} · {(descrizione or '—')[:160]}"]
    if nota:
        lines.append(f"  Nota: {nota[:300]}")
    if link:
        lines += ["", f"Gestione anomalie: {link}"]
    html = _render_mail(
        badge="Anomalia affidata a te", eyebrow=f"OP {op_id}", title=f"{codice} ora è in carico a te",
        intro=f"{'Buongiorno ' + nome + ', ' if nome else ''}{chi} ti ha affidato questa anomalia: ora è in carico a te.",
        columns=["ID", "S/N", "Anomalia", "Nota"], rows=[[codice, seriale or "—", (descrizione or "—")[:160], nota or "—"]],
        cta_url=link, cta_label="Apri in Gestione anomalie",
    )
    esito["mail"] = bool(_send(kind="anomalia_incaricato", subject=subject, lines=lines, html=html, to=[email],
                               op_id=op_id, context={"anomalia_id": anomalia_id, "ruolo": ruolo, "da": chi}))
    return esito
