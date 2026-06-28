import logging.handlers  # noqa: F401 — registra il handler per LOGGING dict
import os
import socket
import tempfile
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from config.app_version import (
    DEFAULT_APP_VERSION,
    MODULE_ENV_KEYS_BY_CODE,
    load_app_version,
)
from config.env_config import iter_runtime_env_paths, load_dotenv_into_environ

# mssql-django 1.6 non riconosce ancora SQL Server major version 17.
# Trattiamo v17 come compatibile con il profilo 2022 per evitare blocchi in startup.
try:
    from mssql.base import DatabaseWrapper as MSSQLDatabaseWrapper

    MSSQLDatabaseWrapper._sql_server_versions.setdefault(17, 2022)
except Exception:
    pass


PROJECT_DIR = Path(__file__).resolve().parents[2]
BASE_DIR = PROJECT_DIR


def env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def env_bool(key: str, default: bool = False) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_list(key: str, default: list[str] | None = None) -> list[str]:
    raw = os.getenv(key)
    if raw is None:
        return list(default or [])
    return [item.strip() for item in raw.split(",") if item.strip()]


def default_dev_allowed_hosts() -> list[str]:
    hosts = {"127.0.0.1", "::1", "localhost", "testserver"}

    for candidate in {socket.gethostname(), socket.getfqdn()}:
        candidate = (candidate or "").strip()
        if candidate:
            hosts.add(candidate)

    try:
        for _family, _socktype, _proto, _canonname, sockaddr in socket.getaddrinfo(
            socket.gethostname(),
            None,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        ):
            host = str(sockaddr[0]).strip()
            if host:
                hosts.add(host)
    except OSError:
        pass

    return sorted(hosts)


for _dotenv_path in iter_runtime_env_paths(PROJECT_DIR):
    load_dotenv_into_environ(_dotenv_path)


SECRET_KEY = env("DJANGO_SECRET_KEY", "change-me-in-dev")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", ["127.0.0.1", "localhost"])
APP_VERSION = env("APP_VERSION", load_app_version(DEFAULT_APP_VERSION))
SETUP_WIZARD_REQUIRED = env_bool("SETUP_WIZARD_REQUIRED", True)

# ── Branding istanza ──────────────────────────────────────────────────────────
# INSTANCE_NAME: nome visualizzato nell'interfaccia (es. "NOVICROM HUB").
# Puoi personalizzarlo per singola installazione senza cambiare il brand documentale.
INSTANCE_NAME = env("INSTANCE_NAME", "NOVICROM HUB")
BRANDING_LOGO = env("BRANDING_LOGO", "")    # percorso relativo a STATICFILES (es. core/img/branding_logo.png)
BRANDING_FAVICON = env("BRANDING_FAVICON", "")  # percorso relativo a STATICFILES


def build_module_versions(default_version: str) -> dict[str, str]:
    versions: dict[str, str] = {}
    for code, env_key in MODULE_ENV_KEYS_BY_CODE.items():
        versions[code] = env(env_key, default_version).strip() or default_version
    return versions


