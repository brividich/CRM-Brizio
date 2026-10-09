# Timbri — rifacimento: documento di analisi (fase 1)

Data: 2026-10-10 · Branch: `feature/timbri-rifacimento` (da `origin/release/prod` `d47091c4`) · Stato: **in attesa di approvazione**

Ambito: registro dei timbri del personale (fisici, digitali, firme, sigle) come **identità di approvazione** qualità EN/AS 9100. Non riguarda le timbrature delle presenze.

---

## 1. Stato attuale

### 1.1 App `timbri`

**Modelli** (`timbri/models.py`)

| Modello | Righe | Note |
|---|---|---|
| `OperatoreTimbri` | 35-56 | Copia testuale di `anagrafica_dipendenti`. `legacy_anagrafica_id` è nullable, **non unique**, non è una FK. |
| `RegistroTimbro` | 88-182 | Dettaglio dei campi qui sotto. |
| `RegistroTimbroImmagine` | 185-248 | Varianti TIMBRO, FIRMA, SIGLA. Accetta solo `.png` fino a 20 MB. `delete()` cancella anche il file. |
| `TimbriImportIssue` | — | Righe scartate dall'import. |
| `TimbriUserPermOverride` | — | Override copy e download. |

Campi di `RegistroTimbro`:
- `codice_timbro`: **non unique**, default `""`.
- `operatore`: FK **CASCADE**.
- `tipo_timbro`: FISICO, DIGITALE, FISICO_E_DIGITALE, ALTRO, SOLO_FIRMA, SOLO_SIGLA.
- `data_consegna`, `data_ritiro`: opzionali.
- Stato: `is_attivo`, `is_archived`.
- Sospensione: `is_sospeso` e `sospeso_*`.
- `abilitazione_processo`: FK verso MOD.128.

L'ultima migrazione è la 0006.

**View** (`timbri/views.py`)
- Tutte le view usano solo `@login_required`, poi ruoli hardcoded e ACL legacy. Non esistono binding ACL v2 per le route.
- L'utente non autenticato via AJAX riceve un redirect, non un JSON 401.
- Due GET scrivono sul DB: `operatore_detail_by_legacy` (:832) e `report` (:710).

**Operazioni distruttive**
- `reset_timbri_table` (:378-394) cancella tutti i registri, le immagini e gli operatori. Basta il permesso *edit* e un `confirm()` JS. Lascia file cifrati orfani perché `QuerySet.delete()` non cancella i file.
- `cleanup_orphan_operatori` (:345-375) cancella fisicamente. Lo usa anche il comando `bonifica_timbri_orfani`, che non scrive audit.
- `operatore_delete` (:622) cancella fisicamente.
- `core/legacy_anagrafica.py:292-366` unisce gli omonimi e cancella gli operatori. Oggi è usato solo nei test.

**Import**
- Non esiste un import Excel. C'è solo `import_timbri_csv`: deduce il tipo da sottostringhe e aggancia l'operatore per id, poi matricola, poi etichetta del nome.
- `import_timbri_da_share` accetta jpg, gif e bmp, che poi il modello rifiuta: restano **file orfani su disco**.
- L'export CSV converte SOLO_FIRMA e SOLO_SIGLA in "Altro", quindi il round-trip perde il tipo.

**Immagini**
- Storage privato cifrato (`timbri/storage.py`), servito da una view protetta con audit (:1409).
- La cifratura viene **saltata se manca la chiave** (`core/encrypted_storage.py:76`).
- Mancano watermark, thumbnail e limiti in pixel.
- La "copia" usa l'URL inline, che richiede solo il permesso *view*: il permesso *copy* esiste solo nella UI.
- Il `Content-Disposition` usa il nome del file originale senza sanitizzarlo.

**Sospensione**: i campi esistono, ma nessuna UI o form li espone.

**Documentazione**: `docs/moduli/timbri.md` è obsoleto. Parla di "timbrature" e descrive un import SharePoint che è stato rimosso.

**Test**: `timbri/tests.py` ha 31 test, di cui 8 skip. Non c'è nessun test su univocità, storia o MIME del form.

