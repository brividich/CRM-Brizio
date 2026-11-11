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


def _termini_correzione_cve():
    """Termini di correzione (ISO 27001 8.8): accettazioni scadute o in scadenza, esposizioni oltre il termine, soppressioni in scadenza.

    Gira prima della valutazione delle regole dopo l'heartbeat, così gli eventi diventano alert nello stesso giro.
    """
    from security.services import accettazione_rischio, cve_sla, soppressioni_scadenza

    accettazioni = accettazione_rischio.controlla_scadenze()
    eventi, chiusi = cve_sla.segnala_scadute()
    soppressioni = soppressioni_scadenza.controlla_scadenze()
    return {**accettazioni, "oltre_termine": eventi, "rientrati": chiusi, "soppressioni_in_scadenza": soppressioni}


def _termini_patch():
    """Patch WatchGuard oltre il termine di installazione (``patch_sla``): eventi nuovi e alert rientrati."""
    from security.services import patch_sla

    eventi, chiusi = patch_sla.segnala_scadute()
    return {"oltre_termine": eventi, "rientrati": chiusi}


def _iso_incidenti():
    """ISO 27001 5.28: sigilla (SHA-256) i contenitori di evidenze ancora senza impronta."""
    from security.services.iso_incidenti import ciclo

    return ciclo()


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
    from security.services import letture

    return letture.esegui("cve")


def ai_sintesi_giorno_task():
    """Sintesi del giorno della Panoramica preparata in anticipo (schedule `security_ai_sintesi`).

    Una richiesta all'AI solo se i punti «da guardare» sono cambiati; spegnibile da /soc/impostazioni/.
    """
    from ai_assistant.http_client import scadenza
    from security.services import soc_settings
    from security.services.ai_explain import prepare_daily_brief
    from security.services.cpe_ai import TETTO_PIANIFICATO

    if not soc_settings.value("ai.sintesi.attivo"):
        return {"skipped": "sintesi automatica spenta"}
    # Timeout della richiesta = min(SECURITY_AI_TIMEOUT_SECONDS, tempo che resta): entro i 120 s del worker.
    with scadenza(TETTO_PIANIFICATO):
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


def ai_cpe_proposte_task():
    """Proposte dell'AI locale su CPE ed esiti «da verificare» (schedule `security_ai_cpe`, lettura `cpe_ai`).

    Solo proposte da accettare o rifiutare, mai decisioni. Spenta finché non si accende in
    /soc/impostazioni/; al massimo «Massimo per giro» casi, nessuna richiesta se Ollama non risponde.
    """
    from security.services import letture

    return letture.esegui("cpe_ai")


def ai_proposte_task():
    """Proposte di chiusura dell'AI sugli alert aperti (schedule `security_ai_proposte`, lettura `ai_proposte`).

    Ogni 15 minuti: prove dai report successivi + decisioni passate → proposta; i tipi di alert che l'AI ha
    imparato dalle conferme si chiudono da soli. Al massimo «Massimo per giro» alert, nessuna richiesta dopo 60 s.
    """
    from security.services import letture

    return letture.esegui("ai_proposte")


def pacchetto_iso_task():
    """Pacchetto mensile di evidenze ISO/IEC 27001 (schedule `security_pacchetto_iso`, lettura `pacchetto_iso`).

    Il giorno 1 alle 06:30 genera il PDF del mese prima (esito dei controlli, CVE corrette, esposizioni
    scadute, incidenti), lo archivia con l'impronta SHA-256 nell'audit e, se acceso, lo copia su SharePoint.
    """
    from security.services import letture

    return letture.esegui("pacchetto_iso")


def dipendenze_portale_task():
    """Librerie Python del portale contro il database OSV (schedule `security_dipendenze_portale`, lettura `dipendenze_portale`).

    Ogni mattina alle 06:50: vulnerabilità nuove e risolte in Dispositivi › Librerie del portale, alert per libreria.
    """
    from security.services import letture

    return letture.esegui("dipendenze_portale")


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


