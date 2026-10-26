"""Chiusura del ciclo di una CVE: dall'alert «PC con versione vulnerabile» alla chiusura con prove.

L'alert nasce dal ricalcolo degli impatti (``cve_impact``) per le CVE critiche o sfruttate (CISA KEV).
Qui si chiude il giro:

- **progresso per PC**: a ogni ricalcolo l'alert aperto dice quanti PC sono ancora esposti
  («3 PC su 5 ancora con versione vulnerabile») e la timeline registra ogni PC che esce, con le
  prove di quel momento («PC-01: aggiornato da 1.2 a 1.4 il 27/10, prove: inventario + patch
  WatchGuard installata»);
- **chiusura con prove** (regola ``cve_impatto_risolto`` del registro di ``auto_resolution``):
  l'alert si chiude da solo quando nessun PC è più impattato né da verificare e ogni PC che era
  esposto ha almeno ``PROVE_RICHIESTE_CRITICA`` prove concordi tra inventario recente, patch
  WatchGuard e Defender. Un PC con una prova sola è «aggiornamento rilevato, in attesa di
  conferma»; un PC non più visto è «non verificabile» finché una persona non lo esclude dalla
  verifica (azione tracciata nella timeline);
- **recidiva**: se la versione vulnerabile ricompare entro ``GIORNI_RECIDIVA`` giorni dalla chiusura
  automatica, si riapre lo stesso alert, con la sua storia, invece di aprirne uno nuovo;
- **metriche** per la pagina Vulnerabilità: giorni da «esposto dal» alla correzione, chiusure
  automatiche e a mano, recidive.

Nel dubbio l'alert resta aperto: un PC non visto di recente non conta mai come corretto.
"""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import timedelta
from statistics import mean

from django.db.models import Max
from django.utils import timezone

from security.models import (
    DefenderVulnerabilita,
    SecurityAlert,
    SecurityAlertActionLog,
    SecurityCveImpact,
    SecurityCveRecord,
    SecurityCveRisoluzione,
    SecuritySource,
    SoftwareInstallation,
    Status,
    WatchGuardPatch,
)
from security.services import soc_settings
from security.services.alert_lifecycle import ACTIVE_ALERT_STATUSES

logger = logging.getLogger(__name__)

RULE_CODE = "cve_impatto_risolto"
GIORNI_RECIDIVA = 90
PROVE_RICHIESTE_CRITICA = 2
PROVE_RICHIESTE = 1
# Esiti WatchGuard che valgono come patch installata («Installata», «Era già installata»).
WG_INSTALLATA = (1, 5)
AUTO_ACTOR = "system"

# Stato di un PC rispetto all'alert: etichetta e classe del badge.
VULNERABILE = "vulnerabile"
DA_VERIFICARE = "da_verificare"
CONFERMATO = "confermato"
IN_ATTESA = "in_attesa"
NON_VERIFICABILE = "non_verificabile"
ESCLUSO = "escluso"
STATI = {
    VULNERABILE: ("Ancora vulnerabile", "sec-badge-critical"),
    DA_VERIFICARE: ("Da verificare", "warning"),
    CONFERMATO: ("Aggiornato e confermato", "sec-badge-success"),
    IN_ATTESA: ("Aggiornamento rilevato, in attesa di conferma", "warning"),
    NON_VERIFICABILE: ("Non verificabile", "sec-badge-muted"),
    ESCLUSO: ("Escluso dalla verifica", "sec-badge-muted"),
}

AZIONE_PC_RISOLTO = "cve_pc_risolto"
AZIONE_PC_ESCLUSO = "cve_pc_escluso"
AZIONE_PC_INCLUSO = "cve_pc_incluso"
AZIONE_RECIDIVA = "cve_recidiva"
AZIONI_PC = (AZIONE_PC_RISOLTO, AZIONE_PC_ESCLUSO, AZIONE_PC_INCLUSO, AZIONE_RECIDIVA)

