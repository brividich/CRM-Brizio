# Audit di NOVICROM HUB — 22/11/2026

Analisi modulo per modulo su sicurezza e flusso/algoritmo. Rilevata sul codice di `main` (`07b18cc67`). Percorsi relativi a `django_app/`. **Nessuna modifica al codice**: questo documento riporta, le correzioni sono proposte in [PROPOSTE_MIGLIORAMENTO_2026-11-22.md](PROPOSTE_MIGLIORAMENTO_2026-11-22.md). Gli algoritmi sono descritti in [ALGORITMI_PORTALE_2026-11-22.md](ALGORITMI_PORTALE_2026-11-22.md) e nei due PDF.

## Come leggere le voci

- **Stato**: `Verificata` = letta direttamente sul codice in questa analisi; `Pista` = emersa dalla mappatura automatica, plausibile ma **non ancora riletta riga per riga**: va confermata prima di intervenire.
- **Gravità**: Alta / Media / Bassa. Nessuna voce è risultata Critica (sfruttabile da anonimi senza alcun segreto).
- Non sono ripetute le voci già chiuse in `AUDIT_SICUREZZA_2026-10-09_STATO.md`; restano aperte da quell'audit: CSP con nonce, eccezioni inghiottite (`except Exception: pass`), `views.py` monolitiche.

## Sintesi

| Area | Alta | Media | Bassa | Piste da confermare |
|---|---|---|---|---|
| Sicurezza | 1 | 6 | 3 | 5 |
| Flusso e algoritmo | 0 | 12 | 8 | 14 |

Le cinque cose da guardare per prime:

1. **Link nella mail delle anomalie** (S1): chi possiede il link decide e carica file senza identificarsi; il segreto è salvato in chiaro.
2. **Doppie mail e decisioni ripetute nel riepilogo anomalie** (A1, A2).
3. **Indice infortuni sottostimato a inizio anno** (G1) ed **eliminazione definitiva delle segnalazioni** (G3).
4. **Avvisi SOC: passaggi di stato senza controllo** e due scale di gravità opposte (C1, C2).
5. **Festivi contati in modo diverso da modulo a modulo** (K1), compreso un termine di legge RENTRI.

---

## 1. Sicurezza

### S1 — Link mail anomalie: autorizzazione al solo possesso del link · Alta · Verificata
- **Dove:** `anomalie/mail_action_views.py:43` (pagina), `:418` (caricamento file), `:707` (riepilogo), `:732` (allegati); `anomalie/mail_action_models.py:11-38`.
- **Fatto:** la pagina è pubblica per scelta dichiarata (`:1-7`, `:120`). Il segreto del link è salvato in chiaro nella tabella (`token`, `:33`), mentre gli altri link del portale salvano solo l'impronta (`automazioni/approval_links.py`). La pagina di riepilogo (`:707`) non controlla né scadenza né revoca. La descrizione del modello (`mail_action_models.py:21`) dice «richiede login», che non è vero.
- **Scenario:** una mail inoltrata, o una lettura della tabella (copia del database, export), consente per 48 ore di approvare, respingere o chiudere anomalie e di caricare file a nome del destinatario; dopo la scadenza il riepilogo resta leggibile.
- **Nota positiva:** l'uso è monouso e atomico (`:228`), gli allegati sono limitati alle anomalie del link (`:759`).
- **Aggiornamento 22/11/2026:** su scelta dell'utente il link resta senza login. Corretto: nel database solo l'impronta del segreto (`anomalie 0032`), scadenza e revoca anche sul riepilogo, revoca dei link superati da una mail nuova, limite ai link inesistenti per indirizzo IP, descrizione del modello. La durata è passata a una settimana per scelta dell'utente. Non fatti, per scelta: ricevuta al destinatario dopo la decisione, restrizioni sul caricamento dei file.

