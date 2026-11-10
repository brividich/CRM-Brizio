"""«Apri ticket» dai problemi di una stampante MFC (pannello laterale e scheda MFC).

Porta al form «Nuovo ticket» dell'app tickets già compilato: macchina, asset collegato,
ultimo avviso critico aperto, consumabili sotto soglia e stato SNMP. Il ticket lo crea
l'utente inviando il form (controlla e corregge prima): qui nessuna apertura automatica.
"""
from __future__ import annotations

from urllib.parse import urlencode

from django.urls import reverse
from django.utils import timezone

from . import services
from .models import AvvisoStampante, StatoSNMP

_CATEGORIA = "STAMPANTE"


def _quando(valore):
    return timezone.localtime(valore).strftime("%d/%m/%Y %H:%M") if valore else ""


def dati_ticket(macchina, consumabili=None, request=None):
    """(titolo, descrizione, priorità) del ticket con i problemi attuali della MFC."""
    avviso = (AvvisoStampante.objects.filter(macchina=macchina, chiuso_il__isnull=True, informativo=False,
                                             critico=True).order_by("-aperto_il").first())
    if consumabili is None:
        consumabili = services.stato_consumabili([macchina]).get(macchina.pk)
    critici = (consumabili or {}).get("critici") or []
    non_risponde = bool(macchina.host) and macchina.snmp_stato == StatoSNMP.ERROR

    if avviso is not None:
        problema = avviso.testo
    elif non_risponde:
        problema = "non risponde in rete"
    elif critici:
        problema = "consumabili da sostituire (" + ", ".join(v["nome"] for v in critici[:3]) + ")"
    else:
        problema = "segnalazione"
    titolo = f"Stampante {macchina.reparto}: {problema}"[:300]

    righe = [f"Stampante MFC: {macchina.reparto}", f"Matricola: {macchina.matricola}"]
    if macchina.modello:
        righe.append(f"Modello: {macchina.modello}")
    if macchina.host:
        righe.append(f"Indirizzo IP: {macchina.host}")
    if macchina.asset_id:
        righe.append(f"Asset HUB: {macchina.asset.asset_tag}")
    stato = f"Stato SNMP: {macchina.get_snmp_stato_display()}"
    if macchina.snmp_ultimo_controllo:
        stato += f" (ultimo controllo {_quando(macchina.snmp_ultimo_controllo)})"
    righe.append(stato)
    if macchina.snmp_ultimo_errore and macchina.snmp_stato == StatoSNMP.ERROR:
        righe.append(f"Ultimo errore SNMP: {macchina.snmp_ultimo_errore[:300]}")
    if avviso is not None:
        righe.append(f"Avviso critico aperto: {avviso.testo} (dal {_quando(avviso.aperto_il)})")
    if critici:
        righe.append("Consumabili sotto il {}%: {}".format(
            services.SOGLIA_CONSUMABILE_PCT, ", ".join(f"{v['nome']} {v['pct']}%" for v in critici)))
    scheda = reverse("contatori:macchina", args=[macchina.pk])
    righe.append(f"Scheda nel portale: {request.build_absolute_uri(scheda) if request else scheda}")
    priorita = "ALTA" if avviso is not None or non_risponde else "MEDIA"
    return titolo, "\n".join(righe), priorita


def url_apri_ticket(request, macchina, consumabili=None):
    """URL del form «Nuovo ticket» IT precompilato; "" se l'utente non può aprire ticket IT."""
    try:
        from tickets.services.accesso import puo_aprire_ticket

        if not puo_aprire_ticket(request, "IT"):
            return ""
    except Exception:  # noqa: BLE001 - senza app tickets il pulsante semplicemente non compare
        return ""
    titolo, descrizione, priorita = dati_ticket(macchina, consumabili, request)
    parametri = {"tipo": "IT", "categoria": _CATEGORIA, "priorita": priorita,
                 "titolo": titolo, "descrizione": descrizione}
    if macchina.asset_id:
        parametri["asset"] = macchina.asset_id
    return f"{reverse('tickets:nuovo')}?{urlencode(parametri)}"