MODULE_VERSIONS = build_module_versions(APP_VERSION)
LEGACY_AUTH_ENABLED = env_bool("LEGACY_AUTH_ENABLED", True)
NAVIGATION_REGISTRY_ENABLED = env_bool("NAVIGATION_REGISTRY_ENABLED", True)
NAVIGATION_LEGACY_FALLBACK_ENABLED = env_bool("NAVIGATION_LEGACY_FALLBACK_ENABLED", False)
# Layer di presentazione per il branding moduli.
# Precedenza runtime:
# 1. SiteConfig: module_branding.<module_key>.<field>
# 2. settings.MODULE_BRANDING
# 3. default dichiarati nel module registry
# Esempio:
# MODULE_BRANDING = {
#     "assets": {
#         "display_label": "Novicrom Assets",
#         "menu_label": "Novicrom Assets",
#     }
# }
MODULE_BRANDING = {}
LDAP_ENABLED = env_bool("LDAP_ENABLED", False)
LDAP_SERVER = env("LDAP_SERVER", "")
LDAP_DOMAIN = env("LDAP_DOMAIN", "")
LDAP_UPN_SUFFIX = env("LDAP_UPN_SUFFIX", "")
LDAP_TIMEOUT = int(env("LDAP_TIMEOUT", "5") or "5")
LDAP_SERVICE_USER = env("LDAP_SERVICE_USER", "")
LDAP_SERVICE_PASSWORD = env("LDAP_SERVICE_PASSWORD", "")
LDAP_BASE_DN = env("LDAP_BASE_DN", "")
LDAP_USER_FILTER = env("LDAP_USER_FILTER", "(&(objectCategory=person)(objectClass=user))")
LDAP_GROUP_ALLOWLIST = env_list("LDAP_GROUP_ALLOWLIST", [])
LDAP_SYNC_PAGE_SIZE = int(env("LDAP_SYNC_PAGE_SIZE", "500") or "500")
WINDOWS_SSO_HOSTNAME = env("WINDOWS_SSO_HOSTNAME", "").strip()
WINDOWS_SSO_SERVICE = env("WINDOWS_SSO_SERVICE", "HTTP").strip() or "HTTP"
EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", "")
EMAIL_PORT = int(env("EMAIL_PORT", "587") or "587")
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_USE_SSL = env_bool("EMAIL_USE_SSL", False)
EMAIL_TIMEOUT = int(env("EMAIL_TIMEOUT", "10") or "10")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "")
SITE_URL = env("SITE_URL", "")
SESSION_IDLE_TIMEOUT_SECONDS = int(env("SESSION_IDLE_TIMEOUT_SECONDS", "3600") or "3600")
SESSION_EXPIRE_AT_BROWSER_CLOSE = env_bool("SESSION_EXPIRE_AT_BROWSER_CLOSE", True)
LEGACY_ACL_CACHE_TTL = int(env("LEGACY_ACL_CACHE_TTL", "120") or "120")
LEGACY_NAV_CACHE_TTL = int(env("LEGACY_NAV_CACHE_TTL", "120") or "120")
# ACL v2 — governance migrazione legacy → canonico.
# ACL_STRICT_CANONICAL=True nega l'accesso quando il resolver cadrebbe nel
# fallback legacy (no RoutePermissionBinding per il path). Abilitare in
# staging/UAT per scovare le route ancora non coperte da binding canonico
# prima di attivarlo in prod. Default False per compat durante la migrazione.
ACL_STRICT_CANONICAL = env_bool("ACL_STRICT_CANONICAL", False)
# ACL_LOG_LEGACY_FALLBACK=True emette un warning throttled (5m) per ogni
# route che risolve via fallback legacy, anche quando l'accesso è consentito.
# Permette di misurare l'uso effettivo del fallback e decidere quando
# attivare ACL_STRICT_CANONICAL in prod. Default True in ambiente test/UAT.
ACL_LOG_LEGACY_FALLBACK = env_bool("ACL_LOG_LEGACY_FALLBACK", True)
# ACL_LEGACY_PERMESSI_UI_ENABLED=True riabilita la vecchia pagina di gestione
# permessi legacy (/admin-portale/permessi/). Default False: la pagina
# reindirizza a /admin-portale/acl-canonico/ (schermata unica di gestione,
# Fase 3 dismissione legacy). Il corpo legacy resta nel codice come rete di
# sicurezza finche' la migrazione canonica non e' definitivamente chiusa.
ACL_LEGACY_PERMESSI_UI_ENABLED = env_bool("ACL_LEGACY_PERMESSI_UI_ENABLED", False)
ASSENZE_SP_PULL_INTERVAL_SECONDS = int(env("ASSENZE_SP_PULL_INTERVAL_SECONDS", "300") or "300")
ASSENZE_SYNC_ON_PAGE_LOAD = env_bool("ASSENZE_SYNC_ON_PAGE_LOAD", True)
ASSENZE_CALENDAR_MAX_EVENTS = int(env("ASSENZE_CALENDAR_MAX_EVENTS", "1500") or "1500")
ANOMALIE_SP_FOLDER_URL = env("ANOMALIE_SP_FOLDER_URL", "#")
# Reparto (DipendenteAnagraficaAziendale.area) i cui dipendenti sono, di fatto,
# i capicommessa del modulo anomalie. L'appartenenza al reparto conferisce
# automaticamente il ruolo. Configurabile per non vincolare al codice "IN1".
ANOMALIE_CAPOCOMMESSA_REPARTO = env("ANOMALIE_CAPOCOMMESSA_REPARTO", "IN1").strip()
SQL_LOG_ENABLED = env_bool("SQL_LOG_ENABLED", False)
SQL_LOG_LEVEL = env("SQL_LOG_LEVEL", "DEBUG").strip().upper() or "DEBUG"
SQL_LOG_FORCE_DEBUG_CURSOR = env_bool("SQL_LOG_FORCE_DEBUG_CURSOR", SQL_LOG_ENABLED)
SQL_LOG_MAX_BYTES = int(env("SQL_LOG_MAX_BYTES", str(10 * 1024 * 1024)) or str(10 * 1024 * 1024))
SQL_LOG_BACKUP_COUNT = int(env("SQL_LOG_BACKUP_COUNT", "10") or "10")
AUTOMAZIONI_TRIGGER_DB_APPLY_ENABLED = env_bool("AUTOMAZIONI_TRIGGER_DB_APPLY_ENABLED", False)
MONITORING_ENABLED = env_bool("MONITORING_ENABLED", True)
MONITORING_CAPTURE_403 = env_bool("MONITORING_CAPTURE_403", True)
MONITORING_CAPTURE_404 = env_bool("MONITORING_CAPTURE_404", False)
MONITORING_SLOW_REQUEST_THRESHOLD_MS = int(env("MONITORING_SLOW_REQUEST_THRESHOLD_MS", "3000") or "3000")
MONITORING_NOTIFY_CRITICAL_BY_EMAIL = env_bool("MONITORING_NOTIFY_CRITICAL_BY_EMAIL", True)
MONITORING_ENVIRONMENT = env(
    "MONITORING_ENVIRONMENT",
    env("DJANGO_ENV", "development" if DEBUG else "production"),
).strip()
MONITORING_ADMIN_EMAILS = env_list("MONITORING_ADMIN_EMAILS", [])
MONITORING_EMAIL_RATE_LIMIT_SECONDS = int(env("MONITORING_EMAIL_RATE_LIMIT_SECONDS", "1800") or "1800")
MONITORING_WATCHDOG_CRITICAL_UNASSIGNED_MINUTES = int(
    env("MONITORING_WATCHDOG_CRITICAL_UNASSIGNED_MINUTES", "120") or "120"
)
# Health-check AI (Ollama/TEI) nel monitoring schedulato (monitoring_ai_alert).
# NON nel hot path di /readyz: fanno chiamate di rete al box GPU. Timeout corto.
MONITORING_AI_CHECKS_ENABLED = env_bool("MONITORING_AI_CHECKS_ENABLED", True)
MONITORING_AI_CHECK_TIMEOUT = float(env("MONITORING_AI_CHECK_TIMEOUT", "4") or "4")
# ── Content-Security-Policy ───────────────────────────────────────────────────
# Applicata da core.middleware.ContentSecurityPolicyMiddleware a tutte le
# risposte. La allowlist riflette l'inventario reale dei template:
#   - cdn.jsdelivr.net      → FullCalendar, frappe-gantt, Chart.js, SortableJS
#   - cdnjs.cloudflare.com  → html2canvas (rule designer)
#   - fonts.googleapis.com / fonts.gstatic.com → font Outfit (base.html, print)
# 'unsafe-inline' su script/style e' richiesto dagli script e dagli stili
# inline dei template SSR (niente nonce per ora). Niente 'unsafe-eval':
# nessun template usa hx-on/hx-vals js:.
# CSP_REPORT_ONLY=1 emette Content-Security-Policy-Report-Only (solo log
# browser, nessun blocco): usarlo al primo rollout in prod per osservare.
CSP_ENABLED = env_bool("CSP_ENABLED", True)
CSP_REPORT_ONLY = env_bool("CSP_REPORT_ONLY", False)
CSP_POLICY = env(
    "CSP_POLICY",
    "; ".join(
        [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com",
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net",
            "font-src 'self' data: https://fonts.gstatic.com",
            "img-src 'self' data: blob:",
            "connect-src 'self'",
            "frame-src 'self'",
            "frame-ancestors 'self'",
            "form-action 'self'",
            "base-uri 'self'",
            "object-src 'none'",
        ]
    ),
)

