# BUILD_LOG — Skill Matrix MOD.187 (Abilitazioni macchina)

> Modulo bridge dentro l'app `anagrafica`. Aggiunge lo strato "abilitazione
> macchina I/L/U/O + continuità + matrice macchina" riusando qualifiche,
> formazione, dipendenti, reparti già esistenti. Ponte di handoff fra le fasi.

Spec di riferimento: `docs/anagrafica/skillmatrix/BUILD_SPEC_skill_matrix.md`
Seed CSV: `docs/anagrafica/skillmatrix/skm_*.csv` (+ `README_skm_csv.md`).

---

## F0 — Discovery & contratto ✅ (2026-06-25)

### Nomi reali riconfermati dal codice (no assunzioni)

| Atteso (spec) | Reale nel repo | Note |
|---|---|---|
| `DipendenteAnagraficaAziendale` | `anagrafica/models.py:957` | chiave `legacy_anagrafica_id` (IntegerField **unique**). NON contiene nome/cognome: `area` (=reparto testo), `area_aziendale_nome`, `caporeparto_legacy_id`, `ruolo_aziendale`. |
| nome→legacy_id | `core.legacy_anagrafica.fetch_anagrafica_rows(deduplicate=True)` | righe con chiavi `id, nome, cognome, mansione, reparto, attivo, …`. **Fonte unica** per il match operatore→legacy_id (CSV operatore = "COGNOME NOME"). |
| `Reparto` | `anagrafica/models.py:751` (db_table storica `anagrafica_areaaziendale`) | ha `caporeparto_legacy_id` → identifica i CAR. |
| `AreaAziendale` | `anagrafica/models.py:728` (db_table `anagrafica_area_aziendale`) | |
| `Mansione` | `anagrafica/models.py:405` | `livello_rischio`, M2M `dpi_richiesti`, `visite_richieste`. |
| `TipoQualifica` | `anagrafica/models.py:478` | `nome` unique, `durata_mesi`. |
| `DipendenteQualifica` | `anagrafica/models.py:522` | `legacy_anagrafica_id`, `tipo` FK, `data_conseguimento/scadenza`, `livello`, `ente`, `numero`, `verificata`; proprietà `is_scaduta`/`in_scadenza`. |
| `DipendenteQualificaStorico` | `anagrafica/models.py:674` | append-only; `origine` choices MANUALE/SESSIONE/IMPORT. Pattern da ricalcare per lo storico abilitazioni. |
| `assets.Asset` | `assets/models.py:18` | `asset_tag` (**unique**), `internal_number`, `name`, `asset_type` (incl. `CNC`, `WORK_MACHINE`), `reparto` (testo). Identità canonica macchina. |
| match codice→asset | `gestione_carichi_macchina/asset_resolver.py` | **funzioni pure riusabili**: `normalizza_codice`, `IndiceAsset.costruisci(assets)`, `risolvi(codice, indice) -> Risoluzione(asset, fonte, confidenza)`; confidenze `alta/media/ambigua/assente`. Lavora su qualsiasi oggetto con `asset_tag`/`name` → la passo `assets.Asset`. |
| pattern alias | `gestione_carichi_macchina.MacchinaAlias` | alias `codice_foglio→Macchina` con `da_confermare`; pattern, non riuso diretto (quello punta a `gcm.Macchina`, non ad `assets.Asset`). |
| singleton config | pattern `AnagraficaHRPermission.get_instance()` (`models.py:1543`) → `get_or_create(pk=1)`. |
| ACL bootstrap | `anagrafica/acl_bootstrap.py` → `core.acl_bootstrap_base.run_bootstrap(defs, cache_key, "anagrafica", …)`. |
| matrice qualifiche esistente | `anagrafica/views.py:13064 matrice_competenze` + template `anagrafica/pages/matrice_competenze.html`, URL `anagrafica:matrice_competenze`. Riuso classi CSS e pattern tab. |

### Scostamenti / decisioni rispetto alla spec
1. **`assets.Asset` ≠ `gcm.Macchina`.** `MacchinaAlias` punta a `gcm.Macchina`, ma
   la spec §3.2 impone `AbilitazioneMacchina.asset → assets.Asset`. Quindi il match
   F2a viene fatto contro `assets.Asset` riusando le **funzioni pure** di
   `asset_resolver.py` (non il modello alias di gcm). Nessuna modifica a gcm.
2. **Catalogo competenze.** La spec parla più volte di "catalogo competenze/macchine"
   ma §3 non definisce un modello omonimo. Introduco `CompetenzaSkm` (chiave
   `competenza_key`, unico) come backbone del catalogo + cache del match asset
   (confidenza/strategia/confermato). Link macchina→`assets.Asset` e processo→
   `TipoQualifica` (FK opzionali). **Non duplica** qualifiche/formazione.
