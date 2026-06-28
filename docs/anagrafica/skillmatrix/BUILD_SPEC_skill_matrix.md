# BUILD_SPEC — Skill Matrix MOD.187 (Abilitazioni macchina) · NOVICROM HUB

> Modulo **bridge** dentro l'app `anagrafica`. Aggiunge l'unico strato mancante
> (abilitazione macchina I/L/U/O + continuità operativa + matrice macchina) e
> **riusa** tutto ciò che già esiste (qualifiche, formazione, dipendenti, reparti).
> Espone resolver read-only che altri moduli (carichi macchina, ecc.) consumano.

---

## 0. CONTRATTO DI AUTONOMIA (leggere per primo)

Sei in modalità build autonoma su un repo Django 5.2 reale e grande (~28 app,
SQL Server in prod, SQLite in dev/test). Regole non negoziabili:

1. **Verifica prima di scrivere.** I nomi di modelli/campi citati qui sono stati
   letti dal codice ma DEVI riconfermarli aprendo i file reali prima di importarli
   o referenziarli. Se un nome non combacia, adegua il codice al reale, non viceversa.
2. **Non duplicare ciò che esiste.** Questo modulo AGGIUNGE solo lo strato macchina.
   Qualunque cosa già presente (qualifiche, formazione, storico qualifiche,
   dipendenti, reparti, matrice qualifiche) va **riusata/collegata**, mai riscritta.
3. **Build dentro l'app `anagrafica`** (nuovo `models_skillmatrix.py`, view, template,
   tab in subnav). NON creare una nuova app Django.
4. **Chiave dipendente = `legacy_anagrafica_id`** (IntegerField), come nel resto del
   progetto. NIENTE ForeignKey al modello dipendente.
5. **Compatibilità SQL Server (mssql-django)**: nessun indice parziale, nessun
   `UniqueConstraint` con `condition`, nessun `ArrayField`, nessun campo `unique`
   nullable. I test girano su SQLite.
6. **Read-only verso gli altri moduli**: il modulo espone resolver; non accoppia
   nulla all'indietro. Nessun altro modulo deve essere modificato per dipendere da
   questo (a parte il consumo opzionale dei resolver, in fasi successive).
7. **Italiano** in UI, label e commenti.
8. **Git discipline**: un commit atomico per fase Fn, messaggio
   `feat(skillmatrix): <fase> — <sintesi>`. NON pushare. Lascia il working tree
   pronto per la mia revisione del diff.
9. **BUILD_LOG**: mantieni `docs/skill-matrix/BUILD_LOG.md` aggiornato a ogni fase
   (cosa fatto, file toccati, decisioni, TODO, esito test). È il ponte di handoff.
10. **Self-recovery**: se i test rompono, fermati, diagnostica, correggi PRIMA di
    proseguire alla fase successiva. Mai accumulare fasi su test rossi.
11. **Orchestrazione lead + subagent sequenziale** (non parallela: vincolo RAM 32GB).
    Una fase per volta.
12. **Stop di approvazione umana** OBBLIGATORIO prima di: (a) cablare la continuità
    operativa alla sorgente di produzione reale (F5), (b) qualunque scrittura
    massiva di baseline (F2). In quei punti, prepara tutto, scrivi nel BUILD_LOG
    "ATTESA APPROVAZIONE", e fermati.

---

## 1. CONTESTO VERIFICATO (cosa esiste già — RIUSARE)

Letto dal repo. Riconferma i nomi prima di usarli.

### Identità e organizzazione (in `anagrafica/models.py`)
- `DipendenteAnagraficaAziendale` — dipendente canonico, chiave `legacy_anagrafica_id`,
  con `reparto` e `caporeparto_legacy_id`.
- `Reparto` (tabella storica `anagrafica_areaaziendale`) e `AreaAziendale`, con
  `caporeparto_legacy_id` → identifica i **CAR**.
- `Mansione` (con `livello_rischio`, `dpi_richiesti`, `visite_richieste`),
  `RuoloOperativo`, `RuoloAziendale`.

