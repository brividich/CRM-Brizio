# Agent Changelog

## 2026-08-05 - Codex

- Area: `django_app/assets`, form nuovo intervento.
- Richiesta: rendere comprensibile la schermata `/assets/workorders/new/<asset>/?source=workorder_list`, utilizzabile sia per guasto sia per manutenzione pianificata; lasciare la risoluzione compilabile subito.
- File modificati: `django_app/assets/views.py`, `django_app/assets/templates/assets/pages/workorder_form.html`, `django_app/assets/tests.py`, `django_app/assets/README.md`, `README.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno; `_AGENT_CONTROL/CRITICAL_FILES.md` non e' presente. Nessuna modifica ad ACL, middleware, settings, autenticazione, permessi, URL, routing globale o navigazione globale.
- Motivo tecnico: il form esponeva prima del titolo regola, manutenzione periodica, fornitore e contratto; mostrava inoltre breadcrumb, tab e azioni globali durante la compilazione, senza gerarchia tra dati essenziali e avanzati.
- Modifica: sotto-nav rimossa server-side per questa view; contesto asset reso esplicito; flusso guidato `Cosa devi registrare?` e `Impatto operativo`; titolo e descrizione anticipati; risoluzione visibile e opzionale; allegati separati; dettagli manutentivi/contrattuali raccolti in `Pianificazione e copertura`, con apertura automatica per tipo preventivo, regola/contratto precompilati o errori.
- Impatto previsto: compilazione piu rapida e leggibile per guasti e manutenzioni pianificate, senza variazioni ai dati salvati o ai flussi backend.
- Rischi residui: verifica visuale autenticata non eseguita tramite browser integrato, non esposto nella sessione; la resa e coperta da render test e template check.
- Test/check: `manage.py check assets` OK; template load OK; test UI guidata OK; test prefill da scadenzario e creazione preventiva con fornitore/allegato OK; `git diff --check` OK.
- Backup creati: nessuno.
- README/CHANGELOG: aggiornati `README.md`, `django_app/assets/README.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`.
- Note operative: lavoro isolato nel worktree `C:\Dev\pn-assets-workorder-form-ux`; modifiche locali non correlate del checkout condiviso preservate.

## 2026-08-05 - Codex

- Area: `django_app/assets`.
- Richiesta: rendere `Asset -> Manutenzione` molto piu fruibile, eliminando la sensazione di pagina costruita per accumulo.
- File modificati in questa sessione: `django_app/assets/views.py`, `django_app/assets/templates/assets/pages/maintenance_hub.html`, `django_app/assets/tests.py`, `django_app/assets/README.md`, `README.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno; `_AGENT_CONTROL/CRITICAL_FILES.md` non e' presente nella workspace. Nessuna modifica a ACL, middleware, settings, autenticazione, permessi, routing globale o navigazione globale.
- Motivo tecnico: l'hub mostrava in sequenza un cruscotto condiviso a due pannelli, sei KPI, filtri, molte card operative e un rail di azioni che duplicava toolbar e sotto-navigazione; gerarchia e percorsi competevano sullo stesso livello.
- Modifica: introdotta una sola fascia compatta di priorita (interventi aperti, scaduti, attivita in avvicinamento, completati); aggiunta intestazione `Lavoro operativo`; mantenuti filtri, OdL, scadenze, regole, macchine e ticket; rail ridotto a `Agenda 7 giorni` con link ai registri; rimosso dall'hub il partial del cruscotto condiviso e il relativo calcolo di aggregazioni inutilizzate. Il cruscotto Assets continua a usare il partial invariato.
- Impatto previsto: meno duplicazioni, ordine di lettura immediato e azioni globali in un solo punto; nessun cambiamento a dati o flussi operativi.
- Rischi residui: verifica visuale autenticata non eseguita perche' il runtime browser richiesto dal plugin non era esposto; rendering e struttura coperti dai test Django. Resta un warning test preesistente su `WorkOrder.closed_at` naive, non introdotto dalla modifica.
- Test/check: `python -B django_app\manage.py check assets --settings=config.settings.test` OK; test mirati su gerarchia UX, sotto-navigazione e regole critiche OK (3 test); rerun finale dopo rimozione query inutilizzate OK (2 test); `git diff --check` OK.
- Backup creati: nessuno.
- README/CHANGELOG: `README.md`, `django_app/assets/README.md`, `CHANGELOG.md` e `django_app/CHANGELOG.md` aggiornati.
- Note operative: lavoro isolato nel worktree `C:\Dev\pn-assets-maintenance-ux`, branch `feature/assets-maintenance-ux`; il checkout condiviso aveva modifiche preesistenti non correlate (`docs/prompt-claude-code-rag-sgi-ampliamento.md`, `remediation-plan.md`) che non sono state toccate.

## 2026-06-17 - Codex

- Area: `django_app/admin_portale`, `django_app/core`, gestione template PDF condiviso.
- Richiesta: creare una pagina da cui gestire il template grafico PDF comune del portale.
- File modificati in questa sessione: `django_app/core/pdf.py`, `django_app/admin_portale/views.py`, `django_app/admin_portale/urls.py`, `django_app/admin_portale/templates/admin_portale/pages/index.html`, `django_app/admin_portale/templates/admin_portale/pages/pdf_template_config.html`, `django_app/admin_portale/tests.py`, `README.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno elencato, perche' `_AGENT_CONTROL/CRITICAL_FILES.md` non e' presente nella workspace. Sono stati modificati `django_app/core/pdf.py` (area core) e file `admin_portale` su richiesta esplicita dell'utente. Aggiunte route interne al namespace `admin_portale`; nessuna modifica a ACL, middleware, settings, autenticazione, permessi, routing globale o navigazione globale.
- Motivo tecnico: il template PDF condiviso esisteva lato codice, ma logo/colori/footer potevano essere variati solo modificando branding o codice; serviva un punto amministrativo chiaro.
- Modifica: `core.pdf` legge nuove chiavi `SiteConfig` `pdf_template_*` per logo PDF, colori primario/accento, footer, data/ora e numerazione; `PdfTheme` applica queste preferenze con fallback al branding portale. Aggiunta pagina `/admin-portale/pdf-template/` con form, mini anteprima e pulsante **Anteprima PDF** verso `/admin-portale/pdf-template/preview/`, che genera inline un PDF dimostrativo reale con il template salvato. Salvataggio validato con upload PNG/JPG in `media/pdf_template/`, card nella sezione Configurazione dell'Admin Portale e audit `pdf_template_config_save`. Aggiunti test su render, salvataggio, preview PDF e uso delle impostazioni nel tema PDF.
- Impatto previsto: gli admin possono gestire da UI la grafica comune dei PDF senza toccare il codice; tutti i PDF gia migrati a `core.pdf` ereditano automaticamente le preferenze salvate.
- Rischi residui: i PDF non ancora migrati a `core.pdf` e le superfici print/browser restano fuori da questa console; la resa visuale va verificata con loghi reali molto larghi o molto alti.
- Test/check: parsing in memoria OK su `django_app/core/pdf.py`, `django_app/admin_portale/views.py`, `django_app/admin_portale/urls.py`, `django_app/admin_portale/tests.py` usando `utf-8-sig`; primo `py_compile` non usato per `Accesso negato` su `django_app/admin_portale/__pycache__`; `python -B django_app\manage.py test admin_portale.tests.AdminPortalePdfTemplateConfigTests --settings=config.settings.test --verbosity 1 --keepdb` OK; `python -B django_app\manage.py check --settings=config.settings.test` OK.
- Backup creati: nessuno.
- README/CHANGELOG: `README.md`, `CHANGELOG.md` e `django_app/CHANGELOG.md` aggiornati.
- Note operative: workspace gia' sporca con molte modifiche preesistenti non correlate, incluse aree Anagrafica/Assets e file non tracciati; non sono state revertite. `_AGENT_CONTROL/ACTIVE_SESSION.md`, `WORK_LOCKS.md`, `CRITICAL_FILES.md` e `CRITICAL_CHANGE_REQUESTS.md` non presenti nella workspace.

## 2026-06-16 - Codex

- Area: `django_app/assets`, hub manutenzione / report / registro OdL.
- Richiesta: proseguire con i successivi step di fruizione del modulo Assets.
- File modificati in questa sessione: `django_app/assets/views.py`, `django_app/assets/templates/assets/pages/maintenance_hub.html`, `django_app/assets/templates/assets/pages/reports_dashboard.html`, `django_app/assets/templates/assets/pages/workorder_list.html`, `django_app/assets/tests.py`, `README.md`, `django_app/assets/README.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno elencato, perche' `_AGENT_CONTROL/CRITICAL_FILES.md` non e' presente nella workspace. Nessuna modifica a ACL, middleware, settings, autenticazione, permessi, routing globale o navigazione globale.
- Motivo tecnico: dopo la sotto-nav e le azioni contestuali, KPI e riepiloghi restavano ancora punti informativi non sempre navigabili; l'utente doveva ricostruire manualmente filtri e perimetro nel registro OdL o nello scadenzario.
- Modifica: aggiunto helper `_workorder_list_page_url` per generare link coerenti alla lista OdL. I KPI dell'hub manutenzione sono ora link verso OdL aperti/chiusi, scadenzario per scadenze/verifiche/contratti e prossime manutenzioni. La dashboard report linka PM compliance, aperti oltre 30 giorni, scadenze critiche, senza baseline e budget/chiusi ai relativi registri filtrati; le righe Budget vs actual hanno una colonna `Registro` verso gli OdL della categoria. Il filtro `Aperti da almeno` della lista OdL include `21 giorni`, soglia usata dall'hub per gli aperti in ritardo. Estese regressioni su report, hub e lista OdL.
- Impatto previsto: dai numeri di sintesi si passa direttamente al dettaglio operativo gia filtrato, riducendo click e ricostruzione manuale del contesto.
- Rischi residui: verifica visuale autenticata non completata; smoke HTTP arriva al login come atteso e Playwright diretto ha restituito backend/browser chiuso. Possibili micro-regolazioni visuali con dati reali e sessione autenticata.
- Test/check: `python -B django_app\manage.py test assets.tests.AssetsRoutingTests.test_reports_dashboard_shows_pm_compliance_and_budget_vs_actual --settings=config.settings.test --verbosity 1 --keepdb --noinput` OK; `python -B django_app\manage.py test assets.tests.WorkOrderFlowTests.test_maintenance_hub_shows_critical_rule_rows assets.tests.WorkOrderFlowTests.test_workorder_list_filters_show_operational_columns --settings=config.settings.test --verbosity 1 --keepdb --noinput` OK; `python -B django_app\manage.py shell --settings=config.settings.test -c "...get_template..."` OK sui tre template toccati; `python -B django_app\manage.py check assets --settings=config.settings.test` OK; `git diff --check` OK; smoke HTTP su `/assets/reports/?scope=production` OK fino a `302` login con `next`.
- Backup creati: nessuno.
- README/CHANGELOG: `README.md`, `django_app/assets/README.md`, `CHANGELOG.md` e `django_app/CHANGELOG.md` aggiornati.
- Note operative: workspace gia' sporca con modifiche preesistenti non correlate; non sono state revertite. I primi lanci test sono andati in timeout durante preparazione/migrazioni DB test, poi rilanciati con timeout piu ampio e completati OK.

## 2026-06-16 - Codex

- Area: `django_app/assets`, navigazione manutenzione / registro interventi.
- Richiesta: continuare autonomamente i prossimi step di fruizione e navigabilita del modulo Assets, senza attendere ulteriori conferme.
- File modificati in questa sessione: `django_app/assets/views.py`, `django_app/assets/templates/assets/base_shell.html`, `django_app/assets/templates/assets/pages/workorder_list.html`, `django_app/assets/tests.py`, `README.md`, `django_app/assets/README.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno elencato, perche' `_AGENT_CONTROL/CRITICAL_FILES.md` non e' presente nella workspace. `django_app/assets/templates/assets/base_shell.html` impatta la navigazione locale del modulo Assets, modifica coerente con la richiesta esplicita. Nessuna modifica a ACL, middleware, settings, autenticazione, permessi, routing globale o navigazione globale.
- Motivo tecnico: la subnav manutenzione orientava gia' l'utente, ma mancavano azioni contestuali stabili e un riepilogo immediato dei filtri applicati nel registro OdL.
- Modifica: `_assets_section_nav` espone ora azioni rapide `Nuovo intervento`, `Esporta OdL` e `Impostazioni`, renderizzate dalla shell Assets accanto ai tab. La lista `/assets/workorders/` apre automaticamente i dialog esistenti quando arriva da `?create=1` o `?export=1`. Aggiunti helper view per costruire chip dei filtri attivi e URL di rimozione puntuale; il template mostra i chip sotto il form filtri con link `Rimuovi tutti`. Estesa la regressione sulla subnav e quella sul registro interventi.
- Impatto previsto: l'utente puo' creare/esportare OdL da qualsiasi sezione manutenzione senza cercare la toolbar giusta; nel registro interventi capisce subito quali filtri sono attivi e puo' rimuoverli uno alla volta.
- Rischi residui: verifica visuale autenticata non completata per assenza di sessione nel browser tool; Playwright e smoke HTTP arrivano correttamente al login preservando `next`. Possibili micro-regolazioni visuali con dati reali o viewport piccoli.
- Test/check: `python -B django_app\manage.py test assets.tests.AssetsRoutingTests.test_maintenance_pages_share_section_navigation assets.tests.WorkOrderFlowTests.test_workorder_list_filters_show_operational_columns --settings=config.settings.test --verbosity 1 --keepdb` OK; `python -B django_app\manage.py check assets --settings=config.settings.test` OK; `git diff --check` OK; smoke HTTP `curl.exe -I` su `/assets/workorders/?status=DONE&origin=PERIODIC&coverage=covered&q=Tagliando` OK fino a `302` login; Playwright su `/assets/workorders/?create=1` OK fino a redirect login con `next`.
- Backup creati: nessuno.
- README/CHANGELOG: `README.md`, `django_app/assets/README.md`, `CHANGELOG.md` e `django_app/CHANGELOG.md` aggiornati.
- Note operative: workspace gia' sporca con molte modifiche preesistenti non correlate, incluse aree Anagrafica e file non tracciati; non sono state revertite. Step 2 e step 3 completati.

## 2026-06-16 - Codex

- Area: `django_app/assets`, navigazione manutenzione / report / interventi.
- Richiesta: proseguire step by step con migliorie di fruizione e navigabilita tra le sezioni del modulo Assets.
- File modificati in questa sessione: `django_app/assets/views.py`, `django_app/assets/templates/assets/base_shell.html`, `django_app/assets/tests.py`, `README.md`, `django_app/assets/README.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno elencato, perche' `_AGENT_CONTROL/CRITICAL_FILES.md` non e' presente nella workspace. Nessuna modifica a ACL, middleware, settings, autenticazione, permessi, routing globale o navigazione globale.
- Motivo tecnico: manutenzione, scadenzario, lista OdL, report e template report erano raggiungibili ma percepiti come pagine separate; serviva un orientamento stabile nel contenuto, oltre alla sidebar.
- Modifica: aggiunta `_assets_section_nav` in `assets/views.py`, integrata in `_assets_shell_context`, per generare una sotto-navigazione comune solo sulle route manutenzione/report/interventi. `assets/base_shell.html` renderizza breadcrumb `Assets / Manutenzione / ...` e tab `Da fare`, `Scadenzario`, `Interventi`, `Report`, `Template report`, `Impostazioni`, con stato attivo. Aggiunta regressione su hub manutenzione, scadenzario, lista OdL e gestione template report. Documentati README e changelog.
- Impatto previsto: l'utente resta nello stesso contesto operativo quando passa da cose da fare, scadenzario, interventi, report e configurazioni; meno ritorni manuali e meno disorientamento tra sezioni.
- Rischi residui: verifica browser autenticata non completata per backend Playwright chiuso e assenza di sessione loggata; possibile rifinitura visuale dopo prova reale su schermi stretti o sidebar molto lunga.
- Test/check: `python -B django_app\manage.py test assets.tests.AssetsRoutingTests.test_maintenance_pages_share_section_navigation assets.tests.AssetsRoutingTests.test_superuser_can_access_report_template_admin_page --settings=config.settings.test --verbosity 1 --keepdb` OK; `python -B django_app\manage.py check assets --settings=config.settings.test` OK; `git diff --check` OK; runserver locale avviato su `http://127.0.0.1:8000/`; smoke HTTP su `/assets/manutenzione/` OK fino a `302` login; apertura Playwright non completata per backend browser chiuso.
- Backup creati: nessuno.
- README/CHANGELOG: `README.md`, `django_app/assets/README.md`, `CHANGELOG.md` e `django_app/CHANGELOG.md` aggiornati.
- Note operative: step 1 completato. Prossimo step naturale: azioni contestuali piu coerenti nelle toolbar e link dai KPI/report verso liste gia filtrate.

## 2026-06-16 - Codex

- Area: `django_app/assets`, gestione template report.
- Richiesta: rendere centrale anche il form del report nella pagina di amministrazione template report.
- File modificati in questa sessione: `django_app/assets/templates/assets/pages/report_template_admin.html`, `django_app/assets/tests.py`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno elencato, perche' `_AGENT_CONTROL/CRITICAL_FILES.md` non e' presente nella workspace. Nessuna modifica a ACL, middleware, settings, autenticazione, permessi, routing globale o navigazione globale.
- Motivo tecnico: la pagina `/assets/reports/manage/` trattava i form come contenuto largo di pagina, con composizione meno ordinata per un'operazione di data-entry.
- Modifica: introdotto uno stack form centrato (`rta-form-stack`) largo al massimo 920px dentro una pagina a 1180px; i due form operativi (**Report gestiti** e **Nuovo template**) usano card dedicate, griglia a due colonne e azioni finali allineate; la lista consultiva dei report e' separata sotto in una card distinta. Aggiunta regressione sul render delle classi e dei vincoli di centratura.
- Impatto previsto: la gestione dei template report risulta piu leggibile e coerente con i form operativi centrati del modulo, senza cambiare campi, validazioni, dati o URL.
- Rischi residui: verifica browser autenticata non completata per assenza di sessione nel tool; copertura affidata a render test Django e check modulo. Possibili micro-regolazioni visuali con dati reali molto lunghi.
- Test/check: `python -B django_app\manage.py test assets.tests.AssetsRoutingTests.test_superuser_can_access_report_template_admin_page --settings=config.settings.test --verbosity 1 --keepdb` OK; `python -B django_app\manage.py check assets --settings=config.settings.test` OK; `git diff --check` OK; Playwright su `http://127.0.0.1:8000/assets/reports/manage/` verificato fino a redirect `/login/?next=%2Fassets%2Freports%2Fmanage%2F`.
- Backup creati: nessuno.
- README/CHANGELOG: `CHANGELOG.md` e `django_app/CHANGELOG.md` aggiornati; README non aggiornato perche' non cambiano URL, setup, dipendenze o documentazione operativa.
- Note operative: workspace gia' sporca con modifiche preesistenti non correlate; non sono state revertite.

## 2026-06-16 - Codex

