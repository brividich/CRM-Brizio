"""Conformità ISO/IEC 27001:2022 del SOC: un controllo dell'Annex A per riga, verificato dai dati che il SOC ha già.

Ogni ``Controllo`` dice cosa si aspetta chi fa l'audit e ha una funzione ``verifica(dal, al)`` che
ritorna sempre lo stesso dizionario: ``stato`` (``ok``, ``attenzione``, ``non_conforme``,
``non_disponibile``), una ``frase`` in italiano, i ``numeri`` su cui si basa, le ``evidenze``
(link alle pagine del portale dove un auditor vede i dati) e le ``azioni`` da fare.

Regole:

* le verifiche sono automatiche e **prudenti**: dato mancante = ``non_disponibile`` o ``attenzione``, mai ``ok``;
* i servizi che non esistono ancora (``cve_sla``, ``iso_incidenti``) si importano a richiesta con
  :func:`_modulo`: se mancano, il controllo dice «dato non disponibile» e la pagina resta in piedi;
* nessuna verifica scrive: la pagina e il pacchetto mensile leggono soltanto.
"""
from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from importlib import import_module
from typing import Callable

from django.utils import timezone

logger = logging.getLogger(__name__)

OK, ATTENZIONE, NON_CONFORME, NON_DISPONIBILE = "ok", "attenzione", "non_conforme", "non_disponibile"
STATI = [(OK, "Conforme"), (ATTENZIONE, "Da guardare"), (NON_CONFORME, "Non conforme"), (NON_DISPONIBILE, "Dato non disponibile")]
ETICHETTA_STATO = dict(STATI)
_ORDINE = {NON_CONFORME: 0, ATTENZIONE: 1, NON_DISPONIBILE: 2, OK: 3}

PERIODI = [
    ("mese_corrente", "Mese corrente"),
    ("mese_scorso", "Mese scorso"),
    ("trimestre", "Ultimi 3 mesi"),
    ("anno", "Ultimi 12 mesi"),
    ("libero", "Intervallo libero"),
]
_MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre",
         "novembre", "dicembre"]

# Soglie delle verifiche (le stesse scritte nella guida in-app).
SOGLIA_GIRI_OK = 95        # % di giri riusciti sui giri attesi per dire «ok» (8.16)
SOGLIA_GIRI_MIN = 80       # sotto: non conforme (8.16)
SOGLIA_COPERTURA_OK = 100  # % di PC con antimalware per dire «ok» (8.7)
SOGLIA_COPERTURA_MIN = 90  # sotto: non conforme (8.7)
SOGLIA_SLA_OK = 90         # % di CVE corrette nei tempi per dire «ok» (8.8)
SOGLIA_SLA_MIN = 70        # sotto: non conforme (8.8)
SOGLIA_BACKUP_FALLITI = 10  # % di job falliti oltre cui è non conforme (8.13)
SOGLIA_OROLOGIO_OK_S = 60   # scarto di orologio tollerato (8.17)
SOGLIA_OROLOGIO_MAX_S = 300  # oltre: non conforme (8.17)
FRESCHEZZA_CVE_ORE = 24     # un giro riuscito della lettura CVE entro queste ore (5.7)
MESI_PACCHETTI = 3          # pacchetti mensili attesi negli ultimi mesi (9.1)


# --- Periodo ---------------------------------------------------------------------------------

def periodo(preset: str = "mese_corrente", dal: date | None = None, al: date | None = None, oggi: date | None = None):
    """``(dal, al, etichetta, preset)`` con date incluse; intervalli invertiti o oltre un anno vengono corretti."""
    oggi = oggi or timezone.localdate()
    if preset not in dict(PERIODI):
        preset = "mese_corrente"
    if preset == "libero" and dal and al:
        if dal > al:
            dal, al = al, dal
        if (al - dal).days > 366:
            dal = al - timedelta(days=366)
        return dal, al, f"dal {dal:%d/%m/%Y} al {al:%d/%m/%Y}", preset
    if preset == "mese_scorso":
        fine = oggi.replace(day=1) - timedelta(days=1)
        return fine.replace(day=1), fine, f"{_MESI[fine.month - 1]} {fine.year}", preset
    if preset == "trimestre":
        return oggi - timedelta(days=90), oggi, "ultimi 3 mesi", preset
    if preset == "anno":
        return oggi - timedelta(days=365), oggi, "ultimi 12 mesi", preset
    return oggi.replace(day=1), oggi, f"{_MESI[oggi.month - 1]} {oggi.year} (fino a oggi)", "mese_corrente"


def mese_precedente(oggi: date | None = None) -> tuple[date, date]:
    """Primo e ultimo giorno del mese prima di ``oggi`` (il pacchetto del giorno 1)."""
    oggi = oggi or timezone.localdate()
    fine = oggi.replace(day=1) - timedelta(days=1)
    return fine.replace(day=1), fine


def etichetta_mese(dal: date, al: date) -> str:
    if dal.day == 1 and al == dal.replace(day=calendar.monthrange(dal.year, dal.month)[1]):
        return f"{_MESI[dal.month - 1]} {dal.year}"
    return f"dal {dal:%d/%m/%Y} al {al:%d/%m/%Y}"


def _istanti(dal: date, al: date) -> tuple[datetime, datetime]:
    tz = timezone.get_current_timezone()
    return (timezone.make_aware(datetime.combine(dal, time.min), tz),
            timezone.make_aware(datetime.combine(al, time.max), tz))


# --- Attrezzi --------------------------------------------------------------------------------

