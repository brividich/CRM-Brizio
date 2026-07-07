# ANALISI 01 — CORE / ACL v2 · SSO Windows · Anagrafica · Assets

**Data:** 2026-07-05
**Perimetro:** SOLO le aree richieste — ACL v2 (`core/acl_v2.py`, `core/acl.py`, `core/middleware.py`, bootstrap ACL), autenticazione/SSO Windows (`core/accounts/backends.py`, `core/accounts/windows_sso.py`, `core/legacy_utils.py`, `core/impersonation.py`), `anagrafica`, `assets`.
**Modalità:** analisi read-only, file per file, in sequenza. Nessuna modifica al codice, nessun comando che altera stato.
**Nota su ACL/SSO:** i rischi di autorizzazione/autenticazione sono descritti a livello di *pattern*; nessun dettaglio sfruttabile.

---

## Executive summary

Il perimetro analizzato è **sostanzialmente solido nelle fondamenta**: la pipeline ACL v2 è fail-closed (deny-by-default nel bootstrap, strict-mode disponibile), i documenti HR sensibili (referti, DPI, qualifiche, foto) sono su **storage privato cifrato AES-256 fuori webroot** con view protette e audit, l'impersonazione è gated su admin + audit trail, il provisioning utente concorrente è protetto da `select_for_update` e gestione `IntegrityError`, e l'audit degli accessi ai documenti c'è. Anti-brute-force (Axes), CSP, HSTS, cookie sicuri e guard di startup su `SECRET_KEY`/`CSRF_TRUSTED_ORIGINS` sono presenti.

I temi che meritano attenzione si concentrano su tre fronti:

1. **Perimetro di autenticazione SSO più largo dell'intenzione.** La allowlist gruppi AD (`LDAP_GROUP_ALLOWLIST`) è applicata solo nella sincronizzazione massiva (`sync_ldap_users`), **non** al login interattivo LDAP/SSO; il provisioning crea automaticamente un account attivo per ogni principal AD che effettua un bind valido. Il gating a valle resta ACL, ma la superficie di *chi può entrare* è ampia.
2. **Un paio di superfici di download non uniformi** rispetto allo standard del progetto: documenti fornitori su webroot non cifrato e download documenti asset senza controllo per-oggetto (pattern IDOR).
3. **Costo per-richiesta del middleware ACL** non trascurabile: helper di path non cachati (`lru_cache` importato ma non applicato), scansione in memoria di tutti i binding, query onboarding ad ogni richiesta; più debito strutturale (doppio motore ACL legacy/canonico, monoliti `views.py` da ~15–17k righe, DDL runtime su `anagrafica_dipendenti`).

Nessun finding è un *"buco spalancato"* verificato in isolamento; le voci a severità più alta sono **combinazioni di postura** (autenticazione larga + gating implicito) e **debito che erode la manutenibilità della barriera di sicurezza**.

---

## Tabella severità × effort

| ID | Finding | Dimensione | Severità | Effort |
|----|---------|-----------|----------|--------|
| F1 | `LDAP_GROUP_ALLOWLIST` non applicato al login interattivo LDAP/SSO | Sicurezza applicativa | **Alta** | Medio |
| F2 | Auto-provisioning "fail-open" di ogni UPN AD sconosciuto | Sicurezza applicativa | Media | Medio |
| F3 | `FornitoreDocumento` su storage pubblico (webroot) non cifrato | Sicurezza / GDPR | **Alta** | Medio |
| F4 | `asset_document_download` senza controllo per-oggetto (IDOR-pattern) | Sicurezza applicativa | Media | Basso |
| F5 | Audit best-effort su download dati sanitari (fail-silent) | Osservabilità / GDPR | Media | Basso |
| F6 | DDL a runtime (`ALTER TABLE`) su `anagrafica_dipendenti` dal request path | Debito tecnico / dati | Media | Medio |
| F7 | Provisioning `UtenteLegacy` non atomico (race su login SSO simultaneo) | Concorrenza / dati | Media | Medio |
| F8 | `_route_names_to_paths` non cachato + `reverse()` ad ogni richiesta | Performance | Media | Basso |
| F9 | `_find_canonical_binding` carica e itera tutti i binding per richiesta | Performance | Media | Medio |
| F10 | Doppio motore ACL (legacy + canonico) con bridge bidirezionale | Debito / manutenibilità | Media | Alto |
| F11 | Monoliti `views.py` (anagrafica ~14.8k / assets ~17.4k righe) | Manutenibilità | Media | Alto |
| F12 | Gating anagrafica con helper ad-hoc non uniformi, route non tutte bound | Manutenibilità / sicurezza | Media | Alto |
| F13 | Fail-open onboarding + `except Exception: pass` nel path ACL | Osservabilità | Bassa | Basso |
| F14 | `CSRF_COOKIE_HTTPONLY=False` + CSP `'unsafe-inline'` (postura) | Sicurezza applicativa | Bassa | Medio |

