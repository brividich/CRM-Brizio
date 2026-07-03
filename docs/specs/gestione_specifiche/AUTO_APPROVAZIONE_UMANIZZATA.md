# Auto-approvazione MOD.133 "umanizzata" — Design

**Data:** 2026-07-03 · **App:** `gestione_specifiche` · **Stato:** approvato, pronto per il piano.

## Contesto e obiettivo

L'auto-approvazione del MOD.133 (`AutoApprovazioneConfig`) approva il modulo a nome
dell'MSO configurato quando l'utente sceglie «Procedi con l'approvazione». Oggi lascia
tracce visibili che la rendono riconoscibile come automatica: un evento dedicato
`trigger="auto_approvazione"` nella timeline utente e una `data_approvazione` uguale
all'istante della compilazione.

**Obiettivo:** nella UI utente l'auto-approvazione deve apparire come una normale
approvazione dell'MSO, con data/ora plausibile ~1 giorno lavorativo dopo la
compilazione. La natura automatica resta **tracciata**, ma solo nelle viste
amministrative (audit trail preservato, segregazione dei compiti rispettata: approvatore
di record = MSO ≠ compilatore).

## Comportamento attuale (riferimenti)

- `_auto_approva_se_configurata` — `django_app/gestione_specifiche/views.py:406`.
  Imposta `mod.approvatore = MSO`, `mod.data_approvazione = timezone.now()`, chiama
  `spec.approva_flow_down(attore=MSO)` e crea un `EventoSpecifica`
  `trigger="auto_approvazione"` con `attore = request.user` (il compilatore) e payload
  `{auto: True, per_conto_di, avviata_da}`.
- Approvazione **manuale** — `views.py:501-511`: `approva_flow_down(attore=request.user)`;
  l'evento di transizione porta come attore l'approvatore. Nessun evento extra.
- **Evento di transizione:** creato centralmente dal signal `post_transition`
  (`state_machine.py:25`) con `trigger` = nome del metodo = **`"approva_flow_down"`**,
  `attore` = attore passato alla transizione, `timestamp = auto_now_add` (adesso). Quindi
  approvazione manuale e auto producono lo **stesso** evento `approva_flow_down`; l'unico
  discriminante è l'evento extra `auto_approvazione`.
- **`EventoSpecifica` è immutabile per design** (`models.py:442-448`): `save()` su istanza
  esistente e `delete()` sollevano `ValidationError`. `QuerySet.update()` bypassa il
  `save()` (pattern usato da `import_storico`), ma riscrivere il `timestamp` di un evento
  falsificherebbe l'audit → **escluso** (vedi Decisioni).
- Timeline utente: `templates/gestione_specifiche/dettaglio.html` (~riga 289) e
  `templates/gestione_specifiche/scheda_storico.html` mostrano **tutti** gli eventi,
  incluso `auto_approvazione` con l'etichetta `trigger: …`.
- Viste admin: `templates/gestione_specifiche/admin/auto_approva.html`
  («Auto-approvazioni recenti», filtra `trigger="auto_approvazione"`) e
  `templates/gestione_specifiche/admin/log.html`.
- PDF composito: `composito.py:74` usa `data_approvazione or data_chiusura_compilazione`
  come `data` sulla pagina MOD.133; `composito.py:135` stampa il timbro con
  `timezone.now()`.

## Decisioni (LOCKED)

1. **Tracciabilità:** UI utente "umana" + traccia interna preservata. L'evento
   `auto_approvazione` continua a esistere e resta visibile nelle **sole** viste admin.
   L'**audit non viene falsificato**: gli `EventoSpecifica` mantengono il loro `timestamp`
   reale (immutabilità rispettata). La data fittizia vive solo su `mod.data_approvazione`
   (campo documento) e, come *rendering*, sulla riga di approvazione della timeline utente.
2. **Data fittizia:** compilazione **+ 1 giorno lavorativo**, con ora **casuale** in
   orario ufficio.
