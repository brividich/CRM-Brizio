"""Task periodici del modulo fornitori (django-q, schedule in ``automazioni/schedules.py``).

``run_avvisi_ingressi_non_in_regola``: ogni 10 minuti guarda chi è entrato dal
GuestPortal; se la ditta ha la scheda fornitore con «Lavora nei nostri locali» e i
documenti di sicurezza non in regola (``fornitori.requisiti``), manda una **notifica
in-app** (mai mail) a chi ricopre oggi i ruoli indicati in ``fornitori_requisiti_ruoli``
(SiteConfig, predefinito «RSPP,ASPP»). Una sola notifica per visita.
"""
from __future__ import annotations

import logging

from django.urls import reverse

logger = logging.getLogger(__name__)

CHIAVE_RUOLI = "fornitori_requisiti_ruoli"
RUOLI_PREDEFINITI = "RSPP,ASPP"


def _destinatari() -> list[int]:
    """``utenti.id`` legacy di chi ricopre oggi i ruoli configurati (nome del ruolo, senza maiuscole)."""
    from datetime import date

    from django.db.models import Q

    from anagrafica.models import DipendenteRuoloOperativo
    from core.legacy_models import AnagraficaDipendente
    from core.models import SiteConfig

    nomi = [n.strip().lower() for n in (SiteConfig.get(CHIAVE_RUOLI, RUOLI_PREDEFINITI) or "").split(",") if n.strip()]
    if not nomi:
        return []
    oggi = date.today()
    filtro = Q()
    for n in nomi:
        filtro |= Q(ruolo__nome__iexact=n)
    ids_anagrafica = set(
        DipendenteRuoloOperativo.objects.filter(filtro, ruolo__is_active=True)
        .filter(Q(data_fine__isnull=True) | Q(data_fine__gte=oggi))
        .filter(Q(data_inizio__isnull=True) | Q(data_inizio__lte=oggi))
        .values_list("legacy_anagrafica_id", flat=True)
    )
    if not ids_anagrafica:
        return []
    return sorted({
        int(u) for u in AnagraficaDipendente.objects.filter(id__in=ids_anagrafica).values_list("utente_id", flat=True) if u
    })


def avvisa_ingressi_non_in_regola() -> dict:
    from core.notifiche import invia_notifica

    from . import guestportal as gp
    from .models import AvvisoIngressoNonInRegola
    from .requisiti import ESITO_NON_IN_REGOLA, abbina_fornitori, stati_per_fornitori

    esito = {"presenti": 0, "non_in_regola": 0, "avvisati": 0, "gia_avvisati": 0, "destinatari": 0}
    if not gp.db_configurato():
        esito["saltato"] = "GuestPortal non configurato"
        return esito
    presenti = gp.presenti_ora()
    esito["presenti"] = len(presenti)
    abbina_fornitori(presenti)
    stati = stati_per_fornitori([a.fornitore_id for a in presenti if a.fornitore_id])
    da_avvisare = [a for a in presenti if a.fornitore_id and stati.get(a.fornitore_id)
                   and stati[a.fornitore_id].esito == ESITO_NON_IN_REGOLA]
    esito["non_in_regola"] = len(da_avvisare)
    if not da_avvisare:
        return esito
    gia = set(AvvisoIngressoNonInRegola.objects.filter(
        visita_id__in=[a.visita_id for a in da_avvisare]).values_list("visita_id", flat=True))
    nuovi = [a for a in da_avvisare if a.visita_id not in gia]
    esito["gia_avvisati"] = len(da_avvisare) - len(nuovi)
    if not nuovi:
        return esito
    destinatari = _destinatari()
    esito["destinatari"] = len(destinatari)
    for a in nuovi:
        problemi = stati[a.fornitore_id].riassunto
        testo = (f"Entrata in azienda una ditta con i documenti di sicurezza non in regola: {a.azienda or '—'}"
                 f" ({a.nome}, alle {a.ingresso:%H:%M}). {problemi}." if a.ingresso else
                 f"Entrata in azienda una ditta con i documenti di sicurezza non in regola: {a.azienda or '—'}. {problemi}.")
        url = reverse("fornitori:fornitore_detail", args=[a.fornitore_id])
        for uid in destinatari:
            invia_notifica(legacy_user_id=uid, tipo="generico", messaggio=testo[:480], url_azione=url)
        AvvisoIngressoNonInRegola.objects.get_or_create(
            visita_id=a.visita_id,
            defaults={"fornitore_id": a.fornitore_id, "azienda": (a.azienda or "")[:200],
                      "problemi": problemi[:500], "destinatari": len(destinatari)},
        )
        esito["avvisati"] += 1
    return esito


def run_avvisi_ingressi_non_in_regola():
    try:
        esito = avvisa_ingressi_non_in_regola()
    except Exception:
        logger.exception("Avvisi ingressi ditte non in regola falliti")
        return {"ok": False}
    if esito.get("avvisati"):
        logger.info("Avvisi ingressi ditte non in regola: %s", esito)
    return {"ok": True, **esito}
