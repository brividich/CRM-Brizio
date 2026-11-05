"""Pagine dello scadenzario generale: pannello di gestione e scadenze generiche.

Rotte condivise (core/middleware.py ``_ACL_SHARED_ROUTE_NAMES``): il permesso si
decide qui, con le regole del pannello (scadenzario/permessi.py).
"""
from __future__ import annotations

import mimetypes
import os
from datetime import timedelta
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_action

from . import catalogo
from .forms import CategoriaForm, RegolaForm, RinnovoForm, ScadenzaForm, VoceForm
from .models import (
    AvvisoInviato, CategoriaScadenza, RegolaVisibilita, RinnovoScadenza, ScadenzaGenerica, VoceConfig,
)
from .permessi import (
    categorie_gestibili, categorie_visibili, puo_gestire_categoria, puo_usare_modulo, puo_vedere_scadenza,
)
from .visibilita import CHIAVE_PANNELLO, SEP, puo_gestire_pannello

# ---------------------------------------------------------------------------
# Pannello di gestione
# ---------------------------------------------------------------------------


def _chiave_valida(chiave: str) -> bool:
    if chiave == CHIAVE_PANNELLO:
        return True
    return bool(chiave) and len(chiave) <= 300 and all(chiave.split(SEP)) and chiave.count(SEP) <= 2


def _url_gestione(chiave: str = "") -> str:
    url = reverse("scadenzario:gestione")
    return f"{url}?{urlencode({'chiave': chiave})}" if chiave else url


@login_required
def gestione(request):
    if not puo_gestire_pannello(request):
        return HttpResponseForbidden("Solo chi gestisce lo scadenzario.")
    voci_cfg = {v.chiave: v for v in VoceConfig.objects.all()}
    regole = list(RegolaVisibilita.objects.select_related("ruolo_portale", "ruolo_aziendale"))
    regole_per_chiave: dict[str, list] = {}
    for r in regole:
        regole_per_chiave.setdefault(r.chiave, []).append(r)
    configurate = {c: v.etichetta for c, v in voci_cfg.items()}
    for r in regole:
        configurate.setdefault(r.chiave, "")
    configurate.pop(CHIAVE_PANNELLO, None)
    radici = catalogo.costruisci(configurate=configurate)

    chiave = request.GET.get("chiave", "").strip()
    selezione = None
    if chiave and _chiave_valida(chiave):
        nodo = catalogo.trova(radici, chiave)
        cfg = voci_cfg.get(chiave)
        selezione = {
            "chiave": chiave,
            "nodo": nodo,
            "pannello": chiave == CHIAVE_PANNELLO,
            "percorso": [] if chiave == CHIAVE_PANNELLO else catalogo.percorso_etichette(radici, chiave),
            "cfg": cfg,
            "regole": regole_per_chiave.get(chiave, []),
            "regole_ereditate": [
                (etichetta, regole_per_chiave[a])
                for a, etichetta in catalogo.percorso_etichette(radici, chiave)[:-1]
                if regole_per_chiave.get(a)
            ] if chiave != CHIAVE_PANNELLO else [],
            "voce_form": VoceForm(initial={
                "attiva": "" if not cfg or cfg.attiva is None else ("1" if cfg.attiva else "0"),
                "modalita": cfg.modalita if cfg else "",
            }),
            "regola_form": RegolaForm(),
            "generiche": chiave.startswith("generiche"),
        }
    return render(request, "scadenzario/pages/gestione.html", {
        "radici": radici,
        "voci_cfg": voci_cfg,
        "regole_per_chiave": regole_per_chiave,
        "selezione": selezione,
        "chiave_pannello": CHIAVE_PANNELLO,
        "n_regole_pannello": len(regole_per_chiave.get(CHIAVE_PANNELLO, [])),
    })


@login_required
@require_POST
def gestione_voce(request):
    if not puo_gestire_pannello(request):
        return HttpResponseForbidden("Solo chi gestisce lo scadenzario.")
    chiave = request.POST.get("chiave", "").strip()
    if not _chiave_valida(chiave) or chiave == CHIAVE_PANNELLO:
        messages.error(request, "Voce non valida.")
        return redirect(_url_gestione())
    form = VoceForm(request.POST)
    if form.is_valid():
        attiva = {"": None, "1": True, "0": False}[form.cleaned_data["attiva"] or ""]
        modalita = form.cleaned_data["modalita"] or ""
        if attiva is None and not modalita:
            VoceConfig.objects.filter(chiave=chiave).delete()
        else:
            VoceConfig.objects.update_or_create(chiave=chiave, defaults={
                "attiva": attiva, "modalita": modalita,
                "etichetta": request.POST.get("etichetta", "")[:300], "aggiornato_da": request.user,
            })
        log_action(request, "scadenzario_voce_impostata", "scadenzario",
                   {"chiave": chiave, "attiva": attiva, "modalita": modalita})
        messages.success(request, "Impostazione salvata.")
    return redirect(_url_gestione(chiave))


