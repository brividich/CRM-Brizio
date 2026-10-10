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
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_action

from .models import FattoreRischio, Mansione, TipoVisitaMedica
from .models_mansioni_rischio import (
    ConfigSicurezzaOperativa, DerogaOperativaVisita, DipendenteMansioneRischioOverride, MansioneRischio,
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


def _ids(request, nome) -> list[int]:
    return [int(v) for v in request.POST.getlist(nome) if str(v).isdigit()]


# ═══════════════════════════════════════════════════════════════════════════
# Catalogo
# ═══════════════════════════════════════════════════════════════════════════

@login_required
def mansioni_rischio_list(request):
    if not _puo_vedere(request):
        return _nega(request)
    q = (request.GET.get("q") or "").strip()
    qs = MansioneRischio.objects.prefetch_related("fattori", "link_mansioni__mansione").order_by("-is_active", "codice")
    if q:
        from django.db.models import Q
        qs = qs.filter(Q(nome__icontains=q) | Q(codice__icontains=q))
    return render(request, "anagrafica/pages/mansioni_rischio_list.html", {
        "page_title": "Mansioni di rischio",
        "mansioni_rischio": list(qs),
        "q": q,
        "config": ConfigSicurezzaOperativa.load(),
        "is_admin": _puo_gestire(request),
        "n_senza_collegamento": Mansione.objects.filter(is_active=True, link_rischio__isnull=True).count(),
    })


@login_required
def mansione_rischio_dettaglio(request, mr_id: int):
    if not _puo_vedere(request):
        return _nega(request)
    from .services import mansionario
    from .services.mansioni_rischio_admin import esposti
    from .views import _can_view_visite_mediche

    mr = get_object_or_404(MansioneRischio.objects.prefetch_related("fattori", "visite", "categorie_dpi"), pk=mr_id)
    return render(request, "anagrafica/pages/mansione_rischio_dettaglio.html", {
        "page_title": mr.nome,
        "mr": mr,
        "requisiti": mansionario.requisiti_mansioni_rischio([mr.pk]).get(mr.pk) or mansionario.requisiti_vuoti(),
        "collegamenti": list(mr.link_mansioni.select_related("mansione").order_by("mansione__nome")),
        "esposti": esposti(mr),
        "override": list(mr.override_dipendenti.filter(attivo=True).order_by("legacy_anagrafica_id")),
        "is_admin": _puo_gestire(request),
        "can_view_visite": _can_view_visite_mediche(request),
    })


def _cataloghi() -> dict:
    from django.db.models import Case, When
    out = {
        "fattori_opts": list(FattoreRischio.objects.filter(is_active=True).order_by("categoria", "nome")),
        "visite_opts": list(TipoVisitaMedica.objects.filter(is_active=True)
                            .order_by(Case(When(categoria="", then=1), default=0), "categoria", "nome")),
        "mansioni_opts": list(Mansione.objects.filter(is_active=True).order_by("nome")),
        "livello_choices": MansioneRischio.LIVELLO_CHOICES,
        "dpi_opts": [],
    }
    try:
        from dpi.models import CategoriaDPI
        out["dpi_opts"] = list(CategoriaDPI.objects.filter(is_active=True).order_by("order_index", "nome"))
    except Exception:
        pass
    return out


def _dati_da_post(request):
    from .services.mansioni_rischio_admin import Dati
    return Dati(
        codice=(request.POST.get("codice") or "").strip()[:20],
        nome=(request.POST.get("nome") or "").strip()[:150],
        descrizione=(request.POST.get("descrizione") or "").strip(),
        livello_rischio_dvr=(request.POST.get("livello_rischio_dvr") or "").strip()[:1],
        dvr_revisione=(request.POST.get("dvr_revisione") or "").strip()[:30],
        dvr_data=_data(request.POST.get("dvr_data")),
        is_active=request.POST.get("is_active") == "on",
        fattori=_ids(request, "fattori"), visite=_ids(request, "visite"),
        categorie_dpi=_ids(request, "categorie_dpi"), mansioni=_ids(request, "mansioni"),
    )


def _dati_da_istanza(mr):
    from .services.mansioni_rischio_admin import Dati
    if mr.pk is None:
        return Dati(codice="", nome="", is_active=True)
    return Dati(
        codice=mr.codice, nome=mr.nome, descrizione=mr.descrizione, livello_rischio_dvr=mr.livello_rischio_dvr,
        dvr_revisione=mr.dvr_revisione, dvr_data=mr.dvr_data, is_active=mr.is_active,
        fattori=list(mr.fattori.values_list("pk", flat=True)), visite=list(mr.visite.values_list("pk", flat=True)),
        categorie_dpi=list(mr.categorie_dpi.values_list("pk", flat=True)),
        mansioni=list(mr.link_mansioni.values_list("mansione_id", flat=True)),
    )


@login_required
def mansione_rischio_form(request, mr_id: int | None = None):
    """Crea/modifica. ``azione=anteprima`` calcola l'effetto senza salvare."""
    if not _puo_gestire(request):
        return _nega(request, "Non hai i permessi per modificare le mansioni di rischio.")
    from .services import mansioni_rischio_admin as admin_svc

    mr = get_object_or_404(MansioneRischio, pk=mr_id) if mr_id else MansioneRischio()
    # Il protocollo sanitario (tipi di visita) si modifica solo con il permesso
    # visite: senza, il form lo mostra in sola lettura e il server lo conserva.
    puo_protocollo = _puo_sorveglianza(request)
    dati, effetto, errori = _dati_da_istanza(mr), None, []
    if request.method == "POST":
        visite_attuali = list(mr.visite.values_list("pk", flat=True)) if mr.pk else []
        dati = _dati_da_post(request)
        if not puo_protocollo:
            dati.visite = visite_attuali
        if not dati.codice or not dati.nome:
            errori.append("Codice e nome sono obbligatori.")
        elif MansioneRischio.objects.filter(codice=dati.codice).exclude(pk=mr.pk).exists():
            errori.append(f"Il codice «{dati.codice}» è già usato.")
        if not errori:
            try:
                if request.POST.get("azione") == "anteprima":
                    effetto = admin_svc.anteprima(mr, dati)
                else:
                    mr, nuova = admin_svc.salva(mr, dati, user=request.user)
                    log_action(request, "mansione_rischio_salvata", MODULE, {
                        "mansione_rischio": mr.pk, "codice": mr.codice, "nuova": nuova,
                        "fattori": dati.fattori, "visite": dati.visite, "dpi": dati.categorie_dpi,
                        "mansioni": dati.mansioni,
                    }, oggetto=mr)
                    messages.success(request, f"Mansione di rischio «{mr.nome}» salvata. Gli adempimenti dei "
                                              "dipendenti coinvolti vengono riallineati in background.")
                    return redirect("anagrafica:mansione_rischio_dettaglio", mr_id=mr.pk)
            except ValidationError as exc:
                errori.extend(exc.messages)
    return render(request, "anagrafica/pages/mansione_rischio_form.html", {
        "page_title": mr.nome if mr.pk else "Nuova mansione di rischio",
        "mr": mr, "dati": dati, "effetto": effetto, "errori": errori, "puo_protocollo": puo_protocollo,
        **_cataloghi(),
    })


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
    return redirect("anagrafica:mansioni_rischio_list")


# ═══════════════════════════════════════════════════════════════════════════
# Organigramma a doppio livello
# ═══════════════════════════════════════════════════════════════════════════

@login_required
def organigramma_mansioni_rischio(request):
    if not _puo_vedere(request):
        return _nega(request)
    from .services.organigramma_rischio import costruisci
    from .views import _can_view_visite_mediche

    fattore_id = int(request.GET["fattore"]) if (request.GET.get("fattore") or "").isdigit() else None
    vista = "lavorativa" if request.GET.get("vista") == "lavorativa" else "rischio"
    gruppi = costruisci(fattore_id=fattore_id, can_view_visite=_can_view_visite_mediche(request))
    per_mansione: dict[int, dict] = {}
    for g in gruppi:
        for m in g.mansioni:
            voce = per_mansione.setdefault(m["mansione"].pk, {"mansione": m["mansione"], "rischi": [], "persone": m["persone"]})
            voce["rischi"].append(g.mansione_rischio)
    return render(request, "anagrafica/pages/organigramma_mansioni_rischio.html", {
        "page_title": "Organigramma per mansione di rischio",
        "gruppi": gruppi,
        "per_mansione": sorted(per_mansione.values(), key=lambda v: v["mansione"].nome.casefold()),
        "vista": vista,
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
    return render(request, "anagrafica/partials/sicurezza_panel.html", {
        "legacy_id": legacy_id,
        "det": det,
        "stato": stato,
        "motivi": stato.motivi_visibili(can_view_visite),
        "can_view_visite": can_view_visite,
        "idoneita_condizionate": idoneita_condizionate,
        "puo_sorveglianza": _puo_sorveglianza(request),
        "override": override,
        "deroghe": list(DerogaOperativaVisita.objects.filter(legacy_anagrafica_id=legacy_id).order_by("-autorizzato_il")[:10]),
        "config": ConfigSicurezzaOperativa.load(),
        "mansioni_rischio_opts": list(MansioneRischio.objects.filter(is_active=True).order_by("codice")),
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
    mr = MansioneRischio.objects.filter(pk=request.POST.get("mansione_rischio") or 0, is_active=True).first()
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
