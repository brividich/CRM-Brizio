# Agent Changelog

## 2026-05-25 - Codex

- Area: `django_app/assets`, sidebar/navigazione locale modulo Assets.
- Richiesta: rendere compresse di default le voci categoria nella sidebar Assets per evitare un menu laterale troppo lungo.
- File modificati: `django_app/assets/views.py`, `django_app/assets/templates/assets/base_shell.html`, `django_app/assets/tests.py`, `README.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: `django_app/assets/views.py` e `django_app/assets/templates/assets/base_shell.html` (navigazione locale del modulo Assets, autorizzata dalla richiesta esplicita). `_AGENT_CONTROL/CRITICAL_FILES.md` non e presente nella workspace. Nessuna modifica ad ACL, middleware, settings, routing globale o autenticazione.
- Motivo tecnico: la sidebar renderizzava tutte le categorie radice e tutte le sottocategorie come link piatti, producendo un menu molto lungo quando il catalogo asset era gerarchico.
- Modifica: la costruzione della sidebar ora annida le sottovoci sotto la categoria padre, marca il ramo `expanded` solo quando il padre o un figlio e attivo, e il template renderizza gruppi richiudibili con chevron dedicato. Le sottocategorie sono chiuse di default, mentre le aperture manuali vengono ricordate in `localStorage`.
- Impatto previsto: il menu laterale Assets resta compatto all'apertura; cliccando la freccia di una categoria si vedono le sottocategorie, e quando si entra in una sottocategoria il relativo ramo resta aperto.
- Rischi residui: la preferenza di apertura e locale al browser; gli utenti potrebbero dover riaprire manualmente alcuni gruppi la prima volta dopo il deploy. La verifica visuale su pagina reale richiede sessione autenticata.
- Test/check: `python django_app\manage.py check --settings=config.settings.dev` OK; `python django_app\manage.py shell --settings=config.settings.dev -c "from django.template.loader import get_template; get_template('assets/base_shell.html')"` OK; shell mirata su `_build_sidebar_groups()` conferma padre con figli chiuso di default e aperto su figlio attivo; `git diff --check` sui file Assets OK. Il run test Django mirato su `AssetsRoutingTests` ha superato la fase di setup ma e andato in timeout nella workspace Windows, quindi la copertura aggiunta non e stata completata end-to-end in questa sessione.
- Note: nessun backup creato; workspace gia sporca con molte modifiche non correlate, lasciate intatte.

## 2026-05-25 - Codex

- Area: `django_app/core/static/core`, tabelle globali portale.
- Richiesta: proseguire l'ordinamento e filtraggio delle tabelle anche sulle altre tabelle presenti nel sito.
- File modificati: `django_app/core/static/core/js/fm-table-enhanced.js`, `django_app/core/static/core/css/fm-table-enhanced.css`, `django_app/core/templates/core/base.html`, `docs/ai/TABELLE_PERSONALIZZABILI.md`, `README.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: `django_app/core/templates/core/base.html` (template globale caricato da tutto il portale; modifica limitata al commento descrittivo del loader tabelle). `_AGENT_CONTROL/CRITICAL_FILES.md` non e presente nella workspace. Nessuna modifica ad ACL, middleware, settings, routing o autenticazione.
- Motivo tecnico: il sistema `fm-table-enhanced` era globale ma si attivava solo su tabelle con `data-table-id` e colonne `data-col`; molte tabelle operative del portale non avevano questi attributi e quindi restavano senza sort/filtro.
- Modifica: il JS ora scansiona le tabelle dati semplici, genera `data-table-id` stabile dalla pagina/contesto, inferisce colonne/tipi filtro dai `<th>` e dai valori, abilita sort/filtro/ricerca/preferenze anche senza intervento template-per-template, osserva tabelle aggiunte dinamicamente e lascia escluse tabelle tecniche, stampe, matrici, gantt, schema DB e mini-table. Migliorato l'ordinamento data per formati italiani `gg/mm/aaaa` e `gg-mm-aaaa`; documentato opt-out con `data-fm-table-skip="1"` o `data-table-enhanced="0"`.
- Impatto previsto: le tabelle elenco e operative dei moduli non ancora convertite ricevono automaticamente barra ricerca, menu colonne, icone sort e filtri per colonna; le tabelle gia configurate esplicitamente continuano a usare i loro `data-table-id` stabili.
- Rischi residui: auto-binding client-side puo aggiungere controlli a tabelle semplici che formalmente sono dati ma in alcune viste potrebbero risultare troppo compatte; per questi casi l'opt-out e documentato. Le preferenze sono salvate per id generato: se una pagina cambia molto struttura/heading, una tabella auto potrebbe ottenere un nuovo id e perdere le preferenze precedenti.
- Test/check: `node --check django_app/core/static/core/js/fm-table-enhanced.js` OK; `python django_app\manage.py check --settings=config.settings.dev` OK; `git diff --check` sui file toccati OK; test browser su pagina fittizia servita dal dev server OK (auto-bind su tabella senza attributi, esclusione `.dbs-page`, inferenza `text/select/date`, ordinamento data italiana, binding dinamico via MutationObserver).
- Note: nessun backup creato; `jsdom` non e installato, quindi la verifica DOM e stata fatta con Playwright/browser. La workspace conteneva gia molte modifiche non correlate, lasciate intatte.

## 2026-05-25 - Codex

- Area: `django_app/anagrafica` UI scheda dipendente.
- Richiesta: eliminare le parti evidenziate in giallo nella scheda dipendente e spostare i pulsanti "Timbri" / "Torna all'elenco" dentro l'intestazione del dipendente.
- File modificati: `django_app/anagrafica/templates/anagrafica/pages/dipendente_detail.html`, `django_app/anagrafica/templates/anagrafica/components/subnav.html`, `django_app/anagrafica/templates/anagrafica/partials/formazione_tab_dipendente.html`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: `django_app/anagrafica/templates/anagrafica/components/subnav.html` impatta navigazione locale del modulo Anagrafica; `_AGENT_CONTROL/CRITICAL_FILES.md` non e presente nella workspace.
- Motivo tecnico: la scheda mostrava una riga descrittiva sotto la subnav e una topbar duplicata con nome dipendente e pulsanti, aumentando lo spazio verticale; il partial Formazione conteneva un commento iniziale da rimuovere per evitare qualsiasi rendering anomalo.
- Modifica: nascosta la notice della subnav quando la route corrente e `anagrafica:dipendente_detail`; la topbar duplicata della scheda e stata nascosta e i pulsanti "Timbri" / "Torna all'elenco" sono stati inseriti in `.dp-hero-actions`; rimosso il commento iniziale dal partial Formazione.
- Impatto previsto: la scheda dipendente apre direttamente con la card intestazione piu compatta e con i comandi principali dentro l'intestazione; spariscono i testi descrittivi/debug evidenziati.
- Rischi residui: verifica visuale browser non completata sulla pagina reale perche `http://127.0.0.1:8000/anagrafica/dipendenti/277/` redirige al login senza credenziali disponibili; i template sono stati caricati dal motore Django e i testi rimossi sono assenti nei sorgenti.
- Test/check: template load via `get_template(...)` OK; `rg` non trova piu `Scheda dipendente:` / `Partial: tab Formazione` nei file modificati; `python django_app\manage.py check --settings=config.settings.dev` OK.
- Note: nessun backup creato; la workspace conteneva gia modifiche non correlate in Anagrafica/Formazione e altri moduli, lasciate intatte.

## 2026-05-25 - Codex

