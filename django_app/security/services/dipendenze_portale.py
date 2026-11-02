"""Vulnerabilità note nelle librerie Python del portale (ISO/IEC 27001:2022, controllo 8.8).

Il portale stesso è software da tenere aggiornato: le librerie installate nel suo ambiente Python
(``importlib.metadata`` dell'interprete che esegue il task, cioè il venv di produzione) si confrontano
ogni mattina con il database pubblico **OSV** (https://osv.dev, lo stesso che usa pip-audit nel release
guard). Prima le vulnerabilità delle dipendenze si vedevano solo preparando un pacchetto; quelle
pubblicate dopo il deploy non le vedeva nessuno.

- Ogni vulnerabilità di una libreria è una ``SecurityVulnerabilityFinding`` della sorgente
  ``SOURCE_NAME`` (un dispositivo esposto: il server del portale), quindi conta in Panoramica,
  report periodico e Conformità ISO come le altre. Le voci che OSV dà con più codici (PYSEC, GHSA,
  CVE dello stesso problema) diventano una sola.
- Gravità: quella del bollettino GitHub (GHSA) se c'è, altrimenti il CVSS della CVE già letta da NVD;
  senza nessuna delle due è «media» e la pagina dice «non classificata».
- Quando la libreria è aggiornata (o tolta) la vulnerabilità passa a «risolta» da sola.
- Se acceso (``dipendenze.alert.attivo``, acceso di default) nasce un evento ``dipendenza_vulnerabile``
  per libreria e versione installata, che il motore regole trasforma in alert; l'alert si chiude da solo
  quando quella versione non è più installata o non ha più vulnerabilità. Ogni passo è nell'audit
  sigillato (``traccia``).
- OSV non raggiungibile = lettura in errore, mai «nessuna vulnerabilità».
"""
from __future__ import annotations

import logging
import re
import time
from datetime import timedelta
from importlib import metadata

from django.utils import timezone

from security.models import (
    SecurityAlert,
    SecurityCveRecord,
    SecurityEventRecord,
    SecurityVulnerabilityFinding,
    Severity,
    Status,
)
from security.services import soc_settings, traccia
from security.services.alert_lifecycle import ACTIVE_ALERT_STATUSES
from security.services.dedup import make_hash

logger = logging.getLogger(__name__)

SOURCE_NAME = "Dipendenze Python del portale (OSV)"
EVENT = "dipendenza_vulnerabile"
RULE_RIENTRO = "dipendenza_aggiornata"
OSV_BATCH_URL = "https://api.osv.dev/v1/querybatch"
OSV_VULN_URL = "https://api.osv.dev/v1/vulns/{}"
USER_AGENT = "NOVICROM-HUB-SOC/1.0 (dipendenze portale)"
TIMEOUT = 20
LOTTO = 500  # pacchetti per richiesta a querybatch (limite OSV: 1000)
DETTAGLI_MAX = 300  # bollettini letti per giro
TEMPO_MAX = 240  # secondi; la lettura è «lunga» (timeout coda 600 s)

APERTE = (Status.OPEN, Status.NEW, Status.ACKNOWLEDGED, Status.IN_PROGRESS)
_ORDINE = {Severity.CRITICAL: 4, Severity.HIGH: 3, Severity.MEDIUM: 2, Severity.LOW: 1, Severity.INFO: 0}
_GHSA = {"CRITICAL": Severity.CRITICAL, "HIGH": Severity.HIGH, "MODERATE": Severity.MEDIUM, "MEDIUM": Severity.MEDIUM,
         "LOW": Severity.LOW}
ETICHETTE_GRAVITA = {Severity.CRITICAL: "Critica", Severity.HIGH: "Alta", Severity.MEDIUM: "Media", Severity.LOW: "Bassa"}


class OsvError(Exception):
    """OSV non ha risposto come atteso: la lettura va in errore."""


def nome_normale(nome: str) -> str:
    """Nome PEP 503 (``Django_Q2`` e ``django-q2`` sono lo stesso pacchetto)."""
    return re.sub(r"[-_.]+", "-", (nome or "").strip()).lower()


def pacchetti_installati() -> dict:
    """{nome normalizzato: versione} delle librerie dell'interprete che esegue il codice."""
    out = {}
    for dist in metadata.distributions():
        nome = nome_normale(dist.metadata.get("Name") or "")
        if nome and dist.version:
            out.setdefault(nome, dist.version)
    return out


def source():
    from security.models import SecuritySource, SourceType

    src, _ = SecuritySource.objects.get_or_create(name=SOURCE_NAME, defaults={"source_type": SourceType.API, "vendor": "osv"})
    return src


