"""Riscaldamento del processo web all'avvio, prima che Waitress accetti richieste.

Con più processi IIS (``processesPerApplication``) ognuno, alla prima richiesta,
costruiva da sé l'indice delle rotte di Django (migliaia di espressioni regolari),
rileggeva il sorgente delle view di anagrafica per i cancelli del sottomenu
(``subnav_gates.page_gates``) e compilava i template di base: secondi di attesa per i
primi utenti dopo ogni riavvio o deploy, ripetuti per ogni processo.

Si chiama da ``config/wsgi.py``. Non deve mai impedire l'avvio: ogni passo è difensivo.
``HUB_WARMUP=0`` lo spegne.
"""
from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger(__name__)

TEMPLATE_DI_BASE = (
    "core/base.html",
    "assets/base_shell.html",
    "tasks/base_shell.html",
    "security/_base_soc.html",
)


def _riscalda_cancelli_sottomenu() -> int:
    """``page_gates`` delle sole pagine linkate nel sottomenu di anagrafica.

    Sono quelle che il menu controlla a ogni pagina (``section_gate_allows``): farle
    tutte (oltre 500 view) costerebbe secondi di avvio per niente.
    """
    from django.urls import Resolver404, resolve, reverse

    from anagrafica.models import SubnavCategoriaAnagrafica, SubnavLinkAnagrafica
    from anagrafica.subnav_gates import page_gates

    percorsi: set[str] = set()
    voci = [(l.url_type, l.url_value) for l in SubnavLinkAnagrafica.objects.only("url_type", "url_value")]
    voci += [
        (getattr(c, "landing_url_type", "named"), getattr(c, "landing_url_value", ""))
        for c in SubnavCategoriaAnagrafica.objects.all()
    ]
    for tipo, valore in voci:
        valore = str(valore or "").strip()
        if not valore:
            continue
        try:
            percorsi.add(reverse(valore) if tipo == "named" else valore.split("?", 1)[0].split("#", 1)[0])
        except Exception:
            continue
    pronte = 0
    for percorso in percorsi:
        if not percorso.startswith("/") or percorso.startswith("//"):
            continue
        try:
            page_gates(resolve(percorso).func)
            pronte += 1
        except (Resolver404, Exception):
            continue
    return pronte


def riscalda() -> dict:
    if os.environ.get("HUB_WARMUP", "1").strip().lower() in {"0", "false", "no", "off"}:
        return {"skipped": True}
    esito: dict = {}
    inizio = time.perf_counter()

    try:
        from django.urls import get_resolver

        resolver = get_resolver()
        resolver.reverse_dict  # noqa: B018 - costruisce l'indice delle rotte una volta
        esito["rotte"] = True
    except Exception:
        logger.warning("Avvio: indice delle rotte non preparato", exc_info=True)
        return esito

    try:
        esito["cancelli_anagrafica"] = _riscalda_cancelli_sottomenu()
    except Exception:
        logger.warning("Avvio: cancelli del sottomenu anagrafica non preparati", exc_info=True)
    finally:
        try:
            from django.db import connections

            connections.close_all()  # la connessione dell'avvio non resta al thread principale
        except Exception:
            pass

    try:
        from django.template.loader import get_template

        pronti = 0
        for nome in TEMPLATE_DI_BASE:
            try:
                get_template(nome)
                pronti += 1
            except Exception:
                pass
        esito["template"] = pronti
    except Exception:
        logger.warning("Avvio: template di base non compilati", exc_info=True)

    esito["ms"] = int((time.perf_counter() - inizio) * 1000)
    logger.info("Avvio: processo riscaldato in %s ms (%s)", esito["ms"], esito)
    return esito