# Liveness/readiness endpoints (monitoring/health.py).
# HEALTHZ_ALLOWED_IPS: client IP autorizzati a chiamare /healthz e /readyz.
# Default: solo loopback. Aggiungere l'IP del proxy IIS / load balancer.
HEALTHZ_ALLOWED_IPS = env_list("HEALTHZ_ALLOWED_IPS", ["127.0.0.1", "::1"])
# Memoizzazione del risultato /readyz per evitare DoS sulle integrazioni.
# Mettere 0 per disabilitare la cache (test, debugging).
READYZ_TTL_SECONDS = int(env("READYZ_TTL_SECONDS", "10") or "10")
# Sottoinsieme di check da eseguire (CSV). Vuoto/non impostato => tutti.
# Nomi disponibili: db_default, db_legacy, cache, graph_token, ldap, smtp,
# automation_queue.
READYZ_CHECKS_ENABLED = env_list("READYZ_CHECKS_ENABLED", [])

# Assistente AI locale via Ollama. La chiamata parte dal server Django verso
# l'endpoint Ollama, mai dal browser dell'utente.
OLLAMA_CHAT_ENABLED = env_bool("OLLAMA_CHAT_ENABLED", True)
# Widget "brief giornaliero personale" (generato dall'AI sui dati live ACL-filtrati,
# on-demand con cache per-utente/giorno). Richiede OLLAMA_CHAT_ENABLED.
OLLAMA_DAILY_BRIEF_ENABLED = env_bool("OLLAMA_DAILY_BRIEF_ENABLED", True)
# Timeout dedicato (piu' corto) per il brief giornaliero: non e' critico e non
# deve occupare un worker per l'intero OLLAMA_REQUEST_TIMEOUT_SECONDS; degrada a fallback.
OLLAMA_DAILY_BRIEF_TIMEOUT_SECONDS = int(env("OLLAMA_DAILY_BRIEF_TIMEOUT_SECONDS", "45") or "45")
# Timeout per la generazione di un report PDF (api/report/): piu' lungo del brief
# perche' l'output e' un documento strutturato, ma comunque limitato.
OLLAMA_REPORT_TIMEOUT_SECONDS = int(env("OLLAMA_REPORT_TIMEOUT_SECONDS", "120") or "120")
OLLAMA_API_PROVIDER = env("OLLAMA_API_PROVIDER", "ollama").strip().lower()
OLLAMA_BASE_URL = env("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_CHAT_MODEL = env("OLLAMA_CHAT_MODEL", "qwen2.5:14b-instruct")
OPENWEBUI_API_KEY = env("OPENWEBUI_API_KEY", "")
OLLAMA_REQUEST_TIMEOUT_SECONDS = int(env("OLLAMA_REQUEST_TIMEOUT_SECONDS", "180") or "180")
OLLAMA_CHAT_TEMPERATURE = env("OLLAMA_CHAT_TEMPERATURE", "0.3")
OLLAMA_CHAT_MAX_PROMPT_CHARS = int(env("OLLAMA_CHAT_MAX_PROMPT_CHARS", "2000") or "2000")
OLLAMA_CHAT_MAX_HISTORY_MESSAGES = int(env("OLLAMA_CHAT_MAX_HISTORY_MESSAGES", "6") or "6")
OLLAMA_RAG_ENABLED = env_bool("OLLAMA_RAG_ENABLED", True)
# Sorgenti RAG su file: README + KB curata in django_app/ai_assistant/knowledge,
# che viaggia nel pacchetto (a differenza di docs/, escluso dal deploy) ed e' la
# fonte RAG su file in prod. docs/ai NON e' tra i default: contiene istruzioni
# per gli agenti AI (in inglese) e architettura, non aiuto per l'utente finale, ed
# essendo assente dal pacchetto in dev "soffocherebbe" la KB curata nel ranking
# BM25 (misurato con `manage.py ai_eval --rag`). Cosi' dev e prod si comportano
# uguale. Per reindicizzare docs/ai (es. assistente interno admin) basta impostare
# esplicitamente OLLAMA_RAG_SOURCE_PATHS nell'.env.
OLLAMA_RAG_SOURCE_PATHS = env_list(
    "OLLAMA_RAG_SOURCE_PATHS",
    ["README.md", "django_app/ai_assistant/knowledge"],
)
OLLAMA_RAG_MAX_CHUNKS = int(env("OLLAMA_RAG_MAX_CHUNKS", "6") or "6")
OLLAMA_RAG_MAX_CONTEXT_CHARS = int(env("OLLAMA_RAG_MAX_CONTEXT_CHARS", "7000") or "7000")
OLLAMA_RAG_CACHE_SECONDS = int(env("OLLAMA_RAG_CACHE_SECONDS", "300") or "300")
OLLAMA_RAG_CHUNK_CHARS = int(env("OLLAMA_RAG_CHUNK_CHARS", "900") or "900")
OLLAMA_RAG_MAX_FILES = int(env("OLLAMA_RAG_MAX_FILES", "80") or "80")
OLLAMA_RAG_MAX_FILE_CHARS = int(env("OLLAMA_RAG_MAX_FILE_CHARS", "300000") or "300000")
OLLAMA_RAG_MAX_DB_ENTRIES = int(env("OLLAMA_RAG_MAX_DB_ENTRIES", "200") or "200")
# Parametri Okapi BM25 per il retrieval RAG (k1: saturazione TF, b: normalizzazione lunghezza).
OLLAMA_RAG_BM25_K1 = float(env("OLLAMA_RAG_BM25_K1", "1.5") or "1.5")
OLLAMA_RAG_BM25_B = float(env("OLLAMA_RAG_BM25_B", "0.75") or "0.75")
# Overlap (caratteri) tra chunk consecutivi della stessa sezione: preserva il
# contesto a cavallo del confine. 0 = nessun overlap.
OLLAMA_RAG_CHUNK_OVERLAP_CHARS = int(env("OLLAMA_RAG_CHUNK_OVERLAP_CHARS", "150") or "150")
# Corpus documentale SGI nel RAG: indicizza le Specifiche in vigore (stato S3) e
# le revisioni procedura correnti, rendendole citabili in chat (handle spec:/proc:).
# OPT-OUT con OLLAMA_RAG_SGI_ENABLED=False. Cap dedicati perche' il corpus SGI
# supera i 200 di OLLAMA_RAG_MAX_DB_ENTRIES. Il testo PDF estratto e' cachato per
# file_hash (TTL dedicato). Il chunking riusa OLLAMA_RAG_CHUNK_CHARS/_OVERLAP_CHARS.
OLLAMA_RAG_SGI_ENABLED = env_bool("OLLAMA_RAG_SGI_ENABLED", True)
OLLAMA_RAG_SGI_MAX_SPECS = int(env("OLLAMA_RAG_SGI_MAX_SPECS", "300") or "300")
OLLAMA_RAG_SGI_MAX_PROCS = int(env("OLLAMA_RAG_SGI_MAX_PROCS", "300") or "300")
OLLAMA_RAG_SGI_MAX_PDF_CHARS = int(env("OLLAMA_RAG_SGI_MAX_PDF_CHARS", "200000") or "200000")
OLLAMA_RAG_SGI_TEXT_CACHE_TTL = int(env("OLLAMA_RAG_SGI_TEXT_CACHE_TTL", "2592000") or "2592000")
# Soglia minima di recall del RAG SGI sotto la quale l'alert qualità giornaliero
# (ai_assistant.tasks.run_rag_quality_alert) avvisa gli admin. 0 = solo sgi_chunks=0.
OLLAMA_RAG_SGI_MIN_RECALL = float(env("OLLAMA_RAG_SGI_MIN_RECALL", "0.7") or "0.7")
# Stemming italiano opt-in per il RAG (Snowball via snowballstemmer, pure-python).
# OFF di default: misurare il recall con `ai_eval --rag`/`--rag-sgi` prima di attivarlo
# in .env. Applicato identico a query e chunk; fail-safe se la dipendenza manca.
OLLAMA_RAG_STEMMING_ENABLED = env_bool("OLLAMA_RAG_STEMMING_ENABLED", False)
# Root (UNC) della share documentale SGI per `manage.py import_sgi_da_share`, che
# registra i PDF come documenti procedura citabili dall'AI. Vuoto = obbligatorio
# passare --root. Esclude sempre la sottocartella SUPERATO (revisioni obsolete).
PROCEDURE_REFRESH_SGI_SHARE_ROOT = env("PROCEDURE_REFRESH_SGI_SHARE_ROOT", "")
# Retrieval semantico (embeddings via Ollama nativo). OPT-IN: richiede un modello
# di embedding scaricato in Ollama (es. `ollama pull nomic-embed-text`). Fail-safe:
# se non disponibile il retrieval resta BM25-only. Solo provider "ollama".
OLLAMA_EMBED_ENABLED = env_bool("OLLAMA_EMBED_ENABLED", False)
OLLAMA_EMBED_MODEL = env("OLLAMA_EMBED_MODEL", "nomic-embed-text")
OLLAMA_EMBED_TIMEOUT_SECONDS = int(env("OLLAMA_EMBED_TIMEOUT_SECONDS", "30") or "30")
OLLAMA_EMBED_BATCH = int(env("OLLAMA_EMBED_BATCH", "16") or "16")
# Robustezza embedding su corpora grandi: retry per batch (timeout transitori) e
# micro-pausa tra batch per non saturare Ollama (utile se il server GPU e' condiviso
# o ha poca VRAM). Per warm pesanti alza la pausa (es. 150) e tieni OLLAMA_NUM_PARALLEL=1
# sul server. La cache per batch fa convergere i run successivi.
OLLAMA_EMBED_RETRY = int(env("OLLAMA_EMBED_RETRY", "2") or "2")
OLLAMA_EMBED_BATCH_PAUSE_MS = int(env("OLLAMA_EMBED_BATCH_PAUSE_MS", "0") or "0")
# Backend di calcolo embeddings: "ollama" (default), "fastembed" (in-process, CPU,
# ONNX: nessun server da saturare — robusto per il warm di corpora grandi) oppure
# "openai" (endpoint HTTP OpenAI-compatibile: TEI/Infinity/vLLM/LM Studio sulla GPU).
# Richiede comunque OLLAMA_EMBED_ENABLED=1. fastembed e' una dipendenza opzionale
# (import lazy, fail-safe -> BM25 se assente).
# NB GPU: con backend "openai"/TEI gli embeddings NON girano in Ollama -> sul server
# Ollama va impostato OLLAMA_MAX_LOADED_MODELS=1 (solo il modello chat) per liberare
# VRAM. Dettagli in docs/ai/OLLAMA_GPU_TUNING.md.
RAG_EMBED_BACKEND = env("RAG_EMBED_BACKEND", "ollama")
RAG_EMBED_FASTEMBED_MODEL = env("RAG_EMBED_FASTEMBED_MODEL", "BAAI/bge-m3")
RAG_EMBED_OPENAI_BASE_URL = env("RAG_EMBED_OPENAI_BASE_URL", "")
RAG_EMBED_OPENAI_MODEL = env("RAG_EMBED_OPENAI_MODEL", "")
RAG_EMBED_OPENAI_API_KEY = env("RAG_EMBED_OPENAI_API_KEY", "")
OLLAMA_EMBED_PERSIST = env_bool("OLLAMA_EMBED_PERSIST", True)
OLLAMA_EMBED_CACHE_TTL = int(env("OLLAMA_EMBED_CACHE_TTL", "2592000") or "2592000")
# Fusione ibrida BM25 + semantica (Reciprocal Rank Fusion): k attenua i ranghi bassi.
OLLAMA_RAG_HYBRID_RRF_K = int(env("OLLAMA_RAG_HYBRID_RRF_K", "60") or "60")
# Routing semantico dei tool runtime: attiva i domini pertinenti per similarita'
# embedding (additivo alle keyword). Soglia/margine calibrati su nomic-embed-text;
# con un altro modello di embedding vanno ritarati. Richiede OLLAMA_EMBED_ENABLED.
AI_TOOL_ROUTING_ENABLED = env_bool("AI_TOOL_ROUTING_ENABLED", True)
AI_TOOL_ROUTING_THRESHOLD = float(env("AI_TOOL_ROUTING_THRESHOLD", "0.70") or "0.70")
AI_TOOL_ROUTING_MARGIN = float(env("AI_TOOL_ROUTING_MARGIN", "0.04") or "0.04")
AI_TOOL_ROUTING_TOP_K = int(env("AI_TOOL_ROUTING_TOP_K", "2") or "2")
# Timeout BREVE (s) per l'embedding della query nel routing: il routing gira a
# OGNI messaggio, quindi se l'endpoint embeddings e' lento/giu' deve degradare in
# fretta a keyword-only invece di sommare il timeout pieno (OLLAMA_EMBED_TIMEOUT_SECONDS)
# alla latenza della chat. Override per i soli chiamanti latency-sensitive.
AI_TOOL_ROUTING_EMBED_TIMEOUT_SECONDS = int(env("AI_TOOL_ROUTING_EMBED_TIMEOUT_SECONDS", "6") or "6")
# Tetto del contesto live iniettato nel modello: meno caratteri = prefill piu'
# rapido (riduce la latenza/timeout sulle domande che attivano molti tool).
AI_RUNTIME_CONTEXT_MAX_CHARS = int(env("AI_RUNTIME_CONTEXT_MAX_CHARS", "12000") or "12000")
AI_RUNTIME_CONTEXT_MAX_LINES = int(env("AI_RUNTIME_CONTEXT_MAX_LINES", "160") or "160")
# Tuning runtime del modello chat (solo Ollama nativo). keep_alive tiene il modello
# in memoria (primo token piu' veloce); num_ctx dimensiona la finestra di contesto
# perche' contesto live + RAG non vengano troncati in silenzio; num_predict cappa la
# generazione: 0 = nessun cap dal portale (Ollama usa il suo default). Cap esplicito
# 1536 -> evita risposte runaway che tengono il worker per tutto il timeout e allocano
# KV-cache, restando ampio per risposte discorsive. Per le env SERVER-SIDE della GPU
# (flash attention, KV-cache q8_0, max_loaded_models=1) vedi docs/ai/OLLAMA_GPU_TUNING.md.
OLLAMA_KEEP_ALIVE = env("OLLAMA_KEEP_ALIVE", "30m")
OLLAMA_NUM_CTX = int(env("OLLAMA_NUM_CTX", "16384") or "16384")
OLLAMA_NUM_PREDICT = int(env("OLLAMA_NUM_PREDICT", "1536") or "1536")
# Throttle per-utente delle richieste alla chat AI (protegge l'istanza Ollama e i
# thread Waitress). 0 = disabilitato. Finestra fissa in secondi.
OLLAMA_CHAT_RATE_LIMIT = int(env("OLLAMA_CHAT_RATE_LIMIT", "20") or "20")
OLLAMA_CHAT_RATE_WINDOW_SECONDS = int(env("OLLAMA_CHAT_RATE_WINDOW_SECONDS", "60") or "60")
OLLAMA_CHAT_MAX_SYSTEM_PROMPT_CHARS = int(env("OLLAMA_CHAT_MAX_SYSTEM_PROMPT_CHARS", "1800") or "1800")
OLLAMA_CHAT_SYSTEM_PROMPT = env(
    "OLLAMA_CHAT_SYSTEM_PROMPT",
    (
        # Stile: chiaro e discorsivo (no telegrafico), ma sempre ancorato al contesto.
        "Sei l'assistente interno di NOVICROM HUB. Rispondi in italiano in modo chiaro e discorsivo: "
        "spiega bene il contenuto, contestualizza e, quando aiuta, aggiungi un breve esempio pratico o i "
        "passi concreti. Evita risposte telegrafiche ma resta pertinente. "
        # Gerarchia fonti — prima regola, non troncabile
        "PRIORITA' FONTI (obbligatoria): "
        "1) CONTESTO LIVE: se presente, e' la fonte principale. Rispondi usando quei dati, "
        "cita tool:* e ignora i documenti interni sulla stessa domanda. "
        "2) DOCUMENTI INTERNI (SGI e KB): usali per spiegare procedure, regole e funzionamento del portale. "
        "3) Conoscenza generale: mai per inventare dati aziendali. "
        # Anti-invenzione
        "REGOLA ASSOLUTA: non inventare file, percorsi, URL, procedure, comandi, codici, numeri o sezioni "
        "assenti dal contesto. Se non hai il dato, dillo senza aggiungere fantasia. "
        "Se l'utente chiede dati operativi (registrazioni, movimenti, elenchi) e non e' presente "
        "un CONTESTO LIVE, rispondi che non hai accesso diretto a quei dati e invita ad aprire il modulo nel "
        "portale; non descrivere il funzionamento come se stessi leggendo i dati reali. "
        # Citazione documenti SGI
        "Quando spieghi a partire da un documento SGI cita sempre codice, revisione e sezione "
        "(es. «MT CN 04 Rev.0 §5.1»). "
        # Dati sensibili
        "Non ripetere password, token o credenziali. Per dati sanitari, disciplinari o riservati "
        "invita a usare il modulo dedicato. "
        # Qualita risposta
        "Se non sei certo, dichiaralo. Non aprire URL esterni."
    ),
)


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "axes",
    "setup_wizard.apps.SetupWizardConfig",
    "hub_tools.apps.HubToolsConfig",
    "core.apps.CoreConfig",
    "dashboard.apps.DashboardConfig",
    "ai_assistant.apps.AiAssistantConfig",
    "assenze.apps.AssenzeConfig",
    "anomalie.apps.AnomalieConfig",
    "assets.apps.AssetsConfig",
    "attrezzature.apps.AttrezzatureConfig",
    "gestione_carichi_macchina.apps.GestioneCarichiMacchinaConfig",
    "gestione_specifiche.apps.GestioneSpecificheConfig",
    "tasks.apps.TasksConfig",
    "automazioni.apps.AutomazioniConfig",
    "monitoring.apps.MonitoringConfig",
    "admin_portale.apps.AdminPortaleConfig",
    "notizie.apps.NotizieConfig",
    "anagrafica.apps.AnagraficaConfig",
    "fornitori.apps.FornitoriConfig",
    "timbri.apps.TimbriConfig",
    "planimetria.apps.PlanimetriaConfig",
    "tickets.apps.TicketsConfig",
    "rentri.apps.RentriConfig",
    "diario_preposto.apps.DiarioPrepostoConfig",
    "rilevazione_incidenti.apps.RilevazioneIncidentiConfig",
    "dpi.apps.DpiConfig",
    "procedure_refresh.apps.ProcedureRefreshConfig",
    "django_extensions",
    "django_q",
    "django_htmx",
    "twofa.apps.TwoFaConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "core.middleware.ContentSecurityPolicyMiddleware",
    "core.middleware.AdaptiveSecureCookieMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "core.csrf_cookie_middleware.EnsureCSRFCookieMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.audit_middleware.AuditRequestMiddleware",
    "axes.middleware.AxesMiddleware",
    "core.middleware.ImpersonationMiddleware",
    "monitoring.middleware.IssueCaptureMiddleware",
    "core.session_middleware.SessionIdleTimeoutMiddleware",
    "setup_wizard.middleware.SetupRequiredMiddleware",   # ← prima di ACL/notizie
    "twofa.middleware.TwoFactorMiddleware",
    "core.middleware.ACLMiddleware",
    "notizie.mandatory_middleware.NotizieMandatoryMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.legacy_nav",
                "core.context_processors.app_meta",
                "core.context_processors.ui_prefs_context",
                "monitoring.context_processors.monitoring_ui",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


def build_sqlite_database() -> dict:
    return {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }


def build_sqlserver_database() -> dict:
    driver = env("DB_DRIVER", "ODBC Driver 18 for SQL Server")
    db_user = env("DB_USER", "")
    db_password = env("DB_PASSWORD", "")
    # TrustServerCertificate: default True solo in dev (DB_TRUST_CERT=1).
    # In produzione lasciare non impostato o DB_TRUST_CERT=0 per verificare il certificato SSL.
    trust_cert = env_bool("DB_TRUST_CERT", False)
    extra_params = f"TrustServerCertificate={'yes' if trust_cert else 'no'};"
    db_encrypt = env("DB_ENCRYPT", "").strip()
    if db_encrypt:
        extra_params += f"Encrypt={'yes' if env_bool('DB_ENCRYPT', True) else 'no'};"
    if not db_user:
        extra_params += "Trusted_Connection=yes;"

    return {
        "ENGINE": "mssql",
        "NAME": env("DB_NAME", ""),
        "HOST": env("DB_HOST", ""),
        "USER": db_user,
        "PASSWORD": db_password,
        "OPTIONS": {
            "driver": driver,
            "extra_params": extra_params,
        },
    }


def build_database_from_env(default_engine: str = "sqlite") -> dict:
    engine = env("DB_ENGINE", default_engine).strip().lower()
    if engine in ("sqlserver", "mssql"):
        return build_sqlserver_database()
    return build_sqlite_database()


DATABASES = {"default": build_database_from_env("sqlite")}


AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


LANGUAGE_CODE = "it-it"
TIME_ZONE = env("TIME_ZONE", "Europe/Rome")
USE_I18N = True
USE_TZ = True

# Formati data/ora italiani normalizzati: date pure "d-m-Y", datetime "d-m-Y H:i".
# I formati custom vivono in config/formats/it/formats.py e sovrascrivono i
# default Django per template ({{ x|date }} senza argomenti) e form.
FORMAT_MODULE_PATH = ["config.formats"]

STATIC_URL = "/static/"
STATIC_ROOT = Path(env("STATIC_ROOT", str(BASE_DIR / "staticfiles")))

MEDIA_ROOT = Path(env("MEDIA_ROOT", str(BASE_DIR / "media")))
MEDIA_URL = "/media/"
DEV_SERVE_STATIC_AND_MEDIA = False

# ── Backup automatico ────────────────────────────────────────────────────────
# BACKUP_DIR: directory radice dove vengono salvati i backup automatici.
# In produzione il wizard imposta: C:\PortaleNovicrom\shared\backups\<env>
# In dev il default è accanto a django_app/ → ../backups
BACKUP_DIR = Path(env("BACKUP_DIR", str(BASE_DIR.parent / "backups")))
# BACKUP_RETENTION: quanti backup mantenere (i più vecchi vengono eliminati)
BACKUP_RETENTION = int(env("BACKUP_RETENTION", "10") or "10")

# Immagini timbri/firme: cartella privata, MAI servita dal web server.
# Il web server (IIS/nginx) non deve avere accesso a questa directory.
TIMBRI_PRIVATE_ROOT = Path(env("TIMBRI_PRIVATE_ROOT", str(BASE_DIR / "media_private")))
# Allegati ticket: storage privato con fallback compatibile sui file legacy in MEDIA_ROOT.
TICKETS_PRIVATE_ROOT = Path(env("TICKETS_PRIVATE_ROOT", str(BASE_DIR / "media_private")))
# Allegati asset sensibili: storage privato con fallback compatibile sui file legacy in MEDIA_ROOT.
ASSETS_PRIVATE_ROOT = Path(env("ASSETS_PRIVATE_ROOT", str(BASE_DIR / "media_private")))
SHAREPOINT_ASSET_PUBLIC_LINKS_ENABLED = env_bool("SHAREPOINT_ASSET_PUBLIC_LINKS_ENABLED", False)
SHAREPOINT_ASSET_ALLOWED_ROOT_NAME = env("SHAREPOINT_ASSET_ALLOWED_ROOT_NAME", "ASSET CN")
SHAREPOINT_ASSET_ALLOWED_ROOT_DRIVE_ID = env("SHAREPOINT_ASSET_ALLOWED_ROOT_DRIVE_ID", "")
SHAREPOINT_ASSET_ALLOWED_ROOT_ITEM_ID = env("SHAREPOINT_ASSET_ALLOWED_ROOT_ITEM_ID", "")
SHAREPOINT_ASSET_SITE_ID = env("SHAREPOINT_ASSET_SITE_ID", "")
SHAREPOINT_ASSET_DRIVE_ID = env("SHAREPOINT_ASSET_DRIVE_ID", "")
# Allegati Diario Preposto (segnalazioni di sicurezza): storage privato con
# fallback compatibile sui file legacy in MEDIA_ROOT.
DIARIO_PREPOSTO_PRIVATE_ROOT = Path(env("DIARIO_PREPOSTO_PRIVATE_ROOT", str(BASE_DIR / "media_private")))
# Documenti dipendente (consegne DPI archiviate, referti visite mediche, contratti).
# Storage privato, mai esposto da IIS: accessibile solo via view protetta con ACL.
ANAGRAFICA_PRIVATE_ROOT = Path(env("ANAGRAFICA_PRIVATE_ROOT", str(BASE_DIR / "media_private")))
# Allegati specifiche tecniche (gestione_specifiche): storage privato cifrato,
# mai esposto da IIS; accessibile solo via view protetta con ACL.
GESTIONE_SPECIFICHE_PRIVATE_ROOT = Path(env("GESTIONE_SPECIFICHE_PRIVATE_ROOT", str(BASE_DIR / "media_private")))

# Configurazione di processo dell'app gestione_specifiche (BUILD_SPEC §5).
# APPROVAZIONE_DOC_CN_MODE ∈ {mod133_approver, car_flow, rdd_dedicato} (decisione F0 #2).
GESTIONE_SPECIFICHE = {
    "APPROVAZIONE_DOC_CN_MODE": env("GESTIONE_SPECIFICHE_APPROVAZIONE_DOC_CN_MODE", "car_flow"),
    "VERIFICA_PERIODICA_MESI": int(env("GESTIONE_SPECIFICHE_VERIFICA_PERIODICA_MESI", "6")),
    "REMINDER_GIORNI": int(env("GESTIONE_SPECIFICHE_REMINDER_GIORNI", "7")),
    "ESCALATION_GIORNI": int(env("GESTIONE_SPECIFICHE_ESCALATION_GIORNI", "14")),
}

# Chiave AES-256 Fernet per cifratura at rest dei file privati.
# Generare con: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Se vuota: nessuna cifratura (sviluppo). In produzione DEVE essere impostata.
DOCUMENT_ENCRYPTION_KEY = env("DOCUMENT_ENCRYPTION_KEY", "")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

Q_CLUSTER = {
    "name": "novicrom_hub",
    "workers": 2,
    "timeout": 120,
    "retry": 180,
    "save_limit": 250,
    "max_attempts": 3,
    "orm": "default",
}

CSRF_FAILURE_VIEW = "core.views.csrf_failure"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard_hub_preview"
LOGOUT_REDIRECT_URL = "login"
SESSION_COOKIE_AGE = max(300, SESSION_IDLE_TIMEOUT_SECONDS) if SESSION_IDLE_TIMEOUT_SECONDS > 0 else 1209600

# IP dei reverse proxy fidati. Solo se REMOTE_ADDR è in questo set, X-Forwarded-For viene accettato.
# Esempio: TRUSTED_PROXY_IPS = {"127.0.0.1", "192.0.2.10"}
TRUSTED_PROXY_IPS: set[str] = set(env_list("TRUSTED_PROXY_IPS", []))

# Prefissi URL esenti da autenticazione e timeout di sessione (usati da entrambi i middleware).
MIDDLEWARE_EXEMPT_PREFIXES = (
    "/health",
    "/healthz",
    "/readyz",
    "/version",
    "/check",
    "/login",
    "/logout",
    "/cambia-password",
    "/static/",
    "/media/",
    "/admin/",
    "/favicon",
    "/setup/",
    "/admin-portale/hub/",
    "/assets/public/",
    "/monitoring/report-problem/",
    "/admin-portale/automazioni/approvazione/",
    "/automazioni/approvazione/",  # token-based, no login required
    "/approval-actions/",          # token-based, Entra Application Proxy frontend
    "/2fa/",                       # 2FA verify/setup — gestiti internamente
    "/gestione-anomalie/mail-action/",  # token-based, no login required
)

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "core.accounts.backends.SQLServerLegacyBackend",
    "core.accounts.backends.LDAPBackend",
    "django.contrib.auth.backends.ModelBackend",
]

AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_TEMPLATE = "core/pages/lockout.html"
# Silenzia il messaggio INFO "AXES: BEGIN version ..." emesso a ogni boot/reload;
# non incide sulla protezione anti-brute-force né sui log di lockout/tentativi falliti.
AXES_VERBOSE = False


_default_log_dir = Path(tempfile.gettempdir()) / "briziohub_logs"
_configured_log_dir = os.environ.get("DJANGO_LOG_DIR")
_env_name = env("DJANGO_ENV", "").strip().lower()
_settings_module = env("DJANGO_SETTINGS_MODULE", "").strip().lower()
if not _configured_log_dir and (_env_name in {"prod", "production"} or _settings_module.endswith(".prod")):
    raise ImproperlyConfigured(
        "DJANGO_LOG_DIR deve essere configurato in produzione: il fallback su temp di sistema non e' consentito."
    )
LOG_DIR = Path(_configured_log_dir or str(_default_log_dir))
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        },
        "file": {
            "class": "core.logging_handlers.SafeTimedRotatingFileHandler",
            "filename": str(LOG_DIR / "app.log"),
            "formatter": "standard",
            "encoding": "utf-8",
            "when": "midnight",
            "backupCount": 5,
        },
        "sql_file": {
            "class": "core.logging_handlers.SafeTimedRotatingFileHandler",
            "filename": str(LOG_DIR / "sql.log"),
            "formatter": "standard",
            "encoding": "utf-8",
            "when": "midnight",
            "backupCount": SQL_LOG_BACKUP_COUNT,
        },
    },
    "loggers": {
        "django.db.backends": {
            "handlers": ["sql_file"],
            "level": SQL_LOG_LEVEL if SQL_LOG_ENABLED else "WARNING",
            "propagate": False,
        },
    },
    "root": {
        "handlers": ["console", "file"],
        "level": "INFO",
    },
}
