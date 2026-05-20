# Anagrafica HR Dipendenti — Documento di sviluppo

> **Stato**: Sprint 1 + 2a + 3 completati  
> **Versione app al kickoff**: 1.0.2 (2026-05-19)  
> **Ultimo aggiornamento**: 2026-05-20

Documento vivo che traccia l'implementazione della gestione HR strutturata dei dipendenti nel modulo `anagrafica`. Usato come filo conduttore tra sessioni di sviluppo.

---

## Indice

1. [Contesto e obiettivo](#1-contesto-e-obiettivo)
2. [Architettura scelta](#2-architettura-scelta)
3. [Implementato — Sprint 1 (anagrafica HR a livelli)](#3-implementato--sprint-1-anagrafica-hr-a-livelli)
4. [Implementato — Sprint 2a (storico contrattuale + cambiamenti organizzativi)](#4-implementato--sprint-2a-storico-contrattuale--cambiamenti-organizzativi)
5. [Implementato — Sprint 3 (retribuzioni: import CSV + data-entry manuale)](#5-implementato--sprint-3-retribuzioni-import-csv--data-entry-manuale)
6. [Implementato — Extra (pannello impostazioni unificato)](#6-implementato--extra-pannello-impostazioni-unificato)
7. [Struttura dati](#7-struttura-dati)
8. [Permessi e ACL](#8-permessi-e-acl)
9. [File coinvolti](#9-file-coinvolti)
10. [Roadmap futura](#10-roadmap-futura)
11. [Decisioni tecniche e note](#11-decisioni-tecniche-e-note)

---

## 1. Contesto e obiettivo

Prima di questo lavoro, la scheda dipendente mostrava solo i dati minimali della tabella legacy `anagrafica_dipendenti` (SQL Server, unmanaged): nome, cognome, matricola, reparto, mansione, email, username.

**Obiettivo**: costruire attorno alla tabella legacy una gestione HR completa, strutturata in livelli di visibilità distinti:

| Livello | Chi vede | Dati |
|---------|----------|------|
| Base | Tutti (con accesso anagrafica) | Dati legacy: nome, cognome, reparto, mansione |
| Admin | Admin portale | Anagrafica aziendale + anagrafica civile (non sensibile) + storico cambiamenti organizzativi |
| HR | Utenti con permesso HR dedicato | IBAN, codice fiscale, categorie protette/disabili, storico contrattuale CCNL, retribuzioni |

**Principio guida**: nessuna modifica alla tabella legacy. Tutti i nuovi dati vivono in tabelle Django aggiuntive collegate tramite `legacy_anagrafica_id` (e in alcuni casi anche `tax_code` come chiave secondaria di lookup quando il legacy_id non è disponibile).

---

## 2. Architettura scelta

### Bridge pattern (identico a DipendenteRuoloOperativo, DipendenteQualifica)

```
anagrafica_dipendenti (SQL Server, unmanaged)
         │
         │  legacy_anagrafica_id = IntegerField (unique per le anagrafiche
         │                        1:1, indexed per gli storici 1:N)
         │
         ├── DipendenteAnagraficaCivile         (1:1, managed)
         ├── DipendenteAnagraficaAziendale      (1:1, managed)
         ├── DipendenteCambiamentoOrganizzativo (1:N, managed) ← Sprint 2a
         ├── StoricoContratto                   (1:N, managed) ← Sprint 2a
         ├── ImportazioneRetributiva            (1:N, managed) ← Sprint 3
         │   └── VoceRetributiva                (1:N, managed) ← Sprint 3
         └── (futuro) altre dimensioni
```

### Singleton permission (identico ad AnagraficaStatPermission)

```python
AnagraficaHRPermission.get_instance()
# accesso: TUTTI | ADMIN | RUOLI
# ruolo_ids: JSONField → lista ID ruolo ACL v2 se accesso=RUOLI
```

### Decisione architetturale chiave

Tra il rilascio iniziale e l'implementazione degli sprint 2a/3 è cambiato l'approccio. Il documento originale ipotizzava un singolo log generico `DipendenteStoricoCambiamento` per tutti i campi chiave (mansione, reparto, area, ruolo, contratto, livello). In corso d'opera abbiamo **separato** le dimensioni:

- **Storico CCNL/inquadramento** → `StoricoContratto` a periodi (`data_inizio`/`data_fine`), import-driven da CSV studio paghe + CRUD manuale.
- **Storico cambiamenti organizzativi interni** → `DipendenteCambiamentoOrganizzativo` a log per campo (mansione, reparto, area, ruolo aziendale), generato automaticamente dagli hook delle view.
- **Retribuzione** → import CSV mensile dallo studio paghe (`ImportazioneRetributiva` + `VoceRetributiva`) con classificazione automatica `fisso/variabile/totale/altro` + **data-entry manuale** (Sprint 3 follow-up) per override puntuali.

Motivazione: lo storico CCNL ha una semantica diversa (periodi contigui con auto-chiusura del periodo "in corso" quando ne inizia uno nuovo) rispetto al log organizzativo interno (modifiche puntuali con vecchio→nuovo). Le retribuzioni sono naturalmente import-driven perché lo studio paghe è la sorgente autorevole; il manuale serve solo per correzioni e bonus una-tantum.

---

## 3. Implementato — Sprint 1 (anagrafica HR a livelli)

### 3.1 Modelli

- [x] `DipendenteAnagraficaCivile` — dati personali, residenza, domicilio, contatti privati, IBAN, CF, disabilità
- [x] `DipendenteAnagraficaAziendale` — area, ruolo aziendale, taglie DPI, contratto, contatti aziendali, privacy
- [x] `AnagraficaHRPermission` — singleton con `get_instance()`, accesso configurabile da admin Django / pannello impostazioni
- [x] `AreaAziendale` — catalogo dropdown per campo `area`
- [x] `RuoloAziendale` — catalogo dropdown per campo `ruolo_aziendale`
- [x] Migrazioni `0005` e `0006`

### 3.2 Form

- [x] `AnagraficaCivileForm` — clean su `codice_fiscale` (uppercase) e `iban` (strip + uppercase)
- [x] `AnagraficaAziendaleForm` — widget dinamico `Select` per `area` e `ruolo_aziendale` dai cataloghi, fallback al valore corrente se non più nel catalogo attivo

### 3.3 Views

- [x] `dipendente_detail` — arricchita con `civile`, `aziendale`, `can_hr`, `form_civile`, `form_aziendale`, storici
- [x] `dipendente_anagrafica_civile_save` — POST, gate admin
- [x] `dipendente_anagrafica_aziendale_save` — POST, gate admin, con hook storicizzazione area/ruolo aziendale (Sprint 2a)
- [x] `dipendenti_report` — GET + CSV export (`?format=csv`), filtri: q/reparto/area/contratto/consenso/cat_protetta; CSV esclude i campi HR
- [x] `dipendenti_list` — filtri area e contratto, link "Report"
- [x] `dipendente_create` — form a sezioni collassabili, cascade create legacy → civile → aziendale → primo `StoricoContratto`

### 3.4 Template

- [x] `dipendente_detail.html` — card "🏢 Aziendale" / "🪪 Civile" / "🔒 HR" + form inline toggle, **edit inline reparto** (Sprint 2a) accanto a mansione
- [x] `dipendenti_list.html` — pulsante "+ Nuovo dipendente", filtri area/contratto, link Report
- [x] `dipendente_create.html` — 4 card collassabili con macro-aree titolate
- [x] `dipendenti_report.html` — filtri avanzati, tabella, export CSV
- [x] `index.html` — hero con "+ Nuovo dipendente"

---

## 4. Implementato — Sprint 2a (storico contrattuale + cambiamenti organizzativi)

Lo sprint è stato implementato **in due modelli separati**:

### 4.1 `StoricoContratto` — CCNL, livello, qualifica professionale (HR-visibile)

Approccio "snapshot a periodi" con `data_inizio`/`data_fine` (null = in corso).

- [x] Modello `StoricoContratto` con `legacy_anagrafica_id` / `tax_code` (dual-path: cerca prima per id, fallback per CF)
- [x] Cataloghi `TipologiaContratto` (sostituisce le `CONTRATTO_CHOICES` hardcoded) e `LivelloContrattuale` (A1, B3, … DIR con descrizione)
- [x] **Import CSV massivo** `/anagrafica/contratti/` (solo admin): formato `Codice fiscale;Data Inizio;Data Fine;Tipo di contratto;Qualifica;Livello;CCNL;Descrizione livello`, righe stesso (CF, data inizio, data fine) aggregate in unico record, `update_or_create` per re-import idempotente, encoding auto-detect
- [x] **CRUD manuale** `dipendente_contratto_add/edit/delete`: auto-chiusura del record "in corso" quando ne inizia uno nuovo
- [x] **Card "📋 Contratto & Inquadramento"** nella scheda dipendente (gated `can_hr`), riga "in corso" evidenziata, edit inline
- [x] Admin `StoricoContrattoAdmin`
- [x] Migrazioni `0008`, `0009`, `0010`

### 4.2 `DipendenteCambiamentoOrganizzativo` — mansione, reparto, area, ruolo aziendale (admin-visibile)

Approccio "log puntuale per campo" con `valore_precedente` → `valore_nuovo`.

- [x] Modello `DipendenteCambiamentoOrganizzativo` con `tipo` in (`MANSIONE`, `REPARTO`, `AREA`, `RUOLO_AZIENDALE`), `valore_precedente`, `valore_nuovo`, `data_effetto`, `note`, `created_by`
- [x] Helper `_registra_cambiamento(legacy_id, tipo, vecchio, nuovo, user, data_effetto, note)` — crea la riga solo se il valore è cambiato (confronto case-insensitive con strip)
- [x] **Hook automatici**:
  - `dipendente_mansione_set` → registra cambio `MANSIONE`
  - `dipendente_reparto_set` (nuova view) → registra cambio `REPARTO`
  - `dipendente_anagrafica_aziendale_save` → registra cambio `AREA` e `RUOLO_AZIENDALE` (entrambi confrontati prima del form.save)
- [x] **Card "📋 Storico cambiamenti organizzativi"** nella scheda dipendente (gated `is_admin`), timeline tabellare con filtro per tipo (Tutti/Mansione/Reparto/Area/Ruolo), badge colorato per tipo, autore + timestamp
- [x] Admin `DipendenteCambiamentoOrganizzativoAdmin` (read-only, no add manuale, delete solo per superuser)
- [x] Migrazione `0011`

### 4.3 Cosa NON è stato implementato (volutamente)

- ❌ Il singolo `DipendenteStoricoCambiamento` generico originariamente proposto: superseduto dalla coppia `StoricoContratto` + `DipendenteCambiamentoOrganizzativo`.
- ❌ Hook di storicizzazione su `tipologia_contratto` e `livello_inquadramento` del modello `DipendenteAnagraficaAziendale`: questi campi sono stati **rimossi dalla card aziendale** (display e form) — la gestione canonica è in `StoricoContratto`.

---

## 5. Implementato — Sprint 3 (retribuzioni: import CSV + data-entry manuale)

### 5.1 Modelli

- [x] `ImportazioneRetributiva` — batch import con metadati: `data_competenza` (1° giorno mese), `origine` (`CSV` | `MANUALE`), `importato_da`, `file_nome`, `righe_ok/errore`, `note`
- [x] `VoceRetributiva` — singola voce per dipendente/periodo: `tax_code`, `legacy_anagrafica_id`, `pay_item` + `pay_item_key`, `categoria` (`fisso`/`variabile`/`totale`/`altro`), `importo`, `is_changed`, `importo_precedente`, **`manuale`** (flag), **`note`**, **`updated_by`**
- [x] Funzione `_classify_pay_item()` — classifica automaticamente le voci in base al nome (es. "Retribuzione base" → `fisso`, "Premio produzione operai" → `variabile`, "RAL" → `totale`)

### 5.2 Import CSV mensile (admin-only)

- [x] Pagina `/anagrafica/retribuzioni/` — upload CSV separatore `;`, decimali con virgola, data `gg/mm/aaaa`, encoding auto-detect utf-8/latin-1/cp1252
- [x] Chiave dipendente = codice fiscale → `DipendenteAnagraficaCivile.codice_fiscale`, con fallback nome-based (`COGNOME NOME` uppercase) contro la tabella legacy
- [x] Rilevamento automatico variazioni rispetto all'ultima importazione (`is_changed` + `importo_precedente`)
- [x] Storico importazioni in tabella; la lista esclude le importazioni manuali

### 5.3 Data-entry manuale (HR + admin)

- [x] View `dipendente_retribuzione_voce_add(legacy_id)` POST — crea/recupera l'unica `ImportazioneRetributiva` manuale per quel mese (`origine=MANUALE`, `file_nome="(inserimento manuale)"`) e vi aggiunge la voce con `manuale=True`
- [x] View `dipendente_retribuzione_voce_edit(legacy_id, voce_id)` POST — modifica `pay_item`, `importo`, `categoria`, `note` (solo voci con `manuale=True`)
- [x] View `dipendente_retribuzione_voce_delete(legacy_id, voce_id)` POST — elimina la voce; se l'importazione manuale resta vuota, viene cancellata anche quella
- [x] Gate scrittura: `can_hr` **OR** `is_admin`
- [x] Validazione: data competenza obbligatoria (accetta `YYYY-MM-DD`, normalizza al primo del mese), pay_item + importo obbligatori, categoria opzionale (auto-classifica se omessa)
- [x] **Override semantico**: le voci manuali fanno override delle voci CSV con stesso `pay_item_key` nello stesso mese. La logica di merge (in `dipendente_retribuzioni` e nella card del dettaglio) prende:
  - 1 sola importazione CSV per mese (la più recente)
  - + tutte le voci manuali del mese
  - per ogni `pay_item_key` presente nelle manuali, la voce CSV omonima viene scartata dal rendering

### 5.4 Template

- [x] Card "💰 Voci retributive" nella scheda dipendente (gated `can_hr`): tre macro-sezioni (Fissi/Variabili/Totali) + voci con badge `⚡ modificato` se cambiate vs mese precedente
- [x] Pagina `/anagrafica/dipendenti/<id>/retribuzioni/`: timeline mensile accordion, **pulsante "+ Voce manuale"** in topbar che apre form inline con campi (mese, voce, importo, categoria, note); per ogni voce con `manuale=True` mostra badge `manuale` + pulsanti ✏/✕; modifica inline via riga edit toggle
- [x] Componente partial `_retr_voce_row.html` — DRY del rendering riga voce (chiamato 4 volte: fissi, variabili, altri, totali)
- [x] Footer mese con contatore voci manuali se presenti
- [x] Admin `ImportazioneRetributivaAdmin` (read-only, no add manuale)

### 5.5 Cosa NON è stato implementato (volutamente)

- ❌ Modello `DipendenteRetribuzione` proposto originariamente (record per variazione retributiva con catalogo voci configurabile + formset): superseduto dal pattern import-driven CSV + override manuale per voce.
- ❌ Catalogo `VoceRetributivaCatalogo` configurabile dall'utente: la classificazione fisso/variabile/totale è hardcoded in `_classify_pay_item` per allineamento con la tassonomia CCNL Metalmeccanici già usata dallo studio paghe.
- ❌ Export CSV retributivo dedicato (es. nel report dipendenti): rinviato a futuro per evitare canali non cifrati per dati sensibili. Lo storico è consultabile solo dal portale.

---

## 6. Implementato — Extra (pannello impostazioni unificato)

Non era in nessuno degli sprint originali ma è stato aggiunto come refactor naturale dei cataloghi.

- [x] `/anagrafica/impostazioni/` — 8 tabs verticali bookmarkable via `?tab=` / `#tab-`:
  1. Mansioni
  2. Aree aziendali
  3. Ruoli aziendali
  4. Ruoli operativi sicurezza
  5. Qualifiche professionali
  6. Livelli contrattuali (CRUD nuovo nel portale; prima solo Django admin)
  7. Tipologie contratto (CRUD nuovo nel portale)
  8. Permessi (singleton `AnagraficaStatPermission` + `AnagraficaHRPermission`, form unico)
- [x] Tutte le view CRUD esistenti onorano un campo nascosto `next_tab` nel POST → tornano al pannello impostazioni con la tab corretta. Le URL standalone restano funzionanti.
- [x] Subnav semplificata: voce unica "⚙️ Impostazioni" al posto delle voci singole per catalogo.

---

## 7. Struttura dati

### 7.1 DipendenteAnagraficaCivile

Vedi `models.py:DipendenteAnagraficaCivile`. Campi chiave: `legacy_anagrafica_id` (1:1), `data_nascita`, `luogo_nascita`, `genere`, `indirizzo/citta/provincia/nazione/cap_residenza`, `indirizzo/citta/nazione/cap_domicilio`, `codice_fiscale` (HR), `titolo_studio`, `email/telefono_privato`, `patente_auto`, `nome_banca`/`iban`/`intestatario_conto` (HR — IBAN con property `iban_mascherato`), `categoria_protetta`/`categoria_disabili`/`percentuale_disabilita` (HR).

### 7.2 DipendenteAnagraficaAziendale

`legacy_anagrafica_id` (1:1), `area`, `ruolo_aziendale`, `taglia_scarpe/pantalone/maglia`, `consenso_privacy` + `data_consenso_privacy`, `data_prima_assunzione`, `prova_data_inizio/fine`, `tipologia_contratto`, `livello_inquadramento`, `email/telefono_aziendale`. **Nota**: `tipologia_contratto` e `livello_inquadramento` sono stati nascosti dalla UI: la gestione canonica è in `StoricoContratto`. I campi DB restano per compatibilità.

### 7.3 DipendenteCambiamentoOrganizzativo (Sprint 2a)

| Campo | Tipo | Note |
|-------|------|------|
| `legacy_anagrafica_id` | IntegerField (indexed, **non unique**) | |
| `tipo` | CharField choices | MANSIONE / REPARTO / AREA / RUOLO_AZIENDALE |
| `valore_precedente` | CharField 300 | Vuoto se valore mancante prima |
| `valore_nuovo` | CharField 300 | Vuoto se rimozione |
| `data_effetto` | DateField | Default `localdate()` |
| `note` | TextField | Opzionale |
| `created_at` | DateTimeField auto_now_add | |
| `created_by` | FK → User SET_NULL | |

Indice composito: `(legacy_anagrafica_id, tipo, -data_effetto)` per query "ultimi cambiamenti per dipendente/tipo".

### 7.4 StoricoContratto (Sprint 2a)

`legacy_anagrafica_id` / `tax_code` (dual-key), `data_inizio` / `data_fine` (null = in corso), `tipologia_contratto` (codice → `TipologiaContratto`), `qualifica_nome`, `codice_livello` (codice → `LivelloContrattuale`), `ccnl`, `descrizione_livello`, `importato_da`, `created_at`. Property `is_in_corso`.

### 7.5 ImportazioneRetributiva + VoceRetributiva (Sprint 3)

`ImportazioneRetributiva`: `data_competenza` (1° giorno mese), **`origine`** (`CSV`/`MANUALE`), `importato_da`, `file_nome`, `righe_totali/ok/errore`, `note`.

`VoceRetributiva`: `importazione` FK, `tax_code` (indexed), `legacy_anagrafica_id` (indexed, nullable), `data_competenza`, `pay_item` + `pay_item_key` (lowercase), `categoria` choices, `importo`, `is_changed`/`importo_precedente`, **`manuale`** (indexed), **`note`**, **`updated_by`** FK → User, **`updated_at`**.

---

## 8. Permessi e ACL

### Helper `_check_hr_permission(request)`

```python
def _check_hr_permission(request) -> bool:
    if not request.user.is_authenticated:
        return False
    perm = AnagraficaHRPermission.get_instance()
    if perm.accesso == AnagraficaHRPermission.ACCESSO_TUTTI:
        return True
    if perm.accesso == AnagraficaHRPermission.ACCESSO_ADMIN:
        return is_legacy_admin(request.user)
    # ACCESSO_RUOLI: verifica ruoli ACL v2
    if perm.ruolo_ids:
        user_roles = request.user.ruoli_operativi.values_list('ruolo_operativo_id', flat=True)
        return bool(set(perm.ruolo_ids) & set(user_roles))
    return False
```

### Configurazione

`AnagraficaHRPermission` e `AnagraficaStatPermission` ora configurabili dal pannello impostazioni `/anagrafica/impostazioni/?tab=permessi` (oltre che da Django admin). Default: `ADMIN`.

### Gate di scrittura per dimensione

| Operazione | Gate |
|-----------|------|
| Anagrafica civile/aziendale save | `is_legacy_admin` |
| Mansione/Reparto set | `is_legacy_admin` |
| Storico contratto CRUD | `can_hr` |
| Voce retributiva manuale add/edit/delete | `can_hr OR is_admin` |
| Storico cambiamenti organizzativi (sola lettura UI) | `is_admin` |
| Dati HR sensibili (IBAN, CF, disabilità) lettura | `can_hr` |

Il report CSV `dipendenti_report?format=csv` esclude i dati HR per design (canale non cifrato).

---

## 9. File coinvolti

```
django_app/anagrafica/
├── models.py
│     ├── DipendenteAnagraficaCivile
│     ├── DipendenteAnagraficaAziendale
│     ├── AnagraficaHRPermission
│     ├── AreaAziendale / RuoloAziendale
│     ├── DipendenteCambiamentoOrganizzativo   ← Sprint 2a
│     ├── StoricoContratto                     ← Sprint 2a
│     ├── TipologiaContratto / LivelloContrattuale
│     ├── ImportazioneRetributiva              ← Sprint 3
│     └── VoceRetributiva (con flag manuale)   ← Sprint 3
├── forms.py
│     ├── AnagraficaCivileForm / AnagraficaAziendaleForm
├── views.py
│     ├── dipendente_detail (orchestrazione + storici + retribuzioni)
│     ├── dipendente_mansione_set (+ hook storico)         ← Sprint 2a
│     ├── dipendente_reparto_set (+ hook storico)          ← Sprint 2a (nuova)
│     ├── dipendente_anagrafica_*_save (+ hook area/ruolo) ← Sprint 2a
│     ├── _registra_cambiamento (helper)                   ← Sprint 2a
│     ├── retribuzioni_import / dipendente_retribuzioni
│     ├── dipendente_retribuzione_voce_add/edit/delete     ← Sprint 3 manuale
│     ├── contratti_import / dipendente_contratto_*
│     └── impostazioni / impostazioni_permessi_save
├── urls.py
├── admin.py
│     ├── DipendenteCambiamentoOrganizzativoAdmin (read-only)
│     ├── StoricoContrattoAdmin / TipologiaContrattoAdmin / LivelloContrattualeAdmin
│     └── ImportazioneRetributivaAdmin (read-only)
├── migrations/
│     ├── 0005_… (Sprint 1 anagrafica civile/aziendale + HR permission)
│     ├── 0006_… (Sprint 1 aree e ruoli aziendali)
│     ├── 0007_retribuzioni.py
│     ├── 0008_storico_contratti.py
│     ├── 0009_livello_contrattuale.py
│     ├── 0010_tipologia_contratto.py
│     └── 0011_cambiamento_organizzativo_voce_manuale.py   ← Sprint 2a + Sprint 3 manuale
└── templates/anagrafica/
    ├── pages/
    │     ├── dipendente_detail.html        (+ card storico cambiamenti + edit reparto inline)
    │     ├── dipendente_create.html
    │     ├── dipendenti_list.html
    │     ├── dipendenti_report.html
    │     ├── dipendente_retribuzioni.html  (+ pulsante "+ Voce manuale" + edit/delete inline)
    │     ├── retribuzioni_import.html
    │     ├── contratti_import.html
    │     ├── impostazioni.html
    │     └── index.html
    └── components/
          ├── subnav.html
          ├── flash_messages.html
          ├── page_header.html
          └── _retr_voce_row.html           ← Sprint 3 (partial DRY)
```

---

## 10. Roadmap futura

### Sprint 4 — Scadenze e alerting (priorità media)

Collegare le scadenze anagrafiche al sistema notifiche esistente.

- [ ] Scadenze contratto determinato (`StoricoContratto.data_fine`, `prova_data_fine`)
- [ ] Alert configurabile: X giorni prima della scadenza → email al responsabile
- [ ] Dashboard anagrafica: widget "Scadenze imminenti" (contratti + qualifiche)
- [ ] Integrazione con `DipendenteQualifica` (corsi/certificazioni in scadenza)

### Sprint 5 — Import batch dipendenti (priorità bassa)

- [ ] Import CSV dipendenti (bulk create/update anagrafica aziendale)
- [ ] Mapping colonne configurabile
- [ ] Preview + conferma prima del salvataggio
- [ ] Log import con errori riga per riga

### Sprint 6 — Organigramma (priorità bassa)

- [ ] Campo `responsabile_id` (FK self → `legacy_anagrafica_id`)
- [ ] Vista organigramma ad albero per area/reparto
- [ ] Export PDF organigramma

### Possibili evoluzioni

- [ ] Estensione automatica dello storico cambiamenti anche per i campi del `dipendente_create` quando in futuro diventerà una pagina di edit (oggi è solo create).
- [ ] Cifratura a riposo dell'IBAN (oggi in chiaro nel DB, mascherato solo in display).
- [ ] Endpoint dedicato per export HR completo con log di accesso (richiesto per audit GDPR).

---

## 11. Decisioni tecniche e note

### Storico organizzativo vs storico CCNL — perché due modelli

`StoricoContratto` modella **periodi di validità** (data_inizio → data_fine) di tipologia + livello + qualifica CCNL. Quando si aggiunge un nuovo periodo, il precedente "in corso" viene auto-chiuso impostando la sua `data_fine` al `data_inizio` del nuovo (`dipendente_contratto_add`).

`DipendenteCambiamentoOrganizzativo` modella invece **cambiamenti puntuali** di campi organizzativi interni (mansione, reparto, area, ruolo aziendale): il valore corrente vive nella tabella principale (legacy o `DipendenteAnagraficaAziendale`), lo storico è un log accessorio. Non c'è auto-chiusura perché ogni riga rappresenta solo un istante.

I due pattern coesistono perché modellano cose diverse: i periodi CCNL hanno una semantica contrattuale rigorosa (servono per buste paga, contributi), i cambi organizzativi sono "tracciabilità HR".

### Hook automatici di storicizzazione — confronto case-insensitive

`_registra_cambiamento()` confronta vecchio e nuovo con `.strip().casefold()`. Questo evita di creare righe spurie per micro-edit di whitespace o capitalizzazione (es. "Operaio" vs "operaio "). Quando il valore è effettivamente diverso, viene salvato preservando le maiuscole originali del valore nuovo.

### Override voci retributive manuali — semantica

Le voci manuali (flag `manuale=True`) vivono in un'`ImportazioneRetributiva` separata per mese, con `origine=MANUALE`. La logica di merge in `dipendente_retribuzioni` e nella card del dettaglio:

1. Raccoglie tutte le voci del dipendente (CSV + manuali) ordinate per data_competenza desc.
2. Per ogni mese, sceglie l'importazione CSV più recente e la lista delle voci manuali del mese.
3. Per ogni `pay_item_key` presente nelle manuali, **scarta** la voce CSV omonima dal rendering.
4. La somma "RAL" e gli altri totali NON vengono ricalcolati: rimangono quelli del CSV (perché lo studio paghe è sorgente autorevole). Se serve override anche dei totali, l'HR può creare una voce manuale con pay_item key "RAL".

Questo permette correzioni puntuali (es. "il CSV ha sbagliato un'indennità di marzo") senza scartare l'intero batch.

### Filtri area/contratto in dipendenti_list

La strategia di join è: filtra prima i `legacy_anagrafica_id` dai modelli Django, poi passa quella lista come filtro IN alla query legacy. Con molti dipendenti il set può diventare grande — valutare paginazione server-side o cache se necessario.

### Report CSV — nessun campo HR

Il report CSV esportato da `dipendenti_report?format=csv` esclude intenzionalmente IBAN, codice fiscale, percentuale disabilità, categorie protette **e voci retributive** anche per utenti `can_hr`. Requisito di sicurezza deliberato: il CSV viaggia spesso non cifrato. Per export HR completi serve un endpoint dedicato con log di accesso (TODO Sprint 4).

### IBAN — masking display vs storage

L'IBAN è salvato in chiaro nel DB. Il mascheramento (`IT60 **** **** **** **** 75`) è solo a livello di display nel template via property `iban_mascherato`. Se in futuro si aggiunge cifratura a riposo, il campo `iban` è l'unico da migrare.

### Codice fiscale — visibilità

Il CF è fisicamente in `DipendenteAnagraficaCivile` ma viene mostrato solo nella card "Dati riservati HR" (gated `can_hr`). Tecnicamente fa parte dell'anagrafica civile, semanticamente è dato sensibile.

### Singleton AnagraficaHRPermission

Analogo ad `AnagraficaStatPermission`. L'admin Django non permette di aggiungere una seconda istanza né di eliminare quella esistente. Il pannello impostazioni (`/anagrafica/impostazioni/?tab=permessi`) espone il form di configurazione anche fuori dal Django admin.
