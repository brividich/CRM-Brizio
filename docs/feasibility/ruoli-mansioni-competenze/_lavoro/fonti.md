# Fonti: studi e analisi precedenti

Inventario al commit `784cbf3ae` (21/11/2026). Raccolto con una ricerca su `docs/`, guide, `CHANGELOG.md` e storico git;
i punti segnati «verificato» sono stati ricontrollati a mano, gli altri vengono dalla ricerca e sono da ritenere
attendibili ma non ricontrollati riga per riga.

**Nota di metodo.** Il commit `93340a676` (07/10/2026, «rimuovi 115 documenti superati» — verificato) ha tolto dal
repository gran parte degli studi del dominio. Si leggono ancora con `git show 93340a676^:<percorso>`.

## A. Documenti presenti

| # | Percorso | Data | Tema | Stato |
| --- | --- | --- | --- | --- |
| A1 | `docs/PROPOSTA_RUOLI_SGI.md` | 29/09/2026 | Più incarichi per persona, perimetri, ruoli → gruppi ACL | Parziale |
| A2 | `docs/ai/PERMESSI_RUOLI.md` | 12/10 → 30/10/2026 | Sistema unico dei permessi, organigramma → ruoli del portale | Implementato |
| A3 | `docs/superpowers/specs/2026-10-15-mansionario-ruolo-mansione-competenze-rischio-design.md` | 15/10/2026 | Mansionario: ruolo → mansione → competenze, mansione di rischio, decisioni D1-D18 (verificato) | Implementato (fasi 1-4), parziale (fasi 5-6, report) |
| A4 | `docs/anagrafica/formazione/PROPOSTA_FATTORI_RISCHIO.md` | 23/05/2026 | Fattori di rischio, categorie corso, scadenze dai fattori | Implementato, salvo la validità ricavata dai fattori (mai fatta) |
| A5 | `docs/anagrafica/formazione/MAPPING_IMPORT_GESTIONALE.md` | 22/05/2026 | Import dal gestionale sui modelli della formazione | Implementato; campi aggiuntivi mai fatti |
| A6 | `docs/moduli/anagrafica.md` | 18/11/2026 | Scheda del modulo: registro di tutte le funzioni | Vivo |
| A7 | `docs/anagrafica/ROADMAP_QUALIFICHE.md` | 19/06/2026 | Mini-modulo qualifiche | Implementato |
| A8 | `docs/anagrafica/ANAGRAFICA_HR_DIPENDENTI.md` | 20/05/2026 | Sprint HR; storico mansione e ruolo | Implementato |
| A9 | `docs/ai/16_AFFIDABILITA_E_PRODOTTO_MODULARE.md` | 25/10/2026 | Regole rigide nel codice (scala dei livelli, mansione per nome) | Analisi, valida |
| A10 | `docs/audit/VERIFICA_PROMPT_01-08_requisiti.md` (+ versione 11/10) | 11/10/2026 | Verifica dei prompt P04 mansioni di rischio/cambio mansione, P05 e-learning, P07 timbri | Verifica, non proposta |
| A11 | `docs/ai/11_FEATURE_BACKLOG.md` | 27/10/2026 | Backlog HR H1-H9 | Vivo |
| A12 | `docs/ai/PIANO_ACL_FASE2_DISMISSIONE_LEGACY.md` e checklist ACL | dal 04/06/2026 | ACL v2 in generale | Nulla di specifico sulle mansioni |
| A13 | Guide nel portale (`django_app/core/guide_moduli/contenuti/anagrafica.py`, guide formazione) | vive | Descrivono il già fatto | — |
| A14 | `CHANGELOG.md` | — | Decisioni D1-D10 della formazione; «analisi del modulo HR applicata» | — |

## B. Documenti rimossi il 07/10/2026 (recuperabili dallo storico)

