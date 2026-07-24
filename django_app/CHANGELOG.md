# Changelog

## [Unreleased]

### Epica C / 4.2 — Registro OFI centralizzato PDCA (allineato MOD.174)

- **[feat/test] `gestione_specifiche/models.py` (`RegistroOFI` [nuovo modello], `AzioneOFI.registro` FK), `gestione_specifiche/migrations/0013_registroofi_azioneofi_registro.py` [nuovo], `gestione_specifiche/registro_ofi.py` [nuovo servizio], `gestione_specifiche/ofi.py` (`crea_ofi_da_riga`), `gestione_specifiche/views.py` (`ofi_registro`), `gestione_specifiche/urls.py`, `gestione_specifiche/acl_bootstrap.py`, `gestione_specifiche/admin.py` (`RegistroOFIAdmin`), `gestione_specifiche/templates/gestione_specifiche/ofi_registro.html` [nuovo], `gestione_specifiche/management/commands/send_ofi_reminders.py` [nuovo], `gestione_specifiche/tests/test_registro_ofi.py` [nuovo]**: (punto 4.2) nuovo **registro OFI centralizzato** che risolve il blocker storico B1 (l'OFI era solo un intero). Il modello `RegistroOFI` replica la struttura **PDCA del MOD.174**: numero di registro, REF, normative (ISO 27001/45001/EN 9100), rif. norma, processo/area, opportunità/descrizione, ciclo **PLAN-DO-CHECK-ACT**, priorità, **proprietario** e **owner di processo**, data richiesta chiusura + **reminder**, riferimento generico d'origine (`content_type`/`object_id`) per l'aggancio **multi-modulo** (le OFI non nascono solo da MOD.133). La generazione OFI da una riga MOD.133 (`crea_ofi_da_riga`) crea automaticamente la **voce di registro** (una per riga, idempotente) e vi collega le `AzioneOFI` (nuova FK `registro`). Servizio `registro_ofi` con numerazione condivisa senza collisioni, contatori **P/D/C/A/TOT** e selezione voci da sollecitare. Nuova pagina **Registro OFI** (`/gestione-specifiche/ofi-registro/`, gated `gestione_specifiche.specifica.view`) con contatori PDCA, filtri fase/priorità/scaduti; gestione campi PDCA da admin; comando schedulabile `send_ofi_reminders` (fail-safe, `--dry-run`/`--days`). **Fix binding ACL**: aggiunti al registro anche i binding mancanti delle rotte 4.1 `riga_documento_add`/`riga_documento_delete` (`mod133.compila`). Migrazione additiva. 15 test.

### Epica C / 4.1 — MOD.133: più documenti impattanti sulla stessa riga

- **[feat/test] `gestione_specifiche/models.py` (`RigaMOD133Documento` [nuovo modello]), `gestione_specifiche/migrations/0012_rigamod133documento.py` [nuovo], `gestione_specifiche/ofi.py` (`documenti_riga`, `crea_ofi_da_riga`), `gestione_specifiche/composito.py`, `gestione_specifiche/views.py` (`riga_documento_add/delete`, `dettaglio`), `gestione_specifiche/urls.py`, `gestione_specifiche/admin.py`, `gestione_specifiche/templates/gestione_specifiche/{dettaglio,mod133_compila}.html`, `gestione_specifiche/tests/test_ofi_multidoc.py` [nuovo]**: (punto 4.1) una riga MOD.133 può impattare **più documenti CN**. Il documento **primario** resta `RigaMOD133.rif_doc_cn` (form, validazione e composito invariati); la nuova tabella figlia `RigaMOD133Documento` elenca i documenti **ulteriori** (nessuna migrazione dati). La generazione OFI (`crea_ofi_da_riga`) crea ora **una azione OFI per documento impattato** (primario + figli), tutte con lo **stesso numero OFI** della riga, **idempotente per documento**; il caso storico a documento singolo resta identico. Il composito MOD.133 e la modale/scheda OFI elencano tutti i documenti impattati. Gestione documenti aggiuntivi dalla pagina di compilazione (solo in flow-down) e da admin. Migrazione additiva. 13 test (helper/OFI/composito + 2 view).

### Remediation gestionale — 1.8 (abilitazione MPQ multi-dipendente)

- **[feat/test] `anagrafica/views_mpq.py` (`bulk_abilita_processo`, `mpq_abilitazione_add`, `_abilitazione_form_ctx`), `anagrafica/templates/anagrafica/pages/mpq_abilitazione_form.html`, `anagrafica/tests_mpq_bulk.py` [nuovo]**: (punto 1.8) nella scheda **Processo qualificato (MOD.128)**, l'aggiunta di persone abilitate consente ora la **selezione multipla di dipendenti interni** → crea in blocco N `AbilitazioneProcesso` in un'unica transazione (idempotente sul vincolo persona×processo, deduplica gli id ripetuti). Il caso **qualificatore esterno** resta a persona singola. La modifica (edit) di una singola abilitazione resta invariata. 4 test. Nessuna migrazione.

### Remediation gestionale — 1.10 / 1.11 (ratei con operatori, KPI assenze)

- **[feat/test] `anagrafica/ratei_alert.py` (`saldo_filter_q`, `SALDO_CAMPI`, `SALDO_OPERATORI`), `anagrafica/views.py` (`ratei_list`, `ratei_export`), `anagrafica/templates/anagrafica/pages/ratei_list.html`, `anagrafica/tests_ratei_filtri.py` [nuovo]**: (punto 1.10) nella lista **Ratei ferie** aggiunto il filtro **per valore del saldo con operatore di confronto** (`<`, `>`, `=`) su Ferie residue / ROL residui / Ex-festività residue. Whitelist esplicita dei campi filtrabili; stesso filtro replicato nell'**export XLSX** per coerenza lista/export. Nessuna migrazione.
- **[feat/test] `anagrafica/views.py` (`_assenze_kpi_annuali`, `dipendente_detail`), `anagrafica/templates/anagrafica/pages/dipendente_detail.html`, `anagrafica/tests_assenze_kpi.py` [nuovo]**: (punto 1.11) nella scheda dipendente, sezione **Assenze**, aggiunti **KPI annuali**: conteggio delle **richieste per tipologia** (ferie, malattia, permesso…) per ciascun anno presente (corrente + precedente, tutte le moderazioni). Complementare al riepilogo giorni-anno-corrente-approvate già esistente. Nessuna migrazione.

### Remediation gestionale — 3.4 (rinomina sezione asset)

- **[style] `assets/templates/assets/pages/asset_detail.html`**: (punto 3.4) la sezione **"Storico interventi"** della scheda asset è rinominata **"Interventi straordinari"** (solo etichetta, stessi dati mostrati — scelta confermata).

### Remediation gestionale — numerazione incrementale (1.7 + 3.3, §5.3)

- **[feat/test] `core/numbering.py` [nuovo], `core/tests_numbering.py` [nuovo]**: servizio di numerazione condiviso (funzioni pure `max_numeric`/`next_numeric`/`next_suffix`/`next_code`), riusato da asset e formazione.
- **[feat/test] `assets/models.py` (`Asset.save`), `assets/tests_numbering_p3.py` [nuovo]**: (punto 3.3) **N. interno asset progressivo** — se lasciato vuoto alla creazione viene assegnato `max numerico + 1` (i numeri interni legacy alfanumerici sono ignorati). Nota: campo non unique → progressivo "suggerito", non chiave.
- **[feat/test] `anagrafica/views.py` (`formazione_corso_codice_suggest`), `anagrafica/templates/anagrafica/pages/formazione_corso_form.html`, `anagrafica/tests_numbering_p3.py` [nuovo]**: (punto 1.7) **codice corso gerarchico** `<codice piano>-<N>` (N progressivo per piano); il form suggerisce il codice al cambio piano. Le lezioni restano numerate a parte via `TrainingLesson.numero`. Fallback storico (base dal titolo) senza piano.

### Remediation gestionale — 1.2 (nome al posto dell'ID nelle tabelle)

- **[style] `anagrafica/templates/anagrafica/pages/{formazione_dashboard,qualifiche_dashboard,qualifiche_scadenzario,formazione_corso_detail,formazione_piano_detail}.html` + `partials/{_formazione_search_results,_safety_search_results,_formazione_search_suggest,_safety_search_suggest}.html`**: (punto 1.2) rimossi i tag `#id` secondari accanto ai nomi nelle tabelle/ricerche utente (il **nome** era già la voce primaria). **Invariati** i documenti di stampa (libretto/print, dove l'ID legacy è metadato) e le schermate admin/diagnostica. Le griglie Skill Matrix / MOD.128 / DPI risolvevano già i nomi (nessun ID grezzo).

### Epica A / A1 — mansione di rischio: modello + resolver

- **[feat/test] `anagrafica/models_rischi.py`, `anagrafica/admin.py`, `anagrafica/migrations/0087_esposizionerischio_legacy_anagrafica_id_and_more.py`, `anagrafica/tests_mansione_rischio_a1.py`**: (punto 1.9) `EsposizioneRischio` può ora puntare anche a un **singolo dipendente** (`legacy_anagrafica_id`), oltre a mansione/area; `clean()` esige almeno un target. Migrazione additiva (AddField + AddIndex). Fondazione dell'Epica A ("mansione di rischio" a vista); nessuna UI.
- **[feat/test] `anagrafica/services/mansionario.py`**: nuova `requisiti_dipendente(legacy_id)` — requisiti effettivi del dipendente come **unione** di mansione lavorativa + esposizioni di area + esposizioni dirette (dedup). Fonte unica riusata da A2 (pannello scheda) e A3 (filtro DPI). Refactor DRY del derivatore fattori→requisiti (`_requisiti_da_fattori`/`_corsi_per_categoria`), condiviso col resolver mansione esistente.

### Epica A / A2.1 — form "nuovo dipendente" (punto 1.4)

- **[feat/test] `anagrafica/views.py`, `anagrafica/templates/anagrafica/pages/dipendente_create.html`, `anagrafica/tests_area_aziendale_dipendente.py`**: (punto 1.4) il form di creazione dipendente ora espone **Area aziendale** (accanto a Reparto, validata contro il reparto da `_sync_aziendale_from_reparto`) e **Ruolo**; le sezioni **"Ruoli operativi di sicurezza"** e la DPI-all'ingresso ad esse accoppiata sono **nascoste** (il profilo di rischio deriva dalla mansione, non dai ruoli operativi). Nuovo `DipendenteCreateFormA2Tests`.
- **[feat/test] `anagrafica/views.py` (`dipendente_conformita_panel`), `anagrafica/templates/anagrafica/partials/conformita_panel.html`, `anagrafica/tests_mansione_rischio_a2.py`**: (A2.2) pannello **"Profilo di rischio"** derivato (sola lettura) nella card Conformità della scheda dipendente — fattori/DPI/visite da `requisiti_dipendente()` + elenco esposizioni dirette. Nuovo `ProfiloRischioPanelTests`.
- **[feat/test] `anagrafica/views.py`, `anagrafica/urls.py`, `anagrafica/templates/anagrafica/partials/conformita_panel.html`, `anagrafica/tests_mansione_rischio_a2.py`**: (A2.2 / punto 1.9) mini-form **admin** nel pannello per **assegnare/rimuovere un'esposizione di rischio direttamente al dipendente** (HTMX, ri-renderizza il pannello). Context del pannello estratto in `_build_conformita_panel_ctx`. Nuovi test add/remove.

### Epica A / A3 — richiesta DPI filtrata per mansione di rischio (punto 2.1)

- **[feat/test] `dpi/views.py` (`nuova_richiesta`), `dpi/templates/dpi/pages/nuova_richiesta.html`, `dpi/tests_profilo_rischio.py`**: (punto 2.1) la richiesta DPI mostra come disponibili **solo i DPI del profilo di rischio** del richiedente (mansione + esposizioni, via `requisiti_dipendente()`), con badge "✓ Profilo mansione". Un toggle **"Mostra anche i DPI fuori profilo"** consente comunque la richiesta con **motivazione obbligatoria** (registrata + nota `[Richiesta fuori profilo di rischio]` auditabile). Profilo vuoto = nessun filtro. Nuovo `NuovaRichiestaProfiloRischioTests`.

### Remediation gestionale — quick-win P1 (bug filtro visite, cessati scadenzario, tag PART145)

- **[fix/test] `anagrafica/templates/anagrafica/pages/visite_mediche_nuova_sessione.html`, `anagrafica/tests_visite_sessione.py`**: (punto 1.1) nel flusso "Giornata visite / Nuova sessione" il select "Filtra per tipo" inviava `name="_tipo_filtro"` mentre la view `visite_mediche_candidati` legge `?tipo` → cambiando la tipologia di visita la lista sottostante non si riaggiornava mai. Rinominato il campo in `tipo`. Aggiunto test di contratto in `GiornataRenderTests`.
- **[fix/test] `anagrafica/views.py`, `anagrafica/tests_visite_sessione.py`**: (punto 1.3) gli ex dipendenti (rapporto cessato) comparivano ancora nello scadenzario nei rami **qualifiche / visite / formazione**: il filtro `_cessati_legacy_ids()` era applicato solo al ramo contratti. Ora è calcolato a monte in `_build_scadenzario_voci` ed escluso da tutte le sorgenti (`.exclude(legacy_anagrafica_id__in=cessati)`). Nuovo `ScadenzarioCessatiTests`.
- **[style] `assets/templates/assets/pages/asset_detail.html`**: (punto 3.1) il tag "PART 145" nella scheda asset passa da rosso a **blu** con testo bianco (`#1d4ed8` light / `#2563eb` dark), coerente con il blu accent del tema.

### Remediation gestionale — quick-win P2 (date asset, matricola)

- **[feat/test] `assets/forms.py`, `assets/templates/assets/pages/asset_detail.html`, `assets/tests_quickwin_p2.py`**: (punto 3.2) i campi **Data acquisto** (`purchase_date`) e **Data fabbricazione** (`production_date`, prima etichettato "Data produzione") sono ora mostrati nella scheda asset (hero-tag) oltre che nei form. Nuovo `AssetDataFabbricazioneTests`.
- **[feat/test] `anagrafica/templatetags/anagrafica_extras.py`, `anagrafica/templates/anagrafica/pages/{dipendente_detail,dipendenti_report}.html`, `anagrafica/tests_quickwin_p2.py`**: (punto 1.15) filtro `matricola_fmt` che rimuove gli **zeri di padding** dalla matricola **solo in visualizzazione** e **solo se numerica** (le matricole alfanumeriche restano invariate). Applicato a scheda dipendente e report. Nuovo `MatricolaFmtTests`.
- **[feat/test] `anagrafica/templates/anagrafica/pages/formazione_corsi.html`, `anagrafica/tests_quickwin_p2.py`**: (punto 1.6) colonna **"Creato il"** nel catalogo corsi. Le altre tabelle formazione avevano già la data: la scheda dipendente mostra "Completato il" + "Scadenza", le sessioni "Inizio/Fine". Nuovo `FormazioneCorsiDataTests`.

### SOC IT - CN - mailbox-admin + API DRF read-only

- **[feat/test] `security/urls_hub.py`, `security/templates/security/{admin_mailbox_sources_list,admin_mailbox_source_detail}.html`, `security/tests_soc.py`**: montate le ultime superfici escluse. (1) **mailbox-admin**: pagine config sorgenti mailbox (sola lettura) su `/soc/admin/mailbox/` — l'ingestione Graph/IMAP resta fuori (serve credenziali + scheduling). (2) **API DRF read-only**: `/soc/api/{dashboard-summary,alerts/recent,kpis/summary}/` (JSON, `permission_classes=[CanViewSecurityCenter]`, ACL-gated). **Esclusi di proposito**: `api_ai.py` (AI NVIDIA di SC-AI → contraddice la convergenza su Ollama del sotto-progetto C) e `api_configuration.py` (config wizard della SPA React droppata). ACL: 31 permessi `security.*` (grant admin). 22 test `tests_soc` verdi. `check` pulito.

### SOC IT - CN - Follow-up innesto (README, CSS, test subset, UI asset)

- **[docs/style/test/feat] `README.md`, `security/static/security/security.css`, `security/tests/`, `security/views_soc.py` + `templates/security/soc_assets.html`, `security/templates/security/_base_soc.html`, `security/tests_soc.py`**: rifiniture post-programma. (1) Righe moduli contatori/security nel README. (2) `security.css` **scopata sotto `.soc-module`** (niente leak del tema dark sullo shell HUB). (3) Sottoinsieme suite SC-AI che regge (111 test: ai_config/ai_memory/rule_simulation) — esclusi i test di funzioni non wired (API/AI/mailbox/React) e le **fixtures con dati REALI del firewall** (non versionabili). (4) Pagina `/soc/assets/` (lista SecurityAsset + link Asset HUB da D2) + nav con link reali + ACL + 2 test. `check` pulito. API DRF/mailbox-admin restano superfici escluse.

### SOC IT - CN - Security Center sotto-progetto D2: collegamento SecurityAsset<->Asset

- **[feat/test] `security/models.py` + `migrations/0010_securityasset_hub_asset.py`, `security/management/commands/collega_asset_security.py` [nuovo], `security/tests_soc.py`**: fase D2. FK opzionale `SecurityAsset.hub_asset`→`assets.Asset` (SET_NULL); comando `collega_asset_security` (match ip↔endpoint, hostname↔name; dry-run/apply; **non tocca gli Asset**). Collega i device di sicurezza al registro asset HUB (alert/vulnerabilità → asset fisico). 3 test (`SecurityAssetLinkTest`, 18 totali). Migrazione additiva. Nessuna UI (pagina security-asset non wired).

### SOC IT - CN - Contatori sotto-progetto D1: collegamento agli asset dell'HUB

- **[feat/test] `contatori/models.py` + `migrations/0004_macchina_asset.py`, `contatori/management/commands/collega_asset.py` [nuovo], `contatori/templates/contatori/macchina.html`, `contatori/tests.py`**: fase D1 (collegamento asset, post-implementazione). FK opzionale `Macchina.asset`→`assets.Asset` (SET_NULL); comando `collega_asset` (match matricola↔serial e host↔ip, dry-run/apply, **non tocca gli Asset**); pannello "Asset collegato" con link nella scheda macchina. 4 test (`CollegamentoAssetTest`, 36 totali contatori). Migrazione additiva su SQL Server. D2 (Security↔Asset) a seguire.

### SOC IT - CN - Security Center sotto-progetto C: tool live nell'assistente AI

- **[feat/test] `ai_assistant/tools.py`, `security/tests_soc.py`**: tool live **`soc_summary`** nell'assistente AI (Ollama) — espone AGGREGATI del Security Center (alert aperti/critici/alti, ticket remediation aperti, CVE critiche, report di oggi): **solo conteggi**, nessun titolo/hostname/IP/asset (privacy). Gate ACL `security.dashboard.view` (bypass superuser/admin). Keyword IT-security disambiguate dalla sicurezza-sul-lavoro. Convergenza AI: dati security nell'assistente unico dell'HUB. 3 test (`SocAiToolTest`). Nessuna migrazione.

### SOC IT - CN - Security Center AI fase B4: test di regressione dell'innesto

- **[test] `security/tests_soc.py` [nuovo]**: 12 test scoped sull'innesto SOC IT - CN (pagine `/soc/` render 200, pipeline sincrona, Configuration Studio, i 2 task `django-q2` puri). **Non** è la suite SC-AI completa (che testa anche funzioni non ancora montate e contiene fixture con **segreti sintetici** bloccati dall'hook pre-commit) → riportata separatamente in futuro. Lavoro spostato su **branch dedicato `feat/soc-security-b4`** per isolarlo da una sessione parallela sul modulo `ai_assistant`.

### SOC IT - CN - Security Center AI fase B3: Pipeline + Celery->django-q2 + Configuration Studio

- **[feat/refactor] `security/urls_hub.py`, `security/tasks.py`, `security/templates/security/{pipeline,inbox,help,admin_diagnostics,admin_docs,admin_addons,admin_addon_detail}.html` + `admin_config/*.html`**: fase B3 del core SC-AI. **Pipeline** (parser+regole+KPI) sincrona via HTMX (nessuna coda); i 2 task background da **Celery a django-q2** (funzioni pure, rimosso import `security_center_ai.celery`); montato l'intero **Configuration Studio** (config + diagnostica + inbox + moduli). **ACL v2**: 25 permessi `security.*` + 26 binding, grant al ruolo **admin**. `check` pulito, tutte le pagine 200. Escluso: API DRF (stub per il solo reverse), mailbox-admin, AI dormiente, suite test (B4).

### SOC IT - CN - Security Center AI fase B2: pagine Alert/Ticket/KPI + ACL + nav

- **[feat] `security/urls_hub.py`, `security/templates/security/{alerts_list,alert_detail,tickets_list,kpis}.html`, `core/migrations/0068_soc_security_nav.py` [nuovo], `dashboard/views_home_portale.py`**: fase B2 del core SC-AI. Montate le pagine **Alert/Ticket/KPI** (viste reali di `security/views.py`) su `/soc/…` nello shell dell'HUB; **ACL v2** con 8 permessi `security.*` + binding + grant al ruolo **admin** (Direzione rimandata); voce topbar **Security Center** (`shield`) + tile launcher nell'area SOC IT - CN. Escluso (→B3): pipeline/ingestione, admin/config, inbox, diagnostica, API DRF; parte AI dormiente; suite test (B4). `check` pulito.

### SOC IT - CN - Security Center AI (core) fase B1: app security innestata

- **[feat] `security/**` [app SC-AI copiata, suite test esclusa], `config/settings/base.py`, `config/urls.py`, `security/urls_hub.py` [nuovo urlconf minimo], `security/templates/security/{_base_soc.html [nuovo],dashboard.html}`, `requirements.in`/`requirements.txt` [+djangorestframework]**: fase B1 del core Security Center AI (area SOC IT - CN). App `security` registrata + **35 tabelle `security_*`** migrate su SQL Server (33 modelli + 2 M2M) + **dashboard** resa nello shell `core/base.html` su **`/soc/`** dietro login. DRF installato (l'import di `permissions.py` lungo il path dashboard lo richiede). Escluso da B1: API DRF, altre pagine, parser, AI (copiata ma dormiente), Celery→django-q2, ACL/nav (B2), test (B4). `check` pulito.

### SOC IT - CN - Contatori MFC innestato come modulo nativo dell'HUB

- **[feat/test] `contatori/**` [nuova app], `config/settings/base.py`, `config/urls.py`, `core/migrations/0067_soc_it_cn_category.py` [nuovo], `dashboard/views_home_portale.py`, `requirements.in`/`requirements.txt`, `contatori/tests.py`**: innesto del tool **Contatori MFC** (contatori Canon iR-ADV: letture, riconciliazione fatture BASE, analisi volumi, consumabili SNMP, export Excel) come **modulo nativo SSR+HTMX** dell'HUB, primo della nuova area **SOC IT - CN** (`ModuleCategory key=soc_it_cn`, teal `#0f766e`, voce topbar icona `printer`). Usa **auth/ACL dell'HUB** (viste dietro `ACLMiddleware`, nessun login proprio); template migrati sullo shell `core/base.html` con CSS **scoped** `.contatori-module`; dipendenza **`puresnmp==2.0.1`**; tabelle `contatori_*` su SQL Server. **ACL v2**: 16 permessi `contatori.*` + binding, grant al ruolo **admin** (IT pieno) — **Direzione rimandata**. **32 test scoped verdi**, `check` pulito. Wiring `base.py`/`urls.py` e nota README non inglobati in questo commit (working tree condiviso con WIP di altra sessione). Config ACL vive nel DB: su test/prod rieseguire `bootstrap_acl_v2 --apply --apps=contatori` + grant admin.

### Fruibilità - Tour guidati (driver.js) riusabili e dichiarativi + tour pilota DPI

- **[feat/test] `core/static/core/vendor/driver/*` [nuovi], `core/static/core/js/tour.js` [nuovo], `core/templates/core/base.html`, `dpi/.../report_conformita.html`, `core/test_vendor_assets.py`, `docs/portale/FRUIBILITA_OSS_PLAN.md`**: voce D2 (F1) del piano fruibilità. Integrato **driver.js** (self-hostato) per i **tour guidati** interattivi, con un launcher **riusabile e dichiarativo** `core/js/tour.js`: una pagina definisce i passi mettendo sugli elementi `data-tour-step="N"` + `data-tour-title`/`data-tour-text`, e un pulsante `data-tour-start` avvia il tour (opz. `data-tour-key` per ricordare «già visto» in localStorage, `data-tour-auto` per partire una volta alla prima visita). **driver.js è caricato in modo lazy** (zero costo sulle pagine senza tour; URL in `window.NHUB_TOUR`), i passi includono **solo gli elementi visibili** (il tour si adatta a cosa è in pagina), pulsanti in italiano. **Pilota**: pulsante «❓ Tour guidato» nel **Report conformità DPI** che accompagna in 4 passi (filtri/dipendente → Copilota DPI → Esporta Excel → tabella stato DPI). Per nuovi tour su altri moduli bastano i `data-tour-*` (nessun nuovo codice: solo contenuto). Guardrail `core/test_vendor_assets.py` esteso (file driver + wiring + pilota); 9 test verdi; `manage.py check` pulito.

### Fruibilità - Command palette Ctrl+K (salto rapido cross-modulo, ACL-filtrato)

- **[feat/test] `core/static/core/js/command-palette.js` [nuovo], `core/static/core/css/command-palette.css` [nuovo], `core/context_processors.py`, `core/templates/core/base.html`, `core/test_vendor_assets.py`, `docs/portale/FRUIBILITA_OSS_PLAN.md`**: voce D4 del piano fruibilità. **Command palette** vanilla (nessuna dipendenza) richiamabile con **Ctrl+K / Cmd+K** per saltare rapidamente a **qualsiasi pagina** del portale (utile con ~27 moduli). L'indice è **piatto e ACL-filtrato lato server**: il context processor `legacy_nav` espone `command_palette_items` costruito dai `nav_items`/subnav già calcolati (riusa il filtro permessi della navigazione; esclude le voci «in arrivo»/placeholder e deduplica per URL). UI: overlay di brand (tema chiaro+scuro), **filtro multi-termine** su label e gruppo, navigazione con **frecce/Invio/Esc**, costruzione **lazy** alla prima apertura. **Zero costo per utenti anonimi** (lista vuota → lo script esce subito). Guardrail `core/test_vendor_assets.py` esteso (wiring in `base.html` + file presenti); `manage.py check` pulito; 8 test verdi. **Chiude l'Ondata D** del piano (e il piano fruibilità, salvo i polish opzionali D1–D3).

### Fruibilità - Export Excel riusabile (openpyxl) + pilota conformità DPI

- **[feat/test] `core/excel_export.py` [nuovo], `dpi/views.py`, `dpi/templates/dpi/pages/report_conformita.html`, `core/test_excel_export.py` [nuovo], `dpi/tests.py`, `docs/portale/FRUIBILITA_OSS_PLAN.md`**: voce C2 del piano fruibilità. Nuova **util condivisa** `core/excel_export.py` (`make_xlsx_response` / `build_xlsx_bytes`, openpyxl **già installato**) che genera un `.xlsx` in **stile NOVICROM HUB** (intestazione navy su testo bianco, larghezze colonna automatiche, riga intestazione bloccata, autofiltro) e lo restituisce come download — la view resta responsabile di **ACL e filtri**. **Pilota**: nel **Report conformità DPI**, quando un dipendente è selezionato, un pulsante **«Esporta Excel»** scarica la tabella DPI (categoria, stato, ultima consegna, scadenza, richiesta) riusando i **dati già calcolati** dalla view; gated `_is_gestore`, **audit solo-metadati** (`dpi_conformita_export_xlsx`: dipendente_id, n. righe). Riusabile altrove (saturazione carichi, asset…) passando `columns` + `rows`. 3 test (util: xlsx valido riapribile + header risposta ripuliti; view: 200 + content-type spreadsheet + attachment + firma `PK`).

### Fruibilità - Chart.js riusabile (helper di brand) + grafico pilota su statistiche anomalie

- **[feat/test] `core/static/core/js/chart-helper.js` [nuovo], `anomalie/.../anomalie_statistiche.html`, `core/test_vendor_assets.py`, `docs/portale/FRUIBILITA_OSS_PLAN.md`**: voce C1 del piano fruibilità. Dopo il self-host di Chart.js (A1), introdotto un **helper riusabile** `NHUB.barChart/lineChart/chart` (`core/js/chart-helper.js`) con **default di brand** (palette navy/cyan/orange, responsive) e **gestione del ciclo di vita** (ridisegnare sullo stesso `<canvas>` distrugge l'istanza precedente → niente leak sui re-render/filtri). **Pilota**: la pagina **Statistiche anomalie** ora mostra la **distribuzione per mese anche come grafico a barre** (oltre alla tabella esistente), alimentato dagli **stessi dati già fetchati** dall'endpoint — additivo, nessuna modifica al backend. Chart.js + helper sono inclusi **per-pagina** (non globali, ~60KB solo dove servono). Per aggiungere un grafico altrove: includere Chart.js + l'helper e chiamare `NHUB.barChart(canvas, {labels, values, label})`. Guardrail `core/test_vendor_assets.py` esteso (helper presente + uso nel pilota); 7 test verdi.

### Fruibilità - Date picker (Flatpickr) con locale IT, opt-in via classe `js-datepicker`

- **[feat/test] `core/static/core/vendor/flatpickr/*` [nuovi], `core/static/core/js/flatpickr-init.js` [nuovo], `core/templates/core/base.html`, `admin_portale/.../audit_log.html`, `core/test_vendor_assets.py`, `docs/portale/FRUIBILITA_OSS_PLAN.md`**: voce B2 del piano fruibilità. Integrato **Flatpickr** (self-hostato, JS+CSS+**locale italiano**) come date picker coerente, in **progressive enhancement**: si attiva **solo** sugli `<input class="js-datepicker">` (e `js-daterange` per il range) e senza JS resta l'`<input type="date">` **nativo**. Per evitare il doppio picker, l'init passa l'input a `type=text` solo dopo aver verificato che JS è attivo. **Compatibilità Django**: `dateFormat:"Y-m-d"` → il valore inviato resta ISO (i filtri server continuano a funzionare), mentre l'utente vede `d/m/Y` (`altInput`). Init globale `flatpickr-init.js` (una volta in `base.html`, `defer`) che inizializza anche gli input arrivati via **HTMX** e ignora i già-inizializzati; fail-safe (`try/catch`, ripristino del nativo su errore). **Pilota**: filtro «Data» dell'audit log. Per estenderlo basta aggiungere la classe. Guardrail `core/test_vendor_assets.py` esteso (file + wiring + classe pilota); 6 test verdi.

### Fruibilità - Select ricercabili (Tom Select) opt-in via classe `js-searchable`

- **[feat/test] `core/static/core/vendor/tom-select/*` [nuovi], `core/static/core/js/tomselect-init.js` [nuovo], `core/templates/core/base.html`, `dpi/.../report_conformita.html`, `tickets/.../gestione_detail.html`, `core/test_vendor_assets.py`, `docs/portale/FRUIBILITA_OSS_PLAN.md`**: voce B1 del piano fruibilità. Integrato **Tom Select** (self-hostato) per trasformare i `<select>` con liste lunghe in **menu ricercabili/typeahead accessibili**, in **progressive enhancement**: si attiva **solo** sui `<select class="js-searchable">` (opt-in) e il select nativo continua a funzionare se JS è off o la libreria non carica (fail-safe in `try/catch`). Init globale `tomselect-init.js` (incluso una volta in `base.html`, `defer`) che inizializza i select al `DOMContentLoaded` **e dopo gli swap HTMX** (`htmx:afterSwap`), ignorando quelli già inizializzati; `create:false` (nessuna opzione inventata), `maxOptions:null` (liste intere), placeholder da `data-placeholder`. **Piloti**: report conformità DPI (selettori **dipendente** ~fino a 100 voci, e **categoria**) e dettaglio gestione **ticket** (tecnico interno + fornitore). Per abilitarlo altrove basta aggiungere la classe `js-searchable`. Guardrail `core/test_vendor_assets.py` esteso (file vendorizzati + wiring in `base.html` + classe sul select pilota); 4 test verdi. Nessun impatto sulle pagine senza `.js-searchable` (Tom Select scopa solo i propri elementi `.ts-*`).

### Fruibilità - Self-host del font Outfit (Google Fonts → locale, offline-safe)

- **[chore/test] `core/static/core/vendor/outfit/*` [nuovi], `core/templates/core/base.html`, 6 template di stampa (`dashboard/employee_board_pdf`, `anomalie/report_segnalazione`+`apertura_segnalazione`, `anagrafica/attestato_formazione`+`dipendente_print`+`dipendente_libretto`), `core/test_vendor_assets.py`**: voce A2 del piano fruibilità. Il font **Outfit** non è più caricato da **Google Fonts** (CDN esterno, dipendenza di rete a runtime) ma **self-hostato** in `core/static/core/vendor/outfit/`: poiché Outfit è un **variable font**, bastano **2 woff2** (latin + latin-ext, ~47KB totali) a coprire tutti i pesi 400–800; CSS locale con `@font-face` a path relativi. Repoint di `base.html` (globale) e dei 6 template di stampa/PDF (browser-print: nessuna libreria HTML→PDF nel progetto, quindi `{% static %}` è sicuro) → **tipografia coerente anche offline**, incluse le stampe. **Guardrail esteso** (`core/test_vendor_assets.py`): ora fallisce anche su `fonts.googleapis.com`/`fonts.gstatic.com`, e verifica la presenza di `outfit/outfit.css`. 2 test verdi. Degradazione invariata se un asset manca (font di sistema). Chiude l'Ondata A (nessun CDN a runtime nei template).

### Fruibilità - Self-host delle librerie front-end (niente CDN a runtime) + fix latenti calendario/gantt

- **[chore/fix/test] `core/static/core/vendor/*` [nuovi], `assets/.../calendario_asset.html`, `assets/.../asset_detail.html`, `assenze/.../calendario.html`, `rilevazione_incidenti/.../statistiche.html`, `admin_portale/.../navigation_builder.html`, `automazioni/.../rule_designer.html`, `core/test_vendor_assets.py` [nuovo], `docs/portale/FRUIBILITA_OSS_PLAN.md` [nuovo]**: prima voce del piano fruibilità (Ondata A). Le librerie front-end caricate **da CDN a runtime** (rischio offline/CSP/supply-chain su un portale on-premise) sono ora **self-hostate** in `core/static/core/vendor/` (**stesse versioni** → zero cambi di comportamento) e i template puntano a `{% static %}`: **Chart.js 4.4.4**, **FullCalendar 6.1.11** (assets) e **6.1.17 + locales-all** (assenze), **frappe-gantt 0.6.1**, **SortableJS 1.15.2**, **html2canvas 1.4.1**. **Due fix latenti emersi**: (1) i `<link>` alla CSS di FullCalendar 6 davano **404** (FC6 inietta la CSS dal bundle JS) → rimossi; (2) `frappe-gantt.umd.js` **non esiste** nella 0.6.1 (il file referenziato 404 → la **gantt del calendario asset era rotta a runtime**) → ora `frappe-gantt.min.js` vendorizzato. **Guardrail** `core/test_vendor_assets.py`: fallisce se un template reale reintroduce un `<script>`/`<link>` da jsdelivr/unpkg/cdnjs, e verifica la presenza dei file vendorizzati (i Google Fonts restano esclusi: voce A2 separata). 2 test verdi. Nessun cambio funzionale per l'utente (le stesse feature, ma offline-safe). *(Resta un file orfano `core/migrations/pages/rule_designer.html` non caricabile da Django: ignorato dal guardrail.)*

### DPI - Copilota AI (Ondata 3.3, F1b): pulsante «Proponi DPI» nel report conformità

- **[feat/ux/test] `dpi/templates/dpi/pages/report_conformita.html`, `dpi/tests.py`, `docs/ai/GUIDA_AI.html`, `README.md`**: UI del copilota DPI. Nuova **card «🦺 Copilota DPI»** nella pagina **Report conformità** (contesto mansionario, gestore), con campi **mansione** (pre-compilata con quella del dipendente selezionato, se presente) + **note** e pulsante **«Proponi DPI»** che chiama `dpi/api/copilota-dpi/` (vanilla JS + `fetch`, CSRF via data-attr, nessun React). Mostra il set proposto in **tabella** (categoria, tipi, **obbligatoria**, motivazione) con avviso «rivedi e firma»; messaggio chiaro se l'AI è offline (mostra solo le obbligatorie). **Nessun salvataggio**: il gestore decide e crea le richieste con i flussi esistenti. Output del modello **escapato** prima dell'inserimento in pagina (anti-XSS). Smoke test sul render della card; `DpiCopilotaTests` **6/6 verdi**. Guida HTML a **v1.5** (Copilota DPI nei copiloti per-modulo), README aggiornato. Backend immutato da F1.

### DPI - Copilota AI: proposta set DPI per mansione (Ondata 3.3, F1 backend), validata sul catalogo

- **[feat/test] `dpi/ai_copilota.py` [nuovo], `dpi/views.py`, `dpi/urls.py`, `dpi/tests.py`**: copilota basato sull'AI on-premise (`ai_assistant.services.chat_with_ollama`) che dalla **mansione** (+ note su attività/rischi) propone un **set di DPI**. **Vincolo rispettato**: l'AI **propone**, il gestore rivede e firma — il modulo `ai_copilota.py` **non scrive nel DB** e non crea richieste (`proposto=True`). **Base deterministica = catalogo reale**: i DPI proposti sono **validati contro `CategoriaDPI`/`TipoDPI` attivi** (categorie e tipi fuori catalogo scartati, mai inventati) e le **categorie obbligatorie da mansionario** (`CategoriaDPI.obbligatoria_mansionario`) sono **sempre incluse** (anche se l'AI le omette o è offline). La mappa mansione→DPI è la parte proposta dall'AI, vincolata al catalogo. **Fail-safe**: AI giù ⇒ solo le obbligatorie, `ai_disponibile=False`. Nuovo endpoint **`api_copilota_dpi`** (`POST /dpi/api/copilota-dpi/`, `@login_required`, gated `_is_gestore` → **JSON 403** se non gestore); carica il catalogo attivo + obbligatorie, chiama il builder, ritorna JSON. **Audit solo-metadati** (`dpi_copilota`: mansione_chars, dpi_count, obbligatorie_count, ai_disponibile). 5 test (`DpiCopilotaTests`): proposta valida con scarto fuori-catalogo + filtro tipi, fail-safe solo-obbligatorie, endpoint 403 non-gestore / 200 gestore (AI mockata) / 400 mansione vuota. **F1 = solo backend (nessuna UI)**; pulsante «Proponi DPI» in F1b. Go-live prod: `AiToolPrivacyReview` key `dpi_copilota`. Nota: non esiste (oggi) una tabella rischio→DPI nel modulo; quando arriverà il RAG Sicurezza/DVR (Ondata 2.2) il copilota potrà anche citare il DVR. Nessuna modifica ad altri endpoint, ad ACL o ai modelli.

### Assistente AI - Report PDF (Ondata 4, F1b): pulsante in chat + stile NOVICROM HUB

- **[feat/ux/test] `ai_assistant/templates/ai_assistant/chat.html`, `ai_assistant/ai_report.py`, `ai_assistant/tests.py`, `docs/ai/GUIDA_AI.html`, `README.md`**: UI + restyle del report. **Pulsante «📄 Report PDF»** nell'header della chat (vanilla JS): prende come argomento l'**ultimo messaggio utente** (o l'input corrente, o lo chiede), chiama `api/report/` via `fetch`, riceve il **blob PDF** e lo **scarica** (object URL + `<a download>`); spinner durante la generazione, messaggio chiaro se l'AI è giù/disabilitata. **Restyle del PDF sullo stile del portale** (`render_report_pdf` riscritto su `canvas` come i PDF ticket): **band navy** con wordmark NOVICROM HUB + **accento arancio**, **sezioni in band cyan** maiuscolo, bullet cyan, **footer su ogni pagina** (linea + «generato il… · disclaimer» + n. pagina), **paginazione automatica** con mini-header di continuazione; palette del design system (navy `#0c2545`, cyan `#1f87cd`, orange `#ff6b00` + neutrali condivisi). L'output del modello è reso con `canvas.drawString` (testo letterale, nessuna interpretazione di markup → niente injection) dopo aver tolto i marcatori markdown. 2 test aggiunti (render in stile + `data-ai-report`/url nel render della pagina chat); `AiReportTests` **7/7 verdi**. Guida HTML a **v1.4** (capacità report + esempio), README aggiornato. Backend `genera_report` immutato da F1.

### Assistente AI - Generatore di report PDF "su qualsiasi argomento" (Ondata 4, F1 backend), ancorato ai dati autorizzati

- **[feat/test] `ai_assistant/ai_report.py` [nuovo], `ai_assistant/views.py`, `ai_assistant/urls.py`, `config/settings/base.py`, `ai_assistant/tests.py`**: l'assistente può ora **generare un report PDF scaricabile** su un argomento libero, ma **ancorato allo stesso contesto autorizzato della chat** — niente report a testo libero che inventa. `ai_report.genera_report(request, topic)` passa il topic per `build_runtime_context` (tool live **ACL-gated**) + RAG/SGI e chiede al modello un report **strutturato basato SOLO su quel contesto**, che **cita le fonti** (`tool:*`/SGI) e dichiara «non disponibile» se i dati mancano (**read-only**, niente DB/scrittura, **fail-safe**: AI giù → nessun PDF). `render_report_pdf()` (reportlab, self-contained) produce il PDF con header NOVICROM HUB + titolo + data/richiedente, corpo (markdown→flowables con **escape dell'output del modello** prima del markup, anti-injection come in chat), blocco **Fonti** e footer **«Bozza generata dall'AI — verifica i dati prima di condividere; l'AI propone, l'umano firma»**. Nuovo endpoint **`api_genera_report`** (`POST /assistente-ai/api/report/`, `@login_required` + rate-limit) che risponde col **PDF in download** (`Content-Disposition: attachment`); **audit solo-metadati** (`ai_report`: topic_chars, n. fonti, had_context, formato, elapsed, riepilogo tool — niente contenuto). Nuovo setting `OLLAMA_REPORT_TIMEOUT_SECONDS` (default 120). 6 test (`AiReportTests`): report ancorato al contesto (fonti tool+SGI), fail-safe AI offline, renderer ritorna `%PDF`, endpoint 200 PDF attachment, topic vuoto → 400, AI giù → 502. **F1 = solo backend**; il pulsante «Genera report PDF» in chat arriva in F1b. Go-live prod: `AiToolPrivacyReview` key `ai_report`. Nessuna modifica ad ACL, ad altri endpoint o al comportamento della chat.

### Assistente AI - Latenza/robustezza routing: timeout breve per gli embeddings della query (degrado rapido a keyword-only)

- **[perf/test/docs] `ai_assistant/services.py`, `ai_assistant/tools.py`, `config/settings/base.py`, `ai_assistant/tests.py`, `docs/ai/RAG_SGI_ROLLOUT.md`, `README.md`**: il **routing semantico dei tool** embedda la query a **ogni messaggio**; finora usava `OLLAMA_EMBED_TIMEOUT_SECONDS` (30-60s) → se l'endpoint embeddings (TEI/Ollama) era lento/giù **ogni chat** poteva pagare il timeout pieno prima di degradare a keyword-only. Aggiunto un **timeout breve dedicato** `AI_TOOL_ROUTING_EMBED_TIMEOUT_SECONDS` (default **6s**): `embed_texts`/`_compute_embeddings`/`_openai_embed_texts`/`_ollama_embed_texts` accettano ora un parametro `timeout` opzionale (default = comportamento attuale, i path di warm/index restano sul timeout lungo) e `_rank_domains` lo passa per la query. Risultato: un TEI lento o una soglia mal tarata **non rallentano più la chat** (fail-safe a keyword-only in ≤6s). **Qualità (doc, da misurare sull'hardware)**: aggiunta in `RAG_SGI_ROLLOUT.md` la **procedura di ritaratura delle soglie di routing per `bge-m3`** (le attuali 0.70/0.04 sono per `nomic-embed-text`) via `ai_eval --json/--rag/--rag-sgi`, senza cambi alla cieca dei valori. 4 nuovi test (`EmbedTimeoutTests`: `embed_texts` inoltra il timeout, override openai applicato, default al setting, `_rank_domains` usa il timeout breve); aggiornate le 2 fake `_ollama_embed_texts` dei test di routing per accettare il kwarg `timeout`. Suite mirata 15/15 verde. Nessun cambio al comportamento del retrieval o del routing (solo il timeout della chiamata).

### Assistente AI - Ottimizzazione GPU/modelli: cap generazione + runbook tuning Ollama (max_loaded=1 con TEI, flash attn, KV q8_0)

- **[perf/docs/test] `config/settings/base.py`, `docs/ai/OLLAMA_GPU_TUNING.md` [nuovo], `docs/ai/00_INDEX.md`, `ai_assistant/tests.py`, `README.md`**: ottimizzazione dell'uso GPU dell'Assistente. **(1) Cap di generazione**: `OLLAMA_NUM_PREDICT` default **0 → 1536** — prima il portale non passava alcun cap (`>0` richiesto) e una risposta runaway poteva tenere il worker per tutto il timeout e allocare KV-cache; 1536 token restano ampi per risposte discorsive, override-abile da `.env`. **(2) Runbook GPU** `docs/ai/OLLAMA_GPU_TUNING.md`: topologia reale (A4000 16GB su PCGAVANCINI: Ollama chat `qwen2.5:14b` ~9GB + TEI `bge-m3` ~2-3GB), budget VRAM, e le **env server-side raccomandate** con rationale — **`OLLAMA_MAX_LOADED_MODELS=1`** (gli embeddings sono migrati su TEI ⇒ Ollama ospita solo la chat: le note che parlavano di `=2` erano stali e riservavano VRAM inutilmente), `OLLAMA_FLASH_ATTENTION=1` (prefill RAG più rapido, meno VRAM), `OLLAMA_KV_CACHE_TYPE=q8_0` (KV-cache quantizzata → forte risparmio VRAM), `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_KEEP_ALIVE=30m`; come applicarle via **NSSM** + verifica (`tools/ai_healthcheck_prod.ps1`, `ollama ps`, `nvidia-smi`) + rollback. Aggiornati i commenti stali in `base.py` (TEI ⇒ max_loaded=1) e pointer in `00_INDEX.md`/README. **Le env server-side si applicano su PCGAVANCINI e si validano con `nvidia-smi`/latenza** (non dal repo): il runbook è la guida. 3 test (`OllamaTuningTests`): `num_predict` nel payload quando >0, omesso a 0, provider Open WebUI senza `options`/`keep_alive`. Nessun cambio al modello chat, ad ACL o al comportamento della risposta.

### Tickets - Copilota AI (Ondata 3.1, F1b UI): pulsante nel dettaglio gestione + pre-compilazione (non salva)

- **[feat/ux/test] `tickets/templates/tickets/pages/gestione_detail.html`, `tickets/tests.py`, `docs/ai/GUIDA_AI.html`, `README.md`**: UI del copilota ticket. Nuova **card «Copilota AI»** nel pannello destro del dettaglio gestione (solo a ticket non chiuso), con pulsante **«Proponi triage»** che chiama `tickets/api/copilota/` (vanilla JS + `fetch`, nessun React). Il pannello mostra la proposta (categoria, priorità, sicurezza, assegnatario, motivazione, bozza di risoluzione) con avviso «rivedi e firma» e due azioni **read-only**: «Usa assegnatario» (imposta la select `#assign-membro` se presente in elenco) e «Usa bozza nel commento» (riempie `#commento-testo`); **nessuna delle due salva** — il gestore conferma con i pulsanti esistenti («Salva assegnazione», «Aggiungi commento»). Messaggio chiaro se l'AI non è disponibile (`ai_disponibile=false`). Smoke test (`test_gestione_detail_shows_copilota_button`) sul render del pulsante/card; suite `TicketCopilotaTests` **7/7 verdi**. Guida HTML a **v1.3** (sezione «Copiloti per-modulo») e README aggiornati: la capacità è ora user-visibile. Nessuna modifica al backend del copilota (immutato da F1), ad ACL o ai modelli.

### Tickets - Copilota AI di triage (Ondata 3.1, F1 backend): categoria/priorità/assegnatario/bozza proposti, read-only

- **[feat/test] `tickets/ai_copilota.py` [nuovo], `tickets/views.py`, `tickets/urls.py`, `tickets/tests.py`**: copilota basato sull'AI on-premise già integrata (`ai_assistant.services.chat_with_ollama`, Ollama) che dal **testo del ticket** (titolo + descrizione) propone in **triage**: `categoria`, `priorita`, `incide_sicurezza`, `assegnatario` (dal team gestori) e una **bozza di risoluzione**. **Vincolo invalicabile rispettato**: l'AI **propone**, il gestore rivede e firma — il modulo `ai_copilota.py` **non scrive nel DB** e non esegue assegnazioni/transizioni (ogni output ha `proposto=True`); l'applicazione resta sui salvataggi esistenti (`api_assegna`/`api_stato`). **Validazione server-side** dei valori proposti: la `categoria` deve appartenere a `get_categorie(tipo)`, la `priorita` all'enum `PrioritaTicket`, l'`assegnatario` al `TicketImpostazioni.team_gestori`; valori fuori lista sono scartati (campo vuoto), mai inventati; `incide_sicurezza=True` forza `priorita=URGENTE` (stessa regola del modello `Ticket`). **Fail-safe** (AI offline ⇒ `ai_disponibile=False`, proposta vuota). Nuovo endpoint **`api_copilota_triage`** (`POST` JSON, rotta `tickets/api/copilota/`) gated da `_tickets_gestione_required` (triage = azione gestionale, coerente con `api_assegna`); **audit solo-metadati** via `log_action` (`ticket_copilota_triage`: tipo, ai_disponibile, ha_categoria, ha_assegnatario), nessun prompt/testo salvato. 6 test (`TicketCopilotaTests`): proposta valida, scarto valori fuori lista, sicurezza→URGENTE, fail-safe AI offline, endpoint 403 non-gestore / 200 gestore con AI mockata. **F1 = solo backend (nessuna UI)**; il pulsante «Copilota» sul dettaglio gestione arriva in F1b. Go-live prod: `AiToolPrivacyReview` key `tickets_copilota` (passo di processo). Nessuna modifica ad altri endpoint, ad ACL o ai modelli.

### Assistente AI - Tool "Carichi macchina": stato per macchina, intento libere/sovraccariche, filtro reparto, sintesi

- **[feat/test] `ai_assistant/tools.py`, `ai_assistant/tests.py`, `docs/ai/GUIDA_AI.html`**: giro di miglioramento del tool `_carichi_context` (resta read-only, ACL=login, audit metadata-only). **(1) Etichetta di stato** per macchina derivata dalla %: SOVRACCARICA (≥100), quasi piena (85-99), ok (40-84), scarica (<40), libera (<1); ogni riga mostra anche le **ore ancora libere** (`capacita-carico`). **(2) Sintesi in testa**: quante macchine sovraccariche / quasi piene / scariche sul parco (o sul reparto filtrato). **(3) Intento della domanda**: «macchine **libere** / capacità disponibile / meno cariche» ordina dalle meno sature (`filtro=libere`); «**sovraccariche** / colli di bottiglia / più cariche» dalle più sature; default top-8 più sature. **(4) Filtro per reparto/categoria** dal testo (torni, torni fresa, alesatrici, 4/5 assi) con la sigla più specifica che vince (`filtro=...+reparto=<cat>`). Il **gate** `_wants_carico_context` riconosce ora anche «macchine libere/disponibili/scariche/sovraccariche» senza la parola "carico/saturazione" (mantenendo la precisione: "macchina" da sola non basta; "batteria scarica" non attiva). Aggiornati keyword set (`sovraccaric`, `scariche`), seed di routing (`libere`/`sovraccariche`) e rimosso il set inutilizzato `_CARICO_KEYWORDS`. 3 nuovi test (etichette+sintesi, intento libere ordina i meno carichi, filtro reparto) + assert sul gate; `CarichiMacchinaContextTests` **7/7 verdi**. Guida HTML aggiornata a 1.2 (sezione tool + esempi). Nessuna modifica al modulo carichi, ad altri tool o all'ACL.

### Assistente AI - Tool live "Carichi macchina" (Ondata 1.2) + guida HTML del funzionamento AI

- **[feat/test] `ai_assistant/tools.py`, `ai_assistant/tests.py`, `docs/ai/GUIDA_AI.html` [nuovo], `docs/ai/00_INDEX.md`**: nuovo **tool runtime** che risponde sui **carichi/saturazione delle macchine** della settimana corrente leggendo `gestione_carichi_macchina` (read-only). **Gate keyword** `_wants_carico_context` con guardia di precisione: serve un **segnale forte** (`carico/carichi/saturazione/saturo/capacità/occupazione`) — la sola parola "macchina" **non** attiva il tool (resta agli asset/anomalie). **Funzione** `_carichi_context`: finestra = settimana lavorativa corrente (lun-ven via `_lunedi`/`_giorni_lavorativi`), calcola la saturazione con `saturazione.calcola_saturazione` (funzione pura) e espone per macchina **% saturazione, ore carico/capacità, n. lavori pianificati**, più totale officina e per reparto; filtra sulla **macchina citata** (codice asset o sigla d'officina via `MacchinaAlias`), altrimenti mostra le **8 più sature**. **Nessun dettaglio commessa/cliente/pezzo.** **ACL**: il modulo carichi è oggi protetto solo da `@login_required` (binding ACL v2 al Passo 6) → il gate del tool rispecchia quel confine (`request.user.is_authenticated`), con `TODO` per stringere a `user_can_modulo_action` quando arriverà il binding canonico. Registrato in `RUNTIME_TOOLS`, nel catalogo governance `RUNTIME_TOOL_CATALOG` (key `carichi_macchina`, `privacy_note` aggregati-only), in `_RUNTIME_PRIORITY_BY_TOOL` (55) e come **seed di routing semantico** (`"carichi"`). **Audit solo-metadati** (`tool, allowed, scope=settimana_corrente, filtro, row_count`). 4 test (`CarichiMacchinaContextTests`): precisione del gate, aggregazione settimana con n. lavori, filtro per macchina citata, accesso negato anonimo + **assenza di dati commessa** nell'output. **Guida HTML** `docs/ai/GUIDA_AI.html` (autoconsistente, da tenere aggiornata a ogni nuova capacità AI): architettura on-premise (Ollama+TEI), RAG SGI citabile, tabella tool runtime (incl. carichi), esempi, limiti/governance, roadmap a ondate; pointer nell'indice `docs/ai/00_INDEX.md`. Nessuna modifica al modulo carichi, ad altri tool, ad ACL o al routing degli altri domini.

### Assistente AI - Risposte più concrete e discorsive (prompt di sistema + contesto)

- **[tune] `config/settings/base.py`**: il prompt di sistema di default (`OLLAMA_CHAT_SYSTEM_PROMPT`) ora chiede risposte **chiare e discorsive** (spiega il contenuto, contestualizza, breve esempio pratico o passi concreti, niente risposte telegrafiche) **mantenendo tutte le regole anti-invenzione** (priorità al CONTESTO LIVE, niente dati inventati, "non ho accesso diretto" sui dati operativi senza tool live, no credenziali/dati sensibili) e aggiungendo la **citazione SGI** nel formato leggibile «MT CN 04 Rev.0 §5.1». Aumentato il contesto passato al modello — `OLLAMA_RAG_MAX_CHUNKS` 4→**6**, `OLLAMA_RAG_MAX_CONTEXT_CHARS` 5000→**7000** — così l'assistente ha più materiale per essere concreto, e la temperatura `OLLAMA_CHAT_TEMPERATURE` 0.2→**0.3** per un tono più naturale senza perdere precisione. Misurato su domanda SGI reale ("come si valutano i fornitori?"): prima 3 righe asciutte con citazioni grezze; dopo risposta strutturata con passi + esempio pratico + citazioni pulite + più sezioni pertinenti recuperate (MT CN 04 §5.1/5.1.2/5.1.3, MT CN 16 §6.7, MT CN 68 §8.3). Tutto override-abile via `.env` (setting `OLLAMA_CHAT_SYSTEM_PROMPT` e i numerici); per risposte brevi resta la preferenza utente "sintetico". Solo settings/default, nessuna modifica al codice.

### Assistente AI - Backend embeddings configurabile (TEI/fastembed) + fix chunk oversize (sblocca l'ibrido sul corpus SGI pieno)

- **[feat/fix/test] `ai_assistant/services.py`, `config/settings/base.py`, `ai_assistant/tests.py`**: due interventi che **sbloccano la ricerca semantica ibrida sull'intero corpus SGI** (9042 chunk), prima impossibile. **(1) Bug chunk oversize** (`_split_long_section`): i PDF spesso estraggono il testo come **un unico blocco senza righe vuote** → lo splitter produceva un chunk gigante (osservato: **42.182 caratteri**) che **sfonda il limite di token del modello di embedding** → l'endpoint (TEI **e** Ollama) restituisce errore/va in tilt → l'intero warm falliva. Fix: i paragrafi più lunghi di `max_chars` vengono **spezzati** (nessun chunk oltre il limite). Era la causa reale dei "blocchi" del server durante la vettorializzazione. **(2) Backend embeddings configurabile** (`RAG_EMBED_BACKEND`): oltre a `ollama` (default), ora `openai` (endpoint HTTP **OpenAI-compatibile**: TEI / Infinity / vLLM / LM Studio su GPU) e `fastembed` (in-process, CPU, ONNX — dipendenza opzionale lazy, fail-safe). Un solo punto di calcolo (`_compute_embeddings`) instrada al backend; `embeddings_enabled()` aggiornato (con `openai`/`fastembed` è indipendente dal provider chat). Nuovi settings: `RAG_EMBED_BACKEND`, `RAG_EMBED_FASTEMBED_MODEL`, `RAG_EMBED_OPENAI_BASE_URL`/`_MODEL`/`_API_KEY`. **Risultato reale**: con **TEI** (bge-m3 su RTX A4000) i 9042 chunk SGI sono vettorializzati in **~115s**, `embeddings_ready: true`; il retrieval ibrido cita la **sezione giusta per significato** (es. «documento per una deroga» → MT CN 16 §6.2.2.1 Deroga; «come valuto i fornitori» → MT CN 04 §5.1 Selezione Fornitori). 7 nuovi test (fix chunk oversize, backend openai parse/fail-safe, `embeddings_enabled` per backend; 3 test di routing/ibrido fissati su `RAG_EMBED_BACKEND="ollama"`). Suite `ai_assistant` 106/106. Nessuna nuova dipendenza obbligatoria (fastembed è opt-in).

### Procedure Refresh - Import del corpus documentale SGI da share di rete (per il RAG dell'assistente)

- **[feat/test] `procedure_refresh/management/commands/import_sgi_da_share.py` [nuovo], `procedure_refresh/management/__init__.py` + `commands/__init__.py` [nuovi], `procedure_refresh/tests.py`, `config/settings/base.py`, `ai_assistant/services.py`**: nuovo comando **`import_sgi_da_share`** che registra i PDF della cartella SGI (file server) come `ProcedureDocument` + `ProcedureRevision` corrente (`source_type=fileserver`, `source_path` UNC), così l'Assistente AI li indicizza e li cita (il RAG legge poi i PDF; il comando non ne estrae il testo). **Solo revisioni correnti**: esclude sempre la sottocartella `SUPERATO` (documenti obsoleti) e tratta ogni file dell'albero attivo come revisione corrente. **L'AI propone, l'umano firma**: `--dry-run` di default, scrive solo con `--apply`. **Parser dei nomi** best-effort sulla convenzione reale `<CODICE> Rev.<n>_<Titolo>.pdf` (es. `MT CN 06 Rev.21_Risorse Umane.pdf`): riconosce MT/MTSI/IDOR/IDPR, la modulistica `MOD.xxx` (col punto), i **sotto-numeri** (`MT CN 125_10`, distinto da `MT CN 125`) e i numeri a 4 cifre (`MT CN 2710` ≠ `MT CN 271`); gli allegati hanno **codice distinto** (`IDOR CN 01 Allegato A`). I nomi non riconosciuti (Piani Qualità `PdQ`, `DVR/PEI`, `MO-ID/MOE`, standard esterni…) non vengono scartati ma importati con un **fallback** (codice ricavato dal nome) → "tutto quanto". Flag `--solo-procedure` per escludere la modulistica, `--root`/`--json`/`--limit`. Codice univoco entro i 50 char di `ProcedureDocument.code` (troncamento+hash sui fallback lunghi); dedup per codice con report dei conflitti (tiene la revisione più alta). Calcolo `file_hash` (sha256) in `--apply` per la cache testo del RAG. Nuovo setting `PROCEDURE_REFRESH_SGI_SHARE_ROOT` (default vuoto → obbligatorio `--root`). **Robustezza embedding** (`ai_assistant/services.py::_embeddings_for_chunks`): la cache embeddings è ora **incrementale per batch** — su corpora grandi (migliaia di chunk) una singola batch fallita non butta via il lavoro fatto, e i run successivi/notturni convergono (utile in prod con DatabaseCache). Aggiunti **retry per batch** (`OLLAMA_EMBED_RETRY`, default 2) e **micro-pausa tra batch** (`OLLAMA_EMBED_BATCH_PAUSE_MS`, default 0) per superare i timeout transitori e non saturare un server GPU condiviso/poco capiente — da abbinare a `OLLAMA_NUM_PARALLEL=1` lato Ollama (limita i contesti concorrenti in VRAM, causa reale dei blocchi sotto carico di embedding). Esito reale sulla share aziendale (dry-run): 254 PDF → **248 documenti** (84 procedure MT/MTSI/IDOR/IDPR + 143 modulistica MOD + 21 fallback), `SUPERATO` (64) escluso. 8 test (parser MT/sotto-numeri/MOD/None/fallback, comando dry-run/apply/esclusione SUPERATO/--solo-procedure). Nessuna modifica ad ACL/routing/modelli.

### Assistente AI - RAG SGI (F1+F2+F3): loader documenti SGI citabili + regola di citazione + comando di indicizzazione + stemming/golden recall@k

- **[feat/test] `ai_assistant/services.py`, `ai_assistant/tasks.py`, `ai_assistant/management/commands/index_sgi_documents.py` [nuovo], `ai_assistant/management/commands/ai_eval.py`, `ai_assistant/eval/golden_sgi.jsonl` [nuovo], `ai_assistant/tests.py`, `config/settings/base.py`, `requirements.in`/`requirements.txt`**: il Copilot indicizza ora il **corpus documentale SGI** già presente nel portale, rendendolo citabile in chat con codice/revisione/sezione. **F1 — loader**: nuovo `_load_sgi_document_chunks()` (gemello di `_load_curated_knowledge_chunks`), agganciato in `_load_knowledge_index()` dietro flag `OLLAMA_RAG_SGI_ENABLED` (default True); la *signature* della cache indice è estesa con `_sgi_documents_signature()` (count + max `updated_at` per fonte) così l'indice si rigenera quando cambia un documento SGI. Indicizza **solo le revisioni in vigore**: `Specifica` in stato S3 `in_validita` e `ProcedureRevision.is_current=True` su documento attivo (`document.is_active`). **Citazione stabile**: `source` = handle `spec:{codice}#rev{revisione}` / `proc:{code}#rev{revision_code}`, `title` = `{codice} Rev.{rev} — §{sezione}` (chunking **sezione-aware** su heading numerati via `_SGI_HEADING_RE`, riuso di `_split_long_section` per split lungo+overlap). **Estrazione PDF** con helper locale `_extract_pdf_text()` (pattern pymupdf, `ai_assistant` resta autonomo: nessun import cross-app), cachata per `file_hash` su DatabaseCache; per la `Specifica` (senza hash persistito) l'hash è derivato dai byte e a sua volta cachato per `(pk, updated_at)`, così i rebuild a caldo non rileggono il file. **On-premise**: per le procedure si legge solo il **file server locale** (`source_type=fileserver`, path `.pdf` esistente); SharePoint e PDF illeggibili **ripiegano sui metadati** (codice/titolo/categoria/descrizione) restando comunque citabili. **F2 — citazione + warm**: il blocco RAG di `build_ollama_messages` impone, quando una fonte inizia con `spec:`/`proc:`, di citare codice + revisione + sezione come nel titolo (es. «MT CN 06 Rev.7 §4.2») e di dichiarare «Non disponibile nei documenti indicizzati» se il contesto SGI non basta — comportamento invariato sugli altri domini (regola condizionata al prefisso). Nuovo `services.index_sgi_documents()` + management command **`index_sgi_documents`** (`--json`, `--fail-on-error`) + task django-q2 `tasks.run_index_sgi_documents` che forzano la build dell'indice e il warm/caching degli embeddings SGI (la prima build è la più costosa, poi è in cache). **Fail-safe assoluto**: app assente, PDF corrotto/mancante o errore Ollama saltano il singolo documento senza mai bloccare una risposta (degrado a BM25-only / chunk saltato). Nuovi settings con default sicuri: `OLLAMA_RAG_SGI_ENABLED`, `OLLAMA_RAG_SGI_MAX_SPECS` (300), `OLLAMA_RAG_SGI_MAX_PROCS` (300), `OLLAMA_RAG_SGI_MAX_PDF_CHARS` (200000), `OLLAMA_RAG_SGI_TEXT_CACHE_TTL` (30g); il chunking riusa `OLLAMA_RAG_CHUNK_CHARS`/`_OVERLAP_CHARS`. **F3 — ottimizzazione misurata**: **stemming italiano opt-in** in `_tokenize` (Snowball via `snowballstemmer`, pure-python) dietro `OLLAMA_RAG_STEMMING_ENABLED` (default **False**), applicato identico a query e chunk (timbri/timbro/timbrare → radice `timbr`) e **fail-safe** se la dipendenza manca; **golden set SGI** `eval/golden_sgi.jsonl` (domanda → frammento documento atteso) + nuova modalità **`ai_eval --rag-sgi`** che misura recall@k / MRR / rank-1 sul corpus SGI (summary con `stemming`/`sgi_chunks`); il modello di embedding resta parametrizzato (`OLLAMA_EMBED_MODEL`, confronto `bge-m3` 1024d vs `nomic-embed-text`) con cache vettori per `(modello, content-hash)` e cosine **dimension-safe**. **Numeri misurati**: golden SGI seminato recall **3/4 → 4/4** e MRR **0.75 → 1.0** con stemming (query flessa «timbrare/presenze»); KB curata (26 golden) **nessuna regressione** (26/26, MRR 0.981 con e senza stemming). Nuovo setting `OLLAMA_RAG_STEMMING_ENABLED` (False); dipendenza `snowballstemmer>=2.2`. 15 regressioni dedicate (chunk citabile + sezione §, esclusione revisioni non correnti, fallback metadati, cache per file_hash con lettura/estrazione una sola volta, opt-out via setting, procedura corrente con esclusione documento dismesso, regola di citazione nel prompt, comando che riporta i chunk SGI, skip a RAG disattivo, task fail-safe, stemming unifica/no-op/fail-safe, `ai_eval --rag-sgi` recall, stemming recupera query flessa); Ollama/pymupdf/embeddings mai toccati dalla rete. Suite `ai_assistant` 102/102. Nessuna modifica al comportamento sugli altri domini, ad ACL, routing o privacy dei tool. **F4 — rollout** (`automazioni/schedules.py`, `docs/ai/RAG_SGI_ROLLOUT.md` [nuovo], `docs/ai/00_INDEX.md`): registrata la schedule django-q2 **`ai_index_sgi_documents`** (CRON 03:30, fail-safe, si attiva al prossimo `setup_q_schedules`) per il warm notturno dell'indice + embeddings SGI; runbook di rollout (settings con default, pull modello embedding `nomic`/`bge-m3`, stemming opt-in misurato, `index_sgi_documents`, verifica funzionale) in `docs/ai/RAG_SGI_ROLLOUT.md` + pointer nell'indice AI.

### Gestione Carichi Macchina - Gantt operativo: turni per-macchina, drag robusto, pannello dettaglio/modifica, info macchina

- **[feat/fix/ux/test] `gestione_carichi_macchina/views.py`, `urls.py`, `templates/.../gantt.html`, `templates/.../excel.html`, `templates/.../partials/_cella_form.html`, `tests_views.py`**: revisione operativa del Gantt (la pagina usata per «muovere») su feedback utente.
  - **Drag&drop robusto**: il cambio macchina scatta **solo se il cursore esce verticalmente dalla riga** di origine → niente più commesse «sparpagliate» su altre macchine durante un drag orizzontale con barre sovrapposte.
  - **Cascata indipendente per turno**: lo spostamento a catena resta confinato a `(macchina, turno)` (il 1° turno non muove 2°/notturno); messaggio di conferma esplicito.
  - **Barra strumenti collassabile** (filtri + KPI saturazione): di default **chiusa** → più spazio al Gantt.
  - **Turni per-macchina nella cella**: il toggle turni è ora accanto al nome macchina (pulsante «▾ turni»); espandere una macchina **non apre** i turni delle altre (`?turni=<id,...>`). Default: 1°+2° turno **uniti** + notturno separato se presente.
  - **Cella macchina interattiva**: il **nome macchina è cliccabile** → riquadro info (categoria, attacco, assi, turni, stato, saturazione).
  - **Pannello laterale destro (#)**: clic su una **commessa** apre un drawer con i dettagli e, se l'utente ha i permessi (`can_edit`, hook ACL), il **form di modifica** (testo/qtà/ore/stato/fase) che salva via `cella_edit`.
  - **Coerenza Excel**: stesso default unione T1+T2; nel modale «+ Aggiungi lavoro» dell'Excel è mostrata l'**affinità macchine** (stesso endpoint/partial del «+» cella). Nuovo endpoint `api/pianificazione/<pk>/`. Test: drag/cascata per turno, turni Gantt, dettaglio pianificazione. Suite modulo 80 verde.

### Gestione Carichi Macchina - Turni nel Gantt + cascata indipendente per turno + default unione T1+T2

- **[feat/fix/test] `gestione_carichi_macchina/views.py`, `templates/.../gantt.html`, `tests_views.py`**: portati i **turni anche nel Gantt** (la pagina usata per «muovere») con lo stesso toggle **Turni** (`?turni=1`): OFF = righe per macchina con **1°+2° turno uniti** + notturno su riga separata se presente (com'era nel foglio); ON = righe esplicite 1° turno / 2° turno / notturno solo per i turni che la macchina ha. **Fix di correttezza**: la **cascata** del drag-to-reschedule ora è limitata a **`(macchina, turno)`** — spostare un lavoro del 1° turno **non sposta più** 2° turno/notturno (prima `reschedule` propagava a tutti i turni della macchina). La conferma del drag lo dichiara esplicitamente. Stessa logica di default unione T1+T2 applicata anche alla vista Excel. Test `test_reschedule_cascata_non_tocca_altri_turni` (indipendenza turni) e `test_gantt_turni_flag_mostra_righe`; suite modulo 79 verde.

### Gestione Carichi Macchina - Turni 1°/2°/notturno per riga (flag visualizzazione + config per macchina)

- **[feat/migration/test] `gestione_carichi_macchina/models.py`, `migrations/0002_macchina_ha_secondo_turno_alter_pianificazione_turno.py` (nuovo), `views.py`, `admin.py`, `templates/.../excel.html`, `tests_views.py`**: la vista Excel può mostrare le righe per **turno** (1° turno / 2° turno / notturno). Nuovo flag macchina `ha_secondo_turno` (il 2° turno di giorno non ce l'hanno tutte; il notturno resta `ha_turno_notte`), configurabili **dalle impostazioni** (admin Macchina, anche con edit inline in lista). Aggiunto il valore turno `t2` (`Pianificazione.TURNO_T2`); i valori `giorno`/`notte` esistenti restano validi (**nessuna data-migration**, solo `AddField` + `AlterField` choices, SQL Server-safe). Nuovo **toggle "Turni"** nella toolbar (`?turni=1`): OFF (default) = una riga per macchina con i lavori di tutti i turni uniti (look familiare preservato); ON = sotto-righe 1°/2°/notturno separate **solo per i turni che la macchina ha**. **Indipendenza dei turni**: nella vista Excel le celle sono già per `(macchina, turno, giorno)`, quindi spostare/modificare un lavoro del 1° turno non tocca il 2° (l'eventuale popup di conferma riguarda il *drag con cascata nel Gantt*, follow-up). Modale "Aggiungi lavoro" con i tre turni. Test `test_excel_turni_flag_mostra_righe_turno`; suite modulo 77 verde.

### Gestione Carichi Macchina - Suggerimento macchina per FASE (sgr/fin/rip/ass)

- **[feat/test] `gestione_carichi_macchina/previsioni.py`, `gestione_carichi_macchina/views.py`, `templates/.../partials/_cella_form.html`, `_suggerimento_macchina.html`, `tests_previsioni.py`**: il suggerimento macchina ora è **fase-aware**: sgrossatura/finitura/ripresa/assemblaggio sono lavorazioni diverse e possono andare su macchine diverse anche per la stessa famiglia. `prevedi_macchina` accetta `fase` + `freq_per_famiglia_fase` (retro-compatibile: senza fase resta l'affinità per sola famiglia); nuovo builder `costruisci_indice_macchine_fase()` che ricava la frequenza per `(famiglia, fase)` **dallo storico `Pianificazione`** (niente migrazione). Nel form cella il box «Consigliate» si aggiorna anche al cambio della **fase** (HTMX) e mostra la fase in intestazione. Test `test_fase_cambia_il_ranking` (sgr→m10, fin→m11, fallback su fase senza storico). Suite modulo verde.

### Gestione Carichi Macchina - Suggerimento macchina visibile nel form cella + guida d'uso

- **[feat/ux/test/doc] `gestione_carichi_macchina/views.py`, `gestione_carichi_macchina/urls.py`, `gestione_carichi_macchina/templates/.../partials/_cella_form.html`, `_suggerimento_macchina.html` (nuovo), `templates/.../excel.html`, `gestione_carichi_macchina/tests_views.py`, `docs/gestione_carichi_macchina/GUIDA_UTILIZZO.md` (nuovo), `README.md`**: il suggerimento macchina (scoring pesato load-aware) ora è **visibile nell'UI**. Mentre si compila una cella, se la famiglia è riconosciuta dal testo compare un box **«Consigliate · <famiglia>»** (HTMX, debounce, read-only): per ogni macchina una barra la cui **lunghezza = score** e il cui **colore = carico** (verde libera → ambra → rosso satura), con **●** sulla macchina della cella, nota «non tra le consigliate» quando pertinente e il **perché** nel tooltip (storico/recency/carico, n. lavori, % saturazione). Nuova view `cella_suggerimento` + route `cella/suggerimento/`; helper `_righe_suggerimento_display`. Aggiunta la **guida d'uso** del modulo (`docs/gestione_carichi_macchina/GUIDA_UTILIZZO.md`) con viste, pianificazione, lettura del suggerimento, stima ore, saturazione/rischio ritardo, import e limiti; README rimanda alla guida. Test `test_cella_suggerimento_box` (box per famiglia nota, frammento vuoto se non riconosciuta); suite modulo verde.

### Gestione Carichi Macchina - Suggerimento macchina pesato e load-aware

- **[feat/test] `gestione_carichi_macchina/previsioni.py`, `gestione_carichi_macchina/views.py`, `gestione_carichi_macchina/tests_previsioni.py`**: il suggerimento della macchina per una famiglia passa da **frequenza storica pura** a uno **scoring pesato esplicabile**. `prevedi_macchina` ora accetta (retro-compatibile: senza i nuovi indici resta il ranking storico) i segnali che i dati già contengono — **recency** della storia (`ultima_data`, decadimento esponenziale), **carico attuale** della macchina (1 − saturazione, da `saturazione.calcola_saturazione`) e **stato** (le macchine in `guasto`/`manutenzione` sono escluse) — e ritorna `score`, `componenti` (freq/recency/carico_libero), `saturazione` e `stato`. Nuovi builder `costruisci_indice_recency/_carico/_stato`. Pesi default freq 0.5 / recency 0.2 / carico 0.3 (somma 1, termini in [0,1]). **Motivazione**: l'affinità commessa↔macchina è un problema numerico/categoriale, non testuale (niente BM25); con i dati attuali (la famiglia è un soprannome, il pezzo non ha feature di materiale/tolleranze/attrezzaggio) lo scoring pesato è il passo corretto — il punto a valore più alto è rendere il suggerimento **load-aware** (prima ignorava la saturazione e poteva proporre una macchina già piena). `cosine`/kNN su feature restano una fase 2 da abilitare quando il pezzo avrà feature strutturate. L'endpoint `api/suggerimento-macchina/` espone i nuovi campi; `prob`/`occorrenze`/`codice` preservati (spiegazione LLM invariata). 3 nuove regressioni; suite modulo 73/73.

### Assistente AI - Qualità RAG: KB ampliata, eval recall@k, sorgenti dev/prod allineate

- **[feat/fix/test] `ai_assistant/knowledge/05..09_*.md` (5 nuovi), `ai_assistant/management/commands/ai_eval.py`, `ai_assistant/tests.py`, `config/settings/base.py`, `.env.example`, `django_app/.env.example`, `README.md`**: knowledge base curata su file da 5 a 10 documenti sintetici (zero dati personali), coprendo anagrafica/qualifiche/formazione, anomalie di produzione, tasks/automazioni, un glossario (ratei, ROL, ex festività, OdL, OP, RDC, DPI, near miss, preposto, ACL, SLA) e una FAQ accesso/account; titoli «a forma di domanda» per il boost BM25. Nuova modalità `ai_eval --rag` che misura il retrieval documentale su un golden set `domanda → fonte attesa` con metriche **recall@k, MRR e #rank-1** (l'MRR/rank cattura le regressioni di *ordinamento* che il recall@k non vede) più un **report di copertura KB** (file di knowledge non esercitati da alcuna golden); opzioni `--top-k`, `--sources` (misura prod-like), `--json`; output ASCII-safe per console Windows, offline-friendly (BM25). Golden set portato a **26 casi** con parafrasi colloquiali (robustezza BM25); i due miss emersi (`guasto del computer`, `password dimenticata`) sono stati risolti **arricchendo la KB** con quei sinonimi (loop golden→contenuto). Default `OLLAMA_RAG_SOURCE_PATHS` allineato a `README.md,django_app/ai_assistant/knowledge` (no-op in prod dove `docs/` è escluso; in dev non soffoca più la KB). **Bug latente corretto**: il `.env` impostava `README.md,docs/ai` (senza `knowledge/`) → KB curata mai usata; corretto `.env` dev + `.env.example`. **Operativo**: verificare/allineare il `.env` di prod (`config\.env`), altrimenti la KB resta inutilizzata in prod. **Metriche**: recall@4 **26/26**, MRR 0.98 (KB-only) / 0.94 (prod-like); copertura KB completa. Aggiunta inoltre la modalità **`ai_eval --rag-live`** che valuta la copertura della KB sulle **domande reali** memorizzate (`AiChatFeedback.prompt`, opz. `AiKnowledgeEntry` con `--include-faq`, `--down-only` per i soli feedback negativi) e segnala i *gap* (domande che non recuperano alcun file di knowledge curato) come candidati per nuovi contenuti/golden — da eseguire dove ci sono feedback raccolti (es. produzione); **non scrive nulla e non committa testo utente** (privacy). `--rag-live` mostra inoltre lo **score BM25** del miglior chunk KB recuperato e accetta **`--min-score`** (default 0.0): sotto soglia il match è classificato *gap debole* (recupera un file KB ma per overlap coincidente/irrilevante), così si scremano i falsi "coperti"; gli score sono sempre mostrati per calibrare la soglia sulla distribuzione reale. Suite `ai_assistant` 87/87. Nessuna modifica ad ACL, routing o privacy dei tool.

### Admin Portale/Core - gestione template PDF

- **[feat/ux/test] `admin_portale/views.py`, `admin_portale/urls.py`, `admin_portale/templates/admin_portale/pages/pdf_template_config.html`, `admin_portale/templates/admin_portale/pages/index.html`, `core/pdf.py`, `admin_portale/tests.py`**: nuova pagina `/admin-portale/pdf-template/` nella sezione Configurazione dell'Admin Portale per gestire la grafica comune dei PDF: logo PNG/JPG, colori primario/accento, testo footer e toggle data/ora + numero pagina. La schermata include il pulsante **Anteprima PDF**, collegato a `/admin-portale/pdf-template/preview/`, che apre inline un PDF dimostrativo reale generato con il template salvato. Le preferenze sono salvate in `SiteConfig` con chiavi `pdf_template_*`; `PdfTheme.from_branding()` le applica ai PDF centralizzati con fallback al branding portale. Aggiunte regressioni su render pagina, salvataggio, anteprima PDF e applicazione al tema PDF. Nessuna nuova dipendenza, nessuna modifica ad ACL, permessi, settings o routing globale.

### Anagrafica HR - Import ASR: fase Formazione (corsi + sessioni partecipate)

- **[feat/test] `anagrafica/management/commands/import_asr.py`, `anagrafica/tests.py`**: `import_asr` ora, oltre alle **qualifiche** (lato Salute e Sicurezza), popola una fase **Formazione**: per Corso Lavoratori e abilitazioni crea/**riusa** un `TrainingCourse` con match per titolo (no doppioni; nuovi nel piano "Sicurezza"/categoria "Sicurezza ASR") e importa le **sessioni partecipate** (`TrainingSession` + `TrainingEnrollment` + `TrainingEmployeeRecord` con scadenza). Idempotente, dry-run di default; flag `--no-qualifiche`/`--no-corsi`. Stessa competenza gestibile in due punti (Formazione + Salute e Sicurezza) senza duplicare i dati. Il file ASR **non contiene visite mediche** (verificato): restano manuali. 3 nuove regressioni. Nessuna modifica a modelli/ACL/routing.

### Assets - sotto-navigazione manutenzione e registro OdL

- **[ux/test] `assets/views.py`, `assets/templates/assets/base_shell.html`, `assets/templates/assets/pages/maintenance_hub.html`, `reports_dashboard.html`, `workorder_list.html`, `assets/tests.py`**: le sezioni operative di manutenzione, scadenzario, interventi, report, template report e impostazioni usano ora una sotto-nav comune renderizzata dalla shell Assets, con breadcrumb `Assets / Manutenzione / ...`, tab `Da fare`, `Scadenzario`, `Interventi`, `Report`, `Template report`, `Impostazioni` e azioni rapide `Nuovo intervento`, `Esporta OdL`, `Impostazioni`. La lista OdL apre i dialog da query `?create=1`/`?export=1` e riepiloga i filtri attivi in chip rimovibili. KPI hub/report e righe budget categoria portano a scadenzario o registro OdL gia filtrati; il filtro anzianita apertura include anche `21 giorni`. La logica di attivazione e' centralizzata in `_assets_section_nav`; regressione dedicata su hub, scadenzario, lista OdL, gestione template report, chip filtri e deep-link. Nessuna modifica a dati, ACL, permessi, URL o routing.

### Assets - form template report centrato

- **[ux/test] `assets/templates/assets/pages/report_template_admin.html`, `assets/tests.py`**: `/assets/reports/manage/` centra i form di gestione report in uno stack da data-entry (`rta-form-stack`) con larghezza massima controllata, card form dedicate e layout a due colonne; la lista dei report resta separata sotto, senza occupare lo stesso blocco operativo. Aggiunta regressione sul render delle classi e dei vincoli di centratura. Nessuna modifica a dati, ACL, permessi, URL o routing.

### Anagrafica HR - Mansioni di rischio: setup DPI/visite visibile, nav non doppia

- **[fix/ux/test] `anagrafica/views.py`, `anagrafica/templates/anagrafica/pages/mansioni_list.html`, `.../pages/mansione_requisiti.html`, `.../partials/_safety_subnav.html`, `anagrafica/migrations/0044_impostazioni_no_mansioni_highlight.py` [nuovo], `anagrafica/tests.py`**: tre fix sulla pagina **Mansioni di rischio**. (1) Tolta la **doppia evidenziazione** top-nav (Salute e Sicurezza + Impostazioni): `mansioni_list` rimosso dagli `active_view_names` di Impostazioni (mig. `0044`); resta raggiungibile dalla tab Mansioni di Impostazioni. (2) Aggiunti i **contatori DPI/visite** e il badge livello di rischio su ogni card (calcolati con `prefetch_related`). (3) Promosso il link "Requisiti" da badge grigio a **pulsante primario «⚙️ Requisiti · DPI · visite»**; aggiunto il **livello di rischio (ASR)** ai form crea/modifica mansione + link ai Requisiti dalla modale; ripulita la pagina Requisiti dai riferimenti ai "fattori ereditati" e aggiunto empty-state visite. Regressione dedicata in `SicurezzaHubTests`. Nessuna modifica ad ACL, permessi o routing globale.

### Core/Assets - template PDF condiviso

- **[ux/test] `core/pdf.py`, `assets/views.py`, `assets/tests.py`**: `core.pdf` espone ora helper canvas riutilizzabili per header/footer standard con logo o monogramma, branding portale, palette e paginazione. Gli export PDF tabellari Assets (`Inventario asset`, `Interventi / Work Orders`, `Macchine di lavoro`) usano il template comune con `make_document`, `header_footer_callback` e `data_table`; anche report PDF scheda asset e report mensile manutenzioni macchine usano tema/header/footer condivisi invece di hardcode grafici locali. Aggiunta regressione sull'export PDF asset. Nessuna modifica a dati, ACL, permessi, URL, routing globale o dipendenze.

### Assets - manutenzione operativa e registro interventi

- **[ux/feat/test] `assets/forms.py`, `assets/models.py`, `assets/views.py`, `assets/templates/assets/pages/maintenance_hub.html`, `workorder_list.html`, `workorder_close.html`, `workorder_detail.html`, `assets/tests.py`**: `/assets/manutenzione/` mostra nel tab **Da fare** anche le regole manutenzione effettive che richiedono attenzione (scadute, in warning o senza prima esecuzione), con azione diretta verso creazione OdL o baseline asset. `/assets/workorders/` espone filtri operativi aggiuntivi e una tabella registro con asset/reparto/categoria, responsabili, copertura, tempi e costi; l'export XLSX/PDF usa lo stesso perimetro filtrato. La chiusura OdL registra costi manodopera/materiali/totale, responsabili e allegati finali. Nessuna migration, nessuna nuova dipendenza, nessuna modifica ad ACL, permessi o routing globale.

### Assets - form nuovo intervento

- **[ux/test] `assets/maintenance.py`, `assets/views.py`, `assets/templates/assets/pages/workorder_form.html`, `assets/tests.py`**: `/assets/workorders/new/<id>/?source=workorder_list` riconosce l'origine **Lista interventi**, mostra il ritorno coerente a `/assets/workorders/` e usa una UI da data-entry: la search/topbar della shell viene nascosta su questa pagina, l'header modulo e' ridotto, non ci sono hero/card contesto grandi, resta solo una striscia asset bassa e il form usa un layout compatto a due colonne fino a 1180px, con dati principali a sinistra e note/allegati a destra. Aggiunta regressione dedicata sul render da lista. Nessuna migration, nessuna modifica ad ACL, permessi o routing globale.

### Assets - interventi da lista

- **[ux/test] `assets/views.py`, `assets/templates/assets/pages/workorder_list.html`, `assets/tests.py`**: `/assets/workorders/` mostra ora il pulsante **+ Nuovo intervento** nella toolbar. Il dialog e' centrato, con backdrop e ricerca live su tag/nome/reparto; la scelta asset invia alla route esistente `assets:wo_create`. La view accetta `asset=<id>` e reindirizza al form gia supportato `/assets/workorders/new/<id>/`, preservando parametri come `kind`. Aggiunte regressioni su CTA/dialog ricercabile e redirect. Nessuna migration, nessuna modifica ad ACL, permessi o routing globale.

### Assets - sidebar categorie

- **[fix/test] `assets/views.py`, `assets/templates/assets/base_shell.html`, `assets/templates/assets/pages/asset_list.html`, `assets/tests.py`**: la sidebar Assets ora valuta `active_match` di tipo query string (`asset_category=<id>`, `asset_type=<code>`) con confronto esatto sui parametri GET, non come semplice sottostringa del path. Risolto il falso active quando una categoria ha ID prefisso di un'altra, per esempio `asset_category=60` che si attivava anche su `asset_category=608`. Rimossa anche la persistenza `localStorage` dei gruppi aperti: shell Assets e inventario usano comportamento accordion e cancellano lo stato legacy, evitando che dopo navigazioni come `/assets/workorders/` restino aperti molti gruppi.

### Assets - reportistica manutenzione

- **[feat/test] `assets/services/maintenance_kpi.py`, `assets/views.py`, `assets/templates/assets/pages/reports_dashboard.html`, `assets/tests.py`**: `/assets/reports/` mostra ora KPI manutentivi piu operativi: PM compliance delle regole preventive, budget usato nell'anno corrente e tabella Budget vs actual per categoria con stato in linea/attenzione/oltre budget/budget mancante. Il nuovo servizio read-only `build_maintenance_report_kpis` aggrega scadenzario e costi degli OdL chiusi riusando `AssetMaintenanceBudget`, senza creare dati. Aggiunta regressione sulla dashboard report.

### Anagrafica HR - Mansione di rischio + idoneità alla mansione

- **[feat] `anagrafica/models.py`, `models_rischi.py`, `migrations/0041_*`, `services/mansionario.py` (nuovo), `services/conformita.py`, `services/onboarding.py`, `forms.py`, `views.py`, `urls.py`, `admin.py`, template mansione_requisiti/mansioni_list/rischi_fattori_list/conformita_report/dipendente_create/conformita_panel, `tests.py`**: la `Mansione` diventa l'hub che dichiara i requisiti DPI/Formazione/Visite (M2M diretti + ereditati dai `FattoreRischio` via esposizioni — completa PATCH-RISK-03). Resolver unico `mansionario.py`; lente `idoneita` in `conformita` (mancante=avviso, scaduto=ko, nessuna mansione=na, **nessun blocco**, privacy visite invariata). UI: pagina Requisiti mansione, M2M nel form fattore, riga idoneità in scheda + colonna/filtro/CSV nel report. Onboarding: task derivati dalla mansione (fallback legacy) + notifiche email AMM/caporeparto (fail-open) + formazione sicurezza pregressa in preinserimento. Suite `MansionarioIdoneitaTests` + `OnboardingMansioneRischioTests`.

### Assets - manutenzioni a contatore

- **[fix/test] `assets/models.py`, `assets/maintenance.py`, `assets/tests.py`**: gli OdL collegati a regole manutentive a contatore (`HOURS/KM/CYCLES`) salvano automaticamente `meter_value_at_close` dal relativo `AssetMeter` alla chiusura o alla sincronizzazione di un'esecuzione registrata. Scadenzario e generatore ripartono dal valore dell'ultimo intervento invece che da zero. Aggiunte regressioni dedicate.

### Assets - stile cockpit esteso al modulo

- **[ux] `assets/templates/assets/base_shell.html`, `assets/templates/assets/pages/asset_dashboard.html`, `asset_list.html`, `maintenance_hub.html`, `work_machine_list.html`, `work_machine_dashboard.html`, `device_list.html`**: esteso alle pagine principali del modulo Assets lo stile cockpit gia applicato alla scheda singolo asset. La shell comune aggiorna sidebar, ricerca, header pagina, pulsanti, campi e tabelle; dashboard, inventario, hub manutenzione, elenco macchine, dashboard officina e dispositivi IT ricevono KPI/card con accenti laterali, ombre leggere, radius piu compatti e header meno pesanti. Solo template/CSS, nessuna modifica a view, dati, ACL, permessi, URL o routing.

### Assets - scheda asset piu compatta

- **[ux/test] `assets/templates/assets/pages/asset_detail.html`, `assets/tests.py`**: `/assets/view/<id>/` sostituisce il titolo shell "Dettaglio asset" con il link "Torna indietro" (fallback alla lista asset, `history.back()` per referrer interno). La scheda e' centrata con larghezza massima e usa una testata "cockpit" piu accattivante: accento laterale, tile tipo asset, nome e codice separati, chip informativi e pannello Azioni rapide a destra. La status band Copertura/Scadenze e le card hanno accenti visivi piu leggibili; le card restano organizzate in due colonne responsive per evitare l'effetto blocchi larghi su monitor grandi. Aggiornato il test smoke del dettaglio asset per verificare il nuovo link e l'assenza del vecchio titolo. Solo template/CSS/JS e test, nessuna modifica a view, dati, ACL, permessi o routing.

- **[ux] `assets/templates/assets/pages/asset_detail.html`**: `/assets/view/<id>/` non mostra piu il sottotitolo/breadcrumb superiore che duplicava nome e tag della macchina sopra il titolo principale. La status band Copertura/Scadenze e' piu bassa, la toolbar del Registro manutenzione usa pulsanti compatti in griglia a massimo due righe e le card del dettaglio hanno spaziature/titoli leggermente piu densi. Solo template/CSS, nessuna modifica a view, dati, ACL, permessi o routing.

### Anagrafica HR - fix 500 scheda dipendente (cronologia assenze)

- **[fix] `anagrafica/views.py`**: `/anagrafica/dipendenti/<id>/` andava in **500** (`KeyError` sul numero mese) aprendo una scheda con assenze. Causa: collisione di nome a livello di modulo tra la tupla `_MESI_IT` (nomi mese indicizzati 1-12, usata da `_assenze_cronologia`) e un secondo globale `_MESI_IT` dict (nome→numero, import cedolini) definito più sotto che la sovrascriveva. La tupla è stata rinominata `_MESI_IT_NOMI` (con nota esplicativa) ed è aggiornato il suo unico uso; il dict cedolini resta invariato.

### Anagrafica HR - scheda dipendente: header su una riga e tab Timbri inline

- **[ux] `anagrafica/templates/anagrafica/pages/dipendente_detail.html`**: nella hero della scheda dipendente i pulsanti di azione ora stanno tutti sulla stessa riga (`.dp-hero-actions` allineata `center`; la form offboarding `select/data/Avvia uscita/Restituzioni` resta inline come blocco unico, con wrap ripristinato solo sotto 600px). Il **Timbri** è stato spostato dalla hero alla tab bar interna della scheda (`#dp-tabbar`), accanto alle altre voci del dipendente.
- **[feat] tab Timbri incorporata nella scheda**: il tab Timbri ora **mostra i record timbri/firme/sigle direttamente nella scheda** (record attivi con sub-tab + storico, immagini, copia, link al report) invece di rimandare alla pagina del modulo. Il contenuto è caricato in **lazy via HTMX** al primo click sul tab (la query timbri parte solo se il tab viene aperto); resta disponibile il link «Apri scheda completa» verso `timbri:operatore_detail_by_legacy`. La logica JS delle tab ignora le voci prive di `data-tab-target`; aggiunto `text-decoration:none` a `.dp-tab`.
- **[feat] `timbri/views.py`, `timbri/urls.py`**: nuovo endpoint `timbri:operatore_embed` (`/timbri/anagrafica/<legacy_id>/embed/`) che rende un frammento HTML dei record timbri del dipendente, riusando gli helper esistenti (`_ensure_legacy_operatore`, `_categorize_records`, `_attach_image_maps`) e l'ACL `_can_view_timbri` (autoritativa lato server: nessun dato senza permesso).
- **[ux] `timbri/templates/timbri/partials/operatore_embed.html`** (nuovo): frammento incorporabile con barra azioni/KPI, sub-tab timbri/firme/sigle e storico, riusando il componente `components/detail_record.html`; CSS e JS scoped al frammento.
- **[test] `timbri/tests.py`**: aggiunte regressioni per il tab Timbri nella scheda (presenza endpoint `operatore_embed` + `data-tab-target="timbri"`), per il render dei record nel frammento e per il caso negato (nessun dato senza permesso).

### Anagrafica HR - rimossa la barra controlli sopra le tabelle

- **[ux] `core/static/core/js/fm-table-enhanced.js`**: nuovo opt-out `data-fm-hide-controls="1"` (sul `<table>` o su un antenato, es. `<body>`) che nasconde l'intera barra controlli sopra la tabella (ricerca globale, menu Colonne, Reset, contatore) mantenendo attive le icone di ordina/filtro per colonna negli header.
- **[ux] `anagrafica/templates/anagrafica/components/subnav.html`**: la subnav del modulo marca `<body data-fm-hide-controls="1">`, così tutte le tabelle dell'area Anagrafica HR (es. `/anagrafica/dipendenti/`) non mostrano più la barra Cerca/Colonne/Reset sopra l'intestazione. Nessuna modifica a view, dati, ACL, permessi o routing.

### Notizie - impostazioni a card e collegamenti rapidi

- **[ux] `notizie/templates/notizie/pages/gestione_admin.html`**: `/notizie/impostazioni/` ora usa una workspace full page coerente con lista e dashboard: hero con KPI, tab compatte, riepilogo a card, permessi/log rifiniti e tab Record trasformata da tabella scrollabile a card responsive con stato, metadati, metriche letture/conformi e azioni.
- **[ux] `notizie/templates/notizie/pages/lista.html`, `notizie/templates/notizie/pages/dashboard.html`**: aggiunto il collegamento a **Impostazioni** dalla lista Notizie per gli utenti abilitati e un accesso stabile nel rail laterale della dashboard, oltre al link gia presente nella hero.
- **[ux] `notizie/views.py`**: introdotto `_can_manage_notizie_settings`, riusato dalla dashboard ed esposto alla lista come `can_gestione_admin`; aggiunto `tasso_conformita_int` come derivato visuale per la barra conformita.
- **[test] `notizie/tests.py`**: aggiunte regressioni per link Impostazioni da lista/dashboard e render della pagina impostazioni a card senza la vecchia tabella `tbl`.

### Notizie - dashboard gestione full page senza tabella scrollabile

- **[ux] `notizie/templates/notizie/pages/dashboard.html`**: `/notizie/dashboard/` ora usa una workspace full page coerente con la lista `/notizie/`: hero con KPI, tab stato, card gestionali per notizia e rail laterale per filtri/riepilogo/permessi. Rimossa la tabella larga, quindi il componente globale `fm-table-enhanced` non viene piu agganciato e non compare lo scroll orizzontale.
- **[ux] `notizie/views.py`**: `_dashboard_rows` aggiunge `completion_rate_int`, derivato solo dalla copertura esistente, per pilotare la barra visuale senza cambiare dati o query.
- **[test] `notizie/tests.py`**: aggiunta regressione sul render della dashboard a card e assenza della vecchia classe `news-table`.

### Anagrafica HR - scheda dipendente, tab Assenze piu leggibile

- **[ux] `anagrafica/templates/anagrafica/pages/dipendente_detail.html`**: la tab Assenze passa da tabella piatta + box riepilogo a una UI coerente col portale (classi `dp-abs-*`, niente stili inline, dark mode). Riepilogo anno come card con icona/accento colore per tipo (ferie/malattia/permesso/congedo/altro) e totale giorni approvati in testata; storico ultimi 2 anni reso come **cronologia a blocchi compatti raggruppata per Anno → Mese** (intestazioni anno/mese a tutta larghezza, item in **griglia responsive** `dp-abs-grid` per evitare righe quasi vuote): blocco con barra colorata + icona per tipo, header tipo + stato (`dp-pill`) e riga meta periodo `inizio → fine` · durata (giorni); hover elevato, stati vuoti come banner.
- **[ux] `anagrafica/views.py`**: in `dipendente_detail` ogni riga assenza espone `giorni` (durata) + `icona`/`accent` (nuovo helper `_assenza_tipo_meta`); il riepilogo diventa lista ordinata per giorni con `assenze_tot_anno` e la cronologia annidata Anno→Mese e costruita da `_assenze_cronologia` (+ costante `_MESI_IT_NOMI`), esposta come `assenze_cronologia`. Solo campi derivati di sola lettura, nessuna modifica a query sorgente, ACL, permessi o routing.

### Timbri - UI piu curata e coerente

- **[ux] `timbri/templates/timbri/pages/index.html`, `timbri/templates/timbri/pages/operatore_detail.html`, `timbri/templates/timbri/pages/record_form.html`**: il modulo Timbri passa a una resa piu vicina agli altri moduli: elenco full-width con hero operativa e KPI/card rifiniti, scheda dipendente con hero visuale e meta/KPI piu ordinati, form record con header piu curato e anteprime immagini piu pulite. Solo template/CSS, nessuna modifica a view, dati, ACL, permessi o routing.

### Assenze - richiesta assenza cockpit dinamico

- **[ux] `assenze/templates/assenze/pages/richiesta_assenze.html`**: la pagina richiesta passa a una UI piu dinamica: hero dedicata, stepper di compilazione, card cliccabili per tipo assenza, select fallback, misuratore live della durata, riepilogo sticky con periodo/percorso approvativo e suggerimenti dinamici legati a ferie, permesso, malattia, flessibilita e certifica presenza. Solo template/CSS/JS client-side, nessuna modifica a view, dati, ACL, permessi o routing.

### Notizie - lista full page e UI piu curata

- **[ux] `notizie/templates/notizie/pages/lista.html`**: `/notizie/` passa da wrapper centrale stretto a workspace full page con hero, KPI di lettura, filtri a tab, card comunicazione a tutta larghezza e rail laterale con riepilogo/stati rapidi.
- **[ux] `notizie/views.py`**: la lista espone conteggi derivati dalle notizie gia visibili all'utente (`news_stats`) per alimentare KPI e riepiloghi, senza cambiare ACL, dati o routing.
- **[test] `notizie/tests.py`**: aggiunta regressione sul render della nuova shell full page e completato l'onboarding degli utenti test Notizie per non fermarsi al middleware globale prima della view.

### Procedure Refresh - lista personale full page

- **[ux] `procedure_refresh/templates/procedure_refresh/pages/my_assignments.html`**: `/procedure-refresh/` passa da tabella centrale a workspace full page con hero operativa, KPI personali, filtri a tab, card assegnazione a tutta larghezza, empty state e rail laterale con stato personale/vista rapida.
- **[ux] `procedure_refresh/views.py`**: la lista personale espone `pr_stats` calcolato sulle sole assegnazioni dell'utente corrente per alimentare KPI e riepiloghi, senza cambiare ACL, dati o routing.
- **[test] `procedure_refresh/tests.py`**: aggiunta regressione sul render della nuova shell full page della lista personale.

### Assenze - linguaggio visuale esteso alle pagine operative

- **[ux] `assenze/templates/assenze/base_shell.html`, `assenze/templates/assenze/pages/richiesta_assenze.html`, `assenze/templates/assenze/pages/gestione_assenze.html`, `assenze/templates/assenze/pages/calendario.html`, `assenze/templates/assenze/pages/certificazione_presenza.html`, `assenze/templates/assenze/pages/car_dashboard.html`, `assenze/templates/assenze/pages/gestione_admin.html`, `assenze/templates/assenze/pages/menu.html`**: aggiunto sprite SVG condiviso nella shell Assenze e portato il nuovo linguaggio visuale del menu sulle altre viste operative: icone nei pulsanti hero, KPI con pittogrammi, tab admin, titoli pannello, banner presenza, filtro ricerca e blocchi diagnostici. Solo template/CSS, nessuna modifica a view, dati, ACL, permessi o routing.

### Assenze - menu modulo piu compatto e visuale

- **[ux] `assenze/templates/assenze/base_shell.html`, `assenze/templates/assenze/pages/menu.html`**: il menu `/assenze/` usa una classe shell dedicata per evitare lo stretching verticale della griglia e presenta hero a cockpit, micro-statistiche, card operative con accenti colore e icone SVG inline, lista ultime richieste con icone di stato, spaziature piu compatte e testi piu asciutti. Solo template/CSS, nessuna modifica a view, dati, ACL o routing.

### Dashboard - home portale mostra solo moduli visibili

- **[fix/ux] `dashboard/views_home_portale.py`**: `_module_groups()` esclude i moduli non accessibili gia' lato server; eventuali sessioni precedenti con `hp_show_locked=True` non riattivano piu' la visualizzazione dei moduli bloccati.
- **[ux] `dashboard/templates/dashboard/pages/home_portale.html`**: rimosso il flag "Mostra moduli non accessibili"; la griglia e il footer parlano solo dei moduli disponibili.
- **[test] `dashboard/tests.py`**: aggiunte regressioni su filtro moduli visibili e sessione stale.

### Automazioni — debounce per gruppo (cooldown_group) per le notifiche anomalie

- **[feat] `automazioni/models.py`, migration `0018_automationcooldowngroup.py`**: nuovo operatore condizione `cooldown_group` (lettura pura) + modello `AutomationCooldownGroup` (chiave `(group_key, group_value)` indipendente dalla regola, namespace condivisibile fra regole).
- **[feat] `automazioni/services.py`**: `evaluate_condition` gestisce `cooldown_group` come gate read-only (fail-open); `_commit_cooldown_groups` scrive `last_fired_at` in `run_rule` solo dopo l'esecuzione riuscita delle azioni (non nei test) → il debounce non si "brucia" su fallimento e vale per qualsiasi azione (incluso send_email).
- **[feat] `packages/au51_anomalia_creata_mail_action_capocommessa.automation_package.json`**: aggiunte condizioni `ex_op_nominativo is_not_empty` + `cooldown_group mail_anomalie_op:5` (max 1 mail/5 min per OP).

### Tickets — match identità ACL gestione/apertura più robusto

- **[fix] `tickets/views.py`** — nuovo helper `_user_acl_identities(request)` + `_acl_list_matches()`: il controllo di `acl_apertura`/`acl_gestione` ora riconosce tutte le forme con cui un utente può essere salvato nelle liste (username Django, email aziendale/UPN, prefisso UPN, `aliasusername` legacy, email aziendale legacy). Risolve i 403 sul dettaglio ticket quando in lista è salvato l'`aliasusername` (es. `a.astarita`) ma l'account Django ha come username/email l'UPN (`a.astarita@dominio`). **`email_notifica` (mail privata) esclusa di proposito**: l'identità valida è solo mail aziendale o username. Aggiornate `_can_open_tickets` e `_can_manage_tickets` per usare gli helper.

### ACL strict-mode — readiness prod

- **[docs] `docs/ai/CHECKLIST_ATTIVAZIONE_ACL_STRICT_PROD.md`** — registrata la misura di readiness eseguita in prod il 2026-06-05 dopo l'aggiornamento della release `feat/acl-chiusura-migrazione-fase1`: `acl_strict_readiness` riporta 0 accessi consentiti solo via fallback legacy su 833 route applicative e tutti i 9 ruoli. Spuntati il prerequisito branch rilasciato e il Passo 1 (strict attivabile senza regressioni); aggiornata la tabella Stato.

### Automazioni - package Power Automate RENTRI

- **[package] `automazioni/packages/pa_rentri_modifica_elemento_promemoria.automation_package.json`** — nuovo package importabile da `rentri_20260604152402.zip` per il flow Power Automate `RENTRI - MODIFICA ELEMENTO`: notifica nuovo carico, promemoria carico non marcato RENTRI dopo 5 giorni e promemoria FIR dopo 30 giorni. Riferisce i package gia' presenti `au31_scarico_senza_fir_notifica` e `docs/automation_packages/rentri_movimenti_da_trasmettere` per evitare sovrapposizioni operative.

### Fix

- **[fix] `timbri/views.py`**: la scheda timbri da anagrafica (`/timbri/anagrafica/<legacy_id>/`) non accede piu' a `civile.foto.url`, non supportato dallo storage privato Anagrafica. Quando il dipendente ha una foto, il template riceve la route protetta `anagrafica:foto_dipendente`, evitando il 500 `NotImplementedError`.

- **[fix] `timbri/management/commands/import_timbri_da_share.py`**: il comando `import_timbri_da_share --apply` usa ora un output di successo ASCII (`OK`) invece del simbolo Unicode di spunta. Su console Windows prod con encoding `charmap`/CP1252 quel carattere generava `UnicodeEncodeError` dopo il salvataggio, facendo apparire le immagini come errore anche se file e record erano gia' stati creati.

- **[fix] `assenze/views.py`** — URL notifica accettazione/rifiuto assenza corretta da `/assenze/gestione/` (inesistente) a `/assenze/richiesta_assenze` (riepilogo richieste del dipendente).

### Autenticazione a due fattori (2FA)

- **[feat] `twofa/` (nuova app)** — modulo 2FA completo con supporto TOTP (app authenticator) ed Email OTP.
- **[feat] `twofa/models.py`** — `TwoFactorPolicy` (configurazione singleton globale: abilitazione, ruoli soggetti, rete interna/esterna, metodi, durata sessione); `UserTwoFactor` (configurazione per utente: metodo, TOTP secret crittografato Fernet, flag attivo/force_setup); `TwoFactorChallenge` (challenge OTP email con hash SHA-256, TTL, contatore tentativi).
- **[feat] `twofa/utils.py`** — generazione/verifica TOTP (`pyotp`), generazione QR SVG inline (`qrcode`), generazione/invio/verifica OTP email, detection rete interna via CIDR (`ipaddress`), gestione session flag `twofa_verified_until`, crittografia secret TOTP via Fernet derivato da `SECRET_KEY`.
- **[feat] `twofa/middleware.py`** — `TwoFactorMiddleware`: intercetta ogni richiesta autenticata con `twofa_pending=True` e reindirizza a `/2fa/verifica/` se la verifica non è stata completata nella sessione corrente.
- **[feat] `twofa/views.py`** — `verify` (verifica codice TOTP/email; resend OTP; redirect post-verifica); `setup_totp` (setup self-service con QR code + conferma primo codice); `resend_otp` (JSON endpoint reinvio OTP).
- **[feat] `twofa/templates/twofa/pages/verify.html`** — pagina verifica 2FA (layout login, form codice, pulsante reinvia per email).
- **[feat] `twofa/templates/twofa/pages/setup_totp.html`** — pagina setup TOTP con QR SVG inline, codice manuale e form conferma.
- **[feat] `twofa/migrations/0001_initial.py`** — migrazione iniziale per i tre modelli 2FA.
- **[feat] `admin_portale/views.py`** — view `twofa_config` (pannello admin), `api_twofa_policy_save` (salva policy globale con validazione CIDR), `api_twofa_user_toggle` (attiva/disattiva per utente), `api_twofa_user_reset` (reset OTP/TOTP, forza re-setup), `api_twofa_user_method_set` (cambio metodo), `api_twofa_user_email_set` (email override OTP).
- **[feat] `admin_portale/templates/admin_portale/pages/twofa_config.html`** — pannello admin: policy globale (abilita, quando, reti CIDR, ruoli, metodi, durata sessione) + tabella utenti con stato, toggle, reset, cambio metodo.
- **[feat] `admin_portale/urls.py`** — route `/admin-portale/2fa/` e API `api_twofa_*`.
- **[feat] `core/accounts/views.py`** — `LegacyLoginView.form_valid()` riscritta per intercettare il 2FA dopo autenticazione: se richiesto, salva `twofa_next` e redirige a `/2fa/verifica/` prima del redirect normale.
- **[config] `config/settings/base.py`** — aggiunto `twofa.apps.TwoFaConfig` a `INSTALLED_APPS`; aggiunto `twofa.middleware.TwoFactorMiddleware` dopo `SetupRequiredMiddleware`; aggiunto `/2fa/` a `MIDDLEWARE_EXEMPT_PREFIXES`.
- **[config] `config/urls.py`** — aggiunto `path("2fa/", include(("twofa.urls", "twofa"), namespace="twofa"))`.
- **[dep] `requirements.in` / `requirements.txt`** — aggiunto `pyotp>=2.9` e `qrcode[pil]>=7.4`.
- **[ux] `admin_portale/templates/admin_portale/pages/index.html`** — aggiunto pulsante "Autenticazione 2FA" nella sezione "Utenti & Accessi" (contatore aggiornato a 6 strumenti).
- **[ux] `admin_portale/templates/admin_portale/pages/utenti_list.html`** — aggiunta colonna "2FA" con badge stato (TOTP/Email/Setup/Off/—) e pulsante "2FA" in azioni per navigare direttamente alla riga utente nella pagina config.
- **[feat] `admin_portale/views.py`** — aggiunta funzione `_attach_twofa_to_users()` che arricchisce ogni `UtenteLegacy` con `twofa_info` (metodo, stato attivo, TOTP confirmed) via join `Profile → UserTwoFactor`.

### Tickets - richiedente collegato al dipendente/utente portale

- **[feat] `tickets/models.py`** — aggiunto campo `richiedente_user = ForeignKey(AUTH_USER_MODEL, null=True, blank=True, SET_NULL, related_name="tickets_richiesti")` per collegare il richiedente all'effettivo utente Django.
- **[feat] `tickets/migrations/0010_richiedente_user_fk.py`** — migrazione per il nuovo campo FK.
- **[data] `tickets/migrations/0011_backfill_richiedente_user.py`** — data migration di backfill: collega i ticket esistenti all'utente Django tramite la catena `richiedente_legacy_user_id → anagrafica_dipendenti.utente_id → aliasusername → auth_user.username`. Elabora in batch da 500 ticket, salta i ticket senza corrispondenza univoca.
- **[feat] `tickets/views.py`** — `ticket_nuovo`: popola `richiedente_user=request.user` alla creazione. `_ticket_access_flags`, `ticket_aggiungi_commento`, `ticket_aggiungi_allegato`: il check `is_richiedente` include `richiedente_user_id == request.user.id` come condizione primaria. `gestione_list`: annotato queryset con `richiedente_anagrafica_id` via Subquery su `AnagraficaDipendente.aliasusername`. `ticket_detail`, `ticket_gestione_detail`: lookup `richiedente_anagrafica_id` e passaggio a context.
- **[ux] `tickets/templates/tickets/pages/gestione_list.html`** — cella Richiedente mostra link alla scheda dipendente se `richiedente_anagrafica_id` disponibile.
- **[ux] `tickets/templates/tickets/pages/gestione_detail.html`** — card hero e sidebar richiedente mostrano link alla scheda dipendente.
- **[ux] `tickets/templates/tickets/pages/detail.html`** — richiedente mostra link alla scheda dipendente.

### Anomalie - rimozione integrazione SharePoint/Microsoft Graph

- **[refactor] `anomalie/views.py`** — rimossi tutti i blocchi relativi a SharePoint/Microsoft Graph: funzioni `_graph_*`, `_sp_*`, `_sharepoint_*`, `_can_sync_anomalie`, `api_sync` (sostituita con stub 410). Rimossi import `requests` e `acquire_graph_token`. Rimosso tracking metadata sync allegati (`_attachment_sync_meta_path`, `_mark_attachment_pending`, `_remove_attachment_sync_meta_entry`, `_pending_attachment_local_ids`, `_sync_attachments_for_local` e relative costanti). Semplificata `_list_attachments_for_local` (nessun campo `sync_status`). Rimosso `sync_status` dalla response di `api_salva`.
- **[refactor] `anomalie/templates/anomalie/pages/gestione_anomalie_react.html`** — rimossa variabile stato `syncing` non più utilizzata.
- **[refactor] `anomalie/templates/anomalie/pages/gestione_anomalie.html`** — endpoint API descritto con placeholder esplicito anziché `...`.
- **[test] `anomalie/tests.py`** — rimossa classe `AnomalieSharePointSyncTests` e i test `test_config_page_shows_sharepoint_config_card` / `test_config_page_can_save_sharepoint_config`. Rimosso il patch `_graph_config_issue` da `test_page_keeps_filter_querystring_for_frontend`. Rimossi import inutilizzati (`shutil`, `Path`, `uuid4`, `_make_workspace_tempdir`).

### Anagrafica - fix filtro Reparto vuoto in Ratei e Retribuzioni globale

- **[fix] `anagrafica/views.py`** — `ratei_list` e `ratei_export`: aggiunto fallback CF→legacy_id via `DipendenteAnagraficaCivile` (per cedolini senza `legacy_anagrafica_id` valorizzato) e fallback reparto via `DipendenteAnagraficaAziendale.area` quando `AnagraficaDipendente.reparto` è vuoto. Il filtro Reparto ora si popola correttamente anche per i dipendenti migrati al nuovo modello.
- **[fix] `anagrafica/views.py`** — `_retribuzioni_globale_context`: aggiunto fallback reparto via `DipendenteAnagraficaAziendale.area`, coerente con la logica di `ratei_list`.

### Assenze - richiesta con caporeparto HR e regole orario

- **[fix/ux] `assenze/views.py`**: `_load_capi_options()` privilegia i caporeparto definiti nei Reparti di Anagrafica HR; il default del form usa il caporeparto effettivo salvato su `DipendenteAnagraficaAziendale`/Reparto per il dipendente corrente, con fallback legacy esistenti.
- **[fix] `assenze/views.py`**: default data inizio/fine sul giorno corrente; le ferie vengono salvate come giornate intere `00:00-23:59` e i permessi multi-giorno sono respinti lato server.
- **[ux] `assenze/templates/assenze/pages/richiesta_assenze.html`**: il cambio tipo applica i default coerenti lato browser: ferie a giornata intera, permesso nello stesso giorno.
- **[test] `assenze/tests.py`**: regressioni su fonte caporeparto Anagrafica HR, default giorno corrente, normalizzazione ferie e blocco permesso multi-giorno.

### Admin Portale - utenti fullpage

- **[ux] `admin_portale/templates/admin_portale/pages/utenti_list.html`**: `/admin-portale/utenti/` passa a una workspace fullpage con form nuovo utente richiudibile, filtri compatti, toolbar azioni massive e tabella utenti con scroll interno.
- **[test] `admin_portale/tests.py`**: aggiunta regressione sul render della shell fullpage della lista utenti.

### Core - notifiche live con popup in-app

- **[feat] `core/views.py`, `core/urls.py`**: aggiunto endpoint `api_notifiche_live` (`/api/notifiche/live/`) che restituisce contatore non lette e notifiche non ancora mostrate come popup, filtrate sull'utente legacy corrente.
- **[ux] `core/templates/core/base.html`, `core/templates/core/components/topnav.html`, `core/templates/core/components/sidebar.html`, `core/static/core/css/theme.css`**: il layout globale aggiorna badge topbar/sidebar via polling, mostra popup live in-app senza refresh e rinfresca il pannello notifiche quando arrivano nuovi eventi.
- **[test] `core/tests.py`**: regressioni su endpoint live, ack popup limitato all'utente corrente, rendering del client globale e flusso pannello/mark-read.

### Anagrafica HR - offboarding compatto a data unica

- **[ux] `anagrafica/templates/anagrafica/pages/dipendente_detail.html`**: nella hero della scheda dipendente il form offboarding mostra una sola "Data uscita"; il menu restituzioni e ora compatto e si apre solo quando serve.
- **[fix] `anagrafica/views.py`**: se il form non passa `ultimo_giorno_operativo`, la pratica lo valorizza con la stessa data uscita per mantenere compatibilita con il dato storico senza chiedere una seconda data all'utente.
- **[test] `anagrafica/tests.py`**: aggiornata la regressione del flusso offboarding a data unica e verifica che il secondo input data non sia piu renderizzato.

### Anagrafica - auto-fill visivo area aziendale e caporeparto nel form

- **[feat] `anagrafica/templates/anagrafica/pages/dipendente_detail.html`**: nel form "Modifica dati aziendali", aggiunti due campi read-only (`Area aziendale`, `Caporeparto`) che si popolano automaticamente via JavaScript al cambio del dropdown Reparto — senza attendere il salvataggio.
- **[refactor] `anagrafica/forms.py`**: `area_aziendale_nome` e `caporeparto_legacy_id` esclusi da `AnagraficaAziendaleForm.exclude` — sono campi auto-gestiti server-side da `_sync_aziendale_from_reparto` e non devono essere modificabili manualmente nel form.
- **[feat] `anagrafica/views.py`**: in `dipendente_detail`, la chiamata a `_dipendenti_picker_rows()` è ora incondizionale; costruita mappa `reparto_autofill_json` (reparto → area aziendale + label caporeparto) passata al template per il JS.

### Anagrafica - fix auto-fill area aziendale e caporeparto al salvataggio

- **[fix] `anagrafica/views.py`**: `dipendente_anagrafica_aziendale_save` ora chiama `_sync_aziendale_from_reparto` dopo il save del form — area aziendale e caporeparto vengono popolati automaticamente dal catalogo Reparto quando si modifica l'anagrafica aziendale del dipendente.

### Anagrafica - fix dropdown reparto in modifica anagrafica aziendale

- **[fix] `anagrafica/forms.py`**: `AnagraficaAziendaleForm.__init__` ora popola il dropdown `area` (Reparto) da `Reparto.objects.filter(is_active=True)` invece di `AreaAziendale` (che è il modello genitore di livello superiore, sempre vuoto). Aggiunto `Reparto` agli import del modulo.

### Anagrafica - fix sincronizzazione lista reparti in Impostazioni

- **[fix] `anagrafica/views.py`**: nella view `impostazioni`, la variabile `aree` ora carica `Reparto.objects.all()` invece di `AreaAziendale.objects.all()`. Il form di creazione reparto creava correttamente oggetti `Reparto`, ma la lista della pagina mostrava `AreaAziendale` (tabella separata, sempre vuota), causando "Nessun reparto registrato" dopo ogni inserimento nonostante il toast di successo. Aggiunto `aree_aziendali` al contesto.
- **[feat] `anagrafica/templates/anagrafica/pages/impostazioni.html`**: aggiunto select "Area aziendale" nel form di creazione reparto e nel modale di modifica; le righe lista ora mostrano il badge area (o avviso "Nessuna area").
- **[feat] `anagrafica/templates/anagrafica/pages/impostazioni.html`, `anagrafica/views.py`**: aggiunta tab "Aree aziendali" nel pannello Impostazioni con form creazione (nome, descrizione, colore) e modale modifica/elimina — usa i CRUD `area_aziendale_create/edit/delete` già esistenti via `next_tab`.

### Anagrafica HR come fonte di verità per i caporeparto

- **[feat] `anagrafica/views.py`**: aggiunto helper `_sync_reparto_capo_mapping(rep)` che allinea `RepartoCapoMapping` (usata da assenze e automazioni) ogni volta che viene salvato un `Reparto` con `caporeparto_legacy_id`; usa `canonical_caporeparto_value` per ricavare la stringa email/nome dal legacy_id.
- **[feat] `anagrafica/views.py`**: `area_create` e `area_edit` chiamano `_sync_reparto_capo_mapping` dopo ogni salvataggio — Anagrafica HR diventa fonte di verità unica per i caporeparto.
- **[feat] `anagrafica/management/commands/sync_reparto_capo_mapping.py`**: nuovo command per sync bulk immediata di tutti i `Reparto` → `RepartoCapoMapping`; supporta `--dry-run`.
- **[remove] `admin_portale/templates/admin_portale/pages/anagrafica_config.html`**: rimossa la card "Associazioni Reparto → Capo Reparto", il relativo modal e il blocco JS — la gestione avviene ora esclusivamente in Anagrafica HR → Impostazioni → Reparti.

### admin_portale - rimozione pagina Anagrafica Config

- **[remove] `admin_portale/views.py`**: rimosse le view `anagrafica_config` e `anagrafica_import_csv` (import CSV dipendenti ora eseguibile solo via management command `import_dipendenti_csv`).
- **[remove] `admin_portale/urls.py`**: rimossi i path `anagrafica-config/` e `anagrafica-config/import-csv`.
- **[remove] `admin_portale/templates/admin_portale/pages/anagrafica_config.html`**, **`anagrafica_config_fallback.html`**: template eliminati.
- **[remove] `admin_portale/templates/admin_portale/pages/index.html`**: rimosso il modulo "Anagrafica Config" dalla griglia Configurazione (contatore 3→2).
- **[remove] `admin_portale/templates/admin_portale/pages/utente_edit.html`**: rimosso il link "Configura liste →" dalla sezione Organizzazione.
- **[migration] `core/migrations/0055_remove_anagrafica_config_nav.py`**: disattiva il `NavigationItem` con `route_name="admin_portale:anagrafica_config"` per evitare errori di reverse URL.
- **[fixture] `fixtures/nav_acl_snapshot.json`**, **`core/management/commands/seed_pulsanti_descrizioni.py`**: rimossi i riferimenti ad `anagrafica_config`.

### Automazioni - split giornaliero Assenze

- **[feat] `automazioni`**: aggiunta l'action `split_assenza_giornaliera` per creare record giornalieri derivati sulla tabella SQL Server `assenze`, con deduplica runtime, dry-run queue/import package e configurazione nel designer.
- **[package/docs] `docs/automation_packages/assenze_calendario_avviso_inserimento.automation_package.json`**: il package Power Automate calendario assenze usa lo split nei rami approvato e salta-approvazione.
- **[test] `automazioni/tests.py`**: aggiunte regressioni su creazione righe derivate e idempotenza.

### Automazioni - designer diagramma workspace leggibile

- **[ux] `automazioni/templates/automazioni/pages/rule_designer.html`**: ripuliti i simboli corrotti nel pulsante e nella toolbar del diagramma (`PNG`, `Chiudi`, `+ Aggiungi azione`) e stabilizzato il workspace full-viewport con inspector sinistro senza overflow orizzontale, campi inline a colonna singola, body/html lock e maniglia drag CSS.
- **[test] `automazioni/tests.py`**: aggiunta regressione sul rendering dei testi puliti del diagramma e sull'assenza dei vecchi label corrotti.

### Assets - rinomina massiva solo nome asset

- **[ops] `assets/management/commands/rename_asset_names.py`**: nuovo command per esportare un template CSV `asset_tag;current_name;new_name` e aggiornare solo `Asset.name` da CSV, con dry-run di default e commit esplicito.
- **[test/docs] `assets/tests.py`, `assets/README.md`, root `README.md`**: regressioni su dry-run, commit, blocco errori e template; documentata procedura operativa.

### Config - hardening `.env` e navigazione

- **[fix] `hub_tools/views.py`, `hub_tools/templates/hub_tools/setup_wizard.html`**: il Setup Wizard Hub usa ora il percorso runtime persistente (`ENV/config/.env` nei deploy) e non forza piu `NAVIGATION_LEGACY_FALLBACK_ENABLED=1` quando il Navigation Registry e' attivo. Se il registry viene disabilitato esplicitamente, il fallback legacy viene riattivato in modo coerente.
- **[fix] `config/env_config.py`**: lettura `.env` robusta con `utf-8-sig`, cosi un salvataggio da Notepad con BOM UTF-8 non rompe la prima chiave del file.
- **[ops] `deployment/scripts/secure-env-acl.ps1`, `deployment/scripts/deploy-release.ps1`, `deployment/scripts/configure-iis-site.ps1`**: nuovo hardening NTFS per proteggere `ENV/config/.env` e le copie release `.env`; deploy e configurazione IIS lo invocano automaticamente.
- **[test] `hub_tools/tests.py`, `config/test_env_config.py`**: regressioni per impedire il ritorno automatico al fallback legacy e per accettare `.env` con BOM UTF-8.

### Core - ripristino Navigation Registry

- **[ops] `core/management/commands/restore_navigation_registry.py`**: nuovo comando dry-run/apply per ripristinare il registry menu (`ModuleCategory`, `NavigationItem`, `NavigationRoleAccess`) dalla fixture locale `fixtures/nav_acl_snapshot.json` o da un dump JSON Django serializer. In apply pubblica prima uno snapshot di backup, sostituisce solo la navigazione e invalida la cache menu.

### Assets - sidebar categorie compatta

- **[ux] `assets/views.py`, `assets/templates/assets/base_shell.html`**: le voci categoria radice della sidebar del modulo Assets sono ora gruppi espandibili con sottocategorie chiuse di default. Il ramo della sottocategoria filtrata resta aperto automaticamente e le aperture manuali vengono memorizzate in `localStorage`.
- **[test] `assets/tests.py`**: aggiunte regressioni sulla costruzione annidata della sidebar e sul rendering HTML dei gruppi richiudibili.

### Core - tabelle ordinabili/filtrabili globali

- **[ux] `core/static/core/js/fm-table-enhanced.js`, `core/static/core/css/fm-table-enhanced.css`**: il sistema tabelle personalizzabili non richiede piu l'intervento template-per-template per le tabelle dati semplici. Le tabelle con `data-table-id` continuano a usare la configurazione esplicita; le altre vengono riconosciute automaticamente, ricevono un `table_id` stabile, colonne inferite dai `<th>`, filtri per tipo, ordinamento, ricerca globale e preferenze per utente. Escluse tabelle tecniche/di stampa/matrici e aggiunto osservatore per tabelle renderizzate dinamicamente.
- **[fix] `core/static/core/js/fm-table-enhanced.js`**: l'ordinamento data ora gestisce anche formati italiani `gg/mm/aaaa` e `gg-mm-aaaa`, non solo date ISO.

### Anagrafica HR - scheda dipendente compatta

- **[ux] `anagrafica/templates/anagrafica/pages/dipendente_detail.html`, `anagrafica/templates/anagrafica/components/subnav.html`, `anagrafica/templates/anagrafica/partials/formazione_tab_dipendente.html`**: nella scheda dipendente e stata nascosta la riga descrittiva sotto la subnav, rimossa la topbar duplicata e portati i pulsanti "Timbri" / "Torna all'elenco" nella hero del dipendente; rimosso anche il commento visibile del partial Formazione.

### Anagrafica HR - offboarding con pratica task

- **[feat] `anagrafica/models.py`, migration `0030_offboarding_pratiche.py`, `anagrafica/admin.py`, `anagrafica/views.py`, `anagrafica/urls.py`, `anagrafica/templates/anagrafica/pages/dipendente_detail.html`**: il tasto admin di offboarding apre una pratica con motivo, data cessazione prevista, ultimo giorno operativo e task HR/IT/responsabile/restituzioni. Il dipendente resta in forza finche la pratica e aperta; la chiusura del rapporto e bloccata se ci sono task "Da fare" o se la data cessazione e futura. Alla chiusura vengono impostati `DipendenteAnagraficaAziendale.data_cessazione`, record legacy `attivo=0`, account portale scollegato (`utente_id=NULL`) e audit metadata-only.
- **[test] `anagrafica/tests.py`**: copertura per apertura pratica, blocco chiusura con task pendenti, completamento task e passaggio finale fuori dalla lista in forza verso la vista ex dipendenti.

### Anagrafica HR - campi onboarding/offboarding configurabili

- **[feat] `anagrafica/models.py`, migration `0031_onboardingoffboardingcampo.py`, `anagrafica/admin.py`, `anagrafica/views.py`, `anagrafica/urls.py`, `anagrafica/templates/anagrafica/pages/impostazioni.html`**: nuovo tab "Onboarding / Offboarding" in `/anagrafica/impostazioni/` per associare i campi reali del form `+ Nuovo dipendente` alle liste operative di ingresso/uscita. Ogni associazione salva fase, categoria, obbligatorieta, ordine, stato e note; le voci Offboarding attive generano task automatici nelle pratiche di uscita.
- **[test] `anagrafica/tests.py`**: regressioni per rendering tab impostazioni, creazione/aggiornamento associazioni e generazione task offboarding da campi configurati.

### Anagrafica HR - nuovo dipendente, offboarding e rimessa in forza

- **[feat] `anagrafica/views.py`, `anagrafica/urls.py`, `anagrafica/templatetags/anagrafica_extras.py`, `anagrafica/templates/anagrafica/pages/index.html`, `anagrafica/templates/anagrafica/pages/dipendente_detail.html`, `anagrafica/templates/anagrafica/components/subnav.html`, migration `0028_subnav_onboarding_offboarding.py`**: rimossa la sezione separata onboarding/offboarding in Anagrafica HR; l'onboarding resta il flusso "Nuovo dipendente", la migration elimina eventuali vecchi link subnav locali e la subnav ignora link named non piu risolvibili.
- **[feat] `anagrafica/models.py`, migration `0029_aziendale_account_pre_offboarding.py`, `anagrafica/templates/anagrafica/pages/dipendente_detail.html`**: mantenuto il tasto admin "Rimetti in forza" quando il rapporto ha `data_cessazione`; la rimessa rimuove la cessazione, riattiva il record legacy e ricollega automaticamente l'account portale usando l'ID salvato prima dell'offboarding o una ricerca univoca per email, alias o nome/cognome.
- **[test] `anagrafica/tests.py`**: regressioni per pratica offboarding, memorizzazione account pre-offboarding, assenza della sezione onboarding/offboarding separata, rimessa in forza con ricollegamento account.

### Fornitori - permessi separati da Anagrafica HR

- **[acl] `admin_portale/views.py`, `fornitori/acl_bootstrap.py`, migrations `fornitori/0001_split_fornitori_acl.py` e `0002_hide_migrated_anagrafica_supplier_buttons.py`**: il catalogo permessi separa `Anagrafica HR` dal modulo `Anagrafica Fornitori`; le route `fornitori:*` sono bindate a permessi compatibili `legacy.fornitori.*`, i vecchi permessi fornitori sotto `anagrafica` vengono migrati verso `fornitori` e i pulsanti storici non piu attivi vengono esclusi dai raggruppamenti modulo.
- **[ux/test] `admin_portale/templates/admin_portale/pages/index.html`, `admin_portale/tests.py`, `fornitori/tests.py`**: la dashboard admin mostra HR e Fornitori come card distinte e i test coprono la separazione dei moduli assegnabili.

### Anagrafica HR - Retribuzioni vista globale

- **[feat] `anagrafica/views.py`, `anagrafica/urls.py`**: nuove view `retribuzioni_globale` e `retribuzioni_globale_export` (gate `_check_hr_permission`); pagina pivot `/anagrafica/retribuzioni/globale/` con una riga per dipendente+mese e una colonna per ogni `pay_item` raggruppata per categoria.
- **[feat] `anagrafica/templates/anagrafica/pages/retribuzioni_globale.html`** (nuovo): tabella pivot con filtri dipendente (multi+ricerca), reparto (multi), livello contrattuale (multi), sesso e mensilita; export Excel con i filtri correnti.
- **[ux] `anagrafica/templates/anagrafica/components/subnav.html`**: aggiunta voce descrittiva per la nuova view nella subnav.
- **[fix] `anagrafica/views.py`**: la vista globale risolve nome/reparto del dipendente via codice fiscale -> `DipendenteAnagraficaCivile` quando la `VoceRetributiva` non ha `legacy_anagrafica_id`; corregge nome mostrato come CF (ricerca per cognome-nome non funzionante) e colonna Reparto vuota.
- **[ux] `anagrafica/templates/anagrafica/pages/retribuzioni_globale.html`**: intestazioni colonna compattate su due righe (font ridotto, colonne strette), padding celle ridotto, `aria-label` sui select dei filtri.
- **[fix] `anagrafica/templates/anagrafica/pages/impostazioni.html`**: i form crea/modifica dei link subnav anagrafica ora espongono il selettore "Tipo di URL" (nome view Django / URL diretto). Prima il form forzava `url_type=raw`, quindi inserire un nome di rotta (es. `anagrafica:retribuzioni_globale`) produceva un link non valido (pagina non trovata).
- **[ux] `anagrafica/views.py`, `anagrafica/templates/anagrafica/pages/impostazioni.html`**: aggiunto un menu a tendina "Scegli una pagina del modulo..." nei form crea/modifica dei link subnav: selezionando una pagina dal catalogo (`subnav_route_choices`, ~19 rotte del modulo anagrafica) il nome view e `url_type=named` vengono compilati automaticamente. Resta possibile inserire manualmente path/URL esterni.

### Assistente AI - Anagrafica HR

- **[feat] `ai_assistant/tools.py`**: abilitato il tool runtime `anagrafica_summary` per elenco dipendenti, campi aziendali minimi, consenso privacy e classifiche ratei ferie/permessi residui; accesso solo a superuser, admin legacy o ruoli autorizzati da `AnagraficaHRPermission`.
- **[fix] `ai_assistant/tools.py`, `ai_assistant/services.py`, `ai_assistant/views.py`**: le domande nominative sui ratei (es. "Quante ore ferie residue ha SMARRELLA?") filtrano ora il dipendente richiesto, includono una `RISPOSTA DIRETTA`, convertono in giorni su base 7.5 ore se richiesto e non mostrano piu fonti RAG irrilevanti quando il contesto live `tool:*` e presente. Aggiornati anche i suggerimenti contestuali dei ratei.
- **[ux] `ai_assistant/templates/ai_assistant/chat.html`, `ai_assistant/views.py`, `ai_assistant/services.py`**: aggiunto pannello "Personalizzazione risposte e limiti" nella chat AI. L'utente puo scegliere stile operativo/sintetico/dettagliato e se mostrare esplicitamente i limiti; la UI chiarisce cosa l'AI puo' e non puo' fare. Le preferenze sono salvate nel browser, sanificate dall'API e passate al modello senza alterare ACL, privacy o tool live disponibili.
- **[privacy] `ai_assistant/tools.py`**: il tool blocca richieste di CF, IBAN, banca, indirizzi, contatti privati, categorie protette/disabilita, visite mediche, retribuzioni, dettagli cedolino, documenti, allegati e path; `timbri_presenze` resta non disponibile.
- **[test] `ai_assistant/tests.py`, `admin_portale/tests.py`**: aggiunte regressioni su consenso privacy, classifica ferie residue, saldo nominativo ferie residue, pulizia fonti RAG con tool live, preferenze utente sanificate, permesso negato, campi HR vietati e catalogo Tool live; riallineato il test di troncamento runtime al limite corrente di righe.

### Admin portale - gestione utenti

- **[ux] `admin_portale/forms.py`**: aggiunto campo `new_username` in `UtenteUpdateForm` con validazione (no spazi); campo opzionale, lasciato vuoto non modifica nulla.
- **[ux] `admin_portale/views.py`**: `utente_edit` passa `django_username` nel context (letto dal `User` Django collegato via `Profile`); `utente_update` gestisce il cambio username Django - verifica unicita, aggiorna `User.username`, aggiunge audit entry `utente_username_change`.
- **[ux] `admin_portale/templates/admin_portale/pages/utente_edit.html`**: campo "Email" rinominato "Email / Login (UPN)" per chiarire che e il login credential legacy; aggiunto campo "Username portale" per modificare `User.username` Django (visibile solo se l'account Django e collegato).

### Anagrafica - scheda dipendente

- **[fix] `anagrafica/templates/anagrafica/pages/dipendente_detail.html`**: chiave `sessionStorage` per le tab interne portata da globale (`dp_detail_tab_v1`) a per-dipendente (`dp_detail_tab_<legacy_id>_v1`); impedisce che l'ultima tab visitata su un dipendente si apra anche su un altro dipendente.
- **[feat] `anagrafica/views.py`, `anagrafica/urls.py`, `anagrafica/templates/anagrafica/pages/dipendente_detail.html`**: aggiunta modifica `aliasusername` inline (tab Riepilogo, campo "Username", solo admin) - stessa UX di mansione/reparto: edit -> form inline -> Salva; validazione unicita, storico cambiamento.
- **[feat] `anagrafica/views.py`, `anagrafica/urls.py`, `anagrafica/templates/anagrafica/pages/dipendente_detail.html`**: aggiunto toggle Disattiva/Riattiva dipendente nell'hero (solo admin) - imposta `attivo=0/1` nel campo legacy; la disattivazione scollega anche l'account portale (`detach_account=True`); operazione reversibile con conferma JS.

### Archivio documenti dipendente

- **[fix] `anagrafica/views.py`**: corretto il 500 su upload manuale documento dipendente (`Path` usato senza import); l'audit `DOCUMENTO_DIPENDENTE_UPLOAD` ora passa un payload dict invece di una stringa.
- **[test] `anagrafica/tests.py`**: aggiunta regressione che carica un PDF sintetico come documento manuale usando `ANAGRAFICA_PRIVATE_ROOT` temporaneo.
- **[fix] `anagrafica/views.py`**: corretto il redirect dopo creazione/modifica/eliminazione delle cartelle documenti. Le view usano ora `_redirect_impostazioni("documenti")` invece di concatenare `?tab=documenti` al nome URL, evitando `NoReverseMatch`.
- **[fix] `anagrafica/views.py`, `anagrafica/templates/anagrafica/pages/documenti_list.html`**: corretto il 500 su `/anagrafica/documenti/`. La view non espone piu un attributo dinamico con underscore (`_nome_dipendente`), non leggibile dal template engine Django, ma usa `nome_dipendente`; il template estende il layout canonico `core/base.html`.
- **[test] `anagrafica/tests.py`**: aggiunte regressioni che renderizzano la lista documenti manuali e verificano i redirect delle impostazioni documenti/subnav.

### Subnav anagrafica

- **[fix] `anagrafica/views.py`**: anche la CRUD subnav configurabile usa `_redirect_impostazioni("navigazione")` per tornare alla tab corretta, evitando lo stesso errore di reverse quando si crea/modifica/elimina categorie o link.

### Lista dipendenti e foto profilo

- **[schema] `anagrafica/models.py`, migration `anagrafica/0017_dipendenteanagraficacivile_foto.py`**: aggiunto campo `foto` su `DipendenteAnagraficaCivile`, salvato sotto `MEDIA_ROOT/anagrafica/dipendenti/<legacy_id>/foto/`.
- **[ux] `anagrafica/views.py`, `anagrafica/templates/anagrafica/pages/dipendenti_list.html`, `anagrafica/templates/anagrafica/pages/dipendente_detail.html`**: la lista `/anagrafica/dipendenti/` viene ordinata lato server per `cognome nome` A-Z prima della paginazione; gli avatar con iniziali sono sostituiti dalla foto dipendente o da un fallback grigio neutro.
- **[form] `anagrafica/forms.py`, `anagrafica/templates/anagrafica/pages/dipendente_create.html`, `anagrafica/views.py`**: i form di creazione/modifica anagrafica civile usano `multipart/form-data` e accettano upload immagine.
- **[test] `anagrafica/tests.py`**: aggiunte coperture per ordinamento A-Z iniziale, rendering foto/fallback e upload foto; riallineati i test di creazione dipendente alla view `dipendente_create`.

### Ratei ferie export XLSX

- **[fix] `anagrafica/views.py`**: l'export `/anagrafica/ratei/export/` non scrive piu sulle celle `A2:D2`, che sono celle mergeate read-only per effetto degli header verticali `A1:A2` ... `D1:D2`; corretto il 500 `MergedCell object attribute 'value' is read-only` con filtri reparto/periodo.
- **[test] `anagrafica/tests.py`**: aggiunta regressione che genera un saldo cedolino, chiama l'export con `periodo` e `reparto`, apre l'XLSX con openpyxl e verifica header/dati principali.

### Assenze SharePoint sync automatico

- **[fix] `config/settings/base.py`, `.env.example`, root `.env.example`**: `ASSENZE_SYNC_ON_PAGE_LOAD` torna attivo di default (`1`) per riabilitare il pull automatico da SharePoint sulle pagine operative assenze quando Graph e' configurato.
- **[setup] `setup_wizard/templates/setup_wizard/wizard.html`, `tools/setup-wizard.html`, `hub_tools/views.py`**: i wizard generano o rigenerano la chiave assenze accesa quando non gia presente.
- **[test] `assenze/tests.py`**: aggiunta copertura mirata per il parser del flag `ASSENZE_SYNC_ON_PAGE_LOAD`.

### Link pubblici SharePoint per QR asset

- **[feat] `assets/models.py`, migration `assets/0069_asset_public_share_links.py`**: aggiunti metadati drive/item SharePoint, link pubblico Graph, stato/errore verifica e token QR pubblico per asset.
- **[feat] `assets/services/sharepoint_public_links.py`**: nuovo servizio Graph dedicato che crea solo link `anonymous/view`, valida cartelle sotto `ASSET CN` e non logga token o segreti.
- **[feat] `assets/management/commands/assets_ensure_public_share_links.py`**: nuovo command con dry-run default, `--apply`, `--force`, `--only-missing` e `--asset-tag` per riconvertire le cartelle asset esistenti.
- **[ux] `assets/views.py`, `assets/urls.py`**: aggiunta route pubblica `/assets/public/<public_qr_token>/`; le etichette QR usano la route pubblica o il link pubblico, mai l'URL SharePoint interno.
- **[fix] `assets/views.py`**: le etichette QR usano `SITE_URL` come base canonica quando configurato, evitando route pubbliche generate in `http` dietro IIS/Waitress.
- **[admin] `assets/admin.py`**: mostrati campi SharePoint pubblico/QR e aggiunte azioni admin per generare, rigenerare/verificare o disabilitare il QR pubblico.
- **[admin] `assets/views.py`, `assets/templates/assets/pages/gestione_admin.html`**: la card SharePoint / Microsoft Graph di `/assets/impostazioni/?tab=config` permette ora di gestire feature flag link pubblici QR, root consentita e ID root/site/drive asset (`SHAREPOINT_ASSET_*`) senza modificare manualmente il file `.env`.
- **[admin] `hub_tools/views.py`, `hub_tools/templates/hub_tools/setup_wizard.html`**: la sezione Microsoft Graph / SharePoint di `/admin-portale/hub/setup-wizard/#sec-graph` centralizza anche URL libreria asset, feature flag link pubblici QR, root consentita e ID root/site/drive asset; la pagina assets rimanda al pannello centrale e continua a salvare le stesse chiavi `.env`.
- **[settings] `config/settings/base.py`, `.env.example`**: aggiunti feature flag e allowlist root SharePoint, con default sicuri e feature spenta.
- **[test] `assets/tests.py`, `hub_tools/tests.py`**: aggiunte coperture per body Graph `createLink`, salvataggio link pubblico, blocco fuori root, command dry-run/apply/only-missing, target QR pubblico, redirect pubblico, base canonica `SITE_URL` per QR, protezione delle altre route `/assets/` e gestione centralizzata `SHAREPOINT_ASSET_*` dal setup wizard hub.

### Link categoria dashboard asset

- **[fix] `assets/templates/assets/pages/asset_dashboard.html`**: i chip categoria e il widget "Asset per categoria" puntano ora a `/assets/lista/?asset_category=<id>` invece del vecchio parametro non gestito `category=<id>`.
- **[fix] `assets/views.py`**: `asset_list` reindirizza i link legacy `?category=<id>` al filtro canonico `?asset_category=<id>`, mantenendo eventuali altri parametri query.
- **[test] `assets/tests.py`**: aggiunti test per link dashboard e compatibilita del parametro legacy.
- **[docs] `README.md`**: chiarito che i collegamenti categoria aprono l'inventario filtrato.

### Specifiche tecniche asset solo compilate

- **[fix] `assets/views.py`**: la card `Specifiche tecniche` del dettaglio asset nasconde sempre i campi vuoti o placeholder (`N/D`, `-`), anche quando il campo dettaglio o categoria e configurato con `show_if_empty`; i valori calcolati non vuoti restano visibili.
- **[fix] `assets/views.py`**: i booleani mancanti in formato `BOOL` non vengono piu trasformati in `No`; solo un valore booleano reale `False` viene mostrato come `No`.
- **[test] `assets/tests.py`**: aggiunte coperture per fallback standard, campi specifici di categoria, booleani `False` e card non renderizzata quando non ci sono specifiche compilate.
- **[docs] `README.md`**: documentato il comportamento della sezione `Specifiche tecniche`.

### Metadati SharePoint sulle cartelle asset

- **[fix] `assets/views.py`**: `_ensure_asset_sharepoint_folder` ora applica le colonne metadato SharePoint anche alla cartella asset `ASSET CN/<tag>` e alle sottocartelle `specifiche`, `interventi`, `manuali`, non solo ai file caricati. La scrittura resta best-effort e usa lo stesso `PATCH .../listItem/fields` gia usato per i documenti.
- **[test] `assets/tests.py`**: aggiunti test per i metadati delle cartelle e per verificare che la creazione/trovamento delle cartelle richiami l'applicazione dei metadati.
- **[docs] `README.md`, `docs/assets/SHAREPOINT_CARTELLE_ASSET_GUIDE.md`**: chiarito che i campi indicizzabili vengono valorizzati anche sulle cartelle create da Graph.

### QR label assets verso SharePoint

- **[ux] `assets/views.py:asset_qr_label`**: la stampa PDF `/assets/view/<id>/qr-label/` ora genera di default un QR verso la cartella SharePoint dell'asset quando `sharepoint_folder_url` e' valorizzato; resta il fallback alla scheda asset se il link SharePoint manca e resta disponibile `?target=detail` per forzare la scheda.
- **[test] `assets/tests.py`**: aggiunti test mirati per verificare il target SharePoint predefinito e la compatibilita del target esplicito `detail`.
- **[docs] `README.md`, `docs/assets/SHAREPOINT_CARTELLE_ASSET_GUIDE.md`**: aggiornata la documentazione del modulo assets per chiarire il comportamento predefinito delle etichette QR.

### Fix branding — silenzio 404 logo compresso mancante

- **[fix] `core/branding.py`**: aggiunta funzione `_local_media_url_exists(url)` che verifica se un path `/media/...` esiste fisicamente su disco prima di restituirlo come URL. I campi `brand_logo_full`, `brand_logo_compact` e `brand_favicon` vengono resettati a stringa vuota se il file non esiste; i template mostrano il monogramma fallback e non viene mai emessa la richiesta HTTP → nessun 404 nei log. URL esterni (http/https) e path non-media non sono interessati dal controllo. Importati `pathlib.Path` e `django.conf.settings`.

### P3.5 — Aggiornamento contatori macchina da tablet

- **[feat] `assets/views.py:work_machine_dashboard`**: aggiunta precarica batch di tutti gli `AssetMeter` delle macchine presenti nella dashboard (`meters_by_asset_id`); calcolata la lista `machines_with_meters` (macchine con almeno un contatore configurato). Aggiunte le due chiavi al context del render.
- **[feat] `assets/templates/assets/pages/work_machine_dashboard.html`**: aggiunta sezione "Contatori macchine" (visibile solo se `machines_with_meters` non è vuoto). Per ogni macchina con contatori mostra nome/tag/reparto e carica via `hx-trigger="load"` il partial `asset_meter_panel.html` già realizzato in P2.2 — form di aggiornamento ore/km/cicli con feedback immediato HTMX senza navigare alla scheda asset.

### P2.2 — Soglie ore/km/cicli operative (`AssetMeter`)

- **[feat] `assets/models.py:AssetMeter`**: nuovo modello per tracciare i contatori ore/km/cicli/altro di ogni asset. Campi: `asset` FK, `meter_type` (HOURS/KM/CYCLES/OTHER), `current_value` DecimalField, `unit_label`, `updated_by` FK, `notes`. Constraint unique su `(asset, meter_type)`. Metodo `update_value(new_value, user)` che aggiorna il valore e crea automaticamente un record `AssetMeterHistory`.
- **[feat] `assets/models.py:AssetMeterHistory`**: nuovo modello di audit trail per ogni aggiornamento contatore. Campi: `meter` FK, `old_value`, `new_value`, `recorded_by`, `recorded_at`.
- **[feat] `assets/models.py:WorkOrder`**: aggiunto campo `meter_value_at_close` (DecimalField nullable) per registrare il valore del contatore al momento della chiusura di un OdL periodico — usato dal command `generate_scheduled_workorders` per calcolare il delta dall'ultimo intervento.
- **[feat] `assets/migrations/0064_assetmeter_assetmeterhistory_and_more.py`**: migrazione per `AssetMeter`, `AssetMeterHistory` e constraint `uniq_asset_meter_type`.
- **[feat] `assets/migrations/0065_workorder_meter_value_at_close.py`**: migrazione per `WorkOrder.meter_value_at_close`.
- **[feat] `assets/admin.py`**: registrazione `AssetMeterAdmin` con inline `AssetMeterHistoryInline` (storico sola lettura) e `AssetMeterHistoryAdmin` (sola lettura, no add).
- **[feat] `assets/views.py:asset_meter_update`**: nuova view `@login_required` a `/assets/<asset_id>/meters/`. GET carica il partial HTMX con i contatori e lo storico recente. POST aggiorna il contatore selezionato, crea un record di storico e loga l'azione con `log_action`. Restituisce il partial `asset_meter_panel.html` per swap `outerHTML` senza reload.
- **[feat] `assets/urls.py`**: URL `assets/<int:asset_id>/meters/` con name `asset_meter_update`.
- **[feat] `assets/templates/assets/components/asset_meter_panel.html`**: nuovo template partial HTMX con `id="asset-meter-panel"`. Mostra le card valore corrente per ogni contatore, form di aggiornamento rapido (select contatore + input valore), storico aggiornamenti in `<details>`. Dark mode via `body.theme-dark`. Fallback nativo POST se HTMX non disponibile.
- **[feat] `assets/templates/assets/pages/asset_detail.html`**: pannello contatori inserito nella card MAINTENANCE dopo la sezione "Analisi costi". Caricato via `hx-trigger="load"` al montaggio della pagina.
- **[feat] `assets/management/commands/generate_scheduled_workorders.py`**: esteso per gestire `threshold_type=HOURS/KM/CYCLES`. Per ogni regola non-DAYS: cerca il contatore `AssetMeter` dell'asset del tipo corretto; calcola il delta rispetto al `meter_value_at_close` dell'ultimo OdL periodico chiuso; genera l'OdL se `delta >= threshold * (1 - warning_days/threshold)`. Salta senza errori se l'asset non ha il contatore del tipo richiesto (`skipped_no_meter`). Summary aggiornato con contatore `SenzaContatore`.

### P3.4 — Report costi manutenzione per asset/periodo

- **[feat] `assets/services/dashboard_kpi.py:get_asset_maintenance_costs`**: nuova funzione che aggrega i costi di manutenzione per un asset su tre orizzonti temporali (mese corrente, trimestre corrente, anno corrente). Calcola: costi OdL per periodo (`Sum("cost_eur")` suddiviso per tipo intervento), costi scadenze amministrative (`AssetAdministrativeDeadlineCompletion.cost_eur`), breakdown per `kind` (etichetta, costo, percentuale, progress bar width), delta YoY (anno corrente vs anno precedente) con badge colorato verde/rosso/neutro. Restituisce `has_data=False` se non ci sono dati per nascondere la sezione. Tutti i `Sum` in try/except indipendenti per compatibilità mssql-django (nessun `ExpressionWrapper`/`DurationField`).
- **[feat] `assets/views.py:asset_detail`**: aggiunta chiamata a `get_asset_maintenance_costs(asset.id, today=today)` con guard `try/except` globale per robustezza su DB mssql. Context key `asset_maintenance_costs` passato al template.
- **[feat] `assets/templates/assets/pages/asset_detail.html`**: aggiunta sezione "Analisi costi" nel card MAINTENANCE, dopo il blocco `deadline_completion_history`. Racchiusa in `{% if asset_maintenance_costs.has_data %}`. Struttura: griglia KPI 3 colonne (mese/trimestre/anno con costo + numero OdL), riga scadenze + totale combinato + badge YoY, breakdown per tipo con barra progress colorata, percentuale e costo assoluto. Dark mode via `body.theme-dark`.

### P3.3 — Landing mobile-first da QR code

- **[feat] `assets/views.py:asset_qr_landing`**: nuova view `@login_required` a `/assets/qr/<asset_tag>/`, accessibile scansionando il QR fisico sull'asset. Mostra: header colorato con nome/tag/reparto, stato asset con badge, giorni dall'ultimo intervento chiuso, prossima scadenza amministrativa, lista OdL aperti (max 5). Usa `asset_tag` come chiave lookup (univoca sul QR fisico). Gestisce il caso asset non trovato con pagina di errore friendly.
- **[feat] `assets/urls.py`**: URL `assets/qr/<str:asset_tag>/` con name `asset_qr_landing`.
- **[feat] `assets/templates/assets/pages/asset_qr_landing.html`**: template mobile-first che estende `core/base.html` (no sidebar, layout a colonna singola, max-width 480px). CTA primaria "Segnala un problema" (→ P3.2 con `?asset=` precompilato), CTA secondarie "Interventi" e "Scheda completa". Dark mode via `prefers-color-scheme`.
- **[feat] `assets/views.py:_asset_qr_target_url`**: aggiunto target `landing` per puntare il QR al `/assets/qr/<asset_tag>/` invece della scheda admin completa — configurabile dal designer etichette.
- **[ux] `assets/views.py` (action buttons)**: aggiunto pulsante "Vista QR mobile" nella zona quick actions della `asset_detail`.

### P3.2 — Form segnalazione rapida operatore

- **[feat] `assets/views.py:asset_quick_report`**: nuova view `@login_required` a `/assets/segnala/`. Mostra un form semplificato per operatori non-admin: seleziona asset (filtrati su non-IT, `status=IN_USE`) oppure descrive il punto di intervento in testo libero; compila titolo, descrizione, categoria MAN, priorità e flag sicurezza. Al POST crea un `Ticket(tipo=MAN, include_in_maintenance_register=True)` con l'identità del richiedente derivata dal `legacy_user` o dal profilo Django. Loga l'azione con `log_action`. Modelli `tickets` importati localmente inside-function. Su successo mostra banner verde con link al ticket creato.
- **[feat] `assets/urls.py`**: URL `assets/segnala/` con name `asset_quick_report`.
- **[feat] `assets/templates/assets/pages/asset_quick_report.html`**: template con form a colonna singola, pre-selezione asset da querystring `?asset=<id>` (utile per link da QR code), categorie MAN dinamiche, radio priorità, checkbox sicurezza, banner successo/errore. CSS `.qr-*` con dark mode.
- **[ux] `assets/views.py:_default_sidebar_buttons`**: aggiunte voci "To-do manutenzione" e "Segnala un problema" come sub-item della sezione Interventi nella sidebar assets.

### P3.1 — Checklist step-by-step in OdL

- **[feat] `assets/models.py:WorkOrderChecklist`**: nuovo modello con `work_order` FK, `step_number`, `description`, `is_done`, `done_at`, `done_by`. Metodo `toggle(user)` che segna/deseleziona lo step aggiornando timestamp e autore.
- **[feat] `assets/migrations/0063_workorderchecklist.py`**: migrazione Django per il nuovo modello.
- **[feat] `assets/views.py`**: tre nuove view HTMX — `workorder_checklist_add` (POST aggiunge step), `workorder_checklist_toggle` (POST inverte `is_done`), `workorder_checklist_delete` (POST elimina step). Tutte restituiscono il partial `workorder_checklist.html` per aggiornamento `outerHTML` senza reload pagina. Aggiunto `HttpResponseForbidden` all'import da `django.http`. View `workorder_detail` arricchita con `checklist_items`, `checklist_done_count`, `checklist_total`, `is_open`.
- **[feat] `assets/urls.py`**: tre nuove URL — `wo_checklist_add`, `wo_checklist_toggle`, `wo_checklist_delete`.
- **[feat] `assets/templates/assets/components/workorder_checklist.html`**: nuovo template partial HTMX con `id="wod-checklist-section"`. Mostra badge progresso (n/tot), lista step con toggle/delete, form aggiunta step inline. Toggle e delete usano `hx-post` + `hx-swap="outerHTML"` per aggiornamento reattivo senza JS custom. Fallback nativo se HTMX non caricato.
- **[ux] `assets/templates/assets/pages/workorder_detail.html`**: incluso il partial `workorder_checklist.html` tra la card principale e la card allegati. Aggiunte classi CSS `.wod-cl-*` con dark mode.

### P2.4 — Consolidamento `PeriodicVerification` → `MaintenanceRule`

- **[feat] `assets/models.py:PeriodicVerification`**: aggiunto campo `is_legacy = BooleanField(default=False, db_index=True)`. Se `True` indica che il trigger temporale è stato migrato a una `MaintenanceRule`; il record rimane come riferimento fornitore/contratto e non genera nuovi OdL automatici.
- **[feat] `assets/migrations/0062_periodicverification_is_legacy.py`**: migrazione Django per il nuovo campo.
- **[feat] `assets/management/commands/migrate_periodic_to_rules.py`** (nuovo file): command Django per la migrazione dati. Per ogni `PeriodicVerification` attiva e non-legacy con tutti gli asset nella stessa `AssetCategory`: converte `frequency_months` in giorni (×30), trova o crea il `MaintenanceInterventionTemplate` equivalente, trova o crea la `MaintenanceRule` corrispondente, poi imposta `is_legacy=True`. Supporta `--dry-run`, `--apply`, `--pv-id` (singolo piano), `--only-legacy` (mostra piani già migrati). Idempotente: esecuzioni multiple non creano duplicati. Salta piani senza asset o con categorie miste.
- **[ux] `assets/templates/assets/pages/periodic_verification_list.html`**: aggiunto banner giallo "Sezione in transizione" con spiegazione del percorso di migrazione. Mostra dinamicamente il conteggio piani già migrati (`is_legacy=True`). Aggiunte classi CSS `.pv-banner-deprecation` con dark mode.
- **[feat] `assets/views.py:periodic_verification_list`**: aggiunto `legacy_verification_count` al contesto (sum dei piani `is_legacy=True` tra i risultati visualizzati).

### P2.3 — Vista "To-do manutenzione" per tecnico/reparto

- **[feat] `assets/views.py:maintenance_todo`**: nuova view `@login_required` alla URL `/assets/manutenzione/todo/`. Aggrega in un'unica pagina: OdL aperti (distinti in ritardo/recenti, filtro per esecutore se non admin), scadenze amministrative in scadenza entro 30 gg, verifiche periodiche in scadenza entro 30 gg, macchine utensili con `next_maintenance_date` nei prossimi 14 gg. Integrazione con modulo `tickets` per mostrare ticket MAN aperti. Filtro per reparto. KPI chips nell'header con conteggi e link alle view di dettaglio.
- **[feat] `assets/templates/assets/pages/maintenance_todo.html`**: template con 5 sezioni (OdL / Scadenze / Verifiche / Macchine / Ticket MAN), colori semantici rosso/ambra/verde per priorità, tabelle responsive, dark mode. Sezione ticket MAN condizionale (visibile solo se ci sono ticket).
- **[feat] `assets/urls.py`**: aggiunta URL `assets/manutenzione/todo/` con name `maintenance_todo`.

### P2.1 — Management command `generate_scheduled_workorders`

- **[feat] `assets/management/commands/generate_scheduled_workorders.py`** (nuovo file): comando Django che genera automaticamente `WorkOrder` periodici da `MaintenanceRule` attive con `threshold_type=DAYS`. Per ogni coppia (asset, rule): salta se override `is_disabled=True`; salta se esiste già un WO OPEN per quella coppia; calcola `next_due = last_wo_done.closed_at + threshold_days` (o `today` se mai eseguito); crea OdL se `next_due <= today + rule.warning_days`. Rispetta `MaintenanceRuleAssetOverride` per soglia e template. Idempotente: nessun duplicato su esecuzioni multiple. Supporta `--dry-run`, `--category` (filtra per categoria), `--limit`. Precarica override e OdL aperti in batch per evitare N+1.

### P1.4 — Management command `send_maintenance_reminders`

- **[feat] `assets/management/commands/send_maintenance_reminders.py`** (nuovo file): comando Django schedulabile via Windows Task Scheduler. Controlla 3 fonti: `AssetAdministrativeDeadline` in scadenza entro N giorni (default 30), `PeriodicVerification` in scadenza entro N giorni, `WorkOrder` aperti da più di 21 giorni. Destinatari configurabili via `SiteConfig.assets_reminder_emails`, altrimenti `settings.ADMINS`, altrimenti superuser con email. Soglia giorni configurabile via `SiteConfig.assets_reminder_days` o `--deadline-days`. Supporta `--dry-run` e `--recipients`. Invio via `django.core.mail.send_mail` (SMTP già configurato nel progetto).

### P1.3 — Auto-aggiornamento `next_maintenance_date` alla chiusura OdL periodico

- **[feat] `assets/models.py:WorkOrder.close()`**: dopo il `save()` dell'OdL, se `status=DONE`, `origin=PERIODIC` e `maintenance_rule_id` è valorizzato, tenta di ricalcolare `WorkMachine.next_maintenance_date = closed_date + timedelta(days=rule.threshold_value)` sulla macchina utensile collegata (`asset.work_machine`). Condizionato a `threshold_type=DAYS` (gli altri tipi non sono ancora operativi). L'aggiornamento è silenzioso in caso di errore (try/except) per non bloccare la chiusura OdL. Nessun effetto su OdL correttivi/manuali.

### P1.2 — Timeline scadenze amministrative eseguite nella scheda asset

- **[feat] `assets/views.py:asset_detail`**: aggiunta query `deadline_completion_history` che recupera i `AssetAdministrativeDeadlineCompletion` dell'asset con `select_related("deadline", "completed_by")`, ordinati per `-completed_on, -id`, limite 20. Il risultato è esposto al template come `deadline_completion_history`.
- **[feat] `assets/templates/assets/pages/asset_detail.html`**: nella card `MAINTENANCE`, dopo la tabella "Storico interventi", aggiunta sezione condizionale "Scadenze amministrative eseguite" — tabella con colonne Data / Tipo (badge) / Scadenza (link) / Eseguita da / Costo / Stato (badge verde "Completato"). Sezione visibile solo se esistono completamenti. Nessuna query N+1 grazie a `select_related`.

### P1.1 — KPI performance manutenzione: dashboard asset arricchita con MTTR, downtime, costi, backlog

- **[feat] `assets/services/dashboard_kpi.py`**: aggiunto `Avg` all'import. Nuova funzione `get_maintenance_performance_kpis(today, lookback_days=30)` che calcola `mttr_hours` (media ore OdL correttivi chiusi), `downtime_hours_month`, `maintenance_cost_month`, `wo_open_by_kind` con `percent` relativo al totale, `wo_open_total`, `ticket_man_open`, `wo_closed_month`, `has_data`. Ogni aggregazione in try/except indipendente; compatibile con mssql-django (no ExpressionWrapper/DurationField).
- **[feat] `assets/views.py:asset_dashboard`**: importata e chiamata `get_maintenance_performance_kpis`; risultato passato al template come `maintenance_perf` (wrappato in try/except esterno).
- **[feat] `assets/templates/assets/pages/asset_dashboard.html`**: aggiunta sezione "Performance manutenzione" con panel `.ad-perf` contenente: 4 card (MTTR, downtime ore, costo mese, ticket MAN); 2 panel minibar (OdL per tipo con link filtrati + riepilogo mese). Sezione condizionale su `maintenance_perf.has_data`. Numeri cliccabili verso `assets:wo_list` e `tickets:gestione_list?tipo=MAN`. Aggiunte classi CSS `.ad-perf`, `.ad-perf-grid`, `.ad-perf-panel-row`, `.ad-perf-val-link` con dark mode.
- **[feat] `docs/ai/10_MAINTENANCE_MODERNIZATION.md`**: creato documento checklist operativa del piano di ammodernamento manutenzione (P1.1→P3.5) con stato aggiornabile da agenti AI.
- **[chore] `docs/ai/00_INDEX.md`**: aggiunto riferimento al nuovo file `10_MAINTENANCE_MODERNIZATION.md`.

### Dashboard famiglie asset — striscia manutenzione: avviso "tutto in ordine" e numeri cliccabili

- **[ux] `assets/views.py:asset_administrative_deadline_list`**: aggiunti `family_filter` e `family_label` al context del render (erano calcolati ma non esposti al template).
- **[ux] `assets/templates/assets/pages/device_list.html`**: la striscia `.dv-maint-strip` è ora sempre visibile; quando `maint_kpis.coinvolti == 0` mostra un avviso verde "Nessuna scadenza nei prossimi 90 giorni — tutto in ordine"; il numero "Coinvolti" linka a `asset_administrative_deadline_list?family=it`; il numero "Da manutentare" linka alla stessa pagina con `status=overdue` (o `all` se zero). Aggiunte classi CSS `.dv-maint-ok-notice` e override link su `.dv-maint-val a`.
- **[ux] `assets/templates/assets/pages/work_machine_dashboard.html`**: stessa logica con classi `wmd-`; il numero "Coinvolti" linka a `work_machine_list`; "Da manutentare" linka a `#wmd-reminder` (anchor sulla card reminder nella stessa pagina); aggiunto `id="wmd-reminder"` all'article della card Reminder manutenzione.

### Dashboard famiglie asset — striscia manutenzione in scadenza

- **[feat] `assets/services/dashboard_kpi.py:get_maintenance_kpis_for_types`**: nuova funzione single-family che riceve una lista di `asset_type` e restituisce `coinvolti / manutentati / da_manutentare / percent_done` con 2 query su `AssetAdministrativeDeadline` (finestra 90 gg) e `AssetAdministrativeDeadlineCompletion` (lookback 365 gg).
- **[feat] `assets/views.py:device_list`**: aggiunta chiamata a `get_maintenance_kpis_for_types(IT_DEVICE_TYPES)`; risultato passato al template come `maint_kpis`.
- **[feat] `assets/views.py:work_machine_dashboard`**: derivati `coinvolti / manutentati / da_manutentare / percent_done` dai valori già presenti in contesto senza query aggiuntive; passati come `maint_kpis`.
- **[feat] `assets/templates/assets/pages/device_list.html`**: aggiunta striscia `.dv-maint-strip` con 3 indicatori + barra di avanzamento colorata dopo i KPI; fix 5 inline style preesistenti estratti in classi CSS.
- **[feat] `assets/templates/assets/pages/work_machine_dashboard.html`**: stessa striscia con classi `wmd-maint-*`; barre `.wmd-progress-fill` migrate da `style="width:X%"` a `data-pct` + JS; fix inline style cella vuota → `wmd-td-empty`.

### Registro manutenzione asset — manutenzione pianificata nel dettaglio singolo asset

- **[fix] `assets/views.py:asset_detail`**: rimosso codice morto (prima assegnazione di `maintenance_rows` da `asset.workorders.select_related(...).all()[:10]` che veniva immediatamente sovrascritta dal registro unificato `collect_asset_maintenance_register`).
- **[feat] `assets/views.py:asset_detail`**: aggiunta `asset_schedule_rows` al contesto del template; la variabile è già calcolata da `build_day_based_maintenance_schedule_rows` ma non era esposta alla view.
- **[feat] `assets/templates/assets/pages/asset_detail.html`**: nella card `MAINTENANCE` aggiunta sezione "Manutenzione pianificata" (tabella regole periodiche con colonne Intervento / Cadenza / Ultima esecuzione / Prossima scadenza / Stato e badge colorati per stato scadenza) prima della sezione "Storico interventi". Se l'asset non ha regole attive, viene mostrato un messaggio esplicativo.
- **[ux] `assets/templates/assets/pages/asset_detail.html`**: aggiunto pulsante "Scadenzario" (link a `asset_maintenance_schedule_url`) nell'header della card `MAINTENANCE`, accanto a "Regole manutenzione" e "Manutenzione periodica".

### Dashboard — widget manutenzione in scadenza per famiglia asset

- **[feat] `assets/services/dashboard_kpi.py:get_maintenance_status_by_family`**: nuova funzione che raggruppa asset per famiglia di `asset_type` (IT, Produzione, Videosorveglianza, Altro) e per ogni famiglia calcola — in 2 query — `coinvolti` (asset con scadenza attiva entro 90 gg), `manutentati` (sottoinsieme con almeno un'esecuzione negli ultimi 365 gg) e `da_manutentare`. Aggiunta anche costante `_ASSET_TYPE_FAMILY_MAP` e dizionario `_TYPE_TO_FAMILY` per il mapping tipo→famiglia. Aggiunta import di `AssetAdministrativeDeadlineCompletion` alle importazioni del modulo.
- **[feat] `dashboard/views.py:dashboard_hub_preview`**: aggiunta chiamata a `get_maintenance_status_by_family()` con risultato passato al template come `maintenance_by_family`; wrappato in `try/except` per non bloccare la dashboard in caso di errore.
- **[feat] `core/templates/core/pages/dashboard_hub_preview.html`**: aggiunta sezione "Manutenzione in scadenza" nella colonna principale del Hub Preview, prima dei moduli; tabella con righe per famiglia (Coinvolti, Manutentati, Da manutentare) + barra di avanzamento colorata (verde ≥100%, giallo ≥50%, rosso <50%); larghezza barra impostata via JS da attributo `data-pct` per evitare inline style; sezione nascosta se `maintenance_by_family` è vuoto.
- **[feat] `core/static/core/css/hub_dashboard.css`**: aggiunte classi `.hd-maint-*` per la tabella, i valori numerici colorati e la barra di avanzamento; responsive: colonna barra nascosta sotto 700px.

### Selezione multipla e modifica massiva asset (bulk edit) — dropdown reali e campi aggiuntivi

- **[feat] `assets/templates/assets/pages/asset_list.html`**: completato il JS `applyBulkBtn` aggiungendo i campi `asset_type` e `assignment_location` alla lista di triple campo/checkbox/valore; tutti e 8 i campi del modal ora vengono correttamente inviati alla view.
- **[feat] `assets/templates/assets/pages/device_list.html`**: modal bulk edit completamente riscritto — reparto, produttore, modello, collocazione ora usano `<select>` alimentati da `AssetListOption` (context `bulk_list_options`); aggiunti campi tipo asset (da `asset_type_choices`), categoria (da `bulk_asset_categories`), collocazione e note; JS aggiornato con le 8 triple; stili inline estratti in classi CSS `.dv-bulk-notes-row` e `.dv-bulk-notes-ta`.
- **[feat] `assets/templates/assets/pages/work_machine_list.html`**: stesso intervento di `device_list.html` con prefisso `wm-`; classi CSS `.wm-bulk-notes-row` e `.wm-bulk-notes-ta` aggiunte al blocco stile.
- **[feat] `assets/views.py:asset_bulk_update`**: aggiunto supporto a `asset_category_id` tra i campi modificabili in blocco; la validazione verifica che l'ID sia un intero e che la categoria esista, oppure accetta stringa vuota per rimuovere la categoria.

### Validazione obbligatoria form Nuovo kickoff (`tasks/projects/new/`)

- **[fix] `tasks/forms.py:ProjectKickoffForm.__init__`**: rimosso `client_name` dalla lista dei campi `required=False`; il campo "Cliente" è ora obbligatorio a livello di form Django.
- **[fix] `tasks/forms.py:ProjectKickoffForm.clean`**: aggiunta validazione che almeno uno tra `project_manager`, `capo_commessa` e `programmer` sia compilato; in caso contrario viene sollevato un `ValidationError` con messaggio esplicito sul team di progetto.
- **[ux] `tasks/templates/tasks/project_create.html`**: aggiunti indicatori visivi obbligatorietà (`*` rosso su "Cliente", `*` + hint su "Team di progetto"); stili estratti in classi CSS `.kc-required` e `.kc-required-hint` nel blocco `<style>` del template.

### Fix ProgrammingError SQL Server — ORDER BY senza GROUP BY in `_build_asset_category_admin_rows`

- **[fix] `assets/views.py:_build_asset_category_admin_rows`**: aggiunto `.order_by()` alle 4 query aggregate (`asset_stats`, `field_stats`, `child_counts`, `open_workorders`) che usano `.values().annotate()` senza ordinamento esplicito. Su SQL Server, `mssql-django` applicava automaticamente il `Meta.ordering` del modello all'`ORDER BY` senza aggiungerlo al `GROUP BY`, producendo l'errore 8127 (`assets_asset.name` non valido in ORDER BY). La pagina `/assets/impostazioni/?tab=categorie` ora funziona correttamente.

### Audit log download allegati sensibili (Agent 3 — download audit logging)

- **[security] Audit trail download allegati ticket** (`tickets/views.py:ticket_download_allegato`): aggiunto `log_action(request, "download_allegato", "tickets", ...)` con `esito` `success`/`denied`/`not_found`. Su success vengono loggati `allegato_id`, `ticket_id` e `filename` logico (mai path fisico, token o contenuto file). Su `denied` (utente non richiedente/gestore/admin) viene loggato `motivo: permission_denied` senza esporre il nome del file.
- **[security] Audit trail download allegati Diario Preposto** (`diario_preposto/views.py:allegato_download`): aggiunto `log_action(request, "download_allegato", "diario_preposto", ...)` su success/not_found con `allegato_id`, `segnalazione_id`, `filename`. Il payload non contiene path fisici.
- **[security] Audit trail download immagini timbri** (`timbri/views.py:serve_timbri_image`): aggiunto `log_action(request, "download_timbri_image", "timbri", ...)` con `esito` `success`/`denied`/`not_found`. Su denied (utente senza permessi ACL) viene loggato `permission_denied` senza esporre il nome file fisico.
- **[security] Audit trail esteso download deadline asset** (`assets/views.py:admin_deadline_attachment_download`): l'azione `download_admin_deadline_attachment` ora copre anche i percorsi `denied` (non admin) e `not_found`, oltre al success preesistente. Aggiunto `filename` logico al payload success.
- **[test] Copertura audit download** (`tickets/tests.py:TicketDownloadAuditTests`, `diario_preposto/tests.py:test_allegato_download_authenticated_creates_audit_log`, `assets/tests.py:test_admin_deadline_attachment_download_creates_audit_log`/`test_admin_deadline_attachment_denied_creates_audit_without_path`, `timbri/tests.py:TimbriDownloadAuditTests`): aggiunti test che verificano (1) creazione `AuditLog` con `esito=success` su download autorizzato, (2) audit con `esito=denied`/`motivo=permission_denied` su accesso non autorizzato, (3) assenza nel payload audit di path fisici (`MEDIA_ROOT`/`ASSETS_PRIVATE_ROOT`/`TIMBRI_PRIVATE_ROOT`), contenuto file e nome file fisico in caso di denied.

### Diario Preposto — Storage privato allegati segnalazioni (Agent 1 — file exposure audit)

- **[security] Allegati Diario Preposto non piu' esposti via /media/ pubblico** (`diario_preposto/storage.py`, `diario_preposto/models.py`, `diario_preposto/migrations/0005_private_storage.py`, `config/settings/base.py`): introdotto `PrivateDiarioPrepostoStorage` (stesso pattern di `tickets/storage.py` e `assets/storage.py`). Il `FileField` di `SegnalazioneAllegato` usa ora `DIARIO_PREPOSTO_PRIVATE_ROOT` (default `BASE_DIR/media_private`). I file legacy gia' presenti in `MEDIA_ROOT` restano leggibili come fallback solo tramite la view di download protetta (mai via URL diretto). Lo storage solleva `NotImplementedError` se qualcuno richiama `.url` sull'allegato.
- **[security] Nuova view di download autenticata** (`diario_preposto/views.py:allegato_download`, `diario_preposto/urls.py`): aggiunta `GET /diario-preposto/allegato/<id>/download/` con `@login_required`. Restituisce `FileResponse` `as_attachment=True` con `Content-Type` derivato dal nome originale; risponde `404` se il file e' assente. Le segnalazioni di sicurezza non sono piu' raggiungibili anonimamente via URL `/media/diario_preposto/...`.
- **[security] API e cancellazioni non leggono piu' `.path`/`.url`** (`diario_preposto/views.py:api_allegato_upload`, `api_allegato_delete`, `elimina`): l'upload risponde ora con `reverse('diario_preposto:allegato_download', ...)` invece di `allegato.file.url`; le rimozioni usano `allegato.file.storage.delete(name)` invece di `os.remove(allegato.file.path)`, supportando sia il nuovo storage privato sia i path legacy in `MEDIA_ROOT`.
- **[security] Template aggiornati al download protetto** (`diario_preposto/templates/diario_preposto/pages/dettaglio.html`, `form.html`): i link "Scarica" puntano a `{% url 'diario_preposto:allegato_download' a.pk %}` (rimosso `target="_blank"` su URL autenticato per evitare apertura in nuova tab gestita dal browser senza redirect login).
- **[test] Copertura download autenticato** (`diario_preposto/tests.py:SegnalazioneAllegatoDownloadTests`): aggiunti `test_allegato_download_requires_login` (anonimo riceve redirect login, contenuto file non leakato) e `test_allegato_download_authenticated_returns_file` (utente autenticato scarica il file con `Content-Disposition: attachment`).

### Deployment hardening — `validate_deployment` (Agent 4)

- **[security] Check DJANGO_SECRET_KEY rafforzato** (`core/management/commands/validate_deployment.py:check_django_settings`): oltre al placeholder, ora si segnalano: prefisso `django-insecure-` (chiave da `startproject`) e lunghezza inferiore a 50 caratteri. Severita' FAIL in prod, WARN in dev/test.
- **[security] DEBUG=True in prod ora e' FAIL** (`core/management/commands/validate_deployment.py:check_django_settings`, `check_security`): non piu' WARN, in coerenza con esposizione tracebacks.
- **[security] ALLOWED_HOSTS wildcard '*'** (`core/management/commands/validate_deployment.py:check_django_settings`): nuovo check che blocca in prod (FAIL) e avvisa in dev/test (WARN) sull'host header poisoning.
- **[security] DJANGO_LOG_DIR obbligatorio in prod** (`core/management/commands/validate_deployment.py:check_django_settings`): allineamento al guard di `config/settings/base.py` (resta loggato come check esplicito anche quando si esegue il comando con `--settings=config.settings.test` contro un `.env` produttivo).
- **[security] ASSETS_PRIVATE_ROOT containment check** (`core/management/commands/validate_deployment.py:check_static_media`, helper `_path_under`): nuovo check FAIL/WARN che impedisce di posizionare lo storage privato sotto `MEDIA_ROOT` (esposizione web). Aggiunta anche presenza obbligatoria in prod.
- **[security] SESSION_COOKIE_SECURE / CSRF_COOKIE_SECURE** (`core/management/commands/validate_deployment.py:check_security`): nuovi check con severita' adattata all'ambiente (FAIL in prod, WARN altrove).
- **[security] CSRF_TRUSTED_ORIGINS no-wildcard** (`core/management/commands/validate_deployment.py:check_security`): rileva valori `*`, `*://*` e prefissi wildcard (FAIL in prod, WARN altrove).
- **[security] AUTOMAZIONI_TRIGGER_DB_APPLY_ENABLED** (`core/management/commands/validate_deployment.py:check_security`): warning esplicito in prod quando attivato (privilegio elevato: DDL diretta su DB).
- **[infra] Helper severita'** (`core/management/commands/validate_deployment.py:_is_prod_environment`, `_severity_for_env`, `_path_under`): nuove utility che rilevano l'ambiente da `DJANGO_SETTINGS_MODULE`/`MONITORING_ENVIRONMENT` e scelgono FAIL in prod / WARN altrove. Mantengono la compatibilita' di `--settings=config.settings.test`.
- **[test] Copertura nuovi check** (`core/test_validate_deployment.py`): aggiunti test per `SECRET_KEY` corta (`test_short_secret_key_warns_outside_prod`), prefisso `django-insecure-` (`test_django_insecure_prefix_warns_outside_prod`), `ALLOWED_HOSTS=['*']` (`test_wildcard_allowed_hosts_warn_outside_prod`), `ASSETS_PRIVATE_ROOT` sotto `MEDIA_ROOT` (`test_assets_private_root_under_media_root_warns`), `CSRF_TRUSTED_ORIGINS=['*']` (`test_csrf_trusted_origins_wildcard_warns`).
- **[docs] `.env.example`** (`.env.example`, `django_app/.env.example`): aggiunti commenti sui requisiti di `DJANGO_SECRET_KEY` (lunghezza, no `django-insecure-`), `DJANGO_ALLOWED_HOSTS` (no wildcard), `DJANGO_LOG_DIR` (obbligatorio in prod), `ASSETS_PRIVATE_ROOT` (no sotto `MEDIA_ROOT`), `AUTOMAZIONI_TRIGGER_DB_APPLY_ENABLED` (warning in prod) e nuovo placeholder `DJANGO_CSRF_TRUSTED_ORIGINS`.

### Hub Preview — Gestione pulsanti, branding e dashboard principale

- **[feat] Pulsanti Manager** (`hub_tools/views.py`, `hub_tools/urls.py`, `hub_tools/templates/hub_tools/pulsanti_manager.html`): nuova sezione admin `/admin-portale/hub/pulsanti/` per la gestione completa dei pulsanti hub. Permette inserimento, modifica, cambio logo (upload file PNG/JPG/SVG/WebP max 2 MB), abilitazione/disabilitazione e cancellazione. I loghi vengono salvati in `media/hub_pulsanti_logos/` e la path aggiornata in `ui_pulsanti_meta.card_image`. Include API endpoints JSON: `save`, `logo`, `toggle`, `delete`.
- **[feat] Branding Hub Preview** (`hub_tools/views.py`, `hub_tools/urls.py`, `hub_tools/templates/hub_tools/branding.html`): nuova sezione admin `/admin-portale/hub/branding/` per personalizzazione grafica della pagina hub-preview. Supporta: logo hero (upload, rimozione), titolo e sottotitolo hero, colore sfondo pagina, gradiente hero (colore 1 e 2). Preview live dei colori e testi nell'interfaccia. I valori sono salvati in `SiteConfig` con chiavi `hub_hero_title`, `hub_hero_sub`, `hub_bg_color`, `hub_hero_color_1`, `hub_hero_color_2`, `hub_logo_url`.
- **[feat] Hub come dashboard principale** (`hub_tools/views.py`, `core/accounts/views.py`): aggiunto toggle nella pagina branding per impostare hub-preview come dashboard post-login per tutti gli utenti non-admin. Implementato tramite `SiteConfig.module_login_redirect_target = "hub-preview"`. Il sistema di redirect ora riconosce il target speciale `hub-preview` → `reverse("dashboard_hub_preview")`.
- **[feat] Admin toolbar inline su hub-preview** (`core/templates/core/pages/dashboard_hub_preview.html`, `core/static/core/css/hub_dashboard.css`): barra admin (visibile solo agli staff) in cima alla hub-preview con link rapidi a "Pulsanti" e "Personalizza". Include stili dark-mode.
- **[feat] Branding dinamico hub-preview** (`dashboard/views.py`): la view `dashboard_hub_preview` legge le chiavi branding da `SiteConfig` e le passa al template. Il template applica i colori come CSS vars inline e mostra il logo nell'hero se configurato.
- **[feat] Hub Tools index** (`hub_tools/views.py`, `hub_tools/urls.py`, `hub_tools/templates/hub_tools/hub_index.html`): nuova pagina indice `/admin-portale/hub/` che raccoglie tutti gli strumenti di gestione del portale (pulsanti, branding, moduli, categorie, notifiche, database, setup wizard, guide) in un'unica griglia di card. Tutte le sottopagine hub aggiornate con link di ritorno all'indice hub invece dell'admin portale.

## 0.9.18 - 2026-04-16

### Modulo Automazioni

- **[feat] Endpoint approvazione per Entra Application Proxy**: aggiunti `GET /approval-actions/approve/<token>/` e `GET /approval-actions/reject/<token>/` — endpoint one-click ottimizzati per essere pubblicati selettivamente dietro Entra Application Proxy. Riusano `process_approval_decision()` senza duplicare logica. L'identità dell'approvatore viene estratta (in ordine) da sessione Django, header `X-MS-CLIENT-PRINCIPAL-NAME` (Entra proxy) o `X-Forwarded-Email`. Ogni decisione è tracciata in AuditLog con `via=entra_proxy`. La route è in `MIDDLEWARE_EXEMPT_PREFIXES` (token UUID come credenziale, analoga a `/automazioni/approvazione/`).
- **[security] Validazione attore approvazione condivisa tra canale web e mailbox Graph**: introdotto `automazioni/approval_security.py` con `validate_approval_actor(token_str, actor_email) -> ApprovalActorValidation`. Fail-closed: verifica in ordine identità non vuota → token valido → approval esistente → stato PENDING → non scaduta → approver_emails configurata → attore nella lista. Il canale web (`_handle_approval_proxy`) ora usa lo stesso helper del canale mailbox Graph (`_validate_sender`), eliminando il gap di sicurezza pregresso. La pagina esito distingue `no_identity`, `not_found`, `already_decided`, `expired`, `unauthorized`, `no_approvers`. Denial tracciate in AuditLog con azione `approval_proxy_denied`.
- **[fix] `log_action` non crasha più con `AnonymousUser`**: `display_name_for_user` in `core/impersonation.py` ora guarda `is_authenticated` prima di chiamare `get_full_name()`, evitando l'`AttributeError` sui path esenti da login.
- **[test] 28 test approvazione proxy + 11 unit test `ApprovalSecurityTests`**: coprono happy path, estrazione identità (sessione/header/priorità), tutti i blocchi di sicurezza (unauthorized, no_identity, expired, already_decided, not_found, no_approvers), audit log per approval e denial, retrocompatibilità `_validate_sender` mailbox Graph.

- **[feat] Monitor salute del poller nella queue admin**: la vista `/admin-portale/automazioni/queue/` e il dettaglio evento mostrano ora una card con task Windows locale `Portale Hub Polling Mail`, stato dell'ultimo job monitorato `automazioni_process_queue`, alert `missing/stuck`, ultimo messaggio runtime e freshness del log `django_app/logs/automation_queue.log`. L'obiettivo e' permettere diagnosi autonome quando gli eventi restano `pending`.
- **[ops] Script locale `register-local-polling-mail.ps1`**: aggiunto in `deployment/scripts/` uno script ripetibile per registrare/aggiornare il task schedulato locale del repository, senza dipendere dalla struttura deploy `C:\\PortaleNovicrom\\prod|test`.
- **[ops] Poller queue Windows eseguito in modalita silent**: i task registrati da `register-local-polling-mail.ps1` e `schedule-automation-queue.ps1` usano ora il wrapper `run-automation-queue-poller.ps1`, che avvia `process_automation_queue` senza finestre console visibili e continua a scrivere nel log `automation_queue.log`.
- **[test] Queue admin isolata dal Task Scheduler reale**: i test SSR della queue patchano ora il nuovo snapshot salute del poller, cosi restano verdi e indipendenti dalla macchina Windows o dai task registrati localmente.

## 0.9.17 - 2026-04-15

### Modulo Assenze

- **[fix] Salvataggio locale richieste senza conflitti FK su `capi_reparto`**: `assenze/views.py` risolve ora `capo_reparto_id` verso il record locale reale di `capi_reparto`, invece di usare l'id dell'utente legacy. Il form accetta quindi sia email sia lookup SharePoint del capo reparto senza far fallire l'`INSERT` su SQL Server.
- **[test] Copertura regressione mapping capo reparto**: aggiunti test mirati per la risoluzione `form value -> capi_reparto.id`, sia nel caso di capo collegato a un `legacy_user_id` sia nel fallback da lookup numerico SharePoint.

### Hub Tools

- **[fix] Icone corrotte nel catalogo guide nascoste invece di comparire come testo sporco**: `hub_tools/views.py` svuota ora le icone con encoding sospetto e i template `guide_list.html` / `guide_view.html` renderizzano l'icona solo se valida, evitando prefissi tipo `ðŸ...` davanti ai titoli delle card e del visualizzatore.

### Modulo Automazioni — Fix queue e schema SQL Server

- **[fix] Queue automazioni compatibile con schema legacy senza `execute_after`**: `process_automation_queue` non va piu in crash sui database dove `dbo.automation_event_queue` non e' ancora stata riallineata. Il fetch degli eventi `pending` degrada automaticamente senza il filtro schedulato, cosi trigger `INSERT`/`UPDATE` come quelli di `assenze` tornano processabili.
- **[fix] `assenze -> send_approval` riallineato a `capi_reparto.id`**: l'arricchimento runtime del payload automazioni risolve ora `capo_email` prima dal record locale `capi_reparto` (campo `indirizzo_email`, con fallback `utente_id`), invece di trattare sempre `capo_reparto_id` come `utenti.id`. Le regole di approvazione sulle nuove richieste assenza tornano quindi a inviare l'email al responsabile corretto.
- **[feat] Queue admin con interventi manuali `Stoppa` / `Elimina`**: la vista `/admin-portale/automazioni/queue/` e il dettaglio evento espongono ora pulsanti operativi per bloccare un evento `pending` senza eseguirlo oppure eliminarlo quando e' ancora `pending/error` e non ha run log collegati. L'obiettivo e' permettere bonifiche autonome su duplicati o code sporche senza passare da shell/SQL.
- **[ops] Riallineamento idempotente della queue SQL Server**: `sql/automation_event_queue.sql` aggiunge ora la colonna `execute_after` se manca gia su ambienti esistenti, evitando di dover ricreare la tabella tecnica.
- **[guardrail] Errore esplicito sulle azioni schedulate**: quando una regola prova a schedulare un evento futuro (`delay`, `do_until`, ecc.) e la colonna `execute_after` non e' ancora presente, il runtime restituisce ora un messaggio di remediation chiaro invece di un generico errore SQL.
- **[test] Copertura regressione queue schema drift**: aggiunti test mirati per il fetch della queue con e senza colonna `execute_after`.

## 0.9.16 - 2026-04-15

### Modulo Automazioni — Impostazioni IMAP approvazioni

- **[feat] Nuova pagina `/admin-portale/automazioni/impostazioni/`**: il modulo espone una superficie amministrativa dedicata per vedere lo stato runtime IMAP delle approvazioni, salvare la mailbox tecnica globale `automazioni_approval_mailbox` in `SiteConfig` e lanciare subito `poll_approval_mailbox` dal portale con pulsante `Esegui ora`.
- **[feat] Pannello IMAP riusato anche in `Config SRV`**: la card `Configurazione SMTP` di `/admin-portale/ldap/` mostra ora anche il riepilogo `APPROVAL_IMAP_*`, il pulsante di esecuzione immediata del polling mailbox e un link rapido verso le impostazioni automazioni, cosi SMTP e mailbox approvazioni si gestiscono nello stesso hub.
- **[fix] Config IMAP davvero editabile da UI**: sia `/admin-portale/automazioni/impostazioni/` sia il pannello IMAP dentro `Config SRV` espongono ora i campi `APPROVAL_IMAP_*` con salvataggio in `.env`, mantenimento password se il campo resta vuoto e refresh del runtime corrente per poter testare subito il polling senza dover riaprire la shell.
- **[test] Copertura mirata admin/runtime**: aggiunti test per rendering pagina impostazioni automazioni, salvataggio mailbox tecnica, trigger manuale del polling e parsing del riepilogo runtime del comando.

### Tooling sviluppo

- **[fix] `django_app/avvia_server.bat` non usa piu `Get-CimInstance Win32_Process` per cercare i `runserver` attivi**: su alcune macchine Windows la query CIM/WMI resta bloccata e il batch sembrava fermarsi su `Chiudo tutte le istanze Django runserver attive...`. Lo script ora libera solo il listener `LISTENING` sulla porta `8000`, stampa esplicitamente se non trova nulla e prosegue subito con l'avvio del server dev.

### Modulo Automazioni — Template Email Approvazioni

- **[feat] `ApprovalEmailTemplate` — template riutilizzabili per le mail di approvazione**: nuovo modello (migration 0011) che permette di definire oggetto, titolo, intro, corpo libero HTML, facts/riepilogo, label CTA e modalità di consegna per le email generate da `send_approval`. I template sono gestibili da `/automazioni/template-approvazioni/` (voce "Template approvazioni" nella subnav del modulo).
- **[feat] Tre modalità di consegna per le CTA**: `portal_links` (link HTTP al portale, default), `mail_reply` (link `mailto:` verso mailbox tecnica interna — ideale per reti non esposte), `hybrid` (entrambi). In `mail_reply`/`hybrid` vengono generati link `mailto:` deterministici con subject strutturato `CMD APPROVO|RIFIUTO RID {approval_token}` per supportare parsing automatico.
- **[feat] Mailbox tecnica configurabile**: l'indirizzo target dei `mailto:` è configurabile per template (campo `mailto_mailbox`) oppure tramite `SiteConfig` (chiave `automazioni_approval_mailbox`) oppure `settings.AUTOMAZIONI_APPROVAL_MAILBOX`.
- **[feat] Preview e test rapido**: pagina `/automazioni/template-approvazioni/<pk>/preview/` mostra rendering HTML in iframe con dati mock caso-assenze, visualizza i placeholder non risolti e permette override con payload JSON personalizzato.
- **[feat] Clona template**: bottone "Clona" nelle viste list e form — crea una copia disabilitata con nuovo codice UUID-suffissato per personalizzazione sicura.
- **[feat] Integrazione nel designer `send_approval`**: nuova sezione "Template email approvazione" nel pannello del designer visuale con dropdown di selezione template abilitati. Il template sovrascrive l'HTML della mail; se non selezionato, comportamento identico al precedente (fallback retro-compatibile).
- **[retro] Fallback garantito**: se il template referenziato non esiste, è disabilitato o la tabella non è ancora migrata, `send_approval` degrada silenziosamente al comportamento standard senza interrompere il flusso.
- **[model] `approval_email_templates.py`**: service layer isolato per rendering, mailto, context building e preview — nessuna logica di invio duplicata.
- **[test] 30+ test automatici** su rendering (SimpleTestCase, senza DB), model DB, fallback e integrazione `send_approval` con template valido/invalido.
- **[feat] `poll_approval_mailbox` management command**: comando `python manage.py poll_approval_mailbox` che legge la casella IMAP configurata, cerca email con subject/corpo strutturato (`CMD APPROVO|RIFIUTO RID <uuid>`) e chiama `process_approval_decision()`. Supporta `--dry-run`, `--folder`, `--limit`, `--no-mark-read`. Configurato tramite variabili `.env`: `APPROVAL_IMAP_HOST`, `APPROVAL_IMAP_PORT`, `APPROVAL_IMAP_USER`, `APPROVAL_IMAP_PASSWORD`, `APPROVAL_IMAP_SSL`, `APPROVAL_IMAP_FOLDER`.
- **[test] Test parser IMAP**: 15+ test `SimpleTestCase` senza DB per `_parse_approval_command` e `_get_text_parts` — coprono parsing da subject, parsing da corpo (fallback), priorità subject > body, messaggi multipart MIME, assenza UUID, assenza keyword.

## 0.9.16 - 2026-04-14

### Modulo Automazioni - Conversione Power Automate integrata

- **[feat] Converter Power Automate dentro Admin Portale**: la webapp spostata in `django_app/powerautomate-to-django-automations/` viene ora riusata direttamente dal modulo `automazioni` tramite la pagina `Converti Power Automate`. L'upload `.zip/.json` analizza il flow con i servizi originali del converter, mostra issue, remediation e diagramma del flow originale, e permette di scaricare il package, aprirlo direttamente nell'import guidato SSR del modulo oppure creare una singola bozza draft e aprirla subito nel designer visuale.
- **[ux] Handoff diretto verso `Importa Package`**: dopo l'analisi o la remediation, il package convertito viene passato nello stesso workflow di preview, dry-run e import definitivo gia usato dai package manuali, senza creare un secondo importer separato.
- **[ux] Target table opzionale allineata al portale**: la selezione tabella target non usa piu il wizard standalone SQL Server, ma il catalogo tabelle modulo gia disponibili nel runtime Django. Se non selezioni un target, il converter resta comunque utile per il mapping runtime e per la generazione del package.

### Modulo Automazioni — Controllo flusso avanzato + Diagramma Power Automate-style

- **[fix] Modal "Aggiungi azione al flusso" stabile e non piu visibile al load**: il picker del diagramma nel designer non si affida piu esclusivamente al popolamento JS. Le azioni disponibili vengono serializzate dalla view e stampate direttamente nel modal, mentre lo script del diagramma riusa la stessa lista per stili e inserimento dei nodi. In piu il CSS del modal rispetta esplicitamente `[hidden]`, evitando che la finestra compaia da sola all'apertura della pagina o resti appesa dopo la chiusura.
- **[ux] Editor inline azioni nel diagramma**: il flow diagram del designer permette ora di cliccare un nodo azione e modificare direttamente la card reale del form dentro un pannello inline, senza aprire un editor separato e senza perdere il comportamento SSR del formset. Il nodo resta sincronizzato live con titolo, stato e preview della card mentre si scrive.
- **[ux] Workspace split-view stile Power Automate per il diagramma**: aprendo `Diagramma di flusso`, il designer entra ora in una vista a pieno viewport con inspector laterale fisso e canvas del flow separato, cosi non serve piu scorrere tutta la pagina mentre si modifica una singola azione. Il backdrop e `Esc` chiudono la workspace, lo scroll del body viene congelato finche la vista e aperta e i pulsanti interni permettono di tornare alle sezioni trigger/condizioni/azioni del form solo quando serve.
- **[feat] Diagramma di flusso visuale** (`🔀 Diagramma di flusso`): bottone nel designer visuale che apre una visualizzazione verticale stile Power Automate con nodi colorati per tipo (trigger, condizioni, azioni), connettori freccia, rami approvazione/branch, corpo loop do_until e iterazione for_each. Ogni nodo ha un pulsante "Modifica ↓" che scrolla al form corrispondente. Renderizzato lato client senza librerie esterne da `flow_nodes_json` calcolato da `_build_flow_nodes()` in `views.py`.
- **[feat] `send_approval` — Approvazione umana nel flusso**: nuova azione che pausa l'automazione, invia email agli approvatori con link `Approva`/`Rifiuta` e crea un record `AutomationApproval`. Quando l'approvatore clicca, vengono eseguite le azioni del ramo `approved_actions` o `rejected_actions`. Path `/automazioni/approvazione/<token>/approva|rifiuta/` senza login (token UUID). Run log passa in status `waiting_approval`.
- **[feat] `do_until` — Loop fino a condizione**: esegue `loop_actions` e si richiama tramite la coda eventi finché `check_field/operator/value` non è soddisfatto o si raggiunge `max_iterations`. Delay configurabile (minuti/ore/giorni). All'uscita: `on_success_actions` o `on_timeout_actions`.
- **[feat] `for_each` — Iterazione su sorgente**: interroga una sorgente registrata con filtro opzionale (campo + valore template) ed esegue `each_actions` su ogni record risultante (max `max_items`, default 50, massimo 500).
- **[feat] `branch` — If/Else completo**: valuta una condizione e sceglie tra `if_true_actions` e `if_false_actions`. Complementa il `run_if` (branch leggero) con pieno ramo else.
- **[model] `AutomationApproval`** (migration 0008): token UUID, approver_emails, approved/rejected_actions, status `pending/approved/rejected/expired`, expires_at, decided_by_email.
- **[api] Pagine approvazione**: `GET /automazioni/approvazione/<token>/` (stato), `GET/POST /automazioni/approvazione/<token>/approva|rifiuta/` (decision). Esenti da ACL (aggiunti a `MIDDLEWARE_EXEMPT_PREFIXES`).

### Modulo Automazioni - Test live e anteprima email

- **[feat] Test live inline nel designer**: il pannello laterale del designer visuale include ora un test AJAX completo con due modalita — "Dati campione" (payload auto-generato) e "Record reale" (picker AJAX degli ultimi 20 record dalla sorgente). Il pulsante "Esegui test" manda un POST a `/api/regole/<id>/test-ajax/` e mostra i risultati azione per azione (status, messaggio, traccia errore, link al run log) senza abbandonare la pagina.
- **[feat] Anteprima email live**: le card azione di tipo `send_email` espongono un pulsante "Anteprima" che apre un pannello visivo — stile client email — che riflette live i campi Da/A/Oggetto/Corpo con evidenziazione dei `{placeholder}` in blu.
- **[api] Nuovi endpoint automazioni**: `GET /api/sorgenti/<code>/record-recenti/`, `GET /api/sorgenti/<code>/record/<id>/payload/`, `POST /api/regole/<id>/test-ajax/` — tutti protetti da `@legacy_admin_required`.

### Modulo Automazioni - UX smart designer/test precedente

- **[ux] `rule_designer.html` piu guidata**: il designer visuale usa ora un browser campi smart con ricerca, filtri per ambito e inserimento contestuale nel target attivo (select trigger/condizione, template, mapping, JSON). I widget dei form vengono marcati con attributi dedicati per rendere robusto il supporto frontend.
- **[ux] `rule_test.html` riscritta come composer**: la pagina test espone un builder current/old payload sincronizzato con i textarea JSON raw, pulsanti rapidi per sample/clone/format e diff sintetico dei campi cambiati, cosi la simulazione non parte piu da textarea vuote.
- **[registry] campi runtime `old_*` visibili**: `tickets` e `tasks` dichiarano ora nel source registry i campi virtuali `old_stato`, `old_assegnato_a`, `old_status`, `old_assigned_to_id`, `old_due_date`, utili nei template e nel test manuale.

## 0.9.15 - 2026-04-10

### Modulo KICK-OFF — redesign interfaccia

- **[ux] `base_shell.html` rinnovato**: hero più compatto con gradiente a doppio radiale, altezza ridotta, pills più piccole; tabs convertite in segmented-control a pillola (stile capsule); KPI card con barra di progresso animata proporzionale; tutti i token CSS unificati (`--ts-radius-sm/md/lg`, `--ts-shadow` coerente col tema).
- **[ux] `list.html` — backlog operativo riscritta**: sostituita la card-feed a singola colonna con una tabella densa stile Linear; ogni riga mostra striscia colorata sinistra per stato (blu=todo, giallo=in_progress, verde=done, grigio=canceled, rosso=overdue), titolo + descrizione troncata, badge stato/priorità, kickoff link, avatar initials assegnatario, data scadenza con highlight rosso se overdue. Pannello filtri collassabile con auto-apertura se filtri attivi.
- **[ux] `projects.html` — portfolio kickoff riscritta**: sostituita la tabella piatta con card grid responsive (`auto-fill minmax(320px)`); ogni card ha strip colorata in cima (verde=VRF ok, giallo=warning, rosso=blocked, grigio=N/A), nome kickoff, chips P/N/Rev/Ver/cliente, progress bar avanzamento attività con percentuale, contatori totali/aperte/chiuse, badge VRF, footer azioni compatte.
- **[ux] `project_gantt.html` — Gantt riscritta e fluidificata**: toolbar opzioni compatta integrata nel panel header (sostituisce pannello separato) con select, toggle-flag pill e slider zoom/altezza inline con indicatore live; banner VRF ridisegnati con icone SVG (no emoji); progress card con gradiente multi-radiale e barra animata cubic-bezier; health grid 2x2 compatta; legenda ridisegnata nel footer del Gantt; barre con border-radius 7px e shadow colorata per stato; hint-bar contestuale drag/clic/resize; tutto il JavaScript invariato.

## 0.9.11 - 2026-04-08

### Anagrafica dipendenti

- **[fix] `/onboarding/` sempre accessibile dopo il login**: `core/middleware.py` lascia passare il wizard di primo accesso a qualunque utente autenticato senza richiedere un permesso ACL legacy/canonico dedicato; aggiunto anche un test di regressione in `core/tests.py`.
- **[fix] Allineamento email account/notifica**: `fetch_anagrafica_rows()` applica ora un fallback automatico `email_notifica -> email` quando il dato legacy manca, cosi scheda dipendente, liste anagrafiche e lookup collegati non mostrano piu una mail notifica vuota a fronte di una mail account valorizzata.
- **[fix] Persistenza nuovi record/import**: `upsert_anagrafica_dipendente()` e `import_dipendenti_csv` valorizzano automaticamente `email_notifica` con l'email account se la colonna dedicata non e presente o arriva vuota dalla sorgente.
- **[test] Regressione coperta**: aggiunti test anagrafica per il fallback in dettaglio e per il salvataggio automatico della mail notifica.
- **[ux] Layout shared full-height**: `core/static/core/css/theme.css` tratta ora i wrapper principali di moduli e dashboard come superfici a tutta altezza; le shell `assets` non usano piu allineamenti che le fermavano prima del fondo viewport, evitando bande vuote sotto contenuti corti come assegnazioni e cruscotti.
- **[ux] Pagine `Impostazioni` modulo uniformate**: `diario_preposto`, `rilevazione_incidenti`, `rentri`, `tasks`, `notizie`, `procedure_refresh`, `timbri`, `assets` e `assenze` espongono ora pagine impostazioni allineate su hero, branding nome/logo modulo e quick links. I path canonici dei moduli con naming incoerente sono stati portati a `/impostazioni/`, mantenendo redirect legacy da `/gestione/`, `/configurazione/`, `/admin/` e `/gestione_assenze`.
- **[ux] Manutenzione periodica riallineata alla manutenzione assets**: la vecchia area `/assets/verifiche-periodiche/` ora converge su `/assets/manutenzione/verifiche/`, presentata in UI come `Manutenzione periodica` e agganciata alla sezione `Manutenzione` della sidebar. Aggiornati CTA, dettagli asset, work order, scadenzari, seed ACL e testi collegati; aggiunte anche le migration `0040_move_periodic_verifications_under_maintenance` e `0041_rename_periodic_verification_labels` per riallineare pulsanti sidebar e label Django negli ambienti gia esistenti.

## 0.8.5 — 2026-03-22

### Deployment — Wizard DEV funzionante + Disinstallazione completata

- **[fix] Modalità DEV nel wizard**: `PackagePage` ora mostra un **folder picker per la cartella sorgente** (invece di chiedere un `.zip` inesistente) quando l'ambiente selezionato è DEV. Richiede che la cartella contenga `django_app/`.
- **[fix] Ordine pagine**: `EnvironmentPage` spostata al passo 1 (prima di `PackagePage`) — così la pagina pacchetto conosce già l'ambiente e può adattare la UI.
- **[fix] Skip IISPage in DEV**: la navigazione Avanti/Indietro salta automaticamente la pagina "Configurazione IIS" quando l'ambiente è DEV (IIS non è richiesto in sviluppo).
- **[feature] Flusso installazione DEV separato**: `_run()` ora ha due branch distinti — DEV (7 step: sorgente, venv `.venv`, `.env`, pip, migrate, admin, istruzioni avvio) e TEST/PROD (11 step, invariato). Per DEV: venv in `repo/.venv`, `.env` in `repo/django_app/.env`, nessuna junction, nessun IIS.
- **[fix] `--mode uninstall` in `main()`**: routing verso `UninstallApp()` già completato nella sessione precedente.
- **[feature] `avvia_disinstalla.bat`**: launcher con auto-elevazione admin per la modalità disinstallazione (rimozione sito IIS + App Pool, IIS non toccato).
- **[feature] Log installazione su file**: tutte le modalità (install, release, uninstall) scrivono un log `logs/install_YYYYMMDD_HHmmss.log` accanto all'exe/script, con flush per linea.
- **[feature] Utente admin automatico**: step "Creazione utente amministratore" aggiunto a tutti i flussi — crea ruolo `admin` in `utenti`/`ruoli` legacy + Django superuser opzionale.

- **[fix] `procedure_refresh` in `build_module_versions`**: aggiunto `"procedure_refresh": "APP_VERSION_PROCEDURE_REFRESH"` in `config/settings/base.py` — il modulo ora compare nel dizionario versioni come tutti gli altri.
- **[fix] Test `procedure_refresh`**: test user creati con `is_superuser=True` per bypassare l'ACL middleware in ambiente di test (comportamento atteso, coerente con gli altri test del progetto).
- **[build] `SetupWizard.exe` rigenerato**: `deployment/dist/SetupWizard.exe` ricompilato con PyInstaller dopo le modifiche al wizard di deployment v0.8.5.

---

## 0.8.4 — 2026-03-21

### Procedure Refresh — Presa Visione MT/MTSI

- **[feature] App `procedure_refresh`**: nuovo modulo per la gestione della presa visione obbligatoria delle procedure MT/MTSI a fini audit.
- **[feature] Modelli**: `ProcedureDocument` (anagrafica documenti con tipo MT/MTSI/ALTRO), `ProcedureRevision` (revisioni con sorgente SharePoint o file server, un solo `is_current` per documento), `ProcedureCampaign` (campagne con stati draft/published/closed/archived), `ProcedureCampaignDocument` (collegamento campagna-revisione), `ProcedureAssignment` (assegnazione utente con tracking aperture, timestamp prima/ultima lettura, IP, user agent, contatore aperture), `ProcedureReadEvent` (log eventi opened/confirmed/reminder/reassigned/exported).
- **[feature] Lato utente**: dashboard "Le mie letture" con filtro per stato, dettaglio assegnazione con apertura link documento (SharePoint URL o percorso file server), inserimento nota, conferma presa visione con flag e timestamp.
- **[feature] Tracking automatico**: prima apertura, ultima apertura, contatore aperture, stato `assigned → opened` al primo accesso, stato `read_confirmed` alla conferma.
- **[feature] Admin — Documenti**: CRUD documenti e revisioni. Validazione sorgente (URL obbligatorio per SharePoint, path per file server). Toggle revisione corrente con gestione automatica unicità.
- **[feature] Admin — Campagne**: CRUD campagne con workflow bozza → pubblicata → chiusa. Aggiunta/rimozione documenti da campagna. Assegnazione massiva utenti con selezione revisione e scadenza. Annullamento assegnazioni singole.
- **[feature] Report**: report per utente, per documento, per campagna con tabelle dettagliate.
- **[feature] Export CSV**: streaming CSV assegnazioni complete (stato, date, note) e riepilogo campagne.
- **[feature] ACL bootstrap**: pulsanti `pr_view`, `pr_admin`, `pr_documents`, `pr_campaigns`, `pr_report_*` registrati automaticamente. Voce "Presa Visione" nel menu topbar per tutti i ruoli.
- **[feature] Module Manager**: `procedure_refresh` e `dpi` aggiunti a `MODULE_DEFS` in hub_tools e alla lista moduli del setup wizard.

### Versione

- Bump 0.8.2 → 0.8.4 (include le modifiche 0.8.3 deployment wizard precedentemente committate solo nel CHANGELOG).

---

## 0.8.3 — 2026-03-21

### Deployment — Gestione Release integrata nel wizard

- **[feature] `ReleaseApp`**: nuova modalità "Gestione Release" integrata in `setup_wizard.py`, accessibile via `avvia_gestore_release.bat` o `python setup_wizard.py --mode release`.
- **[feature] Crea Release** (`--mode create`): pacchettizza il codice sorgente dal PC di sviluppo in un `.zip` con esclusione automatica di `.git`, `venv`, `.env`, `__pycache__`, `db.sqlite3`, `media/`, `logs/`, `staticfiles/`, `releases/`. Legge automaticamente la versione da `settings/base.py`. Verifica integrità del `.zip` al termine.
- **[feature] Promuovi Release** (`--mode promote`): deploya un `.zip` su TEST o PROD con pipeline completa: estrazione → copia `.env` da `ENV/config/` → pip install → collectstatic → migrate + createcachetable → attivazione junction `current` → riavvio App Pool IIS. Salva la release precedente in `run/previous_release.txt` per rollback rapido.
- **[feature] `avvia_gestore_release.bat`**: launcher con auto-elevazione admin. Affianca i launcher esistenti (`avvia_wizard_DEV.bat`, `avvia_wizard_TEST.bat`, `avvia_wizard_PROD.bat`).
- **[feature] `Sidebar` parametrizzata**: `Sidebar(parent, steps=None, subtitle="Setup Wizard")` — permette al Release Manager di mostrare `STEPS_RELEASE` con titolo "Gestione Release".
- **[feature] Argomento `--mode`**: `setup_wizard.py` ora accetta `--mode release|create|promote` oltre al già esistente `--env dev|test|prod`.

---

## 0.8.2 — 2026-03-21

### DPI — Gestione Dispositivi di Protezione Individuale

- **[feature] App `dpi`**: nuovo modulo completo per la gestione dei DPI aziendali, in sostituzione dell'app PowerApps+SharePoint precedente.
- **[feature] Modelli**: `CategoriaDPI` (immagine, emoji, vita utile, unità di misura, scorta minima), `DPIImpostazioni` (singleton), `RichiestaDPI` (numerazione `DPI-YYYY-NNNN`, stati INVIATA/APPROVATA/CONSEGNATA/RIFIUTATA/ANNULLATA), `ConsegnaDPI` (1:1, scadenza auto-calcolata), `RichiestaDPICommento` (timeline con flag interno).
- **[feature] Card picker immagini**: la schermata "Nuova richiesta" presenta le categorie come griglia di card cliccabili con immagine o emoji.
- **[feature] Gestione**: lista con filtri, dettaglio con workflow approvazione/rifiuto/consegna, commenti interni, calcolo automatico scadenza da `vita_utile_giorni`.
- **[feature] Impostazioni admin**: gestione categorie con upload immagine e preview, parametri generali.
- **[feature] Storico utente**: pagina personale con badge scaduto/in scadenza.
- **[feature] KPI anagrafica**: widget DPI nel dettaglio dipendente con link a gestione filtrata.
- **[feature] ACL bootstrap**: pulsanti `dpi_view`, `dpi_create`, `dpi_manage`, `dpi_impostazioni` registrati automaticamente all'avvio.
- **[feature] Notifiche**: `invia_notifica()` chiamata automaticamente all'approvazione, rifiuto e consegna.

### Notifiche — Hub Tools admin

- **[feature] Modulo notifiche** (`/admin-portale/hub/notifiche/`): dashboard per monitorare, filtrare, inviare e gestire le notifiche in-app di tutti gli utenti.
- **[feature] Invio manuale**: form con destinatario singolo / reparto / tutti, selezione tipo e URL azione opzionale.
- **[feature] Azioni bulk**: segna tutte come lette, elimina lette, elimina per utente.
- **[feature] Statistiche**: KPI totali/non lette/lette/popup in attesa + breakdown per tipo.
- **[feature] Subnav admin**: aggiunta voce "🔔 Notifiche" nella sezione Hub Tools.

## 0.8.1 — 2026-03-21

### Fix — Cache condivisa multi-worker e hardening avvio produzione

- **[fix] `DatabaseCache` in produzione**: `config/settings/prod.py` ora configura esplicitamente `django.core.cache.backends.db.DatabaseCache` come backend cache. Con 2+ worker IIS, `LocMemCache` (default Django) è per-processo e impedisce a `bump_legacy_cache_version()` di propagare l'invalidazione ACL agli altri worker. `DatabaseCache` usa SQL Server come store condiviso: `cache.incr()` è atomico e le invalidazioni si propagano immediatamente a tutti i worker. Setup una-tantum: `python manage.py createcachetable`. Tabella configurabile via env `DJANGO_CACHE_TABLE` (default `django_cache`).

- **[fix] Guard `SECRET_KEY` al startup**: `config/settings/prod.py` ora solleva `ImproperlyConfigured` se `DJANGO_SECRET_KEY` non è impostata nel `.env` (rileva il valore di default `"change-me-in-dev"`). Il server non parte con una chiave pubblica nota, che invaliderebbe la protezione di sessioni e CSRF token.

- **[fix] `asgi.py` puntava a settings dev**: `config/asgi.py` usava `config.settings.dev` come default. Corretto in `config.settings.prod`. In produzione WSGI questo file non è caricato (wsgi.py già puntava correttamente a prod), ma preveniva un deploy ASGI accidentale con `DEBUG=True`.

- **[docs] CLAUDE.md — corretti bug documentati non più esistenti**: rimossi i riferimenti a due bug già risolti: (1) `lru_cache` su ACL non invalidata (sostituita da `legacy_cache.py` con chiavi versionare dal 0.7.x); (2) navigation registry permissivo senza record accesso (deny-by-default già implementato in `navigation_registry.py:115`). Aggiunta sezione `Cache in produzione` con istruzioni operative.

---

## 0.8.0 — 2026-03-20

### Monitoring — Sistema interno di monitoraggio e incident reporting

- **[feature] App `monitoring`**: nuova app Django che introduce un sistema completo di osservabilità interna, progettato per essere estendibile ma introdotto in modo conservativo senza alterare ACL, navigazione legacy o moduli esistenti.

- **[feature] Modelli**: `Issue` (deduplicazione per fingerprint, cycle di vita `new → triage → in_progress → resolved/ignored`), `IssueOccurrence` (storico occorrenze con traceback e contesto request), `UserProblemReport` (segnalazioni manuali degli utenti), `AutomationJob` (registro job/background task), `AutomationExecution` (storico esecuzioni con status, durata, eccezioni).

- **[feature] Deduplicazione issue**: fingerprint SHA-256 da `(source, category, exception_class, route_name, module_name, messaggio normalizzato)`. Stesso errore → incrementa contatore e aggiorna `last_seen_at` invece di creare duplicati. Severity escalation automatica se l'errore si ripete con gravità maggiore.

- **[feature] `IssueCaptureMiddleware`**: intercetta eccezioni non gestite, risposte HTTP 500, 403 su route autenticate (configurabile) e richieste lente oltre soglia `MONITORING_SLOW_REQUEST_THRESHOLD_MS`. Non interrompe mai il flusso della request anche in caso di errore interno al monitoring.

- **[feature] Pulsante "Segnala problema"**: bottone globale nel topnav (visibile a tutti gli utenti autenticati), apre modal Bootstrap minimale con textarea descrizione. Invio via AJAX con toast di conferma. Endpoint `POST /monitoring/report-problem/` salvato in `UserProblemReport` con correlazione opzionale a issue aperta sullo stesso modulo.

- **[feature] Dashboard admin** (`/admin-portale/monitoring/`): widget issue aperti/critici/nuovi 24h, top moduli/URL problematici, job falliti/mancanti, ultime segnalazioni. Richiede `is_legacy_admin()`, sotto il prefisso già esente da ACL legacy.

- **[feature] Lista e dettaglio issue**: filtri per status/severity/source/category/modulo/date, storico occorrenze, stacktrace, cambio stato, note interne, assegnazione responsabile.

- **[feature] Monitor automazioni**: tabella job con ultima esecuzione, stato, fallimenti consecutivi, indicatori missing/delayed/failing. Dettaglio per job con storico run e issue collegate.

- **[feature] `@monitored_automation` decorator**: wrappa qualsiasi job/background task, crea automaticamente `AutomationJob` (upsert) e `AutomationExecution`, registra successo/fallimento con traceback, apre issue dopo N fallimenti consecutivi configurabili. Sicuro contro doppia-chiusura: se il salvataggio del completion fallisce per DB error, non viene erroneamente marcato come FAILED.

- **[feature] `automation_run_context`**: context manager usabile senza decorator per i job con flusso di completamento manuale (es. batch con stato intermedio).

- **[feature] Management command `monitoring_healthcheck`**: controlla job critici non eseguiti entro `expected_max_interval_minutes`, job bloccati oltre `expected_max_duration_seconds`, issue critiche non prese in carico da oltre N minuti. Crea/aggiorna issue di tipo `system_watchdog`. Invocabile manualmente o tramite scheduler esterno.

- **[feature] Management command `monitoring_digest`**: digest riepilogativo su stdout dello stato del monitoring (issue aperti per severity, job failing/missing/stuck).

- **[feature] Alert email anti-rumore**: notifica email per issue critiche con rate-limit per fingerprint (cache Django, 1h default). Nessuna email duplicata ravvicinata.

- **[technical] Test**: 27 test che coprono fingerprint/deduplication, creazione issue da errore web, UserProblemReport, decorator su successo/fallimento/reraise, no-double-close, detect_missed_jobs, detect_stuck_jobs, count_consecutive_failures.

- **[technical] Fix `count_consecutive_failures`**: aggiunto parametro `exclude_pk` per escludere l'esecuzione corrente (ancora in stato `WARNING`) dal conteggio dei fallimenti consecutivi. Senza questa fix la soglia di alert non veniva mai raggiunta.

- **[technical] Settings MONITORING_***: `MONITORING_ENABLED`, `MONITORING_CAPTURE_403`, `MONITORING_CAPTURE_404`, `MONITORING_SLOW_REQUEST_THRESHOLD_MS`, `MONITORING_NOTIFY_CRITICAL_BY_EMAIL`, `MONITORING_ALERT_RATE_LIMIT_SECONDS`, `MONITORING_WATCHDOG_CRITICAL_UNASSIGNED_MINUTES`.

---

## 0.7.6 — 2026-03-20

### Core — Module Registry completo

- **[feature] Module Registry esteso**: `core/module_registry.py` è ora il catalogo centrale di tutti i moduli applicativi. `MODULE_DEFINITIONS` passa da 1 (`assets`) a 17 voci, coprendo tutti i moduli navigabili (`dashboard`, `assenze`, `anomalie`, `assets`, `tasks`, `tickets`, `notizie`, `anagrafica`, `timbri`, `planimetria`, `automazioni`, `rentri`, `diario_preposto`, `rilevazione_incidenti`), i moduli admin (`admin_portale`, `hub_tools`) e il modulo di sistema (`monitoring`).

- **[feature] Campo `audience` su `ModuleDefinition`**: ogni modulo dichiara il proprio pubblico — `"user"` (navigazione utente normale), `"admin"` (richiede `is_legacy_admin()`), `"system"` (infrastruttura, non in navigazione). Default `"user"`, backward-compatible.

- **[feature] Helper `get_modules_by_audience()`**: nuova funzione in `core/module_registry.py` per filtrare moduli per audience. Predispone il registry per branding, navigation builder e dashboard coerenti per ruolo.

- **[technical] Metadata standardizzati**: ogni voce del registry include `key`, `default_label`, `icon`, `order`, `route_name`, `route_namespace`, `permission_namespace`, `navigation_codes`, `audience` e label alternative per menu/dashboard. `order` usa range distinti: utente `10–85`, admin `200–210`, sistema `300+`.

- **[technical] Test registry**: aggiunta classe `ModuleRegistryStructureTests` in `core/tests.py` con 18 test che verificano assenza di chiavi duplicate, coerenza dei metadata, coerenza `audience`, funzionamento label branded/fallback e correttezza dei filter per audience.

---

## 0.7.5 — 2026-03-20

### Security — Hardening admin_portale

- **[security] Open redirect fix**: i parametri `next` e `HTTP_REFERER` nelle view di gestione utenti (`utente_toggle_active`, `utente_delete`, `utente_quick_role`, `utente_force_change_password`, `utente_impersonate`) vengono ora validati con `url_has_allowed_host_and_scheme`. URL esterni o con schema non sicuro vengono ignorati e sostituiti dal fallback locale.

- **[security] Audit log esteso**: aggiunte tracce audit per operazioni precedentemente non registrate: creazione utente, aggiornamento utente, cambio ruolo veloce, attivazione/disattivazione account, bulk activate/deactivate/force_password, operazioni bulk permessi (`set_all`, `reset_role`, `copy_from_role`), salvataggio configurazione login, gestione banner login.

- **[security] `@csrf_protect` coerente**: aggiunto `@csrf_protect` esplicito a tutti i POST sensibili di gestione utenti e login config che ne erano privi (difesa in profondità rispetto al `CsrfViewMiddleware` globale).

- **[security] Validazione URL pulsanti**: `PulsanteForm.clean_url()` blocca ora esplicitamente schemi pericolosi (`javascript:`, `data:`, `vbscript:`).

- **[security] Lunghezza minima password**: `UtenteCreateForm` richiede almeno 8 caratteri per la password iniziale quando non AD-managed.

- **[technical] Test di sicurezza**: aggiunte 3 classi test (`AdminPortaleFormSecurityTests`, `AdminPortaleOpenRedirectTests`, `AdminPortaleAuditLogTests`) con 18 test cases che coprono open redirect, validazione form e audit trail delle operazioni critiche.

---

## 0.7.4 — 2026-03-18

### UX — Font scaling globale e sidebar personalizzabile

- **[feature] Font scaling globale**: completata l'uniformazione della tipografia del portale sul sistema a token CSS con `font_scale` per utente (`small`, `normal`, `large`, `xl`) e classi `body.fs-*`. Il cambio scala impatta in modo coerente testi, heading, label, menu, subnav, card, tabelle, form, input, select, textarea, bottoni, badge e widget dashboard.

- **[fix/ux] Moduli allineati al design system**: i moduli `assets`, `anomalie` e `rilevazione_incidenti` non usano piu `font-size` hardcoded in `px` nei componenti principali ne stili inline tipografici. I CSS modulo sono stati ricondotti ai token globali di `theme.css`.

- **[feature] Sidebar header rivisto**: il pulsante di apertura/chiusura della sidebar e stato spostato sopra il logo, mantenendo compatibilita con topnav, sidebar compatta e layout responsive esistente.

- **[feature] Footer sidebar configurabile**: le icone rapide in basso possono ora essere aggiunte, rimosse e riordinate dalle preferenze UI. La configurazione viene salvata per utente in `UserUiPreference.sidebar_footer_actions`, normalizzata lato server ed esposta ai template via context processor. L'azione `CAR` resta visibile solo quando esistono richieste in attesa.

- **[technical] Persistenza preferenze UI**: aggiunta la migration `core.0027_useruipreference_sidebar_footer_actions`, aggiornato il payload di cache sessione UI e integrata la nuova preferenza nelle view di salvataggio impostazioni interfaccia.

---

## 0.7.4 — 2026-03-17

### Navigazione — Categorie moduli e topbar dinamica

- **[feature] Categorie moduli** (`ModuleCategory`): nuovo modello Django per raggruppare le voci topbar in aree funzionali (es. MANUTENZIONE, HR, SICUREZZA). Ogni categoria ha key slug, nome, colore hex e ordine.

- **[feature] Topbar colore dinamico**: quando si naviga in un modulo appartenente a una categoria, il background della topbar assume il colore della categoria. Il default CSS viene ripristinato per le voci senza categoria.

- **[feature] Menu a tendina per categoria**: le voci topbar con categoria assegnata vengono raggruppate sotto un unico bottone `[NOME CATEGORIA ▾]` con dropdown animato. I moduli della categoria appaiono come voci del menu. Le voci senza categoria restano link diretti.

- **[feature] Gestione autonoma categorie** (`/admin-portale/hub/categorie/`): nuova pagina Hub Tools per creare, modificare ed eliminare categorie (color picker, ordine) e assegnare ogni voce topbar a una categoria tramite dropdown ad aggiornamento immediato.

- **[technical]** `NavigationNode` e `NavItem` estesi con `category_color`, `category_key`, `category_label`, `category_order`. Context processor espone `topbar_groups` (lista ordinata di gruppi/voci dirette) e `topbar_color`. Cache nav invalidata automaticamente ad ogni modifica categoria.

---

## 0.7.4 — 2026-03-16

### Anagrafica HR — Mansioni, Qualifiche e Widget statistiche dipendente

#### Mansioni & Qualifiche

- **[feature] Modulo HR anagrafica**: aggiunta sezione risorse umane all'app `anagrafica` con tre nuovi sistemi Django gestiti (separati dal DB legacy) e integrati nella scheda dipendente.

- **[feature] Catalogo Mansioni** (`/anagrafica/mansioni/`): catalogo job title aziendali (Operaio, Impiegato, Quadro, Dirigente + libero). Scelta dalla scheda dipendente aggiorna direttamente il campo `mansione` sul DB legacy via `upsert_anagrafica_dipendente()`. Grid card con colore accent, categoria badge, contatore dipendenti con quella mansione.

- **[feature] Catalogo Qualifiche professionali** (`/anagrafica/qualifiche/`): tipi di qualifica/certificazione con categoria (Sicurezza, Professionale, Gestionale), durata validità in mesi e auto-calcolo scadenza. Sezione "Scadenze in arrivo" con alert visivi per qualifiche scadute (rosso) o in scadenza entro 60gg (arancio).

- **[feature] Qualifiche dipendente**: dalla scheda dipendente è possibile aggiungere e rimuovere qualifiche con data conseguimento, data scadenza (manuale o calcolata) e note. Badge status in-line (scaduta/in scadenza).

- **[feature] Mansione modificabile dalla scheda**: campo mansione aggiornabile con dropdown dal catalogo, con fallback a testo libero.

- **[feature] Ruoli Operativi**: catalogo ruoli sicurezza aziendale (Preposto, RSPP, ASPP, RLS, ecc.) assegnabili ai dipendenti dalla loro scheda.

#### Widget statistiche scheda dipendente

- **[feature] Sezione statistiche dipendente**: 7 widget configurabili per utente (ticket aperti/totali, anomalie, diario preposto, rilevazioni sicurezza, assenze, timbri). Widget drag & drop riordinabili, nascondibili e ripristinabili. Contatori in tempo reale dal DB.

- **[feature] Impostazioni accesso statistiche** (`/anagrafica/impostazioni-widget/`): singleton `AnagraficaStatPermission` — visibilità sezione statistiche configurabile per admin, tutti gli utenti o ruoli ACL specifici.

#### Riorganizzazione subnav anagrafica

- **[ux] Subnav riorganizzato**: aggiunto separatore visivo tra area HR (Dipendenti · Ruoli operativi · Mansioni · Qualifiche) e area Fornitori. Aggiornate notice contestuali per tutte le nuove pagine.

#### Modelli Django aggiunti

- `RuoloOperativo`, `DipendenteRuoloOperativo` — ruoli sicurezza operativi

- `Mansione` — catalogo job title

- `TipoQualifica` — catalogo tipi certificazione

- `DipendenteQualifica` — assegnazioni qualifiche con date e scadenze

- `DipendenteStatLayout` — layout widget per utente loggato

- `AnagraficaStatPermission` — singleton permessi statistiche

- **[versioning]** Bump versione `0.7.3` → `0.7.4`.

---

## 0.7.3 — 2026-03-16

### Rilevazione Incidenti — nuova app

#### Rilevazione Incidenti — nuova app Django

- **[feature] App `rilevazione_incidenti`** (`/rilevazione-incidenti/`): nuova app per la registrazione di segnalazioni di sicurezza nelle 4 tipologie previste (Unsafe Condition, Unsafe Act, Near Miss, Accident). Sostituisce sul portale la PowerApp omonima mantenendo SharePoint come unica fonte di verità: tutte le operazioni CRUD avvengono via Microsoft Graph API, senza modello Django per i dati incidenti.

- **[feature] Workflow ACL tripartito**: ruoli distinti — Preposti/Capireparto (creazione + modifica Sezione 1-2 se stato APERTO), RSPP/ASPP (Sezione 3: approvazione RLS + chiusura), Admin (impostazioni). Whitelist JSON configurabile da `/rilevazione-incidenti/impostazioni/`.

- **[feature] Selezione tipo**: prima schermata con 4 card illustrative (`?tipo=` query param), stessa UX del modulo Tickets.

- **[feature] Form multi-sezione**: Sezione 1 (evento: tipologia, nominativo, reparto, macchina/DPI, descrizione, cause, persone coinvolte), Sezione 2 (analisi 5WHY + note preposto), Sezione 3 (approvazione RLS, data approvazione, note RSPP/ASPP, chiusura + data chiusura).

- **[feature] Stato derivato** (nessuna colonna aggiuntiva SharePoint): `Chiusura_RSPP=True` → **CHIUSO**, `Approvazione_RLS` valorizzato → **APPROVATO**, altrimenti → **APERTO**.

- **[feature] Statistiche** (`/rilevazione-incidenti/statistiche/`): KPI per tipologia (4 badge), stato workflow, top-10 reparti a barre orizzontali, trend mensile ultimi 12 mesi.

- **[feature] ACL bootstrap**: 6 pulsanti registrati automaticamente nella tabella ACL legacy all'avvio; endpoint nascosti dalla UI via `ui_pulsanti_meta`.

- **[fix] Regola template Django**: variabili/chiavi dict con nome iniziante per `_` causano `TemplateSyntaxError`. La regola è ora documentata in CLAUDE.md e applicata uniformemente (es. `stato` e `sp_id` invece di `_stato` e `_sp_id`).

- **[fix] Audit log**: le chiamate `log_action` usano correttamente `"rilevazione_incidenti"` come nome modulo (non `"sicurezza"`).

- **[versioning]** Bump versione `0.7.2` → `0.7.3`.

---

## 0.7.2 — 2026-03-15

### Diario Preposto, Report Timbri, Hub Database e miglioramenti

#### Diario Preposto — nuova app

- **[feature] App `diario_preposto`**: nuova app Django per la gestione delle segnalazioni del preposto. Include modelli, form, viste lista/dettaglio/form con ACL (`acl_bootstrap.py`) e migration iniziale.

- **[ops] Import CSV Diario Preposto**: aggiunto comando `python django_app/manage.py import_preposto_csv <file.csv>` per caricare segnalazioni storiche nel modulo con parsing date italiane, `dry-run` e logica idempotente anti-doppioni.

#### Timbri — report e nuovi componenti

- **[feature] Report timbri** (`/timbri/report/`): nuova pagina di reportistica presenze con template dedicato `report.html`.

- **[feature] Componenti `detail_record` e `report_record`**: nuovi componenti HTML riutilizzabili per la visualizzazione del dettaglio e del report di un singolo record di timbratura.

- **[ops] Import CSV timbri senza immagini**: aggiunto comando `python django_app/manage.py import_timbri_csv <file.csv>` per importare i record dal registro SharePoint, agganciando solo gli operatori presenti in anagrafica centrale e ignorando le immagini.

- **[ux/fix] Timbri**: aggiunto pannello `Da gestire` per le righe CSV non importate, form record con date HTML5 correttamente precompilate in modifica e azioni dedicate per firma/sigla.

- **[fix] Aggiornamenti** a `operatore_detail`, `record_form`, `index`, `views.py`, `urls.py` e `models.py` del modulo timbri.

#### Hub Tools — sottovoce Database separata

- **[ux] Subnav admin**: `Hub / Moduli` e `Hub / Database` ora compaiono come due voci separate nel subnav dell'Admin Portale, ciascuna con stato `active` indipendente.

- **[fix] Aggiornamenti** a `database.html`, `moduli.html` e `views.py` di hub_tools.

#### Tickets

- **[fix/ux] Aggiornamenti** a dashboard, impostazioni, views e urls del modulo tickets.

#### RENTRI

- **[fix] Aggiornamenti** a views, urls e template `elenco.html` / `menu.html` del modulo RENTRI.

#### Varie

- **[fix/ux]** Aggiornamenti anagrafica (liste dipendenti e fornitori), assenze (gestione), core (base.html, topnav, theme.css, settings).

- **[docs] Tools**: aggiunti manuale admin navigazione/permessi (HTML + MD) e riepilogo v0.7.1, mappa moduli HTML.

- **[versioning]** Bump versione `0.7.1` → `0.7.2`.

---

## 0.7.1 — 2026-03-14

### Setup Wizard v2 + app Hub Tools

#### Setup Wizard — wizard guidato esteso a 12 step

- **[feature] Step 9 — Selezione moduli**: il wizard mostra tutti i moduli disponibili con icona, nome e descrizione. I moduli core (`Core & Auth`, `Dashboard`, `Admin Portale`) sono sempre attivi e visualizzati come tali. I moduli opzionali (`assenze`, `anomalie`, `assets`, `tasks`, `tickets`, `notizie`, `anagrafica`, `automazioni`, `timbri`, `planimetria`) sono selezionabili singolarmente con stato default configurato.

- **[feature] Step 10 — Primo utente amministratore**: form con username, password (con strength meter visuale: lunghezza, maiuscola, numero, carattere speciale, corrispondenza), email, nome e cognome. Validazione client-side prima di procedere.

- **[feature] Step 11 — Informazioni operative**: nome azienda, indirizzo, telefono, email di contatto, fuso orario (default `Europe/Rome`), lingua interfaccia e formato data.

- **[feature] Step 12 — Installa & Avvia**: sostituisce il vecchio "Riepilogo & Salva". Esegue 4 fasi in sequenza con progress indicator in tempo reale: (1) salva `.env` e la configurazione legacy su file, (2) `manage.py migrate` via subprocess con rilevamento auto dev/prod settings, (3) crea superuser Django, (4) scrive visibilità moduli in `SiteConfig`. Redirect automatico a `/login/` al termine.

- **[api] Nuovi endpoint setup wizard**: `POST /setup/api/run-migrations/`, `POST /setup/api/create-admin/`, `POST /setup/api/set-modules/`.

#### Hub Tools — nuova app di gestione post-installazione

- **[feature] App `hub_tools`** (`django_app/hub_tools/`): nuova app Django per la gestione operativa, accessibile dallo staff a `/admin-portale/hub/`. Registrata in `INSTALLED_APPS`, `config/urls.py` e `MIDDLEWARE_EXEMPT_PREFIXES`.

- **[feature] Module Manager** (`/admin-portale/hub/moduli/`): toggle enable/disable per ogni modulo opzionale, effetto immediato senza riavvio del server. Aggiorna `SiteConfig` tramite `POST /admin-portale/hub/moduli/toggle/`.

- **[feature] Database Manager** (`/admin-portale/hub/database/`): 5 operazioni — statistiche tabelle (righe + dimensione), backup (file SQLite o `BACKUP DATABASE` SQL Server), pulizia (sessioni scadute, log vecchi, event queue processati, notifiche lette), ottimizzazione (`VACUUM+ANALYZE` / `UPDATE STATISTICS + ALTER INDEX REBUILD`), ripristino da lista backup con salvataggio `.pre_restore`.

- **[infra]** Namespace URL `hub_tools`; tutte le view protette da `is_staff`.

#### Versioning

- **[versioning]** Bump versione `0.7.0` → `0.7.1`.

---

## 0.7.0 — 2026-03-13

### Setup Wizard & Rebrand BrizioHUB

- **[feature] Setup Wizard integrato in Django** (`setup_wizard/`): al primo avvio il portale reindirizza automaticamente a `/setup/`, un wizard guidato a 9 step che configura l'intero ambiente di produzione senza toccare file a mano.

- **[feature] Branding &amp; Identità** (Step 1): il wizard permette di scegliere il nome istanza (es. "Portale Novicrom"), caricare il logo aziendale e il favicon. Logo e favicon vengono salvati in `core/static/core/img/` e referenziati via `BRANDING_LOGO` / `BRANDING_FAVICON` nel `.env`.

- **[feature] Configurazione SQL Server in-browser** (Step 4): il wizard include un tool live per testare la connessione al database SQL Server tramite l'API `/setup/api/test-db/` (usa pyodbc direttamente, risponde in tempo reale con la versione del server).

- **[feature] Test live connessioni** (Steps 4/5/7): pulsanti "Testa connessione" per SQL Server (pyodbc), LDAP/AD (ldap3 + fallback porta TCP) e SMTP (smtplib + STARTTLS).

- **[feature] Salvataggio configurazione server-side**: al termine del wizard, `/setup/api/save/` scrive `django_app/.env` e la configurazione legacy su file sul server e imposta `SETUP_COMPLETED=1`. Il middleware non reindirizzerà più al wizard.

- **[feature] `SetupRequiredMiddleware`**: middleware file-based (legge `.env` direttamente, senza DB) che intercetta ogni richiesta e reindirizza a `/setup/` finché `SETUP_COMPLETED≠1`.

- **[rebrand] BrizioHUB**: nome del software su GitHub cambiato in **BrizioHUB**. Il nome istanza è ora configurabile per-deployment tramite `INSTANCE_NAME` in `.env` (default `BrizioHUB`, override suggerito al primo avvio del wizard). Aggiornati: header wizard, `INSTALLED_APPS`, log dir (`briziohub_logs`), `.env.example`.

- **[infra] `INSTANCE_NAME`, `BRANDING_LOGO`, `BRANDING_FAVICON`** aggiunti a `base.py` settings e `.env.example`.

- **[infra] `/setup/`** aggiunto a `MIDDLEWARE_EXEMPT_PREFIXES` (ACL e session middleware non intercettano il wizard).

- **[tool] `tools/setup-wizard.html`**: wizard standalone HTML (zero dipendenze) per generare `.env` e, nello storico, la configurazione legacy offline; mantenuto come tool di supporto alternativo.

- **[versioning]** Bump versione `0.6.40-dev` → `0.7.0`.

## 0.6.40-dev — 2026-03-12

- **[fix] Automazioni Assenze -> `capo_email` nel payload runtime**: il designer ora espone il placeholder `{capo_email}` tra i campi suggeriti della sorgente `assenze`, il preset "Avviso al responsabile" lo usa direttamente nel destinatario email e il worker automazioni arricchisce payload e old payload risolvendo l'email dal caporeparto selezionato. Aggiornati anche i trigger SQL della queue `assenze` per serializzare `capo_email` nei nuovi eventi.

- **[feature] Anagrafica centrale dipendenti**: la pagina `anagrafica/dipendenti/` non e' piu' solo in lettura. Ora consente l'inserimento diretto di dipendenti con stato `attivo` / `non attivo`, mantenendo i dipendenti non attivi senza account operativo ma sempre presenti nell'anagrafica centrale.

- **[feature] Admin Portale -> anagrafica unica**: creazione, aggiornamento, attivazione/disattivazione e bulk action sugli utenti legacy sincronizzano la tabella `anagrafica_dipendenti`. Se un account viene disattivato, il dipendente resta in anagrafica e viene sganciato come account operativo.

- **[feature] Timbri -> reset e rebuild da anagrafica**: aggiunto in configurazione il pulsante `Reset tabella`, che svuota i dati locali del modulo `timbri` lasciando intatta la configurazione SharePoint e ricreando solo i nominativi dalla tabella anagrafica centrale.

- **[fix] Timbri -> deduplica nominativi duplicati**: la lista dipendenti di `timbri` ora deduplica le anagrafiche doppie con stesso nominativo, preferisce il record anagrafico "buono" non tutto maiuscolo e recupera dal duplicato storico i dati mancanti (es. matricola/ruolo) per evitare doppi in UI.

- **[fix] Anagrafica centrale -> bonifica duplicati reali**: introdotta la deduplica anche lato `anagrafica/dipendenti/` e una bonifica dati reale sulla tabella `anagrafica_dipendenti`, con merge dei campi utili dal record storico al record preferito e rimozione dei duplicati maiuscoli/non collegati.

- **[test] Copertura regressioni anagrafica/admin/timbri**: aggiunti test su inserimento dipendente non attivo senza account, sync anagrafica da disattivazione account e reset/deduplica del modulo `timbri`.

- **[versioning] Versione allineata**: aggiornati `django_app/VERSION` e `config.settings.base.APP_VERSION` alla release corrente `0.6.40-dev`.

## 0.6.39-dev - 2026-03-11

- **[feature] Automazioni — designer visuale affiancato**: aggiunta la vista `/admin-portale/automazioni/regole/`<id>`/designer/` e la creazione `/admin-portale/automazioni/regole/nuova/designer/`, senza introdurre motori o schemi paralleli. Il designer lavora sugli stessi modelli `AutomationRule`, `AutomationCondition`, `AutomationAction`, con riepilogo umano `TRIGGER -> CONDIZIONI -> AZIONI`, trigger card, card condizioni/azioni, test rapido collegato e link dedicati da lista, dettaglio e builder classico.

- **[ux] Automazioni — preset visuali e suggerimenti guidati**: il designer ora propone basi suggerite e preset visuali compatti per condizioni e azioni, con specializzazione `assenze` (approvazione/rifiuto, avviso responsabile, notifiche interne, metriche, log audit, condizioni su `moderation_status`, esclusione `Malattia`, controllo capo reparto). Aggiunti anche controlli dimensione `S / M / L` per mantenere i preset leggibili ma non invasivi.

- **[fix] Assenze — insert SQL Server compatibile con trigger**: corretto il salvataggio locale e il pull SharePoint verso la tabella `assenze` sostituendo il recupero PK via `OUTPUT INSERTED.id` con la sequenza `INSERT` + `SELECT CAST(SCOPE_IDENTITY() AS int)`, necessaria quando sulla tabella sono presenti trigger abilitati. Aggiunti test di regressione sul flusso di insert SQL Server.

- **[docs] Guida Automazioni Designer**: aggiunti documento HTML e PDF riepilogativo delle modifiche implementate sul modulo `automazioni`, in stile guida interna, con overview architetturale, UX del designer, preset, reorder, test e stato finale della fase.

- **[test] Automazioni — copertura designer e reorder**: estesi i test Django per pagina designer, route `nuova/designer`, summary umano, link al designer, endpoint reorder condizioni/azioni e presenza dei cataloghi preset renderizzati.

- **[versioning] Versione allineata**: aggiornati `django_app/VERSION` e `config.settings.base.APP_VERSION` alla release corrente `0.6.39-dev`.

## 0.6.38-dev - 2026-03-11

- **[feature] Automazioni — modulo completo v1 SSR**: completata l'introduzione del modulo `automazioni` con catalogo sorgenti/campi, modelli dominio (`AutomationRule`, `AutomationCondition`, `AutomationAction`, `AutomationRunLog`, `AutomationActionLog`, `DashboardMetricValue`), runtime regole, executor controllati, worker queue e builder finale SSR per creare, modificare, attivare e testare manualmente le regole.

- **[feature] Automazioni — queue SQL Server su `assenze`**: aggiunta l'infrastruttura tecnica con tabella `automation_event_queue` e trigger `AFTER INSERT` / `AFTER UPDATE` su `assenze`, con payload JSON coerente al source registry e processamento demandato al worker Django.

- **[feature] Automazioni — plancia operativa admin**: aggiunte pagine operative SSR per queue e run log in area `admin_portale`, con filtri, dettaglio evento, collegamento ai log applicativi, reset a `pending` e retry controllato del singolo evento.

- **[feature] Automazioni — builder regole con pannello campi sempre visibile**: introdotte le pagine `/admin-portale/automazioni/regole/` con form SSR, formset condizioni/azioni, configurazione umana di `send_email`, `write_log`, `update_dashboard_metric`, `insert_record`, `update_record` e pannello laterale `Contenuti / Colonne disponibili` sempre visibile e coerente con il source registry.

- **[feature] Admin Portale — `Config SRV`**: la precedente area `Diagnostica LDAP` e' stata rinominata lato UI in `Config SRV` e ora centralizza configurazione/test di LDAP / Active Directory e SMTP nello stesso pannello, con persistenza nel file di configurazione legacy.

- **[infra] SMTP nei settings Django**: aggiunto supporto a `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `EMAIL_USE_SSL`, `EMAIL_TIMEOUT` e `DEFAULT_FROM_EMAIL`, letti da environment oppure dalla sezione SMTP del file di configurazione legacy.

- **[versioning] Versione allineata**: aggiornati `django_app/VERSION` e `config.settings.base.APP_VERSION` alla release corrente `0.6.38-dev`.

## 0.6.37-dev - 2026-03-10

- **[feature] Modulo Ticket — app `tickets/`**: nuovo modulo nativo che sostituisce le due app PowerApps ("Ticket IT" e "Ticket MAN"). Gestisce richieste di intervento su asset informatici e macchinari con ciclo di vita Aperta → In carico → Risolto → Chiuso, priorità (Bassa/Media/Alta/Urgente), flag di sicurezza sul lavoro (forza URGENTE non modificabile), categorie configurabili, allegati file, commenti pubblici e note interne.

- **[feature] Ticket — numerazione automatica**: ogni ticket riceve un numero progressivo per anno nel formato `IT-YYYY-NNNN` / `MAN-YYYY-NNNN`, con reset annuale automatico.

- **[feature] Ticket — collegamento asset**: i ticket possono essere collegati a un asset del catalogo (FK su `assets.Asset`) oppure a descrizione libera per asset non censiti.

- **[feature] Ticket — delega a fornitore esterno**: i gestori possono delegare un ticket a un fornitore esterno selezionato dall'anagrafica fornitori (`anagrafica.Fornitore`).

- **[feature] Ticket — impostazioni admin**: sezione `/tickets/impostazioni/` (solo admin) per configurare List ID SharePoint, team gestori (nome + email), ACL apertura e ACL gestione per ciascun tipo (IT e MAN), tutto modificabile in-page senza toccare il codice.

- **[feature] Ticket — ACL configurabile**: chi può aprire e chi può gestire i ticket di ciascun tipo è definito nelle impostazioni. Vuoto = aperto a tutti / solo admin. L'admin portale bypassa sempre.

- **[infra] `tickets` aggiunto a INSTALLED_APPS e MODULE_VERSIONS**: migrazione `0001_initial` applicata su dev (tabelle: `tickets_ticket`, `tickets_ticketcommento`, `tickets_ticketallegato`, `tickets_ticketimpostazioni`).

- **[core] Reparto → Capo Reparto escalation**: `_resolve_default_capo_for_user()` in `assenze/views.py` ora usa `UserExtraInfo.caporeparto` come sorgente primaria (da `RepartoCapoMapping`), lo storico SP come fallback, e `anagrafica_dipendenti.reparto` come last resort.

## 0.6.36-dev - 2026-03-10

- **[feature] Certificazione Presenza — flusso admin con push SharePoint**: aggiunta la nuova sezione `/assenze/certificazione-presenza/` (accesso tramite subnav assenze), riservata agli utenti con ruolo admin/HR. Consente l'inserimento diretto della presenza giornaliera di un dipendente con turno mattina (obbligatorio) e turno pomeriggio (opzionale, attivabile con toggle). L'inserimento è auto-approvato (`consenso = Approvato`), crea automaticamente un record nella tabella `assenze` e tenta il push alla lista SharePoint "Certificazione presenza" tramite Power Automate.

- **[feature] Certificazione Presenza — flusso utente via richiesta assenze**: aggiunta l'opzione "Certifica presenza" nel selettore tipo nella pagina `/assenze/richiesta/`. Quando selezionato, il form standard (data inizio/fine) viene nascosto e compare una sezione dedicata con: banner esplicativo, input data, selettori ora:minuto per entrata/uscita mattina, toggle pomeriggio e selettori condizionali. Al submit JS assembla i campi nascosti compatibili con il backend; il record viene salvato in `assenze` con `consenso = In attesa` e inviato al Capo Reparto per approvazione.

- **[feature] Certificazione Presenza — modello Django e migrazioni**: aggiunto `CertificazionePresenza` nell'app `assenze` (`assenze/models.py`) con campi: nome dipendente, data, entrata/uscita mattina, flag turno pomeriggio, entrata/uscita pomeriggio (nullable), note, consenso (In attesa/Approvato/Rifiutato), capo_reparto_email, salta_approvazione, origine (utente/admin), assenza_id, inserito_da, sharepoint_item_id. Applicate migrazioni `0001_initial_certificazione_presenza` e `0002_add_consenso_origine_to_certificazione`.

- **[feature] Anagrafica — dashboard personalizzabile**: la dashboard `/anagrafica/` supporta ora la modalità "Personalizza" (solo admin), analoga alle altre dashboard del portale. Tre widget (`kpi`, `moduli`, `ultimi`) sono nascondibili, riordinabili con drag-and-drop e le preferenze sono persistite in `localStorage` con chiave `ana_dash_prefs_v1`. Pulsante "Personalizza" nel hero; barra edit con Salva/Reset/Chiudi.

- **[infra] `list_id_presenza` nella configurazione legacy**: aggiunta la chiave `list_id_presenza = 7B15a131b8-...` nella sezione `[AZIENDA]` del file di configurazione legacy per la lista SharePoint "Certificazione presenza".

- **[ux] Subnav assenze — voce Certifica presenza**: aggiunto link "Certifica presenza" nella barra di navigazione secondaria del modulo assenze (`assenze/components/subnav.html`) con highlight attivo sulla pagina corrente.

- **[ux] Menu assenze — card Certifica presenza**: aggiunta card di accesso rapido nel menu del modulo assenze (`assenze/pages/menu.html`).

## 0.6.35-dev - 2026-03-09

- **[ux] Wizard permessi ruolo — flag inline e pulsante Tutto**: i flag "Può modificare / eliminare / approvare" sono ora sempre visibili nella riga, senza espansione "+dettagli". Ogni riga ha un pulsante "Tutto" che seleziona/deseleziona in blocco visibilità e tutti e tre i flag. I pulsanti "Tutto ON / OFF" di modulo gestiscono ora anche i flag extra, non solo la visibilità.

- **[ux] Wizard permessi ruolo — pre-caricamento diretto allo step 2**: quando il wizard viene aperto con `?ruolo_id=X` (es. da link "Modifica"), i permessi esistenti vengono caricati e la pagina salta direttamente allo step 2, senza passare per la selezione manuale del ruolo.

- **[feature] Assets — modifica in blocco da tabella inventario**: aggiunta selezione multipla nella tabella asset tramite checkbox per riga e checkbox "seleziona tutti" nell'intestazione. Quando almeno un asset è selezionato compare una toolbar con il pulsante "Modifica in blocco" che apre un modale per impostare Stato, Reparto, Produttore, Modello e Note su tutti gli asset selezionati in una sola operazione. Aggiunto endpoint backend `POST /assets/bulk-update/` (`assets:asset_bulk_update`).

- **[feature] Assets — card KPI personalizzate nel widget manager**: nel pannello "Widget dashboard — visibilità & collegamenti", nella sezione KPI principali, è ora possibile aggiungere card personalizzate con titolo, valore testuale, sottotitolo e collegamento. Le card vengono salvate in `localStorage` e appaiono nella riga KPI come widget standard (draggabili, nascondibili). Le card custom sono removibili dal manager con un pulsante "Rimuovi".

## 0.6.34-dev - 2026-03-09

- **[feature] Categorie asset dinamiche gestibili da `/assets/`**: introdotte le nuove entita `AssetCategory` e `AssetCategoryField`, con studio admin interno per creare categorie business come `Allarme`, `TVCC`, `Pompa di calore`, scegliere la famiglia tecnica di base e definire i campi dedicati senza nuove modifiche al codice.

- **[ux] Form asset e macchine con campi categoria dinamici**: le schermate di creazione/modifica mostrano ora i campi configurati in base alla categoria selezionata, salvandone i valori in `extra_columns["_category_fields"]` e mantenendo separati i campi custom globali gia esistenti.

- **[ux] Dettaglio asset con titoli sezione personalizzabili per categoria**: la scheda dettaglio legge ora anche i titoli configurati sulla categoria (`Specifiche`, `Profilo`, `Responsabile`, `Timeline`, `Manutenzione`) e integra automaticamente i campi categoria marcati per il dettaglio.

- **[db] Migrazione categorie asset applicata**: aggiunta e applicata `assets.0022_assetcategory_asset_asset_category_and_more` per introdurre FK categoria su `Asset` e la struttura dei campi categoria.

- **[qa] Copertura test estesa su categorie asset**: aggiunti test per la creazione admin di una categoria, per il salvataggio dei valori categoria da form asset e per il rendering nel dettaglio di titoli e campi categoria.

- **[versioning] Versione allineata**: aggiornati `django_app/VERSION` e `config.settings.base.APP_VERSION` alla release corrente `0.6.34-dev`.

## 0.6.33-dev - 2026-03-09

- **[feature] Dettaglio asset configurabile da studio admin**: aggiunta la nuova entita `AssetDetailField`, con gestione da `/assets/` per controllare quali dati compaiono nelle sezioni `Metriche`, `Specifiche tecniche`, `Profilo asset` e `Responsabile attuale`, con ordine, ambito (`tutti`, `asset standard`, `macchine di lavoro`) e formato valore.

- **[ux] Scheda dettaglio guidata da configurazione**: la pagina `/assets/view/`<id>`/` legge ora la configurazione admin e mostra anche campi custom dentro il dettaglio, mantenendo fallback sicuro solo quando non esiste ancora una configurazione valida per il tipo asset aperto.

- **[db] Migrazioni dettaglio asset applicate**: aggiunte e applicate `assets.0020_assetdetailfield` e `assets.0021_seed_asset_detail_fields`, con seed iniziale dei campi che replica la scheda dettaglio predefinita e la rende subito modificabile.

- **[qa] Test amministrazione dettaglio e rendering custom**: aggiunta copertura per la creazione dei campi dettaglio da pannello admin e per il rendering in scheda asset di un campo custom configurato.

- **[versioning] Versione allineata**: aggiornati `django_app/VERSION` e `config.settings.base.APP_VERSION` alla release corrente `0.6.33-dev`.

## 0.6.32-dev - 2026-03-09

- **[ux] Tabelle inventario e macchine piu compatte**: ridotti padding righe, dimensione badge, blocchi nome/tag e densita generale delle tabelle principali di `/assets/` e `/assets/work-machines/`, cosi la lista mostra piu record senza allungare inutilmente la pagina.

- **[versioning] Versione allineata**: aggiornati `django_app/VERSION` e `config.settings.base.APP_VERSION` alla release corrente `0.6.32-dev`.

## 0.6.31-dev - 2026-03-09

- **[ux] Layout assets non piu stirato in altezza**: la shell condivisa del modulo `assets` e la dashboard `/assets/` non forzano piu un'altezza minima a viewport piena, cosi le schermate con poco contenuto non restano artificialmente lunghe.

- **[ux] Sidebar e contenuto allineati al contenuto reale**: il layout usa ora `align-items:start`, evitando che menu laterale e contenuto si trascinino verticalmente fra loro quando una pagina ha piu o meno elementi delle altre.

- **[versioning] Versione allineata**: aggiornati `django_app/VERSION` e `config.settings.base.APP_VERSION` alla release corrente `0.6.31-dev`.

## 0.6.30-dev - 2026-03-09

- **[feature] Sidebar assets gestibile con gerarchia parent/child**: il pannello admin interno di `/assets/` permette ora di definire anche la voce padre della singola voce menu, cosi puoi controllare direttamente posizione, sezione e sottocategoria senza dover intervenire nel codice.

- **[feature] Planimetrie multiple per categoria impianto**: il sistema planimetrie supporta ora piu mappe attive in parallelo, ciascuna con categoria dedicata (ad esempio `Officina`, `TVCC`, `Sistema allarme`), con selettore categoria nella vista utenti e nell'editor.

- **[db] Migrazioni sidebar e planimetrie allineate**: aggiunte `assets.0018_alter_plantlayout_options_assetsidebarbutton_parent_and_more` e `assets.0019_seed_sidebar_parents_and_layout_categories` per introdurre parent menu e categoria planimetria anche sugli ambienti esistenti.

- **[qa] Copertura test estesa**: aggiunti test per la creazione di voci sidebar figlie da pannello admin e per il cambio categoria nella vista planimetrie.

- **[versioning] Versione allineata**: aggiornati `django_app/VERSION` e `config.settings.base.APP_VERSION` alla release corrente `0.6.30-dev`.

## 0.6.29-dev - 2026-03-09

- **[ux] Verifiche periodiche piu compatte e configurabili**: la pagina `/assets/verifiche-periodiche/` usa ora un form piu corto e largo, con layout selezionabile dall'utente (`Compatta`, `Bilanciata`, `Ampia`) persistito in `localStorage`, cosi la schermata non resta inutilmente lunga.

- **[ux] Ricerca live sugli asset coinvolti**: il multiselect asset supporta filtro istantaneo per tag/nome, contatore selezioni e azioni rapide `Seleziona visibili` / `Pulisci`, rendendo gestibile anche una lista macchine ampia.

- **[qa] Test pagina verifiche periodiche esteso**: aggiunta copertura sul rendering dei nuovi controlli UI della pagina (`layout switch` e ricerca asset).

- **[versioning] Versione allineata**: aggiornati `django_app/VERSION` e `config.settings.base.APP_VERSION` alla release corrente `0.6.29-dev`.

## 0.6.28-dev - 2026-03-09

- **[feature] Verifiche periodiche nel modulo assets**: introdotta la nuova entita `PeriodicVerification` con fornitore collegato da `anagrafica.Fornitore`, cadenza in mesi, date ultima/prossima verifica, stato attivo e collegamento multi-asset, cosi ogni macchina o bene puo appartenere a piu cicli di verifica contemporaneamente.

- **[ux] Gestione verifiche integrata nel layout assets**: aggiunta la nuova pagina `/assets/verifiche-periodiche/` dentro il shell standard del modulo, con KPI, form di gestione, lista verifiche e collegamenti diretti da scheda asset, dettaglio asset e form macchine di lavoro.

- **[db] Migrazioni e ACL verifiche periodiche**: create `assets.0016_periodicverification` e `assets.0017_seed_periodic_verifications_sidebar_button`, registrato il modello in admin e aggiunta la voce ACL/sidebar `periodic_verifications` per gli ambienti gia esistenti.

- **[qa] Copertura test asset aggiornata**: aggiunti test per creazione verifica periodica con fornitore e asset multipli, oltre all'assegnazione di piu verifiche sul singolo asset.

- **[versioning] Versione allineata**: aggiornati `django_app/VERSION` e `config.settings.base.APP_VERSION` alla release corrente `0.6.28-dev`.

## 0.6.27-dev - 2026-03-08

- **[fix] Login SQL Server realmente resiliente senza `core_siteconfig`**: `SiteConfig.get_many()` ora materializza la queryset dentro il blocco `try`, cosi l'errore `ProgrammingError` viene assorbito anche quando SQL Server fallisce solo in fase di esecuzione e `/login/` torna ai default applicativi invece di rispondere 500.

- **[qa] Test allineato al comportamento reale di SQL Server**: il test sul login simula ora una queryset che esplode in iterazione, coprendo il caso che aveva bucato la prima correzione.

- **[db] Merge migrazioni core completato**: aggiunta la migration `core.0018_merge_0016_navigationitem_parent_code_0017_loginbanner` per chiudere davvero il conflitto tra i leaf `0016` e `0017` e ripristinare l'esecuzione di `migrate` e dei test.

- **[versioning] Versione allineata**: aggiornati `django_app/VERSION` e `config.settings.base.APP_VERSION` alla release corrente `0.6.27-dev`.

## 0.6.26-dev - 2026-03-08

- **[feature] Mappa officina su planimetria PNG/JPG**: aggiunte nuove entita `PlantLayout`, `PlantLayoutArea` e `PlantLayoutMarker` nel modulo `assets`, con vista utenti interattiva (`/assets/work-machines/map/`) ed editor admin (`/assets/work-machines/map/editor/`) per disegnare reparti e posizionare macchine di lavoro sopra la planimetria.

- **[ux] Collegamento rapido alla mappa officina**: inseriti accessi diretti alla nuova mappa dalle schermate `Dashboard officina` e `Macchine di lavoro`, piu seed sidebar `plant_layout_map` per ambienti con menu assets configurabile.

- **[fix] Login resiliente senza `core_siteconfig`**: `SiteConfig` ora degrada in fallback sicuro se la tabella non esiste ancora nel DB e la pagina `/login/` usa un fetch unico con default applicativi invece di generare `ProgrammingError`.

- **[versioning] Versione allineata**: aggiornati `django_app/VERSION` e `config.settings.base.APP_VERSION` alla release corrente `0.6.26-dev`.

## 0.6.25-dev - 2026-03-08

- **[feature] Subnav centralizzata e configurabile da admin**: la barra secondaria (subnav bianca) è ora gestita dal Navigation Builder anziché essere hardcodata in ogni app. L'admin può aggiungere, modificare e riordinare le voci subnav per ogni sezione direttamente dall'interfaccia, senza toccare il codice.

- **[feature] Navigation Builder — sezione `subnav`**: aggiunta la sezione `subnav` alle voci di navigazione. Ogni voce subnav ha un campo `parent_code` (es. `dashboard`, `assenze`, `anagrafica`) che determina in quale sezione appare.

- **[feature] Drag-and-drop riordino voci**: nel Navigation Builder è ora possibile trascinare le righe della tabella per riordinarle; l'ordine viene salvato automaticamente tramite il nuovo endpoint `/api/navigation/reorder`.

- **[infra] `get_subnav_nodes()` in navigation_registry**: aggiunta funzione dedicata che restituisce le voci subnav filtrate per `parent_code` e ruolo utente, con cache versioned.

- **[infra] Context processor aggiornato**: `legacy_nav()` inietta ora anche `subnav_items` (lista voci subnav per la sezione corrente) in ogni request; il rilevamento della sezione avviene tramite `request.resolver_match.app_name`.

- **[db] Migrazione `core.0014`**: aggiunto campo `parent_code` a `NavigationItem`.

## 0.6.24-dev - 2026-03-08

- **[feature] Nuova app `anagrafica`**: creata sezione autonoma separata da `admin_portale`, con dashboard, lista dipendenti (sola lettura da legacy SQL Server) e gestione completa fornitori.

- **[feature] Gestione fornitori CRUD**: creazione/modifica/disattivazione fornitore con categorizzazione (MATERIALI, SERVIZI, ATTREZZATURE, LOGISTICA, IT, MANUTENZIONE, ALTRO), dati anagrafici completi, filtri e paginazione.

- **[feature] Allegati fornitore**: upload documenti per fornitore (`FornitoreDocumento`) con tipologia (contratto, visura, DURC, certificato, offerta, ecc.) e cancellazione con cleanup file su disco.

- **[feature] Storico ordini fornitore**: `FornitoreOrdine` con numero ordine, data, importo, stato (bozza/confermato/consegnato/annullato) e aggiornamento stato inline.

- **[feature] Valutazioni fornitore**: `FornitoreValutazione` con rating 1-5 su qualità, puntualità, comunicazione; calcolo automatico punteggio medio e rendering barre grafiche.

- **[feature] Asset assegnati a fornitore**: modello `FornitoreAsset` che collega `Fornitore` → `assets.Asset` con tipo relazione (manutenzione/assistenza/noleggio/fornitura), date e stato attivo/scaduto; FK unidirezionale da `anagrafica` verso `assets` senza modificare l'app assets.

- **[ux] UI moderna con sistema `ana-*`**: tutte le pagine anagrafica (lista fornitori, dettaglio fornitore, form fornitore, lista dipendenti) riscritte con design system `ana-*` CSS: KPI cards, tabelle moderne, badge categoria, barre rating, layout a colonne responsive.

- **[ux] Dashboard fornitore a tabs**: pagina `fornitore_detail` con hero header, 4 metriche KPI (ordini/spesa/rating/asset), tab switcher vanilla JS (Ordini/Documenti/Valutazioni/Asset), sidebar contatti e rating bars.

- **[ux] Form fornitore moderno**: `fornitore_form` riscritto con sezioni collassate (Dati aziendali / Contatti / Indirizzo / Altro), griglia 4 colonne responsive, validazione inline.

- **[db] Migrazioni anagrafica**: applicate `anagrafica.0001_initial` e `anagrafica.0002_fornitoreasset` su dev (SQLite) e prod (SQL Server).

- **[infra] Componenti template autonomi**: `anagrafica/components/` con subnav, page_header, flash_messages indipendenti da `admin_portale`.

## 0.6.23-dev - 2026-03-07

- **[fix] Assenze CAR riallineate a SharePoint**: corretta la lettura dello stato richieste quando `Consenso` e gia `Approvato/Rifiutato` ma `_ModerationStatus` resta incoerente su `In attesa`, evitando il ritorno in pending delle stesse pratiche il giorno successivo.

- **[ux] Diagnostica sync assenze**: aggiunto pulsante `Diagnostica sync` nella dashboard CAR con pannello di confronto tra stato locale, `Consenso` SharePoint, `_ModerationStatus` e stato effettivo letto dal portale, piu feedback immediato dopo `Approva/Rifiuta`.

- **[fix] Riconciliazione pendenti assenze lato dashboard**: prima di mostrare le richieste in attesa il portale ricontrolla i pendenti visibili su SharePoint e aggiorna subito il DB locale se il record remoto risulta gia chiuso.

- **[feature] Template etichette assets multi-livello**: introdotta gestione template QR su tre scope (`generale`, `per tipologia asset`, `per singolo asset`) con risoluzione `override asset -> tipologia -> generale`.

- **[ux] Configurazione etichette spostata in admin assets**: `assets/gestione/?tab=config` ora espone il template generale, la matrice per categoria asset con assegnazione/configurazione dedicata e l'elenco override personali direttamente dalla sezione admin.

- **[admin+db] AssetLabelTemplate esteso**: aggiunti campi `scope`, `asset_type` e relazione `asset` con migration `assets.0014_assetlabeltemplate_scope_asset_and_more`; aggiornato anche il Django admin per filtrare e cercare i template per ambito.

- **[test] Copertura aggiornata**: estesi `assenze.tests` e `assets.tests` con casi su incoerenza SharePoint, riconciliazione pendenti, precedenza template etichette e gestione dal tab configurazione admin.

## 0.6.22-dev - 2026-03-06

- **[ux] Versione visibile in dashboard**: aggiunto piè di pagina nella dashboard con versione portale, data release corrente e conteggio moduli versionati.

- **[ux] Area admin con release notes**: il pannello amministrazione ora espone una card `Versioning e Release Notes` con versione portale, versioni dei moduli e riepilogo ultima release.

- **[feature] Supporto versioning per modulo**: introdotta configurazione `MODULE_VERSIONS` con override dedicati via environment (`APP_VERSION_CORE`, `APP_VERSION_ASSETS`, `APP_VERSION_TASKS`, ecc.) mantenendo una versione globale unica come default.

- **[infra] Registry versioni centralizzato**: aggiunto `core.versioning` e nuovo context processor per rendere disponibili versione app, changelog corrente e versioni moduli nei template.

- **[test] Copertura UI versioning**: aggiunti test su footer dashboard e card versioning admin.

## 0.6.21-dev - 2026-03-06

- **[feature] Officina su modulo Assets**: introdotto profilo dedicato `WorkMachine` collegato `1:1` ad `Asset`, con import Excel macchine di lavoro, lista dedicata, create/edit manuale, dettaglio tecnico e dashboard officina.

- **[ux] Assets resi configurabili lato utente**: sistemata la tabella inventario (`record` click fix) e aggiunte funzioni smart con colonne selezionabili/ridimensionabili/riordinabili, widget drag & drop, popup `Admin Studio` e layout persistito in `localStorage`.

- **[feature] Documentazione macchina estesa**: aggiunti allegati reali `AssetDocument`, gestione manuali/specifiche/interventi nel form macchina, campo esplicito `prossima manutenzione`, reminder dashboard su soglia e vista scadenze officina.

- **[feature] SharePoint + QR per asset/macchine**: nuovi campi cartella SharePoint su asset, pulsanti diretti da dettaglio, predisposizione sync upload via Microsoft Graph e nuova stampa etichetta PDF con QR code verso scheda asset o cartella SharePoint.

- **[db] Migrazioni assets**: applicate `assets.0007`-`assets.0011` per tipi macchina, sidebar/dashboard officina, manutenzione esplicita, allegati documentali e metadati SharePoint.

- **[test] Copertura assets aggiornata**: suite `assets.tests` estesa fino a 23 test con verifica import officina, form macchina, dashboard reminder, dettaglio SharePoint e PDF QR.

## 0.6.20-dev - 2026-03-05

- **[feature] Check sovrapposizione impegni su assegnazione task**: in create/edit task viene verificata la presenza di altre task attive gia assegnate allo stesso operatore nello stesso intervallo pianificato (`next_step_due`/`due_date`).

- **[ux] Alert operativo su carico incaricato**: dopo salvataggio task vengono mostrati warning con riepilogo impegni sovrapposti (titoli task e finestre data) per evitare sovraccarico pianificazione.

- **[feature] Scelta gestione conflitto con priorita**: introdotto campo form `Se l'operatore ha altri impegni nello stesso periodo` con opzione di rialzo automatico priorita a `High` in caso di conflitto.

- **[test] Copertura creazione task aggiornata**: aggiunti test su alert conflitto assegnazione e su auto-aggiornamento priorita (`LOW -> HIGH`) quando selezionato.

## 0.6.19-dev - 2026-03-05

- **[fix] Drag Gantt allineato al cursore**: riscritta la logica di trascinamento task su timeline con aggancio alla cella sotto il mouse (non piu solo delta pixel), supporto pointer capture e auto-scroll orizzontale ai bordi tabella.

- **[validation] Regola date task resa stretta**: `data fine` ora deve essere strettamente successiva a `data inizio/next step` (`due_date > next_step_due`) su model/form e update rapido Gantt.

- **[ux] Evidenza intervallo non valido**: le celle timeline di task con range incoerente sono colorate in rosso/stripes con avviso esplicito in riga e legenda.

- **[test] Copertura Gantt estesa**: aggiunti test su blocco update con `fine == inizio` e su rendering classe `is-invalid-range` in vista progetto Gantt.

## 0.6.18-dev - 2026-03-05

- **[ux] Sezione assets completamente in italiano**: tradotti titoli pagina, pulsanti, filtri, card KPI, tabella inventario, etichette dettaglio e testi operativi delle pagine asset/workorder/report.

- **[ux] Shell assets italiana**: aggiornati branding shell, placeholder ricerca, etichetta ruolo utente e call-to-action principale.

- **[ux] Sidebar e azioni italianizzate**: tradotte voci menu predefinite, etichette pulsanti azione e fallback runtime per configurazioni legacy con label inglesi gia salvate.

- **[model] Etichette `choices` italiane**: aggiornate scelte visibili per tipi/stati asset, stati/tipi intervento, sezioni sidebar, zone/azioni/stili pulsanti.

- **[form] Form assets rietichettati**: introdotte label italiane su create/edit/assegnazione asset e su form interventi (creazione/chiusura).

- **[ops] Seed nav/ACL riallineati**: default label navigation e descrizioni ACL aggiornate in italiano per le nuove installazioni/seeding.

- **[qa] Verifiche superate**: eseguiti `manage.py check` e `manage.py test assets.tests` (SQLite/dev) con esito OK.

## 0.6.17-dev - 2026-03-05

- **[feature] Asset import Excel ricostruito e reso tollerante**: ripristinato `import_assets_excel` con rilevamento automatico header riga, matching fogli flessibile (case-insensitive/fuzzy) e fallback su tutti i fogli disponibili.

- **[feature] Supporto nuovi dataset inventario**: esteso import a scenari con fogli/ambiti aggiuntivi (`Telefonia`, `SIM Telefonica`, `TVCC`, ecc.) e colonne non uniformi tra tipi macchinario.

- **[feature] Colonne dinamiche auto-create**: i campi non mappati vengono creati automaticamente come `AssetCustomField` e salvati in `Asset.extra_columns` con tipizzazione base (testo/numero/data/si-no).

- **[security] Sanitizzazione campi sensibili in import**: password/PIN/PUK/PSW non vengono mai salvati in chiaro; viene registrato solo flag di presenza (`... (presente)`).

- **[docs+test] Documentazione e copertura aggiornate**: README assets aggiornato con nuove opzioni (`--all-sheets`) e aggiunti test su colonne dinamiche, campi sensibili e matching foglio fuzzy.

## 0.6.16-dev - 2026-03-05

- **[feature] Progetti Task estesi con anagrafica commessa**: aggiunti campi progetto `cliente`, `project_manager`, `capocommessa`, `programmatore`, `metodo di controllo`, `P/N`, `lavorazione simile` (progetto esistente) e `lavorazione simile` libera.

- **[db] Migrazione tasks**: nuova migration `tasks.0006_project_capo_commessa_project_client_name_and_more` con i nuovi campi strutturali su `Project`.

- **[ux] Form task aggiornato per creazione progetto completa**: nella sezione creazione nuovo progetto ora sono presenti tutti i metadati operativi richiesti; supportata sia selezione lavorazione simile esistente sia inserimento ex-novo.

- **[feature] Controllo assenze su pianificazione task**: su create/edit/update date task viene verificata la sovrapposizione con ferie/permessi dell'assegnatario (tabella `assenze`) e viene emesso warning non bloccante.

- **[feature] Gantt progetto con conflitti assenze**: giorni in conflitto con assenza assegnatario sono evidenziati in riga task con sfondo rosso e marker `X`, tooltip dettaglio e contatore conflitti in metadati riga.

- **[ux] Pagine progetto arricchite**: metadati progetto estesi visibili in dettaglio task, lista progetti e header Gantt.

- **[test] Copertura estesa**: aggiunti test per metadati progetto in creazione task e per rilevamento conflitti assenze + rendering marker nel Gantt.

## 0.6.15-dev - 2026-03-05

- **[ux] Task form create/edit ristrutturato**: pagina di inserimento task riscritta con sezioni operative (`Contesto e Progetto`, `Definizione attivita`, `Pianificazione`, `Responsabilita e visibilita`) e terminologia piu chiara per utenti non tecnici.

- **[ux] Terminologia task allineata al processo**: label/help dei campi aggiornati in `TaskForm` (es. `Data prevista conclusione`, `Operatore incaricato`, `Prossima azione`) con indicazioni esplicite su overdue e coerenza date.

- **[feature] Task dashboard admin estesa**: aggiunta `Control room amministrativa` nella lista task (solo `tasks_admin`) con KPI operativi (`non assegnate`, `senza data`, `task singole`, `scadenza 7 giorni`, `in corso ferme`) e riepilogo progetti piu critici.

- **[feature] Filtri task avanzati**: nuovi filtri lista `unassigned`, `without_due_date`, `without_project` con applicazione server-side.

- **[feature] Asset Admin Studio potenziato**: sezione admin inventario arricchita con metriche configurazione, pannello check di consistenza e operazioni rapide inline.

- **[feature] Export configurazione admin assets**: nuova azione `export_admin_snapshot` con download JSON di campi custom, liste, action button e sidebar button.

- **[test] Copertura aggiornata**: aggiunti test su nuovi filtri task e su export snapshot admin assets (permessi + payload).

## 0.6.14-dev - 2026-03-05

- **[security] Task edit esteso a admin/capo progetto**: la modifica completa task (/tasks/`<id>`/edit/) e le azioni operative di dettaglio (status, subtasks, allegati) ora consentono accesso anche al capo progetto (Project.created_by) oltre a tasks_admin e tasks_edit.

- **[feature] Data prevista conclusione aggiornabile da incaricato/admin**: nuova route POST tasks/`<id>`/update-due-date/ con form dedicato in dettaglio task; autorizzati tasks_admin, capo progetto, ruoli con tasks_edit e assegnatario task.

- **[audit] Tracciamento update scadenza**: aggiornamenti su due_date tramite nuovo form generano evento TaskEventType.EDIT con payload modifiche.

- **[ux] Dettaglio task migliorato**: campo Scadenza task ora include azione rapida Aggiorna data prevista senza entrare nel form completo.

- **[security] Gantt progetto coerente con ruolo capo progetto**: edit schedule Gantt esteso anche al creator del progetto (capo progetto), mantenendo ACL server-side e anti-IDOR.

- **[test] Copertura permessi estesa**: aggiunti test su modifica task da capo progetto, blocco edit per non autorizzati, update due date per assegnatario/admin e blocco per viewer in scope.

## 0.6.13-dev - 2026-03-05

- **[ux] Gantt ridimensionabile via drag**: colonne sinistra (WBS, Nome attivita, Durata, Inizio, Fine) ora ridimensionabili trascinando il bordo header; layout salvato in localStorage per progetto.

- **[ux] Altezza/larghezza celle regolabili live**: aggiunti slider Zoom giorni e Altezza righe con aggiornamento immediato del diagramma.

- **[feature] Drag & drop timeline giorni**: trascinando una cella attiva di task sul diagramma viene eseguito shift orizzontale delle date (next_step_due, due_date) con persistenza server-side.

- **[security] Endpoint shift protetto ACL**: nuova route POST tasks/projects/`<id>`/gantt/tasks/`<task_id>`/shift/ con controllo scope progetto e regole edit (tasks_admin oppure tasks_edit + assegnazione).

- **[audit] Tracciamento shift date**: lo spostamento via drag genera eventi audit EDIT con payload modifiche date.

- **[test] Copertura Gantt estesa**: aggiunti test su shift consentito, negato e out-of-scope.

## 0.6.12-dev - 2026-03-05

- **[ux] Gantt con colonne personalizzabili**: aggiunta barra "Opzioni vista" in pagina progetto per mostrare/nascondere colonne WBS/Durata/Inizio/Fine.

- **[ux] Timeline molto piu ampia**: introdotti preset finestra temporale (1 mese, 2 mesi, 3 mesi, 4 mesi, Auto) per estendere la colonna giorni in formato quasi mensile.

- **[ux] Dimensioni colonna configurabili**: scelta larghezza celle giorni (Compatta/Standard/Ampia) e larghezza colonna "Nome attivita".

- **[ux] Persistenza configurazione vista**: salvataggio task Gantt e commenti progetto mantengono i parametri di visualizzazione correnti.

## 0.6.11-dev - 2026-03-05

- **[ux] Gantt progetto in formato classico tabellare**: la vista tasks/projects/`<id>`/gantt/ ora usa una griglia timeline giornaliera (intestazioni mese/giorno, colonne WBS/Nome attivita/Durata/Inizio/Fine) con rendering tipo diagramma Gantt tradizionale.

- **[ux] Evidenza stato su timeline**: le celle attive della griglia sono colorate per stato task (TODO, IN_PROGRESS, DONE, CANCELED) con evidenza giorno corrente e weekend.

- **[ux] Gestione separata dalla timeline**: aggiunta sezione Modifica rapida timeline sotto al diagramma per aggiornare next_step_due, due_date, status senza perdere la leggibilita della matrice.

## 0.6.10-dev - 2026-03-05

- **[feature] Tasks: Gantt Progetti**: aggiunte viste `tasks/projects/` e `tasks/projects/`<id>`/gantt/` con timeline visuale delle task di progetto.

- **[security] Edit Gantt con regola dedicata**: modifica timeline consentita solo a `tasks_admin` oppure utenti con `tasks_edit` assegnati ad almeno una task del progetto.

- **[feature] Commenti con notifica target utente**: esteso `TaskComment` con `target_user` e aggiunto `ProjectComment` con notifica in-app (`Notifica`, tipo `generico`) all'utente selezionato.

- **[feature] Commenti progetto**: nuova area commenti nel Gantt progetto con invio notifica opzionale a utente specifico.

- **[ux] Navigazione Tasks estesa**: aggiunti link rapidi alla sezione Progetti/Gantt da dashboard lista task e dettaglio task.

- **[db] Migrazione tasks**: aggiunta migration `tasks.0005_taskcomment_target_user_projectcomment`.

- **[test] Copertura estesa tasks**: aggiunti test su accesso/anti-IDOR Gantt, regole edit schedule e notifiche commenti task/progetto.

## 0.6.9-dev - 2026-03-05

- **[feature] Tasks: Progetti come contenitore**: introdotto modello Project e collegamento opzionale Task.project per gestire task singole o raggruppate in progetto.

- **[feature] Tasks: scelta create/edit "Task singolo" o "Task in progetto"**: il form task supporta selezione tipologia con opzione progetto esistente o creazione nuovo progetto inline.

- **[feature] Tasks: Allegati task/progetto**: introdotto modello TaskAttachment, upload file da dettaglio task con destinazione task corrente o progetto collegato.

- **[feature] Audit trail esteso**: aggiunto evento ATTACHMENT_ADDED su upload allegati con payload (attachment_id, target, file_name, riferimenti task/progetto).

- **[ux] Dashboard/lista/dettaglio estesi**: filtro lista per progetto, evidenza progetto su card task, sezione allegati in dettaglio con storico upload.

- **[admin] Backoffice tasks aggiornato**: registrati in Django admin i modelli Project e TaskAttachment; TaskAdmin esteso con campo/filtro progetto.

- **[db] Migrazione tasks**: aggiunta migration tasks.0004_alter_taskevent_type_project_task_project_and_more.

- **[test] Copertura estesa**: test aggiunti per create task singola/progetto, selezione progetto esistente, upload allegati (task/progetto), audit attachment e anti-IDOR endpoint upload.

## 0.6.8-dev - 2026-03-05

- **[feature] Tasks: tag leggeri e filtrabili**: aggiunto campo `Task.tags` (comma-separated), gestione in create/edit e filtro `tag` in lista task.

- **[feature] Tasks: rollup stato da subtasks**: quando lo stato subtasks evolve, la task principale viene riallineata automaticamente (`TODO/IN_PROGRESS/DONE/CANCELED`) con evento audit `STATUS_CHANGE` marcato `source=subtask_rollup`.

- **[ux] Task UI migliorata**: tag visibili in lista/dettaglio e campo dedicato nel form.

- **[test] Copertura estesa tasks**: aggiunti test su filtro tag e su aggiornamento automatico stato task tramite subtasks.

- **[ux] Task dashboard operativa anche a lista vuota**: aggiunti KPI, quick links alle sottosezioni (mie/in corso/overdue/completate), pannello azioni gestione e messaggi ACL espliciti per i pulsanti non autorizzati.

## 0.6.7-dev - 2026-03-05

- **[feature] Nuova app `tasks` (MVP solido)**: introdotto modulo task completo con modelli Django dedicati (`Task`, `SubTask`, `TaskComment`, `TaskEvent`) e campi operativi richiesti (`title`, `description`, `status`, `priority`, `due_date`, `next_step_text`, `next_step_due`, `created_by`, `assigned_to`, `subscribers`, timestamp).

- **[feature] Enum e ordinamento task**: stati/priorita/eventi implementati con `TextChoices`; ordinamento default task impostato a `next_step_due ASC NULLS LAST`, poi `due_date ASC`, poi `updated_at DESC`.

- **[feature] Audit trail obbligatorio task/subtask**: tracciati eventi `STATUS_CHANGE`, `ASSIGNMENT_CHANGE`, `EDIT`, `COMMENT_ADDED`, `SUBTASK_ADDED`, `SUBTASK_STATUS_CHANGE` con payload JSON e actor.

- **[security] ACL legacy per azione + scope anti-IDOR**: introdotto controllo server-side per `tasks_view`, `tasks_create`, `tasks_edit`, `tasks_comment`, `tasks_admin`; scope visibilita applicato (creator/assignee/subscriber o globale con `tasks_admin`) su lista/dettaglio/azioni e protezione 404 su accesso fuori scope.

- **[feature] UI task + PRG**: nuove pagine `tasks/list.html`, `tasks/detail.html`, `tasks/form.html` con filtri (mie task default, status, priority, overdue, range scadenza, assigned_to), dettaglio completo (timeline eventi, commenti, subtasks) e azioni `POST` con redirect.

- **[feature] Bootstrap ACL legacy tasks**: aggiunto bootstrap idempotente `tasks/acl_bootstrap.py` per registrazione pulsanti legacy (`tasks_view/create/edit/comment/admin`) e metadati topbar.

- **[feature] Navigation Registry v2 integrato**: migration `tasks.0002_nav_entry` aggiunge voce topbar `Task`; filtro runtime in `core/context_processors.py` vincola la visibilita della voce al permesso ACL `tasks_view`.

- **[infra] Wiring progetto**: aggiunta app `tasks` in `INSTALLED_APPS` e include URL namespace `tasks` in `config/urls.py`.

- **[test] Copertura modulo tasks**: aggiunti test per permessi/scope admin vs non-admin, anti-IDOR (detail/edit/status), audit events (status/comment/subtask), filtri lista.

## 0.6.6-dev - 2026-03-05

- **[ux] Asset sidebar fix (pulsanti non piu "giganti")**: corretta la resa della colonna sinistra in `/assets/` rimuovendo lo stretching verticale delle voci menu e riducendo dimensioni/spaziatura dei pulsanti.

- **[feature] Menu sidebar dinamico su DB**: introdotto nuovo modello `AssetSidebarButton` con gestione completa di voci (etichetta, sezione, ordine, sottovoce, visibilita, URL target, match attivo), render dinamico e stato `active` coerente.

- **[feature] Admin Studio inline completo in pagina Asset**: nella dashboard asset aggiunte sezioni operative direttamente modificabili senza uscire dalla pagina:
  - Campi custom (`create/update/delete`)
  - Liste suggerite (`create/update/delete`)
  - Pulsanti azione dettaglio asset (`create/update/delete`)
  - Menu sidebar (`create/update/delete/visibile`)

- **[ux] Tutorial utilizzo Admin Studio**: aggiunto pulsante `Tutorial utilizzo` con popup guida rapida (chiusura via bottone, click esterno, `Esc`) per spiegare workflow e placeholder supportati.

- **[fix] Link Admin Studio**: rimossi i link diretti che portavano fuori contesto verso admin-portale/admin; i pulsanti ora aprono/scrollano le sezioni interne di configurazione.

- **[feature] Seed menu sidebar default modificabile**: aggiunto comando interno dalla UI (`seed_sidebar_buttons`) per generare le voci base editabili quando il menu custom non e ancora presente.

- **[ux] Layout assets uniformato**: esteso layout shell comune (`assets/base_shell.html`) alle principali pagine dell'app (`asset_detail`, `asset_form`, `asset_assignment`, `workorder_*`, `reports_dashboard`) per coerenza visiva e navigazione unificata.

- **[db] Migrazione assets**: nuova migration `assets.0006_assetsidebarbutton` per persistenza configurazione menu sidebar.

## 0.6.5-dev - 2026-03-05

- **[ux] Asset Inventory UI refresh**: pagina `/assets/` resa più fluida e moderna con hero header, quick links, card KPI, layout responsive e tabella click-to-open per accesso rapido al dettaglio asset.

- **[feature] Pulsanti di collegamento rapidi**: aggiunti pulsanti diretti a Inventario, Work Orders, Report e Nuovo Asset nella toolbar superiore della sezione assets.

- **[feature] Upload Excel da interfaccia web**: aggiunto box `Import Excel` nella pagina inventario con selezione file `.xlsx/.xlsm`, scelta fogli CSV, opzioni `dry-run`, `include optional`, `update existing`; avvio import senza terminale.

- **[feature] Smart interactions**: introdotto JS dedicato assets per autosubmit filtri (select + ricerca con debounce), stato di caricamento bottone import e navigazione riga-tabella al click.

- **[refactor] Styling assets separato**: introdotti file statici `assets/css/assets.css` e `assets/js/assets.js`; riduzione inline style e componentizzazione messaggi.

## 0.6.4-dev - 2026-03-04

- **[feature] Nuova app `assets` (Asset Inventory)**: introdotta app Django dedicata all'inventario asset IT/Produzione con modelli normalizzati (`Asset`, `AssetEndpoint`, `AssetITDetails`, `WorkOrder`, `WorkOrderLog`), admin completo, pagine web minime (lista, dettaglio, create/edit, assegnazione, workorder, report).

- **[feature] URL ACL-friendly namespaced**: aggiunte route namespace `assets` con prefissi stabili per ACL legacy:
  - `/assets/`, `/assets/view/`<id>`/`, `/assets/new/`, `/assets/edit/`<id>`/`, `/assets/assign/`<id>`/`
  - `/assets/workorders/`, `/assets/workorders/new/`<id>`/`, `/assets/workorders/view/`<id>`/`, `/assets/workorders/close/`<id>`/`
  - `/assets/reports/`

- **[feature] Seed ACL legacy**: nuovo command `python manage.py seed_assets_acl` che crea/aggiorna in modo idempotente i pulsanti legacy su tabella `pulsanti` (`modulo=assets`) con URL `django:assets:<route_name>`, e invalida cache ACL con `bump_legacy_cache_version()`.

- **[feature] Seed topbar navigation**: nuovo command opzionale `python manage.py seed_assets_nav` per creare/aggiornare `NavigationItem(code="assets", label="Asset", route_name="assets:asset_list", section="topbar")` e accessi ruolo opzionali.

- **[feature] Import massivo Excel asset**: nuovo command `python manage.py import_assets_excel` con supporto `--file`, `--sheets`, `--dry-run`, `--update/--no-update`, `--include-optional`, header row 5, upsert via `source_key` SHA1 e import endpoint/details/manutenzioni.

- **[security] Sanitizzazione campi sensibili import**: durante l'import non viene mai salvato alcun segreto in chiaro (es. `PSW BIOS`); viene persistito solo flag booleano `bios_pwd_set` (ed eventuale `vault_ref` testuale lato modello).

- **[infra] Wiring progetto**: aggiunta app `assets` a `INSTALLED_APPS`, include URL in `config/urls.py` prima di `core.urls`, documentazione operativa in `assets/README.md`.

- **[test] Copertura minima `assets`**: aggiunti test per route `/assets/` (legacy auth OFF), idempotenza seed ACL, dry-run import, import mock riga con creazione `Asset + Endpoint + ITDetails`.

- **[deps] Excel parser**: aggiunto `openpyxl==3.1.5` in `django_app/requirements.txt`.

## 0.6.3-dev - 2026-03-04

- **[config] Validazione cartella allegati da pannello**: `POST /api/anomalie/config/liste` ora valida `attachments_dir` prima del salvataggio (cartella esistente, directory valida e scrivibile). Se non valida, il salvataggio viene bloccato con errore esplicito.

- **[sync] Coda allegati con retry verso SharePoint**: introdotti metadati per file allegato (`pending/synced/error`, retry count, last error, timestamp ultimo tentativo/sync) e push allegati durante `POST /api/anomalie/sync`. Aggiunto pass extra per processare anche allegati pendenti di record già sincronizzati.

- **[permessi] Allegati in sola lettura**: separati i permessi allegati. `list/open/download` consentiti in view mode, mentre `upload/delete` restano consentiti solo agli editori OP (capocommessa/CAR/autorizzati/admin).

- **[ops] Cleanup orfani schedulabile**: nuovo comando `python manage.py cleanup_anomalie_allegati` con modalità report (default) o cancellazione reale (`--delete`), filtro età (`--older-than-days`) e limite (`--limit`).

- **[audit] Tracciamento completo allegati**: audit events aggiunti per upload, delete, open e download allegati (`log_action` su modulo `anomalie`).

- **[ux] Stato sync per-file in UI gestione anomalie**: ripristinata visualizzazione allegati anche in sola lettura e aggiunto stato per file (`Sync SP OK`, `In coda sync`, `Errore sync` con dettaglio errore).

## 0.6.2-dev - 2026-03-03

- **[feature] Gestione Anomalie — completamento modulo**: il modulo anomalie era parzialmente implementato; questa release lo porta a produzione.
  - **[nav] Fix navigazione anomalie**: `context_processors.py`, `topnav.html`, `subnav.html` (core e dashboard) e `anomalie_menu.html` aggiornati per puntare direttamente a `gestione_anomalie_page` (React app) invece della vecchia pagina intermediaria "Migrazione in corso".
  - **[db] Nuove colonne tabella `anomalie`**: aggiunte `numero_rdc NVARCHAR(100) NULL` (salva il numero RDC quando `aprire_rdc=1`) e `created_by_user_id INT NULL` (autore del record, usato per notifiche di chiusura). Script SQL da eseguire: `ALTER TABLE anomalie ADD numero_rdc NVARCHAR(100) NULL; ALTER TABLE anomalie ADD created_by_user_id INT NULL;`
  - **[feature] Allegati anomalia (immagini + documenti)**: nella pagina React `gestione_anomalie` aggiunta gestione allegati multipli con upload, elenco, preview immagini, apertura/scaricamento ed eliminazione. Endpoint introdotti: `api_anomalie_allegati`, `api_anomalie_allegati_upload`, `api_anomalie_allegati_delete`, `api_anomalie_allegati_file`. Validazioni lato server: estensioni consentite (`jpg/jpeg/png/gif/bmp/webp/pdf/doc/docx/xls/xlsx/xlsm/csv`), dimensione massima 20 MB, sanitizzazione nome file e protezione path traversal. Storage locale per record in `media/anomalie_allegati/<local_id>` (override opzionale via file di configurazione legacy, sezione `ANOMALIE.attachments_dir`).
  - **[ux] Apertura segnalazione (`/gestione-anomalie/nuova-segnalazione`)**: aggiunto pulsante `Aggiungi allegati` nel form Step 2 con coda file pre-salvataggio e upload automatico dopo il salvataggio del record (single S/N). In caso di range S/N, allegati disabilitati per evitare associazioni ambigue su più record.
  - **[ux] Gestione anomalia (`/gestione-anomalie`)**: ripristinata preview grande dell'allegato selezionato (immagine o documento) sopra la lista allegati, mantenendo azioni `Apri`, `Scarica`, `Elimina`.
  - **[config] Percorso cartella allegati gestibile da pannello**: nella pagina `gestione-anomalie/configurazione` aggiunto campo `Percorso cartella allegati`; salvataggio nel file di configurazione legacy, sezione `[ANOMALIE]` chiave `attachments_dir`, via API `api/anomalie/config/liste` (GET/POST).
  - **[ux] Campo Numero RDC funzionante**: l'input "Numero RDC" (visibile quando `Aprire RDC = true`) è ora collegato a state React, incluso nel payload di salvataggio e persistito in DB. Incluso anche nell'export CSV.
  - **[ux] Bottoni Aggiungi anomalia e Duplica**: il bottone "Anomalia" ora chiama `handleNewAnomalia()` (svuota form, pronto per nuovo record sull'OP selezionato). Il bottone "Duplica" mantiene i dati del form ma azzera `item_id` (force INSERT). Il bottone "Segnalazione" attiva il toggle `segnalare` e avvisa l'utente.
  - **[audit] Audit trail anomalie**: ogni salvataggio (`api_salva`) registra `anomalia_creata` o `anomalia_modificata` in `AuditLog` tramite `core.audit.log_action`. Anche `api_sync` registra l'evento `anomalie_sync`.
  - **[notifiche] Notifiche in-app anomalie**: `api_salva` emette notifiche in-app (modello `Notifica`) in due casi: (1) `segnalare_cliente=1` ? tenta lookup capocommessa su `ordini_produzione + utenti` e notifica; (2) `chiudere=1` ? notifica l'autore originale (da `created_by_user_id`) se diverso dall'utente corrente. Fire-and-forget, silente in caso di errore.
  - **[refactor] Rinominate view `api_*_placeholder`**: `api_salva_placeholder` ? `api_salva`, `api_sync_placeholder` ? `api_sync`, `api_ordini_placeholder` ? `api_ordini`, `api_anomalie_placeholder` ? `api_anomalie`, `api_campi_placeholder` ? `api_campi`. URL names invariate, nessun breaking change.
  - **[model] Notifica.TIPI estesa**: aggiunti `anomalia_segnalata` e `anomalia_chiusa` alla lista choices del modello `Notifica`. Migration `core.0011_alter_notifica_tipo`.

## 0.6.1-dev - 2026-03-03

- **[ux] Dashboard "Gestione Accessi"**: nuova pagina `/admin-portale/accessi/` — punto unico per ruoli, permessi, pulsanti e override utenti. Mostra statistiche (N ruoli / N pulsanti / N override), tabella ruoli con barra di avanzamento permessi attivi, tabella override utenti recenti con chip ON/OFF/ruolo, link rapidi agli strumenti ACL. View `accessi_dashboard` in `admin_portale/views.py`.

- **[ux] Wizard "Configura Ruolo"**: nuovo flusso guidato a 3 step in `/admin-portale/wizard-ruolo/`. Step 1: selezione ruolo con pulsanti cliccabili (pre-selezione da `?ruolo_id=X`). Step 2: card grid per modulo con toggle `can_view` per ogni pulsante + expand "dettagli" per `can_edit`/`can_delete`/`can_approve` + pulsanti "Tutto ON/OFF" per modulo. Step 3: tabella diff con solo le righe cambiate (badge ON?OFF / OFF?ON), salvataggio via `POST api_permessi_bulk mode=update`, redirect alla dashboard accessi. View `wizard_ruolo` in `admin_portale/views.py`.

- **[ux] Permessi — layout card grid**: `permessi.html` refactored da flat expandable list a griglia di card per modulo (auto-fill min 300px). Ogni card mostra icona modulo, conteggio pulsanti, badge "parziale", toggle modulo, e lista pulsanti con toggle `can_view`. Aggiunto pulsante "?? Apri Wizard ?" nella toolbar (solo modalità ruolo). Logica JS invariata (stesse API).

- **[nav] Subnav "Accessi"**: aggiunto link "Accessi" nella subnav admin (tra "Utenti" e "Permessi"), attivo per `admin_portale:accessi` e `admin_portale:wizard_ruolo`. Aggiunti testi help contestuali per entrambe le nuove pagine.

- **[nav] Home admin — card aggiornata**: card "Gestione Permessi" rinominata in "Gestione Accessi" e punta alla nuova dashboard `/admin-portale/accessi/`.

- **[fix] wizard_ruolo.html — filtro `|tojson` inesistente**: sostituito `{{ url|tojson }}` con `"{{ url|escapejs }}"` (Django built-in) per i valori `api_bulk_url` e `accessi_url`.

## 0.6.0-dev - 2026-03-02

- **[feature] App Notizie / Comunicazioni**: nuova app Django `notizie` per la gestione delle comunicazioni aziendali con prova di lettura versionata e audit trail. Modelli: `Notizia` (bozza/pubblicata/archiviata, campo `obbligatoria`), `NotiziaAudience` (audience per ruolo legacy, nessun record = visibile a tutti), `NotiziaAllegato` (upload file + link esterni, SHA-256 automatico), `NotiziaLettura` (versioned: `unique_together = (notizia, legacy_user_id, versione_letta)` per audit completo). Hash versione SHA-256 su titolo+corpo+versione+allegati (escluso `id`). Compliance: `non_letto` / `aperto` / `conforme` / `non_conforme` (nuova versione ? non conforme senza cancellare storia).

- **[feature] Notizie — Admin Django**: `NotiziaAdmin` con inline allegati e letture (read-only), azioni admin `pubblica_notizie` e `archivia_notizie`, filtri per stato/obbligatoria, ricerca per titolo.

- **[feature] Notizie — Viste e URL**: `notizie_lista` (filtri ruolo + badge compliance), `notizie_dettaglio` (tracking `opened_at` automatico), `notizie_conferma` POST idempotente con log e invalidazione cache, `notizie_obbligatorie` (safe path), `notizie_report` (solo admin/hr, filtri notizia/stato/data), `notizie_report_csv` (`StreamingHttpResponse`, encoding `utf-8-sig`).

- **[feature] Notizie — Gating middleware** (`NotizieMandatoryMiddleware`): posizionato dopo `ACLMiddleware`, blocca accesso al portale se l'utente ha notizie obbligatorie non confermate (redirect a `/notizie/obbligatorie/`). Tutta la prefix `/notizie/` è safe. Cache TTL 60s con invalidazione esplicita dopo conferma.

- **[feature] Notizie — ACL bootstrap**: pulsanti `notizie_lista` e `notizie_report` registrati via `acl_bootstrap.py` (pattern identico a `assenze`), chiamato in `AppConfig.ready()`.

- **[feature] Notizie — Navigation Registry**: voce `notizie` aggiunta in `topbar` (order 50) via data migration `0002_nav_entry`.

- **[fix] Login redirect corretto**: `LOGIN_REDIRECT_URL = "dashboard_home"` (era `"dashboard"`, causava redirect a view fittizia). Corretti anche `reverse("dashboard")` ? `reverse("dashboard_home")` in `accounts/views.py` e `windows_sso.py`.

- **[fix] `requests` aggiunto a requirements.txt**: dipendenza mancante che causava `ModuleNotFoundError` in ambienti puliti.

- **[fix] `SQL_LOG_ENABLED` default prod**: cambiato da `True` a `False` in `base.py` (evitava log query SQL massiccio in produzione per default).

- **[fix] `import tempfile` mid-file**: spostato all'inizio del file in `base.py`, rimosso duplicato.

- **[refactor] `provision_legacy_user` centralizzato**: estratto in `core/legacy_utils.py`, eliminando la duplicazione tra `LDAPBackend.authenticate()` e `windows_sso._get_or_create_user()`. Aggiunto `_normalize_principal()` in `windows_sso.py` per uniformare UPN/NTLM.

- **[refactor] `MIDDLEWARE_EXEMPT_PREFIXES` centralizzato**: tupla unica in `base.py`, entrambi i middleware (`session_middleware.py`, `middleware.py`) la leggono via `getattr(settings, ...)`.

- **[perf] `_load_ini()` singleton**: in `assenze/views.py` il parser `ConfigParser` viene istanziato una volta sola a livello di modulo invece di ogni richiesta.

- **[security] X-Forwarded-For sanitizzato**: `_get_client_ip` in `core/audit.py` usa l'header `X-Forwarded-For` solo se `REMOTE_ADDR` è in `TRUSTED_PROXY_IPS` (impostazione `base.py`). Prevenuto IP spoofing su installazioni senza reverse proxy.

- **[ops] File morti rimossi**: eliminati `rwe.py`, `test_structure.py`, `update db.py`, `users.json`, `___All_Errors.txt`, `app.spec`, `app.log`, `opzione_C.html`.

- **[test] Suite notizie**: 21 test (`HashVersioneTests`, `AudienceTests`, `ComplianceTests`, `NotizieACLTests`, `PrisaVisioneTests`, `GatingMiddlewareTests`) — verdi su SQLite (dev) e SQL Server (prod). Fix: helpers usano `Profile` come fallback (tabella `utenti` unmanaged non disponibile in test DB); `SECURE_SSL_REDIRECT=False` aggiunto agli `@override_settings` per compatibilità test su prod settings.

## 0.5.5-dev - 2026-03-02

- **[model] Relazione esplicita `utenti` ? `anagrafica_dipendenti`**: aggiunto `OneToOneField utente` (db_column `utente_id`) su `AnagraficaDipendente` con FK verso `UtenteLegacy`. Chiarito in commento che `utenti.email` è un login_id UPN (es. `l.bova@example.local`), non un'email reale.

- **[model] Campo `email_notifica` su `anagrafica_dipendenti`**: nuovo campo per l'email reale di notifica (es. `l.bova@example.com`), separata dal login_id.

- **[ops] Import CSV con provisioning FK e `email_notifica`**: `import_dipendenti_csv --sync-legacy-users` ora popola `anagrafica_dipendenti.utente_id` (FK verso `utenti.id`) e accetta colonna opzionale `EMAIL_NOTIFICA` dal CSV. `_ensure_extra_columns()` aggiunge automaticamente le colonne `mansione`, `email_notifica` e `utente_id` se assenti (SQLite e SQL Server).

- **[fix] Matching anagrafica con FK**: in `/admin-portale/utenti/` e scheda utente, `_attach_anagrafica_to_users()` e `utente_edit` ora usano il JOIN tramite `utente_id` come lookup primario, con fallback email/alias per record legacy non ancora collegati.

- **[auth] Password locale sempre attiva**: ordine `AUTHENTICATION_BACKENDS` confermato con `SQLServerLegacyBackend` prima di `LDAPBackend` — la password offline configurata localmente continua a funzionare anche quando AD è disponibile; la password AD funziona come secondo metodo tramite `LDAPBackend`.

- **[ops] Import iniziale dipendenti**: eseguito import live da `DIPENDENTI.csv` (371 righe): 139 aggiornati, 137 nuovi utenti legacy creati, 232 saltati (senza username). Colonne `email_notifica` e `utente_id` aggiunte automaticamente al DB.

## 0.5.4-dev - 2026-03-01

- **[feature] Import CSV dipendenti (anagrafica centralizzata)**: aggiunto comando `python manage.py import_dipendenti_csv <file.csv>` per importare/aggiornare `anagrafica_dipendenti` da file HR con mapping `USERNAME -> aliasusername`, normalizzazione automatica di formati `alias`, `dominio\alias`, `alias@dominio`, opzioni `--dry-run`, `--limit`, `--email-domain`, `--overwrite-email`.

- **[feature] Login offline più robusto per alias AD**: `SQLServerLegacyBackend` ora risolve l'utente legacy anche partendo da alias Windows/LDAP (`l.bova`, `EXAMPLE\l.bova`, `l.bova@example.local`) con fallback su `anagrafica_dipendenti.aliasusername -> email`.

- **[ops] Provisioning utenti legacy opzionale da import**: il comando CSV supporta `--sync-legacy-users` per creare/allineare anche la tabella `utenti` (offline login), con password iniziale esplicita via `--default-password`.

- **[model] Anagrafica legacy estesa: colonna `mansione`**: `import_dipendenti_csv` ora supporta il campo CSV `MANSIONE` e, per SQL Server/SQLite, può aggiungere automaticamente la colonna `anagrafica_dipendenti.mansione` se assente (disattivabile con `--no-ensure-schema`).

- **[feature] Sezione Organigramma**: nuova pagina `/organigramma/` con vista gerarchica reparto -> mansione -> persone, filtri per reparto/mansione/ricerca testuale e integrazione in subnav.

- **[ux] Rubrica/Profilo/Scheda Utente**: visualizzazione `mansione` aggiunta nelle pagine utente (`/rubrica/`, `/profilo/`, `/admin-portale/utenti/`<id>`/` tab Anagrafica) con fallback sicuro quando la colonna non è disponibile.

- **[ux] Pulsante upload CSV da UI**: in `/admin-portale/anagrafica-config/` aggiunta card `Import dipendenti (CSV)` con selezione file, dominio email e opzione dry-run; l'import lancia internamente il comando `import_dipendenti_csv` e mostra esito via flash message.

- **[ux] Tabella utenti con colonne configurabili**: in `/admin-portale/utenti/` aggiunte colonne anagrafiche (`reparto`, `mansione`, `username AD`) e nuovo pulsante `Colonne` per mostrare/nascondere le colonne visibili. La preferenza viene salvata localmente nel browser (persistenza per utente/macchina).

- **[ops] Import CSV da UI con provisioning utenti offline**: la card `Import dipendenti (CSV)` ora include opzione `Crea/Aggiorna utenti login offline` + password iniziale; quando attiva passa `--sync-legacy-users` al comando di import.

- **[fix] Matching anagrafica in lista utenti**: in `/admin-portale/utenti/` l'aggancio dati anagrafici ora usa sia email sia alias AD (local-part email), migliorando la compilazione delle colonne per domini email diversi.

## 0.5.3-dev - 2026-03-01

- **[ops] SQL log dedicato**: aggiunto logging SQL su file rotante `logs/sql.log` (logger `django.db.backends`) con configurazione via `.env` (`SQL_LOG_ENABLED`, `SQL_LOG_LEVEL`, `SQL_LOG_FORCE_DEBUG_CURSOR`, `SQL_LOG_MAX_BYTES`, `SQL_LOG_BACKUP_COUNT`). Introdotto hook `connection_created` per forzare `debug cursor` quando richiesto e tracciare query/tempi in modo consistente.

- **[model] Migration core 0009**: aggiunge il campo `categoria` ai modelli `AnagraficaVoce` (default `Campi extra`) e `ChecklistVoce` (default `Generale`).

- **[feature] Categorie per campi configurabili (Anagrafica + Checklist)**: introdotto campo `categoria` per `AnagraficaVoce` e `ChecklistVoce` con gestione da UI admin (modali create/edit). I campi sono ora visualizzati raggruppati per categoria nella scheda utente (`/admin-portale/utenti/`<id>`/`, tab Anagrafica) e nelle esecuzioni checklist (`/admin-portale/checklist/utenti/`<id>`/`).

- **[audit] Checklist con storico completo**: aggiunto audit trail su create/update/toggle/delete delle `ChecklistVoce` e su ogni esecuzione checklist (`api_checklist_esegui`) con snapshot risposte (voce, tipo, valore), utente target e metadati. Consultabile in `/admin-portale/audit/` filtrando modulo `admin_checklist`.

- **[audit] Tracciamento completo campi extra anagrafica**: aggiunto audit trail su create/update/toggle/delete delle `AnagraficaVoce`, salvataggio `UserExtraInfo` e modifiche valori `AnagraficaRisposta` (before/after, utente target, conteggio cambi). Storico consultabile in `/admin-portale/audit/` filtrando modulo `admin_anagrafica`.

- **[ux] Checklist utente - link rapido configurazione voci**: in `/admin-portale/checklist/utenti/`<id>`/` aggiunti link sempre visibili `+ Aggiungi/Configura voci` nelle card Check-in/Check-out, per accedere subito alla pagina di setup globale `/admin-portale/checklist/` ed evitare blocchi operativi.

- **[arch] Caporeparto locale e indipendente da SharePoint**: la card `Capireparto` in `/admin-portale/anagrafica-config/` e il campo `Caporeparto` nella scheda utente tornano a usare `OptioneConfig` locale. CRUD live riattivato per tipo `caporeparto`, senza dipendenze da SharePoint o dalla tabella legacy `capi_reparto`.

- **[feature] Gestione reparto per admin e caporeparto**: nuova pagina `/gestione-reparto/` con salvataggio AJAX per assegnare `reparto` e `caporeparto` agli utenti tramite `UserExtraInfo`. Gli admin possono impostare entrambi i valori; i capireparto possono assegnare utenti solo al proprio reparto.

- **[feature] Anagrafica configurabile â€” dropdown e campi extra**: nuova pagina admin `/admin-portale/anagrafica-config/` per configurare le liste di opzioni e i campi extra del profilo dipendente. I campi Â«RepartoÂ», Â«CaporepartoÂ» e Â«Macchina di utilizzoÂ» nel tab Anagrafica della scheda utente diventano `<select>` quando le rispettive liste sono configurate (graceful degradation a `<input text>` se vuote). Admin puÃ² aggiungere nuovi reparti, capireparto e macchine dalla pagina di config. Aggiunta sezione Â«Campi extraÂ» con pulsante Â«+ Aggiungi campoÂ» (analogo alle voci checklist): campi configurabili di tipo testo, checkbox, data o scelta da lista, visibili e compilabili nel tab Anagrafica di ogni utente. Campo `reparto` aggiunto a `UserExtraInfo` (editabile separatamente dal reparto read-only di `anagrafica_dipendenti`).

- **[model] Migration core 0008**: aggiunge `reparto` a `UserExtraInfo`, crea modelli `OptioneConfig`, `AnagraficaVoce`, `AnagraficaRisposta`.

- **[api] Nuovi endpoint anagrafica**: `api_opzione_create/update/toggle/delete`, `api_anagrafica_voce_create/update/toggle/delete`, `api_anagrafica_risposte_save`.

## 0.5.2-dev - 2026-03-01

- **[feature] Wizard Onboarding / Offboarding (Check-in / Check-out)**: nuovo sistema per tracciare assunzioni e dimissioni. Voci configurabili dall'admin (checkbox, testo libero, data, scelta da lista) via pulsante Â«+ Aggiungi voceÂ» in `/admin-portale/checklist/`. Voci globali (si applicano a tutti gli utenti). Esecuzione da `/admin-portale/checklist/utenti/`<id>`/` con form per check-in e check-out, storico espandibile per utente. Tab Â«ChecklistÂ» aggiunto alla scheda utente con sommario e link diretto. Vista globale `/admin-portale/checklist/` mostra stato check-in/out di tutti i dipendenti attivi.

- **[model] Migration core 0007**: aggiunge modelli `ChecklistVoce`, `ChecklistEsecuzione`, `ChecklistRisposta` al DB Django.

- **[perf] Fix N+1 in checklist_index**: il calcolo dello stato per N utenti ora usa 2 query bulk invece di 2N query individuali.

## 0.5.1-dev - 2026-03-01

- **[feature] Scheda anagrafica utente**: la scheda utente admin (`/admin-portale/utenti/`<id>`/`) aggiunge un 4Â° tab Â«AnagraficaÂ». Sezione in sola lettura con dati da `anagrafica_dipendenti` (nome completo, reparto, email aziendale, username AD, stato dipendente). Sezione editabile con nuovo modello `UserExtraInfo`: caporeparto, macchina di utilizzo (placeholder futura gestione asset), telefono, cellulare, note. Salvataggio AJAX via `POST /admin-portale/api/utenti/`<id>`/extra-info`. Dati visibili anche nel profilo personale (`/profilo/`) nella nuova card Â«Reparto & ContattiÂ» (solo sezioni compilate).

- **[model] Migration core 0006**: aggiunge modello `UserExtraInfo` al DB Django.

## 0.5.0-dev - 2026-03-01

- **[security] Fix CSRF anomalie (H1)**: rimosso `@csrf_exempt` da `api_salva_placeholder` e `api_sync_placeholder` in `anomalie/views.py`. Il template React ora legge il cookie `csrftoken` e invia l'header `X-CSRFToken` su tutti i POST. Eliminato import `csrf_exempt` non piÃ¹ utilizzato.

- **[feature] Profilo utente** (`/profilo/`): nuova pagina personale accessibile a tutti gli utenti autenticati. Mostra nome, email, username, ruolo, stato account legacy. Link diretto a Â«Cambia passwordÂ». L'avatar nella topnav Ã¨ ora un link cliccabile che porta al profilo.

- **[feature] Rubrica aziendale** (`/rubrica/`): pagina di consultazione dipendenti attivi dalla tabella `anagrafica_dipendenti`. Filtro per nome/cognome/email e per reparto. Tabella card-style con avatar iniziali, email cliccabile `mailto:`, username.

- **[feature] Centro notifiche**: nuovo modello `Notifica` (Django-managed). Triggered in `api_car_aggiorna_consenso` dopo approvazione/rifiuto assenza per notificare il richiedente (lookup per `email_esterna`). Badge campanella ðŸ”” nella topnav (con contatore rosso se non lette). Pagina `/notifiche/` con lista cronologica; le notifiche vengono marcate come lette all'apertura della pagina.

- **[feature] Audit log**: nuovo modello `AuditLog` (Django-managed). Helper `core/audit.py` â†’ `log_action()` fire-and-forget. Agganciato a: `api_car_aggiorna_consenso` (assenza_moderata), `api_user_perm_override` (override_permesso), `cambia_password` (cambio_password). Vista admin `/admin-portale/audit/` con filtri per modulo, azione e data; paginazione 50 per pagina.

- **[feature] Dashboard contestuale per ruolo**: il widget di benvenuto ora cambia contenuto in base al ruolo. CAR/Capo Reparto: lista delle prime 5 richieste in attesa del reparto con link diretto alla car_dashboard. AMMIN/Admin: prime 5 richieste in attesa globali. Operaio: stato della propria ultima richiesta con badge colorato.

- **[feature] Health check admin** (`/admin-portale/health/`): pagina diagnostica per admin con 6 check: DB Django, DB Legacy (tabella utenti), Azure MSAL config, file di log, sessioni attive, modello Notifica. Indicatori OK/Errore con dettaglio testuale; pulsante Â«AggiornaÂ».

- **[feature] Export CSV**: pulsante Â«Esporta CSVÂ» nella car_dashboard (esporta assenze reparto, incluso storico gestite) e in gestione_assenze (esporta richieste personali). Endpoint `/anomalie/export-csv` per anomalie. Usa `StreamingHttpResponse` + `csv` stdlib (nessuna dipendenza esterna). Encoding `utf-8-sig` per compatibilitÃ  Excel.

- **[model] Migration core 0005**: aggiunge modelli `Notifica` e `AuditLog` al DB Django (SQLite/SQL Server).

## 0.4.9-dev - 2026-03-01

- **[feature] Note al rifiuto (CAR)**: quando un CAR rifiuta una richiesta, puÃ² ora inserire un motivo opzionale nella textarea inline che compare sotto la riga al click di Â«RifiutaÂ». La nota viene salvata nel campo `note_gestione` della tabella `assenze` e visualizzata nella sezione Â«Ultime gestiteÂ» (colonna Â«Note rifiutoÂ»). L'utente richiedente vede la nota direttamente sotto lo stato Â«RifiutatoÂ» nella propria pagina Gestione. Aggiunto management command `aggiungi_note_gestione` per aggiungere la colonna al DB (SQLite e SQL Server).

- **[feature] Badge "in attesa" (topbar e subnav)**: il numero di richieste in attesa del proprio reparto appare accanto al link Â«SegnalazioniÂ» nel subnav assenze e come indicatore rosso nella topbar (angolo in alto a destra), visibile a tutti i CAR con richieste pendenti. Calcolato tramite context processor `legacy_nav` con query COUNT leggera per ogni richiesta autenticata.

- **[feature] Modifica richiesta Â«In attesaÂ»**: un utente puÃ² ora modificare (tipo, date, motivazione) le proprie richieste finchÃ© sono in stato Â«In attesaÂ». Pulsante Â«ModificaÂ» nella tabella personale (visibile solo per le righe In attesa); apertura modal con form, AJAX POST al nuovo endpoint `POST /assenze/api/mia/`<id>`/update` (`api_mia_assenza_update`). La modifica non altera il consenso e sincronizza con SharePoint. Aggiunto `tipo_raw`, `inizio_iso`, `fine_iso`, `note_gestione` all'output di `_load_personal`.

## 0.4.6-dev - 2026-03-01

- **[ux] Gestione assenze â€” elimina richiesta**: il pulsante Â«DuplicaÂ» nella tabella Â«Le tue richiesteÂ» Ã¨ stato sostituito con Â«EliminaÂ». La rimozione avviene via AJAX (nessun reload), con confirm dialog e fade-out della riga. L'API `api_evento_delete` ora permette a qualsiasi utente autenticato (`can_insert`) di eliminare le proprie richieste verificando la corrispondenza di `copia_nome`/`email_esterna`; l'amministratore puÃ² eliminare qualsiasi record. L'eliminazione propaga anche su SharePoint se configurato.

## 0.4.5-dev - 2026-03-01

- **[feature] Dashboard Segnalazioni CAR**: nuova pagina `/assenze/car/dashboard` accessibile da CAR e AMMINISTRAZIONE. I CAR vedono solo le assenze del proprio reparto; gli admin vedono tutte le richieste. Quattro sezioni: Â«Richieste in attesaÂ» (con pulsanti Approva/Rifiuta in-page), Â«Assenze oggiÂ», Â«Questa settimanaÂ», Â«Ultime gestiteÂ». L'approvazione/rifiuto avviene via AJAX e sincronizza automaticamente con SharePoint.

- **[feature] API consenso CAR**: nuovo endpoint `POST /assenze/api/car/consenso/<item_id>` (`api_car_aggiorna_consenso`) per approvare/rifiutare assenze. Accessibile da CAR (solo record del proprio reparto) e da AMMINISTRAZIONE (qualsiasi record). Aggiorna `consenso`, `moderation_status` e sincronizza su SharePoint.

- **[refactor] Helper assenze**: aggiunti `_load_gestite_for_manager`, `_load_assenze_car_periodo`, `_load_all_pending`, `_load_all_gestite`, `_load_all_assenze_periodo` per supportare le diverse viste per ruolo.

- **[ux] Subnav assenze**: aggiunto link Â«SegnalazioniÂ» visibile a CAR e AMMINISTRAZIONE (`assenze_can_edit_events`). Menu assenze aggiornato con card accesso rapido differenziata per ruolo.

## 0.4.4-dev - 2026-03-01

- **[ux] Navigation Builder â€” selezione ad elenco**: i campi Â«Route nameÂ» (form creazione, tabella inline, redirect) ora supportano selezione dall'elenco delle route Django disponibili tramite `<datalist>` (si puÃ² ancora digitare liberamente). Il campo Â«SezioneÂ» Ã¨ diventato un `<select>` con opzioni fisse (topbar/sidebar/page). Il campo Â«Ruoli abilitatiÂ» Ã¨ ora un `<select multiple>` con tutti i ruoli legacy nominati (Ctrl+click per piÃ¹ ruoli); la serializzazione CSV Ã¨ gestita in JS e compatibile con le API esistenti. Pre-selezione ruoli in tabella gestita via `data-role-ids` e inizializzazione JS.

- **[ux] Navigation Builder â€” descrizioni e semplificazione**: ogni campo e sezione ha testo esplicativo inline (`field-help`). La sezione Â«Ruoli LegacyÂ» Ã¨ collassabile (`<details>`). L'import da legacy Ã¨ stato separato in una card dedicata con pulsante Â«MergeÂ» (sicuro) e Â«Sovrascrivi tuttoÂ» (distruttivo, con confirm). Aggiunto confirm dialog su Elimina voce, Elimina redirect e Ripristina snapshot. Aggiunta colonna Â«TabÂ» nella tabella voci (open_in_new_tab precedentemente assente).

## 0.4.3-dev - 2026-03-01

- **[feature] Permessi: expand pulsante per pulsante**: cliccando su una riga modulo si espande il sottoelenco con tutti i pulsanti, ognuno con il proprio toggle. Funziona sia in modalitÃ  Ruolo che Utente. Lo stato "parziale" del modulo si aggiorna automaticamente dopo ogni modifica singola.

- **[refactor] Permessi helpers**: aggiunto `_aggregate_to_module_rows`, `_full_perm_rows_for_user`, `_build_perm_detail`; eliminata doppia query nel view `permessi`.

## 0.4.2-dev - 2026-03-01

- **[feature] Permessi per modulo**: `/admin-portale/permessi/` completamente ridisegnata. Sostituita la matrice granulare (modulo + azione) con vista semplificata a toggle per modulo: ogni riga rappresenta un modulo con un solo interruttore che abilita/disabilita l'accesso per tutti i pulsanti del modulo in un click. Lo stato "parziale" Ã¨ evidenziato in giallo.

- **[feature] Permessi per ruolo o per utente**: la pagina supporta due modalitÃ  con tab "Per Ruolo" / "Per Utente". In modalitÃ  Ruolo modifica la tabella `permessi` (impatta tutto il ruolo). In modalitÃ  Utente scrive `UserPermissionOverride` come override personale indipendente dal ruolo.

- **[feature] API modulo-level**: `POST /admin-portale/api/permessi/modulo-set` e `POST /admin-portale/api/utenti/`<id>`/modulo-perm-set` per bulk can_view di tutti i pulsanti di un modulo.

- **[refactor] Permessi bulk conservati**: "Tutto ON", "Tutto OFF", "Reset ruolo", "Copia da ruolo" rimangono in modalitÃ  Ruolo e riusano le API bulk esistenti.

## 0.4.1-dev - 2026-03-01

- **[fix] Dashboard reset al riavvio**: il tasto Ã— nella modalitÃ  Modifica ora salva la preferenza in `UserDashboardConfig` (modello Django, persistente con migrazioni) invece di `ui_pulsanti_meta` (raw SQL, persa se il DB viene ricreato). Il pannello "Moduli nascosti" mostra i moduli nascosti per l'utente corrente letti dalla stessa tabella.

- **[feature] Edit mode dashboard per tutti gli utenti**: il pulsante "Modifica" Ã¨ ora visibile a tutti gli utenti (non solo admin). Ogni utente puÃ² decidere autonomamente quali moduli vedere nella propria dashboard. Il tasto Ã— nasconde il modulo solo per se stessi; "Mostra" lo riabilita. La configurazione Ã¨ per-utente e persiste tra i riavvii.

- **[feature] API per-utente dashboard**: nuova API `POST /api/my-dashboard-toggle` (`api_my_dashboard_toggle`) accessibile da tutti gli utenti autenticati; gestisce hide/show personale tramite `UserDashboardConfig`. Il tasto "+ Nuovo" (wizard pulsante) rimane visibile solo agli admin.

## 0.4.0-dev - 2026-03-01

- **[feature] Navigation Registry v2 (strutturale)**: introdotti modelli Django-managed `NavigationItem`, `NavigationRoleAccess`, `NavigationSnapshot`, `LegacyRedirect` per centralizzare menu, regole ruolo, versionamento configurazione e redirect legacy configurabili.

- **[feature] Navigation Builder (no-code)**: nuova pagina admin `/admin-portale/navigation-builder/` con gestione voci menu (CRUD), mapping ruoli (CSV), publish snapshot e rollback snapshot, oltre alla gestione redirect legacy senza modifiche a codice.

- **[feature] Cache versionata navigazione**: nuovo modulo `core/navigation_registry.py` con cache per ruolo/sezione e invalidazione controllata (`bump_navigation_registry_version`) per ridurre query ripetute su topbar e migliorare stabilita' runtime.

- **[feature] Topbar con fallback robusto**: `core/context_processors.py` ora tenta prima la sorgente Navigation Registry v2 (se abilitata) e ricade automaticamente sulla logica legacy `pulsanti/ui_pulsanti_meta` in assenza dati o in caso errore.

- **[feature] Redirect legacy DB-driven**: `core/legacy_flask_views.py` supporta redirect da tabella `LegacyRedirect` prima della mappa hardcoded, migliorando gestibilita' operativa durante la transizione.

- **[feature] UI admin allineata**: aggiunti collegamenti `Navigation Builder` nella home admin e nella subnav per accesso centralizzato.

- **[infra] Flag configurazione**: aggiunto `NAVIGATION_REGISTRY_ENABLED` in settings per attivare/disattivare la nuova sorgente menu senza deploy di codice.

- **[db] Migrazione core**: aggiunta `core.0003_legacyredirect_navigationitem_navigationsnapshot_and_more`.

- **[docs] Guida moduli programma**: creato `GUIDA_MODULI_PROGRAMMA.html` (stile visual) per spiegare in modo chiaro cosa fanno i moduli e dare una visione sintetica dell'architettura/funzionamento del portale.

## 0.3.29-dev - 2026-03-01

- **[fix] Dashboard admin**: il tasto "Modifica" ora appare anche per i superuser Django senza profilo legacy (`request.user.is_superuser` usato come fallback in `is_admin`).

- **[feature] Scheda utente unificata**: la pagina `/admin-portale/utenti/`<id>`/` Ã¨ stata ridisegnata con tre tab â€” **Info** (dati base, invariati), **Permessi** (matrice permessi del ruolo + override personali per ogni flag), **Dashboard** (pulsanti accessibili con toggle visibilitÃ  per-utente). Le modifiche si salvano via AJAX senza ricaricare la pagina.

- **[feature] Override permessi per-utente**: nuovo modello `UserPermissionOverride` (Django-managed) che permette di sovrascrivere singoli flag (`can_view`, `can_edit`, `can_delete`, `can_approve`) per uno specifico utente, indipendentemente dal ruolo. La logica ACL in `core/acl.py` controlla prima l'override, poi il ruolo. Nuova API `POST /admin-portale/api/utenti/`<id>`/perm-override`.

- **[feature] Dashboard per-utente**: nuovo modello `UserDashboardConfig` (Django-managed) che permette di nascondere specifici pulsanti dalla dashboard di un singolo utente. `_module_cards()` ora filtra per configurazione utente. Nuova API `POST /admin-portale/api/utenti/`<id>`/dashboard-toggle`. La diagnostica ACL (`core/acl.py`) mostra anche l'override attivo nell'output di debug.

## 0.3.28-dev - 2026-03-01

- **[feature] Edit mode dashboard**: gli amministratori vedono un pulsante "Modifica" nella card "Moduli disponibili" della dashboard. In edit mode: ogni modulo mostra un Ã— per nasconderlo (imposta `enabled=false` in `ui_pulsanti_meta`), un pannello "Moduli nascosti" permette di riabilitarli, il tasto "+ Nuovo" collega al wizard. Aggiunta API `POST /admin-portale/api/pulsanti/set-enabled` che aggiorna solo il flag `enabled`. Il flag filtra i moduli mostrati a tutti gli utenti senza riavvio (cache invalidata).

## 0.3.27-dev - 2026-03-01

- **[feature] Wizard nuovo pulsante**: aggiunto flusso guidato 4 step (`/admin-portale/wizard-pulsante/`) per creare un pulsante, configurarne la posizione UI (slot/sezione/ordine/topbar/attivo) e assegnare i permessi per ogni ruolo con preset rapidi (Nessuno / Sola lettura / Lettura+Scrittura / Completo) ed espansione ai singoli flag. Il salvataggio Ã¨ atomico e invalida subito la cache ACL legacy affinchÃ© il pulsante appaia nel menu senza riavvio. Link di accesso rapido aggiunto nella pagina "Pulsanti" dell'admin portale.

## 0.3.26-dev - 2026-03-01

- **[C1] Fix dead code anomalie**: corretta funzione `_resolve_op_lookup_id` in `anomalie/views.py` â€” il lookup per titolo OP era irraggiungibile (codice dopo `return fields`); logica spostata nel posto corretto.

- **[H2] Datetime timezone-aware**: eliminato uso di `datetime.utcnow()` (deprecated, naive) in `anomalie/views.py`; standardizzato a `datetime.now(timezone.utc)` con guard `isinstance(exp, datetime)` sulla cache token. Fix anche a `datetime.now()` naive in `assenze/views.py`.

- **[H4] Shared Graph token cache**: creato `core/graph_utils.py` con `acquire_graph_token()` thread-safe condiviso; eliminata duplicazione della logica MSAL e della cache token tra `assenze/views.py` e `anomalie/views.py`. Rimosso anche `_is_placeholder_value()` duplicato.

- **[C3] TrustServerCertificate configurabile**: il flag SQL Server non Ã¨ piÃ¹ hardcoded a `yes`; ora controllato da variabile env `DB_TRUST_CERT` (default `0`/no). Dev locale imposta `DB_TRUST_CERT=1` nel `.env`.

- **[M2] Log rotation**: sostituito `logging.FileHandler` con `logging.handlers.RotatingFileHandler` (5 MB max, 5 backup) per evitare crescita illimitata di `app.log`.

- **[L1] HTTPS prod**: aggiunti in `config/settings/prod.py`: `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS` (1 anno), `SECURE_HSTS_INCLUDE_SUBDOMAINS`, `SECURE_HSTS_PRELOAD`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`.

## 0.3.25-dev - 2026-02-27

- LDAP diagnostica fix: corretto `_ldap_test_connect` (`/admin-portale/ldap/`) per gestire il comportamento `ldap3` dove `Connection.open()` puo' restituire `None` anche con socket aperto.

- UX diagnostica LDAP: eliminato falso negativo "Connessione LDAP fallita: None"; ora la connessione viene considerata riuscita quando `conn.closed` e' `False`, con fallback errore piu' leggibile.

## 0.3.24-dev - 2026-02-27

- Stabilita' esecuzione Django: aggiunto `manage.py` in root progetto come entrypoint unico, cosi' da lanciare i comandi Django sempre da root (`python manage.py ...`) senza dipendere dalla cartella attiva.

- VS Code hardening: debug config root aggiornata per usare il nuovo `manage.py` root e task dedicati (`runserver`, `check`) con interpreter esplicito della venv.

- Workspace multiplo: allineate anche le configurazioni `.vscode` dentro `django_app/` per apertura sia della root che della sola cartella app, evitando mismatch path interpreter.

## 0.3.23-dev - 2026-02-27

- VS Code interpreter resolution fix: rimosso uso di `${workspaceFolder}` per Python path nelle configurazioni di debug/settings, sostituito con percorsi relativi stabili (`.\\.venv\\Scripts\\python.exe`).

- Workspace support: aggiunti file `.vscode` anche dentro `django_app/` per coprire sia apertura workspace root sia apertura diretta della sola cartella `django_app`.

- Terminal policy workaround: impostato `python.terminal.activateEnvironment=false` per evitare errori PowerShell su `Activate.ps1` con execution policy restrittiva.

## 0.3.22-dev - 2026-02-27

- VS Code debug fix: aggiunto `.vscode/launch.json` con configurazioni esplicite Django (`runserver` e `shell`) puntate a `django_app/manage.py`, evitando l'esecuzione accidentale di file non Python (es. il vecchio file di configurazione legacy).

- VS Code Python interpreter: impostato `python.defaultInterpreterPath` su `.venv\\Scripts\\python.exe` in `.vscode/settings.json` per allineare debug/terminal all'ambiente virtuale corretto.

## 0.3.21-dev - 2026-02-27

- LDAP Admin UI: aggiunto pulsante/azione "Sync utenti LDAP" nella pagina diagnostica LDAP (`/admin-portale/ldap/`) con esecuzione diretta del comando `sync_ldap_users`.

- Sync LDAP da web: supporto opzioni da form (`dry-run`, `limit`, override allowlist, replace memberships) e output risultato mostrato nella stessa pagina.

- Diagnostica LDAP estesa: visualizzati anche i parametri di sync (`service_user`, `base_dn`, `user_filter`, `group_allowlist`, `sync_page_size`) per ridurre ambiguita' operative.

## 0.3.20-dev - 2026-02-27

- Layout globale rifinito: contenitore principale `.content` centrato orizzontalmente con larghezza massima (`min(100%, 1600px)`), evitando il blocco UI allineato solo a sinistra su monitor larghi.

## 0.3.19-dev - 2026-02-27

- Layout globale: area contenuti principale resa full-width su tutte le pagine (`.content`), eliminando il vincolo `max-width: 1400px` per evitare sezioni "compresse".

## 0.3.18-dev - 2026-02-27

- LDAP import utenti/gruppi: nuovo comando `python manage.py sync_ldap_users` per importare utenti da AD con supporto membership multipla ai gruppi Django.

- Sync LDAP -> SQL/Django: ogni utente LDAP viene creato/aggiornato in tabella legacy `utenti` come `*AD_MANAGED*`, poi allineato su `auth_user` + `Profile` tramite `sync_django_user_from_legacy`.

- Config LDAP estesa: aggiunte impostazioni `LDAP_SERVICE_USER`, `LDAP_SERVICE_PASSWORD`, `LDAP_BASE_DN`, `LDAP_USER_FILTER`, `LDAP_GROUP_ALLOWLIST`, `LDAP_SYNC_PAGE_SIZE` (da `.env` o dal file di configurazione legacy).

- Gruppi: supporto import selettivo via allowlist e opzione autoritativa `--replace-allowlist-memberships` per allineare i gruppi portale da AD.

## 0.3.17-dev - 2026-02-27

- Assenze permessi per gruppi: `UTENTI` solo inserimento (no calendario), `CAR` inserimento + calendario + modifica solo record con `caporeparto` associato al capo corrente, `AMMINISTRAZIONE` pieno controllo (view/edit/delete/sync).

- Calendario/API hardening: controlli `403` su view/API colori/eventi/sync e blocco update/delete non autorizzati lato backend (non solo UI).

- Richiesta assenza: nuovo flag `salta_approvazione` visibile solo a `CAR/AMMINISTRAZIONE`, salvato su SQL e propagato su SharePoint.

- Vincoli PowerApps portati su Django: validazione data/ora server-side e regole FlessibilitÃ  (min 9h, max 10h, max 2 richieste settimanali per persona) con warning dedicato sul caso 10h.

- UI allineata: subnav nasconde il link `Calendario` ai gruppi senza diritto e popup calendario in modalitÃ  sola lettura quando non ci sono permessi di modifica/eliminazione.

## 0.3.16-dev - 2026-02-26

- Gestione Pulsanti UX: preset rapidi UI estesi anche alla tabella `Pulsanti esistenti` (preset per riga con pulsante `Preset`, applicazione locale dei campi e salvataggio manuale successivo).

- Gestione Pulsanti JS: logica preset riutilizzata sia nel form di creazione sia nelle righe esistenti tramite helper comune (`applyPresetValuesToContainer`).

- Miglioria usabilita': guida inline aggiornata per chiarire che il preset riga non salva automaticamente (serve clic `Salva`).

## 0.3.15-dev - 2026-02-26

- Gestione Pulsanti UX: aggiunti preset rapidi UI nel form di creazione (compilazione automatica di `Slot`, `Sezione`, `Topbar`, `Attivo`) con descrizione e pulsante "Applica preset".

- Gestione Pulsanti backend: preset UI forniti da `admin_portale.views.pulsanti` (DB-driven UI piu' guidata, meno inserimento manuale ripetitivo).

- Uniformazione schermate Admin: nuovo componente `card_head.html` e applicazione progressiva ai card header statici (Pulsanti/ACL/LDAP/Schema Dati) per layout piu' coerente.

## 0.3.14-dev - 2026-02-26

- Uniformazione schermate Admin Portale: introdotti componenti template condivisi `page_header.html` e `flash_messages.html` per standardizzare header pagina e messaggi.

- Refactor template admin: applicati i componenti comuni alle schermate principali (`Home`, `Utenti`, `Permessi`, `Pulsanti`, `ACL`, `LDAP`, `Schema Dati`) e messaggi unificati anche su `utente_edit` / `permessi effettivi`.

- Obiettivo UX/manutenzione: ridurre differenze visive tra schermate e semplificare modifiche future a layout/testi comuni.

## 0.3.13-dev - 2026-02-26

- Admin Portale: nuova pagina `Schema Dati Admin` (`/admin-portale/schema-dati/`) con mappa semplice delle tabelle principali (legacy + Django), responsabilita', gestione dal portale e conteggi live.

- UI Admin: aggiunti collegamenti route-safe a `Schema Dati` in subnav e home admin per ridurre confusione su dove sono salvati ruoli/permessi/pulsanti.

- Obiettivo UX: chiarire la separazione tra dati nel DB SQL Server legacy (`utenti`, `ruoli`, `permessi`, `pulsanti`) e tabelle di supporto Django (`auth_user`, `core_profile`, `ui_pulsanti_meta`).

## 0.3.12-dev - 2026-02-26

- Gestione Pulsanti UX: aggiunti menu a tendina con suggerimenti (`datalist`) per `Modulo`, `Slot UI`, `Sezione UI` e `Icona` sia in creazione sia nella tabella dei pulsanti esistenti (restano ammessi valori personalizzati).

- Gestione Pulsanti: aggiunte guide rapide inline per spiegare `Slot`, `Sezione` e `Ord UI` e migliorare la compilazione dei metadati UI.

- Admin Portale: aggiunta descrizione contestuale ("cosa fa / come usarla") nella subnav per le principali pagine admin (`Home`, `Utenti`, `Permessi`, `Pulsanti`, `ACL`, `LDAP`).

## 0.3.11-dev - 2026-02-26

- Admin Portale: nuova pagina `Diagnostica ACL` (`/admin-portale/acl/`) per analizzare i `403` mostrando utente legacy, ruolo, path normalizzato, pulsante matchato e record in tabella `permessi`.

- Diagnostica ACL: supporto test su utente corrente o su un `legacy_user_id` specifico (utile per verificare un utente LDAP appena creato/assegnato a un ruolo).

- UI Admin: aggiunti link route-safe a `Diagnostica ACL` in subnav e home admin.

## 0.3.10-dev - 2026-02-26

- ACL middleware/permessi: supporto ai `pulsanti.url` configurati come `route:nome_route` / `django:nome_route` anche nel matcher ACL (reverse della route prima del controllo permesso).

- Fix autorizzazioni DB-driven: evitati `403` falsi positivi quando i link menu sono gestiti dal portale con route Django invece di path statici.

## 0.3.9-dev - 2026-02-26

- Fix login LDAP auto-provision: `LDAPBackend` non passa piu' il campo `ruoli` se il modello/tabella legacy `utenti` non lo supporta (compatibilita' con schemi legacy diversi).

- Backend LDAP: create utente legacy resa piu' robusta filtrando i campi in base ai campi effettivi del modello `UtenteLegacy`.

## 0.3.8-dev - 2026-02-26

- Fix Admin Portale home (`/admin-portale/`): card `Diagnostica LDAP` resa route-safe con `{% url ... as ... %}` per evitare `NoReverseMatch` durante reload parziali del dev server.

- Coerenza template admin: comportamento allineato alla subnav (`admin_subnav.html`) gia' protetta con reverse opzionale.

## 0.3.7-dev - 2026-02-26

- Fix subnav Admin: link `LDAP` reso route-safe (`{% url ... as ... %}`) per evitare `NoReverseMatch` in caso di reload parziale / route non ancora registrata nel processo Django.

- Nota operativa: verificata la route `admin_portale:ldap_diagnostica` (`/admin-portale/ldap/`) correttamente registrata a runtime.

## 0.3.6-dev - 2026-02-26

- Admin Portale: nuova pagina `Diagnostica LDAP` (`/admin-portale/ldap/`) con test connessione LDAP e test bind utente (UPN + fallback NTLM `DOMINIO\\utente`).

- Admin Portale: aggiunti link a `Diagnostica LDAP` in subnav e home admin.

- Gestione Pulsanti (DB-driven UI): create/update salvano metadati UI persistenti in `ui_pulsanti_meta` (`ui_slot`, `ui_section`, `ui_order`, `visible_topbar`, `enabled`).

- Gestione Pulsanti: UI estesa con campi Slot/Sezione/Ord UI/Topbar/Attivo per gestire i pulsanti per posizione e contesto dal portale.

- Topbar dinamica: utilizza i metadati `ui_pulsanti_meta` quando presenti (filtri slot/topbar/attivo e ordine UI), con fallback ai campi legacy.

## 0.3.5-dev - 2026-02-26

- Gestione Pulsanti (DB-driven avanzato): introdotti metadati UI persistenti in tabella `ui_pulsanti_meta` (slot, sezione, ordine UI, visibile in topbar, attivo) gestiti dal portale.

- Gestione Pulsanti: create/update salvano anche i metadati UI; lista pulsanti mostra e modifica `Slot`, `Sezione`, `Ord UI`, `Topbar`, `Attivo`.

- Topbar dinamica: ora usa i metadati UI (`enabled`, `visible_topbar`, `ui_slot=topbar/toolbar`, `ui_order`) se presenti, con fallback ai campi legacy.

- LDAP/AD (Django): parametri LDAP letti con priorita' dal file di configurazione legacy (`[ACTIVE_DIRECTORY]`) invece di essere bloccati dai default in `.env`.

- LDAP/AD backend: aggiunto fallback `NTLM` per bind `DOMINIO\\utente` (oltre al bind UPN), migliorando compatibilita' con Active Directory Windows.

## 0.3.4-dev - 2026-02-26

- Admin Portale / Gestione Pulsanti: aggiunto filtro `Area UI` (posizione/funzione) per gestire meglio i pulsanti per contesto (`toolbar`, assenze, calendario assenze, anomalie, admin, utenti, permessi, richieste, altro).

- Gestione Pulsanti: nuova colonna `Area UI` (derivata automaticamente da codice/modulo/url/route) per rendere piu' chiara la collocazione dei pulsanti.

- Migliorata usabilita' gestione pulsanti: approccio orientato alla posizione UI, non solo per modulo tecnico.

## 0.3.3-dev - 2026-02-26

- Admin Portale / Gestione Pulsanti: aggiunto catalogo delle route Django disponibili (nome route + path + valore pronto `route:...`).

- Gestione Pulsanti: filtro client-side e pulsante copia per compilare velocemente il campo URL dei pulsanti topbar/menu.

- Backend admin_portale: catalogo route generato dal resolver Django (ricorsivo, include namespace come `admin_portale:*`).

## 0.3.2-dev - 2026-02-26

- Topbar DB-driven: il campo `pulsanti.url` supporta ora `route:nome_route_django` (o `django:nome_route`) per puntare alle route Django senza modificare il codice.

- Topbar/nav: supporto anche a URL esterni `http(s)://...` dal DB; il mapping Python rimane come fallback per i pulsanti legacy non configurati.

- Admin Portale / Gestione Pulsanti: validazione `url` aggiornata per accettare `route:`, `django:` e URL esterni senza forzare `/`.

- Admin Portale / Gestione Pulsanti: aggiunto hint UI su come configurare i link topbar dal portale (`route:gestione_anomalie_page`, ecc.).

## 0.3.1-dev - 2026-02-26

- Anomalie sync (DB-first): `POST /api/anomalie/sync` ora esegue push SQL Server -> SharePoint (create dei record locali non sincronizzati, update opzionale con `include_updates`).

- Anomalie frontend React legacy in Django: compatibilita' migliorata sulle API `/api/anomalie/ordini` e `/api/anomalie/anomalie` con fallback su DB locale.

- API anomalie: `GET /api/anomalie/db/anomalie` restituisce anche `local_id` e `item_id` sintetico `local:<id>` per record non ancora sincronizzati.

- Sicurezza/compatibilita': endpoint POST anomalie (`salva`, `sync`) mantenuti `csrf_exempt` per supportare il frontend JS legacy durante la migrazione.

## 0.3.0-dev - 2026-02-26

- Migrazione Django step frontend+API: nuova app `dashboard` con route `/dashboard`, `/richieste`, `/anomalie-menu` e redirect root `/`.

- Migrazione Django step assenze: nuova app `assenze` con pagine GET (`/assenze/*`) e API locale `/assenze/api/eventi` su SQL Server.

- Migrazione Django step anomalie: nuova app `anomalie` con pagina `/gestione-anomalie` (frontend React legacy portato in Django).

- API anomalie DB-first: `GET /api/anomalie/db/ordini`, `GET /api/anomalie/db/anomalie` e fallback compatibile su `/api/anomalie/ordini` e `/api/anomalie/anomalie`.

- API anomalie DB-first: `POST /api/anomalie/salva` salva/aggiorna su tabella SQL Server `anomalie` con `item_id` locale (`local:<id>`) se non sincronizzato su SharePoint.

- ACL/menu legacy aggiornati per puntare alle nuove route Django (`assenze`, `anomalie-menu`).

- Note: sync SharePoint e POST avanzati (`assenze`, `anomalie/sync`) restano placeholder per i prossimi step.

## 0.2.0-dev â€” 2026-02-25

- Admin portale: dashboard, gestione utenti (CRUD + bulk), gestione permessi (toggle + bulk + copy), gestione pulsanti (CRUD).

- Menu dinamico aggiornato per puntare alle nuove route admin-portale.

- Harden CSRF su API admin.
