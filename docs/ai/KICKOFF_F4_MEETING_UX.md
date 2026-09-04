# KICK-OFF F4 — Fruibilità e gestione degli incontri

Piano di lavoro derivato dalla ricerca comparativa 2026-09-04 su Fellow, Hypercontext,
Notion Meetings (agenda/action item), Convene / OnBoard / Diligent (verbali e board
portal), Asana / Smartsheet / monday (RAID log).

Stato di partenza: `tasks` a `0cacbe05`, ultima migration `tasks/0036`.
Nomenclatura: **convocazione** = `KickoffMeetingForm` / `project_meeting_edit`,
**esito** = `KickoffMeetingMinuteForm` / `project_meeting_minutes`.

Regole valide per tutti i punti:

- Nessun nuovo namespace CSS: si riusa `tasks.css` e i token del tema (light + dark).
- Nessun nuovo permesso ACL: si resta su `tasks_view` / `tasks_create` + `_can_manage_project`.
- Ogni scrittura passa da `log_action` come le altre azioni incontro.
- Migrations numerate in sequenza da `0037`; dopo ogni merge `makemigrations --check`.
- Test in `tasks/tests_meeting_flow.py` (o nuovo `tests_meeting_ux.py` se il file supera le ~1200 righe).
- `CHANGELOG.md` + `README.md` aggiornati a ogni ondata.

Ordine di esecuzione: **Ondata A** (1, 4, 6, 8, 9) → **Ondata B** (2, 3, 7) → **Ondata C** (5).

---

## Ondata A — costo basso, nessun cambio di modello concettuale

### P1 · Presenze effettive ≠ convocati

**Perché** Ogni prodotto di verbalizzazione distingue presenti / assenti: è il primo dato
che un auditor cerca e oggi il portale non lo ha. `partecipanti_utenti` è solo l'invito.

**Stato attuale** `KickoffMeeting.partecipanti_utenti` (M2M) + `partecipanti_email_extra`
(testo) + `partecipanti_testo` (note). `minute_email._partecipanti_text()` stampa tutti
come se fossero presenti.

**Progetto**

- `KickoffMeeting.presenti_utenti` — M2M a `AUTH_USER_MODEL`, `blank=True`,
  `related_name="kickoff_meetings_presente"`.
- `KickoffMeeting.presenti_email_extra` — `TextField` (una email per riga), stesso
  formato di `partecipanti_email_extra`.
- `KickoffMeeting.presenze_registrate_at` — `DateTimeField(null=True)`: distingue
  "nessuno presente" da "presenze mai registrate" (incontri storici).
- Proprietà `assenti_utenti` / `assenti_email` calcolate per differenza sui convocati.
- UI: sezione **Presenze** in cima alla pagina esito, checkbox per ogni convocato
  (utenti + email extra), tutte spuntate di default alla prima apertura.
- Minuta email + PDF: la sezione "Partecipanti" diventa "Presenti" e, se
  `presenze_registrate_at` è valorizzato e ci sono assenti, si aggiunge "Assenti".
  Per gli incontri storici (presenze mai registrate) il comportamento resta quello di oggi.

**Checklist**

- [x] migration `0037_kickoffmeeting_presenti_email_extra_and_more`
- [x] campi + proprietà `assenti_*` su `KickoffMeeting`
- [x] `KickoffMeetingMinuteForm`: campi presenze (M2M limitata ai convocati + checkbox email)
- [x] `project_meeting_minutes.html`: blocco "Presenze" con "Tutti presenti / Nessuno"
- [x] `project_meeting_detail.html`: badge "N presenti su M convocati" quando registrate
- [x] `minute_email._presenze_sections` → "Presenti" / "Assenti", fallback "Partecipanti"
- [x] test: salvataggio presenze, calcolo assenti, minuta con e senza presenze registrate

### P4 · I punti ODG non discussi si riportano al prossimo incontro

**Perché** Rolling agenda (Hypercontext): ciò che non si è discusso non deve sparire.
Oggi il carry-over esiste solo per i `MeetingIssue` aperti.

**Stato attuale** `project_meeting_create` precarica l'agenda con
`_meeting_issue_agenda_item(issue)` per ogni issue aperta. `agenda_items[].done` è già
gestito da `project_meeting_agenda_toggle`.

**Progetto**

- Helper `_carry_over_agenda_items(project)`: prende l'**ultimo incontro svolto** della
  commessa, seleziona gli item con `done=False` e `source != "meeting_issue"`
  (i problemi arrivano già per la loro strada), li riemette con nuovo `id`,
  `source="carry_over"`, `carried_from_numero=<numero>`, `done=False`, `locked=False`.
- Precedenza in `project_meeting_create`: prima i problemi aperti, poi i riportati.
- Badge "Riportato dall'incontro N" nel form e nel dettaglio (usa `custom_fields`,
  nessun campo nuovo da rendere).
- Nella pagina esito, avviso "N punti non spuntati verranno riproposti nel prossimo incontro".

