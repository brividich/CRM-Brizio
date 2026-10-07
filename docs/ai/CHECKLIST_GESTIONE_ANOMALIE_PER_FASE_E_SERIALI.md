# Piano di avanzamento — Gestione anomalie: controllo a blocchi di seriali

**Stato:** seconda iterazione implementata (6 ottobre 2026), in attesa di UAT con il reparto Controllo e i capicommessa
**Area:** `django_app/anomalie`
**Ambito di questa iterazione:** inserimento anomalia → mail → decisione del capocommessa. NC e Scheda qualità restano fuori (la Scheda qualità resta nascosta).

## 1. Richiesta (come spiegata dall'utente)

Niente più «salva in fondo alla pagina e ricomincia»: tutto il controllo di un OP avviene in **una sola pagina dinamica**.

Esempio: controllo l'OP X e trovo **1 S/N con N anomalie**. Inserisco il S/N, la prima anomalia (con eventuali allegati, anche **trascinati** o **incollati dagli appunti di Windows**), premo **+ Nuova anomalia** e proseguo; le anomalie già scritte si **comprimono** per occupare meno spazio. Premo **Salva**: il blocco di quel S/N si **congela**. Poi inserisco un **range** di S/N (con la possibilità di aggiungere altri seriali singoli, gruppi o range) e le relative anomalie: una sola, oppure più anomalie sugli stessi S/N.

## 2. Decisioni prese con l'utente

