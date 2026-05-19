# Asset SharePoint Upload Review

Data: 2026-05-08

## Stato Implementato

- Upload documenti nelle schede macchine da lavoro per `Specifiche`, `Manuali`, `Interventi`.
- Validazione estensione, dimensione e MIME reale tramite `core.upload_mime`.
- Salvataggio locale nel portale come `AssetDocument`.
- Creazione automatica della cartella SharePoint, se `GRAPH_*` e `ASSETS_SHAREPOINT_*` sono configurati.
- Sync file su SharePoint tramite Microsoft Graph `PUT /drive/root:/path:/content`, solo quando l'utente sceglie la destinazione SharePoint.
- Scelta esplicita upload locale/SharePoint dalla card Documenti del dettaglio asset e dal form macchina.
- Link di fallback locale servito da route autenticata `/assets/documenti/<id>/download/`.

## Criticita Rilevate

- Il nome remoto SharePoint usava il nome originale e poteva sovrascrivere un file omonimo nella stessa categoria.
- Il fallback locale in template puntava a `.file.url`, quindi a `/media/`, invece di passare da una view autenticata.
- La sanitizzazione filename non veniva riusata come nome effettivo salvato e sincronizzato.
- La sync SharePoint resta sincrona nella request: su rete lenta l'utente attende e il portale salva comunque localmente con warning.
- Non esiste ancora una coda di retry per errori Graph temporanei.

## Correzioni Applicate

- Normalizzazione del nome file prima del salvataggio.
- Blocco dei file vuoti sugli upload documenti asset.
- Nome remoto SharePoint univoco con timestamp e ID documento.
- Nuova route `asset_document_download` con audit log sintetico e senza path fisici.
- Template e dettaglio asset aggiornati per usare il download autenticato quando manca `sharepoint_url`.

## Proposta Locale

Per una modalita locale piu robusta, portare `AssetDocument.file` su storage privato `ASSETS_PRIVATE_ROOT`, come gia fatto per gli allegati completamento scadenze. Il modello puo mantenere la compatibilita leggendo i legacy da `MEDIA_ROOT`, ma i nuovi documenti non dovrebbero avere URL diretto pubblico.

Passi consigliati:

1. Aggiungere storage privato dedicato per `AssetDocument`.
2. Creare migration `AlterField(file=...)` con fallback legacy.
3. Aggiungere comando `migrate_asset_documents_private --apply --delete-source`.
4. Rendere opzionale una coda retry Graph, con stato `pending/synced/error` sul documento.
5. Valutare un task periodico che risincronizzi documenti locali non ancora presenti in SharePoint.
