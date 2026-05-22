# BOZZA — Modulo FORMAZIONE HR
## NOVICROM HUB — Anagrafica HR → Sezione Formazione

**Versione bozza:** 0.1.0 (2026-05-22)
**Stato:** PROGETTAZIONE — nessuna migrazione applicata, nessuna modifica distruttiva
**Autore:** Claude Code (proposta architetturale)
**Da validare con:** HR Admin, RSPP, Direzione

---

## A) ANALISI DEL CONTESTO ATTUALE

### A.1 — Dove si trova il modulo Anagrafica HR

```
django_app/
└── anagrafica/
    ├── apps.py               # AppConfig — bootstrap ACL all'avvio
    ├── models.py             # ~1500 righe — tutti i modelli HR
    ├── views.py              # ~2000 righe — view logiche
    ├── urls.py               # ~40 endpoint, namespace "anagrafica"
    ├── forms.py              # ModelForm per i modelli
    ├── admin.py              # Django Admin
    ├── acl_bootstrap.py      # Bootstrap pulsanti legacy ACL
    ├── storage.py            # PrivateAnagraficaStorage (file privati fuori webroot)
    ├── services/             # Logica di servizio (visite, dpi_ingresso)
    ├── templatetags/         # anagrafica_extras.py — filtri template
    ├── management/commands/  # import_cedolini, import_dipendenti_xlsx, ecc.
    ├── migrations/           # 23 migration applicate
    └── templates/anagrafica/
        ├── components/       # subnav.html, page_header.html, flash_messages.html
        ├── pages/            # dipendente_detail.html, index.html, qualifiche_list.html, ...
        └── partials/         # partial per form e componenti riutilizzabili
```

### A.2 — Chiave di collegamento dipendente

Il portale usa **`legacy_anagrafica_id: IntegerField`** come chiave di collegamento tra tutti i modelli HR e il record legacy. Non esiste una FK diretta a `User` per i dati del dipendente — la join avviene a livello applicativo tramite questo intero.

Pattern:
```python
legacy_anagrafica_id = models.IntegerField(db_index=True)
```

Tutti i nuovi modelli Formazione **devono usare lo stesso pattern** per coerenza con `DipendenteQualifica`, `VisitaMedica`, `DocumentoDipendente`, ecc.

### A.3 — Modelli HR di riferimento più vicini per pattern

| Modello di riferimento | Pattern replicabile |
|---|---|
| `TipoQualifica` + `DipendenteQualifica` | Catalogo tipo + assegnazione dipendente |
| `TipoVisitaMedica` + `VisitaMedica` | Catalogo + record con scadenza calcolata |
| `DocumentoDipendente` | Allegati privati via PrivateAnagraficaStorage |
| `VisitaMedica.esito` (ChoiceField) | Stato esito con pill di colore |
| `AnagraficaVisiteMedichePermission` (singleton) | Permesso di accesso singleton |

### A.4 — Il tab "Formazione" esiste già

In `templates/anagrafica/pages/dipendente_detail.html` (righe 369-384):
```html
<button type="button" class="dp-tab" data-tab-target="formazione">🎓 Formazione</button>
...
<div class="dp-soon-card" data-tab="formazione">
  <div class="dp-soon-badge">In arrivo</div>
  ...La gestione dei corsi e degli attestati di formazione sarà disponibile...
</div>
```

**Il tab è già presente come placeholder.** La PATCH FORMAZIONE-02 sostituirà il placeholder con contenuto reale.

### A.5 — Storage privato

Il modulo usa `PrivateAnagraficaStorage` in `anagrafica/storage.py`. Gli attestati di formazione devono essere salvati tramite questo storage (o uno dedicato `PrivateFormazioneStorage`) per garantire accesso ACL-gated come i referti visite mediche.

### A.6 — Navigation sub-menu

Il menu orizzontale di Anagrafica HR è gestito da DB via:
- `SubnavCategoriaAnagrafica` — Categorie dropdown
- `SubnavLinkAnagrafica` — Voci di menu

La voce "Formazione" andrà aggiunta tramite admin o fixture, **non hardcoded**, per rispettare il pattern esistente.

### A.7 — Permessi singleton esistenti

Pattern di riferimento:
```python
class AnagraficaVisiteMedichePermission(models.Model):
    # Singleton — chi può vedere/gestire le visite mediche
    class Meta:
        verbose_name = "Permesso accesso visite mediche"
```

Servirà un modello analogo `AnagraficaFormazionePermission`.

### A.8 — Scadenzario unificato

Il template `scadenzario.html` già aggrega qualifiche + visite mediche. La formazione deve integrarsi in questo scadenzario **aggiungendo una sezione**, non creando una pagina separata per le scadenze.

### A.9 — Cosa NON deve essere toccato

- `core/` — auth, middleware, ACL v2, navigation_registry
- Modelli esistenti in `anagrafica/models.py` — nessuna modifica alle classi esistenti
- `acl_bootstrap.py` esistente — solo aggiunta di nuovi entry
- Template esistenti fuori dal tab formazione e dalla nuova sezione
- `dpi/`, `diario_preposto/`, `procedure_refresh/` — moduli non coinvolti
- Routing globale `config/urls.py` — solo `anagrafica/urls.py` sarà esteso
- Migrazioni già applicate

---

## B) PROPOSTA FUNZIONALE

### B.1 — Dashboard Formazione (`/anagrafica/formazione/`)

**Scopo:** Vista operativa HR per monitorare lo stato complessivo della formazione aziendale.

**Sezioni:**
- **KPI card compatte** (riga superiore):
  - Totale dipendenti con formazione attiva
  - Corsi in scadenza (≤ 30 giorni)
  - Corsi scaduti
  - Corsi obbligatori non completati
  - Attestati mancanti
  - Ore formazione erogate YTD
- **Tabella "Urgente"**: dipendenti con scadenze entro 30 giorni, ordinati per urgenza
- **Grafico mini pill per piano formativo**: completamento % per piano
- **Azioni rapide**: Nuovo corso, Nuova sessione, Export Excel scadenzario
- **Filtri**: Area aziendale, Mansione, Piano formativo, Stato

### B.2 — Piani Formativi (`/anagrafica/formazione/piani/`)

**Scopo:** Catalogo dei macro-contenitori di corsi.

**Colonne tabella:**
- Codice piano | Nome | Categoria | N° corsi | Ore totali | Dipendenti assegnati | % completamento | Stato | Azioni

**Azioni per riga:**
- Visualizza dettaglio
- Modifica
- Archivia

**Filtri:** Categoria, Stato, Obbligatorietà

### B.3 — Dettaglio Piano Formativo (`/anagrafica/formazione/piani/<id>/`)

**Tab interne:**
1. **Info piano** — descrizione, categoria, obbligatorietà per ruolo/mansione, note
2. **Corsi nel piano** — lista corsi con stato, durata, scadenza tipo
3. **Assegnazioni** — dipendenti assegnati + stato completamento aggregato
4. **Statistiche** — ore erogate, % completamento, costi stimati

### B.4 — Corsi (`/anagrafica/formazione/corsi/`)

**Colonne tabella:**
- Codice | Titolo | Piano formativo | Durata | Validità | Obbligatorio | Stato | Sessioni attive | Azioni