### 1.2 MOD.128 (`anagrafica/services/mpq_timbri.py`)

- Il legame è la FK `RegistroTimbro.abilitazione_processo`. Il service non verifica che la persona dell'abilitazione coincida con quella del timbro.
- Un'abilitazione è considerata "operativa" se è `ATTIVA` e il processo non è scaduto. **Vengono ignorati**:
  - lo stato del processo (SOSPESO o REVOCATO);
  - le certificazioni individuali.
- Riattivazione (:99-111): **azzera la storia** della sospensione e rimette `is_attivo=True` anche sui timbri che erano già "superati".
- Nessun audit e nessun `MpqStorico`.
- Trigger:
  - comando manuale `mpq_propaga_timbri`, non schedulato;
  - una chiamata dalla view dentro `try/except: pass`.
- Il batch è tutto-o-niente perché `save()` chiama `full_clean`.
- L'email di notifica interpola i valori **senza escape** (:190-196).

### 1.3 Anagrafica

- Non esiste un modello Django canonico del dipendente. La chiave è l'id legacy della tabella `anagrafica_dipendenti`. `DipendenteAnagraficaAziendale.legacy_anagrafica_id` è unique e contiene `data_cessazione`.
- **Cessazione e cambio mansione non toccano i timbri**: un dipendente cessato conserva timbri attivi.
- Agganci possibili:
  - `dipendente_offboarding_chiudi` (`anagrafica/views.py:4789`);
  - `attiva_assegnazione` (`anagrafica/services/assegnazioni.py:448`);
  - trigger AU56, che però scatta solo su `mansione`.

### 1.4 gestione_specifiche: registro parallelo

**Modelli**
- `TimbroCapocommessa` (`models.py:722-755`): tipo `ricevuto`/`mod133`, `codice` non unico, flag `attivo` che di fatto è inerte. **Non usa l'app `timbri`.**
- `TimbroApplicazione` (:758-783): FK CASCADE, **non registra l'utente** che ha applicato il timbro.

**`applica_timbri`** (`timbri_views.py:52-119`):
- **Chiunque abbia COMPILA può apporre qualsiasi timbro**, compresa la firma dell'approvatore MOD.133 prima dell'approvazione.
- Nessun controllo sullo stato della specifica.
- La POST **cancella e ricrea** le applicazioni (:62), senza `atomic`.
- Un input malformato produce un errore 500.
- La GET invia in base64 **le firme di tutti gli utenti** a chiunque abbia COMPILA.

**Altri punti**
- `composito._risolvi_placements` non filtra i timbri non attivi.
- L'upload in `admin_views` non valida il MIME e la cancellazione è fisica, a cascata.
- Nessun `EventoSpecifica` sui timbri.

### 1.5 Censimento dati (DB di sviluppo, sola lettura)

| Voce | Valore |
|---|---|
| Operatori | 152. Nessuno senza id legacy, nessun id legacy duplicato |
| Registri | 238: 160 attivi, 67 archiviati, 0 sospesi, 0 con abilitazione MOD.128 |
| Tipi | FISICO_E_DIGITALE 187, DIGITALE 37, FISICO 14 |
| Codici vuoti | 5 |
| Senza data di consegna | 36 |
| Immagini | 258 |
| Codici su più registri | 9: 2 ripetuti sulla stessa persona, 4 passati tra persone diverse senza sovrapposizione |
| **Attivi su più persone** | **CNOT116** (2 persone): **conflitto vero** |
| Diciture condivise | **RICEVUTO** (19 persone) e **RIESAME** (6), DIGITALE. Sono timbri *funzionali* personali, non codici identificativi |

> I dati di produzione possono differire: il censimento va ripetuto in sola lettura sulla prod prima di applicare i vincoli.

---

## 2. Problemi principali

