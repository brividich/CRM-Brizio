# Proposta di modellazione — Fattori di Rischio e Categorie Corso

> **Stato**: bozza rev. 1 — 2026-05-23. Da validare prima di scrivere codice.
> **Contesto**: emersa caricando lo storico formativo pregresso. I 682 corsi
> importati hanno `validita_mesi = 0` perché `courses-person.xlsx` non porta la
> frequenza di rinnovo → lo scadenzario formazione mostra tutto come
> `UNA_TANTUM` e non segnala nulla in scadenza.
> **Obiettivo**: far derivare la scadenza dei corsi (e in prospettiva di
> qualifiche, DPI, sorveglianza sanitaria) dai **fattori di rischio**, invece
> di tenere `validita_mesi` come dato piatto su ogni corso.

---

## 1. Problema

Oggi la periodicità di rinnovo formativo è un campo isolato:

- `TrainingCourse.validita_mesi` — intero, mesi. Va impostato a mano corso per corso.
- `TrainingPlan.categoria` — `CharField` con 3 sole scelte (`OBBLIGATORIA` /
  `CONSIGLIATA` / `FACOLTATIVA`): non è una tassonomia, non collega a nulla.
- `TipoQualifica.categoria` — analogo `CharField` (`SICUREZZA` / `PROFESSIONALE` / …).

Non esiste alcun modello di **fattore di rischio**. La normativa sicurezza
(D.Lgs. 81/08) ragiona invece così: una **mansione** espone a certi **fattori
di rischio**; ogni fattore impone formazione, sorveglianza sanitaria e DPI con
una **periodicità** propria. La scadenza non è un attributo del corso: è una
conseguenza del rischio.

## 2. Catena proposta

```
Mansione / Area ──espone a──> FattoreRischio <──coperto da── CategoriaCorso ──> TrainingCourse
                                    │                                              │
                                    │ periodicita_mesi                             │ validita_mesi (override opzionale)
                                    ▼                                              ▼
                              scadenza derivata ───────────────────────────> TrainingDeadline
```

Il `FattoreRischio` diventa l'**hub trasversale** che lega i mondi safety già
presenti nel portale:

- **Formazione** — corsi richiesti dal fattore.
- **Qualifiche/abilitazioni** — `TipoQualifica` (es. "Preposti", "Primo soccorso").
- **DPI** — modulo `dpi/` (DPI imposti dal fattore).
- **Sorveglianza sanitaria** — `TipoVisitaMedica` (visite imposte dal fattore).

## 3. Modelli proposti

### 3.1 `FattoreRischio`

```python
class FattoreRischio(models.Model):
    """Fattore di rischio lavorativo (D.Lgs. 81/08). Hub safety trasversale."""

    CATEGORIA_CHOICES = [
        ("CHIMICO",        "Chimico"),
        ("FISICO",         "Fisico"),
        ("BIOLOGICO",      "Biologico"),
        ("ERGONOMICO",     "Ergonomico / MMC"),
        ("INFORTUNISTICO", "Infortunistico"),
        ("ALTRO",          "Altro"),
    ]

    codice       = models.CharField(max_length=20, unique=True)
    nome         = models.CharField(max_length=200)
    categoria    = models.CharField(max_length=20, choices=CATEGORIA_CHOICES, default="ALTRO")
    descrizione  = models.TextField(blank=True)

    # Periodicità di rinnovo della formazione legata al fattore (0 = una tantum)
    periodicita_formazione_mesi = models.PositiveSmallIntegerField(default=0)
    # Periodicità sorveglianza sanitaria (0 = non prevista)
    periodicita_sorveglianza_mesi = models.PositiveSmallIntegerField(default=0)

    richiede_formazione        = models.BooleanField(default=True)
    richiede_visita_medica     = models.BooleanField(default=False)
    richiede_dpi               = models.BooleanField(default=False)

    is_active  = models.BooleanField(default=True)
    note       = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
```

### 3.2 `CategoriaCorso`

Sostituisce/affianca `TrainingPlan.categoria` come **tabella vera**.

