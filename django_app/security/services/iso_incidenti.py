"""Gestione degli incidenti secondo ISO/IEC 27001:2022 (controlli 5.24-5.28 e 8.13): riepilogo unico.

Un solo punto da cui il cruscotto di conformità e il pacchetto mensile di evidenze leggono i
numeri. Ogni voce è calcolata dai servizi dedicati:

- ``triage``      → :mod:`security.services.triage_tempi` (5.25/5.26: presa in carico per gravità);
- ``incidenti``   → :mod:`security.services.riesame` (5.27: lezioni apprese e azioni correttive);
- ``evidenze``    → :mod:`security.services.evidenze` (5.28: impronta SHA-256 e custodia);
- ``ruoli``       → impostazioni «Ruoli e contatti per gli incidenti» (5.24);
- ``ripristini``  → :mod:`security.services.ripristini` (8.13: prove di ripristino).
"""
from __future__ import annotations

from security.services import soc_settings

RUOLI = [
    ("iso.ruoli.incident_manager", "Responsabile degli incidenti"),
    ("iso.ruoli.vice", "Sostituto"),
    ("iso.ruoli.csirt", "Contatto CSIRT Italia / ACN"),
    ("iso.ruoli.fornitore", "Fornitore IT di supporto"),
]


def ruoli() -> dict:
    """Ruoli e contatti impostati: ``{"voci": [(label, valore)], "completi": bool, "mancanti": [label]}``."""
    voci = [(label, soc_settings.value(key)) for key, label in RUOLI]
    mancanti = [label for label, valore in voci if not valore]
    return {"voci": voci, "completi": not mancanti, "mancanti": mancanti}


def riepilogo(dal, al) -> dict:
    """Numeri del periodo ``dal``-``al`` (date) per il cruscotto di conformità.

    Chiavi: ``triage``, ``incidenti``, ``evidenze``, ``ruoli``, ``ripristini`` (vedi il modulo).
    """
    from security.models import SecurityIncident
    from security.services import evidenze, riesame, ripristini, triage_tempi

    chiusi = SecurityIncident.objects.filter(status__in=riesame.STATI_CONCLUSI, resolved_at__date__gte=dal, resolved_at__date__lte=al)
    senza = [inc for inc in riesame.incidenti_senza_riesame() if inc.resolved_at and dal <= inc.resolved_at.date() <= al]
    r = ruoli()
    return {
        "triage": triage_tempi.riepilogo(dal, al),
        "incidenti": {
            "aperti": SecurityIncident.objects.filter(status__in=[SecurityIncident.STATUS_OPEN, SecurityIncident.STATUS_CONTAINED]).count(),
            "chiusi": chiusi.count(),
            "chiusi_con_riesame": chiusi.filter(riesame__isnull=False).count(),
            "senza_riesame": [{"id": inc.pk, "titolo": inc.title, "chiuso_il": inc.resolved_at} for inc in senza],
            "azioni_scadute": len(riesame.azioni_scadute()),
        },
        "evidenze": evidenze.riepilogo(),
        "ruoli": {"completi": r["completi"], "mancanti": r["mancanti"]},
        "ripristini": ripristini.riepilogo(dal, al),
    }


def ciclo() -> dict:
    """Passo del ciclo periodico: sigilla le evidenze ancora senza impronta."""
    from security.services import evidenze

    return {"evidenze_sigillate": evidenze.sigilla_mancanti()}