# --- OSV ---------------------------------------------------------------------------------------

def _http(metodo, url, **kw):
    import requests

    try:
        r = requests.request(metodo, url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, **kw)
    except requests.RequestException as exc:
        raise OsvError(f"OSV non raggiungibile ({type(exc).__name__})") from exc
    if r.status_code != 200:
        raise OsvError(f"OSV ha risposto {r.status_code}")
    try:
        return r.json()
    except ValueError as exc:
        raise OsvError("risposta di OSV non leggibile") from exc


def interroga_osv(pacchetti: dict) -> dict:
    """{nome: [id vulnerabilità]} per i pacchetti con almeno una vulnerabilità nota."""
    nomi = sorted(pacchetti)
    out = {}
    for i in range(0, len(nomi), LOTTO):
        lotto = nomi[i:i + LOTTO]
        body = {"queries": [{"package": {"name": n, "ecosystem": "PyPI"}, "version": pacchetti[n]} for n in lotto]}
        risultati = (_http("POST", OSV_BATCH_URL, json=body) or {}).get("results")
        if not isinstance(risultati, list) or len(risultati) != len(lotto):
            raise OsvError("risposta di OSV incompleta")
        for nome, r in zip(lotto, risultati, strict=True):
            ids = [v.get("id") for v in (r or {}).get("vulns") or [] if v.get("id")]
            if ids:
                out[nome] = ids
    return out


def _gravita(dettaglio: dict) -> str:
    sev = str((dettaglio.get("database_specific") or {}).get("severity") or "").upper()
    return _GHSA.get(sev, "")


def _corrette(dettaglio: dict, nome: str) -> list:
    out = []
    for aff in dettaglio.get("affected") or []:
        pkg = aff.get("package") or {}
        if pkg.get("ecosystem") != "PyPI" or nome_normale(pkg.get("name")) != nome:
            continue
        for rng in aff.get("ranges") or []:
            out += [e["fixed"] for e in rng.get("events") or [] if e.get("fixed")]
    return out


def _cvss_gravita(cvss):
    if cvss is None:
        return ""
    return Severity.CRITICAL if cvss >= 9 else Severity.HIGH if cvss >= 7 else Severity.MEDIUM if cvss >= 4 else Severity.LOW


def raggruppa(nome: str, ids: list, dettagli: dict) -> list[dict]:
    """Una voce per problema: gli id che si citano come alias (PYSEC, GHSA, CVE) si uniscono."""
    gruppi: list[set] = []
    for vid in ids:
        alias = {vid, *((dettagli.get(vid) or {}).get("aliases") or [])}
        uniti = [g for g in gruppi if g & alias]
        for g in uniti:
            gruppi.remove(g)
            alias |= g
        gruppi.append(alias)
    voci = []
    for g in gruppi:
        cve = sorted(x for x in g if x.startswith("CVE-"))
        noti = [x for x in ids if x in g]
        principale = cve[0] if cve else next((x for x in sorted(g) if x.startswith("GHSA-")), sorted(noti)[0])
        gravita, corrette, testo = "", set(), ""
        for vid in noti:
            d = dettagli.get(vid) or {}
            g_sev = _gravita(d)
            if _ORDINE.get(g_sev, -1) > _ORDINE.get(gravita, -1):
                gravita = g_sev
            corrette.update(_corrette(d, nome))
            testo = testo or (d.get("summary") or d.get("details") or "")
        cvss = None
        if cve:
            cvss = max((c for c in SecurityCveRecord.objects.filter(cve_id__in=cve).values_list("cvss", flat=True) if c is not None), default=None)
        fonte = "GitHub (GHSA)" if gravita else ""
        if not gravita and cvss is not None:
            gravita, fonte = _cvss_gravita(cvss), "CVSS da NVD"
        voci.append({
            "id": principale, "codici": sorted(g), "cve": cve, "gravita": gravita or Severity.MEDIUM,
            "classificata": bool(gravita), "fonte_gravita": fonte, "cvss": cvss,
            "corretta_in": sorted(corrette, key=_chiave_versione), "descrizione": testo.strip()[:500],
        })
    return voci


def _chiave_versione(v):
    return [int(x) if x.isdigit() else 0 for x in re.split(r"[.+-]", v)[:6]]


# --- Giro --------------------------------------------------------------------------------------

