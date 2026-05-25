# Tabelle Personalizzabili — Progettazione

> **Stato**: rev. 2 — 2026-05-25. Infrastruttura attiva e auto-rollout client-side globale.
> **Obiettivo**: dare all'utente il controllo per-colonna su tutte le tabelle del portale (sort, filtro, ricerca, visibilità, ordine). Preferenze persistite per-utente sul DB.

---

## 1. Decisioni base (validate 2026-05-23)

- **Scope finale**: tutti i moduli del portale (formazione, anagrafica HR, dpi, tickets, assets, automazioni, ecc.).
- **Persistenza**: modello DB `UserTablePreference` (cross-device, coerente col pattern `UserUiPreference` già esistente).
- **Capacità per colonna**: sort (multi), filtro per colonna, ricerca globale, toggle visibilità + riordino.

---

## 2. Architettura

```
┌─ Template (qualsiasi pagina) ────────────────────┐
│  <table class="fm-table" data-table-id="..."     │
│         data-table-fields='[{...}]'>             │
│    <thead>                                       │
│      <tr> <th data-col="codice">…</th> … </tr>  │
│    </thead> …                                    │
│  </table>                                        │
└──────────────────────────────────────────────────┘
              ▲
              │ JS auto-binds
              ▼
┌─ static/core/js/fm-table-enhanced.js ─────────────┐
│  - rileva `<table data-table-id>` e tabelle dati   │
│    semplici senza configurazione esplicita         │
│  - costruisce barra controlli (search globale,    │
│    column menu, filter row sotto header)          │
│  - applica filtri client-side sulle righe         │
│    visibili                                       │
│  - GET/POST a /api/table-prefs/<table_id>/       │
│    per persistere preferenze                      │
└───────────────────────────────────────────────────┘
              ▲
              │ JSON
              ▼
┌─ core.UserTablePreference (DB) ────────────────────┐
│  (user, table_id) → JSON columns/sort/filters/q   │
└────────────────────────────────────────────────────┘
```

### Decisioni puntuali

- **Filtering client-side con auto-fetch del dataset completo**: il filtro applicato dall'utente è client-side, ma se la view è paginata server-side (link `?page=N` nel DOM vicino alla tabella) il componente, alla prima azione utente con filtro/sort/search attivo (o al primo render se lo stato persistito ha già una query attiva), scarica in background via `fetch()` tutte le pagine restanti, ne estrae i `<tr>` della tabella corrispondente (match per id / `data-table-id` da template / signature delle intestazioni, fallback per indice) e li unisce al `<tbody>` corrente. Lo stato viene poi riapplicato sul dataset completo, la paginazione nativa viene nascosta e le option dei filtri `select` + i suggerimenti `<datalist>` dei filtri testo rigenerati sui nuovi valori distinti. Cap di sicurezza `FM_MAX_MERGED_ROWS=5000`. Opt-out: `data-fm-fullload="0"` (o `data-fm-tbl-pagination-skip="1"`) sulla `<table>`.
- **Autocomplete nei filtri testo**: per ogni colonna `text` il popover include un `<datalist>` con i valori distinti correnti (max 60, ordinati locale `it`). Il browser mostra automaticamente i suggerimenti man mano che l'utente digita. I suggerimenti vengono rigenerati dopo il merge full-load.
- **Popover filtro fuori-flow**: il popover del filtro colonna viene migrato in `<body>` alla prima apertura e posizionato in `position:fixed` rispetto all'icona funnel, per non essere clippato da contenitori `overflow:hidden` / `overflow-x:auto` (`.table-responsive`, card HR ecc.). Si auto-chiude su resize/scroll della pagina.
- **Persistenza differenziata**: la "view config" (`visible`, `order`, `sort`) viene persistita su `UserTablePreference`; i filtri di colonna (`filters`) e la ricerca globale (`q`) sono invece **transitori** — vivono solo nella sessione di pagina, così quando l'utente ricarica o torna sulla pagina la tabella non risulta filtrata. Opt-in per persistenza completa: `data-fm-persist-filters="1"` (persiste anche `q`) oppure `data-fm-persist-search="1"` (persiste solo `q`). Lo stripping vale anche per entry storiche già salvate, che vengono ignorate al primo caricamento e sovrascritte vuote al prossimo save.
- **Spec colonna inline** nel template via `data-*` su `<th>`: niente accoppiamento Python/JS oltre il `table_id`.
- **Auto-bind**: nessun JS da scrivere a livello di pagina. Le tabelle con `data-table-id` e `data-col` mantengono configurazione esplicita; le tabelle dati semplici senza attributi vengono riconosciute automaticamente, ricevono `table_id` generato dalla pagina e colonne inferite dai `<th>`.
- **Opt-out**: aggiungere `data-fm-table-skip="1"` o `data-table-enhanced="0"` alla tabella o a un contenitore per escludere una tabella tecnica/layout dal potenziamento automatico.