```python
class CategoriaCorso(models.Model):
    """Categoria formativa: raggruppa corsi e li lega a uno o piu fattori di rischio."""

    codice          = models.CharField(max_length=20, unique=True)
    nome            = models.CharField(max_length=200)
    descrizione     = models.TextField(blank=True)
    fattori_rischio = models.ManyToManyField(FattoreRischio, blank=True,
                                             related_name="categorie_corso")
    is_active       = models.BooleanField(default=True)
```

### 3.3 Aggancio su `TrainingCourse`

```python
# nuovo campo, nullable per retrocompat con lo storico già importato
categoria = models.ForeignKey("anagrafica.CategoriaCorso", null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="corsi")
# validita_mesi RESTA: diventa OVERRIDE esplicito. Null/0 = deriva dai fattori.
```

### 3.4 Esposizione mansione/area → fattore

```python
class EsposizioneRischio(models.Model):
    """Una mansione (o area) e esposta a un fattore di rischio."""

    fattore  = models.ForeignKey(FattoreRischio, on_delete=models.CASCADE,
                                 related_name="esposizioni")
    mansione = models.ForeignKey("anagrafica.Mansione", null=True, blank=True,
                                 on_delete=models.CASCADE)
    area     = models.ForeignKey("anagrafica.AreaAziendale", null=True, blank=True,
                                 on_delete=models.CASCADE)
    note     = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
```

Questo si integra con `TrainingRequirementRule`, che già targetta
mansione/area/ruolo: la regola di obbligatorietà può essere **generata** dalle
esposizioni invece di essere inserita a mano.

## 4. Derivazione della scadenza

Service deterministico (estende `training_deadline_service`):

```
validita effettiva di un corso =
    TrainingCourse.validita_mesi            se valorizzato (> 0)  → override esplicito
    altrimenti  min(periodicita_formazione_mesi
                    dei FattoreRischio della CategoriaCorso del corso, escludendo gli 0)
    altrimenti  0  → una tantum
```

Si sceglie il **minimo** (il fattore più restrittivo detta il ritmo). Il
calcolo resta nel service/management command `refresh_training_deadlines`,
coerente con D9 (cache ricalcolabile, mai signal operativi).

## 5. Decisioni aperte (da validare)

| # | Tema | Opzioni | Raccomandazione |
|---|------|---------|-----------------|
| R1 | Dove vivono i modelli | `anagrafica/` vs nuova app `rischi/` | **`anagrafica/`** — coerente con D10 e con `TipoQualifica` già lì; il fattore è trasversale ma piccolo |
| R2 | `TrainingPlan.categoria` (CharField) | tenere / deprecare a favore di `CategoriaCorso` | Tenere per ora; `CategoriaCorso` è sul **corso**, non sul piano — convivono |
| R3 | Da dove arriva l'anagrafica dei fattori di rischio | DVR aziendale / inserimento manuale / import | Da definire con HSE — probabilmente seed manuale dai DVR |
| R4 | Legame fattore → qualifica / DPI / visita | M2M ora o in patch successiva | M2M `FattoreRischio` ↔ `TipoQualifica`/`TipoVisitaMedica` in **patch successiva**, non nella prima |
| R5 | Backfill storico | i 682 corsi importati come si categorizzano? | Lasciare `categoria=null` → restano una tantum finché HSE non assegna la categoria |

## 6. Piano patch suggerito

- **PATCH-RISK-01**: modelli `FattoreRischio`, `CategoriaCorso`, `EsposizioneRischio` + admin + migrazione. FK `TrainingCourse.categoria`. Nessuna UI.
- **PATCH-RISK-02**: UI catalogo fattori di rischio + categorie corso (CRUD, pattern `fm-*`).
- **PATCH-RISK-03**: derivazione scadenza nel `training_deadline_service` + ricalcolo. Generazione `TrainingRequirementRule` dalle esposizioni.
- **PATCH-RISK-04**: M2M fattore ↔ qualifiche / DPI / visite mediche; viste integrate sulla scheda dipendente.

## 7. Cosa NON fare ora

- Non toccare `validita_mesi` dei corsi importati: resta override, default 0.
- Non rimuovere `TrainingPlan.categoria` / `TipoQualifica.categoria` CharField.
- Non implementare il legame DPI/visite prima di PATCH-RISK-04.