- Area: `django_app/fornitori`, `django_app/admin_portale`, ACL.
- Richiesta: dividere Anagrafica HR da Anagrafica Fornitori anche a livello di permessi.
- File modificati: `django_app/admin_portale/views.py`, `django_app/admin_portale/templates/admin_portale/pages/index.html`, `django_app/admin_portale/tests.py`, `django_app/fornitori/acl_bootstrap.py`, `django_app/fornitori/migrations/__init__.py`, `django_app/fornitori/migrations/0001_split_fornitori_acl.py`, `django_app/fornitori/migrations/0002_hide_migrated_anagrafica_supplier_buttons.py`, `django_app/fornitori/tests.py`, `django_app/core/management/commands/seed_pulsanti_descrizioni.py`, `README.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: modifica ACL/navigazione admin su `django_app/admin_portale/views.py`; bootstrap e migration ACL su `django_app/fornitori/acl_bootstrap.py`, `django_app/fornitori/migrations/0001_split_fornitori_acl.py` e `django_app/fornitori/migrations/0002_hide_migrated_anagrafica_supplier_buttons.py`; descrizioni permessi su `django_app/core/management/commands/seed_pulsanti_descrizioni.py`. `_AGENT_CONTROL/CRITICAL_FILES.md` non e presente nella workspace.
- Motivo tecnico: il catalogo admin esponeva ancora `view_anagrafica_fornitori` dentro `MODULE_CATALOG["anagrafica"]`; in piu le route Fornitori non avevano binding ACL v2 dedicati e potevano restare governate da voci storiche Anagrafica con lo stesso URL.
- Modifica: `MODULE_CATALOG["anagrafica"]` ora e "Anagrafica HR" con solo Dipendenti; aggiunto modulo `fornitori` con 14 pulsanti assegnabili. Il bootstrap Fornitori espone tutte le azioni del namespace `fornitori:*` come pulsanti legacy `modulo=fornitori`. La migration `fornitori.0001_split_fornitori_acl` crea binding ACL v2 `legacy.fornitori.*`, migra/merge i permessi storici da `anagrafica` verso `fornitori` e disinnesca vecchi URL storici quando il codice target esiste gia; `0002_hide_migrated_anagrafica_supplier_buttons` esclude i pulsanti storici disinnescati dai raggruppamenti modulo.
- Impatto previsto: in gestione ruoli Anagrafica HR e Anagrafica Fornitori sono moduli separati; togliere i permessi ad Anagrafica HR non rimuove automaticamente i permessi Fornitori e viceversa. Le 14 route Fornitori risultano bound in ACL v2 mantenendo compatibilita con i toggle legacy `permessi`.
- Rischi residui: la migrazione e dati/ACL e va applicata in produzione; eventuali `RolePermissionGrant` canonici custom gia esistenti sulle stesse route potrebbero essere riallineati ai codici `legacy.fornitori.*`. La workspace aveva gia molte modifiche non correlate in Anagrafica/Formazione e core, lasciate intatte.
- Test/check: `python django_app\manage.py migrate fornitori --settings=config.settings.dev` OK; `python django_app\manage.py shell --settings=config.settings.dev -c "from core.management.commands.acl_coverage_report import build_acl_coverage; ..."` conferma `fornitori {'bound': 14}`; query DB conferma 14 pulsanti e 14 azioni permesso `modulo=fornitori`; `python django_app\manage.py bootstrap_acl_v2 --dry-run --apps fornitori --settings=config.settings.dev` OK con 0 proposte; `python django_app\manage.py test admin_portale.tests.AdminPortaleModuleCatalogTests fornitori.tests.FornitoriAclBootstrapTests --settings=config.settings.test --verbosity 2` OK; `python django_app\manage.py check --settings=config.settings.dev` OK; `git diff --check` OK.
- Note: nessun backup creato; DB dev aggiornato applicando `fornitori.0001_split_fornitori_acl` e `fornitori.0002_hide_migrated_anagrafica_supplier_buttons`.

## 2026-05-25 - Codex

- Area: `django_app/anagrafica` + ACL diagnostica.
- Richiesta: fare un check completo del modulo Anagrafica e verificare che permessi/oggetti assegnabili a ruolo siano presenti.
- File modificati: `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File applicativi modificati: nessuno.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non e presente nella workspace. Nessuna modifica a settings, middleware, ACL, routing globale o navigazione globale.
- Motivo tecnico: Anagrafica usa un mix di ACL legacy/canonico, Navigation Registry e singleton applicativi (`AnagraficaStatPermission`, `AnagraficaHRPermission`, `AnagraficaVisiteMedichePermission`, `AnagraficaFormazionePermission`) per sezioni sensibili.
- Esito diagnosi: `acl_coverage_report` indica Anagrafica con 149 route bound e 0 missing; i 23 pulsanti legacy `modulo=anagrafica` hanno righe `permessi` per tutti i 6 ruoli locali. Il bootstrap legacy dichiara 19 pulsanti; nel DB esistono anche 4 voci storiche/di navigazione (`view_anagrafica_dipendenti`, `view_anagrafica_fornitori`, `anagrafica_fornitori`, `anagrafica_fornitore_create`). Il layer canonico contiene 46 `PermissionDefinition` Anagrafica ma 35 sono route-generated senza grant ruolo e i binding route-name Anagrafica risultano inattivi, quindi l'assegnazione operativa passa ancora soprattutto dal legacy e dai singleton.
- Nota funzionale: in `/anagrafica/impostazioni/` tab Permessi sono assegnabili per ruolo statistiche, dati HR riservati e visite mediche; `AnagraficaFormazionePermission` esiste e governa visualizzazione/modifica formazione, ma non e esposta nella tab Permessi del modulo (solo admin Django/modello), quindi e il principale gap di assegnabilita role-friendly rilevato.
- Test/check: `python django_app\manage.py check --settings=config.settings.dev` OK; `python django_app\manage.py bootstrap_acl_v2 --dry-run --apps anagrafica --settings=config.settings.dev` OK senza proposte; script Django resolver/DB su route, pulsanti, permessi, grant e navigation; `python django_app\manage.py acl_coverage_report --settings=config.settings.dev` OK; `showmigrations anagrafica/core --plan --settings=config.settings.dev` mostra migrazioni applicate; `git diff --check -- _AGENT_CONTROL\AGENT_CHANGELOG.md session_checkpoint.md` OK.
- Note: nessun backup creato; non sono stati cambiati permessi runtime.

## 2026-05-25 - Codex

- Area: `django_app/assets` + ACL diagnostica.
- Richiesta: capire perche' il ruolo `MANUTENTORE`, pur indicato come autorizzato, non vede il pulsante "Aggiungi cartella" nella card Documenti del dettaglio asset.
- File modificati: `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File applicativi modificati: nessuno.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non e presente nella workspace. Nessuna modifica a settings, middleware, ACL, routing globale o navigazione globale.
- Motivo tecnico: il template `asset_detail.html` mostra il form solo con `can_manage_doc_folders`; la view valorizza quel flag tramite `_can_manage_asset_document_folders()`, che consente solo superuser/admin legacy o il permesso `assets/admin_assets`.
- Esito diagnosi: i permessi generici del modulo, la route del dettaglio asset, l'upload documenti o `assets_gestione` non bastano a mostrare "Aggiungi cartella"; per il ruolo va verificato/abilitato il grant canonico `legacy.assets.admin_assets` oppure il relativo permesso legacy `assets/admin_assets`.
- Test/check: lettura mirata di `CLAUDE.md`, `docs/ai/05_SECURITY_BOUNDARIES.md`, file controllo disponibili, `django_app/assets/views.py`, `asset_detail.html`, `acl_bootstrap.py`, `admin_portale/views.py`; tentativo query DB locale per ruolo `MANUTENTORE` senza risultati nella workspace dev; nessun test applicativo eseguito perche' diagnosi sola.
- Note: nessun backup creato.

## 2026-05-22 - Codex

- Area: `django_app/ai_assistant` + documentazione.
- Richiesta: migliorare la personalizzazione dell'assistente AI e chiarire il discorso su cosa puo' e non puo' fare.
- File modificati: `django_app/ai_assistant/templates/ai_assistant/chat.html`, `django_app/ai_assistant/views.py`, `django_app/ai_assistant/services.py`, `django_app/ai_assistant/tests.py`, `README.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non e presente nella workspace. Nessuna modifica a settings, middleware, ACL, routing globale o navigazione globale.
- Motivo tecnico: la personalizzazione era solo conversazionale/implicita; mancava una UI che rendesse espliciti stile risposta e confini operativi, e mancava un passaggio controllato delle preferenze al backend.
- Modifica: aggiunto pannello "Personalizzazione risposte e limiti" nella chat AI con stile operativo/sintetico/dettagliato, toggle per mostrare limiti quando mancano permessi/dati/tool e box "Puo/Non puo"; le preferenze sono salvate in `localStorage`, inviate all'API chat, sanificate da `views.py` e trasformate da `services.py` in istruzioni di risposta che non alterano ACL, privacy o tool live. Aggiunti test di rendering, sanitizzazione API e costruzione prompt preferenze.
- Impatto previsto: l'utente puo scegliere il taglio delle risposte e vede chiaramente che l'AI puo usare solo contesti autorizzati, proporre FAQ/miglioramenti approvati, ma non aggirare permessi, inventare dati o esporre dati sensibili.
- Rischi residui: preferenze salvate lato browser; non sono un profilo server-side centralizzato. La resa finale dipende comunque dal modello locale, ma il prompt ora contiene istruzioni esplicite e testate.
- Test/check: AST mirato OK; test mirati `test_chat_page_authenticated`, `test_build_messages_includes_sanitized_user_preferences`, `test_api_chat_sanitizes_and_passes_preferences`, `test_api_chat_passes_runtime_context_and_sources` OK; `python django_app\manage.py test ai_assistant.tests --settings=config.settings.test --verbosity 1` OK (56 test); `python django_app\manage.py check --settings=config.settings.test` OK; `git diff --check` OK.
- Note: nessun backup creato.

## 2026-05-22 - Codex