- Area: `django_app/assets`, manutenzione / work order.
- Richiesta: proseguire con il miglioramento del modulo asset - manutenzione, senza occuparsi per ora di ricambi/magazzino.
- File modificati in questa sessione: `django_app/assets/forms.py`, `django_app/assets/models.py`, `django_app/assets/views.py`, `django_app/assets/templates/assets/pages/maintenance_hub.html`, `django_app/assets/templates/assets/pages/workorder_list.html`, `django_app/assets/templates/assets/pages/workorder_close.html`, `django_app/assets/templates/assets/pages/workorder_detail.html`, `django_app/assets/tests.py`, `README.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `django_app/assets/README.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno elencato, perche' `_AGENT_CONTROL/CRITICAL_FILES.md` non e' presente nella workspace. Nessuna modifica a ACL, middleware, settings, autenticazione, permessi, routing globale o navigazione globale.
- Motivo tecnico: hub manutenzione e lista OdL mostravano dati importanti ma non abbastanza operativi per capire subito quali regole richiedono attenzione, filtrare lo storico per reparto/copertura/responsabile e registrare in chiusura costi e allegati finali.
- Modifica: l'hub `/assets/manutenzione/` calcola le regole manutenzione effettive dallo stesso motore dello scadenzario e mostra le righe critiche (scadute, in warning o con prima esecuzione mancante) con azione diretta verso creazione OdL o baseline asset. La lista `/assets/workorders/` usa filtri aggiuntivi (origine, copertura, reparto, categoria, assegnato/eseguito da, anzianita apertura), tabella registro con asset/reparto/categoria, responsabili, copertura, tempi e costi, ed export XLSX/PDF coerente con il perimetro filtrato. La chiusura OdL registra costi manodopera/materiali/totale, allegati finali e persiste anche `assigned_to`/`executed_by`.
- Impatto previsto: la manutenzione programmata diventa visibile anche prima della creazione dell'OdL; il registro interventi e' piu consultabile e filtrabile; la chiusura produce dati economici e allegati utili per consuntivi/report.
- Rischi residui: la verifica browser autenticata non e' stata possibile dal tool, che arriva al login; i test Django coprono render e flussi autenticati. Il template `maintenance_hub.html` contiene encoding storico mojibake preesistente; le righe nuove usano entita HTML dove necessario.
- Test/check: parsing AST in memoria OK su `assets/forms.py`, `assets/models.py`, `assets/views.py`, `assets/tests.py`; primo `py_compile` non usato per `Accesso negato` su `django_app/assets/__pycache__` con runserver attivi; `python -B django_app\manage.py test assets.tests.WorkOrderFlowTests.test_close_workorder_records_costs_assignee_and_attachments assets.tests.WorkOrderFlowTests.test_workorder_list_filters_show_operational_columns assets.tests.WorkOrderFlowTests.test_workorder_export_uses_filtered_scope_and_operational_columns assets.tests.WorkOrderFlowTests.test_maintenance_hub_shows_critical_rule_rows --settings=config.settings.test --verbosity 1 --keepdb` OK; `python -B django_app\manage.py test assets.tests.AssetMeterScheduleTests.test_workorder_close_snapshots_current_meter_value assets.tests.AssetMeterScheduleTests.test_sync_snapshots_meter_value_for_recorded_execution assets.tests.WorkOrderFlowTests.test_workorder_with_rule_and_contract_syncs_execution_state_only_on_close --settings=config.settings.test --verbosity 1 --keepdb` OK; `python -B django_app\manage.py check assets --settings=config.settings.test` OK; `git diff --check` OK; fallback Playwright su `http://127.0.0.1:8000/assets/manutenzione/` verificato fino a redirect login.
- Backup creati: nessuno.
- README/CHANGELOG: `README.md`, `django_app/assets/README.md`, `CHANGELOG.md` e `django_app/CHANGELOG.md` aggiornati.
- Note operative: workspace gia' sporca con molte modifiche preesistenti non correlate; non sono state revertite. Il primo lancio dei test mirati e' andato in timeout mentre erano attivi altri processi test/check; rilanci successivi OK.

## 2026-06-16 - Codex

- Area: `django_app/core`, `django_app/assets`, template grafico PDF condiviso.
- Richiesta: rendere fattibile un template PDF unico almeno per la parte grafica, da cui far dipendere gli altri PDF.
- File modificati in questa sessione: `django_app/core/pdf.py`, `django_app/assets/views.py`, `django_app/assets/tests.py`, `README.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno elencato, perche' `_AGENT_CONTROL/CRITICAL_FILES.md` non e' presente nella workspace. E' stato modificato `django_app/core/pdf.py` (area core) su richiesta esplicita dell'utente per centralizzare la grafica PDF; nessuna modifica a ACL, middleware, settings, autenticazione, permessi, routing globale o navigazione globale.
- Motivo tecnico: `core.pdf` centralizzava gia' il layout ReportLab/Platypus usato dai PDF DPI, ma i PDF Assets disegnati su canvas e gli export tabellari avevano ancora header/footer, palette e metadati hardcodati localmente.
- Modifica: aggiunti in `core.pdf` helper canvas `draw_canvas_header` e `draw_canvas_footer`, riusati anche da `header_footer_callback`; gli export PDF tabellari Assets usano ora `PdfTheme`, `make_document`, `header_footer_callback` e `data_table`; il report PDF scheda asset e il report mensile manutenzioni macchine ricevono `PdfTheme.from_branding()` dalla view e usano header/footer/palette condivisi. Aggiunta regressione `test_asset_list_export_pdf_returns_shared_template_pdf`.
- Impatto previsto: inventario asset, export OdL, export macchine, scheda PDF asset e report mensile manutenzioni condividono logo/monogramma, nome portale, colori, header/footer e paginazione con il template PDF centrale, senza cambiare dati, URL, permessi o formati di risposta.
- Rischi residui: i PDF HTML/print browser e le etichette QR personalizzate restano fuori da questa prima migrazione perche' usano superfici grafiche diverse; eventuali micro-regolazioni visuali vanno verificate con dati reali molto lunghi.
- Test/check: parsing in memoria OK su `django_app/core/pdf.py` e `django_app/assets/views.py`; primo `py_compile` non usato per `Accesso negato` su `django_app/assets/__pycache__`; `python -B django_app\manage.py test assets.tests.AssetsRoutingTests.test_asset_list_export_pdf_returns_shared_template_pdf assets.tests.AssetsRoutingTests.test_work_machine_maintenance_month_pdf_returns_pdf assets.tests.AssetsRoutingTests.test_asset_report_pdf_returns_pdf assets.tests.AssetsRoutingTests.test_asset_report_pdf_skips_template_query_when_table_is_unavailable --settings=config.settings.test --verbosity 1 --keepdb` OK; `python -B django_app\manage.py check assets --settings=config.settings.test` OK; `git diff --check -- django_app\core\pdf.py django_app\assets\views.py django_app\assets\tests.py` OK.
- Backup creati: nessuno.
- README/CHANGELOG: `README.md`, `CHANGELOG.md` e `django_app/CHANGELOG.md` aggiornati.
- Note operative: workspace gia' sporca con molte modifiche preesistenti non correlate; non sono state revertite.

## 2026-06-15 - Codex

- Area: `django_app/assets`, form nuovo intervento / work order.
- Richiesta: sistemare la UI di `/assets/workorders/new/307/?source=workorder_list`.
- File modificati in questa sessione: `django_app/assets/maintenance.py`, `django_app/assets/views.py`, `django_app/assets/templates/assets/pages/workorder_form.html`, `django_app/assets/tests.py`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno; `_AGENT_CONTROL/CRITICAL_FILES.md` non e' presente nella workspace. Nessuna modifica a ACL, middleware, settings, autenticazione, permessi, routing globale o navigazione globale.
- Motivo tecnico: il form OdL aperto dalla lista interventi veniva trattato come apertura manuale generica, tornava alla scheda asset e usava una composizione troppo grande/da landing page per un'operazione di data entry.
- Modifica: `source=workorder_list` e' ora una sorgente riconosciuta con label `Lista interventi`; la view passa `workorder_back_url`/`workorder_back_label` coerenti; il template form OdL nasconde la search/topbar della shell su questa pagina, riduce l'header modulo, elimina hero/card contesto grandi, usa una sola striscia asset bassa e passa a un layout da data-entry a due colonne fino a 1180px: dati principali a sinistra, descrizione/risoluzione e allegati a destra, checkbox copertura reso compatto, pulsante Annulla verso la lista quando si arriva da li e niente icona allegato emoji. Aggiunta regressione sul render del form dalla lista.
- Impatto previsto: aprendo un nuovo intervento dalla lista OdL si resta nel flusso operativo corretto, con meno scroll e una UI piu ordinata senza cambiare campi, validazioni o logica di creazione.
- Rischi residui: verifica browser autenticata non eseguita; il fallback Playwright raggiunge il redirect login. Layout validato con test/template load. Potrebbero servire micro-regolazioni visuali dopo prova reale su campi con etichette molto lunghe.
- Test/check: `python -B django_app\manage.py test assets.tests.WorkOrderFlowTests.test_workorder_create_from_list_uses_compact_ui_and_back_link --settings=config.settings.test --verbosity 1 --keepdb` OK; template load `assets/pages/workorder_form.html` e `assets/pages/workorder_list.html` OK; `python -B django_app\manage.py check assets --settings=config.settings.test` OK; `git diff --check` sui file toccati OK; `rg` conferma assenza dei vecchi blocchi larghi (`wof-hero`, `wof-side-card`, `wof-backlink`), del font display, dell'icona allegato emoji e della precedente larghezza stretta, e presenza di `max-width: 1180px` con sezioni `wof-section--main`, `wof-section--notes`, `wof-section--attachments`. Fallback Playwright su `http://10.0.0.79:8000/assets/workorders/new/307/?source=workorder_list` verificato fino a redirect `/login/?next=...` per assenza di sessione autenticata nel tool.
- Backup creati: nessuno.
- README/CHANGELOG: `CHANGELOG.md` e `django_app/CHANGELOG.md` aggiornati; README non aggiornato perche' non cambiano URL/setup/dipendenze o documentazione operativa.

- Area: `django_app/assets`, interventi / work order.
- Richiesta: inserire il tasto `+ Nuovo intervento` nella pagina `/assets/workorders/`.
- File modificati in questa sessione: `django_app/assets/views.py`, `django_app/assets/templates/assets/pages/workorder_list.html`, `django_app/assets/tests.py`, `README.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno; `_AGENT_CONTROL/CRITICAL_FILES.md` non e' presente nella workspace. Nessuna modifica a ACL, middleware, settings, autenticazione, permessi, routing globale o navigazione globale.
- Motivo tecnico: il form `workorder_create` richiede un asset; la route globale `/assets/workorders/new/` senza asset tornava alla lista, quindi un pulsante diretto senza scelta asset sarebbe stato inutilizzabile.
- Modifica: la lista interventi mostra un pulsante `+ Nuovo intervento` con dialog centrale, backdrop e ricerca live su tag/nome/reparto; la view `workorder_create` accetta `asset=<id>` e reindirizza al form esistente `/assets/workorders/new/<id>/`, preservando parametri come `kind` e aggiungendo `source=workorder_list` quando manca. Aggiunte regressioni su CTA/dialog ricercabile e redirect.
- Impatto previsto: da `/assets/workorders/` si puo aprire un nuovo OdL senza passare manualmente dalla scheda asset, mantenendo comunque il vincolo che ogni intervento sia collegato a un bene.
- Rischi residui: il dialog renderizza lato pagina gli asset non dismessi; se il catalogo diventasse molto grande potrebbe essere utile sostituire la lista filtrata client-side con autocomplete server-side. Verifica browser autenticata non eseguita in questa tranche.
- Test/check: `python -B django_app\manage.py test assets.tests.WorkOrderFlowTests.test_workorder_list_exposes_new_intervention_selector assets.tests.WorkOrderFlowTests.test_global_workorder_create_redirects_to_selected_asset_form --settings=config.settings.test --verbosity 1 --keepdb` OK; `python -B django_app\manage.py check assets --settings=config.settings.test` OK; template load `assets/pages/workorder_list.html` OK; `git diff --check` sui file toccati OK. Dopo la rifinitura del dialog centrale con ricerca, test/check rilanciati OK. Primo lancio test parallelo interrotto da timeout durante setup DB, poi rilancio singolo OK.
- Backup creati: nessuno.
- README/CHANGELOG: `README.md`, `CHANGELOG.md` e `django_app/CHANGELOG.md` aggiornati.

- Area: `django_app/assets`, sidebar categorie.
- Richiesta: correggere la selezione doppia in sidebar quando aprendo `CMM > Controllo` risultava evidenziato anche `Costruzioni Novicrom > Bls d`.
- File modificati in questa sessione: `django_app/assets/views.py`, `django_app/assets/templates/assets/base_shell.html`, `django_app/assets/templates/assets/pages/asset_list.html`, `django_app/assets/tests.py`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno; `_AGENT_CONTROL/CRITICAL_FILES.md` non e' presente nella workspace. Nessuna modifica a ACL, middleware, settings, autenticazione, permessi, routing globale o navigazione globale.
- Motivo tecnico: `_is_sidebar_button_active` valutava `button.active_match` con un confronto di sottostringa sul path completo. Cosi `active_match=asset_category=60` risultava vero anche su `/assets/lista/?asset_category=608&rows=25`. In piu la shell Assets e l'inventario salvavano in `localStorage` tutti i gruppi sidebar aperti, che restavano aperti dopo navigazioni successive (es. `/assets/workorders/`).
- Modifica: gli `active_match` in forma query string (`chiave=valore`) vengono ora parsati e confrontati esattamente sui parametri `request.GET`; i match path esistenti restano invariati. Rimossa la persistenza dei gruppi aperti dalla sidebar shell e dalla sidebar inventario; entrambe cancellano la vecchia chiave `assets_sidebar_open_groups_v1` e si comportano come accordion. Aggiunte regressioni sul caso categoria `60` vs `608` e sull'assenza del salvataggio persistente.
- Impatto previsto: cliccando una categoria viene evidenziata solo la voce corrispondente; le altre categorie con ID prefisso non si aprono/attivano per errore; dopo aver navigato tra inventario, workorders e altre pagine Assets non restano accumulati gruppi aperti.
- Rischi residui: non eseguita verifica visuale autenticata; comportamento validato via helper/sidebar template e test Django. I pulsanti con `active_match` path continuano a usare il match a sottostringa precedente.
- Test/check: `python -B django_app\manage.py test assets.tests.AssetsRoutingTests.test_asset_sidebar_template_renders_collapsible_groups assets.tests.AssetsRoutingTests.test_asset_sidebar_category_active_match_is_exact --settings=config.settings.test --verbosity 1 --keepdb` OK; `python -B django_app\manage.py check assets --settings=config.settings.test` OK; `git diff --check` OK.
- Backup creati: nessuno.
- README/CHANGELOG: `CHANGELOG.md` e `django_app/CHANGELOG.md` aggiornati; README non aggiornato perche' non cambiano URL, setup, dipendenze o documentazione operativa.
- Note operative: nessun rebuild sidebar richiesto; la correzione funziona anche sulle righe `AssetSidebarButton` gia presenti nel database.

- Area: `django_app/assets`, reportistica manutenzione.
- Richiesta: occuparsi della parte di reportistica del modulo Assets dopo l'audit manutenzioni.
- File modificati in questa sessione: `django_app/assets/services/maintenance_kpi.py`, `django_app/assets/views.py`, `django_app/assets/templates/assets/pages/reports_dashboard.html`, `django_app/assets/tests.py`, `README.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno; `_AGENT_CONTROL/CRITICAL_FILES.md` non e' presente nella workspace. Nessuna modifica a ACL, middleware, settings, autenticazione, permessi, routing globale o navigazione globale.
- Motivo tecnico: la dashboard report Assets mostrava OdL/scadenze/costi ma non un indicatore unico di salute preventiva ne' un confronto budget/consuntivo per categoria, lasciando scollegato il modello `AssetMaintenanceBudget` dai report operativi.
- Modifica: introdotto il servizio read-only `build_maintenance_report_kpis` che aggrega lo scadenzario manutentivo e gli OdL chiusi dell'anno corrente nello scope selezionato; la pagina `/assets/reports/` mostra PM compliance, budget usato e tabella Budget vs actual per categoria con stato in linea/attenzione/oltre budget/budget mancante. Aggiunta regressione sui KPI report. Nessuna migration e nessuna nuova dipendenza.
- Impatto previsto: chi carica e consulta manutenzioni ha una vista immediata di copertura PM e scostamento costi/budget, filtrata per report IT/produzione come gia avveniva per il resto della pagina.
- Rischi residui: il budget resta gestito dal modello esistente ma non ha ancora una UI CRUD dedicata in questa tranche; i costi actual dipendono dalla corretta chiusura degli OdL con costo valorizzato. Verifica visuale autenticata non eseguita.
- Test/check: `python -B django_app\manage.py test assets.tests.AssetsRoutingTests.test_reports_dashboard_contains_month_selector assets.tests.AssetsRoutingTests.test_reports_dashboard_shows_pm_compliance_and_budget_vs_actual --settings=config.settings.test --verbosity 1 --keepdb` OK; `python -B django_app\manage.py check assets --settings=config.settings.test` OK; `git diff --check` OK. Un primo lancio parallelo dei test e' andato in timeout lato shell, poi rilanciato singolarmente con esito OK.
- Backup creati: nessuno.
- README/CHANGELOG: `README.md`, `CHANGELOG.md` e `django_app/CHANGELOG.md` aggiornati.
- Note operative: prima del caricamento massivo conviene valorizzare i budget 2026 per categoria e registrare i costi sugli OdL chiusi, altrimenti la tabella segnala budget mancanti o actual a zero.

- Area: `django_app/assets`, manutenzioni a contatore.
- Richiesta: analizzare il modulo asset/manutenzione prima del caricamento operativo e verificare che il flusso sia collegato.
- File modificati in questa sessione: `django_app/assets/models.py`, `django_app/assets/maintenance.py`, `django_app/assets/tests.py`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno; `_AGENT_CONTROL/CRITICAL_FILES.md` non e' presente nella workspace. Nessuna modifica a ACL, middleware, settings, autenticazione, permessi, routing globale o navigazione globale.
- Motivo tecnico: le regole manutentive a contatore (`HOURS/KM/CYCLES`) calcolano la prossima soglia dal valore salvato sull'ultimo OdL chiuso; quel valore poteva restare nullo nella chiusura/registrazione esecuzione, facendo ripartire lo scadenzario dalla base zero.
- Modifica: `WorkOrder.close()` salva automaticamente `meter_value_at_close` dal relativo `AssetMeter` quando chiude un OdL a contatore; `sync_workorder_maintenance_state()` applica la stessa fotografia anche agli OdL gia marcati come eseguiti dallo scadenzario. Aggiunte regressioni dedicate su chiusura OdL e registrazione esecuzione.
- Impatto previsto: dopo un tagliando a ore/km/cicli, scadenzario e generatore automatico ripartono dal contatore effettivo dell'ultimo intervento, evitando falsi scaduti/subito-rigenerati.
- Rischi residui: restano migliorabili, ma non bloccanti per il caricamento, l'inserimento costi/materiali nella chiusura OdL, i KPI PM compliance/budget e l'inclusione esplicita delle regole manutentive nel riquadro "Prossimi 7 giorni" dell'hub.
- Test/check: `python -B django_app\manage.py test assets.tests.AssetMeterScheduleTests.test_workorder_close_snapshots_current_meter_value assets.tests.AssetMeterScheduleTests.test_sync_snapshots_meter_value_for_recorded_execution --settings=config.settings.test --verbosity 2 --keepdb` OK; `python -B django_app\manage.py test assets.tests.AssetMeterScheduleTests --settings=config.settings.test --verbosity 1 --keepdb` OK; `python -B django_app\manage.py test assets.tests.WorkOrderFlowTests assets.tests.AssetMaintenanceStepTwoTests assets.tests.AssetMaintenanceStepThreeTests assets.tests.PeriodicVerificationConvergenceTests --settings=config.settings.test --verbosity 1 --keepdb` OK; `python -B django_app\manage.py test assets.tests.AssetMaintenanceRegisterUnifiedTests assets.tests.AssetMaintenanceRegisterTicketTests --settings=config.settings.test --verbosity 1 --keepdb` OK; `python -B django_app\manage.py check assets --settings=config.settings.test` OK; `git diff --check` OK.
- Backup creati: nessuno.
- README/CHANGELOG: `CHANGELOG.md` e `django_app/CHANGELOG.md` aggiornati; README non aggiornato perche' non cambiano setup, URL o dipendenze.
- Note operative: prima del caricamento iniziale conviene registrare le ultime esecuzioni/baseline contatori esistenti e schedulare `generate_scheduled_workorders` quotidiano.

