# Frontend Direction

SSR/HTMX, navigation, dashboard, and visual designer direction extracted from the previous root CLAUDE.md.

Important: Do not read all docs automatically. Open only the files relevant to the current task.

## Core Frontend Stack

- **Frontend:** SSR con Django templates, CSS custom, HTMX per partial update senza framework JS completo
- **HTMX:** `django-htmx>=1.17.0` â€” `HtmxMiddleware` aggiunge `request.htmx`; script servito via `{% django_htmx_script %}` in `base.html`; CSRF iniettato via listener `htmx:configRequest`. Moduli con partial views: `assenze` (calendario mese), `automazioni` (azioni designer), `dashboard` (widget lazy loading)
- **Layout shared:** `core/base.html` + `core/static/core/css/theme.css` fungono da shell viewport-aware; i root wrapper di modulo/dashboard devono riempire l'altezza disponibile ed evitare sidebar/grid con `align-self: start` o `align-items: start` se questo crea vuoti verticali visibili
- **Integrazioni:** Microsoft Graph/SharePoint/Outlook Calendar (MSAL), LDAP/AD, SMTP

## Navigation Rendering And Layout

### 3. Navigation Registry (visibilita menu, non sicurezza)

- File: `core/navigation_registry.py`
- Tabelle Django: `NavigationItem`, `NavigationRoleAccess`, `UserNavigationOverride`, `UserDashboardConfig`, `UserModuleVisibility`
- `NavigationItem` espone ora anche `required_permission_code`: se compilato, o se ricavabile da `route_name` / `url_path`, la visibilita della voce viene derivata dai grant canonici del ruolo/utente.
- Runtime attuale: `RolePermissionGrant` / `UserPermissionGrant` sono la fonte primaria di visibilita menu; `NavigationRoleAccess` sopravvive solo come fallback compat per voci ancora prive di permission code canonico.
- Quando il Navigation Registry e' vuoto/disattivato e la shell cade sul fallback legacy `pulsanti`, `core.context_processors.legacy_nav()` deve deduplicare la navigazione principale per modulo prima di renderizzare topbar/sidebar. Le tabelle legacy possono contenere piu azioni dello stesso modulo (`lista`, `crea`, `gestione`) ma il menu principale deve mostrare una sola voce modulo, specialmente dopo restore/import topbar.
- **Override per-utente navigazione** (`UserNavigationOverride`): in runtime e hide-only. `enabled=False` nasconde una voce gia consentita; i vecchi override positivi (`enabled=True`) non forzano piu la mostra di voci negate dal canonico. Non usa la cache; gli admin non sono soggetti agli override. Funziona su `topbar` e `subnav`. Gestito da "Step 5 Ã¢â‚¬â€œ Nav Override" in `/admin-portale/acl-canonico/` e da "Override Navigazione Utente" in `/admin-portale/navigation-builder/`.

#### Sezioni `NavigationItem.section`

| Valore | Dove viene renderizzata | ACL |
| --- | --- | --- |
| `topbar` | Barra di navigazione principale (in cima) | permission code canonico -> fallback `NavigationRoleAccess` solo se unmapped |
| `subnav` | Barra secondaria per modulo (filtrata per `parent_code`) | permission code canonico -> fallback `NavigationRoleAccess` solo se unmapped |
| `sidebar` | Menu laterale (modalita sidebar) | permission code canonico -> fallback `NavigationRoleAccess` solo se unmapped |
| `page` | Dentro una pagina specifica | permission code canonico -> fallback `NavigationRoleAccess` solo se unmapped |
| `admin_subnav` | Barra interna dell'admin portale (`/admin-portale/`) | **Nessuna ACL** Ã¢â‚¬â€ area gia gated da `@legacy_admin_required` |

