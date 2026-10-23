"""Pagine della postazione condivisa: scelta dell'operatore, PIN, cambio operatore (``core.postazioni``)."""
from __future__ import annotations

import logging

from django.contrib.auth import authenticate
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core import postazioni

logger = logging.getLogger(__name__)

_TEMPLATE = "core/pages/postazione.html"


def _postazione_in_attesa(request):
    """La postazione della sessione, solo se nessun operatore è entrato."""
    from core.models import PostazioneCondivisa

    corrente = postazioni.stato(request)
    if not corrente or corrente.get("operatore") or int(corrente.get("account") or 0) != request.user.pk:
        return None
    return PostazioneCondivisa.objects.filter(pk=corrente.get("postazione"), attiva=True).select_related("gruppo").first()


def _iniziali(nome: str) -> str:
    parti = [p for p in str(nome or "").split() if p]
    return "".join(p[0] for p in parti[:2]).upper() or "?"


def _contesto(request, postazione, *, selezionato=None, errore: str = "", **extra) -> dict:
    from core.models import PinPostazione

    elenco = postazioni.operatori(postazione)
    pin = {p.legacy_user_id: p for p in PinPostazione.objects.filter(legacy_user_id__in=[u.id for u in elenco])}
    righe = [{
        "id": u.id,
        "nome": u.nome or u.email,
        "iniziali": _iniziali(u.nome or u.email),
        "ha_pin": u.id in pin,
        "bloccato": bool(u.id in pin and pin[u.id].bloccato_il),
    } for u in elenco]
    scelto = next((r for r in righe if selezionato is not None and r["id"] == int(selezionato.id)), None)
    return {
        "page_title": postazione.nome,
        "postazione": postazione,
        "operatori": righe,
        "scelto": scelto,
        "errore": errore,
        "motivo": request.GET.get("motivo", ""),
        "pin_min": postazioni.PIN_MIN,
        "pin_max": postazioni.PIN_MAX,
        "max_tentativi": postazioni.MAX_TENTATIVI,
        **extra,
    }


@never_cache
@login_required(login_url=reverse_lazy("login"))
@require_GET
def postazione_home(request):
    postazione = _postazione_in_attesa(request)
    if postazione is None:
        return redirect("dashboard_home")
    selezionato = None
    if request.GET.get("operatore"):
        selezionato = postazioni.operatore_della_postazione(postazione, request.GET.get("operatore"))
    return render(request, _TEMPLATE, _contesto(request, postazione, selezionato=selezionato))


def _avvisa_blocco(request, postazione, operatore) -> None:
    from core.legacy_utils import sync_django_user_from_legacy
    from core.security_notify import notify_security_event

    postazioni.registra_audit(request, "postazione_pin_bloccato", {
        "postazione": postazione.nome, "postazione_id": postazione.pk, "operatore_legacy_id": operatore.id,
    })
    try:
        utente = sync_django_user_from_legacy(operatore)
        if utente is not None:
            notify_security_event(
                utente,
                "PIN della postazione bloccato",
                f"Il tuo PIN per la postazione «{postazione.nome}» è stato bloccato dopo "
                f"{postazioni.MAX_TENTATIVI} tentativi sbagliati. Per sbloccarlo impostane uno nuovo "
                "con la tua password dalla postazione, oppure chiedi all'amministratore.",
            )
    except Exception:  # noqa: BLE001 - l'avviso non deve bloccare la risposta
        logger.warning("Postazione: avviso blocco PIN non inviato", exc_info=True)


