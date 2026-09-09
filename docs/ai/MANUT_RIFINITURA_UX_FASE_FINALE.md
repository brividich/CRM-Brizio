# Manutenzione — Fase finale di rifinitura UX

Documento di lavoro (checklist operativa). Fonte: brief utente 2026-09-09.
Serve a evitare di ricaricare il brief completo in contesto: **leggere questo file, non il prompt originale**.

## Obiettivo

RIDURRE LA COMPLESSITÀ PERCEPITA, NON RIDURRE LA POTENZA DEL MODULO.

- Manutentore entra e vede «cosa devo fare?», non «quale tabella devo interpretare?».
- Responsabile entra e vede «dove sono i problemi?».
- Direzione entra e vede «come sta andando la manutenzione?».

Criterio quantitativo (progettuale, non matematico): **-20/30% informazione visibile nelle schermate
operative**, **+20% leggibilità** di quello che resta.

## Vincoli (NON NEGOZIABILI)

- Non riscrivere il modulo, niente redesign completo, niente pagine o funzionalità nuove.
- Struttura funzionale attuale mantenuta; URL, backend e workflow invariati.
- Modello dati invariato se non strettamente necessario. **Nessuna migration senza fermarsi prima e
  spiegare perché.**
- Nessun nuovo sistema di ruoli: usare solo `maintenance_execute`, `maintenance_planning`, `admin_assets`.
- Niente duplicazioni: prima cercare componenti condivisi esistenti.
- Stile CN HUB, desktop prioritario.
- Non sacrificare funzionalità esistenti per semplificare la UI.
- Prima analizzare, poi modificare.
- Niente refactoring globale del frontend CN HUB.
- Nessuna nuova query ripetuta / N+1: riusare queryset e service esistenti.

## FASE 0 — AUDIT (da consegnare PRIMA di toccare codice)

Stato: `FATTO` (2026-09-09)

### A1 — «Il mio turno» vs «Da fare»

Non sono la stessa pagina: lavorano su **due entità diverse**.

| | Il mio turno | Da fare |
|---|---|---|
| View | `views.py::il_mio_turno` (14870) | `views_maintenance.py::maintenance_da_fare` (296) |
| URL | `/assets/manutenzione/il-mio-turno/` | `/assets/manutenzione/da-fare/` |
| Entità | **WorkOrder** (ODL) `status=OPEN` | **MaintenanceOccurrence** `status=OPEN` |
| Filtro | `assigned_to=me OR assigned_to IS NULL` (coda condivisa) | tutte, con filtri + scope caporeparto |
| Sezioni | Bloccati › Emergenze › Scaduti › Oggi › In corso › Resto | Scadute · 7 giorni · Programmate · In attesa · Esterne |
| Filtri | nessuno | `OccurrenceFilterForm` completo |
| Template | `il_mio_turno.html` (`<style>` locale) | `maintenance_da_fare.html` (`md-*` condivisi) |
| Sidebar | `AssetSidebarButton code=il_mio_turno`, section **MAIN**, top-level, sort 5 (migration 0097) | ramo Manutenzione, sort 10 |

**Nessuna delle due è trasversale a CN HUB**: entrambe vivono in `assets`, sotto
`/assets/manutenzione/`. «Il mio turno» sta fuori dal ramo Manutenzione solo per come è
stata seedata la 0097, non perché sia una home di portale.

Sovrapposizione reale: chi ha ODL aperti li vede in «Il mio turno» come sezioni per urgenza,
e li ritrova in «Da fare» come colonna «Ordine di lavoro» delle occorrenze. Il manutentore ha
quindi **due code** che raccontano lo stesso lavoro da due angoli (ODL vs manutenzione dovuta).

**Proposta**: «Da fare» resta l'unica pagina operativa. Le sezioni ODL-centriche di «Il mio
turno» (Bloccati, Emergenze, In corso) sono l'unica cosa che «Da fare» non sa mostrare →
si assorbono come **blocco «I miei interventi in corso/bloccati»** in testa a Da fare, e la
voce di sidebar `il_mio_turno` si nasconde (`is_visible=False`, migration di soli dati,
reversibile). URL e view restano vivi. **Da confermare prima di procedere.**

### A2 — Dato disponibile alla pressione di INIZIA

