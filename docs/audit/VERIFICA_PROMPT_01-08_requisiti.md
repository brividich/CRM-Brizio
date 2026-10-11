# Verifica prompt 01–08 — Contratto dei requisiti

Data: 2026-10-11. Fonte: `md upgrade moduli/01…08_*.md` (shared checkout, file del 09/10/2026).
Riferimenti congelati per la verifica: `origin/main` = `1f2c73c2`, `origin/release/prod` = `bc51d009`.

Ogni requisito ha un ID stabile. Le regole comuni (`REG-*`) e le condizioni di stop (`STOP-*`) si ripetono per prompt perché ognuna va verificata sul lavoro di quel prompt.

## Regole comuni (applicate a ogni prompt Pnn)

| ID | Requisito verificabile |
| --- | --- |
| Pnn-REG-WT | Branch creato da `origin/release/prod` con il nome atteso dal prompt |
| Pnn-REG-ACL | Ogni route nuova ha binding ACL v2 canonico e controllo server-side |
| Pnn-REG-JSON | Endpoint AJAX/HTMX nuovi rispondono JSON 401/403, non redirect HTML |
| Pnn-REG-UPLOAD | Upload nuovi/toccati passano da `validate_extension_and_mime` con limiti, mai serviti inline come HTML/SVG |
| Pnn-REG-SAFE | Nessun `|safe` / `mark_safe` nuovo su dati utente |
| Pnn-REG-EXC | Nessun `except Exception: pass/continue` nuovo senza log |
| Pnn-REG-MIG | Migrazioni reversibili, SQL Server-safe, `makemigrations --check` pulito, numeri non in collisione |
| Pnn-REG-DOC | `CHANGELOG.md` `[Unreleased]` con file e descrizione + `docs/moduli/<app>.md` aggiornato |
| Pnn-REG-BUMP | Checklist version bump se il comportamento visibile cambia |
| Pnn-REG-VIEWS | (03, 04, 05, 06) codice nuovo fuori da `anagrafica/views.py` / `assets/views.py` |
| Pnn-REG-GIT | Solo file propri, commit su branch feature, nessun merge/push su release/prod dalla sessione |

## P01 — Contatori/SNMP

