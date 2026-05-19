# AI Runtime Tools Todolist

Checklist operativa per estendere l'Assistente AI dai soli documenti/FAQ a dati live del portale, sempre con ACL server-side e audit metadata-only.

## Stato

Legenda:

- `[x]` completato
- `[~]` in corso
- `[ ]` da fare
- `[-]` rimandato o non applicabile

## Principi Di Sicurezza

- Ogni dato live passa da un tool Django server-side: il browser non interroga direttamente database, Open WebUI, Ollama o servizi interni.
- Ogni tool applica i permessi reali prima di costruire il contesto per il modello.
- Il contesto inviato al modello contiene solo campi minimi e utili alla risposta.
- Non si salvano prompt, risposte, descrizioni lunghe, note interne, allegati, path fisici, token o credenziali in audit.
- L'audit registra solo metadati: tool usato, permesso concesso/negato, ambito, conteggi, filtri principali ed eventuale errore sintetico.
- Le fonti mostrate in chat devono distinguere chiaramente dati live (`tool:*`) e documentazione/FAQ (`README.md`, `docs/ai`, `faq-portale/*`).
- In caso di dubbio sui permessi il tool deve rispondere fail-closed, fornendo una spiegazione operativa senza esporre dati.

## Contratto Di Ogni Tool

- `[x]` Intent detector: riconosce solo domande compatibili con quel dominio.
- `[x]` Permission resolver: calcola l'ambito autorizzato per l'utente corrente.
- `[x]` Data loader: legge solo righe e colonne necessarie.
- `[x]` Summarizer: produce testo breve, leggibile e non sensibile per il prompt.
- `[x]` Source label: aggiunge una fonte `tool:<dominio>:<azione>`.
- `[x]` Audit payload: aggiunge metadati non sensibili.
- `[x]` Test: copre successo, permesso negato/ambito ristretto e assenza di campi sensibili.

## Fase 1 - Fondamenta AI Live

- `[x]` Registry runtime in `ai_assistant.tools` con merge di piu' tool per la stessa domanda.
- `[x]` Passaggio del contesto live autorizzato a `build_ollama_messages()`.
- `[x]` Fonti live mostrate nella risposta della chat.
- `[x]` Audit metadata-only dei tool eseguiti.
- `[x]` Tool catalogo moduli visibili dalla navigazione utente.
- `[x]` Tool Assenze per oggi/domani/settimana con ambito Amministrazione/CAR/negato.

## Fase 2 - Tool Operativi Read-Only

- `[x]` Ticket: riepilogo ticket aperti/urgenti/risolti con ambito personale o gestione IT/MAN.
- `[x]` KICK-OFF / Tasks: progetti, task in ritardo, scadenze e assegnazioni visibili.
- `[x]` Assets: asset assegnati, scadenze, manutenzioni e stato operativo con ACL modulo.
- `[x]` DPI: richieste, consegne, scadenze e conformita con separazione utente/gestore.
- `[x]` Anomalie: elenco e stato segnalazioni autorizzate.
- `[x]` Procedure Refresh: campagne, prese visione, quiz e formazione autorizzata.
- `[x]` Diario Preposto / Incidenti: solo riepiloghi sicurezza autorizzati, senza note sensibili o allegati.
- `[x]` Notizie: notizie pubblicate e leggibili dall'utente corrente.
- `[-]` Timbri / Anagrafica: rimandato a revisione privacy HR dedicata; nessun tool live abilitato in questa fase.

## Fase 3 - Domande Cross-Dominio

- `[x]` Router intent multi-tool per domande come "cosa devo fare oggi?".
- `[x]` Priorita risposte: sicurezza/compliance, scadenze, ticket urgenti, task in ritardo.
- `[x]` Limite globale righe e caratteri per impedire prompt troppo grandi.
- `[x]` Messaggi chiari quando un dominio non ha ancora un tool live.
- `[x]` Test di regressione su merge fonti e audit multi-tool.

## Fase 4 - Console Admin AI