### S2 — Reindirizzamento non controllato · Media · Verificata
- **Dove:** `tasks/views/spostamenti.py:35,38`; `core/views.py:1101-1116` (fine impersonazione).
- **Fatto:** il parametro `next` della richiesta viene passato a `redirect` senza verifica. Altrove il portale usa già `url_has_allowed_host_and_scheme` e gli helper `_safe_redirect_url` / `back_sicuro` / `safe_next`.
- **Scenario:** un modulo preparato su un sito esterno porta l'utente, dopo l'azione, su una pagina che imita il portale.

### S3 — Download del pacchetto di release con percorso libero · Media · Verificata
- **Dove:** `admin_portale/views/release.py:357-369`.
- **Fatto:** il percorso arriva dalla query string; i soli controlli sono estensione `.zip` e nome che inizia per `portale-novicrom-`. Riservata agli amministratori.
- **Scenario:** un amministratore (o chi ne ha la sessione) scarica qualsiasi zip con quel prefisso da qualsiasi cartella o share raggiungibile dal servizio.

### S4 — Mail delle automazioni: valori inseriti nell'HTML senza neutralizzazione · Media · Verificata
- **Dove:** `automazioni/services.py:1585-1604` (`render_template_string`), `:4545`, `:4592`.
- **Fatto:** i segnaposto del modello sono sostituiti con i valori dell'evento così come sono; il risultato è dichiarato sicuro (`mark_safe`) e inserito nel layout della mail.
- **Scenario:** un testo libero scritto da un utente (descrizione, nota) che contiene HTML finisce nella mail come HTML: link ingannevoli o contenuto alterato in una mail che parte dall'indirizzo aziendale.

### S5 — Amministrazione di Gestione specifiche protetta solo dal controllo generale · Media · Verificata
- **Dove:** `gestione_specifiche/admin_views.py:43-255`; legami in `gestione_specifiche/acl_bootstrap.py:86-97`; rotte in `gestione_specifiche/urls.py:45-56`.
- **Fatto:** tutte le viste di amministrazione hanno solo `@login_required`; `utente_puo_admin` (`:26`) serve solo a mostrare il link. La protezione dipende interamente dal legame pagina-permesso nel database. La rotta `admin_sincronizzazione` (`urls.py:52`) **non ha legame canonico**. Il caricamento del timbro (`:152`) non passa dal validatore centrale `core/upload_mime.py`.
- **Scenario:** se un legame manca o viene tolto dalla matrice, la pagina resta affidata al vecchio sistema a pulsanti; un file di tipo inatteso può essere caricato come timbro.

### S6 — Conferma «ho letto tutte le schede» con una semplice apertura di pagina · Media · Verificata
- **Dove:** `schede_sicurezza/views.py:682-706`.
- **Fatto:** la presa visione di tutte le schede di sicurezza viene registrata su una richiesta GET (scelta voluta per il link nella mail).
- **Scenario:** l'anteprima automatica dei link di un client di posta o un'immagine in una pagina fanno registrare la presa visione senza che la persona abbia letto. La presa visione è una prova ai fini della sicurezza sul lavoro.

### S7 — Blocco del vecchio sistema permessi spento per impostazione predefinita · Media · Verificata (codice), da verificare il valore in produzione
- **Dove:** `config/settings/base.py:188` (`ACL_STRICT_CANONICAL` = False), `core/middleware.py:488-517`.
- **Fatto:** una pagina senza legame canonico viene decisa dal vecchio sistema. Con un `.env` incompleto il blocco resta spento senza alcun avviso.
- **Da fare:** leggere il valore effettivo in produzione; se è già attivo, la voce si riduce a rendere il default sicuro in `prod.py`.

### S8 — SOC: 125 rotte su 174 senza protezione dichiarata sulla rotta · Media · Pista
- **Dove:** `security/urls_hub.py` (174 `path`, 49 `_guard`: conteggio verificato).
- **Fatto:** per le altre il permesso è controllato dentro la vista e dal controllo generale. Non è stato verificato vista per vista.
- **Da fare:** un test automatico che apra ogni rotta SOC con un utente senza permesso e pretenda il rifiuto.

