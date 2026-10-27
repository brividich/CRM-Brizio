"""Schema DB generato dai modelli Django: tabelle, campi, collegamenti e sistemi esterni.

Prima la pagina «Schema DB» era un HTML scritto a mano (fermo a maggio 2026, 182
modelli): ogni migrazione la rendeva vecchia. Qui lo schema si legge dal registro
delle app a ogni avvio del processo, quindi segue sempre il codice in esecuzione.

``CONNESSIONI_ESTERNE`` è invece scritto a mano: dice con quali sistemi fuori dal
database parla il portale, dove si configura (solo i NOMI delle chiavi del .env,
mai i valori) e cosa controllare quando non funziona. Se si aggiunge
un'integrazione, va aggiunta qui.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from functools import lru_cache

from django.apps import apps

# Area, colore e descrizione per ogni app del progetto, nell'ordine della pagina.
APP_INFO: dict[str, tuple[str, str, str]] = {
    "core": ("Piattaforma", "#2563eb", "Utenti legacy, profili, permessi (ACL), menu, notifiche, audit, configurazione, registro e layout dei report, postazioni condivise e PIN"),
    "admin_portale": ("Piattaforma", "#1d4ed8", "Pannello di amministrazione"),
    "dati_bi": ("Piattaforma", "#0369a1", "Dati per Power BI (viste SQL bi_*) e API dati in sola lettura per applicazioni"),
    "hub_tools": ("Piattaforma", "#3b82f6", "Strumenti hub: moduli, database, guide"),
    "dashboard": ("Piattaforma", "#60a5fa", "Home e cruscotti"),
    "monitoring": ("Piattaforma", "#fb923c", "Salute del portale, segnalazioni, schedule, esiti dei backup e prove di ripristino"),
    "setup_wizard": ("Piattaforma", "#94a3b8", "Configurazione iniziale"),
    "twofa": ("Piattaforma", "#64748b", "Verifica in due passaggi"),
    "ai_assistant": ("Piattaforma", "#8b5cf6", "Assistente AI: conversazioni, FAQ, feedback"),
    "anagrafica": ("Persone e HR", "#10b981", "Dipendenti, organigramma, struttura organizzativa e sue revisioni, formazione, visite, skill matrix con catalogo competenze e storico valutazioni, fornitori, richieste di rettifica (GDPR)"),
    "assenze": ("Persone e HR", "#0ea5e9", "Ferie, permessi, certificazioni presenza, sync SharePoint, "
                "saldi, calendario aziendale, contatori, copertura reparti, storico richieste, solleciti, "
                "permessi ripetuti (serie di richieste con una sola approvazione)"),
    "timbri": ("Persone e HR", "#64748b", "Registro timbri, firme e sigle"),
    "notizie": ("Persone e HR", "#fbbf24", "Comunicazioni e letture"),
    "fornitori": ("Operations", "#16a34a", "Fornitori (tabelle in anagrafica)"),
    "assets": ("Operations", "#f97316", "Asset, manutenzioni, ordini di lavoro, verifiche, software, indirizzi IP (DHCP/DNS), rack e switch di rete, macchine collegate (MTConnect)"),
    "attrezzature": ("Operations", "#14b8a6", "Attrezzature per P/N"),
    "tasks": ("Operations", "#06b6d4", "KICK-OFF: commesse, attività, incontri, VRF"),
    "tickets": ("Operations", "#ec4899", "Ticket IT e manutenzione"),
    "anomalie": ("Operations", "#eab308", "Anomalie per OP e seriali"),
    "gestione_carichi_macchina": ("Operations", "#0891b2", "Pianificazione carichi macchina"),
    "checklist_operativa": ("Operations", "#0d9488", "Checklist di chiusura aziendale"),
    "contatori": ("Operations", "#7c3aed", "Contatori IT: MFC e monitor SNMP"),
    "planimetria": ("Operations", "#a3a3a3", "Ponte verso le planimetrie di assets"),
    "diario_preposto": ("Sicurezza sul lavoro", "#ef4444", "Diario del preposto e ispezioni"),
    "rilevazione_incidenti": ("Sicurezza sul lavoro", "#f43f5e", "Incidenti, near miss, situazioni pericolose"),
    "dpi": ("Sicurezza sul lavoro", "#8b5cf6", "DPI: catalogo, richieste, consegne, magazzino"),
    "schede_sicurezza": ("Sicurezza sul lavoro", "#dc2626", "Schede di sicurezza dei prodotti chimici"),
    "rentri": ("Sicurezza sul lavoro", "#84cc16", "Registro rifiuti RENTRI"),
    "procedure_refresh": ("Qualità", "#22c55e", "Presa visione procedure, sync SGI"),
    "sistema_gestione": ("Qualità", "#15803d", "Audit interni ed esterni, certificazioni, SoA, threat intelligence"),
    "gestione_specifiche": ("Qualità", "#4d7c0f", "Specifiche cliente, MOD.133 e tabelle del Registro OFI / NC "
                            "(il modulo con dashboard e viste è registro_ofi)"),
    "suggestion_corner": ("Qualità", "#65a30d", "Segnalazioni di miglioramento PDCA"),
    "report_conformita": ("Qualità", "#a16207", "Report per audit (rettifiche)"),
    "glossario_tecnico": ("Qualità", "#ca8a04", "Glossario tecnico"),
    "security": ("Sicurezza informatica", "#b91c1c", "Security Center: alert, eventi, vulnerabilità, incidenti, backup; ISO 27001: riesame "
                 "degli incidenti e azioni correttive (security_securityincidentreview, security_securitycorrectiveaction), catena di custodia "
                 "delle evidenze (security_securityevidencecustody), prove di ripristino dei backup (security_backuprestoretest)"),
    "registro_log": ("Sicurezza informatica", "#991b1b", "Registro accessi: log dei server (indice), PC del dominio letti, sigilli giornalieri dell'archivio, "
                     "interruzioni, account AD, amministratori di sistema, verifiche annuali, stato ESXi/iLO. "
                     "Può stare in un database a parte (REGISTRO_LOG_DB_NAME)"),
    "automazioni": ("Automazioni", "#a78bfa", "Regole, coda eventi, approvazioni, run log"),
}
# App di Django e librerie: le loro tabelle esistono nel database, mostrate a parte.
FRAMEWORK_INFO: dict[str, str] = {
    "auth": "Utenti e gruppi Django",
    "admin": "Registro del Django admin",
    "contenttypes": "Tipi di contenuto (usato da permessi e relazioni generiche)",
    "sessions": "Sessioni di accesso",
    "axes": "Tentativi di accesso falliti e blocchi (django-axes)",
    "django_q": "Coda e pianificazione dei lavori in background (qcluster)",
}
AREE = ("Piattaforma", "Persone e HR", "Operations", "Sicurezza sul lavoro", "Qualità",
        "Sicurezza informatica", "Automazioni", "Altri moduli", "Framework e librerie")

CONNESSIONI_ESTERNE: list[dict] = [
    {
        "nome": "Collector letture contatori (OPC UA)",
        "cosa": "Script esterni (es. il collector OPC UA delle CNC) che inviano le ore/km/cicli delle macchine a POST /api/assets/contatori/ingest/. Le letture finiscono in assets_assetmeter e assets_assetmeterhistory e alimentano i piani di manutenzione a contatore.",
        "chi": "Asset → contatori e scadenze a contatore.",
        "config": "Token e IP ammessi per collector in Asset › Configurazione › Macchine collegate › Collector (assets_meteringestclient; anche admin Django o manage.py meter_ingest_client); in più ASSETS_METER_INGEST_ALLOWED_IPS del .env; ASSETS_METER_STALE_HOURS (ore oltre cui una lettura è vecchia). Solo rete interna, mai su Entra.",
        "controllo": "Admin «Collector letture contatori» → «ultimo contatto»; badge di freschezza sulla scheda asset e sulla pagina del QR.",
    },
    {
        "nome": "SQL Server",
        "cosa": "Il database del portale: tutte le tabelle di questa pagina, comprese le tabelle storiche (utenti, ruoli, permessi, pulsanti, assenze, anagrafica_dipendenti).",
        "chi": "Tutto il portale.",
        "config": "DB_HOST, DB_NAME, DB_USER, DB_PASSWORD, DB_DRIVER, DB_TRUST_CERT, DB_ENCRYPT, DB_QUERY_TIMEOUT",
        "controllo": "Servizio Windows MSSQL… avviato; errori «ODBC»/«10061» in logs\\app.log; Centrale di comando.",
    },
    {
        "nome": "Share dei backup (NAS)",
        "cosa": "Destinazione dei backup verificabili: set FULL/LOG/FILES/HOST con manifest, store dei file, zip della release. Il .env completo va in una share separata.",
        "chi": "Comandi hub_backup* lanciati dai task PortaleNovicrom-Backup-<ENV>-* (non dal qcluster).",
        "config": "BACKUP_TARGET, BACKUP_TARGET_SECONDARY, BACKUP_STAGING_DIR, BACKUP_ENV_DIR, BACKUP_LOG_WINDOW, BACKUP_KEEP_*, BACKUP_EXTRA_DATABASES",
        "controllo": "manage.py hub_backup_doctor; <BACKUP_TARGET>\\<env>\\status.json e logs\\backup-status.json; tabella monitoring_backuprun.",
    },
    {
        "nome": "Trigger SQL e coda eventi",
        "cosa": "Trigger sul database che scrivono gli eventi in automation_event_queue: da lì partono le regole delle Automazioni.",
        "chi": "Automazioni (assenze, ticket, anomalie e altre sorgenti).",
        "config": "Comando apply_sql_triggers; pagina Automazioni → Trigger generator",
        "controllo": "Coda delle automazioni: eventi «pending» che non scendono = qcluster fermo.",
    },
    {
        "nome": "django-q (qcluster)",
        "cosa": "Il servizio che esegue i lavori in background e quelli pianificati. Usa le tabelle django_q_* del database.",
        "chi": "Mail, promemoria, sincronizzazioni, letture SNMP, Security Center, indicizzazione AI.",
        "config": "Attività pianificata QCluster_PROD + watchdog; schedule registrati da setup_q_schedules",
        "controllo": "Monitoring → Centrale di comando e «Salute degli schedule»; logs\\qcluster.log.",
    },
    {
        "nome": "Active Directory (LDAP)",
        "cosa": "Login con utente e password del PC, import degli utenti, gruppi.",
        "chi": "Accesso al portale, Amministrazione → Utenti.",
        "config": "LDAP_SERVER, LDAP_DOMAIN, LDAP_BASE_DN, LDAP_SERVICE_USER, LDAP_SERVICE_PASSWORD (Setup Wizard → LDAP)",
        "controllo": "Amministrazione → LDAP (diagnostica): test di connessione.",
    },
    {
        "nome": "Microsoft Graph (Microsoft 365)",
        "cosa": "Un'app registrata su Entra ID per leggere e scrivere liste SharePoint, calendari Outlook e caselle di posta.",
        "chi": "Assenze (lista SharePoint), Rilevazione incidenti (lista SharePoint), KICK-OFF (calendario incontri), Security Center (caselle dei report, "
               "alert di Microsoft Defender con SecurityAlert.Read.All, incidenti con SecurityIncident.Read.All, Secure Score con "
               "SecurityEvents.Read.All, software dei PC dall'API di Defender for Endpoint con Software.Read.All, vulnerabilità per PC con Vulnerability.Read.All e Machine.Read.All (tabella security_defendervulnerabilita); Microsoft Entra ID: account degli ex dipendenti e audit "
               "amministrativo con User.Read.All e AuditLog.Read.All), Ruoli e permessi (scheda «Account Microsoft 365»), Centrale di comando (stato dei servizi Microsoft 365 con ServiceHealth.Read.All), Scadenzario (calendario Outlook «Scadenze "
               "NOVICROM HUB» delle persone che lo scelgono, Calendars.ReadWrite, tabella core_scadenzaoutlook), Licenze software (abbonamenti "
               "Microsoft 365 con Organization.Read.All e LicenseAssignment.Read.All), Asset IT (PC gestiti da Microsoft Intune con "
               "DeviceManagementManagedDevices.Read.All, tabella assets_dispositivointune), "
               "Automazioni (lettura risposte di approvazione), "
               "Audit sigillato (export mensile su SharePoint: SiteConfig audit_export_sp_drive_id / audit_export_sp_cartella).",
        "config": "GRAPH_TENANT_ID, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET e gli ID delle liste (Setup Wizard → Microsoft Graph / SharePoint)",
        "controllo": "Errori 401/403/invalid_client = segreto dell'app scaduto: rinnovarlo su Entra ID.",
    },
    {
        "nome": "Veeam Backup & Replication (REST API)",
        "cosa": "Sessioni di backup concluse con l'esito per macchina e spazio dei repository, lette ogni 15 minuti dal "
                "security_cycle (solo letture, in uscita verso il server Veeam sulla porta 9419). Finiscono in "
                "security_backupjobrecord ed eventi del SOC, come le mail di esito Veeam.",
        "chi": "SOC → Backup (riquadro «Lettura diretta da Veeam»), alert «Repository di backup quasi pieno».",
        "config": "SOC › Impostazioni › «Credenziali API Veeam» (indirizzo, utente con ruolo Veeam Backup Viewer, password e "
                  "certificato della CA cifrati in security_securitycentersetting) e interruttore «Leggi i backup dall'API di Veeam»; "
                  "le vecchie variabili VEEAM_API_* del .env valgono solo se nel portale non c'è niente.",
        "controllo": "manage.py veeam_api --prova; manage.py veeam_api (esito dell'ultimo giro); badge del riquadro nella pagina Backup.",
    },
    {
        "nome": "Registro accessi: log dei server e degli apparati",
        "cosa": "Il raccoglitore (manage.py registro_log, task RegistroLog_<ambiente>) legge il registro eventi dei server Windows "
                "con wevtutil (RPC, sola lettura), come BusinessLog anche di tutti i PC del dominio (elenco da AD, tabella "
                "Postazione), o gli eventi inoltrati (WEF), e riceve syslog in UDP/TCP 514 da ESXi, switch, "
                "firewall e NAS (solo dagli IP scritti nelle fonti). Tutto in un archivio di file giornalieri sigillati "
                "(cartella privata o scelta nelle impostazioni), copiati su una cartella di rete e/o SharePoint. Ogni 6 ore legge gli "
                "account di Active Directory via LDAP; ogni ora ESXi/vCenter (pyvmomi) e iLO/iDRAC (Redfish) in sola lettura.",
        "chi": "SOC → Registro accessi (eventi, amministratori di sistema, account AD, verifica annuale, archivio, server e "
               "virtualizzazione), alert del SOC «Registro accessi».",
        "config": "SOC › Registro accessi › «Fonti» (fonti, cartella, conservazione, seconda copia, porta syslog, orario di lavoro); "
                  "apparati ESXi/iLO con password cifrata in «Server e virtualizzazione». Account del raccoglitore nel gruppo "
                  "«Event Log Readers»; porta 514 aperta solo per gli apparati. Facoltativo REGISTRO_LOG_DB_NAME nel .env per il "
                  "database a parte.",
        "controllo": "manage.py registro_log --prova; controllo infrastruttura «registro_log» (Centrale di comando); pagina Panoramica "
                     "del Registro accessi.",
    },
    {
        "nome": "CNC: collector OPC UA e agent MTConnect",
        "cosa": "Stato delle macchine (in lavoro, MDI/manuale, interrotta, ferma, in allarme, emergenza, offline), programma, pezzi e "
                "allarmi. Le DMG MORI: il collector OPC UA dell'officina (django_app/assets/collector_cnc) li invia a POST "
                "/api/assets/contatori/ingest/stato/ e i contatori a /api/assets/contatori/ingest/. Le macchine con agent MTConnect: "
                "HTTP GET /current ogni 2 minuti. Finiscono in assets_collegamentomtconnect, assets_periodostatomacchina e nei "
                "contatori assets_assetmeter.",
        "chi": "Mappa officina (livello «Allarme sulla CNC» e riquadro «Dal controllo della macchina»), contatori Ore e Cicli dei piani di manutenzione.",
        "config": "Tutto in Configurazione → «Macchine collegate» (/assets/work-machines/mtconnect/). «Dove gira il collector»: sul server "
                  "del portale (manage.py collector_cnc, task CollectorCnc_<ENV> installato dal Setup Wizard, scrittura diretta nel DB, uscita "
                  "verso le macchine sulla porta OPC UA 4840, controllo collector_cnc) oppure su un PC dell'officina. Macchine del collector (indirizzo e "
                  "porta OPC UA, codice, credenziali OPC UA cifrate) scaricate dal collector con GET /api/assets/contatori/ingest/config/, "
                  "token e IP ammessi del collector; sul PC del collector solo PORTALE_URL e PORTALE_TOKEN. MTConnect: indirizzo dell'agent "
                  "nella stessa pagina, schedule mtconnect_poll (ogni 2 minuti). «Cerca le macchine in rete» (amministratori): il processo "
                  "web prova una rete interna al massimo /24 sulla porta OPC UA e legge solo l'array dei namespace (collector_cnc/cerca.py).",
        "controllo": "«Prova» e «Cerca le macchine in rete» nella pagina Macchine collegate; colonna Stato ed errori della stessa pagina; "
                     "report «Utilizzo delle CNC» nel catalogo report.",
    },
    {
        "nome": "DHCP e DNS di Windows Server",
        "cosa": "Ambiti DHCP con l'occupazione, lease e prenotazioni (IP, MAC, nome) e record A del DNS, letti ogni ora "
                "con PowerShell in locale (moduli RSAT DhcpServer/DnsServer, solo letture). Finiscono in assets_ambitodhcp "
                "e assets_indirizzorete; ogni MAC visto resta in assets_macrete (evento SOC «dispositivo sconosciuto nuovo in rete»).",
        "chi": "Asset → Indirizzi IP e SOC → Dispositivi → Rete (IP) (non censiti, senza antivirus, switch e porta, record DNS vecchi), "
               "riconciliazione dispositivi IT, riga «Visto da» della scheda asset, elenco e scheda Dispositivi del SOC.",
        "config": "Asset › Indirizzi IP, riquadro «Server DHCP e DNS» (amministratori del modulo Asset; SiteConfig "
                  "assets.rete_windows.config; le vecchie RETE_* del .env valgono solo se vuoto); RSAT sul server del portale; l'utente "
                  "del qcluster nel gruppo «DHCP Users» del server DHCP. Schedule rete_windows_sync (ogni 60 minuti).",
        "controllo": "manage.py rete_windows --prova; esito ed errori dell'ultima lettura in cima alla pagina Indirizzi IP.",
    },
    {
        "nome": "WatchGuard Cloud (API Endpoint Security)",
        "cosa": "Lettura dei PC con agente (protezione, ultima connessione, MAC), dei dispositivi in rete senza agente, del software installato e delle patch mancanti con l'esito dei task di installazione. Sola lettura.",
        "chi": "Security Center → Dispositivi › Patch e protezione, inventario software (fonte WatchGuard), pannello CVE, riga «Visto da» della scheda asset. Tabelle security_watchguarddispositivo, security_watchguardpatch.",
        "config": "SOC › Impostazioni › «Credenziali API WatchGuard» (URL API della regione, ID account, Access ID, password, API Key da Managed Access; cifrate nel database) e interruttori «WatchGuard Endpoint Security (API)».",
        "controllo": "«Prova la connessione» nelle Impostazioni o manage.py soc_api_sync --prova; esito del task watchguard_api_sync.",
    },
    {
        "nome": "Posta in uscita (SMTP)",
        "cosa": "Tutte le mail del portale.",
        "chi": "Notifiche, approvazioni, promemoria, minute degli incontri.",
        "config": "EMAIL_HOST, EMAIL_PORT, EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, DEFAULT_FROM_EMAIL (Setup Wizard → SMTP)",
        "controllo": "Mail di prova dall'Amministrazione; Log notifiche; run log automazioni.",
    },
    {
        "nome": "Power BI e applicazioni esterne (lettura dati)",
        "cosa": "Power BI legge le viste SQL bi_* con un utente SQL in sola lettura; Power BI (connettore Web), Power Automate "
                "o un gestionale leggono l'API /api/v1/ con un token per applicazione. Nessun dato personale nominativo.",
        "chi": "Direzione e reportistica (KPI manutenzione, scadenze, ticket, DPI, CAPA).",
        "config": "Viste: GRANT da manage.py bi_viste --grant <login>. API: manage.py dati_api_client crea …; "
                  "DATI_API_ALLOWED_IPS (IP o reti ammessi)",
        "controllo": "manage.py bi_viste (righe per vista); manage.py dati_api_client elenco (ultimo accesso); GET /api/v1/stato/.",
    },
    {
        "nome": "Servizi push dei browser (Web Push)",
        "cosa": "Il segnale «c'è una notifica nuova» verso telefoni e PC, attraverso il servizio del produttore del browser "
                "(Google, Mozilla, Microsoft, Apple). Parte solo il segnale, senza testo: il dispositivo legge la notifica dal portale.",
        "chi": "Notifiche del portale per chi ha attivato la push (Impostazioni notifiche); invii dal qcluster.",
        "config": "VAPID_PRIVATE_KEY, VAPID_SUBJECT (manage.py genera_chiavi_vapid); uscita https verso fcm.googleapis.com, "
                  "*.push.services.mozilla.com, *.notify.windows.com, *.push.apple.com",
        "controllo": "Impostazioni notifiche → «Invia una prova»; manage.py genera_chiavi_vapid --verifica.",
    },
    {
        "nome": "Entra Application Proxy",
        "cosa": "Pubblica su internet solo i collegamenti di approvazione (/approval-actions/), per approvare dal telefono fuori rete.",
        "chi": "Automazioni → approvazioni via mail.",
        "config": "SITE_URL; app aziendale «Approvazioni» su Entra ID",
        "controllo": "Un link di approvazione aperto da fuori rete deve mostrare la pagina di conferma.",
    },
    {
        "nome": "Cartella SGI (file server)",
        "cosa": "La cartella condivisa con le procedure del sistema di gestione.",
        "chi": "Presa visione procedure (sync notturna), Bacheca, Assistente AI (indice delle procedure).",
        "config": "Percorso della share nelle impostazioni del modulo procedure; l'utente del servizio deve poterla leggere",
        "controllo": "Presa visione procedure → «Log sync».",
    },
    {
        "nome": "Apparati di rete (SNMP)",
        "cosa": "Lettura di contatori e stato da stampanti MFC (anche avvisi, cassetti carta, sportelli e display, sola lettura Printer-MIB), switch, UPS, NVR e altri apparati.",
        "chi": "Contatori MFC e SNMP; asset collegati; Security Center (firmware e vulnerabilità).",
        "config": "Community o utenti SNMPv3 nel catalogo cifrato del modulo Contatori",
        "controllo": "Codici di errore SNMP-001…008 nella scheda dell'apparato.",
    },
    {
        "nome": "Server AI (Ollama e indice)",
        "cosa": "Il modello di linguaggio dell'Assistente AI e il servizio che calcola l'indice dei documenti, su un server interno.",
        "chi": "Assistente AI, copiloti dei moduli (DPI, Suggestion Corner, Specifiche, Security Center: spiegazioni, lettura assistita, "
               "proposte su CPE ed esiti CVE da verificare nella tabella security_securitypropostaai).",
        "config": "OLLAMA_BASE_URL, OLLAMA_CHAT_MODEL, RAG_EMBED_BACKEND, RAG_EMBED_OPENAI_BASE_URL",
        "controllo": "Setup Wizard → Server Dashboard → Assistente AI (verifica); Centrale di comando.",
    },
    {
        "nome": "Archivio file privato",
        "cosa": "Cartelle sul server con gli allegati riservati (cifrati), scaricabili solo dal portale dopo il login.",
        "chi": "Ticket, Notizie, Diario preposto, RENTRI, Suggestion Corner, Specifiche, Schede di sicurezza, Anagrafica.",
        "config": "PRIVATE_ATTACHMENTS_ROOT, DIARIO_PREPOSTO_PRIVATE_ROOT, DOCUMENT_ENCRYPTION_KEY (senza la chiave i file cifrati non si aprono più: va conservata)",
        "controllo": "«File non trovato» = cartella spostata o non leggibile dall'utente del sito IIS.",
    },
]


def _tipo(field) -> str:
    return field.get_internal_type() if hasattr(field, "get_internal_type") else type(field).__name__


def _campo(field) -> dict:
    nota = []
    relazione = ""
    destinazione = ""
    if field.is_relation and field.related_model is not None:
        destinazione = f"{field.related_model._meta.app_label}.{field.related_model.__name__}"
        relazione = "M:M" if field.many_to_many else ("1:1" if field.one_to_one else "FK")
    if getattr(field, "null", False):
        nota.append("null")
    if getattr(field, "unique", False) and not getattr(field, "primary_key", False):
        nota.append("unique")
    max_length = getattr(field, "max_length", None)
    if max_length and not field.is_relation:
        nota.append(f"max {max_length}")
    colonna = getattr(field, "column", None) or ""
    return {
        "nome": field.name,
        # La colonna si mostra solo quando non è quella ovvia (nome, o nome_id per le FK).
        "colonna": colonna if colonna and colonna not in (field.name, f"{field.name}_id") else "",
        "tipo": _tipo(field),
        "pk": bool(getattr(field, "primary_key", False)),
        "relazione": relazione,
        "destinazione": destinazione,
        "note": " · ".join(nota),
    }


@lru_cache(maxsize=1)
def schema() -> dict:
    progetto = []
    framework = []
    for config in apps.get_app_configs():
        label = config.label
        modelli = [m for m in config.get_models() if not m._meta.proxy and not m._meta.auto_created]
        if not modelli and label not in APP_INFO:
            continue
        if label in APP_INFO:
            area, colore, descrizione = APP_INFO[label]
        elif label in FRAMEWORK_INFO:
            area, colore, descrizione = "Framework e librerie", "#94a3b8", FRAMEWORK_INFO[label]
        else:
            # App nuova non ancora censita: compare comunque, da aggiungere ad APP_INFO.
            area, colore, descrizione = "Altri moduli", "#a8a29e", "Modulo non ancora descritto in hub_tools/schema_db.py"
        elenco = []
        for modello in sorted(modelli, key=lambda m: m.__name__.lower()):
            meta = modello._meta
            campi = [_campo(f) for f in meta.get_fields() if getattr(f, "concrete", False) or f.many_to_many and not f.auto_created]
            usata_da = sorted({
                f"{rel.related_model._meta.app_label}.{rel.related_model.__name__}"
                for rel in meta.related_objects
                if rel.related_model is not None and not rel.related_model._meta.auto_created
            })
            elenco.append({
                "nome": modello.__name__,
                "tabella": meta.db_table,
                "descrizione": str(meta.verbose_name_plural or ""),
                "gestita": meta.managed,
                "campi": campi,
                "usata_da": usata_da,
            })
        voce = {
            "label": label,
            "nome": str(config.verbose_name or label),
            "area": area,
            "colore": colore,
            "descrizione": descrizione,
            "modelli": elenco,
        }
        (framework if label in FRAMEWORK_INFO else progetto).append(voce)

    ordine = list(APP_INFO)
    progetto.sort(key=lambda a: ordine.index(a["label"]) if a["label"] in APP_INFO else len(ordine))
    app_tutte = progetto + framework

    # Collegamenti fra moduli: quante relazioni partono da un'app verso un'altra.
    tra_app: dict[str, Counter] = defaultdict(Counter)
    totali = Counter()
    for app in app_tutte:
        totali["modelli"] += len(app["modelli"])
        for modello in app["modelli"]:
            totali["campi"] += len(modello["campi"])
            for campo in modello["campi"]:
                if not campo["relazione"]:
                    continue
                totali[campo["relazione"]] += 1
                destinazione_app = campo["destinazione"].split(".", 1)[0]
                if destinazione_app != app["label"]:
                    tra_app[app["label"]][destinazione_app] += 1
    collegamenti = []
    for app in app_tutte:
        uscita = tra_app.get(app["label"], Counter())
        entrata = Counter({sorgente: c[app["label"]] for sorgente, c in tra_app.items() if c.get(app["label"])})
        app["verso"] = uscita.most_common()
        app["da"] = entrata.most_common()
        if uscita:
            collegamenti.append((app["label"], uscita.most_common()))

    gruppi = []
    for area in AREE:
        membri = [a for a in app_tutte if a["area"] == area]
        if membri:
            gruppi.append((area, membri))
    return {
        "app": app_tutte,
        "gruppi": gruppi,
        "collegamenti": collegamenti,
        "totali": {
            "app": len(app_tutte),
            "modelli": totali["modelli"],
            "campi": totali["campi"],
            "fk": totali["FK"],
            "uno_a_uno": totali["1:1"],
            "molti_a_molti": totali["M:M"],
        },
    }


def indice_ricerca() -> list[dict]:
    """Voci leggere per la ricerca in pagina: app, modello, tabella, nomi dei campi."""
    voci = []
    for app in schema()["app"]:
        for modello in app["modelli"]:
            voci.append({
                "a": app["label"],
                "m": modello["nome"],
                "t": modello["tabella"],
                "c": " ".join(c["nome"] for c in modello["campi"]),
            })
    return voci