def run(pacchetti: dict | None = None) -> dict:
    """Lettura ``dipendenze_portale`` (ogni mattina, «Esegui ora» in Letture automatiche)."""
    if not soc_settings.value("dipendenze.controllo.attivo"):
        return {"skipped": "controllo delle dipendenze spento"}
    inizio = time.monotonic()
    pacchetti = pacchetti if pacchetti is not None else pacchetti_installati()
    try:
        trovati = interroga_osv(pacchetti)
    except OsvError as exc:
        return {"ok": False, "errore": str(exc)}  # nessun numero: la lettura è «errore», non «parziale»
    dettagli, non_letti = {}, 0
    for vid in sorted({v for ids in trovati.values() for v in ids}):
        if len(dettagli) >= DETTAGLI_MAX or time.monotonic() - inizio > TEMPO_MAX:
            non_letti += 1
            continue
        try:
            dettagli[vid] = _http("GET", OSV_VULN_URL.format(vid)) or {}
        except OsvError:
            non_letti += 1
    src = source()
    visti, nuove = set(), 0
    adesso = timezone.now()
    for nome, ids in sorted(trovati.items()):
        versione = pacchetti[nome]
        for voce in raggruppa(nome, ids, dettagli):
            dedup = make_hash(src.pk, nome, voce["id"])
            visti.add(dedup)
            payload = {"pacchetto": nome, "versione": versione, **voce}
            f = SecurityVulnerabilityFinding.objects.filter(source=src, dedup_hash=dedup).first()
            if f is None:
                SecurityVulnerabilityFinding.objects.create(
                    source=src, dedup_hash=dedup, cve=voce["id"][:32], affected_product=f"{nome} {versione}"[:255],
                    cvss=voce["cvss"] or 0.0, exposed_devices=1, severity=voce["gravita"], status=Status.OPEN,
                    payload=payload, first_seen_at=adesso, last_seen_at=adesso,
                )
                nuove += 1
                continue
            if f.status not in APERTE:
                f.status = Status.OPEN  # tornata (es. versione riportata indietro)
            f.affected_product, f.severity, f.cvss = f"{nome} {versione}"[:255], voce["gravita"], voce["cvss"] or 0.0
            f.payload, f.last_seen_at, f.exposed_devices = payload, adesso, 1
            f.save(update_fields=["status", "affected_product", "severity", "cvss", "payload", "last_seen_at", "exposed_devices"])
    risolte = 0
    for f in SecurityVulnerabilityFinding.objects.filter(source=src, status__in=APERTE).exclude(dedup_hash__in=visti):
        f.status, f.exposed_devices = Status.RESOLVED, 0
        f.payload = {**(f.payload or {}), "risolta_il": adesso.isoformat(),
                     "versione_dopo": pacchetti.get((f.payload or {}).get("pacchetto"), "non installata")}
        f.save(update_fields=["status", "exposed_devices", "payload"])
        risolte += 1
    eventi, chiusi = segnala(src)
    out = {"pacchetti": len(pacchetti), "vulnerabili": len(trovati), "vulnerabilita": len(visti), "nuove": nuove,
           "risolte": risolte, "eventi": eventi, "alert_chiusi": chiusi}
    if non_letti:
        out["errore"] = f"{non_letti} bollettini OSV non letti: gravità e versioni corrette incomplete"
    return out


def aperte(src=None):
    return SecurityVulnerabilityFinding.objects.filter(source=src or source(), status__in=APERTE)


def per_pacchetto(src=None) -> list[dict]:
    """Librerie con vulnerabilità aperte: [{pacchetto, versione, gravita, corretta_in, voci}], le più gravi in cima."""
    gruppi = {}
    for f in aperte(src).order_by("cve"):
        p = f.payload or {}
        g = gruppi.setdefault(p.get("pacchetto") or f.affected_product, {
            "pacchetto": p.get("pacchetto") or f.affected_product, "versione": p.get("versione") or "",
            "gravita": f.severity, "voci": [], "corretta_in": set(), "dal": f.first_seen_at})
        g["voci"].append(f)
        g["corretta_in"].update(p.get("corretta_in") or [])
        g["dal"] = min(g["dal"], f.first_seen_at)
        if _ORDINE.get(f.severity, 0) > _ORDINE.get(g["gravita"], 0):
            g["gravita"] = f.severity
    out = []
    for g in gruppi.values():
        versioni = sorted(g["corretta_in"], key=_chiave_versione)
        # la più bassa che corregge tutto: la più alta fra le versioni minime di ogni voce
        minime = [min((p for p in (v.payload or {}).get("corretta_in") or []), key=_chiave_versione, default=None) for v in g["voci"]]
        g["aggiorna_a"] = max((m for m in minime if m), key=_chiave_versione, default="") if all(minime) else ""
        g["corretta_in"] = versioni
        g["etichetta"] = ETICHETTE_GRAVITA.get(g["gravita"], g["gravita"])
        out.append(g)
    return sorted(out, key=lambda g: (-_ORDINE.get(g["gravita"], 0), g["pacchetto"]))


