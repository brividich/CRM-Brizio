"""Viste della sezione Sistema di gestione (fase 1: Dichiarazione di applicabilità e threat intelligence).

Autorizzazione server-side: binding ACL delle route (middleware) più controllo
esplicito del permesso in ogni view, fail-closed. Modifica solo in bozza,
approvazione solo con il permesso dedicato. Ogni transizione finisce nell'AuditLog.
"""
from __future__ import annotations

import logging
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_action

from .acl_bootstrap import PERM_AUDIT_VIEW, PERM_SOA_APPROVA, PERM_SOA_EDIT, PERM_SOA_VIEW, PERM_VIEW
from .catalogo_27002 import TEMI
from .evidenze import evidenze_per
from .exports import kpi_revisione, soa_pdf, soa_xlsx
from .forms import CopiaFirmataForm, SoaVoceForm, ThreatIntelligenceForm
from .models import Audit, SoaRevisione, SoaVoce, ThreatIntelligence
from .services import soa as soa_service

logger = logging.getLogger(__name__)
MODULE = "sistema_gestione"


def _has_perm(request, code: str) -> bool:
    try:
        from core.acl_v2 import evaluate_permission_code_access
        from core.legacy_utils import get_legacy_user

        legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
        return bool(evaluate_permission_code_access(
            permission_code=code, legacy_user=legacy_user, django_user=request.user,
        ).get("allowed"))
    except Exception:
        logger.warning("sistema_gestione: valutazione permesso %s fallita", code, exc_info=True)
        return bool(getattr(request, "user", None) and request.user.is_superuser)


def _nega(request, testo: str = "Non hai i permessi per questa operazione."):
    messages.error(request, testo)
    return redirect("sistema_gestione:index" if _has_perm(request, PERM_VIEW) else "dashboard:dashboard")


# ---------------------------------------------------------------------------
# Hub
# ---------------------------------------------------------------------------

@login_required
def index(request):
    if not _has_perm(request, PERM_VIEW):
        return _nega(request, "Non hai accesso al Sistema di gestione.")
    puo_soa = _has_perm(request, PERM_SOA_VIEW)
    puo_audit = _has_perm(request, PERM_AUDIT_VIEW)
    in_vigore = soa_service.revisione_in_vigore() if puo_soa else None
    di_lavoro = soa_service.revisione_di_lavoro() if puo_soa else None
    ti_anno = (
        ThreatIntelligence.objects.filter(data__gte=timezone.localdate().replace(month=1, day=1)).count()
        if puo_soa else 0
    )
    return render(request, "sistema_gestione/pages/index.html", {
        "page_title": "Sistema di gestione",
        "puo_soa": puo_soa,
        "puo_audit": puo_audit,
        "in_vigore": in_vigore,
        "di_lavoro": di_lavoro,
        "kpi_in_vigore": kpi_revisione(in_vigore) if in_vigore else [],
        "ti_anno": ti_anno,
        "audit_anno": Audit.objects.filter(data_inizio__year=timezone.localdate().year).count() if puo_audit else 0,
    })


# ---------------------------------------------------------------------------
# Dichiarazione di applicabilità
# ---------------------------------------------------------------------------

@login_required
def soa(request):
    if not _has_perm(request, PERM_SOA_VIEW):
        return _nega(request)
    di_lavoro = soa_service.revisione_di_lavoro()
    in_vigore = soa_service.revisione_in_vigore()
    if di_lavoro and _has_perm(request, PERM_SOA_EDIT):
        return redirect("sistema_gestione:soa_revisione", numero=di_lavoro.numero)
    if in_vigore:
        return redirect("sistema_gestione:soa_revisione", numero=in_vigore.numero)
    if di_lavoro:
        return redirect("sistema_gestione:soa_revisione", numero=di_lavoro.numero)
    return render(request, "sistema_gestione/pages/soa_vuota.html", {
        "page_title": "Dichiarazione di applicabilità",
        "puo_modificare": _has_perm(request, PERM_SOA_EDIT),
    })


