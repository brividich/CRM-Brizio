# Presenti in azienda (`presenti`)

URL: `/presenti/` · menu **Persone › Presenti in azienda** · guida in-app «? Guida» (`/presenti/guida/`).

Porta nel portale lo script `report_presenze.py` (diskstation, `UTLIC_ReportPresenze`) che generava ogni ora
`CN-PRESENZE.pdf` dalle timbrature Solari e lo caricava su SharePoint.

## Funzioni

| Pagina | URL | Cosa fa |
|---|---|---|
| Presenti adesso | `/presenti/` | Lista live (HTMX ogni 30 s): turno, matricola, nome, reparto, ora di entrata, incarichi di sicurezza; contatori per incarico; ricerca e filtri; PDF (senza ora di entrata) |
| Esterni in azienda | `/presenti/` (sotto i dipendenti) | Visitatori, ditte e docenti con visita `CHECKEDIN` nel GuestPortal (`fornitori.guestportal.presenti_ora`): nome, azienda, tipo, referente, entrata, badge; anche nel PDF. Con `RECEPTION_NATIVA` e permesso `reception.pannello.manage`: «+ Registra chi è dentro» (`/reception/presenti/registra/`, fornitore o ospite, nessuna mail al referente) e «Come fornitore» per visitatore (`/reception/presenti/<visita>/fornitore/`, binding reception 0010) |
| Andamento per reparto | `/presenti/andamento/` | Persone dentro a ogni ora (5-22) per reparto dell'anagrafica, oggi; colonna «Adesso» = `stato()` della lista; solo numeri; cache 5 min (`services.andamento`, `solari.leggi_timbrature_giorno`) |
| Appello di evacuazione | `/presenti/appello/` | Fotografia dei presenti all'avvio, dipendenti **ed esterni** (id visita col segno meno, nessuna migrazione); spunte «contato» condivise fra più persone (aggiornamento ogni 3 s); chiusura; PDF con colonna CONTATO; storico; **verbale** (`appello/<pk>/verbale/`, PDF `verbale/pdf/`): tempi 50/90/100 %, chi ha contato, non contati, osservazioni (`Appello.osservazioni`, migrazione 0002), firme; **elimina** solo esercitazioni (`appello/<pk>/elimina/`, chi l'ha avviata o `presenti.impostazioni.manage`) |
| Uscite non timbrate | `/presenti/uscite/` | Giornate con timbrature che non tornano, controllate tutte (`solari.analizza_giornata`): uscita mancante, verso sbagliato, due E/U di fila; turni a cavallo della mezzanotte esclusi (16 h); colonna problema + sequenza del giorno; notifica e mail al capo **solo per le uscite mancanti** (gli altri problemi di timbratura solo in pagina); il capo vede la sua squadra, chi ha «tutti» l'azienda |
| Impostazioni | `/presenti/impostazioni/` | Pubblicazione PDF su SharePoint, avviso mattutino delle uscite |

Pallino **«In azienda»** (`{% load presenti_tags %}{% pallino_presenza <legacy_id> %}`) accanto al nome in
Anagrafica: elenco dipendenti, scheda dipendente, organigramma ad albero (`{% presenti_ids as pres_ids %}` una volta per pagina,
`ids=pres_ids stile=False` nei nodi inclusi con `only`, `{% pallino_presenza_stile %}`) e «Il mio team». Anche nella ricerca globale (Ctrl+K): `api/search/` aggiunge
`presenza` (true/false; null se Solari non risponde o `/presenti/` non è visibile) ai risultati «dipendente».

## Dati

- **Fonte**: SQL Server Solari, sola lettura (`presenti/solari.py`): `ANAGRAFICO_DATI` (db anagrafico) +
  `TIMBRATURE` e `ASSELEMGEN` (db timbrature). Presente = ultima timbratura di oggi con `VERSOV='E'`, oppure ultime due `U` di fila
  (rientro col tasto sbagliato, `verifica`), oppure entrata ieri dalle 18 senza timbrature oggi entro 16 h (turno di notte).
  Turno «N» = elemento `SOLARI_TURNO_NORMALE_ELEM` (34013).
