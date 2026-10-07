"""Reportistica di anagrafica: modelli componibili, generazione, archivio.

Autorizzazione server-side e fail-closed su due livelli:
- ``anagrafica.reportistica.view`` per consultare e generare,
  ``anagrafica.reportistica.manage`` per creare e modificare i modelli;
- ogni sezione dati puo' chiedere un permesso ulteriore (es. visite mediche):
  senza, la sezione viene omessa dal documento con una dicitura esplicita.
Ogni generazione e ogni download finiscono nell'AuditLog.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Max, Q
from django.http import Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_action

from .models import ReportBlocco, ReportGenerato, ReportModello
from .reportistica import motore
from .reportistica import sezioni as catalogo
from .reportistica.forms import BlocchiFormSet, GeneraForm, ReportModelloForm, scelte_perimetro
from .reportistica.permessi import can_manage, can_view
from .reportistica.predefiniti import crea_predefiniti

logger = logging.getLogger(__name__)

MODULE = "anagrafica"
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _nega(request, msg: str = "Non hai accesso alla reportistica."):
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return HttpResponseForbidden(msg)
    messages.error(request, msg)
    return redirect("anagrafica:dipendenti_list")


@login_required
def reportistica_index(request):
    if not can_view(request):
        return _nega(request)
    q = (request.GET.get("q") or "").strip()
    modelli = list(
        ReportModello.objects.filter(is_active=True)
        .annotate(n_blocchi=Count("blocchi", distinct=True), ultima_generazione=Max("generati__generato_il"))
        .order_by("nome")
    )
    archivio = ReportGenerato.objects.defer("contenuto").select_related("generato_da")
    trenta_giorni_fa = timezone.now() - timedelta(days=30)
    kpi = {
        "modelli": len(modelli),
        "archivio": ReportGenerato.objects.count(),
        "ultimi_30": ReportGenerato.objects.filter(generato_il__gte=trenta_giorni_fa).count(),
        "dati_personali": ReportGenerato.objects.filter(contiene_dati_personali=True).count(),
    }
    if q:
        archivio = archivio.filter(Q(titolo__icontains=q) | Q(destinatario__icontains=q) | Q(modello_nome__icontains=q))
    return render(request, "anagrafica/pages/reportistica_index.html", {
        "page_title": "Reportistica",
        "modelli": modelli,
        "archivio": list(archivio[:60]),
        "kpi": kpi,
        "q": q,
        "can_manage": can_manage(request),
        "catalogo": catalogo.catalogo_per_gruppo(request),
    })


# ── Modelli ──────────────────────────────────────────────────────────────────

def _editor(request, modello: ReportModello | None):
    creazione = modello is None
    modello = modello or ReportModello(titolo_documento="", riservatezza=ReportModello.RISERVATEZZA_INTERNO)
    scelte = scelte_perimetro()
    if request.method == "POST":
        form = ReportModelloForm(request.POST, instance=modello, scelte=scelte)
        formset = BlocchiFormSet(request.POST, instance=modello, prefix="blocchi", request=request)
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                obj = form.save(commit=False)
                if creazione:
                    obj.created_by = request.user
                obj.updated_by = request.user
                obj.save()
                formset.instance = obj
                formset.save()
                # Ordine compatto 10, 20, 30… nell'ordine visto a schermo.
                for i, blocco in enumerate(obj.blocchi.order_by("ordine", "id"), start=1):
                    if blocco.ordine != i * 10:
                        ReportBlocco.objects.filter(pk=blocco.pk).update(ordine=i * 10)
            log_action(request, "reportistica_modello_salvato", MODULE,
                       {"modello": obj.pk, "nome": obj.nome, "creazione": creazione},
                       oggetto_tipo="report_modello", oggetto_id=str(obj.pk))
            messages.success(request, f"Modello «{obj.nome}» salvato.")
            if request.POST.get("dopo") == "genera":
                return redirect("anagrafica:reportistica_genera", pk=obj.pk)
            return redirect("anagrafica:reportistica_modello_edit", pk=obj.pk)
        messages.error(request, "Controlla i campi evidenziati.")
    else:
        form = ReportModelloForm(instance=modello, scelte=scelte)
        formset = BlocchiFormSet(instance=modello, prefix="blocchi", request=request)

    sezioni_info = {
        s.key: {"descrizione": s.descrizione, "riferimenti": " · ".join(s.riferimenti),
                "perimetro": s.usa_perimetro, "periodo": s.usa_periodo, "dinamiche": s.colonne_dinamiche}
        for s in catalogo.catalogo()
    }
    return render(request, "anagrafica/pages/reportistica_modello_form.html", {
        "page_title": "Nuovo modello di report" if creazione else f"Modifica · {modello.nome}",
        "form": form,
        "formset": formset,
        "modello": None if creazione else modello,
        "sezioni_info": sezioni_info,
        "segnaposto": motore.SEGNAPOSTO,
        "segnaposto_file": motore.SEGNAPOSTO_FILE,
    })


@login_required
def reportistica_modello_create(request):
    if not can_manage(request):
        return _nega(request, "Non hai i permessi per creare modelli di report.")
    return _editor(request, None)


@login_required
def reportistica_modello_edit(request, pk: int):
    if not can_manage(request):
        return _nega(request, "Non hai i permessi per modificare i modelli di report.")
    return _editor(request, get_object_or_404(ReportModello, pk=pk, is_active=True))


@login_required
@require_POST
def reportistica_modello_duplica(request, pk: int):
    if not can_manage(request):
        return _nega(request, "Non hai i permessi per duplicare i modelli di report.")
    origine = get_object_or_404(ReportModello, pk=pk, is_active=True)
    with transaction.atomic():
        copia = ReportModello.objects.get(pk=origine.pk)
        copia.pk = None
        copia.codice_sistema = ""
        copia.nome = f"{origine.nome} (copia)"[:150]
        copia.created_by = copia.updated_by = request.user
        copia.save()
        for b in origine.blocchi.all():
            ReportBlocco.objects.create(modello=copia, ordine=b.ordine, tipo=b.tipo, titolo=b.titolo,
                                        testo=b.testo, sezione=b.sezione, opzioni=dict(b.opzioni or {}))
    log_action(request, "reportistica_modello_duplicato", MODULE, {"origine": origine.pk, "copia": copia.pk},
               oggetto_tipo="report_modello", oggetto_id=str(copia.pk))
    messages.success(request, "Modello duplicato: personalizzalo e salvalo.")
    return redirect("anagrafica:reportistica_modello_edit", pk=copia.pk)


@login_required
@require_POST
def reportistica_modello_elimina(request, pk: int):
    if not can_manage(request):
        return _nega(request, "Non hai i permessi per eliminare i modelli di report.")
    modello = get_object_or_404(ReportModello, pk=pk, is_active=True)
    # Archiviato, non cancellato: i documenti gia' generati restano collegati.
    modello.is_active = False
    modello.codice_sistema = ""
    modello.updated_by = request.user
    modello.save(update_fields=["is_active", "codice_sistema", "updated_by", "updated_at"])
    log_action(request, "reportistica_modello_eliminato", MODULE, {"modello": modello.pk, "nome": modello.nome},
               oggetto_tipo="report_modello", oggetto_id=str(modello.pk))
    messages.success(request, f"Modello «{modello.nome}» eliminato.")
    return redirect("anagrafica:reportistica_index")


@login_required
@require_POST
def reportistica_predefiniti(request):
    if not can_manage(request):
        return _nega(request, "Non hai i permessi per ripristinare i modelli predefiniti.")
    creati = crea_predefiniti(ReportModello, ReportBlocco)
    log_action(request, "reportistica_predefiniti", MODULE, {"creati": creati})
    messages.success(request, f"Modelli predefiniti ripristinati: {creati}." if creati
                     else "Tutti i modelli predefiniti sono già presenti.")
    return redirect("anagrafica:reportistica_index")


# ── Generazione ──────────────────────────────────────────────────────────────

@login_required
def reportistica_genera(request, pk: int):
    if not can_view(request):
        return _nega(request)
    modello = get_object_or_404(ReportModello.objects.prefetch_related("blocchi"), pk=pk, is_active=True)
    scelte = scelte_perimetro()
    azione = (request.POST.get("azione") or "anteprima").strip().lower()

    if request.method == "POST":
        form = GeneraForm(request.POST, modello=modello, scelte=scelte)
        if not form.is_valid():
            messages.error(request, "Controlla i campi evidenziati.")
            return _render_genera(request, modello, form, None)
        parametri = motore.Parametri(
            periodo_tipo=form.cleaned_data["periodo_tipo"], data_da=form.cleaned_data.get("data_da"),
            data_a=form.cleaned_data.get("data_a"), perimetro=form.perimetro(),
            titolo=form.cleaned_data["titolo"], sottotitolo=form.cleaned_data.get("sottotitolo") or "",
            destinatario=form.cleaned_data.get("destinatario") or "", testi=form.testi(),
            escludi_blocchi=form.escludi_blocchi(),
        )
        if form.cleaned_data.get("salva_nel_modello"):
            if can_manage(request):
                _salva_scelte(request, modello, form, parametri)
                messages.success(request, "Scelte salvate nel modello.")
            else:
                messages.warning(request, "Scelte non salvate: serve il permesso di gestione dei modelli.")
    else:
        form = GeneraForm(modello=modello, scelte=scelte)
        parametri = motore.Parametri.dal_modello(modello)

    documento = motore.componi(modello, parametri, request)
    if request.method == "POST" and azione in (ReportGenerato.FORMATO_PDF, ReportGenerato.FORMATO_XLSX):
        return _scarica_nuovo(request, modello, documento, parametri, azione,
                              form.cleaned_data.get("note_archivio") or "")
    return _render_genera(request, modello, form, documento)


def _render_genera(request, modello, form, documento):
    return render(request, "anagrafica/pages/reportistica_genera.html", {
        "page_title": f"Genera · {modello.nome}",
        "modello": modello,
        "form": form,
        "documento": documento,
        "can_manage": can_manage(request),
        "segnaposto": motore.SEGNAPOSTO,
    })


def _salva_scelte(request, modello: ReportModello, form: GeneraForm, parametri: motore.Parametri) -> None:
    with transaction.atomic():
        modello.titolo_documento = parametri.titolo
        modello.sottotitolo = parametri.sottotitolo
        modello.destinatario = parametri.destinatario
        modello.periodo_tipo = parametri.periodo_tipo
        modello.data_da = parametri.data_da
        modello.data_a = parametri.data_a
        modello.filtri = parametri.perimetro.as_dict()
        modello.updated_by = request.user
        modello.save()
        for blocco_id, testo in parametri.testi.items():
            ReportBlocco.objects.filter(pk=blocco_id, modello=modello).update(testo=testo)
    # I blocchi prefetchati vanno riletti per la composizione.
    modello._prefetched_objects_cache = {}
    log_action(request, "reportistica_modello_salvato", MODULE,
               {"modello": modello.pk, "nome": modello.nome, "da_generazione": True},
               oggetto_tipo="report_modello", oggetto_id=str(modello.pk))


def _scarica_nuovo(request, modello, documento: motore.Documento, parametri, formato: str, nota: str,
                   *, extra: dict | None = None):
    if formato == ReportGenerato.FORMATO_PDF:
        contenuto, content_type = motore.render_pdf(documento), "application/pdf"
    else:
        contenuto, content_type = motore.render_xlsx(documento), _XLSX
    nome_file = motore.nome_file(modello, documento, formato)
    sezioni_usate = [e.sezione.key for e in documento.sezioni_calcolate if e.sezione is not None]
    archiviato = ReportGenerato.objects.create(
        # Report a conversazione: il modello non e' salvato, l'archivio tiene la specifica.
        modello=modello if modello.pk else None, modello_nome=modello.nome, titolo=documento.titolo[:200],
        destinatario=documento.destinatario[:200], formato=formato,
        data_da=documento.date_from, data_a=documento.date_to,
        parametri={**parametri.as_dict(), "sezioni": sezioni_usate, **(extra or {})},
        contiene_dati_personali=documento.contiene_dati_personali,
        nome_file=nome_file, contenuto=contenuto, dimensione=len(contenuto),
        sha256=hashlib.sha256(contenuto).hexdigest(), note=nota[:300], generato_da=request.user,
    )
    log_action(request, "reportistica_genera", MODULE, {
        "modello": modello.pk, "archivio": archiviato.pk, "formato": formato,
        "destinatario": documento.destinatario, "sezioni": sezioni_usate,
        "dati_personali": documento.contiene_dati_personali,
    }, oggetto_tipo="report_generato", oggetto_id=str(archiviato.pk))
    response = HttpResponse(contenuto, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{nome_file}"'
    return response


# ── Archivio ─────────────────────────────────────────────────────────────────

def _archivio_consentito(request, doc: ReportGenerato) -> bool:
    """Un documento archiviato si riscarica solo se oggi si potrebbe rigenerarlo."""
    chiavi = (doc.parametri or {}).get("sezioni") or []
    for chiave in chiavi:
        sezione = catalogo.get(chiave)
        if sezione is not None and not sezione.consentita(request):
            return False
    return True


@login_required
def reportistica_archivio_download(request, pk: int):
    if not can_view(request):
        return _nega(request)
    doc = get_object_or_404(ReportGenerato, pk=pk)
    if not _archivio_consentito(request, doc):
        messages.error(request, "Il documento contiene sezioni per cui non hai i permessi.")
        return redirect("anagrafica:reportistica_index")
    log_action(request, "reportistica_download", MODULE, {"archivio": doc.pk, "file": doc.nome_file},
               oggetto_tipo="report_generato", oggetto_id=str(doc.pk))
    content_type = "application/pdf" if doc.formato == ReportGenerato.FORMATO_PDF else _XLSX
    response = HttpResponse(bytes(doc.contenuto), content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{doc.nome_file}"'
    return response


@login_required
@require_POST
def reportistica_archivio_elimina(request, pk: int):
    if not can_manage(request):
        return _nega(request, "Non hai i permessi per eliminare documenti dall'archivio.")
    doc = ReportGenerato.objects.filter(pk=pk).defer("contenuto").first()
    if doc is None:
        raise Http404("Documento inesistente")
    log_action(request, "reportistica_archivio_eliminato", MODULE,
               {"archivio": doc.pk, "file": doc.nome_file, "sha256": doc.sha256},
               oggetto_tipo="report_generato", oggetto_id=str(doc.pk))
    doc.delete()
    messages.success(request, "Documento eliminato dall'archivio.")
    return redirect("anagrafica:reportistica_index")
