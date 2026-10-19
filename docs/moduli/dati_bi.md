# `dati_bi` — dati per Power BI e API in sola lettura

Area **Piattaforma** · URL `/api/v1/` (solo applicazioni, nessuna pagina) · codice [`django_app/dati_bi/`](../../django_app/dati_bi/)

[← Catalogo moduli nel README](../../README.md#-catalogo-moduli)

## Sintesi

Porta i dati del portale fuori, in sola lettura, senza copiarli:

- **Viste SQL `bi_*`** per Power BI (connessione diretta al database con un utente in sola lettura).
- **API `/api/v1/`** per Power BI (connettore Web), Power Automate e gestionali: token per applicazione, ambiti, IP ammessi.

**Nessun dato personale nominativo**: niente assegnatari, richiedenti, nomi di dipendenti, email, testi liberi (descrizioni, note). Il personale (visite, formazione, qualifiche, contratti) esce solo come **conteggi per reparto e tipo**, e solo dall'API con l'ambito `personale_aggregato`.

## Viste SQL (Power BI)

Definite in `dati_bi/viste.py`, create dalla migrazione `dati_bi 0002` (`CREATE OR ALTER VIEW` su SQL Server). SQL portabile: i giorni alla scadenza si calcolano in Power BI.

| Vista | Contenuto |
|---|---|
| `bi_asset` | anagrafica asset: tag, numero interno, nome, tipo, categoria, reparto, costruttore, modello, matricola, stato, acquisto |
| `bi_ordini_lavoro` | OdL: asset, tipo, priorità, stato, origine, titolo, date (apertura, inizio, chiusura, scadenza), attesa, esito, minuti intervento e fermo, costi, contratto, fornitore |
| `bi_scadenze_asset` | una riga per scadenza: `fonte` = `amministrativa` / `licenza` / `contratto` / `verifica_impianto`, titolo, tipo, asset, reparto, scadenza, preavviso |
| `bi_ticket` | numero, tipo, categoria, priorità, stato, sicurezza, asset, fermo macchina, date (apertura, presa in carico, primo intervento, chiusura, risoluzione prevista) |
| `bi_dpi_consegne` | consegne DPI: richiesta, stato, categoria, reparto, quantità, consegna, scadenza stimata, `in_essere` (1 = non sostituita), firma ricevuta |
| `bi_capa` | azioni CAPA: tipo, stato, origine, reparto, scadenza, apertura, chiusura, verifica |

Comandi:

```powershell
python manage.py bi_viste                   # righe per vista (controllo)
python manage.py bi_viste --applica         # ricrea le viste (dopo un ripristino o modifiche a mano)
python manage.py bi_viste --sql             # stampa l'SQL
python manage.py bi_viste --grant <login>   # GRANT SELECT per l'utente SQL di Power BI
```

Messa in opera (DBA): creare un login/utente SQL dedicato in sola lettura (o un gruppo AD), poi eseguire i GRANT stampati da `--grant`. Basta il permesso sulle viste: le tabelle sotto restano invisibili a quell'utente (catena di ownership `dbo`). Una modifica futura alle viste va in una nuova migrazione che richiama `crea_viste`.

## API `/api/v1/`

Solo GET, JSON, paginazione `?limit=` (max 500) e `?offset=`; risposte `{"items": [...], "count": N}`.

| Endpoint | Ambito | Contenuto |
|---|---|---|
| `GET /api/v1/stato/` | — | verifica del token: nome applicazione, ambiti, ora del server |
| `GET /api/v1/asset/?reparto=&stato=` | `asset` | anagrafica asset |
| `GET /api/v1/ordini-lavoro/?dal=&al=&stato=` | `manutenzione` | OdL (date ISO `AAAA-MM-GG` sulla data di apertura) |
| `GET /api/v1/scadenze/?fonte=&stato=` | `scadenze` | voci dello Scadenzario globale per `asset`, `impianti`, `rentri`, `dpi`, `capa`; `stato` = `scaduta` / `entro_30` / `entro_60` / `entro_90`. DPI senza nome del dipendente, CAPA senza titolo libero |
| `GET /api/v1/scadenze/riepilogo/` | `scadenze` (+ `personale_aggregato` per l'HR) | conteggi per fonte, tipo, reparto e stato |

Le scadenze vengono dagli stessi provider della pagina `/scadenze` (`dashboard/scadenze_providers.py`): stessi numeri, orizzonte 90 giorni.

Sicurezza:

- `Authorization: Bearer <token>`; a DB solo l'hash SHA-256 (`ApiClient`), confronto `hmac.compare_digest`; token assente/errato/disattivato = **401** JSON.
- Client IP in `DATI_API_ALLOWED_IPS` (IP o CIDR, default solo loopback); fuori = **403** JSON. Ambito non concesso = **403**.
- Prefisso `/api/v1/` in `MIDDLEWARE_EXEMPT_PREFIXES` (chiama una macchina, niente sessione): l'unica protezione è in `dati_bi/api.py`. **Solo rete interna, mai su Entra Application Proxy.**
- Schema OpenAPI `GET /api/v1/openapi.json` solo per amministratori collegati (niente pagina Swagger: la CSP non carica script esterni).

Gestione delle applicazioni:

```powershell
python manage.py dati_api_client crea "Power BI direzione" --ambito scadenze --ambito manutenzione --ambito asset
python manage.py dati_api_client elenco
python manage.py dati_api_client ambiti "Power BI direzione" --ambito scadenze --ambito personale_aggregato
python manage.py dati_api_client rigenera "Power BI direzione"
python manage.py dati_api_client disattiva "Power BI direzione"
```

Il token si stampa una volta sola. L'admin Django (`Applicazioni API dati`) mostra elenco, ambiti, ultimo accesso e permette di disattivare; non crea token.

Power BI, connettore Web: URL `https://<portale>/api/v1/scadenze/?limit=500`, intestazione `Authorization` = `Bearer <token>` (Opzioni avanzate → Parametri intestazione richiesta HTTP); per più di 500 righe usare `offset`.

## Note di rilascio

- 10/2026 — prima versione: 6 viste `bi_*`, API v1 (stato, asset, ordini di lavoro, scadenze, riepilogo), comandi `bi_viste` e `dati_api_client`. Migrazioni `dati_bi 0001-0002`.