@login_required
@require_POST
def gestione_regola_aggiungi(request):
    if not puo_gestire_pannello(request):
        return HttpResponseForbidden("Solo chi gestisce lo scadenzario.")
    chiave = request.POST.get("chiave", "").strip()
    if not _chiave_valida(chiave):
        messages.error(request, "Voce non valida.")
        return redirect(_url_gestione())
    form = RegolaForm(request.POST)
    if not form.is_valid():
        messages.error(request, "; ".join(e for errs in form.errors.values() for e in errs) or "Dati non validi.")
        return redirect(_url_gestione(chiave))
    tipo = form.cleaned_data["tipo"]
    dati = {"chiave": chiave, "livello": form.cleaned_data["livello"], "creato_da": request.user}
    if tipo == "ruolo_portale":
        dati["ruolo_portale"] = form.cleaned_data["ruolo_portale"]
        doppione = RegolaVisibilita.objects.filter(chiave=chiave, ruolo_portale=dati["ruolo_portale"])
    elif tipo == "ruolo_aziendale":
        dati["ruolo_aziendale"] = form.cleaned_data["ruolo_aziendale"]
        doppione = RegolaVisibilita.objects.filter(chiave=chiave, ruolo_aziendale=dati["ruolo_aziendale"])
    else:
        uid = form.cleaned_data["persona"]
        dati["persona_legacy_id"] = uid
        dati["persona_nome"] = dict(form.fields["persona"].choices).get(uid, "")[:200]
        doppione = RegolaVisibilita.objects.filter(chiave=chiave, persona_legacy_id=uid)
    regola = doppione.first()
    if regola:
        regola.livello = dati["livello"]
        regola.save(update_fields=["livello"])
    else:
        regola = RegolaVisibilita.objects.create(**dati)
    log_action(request, "scadenzario_regola_aggiunta", "scadenzario",
               {"chiave": chiave, "regola": regola.destinatario_label, "livello": regola.livello})
    messages.success(request, f"Regola salvata: {regola.destinatario_label}.")
    return redirect(_url_gestione(chiave))


@login_required
@require_POST
def gestione_regola_togli(request, regola_id: int):
    if not puo_gestire_pannello(request):
        return HttpResponseForbidden("Solo chi gestisce lo scadenzario.")
    regola = get_object_or_404(RegolaVisibilita, pk=regola_id)
    chiave = regola.chiave
    log_action(request, "scadenzario_regola_tolta", "scadenzario",
               {"chiave": chiave, "regola": regola.destinatario_label})
    regola.delete()
    messages.success(request, "Regola tolta.")
    return redirect(_url_gestione(chiave))


# ---------------------------------------------------------------------------
# Scadenze generiche
# ---------------------------------------------------------------------------


def _qs_visibili(request):
    qs = ScadenzaGenerica.objects.select_related("categoria", "responsabile", "asset")
    visibili = categorie_visibili(request)
    if visibili is None:
        return qs
    user_id = getattr(request.user, "id", None)
    ammesse = [s.pk for s in qs.filter(Q(categoria_id__in=visibili) | Q(responsabile_id=user_id))
               if puo_vedere_scadenza(request, s)]
    return qs.filter(pk__in=ammesse)


@login_required
def elenco(request):
    if not puo_usare_modulo(request):
        return HttpResponseForbidden("Non hai scadenze generiche da vedere.")
    oggi = timezone.localdate()
    qs = _qs_visibili(request)
    categoria = request.GET.get("categoria", "")
    testo = request.GET.get("q", "").strip()[:80]
    stato = request.GET.get("stato", "")
    mostra_sospese = request.GET.get("sospese") == "1"
    if categoria.isdigit():
        qs = qs.filter(categoria_id=int(categoria))
    if testo:
        qs = qs.filter(Q(titolo__icontains=testo) | Q(descrizione__icontains=testo) | Q(ubicazione__icontains=testo))
    if not mostra_sospese:
        qs = qs.filter(is_active=True)
    if stato == "scadute":
        qs = qs.filter(data_scadenza__lt=oggi)
    elif stato in ("30", "60", "90"):
        qs = qs.filter(data_scadenza__gte=oggi, data_scadenza__lte=oggi + timedelta(days=int(stato)))
    righe = list(qs.order_by("data_scadenza", "titolo"))
    for s in righe:
        s.giorni = s.giorni_alla_scadenza(oggi)
    gestibili = categorie_gestibili(request)
    visibili = categorie_visibili(request)
    categorie = CategoriaScadenza.objects.order_by("nome")
    if visibili is not None:
        categorie = categorie.filter(pk__in=visibili)
    if request.GET.get("format") == "xlsx":
        return _export_xlsx(righe)
    return render(request, "scadenzario/pages/elenco.html", {
        "righe": righe,
        "categorie": categorie,
        "filtro_categoria": categoria,
        "q": testo,
        "stato": stato,
        "mostra_sospese": mostra_sospese,
        "puo_inserire": gestibili is None or bool(gestibili),
        "puo_pannello": puo_gestire_pannello(request),
        "n_scadute": sum(1 for s in righe if s.giorni is not None and s.giorni < 0),
        "n_30": sum(1 for s in righe if s.giorni is not None and 0 <= s.giorni <= 30),
    })


