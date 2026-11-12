"""Manutenzione notturna del SOC (lettura «manutenzione»): pulizia dei registri tecnici, postura dei PC, avvisi.

**Pulizia** (impostazioni «pulizia.*»): solo registri tecnici, mai alert, incidenti, ticket, eventi, evidenze o audit.
- testo grezzo di mail e file di report **già letti** (esito letto o saltato) più vecchi di N giorni: si svuota il
  testo (``body``/``content``); la riga resta, con oggetto, data, impronta (serve a non reimportare) ed esito;
- giri di lettura delle caselle più vecchi di N giorni;
- registro delle richieste all'AI più vecchio di N giorni;
- cache dei siti esterni scaduta da più di 7 giorni;
- dettaglio delle righe scartate negli import software API più vecchi di 14 giorni (restano i conteggi).
A blocchi (``BLOCCO``) per non tenere bloccato SQL Server: quello che resta si fa la notte dopo.

**Postura**: una fotografia per notte dell'indice di ogni PC (``PosturaGiorno``), con la stessa regola della
scheda e della mappa (``services.postura``); si tengono 400 giorni. **Avviso**: un PC che passa sotto la soglia
(ieri sopra, oggi sotto) va sui canali scelti, una volta.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)

BLOCCO = 2000
GIORNI_POSTURA = 400
GIORNI_DETTAGLI_IMPORT = 14


def _svuota(qs, campo, limite):
    pks = list(qs.values_list("pk", flat=True)[:limite])
    if not pks:
        return 0
    return qs.model.objects.filter(pk__in=pks).update(**{campo: ""})


def _elimina(qs, limite):
    pks = list(qs.values_list("pk", flat=True)[:limite])
    if not pks:
        return 0
    qs.model.objects.filter(pk__in=pks).delete()
    return len(pks)


def pulizia(now=None):
    from security.models import (
        ParseStatus,
        SecurityAiInteractionLog,
        SecurityExternalFeedCache,
        SecurityMailboxIngestionRun,
        SecurityMailboxMessage,
        SecuritySourceFile,
        SoftwareInventoryImport,
        SoftwareSourceKind,
    )
    from security.services import soc_settings

    if not soc_settings.value("pulizia.attiva"):
        return {"attiva": False}
    now = now or timezone.now()
    letti = (ParseStatus.PARSED, ParseStatus.SKIPPED)
    grezzi = now - timedelta(days=int(soc_settings.value("pulizia.grezzi_giorni") or 120))
    esito = {
        "mail_svuotate": _svuota(SecurityMailboxMessage.objects.filter(received_at__lt=grezzi, parse_status__in=letti).exclude(body=""), "body", BLOCCO),
        "file_svuotati": _svuota(SecuritySourceFile.objects.filter(uploaded_at__lt=grezzi, parse_status__in=letti).exclude(content=""), "content", BLOCCO),
        "giri_caselle": _elimina(SecurityMailboxIngestionRun.objects.filter(
            started_at__lt=now - timedelta(days=int(soc_settings.value("pulizia.giri_caselle_giorni") or 60))), BLOCCO),
        "registro_ai": _elimina(SecurityAiInteractionLog.objects.filter(
            created_at__lt=now - timedelta(days=int(soc_settings.value("pulizia.ai_log_giorni") or 365))), BLOCCO),
        "cache_esterna": _elimina(SecurityExternalFeedCache.objects.filter(expires_at__lt=now - timedelta(days=7)), BLOCCO),
    }
    vecchi = SoftwareInventoryImport.objects.filter(
        source_kind__in=(SoftwareSourceKind.WATCHGUARD, SoftwareSourceKind.DEFENDER),
        created_at__lt=now - timedelta(days=GIORNI_DETTAGLI_IMPORT)).exclude(skipped_details=[])
    pks = list(vecchi.values_list("pk", flat=True)[:BLOCCO])
    esito["dettagli_import"] = SoftwareInventoryImport.objects.filter(pk__in=pks).update(skipped_details=[]) if pks else 0
    return esito


def fotografa_postura(oggi=None):
    """Fotografia dell'indice di ogni PC per oggi; ritorna (salvati, passati sotto soglia)."""
    from security.models import PosturaGiorno
    from security.services import postura

    oggi = oggi or timezone.localdate()
    dati = postura.mappa(refresh=True)
    ieri = dict(PosturaGiorno.objects.filter(giorno=oggi - timedelta(days=1)).values_list("pc", "punteggio"))
    esistenti = set(PosturaGiorno.objects.filter(giorno=oggi).values_list("pc", flat=True))
    nuovi, aggiornati = [], 0
    for p in dati["pcs"]:
        if p["key"] in esistenti:
            aggiornati += PosturaGiorno.objects.filter(giorno=oggi, pc=p["key"]).update(punteggio=p["punteggio"], nome=p["nome"][:255])
        else:
            nuovi.append(PosturaGiorno(giorno=oggi, pc=p["key"][:255], nome=p["nome"][:255], punteggio=p["punteggio"]))
    PosturaGiorno.objects.bulk_create(nuovi, batch_size=500)
    PosturaGiorno.objects.filter(giorno__lt=oggi - timedelta(days=GIORNI_POSTURA)).delete()
    return dati["pcs"], ieri


