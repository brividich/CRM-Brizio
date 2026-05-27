# TODO — Modulo Formazione HR — Lista prosecuzione
## NOVICROM HUB — Anagrafica HR → Sezione Formazione

**Aggiornato:** 2026-05-23 (rev. 10 — import storico pregresso caricato + bugfix template + proposta fattori di rischio)
**Stato progetto:** PATCH-06 completata; servizio import implementato e storico pregresso caricato; PATCH-07 (export) ancora da fare
**Da leggere prima di proseguire:**
- `docs/anagrafica/formazione/BOZZA_MODULO_FORMAZIONE.md`
- `docs/anagrafica/formazione/MAPPING_IMPORT_GESTIONALE.md` (colonne export PATCH-07 derivano da qui)
- `docs/anagrafica/formazione/PROPOSTA_FATTORI_RISCHIO.md` (NUOVO — modellazione scadenze via fattori di rischio)

---

## AGGIORNAMENTO 2026-05-23 — Import storico, bugfix, fattori di rischio

### Import storico pregresso (FATTO)
- Nuovo servizio `anagrafica/services/formazione_import.py` — 4 funzioni path-based
  (`import_piani_formativi`, `import_courses_person`, `import_lezioni_presenze`,
  `import_qualifications_person`), dry-run di default, `transaction.atomic()` su commit.
- Caricato lo storico dai 5 Excel di `docs/anagrafica/formazione/` sul DB SQL Server
  `PORTALE NOVICROM`: **12 piani, 682 corsi, 619 sessioni, 859 lezioni, 3499 iscrizioni,
  4598 presenze, 3399 record completamento, 86 qualifiche** (146 dipendenti distinti).
- Scartate per dati gestionale incompleti: 270 righe corsi senza `Inizio corso`,
  371 righe lezioni con data sentinella `2099-12-31`.
- **Migrazione 0026** — widening campi decimali `models_formazione.py` (overflow su valori
  reali: piano NOVICROM 27.636,9 ore; durate/frequenze fino a 1000,0).

### Bugfix template formazione (FATTO)
- Rimosso accesso a attributi template con underscore iniziale (`_nome`, `_dipendente_nome`,
  `_lezioni_presenze`) — Django li vieta → 500 su corso/piano/iscritti/scadenzario detail.
  Rinominati `nome_dip` / `dipendente_nome` / `lezioni_presenze`.
- Corretto `{{ ...|default:obj.docente.nome }}` in sessioni/sessione_detail: l'arg del filtro
  traversava `.nome` su docente FK nullo → `VariableDoesNotExist`. Ora `default:obj.docente`.
- Verificate 11 pagine formazione → tutte 200.

### Punto aperto — scadenze
I 682 corsi importati hanno `validita_mesi = 0` (il gestionale non porta la frequenza di
rinnovo) → `TrainingDeadline` tutto `UNA_TANTUM`, scadenzario non segnala nulla.
**Decisione presa**: derivare la scadenza dai fattori di rischio invece che da un campo
piatto sul corso. Vedi `PROPOSTA_FATTORI_RISCHIO.md` (modelli `FattoreRischio`,
`CategoriaCorso`, `EsposizioneRischio`; piano PATCH-RISK-01…04). Da validare prima di
scrivere codice — restano aperte le decisioni R1-R5 del documento.

---

## STATO ATTUALE

| # | Patch | Stato | Note |
|---|-------|-------|------|
| 00 | Discovery e documento architettura | ✅ COMPLETATO | `docs/anagrafica/formazione/BOZZA_MODULO_FORMAZIONE.md` |
| 01 | Modelli base e admin read-only | ✅ COMPLETATO | 18 modelli, migrazione 0024, check 0 errori |
| 02 | Dashboard Formazione | ✅ COMPLETATO | View, template, subnav link, quality gate OK |
| 03 | Piani Formativi e Corsi (CRUD) | ✅ COMPLETATO | CRUD piani/corsi/istruttori, regole obbligatorietà, prerequisiti, versioni, regola superamento |
| 04 | Sessioni e Lezioni | ✅ COMPLETATO | CRUD sessioni + lezioni inline, validazione date, snapshot docente |
| 05 | Iscritti e Presenze | ✅ COMPLETATO | Iscrizioni, presenze per lezione, snapshot storici, service calc% |
| 06 | Storico Dipendente e Scadenzario | ✅ COMPLETATO | Service deadline, tab dipendente, scadenzario standalone, integrazione scadenzario esistente |
| 07 | Export Excel completo | ⏳ IN ATTESA | Dipende da PATCH-06 |
| 08 | Report Firma PDF | ⏳ IN ATTESA | Dipende da PATCH-07 |
| 09 | Hardening, test, permessi, audit | ⏳ IN ATTESA | Dipende da PATCH-08 |