def _modulo(nome: str):
    """Il modulo ``security.services.<nome>`` se esiste, altrimenti ``None`` (servizi di altri rami)."""
    try:
        return import_module(f"security.services.{nome}")
    except Exception:  # noqa: BLE001 - modulo assente o rotto: il controllo dice «non disponibile»
        return None


def _url(nome: str, query: str = "") -> str:
    from django.urls import NoReverseMatch, reverse

    try:
        return reverse(nome) + (f"?{query}" if query else "")
    except NoReverseMatch:
        return ""


def _evidenza(etichetta: str, nome_rotta: str, query: str = "") -> dict:
    return {"etichetta": etichetta, "url": _url(nome_rotta, query)}


def _esito(stato: str, frase: str, numeri: dict | None = None, evidenze: list | None = None, azioni: list | None = None) -> dict:
    return {"stato": stato, "frase": frase, "numeri": numeri or {}, "evidenze": [e for e in (evidenze or []) if e.get("url")],
            "azioni": azioni or []}


def _non_disponibile(frase: str, azioni: list | None = None, evidenze: list | None = None) -> dict:
    return _esito(NON_DISPONIBILE, frase, {}, evidenze, azioni)


def _pct(parte, totale):
    return round(100 * parte / totale) if totale else None


def _plurale(n, uno, molti):
    return f"{n} {uno if n == 1 else molti}"


# --- Verifiche -------------------------------------------------------------------------------

def _v_5_7(dal: date, al: date) -> dict:
    """Threat intelligence: i feed CVE (NVD, CISA KEV, EPSS) arrivano e sono freschi."""
    from security.models import SecurityCveRecord, SecurityLetturaLog
    from security.services import letture

    lettura = letture.PER_CODICE["cve"]
    evidenze = [_evidenza("Letture automatiche", "security:letture"), _evidenza("Vulnerabilità", "security:vulnerabilities")]
    if not letture.attiva(lettura):
        return _esito(NON_CONFORME, "L'arricchimento delle CVE (NVD, CISA KEV, EPSS) è spento: il SOC non riceve informazioni sulle minacce.",
                      {}, evidenze, ["Accendere «Arricchisci le CVE da NVD e CISA KEV» in Impostazioni › Avvisi e automatismi."])
    da, a = _istanti(dal, al)
    giri = SecurityLetturaLog.objects.filter(codice="cve", avviata_il__range=(da, a)).exclude(
        stato__in=(SecurityLetturaLog.CODA, SecurityLetturaLog.IN_CORSO))
    totale = giri.count()
    riusciti = giri.filter(stato__in=(SecurityLetturaLog.OK, SecurityLetturaLog.PARZIALE)).count()
    ultimo_ok = SecurityLetturaLog.objects.filter(codice="cve", stato__in=(SecurityLetturaLog.OK, SecurityLetturaLog.PARZIALE)).order_by("-avviata_il").first()
    adesso = timezone.now()
    numeri = {
        "giri_nel_periodo": totale, "giri_riusciti": riusciti,
        "ultimo_giro_riuscito": timezone.localtime(ultimo_ok.avviata_il).strftime("%d/%m/%Y %H:%M") if ultimo_ok else "mai",
        "cve_conosciute": SecurityCveRecord.objects.count(),
        "cve_con_dati_nvd": SecurityCveRecord.objects.filter(nvd_fetched_at__isnull=False).count(),
        "cve_sfruttate_kev": SecurityCveRecord.objects.filter(kev=True).count(),
    }
    azioni = []
    if ultimo_ok is None:
        return _esito(NON_CONFORME, "La lettura delle CVE non è mai riuscita: nessuna informazione sulle minacce.", numeri, evidenze,
                      ["Aprire Letture automatiche e lanciare «Esegui ora» sulla lettura «CVE: NVD, CISA KEV, EPSS»; guardare l'errore."])
    vecchio = adesso - ultimo_ok.avviata_il > timedelta(hours=FRESCHEZZA_CVE_ORE)
    if vecchio:
        azioni.append(f"L'ultimo giro riuscito è più vecchio di {FRESCHEZZA_CVE_ORE} ore: controllare la lettura «CVE» nel Battito del SOC.")
    if totale and riusciti < totale:
        azioni.append(f"{totale - riusciti} giri non riusciti nel periodo: leggere l'errore in Letture automatiche.")
    if vecchio:
        return _esito(ATTENZIONE, f"I feed delle minacce non sono freschi: ultimo giro riuscito il {numeri['ultimo_giro_riuscito']}.", numeri, evidenze, azioni)
    if totale == 0:
        return _esito(ATTENZIONE, "Nessun giro della lettura CVE registrato nel periodo.", numeri, evidenze,
                      azioni + ["Verificare che lo schedule «security_cve_enrichment» sia registrato (setup_q_schedules)."])
    stato = OK if riusciti == totale else ATTENZIONE
    return _esito(stato, f"Feed CVE letti ogni ora: {riusciti} giri riusciti su {totale} nel periodo; "
                         f"{numeri['cve_sfruttate_kev']} CVE sfruttate attivamente (KEV) conosciute.", numeri, evidenze, azioni)


def _incidenti(dal, al):
    m = _modulo("iso_incidenti")
    if m is None:
        return None
    try:
        return m.riepilogo(dal, al)
    except Exception:  # noqa: BLE001 - un servizio rotto non ferma la pagina
        logger.exception("iso_incidenti.riepilogo non riuscito")
        return None


_AZIONE_ISO_INCIDENTI = "Il servizio «iso_incidenti» (triage, riesami, evidenze, ruoli, test di ripristino) non è installato in questa versione."