def _export_xlsx(righe):
    from io import BytesIO

    from django.http import HttpResponse
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Scadenze"
    ws.append(["Categoria", "Attività", "Descrizione", "Ubicazione", "Ultimo controllo", "Validità (mesi)",
               "Scadenza", "Giorni", "Attiva"])
    for s in righe:
        ws.append([s.categoria.nome, s.titolo, s.descrizione, s.ubicazione, s.ultimo_controllo, s.validita_mesi,
                   s.data_scadenza, s.giorni, "Sì" if s.is_active else "No"])
    buf = BytesIO()
    wb.save(buf)
    resp = HttpResponse(buf.getvalue(),
                        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = 'attachment; filename="scadenze_generiche.xlsx"'
    return resp


@login_required
def scadenza_nuova(request):
    gestibili = categorie_gestibili(request)
    if gestibili is not None and not gestibili:
        return HttpResponseForbidden("Non puoi inserire scadenze.")
    if request.method == "POST":
        form = ScadenzaForm(request.POST, categorie_ammesse=gestibili)
        if form.is_valid():
            s = form.save(commit=False)
            s.data_scadenza = form.cleaned_data.get("data_scadenza")
            s.creato_da = request.user
            s.save()
            log_action(request, "scadenza_generica_creata", "scadenzario", {"id": s.pk})
            messages.success(request, f"Attività «{s.titolo}» inserita.")
            return redirect("scadenzario:scadenza_dettaglio", pk=s.pk)
    else:
        iniziali = {}
        if request.GET.get("categoria", "").isdigit():
            iniziali["categoria"] = int(request.GET["categoria"])
        form = ScadenzaForm(initial=iniziali, categorie_ammesse=gestibili)
    return render(request, "scadenzario/pages/scadenza_form.html", {"form": form, "nuova": True})


@login_required
def scadenza_modifica(request, pk: int):
    s = get_object_or_404(ScadenzaGenerica, pk=pk)
    if not puo_gestire_categoria(request, s.categoria_id):
        return HttpResponseForbidden("Non puoi modificare questa attività.")
    gestibili = categorie_gestibili(request)
    if request.method == "POST":
        form = ScadenzaForm(request.POST, instance=s, categorie_ammesse=gestibili)
        if form.is_valid():
            s = form.save(commit=False)
            s.data_scadenza = form.cleaned_data.get("data_scadenza")
            s.save()
            log_action(request, "scadenza_generica_modificata", "scadenzario", {"id": s.pk})
            messages.success(request, "Attività aggiornata.")
            return redirect("scadenzario:scadenza_dettaglio", pk=s.pk)
    else:
        form = ScadenzaForm(instance=s, categorie_ammesse=gestibili)
    return render(request, "scadenzario/pages/scadenza_form.html", {"form": form, "nuova": False, "s": s})


@login_required
def scadenza_dettaglio(request, pk: int):
    s = get_object_or_404(ScadenzaGenerica.objects.select_related("categoria", "responsabile", "asset", "fornitore"), pk=pk)
    if not puo_vedere_scadenza(request, s):
        return HttpResponseForbidden("Non puoi vedere questa attività.")
    gestisce = puo_gestire_categoria(request, s.categoria_id)
    return render(request, "scadenzario/pages/scadenza_dettaglio.html", {
        "s": s,
        "giorni": s.giorni_alla_scadenza(),
        "gestisce": gestisce,
        "rinnovi": s.rinnovi.select_related("registrato_da")[:50],
        "avvisi": s.avvisi.all()[:20],
        "rinnovo_form": RinnovoForm(initial={"eseguito_il": timezone.localdate()}),
    })


def _dopo_rinnovo(request, s):
    """Dal calendario (``next`` = /scadenze…) si torna lì, altrimenti alla scheda."""
    from django.utils.http import url_has_allowed_host_and_scheme

    nxt = request.POST.get("next") or ""
    if nxt.startswith("/scadenze") and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return redirect(nxt)
    return redirect("scadenzario:scadenza_dettaglio", pk=s.pk)


@login_required
@require_POST
def scadenza_rinnovo(request, pk: int):
    s = get_object_or_404(ScadenzaGenerica, pk=pk)
    if not puo_gestire_categoria(request, s.categoria_id):
        return HttpResponseForbidden("Non puoi rinnovare questa attività.")
    form = RinnovoForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, "; ".join(e for errs in form.errors.values() for e in errs))
        return _dopo_rinnovo(request, s)
    eseguito = form.cleaned_data["eseguito_il"]
    if eseguito > timezone.localdate():
        messages.error(request, "La data del controllo non può essere futura.")
        return _dopo_rinnovo(request, s)
    nuova = form.cleaned_data.get("nuova_scadenza")
    if not nuova and s.validita_mesi:
        from .models import _add_months

        nuova = _add_months(eseguito, s.validita_mesi)
    allegato = form.cleaned_data.get("allegato")
    r = RinnovoScadenza(scadenza=s, eseguito_il=eseguito, scadenza_precedente=s.data_scadenza,
                        nuova_scadenza=nuova, note=form.cleaned_data.get("note", ""), registrato_da=request.user)
    if allegato:
        r.allegato = allegato
        r.allegato_nome = os.path.basename(allegato.name)[:255]
    r.save()
    s.ultimo_controllo = eseguito
    if nuova:
        s.data_scadenza = nuova
    s.save(update_fields=["ultimo_controllo", "data_scadenza", "aggiornato_il"])
    log_action(request, "scadenza_generica_rinnovata", "scadenzario",
               {"id": s.pk, "eseguito_il": str(eseguito), "nuova_scadenza": str(nuova or "")})
    messages.success(request, f"Rinnovo registrato{f': prossima scadenza {nuova:%d/%m/%Y}' if nuova else ''}.")
    return _dopo_rinnovo(request, s)


