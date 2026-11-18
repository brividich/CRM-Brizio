"""
dashboard/views_mie_attivita.py
===============================
"Le mie attività" — cockpit operativo personale di NOVICROM HUB.

Pagina focalizzata (distinta dalla home launcher) che aggrega in un solo posto
le cose che l'utente loggato deve gestire/seguire, attraversando i moduli:
anomalie aperte, ticket correlati aperti, approvazioni assenze da evadere,
richieste DPI in corso.

Riusa gli helper già provati in dashboard/views.py (stessa app, no circular import)
per non duplicare la logica di visibilità/ACL. Ogni sezione è difensiva: un errore
in un modulo non rompe l'intera pagina.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from django.contrib.auth.decorators import login_required
from django.db.models import F, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import NoReverseMatch, reverse
from django.utils import timezone

from core.legacy_utils import get_legacy_user, is_legacy_admin

logger = __import__("logging").getLogger(__name__)
from dashboard.views import (
    _board_data_anomalie,
    _board_data_assenze_da_approvare,
    _board_related_tickets_queryset,
)
from core import naming


GIORNI_SCADENZE = 30
# Voci personali (letture e corsi): si mostrano tutte, così il numero della sezione è quello vero.
MAX_PROCEDURE = 100
MAX_ELEARNING = 100


def _safe_url(name: str, *args) -> str:
    try:
        return reverse(name, args=args) if args else reverse(name)
    except NoReverseMatch:
        return "#"


def _my_anomalie(legacy_user, is_admin: bool) -> list[dict]:
    try:
        raw = _board_data_anomalie(legacy_user, is_admin, {"max_items": 12, "solo_aperte": True})
    except Exception:
        return []
    url = _safe_url("gestione_anomalie_page")
    out = []
    for a in raw:
        out.append({
            "code": f"A-{a.get('id')}",
            "title": a.get("seriale") or a.get("ex_op_nominativo") or "Anomalia",
            "meta": a.get("operatore") or "—",
            "status": a.get("avanzamento") or "Aperta",
            "url": url,
        })
    return out


def _my_nc(request, legacy_user) -> list[dict]:
    """Non conformita': azioni assegnate all'utente + NC aperte dei suoi OP (CC/CAR)."""
    try:
        from anomalie.nc_views import _mie
        from anomalie.quality_models import AnomaliaNC, AnomaliaNCAzione
    except Exception:
        return []
    out: list[dict] = []
    try:
        viste: set[int] = set()
        if legacy_user:
            azioni = (AnomaliaNCAzione.objects.select_related("nc")
                      .filter(responsabile_legacy_id=legacy_user.id,
                              stato__in=[AnomaliaNCAzione.Stato.DA_FARE, AnomaliaNCAzione.Stato.IN_CORSO])
                      .exclude(nc__stato=AnomaliaNC.Stato.CHIUSA).order_by("scadenza", "id")[:12])
            for a in azioni:
                out.append({
                    "code": a.nc.protocollo,
                    "title": a.descrizione[:120],
                    "meta": f"Azione · OP {a.nc.op_titolo}" + (f" · scade {a.scadenza:%d/%m/%Y}" if a.scadenza else ""),
                    "status": a.get_stato_display(),
                    "due": a.scadenza,
                    "url": _safe_url("anomalie_nc_dettaglio", a.nc_id) + "#azioni",
                })
                viste.add(a.nc_id)
        aperte = (AnomaliaNC.objects.exclude(stato=AnomaliaNC.Stato.CHIUSA)
                  .prefetch_related("azioni").order_by("-id")[:200])
        for nc in aperte:
            if len(out) >= 12:
                break
            if nc.pk in viste or not _mie(request, nc):
                continue
            out.append({
                "code": nc.protocollo,
                "title": f"OP {nc.op_titolo}",
                "meta": nc.part_number or "Non conformità",
                "status": nc.get_stato_display(),
                "url": _safe_url("anomalie_nc_dettaglio", nc.pk),
            })
    except Exception:
        return out
    return out


def _my_kickoff(request) -> dict:
    """Attività, azioni, problemi, programmi e FAI del KICK-OFF assegnati all'utente."""
    try:
        from tasks.services.da_fare import voci_kickoff

        return voci_kickoff(request)
    except Exception:
        logger.exception("Voci KICK-OFF non calcolabili")
        return {"items": [], "total": 0, "overdue": 0, "soon": 0}