---

## 3. Modello

```python
class UserTablePreference(models.Model):
    user      = models.ForeignKey(User, on_delete=CASCADE, related_name="table_prefs")
    table_id  = models.CharField(max_length=100, db_index=True)
    # Stato salvato in JSON: { "visible": ["codice","titolo"], "order": [...],
    #                          "sort": [["titolo","asc"]],
    #                          "filters": {"stato":"ATTIVO", "obbligatorio":"1"},
    #                          "q": "" }
    state_json = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("user", "table_id")]
```

`table_id` è una stringa stabile assegnata alla tabella nel template — convenzione kebab:
`formazione.corsi.list`, `formazione.sessioni.list`, `anagrafica.dipendenti.list`, ecc.

---

## 4. API

- `GET  /core/api/table-prefs/<table_id>/` → JSON dello stato salvato (vuoto se mai salvato).
- `POST /core/api/table-prefs/<table_id>/` → body JSON con `state_json`; upsert.
- `DELETE /core/api/table-prefs/<table_id>/` → reset (rimuove il record).

Autenticazione: `@login_required`. CSRF protetto (POST/DELETE con `X-CSRFToken` header).

---

## 5. Spec colonna nel template

Su ogni `<th>`:

```html
<th data-col="codice"
    data-col-label="Codice"
    data-col-type="text"
    data-col-sortable="1"
    data-col-filterable="1">Codice</th>

<th data-col="stato"
    data-col-label="Stato"
    data-col-type="select"
    data-col-options='[["ATTIVO","Attivo"],["BOZZA","Bozza"]]'
    data-col-sortable="1"
    data-col-filterable="1">Stato</th>

<th data-col="durata"
    data-col-label="Durata (h)"
    data-col-type="number"
    data-col-sortable="1"
    data-col-filterable="1">Durata (h)</th>
```

Tipi colonna supportati: `text` (input contains), `select` (select choices), `number` (range min/max), `date` (range from/to), `bool` (sì/no/tutti).

Colonne senza `data-col` sono visibili-sempre e non filtrabili (es. azioni).

---

## 6. UI controlli generati dal JS

Sopra la `<table>` viene inserita una barra:

```
[ 🔍 Cerca globale… ]   [Colonne ▾]   [Reset]   [✓ Preferenze salvate]
```

Nell'header di ogni colonna `data-col-filterable` compare l'icona filtro: il click apre un popover compatto con l'input adatto al tipo colonna.

Menu "Colonne": lista checkbox per visibilità + drag handle per riordinare.

Sort: click su `<th data-col-sortable>` cicla `asc → desc → off`. Shift+click aggiunge livello (multi-sort).

---

## 7. Roadmap patch

| Patch | Contenuto | Stato |
|-------|-----------|-------|
| **TBL-01** | Modello + API + JS+CSS + pilota su `formazione_corsi.html` | ✅ completato |
| **TBL-02** | Rollout tutte le tabelle formazione (piani, sessioni, scadenzario, istruttori, presenze, iscritti, ecc.) | ✅ lato client |
| **TBL-03** | Rollout anagrafica HR (dipendenti, qualifiche, visite, cedolini, contratti) | ✅ lato client |
| **TBL-04** | Rollout altri moduli (dpi, tickets, assets, automazioni, ecc.) | ✅ auto-bind globale |
| **TBL-05** | Server-side filter per tabelle paginate (query params + view helpers) | ⏳ |

Ogni patch è atomica e self-contained: una può essere posticipata senza bloccare le altre.

---

## 8. Out of scope (per ora)

- Salvataggio "preset" multipli per la stessa tabella (es. "vista commerciale" / "vista HR"). Da PATCH-TBL-06+.
- Export Excel dei dati filtrati. Già coperto dagli export specifici.
- Edit inline su cella. Non rientra in questo sistema.
