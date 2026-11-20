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


def _spostamenti(request) -> list[dict]:
    """KICK-OFF: richieste di spostamento date da decidere, dove l'utente ha pieni poteri
    (stesso elenco di «Le mie azioni»)."""
    from tasks.access import scoped_projects_queryset
    from tasks.services.spostamenti import richieste_da_decidere

    out = []
    for sp in richieste_da_decidere(request, scoped_projects_queryset(request).values("id"))[:MAX_PER_FONTE]:
        chi = (sp.richiesto_da.get_full_name() or sp.richiesto_da.get_username()) if sp.richiesto_da else ""
        nuove = " → ".join(f"{d:%d/%m/%Y}" for d in (sp.inizio_nuovo, sp.fine_nuovo) if d)
        out.append({
            "code": "Spostamento",
            "title": _meta(sp.task.title, getattr(sp.task.project, "name", "")),
            "meta": _meta(f"chiesto da {chi}" if chi else "", f"nuove date {nuove}" if nuove else "", sp.motivo[:80]),
            "status": "Da decidere",
            "due": None,
            "url": _url("tasks:mie_azioni"),
        })
    return out


def _segnalazioni_modifica(request) -> list[dict]:
    """CN-SGI: segnalazioni di modifica dei documenti ancora da chiudere, per chi le gestisce
    (stessi destinatari dell'avviso) e può aprire l'elenco. Quelle prese in carico da un altro
    restano a lui."""
    from procedure_refresh.models import ChangeRequestStatus, ProcedureChangeRequest
    from procedure_refresh.segnalazioni import destinatari_gestori
    from procedure_refresh.views import _can_manage

    mio_id = getattr(getattr(request, "legacy_user", None), "id", None)
    if not mio_id or int(mio_id) not in destinatari_gestori() or not _can_manage(request):
        return []
    qs = (
        ProcedureChangeRequest.objects
        .filter(Q(status=ChangeRequestStatus.APERTA)
                | Q(status=ChangeRequestStatus.IN_CARICO, gestita_da=request.user)
                | Q(status=ChangeRequestStatus.IN_CARICO, gestita_da__isnull=True))
        .select_related("document", "created_by")
        .order_by("created_at", "id")[:MAX_PER_FONTE]
    )
    base = _url("procedure_refresh:change_request_list")
    out = []
    for cr in qs:
        chi = (cr.created_by.get_full_name() or cr.created_by.get_username()) if cr.created_by else ""
        out.append({
            "code": str(getattr(cr.document, "code", "") or "Segnalazione"),
            "title": (cr.testo or "Segnalazione di modifica")[:140],
            "meta": _meta("segnalazione di modifica", f"da {chi}" if chi else ""),
            "status": cr.get_status_display(),
            "due": None,
            "url": f"{base}?doc={cr.document_id}",
        })
    return out


GIORNI_INCIDENTI = 365


def _incidenti(request) -> list[dict]:
    """Sicurezza: rilevazioni dell'ultimo anno che aspettano l'approvazione RLS o la chiusura
    RSPP, per chi può approvare e chiudere. Legge l'archivio del portale: con la lista
    SharePoint configurata il dato sta lì e qui non compare (niente chiamate esterne)."""
    from datetime import timedelta

    from rilevazione_incidenti.models import RilevazioneIncidente
    from rilevazione_incidenti.views import _can_manage_rspp, _get_impostazioni, _use_local

    if not _can_manage_rspp(request) or not _use_local(_get_impostazioni()):
        return []
    da = timezone.now() - timedelta(days=GIORNI_INCIDENTI)
    qs = (RilevazioneIncidente.objects.filter(chiusura_rspp=False, data_segnalazione__gte=da)
          .order_by("-data_segnalazione", "-id")[:MAX_PER_FONTE])
    out = []
    for r in qs:
        rls = (r.approvazione_rls or "").strip().lower()
        giorno = _data(r.data_segnalazione)
        out.append({
            "code": f"SIC-{r.pk}",
            "title": _meta(r.get_tipo_evento_display() or r.tipologia_scheda, r.reparto),
            "meta": _meta(f"del {giorno:%d/%m/%Y}" if giorno else "", (r.descrizione_avvenimento or "")[:80]),
            "status": "Da chiudere (RSPP)" if rls in ("approvato", "non approvato") else "In attesa RLS",
            "due": None,
            "url": _url("rilevazione_incidenti:dettaglio", str(r.pk)),
        })
    return out