### S9 — Verifica dell'onboarding che lascia passare in caso di errore · Bassa · Verificata
- **Dove:** `core/middleware.py:447-460`. Se la lettura fallisce l'accesso non viene bloccato (scelta dichiarata, con traccia nei log). Il controllo dei permessi che segue resta attivo.

### S10 — Pagine pubbliche raggiungibili dal solo codice QR · Bassa · Verificata (SDS), Pista (asset)
- **Dove:** `schede_sicurezza/views.py:527-616` (scelta dichiarata, pagina senza dati personali); `assets/views/qr_labels.py:448` (QR asset senza scadenza: da verificare cosa espone).

### S11 — Documentazione tecnica non allineata · Bassa · Verificata in parte
- `anomalie/mail_action_models.py:21` (vedi S1). **Pista:** `docs/ai/02_ARCHITECTURE.md:99-112` riporta un elenco vecchio delle pagine esenti e un meccanismo di identità che `05_SECURITY_BOUNDARIES.md` vieta.

### Altre piste di sicurezza (da confermare)
- **Caricamenti che non usano il validatore centrale:** `security/views_backup.py:120`, `admin_portale/views_sapere.py:63`, `procedure_refresh/views_modifiche.py:266`, `sistema_gestione/esterni_views.py:136,257`, `attrezzature/views.py:290`, `assets/views/layout.py:530`.
- **Cartella di rete libera** in `gestione_specifiche/admin_views.py:183-213` (campo `cartella` salvato senza controllo sul percorso).
- **CSP con `'unsafe-inline'`** (`config/settings/base.py:263-292`): aperta dall'audit di ottobre.
- **`AdaptiveSecureCookieMiddleware`** (`core/middleware.py:335`): toglie il flag Secure sulle richieste in HTTP.
- **32 `execute(f"…")`**: già censite e governate da `core/test_sql_census.py`; nessuna nuova.

**Corretto rispetto alla mappatura:** il limite di dimensione dei caricamenti esiste (`UPLOAD_MAX_FILE_MB` = 100, `config/settings/base.py:213`).

---

## 2. Flusso e algoritmo — moduli prioritari

### SOC (`security`)
- **C1 · Media · Verificata — Passaggi di stato senza controllo né blocco.** `security/services/alert_lifecycle.py:136-180`: `_transition_alert` scrive il nuovo stato senza verificare che il passaggio sia ammesso e senza bloccare la riga. Due operatori che agiscono insieme si sovrascrivono; un avviso chiuso può tornare «in lavorazione» senza passare dalla riapertura.
- **C2 · Media · Verificata — Due scale di gravità opposte.** `security/services/rule_engine.py:1132`: «attenzione» vale meno di «medio»; `security/services/posture.py:36-42`: «attenzione» pesa 8, «medio» 5. L'ordinamento degli avvisi e il voto di postura danno priorità diverse allo stesso avviso.
- **C3 · Media · Verificata in parte — Due motori di postura.** `posture.py` (azienda) e `postura.py` (PC) hanno pesi e fasce propri (90/75/50 contro 80/50): i due voti non sono confrontabili e ogni modifica va fatta due volte.
- **Piste:** regole di soppressione rilette per ogni evento (`_matching_suppression`), ciclo di valutazione senza limite, eccezioni inghiottite in `overview.py:108,138,153`, `defender_alerts.py:103`, `event_triage.py:461`.

### Contatori SNMP (`contatori`)
- **N1 · Bassa · Verificata — Riconciliazione lenta.** `contatori/services.py:143-147`: per ogni riga di fattura una query sulle macchine e una sulle letture. Con molti contratti la pagina rallenta.
- **Piste:** `interroga_dispositivo` di circa 270 righe; eccezioni inghiottite in `snmp.py:551`, `tabella_mac.py:159,203,253`.
- **Punti solidi:** blocco per apparato, verifica della lettura, salvataggio trimestrale con blocco sulla riga.

