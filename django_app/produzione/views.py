"""Ordini di produzione: elenco degli OP, scheda con i documenti di produzione, impostazioni."""
from __future__ import annotations

from urllib.parse import urlencode

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from core import ordini_produzione as op_db
from core.acl_v2 import request_has_permission_code
from core.audit import log_action
from core.paginazione import pagina_elenco
from tasks.tech_paths import normalizza_percorso

from . import guida as guida_mod
from . import nuovo_op, services
from . import report_cmm_indice as cmm
from .acl_bootstrap import PERM_DOCUMENTI, PERM_IMPOSTAZIONI
from .models import CartellaReportCMM, DocumentoOP, ReportCMM, TipoDocumento


def _richiede(request, codice: str) -> None:
    """Oltre al cancello del middleware: chi scrive deve avere il permesso, sempre."""
    if not request_has_permission_code(request, codice):
        raise PermissionDenied


def _ctx(request, corrente: str, **extra) -> dict:
    return {
        "page_title": "Ordini di produzione",
        "prod_corrente": corrente,
        "prod_puo_documenti": request_has_permission_code(request, PERM_DOCUMENTI),
        "prod_puo_impostazioni": request_has_permission_code(request, PERM_IMPOSTAZIONI),
        **extra,
    }


@login_required
@require_GET
def elenco(request):
    testo = (request.GET.get("q") or "").strip()
    stato = (request.GET.get("stato") or "").strip()
    disponibile = op_db.disponibile()
    manca = (request.GET.get("manca") or "").strip()
    righe = services.righe_elenco(request, testo, stato) if disponibile else []
    vede_kickoff = services._vede_kickoff(request)
    chips = services.conteggi_manca(righe, vede_kickoff)
    if manca not in {c["chiave"] for c in chips}:
        manca = ""
    righe_filtrate = services.filtra_manca(righe, manca)
    return render(request, "produzione/elenco.html", _ctx(
        request, "elenco", disponibile=disponibile, pagina=pagina_elenco(request, righe_filtrate),
        totale=len(righe_filtrate), totale_tutti=len(righe), chips=chips, manca=manca, vede_kickoff=vede_kickoff,
        q=testo, stato=stato, stati=op_db.stati() if disponibile else [], nuovo_op=nuovo_op.contesto(request),
    ))


@login_required
@require_GET
def pn_elenco(request):
    """Una riga per P/N: il P/N è l'articolo principale, con i suoi OP e i suoi FAI."""
    testo = (request.GET.get("q") or "").strip()
    disponibile = op_db.disponibile()
    manca = (request.GET.get("manca") or "").strip()
    righe = services.righe_pn(request, testo) if disponibile else []
    vede_kickoff = services._vede_kickoff(request)
    chips = services.conteggi_manca_pn(righe, vede_kickoff)
    if manca not in {c["chiave"] for c in chips}:
        manca = ""
    righe_filtrate = services.filtra_manca_pn(righe, manca)
    return render(request, "produzione/pn_elenco.html", _ctx(
        request, "pn", disponibile=disponibile, pagina=pagina_elenco(request, righe_filtrate),
        totale=len(righe_filtrate), chips=chips, manca=manca, vede_kickoff=vede_kickoff, q=testo,
    ))


@login_required
@require_GET
def pn_scheda(request):
    if not op_db.disponibile():
        raise Http404
    dati = services.scheda_pn(request, request.GET.get("pn") or "")
    if dati is None:
        raise Http404
    return render(request, "produzione/pn_scheda.html", _ctx(request, "pn", **dati))


@login_required
@require_GET
def pn_quote(request):
    """Analisi quote del P/N: la pagina si disegna nel browser con i dati di ``api_quote``."""
    from tasks.identity import normalize_part_number

    pn = normalize_part_number(request.GET.get("pn") or "")
    if not pn:
        raise Http404
    programmi = cmm.programmi_del_pn(pn)
    prog = (request.GET.get("prog") or "").strip()
    if prog not in {p["programma_base"] for p in programmi}:
        prog = programmi[0]["programma_base"] if programmi else ""
    stato = {k: (request.GET.get(k) or "").strip()[:300] for k in ("q", "nom", "r", "tab", "per", "da", "a", "op", "cmp", "f", "ord")}
    stato["prog"] = prog
    return render(request, "produzione/quote.html", _ctx(
        request, "pn", pn=pn, programmi=programmi, prog=prog, stato=stato,
        cartella=CartellaReportCMM.objects.filter(pn=pn).order_by("-letta_il").first(), attivo=cmm.attivo(),
    ))


def _data_get(request, chiave: str):
    from datetime import date

    try:
        return date.fromisoformat((request.GET.get(chiave) or "").strip()[:10])
    except ValueError:
        return None


