# TODO — Modulo Formazione HR — Lista prosecuzione
## NOVICROM HUB — Anagrafica HR → Sezione Formazione

**Aggiornato:** 2026-05-22 (rev. decisioni architetturali D1-D10)
**Stato progetto:** PATCH FORMAZIONE-00 completata (documento bozza)
**Da leggere prima di proseguire:** `docs/anagrafica/formazione/BOZZA_MODULO_FORMAZIONE.md`

---

## STATO ATTUALE

| # | Patch | Stato | Note |
|---|-------|-------|------|
| 00 | Discovery e documento architettura | ✅ COMPLETATO | `docs/anagrafica/formazione/BOZZA_MODULO_FORMAZIONE.md` |
| 01 | Modelli base e admin read-only | ⏳ PRONTO | Decisioni architetturali definite — vedi sezione sotto |
| 02 | Dashboard Formazione | ⏳ IN ATTESA | Dipende da PATCH-01 |
| 03 | Piani Formativi e Corsi (CRUD) | ⏳ IN ATTESA | Dipende da PATCH-02 |
| 04 | Sessioni e Lezioni | ⏳ IN ATTESA | Dipende da PATCH-03 |
| 05 | Iscritti e Presenze | ⏳ IN ATTESA | Dipende da PATCH-04 |
| 06 | Storico Dipendente e Scadenzario | ⏳ IN ATTESA | Dipende da PATCH-05 |
| 07 | Export Excel completo | ⏳ IN ATTESA | Dipende da PATCH-06 |
| 08 | Report Firma PDF | ⏳ IN ATTESA | Dipende da PATCH-07 |
| 09 | Hardening, test, permessi, audit | ⏳ IN ATTESA | Dipende da PATCH-08 |

---

## DECISIONI ARCHITETTURALI D1-D10

> Stato al 2026-05-22. Le decisioni segnate ✅ sono definitive e non riapribili senza esplicita autorizzazione.
> Le decisioni segnate ⏳ sono ancora aperte e vanno confermate prima di avviare la patch indicata.

| # | Decisione | Stato | Scelta |
|---|-----------|-------|--------|
| D1 | Schema modelli: `models.py` unico vs `models_formazione.py` separato | ⏳ | Da confermare prima di PATCH-01 |
| D2 | Aggiungere `"CERTIFICATO_FORMAZIONE"` alle choices di `DocumentoDipendente.tipo` | ⏳ | Da confermare prima di PATCH-01 |
| D3 | URL base: `/anagrafica/formazione/` dedicato vs tab nella dashboard principale | ⏳ | Da confermare prima di PATCH-02 |
| D4 | Obbligatorietà corsi per mansione/ruolo | ✅ | **`TrainingRequirementRule`** — tabella dedicata (non M2M su TrainingPlan, non TrainingPlanObligation) |
| D5 | Docente esterno | ✅ | **`TrainingInstructor`** — modello dedicato con ragione sociale, email, tipo (interno/esterno) |
| D6 | Import massivo iscritti | ⏳ | Da confermare prima di PATCH-05 |
| D7 | Notifiche scadenza | ⏳ | Da confermare prima di PATCH-06 |
| D8 | PDF report firma: libreria | ⏳ | Da confermare prima di PATCH-08 — **non introdurre reportlab/weasyprint prima di PATCH-08** |
| D9 | `TrainingDeadline` ricalcolo | ✅ | **Management command schedulato** + service layer `training_deadline_service.py` (non signal post_save) |
| D10 | Perimetro app | ⏳ | Da confermare prima di PATCH-01 — le istruzioni attuali assumono `anagrafica/` |

### Dettaglio D4 — `TrainingRequirementRule`

Sostituisce qualsiasi riferimento a M2M diretto su `TrainingPlan` (mansioni/ruoli) e a `TrainingPlanObligation`.