**Azioni per riga:**
- Dettaglio
- Nuova sessione
- Iscrivi dipendenti
- Export iscritti

**Filtri:** Piano formativo, Stato, Obbligatorietà, Validità (scaduto/in scadenza/valido)

### B.5 — Dettaglio Corso (`/anagrafica/formazione/corsi/<id>/`)

**Tab interne:**
1. **Info corso** — codice, titolo, descrizione, durata teorica, validità, obbligatorietà, prerequisiti, note
2. **Moduli** — sotto-corsi/moduli che compongono il corso
3. **Sessioni** — lista sessioni con stato, date, iscritti
4. **Iscritti globali** — tutti i dipendenti mai iscritti con storico completamenti
5. **Regole di superamento** — configurazione criteri (ore minime, % presenza, esame, ecc.)
6. **Versioni/revisioni** — storico revisioni del corso

### B.6 — Sessioni Corso (`/anagrafica/formazione/sessioni/` + `/anagrafica/formazione/corsi/<id>/sessioni/<sid>/`)

**Dati sessione:**
- Codice sessione | Corso | Data inizio/fine | Sede/Aula/Link | Docente | Stato | N° iscritti | N° lezioni | Azioni

**Azioni:**
- Aggiungi iscritti
- Gestisci lezioni
- Export presenze
- Genera report firma PDF

### B.7 — Lezioni Sessione (`/anagrafica/formazione/sessioni/<sid>/lezioni/<lid>/`)

**Vista lezione:**
- Dati lezione (data, ora inizio/fine, durata, argomento, docente)
- Tabella presenti/assenti (riga per partecipante, checkbox presenza, note)
- Panel espandibile sotto la riga di ogni partecipante (non sotto tutta la tabella):
  - Note presenza, motivo assenza, firma digitale futura
- Bottone "Genera report firma" → PDF/Excel
- Indicatore % presenza real-time

### B.8 — Partecipanti / Iscritti (`/anagrafica/formazione/sessioni/<sid>/iscritti/`)

**Tabella iscritti:**
- Dipendente | Mansione | Area | Stato iscrizione | Ore frequentate | % presenza | Idoneità | Attestato | Data completamento | Prossima scadenza | Azioni

**Stati iscrizione pill:**
- `Iscritto` (blu) | `In corso` (azzurro) | `Completato` (verde) | `Non idoneo` (rosso) | `Assente` (arancio) | `Ritirato` (grigio)

### B.9 — Registro Presenze / Firme

**Accesso:** da lezione o da sessione → bottone "Registro presenze"

**Dati mostrati:**
- Header: Titolo corso, Piano, Sessione, Lezione, Data, Orario, Docente
- Tabella partecipanti: Matricola | Cognome Nome | Mansione | Firma ingresso | Firma uscita | Presente (sì/no) | Note
- Bottone "Genera PDF registro" (placeholder in PATCH-08)
- Bottone "Export Excel registro"

### B.10 — Scadenzario Formazione (`/anagrafica/formazione/scadenzario/`)

**Vista unificata** (integrabile in `scadenzario.html` esistente come nuova sezione tab).

**Filtri:**
- Dipendente | Area | Mansione | Piano formativo | Tipo scadenza | Periodo (data da/a)

**Colonne:**
- Dipendente | Mansione | Corso | Piano | Data scadenza | Giorni mancanti | Stato | Obbligatorio | Ultima frequenza | Azione

**Pill scadenza:**
- `Scaduto` (rosso) | `In scadenza ≤30gg` (arancio) | `In scadenza ≤90gg` (giallo) | `Valido` (verde) | `Mai frequentato` (grigio)

### B.11 — Storico Formazione Dipendente

**Accesso:** Tab "Formazione" in `dipendente_detail.html` (sostituisce il placeholder).

**Contenuto tab:**
- KPI mini: corsi completati | ore totali | corsi in scadenza | attestati
- Tabella storico corsi: Corso | Piano | Data completamento | Ore frequentate | % presenza | Esito | Attestato | Scadenza
- Panel espandibile per ogni corso → dettaglio sessione/lezioni frequentate
- Bottone "Export storico formazione" (Excel per singolo dipendente)
- Sezione "Corsi obbligatori mancanti" (evidenziata se presente)
- Sezione "Corsi in scadenza" per quel dipendente

### B.12 — Report ed Export Excel

Vedi sezione F del presente documento.

---

## C) PROPOSTA MODELLO DATI DJANGO

> **Nota:** Tutti i modelli proposti sono da aggiungere in `anagrafica/models.py`
> oppure in un nuovo file `anagrafica/models_formazione.py` (da importare in `models.py`).
> **Nessuna migrazione applicata in questa fase.**