- `[x]` Tab "Tool live" in Gestione AI con stato abilitato/disabilitato per dominio.
- `[x]` Test tool lato admin con utente/ambito simulato senza esporre dati sensibili.
- `[x]` Vista audit AI filtrabile per tool, esito e periodo.
- `[x]` Indicatori di utilizzo: chiamate, errori, latenza media e contesto medio per tool.
- `[x]` Pulsante per svuotare cache RAG/runtime dove applicabile.

## Fase 5 - Governance

- `[x]` Revisione privacy per ogni tool prima di abilitare dati HR o safety sensibili.
- `[x]` Matrice campi consentiti/vietati per modulo.
- `[x]` Policy di retention per FAQ curate e audit AI.
- `[x]` Prompt di sistema aggiornato con regole su dati live, fonti e incertezza.
- `[x]` Runbook operativo per rigenerare API key Open WebUI e diagnosticare Ollama.

## Matrice Moduli

| Modulo | Stato | Campi ammessi nel contesto | Campi vietati |
| --- | --- | --- | --- |
| Catalogo portale | `[x]` | label modulo, URL visibile, stato in arrivo | permessi grezzi, ruoli interni |
| Assenze | `[x]` | nome, tipo assenza, stato, periodo | motivazioni, note, allegati, dati sanitari |
| Ticket | `[x]` | numero, titolo, tipo, stato, priorita, richiedente, assegnatario, data apertura | descrizione completa, note interne, commenti, allegati, path SharePoint |
| Tasks / KICK-OFF | `[x]` | progetto, task, stato, scadenza, assegnatario, ritardo | note riservate, allegati, budget sensibili |
| Assets | `[x]` | codice asset, nome, stato, responsabile, scadenze, OdL sintetici | seriali sensibili se non necessari, documenti, path file |
| DPI | `[x]` | categoria/tipo, stato richiesta, consegna, scadenza | firme, allegati, note mediche o disciplinari |
| Anomalie | `[x]` | numero, titolo, stato, reparto, priorita | descrizioni sensibili, allegati, note interne |
| Procedure | `[x]` | campagna, documento, stato lettura, esito quiz sintetico | risposte dettagliate non necessarie, allegati privati |
| Sicurezza | `[x]` | KPI e riepiloghi autorizzati | testimonianze, dettagli personali, allegati, dati sanitari |
| Notizie | `[x]` | titolo, obbligatorieta, versione, data pubblicazione, compliance utente, conteggio allegati | corpo, hash, file, URL/path allegati, report nominativi letture |
| Timbri / Anagrafica | `[-]` | nessun contesto live AI in fase 2 | dati HR, anagrafiche personali, timbrature e presenze senza revisione privacy dedicata |

## Checklist Per Nuovo Tool

1. `[ ]` Definire esempi di domande che devono attivare il tool.
2. `[ ]` Definire esempi di domande che non devono attivarlo.
3. `[ ]` Identificare helper ACL esistenti del modulo.
4. `[ ]` Definire campi ammessi e vietati.
5. `[ ]` Implementare loader con limite righe.
6. `[ ]` Aggiungere fonte `tool:*`.
7. `[ ]` Aggiungere audit non sensibile.
8. `[ ]` Aggiungere test permesso concesso.
9. `[ ]` Aggiungere test ambito ristretto o negato.
10. `[ ]` Aggiungere test anti-leak su campi vietati.
11. `[ ]` Aggiornare README.
12. `[ ]` Aggiornare CHANGELOG.
13. `[ ]` Eseguire test mirati e `manage.py check`.
14. `[ ]` Verificare compatibilita con router cross-dominio, priorita e limiti globali runtime.

## Prossime Azioni Immediate

1. `[x]` Completare il tool Ticket come primo dominio generale oltre Assenze.
2. `[x]` Aggiungere tool Tasks/KICK-OFF per scadenze e ritardi.
3. `[x]` Aggiungere tool Assets per scadenze e manutenzioni.
4. `[x]` Completare Fase 3 con router cross-dominio, priorita, limiti globali e messaggi tool mancanti.
5. `[x]` Introdurre nella console Admin AI una pagina di stato dei tool live.
6. `[x]` Avviare Fase 5 con matrice campi consentiti/vietati e policy retention audit AI.
