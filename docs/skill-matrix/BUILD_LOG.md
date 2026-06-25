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

## Stato fasi
- [x] F0 Discovery
- [x] F1 Modelli + migrazione + test modello (12 verdi)
- [x] F2a Asset-match report — 18 esatti/14 parziali/10 assenti (13 test) — **GATE attivo**
- [ ] F2b Importer baseline (STOP approvazione scrittura)
- [ ] F3 Resolver bridge read-only
- [ ] F4 Matrice macchina UI + tab
- [ ] F5 Continuità operativa (STOP approvazione cablaggio produzione)
- [ ] F6 Refresh semestrale (CAR)
- [ ] F7 ACL + navigazione
- [ ] F8 Hardening test
- [ ] F9 Chiusura

## TODO aperti (da confermare in sessione CAR / avvio)
- Regola totale multivoce (default `MIN`).
- Voci per tipo macchina (catalogo vuoto, da popolare coi CAR).
- Elenco processi critici con continuità (CND-PT attivo; saldatura/cromatura aperti).
- Mappatura sotto-aree → CAR padre (alcune righe operatori senza CAR proprio).
- Visibilità matrice (default: CAR vede il proprio reparto; qualità vede tutto).
- Sorgente "ultima_esecuzione" continuità (F5, da individuare e approvare).