---

## DECISIONI ARCHITETTURALI D1-D10

> Tutte le decisioni D1-D10 sono **validate e definitive** al 2026-05-22.
> Non riaprire senza esplicita autorizzazione. PATCH-01 può avviarsi senza ulteriori conferme.

| # | Decisione | Stato | Scelta |
|---|-----------|-------|--------|
| D1 | Schema modelli | ✅ | **`models_formazione.py` separato**, importato da `models.py` — evita di gonfiare il file principale |
| D2 | `DocumentoDipendente.tipo` choices | ✅ | **Sì** — aggiungere `"CERTIFICATO_FORMAZIONE"` se il modello usa choices esplicite; attestati via storage privato esistente |
| D3 | URL base | ✅ | **`/anagrafica/formazione/` dedicato** + tab "Formazione" integrato nella scheda dipendente |
| D4 | Obbligatorietà corsi | ✅ | **`TrainingRequirementRule`** — gestisce obbligo per corso, piano, mansione, reparto/area, singolo dipendente, periodo validità, override rinnovo |
| D5 | Docente | ✅ | **`TrainingInstructor`** — supporta interno (via `legacy_anagrafica_id`) ed esterno (nome, azienda, email, telefono, qualifiche) |
| D6 | Import massivo iscritti | ✅ | **MVP: selezione da UI** — architettura predisposta per import Excel in patch successiva |
| D7 | Notifiche scadenza | ✅ | **MVP: solo portale/scadenzario** — predisporre management command per future email (pattern visite mediche) |
| D8 | PDF report firma | ✅ | **`reportlab`** (ambiente Windows/IIS) — **nessuna dipendenza PDF prima di PATCH-08** |
| D9 | `TrainingDeadline` ricalcolo | ✅ | **Management command + service deterministico** — signal solo per invalidare/marcare, mai fonte operativa |
| D10 | Perimetro app | ✅ | **Rimane dentro `anagrafica/`** — nessuna app Django separata in questa fase |

### Dettaglio D4 — `TrainingRequirementRule`

Sostituisce qualsiasi riferimento a M2M diretto su `TrainingPlan` (mansioni/ruoli) e a `TrainingPlanObligation`.

Supporta target multipli: per **corso**, per **piano**, per **mansione**, per **reparto/area**, per **singolo dipendente**, con **periodo di validità** e **override rinnovo**.