```python
# =============================================================================
# FORMAZIONE HR — Modelli proposti (BOZZA, non applicare migrazione)
# =============================================================================

import uuid
from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


# ─────────────────────────────────────────────────────────────
# 1. PIANO FORMATIVO
# ─────────────────────────────────────────────────────────────

class TrainingPlan(models.Model):
    """Macro-contenitore di corsi (es. 'Sistemi Informatici', 'Sicurezza', 'ESG')."""

    CATEGORIA_CHOICES = [
        ("OBBLIGATORIA",   "Obbligatoria"),
        ("CONSIGLIATA",    "Consigliata"),
        ("FACOLTATIVA",    "Facoltativa"),
    ]

    codice            = models.CharField(max_length=20, unique=True)
    nome              = models.CharField(max_length=200)
    categoria         = models.CharField(max_length=20, choices=CATEGORIA_CHOICES, default="CONSIGLIATA")
    descrizione       = models.TextField(blank=True)
    note_operative    = models.TextField(blank=True)
    # Obbligatorietà per mansione/ruolo: relazione M2M, da aggiungere in PATCH-03
    # mansioni_obbligatorie  = models.ManyToManyField("anagrafica.Mansione", blank=True)
    # ruoli_obbligatori      = models.ManyToManyField("anagrafica.RuoloOperativo", blank=True)
    ore_totali_stimate  = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    costo_stimato       = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    provider_esterno    = models.BooleanField(default=False)
    is_active           = models.BooleanField(default=True)
    created_at          = models.DateTimeField(auto_now_add=True)
    updated_at          = models.DateTimeField(auto_now=True)
    created_by          = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["nome"]
        verbose_name = "Piano formativo"
        verbose_name_plural = "Piani formativi"
        indexes = [models.Index(fields=["categoria", "is_active"])]

    def __str__(self):
        return f"[{self.codice}] {self.nome}"


# ─────────────────────────────────────────────────────────────
# 2. CORSO
# ─────────────────────────────────────────────────────────────

class TrainingCourse(models.Model):
    """Corso formativo, appartenente a un piano."""

    STATO_CHOICES = [
        ("BOZZA",      "Bozza"),
        ("ATTIVO",     "Attivo"),
        ("ARCHIVIATO", "Archiviato"),
    ]

    piano               = models.ForeignKey(TrainingPlan, on_delete=models.PROTECT, related_name="corsi")
    codice              = models.CharField(max_length=30, unique=True)
    titolo              = models.CharField(max_length=300)
    descrizione         = models.TextField(blank=True)
    durata_ore_teorica  = models.DecimalField(max_digits=5, decimal_places=2)
    # Validità: 0 = una tantum (nessun rinnovo), >0 = rinnovo ogni N mesi
    validita_mesi       = models.PositiveSmallIntegerField(
        default=0,
        help_text="0 = una tantum, altrimenti durata in mesi prima del rinnovo"
    )
    obbligatorio        = models.BooleanField(default=False)
    costo_unitario      = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    stato               = models.CharField(max_length=15, choices=STATO_CHOICES, default="BOZZA")
    note                = models.TextField(blank=True)
    versione            = models.CharField(max_length=10, default="1.0")
    is_active           = models.BooleanField(default=True)
    created_at          = models.DateTimeField(auto_now_add=True)
    updated_at          = models.DateTimeField(auto_now=True)
    created_by          = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["titolo"]
        verbose_name = "Corso formativo"
        verbose_name_plural = "Corsi formativi"
        indexes = [
            models.Index(fields=["piano", "stato"]),
            models.Index(fields=["obbligatorio", "is_active"]),
        ]

    def __str__(self):
        return f"[{self.codice}] {self.titolo}"


# ─────────────────────────────────────────────────────────────
# 3. PREREQUISITI CORSO
# ─────────────────────────────────────────────────────────────

class TrainingCourseDependency(models.Model):
    """Prerequisito: il corso A è prerequisito per il corso B."""

    corso_principale  = models.ForeignKey(TrainingCourse, on_delete=models.CASCADE, related_name="prerequisiti")
    prerequisito      = models.ForeignKey(TrainingCourse, on_delete=models.CASCADE, related_name="sblocca_corsi")
    obbligatorio      = models.BooleanField(default=True)

    class Meta:
        unique_together = [("corso_principale", "prerequisito")]
        verbose_name = "Prerequisito corso"

    def __str__(self):
        return f"{self.prerequisito.codice} → {self.corso_principale.codice}"


# ─────────────────────────────────────────────────────────────
# 4. COMPOSIZIONE CORSO (moduli / sotto-corsi)
# ─────────────────────────────────────────────────────────────

class TrainingCourseModule(models.Model):
    """Un corso può essere composto da sotto-moduli."""

    corso_padre     = models.ForeignKey(TrainingCourse, on_delete=models.CASCADE, related_name="moduli")
    corso_modulo    = models.ForeignKey(TrainingCourse, on_delete=models.PROTECT, related_name="usato_come_modulo")
    ordine          = models.PositiveSmallIntegerField(default=0)
    obbligatorio    = models.BooleanField(default=True)

    class Meta:
        unique_together = [("corso_padre", "corso_modulo")]
        ordering = ["ordine"]
        verbose_name = "Modulo corso"

    def __str__(self):
        return f"{self.corso_padre.codice} → modulo {self.corso_modulo.codice}"


# ─────────────────────────────────────────────────────────────
# 5. REGOLA DI SUPERAMENTO
# ─────────────────────────────────────────────────────────────

class TrainingCompletionRule(models.Model):
    """Regole configurabili di superamento per un corso."""

    corso                       = models.OneToOneField(TrainingCourse, on_delete=models.CASCADE, related_name="regola_superamento")
    ore_minime_percentuale      = models.PositiveSmallIntegerField(
        default=80,
        help_text="Percentuale minima di ore frequentate rispetto al totale"
    )
    presenza_minima_percentuale = models.PositiveSmallIntegerField(
        default=80,
        help_text="Percentuale minima di presenze alle lezioni"
    )
    richiede_esame_finale       = models.BooleanField(default=False)
    richiede_firma_presenza     = models.BooleanField(default=True)
    richiede_caricamento_attestato = models.BooleanField(default=False)
    richiede_validazione_hr     = models.BooleanField(default=False)
    note                        = models.TextField(blank=True)

    class Meta:
        verbose_name = "Regola di superamento"


# ─────────────────────────────────────────────────────────────
# 6. SESSIONE
# ─────────────────────────────────────────────────────────────

class TrainingSession(models.Model):
    """Una sessione (edizione) di un corso: data, luogo, docente."""

    STATO_CHOICES = [
        ("PIANIFICATA",  "Pianificata"),
        ("IN_CORSO",     "In corso"),
        ("COMPLETATA",   "Completata"),
        ("ANNULLATA",    "Annullata"),
    ]
    MODALITA_CHOICES = [
        ("IN_SEDE",   "In sede"),
        ("REMOTO",    "Remoto / Online"),
        ("ESTERNO",   "Esterno (provider)"),
        ("MISTO",     "Misto"),
    ]

    corso               = models.ForeignKey(TrainingCourse, on_delete=models.PROTECT, related_name="sessioni")
    codice_sessione     = models.CharField(max_length=40, unique=True)
    stato               = models.CharField(max_length=15, choices=STATO_CHOICES, default="PIANIFICATA")
    modalita            = models.CharField(max_length=10, choices=MODALITA_CHOICES, default="IN_SEDE")
    data_inizio         = models.DateField()
    data_fine           = models.DateField()
    sede                = models.CharField(max_length=200, blank=True, help_text="Aula, indirizzo, link remoto")
    docente_nome        = models.CharField(max_length=200, blank=True)
    docente_interno     = models.BooleanField(default=True)
    docente_legacy_id   = models.IntegerField(null=True, blank=True, db_index=True,
                            help_text="legacy_anagrafica_id se docente è dipendente interno")
    note                = models.TextField(blank=True)
    created_at          = models.DateTimeField(auto_now_add=True)
    updated_at          = models.DateTimeField(auto_now=True)
    created_by          = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-data_inizio"]
        verbose_name = "Sessione formativa"
        verbose_name_plural = "Sessioni formative"
        indexes = [
            models.Index(fields=["corso", "stato"]),
            models.Index(fields=["data_inizio", "data_fine"]),
        ]

    def __str__(self):
        return f"[{self.codice_sessione}] {self.corso.titolo} — {self.data_inizio}"


# ─────────────────────────────────────────────────────────────
# 7. LEZIONE
# ─────────────────────────────────────────────────────────────

class TrainingLesson(models.Model):
    """Singola lezione di una sessione."""

    sessione            = models.ForeignKey(TrainingSession, on_delete=models.CASCADE, related_name="lezioni")
    numero              = models.PositiveSmallIntegerField(default=1)
    data                = models.DateField()
    ora_inizio          = models.TimeField()
    ora_fine            = models.TimeField()
    argomento           = models.CharField(max_length=500)
    docente_nome        = models.CharField(max_length=200, blank=True,
                            help_text="Se diverso dal docente della sessione")
    docente_legacy_id   = models.IntegerField(null=True, blank=True, db_index=True)
    note                = models.TextField(blank=True)
    created_at          = models.DateTimeField(auto_now_add=True)
    updated_by          = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["data", "ora_inizio"]
        unique_together = [("sessione", "numero")]
        verbose_name = "Lezione"
        verbose_name_plural = "Lezioni"

    @property
    def durata_ore(self):
        from datetime import datetime, date
        dt_inizio = datetime.combine(date.today(), self.ora_inizio)
        dt_fine   = datetime.combine(date.today(), self.ora_fine)
        diff = dt_fine - dt_inizio
        return round(diff.total_seconds() / 3600, 2)

    def __str__(self):
        return f"Lezione {self.numero} — {self.sessione.codice_sessione} — {self.data}"


# ─────────────────────────────────────────────────────────────
# 8. ISCRIZIONE (Enrollment)
# ─────────────────────────────────────────────────────────────

class TrainingEnrollment(models.Model):
    """Iscrizione di un dipendente a una sessione formativa."""

    STATO_CHOICES = [
        ("ISCRITTO",       "Iscritto"),
        ("IN_CORSO",       "In corso"),
        ("COMPLETATO",     "Completato"),
        ("NON_IDONEO",     "Non idoneo"),
        ("ASSENTE",        "Assente"),
        ("RITIRATO",       "Ritirato"),
    ]

    sessione                = models.ForeignKey(TrainingSession, on_delete=models.CASCADE, related_name="iscrizioni")
    legacy_anagrafica_id    = models.IntegerField(db_index=True)
    stato                   = models.CharField(max_length=15, choices=STATO_CHOICES, default="ISCRITTO")
    ore_frequentate         = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    percentuale_presenza    = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    idoneo                  = models.BooleanField(null=True, blank=True)
    esito_esame             = models.CharField(max_length=100, blank=True)
    data_completamento      = models.DateField(null=True, blank=True)
    note                    = models.TextField(blank=True)
    iscritto_da             = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at              = models.DateTimeField(auto_now_add=True)
    updated_at              = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("sessione", "legacy_anagrafica_id")]
        verbose_name = "Iscrizione"
        verbose_name_plural = "Iscrizioni"
        indexes = [
            models.Index(fields=["legacy_anagrafica_id", "stato"]),
            models.Index(fields=["legacy_anagrafica_id", "data_completamento"]),
        ]

    def __str__(self):
        return f"[{self.legacy_anagrafica_id}] → {self.sessione.codice_sessione} ({self.stato})"


# ─────────────────────────────────────────────────────────────
# 9. PRESENZE LEZIONE
# ─────────────────────────────────────────────────────────────

class TrainingLessonAttendance(models.Model):
    """Presenza di un dipendente a una singola lezione."""

    STATO_PRESENZA_CHOICES = [
        ("PRESENTE",        "Presente"),
        ("ASSENTE_GIUST",   "Assente giustificato"),
        ("ASSENTE_INGIUST", "Assente ingiustificato"),
        ("PARZIALE",        "Presenza parziale"),
    ]

    lezione                 = models.ForeignKey(TrainingLesson, on_delete=models.CASCADE, related_name="presenze")
    legacy_anagrafica_id    = models.IntegerField(db_index=True)
    stato_presenza          = models.CharField(max_length=15, choices=STATO_PRESENZA_CHOICES, default="PRESENTE")
    ore_effettive           = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True)
    firma_ingresso          = models.BooleanField(default=False)
    firma_uscita            = models.BooleanField(default=False)
    note                    = models.TextField(blank=True)
    registrato_da           = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at              = models.DateTimeField(auto_now_add=True)
    updated_at              = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("lezione", "legacy_anagrafica_id")]
        verbose_name = "Presenza lezione"
        verbose_name_plural = "Presenze lezioni"
        indexes = [
            models.Index(fields=["legacy_anagrafica_id", "lezione"]),
        ]

    def __str__(self):
        return f"[{self.legacy_anagrafica_id}] — {self.lezione} — {self.stato_presenza}"


# ─────────────────────────────────────────────────────────────
# 10. RECORD COMPLETAMENTO (storico per dipendente x corso)
# ─────────────────────────────────────────────────────────────

class TrainingEmployeeRecord(models.Model):
    """Record storico di completamento corso per dipendente.
    Generato/aggiornato al completamento di una sessione.
    Usato per calcolo scadenze, matrice obbligatori, storico.
    """

    corso                   = models.ForeignKey(TrainingCourse, on_delete=models.PROTECT, related_name="record_completamenti")
    sessione                = models.ForeignKey(TrainingSession, null=True, on_delete=models.SET_NULL, related_name="record_completamenti")
    enrollment              = models.OneToOneField(TrainingEnrollment, null=True, on_delete=models.SET_NULL, related_name="record_completamento")
    legacy_anagrafica_id    = models.IntegerField(db_index=True)
    data_completamento      = models.DateField()
    ore_frequentate         = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    percentuale_presenza    = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    idoneo                  = models.BooleanField(default=True)
    # Calcolata: data_completamento + corso.validita_mesi
    data_scadenza           = models.DateField(null=True, blank=True,
                                help_text="Null se corso una tantum (validita_mesi=0)")
    validato_da             = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    validato_il             = models.DateField(null=True, blank=True)
    note                    = models.TextField(blank=True)
    created_at              = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-data_completamento"]
        verbose_name = "Record completamento"
        verbose_name_plural = "Record completamenti"
        indexes = [
            models.Index(fields=["legacy_anagrafica_id", "corso"]),
            models.Index(fields=["legacy_anagrafica_id", "data_scadenza"]),
            models.Index(fields=["data_scadenza"]),
        ]

    def __str__(self):
        return f"[{self.legacy_anagrafica_id}] {self.corso.codice} — {self.data_completamento}"


# ─────────────────────────────────────────────────────────────
# 11. ATTESTATO / CERTIFICATO
# ─────────────────────────────────────────────────────────────

class TrainingCertificate(models.Model):
    """Attestato di completamento, collegato a un record completamento."""

    record              = models.OneToOneField(TrainingEmployeeRecord, on_delete=models.CASCADE, related_name="attestato")
    legacy_anagrafica_id = models.IntegerField(db_index=True)
    numero_attestato    = models.CharField(max_length=100, blank=True)
    data_rilascio       = models.DateField()
    rilasciato_da       = models.CharField(max_length=200, blank=True)
    # File salvato con PrivateAnagraficaStorage
    file_attestato      = models.ForeignKey(
        "anagrafica.DocumentoDipendente",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="certificati_formazione"
    )
    note                = models.TextField(blank=True)
    created_at          = models.DateTimeField(auto_now_add=True)
    created_by          = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        verbose_name = "Attestato formazione"
        verbose_name_plural = "Attestati formazione"
        indexes = [
            models.Index(fields=["legacy_anagrafica_id"]),
        ]


# ─────────────────────────────────────────────────────────────
# 12. SCADENZARIO FORMAZIONE (vista/cache calcolata)
# ─────────────────────────────────────────────────────────────

class TrainingDeadline(models.Model):
    """Cache calcolata delle scadenze formazione per dipendente x corso.
    Rigenerata dal management command o post-save di TrainingEmployeeRecord.
    NON modificare manualmente — è un dato derivato.
    """

    STATO_SCADENZA_CHOICES = [
        ("VALIDO",         "Valido"),
        ("IN_SCADENZA_30", "In scadenza ≤30gg"),
        ("IN_SCADENZA_90", "In scadenza ≤90gg"),
        ("SCADUTO",        "Scaduto"),
        ("MAI_FREQUENTATO","Mai frequentato"),
        ("UNA_TANTUM",     "Completato (una tantum)"),
    ]

    corso                   = models.ForeignKey(TrainingCourse, on_delete=models.CASCADE, related_name="scadenze")
    legacy_anagrafica_id    = models.IntegerField(db_index=True)
    ultimo_completamento    = models.ForeignKey(TrainingEmployeeRecord, null=True, on_delete=models.SET_NULL, related_name="+")
    data_ultimo_completamento = models.DateField(null=True, blank=True)
    data_scadenza           = models.DateField(null=True, blank=True)
    stato_scadenza          = models.CharField(max_length=20, choices=STATO_SCADENZA_CHOICES, default="MAI_FREQUENTATO")
    giorni_alla_scadenza    = models.IntegerField(null=True, blank=True)
    ricalcolato_il          = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("corso", "legacy_anagrafica_id")]
        verbose_name = "Scadenza formazione"
        verbose_name_plural = "Scadenze formazione"
        indexes = [
            models.Index(fields=["legacy_anagrafica_id", "stato_scadenza"]),
            models.Index(fields=["data_scadenza"]),
            models.Index(fields=["stato_scadenza"]),
        ]


# ─────────────────────────────────────────────────────────────
# 13. LOG EXPORT
# ─────────────────────────────────────────────────────────────

class TrainingExportLog(models.Model):
    """Audit trail degli export Excel/PDF generati."""

    TIPO_EXPORT_CHOICES = [
        ("PIANI",           "Elenco piani formativi"),
        ("CORSI",           "Elenco corsi"),
        ("ISCRITTI",        "Iscritti sessione"),
        ("PRESENZE",        "Presenze lezione"),
        ("STORICO_DIP",     "Storico dipendente"),
        ("SCADENZARIO",     "Scadenzario formazione"),
        ("MATRICE",         "Matrice dipendente × corso"),
        ("KPI",             "Report KPI direzionale"),
        ("REPORT_FIRMA",    "Report firma lezione PDF"),
    ]

    tipo                = models.CharField(max_length=20, choices=TIPO_EXPORT_CHOICES)
    filtri_json         = models.JSONField(default=dict, blank=True)
    righe_esportate     = models.PositiveIntegerField(default=0)
    generato_da         = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    generato_il         = models.DateTimeField(auto_now_add=True)
    ip_address          = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-generato_il"]
        verbose_name = "Log export formazione"
        verbose_name_plural = "Log export formazione"


# ─────────────────────────────────────────────────────────────
# 14. PERMESSO ACCESSO (Singleton)
# ─────────────────────────────────────────────────────────────

class AnagraficaFormazionePermission(models.Model):
    """Singleton — chi può accedere/gestire la sezione formazione.
    Pattern identico a AnagraficaVisiteMedichePermission.
    """

    ACCESSO_CHOICES = [
        ("TUTTI",   "Tutti i dipendenti autenticati"),
        ("ADMIN",   "Solo amministratori"),
        ("RUOLI",   "Solo ruoli specifici"),
    ]

    accesso_visualizzazione = models.CharField(max_length=10, choices=ACCESSO_CHOICES, default="ADMIN")
    accesso_modifica        = models.CharField(max_length=10, choices=ACCESSO_CHOICES, default="ADMIN")
    accesso_export          = models.CharField(max_length=10, choices=ACCESSO_CHOICES, default="ADMIN")
    accesso_validazione     = models.CharField(max_length=10, choices=ACCESSO_CHOICES, default="ADMIN")
    accesso_report_firma    = models.CharField(max_length=10, choices=ACCESSO_CHOICES, default="ADMIN")
    # Se accesso = RUOLI, lista legacy ruolo_ids (JSON)
    ruoli_autorizzati_json  = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name = "Permesso accesso formazione"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_singleton(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj
```

