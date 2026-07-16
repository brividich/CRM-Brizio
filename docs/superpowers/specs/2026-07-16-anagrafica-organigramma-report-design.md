# Anagrafica — Organigramma ad albero & Report dipendenti canonico — Design (Stream 2)

> Spec di riferimento per il piano `docs/superpowers/plans/2026-07-16-anagrafica-organigramma-report.md`.
> Ambito: `django_app/anagrafica`. Nessuna nuova astrazione trasversale: si estendono i pattern SSR/HTMX esistenti e il service `reparto_canonico`.

## Goal

Chiudere tre voci della punch-list `docs/ANAGRAFICA - PERSONE.md` (sezione «Organigramma / Report dipendenti»):

1. **Organigramma — vista "ad albero" (gerarchia)**, e la stessa vista ad albero **per singola certificazione** (chi la possiede / copertura ad albero). *Vincolo di dominio non negoziabile:* la gerarchia è **tra RUOLI, mai tra persone**. Le persone compaiono solo come titolari (foglie) appese al proprio ruolo.
2. **Report dipendenti — rimuovere il "reparto legacy"** (colonna/filtro sul testo libero `anagrafica_dipendenti.reparto`) e usare la **catena canonica** `dipendente → area_aziendale (FK) → reparto (FK)`.
3. **Caporeparto = responsabile dell'AREA AZIENDALE quando differisce** dal caporeparto del reparto. Correggere la logica di risoluzione del responsabile.

## Architecture

### Stato attuale (fatti verificati nel codice)

