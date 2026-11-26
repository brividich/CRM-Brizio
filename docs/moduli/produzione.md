# Ordini di produzione (`produzione`)

URL: `/produzione/`. Voce «Ordini di produzione» nel menu Produzione.

## Cosa fa

Ogni OP con i suoi documenti di produzione. Gli OP sono la tabella legacy `ordini_produzione`, la stessa di Gestione anomalie: la sezione la legge (`core/ordini_produzione.py`) e non la copia. Gli OP nuovi si creano da qui con «+ Nuovo OP» (pannello laterale, `produzione/_nuovo_op.html` + `produzione/js/nuovo_op.js`, POST JSON `/produzione/op/nuovo/`), dalla scheda FAI (stesso pannello, l'OP creato va nel campo OP con l'evento `op:creato`) o da Gestione anomalie: tutti usano `anomalie.views.crea_op_da_dati`, con il controllo del titolo già esistente in `produzione/nuovo_op.py`.

- **Elenco** (`/produzione/`): OP dal più recente con P/N, capocommessa, CAR, stato, numero di documenti, FAI e anomalie aperte; ricerca per OP, P/N, capocommessa o CAR, filtro per stato, 100 per pagina. Chip «Da sistemare» (`?manca=anomalie|documenti|fai`: con anomalie aperte, senza documenti, senza FAI); nelle colonne «Manca» e il numero delle anomalie aperte portano al passo della scheda (`#passo-<chiave>`).
- **Scheda** (`/produzione/op/<id>/`, id della tabella `ordini_produzione`) come percorso in cinque passi (`services.percorso`): KICK-OFF del P/N, programmi CAM e CMM, documenti di produzione, FAI, anomalie. Ogni passo è `fatto`, `dafare`, `attesa` o `allerta` con un solo pulsante d'azione precompilata («Nuovo KICK-OFF» → `tasks:project_create?pn=`, «Aggiungi documento» → `?aggiungi=1`, «Nuovo FAI» → `tasks:fai_nuovo?op=&pn=`, «Gestisci le anomalie»); «Prossimo passo» in cima (`services.prossimo_passo`: primo da fare o da gestire, poi la prima attesa) o «Percorso completo». Contenuti:
  - documenti registrati (`DocumentoOP`: tipo, titolo o numero, revisione, data, cartella o file di rete, note);
  - FAI del Registro FAI: prima quelli che citano l'OP, poi gli altri del P/N; «Nuovo FAI per questo OP» apre `tasks:fai_nuovo?op=&pn=`;
  - programmi CAM e CMM delle righe KICK-OFF dello stesso P/N;
  - anomalie (totale e aperte, stesso legame di Gestione anomalie: id SharePoint o titolo) con link a `/gestione-anomalie?op=`;
  - KICK-OFF del P/N e altri OP dello stesso P/N.
