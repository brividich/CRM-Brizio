"""Pagine dello scadenzario generale: pannello di gestione e scadenze generiche.

Rotte condivise (core/middleware.py ``_ACL_SHARED_ROUTE_NAMES``): il permesso si
decide qui, con le regole del pannello (scadenzario/permessi.py).
"""
from __future__ import annotations

import mimetypes
import os
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Count, Q
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.audit import log_action

from . import avvisi as servizio_avvisi
from . import catalogo
from . import collegamenti
from . import guida as guida_mod
from .controlli import da_sistemare
from .fonte import SOURCE, chiave_categoria
from .forms import CategoriaForm, RegolaForm, RinnovoForm, ScadenzaForm, VoceForm, opzioni_chi
from .notifiche import avvisa_utente
from .models import (
    AvvisoInviato, CategoriaScadenza, RegolaVisibilita, RinnovoScadenza, ScadenzaGenerica, VoceConfig, _email_pulite,
)
from .permessi import (
    categorie_gestibili, categorie_visibili, puo_gestire_categoria, puo_usare_modulo, puo_vedere_scadenza,
)
from .visibilita import CHIAVE_PANNELLO, SEP, antenati, chiavi_di, configurazione_di, puo_gestire_pannello

# ---------------------------------------------------------------------------
# Pannello di gestione
# ---------------------------------------------------------------------------


def _chiave_valida(chiave: str) -> bool:
    if chiave == CHIAVE_PANNELLO:
        return True
    return bool(chiave) and len(chiave) <= 300 and all(chiave.split(SEP)) and chiave.count(SEP) <= 2


def _torna(request, predefinito: str):
    """Torna a ``next`` se è una pagina dello scadenzario, altrimenti a ``predefinito``."""
    nxt = request.POST.get("next") or ""
    if nxt.startswith("/scadenze") and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return redirect(nxt)
    return redirect(predefinito)


def _dati_regola(post, chi: str = ""):
    """La scelta multipla «Aggiungi» manda ``chi=tipo:id``: lo traduce nei campi di RegolaForm."""
    tipo, _, valore = (chi or "").partition(":")
    if not tipo:
        return post
    dati = post.copy()
    dati["tipo"] = tipo
    dati[tipo] = valore
    return dati


