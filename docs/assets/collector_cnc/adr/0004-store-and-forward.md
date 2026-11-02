# ADR 0004 — Store-and-forward verso il portale con eventi idempotenti

Stato: accettata (27/10/2026)

## Contesto
Prima il collector mandava lo stato «attuale» ogni 5 s se cambiato e ogni minuto comunque: con il
portale fermo i cambi intermedi andavano persi, quindi anche i periodi di stato su cui si calcola l'OEE.

## Decisione
- Ogni cambio di stato o di allarmi diventa un **evento** nella tabella `outbox` di machines.db, nel
  momento del cambio, con il suo `dal`. Anche le letture dei contatori (ogni ora) passano dalla coda.
- La coda si svuota **in ordine**, a lotti di 200; un record si cancella solo dopo la risposta del
  portale. Portale giù: si riprova con attesa crescente (60 s, 120 s… fino a 300 s).
- Chiave dell'evento: `<istanza di machines.db>:<progressivo>` (l'`id` dell'outbox). Il portale salva
  per macchina l'ultima chiave applicata (`CollegamentoMTConnect.ultimo_evento`, migrazione assets
  0157) e scarta come «evento già applicato (reinvio)» quelle più vecchie della stessa istanza: un
  reinvio non duplica mai periodi. Stessa chiave = aggiornamento (battito); istanza diversa = collector
  nuovo o database ricreato, si riparte.
- Il battito (stato di tutte le macchine ogni minuto) parte **solo a coda vuota** e porta la chiave
  dell'ultimo evento consegnato: non può scavalcare eventi non ancora arrivati.
- Le letture dei contatori sono già idempotenti lato portale (`read_at` non più recente: `ignored_older`).
- Righe senza chiave (collector di versione precedente) si applicano come prima.
- machines.db stesso non perde scritture se bloccato: coda in memoria, una transazione per svuotarla,
  nessuna dipendenza da `lastrowid`.

## Conseguenze
Nessuna perdita con il portale fermo fino al limite della coda (500 000 record, poi si scartano i più
vecchi con un ERROR nel log). Un'ora di fermo con una macchina che cambia ogni 5 s sono 720 eventi.