| Tema | Decisione |
|---|---|
| Granularità | **1 anomalia = 1 riga** della tabella legacy `anomalie`: stato, RDC, segnalazione al cliente, chiusura e risposta sono per singola anomalia. Il blocco di S/N e il controllo servono solo a raggruppare (opzione B; scartate «1 blocco = 1 riga con più descrizioni» e l'ibrido). |
| Fase | Indicata **una volta in testa** al controllo, modificabile; ogni blocco salvato registra la fase in vigore in quel momento. |
| Mail al capocommessa | **Entrambe le modalità**, scelte all'avvio e modificabili: «a ogni blocco salvato» (con il debounce di 5 minuti) oppure «una sola mail a fine controllo». |
| Blocco congelato | Si riapre con **«Modifica»**; le anomalie su cui il capocommessa ha già deciso restano bloccate, e con esse seriali e stato superficie del blocco. |
| NC / Scheda qualità | Fuori ambito per ora; l'aggancio esistente alla NC dell'OP resta com'era. |

## 3. Come funziona

### Inserimento (`/gestione-anomalie/nuova-segnalazione`)

1. Scelta OP (invariata). Se l'utente ha un controllo ancora aperto su quell'OP negli ultimi 7 giorni, può **riprenderlo**.
2. Avvio: fase (con suggerimenti dalle fasi già usate sull'OP) e modalità mail → «Inizia controllo».
3. Blocco: seriali a «chip» (Invio, virgola o spazio confermano; si incollano elenchi; i range mostrano il numero di pezzi), stato superficie, anomalie. Avvisi non bloccanti: formato `AAA00000`, prefisso diverso, S/N già in un altro blocco del controllo, S/N con anomalie già aperte sull'OP (con descrizione, stato e autore).
4. Allegati per anomalia: trascina, «sfoglia», **Ctrl+V** ovunque nella pagina (va all'anomalia aperta; nei campi di testo vince il testo). Le immagini incollate prendono il nome `appunti-AAAAMMGG-hhmmss-n.png`. Limiti invariati: formati ammessi; dimensione per file da `UPLOAD_MAX_FILE_MB` (default 100 MB).
5. «Salva blocco» → una riga per anomalia (stesso percorso di `api_salva`: permessi per OP, audit, timeline), blocco congelato, nuovo blocco pronto. Un salvataggio parziale conserva gli id già creati, così un nuovo tentativo non duplica.
6. «Termina controllo» → se c'è un blocco non salvato chiede se salvarlo o scartarlo; manda subito le mail ancora in coda e mostra a chi sono andate.

### Mail

- Destinatario: capocommessa, in copia il CAR; per i **collaudi di benestare** (`ordini_produzione.stato = Benestare`) il CAR è il destinatario principale.
- Link alla pagina sicura con token (scadenza 72 ore, monouso per le azioni dispositive), azione `aggiorna_avanzamento`.
- Corpo raggruppato per blocco di S/N con fase, operatore, data, testo e stato superficie di ogni anomalia.
- Copia di riepilogo senza link al segnalante e alla lista «conferma aggiornamenti».
- Errori di invio: ritentati dal task `anomalie_pending_notifications` (ogni minuto), dopo 5 tentativi avviso ai supervisori. In modalità «fine» la mail parte comunque dopo 4 ore senza salvataggi.

### Decisione del capocommessa

- **Pagina della mail**: anomalie raggruppate per blocco (prima quelle della mail, «Da decidere», poi le altre aperte dell'OP), foto e allegati per ogni anomalia, campi già compilati con lo stato attuale (RDC, cliente, numero RDC, note), «Stessa decisione per tutte le anomalie di questi seriali». Si aggiornano **solo** le anomalie salvate nella pagina.
- **Gestione anomalie**: le anomalie dello stesso blocco sono raggruppate sotto un'intestazione con S/N, fase, operatore e data; nel dettaglio un'opzione applica la stessa decisione alle altre anomalie aperte del blocco.

## 4. Modello dati

- `AnomaliaControllo` — sessione di controllo: OP, fase corrente, modalità mail, operatore, coda `da_notificare`, esito dell'ultimo invio.
- `AnomaliaBlocco` — voci S/N come digitate, etichetta composita per la colonna legacy `seriale` (es. `LCN00005-LCN00010, LCN00020 (7 pezzi)`), fase, stato superficie.
- `AnomaliaSegnalazioneMeta` (esistente) + `controllo`, `blocco`, `ordine_nel_blocco`.
- Colonna legacy `descrizione` = `Stato superficie: …` in testa + testo (formato già letto da pagina mail e gestione).
- `AnomaliaDescrizione` / `AnomaliaDescrizioneAllegato` (prima iterazione) restano per compatibilità: le descrizioni multiple si mostrano solo dove esistono già (righe con più di una descrizione); non se ne creano più.

Migrazioni: `0013`, `0014` (prima iterazione), `0015_controllo_blocchi` — tutte additive.

## 5. Problemi della prima iterazione corretti

- [x] Ogni salvataggio cancellava e ricreava le descrizioni: si perdevano risposte, legami con gli allegati e i link delle mail già inviate.
- [x] Al primo salvataggio dalla gestione veniva creata una «descrizione» per ogni riga, duplicando il testo.
- [x] Le risposte per descrizione aggiornavano autore e data anche se non cambiate.
- [x] Errori nel salvataggio delle descrizioni nascosti all'utente (solo nel log).
- [x] Pagina della mail: confermando, le anomalie non toccate perdevano i flag RDC/cliente; la nota per anomalia non veniva salvata con «Aggiorna avanzamento»; mancava il numero RDC; immagini solo per la prima anomalia.
- [x] Gestione: dopo il salvataggio il record nell'elenco perdeva i dati aggiunti dal server (fase, blocco).
- [x] Controllo duplicati: i range dentro una lista (`A, B-C`) non venivano espansi.

## 6. Checklist

### Implementazione
- [x] Modelli e migrazione `0015`.
- [x] API controllo (`controlli`, `apri`, `<id>`, `impostazioni`, `blocco`, `termina`) con permesso per OP e controllo legato all'operatore.
- [x] Form dinamico: fase in testa, modalità mail, blocchi, chip seriali, anomalie comprimibili, drag & drop, incolla da appunti, congela/modifica, ripresa, termina.
- [x] Mail con link: due modalità, debounce, rete di sicurezza, ritentativi, raggruppamento per blocco.
- [x] Pagina della mail: raggruppamento, allegati, campi precompilati, numero RDC, decisione per blocco, nessun azzeramento delle anomalie non toccate.
- [x] Gestione anomalie: raggruppamento per blocco, decisione su tutto il blocco.
- [x] Test (`anomalie.tests_controllo` + `tests_mail_action` + `tests_qualita`: 68 verdi); i 7 rossi di `anomalie.tests` sono preesistenti (identici sul branch di partenza).
- [x] Verifica a video su SQLite con dati sintetici: form (chiaro, scuro, telefono), esito, mail HTML, pagina della mail, gestione (chiaro, scuro).

### UAT (da fare con il reparto)
- [ ] Un S/N con più anomalie, poi un range + seriali singoli con una e con più anomalie.
- [ ] Incolla da appunti con screenshot reali (Strumento di cattura) e foto da telefono/cartella.
- [ ] Modalità «a ogni blocco» e «a fine controllo»: arrivo, leggibilità nei client reali (Outlook), copia al CAR, benestare.
- [ ] Decisione dalla mail (singola e per blocco) e dalla gestione; verifica che le anomalie non toccate restino invariate.
- [ ] Riapertura di un blocco dopo una decisione del capocommessa.
- [ ] Verificare in produzione le regole automazione attive sull'inserimento in `anomalie`: con «a fine controllo» manderebbero comunque mail a ogni riga.

### Rilascio
- [ ] Merge `feature/anomalie-fasi-seriali-v2` → `main` → `release/prod`.
- [ ] Backup DB e cartella allegati; `migrate anomalie 0013 0014 0015`.
- [ ] Rivalutare la riattivazione della Scheda qualità (fuori da questo rilascio).
