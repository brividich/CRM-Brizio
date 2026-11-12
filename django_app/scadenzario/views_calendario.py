"""Azioni della pagina ``/scadenze`` (calendario): presa in carico e viste salvate.

Rotte condivise (prefisso ``/scadenze/azioni/`` in ``core/middleware.py``): il
permesso si decide qui. Si prende in carico solo una scadenza che si vede.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.audit import log_action

from .calendario import chiave_scadenza, descrizione_scadenza, nome_utente, pulisci_parametri
from .models import PresaInCarico, VistaSalvata
from .notifiche import avvisa_utente
from .visibilita import puo_gestire_pannello


def _torna(request):
    nxt = request.POST.get("next") or ""
    # Si torna anche alla scheda del modulo da cui si è presa la scadenza.
    if nxt.startswith("/") and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return redirect(nxt)
    return redirect(reverse("scadenze_globali"))


def _scadenza_visibile(request, chiave: str, data_iso: str):
    """La scadenza con questa impronta fra quelle che chi chiede vede oggi."""
    from dashboard.scadenze_providers import ORIZZONTE_GIORNI, collect_all

    oggi = timezone.localdate()
    try:
        data = date.fromisoformat(data_iso)
    except (TypeError, ValueError):
        return None
    orizzonte = max(oggi + timedelta(days=ORIZZONTE_GIORNI), data + timedelta(days=1))
    for v in collect_all(request, oggi=oggi, orizzonte=orizzonte):
        if v.data_scadenza == data and chiave_scadenza(v) == chiave:
            return v
    return None


@login_required
def scheda_riquadro(request):
    """Scadenze di una scheda di modulo: solo ciò che chi chiede vede già nello Scadenzario."""
    from urllib.parse import urlencode, urlsplit

    from dashboard.scadenze_providers import PROVIDERS, collect_all
    from dashboard.views_scadenze import _azioni

    from . import collegamenti
    from .permessi import puo_vedere_scadenza

    percorso = (request.GET.get("percorso") or "").strip()
    if not percorso.startswith("/"):
        return HttpResponse("")
    fonti = {f for f in (request.GET.get("fonti") or "").split(",") if f in PROVIDERS}
    voci = []
    if fonti:
        voci = [v for v in collect_all(request, sources=fonti) if urlsplit(v.url or "").path == percorso]
        _azioni(request, voci)
    tipo, _sep, oggetto = (request.GET.get("collegata") or "").partition(":")
    collegate = []
    if oggetto.isdigit():
        oggi = timezone.localdate()
        collegate = [s for s in collegamenti.attivita_collegate(tipo, int(oggetto)) if puo_vedere_scadenza(request, s)]
        for s in collegate:
            s.scaduta = bool(s.data_scadenza and s.data_scadenza < oggi)
    if not voci and not collegate:
        return HttpResponse("")
    nome = (request.GET.get("nome") or "").strip()
    return render(request, "scadenzario/components/riquadro_contenuto.html", {
        "voci": voci, "collegate": collegate, "percorso": percorso,
        "link_tutte": reverse("scadenze_globali") + (f"?{urlencode({'q': nome})}" if nome else ""),
    })


def _persona_scelta(valore):
    """«Nome Cognome (username)» dall'elenco di «Assegna a»; None se non è una persona attiva."""
    import re

    from django.contrib.auth import get_user_model

    trovato = re.search(r"\(([^()]+)\)\s*$", valore or "")
    if not trovato:
        return None
    return get_user_model().objects.filter(is_active=True, username=trovato.group(1)).first()


@login_required
@require_POST
def presa_in_carico(request):
    chiave = (request.POST.get("chiave") or "").strip()[:64]
    azione = request.POST.get("azione") or "prendi"
    esistente = PresaInCarico.objects.filter(chiave=chiave).select_related("utente").first()
    if azione == "lascia":
        if esistente and (esistente.utente_id == request.user.id or puo_gestire_pannello(request)):
            log_action(request, "scadenza_lasciata", "scadenzario",
                       {"scadenza": esistente.descrizione, "era_di": esistente.utente_id})
            esistente.delete()
            messages.success(request, "Presa in carico tolta.")
        return _torna(request)
    v = _scadenza_visibile(request, chiave, request.POST.get("data") or "")
    if v is None:
        return HttpResponseForbidden("Scadenza non trovata fra quelle che puoi vedere.")
    nota = (request.POST.get("nota") or "").strip()[:300]
    precedente = esistente.utente if esistente else None
    incaricato = request.user
    if azione == "assegna":
        if not (puo_gestire_pannello(request) or (precedente and precedente.pk == request.user.pk)):
            return HttpResponseForbidden("Solo chi ha la scadenza o gestisce lo scadenzario può assegnarla.")
        incaricato = _persona_scelta(request.POST.get("persona"))
        if incaricato is None:
            messages.error(request, "Scegli la persona dall'elenco.")
            return _torna(request)
    PresaInCarico.objects.update_or_create(chiave=chiave, defaults={
        "utente": incaricato, "nota": nota, "descrizione": descrizione_scadenza(v), "data_scadenza": v.data_scadenza,
    })
    log_action(request, "scadenza_assegnata" if azione == "assegna" else "scadenza_presa_in_carico", "scadenzario",
               {"scadenza": descrizione_scadenza(v), "nota": nota, "subentra_a": precedente.pk if precedente else None,
                "a": incaricato.pk})
    chi = nome_utente(request.user)
    if incaricato.pk != request.user.pk:
        avvisa_utente(incaricato, "scadenza_assegnata", f"{chi} ti ha assegnato la scadenza: {descrizione_scadenza(v)}.", v.url)
    if precedente and precedente.pk not in {incaricato.pk, request.user.pk}:
        avvisa_utente(precedente, "scadenza_assegnata", f"Di questa scadenza ora si occupa {nome_utente(incaricato)}: {descrizione_scadenza(v)}.", v.url)
    if azione == "assegna":
        messages.success(request, f"Scadenza assegnata a {nome_utente(incaricato)}.")
    else:
        messages.success(request, "Scadenza presa in carico: compare con il tuo nome a chi la vede.")
    return _torna(request)


@login_required
@require_POST
def vista_salva(request):
    nome = (request.POST.get("nome") or "").strip()[:80]
    if not nome:
        messages.error(request, "Dai un nome alla vista.")
        return _torna(request)
    parametri = pulisci_parametri(request.POST.get("parametri") or "")
    predefinita = request.POST.get("predefinita") == "1"
    if predefinita:
        VistaSalvata.objects.filter(utente=request.user).update(predefinita=False)
    VistaSalvata.objects.update_or_create(utente=request.user, nome=nome,
                                          defaults={"parametri": parametri, "predefinita": predefinita})
    messages.success(request, f"Vista «{nome}» salvata.")
    return _torna(request)


@login_required
@require_POST
def vista_elimina(request, pk: int):
    vista = get_object_or_404(VistaSalvata, pk=pk, utente=request.user)
    vista.delete()
    messages.success(request, f"Vista «{vista.nome}» eliminata.")
    return _torna(request)


@login_required
@require_POST
def vista_predefinita(request, pk: int):
    vista = get_object_or_404(VistaSalvata, pk=pk, utente=request.user)
    diventa = not vista.predefinita
    VistaSalvata.objects.filter(utente=request.user).update(predefinita=False)
    if diventa:
        vista.predefinita = True
        vista.save(update_fields=["predefinita"])
        messages.success(request, f"«{vista.nome}» si apre quando entri nello scadenzario.")
    else:
        messages.success(request, "Nessuna vista predefinita: lo scadenzario si apre senza filtri.")
    return _torna(request)