# Tempo del giro oltre il quale le letture esterne del ciclo passano al giro dopo: i passi
# interni (regole, battito, KPI, notifiche) girano comunque, entro i 120 s del worker.
CICLO_BUDGET_LETTURE_SECONDI = 50
LETTURE_DEL_CICLO = ("defender", "entra", "veeam", "secure_score")


def run_security_caselle_task():
    """Lettura delle caselle mail dei report (schedule `security_caselle`, ogni 15 minuti).

    Sta in un lavoro suo, con un timeout più lungo, perché è il passo più pesante: con un
    arretrato di mail non deve più far fermare il ciclo prima di regole, battito e KPI.
    Ogni mail importata passa già da parser e regole.
    """
    from security.services import letture

    return letture.esegui("caselle")


def run_security_cycle_task():
    """Ciclo periodico del Security Center (schedule `security_cycle`, ogni 15 minuti).

    1. letture esterne (Defender, Entra, Veeam, Secure Score), saltate al giro dopo se il
       giro ha già usato ``CICLO_BUDGET_LETTURE_SECONDI``;
    2. recupera eventuali elementi rimasti in coda e valuta le regole;
    3. controlla le sorgenti silenziose (heartbeat) e le rivaluta;
    4. aggiorna gli snapshot KPI di oggi, rientri e notifiche.
    Le caselle mail hanno il loro lavoro (``run_security_caselle_task``).
    Ogni passo è isolato: un errore (es. credenziali Graph) non ferma gli altri.
    """
    import logging

    from security.services.kpi_service import build_daily_kpi_snapshots
    from security.services.parser_engine import run_pending_parsers
    from security.services.rule_engine import evaluate_security_rules
    from security.services.source_heartbeat import evaluate_source_heartbeat

    logger = logging.getLogger(__name__)
    result = {}
    from security.services import letture

    steps = (
        # Le letture passano dal registro (Impostazioni › Letture automatiche): storico ed «Esegui ora».
        ("defender", lambda: letture.esegui("defender_alert", rilancia=True)),
        ("entra", lambda: letture.esegui("entra", rilancia=True)),
        ("veeam", lambda: letture.esegui("veeam", rilancia=True)),
        ("secure_score", lambda: letture.esegui("secure_score", rilancia=True)),
        ("parsers", run_pending_parsers),
        ("rules", evaluate_security_rules),
        ("heartbeat", lambda: len(evaluate_source_heartbeat())),
        ("termini_cve", _termini_correzione_cve),
        ("termini_patch", _termini_patch),
        ("rules_after_heartbeat", evaluate_security_rules),
        ("kpis", build_daily_kpi_snapshots),
        ("rientri", _periodic_recoveries),
        ("pulizia_inventario", _cleanup_inventory_previews),
        ("iso", _iso_incidenti),
        ("avvisi", _scheduled_notifications),
    )
    import time

    inizio = time.monotonic()
    for name, step in steps:
        if name in LETTURE_DEL_CICLO and time.monotonic() - inizio > CICLO_BUDGET_LETTURE_SECONDI:
            result[name] = "rimandata al prossimo giro (tempo del giro esaurito)"
            logger.warning("security_cycle: lettura %s rimandata, giro oltre %s s", name, CICLO_BUDGET_LETTURE_SECONDI)
            continue
        try:
            result[name] = step()
        except Exception as exc:  # noqa: BLE001 - un passo fallito non blocca il ciclo
            logger.exception("security_cycle: passo %s fallito", name)
            result[name] = f"errore: {exc}"[:300]
    return result


def run_defender_software_task() -> dict:
    """Software dei PC da Microsoft Defender for Endpoint (``services.defender_software``)."""
    from security.services import letture

    return letture.esegui("defender_software")


def run_watchguard_api_task() -> dict:
    """PC, software e patch da WatchGuard Cloud (``services.watchguard_api``), con i loro interruttori."""
    from security.services import letture

    return letture.esegui("watchguard")


def run_defender_vulnerabilita_task() -> dict:
    """CVE viste da Defender per il confronto nel pannello CVE (``services.defender_vuln``)."""
    from security.services import letture

    return letture.esegui("defender_vuln")
