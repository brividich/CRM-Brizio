"""Arricchimento CVE: NVD CVE API 2.0 (configurazioni CPE e range), CISA KEV, EPSS.

Gira solo nel job django-q ``enrich_cve_task`` (mai in una request, mai dentro
``transaction.atomic``). Ogni chiamata ha timeout, retry con backoff e rispetta il rate
limit NVD (5 richieste / 30 s senza API key, 50 con la key). I risultati vanno nella
cache dedicata ``SecurityExternalFeedCache`` con TTL, poi in ``SecurityCveRecord``.
Nessun test usa la rete: ``http_get`` si sostituisce con un mock.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from datetime import date, timedelta
from datetime import timezone as dt_timezone

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from security.models import SecurityCenterSetting, SecurityCveRecord, SecurityExternalFeedCache, SecurityVulnerabilityFinding
from security.services import secret_box

logger = logging.getLogger(__name__)

NVD_CVE_URL = "https://services.nvd.nist.gov/rest/json/cves/2.0"
NVD_CPE_URL = "https://services.nvd.nist.gov/rest/json/cpes/2.0"
KEV_URL = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
EPSS_URL = "https://api.first.org/data/v1/epss"

NVD_KEY_SETTING = "cve.nvd_api_key"
NVD_KEY_PURPOSE = "nvd-api-key"
TIMEOUT_SECONDS = 20
RETRIES = 3
# ``nvd_rinvio``: CVE la cui lettura NVD è andata in errore, rimandate di un giorno (non tornano in testa a ogni giro).
TTL = {"nvd_cve": timedelta(days=7), "nvd_cpe": timedelta(days=30), "kev": timedelta(hours=24), "epss": timedelta(hours=24),
       "nvd_rinvio": timedelta(hours=24)}
BLOCCO = 500
RETRY_AFTER_MAX = 60  # secondi: un Retry-After più lungo si rispetta fermando il giro, non aspettando
USER_AGENT = "NOVICROM-HUB-SOC/1.0 (vulnerability enrichment)"


class FeedError(RuntimeError):
    pass


class BudgetExhausted(FeedError):
    """Il giro del job ha finito il tempo: si riprende al prossimo."""


class ApiKeyError(FeedError):
    """NVD rifiuta l'API key impostata (403/404 con la chiave): inutile riprovare, né per questa CVE né per le altre."""


# --- Trasporto -------------------------------------------------------------------------------

def http_get(url, *, params=None, headers=None, timeout=TIMEOUT_SECONDS):
    """Unico punto che va in rete (sostituito dai test).

    Ritorna (status_code, json|None, intestazioni utili): Content-Type e Server dicono chi ha risposto
    davvero (un proxy risponde HTML), Retry-After quanto aspettare. I mock possono tornare solo (status, json).
    """
    import requests

    response = requests.get(url, params=params, headers={"User-Agent": USER_AGENT, **(headers or {})}, timeout=timeout)
    try:
        body = response.json()
    except ValueError:
        body = None
    info = {k: str(response.headers.get(k) or "") for k in ("Content-Type", "Server", "Retry-After")}
    return response.status_code, body, info


def _chi_risponde(info) -> str:
    """Se la risposta non è JSON, chi ha risposto (header Server): un proxy o una pagina di errore, non il servizio."""
    tipo = str((info or {}).get("Content-Type") or "")
    server = str((info or {}).get("Server") or "")[:60]
    if not tipo or "json" in tipo.lower():
        return ""
    dettagli = ", ".join(x for x in (f"server «{server}»" if server else "", f"tipo «{tipo[:40]}»" if tipo else "") if x)
    return (" La risposta non arriva dal servizio" + (f" ({dettagli})" if dettagli else "")
            + ": risponde un proxy o un altro servizio.")


def _retry_after(info):
    """Secondi di Retry-After (solo la forma numerica), None se assente o non leggibile."""
    valore = str((info or {}).get("Retry-After") or "").strip()
    return int(valore) if valore.isdigit() else None