def _v_5_24(dal, al):
    """Pianificazione: ruoli della gestione incidenti assegnati."""
    r = _incidenti(dal, al)
    ev = [_evidenza("Incidenti", "security:incidents"), _evidenza("Avvisi e automatismi", "security:soc_settings")]
    if r is None:
        return _non_disponibile("Ruoli della gestione incidenti: dato non disponibile.", [_AZIONE_ISO_INCIDENTI], ev)
    ruoli = r.get("ruoli") or {}
    # iso_incidenti: {"completi": bool, "mancanti": [etichette dei ruoli senza un nome]}
    mancanti = [str(x) for x in (ruoli.get("mancanti") or [])]
    numeri = {"ruoli_mancanti": len(mancanti)}
    if mancanti:
        return _esito(NON_CONFORME, f"Ruoli della gestione incidenti da assegnare: {', '.join(mancanti)}.", numeri, ev,
                      ["Scriverli in Impostazioni › Avvisi e automatismi › «Gestione degli incidenti»: compaiono nella "
                       "scheda di ogni incidente e nel PDF."])
    if not ruoli.get("completi"):
        return _esito(ATTENZIONE, "Ruoli della gestione incidenti non verificabili.", numeri, ev,
                      ["Definire chi guida la risposta agli incidenti e chi lo sostituisce."])
    return _esito(OK, "Ruoli e contatti della gestione incidenti tutti assegnati.", numeri, ev)


def _v_5_25(dal, al):
    """Valutazione e decisione: ogni segnalazione presa in carico entro il tempo scelto."""
    r = _incidenti(dal, al)
    ev = [_evidenza("Segnalazioni", "security:segnalazioni"), _evidenza("Alert", "security:alerts_list")]
    if r is None:
        return _non_disponibile("Tempi di presa in carico: dato non disponibile.", [_AZIONE_ISO_INCIDENTI], ev)
    t = r.get("triage") or {}
    in_tempo, ritardo, non_presi = int(t.get("presi_in_tempo") or 0), int(t.get("presi_in_ritardo") or 0), int(t.get("non_presi") or 0)
    numeri = {"obiettivo": t.get("target"), "presi_in_tempo": in_tempo, "presi_in_ritardo": ritardo, "non_presi": non_presi,
              "mediana_ore": t.get("mediana_ore")}
    totale = in_tempo + ritardo + non_presi
    if non_presi:
        return _esito(NON_CONFORME, f"{_plurale(non_presi, 'segnalazione', 'segnalazioni')} del periodo mai prese in carico.", numeri, ev,
                      ["Aprire Segnalazioni e assegnare o chiudere quelle senza responsabile."])
    if ritardo:
        return _esito(ATTENZIONE, f"{ritardo} su {totale} prese in carico oltre il tempo scelto ({t.get('target') or '—'}).", numeri, ev,
                      ["Guardare chi riceve gli alert fuori orario e rivedere i canali di notifica."])
    if not totale:
        return _esito(OK, "Nessuna segnalazione da valutare nel periodo.", numeri, ev)
    return _esito(OK, f"Tutte le {totale} segnalazioni prese in carico in tempo (mediana {t.get('mediana_ore') if t.get('mediana_ore') is not None else '—'} ore).", numeri, ev)


def _v_5_26(dal, al):
    """Risposta: incidenti gestiti, nessuna azione scaduta."""
    r = _incidenti(dal, al)
    ev = [_evidenza("Incidenti", "security:incidents"), _evidenza("Ticket", "security:tickets_list")]
    if r is None:
        return _non_disponibile("Risposta agli incidenti: dato non disponibile.", [_AZIONE_ISO_INCIDENTI], ev)
    i = r.get("incidenti") or {}
    aperti, chiusi, scadute = int(i.get("aperti") or 0), int(i.get("chiusi") or 0), int(i.get("azioni_scadute") or 0)
    numeri = {"incidenti_aperti": aperti, "incidenti_chiusi_nel_periodo": chiusi, "azioni_scadute": scadute}
    if scadute:
        return _esito(NON_CONFORME, f"{_plurale(scadute, 'azione', 'azioni')} di risposta oltre la scadenza.", numeri, ev,
                      ["Aprire gli incidenti con attività scadute e chiuderle o ripianificarle con un motivo."])
    return _esito(OK, f"{aperti} incidenti aperti, {chiusi} chiusi nel periodo, nessuna azione scaduta.", numeri, ev)


def _v_5_27(dal, al):
    """Imparare dagli incidenti: ogni incidente chiuso ha il riesame (lezioni apprese)."""
    r = _incidenti(dal, al)
    ev = [_evidenza("Incidenti", "security:incidents")]
    if r is None:
        return _non_disponibile("Riesame degli incidenti chiusi: dato non disponibile.", [_AZIONE_ISO_INCIDENTI], ev)
    i = r.get("incidenti") or {}
    chiusi, con = int(i.get("chiusi") or 0), int(i.get("chiusi_con_riesame") or 0)
    senza = list(i.get("senza_riesame") or [])
    numeri = {"chiusi_nel_periodo": chiusi, "con_riesame": con, "senza_riesame": len(senza)}
    if senza:
        titoli = "; ".join(str(x.get("titolo") or x.get("id")) for x in senza[:5])
        return _esito(NON_CONFORME, f"{_plurale(len(senza), 'incidente chiuso', 'incidenti chiusi')} senza lezioni apprese: {titoli}.", numeri, ev,
                      ["Compilare «Lezioni apprese» negli incidenti chiusi elencati."])
    if not chiusi:
        return _esito(OK, "Nessun incidente chiuso nel periodo.", numeri, ev)
    return _esito(OK, f"Tutti i {chiusi} incidenti chiusi hanno il riesame.", numeri, ev)