- Area: repository Git / pubblicazione su GitHub.
- Richiesta: fare commit e push su GitHub unendo i branch di lavoro sotto l'unico `main`.
- File modificati direttamente in questa sessione: `.gitignore`, `CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File inclusi nel commit/push: tutto il workspace Git tracciabile gia modificato nella checkout, esclusi artefatti locali/privacy esplicitamente ignorati (`.tmp_export/`, `.tmp_timbri_commit/`, `/prod`).
- File critici modificati: `_AGENT_CONTROL/CRITICAL_FILES.md` non e' presente nella workspace. La pubblicazione include comunque modifiche preesistenti in aree operative sensibili (`django_app/config/settings/base.py`, `django_app/core/middleware.py`, `django_app/core/urls.py` e varie URL di modulo), non editate in questa micro-sessione ma presenti nel workspace da consolidare.
- Motivo tecnico: consolidare le modifiche locali e il branch `feat/timbri-export-csv` su `main`, evitando di versionare export CSV/scratch temporanei o marker locali.
- Modifica: eseguito `git fetch --all --prune`; rimossi dall'indice gli artefatti temporanei/privacy gia staged; aggiunte regole `.gitignore` per `.tmp_export/`, `.tmp_timbri_commit/` e `/prod`; creato il commit `acac731` su `main`, poi merge commit `39fbe1c` per integrare `feat/timbri-export-csv`; push `origin/main` eseguito con successo. Eliminati i branch locali mergiati `feat/anomalie-mail-action-op` e `feat/timbri-export-csv`; eliminati da GitHub i branch remoti gia inclusi in `main` (`feat/acl-chiusura-migrazione-fase1`, `feat/automazioni-motore-flussi`, `feat/timbri-export-csv`, `sec-runbook-01-private-attachments`). Nessuna nuova dipendenza.
- Impatto previsto: `main` diventa il ramo unico di riferimento per le modifiche consolidate, mentre gli artefatti locali restano sul disco ma fuori dal repository.
- Rischi residui: commit molto ampio, composto da piu tranche precedenti e non da una singola feature; non e' stata lanciata una suite completa in questa micro-sessione. I branch Dependabot non sono stati fusi perche' introducono upgrade di dipendenze e richiedono revisione separata; i branch locali `worktree-agent-*` restano perche' agganciati a worktree bloccati.
- Test/check: `git diff --check` OK prima del commit; `git diff --check origin/main..main` inizialmente ha trovato trailing whitespace in `django_app/anagrafica/templates/anagrafica/pages/dipendente_detail.html`, corretto nel merge commit; rilancio OK. `python -B django_app\manage.py check --settings=config.settings.test` OK. `gh` non disponibile nella macchina, quindi nessuna PR GitHub aperta da CLI.
- Backup creati: nessuno.
- README/CHANGELOG: `CHANGELOG.md` aggiornato per la guardia `.gitignore`; README non aggiornato perche' il cambio diretto di questa micro-sessione non modifica setup utente, URL, dipendenze o comportamento runtime.
- Note operative: `.tmp_export/`, `.tmp_timbri_commit/` e `/prod` restano locali/ignorati e non devono essere forzati in Git.

- Area: `django_app/assets`, pagine principali modulo Assets.
- Richiesta: applicare anche alle altre pagine del modulo asset lo stesso stile apprezzato sulla scheda asset.
- File modificati in questa sessione: `django_app/assets/templates/assets/base_shell.html`, `django_app/assets/templates/assets/pages/asset_dashboard.html`, `django_app/assets/templates/assets/pages/asset_list.html`, `django_app/assets/templates/assets/pages/maintenance_hub.html`, `django_app/assets/templates/assets/pages/work_machine_list.html`, `django_app/assets/templates/assets/pages/work_machine_dashboard.html`, `django_app/assets/templates/assets/pages/device_list.html`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno; `_AGENT_CONTROL/CRITICAL_FILES.md` non e' presente nella workspace. Nessuna modifica a ACL, middleware, settings, autenticazione, permessi, routing globale o navigazione globale.
- Motivo tecnico: dopo la rifinitura della scheda singolo asset, le altre viste del modulo restavano visivamente disomogenee e piu pesanti, con KPI/card/tabelle percepiti come blocchi separati.
- Modifica: aggiornata la shell comune Assets con sidebar, ricerca, header pagina, pulsanti, campi e tabelle in stile cockpit; aggiunti override visuali mirati a dashboard asset, inventario asset, hub manutenzione, elenco macchine, dashboard officina e dispositivi IT con accenti laterali, ombre leggere, radius piu compatti, header card sfumati e dark mode coerente. Nessuna nuova dipendenza.
- Impatto previsto: consultazione piu omogenea e meno pesante nelle principali pagine operative Assets; dati, filtri, azioni e URL restano invariati.
- Rischi residui: verifica visuale autenticata non eseguita; il Browser plugin e' disponibile come skill ma non espone tool runtime in questa sessione. Il workspace contiene modifiche preesistenti non correlate in vari file documentali, non revertite.
- Test/check: `python -B django_app\manage.py check assets --settings=config.settings.test` OK; template load via `manage.py shell` per i 7 template toccati OK; smoke test mirati AssetsRoutingTests su asset list, dashboard, macchine, dispositivi e dashboard officina OK (5 test); test mirati dettaglio asset/manutenzione OK (2 test); `git diff --check` sui file toccati OK; `rg` non trova `letter-spacing` negativo nei template toccati.
- Backup creati: nessuno.
- README/CHANGELOG: `CHANGELOG.md` e `django_app/CHANGELOG.md` aggiornati; README non aggiornato perche' modifica solo presentazionale senza cambio URL, setup, dipendenze o comportamento operativo.
- Note operative: modifica applicata solo alla workspace locale, non a `Y:\current`/prod.

## 2026-06-15 - Codex

- Area: `django_app/assets`, scheda asset `/assets/view/<id>/`.
- Richiesta: rendere la UI della scheda asset piu accattivante rispetto alla prima sistemazione.
- File modificati in questa sessione: `django_app/assets/templates/assets/pages/asset_detail.html`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno; `_AGENT_CONTROL/CRITICAL_FILES.md` non e' presente nella workspace. Nessuna modifica a ACL, middleware, settings, autenticazione, permessi, routing globale o navigazione globale.
- Motivo tecnico: la scheda era stata alleggerita ma restava visivamente piatta; serviva una testata piu riconoscibile e un'organizzazione delle azioni meno amministrativa.
- Modifica: la testata asset ora usa un layout "cockpit" con accento laterale multicolore, tile tipo asset, nome macchina separato dal codice, chip informativi per tipo/reparto/produttore/modello/seriale quando disponibili e pannello Azioni rapide dedicato. La status band Copertura/Scadenze e le card hanno accenti visivi piu marcati ma sobri; responsive e dark mode aggiornati. Nessuna nuova dipendenza.
- Impatto previsto: `/assets/view/<id>/` risulta piu curata e leggibile a colpo d'occhio, mantenendo la densita' operativa e gli stessi link/azioni.
- Rischi residui: verifica visuale autenticata non eseguita; la resa finale va confermata in browser con sessione utente. Il Browser plugin e' disponibile come skill ma il tool runtime `node_repl js` non e' esposto in questa sessione.
- Test/check: `python -B django_app\manage.py check assets --settings=config.settings.test` OK; `python -B django_app\manage.py test assets.tests.AssetAdministrativeStepOneTests.test_step_one_routes_render_and_asset_detail_contains_links --settings=config.settings.test --verbosity 1 --keepdb` OK; `rg` conferma presenza delle nuove classi `af-hero-*` e assenza di `Dettaglio asset`/letter-spacing negativo nel template.
- Backup creati: nessuno.
- README/CHANGELOG: `CHANGELOG.md` e `django_app/CHANGELOG.md` aggiornati; README non aggiornato perche' modifica presentazionale senza cambio URL, setup, dipendenze o comportamento operativo documentabile.
- Note operative: modifica applicata solo alla workspace locale, non a `Y:\current`/prod.

## 2026-06-15 - Codex

- Area: `django_app/assets`, scheda asset `/assets/view/<id>/`.
- Richiesta: sostituire il titolo shell "Dettaglio asset" con un collegamento per tornare alla pagina precedente e proporre/applicare un layout meno pesante della scheda.
- File modificati in questa sessione: `django_app/assets/templates/assets/pages/asset_detail.html`, `django_app/assets/tests.py`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno; `_AGENT_CONTROL/CRITICAL_FILES.md` non e' presente nella workspace. Nessuna modifica a ACL, middleware, settings, autenticazione, permessi, routing globale o navigazione globale.
- Motivo tecnico: la shell mostrava ancora un titolo generico e ridondante rispetto all'H1 asset, mentre il contenuto del dettaglio si estendeva su tutta la larghezza disponibile generando card molto larghe e difficili da consultare.
- Modifica: il blocco `assets_shell_title` ora renderizza un link `Torna indietro` con fallback a `collection_url` e JS che usa `history.back()` solo se il referrer e' interno al portale. La scheda e' stata centrata con `max-width:1440px`, header compattato, azioni secondarie meno invasive e sezioni dettaglio rese a due colonne responsive con `break-inside: avoid`; sotto 1180px torna una colonna. Aggiunta regressione nel test smoke asset per verificare il link di ritorno e l'assenza del vecchio titolo.
- Impatto previsto: `/assets/view/<id>/` ha un ingresso piu chiaro per tornare indietro e una consultazione meno dispersiva su monitor larghi, senza cambiare dati, query, salvataggi, ACL, permessi, URL o routing.
- Rischi residui: verifica visuale autenticata non eseguita; la resa finale va confermata con sessione utente sul portale locale. Il layout a colonne CSS rispetta l'ordine delle card ma puo' bilanciare visivamente l'altezza delle colonne in base ai contenuti disponibili.
- Test/check: `python -B django_app\manage.py check assets --settings=config.settings.test` OK; `python -B django_app\manage.py test assets.tests.AssetAdministrativeStepOneTests.test_step_one_routes_render_and_asset_detail_contains_links --settings=config.settings.test --verbosity 2` OK; `git diff --check -- django_app/assets/templates/assets/pages/asset_detail.html django_app/assets/tests.py CHANGELOG.md django_app/CHANGELOG.md _AGENT_CONTROL/AGENT_CHANGELOG.md session_checkpoint.md` OK; `rg` conferma che nel template non restano `Dettaglio asset`, `af-breadcrumb` o `letter-spacing` negativo, e trova il nuovo `data-af-back-link`. Un primo lancio con classe test errata e' fallito prima dell'esecuzione (`AttributeError`), poi rilanciato con path corretto. Verifica Browser in-app non eseguita perche' il plugin Browser e' presente ma il tool runtime `node_repl js` richiesto non e' esposto in questa sessione.
- Backup creati: nessuno.
- README/CHANGELOG: `CHANGELOG.md` e `django_app/CHANGELOG.md` aggiornati; README non aggiornato perche' modifica presentazionale senza cambio URL, setup, dipendenze o comportamento operativo documentabile.
- Note operative: modifica applicata solo alla workspace locale, non a `Y:\current`/prod.

## 2026-06-15 - Codex

- Area: `django_app/assets`, scheda asset `/assets/view/<id>/`.
- Richiesta: eliminare il blocco alto dove nome/tag macchina si ripetevano, sistemare i pulsanti del Registro manutenzione in massimo due righe e rendere piu compatta la banda Copertura/Scadenze per ridurre l'effetto "grossi blocchi".
- File modificati in questa sessione: `django_app/assets/templates/assets/pages/asset_detail.html`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno; `_AGENT_CONTROL/CRITICAL_FILES.md` non e' presente nella workspace. Nessuna modifica a ACL, middleware, settings, autenticazione, permessi, routing globale o navigazione globale.
- Motivo tecnico: la scheda asset mostrava sopra l'H1 sia il sottotitolo `asset_tag - asset.name` sia il breadcrumb con asset tag, duplicando l'identita' della macchina gia presente nel titolo principale. La status band Copertura/Scadenze usava dimensioni da KPI/card troppo alte e i pulsanti del Registro manutenzione si disponevano come blocco largo poco leggibile.
- Modifica: rimosso il sottotitolo asset e il breadcrumb superiore dal dettaglio; ridotte dimensioni di titolo, card, shadow, gap e status band; la banda Copertura/Scadenze ora usa valori e metadati piu piccoli; il Registro manutenzione usa `af-card-actions--maintenance` in griglia 2 colonne con etichette compatte (`Regole`, `Scadenzario`, `Periodica`, `+ Straordinaria`) e tooltip descrittivi completi. Rimossi `letter-spacing` negativi dal template toccato.
- Impatto previsto: `/assets/view/<id>/` risulta piu pulita in alto, con meno duplicazione del nome macchina, una banda stato meno invadente e una toolbar manutenzione leggibile senza occupare molte righe. Nessun cambio a dati, query, salvataggi, ACL, permessi, URL o routing.
- Rischi residui: verifica visuale autenticata non eseguita; la rotta locale `/assets/view/714/` risponde ma reindirizza al login senza sessione. Il Browser in-app non esponeva il canale di automazione in questa sessione, quindi la verifica e' rimasta HTTP/template/test.
- Test/check: `python -B django_app\manage.py check assets --settings=config.settings.test` OK; `python -B django_app\manage.py test assets.tests.AssetAdministrativeStepOneTests.test_step_one_routes_render_and_asset_detail_contains_links assets.tests.AssetMaintenanceStepThreeTests.test_asset_maintenance_routes_render_and_reset_override --settings=config.settings.test --verbosity 1 --keepdb` OK (2 test); `git diff --check -- django_app/assets/templates/assets/pages/asset_detail.html CHANGELOG.md django_app/CHANGELOG.md` OK; `rg` non trova `letter-spacing` negativo, `af-breadcrumb` o il vecchio sottotitolo duplicato nel template; `curl.exe -I http://localhost:8000/assets/view/714/` e `http://127.0.0.1:8000/assets/view/714/` restituiscono `302 Found` verso `/login/?next=%2Fassets%2Fview%2F714%2F`.
- Backup creati: nessuno.
- README/CHANGELOG: `CHANGELOG.md` e `django_app/CHANGELOG.md` aggiornati; README non aggiornato perche' modifica presentazionale senza cambio URL, setup, dipendenze o comportamento operativo documentabile.
- Note operative: modifica applicata solo alla workspace locale, non a `Y:\current`/prod. Primo tentativo test con path classe errato fallito con `AttributeError` prima dell'esecuzione del test; rilancio con path corretto OK.

## 2026-06-15 - Codex

- Area: `django_app/notizie`, impostazioni Notizie `/notizie/impostazioni/` e collegamenti da `/notizie/` + `/notizie/dashboard/`.
- Richiesta: rendere anche `notizie/impostazioni` coerente con la dashboard/lista e inserire il collegamento a Impostazioni da dashboard e Notizie.
- File modificati in questa sessione: `django_app/notizie/templates/notizie/pages/gestione_admin.html`, `django_app/notizie/templates/notizie/pages/lista.html`, `django_app/notizie/templates/notizie/pages/dashboard.html`, `django_app/notizie/views.py`, `django_app/notizie/tests.py`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno; `_AGENT_CONTROL/CRITICAL_FILES.md` non e' presente nella workspace. Nessuna modifica a ACL, middleware, settings, autenticazione, permessi, routing globale o navigazione globale.
- Motivo tecnico: `/notizie/impostazioni/` usava ancora il layout amministrativo `ga-*` con tabella `tbl` dentro `overflow-x:auto`, visivamente distante dalla nuova lista/dashboard Notizie e con lo stesso problema di scorrimento orizzontale segnalato sulla dashboard. La lista non riceveva inoltre il flag necessario per mostrare il collegamento a Impostazioni agli utenti abilitati.
- Modifica: `gestione_admin.html` ora usa body class `notizie-settings-page`, hero full page, KPI, tab compatte e pannelli coerenti con il linguaggio `news-*`; la tab Record e' stata trasformata in card responsive con stato, obbligatorieta', metadati, metriche letture/conformi e azioni, senza tabella e senza `overflow-x`. La lista `/notizie/` mostra il link `Impostazioni` in hero e vista rapida per chi ha `can_gestione_admin`; la dashboard mantiene il link in hero e aggiunge un pannello Strumenti nel rail laterale. `views.py` introduce `_can_manage_notizie_settings`, riusato dalla dashboard ed esposto alla lista, e `tasso_conformita_int` come campo derivato per la barra visuale. Aggiunte regressioni sui link e sul render impostazioni a card.
- Impatto previsto: impostazioni, dashboard e lista Notizie hanno ora ingressi coerenti e una resa allineata, con record amministrativi leggibili senza scroll orizzontale. Nessun cambio a dati, audience, pubblicazione, conferma lettura, permessi, URL o routing.
- Rischi residui: screenshot autenticato non eseguito; Playwright locale raggiunge `/notizie/impostazioni/?tab=record` ma viene reindirizzato a `/login/?next=%2Fnotizie%2Fimpostazioni%2F%3Ftab%3Drecord`, quindi la resa finale va confermata con sessione autenticata. La suite completa `notizie` non e' stata rilanciata in questa tranche; resta nota la precedente rottura fuori scope su due test upload/form (`test_crea_notizia_con_audience_e_allegato_file`, `test_form_rejects_empty_file`).
- Test/check: template load OK per `notizie/pages/gestione_admin.html`, `notizie/pages/lista.html`, `notizie/pages/dashboard.html`; `python -B django_app\manage.py test notizie.tests.NotizieACLTests.test_lista_mostra_link_impostazioni_per_admin notizie.tests.NotizieACLTests.test_dashboard_mostra_link_impostazioni_per_admin notizie.tests.NotizieACLTests.test_impostazioni_renderizza_workspace_a_card_senza_tabella notizie.tests.NotizieACLTests.test_bottone_dashboard_visibile_solo_abilitati notizie.tests.NotizieACLTests.test_dashboard_renderizza_workspace_a_card_senza_tabella --settings=config.settings.test --verbosity 1 --keepdb` OK (5 test); `python -B django_app\manage.py test notizie.tests.NotizieACLTests --settings=config.settings.test --verbosity 1 --keepdb` OK (15 test); `python -B django_app\manage.py check notizie --settings=config.settings.test` OK; `git diff --check` sui file Notizie OK; `rg` non trova `ga-`, `class="tbl"`, `overflow-x` o `letter-spacing` negativo nei template Notizie toccati; smoke Playwright locale su `/notizie/impostazioni/?tab=record` OK fino al redirect login.
- Backup creati: nessuno.
- README/CHANGELOG: `CHANGELOG.md` e `django_app/CHANGELOG.md` aggiornati; README non aggiornato perche' modifica presentazionale senza cambio URL, setup, dipendenze o comportamento operativo documentabile.
- Note operative: modifica applicata solo alla workspace locale, non a `Y:\current`/prod.

