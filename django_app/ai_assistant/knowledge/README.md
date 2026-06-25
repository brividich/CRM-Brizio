# Knowledge base assistente AI — NOVICROM HUB

Questa cartella contiene conoscenza **curata** che l'assistente AI usa come fonte
per rispondere su uso del portale, moduli e procedure operative. Viene indicizzata
dal RAG (`OLLAMA_RAG_SOURCE_PATHS`) e viaggia nel pacchetto di deploy insieme
all'app (a differenza di `docs/`, esclusa dal pacchetto).

Regole per il contenuto:

- Solo informazioni **non sensibili** e **generali** (dove si fa una cosa, come
  funziona un flusso). Nessun dato personale, credenziale, nominativo o numero reale.
- Frasi chiare e brevi, organizzate per **titoli a forma di domanda**: il RAG
  recupera per sezione, quindi un buon titolo migliora la pertinenza.
- Mantenere accurato: ciò che è scritto qui l'AI lo riporta con sicurezza.

Gli amministratori possono ampliarla aggiungendo file `.md` qui, oppure inserendo
voci dalla console **Gestione AI → FAQ** (salvate nel database e indicizzate allo
stesso modo). Per domande su **dati operativi live** (chi è assente, ticket aperti,
ferie residue…) l'AI non usa questa knowledge base ma i tool runtime filtrati dai
permessi dell'utente.