```python
class TrainingRequirementRule(models.Model):
    """Regola di obbligatorietà: quale corso è obbligatorio per quale mansione/ruolo."""
    corso          = ForeignKey(TrainingCourse, on_delete=CASCADE, related_name="regole_obbligo")
    # Target: mansione OPPURE ruolo_operativo (non entrambi nella stessa riga)
    mansione       = ForeignKey("anagrafica.Mansione", null=True, blank=True, on_delete=CASCADE)
    ruolo_operativo = ForeignKey("anagrafica.RuoloOperativo", null=True, blank=True, on_delete=CASCADE)
    frequenza_mesi  = PositiveSmallIntegerField(default=0, help_text="0 = una tantum")
    note            = TextField(blank=True)
    is_active       = BooleanField(default=True)
    created_by      = ForeignKey(User, null=True, on_delete=SET_NULL, related_name="+")

    class Meta:
        # Vincolo: almeno uno tra mansione e ruolo_operativo deve essere valorizzato
        # Verificato a livello di form/view, non in DB (MSSQL non supporta check constraint complessi via Django)
        verbose_name = "Regola di obbligatorietà"
```

### Dettaglio D5 — `TrainingInstructor`

```python
class TrainingInstructor(models.Model):
    """Catalogo docenti/formatori interni ed esterni."""
    TIPO_CHOICES = [("INTERNO", "Interno"), ("ESTERNO", "Esterno / Provider")]
    tipo               = CharField(max_length=10, choices=TIPO_CHOICES, default="ESTERNO")
    nome               = CharField(max_length=200)
    ragione_sociale    = CharField(max_length=300, blank=True)
    email              = EmailField(blank=True)
    telefono           = CharField(max_length=30, blank=True)
    # Se interno: collega al dipendente (opzionale)
    legacy_anagrafica_id = IntegerField(null=True, blank=True, db_index=True)
    note               = TextField(blank=True)
    is_active          = BooleanField(default=True)

    class Meta:
        ordering = ["nome"]
        verbose_name = "Docente / Formatore"
```

`TrainingSession.docente` e `TrainingLesson.docente` diventano FK a `TrainingInstructor` (nullable).

---

## SET MODELLI DEFINITIVO PER PATCH-01

> **17 modelli** (aggiornato rispetto ai 13 della bozza originale).
> La bozza § C in `BOZZA_MODULO_FORMAZIONE.md` rimane riferimento strutturale,
> ma il set effettivo da creare in PATCH-01 è questo.

### Modelli confermati dalla bozza (con aggiornamenti)

| Modello | Note aggiornamenti |
|---------|-------------------|
| `TrainingPlan` | Invariato. Rimuovere i campi M2M mansioni/ruoli commentati — sostituiti da `TrainingRequirementRule` |
| `TrainingCourse` | Invariato |
| `TrainingCourseDependency` | Invariato |
| `TrainingCourseModule` | Invariato |
| `TrainingCompletionRule` | Invariato (OneToOne su `TrainingCourse`) |
| `TrainingSession` | `docente` → FK a `TrainingInstructor` (nullable, con fallback `docente_nome` CharField per retrocompat) |
| `TrainingLesson` | `docente` → FK a `TrainingInstructor` (nullable, con fallback `docente_nome` CharField) |
| `TrainingEnrollment` | Invariato |
| `TrainingLessonAttendance` | Invariato |
| `TrainingEmployeeRecord` | **Rafforzato** — vedi sotto |
| `TrainingCertificate` | Invariato |
| `TrainingDeadline` | **Cache ricalcolabile** — vedi sotto |
| `TrainingExportLog` | Invariato |
| `AnagraficaFormazionePermission` | Invariato (singleton) |

### Nuovi modelli rispetto alla bozza originale

| Modello | Scopo |
|---------|-------|
| `TrainingRequirementRule` | Obbligatorietà corso per mansione/ruolo (sostituisce M2M + TrainingPlanObligation) |
| `TrainingInstructor` | Catalogo docenti interni/esterni (sostituisce CharField `docente_nome`) |
| `TrainingAssignment` | Assegnazione esplicita di un corso a un dipendente (pre-iscrizione HR) |
| `TrainingCourseVersion` | Storico versioni/revisioni del corso (era prevista come feature inline, ora modello dedicato) |

### Dettaglio `TrainingAssignment`

