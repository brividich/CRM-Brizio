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
- **Impostazioni** (`/produzione/impostazioni/`): tipi di documento (`TipoDocumento`), seminati dalla migrazione `0002`.

Un documento cita l'OP col suo titolo, come anomalie e FAI. FAI, programmi e KICK-OFF rispettano i permessi del modulo KICK-OFF.

## Permessi (ACL v2)

| Codice | Default | Rotte |
|---|---|---|
| `produzione.op.view` | tutti i ruoli | elenco, scheda, pn_elenco, pn_scheda, guida |
| `produzione.documenti.manage` | admin | documento, documento_elimina |
| `produzione.impostazioni.manage` | admin | impostazioni |
| `produzione.op.manage` | admin | op_nuovo (risponde in JSON 401/403/400) |

Nella matrice di Ruoli e permessi il modulo è «Ordini di produzione» (area Produzione, `produzione/registro_permessi.py`): «Vedere» accende `op.view`, «Creare/Modificare/Cancellare» accendono `documenti.manage` e `op.manage` (capacità forzate a modifica), «Impostazioni del modulo» accende `impostazioni.manage` (`core/permessi/impostazioni.py`). Dopo il deploy: «Sincronizza i permessi delle pagine».

## Tabelle

`produzione_tipodocumento`, `produzione_documentoop` (migrazioni `0001-0002`). Legge `ordini_produzione` e `anomalie`.

## Deploy

`migrate produzione`, `collectstatic` (`produzione/css/produzione.css`, `produzione/css/nuovo_op.css`, `produzione/js/nuovo_op.js`).
