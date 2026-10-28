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
- **Registrazione a wizard** (`/rentri/carico/`, `/rentri/scarico-originale/`, `/rentri/scarico-effettivo/`, `/rentri/rettifica-scarico/`): form guidato a step (Data → Codice CER ricercabile → Rif.Op a selezione guidata sui soli movimenti collegabili → Quantità/Rettifica → campi accessori facoltativi), allegato del carico con validazione MIME reale
- **Import CSV da portale e CLI** (`import_rentri_csv`): accetta automaticamente export separati da `;` o `,` e normalizza i codici di pericolosita `HPxx` anche quando SharePoint li esporta come lista JSON
- **Formulari** di identificazione rifiuto
- **Elenco a famiglie** (`/rentri/elenco/`): ogni carico con i movimenti collegati, ricostruiti risalendo la catena `rif_op` anche quando lo scarico referenzia il genitore (O o M) invece del carico; famiglie che condividono un carico vengono fuse. Ogni famiglia ha un'intestazione collassabile con stato **APERTA/CHIUSA** (chiusa = ha un carico e almeno uno scarico effettivo M), codice EER, sequenza dei tipi e periodo; le chiuse stanno in fondo e nascono compresse. Filtro **Stato famiglia** (tutte / solo aperte / solo chiuse) e comandi Espandi/Comprimi
- **Scadenzario adempimenti** (`/rentri/scadenzario/`): FIR mancanti, da comunicare, bozze
- **Giacenze per CER** (`/rentri/giacenze/`): giacenza = carico − scarico effettivo − rettifiche per codice EER, **semaforo deposito temporaneo** su soglie giorni configurabili (`SiteConfig`), flag rifiuti pericolosi, export CSV; alimenta lo Scadenzario Globale `/scadenze`
- **Report periodico** per MUD e adempimenti
- **Audit log download** allegati sensibili (non loggati path fisici, contenuto file, token o segreti)

## Hardening ottobre 2026

- Allegati dei carichi in storage privato cifrato (`PRIVATE_ATTACHMENTS_ROOT`), mai serviti da `/media/`. Migrazione `rentri 0006`.

## Robustezza del registro (ottobre 2026)

- **Regole lato server** (`rentri/validazione.py`): CER a sei cifre, quantità > 0 (`Decimal`, virgola accettata; la rettifica R può essere negativa ma non zero), unità obbligatoria sui nuovi movimenti, data non futura, HP obbligatorio sui carichi con CER `*`, Rif. Op esistente, del tipo giusto (O→C, M→O o C, R→M o C), stesso CER, data non precedente, genitore non già collegato; O/M non oltre la giacenza del codice. Le regole di campo valgono per i movimenti nuovi e per i campi che cambiano: lo storico incompleto resta modificabile negli altri campi.
- **Scritture** solo da `rentri/servizi.py` (`salva_movimento`, `consolida`, `annulla`, `segna_trasmesso`): transazione con `select_for_update` su genitori e carichi dello stesso codice, `log_action` con prima/dopo agganciato al record (oltre all'audit automatico dei campi).
- **Stati**: bozza → consolidata (`salva`, non modificabile: 409) → trasmessa (`rentri_si_no`); annullata (`annullato` + motivo, autore, data): resta a registro, non conta mai. `elimina` resta come URL di compatibilità ma annulla.
- **Scheda movimento** `/rentri/<pk>/` (`rentri_dettaglio`): dati, movimenti collegati, Consolida / Segna trasmessa / Annulla, storico. POST `rentri/<pk>/consolida|trasmesso|annulla/`, permesso `rentri.registro.manage`.
- **Verifica** `/rentri/verifica/` (`rentri_verifica`, CSV con `?export=csv`) e comando `python manage.py rentri_verifica [--solo-conteggi] [--format json]`: controlli in `rentri/verifica.py` (termini: 10 giorni lavorativi, 90 giorni quarta copia FIR, costanti da confermare col responsabile ambientale). I conteggi entrano nella mail di `check_rentri_scadenze`, inviata ai referenti delle Impostazioni.
- **Giacenze**: FIFO per l'età in deposito, unità per codice («MISTE» se diverse), criterio quantitativo in m³ (`SiteConfig` `rentri_deposito_m3_max` = 30, `rentri_deposito_m3_pericolosi_max` = 10).
- **SharePoint** (`rentri/sharepoint.py`): il portale fa fede; invio mai bloccante, errore in `sync_errore`, reinvio con `python manage.py rentri_sync_riprova [--dry-run]`; il pull crea solo movimenti nuovi con tipo C/O/M/R e non tocca consolidati/annullati.
- **Import CSV** (`rentri/importazione.py`): tutto o niente, origine `import`; `import_rentri_csv --clear [--backup percorso]` scrive sempre una copia prima di cancellare.
- Migrazione `rentri 0007`: `unita`, `origine` (esistenti = `storico`), `consolidato_il/da`, `annullato`, `annullato_il/da`, `motivo_annullamento`, `sync_errore`.

