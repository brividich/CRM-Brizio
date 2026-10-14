# TVCC TVT — FASE 0: ricognizione (solo lettura)

Data: 2026-10-13 · Base: `origin/main` `adfcae88` · Branch: `feature/assets-tvcc`
Nessun codice applicativo modificato. Questo documento è l'unico file aggiunto.

---

## 1. Modello Asset

| Tema | Stato attuale | File |
|---|---|---|
| Asset | `Asset` con `asset_type` (choices fisse) e **`TYPE_CCTV = "CCTV"` («Videosorveglianza») già esistente**; `manufacturer`, `model`, `serial_number`, `status`, `extra_columns` (JSON), `reparto`, `assignment_*`, `public_qr_token`/`public_qr_enabled` | `assets/models.py:26` |
| Categorie dinamiche | `AssetCategory` ad albero (`parent`), con `base_asset_type` che ricade su `asset_type`; campi custom per categoria in `AssetCategoryField` (TEXT/TEXTAREA/NUMBER/DATE/BOOL, sezione di dettaglio, dimensione card) | `assets/models.py:352`, `:622` |
| Attributi custom globali | `AssetCustomField` + `Asset.extra_columns` | `assets/models.py:325` |
| Relazioni tra asset | **Nessuna relazione asset↔asset** (né padre/figlio né collegamento generico). Esistono solo `AssetComponent` (componenti testuali dell'asset) e `AssetGroup`/`AssetGroupMembership` (gruppi M2M) | `assets/models.py:776`, `:3450` |
| Dati IT | `AssetEndpoint` (N per asset): `endpoint_name`, `vlan`, `ip`, `switch_name`, `switch_port`, `punto`. `AssetITDetails` (1:1): os, cpu, ram, disco, flag sicurezza, `vault_ref` | `assets/models.py:732`, `:759` |
| MAC / hostname | **Non esistono** in nessun modello assets. Unico «nome» rete: `AssetEndpoint.endpoint_name` | — |
| Storico campi | `AssetFieldHistory` (stato, assegnazione, rete) con `fonte` (`form`/`job`/`api`/…), scritto solo da `services/storico_asset.py` | `assets/models.py:4069` |
| Planimetrie | `PlantLayout` + `PlantLayoutMarker(layout, asset, x_percent, y_percent)` univoco per layout/asset → la posizione di una telecamera è già rappresentabile e linkabile | `assets/models.py:1758` |
| Elenco CCTV | Contesto elenco `AssetListLayout.CONTEXT_CCTV` già presente | `assets/views.py:8269` |
| Profilo IT | `services/it_presentation.it_profile()` mappa PC/server/VM/stampante/firewall; **CCTV non è mappato** → la scheda di una telecamera oggi usa il layout standard (non quello IT) | `assets/services/it_presentation.py:9` |

## 2. Pagina dettaglio asset

- Template unico `assets/pages/asset_detail.html` (≈2.300 righe), vista `assets/views.py` (contesto a partire da ~`:10600`).
- **Tab costruiti lato client**: ogni blocco porta `data-af-tab="<Nome>"`; uno script raggruppa i blocchi per nome e crea la barra tab (`asset_detail.html:1948`), con hash `#tab-<slug>` e memoria in `localStorage`. Aggiungere un tab «TVCC» = aggiungere una `<section data-af-tab="TVCC">`.
- Sezioni configurabili: `AssetDetailSectionLayout` ha `SECTION_CHOICES` fisse (specifiche, timeline, manutenzione…); non serve estenderle per TVCC.
- Partial HTMX lazy già in uso (es. `partials/storico_campi_lazy.html`): modello da seguire per caricare la sezione TVCC senza appesantire l'apertura della scheda.
- Esiste già un blocco **«Monitoraggio MFC e SNMP»** (`data-af-tab="Monitoraggio"`, `asset_detail.html:797`) che elenca `asset.dispositivi_snmp` e `asset.contatori_macchine`.
- **Discrepanze identità già esistenti**: `services/it_identity_diff.snmp_identity_diffs()` calcola (non persiste) le differenze seriale/produttore/modello fra asset e SNMP; l'azione `apply_snmp_identity` (`assets/views.py:9817`) applica solo un valore effettivamente letto, con audit. Manca «mantieni dichiarato / ignora» persistente.
- **Abbinamento dispositivo→asset già esistente**: `services/identity_match.py` (seriale → IP → nome, mai scelta arbitraria con più candidati). Il TVCC chiede MAC → seriale → IP: va esteso con il MAC, non duplicato.
- Pattern «aprire la scheda non interroga mai il device»: `services/it_monitoring.py:1` — da rispettare.

## 3. Lettori SNMP (app `contatori`)

| Tema | Stato attuale |
|---|---|
| Preset | `ProfiloSNMP` (slug, produttore, categoria, `sys_object_id_prefix`, `sys_descr_pattern`, `oid_riconoscimento`) + `ColonnaProfiloSNMP` (OID, GET/WALK, aggregazione, unità, soglie, etichette, **`verificata` + `fonte`**). Seminati con **data migration** (`update_or_create` su `profilo+oid`), es. `contatori/migrations/0022_preset_hpe_ilo_verificato.py` |
| Dispositivo | `DispositivoSNMP` (host **unique**, porta/versione/timeout con fallback globale, `community_salvata` → `CommunitySNMP` cifrata, `profilo_snmp`, **FK `asset`**, stato/ultimo errore/sys*). `Categoria` choices: nessuna voce TVCC (oggi finirebbe in `ALTRO`) |
| Sonde | `SondaSNMP` (copiate dalle colonne del profilo, soglie warning/critica) |
| Osservazioni | `RilevazioneSNMP` (`rilevata_il`, stato, tempo risposta, errore, sys*) + `ValoreSNMP` per sonda. **Una riga per ogni poll**, nessuna retention trovata in `contatori` |
| Motore | `contatori/snmp.py` su `puresnmp` (async, v1/v2c/v3), timeout per richiesta e `max_duration` |
| Capture | **`snmp_capture` esiste già** (`contatori/management/commands/snmp_capture.py`): walk completo `.snmprec` + `.txt`, community da catalogo cifrato/variabile d'ambiente, `--sanitize`/`--sanitize-from` (pseudonimizza IP/MAC/nomi). Fixture sanificate in `contatori/fixtures/snmp/`. Test in `contatori/tests_snmp_capture.py` |
| Verifica OID | `contatori/verifica_oid.py` + view dedicate |
| Discovery | `DiscoverySNMP` in background (`discovery_jobs.py`) |

Conseguenza: per TVT lo SNMP si fa **con i mattoni esistenti** (nuovi `ProfiloSNMP` `tvt-nvr`/`tvt-ipc` via migration, colonne standard + overlay privato solo `verificata=True`), senza un secondo motore.

## 4. Credenziali dispositivi

- `contatori/credential_crypto.py`: Fernet con chiave derivata HMAC(`SECRET_KEY`, scopo `novicrom:contatori:community:v1`), rotazione via `SECRET_KEY_FALLBACKS`. Usata da `CommunitySNMP.segreto_cifrato` (mai reso nei form).
- `security/services/secret_box.py`: stessa tecnica ma **generica per scopo** (`encrypt(value, purpose)`, prefisso `fernet:`, decrypt che non solleva mai verso l'utente).
- `AssetITDetails.vault_ref`: solo riferimento testuale a un vault esterno.
- Oggi nessuna credenziale utente/password per dispositivi (solo community/chiavi SNMPv3).

## 5. Scheduler django-q2

- Schedule dichiarate in `automazioni/schedules.py` (lista di spec; applicate da `setup_q_schedules`; salute in `monitoring/schedule_health.py`). Es. `contatori_poll_snmp` ogni 5 min.
- Pattern di fan-out: `contatori/tasks.py` — un job per apparato, lock in cache (`cache.add`, 240 s) contro accumuli, `q_options={"timeout": 110}`, errore → eccezione visibile in django-q ma dettaglio nello storico del device.
- `Q_CLUSTER`: `workers` da env (default 3), `timeout` 120, `retry` 180, `max_attempts` 3, broker `automazioni.broker.FlowBroker`, `catch_up=False`.
- Memoria di progetto: dopo un `migrate` il qcluster va riavviato; una schedule rinominata resta orfana.

## 6. ACL v2

- Permessi = `core.PermissionDefinition` (`code` tipo `contatori.modulo.view`, `contatori.gestione.manage`), binding per route `RoutePermissionBinding` (exact o prefix, priorità), grant per ruolo/utente/gruppo — tutto creato con **data migration create-only** (`contatori/migrations/0025_acl_consultazione_gestione.py`).
- Controllo dentro le view per le scritture: `contatori/permessi.py` (`evaluate_permission_code_access`, JSON 403 per HTMX/AJAX).
- Registro modulo per il sistema ruoli: `registro_permessi.py` → `core.permessi.registro.registra_modulo`.
- `ACL_STRICT_CANONICAL` (attivo in prod): **ogni nuova route senza binding è negata** ai non superuser → ogni URL TVCC deve nascere con il suo binding.
- Assets: `_is_assets_admin()` (`assets/views.py:3372`), `_can_edit_asset()` via `acl_allows_path`. Pagina QR pubblica: `_render_asset_qr_landing(public=True)` (`assets/views.py:11159`) costruisce un contesto esplicito (manutenzioni, documenti): non include SNMP, quindi non includerà TVCC se non aggiunto — va blindato con un test.

## 7. Dipendenze e vincoli di esecuzione

- Presenti: `requests`, `defusedxml`, `cryptography`, `puresnmp`(+crypto), `django-q2`, `django-ninja`, `django-htmx`. **Assenti**: `zeep`, `lxml`, librerie ONVIF.
- pip-tools: `requirements.in` → `requirements.txt` (memoria di progetto: `pip-compile` su Windows può perdere i marker di piattaforma: va ricontrollato a mano).
- **Discrepanze col brief**: il repo non usa pytest (Django `manage.py test`) e non ha `.pre-commit-config`/detect-secrets alla radice; esiste invece `manage.py secret_hygiene_check`. Mi allineo agli strumenti del repo.
- Raggiungibilità già usata: `socket.create_connection` (`monitoring/health.py:284`). Nessun ping/ICMP nel codice.
- Windows/IIS: ICMP con raw socket richiede privilegi amministrativi; senza privilegi restano `ping.exe` (subprocess, esito dal codice di ritorno) o `IcmpSendEcho` (iphlpapi via ctypes). Va verificato sotto l'identità del servizio qcluster. Multicast WS-Discovery: non serve (i canali si leggono dall'NVR) e non attraverserebbe le VLAN.

## 8. Gap analysis

| # | Serve | Esiste | Da aggiungere |
|---|---|---|---|
| G1 | Ruolo NVR/telecamera | `TYPE_CCTV` unico | distinzione NVR vs IPC |
| G2 | Collegamento telecamera→NVR+canale | nessuna relazione asset↔asset | modello collegamento con vincolo canale unico per NVR |
| G3 | MAC dichiarato | assente | campo MAC dichiarato (per match e discrepanze) |
| G4 | Profilo connessione + credenziale ONVIF cifrata | solo community SNMP | profilo connessione TVCC + segreto cifrato (riuso tecnica `secret_box`) |
| G5 | Osservazioni ONVIF/reachability con `observed_at` | `RilevazioneSNMP` (solo SNMP, riga per poll, niente retention) | osservazioni TVCC con `fonte` |
| G6 | Discrepanze persistenti con revisione | diff calcolato al volo + applica | stato revisione (accetta/mantieni/ignora, utente, data) |
| G7 | Storico disponibilità a eventi + retention | — | eventi di cambio stato |
| G8 | Profili stream, snapshot NVR | — | modelli dedicati (senza URI) |
| G9 | Client ONVIF read-only | — | client + allowlist operazioni + test anti-metodi |
| G10 | Preset SNMP TVT | motore e formato pronti | profili `tvt-nvr`/`tvt-ipc` (dopo FASE 1) |
| G11 | Match MAC→seriale→IP | `identity_match` seriale→IP→nome | aggiunta del MAC in testa |
| G12 | Sezione TVCC su scheda + vista d'insieme + wizard | tab client-side, partial HTMX | nuove view/partial |
| G13 | Permessi TVCC (3 livelli) | pattern migration + binding | 3 `PermissionDefinition` + binding |
| G14 | Alert | `core.Notifica` (in-app, tipi a choices) | nuovo tipo o solo dashboard |
| G15 | Porta switch da MAC | `snmp_capture` conosce `dot1dTpFdb` ma **nessun preset/sonda lo raccoglie** | → sviluppo futuro, come previsto dal brief |

## 9. Decisioni proposte (da confermare prima della FASE 1/2)

1. **Nuova app `tvcc`** (FK verso `assets.Asset`, partial incluso nella scheda asset) invece di aggiungere modelli in `assets/models.py` (4.700 righe, molti branch paralleli → collisioni di numerazione migration già viste). Stesso approccio di `contatori`.
2. **Ruolo** NVR/TELECAMERA come campo del modello TVCC dell'asset (`asset_type` resta `CCTV`); sottocategorie «NVR» e «Telecamere IP» seminate solo come comodità di filtro, non come fonte del ruolo (le categorie sono modificabili dagli admin).
3. **MAC dichiarato** su `AssetEndpoint` (`mac`, nullable, normalizzato) tracciato in `AssetFieldHistory` come gli altri campi di rete. È l'unica modifica a `assets`.
4. **Osservazioni**: modello nuovo in `tvcc` con `fonte` (`onvif`/`reachability`/`snmp`/`tvt_api`) che salva solo l'ultimo valore per chiave + eventi di cambio; **non** generalizzo `RilevazioneSNMP` (rischio regressione stampanti). Lo SNMP dei TVT passa da `DispositivoSNMP` + preset; la vista TVCC legge l'ultima rilevazione. Suggerisco SNMP solo sull'NVR (26 telecamere × poll ogni 5 min = ~7.500 righe/giorno senza retention).
5. **ONVIF**: client interno minimale su `requests` + `defusedxml` (già nel repo) con allowlist esplicita delle ~12 operazioni Get* e WS-UsernameToken digest con offset orario, al posto di `onvif-zeep` (non mantenuto, scarica/legge WSDL, porta `zeep`+`lxml`, più RAM). Niente WSDL a runtime. Motivazione completa nell'ADR. Alternativa: `zeep` 4.x + WSDL nel repo, se preferisci una libreria.
6. **Reachability**: TCP connect (porta HTTP/ONVIF) come default; ICMP via `ping.exe` solo se la verifica sotto il servizio qcluster va a buon fine.
7. **Permessi**: `tvcc.modulo.view`, `tvcc.gestione.manage`, `tvcc.admin.manage` (convenzione del repo), nessun grant iniziale (solo superuser) finché non li assegni tu dal pannello Accessi.
8. **Alert**: nuovo tipo `tvcc_alert` in `core.Notifica` (canale in-app esistente, non nuovo) ai titolari di `tvcc.admin.manage`; in alternativa solo evidenza in dashboard.

## 10. Rischi aperti

- Le API/OID/porte TVT sono ignote finché non arrivano le catture di FASE 1.
- Il supporto ONVIF Profile G (Recording/Search) sugli NVR TVT è da verificare: senza, la profondità archivio non è disponibile via ONVIF.
- Drift orario: WS-UsernameToken fallisce se l'ora del device è molto sfasata → serve `GetSystemDateAndTime` non autenticato prima dell'autenticazione.
- Identità del servizio qcluster in prod: ICMP e uscita verso la VLAN TVCC da verificare (regole WatchGuard).

## 11. Decisioni confermate (2026-10-13)

Perimetro ridotto: **solo dati SNMP**, mostrati sugli asset esistenti.

| # | Esito |
|---|---|
| 1 | No nuova app: la categoria asset TVCC esiste già; servono solo le info che arrivano dallo SNMP (motore `contatori`). |
| 2 | No campo ruolo NVR/telecamera. |
| 3 | Sì: MAC dichiarato su `AssetEndpoint.mac`, tracciato nello storico. |
| 4 | Telecamere interrogate ogni **30 minuti**; rilevazioni ripulite oltre **14 giorni**. |
| 5 | ONVIF: non ora. |
| 6–8 | Reachability, permessi dedicati e alert: non servono. |

Prossimo passo: catture SNMP reali con il comando esistente `snmp_capture`, poi preset `tvt-nvr`/`tvt-ipc` con soli OID verificati.
