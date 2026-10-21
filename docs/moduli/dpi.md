# `dpi` — Dispositivi Protezione Individuale

Area **Sicurezza** · URL `/dpi/` · codice [`django_app/dpi/`](../../django_app/dpi/)

[← Catalogo moduli nel README](../../README.md#-catalogo-moduli)

## Sintesi

Dispositivi Protezione Individuale: catalogo gerarchico, richieste, approvazione, consegna firmata, report conformita, reminder scadenze; **raccoglitore «Documenti»** (certificati, attestati, manuali d'uso, ciascuno legato al suo DPI del catalogo, senza categorie di documento: i gestori caricano/eliminano, tutti consultano; storage privato cifrato con audit); **flusso di richiesta**: dipendente (o il suo responsabile per suo conto) → approvazione del responsabile/preposto (vede solo i propri dipendenti) → avviso di consegna a Magazzino e Amministrazione (email configurabili in Impostazioni) → consegna registrata dal magazzino → report di consegna con PDF all'Amministrazione; **Magazzino DPI**: giacenza per modello come somma di movimenti (carico DDT inserito a mano, scarico automatico alla consegna, rettifica inventario), scorta minima con stato «Da riordinare/Esaurito»; **report magazzino** (consumi per mese/reparto/modello, coperture in giorni, elenco «da riordinare» con quantita' suggerita, export CSV); **«Prima di decidere»** nella gestione richieste (storico consegne, media reparto, proposta AI che impara dalle decisioni del gestore)

## Dettaglio

Ciclo completo DPI dal magazzino alla consegna firmata al dipendente.

- **8 modelli**: CategoriaDPI (con immagine, vita utile e flag obbligatorio mansionario), TipoDPI (sottocategoria), ModelloDPI (codice, produttore, immagine, vita utile override), TagliaDPI (valore taglia), DPIImpostazioni (singleton), RichiestaDPI, ConsegnaDPI (1:1 con firma PNG base64), RichiestaDPICommento
- **Gerarchia DPI**: Categoria → Tipo → Modello → Taglia gestibile da `/dpi/impostazioni/`, con immagine modello e attivazione/disattivazione record
- **Icona categoria**: selezionabile da un set di 11 icone SVG line-style (sprite `dpi/components/_dpi_icons.html`, filtro `dpi_extras.dpi_icon_key`) al posto di un'emoji libera; sostituibile con un'immagine caricata. Le emoji storiche già salvate restano visualizzate correttamente tramite mappatura automatica. L'icona «Mascherina / respiratore» (`mask`) è una semimaschera con due filtri vista di fronte (21/10/2026); la migrazione `dpi 0013` assegna `mask` alle categorie con «respir»/«mascher» nel nome rimaste sull'icona predefinita (gilet)
- **Richieste** con **card-picker grafico** per la categoria e selezione opzionale di tipo/modello/taglia; resta supportata la richiesta con sola categoria
- **Numerazione univoca** `DPI-YYYY-NNNN`
- **Stati workflow**: creata → approvata → consegnata → rifiutata/annullata
- **Approvazione** da parte del responsabile sicurezza con commenti
- **Consegna** con firma dipendente via canvas HTML5, data e ricevuta firmata; una nuova consegna dello stesso `tipo_dpi` già in carico allo stesso dipendente sostituisce automaticamente la precedente (che resta in storico, uscendo dai conteggi "in uso"/scadenze)
- **Vita utile** DPI tracciata per categoria/modello: il modello, se valorizzato, sovrascrive la vita utile categoria nel calcolo della scadenza consegna; lista e dettaglio mostrano il semaforo scadenza. Cambiando la vita utile di categoria o modello, le consegne in uso con scadenza automatica si riallineano subito (`segnali_scadenze.py`); restano quelle con scadenza inserita a mano e quelle già sostituite
- **Report conformita** per dipendente su `/dpi/report-conformita/`, con filtro categorie obbligatorie e stato OK/scaduto/mancante
- **Reminder scadenze** schedulabile con `python manage.py send_dpi_expiry_reminders --dry-run`
- **Storico** completo per dipendente con export PDF
- **KPI dashboard** su consumi, costi, scadenze imminenti
- **Leggi un DDT** (Magazzino, scheda accanto a «Carico da DDT»): PDF o foto del DDT → `core.lettura_documenti` (testo nativo, OCR Tesseract per le scansioni) → `dpi/lettura_ddt.py` propone numero, data, fornitore e una riga per ogni codice `ModelloDPI` attivo trovato nel testo, con la quantità della stessa riga (prima «PZ 24», poi «24 PZ»; «da controllare» se incerta). Il gestore spunta e corregge; `azione=carico_ddt` registra un `magazzino.carica_ddt` per riga. Stessa URL `/dpi/magazzino/` (azioni POST `leggi_ddt`, `carico_ddt`), stesso controllo `_is_gestore`; il file non resta sul server.

## Ruoli del portale

Con il sistema dei ruoli attivo ([PERMESSI_RUOLI.md](../ai/PERMESSI_RUOLI.md)): «gestire» apre consegne, magazzino, catalogo e impostazioni (Sicurezza, Magazzino); «approvare» approva sul perimetro del ruolo, per preposti e responsabili il team d'organigramma; nessuno approva la propria richiesta. Dashboard e dettaglio mostrano proprie, del team o tutte secondo «vedere». Sempre: la notifica in-app di approvazione, rifiuto e consegna va all'account del richiedente (prima riceveva l'id anagrafica come id utente e poteva arrivare a un'altra persona).
