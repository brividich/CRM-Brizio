# `timbri` — report timbrature

Area **HR & Workflow** · URL `/timbri/` · codice [`django_app/timbri/`](../../django_app/timbri/)

[← Catalogo moduli nel README](../../README.md#-catalogo-moduli)

## Sintesi

Report timbrature da DB legacy, registro, immagini badge

## Dettaglio

Lettura e reporting timbrature dal sistema di rilevazione presenze esterno.

- **5 modelli**: OperatoreTimbri, RegistroTimbro, RegistroTimbroImmagine, TimbriImportIssue, TimbriUserPermOverride
- **Report** per periodo, operatore, reparto
- **UI allineata al design system HR** (10/2026): le pagine usano il guscio `fmd-` di anagrafica (`anagrafica/css/formazione_design.css`: intestazione con breadcrumb, tessere KPI `_kpi_tile.html`, pannelli, tabelle, paginatore) e il form-kit `hub-` per il form record (sezioni Identificazione / Consegna e stato / Note e firma, immagini a lato). I componenti propri del modulo (riga record con immagini timbro/firma/sigla, tab Timbri/Firme/Sigle, griglia dati, anteprima espandibile, menu Report) stanno in `timbri/components/_timbri_ui.html`, con palette NOVICROM navy/cyan e tema scuro; i record attivi sono resi da `_records_attivi.html`, condiviso da scheda timbri e frammento in anagrafica. Il report stampabile usa la stessa palette. Funzionamento, view e permessi invariati.
- **Index con preview espansa**: card per ogni record attivo con le tre immagini (TIMBRO / FIRMA / SIGLA), bottoni **Copia** (appunti) e **Scarica** (PNG via `?download=1`) gated per permesso. Ricerca live con debounce 280ms su `q`; reparto e qualifica ricaricano subito; la paginazione conserva tutti i filtri
- **Filtro per qualifica** nella lista dipendenti: accanto a Reparto, un menu **Qualifica** (opzioni = qualifiche distinte dei `RegistroTimbro`) mostra solo i dipendenti che possiedono almeno un registro di quella qualifica (match case-insensitive; incluso nel "Reset")
- **Permessi copia/download** ACL v2 (`timbri_copy`, `timbri_download`) con **override per-utente** (`TimbriUserPermOverride`, `granted` boolean) che vince sul ruolo: badge "Forzato ON"/"Forzato OFF" nella tab Permessi delle impostazioni. La view `serve_timbri_image` distingue inline (richiede `timbri_view`) da download forzato (richiede `timbri_download`), audit separato per ogni accesso
- **Impostazioni** semplificate: tab **Permessi** (toggle per ruolo/azione + override per utente), tab **Operazioni** (export CSV, reset tabella), tab **Log audit** (filtro per azione, badge colorati, ultimi 200 entry). La configurazione SharePoint/Graph è stata spostata fuori dalla pagina impostazioni del modulo
- **Import da SharePoint** (lista "Registro timbri") via Microsoft Graph dal pulsante "Importa da SharePoint" in `/timbri/impostazioni/?tab=import`: idempotente (dedup per `sharepoint_item_id`), non sovrascrive i record modificati nel portale e aggancia solo i dipendenti presenti in anagrafica (gli altri finiscono in `TimbriImportIssue`). Richiede `GRAPH_SITE_ID` e `GRAPH_LIST_ID_TIMBRI` nel `.env`. Import alternativo da CSV con `manage.py import_timbri_csv` o `manage.py import_timbri_da_share [--tutti]` (`--tutti` rimuove il filtro CNO per importare anche RICEVUTO/RIESAME/MESSA IN LAVORO). Per **rigenerare il CSV sorgente** dai record già presenti (es. travaso dev→prod quando il file originale è perso) usare `manage.py export_timbri_csv <path> [--only-active]`: produce un CSV con header simmetrici a `import_timbri_csv` e `sharepoint_item_id` come colonna `ID` (idempotenza preservata); il matching operatore viene rifatto sull'anagrafica della destinazione.
- **Import immagini timbro** (pulsante "Importa immagini (da libreria)"): gli allegati di lista SharePoint non sono scaricabili in app-only (Graph non li espone, REST `_api/web` rifiuta i token app-only, ACS ritirato). Workaround: un flow **Power Automate** copia gli allegati nella document library `Documenti/TimbriImport` (nome `{sharepoint_item_id}__<nome>.png`), che Graph legge col token app-only; l'import li aggancia ai record in ordine alle varianti TIMBRO/FIRMA/SIGLA. Env opzionali `GRAPH_DRIVE_ID_TIMBRI_IMPORT` e `GRAPH_FOLDER_TIMBRI_IMPORT`.
- **Immagini badge** associate a ogni timbratura per verifica (storage privato `TIMBRI_PRIVATE_ROOT` sovrascrivibile da `.env`, cifrate at rest)
- **Registro** con correzione manuale auditata
- **Timbri inline nella scheda dipendente**: dal tab «Timbri» di `/anagrafica/dipendenti/<id>/` i record (attivi con sub-tab timbri/firme/sigle + storico, immagini, copia, link al report) si vedono **dentro la scheda** senza uscire dal modulo anagrafica. Frammento reso da `timbri:operatore_embed` (`/timbri/anagrafica/<legacy_id>/embed/`) e caricato in **lazy via HTMX** al primo click sul tab; ACL `timbri_view` autoritativa lato server