---

## D) RELAZIONI CON ANAGRAFICA HR

### D.1 — Chiave di collegamento confermata

Tutti i modelli formazione usano `legacy_anagrafica_id = IntegerField(db_index=True)` coerente con:
- `DipendenteQualifica.legacy_anagrafica_id`
- `VisitaMedica.legacy_anagrafica_id`
- `DocumentoDipendente.legacy_anagrafica_id`
- `DipendenteCambiamentoOrganizzativo.legacy_anagrafica_id`

**Non usare FK a `User`** per il dipendente — mantenere il pattern del portale.

### D.2 — Join nelle view

Le view formazione recuperano i dati dipendente con:
```python
# Pattern da replicare (da views.py esistenti)
from anagrafica.models import DipendenteAnagraficaAziendale, DipendenteAnagraficaCivile

dip_az = DipendenteAnagraficaAziendale.objects.filter(legacy_anagrafica_id=legacy_id).first()
dip_civ = DipendenteAnagraficaCivile.objects.filter(legacy_anagrafica_id=legacy_id).first()
```

### D.3 — Relazioni M2M future (da valutare)

- `TrainingPlan.mansioni_obbligatorie` → FK a `Mansione` (per obbligatorietà per mansione)
- `TrainingPlan.ruoli_obbligatori` → FK a `RuoloOperativo` (per obbligatorietà per ruolo)
- Queste relazioni sono commentate nei modelli proposti e da attivare in PATCH-03

