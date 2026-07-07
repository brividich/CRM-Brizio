# ANALISI 02 — MODULI OPERATIVI · Gestione Specifiche (FSM 9 stati) · Carichi Macchina · Skill Matrix MOD.187

**Data:** 2026-07-05
**Perimetro:** SOLO le aree richieste — `gestione_specifiche` (macchina a stati S1–S9, MOD.133, OFI, share), `gestione_carichi_macchina` (matrice Excel/Gantt, cell editing HTMX, reschedule, importer), Skill Matrix MOD.187 (in `anagrafica`: `models_skillmatrix.py`, `services/skillmatrix_*`, view `skm_*`/`skill_matrix_macchina`). Non esiste un'app `gestione_competenze` separata: la skill matrix vive in `anagrafica`.
**Modalità:** analisi read-only, file per file, in sequenza. Nessuna modifica al codice, nessun comando che altera stato.
**Focus richiesto:** transizioni FSM non gestite · race condition su django-q2 · HTMX cell editing senza validazione lato server.

---

## Executive summary

I tre moduli sono tra i **meglio costruiti del portale**: codice recente, bootstrap ACL v2 completo (rotte di scrittura separate da quelle di lettura, sezioni admin bound, API mappata nel gate middleware), test presenti (8 file in carichi macchina, 8 suite skill matrix), share UNC con hardening esemplare (canonicalizzazione lessicale + `realpath` + `commonpath`, dry-run/rollback/audit, mai overwrite silenzioso), audit append-only immutabile (`EventoSpecifica`, `AbilitazioneMacchinaStorico`, `RegistroAzione`).

Sui tre fronti di attenzione richiesti l'esito è:

