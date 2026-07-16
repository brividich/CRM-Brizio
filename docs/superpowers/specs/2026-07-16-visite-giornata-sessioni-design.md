# Design — Visite mediche: "Giornata visite" reattiva, sessioni salvate e proposte di rinnovo

Data: 2026-07-16 · Stato: approvato (brainstorming) · Modulo: `anagrafica`

## Contesto

Il flusso `/anagrafica/visite-mediche/nuova-sessione/` (appena rifatto: candidati
"consoni", guardrail, referto per riga — vedi
`2026-07-15-visite-mediche-sessione-design.md`) è un wizard a 2 step **mono-tipo**:
scegli un tipo di visita, ottieni i candidati di quel tipo, registri. Per inserire
10-15 visite di tipi diversi in una giornata del medico competente servono più
sessioni separate, e l'inserimento non è reattivo (ricarico pagina tra i due step).

Il portale ha già il pattern reattivo giusto: le **sessioni di rinnovo qualifiche**
(`qualifica_sessione_create` + endpoint HTMX `qualifica_sessione_candidati`, deep-link
`?tipo=<id>`, preselezione scaduti/in-scadenza, picker, barra sticky). Questo design
porta le visite a quel livello e aggiunge un modello sessione salvato + proposte.

## Obiettivi

- **Giornata visite multi-tipo**: una sessione = data + medico + un elenco di persone,
  ognuna con la *propria* visita dovuta (tipi misti).
- **Reattiva** (HTMX): scelti data/medico, la tabella candidati si carica/aggiorna
  live senza reload; scorciatoie Tutti/Nessuno/Solo-scaduti; barra azioni sticky.
- **Sessioni salvate** (`VisitaSessione`): lista + dettaglio consultabili, aggiunta
  partecipanti a posteriori (come `QualificaSessione`).
- **Proposte di rinnovo**: un hub che, per tipo, propone chi è da rinnovare e apre la
  giornata già pre-caricata; più una "Giornata completa" (tutti i dovuti).
- **Punti d'ingresso multipli** che convergono sullo stesso deep-link `?tipo=<id>`:
  hub proposte, **scadenzario** (pulsante ↻ Rinnovo per gruppo), pagina stessa.
- Preservare i guardrail già fatti (anti-doppione, no date future, prescrizioni/note
  separate, referto per riga, badge origine).

## Non-obiettivi

- Stato "programmata/convocazione" con conferma esiti post-visita.
- Prenotazione/calendario del medico.
- Notifiche automatiche al dipendente alla creazione sessione.
- PDF "registro giornata" (valutabile dopo).

## Design

### 1. Modello dati (migrazione additiva)

`VisitaSessione` (nuovo, `models.py`):

- `data_svolgimento: DateField`
- `medico_competente: CharField(max_length=200, blank)`
- `luogo: CharField(max_length=200, blank, default="")`
- `note: TextField(blank, default="")`
- `created_by: FK(AUTH_USER_MODEL, SET_NULL, null)`, `created_at`, `updated_at`
- `__str__`: `"Giornata {data} — {medico}"`; `Meta.ordering = ["-data_svolgimento", "-id"]`.

`VisitaMedica.sessione`: nuovo `FK(VisitaSessione, null=True, blank=True,
on_delete=SET_NULL, related_name="visite")`. Le visite esistenti restano
`sessione=NULL` (retro-compatibile). Una sessione contiene visite di **tipi diversi**.
Eliminare una sessione NON elimina le visite (SET_NULL): lo storico clinico resta.

Migrazione: `AddField` × (VisitaSessione create + `sessione` su VisitaMedica). Nessun
dato toccato.

### 2. Builder candidati "giornata" (riuso, non riscrittura)

Nuovo helper in `views.py` che **riusa** `_build_candidati_sessione(tipo, oggi)` già
vetato (ruoli + MOD.128, cessati esclusi, fallback storico, stato/preselect):