def _v_5_28(dal, al):
    """Raccolta delle evidenze: integre e verificate."""
    r = _incidenti(dal, al)
    ev = [_evidenza("Incidenti", "security:incidents"), _evidenza("Archivio e integrità", "security:registro_log_archivio")]
    if r is None:
        return _non_disponibile("Evidenze degli incidenti: dato non disponibile.", [_AZIONE_ISO_INCIDENTI], ev)
    e = r.get("evidenze") or {}
    tot, ver, alt = int(e.get("totali") or 0), int(e.get("verificate") or 0), int(e.get("alterate") or 0)
    chiusi = int((r.get("incidenti") or {}).get("chiusi") or 0)
    numeri = {"evidenze_raccolte": tot, "verificate": ver, "alterate": alt}
    if alt:
        return _esito(NON_CONFORME, f"{_plurale(alt, 'evidenza', 'evidenze')} con impronta diversa da quella registrata.", numeri, ev,
                      ["Ricostruire la catena di custodia delle evidenze alterate e annotarlo nell'incidente."])
    if tot and ver < tot:
        return _esito(ATTENZIONE, f"{tot - ver} evidenze su {tot} non ancora verificate.", numeri, ev, ["Verificare le impronte delle evidenze."])
    if not tot and chiusi:
        return _esito(ATTENZIONE, f"{chiusi} incidenti chiusi nel periodo senza evidenze allegate.", numeri, ev,
                      ["Allegare agli incidenti i log, le mail e le immagini che li documentano."])
    return _esito(OK, f"{tot} evidenze raccolte, tutte verificate." if tot else "Nessuna evidenza da verificare nel periodo.", numeri, ev)


def _v_6_8(dal, al):
    """Segnalazione degli eventi: il personale ha un canale per segnalare."""
    from security.services import soc_settings

    canale = soc_settings.value("iso.segnalazioni.canale")
    ev = [_evidenza("Avvisi e automatismi", "security:soc_settings")]
    if not canale:
        return _esito(ATTENZIONE, "Canale di segnalazione per il personale: da definire.", {"canale": ""}, ev, [
            "Decidere come i dipendenti segnalano un sospetto (mail dedicata, ticket, telefono) e scriverlo in Impostazioni › "
            "Avvisi e automatismi › «Conformità ISO 27001» › Canale di segnalazione.",
            "Comunicarlo al personale (bacheca, informativa) e conservare la comunicazione come evidenza.",
        ])
    from security.models import SecurityIncident

    da, a = _istanti(dal, al)
    segnalati = SecurityIncident.objects.filter(detected_at__range=(da, a), category__in=("phishing", "physical", "data_leak")).count()
    return _esito(OK, f"Canale di segnalazione definito: {canale}.", {"canale": canale, "incidenti_da_segnalazione_nel_periodo": segnalati}, ev)


def _v_8_7(dal, al):
    """Protezione da malware: ogni PC visto dal SOC ha WatchGuard o Defender."""
    from security.models import WatchGuardDispositivo
    from security.services import pc_copertura

    ev = [_evidenza("Dispositivi senza WatchGuard", "security:pc_copertura", "filtro=senza_edr"),
          _evidenza("Patch e protezione", "security:watchguard_pc")]
    try:
        righe = pc_copertura.righe(proposte=False)
    except Exception:  # noqa: BLE001
        logger.exception("pc_copertura non disponibile")
        return _non_disponibile("Elenco dei dispositivi non disponibile.", ["Aprire Dispositivi › Elenco e leggere l'errore."], ev)
    totale = len(righe)
    if not totale:
        return _non_disponibile("Nessun dispositivo visto dal SOC: copertura antimalware non verificabile.",
                                ["Accendere le letture di WatchGuard, Defender o Intune in Avvisi e automatismi."], ev)
    coperti = sum(1 for r in righe if r["watchguard"] or r["defender"])
    scoperti = [r["nome"] for r in righe if not (r["watchguard"] or r["defender"])]
    wg = WatchGuardDispositivo.objects.filter(presente=True, gestito=True)
    wg_tot = wg.count()
    wg_ko = [d.host_display or d.host for d in wg if not d.protetto]
    pct = _pct(coperti, totale)
    numeri = {"dispositivi": totale, "con_antimalware": coperti, "senza_antimalware": len(scoperti), "copertura_pct": pct,
              "watchguard_gestiti": wg_tot, "watchguard_protezione_non_attiva": len(wg_ko)}
    azioni = []
    if scoperti:
        azioni.append("Installare l'agente su: " + ", ".join(scoperti[:8]) + (" …" if len(scoperti) > 8 else "") + ", oppure segnare il dispositivo come fuori perimetro.")
    if wg_ko:
        azioni.append("Protezione non attiva o motore vecchio su: " + ", ".join(wg_ko[:8]) + (" …" if len(wg_ko) > 8 else "") + " (console WatchGuard).")
    if pct < SOGLIA_COPERTURA_MIN:
        return _esito(NON_CONFORME, f"Solo {pct}% dei dispositivi ha un antimalware ({coperti} su {totale}).", numeri, ev, azioni)
    if pct < SOGLIA_COPERTURA_OK or wg_ko:
        return _esito(ATTENZIONE, f"{coperti} dispositivi su {totale} con antimalware ({pct}%); {len(wg_ko)} con protezione non attiva.", numeri, ev, azioni)
    return _esito(OK, f"Tutti i {totale} dispositivi hanno un antimalware attivo.", numeri, ev)