## 2026-06-15 - Codex

- Area: `django_app/notizie`, dashboard gestione `/notizie/dashboard/`.
- Richiesta: rendere la dashboard gestione Notizie coerente con la nuova UI Notizie ed eliminare la tabella scrollabile/antiestetica.
- File modificati in questa sessione: `django_app/notizie/templates/notizie/pages/dashboard.html`, `django_app/notizie/views.py`, `django_app/notizie/tests.py`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno; `_AGENT_CONTROL/CRITICAL_FILES.md` non e' presente nella workspace. Nessuna modifica a ACL, middleware, settings, autenticazione, permessi, routing globale o navigazione globale.
- Motivo tecnico: `/notizie/dashboard/` usava ancora una tabella larga che veniva agganciata automaticamente da `fm-table-enhanced` (toolbar Cerca/Colonne/Reset) e richiedeva scroll orizzontale; inoltre la resa era distante dalla nuova lista `/notizie/` a workspace/card.
- Modifica: `dashboard.html` ora usa body class `notizie-dashboard-page`, hero full page con KPI, tab stato, card gestionali responsive per ogni notizia e rail laterale con filtri, riepilogo e permessi dashboard. Rimossa la tabella `news-table`, quindi non c'e' piu' binding automatico del sistema tabelle ne' scroll orizzontale. `_dashboard_rows` espone `completion_rate_int` come campo derivato per la barra copertura. Aggiunta regressione `test_dashboard_renderizza_workspace_a_card_senza_tabella` e aggiornato il testo atteso del pannello permessi.
- Impatto previsto: la dashboard gestione Notizie risulta coerente con `/notizie/`, piu leggibile e usabile su desktop/mobile, senza cambiare dati, audience, pubblicazione, archiviazione, permessi, URL o routing.
- Rischi residui: screenshot autenticato non eseguito; Playwright locale arriva al login `/login/?next=%2Fnotizie%2Fdashboard%2F`, quindi la resa finale va confermata con sessione autenticata. La suite completa `notizie` resta rossa su due test non legati alla dashboard (`test_crea_notizia_con_audience_e_allegato_file`, `test_form_rejects_empty_file`) nella validazione allegati/upload.
- Test/check: `python -B django_app\manage.py test notizie.tests.NotizieACLTests.test_dashboard_renderizza_workspace_a_card_senza_tabella notizie.tests.NotizieACLTests.test_dashboard_mostra_editor_permessi_per_hr notizie.tests.NotizieACLTests.test_bottone_dashboard_visibile_solo_abilitati --settings=config.settings.test --verbosity 1 --keepdb` OK (3 test); `python -B django_app\manage.py check notizie --settings=config.settings.test` OK; template load `notizie/pages/dashboard.html` OK; `git diff --check` sui file Notizie OK; `rg` conferma assenza di `news-table`, `fm-tbl-controls`, `<table` e `letter-spacing` negativo nel template dashboard; smoke Playwright locale su `/notizie/dashboard/` OK fino al redirect login; `python -B django_app\manage.py test notizie --settings=config.settings.test --verbosity 1 --keepdb` eseguito ma FALLISCE sui due test upload/form indicati sopra.
- Backup creati: nessuno.
- README/CHANGELOG: `CHANGELOG.md` e `django_app/CHANGELOG.md` aggiornati; README non aggiornato perche' modifica solo presentazionale senza cambio URL, setup, dipendenze o comportamento operativo documentabile.
- Note operative: modifica applicata solo alla workspace locale, non a `Y:\current`/prod.

## 2026-06-14 - Codex

- Area: `django_app/procedure_refresh`, lista personale `/procedure-refresh/`.
- Richiesta: rendere piu carina e full page anche la UI del modulo Procedure Refresh, come fatto per Notizie.
- File modificati in questa sessione: `django_app/procedure_refresh/views.py`, `django_app/procedure_refresh/templates/procedure_refresh/pages/my_assignments.html`, `django_app/procedure_refresh/tests.py`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno; `_AGENT_CONTROL/CRITICAL_FILES.md` non e' presente nella workspace. Nessuna modifica a ACL, middleware, settings, autenticazione, permessi, routing globale o navigazione globale.
- Motivo tecnico: `/procedure-refresh/` usava una tabella centrale compatta e lasciava molto spazio laterale inutilizzato, risultando meno coerente con le nuove workspace operative full page.
- Modifica: `my_assignments` ora calcola `pr_stats` sulle sole assegnazioni dell'utente corrente; `my_assignments.html` usa `pr-workspace-page`, allarga la content area e introduce hero, KPI personali, filtri a tab, card assegnazione larghe con badge stato, empty state e rail laterale con stato personale/vista rapida. Aggiunta regressione `test_my_assignments_renderizza_workspace_fullpage`.
- Impatto previsto: `/procedure-refresh/` risulta piu leggibile e operativa su desktop e mobile, senza cambiare assegnazioni visibili, workflow di presa visione, permessi o URL.
- Rischi residui: screenshot autenticato non eseguito; il browser locale raggiunge `/procedure-refresh/` ma viene reindirizzato a `/login/?next=/procedure-refresh/`. La resa finale va confermata con una sessione autenticata.
- Test/check: `python -B django_app\manage.py test procedure_refresh.tests.ViewTests.test_my_assignments_renderizza_workspace_fullpage procedure_refresh.tests.ViewTests.test_my_assignments_authenticated --settings=config.settings.test --verbosity 1 --keepdb` OK (2 test); `python -B django_app\manage.py check procedure_refresh --settings=config.settings.test` OK; template load `procedure_refresh/pages/my_assignments.html` OK; `git diff --check` sui file Procedure Refresh OK; verifica Playwright locale OK fino al redirect login.
- Backup creati: nessuno.
- README/CHANGELOG: `CHANGELOG.md` e `django_app/CHANGELOG.md` aggiornati; README non aggiornato perche' modifica presentazionale senza cambio URL, setup, dipendenze o comportamento operativo.
- Note operative: nessuna.

## 2026-06-14 - Codex

- Area: `django_app/timbri`, UI modulo Timbri.
- Richiesta: rendere piu carina la UI di Timbri, come per gli altri moduli.
- File modificati in questa sessione: `django_app/timbri/templates/timbri/pages/index.html`, `django_app/timbri/templates/timbri/pages/operatore_detail.html`, `django_app/timbri/templates/timbri/pages/record_form.html`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno; `_AGENT_CONTROL/CRITICAL_FILES.md` non e' presente nella workspace. Nessuna modifica a ACL, middleware, settings, autenticazione, permessi, routing globale o navigazione globale.
- Motivo tecnico: il modulo Timbri risultava piu spoglio e centrale rispetto alle nuove schermate Notizie/Assenze, con elenco e scheda meno coerenti col linguaggio visuale operativo del portale.
- Modifica: aggiunte body class dedicate alle tre pagine principali; `index.html` ora allarga la content area, usa hero operativa full-width, KPI/card piu puliti e filtri/tabella piu rifiniti; `operatore_detail.html` usa una hero card visuale per scheda dipendente, KPI e meta piu ordinati; `record_form.html` usa header visuale, card/anteprime immagini piu curate e azioni allineate. Rimossi anche letter-spacing negativi dai template Timbri toccati.
- Impatto previsto: `/timbri/`, la scheda dipendente Timbri e il form di caricamento record risultano piu moderni e coerenti con gli altri moduli, senza cambiare workflow, dati salvati, URL o permessi.
- Rischi residui: verifica visuale autenticata non eseguita; la rotta locale Timbri porta al login se non c'e' sessione attiva e l'istanza Playwright MCP risulta gia' occupata da un'altra sessione, quindi la resa finale va confermata con utente autenticato.
- Test/check: template load OK su `timbri/pages/index.html`, `timbri/pages/operatore_detail.html`, `timbri/pages/record_form.html`; `python -B django_app\manage.py check timbri --settings=config.settings.test` OK; `git diff --check` sui template Timbri e documenti aggiornati OK; `rg` conferma nessun `letter-spacing` negativo nei template Timbri toccati; `curl.exe -I http://127.0.0.1:8000/timbri/` restituisce `302 Found` verso `/login/?next=%2Ftimbri%2F`.
- Backup creati: nessuno.
- README/CHANGELOG: `CHANGELOG.md` e `django_app/CHANGELOG.md` aggiornati; README non aggiornato perche' modifica presentazionale senza cambio URL, setup, dipendenze o comportamento operativo documentabile.
- Note operative: modifica applicata solo alla workspace locale, non a `Y:\current`/prod.

## 2026-06-14 - Codex

- Area: `django_app/assenze`, pagina inserimento richiesta assenza.
- Richiesta: spingere di piu la UI, soprattutto su richiesta assenza, con qualcosa di dinamico.
- File modificati in questa sessione: `django_app/assenze/templates/assenze/pages/richiesta_assenze.html`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno; `_AGENT_CONTROL/CRITICAL_FILES.md` non e' presente nella workspace. Nessuna modifica a ACL, middleware, settings, autenticazione, permessi, routing globale o navigazione globale.
- Motivo tecnico: la prima rifinitura della pagina richiesta aggiungeva icone ma lasciava il form ancora statico e lineare; serviva una UI piu guidata e reattiva senza cambiare il workflow backend.
- Modifica: `richiesta_assenze.html` ora usa `abs-request-page`, hero piu dinamica, stepper di compilazione, card cliccabili per tipo assenza sincronizzate col select nativo, misuratore live della durata, stato attivo sugli shortcut orari, riepilogo sticky laterale con tipo/periodo/durata/percorso approvativo e suggerimenti live per ferie, permesso, malattia, flessibilita e certifica presenza. Il JS resta inline nel template e agisce solo come enhancement client-side; il submit continua a usare gli stessi campi/nome endpoint esistenti.
- Impatto previsto: `/assenze/richiesta_assenze` risulta piu moderna e dinamica, con feedback immediato durante la compilazione, senza cambiare dati salvati, view, URL o permessi.
- Rischi residui: verifica screenshot autenticata non eseguita; Browser in-app non espone `node_repl js` e non sono installati Playwright locale/Python. Smoke HTTP su `http://10.0.0.79:8000/assenze/richiesta_assenze` restituisce login, quindi non consente verifica visuale autenticata.
- Test/check: template load `get_template('assenze/pages/richiesta_assenze.html')` OK; render Django minimale OK; JS renderizzato validato con `node --check -` OK; `python -B django_app\manage.py check assenze --settings=config.settings.test` OK; `git diff --check` sul template OK.
- Backup creati: nessuno.
- README/CHANGELOG: `CHANGELOG.md` e `django_app/CHANGELOG.md` aggiornati; README non aggiornato perche' modifica presentazionale/client-side senza cambio URL, setup, dipendenze o comportamento operativo documentabile.
- Note operative: il template `richiesta_assenze.html` non era read-only al momento della modifica.

## 2026-06-14 - Codex

- Area: `django_app/notizie`, lista modulo `/notizie/`.
- Richiesta: rendere piu carina la UI del modulo Notizie e portarla full page, non solo centrale.
- File modificati in questa sessione: `django_app/notizie/views.py`, `django_app/notizie/templates/notizie/pages/lista.html`, `django_app/notizie/tests.py`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno; `_AGENT_CONTROL/CRITICAL_FILES.md` non e' presente nella workspace. Nessuna modifica a ACL, middleware, settings, autenticazione, permessi, routing globale o navigazione globale.
- Motivo tecnico: `/notizie/` usava un wrapper centrale stretto (`max-width:860px`) con card semplici, lasciando molto spazio laterale inutilizzato e un'esperienza meno coerente con le nuove workspace operative.
- Modifica: la view `lista` costruisce `news_stats` dai soli item gia visibili all'utente; il template `lista.html` usa `body_class` dedicata `notizie-list-page`, allarga la content area, aggiunge hero full page con KPI, filtri a tab, card comunicazione larghe con badge stato/obbligatorieta', empty state e rail laterale con riepilogo/stati rapidi. I test Notizie completano l'onboarding degli utenti creati per non essere deviati dal middleware globale prima della view.
- Impatto previsto: `/notizie/` risulta piu piena, leggibile e operativa su desktop e mobile, senza cambiare audience, permessi, conferme di lettura o URL.
- Rischi residui: screenshot autenticato non eseguito; il browser locale raggiunge `/notizie/` ma viene correttamente reindirizzato a `/login/?next=/notizie/`. La resa finale va confermata con una sessione autenticata.
- Test/check: `python -B django_app\manage.py check notizie --settings=config.settings.test` OK; template load `get_template('notizie/pages/lista.html')` OK; `python -B django_app\manage.py test notizie.tests.NotizieACLTests.test_lista_renderizza_workspace_fullpage notizie.tests.NotizieACLTests.test_bottone_dashboard_visibile_solo_abilitati --settings=config.settings.test --verbosity 1 --keepdb` OK (2 test); `git diff --check` sui file Notizie OK. Primo tentativo test senza `--keepdb` interrotto durante setup DB test da `OSError: [Errno 22] Invalid argument` sul flush stdout di `migrate`, prima dell'esecuzione dei test.
- Backup creati: nessuno.
- README/CHANGELOG: `CHANGELOG.md` e `django_app/CHANGELOG.md` aggiornati; README non aggiornato perche' la modifica e' presentazionale e non cambia URL, setup, dipendenze o comportamento operativo.
- Note operative: il runtime Browser in-app richiesto dal plugin non esponeva `node_repl js`; usato fallback Playwright disponibile solo per verificare il redirect login locale.

## 2026-06-14 - Codex

- Area: `django_app/assenze`, UI modulo Assenze oltre al menu.
- Richiesta: la nuova UI del menu piace, ma la pagina resta un po' spoglia; continuare con lo stesso stile anche sulle altre pagine del modulo.
- File modificati in questa sessione: `django_app/assenze/templates/assenze/base_shell.html`, `django_app/assenze/templates/assenze/pages/menu.html`, `django_app/assenze/templates/assenze/pages/richiesta_assenze.html`, `django_app/assenze/templates/assenze/pages/gestione_assenze.html`, `django_app/assenze/templates/assenze/pages/calendario.html`, `django_app/assenze/templates/assenze/pages/certificazione_presenza.html`, `django_app/assenze/templates/assenze/pages/car_dashboard.html`, `django_app/assenze/templates/assenze/pages/gestione_admin.html`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno; `_AGENT_CONTROL/CRITICAL_FILES.md` non e' presente nella workspace. Nessuna modifica a ACL, middleware, settings, autenticazione, permessi, routing globale o navigazione globale.
- Motivo tecnico: il solo menu risultava piu curato, ma le altre viste Assenze restavano molto testuali/tabellari e senza segnali visivi coerenti; inoltre le icone SVG erano duplicate localmente nel menu invece che riusabili dal layout del modulo.
- Modifica: spostato lo sprite SVG nel layout `base_shell.html`, aggiunte regole comuni per icone, titoli pannello, tab e KPI; rimosso lo sprite locale dal menu; aggiunte icone e piccoli accenti visuali a hero action, KPI, pannelli, tab admin, banner presenza, filtro ricerca, calendario, dashboard reparto e gestione admin. Il calendario mantiene l'icona del titolo agenda separata dallo span aggiornato via JavaScript per non perderla al cambio data.
- Impatto previsto: le schermate `/assenze/richiesta_assenze`, gestione richieste, calendario, certificazione presenza, dashboard reparto/segnalazioni e gestione admin risultano piu piene e leggibili, coerenti col tema teal e con il menu, senza cambiare dati o workflow.
- Rischi residui: verifica visuale autenticata/screenshot non eseguita per indisponibilita' del runtime Browser in-app (`node_repl js` non disponibile in questa sessione); verificati template, simboli SVG e check Django. La resa finale va confermata a browser autenticato.
- Test/check: `python -B django_app\manage.py shell --settings=config.settings.test -c "from django.template.loader import get_template; templates=[...]; [get_template(t) for t in templates]; print('templates ok', len(templates))"` OK su 7 template; confronto simboli SVG `abs-i-*` usati vs definiti OK, missing vuoto; `python -B django_app\manage.py check assenze --settings=config.settings.test` OK; `git diff --check` sui template Assenze e sui documenti aggiornati OK.
- Backup creati: nessuno.
- README/CHANGELOG: `CHANGELOG.md` e `django_app/CHANGELOG.md` aggiornati; README non aggiornato perche' la modifica e' solo presentazionale e non cambia URL, setup, dipendenze o comportamento operativo.
- Note operative: `base_shell.html`, `menu.html`, `gestione_assenze.html` e `calendario.html` erano read-only; attributo rimosso temporaneamente per applicare la patch e ripristinato prima della chiusura.

## 2026-06-14 - Codex

- Area: `django_app/assenze`, menu modulo `/assenze/`.
- Richiesta: rendere piu compatta e piu curata la UI della pagina iniziale Assenze, poi renderla piu gradevole visivamente con icone e anche cambio UI se utile.
- File modificati in questa sessione: `django_app/assenze/templates/assenze/base_shell.html`, `django_app/assenze/templates/assenze/pages/menu.html`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno; `_AGENT_CONTROL/CRITICAL_FILES.md` non e' presente nella workspace. Nessuna modifica a ACL, middleware, settings, autenticazione, permessi, routing globale o navigazione globale.
- Motivo tecnico: la shell Assenze eredita `min-height:100%` dal layout globale e la griglia del menu tendeva ad allungare hero, card e pannello "Ultime richieste" occupando molto spazio vuoto verticale.
- Modifica: aggiunto un block opzionale `assenze_shell_class` in `base_shell.html` e usato `abs-menu-shell` solo nel menu; la pagina ora applica `align-content:start`/`grid-auto-rows:max-content`, hero a cockpit con micro-statistiche, card operative con accenti colore e icone SVG inline, badge reparto con conteggio richieste in attesa e lista ultime richieste in formato piu denso con icone di stato e link rapido alla gestione.
- Impatto previsto: `/assenze/` risulta piu compatta, meno vuota e visivamente piu curata, coerente con il tema teal del modulo ma con accenti colore differenziati, senza cambiare dati, permessi o navigazione.
- Rischi residui: verifica visuale autenticata non eseguita per indisponibilita' del runtime Browser in-app (`node_repl js` non disponibile in questa sessione); il controllo e' stato fatto via caricamento template e check Django.
- Test/check: `python -B django_app\manage.py shell --settings=config.settings.test -c "from django.template.loader import get_template; get_template('assenze/pages/menu.html'); print('template ok')"` OK; `python -B django_app\manage.py check assenze --settings=config.settings.test` OK; `git diff --check -- django_app/assenze/templates/assenze/base_shell.html django_app/assenze/templates/assenze/pages/menu.html` OK; dopo il secondo passaggio visuale rieseguiti template load, `check assenze` e `git diff --check` sul template menu, tutti OK.
- Backup creati: nessuno.
- README/CHANGELOG: `CHANGELOG.md` e `django_app/CHANGELOG.md` aggiornati; README non aggiornato perche' la modifica e' solo presentazionale e non cambia URL, setup, dipendenze o comportamento operativo.
- Note operative: i due template erano read-only; rimosso temporaneamente l'attributo solo su `base_shell.html` e `menu.html` per applicare la patch, poi ripristinato a fine sessione.