1. **Transizioni FSM**: la *definizione* della macchina a stati è completa e coerente (matrice T2 rispettata, slot separati sospensione/errore S5/S9 che si annidano senza calpestarsi, `GET_STATE` guardati, S9 con `source="+"` che impedisce S9→S9). Il rischio **non è nella FSM ma nella sua esecuzione**: nessuna protezione di concorrenza (niente `ConcurrentTransitionMixin`/`select_for_update`) e side-effect di transizione eseguiti **fuori transazione** in metà delle view (l'altra metà, `mod133_approva`, fa da modello corretto).
2. **Race su django-q2**: i job sono **CRON giornalieri** (06:30/07:00/07:15), non orari come dicono i docstring; il pattern check-then-act su `reminder_inviato`/`escalation_inviata` è reale ma a bassa esposizione. Il rischio maggiore legato ai job è un altro: la **sospensione automatica per continuità persa (SKM) non è schedulata affatto** — l'unica regola bloccante della skill matrix dipende da un command manuale.
3. **HTMX cell editing senza validazione server**: confermato in `gestione_carichi_macchina.cella_edit` — `turno`/`stato`/`fase` non sono validati né contro le choices né contro la capability turni della macchina (`update()`/`create()` bypassano la validazione modello). In gestione_specifiche il formset Django valida correttamente; nella skill matrix il service valida i livelli. Il caso concreto è uno solo, ma è sul percorso di scrittura principale del modulo.

Tema trasversale di compliance: **attribuzione dell'attore incompleta dove più conta** — lo storico refresh SKM non registra chi ha valutato (`car_legacy_id` mai passato) e l'auto-approvazione MOD.133 scrive sul documento una data di approvazione "umanizzata" (fabbricata), scelta documentata nel codice ma da far validare formalmente lato qualità.

---

## Tabella severità × effort

| ID | Finding | Modulo | Dimensione | Severità | Effort |
|----|---------|--------|-----------|----------|--------|
| F1 | Transizioni FSM senza protezione di concorrenza (+ race sul claim) | gestione_specifiche | Concorrenza / audit | **Media** | Medio |
| F2 | Side-effect di transizione fuori `transaction.atomic` in metà delle view | gestione_specifiche | Concorrenza / dati | Media | Basso |
| F3 | `applica_timbri` senza guardia di stato: composito ufficiale alterabile post-approvazione | gestione_specifiche | Integrità documento / FSM | **Media** | Basso |
| F4 | Auto-approvazione MOD.133 con data di approvazione "umanizzata" sul documento | gestione_specifiche | Compliance ISO/EN | Media | Decisione |
| F5 | Job reminder/escalation check-then-act + docstring in disaccordo con la cadenza reale | gestione_specifiche | Concorrenza django-q2 | Bassa | Basso |
| F6 | Numerazione OFI MAX+1 con lock solo su righe esistenti; autorizzazione per-modo demandata | gestione_specifiche | Concorrenza / autorizzazione | Bassa | Medio |
| F7 | `incaricato`/riassegna: id utente non validato (500 su id inesistente, fuori pool ammesso) | gestione_specifiche | Robustezza input | Bassa | Basso |
| F8 | `cella_edit` HTMX: `turno`/`stato`/`fase` non validati lato server (choices + capability) | gestione_carichi_macchina | Validazione input | **Media** | Basso |
| F9 | `reschedule` applica delta di calendario su griglia lavorativa: lavori "spariscono" nel weekend | gestione_carichi_macchina | Integrità dati / UX | **Media** | Basso |
| F10 | Race su reschedule/undo: barra primaria non lockata, undo last-write-wins | gestione_carichi_macchina | Concorrenza | Bassa | Basso |
| F11 | `update()` bypassa `updated_at`; dedup anti doppio-click senza vincolo DB | gestione_carichi_macchina | Robustezza dati | Bassa | Basso |
| F12 | Importer: `Commessa` dedup su `nome[:200]`, righe backlog lunghe collassano | gestione_carichi_macchina | Qualità dati import | Bassa | Basso |
| F13 | Storico refresh SKM senza attribuzione dell'attore (`car_legacy_id` mai valorizzato) | skill matrix | Audit / compliance MOD.187 | **Media** | Basso |
| F14 | Scoping CAR per reparto non enforced (chiunque con `manage` refresha ogni reparto) | skill matrix | Autorizzazione (scope) | Media | Medio |
| F15 | Continuità operativa: regola bloccante non schedulata + stato affidato a marker testuale in `note` | skill matrix | Affidabilità processo | Media | Basso |
| F16 | `applica_refresh`: `int(ab_id)` non guardato (500 su POST malformato), nessun lock | skill matrix | Robustezza / concorrenza | Bassa | Basso |

---

## Findings di dettaglio

### F1 — Transizioni FSM senza protezione di concorrenza · Media · gestione_specifiche

**Evidenza:** `Specifica.stato` è `FSMField(protected=True)` (`models.py:52`) e ogni view segue il pattern *get → transizione → save* senza lock né controllo ottimistico: `views.py:309-318` (`avvia_flow_down_view`), `views.py:625-660` (`_esegui_transizione` per sospendi/ripristina/annulla), `api.py:158-194` (endpoint `transizione`). django-fsm valuta lo stato **in memoria**: due richieste concorrenti che leggono entrambe S2 passano entrambe la guardia e salvano entrambe.

**Conseguenze concrete:** doppio `EventoSpecifica` per la stessa transizione (catena audit ISO 9001/EN 9100 sporcata); con transizioni *diverse* in gara (es. `sospendi` vs `approva_flow_down`) vince l'ultimo `save()` e l'audit registra due transizioni entrambe uscenti dallo stesso `stato_da`; con l'auto-deposito attivo, doppio deposito del composito sulla share. Analogamente `claim` (`views.py:336-351`) è check-then-set: due utenti che cliccano insieme superano entrambi il controllo `compilatore_id is None` e vince l'ultimo, mentre al primo viene mostrato "Task preso in carico".

**Raccomandazione:** adottare `ConcurrentTransitionMixin` di django-fsm su `Specifica` (controllo ottimistico nativo), oppure rileggere l'istanza con `select_for_update` dentro `transaction.atomic` prima di ogni transizione. Per `claim`, `update(...filter(compilatore__isnull=True))` con controllo righe toccate.

---

### F2 — Side-effect di transizione fuori transazione · Media · gestione_specifiche

**Evidenza:** i metodi di transizione scrivono su `MOD133` **immediatamente** (autocommit) mentre lo stato si salva **dopo**, nel chiamante: `avvia_flow_down` crea il MOD.133 e imposta `timer_anchor` (`models.py:145-152`), `sospendi`/`errore_tecnico` mettono in pausa il timer (`models.py:194-198,245-250`), `ripristina`/`ripristina_da_errore` spostano l'anchor (`models.py:211-217,262-269`), `approva_flow_down` supera e **salva** la revisione precedente (`models.py:168-172`). Se il `spec.save()` successivo fallisce (o la richiesta muore), restano effetti orfani: timer pausato con specifica ancora "in validità", revisione precedente superata con la nuova ancora in S2, MOD.133 creato con specifica in bozza.

**Contrasto interno:** `mod133_approva` (`views.py:510-520`) e `_auto_approva_se_configurata` (`views.py:425-438`) avvolgono correttamente esito+transizione+save in `transaction.atomic` — con commento che spiega esattamente questo rischio.

**Raccomandazione:** estendere il pattern atomico già presente alle altre view di transizione (`avvia_flow_down_view`, `_esegui_transizione`, endpoint API): `with transaction.atomic(): metodo(); spec.save()`. Effort basso, il modello c'è già nel file.

---

### F3 — `applica_timbri` modificabile dopo l'approvazione · Media · gestione_specifiche

**Evidenza:** `mod133_compila` è bloccata fuori da S2 con motivazione esplicita: «il composito ufficiale legge le righe live → un edit post-approvazione cambierebbe il documento ufficiale in silenzio» (`views.py:355-363`). Lo **stesso argomento vale per i timbri**, ma `applica_timbri` (`timbri_views.py:53-75`) non ha alcuna guardia di stato: con la specifica in S3 (o superata) il POST fa `spec.timbri_applicati.all().delete()` e ricrea le posizioni — alla prossima rigenerazione il composito ufficiale depositato cambia, senza transizione né audit (`TimbroApplicazione` non produce `EventoSpecifica`). In più il delete-all+ricrea non è transazionale: un errore a metà loop lascia i timbri parziali.

**Raccomandazione:** applicare `_blocca_fuori_stato(request, spec, [C.STATO_FLOW_DOWN])` (o risposta 409 come `mod133_riga_add`) al POST di `applica_timbri`; avvolgere delete+create in `transaction.atomic`; valutare un `EventoSpecifica` trigger `timbri_aggiornati`.

---

### F4 — Data di approvazione "umanizzata" nell'auto-approvazione · Media (compliance) · gestione_specifiche

**Evidenza:** `_auto_approva_se_configurata` (`views.py:417-423`) calcola `data_approvazione` come «primo giorno lavorativo dopo la compilazione, ora casuale in orario ufficio» (`next_business_datetime`) e la scrive su `mod.data_approvazione` — il campo che finisce sul MOD.133/composito ufficiale. L'audit immutabile registra la verità (trigger `auto_approvazione`, `auto=true`, attore reale, timestamp vero), quindi internamente è tracciato; ma il **documento** mostra una data/ora di approvazione fabbricata, in un processo dichiaratamente ISO 9001/EN 9100.

**Raccomandazione:** non è un difetto tecnico (è una decisione, commentata nel codice, con audit fedele a fianco): va **validata formalmente dalla direzione qualità** e messa a verbale, perché in un audit esterno la divergenza documento↔audit interno va spiegata. Alternativa a basso costo: usare il timestamp reale e indicare "approvazione automatica per conto di <MSO>" sul documento.

---

### F5 — Job django-q2: check-then-act + docstring fuorvianti · Bassa · gestione_specifiche

**Evidenza:** `invia_reminder_mod133`/`invia_escalation_mod133` (`scadenze.py:100-153`) leggono `reminder_inviato=False`, inviano email/notifiche e **poi** salvano il flag, senza lock né atomica: due esecuzioni sovrapposte duplicano le notifiche. L'esposizione reale è bassa perché gli schedule sono CRON giornalieri (`automazioni/schedules.py:215-241`: 07:00, 07:15, 06:30) — ma i docstring dei task dichiarano «eseguito ~ogni ora» (`tasks.py:16,22`): se qualcuno "allinea" la cadenza ai docstring, l'esposizione sale. `esegui_verifica_periodica` inoltre notifica → salva → audita senza transazione (notifica inviata anche se il save fallisce, con re-invio al giro successivo).

**Raccomandazione:** claim atomico della riga prima dell'invio (`update(reminder_inviato=True).filter(reminder_inviato=False)` e invio solo se righe toccate = 1), e allineare i docstring alla cadenza reale (o viceversa). Nota: schedule di tipo CRON, quindi il gotcha noto di django-q2 sul tipo "S"(SECONDS) qui non si applica.

---

### F6 — Numerazione OFI e autorizzazione per-modo · Bassa · gestione_specifiche

**Evidenza:** `_prossimo_numero_ofi` (`ofi.py:42-51`) serializza i creatori concorrenti lockando le `AzioneOFI` **esistenti** con `ofi` valorizzato: a tabella vuota (primo OFI in assoluto) non c'è nulla da lockare e due transazioni possono ottenere lo stesso `MAX+1`; non esiste vincolo di unicità su `ofi`. Edge-case una-tantum, mitigato dal fatto che `crea_ofi_da_riga` è `@transaction.atomic` con lock sulla riga. Inoltre `approva_azione_ofi` (`ofi.py:97-128`) verifica l'identità dell'approvatore **solo** nel modo `mod133_approver`; per `car_flow`/`rdd_dedicato` il controllo di ruolo è «demandato all'ACL», ma il binding è per-rotta (`PERM_APPROVA`): chiunque abbia quel permesso decide qualunque azione OFI in quei modi.

**Raccomandazione:** vincolo unique su `AzioneOFI.ofi` (nullable-safe su SQL Server: filtered index non ammesso → tabella contatore o lock su riga sentinella); quando i modi CAR/RDD verranno attivati davvero, aggiungere il controllo di ruolo per-modo (oggi B1/B2 sono dichiaratamente aperti).

---

### F7 — Id utente non validati su assegnazione incaricato · Bassa · gestione_specifiche

**Evidenza:** `nuova_specifica` (`views.py:262-266`) e `admin_specifica_riassegna` (`admin_views.py:122-129`) fanno `incaricato_id = int(post)` se `isdigit()`, senza verificare che l'utente esista né che appartenga a `pool_utenti()`: id inesistente → `IntegrityError` 500 al save; id valido ma fuori pool → assegnazione a chiunque (incoerente con la UI che offre solo il pool).

**Raccomandazione:** validare contro `pool_utenti()` (o almeno `User.objects.filter(pk=..., is_active=True).exists()`) e degradare con messaggio, come già fatto altrove nel modulo.

---

### F8 — Cell editing HTMX senza validazione server-side · **Media** · gestione_carichi_macchina

**Evidenza:** `cella_edit` POST (`views.py:433-510`) persiste con `update(**valori)` / `create(...)` — che **bypassano la validazione del modello** — questi input non validati:

- `turno` (`views.py:442`): nessun confronto con `TURNO_CHOICES` né con `macchina.turni_consentiti()` → si crea un lavoro sul turno notte di una macchina senza notturno (la UI lo impedisce, il server no), o si persiste una stringa arbitraria ≤8 char; `Pianificazione.fasce_di()` ripiega in silenzio sulla fascia G e la cella diventa incoerente tra viste, conflitti e saturazione;
- `stato` (`views.py:486`): non validato contro `STATO_CHOICES` (≤16 char arbitrari) — un valore fuori scala esclude/include silenziosamente il lavoro da `_sovrapposizioni` (che esclude solo `completata`) e dalla colorazione;
- `fase` (`views.py:485`): non validata contro `FASE_CHOICES`.

Contrasto interno: `macchina_config` (`views.py:1238`) valida `stato` contro le choices — il pattern giusto esiste nello stesso file. Il gate ACL è corretto (rotta bound a `piano.edit`, `acl_bootstrap.py:49`), quindi il problema è di **integrità dati**, non di accesso; ma è il percorso di scrittura principale del modulo, richiamabile via POST diretto fuori dalla UI.

**Raccomandazione:** all'ingresso del POST: `turno` in `dict(TURNO_CHOICES)` **e** `macchina.puo_turno(turno)`, `stato` in `dict(STATO_CHOICES)`, `fase` in `dict(FASE_CHOICES)`; risposta 400 sul resto. Stessa guardia su `turno` in `api_sovrapposizione` per coerenza dei responsi.

---

### F9 — Reschedule con delta di calendario su griglia lavorativa · **Media** · gestione_carichi_macchina

**Evidenza:** `reschedule` applica `job.data = job.data + timedelta(days=delta)` (`views.py:973`) mentre **tutte** le viste indicizzano solo lun–ven (`_giorni_lavorativi`, `views.py:100-108`): un lavoro che atterra di sabato/domenica resta nel DB ma **sparisce da Excel e Gantt** (nel Gantt `idx_map.get(p.data) is None → continue`, `views.py:709-711`; nella matrice il lookup è keyed sui soli giorni lavorativi). Con `cascata=1` l'effetto si moltiplica sui successivi. L'unico recupero è l'undo di sessione (`gcm_undo`), che è volatile e per-utente. Il controllo sovrapposizioni pre-spostamento inoltre viene **saltato del tutto** quando `cascata=1` (`views.py:940`, condizione `not forza and not cascata`).

**Raccomandazione:** normalizzare lato server la data risultante al giorno lavorativo più vicino nella direzione dello spostamento (o rifiutare con 400 se cade nel weekend), per la barra primaria e per ogni elemento della cascata; in alternativa, esporre nelle viste anche le date weekend "orfane" con un marker di anomalia.

---

### F10 — Race su reschedule/undo · Bassa · gestione_carichi_macchina

**Evidenza:** in `reschedule` la barra primaria è letta con `get_object_or_404` **fuori** dalla transazione e mai lockata (il `select_for_update` copre solo i successivi in cascata, `views.py:960-964`): due drag concorrenti sulla stessa barra sommano i delta (doppio spostamento). `reschedule_undo` (`views.py:1005-1009`) ripristina lo snapshot di sessione alla cieca con `update()`: sovrascrive modifiche fatte nel frattempo da altri (last-write-wins). `RegistroAzione` traccia tutto, quindi l'accaduto resta ricostruibile.

**Raccomandazione:** rileggere la barra con `select_for_update` dentro la transazione; nell'undo, confrontare lo stato corrente con quello atteso post-spostamento e avvisare in caso di divergenza.

---

### F11 — `update()` bypassa `updated_at`; dedup senza vincolo · Bassa · gestione_carichi_macchina

**Evidenza:** il ramo di modifica di `cella_edit` usa `QuerySet.update(**valori)` (`views.py:495`), che non innesca `auto_now` → `updated_at` resta stantio proprio sul percorso di modifica più usato (il registro azioni compensa solo in parte). Il blocco anti doppio-inserimento (`views.py:503-509`) è un `exists()` check-then-act senza vincolo unique: due submit *davvero* simultanei possono ancora duplicare.

**Raccomandazione:** passare a `save()` sull'istanza (o aggiungere `updated_at=timezone.now()` all'update); per il dedup, valutare un vincolo su (`macchina`, `data`, `turno`, `testo_originale`) — attenzione ai limiti indice su SQL Server con `testo_originale` TEXT: eventualmente hash persistito.