def _my_tickets(request_user, legacy_user, legacy_user_id) -> list[dict]:
    try:
        from tickets.models import StatoTicket, Ticket  # noqa: F401

        open_states = (StatoTicket.APERTA, StatoTicket.IN_CARICO, StatoTicket.IN_ATTESA)
        qs = (
            _board_related_tickets_queryset(request_user, legacy_user, legacy_user_id)
            .filter(stato__in=open_states)
            .order_by("-created_at", "-id")[:15]
        )
    except Exception:
        return []
    out = []
    for t in qs:
        try:
            status_label = t.get_stato_display()
        except Exception:
            status_label = getattr(t, "stato", "") or "Aperto"
        out.append({
            "code": t.numero_ticket or f"T-{t.pk}",
            "title": t.titolo or "Ticket",
            "meta": (getattr(t, "asset_descrizione_libera", "") or getattr(t, "categoria", "") or "—"),
            "status": status_label,
            "priority": getattr(t, "priorita", "") or "",
            "url": _safe_url("tickets:detail", t.pk),
        })
    return out


def _my_tickets_totale(request_user, legacy_user, legacy_user_id) -> int:
    """Tutti i ticket aperti correlati, non solo i 15 mostrati."""
    try:
        from tickets.models import StatoTicket

        return _board_related_tickets_queryset(request_user, legacy_user, legacy_user_id).filter(
            stato__in=(StatoTicket.APERTA, StatoTicket.IN_CARICO, StatoTicket.IN_ATTESA)
        ).count()
    except Exception:
        return 0


def _my_workorders(request_user) -> dict:
    """Ordini di lavoro aperti assegnati all'utente (manutentore), i più urgenti in testa."""
    vuoto = {"items": [], "total": 0}
    if not getattr(request_user, "is_authenticated", False):
        return vuoto
    try:
        from assets.models import WorkOrder

        qs = WorkOrder.objects.filter(assigned_to=request_user, status=WorkOrder.STATUS_OPEN).select_related("asset")
        total = qs.count()
        if not total:
            return vuoto
        righe = list(qs.order_by(F("due_at").asc(nulls_last=True), "-id")[:15])
    except Exception:
        logger.exception("Ordini di lavoro non calcolabili")
        return vuoto
    out = []
    for wo in righe:
        due = timezone.localtime(wo.due_at).date() if wo.due_at else None
        asset = getattr(wo, "asset", None)
        out.append({
            "code": f"OdL {wo.pk}",
            "title": wo.title or wo.get_kind_display(),
            "meta": " · ".join(x for x in (
                str(getattr(asset, "asset_tag", "") or ""), str(getattr(asset, "name", "") or ""),
                f"entro il {due:%d/%m/%Y}" if due else "",
            ) if x) or "—",
            "status": wo.get_priority_display() if wo.priority else wo.get_status_display(),
            "due": due,
            "url": _safe_url("assets:wo_view", wo.pk),
        })
    return {"items": out, "total": total}


def _my_approvals(legacy_user, is_admin: bool) -> list[dict]:
    """Assenze che aspettano l'utente come capo. Un amministratore vede le sue, non quelle di
    tutta l'azienda; l'ufficio Amministrazione (che le gestisce tutte) le vede tutte."""
    if not legacy_user:
        return []
    try:
        if str(getattr(legacy_user, "ruolo", "") or "").strip().upper() == "AMMINISTRAZIONE":
            raw = _board_data_assenze_da_approvare(legacy_user, True, {"max_items": 12})
        else:
            from assenze.views import _load_pending_for_manager

            # Stessa identità della pagina Assenze: id, nome ed email del capo.
            raw = _load_pending_for_manager(
                int(legacy_user.id), limit=12,
                manager_name=str(getattr(legacy_user, "nome", "") or ""),
                manager_email=str(getattr(legacy_user, "email", "") or ""),
            )
    except Exception:
        return []
    url = _safe_url("assenze_gestione")
    out = []
    for a in raw:
        out.append({
            "title": f"{a.get('tipo', 'Assenza')}",
            "meta": a.get("dipendente", "") or "—",
            "status": " → ".join(x for x in (a.get("inizio_label") or "", a.get("fine_label") or "") if x),
            "url": url,
        })
    return out


