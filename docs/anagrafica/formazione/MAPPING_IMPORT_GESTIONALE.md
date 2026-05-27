# Mapping import gestionale → modulo Formazione HR

> **Stato**: rev. 1 — 2026-05-22 (PATCH-06 completata, prima di PATCH-07).
> **Scopo**: documentare la struttura dei file Excel di estrazione del gestionale
> attualmente in uso e la loro corrispondenza con i modelli del modulo Formazione
> (`anagrafica/models_formazione.py`) e con il catalogo qualifiche/abilitazioni
> esistente in `anagrafica/models.py`.
>
> **Uso operativo**:
> - **PATCH-07 (export Excel)**: gli header degli export round-trip devono
>   coincidere con le colonne qui mappate, così che gli operatori possano
>   confrontare/riconciliare con i file estratti dal gestionale.
> - **PATCH future (import)**: questo doc è il riferimento autoritativo per
>   l'implementazione di `import_*_from_xlsx()` nei servizi formazione.
>
> **Out of scope per PATCH-07**: l'IMPORT vero e proprio. Qui si definisce solo
> la **forma delle colonne**, non la logica di lookup/upsert.

---

## 1. `courses-person.xlsx` (3.772 righe, 21 col)

**Cosa contiene**: storico iscrizioni/esiti per dipendente — un record per ogni
partecipazione di un dipendente a un corso.

**Mapping ai modelli**:

| Colonna Excel                | Modello.campo                                                                 | Note |
|------------------------------|-------------------------------------------------------------------------------|------|
| `ID`                         | (esterno — ID gestionale)                                                     | Non persistito. Tracciato in `last_recalculation_source` se utile. |
| `Data di estrazione`         | (metadata import)                                                             | Solo log import. |
| `Iscritto`                   | → lookup `AnagraficaDipendente` per Cognome Nome → `legacy_anagrafica_id`     | Lookup case-insensitive con normalizzazione spazi. |
| `Genere`                     | `DipendenteAnagraficaCivile.genere`                                           | Già presente in anagrafica. Solo per validazione cross-check. |
| `Codice fiscale`             | `DipendenteAnagraficaCivile.codice_fiscale`                                   | Usato come fallback di lookup se ambiguità su Cognome Nome. |
| `Rapporto di Lavoro`         | (riferimento — non persistito in record formazione)                            | Es: "Dipendente". |
| `Azienda`                    | (riferimento — non persistito in record formazione)                            | Es: "PONTEDERA". |
| `Piano formativo`            | `TrainingEmployeeRecord.plan_name_snapshot` + lookup `TrainingPlan.nome`      | Lookup per nome esatto. Se non esiste → crea piano in stato BOZZA. |
| `Codice corso`               | `TrainingEmployeeRecord.course_code_snapshot` + lookup `TrainingCourse.codice` | Codice = chiave primaria di lookup. |
| `Corso`                      | `TrainingEmployeeRecord.course_title_snapshot` + `TrainingCourse.titolo`      | Snapshot al momento dell'import. |
| `Modalità di erogazione`     | `TrainingSession.modalita`                                                    | "DA REMOTO - LMS" → REMOTO. "AULA" → IN_SEDE. Mapping in `_map_modalita()`. |
| `Luogo del corso`            | `TrainingSession.sede`                                                        | Stringa libera. |
| `Sede`                       | **GAP** — non esiste campo `sede_dipendente_snapshot` in `TrainingEmployeeRecord` | Future: aggiungere campo opzionale. Per ora ignorato in import e vuoto in export. |
| `Durata (ore)`               | `TrainingEmployeeRecord.duration_hours_snapshot`                              | `TrainingCourse.durata_ore_teorica` come fallback. |
| `Frequenza`                  | `TrainingEmployeeRecord.ore_frequentate`                                      | Decimal. |
| `Ore partecipate (%)`        | `TrainingEmployeeRecord.percentuale_presenza`                                 | Decimal 0–100. |
| `Inizio corso`               | `TrainingSession.data_inizio`                                                 | Formato gg/mm/aaaa. |
| `Fine corso`                 | `TrainingSession.data_fine` + `TrainingEmployeeRecord.data_completamento`     | Se "Ha superato il corso? = Si". |
| `Ha partecipato al corso ?`  | → mapping `TrainingEnrollment.stato`                                          | "Si" → ISCRITTO/IN_CORSO/COMPLETATO secondo `Ha superato`. "No" → ASSENTE. |
| `Ha superato il corso ?`     | `TrainingEmployeeRecord.idoneo` (Boolean)                                     | "Si" → True. "No" → False (+ enrollment stato NON_IDONEO). |
| `Livello di apprendimento`   | **GAP** — non esiste campo `learning_level_snapshot`                          | Valori osservati: "Completo". Future: aggiungere CharField opzionale. |