**Checklist**

- [x] `_carry_over_agenda_items()` + aggancio a `project_meeting_create`
- [x] badge origine ("Riportato da: Incontro N") nel form / dettaglio, via `custom_fields`
- [x] avviso nella pagina esito
- [x] test: punto non discusso riportato, punto discusso no, issue non duplicata, solo da incontri svolti

### P6 · Modelli di ordine del giorno

**Perché** Fellow vende la libreria di template; qui ogni incontro riparte da zero.

**Progetto**

- Modello `MeetingAgendaTemplate(nome, descrizione, items JSON, is_active, order_index,
  created_by, created_at, updated_at)`.
- Gestione in `/tasks/impostazioni/?tab=modelli` (nuovo `_tab_modelli.html`, coerente con
  gli altri tab appena scorporati).
- Nel form incontro: menu **"Carica modello"** (sostituisce/aggiunge i punti, chiede
  conferma se l'agenda non è vuota) e **"Duplica ODG dall'incontro precedente"**.
- I punti caricati da modello sono normali `agenda_items` (nessun vincolo successivo).

**Checklist**

- [x] migration `0039_meetingagendatemplate`
- [x] modello + CRUD nel tab `?tab=modelli` (`_tab_modelli.html`, `_handle_tasks_agenda_templates_post`)
- [x] ~~endpoint JSON~~ → i modelli attivi viaggiano nel contesto del form (`json_script`), nessuna rotta in più
- [x] pulsanti "Carica modello" / "Duplica ODG precedente" nel form incontro
- [x] test: creazione con durate, solo modelli attivi al form, duplica esclude i problemi, tab apre

### P8 · Chiusura (approvazione) della minuta

**Perché** Board portal: il verbale si blocca all'approvazione e ogni riapertura è
tracciata. Oggi l'esito è modificabile all'infinito senza traccia di versione.

**Progetto**

- Campi `minuta_chiusa_at`, `minuta_chiusa_da` (FK utente), `minuta_riaperture` (int).
- Azione **"Approva e chiudi minuta"** (POST, `can_manage`) dal dettaglio incontro.
- A minuta chiusa: `project_meeting_minutes` in GET mostra sola lettura e in POST
  rifiuta con messaggio; l'invio minuta e il PDF restano disponibili.
- **"Riapri minuta"**: richiede un motivo (testo obbligatorio), incrementa il contatore,
  `log_action("kickoff_meeting_minute_reopen", …, {"motivo": …})`.
- PDF e email: riga "Minuta approvata il … da …" nei fatti di testata.

**Checklist**

- [x] migration `0038_kickoffmeeting_minuta_chiusa_at_and_more`
- [x] view `project_meeting_minute_close` / `project_meeting_minute_reopen`
- [x] guardia in `project_meeting_minutes`: a minuta chiusa GET e POST rimandano al dettaglio
- [x] badge "Minuta approvata" nel dettaglio + riga nei fatti di PDF/email
- [x] test: incontro non svolto non si approva, chiusura blocca il POST, riapertura richiede motivo

### P9 · "I miei incontri" e ricerca trasversale

**Perché** Oggi si arriva a un incontro solo dalla commessa o dal calendario del mese:
manca l'elenco filtrabile e la ricerca nel testo delle minute.

**Progetto**

- Route `tasks:incontri_lista` → `/tasks/incontri/`, `tasks_view`, scope
  `_scoped_projects_queryset`.
- Filtri: `mine` (default: incontri dove sono convocato o presente), stato, periodo
  (prossimi / passati / tutti), commessa, testo `q` su titolo, note, ODG e decisioni.
- Toggle Calendario ↔ Elenco in cima a entrambe le pagine.
- Riga cliccabile, badge stato, colonna commessa/numero/data/partecipanti.

**Checklist**

- [x] view `incontri_lista` + template `incontri_lista.html` (`/tasks/incontri/`)
- [x] toggle Elenco ↔ Calendario
- [x] voce ACL in `acl_bootstrap.py` (`tasks.kickoff.view`)
- [x] test: default "i miei", scope tutti, ricerca nel verbale

---

## Ondata B — struttura del dato

### P2 · Next step strutturati (chi fa cosa entro quando)

**Perché** `next_steps` è un `TextField`: nessun owner, nessuna scadenza, nessun
rollforward. Fellow/Hypercontext trattano l'action item come oggetto di prima classe.

**Stato attuale** `create_tasks_from_next_steps()` e
`project_meeting_task_from_step` creano un `Task` da una riga di testo, a mano.

**Progetto**

- Modello `MeetingActionItem`, simmetrico a `MeetingIssue`:
  `project`, `source_meeting`, `title`, `description`, `assigned_to`, `due_date`,
  `status` (OPEN/DONE), `linked_task`, `done_at`, `done_by`, `created_by`, timestamp.
- Nella pagina esito: righe strutturate come i problemi (titolo, responsabile, scadenza,
  "crea attività collegata"). `next_steps` resta come campo storico, con l'etichetta
  "campo storico" già usata per `problemi_aperti`.
- Carry-forward: gli action item aperti entrano nell'agenda del prossimo incontro e nel
  digest giornaliero, esattamente come i `MeetingIssue`.
- Nessuna migrazione dati automatica: i testi esistenti restano visibili nel campo storico.

**Checklist**

- [ ] migration `0040_meetingactionitem`
- [ ] modello + helper `_sync_meeting_action_items_from_post`
- [ ] blocco "Azioni (chi fa cosa entro quando)" nella pagina esito
- [ ] carry-forward in agenda + digest
- [ ] chiusura azione dal dettaglio incontro e dalla Panoramica
- [ ] test: creazione, chiusura, carry-forward, digest

### P3 · Registro decisioni

**Perché** Le decisioni finiscono nel verbale libero: irrecuperabili a mesi di distanza.
RAID log e board portal le tengono separate.

**Progetto**

- Modello `MeetingDecision(project, meeting, testo, decisa_da (FK utente, opzionale),
  data, impatto BASSO/MEDIO/ALTO, agenda_item_id opzionale, created_by, created_at)`.
- Blocco "Decisioni" nella pagina esito (riga = testo + chi + impatto).
- Sezione "Registro decisioni" nella Panoramica commessa (ultime 5) e pagina
  `/tasks/projects/<id>/decisioni/` con l'elenco completo.
- Sezione "Decisioni" in minuta email e PDF.

**Checklist**

- [ ] migration `0041_meetingdecision`
- [ ] modello + sync dal POST esito
- [ ] blocco nella pagina esito + elenco nel dettaglio incontro
- [ ] registro di commessa + link dalla Panoramica
- [ ] sezione in `_minute_sections`
- [ ] test: creazione, resa in minuta, registro di commessa

### P7 · I convocati possono proporre punti all'ordine del giorno

**Perché** La preparazione collaborativa è lo standard dei tool moderni; qui l'agenda la
scrive solo chi ha `tasks_create`.

**Progetto**

- Modello `MeetingAgendaProposal(meeting, proposed_by, titolo, nota, stato
  PENDING/ACCEPTED/REJECTED, decided_by, decided_at, created_at)`.
- Dal dettaglio incontro, se l'utente è fra i convocati: form "Proponi un punto".
- Il gestore vede le proposte in attesa con **Accetta** (l'item entra in `agenda_items`
  con `source="proposal"`) o **Rifiuta** (con nota facoltativa).
- Notifica in-app al gestore alla proposta, al proponente alla decisione.

**Checklist**

- [ ] migration `0042_meetingagendaproposal`
- [ ] modello + view proponi / accetta / rifiuta
- [ ] blocco nel dettaglio incontro (due viste: convocato / gestore)
- [ ] notifiche
- [ ] test: permessi (non convocato non propone), accettazione crea l'item, rifiuto no

---

## Ondata C — conduzione

### P5 · Vista "conduci la riunione"

**Perché** È ciò che sposta davvero l'uso quotidiano: oggi la durata per punto esiste ma
non è sommata, non è confrontata con l'orario, e l'esito si scrive dopo in un form lungo.

**Progetto**

- Route `/tasks/projects/<id>/incontri/<mid>/conduci/`, `can_manage`.
- Schermata a punto corrente: titolo, responsabile, durata stimata, timer, nota rapida,
  pulsanti **Discusso** / **Rimanda** / **Punto successivo**.
- Barra in testa: tempo pianificato totale vs trascorso, avviso di sforamento.
- Cattura rapida durante il punto: **azione** (P2), **decisione** (P3), **problema**
  (`MeetingIssue`) senza uscire dalla schermata.
- Autosave su endpoint JSON (`agenda_item_update`: nota, done, `tempo_effettivo_minuti`).
- A fine riunione, "Chiudi e vai all'esito" precompila la pagina esito con quanto raccolto.

**Checklist**

- [ ] endpoint `project_meeting_agenda_item_update` (nota / done / tempo effettivo)
- [ ] endpoint di cattura rapida azione / decisione / problema
- [ ] template `project_meeting_run.html` + CSS in `tasks.css`
- [ ] barra tempi e avviso sforamento
- [ ] passaggio alla pagina esito precompilata
- [ ] test: autosave, permessi, tempi, precompilazione esito

---

## Rischi trasversali

- **Numerazione migration**: sessioni parallele lavorano su `assets` e `anagrafica`;
  dopo ogni merge verificare `makemigrations --check` per `tasks`.
- **`agenda_items` è JSON senza schema**: ogni nuova chiave va difesa in
  `clean_agenda_items_raw`, che è il solo punto di normalizzazione.
- **Minuta**: email e PDF condividono `_minute_sections()`. Ogni nuova sezione va
  aggiunta lì, mai in uno solo dei due.
- **Incontri storici**: presenze, minuta chiusa e action item non esistono sui record
  vecchi; ogni resa deve degradare al comportamento attuale quando il dato manca.