### Diario del preposto (`diario_preposto`)
- **D1 · Bassa · Verificata — «In ritardo» calcolato in UTC.** `diario_preposto/cruscotto.py:83-84`: usa `creata.date()` e non l'ora italiana (la funzione `_locale` esiste alla riga 26 ma qui non è usata). Un'annotazione inserita fra mezzanotte e l'una/le due può risultare di un giorno prima.
- **Piste:** `ripristina` senza filtro di visibilità (`views.py:782`), `rimanda_scheda` con controllo fatto a mano (`views.py:727`).

### Segnalazioni di sicurezza (`rilevazione_incidenti`)
- **G1 · Media · Verificata — Indice infortuni sottostimato in corso d'anno.** `rilevazione_incidenti/services.py:51-72`: gli incidenti da inizio anno sono divisi per le ore di un anno intero (organico × 2.000). A giugno l'indice vale circa la metà del reale.
- **G2 · Media · Verificata — Organico a zero in silenzio.** `:23-27`: se l'anagrafica non risponde l'organico vale 0, l'indice diventa vuoto e nessuno viene avvisato.
- **G3 · Media · Verificata — Eliminazione definitiva.** `rilevazione_incidenti/views.py:1080-1104`: la segnalazione viene cancellata; resta solo una riga nel registro azioni con l'identificativo. Il diario del preposto, per lo stesso tipo di dato, archivia con motivo e consente il ripristino.
- **Piste:** elenco locale con una query per riga (`views.py:595`), doppia sorgente dati (SharePoint / locale) da mantenere allineata.

### Schede di sicurezza (`schede_sicurezza`)
- **H1 · Media · Verificata — «Da rivedere» calcolato dalla data di caricamento.** `schede_sicurezza/models.py:193-198`: i 1.095 giorni partono da quando il PDF è stato caricato, non dalla data di revisione del fornitore. Una scheda vecchia di cinque anni caricata oggi risulta in regola per tre anni.
- **H2 · Bassa · Verificata — Cambio di versione corrente non protetto.** `:185-190`: togliere il segno alle altre versioni e salvare la nuova sono due operazioni separate, senza transazione. Due caricamenti insieme possono lasciare due versioni correnti.
- **Piste:** estrazione del PDF dentro la richiesta (`views.py:387`), una query per mansione nel report di presa visione (`reports.py:49`).

### Gestione anomalie (`anomalie`)
- **A1 · Media · Verificata — Doppia mail di riepilogo.** `anomalie/mail_action_service.py:866-949`: l'elenco delle notifiche in attesa è letto senza blocco. «Invia ora» e il controllo automatico (ogni minuto) possono inviare lo stesso riepilogo due volte.
- **A2 · Media · Verificata sul codice, da confermare con un test — Decisioni già inviate ripetute.** `:833-845` e `:939-941`: dopo l'invio l'elenco delle decisioni (`updates_snapshot`) non viene svuotato; la decisione successiva sullo stesso ordine si aggiunge alle vecchie e il riepilogo le ripropone tutte.
- **A3 · Media · Verificata — Decisione registrata durante l'invio.** Se una decisione arriva mentre la mail sta partendo, il segno «notificato» scritto a fine invio (`:939`) copre il nuovo «da notificare» (`:843`): quella decisione parte solo alla modifica successiva.
- **A4 · Bassa · Verificata — Stati come testo libero.** `mail_action_views.py:34-38` scrive «Finito trattato», mentre la mappatura riporta «Chiusa» in altre parti (`views.py:4905`): gli stati vanno ricondotti a un elenco unico.
- **Piste:** ricerca delle ricorrenze senza limite (`automazioni_service.py:169`), 37 eccezioni inghiottite, `views.py` di 7.500 righe.