| ID | Requisito |
| --- | --- |
| P01-A1 | Bug fattura riprodotto (test rosso su `fattura_import.py` / `views.fattura_edit`) |
| P01-A2 | Test formati: PDF testuale, PDF scansionato (errore chiaro), XML FatturaPA, `.p7m`, file vuoto/corrotto, numeri `1.234,56`, date `gg/mm/aaaa`, più righe stessa macchina, duplicato |
| P01-A3 | `FatturaNonLeggibile` dice cosa manca (numero, data, righe) e cosa fare |
| P01-A4 | Anteprima prima del salvataggio con righe assegnate/non assegnate da associare a mano; niente salvataggio parziale silenzioso |
| P01-A5 | Duplicati per numero + fornitore + data con avviso esplicito |
| P01-A6 | XML su `defusedxml`; PyMuPDF con limite pagine e dimensione |
| P01-B1 | Difetto andamento reparti riprodotto |
| P01-B2 | Test numerici: delta consecutivi |
| P01-B3 | Test: reset/sostituzione contatore (delta negativo segnalato, non sottratto) |
| P01-B4 | Test: macchina spostata di reparto attribuita con lo storico |
| P01-B5 | Test: letture mancanti (interpolazione o buco dichiarato, mai zero silenzioso) |
| P01-B6 | Test: macchine disattivate |
| P01-B7 | Test: trimestri a cavallo d'anno |
| P01-B8 | Grafico dichiara periodo, unità, fonte; totale grafico = export xlsx (test) |
| P01-B9 | Niente N+1, `assertNumQueries` |
| P01-C1 | Dashboard: stato flotta (OK/attenzione/errore/non interrogata da N giorni) |
| P01-C2 | Dashboard: consumabili sotto soglia |
| P01-C3 | Dashboard: letture proposte da confermare |
| P01-C4 | Dashboard: fatture da riconciliare |
| P01-C5 | Dashboard: ultimi errori con causa |
| P01-C6 | Ogni riquadro porta alla lista già filtrata |
| P01-C7 | Menu raggruppato Operatività / Economico / Configurazione (Configurazione solo con permesso gestione) |
| P01-C8 | Dettaglio dispositivo con sezione Info completa (modello, IP, versione SNMP, profilo, ultima lettura ok/ko con motivo, asset, reparto, storico) |
| P01-D1 | Un solo motore di wizard riusabile (HTMX, stato server-side, avanti/indietro senza perdita) |
| P01-D2 | Wizard dispositivo step 1: tipo/modello con preset o generico |
| P01-D3 | Step 2: IP/hostname validato, porta 161, v2c/v3 |
| P01-D4 | Step 3: community da `CommunitySNMP` cifrata o utente v3 |
| P01-D5 | Default hardcoded `novicromprinter` rimosso da `models.py` e `snmp.py` |
| P01-D6 | Step 4: test connessione obbligatorio (sysDescr/sysObjectID, timeout 3 s, 1 retry, fuori transazione, autodetect profilo) |
| P01-D7 | Step 5: mappatura contatori con valori letti e OID non rispondenti evidenziati |
| P01-D8 | Step 6: associazione asset/reparto con ricerca, niente id a mano |
| P01-D9 | Step 7: riepilogo e conferma; bozza solo esplicita con stato "non verificato" visibile ovunque |
| P01-E1..E6 | Catalogo errori `contatori/errori_snmp.py`: SNMP-001 IP non valido, 002 DNS, 003 timeout, 004 v3 auth/unknownUser, 005 noSuchObject, 006 valore non valido |
| P01-E7 | Catalogo usato da wizard, dashboard e job notturni |
| P01-D10 | Stessa logica per wizard macchina, profilo, colonna profilo, sonda (validazione server-side per step) |
| P01-D11 | Test: ogni step, ogni codice d'errore (SNMP mockato), completamento bloccato senza test, bozza |
| P01-STOP-1 | Bug non riproducibile (fattura, andamento): chiesto il file/errore invece di indovinare |
| P01-STOP-3 | Lavoro oltre ~1.500 righe nette: proposto split |

## P02 — SOC automatismi e CVE