def approvazioni(request) -> list[dict]:
    """Decisioni che spettano all'utente: modifiche SGI, approvazioni dei flussi, richieste di visita."""
    if not getattr(request.user, "is_authenticated", False):
        return []
    return (_sicura("modifiche SGI", _modifiche_sgi, request)
            + _sicura("approvazioni automazioni", _approvazioni_automazioni, request)
            + _sicura("richieste di visita", _richieste_visita, request)
            + _sicura("spostamenti KICK-OFF", _spostamenti, request)
            + _sicura("segnalazioni di modifica", _segnalazioni_modifica, request)
            + _sicura("rilevazioni di sicurezza", _incidenti, request))


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
            "status": s.stato_label,
            "due": due,
            "url": _url("suggestion_corner:dettaglio", s.pk),
        })
    return out


def _suggestion_team(user) -> list[dict]:
    """Suggestion Corner: segnalazioni che aspettano il team SMS (da classificare o pianificare).
    Solo i membri del gruppo: un superuser fuori dal team non le riceve fra le sue."""
    from suggestion_corner.models import SuggestionCorner, SuggestionCornerConfig

    if not user.groups.filter(name=SuggestionCornerConfig.load().sms_team_group_name).exists():
        return []
    S = SuggestionCorner.Stato
    qs = SuggestionCorner.objects.filter(stato__in=(S.INSERITA, S.DA_CLASSIFICARE, S.CLASSIFICATA)).order_by("id")[:MAX_PER_FONTE]
    return [{
        "code": f"SC#{sc.pk}",
        "title": (sc.opportunity or str(sc))[:140],
        "meta": "team SMS",
        "status": sc.stato_label,
        "due": None,
        "url": _url("suggestion_corner:dettaglio", sc.pk),
    } for sc in qs]


def _sds(user) -> list[dict]:
    """Schede di sicurezza dovute per la mansione e non ancora prese in visione."""
    from schede_sicurezza.services.assegnazioni import profilo_sds_utente

    url = _url("schede_sicurezza:sds_da_leggere")
    return [{
        "code": "SDS",
        "title": str(getattr(scheda.prodotto, "nome", "") or "Scheda di sicurezza"),
        "meta": "scheda di sicurezza da leggere",
        "status": "Da leggere",
        "due": None,
        "url": url,
    } for scheda in profilo_sds_utente(user).da_leggere[:MAX_PER_FONTE]]


GIORNI_MANUTENZIONI = 30


def _manutenzioni(user) -> list[dict]:
    """Manutenzioni programmate aperte dell'utente (assegnatario del piano sull'asset, o
    manutentore predefinito del piano), scadute o in scadenza entro 30 giorni e non ancora
    dentro un ordine di lavoro (quelle compaiono già fra gli OdL)."""
    from datetime import timedelta

    from assets.models import MaintenanceOccurrence

    mie = (Q(assignment__assigned_to=user)
           | Q(assignment__assigned_to__isnull=True, plan__default_assignee=user)
           | Q(assignment__isnull=True, plan__default_assignee=user))
    from assets.services.deadline_feed import exclude_mirror_occurrences
    from assets.services.maintenance_domain import q_aperte_non_piu_dovute

    # Stesse esclusioni di Da fare: niente copie delle scadenze amministrative (arrivano
    # dalla loro fonte), niente asset dismessi o piani spenti.
    qs = (
        exclude_mirror_occurrences(MaintenanceOccurrence.objects.filter(
            mie, status=MaintenanceOccurrence.STATUS_OPEN, work_order__isnull=True,
            due_date__lte=timezone.localdate() + timedelta(days=GIORNI_MANUTENZIONI),
        ))
        .exclude(q_aperte_non_piu_dovute())
        .select_related("plan", "asset").order_by("due_date", "id")[:MAX_PER_FONTE]
    )
    return [{
        "code": str(getattr(o.asset, "asset_tag", "") or "Manutenzione"),
        "title": str(getattr(o.plan, "label", "") or o.plan),
        "meta": _meta("manutenzione programmata", getattr(o.asset, "name", ""), _entro(o.due_date)),
        "status": "Da eseguire",
        "due": o.due_date,
        "url": _url("assets:occurrence_worksheet", o.pk),
    } for o in qs]