1. **Univocità assente.** Né il DB, né il form, né l'import garantiscono l'univocità del codice.
2. **Storia non garantita.** Cancellazioni fisiche, CASCADE, reset, sovrascritture e una riattivazione che azzera la sospensione rendono la query "chi aveva X il giorno Y" non affidabile.
3. **Identità della persona fragile.** Si basa su copie testuali, manca un vincolo unique e gli agganci per nome espongono a errori sugli omonimi.
4. **Sicurezza delle firme.** gestione_specifiche espone e permette di apporre firme altrui. Mancano watermark e audit della copia. La cifratura non è fail-closed.
5. **Ciclo di vita implicito.** Esistono due booleani e una sospensione non gestibile. Non c'è quarantena, smarrimento, ricevuta né richiesta o approvazione.
6. **Automatismi assenti o fragili.** MOD.128 non è schedulato, non scrive audit e ignora lo stato del processo. Cessazione e cambio mansione non producono effetti sui timbri.
7. **Due registri paralleli di identità di approvazione.** `timbri` e `gestione_specifiche` coesistono: è un rilievo prevedibile in audit AS9100.
8. **Permessi solo legacy.** Non ci sono route ACL v2 e le risposte AJAX non sono in JSON.

---

## 3. Modello target

### 3.1 Entità

**`OperatoreTimbri` diventa la persona canonica.** Classe e tabella restano invariate.
- Campi nuovi: `is_interno`, `user` (cache).
- `UniqueConstraint(legacy_anagrafica_id, condition=Q(is_interno=True))`.
- La migrazione esegue un pre-check che fallisce elencando i duplicati.

**`Timbro`**, anagrafica del timbro:
- `codice` e `codice_norm`. `codice_norm` è **unique globale**, normalizzato in maiuscolo, senza spazi e trattini doppi.
- `classe`: IDENTIFICATIVO oppure FUNZIONALE.
- `dicitura`.
- `persona_proprietaria`: solo per i funzionali.
- `tipo`: fisico, digitale, fisico+digitale, firma, sigla.
- `ambito`: ispezione, accettazione, processo speciale, riesame, ricevuto, altro.
- `abilitazione_processo`.
- `valido_fino`.
- `stato`, scritto solo dal service.
- `codice_bloccato`.
- `quarantena_fino`.

Timbri funzionali:
- codice generato `RICEVUTO-P<id>`;
- `UniqueConstraint(dicitura, persona_proprietaria)` condizionato alla classe FUNZIONALE;
- non riassegnabili;
- le diciture funzionali sono configurabili, mai dedotte automaticamente.

**`AssegnazioneTimbro`**: chi, `dal`, `al` (intervallo semiaperto), `aperta`, `motivo_fine`, `data_stimata`, ricevute di consegna e ritiro (file privato con sha256), snapshot di nome e matricola, `legacy_registro`.
- `UniqueConstraint(timbro, condition=Q(aperta=True))`: **un solo assegnatario attivo**.
- Check constraint di coerenza tra date e `aperta`.

**`TimbroBlocco`**: sospensioni componibili per origine (MANUALE, MPQ, CESSAZIONE, SCADENZA_QUALIFICA, SMARRIMENTO). Sostituisce il MARKER testuale.
- Il timbro è sospeso se ha almeno un blocco aperto.
- Ogni automatismo chiude solo i blocchi della propria origine.

**`TimbroEvento`**, append-only:
- registra transizione, data effetto, utente, origine, motivo obbligatorio e payload;
- **catena di hash** per l'evidenza di manomissione;
- `delete()` e update sono vietati.

**`TimbroSpecimen`**: versioni delle immagini, append-only. Contiene sha256, MIME e dimensioni, ed è vincolato a un'immagine `corrente` per variante. Non si cancella mai il file.

**Altri modelli**:
- `TimbroAccesso`: audit di download, copia, PDF e applicazione;
- `TimbriConfig`: riassegnazione, quarantena, diciture, destinatari;
- `ConflittoMigrazione`: conflitti da risolvere con decisione umana.

**"Chi aveva X il giorno Y"** è il servizio `storia.chi_aveva(codice, giorno)`. Restituisce:
- l'assegnazione valida a quella data;
- lo stato a quella data;
- i blocchi aperti a quella data.