APERTI = (SecurityCveImpact.IMPACTS, SecurityCveImpact.TO_VERIFY)


def _payload(alert):
    return (alert.event.payload or {}) if alert.event_id else {}


def cve_di(alert):
    return str(_payload(alert).get("cve") or "").strip().upper()


def alert_attivo(record):
    """L'alert aperto della CVE (uno solo: dedup sulla CVE), o None."""
    from security.services.cve_impact import IMPACT_EVENT_TYPE, IMPACT_SOURCE_NAME, alert_dedup_hash

    source = SecuritySource.objects.filter(name=IMPACT_SOURCE_NAME).first()
    if source is None:
        return None
    return (
        SecurityAlert.objects.filter(source=source, dedup_hash=alert_dedup_hash(source, record),
                                     status__in=ACTIVE_ALERT_STATUSES, event__event_type=IMPACT_EVENT_TYPE)
        .select_related("event").first()
    )


# --- Titolo --------------------------------------------------------------------------------

def titolo_alert(payload, ancora, totale, recidiva=False):
    """Titolo dell'alert: «CVE-X critica: 3 PC su 5 ancora con versione vulnerabile di Prodotto»."""
    cve = str(payload.get("cve") or "").upper()
    motivo = "sfruttata attivamente (CISA KEV)" if payload.get("kev") else f"critica (CVSS {payload.get('cvss') or 'n/d'})"
    prodotto = f" di {payload['affected_product']}" if payload.get("affected_product") else ""
    if totale > ancora:
        testo = f"{cve} {motivo}: {ancora} PC su {totale} ancora con versione vulnerabile{prodotto}"
    else:
        testo = f"{cve} {motivo}: {ancora} PC con versione vulnerabile{prodotto}"
    if recidiva:
        testo = "Recidiva · " + testo
    return testo[:255]


def titolo_progresso(alert, payload=None):
    info = analisi(alert)
    return titolo_alert(payload or _payload(alert), info["ancora"], info["totale"], info["recidiva"])


# --- Analisi per PC ------------------------------------------------------------------------

def esclusioni(alert):
    """{host: voce di timeline} dei PC esclusi dalla verifica (l'ultima azione per PC vince)."""
    out = {}
    for log in alert.action_logs.filter(action__in=(AZIONE_PC_ESCLUSO, AZIONE_PC_INCLUSO)).order_by("created_at"):
        host = (log.details or {}).get("host")
        if not host:
            continue
        if log.action == AZIONE_PC_ESCLUSO:
            out[host] = log
        else:
            out.pop(host, None)
    return out


def _defender(cve_id, hosts):
    """Cosa dice Defender: None se il confronto è spento o non ha ancora letto nulla."""
    from security.services import defender_vuln

    if not soc_settings.value("defender.vulnerabilita.attivo") or not defender_vuln.dati_presenti():
        return None
    return {
        "noti": defender_vuln.host_in_defender(hosts),
        "vede": defender_vuln.per_cve(cve_id),
        "letto": DefenderVulnerabilita.objects.aggregate(m=Max("letta_il"))["m"],
    }


def _quando(dt):
    return f" il {timezone.localtime(dt):%d/%m/%Y}" if dt else ""