```
def _build_candidati_giornata(oggi, tipo_id=None) -> list[dict]:
    tipi = [tipo] se tipo_id valido, altrimenti TipoVisitaMedica attivi
    righe = []
    for tipo in tipi:
        for c in _build_candidati_sessione(tipo, oggi):
            righe.append({**c, "tipo": tipo, "preselect": c["status"] in ("scaduta","in_scadenza")})
    ordina per (stato: scaduta→in_scadenza→mai, nome)
    return righe
```

- **Una riga = (persona, tipo dovuto)**. Chi ha 2 tipi in scadenza → 2 righe (= 2
  visite nel giorno, fedele al medico competente).
- `tipo_id` valorizzato = modalità mono-tipo (deep-link); assente = giornata completa.
- Scaduti/in-scadenza pre-selezionati; "mai effettuata" mostrata, non pre-selezionata.

### 3. Pagina "Giornata visite" reattiva (sostituisce il wizard mono-tipo)

`visite_mediche_nuova_sessione` (stessa route) diventa **pagina unica**:

- **GET** (opz. `?tipo=<id>`): rende data (default oggi), medico (`<datalist>` valori
  esistenti), luogo, e la tabella candidati — server-side se `?tipo=` è presente
  (deep-link no-JS), altrimenti vuota finché l'utente non sceglie un tipo o "tutti".
- **Endpoint HTMX** `visite_mediche_candidati` (nuovo, `visite-mediche/candidati/`):
  ritorna il partial `_visite_candidati.html` per `?tipo=<id>` (o tutti). Popola la
  tabella al cambio del filtro tipo, senza reload. Gated `_can_view_visite_mediche`.
- Riga: checkbox, nome (+ badge origine Ruolo/MOD.128/Storico), **tipo** (colonna,
  in giornata multi-tipo), ultima visita, scadenza attuale, stato, esito, prescrizioni,
  note, referto (file). Scorciatoie **Tutti / Nessuno / Solo scaduti**; barra sticky
  con contatore live + anteprima "N visite".
- **Picker "+ Aggiungi"**: riusa `visite_mediche_api_cerca_dipendente` (già con flag
  `pertinente`, cessati esclusi); in giornata la riga aggiunta richiede anche la scelta
  del **tipo** (select nel popup o nella riga). Filtro pertinenza per il tipo scelto.
- **POST salva**: crea una `VisitaSessione` (data/medico/luogo/note) e, per ogni riga
  selezionata `(legacy_id, tipo)`, una `VisitaMedica` con `sessione=<sess>` — riusando
  i **guardrail esistenti** (anti-doppione persona+tipo+data, no date future,
  prescrizioni/note separate, referto per riga, conteggi in audit). Redirect al
  dettaglio sessione. `data_svolgimento` della visita = data della sessione.

Form `enctype="multipart/form-data"`. Progressive enhancement: senza JS resta un
flusso a step server-side (il GET con `?tipo=` mostra già i candidati; il submit
funziona con i campi resi lato server).

### 4. Hub "Sessioni & Proposte" (`visite-mediche/sessioni/`)

Nuova pagina `visite_mediche_sessioni` = **hub**:

- **Proposte di rinnovo** (in alto): riusa i conteggi per tipo già calcolati in
  dashboard (ultima visita corrente per tipo → scadute/in-scadenza). Card per tipo:
  «Videoterminalisti — 🔴 8 · 🟠 4 → [Crea sessione]» (link `nuova-sessione?tipo=<id>`).
  In testa: «⚡ Giornata completa: N da rinnovare →» (link `nuova-sessione`).
- **Elenco sessioni salvate** (sotto): `VisitaSessione` recenti (data, medico, n. visite),
  link al dettaglio; pulsante «+ Nuova giornata».
- Gated `_can_view_visite_mediche`. Link dalla dashboard visite e dalla subnav.

### 5. Dettaglio sessione + aggiungi partecipante

- `visite_mediche_sessione_detail` (`visite-mediche/sessioni/<id>/`): intestazione
  (data/medico/luogo) + tabella partecipanti (persona, tipo, esito, scadenza). Picker
  **aggiungi partecipante a posteriori** → `visite_mediche_sessione_partecipante_add`
  (crea una `VisitaMedica` col tipo scelto, `sessione=<sess>`, data = data sessione;
  anti-doppione). Gated.