---

## Findings di dettaglio

### F1 — `LDAP_GROUP_ALLOWLIST` non applicato al login interattivo · Alta · Sicurezza applicativa

**Pattern di rischio:** la restrizione per gruppo AD è enforced solo nel comando di sincronizzazione massiva `core/management/commands/sync_ldap_users.py:165`, dove `LDAP_GROUP_ALLOWLIST` filtra chi viene importato. I percorsi di **autenticazione interattiva** non consultano la allowlist:

- `core/accounts/backends.py:129` (`LDAPBackend.authenticate`) — dopo un bind riuscito chiama `resolve_ldap_identity` → `provision_legacy_user` → `sync_django_user_from_legacy`, senza alcun controllo di membership.
- `core/accounts/windows_sso.py:116` — stesso schema dopo l'handshake SPNEGO.
- `grep allowlist|group|memberof` su `backends.py` → 0 occorrenze.

**Conseguenza:** il perimetro di *chi può ottenere una sessione* coincide con *chi ha credenziali di dominio valide e sa fare bind*, non con il gruppo aziendale previsto. L'autorizzazione fine resta ACL v2, ma alcune superfici sono condivise per ogni autenticato (vedi F12 e gli `_ACL_SHARED_*` in `middleware.py:37-80`).

**Raccomandazione:** applicare la stessa allowlist di gruppo anche in `LDAPBackend.authenticate` e nel flusso SSO (verifica `memberOf` durante `resolve_ldap_identity`, che ha già una connessione LDAP attiva), fail-closed se la allowlist è configurata e la membership non è verificabile. Riferimenti: `backends.py:210`, `legacy_utils.py:104`.

---

### F2 — Auto-provisioning "fail-open" di ogni UPN AD sconosciuto · Media · Sicurezza applicativa

**Pattern di rischio:** `core/legacy_utils.py:482` (`provision_legacy_user`) crea automaticamente un `UtenteLegacy` **attivo** con ruolo `"utente"` per ogni UPN non ancora presente. Combinato con F1, il primo login di un principal AD qualsiasi materializza un account applicativo senza approvazione esplicita.

**Attenuanti presenti:** ruolo di default `utente` (nessun bypass admin), gating ACL a valle, `attivo` verificato per gli account esistenti.