def _assenze_squadra(legacy_user, is_admin: bool) -> dict:
    """Sezione «Assenze della squadra»: le richieste da accettare e, sotto, quelle già
    accettate e non ancora finite. ``informative`` = righe accettate (non sono cose da fare)."""
    da_fare = _my_approvals(legacy_user, is_admin)
    vuoto = {"items": da_fare, "total": len(da_fare), "informative": 0, "nota": ""}
    if not legacy_user:
        return vuoto
    try:
        from assenze.views._helpers import riepilogo_per_capo

        r = riepilogo_per_capo(
            int(legacy_user.id),
            manager_name=str(getattr(legacy_user, "nome", "") or ""),
            manager_email=str(getattr(legacy_user, "email", "") or ""),
            tutte=str(getattr(legacy_user, "ruolo", "") or "").strip().upper() == "AMMINISTRAZIONE",
        )
    except Exception:
        logger.exception("Riepilogo assenze della squadra non calcolabile")
        return vuoto
    url = _safe_url("assenze_gestione")
    accettate = [{
        "title": a.get("tipo") or "Assenza",
        "meta": " · ".join(x for x in (
            a.get("dipendente") or "",
            " → ".join(x for x in (a.get("inizio_label") or "", a.get("fine_label") or "") if x),
        ) if x) or "—",
        "status": "Accettata",
        "url": url,
    } for a in r["prossime"]]
    da_approvare = max(len(da_fare), r["da_approvare"])
    nota = ""
    if da_approvare or r["approvate"]:
        nota = f"{da_approvare} da accettare · {r['approvate']} accettat{'a' if r['approvate'] == 1 else 'e'} in corso o in arrivo"
    return {"items": da_fare + accettate, "total": da_approvare + len(accettate), "informative": len(accettate), "nota": nota}


def _anagrafica_id(request) -> int | None:
    """Id anagrafica del dipendente (``AnagraficaDipendente.id``): NON è l'id dell'utente legacy."""
    try:
        from core.operational_roles import get_legacy_anagrafica_id

        return get_legacy_anagrafica_id(request.user)
    except Exception:
        return None


def _my_dpi(request) -> dict:
    """Le richieste DPI dell'utente ancora in corso: fatte da lui o intestate alla sua anagrafica."""
    vuoto = {"items": [], "total": 0}
    if not getattr(request.user, "is_authenticated", False):
        return vuoto
    try:
        from dpi.models import RichiestaDPI, StatoRichiesta

        mie = Q(created_by=request.user)
        anagrafica_id = _anagrafica_id(request)
        if anagrafica_id:
            # Chi inserisce per un altro non la vede come sua; il dipendente intestatario sì.
            mie = Q(richiedente_legacy_id=anagrafica_id) | Q(created_by=request.user, richiedente_legacy_id__isnull=True)
        qs = RichiestaDPI.objects.filter(mie, stato__in=(StatoRichiesta.INVIATA, StatoRichiesta.APPROVATA))
        total = qs.count()
        righe = list(qs.select_related("categoria").order_by("-created_at")[:15]) if total else []
    except Exception:
        logger.exception("Richieste DPI in corso non calcolabili")
        return vuoto
    out = []
    for r in righe:
        if r.stato == StatoRichiesta.APPROVATA and r.pronta_ritiro_il:
            stato = "Pronto: passa a ritirarlo"
        else:
            stato = r.get_stato_display()
        out.append({
            "code": r.numero,
            "title": str(r.categoria or "Richiesta DPI"),
            "meta": f"Qtà {r.quantita or '—'}",
            "status": stato,
            "url": _safe_url("dpi:detail", r.pk),
        })
    return {"items": out, "total": total}


def _dpi_da_fare(request) -> list[dict]:
    """DPI che aspettano l'utente: da approvare, scarpe da ordinare, consegne da preparare."""
    try:
        from dpi.mie_attivita import voci_da_fare

        return voci_da_fare(request)
    except Exception:
        logger.exception("Le mie attività: DPI da gestire non calcolabili")
        return []