- `visite_mediche_sessione_delete` (admin): elimina la `VisitaSessione`; le visite
  restano (SET_NULL), messaggio esplicito. Speculare a `qualifica_sessione_delete`.

### 6. Scadenzario: pulsante "↻ Rinnovo" per gruppo

Lo scadenzario è già raggruppato per `(kind, tipo_nome)` (`_raggruppa_scadenze_per_tipo`).

- `_build_scadenzario_voci`: le voci **visite** oggi portano solo `tipo_nome` → aggiungo
  `tipo_id` (le voci qualifiche ce l'hanno già). Il raggruppatore propaga `tipo_id` al
  gruppo (dalla prima voce).
- `scadenzario.html`, intestazione di ogni gruppo:
  - `kind == "visita"` → «↻ Rinnovo» link a `nuova-sessione?tipo=<tipo_id>` (apre la
    giornata pre-caricata coi dovuti di quel tipo).
  - `kind == "qualifica"` → «↻ Rinnovo» link a `qualifica_sessione_create?tipo=<tipo_id>`
    (flusso esistente).
  - `formazione` (ha già la sua CTA altrove), `contratto`/prova → nessun pulsante.
- Gating invariato: il pulsante compare solo se la sorgente è visibile e l'utente può
  gestire quel dominio.

### 7. Privacy / ACL

Tutte le nuove viste gated `_can_view_visite_mediche` (dato sanitario). Il picker e
l'endpoint candidati non espongono esiti/prescrizioni, solo stato + tipo. Audit su
creazione sessione (riusa/estende `VISITA_MEDICA_BATCH_CREATA` con l'id sessione).

### 8. Test (label `anagrafica`, `--keepdb`, settings test)

- Modello: `VisitaSessione` + FK `sessione`; eliminare la sessione lascia le visite
  (SET_NULL).
- `_build_candidati_giornata`: multi-tipo flatten; persona con 2 tipi dovuti → 2 righe;
  cessati esclusi; `tipo_id` filtra a un solo tipo; preselect su scaduta/in-scadenza.
- POST giornata: crea `VisitaSessione` + N `VisitaMedica` di tipi misti collegate;
  guardrail (doppione saltato, data futura respinta) ancora attivi.
- Endpoint HTMX `visite_mediche_candidati`: rende il partial per tipo/tutti; 403 senza
  permesso.
- Hub proposte: conteggi per tipo corretti; link deep-link presenti.
- Dettaglio + aggiungi partecipante: crea visita nel gruppo sessione.
- Scadenzario: le voci visite portano `tipo_id`; il gruppo visite mostra «↻ Rinnovo»
  col deep-link corretto; il gruppo qualifiche punta a `qualifica_sessione_create`.
- Regressione: i test esistenti `tests_visite_sessione` aggiornati al nuovo flusso
  (il vecchio POST a 2 step è sostituito); `ScadenzarioEstesoTests` non regredisce.

### 9. Rollout

- Worktree dedicato, branch feature, commit + push (Session Isolation).
- Migrazione additiva. CHANGELOG.md `[Unreleased]` + README (sezione visite) obbligatori.
- Nessun version bump per-feature (il repo accumula sotto `[Unreleased]`).
- Riuso massimo: `_build_candidati_sessione`, `_requisiti_tipo_visita`,
  `_cessati_legacy_ids`, `_salva_referto_visita`, `ultime_visite_correnti_ids`,
  `_build_nomi_map`, pattern HTMX di `qualifica_sessione_candidati`.

## Rischi

- La pagina `nuova-sessione` cambia forma: i test esistenti del vecchio POST a 2 step
  vanno riscritti (non è regressione, è il nuovo flusso).
- Multi-tipo → più righe: attenzione a performance del builder (itera i tipi attivi ×
  `_build_candidati_sessione`); i tipi attivi sono pochi (decine), i candidati per tipo
  limitati. Accettabile; se cresce, batchare `ultime_visite_per_tipo`.
- Il picker in giornata deve chiedere il tipo: senza tipo la riga aggiunta non è
  registrabile (validazione lato server: righe senza tipo scartate con avviso).
