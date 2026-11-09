"""«Scarica CSV» degli elenchi del SOC: una risposta, un audit, gli stessi formati ovunque.

Ogni elenco esporta TUTTE le righe del filtro corrente (non solo la pagina mostrata), con le
celle protette dalle formule (``core.csv_export``), separatore «;» per Excel in italiano,
date «gg/mm/aaaa hh:mm», stati e gravità tradotti come a video (``ui_label``). L'export
resta nell'audit del portale (``soc_<elenco>_export``) con il numero di righe e i filtri.
"""
from __future__ import annotations

import logging

from django.utils import timezone

from security.templatetags.security_i18n import ui_label

logger = logging.getLogger(__name__)


def data_ora(valore):
    """Data e ora locali in formato italiano; vuoto se manca."""
    if not valore:
        return ""
    if hasattr(valore, "hour") and timezone.is_aware(valore):
        valore = timezone.localtime(valore)
    return valore.strftime("%d/%m/%Y %H:%M") if hasattr(valore, "hour") else valore.strftime("%d/%m/%Y")


def data(valore):
    if not valore:
        return ""
    if hasattr(valore, "hour") and timezone.is_aware(valore):
        valore = timezone.localtime(valore)
    return valore.strftime("%d/%m/%Y")


def etichetta(valore):
    """Stato, gravità o tipo tradotto come nelle pagine; vuoto se manca."""
    return "" if valore in (None, "") else ui_label(valore)


def numero(valore, decimali=1):
    """Numero con la virgola decimale (Excel in italiano); vuoto se manca."""
    if valore in (None, ""):
        return ""
    try:
        return f"{float(valore):.{decimali}f}".replace(".", ",")
    except (TypeError, ValueError):
        return str(valore)


def si_no(valore):
    return "sì" if valore else "no"


def risposta(request, nome, intestazioni, righe, *, azione, filtri=None):
    """HttpResponse CSV con ``intestazioni`` e ``righe`` (iterabile di liste) + riga di audit.

    ``nome`` è la base del file (es. ``alert`` → ``alert-20261109.csv``); ``azione`` il codice
    di audit (es. ``soc_alert_export``); ``filtri`` i parametri del filtro, per la traccia.
    """
    from core.audit import log_action
    from core.csv_export import csv_download_response

    resp, writer = csv_download_response(f"{nome}-{timezone.localdate():%Y%m%d}.csv", delimiter=";")
    writer.writerow(intestazioni)
    n = 0
    for riga in righe:
        writer.writerow(["" if v is None else v for v in riga])
        n += 1
    dettagli = {"righe": n}
    dettagli.update({k: (v.isoformat() if hasattr(v, "isoformat") else v)
                     for k, v in (filtri or {}).items() if v not in (None, "", [], ())})
    try:
        log_action(request, azione, "security", dettagli)
    except Exception:  # noqa: BLE001 - l'audit non blocca l'export
        logger.exception("Audit dell'export %s non registrato", azione)
    return resp


def a_blocchi(valori, n=1000):
    """Liste di id a blocchi: SQL Server accetta al massimo 2100 parametri per query."""
    valori = list(valori)
    for i in range(0, len(valori), n):
        yield valori[i:i + n]


def vuole_csv(request) -> bool:
    return request.GET.get("formato") == "csv"


def filtri_get(request, *chiavi):
    """I parametri del filtro presenti nella querystring, per l'audit (liste per i multipli)."""
    out = {}
    for k in chiavi:
        valori = [v[:100] for v in request.GET.getlist(k) if v]
        if valori:
            out[k] = valori if len(valori) > 1 else valori[0]
    return out