def _my_elearning(request) -> list[dict]:
    """Micro-corsi e-learning assegnati (obbligo) all'utente e non ancora completati."""
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if not legacy_user:
        return []
    try:
        from core.legacy_models import AnagraficaDipendente
        from anagrafica.models_formazione import TrainingAssignment

        ana = AnagraficaDipendente.objects.filter(utente_id=legacy_user.id).only("id").first()
        if not ana:
            return []
        qs = (
            TrainingAssignment.objects.filter(
                legacy_anagrafica_id=ana.id,
                corso__is_elearning=True, corso__is_active=True, corso__stato="ATTIVO",
            )
            .exclude(stato__in=("COMPLETATO", "ESONERATO"))
            .select_related("corso")
            .order_by("due_date")[:MAX_ELEARNING]
        )
    except Exception:
        return []
    out = []
    for a in qs:
        out.append({
            "code": a.corso.codice,
            "title": a.corso.titolo,
            "meta": ("Scadenza " + a.due_date.isoformat()) if a.due_date else "Da completare",
            "status": a.get_stato_display(),
            "due": a.due_date,
            "url": _safe_url("anagrafica:formazione_online_player", a.corso_id),
        })
    return out


def _my_procedure(request_user) -> list[dict]:
    """Procedure ancora da leggere/confermare assegnate all'utente corrente."""
    if not getattr(request_user, "is_authenticated", False):
        return []
    try:
        from procedure_refresh.models import AssignmentStatus, ProcedureAssignment

        da_leggere = (AssignmentStatus.ASSIGNED, AssignmentStatus.OPENED, AssignmentStatus.OVERDUE)
        qs = (
            ProcedureAssignment.objects.filter(user=request_user, status__in=da_leggere)
            .select_related("campaign", "revision")
            .order_by("due_date", "-assigned_at")[:MAX_PROCEDURE]
        )
    except Exception:
        return []
    url = _safe_url("procedure_refresh:my_assignments")
    out = []
    for a in qs:
        try:
            status_label = a.get_status_display()
        except Exception:
            status_label = getattr(a, "status", "") or ""
        out.append({
            "title": str(getattr(a.campaign, "name", "") or getattr(a.revision, "file_name", "") or "Procedura"),
            "meta": (a.due_date.strftime("%d-%m-%Y") if a.due_date else "—"),
            "status": status_label,
            "due": a.due_date,
            "url": url,
        })
    return out


def _safety_scadenze(request) -> list[dict] | None:
    """Qualifiche/abilitazioni scadute o in scadenza (≤60gg) da gestire.

    Vista **gestionale** (gated dal permesso formazione/HR): ritorna ``None`` se
    l'utente non ha il permesso (la sezione non viene mostrata). Query leggera; i
    nomi dipendente sono risolti solo per i pochi item mostrati. Le visite mediche
    (dato sanitario) sono escluse di proposito; il conteggio idoneità "non idonei"
    resta sul cruscotto Safety (calcolo batch più pesante).
    """
    try:
        from anagrafica.views import _can_view_formazione
        if not _can_view_formazione(request):
            return None
    except Exception:
        return None
    try:
        from datetime import timedelta
        from django.utils import timezone
        from anagrafica.models import DipendenteQualifica
        from core.legacy_anagrafica import fetch_anagrafica_rows

        oggi = timezone.localdate()
        soglia = oggi + timedelta(days=60)
        qs = list(
            DipendenteQualifica.objects.select_related("tipo")
            .filter(data_scadenza__isnull=False, data_scadenza__lte=soglia)
            .order_by("data_scadenza")[:10]
        )
        nomi: dict[int, str] = {}
        ids = list({q.legacy_anagrafica_id for q in qs})
        if ids:
            for r in fetch_anagrafica_rows(ids=ids):
                rid = int(r.get("id") or 0)
                if rid:
                    nomi[rid] = naming.nome_completo(r.get('nome'), r.get('cognome'))
        url = _safe_url("anagrafica:scadenzario") + "?tipo=qualifica"
        out = []
        for q in qs:
            scaduta = q.data_scadenza < oggi
            out.append({
                "code": f"Q-{q.id}",
                "title": q.tipo.nome,
                "meta": nomi.get(q.legacy_anagrafica_id, f"#{q.legacy_anagrafica_id}"),
                "status": "Scaduta" if scaduta else "In scadenza",
                "due": q.data_scadenza,
                "url": url,
            })
        return out
    except Exception:
        return []


