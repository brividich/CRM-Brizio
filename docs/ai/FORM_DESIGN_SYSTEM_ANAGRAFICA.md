# Design-system dei form — modulo Anagrafica (e primitive form-kit portale-wide)

> Scopo: se devi **mettere mano ai form di inserimento/gestione** dell'anagrafica (o
> cambiare l'aspetto dei campi in generale), parti da qui. La regola d'oro è
> **single-point-of-change**: l'aspetto dei campi si cambia in **un punto solo**, non
> pagina per pagina.

## Requisito d'origine

Richiesta utente (2026-07-07/08): i form di **creazione/gestione** dell'anagrafica devono
essere **verticali** (colonna singola, non griglia orizzontale), con **suddivisione in
sezioni per tipo di campo** (header + descrizione), coerenti col DB e intuitivi — e
soprattutto realizzati con **componenti riusabili**, così un futuro ritocco all'UI è un
intervento localizzato.

## La primitiva canonica: `.hub-field`

Vive in **`django_app/core/templates/core/components/_hub_formkit.html`** (form-kit
**portale-wide**, non solo anagrafica). È la fonte unica dell'aspetto dei campi:

- `.hub-field` — contenitore campo, `display:flex; flex-direction:column` (label sopra, input sotto).
- `.hub-field > label` — label in mono 10px uppercase (stile HUB).
- styling di `input`/`select`/`textarea` **discendenti** di `.hub-field` (bordo, focus, ecc.).
- **override dark-mode integrato** (`body.theme-dark .hub-field input/select/textarea`).
- `.hub-req` — l'asterisco rosso del campo obbligatorio.

Contenitori/sezioni:

- `.hub-form-stack` — stack verticale di campi/sezioni (il default per i form verticali).
- `.hub-form-grid` — griglia 2 colonne responsive (→ 1fr sotto 720px). **È globale**: quando
  serve una coppia 2-col compatta usala, ma **non ridefinirla** localmente (blast-radius).
- `.hub-fsec` / `.hub-fsec-h` / `.hub-fsec-d` — sezione titolata (contenitore / header / descrizione).

Corollario: **se un campo usa `.hub-field`, non serve CSS locale** per label/input/dark-mode.
Ridefinirlo localmente = duplicazione da evitare.

## Le tre leve riusabili (quale usare)

1. **Form full-page da `ModelForm`** (bound-field Django) → partial
   **`anagrafica/partials/_fmd_section.html`** (titolo + descrizione + `.fmd-stack` di campi)
   alimentato dal filtro **`section_fields`** in `anagrafica/templatetags/anagrafica_extras.py`
   (`form|section_fields:"campo1,campo2"`). Dichiari i nomi-campo per sezione, il markup è
   centralizzato. Esempi: `formazione_corso_form.html`, `formazione_sessione_form.html`,
   `mpq_processo_form.html` (MOD.128).

2. **Modali / form semplici** che includono **`anagrafica/partials/_fmd_form_fields.html`**
   → rende già `.fmd-stack` (verticale). Ogni modale che lo include diventa verticale
   automaticamente (es. crea-piano formativo).

3. **Form catalogo "hand-written"** (input raw, la view legge `request.POST[...]`, niente
   `form` Django) → usa direttamente le **primitive `.hub-field` / `.hub-form-stack` /
   `.hub-fsec`** del form-kit canonico. È il caso dei form-lista catalogo (vedi sotto).

## Stato dei form catalogo (già consolidati su `.hub-field`)

Tutti includono `_hub_formkit.html` e usano `.hub-field`; **niente più classi di campo locali**.

| File | Form "nuovo" | Modale modifica |
| --- | --- | --- |
| `mansioni_list.html` | `.hub-form-stack` + `.hub-fsec` | `.hub-form-stack` + `.hub-field` |
| `ruoli_operativi.html` | `.hub-form-stack` + `.hub-fsec` | `.hub-form-stack` + `.hub-field` |
| `qualifiche_list.html` | `.hub-form-stack` + `.hub-fsec` | `.hub-form-stack` + `.hub-field` |
| `aree_list.html` | `.hub-form-stack` (reparto + area) | `.hub-form-stack` + `.hub-field` (2 modali) |
| `ruoli_aziendali_list.html` | `.hub-form-stack` (era orizzontale, raddrizzato) | `.hub-form-stack` + `.hub-field` |