- **P/N** (`/produzione/pn/`, `services.righe_pn`): il P/N è l'articolo principale con più OP, e il FAI è del P/N, non dell'OP. Una riga per P/N (normalizzato con `tasks.identity.normalize_part_number`) degli OP: numero di OP, ultimo OP, capocommessa, FAI, «Situazione FAI» (la peggiore fra gli articoli del P/N, da `tasks.services.fai.righe_registro`, stessa lettura del Registro FAI) e anomalie aperte di tutti gli OP. La ricerca sceglie i P/N da un loro OP, capocommessa o CAR ma conta tutti gli OP. Chip `?manca=anomalie|fai|scadenza`.
- **Scheda del P/N** (`/produzione/pn/scheda/?pn=`, `services.scheda_pn`, 404 se nessun OP ha quel P/N): quattro passi — KICK-OFF del P/N, programmi CAM e CMM, FAI del P/N (situazione per cliente con «entro», tutti i FAI con il loro OP, «+ Nuovo FAI per questo P/N» → `tasks:fai_nuovo?pn=`), OP del P/N (CAR, stato, documenti, anomalie aperte).
- Nella scheda dell'OP il passo è **FAI del P/N** (`services._passo_fai`): conta il FAI più recente non annullato del P/N, anche se fatto su un altro OP; «allerta» se l'articolo è da ripetere o, dopo un FAI positivo, da verificare. Nell'elenco OP la colonna «FAI del P/N» e il chip «Senza FAI» contano i FAI del P/N.
- **Report CMM e andamento quote** (`produzione/report_cmm_indice.py`): la cartella `PRODUZIONE_REPORT_CMM_ROOT` (default `\\novisrv\Area Controllo\Collaudo`, struttura `<P/N>\<OP-aaaa-n>\<fase>_<OP>_<Z..>_<S/N>[_suffisso].pdf`) si legge in sola lettura con `anomalie.report_cmm.leggi_pdf(ocr=False)`. `ReportCMM` (P/N dalla cartella, OP dalla cartella → `OP/aaaa/n`, programma = «Part Program Name», `programma_base` senza `_REVn`, S/N e data dalla testata, ripiego sul nome file) e `MisuraCMM` (nome, `chiave` = nome senza spazi maiuscolo, gruppo, tipo, rilevato, nominale, tolleranze con segno, fuori, `fuori_di`, da verificare). Un PDF si rilegge solo se cambiano dimensione o data; quelli spariti si tolgono. Giro pianificato `produzione_report_cmm_giro` (`produzione.tasks.run_giro_report_cmm`, ogni ora ai 40, timeout 900 s, blocco in cache contro la riconsegna) per `PRODUZIONE_REPORT_CMM_MINUTI` (15): prima le cartelle mai lette, poi quelle cambiate, poi le più vecchie. `manage.py leggi_report_cmm [--pn P/N] [--minuti N]`.
  - **Analisi quote** (`/produzione/pn/quote/?pn=`, template `quote.html` + `produzione/js/analisi_quote.js` + `produzione/css/analisi_quote.css`, nessuna libreria): i dati arrivano da `GET /produzione/api/quote/?pn=&prog=&da=&a=` (`report_cmm_indice.dati_programma`, JSON compatto: report, quote `id = chiave|nominale`, valori per quota; al massimo 800 report, i più recenti; 401 JSON senza login, permesso dal middleware ACL). Filtri globali (programma, periodo, OP, S/N evidenziato), KPI del programma, elenco quote con mini linea e filtri/ordinamenti, viste Quota (Cp/Cpk, grafico con zona di tolleranza, media, ±3σ, colori per OP, zoom a trascinamento, istogramma allineato, tabella), Mappa (canvas quote × report, divergente blu/rosso sulla tolleranza usata, fuori = rosso pieno), Confronto (fino a 6 quote in % della tolleranza) e Pezzo (barre per quota, secondo S/N a confronto). Stato nell'indirizzo (`prog, q, tab, per, da, a, op, cmp, r, f, ord`; dal report `q=<chiave>&nom=`). CSV lato browser con `;` e virgola decimale. Tolleranza usata e Cpk: `report_cmm_indice.usata` / `statistiche` (unilaterali con nominale 0 e limite inferiore 0: x/USL e Cpk = CPU).
  - **Migliorie (migrazione `0004`)**: `ReportCMM.escluso` (+ motivo, nota, chi, quando; POST `/produzione/report-cmm/<id>/escludi/` con `azione=escludi|riammetti`, permesso `produzione.quote.manage`); `NotaQuotaCMM` (eventi sul grafico, `POST /produzione/api/quote/nota/`, togliere: autore o `quote.manage`); `AliasQuotaCMM` (quota d'origine anche di un altro programma → destinazione, `POST /produzione/api/quote/alias/`, `GET /produzione/api/quote/candidati/`); `ImpostazioniQuoteCMM` (destinatari e interruttori degli avvisi, in Impostazioni). `dati_programma` restituisce anche esclusi (flag), programma con revisione, note, anomalie per report (tabella legacy `anomalie`, stesso OP e S/N) e le quote unite. Filtri della pagina: `tutte`, `esclusi`, `rs` (id report). `deriva` (retta ultimi 20) e `segnali` (Western Electric) uguali in Python e JS; `analisi_pn` (ultimi 30 validi, una misura per S/N, cache finché non cambiano i report) alimenta `quote_critiche`, `cruscotto` e gli avvisi.
  - **Quote CMM** (`/produzione/quote/`, `?f=tutti`): tutti i P/N dal più grave. **PDF di capacità** (`/produzione/pn/quote/pdf/`, reportlab, `pdf_capacita.py`). **Avvisi** (`avvisi_cmm.invia_avvisi`, chiamato dopo ogni lettura con report nuovi): notifica in-app «generico» per i report nuovi con fuori (`ReportCMM.avvisato`) e per le quote in deriva (cache 30 giorni). **FAI**: `services.fai_cmm` (primo report valido dell'OP del FAI + `capacita_dopo`) nella scheda FAI e nel passo FAI della scheda P/N.
  - **Quote da tenere d'occhio** nella scheda P/N (`report_cmm_indice.quote_critiche`: ultimi 30 report per programma, fuori nell'ultimo report poi Cpk < 1,33, al massimo 6).
  - **Report** (`/produzione/report-cmm/<id>/`): quote fuori o da verificare (`?tutte=1` tutte), «Andamento» per ciascuna, altri report dello stesso S/N, «Apri il PDF» (`/produzione/report-cmm/<id>/pdf/`, solo file sotto la radice) e «Apri segnalazione anomalia» → `/gestione-anomalie/nuova-segnalazione?op_id=<id>&report_cmm=<id>`: il pannello «Dal report CMM (PDF)» si apre da sé e chiede `api/anomalie/report-cmm/leggi` con `report_cmm` (serve anche `produzione.op.view`).
  - Riquadro «Report CMM» nelle schede del P/N (conteggi e ultimi 8) e dell'OP (report di quell'OP).