| # | Percorso | Data | Tema | Stato |
| --- | --- | --- | --- | --- |
| B1 | `docs/anagrafica/formazione/BOZZA_MODULO_FORMAZIONE.md` | 22/05/2026 | Progetto del modulo Formazione | Implementato |
| B2 | `docs/anagrafica/formazione/TODO_FORMAZIONE_PROSECUZIONE.md` | 23/05/2026 | Decisioni D1-D10 «definitive» | Implementato; **D9 superata** (la scadenza non è più ricalcolata solo a comando) |
| B3 | `MIGLIORAMENTI_FORMAZIONE.md` | 13/07/2026 | **Analisi di miglioramento del modulo Formazione** — riguarda **solo l'e-learning** | Implementato (P0, P1); P2 non verificato |
| B4 | `docs/anagrafica/skillmatrix/BUILD_SPEC_skill_matrix.md` | 28/06/2026 | Specifica Skill Matrix MOD.187 | Implementato; voci per tipo macchina e regola «minimo» **superate** da D16-D17 |
| B5 | `docs/anagrafica/skillmatrix/SPEC_`/`PLAN_scadenzario_refresh_abilitazioni.md` | 03/07/2026 | Scadenzario abilitazioni, avvio del refresh | Implementato |
| B6 | `docs/skill-matrix/BUILD_LOG.md` | 25/06-03/07/2026 | Diario di costruzione; ancoraggio ad `assets.Asset` | Implementato |
| B7 | `docs/mod128/ANALISI_IMPLEMENTAZIONE_MOD128.md` | 06/07/2026 | MOD.128: modello dati, timbri, decisioni D1-D9 | Implementato; ruoli come booleani **superati** da `RuoloProcesso` |
| B8 | spec «mansione di rischio A1» | 22/07/2026 | Esposizione al rischio sul singolo dipendente | Implementato |
| B9 | `remediation-plan.md` | 06/08/2026 | 22 punti Anagrafica/DPI/Asset | Non ricontrollato |
| B10 | `docs/superpowers/plans/2026-07-15-piano-miglioramento-moduli.md` | 15/07/2026 | Catalogo ruoli unico, gerarchia «riporta a» | Implementato |
| B11 | spec interfaccia Formazione | 16/07/2026 | Chip «Processi qualificati», ruoli in linea | Implementato |
| B12 | spec Recruiting MOD.05-01 | 22/07/2026 | Selezione dei candidati di assunzione (altro dominio) | Implementato |
| B13 | spec visite e sorveglianza sanitaria | 15/07-25/08/2026 | Candidati alle visite, lettura dei referti | Implementato |

## C. Non trovati

- La **«versione unificata»** dell'analisi di miglioramento della Formazione: non esiste né nell'albero né nello storico.
- Il documento sorgente dell'«analisi del modulo HR» applicata il 16/10/2026.
- Qualunque precedente su **MOD.053, RAM, Sessione Formativa SF-AAAA, mansioni potenziali, P/A/C come modalità**:
  la richiesta della Qualità è nuova su tutti questi punti.
- MT CN 06, MT CN 08, MT CN 65, MOD.187 originale: citati dal codice, non presenti nel repository.
- La cartella `md upgrade moduli/` (prompt 01-08) non è tracciata: è solo nel checkout condiviso.

## D. Tappe principali (git)

| Data | Commit | Tappa |
| --- | --- | --- |
| 27/05/2026 | `1f94b4e79` | Modulo Formazione, fattori di rischio |
| 18/06/2026 | `2b766ad8d` | Selezione candidati ai corsi (`training_eligibility`) |
| 25-26/06/2026 | `26de68f7b` … `b32e0d841` | Skill Matrix MOD.187 |
| 07/07/2026 | `d4a54367c` | MOD.128 |
| 15/07/2026 | `43eebdb5f` | Catalogo ruoli unico |
| 24/07/2026 | `da7c75e5f` | Blocco I→L con corso qualificante |
| 26/08/2026 | `2994fd37e` | Ambiti dei ruoli |
| 07/10/2026 | `6186e2a24` | **Motore unico requisiti/scadenze**, cambio mansione |
| 12/10/2026 | `55dd0da43` | Formazione d'aula, integrità, MOD.040 |
| 15/10/2026 | `e7b48b679` … `5fb71477f` | Mansionario fasi 1-6 |
| 21/10/2026 | — | Struttura della Qualità «MEGA SKILL MATRIX v8» |
| 23/10/2026 | `aa3f5d6b2` | Catalogo unico competenze, storico valutazioni |
| 28/10/2026 | `f7368a6d5`, `d52d4a503` | Livelli ricalcolati in automatico; mansione solo a chi ha il suo ruolo (verificato) |
| 13/11/2026 | `edafd499e` | MOD.128: ruoli di processo, ponte verso il Mansionario |
