# Session Checkpoint

Data: 2026-05-19

Ultime voci viste/aggiunte in questa sessione:

- `_AGENT_CONTROL/AGENT_CHANGELOG.md` -> `2026-05-20 - Codex` (commit e push workspace su Git)
- `_AGENT_CONTROL/AGENT_CHANGELOG.md` -> `2026-05-20 - Codex` (Assenze SharePoint sync automatico riabilitato)
- `django_app/config/settings/base.py` -> `ASSENZE_SYNC_ON_PAGE_LOAD` default `True`
- `.env.example`, `django_app/.env.example` -> `ASSENZE_SYNC_ON_PAGE_LOAD=1`
- `django_app/setup_wizard/templates/setup_wizard/wizard.html`, `tools/setup-wizard.html`, `django_app/hub_tools/views.py` -> wizard/default configurazione assenze sync acceso
- `django_app/assenze/tests.py` -> test parser flag `ASSENZE_SYNC_ON_PAGE_LOAD`
- `CHANGELOG.md`, `django_app/CHANGELOG.md`, `README.md` -> documentato sync pull automatico assenze attivo di default
- Nota operativa ricorrente menu/topbar: se il menu torna con nomi legacy, duplicati, ordine errato o senza categorie padre, controllare prima il `.env` prod. La causa verificata il 2026-05-20 era `NAVIGATION_REGISTRY_ENABLED=0` e `NAVIGATION_LEGACY_FALLBACK_ENABLED=1`, che forzavano il fallback legacy `pulsanti`. Fix rapido:
  `NAVIGATION_REGISTRY_ENABLED=1`, `NAVIGATION_LEGACY_FALLBACK_ENABLED=0`, poi pulire cache/sessioni e `iisreset`.