Tutti i vincoli unique condizionati usano **condizioni positive**, perché sugli indici filtrati di SQL Server `~Q` non funziona. Il DDL va verificato con `sqlmigrate`.

### 3.2 State machine (`timbri/services/lifecycle.py`, unico punto di scrittura)

| Da | Azione | A | Permesso | Effetti |
|---|---|---|---|---|
| — | richiedi | RICHIESTO | `timbri.timbro.request` | Controllo live di univocità, blocco e policy di riassegnazione |
| RICHIESTO | approva / rifiuta | APPROVATO / ANNULLATO | `timbri.timbro.approve` (approvatore diverso dal richiedente) | |
| APPROVATO | emetti | EMESSO | `timbri.timbro.manage` | Apre l'assegnazione e genera la ricevuta |
| EMESSO | conferma ricevuta | ATTIVO | manage | Carica la ricevuta firmata |
| ATTIVO | sospendi | SOSPESO | manage o automatismo | Apre un blocco |
| SOSPESO | riattiva | ATTIVO | manage o automatismo della stessa origine | Torna attivo solo se nessun blocco resta aperto |
| ATTIVO / SOSPESO | ritira | RITIRATO → QUARANTENA | manage | Chiude l'assegnazione con motivo e genera la ricevuta di ritiro |
| ATTIVO / SOSPESO / EMESSO | smarrito | SMARRITO | manage (la persona stessa può segnalarlo) | **Codice bloccato per sempre**, invia un alert |
| QUARANTENA | distruggi / archivia | DISTRUTTO / ARCHIVIATO | manage | Genera un verbale |
| QUARANTENA scaduta | riapri per riassegnazione | APPROVATO | approve | Solo per i codici identificativi, secondo la policy e mai se bloccato |

Implementazione:
- tutto dentro `transaction.atomic`, con `select_for_update` sul timbro;
- create singoli, mai `bulk_create`;
- notifiche in `on_commit`;
- una data effetto retroattiva richiede il permesso `timbri.timbro.backdate` e non può precedere l'ultimo evento;
- un test per **ogni transizione non ammessa**.

### 3.3 Integrazioni

**MOD.128.** `mpq_timbri.py` viene riscritto mantenendo le firme pubbliche, sopra `TimbroBlocco(MPQ)`.
- Include lo stato del processo.
- Le certificazioni scadute aprono un blocco SCADENZA_QUALIFICA, attivabile da configurazione.
- Non azzera più la storia e non riattiva i timbri superati.
- Scrive audit.

**Scheduler giornaliero** `timbri_sincronizza_stati`, cron 00:15 dopo l'attivazione delle assegnazioni. Esegue:
1. la propagazione MPQ;
2. il controllo della scadenza `valido_fino`;
3. la riconciliazione con l'HR per cessazioni e rientri;
4. la notifica di fine quarantena;
5. il digest.

**Cessazione.** Apre un blocco CESSAZIONE, crea una richiesta di ritiro e invia un alert. Si aggiunge un hook `on_commit` minimale in offboarding e in "rimetti in forza", con logging e senza `pass`.

**Cambio mansione.** Un hook in `attiva_assegnazione` produce **proposte** di ritiro, mai ritiri automatici.

**gestione_specifiche**, in due passi:
- **Passo A:** FK `TimbroCapocommessa.timbro_registro` verso `Timbro`. Un comando di collegamento `--dry-run` mappa User → `utente_id` → persona; le ambiguità vanno nel report.
- **Passo B:** `applica_timbri` legge solo `Timbro`. `TimbroApplicazione` diventa append-only e registra utente, versione dello specimen, assegnazione e annullamento al posto del delete.
- Controlli in `applica_timbri`:
  - timbro attivo alla data;
  - titolare uguale all'utente;
  - stato della specifica compilabile;
  - input validato;
  - la GET mostra solo gli specimen propri, in anteprima.
- Ogni applicazione genera un `EventoSpecifica` e compare nella timeline del timbro.

### 3.4 Sicurezza

**Permessi ACL v2.**