def _my_skm_refresh(legacy_user_id) -> list[dict]:
    """Refresh abilitazioni macchina da gestire per il CAR (campagne aperte del suo reparto)."""
    if not legacy_user_id:
        return []
    try:
        from anagrafica.services.skillmatrix_refresh import campagne_da_gestire
        raw = campagne_da_gestire(legacy_user_id)
    except Exception:
        return []
    out = []
    for c in raw:
        out.append({
            "code": f"REP-{c['campagna_id']}",
            "title": f"Refresh reparto {c['reparto']}",
            "meta": f"{c['n_da_rivalutare']} abilitazioni da rivalutare",
            "status": "Da rivalutare",
            "url": c["url"],
        })
    return out


def _mie_scadenze(request: HttpRequest) -> list[dict]:
    """Scadute ed entro ``GIORNI_SCADENZE`` giorni che riguardano la persona, dalle fonti senza sezione propria, tranne l'HR
    (dati sanitari: vedi sotto). Il risultato resta in cache 5 minuti: la Home non deve
    interrogare ogni modulo a ogni apertura."""
    from django.core.cache import cache

    user_id = getattr(request.user, "id", None)
    if not user_id:
        return []
    chiave = f"scadenzario:mie:v3:{user_id}"
    salvate = cache.get(chiave)
    if salvate is not None:
        return salvate
    try:
        from dashboard.scadenze_providers import PROVIDERS, collect_all
        from dashboard.views_scadenze import _azioni
        from scadenzario.calendario import chiavi_persona_di, e_mia
        from scadenzario.fonti_moduli import SOURCE_ANOMALIE, SOURCE_LAVORO, SOURCE_PROCEDURE

        # Attività, azioni, NC e procedure hanno già la loro sezione: qui le stesse voci
        # verrebbero contate due volte nel totale.
        escluse = {"hr", SOURCE_LAVORO, SOURCE_ANOMALIE, SOURCE_PROCEDURE}
        # Con 7 giorni le voci assegnate più avanti non comparivano da nessuna parte.
        orizzonte = timezone.localdate() + timedelta(days=GIORNI_SCADENZE)
        voci = [v for v in collect_all(request, sources=set(PROVIDERS) - escluse, orizzonte=orizzonte)
                if v.giorni is not None and v.giorni <= GIORNI_SCADENZE]
        _azioni(request, voci)
        persona = chiavi_persona_di(request)
        righe = [v for v in voci if e_mia(v, user_id=user_id, chiavi_persona=persona)]
        righe.sort(key=lambda v: v.giorni)
        esito = [{
            "code": v.source_label,
            "title": v.titolo or v.soggetto,
            "meta": f"{v.kind_label} · {v.data_scadenza:%d/%m/%Y}" if v.kind_label else f"{v.data_scadenza:%d/%m/%Y}",
            "status": "Scaduta" if v.giorni < 0 else ("Oggi" if v.giorni == 0 else f"Tra {v.giorni} gg"),
            "due": v.data_scadenza,
            "url": v.url,
        } for v in righe[:15]]
    except Exception:
        logger.exception("Le mie scadenze non calcolabili")
        return []
    cache.set(chiave, esito, 300)
    return esito


def _segna_urgenze(sections: list[dict]) -> tuple[int, int]:
    """Aggiunge a ogni voce l'urgenza e restituisce quante sono scadute ed entro 7 giorni.

    Conta solo le voci con una data vera: ticket e anomalie non ne hanno una.
    """
    oggi = timezone.localdate()
    fra_7 = oggi + timedelta(days=7)
    scadute = presto = 0
    for s in sections:
        for it in s["items"]:
            due = it.get("due")
            if isinstance(due, datetime):
                due = due.date()
            it["urgenza"] = ""
            if due:
                it["urgenza"] = "scaduta" if due < oggi else ("presto" if due <= fra_7 else "")
            it["rank"] = {"scaduta": 0, "presto": 1}.get(it["urgenza"], 2)
            it["due_iso"] = due.isoformat() if due else "9999-12-31"
        s["n_scadute"] = s.get("overdue_total", sum(1 for i in s["items"] if i["urgenza"] == "scaduta"))
        s["n_presto"] = s.get("soon_total", sum(1 for i in s["items"] if i["urgenza"] == "presto"))
        s["n_totale"] = s.get("total", len(s["items"]))
        s["n_altre"] = s["n_totale"] - len(s["items"])
        scadute += s["n_scadute"]
        presto += s["n_presto"]
    return scadute, presto


