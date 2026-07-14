# RECON — App `schede_sicurezza` (Fase A)

Ricognizione al 2026-07-09, prima di scrivere codice. Nomi e firme reali (non supposti).

## 1. DPI (`dpi/models.py`)

- **Nessun modello `DPICategoria`**: il nome reale è **`CategoriaDPI`** (`dpi.models.CategoriaDPI`).
  Campi: `nome`, `descrizione`, `immagine` (`ImageField(upload_to="dpi/categorie/")`, storage pubblico
  `MEDIA_ROOT` — non privato), `icona_emoji`, `is_active`, `order_index`. Property `immagine_url`.
- Gerarchia: `CategoriaDPI` → `TipoDPI` (FK categoria) → `ModelloDPI` (FK tipo) → `TagliaDPI` (FK modello).
  Per "DPI obbligatori" a livello di prodotto chimico ha senso agganciarsi a **`CategoriaDPI`**
  (granularità coerente con "occhiali, guanti, maschera…"), non a Tipo/Modello/Taglia.
- Richiesta DPI: `RichiestaDPI` (stato `StatoRichiesta`: INVIATA/APPROVATA/CONSEGNATA/RIFIUTATA/ANNULLATA),
  poi `ConsegnaDPI` (OneToOne). Nessun endpoint di "avvio richiesta con prefill categoria" via querystring:
  `nuova_richiesta` (`dpi/views.py:395`) carica tutte le categorie attive e risolve la selezione dal
  form POST (`_resolve_richiesta_catalog_selection`), non da GET params. Se in Fase 3 vorremo un link
  "richiedi questo DPI" dalla scheda mobile, andrà aggiunto un prefill via querystring in `dpi` (fuori
  scope Fase 1 — qui ci limitiamo a mostrare l'immagine, non a linkare la richiesta).
- URL: `dpi:nuova` → `/dpi/nuova/`.

## 2. Presa visione — `procedure_refresh`

- Modellazione reale: `ProcedureAssignment` (FK `campaign`, `revision`, `user` diretto su
  `settings.AUTH_USER_MODEL`, `status`, `read_confirmed_flag`, `read_confirmed_at`) +
  `ProcedureReadEvent` (append-only, `event_type`, `event_by`, `event_at`) per l'audit trail.
  Tutto è **ancorato a una `ProcedureCampaign`** (workflow di assegnazione con scadenza/manager),
  pensato per campagne di formazione su documenti MT/MTSI.
- **Decisione**: NON estendere `procedure_refresh`. Il meccanismo è troppo accoppiato al concetto di
  campagna/assegnazione manager→utente, mentre la presa visione SDS è **ad-hoc**: l'operatore scansiona
  il QR in reparto e conferma di aver letto la versione corrente, senza assegnazione preventiva.
  Si **specchia il pattern** (modello locale `PresaVisioneScheda`, FK diretta su
  `settings.AUTH_USER_MODEL` come fa `ProcedureAssignment.user` — non `legacy_anagrafica_id` — perché
  la vista è già gated da login Django) con vincolo di unicità (utente, scheda-versione) e
  storicizzazione implicita: una nuova `SchedaSicurezza` (nuova versione) genera nuove righe, quelle
  sulla versione precedente restano come storico.

## 3. Unità organizzativa (reparto)

- Modello reale: **`anagrafica.models.Reparto`** (non un modello dedicato in `assets`/`core`).
  Nota: `db_table = "anagrafica_areaaziendale"` per compatibilità storica — il nome tabella è legacy,
  il modello Python si chiama `Reparto`.
- `anagrafica.models.AreaAziendale` è la sotto-articolazione (FK a `Reparto`, opzionale) introdotta
  dalla recente inversione di gerarchia (vedi memoria `reparto_area_aziendale_inversione_done`).
- **Decisione**: FK `ProdottoChimico.reparto` → `anagrafica.Reparto` (unità di primo livello), non
  `AreaAziendale`. Motivazione: i prodotti chimici/SDS si gestiscono a livello di reparto (es. "UT",
  "Produzione"), coerente con la granularità con cui oggi si organizzano DPI e procedure. Se in futuro
  serve granularità più fine si aggiunge un FK opzionale ad `AreaAziendale` senza rompere lo schema.

## 4. Chiave dipendente/operatore

- `legacy_anagrafica_id` è la chiave usata da `anagrafica` (`DipendenteAnagraficaCivile`,
  `DipendenteAnagraficaAziendale`, `DipendenteQualifica`, ecc.) e da `dpi.RichiestaDPI` (denormalizzato,
  `richiedente_legacy_id`) per collegare record al dipendente legacy.
- `procedure_refresh`, il modulo di riferimento più vicino per "presa visione", usa invece **FK diretta
  su `settings.AUTH_USER_MODEL`** per `user`/`created_by`/ecc., perché opera su utenti già autenticati
  Django. **Decisione**: seguiamo lo stesso pattern di `procedure_refresh` per `PresaVisioneScheda`
  (FK diretta a `AUTH_USER_MODEL`), dato che la vista mobile richiede login. Nessun uso di
  `legacy_anagrafica_id` necessario in Fase 1.

## 5. ACL v2 — registrazione permesso e gating view

Pattern canonico osservato in `gestione_carichi_macchina/acl_bootstrap.py` (il modulo più recente,
preferito a `procedure_refresh/acl_bootstrap.py` che è ancora sul pattern legacy "Pulsante/Permesso"):

- `core.models.PermissionDefinition` (`code`, `module`, `label`, `description`, `is_active`) — il
  codice permesso, es. `schede_sicurezza.prodotto.view` / `.gestisci`.
- `core.models.RoutePermissionBinding` (`route_name`, `path_pattern`, `match_strategy`,
  `permission_id`, `source_app`, `priority`, `is_active`) — lega una URL name al permesso; necessario
  perché con `ACL_STRICT_CANONICAL=True` (attivo in prod, vedi memoria) il binding canonico **ha
  priorità sui permessi legacy**.
- `core.models.RolePermissionGrant` (`legacy_role_id`, `permission_id`, `enabled`) — grant di default
  per ruolo, CREATE-ONLY (non sovrascrive modifiche fatte da admin in `/admin-portale/acl-canonico/`).
- `core.models.NavigationItem` (+ `NavigationRoleAccess`) con `required_permission_code` per la voce
  di menu.
- Tutto orchestrato da `core.acl_bootstrap_base.run_bootstrap(...)`, chiamato da `apps.py::ready()`
  dell'app (pattern: `bootstrap_carichi_acl_endpoints()` chiamato via `AppConfig.ready`).
- **Gating a runtime in view**: `core.acl_v2.evaluate_permission_code_access(permission_code=...,
  legacy_user=..., django_user=request.user).get("allowed")` (vedi `gestione_carichi_macchina/
  views.py:_puo_modificare`). Fail-safe: se il sottosistema ACL non risponde, ricade su
  `request.user.is_authenticated` — mai fail-open su un default permissivo diverso.
- Il download PDF e la vista mobile devono avere **anche** il `RoutePermissionBinding`, non solo
  `@login_required`, altrimenti in prod con `ACL_STRICT_CANONICAL` restano scoperte (vedi memoria
  `acl_middleware_api_gate_paths`).

## 6. Navigation registry, context processor, layout

- Template base: **`core/base.html`** (`{% extends "core/base.html" %}`, usato da `dpi` e dalle altre
  app di dominio).
- Context processor attivi (da `TEMPLATES.OPTIONS.context_processors` in `config/settings/base.py`):
  `core.context_processors.legacy_nav`, `core.context_processors.app_meta`,
  `core.context_processors.ui_prefs_context`, `monitoring.context_processors.monitoring_ui`.
- Navigation: voce in area Sicurezza/Compliance registrata via `NavigationItem` (sezione `topbar` o
  sotto-sezione dedicata, coerente con `dpi`/`procedure_refresh`/`rilevazione_incidenti`).

## 7. App di riferimento per struttura lista+dettaglio HTMX

Combinazione di due riferimenti, per la parte più vicina concettualmente:

- **`procedure_refresh`** (`document_list` / `document_form` / `revision_form` in
  `procedure_refresh/views.py` + `procedure_refresh/templates/procedure_refresh/pages/`): pattern
  "documento con revisioni versionate, una corrente" — il più vicino a `ProdottoChimico` +
  `SchedaSicurezza` versionata.
- **`dpi`** (`dashboard.html` / `detail.html` + `dpi/templates/dpi/components/subnav.html`): pattern
  di dettaglio con immagini di categoria — utile per la vista mobile con DPI obbligatori e immagine.

## 8. Storage privato, validazione upload, dipendenze

- Pattern storage privato più recente: **`gestione_specifiche/storage.py`**
  (`PrivateSpecificaStorage(EncryptedStorageMixin, FileSystemStorage)`), con `base_location` da
  settings (`GESTIONE_SPECIFICHE_PRIVATE_ROOT`, derivato da `MEDIA_ROOT.parent / "media_private"` —
  **persistente fuori da `current`**, sopravvive ai deploy), `url()` che alza `NotImplementedError`
  per forzare il passaggio dalla view protetta, `upload_to_*` con `get_valid_filename`.
  → replicare per `schede_sicurezza`: nuova var `SCHEDE_SICUREZZA_PRIVATE_ROOT` in
  `config/settings/base.py`, nuova classe `PrivateSchedaSicurezzaStorage` in
  `schede_sicurezza/storage.py`.
- Validazione MIME: già esiste **`core.upload_mime.validate_extension_and_mime(...)`**
  (`UploadMimeValidationError`), usata da `dpi/views.py` — copre nome file (path traversal),
  estensione, dimensione, **magic bytes via `python-magic`** (fail-closed se libmagic assente).
  Nessun bisogno di reinventare la validazione: per il PDF SDS basta
  `validate_extension_and_mime(f, allowed_extensions={".pdf"}, allowed_mimes={"application/pdf"},
  max_bytes=..., allow_empty=False)`.
- Dipendenze richieste dallo spec: **già tutte presenti** in `requirements.txt`
  (`pymupdf==1.27.2.3`, `qrcode==8.0`, `python-magic-bin==0.4.14` su Windows /
  `python-magic==0.4.27` su altre piattaforme). `fitz` (PyMuPDF) è già usato in produzione da
  `ai_assistant/services.py` e `anagrafica/services/elearning_import.py` — nessuna nuova dipendenza
  da aggiungere, nessuna ricompilazione lock necessaria.
- `JSONField` su SQL Server: **già in uso in produzione** da `procedure_refresh.ProcedureQuiz.questions`
  e `ProcedureQuizAttempt.answers` (`models.JSONField`) via `mssql-django`. Nessun rischio noto:
  possiamo usare `JSONField` per `pittogrammi`, `frasi_h`, `frasi_p`, `estratto_grezzo` invece di
  TextField+serializzazione manuale.
- App registration: aggiungere `"schede_sicurezza.apps.SchedeSicurezzaConfig",` a `INSTALLED_APPS`
  in `config/settings/base.py` (dopo `procedure_refresh`, prima di `suggestion_corner` o dopo — ordine
  non semanticamente vincolante).

## 9. Dati reali di catalogo (fonte: foglio Excel di censimento fornito dall'utente)

Intestazione reale del foglio con cui l'azienda sta censendo i prodotti chimici, da usare per allineare
i campi di `ProdottoChimico`/`SchedaSicurezza` (Fase B) invece di inventare uno schema:

```
famiglia | sottocategoria | tag_id | asset_id | new_asset_id | Pittogrammi | n_interno |
Codice Prodotto | stato | produttore | Nome prodotto | ubicazione | Quantita presente |
SDS | Classificazione CLP | Dpi Richiesti
```

Mappatura proposta per Fase B:

- `famiglia`, `sottocategoria` → nuovi `CharField` su `ProdottoChimico` (classificazione interna,
  non normativa CLP).
- `tag_id`, `asset_id`, `new_asset_id` → **non** mappano su `assets.Asset` (quel modello è per IT/
  macchinari — PC, server, CNC, ecc. — non contenitori chimici). Li teniamo come `CharField` opzionali
  di riferimento incrociato al censimento Excel/legacy, senza FK forzata. Da confermare con l'utente
  se in futuro serve un collegamento reale ad Assets.
- `n_interno` → `CharField` `numero_interno` (distinto da `codice_prodotto`).
- `Codice Prodotto` → `CharField` `codice_prodotto` (codice fornitore/produttore).
- `stato` → non solo booleano `attivo`: il foglio ha valori testuali (da confermare in Fase B, es.
  "attivo"/"dismesso"/"esaurito"). Manteniamo `attivo` (bool) per la logica del portale e aggiungiamo
  `stato_note`/`stato` come `CharField` per il valore grezzo del censimento, se necessario.
- `ubicazione` → `CharField` `ubicazione` (posizione fisica nel reparto, testo libero).
- `Quantita presente` → `CharField` `quantita_presente` (testo libero: il foglio non garantisce unità
  di misura uniforme — non forziamo un `DecimalField` senza conferma).
- `SDS` → il file stesso, gestito da `SchedaSicurezza.pdf`.
- `Classificazione CLP` → nuovo `TextField` `classificazione_clp` su `SchedaSicurezza` (distinto da
  `pittogrammi`/`frasi_h`/`frasi_p`, è il testo di classificazione).
- `Dpi Richiesti` → M2M `dpi_obbligatori` già previsto (testo del foglio usato per il mapping manuale
  in fase di import, non per un nuovo campo).

## 10. Discrepanze rispetto allo spec originale (nomi reali vincono)

| Spec (ipotizzato) | Realtà | Impatto |
|---|---|---|
| `dpi.DPICategoria` | `dpi.CategoriaDPI` | M2M `dpi_obbligatori` punta a `CategoriaDPI` |
| Estendere `procedure_refresh` come opzione praticabile | Troppo accoppiato a `ProcedureCampaign` | Si conferma modello locale `PresaVisioneScheda` |
| "reparto esistente" generico | `anagrafica.Reparto` (non `assets`) | FK confermata verso `anagrafica.Reparto` |
| Dipendenze da aggiungere (`PyMuPDF`/`qrcode`/`python-magic`) | Già tutte presenti in `requirements.txt` | Nessuna modifica a `requirements.txt`/lock |
| `JSONField` "da verificare su SQL Server" | Già in produzione (`procedure_refresh`) | Si adotta `JSONField` senza fallback TextField |
| Chiave operatore = `legacy_anagrafica_id` (ipotesi spec) | `procedure_refresh` (riferimento più vicino) usa FK diretta `AUTH_USER_MODEL` | `PresaVisioneScheda.operatore` = FK `AUTH_USER_MODEL` |
| Nessuna colonna Excel reale nello spec | Fornito export reale con più campi (famiglia, ubicazione, quantità, ecc.) | Modello `ProdottoChimico`/`SchedaSicurezza` esteso rispetto alla bozza spec (vedi §9) |

Fase A completata. Si procede con la Fase B (modelli) adattando i target FK ai nomi reali sopra.