### Processi qualificati con scadenza = GIÀ GESTITI (NON ricreare)
- `TipoQualifica`, `DipendenteQualifica` (`data_conseguimento`, `data_scadenza`,
  `livello`, `ente`, evidenza documentale, `verificata`, proprietà `is_scaduta` /
  `in_scadenza`), `QualificaSessione`, `DipendenteQualificaStorico` (storico
  append-only dei rinnovi).
- È il "Processo qualificato GIÀ GESTITO · MOD.128 MPQ" della proposta. Il tab
  **"Processi qualificati"** della skill matrix DEVE collegarsi a questi dati, non
  duplicarli.

### Formazione / corsi = GIÀ GESTITI (hook "refresh come corso")
- `models_formazione.py`: `TrainingPlan`, `TrainingCourse` (FK `qualifica`),
  `TrainingRequirementRule` (mansione/area/ruolo → corso obbligatorio),
  `TrainingAssignment`, `TrainingSession`, `TrainingEnrollment`,
  `TrainingEmployeeRecord` (completamento + `data_scadenza`), `TrainingCertificate`,
  `TrainingDeadline` (cache scadenze), e-learning (`TrainingSlide`,
  `TrainingQuizQuestion`, `TrainingElearningEnrollment`), `ElearningConfig`.
- Comando `link_qualifiche_corsi` lega qualifica ↔ corso.
- Servizi: `training_eligibility.py`, `training_deadline_service.py`, `mansionario.py`.

### Matrice competenze (qualifiche) GIÀ ESISTENTE
- `anagrafica/views.py::matrice_competenze` + `templates/.../matrice_competenze.html`,
  URL `anagrafica:matrice_competenze` (`sicurezza/matrice/`), area *Salute e Sicurezza*.
  È dipendenti × qualifiche/abilitazioni (valido/in scadenza/scaduto) per audit
  ISO 45001. Riusa le sue classi CSS (`mc-table`, `mc-cell-*`) e il pattern tab.

### Macchine / asset
- `assets.Asset` (campo `asset_tag`, `name`, `reparto` testo). Identità canonica
  macchina. Per il match codice→asset riusa il pattern alias di
  `gestione_carichi_macchina.MacchinaAlias` (uppercase, no spazi; ZEISS = match su
  nome completo, codice non univoco).

### ACL / permessi
- `anagrafica/acl_bootstrap.py` e pattern `AnagraficaFormazionePermission` per i
  livelli di accesso. Registra le nuove route con permission code coerenti alla
  convenzione del progetto (vedi `doc/ACL_V2_PERMISSION_CODE_CONVENTION.md`).

---

## 2. COSA COSTRUIRE (l'unico strato nuovo)

1. **Abilitazione macchina I/L/U/O** su `assets.Asset` — non esiste.
2. **Continuità operativa** (regola 12 mesi da esecuzione reale di produzione) — nuova.
3. **Matrice persone × macchine** con KPI dedicati — distinta dalla matrice qualifiche.
4. **Resolver bridge read-only** consumabili da altri moduli (primo cliente:
   `gestione_carichi_macchina`).
5. **Importer** dello storico MOD.187 (4 CSV) come baseline ufficiale + storico seminato.
6. **Refresh semestrale** (campagna + approvazione di merito SOLO CAR).

---

## 3. MODELLO DATI (nuovo — `anagrafica/models_skillmatrix.py`)

Tutti i modelli usano `legacy_anagrafica_id` per il dipendente. Compatibili SQL Server.

### 3.1 Scala e configurazione
- **Scala I/L/U/O** ordinata `I < L < U < O`. Memorizza il livello come
  `CharField(choices=[(I,..),(L,..),(U,..),(O,..)])` PIÙ un ordinale derivato per i
  confronti. Etichette esatte (MT CN 06 §8.3), **configurabili** (non hardcoded):
  - I = In formazione (solo affiancamento/tutoraggio)
  - L = Intermedio (autonomia su note; supervisione CAR su nuove/complesse)
  - U = Autonomo (piena autonomia nel rispetto delle istruzioni)
  - O = Formatore/Esperto (forma altri; programma a bordo macchina se applicabile)
  - **Cella vuota = NON in lista** per quella macchina (esclusione deliberata del CAR,
    NON un livello). Modellata come assenza di record `in_lista=True`, non come livello.