## 2026-06-14 - Claude

- Area: `django_app/anagrafica`, tab "Assenze" della scheda dettaglio dipendente.
- Richiesta: in Anagrafica, tab Assenze della scheda dipendente non venivano mostrate le assenze presenti.
- File modificati in questa sessione: `django_app/anagrafica/views.py`, `django_app/anagrafica/tests.py`, `CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`.
- File critici modificati: nessuno. Nessuna modifica a ACL, middleware, settings, autenticazione, permessi, routing globale o navigazione globale.
- Motivo tecnico: due cause concomitanti. (1) Bug bloccante — `_query_assenze_dipendente` referenziava `connections["default"]` ma `connections` non era importato a livello di modulo in `anagrafica/views.py` (solo import locali in altre funzioni): ogni chiamata sollevava `NameError`, catturato dal `except Exception`, ritornando sempre lista vuota → il tab mostrava sempre "Nessuna assenza" mentre il widget conteggio (che filtra per `copia_nome`) ne riportava di presenti. (2) Match fragile — la query usava la sola `INNER JOIN dipendenti ON a.dipendente_id = d.id` filtrando per `d.utente_id`; la colonna `assenze.dipendente_id` può mancare in prod (errore `42S22`, già noto in `assenze.views._load_events`) o restare NULL.
- Modifica: aggiunto `connections` a `from django.db import IntegrityError, connections, transaction`. Riscritto `_query_assenze_dipendente(dip)` con match robusto allineato al widget conteggio e al modulo assenze (`copia_nome` LIKE in entrambi gli ordini del nome, `utente_id` diretto su `assenze`, JOIN `dipendenti` solo se le colonne esistono — guardate da `legacy_table_columns`). La funzione ritorna ora `(lista, no_link)`; aggiornato il chiamante in `dipendente_detail`. Aggiunti 4 test (`QueryAssenzeDipendenteTests`).
- Hotfix prod diretta: non applicata (modifica solo su workspace; valutare deploy + recycle App Pool come per le patch precedenti).
- Impatto previsto: il tab Assenze elenca ora le assenze del dipendente (ultimi 2 anni) in modo coerente col widget conteggio, sia in dev sia in prod indipendentemente dalla presenza di `assenze.dipendente_id`.
- Rischi residui: il match per `copia_nome` LIKE può, in caso di omonimia, includere assenze di un omonimo — stesso comportamento già accettato dal widget conteggio esistente.
- Test/check: `python django_app/manage.py check anagrafica --settings=config.settings.test` OK; `python django_app/manage.py test anagrafica.tests.QueryAssenzeDipendenteTests --settings=config.settings.test` OK (4 test).
- README/CHANGELOG: `CHANGELOG.md` aggiornato; README non aggiornato (fix interna, nessun cambio URL/setup/dipendenze/funzionalità visibile nuova).

## 2026-06-14 - Codex

- Area: `django_app/timbri`, scheda timbri collegata ad Anagrafica HR.
- Richiesta: analizzare errore prod `Internal Server Error: /timbri/anagrafica/141/` con `NotImplementedError` da `civile.foto.url` su `PrivateAnagraficaStorage`.
- File modificati in questa sessione: `django_app/timbri/views.py`, `django_app/timbri/tests.py`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno; `_AGENT_CONTROL/CRITICAL_FILES.md` non e' presente nella workspace. Nessuna modifica a ACL, middleware, settings, autenticazione, permessi, routing globale o navigazione globale.
- Motivo tecnico: dopo la migrazione GDPR, le foto dipendente Anagrafica sono su `PrivateAnagraficaStorage` e non hanno URL pubblico; `ImageField.url` solleva intenzionalmente `NotImplementedError`. La view Timbri `operatore_detail_by_legacy` usava ancora `civile.foto.url` invece della view protetta gia' disponibile.
- Modifica: `operatore_detail_by_legacy` passa al template `reverse("anagrafica:foto_dipendente", args=[legacy_id])` quando la foto esiste, senza accedere a `.url`. Aggiunto test di regressione con foto privata su scheda timbri.
- Hotfix prod diretta: applicata la stessa modifica anche su `Y:\current\django_app\timbri\views.py`, con backup preventivo `Y:\current\django_app\timbri\views.py.bak_20260614_184224`.
- Impatto previsto: `/timbri/anagrafica/<legacy_id>/` non va piu' in 500 per dipendenti con foto profilo privata; la foto viene servita dalla route autenticata Anagrafica come nelle liste/schede HR.
- Rischi residui: il processo web prod potrebbe richiedere recycle App Pool/IIS per caricare il file Python modificato. Il path `C:\PortaleNovicrom\prod\current\...` del traceback non e' raggiungibile da questa workspace; la patch e' stata applicata alla mappa prod disponibile `Y:\current\...`.
- Test/check: `python -B -c "ast.parse(...)"` OK su `django_app/timbri/views.py` e `django_app/timbri/tests.py`; `python -B django_app\manage.py test timbri.tests.TimbriAnagraficaIntegrationTests.test_operatore_detail_uses_private_anagrafica_photo_route --settings=config.settings.test --verbosity 1 --keepdb` OK; `python -B -c ast.parse(...)` OK su `Y:\current\django_app\timbri\views.py`.
- Backup creati: `Y:\current\django_app\timbri\views.py.bak_20260614_184224`.
- README/CHANGELOG: `CHANGELOG.md` e `django_app/CHANGELOG.md` aggiornati; README non aggiornato perche' fix interna senza cambio URL/setup/dipendenze.

## 2026-06-14 - Codex

- Area: `django_app/timbri`, comando import immagini da share.
- Richiesta: analizzare output prod di `python manage.py import_timbri_da_share --apply --settings=config.settings.prod`, che mostrava `ERRORE: 'charmap' codec can't encode character '\u2713'` per ogni immagine.
- File modificati in questa sessione: `django_app/timbri/management/commands/import_timbri_da_share.py`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno; `_AGENT_CONTROL/CRITICAL_FILES.md` non e' presente nella workspace. Nessuna modifica a ACL, middleware, settings, autenticazione, permessi, routing globale o navigazione globale.
- Motivo tecnico: il comando salvava correttamente file e record `RegistroTimbroImmagine`, poi stampava il simbolo Unicode di spunta dentro lo stesso blocco `try`. Sulla console prod Windows con encoding `charmap`/CP1252 la stampa falliva con `UnicodeEncodeError`, veniva catturata come se fosse un errore di import e impediva il conteggio `Salvate`.
- Modifica: spostato il conteggio successo nel ramo `else` del `try` e sostituito il simbolo Unicode con `OK` ASCII. In questo modo eventuali errori reali di lettura/salvataggio restano tracciati, mentre il logging non trasforma un salvataggio riuscito in `ERRORE`.
- Hotfix prod diretta: applicata la stessa modifica anche su `Y:\current\django_app\timbri\management\commands\import_timbri_da_share.py`, su richiesta esplicita, con backup preventivo `Y:\current\django_app\timbri\management\commands\import_timbri_da_share.py.bak_20260614_183347`.
- Impatto previsto: rilanciando `import_timbri_da_share --apply` in prod il comando non fallisce piu' sulla stampa del successo. Le immagini gia' create dal tentativo precedente risultano come `gia' presente`/saltate grazie al controllo per variante.
- Rischi residui: l'output prod gia' ricevuto indica che molti salvataggi potrebbero essere avvenuti nonostante il messaggio `ERRORE`; prima di rilanciare conviene eseguire il dry-run per verificare se le 180 immagini risultano gia' presenti. Restano da valutare separatamente i casi `Senza cartella`, `Senza record attivo` e `NO FILE`.
- Test/check: `python -m py_compile django_app\timbri\management\commands\import_timbri_da_share.py` OK; `python django_app\manage.py help import_timbri_da_share --settings=config.settings.test` OK; `python -m py_compile Y:\current\django_app\timbri\management\commands\import_timbri_da_share.py` OK con Python locale; verifica `Select-String` conferma nessun simbolo `✓` rimasto nel file prod. Check con `Y:\venv\Scripts\python.exe` non eseguito per runtime prod locale rotto (`did not find executable at C:\Users\administrator\AppData\Local\Programs\Python\Python313\python.exe`).
- Backup creati: `Y:\current\django_app\timbri\management\commands\import_timbri_da_share.py.bak_20260614_183347`.
- README/CHANGELOG: `CHANGELOG.md` e `django_app/CHANGELOG.md` aggiornati; README non aggiornato perche' la modifica riguarda solo compatibilita' output console del comando.

## 2026-06-14 - Codex

- Area: `django_app/dashboard`, home portale `/hub/home/`.
- Richiesta: il flag "Mostra moduli non accessibili" non deve essere visibile, deve essere falso di default e nella home devono comparire solo i moduli visibili/accessibili.
- File modificati in questa sessione: `django_app/dashboard/views_home_portale.py`, `django_app/dashboard/templates/dashboard/pages/home_portale.html`, `django_app/dashboard/tests.py`, `README.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno; `_AGENT_CONTROL/CRITICAL_FILES.md` non e' presente nella workspace. Nessuna modifica a ACL, middleware, settings, autenticazione, permessi, routing globale o navigazione globale.
- Motivo tecnico: la home persisteva in sessione `hp_show_locked` con default precedente `True` e il template esponeva un toggle che permetteva di renderizzare anche tile non accessibili.
- Modifica: `_module_groups()` filtra lato server i moduli non accessibili prima di costruire i gruppi; `home_portale` non legge piu' `hp_show_locked` e non passa piu' `show_locked_modules` al template; il vecchio endpoint `toggle_locked` resta compatibile ma forza la sessione a `False`; il template rimuove il form "Mostra moduli non accessibili", renderizza direttamente solo le tile ricevute e aggiorna i testi a "moduli disponibili".
- Impatto previsto: ogni utente vede nella sezione "Moduli del portale" solo i moduli concessi dal proprio ruolo/utente; eventuali sessioni vecchie con `hp_show_locked=True` non mostrano piu' moduli bloccati. Gli amministratori continuano a vedere tutti i moduli perche' risultano accessibili.
- Rischi residui: nessuno noto sulla sicurezza, perche' la modifica riguarda solo visibilita' UI e non sostituisce i controlli server-side ACL; il vecchio endpoint HTMX e' mantenuto per compatibilita' ma non e' piu' richiamato dal template.
- Test/check: `python django_app\manage.py test dashboard.tests.HomePortaleModuleVisibilityTests dashboard.tests.PriorityKpisTests --settings=config.settings.test --verbosity 2` OK (4 test); `python django_app\manage.py check --settings=config.settings.test` OK; `git diff --check` OK; `rg "Mostra moduli non accessibili|show_locked_modules|hp_show_locked" django_app\dashboard django_app\core -S` conferma nessun testo/toggle visibile nel template, restano solo test ed endpoint compat. Verifica browser fallback su `http://10.0.0.79:8000/hub/home/`: server raggiunto ma redirect a `/login/?next=/hub/home/`, quindi niente verifica visuale autenticata.
- Backup creati: nessuno.
- README/CHANGELOG: `README.md`, `CHANGELOG.md` e `django_app/CHANGELOG.md` aggiornati.

## 2026-06-14 - Codex

- Area: `django_app/anagrafica`, diagnosi lista dipendenti vuota in dev.
- Richiesta: capire perche' in Anagrafica HR non si vedono i dipendenti mentre KPI/altre pagine sembrano avere dati.
- File modificati in questa sessione: `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno; `_AGENT_CONTROL/CRITICAL_FILES.md` non e' presente nella workspace. Nessuna modifica a codice runtime, ACL, middleware, settings, autenticazione, routing globale o navigazione globale.
- Diagnosi: nel DB dev SQL Server la tabella canonica legacy `dbo.anagrafica_dipendenti` non esiste/non e' raggiungibile (`ProgrammingError` SQL Server 208, nome oggetto non valido). La lista `/anagrafica/dipendenti/` usa `core.legacy_anagrafica.fetch_anagrafica_rows()` e quindi ritorna 0 righe. Invece le tabelle Django HR collegate sono presenti e popolate: `DipendenteAnagraficaAziendale` 145 righe, `DipendenteAnagraficaCivile` 145, qualifiche 86, visite 200, record formazione 3399. Esiste anche `dbo.dipendenti` con 138 righe, ma e' una tabella legacy SharePoint/minimale (`title`, `sharepoint_item_id`, date, `utente_id`) e non sostituisce `anagrafica_dipendenti`.
- Ripristino dev applicato: ricreata `dbo.anagrafica_dipendenti` con colonne legacy attese (`id`, `aliasusername`, `nome`, `cognome`, `mansione`, `reparto`, `email`, `email_notifica`, `utente_id`, `matricola`, `ruolo`, `attivo`) e popolata con 145 righe mantenendo gli stessi `legacy_anagrafica_id` delle tabelle HR. Fonte nominativi: `doc/people (2).xlsx` + `doc/Copia di people (3).xlsx`, match 145/145 su codice fiscale gia' presente in `DipendenteAnagraficaCivile`; reparto/ruolo/stato da `DipendenteAnagraficaAziendale`; qualifica corrente come fallback mansione da `StoricoContratto`.
- Backup creato: tabella SQL Server `dbo.anagrafica_dipendenti_recovery_20260614_172410` con copia completa della tabella ricostruita.
- Impatto previsto: `/anagrafica/dipendenti/` torna a mostrare 136 dipendenti in forza e `Ex dipendenti` resta a 9; schede HR e moduli collegati ritrovano la tabella legacy canonica.
- Rischi residui: `utente_id` resta non popolato nel ripristino perche' non c'era match diretto email-account in `utenti`; gli account possono essere riallineati successivamente con le procedure esistenti (`reconcile_usernames`/login sync) se serve. La tabella e' ricostruita da export HR locali, quindi prima di promuovere in ambienti non-dev va usata una sorgente ufficiale controllata.
- Test/check: `fetch_anagrafica_rows(deduplicate=True)` = 145; visibili in lista = 136; `count_anagrafica_statuses` = active 136 / inactive 9; riavviato `runserver` dev su `0.0.0.0:8000`; smoke test Django Client su `/anagrafica/dipendenti/` status 200, contiene `136 dipendenti`, non contiene `Nessun dipendente trovato`.
- Note: nessun codice runtime modificato; README/CHANGELOG non aggiornati perche' non ci sono modifiche funzionali al progetto.

## 2026-06-08 - Codex

- Area: repository completo, commit e push GitHub del branch `feat/acl-chiusura-migrazione-fase1`.
- Richiesta: fare commit e push su GitHub delle modifiche locali.
- File modificati in questa sessione: `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File inclusi nel commit: working tree locale completo su branch `feat/acl-chiusura-migrazione-fase1`, con 2 commit gia' locali e un nuovo commit di integrazione/publish. Perimetro principale gia' documentato in `CHANGELOG.md`/`README.md`: README riallineato, infrastruttura `media_private`, GDPR/cifratura at rest, manutenzione Assets, Timbri permessi copy/download, Anomalie mail action token, Automazioni "Ripeti", normalizzazione date, fix ACL/identita' e varie UI operative.
- File critici modificati/inclusi: `_AGENT_CONTROL/CRITICAL_FILES.md` non e' presente nella workspace; nel perimetro pubblicato sono comunque presenti superfici globali o sensibili gia' modificate nel working tree (`django_app/config/settings/base.py`, deployment PowerShell/IIS, URL/view di moduli, `admin_portale`, storage privati e pagine pubbliche tokenizzate Anomalie). Motivo tecnico: pubblicare lo stato locale esistente richiesto dall'utente; questa sessione non ha introdotto modifiche funzionali aggiuntive su tali file.
- Impatto previsto: GitHub riceve i commit locali gia' presenti piu' il commit di integrazione del working tree corrente; il branch remoto si allinea alla workspace locale.
- Rischi residui: commit molto ampio e multi-area; richiede review funzionale mirata prima di promozione in produzione, soprattutto per superfici pubbliche tokenizzate, settings/middleware, deploy, storage cifrati e ACL/permessi.
- Test/check: `git diff --check` OK; `python django_app\manage.py check --settings=config.settings.test` OK; scansione basilare diff/untracked per pattern secret senza valori reali evidenti (solo riferimenti a token/secret nel codice e nella documentazione).
- Note: `gh` non installato, quindi nessuna draft PR creata tramite GitHub CLI; pubblicazione prevista via `git push`. Nessun backup creato; README e CHANGELOG risultano gia' aggiornati nel working tree.

## 2026-06-04 - Codex

