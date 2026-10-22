"""Mansioni di rischio: catalogo, form con anteprima, organigramma, scheda dipendente.

Cancelli (verificati server-side all'inizio di ogni view, letti anche dalla
subnav via ``subnav_gates``):

- catalogo e organigramma: amministrazione anagrafica o dati HR;
- modifica di mansioni di rischio e configurazione: amministrazione anagrafica;
- override individuali e deroghe: amministrazione anagrafica **e** permesso
  visite mediche (decisione 10/10/2026: toccano la sorveglianza sanitaria);
- pannello della scheda: chi apre la scheda; i motivi dello stato operativo e
  il protocollo sanitario solo con il permesso visite.
"""
from __future__ import annotations

import logging
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_action

from .models import FattoreRischio, Mansione
from .models_mansioni_rischio import (
    ConfigSicurezzaOperativa, DerogaOperativaVisita, DipendenteMansioneRischioOverride,
)

logger = logging.getLogger(__name__)
MODULE = "anagrafica"


def _puo_vedere(request) -> bool:
    from .views import _check_hr_permission, _is_anagrafica_admin
    return _is_anagrafica_admin(request) or _check_hr_permission(request)


def _puo_gestire(request) -> bool:
    from .views import _is_anagrafica_admin
    return _is_anagrafica_admin(request)


def _puo_sorveglianza(request) -> bool:
    from .views import _can_view_visite_mediche, _is_anagrafica_admin
    return _is_anagrafica_admin(request) and _can_view_visite_mediche(request)


def _nega(request, testo="Non hai i permessi per questa pagina."):
    messages.error(request, testo)
    return redirect("anagrafica:index")


def _data(valore) -> date | None:
    try:
        return date.fromisoformat((valore or "").strip()) if (valore or "").strip() else None
    except ValueError:
        return None


# ═══════════════════════════════════════════════════════════════════════════
# Catalogo
# ═══════════════════════════════════════════════════════════════════════════

# Decisione 15/10/2026 (spec Mansionario): il catalogo delle mansioni di rischio
# è ``Mansione``. Il vecchio catalogo separato è stato assorbito (fase 6); i suoi
# indirizzi restano e rimandano al catalogo, per i collegamenti salvati.
_AVVISO_CATALOGO = ("Le mansioni di rischio sono il catalogo «Mansioni di rischio»: "
                    "DPI, visite e schede di sicurezza si gestiscono dai requisiti di ogni voce.")


def _al_catalogo(request):
    messages.info(request, _AVVISO_CATALOGO)
    return redirect("anagrafica:mansioni_list")


@login_required
def mansioni_rischio_list(request):
    if not _puo_vedere(request):
        return _nega(request)
    return _al_catalogo(request)


@login_required
def mansione_rischio_dettaglio(request, mr_id: int):
    if not _puo_vedere(request):
        return _nega(request)
    return _al_catalogo(request)


@login_required
def mansione_rischio_form(request, mr_id: int | None = None):
    """Crea/modifica. ``azione=anteprima`` calcola l'effetto senza salvare."""
    if not _puo_gestire(request):
        return _nega(request, "Non hai i permessi per modificare le mansioni di rischio.")
    return _al_catalogo(request)


@login_required
@require_POST
def sicurezza_operativa_config(request):
    if not _puo_gestire(request):
        return _nega(request)
    config = ConfigSicurezzaOperativa.load()
    modalita = request.POST.get("modalita_visita_mancante")
    if modalita in dict(ConfigSicurezzaOperativa.MODALITA_CHOICES):
        config.modalita_visita_mancante = modalita
    try:
        config.deroga_max_giorni = max(1, min(365, int(request.POST.get("deroga_max_giorni") or 30)))
    except ValueError:
        pass
    config.aggiornata_da = request.user
    config.save()
    log_action(request, "sicurezza_operativa_config", MODULE, {
        "modalita": config.modalita_visita_mancante, "deroga_max_giorni": config.deroga_max_giorni,
    }, oggetto=config)
    messages.success(request, f"Visita del cambio mansione mancante: «{config.get_modalita_visita_mancante_display()}».")
    return redirect("anagrafica:mansioni_list")