---

### F12 — Importer: dedup Commessa su nome troncato · Bassa · gestione_carichi_macchina

**Evidenza:** l'importer è ben fatto (transazionale con `dry_run` via `set_rollback`, idempotente, rispetta gli edit manuali `fonte != import`, fusione multi-edizione con dedup su (macchina, data, testo)); l'unico punto debole è `Commessa.objects.update_or_create(nome=testo[:200], ...)` (`importer.py:506-509`): due righe di backlog che differiscono oltre il 200° carattere collassano in una, e `report["commesse"]` conta gli update come creazioni.

**Raccomandazione:** chiave di dedup su hash del testo integrale (campo dedicato) e conteggio separato create/update nel report.

---

### F13 — Storico refresh SKM senza attribuzione dell'attore · **Media** · skill matrix

**Evidenza:** `AbilitazioneMacchinaStorico` prevede `car_legacy_id` proprio per tracciare **chi** ha rivalutato, e `applica_refresh`/`aggiungi_abilitazione` lo accettano come parametro — ma la view `skm_refresh` non lo passa mai (`views.py:13544,13552-13553` → `skillmatrix_refresh.py:75,121`: default `car_legacy_id=None`). Risultato: ogni scatto storico del refresh semestrale (conferme, modifiche di livello, rimozioni dalla lista, aggiunte) è **anonimo**. Per un processo qualità MOD.187 l'attribuzione della valutazione è parte del requisito; il resto del portale su operazioni analoghe traccia sempre l'attore (`EventoSpecifica.attore`, `RegistroAzione.utente`).