| Codice | Uso |
|---|---|
| `timbri.modulo.view` | Consultazione, solo anteprime |
| `timbri.timbro.request` | Richiesta di emissione |
| `timbri.timbro.approve` | Approvazione e riassegnazione |
| `timbri.timbro.manage` | Emissione, sospensione, ritiro, smarrimento, quarantena |
| `timbri.timbro.backdate` | Date effetto retroattive |
| `timbri.specimen.upload` | Caricamento specimen |
| `timbri.specimen.download` | Download dell'originale |
| `timbri.specimen.copy` | Copia |
| `timbri.audit.export` | Export audit |
| `timbri.import.manage` | Import Excel |
| `timbri.migrazione.resolve` | Risoluzione dei conflitti di migrazione |
| `timbri.config.manage` | Configurazione |
| `gestione_specifiche.timbro.apply` | Applicazione dei timbri |

- I grant iniziali derivano dai pulsanti legacy `timbri_*`, in modalità create-only.
- Ogni route ha un binding exact.
- Il decorator `require_perm` risponde JSON 401/403 alle richieste AJAX.
- Nessuna GET scrive sul DB.

**Anteprime.** Massimo 320 px, watermark diagonale "ANTEPRIMA – NON VALIDO", JPEG, `Cache-Control: private, no-store`. L'originale si ottiene solo con il permesso di download e l'accesso viene registrato. La copia passa dallo stesso endpoint auditato.

**Upload.**
- Solo PNG e JPEG, niente SVG, controllati con `validate_extension_and_mime`.
- Pillow con limite di 25 Mpx e lato massimo di 4000 px, `exif_transpose`, ri-codifica PNG **senza metadati**, sha256.
- Il nome file viene sanitizzato nel `Content-Disposition`.

**Cifratura fail-closed.** Un system check segnala l'errore se manca la chiave con `DEBUG=False`.

---

## 4. Piano di migrazione

**Schema.** Migrazioni 0007-0010, solo creazione e vincoli, reversibili:
- 0007: modelli nuovi;
- 0008: persona e vincolo unique, con pre-check;
- 0009: ACL v2;
- 0010: collegamento a gestione_specifiche.

Le tabelle legacy `RegistroTimbro` e `RegistroTimbroImmagine` restano come **archivio in sola lettura**: non vengono mai modificate né cancellate.

**Dati.** Comando `timbri_migra_registro --dry-run | --apply [--run-id] [--report-dir]`.
- È idempotente: i registri già legati vengono saltati.
- Lavora con una transazione per codice.
- Produce un report JSON e CSV con le sezioni: unificati, duplicati, conflitti, non migrabili, date stimate, funzionali.

| Caso (dati dev) | Regola |
|---|---|
| RICEVUTO / RIESAME | Un `Timbro` FUNZIONALE per persona |
| Stesso codice sulla stessa persona (2) | Assegnazioni consecutive se il tipo coincide e gli intervalli sono compatibili, altrimenti **conflitto** |
| Codice passato tra persone (4) | Assegnazioni ordinate per data. Se l'ordine non è ricostruibile: **conflitto, gruppo non migrato** |
| **CNOT116** attivo su 2 persone | `ConflittoMigrazione`, **gruppo non migrato**. Si decide a mano nella pagina "Conflitti" |
| Codice vuoto (5) | Non migrabile ed elencato. In alternativa, solo su richiesta, codice provvisorio `PROVV-R<id>` in stato RICHIESTO |
| Senza data di consegna (36) | Data stimata da creazione o import, con `data_stimata=True` ed evento esplicativo. **Va validata dalla Qualità** |
| Archiviati (67) | Assegnazione chiusa, stato ARCHIVIATO |
| Immagini (258) | `TimbroSpecimen` v1 che punta allo stesso file cifrato, con sha256 calcolato sul contenuto in chiaro |

**Rollback.** `--rollback <run_id>` rimuove solo le righe create da quel run e prive di eventi successivi. Può lanciarlo solo un superuser, dopo un export.

