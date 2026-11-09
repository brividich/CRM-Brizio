# Ordini di produzione (`produzione`)

URL: `/produzione/`. Voce «Ordini di produzione» nel menu Produzione.

## Cosa fa

Ogni OP con i suoi documenti di produzione. Gli OP sono la tabella legacy `ordini_produzione`, la stessa di Gestione anomalie: la sezione la legge (`core/ordini_produzione.py`) e non la copia. Gli OP nuovi si creano da qui con «+ Nuovo OP» (pannello laterale, `produzione/_nuovo_op.html` + `produzione/js/nuovo_op.js`, POST JSON `/produzione/op/nuovo/`), dalla scheda FAI (stesso pannello, l'OP creato va nel campo OP con l'evento `op:creato`) o da Gestione anomalie: tutti usano `anomalie.views.crea_op_da_dati`, con il controllo del titolo già esistente in `produzione/nuovo_op.py`.

- **Elenco** (`/produzione/`): OP dal più recente con P/N, capocommessa, CAR, stato, numero di documenti, FAI e anomalie aperte; ricerca per OP, P/N, capocommessa o CAR, filtro per stato, 100 per pagina.
- **Scheda** (`/produzione/op/<id>/`, id della tabella `ordini_produzione`):
  - documenti registrati (`DocumentoOP`: tipo, titolo o numero, revisione, data, cartella o file di rete, note);
  - FAI del Registro FAI: prima quelli che citano l'OP, poi gli altri del P/N; «Nuovo FAI per questo OP» apre `tasks:fai_nuovo?op=&pn=`;
  - programmi CAM e CMM delle righe KICK-OFF dello stesso P/N;
  - anomalie (totale e aperte, stesso legame di Gestione anomalie: id SharePoint o titolo) con link a `/gestione-anomalie?op=`;
  - KICK-OFF del P/N e altri OP dello stesso P/N.
- **Impostazioni** (`/produzione/impostazioni/`): tipi di documento (`TipoDocumento`), seminati dalla migrazione `0002`.

Un documento cita l'OP col suo titolo, come anomalie e FAI. FAI, programmi e KICK-OFF rispettano i permessi del modulo KICK-OFF.

## Permessi (ACL v2)

| Codice | Default | Rotte |
|---|---|---|
| `produzione.op.view` | tutti i ruoli | elenco, scheda, guida |
| `produzione.documenti.manage` | admin | documento, documento_elimina |
| `produzione.impostazioni.manage` | admin | impostazioni |
| `produzione.op.manage` | admin | op_nuovo (risponde in JSON 401/403/400) |

Nella matrice di Ruoli e permessi il modulo è «Ordini di produzione» (area Produzione, `produzione/registro_permessi.py`): «Vedere» accende `op.view`, «Creare/Modificare/Cancellare» accendono `documenti.manage` e `op.manage` (capacità forzate a modifica), «Impostazioni del modulo» accende `impostazioni.manage` (`core/permessi/impostazioni.py`). Dopo il deploy: «Sincronizza i permessi delle pagine».

## Tabelle

`produzione_tipodocumento`, `produzione_documentoop` (migrazioni `0001-0002`). Legge `ordini_produzione` e `anomalie`.

## Deploy

`migrate produzione`, `collectstatic` (`produzione/css/produzione.css`, `produzione/css/nuovo_op.css`, `produzione/js/nuovo_op.js`).