@never_cache
@login_required(login_url=reverse_lazy("login"))
@require_POST
def postazione_entra(request):
    postazione = _postazione_in_attesa(request)
    if postazione is None:
        return redirect("dashboard_home")
    operatore = postazioni.operatore_della_postazione(postazione, request.POST.get("operatore"))
    if operatore is None:
        return render(request, _TEMPLATE, _contesto(request, postazione, errore="Scegli il tuo nome dall'elenco."),
                      status=400)
    esito = postazioni.verifica_pin(operatore.id, request.POST.get("pin", ""))
    if esito["esito"] == "ok":
        if postazioni.passa_a_operatore(request, postazione, operatore):
            return redirect("dashboard_home")
        return render(request, _TEMPLATE, _contesto(
            request, postazione, selezionato=operatore, errore="Questo account non può entrare dalla postazione."),
            status=403)
    if esito["esito"] == "assente":
        errore = "Non hai ancora un PIN: impostalo con «Imposta o cambia il PIN»."
    elif esito["esito"] == "bloccato":
        errore = "PIN bloccato per troppi tentativi. Impostane uno nuovo con la tua password, o chiedi all'amministratore."
    else:
        restanti = esito["restanti"]
        errore = f"PIN errato. {'Resta 1 tentativo' if restanti == 1 else f'Restano {restanti} tentativi'} prima del blocco."
    postazioni.registra_audit(request, "postazione_pin_errato", {
        "postazione": postazione.nome, "postazione_id": postazione.pk,
        "operatore_legacy_id": operatore.id, "esito": esito["esito"],
    })
    if esito.get("appena_bloccato"):
        _avvisa_blocco(request, postazione, operatore)
    return render(request, _TEMPLATE, _contesto(request, postazione, selezionato=operatore, errore=errore),
                  status=403)


@never_cache
@login_required(login_url=reverse_lazy("login"))
@require_http_methods(["GET", "POST"])
def postazione_imposta_pin(request, legacy_user_id: int):
    """L'operatore imposta (o cambia, o sblocca) il PIN con la propria password, poi entra."""
    postazione = _postazione_in_attesa(request)
    if postazione is None:
        return redirect("dashboard_home")
    operatore = postazioni.operatore_della_postazione(postazione, legacy_user_id)
    if operatore is None:
        return redirect("postazione_home")
    ctx = {"imposta_pin": True, "username": request.POST.get("username") or operatore.email or ""}
    if request.method == "GET":
        return render(request, _TEMPLATE, _contesto(request, postazione, selezionato=operatore, **ctx))

    pin = request.POST.get("pin", "")
    errore = postazioni.errore_pin(pin)
    if not errore and pin != request.POST.get("pin_conferma", ""):
        errore = "I due PIN non coincidono."
    if not errore:
        # Credenziali dell'operatore, con la stessa cascata del login (axes compreso).
        utente = authenticate(request, username=ctx["username"].strip(), password=request.POST.get("password", ""))
        legacy = postazioni.legacy_di(utente) if utente is not None else None
        if legacy is None or int(legacy.id) != int(operatore.id):
            errore = "Nome utente o password non corretti."
    if errore:
        return render(request, _TEMPLATE, _contesto(request, postazione, selezionato=operatore, errore=errore, **ctx),
                      status=400)

    postazioni.imposta_pin(operatore.id, pin)
    postazioni.registra_audit(request, "postazione_pin_impostato", {
        "postazione": postazione.nome, "postazione_id": postazione.pk, "operatore_legacy_id": operatore.id,
    })
    try:
        from core.security_notify import notify_security_event

        notify_security_event(utente, "PIN della postazione impostato",
                              f"Hai impostato un nuovo PIN per la postazione «{postazione.nome}».")
    except Exception:  # noqa: BLE001
        logger.warning("Postazione: avviso PIN impostato non inviato", exc_info=True)
    if postazioni.passa_a_operatore(request, postazione, operatore):
        return redirect("dashboard_home")
    return redirect("postazione_home")


@never_cache
@login_required(login_url=reverse_lazy("login"))
@require_POST
def postazione_cambio(request):
    """«Cambio operatore» (o inattività rilevata dalla pagina): si torna alla scelta."""
    motivo = "inattivita" if request.POST.get("motivo") == "inattivita" else "cambio"
    if not postazioni.stato(request).get("operatore"):
        return redirect("postazione_home")
    if postazioni.torna_alla_postazione(request, motivo=motivo):
        url = reverse("postazione_home")
        return redirect(f"{url}?motivo={motivo}" if motivo == "inattivita" else url)
    return redirect(f"{reverse('login')}?reason=logout")