```python
class TrainingAssignment(models.Model):
    """Assegnazione esplicita di un corso a un dipendente da parte di HR.
    Distinto da TrainingEnrollment (che è l'iscrizione a una sessione specifica).
    Usato per: piano formativo individuale, corsi obbligatori assegnati manualmente.
    """
    STATO_CHOICES = [
        ("ASSEGNATO",   "Assegnato"),
        ("IN_CORSO",    "In corso"),
        ("COMPLETATO",  "Completato"),
        ("SCADUTO",     "Scaduto"),
        ("RIMANDATO",   "Rimandato"),
        ("ESONERATO",   "Esonerato"),
    ]
    corso                = ForeignKey(TrainingCourse, on_delete=PROTECT)
    legacy_anagrafica_id = IntegerField(db_index=True)
    piano                = ForeignKey(TrainingPlan, null=True, blank=True, on_delete=SET_NULL)
    stato                = CharField(max_length=15, choices=STATO_CHOICES, default="ASSEGNATO")
    data_assegnazione    = DateField(auto_now_add=True)
    data_scadenza_target = DateField(null=True, blank=True, help_text="Entro quando completare")
    note                 = TextField(blank=True)
    assegnato_da         = ForeignKey(User, null=True, on_delete=SET_NULL, related_name="+")
    created_at           = DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("corso", "legacy_anagrafica_id")]
        verbose_name = "Assegnazione corso"
        indexes = [Index(fields=["legacy_anagrafica_id", "stato"])]
```

### Dettaglio `TrainingCourseVersion`

```python
class TrainingCourseVersion(models.Model):
    """Storico revisioni di un corso formativo."""
    corso          = ForeignKey(TrainingCourse, on_delete=CASCADE, related_name="versioni")
    numero_versione = CharField(max_length=10)   # es. "1.0", "2.1"
    data_revisione = DateField()
    descrizione_modifiche = TextField(blank=True)
    revised_by     = ForeignKey(User, null=True, on_delete=SET_NULL, related_name="+")
    created_at     = DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-data_revisione"]
        unique_together = [("corso", "numero_versione")]
        verbose_name = "Versione corso"
```

### `TrainingEmployeeRecord` — campi snapshot storici rafforzati

Rispetto alla bozza, aggiungere i seguenti campi snapshot per garantire integrità storica anche se il corso viene modificato o archiviato successivamente:

```python
# Snapshot storici al momento del completamento
snapshot_titolo_corso     = CharField(max_length=300, blank=True)
snapshot_versione_corso   = CharField(max_length=10, blank=True)
snapshot_piano_nome       = CharField(max_length=200, blank=True)
snapshot_docente_nome     = CharField(max_length=200, blank=True)
snapshot_durata_ore       = DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
```

Questi campi vengono compilati alla creazione del record e **non aggiornati mai più**, garantendo che lo storico rifletta il corso così com'era al momento della frequenza.

### `TrainingDeadline` — natura di cache ricalcolabile

`TrainingDeadline` è una **tabella di cache derivata**, non una fonte di verità primaria.

- **Non modificare manualmente** i record `TrainingDeadline`.
- Il ricalcolo avviene tramite:
  1. **Service layer:** `anagrafica/services/training_deadline_service.py` → funzione `refresh_deadlines(legacy_id=None, corso_id=None)` chiamabile da view o command.
  2. **Management command:** `python manage.py refresh_training_deadlines [--legacy-id <id>] [--corso-id <id>] [--all]`
- **Non usare signal `post_save`** su `TrainingEmployeeRecord` (decisione D9) — troppo fragile in bulk insert e import da Excel.
- Il command va pianificato come task schedulato (es. notturno) in IIS o tramite Windows Task Scheduler.

---

## TODO PATCH-01 — Modelli base e admin

> **Prerequisiti:** Confermare D1 (schema file), D2 (choices DocumentoDipendente), D10 (perimetro app)

- [ ] Confermare D1: decidere se aggiungere i modelli in `models.py` o in `models_formazione.py`
- [ ] Confermare D2: aggiungere o no `"CERTIFICATO_FORMAZIONE"` alle choices di `DocumentoDipendente.tipo`
- [ ] Confermare D10: la formazione rimane dentro `anagrafica/` (assunzione corrente)
- [ ] Aggiungere i **17 modelli** elencati nel "Set Modelli Definitivo" (sezione sopra)
  - Eliminare i campi M2M mansioni/ruoli commentati da `TrainingPlan` (sostituiti da `TrainingRequirementRule`)
  - Aggiungere campi snapshot storici a `TrainingEmployeeRecord`
  - Aggiornare FK docente in `TrainingSession` e `TrainingLesson` → `TrainingInstructor` (nullable)