- **`SkillMatrixConfig`** (singleton): `soglia_operativa` (default `U`: livelli ≥ soglia
  contano come operativi nel pool), `regola_multivoce` (`MIN`/`MEDIA`/`BLOCCANTI`,
  default `MIN`, marcata "da confermare in sessione CAR"), `finestra_continuita_mesi`
  (default 12), `preavviso_continuita_mesi` (default 9), `periodicita_refresh_mesi`
  (default 6), `soglia_uomo_solo` (default 2, MT CN 06 §8.2.2),
  `includi_car_come_riserva` (default False).

### 3.2 Abilitazione macchina
- **`AbilitazioneMacchina`**:
  - `legacy_anagrafica_id` (IntegerField, db_index)
  - `asset` → `ForeignKey("assets.Asset", on_delete=PROTECT, related_name="abilitazioni_skm")`
  - `livello` (I/L/U/O)
  - `in_lista` (Boolean, default True) — chi non è in lista non opera su quell'asset
  - `stato` (`attiva` / `sospesa`), default `attiva`
  - `conteggiabile_nel_carico` (Boolean, default True) — **False per i CAR**
    (derivato all'import dal prefisso ruolo `CAR <area>`); i CAR restano visibili ma
    fuori dal pool capacità.
  - `livello_richiesto` (I/L/U/O, null) — livello atteso per la mansione su quell'asset
    (per il marker ▲ "sotto livello richiesto")
  - `car_legacy_id` (IntegerField, null) — CAR titolare
  - `data_assegnazione`, `prossima_revisione` (date), `note`
  - proprietà derivata `is_operational` = `stato==attiva AND in_lista AND
    ordinale(livello) >= ordinale(config.soglia_operativa) AND conteggiabile_nel_carico`
  - vincolo unique `(legacy_anagrafica_id, asset)`.
- **`VoceMacchinaCatalogo`** + **`AbilitazioneMacchinaVoce`** (macchine "più voci"):
  voci valutate per **tipo** di macchina (non per singolo asset), configurabili
  (es. lettura disegno, set-up, programmazione BM, esecuzione, autocontrollo,
  manutenzione 1° liv.). Il livello complessivo di un'`AbilitazioneMacchina` multivoce
  si calcola dalle voci secondo `config.regola_multivoce`. Predisponi il catalogo
  vuoto + la regola; popolamento voci = sessione CAR (non bloccante per il resto).

### 3.3 Storico (append-only — ricalca `DipendenteQualificaStorico`)
- **`AbilitazioneMacchinaStorico`**: `legacy_anagrafica_id`, `asset`, `livello`,
  `data_rilevazione`, `fonte` (`import`/`refresh`/`manuale`), `car_legacy_id`,
  `note`. Ogni rinnovo/modifica produce uno scatto datato. **Seminato dai 2 snapshot**
  dell'import (2024-04-22 e 2026-04-30).

### 3.4 Continuità operativa (nuova)
- **`ProcessoCriticoContinuita`** (catalogo): `nome`, `riferimento_normativo`
  (es. EN 4179/NAS 410, MT CN 65 §3.7), `finestra_mesi` (override config),
  collegamento opzionale a `TipoQualifica` esistente. Elenco processi monitorati
  **da confermare** (CND-PT certo; saldatura ISO 9606 e cromatura = aperti).
- **`ContinuitaOperativa`**: `legacy_anagrafica_id`, `processo`
  (FK `ProcessoCriticoContinuita`), `ultima_esecuzione` (date, popolata dalla
  produzione), stato derivato:
  - `mantenuta` (esecuzione ≤ finestra)
  - `in_scadenza` (tra preavviso e finestra → alert Annual Proficiency)
  - `persa` (> finestra → **sospende** l'abilitazione collegata, MT CN 65 §3.7;
    UNICA regola bloccante).

### 3.5 Refresh semestrale
- **`CampagnaRefresh`**: `periodo` (date), `scadenza`, `reparto`/`area`,
  `avviatore_ruolo` (CharField configurabile — è solo il *trigger* della tornata,
  NON un approvatore di merito), `stato` (`aperta`/`chiusa`). L'**approvazione di
  merito è SOLO del CAR** sul proprio reparto. NIENTE MSO/RDD (quelli sono del flusso
  specifiche, non c'entrano qui).
- Il rinnovo del CAR (conferma invariati o modifica) scrive in
  `AbilitazioneMacchinaStorico`.

### 3.6 Contatore "corsi attivati"
- La colonna "corsi attivati" del MOD.187 **non è un livello**: è un intero. Modellala
  come attributo separato per dipendente (`SkmCorsiAttivati.legacy_anagrafica_id`,
  `numero`), NON come `AbilitazioneMacchina`.

---

## 4. FASI DI BUILD (F0 → F9, sequenziali)

### F0 — Discovery & contratto
- Leggi e conferma i nomi reali di: `DipendenteAnagraficaAziendale`, `Reparto`,
  `AreaAziendale`, `Mansione`, `TipoQualifica`, `DipendenteQualifica`,
  `DipendenteQualificaStorico`, `assets.Asset`, `gestione_carichi_macchina.MacchinaAlias`,
  e gli helper `acl_bootstrap.py`.
- Inizializza `docs/skill-matrix/BUILD_LOG.md`.
- Annota nel log eventuali scostamenti dai nomi attesi.

### F1 — Modelli + migrazioni
- Crea `anagrafica/models_skillmatrix.py` con i modelli §3. Importa nel `models.py`
  dell'app come fa già `models_formazione.py`.
- Migrazione SQL-Server-safe. Verifica con `makemigrations --check` e `migrate` su
  SQLite.
- Test modello (creazione, vincoli unique, `is_operational`, derivazione stato
  continuità).

### F2a — Asset-matching report (GATE OBBLIGATORIO prima di qualunque import)
Il punto fragile **non è il personale** (i nomi sono anagrafica pulita: match diretto
nome → `legacy_anagrafica_id`, senza gate). Il punto fragile è il **match
colonna-macchina → `assets.Asset`**, per tre ragioni note dai dati:
codici sparsi tra `asset_tag`/`name` con formati incoerenti; **ZEISS** (6 CMM con lo
stesso prefisso → match su nome completo); **7 macchine rinominate** tra snapshot
(`DMG`/`DMC`, spazi) → match sul CODICE, non sulla descrizione.

- Comando `skm_asset_match_report` (sola lettura, NON scrive baseline) che, partendo
  da `skm_catalogo_competenze.csv` (solo righe `tipo=macchina`), produce
  `docs/skill-matrix/asset_match_report.csv` con colonne:
  `competenza_key, nome_mod187, codice, asset_match_id, asset_tag, asset_name,
  confidenza (esatto|parziale|assente), strategia (asset_tag|name|alias|manuale),
  azione_suggerita`.
- Strategia di match (riusa il pattern di `gestione_carichi_macchina.MacchinaAlias`:
  normalizzazione uppercase/no-spazi):
  1. codice == `asset_tag` normalizzato → **esatto**;
  2. codice presente in `name` normalizzato → **parziale**;
  3. ZEISS / casi noti → match sul **nome completo** → parziale;
  4. nessun match → **assente**.
- Le **41 colonne `processo`** NON si mappano ad asset (non sono macchine): diventano
  voci del catalogo competenze. Il `contatore` ("corsi attivati") è escluso dal report.
- **GATE**: scrivi il report, riportane il riepilogo nel BUILD_LOG
  (N esatti / N parziali / N assenti) e **fermati** con "ATTESA CONFERMA MATCH ASSET".
  Nessun passo successivo finché il match parziale/assente non è confermato a mano
  (l'operatore validerà il CSV o popolerà gli alias). I match `esatto` sono comunque
  pre-approvati.

### F2b — Importer baseline (STOP approvazione prima della scrittura massiva)
Eseguibile **solo dopo** che il match asset di F2a è confermato.
- Comando `import_skill_matrix` che ingerisce i 4 CSV (path atteso:
  `docs/skill-matrix/seed/skm_*.csv`):
  - `skm_catalogo_competenze.csv` → crea catalogo macchine usando il **match asset
    confermato in F2a** (alias `da_confermare` solo per i residui); processi; tratta
    "corsi attivati" come contatore; le colonne `processo` che corrispondono a
    `TipoQualifica` esistenti le **collega**, non le ricrea.
  - `skm_operatori.csv` → match diretto `nome` → `legacy_anagrafica_id` (no gate);
    imposta reparto; `is_car=SI` ⇒ `conteggiabile_nel_carico=False`; **academy inclusi**.
  - `skm_matrice_livelli.csv` → popola `AbilitazioneMacchina` (snapshot più recente =
    baseline) e alimenta lo storico per ENTRAMBI gli snapshot.
  - `skm_storico_delta.csv` → verifica di coerenza dello storico seminato.
  - Scrittura **diretta come baseline ufficiale** (dati già validati, NON bozza),
    con `data_emissione` e avvio ciclo semestrale.
- **Robustezza**: nome personale non risolto → report esplicito (mai drop silenzioso),
  ma è un'eccezione non attesa; macchina senza match confermato → BLOCCA quella riga e
  la elenca (non inventare l'asset); idempotenza (re-run non duplica); `--dry-run` che
  stampa il piano senza scrivere.
- **STOP**: prepara tutto, esegui `--dry-run`, scrivi nel BUILD_LOG l'esito e
  "ATTESA APPROVAZIONE prima della scrittura baseline", fermati.

### F3 — Resolver bridge (read-only)
- `anagrafica/services/skillmatrix_resolver.py`:
  - `pool_abilitati(asset, livello_min=None) -> list[legacy_anagrafica_id]` — abilitati
    `is_operational` su quell'asset (filtra CAR via `conteggiabile_nel_carico`, applica
    soglia; `includi_car_come_riserva` opzionale).
  - `livello_operatore(legacy_anagrafica_id, asset)`, `kpi_uomo_solo(asset)`,
    `macchine_scoperte(reparto)`, `prontezza_squadra(reparto)`.
- Nessuna scrittura. Test dedicati (incluso: CAR esclusi, academy inclusi, soglia).
- Documenta nel BUILD_LOG che questi resolver sono il punto d'aggancio della
  **Fase B** (overlay disponibilità nei carichi macchina).

### F4 — Matrice macchina (UI) + tab
- View `skill_matrix_macchina` + template che riusa le classi CSS della
  `matrice_competenze` esistente (`mc-table`, `mc-cell-*`) e il design system HUB
  (navy `#0c2545`, cyan `#1f87cd`, orange `#ff8a1f`).
- Matrice persone × macchine per reparto: celle I/L/U/O; `▲` sotto livello richiesto;
  **tratteggio = rivalutazione arretrata (NON bloccante)**; barra blu = multivoce;
  `◉` = continuità monitorata.
- **KPI** in testa: Prontezza squadra (%U/O), Macchina scoperta (0 abilitati in lista),
  Rischio uomo solo (< `soglia_uomo_solo` persone U/O), Continuità persa.
- Export CSV + Stampa.
- **Tab**: "Macchina" (questa) + "Processi qualificati" che **rimanda alla matrice
  qualifiche esistente** (`anagrafica:matrice_competenze`), non la riscrive.

### F5 — Continuità operativa (STOP approvazione prima del cablaggio produzione)
- Catalogo `ProcessoCriticoContinuita` + popolamento `ContinuitaOperativa`.
- `ultima_esecuzione` va letta dall'**esecuzione reale di produzione** (timbri /
  avanzamento ordini). Individua la sorgente corretta nel repo (NON inserimento
  manuale), ma **fermati prima di cablarla**: documenta la sorgente candidata nel
  BUILD_LOG e attendi approvazione.
- Logica stati (mantenuta/in_scadenza/persa) + regola di sospensione automatica
  dell'abilitazione collegata su `persa`.

### F6 — Refresh semestrale (CAR)
- `CampagnaRefresh` + schermata CAR a 2 gruppi (① in lista → rivaluta; ② aggiunte
  manuali). "Conferma invariati" e modifica → scatto in `AbilitazioneMacchinaStorico`.
- Trigger campagna = ruolo `avviatore_ruolo` configurabile (solo innesco). Merito =
  SOLO CAR sul proprio reparto.
- Arretrato visibile, **non bloccante**.

### F7 — ACL + navigazione
- `acl_bootstrap` per le nuove route, permission code da convenzione. Voce di subnav
  sotto Anagrafica/Competenze, nome esplicito **"Skill Matrix — Abilitazioni macchina
  (MOD.187)"** per non collidere con la "Matrice competenze (Salute e Sicurezza)".

### F8 — Hardening test
- Suite completa verde (modelli, importer, resolver, UI smoke, continuità, refresh,
  ACL). Tutti i test ESISTENTI di `anagrafica` restano verdi.

### F9 — Chiusura
- Finalizza BUILD_LOG (cosa fatto, file, decisioni, TODO aperti: regola multivoce,
  voci per tipo macchina, elenco processi critici, granularità asset, visibilità
  matrice). NON committare oltre i commit di fase. NON pushare.

---

## 5. PUNTI APERTI DELLA PROPOSTA → default configurabili

Implementa con default sensato e marca "da confermare in sessione CAR", MAI hardcoded:
- **Regola totale multivoce**: default `MIN` (più rigoroso).
- **Voci per tipo macchina**: catalogo vuoto, da popolare coi CAR.
- **Granularità asset**: per singola macchina (default), predisposto per famiglia/tipo.
- **Processi critici con continuità**: CND-PT attivo; altri (saldatura/cromatura) da
  confermare.
- **Visibilità matrice**: default CAR vede il proprio reparto; ruolo qualità vede tutto;
  configurabile.

---

## 6. CRITERI DI ACCETTAZIONE

- [ ] Nessun modello duplica qualifiche/formazione/storico esistenti; il tab "Processi
      qualificati" rimanda alla matrice qualifiche esistente.
- [ ] Dipendenti agganciati via `legacy_anagrafica_id` (nessuna FK dipendente).
- [ ] CAR esclusi dal pool (`conteggiabile_nel_carico=False`), academy inclusi.
- [ ] F2a: `asset_match_report.csv` prodotto; match macchina→asset confermato prima
      di scrivere baseline; personale matchato direttamente sul nome (senza gate);
      processi NON mappati ad asset.
- [ ] Import scrive baseline ufficiale (non bozza) e semina storico con i 2 snapshot;
      righe macchina senza match confermato bloccate ed elencate, mai inventate.
- [ ] Resolver `pool_abilitati` read-only funzionante (pronto per i carichi).
- [ ] Continuità persa > finestra sospende l'abilitazione; arretrato semestrale NON
      blocca.
- [ ] Refresh: merito solo CAR; trigger campagna = ruolo configurabile; ogni modifica =
      scatto storico.
- [ ] Migrazioni SQL-Server-safe; tutti i test (nuovi + esistenti anagrafica) verdi.
- [ ] Diff limitato all'app `anagrafica` (+ `docs/skill-matrix/`); nessun altro modulo
      modificato.

## 7. OUTPUT
Lascia il working tree modificato (commit per fase, NO push). BUILD_LOG completo con
conteggio test, decisioni, sorgente continuità candidata, e TODO aperti.