def _v_8_8(dal, al):
    """Vulnerabilità tecniche: corrette entro i tempi per classe, nessuna esposizione scaduta senza accettazione."""
    from security.services import cve_chiusura

    ev = [_evidenza("Vulnerabilità", "security:vulnerabilities")]
    try:
        m = cve_chiusura.metriche(dal=dal, al=al)
    except Exception:  # noqa: BLE001
        logger.exception("cve_chiusura.metriche non riuscito")
        m = {}
    numeri = {"pc_corretti": m.get("correzioni"), "pc_corretti_gravi": m.get("correzioni_gravi"), "giorni_medi_alla_correzione": m.get("giorni_medi"),
              "alert_cve_aperti": m.get("aperti"), "recidive": m.get("recidive")}
    sla = _modulo("cve_sla")
    if sla is None:
        return _esito(NON_DISPONIBILE, "Tempi di correzione per classe: dato non disponibile.", numeri, ev,
                      ["Il servizio «cve_sla» (tempi di correzione per classe e accettazioni del rischio) non è installato in questa versione."])
    try:
        r = sla.riepilogo(dal, al)
    except Exception:  # noqa: BLE001
        logger.exception("cve_sla.riepilogo non riuscito")
        return _esito(NON_DISPONIBILE, "Tempi di correzione per classe: il calcolo non è riuscito.", numeri, ev)
    pct = r.get("percentuale_in_tempo")
    scadute = list(r.get("aperte_scadute") or [])
    non_accettate = [x for x in scadute if not x.get("accettata")]
    numeri.update({"corrette_in_tempo_pct": pct, "esposizioni_scadute": len(scadute), "scadute_senza_accettazione": len(non_accettate),
                   "classi": [{k: c.get(k) for k in ("etichetta", "giorni", "corrette", "in_tempo", "in_ritardo", "aperte", "aperte_scadute")}
                              for c in (r.get("classi") or [])]})
    azioni = []
    if non_accettate:
        azioni.append("Correggere o accettare formalmente (con motivo e scadenza) le esposizioni oltre il termine: "
                      + ", ".join(f"{x.get('cve')} su {x.get('host')}" for x in non_accettate[:6]) + (" …" if len(non_accettate) > 6 else "") + ".")
    if non_accettate or (pct is not None and pct < SOGLIA_SLA_MIN):
        return _esito(NON_CONFORME, f"{len(non_accettate)} esposizioni oltre il termine senza accettazione del rischio"
                      + (f"; {pct}% corrette in tempo" if pct is not None else "") + ".", numeri, ev, azioni)
    if scadute or (pct is not None and pct < SOGLIA_SLA_OK):
        return _esito(ATTENZIONE, f"{pct if pct is not None else '—'}% delle CVE corrette nei tempi; {len(scadute)} esposizioni scadute con rischio accettato.",
                      numeri, ev, azioni + ["Rivedere le accettazioni del rischio alla loro scadenza."])
    if pct is None:
        return _esito(OK, "Nessuna CVE da correggere nel periodo.", numeri, ev)
    return _esito(OK, f"{pct}% delle CVE corrette nei tempi; nessuna esposizione oltre il termine.", numeri, ev)


def _v_8_13(dal, al):
    """Backup: esiti dei job nel periodo e dispositivi senza backup."""
    from security.models import BackupJobRecord
    from security.services import backup_center, pc_copertura

    ev = [_evidenza("Backup", "security:backup"), _evidenza("Dispositivi senza backup", "security:pc_copertura", "filtro=senza_backup")]
    da, a = _istanti(dal, al)
    qs = BackupJobRecord.objects.filter(created_at__range=(da, a))
    totale = qs.count()
    if not totale:
        return _non_disponibile("Nessun esito di backup nel periodo: copertura non verificabile.",
                                ["Collegare la casella dei report di backup o l'API di Veeam in Avvisi e automatismi."], ev)
    falliti = qs.filter(status=backup_center.FAIL).count()
    avvisi = qs.filter(status=backup_center.WARN).count()
    riusciti = qs.filter(status=backup_center.OK).count()
    try:
        senza = [r["nome"] for r in pc_copertura.righe(proposte=False) if not r["backup"]]
    except Exception:  # noqa: BLE001
        senza = []
    pct_falliti = _pct(falliti, totale) or 0
    numeri = {"job_nel_periodo": totale, "riusciti": riusciti, "con_avvisi": avvisi, "falliti": falliti, "falliti_pct": pct_falliti,
              "dispositivi_senza_backup": len(senza)}
    azioni = []
    if falliti:
        azioni.append("Aprire Backup e leggere i job falliti; i PC senza backup riuscito aprono un avviso se acceso in Avvisi e automatismi.")
    if senza:
        azioni.append("Dispositivi mai visti in un backup: " + ", ".join(senza[:8]) + (" …" if len(senza) > 8 else "") + ": includerli in un job o segnarli fuori perimetro.")
    if pct_falliti > SOGLIA_BACKUP_FALLITI:
        return _esito(NON_CONFORME, f"{falliti} job di backup falliti su {totale} ({pct_falliti}%).", numeri, ev, azioni)
    if falliti or senza:
        return _esito(ATTENZIONE, f"{riusciti} job riusciti su {totale}; {falliti} falliti, {len(senza)} dispositivi senza backup.", numeri, ev, azioni)
    return _esito(OK, f"{riusciti} job riusciti su {totale}, nessun fallito; tutti i dispositivi hanno un backup.", numeri, ev)