3. **Etichette I/L/U/O configurabili** → override in `SkillMatrixConfig`
   (`etichetta_i/l/u/o`); l'ordinale `I<L<U<O` resta fisso (scala MT CN 06 §8.3).
4. **Competenze "processo" con livello per-persona** (i CSV hanno livelli su processi,
   es. "Fresatrice generica: O"): NON entrano nello strato macchina (la matrice F4 è
   persone×macchine). In F2b verranno gestite via catalogo/qualifiche e **riportate
   esplicitamente** (mai drop silenzioso). Decisione finale al gate F2b.

### Dati seed (letti)
- `skm_catalogo_competenze.csv`: 84 competenze (42 macchine, 41 processi, 1 contatore
  "corsi attivati"). 7 macchine **rinominate** tra snapshot (DMC/DMG) → match su CODICE
  via `alias_storici`. 7 **ZEISS** (codice non univoco) → match su nome completo.
- `skm_operatori.csv`: 102 operatori, 21 aree, 8 CAR (`is_car=SI`), 7 academy. Alcune
  sotto-aree senza riga CAR propria → `car_di_riferimento` punta al CAR padre.
- `skm_matrice_livelli.csv`: livelli I/L/U/O per (operatore, competenza, snapshot);
  baseline = 2026-04-30, storico = 2024-04-22.
- `skm_storico_delta.csv`: 112 nuove, 43 promozioni, 5 regressioni (verifica coerenza).

**Esito F0:** nomi confermati, nessun blocco. Procedo a F1.

---

## F1 — Modelli + migrazioni  ✅ (2026-06-25)

**File toccati:**
- `django_app/anagrafica/models_skillmatrix.py` (nuovo) — tutti i modelli §3.
- `django_app/anagrafica/models.py` — aggiunto `from .models_skillmatrix import *`.
- `django_app/anagrafica/migrations/0071_campagnarefresh_skillmatrixconfig_skmcorsiattivati_and_more.py` (nuovo).
- `django_app/anagrafica/tests_skillmatrix.py` (nuovo) — 12 test modello.

**Modelli creati:** `LivelloSkm` (TextChoices) + `ordinale_livello`; `SkillMatrixConfig`
(singleton pk=1, etichette I/L/U/O configurabili); `CompetenzaSkm` (catalogo + cache
match asset); `AbilitazioneMacchina` (unique persona-asset, `is_operational`,
`sotto_livello_richiesto`); `VoceMacchinaCatalogo` + `AbilitazioneMacchinaVoce`;
`AbilitazioneMacchinaStorico` (append-only); `ProcessoCriticoContinuita` +
`ContinuitaOperativa` (stato derivato); `CampagnaRefresh`; `SkmCorsiAttivati`.

**Decisioni:** vedi F0 #1-4 (Asset≠gcm.Macchina → match su `assets.Asset` con le
funzioni pure di `asset_resolver`; `CompetenzaSkm` come catalogo; etichette
configurabili; processi con livello gestiti al gate F2b).

**SQL-Server-safe:** tutti i vincoli sono `UniqueConstraint` senza `condition`;
nessun `unique` nullable; nessun indice parziale; nessun `ArrayField`.

**Esito test:** `python manage.py test anagrafica.tests_skillmatrix --settings=config.settings.test --keepdb`
→ **12 passed**. `makemigrations --check` pulito. `migrate` su SQLite OK.

## F2a — Asset-match report  ⛔ GATE: **ATTESA CONFERMA MATCH ASSET** (2026-06-25)

**File toccati:**
- `django_app/anagrafica/services/skillmatrix_match.py` (nuovo) — matcher puro a token.
- `django_app/anagrafica/management/commands/skm_asset_match_report.py` (nuovo) — comando **sola lettura**.
- `django_app/anagrafica/tests_skillmatrix_match.py` (nuovo) — 13 test.
- `docs/skill-matrix/asset_match_report.csv` (generato) — **derivato dal DB dev**.

**Strategia di match** (self-contained in anagrafica, niente import cross-modulo):
normalizzazione uppercase/no-spazi (pattern gcm) + match a **token interi** del
tag/nome (gestisce codici sole-lettere `STZ/HH/CNV` e con cifra iniziale `35S`,
e mantiene la precisione `DM1≠DM10≠DM11`). Mappatura confidenza:
codice in `asset_tag` → **esatto**; solo in `name` → **parziale**; ambiguo/assente
→ **parziale/manuale** o **assente**; ZEISS (codice non univoco) → match sul nome
completo (best-overlap), sempre "confermare a mano". **Declassamento** di un
"esatto" sospetto (= pre-approvato, salterebbe la review): asset di tipo
non-macchina, oppure **codice ≤2 char** (collisione tipo `HI → PCHI`).

