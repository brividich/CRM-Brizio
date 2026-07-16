# Polish multi-app (Stream 5) — Design / Spec

> Punch-list di riferimento: `docs/ANAGRAFICA - PERSONE.md`, sezioni **TIMBRI**, **PROCEDURE REFRESH**, **ASSET**, **KICKOFF**.
> Piano operativo gemello: `docs/superpowers/plans/2026-07-16-polish-multiapp.md`.

## Obiettivo

Pacchetto di rifiniture "polish" su **quattro app disgiunte** del portale
(`timbri`, `procedure_refresh`, `assets`, `tasks`). Ogni area è indipendente
dalle altre (file disgiunti) e committa separatamente. Lo stream **non tocca**
`anagrafica`, quindi **non c'è conflitto** con gli stream visite-mediche /
sessioni che lavorano su `anagrafica`.

## Vincoli architetturali comuni

- Django 5.2 SSR + HTMX, niente framework JS, niente React.
- Popup/lightbox = CSS/JS leggero inline nel template, riuso dei token di
  `theme.css`; nessuna dipendenza esterna.
- Impostazioni / quadranti / branding sono spesso **data-driven** (SiteConfig,
  `NavigationItem`, componenti condivisi `core/components/module_*`): dove il
  contenuto è un dato/config si rimuove via dato; dove è template statico si
  edita il template. Mai hardcodare rimozioni che il seed rigenererebbe.
- ACL invariata: si riusano i gate esistenti di ciascun modulo.
- Template Django: `{# #}` commenta **una sola riga**; niente attributi con `_`
  iniziale.

---

## A. TIMBRI — ricerca timbri anche per qualifica

### Stato attuale
- Vista lista/ricerca: `django_app/timbri/views.py` → `index()` (riga ~502).
  Il campo libero `q` (riga 529) filtra le righe dipendente su nome, alias,
  matricola, reparto, ruolo legacy (righe 537-553). Il secondo filtro è
  `reparto` (select, righe 554-555).
- La **qualifica** non è un attributo del dipendente ma del singolo timbro:
  `RegistroTimbro.qualifica` (`django_app/timbri/models.py` riga 111) — e in
  copia su `OperatoreTimbri.qualifica` (riga 66). Un dipendente può avere più
  registri con qualifiche diverse.
- Template filtri: `django_app/timbri/templates/timbri/pages/index.html`,
  form GET righe 260-283 (input `q` riga 264, select `reparto` riga 268).

### Design
1. Aggiungere un filtro **Qualifica** (select) accanto a Reparto nel form GET.
2. Le opzioni qualifica = valori distinti non vuoti da
   `RegistroTimbro.objects.values_list("qualifica", flat=True).distinct()`,
   ordinati, calcolati in `index()` e passati nel context (`qualifiche`).
3. Quando `qualifica` è valorizzata: filtrare le righe dipendente ai soli
   `legacy_anagrafica_id` che hanno **almeno un** `RegistroTimbro` con quella
   qualifica (match esatto case-insensitive). Implementazione:
   `OperatoreTimbri.objects.filter(registri__qualifica__iexact=qualifica)`
   `.values_list("legacy_anagrafica_id", flat=True)` → set di legacy id per cui
   tenere le righe. Applicato **dopo** il filtro `q`/`reparto`, prima della
   paginazione.
4. `q` continua a NON cercare la qualifica (resta ricerca anagrafica); la
   qualifica ha il suo filtro dedicato, coerente con "reparto". Reset/placeholder
   aggiornati. Il context deve restituire `qualifica` selezionata per lo stato
   del form, e includere `qualifica` nel controllo pill "Reset" (riga 280).

