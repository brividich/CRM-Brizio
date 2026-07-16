# Anagrafica — Formazione/Compliance UI & Impostazioni — Design (Stream 3)

> Spec di design per lo **stream 3** della punch-list `docs/ANAGRAFICA - PERSONE.md`
> (sezioni ANAGRAFICA – FORMAZIONE, ANAGRAFICA – COMPLIANCE, Impostazioni ANAGRAFICA).
> Interventi UI + **una** modifica funzionale (chip "Processi qualificati" e "Ruoli"
> inline). Nessuna riscrittura di modelli dati salvo, eventualmente, una choice
> aggiuntiva. Piano operativo: `docs/superpowers/plans/2026-07-16-anagrafica-formazione-ui-settings.md`.

## Obiettivo

Cinque interventi, tutti dentro `django_app/anagrafica`, sul modulo Formazione,
Compliance e sulla pagina Impostazioni anagrafica:

1. **FORMAZIONE — "Nuovo istruttore"**: rifinire visivamente il popup di creazione
   e il popup di modifica istruttore.
2. **FORMAZIONE — "Gestione e-learning"**: ripulire lo "sporco" nel form della
   pagina di gestione (assegnazione dipendenti).
3. **FORMAZIONE — "Qualifiche–abilitazioni"**: aggiungere la categoria/chip
   **"Processi qualificati"** accanto a *Tutte / Sicurezza / Professionale /
   Gestionale / Altro*.  ← unico intervento **funzionale**.
4. **COMPLIANCE — "Modifica mansione"**: rifinire il popup di modifica mansione.
5. **IMPOSTAZIONI ANAGRAFICA**: pulire lo "sporco" tra *Reparti* e *Ruoli* nella
   sidebar dei tab; il tab **"Ruoli"** non deve più mandare a una pagina esterna ma
   mostrarsi **inline** come gli altri tab.  ← secondo intervento **funzionale**.

## Stato attuale (file/righe reali)

### 1. Popup "Nuovo istruttore"
- Template: `django_app/anagrafica/templates/anagrafica/pages/formazione_istruttori.html`.
- View: `views.formazione_istruttori_list` (`views.py:11465`), context `TIPO_CHOICES`,
  `form`, `is_editor`.
- Due modali con **stili inline grezzi** (non design-system):
  - `#modal-crea-istr` (righe 113–130): overlay `position:fixed;inset:0;...`,
    card `background:#fff;border-radius:12px;padding:28px 32px;width:520px;...`;
    corpo campi via `{% include "anagrafica/partials/_fm_form_fields.html" with form=form %}`.
  - `#modal-edit-istr` (righe 132–149): campi **iniettati via JS** in
    `openEditModal(...)` (righe 152–174) con markup `.fm-input`/`.fm-label`
    hard-coded nello script; `.fm-label` definita in un `<style>` a fine file (riga 176).
- Sporco: doppia fonte di verità dei campi (partial server-side per il "crea", markup
  JS per il "modifica"), overlay/card con colori hard-coded, nessun supporto tema
  scuro, chiusura solo via `×` (niente click-fuori / ESC).

### 2. Form "Gestione e-learning"
- Pagina di gestione corso: `templates/anagrafica/pages/formazione_elearning_manage.html`
  (view `views.formazione_elearning_manage`, `views.py:14808`).
- Il "form con sporco" è il box **"Assegna dipendenti"** (`fm-add-box`, righe 138–165):
  mescola classi design-system (`fmd-btn`, `fmd-search`, `fmd-block-title`) con
  **inline style grezzi** (`style="display:flex;gap:14px;flex-wrap:wrap;align-items:flex-end;..."`,
  `.fm-input` con `style="max-width:180px;"`, `.fm-assign-list`/`.fm-assign-item`) e
  una `<label class="fmd-field">` con `<span>` stilizzato inline.
- Correlati (stessa famiglia "e-learning", da lasciare coerenti se toccati):
  `formazione_elearning_settings.html` (già pulito, usa `_fmd_field.html`),
  `formazione_corso_form.html` (già su `_fmd_field.html`).

### 3. Chip "Processi qualificati" nelle Qualifiche
- Pagina: `templates/anagrafica/pages/qualifiche_list.html`; view `views.qualifiche_list`
  (`views.py:5953`).