**Strategia chiave per export PATCH-07** (`export_storico_dipendente.xlsx`):
- Riprodurre **le stesse 21 colonne** nell'ordine sopra.
- Colonne GAP (`Sede`, `Livello di apprendimento`) → vuote per ora.
- `Data di estrazione` → `today().strftime('%d/%m/%Y')`.

---

## 2. `Iscritti alle lezioni_AAAA-MM-GG.xlsx` (4.970 righe, 33 col)

**Cosa contiene**: presenze granulari — un record per ogni partecipazione
(o assenza) di un dipendente a una **lezione specifica** di un corso.

**Mapping ai modelli**:

| Colonna Excel                            | Modello.campo                                              | Note |
|------------------------------------------|------------------------------------------------------------|------|
| `ID`                                     | (esterno — riga gestionale)                                | Non persistito. |
| `Data di estrazione`                     | (metadata import)                                          |  |
| `ID lezione`                             | (esterno — ID lezione gestionale)                          | Lookup `TrainingLesson` via `external_id` (GAP — campo non esiste). Per ora lookup composito (sessione+numero+data). |
| `Iscritto`                               | → lookup `legacy_anagrafica_id`                            |  |
| `Genere` / `Codice fiscale` / `Rapporto di Lavoro` / `Sede` / `Azienda` | (riferimenti anagrafica)        | Non persistiti in `TrainingLessonAttendance`. |
| `Nome lezione`                           | `TrainingLesson.argomento`                                 | Snapshot. |
| `Ha partecipato alla lezione?` (2x)      | `TrainingLessonAttendance.stato_presenza`                  | "Si" → PRESENTE. "No" → ASSENTE_INGIUST. (Si appare 2 volte: testuale + boolean.) |
| `Durata lezione (ore)`                   | (derivato da `TrainingLesson.ora_inizio/ora_fine`)         |  |
| `Ore frequentate`                        | `TrainingLessonAttendance.ore_effettive`                   |  |
| `Frequenza` (str "0,00 %")               | (calcolato `ore_eff / durata`)                             | Non persistito direttamente. |
| `Data`                                   | `TrainingLesson.data`                                      |  |
| `Ora di inizio` / `Ora di fine`          | `TrainingLesson.ora_inizio` / `.ora_fine`                  |  |
| `Modalità di erogazione della lezione`   | **GAP** — `TrainingLesson` non ha `modalita` propria       | Fallback su `TrainingSession.modalita`. Future: aggiungere campo opzionale. |
| `Livello di apprendimento`               | (vedi sezione 1 — GAP)                                     |  |
| `Codice corso` / `Corso`                 | `TrainingCourse.codice` / `.titolo` (via `lezione.sessione.corso`) |  |
| `Categoria`                              | **GAP** — non esiste `TrainingLesson.categoria`            | Future: aggiungere CharField opzionale. |
| `Inizio corso` / `Fine corso`            | `TrainingSession.data_inizio` / `.data_fine`               |  |
| `Piano formativo`                        | `TrainingPlan.nome` (via corso → piano)                    |  |
| `Luogo del corso`                        | `TrainingSession.sede`                                     |  |
| `Durata corso (ore)`                     | `TrainingCourse.durata_ore_teorica`                        |  |
| `Ore partecipate (%)`                    | (calcolato corso-level — `TrainingEnrollment.percentuale_presenza`) |  |
| `Frequenza` (corso, str "100 %")         | (calcolato)                                                |  |
| `Ha partecipato al corso ?` / `Ha superato il corso ?` | `TrainingEnrollment.stato` / `TrainingEmployeeRecord.idoneo` |  |
| `Modalità del corso`                     | (potrebbe duplicare modalità lezione — vuoto se non popolato) |  |

**Strategia chiave per export PATCH-07** (`export_presenze_lezione.xlsx`):
- Riprodurre **le stesse 33 colonne** nell'ordine sopra.
- Per export "Presenze lezione" generato da una **singola lezione**, popolare
  solo le colonne con dati disponibili. Le altre → vuote.

---

## 3. `qualifications-person.xlsx` (87 righe, 9 col)

**Cosa contiene**: qualifiche/abilitazioni del dipendente con scadenza.