- `WorkOrder.started_at` (DateTimeField) — **quando**: c'è.
- **Chi**: NON esiste un campo `started_by`. `WorkOrder.start()` (models.py 2610) salva solo
  `started_at`.
- L'autore però **è già registrato**: entrambe le view che chiamano `start()`
  (`views.py:15226` azione `start`, `views.py:15651` board) creano un `WorkOrderLog` con
  `author=request.user` e nota «Intervento iniziato.» / «Intervento avviato da X (board).».
- `WorkOrder.operational_state` deriva già `IN_PROGRESS` da `started_at`.

Tre strade, **nessuna obbligata**:

- **(1) assegnatario + orario, zero costi** — mostrare `In corso · dalle 09:42` e il nome solo
  se `assigned_to` è valorizzato. Nessuna query nuova (già in `select_related`), nessuna
  migration. Limite: su ODL non assegnato resta «In corso · dalle 09:42» senza nome.
- **(2) intestazione all'avvio** — se `assigned_to` è vuoto quando si preme INIZIA, assegnarlo
  a chi ha premuto, con log esplicito. Copre il 100% dei casi, nessuna migration, nessuna query
  nuova. Tocca `assigned_to` (l'utente ha detto «senza *necessariamente*» modificarlo).
  La coda resta condivisa: si intesta solo chi comincia davvero.
- **(3) `started_by` FK** — dato pulito e permanente, ma **richiede migration**: fuori dal
  perimetro senza tuo via esplicito.

Derivare l'autore dal `WorkOrderLog` è scartato: match su testo libero della nota, fragile.

**Raccomandata: (2)**, con fallback (1) se preferisci non toccare `assigned_to`.

### A3 — Chiusura ODL con occurrence aperte

Oggi (`views.py::workorder_close`, 15671): la chiusura **avviene**, e solo dopo
`messages.warning` avvisa che N manutenzioni raccolte restano dovute. È un avviso
**a cose fatte**, su una pagina già cambiata: si legge di sfuggita.

Nessun automatismo esistente tocca le occurrence alla chiusura (comportamento corretto,
da preservare). Il pannello di registrazione è `_workorder_occurrences.html`.

**Proposta minima**: intercettare nel POST, prima di `workorder.close()`, il caso
`status in (DONE, CANCELED)` + occurrence `OPEN` collegate, e ri-renderizzare `workorder_close.html`
con un pannello di conferma (nessuna nuova URL, nessuna nuova view):

- primaria `[Torna alle manutenzioni]` → ancora `#occorrenze` sul dettaglio ODL;
- secondaria `[Chiudi comunque]` → ripropone il POST con `conferma_occorrenze_aperte=1`.

Tra le due varianti richieste scelgo **(A) gate su `maintenance_planning`** per il «Chiudi
comunque», con **la motivazione richiesta solo a chi non ce l'ha**: chi pianifica sa cosa
lascia dovuto; chi esegue deve dichiararlo, e la motivazione finisce nel `WorkOrderLog` di
chiusura (campo già esistente, nessuna migration). Se preferisci solo (A) o solo (B), lo dici.

### A4 — «ODL in ritardo»: dove compare ancora

Buona parte è già stata bonificata (`views_maintenance.py:642` lo dichiara esplicitamente).
Residui da correggere:

| File | Riga | Testo |
|---|---|---|
| `maintenance_responsabile.html` | 178 | `OdL in ritardo` (KPI) ← **il principale** |
| `maintenance_todo.html` | 135, 190, 202, 350 | `N in ritardo`, `In ritardo` |
| `send_maintenance_reminders.py` | 176, 282 | help del comando e commento |
| `services/dashboard_kpi.py` | 725, 729 | docstring (`soglia di ritardo`, `in ritardo`) |

Già corretti (nessun intervento): `maintenance_responsabile.html` 88/285/287/302
(«aperti da oltre N giorni»), `maintenance_hub.html` («oltre soglia»),
`work_machine_dashboard.html` («oltre soglia N giorni»), `send_maintenance_reminders.py:420`.

**Non toccare** (sono ritardi veri, su una data di scadenza reale):
`maintenance_hub.html:114` (`machines_overdue`), `maintenance_plan_detail.html:163`
(`completed_on > due_date`), `occurrence_complete.html:25`, `recurrence.py`, `models.py:1069`.

`assets_wo_overdue_days` ha già una fonte unica: `maintenance.py::get_workorder_overdue_days`.

### A5 — Componenti UI condivisi esistenti

- **`components/maintenance_domain_styles.html`** — il design system del modulo, namespace
  `md-*`: `md-kpis`/`md-kpi` (+`is-danger|is-warn|is-ok`), `md-badge` (+`badge-danger|warning|info|primary|success|muted`), `md-filters`, `md-tabs`/`md-tab`, `md-section` (+`is-urgent|is-warn`), `md-table`, `md-empty`, `md-groups`, `md-bulk`, `md-form`. **Questo è il posto dove intervenire.**
- **`components/_occurrence_rows.html`** — tabella occorrenze **riusata** da Da fare, Scadenze,
  scheda piano e Cruscotto. Colonne attuali: Scadenza · Piano · Asset · Stato · Ordine di
  lavoro · Azioni. È qui che vive il punto «meno colonne» — ma essendo condiviso fra pagina
  operativa e pagine gestionali serve una **variante via flag di inclusione**, non un secondo file.
- `components/_workorder_occurrences.html`, `components/workorder_checklist.html`.
- **`components/maintenance_ux_v2_styles.html`** — namespace `ux-*`, secondo linguaggio, usato
  da `maintenance_hub`, `maintenance_schedule`, `workorder_detail`, `maintenance_impostazioni`.
- Namespace locali non condivisi: `mc-*` in `maintenance_todo.html`, `oc-*` in
  `_operational_cockpit.html`.
- Template con `<style>` proprio (candidati alla convergenza su `md-*`, con prudenza):
  `il_mio_turno`, `workorder_list`, `workorder_close`, `workorder_form`, `maintenance_history`,
  `maintenance_scadenzario`, `maintenance_suppliers`, `maintenance_rule_list`.

Tre namespace (`md-`, `ux-`, locali) sono già una violazione del pattern canonico CN HUB.
**Non li unifico tutti**: mi limito alle pagine in perimetro.

### A6 — Differenze attuali fra i tre linguaggi

Oggi **non c'è differenziazione**: le pagine operative, gestionali e analitiche usano lo stesso
`md-table` con le stesse metriche tipografiche. «Da fare» e «Scadenze» rendono letteralmente lo
stesso `_occurrence_rows.html`. La Sintesi esiste già (`_vista_cruscotto` + `_sintesi_direzione`,
`?vista=sintesi`, default per chi non ha né `maintenance_execute` né `maintenance_planning`) ma
condivide layout e CTA con il Cruscotto operativo.

### A7 — Punti del brief GIÀ implementati (nessun lavoro)

- **§22 sidebar** — migration 0102/0103: rami `Manutenzione` (Da fare, Scadenze, Interventi,
  Piani, Cruscotto, Storico) e `Configurazione` (Attività, Gruppi asset, Fornitori, Copertura)
  esistono già esattamente come li chiedi.
- **§14 KPI cliccabili** — in «Da fare» le 4 card sono già `<a href="?window=...">`.
- **§19 KPI non affidabili** — `_sintesi_direzione` già dichiara `n.d.` sotto base 10 e mostra
  la copertura dato al posto di MTTR/MTBF/costi.
- **§18 Storico copertura dato** — già corretto (`__gt=0`).
- **§2 rinomina** — già fatta al 70% (vedi A4).
- **§12 empty state** — «Il mio turno» già non stampa le sezioni vuote e le riassume in riga.
- **§4 coda condivisa senza «Prendi in carico» obbligatorio** — già così.

### A8 — §21 Scadenze amministrative in Sintesi: fattibile?

**Sì, senza campi nuovi.** `MaintenanceOccurrence` con
`plan__maintenance_type = MaintenanceInterventionTemplate.TYPE_ADMINISTRATIVE`, `status=OPEN`,
`due_date >= oggi`, ordinate per `due_date`, `[:5]` — `due_date` / `plan.label` /
`asset.asset_tag` + `supplier.ragione_sociale` sono tutti già in `_OCCURRENCE_SELECT`.
Costo: **una query** con `select_related` già impostato.

## DECISIONI PRESE (utente, 2026-09-09)

1. **«Il mio turno» viene assorbita in «Da fare»** — Da fare diventa l'unica pagina operativa.
   Blocco «I miei interventi» (in corso / bloccati / emergenze) in testa; URL e view
   `il_mio_turno` restano vivi; voce di sidebar nascosta con migration **di soli dati**,
   reversibile.
2. **INIZIA intesta l'ODL a chi preme, se non assegnato** — nessuna migration, nessuna query
   nuova, log esplicito. La coda resta condivisa.
3. **Chiusura ODL con occurrence aperte**: `maintenance_planning` chiude comunque con un click;
   chi ha solo `maintenance_execute` deve scrivere una motivazione, che finisce nel
   `WorkOrderLog` di chiusura. Nessun campo nuovo.

## PIANO DELLE MODIFICHE MINIME

### Fase A — semantica (3 file py, 2 template)
- `views_maintenance.py` — nessun cambio logico; solo il KPI in template.
- `maintenance_responsabile.html:178` → «Aperti da oltre {{ wo_overdue_days }} giorni».
- `maintenance_todo.html` 135/190/202/350 → stessa dicitura.
- `send_maintenance_reminders.py` 176/282 e `services/dashboard_kpi.py` 725/729 → testi.
- `models.py::WorkOrder.start(user)` — parametro opzionale; se `assigned_to` è vuoto lo
  valorizza. `views.py:15226` e `views.py:15651` passano `request.user` e loggano.
- `views.py::workorder_close` — gate di conferma **prima** di `close()`; il `messages.warning`
  post-chiusura resta come rete di sicurezza.
- `workorder_close.html` — pannello di conferma (primaria «Torna alle manutenzioni»,
  secondaria «Chiudi comunque» + textarea motivazione per chi non ha `maintenance_planning`).

### Fase B — Da fare / Interventi (operative)
- `maintenance_domain_styles.html` — aggiunta di una **variante operativa**: `md-table--op`
  (righe più alte, titolo 14px, metadata 12-13px), `md-row-flag` (barra verticale sinistra,
  5 toni), `md-badge` normalizzato su 3 famiglie. Nessun namespace nuovo.
- `_occurrence_rows.html` — flag di inclusione `layout="op"`: accorpa in 4 colonne
  (ATTIVITÀ · ASSET · GESTIONE · AZIONE) senza perdere dati; `layout` assente = tabella
  gestionale odierna invariata (Scadenze, scheda piano, Cruscotto non cambiano).
- `maintenance_da_fare.html` — blocco «I miei interventi» in testa, `layout="op"`, empty state
  compatti positivi, gerarchia CTA.
- `workorder_list.html` — gerarchia CTA (Nuovo intervento blu, resto outline), colonne
  accorpate, righe più alte, «In corso — Nome · dalle HH:MM».

### Fase C — Cruscotto
- `maintenance_responsabile.html` — KPI su due livelli (principali/secondari), card cliccabili
  verso le liste già esistenti, riga «Non assegnate» evidenziata, empty state compatti.

### Fase D — Sintesi
- `maintenance_responsabile.html` (ramo `vista=sintesi`) — 4-6 KPI · max 2 grafici · max 2
  tabelle; CTA operative fuori dalla vista; sezione «Prossime scadenze amministrative» (5 righe,
  1 query).
- `views_maintenance.py::_sintesi_direzione` — sola aggiunta della query amministrative.

### Fase E — rifinitura
- Migration dati `0104` per nascondere la voce sidebar `il_mio_turno` (reversibile).
- Consolidamento badge, responsive, verifica N+1, verifica a video light+dark.

## FASE A — Correzioni semantiche

Stato: `FATTO` (2026-09-09)

### A.1 «ODL in ritardo» → «Aperti da oltre N giorni»
Il KPI misura `opened_at` oltre `assets_wo_overdue_days`: è **anzianità**, non una deadline.
Rinominare ovunque, con N dinamico da `assets_wo_overdue_days`. Es. «Aperti da oltre 21 giorni — 4».
Controllare almeno: Cruscotto, Sintesi, Interventi, reminder/email, export, tooltip, testi di aiuto,
manuale/template se generato dal codice.

### A.2 «In corso da …»
Coda condivisa confermata: **NON** introdurre «Prendi in carico» obbligatorio; un intervento non
assegnato resta disponibile alla squadra. Ma quando qualcuno preme INIZIA gli altri devono vederlo:
`IN CORSO — Luca Bova · dalle 09:42`, senza toccare `assigned_to`.
Se il dato non esiste già → **fermarsi e dirlo**, nessuna migration automatica.

### A.3 Chiusura ODL con occurrence aperte
Separazione WorkOrder / MaintenanceOccurrence mantenuta: chiudere un ODL **non** registra le occurrence.
Se restano occurrence da registrare, alla chiusura mostrare:
«Rimangono N manutenzioni non registrate. Chiudendo l'intervento continueranno a risultare dovute.»
- Primaria: `[Torna alle manutenzioni]`
- Secondaria: `[Chiudi comunque]`
Scegliere la soluzione minima migliore tra: (A) «Chiudi comunque» solo con `maintenance_planning`,
(B) conferma esplicita + motivazione. Nessuna modifica automatica alle occurrence.

## FASE B — Da fare / Interventi (pagine OPERATIVE)

Stato: `FATTO` (2026-09-09)

### B.1 «Il mio turno» vs «Da fare»
Se sono due rappresentazioni dello stesso lavoro manutentivo → **una sola pagina operativa: DA FARE**.
Tenere «Il mio turno» separata solo se è davvero una home trasversale a più moduli CN HUB.
Non eliminarla prima di aver spiegato cosa contiene.

### B.2 Gerarchia visiva delle righe
Struttura funzionale invariata (Scadute / Da fare oggi / Prossimi 7 giorni / Assegnate a me +
Cerca, Reparto, Assegnatario, Scadenza, Filtri avanzati). **Nessun KPI nuovo.**
Priorità visiva: 1 attività · 2 asset · 3 urgenza · 4 stato · 5 azione.

```
REVISIONE CARROPONTE
CNC-000019 · DM7 - CN5
SCADUTA DA 131 GIORNI
[ INIZIA ]
```

### B.3 Color coding riga
Indicazione laterale (es. barra verticale sinistra), non solo badge piccoli. Non invasiva.
ROSSO scaduto/critico · ARANCIO oggi/imminente · BLU programmato/futuro · GRIGIO attesa/neutro ·
VERDE completato/conforme.

### B.4 Meno colonne
Non tabelle da ERP. Accorpare: `ATTIVITÀ | ASSET | GESTIONE | AZIONE`, dove GESTIONE contiene es.
«Scaduta · Produzione / Assegnata a Mario Rossi» oppure «In corso — Luca Bova · dalle 09:42».
**Non eliminare dati: spostarli gerarchicamente.**

### B.5 Altezza e leggibilità righe
Aumentare moderatamente altezza riga, spazio verticale, distanza titolo/metadata — **solo** in queste
pagine, non in tutto il portale. Target indicativo: titolo ~14px, metadata 12-13px, header tabella
~12px semibold, badge ≥11-12px, KPI 24-28px. Prima verificare il design system esistente.

### B.6 Gerarchia azioni
BLU = primaria della pagina · ARANCIO = attenzione/eccezione · OUTLINE/BIANCO = secondaria.
Es. Interventi: `+ Nuovo intervento` blu; Campagna / Esporta / Inventario secondari.
Mai quattro CTA che sembrano ugualmente importanti.

### B.7 Badge uniformi (componente condiviso, non uno per template)
- Stato lavoro: Da fare · In corso · In attesa · Eseguita · Chiusa
- Documentazione: Rapporto mancante · Documentata
- Urgenza: Scaduta · Oggi · Prossima
Stessa forma, altezza, peso visivo in tutte le pagine.

### B.8 Empty state
Compatti e positivi: «✓ Nessuna manutenzione scaduta», «✓ Nessun rapporto mancante»,
«✓ Nessun follow-up aperto». Una sezione vuota non deve occupare un blocco grande.

## FASE C — Cruscotto (RESPONSABILE)

Stato: `FATTO` (2026-09-09)

- Mantenere i KPI esistenti, cambiare **peso e disposizione**, non necessariamente il numero.
  - Principali: Scadute · Non pianificate · ODL aperti · Rapporti mancanti
  - Secondari: In scadenza · In attesa · Aperti da oltre N giorni · Follow-up · Conflitti
- KPI cliccabili dove sensato → filtro/drill-down coerente sulla lista sottostante. Niente navigazioni
  sorprendenti.
- Carico manutentori: mantenere Tecnico / Aperte / Scadute / Questa settimana. La riga
  **NON ASSEGNATE** più evidente (gerarchia, non tutta rossa). Nomi cliccabili → «Da fare» filtrato.
- Empty state come B.8.

## FASE D — Sintesi (DIREZIONE / AMMINISTRAZIONE)

Stato: `FATTO` (2026-09-09)

Pagina più pulita del modulo, comprensibile in ~30 secondi.
- Riga 1: 4-6 KPI · Riga 2: max 2 grafici · Riga 3: max 2 tabelle. Fine.
- Indicatori esistenti (Manutenzioni nei tempi, Scadute adesso, Interventi aperti, Copertura
  documentale, Parco con piano, Conflitti). **KPI non affidabile → `n.d.` con spiegazione.**
- Niente CTA operative dominanti (Nuovo intervento, Nuovo piano, Campagna, Registra manutenzione).
  Restano disponibili dove servono, ma non dominano la vista.
- **Solo se ottenibile dai dati esistenti**: sezione «PROSSIME SCADENZE AMMINISTRATIVE», max 5 righe
  (DATA · SCADENZA · ASSET/FORNITORE). Nessuna pagina nuova, nessun campo DB nuovo.
  Se i dati non consentono una lista affidabile → **dirlo e non implementarla**.

## FASE E — Rifinitura

Stato: `FATTO` (2026-09-09)

- **Sidebar**: separazione chiara MANUTENZIONE (Da fare, Scadenze, Interventi, Piani, Cruscotto,
  Storico) vs CONFIGURAZIONE (Attività, Gruppi asset, Fornitori, Copertura, impostazioni tecniche).
  Le categorie inventario non devono competere visivamente. Rami non pertinenti collassati se il
  componente sidebar esistente lo permette. Architettura sidebar CN HUB invariata.
- **Badge/componenti condivisi**: consolidare CSS duplicato del modulo in modo prudente.
- **Responsive**: desktop prioritario; niente overflow inutili; scroll orizzontale nelle tabelle
  gestionali; non trasformare tutte le tabelle in cards; azioni principali sempre visibili; filtri
  avanzati eventualmente offcanvas/collapsible. Smartphone non è caso d'uso primario.
- **Performance**: verificare KPI cliccabili, carico manutentori, conteggi, dato «in corso»,
  scadenze amministrative, nuove annotazioni. Evitare N+1.

## Pagine che NON vanno alleggerite

- **Scadenze** — pagina gestionale, densità tabellare corretta. Mantenere Scadute / 30 gg / 90 gg /
  Tutte future / Amministrative / Ordinarie + filtri completi. **NON trasformare in cards.**
- **Piani** — gestionale, tabella compatta, non dashboard. Colonne: Piano, Tipo, Copertura,
  Periodicità, Ultima esecuzione, Prossima scadenza, Scadute, Stato. Se un dato non è implementato o
  non è affidabile, **non inventarlo**.
- **Storico** — linguaggio da archivio: tabella compatta, filtri chiari, poco colore, niente CTA
  operative dominanti. Mantenere la logica già corretta della copertura dato (durata/costo/fermo poco
  compilati → mostrare la copertura, non statistiche ingannevoli).

## Differenziazione visiva (riepilogo)

| Classe | Pagine | Linguaggio |
|---|---|---|
| Operative | Da fare, Interventi | più spazio, meno colonne, CTA evidenti |
| Gestionali | Scadenze, Piani, Fornitori | tabelle più dense |
| Analitiche | Cruscotto, Sintesi | KPI, grafici, eccezioni |
| Archivio | Storico | tabella compatta, filtri, poco colore |

Non rendere tutte le pagine graficamente identiche.

## Consegna finale attesa

- File modificati
- Riepilogo per pagina
- Query cambiate
- Componenti condivisi introdotti
- Screenshot prima/dopo (verifica a video light + dark, non solo status 200)
- Test effettuati
- Punti deliberatamente non implementati e motivo

## Note di processo

- Sessione in worktree dedicato (`C:\Dev\pn-<tema>`), mai commit dal checkout condiviso.
- CHANGELOG.md e README.md aggiornati d'obbligo a ogni modifica di codice.
- Aggiornare lo `Stato:` di ogni fase in questo file man mano.