- Le chip categoria (righe 73–78 del template) sono costruite dal context `tabs`,
  popolato in view (righe 6034–6038) da:
  - `("", "Tutte", len(tipi))` + una voce per ciascuna di
    `TipoQualifica.CATEGORIA_CHOICES`.
- `TipoQualifica.CATEGORIA_CHOICES` (`models.py:512-517`):
  `SICUREZZA / PROFESSIONALE / GESTIONALE / ALTRO`.
- I **processi qualificati** NON sono una categoria di `TipoQualifica`: sono il
  modello MOD.128 `anagrafica.models_mpq.ProcessoQualificato`, già caricato in view
  come `processi_qualificati` (righe 6045–6056) e già renderizzato in una sezione
  dedicata del template (righe 181–207, "Processi qualificati (MOD.128)").
- **Problema attuale**: manca una chip che li rappresenti; la sezione MOD.128 resta
  visibile in fondo anche quando si filtra per un'altra categoria (es. `?categoria=SICUREZZA`),
  perché è dentro un `{% if processi_qualificati %}` incondizionato rispetto al filtro.

### 4. Popup "Modifica mansione"
- Template: `templates/anagrafica/pages/mansioni_list.html`; view `views.mansioni_list`
  (`views.py:5371`), context `CATEGORIA_CHOICES` (`Mansione.CATEGORIA_CHOICES`),
  `LIVELLO_RISCHIO_CHOICES`.
- Modale `#mn-modal` (`.mn-modal-overlay`/`.mn-modal`, CSS righe 21–28 del `<style>`
  in testa, markup righe 192–224). Già usa `hub-form-stack`/`hub-field` (buono) e ha
  dark mode parziale (riga 28 `body.theme-dark .mn-modal`), ma:
  - overlay/dimensioni con valori hard-coded, header senza pulsante `×`,
  - niente chiusura con ESC, corpo non `overflow-y:auto` (su schermi bassi il footer
    esce dal viewport), palette non allineata ai token del tema per l'overlay.
- Nota: la modifica della mansione **assegnata al singolo dipendente** è un altro
  flusso (form inline `#mansione-form` in `dipendente_detail.html`, righe 870–889) —
  **fuori scope** qui; l'intervento riguarda il popup del **catalogo mansioni**
  ("Modifica mansione"), che è l'unico popup con quel titolo.

### 5. Impostazioni — Reparti/Ruoli sidebar + "Ruoli" inline
- Pagina: `templates/anagrafica/pages/impostazioni.html`; view `views.impostazioni`
  (`views.py:8386`).
- Sidebar tab (`.imp-tabs`, righe 197–255): i tab sono `<button data-tab="...">` che
  attivano il pannello `<section class="imp-panel" data-panel="...">` corrispondente
  via JS (`setTab`, righe 2239–2275: toggla `.active` su tab e pannello).
- **Sporco reparti/ruoli**:
  - "Aree aziendali" (🏭, `data-tab="aree-aziendali"`), "Reparti" (🏢, `data-tab="aree"`
    — nome pannello storico `aree` ma etichetta "Reparti") e "Ruoli" convivono con
    un commento Fase-2 orfano (righe 210–212).
  - **"Ruoli"** è un `<a class="imp-tab" href="{% url 'anagrafica:ruoli_operativi_list' %}">`
    (righe 213–216): unico tab (con "E-learning") che **naviga via** invece di aprire
    un pannello inline. Cliccandolo si lascia la pagina Impostazioni.
- La gestione ruoli sta nella pagina autonoma
  `templates/anagrafica/pages/ruoli_operativi.html` (view `views.ruoli_operativi_list`
  `views.py:3105`, context `ruoli`, `ruoli_catalogo`, `ruoli_suggeriti`, `is_admin`).
  Contiene: griglia ruoli, form "+ Nuovo ruolo", suggeriti, e modale "Modifica ruolo"
  (`#ro-modal`, script `openEdit`). Le route CRUD già esistono
  (`ruolo_operativo_create` / `.../modifica` / `ruolo_operativo_delete`).
