# Presenti in azienda (`presenti`)

URL: `/presenti/` · menu **Persone › Presenti in azienda** · guida in-app «? Guida» (`/presenti/guida/`).

Porta nel portale lo script `report_presenze.py` (diskstation, `UTLIC_ReportPresenze`) che generava ogni ora
`CN-PRESENZE.pdf` dalle timbrature Solari e lo caricava su SharePoint.

## Funzioni

| Pagina | URL | Cosa fa |
|---|---|---|
| Presenti adesso | `/presenti/` | Lista live (HTMX ogni 30 s): turno, matricola, nome, reparto, ora di entrata, incarichi di sicurezza; contatori per incarico; ricerca e filtri; PDF |
| Appello di evacuazione | `/presenti/appello/` | Fotografia dei presenti all'avvio; spunte «contato» condivise fra più persone (aggiornamento ogni 3 s); chiusura; PDF con colonna CONTATO; storico |
| Uscite non timbrate | `/presenti/uscite/` | Giornate con ultima timbratura in entrata; il capo vede la sua squadra, chi ha «tutti» l'azienda |
| Impostazioni | `/presenti/impostazioni/` | Pubblicazione PDF su SharePoint, avviso mattutino delle uscite |

Pallino **«In azienda»** (`{% load presenti_tags %}{% pallino_presenza <legacy_id> %}`) accanto al nome in
Anagrafica: elenco dipendenti e scheda dipendente.

## Dati

- **Fonte**: SQL Server Solari, sola lettura (`presenti/solari.py`): `ANAGRAFICO_DATI` (db anagrafico) +
  `TIMBRATURE` e `ASSELEMGEN` (db timbrature). Presente = ultima timbratura di oggi con `VERSOV='E'`.
  Turno «N» = elemento `SOLARI_TURNO_NORMALE_ELEM` (34013).
- **Una lettura al minuto per tutto il server**: `services.stato()` mette la fotografia nella cache condivisa
  (`DURATA_CACHE = 60` s; 20 s dopo un errore). La query costa ~0,1-0,5 s su ~1 milione di righe.
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
SOLARI_DB_DRIVER={ODBC Driver 17 for SQL Server}
SOLARI_DB_ANAGRAFICO=dbstartPRV
SOLARI_DB_TIMBRATURE=dbstartBIZ
SOLARI_TURNO_NORMALE_ELEM=34013
```

Login consigliato sul SQL Solari: utente dedicato con solo `db_datareader` sui due database (lo script usava `sa`).

Dopo il deploy: `migrate`, `setup_q_schedules`, riavvio qcluster; import una tantum degli incarichi dal vecchio
`config.ini`: `manage.py importa_incarichi_presenze --ini <config.ini>` (anteprima) poi `--apply`
(crea «Addetto Primo Soccorso» e «RLS» nell'ambito ISO 45001). Per dismettere lo script: attivare la
pubblicazione in Impostazioni, verificare «Ultima pubblicazione», poi disattivare l'attività pianificata dell'exe.

## Limiti noti

- Un turno a cavallo della mezzanotte: chi entra la sera e timbra l'uscita il giorno dopo compare fra i presenti
  solo fino a mezzanotte e fra le uscite non timbrate del giorno di entrata (stessa logica dello script).
- L'appello comprende solo chi timbra: visitatori e fornitori dal registro accessi (GuestPortal).