- [ ] **NON aggiungere** dipendenze PDF (`reportlab`, `weasyprint`) — sono riservate a PATCH-08
- [ ] Creare migrazione: `python manage.py makemigrations anagrafica --name add_training_models`
- [ ] Registrare tutti i modelli in `anagrafica/admin.py` (list_display read-only, nessuna inline complessa)
- [ ] Eseguire `python manage.py migrate`
- [ ] Registrare stub endpoint in `anagrafica/acl_bootstrap.py`
- [ ] Creare stub `anagrafica/services/training_deadline_service.py` con firma vuota `refresh_deadlines()`
- [ ] **Quality gate:** `python manage.py check` → 0 errori
- [ ] **Quality gate:** `python manage.py test anagrafica` → verde

**File da toccare:**
- `django_app/anagrafica/models.py` — aggiunta 17 modelli (o `models_formazione.py` se D1 lo decide)
- `django_app/anagrafica/admin.py` — registrazione admin read-only
- `django_app/anagrafica/migrations/00XX_add_training_models.py` — generato automaticamente
- `django_app/anagrafica/acl_bootstrap.py` — stub endpoint
- `django_app/anagrafica/services/training_deadline_service.py` — nuovo, stub

**File NON da toccare in PATCH-01:**
- `requirements.txt` — nessuna nuova dipendenza
- `django_app/anagrafica/views.py` — nessuna view ancora
- `django_app/anagrafica/urls.py` — nessun URL ancora
- Template — nessun template ancora

---

## TODO PATCH-02 — Dashboard Formazione

> **Prerequisiti:** PATCH-01 completata; D3 confermata (URL `/anagrafica/formazione/` o tab)

- [ ] Confermare D3 prima di iniziare
- [ ] Creare view `formazione_dashboard` in `django_app/anagrafica/views.py`
  - KPI: dipendenti con formazione, scadenze ≤30gg, scaduti, obbligatori mancanti (da `TrainingAssignment` + `TrainingDeadline`)
  - Tabella scadenzario urgente (TOP 20, ordinato per urgenza)
- [ ] Aggiungere URL `formazione/` in `django_app/anagrafica/urls.py`
- [ ] Creare template `django_app/anagrafica/templates/anagrafica/pages/formazione_dashboard.html`
  - Classi CSS: prefisso `fm-*` (non confliggono con `dp-*`)
  - KPI card compatte, tabella densa, pill di stato
- [ ] Aggiungere voce "Formazione" nella subnav (via DB `SubnavLinkAnagrafica` — non hardcoded nel template)
- [ ] Testare accesso con permessi HR Admin
- [ ] **Quality gate:** `python manage.py check` → 0 errori; pagina carica senza errori con DB vuoto

**File da toccare:**
- `django_app/anagrafica/views.py`
- `django_app/anagrafica/urls.py`
- `django_app/anagrafica/templates/anagrafica/pages/formazione_dashboard.html` (nuovo)
- `django_app/anagrafica/acl_bootstrap.py`

---

## TODO PATCH-03 — Piani Formativi e Corsi

> **Prerequisiti:** PATCH-02 completata

- [ ] View e URL: `formazione_piani_list`, `formazione_piano_detail`, `formazione_piano_create`, `formazione_piano_edit`
- [ ] View e URL: `formazione_corsi_list`, `formazione_corso_detail`, `formazione_corso_create`, `formazione_corso_edit`
- [ ] View e URL: `formazione_istruttori_list`, `formazione_istruttore_create`, `formazione_istruttore_edit` (catalogo `TrainingInstructor`)
- [ ] Form: `TrainingPlanForm`, `TrainingCourseForm`, `TrainingInstructorForm`, `TrainingRequirementRuleForm`
- [ ] Gestione `TrainingRequirementRule` inline sul dettaglio corso (non M2M su piano — vedi D4)
- [ ] Gestione prerequisiti corso (`TrainingCourseDependency`)
- [ ] Gestione moduli/composizione corso (`TrainingCourseModule`)
- [ ] Gestione versioni corso (`TrainingCourseVersion`) — inline nella scheda corso
- [ ] Configurazione regole superamento (`TrainingCompletionRule`) — inline nella scheda corso
- [ ] Template: `formazione_piani.html`, `formazione_piano_detail.html`, `formazione_corsi.html`, `formazione_corso_detail.html`
- [ ] **Quality gate:** CRUD completo senza errori, filtri funzionanti