def _v_5_30(dal, al):
    """Continuità: i ripristini si provano davvero, con esito registrato."""
    r = _incidenti(dal, al)
    ev = [_evidenza("Backup", "security:backup")]
    if r is None:
        return _non_disponibile("Test di ripristino: dato non disponibile.", [_AZIONE_ISO_INCIDENTI], ev)
    p = r.get("ripristini") or {}
    numeri = {"ultimo_test": str(p.get("ultimo_test") or "mai"), "esito_ultimo": p.get("esito_ultimo") or "—",
              "test_nel_periodo": int(p.get("test_periodo") or 0), "falliti_nel_periodo": int(p.get("falliti_periodo") or 0),
              "in_ritardo": bool(p.get("in_ritardo"))}
    if not p.get("ultimo_test"):
        return _esito(NON_CONFORME, "Nessun test di ripristino registrato.", numeri, ev,
                      ["Fare un ripristino di prova (un file e una macchina) e registrarlo con esito e durata."])
    if str(p.get("esito_ultimo") or "").lower() in ("fallito", "ko", "failed", "errore"):
        return _esito(NON_CONFORME, f"L'ultimo test di ripristino ({numeri['ultimo_test']}) è fallito.", numeri, ev,
                      ["Ripetere il ripristino dopo la correzione e registrare l'esito."])
    if p.get("in_ritardo"):
        return _esito(ATTENZIONE, f"Test di ripristino in ritardo: l'ultimo è del {numeri['ultimo_test']}.", numeri, ev,
                      ["Pianificare il prossimo test di ripristino."])
    return _esito(OK, f"Ultimo test di ripristino il {numeri['ultimo_test']} con esito {numeri['esito_ultimo']}.", numeri, ev)


def _v_8_15(dal, al):
    """Logging: archivio sigillato ogni giorno, integro, interruzioni spiegate."""
    ev = [_evidenza("Archivio e integrità", "security:registro_log_archivio"), _evidenza("Fonti", "security:registro_log_fonti")]
    try:
        from registro_log.models import Impostazioni, Interruzione, SigilloGiorno
    except Exception:  # noqa: BLE001
        return _non_disponibile("Registro accessi non installato.", [], ev)
    if not Impostazioni.corrente().attivo:
        return _esito(NON_CONFORME, "Il Registro accessi è spento: i log dei server non vengono raccolti né sigillati.", {}, ev,
                      ["Accendere la raccolta in Registro accessi › Fonti e installare il raccoglitore come servizio."])
    ieri = min(al, timezone.localdate() - timedelta(days=1))
    attesi = max(0, (ieri - dal).days + 1)
    sigilli = SigilloGiorno.objects.filter(giorno__range=(dal, ieri))
    presenti = sigilli.count()
    rotti = list(sigilli.filter(verifica_ok=False).values_list("giorno", flat=True))
    da, a = _istanti(dal, al)
    inter = Interruzione.objects.filter(dal__range=(da, a))
    n_inter = inter.count()
    non_giust = inter.filter(giustificazione="").count()
    numeri = {"giorni_attesi": attesi, "giorni_sigillati": presenti, "sigilli_non_integri": len(rotti), "interruzioni": n_inter,
              "interruzioni_senza_giustificazione": non_giust}
    azioni = []
    if rotti:
        return _esito(NON_CONFORME, f"{_plurale(len(rotti), 'giorno', 'giorni')} dell'archivio non integri: " + ", ".join(f"{g:%d/%m}" for g in rotti[:6]) + ".",
                      numeri, ev, ["Aprire Archivio e integrità, leggere l'esito della verifica e aprire un incidente."])
    if attesi and presenti < attesi:
        azioni.append(f"{attesi - presenti} giorni del periodo senza sigillo: controllare il raccoglitore nel Battito del SOC.")
    if non_giust:
        azioni.append(f"{non_giust} interruzioni della raccolta senza giustificazione: scriverla in Archivio e integrità.")
    if azioni:
        return _esito(ATTENZIONE, f"{presenti} giorni sigillati su {attesi}; {n_inter} interruzioni, {non_giust} senza giustificazione.", numeri, ev, azioni)
    return _esito(OK, f"Tutti i {attesi} giorni del periodo sigillati e integri; {n_inter} interruzioni, tutte giustificate." if attesi
                  else "Nessun giorno concluso nel periodo da sigillare.", numeri, ev)