### Test (TDD, comportamentale)
`django_app/timbri/tests.py`, nuova classe. Un `OperatoreTimbri` con
`legacy_anagrafica_id` collegato a una riga legacy + due `RegistroTimbro` con
qualifiche diverse. `Client.get` su `timbri:index?qualifica=<X>` → la riga del
dipendente compare solo per la qualifica posseduta e sparisce per una qualifica
non posseduta. NB: usare `@override_settings(LEGACY_AUTH_ENABLED=False)` con
superuser per non far intercettare l'ACL middleware (trappola nota). Attenzione
allo `_timbri_schema_issue()` in ambiente test: gestire il caso schema mancante
seguendo il pattern dei test esistenti in `tests.py`.

---

## B. PROCEDURE REFRESH

### B1. "Gestione sessione" — rimuovere "Revisione da assegnare"

#### Stato attuale
- Template: `django_app/procedure_refresh/templates/procedure_refresh/pages/campaign_detail.html`,
  card "Assegna utenti" (righe 228-299). Contiene il select **"Revisione da
  assegnare"** (`name="revision_id"`, righe 236-243) che obbliga a scegliere UN
  documento.
- Vista: `django_app/procedure_refresh/views.py` → `assign_users()` (riga 1289).
  Richiede `revision_id` (righe 1296-1307) e crea **una** `ProcedureAssignment`
  per utente su **quella** revisione (righe 1318-1335). La notifica in-app cita
  la singola revisione (righe 1339-1356).

#### Design
Gli utenti devono leggere **tutti** i documenti della sessione, quindi non si
assegna un singolo documento: si assegna l'utente a **tutte le revisioni della
campagna**.
1. Template: rimuovere il blocco `<label>Revisione da assegnare</label> +
   <select name="revision_id">` (righe 236-243). Resta scadenza + selezione
   utenti.
2. Vista `assign_users`: eliminare la lettura/validazione di `revision_id`.
   Ricavare le revisioni dalla campagna: iterare i `campaign_docs`
   (`ProcedureCampaignDocument` collegati, gli stessi già usati per popolare il
   select) e per **ogni** utente × **ogni** revisione fare
   `ProcedureAssignment.objects.get_or_create(campaign, revision, user, ...)`.
3. Guardia: se la campagna non ha documenti → messaggio d'errore e redirect
   (non si può assegnare il nulla). La notifica in-app diventa una sola per
   utente, testo generico ("N documenti della sessione «...»"), non più per
   singola revisione.
4. Nessuna modifica al modello `ProcedureAssignment` (già unico per
   campaign+revision+user): il get_or_create resta idempotente.

#### Test (TDD, comportamentale)
`django_app/procedure_refresh/tests.py`. Campagna con 2 revisioni collegate +
2 utenti. `POST assign_users` con solo `user_ids` (senza `revision_id`) → devono
nascere 2×2 = 4 `ProcedureAssignment`. Secondo POST identico → nessun duplicato
(idempotenza). Campagna senza documenti → 0 assignment + messaggio.

### B2. Impostazioni — rimuovere "Accesso rapido" e rimpicciolire branding

#### Stato attuale
- Template: `django_app/procedure_refresh/templates/procedure_refresh/pages/admin_dashboard.html`
  (rotta `impostazioni/` → `views.admin_dashboard`).
  - Hero: include `core/components/module_settings_hero.html` (riga 72) con
    sottotitolo che cita "accessi rapidi".
  - Quadrante **"Accesso rapido"**: `<div class="pr-card">` righe 109-123 dentro
    la griglia `ms-grid-2`, affiancato al branding.
  - Branding: include `core/components/module_branding_card.html` (riga 124).

#### Design
1. Rimuovere l'intero blocco `pr-card` "Accesso rapido" (righe 109-123). La
   griglia `ms-grid-2` resta con la sola card branding (che occuperà la riga);
   valutare di togliere il wrapper `ms-grid-2` lasciando la branding card a
   larghezza piena, oppure passare a griglia a 1 colonna. Aggiornare il
   sottotitolo dell'hero togliendo "accessi rapidi".