@login_required
def soa_revisione(request, numero: int):
    if not _has_perm(request, PERM_SOA_VIEW):
        return _nega(request)
    revisione = get_object_or_404(SoaRevisione.objects.select_related("preparata_da", "approvata_da"), numero=numero)
    formato = (request.GET.get("formato") or "").strip().lower()
    if formato in {"pdf", "xlsx"}:
        log_action(request, "soa_download", MODULE, {"revisione": revisione.numero, "formato": formato},
                   oggetto=revisione)
        if formato == "pdf":
            body, ctype = soa_pdf(revisione), "application/pdf"
        else:
            body, ctype = soa_xlsx(revisione), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        response = HttpResponse(body, content_type=ctype)
        response["Content-Disposition"] = f'attachment; filename="SoA_MOD165_Rev{revisione.numero}.{formato}"'
        return response

    tema = request.GET.get("tema", "")
    filtro = request.GET.get("filtro", "")
    voci = list(revisione.voci.select_related("controllo", "ofi"))
    precedente = SoaRevisione.objects.filter(numero__lt=revisione.numero).order_by("-numero").first()
    cambi = soa_service.differenze(revisione, precedente)
    oggi = timezone.localdate()
    righe = []
    for voce in voci:
        if tema and voce.controllo.tema != tema:
            continue
        if filtro == "parziali" and not (0 < voce.livello < 4):
            continue
        if filtro == "esclusi" and voce.livello != 0:
            continue
        if filtro == "azioni" and not voce.ha_azione_aperta:
            continue
        if filtro == "modificati" and voce.controllo_id not in cambi:
            continue
        righe.append({
            "voce": voce,
            "evidenze": evidenze_per(voce.controllo.codice),
            "cambi": cambi.get(voce.controllo_id, []),
            "scaduta": voce.azione_scaduta(oggi),
        })

    puo_modificare = _has_perm(request, PERM_SOA_EDIT)
    return render(request, "sistema_gestione/pages/soa_revisione.html", {
        "page_title": f"Dichiarazione di applicabilità - Rev.{revisione.numero}",
        "revisione": revisione,
        "precedente": precedente,
        "revisioni": SoaRevisione.objects.order_by("-numero"),
        "righe": righe,
        "kpis": kpi_revisione(revisione, oggi),
        "temi": TEMI,
        "tema": tema,
        "filtro": filtro,
        "n_cambi": len(cambi),
        "puo_modificare": puo_modificare and revisione.modificabile,
        "puo_proporre": puo_modificare and revisione.stato == SoaRevisione.STATO_BOZZA,
        "puo_riportare": puo_modificare and revisione.stato == SoaRevisione.STATO_PROPOSTA,
        "puo_approvare": _has_perm(request, PERM_SOA_APPROVA) and revisione.stato == SoaRevisione.STATO_PROPOSTA,
        "puo_nuova": puo_modificare and soa_service.revisione_di_lavoro() is None,
        "puo_caricare_firmata": puo_modificare and revisione.stato in (SoaRevisione.STATO_APPROVATA, SoaRevisione.STATO_SUPERATA),
        "form_firmata": CopiaFirmataForm(),
    })


@login_required
def soa_voce(request, pk: int):
    if not _has_perm(request, PERM_SOA_EDIT):
        return _nega(request)
    voce = get_object_or_404(SoaVoce.objects.select_related("revisione", "controllo"), pk=pk)
    if not voce.revisione.modificabile:
        messages.error(request, "La revisione non è in bozza: non si può modificare. Apri una nuova revisione.")
        return redirect("sistema_gestione:soa_revisione", numero=voce.revisione.numero)
    form = SoaVoceForm(request.POST or None, instance=voce)
    if request.method == "POST" and form.is_valid():
        voce = form.save(commit=False)
        voce.aggiornata_da = request.user
        voce.save()
        log_action(request, "soa_voce_modificata", MODULE,
                   {"revisione": voce.revisione.numero, "controllo": voce.controllo.codice,
                    "campi": sorted(form.changed_data)}, oggetto=voce)
        messages.success(request, f"Controllo {voce.controllo.codice} aggiornato.")
        return redirect(f"{_url_revisione(voce.revisione.numero)}#c-{voce.controllo.codice}")
    return render(request, "sistema_gestione/pages/soa_voce.html", {
        "page_title": f"Controllo {voce.controllo.codice}",
        "voce": voce,
        "form": form,
        "evidenze": evidenze_per(voce.controllo.codice),
        "suggerimento_vulnerabilita": SoaVoce.VULNERABILITA_DA_LIVELLO,
    })


def _url_revisione(numero: int) -> str:
    from django.urls import reverse

    return reverse("sistema_gestione:soa_revisione", kwargs={"numero": numero})


@login_required
@require_POST
def soa_nuova_revisione(request):
    if not _has_perm(request, PERM_SOA_EDIT):
        return _nega(request)
    motivo = (request.POST.get("motivo") or "").strip()[:255]
    try:
        revisione = soa_service.nuova_revisione(utente=request.user, motivo=motivo)
    except soa_service.TransizioneNonAmmessa as exc:
        messages.error(request, str(exc))
        return redirect("sistema_gestione:soa")
    log_action(request, "soa_revisione_creata", MODULE, {"revisione": revisione.numero, "motivo": motivo},
               oggetto=revisione)
    messages.success(request, f"Aperta la revisione {revisione.numero} in bozza, copia della precedente.")
    return redirect("sistema_gestione:soa_revisione", numero=revisione.numero)


def _transizione(request, numero: int, *, perm: str, azione, evento: str, successo: str):
    if not _has_perm(request, perm):
        return _nega(request)
    revisione = get_object_or_404(SoaRevisione, numero=numero)
    try:
        azione(revisione)
    except soa_service.TransizioneNonAmmessa as exc:
        messages.error(request, str(exc))
    else:
        log_action(request, evento, MODULE, {"revisione": revisione.numero, "stato": revisione.stato}, oggetto=revisione)
        messages.success(request, successo)
    return redirect("sistema_gestione:soa_revisione", numero=revisione.numero)