| ID | Requisito |
| --- | --- |
| P02-A1 | Fingerprint stabile (sorgente + event_type + chiave dedup normalizzata), documentato per tipo |
| P02-A2 | "Disattivazione" = chiusura manuale FP / non rilevante / accettato / mute con motivo obbligatorio; chiusure automatiche e rientri non contano |
| P02-A3 | Alla 3ª disattivazione nella finestra: regola `owner="system:learned"`, scope esatto, reason con le 3 disattivazioni, `expires_at` 180 gg configurabile |
| P02-A4 | Creazione scritta in `SecurityConfigurationAuditLog` e notificata al canale SOC |
| P02-A5 | Dalla 4ª: nessun alert, `SecurityEventRecord` con `decision_trace`, `hit_count`/`last_hit_at`, visibile in "Eventi soppressi" |
| P02-A6 | Guardrail: mai per critical, KEV, minacce/malware, ransomware |
| P02-A7 | Guardrail: severità in salita → alert nasce comunque |
| P02-A8 | Guardrail: riapertura manuale disattiva la regola e azzera il conteggio |
| P02-A9 | Pagina "Soppressioni": filtro apprese/manuali, revoca con motivo, scadenze imminenti, hit |
| P02-A10 | Badge "2/3 disattivazioni" sull'alert |
| P02-A11 | Impostazioni in `SecurityCenterSetting`: soglia, finestra, durata, severità escluse, tipi esclusi, on/off |
| P02-B1 | Registro regole di rientro (condizione, prova, azione); regole esistenti migrate senza cambiare comportamento, test esistenti verdi |
| P02-B2 | Nuove regole: VPN nei limiti N giorni, heartbeat ok, CVE con patch da inventario |
| P02-B3 | Risoluzione automatica scrive `status_reason` con riferimento prova + voce timeline; caso chiuso solo senza attività aperte |
| P02-B4 | Simulazione ultimi 30 giorni (riusa `rule_simulation.py`) prima di attivare |
| P02-C1 | Import inventario CSV/XLSX con wizard mappatura colonne e preset per fonte |
| P02-C2 | Anteprima, righe scartate con motivo, import idempotente |
| P02-C3 | Modelli `SoftwareInventoryImport` / `SoftwareInstallation` con campi richiesti; non più viste marcate, non cancellate |
| P02-C4 | Tabella alias vendor/prodotto modificabile da UI |
| P02-C5 | Mappatura CPE con suggerimenti dal dizionario NVD e conferma manuale |
| P02-C6 | Job django-q NVD CVE API 2.0 con range versioni |
| P02-C7 | CISA KEV; EPSS opzionale |
| P02-C8 | Cache con TTL su tabella dedicata; API key cifrata in `SecurityCenterSetting` |
| P02-C9 | Chiamate esterne con timeout, retry/backoff, rate limit, in django-q, fuori da `atomic` |
| P02-C10 | Matching IMPATTA / NON IMPATTA / DA VERIFICARE con spiegazione leggibile |
| P02-C11 | Confronto versioni `packaging.version` + fallback per segmenti, test su `10.0.19045.4651`, `23.01`, `2.4.1-beta` |
| P02-C12 | Sezione "Impatto sugli asset" su finding e alert CVE |
| P02-C13 | CVE con zero IMPATTA proposta per chiusura, mai chiusa da sola se KEV/critica |
| P02-C14 | Sezione "Vulnerabilità" sulla pagina asset HUB |
| P02-C15 | Dashboard: CVE che impattano ordinate KEV→CVSS/EPSS→n. asset; asset più esposti; software senza CPE |
| P02-C16 | Test con NVD/KEV mockati, nessuna rete nei test; rate limit testato |
| P02-STOP-1 | Formato export WatchGuard/BusinessLog non disponibile: mappatura configurabile, nessun parser rigido |
| P02-STOP-2 | Regola che potrebbe chiudere/sopprimere alert critici: chiesto |

## P03 — Anagrafica elenco / creazione / admin

| ID | Requisito |
| --- | --- |
| P03-A1 | Registro colonne `services/colonne_elenco.py` con default identico all'attuale |
| P03-A2 | Ogni voce dichiara chiave, etichetta, accessor, ordinabile, filtrabile, esportabile, permesso, `sensibile`; nessun `getattr` su stringhe utente |
| P03-A3 | Modelli `VistaElenco` e `PreferenzaVistaUtente` |
| P03-A4 | Pannello admin "Viste elenco" (drag&drop, visibilità, larghezza, anteprima live, duplica, ripristina, elimina con conferma, badge sensibile) |
| P03-A5 | Preset ISO 9001 / ISO 45001 / HR / Sicurezza / Altro con migrazione dati reversibile |
| P03-A6 | Elenco: selettore vista, ordinamento/filtri per colonna, preferenze per utente |
| P03-A7 | Export xlsx che rispetta vista e permessi, con protezione formule |
| P03-A8 | Permesso colonna verificato in elenco, ordinamento, filtro ed export (anche via querystring) |
| P03-A9 | `assertNumQueries` 200 dipendenti × 25 colonne costante |
| P03-B1 | Creazione dipendente a step (anagrafica → organizzazione → account → riepilogo) |
| P03-B2 | Ricerca utente portale esistente per email/CF con proposta di collegamento |
| P03-B3 | Ricerca LDAP sola lettura (email, UPN, nome) con gruppi e stato; scelte AD / locale / nessuno |
| P03-B4 | Collegamento AD solo per UPN/email esatti |
| P03-B5 | Mai collegare superuser/staff/password utilizzabile senza conferma superuser |
| P03-B6 | Account fuori `LDAP_GROUP_ALLOWLIST` → avviso bloccante |
| P03-B7 | Ogni collegamento/creazione in `core.audit.log_action` |
| P03-B8 | Errori LDAP spiegati (timeout `receive_timeout`, ambiguo, disabilitato); dipendente creato comunque |
| P03-B9 | Il portale non crea/modifica account AD |
| P03-B10 | Test LDAP mockato per ogni caso; creazione idempotente |
| P03-C1 | Censimento route admin/import → tabella |
| P03-C2 | Ogni import nella pagina della sua entità (pannello HTMX), permesso import server-side |
| P03-C3 | Hub "Amministrazione anagrafica" a schede |
| P03-C4 | Storico import centralizzato con scarico dello scarto |
| P03-C5 | Vecchi URL → 301; `tests_subnav_acl.py` verde |
| P03-D1 | Subnav "Salute e sicurezza" in gruppi con conteggi scadenze |
| P03-D2 | Voci rispettano ACL e cancelli in-view |
| P03-D3 | Evidenziazione voce corrente nelle sottopagine |