2. **Rimpicciolire branding**: il branding è il componente **condiviso**
   `core/components/module_branding_card.html` + `module_settings_hero.html`,
   usato da 15 pagine impostazioni. Per non toccare gli altri moduli, introdurre
   una variante **compatta opt-in**:
   - `module_settings_hero.html`: se il chiamante passa
     `settings_variant="compact"`, aggiungere la classe `ms-hero--compact` alla
     `<section>`.
   - `module_branding_card.html`: se il chiamante passa `branding_compact=True`,
     aggiungere `ms-card--compact` alla `<section>`.
   - `core/components/module_settings_styles.html`: aggiungere regole CSS
     `.ms-hero--compact` (h1 più piccolo, padding ridotto) e
     `.ms-card--compact .ms-brand-mark` (marchio più piccolo). Backward
     compatibile: senza il flag il rendering resta identico.
   - `admin_dashboard.html`: passare `settings_variant="compact"` all'hero e
     `branding_compact=True` alla branding card.

#### Test (render leggero)
`Client.get` su `procedure_refresh:admin_dashboard` (utente manager): il body
**non** contiene "Accesso rapido"; contiene la classe `ms-hero--compact`.

---

## C. ASSET

### C1. Immagine header apribile in popup (lightbox)

#### Stato attuale
- Template: `django_app/assets/templates/assets/pages/asset_detail.html`, header
  `af-header` (riga 516). L'immagine è `asset.foto_targhetta` renderizzata come
  `<img class="af-targhetta" src="{{ asset.foto_targhetta.url }}" ...>`
  (righe 528-530), non cliccabile.

#### Design
1. Avvolgere l'`<img>` in un trigger cliccabile (`<button type="button"
   class="af-targhetta-trigger" data-lightbox-src="...">`), con `cursor:zoom-in`.
2. Aggiungere in fondo al template un overlay lightbox leggero (`<div
   id="af-lightbox">` nascosto) + `<style>`/`<script>` inline: al click sul
   trigger si mostra l'immagine a piena dimensione su sfondo scuro; chiusura con
   click sull'overlay o tasto `Esc`. Usa i token/tema esistenti (sfondo scuro
   con `rgba`), coerente col resto del portale, senza librerie.
3. Progressive enhancement: senza JS l'immagine resta visibile (il trigger è
   comunque un `<img>` mostrato), il lightbox è solo un di più.

#### Test (render leggero)
`Client.get` sulla pagina dettaglio di un asset **con** `foto_targhetta`: il body
contiene `af-targhetta-trigger` / `af-lightbox`. (Se popolare un `ImageField`
reale in test è oneroso, verificare la presenza del markup lightbox statico
sempre renderizzato e del wrapping condizionale.)

### C2. "Posizione in officina" — planimetria reale per ogni asset

#### Stato attuale — CAUSA DEL BUG
- Card MAP: `asset_detail.html` righe 1219-1228 mostra
  `map_marker.layout.image.url` come sfondo + un pallino su
  `x_percent/y_percent`.
- Context: `django_app/assets/views.py` righe 9880-9889 — `map_marker` è il
  primo `PlantLayoutMarker` dell'asset su un layout attivo.
- **Radice del problema**: `_ensure_asset_plant_layout_marker(asset)`
  (`views.py` righe 4010-4032) crea il marker **sempre sul PRIMO layout attivo**
  (`PlantLayout.objects.filter(is_active=True).order_by("category","name","id")
  .first()`), a coordinate fisse (50,50), **ignorando reparto/area dell'asset**.
  Risultato: ogni asset finisce sulla stessa planimetria "di default" ("la
  solita"), non su quella reale del suo reparto/officina.
- Modelli: `PlantLayout.category` (default "Officina") e
  `PlantLayoutArea.reparto_code` collegano un layout a un reparto
  (`models.py` righe 1412-1470). L'asset ha `asset.reparto`.

#### Design
1. Nuovo helper `_resolve_asset_plant_layout(asset)` che seleziona il layout
   **attivo** coerente con la posizione dell'asset, in ordine di preferenza:
   a) layout attivo la cui `category` combacia (case-insensitive) con
      `asset.reparto`; b) layout attivo che possiede una `PlantLayoutArea` con
      `reparto_code` combaciante con `asset.reparto`; c) fallback al primo layout
      attivo (comportamento storico) solo se nessun match — così non si regredisce
      quando i reparti non sono mappati.
2. `_ensure_asset_plant_layout_marker` usa `_resolve_asset_plant_layout(asset)`
   al posto del `first()` generico. Se un match specifico esiste ed è diverso dal
   layout su cui il marker era stato messo, **rimappare** il marker sul layout
   corretto (spostare o ricreare il `PlantLayoutMarker` sul layout risolto,
   rispettando il unique constraint layout+asset). Coordinate default invariate.
3. Nessuna modifica di modello. Solo logica di risoluzione layout.

#### Test (TDD, comportamentale)
`django_app/assets/tests.py`. Due `PlantLayout` attivi con `category` diverse
(es. "Officina" e "Reparto Cromatura"), un `Asset` con `reparto="Reparto
Cromatura"`. Chiamare `_ensure_asset_plant_layout_marker(asset)` →
`PlantLayoutMarker` creato **sul layout Cromatura**, non su quello
alfabeticamente primo. Secondo caso: asset con reparto non mappato → fallback al
primo layout attivo (nessuna eccezione).