**Raccomandazione:** rendere il provisioning opt-in rispetto alla allowlist di F1 (creare l'account solo se il principal supera il filtro di gruppo). Documentare esplicitamente la scelta "auto-provision on first login" come decisione di sicurezza.

---

### F3 — `FornitoreDocumento` su storage pubblico non cifrato · Alta · Sicurezza / GDPR

**Evidenza:** `anagrafica/models.py:138` — `file = models.FileField(upload_to=_fornitore_documento_upload_to)` **senza** `storage=PrivateAnagraficaStorage()`. `_fornitore_documento_upload_to` (`models.py:105`) scrive in `anagrafica/fornitori/<id>/...` **sotto `MEDIA_ROOT`**, cioè nella webroot servita staticamente. `/media/` è in `MIDDLEWARE_EXEMPT_PREFIXES` (`base.py:697`), quindi esente da autenticazione.

Questo diverge dallo standard del modulo: referti visite, DPI, qualifiche, storico qualifiche e foto usano tutti `PrivateAnagraficaStorage` (cifrato, fuori webroot, `url()` che solleva `NotImplementedError`) — vedi `anagrafica/models.py:571,700,829,2009`. I documenti fornitori (contratti, offerte, certificazioni, visure) restano invece potenzialmente accessibili via URL diretto se IIS serve `/media/`.

**Caveat:** l'esposizione effettiva dipende dalla configurazione IIS del sito (se `/media/` è mappato su disco). Va verificato, ma la postura corretta è non dipendere da quella configurazione.

**Raccomandazione:** migrare `FornitoreDocumento.file` a `PrivateAnagraficaStorage` con view di download ACL + audit, coerente con gli altri documenti del modulo; predisporre migrazione dei file già caricati.

---

### F4 — `asset_document_download` senza controllo per-oggetto · Media · Sicurezza applicativa

**Evidenza:** `assets/views.py:3086` — `@login_required` è l'unico gate; la view fa `get_object_or_404(AssetDocument, pk=document_id)` e restituisce il file a **qualsiasi utente autenticato**, iterando `document_id`. È un pattern IDOR classico.

**Contrasto interno:** la sorella `admin_deadline_attachment_download` (`assets/views.py:3407`) verifica `_is_assets_admin(request)` e logga il diniego. Il download documento asset no.

**Attenuante:** il contenuto (`SPECIFICHE`/`INTERVENTI`/`MANUALI`) è meno sensibile dei dati HR, ma resta materiale tecnico riservato d'impresa.

**Raccomandazione:** aggiungere un controllo di autorizzazione coerente con la visibilità dell'asset (o almeno con il permesso `assets` di lettura), sul modello di `admin_deadline_attachment_download`. Effort basso: il pattern e l'audit esistono già a poche righe di distanza.

---

### F5 — Audit best-effort su download di dati sanitari · Media · Osservabilità / GDPR

**Evidenza:** `anagrafica/views.py:8869-8886` (`documento_dipendente_download`) — l'`log_action` del download è avvolto in `try/except: logger.warning(...)` e il download **procede comunque** se l'audit fallisce. Per referti visite mediche (dati sanitari, art. 9 GDPR) l'audit trail dovrebbe essere garantito, non fire-and-forget.

Lo stesso pattern "audit best-effort" è pervasivo (`core/audit.py:59` cattura ogni eccezione), il che è ragionevole per azioni ordinarie ma non per l'accesso a categorie particolari di dati personali.

**Raccomandazione:** per i download di documenti sanitari/disciplinari, rendere l'audit una precondizione (se la scrittura audit fallisce, negare o mettere in coda), oppure garantirlo transazionalmente. Riferimenti: `anagrafica/views.py:8853`, `core/audit.py:13`.

---

### F6 — DDL a runtime su `anagrafica_dipendenti` dal request path · Media · Debito tecnico / dati

**Evidenza:** `core/legacy_anagrafica.py:159` (`ensure_anagrafica_schema`) esegue `ALTER TABLE anagrafica_dipendenti ADD COLUMN ...` per colonne mancanti, ed è invocata **all'inizio di view interattive** come `dipendenti_list` (`anagrafica/views.py:517`) e `fetch_anagrafica_rows`.

**Rischio:** DDL implicito fuori dal sistema di migrazioni Django, eseguito su richiesta utente: possibile latenza/lock su SQL Server al primo hit dopo un deploy, divergenza schema non tracciata dalle migrazioni, comportamento diverso tra ambienti. Su una tabella legacy condivisa il lock DDL è particolarmente delicato.

**Raccomandazione:** spostare l'aggiunta colonne in una migrazione/`management command` idempotente eseguito al deploy, e ridurre `ensure_anagrafica_schema` a sola verifica (o a no-op cachato) nel path di richiesta.

---

### F7 — Provisioning `UtenteLegacy` non atomico · Media · Concorrenza / dati

**Evidenza:** `core/legacy_utils.py:482` (`provision_legacy_user`) fa `filter(email__iexact=upn).first()` e, se assente, `UtenteLegacy.objects.create(...)` **senza** `transaction.atomic` né lock/vincolo di unicità garantito su `email`. Due login SSO simultanei dello stesso nuovo UPN possono creare due righe `UtenteLegacy`.

**Contesto positivo:** il downstream `sync_django_user_from_legacy` (`legacy_utils.py:399`) è invece ben protetto (`select_for_update` su `Profile`, gestione `IntegrityError`, blocco dei remap). Il punto debole è a monte, nella creazione del record legacy.

**Raccomandazione:** avvolgere lookup+create in `transaction.atomic` con `get_or_create` e affidarsi a un vincolo di unicità (case-insensitive) su `email`; gestire `IntegrityError` ricadendo sul record esistente.

---

### F8 — Helper di path non cachati nel hot path del middleware · Media · Performance

**Evidenza:** `core/middleware.py:4` importa `lru_cache` ma **non lo applica mai** (`grep @lru_cache` → 0). `_route_names_to_paths` (`middleware.py:105`) esegue `reverse()` su ~33 route (`_ACL_SHARED_ROUTE_NAMES`) ricostruendo il `frozenset` **ad ogni chiamata**; viene invocata due volte per richiesta (onboarding-shared + shared) in `ACLMiddleware.__call__`. In più `reverse("onboarding_wizard")` è chiamato ad ogni `__call__` (`middleware.py:225`).

**Conseguenza:** decine di `reverse()` per ogni richiesta autenticata non-esente, costo costante e inutile su tutto il traffico.

**Raccomandazione:** applicare `@lru_cache` a `_route_names_to_paths` (le route non cambiano a runtime) e calcolare `onboarding_path` in modo lazy/cachato. Effort basso, beneficio su ogni richiesta.

---

### F9 — `_find_canonical_binding` carica e itera tutti i binding per richiesta · Media · Performance

**Evidenza:** `core/acl_v2.py:343-353` — quando il match per `route_name` fallisce, il ramo DB fa `RoutePermissionBinding.objects.filter(is_active=True).exclude(path_pattern="")` e **itera in Python** tutti i binding per testare il match di path, ad ogni richiesta. Nessuna cache (a differenza di pulsanti/`perm_map` legacy, cachati con TTL in `legacy_cache.py`).

**Conseguenza:** costo O(N binding) per ogni richiesta che ricade sul match per path; cresce con la copertura ACL canonica (obiettivo dichiarato del progetto).

**Raccomandazione:** cachare i binding attivi (stesso schema TTL + `bump` su modifica già presente per il legacy) e/o indicizzare il match per prefisso. Attenzione all'invalidazione quando si edita un binding da `/admin-portale/acl-canonico/`.

---

### F10 — Doppio motore ACL con bridge bidirezionale · Media · Debito / manutenibilità

**Evidenza:** coesistono `core/acl.py` (legacy: pulsanti/permessi) e `core/acl_v2.py` (canonico). `check_permesso` (`acl.py:134`) chiama `acl_v2`, che a sua volta può ricadere sul fallback legacy (`acl_v2.py:800`). `_find_canonical_binding` ha **due rami** (DB e in-memory) che "devono restare sincronizzati per evitare divergenze" — annotazione nel codice stesso (`acl_v2.py:322`).

**Rischio:** ogni superficie di duplicazione è un punto di divergenza di comportamento tra ambienti (in dev/test il middleware ACL è spesso inattivo, quindi la guardia effettiva è quella in-view — vedi F12). È debito *atteso* durante la migrazione, ma va tenuto sotto controllo con test di equivalenza tra i due rami.

**Raccomandazione:** mantenere/estendere i test che verificano parità di decisione DB-vs-in-memory e canonico-vs-legacy; pianificare la dismissione del ramo legacy quando `ACL_STRICT_CANONICAL` sarà stabile in prod (coerente con la checklist già citata nel progetto).

---

### F11 — Monoliti `views.py` · Media · Manutenibilità

**Evidenza:** `anagrafica/views.py` = 14.843 righe / 312 funzioni; `assets/views.py` = 17.394 righe / 373 funzioni. Blast-radius elevato per ogni modifica, merge-conflict frequenti (coerente con la trappola "working tree condiviso" già nota), review difficile.

**Raccomandazione:** scomposizione incrementale per dominio (es. `views/formazione.py`, `views/skillmatrix.py`, `views/documenti.py`; per assets `views/workorders.py`, `views/maintenance.py`, `views/documents.py`) senza cambiare URL/route. Effort alto ma abilitante per tutti gli interventi futuri.

---

### F12 — Gating anagrafica con helper ad-hoc non uniformi · Media · Manutenibilità / sicurezza

**Evidenza:** in `anagrafica/views.py` ci sono 244 `@login_required` ma **0** usi di `user_can_modulo_action`; l'autorizzazione è affidata a helper eterogenei: `_check_hr_permission` (`:1203`), `_can_view_visite_mediche` (`:1241`), `_ensure_admin` (`:8714`), `_check_skm_permission` (`:1222`), `_can_edit_formazione` (`:10234`), ciascuno con la propria logica di singleton/ruoli. Le route del modulo non sono tutte sotto binding canonico (il bootstrap copre Skill Matrix e pochi pulsanti).

**Rischio:** un nuovo endpoint HR aggiunto senza replicare il pattern giusto può risultare più aperto del previsto; la coerenza dipende dalla disciplina dello sviluppatore, non dal framework. In dev/test (middleware ACL inattivo) l'unica barriera è questo gating in-view — quindi la sua uniformità è security-relevant.

**Raccomandazione:** consolidare gli helper in decoratori riusabili (es. `@require_hr_permission`, `@require_skm(code)`) e completare i binding canonici delle route del modulo; aggiungere un test che verifica che ogni view sensibile abbia un gate.

---

### F13 — Fail-open onboarding + `except Exception: pass` nel path ACL · Bassa · Osservabilità

**Evidenza:** `core/middleware.py:263-264` — il check onboarding cattura ogni eccezione con `pass` ("non bloccare l'accesso in caso di errore DB"). Scelta di disponibilità comprensibile, ma maschera errori DB senza traccia. In generale `except Exception: pass` compare 5× in anagrafica e 11× in assets (views).

**Raccomandazione:** almeno loggare (throttled) prima del `pass`, così un guasto DB sistematico non resta invisibile.

---

### F14 — Postura CSRF/CSP · Bassa · Sicurezza applicativa

**Evidenza:** `prod.py:92` `CSRF_COOKIE_HTTPONLY=False` (necessario: il JS legge il token dai cookie) combinato con CSP che ammette `'unsafe-inline'` su `script-src` (`base.py:217`). Nessuno dei due è un difetto isolato — sono trade-off documentati del pattern SSR/HTMX — ma insieme riducono la difesa in profondità contro XSS (un XSS potrebbe leggere il token CSRF).

**Raccomandazione (lungo termine):** percorso verso CSP con nonce per eliminare `'unsafe-inline'` su script; è un lavoro trasversale ai template, da pianificare separatamente.

---

## Note positive (postura già corretta, da non regredire)

- **Storage privato cifrato** per i documenti HR sensibili (`EncryptedStorageMixin` AES-256 Fernet, fuori webroot, `url()` che solleva) — `core/encrypted_storage.py`, `anagrafica/storage.py`, `assets/storage.py`.
- **Bootstrap ACL deny-by-default**: `init_missing_permessi` crea permessi con tutti i flag a 0 (`acl_bootstrap_base.py:252`).
- **Strict-mode ACL** disponibile e fail-closed (`middleware.py:309`, `ACL_STRICT_CANONICAL`).
- **Impersonazione** gated su admin/superuser, audit start/stop, ri-validazione del target ad ogni richiesta e attore reale tracciato nell'audit (`impersonation.py`, `audit.py:26`).
- **Provisioning Django concorrente** robusto (`select_for_update`, `IntegrityError`, blocco remap) — `legacy_utils.py:399`.
- **Anti-brute-force** (Axes), **HSTS/SSL redirect**, **cookie Secure/HttpOnly**, **guard di startup** su `SECRET_KEY` e `CSRF_TRUSTED_ORIGINS` placeholder (`prod.py`).
- **API protette** che rispondono `401/403` JSON e non redirect HTML (`middleware.py:235,358`).
- **Validazione upload** con sniffing MIME reale (`sniff_mime`) oltre all'estensione (`anagrafica/views.py:2630`).
- **Anti-open-redirect** centralizzato (`get_safe_redirect_target`, `redirects.py`).
- **Logging ACL throttled** (`_log_acl_once`) per evitare flood mantenendo osservabilità.

---

## Suggerimento di sequenza d'intervento

1. **Quick win a basso effort / alto valore:** F4 (controllo per-oggetto download asset), F8 (`@lru_cache` sugli helper path), F5 (audit garantito sui dati sanitari), F13 (log prima del `pass`).
2. **Sicurezza di perimetro (medio effort):** F1 + F2 (allowlist gruppo al login SSO/LDAP e provisioning condizionato), F3 (documenti fornitori su storage privato).
3. **Robustezza dati (medio effort):** F6 (DDL runtime → migrazione), F7 (provisioning atomico), F9 (cache binding).
4. **Debito strutturale (alto effort, pianificato):** F10 (dismissione ramo legacy dopo strict-mode prod), F11 (scomposizione monoliti), F12 (decoratori di gating uniformi + copertura binding), F14 (CSP con nonce).

---

*Report di sola analisi. Nessun file di progetto è stato modificato. I rischi ACL/SSO sono descritti a livello di pattern, senza dettagli sfruttabili.*