def _onboarding(request) -> list[dict]:
    """Inserimenti in corso: una riga per pratica con le voci ancora da fare. Le voci IT vanno
    ai destinatari dell'avviso IT, le altre a chi gestisce le pratiche (permesso HR)."""
    from anagrafica.models import OnboardingPratica, OnboardingTask
    from anagrafica.services.avviso_it_ingresso import configurazione
    from anagrafica.views._helpers import _check_hr_permission

    hr = bool(_check_hr_permission(request))
    cfg = configurazione()
    mio_id = getattr(getattr(request, "legacy_user", None), "id", None)
    it = _email(request.user) in {str(e).strip().lower() for e in cfg["emails"]} or (
        bool(mio_id) and int(mio_id) in cfg["utenti_ids"])
    if not hr and not it:
        return []
    voci = OnboardingTask.objects.filter(
        stato=OnboardingTask.STATO_DA_FARE, pratica__stato__in=OnboardingPratica.STATI_APERTI)
    if not hr:
        voci = voci.filter(categoria=OnboardingTask.CATEGORIA_IT)
    elif not it:
        voci = voci.exclude(categoria=OnboardingTask.CATEGORIA_IT)
    per_pratica: dict[int, dict] = {}
    oggi = timezone.localdate()
    for t in voci.select_related("pratica").order_by("pratica_id", "ordine", "id"):
        riga = per_pratica.setdefault(t.pratica_id, {"pratica": t.pratica, "n": 0, "ritardo": 0, "prima": None})
        riga["n"] += 1
        if t.scadenza:
            riga["ritardo"] += t.scadenza < oggi
            riga["prima"] = min(riga["prima"], t.scadenza) if riga["prima"] else t.scadenza
    out = []
    for riga in list(per_pratica.values())[:MAX_PER_FONTE]:
        pr = riga["pratica"]
        n, ritardo = riga["n"], riga["ritardo"]
        out.append({
            "code": "Ingresso",
            "title": pr.dipendente_nome or f"Pratica {pr.pk}",
            "meta": _meta(
                "onboarding", pr.reparto,
                f"ingresso il {pr.data_assunzione:%d/%m/%Y}" if pr.data_assunzione else "",
                "" if hr else "la pratica si apre con il permesso HR",
            ),
            "status": f"{n} voc{'e' if n == 1 else 'i'} da fare" + (f", {ritardo} in ritardo" if ritardo else ""),
            "due": riga["prima"],
            "url": _url("anagrafica:onboarding_detail", pr.pk) if hr else "#",
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
    return (_sicura("schede di sicurezza", _sds, user)
            + _sicura("manutenzioni programmate", _manutenzioni, user)
            + _sicura("onboarding", _onboarding, request)
            + _sicura("specifiche", _specifiche, user)
            + _sicura("registro OFI", _ofi, user)
            + _sicura("CAR", _car, user)
            + _sicura("obiettivi riesame", _obiettivi, user)
            + _sicura("Suggestion Corner", _suggestion, user)
            + _sicura("Suggestion Corner team", _suggestion_team, user)
            + _sicura("attrezzature", _attrezzature, user)
            + _sicura("checklist chiusure", _checklist, request))


# ---------------------------------------------------------------------------
# Ticket del proprio team ancora senza un assegnatario
# ---------------------------------------------------------------------------

def ticket_team_da_assegnare(request) -> dict:
    """Ticket aperti che nessuno ha preso, dei tipi in cui l'utente è nel team dei gestori
    (Impostazioni ticket) e può gestire. {"items": [...], "total": n}."""
    vuoto = {"items": [], "total": 0}
    try:
        from tickets.models import StatoTicket, Ticket, TicketImpostazioni
        from tickets.views import _can_manage_tickets, _user_acl_identities

        mie = set(_user_acl_identities(request)) | {_email(request.user)}
        mie.discard("")
        tipi = [
            cfg.tipo for cfg in TicketImpostazioni.objects.all()
            if any(
                str(g.get("email", "")).strip().lower() in mie
                for g in (cfg.team_gestori or []) if isinstance(g, dict)
            ) and _can_manage_tickets(request, cfg.tipo)
        ]
        if not tipi:
            return vuoto
        qs = Ticket.objects.filter(tipo__in=tipi, stato=StatoTicket.APERTA, assegnato_a="", delegato_fornitore__isnull=True)
        total = qs.count()
        righe = list(qs.order_by("created_at", "id")[:MAX_PER_FONTE]) if total else []
    except Exception:
        logger.exception("Le mie attività: ticket del team non calcolabili")
        return vuoto
    return {"total": total, "items": [{
        "code": t.numero_ticket or f"T-{t.pk}",
        "title": t.titolo or "Ticket",
        "meta": "nessuno lo ha preso in carico",
        "status": "Da assegnare",
        "priority": getattr(t, "priorita", "") or "",
        "due": None,
        "url": _url("tickets:gestione_detail", t.pk),
    } for t in righe]}
