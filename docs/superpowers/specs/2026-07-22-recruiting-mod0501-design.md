# Recruiting MOD. 05-01 — design

Data: 2026-07-22
Branch: `feature/recruiting-mod0501`
Fonte: `PROMPT~2.MD` (digitalizzazione del Mod. 05-01 "Valutazione Selezione Risorse")

## Obiettivo

Digitalizzare il foglio Excel Mod. 05-01 come sezione **Recruiting** del portale: scheda
candidato, valutazione a punteggio pesato, secondo colloquio, transizione a Onboarding o
archiviazione in database, cruscotto KPI, il tutto con il gating riservato ai dati HR
sensibili e con tracciabilità delle decisioni utilizzabile come evidenza UNI/PdR 125.

## Collocazione

Sotto-modulo dell'app `anagrafica`, sul precedente di **MOD.128 MPQ** (`models_mpq.py`,
`views_mpq.py`, `forms_mpq.py` + blocco dedicato in `acl_bootstrap.py`).

Motivazione: riusa direttamente `services/onboarding.py`, i permessi HR e il design-system
`hub-` dell'app. Tutto il codice nuovo vive in **file nuovi**, così le sessioni parallele
che lavorano su `views.py`/`models.py` di anagrafica (>14k righe) non collidono. La
superficie condivisa è di poche righe:

| File | Modifica |
| --- | --- |
| `anagrafica/models_recruiting.py` | nuovo |
| `anagrafica/forms_recruiting.py` | nuovo |
| `anagrafica/views_recruiting.py` | nuovo |
| `anagrafica/services/recruiting.py` | nuovo |
| `anagrafica/templates/anagrafica/pages/recruiting_*.html` | nuovi |
| `anagrafica/tests_recruiting.py` | nuovo |
| `anagrafica/migrations/00XX_recruiting.py` | nuovo |
| `anagrafica/models.py` | +1 riga di import in coda (come MPQ) |
| `anagrafica/urls.py` | +1 import, +1 blocco contiguo di `path()` |
| `anagrafica/acl_bootstrap.py` | +1 blocco `_RECR_*`, bump chiave cache a `v9` |
| `anagrafica/admin.py` | +registrazioni |

## Modello dati

### `RecruitingCriterio`

Il criterio di valutazione **non** è hardcoded: è una riga di tabella.

- `codice` (slug univoco), `label`, `descrizione`
- `rubrica` — testo libero: cosa significa 1, cosa significa 3, cosa significa 5
- `peso_percentuale` (Decimal)
- `ordine`, `is_active`

Seed via data-migration con i 5 criteri dell'Excel e i pesi originali:
Sintonia 20, Vicinanza 15, Esperienze pregresse 25, Capacità relazionali 20,
Competenze tecniche 20.

Conseguenza voluta: ripesare, disattivare "Vicinanza" o scrivere una rubrica sono
**decisioni HR** eseguibili dall'interfaccia, non modifiche di codice con migrazione.

### `Candidato`

Una sola entità per tutto l'iter: step 1 e step 2 stanno sulla stessa riga.

- *Provenienza*: `data_primo_colloquio`, `canale_provenienza`, `nome`, `cognome`,
  `cellulare`, `email`, `localita`, `provincia`, `mansione_cercata`, `azienda_attuale`,
  `mansione_attuale`, `livello_contratto_attuale`, `occupato_attualmente`
- *Informativi, mai a punteggio*: `eta`, `titolo_studio`, `cittadinanza`
- *Esito CV*: `cv_esito` (OK/KO), `colloquio_effettuato`
- *Valutazione*: `punteggio_ponderato` (denormalizzato, scritto solo dal server),
  `lingua_inglese_livello`, `idoneita_tirocinio`, `idoneita_apprendistato`,
  `disponibilita`, `motivo_cambio_lavoro`, `note`, `rischio_abbandono` (1-10),
  `giudizio_finale` (POSITIVO/NEGATIVO/vuoto)
- *Step 2*: `data_secondo_colloquio`, `note_secondo_colloquio`, `comunicazione_esito`,
  `data_assunzione`
- *Esito*: `stato`, `legacy_anagrafica_id`, `onboarding_pratica` (FK null)