# ═══════════════════════════════════════════════════════════════════════════
# Organigramma per mansione di rischio
# ═══════════════════════════════════════════════════════════════════════════

def _senza_mansione() -> int:
    """Dipendenti attivi senza mansione di rischio in anagrafica (non compaiono nei gruppi)."""
    from core.legacy_anagrafica import fetch_anagrafica_rows
    return sum(1 for r in fetch_anagrafica_rows(deduplicate=True)
               if r.get("attivo", True) and not str(r.get("mansione") or "").strip())


@login_required
def organigramma_mansioni_rischio(request):
    if not _puo_vedere(request):
        return _nega(request)
    from .services.organigramma_rischio import costruisci
    from .views import _can_view_visite_mediche

    fattore_id = int(request.GET["fattore"]) if (request.GET.get("fattore") or "").isdigit() else None
    gruppi = costruisci(fattore_id=fattore_id, can_view_visite=_can_view_visite_mediche(request))
    return render(request, "anagrafica/pages/organigramma_mansioni_rischio.html", {
        "page_title": "Organigramma per mansione di rischio",
        "gruppi": gruppi,
        "senza_mansione": _senza_mansione(),
        "fattori_opts": list(FattoreRischio.objects.filter(is_active=True).order_by("nome")),
        "fattore_id": fattore_id,
        "can_view_visite": _can_view_visite_mediche(request),
    })


# ═══════════════════════════════════════════════════════════════════════════
# Scheda dipendente: pannello, override, deroghe
# ═══════════════════════════════════════════════════════════════════════════

@login_required
def dipendente_sicurezza_panel(request, legacy_id: int):
    """Mansioni di rischio effettive, stato operativo e timeline (HTMX lazy-load)."""
    from .services import eventi_sicurezza, mansionario, stato_operativo
    from .views import _can_view_visite_mediche

    can_view_visite = _can_view_visite_mediche(request)
    det = mansionario.requisiti_dipendente_dettaglio(legacy_id)
    stato = stato_operativo.stato_persona([legacy_id])
    stato.etichetta_mostrata = stato.etichetta_visibile(can_view_visite)
    # Idoneità con prescrizioni/limitazioni sulle visite correnti, da leggere
    # rispetto alla mansione attuale: solo con il permesso visite.
    idoneita_condizionate = []
    if can_view_visite:
        from .models import VisitaMedica
        from .services.visite import ultime_visite_correnti_ids
        condizionati = ("IDONEO_MANS", "IDONEO_PRESCR", "IDONEO_LIM", "IDONEO_LIM_PRESCR")
        idoneita_condizionate = list(
            VisitaMedica.objects.filter(pk__in=list(ultime_visite_correnti_ids([legacy_id])), esito__in=condizionati)
            .select_related("tipo").order_by("-data_svolgimento")
        )
    override = list(DipendenteMansioneRischioOverride.objects.filter(legacy_anagrafica_id=legacy_id)
                    .select_related("mansione_rischio", "created_by", "revocato_da")
                    .order_by("-attivo", "-created_at")[:30])
    nome_mansione = (det.get("mansione_nome") or "").strip()
    from .services.mansionario import mansione_per_nome

    mansione_catalogo = mansione_per_nome(nome_mansione)
    return render(request, "anagrafica/partials/sicurezza_panel.html", {
        "legacy_id": legacy_id,
        "det": det,
        "mansione_catalogo": mansione_catalogo,
        "stato": stato,
        "motivi": stato.motivi_visibili(can_view_visite),
        "can_view_visite": can_view_visite,
        "idoneita_condizionate": idoneita_condizionate,
        "puo_sorveglianza": _puo_sorveglianza(request),
        "override": override,
        "deroghe": list(DerogaOperativaVisita.objects.filter(legacy_anagrafica_id=legacy_id).order_by("-autorizzato_il")[:10]),
        "config": ConfigSicurezzaOperativa.load(),
        "mansioni_rischio_opts": list(Mansione.objects.filter(is_active=True).order_by("nome")),
        "timeline": eventi_sicurezza.timeline([legacy_id], limite=40),
        "oggi": timezone.localdate(),
    })


def _torna(legacy_id):
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