**Produzione**, in quest'ordine:
1. censimento in sola lettura;
2. dry-run e consegna del report alla Qualità;
3. risoluzione manuale dei conflitti;
4. apply;
5. verifica a campione di "chi aveva X il giorno Y".

**Operazioni distruttive.** `reset_timbri_table`, `cleanup_orphan_operatori`, `operatore_delete` e `bonifica_timbri_orfani` vengono **eliminati**: non servono più e il modello non ammette cancellazioni. `core/legacy_anagrafica.cleanup_duplicate_anagrafica_rows` deve escludere i timbri.

---

## 5. Fasi di implementazione

Ogni fase ha test mirati, `--keepdb` e un commit sul branch feature.

| # | Fase | File principali |
|---|---|---|
| 1 | Modelli e vincoli | `timbri/models.py`, migrazioni 0007-0008, `timbri/tests/test_models_constraints.py` |
| 2 | Service lifecycle e storia | `timbri/services/{lifecycle,storia,policy}.py`, test per ogni transizione |
| 3 | Immagini | `timbri/services/images.py`, `timbri/storage.py` |
| 4 | ACL v2 | `timbri/permissions.py`, migrazione 0009, `acl_bootstrap.py` |
| 5 | Migrazione dati | `timbri_migra_registro`, `services/migrazione.py`, test sintetici: CNOT116, funzionali, vuoti, senza data |
| 6 | UI | Dashboard, registro storico, scheda timbro e scheda persona, wizard di emissione e ritiro, conflitti, PDF specimen sheet e ricevute, export audit. Le view legacy passano in sola lettura |
| 7 | Import Excel | Anteprima, mappatura, conflitti spiegati, idempotenza |
| 8 | MOD.128 e scheduler | `anagrafica/services/mpq_timbri.py`, `timbri/tasks.py`, `automazioni/schedules.py` |
| 9 | HR | `timbri/services/hr_sync.py` e hook in anagrafica |
| 10 | gestione_specifiche | Modelli e migrazione, `timbri_views.py`, `composito.py`, `admin_views.py` |
| 11 | Dismissione legacy e documentazione | `docs/moduli/timbri.md`, CHANGELOG, bump di versione |

Le fasi 3, 4 e 5 sono su file disgiunti e si possono delegare in parallelo dopo la 2. Lo stesso vale per le fasi 8 e 9.

---

## 6. Rischi

- I dati di produzione possono contenere nuovi conflitti o id legacy duplicati.
- Gli indici filtrati su mssql-django vanno verificati con `sqlmigrate`.
- La mappatura User → persona via `utente_id` può essere incompleta e bloccare il passo B di gestione_specifiche.
- Non è confermato che RIESAME corrisponda alle firme MOD.133 Revisore e Approvatore.
- Il cambio di comportamento in `applica_timbri` (niente più firme altrui) può bloccare chi oggi compila per conto di terzi: va comunicato prima del rilascio.
- I PDF già composti restano invariati.

---

## 7. Decisioni richieste prima dell'implementazione

1. **Riassegnazione** di un codice identificativo ritirato: mai, oppure dopo N anni? Quanti giorni di quarantena?
2. **Ruoli**: chi gestisce (Qualità, MSM o HR), chi approva l'emissione e chi consulta soltanto.
3. **Procedura** MT CN 06 §10.x: punti chiave del ciclo di vita, ad esempio se la ricevuta firmata è obbligatoria e se serve un verbale di distruzione.
4. **CNOT116**, attivo su 2 persone: a chi appartiene? Oppure il gruppo resta non migrato e lo si decide dalla pagina Conflitti.
5. **Diciture funzionali**: confermare RICEVUTO e RIESAME. Ce ne sono altre?
6. **gestione_specifiche**: approvare l'unificazione in `Timbro` (passi A e B) e confermare la corrispondenza RIESAME ↔ firme MOD.133.
7. **Codici vuoti** (5): elencarli come non migrabili oppure usare un codice provvisorio?
8. **Problemi concreti di oggi** da priorizzare: import, immagini, duplicati, lentezza.