**Raccomandazione:** nella view risolvere l'identità legacy del richiedente (`get_legacy_user(request.user)`) e passarla come `car_legacy_id` a entrambe le chiamate; valutare anche uno snapshot username in `note` per resilienza (pattern `RegistroAzione`). Effort minimo, il plumbing c'è già.

---

### F14 — Scoping CAR per reparto non enforced · Media · skill matrix

**Evidenza:** il modello dichiara «Merito = SOLO CAR sul proprio reparto» (`models_skillmatrix.py:463`) e la view ammette che «lo scoping per CAR sul proprio reparto è una rifinitura successiva» (`views.py:13512-13513`): oggi chiunque abbia `anagrafica.skillmatrix.manage` può aprire campagne e rivalutare **qualunque** reparto, scegliendolo da un parametro GET/POST libero. Coerente con il gap noto del progetto (scope OWN/TEAM gestito ad-hoc nelle view, non primitiva ACL v2), ma qui tocca valutazioni del personale.

**Raccomandazione:** quando si chiude la rifinitura: risolvere il reparto del CAR dall'anagrafica e vincolare `reparto` a quello (bypass per admin/qualità); nel frattempo il grant `manage` va dato con parsimonia (oggi il bootstrap lo concede anche a tutti i `caporeparto`, `acl_bootstrap.py:43-47`).