## P04 — Mansioni di rischio / cambio mansione

| ID | Requisito |
| --- | --- |
| P04-A1 | `Mansione` lavorativa ripulita (profilo di rischio deprecato, non rimosso) |
| P04-A2 | Modello `MansioneRischio` con fattori, visite con periodicità, categorie DPI, regole formative, livello, riferimento DVR (revisione, data) |
| P04-A3 | M2M lavorativa↔rischio con ordine e note |
| P04-A4 | Override individuali (aggiunta/esclusione motivata, data, autore) |
| P04-A5 | `mansionario.requisiti_dipendente` dall'unione effettiva con provenienza; test esistenti verdi o adeguati |
| P04-A6 | Organigramma a doppio livello, filtro per fattore, export RSPP/medico |
| P04-A7 | CRUD admin con lavorative collegate, dipendenti esposti e anteprima effetto ("N visite, M corsi") |
| P04-B1 | Cambio robusto su: cambio mansione lavorativa |
| P04-B2 | … cambio reparto/area che implica altra mansione |
| P04-B3 | … modifica collegamento da admin con job in background e report |
| P04-B4 | … override aggiunto/tolto |
| P04-B5 | … cambio futuro, retroattivo, annullamento (adempimenti annullati con motivo, non cancellati) |
| P04-B6 | Delta requisiti (visite, formazione, DPI): solo mancanti, "non più dovuto", nessun duplicato |
| P04-B7 | Idempotente e transazionale; notifiche `transaction.on_commit` |
| P04-B8 | Visita cambio mansione (art. 41 c.2 d) con scadenza entro decorrenza; stato "Non idoneo a operare: visita mancante" su scheda, scadenzario, dashboard HR, organigramma |
| P04-B9 | Periodicità ricalcolata al cambio protocollo |
| P04-B10 | Visita chiude l'adempimento solo se il tipo copre il requisito |
| P04-B11 | Idoneità con prescrizioni mostrata nel contesto della nuova mansione |
| P04-B12 | Non idoneità blocca lo stato operativo |
| P04-B13 | Controllo integrità notturno esteso (requisiti senza adempimento, orfani, visite scadute, cambi senza piano) con report in monitoring e link |
| P04-B14 | Audit trail in timeline dipendente (generazione, chiusura, annullamento, deroga) |
| P04-T1..T11 | Casi test: cambio semplice; rischi in più/meno; programmato poi annullato; retroattivo; modifica collegamento su 50 dipendenti (job); doppia esecuzione; visita tipo sbagliato; non idoneità; deroga; utente senza permesso sanitario; referto HTML/SVG come allegato |
| P04-MIG1 | Migrazione dati reversibile, idempotente, con report mappati/non mappati, testata con dati sintetici |
| P04-MIG2 | Nessun campo vecchio rimosso |
| P04-SEC1 | Dati sanitari solo con permesso visite/sorveglianza server-side, esclusi da export non autorizzati |
| P04-SEC2 | Nessun dato sanitario in log, email, titoli alert |
| P04-SEC3 | A8: download referti con sniff server-side, inline solo PDF/PNG/JPEG, `as_attachment` per il resto, CSP sandbox, `validate_extension_and_mime` in `_salva_referto_visita` |
| P04-STOP-1 | Schema e migrazione mostrati a Brizio PRIMA di scrivere migrazioni |
| P04-STOP-2 | Requisiti normativi ambigui resi configurabili e chiesti |