@login_required
def rinnovo_allegato(request, pk: int):
    r = get_object_or_404(RinnovoScadenza.objects.select_related("scadenza"), pk=pk)
    if not puo_vedere_scadenza(request, r.scadenza):
        return HttpResponseForbidden("Allegato non disponibile.")
    if not r.allegato or not r.allegato.name:
        raise Http404("Nessun allegato.")
    try:
        handle = r.allegato.storage.open(r.allegato.name, "rb")
    except FileNotFoundError:
        raise Http404("File non trovato.")
    nome = r.allegato_nome or os.path.basename(r.allegato.name)
    tipo = mimetypes.guess_type(nome)[0] or "application/octet-stream"
    return FileResponse(handle, as_attachment=True, filename=nome, content_type=tipo)


@login_required
def categorie(request):
    gestibili = categorie_gestibili(request)
    if not puo_gestire_pannello(request) and not gestibili:
        return HttpResponseForbidden("Non gestisci categorie.")
    if request.method == "POST":
        if not puo_gestire_pannello(request):
            return HttpResponseForbidden("Solo chi gestisce lo scadenzario crea categorie.")
        form = CategoriaForm(request.POST)
        if form.is_valid():
            cat = form.save()
            log_action(request, "scadenzario_categoria_creata", "scadenzario", {"id": cat.pk})
            messages.success(request, f"Categoria «{cat.nome}» creata.")
            return redirect("scadenzario:categorie")
    else:
        form = CategoriaForm()
    qs = CategoriaScadenza.objects.order_by("nome")
    if gestibili is not None:
        qs = qs.filter(pk__in=gestibili)
    return render(request, "scadenzario/pages/categorie.html", {
        "categorie": qs, "form": form, "puo_pannello": puo_gestire_pannello(request),
    })


@login_required
def categoria_modifica(request, pk: int):
    cat = get_object_or_404(CategoriaScadenza, pk=pk)
    if not puo_gestire_categoria(request, cat.pk):
        return HttpResponseForbidden("Non puoi modificare questa categoria.")
    if request.method == "POST":
        form = CategoriaForm(request.POST, instance=cat)
        if form.is_valid():
            form.save()
            log_action(request, "scadenzario_categoria_modificata", "scadenzario", {"id": cat.pk})
            messages.success(request, "Categoria aggiornata.")
            return redirect("scadenzario:categorie")
    else:
        form = CategoriaForm(instance=cat)
    return render(request, "scadenzario/pages/categoria_form.html", {"form": form, "cat": cat})


@login_required
def avvisi(request):
    visibili = categorie_visibili(request)
    if visibili is not None and not visibili:
        return HttpResponseForbidden("Non hai scadenze generiche da vedere.")
    qs = AvvisoInviato.objects.select_related("scadenza", "categoria")
    if visibili is not None:
        qs = qs.filter(Q(categoria_id__in=visibili) | Q(scadenza__categoria_id__in=visibili))
    return render(request, "scadenzario/pages/avvisi.html", {"avvisi": qs[:300]})