- **Impostazioni** (`/produzione/impostazioni/`): tipi di documento (`TipoDocumento`), seminati dalla migrazione `0002`.

Un documento cita l'OP col suo titolo, come anomalie e FAI. FAI, programmi e KICK-OFF rispettano i permessi del modulo KICK-OFF.

### Report CMM nel formato vecchio (26/11/2026)

- `anomalie.report_cmm`: la riga d'intestazione «Name ID Aktual Nominal pos Tol neg Tol Diff <--|-->» (CALYPSO con novaPDF, 2014-2024) vale come quella nuova (`_SINONIMI_COLONNE`, `col["vecchio"]`). Nel formato vecchio «neg Tol» vuota = tolleranza unilaterale (0); con nominale 0 e «neg Tol» positiva è la tolleranza effettiva della posizione (bonus di massimo materiale): `tol_sup = max(pos, neg)`, `tol_inf = 0`. Nella colonna «<--|-->» la barretta grafica si ignora, il numero è l'eccedenza. Testata anche in italiano («Nome piano», «No. di disegno», «Ordine», «Numero pezzo incrementale», «Commento:», «Firma:»). Verificato su 325 report veri (25 per anno, 2012-2024, solo lettura): 22.560 quote, 4 da verificare, eccedenza stampata = fuori calcolato; 120 report del formato nuovo invariati.
- `report_cmm_indice.data_report` legge anche «13 settembre 2023» / «September 13, 2023».
- `ReportCMM.lettore` (migrazione `0006`) e `report_cmm_indice.LETTORE = 2`: un report senza quote letto da un lettore più vecchio si rilegge anche se il file non è cambiato (`ReportCMM.da_rileggere`); il giro passa prima le cartelle che ne hanno. Alzare `LETTORE` quando il lettore impara un formato nuovo.
- `avvisi_cmm.invia_avvisi`: avvisa solo i report con data negli ultimi `GIORNI_AVVISO` (30) giorni; gli altri si segnano come avvisati.

### Pagina del pezzo (26/11/2026)

- `/produzione/pezzo/?pn=<P/N>&sn=<S/N>`: report del pezzo (S/N confrontato su lettere e cifre), quote allineate come nel confronto (ultimi 12 report), filtri `solo=fuori|cambiate`, storia con anomalie del S/N (`core.ordini_produzione.anomalie_del_seriale`); `formato=pdf` scarica la scheda pezzo (`produzione/pdf_pezzo.py`, ultimi 6 report). Dati in `report_cmm_pagine.pezzo` e `report_del_pezzo`. Nessuna tabella nuova.
- Link: S/N nel titolo del report, «Pagina del pezzo» in «Altri report dello stesso S/N» (ora riconosce anche il S/N scritto diverso), S/N nella matrice «Pezzi e fasi» dell'OP.

### Anagrafica e catalogo dei P/N (26/11/2026)