- Area: `django_app/automazioni/packages`, conversione flow Power Automate RENTRI.
- Richiesta: analizzare `rentri_20260604152402.zip`, fare riferimento anche ai flussi gia' presenti in `django_app/automazioni/packages` e creare un package importabile.
- File modificati/creati: `django_app/automazioni/packages/pa_rentri_modifica_elemento_promemoria.automation_package.json` (nuovo), `django_app/automazioni/packages/HANDOFF_AUTOMAZIONI.md`, `README.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno; `_AGENT_CONTROL/CRITICAL_FILES.md` non e' presente nella workspace. Nessuna modifica a runtime, ACL, middleware, settings, autenticazione, routing globale o navigazione globale.
- Motivo tecnico: convertire il flow Power Automate SharePoint/Outlook `RENTRI - MODIFICA ELEMENTO` in regole Automazioni importabili e coerenti con il catalogo AU esistente, senza introdurre dipendenze o chiamate esterne.
- Modifica: aggiunto package `pa_rentri_modifica_elemento_promemoria` su sorgente `rentri`, con 3 regole draft/inattive: notifica nuovo carico, controllo differito a 5 giorni per carico non marcato RENTRI e controllo differito a 30 giorni per FIR mancante. Le attese del flow sono modellate con `do_until` e retry differito; il package documenta i limiti rispetto a `GetItemChanges` e al calcolo `Data + 30 giorni` di Power Automate. Handoff e README aggiornati a 29 package importabili.
- Riferimenti ai flussi esistenti: il package cita `au31_scarico_senza_fir_notifica.automation_package.json` come presidio immediato FIR e `docs/automation_packages/rentri_movimenti_da_trasmettere.automation_package.json` per i movimenti consolidati da trasmettere, cosi' da evitare destinatari/attivazioni duplicate.
- Impatto previsto: il package puo' essere importato da Automazioni -> Regole -> Importa package e configurato nel designer; nessuna regola viene attivata automaticamente.
- Rischi residui: i controlli differiti usano il payload della queue e non rileggono automaticamente SharePoint/DB come `GetItemChanges`; prima dell'attivazione verificare su record reali oppure valutare un job schedulato che rilegga lo stato corrente. I destinatari `RENTRI_DA_CONFIGURARE` vanno sostituiti.
- Test/check: JSON valido con `python -m json.tool`; `analyze_package_dict` con `config.settings.test` OK (`status=ready`, 3/3 regole importabili); `run_package_dry_run` OK su campioni sintetici carico/scarico.
- Note: nessun backup creato; lo zip sorgente `rentri_20260604152402.zip` e' rimasto invariato.

## 2026-05-29 - Codex

- Area: `docs/email_templates`, mockup grafico email automazioni.
- Richiesta: chiarimento su template grafico per le email delle automazioni, inteso come layout visivo.
- File modificati/creati: `docs/email_templates/automation_email_graphic_template.html` (nuovo), `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno; `_AGENT_CONTROL/CRITICAL_FILES.md` non e presente nella workspace. Nessuna modifica a runtime, ACL, middleware, settings, autenticazione, routing globale o navigazione globale.
- Motivo tecnico: fornire una preview grafica concreta e apribile nel browser, separata dalla logica automazioni, da usare come riferimento prima di integrare un renderer email nel portale.
- Modifica: creato mockup HTML statico con layout email-safe a tabelle/inline style: header NOVICROM HUB con logo reale `django_app/core/static/core/img/logo_novicrom.png`, badge automazione, riepilogo richiesta, box scadenza, CTA approva/rifiuta/dettaglio, footer e pannello laterale con palette/varianti.
- Impatto previsto: nessun impatto runtime; il file e solo un prototipo visuale/documentale.
- Rischi residui: prima dell'uso reale in produzione andra verificata la resa nei client email target, in particolare Outlook desktop.
- Test/check: verifica manuale del file creato; nessun test Django eseguito perche modifica documentale/prototipale.
- Note: nessun backup creato; README, `CHANGELOG.md` e `django_app/CHANGELOG.md` non aggiornati perche non cambia comportamento operativo, URL, setup o dipendenze.

## 2026-05-28 - Codex

- Area: `django_app/assenze`, richiesta assenza / caporeparto e regole orario.
- Richiesta: nella nuova richiesta assenza, leggere il capo reparto dai caporeparto configurati in Anagrafica HR e predefinire quello effettivo del dipendente; impostare data inizio/fine sul giorno corrente e controllare permessi/ferie.
- File modificati: `django_app/assenze/views.py`, `django_app/assenze/templates/assenze/pages/richiesta_assenze.html`, `django_app/assenze/tests.py`, `README.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non e presente nella workspace. Modifica in area `assenze` eseguita su richiesta esplicita dell'utente; nessuna modifica a ACL, middleware, settings, autenticazione, routing globale o navigazione globale.
- Motivo tecnico: il form usava ancora sorgenti locali/legacy per il menu caporeparto e precompilava con mapping/storico; inoltre il default data fine era domani e mancavano regole specifiche per ferie e permessi.
- Modifica: `_load_capi_options()` privilegia i caporeparto dei Reparti Anagrafica HR, mappando il caporeparto HR al relativo utente legacy quando disponibile; `_resolve_default_capo_for_user()` usa prima il caporeparto effettivo del dipendente da `DipendenteAnagraficaAziendale`/Reparto. La richiesta apre data inizio e fine sul giorno corrente; Ferie forza `00:00-23:59`, Permesso resta nello stesso giorno. Aggiunti controlli coerenti lato JS e backend.
- Impatto previsto: il capo reparto selezionabile e quello predefinito seguono Anagrafica HR, riducendo selezioni manuali sbagliate; ferie e permessi non generano intervalli incoerenti.
- Rischi residui: se un caporeparto HR non ha account `utenti` collegato in `anagrafica_dipendenti.utente_id`, puo comparire in lista ma non essere assegnabile come approvatore legacy; va mantenuto il collegamento account in Anagrafica HR.
- Test/check: `python django_app\manage.py test assenze.tests.AssenzeSubmitTokenTests assenze.tests.AssenzeCaporepartoLocalSourceTests --settings=config.settings.test --verbosity 2` OK (15 test). `manage.py check` e `git diff --check` eseguiti a fine sessione.
- Note: nessun backup creato; README, CHANGELOG e `django_app/CHANGELOG.md` aggiornati.

- Area: `django_app/admin_portale`, vista utenti.
- Richiesta: sistemare `/admin-portale/utenti/` e renderla fullpage.
- File modificati: `django_app/admin_portale/templates/admin_portale/pages/utenti_list.html`, `django_app/admin_portale/tests.py`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno da `_AGENT_CONTROL/CRITICAL_FILES.md` perche il file non e presente nella workspace; area `admin_portale` modificata su richiesta esplicita. Nessuna modifica a ACL, middleware, settings, autenticazione, routing globale, permessi o navigazione globale.
- Motivo tecnico: la pagina utenti era composta da card impilate e lasciava poco spazio operativo alla tabella, rendendo scomoda la gestione utenti/ruoli su schermi desktop.
- Modifica: aggiunta classe pagina fullpage, contenitore workspace a tutta larghezza/altezza, form "Nuovo Utente" richiudibile, filtri compatti in barra superiore, toolbar azioni massive e tabella utenti con scroll interno e header sticky. Il link import LDAP/AD resta nel page header; endpoint e azioni POST esistenti invariati.
- Impatto previsto: gestione utenti piu densa e leggibile, con tabella come superficie principale della pagina e creazione utente ancora disponibile senza occupare spazio costante.
- Rischi residui: verifica visuale reale oltre login non eseguita per assenza di sessione admin nel browser locale; test client copre render/route/template. Il template `utenti_list.html` era read-only ed e stato sbloccato per applicare la patch.
- Test/check: `python django_app\manage.py test admin_portale.tests.AdminPortaleUtentiListLayoutTests --settings=config.settings.test --verbosity 1` OK; `python django_app\manage.py check --settings=config.settings.test` OK; `git diff --check -- django_app/admin_portale/templates/admin_portale/pages/utenti_list.html django_app/admin_portale/tests.py` OK; browser locale su `http://127.0.0.1:8000/admin-portale/utenti/` arriva correttamente al redirect login.
- Note: nessun backup creato; README non aggiornato perche cambia solo layout UX della vista, non URL/setup/dipendenze o comportamento operativo backend.

- Area: `django_app/ai_assistant` / `django_app/admin_portale`, diagnosi errore cancellazione utente in produzione.
- Richiesta: analizzare errore SQL Server `42S02` su cancellazione utente per tabella mancante `ai_assistant_aitoolprivacyreview`.
- File modificati: `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno; nessuna modifica a codice runtime, ACL, middleware, settings, autenticazione, routing o navigazione globale.
- Motivo tecnico: `admin_portale.views._delete_legacy_user_with_dependencies` elimina anche il profilo `auth.User`; la cancellazione Django segue le FK verso `AiToolPrivacyReview.reviewed_by` (`on_delete=SET_NULL`) e quindi interroga la tabella `ai_assistant_aitoolprivacyreview`.
- Diagnosi: i file migration `ai_assistant/0002_aitoolprivacyreview.py` e `0003_aichatfeedback.py` sono presenti sia nella workspace locale sia in `Y:\current`; l'errore indica schema DB produzione non allineato alla release, oppure migration marcata applicata senza tabella fisica.
- Impatto previsto: applicare/verificare le migration prod `ai_assistant.0002` e successive risolve la cancellazione utente e riallinea la console Governance AI.
- Rischi residui: se `django_migrations` in prod segnala `ai_assistant.0002` come applicata ma la tabella non esiste, serve intervento DB controllato (`migrate --fake ai_assistant zero` non va usato alla cieca su prod); verificare prima tabella e righe `django_migrations`.
- Test/check: lettura codice `AiToolPrivacyReview`, migration `0002`, `utente_delete`/`_delete_legacy_user_with_dependencies`; verifica presenza migration su `Y:\current`. Nessun test eseguito per assenza di modifica runtime.
- Note: correzione operativa consigliata: eseguire `showmigrations ai_assistant` e `migrate ai_assistant` sull'ambiente prod con account runtime/admin DB, poi riciclare App Pool/IIS.

- Area: `django_app/core`, notifiche portale.
- Richiesta: verificare e rendere essenziale il funzionamento delle notifiche interne al portale, incluso popup live.
- File modificati: `django_app/core/views.py`, `django_app/core/urls.py`, `django_app/core/templates/core/base.html`, `django_app/core/templates/core/components/topnav.html`, `django_app/core/templates/core/components/sidebar.html`, `django_app/core/static/core/css/theme.css`, `django_app/core/tests.py`, `README.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: `django_app/core/urls.py`, `django_app/core/views.py`, `django_app/core/templates/core/base.html`, `django_app/core/templates/core/components/topnav.html`, `django_app/core/templates/core/components/sidebar.html` per routing API notifiche e layout globale autenticato. `_AGENT_CONTROL/CRITICAL_FILES.md` non e presente nella workspace; nessuna modifica a ACL, middleware, settings, autenticazione o permessi.
- Motivo tecnico: il centro notifiche aggiornava il pannello via HTMX e il banner popup solo al render pagina; una notifica creata durante la sessione non produceva popup live senza refresh.
- Modifica: aggiunto endpoint JSON `/api/notifiche/live/` filtrato sull'utente legacy corrente, con conteggio non lette e payload popup non ancora mostrati; il layout globale ora polla ogni 15 secondi, aggiorna i badge topbar/sidebar, mostra toast live in-app, marca `popup_shown` solo per notifiche dell'utente corrente e rinfresca il pannello HTMX quando arrivano popup.
- Impatto previsto: le notifiche restano consultabili dal centro esistente e quelle nuove possono apparire come popup live senza ricaricare la pagina; l'ack popup resta limitato all'utente autenticato.
- Rischi residui: verifica visuale browser/in-app non eseguita per tool browser non esposto e Playwright Python non installato; copertura tramite test client Django, render template e check statici OK. La latenza live e polling leggero di circa 15 secondi, non WebSocket.
- Test/check: `python django_app\manage.py test core.tests.CoreBacklogCFeatureTests.test_live_notifications_api_returns_badge_count_and_popup_payload core.tests.CoreBacklogCFeatureTests.test_popup_ack_marks_only_current_user_notifications core.tests.CoreBacklogCFeatureTests.test_base_template_loads_live_notification_client core.tests.CoreBacklogCFeatureTests.test_notification_panel_lists_unread_notifications core.tests.CoreBacklogCFeatureTests.test_mark_all_notifications_read --settings=config.settings.test --verbosity 1` OK; `python django_app\manage.py check --settings=config.settings.test` OK; `git diff --check -- django_app/core/views.py django_app/core/urls.py django_app/core/templates/core/base.html django_app/core/templates/core/components/topnav.html django_app/core/templates/core/components/sidebar.html django_app/core/static/core/css/theme.css django_app/core/tests.py README.md CHANGELOG.md django_app/CHANGELOG.md` OK.
- Note: nessun backup creato; README e CHANGELOG aggiornati per documentare notifiche live.

- Area: `django_app/anagrafica`, scheda dipendente / offboarding.
- Richiesta: rendere piu carino e compatto il blocco uscita dipendente e togliere la doppia data visibile.
- File modificati: `django_app/anagrafica/templates/anagrafica/pages/dipendente_detail.html`, `django_app/anagrafica/views.py`, `django_app/anagrafica/tests.py`, `README.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno; `_AGENT_CONTROL/CRITICAL_FILES.md` non e presente nella workspace. Nessuna modifica a ACL, middleware, settings, autenticazione, routing globale, navigazione globale o dati sensibili.
- Motivo tecnico: il form offboarding nella hero esponeva due date (`data_cessazione` e `ultimo_giorno_operativo`) creando ambiguita e ingombro visivo.
- Modifica: nella hero resta una sola "Data uscita"; il campo restituzioni e diventato un menu compatto a comparsa; il riepilogo pratica mostra "Ultimo giorno operativo" solo se differisce dalla data uscita. La view mantiene compatibilita: se `ultimo_giorno_operativo` non viene inviato, lo imposta uguale alla data uscita.
- Impatto previsto: avvio pratica offboarding piu chiaro e compatto; nessuna migrazione DB e nessuna rottura per eventuali integrazioni che passano ancora `ultimo_giorno_operativo` esplicitamente.
- Rischi residui: verifica visuale browser non eseguita su pagina reale autenticata; copertura template/view via test client OK.
- Test/check: `python django_app\manage.py check --settings=config.settings.test` OK; `python django_app\manage.py test anagrafica.tests.AnagraficaDipendentiViewTests.test_offboarding_licenziamento_creates_pratica_then_closes_employee --settings=config.settings.test --verbosity 2` OK; `git diff --check -- django_app/anagrafica/templates/anagrafica/pages/dipendente_detail.html django_app/anagrafica/views.py django_app/anagrafica/tests.py README.md CHANGELOG.md django_app/CHANGELOG.md` OK.
- Note: nessun backup creato; README aggiornato per allineare la descrizione offboarding alla data unica.

- Area: `django_app/automazioni`, action runtime Assenze / package Power Automate.
- Richiesta: chiarire e implementare lo split multi-giorno del flow Power Automate calendario assenze (`Do until` + `addDays`) nel portale.
- File modificati/creati: `django_app/automazioni/models.py`, `django_app/automazioni/migrations/0014_split_assenza_giornaliera_action.py` (nuovo), `django_app/automazioni/services.py`, `django_app/automazioni/forms.py`, `django_app/automazioni/views.py`, `django_app/automazioni/package_importer.py`, `django_app/automazioni/templates/automazioni/components/action_card.html`, `django_app/automazioni/templates/automazioni/pages/rule_designer.html`, `django_app/automazioni/tests.py`, `docs/automation_packages/assenze_calendario_avviso_inserimento.automation_package.json`, `docs/automation_packages/README.md`, `docs/ai/AUTOMATION_PACKAGE_REFERENCE.md`, `README.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno; `_AGENT_CONTROL/CRITICAL_FILES.md` non e presente nella workspace. Nessuna modifica a ACL, middleware, settings, autenticazione, routing globale, navigazione globale o dati sensibili.
- Motivo tecnico: il package precedente rappresentava approval/update/email ma non aveva un equivalente runtime per creare le righe giornaliere derivate che il flow Power Automate generava su SharePoint.
- Modifica: aggiunta action `split_assenza_giornaliera` con choice/migration, executor SQL Server/SQLite su sorgente `assenze`, calcolo date da `data_inizio`/`data_fine` o campi numero giorni, deduplica naturale, reset contatore giorni derivati a 1 e stato approvato sulle righe create. Aggiunti form, preset/preview designer, stile diagramma, normalizzazione/validazione/dry-run import package e documentazione. Il package calendario assenze v1.1 ora inserisce lo split nei rami approvato e salta-approvazione e blocca la regola skip sui record gia approvati per evitare loop sulle righe derivate.
- Impatto previsto: importando/aggiornando il package, il portale puo sostituire anche il loop multi-giorno del flow storico creando record `assenze` giornalieri derivati senza duplicarli in caso di retry.
- Rischi residui: la deduplica usa campi naturali (`dipendente`, date, tipo, motivazione) perche lo schema legacy non espone un parent id dedicato; se un caso reale richiede due permessi identici per stesso dipendente/stesso orario/stessa motivazione potrebbero essere considerati duplicati. I destinatari email del package restano da verificare prima dell'attivazione.
- Test/check: `python django_app/manage.py test automazioni.tests.AutomationAssenzeSplitActionTests` OK; `python django_app/manage.py test automazioni.tests.AutomationAssenzeSplitActionTests automazioni.tests.AutomationActionFormExtendedTests.test_split_assenza_giornaliera_form_builds_config_for_assenze automazioni.tests.AutomationPackageImportTests.test_dry_run_supports_split_assenza_giornaliera_inline_action` OK; `python django_app/manage.py test automazioni.tests.AutomationPackageImportTests automazioni.tests.AutomationActionFormExtendedTests` OK (31 test); `python django_app/manage.py check` OK; `python django_app/manage.py makemigrations automazioni --check --dry-run` OK; package JSON `analyze_package_dict` OK (`status=ready`, 6/6 importabili); `git diff --check` OK sui file toccati; Playwright aperto su `https://hub.cnovicrom.local/.../designer/` fino al redirect login.
- Note: nessun backup creato; migration `automazioni.0014_split_assenza_giornaliera_action` da applicare prima di usare la nuova action in ambienti non migrati.

## 2026-05-28 - Codex