**`admin_subnav` Ã¢â‚¬â€ regola critica:** NON hardcodare mai voci in `admin_subnav.html`. Gestire sempre tramite `NavigationItem` con `section="admin_subnav"` via Navigation Builder o migration. Migration seed: `core/migrations/0031_admin_subnav_seed.py` + `0032_admin_subnav_acl_nav_map.py` (voce aggiuntiva mappa permessi/navigazione). Il context processor inietta `admin_subnav_items` solo per utenti `is_legacy_admin()`.

Navigation Builder (`/admin-portale/navigation-builder/`): oltre alla tabella inline include una **vista visuale drag&drop orizzontale** (scroll laterale) a colonne per sezione (`topbar`, `subnav`, `admin_subnav`, `sidebar`, `page`) con card trascinabili, spostamento cross-sezione e sincronizzazione immediata su `NavigationItem.section` + `NavigationItem.order` tramite `api_navigation_reorder`. Ogni card supporta azioni rapide `Apri`, `Clona`, `Rimuovi`; il listener globale dei click nel template deve restare `async` perchÃƒÂ© invoca fetch asincrone. Nota semantica: `topbar` rappresenta la navigazione principale e in `nav_mode=side` viene renderizzata nella sidebar. Nel builder `sidebar` e trattata come opzione avanzata (`Sidebar Dedicated`) e viene nascosta in modalita standard.

Rendering icone navigazione: `render_icon` supporta alias SVG semantici (`layout-dashboard`, `newspaper`, `scan`, `id-card`, `package`, `shield-check`, `file-check`, `key-round`, ecc.), immagini (`media:`/`static:`/URL) e fallback automatico da label per sostituire iniziali placeholder nella topbar/sidebar.

Sidebar nav side: i gruppi aperti devono restare visivamente distinti dal primo livello tramite pannello annidato, rientro e stato aperto evidente, senza rompere la leggibilita in modalita `sb-collapsed` o mobile.

## Dashboard / Module Boundary

| `/admin/` | Django admin nativo |

Le app `dashboard`, `assenze`, `anomalie`, `timbri`, `rentri`, `core`, `planimetria` usano prefisso vuoto `""` (i path sono definiti internamente al loro `urls.py`).

### Confine dashboard / moduli

- `dashboard` deve restare una superficie KPI/launcher, non il contenitore dei workflow di dominio.
- La dashboard principale vive in `dashboard` come workspace personale: widget KPI multi-modulo, layout utente e template iniziale globale gestito dagli admin. `scheda-dipendente` resta solo come alias compatibile.
- Per `assenze`, il punto di ingresso canonico e il modulo `/assenze/`: menu, nuova richiesta, gestione personale, calendario e certificazione presenza.
- Eventuali route legacy o compatibilita (es. `/richieste`, alias `coming_assenze`) devono puntare al modulo `assenze`, non duplicarne le pagine dentro `dashboard`.

---


## Automations Designer UI Direction

