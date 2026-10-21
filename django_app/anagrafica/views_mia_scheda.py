"""«La mia scheda»: i dati HR del dipendente collegato, solo i suoi.

Scelta del titolare (16/10/2026): ferie e ratei, visite e idoneità (mai referti
né prescrizioni), formazione con gli attestati, voci del cedolino e DPI. La
persona è sempre quella collegata all'utente (``_current_legacy_anagrafica_id``):
nessun parametro nell'URL sceglie di chi sono i dati. Le pagine stanno sotto un
percorso condiviso del middleware ACL perché il filtro è qui dentro.
"""
from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from django.utils import timezone

from core import naming
from core.legacy_anagrafica import fetch_anagrafica_rows

logger = logging.getLogger(__name__)

MESI_CEDOLINO = 6


def _io(request) -> int | None:
    from anagrafica.views import _current_legacy_anagrafica_id

    return _current_legacy_anagrafica_id(request)


def _ratei(lid: int):
    from anagrafica.models import SaldoCedolino

    return SaldoCedolino.objects.filter(legacy_anagrafica_id=lid).order_by("-data_competenza", "-id").first()


def _visite(lid: int) -> list:
    from anagrafica.models import VisitaMedica
    from anagrafica.services.visite import ultime_visite_correnti_ids

    ids = ultime_visite_correnti_ids([lid], includi_cessati=True)
    # Solo tipo, date e giudizio: prescrizioni e referti non arrivano al template.
    return list(
        VisitaMedica.objects.filter(pk__in=ids, superata_il__isnull=True).select_related("tipo")
        .only("tipo__nome", "data_svolgimento", "data_scadenza", "esito", "scadenza_nota")
        .order_by("data_scadenza")
    )


def _formazione(lid: int) -> list:
    from anagrafica.models_formazione import TrainingEmployeeRecord

    return list(
        TrainingEmployeeRecord.objects.filter(legacy_anagrafica_id=lid).select_related("corso")
        .order_by("-data_completamento", "-id")[:100]
    )


def _cedolino(lid: int, competenza: str):
    """Voci dell'ultimo cedolino importato (o del mese scelto fra gli ultimi sei)."""
    from anagrafica.models import VoceRetributiva

    mesi = list(
        VoceRetributiva.objects.filter(legacy_anagrafica_id=lid).values_list("data_competenza", flat=True)
        .distinct().order_by("-data_competenza")[:MESI_CEDOLINO]
    )
    if not mesi:
        return [], [], None
    scelto = next((m for m in mesi if m.isoformat() == competenza), mesi[0])
    voci = list(
        VoceRetributiva.objects.filter(legacy_anagrafica_id=lid, data_competenza=scelto)
        .order_by("categoria", "pay_item")
    )
    return mesi, voci, scelto


def _dpi(lid: int, request) -> list:
    try:
        from dpi.models import RichiestaDPI
        from dpi.views import _own_richiesta_filter

        return list(
            RichiestaDPI.objects.filter(_own_richiesta_filter(request))
            .select_related("categoria", "tipo_dpi", "taglia_dpi").order_by("-created_at")[:20]
        )
    except Exception:
        logger.warning("La mia scheda: DPI non leggibili per %s", lid, exc_info=True)
        return []


@login_required
def mia_scheda(request):
    lid = _io(request)
    if lid is None:
        return render(request, "anagrafica/pages/mia_scheda.html", {"collegato": False})
    row = next(iter(fetch_anagrafica_rows(ids=[lid])), {})
    mesi, voci, competenza = _cedolino(lid, request.GET.get("cedolino", ""))
    return render(request, "anagrafica/pages/mia_scheda.html", {
        "collegato": True,
        "nome": naming.nome_completo(row.get("nome"), row.get("cognome")),
        "reparto": row.get("reparto") or "",
        "mansione": row.get("mansione") or "",
        "saldo": _ratei(lid),
        "visite": _visite(lid),
        "formazione": _formazione(lid),
        "cedolino_mesi": mesi,
        "cedolino_voci": voci,
        "cedolino_competenza": competenza,
        "dpi": _dpi(lid, request),
        "ambiti_rettifica": _ambiti_rettifica(),
        "mie_rettifiche": _mie_rettifiche(lid),
    })


def _ambiti_rettifica():
    from anagrafica.models import RichiestaRettifica

    return RichiestaRettifica.AMBITO_CHOICES


