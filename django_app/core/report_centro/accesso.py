"""Quali report del catalogo può aprire un utente.

Un report è visibile se l'utente può aprire la **pagina da cui si lancia**
(``ReportVoce.pagina``), con la stessa politica dell'``ACLMiddleware``
(:func:`core.middleware.acl_allows_path`: bypass, gate e strict-mode). Le voci
senza pagina (generate da altre schermate, es. la scheda da QR) non compaiono:
non c'è un punto da cui lanciarle.

La visibilità qui è solo comodità: il permesso vero resta quello della pagina e
della route di export, controllati dal middleware a ogni richiesta.
"""
from __future__ import annotations

import logging

from django.urls import NoReverseMatch, reverse

from core.report_centro import catalogo

logger = logging.getLogger(__name__)


def voci_accessibili(request) -> list[dict]:
    """Moduli con le voci che l'utente può lanciare: ``[{"modulo", "righe": [{"voce", "url"}]}]``."""
    from core.middleware import acl_allows_path

    legacy_user = getattr(request, "legacy_user", None)
    esito_per_path: dict[str, bool] = {}
    gruppi = []
    for modulo in catalogo.moduli():
        righe = []
        for voce in modulo.voci:
            if not voce.pagina:
                continue
            try:
                url = reverse(voce.pagina)
            except NoReverseMatch:
                continue
            if url not in esito_per_path:
                try:
                    esito_per_path[url] = acl_allows_path(
                        url, django_user=request.user, legacy_user=legacy_user, request=request
                    )
                except Exception:
                    logger.warning("I miei report: ACL non valutabile per %s", url, exc_info=True)
                    esito_per_path[url] = False
            if esito_per_path[url]:
                righe.append({"voce": voce, "url": url})
        if righe:
            gruppi.append({"modulo": modulo, "righe": righe})
    return gruppi