def _riga(host, impatto, ris, esclusione, inventario_il, patch, defender, stale_before, today, richieste):
    display = (ris.host_display if ris else "") or (impatto.installation.host_display if impatto is not None and impatto.installation_id else "") or host
    riga = {"host": host, "host_display": display, "prove": [], "contro": [], "nota": "", "risoluzione": ris,
            "versione_prima": ris.versione_prima if ris else "", "versione_dopo": ris.versione_dopo if ris else ""}

    def esito(stato):
        riga["stato"], (riga["stato_label"], riga["classe"]) = stato, STATI[stato]
        return riga

    if esclusione is not None:
        riga["nota"] = f"escluso da {esclusione.actor}{_quando(esclusione.created_at)}: {(esclusione.details or {}).get('motivo') or ''}"
        return esito(ESCLUSO)
    if impatto is not None and impatto.outcome == SecurityCveImpact.IMPACTS:
        riga["versione_prima"] = impatto.installation.version_raw if impatto.installation_id else ""
        riga["nota"] = f"versione {riga['versione_prima'] or 'n/d'} (inventario del {impatto.inventory_date:%d/%m/%Y})" if impatto.inventory_date else ""
        return esito(VULNERABILE)
    if impatto is not None:
        riga["nota"] = (impatto.explanation or "").splitlines()[0][-200:] if impatto.explanation else ""
        return esito(DA_VERIFICARE)
    if ris is None:
        riga["nota"] = "nessuna traccia di risoluzione per questo PC"
        return esito(NON_VERIFICABILE)

    # Il PC non è più esposto: quali prove lo dicono?
    stato = None
    if ris.come == SecurityCveRisoluzione.PC_ASSENTE or inventario_il is None:
        giorni = (today - timezone.localtime(ris.risolta_il).date()).days
        riga["nota"] = f"PC non più nell'inventario (non visto da {giorni} giorni)" if giorni else "PC non più nell'inventario"
        stato = NON_VERIFICABILE
    elif inventario_il < stale_before:
        riga["nota"] = f"PC non visto da {(today - inventario_il).days} giorni (inventario del {inventario_il:%d/%m/%Y})"
        stato = NON_VERIFICABILE
    elif ris.come == SecurityCveRisoluzione.AGGIORNATO:
        riga["prove"].append(f"inventario del {inventario_il:%d/%m/%Y}: {ris.software or 'programma'} {ris.versione_prima} → {ris.versione_dopo}")
    elif ris.come == SecurityCveRisoluzione.RIMOSSO:
        riga["prove"].append(f"inventario del {inventario_il:%d/%m/%Y}: programma disinstallato")
    else:
        riga["prove"].append(f"inventario del {inventario_il:%d/%m/%Y}: versione {ris.versione_prima} non più nel range vulnerabile (rivalutata)")

    mancanti = [p for p in patch if p.presente and p.esito not in WG_INSTALLATA]
    fatte = [p for p in patch if not p.presente or p.esito in WG_INSTALLATA]
    if mancanti:
        riga["contro"].append(f"patch WatchGuard «{mancanti[0].nome}» ancora mancante")
    elif fatte:
        p = fatte[0]
        riga["prove"].append(f"patch WatchGuard «{p.nome}» installata{_quando(p.esito_il if p.esito in WG_INSTALLATA else p.chiusa_il)}")
    if defender is not None and host in defender["noti"]:
        if host in defender["vede"]:
            riga["contro"].append("Defender la vede ancora su questo PC")
        else:
            riga["prove"].append(f"Defender non la segnala più{_quando(defender['letto'])}")

    if stato is not None:
        return esito(stato)
    if riga["contro"]:
        return esito(IN_ATTESA)
    return esito(CONFERMATO if len(riga["prove"]) >= richieste else IN_ATTESA)


def _verdetto(conteggi, totale, richieste):
    """(chiudibile, motivo in chiaro)."""
    if totale == 0:
        return False, "Nessun PC collegato all'alert: niente da verificare."
    if conteggi[VULNERABILE]:
        return False, f"{conteggi[VULNERABILE]} PC ancora con versione vulnerabile."
    if conteggi[DA_VERIFICARE]:
        return False, f"{conteggi[DA_VERIFICARE]} PC da verificare (versione non confrontabile o inventario vecchio)."
    if conteggi[NON_VERIFICABILE]:
        n = conteggi[NON_VERIFICABILE]
        return False, f"{n} PC non verificabil{'e' if n == 1 else 'i'}: non visto di recente. Se è dismesso o fuori uso, escludilo dalla verifica."
    if conteggi[IN_ATTESA]:
        n = conteggi[IN_ATTESA]
        return False, f"{n} PC con prove insufficienti: servono {richieste} prove concordi (inventario, patch WatchGuard, Defender)."
    if not conteggi[CONFERMATO]:
        return False, "Tutti i PC sono esclusi dalla verifica: la chiusura resta a una persona."
    testo = f"Tutti i {conteggi[CONFERMATO]} PC esposti sono aggiornati con {richieste} prove concordi"
    if conteggi[ESCLUSO]:
        testo += f" ({conteggi[ESCLUSO]} PC esclus{'o' if conteggi[ESCLUSO] == 1 else 'i'} dalla verifica da una persona)"
    return True, testo + "."