def _mie_rettifiche(lid: int) -> list:
    from anagrafica.models import RichiestaRettifica

    return list(RichiestaRettifica.objects.filter(legacy_anagrafica_id=lid)[:10])


@login_required
def miei_dati_zip(request):
    """«Scarica i miei dati» (GDPR art. 15/20): ZIP con JSON e CSV, registrato in audit."""
    from anagrafica.services.dati_personali import archivio_zip, raccogli
    from core.audit import log_action

    lid = _io(request)
    if lid is None:
        raise Http404
    nome, sezioni = raccogli(request, lid)
    contenuto = archivio_zip(nome, sezioni)
    log_action(request, "DATI_PERSONALI_ESPORTATI", "anagrafica", {
        "dipendente_id": lid, "sezioni": {k: len(v) for k, v in sezioni.items()},
    }, oggetto_tipo="dipendente", oggetto_id=str(lid))
    resp = HttpResponse(contenuto, content_type="application/zip")
    resp["Content-Disposition"] = f'attachment; filename="miei_dati_{timezone.localdate():%Y%m%d}.zip"'
    resp["Cache-Control"] = "private, no-store"
    return resp


@login_required
@require_POST
def segnala_rettifica(request):
    """«Segnala un dato errato» (GDPR art. 16): richiesta tracciata verso l'ufficio HR."""
    from anagrafica.models import RichiestaRettifica
    from core.audit import log_action

    lid = _io(request)
    if lid is None:
        raise Http404
    testo = (request.POST.get("testo") or "").strip()[:4000]
    ambito = request.POST.get("ambito") or "ALTRO"
    if ambito not in dict(RichiestaRettifica.AMBITO_CHOICES):
        ambito = "ALTRO"
    if len(testo) < 5:
        messages.error(request, "Scrivi quale dato è sbagliato e come dovrebbe essere.")
        return redirect("anagrafica:mia_scheda")
    richiesta = RichiestaRettifica.objects.create(
        legacy_anagrafica_id=lid, utente=request.user, ambito=ambito, testo=testo)
    log_action(request, "RETTIFICA_RICHIESTA", "anagrafica",
               {"richiesta_id": richiesta.pk, "ambito": ambito, "dipendente_id": lid}, oggetto=richiesta)
    _avvisa_hr(request, richiesta)
    messages.success(request, f"Segnalazione inviata all'ufficio HR (n. {richiesta.pk}). "
                              f"Riceverai la risposta entro il {richiesta.scadenza:%d/%m/%Y}.")
    return redirect("anagrafica:mia_scheda")


def _avvisa_hr(request, richiesta) -> None:
    """Mail alla casella HR di SiteConfig «anagrafica_rettifiche_email», senza il testo
    della richiesta (resta nel portale)."""
    try:
        from django.urls import reverse

        from core.models import SiteConfig
        from core.notifiche import invia_notifica_email

        email = (SiteConfig.get("anagrafica_rettifiche_email", "") or "").strip()
        if email:
            invia_notifica_email(
                email, "rettifica_dati",
                f"Nuova richiesta di rettifica dei dati n. {richiesta.pk} ({richiesta.get_ambito_display()}). "
                f"Da gestire entro il {richiesta.scadenza:%d/%m/%Y}.",
                request.build_absolute_uri(reverse("anagrafica:rettifiche")),
            )
    except Exception:
        logger.warning("Avviso HR per la rettifica %s non inviato", richiesta.pk, exc_info=True)


@login_required
def mio_attestato(request, record_id: int):
    """PDF dell'attestato di un proprio corso; di un altro = 404 (non si rivela che esiste)."""
    from anagrafica.models_formazione import TrainingEmployeeRecord, TrainingExportLog
    from anagrafica.services.attestato_pdf import build_attestato_pdf_bytes

    lid = _io(request)
    record = TrainingEmployeeRecord.objects.filter(pk=record_id).select_related("corso").first()
    if lid is None or record is None or int(record.legacy_anagrafica_id) != int(lid):
        raise Http404
    pdf = build_attestato_pdf_bytes(record)
    try:
        TrainingExportLog.objects.create(
            tipo="ATTESTATO", righe_esportate=1, generato_da=request.user,
            filtri_json={"record_id": record.pk, "legacy_anagrafica_id": lid, "formato": "attestato_pdf_self"},
            ip_address=request.META.get("REMOTE_ADDR") or None,
        )
    except Exception:
        logger.exception("La mia scheda: log attestato %s non registrato", record_id)
    resp = HttpResponse(pdf, content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="attestato_{record.pk}.pdf"'
    return resp
