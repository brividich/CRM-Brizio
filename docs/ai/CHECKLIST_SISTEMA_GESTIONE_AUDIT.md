# Checklist — Sistema di gestione: SoA ISO 27001 e audit interni

> Documento di avanzamento **autosufficiente**: chi lo riprende (persona o LLM) deve poter continuare il lavoro
> senza altro contesto. Aggiornare le caselle `[ ]` → `[x]` e la sezione «Stato» a ogni blocco completato,
> nello stesso commit del codice.

- **App**: `django_app/sistema_gestione/` — URL `/sistema-gestione/` — namespace `sistema_gestione`
- **Voce di menu**: «Sistema di gestione», categoria **Qualità** (`riorganizza_topbar`, ordine 65)
- **Modulo collegato**: `django_app/report_conformita/` (report di sola lettura, riesame della direzione)
- **Ultimo aggiornamento**: 2026-09-25

---

## 0. Stato in sintesi

| Fase | Contenuto | Stato | Commit / note |
|---|---|---|---|
| 1 | Dichiarazione di applicabilità (SoA) ISO 27001 = MOD.165 Control Matrix + threat intelligence | **FATTA** — mergiata su `main` e `release/prod`, **non deployata** | feature `e525875a`, main `a784d330`, release/prod `e59c3223` |
| 2 | Audit interni EN 9100: MOD.034 programma, MOD.035A piano, MOD.035B rapporto, auditor, collegamento al Registro OFI | **FATTA** — implementata e verificata, **non deployata** | branch `feature/sistema-gestione-audit-9100`; hash finali nel riepilogo di chiusura |
| 3 | Audit interni ISMS: MOD.171 piano, MOD.168 rapporto (punteggio 1-4 dei 93 controlli precompilato dalla SoA) | **DA FARE** | — |
| 4 | Estensioni: checklist ISO 45001 e UNI/PdR 125, flag PdR 125 nel Registro OFI, (eventuale) analisi del rischio completa del MOD.165 | **RIMANDATE** dall'utente | — |

---

## 1. Regole di lavoro (obbligatorie)

1. **Mai lavorare nel checkout condiviso** `C:\Dev\Portale Novicrom` (altre sessioni lo usano). Per ogni blocco:
   `git worktree add C:\Dev\pn-<tema> -B <branch> origin/main` → lavoro, test, commit, push dal worktree →
   `git worktree remove`. Mai `git checkout` nel condiviso; mai `git add -A`.
2. **Chiusura del giro** (senza chiedere): merge `--no-ff` del branch su `main` (branch temporaneo da `origin/main`,
   `git push origin HEAD:main`), poi merge di `origin/main` su `release/prod` (`git push origin HEAD:release/prod`).
   Dopo ogni merge verificare **due genitori** (`git log --format="%h parents=%p %s" -1`), assenza di `<<<<<<<`,
   `git diff --stat origin/main origin/release/prod` vuoto, `makemigrations --check --dry-run` pulito. Poi nel
   condiviso `git merge --ff-only origin/release/prod` e `manage.py migrate --settings=config.settings.dev`.
3. **CHANGELOG.md** (sezione `[Unreleased]`) e **README.md** (tabella moduli + `<details>` 22c) aggiornati a ogni
   modifica di codice, con l'elenco dei file toccati.
4. **Test**: solo quelli del modulo, mai la suite completa:
   `python manage.py test sistema_gestione report_conformita --settings=config.settings.test`
   (nei worktree manca il `.env`: impostare `DEFAULT_FROM_EMAIL=noreply@example.com`; **non copiare mai il `.env`**).
   Più `check`, `makemigrations --check --dry-run`, e i test topbar/tassonomia se si toccano quei file:
   `core.tests.TopbarGroupingTests core.tests.RiorganizzaTopbarCommandTests admin_portale.tests.AclPermissionTaxonomyTests`.
5. **Verifica a video prima di dire «fatto»**, tema chiaro **e** scuro. Nel worktree le settings `dev` senza `.env`
   usano SQLite locale (`DJANGO_DEBUG=1`, `migrate`, `runserver 127.0.0.1:80XX --noreload`, `LEGACY_AUTH_ENABLED=0`,
   sessione forgiata con `SessionStore`). Il tema scuro si prova creando `UserUiPreference(theme_mode="dark")` e una
   **sessione nuova** (le preferenze sono in cache di sessione): aggiungere la classe `theme-dark` via JS dà falsi
   difetti. Se l'estensione Chrome non è collegata, Playwright è installato nel venv.