- Builder classico e designer visuale devono passare cataloghi sorgente e preset al frontend come oggetti Python via `json_script`; non usare `json.dumps` sui valori gia destinati a `json_script`, altrimenti i dropdown trigger/condizioni restano fermi sulla sorgente iniziale.
- Designer visuale e pagina test espongono ora un browser campi smart con ricerca, filtri per ambito (`trigger`, `condition`, `template`, `action_mapping`) e inserimento contestuale nel target attivo (select, template o JSON raw).
- Il `source_registry` puo dichiarare per ogni campo metadata UI come `allowed_values`, `value_source_label` e `ui_control`; il designer condizioni deve riusarli per mostrare accanto a `expected_value` il riquadro `Valori disponibili` e, per i campi mappati a colonna fisica, completarlo via endpoint `/admin-portale/automazioni/api/sorgenti/<source>/campi/<field>/valori/` con valori distinti reali dal DB. Il comportamento deve restare generico per qualsiasi campo queryable, non hardcoded a `tipo_assenza`; per `assenze.tipo_assenza` i valori canonici vanno condivisi con il modulo assenze, non duplicati in JS/template.
- Il pannello laterale `Contenuti / Colonne disponibili` del designer deve restare sticky e con scroll autonomo rispetto alla pagina, anche nella workspace del diagramma, per evitare di perdere il contesto mentre si cercano campi o si compongono condizioni/template/mapping.
- La pagina test manuale usa un composer guidato per `payload_json` e `old_payload_json`, sincronizzato con i textarea raw e con diff sintetico dei campi cambiati.
- Le sorgenti che in update aggiungono campi runtime `old_*` direttamente nel payload (es. `tickets`, `tasks`) devono dichiararli nel `source_registry` come campi virtuali per renderli disponibili a catalogo, preset, test e template.
- Il converter Power Automate integrato vive su `admin_portale:automazioni_rule_power_automate_convert`: riusa i servizi della cartella spostata `django_app/powerautomate-to-django-automations/app` tramite `automazioni/power_automate_bridge.py`, non tramite una seconda webapp standalone.
- La pagina `Converti Power Automate` deve restare agganciata al workflow SSR di `Importa Package`: upload `.zip/.json`, analisi, remediation opzionale, diagramma del flow originale, download package e handoff diretto alla sessione di import esistente. Se una singola regola e' gia importabile, il converter puo' anche creare una bozza draft/disattiva e aprirla subito nel designer visuale. Non creare un importer parallelo.
- La tabella target nel converter integrato e' opzionale e va popolata dal catalogo tabelle del portale (`discover_module_tables()`), non dal vecchio wizard SQL Server standalone. Se manca il target, il package deve restare convertibile per il solo runtime portale.
- Per i flow con approval, il converter deve mostrare un selettore di `ApprovalEmailTemplate` attivi, con default sul primo `hybrid` e fallback sul primo `mail_reply`; il package deve salvare il riferimento portabile `approval_email_template_code` e una sezione top-level `approval_conversion`, non dipendere dal solo PK locale.
- La conversione automatica approval e' consentita solo per source noti/non `generic` e solo sul subset sicuro dei branch (`send_email`, `write_log`, `update_trigger_record`). I branch non mappabili restano in `issues`/`warnings`; per `assenze` il converter deve generare un vero `send_approval` e prependere `moderation_status=0/1` nei rami approvato/rifiutato.
- Il designer visuale espone un **test live inline** nel pannello laterale: modalita "Dati campione" e "Record reale" (AJAX picker ultimi 20 record), esecuzione via `POST /api/regole/<id>/test-ajax/` con risultati azione per azione. Endpoint aggiuntivi: `GET /api/sorgenti/<code>/record-recenti/` e `GET /api/sorgenti/<code>/record/<id>/payload/`.
- Nel designer visuale, `branch`, `do_until` e `for_each` non devono presentarsi come editor solo-JSON per il caso d'uso normale: servono pannelli guidati leggibili (`Se Vero/Se Falso`, `Corpo loop/Se completato/Se timeout`, `Azioni per ogni record`) con badge di stato, lista delle azioni inline e quick actions. Il JSON embedded in `config_json` resta il formato canonico, ma va relegato a `JSON avanzato` come fallback esperto senza rompere import/export o riapertura draft.
- Le card azione `send_email` hanno un pulsante "Anteprima" che mostra un pannello email renderizzato live (Da/A/Oggetto/Corpo) con highlight automatico dei `{placeholder}`, aggiornato su ogni keystroke senza submit.
- **Azioni di controllo flusso** (migration 0008): `send_approval`, `do_until`, `for_each`, `branch` â€” tutte con azioni figlie embedded in `config_json` come lista `[{action_type, config_json, description}]`.
  - `send_approval`: pausa il flusso, crea `AutomationApproval`, lascia il run log in `waiting_approval` e mantiene `process_approval_decision()` come source of truth per i rami `approved_actions` / `rejected_actions`. URL decision classici: `/automazioni/approvazione/<token>/approva|rifiuta/` (no login, token-based, `@csrf_exempt`). URL proxy Entra: `/approval-actions/approve|reject/<token>/` (GET one-click, vedi sezione `MIDDLEWARE_EXEMPT_PREFIXES`).
  - `send_approval` supporta `delivery_mode` configurabile in `config_json`: `email`, `teams_webhook_legacy`, `teams_chat_flow`, `email_and_teams_chat_flow`.
  - `teams_webhook_legacy`: mantiene il comportamento storico con `MessageCard` verso webhook di canale Teams; l'endpoint decision rileva POST JSON (chiamate Teams) e risponde con header `CARD-ACTION-STATUS` invece di HTML.
  - `teams_chat_flow`: renderizza `teams_recipient_email_template`, costruisce payload JSON (`approval_id`, `token`, `recipient_email`, `subject`, `message`, `approve_url`, `reject_url`, `expires_at`, `facts`) e invia una `POST` a un endpoint Power Automate / Teams Workflow. Teams recapita la card al singolo utente, ma la business logic resta nel portale: i pulsanti aprono sempre gli URL firmati del portale.
  - `email_and_teams_chat_flow`: recapita sia email sia flow Teams; per default email riuscita + Teams flow fallito produce warning nel `result_message` ma non fallisce l'azione, salvo `strict_teams_flow=true`.
  - `do_until`: esegue `loop_actions` ogni iterazione e si richiama tramite `_insert_loop_reschedule_event()`; esce quando la condizione (`check_field/operator/value`) Ã¨ soddisfatta o si raggiunge `max_iterations`. Tiene il contatore in `payload._loop_iteration`.
  - `for_each`: interroga una sorgente registrata con filtro opzionale, esegue `each_actions` su ogni record (max `max_items`). Solo sorgenti con `table_name` definito nel registry; `filter_field` validato contro i campi esposti.
  - `branch`: valuta una condizione e esegue `if_true_actions` o `if_false_actions`. Simile a `run_if` ma con pieno ramo else.