- `_AGENT_CONTROL/AGENT_CHANGELOG.md` -> `2026-05-20 - Codex` (hotfix pulita `hotfix-v1.0.2-20260520_121751-qr-site-url-clean.zip`)
- `hotfix/hotfix-v1.0.2-20260520_121751-qr-site-url-clean.zip` -> creato da `C:\Users\l.bova\Desktop\views.py` sano con solo fix `SITE_URL` per QR
- `_AGENT_CONTROL/AGENT_CHANGELOG.md` -> `2026-05-20 - Codex` (hotfix `hotfix-v1.0.2-20260520_103701-qr-site-url.zip`)
- `hotfix/hotfix-v1.0.2-20260520_103701-qr-site-url.zip` -> creato per QR pubblici asset con base HTTPS canonica da `SITE_URL`
- `_AGENT_CONTROL/AGENT_CHANGELOG.md` -> `2026-05-20 - Codex` (QR pubblici asset con base HTTPS canonica da `SITE_URL`)
- `django_app/CHANGELOG.md` -> `[Unreleased]` -> `Link pubblici SharePoint per QR asset` (fix base canonica `SITE_URL` per etichette QR)
- `CHANGELOG.md` -> `[Unreleased]` -> `ASSETS - QR pubblici - Base HTTPS canonica da SITE_URL`
- `README.md` -> modulo Assets -> etichette QR usano `SITE_URL` per evitare link `http` dietro IIS/Waitress
- `django_app/assets/README.md` -> sezione `Link pubblici QR SharePoint` con nota `SITE_URL`
- `docs/assets/SHAREPOINT_CARTELLE_ASSET_GUIDE.md` -> sezione `Etichette QR` con base canonica `SITE_URL`
- `_AGENT_CONTROL/AGENT_CHANGELOG.md` -> `2026-05-19 - Codex` (SharePoint asset centralizzato in gestione server admin portale)
- `django_app/CHANGELOG.md` -> `[Unreleased]` -> `Link pubblici SharePoint per QR asset` (setup wizard hub centralizza `SHAREPOINT_ASSET_*`)
- `CHANGELOG.md` -> `[Unreleased]` -> `HUB TOOLS - Setup Wizard - SharePoint asset centralizzato in Gestione server`
- `README.md` -> Hub Tools / Microsoft 365 -> Graph/SharePoint asset gestito da `/admin-portale/hub/setup-wizard/#sec-graph`
- `django_app/assets/README.md` -> sezione `Link pubblici QR SharePoint` con pannello centrale hub + tab assets
- `docs/assets/SHAREPOINT_CARTELLE_ASSET_GUIDE.md` -> configurazione minima anche da pannello centrale hub setup wizard
- `_AGENT_CONTROL/AGENT_CHANGELOG.md` -> `2026-05-19 - Codex` (configurazione link pubblici SharePoint QR da administrator asset)
- `django_app/CHANGELOG.md` -> `[Unreleased]` -> `Link pubblici SharePoint per QR asset` (admin config `SHAREPOINT_ASSET_*`)
- `CHANGELOG.md` -> `[Unreleased]` -> `ASSETS - Admin - Configurazione link pubblici SharePoint da modulo assets`
- `README.md` -> modulo Assets -> feature flag e root/drive link pubblici gestibili da `/assets/impostazioni/`
- `django_app/assets/README.md` -> sezione `Link pubblici QR SharePoint` con gestione admin `SHAREPOINT_ASSET_*`
- `docs/assets/SHAREPOINT_CARTELLE_ASSET_GUIDE.md` -> configurazione QR pubblici dalla card SharePoint del modulo assets
- `_AGENT_CONTROL/AGENT_CHANGELOG.md` -> `2026-05-19 - Codex` (link pubblici SharePoint read-only per QR asset sotto `ASSET CN`)
- `django_app/CHANGELOG.md` -> `[Unreleased]` -> `Link pubblici SharePoint per QR asset`
- `CHANGELOG.md` -> `[Unreleased]` -> `ASSETS - SharePoint - Link pubblici QR sotto ASSET CN`
- `README.md` -> modulo Assets -> QR verso route pubblica tokenizzata e command `assets_ensure_public_share_links`
- `django_app/assets/README.md` -> sezione `Link pubblici QR SharePoint`
- `docs/assets/SHAREPOINT_CARTELLE_ASSET_GUIDE.md` -> route pubblica `/assets/public/<public_qr_token>/` e comandi riconversione
- `docs/ai/05_SECURITY_BOUNDARIES.md` -> prefisso pubblico ristretto `/assets/public/`
- `_AGENT_CONTROL/AGENT_CHANGELOG.md` -> `2026-05-19 - Codex` (link categoria dashboard Assets verso filtro `asset_category`)
- `django_app/CHANGELOG.md` -> `[Unreleased]` -> `Link categoria dashboard asset`
- `CHANGELOG.md` -> `[Unreleased]` -> `ASSETS - Dashboard - Link categoria inventario`
- `README.md` -> modulo Assets -> nota "Dashboard e categorie"
- `_AGENT_CONTROL/AGENT_CHANGELOG.md` -> `2026-05-19 - Codex` (specifiche tecniche asset solo compilate)
- `django_app/CHANGELOG.md` -> `[Unreleased]` -> `Specifiche tecniche asset solo compilate`
- `CHANGELOG.md` -> `[Unreleased]` -> `ASSETS - Dettaglio asset - Specifiche tecniche solo compilate`
- `README.md` -> modulo Assets -> nota "Specifiche tecniche pulite per categoria"
- `_AGENT_CONTROL/AGENT_CHANGELOG.md` -> `2026-05-19 - Codex` (hotfix modulo mancante `assets.services.sidebar_categories`)
- `hotfix/hotfix-v1.0.1-20260519_122243-sidebar-categories.zip` -> creato per crash import produzione da modulo sidebar categorie mancante
- `_AGENT_CONTROL/AGENT_CHANGELOG.md` -> `2026-05-19 - Codex` (hotfix `hotfix-v1.0.1-20260519_120132.zip`)
- `hotfix/hotfix-v1.0.1-20260519_120132.zip` -> creato per metadati cartelle asset SharePoint
- `django_app/CHANGELOG.md` -> `[Unreleased]` -> `Metadati SharePoint sulle cartelle asset`
- `CHANGELOG.md` -> `[Unreleased]` -> `ASSETS - SharePoint - Metadati sulle cartelle asset`
- `_AGENT_CONTROL/AGENT_CHANGELOG.md` -> `2026-05-19 - Codex` (metadati cartelle asset SharePoint)
- `django_app/CHANGELOG.md` -> `[Unreleased]` -> `QR label assets verso SharePoint`
- `_AGENT_CONTROL/AGENT_CHANGELOG.md` -> `2026-05-19 - Codex`
- `CHANGELOG.md` -> `[Unreleased]` -> `ASSETS - SharePoint - Upload cartella con sottocartelle preservate`
- `_AGENT_CONTROL/AGENT_CHANGELOG.md` -> `2026-05-19 - Codex` (upload cartella asset SharePoint)
- `_AGENT_CONTROL/AGENT_CHANGELOG.md` -> `2026-05-19 - Codex` (hotfix upload cartella asset SharePoint)
- `hotfix/hotfix-v1.0.1-20260519_115839.zip` -> pacchetto hotfix valido e verificato

Nota: i file di controllo sessione `_AGENT_CONTROL/ACTIVE_SESSION.md`, `WORK_LOCKS.md`, `CRITICAL_FILES.md` e `CRITICAL_CHANGE_REQUESTS.md` non erano presenti nella workspace all'avvio.