**File da toccare:**
- `django_app/anagrafica/views.py` — 10-12 nuove view
- `django_app/anagrafica/urls.py` — 10-12 nuovi URL
- `django_app/anagrafica/forms.py` — 4 nuovi form
- 4 nuovi template

---

## TODO PATCH-04 — Sessioni e Lezioni

> **Prerequisiti:** PATCH-03 completata

- [ ] View e URL: `formazione_sessioni_list`, `formazione_sessione_detail`, `formazione_sessione_create`, `formazione_sessione_edit`
- [ ] View e URL: `formazione_lezione_detail`, `formazione_lezione_create`, `formazione_lezione_edit`
- [ ] Form: `TrainingSessionForm` (FK docente → `TrainingInstructor`, con autocomplete nome), `TrainingLessonForm`
- [ ] Template: `formazione_sessione_detail.html`, `formazione_lezione_detail.html`
- [ ] Validazione date (data_fine ≥ data_inizio; lezione dentro intervallo sessione)
- [ ] **Quality gate:** creazione sessione e lezioni senza errori; validazione date funzionante

---

## TODO PATCH-05 — Iscritti e Presenze

> **Prerequisiti:** PATCH-04 completata; D6 confermata (import massivo iscritti)

- [ ] Confermare D6 prima di iniziare
- [ ] View: `formazione_sessione_iscritti` — lista iscritti con stato pill
- [ ] View: `formazione_iscrizione_add` — iscrizione singola (+ massiva se D6 lo prevede)
- [ ] View: `formazione_lezione_presenze` — registro presenze per lezione
- [ ] Pannello espandibile **per singola riga** (non drawer, non modale, non panel sotto tutta la tabella)
- [ ] Calcolo automatico `percentuale_presenza` su save `TrainingEnrollment` via service
- [ ] Creazione `TrainingEmployeeRecord` con campi snapshot al completamento dell'iscrizione (stato → COMPLETATO)
- [ ] Chiamata a `training_deadline_service.refresh_deadlines(legacy_id=...)` dopo ogni completamento
- [ ] Export Excel presenze lezione (stub — export completo in PATCH-07)
- [ ] Template: `formazione_iscritti.html`, `formazione_presenze.html`
- [ ] **Quality gate:** iscrizione, presenze, calcolo %, snapshot storici compilati correttamente

---

## TODO PATCH-06 — Storico Dipendente e Scadenzario

> **Prerequisiti:** PATCH-05 completata; D7 confermata (notifiche)

- [ ] **VINCOLO CRITICO:** modificare `dipendente_detail.html` **solo e soltanto** nel blocco `data-tab="formazione"` (righe 377-384) — sostituire il `dp-soon-card` con il partial. Non toccare nessun altro blocco del file.
- [ ] Creare partial `django_app/anagrafica/templates/anagrafica/partials/formazione_tab_dipendente.html`
  - KPI mini: corsi completati, ore totali, corsi in scadenza, attestati
  - Tabella storico corsi (legge da `TrainingEmployeeRecord`)
  - Sezione "Corsi obbligatori mancanti" (legge da `TrainingRequirementRule` vs `TrainingDeadline`)
  - Sezione "Corsi in scadenza" (legge da `TrainingDeadline.stato_scadenza IN [IN_SCADENZA_30, IN_SCADENZA_90]`)
  - Pannello espandibile per riga (non drawer)
  - Bottone "Export storico personale" → view Excel PATCH-07
- [ ] Aggiungere al context di `dipendente_detail` (in `views.py`) solo le query formazione necessarie (no query aggiuntive non usate)
- [ ] Creare view e template `formazione_scadenzario.html` — pagina standalone scadenzario formazione
- [ ] Implementare `django_app/anagrafica/management/commands/refresh_training_deadlines.py`
- [ ] Implementare logica completa in `training_deadline_service.py`
- [ ] Integrare sezione formazione in `scadenzario.html` esistente come nuova tab/sezione (non sovrascrivere le sezioni qualifiche/visite)
- [ ] Confermare D7 e impostare stub notifiche se necessario
- [ ] **Quality gate:** tab formazione scheda dipendente mostra dati corretti; scadenzario filtra correttamente; `dipendente_detail.html` non regredisce sulle altre tab