> **Nota architetturale**: le qualifiche sono **già modellate** in
> `anagrafica/models.py` come `TipoQualifica` (catalogo) e `DipendenteQualifica`
> (assegnazione). Sono entità del modulo `anagrafica` (non del modulo
> Formazione). In futuro avranno:
>
> - **fattori di rischio** associati (modulo da definire)
> - **corsi richiesti** (legame via `TrainingRequirementRule` — già esiste,
>   ma il target attuale è Mansione/Area/RuoloOperativo, non Qualifica)
> - **DPI assegnati** (modulo `dpi/` — legame da definire)
> - **scadenze proprie** (già su `DipendenteQualifica.data_scadenza`)
>
> Pertanto l'import qualifiche **NON** popola tabelle Formazione: popola le
> tabelle qualifiche di `anagrafica`. Lo includiamo qui per riferimento
> centralizzato delle estrazioni gestionali.

**Mapping ai modelli (anagrafica.qualifica*)**:

| Colonna Excel       | Modello.campo                                                  | Note |
|---------------------|----------------------------------------------------------------|------|
| `Nome`              | → lookup `legacy_anagrafica_id` da Cognome Nome                |  |
| `Abilitazione`      | `TipoQualifica.nome` (lookup; create se mancante)              | Es: "PRIMO SOCCORSO Aziende Categoria A", "PREPOSTI". |
| `Valore monetario`  | **GAP** — `DipendenteQualifica` non ha `valore_monetario`      | Future: aggiungere Decimal opzionale. |
| `Data conseguimento`| `DipendenteQualifica.data_conseguimento`                       |  |
| `Data scadenza`     | `DipendenteQualifica.data_scadenza`                            |  |
| `Note`              | `DipendenteQualifica.note`                                     |  |
| `Categoria`         | `TipoQualifica.categoria`                                      | Mapping: SICUREZZA / PROFESSIONALE / GESTIONALE / ALTRO. |
| `Area`              | (lookup `AreaAziendale.nome`)                                  | Già presente in `DipendenteAnagraficaAziendale`. Solo cross-check. |
| `Reparto`           | (campo dipendente, non qualifica)                              | Es: "CQI", "CQF". |

**Strategia export**: NON nel modulo Formazione. Eventuale export qualifiche
appartiene al cruscotto qualifiche esistente (fuori scope PATCH-07).

---

## 4. `SOSTENIBILITA' ESG.xlsx` (31 righe, 6 col)

**Cosa contiene**: mini-catalogo di un singolo piano (ESG).

**Mapping ai modelli**:

| Colonna Excel       | Modello.campo                                  | Note |
|---------------------|------------------------------------------------|------|
| `ID`                | (esterno)                                      |  |
| `Titolo del corso`  | `TrainingCourse.titolo`                        |  |
| `Codice corso`      | `TrainingCourse.codice`                        | Unique. |
| `Stato`             | `TrainingCourse.stato`                         | "CHIUSO" → ARCHIVIATO. "ATTIVO" → ATTIVO. |
| `Inizio corso`      | `TrainingSession.data_inizio` (sessione associata) | Indica edizione storica. |
| `Fine corso`        | `TrainingSession.data_fine`                    |  |

**Osservazione**: questo file è una **vista alternativa** del catalogo corsi
filtrato per piano (ESG). Per l'import sostituibile da `courses-person.xlsx`.

---

## 5. `training-plans.xlsx` (13 righe, 8 col)

**Cosa contiene**: elenco piani formativi con KPI aggregati.

**Mapping ai modelli**:

| Colonna Excel                       | Modello.campo                                  | Note |
|-------------------------------------|------------------------------------------------|------|
| `Nome`                              | `TrainingPlan.nome`                            | Lookup/create. |
| `Stato`                             | `TrainingPlan.stato`                           | "Attivo" → ATTIVO. |
| `Numero di corsi`                   | (count(`TrainingCourse` where `piano=`))       | Calcolato. |
| `Ore totali dei corsi`              | `TrainingPlan.ore_totali_stimate` o sum derivato | Decimal. |
| `Partecipanti ai corsi`             | (count distinct `legacy_anagrafica_id` via record) | Calcolato. |
| `Rapporto ore corsi / partecipanti` | (calcolato)                                    |  |
| `Totale ore dei partecipanti`       | (sum `TrainingEmployeeRecord.ore_frequentate`) | Calcolato. |
| `Costo totale`                      | `TrainingPlan.costo_stimato` o sum derivato    | Decimal. |