@login_required
@require_POST
def soa_proponi(request, numero: int):
    return _transizione(
        request, numero, perm=PERM_SOA_EDIT, evento="soa_revisione_proposta",
        azione=lambda r: soa_service.proponi(r, utente=request.user),
        successo="Revisione proposta alla Direzione per l'approvazione.",
    )


@login_required
@require_POST
def soa_riporta_in_bozza(request, numero: int):
    return _transizione(
        request, numero, perm=PERM_SOA_EDIT, evento="soa_revisione_riportata_in_bozza",
        azione=soa_service.riporta_in_bozza, successo="Revisione riportata in bozza.",
    )


@login_required
@require_POST
def soa_approva(request, numero: int):
    return _transizione(
        request, numero, perm=PERM_SOA_APPROVA, evento="soa_revisione_approvata",
        azione=lambda r: soa_service.approva(r, utente=request.user),
        successo="Revisione approvata: è la Dichiarazione di applicabilità in vigore.",
    )


@login_required
@require_POST
def soa_carica_firmata(request, numero: int):
    if not _has_perm(request, PERM_SOA_EDIT):
        return _nega(request)
    revisione = get_object_or_404(SoaRevisione, numero=numero)
    if revisione.stato not in (SoaRevisione.STATO_APPROVATA, SoaRevisione.STATO_SUPERATA):
        messages.error(request, "La copia firmata si carica dopo l'approvazione.")
        return redirect("sistema_gestione:soa_revisione", numero=numero)
    form = CopiaFirmataForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, " ".join(form.errors.get("file", ["File non valido."])))
        return redirect("sistema_gestione:soa_revisione", numero=numero)
    caricato = form.cleaned_data["file"]
    revisione.copia_firmata.save(f"SoA_Rev{revisione.numero}_firmata.pdf", caricato, save=False)
    revisione.copia_firmata_nome = Path(caricato.name).name[:255]
    revisione.copia_firmata_caricata_il = timezone.now()
    revisione.save(update_fields=["copia_firmata", "copia_firmata_nome", "copia_firmata_caricata_il", "updated_at"])
    log_action(request, "soa_copia_firmata_caricata", MODULE, {"revisione": revisione.numero}, oggetto=revisione)
    messages.success(request, "Copia firmata caricata.")
    return redirect("sistema_gestione:soa_revisione", numero=numero)


@login_required
def soa_copia_firmata(request, numero: int):
    if not _has_perm(request, PERM_SOA_VIEW):
        return _nega(request)
    revisione = get_object_or_404(SoaRevisione, numero=numero)
    if not revisione.copia_firmata:
        raise Http404("Copia firmata non presente.")
    try:
        fh = revisione.copia_firmata.open("rb")
    except Exception as exc:
        raise Http404("File non trovato.") from exc
    log_action(request, "soa_copia_firmata_scaricata", MODULE, {"revisione": revisione.numero}, oggetto=revisione)
    response = FileResponse(fh, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="SoA_Rev{revisione.numero}_firmata.pdf"'
    response["X-Content-Type-Options"] = "nosniff"
    return response


# ---------------------------------------------------------------------------
# Threat intelligence
# ---------------------------------------------------------------------------

@login_required
def threat_intelligence(request):
    if not _has_perm(request, PERM_SOA_VIEW):
        return _nega(request)
    oggi = timezone.localdate()
    try:
        anno = int(request.GET.get("anno") or oggi.year)
    except ValueError:
        anno = oggi.year
    voci = ThreatIntelligence.objects.filter(data__year=anno).select_related("ofi", "registrato_da")
    anni = sorted({d.year for d in ThreatIntelligence.objects.dates("data", "year")} | {oggi.year}, reverse=True)
    return render(request, "sistema_gestione/pages/threat_intelligence.html", {
        "page_title": "Registro threat intelligence",
        "voci": voci,
        "anno": anno,
        "anni": anni,
        "puo_registrare": _has_perm(request, PERM_SOA_EDIT),
    })


@login_required
def threat_intelligence_nuova(request):
    if not _has_perm(request, PERM_SOA_EDIT):
        return _nega(request)
    form = ThreatIntelligenceForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        voce = form.save(commit=False)
        voce.registrato_da = request.user
        voce.save()
        log_action(request, "threat_intelligence_registrata", MODULE, {"fonte": voce.fonte, "esito": voce.esito},
                   oggetto=voce)
        messages.success(request, "Attività registrata.")
        return redirect("sistema_gestione:threat_intelligence")
    return render(request, "sistema_gestione/pages/threat_intelligence_form.html", {
        "page_title": "Nuova attività di threat intelligence",
        "form": form,
    })