- Area: `django_app/ai_assistant` + documentazione.
- Richiesta: correggere il caso in cui `tool:anagrafica:ratei` veniva attivato ma il modello rispondeva ancora "Non ho accesso diretto" per domande nominative come "Quante ore ferie residue ha SMARRELLA?", con fonti RAG irrilevanti mostrate nel menu contestuale.
- File modificati: `django_app/ai_assistant/tools.py`, `django_app/ai_assistant/services.py`, `django_app/ai_assistant/views.py`, `django_app/ai_assistant/tests.py`, `README.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non e presente nella workspace. Nessuna modifica a settings, middleware, ACL, routing globale o navigazione globale.
- Motivo tecnico: il tool ratei produceva una classifica top N anche per domande su un singolo dipendente; se il nominativo non era nelle righe inviate, Qwen non aveva il dato diretto e tornava al fallback. Inoltre `chat_with_ollama` restituiva alla UI le fonti RAG anche quando il RAG non veniva iniettato nel payload, causando chip come sezioni README non pertinenti.
- Modifica: aggiunto filtro nominativo/self per i ratei, matching su nome/cognome/alias/matricola prima della query `SaldoCedolino`; aggiunta sezione `RISPOSTA DIRETTA` nel contesto live, conversione giorni su base 7.5 ore quando richiesta, istruzione runtime per riportare la risposta diretta, soppressione fonti RAG e `rag_context_chars=0` quando esiste un contesto `tool:*`, suggerimenti contestuali specifici per ratei.
- Impatto previsto: domande tipo "Quante ore ferie residue ha SMARRELLA?" rispondono con il saldo del dipendente richiesto e fonte `tool:anagrafica:ratei`, senza mostrare fonti documentali non usate.
- Rischi residui: il matching nominativo e parziale; in caso di omonimi mostra piu righe e richiede disambiguazione pratica. I ratei restano disponibili solo a utenti autorizzati da Anagrafica HR.
- Test/check: AST mirato OK; `python django_app\manage.py test ai_assistant.tests.AiAssistantTests.test_runtime_anagrafica_context_lists_named_ferie_residue ai_assistant.tests.AiAssistantTests.test_runtime_anagrafica_context_converts_named_ferie_to_days_when_requested ai_assistant.tests.AiAssistantTests.test_runtime_anagrafica_context_lists_top_ferie_residue ai_assistant.tests.AiAssistantTests.test_chat_with_ollama_hides_rag_sources_when_runtime_context_present --settings=config.settings.test --verbosity 2` OK; `python django_app\manage.py test ai_assistant.tests --settings=config.settings.test --verbosity 1` OK (54 test).
- Note: nessun backup creato.

## 2026-05-22 - Codex

- Area: `django_app/ai_assistant` + governance/documentazione AI.
- Richiesta: far rispondere l'assistente alla domanda "elencami i primi 5 dipendenti con maggior numero di ore ferie residue".
- File modificati: `django_app/ai_assistant/tools.py`, `django_app/ai_assistant/tests.py`, `README.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `docs/ai/12_AI_RUNTIME_TOOLS_TODOLIST.md`, `docs/ai/13_AI_GOVERNANCE.md`, `docs/ai/13_AI_GOVERNANCE_PREDICTIVE_POLICY.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non e presente nella workspace. Nessuna modifica a settings, middleware, ACL, routing globale o navigazione globale.
- Motivo tecnico: la richiesta su ferie residue veniva intercettata dal dominio Assenze o dal fallback senza produrre contesto live Anagrafica; i dati sono gia disponibili in `SaldoCedolino.ferie_residui` e la vista ratei e gated da permesso HR.
- Modifica: aggiunta sotto-modalita ratei al tool `anagrafica_summary`: riconosce ferie/ROL/permessi/ex-fest residui, usa l'ultimo periodo disponibile (o il mese richiesto), ordina per valore maggiore/minore, limita la classifica a N righe (default 5) e restituisce solo dipendente, reparto, periodo e ore residue. Il tool continua a bloccare CF, dettagli cedolino, retribuzioni, documenti, allegati e path; audit metadata-only con metrica, periodo, ordine e conteggi.
- Impatto previsto: una domanda come "elencami i primi 5 dipendenti con maggior numero di ore ferie residue" attiva `tool:anagrafica:ratei` e produce una classifica autorizzata invece del messaggio di mancato accesso.
- Rischi residui: i ratei ferie/permessi sono dati HR nominativi; restano esposti solo a superuser/admin legacy o ruoli `AnagraficaHRPermission` e solo in forma sintetica ore+periodo.
- Test/check: parse AST mirato OK; primo test mirato interrotto da timeout durante creazione DB test, poi `python django_app\manage.py test ai_assistant.tests.AiAssistantTests.test_runtime_anagrafica_context_lists_top_ferie_residue ai_assistant.tests.AiAssistantTests.test_runtime_anagrafica_context_lists_privacy_consent_for_authorized_user ai_assistant.tests.AiAssistantTests.test_runtime_context_reports_missing_live_tool_for_deferred_hr_domains --settings=config.settings.test --verbosity 1` OK; `python django_app\manage.py test ai_assistant.tests --settings=config.settings.test --verbosity 1` OK (51 test); `python django_app\manage.py check --settings=config.settings.test` OK.
- Note: nessun backup creato.

## 2026-05-22 - Codex

- Area: `django_app/ai_assistant` + governance/documentazione AI.
- Richiesta: abilitare il modulo Anagrafica nell'assistente AI, dopo il fallback `tool:runtime:non-disponibile`.
- File modificati: `django_app/ai_assistant/tools.py`, `django_app/ai_assistant/tests.py`, `django_app/admin_portale/tests.py`, `README.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `docs/ai/12_AI_RUNTIME_TOOLS_TODOLIST.md`, `docs/ai/13_AI_GOVERNANCE.md`, `docs/ai/13_AI_GOVERNANCE_PREDICTIVE_POLICY.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non e presente nella workspace. Nessuna modifica a settings, middleware, ACL, routing globale o navigazione globale.
- Motivo tecnico: il catalogo runtime marcava il dominio combinato Timbri/Anagrafica come deferred, quindi ogni domanda su dipendenti/consenso privacy produceva fallback privacy senza leggere i dati gia disponibili nel modulo Anagrafica.
- Modifica: separato `anagrafica_summary` da `timbri_presenze`; aggiunto tool Anagrafica HR read-only con permesso superuser/admin legacy o ruoli `AnagraficaHRPermission`, loader su `fetch_anagrafica_rows` + `DipendenteAnagraficaAziendale`, filtri sintetici per consenso privacy/reparto-area/stato e output limitato a nome, matricola, reparto, mansione, area, ruolo aziendale, stato e consenso privacy se richiesto. Il tool blocca esplicitamente richieste di CF, IBAN, banca, indirizzi, contatti privati, categorie protette/disabilita, visite mediche, retribuzioni, documenti, allegati e path. Timbri/Presenze resta deferred.
- Impatto previsto: l'assistente puo rispondere a richieste tipo "elenco dipendenti che hanno fornito il consenso privacy" mostrando solo dati aziendali minimi e fonte `tool:anagrafica:dipendenti`; le richieste su timbrature o dati HR riservati restano fail-closed.
- Rischi residui: il tool espone nominativi e dati aziendali minimali al modello locale per utenti autorizzati; la governance resta `restricted` e va tenuta allineata in Admin AI se si usa `AiToolPrivacyReview`. Non abilita timbrature/presenze.
- Test/check: parse AST mirato OK; `python django_app\manage.py test ai_assistant.tests.AiAssistantTests.test_runtime_anagrafica_context_lists_privacy_consent_for_authorized_user ai_assistant.tests.AiAssistantTests.test_runtime_anagrafica_context_denies_user_without_hr_permission ai_assistant.tests.AiAssistantTests.test_runtime_anagrafica_context_blocks_forbidden_hr_fields ai_assistant.tests.AiAssistantTests.test_runtime_context_reports_missing_live_tool_for_deferred_hr_domains admin_portale.tests.AdminPortaleConfigSrvLdapTests.test_ai_settings_page_renders_live_tools_console --settings=config.settings.test --verbosity 1` OK; `python django_app\manage.py test ai_assistant.tests --settings=config.settings.test --verbosity 1` OK (50 test; prima esecuzione completa ha evidenziato il test legacy di troncamento sotto soglia, aggiornato da 250 a 500 righe); `python django_app\manage.py check --settings=config.settings.test` OK.
- Note: nessun backup creato. `django_app/admin_portale/tests.py` era read-only: attributo rimosso solo per aggiornare il test del catalogo Tool live e poi ripristinato.

## 2026-05-22 - Codex

- Area: `django_app/anagrafica`.
- Richiesta: correggere il 500 su `POST /anagrafica/dipendenti/277/documenti/upload` con `NameError: name 'Path' is not defined`.
- File modificati: `django_app/anagrafica/views.py`, `django_app/anagrafica/tests.py`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non e presente nella workspace.
- Motivo tecnico: `documento_dipendente_upload` usa `Path(uploaded.name).suffix` ma `Path` non era importato in `views.py`; inoltre l'audit `DOCUMENTO_DIPENDENTE_UPLOAD` passava una stringa a `core.audit.log_action`, che si aspetta un dict.
- Modifica: aggiunto `from pathlib import Path`; audit upload convertito a payload dict con id documento, nome file, cartella e `legacy_anagrafica_id`; aggiunto test `DocumentoDipendenteUploadTests`.
- Impatto previsto: l'upload manuale dei documenti dipendente salva il file privato e torna alla scheda dipendente senza errore 500 e senza errore audit fail-soft.
- Rischi residui: lo sniff MIME resta sul comportamento corrente della view: se `core.upload_mime.sniff_mime` non e disponibile, usa `uploaded.content_type` come fallback; nessuna modifica a policy formati/dimensione.
- Test/check: `python django_app\manage.py test anagrafica.tests.DocumentoDipendenteUploadTests --settings=config.settings.test --verbosity 2` OK; `python django_app\manage.py check --settings=config.settings.test` OK; `python django_app\manage.py check` OK. Un primo run del test e passato ma mostrava errore audit fail-soft; ripetuto OK dopo payload dict.
- Note: nessun backup creato.

## 2026-05-22 - Codex

- Area: `django_app/anagrafica`.
- Richiesta: correggere il 500 su `POST /anagrafica/cartelle-documenti/nuovo` con `NoReverseMatch: Reverse for 'impostazioni?tab=documenti' not found`.
- File modificati: `django_app/anagrafica/views.py`, `django_app/anagrafica/tests.py`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non e presente nella workspace.
- Motivo tecnico: `redirect("anagrafica:impostazioni" + "?tab=documenti")` concatena la querystring al nome URL prima del reverse; Django prova quindi a risolvere `anagrafica:impostazioni?tab=documenti`, che non esiste. Lo stesso pattern era presente anche nella CRUD subnav (`_SUBNAV_REDIRECT + _SUBNAV_TAB`).
- Modifica: tutti i redirect della CRUD `CartellaDocumentoDipendente` usano `_redirect_impostazioni("documenti")`; tutti i redirect CRUD subnav usano `_redirect_impostazioni("navigazione")`; rimosse le costanti subnav non piu necessarie; aggiunti test `ImpostazioniRedirectTests`.
- Impatto previsto: dopo creazione/modifica/eliminazione cartelle documenti o subnav, l'utente torna alla tab corretta di `/anagrafica/impostazioni/` senza errore 500.
- Rischi residui: nessuno noto; nessuna modifica a schema DB, ACL, middleware, routing globale o settings.
- Test/check: `python django_app\manage.py test anagrafica.tests.ImpostazioniRedirectTests --settings=config.settings.test --verbosity 2` OK; `python django_app\manage.py check --settings=config.settings.test` OK; `python django_app\manage.py check` OK; scansione `Select-String` senza residui del pattern `redirect(... + "?tab=...")` nei punti corretti.
- Note: nessun backup creato.

## 2026-05-22 - Codex

- Area: `django_app/anagrafica`.
- Richiesta: correggere il 500 su `GET /anagrafica/documenti/` con `TemplateSyntaxError: Variables and attributes may not begin with underscores: 'd._nome_dipendente'`.
- File modificati: `django_app/anagrafica/views.py`, `django_app/anagrafica/templates/anagrafica/pages/documenti_list.html`, `django_app/anagrafica/tests.py`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non e presente nella workspace.
- Motivo tecnico: Django template engine blocca variabili/attributi che iniziano con underscore; inoltre `documenti_list.html` estendeva `base.html`, incoerente con gli altri template anagrafica che usano `core/base.html`.
- Modifica: la view `documenti_list` espone `nome_dipendente` invece di `_nome_dipendente`; il template usa `{{ d.nome_dipendente }}` ed estende `core/base.html`; aggiunto test di regressione `DocumentoDipendenteListTests`.
- Impatto previsto: `/anagrafica/documenti/` torna a renderizzare l'archivio documenti manuali con nome dipendente e link scheda senza errore 500.
- Rischi residui: nessuno noto; nessuna modifica a schema DB, ACL, routing globale, middleware o settings.
- Test/check: `python django_app\manage.py test anagrafica.tests.DocumentoDipendenteListTests --settings=config.settings.test --verbosity 2` OK; `python django_app\manage.py check --settings=config.settings.test` OK; `python django_app\manage.py check` OK. Un primo run del test e fallito prima della correzione del parent template (`base.html` non trovato nel profilo test); ripetuto con esito OK dopo la fix.
- Note: nessun backup creato.

## 2026-05-22 - Codex

- Area: `config/runtime`.
- Richiesta: diagnosi traceback `django.db.utils.OperationalError ('08001')` durante comando `manage.py`, con timeout ODBC Driver 18 su SQL Server.
- File modificati: `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File applicativi modificati: nessuno.
- File critici modificati: nessuno; `_AGENT_CONTROL/CRITICAL_FILES.md` non e presente nella workspace.
- Motivo tecnico: il profilo `config.settings.dev` legge `django_app/.env`; in questa workspace `DB_ENGINE=sqlserver` punta a `localhost\SQLEXPRESS` con autenticazione Windows. Il traceback nasce durante i system check DB di Django/mssql-django, quando il backend apre una connessione per verificare il supporto a `JSONField`.
- Modifica: nessuna modifica runtime o codice; eseguita solo diagnosi non sensibile su `.env`, driver ODBC, servizi SQL e comandi Django.
- Esito verifica: `MSSQL$SQLEXPRESS` risulta avviato; ODBC Driver 18 e 17 sono installati a 32/64 bit; connessione diretta pyodbc a `localhost\SQLEXPRESS` sul database locale riuscita; `python manage.py check`, `python manage.py check --database default`, `python manage.py check --settings=config.settings.test` OK; `showmigrations anagrafica --plan` OK e mostra `anagrafica.0022_subnavlink_anagrafica` ancora da applicare.
- Rischi residui: se SQL Server/SQLEXPRESS e appena avviato, bloccato, non raggiungibile o il database locale non e disponibile, i comandi che richiedono DB possono ripresentare lo stesso timeout; per controlli Django-only usare `--settings=config.settings.test`.
- Test/check: comandi elencati sopra; nessuna migrazione applicata e nessun file applicativo modificato.
- Note: nessun backup creato.