## P05 — E-learning

| ID | Requisito |
| --- | --- |
| P05-A1 | Home "La mia formazione" (scadenza, stato, %, tempo residuo, obbligatori in evidenza, attestati scaricabili) |
| P05-A2 | Player per moduli e lezioni; slide, PDF incorporato sicuro, video |
| P05-A3 | Ripresa dal punto lasciato; avanzamento salvato a ogni passo |
| P05-A4 | Player mobile |
| P05-A5 | Banca domande con estrazione casuale e ordine risposte casuale |
| P05-A6 | Soglia, tentativi massimi, attesa tra tentativi configurabili |
| P05-A7 | Feedback senza svelare risposte se restano tentativi |
| P05-A8 | Domande singola, multipla, vero/falso |
| P05-A9 | Attestato automatico con protocollo e verifica QR/codice; pagina pubblica minima (nessun dato oltre al nome) |
| P05-A10 | Questionario di gradimento collegato a `TrainingEfficacia` |
| P05-B1 | Import slide PPTX/PDF e markdown |
| P05-B2 | Editor domande con import Excel |
| P05-B3 | Versioni corso: modifica di un pubblicato crea nuova versione; completamenti v1 restano validi secondo regole |
| P05-B4 | Assegnazioni automatiche da mansione di rischio, lavorativa, reparto, onboarding |
| P05-B5 | Assegnazioni manuali persone/gruppi con scadenza |
| P05-B6 | Riassegnazione automatica alla scadenza |
| P05-B7 | Scaletta promemoria configurabile, solleciti al responsabile, digest settimanale, nessuna email duplicata |
| P05-C1 | Cruscotto: copertura per reparto e mansione, in scadenza/scaduti |
| P05-C2 | Completamenti nel tempo, ore erogate, punteggi medi, domande più sbagliate |
| P05-C3 | Tempo medio di completamento |
| P05-C4 | Drill-down fino alla persona; export xlsx e PDF con data e filtri |
| P05-C5 | Registro immutabile (chi, versione, quando, tempo, tentativi, punteggio, IP/dispositivo se configurato); rettifiche tracciate |
| P05-INT1 | Completamento valido solo con regole verificate lato server |
| P05-INT2 | Tempo da heartbeat server-side con throttle ≥ 30 s e pause per inattività |
| P05-INT3 | Record e attestato una sola volta; alimenta scadenze e requisiti |
| P05-SEC1 | Discente vede solo i propri corsi; HR per `AnagraficaFormazionePermission` |
| P05-SEC2 | Risposte corrette mai al browser prima della consegna |
| P05-SEC3 | Markdown sanificato con `nh3`; contenuti su storage privato |
| P05-STOP-1 | Piano MVP mostrato e OK atteso prima dell'implementazione |
| P05-STOP-2 | Regole FAD non codificate a memoria (configurabili) |
| P05-STOP-3 | SCORM non implementato senza conferma |

## P06 — Asset