def analisi(alert, record=None, today=None):
    """Stato PC per PC dell'alert e verdetto: chiudibile o perché no.

    I PC considerati sono quelli impattati o da verificare oggi, quelli usciti dopo la nascita
    dell'alert (``SecurityCveRisoluzione``) e quelli elencati nell'evento che l'ha aperto.
    """
    from security.services.cve_impact import alert_worthy, fresh_since

    cve_id = cve_di(alert)
    record = record or SecurityCveRecord.objects.filter(cve_id=cve_id).first()
    base = {"cve": cve_id, "record": record, "pc": [], "conteggi": dict.fromkeys(STATI, 0), "ancora": 0, "totale": 0,
            "chiudibile": False, "motivo": "CVE non in archivio: niente da verificare.", "prove_richieste": PROVE_RICHIESTE_CRITICA,
            "recidiva": False, "defender_attivo": False, "watchguard_attivo": bool(soc_settings.value("watchguard.api.patch"))}
    if record is None:
        return base
    today = today or timezone.localdate()
    stale_before = fresh_since(today)
    impatti = {i.host: i for i in record.impacts.filter(outcome__in=APERTI).select_related("installation")}
    risolte = {}
    for r in record.risoluzioni.filter(risolta_il__gte=alert.created_at - timedelta(minutes=5)).order_by("risolta_il"):
        risolte[r.host] = r  # l'ultima per PC
    hosts = set(impatti) | set(risolte) | {str(h) for h in (_payload(alert).get("impacted_hosts") or [])}
    elenco = sorted(hosts)[:500]
    inventario = dict(
        SoftwareInstallation.objects.filter(host__in=elenco, still_detected=True)
        .values("host").order_by().annotate(ultimo=Max("last_inventory_date")).values_list("host", "ultimo")
    )
    patch = defaultdict(list)
    for p in WatchGuardPatch.objects.filter(host__in=elenco, cve__contains=f"|{cve_id}|").order_by("nome"):
        patch[p.host].append(p)
    defender = _defender(cve_id, elenco)
    escluse = esclusioni(alert)
    richieste = PROVE_RICHIESTE_CRITICA if alert_worthy(record) else PROVE_RICHIESTE
    righe = [
        _riga(host, impatti.get(host), risolte.get(host), escluse.get(host), inventario.get(host), patch.get(host, []),
              defender, stale_before, today, richieste)
        for host in elenco
    ]
    conteggi = Counter(r["stato"] for r in righe)
    chiudibile, motivo = _verdetto(conteggi, len(righe), richieste)
    ordine = [VULNERABILE, DA_VERIFICARE, IN_ATTESA, NON_VERIFICABILE, CONFERMATO, ESCLUSO]
    righe.sort(key=lambda r: (ordine.index(r["stato"]), r["host"]))
    return {
        **base, "pc": righe, "conteggi": {stato: conteggi.get(stato, 0) for stato in STATI}, "ancora": conteggi[VULNERABILE],
        "totale": len(righe), "chiudibile": chiudibile, "motivo": motivo, "prove_richieste": richieste,
        "recidiva": alert.action_logs.filter(action=AZIONE_RECIDIVA).exists(), "defender_attivo": defender is not None,
    }


# --- Progresso dopo il ricalcolo -----------------------------------------------------------