```python
class TrainingRequirementRule(models.Model):
    """Regola di obbligatorietà formativa — può riguardare un corso o un intero piano.
    I target (mansione, area, singolo dipendente) sono mutuamente non esclusivi:
    la stessa regola può valere per una mansione E per un singolo dipendente.
    Vincolo minimo: almeno uno dei target deve essere valorizzato (verificato a livello form).
    """
    # Oggetto della regola: corso singolo OPPURE intero piano (non entrambi)
    corso          = ForeignKey(TrainingCourse, null=True, blank=True, on_delete=CASCADE, related_name="regole_obbligo")
    piano          = ForeignKey(TrainingPlan,   null=True, blank=True, on_delete=CASCADE, related_name="regole_obbligo")

    # Target della regola (uno o più possono essere valorizzati)
    mansione           = ForeignKey("anagrafica.Mansione",        null=True, blank=True, on_delete=CASCADE)
    area               = ForeignKey("anagrafica.AreaAziendale",   null=True, blank=True, on_delete=CASCADE)
    ruolo_operativo    = ForeignKey("anagrafica.RuoloOperativo",  null=True, blank=True, on_delete=CASCADE)
    legacy_anagrafica_id = IntegerField(null=True, blank=True, db_index=True,
                            help_text="Se valorizzato: regola per singolo dipendente")

    # Periodicità: 0 = una tantum, >0 = rinnovo ogni N mesi (override di TrainingCourse.validita_mesi)
    override_frequenza_mesi = PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="Sovrascrive la frequenza del corso. Null = usa la frequenza del corso."
    )

    # Periodo di applicazione della regola (None = sempre attiva)
    data_inizio_validita  = DateField(null=True, blank=True)
    data_fine_validita    = DateField(null=True, blank=True)

    note       = TextField(blank=True)
    is_active  = BooleanField(default=True)
    created_by = ForeignKey(User, null=True, on_delete=SET_NULL, related_name="+")
    created_at = DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Regola di obbligatorietà"
        indexes = [
            Index(fields=["mansione", "is_active"]),
            Index(fields=["area", "is_active"]),
            Index(fields=["legacy_anagrafica_id", "is_active"]),
        ]
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

### `TrainingDeadline` — natura di cache ricalcolabile (D9)

`TrainingDeadline` è una **tabella di cache derivata**, non una fonte di verità primaria.

- **Non modificare manualmente** i record `TrainingDeadline`.
- Il ricalcolo avviene tramite:
  1. **Service layer:** `anagrafica/services/training_deadline_service.py` → funzione `refresh_deadlines(legacy_id=None, corso_id=None)` chiamabile da view o command.
  2. **Management command:** `python manage.py refresh_training_deadlines [--legacy-id <id>] [--corso-id <id>] [--all]`
- **I signal `post_save`** su `TrainingEmployeeRecord` possono essere usati **solo per invalidare o marcare** righe di `TrainingDeadline` come "da ricalcolare" (es. settando un flag `needs_refresh=True`), **mai** come fonte operativa del calcolo. Il ricalcolo effettivo è sempre delegato al management command/service — robusto anche in bulk insert e import da Excel.
- Il command va pianificato come task schedulato (es. notturno) via Windows Task Scheduler o IIS.

---

## TODO PATCH-01 — Modelli base e admin

> **Prerequisiti:** Nessuno — tutte le decisioni D1-D10 sono validate. Questa patch può avviarsi.
>
> Riepilogo decisioni operative per questa patch:
> - **D1:** creare `django_app/anagrafica/models_formazione.py`, importarlo da `models.py`
> - **D2:** aggiungere `"CERTIFICATO_FORMAZIONE"` alle choices di `DocumentoDipendente.tipo`
> - **D8:** non aggiungere `reportlab` né `weasyprint` — nessuna dipendenza PDF
> - **D10:** la formazione rimane dentro `anagrafica/`

- [x] Aggiungere i **18 modelli** in `django_app/anagrafica/models_formazione.py`
  - Campi M2M mansioni/ruoli rimossi da `TrainingPlan` — sostituiti da `TrainingRequirementRule`
  - Campi snapshot storici aggiunti a `TrainingEmployeeRecord`
  - FK docente in `TrainingSession` e `TrainingLesson` → `TrainingInstructor` (nullable) + `docente_nome` snapshot
- [x] **NON aggiunto** reportlab/weasyprint — riservati a PATCH-08
- [x] Migrazione generata: `0024_add_training_models.py`
- [x] Registrati tutti i 18 modelli in `anagrafica/admin.py` (list_display read-only, nessuna inline complessa)
- [ ] `python manage.py migrate` — da eseguire a cura dell'operatore sulla macchina con SQL Server
- [x] Registrati stub endpoint in `anagrafica/acl_bootstrap.py` (7 entry formazione, hide=True)
- [x] Creato stub `anagrafica/services/training_deadline_service.py` con `refresh_deadlines()` NotImplementedError
- [x] **Quality gate:** `python manage.py check --settings=config.settings.test` → 0 errori
- [x] **Quality gate:** `python manage.py makemigrations --check --dry-run` → No changes detected
- [ ] **Quality gate:** `python manage.py test anagrafica --settings=config.settings.test` → verde (test da scrivere in PATCH-09)

**File toccati (PATCH-01 completata 2026-05-22):**
- `django_app/anagrafica/models_formazione.py` — **nuovo file** con 18 modelli ✅
- `django_app/anagrafica/models.py` — aggiunto `CERTIFICATO_FORMAZIONE` a `DocumentoDipendente.Tipo` + `from .models_formazione import *` ✅
- `django_app/anagrafica/admin.py` — registrazione admin read-only per tutti i 18 modelli ✅
- `django_app/anagrafica/migrations/0024_add_training_models.py` — generato ✅
- `django_app/anagrafica/acl_bootstrap.py` — 7 stub endpoint formazione (hide=True) ✅
- `django_app/anagrafica/services/training_deadline_service.py` — nuovo, stub con NotImplementedError ✅

**File NON da toccare in PATCH-01:**
- `requirements.txt` — nessuna nuova dipendenza (no reportlab, no weasyprint — D8)
- `django_app/anagrafica/views.py` — nessuna view ancora
- `django_app/anagrafica/urls.py` — nessun URL ancora
- Template — nessun template ancora

---

## TODO PATCH-02 — Dashboard Formazione

> **Prerequisiti:** PATCH-01 completata; D3 confermata (URL `/anagrafica/formazione/` o tab)

- [x] Confermare D3 — URL `/anagrafica/formazione/` dedicato
- [x] Creare view `formazione_dashboard` in `django_app/anagrafica/views.py`
  - KPI: dipendenti con formazione, scadenze ≤30gg, scaduti, obbligatori mancanti, piani attivi, corsi attivi
  - Tabella scadenzario urgente (TOP 20, ordinato per urgenza)
  - Banner `fm-cache-banner` quando `TrainingDeadline` è vuota
- [x] Aggiungere URL `formazione/` in `django_app/anagrafica/urls.py`
- [x] Creare template `django_app/anagrafica/templates/anagrafica/pages/formazione_dashboard.html`
  - Classi CSS: prefisso `fm-*` (non confliggono con `dp-*`)
  - KPI card compatte, tabella densa, pill di stato, tag giorni
- [x] Aggiungere voce "Formazione" nella subnav (via data migration `0025_subnav_formazione.py`)
- [x] **Quality gate:** `python manage.py check --settings=config.settings.test` → 0 errori
- [x] **Quality gate:** `python manage.py makemigrations --check --dry-run` → No changes detected

**File toccati (PATCH-02 completata 2026-05-22):**
- `django_app/anagrafica/views.py` — import modelli formazione, `_can_view_formazione()`, `formazione_dashboard()` ✅
- `django_app/anagrafica/urls.py` — aggiunto `path("formazione/", ...)` ✅
- `django_app/anagrafica/templates/anagrafica/pages/formazione_dashboard.html` — nuovo template ✅
- `django_app/anagrafica/migrations/0025_subnav_formazione.py` — data migration subnav link ✅

---

## TODO PATCH-03 — Piani Formativi e Corsi

> **Prerequisiti:** PATCH-02 completata

- [x] View e URL: `formazione_piani_list`, `formazione_piano_detail`, `formazione_piano_create`, `formazione_piano_edit`, `formazione_piano_delete`
- [x] View e URL: `formazione_corsi_list`, `formazione_corso_detail`, `formazione_corso_create`, `formazione_corso_edit`, `formazione_corso_delete`
- [x] View e URL: `formazione_istruttori_list`, `formazione_istruttore_create`, `formazione_istruttore_edit`, `formazione_istruttore_delete`
- [x] Form: `TrainingPlanForm`, `TrainingCourseForm`, `TrainingInstructorForm`, `TrainingRequirementRuleForm`, `TrainingCompletionRuleForm`, `TrainingCourseVersionForm`, `TrainingCourseDependencyForm`
- [x] Gestione `TrainingRequirementRule` inline sul dettaglio corso
- [x] Gestione prerequisiti corso (`TrainingCourseDependency`) — add/remove inline
- [x] Gestione versioni corso (`TrainingCourseVersion`) — inline nella scheda corso
- [x] Configurazione regola superamento (`TrainingCompletionRule`) — form inline nella scheda corso
- [x] Template: `formazione_piani.html`, `formazione_piano_detail.html`, `formazione_corsi.html`, `formazione_corso_detail.html`, `formazione_corso_form.html`, `formazione_istruttori.html`
- [x] Partial condiviso: `anagrafica/partials/_fm_form_fields.html`
- [x] Helper view `_can_edit_formazione()` con pattern identico a `_can_view_formazione`
- [x] **Quality gate:** `manage.py check --settings=config.settings.test` → 0 errori; `makemigrations --check --dry-run` → No changes

**File toccati (PATCH-03 completata 2026-05-22):**
- `django_app/anagrafica/forms.py` — 7 nuovi form formazione ✅
- `django_app/anagrafica/views.py` — import espanso + `_can_edit_formazione` + 14 view CRUD ✅
- `django_app/anagrafica/urls.py` — 21 nuovi URL formazione ✅
- `django_app/anagrafica/templates/anagrafica/pages/formazione_piani.html` — nuovo ✅
- `django_app/anagrafica/templates/anagrafica/pages/formazione_piano_detail.html` — nuovo ✅
- `django_app/anagrafica/templates/anagrafica/pages/formazione_corsi.html` — nuovo ✅
- `django_app/anagrafica/templates/anagrafica/pages/formazione_corso_detail.html` — nuovo ✅
- `django_app/anagrafica/templates/anagrafica/pages/formazione_corso_form.html` — nuovo ✅
- `django_app/anagrafica/templates/anagrafica/pages/formazione_istruttori.html` — nuovo ✅
- `django_app/anagrafica/templates/anagrafica/partials/_fm_form_fields.html` — nuovo ✅

---

## TODO PATCH-04 — Sessioni e Lezioni

> **Prerequisiti:** PATCH-03 completata

- [x] View e URL: `formazione_sessioni_list`, `formazione_sessione_detail`, `formazione_sessione_create`, `formazione_sessione_edit`, `formazione_sessione_delete`
- [x] View e URL: `formazione_lezione_add`, `formazione_lezione_edit`, `formazione_lezione_delete` (inline nella sessione)
- [x] Form: `TrainingSessionForm` (FK docente → `TrainingInstructor`, snapshot `docente_nome` automatico), `TrainingLessonForm` (con validazione ora_fine > ora_inizio e data dentro intervallo sessione)
- [x] Template: `formazione_sessioni.html`, `formazione_sessione_detail.html`, `formazione_sessione_form.html`
- [x] Validazione date: `data_fine ≥ data_inizio` in `TrainingSessionForm`; lezione fuori intervallo → errore campo
- [x] Bugfix PATCH-03: `formazione_istruttore_delete` usava `related_name` errati (`sessioni_docente/lezioni_docente` → `sessioni/lezioni`)
- [x] **Quality gate:** `manage.py check --settings=config.settings.test` → 0 errori

**File toccati (PATCH-04 completata 2026-05-22):**
- `django_app/anagrafica/forms.py` — aggiunto `TrainingSessionForm`, `TrainingLessonForm`; bugfix import ✅
- `django_app/anagrafica/views.py` — bugfix related_name + import + 8 view sessioni/lezioni ✅
- `django_app/anagrafica/urls.py` — 8 nuovi URL sessioni/lezioni ✅
- `django_app/anagrafica/templates/anagrafica/pages/formazione_sessioni.html` — nuovo ✅
- `django_app/anagrafica/templates/anagrafica/pages/formazione_sessione_detail.html` — nuovo ✅
- `django_app/anagrafica/templates/anagrafica/pages/formazione_sessione_form.html` — nuovo ✅

---

## TODO PATCH-05 — Iscritti e Presenze

> **Prerequisiti:** PATCH-04 completata.
>
> D6 definita: **MVP = selezione da UI** — l'import massivo da Excel è predisposto ma non implementato in questa patch.

- [x] View: `formazione_sessione_iscritti` — lista iscritti con stato pill e griglia presenze per lezione (expand per riga)
- [x] View: `formazione_iscrizione_add` — iscrizione singola (selezione da lista dipendenti via UI)
- [x] View: `formazione_iscrizione_edit` — modifica stato/ore/presenza/idoneo/esito (modal JS)
- [x] View: `formazione_iscrizione_delete` — rimozione iscrizione
- [x] **Predisposto architettura import Excel** in `formazione_excel.py` con stub `import_iscritti_from_xlsx()` — implementazione in PATCH-07
- [x] View: `formazione_lezione_presenze` — registro presenze per lezione (expand form per riga)
- [x] View: `formazione_presenza_set` — registra/modifica presenza singola (POST)
- [x] Pannello espandibile **per singola riga** (non drawer, non modale) in iscritti e presenze
- [x] Helper `_calcola_percentuale_presenza(enrollment)` — calcolo % su ore effettive/presenziate
- [x] Helper `_crea_employee_record(enrollment, created_by)` — snapshot storici (11 campi) al completamento
- [x] Helper `_add_months(dt, months)` — aritmetica mesi senza dateutil
- [x] Chiamata a `training_deadline_service.refresh_deadlines(legacy_id=...)` dopo ogni completamento (try/except NotImplementedError per stub)
- [x] Aggiunto `i._lezioni_presenze` (zip lezioni + stati) per griglia template
- [x] Aggiunto `n_presenti` al context di `formazione_lezione_presenze`
- [x] Form: `TrainingEnrollmentEditForm`, `TrainingLessonAttendanceForm`
- [x] URL: 6 nuovi path per iscritti e presenze
- [x] Template: `formazione_iscritti.html`, `formazione_presenze.html`
- [x] **Quality gate:** `python manage.py check --settings=config.settings.test` → 0 errori

**File toccati (PATCH-05 completata 2026-05-22):**
- `django_app/anagrafica/services/formazione_excel.py` — nuovo stub `import_iscritti_from_xlsx()` ✅
- `django_app/anagrafica/forms.py` — aggiunto `TrainingEnrollmentEditForm`, `TrainingLessonAttendanceForm` ✅
- `django_app/anagrafica/views.py` — helper `_add_months`, `_calcola_percentuale_presenza`, `_crea_employee_record` + 6 view iscritti/presenze + augment context (`_lezioni_presenze`, `n_presenti`) ✅
- `django_app/anagrafica/urls.py` — 6 nuovi URL iscritti/presenze ✅
- `django_app/anagrafica/templates/anagrafica/pages/formazione_iscritti.html` — nuovo ✅
- `django_app/anagrafica/templates/anagrafica/pages/formazione_presenze.html` — nuovo ✅

---

## TODO PATCH-06 — Storico Dipendente e Scadenzario

> **Prerequisiti:** PATCH-05 completata.
>
> D7 definita: **MVP = solo portale/scadenzario** — predisporre management command stub per future notifiche email.

- [x] **VINCOLO CRITICO:** sostituito `dp-soon-card` in `dipendente_detail.html` (solo righe 377-384) con `{% include "partials/formazione_tab_dipendente.html" %}`
- [x] Creato partial `formazione_tab_dipendente.html`:
  - KPI mini: corsi completati, ore totali, corsi in scadenza, attestati
  - Sezione scadenze urgenti (SCADUTO / IN_SCADENZA_30 / IN_SCADENZA_90 / MAI_FREQUENTATO)
  - Tabella storico completamenti (ultimi 30, expand per riga con snapshot)
  - Fallback `dp-soon-card` per utenti senza `_can_view_formazione`
  - Link a scadenzario formazione standalone
- [x] Aggiunto blocco `can_view_formazione_tab` + 6 variabili formazione al context di `dipendente_detail` (sotto gate `_can_view_formazione`, try/except)
- [x] Aggiunto `TrainingCertificate` agli import di `views.py`
- [x] Implementato `training_deadline_service.refresh_deadlines()`:
  - Scan `TrainingEmployeeRecord` (idoneo=True) → calcola stato_scadenza da data_scadenza vs oggi
  - Gestisce regole `TrainingRequirementRule` per singolo dipendente → MAI_FREQUENTATO se nessun record
  - TODO PATCH-09: cross-reference mansione/area/ruolo con AnagraficaDipendente
- [x] Creato `management/commands/refresh_training_deadlines.py` (opzioni `--all`, `--legacy-id`, `--corso-id`)
- [x] Creato stub `management/commands/send_training_expiry_reminders.py` (nessun invio email — PATCH-09)
- [x] Creata view `formazione_scadenzario` (filtri: stato, corso, dipendente; paginazione 50/pag; KPI globali)
- [x] Aggiunto URL `/anagrafica/formazione/scadenzario/` → `formazione_scadenzario`
- [x] Creato template `formazione_scadenzario.html` (KPI, filtri, tabella sortable)
- [x] Integrato riepilogo formazione in `scadenzario.html` (nuova card in fondo, non invasiva)
- [x] Aggiornato `scadenzario` view con `fm_n_scaduti/30gg/90gg/fm_is_cache_empty` sotto `_can_view_formazione`
- [x] **Quality gate:** `python manage.py check --settings=config.settings.test` → 0 errori

**File toccati (PATCH-06 completata 2026-05-22):**
- `django_app/anagrafica/services/training_deadline_service.py` — implementato `refresh_deadlines()` ✅
- `django_app/anagrafica/management/commands/refresh_training_deadlines.py` — nuovo ✅
- `django_app/anagrafica/management/commands/send_training_expiry_reminders.py` — nuovo stub ✅
- `django_app/anagrafica/views.py` — import `TrainingCertificate` + contesto formazione `dipendente_detail` + `formazione_scadenzario` view + `scadenzario` view aggiornato ✅
- `django_app/anagrafica/urls.py` — 1 nuovo URL `formazione_scadenzario` ✅
- `django_app/anagrafica/templates/anagrafica/partials/formazione_tab_dipendente.html` — nuovo ✅
- `django_app/anagrafica/templates/anagrafica/pages/formazione_scadenzario.html` — nuovo ✅
- `django_app/anagrafica/templates/anagrafica/pages/dipendente_detail.html` — solo righe 377-384 patched ✅
- `django_app/anagrafica/templates/anagrafica/pages/scadenzario.html` — aggiunta card formazione in fondo ✅

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
4. Avviare **PATCH-01** copiando e incollando questo prompt (tutte le decisioni sono già dentro):

```
Prosegui con PATCH FORMAZIONE-01 del modulo Formazione HR.