class RateLimiter:
    """Finestra scorrevole: al massimo ``limit`` richieste ogni ``window`` secondi."""

    def __init__(self, limit, window=30.0, clock=time.monotonic, sleep=time.sleep):
        self.limit, self.window, self.clock, self.sleep = limit, window, clock, sleep
        self.calls = deque()

    def wait(self):
        now = self.clock()
        while self.calls and now - self.calls[0] >= self.window:
            self.calls.popleft()
        if len(self.calls) >= self.limit:
            pause = self.window - (now - self.calls[0]) + 0.1
            self.sleep(max(pause, 0))
            now = self.clock()
            while self.calls and now - self.calls[0] >= self.window:
                self.calls.popleft()
        self.calls.append(self.clock())


def _get_json(url, *, params=None, headers=None, limiter=None, sleep=time.sleep, deadline=None, clock=time.monotonic):
    """``deadline`` (secondi di ``clock``): nessuna attesa o richiesta lo supera."""
    last_error = ""
    for attempt in range(RETRIES):
        if deadline is not None and clock() >= deadline:
            raise BudgetExhausted(f"{url}: tempo del job esaurito")
        if limiter:
            limiter.wait()
        timeout = TIMEOUT_SECONDS
        if deadline is not None:
            timeout = max(1, min(TIMEOUT_SECONDS, int(deadline - clock())))
        info = {}
        try:
            risposta = http_get(url, params=params, headers=headers, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 - errori di rete: riprovo con backoff, poi FeedError
            status, body, last_error = 0, None, f"{exc.__class__.__name__}: {exc}"[:300]
        else:
            status, body = risposta[0], risposta[1]
            info = risposta[2] if len(risposta) > 2 else {}
            if status == 200 and body is not None:
                return body
            if status == 200:
                raise FeedError(f"{url}: risposta 200 non JSON.{_chi_risponde(info)}")
            chi = _chi_risponde(info)
            if status in (403, 404) and (headers or {}).get("apiKey") and not chi:
                oltre = " o ha superato il limite di richieste" if status == 403 else ""
                raise ApiKeyError(f"NVD ha risposto {status} con l'API key impostata: la chiave non è valida, è stata "
                                  f"revocata{oltre}. Aggiornala o rimuovila in «Software e CPE», riquadro «API key NVD».")
            if status == 404:
                raise FeedError(f"{url}: 404{chi}")
            last_error = f"HTTP {status}{chi}"
            if status not in (0, 403, 429, 500, 502, 503, 504):
                raise FeedError(f"{url}: {last_error}")
        pause = 2 ** (attempt + 1)  # 2, 4, 8 s (NVD risponde 403/429 quando si supera il limite)
        attesa = _retry_after(info) if status in (429, 503) else None
        if attesa is not None:
            if attesa > RETRY_AFTER_MAX:
                raise BudgetExhausted(f"{url}: il servizio chiede di riprovare fra {attesa} s ({last_error})")
            pause = max(pause, attesa)
        if deadline is not None and clock() + pause >= deadline:
            raise BudgetExhausted(f"{url}: tempo del job esaurito ({last_error})")
        sleep(pause)
    raise FeedError(f"{url}: {last_error or 'nessuna risposta'}")


# --- Cache dedicata --------------------------------------------------------------------------

def cache_get(feed, key):
    entry = SecurityExternalFeedCache.objects.filter(feed=feed, key=key[:190], expires_at__gt=timezone.now()).first()
    return entry.payload if entry else None


def cache_put(feed, key, payload, status_code=200, error=""):
    now = timezone.now()
    SecurityExternalFeedCache.objects.update_or_create(
        feed=feed, key=key[:190],
        defaults={"payload": payload if isinstance(payload, (dict, list)) else {"value": payload}, "status_code": status_code,
                  "error": error[:500], "fetched_at": now, "expires_at": now + TTL[feed]},
    )


# --- API key ---------------------------------------------------------------------------------

def nvd_api_key():
    setting = SecurityCenterSetting.objects.filter(key=NVD_KEY_SETTING).first()
    return secret_box.decrypt(setting.value, NVD_KEY_PURPOSE) if setting else ""


def set_nvd_api_key(raw_key, actor=None):
    from security.services.configuration import audit_config_change

    setting, _ = SecurityCenterSetting.objects.get_or_create(
        key=NVD_KEY_SETTING, defaults={"category": "cve", "is_secret": True, "description": "API key NVD (cifrata)"})
    had_key = bool(setting.value)
    setting.value = secret_box.encrypt(raw_key.strip(), NVD_KEY_PURPOSE) if raw_key else ""
    setting.is_secret = True
    setting.updated_by = actor if getattr(actor, "pk", None) else None
    setting.save()
    audit_config_change(actor, "update", setting, field_name="value", old_value="***" if had_key else "",
                        new_value="***" if raw_key else "")


def nvd_limiter():
    return RateLimiter(50 if nvd_api_key() else 5, 30.0)


def _nvd_headers():
    key = nvd_api_key()
    return {"apiKey": key} if key else {}


# --- Parsing NVD -----------------------------------------------------------------------------

def parse_cpe(criteria):
    parts = str(criteria or "").split(":")
    if len(parts) < 6 or parts[0] != "cpe":
        return None
    return {"part": parts[2], "vendor": parts[3], "product": parts[4], "version": parts[5]}


def parse_nvd_cve(cve):
    """Dal JSON NVD 2.0 a campi del record: CVSS, configurazioni piatte e ambiguità."""
    metrics = cve.get("metrics") or {}
    cvss, severity = None, ""
    for key in ("cvssMetricV40", "cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        for metric in metrics.get(key) or []:
            data = metric.get("cvssData") or {}
            if data.get("baseScore") is not None:
                cvss = float(data["baseScore"])
                severity = str(data.get("baseSeverity") or metric.get("baseSeverity") or "").lower()
                break
        if cvss is not None:
            break
    criteria, ambiguous = [], False
    for config in cve.get("configurations") or []:
        nodes = config.get("nodes") or []
        requires_platform = str(config.get("operator") or "OR").upper() == "AND" and len(nodes) > 1
        for node in nodes:
            if node.get("negate"):
                ambiguous = True
            for match in node.get("cpeMatch") or []:
                if not match.get("vulnerable"):
                    continue
                cpe = parse_cpe(match.get("criteria"))
                if not cpe:
                    ambiguous = True
                    continue
                criteria.append({
                    **cpe,
                    "start_including": match.get("versionStartIncluding") or "",
                    "start_excluding": match.get("versionStartExcluding") or "",
                    "end_including": match.get("versionEndIncluding") or "",
                    "end_excluding": match.get("versionEndExcluding") or "",
                    "requires_platform": requires_platform,
                })
    description = next((d.get("value", "") for d in cve.get("descriptions") or [] if d.get("lang") == "en"), "")
    return {
        "cvss": cvss, "severity": severity, "configurations": criteria, "ambiguous_configuration": ambiguous,
        "description": description[:4000],
        "published_at": parse_datetime(cve.get("published") or "") if cve.get("published") else None,
        "nvd_last_modified": parse_datetime(cve.get("lastModified") or "") if cve.get("lastModified") else None,
    }


def _aware(value):
    if value and timezone.is_naive(value):
        return timezone.make_aware(value, dt_timezone.utc)
    return value


def fetch_nvd_cve(cve_id, limiter=None, sleep=time.sleep, deadline=None, clock=time.monotonic):
    cached = cache_get("nvd_cve", cve_id)
    if cached is not None:
        return cached
    body = _get_json(NVD_CVE_URL, params={"cveId": cve_id}, headers=_nvd_headers(), limiter=limiter, sleep=sleep,
                     deadline=deadline, clock=clock)
    items = body.get("vulnerabilities") or []
    payload = items[0].get("cve", {}) if items else {}
    cache_put("nvd_cve", cve_id, payload)
    return payload


def enrich_cve(cve_id, limiter=None, sleep=time.sleep, deadline=None, clock=time.monotonic):
    record, _ = SecurityCveRecord.objects.get_or_create(cve_id=cve_id)
    try:
        payload = fetch_nvd_cve(cve_id, limiter=limiter, sleep=sleep, deadline=deadline, clock=clock)
    except (BudgetExhausted, ApiKeyError):
        raise
    except FeedError as exc:
        record.nvd_error = str(exc)[:300]
        record.save(update_fields=["nvd_error"])
        # rimandata di un giorno: non torna in testa alla coda a ogni giro togliendo posto alle altre
        cache_put("nvd_rinvio", cve_id, {"errore": record.nvd_error}, status_code=0, error=record.nvd_error)
        return record
    if not payload:
        record.nvd_error = "CVE non presente in NVD"
        record.nvd_fetched_at = timezone.now()
        record.save(update_fields=["nvd_error", "nvd_fetched_at"])
        return record
    fields = parse_nvd_cve(payload)
    fields["published_at"] = _aware(fields["published_at"])
    fields["nvd_last_modified"] = _aware(fields["nvd_last_modified"])
    for name, value in fields.items():
        setattr(record, name, value)
    record.nvd_error = ""
    record.nvd_fetched_at = timezone.now()
    record.save()
    return record


# --- CISA KEV e EPSS -------------------------------------------------------------------------

def refresh_kev(sleep=time.sleep, deadline=None, clock=time.monotonic):
    catalog = cache_get("kev", "catalog")
    if catalog is None:
        body = _get_json(KEV_URL, sleep=sleep, deadline=deadline, clock=clock)
        catalog = {
            item["cveID"].upper(): {"added": item.get("dateAdded", ""), "due": item.get("dueDate", "")}
            for item in body.get("vulnerabilities") or [] if item.get("cveID")
        }
        cache_put("kev", "catalog", catalog)
    _controlla_tempo(deadline, clock, "KEV")
    cambiati = []
    for record in SecurityCveRecord.objects.all().only("pk", "cve_id", "kev", "kev_added", "kev_due"):
        entry = catalog.get(record.cve_id.upper())
        kev, added, due = bool(entry), _date(entry, "added"), _date(entry, "due")
        if (record.kev, record.kev_added, record.kev_due) != (kev, added, due):
            record.kev, record.kev_added, record.kev_due = kev, added, due
            cambiati.append(record)
    if cambiati:
        SecurityCveRecord.objects.bulk_update(cambiati, ["kev", "kev_added", "kev_due"], batch_size=BLOCCO)
    return len(cambiati)


def _controlla_tempo(deadline, clock, passo):
    if deadline is not None and clock() >= deadline:
        raise BudgetExhausted(f"{passo}: tempo del job esaurito")


def _date(entry, key):
    if not entry or not entry.get(key):
        return None
    try:
        return date.fromisoformat(entry[key])
    except ValueError:
        return None


def refresh_epss(cve_ids, sleep=time.sleep, deadline=None, clock=time.monotonic):
    import hashlib

    updated = 0
    ids = sorted({c.upper() for c in cve_ids})
    for start in range(0, len(ids), 100):
        chunk = ids[start:start + 100]
        joined = ",".join(chunk)
        key = hashlib.sha256(joined.encode()).hexdigest()  # la lista intera supera la colonna: niente collisioni
        data = cache_get("epss", key)
        if data is None:
            body = _get_json(EPSS_URL, params={"cve": joined}, sleep=sleep, deadline=deadline, clock=clock)
            data = {row["cve"].upper(): [row.get("epss"), row.get("percentile")] for row in body.get("data") or [] if row.get("cve")}
            cache_put("epss", key, data)
        _controlla_tempo(deadline, clock, "EPSS")
        valori = {}
        for cve_id, coppia in data.items():
            try:
                score, percentile = coppia
                valori[cve_id] = (float(score), float(percentile))
            except (TypeError, ValueError):
                continue
        # solo i valori cambiati, in un'unica scrittura per blocco
        cambiati = []
        for record in SecurityCveRecord.objects.filter(cve_id__in=list(valori)).only("pk", "cve_id", "epss", "epss_percentile"):
            nuovo = valori.get(record.cve_id.upper())
            if nuovo and (record.epss, record.epss_percentile) != nuovo:
                record.epss, record.epss_percentile = nuovo
                cambiati.append(record)
        if cambiati:
            SecurityCveRecord.objects.bulk_update(cambiati, ["epss", "epss_percentile"], batch_size=BLOCCO)
        updated += len(cambiati)
    return updated


# --- Dizionario CPE (suggerimenti di mappatura) ----------------------------------------------

def suggest_cpe(vendor, product, limiter=None, sleep=time.sleep):
    """Suggerimenti (vendor, product, titolo) dal dizionario CPE NVD: si confermano a mano."""
    keyword = " ".join(part for part in (vendor, product) if part).strip()[:100]
    if not keyword:
        return []
    cached = cache_get("nvd_cpe", keyword)
    if cached is None:
        body = _get_json(NVD_CPE_URL, params={"keywordSearch": keyword, "resultsPerPage": 20}, headers=_nvd_headers(),
                         limiter=limiter, sleep=sleep)
        seen, cached = set(), []
        for item in body.get("products") or []:
            cpe_obj = item.get("cpe") or {}
            if cpe_obj.get("deprecated"):
                continue
            parsed = parse_cpe(cpe_obj.get("cpeName"))
            if not parsed or (parsed["vendor"], parsed["product"]) in seen:
                continue
            seen.add((parsed["vendor"], parsed["product"]))
            title = next((t.get("title", "") for t in cpe_obj.get("titles") or [] if t.get("lang") == "en"), "")
            cached.append({"cpe_vendor": parsed["vendor"], "cpe_product": parsed["product"], "title": title[:200]})
        cache_put("nvd_cpe", keyword, cached)
    return cached


# --- Elenco CVE da arricchire ----------------------------------------------------------------

def known_cve_ids(days=180):
    since = timezone.now() - timedelta(days=days)
    ids = set(SecurityVulnerabilityFinding.objects.filter(last_seen_at__gte=since).values_list("cve", flat=True).distinct())
    ids |= set(SecurityCveRecord.objects.values_list("cve_id", flat=True))
    ids |= set(_cve_da_defender())
    return sorted({i.strip().upper() for i in ids if i and i.strip().upper().startswith("CVE-")})


def _cve_da_defender():
    """Le CVE gravi di Defender, le critiche per prime (vuoto se il calcolo ibrido è spento)."""
    from security.services import defender_vuln

    return list(defender_vuln.cve_per_calcolo()) if defender_vuln.ibrido_attivo() else []


def stale_cve_ids(limit):
    ids = known_cve_ids()
    fresh_before = timezone.now() - TTL["nvd_cve"]
    fresh = set(SecurityCveRecord.objects.filter(nvd_fetched_at__gte=fresh_before).values_list("cve_id", flat=True))
    # in errore di recente: rimandate di un giorno (TTL ``nvd_rinvio``)
    fresh |= set(SecurityExternalFeedCache.objects.filter(feed="nvd_rinvio", expires_at__gt=timezone.now())
                 .values_list("key", flat=True))
    missing = [cve for cve in ids if cve not in fresh]
    # Prima quelle che Defender vede davvero sui PC: con un limite di richieste a NVD contano di più.
    priorita = {cve: i for i, cve in enumerate(_cve_da_defender())}
    missing.sort(key=lambda cve: priorita.get(cve, len(priorita)))
    return missing[:limit]


def run_enrichment(time_budget_seconds=90, clock=time.monotonic, sleep=time.sleep, recompute=None):
    """Un giro del job: KEV, CVE NVD mancanti/scadute, EPSS, poi il ricalcolo degli impatti.

    Ogni attesa e richiesta rispetta ``deadline`` (timeout worker 120 s): quando il tempo finisce
    il giro si ferma e riprende al successivo; il ricalcolo degli impatti va in un task a parte.
    """
    deadline = clock() + time_budget_seconds
    result = {"nvd": 0, "nvd_errors": 0, "kev_updated": 0, "epss_updated": 0, "recompute": "", "errors": []}
    try:
        _crea_mancanti(known_cve_ids())
        try:
            result["kev_updated"] = refresh_kev(sleep=sleep, deadline=deadline, clock=clock)
        except BudgetExhausted:
            raise
        except FeedError as exc:
            result["errors"].append(f"KEV: {exc}")
            logger.warning("CISA KEV non aggiornato: %s", exc)
        limiter = RateLimiter(50 if nvd_api_key() else 5, 30.0, clock=clock, sleep=sleep)
        _controlla_tempo(deadline, clock, "NVD")
        try:
            for cve_id in stale_cve_ids(limit=200):
                # Ultimo slot di rate limit troppo vicino alla scadenza: meglio fermarsi qui.
                if clock() >= deadline:
                    raise BudgetExhausted("tempo del job esaurito")
                record = enrich_cve(cve_id, limiter=limiter, sleep=sleep, deadline=deadline, clock=clock)
                result["nvd_errors" if record.nvd_error else "nvd"] += 1
        except ApiKeyError as exc:
            result["errors"].append(f"NVD: {exc}")  # la chiave vale per tutte: inutile provare le altre CVE
            logger.warning("NVD: %s", exc)
        if get_epss_enabled():
            _controlla_tempo(deadline, clock, "EPSS")
            try:
                result["epss_updated"] = refresh_epss(known_cve_ids(), sleep=sleep, deadline=deadline, clock=clock)
            except BudgetExhausted:
                raise
            except FeedError as exc:
                result["errors"].append(f"EPSS: {exc}")
        _controlla_tempo(deadline, clock, "collegamento automatico")
    except BudgetExhausted as exc:
        result["errors"].append(f"budget di tempo esaurito: il resto al prossimo giro ({exc})"[:300])
        result["recompute"] = (recompute or queue_recompute)()
        return result
    try:
        # Prodotti dell'inventario con nome identico a un CPE delle CVE scaricate: collegati da soli.
        from security.services.cpe_auto import auto_link

        result["auto_linked"] = auto_link()
    except Exception as exc:  # noqa: BLE001 - il collegamento automatico non deve fermare il ricalcolo
        logger.exception("Collegamento automatico CPE non eseguito")
        result["errors"].append(f"collegamento automatico: {exc}"[:200])
    result["recompute"] = (recompute or queue_recompute)()
    return result


def _crea_mancanti(cve_ids):
    """Record delle CVE nuove, in blocchi: una query per le esistenti invece di un get_or_create per CVE."""
    from django.db import IntegrityError

    esistenti = set(SecurityCveRecord.objects.values_list("cve_id", flat=True))
    mancanti = [SecurityCveRecord(cve_id=c) for c in cve_ids if c not in esistenti]
    if not mancanti:
        return 0
    try:
        # SQL Server (mssql-django) non supporta ignore_conflicts: si creano solo quelle mancanti
        SecurityCveRecord.objects.bulk_create(mancanti, batch_size=BLOCCO)
    except IntegrityError:
        # un altro giro le ha create nel frattempo: si torna una per una
        for record in mancanti:
            SecurityCveRecord.objects.get_or_create(cve_id=record.cve_id)
    return len(mancanti)


def queue_recompute():
    """Ricalcolo degli impatti in un task django-q separato (ha il suo timeout)."""
    from django.core.cache import cache

    from security.services.cve_impact import LOCK_TTL, QUEUED_KEY

    # Un ricalcolo già in coda e non ancora partito copre anche questa richiesta.
    if not cache.add(QUEUED_KEY, 1, LOCK_TTL):
        return "già accodato"
    try:
        from django_q.tasks import async_task

        async_task("security.services.cve_impact.recompute_all", timeout=110)
        return "accodato"
    except Exception as exc:  # noqa: BLE001 - la coda non disponibile non annulla l'arricchimento
        cache.delete(QUEUED_KEY)
        logger.exception("Ricalcolo impatti CVE non accodato")
        return f"non accodato: {exc}"[:200]


def get_epss_enabled():
    from security.services import soc_settings

    return soc_settings.value("cve.epss.attivo")


def enrichment_enabled():
    from security.services import soc_settings

    return soc_settings.value("cve.arricchimento.attivo")