@require_GET
def api_quote(request):
    """Misure di un programma del P/N in JSON (pagina «Analisi quote»). Risponde sempre in JSON."""
    from tasks.identity import normalize_part_number

    # Il permesso «Elenco e scheda OP» lo controlla il middleware ACL (rotta legata, risposta JSON sotto /api/).
    if not request.user.is_authenticated:
        return JsonResponse({"ok": False, "error": "Autenticazione richiesta."}, status=401)
    pn = normalize_part_number(request.GET.get("pn") or "")
    prog = (request.GET.get("prog") or "").strip()[:200]
    if not pn or not prog:
        return JsonResponse({"ok": False, "error": "Servono P/N e programma."}, status=400)
    dati = cmm.dati_programma(pn, prog, _data_get(request, "da"), _data_get(request, "a"))
    return JsonResponse({"ok": True, **dati})


@login_required
@require_POST
def pn_leggi_report(request):
    """Accoda la lettura dei report CMM della cartella del P/N."""
    from tasks.identity import normalize_part_number

    pn = normalize_part_number(request.POST.get("pn") or "")
    if not pn or not cmm.attivo():
        raise Http404
    from .tasks import accoda_lettura_pn

    if accoda_lettura_pn(pn):
        log_action(request, "produzione_report_cmm_leggi", "produzione", {"pn": pn})
        messages.success(request, "Lettura dei report avviata: ricarica la pagina tra qualche minuto.")
    else:
        messages.info(request, "La lettura dei report di questo P/N è già in corso.")
    return redirect(f"{reverse('produzione:pn_quote')}?{urlencode({'pn': pn})}")


@login_required
@require_GET
def report_cmm(request, pk: int):
    """Un report CMM: le quote fuori tolleranza (o tutte), con l'andamento di ciascuna e il link all'anomalia."""
    report = get_object_or_404(ReportCMM, pk=pk)
    tutte = request.GET.get("tutte") == "1"
    misure = report.misure.all() if tutte else report.misure.filter(Q(fuori=True) | Q(da_verificare=True))
    op = op_db.per_titolo(report.op) if report.op and op_db.disponibile() else None
    url_anomalia = ""
    if op:
        url_anomalia = f"{reverse('apertura_segnalazione')}?{urlencode({'op_id': op['id'], 'report_cmm': report.pk})}"
    return render(request, "produzione/report_cmm.html", _ctx(
        request, "pn", report=report, misure=list(misure.order_by("indice")), tutte=tutte, op=op,
        url_anomalia=url_anomalia, altri=ReportCMM.objects.filter(pn=report.pn, seriale=report.seriale)
        .exclude(pk=report.pk).exclude(seriale="")[:20] if report.seriale else [],
    ))


@login_required
@require_GET
def report_cmm_pdf(request, pk: int):
    """Il PDF dalla share, solo se sta sotto la cartella dei report."""
    report = get_object_or_404(ReportCMM, pk=pk)
    percorso = cmm.percorso_sicuro(report.percorso)
    if not percorso:
        raise Http404
    log_action(request, "produzione_report_cmm_pdf", "produzione", {"id": report.pk, "file": report.file})
    return FileResponse(open(percorso, "rb"), content_type="application/pdf", filename=report.file, as_attachment=False)


class DocumentoForm(forms.ModelForm):
    class Meta:
        model = DocumentoOP
        fields = ("tipo", "titolo", "revisione", "data", "percorso", "note")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        attuale = self.instance.tipo_id if self.instance.pk else None
        self.fields["tipo"].queryset = TipoDocumento.objects.filter(attivo=True) | TipoDocumento.objects.filter(pk=attuale)

    def clean_percorso(self):
        try:
            return normalizza_percorso(self.cleaned_data.get("percorso"))
        except ValueError as exc:
            raise forms.ValidationError(str(exc)) from exc


def _op_o_404(pk: int) -> dict:
    op = op_db.per_id(pk)
    if op is None:
        raise Http404
    return op


@login_required
@require_GET
def scheda(request, pk: int):
    op = _op_o_404(pk)
    modifica = None
    if (request.GET.get("documento") or "").isdigit():
        modifica = DocumentoOP.objects.filter(pk=int(request.GET["documento"]), op__iexact=op["op"]).first()
    form = DocumentoForm(instance=modifica) if modifica else DocumentoForm()
    return render(request, "produzione/scheda.html", _ctx(
        request, "scheda", form=form, modifica=modifica, tipi=TipoDocumento.objects.filter(attivo=True),
        apri_form=request.GET.get("aggiungi") == "1", **services.scheda(request, op),
    ))


