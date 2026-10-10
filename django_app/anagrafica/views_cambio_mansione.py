"""Cambi mansione: piano di adeguamento per persona e quadro di quelli in corso.

Stessi cancelli degli spostamenti organizzativi: chi gestisce gli spostamenti
(amministrazione anagrafica) chiude o riapre gli adempimenti; il quadro lo vede
anche chi ha accesso ai dati HR. I nomi delle visite (dato sanitario) compaiono
solo con il permesso visite mediche. Ogni modifica finisce nell'AuditLog.
"""
from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_action
from core.legacy_anagrafica import fetch_anagrafica_rows
from core import naming

from .models import AdempimentoCambioMansione

logger = logging.getLogger(__name__)
MODULE = "anagrafica"


@login_required
@require_POST
def adempimento_cambio_mansione_stato(request, legacy_id: int, adempimento_id: int):
    from .views import _is_anagrafica_admin

    if not _is_anagrafica_admin(request):
        messages.error(request, "Non hai i permessi per gestire il piano di adeguamento.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)
    adempimento = AdempimentoCambioMansione.objects.filter(pk=adempimento_id, legacy_anagrafica_id=legacy_id).first()
    if adempimento is None:
        messages.error(request, "Adempimento non trovato.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)

    azione = (request.POST.get("azione") or "").strip()
    motivo = (request.POST.get("motivo") or "").strip()[:300]
    if azione == "non_necessario":
        if not adempimento.aperto:
            messages.info(request, "L'adempimento è già chiuso.")
            return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)
        if not motivo:
            messages.error(request, "Indica perché l'adempimento non è necessario.")
            return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)
        adempimento.stato = AdempimentoCambioMansione.STATO_NON_NECESSARIO
        adempimento.chiuso_il = timezone.now()
        adempimento.chiuso_da = request.user
        adempimento.chiusura_automatica = False
        adempimento.chiusura_nota = motivo
    elif azione == "riapri":
        # Solo i «non necessario» chiusi a mano: annullati e non più dovuti sono
        # storia di uno spostamento annullato o di un requisito sparito.
        if adempimento.stato != AdempimentoCambioMansione.STATO_NON_NECESSARIO or adempimento.chiusura_automatica:
            messages.info(request, "Si riapre solo un adempimento chiuso a mano come «non necessario».")
            return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)
        adempimento.stato = AdempimentoCambioMansione.STATO_APERTO
        adempimento.chiuso_il = None
        adempimento.chiuso_da = None
        adempimento.chiusura_nota = ""
    else:
        messages.error(request, "Azione non valida.")
        return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)
    adempimento.save(update_fields=["stato", "chiuso_il", "chiuso_da", "chiusura_automatica", "chiusura_nota"])
    from .services import eventi_sicurezza
    eventi_sicurezza.registra(
        legacy_id, "ADEMPIMENTO_CHIUSO" if azione == "non_necessario" else "ADEMPIMENTO_RIAPERTO",
        f"{adempimento.get_tipo_display()}: {'non necessario' if azione == 'non_necessario' else 'riaperto'}",
        request=request, oggetto=adempimento,
        payload={"adempimento_id": adempimento.pk, "chiave": adempimento.chiave, "motivo": motivo},
    )
    log_action(request, "cambio_mansione_adempimento", MODULE, {
        "adempimento": adempimento.pk, "assegnazione": adempimento.assegnazione_id, "azione": azione,
        "tipo": adempimento.tipo, "motivo": motivo,
    }, oggetto_tipo="anagrafica.adempimentocambiomansione", oggetto_id=str(adempimento.pk))
    messages.success(request, "Piano di adeguamento aggiornato.")
    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)


@login_required
def cambi_mansione(request):
    """Quadro dei cambi mansione con adempimenti: chi, cosa manca, entro quando."""
    from .views import _can_view_visite_mediche, _check_hr_permission, _is_anagrafica_admin

    if not (_is_anagrafica_admin(request) or _check_hr_permission(request)):
        messages.error(request, "Non hai i permessi per il quadro dei cambi mansione.")
        return redirect("anagrafica:index")
    try:
        from .services.cambio_mansione import aggiorna_piani

        aggiorna_piani()
    except Exception:
        logger.warning("Aggiornamento piani di adeguamento fallito", exc_info=True)

    filtro = (request.GET.get("stato") or "aperti").strip()
    qs = AdempimentoCambioMansione.objects.select_related("assegnazione", "chiuso_da")
    if filtro == "aperti":
        qs = qs.filter(stato=AdempimentoCambioMansione.STATO_APERTO)
    elif filtro == "ritardo":
        qs = qs.filter(stato=AdempimentoCambioMansione.STATO_APERTO, entro_il__lt=timezone.localdate())
    adempimenti = list(qs.order_by("entro_il", "legacy_anagrafica_id", "tipo")[:500])

    nomi = {}
    ids = sorted({a.legacy_anagrafica_id for a in adempimenti})
    if ids:
        for row in fetch_anagrafica_rows(ids=ids):
            nomi[int(row["id"])] = naming.nome_completo(row.get("nome"), row.get("cognome"))
    persone: dict[tuple[int, int], dict] = {}
    for a in adempimenti:
        chiave = (a.legacy_anagrafica_id, a.assegnazione_id)
        voce = persone.setdefault(chiave, {
            "legacy_id": a.legacy_anagrafica_id, "nome": nomi.get(a.legacy_anagrafica_id) or f"#{a.legacy_anagrafica_id}",
            "assegnazione": a.assegnazione, "voci": [], "ritardo": 0, "aperti": 0,
        })
        voce["voci"].append(a)
        voce["aperti"] += a.aperto
        voce["ritardo"] += a.in_ritardo
    tutti_aperti = AdempimentoCambioMansione.objects.filter(stato=AdempimentoCambioMansione.STATO_APERTO)
    # Stato operativo (visita del cambio mansione mancante, non idoneità): solo
    # l'etichetta, il perché resta a chi ha il permesso visite.
    from .services import stato_operativo
    stati = sorted(
        (s for s in stato_operativo.calcola().values() if s.codice != stato_operativo.OK),
        key=lambda s: (not s.bloccante, s.legacy_id),
    )
    mancanti = [s.legacy_id for s in stati if s.legacy_id not in nomi]
    if mancanti:
        for row in fetch_anagrafica_rows(ids=mancanti):
            nomi[int(row["id"])] = naming.nome_completo(row.get("nome"), row.get("cognome"))
    for s in stati:
        s.nome = nomi.get(s.legacy_id) or f"#{s.legacy_id}"

    def _ordine(g):
        # Gli adempimenti di uno spostamento annullato non hanno più l'assegnazione.
        inizio = g["assegnazione"].data_inizio if g["assegnazione"] else g["voci"][0].entro_il
        return (-g["ritardo"], inizio, g["nome"])

    return render(request, "anagrafica/pages/cambi_mansione.html", {
        "page_title": "Cambi mansione",
        "gruppi": sorted(persone.values(), key=_ordine),
        "stati_operativi": stati,
        "filtro": filtro,
        "n_aperti": tutti_aperti.count(),
        "n_ritardo": tutti_aperti.filter(entro_il__lt=timezone.localdate()).count(),
        "n_persone": tutti_aperti.order_by().values("legacy_anagrafica_id").distinct().count(),
        "can_view_visite": _can_view_visite_mediche(request),
        "is_admin": _is_anagrafica_admin(request),
    })