In questi file **restano** (giustamente) le classi locali che NON sono campi: chrome, card,
bottoni, tabelle, pill, tab, band — es. `.mn-item*`, `.ro-btn/.ro-card/.ro-swatch`,
`.ql-btn/.ql-scad*/.ql-panel-warn`, `.cat-btn/.cat-card/.cat-table/.cat-pill/.cat-tabs/.area-band`.
Toccare **solo** le classi di campo (`*-field/*-label/*-input/*-select/*-form-grid`).

## Lasciati compatti di proposito (NON sono difetti "da raddrizzare")

- `dipendente_retribuzioni.html` — form d'aggiunta voce già verticale (`grid-template-columns:1fr`);
  modale di modifica compatto a 2 colonne **voluto**; il resto è la tabella pivot retributiva.
- `impostazioni.html` — hub impostazioni (~2600 righe, ~13 tab): le "add-form" sono **barre
  quick-add compatte** per progettazione e i modali di modifica sono **già verticali**
  (`.imp-modal-body` è `flex-direction:column`). Riscriverle sul kit = invasivo e a basso valore.
- Editor inline `formazione_corso_elearning`, picker a checkbox `mansione_requisiti`, e i form
  già verticali via renderer core (`attestato_impostazioni`, categorie/esposizioni rischi),
  coppie 2-col sensate in `rischi_fattori`.

## Gotcha / trappole

- **Non ridefinire `.hub-form-grid`** (è globale in `_hub_formkit.html`): aggiungi primitive
  additive, non override.
- Header di sezione **testuali** (niente `<use href="#...">`): non dipendere dallo sprite icone
  su ogni pagina.
- `{# ... #}` multi-riga **esegue** i tag interni → usare `{% comment %}`.
- `qualifiche_list.html` ha WIP dark-mode concorrente sulle scadenze (`.fmd-scad*`/`.ql-scad*`/
  `.ql-panel-warn`): edit **token-safe**, non clobberare quei blocchi.
- Working tree condiviso tra sessioni: `git status`/`diff --cached` prima di committare, mai `git add .`.

## Come verificare (smoke-render dev)

Django test `Client` con `settings.ALLOWED_HOSTS=["*"]`, `Client(raise_request_exception=False)`,
`force_login` di un superuser, `GET` sulle URL dei form → attesa **200**. Dopo aver rimosso
classi locali, un **grep** su `*-field|*-label|*-input|*-select|*-form-grid` deve dare **0 orfani**.
`manage.py check --settings=config.settings.dev` deve restare pulito. **Nessuna migration**
(solo template/CSS/tag).

## Caveat non correlato: drift `0080`

`aree_list.html` (e `mod128/<id>/modifica`) possono andare in **500** in smoke per la migrazione
WIP **non tracciata** `0080_reparto_area_aziendale_inversione` (altra sessione, distruttiva):
ha cambiato i modelli `ProcessoQualificato`/`AreaAziendale`/`Reparto` ma il DB dev ha ancora lo
schema vecchio → colonne `colore`/`reparto_id`/`responsabile_legacy_id` mancanti, la query
fallisce **prima** del template. **Non è il restyle**; il markup è corretto (`check` pulito).
Non applicare `0080` finché non è completa (decisione presa).

## Riferimenti

- Frontend conventions generali: [04_FRONTEND_DIRECTION.md](04_FRONTEND_DIRECTION.md).
- Quality gate pre-finish: [06_TESTING_AND_QUALITY_GATES.md](06_TESTING_AND_QUALITY_GATES.md).
- Storia dell'iniziativa: voci `[Unreleased]` in `CHANGELOG.md` (restyle verticale + consolidamento design-system).