def _testo_pc_risolto(ris, riga):
    come = {
        SecurityCveRisoluzione.AGGIORNATO: f"aggiornato da {ris.versione_prima or 'n/d'} a {ris.versione_dopo or 'n/d'}",
        SecurityCveRisoluzione.RIMOSSO: "programma disinstallato",
        SecurityCveRisoluzione.PC_ASSENTE: "non più nell'inventario",
        SecurityCveRisoluzione.RIVALUTATA: f"rivalutata: versione {ris.versione_prima or 'n/d'} non più nel range",
    }.get(ris.come, ris.come)
    testo = f"{ris.host_display or ris.host}: {come}{_quando(ris.risolta_il)}"
    if riga is None:
        return testo
    if riga["prove"]:
        testo += ", prove: " + " + ".join(riga["prove"])
    if riga["contro"]:
        testo += "; ma " + "; ".join(riga["contro"])
    return f"{testo} ({riga['stato_label'].lower()})"


def aggiorna_alert(record, risolte):
    """Dopo un ricalcolo: la timeline dell'alert aperto registra i PC usciti, il titolo dice quanti restano."""
    from security.services.cve_impact import alert_worthy

    if not alert_worthy(record):
        return None
    alert = alert_attivo(record)
    if alert is None:
        return None
    info = analisi(alert, record)
    per_host = {r["host"]: r for r in info["pc"]}
    for ris in risolte:
        riga = per_host.get(ris.host)
        SecurityAlertActionLog.objects.create(alert=alert, action=AZIONE_PC_RISOLTO, actor=AUTO_ACTOR, details={
            "cve": record.cve_id, "host": ris.host, "come": ris.come, "versione_prima": ris.versione_prima,
            "versione_dopo": ris.versione_dopo, "stato": riga["stato"] if riga else "", "prove": riga["prove"] if riga else [],
            "testo": _testo_pc_risolto(ris, riga),
        })
    titolo = titolo_alert(_payload(alert) or {"cve": record.cve_id, "kev": record.kev, "cvss": record.cvss},
                          info["ancora"], info["totale"], info["recidiva"])
    if titolo != alert.title:
        alert.title = titolo
        alert.save(update_fields=["title", "updated_at"])
    return info


# --- Esclusione manuale --------------------------------------------------------------------

def escludi_pc(alert, host, motivo, actor, annulla=False):
    """Esclude dalla verifica un PC non verificabile (o annulla l'esclusione). Sempre con motivo, in timeline."""
    host = str(host or "").strip().lower()
    motivo = str(motivo or "").strip()
    if not host:
        raise ValueError("Indica il PC.")
    if not motivo:
        raise ValueError("Scrivi il motivo: resta nella timeline dell'alert.")
    info = analisi(alert)
    riga = next((r for r in info["pc"] if r["host"] == host), None)
    if riga is None:
        raise ValueError("Il PC non è tra quelli dell'alert.")
    if annulla:
        if riga["stato"] != ESCLUSO:
            raise ValueError("Il PC non è escluso dalla verifica.")
        azione = AZIONE_PC_INCLUSO
    else:
        if riga["stato"] != NON_VERIFICABILE:
            raise ValueError(f"Si può escludere solo un PC non verificabile; questo è «{riga['stato_label']}».")
        azione = AZIONE_PC_ESCLUSO
    return SecurityAlertActionLog.objects.create(alert=alert, action=azione, actor=actor or "ui", details={
        "cve": info["cve"], "host": host, "motivo": motivo, "stato_prima": riga["stato"],
        "testo": f"{riga['host_display']}: {'di nuovo nella verifica' if annulla else 'escluso dalla verifica'} da {actor or 'ui'}: {motivo}",
    })


# --- Recidiva ------------------------------------------------------------------------------

