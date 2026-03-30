# Manuale Amministratore — Navigazione, Pulsanti e Permessi

> Portale Novicrom · Aggiornato: marzo 2026 (v0.8.5)
> Percorso admin: **Admin Portale** (voce nel menu principale)

---

## Indice

1. [Panoramica del sistema](#1-panoramica-del-sistema)
2. [Pulsanti (sistema legacy)](#2-pulsanti-sistema-legacy)
3. [Topbar Live — editor rapido navigazione](#3-topbar-live--editor-rapido-navigazione)
4. [Navigation Builder — sistema nuovo](#4-navigation-builder--sistema-nuovo)
5. [Permessi — gestione accessi](#5-permessi--gestione-accessi)
6. [Wizard: crea pulsante](#6-wizard-crea-pulsante)
7. [Wizard: configura ruolo](#7-wizard-configura-ruolo)
8. [Flusso consigliato per operazioni comuni](#8-flusso-consigliato-per-operazioni-comuni)
9. [Riferimento campi](#9-riferimento-campi)

---

## 1. Panoramica del sistema

Il portale usa **due sistemi di navigazione** paralleli:

| Sistema | Dove si gestisce | Scopo |
|---------|-----------------|-------|
| **Pulsanti** (legacy) | Topbar Live / Gestione Pulsanti | Tabella storica del portale originale. Ancora usata per la topbar e per il sistema ACL (permessi). |
| **Navigation Builder** (nuovo) | Navigation Builder | Nuovo sistema Django per topbar, subnav, sidebar, link di pagina e **barra interna admin**. Può importare i pulsanti legacy. |

> **Regola pratica:** per aggiungere voci al menu usa il **Navigation Builder**. Per modificare i permessi ACL usa **Gestione Permessi** (che si basa sempre sui Pulsanti legacy).

---

## 2. Pulsanti (sistema legacy)

### Cos'è un pulsante

Un **pulsante** è l'unità base del sistema ACL. Rappresenta un'azione o una sezione del portale. A ogni pulsante corrispondono:
- Una voce nel menu (se abilitato)
- Un permesso verificabile (il sistema controlla se l'utente ha accesso a quel codice/modulo)

### Dove si gestiscono

**Admin Portale → Gestione Pulsanti**

La pagina mostra una griglia di card, una per ogni modulo. Ogni card contiene i pulsanti del modulo con i loro toggle.

### Campi principali di un pulsante

| Campo | Significato |
|-------|-------------|
| `codice` | Identificatore univoco (slug). Non modificare dopo averlo usato nei permessi. |
| `modulo` | Gruppo di appartenenza (es. `assenze`, `anomalie`, `assets`). Usato per raggruppare i permessi nella UI. |
| `label` / `nome_visibile` | Testo mostrato nel menu all'utente. |
| `url` | Destinazione del link. Usa il formato `route:nome_route` per route Django interne. |
| `visible_topbar` | Se spuntato, il pulsante compare nella barra in alto. |
| `enabled` | Se non spuntato, il link è disabilitato (grigio) ma ancora visibile. |
| `ui_slot` | Posizione nel layout (`topbar`, `toolbar`, ecc.). |
| `ui_section` | Sezione di raggruppamento visiva (es. `dashboard`, `assenze`). |
| `ui_order` | Numero d'ordine nel menu (più basso = mostrato prima). |

### Toggle nell'interfaccia

- **Toggle verde arancione** = funzionalità attiva
- **Toggle grigio** = funzionalità disattiva
- **Toggle giallo "parziale"** = il modulo è parzialmente abilitato (solo alcuni pulsanti attivi)
- La riga diventa semi-trasparente durante il salvataggio (stato `saving`)

---

## 3. Topbar Live — editor rapido navigazione

### Percorso

**Admin Portale → Topbar Live**

### A cosa serve

Interfaccia semplificata per modificare rapidamente la topbar senza uscire dalla pagina. Ideale per riordinare le voci o attivare/disattivare link in tempo reale.

### Come usarla

1. Ogni riga rappresenta un pulsante (legacy)
2. Modifica direttamente i campi nella riga
3. Premi **Salva** sulla riga per applicare la modifica
4. I toggle `Topbar` e `Attivo` si salvano automaticamente al cambio senza bisogno di premere Salva

### Riordinare le voci

- Usa i pulsanti **Su / Giù** per spostare una voce
- In alternativa, modifica manualmente il campo **Ord UI** e premi Salva
- **Rinumera ordine UI** ricalcola automaticamente tutti i numeri in sequenza multipla di 10

### Filtri disponibili

| Filtro | Descrizione |
|--------|-------------|
| Ricerca | Cerca per nome, codice, modulo o URL |
| Sezione UI | Filtra per sezione (`dashboard`, `assenze`, ecc.) |
| Vista | "Solo topbar" mostra solo le voci con `visible_topbar = ON` |

### Catalogo route

In fondo alla pagina c'è il **Catalogo route Django** con tutti gli URL interni disponibili. Per i link usa il formato `route:nome_route` nel campo Link (es. `route:dashboard_home`).

> **Nota:** la voce Dashboard viene sempre garantita anche se non presente nel catalogo.

---

## 4. Navigation Builder — sistema nuovo

### Percorso

**Admin Portale → Navigation Builder**

### A cosa serve

Gestione centralizzata del menu senza modificare codice. Supporta topbar, subnav, sidebar e link di pagina. Le modifiche sono **immediate** e possono essere versionatedattraverso snapshot.

### Struttura di una voce

| Campo | Significato |
|-------|-------------|
| `Codice` | Slug univoco. Se vuoto, viene generato dalla label. |
| `Label` | Testo visualizzato nel menu *(obbligatorio)* |
| `Sezione` | Dove appare: `topbar`, `subnav`, `sidebar`, `page`, `admin_subnav` |
| `Gruppo subnav` | Solo per sezione `subnav` — codice del gruppo di appartenenza (es. `assenze`, `dashboard`, `anagrafica`). La subnav appare quando l'utente è nella sezione corrispondente. |
| `Gruppo` | Per sezione `admin_subnav` — nome del gruppo visivo (es. `accessi`, `navigazione`, `sistema`). Determina i separatori orizzontali nella barra admin. |
| `Ordine` | Numero d'ordine (basso = prima). Si può anche riordinare trascinando. |
| `Route name` | Route Django interna *(consigliato per link interni)*. Si seleziona dall'elenco autocomplete. |
| `URL path` | URL diretto o link esterno — usarlo solo se non c'è una route disponibile. |
| `Ruoli abilitati` | Limita la voce a specifici ruoli ID. Nessuna selezione = visibile a tutti. |
| `Visibile` | La voce compare nel menu |
| `Attivo` | Il link è cliccabile |
| `Nuova tab` | Apre in una nuova scheda del browser |

### Creare una nuova voce

1. Compila il form **Nuova voce di navigazione** in cima alla pagina
2. Il campo `Codice` è opzionale (viene autogenerato)
3. Per link interni: usa **Route name** (l'elenco autocomplete mostra tutte le route disponibili)
4. Per `Sezione = subnav`: inserire il **Gruppo subnav** (es. `assenze`) — indica a quale sezione del portale appartiene la subnav
5. Per `Sezione = admin_subnav`: la voce comparirà nella barra interna dell'admin portale. Inserire il **Gruppo** (es. `accessi`, `navigazione`, `sistema`, `hub`) per il separatore visivo. Non serve configurare i **Ruoli abilitati** — la barra admin è visibile solo agli amministratori di sistema.
6. Premi **Crea voce**

### Modificare le voci esistenti

La tabella permette modifica inline:
- Clicca direttamente sulle celle per modificare i valori
- Premi **Salva** sulla riga per applicare
- Per riordinare: trascina le righe con l'handle `⠿` oppure modifica il campo `Ord.`
- Usa i filtri per sezione o ricerca testo per trovare rapidamente una voce

### Ruoli abilitati (visibilità per ruolo)

- Apri la tabella dei ruoli cliccando su **Ruoli Legacy** (collassabile in cima)
- Usa gli **ID numerici** nel campo `Ruoli abilitati`
- Tieni premuto `Ctrl` (o `Cmd` su Mac) per selezionare più ruoli
- Nessuna selezione = voce visibile a tutti i ruoli

### Publish / Rollback snapshot

> Le modifiche alle voci sono **immediate** ma non "certificate". Uno snapshot è un salvataggio versionato dell'intera configurazione.

**Per pubblicare uno snapshot:**
1. Inserisci una nota descrittiva (es. *"Menu marzo 2026 – aggiunto link RENTRI"*)
2. Premi **Pubblica snapshot**

**Per ripristinare:**
1. Seleziona la versione dall'elenco `Ripristina snapshot`
2. Premi **Ripristina** — la configurazione corrente viene **sostituita completamente**

> ⚠️ Prima di operazioni rischiose (come "Sovrascrivi tutto dal legacy"), pubblica sempre uno snapshot.

### Import da legacy

| Modalità | Effetto |
|----------|---------|
| **Merge con legacy** *(consigliato)* | Aggiunge le voci legacy non ancora presenti, senza toccare quelle già configurate |
| **Sovrascrivi tutto dal legacy** | Elimina tutto e ricrea dal legacy da zero — **irreversibile senza snapshot** |

### Redirect Legacy

Intercetta vecchi URL del portale legacy e reindirizza verso i nuovi percorsi Django.

**Campi:**

| Campo | Descrizione |
|-------|-------------|
| `Legacy path` | Vecchio URL da intercettare (es. `/admin/vecchio-path`) |
| `Target route` | Route Django di destinazione (autocomplete disponibile) |
| `Target path` | URL path diretto come alternativa alla route |
| `Attivo` | Deseleziona per disabilitare temporaneamente senza eliminare |

**Uso tipico:** durante la migrazione dal sistema legacy, crea un redirect per ogni vecchio URL in modo che i link salvati nei segnalibri continuino a funzionare.

### State Preview (JSON)

Mostra in tempo reale il JSON dell'intera configurazione corrente — identico a quello salvato in uno snapshot. Utile per debug o backup manuale.

---

## 5. Permessi — gestione accessi

### Percorso

**Admin Portale → Permessi**

### Modalità: per Ruolo o per Utente

| Tab | Effetto |
|-----|---------|
| **Per Ruolo** | Imposta i permessi standard per tutti gli utenti con quel ruolo |
| **Per Utente** | Imposta un override personale che sovrascrive il ruolo per quel singolo utente |

### Come funziona la griglia permessi

La griglia mostra una card per ogni **modulo**, con all'interno i singoli **pulsanti**.

```
┌─ Modulo: assenze ─────────────────── [●] toggle modulo ─┐
│  richiesta_assenza    /assenze/richiesta    [●]           │
│  gestione_assenze     /assenze/gestione     [○]           │
│  calendario_assenze   /assenze/calendario   [●]           │
└─────────────────────────────────────────────────────────┘
```

- **Toggle modulo** (in testa alla card): attiva/disattiva tutti i pulsanti del modulo in un colpo solo
- **Toggle pulsante** (riga): controlla il singolo pulsante
- Badge **"parziale"** = solo alcuni pulsanti del modulo sono attivi
- Il toggle modulo diventa **giallo/indeterminate** quando lo stato è parziale

### Azioni bulk (solo modalità Ruolo)

| Pulsante | Effetto |
|----------|---------|
| **Tutto ON** | Attiva tutti i moduli e tutti i pulsanti per il ruolo |
| **Tutto OFF** | Disattiva tutto (chiede conferma) |
| **Reset ruolo** | Elimina tutti i permessi del ruolo (torna allo stato "nessuna impostazione") |
| **Copia da** + **Copia** | Copia i permessi da un altro ruolo selezionato |

### Override per utente

Quando sei nella tab **Per Utente**, ogni toggle imposta un override personale per quell'utente. L'override ha priorità sul ruolo. Utile per:
- Dare accesso temporaneo a una funzione senza cambiare il ruolo
- Bloccare un singolo utente su una funzione specifica

### Permessi effettivi

In **Gestione Utenti**, per ogni utente c'è il pulsante **Permessi effettivi** che mostra la lista completa dei permessi finali (combinazione ruolo + override personale).

---

## 6. Wizard: crea pulsante

### Percorso

**Admin Portale → Pulsanti → Wizard nuovo pulsante**
(oppure dall'intestazione della card modulo)

### Step 1 — Dati base

Compila i campi principali:
- **Modulo** — gruppo di appartenenza (scegli da quelli esistenti o creane uno nuovo)
- **Codice/Azione** — identificatore slug (es. `gestione_assenze`). Non deve contenere spazi.
- **Label** — testo mostrato nel menu
- **URL** — destinazione (usa `route:nome_route` per route interne)

### Step 2 — Permessi iniziali

Per ogni ruolo puoi impostare il permesso di accesso al nuovo pulsante:
- **Preset rapido:** scegli tra "Tutti ON", "Tutti OFF", "Solo Admin", ecc.
- **Manuale:** espandi il ruolo e imposta singolarmente `can_view`
- Ogni riga mostra il nome del ruolo e un checkbox per accesso

### Step 3 — Riepilogo e salvataggio

Verifica tutti i dati prima di salvare. Il pulsante viene creato e i permessi applicati in un'unica operazione.

> Dopo la creazione il pulsante è disponibile immediatamente nella pagina **Permessi** e nella **Topbar Live**.

---

## 7. Wizard: configura ruolo

### Percorso

**Admin Portale → Permessi → Apri Wizard** (pulsante in alto a destra dopo aver selezionato un ruolo)

### Step 1 — Seleziona ruolo

Clicca sul ruolo da configurare dall'elenco.

### Step 2 — Configura permessi modulo

Stessa griglia di Gestione Permessi ma in formato wizard:
- **Toggle modulo** per attivare/disattivare l'intero gruppo
- **Pulsanti ON / OFF** per configurazione rapida dentro la card
- Espandi per vedere e configurare i singoli pulsanti

### Step 3 — Riepilogo e salvataggio

Mostra tutti i cambiamenti da applicare. Premi **Salva configurazione ruolo** per confermare.

> Il wizard è ideale per configurare un ruolo appena creato da zero.

---

## 8. Flusso consigliato per operazioni comuni

### Aggiungere una voce al menu principale (topbar)

1. **Navigation Builder** → *Nuova voce di navigazione*
2. Sezione: `topbar`
3. Route name: scegli dall'autocomplete
4. Ordine: inserisci un numero (es. 50 per metterla a metà)
5. Crea voce
6. Verifica il risultato nel menu — se la voce è nell'ordine sbagliato, trascina dalla tabella o modifica il campo `Ord.`
7. (Facoltativo) Pubblica snapshot con una nota descrittiva

### Aggiungere una subnav a un modulo

1. **Navigation Builder** → *Nuova voce di navigazione*
2. Sezione: `subnav`
3. **Gruppo subnav**: inserisci il codice della sezione (es. `assenze`, `anagrafica`, `assets`)
4. Route name: la pagina specifica
5. Crea voce
6. La subnav apparirà automaticamente quando l'utente è nella sezione corrispondente

### Limitare una voce a un ruolo specifico

1. **Navigation Builder** → trova la voce nella tabella
2. Campo **Ruoli**: seleziona i ruoli abilitati (Ctrl+click per più ruoli)
3. Premi **Salva** sulla riga

### Dare accesso a un modulo per un intero ruolo

1. **Permessi** → tab **Per Ruolo** → seleziona il ruolo → Seleziona
2. Trova la card del modulo e attiva il **toggle modulo** (attiva tutti i pulsanti in un colpo)
3. Oppure attiva i singoli pulsanti
4. Il salvataggio è automatico (non serve premere Salva)

### Creare un nuovo ruolo e configurarlo

1. **Gestione Utenti** o sistema Django admin: crea il ruolo
2. **Permessi** → tab **Per Ruolo** → seleziona il nuovo ruolo
3. Se hai un ruolo simile: usa **Copia da** → seleziona il ruolo sorgente → Copia
4. Poi aggiusta manualmente le differenze
5. In alternativa: usa **Wizard configura ruolo** per procedura guidata

### Rollback dopo un errore di configurazione

1. **Navigation Builder** → sezione *Publish / Rollback snapshot*
2. Seleziona lo snapshot precedente all'errore
3. Premi **Ripristina** → conferma
4. La configurazione viene ripristinata immediatamente per tutti gli utenti

### Redirect di un vecchio URL

1. **Navigation Builder** → sezione *Redirect Legacy*
2. `Legacy path` = vecchio URL (es. `/vecchio/percorso/`)
3. `Target route` = nome route Django di destinazione (usa l'autocomplete)
4. Aggiungi redirect
5. Verifica aprendo il vecchio URL nel browser

---

## 9. Riferimento campi

### Pulsante legacy — campi completi

| Campo | Tipo | Note |
|-------|------|------|
| `id` | Numero | Auto-generato |
| `codice` | Slug | Identificatore univoco, usato dal sistema ACL |
| `modulo` | Testo | Gruppo funzionale (es. `assenze`, `assets`) |
| `nome_visibile` | Testo | Etichetta mostrata all'utente |
| `url` | Testo | Destinazione — usa `route:nome_route` per Django |
| `ui_slot` | Testo | `topbar`, `toolbar` ecc. |
| `ui_section` | Testo | Sezione di raggruppamento |
| `ui_order` | Numero | Ordine di visualizzazione |
| `visible_topbar` | Bool | Mostra nella topbar |
| `enabled` | Bool | Link attivo/disattivo |

### Voce Navigation Builder — campi completi

| Campo | Tipo | Note |
|-------|------|------|
| `codice` | Slug | Auto-generato se vuoto |
| `label` | Testo | *(obbligatorio)* |
| `section` | Enum | `topbar` / `subnav` / `sidebar` / `page` |
| `parent_code` | Testo | Solo subnav: codice sezione (es. `assenze`) |
| `order` | Numero | Ordine nel menu |
| `route_name` | Testo | Route Django — usa l'autocomplete |
| `url_path` | Testo | URL diretto o link esterno |
| `role_ids_csv` | CSV | ID ruoli abilitati separati da virgola |
| `is_visible` | Bool | Mostra nel menu |
| `is_enabled` | Bool | Link cliccabile |
| `open_in_new_tab` | Bool | Apri in nuova scheda |
| `description` | Testo | Nota interna, non mostrata agli utenti |

### Codici sezione subnav — valori comuni

| Codice | Sezione attivata in |
|--------|---------------------|
| `dashboard` | Dashboard principale |
| `assenze` | Modulo Assenze |
| `anagrafica` | Modulo Anagrafica |
| `admin_portale` | Admin Portale |
| `assets` | Modulo Assets |
| `notizie` | Modulo Notizie |
| `tasks` | Modulo Tasks |
| `tickets` | Modulo Tickets |
| `rentri` | Modulo RENTRI |
| `timbri` | Modulo Timbri |
| `dpi` | Modulo DPI |
| `procedure_refresh` | Modulo Presa Visione Procedure |
| `diario_preposto` | Modulo Diario Preposto |
| `rilevazione_incidenti` | Modulo Rilevazione Incidenti |
| `automazioni` | Modulo Automazioni |

---

## 10. Categorie Navigazione — colori topbar

**Admin Portale → Hub Tools → Categorie** (`/admin-portale/hub/categorie/`)

### Descrizione categorie

Le categorie permettono di raggruppare le voci della topbar per area funzionale e assegnare un colore identificativo. Quando l'utente naviga in un modulo appartenente a una categoria, il background della topbar assume il colore della categoria.

### Gestione categorie

- Crea una categoria: inserisci nome, key slug e colore hex nel form in cima alla pagina
- Modifica il colore: usa il color picker sulla riga esistente, si salva automaticamente
- Ordine: modifica il campo `Ordine` e premi Salva — categorie con ordine più basso appaiono prima
- Elimina: pulsante Elimina sulla riga (le voci assegnate tornano senza categoria)

### Assegnare una voce a una categoria

Dalla stessa pagina, ogni voce topbar ha un dropdown "Categoria" — seleziona la categoria e si salva immediatamente. La modifica è visibile a tutti gli utenti al prossimo caricamento pagina.

### Comportamento nel menu

Le voci con la stessa categoria vengono raggruppate sotto un pulsante `[NOME CATEGORIA ▾]` con menu a tendina. Le voci senza categoria restano link diretti nella topbar.

> Prima di eliminare una categoria usata da molte voci, pubblica uno snapshot nel Navigation Builder come backup.

---

## 11. Monitoring — dashboard issue applicative

**Admin Portale → Monitoring** (`/admin-portale/monitoring/`) — richiede profilo admin.

### Funzionalità monitoring

Il sistema di monitoring registra automaticamente errori, eccezioni non gestite e risposte anomale del portale. Come amministratore puoi:

- Vedere tutte le issue aperte, filtrate per severità, modulo, stato e data
- Cambiare lo stato di un'issue (`new → triage → in_progress → resolved/ignored`)
- Leggere il traceback completo e il contesto della request che ha causato l'errore
- Vedere le ultime segnalazioni manuali degli utenti (pulsante "Segnala problema" nel topnav)
- Monitorare i job automatici: stato, fallimenti consecutivi, job missing o in ritardo

### Deduplicazione issue

Lo stesso errore che si ripete non genera issue duplicate — incrementa il contatore occorrenze e aggiorna il timestamp `last_seen_at`. Un'issue con molte occorrenze è più urgente di una con poche.

### Alert email

Le issue con severity `critical` inviano un'email di notifica (con rate-limit: massimo 1 per ora per tipologia di errore). Configurabile via impostazioni `MONITORING_*` nel `.env`.

---

Fine manuale — Portale Novicrom Admin (v0.8.5)
