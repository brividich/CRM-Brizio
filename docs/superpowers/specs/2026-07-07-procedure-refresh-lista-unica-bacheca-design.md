# Procedure Refresh · Lista unica documenti + sync che segnala + Bacheca — Design

**Data:** 2026-07-07
**Modulo:** `procedure_refresh` (+ tocchi a `dashboard`)
**Stato:** approvato (brainstorming) — pronto per il piano di implementazione

## Contesto e problema

Dopo la v2 (`docs/superpowers/specs/2026-07-06-procedure-refresh-v2-design.md`) la lista
documenti è stata divisa in due tab **mutuamente esclusivi** — «Presa visione» vs
«Corpus AI» — sul flag `requires_acknowledgement`. Questo ha creato confusione:
i documenti importati dalla share SGI (nati `requires_acknowledgement=False`)
finivano solo in «Corpus AI» e **non erano selezionabili nelle campagne**.

**Diagnosi:** i due concetti sono **già ortogonali nel dato**:

- indicizzazione AI → guarda `ProcedureDocument.escludi_dal_rag` (default: incluso) + deny-list keyword;
- presa visione → guarda `ProcedureDocument.requires_acknowledgement`.

Un documento **può e deve** stare in entrambi. Era la **UI** a mentire, non il modello.
Il flag `requires_acknowledgement` non deve gattare il picker: la scelta di quali
documenti mettere in una campagna si fa **al momento della campagna**.

Requisito ISO 9001/EN 9100 (§7.5.3, controllo informazioni documentate) preservato:
disponibilità della revisione corrente, prevenzione uso di documenti obsoleti,
tracciabilità dei cambiamenti.

## Decisioni utente (brainstorming 2026-07-07)

1. **Lista unica condivisa**, non due tab esclusivi. Il flag presa-visione resta solo
   come **marcatore/badge** informativo (alimenta il report gap); il picker mostra tutti.
2. **Sync notturno**: se la revisione sulla share è cambiata, **aggiorna** anche i
   documenti in presa visione e **rimane segnalata come nuova rev**, catalogata a parte;
   funzionalmente non cambia nulla; **tenere un log** dei cambiamenti.
3. **Bacheca**: i documenti procedura devono essere **accessibili dentro la Bacheca
   esistente** («Documenti & Collegamenti»).
4. **Visibilità Bacheca**: tutti i dipendenti autenticati, **esclusi i sensibili**
   (stesso perimetro del RAG: `escludi_dal_rag` o deny-list keyword).

## Design

### Parte 1 — Lista unica + picker aperto

- **`document_list`**: una sola lista (niente tab esclusivi pv/rag). Per riga, badge
  **indipendenti**: `AI` (se non `escludi_dal_rag`), `Presa visione` (se
  `requires_acknowledgement`). Filtri come chip **opzionali** (tutti / solo PV / solo AI /
  sensibili), default **tutti**. Ricerca `?q=` invariata.
- **Picker campagna** (`campaign_detail.available_revisions`): mostra **tutte** le
  revisioni correnti dei documenti **attivi**, non più filtrate su
  `requires_acknowledgement`. Aggiunta **casella di ricerca client-side** (sono centinaia).
- **`requires_acknowledgement`**: da gate → **marcatore**. Alimenta il report
  «documenti soggetti a presa visione non ancora coperti da una campagna attiva».
- **`document_toggle_ack`** (già presente): resta ma **relabel** — marca/smarca il badge
  presa-visione (non abilita più nulla nel picker). Copy aggiornata, niente più
  conferma «non selezionabile nelle campagne».

### Parte 2 — Sync aggiorna + segnala + logga

- **`filter_auto_safe`** allentato: oltre a documenti nuovi e «import children», ammette
  anche l'**aggiornamento di revisione** (share rev > DB current rev) sui documenti
  gestiti / in presa visione. Resta escluso solo il rischio-**nome** (fallback /
  codici disambiguati): mai auto-scrittura su nomi non riconosciuti.
- Aggiornare = `upsert_candidate` crea la nuova revisione corrente. **Non tocca**
  assegnazioni/campagne (puntano alla vecchia revisione PK) → funzionalità invariata.
