# `core` — fondamenta del portale

Area **Core** · URL — (`/capa/`) · codice [`django_app/core/`](../../django_app/core/)

[← Catalogo moduli nel README](../../README.md#-catalogo-moduli)

## Sintesi

Middleware ACL, navigation registry, auth backends, audit, notifiche, export, ricerca globale, legacy models, **azioni CAPA** correttive/preventive trasversali

## Dettaglio

### Limiti di upload (`core/upload_limits.py`)

Un solo limite per file vale per tutti gli upload di documenti e allegati: assets, anagrafica, anomalie e NC, tickets, tasks, DPI, SDS, diario preposto, RENTRI, fornitori, notizie, sistema di gestione e bacheca. Lo stesso limite vale per l'import dell'archivio HR.

| Variabile `.env` | Default | Effetto |
|---|---|---|
| `UPLOAD_MAX_FILE_MB` | 100 | Dimensione massima del singolo file; i testi «max N MB» nelle pagine la leggono da `upload_max_mb` (context processor `app_meta`). |
| `DATA_UPLOAD_MAX_NUMBER_FILES` | 1000 | File per singolo invio (caricamento di una cartella intera). |

Il tetto sull'intera richiesta lo applica IIS: `maxAllowedContentLength` nel `web.config` (template: 104857600 = 100 MB). Va tenuto >= `UPLOAD_MAX_FILE_MB`, altrimenti IIS risponde 404.13 prima di Django. Il `web.config` di produzione non viene ridistribuito con il pacchetto: va aggiornato a mano sul server.

Restano fuori, con i limiti dedicati: loghi e immagini di branding, foto/planimetrie, import Excel/CSV/JSON, upload anonimi dalla landing QR pubblica (15 MB) e caselle SOC.

L'app trasversale che fa funzionare tutto il resto. Contiene middleware, resolver ACL, legacy models, auth backends, audit trail e context processors.

- **ACL middleware** con resolver canonico v2 + fallback legacy, logging throttled delle decisioni
- **Navigation registry** (`NavigationItem`, `NavigationRoleAccess`, `UserNavigationOverride`) con visibilita derivata dai permission code canonici e fallback legacy solo per voci ancora non mappate
- **Sidebar a 3° livello (sotto-moduli)**: un modulo della sidebar (es. Anagrafica) si espande in accordion mostrando i propri sotto-moduli. Le voci figlie sono `NavigationItem section='subnav'` con `parent_code` = `code` del modulo topbar, con ACL ereditata dalla stessa compilazione delle subnav; gestibili dal NavBuilder (section subnav + modulo padre). Il click sul nome naviga alla home del modulo, la freccia espande; lo stato attivo si propaga al padre
- **Fallback navigazione legacy** con deduplica visuale per modulo, cosi i restore/import non duplicano in sidebar le azioni `pulsanti` dello stesso modulo
- **Restore navigazione controllato** con `restore_navigation_registry`: dry-run di default, backup snapshot in apply e ripristino solo di categorie/menu/fallback ruoli da `fixtures/nav_acl_snapshot.json`
- **4 auth backend in cascata**: `AxesStandaloneBackend` → `SQLServerLegacyBackend` → `LDAPBackend` → `ModelBackend`
- **Header delle superfici pubbliche** (`core.public_headers`): le rotte fuori dal perimetro autenticato (`MIDDLEWARE_EXEMPT_PREFIXES`) si decorano con `@risposta_pubblica`, che aggiunge `X-Robots-Tag: noindex, nofollow, noarchive`, `Referrer-Policy: no-referrer`, `X-Content-Type-Options: nosniff` e `Cache-Control: no-store`. Sulle tre rotte **a token** (approvazioni automazioni, proxy Entra, azioni via mail sulle anomalie) `no-referrer` evita che il token nell'URL viaggi nell'header `Referer`
- **Audit trail** fire-and-forget via `core.audit.log_action()` su tabella `AuditLog`, con **aggancio opzionale al record** (`oggetto=<istanza>`, oppure `oggetto_tipo`/`oggetto_id` per le tabelle legacy senza modello Django): `core.audit.storico_oggetto()` ne ricava lo **storico modifiche del singolo record**, reso dal partial `core/components/_storico_modifiche.html`. Agganciarlo a una scheda costa due righe (kwarg nella `log_action` + include nel template); già attivo sulle scadenze amministrative degli asset, visibile in fondo a `/assets/<id>/`
- **Centro notifiche** unificato con campanella, badge, pannello HTMX, popup live in-app via polling leggero e sorgenti scadenze asset/DPI/SLA ticket
- **CAPA — Azioni Correttive/Preventive** (`/capa/`): modello trasversale `ActionItem` collegato a un evento di origine (incidente/anomalia/audit, schema `source_code`+`source_pk`), workflow **APERTA → IN_CORSO → CHIUSA (con evidenza) → VERIFICATA** con chiusura ed efficacia separate (quattro occhi). Lista filtrabile + export CSV/XLSX, gating fail-closed (gestore `core.capa_manage` vs responsabile assegnato), pannello "Azioni collegate" embeddabile nei detail (già nel dettaglio incidente), alimenta lo Scadenzario Globale e il Centro notifiche; sorgente automazioni `core_actionitem` con trigger SQL
- **Export riusabile CSV/XLSX** con `core.exporting.ExportMixin` e helper per liste filtrate
- **Legacy models managed** su SQL Server: `Ruolo`, `UtenteLegacy`, `AnagraficaDipendente`, `Pulsante`, `Permesso`
- **Impersonation** admin → utente con middleware dedicato e session key
- **23 modelli Django** (Profile, AuditLog, SiteConfig, Notifica, Checklist*, OptioneConfig, ecc.)
- **Ricerca unificata** Ctrl+K (o barra «Cerca o vai a…» in topnav): pagine recenti, salto a qualsiasi pagina di navigazione (ACL-filtrata) e ricerca dati su 7 sorgenti (dipendenti, asset, ticket, progetti, task, procedure, DPI), con modulo e preview risultato
- **Topnav**: voci in eccesso raccolte in «Altro», hamburger da ≤1100px, menu utente (profilo, preferenze, tema chiaro/scuro, segnala problema, esci), approvazioni assenze in attesa come «N da approvare». Struttura: Per me · Tickets · Produzione · Persone · Sicurezza e ambiente · Qualità · IT · Suggestion Corner, con sottocategorie da `NavigationItem.group`; si applica con `python manage.py riorganizza_topbar --apply` (dry-run senza `--apply`)

## Hardening ottobre 2026

- Helper di sicurezza: `core.net.client_ip` (IP client, `X-Forwarded-For` solo da `TRUSTED_PROXY_IPS`), `core.redirects.safe_next` (redirect di ritorno validati sull'host), filtro template `js_json` (`{% load safe_json %}`, dati negli `<script>` senza XSS), `core.private_attachments.PrivateAttachmentStorage` (allegati privati cifrati con lettura dei file storici). In produzione `LEGACY_AUTH_ENABLED=0` blocca l'avvio senza `ACL_DISABLE_ACKNOWLEDGED=1`; DRF ha default espliciti (sessione + utente autenticato).
