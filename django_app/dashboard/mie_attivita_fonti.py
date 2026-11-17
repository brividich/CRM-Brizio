"""
dashboard/mie_attivita_fonti.py
===============================
Fonti di «Le mie attività» che prima mancavano: approvazioni e voci assegnate nei moduli
che non avevano una sezione propria (e comparivano solo se in scadenza a breve, o mai
quando non hanno una data).

Ogni fonte è isolata: un modulo assente o rotto non toglie le altre voci. Ogni voce ha la
stessa forma delle altre sezioni (code, title, meta, status, due, url).
"""

from __future__ import annotations

import logging
from datetime import date, datetime

from django.db.models import Q
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

logger = logging.getLogger(__name__)

MAX_PER_FONTE = 30


def _url(nome: str, *args) -> str:
    try:
        return reverse(nome, args=args) if args else reverse(nome)
    except NoReverseMatch:
        return "#"


def _data(valore) -> date | None:
    if isinstance(valore, datetime):
        return timezone.localtime(valore).date() if timezone.is_aware(valore) else valore.date()
    return valore or None


def _meta(*parti) -> str:
    return " · ".join(str(p) for p in parti if p) or "—"


def _entro(d) -> str:
    return f"entro il {d:%d/%m/%Y}" if d else ""


def _email(user) -> str:
    return str(getattr(user, "email", "") or "").strip().lower()


def _sicura(nome: str, funzione, *args) -> list[dict]:
    try:
        return funzione(*args)
    except Exception:
        logger.exception("Le mie attività: fonte «%s» non calcolabile", nome)
        return []


# ---------------------------------------------------------------------------
# Approvazioni e richieste che aspettano una decisione
# ---------------------------------------------------------------------------

def _modifiche_sgi(request) -> list[dict]:
    from procedure_refresh.modifiche import da_fare

    try:
        from procedure_refresh.views import _can_manage

        gestore = bool(_can_manage(request))
    except Exception:
        gestore = False
    out = []
    for r in da_fare(request.user, gestore)[:MAX_PER_FONTE]:
        m = r.m
        out.append({
            "code": "Modifica SGI",
            "title": str(m),
            "meta": _meta(f"tocca a te come {r.ruolo_label.lower()}" if r.ruolo_label else "", _entro(m.entro)),
            "status": m.get_stato_display(),
            "due": m.entro,
            "url": _url("procedure_refresh:modifica_dettaglio", m.pk),
        })
    return out


def _approvazioni_automazioni(request) -> list[dict]:
    from automazioni.approval_security import normalize_actor_email
    from automazioni.models import AutomationApproval

    me = normalize_actor_email(getattr(request.user, "email", "") or getattr(request.user, "username", ""))
    if not me:
        return []
    adesso = timezone.now()
    qs = (AutomationApproval.objects.filter(status=AutomationApproval.Status.PENDING)
          .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=adesso))
          .only("id", "token", "subject", "approver_emails", "expires_at", "created_at")
          .order_by("created_at")[:500])
    out = []
    for a in qs:
        # approver_emails è una lista JSON: il filtro «contains» non è portabile su SQL Server.
        if me not in {normalize_actor_email(e) for e in (a.approver_emails or [])}:
            continue
        scade = _data(a.expires_at)
        out.append({
            "code": "Approvazione",
            "title": a.subject or "Richiesta di approvazione",
            "meta": _meta(f"dal {_data(a.created_at):%d/%m/%Y}" if a.created_at else "", f"scade il {scade:%d/%m/%Y}" if scade else ""),
            "status": "Da decidere",
            "due": scade,
            "url": _url("automazioni_approval_status", a.token),
        })
        if len(out) >= MAX_PER_FONTE:
            break
    return out


def _richieste_visita(request) -> list[dict]:
    from django.apps import apps

    if not apps.is_installed("reception"):
        return []
    from reception.models import RichiestaAppuntamento

    email = _email(request.user)
    if "@" not in email:
        return []
    qs = (RichiestaAppuntamento.objects.filter(referente__email__iexact=email, stato=RichiestaAppuntamento.IN_ATTESA)
          .order_by("data_visita", "ora_inizio")[:MAX_PER_FONTE])
    return [{
        "code": "Visita",
        "title": _meta(f"{r.nome} {r.cognome}".strip(), r.azienda),
        "meta": _meta(f"{r.data_visita:%d/%m/%Y}" + (f" {r.ora_inizio:%H:%M}" if r.ora_inizio else ""), r.motivo),
        "status": "Da decidere",
        "due": r.data_visita,
        "url": _url("reception:annuncia"),
    } for r in qs]


def approvazioni(request) -> list[dict]:
    """Decisioni che spettano all'utente: modifiche SGI, approvazioni dei flussi, richieste di visita."""
    if not getattr(request.user, "is_authenticated", False):
        return []
    return (_sicura("modifiche SGI", _modifiche_sgi, request)
            + _sicura("approvazioni automazioni", _approvazioni_automazioni, request)
            + _sicura("richieste di visita", _richieste_visita, request))


# ---------------------------------------------------------------------------
# Voci assegnate nei moduli senza sezione propria
# ---------------------------------------------------------------------------