- Area: `docs/automation_packages`, conversione Power Automate calendario assenze.
- Richiesta: usare `docs/automation_packages/power automate/BCK - Calendario assenze - avviso di inserimento.json` come base per un package Automazioni, trattando insert/update SharePoint come equivalenti alla tabella SQL Server del portale.
- File modificati/creati: `docs/automation_packages/assenze_calendario_avviso_inserimento.automation_package.json` (nuovo), `docs/automation_packages/README.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno; `_AGENT_CONTROL/CRITICAL_FILES.md` non e presente nella workspace. Nessuna modifica a ACL, middleware, settings, autenticazione, routing globale, navigazione globale o codice runtime.
- Motivo tecnico: il flow Power Automate e un export ARM con trigger su nuovo elemento calendario assenze, approval, notifiche email e azioni su elementi SharePoint; nel portale queste azioni corrispondono alla sorgente `assenze` su SQL Server.
- Modifica: aggiunto package draft/inattivo con 6 regole importabili: richiesta approvazione caporeparto, ramo `salta_approvazione`, avviso post-approvazione, assemblea sindacale, flessibilita e malattia. Gli update di stato sono modellati con `update_trigger_record`; le email usano mailbox di ruolo o placeholder runtime. Lo split multi-giorno del flow originale e documentato come logica runtime/custom action da completare, per evitare insert derivati senza calcolo date equivalente.
- Impatto previsto: il package puo essere importato da `Automazioni -> Regole -> Importa package`, verificato nel designer e attivato dopo rifinitura destinatari/template. Non contiene URL SharePoint, token o segreti.
- Rischi residui: la parte Power Automate `Do until`/`addDays` che crea record giornalieri derivati non e automatizzata dal package; se serve sostituirla completamente va implementata nel modulo Assenze o come action dedicata. I destinatari di ruolo vanno confermati prima dell'attivazione.
- Test/check: parse JSON OK; `analyze_package_dict` con `config.settings.test` OK (`status=ready`, 6/6 regole importabili); `run_package_dry_run` OK su campioni pending approval, skip approval e flessibilita approvata; `git diff --check -- docs/automation_packages/assenze_calendario_avviso_inserimento.automation_package.json docs/automation_packages/README.md` OK.
- Note: nessun backup creato; README di cartella aggiornato, README/CHANGELOG di progetto non aggiornati perche non cambia comportamento runtime.

## 2026-05-28 - Codex

- Area: `django_app/automazioni`, designer visuale / workspace diagramma.
- Richiesta: sistemare la schermata del diagramma di flusso aperta da `/admin-portale/automazioni/regole/<id>/designer/`.
- File modificati: `django_app/automazioni/templates/automazioni/pages/rule_designer.html`, `django_app/automazioni/tests.py`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno; `_AGENT_CONTROL/CRITICAL_FILES.md` non e presente nella workspace. Nessuna modifica a ACL, middleware, settings, autenticazione, routing globale, navigazione globale o dati runtime.
- Motivo tecnico: il template del designer conteneva label/simboli gia corrotti da mojibake nel pulsante e nella toolbar del diagramma (`ðŸ...`, `âœ...`, `Â·`) e l'editor inline nel pannello sinistro poteva generare overflow orizzontale/taglio dei campi.
- Modifica: sostituiti i label visibili del diagramma con testi puliti (`Diagramma di flusso`, `PNG`, `Chiudi`, `+ Aggiungi azione`), normalizzati i fallback JS del diagramma, disegnata la maniglia drag via CSS invece di testo corrotto, aggiunto `box-sizing` ai campi, inspector sinistro con `overflow-x:hidden`, editor inline a colonna singola e lock anche su `html` quando la workspace e aperta.
- Impatto previsto: la workspace del diagramma risulta leggibile senza caratteri corrotti e il pannello inspector resta stabile mentre si modifica una card azione.
- Rischi residui: verifica browser locale completa non conclusa perche il server gia attivo su `127.0.0.1:8000` reindirizza al login; copertura via test client e check Django OK.
- Test/check: `python django_app\manage.py test automazioni.tests.AutomazioniAdminPageTests.test_rule_designer_page_renders_visual_blocks_and_human_summary --settings=config.settings.test --verbosity 2` OK; `python django_app\manage.py check --settings=config.settings.test` OK; `git diff --check -- django_app/automazioni/templates/automazioni/pages/rule_designer.html django_app/automazioni/tests.py CHANGELOG.md django_app/CHANGELOG.md` OK; Playwright su `127.0.0.1:8000` verificato fino alla pagina login.
- Note: nessun backup creato; README non aggiornato perche non cambia comportamento operativo, URL, setup o dipendenze.

- Area: `docs/automation_packages`, automazioni importabili.
- Richiesta: creare flussi importabili facendo riferimento a `docs/ai/AUTOMATION_PACKAGE_REFERENCE.md`.
- File modificati/creati: `docs/automation_packages/README.md` (nuovo), `docs/automation_packages/assenze_approvazione_caporeparto.automation_package.json` (nuovo), `docs/automation_packages/tickets_notifiche_operativi.automation_package.json` (nuovo), `docs/automation_packages/dpi_richiesta_stato.automation_package.json` (nuovo), `docs/automation_packages/offboarding_notifiche_hr_it.automation_package.json` (nuovo), `docs/automation_packages/formazione_completamento_hr.automation_package.json` (nuovo), `docs/automation_packages/visite_mediche_esiti_critici.automation_package.json` (nuovo), `docs/automation_packages/rentri_movimenti_da_trasmettere.automation_package.json` (nuovo), `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno; `_AGENT_CONTROL/CRITICAL_FILES.md` non e presente nella workspace. Nessuna modifica a ACL, middleware, settings, autenticazione, routing globale, navigazione globale o dati runtime.
- Motivo tecnico: serviva un set di package `.automation_package.json` gia pronti per l'import nel modulo Automazioni, coerenti con la guida e con il validatore reale `automazioni.package_importer`.
- Modifica: aggiunta cartella `docs/automation_packages/` con 7 package separati per sorgente (`assenze`, `tickets`, `dpi`, `anagrafica_offboarding`, `anagrafica_formazione_record`, `anagrafica_visite_mediche`, `rentri`) e un README operativo. Ogni package contiene `approved_field_mapping`, regole draft/inattive, condizioni conservative, azioni email/log e, per il flusso assenze, `update_trigger_record` per impostare `moderation_status` dopo approvazione/rifiuto.
- Impatto previsto: l'operatore puo importare i file da `Automazioni -> Regole -> Importa package`, verificarli in dry-run e adattare destinatari/template prima dell'attivazione. I package non contengono segreti, webhook URL o token.
- Rischi residui: gli indirizzi email sono mailbox di ruolo placeholder (`hr@`, `it@`, `dpi@`, ecc.) e vanno confermati prima dell'attivazione; i flussi che notificano su condizioni frequenti possono generare email duplicate se piu regole combaciano sullo stesso evento.
- Test/check: parser JSON OK su 7 package; `analyze_package_dict` con `config.settings.test` OK, tutti `status=ready` e `importable=12/12` regole totali; `run_package_dry_run` con payload sintetico registry OK su 7 package; `git diff --check -- docs/automation_packages` OK.
- Note: nessun backup creato; nessuna modifica a README/CHANGELOG di progetto perche sono stati aggiunti solo artifact documentali/importabili senza cambiare comportamento runtime.

## 2026-05-26 - Codex

- Area: `django_app/assets`.
- Richiesta: preparare un modo sicuro per rinominare massivamente solo il campo nome degli asset, senza modificare `asset_tag` o altri dati.
- File modificati: `django_app/assets/management/commands/rename_asset_names.py` (nuovo), `django_app/assets/tests.py`, `django_app/assets/README.md`, `README.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non e presente nella workspace. Modifica in area `assets` autorizzata dalla richiesta esplicita dell'utente; nessuna modifica a ACL, middleware, settings, routing globale, autenticazione o navigazione globale.
- Motivo tecnico: l'import/catalogo asset puo aggiornare piu campi operativi; per rimuovere prefissi testuali dai nomi serviva invece una procedura dedicata e limitata al solo `Asset.name`, agganciata a `asset_tag` come chiave stabile.
- Modifica: aggiunto management command `rename_asset_names` con export template CSV `asset_tag;current_name;new_name`, lettura CSV UTF-8/cp1252 con separatore `;`/`,`, dry-run di default, `--commit` esplicito in transazione, validazioni su tag mancanti/duplicati, nomi vuoti/lunghi e asset non trovati. Il commit salva solo `name` e `updated_at`.
- Impatto previsto: l'operatore puo esportare il template, correggere in Excel solo la colonna `new_name` (es. rimuovendo `Macchine CNC | ` o `Frese | `), verificare le rinomine in dry-run e poi applicarle senza toccare tag, categorie, stato, reparto, SharePoint o relazioni.
- Rischi residui: la correttezza dei nuovi nomi dipende dal CSV revisionato; se si usa un export diverso dal template bisogna indicare correttamente `--tag-column` e `--name-column`. Il comando blocca il commit in presenza di errori riga per riga.
- Test/check: `python -m py_compile django_app\assets\management\commands\rename_asset_names.py` OK; `python django_app\manage.py test assets.tests.RenameAssetNamesCommandTests --settings=config.settings.test --verbosity 2` OK (4 test); `python django_app\manage.py check --settings=config.settings.test` OK; `python django_app\manage.py help rename_asset_names --settings=config.settings.test` OK; `git diff --check` OK sui file modificati in questa sessione.
- Note: nessun backup runtime creato perche non e stato eseguito alcun commit dati; il comando opera sul DB solo quando l'utente lancia `--commit`.

## 2026-05-26 - Codex

- Area: configurazione runtime / deploy / navigazione globale.
- Richiesta: spiegare e correggere perche il `.env` produttivo puo cambiare flag critici (LDAP prima, Navigation Registry ora) e impedire lettura casuale del file con Notepad.
- File modificati: `django_app/hub_tools/views.py`, `django_app/hub_tools/templates/hub_tools/setup_wizard.html`, `django_app/hub_tools/tests.py`, `django_app/config/env_config.py`, `django_app/config/test_env_config.py`, `deployment/scripts/secure-env-acl.ps1` (nuovo), `deployment/scripts/deploy-release.ps1`, `deployment/scripts/configure-iis-site.ps1`, `README.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: `_AGENT_CONTROL/CRITICAL_FILES.md` non e presente nella workspace. Modificati file critici per configurazione runtime/deploy (`config/env_config.py`, `hub_tools/views.py`, script deploy/IIS) e navigazione globale (`NAVIGATION_*` nel salvataggio Hub Setup Wizard) per correggere un drift produttivo richiesto esplicitamente.
- Motivo tecnico: il Setup Wizard Hub leggeva/scriveva la copia `django_app/.env` della release invece del sorgente persistente `ENV/config/.env` e, a ogni salvataggio, forzava `NAVIGATION_LEGACY_FALLBACK_ENABLED=1`. Questo poteva riportare la sidebar al fallback legacy anche con Navigation Builder ripristinato. Inoltre i file `.env` non avevano un hardening NTFS dedicato nel flusso deploy.
- Modifica: `_ENV_PATH` del Setup Wizard Hub usa ora `primary_runtime_env_path(_APP_DIR)`, quindi in deploy punta al `config/.env` persistente; `api_reconfigure` imposta `NAVIGATION_LEGACY_FALLBACK_ENABLED=0` quando `NAVIGATION_REGISTRY_ENABLED=1` e lo riattiva solo se il registry viene disabilitato. Il testo UI della sezione Navigazione e stato riallineato. `config/env_config.py` legge `.env` con `utf-8-sig` per tollerare BOM UTF-8 da Notepad. Aggiunto `secure-env-acl.ps1` e invocazione da deploy/configurazione IIS per restringere ACL su `ENV/config/.env` e sulle copie release `.env`.
- Impatto previsto: salvare il Setup Wizard Hub non rimette piu il menu in fallback legacy; le modifiche runtime finiscono nel file persistente corretto; i `.env` sono leggibili solo da SYSTEM, Administrators locali e identita AppPool, con copie release read-only per l'AppPool.
- Rischi residui: il file persistente `ENV/config/.env` resta modificabile dall'AppPool per mantenere funzionanti i pannelli admin che salvano configurazione; per bloccare ogni scrittura web bisognerebbe disabilitare o ridisegnare quei flussi. L'hardening NTFS va applicato al server con lo script aggiornato o tramite una release/hotfix che lo includa.
- Test/check: parser PowerShell OK su `secure-env-acl.ps1`, `deploy-release.ps1`, `configure-iis-site.ps1`; `python django_app\manage.py test hub_tools.tests.HubSetupWizardEnvTests config.test_env_config.RuntimeEnvPathTests --settings=config.settings.test --verbosity 1` OK (10 test); AST Python OK sui file modificati; `python django_app\manage.py check --settings=config.settings.dev` OK; `git diff --check` OK. `python -m py_compile ...` non completato per Access denied su scrittura `.pyc` in `django_app/config/__pycache__`, sostituito con AST check senza bytecode.
- Note: nessun valore `.env` o segreto stampato; nessun backup runtime creato in questa sessione. File `django_app/config/env_config.py` e `django_app/config/test_env_config.py` erano read-only e sono stati sbloccati per la patch.

## 2026-05-26 - Codex

- Area: navigazione globale / Navigation Registry.
- Richiesta: avere il menu come nell'ambiente TEST locale di questo PC.
- File modificati: `django_app/core/management/commands/restore_navigation_registry.py` (nuovo), `README.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: `_AGENT_CONTROL/CRITICAL_FILES.md` non e presente nella workspace. Intervento su area critica "navigazione globale" limitato a un nuovo management command operativo; nessuna modifica diretta a settings, middleware, autenticazione, ACL grants, routing globale o dati `NavigationItem` in DB.
- Motivo tecnico: il menu della working copy locale `C:\Dev\Portale Novicrom` esiste come dump `django_app/fixtures/nav_acl_snapshot.json` e come registry locale sano; serve un modo controllato per ripristinare lo stesso registry in un ambiente target senza caricare anche permessi/utenti dal fixture completo.
- Modifica: aggiunto comando `restore_navigation_registry` con dry-run di default e `--apply` esplicito. Il comando legge un dump JSON Django serializer (default `django_app/fixtures/nav_acl_snapshot.json`), considera solo `ModuleCategory`, `NavigationItem` e `NavigationRoleAccess`, mostra topbar sorgente/corrente, in apply pubblica prima uno snapshot di backup, sostituisce solo il registry di navigazione e invalida la cache menu.
- Esito operativo: dry-run locale OK; la sorgente della working copy mostra 15 voci topbar (`Assenze`, `Diario preposto`, `Rentri`, `Tickets`, `Asset`, `Segnalazioni sicurezza`, `Anagrafica`, `KICK-OFF`, `Notizie`, `Gestione Anomalie`, `Gestione Attrezzatura`, `Timbri`, `Accessi azienda`, `DPI`, `Presa Visione`). Il restore non e stato applicato su `Y:` perche la connessione SQL diretta da questa sessione viene rifiutata dall'autenticazione Windows dell'utente locale; va eseguito sul target con l'account runtime/admin che ha accesso al DB.
- Impatto previsto: dopo deploy/copia del comando nell'ambiente target, l'operatore puo eseguire prima dry-run e poi apply per riportare il Navigation Builder/topbar allo stato del TEST locale, con snapshot di rollback automatico.
- Rischi residui: il comando `--apply` elimina e ricrea tutte le `NavigationItem`; eventuali override per-utente collegati a vecchi record possono decadere per cascade se presenti nel DB target. Lo snapshot di backup consente rollback tramite Navigation Builder/restore snapshot. Nessun dato di produzione e stato modificato in questa sessione.
- Test/check: `python django_app\manage.py restore_navigation_registry --settings=config.settings.dev` dry-run OK; `python -m py_compile django_app\core\management\commands\restore_navigation_registry.py` OK; `python django_app\manage.py help restore_navigation_registry --settings=config.settings.dev` OK; `python django_app\manage.py check --settings=config.settings.dev` OK.
- Note: nessun backup runtime creato perche non e stato eseguito `--apply`; il comando creera snapshot di backup automaticamente quando lanciato in apply.

## 2026-05-26 - Codex

- Area: navigazione globale / Navigation Builder.
- Richiesta: aiutare a ripristinare le voci della navbar/topbar mostrate vuote nel Navigation Builder.
- File modificati: `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessun file critico applicativo modificato. Verificata area critica "navigazione globale" solo in lettura; nessuna modifica a ACL, middleware, settings, autenticazione, routing globale, `NavigationItem` o dati DB.
- Diagnosi locale: con `config.settings.dev` il Navigation Registry non e vuoto: `NavigationItem total=37`, sezioni `admin_subnav=21`, `page=1`, `topbar=15`; le 15 voci topbar visibili/attive includono `assenze`, `assets`, `anagrafica`, `notizie`, `tasks/KICK-OFF`, `anomalie`, `attrezzature`, `timbri`, `accessi`, `dpi`, `procedure_refresh`, ecc.
- Backup disponibile: `django_app/fixtures/nav_acl_snapshot.json` contiene 37 `NavigationItem`, di cui 15 `topbar`, coerenti con lo stato sano locale. Lo snapshot DB interno disponibile e vecchio/incompleto (`v1`, 4 item, 3 topbar) e non e il candidato migliore per un restore completo.
- Verifica produzione: tentata una lettura non invasiva usando `Y:\config\.env` e `config.settings.prod`, ma la connessione e andata in timeout prima di restituire conteggi; il processo Python appeso e stato chiuso manualmente. Nessun valore `.env` o segreto e stato stampato.
- Ipotesi operative: lo screenshot probabilmente punta a un ambiente diverso da `config.settings.dev`, oppure a una vista filtrata/cachata/fallback legacy. La nota ricorrente nel checkpoint resta valida: controllare `NAVIGATION_REGISTRY_ENABLED=1` e `NAVIGATION_LEGACY_FALLBACK_ENABLED=0/compat` nell'ambiente effettivo, poi invalidare cache/sessioni/IIS se necessario.
- Test/check: query read-only Django shell su DB dev OK; ispezione read-only fixture JSON OK; controllo processi Python dopo timeout OK. Nessun test applicativo eseguito perche non sono stati modificati codice o dati applicativi.
- Note: nessun backup nuovo creato; nessun restore eseguito.

## 2026-05-26 - Codex