### D.4 — Attestati come DocumentoDipendente

Gli attestati vanno salvati come `DocumentoDipendente` con:
```python
tipo = "CERTIFICATO_FORMAZIONE"  # nuovo tipo da aggiungere alle choices
```
Il campo `TrainingCertificate.file_attestato` punta a `DocumentoDipendente` per sfruttare storage privato e ACL esistenti.

> **DECISIONE DA VALIDARE:** aggiungere `"CERTIFICATO_FORMAZIONE"` alle choices di `DocumentoDipendente.tipo`.
> Questa è l'unica modifica al codice esistente necessaria per PATCH-01.

### D.5 — Docente interno

`TrainingSession.docente_legacy_id` + `TrainingLesson.docente_legacy_id` permettono di collegare il docente a un dipendente interno senza FK vincolante. Se il docente è esterno, il campo è null e si usa `docente_nome`.

---

## E) REGOLE DI SCADENZA

### E.1 — Logica di calcolo

```
data_scadenza = data_completamento + relativedelta(months=corso.validita_mesi)

se corso.validita_mesi == 0:
    → corso una tantum, nessuna scadenza, stato = "UNA_TANTUM"
    → il record rimane valido a vita

se data_scadenza > oggi + 90gg:
    → stato = "VALIDO"
se data_scadenza tra oggi + 30gg e oggi + 90gg:
    → stato = "IN_SCADENZA_90"
se data_scadenza tra oggi e oggi + 30gg:
    → stato = "IN_SCADENZA_30"
se data_scadenza < oggi:
    → stato = "SCADUTO"
se non esiste TrainingEmployeeRecord:
    → stato = "MAI_FREQUENTATO"
```

### E.2 — Rinnovo corso

Al termine di una nuova sessione completata per un corso già frequentato:
1. Viene creato un nuovo `TrainingEmployeeRecord` con la nuova data.
2. La `data_scadenza` viene ricalcolata.
3. Il vecchio record rimane nello storico (non viene cancellato).
4. `TrainingDeadline` viene aggiornata (da signal o management command).

### E.3 — Corso obbligatorio per mansione/reparto

1. `TrainingPlan.mansioni_obbligatorie` (M2M a `Mansione`) → tutti i corsi del piano diventano obbligatori per quella mansione.
2. Il calcolo "corsi obbligatori mancanti" compara:
   - Corsi obbligatori per la mansione del dipendente
   - Corsi completati e validi per quel dipendente (da `TrainingEmployeeRecord` / `TrainingDeadline`)

### E.4 — Gestione scadenziario (management command)