def risolte_recenti(giorni=90, src=None, limite=200) -> list:
    """Vulnerabilità risolte negli ultimi ``giorni`` (``risolta_il`` nel payload), la più recente in cima."""
    from django.utils.dateparse import parse_datetime

    dal = timezone.now() - timedelta(days=giorni)
    out = []
    # last_seen_at è l'ultimo controllo che l'ha vista aperta: sempre prima della risoluzione
    for f in SecurityVulnerabilityFinding.objects.filter(source=src or source(), status=Status.RESOLVED,
                                                         last_seen_at__gte=dal - timedelta(days=1)):
        f.risolta_il = parse_datetime(str((f.payload or {}).get("risolta_il") or "")) or f.last_seen_at
        if f.risolta_il >= dal:
            out.append(f)
    return sorted(out, key=lambda f: f.risolta_il, reverse=True)[:limite]


# --- Alert -------------------------------------------------------------------------------------

def _dedup_evento(src, g):
    return make_hash(src.pk, EVENT, g["pacchetto"], g["versione"])


def segnala(src=None):
    """Un evento per libreria e versione installata con vulnerabilità aperte; chiude gli alert rientrati.

    Torna ``(eventi creati, alert chiusi)``. Con l'interruttore spento non crea eventi ma chiude i rientrati.
    """
    src = src or source()
    gruppi = per_pacchetto(src)
    creati = 0
    if soc_settings.value("dipendenze.alert.attivo"):
        for g in gruppi:
            dedup = _dedup_evento(src, g)
            if SecurityEventRecord.objects.filter(source=src, event_type=EVENT, dedup_hash=dedup).exists():
                continue
            payload = {
                "pacchetto": g["pacchetto"], "versione": g["versione"], "gravita": g["gravita"], "etichetta": g["etichetta"],
                "vulnerabilita": [v.cve for v in g["voci"]][:30], "aggiorna_a": g["aggiorna_a"], "alert_candidate": True,
            }
            event = SecurityEventRecord.objects.create(
                source=src, event_type=EVENT, severity=g["gravita"], occurred_at=timezone.now(),
                fingerprint=dedup, dedup_hash=dedup, payload=payload,
            )
            traccia.registra(traccia.DIPENDENZA_VULNERABILE, {
                "pacchetto": g["pacchetto"], "versione": g["versione"], "gravita": g["gravita"],
                "vulnerabilita": payload["vulnerabilita"], "evento_id": event.pk, "regola": EVENT,
            })
            creati += 1
    return creati, chiudi_rientrati(gruppi, src)


def ancora_vulnerabile(event) -> bool:
    """L'evento riguarda una libreria e versione che ha ancora vulnerabilità aperte (non aggiornata nel frattempo)."""
    return event.dedup_hash in {_dedup_evento(event.source, g) for g in per_pacchetto(event.source)}


def chiudi_rientrati(gruppi=None, src=None):
    from security.services.auto_resolution import resolve_alert

    src = src or source()
    ancora = {_dedup_evento(src, g) for g in (per_pacchetto(src) if gruppi is None else gruppi)}
    chiusi = 0
    for alert in SecurityAlert.objects.filter(source=src, status__in=ACTIVE_ALERT_STATUSES, event__event_type=EVENT).select_related("event"):
        if alert.dedup_hash in ancora:
            continue
        p = (alert.event.payload or {}) if alert.event_id else {}
        motivo = f"{p.get('pacchetto')} {p.get('versione')}: non più installata o senza vulnerabilità note (libreria aggiornata)."
        resolve_alert(alert, motivo[:500], rule_code=RULE_RIENTRO)
        traccia.registra(traccia.DIPENDENZA_AGGIORNATA, {
            "pacchetto": p.get("pacchetto"), "versione": p.get("versione"), "alert_id": alert.pk, "motivo": motivo, "regola": RULE_RIENTRO,
        }, oggetto=alert)
        chiusi += 1
    return chiusi


def titolo_evento(payload):
    n = len(payload.get("vulnerabilita") or [])
    agg = f", aggiornare a {payload['aggiorna_a']}" if payload.get("aggiorna_a") else ""
    return (f"Libreria del portale vulnerabile: {payload.get('pacchetto')} {payload.get('versione')}, "
            f"{n} vulnerabilit{'à nota' if n == 1 else 'à note'}{agg}")[:255]
