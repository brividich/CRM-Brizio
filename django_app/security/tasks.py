"""Task in background del modulo security.

Nell'HUB NOVICROM questi task girano tramite **django-q2** (non Celery, non usato
dal portale). Sono funzioni pure, senza dipendenze da broker/decoratori: si
accodano con `django_q.tasks.async_task("security.tasks.run_security_parsers_task")`
oppure si pianificano con un `django_q.models.Schedule`. La stessa logica è anche
disponibile via management command (`run_security_parsers`, `evaluate_security_rules`).
"""


def run_security_parsers_task():
    """Esegue i parser sui messaggi/file in attesa. Ritorna il numero di report elaborati."""
    from security.services.parser_engine import run_pending_parsers

    return run_pending_parsers()


def evaluate_security_rules_task():
    """Valuta le regole di alert sugli eventi ingeriti. Ritorna il numero di regole valutate."""
    from security.services.rule_engine import evaluate_security_rules

    return evaluate_security_rules()


def ingest_security_mailboxes_task():
    """Ingestione delle sorgenti mailbox Graph/IMAP abilitate (per django-q2/Schedule).

    Ritorna il numero di sorgenti processate senza errore. Le credenziali vanno
    configurate come SecurityCenterSetting (Configuration Studio).
    """
    import logging

    from security.models import SecurityMailboxSource
    from security.services.mailbox_ingestion import run_mailbox_ingestion

    ok = 0
    for src in SecurityMailboxSource.objects.filter(enabled=True).exclude(source_type="manual"):
        try:
            run_mailbox_ingestion(src)
            ok += 1
        except Exception:  # noqa: BLE001 - una casella guasta non ferma le altre, ma si vede nel log
            logging.getLogger(__name__).exception("Lettura della casella %s fallita", src.code)
            continue
    return ok



def _scheduled_notifications():
    """Avvisi programmati (scadenze incidenti, backup, report): accesi da /soc/impostazioni/."""
    from security.services.proactive_alerts import run_scheduled_notifications

    return run_scheduled_notifications()


def _periodic_recoveries():
    """Regole di rientro periodiche (VPN nei limiti, CVE con patch): spente finché non simulate e accese."""
    from security.services.auto_resolution import run_periodic_recoveries

    return run_periodic_recoveries()


def _cleanup_inventory_previews():
    """File di inventario caricati e mai importati: eliminati dopo 2 giorni."""
    from security.services.software_inventory import cleanup_stale_previews

    return cleanup_stale_previews(days=2)


def enrich_cve_task():
    """Arricchimento CVE (schedule `security_cve_enrichment`, ogni ora): NVD, CISA KEV, EPSS, impatti.

    Fuori dalla request e senza transazione esterna: le chiamate di rete hanno timeout, retry
    con backoff e rate limit; il giro si ferma entro 90 s (timeout worker 120 s) e riprende
    al successivo. Spento finché non si accende «Impatto CVE sugli asset» in /soc/impostazioni/.
    """
    from security.services.cve_feeds import enrichment_enabled, run_enrichment

    if not enrichment_enabled():
        return {"skipped": "arricchimento CVE spento"}
    return run_enrichment(time_budget_seconds=90)


def ai_sintesi_giorno_task():
    """Sintesi del giorno della Panoramica preparata in anticipo (schedule `security_ai_sintesi`).

    Una richiesta all'AI solo se i punti «da guardare» sono cambiati; spegnibile da /soc/impostazioni/.
    """
    from security.services import soc_settings
    from security.services.ai_explain import prepare_daily_brief

    if not soc_settings.value("ai.sintesi.attivo"):
        return {"skipped": "sintesi automatica spenta"}
    return prepare_daily_brief()


def ai_lettura_assistita_task():
    """Lettura assistita dall'AI (schedule `security_ai_lettura`, flusso del designer Automazioni).

    Fa leggere all'AI locale le letture «da verificare» e le mail che nessun parser riconosce:
    proposte da controllare, mai alert. Spenta finché non si accende in /soc/impostazioni/;
    al massimo «Massimo per giro» elementi, nessuna nuova richiesta dopo 60 s (timeout worker 120 s).
    """
    from security.services import soc_settings
    from security.services.ai_lettura import leggi_candidati, notifica_letture_ai

    if not soc_settings.value("ai.lettura.attivo"):
        return {"skipped": "lettura assistita spenta"}
    done = leggi_candidati(limit=soc_settings.value("ai.lettura.max_per_giro"))
    notified = notifica_letture_ai(done) if done else 0
    return {
        "lette": len(done),
        "proposte_ok": sum(1 for row in done if row["result"]["ok"]),
        "ms_medi": int(sum(row["result"]["ms"] for row in done) / len(done)) if done else 0,
        "avvisi_inviati": notified or 0,
    }


def suggest_cpe_task(vendor, product):
    """Suggerimenti CPE dal dizionario NVD per un prodotto dell'inventario (accodato dalla pagina Software)."""
    from security.models import SoftwareCpeMapping
    from security.services.cve_feeds import FeedError, nvd_limiter, suggest_cpe

    mapping, _ = SoftwareCpeMapping.objects.get_or_create(vendor=vendor or "", product=product)
    try:
        mapping.suggestions = suggest_cpe(vendor, product, limiter=nvd_limiter())
    except FeedError as exc:
        mapping.suggestions = [{"error": str(exc)[:200]}]
    mapping.save(update_fields=["suggestions", "updated_at"])
    return len(mapping.suggestions)


def run_security_cycle_task():
    """Ciclo periodico del Security Center (schedule `security_cycle`, ogni 15 minuti).

    Prima nessun task del modulo era pianificato: anche con una casella configurata,
    nessuno andava a leggere le mail e dashboard/alert restavano vuoti.
    1. legge le caselle attive (ogni mail importata passa già da parser e regole);
    2. recupera eventuali elementi rimasti in coda e valuta le regole;
    3. controlla le sorgenti silenziose (heartbeat) e le rivaluta;
    4. aggiorna gli snapshot KPI di oggi.
    Ogni passo è isolato: un errore (es. credenziali Graph) non ferma gli altri.
    """
    import logging

    from security.services.kpi_service import build_daily_kpi_snapshots
    from security.services.parser_engine import run_pending_parsers
    from security.services.rule_engine import evaluate_security_rules
    from security.services.source_heartbeat import evaluate_source_heartbeat

    logger = logging.getLogger(__name__)
    result = {}
    from security.services import defender_alerts, entra_signals, secure_score, veeam_api

    steps = (
        ("mailboxes", ingest_security_mailboxes_task),
        ("defender", defender_alerts.run),
        ("entra", entra_signals.run),
        ("veeam", veeam_api.run),
        ("secure_score", secure_score.aggiorna),
        ("parsers", run_pending_parsers),
        ("rules", evaluate_security_rules),
        ("heartbeat", lambda: len(evaluate_source_heartbeat())),
        ("rules_after_heartbeat", evaluate_security_rules),
        ("kpis", build_daily_kpi_snapshots),
        ("rientri", _periodic_recoveries),
        ("pulizia_inventario", _cleanup_inventory_previews),
        ("avvisi", _scheduled_notifications),
    )
    for name, step in steps:
        try:
            result[name] = step()
        except Exception as exc:  # noqa: BLE001 - un passo fallito non blocca il ciclo
            logger.exception("security_cycle: passo %s fallito", name)
            result[name] = f"errore: {exc}"[:300]
    return result


def run_defender_software_task() -> dict:
    """Software dei PC da Microsoft Defender for Endpoint (``services.defender_software``)."""
    from security.services import defender_software

    return defender_software.run()