- Tabella `produzione_articolopn` (`ArticoloPN`, migrazione `produzione 0005`): P/N unico, descrizione, cliente, disegno, revisione, materiale, famiglia, stato (vuoto = dall'attività), note, origine, cartella Collaudo, chi ha modificato; riepilogo precalcolato (OP, OP aperti, report, report 12 mesi, fuori 30 giorni, ultimo report, Cpk peggiore, quote non capaci, andamento per mese).
- `produzione/articoli.py`: `sincronizza()` crea gli articoli da OP, KICK-OFF (`tasks.Project`) e cartelle della share, completa i campi vuoti da KICK-OFF e Registro FAI, ricalcola il riepilogo; `aggiorna_cpk()` per i P/N letti. Lo chiama la fine di ogni giro dei report CMM; «Aggiorna il catalogo» (POST `/produzione/pn/sincronizza/`) lo lancia a mano.
- `/produzione/pn/`: catalogo (`services.catalogo`) con «Mostra», cliente, ordine; `/produzione/pn/<P/N>/anagrafica/` (POST) salva il pannello «Anagrafica». La scheda del P/N si apre anche per i P/N senza OP.
- Permesso nuovo `produzione.articoli.manage` (di default solo admin). Deploy: `migrate produzione`, sincronizzazione dei permessi; il catalogo si riempie al primo giro o al primo «Aggiorna il catalogo».

### Scheda OP a sezioni con pezzi × fasi (26/11/2026)

- Sezioni con `?sez=`: Pezzi (vuota), `report`, `documenti`, `fai`, `programmi` (gli ultimi due per chi vede i KICK-OFF). `?aggiungi=1` e `?documento=<id>` aprono Documenti; dopo il salvataggio si torna a Documenti.
- Matrice: `report_cmm_pagine.matrice_op` (report validi dell'OP per S/N e programma base; cella = ultimo report; «limite» se una quota supera l'80% della tolleranza; rimisure contate) e `cronologia_op`. Anomalie aperte per S/N: `core.ordini_produzione.anomalie_aperte_per_seriale` (stesso legame di Gestione anomalie).
- Tolto «Prossimo passo»: il percorso è la striscia in alto.

### Scheda P/N a sezioni (26/11/2026)

- Indirizzo stabile `/produzione/pn/<P/N>/` (nome `produzione:pn`, `services.url_pn(pn, sezione)`); il vecchio `/produzione/pn/scheda/?pn=` reindirizza (301) e resta valido per i link degli altri moduli.
- Sezioni con `?sez=`: Panoramica (vuota), `op`, `report`, `programmi`, `fai`. Programmi e FAI solo per chi vede i KICK-OFF.
- Panoramica: striscia del percorso, «Da fare» (`services.da_fare_pn`: quote fuori nell'ultimo report o in deriva, anomalie aperte, OP senza documenti), «Pezzi misurati per mese» (`services.pezzi_per_mese`, report CMM validi degli ultimi 6 mesi).

### Report CMM e confronto (26/11/2026)

- `/produzione/report-cmm/<id>/`: tutte le quote del report (le fuori in cima) con barra nella tolleranza, tolleranza usata, differenza dal pezzo prima (stesso programma), Cpk sugli ultimi 30 pezzi; filtri `?f=fuori|limite|cambiate`; pezzo prima / dopo.
- `/produzione/report-cmm/confronta/?r=<id>&r=<id>…`: da 2 a 6 report affiancati, quote allineate per nome e nominale e con le unioni di Analisi quote; `solo=1` solo quote che cambiano oltre il 20% della tolleranza o fuori; `formato=csv` per Excel. Si apre spuntando le righe negli elenchi dei report (scheda P/N, scheda OP, report).
- Calcoli in `produzione/report_cmm_pagine.py` (`righe_report`, `vicini`, `confronta`, `proposte`). Permesso: `produzione.op.view`.

### Pagine in stile protocollo CMM (26/11/2026)

- Report (`report_cmm.html`): testata con timbro d'esito (`nok`, `verifica`, `ok`, `escluso`, `vuoto`), protocollo a tre parti: albero dei gruppi (`report_cmm_pagine.gruppi`, sezione del report), tabella con deviazione, «Fuori di» e grafico SVG (`report_cmm_pagine.grafico`: limiti a 15 e 85, avviso all'80%, barra dal centro; unilaterali da 10 a 80), dettaglio a destra da `json_script` (`report_cmm_pagine.pannello`) disegnato da `produzione/js/protocollo.js` con la serie degli ultimi 30 pezzi (`analisi_pn` ora restituisce `serie`, `media`, `sd`, `cp`, `lsl`, `usl`, `deriva_info`; chiave cache `prod_cmm_analisi2`).
- Pezzo (`pezzo.html`): stato dall'ultimo report di ogni fase (`fasi_ko`), matrice quote × report con livello per cella (`_livello`: basso fino al 50%, medio, limite oltre l'80%, fuori), viste % / deviazione / valore ricordate in `localStorage`, pezzi dello stesso OP (`stesso_op`).
- Scheda P/N: sezione `?sez=qualita` (`report_cmm_pagine.qualita_pn`, `lettura_quota`), `&q=<programma>::<id quota>` sceglie la quota, `&vista=tabella` la tabella Cpk. La sezione `report` accetta `?da=AAAA-MM-GG&a=AAAA-MM-GG` (dalla mappa) e non ripete più le quote critiche.
- Quote CMM: `cruscotto()` restituisce `celle` (report fuori / misurati per settimana, `_cella_mappa`), `settimane_mappa()` e `quote_da_guardare_tutte()`.
- Pagine di dettaglio senza `_nav.html`: percorso nell'eyebrow e `<template data-hub-percorso-gerarchia>`, badge con `prod-badge` (fuori dal nome nel percorso in alto), «? Guida» fra i pulsanti. Il catalogo si intitola «Catalogo P/N». Nessuna migrazione; serve `collectstatic` (`produzione.css`, `protocollo.js`).

