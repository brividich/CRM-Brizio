"""Letture automatiche del SOC: registro unico, storico dei giri ed «Esegui ora».

Ogni lettura (WatchGuard, Defender, Entra, Intune, NVD, switch…) è descritta una volta in ``LETTURE``:
cosa legge, quando gira, quali interruttori la accendono, cosa le serve. ``esegui`` la lancia e scrive
il giro in ``SecurityLetturaLog`` (quando, chi, quanto è durato, cosa ha letto): lo usano i task
pianificati e il pulsante «Esegui ora» della pagina Impostazioni › Letture automatiche.

* I giri pianificati con la lettura spenta non si registrano (sarebbero rumore ogni 15 minuti).
* Se un giro della stessa lettura è già in corso da meno di ``BLOCCO_MINUTI`` il nuovo non parte:
  copre il doppio clic e la riconsegna della coda (``retry`` di django-q) dei giri lunghi.
* Si tengono gli ultimi ``TENUTI`` giri per lettura.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from importlib import import_module

from django.utils import timezone

from security.models import SecurityLetturaLog

logger = logging.getLogger(__name__)

BLOCCO_MINUTI = 15
TENUTI = 300
TIMEOUT_CODA = 600  # secondi: «Esegui ora» e giri lunghi (WatchGuard), oltre i 120 s del cluster


@dataclass(frozen=True)
class Lettura:
    codice: str
    nome: str
    gruppo: str
    descrizione: str
    quando: str
    funzione: str  # "modulo:funzione" della lettura vera (non il task, che passa da qui)
    interruttori: tuple = field(default_factory=tuple)  # accesa se almeno uno è acceso; vuoto = sempre
    requisito: str = ""  # "graph" | "watchguard" | "caselle"
    dati_url: str = ""  # rotta della pagina con i dati letti
    dati_label: str = ""
    lunga: bool = False
    manuale: str = ""  # funzione per «Esegui ora», se diversa (es. senza l'attesa tra un giro e l'altro)


LETTURE = (
    Lettura("caselle", "Caselle dei report", "Report via mail",
            "Le mail dei report (antivirus, firewall, backup) nelle caselle configurate: ogni mail passa dai parser e dalle regole.",
            "ogni 15 minuti", "security.services.letture:_caselle", requisito="caselle",
            dati_url="security:events", dati_label="Eventi"),
    Lettura("defender_alert", "Alert di Microsoft Defender", "Microsoft 365",
            "Alert (e incidenti, se acceso) di Defender aggiornati dall'ultimo giro: diventano alert del SOC.",
            "ogni 15 minuti", "security.services.defender_alerts:run", ("defender.alert.attivo",), "graph",
            "security:alerts_list", "Alert"),
    Lettura("entra", "Microsoft Entra ID", "Microsoft 365",
            "Account di ex dipendenti ancora attivi, modifiche amministrative sensibili, accessi sospetti.",
            "ogni 15 minuti", "security.services.entra_signals:run",
            ("entra.account_cessati.attivo", "entra.audit.attivo", "entra.accessi.attivo"), "graph",
            "security:alerts_list", "Alert"),
    Lettura("secure_score", "Secure Score", "Microsoft 365",
            "Punteggio di Microsoft Secure Score e le azioni che valgono di più.",
            "ogni 12 ore", "security.services.secure_score:aggiorna", ("defender.secure_score.attivo",), "graph",
            "security:dashboard", "Panoramica", manuale="security.services.letture:_secure_score_ora"),
    Lettura("defender_software", "Software dei PC da Defender", "Microsoft 365",
            "Programmi installati sui PC collegati a Defender: entrano nell'inventario e nel calcolo delle CVE.",
            "ogni mattina alle 06:20", "security.services.defender_software:run", ("defender.software.attivo",), "graph",
            "security:vulnerabilities", "Vulnerabilità"),
    Lettura("defender_vuln", "CVE viste da Defender", "Microsoft 365",
            "Le vulnerabilità che Defender vede su ogni PC, da confrontare con il calcolo del SOC nel pannello CVE.",
            "ogni mattina alle 06:25", "security.services.defender_vuln:run", ("defender.vulnerabilita.attivo",), "graph",
            "security:vulnerabilities", "Vulnerabilità"),
    Lettura("intune", "Dispositivi Intune", "Microsoft 365",
            "PC gestiti da Intune: conformità, cifratura, ultima sincronizzazione, hardware, utente principale.",
            "ogni mattina alle 06:45", "assets.tasks:_intune_sync", requisito="graph",
            dati_url="security:pc_copertura", dati_label="Dispositivi"),
    Lettura("m365_licenze", "Abbonamenti Microsoft 365", "Microsoft 365",
            "Abbonamenti, posti usati e scadenze nel modulo Licenze software.",
            "ogni mattina alle 06:40", "assets.tasks:_m365_licenze_sync", requisito="graph"),
    Lettura("watchguard", "WatchGuard Endpoint Security", "WatchGuard",
            "PC con lo stato della protezione, dispositivi in rete senza agente, software dei PC e patch mancanti.",
            "alle 06:10 e alle 13:10", "security.services.watchguard_api:run",
            ("watchguard.api.dispositivi", "watchguard.api.software", "watchguard.api.patch"), "watchguard",
            "security:watchguard_pc", "Patch e protezione", lunga=True),
    Lettura("cve", "CVE: NVD, CISA KEV, EPSS", "Vulnerabilità",
            "Dati delle CVE (range vulnerabili), CVE sfruttate attivamente e probabilità di attacco; poi il ricalcolo degli impatti.",
            "ogni ora", "security.services.letture:_cve", ("cve.arricchimento.attivo",),
            dati_url="security:vulnerabilities", dati_label="Vulnerabilità"),
    Lettura("tabella_mac", "Tabella MAC degli switch", "Rete",
            "Su quale porta di ogni switch «Rete» sta ogni MAC: dice a quale porta è collegato ogni PC.",
            "ogni notte alle 05:30", "contatori.tabella_mac:run", ("apparati.tabella_mac.attivo",),
            dati_url="contatori:snmp_centrale", dati_label="Monitor SNMP", lunga=True),
)
PER_CODICE = {lettura.codice: lettura for lettura in LETTURE}


# --- Letture che non hanno già una funzione unica ----------------------------------------------

def _caselle():
    from security.models import SecurityMailboxSource
    from security.tasks import ingest_security_mailboxes_task

    ok = ingest_security_mailboxes_task()
    totale = SecurityMailboxSource.objects.filter(enabled=True).exclude(source_type="manual").count()
    if not totale:
        return {"attivo": False}
    out = {"caselle": totale, "lette": ok}
    if ok < totale:
        out["errore"] = f"{totale - ok} casell{'a' if totale - ok == 1 else 'e'} non lett{'a' if totale - ok == 1 else 'e'}: vedi Caselle mail"
    return out


def _secure_score_ora():
    from security.services.secure_score import aggiorna

    return aggiorna(forza=True)


def _cve():
    from security.services.cve_feeds import enrichment_enabled, run_enrichment

    if not enrichment_enabled():
        return {"skipped": "arricchimento CVE spento"}
    return run_enrichment(time_budget_seconds=90)


# --- Stato -------------------------------------------------------------------------------------

def attiva(lettura: Lettura) -> bool:
    if not lettura.interruttori:
        return True
    from security.services import soc_settings

    return any(soc_settings.value(k) for k in lettura.interruttori)


def manca(lettura: Lettura) -> str:
    """Cosa manca perché la lettura possa girare ('' se niente)."""
    try:
        if lettura.requisito == "graph":
            from core import m365_graph

            return "" if m365_graph.configurato() else "Credenziali Microsoft Graph non configurate (Setup Wizard)."
        if lettura.requisito == "watchguard":
            from security.services import watchguard_api

            return "" if watchguard_api.configurato() else "Credenziali API WatchGuard non configurate (riquadro in Avvisi e automatismi)."
        if lettura.requisito == "caselle":
            from security.models import SecurityMailboxSource

            return "" if SecurityMailboxSource.objects.filter(enabled=True).exclude(source_type="manual").exists() \
                else "Nessuna casella attiva (Configurazione › Caselle mail)."
    except Exception:  # noqa: BLE001 - lo stato non deve rompere la pagina
        return ""
    return ""


def esito(riepilogo) -> tuple[str, str]:
    """(stato, messaggio) dal risultato di una lettura."""
    if not isinstance(riepilogo, dict):
        return SecurityLetturaLog.OK, ""
    if riepilogo.get("attivo") is False or riepilogo.get("skipped") or riepilogo.get("saltato") is True:
        return SecurityLetturaLog.SPENTA, str(riepilogo.get("skipped") or "")
    errori = list(_errori(riepilogo))
    if not errori and riepilogo.get("ok") is False:
        errori = [str(riepilogo.get("motivo") or "non riuscita")]
    if not errori:
        return SecurityLetturaLog.OK, ""
    dati = any(isinstance(v, (int, float)) and not isinstance(v, bool) and v for k, v in _numeri(riepilogo))
    return (SecurityLetturaLog.PARZIALE if dati else SecurityLetturaLog.ERRORE), " · ".join(errori)[:1000]


def _errori(d, prefisso=""):
    for k, v in d.items():
        if k == "errore" and v:
            yield f"{prefisso}{v}"
        elif k in ("errors", "errori") and isinstance(v, list):
            yield from (f"{prefisso}{e}" for e in v if e)
        elif isinstance(v, dict):
            yield from _errori(v, f"{ETICHETTE.get(k, k)}: ")


def _numeri(d, prefisso=""):
    for k, v in d.items():
        if isinstance(v, dict):
            yield from _numeri(v, f"{k}.")
        else:
            yield f"{prefisso}{k}", v


# --- Esecuzione --------------------------------------------------------------------------------

def _funzione(lettura, manuale=False):
    modulo, nome = ((manuale and lettura.manuale) or lettura.funzione).split(":")
    return getattr(import_module(modulo), nome)


def in_corso(codice: str):
    dal = timezone.now() - timedelta(minutes=BLOCCO_MINUTI)
    return SecurityLetturaLog.objects.filter(codice=codice, stato__in=(SecurityLetturaLog.CODA, SecurityLetturaLog.IN_CORSO),
                                             avviata_il__gte=dal).first()


def esegui(codice: str, *, log_id: int | None = None, rilancia: bool = False):
    """Lancia la lettura e registra il giro; ritorna il risultato della lettura (come il task di prima).

    ``rilancia``: un'eccezione della lettura, dopo essere registrata, risale (passi del ciclo SOC,
    che la scrivono nel loro esito).
    """
    lettura = PER_CODICE[codice]
    log = SecurityLetturaLog.objects.filter(pk=log_id).first() if log_id else None
    if log is None:
        if in_corso(codice):
            return {"saltato": True, "motivo": "un giro è già in corso"}
        log = SecurityLetturaLog(codice=codice)
    elif log.stato not in (SecurityLetturaLog.CODA,):
        return {"saltato": True, "motivo": "giro già eseguito"}  # riconsegna della coda
    log.stato, log.avviata_il = SecurityLetturaLog.IN_CORSO, timezone.now()
    log.save()
    try:
        risultato = _funzione(lettura, log.manuale)()
    except Exception as exc:  # noqa: BLE001 - il giro fallito si registra, la coda non si blocca
        logger.exception("Lettura %s non riuscita", codice)
        log.stato, log.messaggio, log.riepilogo = SecurityLetturaLog.ERRORE, f"{type(exc).__name__}: {exc}"[:1000], {}
        log.finita_il = timezone.now()
        log.save()
        if rilancia:
            raise
        return {"ok": False, "errore": log.messaggio}
    stato, messaggio = esito(risultato)
    if stato == SecurityLetturaLog.SPENTA and not log.manuale:
        log.delete()
        return risultato
    log.stato, log.messaggio, log.finita_il = stato, messaggio, timezone.now()
    log.riepilogo = risultato if isinstance(risultato, dict) else {"valore": risultato}
    try:
        log.save()
    except (TypeError, ValueError):  # risultato non serializzabile: si tiene il testo
        log.riepilogo = {"valore": str(risultato)[:500]}
        log.save()
    _pulisci(codice)
    return risultato


def esegui_da_coda(codice: str, log_id: int):
    """Task accodato da «Esegui ora»."""
    return esegui(codice, log_id=log_id)


def accoda(codice: str, utente) -> tuple[bool, str]:
    """«Esegui ora»: mette il giro in coda (worker django-q). (accodato, messaggio)."""
    lettura = PER_CODICE[codice]
    if in_corso(codice):
        return False, f"«{lettura.nome}»: un giro è già in corso, aspetta che finisca."
    log = SecurityLetturaLog.objects.create(codice=codice, manuale=True, utente=utente if getattr(utente, "pk", None) else None)
    try:
        from django_q.tasks import async_task

        async_task("security.services.letture.esegui_da_coda", codice, log.pk, q_options={"timeout": TIMEOUT_CODA})
    except Exception as exc:  # noqa: BLE001 - coda non disponibile
        log.stato, log.messaggio, log.finita_il = SecurityLetturaLog.ERRORE, f"Coda dei lavori non disponibile: {type(exc).__name__}", timezone.now()
        log.save()
        return False, f"«{lettura.nome}»: non è stato possibile mettere il giro in coda ({type(exc).__name__})."
    return True, f"«{lettura.nome}» in coda: la pagina si aggiorna da sola quando ha finito."


def _pulisci(codice):
    vecchi = list(SecurityLetturaLog.objects.filter(codice=codice).order_by("-avviata_il").values_list("pk", flat=True)[TENUTI:TENUTI + 500])
    if vecchi:
        SecurityLetturaLog.objects.filter(pk__in=vecchi).delete()


# --- Lettura per la pagina ---------------------------------------------------------------------

ETICHETTE = {
    # comuni
    "letti": "letti", "eventi": "eventi", "righe": "righe lette", "importate": "importate", "nuove": "nuove",
    "pc": "PC", "non_piu_rilevate": "non più rilevate", "creati": "nuovi", "aggiornati": "aggiornati", "usciti": "usciti",
    # WatchGuard
    "dispositivi": "PC e protezione", "software": "Software", "patch": "Patch", "task": "Task di installazione",
    "senza_agente": "senza agente", "spariti": "non più visti", "chiuse": "chiuse", "patch_aggiornate": "esiti aggiornati",
    # Defender / Entra
    "incidenti_letti": "incidenti letti", "eventi_incidenti": "eventi da incidenti", "salvate": "vulnerabilità",
    "account": "Account ex dipendenti", "audit": "Modifiche amministrative", "accessi": "Accessi",
    "percentuale": "punteggio %",
    # Intune / M365
    "asset_completati": "asset completati", "ram_lette": "RAM lette", "abbonamenti": "abbonamenti",
    "non_piu_presenti": "non più presenti", "con_scadenza": "con scadenza",
    # CVE
    "nvd": "CVE lette da NVD", "nvd_errors": "CVE non lette", "kev_updated": "KEV aggiornate", "epss_updated": "EPSS aggiornati",
    "auto_linked": "software collegati da soli", "recompute": "ricalcolo",
    # switch / caselle
    "switch": "switch", "mac": "MAC", "caselle": "caselle", "lette": "lette",
}
_NASCOSTE = {"ok", "attivo", "at", "errore", "errors", "errori", "motivo", "skipped", "saltato", "valore"}


def righe_riepilogo(riepilogo) -> list[dict]:
    """[{titolo, voci: [(etichetta, valore)]}] da mostrare: numeri in italiano, niente chiavi tecniche."""
    if not isinstance(riepilogo, dict):
        return [{"titolo": "", "voci": [("risultato", riepilogo)]}] if riepilogo not in (None, "") else []
    out, voci = [], []
    for k, v in riepilogo.items():
        if k in _NASCOSTE:
            continue
        if isinstance(v, dict):
            sotto = [(ETICHETTE.get(kk, kk.replace("_", " ")), vv) for kk, vv in v.items()
                     if kk not in _NASCOSTE and not isinstance(vv, (dict, list))]
            if sotto or v.get("errore"):
                out.append({"titolo": ETICHETTE.get(k, k.replace("_", " ")), "voci": sotto, "errore": v.get("errore", "")})
        elif isinstance(v, list):
            if v:
                voci.append((ETICHETTE.get(k, k.replace("_", " ")), ", ".join(map(str, v[:5]))))
        elif v not in (None, ""):
            voci.append((ETICHETTE.get(k, k.replace("_", " ")), v))
    if voci:
        out.insert(0, {"titolo": "", "voci": voci})
    return out


def _arricchisci(log):
    log.righe = righe_riepilogo(log.riepilogo)
    log.errore_in_righe = any(r.get("errore") for r in log.righe)
    log.lettura = PER_CODICE.get(log.codice)
    adesso = timezone.now()
    log.bloccato = (log.stato in (SecurityLetturaLog.CODA, SecurityLetturaLog.IN_CORSO)
                    and log.avviata_il < adesso - timedelta(minutes=BLOCCO_MINUTI))
    return log


def stato_pagina() -> dict:
    """Le schede della pagina: una per lettura, con ultimo giro, ultimo giro riuscito e storico breve."""
    from django.urls import NoReverseMatch, reverse

    ultimi = {}
    for log in SecurityLetturaLog.objects.select_related("utente").order_by("-avviata_il")[:1500]:
        ultimi.setdefault(log.codice, []).append(log)
    schede, in_corso_ora = [], False
    for lettura in LETTURE:
        storico = [_arricchisci(x) for x in ultimi.get(lettura.codice, [])[:12]]
        ultimo = storico[0] if storico else None
        riuscito = next((x for x in ultimi.get(lettura.codice, []) if x.stato in (SecurityLetturaLog.OK, SecurityLetturaLog.PARZIALE)), None)
        corre = bool(ultimo and ultimo.stato in (SecurityLetturaLog.CODA, SecurityLetturaLog.IN_CORSO) and not ultimo.bloccato)
        in_corso_ora = in_corso_ora or corre
        try:
            dati_url = reverse(lettura.dati_url) if lettura.dati_url else ""
        except NoReverseMatch:
            dati_url = ""
        accesa, mancante = attiva(lettura), manca(lettura)
        if mancante:
            tono = "muted" if not accesa else "ko"
        elif not accesa:
            tono = "muted"
        elif corre:
            tono = "run"
        elif ultimo and ultimo.stato == SecurityLetturaLog.ERRORE:
            tono = "ko"
        elif ultimo and ultimo.stato == SecurityLetturaLog.PARZIALE:
            tono = "warn"
        elif ultimo:
            tono = "ok"
        else:
            tono = "idle"
        schede.append({"lettura": lettura, "accesa": accesa, "manca": mancante, "ultimo": ultimo,
                       "riuscito": _arricchisci(riuscito) if riuscito and riuscito is not ultimo else None,
                       "storico": storico, "corre": corre, "tono": tono, "dati_url": dati_url})
    gruppi = []
    for scheda in schede:
        if not gruppi or gruppi[-1]["nome"] != scheda["lettura"].gruppo:
            gruppi.append({"nome": scheda["lettura"].gruppo, "schede": []})
        gruppi[-1]["schede"].append(scheda)
    conteggi = {
        "accese": sum(1 for s in schede if s["accesa"] and not s["manca"]),
        "errori": sum(1 for s in schede if s["tono"] == "ko" and s["accesa"]),
        "spente": sum(1 for s in schede if not s["accesa"]),
        "totale": len(schede),
    }
    recenti = [_arricchisci(x) for x in SecurityLetturaLog.objects.select_related("utente").order_by("-avviata_il")[:30]]
    return {"gruppi": gruppi, "in_corso": in_corso_ora, "conteggi": conteggi, "recenti": recenti}