**Strategia export PATCH-07** (`export_piani_formativi.xlsx`):
- Riprodurre le stesse 8 colonne, valori calcolati on-the-fly dal portale.

---

## Riepilogo GAP campi (per PATCH future)

Campi da aggiungere ai modelli per piena fedeltà al gestionale (tutti
opzionali, non bloccanti per PATCH-07):

| Modello                   | Campo da aggiungere                  | Tipo                              | Esempio |
|---------------------------|--------------------------------------|-----------------------------------|---------|
| `TrainingEmployeeRecord`  | `learning_level_snapshot`            | `CharField(max_length=50, blank=True)` | "Completo" |
| `TrainingEmployeeRecord`  | `sede_dipendente_snapshot`           | `CharField(max_length=200, blank=True)` | "PONTEDERA" |
| `TrainingLesson`          | `modalita`                           | `CharField(max_length=10, choices=..., blank=True)` | "REMOTO" |
| `TrainingLesson`          | `categoria`                          | `CharField(max_length=100, blank=True)` | "Informazione" |
| `TrainingLesson`          | `external_id`                        | `IntegerField(null=True, blank=True, db_index=True)` | 4468 |
| `DipendenteQualifica`     | `valore_monetario`                   | `DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)` | — |

> **Non aggiungerli ora**. Tracciati per PATCH dedicata
> (probabilmente PATCH-IMPORT o successiva a PATCH-09).

---

## Strategia di lookup `Iscritto` → `legacy_anagrafica_id`

Riferimento per future `services.formazione_import`:

```python
def _lookup_legacy_id(cognome_nome: str, codice_fiscale: str | None = None) -> int | None:
    """Cerca AnagraficaDipendente per nome + CF di fallback.

    1) Match esatto Cognome Nome (case-insensitive, spazi normalizzati).
    2) Se ambiguo o assente: match su codice_fiscale (se fornito).
    3) Se ancora ambiguo: ritorna None — riga finisce in 'errori'.
    """
    # Implementazione in PATCH dedicata.
```

**Strategia di gestione duplicati nell'import**:
- Chiave naturale `TrainingEmployeeRecord` = `(legacy_anagrafica_id, corso, sessione, data_completamento)`.
- Upsert idempotente: se record esiste con stessi campi snapshot → skip.
- Se record esiste ma `idoneo`/`ore_frequentate` divergono → flag come "anomalia"
  per revisione manuale (non sovrascrivere automaticamente).

---

## Convenzioni formattazione Excel

Pattern osservati nei file gestionale (da replicare in export PATCH-07):

- **Date**: `gg/mm/aaaa` (es: "22/05/2026") — `cell.number_format = "DD/MM/YYYY"`.
- **Percentuali**: numero decimale (es: `100.0`), oppure stringa con `%` (es: `"100 %"`, `"0,00 %"`).
  - In export usare **numero decimale**, header "Ore partecipate (%)".
- **Booleani Sì/No**: stringa "Si" / "No" (notare: senza accento).
- **Decimali**: punto come separatore (`0.15`), oppure virgola in stringhe (`"0,00 %"`).
  - In export usare **punto come separatore**.
- **Codifica**: UTF-8. Header file gestionale ha alcuni caratteri corrotti
  (`Modalit�` invece di `Modalità`) — export portale deve usare UTF-8 corretto.

---

## Schema export "Iscritti a sessione" (PATCH-07)

Per l'export della pagina `formazione_iscritti.html` (singola sessione) si usa
uno **schema snello dedicato** (non round-trip al gestionale). Decisione
operativa 2026-05-22 — **modificabile in futuro** se servirà un export
round-trip con `courses-person.xlsx`.

Colonne (~11):

```
codice sessione | data sessione | docente | dipendente | stato iscrizione |
ore frequentate | percentuale presenza | idoneo | esito esame |
data completamento | note
```

Per round-trip totale con gestionale resta disponibile l'export
**Storico dipendente** (21 col `courses-person.xlsx`) usato dalla scheda
dipendente: filtrando per sessione si ottiene il subset equivalente.

---

## Note finali

- I file gestionale **non sono fonte di verità** del portale: una volta
  importati, i record vivono nei modelli `TrainingEmployeeRecord`,
  `TrainingLessonAttendance`, ecc.
- L'export PATCH-07 produce dati **derivati dal portale**, formattati come il
  gestionale per facilità di confronto/riconciliazione.
- Nessuna sincronizzazione bidirezionale: export e import sono **one-shot**
  manuali, supervisionati da operatore HR.
