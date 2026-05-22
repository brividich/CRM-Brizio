# AI Governance And Predictive Policy

Policy operativa per l'Assistente AI di NOVICROM HUB: dati live, FAQ curate, audit, apprendimento controllato e funzioni predittive.

## Obiettivi

- Mantenere l'AI dentro i confini ACL server-side del portale.
- Evitare salvataggi automatici di prompt, risposte, note interne o dati sensibili.
- Rendere ogni risposta tracciabile tramite fonti documentali o `tool:*`.
- Abilitare apprendimento e predizioni solo come funzioni assistive, spiegabili e revocabili.

## Regole Non Negoziabili

- L'LLM non interroga database, Open WebUI, Ollama o servizi interni dal browser.
- I tool runtime leggono dati live solo dopo il resolver permessi del modulo.
- L'audit AI resta metadata-only: tool, esito, ambito, conteggi, filtri sintetici, durata e dimensione contesto.
- Le FAQ AI sono conoscenza approvata da admin: nessuna conversazione diventa FAQ senza azione esplicita.
- Le previsioni non aprono ticket, non approvano workflow e non cambiano dati: possono solo suggerire azioni all'utente.

## Matrice Campi

| Dominio | Stato AI | Campi consentiti | Campi vietati | Note privacy |
| --- | --- | --- | --- | --- |
| Catalogo portale | abilitato | label modulo, URL visibile, stato in arrivo | permessi grezzi, ruoli interni | solo discovery navigazione, non autorizzazione |
| Assenze | abilitato | nome, tipo assenza, stato, periodo | motivazioni, note, allegati, dati sanitari | periodo limitato e ACL calendario |
| Ticket | abilitato | numero, titolo, tipo, stato, priorita, richiedente, assegnatario, data apertura | descrizione completa, note interne, commenti, allegati, path SharePoint | scope personale o gestione IT/MAN |
| Tasks / KICK-OFF | abilitato | progetto, task, stato, scadenza, assegnatario, ritardo | note riservate, allegati, budget, extra data | solo campi utili a scadenze e avanzamento |
| Assets | abilitato | codice asset, nome, stato, responsabile, scadenze, OdL sintetici | seriali sensibili se non necessari, documenti, path file, costi dettagliati | manutenzioni e scadenze in forma sintetica |
| DPI | abilitato | categoria/tipo, stato richiesta, consegna, scadenza | firme, allegati, note mediche o disciplinari | separazione utente/gestore obbligatoria |
| Anomalie | abilitato | numero, titolo sintetico, stato, reparto, priorita | descrizioni sensibili, allegati, note interne | niente testo libero esteso |
| Procedure Refresh | abilitato | campagna, documento, stato lettura, esito quiz sintetico | risposte quiz, opzioni, IP, user agent, allegati privati | manager vedono aggregati, utenti assegnazioni |
| Notizie | abilitato | titolo, obbligatorieta, versione, pubblicazione, compliance utente, conteggio allegati | corpo, hash, file, URL/path allegati, report nominativi letture | niente corpo esteso o allegati |
| Sicurezza | abilitato | KPI, trend e riepiloghi aggregati autorizzati | testimonianze, dettagli personali, cause libere, allegati, dati sanitari | solo aggregati, non casi individuali |
| Anagrafica HR | limitato | nome, matricola, reparto, mansione, area, ruolo aziendale, stato attivo/cessato, consenso privacy se richiesto, classifiche ratei ferie/permessi residui con ore e periodo | CF, IBAN, banca, indirizzi, contatti privati, categorie protette, visite mediche, retribuzioni, dettagli cedolino, documenti, path/allegati | solo superuser/admin legacy o ruoli `AnagraficaHRPermission` |
| Timbri / Presenze | rimandato | nessun contesto live AI | timbrature, cartellini, presenze | richiede DPIA/revisione privacy dedicata |

## Retention

| Oggetto | Contenuto ammesso | Retention proposta | Azione operativa |
| --- | --- | --- | --- |
| Audit AI chat/test | metadata-only, nessun prompt o risposta | 180 giorni consultabili, 365 giorni massimi salvo audit legale | job periodico futuro per pruning o export aggregato |
| FAQ AI curate | domanda/risposta approvata, fonte, stato attivo | conservazione fino a revisione admin | revisione trimestrale, disattivazione prima di eliminazione |
| Cache RAG/runtime | chunk documentali e FAQ indicizzate in memoria/cache | TTL configurato da `OLLAMA_RAG_CACHE_SECONDS` | pulsante admin "Svuota cache RAG/runtime" |
| Metriche tool | conteggi, errori, latenza media, contesto medio | derivate da audit metadata-only | non salvare aggregati con dati personali |

## Apprendimento Controllato

L'AI non deve essere "autoapprendente" nel senso di aggiornare autonomamente conoscenza o modello. Il modello sicuro per NOVICROM HUB e':

1. Conversazione effimera nel browser e chiamata server-side.
2. Salvataggio manuale "Salva in FAQ AI" disponibile solo ad admin.
3. FAQ salvata con domanda/risposta approvata e senza prompt history completa.
4. RAG rilegge FAQ curate e documenti allowlist.
5. Audit registra solo lunghezze, tool, fonti e durata.

Evoluzione consigliata: una coda "Proposte FAQ AI" con stato `bozza`, autore, fonte sintetica e review admin. La coda puo' suggerire miglioramenti, ma non pubblicarli.

## Predittivita

Le funzioni predittive devono essere read-only e spiegabili:

- Predire scadenze o priorita partendo da tool gia autorizzati.
- Mostrare sempre fonti, finestra temporale e confidenza.
- Separare "fatti osservati" da "ipotesi" e "azioni consigliate".
- Non generare decisioni automatiche su HR, sicurezza, approvazioni, ticket o task.
- Non usare campi vietati per aumentare l'accuratezza.

Primi casi sicuri:

- Brief operativo "cosa devo fare oggi?" con ranking gia disponibile.
- Rischio scadenza DPI/task/ticket basato su data, stato e priorita.
- Segnalazione di anomalie operative solo aggregate, senza note o descrizioni libere.

## Runbook Open WebUI E Ollama

1. Aprire Admin Portale -> Gestione AI.
2. Verificare provider, URL, modello e timeout.
3. Per Open WebUI HTTP 401/403: rigenerare API key in Open WebUI, incollarla nella console e salvare.
4. Per modello non disponibile: verificare catalogo `/api/models` Open WebUI o `/api/tags` Ollama.
5. Per cold start o modelli grandi: aumentare timeout fino a 180-300 secondi dalla console.
6. Se il RAG sembra obsoleto: usare "Svuota cache RAG/runtime".
7. Dopo ogni modifica, eseguire test connessione e una domanda con fonte attesa.
8. Non incollare key, prompt sensibili o risposte complete nei ticket di supporto: usare solo host, provider, modello, elapsed ms, tool e codice errore sintetico.