Leggi prima (obbligatorio, non saltare):
- docs/anagrafica/formazione/TODO_FORMAZIONE_PROSECUZIONE.md
- docs/anagrafica/formazione/BOZZA_MODULO_FORMAZIONE.md (§ C per struttura modelli)

Decisioni D1-D10 tutte validate — riassunte:
- D1: creare django_app/anagrafica/models_formazione.py (non modificare models.py se non per import e choices)
- D2: aggiungere "CERTIFICATO_FORMAZIONE" alle choices di DocumentoDipendente.tipo
- D3: URL dedicato /anagrafica/formazione/ (ma non in questa patch — solo modelli)
- D4: TrainingRequirementRule con campi corso/piano, mansione/area/ruolo_operativo/legacy_id, override_frequenza_mesi, date validità
- D5: TrainingInstructor con tipo interno/esterno, legacy_anagrafica_id, email, telefono, qualifiche
- D6: MVP iscrizione da UI; stub import Excel predisposto ma non implementato
- D7: MVP solo portale; stub command email ma nessun invio
- D8: reportlab scelto per PDF — NON aggiungere in questa patch
- D9: management command + service; signal solo per invalidare flag
- D10: tutto dentro anagrafica/, nessuna app separata

Obiettivo PATCH-01: solo modelli, migrazione, admin read-only, stub service.
Nessuna view, nessun URL, nessun template, nessuna dipendenza nuova in requirements.txt.
```

5. Per le patch successive (02-09) usare lo stesso prompt sostituendo il numero di patch e leggendo il relativo TODO.

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