def _specifiche(user) -> list[dict]:
    from gestione_specifiche import constants as C
    from gestione_specifiche.models import MOD133, Specifica

    out = []
    compilare = (MOD133.objects.filter(compilatore=user, data_chiusura_compilazione__isnull=True,
                                       specifica__stato=C.STATO_FLOW_DOWN).select_related("specifica")[:MAX_PER_FONTE])
    gia = set()
    for m in compilare:
        s = m.specifica
        gia.add(s.pk)
        out.append({"code": "MOD.133", "title": f"{s.codice} · {s.titolo}", "meta": _meta(s.cliente, "da compilare"),
                    "status": s.get_stato_display(), "url": _url("gestione_specifiche:dettaglio", s.pk)})
    for s in Specifica.objects.filter(incaricato=user, stato__in=(C.STATO_BOZZA, C.STATO_FLOW_DOWN)).order_by("-id")[:MAX_PER_FONTE]:
        if s.pk in gia:
            continue
        out.append({"code": "Specifica", "title": f"{s.codice} · {s.titolo}", "meta": _meta(s.cliente, "da prendere in carico"),
                    "status": s.get_stato_display(), "url": _url("gestione_specifiche:dettaglio", s.pk)})
    return out


def _ofi(user) -> list[dict]:
    from gestione_specifiche.models import RegistroOFI

    # Con una CAR aperta a nome mio la voce compare già come CAR.
    qs = (RegistroOFI.objects.filter(RegistroOFI.q_aperte(), responsabile=user)
          .exclude(car_procedurale__chiusa_il__isnull=True, car_procedurale__responsabile=user)
          .order_by("-numero")[:MAX_PER_FONTE])
    return [{
        "code": str(o),
        "title": (o.opportunita or o.processo or str(o))[:140],
        "meta": _meta(o.get_tipo_display(), o.processo, _entro(o.data_richiesta)),
        "status": o.get_fase_display(),
        "due": o.data_richiesta,
        "url": _url("registro_ofi:dettaglio", o.pk),
    } for o in qs]


def _car(user) -> list[dict]:
    from sistema_gestione.models import AzioneCorrettivaAudit

    out = []
    for c in (AzioneCorrettivaAudit.objects.filter(responsabile=user, chiusa_il__isnull=True)
              .select_related("registro").order_by("data_richiesta")[:MAX_PER_FONTE]):
        analisi = c.analizzata_il is None
        due = c.scadenza_analisi if analisi else c.scadenza_chiusura
        out.append({
            "code": "CAR",
            "title": f"{c.registro}" + (f" · {c.registro.opportunita[:100]}" if c.registro.opportunita else ""),
            "meta": _meta("analisi da fare" if analisi else "da chiudere", _entro(due)),
            "status": "Analisi" if analisi else "In corso",
            "due": due,
            "url": _url("sistema_gestione:procedura_car", c.registro_id),
        })
    return out


def _obiettivi(user) -> list[dict]:
    from sistema_gestione.services.riesame import obiettivi_aperti

    return [{
        "code": "Obiettivo",
        "title": str(o),
        "meta": _meta("Riesame della direzione", _entro(o.scadenza)),
        "status": o.get_stato_display(),
        "due": o.scadenza,
        "url": _url("sistema_gestione:riesame_dettaglio", o.riesame_id),
    } for o in obiettivi_aperti().filter(responsabile=user).order_by("scadenza")[:MAX_PER_FONTE]]


def _suggestion(user) -> list[dict]:
    from suggestion_corner.models import SuggestionCorner

    S = SuggestionCorner.Stato
    qs = SuggestionCorner.objects.filter(
        Q(incaricato=user, stato__in=(S.PLAN_DEFINITO, S.DO_IN_CORSO)) | Q(controllore=user, stato=S.CHECK_IN_CORSO)
    ).order_by("id")[:MAX_PER_FONTE]
    out = []
    for s in qs:
        controllo = s.controllore_id == user.pk and s.stato == S.CHECK_IN_CORSO
        due = s.data_limite_controllo if controllo else s.data_limite_esecuzione
        out.append({
            "code": f"SC#{s.pk}",
            "title": (s.opportunity or str(s))[:140],
            "meta": _meta("controllo" if controllo else "esecuzione", _entro(due)),
            "status": s.get_stato_display(),
            "due": due,
            "url": _url("suggestion_corner:dettaglio", s.pk),
        })
    return out


def _attrezzature(user) -> list[dict]:
    from attrezzature.models import AttrezzaturaTask

    qs = (AttrezzaturaTask.objects.filter(assegnato_a=user, stato__in=("aperta", "in_lavorazione", "bloccata"))
          .select_related("attrezzatura").order_by("scadenza", "id")[:MAX_PER_FONTE])
    return [{
        "code": "Attrezzatura",
        "title": t.titolo,
        "meta": _meta(str(t.attrezzatura) if t.attrezzatura_id else t.codice_attrezzo, _entro(t.scadenza)),
        "status": t.get_stato_display(),
        "due": t.scadenza,
        "url": _url("attrezzature:task_detail", t.pk),
    } for t in qs]


def _checklist(request) -> list[dict]:
    from checklist_operativa.services import dipendente_di, voci_da_confermare

    return [{
        "code": "Checklist",
        "title": v.descrizione[:140],
        "meta": _meta(v.evento.nome, f"dal {v.evento.data_inizio:%d/%m/%Y}"),
        "status": "Da confermare",
        "due": v.evento.data_inizio,
        "url": _url("checklist_operativa:gestione") + f"?evento={v.evento_id}",
    } for v in voci_da_confermare(dipendente_di(request)).order_by("evento__data_inizio", "ordine")[:MAX_PER_FONTE]]


def assegnate(request) -> list[dict]:
    """Voci assegnate all'utente nei moduli senza sezione propria, con o senza scadenza."""
    user = request.user
    if not getattr(user, "is_authenticated", False):
        return []
    return (_sicura("specifiche", _specifiche, user)
            + _sicura("registro OFI", _ofi, user)
            + _sicura("CAR", _car, user)
            + _sicura("obiettivi riesame", _obiettivi, user)
            + _sicura("Suggestion Corner", _suggestion, user)
            + _sicura("attrezzature", _attrezzature, user)
            + _sicura("checklist chiusure", _checklist, request))
