"""Pannello «Banco consegne DPI» della home, per chi gestisce le consegne (Magazzino).

Stesso perimetro e stessi numeri della pagina Banco consegne (``views._banco_*``):
richieste approvate dei DPI che consegna il magazzino, per persona, piu' le
conferme di ricevuta in attesa o contestate. Fail-soft: un errore non rompe la home.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)

PERSONE_MAX = 6


def riepilogo_banco(request) -> dict | None:
    """Dati del pannello, o None se l'utente non gestisce le consegne DPI."""
    try:
        from . import magazzino
        from .models import ConfermaConsegnaDPI, ModelloDPI
        from .views import _banco_conferme_qs, _banco_persone, _banco_queryset, _is_gestore

        if not _is_gestore(request):
            return None
        qs = _banco_queryset(request).filter(categoria__consegna_magazzino=True)
        persone = _banco_persone(qs, magazzino.giacenze())
        conferme = _banco_conferme_qs(request)
        url_banco = reverse("dpi:banco")
        for p in persone:
            p["url"] = f"{url_banco}#apri-{p['chiave']}"
            p["n_dpi"] = len(p["righe"])
        return {
            "url": url_banco,
            "persone": persone[:PERSONE_MAX],
            "persone_altre": max(0, len(persone) - PERSONE_MAX),
            "n_persone": len(persone),
            "n_da_preparare": sum(p["n_da_preparare"] for p in persone),
            "n_pronte": sum(p["n_pronte"] for p in persone),
            "n_mancanti": sum(p["n_mancanti"] for p in persone),
            "n_conferme_attesa": conferme.filter(stato=ConfermaConsegnaDPI.Stato.IN_ATTESA).count(),
            "n_contestate": conferme.filter(
                stato=ConfermaConsegnaDPI.Stato.CONTESTATA, decisa_il__gte=timezone.now() - timedelta(days=30)
            ).count(),
            "consegna_diretta": ModelloDPI.objects.filter(
                is_active=True, tipo__is_active=True, tipo__categoria__is_active=True,
                tipo__categoria__consegna_diretta=True,
            ).exists(),
        }
    except Exception:
        logger.exception("Home: pannello banco DPI non calcolato")
        return None
