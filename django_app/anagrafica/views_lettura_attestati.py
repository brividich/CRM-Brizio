"""«Leggi un attestato»: dall'attestato di un ente esterno al completamento a libretto.

Vive dentro la Dashboard formazione (``/anagrafica/formazione/?vista=leggi-attestato``
e POST con ``azione``) per restare sotto la stessa rotta e lo stesso permesso:
nessuna rotta nuova da legare nell'ACL. Serve il permesso di modifica della
formazione (``_can_edit_formazione``).

1. ``azione=leggi_attestato`` (fetch): legge il file e risponde con la proposta
   (``services.lettura_attestato``). Il file non resta sul server.
2. ``azione=registra_attestato``: il modulo confermato torna con lo stesso file;
   si crea il completamento senza sessione (``_crea_record_diretto``, idempotente
   su corso/persona/data), si archivia l'attestato come «esterno principale» e si
   registra il certificato con numero, data di rilascio ed ente.
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse

logger = logging.getLogger(__name__)


def _data(raw: str) -> date | None:
    try:
        return date.fromisoformat((raw or "").strip())
    except ValueError:
        return None


def _dipendenti_attivi() -> list[dict]:
    from anagrafica.models import DipendenteAnagraficaAziendale
    from core.legacy_anagrafica import fetch_anagrafica_rows
    from core.naming import nome_completo

    cessati = set(
        DipendenteAnagraficaAziendale.objects.filter(data_cessazione__isnull=False)
        .values_list("legacy_anagrafica_id", flat=True)
    )
    out = [
        {"id": int(r["id"]), "nome": nome_completo(r.get("nome") or "", r.get("cognome") or "") or f"#{r['id']}"}
        for r in fetch_anagrafica_rows(deduplicate=True)
        if r.get("id") and int(r["id"]) not in cessati
    ]
    return sorted(out, key=lambda d: d["nome"].casefold())


def gestisci(request):
    from . import views as v

    if not v._can_edit_formazione(request):
        if request.method == "POST" and request.POST.get("azione") == "leggi_attestato":
            return JsonResponse({"ok": False, "reason": "forbidden"}, status=403)
        messages.error(request, "Per registrare un attestato serve il permesso di modifica della formazione.")
        return redirect("anagrafica:formazione_dashboard")
    if request.method == "POST":
        azione = request.POST.get("azione")
        if azione == "leggi_attestato":
            return _leggi(request, v)
        if azione == "registra_attestato":
            return _registra(request, v)
    from anagrafica.models_formazione import TrainingCourse

    return render(request, "anagrafica/pages/formazione_leggi_attestato.html", {
        "page_title": "Leggi un attestato",
        "dipendenti": _dipendenti_attivi(),
        "corsi": list(TrainingCourse.objects.filter(is_active=True).exclude(stato="ARCHIVIATO").order_by("titolo")
                      .values("id", "codice", "titolo")),
        "accept": ".pdf,.jpg,.jpeg,.png,.webp",
    })


def _valida_file(request, v):
    from .services.upload_documenti import UploadMimeValidationError, valida_documento

    uploaded = request.FILES.get("file")
    if not uploaded:
        return None, "", "Scegli il file dell'attestato."
    try:
        mime = valida_documento(uploaded, {".pdf", ".jpg", ".jpeg", ".png", ".webp"} & set(v._ALLOWED_DOC_EXTENSIONS))
    except UploadMimeValidationError as exc:
        return None, "", f"File rifiutato: {exc} Ammessi PDF e immagini (JPG, PNG, WEBP)."
    uploaded.seek(0)  # il controllo del contenuto ha già letto il file
    return uploaded, mime, ""


def _leggi(request, v):
    from core.lettura_documenti import DocumentoNonLeggibile, leggi

    from .services.lettura_attestato import proponi

    uploaded, _mime, errore = _valida_file(request, v)
    if errore:
        return JsonResponse({"ok": False, "errore": errore}, status=400)
    try:
        lettura = leggi(uploaded.read())
    except DocumentoNonLeggibile as exc:
        return JsonResponse({"ok": False, "errore": str(exc)}, status=400)
    return JsonResponse({"ok": True, **proponi(lettura)})


def _registra(request, v):
    from anagrafica.models_formazione import TrainingCertificate, TrainingCourse, TrainingEmployeeRecord

    from .services.attestato_pdf import archivia_attestato, archivia_attestato_caricato

    torna = reverse("anagrafica:formazione_dashboard") + "?vista=leggi-attestato"
    uploaded, mime, errore = _valida_file(request, v)
    if errore:
        messages.error(request, errore)
        return redirect(torna)
    corso = TrainingCourse.objects.filter(pk=v._int_or_none(request.POST.get("corso"))).first()
    try:
        legacy_id = int(request.POST.get("dipendente") or 0)
    except ValueError:
        legacy_id = 0
    data_completamento = _data(request.POST.get("data_completamento"))
    if corso is None or legacy_id <= 0 or data_completamento is None:
        messages.error(request, "Indica dipendente, corso e data di completamento.")
        return redirect(torna)
    if legacy_id not in {d["id"] for d in _dipendenti_attivi()}:
        messages.error(request, "Il dipendente scelto non è tra quelli in forza.")
        return redirect(torna)
    try:
        ore = Decimal((request.POST.get("ore") or "").replace(",", ".")) if request.POST.get("ore") else None
    except InvalidOperation:
        ore = None
    ente = (request.POST.get("ente") or "").strip()[:200]
    numero = (request.POST.get("numero") or "").strip()[:100]
    data_rilascio = _data(request.POST.get("data_rilascio")) or data_completamento

    try:
        with transaction.atomic():
            record = v._crea_record_diretto(
                corso, legacy_id, data_completamento=data_completamento, ore_frequentate=ore,
                idoneo=request.POST.get("idoneo", "1") == "1", erogato_da=ente,
                note="Registrato da «Leggi un attestato».", created_by=request.user,
            )
    except IntegrityError:
        record = None
    nuovo = record is not None
    if record is None:
        record = TrainingEmployeeRecord.objects.filter(
            corso=corso, legacy_anagrafica_id=legacy_id, data_completamento=data_completamento,
        ).first()
    if record is None:
        messages.error(request, "Completamento non registrato.")
        return redirect(torna)

    try:
        try:
            archivia_attestato(record, user=request.user)
        except Exception:
            logger.exception("Copia interna attestato non generata (record %s)", record.pk)
        doc = archivia_attestato_caricato(
            record, uploaded, user=request.user, force=True, mime=mime,
            descrizione="Attestato organizzatore esterno (principale)" + (f" — {ente}" if ente else ""),
        )
        TrainingCertificate.objects.update_or_create(
            record=record,
            defaults={
                "legacy_anagrafica_id": record.legacy_anagrafica_id, "numero_attestato": numero,
                "data_rilascio": data_rilascio, "rilasciato_da": ente, "file_attestato": doc,
                "created_by": request.user,
            },
        )
    except Exception:
        logger.exception("Archiviazione attestato letto fallita (record %s)", record.pk)
        messages.error(request, "Completamento registrato, ma l'archiviazione del file non è riuscita: ricaricalo dalla scheda.")
        return redirect(torna)

    v._audit_safe(request, "formazione_attestato_letto", "formazione", {
        "record_id": record.pk, "corso_id": corso.pk, "nuovo": nuovo, "documento_id": doc.pk,
    })
    messages.success(
        request,
        f"Attestato registrato: {corso.titolo} del {data_completamento:%d/%m/%Y}."
        if nuovo else
        f"Il completamento c'era già ({corso.titolo} del {data_completamento:%d/%m/%Y}): attestato archiviato.",
    )
    return redirect(torna)