- La view `impostazioni` fornisce già `ruoli_operativi` annotato con `n_assegnati`
  (`views.py:8436-8438`) ma **non** `ruoli_catalogo`/`ruoli_suggeriti`, necessari per
  rendere il pannello inline identico alla pagina autonoma.

## Design proposto

### Principi trasversali (design-system)
- Riusare i **token di `theme.css`** e le classi esistenti `hub-`
  (`hub-form-stack`, `hub-fsec`, `hub-field`, `hub-btn`) e il set `fmd-*`
  (`fmd-btn`, `fmd-panel`, `fmd-field`) già in uso nel modulo. **Niente React.**
- Tema chiaro/scuro: i token `--surface-alt`, `--thead-bg`, `--tbody-hover`
  esistono **solo** in `body.theme-dark` → usarli sempre con fallback
  (`var(--surface-alt, #f8fafc)`), oppure gate dentro `body.theme-dark { ... }`
  come già fanno `mn-modal`/`ro-modal`.
- **Modale canonico**: uniformare i tre popup (istruttore, mansione, e in futuro
  ruolo) sul pattern già più maturo `.mn-modal`/`.ro-modal`:
  overlay `position:fixed;inset:0;background:rgba(...)`, card centrata con
  `max-width` + `max-height:90vh;overflow-y:auto`, header con titolo + `×`,
  chiusura su click-overlay e su **ESC**, override `body.theme-dark`.
  Preferire estrazione di CSS ripetuto in `_hr_restyle.html`/`formazione_design.css`
  **solo se** già lì convergono classi affini; altrimenti mantenere il `<style>`
  locale della pagina per minimizzare il blast-radius su file condivisi.

### 1. Popup "Nuovo istruttore"
- Unificare la **fonte dei campi**: usare il partial
  `anagrafica/partials/_fm_form_fields.html` (o un nuovo
  `_istruttore_fields.html`) sia nel modale "crea" sia in quello "modifica",
  eliminando il markup JS hard-coded di `openEditModal`. Il modale "modifica"
  ottiene i campi renderizzati server-side (nascosti) e li popola per valore, oppure
  — più semplice e coerente col resto del modulo — mantiene i campi statici nel DOM
  e `openEditModal` setta solo `value`/`action` (come fa `mn-modal`/`ro-modal`).
- Applicare il **pattern modale canonico** (overlay/card/`×`/ESC/click-fuori,
  `max-height:90vh;overflow-y:auto`, dark mode).
- Sostituire i colori hard-coded con i token; label via `.hub-field label` o
  `.fmd-field` invece di `.fm-label` ad hoc.

### 2. Form "Gestione e-learning"
- Ripulire il box **"Assegna dipendenti"** in `formazione_elearning_manage.html`:
  spostare gli inline `style="..."` in classi `fmd-*`/`hub-*` esistenti (o poche
  regole in `formazione_design.css`), allineare `fm-input`/`fm-assign-list` alla
  griglia del resto della pagina, uniformare spaziature e stati (hover/focus) coi
  token del tema. Nessun cambiamento di comportamento del POST (`formazione_elearning_assign`).

### 3. Chip "Processi qualificati" (funzionale)
- **NON** aggiungere una nuova choice a `TipoQualifica.CATEGORIA_CHOICES`
  (creerebbe una categoria vuota e duplicherebbe MOD.128, richiedendo migrazione dati
  inutile). I processi qualificati **restano** il modello MOD.128 già caricato.
- In `views.qualifiche_list`:
  - definire una costante pseudo-categoria locale, es. `CAT_PROCESSI = "PROCESSI"`
    (label "Processi qualificati"), **non** persistita sul modello.
  - includere `"PROCESSI"` in `valid_cats` per il parsing di `?categoria=`.
  - aggiungere alla lista `tabs` la voce
    `("PROCESSI", "Processi qualificati", len(processi_qualificati))`.
  - quando `cat_filter == "PROCESSI"`: `tipi_grouped = []`, `scadenze = []`,
    e passare un flag `mostra_processi = True`; quando `cat_filter` è una categoria
    reale non vuota: `mostra_processi = False` (nasconde la sezione MOD.128);
    quando `cat_filter == ""` (Tutte): `mostra_processi = True`.