- Area: `django_app/anagrafica`, impostazioni Anagrafica HR / workflow onboarding-offboarding.
- Richiesta: creare nella pagina impostazioni una sezione dove associare i campi da compilare in `+ Nuovo dipendente` alla lista onboarding-offboarding.
- File modificati: `django_app/anagrafica/models.py`, `django_app/anagrafica/migrations/0031_onboardingoffboardingcampo.py`, `django_app/anagrafica/admin.py`, `django_app/anagrafica/views.py`, `django_app/anagrafica/urls.py`, `django_app/anagrafica/templates/anagrafica/pages/impostazioni.html`, `django_app/anagrafica/tests.py`, `README.md`, `docs/ai/03_BACKEND_MODULES.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno rilevato perche `_AGENT_CONTROL/CRITICAL_FILES.md` non e presente nella workspace. `django_app/anagrafica/urls.py` aggiunge solo route locali del modulo Anagrafica; nessuna modifica ad ACL, middleware, settings, autenticazione, navigazione globale o routing globale.
- Motivo tecnico: il form `+ Nuovo dipendente` e ora la fonte dell'onboarding; serviva una configurazione HR per dichiarare quali campi del form alimentano le liste operative di onboarding/offboarding e, per l'uscita, trasformare le voci configurate in task tracciabili nella pratica.
- Modifica: aggiunto modello `OnboardingOffboardingCampo` con fase, campo, sezione, categoria, obbligatorieta, stato, ordine e note; registrazione Django admin e migration `0031`. In `/anagrafica/impostazioni/` e stato aggiunto il tab "Onboarding / Offboarding" con form di associazione dei campi reali del nuovo dipendente e lista modificabile/eliminabile. Le associazioni Offboarding attive vengono lette all'avvio della pratica e generano task automatici `campo_<campo>` oltre ai task standard.
- Impatto previsto: HR puo configurare da interfaccia quali dati raccolti nel nuovo dipendente devono essere considerati nel workflow operativo. Per l'offboarding le voci attive diventano controlli concreti nella pratica di uscita; le voci Onboarding sono censite e pronte per essere consumate da eventuali step futuri agganciati alla creazione dipendente.
- Rischi residui: la parte Onboarding e configurativa e non avvia ancora task/reparti automatici alla creazione dipendente; per quello servira un secondo aggancio al salvataggio del nuovo dipendente o a moduli IT/DPI/Amministrazione. Workspace gia sporca con modifiche non correlate, lasciate intatte.
- Test/check: `python django_app\manage.py makemigrations anagrafica --check --dry-run --settings=config.settings.dev` OK; `python django_app\manage.py check --settings=config.settings.dev` OK; `python django_app\manage.py test anagrafica.tests.ImpostazioniRedirectTests.test_workflow_settings_maps_new_employee_field anagrafica.tests.AnagraficaDipendentiViewTests.test_offboarding_creates_tasks_from_configured_fields anagrafica.tests.AnagraficaDipendentiViewTests.test_offboarding_licenziamento_creates_pratica_then_closes_employee --settings=config.settings.test --verbosity 2` OK; `python django_app\manage.py bootstrap_acl_v2 --dry-run --apps anagrafica --settings=config.settings.dev` OK con 0 proposte; `python django_app\manage.py acl_coverage_report --settings=config.settings.dev` conferma Anagrafica `bound=157`, `missing=0`; `git diff --check` OK.
- Note: nessun backup creato.

## 2026-05-26 - Codex

- Area: `deployment`, release manager / configurazione ambiente PROD.
- Richiesta: verificare in `Y:\Portale Novicrom\` perche dopo l'import di una nuova release il file `.env` risulta ripristinato.
- Verifica su `Y:\`: il drive `Y:` punta gia a `\\pclogsys\PortaleNovicrom\prod`; il path `Y:\Portale Novicrom\` non esiste. La root ambiente PROD e `Y:\`, con `Y:\config\.env`, `Y:\current` come junction verso `C:\PortaleNovicrom\prod\releases\20260525_150722` e `Y:\current\django_app\.env`.
- Esito verifica `.env`: al primo controllo `Y:\config\.env` e `Y:\current\django_app\.env` erano identici; dopo l'aggiornamento runtime delle 09:51, `Y:\current\django_app\.env` risulta piu grande e contiene molte chiavi assenti da `Y:\config\.env` (nomi chiave verificati senza stampare valori). Questo conferma la causa: una nuova release copierebbe il `config\.env` vecchio e perderebbe le modifiche presenti solo nel `.env` attivo.
- File modificati: `deployment/scripts/deploy-release.ps1`, `deployment/setup_wizard.py`, `Y:\current\deployment\scripts\deploy-release.ps1`, `Y:\current\deployment\setup_wizard.py`, `README.md`, `CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: `_AGENT_CONTROL/CRITICAL_FILES.md` non e presente nella workspace. Modificati file di deployment (`deploy-release.ps1`, `setup_wizard.py`) che impattano il flusso di promozione release, senza toccare `.env`, segreti, settings Django, ACL, middleware, autenticazione o routing applicativo.
- Motivo tecnico: il deploy usava `config\.env` come sorgente persistente ma non segnalava se il `.env` attivo conteneva modifiche manuali non riportate li; questo rendeva possibile sovrascrivere silenziosamente configurazioni runtime alla release successiva.
- Modifica: aggiunta guardia anti-drift in `deploy-release.ps1` e in `setup_wizard.py`/`Promuovi Release`, sia nel sorgente locale sia nella release attiva su `Y:\current`: prima della copia nella nuova release confrontano `ENV/config/.env` con `ENV/current/django_app/.env`; se i valori delle chiavi divergono, il deploy si ferma e mostra solo i nomi delle chiavi da allineare. La CLI espone `-AllowEnvDrift` come override esplicito per emergenze operative. Corretto anche il marker `.release_info` dello script PowerShell per essere parse-safe.
- Impatto previsto: una modifica fatta per errore nel `.env` della release attiva non viene piu persa senza avviso; l'operatore deve riportarla nel `config\.env` persistente prima di importare/promuovere una nuova release.
- Rischi residui: `Y:\config\.env` resta ancora non allineato al `.env` attivo; non e stato modificato per policy sui segreti. Finche non viene aggiornato manualmente, la nuova guardia blocchera correttamente il prossimo deploy/promote. Eventuali deploy lanciati da copie vecchie degli script esterne a `Y:\current` mantengono il comportamento precedente.
- Test/check: parser PowerShell OK su `deployment/scripts/deploy-release.ps1` e `Y:\current\deployment\scripts\deploy-release.ps1`; `python -m py_compile deployment/setup_wizard.py` OK; `python -m py_compile Y:\current\deployment\setup_wizard.py` OK; `git diff --check` OK sui file sorgente/documentazione/sessione modificati; confronto chiavi `.env` su `Y:\` eseguito senza stampare valori.
- Note: nessun backup creato; nessun valore segreto del `.env` e stato stampato o modificato.

## 2026-05-26 - Codex

- Area: `django_app/anagrafica`, workflow offboarding scheda dipendente.
- Richiesta: provare il workflow proposto per l'offboarding, mantenendo l'onboarding come "Nuovo dipendente" e trasformando l'uscita in una pratica operativa con restituzioni/task prima della cessazione effettiva.
- File modificati: `django_app/anagrafica/models.py`, `django_app/anagrafica/migrations/0030_offboarding_pratiche.py`, `django_app/anagrafica/admin.py`, `django_app/anagrafica/views.py`, `django_app/anagrafica/urls.py`, `django_app/anagrafica/templates/anagrafica/pages/dipendente_detail.html`, `django_app/anagrafica/tests.py`, `README.md`, `docs/ai/03_BACKEND_MODULES.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno rilevato perche `_AGENT_CONTROL/CRITICAL_FILES.md` non e presente nella workspace. `django_app/anagrafica/urls.py` impatta solo routing locale Anagrafica. Nessuna modifica ad ACL, middleware, settings, autenticazione, navigazione globale o routing globale.
- Motivo tecnico: la cessazione immediata non permetteva a HR/IT/responsabili di tracciare cosa recuperare o completare prima dell'ultimo giorno; serve separare apertura pratica e chiusura effettiva del rapporto.
- Modifica: aggiunti modelli `OffboardingPratica` e `OffboardingTask` con admin e migration `0030`; il tasto offboarding della scheda crea una pratica con motivo, data cessazione prevista, ultimo giorno operativo, note e task base/restituzioni. Il dipendente resta in forza finche la pratica e aperta. La card in scheda permette di completare o marcare come eccezione i task; la chiusura e bloccata con task pendenti o data futura e solo alla chiusura imposta `data_cessazione`, disattiva il legacy, scollega l'account e sposta il dipendente negli ex.
- Impatto previsto: HR puo avviare l'uscita senza togliere subito il dipendente dall'organico; l'offboarding diventa un piccolo workflow tracciato e auditato, mentre "Rimetti in forza" resta l'azione inversa dopo cessazione.
- Rischi residui: i task sono interni ad Anagrafica e non creano ancora automaticamente ticket/attivita nei moduli IT, DPI, Assets o Amministrazione; eventuali assegnazioni per reparto richiedono una fase successiva.
- Test/check: `python django_app\manage.py makemigrations anagrafica --check --dry-run --settings=config.settings.dev` OK; `python django_app\manage.py test anagrafica.tests.AnagraficaDipendentiViewTests.test_offboarding_licenziamento_creates_pratica_then_closes_employee anagrafica.tests.AnagraficaDipendentiViewTests.test_rimetti_in_forza_relinks_saved_pre_offboarding_account anagrafica.tests.AnagraficaDipendentiViewTests.test_rimetti_in_forza_clears_cessazione_and_restores_active_status --settings=config.settings.test --verbosity 2` OK; `python django_app\manage.py check --settings=config.settings.dev` OK; `python django_app\manage.py bootstrap_acl_v2 --dry-run --apps anagrafica --settings=config.settings.dev` OK con 0 proposte; `python django_app\manage.py acl_coverage_report --settings=config.settings.dev` conferma Anagrafica `bound=154`, `missing=0`; `git diff --check` OK.
- Note: nessun backup creato; workspace gia sporca con molte modifiche Anagrafica/Formazione e altri moduli non correlate, lasciate intatte.

## 2026-05-26 - Codex

- Area: `django_app/anagrafica`, flussi onboarding/offboarding in Anagrafica HR.
- Richiesta: chiarire che l'onboarding operativo e la creazione del dipendente, eliminare la sezione separata onboarding/offboarding e rivedere l'offboarding come flusso di restituzioni da chiedere al dipendente.
- File modificati: `django_app/anagrafica/views.py`, `django_app/anagrafica/urls.py`, `django_app/anagrafica/templatetags/anagrafica_extras.py`, `django_app/anagrafica/templates/anagrafica/pages/index.html`, `django_app/anagrafica/templates/anagrafica/pages/dipendente_detail.html`, `django_app/anagrafica/templates/anagrafica/components/subnav.html`, `django_app/anagrafica/templates/anagrafica/pages/onboarding_offboarding.html` (rimosso), `django_app/anagrafica/templates/anagrafica/pages/onboarding_offboarding_dipendente.html` (rimosso), `django_app/anagrafica/migrations/0028_subnav_onboarding_offboarding.py`, `django_app/anagrafica/tests.py`, `README.md`, `docs/ai/03_BACKEND_MODULES.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno rilevato perche `_AGENT_CONTROL/CRITICAL_FILES.md` non e presente nella workspace. `django_app/anagrafica/urls.py`, `subnav.html` e `anagrafica_extras.py` impattano solo routing/navigazione locale Anagrafica. Nessuna modifica ad ACL, middleware, settings, autenticazione o routing globale.
- Motivo tecnico: la checklist separata duplicava un processo che ora ha come fonte operativa il form "Nuovo dipendente"; per l'offboarding serve invece tracciare i beni/passaggi da recuperare dal dipendente.
- Modifica: rimosse route/API/template Anagrafica per `/anagrafica/onboarding-offboarding/`; dashboard e scheda dipendente non mostrano piu "Onboarding / Offboarding" e mantengono "+ Nuovo dipendente" come ingresso onboarding. La migration `0028` ora elimina eventuali vecchi link subnav e il loader subnav ignora link named non risolvibili. Il form "Avvia offboarding licenziamento" aggiunge il promemoria restituzioni (badge/chiavi, device IT, DPI/divise/attrezzature, mezzi/carte, documenti/archivi, accessi/account) e salva codici/note nell'audit metadata-only.
- Impatto previsto: HR non vede piu una sezione onboarding/offboarding separata in Anagrafica; la creazione del dipendente resta il flusso onboarding da estendere in futuro; l'offboarding conserva una traccia audit delle restituzioni da verificare senza bloccare la cessazione.
- Rischi residui: il promemoria restituzioni e audit-only e non crea ancora workflow assegnati ai reparti IT/DPI/Assets; eventuali integrazioni automatiche con quei moduli richiedono una fase dedicata.
- Test/check: `python django_app\manage.py check --settings=config.settings.dev` OK; test mirati `test_offboarding_licenziamento_marks_employee_as_no_longer_in_force`, `test_rimetti_in_forza_relinks_saved_pre_offboarding_account`, `test_rimetti_in_forza_clears_cessazione_and_restores_active_status` OK; `python django_app\manage.py makemigrations anagrafica --check --dry-run --settings=config.settings.dev` OK; `python django_app\manage.py bootstrap_acl_v2 --dry-run --apps anagrafica --settings=config.settings.dev` OK con 0 proposte; `acl_coverage_report` conferma Anagrafica `bound=152`, `missing=0`; `git diff --check` OK.
- Note: nessun backup creato; workspace gia sporca con molte modifiche Anagrafica/Formazione e altri moduli non correlate, lasciate intatte.

## 2026-05-25 - Codex

- Area: `django_app/anagrafica`, rimessa in forza scheda dipendente.
- Richiesta: correggere "Rimetti in forza" per ricollegare automaticamente un account portale gia scollegato dall'offboarding quando possibile.
- File modificati: `django_app/anagrafica/models.py`, `django_app/anagrafica/views.py`, `django_app/anagrafica/migrations/0029_aziendale_account_pre_offboarding.py`, `django_app/anagrafica/tests.py`, `README.md`, `docs/ai/03_BACKEND_MODULES.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno rilevato perche `_AGENT_CONTROL/CRITICAL_FILES.md` non e presente nella workspace. Nessuna modifica ad ACL, middleware, settings, autenticazione, navigazione globale o routing globale.
- Motivo tecnico: dopo l'offboarding il campo legacy `anagrafica_dipendenti.utente_id` viene svuotato; senza una traccia separata o una ricerca controllata la rimessa in forza non poteva ricollegare l'account portale.
- Modifica: aggiunto `DipendenteAnagraficaAziendale.utente_id_pre_offboarding` e migration `0029`; l'offboarding salva l'ID account prima di scollegarlo. La rimessa in forza prova a ricollegare l'account da quell'ID e, per offboarding gia eseguiti senza storico, usa fallback univoci su `utente_id` corrente, email, alias/UPN e nome/cognome; se non trova un match unico riattiva comunque il dipendente e mostra warning.
- Impatto previsto: un dipendente rimesso in forza torna nella lista "in forza" con `attivo=1`, `data_cessazione=NULL` e account portale ricollegato automaticamente quando identificabile.
- Rischi residui: per offboarding storici senza `utente_id_pre_offboarding`, il ricollegamento non avviene se email/alias/nome non identificano un solo account; in quel caso resta necessario il ricollegamento manuale. La verifica visuale su pagina reale richiede sessione autenticata.
- Test/check: `python django_app\manage.py check --settings=config.settings.dev` OK; `python django_app\manage.py test anagrafica.tests.AnagraficaDipendentiViewTests.test_offboarding_licenziamento_marks_employee_as_no_longer_in_force anagrafica.tests.AnagraficaDipendentiViewTests.test_rimetti_in_forza_relinks_saved_pre_offboarding_account anagrafica.tests.AnagraficaDipendentiViewTests.test_rimetti_in_forza_clears_cessazione_and_restores_active_status --settings=config.settings.test --verbosity 2` OK; `python django_app\manage.py makemigrations anagrafica --check --dry-run --settings=config.settings.dev` OK; `git diff --check` OK.
- Note: nessun backup creato; workspace gia sporca con molte modifiche Anagrafica/Formazione e altri moduli non correlate, lasciate intatte.

## 2026-05-25 - Codex

- Area: `django_app/anagrafica`, onboarding/offboarding HR e scheda dipendente.
- Richiesta: aggiungere il tasto "Rimetti in forza" e spostare/replicare la sezione onboarding-offboarding dentro Anagrafica HR.
- File modificati: `django_app/anagrafica/views.py`, `django_app/anagrafica/urls.py`, `django_app/anagrafica/templates/anagrafica/pages/dipendente_detail.html`, `django_app/anagrafica/templates/anagrafica/pages/index.html`, `django_app/anagrafica/templates/anagrafica/pages/onboarding_offboarding.html`, `django_app/anagrafica/templates/anagrafica/pages/onboarding_offboarding_dipendente.html`, `django_app/anagrafica/templates/anagrafica/components/subnav.html`, `django_app/anagrafica/migrations/0028_subnav_onboarding_offboarding.py`, `django_app/anagrafica/tests.py`, `README.md`, `docs/ai/03_BACKEND_MODULES.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno rilevato perche `_AGENT_CONTROL/CRITICAL_FILES.md` non e presente nella workspace. `django_app/anagrafica/urls.py` e routing locale del modulo Anagrafica; `subnav.html` e `0028_subnav_onboarding_offboarding.py` impattano navigazione locale Anagrafica. Nessuna modifica ad ACL, middleware, settings, autenticazione o routing globale.
- Motivo tecnico: la checklist onboarding/offboarding era operativa in Admin Portale; la richiesta vuole la stessa gestione direttamente nel modulo Anagrafica HR e un'azione inversa dell'offboarding licenziamento che riporti il dipendente tra quelli in forza.
- Modifica: aggiunte view/template/API Anagrafica per configurare voci check-in/check-out, attivarle/disattivarle, eliminarle se senza risposte, vedere lo stato dei dipendenti e registrare esecuzioni per singolo dipendente. Aggiunta route `/anagrafica/onboarding-offboarding/` con dettaglio `/anagrafica/onboarding-offboarding/dipendenti/<legacy_id>/` e subnav locale. La scheda dipendente ora mostra link "Onboarding / Offboarding" e, se cessato, il tasto "Rimetti in forza"; il POST rimuove `data_cessazione`, imposta `anagrafica_dipendenti.attivo=1` e, dopo la correzione successiva, ricollega l'account portale quando identificabile.
- Impatto previsto: HR/admin possono gestire l'intero flusso checklist dal modulo Anagrafica, senza dipendere dalle pagine Admin Portale. Un ex dipendente rimesso in forza torna nella lista dipendenti e sparisce dalla vista ex dipendenti.
- Rischi residui: le vecchie route Admin Portale non sono state rimosse per compatibilita, ma la nuova operativita richiesta e nel namespace Anagrafica. Il ricollegamento automatico degli account scollegati e stato corretto nella voce successiva: resta manuale solo se nessun account risulta univoco.
- Test/check: `python django_app\manage.py check --settings=config.settings.dev` OK; test mirati `test_offboarding_licenziamento_marks_employee_as_no_longer_in_force`, `test_rimetti_in_forza_clears_cessazione_and_restores_active_status`, `test_onboarding_offboarding_section_manages_checklist_inside_anagrafica` OK; template load `dipendente_detail.html`, `onboarding_offboarding.html`, `onboarding_offboarding_dipendente.html` OK; `bootstrap_acl_v2 --dry-run --apps anagrafica` OK con 0 proposte; `acl_coverage_report` conferma Anagrafica `bound=159`, `missing=0`; `git diff --check` sui file toccati OK.
- Note: nessun backup creato; workspace gia sporca con molte modifiche Anagrafica/Formazione e altri moduli non correlate, lasciate intatte.

## 2026-05-25 - Codex

- Area: `django_app/anagrafica`, scheda dipendente HR.
- Richiesta: aggiungere nella scheda dipendente un tasto "avvia offboarding licenziamento" affinche il dipendente non risulti piu in forza all'azienda.
- File modificati: `django_app/anagrafica/views.py`, `django_app/anagrafica/urls.py`, `django_app/anagrafica/templates/anagrafica/pages/dipendente_detail.html`, `django_app/anagrafica/tests.py`, `README.md`, `docs/ai/03_BACKEND_MODULES.md`, `CHANGELOG.md`, `django_app/CHANGELOG.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno rilevato perche `_AGENT_CONTROL/CRITICAL_FILES.md` non e presente nella workspace. `django_app/anagrafica/urls.py` e routing locale del modulo Anagrafica, non routing globale. Nessuna modifica ad ACL, middleware, settings, autenticazione o navigazione globale.
- Motivo tecnico: la lista dei dipendenti in forza esclude i nominativi con `DipendenteAnagraficaAziendale.data_cessazione` valorizzata; il toggle esistente "Disattiva" agiva solo sul campo legacy `attivo` e non bastava a spostare il dipendente tra gli ex.
- Modifica: aggiunta view POST `dipendente_offboarding_licenziamento` e relativa URL locale `/anagrafica/dipendenti/<legacy_id>/offboarding/licenziamento`; la hero della scheda mostra agli admin un form compatto con data cessazione e tasto "Avvia offboarding licenziamento" se il rapporto non e gia cessato. Il POST valida una data non futura, valorizza `data_cessazione`, imposta `anagrafica_dipendenti.attivo=0`, scollega `utente_id`, registra audit metadata-only e conferma con messaggio flash.
- Impatto previsto: dopo l'azione il dipendente sparisce dalla lista `/anagrafica/dipendenti/`, compare in `/anagrafica/ex-dipendenti/`, resta consultabile per storico/audit e non ha piu account portale collegato.
- Rischi residui: il flusso non compila automaticamente la checklist amministrativa di offboarding in Admin Portale; l'azione e immediata e non reversibile tramite lo stesso tasto, mentre la riattivazione legacy resta separata dal ripristino della data cessazione. La verifica visuale su pagina reale richiede sessione autenticata.
- Test/check: `python django_app\manage.py check --settings=config.settings.dev` OK; `python django_app\manage.py test anagrafica.tests.AnagraficaDipendentiViewTests.test_offboarding_licenziamento_marks_employee_as_no_longer_in_force --settings=config.settings.test --verbosity 2` OK; template load `anagrafica/pages/dipendente_detail.html` OK; `bootstrap_acl_v2 --dry-run --apps anagrafica` OK con 0 proposte; `acl_coverage_report` conferma Anagrafica `bound=151`, `missing=0`; `git diff --check` sui file toccati OK.
- Note: nessun backup creato; workspace gia sporca con molte modifiche Anagrafica/Formazione non correlate, lasciate intatte.

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