**Esito (DB dev, 773 asset, 42 macchine):** **18 esatti · 14 parziali · 10 assenti.**
- **Esatti (18, pre-approvati):** CNT1, DM2…DM15, DM3, MK1, MK2, TNZ — tutti su
  `asset_tag` `CNC-<codice>-<seriale>` (i 7 rinominati DMC/DMG matchano sul codice,
  come atteso).
- **Parziali (14, da confermare):**
  - solo-nome (asset `name`==codice, tag generico `CNC-00000x`): **AGV1, AGV2, AGV3,
    DM1, MK3** — probabilmente corretti, confermare.
  - **CNV** → 2 asset col codice nel nome (disambiguare).
  - **HI** → declassato: ha colpito `IT-PC-HI`/`PCHI` (un PC mistippato `OTHER`).
    **Quasi certamente NON la HITACHI**: escludere o creare l'asset macchina.
  - **7 ZEISS** (CONTURA G2, DURAMAX ×2, PRISMO ×4) → 2–6 candidati ciascuno:
    disambiguare per matricola/modello a mano.
- **Assenti (10, da creare/alias o escludere):** 35S, D1, ELT1, HH, HY1, **MZ2, MZ3,
  MZ5, MZ6** (tutti i Mazak), STZ — non presenti tra gli asset del DB dev.

⚠️ **Il report è derivato dal DB *dev*.** Va **rigenerato nell'ambiente target**
(`python manage.py skm_asset_match_report --settings=config.settings.prod`) e
validato lì prima dell'import: i Mazak assenti in dev potrebbero esserci in prod.

**Test:** `anagrafica.tests_skillmatrix_match` → **13 passed**. `manage.py check` pulito.

### ⛔ STOP — cosa serve per sbloccare F2b
1. Validare a mano `docs/skill-matrix/asset_match_report.csv` (rigenerato in target):
   confermare i **parziali**, decidere su **assenti** (creare asset/alias o escludere),
   risolvere **ZEISS** e il caso **HI**.
2. Confermare/correggere la colonna `asset_match_id` per parziali/assenti.
3. Dare l'ok esplicito: solo allora parte **F2b** (import baseline, con ulteriore
   STOP di approvazione prima della scrittura massiva, e `--dry-run` come default).

## F2a-UI — Specchietto di validazione in portale  ⛔ GATE ancora attivo (2026-06-25)

> Richiesta utente: «in prod gli asset sono diversi, puoi inserire uno specchietto
> per associarli all'interno del portale?». Il report CSV era derivato dal DB dev →
> serviva un modo di validare il match **nell'ambiente target**, senza editare CSV.

**Decisione packaging:** il catalogo viaggia come **modulo Python**
(`anagrafica/skillmatrix_catalogo.py`, `CATALOGO_MOD187`), non come CSV: prod esclude
`docs/` e l'allowlist di release esclude i file dati → il CSV non arriverebbe in prod.
Il modulo `.py` è sempre disponibile a runtime. Contiene **solo** chiavi/display/codici
del catalogo macchine-processi (nessun dato personale).

**File toccati:**
- `django_app/anagrafica/skillmatrix_catalogo.py` (nuovo) — catalogo 84 voci come dati Python.
- `django_app/anagrafica/services/skillmatrix_seed.py` (nuovo) — `sincronizza_catalogo()`:
  upsert idempotente di `CompetenzaSkm` dal catalogo + match macchine vs asset live;
  auto-conferma gli "esatto"; **preserva le conferme manuali** (non ricalcola se
  `match_confermato=True`); collega i processi a `TipoQualifica` per nome.
- `django_app/anagrafica/management/commands/skm_seed_catalogo.py` (nuovo) — wrapper CLI `--dry-run`.
- `django_app/anagrafica/services/skillmatrix_match.py` — refactor: `match_competenza()`
  centralizza il declassamento; `AssetRef` con `asset_type`; usato dal report e dal seed.
- `django_app/anagrafica/views.py` — nuova view `skm_match_validazione` (GET tabella +
  POST `sincronizza`/`salva`), guard `_check_hr_permission`.
- `django_app/anagrafica/urls.py` — `path("skill-matrix/match/", …, name="skm_match_validazione")`.
- `django_app/anagrafica/templates/anagrafica/pages/skm_match_validazione.html` (nuovo) —
  design HUB (chips riepilogo, tabella con `datalist` asset, decisione da_validare/conferma/escludi).