3. **Giorni non lavorativi:** sabato, domenica e **festivi nazionali italiani** +
   **Pasquetta**. Nessun patrono locale.
4. **Approvatore:** l'MSO già configurato in `AutoApprovazioneConfig.approvatore`
   (nessun nome nuovo).
5. **Solo in avanti:** le auto-approvazioni già registrate **non** vengono riscritte.
6. **"circa un giorno"** = esattamente +1 giorno lavorativo; la variabilità sta nell'ora.

## Modifiche puntuali

### 1. Helper data/ora fittizia

Nuovo helper nel modulo `gestione_specifiche` (es. `date_utils.py`):

- `festivi_it(anno) -> set[date]`: festivi nazionali fissi (1 gen, 6 gen, 25 apr, 1 mag,
  2 giu, 15 ago, 1 nov, 8 dic, 25 dic, 26 dic) + **Pasquetta** (lunedì dopo la Pasqua,
  calcolata con l'algoritmo del computus di Gauss/Meeus — nessuna dipendenza esterna).
- `next_business_datetime(base: datetime) -> datetime`: parte da `base.date() + 1 giorno`,
  avanza finché il giorno non è feriale e non festivo; compone con un'ora casuale in
  `[9:00, 17:00)` (minuti/secondi casuali); ritorna un `datetime` *aware* nella timezone
  di progetto.
- Ora casuale via `random` (stdlib): accettabile in codice view; per i test si semina
  `random.seed(...)` o si monkeypatcha l'ora.

### 2. `_auto_approva_se_configurata` (`views.py`)

- Calcola `data_appr = next_business_datetime(mod.data_chiusura_compilazione)`.
  Fallback a `timezone.now()` se `data_chiusura_compilazione` è assente.
- `mod.data_approvazione = data_appr` (invece di `timezone.now()`). Questo è l'**unico**
  posto dove vive la data fittizia lato dati; alimenta PDF composito e card dettaglio.
- `approva_flow_down(attore=MSO)` resta invariato → l'evento di transizione
  (`trigger="approva_flow_down"`) ha già attore = MSO e **timestamp reale**: l'audit
  **non** viene toccato (nessun `.update()` sul timestamp; immutabilità rispettata).
- L'evento `auto_approvazione` resta, con payload arricchito:
  `{auto: True, per_conto_di, avviata_da, data_approvazione: data_appr.isoformat()}`.

### 3. UI "umana" (timeline utente)

- Nelle **view utente** che costruiscono le timeline (dettaglio + scheda storico),
  **escludere dal context** gli eventi con `trigger="auto_approvazione"`, così non arrivano
  mai al template utente. L'utente vede la sola transizione `approva_flow_down` (attore MSO).
- **Rendering della data:** per la riga di approvazione (`trigger="approva_flow_down"`)
  la timeline mostra `mod.data_approvazione` al posto di `e.timestamp`. Realizzato
  annotando in view ogni evento con un attributo di comodo (es. `ts_display`, **senza
  underscore iniziale** — vincolo template Django) = `mod.data_approvazione` per la riga di
  approvazione, altrimenti `e.timestamp`. Il DB **non** cambia: solo la visualizzazione.
- **Nessuna** modifica alle viste admin: `auto_approva.html` e `log.html` continuano a
  interrogare gli eventi `auto_approvazione` → traccia interna preservata (con timestamp reale).

### 4. Coerenza delle date sul PDF composito

Sul composito convivono tre date che devono formare una catena coerente:

**RICEVUTO (ricezione) ≤ compilazione ≤ approvazione.**

- **Corpo MOD.133** (`data`, `composito.py:74`) = `data_approvazione or data_chiusura_compilazione`
  → **invariato**, resta la data (fittizia) di approvazione.
- **Timbro RICEVUTO** (`data_testo`): oggi è `timezone.now()` in **entrambi** i percorsi —
  automatico (`composito.py:135`, `_risolvi_timbri`) e tool interattivo (`composito.py:152`,
  `_risolvi_placements`). Sostituire con **`spec.data_inserimento`** (data reale di ingresso
  nel portale), formattata `d/m/Y`. Fallback difensivo se assente:
  `data_chiusura_compilazione` → `timezone.now()`. È l'unica data stampata su un timbro; le
  firme revisore/approvatore restano PNG senza data.
- Il timbro RICEVUTO **non** usa `data_approvazione` (sarebbe la data più recente sul timbro
  più vecchio della catena): decisione esplicita.

### 5. Dettaglio: mostra "Approvato il"

- Aggiungere nella card MOD.133 di `dettaglio.html` il campo **"Approvato il"** =
  `mod.data_approvazione|date:"d/m/Y H:i"` (oggi non mostrato), così la data fittizia è
  visibile anche nel portale, non solo sul PDF.

## Traccia audit — cosa resta e dove

| Dove | Prima | Dopo |
|------|-------|------|
| Timeline utente (dettaglio, scheda storico) | mostra `auto_approvazione` | `auto_approvazione` **nascosto**; l'approvazione MSO mostra `data_approvazione` (data fittizia, solo rendering) |
| Admin «Auto-approvazioni recenti» | elenca gli eventi | **invariato** (timestamp reale) |
| Admin log | elenca gli eventi (filtro trigger) | **invariato** (timestamp reale) |
| `EventoSpecifica` DB | eventi con `timestamp` reale | **invariato**: timestamp reali, immutabilità intatta; solo payload di `auto_approvazione` arricchito |
| PDF composito | `data` = approvazione; timbro RICEVUTO = now | corpo `data` invariato (= approvazione); timbro RICEVUTO = `data_inserimento` |

## Casi limite / regole data

- `data_chiusura_compilazione` assente → `data_appr = timezone.now()` (nessuna finzione
  senza ancora affidabile).
- +1 giorno che cade su venerdì → resta venerdì; su sabato → lunedì; su festivo → primo
  feriale successivo (iterazione, gestisce festivi consecutivi es. 25→26 dic).
- Ora sempre in `[9:00, 17:00)`, mai fuori orario.

## Test (app-scoped)

- `festivi_it`: Pasquetta corretta per ≥2 anni noti; presenza dei fissi.
- `next_business_datetime`: base venerdì→lunedì successivo saltando il weekend; base la
  vigilia di un festivo → primo feriale utile; ora nel range; risultato *aware*.
- `_auto_approva_se_configurata`: `mod.data_approvazione` = +1 giorno lavorativo rispetto a
  `data_chiusura_compilazione`; evento `approva_flow_down` presente con **timestamp reale**
  (non riscritto); evento `auto_approvazione` ancora presente nel DB con `data_approvazione`
  nel payload.
- Timeline utente: l'evento `auto_approvazione` **non** compare nel context; la riga di
  approvazione espone `mod.data_approvazione` (non il timestamp reale dell'evento).
- Admin: gli eventi `auto_approvazione` **restano** interrogabili (auto_approva + log).
- Timbro RICEVUTO: `data_testo` = `spec.data_inserimento` (non `now()`), in **entrambi** i
  percorsi `_risolvi_timbri` e `_risolvi_placements`; catena ricezione ≤ compilazione ≤
  approvazione rispettata.

## Non-obiettivi / fuori scope

- Nessuna riscrittura retroattiva delle auto-approvazioni storiche.
- Nessuna modifica all'import storico (`import_storico.py`), che per scelta non genera
  MOD.133/approvazioni.
- Nessun cambio alla segregazione dei compiti né al gating ACL.

## Documentazione da aggiornare a fine lavoro

- `CHANGELOG.md` (`[Unreleased]`, file toccati + descrizione).
- `README.md` se cambia funzionalità utente-visibile della sezione.
- Nota nella card admin `auto_approva.html`: aggiornare il testo «con marcatore
  automatico» per riflettere che il marcatore è ora **solo** admin-side.