| ID | Requisito |
| --- | --- |
| P06-A1 | QR in testata dettaglio; clic → anteprima grande, link copiabile, stampa etichetta, PNG |
| P06-A2 | Colonna QR facoltativa nell'elenco + stampa etichette multipla |
| P06-A3 | Stesso componente (include + view unica) nelle pagine IT e officina |
| P06-A4 | Cache immagini QR con chiave asset+destinazione+versione, invalidata al cambio tag/token |
| P06-A5 | Test: destinazione giusta, nessun token pubblico implicito, permessi |
| P06-SEC1 | Nessun token QR pubblico generato implicitamente (B3) |
| P06-SEC2 | QR generato server-side, mai SVG caricati |
| P06-SEC3 | Download allegati OdL (`assets/views.py:2630-2665`) allineato a `_can_download_asset_document` |
| P06-SEC4 | SVG/HTML rimossi dagli upload immagini; `validate_extension_and_mime` su tutti gli upload del modulo |
| P06-B1 | Pagina asset MFC mostra in automatico dai dati a DB: consumabili con data, stima esaurimento, pagine per periodo B/N/colore con trend, ultimi errori SNMP, link Contatori |
| P06-B2 | Asset MFC non collegato reso visibile + azione "collega" con permesso |
| P06-B3 | "Leggi adesso" asincrono (job) con stato, solo con permesso |
| P06-B4 | Lettura vecchia oltre N giorni segnalata |
| P06-B5 | Test: stima/trend, asset senza letture, lettura vecchia, nessuna chiamata SNMP nella request |
| P06-C1 | Modello di storico motivato (endpoint IP/MAC/switch/porta/patch, dati tecnici, assegnatario, stato) |
| P06-C2 | Servizio unico usato da form, import Excel e job, atomico |
| P06-C3 | Timeline Monitor/Tecnica-rete con diff, autore, fonte, filtri; vista "com'era alla data X" |
| P06-C4 | Migrazione baseline senza inventare cronologia |
| P06-C5 | Test: ogni via produce storico; nessuna voce se invariato; vista alla data; permessi |
| P06-C6 | Retention configurabile |
| P06-D1 | Catalogo report con descrizione, filtri, esempio |
| P06-D2 | Report salvati per utente e condivisi |
| P06-D3 | Export xlsx protetto e PDF con data e filtri |
| P06-D4 | Totali pagina = export (test) |
| P06-D5 | Report pianificati django-q via email solo a utenti con permesso |
| P06-D6 | `dashboard_kpi.py` senza `except Exception: pass`; "dato non disponibile" con log |
| P06-PERF | Nessuna rete nella request; `assertNumQueries` sulla pagina asset |
| P06-STOP-1 | Destinazione QR (interna/pubblica) chiesta |
| P06-STOP-2 | Storico su decine di view: piano di convergenza proposto |

## P07 — Timbri