### Stile unico del modulo (26/11/2026)

- `.prod-chip`, `.aq-chip`, `.aq-segmenti` come `.prot-filtro` (scelto = `var(--text)` pieno); `.prod-dati`/`.prod-dato`, `.aq-kpi`/`.aq-tiles`/`.aq-tile` come striscia unica (bordi interni con `box-shadow`); `.prod-cella` con la tavolozza di `.prot-liv`. Elenco OP e catalogo: `data-fm-hide-search="1"` (una sola ricerca). Solo CSS e template, nessuna migrazione.

### Quote CMM con analisi precalcolata (26/11/2026)

- `ArticoloPN.quote_deriva`, `quote_fuori_ultimo`, `analisi_il` (migrazione `produzione 0007`). `articoli.analizza(articolo)` li calcola con `cpk_peggiore` e `quote_non_capaci` da `analisi_pn`; `articoli.da_analizzare()` sceglie i P/N con analisi mai fatta o più vecchia dell'ultimo `letto_il`/`escluso_il`. Il giro chiama `aggiorna_cpk` sui P/N letti e poi sugli altri da aggiornare; `report_escludi` ricalcola il P/N. `cruscotto()` non chiama più `analisi_pn` (`analisi_pronta` falso = «in calcolo»).

### Database: indici, misure compresse, manutenzione (26/11/2026)

- `produzione 0008`: indici di copertura `prod_rcmm_pn_prog_cop` e `prod_rcmm_data` su `produzione_reportcmm`; tolti `pn` singolo, `programma_base`, `escluso`, `misuracmm.chiave`.
- `produzione 0009` (solo SQL Server, `atomic = False`): `produzione_misuracmm` con indice cluster `prod_mcmm_report_cl` (report_id, id) PAGE e `PK_produzione_misuracmm` non cluster; `UPDATE STATISTICS … WITH FULLSCAN`. Durata stimata in produzione 30-60 s: fare `migrate` con qcluster fermo.
- `produzione/manutenzione_db.py` + schedule `produzione_manutenzione_db` (03:10): statistiche (>10% modifiche, almeno 5.000), REORGANIZE 10-30%, REBUILD oltre 30% (indici con almeno 1.000 pagine).

### Statistica di processo (27/11/2026)