6. **Riservatezza**: i contenuti dei documenti SGI (MOD.165, rapporti di audit, checklist compilate) **non vanno mai
   nel repository** né in fixture/test: si leggono a runtime con comandi di import e restano nel database. Nei test
   solo dati sintetici. Nessun nome di persona reale nei documenti o nel codice.
7. **Ambito normativo europeo/italiano**: EN 9100 (UNI EN 9100:2018, mai «AS9100»), UNI EN ISO 9001/45001/19011,
   UNI CEI EN ISO/IEC 27001:2022, UNI/PdR 125:2022, D.Lgs. 81/08, GDPR, NIS2 (D.Lgs. 138/2024). Nessun riferimento a
   prodotti o fonti statunitensi.
8. **ACL v2**: ogni nuova route va in `_ROUTE_BINDINGS` di `sistema_gestione/acl_bootstrap.py` (altrimenti con
   `ACL_STRICT_CANONICAL` è 403 per i non superuser; i test con superuser non se ne accorgono) **e** va ricontrollata
   nella view con `_has_perm(request, CODICE)`, fail-closed. Grant di default solo *create-only*
   (`get_or_create`), mai `update_or_create` su `NavigationItem` (usare `ensure_navigation_item`).
9. **Template Django**: commenti `{# #}` solo su una riga; per blocchi usare `{% comment %}`. Nei test cercare `{#`
   nell'HTML reso. Stili solo con i token di `theme.css` (niente colori fissi che rompono il tema scuro).
10. **DateInput** sempre con `format="%Y-%m-%d"` (altrimenti il valore iniziale non compare nel campo `type=date`).

---

## 2. Decisioni prese con l'utente (non ridiscutere)