Stati: `NUOVO` → `CV_VALUTATO` → `COLLOQUIO_1` → `COLLOQUIO_2` →
`ASSUNTO` / `IN_DATABASE` / `SCARTATO` / `RINUNCIA`.

### `CandidatoPunteggio`

`candidato` × `criterio` × `valore` (1-5), unique insieme.

Qui sta la garanzia di conformità richiesta dal prompt: **un punteggio può esistere solo
in relazione a un `RecruitingCriterio`**. `eta` e `cittadinanza` sono campi scalari di
`Candidato` e non hanno alcun percorso — nemmeno indiretto — verso il calcolo del
ponderato. Un test lo verifica esplicitamente.

### `CandidatoLog`

`candidato`, `campo`, `valore_prima`, `valore_dopo`, `user`, `at`.

Registra ogni cambio di punteggio e di giudizio finale: è l'evidenza di tracciabilità
delle decisioni da esibire in audit, visibile in scheda. Affianca (non sostituisce)
`core.audit.log_action`, che resta il registro di sicurezza.

### `RecruitingPermission`

Singleton modellato su `AnagraficaVisiteMedichePermission`: `accesso` in
TUTTI/ADMIN/RUOLI, default **ADMIN**, `ruolo_ids` JSON per la modalità RUOLI.

## Calcolo del punteggio

Solo lato server, in `services/recruiting.py`:

```
ponderato = Σ(valore_i × peso_i) / Σ(peso_i)   sui criteri attivi e compilati
```

La normalizzazione sulla **somma dei pesi effettivi** (non su 100) tiene il risultato
sulla scala 1-5 anche quando HR disattiva un criterio o la valutazione è incompleta.
Il template può mostrare un'anteprima JS, ma il valore persistito è sempre quello
ricalcolato dal server al salvataggio.

## Transizione di fine iter

- **Assunto → Onboarding**: `services.recruiting.assumi_e_avvia_onboarding()` crea il
  dipendente legacy dai dati già raccolti (`upsert_anagrafica_dipendente`) e chiama
  `anagrafica.services.onboarding.avvia_onboarding()`, salvando `legacy_anagrafica_id` e
  `onboarding_pratica` sul candidato. Idempotente: se il candidato è già collegato non
  duplica nulla. Nessuna doppia immissione manuale.
- **Mantieni in database**: stato `IN_DATABASE`, il profilo resta nella lista filtrabile
  per mansione, canale, punteggio, esito e data.

## KPI

Cruscotto con: candidati per periodo / canale / mansione, media ponderata aggregata,
percentuale di esiti positivi e negativi, giorni medi tra primo e secondo colloquio,
tasso di trasformazione in assunzione.

## Permessi

Due strati, come il resto del portale:

1. **ACL v2 canonico**: `anagrafica.recruiting.view` e `anagrafica.recruiting.manage`, con
   `RoutePermissionBinding` su **tutte** le route del modulo. Obbligatorio: con
   `ACL_STRICT_CANONICAL=True` (attivo in produzione) una route non mappata viene negata a
   tutti i non-superuser.
2. **Singleton di sezione** `RecruitingPermission`, default ADMIN, verificato in view.

## Note di conformità UNI/PdR 125

Il modulo non decide al posto di HR: espone le scelte. Nella pagina *Impostazioni criteri*
compare un pannello con i quattro punti da validare con HR:

1. "Sintonia" e "Vicinanza" sono soggettivi rispetto a "Competenze tecniche": valutare una
   rubrica con esempi per ogni livello 1-5 (il campo `rubrica` esiste apposta).
2. "Vicinanza" può essere un proxy indiretto di caratteristiche protette: decidere se
   resta criterio a punteggio o diventa informazione logistica (basta `is_active=False`).
3. Età e cittadinanza restano informativi: garantito dalla struttura dati, non da una
   convenzione.
4. Ogni cambio di punteggio o giudizio è loggato con autore, istante e valore precedente.

## Test

`anagrafica/tests_recruiting.py` copre: calcolo ponderato (inclusi criterio disattivato e
valutazione parziale), impossibilità che età/cittadinanza influenzino il punteggio,
gating del singleton e delle route, transizione a Onboarding e sua idempotenza,
scrittura del log su cambio punteggio/giudizio, KPI.