- `produzione/spc.py` (unico posto delle formule) e `static/produzione/js/spc.js` (stessa cosa per Analisi quote; `tests_spc.py` confronta i numeri con Node): σ di breve periodo MR̄/1,128 → Cp/Cpk; σ totale → Pp/Ppk; `indice` = min(Cpk, Ppk) per conteggi e classifiche; Weibull e percentili (ISO 22514-2) per le unilaterali; intervallo di Bissell e verdetto sul limite basso, «pochi dati» sotto 25; limiti I-MR; Nelson 1-8 + EWMA (λ 0,2, L 3, base = prima metà); rischio del prossimo pezzo (EWMA + pendenza della deriva, normale o coda Weibull); punti di cambio (segmentazione binaria, penalità 3σ²ln n, salto ≥ 1σ); famiglie (|r| ≥ 0,7 su ≥ 15 report); Kruskal-Wallis; ripetibilità da rimisure entro 2 giorni senza fuori nella prima.
- `report_cmm_indice.statistiche` e `analisi_pn` (chiave cache `prod_cmm_analisi3`) usano `spc`; `deriva()` dà anche `pezzi_min`/`pezzi_max`.
- Migrazione `produzione 0010`: tabella `produzione_quotacapacita` (una riga per quota: Cpk, Ppk, indice, verdetto, metodo, rischio, deriva, fuori, famiglia, `caratteristica` = nome senza numerazione) e `ArticoloPN.rischio_max`, `salute`; le riempie `articoli.analizza`. Quote CMM legge da qui (salute, rischio, quote da guardare, `?car=`).
- Anomalie da aprire (`report_cmm_pagine.anomalie_da_aprire`, solo report con data negli ultimi 30 giorni) e avviso «Anomalia da aprire» con il link a `apertura_segnalazione?op_id&report_cmm`. `core.ordini_produzione.anomalie_del_seriale`: confronto senza separatori anche in SQL e `aperta` corretta (prima «0»/«False» testuali contavano come chiuse).

### Quote CMM senza calcoli nella richiesta (27/11/2026)

- `quote_da_guardare_tutte` scorre `QuotaCapacita` (flag fuori/deriva/indice < 1,33, ordinate come `quote_critiche`) e tiene i P/N scelti, senza `pn IN (…)`; `cruscotto()` prende l'ultimo report con `ROW_NUMBER()` e legge tutto `ArticoloPN` filtrando in Python. La richiesta non chiama mai `analisi_pn` (test con `assert_not_called`).

## Permessi (ACL v2)

| Codice | Default | Rotte |
|---|---|---|
| `produzione.op.view` | tutti i ruoli | elenco, scheda, pn_elenco, pn_scheda, pn_quote, api_quote, api_quote_candidati, api_quote_nota(_elimina), quote_cruscotto, quote_pdf, pn_leggi_report, report_cmm, report_cmm_pdf, guida |
| `produzione.documenti.manage` | admin | documento, documento_elimina |
| `produzione.impostazioni.manage` | admin | impostazioni |
| `produzione.op.manage` | admin | op_nuovo (risponde in JSON 401/403/400) |
| `produzione.quote.manage` | admin | report_escludi, api_quote_alias(_elimina) |

Nella matrice di Ruoli e permessi il modulo è «Ordini di produzione» (area Produzione, `produzione/registro_permessi.py`): «Vedere» accende `op.view`, «Creare/Modificare/Cancellare» accendono `documenti.manage` e `op.manage` (capacità forzate a modifica), «Impostazioni del modulo» accende `impostazioni.manage` (`core/permessi/impostazioni.py`). Dopo il deploy: «Sincronizza i permessi delle pagine».

## Tabelle

`produzione_tipodocumento`, `produzione_documentoop` (migrazioni `0001-0002`); `produzione_cartellareportcmm`, `produzione_reportcmm`, `produzione_misuracmm` (migrazione `0003`); `produzione_notaquotacmm`, `produzione_aliasquotacmm`, `produzione_impostazioniquotecmm` e i campi di esclusione/avviso di `produzione_reportcmm` (migrazione `0004`, che segna come già avvisati i report esistenti). Legge `ordini_produzione` e `anomalie`.

## Deploy

`migrate produzione`, `collectstatic` (`produzione/css/produzione.css`, `produzione/js/protocollo.js`, `produzione/css/nuovo_op.css`, `produzione/js/nuovo_op.js`, `produzione/js/analisi_quote.js`, `produzione/css/analisi_quote.css`, bundle di Gestione anomalie), registrazione degli schedule (`produzione_report_cmm_giro`), riavvio di qcluster. L'utente del portale e quello di qcluster devono poter **leggere** `\\novisrv\Area Controllo\Collaudo`.