def avvisa_postura(pcs, ieri):
    from security.models import Severity
    from security.services import soc_settings
    from security.services.dedup import make_hash
    from security.services.notifications import _link
    from security.services.proactive_alerts import _channels, _send

    if not soc_settings.value("postura.avviso.attivo"):
        return 0
    soglia = int(soc_settings.value("postura.avviso.soglia") or 50)
    scesi = [p for p in pcs if p["punteggio"] < soglia and ieri.get(p["key"], 100) >= soglia and p["key"] in ieri]
    channels = _channels("postura.avviso.canali")
    if not scesi or not channels:
        return len(scesi)
    righe = [f"- {p['nome']}: {ieri[p['key']]} → {p['punteggio']} ({p['motivo']}) {_link(p['url'])}" for p in scesi[:20]]
    body = (f"{len(scesi)} PC sono scesi sotto {soglia} di indice di postura da ieri.\n\n" + "\n".join(righe)
            + f"\n\nMappa: {_link('/soc/')}")
    _send(channels, event_kind="postura_sotto_soglia", severity=Severity.MEDIUM,
          dedup_hash=make_hash("postura", timezone.localdate().isoformat(), *sorted(p["key"] for p in scesi)),
          subject=f"SOC: {len(scesi)} PC sotto la soglia di postura", body=body)
    return len(scesi)


def giro():
    esito = {"ok": True}
    try:
        esito["pulizia"] = pulizia()
    except Exception as exc:  # noqa: BLE001 - un passo fallito non ferma gli altri
        logger.exception("Manutenzione SOC: pulizia non riuscita")
        esito["pulizia"] = f"errore: {exc}"[:200]
    try:
        pcs, ieri = fotografa_postura()
        esito["postura_pc"] = len(pcs)
        esito["sotto_soglia"] = avvisa_postura(pcs, ieri)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Manutenzione SOC: postura non riuscita")
        esito["postura"] = f"errore: {exc}"[:200]
    return esito


def andamento(pc, giorni=30):
    """[(giorno, punteggio)] degli ultimi giorni per un PC (nome normalizzato)."""
    from security.models import PosturaGiorno

    da = timezone.localdate() - timedelta(days=giorni)
    return list(PosturaGiorno.objects.filter(pc=pc, giorno__gte=da).order_by("giorno").values_list("giorno", "punteggio"))


def variazioni(attuali, giorni=7):
    """{pc: differenza} tra il valore di adesso (``attuali`` = {pc: punteggio}) e la fotografia di ``giorni`` fa
    (l'ultima entro quel giorno): la stessa differenza della linea dell'andamento nella scheda del PC."""
    from security.models import PosturaGiorno

    giorno = (PosturaGiorno.objects.filter(giorno__lte=timezone.localdate() - timedelta(days=giorni))
              .order_by("-giorno").values_list("giorno", flat=True).first())
    if not giorno:
        return {}
    prima = dict(PosturaGiorno.objects.filter(giorno=giorno).values_list("pc", "punteggio"))
    return {pc: punteggio - prima[pc] for pc, punteggio in attuali.items() if pc in prima}