---

### F15 — Continuità operativa: regola bloccante non schedulata, stato su marker testuale · Media · skill matrix

**Evidenza:** la sospensione automatica per continuità persa è dichiarata «l'unica regola bloccante della skill matrix» (`skillmatrix_continuita.py:4-6`), ma `applica_sospensioni` gira solo dal management command `skm_continuita_sync`: **nessuno schedule** in `automazioni/schedules.py` (i CRON registrati coprono solo gestione_specifiche e altri moduli). Se nessuno lancia il command, abilitazioni con continuità persa restano attive a tempo indefinito. Inoltre la riattivazione automatica si affida al marcatore testuale `[continuita-persa]` dentro `AbilitazioneMacchina.note` (`skillmatrix_continuita.py:26,54,67`): un edit manuale delle note (campo libero, editabile dal refresh) può rimuovere o introdurre il marker, alterando il comportamento dell'automatismo; gli scatti storico usano `fonte=MANUALE` anche per le azioni automatiche (`skillmatrix_continuita.py:60,77`), sporcando la distinzione manuale/automatico.

**Attenuante:** la sorgente di `ultima_esecuzione` non è ancora cablata (F5 del BUILD_LOG in attesa), quindi oggi la regola è comunque dormiente. Ma va chiusa **insieme** al popolamento, o la feature nascerà spenta.