def _ambito_regola(chiave: str, livello: str, valore: str) -> str | None:
    """Ambito da salvare, ``None`` se non valido.

    Il pannello e «Vede e gestisce» valgono per tutta la voce: sempre «Tutti».
    """
    if chiave == CHIAVE_PANNELLO or livello == RegolaVisibilita.LIVELLO_GESTISCE:
        return RegolaVisibilita.AMBITO_TUTTI
    valore = valore or RegolaVisibilita.AMBITO_TUTTI
    return valore if valore in dict(RegolaVisibilita.AMBITO_CHOICES) else None


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
        conf = configurazione_di(request)
        percorso_chiavi = [] if chiave == CHIAVE_PANNELLO else antenati(chiave)
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
            "generiche": chiave.startswith(SOURCE),
            "compare": conf.attiva(percorso_chiavi),
            "solo_regole": conf.modalita(percorso_chiavi) == VoceConfig.MODALITA_REGOLE,
            "n_regole": sum(len(regole_per_chiave.get(c, ())) for c in percorso_chiavi),
        }
    return render(request, "scadenzario/pages/gestione.html", {
        "radici": radici,
        "voci_cfg": voci_cfg,
        "regole_per_chiave": regole_per_chiave,
        "selezione": selezione,
        "opzioni_chi": opzioni_chi() if selezione else [],
        "da_sistemare": [] if selezione else da_sistemare(),
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
    scelte = [c for c in request.POST.getlist("chi") if c] or ([""] if request.POST.get("tipo") else [])
    if not scelte:
        messages.error(request, "Scegli almeno un ruolo o una persona.")
        return _torna(request, _url_gestione(chiave))
    salvate, persone = [], None
    try:
        with transaction.atomic():
            for chi in scelte:
                form = RegolaForm(_dati_regola(request.POST, chi), persone=persone)
                persone = form.fields["persona"].choices
                if not form.is_valid():
                    raise _RegolaNonValida("; ".join(e for errs in form.errors.values() for e in errs) or "Dati non validi.")
                ambito = _ambito_regola(chiave, form.cleaned_data["livello"], request.POST.get("ambito", ""))
                if ambito is None:
                    raise _RegolaNonValida("Ambito non valido.")
                salvate.append(_salva_regola(request, chiave, form, ambito))
    except _RegolaNonValida as errore:
        messages.error(request, str(errore))
        return _torna(request, _url_gestione(chiave))
    if len(salvate) == 1:
        messages.success(request, f"Regola salvata: {salvate[0].destinatario_label}.")
    else:
        messages.success(request, f"Regole salvate: {len(salvate)}.")
    return _torna(request, _url_gestione(chiave))


class _RegolaNonValida(Exception):
    pass


def _salva_regola(request, chiave: str, form, ambito: str):
    """Crea la regola, o aggiorna livello e ambito se il destinatario c'è già."""
    tipo = form.cleaned_data["tipo"]
    dati = {"chiave": chiave, "livello": form.cleaned_data["livello"], "ambito": ambito, "creato_da": request.user}
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
        regola.ambito = ambito
        regola.save(update_fields=["livello", "ambito"])
    else:
        regola = RegolaVisibilita.objects.create(**dati)
    log_action(request, "scadenzario_regola_aggiunta", "scadenzario",
               {"chiave": chiave, "regola": regola.destinatario_label, "livello": regola.livello, "ambito": regola.ambito})
    return regola


@login_required
@require_POST
def gestione_regola_modifica(request, regola_id: int):
    """Cambia ambito e livello di una regola esistente, senza toglierla e rimetterla."""
    if not puo_gestire_pannello(request):
        return HttpResponseForbidden("Solo chi gestisce lo scadenzario.")
    regola = get_object_or_404(RegolaVisibilita, pk=regola_id)
    livello = request.POST.get("livello") or regola.livello
    ambito = _ambito_regola(regola.chiave, livello, request.POST.get("ambito") or regola.ambito)
    if ambito is None or livello not in dict(RegolaVisibilita.LIVELLO_CHOICES):
        messages.error(request, "Valore non valido.")
        return _torna(request, _url_gestione(regola.chiave))
    regola.livello, regola.ambito = livello, ambito
    regola.save(update_fields=["livello", "ambito"])
    log_action(request, "scadenzario_regola_modificata", "scadenzario",
               {"chiave": regola.chiave, "regola": regola.destinatario_label, "livello": livello, "ambito": ambito})
    messages.success(request, f"Regola aggiornata: {regola.destinatario_label}.")
    return _torna(request, _url_gestione(regola.chiave))


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
    return _torna(request, _url_gestione(chiave))


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
def guida(request):
    """Guida completa, per tutti: non contiene dati, solo come funziona."""
    if (request.GET.get("formato") or "") == "pdf":
        from core.guida_pdf import render_guida_pdf

        contenuto = render_guida_pdf(
            titolo=guida_mod.TITOLO, sottotitolo=guida_mod.SOTTOTITOLO, sezioni=guida_mod.SEZIONI,
            generato_da=request.user.get_username(), generato_il=timezone.localdate().strftime("%d-%m-%Y"),
        )
        resp = HttpResponse(contenuto, content_type="application/pdf")
        resp["Content-Disposition"] = 'attachment; filename="Guida_Scadenzario.pdf"'
        return resp
    return render(request, "scadenzario/pages/guida.html", {
        "titolo": guida_mod.TITOLO, "sottotitolo": guida_mod.SOTTOTITOLO, "sezioni": guida_mod.SEZIONI,
    })


@login_required
def elenco(request):
    if not puo_usare_modulo(request):
        return HttpResponseForbidden("Non hai scadenze generiche da vedere.")
    oggi = timezone.localdate()
    qs = _qs_visibili(request)
    categoria = request.GET.get("categoria", "")
    testo = request.GET.get("q", "").strip()[:80]
    stato = request.GET.get("stato", "")
    senza = request.GET.get("senza", "")
    mostra_sospese = request.GET.get("sospese") == "1"
    if categoria.isdigit():
        qs = qs.filter(categoria_id=int(categoria))
    if testo:
        qs = qs.filter(Q(titolo__icontains=testo) | Q(descrizione__icontains=testo) | Q(ubicazione__icontains=testo))
    if not mostra_sospese:
        qs = qs.filter(is_active=True)
    if senza == "responsabile":
        qs = qs.filter(responsabile__isnull=True)
    gestibili = categorie_gestibili(request)
    tutte = list(qs.order_by("data_scadenza", "titolo"))
    if senza == "destinatari":
        tutte = [s for s in tutte if not s.destinatari]
    for s in tutte:
        s.giorni = s.giorni_alla_scadenza(oggi)
        s.n_destinatari = len(s.destinatari)
        s.gestibile = gestibili is None or s.categoria_id in gestibili
    # I contatori in alto restano quelli senza il filtro di stato: servono a sceglierlo.
    con_data = [s for s in tutte if s.giorni is not None]
    if stato == "scadute":
        righe = [s for s in con_data if s.giorni < 0]
    elif stato in ("30", "60", "90"):
        righe = [s for s in con_data if 0 <= s.giorni <= int(stato)]
    else:
        righe = tutte
    visibili = categorie_visibili(request)
    categorie = CategoriaScadenza.objects.order_by("nome")
    if visibili is not None:
        categorie = categorie.filter(pk__in=visibili)
    puo_massa = gestibili is None or bool(gestibili)
    if request.GET.get("format") == "xlsx":
        return _export_xlsx(righe)
    return render(request, "scadenzario/pages/elenco.html", {
        "righe": righe,
        "categorie": categorie,
        "filtro_categoria": categoria,
        "q": testo,
        "stato": stato,
        "senza": senza,
        "mostra_sospese": mostra_sospese,
        "puo_inserire": puo_massa,
        "puo_massa": puo_massa,
        "utenti": _utenti_attivi() if puo_massa else [],
        "oggi": oggi,
        "n_tutte": len(tutte),
        "n_scadute": sum(1 for s in con_data if s.giorni < 0),
        "n_30": sum(1 for s in con_data if 0 <= s.giorni <= 30),
    })


def _utenti_attivi():
    return get_user_model().objects.filter(is_active=True).order_by("last_name", "first_name", "username")


@login_required
@require_POST
def scadenze_massa(request):
    """Stessa modifica su più attività. Tocca solo quelle delle categorie che la persona gestisce."""
    predefinito = reverse("scadenzario:elenco")
    gestibili = categorie_gestibili(request)
    if gestibili is not None and not gestibili:
        return HttpResponseForbidden("Non puoi modificare queste attività.")
    azione = request.POST.get("azione", "")
    ids = [int(x) for x in request.POST.getlist("ids") if x.isdigit()][:500]
    scadenze = list(ScadenzaGenerica.objects.select_related("categoria").filter(pk__in=ids))
    if gestibili is not None:
        scadenze = [s for s in scadenze if s.categoria_id in gestibili]
    if not scadenze:
        messages.error(request, "Seleziona almeno un'attività.")
        return _torna(request, predefinito)

    email = _email_pulite(request.POST.get("email", ""))
    if azione == "responsabile":
        uid = request.POST.get("responsabile", "")
        responsabile = None
        if uid:
            responsabile = _utenti_attivi().filter(pk=uid).first() if uid.isdigit() else None
            if responsabile is None:
                messages.error(request, "Responsabile non valido.")
                return _torna(request, predefinito)
        for s in scadenze:
            s.responsabile = responsabile
            s.save(update_fields=["responsabile", "aggiornato_il"])
            if responsabile and responsabile.pk != request.user.pk:
                avvisa_utente(responsabile, "scadenza_assegnata", f"Sei responsabile dell'attività: {s.titolo}.",
                              reverse("scadenzario:scadenza_dettaglio", args=[s.pk]))
    elif azione in ("destinatari_aggiungi", "destinatari_sostituisci"):
        try:
            for indirizzo in email:
                validate_email(indirizzo)
        except ValidationError:
            messages.error(request, "Controlla gli indirizzi: almeno uno non è valido.")
            return _torna(request, predefinito)
        if azione == "destinatari_aggiungi" and not email:
            messages.error(request, "Scrivi almeno un indirizzo.")
            return _torna(request, predefinito)
        for s in scadenze:
            nuovi = s.destinatari + email if azione == "destinatari_aggiungi" else email
            s.email_avviso = ", ".join(_email_pulite(", ".join(nuovi)))
            s.save(update_fields=["email_avviso", "aggiornato_il"])
    elif azione == "destinatari_categoria":
        for s in scadenze:
            s.email_avviso = ", ".join(s.categoria.destinatari)
            s.save(update_fields=["email_avviso", "aggiornato_il"])
    elif azione in ("sospendi", "riattiva"):
        for s in scadenze:
            s.is_active = azione == "riattiva"
            s.save(update_fields=["is_active", "aggiornato_il"])
    else:
        messages.error(request, "Azione non valida.")
        return _torna(request, predefinito)
    log_action(request, "scadenze_generiche_modifica_massa", "scadenzario",
               {"azione": azione, "ids": [s.pk for s in scadenze]})
    n = len(scadenze)
    messages.success(request, f"Fatto su {n} attività." if n != 1 else "Fatto su 1 attività.")
    return _torna(request, predefinito)


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
    return render(request, "scadenzario/pages/scadenza_form.html", {
        "form": form, "nuova": True, "email_categorie": _email_categorie(form),
    })


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
    return render(request, "scadenzario/pages/scadenza_form.html", {
        "form": form, "nuova": False, "s": s, "email_categorie": _email_categorie(form),
    })


def _email_categorie(form) -> dict:
    """Destinatari di ogni categoria del form, per «Usa quelli della categoria»."""
    return {str(c.pk): ", ".join(c.destinatari) for c in form.fields["categoria"].queryset}


@login_required
def scadenza_dettaglio(request, pk: int):
    s = get_object_or_404(ScadenzaGenerica.objects.select_related("categoria", "responsabile", "asset", "fornitore"), pk=pk)
    if not puo_vedere_scadenza(request, s):
        return HttpResponseForbidden("Non puoi vedere questa attività.")
    gestisce = puo_gestire_categoria(request, s.categoria_id)
    if s.unita:
        collegamenti.allinea_unite()
        s.refresh_from_db(fields=["data_scadenza"])
    cerca_tipo, cerca = request.GET.get("cerca_tipo", ""), request.GET.get("cerca", "")
    return render(request, "scadenzario/pages/scadenza_dettaglio.html", {
        "s": s,
        "collegamenti": collegamenti.collegamenti_di(s),
        "tipi_collegamento": [(t.codice, t.etichetta) for t in collegamenti.TIPI.values()],
        "cerca_tipo": cerca_tipo,
        "cerca": cerca,
        "risultati": collegamenti.cerca(cerca_tipo, cerca) if gestisce else [],
        "giorni": s.giorni_alla_scadenza(),
        "oggi": timezone.localdate(),
        "gestisce": gestisce,
        "rinnovi": s.rinnovi.select_related("registrato_da")[:50],
        "avvisi": s.avvisi.all()[:20],
        "rinnovo_form": RinnovoForm(initial={"eseguito_il": timezone.localdate()}),
    })


def _dopo_rinnovo(request, s):
    """Dal calendario o dall'elenco (``next`` = /scadenze…) si torna lì, altrimenti alla scheda."""
    return _torna(request, reverse("scadenzario:scadenza_dettaglio", args=[s.pk]))


@login_required
def collega_elenco(request):
    """Le attività ancora isolate, con i possibili collegamenti da confermare."""
    gestibili = categorie_gestibili(request)
    if gestibili is not None and not gestibili:
        return HttpResponseForbidden("Non gestisci categorie.")
    qs = ScadenzaGenerica.objects.select_related("categoria").filter(is_active=True).order_by("categoria__nome", "titolo")
    if gestibili is not None:
        qs = qs.filter(categoria_id__in=gestibili)
    attive = list(qs)
    isolate = [s for s in attive if not (s.collegata_tipo or s.asset_id or s.fornitore_id)]
    proposte = collegamenti.suggerimenti(isolate)
    from sistema_gestione.models import Certificazione

    return render(request, "scadenzario/pages/collega.html", {
        "righe": [{"s": s, "proposte": proposte[s.pk]} for s in isolate if s.pk in proposte],
        "senza_proposte": sum(1 for s in isolate if s.pk not in proposte),
        "gia_collegate": len(attive) - len(isolate),
        "senza_certificazioni": not Certificazione.objects.filter(attiva=True).exists(),
    })


def _dopo_collega(request, s):
    return _torna(request, reverse("scadenzario:scadenza_dettaglio", args=[s.pk]))


@login_required
@require_POST
def scadenza_collega(request, pk: int):
    s = get_object_or_404(ScadenzaGenerica, pk=pk)
    if not puo_gestire_categoria(request, s.categoria_id):
        return HttpResponseForbidden("Non puoi modificare questa attività.")
    tipo, oggetto = request.POST.get("tipo", ""), request.POST.get("oggetto", "")
    unisci = request.POST.get("unisci") == "1"
    if not oggetto.isdigit():
        messages.error(request, "Scegli a cosa collegare l'attività.")
        return _dopo_collega(request, s)
    try:
        collegamenti.collega(s, tipo, int(oggetto), unisci=unisci)
    except ValueError as exc:
        messages.error(request, str(exc))
        return _dopo_collega(request, s)
    log_action(request, "scadenza_generica_collegata", "scadenzario",
               {"id": s.pk, "tipo": tipo, "oggetto": int(oggetto), "unita": unisci})
    messages.success(request, f"«{s.titolo}» unita al modulo." if unisci else f"«{s.titolo}» collegata.")
    return _dopo_collega(request, s)


@login_required
@require_POST
def scadenza_scollega(request, pk: int):
    s = get_object_or_404(ScadenzaGenerica, pk=pk)
    if not puo_gestire_categoria(request, s.categoria_id):
        return HttpResponseForbidden("Non puoi modificare questa attività.")
    tipo = request.POST.get("tipo", "")
    try:
        if request.POST.get("solo_separa") == "1":
            collegamenti.separa(s)
        else:
            collegamenti.scollega(s, tipo)
    except ValueError as exc:
        messages.error(request, str(exc))
        return _dopo_collega(request, s)
    log_action(request, "scadenza_generica_scollegata", "scadenzario",
               {"id": s.pk, "tipo": tipo, "solo_separa": request.POST.get("solo_separa") == "1"})
    messages.success(request, "Collegamento aggiornato.")
    return _dopo_collega(request, s)


@login_required
@require_POST
def scadenza_rinnovo(request, pk: int):
    s = get_object_or_404(ScadenzaGenerica, pk=pk)
    if not puo_gestire_categoria(request, s.categoria_id):
        return HttpResponseForbidden("Non puoi rinnovare questa attività.")
    if s.unita:
        messages.error(request, "Questa attività prende la data dal modulo collegato: aggiornala lì, oppure separala.")
        return _dopo_rinnovo(request, s)
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
    categorie_righe = list(qs)
    attive = ScadenzaGenerica.objects.filter(is_active=True).order_by()
    n_attivita = dict(attive.values_list("categoria_id").annotate(n=Count("pk")))
    n_scadute = dict(attive.filter(data_scadenza__lt=timezone.localdate()).values_list("categoria_id").annotate(n=Count("pk")))
    regole = RegolaVisibilita.objects.select_related("ruolo_portale", "ruolo_aziendale")
    regole_fonte = list(regole.filter(chiave=SOURCE))
    per_chiave: dict[str, list] = {}
    for r in regole.filter(chiave__startswith=SOURCE + SEP):
        per_chiave.setdefault(r.chiave, []).append(r)
    for c in categorie_righe:
        c.n_attivita = n_attivita.get(c.pk, 0)
        c.n_scadute = n_scadute.get(c.pk, 0)
        c.regole = per_chiave.get(_chiave_cat(c.pk), [])
    return render(request, "scadenzario/pages/categorie.html", {
        "categorie": categorie_righe, "regole_fonte": regole_fonte, "form": form,
        "puo_pannello": puo_gestire_pannello(request),
    })


def _chiave_cat(categoria_id: int) -> str:
    return chiavi_di(SOURCE, chiave_categoria(categoria_id))[1]


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
    contesto = {"form": form, "cat": cat, "puo_pannello": puo_gestire_pannello(request)}
    if contesto["puo_pannello"]:
        regole = RegolaVisibilita.objects.select_related("ruolo_portale", "ruolo_aziendale")
        contesto.update({
            "chiave": _chiave_cat(cat.pk),
            "regole": list(regole.filter(chiave=_chiave_cat(cat.pk))),
            "regole_fonte": list(regole.filter(chiave=SOURCE)),
            "opzioni_chi": opzioni_chi(),
            "torna": request.path,
        })
    return render(request, "scadenzario/pages/categoria_form.html", contesto)


@login_required
def avvisi(request):
    visibili = categorie_visibili(request, solo_intere=True)
    if visibili is not None and not visibili:
        return HttpResponseForbidden("Non hai scadenze generiche da vedere.")
    qs = AvvisoInviato.objects.select_related("scadenza", "categoria")
    if visibili is not None:
        qs = qs.filter(Q(categoria_id__in=visibili) | Q(scadenza__categoria_id__in=visibili))
    return render(request, "scadenzario/pages/avvisi.html", {
        "avvisi": qs[:300],
        "anteprima": servizio_avvisi.anteprima(categorie=visibili),
        "ora_invio": "{:02d}:{:02d}".format(*servizio_avvisi.ORA_AVVISI),
        "riepilogo": {
            "giorno": servizio_avvisi.prossimo_riepilogo(),
            "ora": "{:02d}:{:02d}".format(*servizio_avvisi.ORA_RIEPILOGO),
        },
    })