| Tema | Decisione |
|---|---|
| Struttura | Una sola app «Sistema di gestione» con sezioni SoA e Audit, permessi separati |
| Ordine | SoA (fatta), poi audit EN 9100, poi audit ISMS |
| Rilievi di audit (OFI/NC) | Vanno nel **Registro OFI MOD.174** (`gestione_specifiche.RegistroOFI`), collegati all'audit |
| Approvazione | Semplice: chi prepara propone, **la Direzione approva** (programma audit, piano, SoA) |
| Firme | **Entrambe**: approvazione registrata nel portale (nome, data/ora nel PDF) **e** copia firmata a mano caricabile (PDF, storage privato cifrato) |
| Auditor | Interni con qualifica + **auditor esterni** (consulenti, con approvazione del CEO come da MT CN 12 §5.3) |
| Modelli dei documenti | Replicare i moduli aziendali; **il PDF di export deve essere identico al modulo** (MOD.035A in particolare) |
| Checklist | Per ora **solo EN 9100** (Folder B del MOD.035B) **e ISMS** (MOD.171/168); ISO 45001 e PdR 125 dopo |
| Scala controlli ISO 27001 | **0-4, 4 = pienamente applicato**, 0 = non applicato/escluso (come MOD.165) |
| MOD.165 sorgente | Esiste **solo il PDF** (l'Excel originale non è disponibile) → import dal PDF |
| NIS2 | Azienda registrata presso l'ACN ma **non soggetta** alle misure di base → nessuna mappatura ACN per ora (la struttura deve poterla aggiungere dopo) |

---

## 3. Documenti sorgente (cartella di rete SGI)

Base: `\\novisrv\Sistema Gestione Integrato\`

| Documento | Percorso relativo | Uso |
|---|---|---|
| MT CN 12 Rev.1 — Audit interni (procedura) | `9100_Qualità\2_MT\MT CN 12 Rev.1_Audit Interni.pdf` | Regole: programmazione annuale, nomina auditor, piano, esecuzione, rapporto, requisiti auditor (§6), KPI (§7) |
| MOD.034 Rev.18 — Programmazione verifiche ispettive | `9100_Qualità\_Modelli\MOD.034 - Programmazione Verifiche Ispettive Rev.18.pdf` | Programma annuale (fase 2) |
| MOD.035A Rev.0 — Piano di audit | `9100_Qualità\_Modelli\MOD.035A Piano di Audit Rev0.pdf` | Piano del singolo audit (fase 2); **PDF di export identico** |
| MOD.035B Rev.0 — Rapporto di audit interno di sistema (RAIS) | `9100_Qualità\_Modelli\MOD.035B RAIS Rapporto di Audit Interno di Sistema Rev0.pdf` | Rapporto + checklist «Folder B — EN 9100» (fase 2) |
| MOD.036 Rev.3 — CAR Corrective Action Request | `9100_Qualità\_Modelli\MOD.036 - CAR - Corrective Action Request Rev.3.pdf` | Richiesta di azione correttiva (riferimento; «CAR autorizzate» nel MOD.035B) |
| MOD.062 — Verbale di riesame (VRS) | `9100_Qualità\_Modelli\MOD.062 - VRS - Verbale di Riesame Rev.13.pdf` | Solo riferimento testuale nel programma/piano |
| MT CN 276 Rev.2 — Audit interno ISMS | `27001_Sistemi Informatici\MT CN 276_Audit Interno - ISMS Rev.2.pdf` | Procedura audit ISMS (fase 3) |
| MOD.171 Rev.1 — M-AUD-01 Audit Plan | `27001_Sistemi Informatici\MOD.171 - M-AUD-01 Audit Plan Rev.1.pdf` | Piano audit ISMS (fase 3) |
| MOD.168 Rev.2 — M-AUD-02 Rapporto di audit | `27001_Sistemi Informatici\MOD.168 - M-AUD-02 Rapporto di Audit Rev.2.pdf` | Rapporto audit ISMS (fase 3) |
| MOD.165 Rev.3 — RAR Risk Assessment And Register | `27001_Sistemi Informatici\MOD.165 - RAR RiskAssessmentAndRegister Rev.3.pdf` | SoA (fase 1, importata dal PDF) |
| Manuale ISMS IDOR CN 02 Rev.2 | `27001_Sistemi Informatici\IDOR CN 02 ISMS_Manuale ISMS Rev.2.pdf` | §6.1.3: SoA e piano di trattamento stanno nel MOD.165, riesame almeno annuale |

Il MOD.165 (20 pagine) contiene: Control Matrix (= SoA), catalogo informazioni con livelli C/I/A, tipi di asset,
catalogo minacce con probabilità, matrice minacce × asset, rischio inerente, minacce × controlli, rischio residuo con
soglia di accettabilità 30, *Threat Monitoring* (azioni, responsabile, scadenza, livello futuro; rimanda a «OFI n. …»),
registro annuale threat intelligence. In fase 1 sono stati portati nel portale solo Control Matrix, piano di
trattamento e threat intelligence.

---

## 4. Incongruenze trovate nei documenti SGI (da segnalare all'RDD, NON correggere nel codice)

- [ ] MT CN 12 Rev.1 cita come rapporto di audit il **MOD.077** (oggi MOD.035B), cita ISO 14001 e non cita ISO 27001 né UNI/PdR 125 (presenti nei moduli).
- [ ] Preavviso agli auditati: MT CN 12 «almeno una settimana», MOD.035A «minimo 5 giorni lavorativi». Nel portale: soglia configurabile, default **5 giorni lavorativi**.
- [ ] Convalida del rapporto: MT CN 12 «Responsabile audit + Responsabile dell'ente verificato», MOD.035B «Auditor + RDD». Nel portale: prevedere entrambe le approvazioni (vedi fase 2).
- [ ] Approvazione del piano: MT CN 12 «approvato dal CEO», MOD.035A «Lead Auditor + RDD/CEO».
- [ ] MOD.035B richiama «MOD.034 Rev.19»; in cartella c'è la Rev.18.
- [ ] Punteggi dei controlli nel MOD.168 e nella tabella del MT CN 276 molto diversi dal MOD.165 (es. 5.1 = 1 contro 4). Confermato dall'utente: la scala giusta è quella del MOD.165 (4 = applicato); i valori nei moduli di audit sono d'esempio o da aggiornare.
- [ ] MOD.165: controllo **6.5** con rischio residuo non accettabile e nessuna azione pianificata; controllo **8.11** livello 1 nella Control Matrix ma 3 nel Threat Monitoring; righe con errori `#N/D` / `#RIF!` nel foglio Inherent Risk.
- [ ] Registro OFI (portale) senza la spunta **UNI/PdR 125** (serve per gli audit PdR 125, fase 4).

---

## 5. Fase 1 — Dichiarazione di applicabilità (FATTA)

### 5.1 File

- `sistema_gestione/catalogo_27002.py` — 93 codici ufficiali + titoli brevi in italiano **scritti per il portale** (non il testo ISO); temi ORG 37 / PER 8 / FIS 14 / TEC 34.
- `sistema_gestione/models.py` — `ControlloIso27002`, `SoaRevisione` (numero, stato BOZZA/PROPOSTA/APPROVATA/SUPERATA, preparata/proposta/approvata, copia firmata), `SoaVoce` (livello 0-4, vulnerabilità 0-4, riferimenti, giustificazione, 5 flag obbligo, azione/responsabile/scadenza/livello atteso, FK `RegistroOFI`), `ThreatIntelligence`.
- `sistema_gestione/storage.py` — `PrivateSistemaGestioneStorage` (cifrato, `TASKS_PRIVATE_ROOT`, nessun URL pubblico).
- `sistema_gestione/services/soa.py` — `assicura_catalogo`, `nuova_revisione` (copia la più recente), `proponi`, `riporta_in_bozza`, `approva` (la precedente → SUPERATA), `statistiche`, `differenze`.
- `sistema_gestione/services/mod165_import.py` — parser PyMuPDF della Control Matrix (pagine ruotate 90°, parole riportate nel verso di lettura con `page.rotation_matrix`, colonne ricavate dalle intestazioni `APPLIED?`/`VULNERABILITY`/`References`/`Justification`/`OBJECTIVE`, riga = banda fino all'ancora «X.Y» in fondo alla cella, «(Required by: …)» → flag).
- `sistema_gestione/management/commands/importa_soa_mod165.py` — dry-run di default, `--numero N`, `--apply`.
- `sistema_gestione/evidenze.py` — mappa controllo → report di `report_conformita` (28 controlli).
- `sistema_gestione/forms.py`, `exports.py` (PDF via `report_conformita.exports.render_pdf`, XLSX via `core.excel_export.build_xlsx_bytes`), `views.py`, `urls.py`, `acl_bootstrap.py`, `apps.py`.
- Template `sistema_gestione/templates/sistema_gestione/pages/{index,soa_vuota,soa_revisione,soa_voce,threat_intelligence,threat_intelligence_form}.html`, `components/_styles.html` (include gli stili `rc-` di report_conformita + classi `sg-`).
- Migration `0001_initial`, `0002_seed_catalogo_27002`.
- `report_conformita/reports/it.py` — report `dichiarazione-applicabilita` (registrato solo se l'app è installata).
- `report_conformita/exports.py` — larghezza minima delle colonne PDF (intestazioni non più spezzate).
- Wiring: `config/settings/base.py` (INSTALLED_APPS), `config/urls.py`, `core/permission_taxonomy.py` (area sicurezza), `core/management/commands/riorganizza_topbar.py` (voce in Qualità).
- `sistema_gestione/tests.py` — 16 test (catalogo, ciclo revisioni, statistiche/differenze, form, parser su PDF sintetico, comando import, ACL, view, permesso di approvazione, copia firmata, threat intelligence, report).

### 5.2 Permessi (ACL v2)

| Codice | Uso | Default |
|---|---|---|
| `sistema_gestione.modulo.view` | hub | admin, qualita |
| `sistema_gestione.soa.view` | SoA, revisioni, PDF/XLSX, copia firmata, threat intelligence (lettura) | admin, qualita |
| `sistema_gestione.soa.edit` | bozza, voci, proposta, riporta in bozza, nuova revisione, copia firmata, threat intelligence (inserimento) | admin |
| `sistema_gestione.soa.approva` | approvazione (Direzione) | admin |

### 5.3 Checklist fase 1

- [x] Catalogo 93 controlli + seed
- [x] Modelli, storage privato, migration
- [x] Ciclo revisioni con blocco modifica fuori bozza
- [x] Form voce (esclusione ⇒ giustificazione obbligatoria; azione ⇒ scadenza obbligatoria)
- [x] Evidenza viva
- [x] PDF / XLSX
- [x] Copia firmata (upload PDF validato con `validate_extension_and_mime`, download protetto)
- [x] Threat intelligence
- [x] Parser MOD.165 + comando import (provato sul PDF reale in DB locale: 93/93)
- [x] Report SoA in report_conformita
- [x] ACL + menu + test + CHANGELOG + README
- [x] Verifica a video chiaro/scuro (Playwright)
- [x] Merge main → release/prod, `migrate` in dev
- [ ] **Deploy** (vedi §8)

---

## 6. Fase 2 — Audit interni EN 9100 (FATTA — NON DEPLOYATA)

Implementazione completata il 2026-09-25 sul branch `feature/sistema-gestione-audit-9100`; migrazioni, importatore, PDF e verifiche UI inclusi. Il deploy resta separato (§8).

Permessi nuovi aggiunti in `acl_bootstrap.py`, con binding di **ogni** route:

| Codice | Uso |
|---|---|
| `sistema_gestione.audit.view` | consultazione programma, piani, rapporti, PDF |
| `sistema_gestione.audit.edit` | MSM/RDD: programma, piani, rapporti, auditor |
| `sistema_gestione.audit.esegui` | auditor: compila checklist ed esiti del proprio audit |
| `sistema_gestione.audit.approva` | Direzione (CEO/RDD): approva programma e piano, valuta il rapporto |

### 6.1 Modelli

- [x] **`Auditor`** — `user` (FK nullable) **oppure** `nome_esterno` + `ente_esterno`; `interno` (bool); requisiti MT CN 12 §6 come campi booleani con data di verifica: `req_diploma`, `req_norme`, `req_tecniche_audit`, `req_settore`, `req_esperienza_2_anni`; `audit_svolti_pregressi` (int, da storico cartaceo); per gli esterni `approvato_ceo_da/_il` e `formazione_processi_il` (§5.3); `attivo`. Proprietà `audit_svolti` = pregressi + audit chiusi nel portale; `qualificato` = tutti i requisiti + `audit_svolti >= 4`. Facoltativo: collegamento a `anagrafica.DipendenteQualifica` se esiste una qualifica «Auditor interno».
- [x] **`ProgrammaAudit`** (MOD.034) — `anno`, `revisione` (int), `stato` (BOZZA/PROPOSTA/APPROVATO/SUPERATO), `rif_riesame` (testo: «MOD.062 VRS del …»), `periodi` (testo libero per norma: es. «Audit 27001: gennaio; 9100: maggio + ottobre; 45001: giugno–settembre; PdR 125: settembre»), `esclusioni_27002` (testo, **precompilato dalla SoA in vigore**: controlli con livello 0), approvazione CEO (`approvato_da/_il`) + convalida RDD (`convalidato_da/_il`), `copia_firmata` (come SoA). Una revisione approvata non si modifica; la nuova revisione copia righe e celle (motivo obbligatorio: date non rispettate / nuove criticità, MT CN 12 §5.2).
- [x] **`RigaProgramma`** — `programma` FK, `ordine`, `area` (testo, es. «Supporto (Gestione delle risorse)»), `enti` (testo, es. «SAM - MSM / RSPP - CISO»), punti norma per colonna: `punti_9100`, `punti_45001`, `punti_27001`, `punti_pdr125`, `altre_normative` (es. «MO-ID-009.24, EASA, EMAR/AER P-145, MOE», «Doc 1 DMFGSDP», «MT CN 65»), `note`.
- [x] **`CellaProgramma`** — `riga` FK, `mese` (1-12), `stato` PR (programmata) / RP (riprogrammata) / ST (straordinaria), `audit` FK nullable (l'audit che la realizza). Vincolo unico (riga, mese).
- [x] **`Audit`** (MOD.035A + testata MOD.035B) — `numero` (formato da confermare con l'utente, es. `RAIS-AAAA-NN`), `programma` FK + `righe` M2M (righe coperte), `tipo`: SISTEMA (RAIS) / MANDATORIO_CLIENTE (RAI) / STRAORDINARIO; flag norme `en9100`, `iso45001`, `iso27001`, `pdr125`; `lead_auditor` FK Auditor, `auditor` M2M; `processi`, `punti_norma`, `procedure_criteri`, `esclusioni` (default «Nessuna»); `data_inizio`, `data_fine`, `durata_stimata`, `sede` (default «Costruzioni Novicrom srl – Pontedera (PI)» da configurazione, non fisso nel codice); metodi (4 booleani: intervista, esame documenti, osservazione diretta, verifica evidenze); `comunicazione_il` + `comunicazione_metodo` (EMAIL / CALENDARIO); stato: PIANIFICATO → PIANO_APPROVATO → IN_CORSO → RAPPORTO → CHIUSO (+ ANNULLATO); approvazioni: `piano_approvato_lead_*`, `piano_approvato_direzione_*`, `rapporto_firmato_auditor_*`, `rapporto_convalidato_ente_*` (responsabile ente verificato, MT CN 12), `rapporto_valutato_rdd_*`; `giudizio`, `punti_forza`, `valutazione_rdd`, `car_autorizzate` (testo); `copia_firmata_piano`, `copia_firmata_rapporto`.
- [x] **`AuditPersona`** (sez. 4 MOD.035A / sez. B MOD.035B) — `audit` FK, `nome`, `funzione_ente`, `ruolo` (TEAM / AUDITATO / PROCESSO), `data_intervista`, `intervistato` (bool).
- [x] **`AuditAgenda`** (sez. 5 MOD.035A) — `audit` FK, `quando` (datetime), `processo_area`, `attivita` (punto norma / documento), `auditor` (testo o FK). Alla creazione dell'audit generare «Riunione di apertura» e «Riunione di chiusura» (Lead Auditor).
- [x] **`ChecklistModello`** / **`ChecklistSezione`** / **`ChecklistDomanda`** — modello versionato per norma (fase 2: `EN9100_FOLDER_B`). Sezione = «§4 – Contesto dell'organizzazione» con `criteri` (es. «IDOR CN 01 Rev.10 · MOD.062 VRS»); domanda = `punti` (es. «4.1 4.2») + `testo` (requisito / domande guida). **Il testo delle domande è contenuto aziendale del MOD.035B**: caricarlo con un **comando di import dal PDF** (come `importa_soa_mod165`), non in una migration né nel codice; nei test usare domande sintetiche.
- [x] **`AuditEsito`** — `audit` FK, `domanda` FK, `esito` CONFORME (✓) / OFI / NC / NA, `evidenze` (testo), `ofi` FK `RegistroOFI` nullable. Per sezione: `AuditSezioneCar` (`audit`, `sezione`, `car_aperta` bool) = riga «CAR (MOD.036) aperta – §x: NO/SÌ → vedere MOD.174».

### 6.2 Flussi e regole

- [x] **Programma**: griglia righe × 12 mesi con PR/RP/ST cliccabili (HTMX o form semplice), legenda come MOD.034; da una cella «Pianifica audit» crea l'`Audit` precompilato (norme dalle colonne con punti valorizzati, punti norma, enti).
- [x] **Piano**: form a sezioni identiche al MOD.035A (1 Identificazione, 2 Campo, 3 Logistica e comunicazione, 4 Persone coinvolte, 5 Programma orario, 6 Approvazione). Pulsante «Comunica agli auditati»: email (+ invito calendario se l'integrazione Outlook è disponibile) alle persone con ruolo AUDITATO; registra `comunicazione_il/_metodo`; **avviso bloccante (con deroga motivata)** se mancano meno di 5 giorni lavorativi alla `data_inizio` (festivi italiani: riusare l'helper già presente nel progetto, cercare `holidays` / giorni lavorativi in `gestione_specifiche`).
- [x] **Imparzialità** (EN 9100 §9.2.2, MT CN 12 §5.3): errore se lead auditor o auditor appartengono al reparto/funzione del processo auditato (confronto con il reparto in anagrafica, ponte `utente_id` — mai confrontare direttamente id utente e id anagrafica); deroga solo con motivazione, tracciata in audit log. Avviso se l'auditor non risulta `qualificato`.
- [x] **Esecuzione**: checklist precaricata dal modello della norma; per ogni domanda esito + evidenze; la checklist «può essere ampliata o modificata durante l'audit» (MT CN 12 §5.5) → consentire domande aggiuntive all'audit.
- [x] **OFI/NC → Registro OFI**: all'esito OFI o NC creare (una volta sola) una `RegistroOFI` con `tipo` OFI/NC, `norma_en9100=True` (e le altre secondo il flag dell'audit), `rif_norma` = punti della domanda, `processo` = processi dell'audit, `opportunita` = evidenze, `data_apertura` = data dell'audit, `modulo_origine="sistema_gestione"`, origine generica = l'`AuditEsito`. Numerazione: usare la stessa logica del registro (cercare in `gestione_specifiche/views_ofi.py` / `models.py` come si assegna `numero`). Collegare `AuditEsito.ofi`.
- [x] **Contatori** «OFI emesse / NC di sistema» calcolati dagli esiti (sez. D).
- [x] **Chiusura**: firma auditor → convalida responsabile ente → valutazione RDD con «CAR autorizzate» → CHIUSO. Distribuzione del rapporto (MT CN 12 §5.6): notifica/email al responsabile della funzione auditata e al MSM.
- [x] **Audit mirati su richiesta del cliente** (MT CN 12, es. DMFG - Part 145): tipo MANDATORIO_CLIENTE; righe «Normative» del MOD.034.
- [x] **KPI MT CN 12 §7**: «N. verifiche effettuate / n. verifiche programmate» per anno → nuovo report `audit-interni` in `report_conformita/reports/qualita.py` (celle PR/RP/ST vs audit chiusi, NC/OFI da audit aperte, tempi di chiusura, auditor qualificati) + incluso nel riesame.
- [x] **Evidenza viva SoA**: in `evidenze.py` collegare i controlli **5.35** e **5.36** al report `audit-interni`.

### 6.3 PDF (identici ai moduli)

- [x] `MOD.034` programma (A3/A4 orizzontale: colonne area, enti, punti per norma, normative, 12 mesi con PR/RP/ST colorati, riquadri approvazione CEO / convalida RDD, riferimento verbale di riesame, periodi per norma, esclusioni 27002).
- [x] `MOD.035A` piano: stessa impaginazione del PDF aziendale (testata con logo / titolo / codice-rev-data, sezioni 1-6 a tabella, caselle ☐/☒, nota a piè di pagina «Il presente Piano di Audit costituisce…» presa dal modulo). Nelle caselle firma: «Approvato digitalmente da … il …» se approvato nel portale, altrimenti vuote per la firma a mano.
- [x] `MOD.035B` rapporto: testata A, persone intervistate B, Folder C con righe § / requisito / evidenze / rilievo (☑ sull'esito scelto) e riga «CAR (MOD.036) aperta» per sezione, giudizi D, valutazioni RDD E.
- [x] Usare `core.pdf` (`PdfTheme`, `make_document`, `data_table`, `header_footer_callback`) o `canvas` per le parti a posizione fissa; confrontare a occhio con i PDF aziendali (render in PNG con PyMuPDF).

### 6.4 Test minimi

- [x] Modelli e vincoli (cella unica per riga/mese, stati, revisione programma che copia righe/celle).
- [x] Imparzialità (errore sul proprio reparto, deroga registrata).
- [x] Preavviso 5 giorni lavorativi.
- [x] Esito OFI/NC → una sola `RegistroOFI` con i campi giusti; nessun duplicato se si salva due volte.
- [x] Permessi: esegui senza approva; approva negato senza permesso (patch di `_has_perm`); binding di tutte le route.
- [x] PDF MOD.034/035A/035B generati (`%PDF`), nessun `{#` nelle pagine.
- [x] Report `audit-interni` su DB vuoto e con dati sintetici.

---

## 7. Fase 3 — Audit ISMS (DA FARE)

- [ ] Tipo audit ISMS che usa lo stesso modello `Audit` con impaginazione **MOD.171** (piano: team, siti, attività da remoto S/N, agenda con riunione iniziale, formazione, intervista IT per controlli tecnici, intervista direzione per controlli non tecnici, presentazione risultati, termine) e **MOD.168** (rapporto).
- [ ] MOD.168: attività da remoto (%) / in campo con date e durata; siti e campo di applicazione; team; «Modifiche significative dopo il precedente audit» (4 domande sì/no + specificare); efficacia delle azioni sulle NC minori precedenti (efficaci / non efficaci ⇒ NC maggiore / non presenti); valutazione dei report degli ultimi due audit; analisi dei commenti del precedente audit; tabella requisiti ISO 27001 (4.3, 5.2, 6.1.2, 6.1.3 d, 6.1.3/8.2/8.3, 6.2, 7.2, 7.5, 8.1, 9.1, 9.2, 9.3, 10.1, obblighi di conformità, famiglie di controlli) con evidenze e rilievi (NC / COM / AP); tabella dei 93 controlli con **applicazione 1-4 precompilata dal livello della SoA in vigore** (modificabile dall'auditor, differenze evidenziate) e commento; elenco azioni correttive (NC, azione, responsabile, scadenza).
- [ ] NC/COM/AP → Registro OFI con `norma_iso27001=True`, `rif_norma` = controllo o requisito.
- [ ] Alla chiusura: proposta di aggiornamento della SoA (apre una nuova revisione in bozza con i livelli emersi dall'audit, da approvare).
- [ ] PDF MOD.171 e MOD.168 identici ai moduli.

---

## 8. Deploy (per ogni fase)

1. Pacchetto da `release/prod` (vedi `docs/ai/06_TESTING_AND_QUALITY_GATES.md` e `deployment/scripts/package-release.ps1`).
2. `manage.py migrate` (fase 1: `sistema_gestione 0001-0002`; fase 2: anche `0003_audit_*`).
3. `manage.py riorganizza_topbar` (dry-run) e poi `--apply`.
4. Fase 1: `manage.py importa_soa_mod165 "\\novisrv\Sistema Gestione Integrato\27001_Sistemi Informatici\MOD.165 - RAR RiskAssessmentAndRegister Rev.3.pdf" --numero 3` (controllare l'output) e poi con `--apply` → Rev.3 in bozza da verificare e proporre.
5. Fase 2: `manage.py importa_checklist_mod035b "\\novisrv\Sistema Gestione Integrato\9100_Qualità\_Modelli\MOD.035B RAIS Rapporto di Audit Interno di Sistema Rev0.pdf" --revisione 0` (dry-run: verificare sezioni/domande), poi ripetere con `--apply` nell'ambiente autorizzato.
6. Admin › ACL: assegnare `soa.edit` al CISO, `soa.approva` alla Direzione; per la fase 2 assegnare `audit.view/edit/esegui/approva` separatamente a MSM/RDD, auditor e Direzione.
7. Fase 2: configurare `SISTEMA_GESTIONE_AUDIT_SEDE` e `SISTEMA_GESTIONE_AUDIT_EMAIL_MSM`; verificare invio email/invito calendario in TEST.
8. Verificare che `DOCUMENT_ENCRYPTION_KEY` sia configurata in prod (copie firmate cifrate).

---

## 9. Riferimenti normativi usati nel disegno

- UNI EN ISO 19011:2018 — programma di audit basato sul rischio, piano, evidenze, rilievi, rapporto, follow-up, competenza degli auditor.
- UNI EN 9100:2018 §9.2 — programma, criteri e campo, **imparzialità degli auditor**, risultati alla direzione, **correzioni e azioni correttive senza ritardi ingiustificati**, evidenze conservate. Revisione IA9100 attesa tra fine 2026 e inizio 2027 (enfasi su efficacia dei processi).
- UNI ISO 45001:2018 §9.2 — consultazione dei lavoratori sul programma, comunicazione dei risultati a lavoratori e rappresentanti.
- UNI CEI EN ISO/IEC 27001:2022 §6.1.3 d) — SoA: controlli necessari, giustificazione di inclusione/esclusione, stato di attuazione; §9.2 audit interno.
- ISO 9001:2026 pubblicata il 16/09/2026 (transizione 3 anni).
