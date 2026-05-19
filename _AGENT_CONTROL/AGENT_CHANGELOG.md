# Agent Changelog

## 2026-05-19 - Codex

- Area: `hotfix`
- Richiesta: creare un nuovo pacchetto hotfix per la correzione metadati SharePoint sulle cartelle asset.
- File modificati/creati: `hotfix/hotfix-v1.0.1-20260519_120132.zip`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non era presente nella workspace.
- Motivo tecnico: predisporre un pacchetto overlay leggero applicabile dal Release Manager senza nuova release completa.
- Modifica: creato zip hotfix con `django_app/assets/views.py`.
- Impatto previsto: applicando lo zip al release attivo viene distribuito il fix che valorizza i metadati SharePoint anche sulle cartelle asset.
- Rischi residui: il pacchetto contiene il file runtime completo `django_app/assets/views.py` nello stato corrente della workspace; non include test o documentazione.
- Test/check: contenuto zip verificato (`django_app/assets/views.py`); SHA256 `C53140A7AC88B1845F8D76B616577CF78E06A41D96A783EE58BD4110488F3880`.
- Note: i file di controllo sessione `_AGENT_CONTROL/ACTIVE_SESSION.md`, `WORK_LOCKS.md`, `CRITICAL_FILES.md`, `CRITICAL_CHANGE_REQUESTS.md` non erano presenti all'avvio.

- Area: `django_app/assets`
- Richiesta: colonne metadato SharePoint create ma non compilate sulle cartelle asset.
- File modificati: `django_app/assets/views.py`, `django_app/assets/tests.py`, `django_app/CHANGELOG.md`, `CHANGELOG.md`, `README.md`, `docs/assets/SHAREPOINT_CARTELLE_ASSET_GUIDE.md`, `_AGENT_CONTROL/AGENT_CHANGELOG.md`, `session_checkpoint.md`.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non era presente nella workspace.
- Motivo tecnico: i metadati venivano applicati solo ai file documento caricati su SharePoint, mentre le righe visibili sotto `ASSET CN` sono cartelle `driveItem` e restavano senza PATCH su `listItem/fields`.
- Modifica: `_ensure_sharepoint_folder` restituisce anche l'id del driveItem; `_ensure_asset_sharepoint_folder` applica i metadati anche alla cartella asset e alle tre sottocartelle categoria usando helper condivisi per il PATCH campi.
- Impatto previsto: nuovi salvataggi/sync SharePoint asset valorizzano `AssetTag`, categoria, produttore, modello, matricola, stato, reparto e tipo cartella anche sulle cartelle, non solo sui file.
- Rischi residui: cartelle gia create prima della patch restano vuote finche l'asset non viene risalvato o non viene rieseguito un flusso che richiama `_ensure_asset_sharepoint_folder`; l'operazione resta best-effort e dipende dai permessi Graph sui campi lista.
- Test/check: `python django_app\manage.py test assets.tests.AssetsRoutingTests.test_sharepoint_upload_uses_relative_subfolders assets.tests.AssetsRoutingTests.test_sharepoint_document_metadata_includes_asset_fields assets.tests.AssetsRoutingTests.test_sharepoint_folder_metadata_includes_asset_fields assets.tests.AssetsRoutingTests.test_ensure_asset_sharepoint_folder_applies_metadata_to_folders --settings=config.settings.test --verbosity 2` OK.
- Note: i file di controllo sessione `_AGENT_CONTROL/ACTIVE_SESSION.md`, `WORK_LOCKS.md`, `CRITICAL_FILES.md`, `CRITICAL_CHANGE_REQUESTS.md` non erano presenti all'avvio.

