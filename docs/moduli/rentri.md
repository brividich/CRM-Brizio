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