- `django_app/anagrafica/tests_skillmatrix_seed.py` (nuovo) — 6 test (seed + view).

**Come si valida (nell'ambiente target):** `Anagrafica → Skill Matrix → Validazione
abbinamento macchine` (`/anagrafica/skill-matrix/match/`). «Sincronizza dagli asset»
popola/ricalcola il match sugli asset reali; per ogni macchina si imposta l'asset_tag
e si sceglie *Conferma* / *Escludi* / *Da validare*; «Salva» persiste su
`CompetenzaSkm.match_confermato`. Gli "esatto" arrivano già confermati.

**Il gate F2b resta chiuso** finché tutte le macchine non sono *confermate* o *escluse*
(`match_confermato=True`). La conferma in portale **sostituisce** l'edit manuale del CSV.

**Esito:** seed dev → 84 voci (42 macchine: 18 esatti/14 parziali/10 assenti, 18 confermati),
41 processi, 1 contatore. Test `anagrafica.tests_skillmatrix*` → **31 passed**. `check` pulito.

## F2a — Codici asset dall'ambiente target (export read-only + match offline)  ⛔ GATE attivo (2026-06-25)

> Richiesta utente: «prendiamo i codici degli asset dal server prod». Da una
> macchina di sviluppo NON ci si collega al DB di prod (serve `.env`/credenziali
> prod, è un confine di sicurezza). Gli asset (tag/nome/tipo) **non** sono dati
> personali → si "prendono i codici" con un export sola lettura, da rigiocare
> offline nel matcher.

**File toccati:**
- `django_app/anagrafica/management/commands/skm_export_assets.py` (nuovo) — export **sola lettura**
  dei soli metadati asset (`id, asset_tag, internal_number, name, asset_type`) in CSV.
- `django_app/anagrafica/management/commands/skm_asset_match_report.py` — opzione **`--assets-csv`**
  (match OFFLINE dal CSV, DB non letto) + fallback al catalogo impacchettato
  `skillmatrix_catalogo.CATALOGO_MOD187` quando manca il CSV in `docs/` (eseguibile anche in prod).
- `django_app/anagrafica/tests_skillmatrix_export.py` (nuovo) — 3 test.

**Flusso operativo (GDPR-safe, niente DB prod da dev):**
1. Su prod: `python manage.py skm_export_assets --settings=config.settings.prod`
   → `docs/skill-matrix/assets_export.csv` (solo codici asset, nessun dato personale).
2. Su dev: `python manage.py skm_asset_match_report --assets-csv <file>`
   → report prod-accurato, **senza** leggere il DB di prod.

Round-trip verificato: export 773 asset dev + match offline riproduce **identici** i conteggi
del run su DB (18 esatti/14 parziali/10 assenti su 42 macchine). Suite `tests_skillmatrix*` → **34 passed**.

In alternativa: lanciare lo specchietto «Sincronizza dagli asset» **direttamente su prod**
(legge gli asset live), oppure `skm_asset_match_report --settings=config.settings.prod` (modalità DB).

## F3 — Resolver bridge (read-only)  ✅ (2026-06-25)

**File toccati:**
- `django_app/anagrafica/services/skillmatrix_resolver.py` (nuovo) — sola lettura.
- `django_app/anagrafica/tests_skillmatrix_resolver.py` (nuovo) — 9 test.

**API esposta** (nessuna scrittura): `pool_abilitati(asset, livello_min=None, includi_riserva=None)`
→ `legacy_anagrafica_id` operativi (attiva+in_lista+livello≥soglia; CAR esclusi salvo
riserva); `livello_operatore(legacy_id, asset)`; `kpi_uomo_solo(asset)`;
`macchine_scoperte(reparto)`; `prontezza_squadra(reparto)`. `asset` accetta istanza o id.
Filtro soglia tradotto in `livello__in` (niente derivati in query). Universo macchine =
`CompetenzaSkm(tipo=macchina, asset risolto)`, reparto = `asset.reparto`.

**Punto d'aggancio Fase B:** `pool_abilitati`/`livello_operatore` alimenteranno l'overlay
disponibilità nel Gantt carichi macchina (chi può stare sulla macchina, a che livello)
senza che i carichi importino i modelli skill matrix.

**Esito:** `anagrafica.tests_skillmatrix_resolver` → **9 passed** (CAR esclusi, academy
inclusi, soglia, riserva, uomo-solo, copertura, prontezza, no-scrittura).

## F4 — Matrice macchina (UI) + tab  ✅ (2026-06-25)

**File toccati:**
- `django_app/anagrafica/views.py` — view `skill_matrix_macchina` (sola lettura).
- `django_app/anagrafica/templates/anagrafica/pages/skill_matrix_macchina.html` (nuovo).
- `django_app/anagrafica/urls.py` — `path("skill-matrix/", …, name="skill_matrix_macchina")`.

**Pagina** `/anagrafica/skill-matrix/`: matrice **persone × macchine** (colonne = macchine
MOD.187 con asset risolto, righe = persone con abilitazioni). Celle livello I/L/U/O
(colore per livello, etichette configurabili), marker `▲` sotto livello richiesto,
**tratteggio** = rivalutazione arretrata (non bloccante), barra blu = multivoce, cella
vuota = non in lista. **KPI** dal resolver F3 (prontezza squadra %, macchine scoperte,
rischio uomo-solo, continuità persa), filtro **reparto** (`asset.reparto`), **export CSV**.
Riusa il design HUB (`hr-shell`/`hr-pagehead`, navy/cyan) e la subnav del modulo.
**Tab gemella** "Processi qualificati" → rimanda alla `matrice_competenze` esistente
(non la riscrive). Nomi dall'anagrafica legacy **fail-safe** (sorgente assente → "ID n";
in test la sorgente legacy non esiste). Finché la baseline F2b non è importata la matrice
è **vuota**: la pagina mostra struttura + KPI + rimando alla validazione match (F2a).

## F7 (parziale) — Navigazione: voci di menu del modulo anagrafica  ✅ (2026-06-25)

**File toccati:**
- `django_app/anagrafica/migrations/0072_subnav_skill_matrix.py` (nuovo) — data migration.

La subnav di anagrafica è **data-driven** (`SubnavLinkAnagrafica`/`SubnavCategoriaAnagrafica`,
non `NavigationItem`). La migration `0072` semina — con lo stesso idioma di `0070`,
idempotente per `url_value`, voci **non di sistema** (riordinabili/nascondibili da
Impostazioni → Navigazione) — sotto il pilastro **Competenze**, gruppo **"Skill Matrix"**:
- **Abilitazioni macchina (MOD.187)** → `anagrafica:skill_matrix_macchina`
- **Validazione abbinamento macchine** → `anagrafica:skm_match_validazione`

**ACL canonico (completato 2026-06-26):** le 3 route sono ora governabili da
`/admin-portale/acl-canonico/`. `anagrafica/acl_bootstrap.py` registra (via
`bootstrap_nav_fn`, cache key → v3) i permessi canonici **`anagrafica.skillmatrix.view`**
e **`anagrafica.skillmatrix.manage`**, i `RoutePermissionBinding`
(matrice→view, validazione/refresh→manage) e i grant di default CREATE-ONLY
(admin/amministrazione/qualita/caporeparto). Le view non usano più `_check_hr_permission`
ma il nuovo helper **`_check_skm_permission(request, code)`** (`core.acl_v2.evaluate_permission_code_access`:
bypass superuser/admin legacy, altrimenti grant del ruolo) → ciò che si imposta in ACL
canonico governa davvero l'accesso, e in `ACL_STRICT_CANONICAL` (prod) il middleware applica
i binding (senza i quali le route sarebbero state **solo-superuser**).

**Test (F4+F7):** `anagrafica.tests_skillmatrix_ui` → **5 passed** (render vuoto, render con
abilitazione, export CSV, accesso negato, voci di menu seminate). Suite skill-matrix totale
**49 verdi**; `manage.py check` pulito; migration applicata su SQLite (dev).

## F2b — Importer baseline  ⛔ STOP: **ATTESA APPROVAZIONE SCRITTURA** (2026-06-25)

> Importer **costruito e testato**; eseguito solo in **dry-run** su fixtures sintetiche.
> NON eseguito `--apply` sui dati reali: serve prima la conferma del match (gate F2a)
> e l'ok esplicito alla scrittura baseline.

**File toccati:**
- `django_app/anagrafica/services/skillmatrix_importer.py` (nuovo) — logica import.
- `django_app/anagrafica/management/commands/import_skill_matrix.py` (nuovo) — comando.
- `django_app/anagrafica/tests_skillmatrix_importer.py` (nuovo) — 3 test.

**Comportamento** (`importa_skill_matrix`, comando `import_skill_matrix`):
- **dry-run di default**, scrive solo con `--apply`; CSV da `docs/anagrafica/skillmatrix/`.
- operatori risolti per **nome** → `legacy_anagrafica_id` (via `fetch_anagrafica_rows`,
  match "COGNOME NOME"/"NOME COGNOME"); non risolti/ambigui **riportati** (mai drop);
- chiama `sincronizza_catalogo()` poi usa SOLO le macchine con **match confermato**
  (`match_confermato` + `asset`); macchina referenziata senza match → **bloccata** e
  elencata (non si inventa l'asset);
- baseline (snapshot 2026-04-30) → `AbilitazioneMacchina` (`update_or_create`,
  CAR ⇒ `conteggiabile_nel_carico=False`, cella vuota = non in lista);
- **storico** append-only per ENTRAMBI gli snapshot (`get_or_create` per data, idempotente);
- "corsi attivati" → `SkmCorsiAttivati`; righe **processo** della matrice → contate e
  riportate (NON nello strato macchina, decisione F0 #4);
- verifica **coerenza** matrice vs `skm_storico_delta.csv`; tutto in transazione.

**Test:** `anagrafica.tests_skillmatrix_importer` → **3 passed** (dry-run pianifica senza
scrivere; `--apply` scrive abilitazioni+storico+contatore con CAR escluso dal carico;
idempotenza). Suite skill-matrix totale **52 verdi**.

### ⛔ STOP — cosa serve per `--apply` sui dati reali
1. Confermare i match competenza→asset nell'ambiente target (specchietto F2a, o report);
   le macchine non confermate restano **bloccate** dall'importer.
2. `python manage.py import_skill_matrix` (dry-run) nell'ambiente target → rivedere il
   piano (operatori risolti, abilitazioni, bloccate, processi saltati, coerenza storico).
3. Ok esplicito → `python manage.py import_skill_matrix --apply`.

## F5 — Continuità operativa (regola di sospensione)  ⛔ STOP: sorgente produzione NON cablata (2026-06-25)

**File toccati:**
- `django_app/anagrafica/services/skillmatrix_continuita.py` (nuovo) — sospensione/riattivazione.
- `django_app/anagrafica/management/commands/skm_continuita_sync.py` (nuovo) — `--dry-run`.
- `django_app/anagrafica/migrations/0073_seed_continuita_cndpt.py` (nuovo) — seed CND-PT.
- `django_app/anagrafica/tests_skillmatrix_continuita.py` (nuovo) — 6 test.

**Regola bloccante (MT CN 65 §3.7):** `applica_sospensioni()` calcola `ContinuitaOperativa.stato()`
e, su **persa**, **sospende** l'abilitazione collegata (scatto storico, nota con marcatore
`[continuita-persa]`); al recupero (mantenuta/in_scadenza) **riattiva** SOLO le abilitazioni
che erano state sospese per continuità (marcatore presente) — le sospensioni di altra origine
restano. Idempotente; `--dry-run` pianifica senza scrivere. È l'**unica regola bloccante**.
`riepilogo_continuita()` per i KPI. Seed catalogo: solo **CND-PT** (certo); saldatura ISO 9606
e cromatura restano **aperti** (da confermare in avvio).

### ⛔ STOP — sorgente di `ultima_esecuzione` (da approvare prima di cablare)
La data di ultima esecuzione **non** è inserita a mano: va letta dall'esecuzione reale di
produzione. Sorgenti candidate individuate nel repo (da validare, **non ancora cablate**):
- **avanzamento ordini di produzione** (`ordini_produzione` / avanzamento) — segnale "processo
  eseguito" ma da incrociare con l'operatore;
- **timbri** (registro timbri/firme/sigle) — presenza/operazione per persona, ma non sempre
  legato al *processo* CND-PT;
- eventuale log di esecuzione CND dedicato (da verificare con qualità).
Manca un segnale pulito **persona × processo × data**: serve decidere la fonte e la regola di
attribuzione **prima** di popolare `ContinuitaOperativa.ultima_esecuzione`. Fino ad allora la
regola di sospensione gira su dati assenti (no-op) ed è testata su fixtures.

**Test:** `anagrafica.tests_skillmatrix_continuita` → **6 passed** (persa→sospende, dry-run,
idempotenza, recupero→riattiva, no-riattiva-altre-origini, seed CND-PT). Suite skill-matrix **58 verdi**.

## F6 — Refresh semestrale (CAR)  ✅ (2026-06-25)

**File toccati:**
- `django_app/anagrafica/services/skillmatrix_refresh.py` (nuovo).
- `django_app/anagrafica/views.py` — view `skm_refresh`.
- `django_app/anagrafica/urls.py` — `path("skill-matrix/refresh/", …)`.
- `django_app/anagrafica/templates/anagrafica/pages/skm_refresh.html` (nuovo).
- `django_app/anagrafica/migrations/0074_subnav_skill_matrix_refresh.py` (nuovo) — voce di menu.
- `django_app/anagrafica/tests_skillmatrix_refresh.py` (nuovo) — 12 test.
- `django_app/anagrafica/tests_skillmatrix.py` — fix collisione `CND-PT` col seed F5 (→ `CND-PT-TEST`).

**Pagina** `/anagrafica/skill-matrix/refresh/` (guard `_check_hr_permission`): selezione
reparto → **① rivaluta** le abilitazioni in lista (conferma/aggiorna livello, oppure rimuovi)
e **② aggiunta manuale** (legacy id + macchina + livello). Servizio `skillmatrix_refresh`:
`apri_campagna` (CampagnaRefresh, idempotente, è solo l'innesco), `abilitazioni_reparto`,
`applica_refresh` (scrive scatti storico **fonte refresh** e sposta `prossima_revisione` di
`periodicita_refresh_mesi`; `--dry-run` via `apply=False`), `aggiungi_abilitazione`,
`arretrati_reparto`. Arretrato (revisione scaduta) **visibile, non bloccante**. Merito = CAR
(lo scoping stretto per reparto-del-CAR è una rifinitura ACL successiva). Voce di menu
"Refresh semestrale" nel gruppo Skill Matrix (migration `0074`).

**Test:** `anagrafica.tests_skillmatrix_refresh` → **12 passed** (campagna idempotente,
abilitazioni reparto, conferma/modifica/rimuovi, aggiunta manuale, livello invalido, dry-run,
view GET/POST, accesso negato, voce menu). Suite skill-matrix totale **70 verdi**.

## F8 — Hardening test  ✅ (2026-06-26)

- Suite Skill Matrix completa **70 verdi** (9 moduli: modelli, match, seed, export,
  resolver, UI, importer, continuità, refresh).
- `makemigrations anagrafica --check` → **No changes detected** (nessun model change
  pendente; migrazioni 0071–0074 consistenti).
- `manage.py check` (test) → **0 issues**.
- **Compatibilità preesistente:** lo strato è **additivo**. Nessuna modifica ai modelli/
  view esistenti tranne (a) la guardia *fail-safe* su `fetch_anagrafica_rows` nelle nuove
  view e (b) il rename `CND-PT`→`CND-PT-TEST` in un test modello (collisione col seed F5).
  La suite **completa** di `anagrafica` include test che dipendono dalla **sorgente legacy
  SQL** (`fetch_anagrafica_rows` → colonna `ruolo`): falliscono su SQLite **per ambiente**,
  non per queste modifiche → vanno eseguiti nell'ambiente di test con SQL Server.

## F9 — Chiusura  ✅ (2026-06-26)

**Costruito (commit `26de68f`→`7c4a19d` sul branch `feature/skill-matrix-mod187`, no push):**
modello dati (F1), report match asset + specchietto di validazione in portale + export/match
offline (F2a), importer baseline dry-run (F2b, gated), resolver read-only (F3), matrice
persone×macchine UI (F4), continuità operativa con sospensione automatica (F5, sorgente
gated), refresh semestrale CAR (F6), voci di menu Anagrafica→Competenze→Skill Matrix (F7).
**70 test**, tutto SQL-Server-safe, dipendente sempre via `legacy_anagrafica_id`.

**Pagine:** `/anagrafica/skill-matrix/` (matrice), `…/match/` (validazione F2a),
`…/refresh/` (refresh CAR). **Comandi:** `skm_seed_catalogo`, `skm_asset_match_report`,
`skm_export_assets`, `import_skill_matrix`, `skm_continuita_sync`.

**⛔ Gate ancora aperti (azioni umane su prod, non codice):**
1. **F2b `--apply`** — import baseline: prima confermare il match competenza→asset
   nell'ambiente target (specchietto F2a; mapping prod già derivato), poi `import_skill_matrix`
   (dry-run → `--apply`).
2. **F5 sorgente continuità** — cablare `ultima_esecuzione` alla produzione reale dopo aver
   scelto/approvato la fonte (avanzamento ordini / timbri / log CND).

**TODO aperti (sessione CAR / avvio):** regola multivoce (default `MIN`), voci per tipo
macchina (catalogo vuoto), elenco processi critici (CND-PT certo; saldatura/cromatura),
mappatura sotto-aree→CAR padre, visibilità matrice (scoping CAR/qualità), scoping ACL CAR
sul refresh, link processo→`TipoQualifica` in continuità.

**Follow-up a merge:** aggiornare `README.md` (catalogo moduli / sezione anagrafica) con le
pagine Skill Matrix — rimandato perché `README.md` è in editing parallelo da altre chat.

## F10 — Scadenzario abilitazioni + avvio refresh HR→CAR  ✅ (2026-07-03)

Il refresh diventa una **scadenza gestibile** con un posto esplicito. Nuova pagina
**Scadenzario abilitazioni** (`/anagrafica/skill-matrix/scadenzario/`, gated
`anagrafica.skillmatrix.manage`): stato del refresh **per reparto** (prossima revisione,
arretrati non bloccanti, stato campagna), KPI, filtro stato, export CSV, drill-down alla
pagina Refresh F6. **HR "dà il via"**: il bottone «Avvia refresh» apre la `CampagnaRefresh`
(idempotente) e — solo alla prima apertura — **avvisa il CAR** (notifica in-app
`core.notifiche` + email best-effort `core.email_utils.send_hub_mail`, fail-safe: un errore
non annulla l'apertura); la campagna aperta compare anche nella home **«Cose da gestire»**
del CAR (sezione in `dashboard/views_mie_attivita.py`, helper read-only
`campagne_da_gestire`). Il **merito** della rivalutazione resta al CAR (pagina Refresh).

Additivo, lettura **live** di `AbilitazioneMacchina.prossima_revisione` (nessuna cache),
Skill Matrix read-only verso gli altri moduli. Nuovo campo config
**`preavviso_refresh_giorni`** (default 60, in `SkillMatrixConfig` + form + Impostazioni)
= soglia «in arrivo». Binding ACL route → `manage` (bootstrap cache **v4→v5**); voce subnav
«Scadenzario abilitazioni» (migration **0076**). Servizio esteso in
`services/skillmatrix_refresh.py` (`scadenzario_reparti`, `avvia_refresh`, `_risolvi_car`,
`_notifica_car`, `campagne_da_gestire`; `apri_campagna` refactor con flag `created`).

**Test:** nuovo `tests_skillmatrix_scadenzario.py` (15) — config, aggregazione/ordinamento,
avvia_refresh idempotente + notifica una-sola-volta, risoluzione CAR, campagne_da_gestire,
view (render/CSV/POST/accesso negato), binding ACL, voce menu, helper Cose da gestire.
Suite skill-matrix **85 verdi** (70 + 15); `makemigrations --check` pulito; `check` pulito.
Spec/piano: `docs/anagrafica/skillmatrix/SPEC_…` / `PLAN_scadenzario_refresh_abilitazioni.md`.

## Stato fasi
- [x] F0 Discovery
- [x] F1 Modelli + migrazione + test modello (12 verdi)
- [x] F2a Asset-match report — 18 esatti/14 parziali/10 assenti (13 test) — **GATE attivo**
- [x] F2a-UI Specchietto validazione in portale (`/anagrafica/skill-matrix/match/`) — 31 test totali — **GATE attivo**
- [~] F2b Importer baseline — **costruito + dry-run validato (3 test)**; STOP attivo per `--apply` (conferma match + approvazione)
- [x] F3 Resolver bridge read-only (9 test) — punto d'aggancio Fase B carichi macchina
- [x] F4 Matrice macchina UI + tab (`/anagrafica/skill-matrix/`, 5 test) — vuota finché F2b non importa la baseline
- [~] F5 Continuità operativa — **regola sospensione + seed CND-PT fatti (6 test)**; STOP: sorgente produzione `ultima_esecuzione` da approvare/cablare
- [x] F6 Refresh semestrale (CAR) — pagina `/anagrafica/skill-matrix/refresh/` + servizio (12 test)
- [x] F7 ACL + navigazione — voci di menu (migration 0072/0074) **+ ACL canonico** (permessi `anagrafica.skillmatrix.view/.manage`, binding route, grant di default → governabili in /admin-portale/acl-canonico/)
- [x] F8 Hardening test — suite skill-matrix **70 verdi**, `makemigrations --check` pulito, `check` pulito
- [x] F9 Chiusura — BUILD_LOG finalizzato; gate residui (F2b `--apply`, sorgente F5) e README a merge
- [x] F10 Scadenzario abilitazioni + avvio refresh HR→CAR (`/anagrafica/skill-matrix/scadenzario/`, notifica+email CAR, Cose da gestire, config `preavviso_refresh_giorni`, ACL v5, subnav 0076) — 15 test

## TODO aperti (da confermare in sessione CAR / avvio)
- Regola totale multivoce (default `MIN`).
- Voci per tipo macchina (catalogo vuoto, da popolare coi CAR).
- Elenco processi critici con continuità (CND-PT attivo; saldatura/cromatura aperti).
- Mappatura sotto-aree → CAR padre (alcune righe operatori senza CAR proprio).
- Visibilità matrice (default: CAR vede il proprio reparto; qualità vede tutto).
- Sorgente "ultima_esecuzione" continuità (F5, da individuare e approvare).