def _dipendente_esiste(legacy_id: int) -> bool:
    from core.legacy_anagrafica import fetch_anagrafica_rows
    return bool(fetch_anagrafica_rows(ids=[legacy_id]))


@login_required
@require_POST
def dipendente_override_aggiungi(request, legacy_id: int):
    if not _puo_sorveglianza(request):
        messages.error(request, "Servono amministrazione anagrafica e permesso visite mediche.")
        return _torna(legacy_id)
    from .services import riallineamento

    if not _dipendente_esiste(legacy_id):
        messages.error(request, "Dipendente non trovato.")
        return redirect("anagrafica:dipendenti_list")
    mr = Mansione.objects.filter(pk=request.POST.get("mansione_rischio") or 0, is_active=True).first()
    if mr is None:
        messages.error(request, "Mansione di rischio non valida.")
        return _torna(legacy_id)
    try:
        override, esito = riallineamento.aggiungi_override(
            legacy_id, mr, azione=request.POST.get("azione"), motivo=request.POST.get("motivo"),
            data_inizio=_data(request.POST.get("data_inizio")) or timezone.localdate(),
            data_fine=_data(request.POST.get("data_fine")), user=request.user, request=request,
        )
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return _torna(legacy_id)
    messages.success(request, f"{override.get_azione_display()} registrata: {esito.get('creati', 0)} nuovi adempimenti, "
                              f"{esito.get('non_piu_dovuti', 0)} non più dovuti.")
    return _torna(legacy_id)


@login_required
@require_POST
def dipendente_override_revoca(request, legacy_id: int, override_id: int):
    if not _puo_sorveglianza(request):
        messages.error(request, "Servono amministrazione anagrafica e permesso visite mediche.")
        return _torna(legacy_id)
    from .services import riallineamento

    override = get_object_or_404(DipendenteMansioneRischioOverride, pk=override_id, legacy_anagrafica_id=legacy_id)
    try:
        riallineamento.revoca_override(override, motivo=request.POST.get("motivo"), user=request.user, request=request)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return _torna(legacy_id)
    messages.success(request, "Override revocato.")
    return _torna(legacy_id)


@login_required
@require_POST
def dipendente_deroga_aggiungi(request, legacy_id: int):
    if not _puo_sorveglianza(request):
        messages.error(request, "Servono amministrazione anagrafica e permesso visite mediche.")
        return _torna(legacy_id)
    from .services import stato_operativo

    if not _dipendente_esiste(legacy_id):
        messages.error(request, "Dipendente non trovato.")
        return redirect("anagrafica:dipendenti_list")
    stato = stato_operativo.stato_persona([legacy_id])
    if stato_operativo.MOTIVO_VISITA_MANCANTE not in stato.motivi:
        messages.error(request, "Nessuna visita del cambio mansione mancante: la deroga non serve.")
        return _torna(legacy_id)
    valida_fino = _data(request.POST.get("valida_fino"))
    if valida_fino is None:
        messages.error(request, "Indica fino a quando vale la deroga.")
        return _torna(legacy_id)
    try:
        from .models import AdempimentoCambioMansione
        adempimento = AdempimentoCambioMansione.objects.filter(pk__in=stato.adempimenti_ids).order_by("entro_il").first()
        stato_operativo.concedi_deroga(legacy_id, motivo=request.POST.get("motivo"), valida_fino=valida_fino,
                                       user=request.user, request=request, adempimento=adempimento)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return _torna(legacy_id)
    messages.success(request, f"Deroga concessa fino al {valida_fino:%d/%m/%Y}.")
    return _torna(legacy_id)


@login_required
@require_POST
def dipendente_deroga_revoca(request, legacy_id: int, deroga_id: int):
    if not _puo_sorveglianza(request):
        messages.error(request, "Servono amministrazione anagrafica e permesso visite mediche.")
        return _torna(legacy_id)
    from .services import stato_operativo

    deroga = get_object_or_404(DerogaOperativaVisita, pk=deroga_id, legacy_anagrafica_id=legacy_id, attivo=True)
    stato_operativo.revoca_deroga(deroga, motivo=request.POST.get("motivo") or "", user=request.user, request=request)
    messages.success(request, "Deroga revocata.")
    return _torna(legacy_id)
