"""Ordini di produzione: elenco degli OP, scheda con i documenti di produzione, impostazioni."""
from __future__ import annotations

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from core import ordini_produzione as op_db
from core.acl_v2 import request_has_permission_code
from core.audit import log_action
from core.paginazione import pagina_elenco
from tasks.tech_paths import normalizza_percorso

from . import guida as guida_mod
from . import nuovo_op, services
from .acl_bootstrap import PERM_DOCUMENTI, PERM_IMPOSTAZIONI
from .models import DocumentoOP, TipoDocumento


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
    righe = services.righe_elenco(request, testo, stato) if disponibile else []
    return render(request, "produzione/elenco.html", _ctx(
        request, "elenco", disponibile=disponibile, pagina=pagina_elenco(request, righe), totale=len(righe),
        q=testo, stato=stato, stati=op_db.stati() if disponibile else [], nuovo_op=nuovo_op.contesto(request),
    ))


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
        **services.scheda(request, op),
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
