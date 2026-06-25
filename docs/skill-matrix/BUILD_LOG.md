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

## Stato fasi
- [x] F0 Discovery
- [x] F1 Modelli + migrazione + test modello (12 verdi)
- [ ] F2a Asset-match report (GATE: ATTESA CONFERMA MATCH ASSET)
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
