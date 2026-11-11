"""Modulo pubblico «Richiedi un appuntamento» (``/richiesta-visita/``): senza login, per gli esterni.

Prefisso in ``MIDDLEWARE_EXEMPT_PREFIXES``, view in ``PUBLIC_VIEWS``. Spento (404) finché
``RECEPTION_RICHIESTE_PUBBLICHE`` e ``RECEPTION_NATIVA`` non valgono 1. Protezioni:

- la richiesta non arriva a nessuno finché l'esterno non conferma l'email (link valido 48 ore,
  conferma con un POST: i controlli antivirus delle mail che aprono i link non la confermano);
- limite per IP e globale, campo trappola, tempo minimo di compilazione firmato;
- al massimo 3 richieste aperte per email; la pagina non mostra mai l'elenco dei dipendenti.
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.http import Http404
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from core.accounts.portal_links import portal_link
from core.net import client_ip
from core.public_headers import risposta_pubblica_con_form

from . import mail, servizi
from .models import CategoriaVisita

logger = logging.getLogger(__name__)

LIMITE_IP, FINESTRA_IP = 5, 3600
LIMITE_GLOBALE, FINESTRA_GLOBALE = 40, 3600
SECONDI_MINIMI = 4
SALE_FIRMA = "reception.richiesta-visita"
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_LOOPBACK = {"127.0.0.1", "::1", ""}


def _attivo() -> bool:
    return bool(getattr(settings, "RECEPTION_RICHIESTE_PUBBLICHE", False)) and bool(getattr(settings, "RECEPTION_NATIVA", False))


def _conta(chiave: str, limite: int, finestra: int) -> bool:
    cache.add(chiave, 0, timeout=finestra)
    try:
        return cache.incr(chiave) > limite
    except ValueError:
        cache.set(chiave, 1, timeout=finestra)
        return False


def _troppe(ip: str) -> bool:
    """Come il form pubblico del Suggestion Corner: senza IP vero (127.0.0.1) vale solo il limite globale."""
    try:
        if ip not in _LOOPBACK and _conta(f"rc_richiesta:{ip}", LIMITE_IP, FINESTRA_IP):
            return True
        return _conta("rc_richiesta:__tutti__", LIMITE_GLOBALE, FINESTRA_GLOBALE)
    except Exception:  # noqa: BLE001 - cache giù: meglio una richiesta in più che il modulo fermo
        return False


def _base_pubblica(request) -> str:
    return (getattr(settings, "RECEPTION_RICHIESTE_URL_PUBBLICO", "") or "").strip().rstrip("/") or request.build_absolute_uri("/").rstrip("/")


def _testo(dati, chiave: str, massimo: int) -> str:
    return " ".join(str(dati.get(chiave) or "").split())[:massimo]


def _contesto(**extra) -> dict:
    oggi = timezone.localdate()
    return {
        "categorie": CategoriaVisita.objects.filter(attiva=True),
        "data_min": oggi + timedelta(days=1), "data_max": oggi + timedelta(days=servizi.GIORNI_MAX_ANTICIPO_RICHIESTA),
        "ore_conferma": servizi.ORE_CONFERMA_RICHIESTA, "giorni_conservazione": servizi.GIORNI_CONSERVAZIONE_RICHIESTE,
        "firma": signing.dumps(int(time.time()), salt=SALE_FIRMA), "dati": {}, "errori": [], **extra,
    }


def _errori(dati, firma_ok: bool) -> tuple[list[str], dict]:
    pulito = {
        "nome": _testo(dati, "nome", 100), "cognome": _testo(dati, "cognome", 100), "azienda": _testo(dati, "azienda", 200),
        "email": _testo(dati, "email", 255).lower(), "telefono": _testo(dati, "telefono", 50),
        "referente_indicato": _testo(dati, "referente", 200), "motivo": _testo(dati, "motivo", 200),
        "messaggio": str(dati.get("messaggio") or "").strip()[:1000], "data": dati.get("data_visita", ""), "ora": dati.get("ora_inizio", ""),
        "informativa": dati.get("informativa") == "1",
    }
    errori = []
    if not firma_ok:
        errori.append("Non siamo riusciti a verificare l'invio: aspetta qualche secondo e premi di nuovo «Invia la richiesta».")
    if not pulito["nome"] or not pulito["cognome"]:
        errori.append("Scrivi nome e cognome.")
    if not _EMAIL.match(pulito["email"]):
        errori.append("Scrivi un'email valida: ti mandiamo lì il link di conferma.")
    if not pulito["referente_indicato"]:
        errori.append("Scrivi chi vuoi incontrare.")
    oggi = timezone.localdate()
    try:
        giorno = datetime.strptime(pulito["data"], "%Y-%m-%d").date()
    except ValueError:
        giorno = None
    if giorno is None or not oggi < giorno <= oggi + timedelta(days=servizi.GIORNI_MAX_ANTICIPO_RICHIESTA):
        errori.append(f"Scegli un giorno da domani ai prossimi {servizi.GIORNI_MAX_ANTICIPO_RICHIESTA} giorni.")
    ora = None
    if pulito["ora"]:
        try:
            ora = datetime.strptime(pulito["ora"], "%H:%M").time()
        except ValueError:
            errori.append("L'ora non è valida.")
    if dati.get("informativa") != "1":
        errori.append("Conferma di aver letto l'informativa privacy.")
    pulito["giorno"], pulito["ora_inizio"] = giorno, ora
    return errori, pulito


def _firma_valida(firma: str) -> bool:
    try:
        creata = signing.loads(firma or "", salt=SALE_FIRMA, max_age=6 * 3600)
    except signing.BadSignature:
        return False
    return time.time() - int(creata) >= SECONDI_MINIMI


@require_http_methods(["GET", "POST"])
@risposta_pubblica_con_form
def richiesta(request):
    if not _attivo():
        raise Http404
    if request.method == "GET":
        return render(request, "reception/pubblica/richiesta.html", _contesto())
    ip = client_ip(request) or ""
    if _troppe(ip):
        return render(request, "reception/pubblica/esito.html", {"titolo": "Troppe richieste",
                      "testo": "Abbiamo ricevuto troppe richieste in poco tempo. Riprova tra un'ora."}, status=429)
    if request.POST.get("sito_web"):
        # Campo trappola compilato: un programma automatico. Finto successo, nessun indizio.
        return render(request, "reception/pubblica/esito.html", {"titolo": "Controlla la tua email", "testo": "", "inviata": True})
    errori, pulito = _errori(request.POST, _firma_valida(request.POST.get("firma")))
    if not errori:
        try:
            nuova = servizi.nuova_richiesta(
                nome=pulito["nome"], cognome=pulito["cognome"], email=pulito["email"], data_visita=pulito["giorno"],
                referente_indicato=pulito["referente_indicato"], azienda=pulito["azienda"], telefono=pulito["telefono"],
                ora_inizio=pulito["ora_inizio"], motivo=pulito["motivo"], messaggio=pulito["messaggio"], ip=ip,
            )
        except servizi.OperazioneNonValida as exc:
            errori.append(str(exc))
        else:
            link = _base_pubblica(request) + reverse("reception_pubblica:conferma", args=[nuova.token])
            try:
                mail.invia_conferma_richiesta(nuova, link)
            except Exception:  # noqa: BLE001 - senza mail la richiesta non si può confermare: si cancella
                logger.exception("Richiesta di visita %s: mail di conferma non inviata", nuova.pk)
                nuova.delete()
                return render(request, "reception/pubblica/esito.html", {"titolo": "Non è stato possibile inviare la richiesta",
                              "testo": "Il servizio di posta non risponde. Riprova più tardi."}, status=503)
            return render(request, "reception/pubblica/esito.html", {"titolo": "Controlla la tua email", "testo": "", "inviata": True,
                          "ore_conferma": servizi.ORE_CONFERMA_RICHIESTA})
    return render(request, "reception/pubblica/richiesta.html", _contesto(dati=pulito, errori=errori), status=400)


@require_http_methods(["GET", "POST"])
@risposta_pubblica_con_form
def conferma(request, token):
    if not _attivo():
        raise Http404
    if request.method == "GET":
        trovata = servizi.richiesta_da_confermare(token)
        return render(request, "reception/pubblica/conferma.html", {"richiesta": trovata}, status=200 if trovata else 404)
    confermata = servizi.conferma_richiesta(token)
    if confermata is None:
        return render(request, "reception/pubblica/conferma.html", {"richiesta": None}, status=404)
    try:
        mail.avvisa_nuova_richiesta(
            confermata,
            portal_link(reverse("reception:annuncia")) or reverse("reception:annuncia"),
            portal_link(reverse("reception:richieste")) or reverse("reception:richieste"),
        )
    except Exception:  # noqa: BLE001 - la richiesta resta nel pannello anche se l'avviso non parte
        logger.exception("Richiesta di visita %s: avviso al referente non inviato", confermata.pk)
    return render(request, "reception/pubblica/esito.html", {
        "titolo": "Richiesta inoltrata",
        "testo": "Grazie. Riceverai una mail con la risposta: se la visita viene accettata, nella mail trovi il codice e il QR per entrare.",
    })
