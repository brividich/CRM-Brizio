# `rentri` — tracciabilità rifiuti

Area **Sicurezza** · URL `/rentri/` · codice [`django_app/rentri/`](../../django_app/rentri/)

[← Catalogo moduli nel README](../../README.md#-catalogo-moduli)

## Sintesi

Tracciabilità rifiuti (normativa RENTRI): registro C/O/M/R, scadenzario adempimenti, **giacenze per CER** con semaforo deposito temporaneo

## Dettaglio

Gestione registro rifiuti secondo normativa **RENTRI** (Registro Elettronico Nazionale Tracciabilità Rifiuti).

- **3 modelli**: RegistroRifiuti, RentriImpostazioni, RentriRegistroCounter
- **Movimenti** con codice CER, quantità, destinazione, formulario (tipi C/O/M/R)
- **Numero di registrazione allocato** (`rentri/numerazione.py`): `<anno>/<progressivo>` da un contatore per anno con `select_for_update`, non dal conteggio dei movimenti — le eliminazioni non fanno più riciclare un numero già assegnato e i salvataggi simultanei non se lo contendono. Il contatore di un anno mai allocato riparte dal massimo già presente (storico e import inclusi); gli id imposti dall'import restano intatti. Audit di sola lettura: `python manage.py rentri_id_duplicati [--solo-anomalie] [--format table|csv|json]`
- **Registrazione su pagina unica** (`/rentri/carico/`, `/rentri/scarico-originale/`, `/rentri/scarico-effettivo/`, `/rentri/rettifica-scarico/`, modifica `/rentri/<pk>/modifica/`): un solo template `rentri/pages/movimento_form.html` per i quattro tipi (testi in `_FORM_TIPO` di `rentri/views.py`), form-kit `hub-` a sezioni numerate (Movimento → Collegato a → Quantità → Documenti e invio), Codice CER con suggerimenti da tastiera, movimenti collegabili ricaricati a ogni cambio di codice, riepilogo laterale con spunta dei campi obbligatori e salvataggio unico; allegato con validazione MIME reale
- **Compilazione assistita**: dati proposti dal codice e giacenza (`/rentri/api/cer-info/`), pulsanti della catena nella scheda (`?da=<pk>`), «Duplica» (`?duplica=<pk>`), «Scarica» dalle Giacenze (`?codice=`), «Seleziona tutti» e quantità proposta come somma dei collegati
- **Catalogo EER** (`rentri.CatalogoEER`, `rentri/catalogo.py`): solo confronto del codice col nome ufficiale (✓/⚠), ricerca per nome nel carico; caricamento da Impostazioni → «Catalogo EER» o `python manage.py rentri_catalogo_eer <file> [--dry-run] [--forza]` (HTML/PDF EUR-Lex della Decisione 2000/532/CE o CSV `codice;descrizione`, minimo 500 voci)
- **Lettura del FIR** (`rentri/lettura_fir.py`, `POST /rentri/api/leggi-fir/`, solo gestori): propone numero, data, codice, quantità/unità e destinatario dal PDF o dalla foto; regole prima, AI locale (Ollama) solo per codice e quantità mancanti, valori marcati e da confermare
- **Promemoria scarico effettivo** (`rentri/promemoria.py`): schedule `rentri_promemoria_scarico_effettivo` alle 07:25, notifica in-app all'autore e ai referenti per gli O senza M oltre `rentri_promemoria_m_giorni` (SiteConfig, 60, max 90), una volta a settimana; `python manage.py rentri_promemoria [--dry-run]`
- **Import CSV da portale e CLI** (`import_rentri_csv`): accetta automaticamente export separati da `;` o `,` e normalizza i codici di pericolosita `HPxx` anche quando SharePoint li esporta come lista JSON
- **Formulari** di identificazione rifiuto
- **Elenco a famiglie (fili)** (`/rentri/elenco/`): ogni carico con i movimenti collegati, ricostruiti risalendo la catena `rif_op` anche quando lo scarico referenzia il genitore (O o M) invece del carico; famiglie che condividono un carico vengono fuse. Stato dal conto del filo (`rentri/fili.py`): **IN DEPOSITO** (con residuo), **MANCA SCARICO EFFETTIVO**, **CHIUSA**, **SENZA CARICO**, più il segno «COLLEGATO A ANNULLATO». In alto i fili da completare; le chiuse sono **raggruppate per codice CER** (sei cifre) in gruppi collassati. Filtri condivisi con il PDF (`_filtra_registro`): ricerca su numero/codice/rif. op/FIR/note, codice CER, tipo, stato del filo (`aperte`, `deposito`, `attesa_m`, `chiuse`, `senza_carico`, `scollegati`), dal/al, trasmessi, consolidati, solo pericolosi, annullati
- **Scadenzario adempimenti** (`/rentri/scadenzario/`): FIR mancanti, da comunicare, bozze
- **Giacenze per CER** (`/rentri/giacenze/`): giacenza = somma dei residui dei carichi (conto del filo, vedi sotto), codice raggruppato per sei cifre, **semaforo deposito temporaneo** su soglie giorni configurabili (`SiteConfig`), flag rifiuti pericolosi, export CSV; alimenta lo Scadenzario Globale `/scadenze`
- **Report periodico** per MUD e adempimenti
- **Audit log download** allegati sensibili (non loggati path fisici, contenuto file, token o segreti)

## Hardening ottobre 2026

- Allegati dei carichi in storage privato cifrato (`PRIVATE_ATTACHMENTS_ROOT`), mai serviti da `/media/`. Migrazione `rentri 0006`.

## Robustezza del registro (ottobre 2026)

- **Regole lato server** (`rentri/validazione.py`): CER a sei cifre, quantità > 0 (`Decimal`, virgola accettata; la rettifica R può essere negativa ma non zero), unità obbligatoria sui nuovi movimenti, data non futura, HP obbligatorio sui carichi con CER `*`, Rif. Op **facoltativo** (se c'è: esistente, del tipo giusto O→C, M→O o C, R→M, O o C, stesso CER, data non precedente, M/R non già collegati); O collegata non oltre il residuo dei carichi collegati (un carico si scarica in più volte), O non collegata non oltre la giacenza del codice, M dopo una O non controllata (peso a destino), M senza O nel filo come la O. Le regole di campo valgono per i movimenti nuovi e per i campi che cambiano: lo storico incompleto resta modificabile negli altri campi.
- **Scritture** solo da `rentri/servizi.py` (`salva_movimento`, `consolida`, `annulla`, `segna_trasmesso`): transazione con `select_for_update` su genitori e carichi dello stesso codice, `log_action` con prima/dopo agganciato al record (oltre all'audit automatico dei campi).
- **Stati**: bozza → consolidata (`salva`, non modificabile: 409) → trasmessa (`rentri_si_no`); annullata (`annullato` + motivo, autore, data): resta a registro, non conta mai. `elimina` resta come URL di compatibilità ma annulla.
- **Scheda movimento** `/rentri/<pk>/` (`rentri_dettaglio`): dati, «Filo del carico» (stato e residuo), movimenti collegati (genitore annullato = solo traccia), «Collegamenti tolti (traccia)» da `rif_op_storico`, Consolida / Segna trasmessa / Annulla, storico. L'annullamento non è più bloccato dai figli: restano con il `rif_op` come traccia e la verifica li elenca. POST `rentri/<pk>/consolida|trasmesso|annulla/`, permesso `rentri.registro.manage`.
- **Verifica** `/rentri/verifica/` (`rentri_verifica`, CSV con `?export=csv`) e comando `python manage.py rentri_verifica [--solo-conteggi] [--format json]`: controlli in `rentri/verifica.py` (termini: 10 giorni lavorativi, 90 giorni quarta copia FIR, costanti da confermare col responsabile ambientale). I conteggi entrano nella mail di `check_rentri_scadenze`, inviata ai referenti delle Impostazioni.
- **Giacenze**: FIFO per l'età in deposito, unità per codice («MISTE» se diverse), criterio quantitativo in m³ (`SiteConfig` `rentri_deposito_m3_max` = 30, `rentri_deposito_m3_pericolosi_max` = 10).
- **SharePoint** (`rentri/sharepoint.py`): il portale fa fede; invio mai bloccante, errore in `sync_errore`, reinvio con `python manage.py rentri_sync_riprova [--dry-run]`; il pull crea solo movimenti nuovi con tipo C/O/M/R e non tocca consolidati/annullati.
- **Import CSV** (`rentri/importazione.py`): tutto o niente, origine `import`; `import_rentri_csv --clear [--backup percorso]` scrive sempre una copia prima di cancellare.
- Migrazione `rentri 0007`: `unita`, `origine` (esistenti = `storico`), `consolidato_il/da`, `annullato`, `annullato_il/da`, `motivo_annullamento`, `sync_errore`.
- **Segni come in produzione** (letto il 28/10/2026): C positivo; O spesso negativo; M con `quantita` vuota e `rettifica_scarico` negativa; R con lo stesso valore positivo, stesso numero e stessa data dell'M, `rif_op` sullo stesso O/C. La validazione accetta il segno libero tranne sul carico.
- **Consolidamento in blocco**: POST `rentri/scadenzario/consolida-bozze/` (`rentri_consolida_bozze`, pulsante nello Scadenzario) e `python manage.py rentri_consolida_bozze --fino-al AAAA-MM-GG [--applica]`; una voce di audit riassuntiva, nessun invio SharePoint riga per riga (con Graph configurato le righe restano in `sync_errore` per `rentri_sync_riprova`).

## Filo conduttore e collegamenti (novembre 2026)

- **Codice per sei cifre** (`rentri.fili.chiave` = `validazione.normalizza_cer`): candidati, giacenze, validazione ed elenco confrontano «12.01.01 Sfridi Ferro Kg» e «12 01 01» come lo stesso CER. Prima il confronto era sul testo esatto e lo scarico non trovava i carichi scritti in altro modo (catalogo EER, lettura FIR).
- **Conto del filo** (`rentri/fili.py`, unica fonte): residuo per carico; l'uscita dal deposito è la O (valore assoluto), la M solo se nel suo filo non c'è una O, la R mai. Un'uscita collegata consuma i propri carichi (eccedenza = anomalia, non tocca gli altri carichi); una non collegata consuma i carichi del codice in FIFO. Sul registro di produzione la formula precedente `C − M − R` dava giacenze negative (es. 15 01 03 a −5100) e bloccava gli scarichi con «oltre la giacenza». **Da validare col responsabile ambientale.**
- **Movimenti collegabili** (`GET /rentri/api/candidati-rif-op/?tipo=&codice=[&tutti=1][&escludi=<pk>]`): una voce per filo con il carico in vista (data, quantità, residuo, stato); O → carichi con residuo, M → scarichi originali senza M (il carico senza O solo con `tutti=1`), R → scarichi effettivi senza R. `tutti=1` aggiunge i fili già completi (`gia_collegato`).
- **Collegamento facoltativo**: senza Rif. Op lo scarico si salva e si consolida; la verifica lo elenca in «Scarichi senza collegamento».
- **Traccia**: `rif_op_storico` (migrazione `rentri 0009`) riceve i riferimenti tolti in modifica; i figli di un movimento annullato tengono il `rif_op` e compaiono in «Collegati a un movimento annullato».
- **Verifica**: «Saldo del deposito sotto zero» sostituito da «Scarichi oltre il carico» (eccedenze del conto del filo); nuove sezioni «Collegati a un movimento annullato» e «Scarichi senza collegamento».