- **Diagramma di flusso Power Automate-style**: bottone "ðŸ”€ Diagramma di flusso" nel designer visuale. Visualizzazione verticale con nodi colorati, connettori freccia, rami approvazione/branch, corpo loop do_until e iterazione for_each. Renderizzato lato client da `flow_nodes_json` iniettato nel contesto via `_build_flow_nodes()` in `views.py`. Pulsante "Modifica â†“" su ogni nodo scrolla al form corrispondente.
- Il modal del diagramma "Aggiungi azione al flusso" deve renderizzare le card azione gia' lato server e usare la stessa lista serializzata anche nel JS del diagramma; non affidare il picker a un popolamento solo client-side. Inoltre il CSS del modal deve rispettare esplicitamente `[hidden]`, altrimenti puo comparire da solo al load o non sparire davvero in chiusura.
- Nel diagramma, l'editing inline delle azioni deve riusare la card reale del formset invece di creare un secondo editor separato: in questo modo il salvataggio resta SSR, non si sdoppiano gli stati dei campi e il nodo puo' riallinearsi live con preview, titolo e stato della card.
- L'apertura del diagramma deve comportarsi come una workspace split-view stile Power Automate: overlay full-viewport, inspector fisso a sinistra, canvas a destra, `body` bloccato finche' la workspace e' aperta, chiusura con backdrop/Esc e scorciatoie che rimandano alle sezioni `trigger-section`, `conditions-section` e `actions-section` nel form SSR sottostante.
- `AutomationApproval` (migration 0008): token UUID univoco, approver_emails, approved/rejected_actions, status `pending/approved/rejected/expired`, expires_at, decided_by_email. Path `/automazioni/approvazione/` esente da ACL (`MIDDLEWARE_EXEMPT_PREFIXES`).
- `TeamsWebhookPreset` (migration 0009): webhook URL legacy riutilizzabile con nome, descrizione, is_active. Gestito su `/automazioni/canali-teams/`. Il campo `teams_preset_id` in `config_json` di `send_approval` fa lookup del URL da DB; fallback su `teams_webhook_url` raw (retrocompat). I fatti sono specificati come `Etichetta | {valore}` per riga in `teams_facts_inline` (alternativa alla lista JSON legacy `teams_facts`). Nel designer e in `action_card.html` il dropdown Teams legacy mostra solo preset attivi.
- `AutomationDeliveryEndpoint` (migration 0010): endpoint generico riutilizzabile per recapiti automazione, con `endpoint_type` (`teams_webhook_legacy`, `teams_flow_webhook`), URL, flag `is_active`, codice e descrizione. La pagina `/automazioni/canali-teams/` gestisce ora sia i preset legacy sia gli endpoint Teams Flow; `send_approval` usa `teams_flow_endpoint_id` per risolvere l'URL del Power Automate / Teams Workflow, con fallback compatibile su eventuale `teams_flow_url` raw in `config_json`.
- Schema drift difensivo: se il codice gira su un database dove la migration `automazioni.0010_automationdeliveryendpoint` non e' ancora applicata, pagina `Canali Teams`, builder classico, designer visuale e form `SEND_APPROVAL` non devono andare in 500. I lookup verso `AutomationDeliveryEndpoint` degradano a lista vuota con warning UI esplicito e il runtime `teams_chat_flow` restituisce un errore funzionale chiaro; il rimedio operativo resta `python django_app/manage.py migrate automazioni`.
- **Template Email Approvazioni** (migration 0011): `ApprovalEmailTemplate` â€” template riutilizzabili per le mail generate da `send_approval`. Gestiti su `/automazioni/template-approvazioni/` (voce "Template approvazioni" in subnav). Tre `delivery_mode`: `portal_links` (link HTTP, default), `mail_reply` (mailto: verso mailbox tecnica â€” per reti non esposte), `hybrid`. La mailbox tecnica si configura per-template (`mailto_mailbox`) o tramite `SiteConfig` chiave `automazioni_approval_mailbox`. Service layer in `automazioni/approval_email_templates.py`: rendering, context building, build mailto links, preview. Il `config_json` di `send_approval` puo' referenziare il template con `approval_email_template_id` (PK) o `approval_email_template_code`, ma per package/import/export e riapertura draft il riferimento canonico deve essere `approval_email_template_code`; l'id locale resta solo comodita' di lookup. Schema drift: lookup safe se migration non applicata. La preview su `/automazioni/template-approvazioni/<pk>/preview/` mostra HTML renderizzato con dati mock e rileva placeholder non risolti.

## Global Search UI

## Ricerca Globale (Ctrl+K)

- Endpoint: `GET /api/search/?q=<query>` â†’ `core/views.py:api_global_search` â†’ `core/urls.py`
- Attivazione: `Ctrl+K` (o `Cmd+K` su Mac) oppure click sull'icona ðŸ” nella topbar
- Modelli interrogati (max 5 risultati per gruppo): `AnagraficaDipendente`, `Asset`, `Ticket`, `Project`, `Task`, `ProcedureDocument`
- I modelli di altre app vanno importati localmente dentro la funzione per evitare import circolari
- Risposta: `{"results": [{tipo, label, sub, url}, ...], "query": "..."}` con risultati raggruppati per tipo
- UI: overlay spotlight in `topnav.html` con navigazione da tastiera (frecce, Enter, Esc), debounce 220ms; in modalita sidebar il trigger rapido vive anche in `core/components/sidebar.html` come card scura integrata con hint `Ctrl+K` e resa icon-only quando `sb-collapsed` e attivo
- CSS: classi `.gs-*` in `theme.css`; ogni tipo di risultato ha la sua classe colore `.gs-tipo-<tipo>`
- Query minima: 2 caratteri; gestione errori per app non disponibili tramite `try/except` silenzioso

---