| ID | Requisito |
| --- | --- |
| P07-A1 | Modello `Timbro` (codice univoco, tipo, qualifica/ambito, specimen, stato) separato da `AssegnazioneTimbro` (chi, da, a, motivo fine) |
| P07-A2 | State machine esplicita richiesto→approvato→consegnato→attivo / sospeso / ritirato→quarantena→distrutto / smarrito, con test delle transizioni non ammesse |
| P07-A3 | Collegamento forte al dipendente anagrafica, identità unica |
| P07-A4 | Automatismo: cessato → ritiro richiesto con alert |
| P07-A5 | Automatismo: MOD.128 non operativa → sospensione (integrata in `mpq_timbri`) |
| P07-A6 | Automatismo: cambio mansione che toglie qualifica → ritiro proposto |
| P07-A7 | Automatismo: scadenza qualifica → sospensione |
| P07-B1 | Dashboard (attivi, sospesi, da ritirare, smarriti, quarantena, pendenti, ultimi movimenti) |
| P07-B2 | Registro con ricerca per codice, persona, reparto, stato, data ("chi aveva X il giorno Y") |
| P07-B3 | Scheda timbro con timeline; scheda persona con timbri attuali e passati |
| P07-B4 | Wizard emissione/ritiro con controllo univocità in tempo reale |
| P07-B5 | Specimen sheet PDF con data e revisione |
| P07-B6 | Ricevuta consegna/ritiro da firmare |
| P07-B7 | Export registro per audit |
| P07-B8 | Import Excel con anteprima, mappatura, conflitti spiegati, idempotente (sostituisce merge in `views.py`) |
| P07-C1 | `gestione_specifiche` applica solo timbri attivi alla data e dell'utente autorizzato; test con sospeso/ritirato |
| P07-C2 | Ogni applicazione tracciata e visibile nella timeline del timbro |
| P07-INT1 | Mai delete fisico della storia; `reset_timbri_table`/`cleanup_orphan_operatori` solo superuser + conferma + backup + audit (o eliminati) |
| P07-INT2 | Univocità codice imposta dal DB, riassegnazione con quarantena |
| P07-INT3 | Query "chi aveva X il giorno Y" sempre risolvibile |
| P07-SEC1 | Immagini su storage privato cifrato |
| P07-SEC2 | Anteprime con watermark e risoluzione ridotta; originale con permesso dedicato e audit download |
| P07-SEC3 | Upload solo PNG/JPEG, `validate_extension_and_mime`, Pillow senza metadati, limite pixel |
| P07-MIG | Migrazione dati con report, nessuna fusione automatica incerta |
| P07-STOP-1 | Documento di analisi presentato e OK atteso prima del rifacimento |
| P07-STOP-2 | Conflitti (stesso codice attivo su due persone) elencati e chiesti |

## P08 — Audit interni (`sistema_gestione`)

| ID | Requisito |
| --- | --- |
| P08-A1 | Programma annuale/triennale con frequenza da rischio, esiti, NC aperte, cambi, reclami |
| P08-A2 | Calendario e matrice processo×mese con coperture mancanti; approvazione con revisione |
| P08-A3 | Indipendenza e qualifica auditor verificate con blocco e override motivato |
| P08-B1 | Wizard audit con checklist proposta da modelli + domande sui rilievi aperti precedenti |
| P08-B2 | Invio piano e inviti via `tasks/meeting_outlook.py` con conferma |
| P08-B3 | Preparazione AI marcata "bozza da verificare" |
| P08-C1 | Esecuzione tablet domanda per domanda, autosave con indicatore |
| P08-C2 | Tolleranza rete instabile, bozze lato server |
| P08-C3 | Classificazione rilievi (NC magg/min, osservazione, OFI, punto di forza) con clausola ed evidenza obbligatoria per NC |
| P08-D1 | NC → NC/CAPA `anomalie` bidirezionale; OFI → registro OFI |
| P08-D2 | Azione con responsabile, scadenza, cause strutturate, evidenza, verifica efficacia |
| P08-D3 | Solleciti/escalation; chiusura audit solo con azioni approvate (configurabile) |
| P08-E1 | Rapporto PDF configurabile, emissione immutabile con hash e versione, export xlsx |
| P08-E2 | Cruscotto (avanzamento, rilievi, tempo chiusura, efficacia, ricorrenti, copertura clausole) |
| P08-SEC | Permessi per ruolo, auditato vede solo i propri rilievi, evidenze private con controllo per oggetto, AI senza documenti non accessibili |
| P08-STOP-1 | Gap analysis presentata e OK atteso |

## Note di metodo

- I test non vengono eseguiti dai subagent in parallelo. Il vincolo di risorse di `CLAUDE.md` impone un worktree alla volta, e ogni run ricrea un DB SQLite per PID (oltre 15 min sotto carico). I subagent indicano i test-prova; l'auditor li esegue in serie, uno per ambiente (`main`, branch P02, branch P06), con un DB di test a nome fisso.
- Le condizioni di stop "chieste a Brizio" non lasciano traccia nel codice. Si cercano nei commit, nei documenti di analisi e nei report del repo; se non c'è traccia, il requisito è NON VERIFICABILE.
