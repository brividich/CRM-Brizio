"""Pagina «Scarpe»: ordini al negozio in convenzione e fuori convenzione, chiusura con fattura."""
from __future__ import annotations

import mimetypes
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from core.upload_mime import UploadMimeValidationError, validate_extension_and_mime

from . import flusso, negozio as negozio_srv
from .models import DPIImpostazioni, FatturaNegozioDPI, ModalitaNegozio, OrdineNegozioDPI
from .views import (
    DPI_DOCUMENT_MAX_BYTES,
    _approvate_queryset,
    _chiave_persona,
    _int_or_none,
    _is_gestore,
    _notifica_richiedente,
    _registra_consegna,
    _segna_pronta,
    log_action,
)

FATTURA_ESTENSIONI = {".pdf", ".jpg", ".jpeg", ".png"}
FATTURA_MIME = {"application/pdf", "image/jpeg", "image/png"}


def _autore(request) -> str:
    return request.user.get_full_name() or request.user.username


def _selezionate(request, qs) -> list:
    ids = [i for i in (_int_or_none(v) for v in request.POST.getlist("ids")) if i]
    return list(qs.filter(pk__in=ids).order_by("richiedente_nome", "created_at")) if ids else []


def _registra_ordine(request, richieste, *, inviato_a: str) -> None:
    ordine = negozio_srv.registra_ordine(richieste, inviato_a=inviato_a, autore=_autore(request))
    numeri = ", ".join(r.numero for r in richieste)
    log_action(request, "DPI_ORDINE_NEGOZIO", "dpi", f"Ordine al negozio {ordine.pk}: {numeri}")
    for r in richieste:
        _notifica_richiedente(r, f"Le tue scarpe {r.numero} sono state ordinate: ti avvisiamo quando arrivano.")


def _chiudi_con_fattura(request, richieste, impost) -> None:
    upload = request.FILES.get("fattura")
    numero = request.POST.get("fattura_numero", "").strip()[:60]
    try:
        data_fattura = date.fromisoformat(request.POST.get("fattura_data", "").strip())
    except ValueError:
        data_fattura = None
    # Stessa fattura gia' caricata (un ordine rimasto fuori): si aggiunge a quella, senza doppioni.
    fattura = FatturaNegozioDPI.objects.filter(numero__iexact=numero, data=data_fattura).first() if numero and data_fattura else None
    if fattura is None:
        if upload is None or not numero or data_fattura is None:
            messages.error(request, "Per chiudere servono il file della fattura, il numero e la data.")
            return
        try:
            validate_extension_and_mime(
                upload, allowed_extensions=FATTURA_ESTENSIONI, allowed_mimes=FATTURA_MIME,
                max_bytes=DPI_DOCUMENT_MAX_BYTES, label=upload.name, allow_empty=False,
            )
        except UploadMimeValidationError as exc:
            messages.error(request, str(exc))
            return
        fattura = FatturaNegozioDPI.objects.create(
            numero=numero, data=data_fattura, negozio_nome=impost.negozio_nome[:120], file=upload,
            nome_originale=(upload.name or "fattura")[:255], dimensione_bytes=int(upload.size or 0),
            caricata_da=request.user,
        )
    log_action(request, "DPI_FATTURA_NEGOZIO", "dpi", f"Fattura {numero} ({fattura.pk}): {', '.join(r.numero for r in richieste)}")
    for r in richieste:
        r.fattura_negozio = fattura
        r.save(update_fields=["fattura_negozio", "updated_at"])
        _registra_consegna(
            request, r, data_consegna=data_fattura,
            note=f"Ritirate al negozio {impost.negozio_nome}, fattura {numero} del {data_fattura:%d-%m-%Y}.",
        )
    messages.success(request, f"Fattura {numero} caricata: {len(richieste)} ordini chiusi.")


