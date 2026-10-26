"""Ciclo di controllo del Registro accessi (schedule ``registro_log_ciclo``, ogni 5 minuti).

Gira nel qcluster, non nel raccoglitore: se il raccoglitore si ferma, qui ce ne si accorge.

1. Raccoglitore vivo? Se non dà segnali da oltre 5 minuti si apre l'interruzione
   «Raccoglitore fermo»; si chiude da sola quando riparte.
2. Fonti mute: nessun messaggio oltre la soglia della fonte → «Fonte senza messaggi».
3. Sigilli: i giorni conclusi ricevono il sigillo (il giorno ancora aperto dal raccoglitore no).
4. Una volta al giorno: verifica a rotazione dell'archivio, copia nella seconda destinazione,
   conservazione (file oltre i mesi scelti, mai meno di 6).
5. SOC: gli eventi importanti e le interruzioni diventano eventi del SOC (``registro_log``),
   che li trasforma in alert secondo gli interruttori di Impostazioni › Avvisi e automatismi.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from . import archivio
from .raccoglitore import apri_interruzione, chiudi_interruzioni

logger = logging.getLogger(__name__)

BATTITO_VECCHIO_MINUTI = 5
CHIAVE_GIORNALIERO = "registro_log.ultimo_giro_giornaliero"
EVENT_TYPE = "registro_log"
SOURCE_NAME = "Registro accessi (log dei server)"


def battito() -> dict:
    from .models import StatoRaccoglitore

    s = StatoRaccoglitore.objects.filter(pk=1).first()
    at = s.battito_il if s else None
    vivo = bool(at and timezone.now() - at <= timedelta(minutes=BATTITO_VECCHIO_MINUTI))
    return {"stato": s, "at": at, "vivo": vivo}


def controlla_raccoglitore() -> dict:
    from .models import Interruzione

    b = battito()
    if b["vivo"]:
        stato = b["stato"]
        ripartito = stato.avviato_il if stato and stato.avviato_il else timezone.now()
        Interruzione.objects.filter(fonte_id__isnull=True, motivo="raccoglitore_fermo", al__isnull=True).update(al=ripartito)
    elif b["at"] is not None:
        aperta = apri_interruzione(None, "raccoglitore_fermo", "Il raccoglitore non dà segnali di vita: nessun log "
                                   "viene ricevuto né archiviato finché non riparte.")
        if aperta.dal > b["at"]:
            aperta.dal = b["at"]
            aperta.save(update_fields=["dal"])
    return {"vivo": b["vivo"]}


def controlla_fonti() -> dict:
    from .models import FonteLog

    ora = timezone.now()
    mute = 0
    for f in FonteLog.objects.filter(attiva=True):
        riferimento = f.ultimo_evento_il or f.creata_il
        if f.silenzio_max_ore and riferimento and ora - riferimento > timedelta(hours=f.silenzio_max_ore):
            apri_interruzione(f, "fonte_muta", f"Nessun messaggio da oltre {f.silenzio_max_ore} ore.")
            mute += 1
        else:
            chiudi_interruzioni(f, "fonte_muta", f.ultimo_evento_il or ora)
    return {"mute": mute}


def giornaliero(forza: bool = False) -> dict | None:
    from core.models import SiteConfig

    oggi = timezone.localdate().isoformat()
    if not forza and (SiteConfig.get(CHIAVE_GIORNALIERO, "") == oggi or timezone.localtime().hour < 1):
        return None
    esito = {
        "verifica": archivio.verifica_a_rotazione(),
        "copia": archivio.copia_mancanti(),
        "conservazione": archivio.applica_conservazione(),
    }
    SiteConfig.objects.update_or_create(chiave=CHIAVE_GIORNALIERO, defaults={"valore": oggi})
    return esito


# ── SOC ──────────────────────────────────────────────────────────────────────


def _soc_source():
    from security.models import SecuritySource, SourceType

    source, _ = SecuritySource.objects.get_or_create(
        name=SOURCE_NAME, defaults={"source_type": SourceType.API, "vendor": "novicrom"},
    )
    return source


def _evento_soc(source, motivo: str, titolo: str, severita: str, chiave: str, quando, payload: dict) -> bool:
    from security.models import SecurityEventRecord
    from security.services.dedup import make_hash

    dedup = make_hash(source.pk, EVENT_TYPE, chiave)
    if SecurityEventRecord.objects.filter(source=source, event_type=EVENT_TYPE, dedup_hash=dedup).exists():
        return False
    SecurityEventRecord.objects.create(
        source=source, event_type=EVENT_TYPE, severity=severita, occurred_at=quando, fingerprint=dedup,
        dedup_hash=dedup, payload={"motivo": motivo, "titolo": titolo[:300], **payload},
    )
    return True


ALERT_CATEGORIE = {
    # categoria → (interruttore in soc_settings, severità dell'alert)
    "registro_cancellato": ("registro.alert.registro_cancellato", "high"),
    "audit_modificato": ("registro.alert.audit_modificato", "high"),
    "gruppo_privilegiato": ("registro.alert.gruppo_privilegiato", "high"),
    "account_creato": ("registro.alert.account_creato", "medium"),
    "account_bloccato": ("registro.alert.account_bloccato", "medium"),
    "servizio_installato": ("registro.alert.servizio_installato", "medium"),
    "configurazione": ("registro.alert.configurazione", "medium"),
}


def invia_al_soc() -> dict:
    """Eventi e interruzioni nuove → eventi del SOC. Senza interruttore generale non fa nulla."""
    from security.models import Severity
    from security.services import soc_settings

    from .models import EventoRegistro, Interruzione, SigilloGiorno

    if not soc_settings.value("registro.alert.attivo"):
        return {"attivo": False}
    source = _soc_source()
    creati = 0
    nuovi = list(EventoRegistro.objects.filter(inviato_soc=False).order_by("id")[:2000])
    for ev in nuovi:
        regola = ALERT_CATEGORIE.get(ev.categoria)
        da_mandare = bool(regola and soc_settings.value(regola[0]))
        if not da_mandare and ev.privilegiato and ev.fuori_orario and ev.categoria in ("accesso", "accesso_privilegiato"):
            da_mandare, regola = bool(soc_settings.value("registro.alert.fuori_orario")), (None, "low")
        if da_mandare:
            creati += _evento_soc(source, ev.categoria, f"{ev.descrizione} su {ev.host or ev.fonte_nome}",
                                  getattr(Severity, regola[1].upper(), regola[1]), f"ev|{ev.pk}", ev.quando, {
                                      "evento_id": ev.pk, "host": ev.host, "account": ev.account,
                                      "ip": ev.ip_origine, "categoria": ev.categoria, "fonte": ev.fonte_nome,
                                  })
    if nuovi:
        EventoRegistro.objects.filter(pk__lte=nuovi[-1].pk, inviato_soc=False).update(inviato_soc=True)
    # Accessi falliti a raffica sullo stesso account (ultimi 15 minuti)
    soglia = int(soc_settings.value("registro.alert.falliti_soglia") or 0)
    if soglia and soc_settings.value("registro.alert.falliti"):
        da = timezone.now() - timedelta(minutes=15)
        raffiche = (EventoRegistro.objects.filter(categoria="accesso_fallito", quando__gte=da).exclude(account="")
                    .values("account").annotate(n=Count("id")).filter(n__gte=soglia).order_by("account"))
        ora = timezone.localtime()
        for r in raffiche:
            creati += _evento_soc(source, "falliti", f"{r['n']} accessi non riusciti in 15 minuti per l'account {r['account']}",
                                  Severity.MEDIUM, f"raffica|{r['account'].lower()}|{ora:%Y%m%d%H}", timezone.now(),
                                  {"account": r["account"], "tentativi": r["n"]})
    # Interruzioni e archivio
    if soc_settings.value("registro.alert.interruzioni"):
        for i in Interruzione.objects.filter(inviata_soc=False).order_by("id")[:200]:
            if i.motivo in ("raccoglitore_fermo", "fonte_muta", "errore_lettura", "eventi_persi"):
                creati += _evento_soc(source, "interruzione", f"Registro accessi: {i.get_motivo_display().lower()}"
                                      + (f" ({i.fonte_nome})" if i.fonte_nome else ""), Severity.MEDIUM,
                                      f"int|{i.pk}", i.dal, {"interruzione_id": i.pk, "dettaglio": i.dettaglio})
            Interruzione.objects.filter(pk=i.pk).update(inviata_soc=True)
        for s in SigilloGiorno.objects.filter(verifica_ok=False):
            creati += _evento_soc(source, "archivio", f"Archivio dei log non integro il {s.giorno:%d/%m/%Y}: {s.verifica_esito}",
                                  Severity.HIGH, f"sig|{s.pk}|{s.verificato_il:%Y%m%d}", timezone.now(),
                                  {"giorno": s.giorno.isoformat(), "esito": s.verifica_esito})
    if creati:
        from security.services.rule_engine import evaluate_security_rules

        evaluate_security_rules()
    return {"eventi_soc": creati}


def esegui() -> dict:
    from .models import Impostazioni

    if not Impostazioni.corrente().attivo:
        return {"attivo": False}
    esito: dict = {"attivo": True}
    for nome, passo in (("raccoglitore", controlla_raccoglitore), ("fonti", controlla_fonti)):
        try:
            esito[nome] = passo()
        except Exception as exc:  # noqa: BLE001 - i passi sono indipendenti
            logger.exception("Registro accessi: passo %s non riuscito", nome)
            esito[nome] = {"errore": str(exc)[:300]}
    try:
        b = battito()
        aperto = b["stato"].giorno_corrente if b["vivo"] and b["stato"] else None
        esito["sigilli"] = len(archivio.sigilla_mancanti(giorno_aperto=aperto))
        esito["giornaliero"] = giornaliero()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Registro accessi: sigilli non riusciti")
        esito["sigilli"] = {"errore": str(exc)[:300]}
    try:
        esito["soc"] = invia_al_soc()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Registro accessi: invio al SOC non riuscito")
        esito["soc"] = {"errore": str(exc)[:300]}
    return esito
