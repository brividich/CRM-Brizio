"""Avvisi delle quote CMM: report nuovi con quote fuori tolleranza e quote che vanno in deriva.

Li riceve chi è scelto in Ordini di produzione › Impostazioni («Chi riceve gli avvisi»), come notifica
in-app (campanella e, se l'utente l'ha chiesta, push). Ogni report avvisa una volta sola (``avvisato``);
una quota in deriva si riavvisa al massimo ogni 30 giorni. Si avvisa solo per i report degli ultimi
``GIORNI_AVVISO`` giorni: la prima lettura di una cartella (anni di report) non manda avvisi su pezzi vecchi.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone
from django.urls import reverse
from urllib.parse import urlencode

from .models import ImpostazioniQuoteCMM, ReportCMM

logger = logging.getLogger(__name__)
_DERIVA_RIPETI = 30 * 24 * 3600
GIORNI_AVVISO = 30


def _destinatari(imp: ImpostazioniQuoteCMM) -> list[int]:
    from core.permessi import legacy_id_da_user_id

    ids = []
    for uid in imp.destinatari.values_list("id", flat=True):
        lid = legacy_id_da_user_id(uid)
        if lid:
            ids.append(int(lid))
    return ids


def invia_avvisi(pn: str) -> dict:
    """Avvisa dei report nuovi del P/N con quote fuori e delle quote entrate in deriva. Non solleva mai."""
    from core.notifiche import invia_notifica

    from . import report_cmm_indice as cmm

    esito = {"fuori": 0, "deriva": 0}
    try:
        imp = ImpostazioniQuoteCMM.attuali()
        dest = _destinatari(imp)
        nuovi = list(ReportCMM.objects.filter(pn=pn, avvisato=False))
        da = timezone.localdate() - timedelta(days=GIORNI_AVVISO)
        recenti = [r for r in nuovi if r.data and r.data >= da]
        if dest and imp.avvisa_fuori:
            for r in recenti:
                if r.escluso or not r.righe or not r.fuori:
                    continue
                nomi = list(r.misure.filter(fuori=True).values_list("nome", flat=True)[:3])
                altro = f" e altre {r.fuori - len(nomi)}" if r.fuori > len(nomi) else ""
                msg = f"{pn} · {r.seriale or r.file}: {r.fuori} quote fuori tolleranza ({', '.join(nomi)}{altro}) · {r.op}"
                url = reverse("produzione:report_cmm", args=[r.pk])
                for lid in dest:
                    invia_notifica(lid, "generico", msg[:500], url)
                esito["fuori"] += 1
        ReportCMM.objects.filter(pk__in=[r.pk for r in nuovi]).update(avvisato=True)
        if dest and imp.avvisa_deriva and recenti:
            for a in cmm.analisi_pn(pn):
                d = a["deriva"]
                if not d:
                    continue
                chiave = f"prod_cmm_deriva_avvisata:{pn}:{a['prog']}:{a['quota']['id']}"
                if not cache.add(chiave, 1, _DERIVA_RIPETI):
                    continue
                verso = "superiore" if d["verso"] == "sup" else "inferiore"
                quando = "è già al limite" if not d["pezzi"] else f"al limite {verso} tra circa {d['pezzi']} pezzi"
                msg = f"{pn} · {a['quota']['nome']} in deriva: {quando} ({a['prog']})"
                url = f"{reverse('produzione:pn_quote')}?{urlencode({'pn': pn, 'prog': a['prog'], 'q': a['quota']['id']})}"
                for lid in dest:
                    invia_notifica(lid, "generico", msg[:500], url)
                esito["deriva"] += 1
    except Exception:
        logger.exception("avvisi quote CMM non inviati per %s", pn)
    return esito