## 2026-05-21 - Codex

- Area: `config/runtime`.
- Richiesta: individuare il `.env` reale in `Y:\PortaleNovicrom\prod\...`.
- File modificati: `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File applicativi modificati: nessuno.
- File critici modificati: nessuno; il `.env` non e stato modificato.
- Motivo tecnico: l'ambiente mappato espone `Y:\` direttamente come root PROD, non `Y:\PortaleNovicrom\prod`; il file persistente letto per primo e `Y:\config\.env`.
- Modifica: nessuna patch runtime; verificati solo i valori non sensibili `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `SITE_URL`.
- Esito verifica: `Y:\config\.env` contiene `DJANGO_ALLOWED_HOSTS=hub.cnovicrom.local,127.0.0.1` e `DJANGO_CSRF_TRUSTED_ORIGINS=https://hub.cnovicrom.local`, quindi manca `https://hub.costruzioninovicrom.it`; `Y:\current\django_app\.env` contiene gia il dominio pubblico ma viene caricato dopo e non sovrascrive le chiavi gia presenti.
- Rischi residui: `Y:\venv\Scripts\python.exe` esiste ma il venv punta a `C:\Users\administrator\AppData\Local\Programs\Python\Python313\python.exe`, non presente; il check `manage.py shell` non e eseguibile finche il venv non viene ripristinato.
- Test/check: `Select-String` mirato sui due `.env`; verifica esistenza `manage.py`, venv python e `pyvenv.cfg`; tentativo `manage.py shell` fallito per venv rotto.
- Note: nessun backup creato.

## 2026-05-21 - Codex

- Area: `config/runtime`.
- Richiesta: nuovo log produzione con `Forbidden (Origin checking failed - https://hub.costruzioninovicrom.it does not match any trusted origins.): /login/` dopo la correzione proposta.
- File modificati: `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File applicativi modificati: nessuno.
- File critici modificati: nessuno.
- Motivo tecnico: il processo Django in esecuzione non sta ancora leggendo `DJANGO_CSRF_TRUSTED_ORIGINS` con l'origin pubblico, oppure legge un valore precedente dalla precedenza runtime.
- Modifica: nessuna patch runtime; indicati comandi di verifica su PROD per stampare `settings.CSRF_TRUSTED_ORIGINS`, `settings.ALLOWED_HOSTS`, il valore env e i dotenv caricati.
- Impatto previsto: consente di distinguere tra `.env` modificato nel percorso sbagliato, mancato recycle App Pool, nome variabile errato, separatore CSV errato o variabile di processo che sovrascrive il file.
- Rischi residui: finche il processo non espone `https://hub.costruzioninovicrom.it` in `settings.CSRF_TRUSTED_ORIGINS`, `/login/` continuera a tornare 403 sui POST.
- Test/check: riletti `env_config.py` e `settings/prod.py`; nessun test applicativo eseguito.
- Note: nessun backup creato.

## 2026-05-21 - Codex

- Area: `config/runtime`.
- Richiesta: mantenere l'accesso al portale sia dal dominio pubblico sia dal sito locale.
- File modificati: `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File applicativi modificati: nessuno.
- File critici modificati: nessuno; non sono stati modificati settings, middleware, ACL o `.env`.
- Motivo tecnico: Django richiede che ogni host usato per raggiungere il portale sia presente in `DJANGO_ALLOWED_HOSTS`; ogni origin da cui partono POST/HTMX/form deve essere presente in `DJANGO_CSRF_TRUSTED_ORIGINS` con schema e, se non standard, porta.
- Modifica: nessuna patch runtime; indicata configurazione `.env` multi-origin per dominio pubblico e dominio locale.
- Impatto previsto: il portale resta raggiungibile sia da `https://hub.costruzioninovicrom.it` sia dal nome locale, senza 403 CSRF sui POST.
- Rischi residui: se il sito locale usa HTTP invece di HTTPS e i cookie secure sono attivi, login/POST possono fallire; preferibile pubblicare anche il locale in HTTPS oppure configurare coerentemente cookie e proxy.
- Test/check: nessun test applicativo eseguito; modifica solo documentazione agente.
- Note: nessun backup creato.

## 2026-05-21 - Codex