### Calendari (scadenze, assenze, manutenzione, attività, audit)
- **K1 · Media · Verificata — Festivi contati in modo diverso.** Calcolo comune in `core/calendario_it.py:25-65`, usato da anomalie (`tempi_service.py:82`), attività (`tasks/services/calendar_it.py:6`), specifiche (`gestione_specifiche/date_utils.py:14`). Riscritto in `assenze/hr.py:43-58` e `scadenzario/calendario.py:29-63` (questi due aggiungono il santo patrono). **Ignorati** in `gestione_carichi_macchina/saturazione.py:15` (e in altri otto punti del modulo) e in `rentri/verifica.py:52-62`.
- **K2 · Media · Verificata — Termine RENTRI senza festivi.** `rentri/verifica.py:52-62`: i 10 giorni lavorativi per l'annotazione escludono solo sabato e domenica. Con una festa in mezzo il portale segnala un ritardo che non c'è.
- **K3 · Bassa · Verificata — Capacità delle macchine sovrastimata nelle settimane con festa.** `gestione_carichi_macchina/saturazione.py:15-19`.
- **Piste:** una query per scadenza negli avvisi (`scadenzario/avvisi.py:124,264`); santo patrono presente solo in due calendari su cinque.
- **Punti solidi:** allineamento Outlook prudente (non ricrea ciò che l'utente ha cancellato, non cancella su elenco incompleto).

---

## 3. Flusso e algoritmo — altri moduli

- **R1 · Media · Verificata — Report pianificati rispediti.** `core/report_centro/pianificazione.py:290-312`: la prossima data è salvata solo dopo l'invio e senza blocco. Se l'esecuzione solleva un errore la data non avanza e il report viene ritentato ogni ora; due processi insieme lo spediscono due volte.
- **R2 · Media · Verificata — Promemoria di presa visione solo nel giorno esatto.** `procedure_refresh/tasks.py:231-235`: parte solo se i giorni mancanti sono esattamente 7 o 2. Se quel giorno il controllo non gira (server fermo, errore), il promemoria è perso.
- **R3 · Bassa · Verificata — Motore delle automazioni in un file solo.** `automazioni/services.py`, oltre 6.000 righe: ogni modifica tocca lo stesso file, con più rischio di conflitti fra sessioni.
- **Piste da confermare:**
  - Ticket: promemoria SLA giornaliero senza memoria di quelli già inviati; tempo contato a orologio continuo; una query per ogni proprietà SLA letta (`tickets/models.py:345`).
  - Numeratori senza ritentativo: `anagrafica/services/mpq_utensili.py:22`, `sistema_gestione/services/audit.py:171`.
  - DPI e ticket ordinano il numero come testo: oltre 9.999 l'ordine si rompe.
  - Assenze: riconciliazione con le presenze per nome (`assenze/riconciliazione.py:64`); elenco richieste vuoto su errore senza avviso.
  - DPI: elenco approvatori parziale su errore (`dpi/flusso.py:99`).
  - KICK-OFF: `docs/ai/03_BACKEND_MODULES.md:117` riporta soglie diverse dal codice (`tasks/vrf_catalog.py:58-59`).
  - Assistente AI: limite di 3 richieste per processo e non in totale; default diversi per la stessa impostazione (`ai_assistant/services.py:304` contro `:634`, `:1048`).
  - Automazioni: una pausa scritta male lascia passare la regola (`automazioni/services.py:1913`).
  - Carichi macchina, presenti, reception, sistema di gestione: nessuna criticità emersa oltre a K3.

## 4. Punti solidi rilevati

- Controllo accessi centralizzato con risposta JSON 401/403 per le API (`core/middleware.py:418-432`, `:552`).
- Link di approvazione con sola impronta a database e uso atomico (`automazioni/approval_links.py`).
- Avvisi SOC senza doppioni garantiti dal database; vulnerabilità trattate «a favore di sicurezza».
- Timeout presenti su tutte le integrazioni controllate (SNMP, Graph, LDAP, SMTP, assistente AI).
- Registro azioni con sigillo mensile a catena.
- Produzione che rifiuta di partire con chiave segreta di esempio o controlli accessi spenti (`config/settings/prod.py:9,74`).