- In `qualifiche_list.html`:
  - la chip esce automaticamente dal loop su `tabs` (nessun markup nuovo per la chip).
  - avvolgere la sezione "Processi qualificati (MOD.128)" (righe 181–207) in
    `{% if mostra_processi and processi_qualificati %}`.
- **Test** (funzionale): la chip "Processi qualificati" è presente con conteggio
  corretto; `?categoria=PROCESSI` mostra la sezione MOD.128 e **nasconde** il
  catalogo tipi; `?categoria=SICUREZZA` **non** mostra la sezione MOD.128.

### 4. Popup "Modifica mansione"
- Rifinire `#mn-modal` in `mansioni_list.html`: header con titolo + pulsante `×`,
  corpo `max-height:90vh;overflow-y:auto`, chiusura ESC (oltre al click-overlay già
  presente), overlay/superfici via token con fallback. Mantenere invariati campi,
  `openEdit(...)`, action e `hub-form-stack`/`hub-field`.

### 5. Impostazioni — Ruoli inline + pulizia
- **Estrarre** il corpo gestione-ruoli da `ruoli_operativi.html` in un partial
  riusabile, es. `templates/anagrafica/partials/_ruoli_operativi_body.html`
  (griglia + form "+ Nuovo ruolo" + suggeriti + modale `#ro-modal` + script), con lo
  `<style>` `ro-*` incluso una sola volta (o spostato in un `_ruoli_style.html`).
  La pagina autonoma `ruoli_operativi.html` `{% include %}`-a il partial (resta
  funzionante per i link diretti / retro-compatibilità).
- In `impostazioni.html`:
  - trasformare il tab "Ruoli" da `<a href=...>` a
    `<button class="imp-tab" data-tab="ruoli" type="button">…</button>`;
  - aggiungere `<section class="imp-panel" data-panel="ruoli" id="tab-ruoli">` che
    `{% include %}`-a `_ruoli_operativi_body.html`;
  - rimuovere il commento Fase-2 orfano (righe 210–212) e allineare etichette/icone
    del gruppo *Aree aziendali / Reparti / Ruoli* (pulizia "sporco", senza cambiare
    la semantica dei pannelli `aree-aziendali`/`aree`).
- In `views.impostazioni`: aggiungere al context `ruoli_catalogo`
  (`RuoloOperativo.objects.order_by("nome").values("id","nome")`) e
  `ruoli_suggeriti`, ed estendere `ruoli_operativi` con `select_related("riporta_a")`
  (già annotato `n_assegnati`) così il partial renderizza identico alla pagina.
- **Test** (funzionale): GET `impostazioni` rende inline il form "+ Nuovo ruolo" e la
  griglia ruoli (nessun redirect); il tab "Ruoli" è un `<button data-tab="ruoli">`
  e **non** un `<a href>` verso `ruoli_operativi_list`.

## Vincoli / non-obiettivi
- Nessun cambiamento ai POST/route esistenti (istruttore, mansione, ruolo, assign
  e-learning): solo presentazione + il wiring inline dei Ruoli e la chip Processi.
- Nessuna migrazione dati. Nessun nuovo modello. La chip "Processi qualificati" è
  virtuale (non tocca lo schema).
- La **subnav di modulo** (`anagrafica/components/subnav.html`) è guidata da
  `NavigationItem` (section) e **non** va hardcodata; i `.imp-tabs` della pagina
  Impostazioni sono invece tab interni alla pagina (modificabili nel template).
- Template Django: `{# #}` commenta **una sola riga**; niente attributi con `_`
  iniziale.
- Coerenza tema chiaro/scuro obbligatoria per ogni superficie toccata.

## Coordinamento con stream 1 e 2 (paralleli)
File potenzialmente condivisi (rischio conflitto): `anagrafica/views.py`,
`anagrafica/urls.py`, `impostazioni.html`. Mitigazione: interventi il più possibile
isolati ai template dei popup e al partial ruoli; su `views.py` toccare solo
`qualifiche_list` e `impostazioni` (blocchi disgiunti). Nessuna nuova route in
`urls.py` (si riusano le route CRUD ruoli esistenti). Dettaglio nel piano, sezione
"Coordinamento".