- **`SgiSyncLog`** (nuovo modello append-only): una riga per cambiamento con
  `run_id`/`ts`, `azione` ∈ {NUOVO_DOC, NUOVA_REVISIONE, DOC_SPARITO}, `document_code`,
  `revision_old`, `revision_new`, `note`, `origine` ∈ {AUTO, MANUALE}. Pagina admin
  **«Log sincronizzazioni SGI»** (`/procedure-refresh/admin/sync-log/`, gate `_can_manage`).
  Scritto sia da `run_sgi_auto_sync` sia da `sgi_sync_now`.
- **Segnalazione «nuova rev»**: badge `⟳ nuova Rev.X (sync gg/mm)` nella lista documenti,
  derivato dall'ultima riga `SgiSyncLog` NUOVA_REVISIONE per quel documento **negli ultimi
  N giorni** (default 30, `PROCEDURE_REFRESH_NUOVA_REV_BADGE_GIORNI`): così invecchia da
  solo senza bisogno di uno «spegnimento» esplicito. Informativo, **nessuna macchina a
  stati** (decisione utente).

### Parte 3 — Documenti nella Bacheca

- **Categoria virtuale «Procedure SGI»** iniettata nell'output della Bacheca (home +
  `/bacheca/`), costruita **al volo** dai `ProcedureDocument` (revisione corrente, attivi),
  **non** come righe `HubLink` (niente duplicazione/drift). Builder
  `procedure_refresh.bacheca.build_procedure_group(legacy_role_id, is_admin, preview_limit)`
  che ritorna la stessa forma-dict di `visible_bacheca` (`{category, items, total, more}`),
  chiamato dalle view dashboard (`views_home_portale`, `views_bacheca`) → confine pulito,
  `core/hub_bacheca.py` resta indipendente da `procedure_refresh`.
- **Visibilità**: tutti gli autenticati, **esclusi i sensibili** = `escludi_dal_rag=True`
  o deny-list keyword. Riuso di un helper condiviso `documento_e_sensibile(doc)` che
  incapsula lo stesso criterio del RAG (patterns da settings + flag).
- **Apertura** (`document_open(rev_pk)`, login): SharePoint → `redirect(source_url)`;
  file server → **stream del PDF** letto lato server **solo se** il path corrisponde alla
  `source_path` di una revisione nota **e** risolve sotto la root SGI consentita
  (riuso del pattern `_sgi_safe_pdf_path`: whitelist DB + root, blocco path traversal).
  Se sensibile → 404. Così anche i documenti file-server diventano apribili dal browser
  (oggi mostrano solo il percorso UNC come testo).

## Confini e unità

- `procedure_refresh/bacheca.py` — builder gruppo virtuale + criterio sensibilità
  (funzioni pure/testabili; dipende solo dai modelli).
- `procedure_refresh/services/sgi_sync_log.py` (o helper in `tasks.py`) — scrittura log.
- `document_open` — unica porta di apertura documento, whitelist path.
- `dashboard` chiama il builder; `core/hub_bacheca.py` non cambia (nessuna dipendenza inversa).

## Sicurezza / vincoli (CLAUDE.md)

- Deny-list sensibili rispettata **ovunque** (lista Bacheca + `document_open`).
- `document_open` whitelista per DB+root, nessun path arbitrario → no path traversal.
- Nessun endpoint API nuovo sotto `/api/`; le nuove route sono pagine gated `_can_manage`
  (admin) o `@login_required` (`document_open`, consultazione). Nessun tocco a
  `API_ACL_GATE_PATHS`.
- Email/notifiche invariate. Nessun dato reale nei test (documenti/PII sintetici).

## Test (TDD)

- Parte 1: lista unica (badge AI+PV coesistono), picker mostra doc non-PV, toggle relabel.
- Parte 2: `filter_auto_safe` ammette update-rev su doc PV; `SgiSyncLog` scritto su
  nuovo/updated/missing; badge nuova-rev derivato dal log; assegnazioni intatte.
- Parte 3: builder esclude i sensibili; `document_open` redirect SharePoint / stream
  fileserver whitelistato / 404 su path fuori root o documento sensibile; gruppo virtuale
  visibile in home e /bacheca.

## Migrazioni

- `SgiSyncLog` (nuova tabella). SQL-Server-safe (no indici parziali/unique nullable).

## Fuori scope

- Macchina a stati «nuova rev → campagna pubblicata → badge spento» (esplicitamente non voluta).
- Sincronizzazione dei documenti come righe HubLink persistenti.
- Riscrittura del flusso presa-visione/campagne esistente.