```python
# management/commands/refresh_training_deadlines.py
# Da eseguire: python manage.py refresh_training_deadlines [--legacy-id <id>]
# Ricalcola TrainingDeadline per tutti (o per un dipendente specifico)
```

### E.5 — Notifiche scadenza (future)

Pattern già esistente: `send_visite_expiry_reminders.py` in `anagrafica/management/commands/`.
Il management command `send_training_expiry_reminders.py` seguirà lo stesso pattern.

---

## F) REPORTISTICA ED EXCEL

### F.1 — Export con `openpyxl` (pattern già usato nel portale)

Tutti gli export usano `openpyxl` con `HttpResponse` content_type `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`.

### F.2 — Export: Elenco piani formativi

**Colonne:**
`Codice Piano` | `Nome` | `Categoria` | `N° Corsi` | `Ore Totali Stimate` | `Costo Stimato (€)` | `Provider Esterno` | `Stato`

### F.3 — Export: Elenco corsi

**Colonne:**
`Codice Corso` | `Titolo` | `Piano Formativo` | `Durata Ore` | `Validità (mesi)` | `Obbligatorio` | `Versione` | `Stato`

### F.4 — Export: Iscritti a sessione

**Colonne:**
`Matricola` | `Cognome` | `Nome` | `Mansione` | `Area` | `Stato Iscrizione` | `Ore Frequentate` | `% Presenza` | `Idoneo` | `Data Completamento` | `Attestato (S/N)` | `Note`

### F.5 — Export: Presenze lezione

**Colonne:**
`Data Lezione` | `Orario` | `Argomento` | `Matricola` | `Cognome` | `Nome` | `Mansione` | `Stato Presenza` | `Ore Effettive` | `Firma Ingresso` | `Firma Uscita` | `Note`

### F.6 — Export: Storico formazione dipendente

**Colonne:**
`Matricola` | `Cognome` | `Nome` | `Codice Corso` | `Titolo Corso` | `Piano Formativo` | `Data Completamento` | `Ore Frequentate` | `% Presenza` | `Idoneo` | `Data Scadenza` | `Stato Scadenza` | `N° Attestato`

### F.7 — Export: Scadenzario formazione

**Colonne:**
`Matricola` | `Cognome` | `Nome` | `Mansione` | `Area` | `Codice Corso` | `Titolo Corso` | `Piano` | `Obbligatorio` | `Ultimo Completamento` | `Data Scadenza` | `Giorni alla Scadenza` | `Stato Scadenza`

### F.8 — Export: Matrice Dipendente × Corso Obbligatorio

**Struttura:** Dipendenti per riga, corsi obbligatori per colonna.

**Celle:** `OK` (verde — completato valido) | `SCAD` (rosso — scaduto) | `MISS` (arancio — mai frequentato) | `N/A` (grigio — non obbligatorio per quella mansione)

**Colonne fissi sinistra:**
`Matricola` | `Cognome` | `Nome` | `Mansione` | `Area`

**Colonne dinamiche:** una per corso obbligatorio (titolo breve + codice)

### F.9 — Export: Report KPI Direzionale

**Foglio 1 — KPI Riepilogo:**
`KPI` | `Valore` | `Periodo`
Esempi: Ore totali erogate | N° dipendenti formati | % completamento corsi obbligatori | N° scaduti | N° in scadenza

**Foglio 2 — Distribuzione per area:**
`Area` | `Dipendenti Totali` | `Formati` | `% Completamento` | `Ore Medie`

**Foglio 3 — Distribuzione per piano formativo:**
`Piano` | `Corsi Totali` | `Sessioni Erogate` | `Ore Erogate` | `N° Iscritti` | `Completati` | `% Completamento`

---

## G) REPORT LEZIONE / RACCOLTA FIRME

### G.1 — Layout dati (struttura logica)

**Intestazione:**
```
NOVICROM HUB — Registro Presenze Lezione
[Logo aziendale o intestazione formale]
```

**Blocco corso/sessione/lezione:**
```
Piano formativo:   [nome piano]
Codice corso:      [codice]
Titolo corso:      [titolo]
Sessione:          [codice_sessione]
Lezione n°:        [numero]
Data:              [data]
Orario:            [ora_inizio] — [ora_fine]
Durata:            [durata_ore] ore
Sede/Luogo:        [sede sessione]
Docente:           [docente_nome]
```

**Tabella partecipanti:**
| N° | Matricola | Cognome e Nome | Mansione | Firma Ingresso | Firma Uscita | Note |
|----|-----------|----------------|----------|---------------|-------------|------|
| 1  | ...       | ...            | ...      | _________     | _________   |      |

**Spazio note generali:**
```
Note lezione: _______________________________
```

**Piè di pagina:**
```
Documento generato da NOVICROM HUB — [data/ora generazione]
Versione: [versione app]
Pagina X di Y
```

### G.2 — Dove implementare

**File per PDF:**
- `anagrafica/services/formazione_pdf.py` — servizio generazione PDF
- Libreria: **`reportlab`** (già usata altrove nel portale) o **`weasyprint`** + template HTML

**File per Excel:**
- `anagrafica/services/formazione_excel.py` — servizio export Excel
- Libreria: `openpyxl` (già usata nel portale)

**View dedicata:**
- `anagrafica/views.py` → `def formazione_registro_firma_pdf(request, lezione_id):`
- `anagrafica/views.py` → `def formazione_registro_firma_excel(request, lezione_id):`

**URL:**
- `anagrafica/formazione/lezioni/<lid>/registro-firma/pdf/`
- `anagrafica/formazione/lezioni/<lid>/registro-firma/excel/`

---

## H) UI/UX BOZZA

### H.1 — Palette e design system (coerente con Anagrafica HR)

| Token | Valore |
|-------|--------|
| Blu istituzionale | `#12395f` |
| Blu chiaro | `#1f5c91` |
| Sfondo card | `#fff` |
| Bordo card | `#e2e8f0` |
| Sfondo pagina | `#f8fafc` |
| Testo principale | `#1e293b` |
| Testo secondario | `#64748b` |
| Bordo input | `#cbd5e1` |

### H.2 — Classi CSS (estensione del sistema `dp-*`)

Le classi per la sezione Formazione seguono il prefisso `fm-*` per non confliggere con le esistenti.

```
fm-kpi-grid        — griglia card KPI (3-4 colonne)
fm-kpi-card        — singola KPI card (border-radius: .85rem)
fm-kpi-value       — numero grande
fm-kpi-label       — etichetta piccola
fm-table-compact   — tabella densa (font-size: 12px, padding: 6px 10px)
fm-pill            — pill di stato (base)
fm-pill-valid      — verde: completato/valido
fm-pill-expiring   — arancio: in scadenza
fm-pill-expired    — rosso: scaduto
fm-pill-missing    — grigio: mai frequentato
fm-pill-enrolled   — blu: iscritto
fm-pill-ongoing    — azzurro: in corso
fm-row-detail      — panel espandibile sotto la singola riga (non sotto tutta la tabella)
```

### H.3 — Struttura pagina Dashboard Formazione

