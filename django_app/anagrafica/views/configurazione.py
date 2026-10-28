"""Viste anagrafica — Configurazione del modulo: impostazioni, widget, subnav, API e scadenzario.

Spacchettamento di ``anagrafica/views.py`` (18/10/2026): le funzioni condivise stanno in
``_helpers`` e si chiamano ``_helpers.nome`` così i test patchano un solo punto.
"""
from __future__ import annotations

import calendar
import json
import logging
from datetime import date

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Count
from django.http import (
    HttpResponse, JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
# Alias esplicito: in questo file `timezone` è già importato dentro varie
# funzioni (come `tz`/`_tz`) e `datetime.timezone` è un'altra cosa ancora.
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from django.contrib.auth.decorators import login_required
from core import naming
from core.csv_export import BOM, CSV_CONTENT_TYPE, safe_csv_writer
from core.legacy_models import Ruolo, UtenteLegacy
from core.legacy_utils import get_legacy_user

from ..forms import (
    AnagraficaAziendaleForm,
    AnagraficaCivileForm,
    DipendenteLegacyForm,
)
from ..models import (
    AnagraficaHRPermission,
    AnagraficaStatPermission,
    AnagraficaVisiteMedichePermission,
    RecruitingPermission,
    AreaAziendale,
    Reparto,
    CartellaDocumentoDipendente,
    SubnavCategoriaAnagrafica,
    SubnavLinkAnagrafica,
    DipendenteQualifica,
    DipendenteStatLayout,
    LivelloContrattuale,
    Mansione,
    OnboardingOffboardingCampo,
    RuoloOperativo,
    RuoloQualifica,
    TipologiaContratto,
    TipoQualifica,
    TipoVisitaMedica,
    VisitaMedica,
)
from ..models_formazione import (
    TrainingDeadline,
)
from ..services.dpi_ingresso import (
    proposta_righe_iniziali,
)
from ..services import avviso_it_ingresso


from . import _helpers  # noqa: E402
from core.permessi.impostazioni import impostazioni_o

logger = logging.getLogger(__name__)


def _dipendente_workflow_field_groups() -> list[dict]:
    forms_by_source = {
        "legacy": DipendenteLegacyForm(),
        "aziendale": AnagraficaAziendaleForm(),
        "civile": AnagraficaCivileForm(),
    }
    raw_groups = [
        ("Dati account", "legacy", [
            "nome", "cognome", "matricola", "aliasusername", "reparto",
            "mansione", "ruolo", "email", "email_notifica", "attivo",
        ]),
        ("Ruolo e organizzazione", "aziendale", ["area", "ruolo_aziendale", "badge"]),
        ("Ruoli operativi e DPI", "manual", [
            ("ruoli_operativi_ids", "Ruoli operativi"),
            ("dpi_consegna_iniziale", "DPI consegnati all'ingresso"),
        ]),
        ("Contratto e inquadramento", "manual", [
            ("contratto_data_inizio", "Data inizio contratto"),
            ("contratto_data_fine", "Data fine contratto"),
            ("contratto_tipologia_id", "Tipologia contratto"),
            ("contratto_codice_livello", "Livello CCNL"),
            ("contratto_ccnl", "CCNL applicato"),
            ("contratto_qualifica_nome", "Qualifica professionale"),
        ]),
        ("Periodo di prova e prima assunzione", "aziendale", [
            "data_prima_assunzione", "data_assunzione_ultima", "data_cessazione",
            "prova_data_inizio", "prova_data_fine",
        ]),
        ("Contatti aziendali", "aziendale", ["email_aziendale", "telefono_aziendale"]),
        ("Taglie DPI / abbigliamento", "aziendale", ["taglia_scarpe", "taglia_pantalone", "taglia_maglia"]),
        ("Privacy", "aziendale", ["consenso_privacy", "data_consenso_privacy"]),
        ("Dati personali", "civile", [
            "foto", "data_nascita", "luogo_nascita", "provincia_nascita",
            "nazionalita", "genere", "titolo_studio",
        ]),
        ("Residenza", "civile", [
            "indirizzo_residenza", "citta_residenza", "provincia_residenza",
            "cap_residenza", "nazione_residenza",
        ]),
        ("Domicilio", "civile", ["indirizzo_domicilio", "citta_domicilio", "cap_domicilio", "nazione_domicilio"]),
        ("Contatti privati e patente", "civile", ["email_privata", "telefono_privato", "patente_auto"]),
        ("Dati riservati HR", "civile", [
            "codice_fiscale", "nome_banca", "iban", "intestatario_conto",
            "categoria_protetta", "categoria_disabili", "percentuale_disabilita",
        ]),
    ]
    groups: list[dict] = []
    for section, source, fields in raw_groups:
        rows = []
        for entry in fields:
            if isinstance(entry, tuple):
                key, label = entry
                required = False
            else:
                key = entry
                field = forms_by_source.get(source).fields.get(key) if source in forms_by_source else None
                label = field.label if field else key.replace("_", " ").title()
                required = bool(field.required) if field else False
            rows.append({
                "key": key,
                "label": label,
                "section": section,
                "source": source,
                "required": required,
            })
        groups.append({"label": section, "fields": rows})
    return groups


def _dipendente_workflow_field_map() -> dict[str, dict]:
    return {
        field["key"]: field
        for group in _dipendente_workflow_field_groups()
        for field in group["fields"]
    }

_WIDGET_DEFAULT_ORDER = [w["id"] for w in _helpers.STAT_WIDGETS]


# ---------------------------------------------------------------------------
# API: salva layout widget scheda dipendente
# ---------------------------------------------------------------------------

@login_required
@require_POST
def api_dipendente_widget_layout(request):
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({"ok": False, "error": "JSON non valido"}, status=400)

    hidden = [str(wid) for wid in (data.get("hidden") or []) if wid in _WIDGET_DEFAULT_ORDER]
    order = [str(wid) for wid in (data.get("order") or []) if wid in _WIDGET_DEFAULT_ORDER]

    DipendenteStatLayout.objects.update_or_create(
        viewer_user_id=request.user.id,
        defaults={"hidden": hidden, "order": order},
    )
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------------------
# Impostazioni permessi sezione statistiche (solo admin)
# ---------------------------------------------------------------------------

@login_required
def widget_permissions(request):
    legacy_user = get_legacy_user(request.user)
    if not impostazioni_o(request, "anagrafica", _helpers._is_anagrafica_admin):
        messages.error(request, "Accesso riservato agli amministratori.")
        return redirect("anagrafica:index")

    perm = AnagraficaStatPermission.get_instance()

    if request.method == "POST":
        perm.accesso = request.POST.get("accesso", AnagraficaStatPermission.ACCESSO_ADMIN)
        if perm.accesso not in (
            AnagraficaStatPermission.ACCESSO_TUTTI,
            AnagraficaStatPermission.ACCESSO_ADMIN,
            AnagraficaStatPermission.ACCESSO_RUOLI,
        ):
            perm.accesso = AnagraficaStatPermission.ACCESSO_ADMIN
        ruolo_ids_raw = request.POST.getlist("ruolo_ids")
        perm.ruolo_ids = [int(r) for r in ruolo_ids_raw if str(r).isdigit()]
        perm.save()
        messages.success(request, "Impostazioni salvate.")
        return redirect("anagrafica:widget_permissions")

    try:
        ruoli_acl = list(Ruolo.objects.order_by("nome"))
    except Exception:
        ruoli_acl = []

    return render(request, "anagrafica/pages/widget_permissions.html", {
        "perm": perm,
        "ruoli_acl": ruoli_acl,
        "ACCESSO_TUTTI": AnagraficaStatPermission.ACCESSO_TUTTI,
        "ACCESSO_ADMIN": AnagraficaStatPermission.ACCESSO_ADMIN,
        "ACCESSO_RUOLI": AnagraficaStatPermission.ACCESSO_RUOLI,
    })


@login_required
def dipendente_assegnazione_verifica(request, legacy_id: int):
    """Anteprima JSON dell'idoneità per una mansione ipotizzata.

    Chiamata dal form di spostamento quando si sceglie la mansione, per dire
    subito "abilitato" oppure "parziale, manca X" prima di confermare.
    """
    if not _helpers._is_anagrafica_admin(request):
        return JsonResponse({"detail": "Permesso negato."}, status=403)

    from ..services.assegnazioni import verifica_idoneita
    mansione = (request.GET.get("mansione") or "").strip()
    dettaglio_visite = _helpers._can_view_visite_mediche(request)
    esito = verifica_idoneita(legacy_id, mansione, include_visite_dettaglio=dettaglio_visite)
    # Cosa cambia passando alla nuova mansione: rischi, formazione, visite, DPI, SDS.
    area_raw = (request.GET.get("area_aziendale") or "").strip()
    try:
        from ..services.cambio_mansione import confronta
        esito["confronto"] = confronta(
            legacy_id, mansione, area_nuova_id=int(area_raw) if area_raw.isdigit() else None,
        ).as_dict(include_visite_dettaglio=dettaglio_visite) if mansione else None
    except Exception:
        logger.warning("Confronto cambio mansione non calcolabile per %s", legacy_id, exc_info=True)
        esito["confronto"] = None
    return JsonResponse(esito)


# ---------------------------------------------------------------------------
# Mansioni — gestione catalogo
# ---------------------------------------------------------------------------

def _conta_mansioni_lavorative() -> int:
    """Mansioni lavorative attive del Mansionario (colonne macchina/processo della skill matrix)."""
    try:
        from ..services.mansionario_struttura import mansioni as mansioni_lavorative

        return mansioni_lavorative().count()
    except Exception:
        return 0


def _workflow_campo_payload(request, existing: OnboardingOffboardingCampo | None = None) -> tuple[dict | None, str | None]:
    field_map = _dipendente_workflow_field_map()
    campo_key = (request.POST.get("campo_key") or getattr(existing, "campo_key", "") or "").strip()
    meta = field_map.get(campo_key)
    if not meta:
        return None, "Campo del form nuovo dipendente non valido."

    fase = (request.POST.get("fase") or getattr(existing, "fase", "") or "").strip()
    valid_fasi = {value for value, _label in OnboardingOffboardingCampo.FASE_CHOICES}
    if fase not in valid_fasi:
        return None, "Fase onboarding/offboarding non valida."

    categoria = (request.POST.get("categoria") or getattr(existing, "categoria", "") or "").strip()
    valid_categorie = {value for value, _label in OnboardingOffboardingCampo.CATEGORIA_CHOICES}
    if categoria not in valid_categorie:
        categoria = OnboardingOffboardingCampo.CATEGORIA_HR

    label = (request.POST.get("campo_label") or meta["label"]).strip()[:160]
    if not label:
        label = meta["label"][:160]
    try:
        ordine = int((request.POST.get("ordine") or getattr(existing, "ordine", 50) or 50))
    except (TypeError, ValueError):
        ordine = 50
    ordine = max(0, min(ordine, 9999))

    return {
        "fase": fase,
        "campo_key": campo_key,
        "campo_label": label,
        "sezione": meta["section"][:120],
        "categoria": categoria,
        "obbligatorio": request.POST.get("obbligatorio") == "1",
        "is_active": request.POST.get("is_active", "1") == "1",
        "ordine": ordine,
        "note": (request.POST.get("note") or "").strip()[:1000],
        "updated_by": request.user,
    }, None


@login_required
@require_POST
def avviso_it_save(request):
    """Salva destinatari e interruttori dell'avviso IT ai nuovi ingressi (solo admin anagrafica)."""
    ok, resp = _helpers._impostazioni_admin_check(request, "workflow")
    if not ok:
        return resp
    errori = avviso_it_ingresso.salva_configurazione(
        emails_raw=request.POST.get("avviso_it_emails") or "",
        utenti_ids=request.POST.getlist("avviso_it_utenti"),
        ticket=request.POST.get("avviso_it_ticket") == "1",
    )
    if errori:
        for errore in errori:
            messages.error(request, errore)
    else:
        try:
            from core.audit import log_action
            log_action(request, "AVVISO_IT_CONFIGURAZIONE", "anagrafica", avviso_it_ingresso.configurazione())
        except Exception:
            logger.warning("Audit AVVISO_IT_CONFIGURAZIONE fallito", exc_info=True)
        messages.success(request, "Avviso IT ai nuovi ingressi salvato.")
    return _helpers._redirect_impostazioni("workflow")


@login_required
@require_POST
def workflow_campo_create(request):
    ok, resp = _helpers._impostazioni_admin_check(request, "workflow")
    if not ok:
        return resp

    payload, error = _workflow_campo_payload(request)
    if error:
        messages.error(request, error)
        return _helpers._redirect_impostazioni("workflow")

    try:
        obj, created = OnboardingOffboardingCampo.objects.get_or_create(
            fase=payload["fase"],
            campo_key=payload["campo_key"],
            defaults=payload,
        )
        if created:
            messages.success(request, "Campo aggiunto alla lista onboarding/offboarding.")
        else:
            for key, value in payload.items():
                setattr(obj, key, value)
            obj.save()
            messages.info(request, "Associazione gia presente: aggiornata con i nuovi valori.")
    except IntegrityError:
        messages.error(request, "Esiste gia una associazione per questo campo e questa fase.")
    return _helpers._redirect_impostazioni("workflow")


@login_required
@require_POST
def workflow_campo_update(request, campo_id: int):
    ok, resp = _helpers._impostazioni_admin_check(request, "workflow")
    if not ok:
        return resp

    obj = get_object_or_404(OnboardingOffboardingCampo, pk=campo_id)
    payload, error = _workflow_campo_payload(request, existing=obj)
    if error:
        messages.error(request, error)
        return _helpers._redirect_impostazioni("workflow")

    try:
        for key, value in payload.items():
            setattr(obj, key, value)
        obj.save()
        messages.success(request, "Associazione onboarding/offboarding aggiornata.")
    except IntegrityError:
        messages.error(request, "Esiste gia una associazione per questo campo e questa fase.")
    return _helpers._redirect_impostazioni("workflow")


@login_required
@require_POST
def workflow_campo_delete(request, campo_id: int):
    ok, resp = _helpers._impostazioni_admin_check(request, "workflow")
    if not ok:
        return resp
    obj = get_object_or_404(OnboardingOffboardingCampo, pk=campo_id)
    label = obj.campo_label
    obj.delete()
    messages.success(request, f'Associazione "{label}" eliminata.')
    return _helpers._redirect_impostazioni("workflow")


def _raggruppa_scadenze_per_tipo(voci: list[dict]) -> list[dict]:
    """Raggruppa le voci scadenzario per (kind, tipo_nome) — per la vista a
    gruppi espandibili. Ogni gruppo espone i conteggi e le voci ordinate coi
    più urgenti in cima; i gruppi sono ordinati con gli scaduti/urgenti prima.
    """
    from collections import OrderedDict

    buckets: "OrderedDict[tuple, list[dict]]" = OrderedDict()
    for v in voci:
        buckets.setdefault((v.get("kind"), v.get("tipo_nome") or "—"), []).append(v)

    gruppi: list[dict] = []
    for (kind, tipo_nome), gv in buckets.items():
        gv_sorted = sorted(gv, key=lambda x: (not x.get("scaduta"), x.get("giorni", 9999)))
        n_scadute = sum(1 for x in gv if x.get("scaduta"))
        worst = min((x.get("giorni", 9999) for x in gv), default=9999)
        gruppi.append({
            "kind": kind,
            "kind_label": gv[0].get("kind_label", ""),
            "tipo_nome": tipo_nome,
            "tipo_id": gv[0].get("tipo_id"),
            "voci": gv_sorted,
            "n_totale": len(gv),
            "n_scadute": n_scadute,
            "worst_giorni": worst,
            "has_scadute": n_scadute > 0,
        })
    gruppi.sort(key=lambda g: (not g["has_scadute"], g["worst_giorni"], g["tipo_nome"].lower()))
    return gruppi


def _scadenzario_periodo(request, oggi):
    """``(chiave, dal, al, periodo)`` dal GET: mese | prossimo | intervallo (dal/al ISO).

    Intervallo con una sola data = da quella data in poi (o fino a quella data).
    Date non valide o invertite = nessun periodo (vale il filtro di stato)."""
    import calendar as _cal

    chiave = request.GET.get("periodo", "").strip()
    if chiave == "mese":
        dal = oggi.replace(day=1)
        al = oggi.replace(day=_cal.monthrange(oggi.year, oggi.month)[1])
        return chiave, dal, al, (dal, al)
    if chiave == "prossimo":
        dal = _helpers._add_months(oggi.replace(day=1), 1)
        al = dal.replace(day=_cal.monthrange(dal.year, dal.month)[1])
        return chiave, dal, al, (dal, al)
    if chiave == "intervallo":
        def _data(nome):
            try:
                return parse_date(request.GET.get(nome, "").strip())
            except ValueError:
                return None

        dal, al = _data("dal"), _data("al")
        if dal or al:
            dal_eff, al_eff = dal or date(1900, 1, 1), al or date(9999, 12, 31)
            if dal_eff <= al_eff:
                return chiave, dal, al, (dal_eff, al_eff)
    return "", None, None, None


@login_required
def scadenzario(request):
    """Scadenzario unificato: qualifiche, visite mediche, formazione obbligatoria
    e contratti/periodi di prova in scadenza o scaduti.

    Accesso: login obbligatorio. Le voci — e con esse il gating per sorgente —
    arrivano da ``_build_scadenzario_voci``, condiviso con la dashboard.
    """
    from django.utils import timezone as tz
    oggi = tz.localdate()

    can_view_visite = _helpers._can_view_visite_mediche(request)
    can_view_formazione = _helpers._can_view_formazione(request)
    can_view_contratti = _helpers._check_hr_permission(request)

    filtro_tipo    = request.GET.get("tipo", "")         # "qualifica" / "visita" / "formazione" / "contratto" / ""
    filtro_stato   = request.GET.get("stato", "")        # "scaduta" / "30" / "60" / ""
    filtro_reparto = request.GET.get("reparto", "").strip()
    export_csv     = request.GET.get("format") == "csv"
    # Periodo: «questo mese», «prossimo mese» o un intervallo dal/al libero.
    filtro_periodo, periodo_dal, periodo_al, periodo = _scadenzario_periodo(request, oggi)

    voci = _helpers._build_scadenzario_voci(
        request,
        filtro_tipo=filtro_tipo,
        filtro_stato=filtro_stato,
        filtro_reparto=filtro_reparto,
        periodo=periodo,
    )

    # KPI
    n_scadute = sum(1 for v in voci if v["scaduta"])
    n_30gg    = sum(1 for v in voci if not v["scaduta"] and v["giorni"] <= 30)
    n_60gg    = sum(1 for v in voci if not v["scaduta"] and 30 < v["giorni"] <= 60)

    # Raggruppamento per TIPO (con espansione dei dipendenti): un gruppo per
    # (kind, tipo_nome), ordinato con i più urgenti (scaduti / meno giorni) in alto.
    gruppi = _raggruppa_scadenze_per_tipo(voci)

    reparti = sorted({v["reparto"] for v in voci if v["reparto"]})

    # Export CSV
    if export_csv:
        resp = HttpResponse(content_type=CSV_CONTENT_TYPE)
        resp["Content-Disposition"] = 'attachment; filename="scadenzario_anagrafica.csv"'
        resp.write(BOM)  # una volta sola: Excel riconosce l'UTF-8
        writer = safe_csv_writer(resp, delimiter=";")
        writer.writerow(["Dipendente", "Reparto", "Tipo entità", "Descrizione", "Scadenza", "Stato"])
        for v in voci:
            stato = "Scaduta" if v["scaduta"] else f"Scade in {v['giorni']} giorni"
            writer.writerow([
                naming.nome_completo(v["nome"], v["cognome"]),
                v["reparto"],
                v["kind_label"],
                v["tipo_nome"],
                v["data_scadenza"].strftime("%d-%m-%Y") if v["data_scadenza"] else "",
                stato,
            ])
        return resp

    # Paginazione
    paginator  = Paginator(voci, 50)
    page_obj   = paginator.get_page(request.GET.get("page"))

    # Formazione: riepilogo scadenze urgenti da mostrare come sezione aggiuntiva
    fm_n_scaduti = 0
    fm_n_30gg    = 0
    fm_n_90gg    = 0
    fm_is_cache_empty = True
    if can_view_formazione:
        try:
            fm_n_scaduti = TrainingDeadline.objects.filter(stato_scadenza="SCADUTO").count()
            fm_n_30gg    = TrainingDeadline.objects.filter(stato_scadenza="IN_SCADENZA_30").count()
            fm_n_90gg    = TrainingDeadline.objects.filter(stato_scadenza="IN_SCADENZA_90").count()
            fm_is_cache_empty = not TrainingDeadline.objects.exists()
        except Exception:
            logger.exception("Errore caricamento KPI formazione per scadenzario")

    # Toggle di vista: gruppi (default), calendario (griglia mensile),
    # affiancata (due colonne Visite | Formazione). Valore ignoto → gruppi.
    layout = request.GET.get("layout", "gruppi")
    if layout not in ("gruppi", "calendario", "affiancata"):
        layout = "gruppi"

    voci_visite = [v for v in voci if v["kind"] == "visita"]
    voci_formazione = [v for v in voci if v["kind"] == "formazione"]

    cal_settimane = cal_label = cal_prev = cal_next = None
    if layout == "calendario":
        try:
            cal_anno = int(request.GET.get("anno") or oggi.year)
            cal_mese = int(request.GET.get("mese") or oggi.month)
        except (TypeError, ValueError):
            cal_anno, cal_mese = oggi.year, oggi.month
        if not 1 <= cal_mese <= 12:
            cal_mese = oggi.month
        primo = date(cal_anno, cal_mese, 1)
        per_giorno: dict = {}
        for v in voci:
            ds = v["data_scadenza"]
            if ds and ds.year == cal_anno and ds.month == cal_mese:
                per_giorno.setdefault(ds.day, []).append(v)
        settimane = []
        for week in calendar.Calendar(firstweekday=0).monthdatescalendar(cal_anno, cal_mese):
            giorni = []
            for gg in week:
                in_mese = (gg.month == cal_mese)
                giorni.append({
                    "data": gg,
                    "in_mese": in_mese,
                    "voci": per_giorno.get(gg.day, []) if in_mese else [],
                    "is_oggi": gg == oggi,
                })
            settimane.append(giorni)
        cal_settimane = settimane
        cal_label = primo.strftime("%B %Y").capitalize()
        cal_prev = _helpers._add_months(primo, -1)
        cal_next = _helpers._add_months(primo, 1)

    return render(request, "anagrafica/pages/scadenzario.html", {
        "page_obj":      page_obj,
        "n_scadute":     n_scadute,
        "n_30gg":        n_30gg,
        "n_60gg":        n_60gg,
        "oggi":          oggi,
        "filtro_tipo":   filtro_tipo,
        "filtro_stato":  filtro_stato,
        "filtro_reparto": filtro_reparto,
        "filtro_periodo": filtro_periodo,
        "periodo_dal":   periodo_dal,
        "periodo_al":    periodo_al,
        "reparti":       reparti,
        "gruppi":        gruppi,
        "can_view_visite": can_view_visite,
        "totale":        len(voci),
        "can_view_formazione": can_view_formazione,
        "can_view_contratti": can_view_contratti,
        "is_qual_admin": _helpers._qualifiche_can_edit(request),
        "fm_n_scaduti":  fm_n_scaduti,
        "fm_n_30gg":     fm_n_30gg,
        "fm_n_90gg":     fm_n_90gg,
        "fm_is_cache_empty": fm_is_cache_empty,
        "layout":        layout,
        "voci_visite":   voci_visite,
        "voci_formazione": voci_formazione,
        "cal_settimane": cal_settimane,
        "cal_label":     cal_label,
        "cal_prev":      cal_prev,
        "cal_next":      cal_next,
    })


# ---------------------------------------------------------------------------

@login_required
def impostazioni(request):
    """Pannello unico di gestione dei cataloghi/configurazioni del modulo anagrafica."""
    from datetime import timedelta
    from django.utils import timezone as tz

    legacy_user = get_legacy_user(request.user)
    is_admin = impostazioni_o(request, "anagrafica", _helpers._is_anagrafica_admin)

    active_tab = (request.GET.get("tab") or "mansioni").strip().lower()

    # --- Mansioni ---
    mansioni = list(Mansione.objects.all().order_by("nome"))
    mansione_counts: dict[str, int] = {}
    try:
        from django.db import connections
        conn_name = "legacy" if "legacy" in connections else "default"
        with connections[conn_name].cursor() as cur:
            cur.execute(
                "SELECT LOWER(mansione), COUNT(*) FROM anagrafica_dipendenti "
                "WHERE mansione IS NOT NULL AND mansione != '' GROUP BY LOWER(mansione)"
            )
            for row in cur.fetchall():
                mansione_counts[row[0]] = row[1]
    except Exception:
        pass
    for m in mansioni:
        m.n_dipendenti = mansione_counts.get(m.nome.lower(), 0)

    cat_order = [c for c, _ in Mansione.CATEGORIA_CHOICES]
    cat_labels = dict(Mansione.CATEGORIA_CHOICES)
    mansioni_grouped: list[tuple[str, str, list]] = []
    for cat_code in cat_order:
        items = [m for m in mansioni if (m.categoria or Mansione.CAT_ALTRO) == cat_code]
        if items:
            mansioni_grouped.append((cat_code, cat_labels[cat_code], items))

    # --- Reparti e Aree aziendali ---
    aree = list(Reparto.objects.prefetch_related("aree_aziendali", "responsabili").order_by("nome"))
    aree_aziendali = list(AreaAziendale.objects.prefetch_related("responsabili").order_by("nome"))
    dipendenti_picker = _helpers._dipendenti_picker_rows()
    _dip_picker_map = {item["id"]: item["label"] for item in dipendenti_picker}

    def _responsabili_labels(obj):
        ids = [d.id for d in obj.responsabili.all()]
        return ids, ", ".join(_dip_picker_map.get(i, "") for i in ids if _dip_picker_map.get(i, ""))

    for a in aree:
        a.caporeparto_label = _dip_picker_map.get(a.caporeparto_legacy_id or 0, "")
        a.responsabili_ids, a.responsabili_label = _responsabili_labels(a)
    for az in aree_aziendali:
        az.responsabile_label = _dip_picker_map.get(az.responsabile_legacy_id or 0, "")
        az.responsabili_ids, az.responsabili_label = _responsabili_labels(az)

    # --- Ruoli operativi sicurezza ---
    # select_related("riporta_a") + catalogo/suggeriti: il pannello "Ruoli" inline
    # di impostazioni.html riusa il partial _ruoli_operativi_body.html e ha bisogno
    # dello stesso context della pagina autonoma ruoli_operativi_list.
    ruoli_operativi = list(
        RuoloOperativo.objects
        .annotate(n_assegnati=Count("assegnazioni"))
        .select_related("riporta_a", "ambito")
        .order_by("nome")
    )
    ruoli_operativi.sort(key=lambda r: (
        r.ambito.ordine if r.ambito_id else 9999,
        (r.ambito.nome if r.ambito_id else "").casefold(),
        (r.nome or "").casefold(),
    ))
    _ruoli_da_scheda = _helpers._ruoli_conteggio_da_scheda()
    for _r in ruoli_operativi:
        _r.n_da_scheda = _ruoli_da_scheda.get((_r.nome or "").strip().casefold(), 0)
    # Stesso partial della pagina Ruoli: gli serve anche il catalogo qualifiche.
    _qual_per_ruolo: dict[int, list] = {}
    for _rq in RuoloQualifica.objects.select_related("qualifica").order_by("qualifica__nome"):
        _qual_per_ruolo.setdefault(_rq.ruolo_id, []).append(_rq)
    for _r in ruoli_operativi:
        _r.qualifiche = _qual_per_ruolo.get(_r.id, [])
    qualifiche_catalogo_ruoli = list(
        TipoQualifica.objects.filter(is_active=True).order_by("categoria", "nome")
    )
    ruoli_catalogo = list(RuoloOperativo.objects.order_by("nome").values("id", "nome"))
    ruoli_suggeriti = [
        "Preposto", "RSPP", "ASPP", "RLS",
        "Squadra antincendio", "Squadra primo soccorso",
        "Addetto emergenze", "Rappresentante sicurezza",
    ]

    # --- Qualifiche professionali ---
    tipi_qualifica = list(
        TipoQualifica.objects.annotate(n_assegnazioni=Count("assegnazioni"))
        .order_by("categoria", "nome")
    )
    oggi = tz.localdate()
    soglia_q = oggi + timedelta(days=60)
    scadenze_q_count = DipendenteQualifica.objects.filter(
        data_scadenza__isnull=False, data_scadenza__lte=soglia_q
    ).count()

    # --- Livelli contrattuali ---
    livelli = list(LivelloContrattuale.objects.all().order_by("ordine", "codice"))

    # --- Tipologie contratto ---
    tipologie = list(TipologiaContratto.objects.all().order_by("ordine", "codice"))

    # --- Permessi di sezione (singleton TUTTI/ADMIN/RUOLI) ---
    # Una sola lista descrittiva: il template cicla su `permessi_cards` e
    # `impostazioni_permessi_save` salva sugli stessi prefissi. Aggiungere un
    # permesso significa aggiungere una riga qui, non un blocco di markup.
    _permessi_defs = [
        {
            "prefix": "stat",
            "icona": "📊",
            "titolo": "Widget statistiche",
            "descrizione": "Chi può vedere la sezione statistiche attività nella scheda dipendente",
            "perm": AnagraficaStatPermission.get_instance(),
        },
        {
            "prefix": "hr",
            "icona": "🔐",
            "titolo": "Dati HR riservati",
            "descrizione": "Chi può vedere IBAN, codice fiscale, percentuale disabilità nelle schede",
            "perm": AnagraficaHRPermission.get_instance(),
        },
        {
            "prefix": "visite",
            "icona": "🩺",
            "titolo": "Visite mediche",
            "descrizione": "Chi può vedere e registrare le visite mediche (dato sanitario sensibile — default: solo admin)",
            "perm": AnagraficaVisiteMedichePermission.get_instance(),
        },
        {
            "prefix": "recruiting",
            "icona": "🧭",
            "titolo": "Recruiting (MOD. 05-01)",
            "descrizione": "Chi può vedere e gestire le schede candidato: contengono età, cittadinanza e note libere (default: solo admin)",
            "perm": RecruitingPermission.get_instance(),
            "nota": (
                "Questo permesso restringe, non concede: serve comunque il permesso canonico "
                "anagrafica.recruiting.view / .manage in ACL canonico."
            ),
        },
    ]
    # L'allow-list per-utente (utente_ids) esiste su Stat/HR/Visite; RecruitingPermission
    # è arrivato dopo e non la espone → la card non mostra la sezione utenti.
    permessi_cards = []
    for _d in _permessi_defs:
        _perm = _d["perm"]
        _d["supporta_utenti"] = hasattr(_perm, "utente_ids")
        _d["utente_ids"] = list(getattr(_perm, "utente_ids", []) or [])
        permessi_cards.append(_d)
    try:
        from core.legacy_models import Ruolo
        ruoli_acl = list(Ruolo.objects.order_by("nome"))
    except Exception:
        ruoli_acl = []
    # Utenti legacy attivi: allow-list per-utente (singleton) + override canonici.
    try:
        utenti_acl = list(UtenteLegacy.objects.filter(attivo=True).order_by("nome"))
    except Exception:
        utenti_acl = []

    # --- Permessi canonici ACL v2 del modulo (write-through su tabelle core) ---
    # Vista/gestione inline dei permessi anagrafica governati da /admin-portale/
    # acl-canonico/: si legge/scrive DIRETTAMENTE su PermissionDefinition/
    # RolePermissionGrant/UserPermissionGrant → "la solita cosa", nessuna copia.
    acl_perms: list = []
    acl_role_matrix: list = []
    acl_user_overrides: list = []
    try:
        from core.models import (
            PermissionDefinition, RolePermissionGrant, UserPermissionGrant,
        )
        acl_perms = list(
            PermissionDefinition.objects
            .filter(module="anagrafica", is_active=True)
            .order_by("code")
        )
        _perm_codes = [p.code for p in acl_perms]
        if _perm_codes:
            _grant_map = {
                (int(g.legacy_role_id), g.permission_id): bool(g.enabled)
                for g in RolePermissionGrant.objects.filter(permission_id__in=_perm_codes)
            }
            for _r in ruoli_acl:
                acl_role_matrix.append({
                    "role": _r,
                    "cells": [
                        {"code": p.code, "enabled": _grant_map.get((int(_r.id), p.code), False)}
                        for p in acl_perms
                    ],
                })
            _overrides = list(
                UserPermissionGrant.objects
                .filter(permission_id__in=_perm_codes)
                .select_related("permission")
                .order_by("legacy_user_id", "permission_id")
            )
            _uids = {int(o.legacy_user_id) for o in _overrides}
            _users_by_id = (
                {u.id: u for u in UtenteLegacy.objects.filter(id__in=_uids)} if _uids else {}
            )
            _grouped: dict[int, dict] = {}
            for o in _overrides:
                uid = int(o.legacy_user_id)
                grp = _grouped.get(uid)
                if grp is None:
                    _u = _users_by_id.get(uid)
                    _label = (
                        (getattr(_u, "nome", "") or getattr(_u, "email", "")).strip()
                        if _u else ""
                    ) or f"utente #{uid}"
                    grp = {"legacy_user_id": uid, "user_label": _label, "items": []}
                    _grouped[uid] = grp
                grp["items"].append({
                    "code": o.permission_id,
                    "perm_label": o.permission.label,
                    "enabled": bool(o.enabled),
                })
            acl_user_overrides = list(_grouped.values())
    except Exception:
        acl_perms, acl_role_matrix, acl_user_overrides = [], [], []

    # --- Tipi visita medica ---
    # Ordinate per categoria (le senza-categoria in fondo) cosi' il template
    # puo' raggrupparle con {% regroup %} in sezioni collassabili.
    from django.db.models import Case as _VmCase, When as _VmWhen
    tipi_visita = list(
        TipoVisitaMedica.objects
        .annotate(n_visite=Count("visite"))
        .prefetch_related("ruoli_operativi", "mansioni_richiedenti")
        .order_by(_VmCase(_VmWhen(categoria="", then=1), default=0), "categoria", "nome")
    )
    categorie_visita = sorted({
        t.categoria for t in tipi_visita if t.categoria
    })
    scadenze_vm_count = VisitaMedica.objects.filter(
        data_scadenza__isnull=False, data_scadenza__lte=soglia_q
    ).count()

    # --- DPI catalogo (gestione diretta dal pannello) ---
    dpi_categorie = []
    dpi_tipi = []
    dpi_modelli = []
    dpi_taglie = []
    dpi_icone_disponibili = []
    try:
        from dpi.models import CategoriaDPI, TipoDPI, ModelloDPI, TagliaDPI as _TagliaDPI, ICONE_DPI_DISPONIBILI
        dpi_categorie = list(CategoriaDPI.objects.order_by("order_index", "nome"))
        dpi_icone_disponibili = ICONE_DPI_DISPONIBILI
        dpi_tipi = list(TipoDPI.objects.select_related("categoria").prefetch_related("modelli").order_by("categoria__order_index", "categoria__nome", "ordine", "nome"))
        dpi_modelli = list(ModelloDPI.objects.select_related("tipo", "tipo__categoria").order_by("tipo__categoria__order_index", "tipo__ordine", "codice", "nome"))
        dpi_taglie = list(_TagliaDPI.objects.select_related("modello", "modello__tipo", "modello__tipo__categoria").order_by("modello__tipo__categoria__order_index", "modello__tipo__ordine", "ordine", "valore"))
    except Exception:
        pass

    # --- Cartelle documenti (ordinate ad albero: parent → figlie, con livello) ---
    _cartelle_all = list(
        CartellaDocumentoDipendente.objects
        .annotate(n_documenti=Count("documenti"))
        .prefetch_related("reparti", "ruoli_operativi")
        .order_by("ordine", "nome")
    )
    _cartelle_by_parent: dict = {}
    for _c in _cartelle_all:
        # Targeting: id selezionati (per i multiselect del form) + flag "mirata"
        _c.reparti_ids = {r.id for r in _c.reparti.all()}
        _c.ruoli_ids = {r.id for r in _c.ruoli_operativi.all()}
        _c.is_mirata = bool(_c.reparti_ids or _c.ruoli_ids)
        _cartelle_by_parent.setdefault(_c.parent_id, []).append(_c)
    cartelle_documenti: list = []

    def _walk_cartelle(parent_id, livello):
        for _c in _cartelle_by_parent.get(parent_id, []):
            _c.livello = livello
            cartelle_documenti.append(_c)
            _walk_cartelle(_c.id, livello + 1)

    _walk_cartelle(None, 0)

    # --- Subnav navigazione ---
    subnav_categorie = list(SubnavCategoriaAnagrafica.objects.order_by("ordine", "nome"))
    subnav_links = list(
        SubnavLinkAnagrafica.objects
        .select_related("categoria")
        .order_by("ordine", "etichetta")
    )
    # Rotte del modulo selezionabili nei link subnav (pagine GET senza parametri)
    subnav_route_choices = [
        ("anagrafica:index", "Dashboard modulo (home)"),
        ("anagrafica:scadenzario", "Scadenzario unificato (filtrabile)"),
        # Persone
        ("anagrafica:dipendenti_list", "Persone — elenco dipendenti"),
        ("anagrafica:dipendente_create", "Persone — nuovo dipendente"),
        ("anagrafica:ex_dipendenti_list", "Persone — ex dipendenti"),
        ("anagrafica:organigramma", "Persone — organigramma"),
        ("anagrafica:onboarding_list", "Persone — onboarding (pratiche)"),
        ("anagrafica:documenti_list", "Persone — documenti"),
        ("anagrafica:dipendenti_report", "Persone — report dipendenti"),
        # Competenze (formazione + qualifiche)
        ("anagrafica:formazione_dashboard", "Competenze — dashboard formazione"),
        ("anagrafica:formazione_piani_list", "Competenze — piani formativi"),
        ("anagrafica:formazione_corsi_list", "Competenze — corsi"),
        ("anagrafica:formazione_sessioni_list", "Competenze — sessioni"),
        ("anagrafica:formazione_istruttori_list", "Competenze — istruttori"),
        ("anagrafica:formazione_elearning_hub", "Competenze — e-learning (hub)"),
        ("anagrafica:formazione_online_catalog", "Competenze — corsi online"),
        ("anagrafica:formazione_copertura", "Competenze — copertura / gap"),
        ("anagrafica:qualifiche_dashboard", "Competenze — cruscotto qualifiche"),
        ("anagrafica:qualifiche_list", "Competenze — catalogo qualifiche"),
        ("anagrafica:qualifica_sessioni_list", "Competenze — sessioni di rinnovo"),
        ("anagrafica:matrice_competenze", "Competenze — matrice competenze"),
        # Compliance (salute & sicurezza)
        ("anagrafica:sicurezza_hub", "Compliance — hub sicurezza"),
        ("anagrafica:visite_mediche_dashboard", "Compliance — visite mediche"),
        ("anagrafica:visite_mediche_nuova_sessione", "Compliance — visite, nuova sessione"),
        ("anagrafica:conformita_report", "Compliance — conformità alla mansione"),
        # Amministrazione (paghe & contratti)
        ("anagrafica:retribuzioni_globale", "Amministrazione — analisi retribuzioni"),
        ("anagrafica:costo_orario", "Amministrazione — costo orario"),
        ("anagrafica:costo_orario_storico", "Amministrazione — storico del costo orario"),
        ("anagrafica:retribuzioni_import", "Amministrazione — import retribuzioni"),
        ("anagrafica:contratti_import", "Amministrazione — contratti"),
        ("anagrafica:cedolini_import", "Amministrazione — cedolini"),
        ("anagrafica:ratei_list", "Amministrazione — ratei ferie / ROL"),
        # Cataloghi struttura / impostazioni
        ("anagrafica:ruoli_operativi_list", "Catalogo — ruoli operativi"),
        ("anagrafica:mansioni_list", "Catalogo — mansioni"),
        ("anagrafica:aree_list", "Catalogo — reparti"),
        ("anagrafica:ruoli_aziendali_list", "Catalogo — ruoli aziendali"),
        ("anagrafica:widget_permissions", "Impostazioni — permessi widget"),
        ("anagrafica:impostazioni", "Impostazioni anagrafica"),
    ]

    # --- Workflow onboarding/offboarding ---
    workflow_field_groups = _dipendente_workflow_field_groups()
    workflow_field_map = {
        field["key"]: field
        for group in workflow_field_groups
        for field in group["fields"]
    }
    workflow_campi = list(
        OnboardingOffboardingCampo.objects.order_by("fase", "ordine", "campo_label")
    )
    for item in workflow_campi:
        meta = workflow_field_map.get(item.campo_key)
        item.catalog_missing = meta is None
        item.catalog_label = meta["label"] if meta else item.campo_label
        item.catalog_section = meta["section"] if meta else item.sezione

    try:
        from anagrafica.models import RichiestaRettifica

        rettifiche_aperte = RichiestaRettifica.objects.filter(stato=RichiestaRettifica.STATO_APERTA).count()
    except Exception:
        rettifiche_aperte = 0

    return render(request, "anagrafica/pages/impostazioni.html", {
        "is_admin": is_admin,
        "rettifiche_aperte": rettifiche_aperte,
        "active_tab": active_tab,
        # Mansioni
        "mansioni": mansioni,
        "mansioni_grouped": mansioni_grouped,
        "CATEGORIA_CHOICES": Mansione.CATEGORIA_CHOICES,
        "n_mansioni_lavorative": _conta_mansioni_lavorative(),
        # Reparti
        "aree": aree,
        "aree_aziendali": aree_aziendali,
        "dipendenti_picker": dipendenti_picker,
        # Ruoli aziendali
        # Ruoli operativi
        "ruoli_operativi": ruoli_operativi,
        "qualifiche_catalogo": qualifiche_catalogo_ruoli,
        "ruoli_catalogo": ruoli_catalogo,
        "ruoli_suggeriti": ruoli_suggeriti,
        **_helpers._ambiti_context(ruoli_operativi),
        # Qualifiche
        "tipi_qualifica": tipi_qualifica,
        "QUAL_CATEGORIA_CHOICES": TipoQualifica.CATEGORIA_CHOICES,
        "scadenze_q_count": scadenze_q_count,
        # Livelli
        "livelli": livelli,
        # Tipologie
        "tipologie": tipologie,
        # Visite mediche
        "tipi_visita": tipi_visita,
        "categorie_visita": categorie_visita,
        "scadenze_vm_count": scadenze_vm_count,
        # DPI
        "dpi_categorie": dpi_categorie,
        "dpi_tipi": dpi_tipi,
        "dpi_modelli": dpi_modelli,
        "dpi_taglie": dpi_taglie,
        "dpi_icone_disponibili": dpi_icone_disponibili,
        # Permessi
        "permessi_cards": permessi_cards,
        "ruoli_acl": ruoli_acl,
        "utenti_acl": utenti_acl,
        "ACCESSO_TUTTI": AnagraficaStatPermission.ACCESSO_TUTTI,
        "ACCESSO_ADMIN": AnagraficaStatPermission.ACCESSO_ADMIN,
        "ACCESSO_RUOLI": AnagraficaStatPermission.ACCESSO_RUOLI,
        # Permessi canonici ACL v2 del modulo (write-through)
        "acl_perms": acl_perms,
        "acl_role_matrix": acl_role_matrix,
        "acl_user_overrides": acl_user_overrides,
        # Cartelle documenti
        "cartelle_documenti": cartelle_documenti,
        # Subnav navigazione
        "subnav_categorie": subnav_categorie,
        "subnav_links": subnav_links,
        "subnav_route_choices": subnav_route_choices,
        # Workflow onboarding/offboarding
        "workflow_campi": workflow_campi,
        "workflow_field_groups": workflow_field_groups,
        "workflow_fase_choices": OnboardingOffboardingCampo.FASE_CHOICES,
        "workflow_categoria_choices": OnboardingOffboardingCampo.CATEGORIA_CHOICES,
        # Avviso IT ai nuovi ingressi (SiteConfig)
        "avviso_it": avviso_it_ingresso.configurazione(),
    })


@login_required
@require_POST
def impostazioni_permessi_save(request):
    """Salvataggio combinato dei permessi statistiche, dati HR e visite mediche.

    Oltre a modalità (TUTTI/ADMIN/RUOLI) e lista ruoli, salva la allow-list
    per-utente ``utente_ids`` (concessione additiva, chiave = UtenteLegacy.id).
    """
    ok, resp = _helpers._impostazioni_admin_check(request, "permessi")
    if not ok:
        return resp

    def _parse_accesso(prefix: str) -> str:
        val = (request.POST.get(f"{prefix}_accesso") or "").strip()
        if val in (
            AnagraficaStatPermission.ACCESSO_TUTTI,
            AnagraficaStatPermission.ACCESSO_ADMIN,
            AnagraficaStatPermission.ACCESSO_RUOLI,
        ):
            return val
        return AnagraficaStatPermission.ACCESSO_ADMIN

    def _parse_ruoli(prefix: str) -> list[int]:
        raw = request.POST.getlist(f"{prefix}_ruolo_ids")
        return [int(r) for r in raw if str(r).isdigit()]

    def _parse_utenti(prefix: str) -> list[int]:
        raw = request.POST.getlist(f"{prefix}_utente_ids")
        # dedup preservando l'ordine
        seen: dict[int, None] = {}
        for u in raw:
            if str(u).isdigit():
                seen.setdefault(int(u), None)
        return list(seen.keys())

    # Stessi prefissi delle card costruite in `impostazioni`: aggiungere un
    # permesso di sezione significa aggiungere una riga là e una qui. La
    # allow-list per-utente (utente_ids) si salva solo sui permessi che espongono
    # quel campo: RecruitingPermission è arrivato dopo e per ora non lo ha.
    for prefix, modello in (
        ("stat", AnagraficaStatPermission),
        ("hr", AnagraficaHRPermission),
        ("visite", AnagraficaVisiteMedichePermission),
        ("recruiting", RecruitingPermission),
    ):
        perm = modello.get_instance()
        perm.accesso = _parse_accesso(prefix)
        perm.ruolo_ids = _parse_ruoli(prefix)
        if hasattr(perm, "utente_ids"):
            perm.utente_ids = _parse_utenti(prefix)
        perm.save()

    messages.success(request, "Permessi salvati.")
    return _helpers._redirect_impostazioni("permessi")


@login_required
@require_POST
def impostazioni_acl_role_grants_save(request):
    """Feature A — salva la matrice ruoli × permessi canonici del modulo.

    Write-through su ``core.RolePermissionGrant`` (le STESSE tabelle di
    ``/admin-portale/acl-canonico/``): editare da qui equivale a editare lì.
    Scope = solo i permessi ``module=anagrafica``. Un checkbox per cella con
    ``name="grant_<role_id>"`` e ``value=<permission_code>``.
    """
    ok, resp = _helpers._impostazioni_admin_check(request, "permessi")
    if not ok:
        return resp
    from core.models import PermissionDefinition
    from core.acl_v2 import apply_role_grants

    perms = list(PermissionDefinition.objects.filter(module="anagrafica", is_active=True))
    perm_codes = {p.code for p in perms}
    tot_created = tot_updated = 0
    for rid in Ruolo.objects.values_list("id", flat=True):
        selected = {c for c in request.POST.getlist(f"grant_{int(rid)}") if c in perm_codes}
        created, updated = apply_role_grants(int(rid), perms, selected)
        tot_created += created
        tot_updated += updated
    messages.success(
        request,
        f"Permessi canonici (ruoli) aggiornati: creati {tot_created}, modificati {tot_updated}.",
    )
    return _helpers._redirect_impostazioni("permessi")


@login_required
@require_POST
def impostazioni_acl_user_override_save(request):
    """Feature A — override per-utente sui permessi canonici del modulo.

    Write-through su ``core.UserPermissionGrant``. Azioni:
      - default: upsert override per l'utente scelto (``ov_allow`` / ``ov_deny``
        per permesso; permessi non citati → override rimosso = eredita dal ruolo);
      - ``action=delete``: rimuove tutti gli override anagrafica dell'utente.
    """
    ok, resp = _helpers._impostazioni_admin_check(request, "permessi")
    if not ok:
        return resp
    from core.models import PermissionDefinition
    from core.acl_v2 import apply_user_overrides

    perms = list(PermissionDefinition.objects.filter(module="anagrafica", is_active=True))
    perm_codes = {p.code for p in perms}
    uid_raw = (request.POST.get("legacy_user_id") or "").strip()
    if not uid_raw.isdigit():
        messages.error(request, "Utente non valido.")
        return _helpers._redirect_impostazioni("permessi")
    uid = int(uid_raw)

    if (request.POST.get("action") or "").strip() == "delete":
        apply_user_overrides(uid, perms, [], [])
        messages.success(request, f"Override utente #{uid} rimossi (eredita dai ruoli).")
        return _helpers._redirect_impostazioni("permessi")

    # Un radio per permesso: name="ov_<code>", value in inherit|allow|deny.
    allow, deny = [], []
    for p in perms:
        choice = (request.POST.get(f"ov_{p.code}") or "inherit").strip()
        if choice == "allow":
            allow.append(p.code)
        elif choice == "deny":
            deny.append(p.code)
    changed = apply_user_overrides(uid, perms, allow, deny)
    messages.success(request, f"Override utente #{uid} salvati: {changed} permessi.")
    return _helpers._redirect_impostazioni("permessi")


# ---------------------------------------------------------------------------
# CRUD subnav — categorie e link (da impostazioni)
# ---------------------------------------------------------------------------

@login_required
@require_POST
def subnav_categoria_create(request):
    ok, resp = _helpers._impostazioni_admin_check(request, "navigazione")
    if not ok:
        return resp
    nome = (request.POST.get("nome") or "").strip()[:80]
    icona = (request.POST.get("icona") or "").strip()[:20]
    ordine_raw = (request.POST.get("ordine") or "0").strip()
    if not nome:
        messages.error(request, "Il nome della categoria è obbligatorio.")
        return _helpers._redirect_impostazioni("navigazione")
    try:
        ordine = int(ordine_raw)
    except (ValueError, TypeError):
        ordine = 0
    landing_type = request.POST.get("landing_url_type") or "named"
    if landing_type not in ("named", "raw"):
        landing_type = "named"
    landing_value = (request.POST.get("landing_url_value") or "").strip()[:255]
    SubnavCategoriaAnagrafica.objects.create(
        nome=nome, icona=icona, ordine=ordine,
        landing_url_type=landing_type, landing_url_value=landing_value,
    )
    messages.success(request, f"Categoria «{nome}» creata.")
    return _helpers._redirect_impostazioni("navigazione")


@login_required
@require_POST
def subnav_categoria_edit(request, cat_id: int):
    ok, resp = _helpers._impostazioni_admin_check(request, "navigazione")
    if not ok:
        return resp
    cat = get_object_or_404(SubnavCategoriaAnagrafica, pk=cat_id)
    cat.nome = (request.POST.get("nome") or "").strip()[:80] or cat.nome
    cat.icona = (request.POST.get("icona") or "").strip()[:20]
    cat.is_active = request.POST.get("is_active") == "1"
    try:
        cat.ordine = int(request.POST.get("ordine") or cat.ordine)
    except (ValueError, TypeError):
        pass
    landing_type = request.POST.get("landing_url_type") or cat.landing_url_type
    if landing_type in ("named", "raw"):
        cat.landing_url_type = landing_type
    cat.landing_url_value = (request.POST.get("landing_url_value") or "").strip()[:255]
    cat.save()
    messages.success(request, f"Categoria «{cat.nome}» aggiornata.")
    return _helpers._redirect_impostazioni("navigazione")


@login_required
@require_POST
def subnav_categoria_delete(request, cat_id: int):
    ok, resp = _helpers._impostazioni_admin_check(request, "navigazione")
    if not ok:
        return resp
    cat = get_object_or_404(SubnavCategoriaAnagrafica, pk=cat_id)
    n_links = cat.links.count()
    if n_links > 0:
        messages.error(request, f"Impossibile eliminare: la categoria contiene {n_links} link/s. Spostarli o eliminarli prima.")
        return _helpers._redirect_impostazioni("navigazione")
    nome = cat.nome
    cat.delete()
    messages.success(request, f"Categoria «{nome}» eliminata.")
    return _helpers._redirect_impostazioni("navigazione")


@login_required
@require_POST
def subnav_link_create(request):
    ok, resp = _helpers._impostazioni_admin_check(request, "navigazione")
    if not ok:
        return resp
    etichetta = (request.POST.get("etichetta") or "").strip()[:80]
    icona = (request.POST.get("icona") or "").strip()[:20]
    gruppo = (request.POST.get("gruppo") or "").strip()[:40]
    url_type = request.POST.get("url_type") or "raw"
    if url_type not in ("named", "raw"):
        url_type = "raw"
    url_value = (request.POST.get("url_value") or "").strip()[:255]
    cat_id_raw = (request.POST.get("categoria_id") or "").strip()
    apri_nuova_tab = request.POST.get("apri_nuova_tab") == "1"
    try:
        ordine = int(request.POST.get("ordine") or 0)
    except (ValueError, TypeError):
        ordine = 0
    if not etichetta or not url_value:
        messages.error(request, "Etichetta e URL sono obbligatori.")
        return _helpers._redirect_impostazioni("navigazione")
    cat = None
    if cat_id_raw:
        cat = SubnavCategoriaAnagrafica.objects.filter(pk=cat_id_raw).first()
    SubnavLinkAnagrafica.objects.create(
        etichetta=etichetta, icona=icona, gruppo=gruppo, url_type=url_type, url_value=url_value,
        categoria=cat, apri_nuova_tab=apri_nuova_tab, ordine=ordine, is_sistema=False,
    )
    messages.success(request, f"Link «{etichetta}» aggiunto.")
    return _helpers._redirect_impostazioni("navigazione")


@login_required
@require_POST
def subnav_link_edit(request, link_id: int):
    ok, resp = _helpers._impostazioni_admin_check(request, "navigazione")
    if not ok:
        return resp
    link = get_object_or_404(SubnavLinkAnagrafica, pk=link_id)
    link.etichetta = (request.POST.get("etichetta") or "").strip()[:80] or link.etichetta
    link.icona = (request.POST.get("icona") or "").strip()[:20]
    link.gruppo = (request.POST.get("gruppo") or "").strip()[:40]
    link.is_active = request.POST.get("is_active") == "1"
    link.apri_nuova_tab = request.POST.get("apri_nuova_tab") == "1"
    try:
        link.ordine = int(request.POST.get("ordine") or link.ordine)
    except (ValueError, TypeError):
        pass
    cat_id_raw = (request.POST.get("categoria_id") or "").strip()
    if cat_id_raw:
        link.categoria = SubnavCategoriaAnagrafica.objects.filter(pk=cat_id_raw).first()
    else:
        link.categoria = None
    # Per link non di sistema permetti anche di cambiare URL
    if not link.is_sistema:
        url_type = request.POST.get("url_type") or link.url_type
        if url_type in ("named", "raw"):
            link.url_type = url_type
        url_value = (request.POST.get("url_value") or "").strip()[:255]
        if url_value:
            link.url_value = url_value
    link.save()
    messages.success(request, f"Link «{link.etichetta}» aggiornato.")
    return _helpers._redirect_impostazioni("navigazione")


@login_required
@require_POST
def subnav_link_delete(request, link_id: int):
    ok, resp = _helpers._impostazioni_admin_check(request, "navigazione")
    if not ok:
        return resp
    link = get_object_or_404(SubnavLinkAnagrafica, pk=link_id)
    if link.is_sistema:
        messages.error(request, "I link di sistema non possono essere eliminati. Puoi disattivarli.")
        return _helpers._redirect_impostazioni("navigazione")
    nome = link.etichetta
    link.delete()
    messages.success(request, f"Link «{nome}» eliminato.")
    return _helpers._redirect_impostazioni("navigazione")


@login_required
def dipendente_dpi_iniziali_proposti(request):
    """Partial HTMX: lista righe DPI iniziali in base ai ruoli operativi scelti.

    Accetta ``ruoli_operativi_ids`` (multi-value) via GET. Ritorna l'HTML
    parziale ``_dpi_iniziali_righe.html`` con il formset pre-compilato.
    """
    ruoli_raw = request.GET.getlist("ruoli_operativi_ids")
    ruoli_ids: list[int] = []
    for raw in ruoli_raw:
        try:
            ruoli_ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    righe = proposta_righe_iniziali(ruoli_ids)
    return render(
        request,
        "anagrafica/partials/_dpi_iniziali_righe.html",
        {"righe": righe, "indici": list(range(len(righe)))},
    )