---

## D. KICKOFF (app `tasks`)

### D1. In dashboard non si vedono i kickoff già programmati — BUG

#### Stato attuale — CAUSA PROBABILE
- "Dashboard" kickoff = `project_list()` (`django_app/tasks/views.py` riga 3269),
  template `tasks/projects.html` ("Portfolio kickoff"). Elenca i `Project`
  (= kickoff) restituiti da `_scoped_projects_queryset(request)` (riga 1025).
- Per utenti **non admin/non full-read**, lo scope è
  `_project_scope_filter_q(request)` (righe 982-1004). Un progetto entra solo se:
  `created_by=user` **oppure** ha **tasks** create/assegnate/sottoscritte
  dall'utente, oppure l'utente è PM/CapoCommessa/Programmatore (role-gated),
  oppure c'è un task di categoria col ruolo dell'utente.
- **Radice**: un kickoff **programmato** ma **senza task** (appena creato /
  pianificato), o dove l'utente è **solo partecipante dell'incontro**
  (`KickoffMeeting.partecipanti_utenti`, `models.py` riga 928) e non è
  creator/PM, **non entra in nessun ramo** del filtro → non compare in
  dashboard. I `KickoffMeeting` non sono considerati dallo scope.

#### Design
Estendere `_project_scope_filter_q` includendo i kickoff in cui l'utente è
partecipante di un incontro programmato:
`q |= Q(meetings__partecipanti_utenti=user)`.
(Valutare anche `Q(meetings__created_by=user)` per chi ha creato l'incontro.)
La `_scoped_projects_queryset` fa già `.distinct()`, quindi il join M2M non
duplica. Nessun cambio ai rami esistenti: additivo.

#### Test (TDD, riproduce il bug)
`django_app/tasks/tests.py`. Utente **non** admin/non full-read. `Project` senza
task, creato da un altro utente, con un `KickoffMeeting` in cui l'utente è
`partecipanti_utenti`. **Prima** del fix: il progetto **non** è in
`_scoped_projects_queryset` / non appare in `project_list`. **Dopo**: appare.
NB: impostare l'accesso task in modo che l'utente NON abbia full-read (altrimenti
il queryset ritorna tutto e il test non discrimina); usare gli helper/fixture
dei test tasks esistenti per livello accesso.

### D2. Assegnazione attività dalla pagina dell'incontro

#### Stato attuale
- La pagina `project_meeting_detail` (`views.py` riga 6344, template
  `tasks/project_meeting_detail.html`) ha **già** un modal "Crea task dal next
  step" con select **"Assegna a"** (`active_users`, template righe 520-576) che
  fa POST a `project_meeting_task_from_step` (`views.py` riga 6512), il quale
  crea un `Task` con assegnatario/scadenza/priorità.
- **Limite**: il modal si apre **solo** dai righi di `meeting.next_steps`
  (template righe 487-499). Se l'incontro non ha next_steps, non c'è modo di
  creare/assegnare un'attività dalla pagina.

#### Design
Aggiungere un pulsante **"+ Crea / assegna attività"** sempre visibile nella
pagina incontro (per chi `can_manage`), che apre lo stesso modal `#ctm-overlay`
con step di riferimento vuoto e titolo libero. Riusa la view
`project_meeting_task_from_step` esistente (nessun cambio backend necessario:
`title` è già l'unico obbligatorio; lo "step" è solo descrizione). Il modal e la
select assegnatario esistono già.

#### Test (render leggero)
`Client.get` su `project_meeting_detail` di un incontro **senza** next_steps,
utente manager: il body contiene il pulsante "Crea / assegna attività" (trigger
del modal) e il modal `ctm-overlay` con la select `assigned_to`.

### D3. Impostazioni — rimuovere "Tutte le impostazioni modificabili" e rimpicciolire branding

#### Stato attuale
- Vista canonica: `impostazioni()` (`views.py` riga 5275; **attenzione**: esiste
  una seconda `def impostazioni` a riga 4049 sovrascritta da questa — la valida è
  la 5275), template `tasks/impostazioni.html`.
- Nel template, tab config: pannello con titolo **"Tutte le impostazioni
  modificabili"** (riga 211) + sottotitolo (riga 212) + callout "Tutte le
  impostazioni modificabili del modulo sono in questa tab..." (righe 223-224).
- Hero titolo usa `module_branding_display_label` (riga 147); branding card
  inclusa a riga 229; riassunto branding righe 403-405.

#### Design
1. Rimuovere il titolo/sottotitolo/callout ridondante "Tutte le impostazioni
   modificabili" (righe 211-212 e 223-224), lasciando i controlli effettivi
   (form config, branding, ecc.). È testo statico di template → rimozione diretta.
2. **Rimpicciolire branding**: stessa variante compatta opt-in di B2. Se
   `tasks/impostazioni.html` include `module_settings_hero.html` passare
   `settings_variant="compact"`; alla `module_branding_card.html` (riga 229)
   passare `branding_compact=True`. (Riusa le stesse modifiche ai componenti
   condivisi introdotte nel blocco B — quindi **il blocco B va prima del blocco
   D** per avere i modificatori già disponibili, oppure introdurre i modificatori
   nel primo dei due blocchi eseguiti. Vedi ordine nel piano.)

#### Test (render leggero)
`Client.get` su `tasks:impostazioni?tab=config` (utente admin): il body **non**
contiene "Tutte le impostazioni modificabili"; contiene `ms-hero--compact`.

---

## Interdipendenza tra blocchi

- **A / C** sono completamente autonomi.
- **B2** e **D3** condividono le modifiche ai componenti condivisi
  `core/components/module_settings_hero.html`, `module_branding_card.html`,
  `module_settings_styles.html` (variante compatta). Per evitare conflitto
  interno: introdurre la variante compatta **nel blocco eseguito per primo tra i
  due** (nel piano: nel blocco B), e nel blocco D limitarsi a **usarla**. Sono
  file `core/` ma le modifiche sono additive e backward-compatibili; nessun altro
  stream tocca `core/components/module_*`.
- Nessun file è condiviso con gli stream `anagrafica` (visite/sessioni): stream
  disgiunto, **nessun conflitto cross-stream**.

## Fuori scope

- Non si riscrive la UI KICK-OFF ("ci arrendiamo" da punch-list): solo bugfix
  dashboard + assegnazione da incontro + pulizia impostazioni.
- Non si tocca il flusso import/anagrafica timbri, né il modello dati di alcun
  modulo (le modifiche C2/D1 sono solo di logica/query).
- Niente version bump.