@login_required
@require_POST
def documento(request, pk: int):
    """Nuovo documento dell'OP, o modifica di quello indicato in ``documento``."""
    _richiede(request, PERM_DOCUMENTI)
    op = _op_o_404(pk)
    istanza = None
    if (request.POST.get("documento") or "").isdigit():
        istanza = get_object_or_404(DocumentoOP, pk=int(request.POST["documento"]), op__iexact=op["op"])
    form = DocumentoForm(request.POST, instance=istanza)
    if not form.is_valid():
        return render(request, "produzione/scheda.html", _ctx(
            request, "scheda", form=form, modifica=istanza, tipi=TipoDocumento.objects.filter(attivo=True),
            apri_form=True, **services.scheda(request, op),
        ), status=400)
    doc = form.save(commit=False)
    doc.op = op["op"]
    if istanza is None:
        doc.creato_da = request.user
    doc.save()
    log_action(request, "produzione_documento_salva", "produzione",
               {"id": doc.pk, "op": doc.op, "tipo": doc.tipo.etichetta, "nuovo": istanza is None})
    messages.success(request, f"{doc.tipo.etichetta} salvato.")
    return redirect("produzione:scheda", pk)


@login_required
@require_POST
def documento_elimina(request, pk: int, doc_id: int):
    _richiede(request, PERM_DOCUMENTI)
    op = _op_o_404(pk)
    doc = get_object_or_404(DocumentoOP, pk=doc_id, op__iexact=op["op"])
    log_action(request, "produzione_documento_elimina", "produzione",
               {"id": doc.pk, "op": doc.op, "tipo": doc.tipo.etichetta, "titolo": doc.titolo})
    doc.delete()
    messages.success(request, "Documento eliminato.")
    return redirect("produzione:scheda", pk)


@login_required
def impostazioni(request):
    _richiede(request, PERM_IMPOSTAZIONI)
    if request.method == "POST":
        azione = request.POST.get("azione")
        etichetta = (request.POST.get("etichetta") or "").strip()[:80]
        descrizione = (request.POST.get("descrizione") or "").strip()[:255]
        ordine = int(request.POST["ordine"]) if (request.POST.get("ordine") or "").isdigit() else 100
        if azione == "nuovo":
            if not etichetta:
                messages.error(request, "Scrivi il nome del tipo.")
            elif TipoDocumento.objects.filter(etichetta__iexact=etichetta).exists():
                messages.error(request, f"Il tipo «{etichetta}» c'è già.")
            else:
                TipoDocumento.objects.create(etichetta=etichetta, descrizione=descrizione, ordine=ordine)
                messages.success(request, f"Tipo «{etichetta}» aggiunto.")
        elif azione == "salva" and (request.POST.get("id") or "").isdigit():
            tipo = get_object_or_404(TipoDocumento, pk=int(request.POST["id"]))
            if etichetta and not TipoDocumento.objects.filter(etichetta__iexact=etichetta).exclude(pk=tipo.pk).exists():
                tipo.etichetta = etichetta
            tipo.descrizione, tipo.ordine = descrizione, ordine
            tipo.attivo = request.POST.get("attivo") == "1"
            tipo.save()
            messages.success(request, f"Tipo «{tipo.etichetta}» salvato.")
        log_action(request, "produzione_impostazioni", "produzione", {"azione": azione, "etichetta": etichetta})
        return redirect("produzione:impostazioni")
    return render(request, "produzione/impostazioni.html", _ctx(
        request, "impostazioni", tipi=TipoDocumento.objects.all(),
    ))


@require_POST
def op_nuovo(request):
    """Crea un OP dal pannello laterale: risponde sempre in JSON."""
    if not request.user.is_authenticated:
        return JsonResponse({"ok": False, "error": "Autenticazione richiesta."}, status=401)
    if not nuovo_op.puo_creare(request):
        return JsonResponse({"ok": False, "error": "Non hai il permesso di creare OP."}, status=403)
    op, errori = nuovo_op.crea(request, request.POST)
    if errori:
        return JsonResponse({"ok": False, "errori": errori, "error": errori.get("__all__", "")}, status=400)
    log_action(request, "produzione_op_crea", "produzione", {"op": op["op"], "id": op["id"]})
    return JsonResponse({"ok": True, "op": op})


@login_required
@require_GET
def guida(request):
    if (request.GET.get("formato") or "") == "pdf":
        from core.guida_pdf import render_guida_pdf

        contenuto = render_guida_pdf(
            titolo=guida_mod.TITOLO, sottotitolo=guida_mod.SOTTOTITOLO, sezioni=guida_mod.SEZIONI,
            generato_da=request.user.get_username(), generato_il=timezone.localdate().strftime("%d-%m-%Y"),
        )
        resp = HttpResponse(contenuto, content_type="application/pdf")
        resp["Content-Disposition"] = 'attachment; filename="Guida_Ordini_di_produzione.pdf"'
        return resp
    return render(request, "produzione/guida.html", _ctx(
        request, "guida", sezioni=guida_mod.SEZIONI, titolo=guida_mod.TITOLO, sottotitolo=guida_mod.SOTTOTITOLO,
    ))