- Area: `django_app/assets`
- Richiesta: QR delle etichette asset verso la cartella SharePoint relativa.
- File modificati: `django_app/assets/views.py`, `django_app/assets/tests.py`, `django_app/CHANGELOG.md`, `README.md`, `docs/assets/SHAREPOINT_CARTELLE_ASSET_GUIDE.md`.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non era presente nella workspace.
- Motivo tecnico: rendere `/assets/view/<id>/qr-label/` coerente con l'uso operativo delle label fisiche, puntando alla cartella SharePoint dell'asset quando disponibile.
- Modifica: default target QR da `detail` a `sharepoint` nella view `asset_qr_label`, con fallback gia esistente alla scheda asset se `sharepoint_folder_url` manca; `?target=detail` continua a forzare la scheda.
- Impatto previsto: le nuove label generate senza querystring aprono direttamente la cartella SharePoint dell'asset; nessuna migrazione DB.
- Rischi residui: asset senza `sharepoint_folder_url` continuano a puntare alla scheda portale finche Graph/sync non valorizza l'URL cartella.
- Test/check: `python django_app\manage.py test assets.tests.AssetsRoutingTests.test_asset_qr_label_returns_pdf assets.tests.AssetsRoutingTests.test_asset_qr_label_defaults_to_sharepoint_folder_when_available assets.tests.AssetsRoutingTests.test_asset_qr_label_detail_target_still_points_to_asset_detail --settings=config.settings.test --verbosity 2` OK.
- Note: i file di controllo sessione `_AGENT_CONTROL/ACTIVE_SESSION.md`, `WORK_LOCKS.md`, `CRITICAL_FILES.md`, `CRITICAL_CHANGE_REQUESTS.md` non erano presenti all'avvio.

## 2026-05-19 - Codex

- Area: `django_app/assets`
- Richiesta: upload su SharePoint dell'intera cartella selezionata dalla card Documenti asset, mantenendo eventuali sottocartelle.
- File modificati: `django_app/assets/views.py`, `django_app/assets/templates/assets/pages/asset_detail.html`, `django_app/assets/tests.py`, `README.md`, `CHANGELOG.md`, `docs/assets/SHAREPOINT_CARTELLE_ASSET_GUIDE.md`.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non era presente nella workspace all'avvio.
- Motivo tecnico: l'input `webkitdirectory` invia una lista di file; senza salvare il `webkitRelativePath` lato backend l'upload Graph appiattiva tutto nella sola sottocartella categoria.
- Modifica: il template invia hidden field con percorso relativo per ciascun file selezionato da cartella; `_validate_asset_document_uploads` conserva il percorso relativo sanitizzato; `_upload_asset_document_to_sharepoint` crea la cartella categoria piu eventuali sottocartelle relative prima del `PUT` Graph.
- Impatto previsto: su SharePoint i file caricati da "Carica cartella" finiscono in `ASSET CN/<tag>/<categoria>/<cartella selezionata>/<subfolder>/...`; resta il fallback locale `AssetDocument`.
- Rischi residui: i nomi remoti dei file continuano a usare il prefisso univoco timestamp/id gia esistente per evitare sovrascritture; la struttura cartella e preservata, il nome fisico del file SharePoint non e identico al nome sorgente.
- Test/check: `python django_app\manage.py test assets.tests.AssetsRoutingTests.test_asset_detail_upload_can_target_local_archive assets.tests.AssetsRoutingTests.test_asset_detail_folder_upload_keeps_sharepoint_relative_path assets.tests.AssetsRoutingTests.test_sharepoint_upload_uses_relative_subfolders --settings=config.settings.test` OK; `python django_app\manage.py check --settings=config.settings.test` OK.
- Note: i file di controllo sessione `_AGENT_CONTROL/ACTIVE_SESSION.md`, `WORK_LOCKS.md`, `CRITICAL_FILES.md`, `CRITICAL_CHANGE_REQUESTS.md` non erano presenti all'avvio.

## 2026-05-19 - Codex

- Area: `hotfix`
- Richiesta: creare pacchetto hotfix per la correzione upload cartella asset SharePoint.
- File pacchetto: `hotfix/hotfix-v1.0.1-20260519_115839.zip`.
- Contenuto pacchetto: `django_app/assets/views.py`, `django_app/assets/templates/assets/pages/asset_detail.html`.
- File critici modificati: nessuno rilevato; `_AGENT_CONTROL/CRITICAL_FILES.md` non era presente nella workspace.
- Motivo tecnico: distribuire rapidamente la fix runtime senza release completa, includendo solo backend e template necessari alla produzione.
- Impatto previsto: applicando il pacchetto sul release attivo, "Carica cartella" preserva sottocartelle relative su SharePoint.
- Rischi residui: creato anche `hotfix/hotfix-v1.0.1-20260519_115759.zip` durante un primo tentativo, ma contiene entry appiattite (`views.py`, `asset_detail.html`) e non va usato; il pacchetto valido e verificato e quello `115839`.
- Test/check: verifica zip OK con entry `django_app/...` complete.
- Note: nessuna migrazione, dipendenza o collectstatic richiesti per questa fix.