**File critici — modificare con estrema cura:**
- `django_app/anagrafica/templates/anagrafica/pages/dipendente_detail.html` — **SOLO righe 377-384** (blocco `data-tab="formazione"`)
- `django_app/anagrafica/views.py` — aggiungere solo le variabili formazione al context esistente, senza alterare le query già presenti

---

## TODO PATCH-07 — Export Excel completo

> **Prerequisiti:** PATCH-06 completata

- [ ] Creare `django_app/anagrafica/services/formazione_excel.py`
- [ ] Verificare che `openpyxl` sia già in `requirements.txt` (atteso: sì — già usato nel portale)
- [ ] Implementare tutti gli 8 export con colonne definite in `BOZZA_MODULO_FORMAZIONE.md § F`:
  - [ ] Elenco piani formativi
  - [ ] Elenco corsi
  - [ ] Iscritti a sessione
  - [ ] Presenze lezione
  - [ ] Storico formazione dipendente
  - [ ] Scadenzario formazione
  - [ ] Matrice dipendente × corso obbligatorio (legge da `TrainingRequirementRule` + `TrainingDeadline`)
  - [ ] Report KPI direzionale (multi-foglio)
- [ ] View e URL per ogni export (pattern `HttpResponse` con content_type xlsx)
- [ ] Registrare ogni export in `TrainingExportLog` (tipo, filtri, righe, utente, IP)
- [ ] **Quality gate:** ogni export produce file Excel valido e non vuoto con dati di test; log creato correttamente

---

## TODO PATCH-08 — Report Firma PDF

> **Prerequisiti:** PATCH-07 completata; D8 confermata (libreria PDF scelta e verificata in prod)

- [ ] **Prima di iniziare:** verificare disponibilità libreria PDF nell'ambiente prod (IIS/Windows):
  - Opzione A: `reportlab` — puro Python, nessuna dipendenza di sistema, preferibile per IIS
  - Opzione B: `weasyprint` — richiede librerie di sistema (libpango, libcairo) — verificare compatibilità Windows
  - **Raccomandazione:** `reportlab` per ambienti Windows/IIS
- [ ] Aggiungere libreria scelta a `requirements.txt`
- [ ] Creare `django_app/anagrafica/services/formazione_pdf.py`
- [ ] Implementare layout PDF (vedi `BOZZA_MODULO_FORMAZIONE.md § G`): intestazione, dati corso/sessione/lezione, tabella partecipanti con spazio firma, note, piè di pagina con versione e data generazione
- [ ] View `formazione_registro_firma_pdf(request, lezione_id)` → StreamingHttpResponse PDF
- [ ] URL: `formazione/lezioni/<lid>/registro-firma/pdf/`
- [ ] Registrare export in `TrainingExportLog` (tipo=`REPORT_FIRMA`)
- [ ] **Quality gate:** PDF generato con dati corretti; download funzionante su IIS; layout leggibile e stampabile

---

## TODO PATCH-09 — Hardening, test, permessi, audit

> **Prerequisiti:** PATCH-08 completata

- [ ] Implementare `AnagraficaFormazionePermission` (singleton — pattern identico a `AnagraficaVisiteMedichePermission`)
- [ ] Applicare controllo permesso a tutte le view formazione (decorator o mixin, coerente con il portale)
- [ ] Completare `acl_bootstrap.py` con tutti gli endpoint formazione definitivi
- [ ] Scrivere test suite in `django_app/anagrafica/tests.py` (o file separato `tests_formazione.py`):
  - [ ] Modelli: creazione, vincoli `unique_together`, calcolo `durata_ore` su `TrainingLesson`, snapshot su `TrainingEmployeeRecord`
  - [ ] `TrainingRequirementRule`: vincolo almeno un target tra mansione e ruolo_operativo
  - [ ] `training_deadline_service`: ricalcolo scadenze, stati corretti per ogni scenario
  - [ ] Management command `refresh_training_deadlines`: test con `--all`, `--legacy-id`, `--corso-id`
  - [ ] View: accesso negato senza permessi, CRUD, export
