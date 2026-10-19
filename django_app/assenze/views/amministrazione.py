"""Viste del modulo Assenze — Amministrazione: gestione, impostazioni, export CSV, riconciliazione.

Spacchettamento di ``assenze/views.py`` (18/10/2026): le funzioni condivise stanno in
``_helpers`` e si chiamano ``_helpers.nome`` così i test patchano un solo punto.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone as dt_timezone
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import transaction
from django.http import HttpResponseForbidden, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods
from core.csv_export import safe_csv_writer

from admin_portale.decorators import legacy_admin_or_acl_required
from core.models import AuditLog
from core.module_branding import get_module_branding_context, handle_module_branding_post


from . import _helpers  # noqa: E402

logger = logging.getLogger(__name__)


VISIBILITA_LIVELLI = (
    (
        "all",
        "view_all_assenze",
        "Tutta l'azienda",
        "Vede le assenze di tutti i dipendenti: calendario completo, coda globale ed export integrale.",
    ),
    (
        "reparto",
        "view_reparto_assenze",
        "Solo il proprio reparto",
        "Vede le assenze dei dipendenti di cui è capo assegnato — lo stesso insieme che può approvare.",
    ),
)


def _visibilita_overview() -> dict:
    """Chi ricade in quale livello di visibilità, per il cruscotto in Impostazioni.

    Legge le stesse sorgenti che `user_can_modulo_action` consulta a runtime:
    permessi di ruolo (`permessi`) e override per singolo utente
    (`UserPermissionOverride`). È una fotografia di sola lettura: la modifica
    resta in /admin-portale/accessi/, che è la pagina unica per i permessi.
    """
    from core.legacy_models import Permesso, Ruolo, UtenteLegacy
    from core.models import UserPermissionOverride

    livelli = []
    for scope, codice, etichetta, descrizione in VISIBILITA_LIVELLI:
        ruoli: list[str] = []
        utenti_si: list[str] = []
        utenti_no: list[str] = []
        try:
            ruolo_ids = [
                p.ruolo_id
                for p in Permesso.objects.filter(modulo__iexact="assenze", azione__iexact=codice)
                if bool(p.can_view) or bool(p.consentito)
            ]
            if ruolo_ids:
                ruoli = sorted(
                    str(r.nome or "").strip()
                    for r in Ruolo.objects.filter(id__in=set(ruolo_ids))
                    if str(r.nome or "").strip()
                )
        except Exception:
            _helpers.logger.debug("_visibilita_overview: lettura permessi ruolo fallita (%s)", codice, exc_info=True)
        try:
            overrides = list(
                UserPermissionOverride.objects.filter(
                    modulo__iexact="assenze", azione__iexact=codice
                ).exclude(can_view__isnull=True)
            )
            if overrides:
                nomi = {
                    u.id: (str(u.nome or "").strip() or str(u.email or "").strip() or f"utente {u.id}")
                    for u in UtenteLegacy.objects.filter(id__in={o.legacy_user_id for o in overrides})
                }
                for o in overrides:
                    label = nomi.get(o.legacy_user_id, f"utente {o.legacy_user_id}")
                    (utenti_si if o.can_view else utenti_no).append(label)
                utenti_si.sort()
                utenti_no.sort()
        except Exception:
            _helpers.logger.debug("_visibilita_overview: lettura override fallita (%s)", codice, exc_info=True)

        livelli.append(
            {
                "scope": scope,
                "codice": codice,
                "etichetta": etichetta,
                "descrizione": descrizione,
                "ruoli": ruoli,
                "utenti_concessi": utenti_si,
                "utenti_negati": utenti_no,
                "configurato": bool(ruoli or utenti_si or utenti_no),
            }
        )
    return {
        "visibilita_livelli": livelli,
        "visibilita_configurata": any(l["configurato"] for l in livelli),
    }


@login_required
@ensure_csrf_cookie
def impostazioni_admin(request):
    """Pagina «Impostazioni» del modulo assenze — riservata all'HR-admin.

    Contiene il pannello amministrativo (statistiche globali, gestione di TUTTE le
    assenze con Approva/Rifiuta/Elimina, log attività) e il branding di modulo.
    Gate: capability ACL `admin_assenze`. I profili non-admin vengono rimandati alla
    pagina personale «Le mie richieste».
    """
    if not _helpers.user_can_modulo_action(request, "assenze", "admin_assenze"):
        from django.shortcuts import redirect
        return redirect("assenze_gestione")

    if request.method == "POST":
        if str(request.POST.get("form") or "").strip() == "flessibilita":
            return _salva_impostazioni_flessibilita(request)

        branding_response = handle_module_branding_post(
            request,
            module_key="assenze",
            redirect_to="assenze_impostazioni",
            audit_module="assenze",
            fallback_label="Assenze",
        )
        if branding_response is not None:
            return branding_response

    perms = _helpers._assenze_permissions(request)
    admin_q = (request.GET.get("q_admin") or "").strip()
    admin_overview = _admin_assenze_overview(
        admin_q,
        stato=request.GET.get("stato") or "",
        tipo=request.GET.get("tipo") or "",
        da=request.GET.get("da") or "",
        a=request.GET.get("a") or "",
        page=request.GET.get("page") or 1,
        per_page=request.GET.get("per_page") or ADMIN_PER_PAGE_DEFAULT,
        ordina=request.GET.get("ordina") or _helpers.ADMIN_ORDINAMENTO_DEFAULT,
        verso=request.GET.get("verso") or "desc",
    )
    admin_audit_entries = list(
        AuditLog.objects.filter(modulo="assenze").order_by("-created_at")[:100]
    )

    return _helpers.render(
        request,
        "assenze/pages/impostazioni.html",
        {
            "is_assenze_admin": True,
            "can_manage_module_branding": True,
            "admin_q": admin_q,
            "admin_tabella_ok": admin_overview.get("tabella_ok", False),
            "admin_stats": admin_overview.get("stats"),
            "admin_by_tipo": admin_overview.get("by_tipo"),
            "admin_sync_info": admin_overview.get("sync_info"),
            "admin_assenze": admin_overview.get("assenze"),
            "admin_filtri": admin_overview.get("filtri"),
            "admin_paginazione": admin_overview.get("paginazione"),
            "admin_tipi_disponibili": admin_overview.get("tipi_disponibili"),
            "admin_mostra_creata": admin_overview.get("mostra_creata"),
            "admin_stati_disponibili": admin_overview.get("stati_disponibili"),
            "admin_per_page_scelte": admin_overview.get("per_page_scelte"),
            "admin_audit_entries": admin_audit_entries,
            "admin_can_moderate": perms.get("can_update_any", False),
            "admin_can_delete": perms.get("can_delete_any", False),
            **_visibilita_overview(),
            **_flessibilita_admin_context(),
            **get_module_branding_context("assenze", fallback_label="Assenze"),
            **_helpers._template_perm_context(request),
        },
    )


def _flessibilita_admin_context() -> dict:
    """Dati della sezione «Flessibilità» di Impostazioni."""
    from ..models import FlessibilitaAbilitato

    conf = _helpers._flessibilita_config()
    abilitati_ids = _helpers._flessibilita_abilitati_ids()
    dipendenti = _helpers._load_dipendenti_attivi_list()
    elenco = [
        {
            "id": _helpers._as_int(d.get("id")),
            "full_name": d.get("full_name") or "",
            "abilitato": _helpers._as_int(d.get("id")) in abilitati_ids,
        }
        for d in dipendenti
        if _helpers._as_int(d.get("id")) is not None
    ]
    # Chi e' abilitato ma non compare fra gli attivi (es. cessato) resterebbe
    # invisibile: lo mostriamo comunque, altrimenti non si potrebbe togliere.
    noti = {row["id"] for row in elenco}
    for orfano in FlessibilitaAbilitato.objects.exclude(legacy_anagrafica_id__in=noti):
        elenco.append(
            {
                "id": orfano.legacy_anagrafica_id,
                "full_name": orfano.nominativo or f"#{orfano.legacy_anagrafica_id}",
                "abilitato": True,
                "fuori_elenco": True,
            }
        )
    elenco.sort(key=lambda row: str(row.get("full_name") or "").casefold())
    return {
        "flessibilita_orari_entrata": ", ".join(conf.entrate),
        "flessibilita_orari_uscita": ", ".join(conf.uscite),
        "flessibilita_dipendenti": elenco,
        "flessibilita_abilitati_count": len(abilitati_ids),
    }


def _salva_impostazioni_flessibilita(request):
    """Salva orari ammessi ed elenco degli abilitati alla flessibilità."""
    from django.contrib import messages
    from django.shortcuts import redirect

    from ..models import FlessibilitaAbilitato, FlessibilitaImpostazioni

    conf = FlessibilitaImpostazioni.get_solo()
    entrate = FlessibilitaImpostazioni._parse(request.POST.get("orari_entrata"))
    uscite = FlessibilitaImpostazioni._parse(request.POST.get("orari_uscita"))
    if not entrate or not uscite:
        messages.error(
            request,
            "Orari flessibilità non salvati: servono almeno un orario di entrata e uno di uscita, in formato HH:MM.",
        )
        return redirect("assenze_impostazioni")

    conf.orari_entrata = ",".join(entrate)
    conf.orari_uscita = ",".join(uscite)
    conf.updated_by = (request.user.get_username() or "")[:200]
    conf.save()

    selezionati: set[int] = set()
    for raw in request.POST.getlist("abilitati"):
        value = _helpers._as_int(raw)
        if value is not None and value > 0:
            selezionati.add(value)

    nomi = {
        _helpers._as_int(d.get("id")): str(d.get("full_name") or "")
        for d in _helpers._load_dipendenti_attivi_list()
    }
    precedenti = _helpers._flessibilita_abilitati_ids()
    with transaction.atomic():
        FlessibilitaAbilitato.objects.exclude(legacy_anagrafica_id__in=selezionati).delete()
        for ana_id in sorted(selezionati - precedenti):
            FlessibilitaAbilitato.objects.update_or_create(
                legacy_anagrafica_id=ana_id,
                defaults={
                    "nominativo": (nomi.get(ana_id) or "")[:200],
                    "created_by": (request.user.get_username() or "")[:200],
                },
            )

    _helpers.log_action(
        request,
        "impostazioni_flessibilita_salvate",
        "assenze",
        {
            "orari_entrata": conf.orari_entrata,
            "orari_uscita": conf.orari_uscita,
            "abilitati": len(selezionati),
            "aggiunti": sorted(selezionati - precedenti),
            "rimossi": sorted(precedenti - selezionati),
        },
    )
    messages.success(
        request,
        f"Flessibilità aggiornata: {len(selezionati)} dipendenti abilitati, "
        f"entrata {', '.join(entrate)} · uscita {', '.join(uscite)}.",
    )
    return redirect("assenze_impostazioni")


def _riconciliazione_csv(items, da, a):

    from django.http import HttpResponse

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="riconciliazione_presenze_{da:%Y%m%d}_{a:%Y%m%d}.csv"'
    )
    response.write("﻿")  # BOM per Excel
    writer = safe_csv_writer(response, delimiter=";")
    writer.writerow([
        "Dipendente", "Data presenza", "Ore presenza",
        "Tipo assenza approvata", "ID assenza", "ID presenza",
    ])
    for c in items:
        writer.writerow([
            c.nome,
            c.data.strftime("%d/%m/%Y"),
            c.ore_presenza if c.ore_presenza is not None else "",
            c.tipo_label,
            c.assenza_id if c.assenza_id is not None else "",
            c.presenza_id if c.presenza_id is not None else "",
        ])
    return response


@login_required
def riconciliazione(request):
    """RA1 — incongruenze presenza certificata vs assenza approvata (sola lettura).

    Riservata all'Amministrazione assenze (dato globale, le presenze certificate
    non hanno reparto). Export CSV con ?export=csv. Periodo filtrabile (default:
    dal 1° gennaio dell'anno corrente a oggi).
    """
    perms = _helpers._assenze_permissions(request)
    if not (perms.get("can_update_any") or getattr(request.user, "is_superuser", False)):
        return HttpResponseForbidden(
            "Accesso riservato all'Amministrazione assenze."
        )

    from ..riconciliazione import conflitti as _conflitti, parse_periodo

    today = timezone.localdate()
    da, a = parse_periodo(
        request.GET.get("da"),
        request.GET.get("a"),
        default_da=today.replace(month=1, day=1),
        default_a=today,
    )
    items = _conflitti(da, a)

    if request.GET.get("export") == "csv":
        return _riconciliazione_csv(items, da, a)

    return _helpers.render(
        request,
        "assenze/pages/riconciliazione.html",
        {
            "items": items,
            "totale": len(items),
            "da": da,
            "a": a,
            **get_module_branding_context("assenze", fallback_label="Assenze"),
            **_helpers._template_perm_context(request),
        },
    )


BULK_MAX = 200


@login_required
@require_http_methods(["POST"])
def api_admin_bulk_consenso(request):
    """Approva o rifiuta piu' assenze in un colpo solo.

    Ogni record passa dagli **stessi controlli** dell'azione singola (permesso
    sul record, record gestito su SharePoint, esistenza): un'azione in blocco
    non deve poter fare quello che l'azione singola vieta. Gli scarti non
    fermano gli altri: la risposta dice quanti sono passati e perche' gli altri
    no, cosi' l'operatore non resta a chiedersi cosa sia successo.
    """
    perms = _helpers._assenze_permissions(request)
    if not perms.get("can_update_owned") and not perms.get("can_update_any"):
        return _helpers._json_error("Permessi insufficienti per moderare le assenze.", status=403)

    payload = _helpers._request_json(request) or {}
    consenso = _helpers._norm_consenso(payload.get("consenso") or request.POST.get("consenso") or "")
    if consenso not in {"Approvato", "Rifiutato"}:
        return _helpers._json_error("Valore consenso non valido. Usa 'Approvato' o 'Rifiutato'.", status=400)

    note_gestione = str(payload.get("note_gestione") or request.POST.get("note_gestione") or "").strip()
    if not note_gestione:
        return _helpers._json_error("La nota è obbligatoria.", status=400)

    ids_raw = payload.get("ids")
    if ids_raw is None:
        ids_raw = request.POST.getlist("ids")
    ids: list[int] = []
    for raw in ids_raw or []:
        value = _helpers._as_int(raw)
        if value is not None and value > 0 and value not in ids:
            ids.append(value)
    if not ids:
        return _helpers._json_error("Nessuna assenza selezionata.", status=400)
    if len(ids) > BULK_MAX:
        return _helpers._json_error(f"Troppe assenze selezionate: massimo {BULK_MAX} per volta.", status=400)

    fatte: list[int] = []
    scartate: list[dict] = []
    for item_id in ids:
        current = _helpers._get_assenza(item_id)
        if not current:
            scartate.append({"id": item_id, "motivo": "record non trovato"})
            continue
        if not _helpers._can_manage_record(request, current, require_delete=False):
            scartate.append({"id": item_id, "motivo": "fuori dal tuo ambito"})
            continue
        if _helpers._e_propria_assenza(request, current):
            scartate.append({"id": item_id, "motivo": "è una tua richiesta"})
            continue
        if _helpers._sharepoint_managed_error(item_id) is not None:
            scartate.append({"id": item_id, "motivo": "gestita su SharePoint"})
            continue
        if _helpers._applica_moderazione(request, item_id, current, consenso, note_gestione) is None:
            scartate.append({"id": item_id, "motivo": "aggiornamento non eseguito"})
            continue
        fatte.append(item_id)

    _helpers.log_action(request, "assenze_moderate_in_blocco", "assenze", {
        "consenso": consenso,
        "richieste": len(ids),
        "applicate": len(fatte),
        "scartate": len(scartate),
        "note_gestione": note_gestione,
    })

    return JsonResponse({
        "ok": True,
        "consenso": consenso,
        "applicate": len(fatte),
        "ids_applicati": fatte,
        "scartate": scartate,
    })


@login_required
@require_http_methods(["POST"])
def api_admin_assenza_delete(request, item_id: int):
    """API admin: elimina una qualsiasi assenza registrando una nota obbligatoria nel log."""
    perms = _helpers._assenze_permissions(request)
    if not perms.get("can_delete_any"):
        return _helpers._json_error("Permessi insufficienti: solo l'amministrazione può eliminare le assenze.", status=403)

    current = _helpers._get_assenza(item_id)
    if not current:
        return _helpers._json_error("Record non trovato.", status=404)

    payload = _helpers._request_json(request)
    note_raw = (payload.get("note_gestione") if payload else None)
    if note_raw is None:
        note_raw = request.POST.get("note_gestione", "")
    note_gestione = str(note_raw or "").strip()
    if not note_gestione:
        return _helpers._json_error("La nota è obbligatoria per eliminare un'assenza.", status=400)
    managed_error = _helpers._sharepoint_managed_error(item_id)
    if managed_error:
        return managed_error

    # Stessa transazione: la coda di eliminazione esiste solo se il record e' davvero cancellato.
    with transaction.atomic():
        _helpers._sp_enqueue_delete(item_id, current.get("sharepoint_item_id"))
        if not _helpers._delete_assenza(item_id):
            transaction.set_rollback(True)
            return _helpers._json_error("Eliminazione non riuscita.", status=500)

    # --- Audit log ---
    try:
        _helpers.log_action(request, "assenza_eliminata", "assenze", {
            "item_id": item_id,
            "dipendente": str(current.get("copia_nome") or ""),
            "tipo": _helpers._tipo_for_display(current.get("tipo_assenza"), current.get("motivazione_richiesta")),
            "note_gestione": note_gestione,
        })
    except Exception:
        pass

    # Notifica eliminazione (best-effort), coerente con api_evento_delete.
    if _helpers._as_int(current.get("moderation_status")) == 0:
        try:
            _helpers._notify_assenza_deleted(request, current)
        except Exception:
            _helpers.logger.warning("api_admin_assenza_delete: notifica fallita per id=%s", item_id, exc_info=True)

    return JsonResponse({"ok": True, "item_id": item_id})


@login_required
def export_gestione_assenze_csv(request):
    """Esporta in CSV le proprie assenze (vista gestione personale)."""
    legacy_user = getattr(request, "legacy_user", None) or _helpers.get_legacy_user(request.user)
    nome = getattr(legacy_user, "nome", "") or ""
    email = getattr(legacy_user, "email", "") or ""
    rows_data = _helpers._load_personal(nome, email, limit=5000)
    _helpers.log_action(
        request,
        "export_csv",
        "assenze",
        {
            "rows": len(rows_data),
            "filters": {
                "scope": "personal",
                "nome": nome,
                "email": email,
                "limit": 5000,
            },
        },
    )

    headers = ["Tipo", "Inizio", "Fine", "Stato", "Motivazione", "Certificato medico", "Note"]

    def row_iter():
        for r in rows_data:
            yield [
                r.get("tipo", ""),
                r.get("inizio", ""),
                r.get("fine", ""),
                r.get("stato", ""),
                r.get("motivazione", ""),
                r.get("certificato_medico", ""),
                r.get("note_gestione", ""),
            ]

    return _helpers._csv_streaming_response(row_iter(), headers, "mie_assenze.csv")


ADMIN_STATI = {
    "in_attesa": ("In attesa", 2),
    "approvate": ("Approvate", 0),
    "rifiutate": ("Rifiutate", 1),
}
ADMIN_PER_PAGE_SCELTE = (25, 50, 100, 200)
ADMIN_PER_PAGE_DEFAULT = 25

# Il pannello si apre su cio' che ha bisogno di una decisione: le approvate
# sono migliaia e non chiedono niente a nessuno. "tutti" e' la scelta esplicita
# per vedere l'intero storico.
ADMIN_STATO_DEFAULT = "in_attesa"
ADMIN_STATO_TUTTI = "tutti"


def _admin_assenze_overview(
    q: str = "",
    *,
    stato: str = "",
    tipo: str = "",
    da: str = "",
    a: str = "",
    page: int = 1,
    per_page: int = ADMIN_PER_PAGE_DEFAULT,
    ordina: str = _helpers.ADMIN_ORDINAMENTO_DEFAULT,
    verso: str = "desc",
) -> dict:
    """Panoramica admin del modulo assenze.

    Statistiche globali, distribuzione per tipo e **una pagina** di record
    filtrati. Prima venivano caricate in pagina fino a 5000 righe perche' la
    ricerca era client-side: su uno storico reale significa un documento enorme
    da scaricare e da rendere a ogni apertura delle Impostazioni, per poi
    guardarne venti. Filtri, ordinamento e paginazione sono ora lato server, e
    la ricerca copre comunque l'intero storico perche' e' una WHERE, non un
    filtro sul DOM.
    """
    tabella_ok = _helpers._table_exists("assenze")
    stats = {"total": 0, "in_attesa": 0, "approvate": 0, "rifiutate": 0}
    by_tipo: list[dict] = []
    from ..models import AssenzaSharePointOutbox

    last_pull_ts = _helpers._as_int(cache.get(_helpers._SYNC_PULL_LAST_TS_KEY))
    sync_info = {
        "last_pull": (
            timezone.localtime(datetime.fromtimestamp(last_pull_ts, tz=dt_timezone.utc)).strftime("%d/%m/%Y %H:%M")
            if last_pull_ts else None
        ),
        "pending": AssenzaSharePointOutbox.objects.count(),
        "failing": AssenzaSharePointOutbox.objects.filter(tentativi__gt=0).count(),
    }

    stato = str(stato or "").strip().lower()
    if stato == ADMIN_STATO_TUTTI:
        stato = ""
    elif stato not in ADMIN_STATI:
        stato = ADMIN_STATO_DEFAULT
    tipo = str(tipo or "").strip()
    ordina = str(ordina or "").strip().lower()
    if ordina not in _helpers.ADMIN_ORDINAMENTI:
        ordina = _helpers.ADMIN_ORDINAMENTO_DEFAULT
    verso = "asc" if str(verso or "").strip().lower() == "asc" else "desc"
    q = str(q or "").strip()
    da_dt = _helpers._parse_input_dt(f"{da}T00:00") if str(da or "").strip() else None
    a_dt = _helpers._parse_input_dt(f"{a}T23:59") if str(a or "").strip() else None
    try:
        per_page = int(per_page)
    except (TypeError, ValueError):
        per_page = ADMIN_PER_PAGE_DEFAULT
    if per_page not in ADMIN_PER_PAGE_SCELTE:
        per_page = ADMIN_PER_PAGE_DEFAULT
    try:
        page = max(1, int(page))
    except (TypeError, ValueError):
        page = 1

    risultato = {
        "tabella_ok": tabella_ok,
        "stats": stats,
        "by_tipo": by_tipo,
        "sync_info": sync_info,
        "assenze": [],
        "filtri": {
            "q": q,
            # Nel form: stringa vuota significa "tutti", altrimenti il menu non
            # potrebbe piu' rappresentare la scelta esplicita di vedere tutto.
            "stato": stato or ADMIN_STATO_TUTTI,
            "tipo": tipo,
            "da": str(da or "").strip(),
            "a": str(a or "").strip(),
            "per_page": per_page,
            "ordina": ordina,
            "verso": verso,
            "attivi": bool(q or tipo or da or a) or stato != ADMIN_STATO_DEFAULT,
            "solo_in_attesa": stato == ADMIN_STATO_DEFAULT,
        },
        "tipi_disponibili": [],
        "mostra_creata": False,
        "stati_disponibili": [{"key": k, "label": v[0]} for k, v in ADMIN_STATI.items()],
        "per_page_scelte": list(ADMIN_PER_PAGE_SCELTE),
        "paginazione": {
            "page": 1, "pages": 1, "per_page": per_page, "total": 0,
            "da_riga": 0, "a_riga": 0, "ha_prec": False, "ha_succ": False,
            "prec": 1, "succ": 1,
        },
    }
    if not tabella_ok:
        return risultato

    def _count_sql(where="", count_params=None):
        sql = "SELECT COUNT(*) FROM assenze" + (f" WHERE {where}" if where else "")
        with _helpers.connections["default"].cursor() as cur:
            cur.execute(sql, count_params or [])
            return cur.fetchone()[0]

    stats["total"] = _count_sql()
    stats["in_attesa"] = _count_sql("COALESCE(moderation_status, 2) = 2")
    stats["approvate"] = _count_sql("COALESCE(moderation_status, 2) = 0")
    stats["rifiutate"] = _count_sql("COALESCE(moderation_status, 2) = 1")

    tipo_sql = _helpers._select_limited(
        "SELECT tipo_assenza, motivazione_richiesta, COUNT(*) AS n FROM assenze GROUP BY tipo_assenza, motivazione_richiesta",
        "ORDER BY n DESC",
        30,
    )
    by_tipo_counts: dict[str, int] = {}
    for row in _helpers._fetch_all_dict(tipo_sql):
        tipo_label = _helpers._tipo_for_display(row.get("tipo_assenza"), row.get("motivazione_richiesta"))
        by_tipo_counts[tipo_label] = by_tipo_counts.get(tipo_label, 0) + int(row.get("n") or 0)
    by_tipo = [
        {"tipo_assenza": t, "n": c}
        for t, c in sorted(by_tipo_counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    risultato["by_tipo"] = by_tipo
    risultato["tipi_disponibili"] = [r["tipo_assenza"] for r in by_tipo]

    where_parts: list[str] = []
    params: list = []
    if q:
        where_parts.append(
            "(UPPER(COALESCE(copia_nome,'')) LIKE UPPER(%s)"
            " OR UPPER(COALESCE(tipo_assenza,'')) LIKE UPPER(%s)"
            " OR UPPER(COALESCE(motivazione_richiesta,'')) LIKE UPPER(%s))"
        )
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
    if stato:
        where_parts.append("COALESCE(moderation_status, 2) = %s")
        params.append(ADMIN_STATI[stato][1])
    if tipo:
        # Il tipo mostrato puo' derivare dalla motivazione ("Certifica presenza"
        # e' persistita come "Altro"): si filtra su entrambe le colonne.
        where_parts.append(
            "(UPPER(COALESCE(tipo_assenza,'')) = UPPER(%s)"
            " OR UPPER(COALESCE(motivazione_richiesta,'')) LIKE UPPER(%s))"
        )
        params.extend([tipo, f"%{tipo}%"])
    if da_dt is not None:
        # Periodi che si intersecano: una richiesta iniziata prima della finestra
        # ma ancora in corso dentro la finestra va mostrata.
        where_parts.append("data_fine >= %s")
        params.append(da_dt)
    if a_dt is not None:
        where_parts.append("data_inizio <= %s")
        params.append(a_dt)
    where_clause = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

    total = _count_sql(" AND ".join(where_parts) if where_parts else "", params)
    pages = max(1, (total + per_page - 1) // per_page)
    page = min(page, pages)
    offset = (page - 1) * per_page

    creata_col = ", created_datetime" if _helpers._has_assenze_column("created_datetime") else ""
    base_sql = f"""
        SELECT
            id, copia_nome AS dipendente, tipo_assenza,
            data_inizio, data_fine, consenso,
            moderation_status, motivazione_richiesta{creata_col}{_helpers._col_utente_id("")}
        FROM assenze
        {where_clause}
    """
    ordina_effettivo = ordina
    if ordina == "creata" and not creata_col:
        ordina_effettivo = _helpers.ADMIN_ORDINAMENTO_DEFAULT
    sql = _helpers._select_paginated(
        base_sql,
        _helpers._admin_order_by(ordina_effettivo, verso),
        offset=offset,
        limit=per_page,
    )

    assenze: list[dict] = []
    for row in _helpers._applica_nominativo(_helpers._fetch_all_dict(sql, params)):
        _, mod_label = _helpers._status_from_moderation(row.get("moderation_status"), default_pending=True)
        assenze.append({
            "id": row.get("id"),
            "dipendente": str(row.get("dipendente") or "N/D"),
            "tipo": _helpers._tipo_for_display(row.get("tipo_assenza"), row.get("motivazione_richiesta")),
            "stato_label": mod_label,
            "moderation_status": row.get("moderation_status"),
            "inizio_label": _helpers._dt_label(row.get("data_inizio")),
            "fine_label": _helpers._dt_label(row.get("data_fine")),
            "motivo": _helpers._strip_tipo_metadata_from_motivazione(row.get("motivazione_richiesta")),
            "creata_label": _helpers._dt_label(row.get("created_datetime")) if creata_col else "",
        })
    _helpers._mark_sharepoint_managed(assenze)

    risultato["assenze"] = assenze
    risultato["mostra_creata"] = bool(creata_col)
    risultato["paginazione"] = {
        "page": page,
        "pages": pages,
        "per_page": per_page,
        "total": total,
        "da_riga": offset + 1 if total else 0,
        "a_riga": min(offset + per_page, total),
        "ha_prec": page > 1,
        "ha_succ": page < pages,
        "prec": max(1, page - 1),
        "succ": min(pages, page + 1),
    }
    return risultato


@legacy_admin_or_acl_required("assenze", "gestione_admin")
def gestione_admin(request):
    """Deprecato: il pannello admin è ora unificato nelle Impostazioni assenze.

    Mantenuto come redirect per retrocompatibilità di eventuali bookmark/URL.
    """
    from django.shortcuts import redirect
    return redirect("assenze_impostazioni")