**Raccomandazione:** registrare lo schedule (CRON giornaliero, tipo "C" — mai "I"/"S" vista la trappola nota di django-q2) nello stesso passo che popola `ultima_esecuzione`; sostituire il marker in `note` con un campo dedicato (`sospesa_per_continuita` boolean) e aggiungere una `fonte` dedicata allo storico (es. `automatico`).

---

### F16 — Robustezza POST refresh · Bassa · skill matrix

**Evidenza:** `applica_refresh` fa `abil.get(int(ab_id))` (`skillmatrix_refresh.py:91`) con `ab_id` estratto dai nomi dei campi POST (`azione_<id>`, `views.py:13540-13543`): un POST malformato (`azione_x=...`) produce `ValueError` → 500. Nessun `select_for_update` sulle abilitazioni: due CAR concorrenti sullo stesso reparto producono doppi scatti storico e last-write-wins sul livello (esposizione bassa: operazione rara e per-reparto). Le validazioni di merito invece ci sono (livello contro `LivelloSkm.choices` sia nel refresh sia nell'aggiunta manuale, con fallback/`ValueError` puliti).

**Raccomandazione:** guardare `int()` con try/except (skip della chiave malformata) e lockare le abilitazioni del reparto nella transazione già presente.

---

## Note positive (postura già corretta, da non regredire)

**Gestione Specifiche**
- FSM con `protected=True`, audit centralizzato nel signal `post_transition` (esattamente un `EventoSpecifica` per transizione, con snapshot metadati) — `state_machine.py`.
- Slot separati `stato_precedente`/`stato_pre_errore`: sospensione ed errore tecnico si annidano (S5→S9→S5) senza calpestarsi; `errore_tecnico` con `source="+"` evita S9→S9.
- Guardie di stato server-side esplicite (`_blocca_fuori_stato`) sulle view di scrittura, con motivazioni nel codice; `mod133_riga_add` risponde 409 fuori da S2.
- Segregazione compilatore≠approvatore enforced **due volte** (guardia FSM in `approva_flow_down` + check in view), preservata anche nell'auto-approvazione.
- API django-ninja con difesa in profondità: whitelist transizioni, permesso ACL **per azione** (`_AZIONE_PERM`) oltre al gate di rotta, SessionAuth+CSRF, JSON 401/403.
- Bootstrap ACL completo: tutte le rotte bound (incluse le 11 admin e l'API nel gate middleware `core/middleware.py:24`).
- Hardening share esemplare (`share_link.py`/`share_write.py`/`composito_deposito.py`): canonicalizzazione lessicale (ADS, spazi/punti finali, `..` varianti Windows) + `realpath`/`commonpath` su percorso E radici, mai overwrite silenzioso, `_SUPERATO` mai destinazione attiva, dry-run di default, rollback completo, audit con sha256.
- `EventoSpecifica` immutabile a livello di modello (update/delete bloccati); form con dedup applicativo (codice, revisione).

**Carichi Macchina**
- Binding ACL con separazione lettura/scrittura pulita (tutte le rotte mutanti sotto `piano.edit`); `_puo_modificare` dichiaratamente solo-UI.
- `RegistroAzione` con snapshot di username/codice macchina (leggibile anche dopo delete); capability turni modellata in un punto solo (`turni_consentiti`).
- Importer transazionale, idempotente, dry-run reale (`set_rollback`), che non sovrascrive gli edit manuali; fusione multi-edizione con dedup.
- Integrazioni KICK-OFF e assenze rigorosamente read-only e fail-safe (mai bloccanti); overlay skill-matrix×assenze additivo.
- Saturazione cache-backed con fallback live (funziona senza cluster q2); 8 file di test.

**Skill Matrix MOD.187**
- Gating in-view con ACL **canonico** (`_check_skm_permission` → `evaluate_permission_code_access`): allineato al middleware e governabile da `/admin-portale/acl-canonico/` — pattern migliore degli helper singleton del resto di anagrafica; binding di rotta completi.
- Modello conforme alle convenzioni (aggancio via `legacy_anagrafica_id` senza FK, vincoli SQL Server rispettati, storico append-only, cella vuota = assenza di record e non "livello 0").
- Baseline gated dalla conferma match F2a (`match_confermato` mai usato come baseline finché non confermato); resolver read-only con query bulk per l'overlay Gantt; livelli sempre validati contro le choices nei service.

---

## Suggerimento di sequenza d'intervento

1. **Quick win (basso effort, chiudono i focus richiesti):** F8 (validazione choices+capability in `cella_edit`), F9 (normalizzazione weekend nel reschedule), F13 (attore nello storico refresh), F3 (guardia di stato sui timbri), F2 (atomicità transizioni: estendere il pattern di `mod133_approva`).
2. **Concorrenza (medio effort):** F1 (`ConcurrentTransitionMixin`/lock sulle transizioni + claim atomico), F10 (lock barra primaria + undo verificato), F16 (guardie e lock nel refresh SKM).
3. **Processo/compliance:** F4 (far validare la data "umanizzata" alla qualità), F14 (scoping CAR per reparto), F15 (schedulare la continuità insieme al popolamento di `ultima_esecuzione`, campo dedicato al posto del marker).
4. **Pulizie:** F5 (docstring/cadenza + claim atomico dei flag), F6 (unique su OFI), F7, F11, F12.

---

*Report di sola analisi. Nessun file di progetto è stato modificato. I rischi di autorizzazione sono descritti a livello di pattern, senza dettagli sfruttabili.*
