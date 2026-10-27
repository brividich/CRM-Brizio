# ADR 0001 — Un thread per macchina per i driver bloccanti

Stato: accettata (27/10/2026)

## Contesto
pyLSV2 (Heidenhain) e Fwlib (Fanuc, via ctypes) sono librerie bloccanti. Il collector è nato asincrono
(asyncua, una coroutine per macchina) e così deve restare per le DMG MORI. Una chiamata bloccante nel
ciclo asincrono fermerebbe tutte le macchine; un pool condiviso mescolerebbe le connessioni e, per
FOCAS, violerebbe l'affinità tra handle e thread che l'ha aperto.

## Decisione
- OPC UA resta asincrono (una coroutine per macchina).
- LSV2 e FOCAS: **un `threading.Thread` per macchina** (`lavoratore.Lavoratore`) con la **sua**
  connessione persistente, riusata a ogni lettura. I record passano al ciclo asincrono con
  `loop.call_soon_threadsafe` su una `asyncio.Queue` della macchina.
- Stop con `threading.Event`: tutte le attese sono `Event.wait`, quindi lo stop interrompe subito
  anche una riconnessione in attesa; poi `join` con timeout e log dei thread rimasti vivi.
- `Sorvegliante`: se una chiamata alla libreria dura più di 3 volte il timeout, il thread è bloccato:
  si interrompe la connessione (LSV2: `disconnect` dal sorvegliante; FOCAS: niente, l'handle è del
  thread), il thread viene abbandonato (i suoi record non passano più), ne parte uno nuovo con un
  driver nuovo, e si registra un intervallo OFFLINE. Evento loggato e contato.

## Conseguenze
- Un thread in più per ogni macchina LSV2/FOCAS (decine, non migliaia: accettabile).
- Un thread davvero appeso dentro una DLL non si può uccidere: resta daemon e abbandonato. Fwlib ha
  il suo timeout (`cnc_allclibhndl3`), pyLSV2 il timeout del socket: il caso è residuale e visibile
  (contatore `bloccati`, riga di log ERROR).