def _azione(request, impost):
    azione = request.POST.get("azione", "")
    base = _approvate_queryset(request)
    url = reverse("dpi:negozio")

    if azione in ("invia_ordine", "segna_ordinato"):
        richieste = _selezionate(request, negozio_srv.da_ordinare(base))
        if not richieste:
            messages.warning(request, "Spunta almeno un paio di scarpe da ordinare.")
        elif azione == "segna_ordinato":
            _registra_ordine(request, richieste, inviato_a="")
            messages.success(request, f"Segnate come ordinate: {len(richieste)}.")
        elif not impost.negozio_email.strip():
            messages.error(request, "Manca la mail del negozio in Impostazioni DPI. Puoi copiare il testo e usare «Ho già scritto io al negozio».")
        else:
            testo = negozio_srv.testo_ordine(richieste, note=request.POST.get("note", ""))
            if flusso.invia_ordine_negozio(testo):
                _registra_ordine(request, richieste, inviato_a=impost.negozio_email.strip())
                messages.success(request, f"Ordine inviato a {impost.negozio_nome}: {len(richieste)} righe.")
            else:
                messages.error(request, "Mail non inviata (regola spenta in Automazioni o invio fallito): l'ordine resta da fare.")
        return redirect(url + "#da-ordinare")

    if azione == "pronte":
        richieste = _selezionate(request, negozio_srv.ordinate(base))
        if not richieste:
            messages.warning(request, "Spunta almeno un paio di scarpe arrivate.")
        for r in richieste:
            _segna_pronta(request, r, da_nome=_autore(request))
        if richieste:
            messages.success(request, f"Dipendenti avvisati del ritiro in ufficio: {len(richieste)}.")
        return redirect(url + "#ordinate")

    if azione in ("negozio_avvisato", "fattura"):
        richieste = _selezionate(request, negozio_srv.fuori_convenzione(base))
        if not richieste:
            messages.warning(request, "Spunta almeno un ordine.")
        elif azione == "fattura":
            _chiudi_con_fattura(request, richieste, impost)
        else:
            for r in richieste:
                _segna_pronta(request, r, da_nome=_autore(request))
            messages.success(request, f"Segnato il negozio come avvisato e avvisati i dipendenti: {len(richieste)}.")
        return redirect(url + "#fuori")

    messages.error(request, "Azione non riconosciuta.")
    return redirect(url)


@login_required
def negozio(request):
    if not _is_gestore(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dpi:dashboard")
    impost = DPIImpostazioni.get_singleton()
    if request.method == "POST":
        return _azione(request, impost)

    base = _approvate_queryset(request).select_related("ordine_negozio").order_by("richiedente_nome", "created_at")
    da_ordinare = list(negozio_srv.da_ordinare(base))
    ordinate = list(negozio_srv.ordinate(base))
    fuori = list(negozio_srv.fuori_convenzione(base))
    for r in da_ordinare:
        r.riga_testo = negozio_srv.riga_ordine(r)
        r.dettaglio = negozio_srv.dettaglio_ordine(r)
    for r in ordinate:
        r.chiave_banco = _chiave_persona(r)
    return render(request, "dpi/pages/negozio.html", {
        "is_gestore": True,
        "is_approvatore": True,
        "impost": impost,
        "da_ordinare": da_ordinare,
        "ordinate": ordinate,
        "fuori": fuori,
        "n_fuori_da_avvisare": sum(1 for r in fuori if r.pronta_ritiro_il is None),
        "prossimo_riepilogo": negozio_srv.prossimo_riepilogo(),
        "ultimo_ordine": OrdineNegozioDPI.objects.order_by("-created_at").first(),
        "ordini": OrdineNegozioDPI.objects.prefetch_related("richieste").order_by("-created_at")[:10],
        "fatture": FatturaNegozioDPI.objects.prefetch_related("richieste").order_by("-data", "-id")[:10],
        "testo_apertura": negozio_srv.testo_ordine([]).split("\n\n")[0],
        "modalita_convenzione": ModalitaNegozio.CONVENZIONE,
    })


@login_required
def fattura_download(request, pk: int):
    if not _is_gestore(request):
        messages.error(request, "Accesso non autorizzato.")
        return redirect("dpi:dashboard")
    fattura = get_object_or_404(FatturaNegozioDPI, pk=pk)
    storage = fattura.file.storage
    if not fattura.file or not fattura.file.name or not storage.exists(fattura.file.name):
        return HttpResponse("Fattura non trovata.", status=404)
    log_action(request, "DPI_FATTURA_APERTA", "dpi", f"Aperta fattura negozio {fattura.pk}: {fattura.numero}")
    nome = fattura.nome_originale or f"fattura-{fattura.numero}"
    return FileResponse(
        storage.open(fattura.file.name, "rb"),
        as_attachment=request.GET.get("download") == "1",
        filename=nome,
        content_type=mimetypes.guess_type(nome)[0] or "application/octet-stream",
    )