def _v_8_16(dal, al):
    """Monitoraggio: letture e lavori del SOC girano quando devono."""
    from security.models import SecurityLetturaLog
    from security.services import battito, letture

    ev = [_evidenza("Battito del SOC", "security:battito"), _evidenza("Letture automatiche", "security:letture")]
    try:
        s = battito.stato()
    except Exception:  # noqa: BLE001
        logger.exception("battito.stato non riuscito")
        return _non_disponibile("Battito del SOC non disponibile.", [], ev)
    schedules = battito._schedules()
    da, a = _istanti(dal, min(al, timezone.localdate()))
    a = min(a, timezone.now())
    attesi_tot, fatti_tot, dettaglio = 0, 0, []
    for lt in letture.LETTURE:
        if not letture.attiva(lt) or letture.manca(lt):
            continue
        nome_schedule, ogni = battito.SCHEDULE_DI_LETTURA.get(lt.codice, ("", None))
        sch = schedules.get(nome_schedule)
        if sch is None:
            continue
        if ogni:
            attesi = max(0, int((a - da).total_seconds() // (ogni * 60)))
        else:
            attesi = len(battito.giri_attesi(sch, da, a, massimo=5000))
        if not attesi:
            continue
        fatti = SecurityLetturaLog.objects.filter(codice=lt.codice, manuale=False, avviata_il__range=(da, a),
                                                  stato__in=(SecurityLetturaLog.OK, SecurityLetturaLog.PARZIALE)).count()
        attesi_tot += attesi
        fatti_tot += min(fatti, attesi)
        dettaglio.append({"lettura": lt.nome, "attesi": attesi, "riusciti": min(fatti, attesi)})
    pct = _pct(fatti_tot, attesi_tot)
    c = s["conteggi"]
    numeri = {"giri_attesi": attesi_tot, "giri_riusciti": fatti_tot, "giri_riusciti_pct": pct, "componenti_regolari": c["ok"],
              "componenti_da_sistemare": c["problemi"], "componenti_da_guardare": c["avvisi"], "coda_lavori": s["coda"]["frase"], "letture": dettaglio}
    azioni = [f"{p['nome']}: {p['frase']}" for p in s["problemi"][:6]]
    if s["coda"]["tono"] == "ko":
        return _esito(NON_CONFORME, "La coda dei lavori è ferma: il SOC non legge niente.", numeri, ev, azioni)
    if attesi_tot == 0:
        return _non_disponibile("Nessun giro atteso nel periodo (schedule non registrati o letture spente).",
                                ["Lanciare setup_q_schedules e accendere le letture in Avvisi e automatismi."], ev)
    if pct < SOGLIA_GIRI_MIN:
        return _esito(NON_CONFORME, f"Solo {pct}% dei giri attesi è riuscito ({fatti_tot} su {attesi_tot}).", numeri, ev, azioni)
    if pct < SOGLIA_GIRI_OK or c["problemi"]:
        return _esito(ATTENZIONE, f"{pct}% dei giri attesi riusciti ({fatti_tot} su {attesi_tot}); {c['problemi']} componenti da sistemare adesso.", numeri, ev, azioni)
    return _esito(OK, f"{pct}% dei giri attesi riusciti ({fatti_tot} su {attesi_tot}); tutti i componenti regolari.", numeri, ev)


def _v_8_17(dal, al):
    """Sincronizzazione degli orologi: lo scarto tra l'ora dei messaggi e quella di ricezione resta piccolo."""
    ev = [_evidenza("Fonti", "security:registro_log_fonti")]
    try:
        from registro_log.models import FonteLog
    except Exception:  # noqa: BLE001
        return _non_disponibile("Registro accessi non installato.", [], ev)
    fonti = list(FonteLog.objects.filter(attiva=True, scarto_orologio_s__isnull=False).values_list("nome", "scarto_orologio_s"))
    if not fonti:
        return _non_disponibile("Nessuna fonte syslog attiva con lo scarto di orologio misurato.",
                                ["Collegare almeno una fonte syslog (ESXi, switch, firewall): lo scarto si misura da solo. "
                                 "Per i server Windows vale la sincronizzazione del dominio (w32time), da documentare a mano."], ev)
    fuori = [(n, s) for n, s in fonti if abs(s) > SOGLIA_OROLOGIO_OK_S]
    gravi = [(n, s) for n, s in fonti if abs(s) > SOGLIA_OROLOGIO_MAX_S]
    massimo = max(abs(s) for _n, s in fonti)
    numeri = {"fonti_misurate": len(fonti), "scarto_massimo_s": massimo, "oltre_tolleranza": len(fuori), "scarti": [{"fonte": n, "secondi": s} for n, s in fonti]}
    azioni = ["Sistemare l'ora (NTP) su: " + ", ".join(f"{n} ({s} s)" for n, s in fuori[:8]) + "."] if fuori else []
    if gravi:
        return _esito(NON_CONFORME, f"{len(gravi)} fonti con l'orologio fuori di oltre {SOGLIA_OROLOGIO_MAX_S} s (massimo {massimo} s).", numeri, ev, azioni)
    if fuori:
        return _esito(ATTENZIONE, f"{len(fuori)} fonti con scarto oltre {SOGLIA_OROLOGIO_OK_S} s (massimo {massimo} s).", numeri, ev, azioni)
    return _esito(OK, f"Orologi allineati: scarto massimo {massimo} s su {len(fonti)} fonti.", numeri, ev)


def _v_9_1(dal, al):
    """Monitoraggio e misurazione: il pacchetto di evidenze mensile esiste e viene conservato."""
    from security.models import SecurityPacchettoIso

    ev = [_evidenza("Conformità ISO 27001", "security:iso27001")]
    oggi = timezone.localdate()
    mancanti = []
    primo = oggi.replace(day=1)
    for _ in range(MESI_PACCHETTI):
        fine = primo - timedelta(days=1)
        inizio = fine.replace(day=1)
        if not SecurityPacchettoIso.objects.filter(periodo_dal=inizio, periodo_al=fine).exists():
            mancanti.append(f"{_MESI[inizio.month - 1]} {inizio.year}")
        primo = inizio
    totale = SecurityPacchettoIso.objects.count()
    ultimo = SecurityPacchettoIso.objects.order_by("-generato_il").first()
    numeri = {"pacchetti_archiviati": totale, "mesi_senza_pacchetto": len(mancanti),
              "ultimo_pacchetto": timezone.localtime(ultimo.generato_il).strftime("%d/%m/%Y %H:%M") if ultimo else "mai"}
    if not totale:
        return _esito(ATTENZIONE, "Nessun pacchetto di evidenze ancora generato.", numeri, ev,
                      ["Premere «Genera ora» o aspettare il giorno 1 del mese (06:30): il pacchetto nasce da solo."])
    if mancanti:
        return _esito(ATTENZIONE, f"Mancano i pacchetti di: {', '.join(mancanti)}.", numeri, ev,
                      ["Generare i pacchetti mancanti con «Genera ora» scegliendo il mese."])
    return _esito(OK, f"Pacchetti mensili degli ultimi {MESI_PACCHETTI} mesi archiviati ({totale} in tutto).", numeri, ev)


# --- Registro --------------------------------------------------------------------------------

@dataclass(frozen=True)
class Controllo:
    codice: str
    titolo: str
    atteso: str  # cosa si aspetta chi fa l'audit, in una frase
    verifica: Callable[[date, date], dict]
    area: str = "SOC"


CONTROLLI = (
    Controllo("5.7", "Threat intelligence", "Il SOC riceve e usa informazioni aggiornate sulle minacce (feed NVD, CISA KEV, EPSS).", _v_5_7, "Minacce e vulnerabilità"),
    Controllo("8.8", "Gestione delle vulnerabilità tecniche", "Le vulnerabilità note sui PC vengono corrette entro tempi definiti o il rischio è accettato formalmente.", _v_8_8, "Minacce e vulnerabilità"),
    Controllo("8.7", "Protezione da malware", "Ogni dispositivo del perimetro ha un antimalware attivo e aggiornato.", _v_8_7, "Minacce e vulnerabilità"),
    Controllo("6.8", "Segnalazione degli eventi di sicurezza", "Il personale sa come e a chi segnalare un sospetto, e il canale è in uso.", _v_6_8, "Incidenti"),
    Controllo("5.24", "Pianificazione della gestione incidenti", "Ruoli e responsabilità della risposta agli incidenti sono assegnati.", _v_5_24, "Incidenti"),
    Controllo("5.25", "Valutazione e decisione sugli eventi", "Ogni segnalazione viene valutata e presa in carico entro un tempo definito.", _v_5_25, "Incidenti"),
    Controllo("5.26", "Risposta agli incidenti", "Gli incidenti seguono la procedura e le azioni di risposta non restano scadute.", _v_5_26, "Incidenti"),
    Controllo("5.27", "Imparare dagli incidenti", "Ogni incidente chiuso ha un riesame con le lezioni apprese.", _v_5_27, "Incidenti"),
    Controllo("5.28", "Raccolta delle evidenze", "Le evidenze degli incidenti sono raccolte, con impronta, e verificate.", _v_5_28, "Incidenti"),
    Controllo("8.13", "Backup delle informazioni", "I backup girano con esito registrato e coprono tutti i dispositivi del perimetro.", _v_8_13, "Continuità"),
    Controllo("5.30", "Prontezza ICT per la continuità", "I ripristini vengono provati periodicamente con esito registrato.", _v_5_30, "Continuità"),
    Controllo("8.15", "Registrazione degli eventi (logging)", "I log dei server sono raccolti, sigillati ogni giorno, integri; le interruzioni sono spiegate.", _v_8_15, "Log e monitoraggio"),
    Controllo("8.16", "Attività di monitoraggio", "Le letture automatiche del SOC girano quando devono e i problemi si vedono subito.", _v_8_16, "Log e monitoraggio"),
    Controllo("8.17", "Sincronizzazione degli orologi", "Gli orologi dei sistemi che producono log sono allineati a una fonte comune.", _v_8_17, "Log e monitoraggio"),
    Controllo("9.1", "Monitoraggio, misurazione, analisi e valutazione", "Le misure del SOC sono raccolte ogni mese in un pacchetto di evidenze conservato.", _v_9_1, "Riesame"),
)
PER_CODICE = {c.codice: c for c in CONTROLLI}


def verifica_controllo(c: Controllo, dal: date, al: date) -> dict:
    """Esito di un controllo; un errore della verifica diventa «dato non disponibile», mai una pagina rotta."""
    try:
        esito = c.verifica(dal, al)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Verifica ISO %s non riuscita", c.codice)
        esito = _non_disponibile(f"Verifica non riuscita: {type(exc).__name__}.", ["Segnalare l'errore a chi gestisce il portale."])
    esito.update({"codice": c.codice, "titolo": c.titolo, "atteso": c.atteso, "area": c.area, "stato_label": ETICHETTA_STATO[esito["stato"]],
                  "numeri_semplici": numeri_semplici(esito["numeri"]), "numeri_tabelle": numeri_tabelle(esito["numeri"])})
    return esito


def _testo(v) -> str:
    if isinstance(v, bool):
        return "sì" if v else "no"
    if v is None or v == "":
        return "—"
    return str(v)


def numeri_semplici(numeri: dict) -> list[tuple[str, str]]:
    """``[(etichetta, valore)]`` dei numeri scalari, pronti per la pagina e il PDF."""
    return [(k.replace("_", " "), _testo(v)) for k, v in numeri.items() if not isinstance(v, (list, dict))]


def numeri_tabelle(numeri: dict) -> list[dict]:
    """Le liste di dizionari dei numeri come tabelle: ``{titolo, colonne, righe}``."""
    out = []
    for k, v in numeri.items():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            colonne = list(v[0].keys())
            out.append({"titolo": k.replace("_", " "), "colonne": [h.replace("_", " ") for h in colonne],
                        "righe": [[_testo(r.get(h)) for h in colonne] for r in v[:40]]})
    return out


def valuta(dal: date, al: date) -> dict:
    """Tutti i controlli nel periodo, con i conteggi per stato (per la pagina e per il pacchetto)."""
    controlli = [verifica_controllo(c, dal, al) for c in CONTROLLI]
    conteggi = {stato: sum(1 for c in controlli if c["stato"] == stato) for stato, _l in STATI}
    conteggi["totale"] = len(controlli)
    aree: list[dict] = []
    for c in controlli:
        a = next((x for x in aree if x["nome"] == c["area"]), None)
        if a is None:
            a = {"nome": c["area"], "controlli": []}
            aree.append(a)
        a["controlli"].append(c)
    da_fare = sorted((c for c in controlli if c["stato"] != OK), key=lambda c: (_ORDINE[c["stato"]], c["codice"]))
    return {"dal": dal, "al": al, "etichetta": etichetta_mese(dal, al), "controlli": controlli, "aree": aree, "conteggi": conteggi,
            "da_fare": da_fare, "generato_il": timezone.now()}