def build_cose_da_gestire(request: HttpRequest) -> dict[str, Any]:
    """Aggrega in un'unica struttura le "cose da gestire" dell'utente corrente,
    attraversando i moduli. Riusato sia dalla pagina dedicata `mie_attivita` sia
    dalla sezione in home. Ogni fonte è difensiva (un errore non rompe il resto).

    Ritorna {"sections": [...], "total": n}. Le scadenze HR personali
    (visite/qualifiche) sono volutamente escluse da questa versione: richiedono il
    mapping utente→anagrafica e toccano dati sanitari (privacy), da inquadrare a parte.
    """
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    is_admin = request.user.is_superuser or (is_legacy_admin(legacy_user) if legacy_user else False)
    legacy_user_id = int(legacy_user.id) if legacy_user else None

    kickoff = _my_kickoff(request)
    odl = _my_workorders(request.user)
    dpi_mie = _my_dpi(request)
    ticket = _my_tickets(request.user, legacy_user, legacy_user_id)
    ticket_totale = max(len(ticket), _my_tickets_totale(request.user, legacy_user, legacy_user_id))
    # Ticket del mio team che nessuno ha preso: non sono «miei» per identità, ma aspettano me.
    from dashboard.mie_attivita_fonti import ticket_team_da_assegnare

    del_team = ticket_team_da_assegnare(request)
    gia_ticket = {t["code"] for t in ticket}
    nuovi = [t for t in del_team["items"] if t["code"] not in gia_ticket]
    ticket = nuovi + ticket
    ticket_totale += del_team["total"] - (len(del_team["items"]) - len(nuovi))
    assenze_squadra = _assenze_squadra(legacy_user, is_admin)
    sections = [
        {
            "key": "kickoff",
            "label": "KICK-OFF",
            "tone": "warning",
            "icon": "🗂",
            "items": kickoff["items"],
            "total": kickoff["total"],
            "overdue_total": kickoff["overdue"],
            "soon_total": kickoff["soon"],
            "all_url": _safe_url("tasks:mie_azioni"),
            "empty": "Niente da fare nelle commesse.",
        },
        {
            "key": "ordini_lavoro",
            "label": "Ordini di lavoro",
            "tone": "warning",
            "icon": "🛠",
            "items": odl["items"],
            "total": odl["total"],
            "all_url": _safe_url("assets:wo_list") + f"?status=OPEN&assigned={request.user.pk}",
            "empty": "Nessun ordine di lavoro aperto assegnato a te.",
        },
        {
            "key": "approvazioni",
            "label": "Assenze della squadra",
            "tone": "info",
            "icon": "✅",
            "items": assenze_squadra["items"],
            "total": assenze_squadra["total"],
            "informative": assenze_squadra["informative"],
            "nota": assenze_squadra["nota"],
            "all_url": _safe_url("assenze_gestione"),
            "empty": "Nessuna assenza da accettare o accettata in arrivo.",
        },
        {
            "key": "ticket",
            "label": "Ticket aperti",
            "tone": "warning",
            "icon": "🎫",
            "items": ticket,
            "total": max(len(ticket), ticket_totale),
            "all_url": _safe_url("tickets:dashboard"),
            "empty": "Nessun ticket aperto correlato.",
        },
        {
            "key": "anomalie",
            "label": "Anomalie aperte",
            "tone": "danger",
            "icon": "⚠",
            "items": _my_anomalie(legacy_user, is_admin),
            "all_url": _safe_url("gestione_anomalie_page"),
            "empty": "Nessuna anomalia aperta a te collegata.",
        },
        {
            "key": "non_conformita",
            "label": "Non conformità",
            "tone": "warning",
            "icon": "📋",
            "items": _my_nc(request, legacy_user),
            "all_url": _safe_url("anomalie_nc_lista") + "?mie=1",
            "empty": "Nessuna non conformità o azione a te assegnata.",
        },
        {
            "key": "procedure",
            "label": "Procedure da leggere",
            "tone": "info",
            "icon": "📄",
            "items": _my_procedure(request.user),
            "all_url": _safe_url("procedure_refresh:my_assignments"),
            "empty": "Nessuna procedura da leggere.",
        },
        {
            "key": "dpi_da_fare",
            "label": "DPI da gestire",
            "tone": "warning",
            "icon": "🥾",
            "items": _dpi_da_fare(request),
            "all_url": _safe_url("dpi:dashboard"),
            "empty": "Nessun DPI da approvare, ordinare o consegnare.",
        },
        {
            "key": "dpi",
            "label": "Richieste DPI in corso",
            "tone": "info",
            "icon": "🦺",
            "items": dpi_mie["items"],
            "total": dpi_mie["total"],
            "all_url": _safe_url("dpi:dashboard"),
            "empty": "Nessuna richiesta DPI in corso.",
        },
        {
            "key": "elearning",
            "label": "Corsi e-learning da completare",
            "tone": "info",
            "icon": "🎓",
            "items": _my_elearning(request),
            "all_url": _safe_url("anagrafica:formazione_online_catalog"),
            "empty": "Nessun corso e-learning da completare.",
        },
        {
            "key": "skm_refresh",
            "label": "Refresh abilitazioni macchina",
            "tone": "warning",
            "icon": "🔧",
            "items": _my_skm_refresh(_anagrafica_id(request)),
            "all_url": _safe_url("anagrafica:skm_scadenzario"),
            "empty": "Nessun refresh abilitazioni da gestire.",
        },
    ]

    # Sezione Salute e Sicurezza (solo per chi gestisce formazione/HR).
    safety_items = _safety_scadenze(request)
    if safety_items is not None:
        sections.append({
            "key": "safety",
            "label": "Salute e Sicurezza — scadenze qualifiche",
            "tone": "warning",
            "icon": "🛡",
            "items": safety_items,
            "all_url": _safe_url("anagrafica:scadenzario") + "?tipo=qualifica",
            "empty": "Nessuna qualifica scaduta o in scadenza.",
        })

    from dashboard import mie_attivita_fonti as fonti

    sections.append({
        "key": "approvazioni_varie",
        "label": "Approvazioni e richieste",
        "tone": "info",
        "icon": "🖊",
        "items": fonti.approvazioni(request),
        "all_url": _safe_url("procedure_refresh:modifiche") + "?mie=1",
        "empty": "Nessuna modifica SGI, approvazione, richiesta di visita, spostamento date, segnalazione di modifica o rilevazione di sicurezza in attesa di te.",
    })
    sections.append({
        "key": "assegnate",
        "label": "Altre voci assegnate a te",
        "tone": "warning",
        "icon": "📌",
        "items": fonti.assegnate(request),
        "all_url": _safe_url("scadenze_globali") + "?mie=1",
        "empty": "Nessuna voce assegnata in schede di sicurezza, manutenzioni, onboarding, specifiche, OFI, CAR, obiettivi, Suggestion Corner, attrezzature o checklist.",
    })

    # Le voci già presenti in un'altra sezione non si ripetono fra le scadenze (stesso link).
    gia = {it["url"] for s in sections for it in s["items"] if it.get("url") not in (None, "", "#")}
    mie = [v for v in _mie_scadenze(request) if v.get("url") not in gia]
    if mie:
        sections.append({
            "key": "scadenze",
            "label": "Le mie scadenze",
            "tone": "warning",
            "icon": "📅",
            "items": mie,
            "all_url": _safe_url("scadenze_globali") + "?mie=1",
            "empty": f"Nessuna scadenza nei prossimi {GIORNI_SCADENZE} giorni.",
        })

    # Le righe informative (assenze già accettate) non sono cose da fare: fuori dal totale.
    total = sum(s.get("total", len(s["items"])) - s.get("informative", 0) for s in sections)
    overdue, soon = _segna_urgenze(sections)
    return {"sections": sections, "total": total, "overdue": overdue, "soon": soon}


def contesto_mie_attivita(data: dict[str, Any]) -> dict[str, Any]:
    """Dati del blocco «Le mie attività», uguale nella pagina dedicata e nella Home."""
    return {
        "sections": data["sections"],
        "sections_piene": [s for s in data["sections"] if s["items"]],
        "sections_vuote": [s for s in data["sections"] if not s["items"]],
        "total_open": data["total"],
        "total_overdue": data.get("overdue", 0),
        "total_soon": data.get("soon", 0),
        "oggi": timezone.localdate(),
    }


@login_required
def mie_attivita(request: HttpRequest) -> HttpResponse:
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    display_name = (
        request.user.first_name
        or getattr(legacy_user, "nome", "")
        or request.user.get_username()
    )

    data = build_cose_da_gestire(request)

    context: dict[str, Any] = {
        "page_title": "Le mie attività",
        "greeting_name": display_name,
        **contesto_mie_attivita(data),
    }
    return render(request, "dashboard/pages/mie_attivita.html", context)
