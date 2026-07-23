# Epica A · Sotto-progetto A1 — Mansione di rischio: modello + resolver

**Data:** 2026-07-22
**Ambito:** Fondazione dell'Epica A (mansione di rischio "a vista"). Solo modello dati e
resolver condiviso. **Nessuna UI.**
**Riferimento:** `remediation-plan.md` punti 1.4 / 1.9 / 2.1 (Epica A).

## Decisioni già prese (dal committente)

1. La "mansione di rischio" è una **vista/aggregato**, non una nuova entità dedicata
   parallela: si **estende** lo strato esistente (`FattoreRischio` / `EsposizioneRischio` +
   `Mansione.dpi_richiesti` / `visite_richieste`), non lo si duplica.
2. Nel form "nuovo dipendente" (A2) resterà editabile la **mansione lavorativa**; il profilo
   di rischio sarà un **pannello derivato** in sola lettura. L'assegnazione **diretta** di
   un'esposizione a un singolo dipendente (1.9) avverrà dalla **scheda dipendente**.
3. Build in **3 incrementi** mergiabili singolarmente: **A1** (questo spec, modello +
   resolver, no UI) → A2 (form 1.4 + pannello scheda + assegnazione diretta 1.9) → A3
   (filtro DPI 2.1).

## Contesto di codice (già esistente, da riusare)

- `anagrafica/models_rischi.py::EsposizioneRischio` — collega un `FattoreRischio` a una
  `Mansione` **e/o** a un'`AreaAziendale` (entrambe FK nullable). Nessun target dipendente.
- `anagrafica/models.py::Mansione` — porta già `dpi_richiesti` (M2M `dpi.CategoriaDPI`) e
  `visite_richieste` (M2M `TipoVisitaMedica`): il "profilo di rischio diretto" della mansione.
- `anagrafica/services/mansionario.py` — resolver **già completo a livello mansione**:
  `requisiti_mansione` / `requisiti_per_nome` / `requisiti_per_nome_mansione` ritornano
  `{dpi, visite, corsi, piani, fattori}` come unione di requisiti diretti della mansione +
  ereditati dai `FattoreRischio` esposti. Il legame dipendente↔mansione è **per nome**
  (campo legacy `mansione` stringa ↔ `Mansione.nome` unique).
- `DipendenteAnagraficaAziendale.area_aziendale` (FK `AreaAziendale`) — già presente.

**Lacune che A1 colma:** il resolver mansione **non considera** (a) le esposizioni di
**area**, né (b) esposizioni **dirette al singolo dipendente** (che oggi non esistono nel
modello).

## Modello

Estendere `EsposizioneRischio` con un terzo target opzionale:

```python
legacy_anagrafica_id = models.IntegerField(
    null=True, blank=True, db_index=True,
    help_text="Esposizione assegnata direttamente a un singolo dipendente (1.9).",
)
```

- Un'esposizione può quindi puntare a **Mansione**, **Area**, **oppure un dipendente**.
- `clean()`: richiede **almeno uno** fra `mansione`, `area`, `legacy_anagrafica_id`
  (oggi richiede almeno mansione o area — si aggiunge il terzo alla condizione).
- `__str__`: includere il target dipendente quando valorizzato.
- Admin: esporre il nuovo campo (sola aggiunta a `fields`, non blocca A1).
- **Migrazione additiva**, SQL-Server-safe: colonna nullable, indice semplice
  (`db_index=True`), nessun indice parziale né `UniqueConstraint` condizionale. I record
  esistenti (mansione/area) restano invariati; il nuovo campo parte `NULL`.

## Resolver

Nuova funzione in `services/mansionario.py`:

```python
def requisiti_dipendente(legacy_id: int, *, mansione_nome=None, area_id=None) -> dict[str, list]:
    """Requisiti effettivi di un dipendente = unione di:
      1) requisiti della sua MANSIONE lavorativa (resolver esistente, per nome);
      2) esposizioni di AREA (EsposizioneRischio.area = area_aziendale del dipendente);
      3) esposizioni DIRETTE (EsposizioneRischio.legacy_anagrafica_id = legacy_id).
    Ritorna {dpi, visite, corsi, piani, fattori} con dedup fra le tre fonti.
    """
```

- **Fonte 1** riusa `requisiti_per_nome_mansione(nome)` (nessuna duplicazione della logica
  fattori→dpi/visite/corsi).
- **Fonti 2 e 3**: estrarre i `FattoreRischio` dalle esposizioni attive che puntano a
  quell'area / a quel dipendente e applicare la **stessa** derivazione fattore→requisiti già
  usata dal resolver mansione (fattorizzare l'helper interno `_resolve` per una lista di
  fattori, così le 3 fonti condividono un'unica implementazione).
- I parametri `mansione_nome` / `area_id` sono opzionali: se il chiamante li ha già (es. dal
  form) li passa per evitare un fetch legacy; altrimenti il resolver li risolve da
  `DipendenteAnagraficaAziendale` / dalla riga legacy anagrafica.
- **Dedup** per pk fra le fonti (riuso `_dedup`).

### Nota cessati

Le esposizioni dirette di un dipendente cessato **restano a DB** (storico); il resolver non
fa pulizia automatica. È usato su dipendenti attivi; nessun filtro cessati dentro il resolver
(coerente con l'uso previsto in A2/A3).

## Test (TDD, prima del codice)

**Modello (`tests` mirati):**
- esposizione con **solo** `legacy_anagrafica_id` è valida (`full_clean` passa);
- `clean()` **fallisce** se nessun target è valorizzato;
- esposizione mansione/area esistente resta valida (nessuna regressione).

**Resolver (`requisiti_dipendente`):**
- dipendente con mansione esposta a un fattore → eredita DPI/visite del fattore;
- esposizione **diretta** al dipendente aggiunge il fattore/DPI ai requisiti;
- esposizione di **area** (area del dipendente) aggiunge il fattore/DPI;
- **dedup**: lo stesso DPI da mansione e da esposizione diretta compare una sola volta;
- dipendente "nudo" (nessuna mansione riconosciuta, nessuna esposizione) → `requisiti_vuoti()`.

## Fuori scope A1 (rimandato)

- Qualsiasi **UI**: form "nuovo dipendente" (1.4), pannello rischio sulla scheda, UI di
  assegnazione diretta → **A2**.
- **Filtro DPI** in fase di richiesta (2.1) → **A3**.
- Derivazione scadenze/idoneità, notifiche, audit di assegnazione (già coperti altrove).

## Criteri di completamento A1

- Migrazione additiva applicata; `manage.py check` pulito.
- Resolver `requisiti_dipendente` con test verdi (RED→GREEN).
- Nessuna regressione sui test esistenti di `mansionario` / anagrafica toccati.
- CHANGELOG aggiornato. README non toccato (nessuna superficie utente in A1).