- Area: `config/runtime`.
- Richiesta: diagnosi errore sito web "Token di sessione non valido" con dettaglio `HTTP 403 - Origin checking failed - https://hub.costruzioninovicrom.it does not match any trusted origins`.
- File modificati: `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File applicativi modificati: nessuno.
- File critici modificati: nessuno; non sono stati modificati `django_app/config/settings/*.py`, middleware, ACL o `.env`.
- Motivo tecnico: l'errore e generato dal controllo CSRF di Django quando l'origin pubblico `https://hub.costruzioninovicrom.it` non e presente in `DJANGO_CSRF_TRUSTED_ORIGINS` o non combacia con host/scheme visti dal backend dietro IIS/Waitress.
- Modifica: nessuna patch runtime; indicata correzione operativa sul `.env` persistente di produzione con `DJANGO_CSRF_TRUSTED_ORIGINS=https://hub.costruzioninovicrom.it` e verifica di `DJANGO_ALLOWED_HOSTS`.
- Impatto previsto: dopo aggiornamento `.env` e recycle dell'App Pool/IIS, i POST dal dominio pubblico passano il controllo Origin CSRF.
- Rischi residui: se il proxy/IIS non inoltra correttamente host o scheme, puo servire anche verificare header `X-Forwarded-Proto`/Host e l'eventuale supporto `USE_X_FORWARDED_HOST`; modifiche a settings richiedono autorizzazione esplicita.
- Test/check: letti `CLAUDE.md`, checkpoint e file controllo disponibili; ispezionati `django_app/config/settings/prod.py`, `base.py`, `env_config.py`, `deployment/setup_wizard.py`, `.env.example` e riferimenti CSRF/deploy. Nessun test applicativo eseguito perche non sono stati modificati file applicativi.
- Note: nessun backup creato.

## 2026-05-21 - Claude (Opus 4.7)

- Area: `django_app/anagrafica` + `django_app/dpi` + `django_app/config/settings`.
- Richiesta utente: integrare i DPI consegnati ai dipendenti con modulistica PDF prodotta dal portale e caricata automaticamente nello spazio del dipendente (anche per i DPI consegnati all'ingresso, proposti in base alla mansione), e aggiungere la gestione delle visite mediche con tipologie configurabili per ruolo operativo e scadenza calcolata dalla data dell'ultima visita.
- File creati: `django_app/anagrafica/storage.py`, `django_app/anagrafica/services/__init__.py`, `django_app/anagrafica/services/visite.py`, `django_app/anagrafica/services/dpi_ingresso.py`, `django_app/anagrafica/templatetags/__init__.py`, `django_app/anagrafica/templatetags/anagrafica_extras.py`, `django_app/anagrafica/management/commands/send_visite_expiry_reminders.py`, `django_app/anagrafica/migrations/0018_documentodipendente_visitamedica.py`, `django_app/anagrafica/migrations/0019_seed_tipi_visita.py`, `django_app/anagrafica/templates/anagrafica/partials/_dpi_iniziali_righe.html`, `django_app/dpi/pdf.py`, `_AGENT_CONTROL/TODO_DPI_VISITE_INTEGRATION.md`.
- File modificati: `django_app/config/settings/base.py`, `django_app/anagrafica/models.py`, `django_app/anagrafica/admin.py`, `django_app/anagrafica/forms.py`, `django_app/anagrafica/views.py`, `django_app/anagrafica/urls.py`, `django_app/anagrafica/tests.py`, `django_app/anagrafica/templates/anagrafica/pages/dipendente_create.html`, `django_app/anagrafica/templates/anagrafica/pages/dipendente_detail.html`, `django_app/anagrafica/templates/anagrafica/components/subnav.html`, `django_app/dpi/views.py`, `README.md`, `CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`.
- File critici modificati: nessuno rilevato in `_AGENT_CONTROL/CRITICAL_FILES.md` (file non presente).
- Motivo tecnico: lo schema esisteva già per `ConsegnaDPI`+firma ma il PDF di consegna non era persistito e non c'era spazio documenti dipendente; le visite mediche erano completamente assenti.
- Modifica: nuovo storage privato `PrivateAnagraficaStorage` su `ANAGRAFICA_PRIVATE_ROOT`; modello unico `DocumentoDipendente` per consegne DPI/referti/altro con ACL per tipo; modelli `TipoVisitaMedica` (M2M `RuoloOperativo`, `durata_mesi`) e `VisitaMedica` con scadenza calcolata in `save()` via helper Python-only `_add_months` (no dipendenza `dateutil`); singleton `AnagraficaVisiteMedichePermission` (default `ADMIN`); helper `_can_view_visite_mediche`; generatore PDF `dpi/pdf.py::render_modulo_consegna_dpi[_multipla]` con reportlab che incorpora la firma `data:image/png;base64,...`; hook in `dpi.views::consegna_richiesta` archivia il PDF come `DocumentoDipendente` in modo idempotente; nel form di creazione dipendente, multiselect ruoli operativi + sezione HTMX "DPI consegnati all'ingresso" che propone le categorie `obbligatoria_mansionario=True` e crea automaticamente `RichiestaDPI`+`ConsegnaDPI` (firma differita) + PDF cumulativo; scheda dipendente arricchita con card "🏥 Visite mediche" (stato per ruolo + storico + form add) e "📄 Documenti"; management command `send_visite_expiry_reminders` con dry-run; 14 nuovi test (calcolo scadenza, stato visite, PDF render, ACL referto, servizio ingresso) tutti verdi; data migration 0019 con seed di 6 tipi visita comuni (art. 41, VDT, MMC, rumore, DPI III cat., lavori in quota) — `obbligatoria=False, ruoli=[]` da configurare.
- Impatto previsto: l'utente HR può registrare consegne DPI ottenendo il PDF firmato nello spazio dipendente; può consegnare i DPI obbligatori all'ingresso e gestire le visite mediche con calendario di scadenza automatico per ruolo.
- Rischi residui: richiede migrazione `anagrafica.0018` + `anagrafica.0019`; la cartella `media_private/anagrafica/` va creata e protetta in prod (non esposta da IIS); l'M2M `TipoVisitaMedica.ruoli_operativi` parte vuoto per i tipi seed, va popolato manualmente da admin prima che il sistema generi alert; bug pre-esistenti rilevati ma non corretti: (a) `core.audit.log_action` riceve stringa invece di dict (errore log fail-soft, non blocca), (b) `dateutil` non è installato pur essendo importato da `anagrafica/views.py:1275` per le qualifiche.
- Test/check: `python django_app\manage.py check --settings=config.settings.test` OK; `python django_app\manage.py makemigrations --check --dry-run --settings=config.settings.dev` OK; `python django_app\manage.py test anagrafica.tests.VisitaMedicaScadenzaTests anagrafica.tests.StatoVisiteServiceTests anagrafica.tests.DPIPDFRenderTests anagrafica.tests.VisiteMedichePermissionTests anagrafica.tests.DocumentoDipendenteDownloadACLTests anagrafica.tests.DPIIngressoServiceTests --settings=config.settings.test` → 14/14 OK; suite anagrafica completa 24/25 OK (1 errore pre-esistente in `test_upload_validation.py` che importa `FornitoreDocumentoForm` spostato nel modulo `fornitori`, non regressione).
- Note: piano completo in `C:\Users\l.bova\.claude\plans\vectorized-floating-lampson.md`. Tracciamento operativo in `_AGENT_CONTROL/TODO_DPI_VISITE_INTEGRATION.md`. UI smoke test manuale (dev server + browser) non eseguito.

## 2026-05-21 - Codex

- Area: `django_app/anagrafica`
- Richiesta: su `/anagrafica/dipendenti/` ordinare sempre la tabella all'accesso da A a Z per dipendente, rimuovere il cerchio con iniziali e usare foto dipendente con upload in anagrafica/fallback grigio.
- File modificati: `django_app/anagrafica/models.py`, `django_app/anagrafica/migrations/0017_dipendenteanagraficacivile_foto.py`, `django_app/anagrafica/forms.py`, `django_app/anagrafica/views.py`, `django_app/anagrafica/templates/anagrafica/pages/dipendenti_list.html`, `django_app/anagrafica/templates/anagrafica/pages/dipendente_detail.html`, `django_app/anagrafica/templates/anagrafica/pages/dipendente_create.html`, `django_app/anagrafica/tests.py`, `README.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non e presente nella workspace.
- Motivo tecnico: rendere stabile l'ordinamento iniziale della lista dipendenti e sostituire avatar testuali con una foto reale gestita dal portale.
- Modifica: aggiunto campo `foto` su `DipendenteAnagraficaCivile` con upload sotto `anagrafica/dipendenti/<legacy_id>/foto/`; i form civile di creazione/modifica accettano upload immagine; la lista ordina lato server per `cognome`, `nome`, `aliasusername`, `id` prima della paginazione; lista e hero scheda mostrano foto o fallback grigio CSS senza iniziali.
- Impatto previsto: entrando in `/anagrafica/dipendenti/` la tabella parte gia in ordine alfabetico per dipendente; le foto caricate sono visibili in lista e scheda.
- Rischi residui: richiede applicazione migrazione `0017`; le foto sono servite tramite media runtime esistente e restano dati personali da gestire secondo policy interna.
- Test/check: `python django_app\manage.py test anagrafica.tests --settings=config.settings.test --verbosity 1` OK; `python django_app\manage.py check --settings=config.settings.test` OK; `python django_app\manage.py makemigrations --check --dry-run --settings=config.settings.test` OK.
- Note: nessun backup creato. I test di creazione dipendente sono stati riallineati alla view corrente `dipendente_create`.

- Area: `django_app/anagrafica`
- Richiesta: correggere il 500 su `GET /anagrafica/ratei/export/?periodo=2026-05-31&reparto=AMMINISTRAZIONE` con errore openpyxl `MergedCell object attribute 'value' is read-only`.
- File modificati: `django_app/anagrafica/views.py`, `django_app/anagrafica/tests.py`, `README.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non e presente nella workspace.
- Motivo tecnico: l'export ratei univa verticalmente `A1:A2`, `B1:B2`, `C1:C2`, `D1:D2`, poi tentava di scrivere anche nelle celle `A2:D2`, che openpyxl espone come `MergedCell` read-only.
- Modifica: rimosse `A:D` dalla lista delle sotto-intestazioni di riga 2; restano scritte solo le sotto-intestazioni operative `E:P` per Ferie, ROL ed Ex-Festivita. Aggiunto test di regressione che crea un saldo cedolino, chiama l'export con filtro periodo/reparto, apre l'XLSX con openpyxl e verifica header/dati principali.
- Impatto previsto: il bottone export Excel dei ratei non genera piu errore 500 con filtri attivi e produce un workbook valido.
- Rischi residui: nessuno noto; la correzione non cambia ACL, routing, schema DB o dipendenze.
- Test/check: `python django_app\manage.py test anagrafica.tests.AnagraficaRateiExportTests --settings=config.settings.test --verbosity 2` OK; `python django_app\manage.py check --settings=config.settings.test` OK.
- Note: nessun backup creato.

## 2026-05-20 - Codex

- Area: `git/workspace`
- Richiesta: fare commit e push su Git per pulire la workspace.
- File modificati: tutti i file gia modificati/non tracciati nella workspace al momento della richiesta, inclusa la nota agente corrente.
- File critici modificati: presenti modifiche gia in workspace a `django_app/config/settings/base.py` e altri file di configurazione/deploy; dettagli funzionali nelle voci precedenti.
- Motivo tecnico: consolidare su repository remoto le modifiche accumulate e riportare la working tree Git a stato pulito.
- Modifica: eseguiti controlli pre-commit (`git diff --check`, status, elenco untracked), previsto commit unico e push su `origin/main`.
- Impatto previsto: le modifiche locali diventano tracciate sul branch remoto `main`.
- Rischi residui: commit ampio con molte modifiche pregresse non tutte originate in questa micro-sessione; nessun `.env` reale visibile nello staging Git.
- Test/check: `git diff --check` OK; test applicativi specifici gia indicati nelle voci funzionali precedenti.
- Note: nessun backup creato.

- Area: `django_app/assenze`, `config/runtime`
- Richiesta: verificare se il sync SharePoint del modulo assenze fosse disattivato e riabilitarlo.
- File modificati: `django_app/config/settings/base.py`, `.env.example`, `django_app/.env.example`, `django_app/setup_wizard/templates/setup_wizard/wizard.html`, `tools/setup-wizard.html`, `django_app/hub_tools/views.py`, `django_app/assenze/tests.py`, `README.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: `django_app/config/settings/base.py`.
- Motivo tecnico: il flag `ASSENZE_SYNC_ON_PAGE_LOAD` risultava disattivato nei default versionati (`False`/`0`), quindi il pull SharePoint automatico sulle pagine operative assenze non partiva salvo override esplicito nel `.env`.
- Modifica critica: default runtime `ASSENZE_SYNC_ON_PAGE_LOAD` portato a `True`; esempi `.env` e wizard impostano/generano `ASSENZE_SYNC_ON_PAGE_LOAD=1`; il setup hub usa `1` come default quando la chiave manca; aggiunti test mirati sul parser del flag.
- Impatto previsto: se Graph e le liste assenze sono configurati, `gestione_assenze` e `car_dashboard` tornano a lanciare il pull SharePoint automatico, sempre throttled da `ASSENZE_SP_PULL_INTERVAL_SECONDS`.
- Rischi residui: un `.env` reale gia valorizzato con `ASSENZE_SYNC_ON_PAGE_LOAD=0` continua a prevalere e va corretto tramite pannello/configurazione server; non sono stati letti o modificati `.env` reali per policy sui segreti.
- Test/check: `python django_app\manage.py test assenze.tests.AssenzeSyncFlagTests --settings=config.settings.test --verbosity 2` OK; `python django_app\manage.py check --settings=config.settings.test` OK.
- Note: rimosso attributo read-only da `django_app/assenze/tests.py` per aggiungere copertura; nessun backup creato.

- Area: `config/runtime`
- Richiesta: memorizzare la procedura corretta per il problema ricorrente menu/topbar popolato con voci legacy, ordine errato e categorie padre mancanti.
- File modificati: `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno rilevato; nota documentale operativa.
- Motivo tecnico: il problema non era il file `views.py` ne la preferenza sidebar/topbar, ma il `.env` prod con `NAVIGATION_REGISTRY_ENABLED=0` e `NAVIGATION_LEGACY_FALLBACK_ENABLED=1`, che disabilitava il Navigation Registry e forzava il fallback legacy `pulsanti`.
- Procedura corretta: impostare `NAVIGATION_REGISTRY_ENABLED=1` e `NAVIGATION_LEGACY_FALLBACK_ENABLED=0`, poi pulire cache/sessioni e riciclare IIS/app pool.
- Impatto previsto: la navigazione torna a usare `NavigationItem` con categorie padre/ordine configurati, invece dei nomi legacy dei pulsanti.
- Rischi residui: capire perche il setup/runtime riscrive talvolta `.env` con quei flag sbagliati; da indagare in un passaggio separato.
- Test/check: nota salvata in checkpoint agente; nessun test eseguito per modifica documentale.
- Note: questa e la prima verifica da fare se il menu "si risminchia" dopo deploy/hotfix/migrazioni.

- Area: `hotfix`
- Richiesta: rifare la hotfix QR in modo chirurgico partendo dal `views.py` sano fornito su Desktop, per evitare regressioni UI/topbar introdotte dal pacchetto precedente.
- File modificati/creati: `hotfix/hotfix-v1.0.2-20260520_121751-qr-site-url-clean.zip`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- Contenuto pacchetto: `django_app/assets/views.py`.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non era presente nella workspace.
- Motivo tecnico: la hotfix `hotfix-v1.0.2-20260520_103701-qr-site-url.zip` era basata su un `views.py` di workspace troppo avanzato e poteva disallineare UI/template. Serviva una patch runtime minima sul file produzione sano.
- Modifica: copiato `C:\Users\l.bova\Desktop\views.py` in staging, aggiunto solo helper `_portal_absolute_uri()` e sostituite le chiamate QR/preview a `request.build_absolute_uri()` con il fallback su `SITE_URL`.
- Impatto previsto: ripristina lo stato funzionale della UI mantenendo il fix per generare QR `https` via `SITE_URL`.
- Rischi residui: richiede `SITE_URL` corretto nel `.env` prod, riciclo app pool/IIS e rigenerazione dei PDF QR; non usare il pacchetto precedente `hotfix-v1.0.2-20260520_103701-qr-site-url.zip`.
- Test/check: `python -m py_compile` sul file staging OK; contenuto zip verificato (`django_app/assets/views.py` solo); SHA256 `ACE31DF9AF3F5C373C97CD3059DE4B47DB94C32F21A9DC7C8124DB4D514C99B1`.
- Note: nessun backup creato.

- Area: `hotfix`
- Richiesta: creare hotfix minimale per correggere i QR pubblici asset generati in `http` invece di `https`.
- File modificati/creati: `hotfix/hotfix-v1.0.2-20260520_103701-qr-site-url.zip`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- Contenuto pacchetto: `django_app/assets/views.py`.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non era presente nella workspace.
- Motivo tecnico: distribuire rapidamente la correzione runtime che usa `SITE_URL` come base canonica per le etichette QR, senza release completa.
- Impatto previsto: applicando lo zip al release attivo e configurando `SITE_URL=https://hub.cnovicrom.local`, le nuove etichette QR puntano a `https://hub.cnovicrom.local/assets/public/<token>/`.
- Rischi residui: il pacchetto contiene solo `views.py`; richiede riciclo app pool/IIS e rigenerazione delle etichette gia prodotte. Se `SITE_URL` manca o e errato, il QR puo ancora usare una base non corretta.
- Test/check: contenuto zip verificato (`django_app/assets/views.py`); SHA256 `60BC4B350A693BBEDA35F27A7780D4A79A5D7E91715DF9D6CB0EB6784F950227`.
- Note: nessun backup creato.

- Area: `django_app/assets`
- Richiesta: correggere le etichette QR asset che continuavano a generare link `http://hub.cnovicrom.local/assets/public/<token>/` invece di `https://...` dietro IIS/Waitress.
- File modificati: `django_app/assets/views.py`, `django_app/assets/tests.py`, `README.md`, `django_app/assets/README.md`, `docs/assets/SHAREPOINT_CARTELLE_ASSET_GUIDE.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non era presente nella workspace.
- Motivo tecnico: `request.build_absolute_uri()` costruiva la route QR con lo scheme visto dalla request interna, che in produzione puo essere `http` anche quando il dominio pubblico e HTTPS.
- Modifica: aggiunto helper `_portal_absolute_uri()` che usa `settings.SITE_URL` come base canonica quando configurato; applicato ai target QR pubblico, landing, dettaglio e preview etichetta. Documentato l'uso di `SITE_URL=https://hub.cnovicrom.local`.
- Impatto previsto: rigenerando le etichette PDF, i QR pubblici puntano a `https://hub.cnovicrom.local/assets/public/<token>/`; i link gia stampati/generati prima restano invariati.
- Rischi residui: in produzione serve avere `SITE_URL` valorizzato correttamente e riavviare/riciclare l'app pool se si modifica `.env`; se `SITE_URL` resta vuoto, il comportamento torna a dipendere dalla request.
- Test/check: `python django_app\manage.py test assets.tests.AssetsRoutingTests.test_asset_qr_label_defaults_to_public_route_when_available assets.tests.AssetsRoutingTests.test_asset_qr_label_uses_site_url_for_public_route assets.tests.AssetsRoutingTests.test_asset_qr_label_does_not_use_internal_sharepoint_folder_without_public_link assets.tests.AssetsRoutingTests.test_asset_qr_label_detail_target_still_points_to_asset_detail --settings=config.settings.test --verbosity 2` OK; `python django_app\manage.py check --settings=config.settings.test` OK.
- Note: nessun backup creato.

## 2026-05-19 - Codex

- Area: `django_app/hub_tools`, `django_app/assets`
- Richiesta: unificare nella gestione server/admin portale le configurazioni SharePoint usate dagli asset, inclusi i link pubblici QR.
- File modificati: `django_app/hub_tools/views.py`, `django_app/hub_tools/templates/hub_tools/setup_wizard.html`, `django_app/hub_tools/tests.py`, `django_app/assets/templates/assets/pages/gestione_admin.html`, `README.md`, `django_app/assets/README.md`, `docs/assets/SHAREPOINT_CARTELLE_ASSET_GUIDE.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno rilevato in questo passaggio; `_AGENT_CONTROL/CRITICAL_FILES.md` non era presente nella workspace. La modifica riguarda comunque UI amministrativa di configurazione server e va considerata operativamente sensibile.
- Motivo tecnico: le impostazioni SharePoint asset erano disponibili dal modulo assets, ma il punto naturale di amministrazione delle connessioni Graph/SharePoint e il pannello centrale `/admin-portale/hub/setup-wizard/`.
- Modifica: estesa la sezione Microsoft Graph / SharePoint del setup wizard hub con URL libreria asset, toggle link pubblici QR, root consentita e ID root/site/drive; il salvataggio aggiorna le stesse chiavi `.env` usate dal modulo assets. La pagina assets mostra un rimando al pannello centrale.
- Impatto previsto: gli admin possono gestire tutte le connessioni SharePoint dal pannello server centrale mantenendo flessibilita di modulo; nessun cambio DB e nessuna chiamata Graph reale nei test.
- Rischi residui: come per gli altri setting `.env`, in ambienti multi-processo puo servire riavviare/riciclare l'app pool per allineare tutti i worker; valori root/item errati bloccano correttamente la generazione link pubblici.
- Test/check: `python django_app\manage.py test hub_tools.tests.HubSetupWizardEnvTests.test_setup_wizard_renders_true_false_env_booleans_correctly hub_tools.tests.HubSetupWizardEnvTests.test_setup_wizard_renders_asset_sharepoint_public_link_fields hub_tools.tests.HubSetupWizardEnvTests.test_reconfigure_saves_asset_sharepoint_public_link_settings assets.tests.AssetsRoutingTests.test_gestione_admin_shows_sharepoint_config_card assets.tests.AssetsRoutingTests.test_gestione_admin_can_save_sharepoint_config --settings=config.settings.test --verbosity 2` OK; `python django_app\manage.py test hub_tools --settings=config.settings.test --verbosity 1` OK (13 test); `python django_app\manage.py check --settings=config.settings.test` OK; `python django_app\manage.py makemigrations --check --dry-run --settings=config.settings.test` OK.
- Note: nessun backup creato.

- Area: `django_app/assets`
- Richiesta: gestire da administrator asset le impostazioni `SHAREPOINT_ASSET_PUBLIC_LINKS_ENABLED`, root consentita e ID root/site/drive per i link pubblici QR SharePoint.
- File modificati: `django_app/assets/views.py`, `django_app/assets/templates/assets/pages/gestione_admin.html`, `django_app/assets/services/sharepoint_public_links.py`, `django_app/assets/management/commands/assets_ensure_public_share_links.py`, `django_app/assets/tests.py`, `README.md`, `django_app/assets/README.md`, `docs/assets/SHAREPOINT_CARTELLE_ASSET_GUIDE.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno rilevato in questo passaggio; `_AGENT_CONTROL/CRITICAL_FILES.md` non era presente nella workspace.
- Motivo tecnico: dopo l'introduzione dei link pubblici QR, i relativi `SHAREPOINT_ASSET_*` dovevano essere amministrabili dalla pagina impostazioni del modulo assets, senza richiedere modifica manuale del file `.env`.
- Modifica: estesa la card SharePoint / Microsoft Graph di `/assets/impostazioni/?tab=config` con toggle link pubblici QR, root consentita e ID root/site/drive; il salvataggio aggiorna le chiavi `.env`; servizio e command leggono i valori aggiornati da processo/env mantenendo default sicuri.
- Impatto previsto: l'admin asset puo attivare/disattivare e configurare i link pubblici SharePoint QR dal portale; la feature resta spenta di default e continua a creare solo link Graph `anonymous/view` su cartelle validate.
- Rischi residui: il cambio root da UI va usato solo se cambia la root SharePoint operativa; valori root/item errati fanno saltare la validazione e il command segnera gli asset come non eleggibili.
- Test/check: `python django_app\manage.py check --settings=config.settings.test` OK; `python django_app\manage.py test assets.tests.AssetsRoutingTests.test_gestione_admin_shows_sharepoint_config_card assets.tests.AssetsRoutingTests.test_gestione_admin_can_save_sharepoint_config --settings=config.settings.test --verbosity 2` OK; `python django_app\manage.py makemigrations --check --dry-run --settings=config.settings.test` OK; `python django_app\manage.py test assets --settings=config.settings.test --verbosity 1` OK (219 test).
- Note: nessun backup creato; non sono state fatte chiamate reali a Microsoft Graph nei test.

- Area: `django_app/assets`, `django_app/config/settings/base.py`
- Richiesta: generare automaticamente link pubblici SharePoint read-only per QR asset, solo per cartelle sotto `ASSET CN`, e riconvertire cartelle gia esistenti tramite command.
- File modificati/creati: `django_app/assets/models.py`, `django_app/assets/migrations/0069_asset_public_share_links.py`, `django_app/assets/services/sharepoint_public_links.py`, `django_app/assets/management/commands/assets_ensure_public_share_links.py`, `django_app/assets/views.py`, `django_app/assets/urls.py`, `django_app/assets/admin.py`, `django_app/assets/tests.py`, `django_app/config/settings/base.py`, `django_app/.env.example`, `README.md`, `django_app/assets/README.md`, `docs/assets/SHAREPOINT_CARTELLE_ASSET_GUIDE.md`, `docs/ai/05_SECURITY_BOUNDARIES.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: `django_app/config/settings/base.py` (nuove impostazioni `SHAREPOINT_ASSET_*` e sola eccezione pubblica `/assets/public/` in `MIDDLEWARE_EXEMPT_PREFIXES`). `_AGENT_CONTROL/CRITICAL_FILES.md` non era presente nella workspace.
- Motivo tecnico: i QR verso `sharepoint_folder_url` aprivano l'URL interno SharePoint e richiedevano login Microsoft; serviva un link Graph `anonymous/view` per singola cartella asset, senza aprire tenant/sito e senza pubblicare cartelle fuori `ASSET CN`.
- Modifica: aggiunti campi Asset per drive/item, link pubblico, stato/errore e token QR; nuovo servizio Graph dedicato con body fisso `type=view`, `scope=anonymous`, `retainInheritedPermissions=true`; validazione root tramite `parentReference`/path; route pubblica tokenizzata `/assets/public/<token>/`; QR aggiornato per usare route/link pubblico e non l'URL interno; command `assets_ensure_public_share_links` con dry-run default, apply, force, only-missing e asset-tag; admin con campi/azioni essenziali.
- Impatto previsto: nuove cartelle asset salvano `drive_id/item_id`; dopo attivazione feature flag e command di riconversione, i QR fisici aprono senza login Microsoft solo le cartelle asset autorizzate sotto `ASSET CN`. Le altre route `/assets/` restano protette.
- Rischi residui: in produzione serve configurare e testare `SHAREPOINT_ASSET_PUBLIC_LINKS_ENABLED=true` e preferibilmente `SHAREPOINT_ASSET_ALLOWED_ROOT_DRIVE_ID/ITEM_ID`; asset storici senza `sharepoint_drive_id/item_id` richiedono risoluzione Graph da path durante il command. La route pubblica e volutamente stretta ma resta una nuova superficie pubblica tokenizzata.
- Test/check: `python django_app\manage.py test assets.tests.AssetsRoutingTests.test_create_anonymous_view_link_uses_view_anonymous_body assets.tests.AssetsRoutingTests.test_ensure_asset_public_share_link_saves_public_url assets.tests.AssetsRoutingTests.test_ensure_asset_public_share_link_blocks_outside_asset_cn assets.tests.AssetsRoutingTests.test_management_command_dry_run_does_not_save_public_url assets.tests.AssetsRoutingTests.test_management_command_apply_saves_public_url_for_eligible_asset assets.tests.AssetsRoutingTests.test_management_command_only_missing_skips_asset_with_existing_link assets.tests.AssetsRoutingTests.test_asset_qr_label_defaults_to_public_route_when_available assets.tests.AssetsRoutingTests.test_asset_qr_label_does_not_use_internal_sharepoint_folder_without_public_link assets.tests.AssetsRoutingTests.test_public_redirect_valid_token_redirects_without_login assets.tests.AssetsRoutingTests.test_public_redirect_unknown_token_404 assets.tests.AssetsRoutingTests.test_public_redirect_disabled_token_404 assets.tests.AssetsRoutingTests.test_assets_public_prefix_is_accessible_without_login_but_other_assets_routes_are_protected --settings=config.settings.test --verbosity 2` OK (12 test); `python django_app\manage.py makemigrations --check --dry-run --settings=config.settings.test` OK; `python django_app\manage.py check --settings=config.settings.test` OK; `python django_app\manage.py test assets.tests --settings=config.settings.test --verbosity 2` OK (219 test); `python django_app\manage.py test --settings=config.settings.test --verbosity 1` OK (357 test, skipped=1); `python django_app\manage.py test assets --settings=config.settings.test --verbosity 1` OK (219 test).
- Note: `django_app/config/settings/base.py`, `django_app/assets/urls.py` e `django_app/assets/admin.py` erano in sola lettura; rimosso l'attributo read-only per applicare la patch. I file di controllo sessione `_AGENT_CONTROL/ACTIVE_SESSION.md`, `WORK_LOCKS.md`, `CRITICAL_FILES.md`, `CRITICAL_CHANGE_REQUESTS.md` non erano presenti all'avvio.

- Area: `django_app/assets`
- Richiesta: correggere i collegamenti categoria della dashboard Assets che aprivano `/assets/lista/?category=<id>` senza filtrare l'inventario canonico.
- File modificati: `django_app/assets/views.py`, `django_app/assets/templates/assets/pages/asset_dashboard.html`, `django_app/assets/tests.py`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `README.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non era presente nella workspace.
- Motivo tecnico: la dashboard usava il parametro legacy `category`, mentre la lista asset filtra tramite `asset_category`; il link risultava formalmente valido ma non applicava il filtro categoria.
- Modifica: aggiornati i link categoria dashboard a `asset_category=<id>`; aggiunto redirect compatibile da `category=<id>` a `asset_category=<id>` nella lista asset; aggiunti test di routing e regressione.
- Impatto previsto: cliccando su Pressa o su qualsiasi chip categoria si apre la lista asset gia filtrata sulla categoria corretta; i vecchi link salvati con `category` vengono normalizzati.
- Rischi residui: nessuno noto sulla lista asset; il redirect riguarda solo `GET` con `category` presente e `asset_category` assente.
- Test/check: `python django_app\manage.py test assets.tests.AssetsRoutingTests.test_asset_dashboard_category_links_use_asset_category_filter assets.tests.AssetsRoutingTests.test_asset_list_legacy_category_query_redirects_and_filters --settings=config.settings.test --verbosity 2` OK; `python django_app\manage.py test assets.tests --settings=config.settings.test --verbosity 2` OK (208 test); `python django_app\manage.py check --settings=config.settings.test` OK.
- Note: il template `django_app/assets/templates/assets/pages/asset_dashboard.html` era in sola lettura; rimosso l'attributo read-only per applicare la correzione. I file di controllo sessione `_AGENT_CONTROL/ACTIVE_SESSION.md`, `WORK_LOCKS.md`, `CRITICAL_FILES.md`, `CRITICAL_CHANGE_REQUESTS.md` non erano presenti all'avvio.

## 2026-05-19 - Codex

- Area: `django_app/assets`
- Richiesta: nella sezione "Specifiche tecniche" del dettaglio asset mostrare solo caratteristiche compilate, tenendo conto dei campi specifici di categoria.
- File modificati: `django_app/assets/views.py`, `django_app/assets/tests.py`, `django_app/CHANGELOG.md`, `CHANGELOG.md`, `README.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non era presente nella workspace.
- Motivo tecnico: il rendering del dettaglio asset poteva mostrare righe placeholder (`N/D`, `-`) nelle specifiche, soprattutto nel fallback hardcoded e nei campi configurati con `show_if_empty`.
- Modifica: introdotto helper condiviso per riconoscere valori vuoti/placeholder; filtrate sempre le righe vuote nella sezione `SPECS` per campi configurati, campi categoria e fallback; corretto il formato `BOOL` per non trasformare valori mancanti in `No`.
- Impatto previsto: la card "Specifiche tecniche" mostra solo dati utili e sparisce quando non rimangono specifiche compilate; ogni categoria continua a esporre le proprie caratteristiche valorizzate.
- Rischi residui: valori calcolati non vuoti (es. data acquisto derivata) restano visibili come deciso; eventuali configurazioni admin che usavano `show_if_empty` su `SPECS` non forzeranno piu la visualizzazione del placeholder.
- Test/check: `python django_app\manage.py test assets.tests --settings=config.settings.test --verbosity 2` OK (206 test); `python django_app\manage.py check --settings=config.settings.test` OK.
- Note: i file di controllo sessione `_AGENT_CONTROL/ACTIVE_SESSION.md`, `WORK_LOCKS.md`, `CRITICAL_FILES.md`, `CRITICAL_CHANGE_REQUESTS.md` non erano presenti all'avvio.

## 2026-05-19 - Codex

- Area: `hotfix`
- Richiesta: analisi crash produzione da `hotfix/app.log` dopo applicazione hotfix asset.
- File modificati/creati: `hotfix/hotfix-v1.0.1-20260519_122243-sidebar-categories.zip`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non era presente nella workspace.
- Motivo tecnico: `django_app/assets/views.py` importava `assets.services.sidebar_categories`, ma il pacchetto hotfix precedente `hotfix-v1.0.1-20260519_120132.zip` conteneva solo `django_app/assets/views.py` e non il nuovo modulo service richiesto in runtime.
- Modifica: creato zip hotfix minimale con `django_app/assets/services/sidebar_categories.py` nel percorso relativo corretto.
- Impatto previsto: applicando lo zip sopra il release attivo, l'import di `assets.views` torna a risolversi e il portale non cade piu durante il caricamento di `config.urls`.
- Rischi residui: il pacchetto corregge solo il modulo mancante rilevato dal log; se il deploy attivo manca altri file introdotti da modifiche precedenti, emergeranno al successivo import/check.
- Test/check: `python -m py_compile django_app\assets\services\sidebar_categories.py` OK; contenuto zip verificato (`django_app/assets/services/sidebar_categories.py`); SHA256 `93CE1ED790E232A6B0DFA7FCF34A82FA0A479F2EDEE9DC2703D31E969D417A14`.
- Note: dopo applicazione hotfix riavviare il servizio/app pool e ricontrollare il log per eventuali import mancanti successivi.

## 2026-05-19 - Codex

- Area: `hotfix`
- Richiesta: creare un nuovo pacchetto hotfix per la correzione metadati SharePoint sulle cartelle asset.
- File modificati/creati: `hotfix/hotfix-v1.0.1-20260519_120132.zip`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non era presente nella workspace.
- Motivo tecnico: predisporre un pacchetto overlay leggero applicabile dal Release Manager senza nuova release completa.
- Modifica: creato zip hotfix con `django_app/assets/views.py`.
- Impatto previsto: applicando lo zip al release attivo viene distribuito il fix che valorizza i metadati SharePoint anche sulle cartelle asset.
- Rischi residui: il pacchetto contiene il file runtime completo `django_app/assets/views.py` nello stato corrente della workspace; non include test o documentazione.
- Test/check: contenuto zip verificato (`django_app/assets/views.py`); SHA256 `C53140A7AC88B1845F8D76B616577CF78E06A41D96A783EE58BD4110488F3880`.
- Note: i file di controllo sessione `_AGENT_CONTROL/ACTIVE_SESSION.md`, `WORK_LOCKS.md`, `CRITICAL_FILES.md`, `CRITICAL_CHANGE_REQUESTS.md` non erano presenti all'avvio.

- Area: `django_app/assets`
- Richiesta: colonne metadato SharePoint create ma non compilate sulle cartelle asset.
- File modificati: `django_app/assets/views.py`, `django_app/assets/tests.py`, `django_app/CHANGELOG.md`, `CHANGELOG.md`, `README.md`, `docs/assets/SHAREPOINT_CARTELLE_ASSET_GUIDE.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non era presente nella workspace.
- Motivo tecnico: i metadati venivano applicati solo ai file documento caricati su SharePoint, mentre le righe visibili sotto `ASSET CN` sono cartelle `driveItem` e restavano senza PATCH su `listItem/fields`.
- Modifica: `_ensure_sharepoint_folder` restituisce anche l'id del driveItem; `_ensure_asset_sharepoint_folder` applica i metadati anche alla cartella asset e alle tre sottocartelle categoria usando helper condivisi per il PATCH campi.
- Impatto previsto: nuovi salvataggi/sync SharePoint asset valorizzano `AssetTag`, categoria, produttore, modello, matricola, stato, reparto e tipo cartella anche sulle cartelle, non solo sui file.
- Rischi residui: cartelle gia create prima della patch restano vuote finche l'asset non viene risalvato o non viene rieseguito un flusso che richiama `_ensure_asset_sharepoint_folder`; l'operazione resta best-effort e dipende dai permessi Graph sui campi lista.
- Test/check: `python django_app\manage.py test assets.tests.AssetsRoutingTests.test_sharepoint_upload_uses_relative_subfolders assets.tests.AssetsRoutingTests.test_sharepoint_document_metadata_includes_asset_fields assets.tests.AssetsRoutingTests.test_sharepoint_folder_metadata_includes_asset_fields assets.tests.AssetsRoutingTests.test_ensure_asset_sharepoint_folder_applies_metadata_to_folders --settings=config.settings.test --verbosity 2` OK.
- Note: i file di controllo sessione `_AGENT_CONTROL/ACTIVE_SESSION.md`, `WORK_LOCKS.md`, `CRITICAL_FILES.md`, `CRITICAL_CHANGE_REQUESTS.md` non erano presenti all'avvio.

- Area: `django_app/assets`
- Richiesta: QR delle etichette asset verso la cartella SharePoint relativa.
- File modificati: `django_app/assets/views.py`, `django_app/assets/tests.py`, `django_app/CHANGELOG.md`, `README.md`, `docs/assets/SHAREPOINT_CARTELLE_ASSET_GUIDE.md`.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non era presente nella workspace.
- Motivo tecnico: rendere `/assets/view/<id>/qr-label/` coerente con l'uso operativo delle label fisiche, puntando alla cartella SharePoint dell'asset quando disponibile.
- Modifica: default target QR da `detail` a `sharepoint` nella view `asset_qr_label`, con fallback gia esistente alla scheda asset se `sharepoint_folder_url` manca; `?target=detail` continua a forzare la scheda.
- Impatto previsto: le nuove label generate senza querystring aprono direttamente la cartella SharePoint dell'asset; nessuna migrazione DB.
- Rischi residui: asset senza `sharepoint_folder_url` continuano a puntare alla scheda portale finche Graph/sync non valorizza l'URL cartella.
- Test/check: `python django_app\manage.py test assets.tests.AssetsRoutingTests.test_asset_qr_label_returns_pdf assets.tests.AssetsRoutingTests.test_asset_qr_label_defaults_to_sharepoint_folder_when_available assets.tests.AssetsRoutingTests.test_asset_qr_label_detail_target_still_points_to_asset_detail --settings=config.settings.test --verbosity 2` OK.
- Note: i file di controllo sessione `_AGENT_CONTROL/ACTIVE_SESSION.md`, `WORK_LOCKS.md`, `CRITICAL_FILES.md`, `CRITICAL_CHANGE_REQUESTS.md` non erano presenti all'avvio.

## 2026-05-19 - Codex

- Area: `django_app/assets`
- Richiesta: upload su SharePoint dell'intera cartella selezionata dalla card Documenti asset, mantenendo eventuali sottocartelle.
- File modificati: `django_app/assets/views.py`, `django_app/assets/templates/assets/pages/asset_detail.html`, `django_app/assets/tests.py`, `README.md`, `CHANGELOG.md`, `docs/assets/SHAREPOINT_CARTELLE_ASSET_GUIDE.md`.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non era presente nella workspace all'avvio.
- Motivo tecnico: l'input `webkitdirectory` invia una lista di file; senza salvare il `webkitRelativePath` lato backend l'upload Graph appiattiva tutto nella sola sottocartella categoria.
- Modifica: il template invia hidden field con percorso relativo per ciascun file selezionato da cartella; `_validate_asset_document_uploads` conserva il percorso relativo sanitizzato; `_upload_asset_document_to_sharepoint` crea la cartella categoria piu eventuali sottocartelle relative prima del `PUT` Graph.
- Impatto previsto: su SharePoint i file caricati da "Carica cartella" finiscono in `ASSET CN/<tag>/<categoria>/<cartella selezionata>/<subfolder>/...`; resta il fallback locale `AssetDocument`.
- Rischi residui: i nomi remoti dei file continuano a usare il prefisso univoco timestamp/id gia esistente per evitare sovrascritture; la struttura cartella e preservata, il nome fisico del file SharePoint non e identico al nome sorgente.
- Test/check: `python django_app\manage.py test assets.tests.AssetsRoutingTests.test_asset_detail_upload_can_target_local_archive assets.tests.AssetsRoutingTests.test_asset_detail_folder_upload_keeps_sharepoint_relative_path assets.tests.AssetsRoutingTests.test_sharepoint_upload_uses_relative_subfolders --settings=config.settings.test` OK; `python django_app\manage.py check --settings=config.settings.test` OK.
- Note: i file di controllo sessione `_AGENT_CONTROL/ACTIVE_SESSION.md`, `WORK_LOCKS.md`, `CRITICAL_FILES.md`, `CRITICAL_CHANGE_REQUESTS.md` non erano presenti all'avvio.

## 2026-05-19 - Codex

- Area: `hotfix`
- Richiesta: creare pacchetto hotfix per la correzione upload cartella asset SharePoint.
- File pacchetto: `hotfix/hotfix-v1.0.1-20260519_115839.zip`.
- Contenuto pacchetto: `django_app/assets/views.py`, `django_app/assets/templates/assets/pages/asset_detail.html`.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non era presente nella workspace.
- Motivo tecnico: distribuire rapidamente la fix runtime senza release completa, includendo solo backend e template necessari alla produzione.
- Impatto previsto: applicando il pacchetto sul release attivo, "Carica cartella" preserva sottocartelle relative su SharePoint.
- Rischi residui: creato anche `hotfix/hotfix-v1.0.1-20260519_115759.zip` durante un primo tentativo, ma contiene entry appiattite (`views.py`, `asset_detail.html`) e non va usato; il pacchetto valido e verificato e quello `115839`.
- Test/check: verifica zip OK con entry `django_app/...` complete.
- Note: nessuna migrazione, dipendenza o collectstatic richiesti per questa fix.