- **Organigramma "a griglia"** — `anagrafica/views.py::organigramma` (riga 13330), template `anagrafica/templates/anagrafica/pages/organigramma.html`, route `organigramma/` (`urls.py` riga 238). Rende una card per `Reparto`, con chip delle `aree_aziendali`, il capo (`rep.caporeparto_legacy_id`, riga 13380 in `_blocco_reparto`) e i membri. Il reparto di ogni dipendente è risolto dal service canonico `anagrafica/services/reparto_canonico.py` (`build_reparto_canonico_map`, `build_area_canonica_map`, `resolve_reparto_for_row`) con fallback al testo legacy. Export lista piatta in `anagrafica/exports_persone.py` (`key="organigramma"`, riga 901).
- **Gerarchia dei RUOLI già modellata** — `anagrafica/models.py::RuoloOperativo` (riga 316) ha il self-FK **`riporta_a`** (riga 334, `related_name="riporti"`) con help-text *«Relazione tra RUOLI, non tra persone»* e il campo **`certificazione_competenza`** (riga 327). Le assegnazioni ruolo↔persona sono in `DipendenteRuoloOperativo` (riga 355, `legacy_anagrafica_id` + FK `ruolo`). Il ponte legacy↔Django e il roster per ruolo sono già centralizzati in `core/operational_roles.py` (`get_anagrafica_ids_for_role`, `get_active_roles`).
- **Certificazioni/qualifiche possedute** — catalogo `anagrafica/models.py::TipoQualifica` (riga 506); possesso per persona in `DipendenteQualifica` (riga 550, `legacy_anagrafica_id` + FK `tipo` + `data_scadenza`). È la fonte canonica di "chi possiede una certificazione" (con validità/scadenza).
- **Report dipendenti** — `anagrafica/views.py::dipendenti_report` (riga 5197), template `anagrafica/pages/dipendenti_report.html`, route `dipendenti/report/` (`urls.py` riga 143). Oggi:
  - filtra sul reparto **legacy testo** (`row.get("reparto")`, righe 5226-5230) e costruisce `reparti_list` dal testo legacy (riga 5314);
  - il CSV scrive la colonna **"Reparto"** dal testo legacy (`row.get("reparto")`, riga 5302);
  - il template mostra **due** colonne: `Reparto (legacy)` (riga 153/174, `row.reparto`) e `Reparto (catalogo)` (riga 154/175, `az.area` — anch'esso **testo**, non la FK canonica); il filtro "Reparto (catalogo)" (righe 98-102) usa `az.area` distinct.
- **Risoluzione caporeparto** — `Reparto.caporeparto_legacy_id` (models riga 762) e `AreaAziendale.responsabile_legacy_id` (models riga 802, FK `reparto`). La scrittura del denormalizzato avviene in `anagrafica/views.py::_sync_aziendale_from_reparto` (riga 5635): oggi imposta `capo_id = rep.caporeparto_legacy_id` (riga 5653) **ignorando** il responsabile dell'area. Altri consumatori del caporeparto: `organigramma._blocco_reparto` (13380) e `anagrafica/services/onboarding.py::_caporeparto_emails` (riga 243, risolve da `Reparto`).

### Interventi proposti (minimizzando la superficie su `views.py`/`urls.py`)

Per il **coordinamento** con gli stream 1 e 3 (che toccano gli stessi `views.py`/`urls.py`), la logica nuova vive in **service module dedicati** e in **una view + un template nuovi**; su `views.py`/`urls.py` si toccano solo hunk piccoli e localizzati.

**A. Responsabile effettivo (Intervento 3) — fonte unica.**
Estendere `anagrafica/services/reparto_canonico.py` con:
- `resolve_responsabile_effettivo(*, area, reparto) -> int | None`: ritorna `area.responsabile_legacy_id` se valorizzato, altrimenti `reparto.caporeparto_legacy_id` (fallback), altrimenti `None`. Regola: *l'area vince sul reparto quando differisce*.
- `build_responsabile_effettivo_map(legacy_ids) -> dict[int, int]`: per-dipendente, riusa `build_area_canonica_map` (area → reparto via `select_related`) e applica `resolve_responsabile_effettivo`.

Consumatori aggiornati (hunk minimi):
- `_sync_aziendale_from_reparto` (views.py 5635): il denormalizzato `az.caporeparto_legacy_id` diventa il **responsabile effettivo** (area.responsabile se presente, altrimenti capo reparto). Nessun cambio di firma.
- `onboarding._caporeparto_emails`: risolve l'email del responsabile effettivo. *(Task separato, opzionale ma incluso per coerenza notifiche.)*

**B. Report dipendenti canonico (Intervento 2).**
In `dipendenti_report` (views.py 5197):
- arricchire le righe con `reparto_canonico.enrich_rows_reparto_canonico` (già esistente: sovrascrive `row["reparto"]` col nome del reparto canonico e imposta `row["area_aziendale_nome"]`);
- sostituire il filtro sul testo legacy con un filtro sul **reparto canonico** (nome del `Reparto` dopo l'enrich) e alimentare `reparti_list` dal **catalogo `Reparto`** (non dal testo legacy);
- CSV: la colonna "Reparto" attinge al reparto canonico; aggiungere/rinominare "Area aziendale" da `row["area_aziendale_nome"]` (rimuovere il testo `az.area`).
Nel template `dipendenti_report.html`: **rimuovere la colonna "Reparto (legacy)"** (righe 153/174), tenere una sola colonna "Reparto" canonica + "Area aziendale" (`row.area_aziendale_nome`); il selettore filtro usa i nomi del catalogo.

**C. Organigramma ad albero (Intervento 1).**
Nuovo service `anagrafica/services/organigramma_albero.py` (builder puri, testabili senza HTTP):
- `build_ruolo_albero() -> list[nodo]`: albero dei `RuoloOperativo` attivi via `riporta_a` (radici = `riporta_a IS NULL`); ogni nodo = `{ruolo, titolari: [ {legacy_id, nome} ], figli: [...] }`. I titolari vengono da `DipendenteRuoloOperativo`/`core.operational_roles.get_anagrafica_ids_for_role`, con nomi risolti da `fetch_anagrafica_rows`. Difesa anti-ciclo su `riporta_a`. *Le persone non hanno mai figli: sono foglie sotto il ruolo.*
- `build_certificazione_copertura(tipo_qualifica_id) -> list[nodo]`: stesso albero dei ruoli, con overlay di copertura per ogni titolare — stato `posseduta_valida` / `scaduta` / `mancante` calcolato da `DipendenteQualifica` (filtro `tipo_id`, `data_scadenza` vs oggi). Aggrega per nodo `n_copertura`/`n_totale`.

Nuova view `organigramma_albero` (route `organigramma/albero/`) + template `pages/organigramma_albero.html`:
- default = albero dei ruoli; con `?certificazione=<TipoQualifica.pk>` = overlay copertura;
- selettore certificazione (SSR, GET; niente JS obbligatorio — HTMX solo come miglioria, coerente con l'organigramma esistente);
- link di **toggle** reciproco tra `organigramma` (griglia) e `organigramma_albero` (albero), aggiunto nell'header di entrambe.
- Il "capo" mostrato resta il **responsabile effettivo** (A) dove pertinente, ma nell'albero dei ruoli la gerarchia è quella dei ruoli, non dei capireparto.

### Vincolo di dominio (ribadito nel codice e nei test)

- La gerarchia dell'albero è **esclusivamente** `RuoloOperativo.riporta_a` (ruolo→ruolo). Non esiste e non va introdotta alcuna gerarchia persona→persona. Una persona appare N volte se ricopre N ruoli; è sempre foglia.
- La certificazione mostra **copertura** (chi la possiede, con validità), non idoneità operativa: nessuna inferenza di idoneità dai dati (coerente con i guardrail privacy/AI del progetto).

## Tech Stack

Django 5.2, Python 3.11+, SSR (template Django + CSS custom, HTMX opzionale), test `django.test.TestCase` + `RequestFactory`/`Client`. DB prod SQL Server (ORM SQL-Server-safe: niente window function); test SQLite per-PID sotto `.tmp_tests`.

## Non-goals

- Nessun redesign dell'organigramma a griglia esistente (resta la vista di default reparto-centrica).
- Nessuna migrazione di schema: tutti i campi necessari (`riporta_a`, `certificazione_competenza`, `responsabile_legacy_id`, `DipendenteQualifica`) esistono già.
- Nessun version bump.
- Nessun intervento sulla punch-list Formazione/Compliance/Assenze/altri moduli (stream diversi).

## Coordinamento (rischio conflitti)

`anagrafica/views.py` e `anagrafica/urls.py` sono condivisi con gli stream 1 e 3, in parallelo. Mitigazioni:
- logica in **file nuovi** (`services/organigramma_albero.py`, estensioni additive in `services/reparto_canonico.py`, template nuovi, test nuovi);
- su `views.py`: **una sola** nuova funzione (`organigramma_albero`) + hunk piccoli e ben delimitati in `dipendenti_report`, `_sync_aziendale_from_reparto`, `_blocco_reparto`;
- su `urls.py`: **una sola** riga aggiunta (`organigramma/albero/`);
- staging esplicito per-file, mai `git add -A`; il worktree dedicato isola il branch.
