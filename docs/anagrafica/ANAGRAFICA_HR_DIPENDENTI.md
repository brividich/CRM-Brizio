# Anagrafica HR Dipendenti — Documento di sviluppo

> **Stato**: In sviluppo attivo  
> **Versione app al kickoff**: 1.0.2 (2026-05-19)  
> **Ultimo aggiornamento**: 2026-05-19

Documento vivo che traccia l'implementazione della gestione HR strutturata dei dipendenti nel modulo `anagrafica`. Usato come filo conduttore tra sessioni di sviluppo.

---

## Indice

1. [Contesto e obiettivo](#1-contesto-e-obiettivo)
2. [Architettura scelta](#2-architettura-scelta)
3. [Implementato — Sprint 1](#3-implementato--sprint-1)
4. [Struttura dati](#4-struttura-dati)
5. [Permessi e ACL](#5-permessi-e-acl)
6. [File coinvolti](#6-file-coinvolti)
7. [Roadmap futura](#7-roadmap-futura)
8. [Decisioni tecniche e note](#8-decisioni-tecniche-e-note)

---

## 1. Contesto e obiettivo

Prima di questo sprint, la scheda dipendente mostrava solo i dati minimali della tabella legacy `anagrafica_dipendenti` (SQL Server, unmanaged): nome, cognome, matricola, reparto, mansione, email, username.

**Obiettivo**: costruire attorno alla tabella legacy una gestione HR completa, strutturata in livelli di visibilità distinti:

| Livello | Chi vede | Dati |
|---------|----------|------|
| Base | Tutti (con accesso anagrafica) | Dati legacy: nome, cognome, reparto, mansione |
| Admin | Admin portale | Anagrafica aziendale + anagrafica civile (non sensibile) |
| HR | Utenti con permesso HR dedicato | IBAN, codice fiscale, categorie protette/disabili |

**Principio guida**: nessuna modifica alla tabella legacy. Tutti i nuovi dati vivono in tabelle Django aggiuntive collegate tramite `legacy_anagrafica_id`.

---

## 2. Architettura scelta

### Bridge pattern (identico a DipendenteRuoloOperativo, DipendenteQualifica)

```
anagrafica_dipendenti (SQL Server, unmanaged)
         │
         │  legacy_anagrafica_id = IntegerField(unique=True)
         │
         ├── DipendenteAnagraficaCivile     (Django managed)
         ├── DipendenteAnagraficaAziendale  (Django managed)
         └── (futuro) DipendenteRetribuzione (Django managed)
```

### Singleton permission (identico ad AnagraficaStatPermission)

```python
AnagraficaHRPermission.get_instance()
# accesso: TUTTI | ADMIN | RUOLI
# ruolo_ids: JSONField → lista ID ruolo ACL v2 se accesso=RUOLI
```

---

## 3. Implementato — Sprint 1

### 3.1 Modelli

- [x] `DipendenteAnagraficaCivile` — dati personali, residenza, domicilio, contatti privati, IBAN, CF, disabilità
- [x] `DipendenteAnagraficaAziendale` — area, ruolo aziendale, taglie DPI, contratto, contatti aziendali, privacy
- [x] `AnagraficaHRPermission` — singleton con `get_instance()`, accesso configurabile da admin Django
- [x] `AreaAziendale` — catalogo dropdown per campo `area` in `DipendenteAnagraficaAziendale`
- [x] `RuoloAziendale` — catalogo dropdown per campo `ruolo_aziendale` in `DipendenteAnagraficaAziendale`
- [x] Migrazione `0005_dipendenteanagraficacivile_aziendale_hrpermission.py` (scritta manualmente — venv non disponibile)
- [x] Migrazione `0006_areaaziendale_ruoloaziendale.py` (scritta manualmente)

### 3.2 Form

- [x] `AnagraficaCivileForm` — tutti i campi tranne `updated_by`; `clean_codice_fiscale()` → uppercase; `clean_iban()` → strip spazi + uppercase
- [x] `AnagraficaAziendaleForm` — tutti i campi tranne `updated_by`; widget con classe `dp-input`; `__init__` dinamico che imposta `Select` per `area` e `ruolo_aziendale` dai rispettivi cataloghi (con fallback al valore corrente se non presente nel catalogo)

### 3.3 Views

- [x] `dipendente_detail` — arricchita con `civile`, `aziendale`, `can_hr`, `form_civile`, `form_aziendale`
- [x] `dipendente_anagrafica_civile_save` — POST, gate admin, `get_or_create` + form save
- [x] `dipendente_anagrafica_aziendale_save` — POST, gate admin, stessa logica
- [x] `dipendenti_report` — GET + CSV export (`?format=csv`), filtri: q / reparto / area / contratto / consenso / cat_protetta; join legacy↔Django in memoria
- [x] `dipendenti_list` — rimosso form inline, aggiunti filtri area e contratto, link "Report"
- [x] `dipendente_create` — form a sezioni collassabili, cascade create legacy → civile → aziendale

### 3.4 URL

```
/anagrafica/dipendenti/nuovo/
/anagrafica/dipendenti/<id>/anagrafica-civile/salva/
/anagrafica/dipendenti/<id>/anagrafica-aziendale/salva/
/anagrafica/dipendenti/report/
```

### 3.5 Template

- [x] `dipendente_detail.html` — 3 card: 🏢 Aziendale / 🪪 Civile / 🔒 HR; form inline a toggle `toggleSection(id)`
- [x] `dipendenti_list.html` — pulsante "+ Nuovo dipendente", filtri area/contratto, link Report
- [x] `dipendente_create.html` — 4 card collassabili con macro-aree titolate
- [x] `dipendenti_report.html` — filtri avanzati, tabella, export CSV
- [x] `index.html` (home anagrafica) — pulsante "+ Nuovo dipendente" nell'hero

### 3.6 Admin e ACL

- [x] `AnagraficaHRPermissionAdmin` — singleton (no add se esiste, no delete)
- [x] `acl_bootstrap.py` — 5 nuovi endpoint: `dipendente_civile_save`, `dipendente_aziendale_save`, `dipendenti_report`, `anagrafica_aree`, `anagrafica_ruoli_aziendali`

### 3.7 Catalogo Aree e Ruoli aziendali

- [x] Pagina `/anagrafica/aree/` — lista + form aggiungi + modal modifica + elimina con conferma
- [x] Pagina `/anagrafica/ruoli-aziendali/` — stessa struttura
- [x] Entrambe raggiungibili da subnav ("Aree" e "Ruoli az.")
- [x] Voci inattive rimangono in catalogo ma non appaiono nel dropdown (compatibilità: il valore corrente è sempre mostrato anche se non più nel catalogo attivo)

---

## 4. Struttura dati

### DipendenteAnagraficaCivile

| Campo | Tipo | Note |
|-------|------|------|
| `legacy_anagrafica_id` | IntegerField (unique) | Bridge key |
| `data_nascita` | DateField null | |
| `luogo_nascita` | CharField 200 | |
| `genere` | CharField choices M/F/A | |
| `indirizzo_residenza` | CharField 300 | |
| `citta_residenza` | CharField 100 | |
| `provincia_residenza` | CharField 5 | |
| `nazione_residenza` | CharField 100 | default Italia |
| `cap_residenza` | CharField 10 | |
| `indirizzo_domicilio` | CharField 300 | |
| `citta_domicilio` | CharField 100 | |
| `nazione_domicilio` | CharField 100 | |
| `cap_domicilio` | CharField 10 | |
| `codice_fiscale` | CharField 16 | **HR** |
| `titolo_studio` | CharField choices | PRIMO_GRADO / SECONDO_GRADO / LAUREA_TRIENNALE / LAUREA_MAGISTRALE / LAUREA_CICLO_UNICO |
| `email_privata` | EmailField | |
| `telefono_privato` | CharField 30 | |
| `patente_auto` | BooleanField | |
| `nome_banca` | CharField 200 | **HR** |
| `iban` | CharField 34 | **HR** — property `iban_mascherato` |
| `intestatario_conto` | CharField 200 | **HR** |
| `categoria_protetta` | BooleanField | **HR** |
| `categoria_disabili` | BooleanField | **HR** |
| `percentuale_disabilita` | DecimalField 5,2 null | **HR** |
| `updated_at` | DateTimeField auto_now | |
| `updated_by` | FK → User SET_NULL | |

### DipendenteAnagraficaAziendale

| Campo | Tipo | Note |
|-------|------|------|
| `legacy_anagrafica_id` | IntegerField (unique) | Bridge key |
| `area` | CharField 100 | Es. "Commerciale", "Tecnico" |
| `ruolo_aziendale` | CharField 200 | Distinto da mansione CCNL |
| `taglia_scarpe` | CharField 10 | Es. "42", "43.5" |
| `taglia_pantalone` | CharField 20 | Es. "48", "50/34" |
| `taglia_maglia` | CharField choices | XS/S/M/L/XL/XXL/XXXL |
| `consenso_privacy` | BooleanField | |
| `data_consenso_privacy` | DateField null | |
| `data_prima_assunzione` | DateField null | |
| `prova_data_inizio` | DateField null | |
| `prova_data_fine` | DateField null | |
| `tipologia_contratto` | CharField choices | INDETERMINATO / DETERMINATO / APPRENDISTATO / SOMMINISTRAZIONE / COLLABORAZIONE / STAGE / ALTRO |
| `livello_inquadramento` | CharField 50 | Free text per CCNL diversi |
| `email_aziendale` | EmailField | |
| `telefono_aziendale` | CharField 30 | |
| `updated_at` | DateTimeField auto_now | |
| `updated_by` | FK → User SET_NULL | |

---

## 5. Permessi e ACL

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

### Configurazione admin

`AnagraficaHRPermission` è configurabile da Django admin (`/django-admin/anagrafica/anagraficahrpermission/1/`). Default: `ADMIN`.

### Gate di scrittura

Le view `_save` usano `is_legacy_admin(request.user)` — solo admin possono scrivere. La lettura dei dati HR segue `can_hr`.

---

## 6. File coinvolti

```
django_app/anagrafica/
├── models.py                    ← DipendenteAnagraficaCivile, DipendenteAnagraficaAziendale, AnagraficaHRPermission
├── forms.py                     ← AnagraficaCivileForm, AnagraficaAziendaleForm
├── views.py                     ← dipendente_detail, _save views, dipendenti_report, dipendente_create
├── urls.py                      ← 4 nuovi pattern
├── admin.py                     ← AnagraficaHRPermissionAdmin
├── acl_bootstrap.py             ← 3 nuovi endpoint
├── migrations/
│   └── 0005_dipendenteanagraficacivile_aziendale_hrpermission.py
└── templates/anagrafica/pages/
    ├── dipendente_detail.html   ← 3 card HR
    ├── dipendente_create.html   ← form creazione con macro-aree
    ├── dipendenti_list.html     ← filtri + pulsante nuovo
    ├── dipendenti_report.html   ← report + CSV export
    └── index.html               ← hero con "+ Nuovo dipendente"
```

---

## 7. Roadmap futura

### Sprint 2a — Storico cambiamenti organizzativi (priorità alta)

Tracciare nel tempo i cambi di mansione, reparto, area, ruolo aziendale, contratto e livello di inquadramento, con data effetto e autore.

**Principio**: ogni modifica a uno di questi campi chiave non sovrascrive il valore precedente ma crea una riga di storico. Il valore corrente è sempre quello col `data_effetto` più recente. Il record principale (`DipendenteAnagraficaAziendale`) continua a contenere il valore attuale per semplicità di lettura — lo storico affianca, non sostituisce.

**Struttura proposta**:

```python
class DipendenteStoricoCambiamento(models.Model):
    TIPO_CHOICES = [
        ('MANSIONE',             'Mansione'),
        ('REPARTO',              'Reparto'),
        ('AREA',                 'Area'),
        ('RUOLO_AZIENDALE',      'Ruolo aziendale'),
        ('TIPOLOGIA_CONTRATTO',  'Tipo contratto'),
        ('LIVELLO_INQUADRAMENTO','Livello inquadramento'),
    ]
    legacy_anagrafica_id = IntegerField(db_index=True)   # NON unique
    tipo                 = CharField(max_length=30, choices=TIPO_CHOICES)
    valore_precedente    = CharField(max_length=300, blank=True, default="")
    valore_nuovo         = CharField(max_length=300, blank=True, default="")
    data_effetto         = DateField()                   # da quando vale il nuovo valore
    note                 = TextField(blank=True, default="")
    created_at           = DateTimeField(auto_now_add=True)
    created_by           = FK → User SET_NULL

    class Meta:
        ordering = ['-data_effetto', '-created_at']
        indexes  = [Index(fields=['legacy_anagrafica_id', 'tipo', '-data_effetto'])]
```

**Logica di salvataggio**: quando `dipendente_anagrafica_aziendale_save` o la view mansione rileva una modifica su uno dei campi monitorati, prima di salvare crea automaticamente una riga `DipendenteStoricoCambiamento` con il vecchio e il nuovo valore.

**Feature da implementare**:
- [ ] Modello `DipendenteStoricoCambiamento` + migrazione
- [ ] Helper `_registra_cambiamento(legacy_id, tipo, vecchio, nuovo, data_effetto, user)` in `models.py` o `views.py`
- [ ] Hook automatico in `dipendente_anagrafica_aziendale_save` e `dipendente_mansione_set`
- [ ] Card "📋 Storico cambiamenti" nella scheda dipendente (solo admin)
  - Timeline raggruppata per tipo o cronologica
  - Badge colorato per tipo cambiamento
  - Autore + data del cambio
- [ ] Filtro per tipo nella card storico
- [ ] Admin `DipendenteStoricoCambiamentoAdmin` (read-only, no delete)

---

### Sprint 3 — Gestione retributiva (priorità alta)

Modello `DipendenteRetribuzione` con storicizzazione automatica.

**Principio**: ogni variazione retributiva crea un nuovo record (non modifica quello precedente). La retribuzione corrente è sempre il record con `data_effetto` più recente ≤ oggi.

**Struttura proposta**:

```python
class DipendenteRetribuzione(models.Model):
    legacy_anagrafica_id = IntegerField(db_index=True)  # NON unique — più record per dipendente
    data_effetto         = DateField()         # data da cui vale questa voce
    livello              = CharField(50, blank)  # es. "3° livello CCNL Metalmeccanici"
    note                 = TextField(blank)

    # Collegamento a voci retributive (FK a catalogo)
    # voci = M2M o FK a DipendenteVoceRetributiva

    created_at = DateTimeField(auto_now_add=True)
    created_by = FK → User SET_NULL

    class Meta:
        ordering = ['-data_effetto']
        indexes = [Index(fields=['legacy_anagrafica_id', '-data_effetto'])]
```

```python
class VoceRetributivaCatalogo(models.Model):
    nome       = CharField(200, unique=True)   # es. "Minimo contrattuale", "Superminimo", "Indennità cassa"
    tipologia  = CharField choices FISSA / VARIABILE / BENEFIT
    descrizione = TextField(blank)
    attivo     = BooleanField(default=True)
```

```python
class DipendenteVoceRetributiva(models.Model):
    retribuzione = FK → DipendenteRetribuzione
    voce         = FK → VoceRetributivaCatalogo
    importo      = DecimalField(10, 2)
    frequenza    = CharField choices MENSILE / ANNUALE / UNA_TANTUM
    note         = CharField(300, blank)
```

**Feature da implementare**:
- [ ] Modelli + migrazione
- [ ] Form `RetribuzioneForm` + `VoceRetributivaFormset`
- [ ] Card "📊 Retribuzione" nella scheda dipendente (solo `can_hr`)
  - Sezione "Retribuzione corrente" con tabella voci
  - Sezione "Storico" con accordion per variazioni precedenti
  - Form inline "Nuova variazione" con data effetto e voci
- [ ] View `dipendente_retribuzione_add(request, legacy_id)` — POST
- [ ] Export CSV in `dipendenti_report` con colonne retributive (solo se `can_hr`)
- [ ] Admin `VoceRetributivaCatalogoAdmin` per gestire il catalogo voci

### Sprint 4 — Scadenze e alerting (priorità media)

Collegare le scadenze anagrafiche al sistema notifiche esistente.

- [ ] Scadenze contratto determinato (`prova_data_fine`, fine contratto)
- [ ] Alert configurabile: X giorni prima della scadenza → email al responsabile
- [ ] Dashboard anagrafica: widget "Scadenze imminenti"
- [ ] Integrazione con `DipendenteQualifica` (scadenze corsi/certificazioni)

### Sprint 5 — Import batch (priorità bassa)

- [ ] Import CSV dipendenti (bulk create/update anagrafica aziendale)
- [ ] Mapping colonne configurabile
- [ ] Preview + conferma prima del salvataggio
- [ ] Log import con errori riga per riga

### Sprint 6 — Organigramma (priorità bassa)

- [ ] Aggiunta campo `responsabile_id` (FK a se stessa → `legacy_anagrafica_id`)
- [ ] Vista organigramma ad albero per area/reparto
- [ ] Export PDF organigramma

---

## 8. Decisioni tecniche e note

### Venv non disponibile
Il venv `.venv` punta a `C:\Users\l.bova\AppData\Local\Programs\Python\Python313\python.exe` (utente diverso). Finché non viene ricreato, le migrazioni devono essere scritte manualmente. Per ricreare:
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r django_app\requirements.txt
```

### IBAN — masking display vs storage
L'IBAN è salvato in chiaro nel DB (non cifrato). Il mascheramento (`IT60 **** **** **** **** 75`) è solo a livello di display nel template. Se in futuro si aggiunge cifratura a riposo, il campo `iban` è l'unico da migrare.

### Codice fiscale in AnagraficaCivile vs campo HR
Il CF è fisicamente in `DipendenteAnagraficaCivile` ma nel template viene mostrato solo nella card "Dati riservati HR" (gated da `can_hr`). Questo è intenzionale: il CF è dato sensibile ma tecnicamente fa parte dell'anagrafica civile, non dei soli dati bancari.

### Filtri area/contratto in dipendenti_list
La strategia di join è: filtra prima i `legacy_anagrafica_id` dai modelli Django, poi passa quella lista come filtro IN alla query legacy. Con molti dipendenti il set può diventare grande — valutare paginazione server-side o cache se necessario.

### Report CSV — nessun campo HR
Il report CSV esportato da `dipendenti_report?format=csv` esclude intenzionalmente IBAN, codice fiscale, percentuale disabilità e categorie protette, anche per utenti `can_hr`. Questo è un requisito di sicurezza deliberato: il CSV viaggia spesso non cifrato (email, download browser). Se in futuro serve un export HR completo, deve essere un endpoint dedicato con log di accesso.

### Singleton AnagraficaHRPermission
Analogo ad `AnagraficaStatPermission`. L'admin Django non permette di aggiungere una seconda istanza (`has_add_permission` restituisce False se `pk=1` esiste) né di eliminare quella esistente (`has_delete_permission` sempre False).
