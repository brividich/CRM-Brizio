# Design — Visite mediche: sessione "consona" e scadenze confermate

Data: 2026-07-15 · Stato: approvato dall'utente (brainstorming) · Modulo: `anagrafica`

## Contesto e problema

Il modulo visite mediche registra le visite (`VisitaMedica`) per tipologia
(`TipoVisitaMedica`, periodicità in `durata_mesi`, obbligo derivato dai ruoli
operativi e dai processi MOD.128). La registrazione batch avviene dalla pagina
"Registra sessione visite mediche" (`visite_mediche_nuova_sessione`): si sceglie
un tipo, il sistema propone i candidati, si registrano gli esiti.

Problemi rilevati nel codice attuale:

1. **Proposta candidati non "consona"** (`_build_candidati_sessione`, `views.py`):
   - il pool con ruoli collegati **non esclude i cessati**;
   - i requisiti da **processi MOD.128** (`mpq_visite.tipi_visita_richiesti_da_processo`)
     sono ignorati: chi deve la visita per abilitazione a processo non viene mai proposto;
   - tipo **senza ruoli configurati** → viene proposta **tutta l'azienda** attiva;
   - una visita senza scadenza (`data_scadenza=None`, durata 0) è classificata
     "scaduta" e ripropone il dipendente per sempre;
   - l'**aggiunta manuale** accetta chiunque senza segnalare che il tipo non è
     pertinente per quel dipendente.
2. **La scadenza non "scade" dopo la registrazione**: la dashboard visite
   (`visite_mediche_dashboard`) calcola KPI "scadute"/"in scadenza", la tabella
   "scadute o in scadenza" e i contatori per tipologia (`scadute_db`/`valide_db`)
   su **tutte le righe storiche**: dopo aver registrato la nuova sessione, la
   vecchia scadenza superata resta visibile come "scaduta". Stesso difetto nel
   digest AU45 (`send_visite_mediche_digest`).
3. **Doppia definizione di "ultima visita"**: i servizi
   (`services/visite.py`, `services/conformita.py`) usano max `data_svolgimento`;
   dashboard, scadenzario e index usano `Max(id)` — sbaglia quando si inserisce
   a posteriori una visita retrodatata.
4. **Guardrail assenti nel batch**: nessun controllo anti-doppione, la data
   futura è permessa (il form singolo `VisitaMedicaForm` la vieta), il campo
   "Note/Prescrizioni" finisce solo in `prescrizioni`, nessun referto per riga.

## Obiettivi

- La sessione propone **solo** dipendenti per cui il tipo è davvero richiesto
  (ruoli + MOD.128, cessati esclusi) e mostra il perché.
- Registrata la visita, la vecchia scadenza si rinnova **ovunque**
  (dashboard, KPI, digest) — "scade in quanto confermata". Nessun nuovo stato.
- **Una sola definizione** di "ultima visita per (dipendente, tipo)" riusata da
  tutte le superfici.
- Guardrail: anti-doppione, niente date future, avviso su aggiunte manuali non
  pertinenti.
- Riga di sessione più ricca: anteprima nuova scadenza, referto opzionale,
  prescrizioni separate dalle note, suggerimenti medico competente.

## Non-obiettivi (fuori scope, idee future)

- Stato "programmata/convocazione" con conferma esiti post-visita.
- Flusso dipendente-first multi-tipo (una sessione con tipi misti).
- Anagrafica strutturata dei medici competenti (nuovo modello).
- PDF "registro sessione" sul template standard `core/pdf`.
- Notifica al dipendente alla registrazione della visita.

## Design

### 1. Fonte unica "ultima visita" (approccio scelto: helper di servizio)

In `anagrafica/services/visite.py`:

- `ultime_visite_correnti_ids(legacy_ids=None, tipo_ids=None) -> set[int]`:
  id delle `VisitaMedica` "correnti", cioè l'ultima per
  coppia `(legacy_anagrafica_id, tipo_id)`. Definizione canonica: **max
  `data_svolgimento`, spareggio `pk` più alto**. Implementazione SQL Server-safe
  a due passaggi (pattern già usato in `ultime_visite_per_tipo`): prima
  `values(...).annotate(Max("data_svolgimento"))`, poi risoluzione degli id con
  spareggio su `pk`. Nessuna migrazione, nessun campo denormalizzato
  (alternative B flag denormalizzato e C tabella cache scartate: doppia fonte
  di verità, manutenzione su ogni scrittura).
- `ultime_visite_per_tipo` e `_ultime_visite_map` (conformità) restano ma vanno
  allineati alla stessa definizione (già max data; verificare spareggio `pk`).

Consumatori da migrare all'helper:

| Superficie | Oggi | Dopo |
|---|---|---|
| Dashboard visite: KPI scadute/in scadenza | tutte le righe | solo correnti |
| Dashboard visite: tabella "scadute o in scadenza" (+ filtri mese) | tutte le righe | solo correnti |
| Dashboard visite: `valide_db`/`scadute_db` e copertura per tipologia | tutte le righe | solo correnti |
| Dashboard visite: pannello "sessioni per tipo" | `Max(id)` | helper |
| Index anagrafica: `n_visite_scadute` | `Max(id)` | helper |
| Scadenzario: sezione visite | `Max(id)` | helper |
| Export Excel `visite_mediche_export_scadenze` | tutte le righe | solo correnti |
| Digest AU45 `send_visite_mediche_digest` | tutte le righe in finestra | solo correnti |

Il KPI "visite totali" della dashboard resta sul conteggio storico (è dichiarato
come totale registrazioni). `send_visite_expiry_reminders`, conformità e
riepilogo dipendente usano già l'ultima visita per tipo: nessun cambio di
comportamento, solo eventuale riuso dell'helper.

### 2. Candidati sessione "consoni" (`_build_candidati_sessione`)

Pool dei candidati per il tipo scelto = unione di:

- **Ruoli**: dipendenti con almeno un ruolo operativo collegato al tipo,
  **esclusi i cessati** (`DipendenteAnagraficaAziendale.data_cessazione` valorizzata);
- **Processi MOD.128**: dipendenti con `AbilitazioneProcesso` ATTIVA su un
  processo che ha il tipo in `visite_richieste` (lookup inverso di
  `mpq_visite.tipi_visita_richiesti_da_processo`), cessati esclusi;