def riapri_recidiva(event):
    """Se la CVE aveva un alert chiuso dalla regola entro ``GIORNI_RECIDIVA`` giorni, lo riapre come recidiva.

    Torna l'alert riaperto, oppure None (nessuna chiusura automatica recente, o un alert è già attivo).
    """
    now = timezone.now()
    if SecurityAlert.objects.filter(source=event.source, dedup_hash=event.dedup_hash, status__in=ACTIVE_ALERT_STATUSES).exists():
        return None
    chiusi = (
        SecurityAlert.objects.filter(source=event.source, dedup_hash=event.dedup_hash, status=Status.RESOLVED,
                                     closed_at__gte=now - timedelta(days=GIORNI_RECIDIVA))
        .order_by("-closed_at")[:5]
    )
    for alert in chiusi:
        automatica = any(
            (log.details or {}).get("rule") == RULE_CODE
            for log in alert.action_logs.filter(action="auto_resolved").order_by("-created_at")[:3]
        )
        if not automatica:
            continue
        hosts = [str(h) for h in ((event.payload or {}).get("new_hosts") or [])]
        giorni = (now - alert.closed_at).days
        motivo = (f"Recidiva: versione vulnerabile ricomparsa su {len(hosts)} PC {giorni} giorni dopo la chiusura automatica "
                  f"del {timezone.localtime(alert.closed_at):%d/%m/%Y}.")
        vecchio = alert.status
        alert.status = Status.OPEN
        alert.status_reason = motivo
        alert.closed_at = None
        alert.snoozed_until = None
        alert.save(update_fields=["status", "status_reason", "closed_at", "snoozed_until", "updated_at"])
        SecurityAlertActionLog.objects.create(alert=alert, action=AZIONE_RECIDIVA, actor=AUTO_ACTOR, details={
            "old_status": vecchio, "new_status": Status.OPEN, "reason": motivo, "hosts": hosts[:50], "giorni": giorni,
            "testo": motivo + (" PC: " + ", ".join(hosts[:10]) if hosts else ""),
        })
        return alert
    return None


# --- Metriche ------------------------------------------------------------------------------

def metriche(giorni=90):
    """Numeri per la pagina Vulnerabilità: tempo esposto → corretto, chiusure da sole o a mano, recidive."""
    from security.services.cve_impact import IMPACT_EVENT_TYPE

    dal = timezone.now() - timedelta(days=giorni)
    corrette = list(
        SecurityCveRisoluzione.objects.filter(risolta_il__gte=dal, come__in=SecurityCveRisoluzione.CORREZIONI, aperta_dal__isnull=False)
        .select_related("cve")
    )

    def giorni_medi(righe):
        return round(mean((r.risolta_il - r.aperta_dal).total_seconds() / 86400 for r in righe), 1) if righe else None

    gravi = [r for r in corrette if r.cve.kev or (r.cve.cvss or 0) >= 9]
    chiusi = list(
        SecurityAlert.objects.filter(event__event_type=IMPACT_EVENT_TYPE, closed_at__gte=dal)
        .exclude(status__in=ACTIVE_ALERT_STATUSES).values_list("pk", "closed_at")
    )
    chiuso_il = dict(chiusi)
    automatici = {
        alert_id for alert_id, quando in SecurityAlertActionLog.objects.filter(alert_id__in=list(chiuso_il), action="auto_resolved")
        .values_list("alert_id", "created_at")
        if chiuso_il.get(alert_id) and quando >= chiuso_il[alert_id] - timedelta(minutes=1)
    }
    totale = len(chiuso_il)
    return {
        "giorni": giorni,
        "correzioni": len(corrette),
        "correzioni_gravi": len(gravi),
        "giorni_medi": giorni_medi(corrette),
        "giorni_medi_gravi": giorni_medi(gravi),
        "chiusi": totale,
        "auto": len(automatici),
        "manuali": totale - len(automatici),
        "pct_auto": round(100 * len(automatici) / totale) if totale else None,
        "recidive": SecurityAlertActionLog.objects.filter(action=AZIONE_RECIDIVA, created_at__gte=dal).count(),
        "aperti": SecurityAlert.objects.filter(event__event_type=IMPACT_EVENT_TYPE, status__in=ACTIVE_ALERT_STATUSES).count(),
    }