```
[KPI Grid: 4 card]
[Dipendenti attivi con formazione] [Scadenze ≤30gg ⚠] [Scaduti 🔴] [Obbligatori mancanti 🟠]

[Tab bar: Scadenzario urgente | Per piano | Per mansione | Statistiche]

[Tabella urgente: Dipendente | Corso | Scadenza | Gg mancanti | Stato | Azione]
  → riga espandibile → mostra ultime sessioni frequentate

[Barra azioni: ▼ Export Excel  +Nuova sessione  ⚙ Impostazioni]
```

### H.4 — Pattern espandibile per riga (panel inline)

Stesso pattern usato in `dipendente_detail.html` per le sezioni collassabili:
```html
<tr class="fm-row" data-row-id="42">
  <td>...</td>
  <td><button onclick="toggleFmDetail(42)">▼</button></td>
</tr>
<tr class="fm-row-detail" id="fm-detail-42" hidden>
  <td colspan="N">
    <!-- Dettaglio inline della riga -->
  </td>
</tr>
```

**Non usare drawer/modale** per i dettagli riga — usare panel inline per coerenza con la UI esistente del portale.

### H.5 — Filtri tabella

Pattern coerente con `dipendenti_list.html`:
```html
<form method="get" class="fm-filters">
  <input type="text" name="q" placeholder="Cerca dipendente, corso...">
  <select name="piano">...</select>
  <select name="stato_scadenza">...</select>
  <select name="area">...</select>
  <select name="mansione">...</select>
  <button type="submit">Filtra</button>
  <a href="?">Reset</a>
</form>
```

---

## I) MATRICE PERMESSI

> **Nota:** Questa matrice è una proposta funzionale. I permessi saranno implementati tramite
> `AnagraficaFormazionePermission` (singleton) e ACL legacy/v2, **senza modificare** il sistema
> di permessi esistente.

| Funzione | HR Admin | HR Viewer | Resp. Reparto | RSPP/Sicurezza | Direzione | Dipendente |
|----------|----------|-----------|---------------|----------------|-----------|------------|
| Dashboard formazione | ✅ | ✅ | ✅ (solo suo reparto) | ✅ | ✅ | ❌ |
| Catalogo piani/corsi (lettura) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Gestione piani/corsi (CRUD) | ✅ | ❌ | ❌ | ✅ (sicurezza) | ❌ | ❌ |
| Gestione sessioni | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ |
| Gestione lezioni | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ |
| Iscrizione dipendenti | ✅ | ❌ | ✅ (suo reparto) | ✅ | ❌ | ❌ |
| Registro presenze | ✅ | ❌ | ✅ (suo reparto) | ✅ | ❌ | ❌ |
| Validazione completamento | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ |
| Upload/gestione attestati | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ |
| Storico formazione (tutti) | ✅ | ✅ | ✅ (suo reparto) | ✅ | ✅ | ❌ |
| Storico formazione (proprio) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Scadenzario (tutti) | ✅ | ✅ | ✅ (suo reparto) | ✅ | ✅ | ❌ |
| Export Excel (tutti) | ✅ | ✅ | ✅ (suo reparto) | ✅ | ✅ | ❌ |
| Export Excel (proprio) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Genera report firma PDF | ✅ | ❌ | ✅ (suo reparto) | ✅ | ❌ | ❌ |
| Impostazioni modulo | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Report KPI direzionale | ✅ | ✅ | ❌ | ✅ | ✅ | ❌ |

---

## J) PIANO IMPLEMENTATIVO INCREMENTALE

### PATCH FORMAZIONE-00 — Discovery e documento architettura
- **Obiettivo:** Documento bozza completo (questo file). Analisi repository.
- **File coinvolti:** `docs/anagrafica/formazione/BOZZA_MODULO_FORMAZIONE.md`
- **Rischio:** Nessuno — solo documentazione
- **Test minimi:** Nessuno
- **Quality gates:** Nessuno
- **Parti provvisorie:** Tutto — documento da validare con HR/RSPP/Direzione
- **Decisioni da validare prima di PATCH-01:**
  1. Aggiungere `"CERTIFICATO_FORMAZIONE"` alle choices di `DocumentoDipendente.tipo`?
  2. Modelli in `models.py` principale o in `models_formazione.py` separato?
  3. La sezione è un nuovo URL `/anagrafica/formazione/` o integrata come tab nella dashboard?
  4. Obbligatorietà per mansione: M2M su `TrainingPlan` o tabella separata `TrainingPlanObligation`?
  5. Docente esterno: semplice CharField o entità `TrainingInstructor` dedicata?

---

### PATCH FORMAZIONE-01 — Modelli base e Django Admin read-only
- **Obiettivo:** Aggiungere modelli al codice, creare migrazione, registrare in admin Django (read-only).
- **File coinvolti:**
  - `django_app/anagrafica/models.py` (o nuovo `models_formazione.py`)
  - `django_app/anagrafica/admin.py`
  - `django_app/anagrafica/migrations/00XX_add_training_models.py`
- **Rischio:** BASSO — nuove tabelle, nessuna modifica tabelle esistenti. Solo aggiunta choices a `DocumentoDipendente.tipo`.
- **Test minimi:**
  - `python manage.py check`
  - `python manage.py makemigrations --check`
  - `python manage.py migrate`
  - Verifica admin Django accessibile
- **Quality gates:** `python manage.py test anagrafica`
- **Parti configurabili:** Scelta schema modelli (models.py vs models_formazione.py)
- **Parti provvisorie:** Admin è read-only/bozza, nessuna UI utente

---

### PATCH FORMAZIONE-02 — Dashboard Formazione
- **Obiettivo:** Pagina dashboard `/anagrafica/formazione/` con KPI e scadenzario urgente.
- **File coinvolti:**
  - `django_app/anagrafica/views.py` — view `formazione_dashboard`
  - `django_app/anagrafica/urls.py` — URL `formazione/`
  - `django_app/anagrafica/templates/anagrafica/pages/formazione_dashboard.html`
  - `django_app/anagrafica/acl_bootstrap.py` — registrazione endpoint
  - `django_app/anagrafica/templates/anagrafica/components/subnav.html` — eventuale aggiunta voce menu
- **Rischio:** BASSO — nuova pagina, nessuna modifica a view/template esistenti
- **Test minimi:** Accesso pagina, KPI mostrano valori (anche 0 se DB vuoto)
- **Quality gates:** `python manage.py check`, review visiva UI

---

### PATCH FORMAZIONE-03 — Piani Formativi e Corsi (CRUD)
- **Obiettivo:** CRUD completo per piani e corsi. Relazioni M2M mansioni/ruoli.
- **File coinvolti:**
  - `django_app/anagrafica/views.py` — 6-8 nuove view
  - `django_app/anagrafica/urls.py` — 8-10 nuovi URL
  - `django_app/anagrafica/forms.py` — TrainingPlanForm, TrainingCourseForm
  - `django_app/anagrafica/templates/anagrafica/pages/formazione_piani.html`
  - `django_app/anagrafica/templates/anagrafica/pages/formazione_piano_detail.html`
  - `django_app/anagrafica/templates/anagrafica/pages/formazione_corsi.html`
  - `django_app/anagrafica/templates/anagrafica/pages/formazione_corso_detail.html`
- **Rischio:** BASSO-MEDIO — aggiunta form e view, nessun impatto su dati esistenti
- **Test minimi:** CRUD piani e corsi, filtri, relazioni M2M

---