- [ ] **Quality gate finale:**
  - `python manage.py test anagrafica` → verde
  - `python manage.py check` → 0 errori
  - `python manage.py validate_deployment --format json` → OK
  - `python manage.py acl_coverage_report` → nessun endpoint formazione scoperto
  - Review sicurezza: nessun endpoint formazione restituisce dati senza ACL

---

## COME PROSEGUIRE SU ALTRO PC CON VS CODE + CLAUDE

1. Aprire la cartella `y:\Portale Novicrom` in VS Code
2. Aprire Claude Code (estensione VS Code)
3. Leggere **questo file** e `docs/anagrafica/formazione/BOZZA_MODULO_FORMAZIONE.md`
4. Avviare PATCH-01 con questo prompt:

```
Prosegui con PATCH FORMAZIONE-01 del modulo Formazione HR.

Leggi prima:
- docs/anagrafica/formazione/TODO_FORMAZIONE_PROSECUZIONE.md (decisioni D1-D10 e set modelli definitivo)
- docs/anagrafica/formazione/BOZZA_MODULO_FORMAZIONE.md (§ C per struttura modelli)

Decisioni D1, D2, D10 da confermare:
- D1 (schema file): [rispondere qui: models.py unico / models_formazione.py separato]
- D2 (choices DocumentoDipendente): [rispondere qui: sì / no]
- D10 (perimetro app): [rispondere qui: anagrafica / app separata]

Le decisioni D4, D5, D9 sono già definitive (TrainingRequirementRule, TrainingInstructor, management command).
Non aggiungere reportlab/weasyprint in questa patch.
Non creare view né URL in questa patch — solo modelli, migrazione e admin.
```

---

## FILE CHIAVE DEL PROGETTO

| File | Scopo |
|------|-------|
| `django_app/anagrafica/models.py` | Tutti i modelli HR — aggiungere qui i 17 nuovi modelli formazione |
| `django_app/anagrafica/views.py` | Tutte le view — aggiungere le view formazione in fondo |
| `django_app/anagrafica/urls.py` | URL patterns — namespace "anagrafica" |
| `django_app/anagrafica/forms.py` | Form ModelForm |
| `django_app/anagrafica/admin.py` | Registrazione Django Admin |
| `django_app/anagrafica/acl_bootstrap.py` | Bootstrap pulsanti legacy ACL |
| `django_app/anagrafica/storage.py` | PrivateAnagraficaStorage (per attestati) |
| `django_app/anagrafica/services/training_deadline_service.py` | Service layer scadenze (da creare in PATCH-01) |
| `django_app/anagrafica/templates/anagrafica/pages/dipendente_detail.html` | Scheda dipendente — **TAB FORMAZIONE righe 377-384** — solo quelle |
| `django_app/anagrafica/templates/anagrafica/pages/scadenzario.html` | Scadenzario unificato — aggiungere sezione formazione in PATCH-06 |
| `docs/anagrafica/formazione/BOZZA_MODULO_FORMAZIONE.md` | Documento bozza architetturale completo |

---

## COMANDI UTILI

```powershell
# Dev server
python django_app\manage.py runserver --settings=config.settings.dev

# Check Django
python django_app\manage.py check --settings=config.settings.test

# Makemigrations (dopo aggiunta modelli in PATCH-01)
python django_app\manage.py makemigrations anagrafica --name add_training_models --settings=config.settings.dev

# Apply migrations
python django_app\manage.py migrate --settings=config.settings.dev

# Test
python django_app\manage.py test anagrafica --settings=config.settings.test

# ACL report
python django_app\manage.py acl_coverage_report --max-missing 250
python django_app\manage.py bootstrap_acl_v2 --dry-run

# Dopo PATCH-06: refresh scadenze
python django_app\manage.py refresh_training_deadlines --all
python django_app\manage.py refresh_training_deadlines --legacy-id 42
```

---

*Aggiornato da Claude Code — NOVICROM HUB v1.0.2 — 2026-05-22 (rev. decisioni architetturali)*