- **Una lettura al minuto per tutto il server**: `services.stato()` mette la fotografia nella cache condivisa
  (`DURATA_CACHE = 60` s; 20 s dopo un errore). La query costa ~0,1-0,5 s su ~1 milione di righe.
- **Esterni**: GuestPortal (MySQL, sola lettura, stesse chiavi `GUESTPORTAL_DB_*` di Accessi esterni), letti
  insieme alle timbrature nella stessa fotografia di `services.stato()` (chiavi `esterni`, `errore_esterni`);
  se Solari è giù gli esterni si leggono comunque. Visibili a chi vede la lista presenti.
- **Aggancio all'anagrafica** per codice fiscale (`DipendenteAnagraficaCivile.codice_fiscale`).
- **Incarichi di sicurezza**: ruoli in essere dell'ambito ISO 45001 (`DipendenteRuoloOperativo`).
- Tabelle proprie: `presenti_appello`, `presenti_appellospunta`, `presenti_avvisouscitamancante`
  (migrazione `presenti 0001`). Le timbrature non vengono copiate.

## Permessi (ACL v2, `presenti/acl_bootstrap.py`)

| Codice | Default |
|---|---|
| `presenti.lista.view` | tutti i ruoli |
| `presenti.appello.manage` | tutti i ruoli |
| `presenti.uscite.view` | tutti i ruoli (filtrato sulla squadra) |
| `presenti.uscite.tutte` | admin |
| `presenti.impostazioni.manage` | admin |

## Task django-q (`automazioni/schedules.py`)

- `presenti_pubblica_pdf` — ogni 30 minuti; no-op se la pubblicazione è spenta. Non sovrascrive il file se Solari non risponde.
- `presenti_avvisi_uscite` — lun-sab 07:30; ultimi 3 giorni, un messaggio (notifica + mail) per capo, una volta per giornata.

## Setup

`.env` del server:

```
SOLARI_DB_SERVER=<host\istanza>
SOLARI_DB_USER=<login sola lettura>
SOLARI_DB_PASSWORD=<...>
SOLARI_DB_DRIVER={ODBC Driver 18 for SQL Server}
SOLARI_DB_ENCRYPT=1
SOLARI_DB_TRUST_CERT=1
SOLARI_DB_ANAGRAFICO=dbstartPRV
SOLARI_DB_TIMBRATURE=dbstartBIZ
SOLARI_TURNO_NORMALE_ELEM=34013
```

Con ODBC Driver 18 servono `SOLARI_DB_ENCRYPT=1` e `SOLARI_DB_TRUST_CERT=1`: l'istanza Solari ha un certificato autofirmato (verificato il 04/11/2026, senza dà «Catena di certificati emessa da una autorità non attendibile»). Con Driver 17 le due chiavi si possono lasciare vuote.

Login consigliato sul SQL Solari: utente dedicato con solo `db_datareader` sui due database (lo script usava `sa`).

Dopo il deploy: `migrate`, `setup_q_schedules`, riavvio qcluster; import una tantum degli incarichi dal vecchio
`config.ini`: `manage.py importa_incarichi_presenze --ini <config.ini>` (anteprima) poi `--apply`
(crea «Addetto Primo Soccorso» e «RLS» nell'ambito ISO 45001). Per dismettere lo script: attivare la
pubblicazione in Impostazioni, verificare «Ultima pubblicazione», poi disattivare l'attività pianificata dell'exe.

Numeri di badge da Solari: `manage.py importa_badge_solari` (anteprima), `--apply` per i mancanti, `--sovrascrivi` anche per i diversi. Prende l'ultimo `TIMBRATURE.BADGE` di ogni persona, aggancio per codice fiscale; lo stesso numero su due persone non si importa; nell'output mai i numeri.

## Limiti noti

- Un turno a cavallo della mezzanotte: chi entra la sera e timbra l'uscita il giorno dopo compare fra i presenti
  solo fino a mezzanotte e fra le uscite non timbrate del giorno di entrata (stessa logica dello script).
- L'appello comprende solo chi timbra: visitatori e fornitori dal registro accessi (GuestPortal).