### PATCH FORMAZIONE-04 — Sessioni e Lezioni
- **Obiettivo:** Gestione sessioni e lezioni per ogni corso.
- **File coinvolti:**
  - `django_app/anagrafica/views.py` — view sessioni e lezioni
  - `django_app/anagrafica/urls.py` — URL sessioni/lezioni
  - `django_app/anagrafica/forms.py` — TrainingSessionForm, TrainingLessonForm
  - Template: `formazione_sessione_detail.html`, `formazione_lezione_detail.html`
- **Rischio:** BASSO — nuove entità senza impatto su dati HR esistenti
- **Test minimi:** Creazione sessione, aggiunta lezioni, validazione date

---

### PATCH FORMAZIONE-05 — Iscritti e Presenze
- **Obiettivo:** Iscrizione dipendenti a sessioni, registro presenze per lezione.
- **File coinvolti:**
  - `django_app/anagrafica/views.py` — view enrollment e presenze
  - `django_app/anagrafica/urls.py`
  - Template: `formazione_iscritti.html`, `formazione_presenze.html`
  - `django_app/anagrafica/services/formazione_excel.py` — export presenze
- **Rischio:** MEDIO — logica di calcolo percentuali presenza, validazioni
- **Test minimi:** Iscrizione, registrazione presenze, calcolo % presenza
- **Decisioni da validare:** Come gestire iscrizione massiva (da Excel/CSV)?

---

### PATCH FORMAZIONE-06 — Storico Dipendente e Scadenzario
- **Obiettivo:** Tab "Formazione" in scheda dipendente (sostituisce placeholder). Scadenzario.
- **File coinvolti:**
  - `django_app/anagrafica/templates/anagrafica/pages/dipendente_detail.html` — sostituisce `dp-soon-card`
  - `django_app/anagrafica/views.py` — aggiunta dati formazione al context `dipendente_detail`
  - `django_app/anagrafica/templates/anagrafica/pages/formazione_scadenzario.html`
  - `django_app/anagrafica/management/commands/refresh_training_deadlines.py`
- **Rischio:** MEDIO — modifica a `dipendente_detail.html` (file critico); limitare al solo tab formazione
- **Test minimi:** Tab mostra storico corretto, scadenzario filtra correttamente

---

### PATCH FORMAZIONE-07 — Export Excel completo
- **Obiettivo:** Tutti gli export Excel (piani, corsi, iscritti, presenze, storico, scadenzario, matrice, KPI).
- **File coinvolti:**
  - `django_app/anagrafica/services/formazione_excel.py` — tutti gli export
  - `django_app/anagrafica/views.py` — view export
  - `django_app/anagrafica/urls.py` — URL export
- **Rischio:** BASSO — solo generazione file, nessun effetto su DB
- **Test minimi:** Ogni export genera file valido con colonne corrette

---

### PATCH FORMAZIONE-08 — Report Firma PDF
- **Obiettivo:** Generazione PDF registro presenze/firme per lezione.
- **File coinvolti:**
  - `django_app/anagrafica/services/formazione_pdf.py`
  - `django_app/anagrafica/views.py` — view PDF
  - `django_app/anagrafica/urls.py` — URL PDF
  - `requirements.txt` — eventuale aggiunta `reportlab` o `weasyprint`
- **Rischio:** MEDIO — dipendenza esterna, test su Windows con IIS
- **Test minimi:** PDF generato con dati corretti, download funzionante
- **Decisioni da validare:** `reportlab` vs `weasyprint` (verificare disponibilità in ambiente prod)

---

### PATCH FORMAZIONE-09 — Hardening, test, permessi, audit
- **Obiettivo:** Permessi granulari, audit trail, test completi, review sicurezza.
- **File coinvolti:**
  - `django_app/anagrafica/acl_bootstrap.py` — tutti gli endpoint formazione
  - `django_app/anagrafica/models.py` — `AnagraficaFormazionePermission`
  - `django_app/anagrafica/views.py` — decoratori permesso
  - `django_app/anagrafica/tests.py` — test suite formazione
- **Rischio:** BASSO — solo hardening, nessuna nuova feature
- **Test minimi:** Coverage > 80% per view e modelli formazione
- **Quality gates:**
  - `python manage.py test anagrafica`
  - `python manage.py check`
  - `python manage.py validate_deployment --format json`
  - `python manage.py acl_coverage_report`

---

## K) FILE CREATI IN QUESTA FASE (PATCH-00)

| File | Tipo | Note |
|------|------|------|
| `docs/anagrafica/formazione/BOZZA_MODULO_FORMAZIONE.md` | Documento | Questo file |

**Nessuna migrazione applicata.**
**Nessuna modifica a file di codice esistenti.**

---

## L) QUALITY GATES (da eseguire prima di ogni patch successiva)

```powershell
# Controllo salute Django
python django_app\manage.py check --settings=config.settings.test

# Verifica migrazioni (deve restare pulito finché non si applica PATCH-01)
python django_app\manage.py makemigrations --check --dry-run --settings=config.settings.dev

# Test suite
python django_app\manage.py test --settings=config.settings.test

# Verifica deployment
python django_app\manage.py validate_deployment --format json --settings=config.settings.test

# Dopo PATCH-01: verifica copertura ACL
python django_app\manage.py acl_coverage_report --max-missing 250
```

---

## RISCHI E PUNTI DA DECIDERE

### Rischi principali

| Rischio | Livello | Mitigazione |
|---------|---------|-------------|
| Modifica `dipendente_detail.html` (file critico) | MEDIO | Toccare solo il `data-tab="formazione"` placeholder |
| Performance matrice dipendente × corso (O(n×m)) | MEDIO | Paginazione + cache `TrainingDeadline` |
| Dipendenza `reportlab`/`weasyprint` per PDF in prod Windows/IIS | MEDIO | Verificare prima di PATCH-08 |
| Dati legacy: `legacy_anagrafica_id` non referenziale | BASSO | Pattern già usato ovunque nel portale |
| `openpyxl` già disponibile nel portale | BASSO | Verificare in requirements.txt prima di PATCH-07 |

### Decisioni da validare prima di PATCH-01

1. **Schema modelli:** `models.py` unico o `models_formazione.py` separato?
2. **DocumentoDipendente.tipo:** aggiungere `"CERTIFICATO_FORMAZIONE"` alle choices?
3. **URL base:** `/anagrafica/formazione/` o mantenerlo come sezione tab senza URL dedicato?
4. **Obbligatorietà:** M2M su `TrainingPlan` o tabella `TrainingPlanObligation` separata?
5. **Docente esterno:** semplice `CharField` o modello `TrainingInstructor` dedicato?
6. **Import massivo iscritti:** da UI tabella o da Excel upload?
7. **Notifiche scadenza:** email via SMTP (già presente) o solo portale?
8. **PDF report firma:** `reportlab` o `weasyprint`? Verificare con team infrastruttura.
9. **`TrainingDeadline` ricalcolo:** tramite signal post-save o management command schedulato?
10. **Modulo separato vs estensione anagrafica:** confermare che rimane in `anagrafica/` e non diventa app Django separata `formazione/`.

---

*Documento generato da Claude Code — NOVICROM HUB v1.0.2 — 2026-05-22*
*Stato: BOZZA — da validare con HR Admin, RSPP, Direzione prima dell'implementazione*