- **Storico** (solo per tipi senza ruoli E senza processi **collegati** —
  conta la configurazione del tipo, non quante persone hanno il ruolo):
  dipendenti attivi che hanno **almeno una visita di quel tipo nello storico**
  (stato calcolato sull'ultima) — non più tutta l'azienda. In pagina appare un
  avviso "tipo senza ruoli/processi collegati: candidati proposti dallo
  storico". Un tipo con ruoli collegati ma nessun assegnatario produce zero
  candidati (non degrada allo storico).

Filtro sullo stato (invariato nella soglia: scaduta / in scadenza ≤90gg / mai
effettuata) con due correzioni:

- ultima visita con `data_scadenza=None` → **valida senza scadenza**, NON
  candidata (oggi è trattata come scaduta);
- "mai effettuata" si applica solo a chi è nel pool ruoli/processi (per lo
  storico non ha senso).

Ogni riga candidata espone: nome (link scheda), ultima visita (data + esito),
**scadenza attuale**, stato, **origine della proposta** (badge: Ruolo /
Processo / Storico), esito da registrare, prescrizioni, note, referto.
In testata: **anteprima della nuova scadenza** (data sessione + `durata_mesi`).

**Aggiunta manuale**: l'API `visite_mediche_api_cerca_dipendente` riceve anche
`tipo_id` e ritorna per ogni risultato `pertinente: bool` (il tipo è richiesto
per quel dipendente da ruoli/processi; se il tipo non ha né ruoli né processi
collegati la pertinenza non è valutabile e vale sempre `true`). La riga aggiunta
con `pertinente=False` mostra un badge di avviso "tipo non richiesto per questo
dipendente" (non bloccante). I cessati non compaiono nella ricerca.

### 3. Guardrail registrazione (POST step 2)

- **Anti-doppione**: se esiste già una `VisitaMedica` con stesso
  `(legacy_anagrafica_id, tipo, data_svolgimento)`, la riga è **saltata** e
  conteggiata nell'esito ("N già registrate, saltate").
- **Retro-registrazione sospetta**: se l'ultima visita corrente del tipo ha
  `data_svolgimento >` data sessione, la riga è comunque salvata ma il messaggio
  finale segnala che non diventa la visita corrente (la definizione canonica
  per data garantisce che non alteri le scadenze).
- **Data futura vietata** anche nel batch (allineamento a `VisitaMedicaForm`):
  errore bloccante in step 1 e ricontrollo in step 2.
- **Audit**: `VISITA_MEDICA_BATCH_CREATA` arricchito con conteggi
  creati/saltati e numero di righe non pertinenti registrate.

### 4. Riga di sessione più ricca

- **Referto per riga**: `<input type="file" name="referto_{legacy_id}">`
  opzionale; il salvataggio riusa lo stesso percorso del form singolo
  (creazione `DocumentoDipendente` tipo `VISITA_MEDICA_REFERTO` in storage
  privato + aggancio a `referto_documento`). Form con `enctype="multipart/form-data"`.
- **Prescrizioni e Note separate**: due campi per riga
  (`prescrizioni_{id}`, `note_{id}`), salvati nei rispettivi campi modello
  (oggi l'unico campo finisce in `prescrizioni` e `note` resta vuoto).
- **Medico competente**: `<datalist>` alimentato dai valori distinti già usati
  in `VisitaMedica.medico_competente` (niente nuovo modello); resta testo libero.

### 5. Test (label `anagrafica`, `--keepdb`, settings test)

- Helper: ultima per (dip, tipo) con retrodatata inserita dopo (id più alto,
  data più vecchia → NON corrente); spareggio a parità di data.
- Dashboard: dopo nuova visita, KPI scadute e tabella non mostrano più la
  scadenza superata; contatori per tipologia coerenti.
- Candidati: cessato escluso; abilitato MOD.128 incluso; tipo senza
  ruoli/processi → solo storico; `data_scadenza=None` non candidata.
- POST: doppione saltato; data futura respinta; prescrizioni/note nei campi
  giusti; referto per riga creato e agganciato.
- API ricerca: flag `pertinente`, cessati esclusi.
- Digest AU45: righe superate escluse.
- Regressione: `send_visite_expiry_reminders` invariato.

### 6. Rollout

- Lavoro in worktree dedicato, branch feature, commit + push
  (regole Session Isolation di CLAUDE.md).
- CHANGELOG.md sotto `[Unreleased]` con tutti i file toccati; README.md
  (sezione anagrafica/visite) per il comportamento visibile; version bump
  secondo checklist `docs/ai/06_TESTING_AND_QUALITY_GATES.md`.
- Nessuna migrazione DB. Privacy invariata: gating `_can_view_visite_mediche`
  su tutte le superfici; nessun dato sanitario in log/audit oltre ai conteggi.

## Rischi e note

- La correzione della definizione "ultima visita" può cambiare i numeri della
  dashboard rispetto a oggi (in meglio: spariscono i falsi "scaduti"); da
  segnalare nel CHANGELOG come fix di coerenza.
- L'upload referto nel batch aumenta la dimensione della richiesta: limite
  dimensione/estensioni identici al form singolo.
- `tipo_id` aggiunto all'API di ricerca: endpoint già autenticato e gated;
  ritorna solo nome + flag pertinenza (nessun dato sanitario).
