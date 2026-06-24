# BUILD LOG — App `gestione_specifiche`

> Traccia di esecuzione end-to-end (F1→F9) secondo `BUILD_SPEC.md`.
> Mantenuto dal lead orchestrator. Aggiornato a ogni fine fase e a ogni blocker.

## Stato fasi

| Fase | Descrizione | Stato | Data |
|------|-------------|-------|------|
| STEP 0 | Esplorazione repo | fatto | 2026-06-24 |
| F1 | Modello dati, migrazioni, admin, ACL, navigation | fatto | 2026-06-24 |
| F2 | Macchina a stati (django-fsm-2) + audit + test | fatto | 2026-06-24 |
| F3 | Flusso MOD.133 (UI HTMX) | fatto | 2026-06-24 |
| F4 | Timer/scheduling (django-q2) + notifiche | todo | — |
| F5 | OFI → MOD.174 + sotto-flusso documento CN | todo | — |
| F6 | Distribuzione + tracciamento copie | todo | — |
| F7 | Ricerca, API ninja, UI elenco/cruscotto + storico | todo | — |
| F8 | Import storico + prospetto intake | todo | — |
| F9 | Copilota AI locale | todo | — |

---

## Esplorazione (STEP 0)

Stack: **Django 5.2.13**, mssql-django 1.6, pyodbc 5.3, SQLite in dev. `django-htmx 1.27`, `django-q2 1.9`, `pymupdf`, `reportlab`, `openpyxl` presenti.
**django-fsm-2** e **django-ninja** NON erano installati → installati `django-fsm-2 4.2.4` e `django-ninja 1.6.2` (+ pydantic) nel venv; da aggiungere a `requirements.in/.txt`.

### App rappresentativa / scaffold
- App sotto `django_app/<app>/`. Config in `apps.py` (`class XxxConfig(AppConfig)`, `name=...`, `ready()` chiama il bootstrap ACL).
- INSTALLED_APPS in `config/settings/base.py:332` (formato `"app.apps.AppConfig"`).
- URL inclusi in `config/urls.py` con `path("<prefix>/", include(("app.urls","app"), namespace="app"))`.
- App più recente e pulita da usare come **template**: `gestione_carichi_macchina` (ACL v2 canonico completo).

### ACL v2 (pattern canonico — da `gestione_carichi_macchina/acl_bootstrap.py`)
Modelli in `core.models`:
- `PermissionDefinition(code, module, label, description, is_active)` — permessi canonici.
- `RoutePermissionBinding(route_name, path_pattern, match_strategy, permission_id, source_app, priority, is_active)` — binding rotta→permesso (NECESSARI con `ACL_STRICT_CANONICAL=True` attivo in prod).
- `NavigationItem(code, label, route_name, url_path, section, required_permission_code, order, is_visible, is_enabled, icon, description)` — voce di menu.
- `NavigationRoleAccess(item, legacy_role_id, can_view)`.
- `RolePermissionGrant(legacy_role_id, permission_id, enabled, note)`.
- Fallback legacy: `core.legacy_models.Permesso(ruolo_id, modulo, azione, consentito, can_view, can_edit, can_delete, can_approve)`, `Ruolo`, `Pulsante`.
- Bootstrap: `core.acl_bootstrap_base.run_bootstrap(defs, cache_key, app, section=, bootstrap_nav_fn=)`, chiamato in `AppConfig.ready()`.
- **Gating view**: middleware `core.middleware.ACLMiddleware` applica il binding canonico per rotta (le view usano `@login_required`); per controlli fini: `core.acl.user_can_modulo_action(request, modulo, azione) -> bool`.
- API/AJAX: ritornare `JsonResponse(..., status=401/403)` (no redirect HTML).

### Punti di aggancio esterni (NON modificare, solo FK nullable)
- **OFI / MOD.174**: registro **NON esistente** → `PositiveIntegerField(null=True)` + BLOCKER (vedi §BLOCKERS).
- **Documenti CN**: registro **NON esistente** → `CharField`.
- **Reparti destinatari**: `anagrafica.Reparto` (PK id, `nome` unique, `is_active`) → M2M reale.
- **AI locale**: `ai_assistant.services.chat_with_ollama(prompt, history, runtime_context=...)` (Ollama + RAG). Per F9.
- **Notifiche in-app**: `core.notifiche.invia_notifica(legacy_user_id, tipo, messaggio, url_azione)` + modello `core.Notifica`.
- **Email**: `core.email_utils.send_hub_mail(subject, body_text, recipients, ...)`.

### Storage privato allegati
Pattern: classe storage che estende `core.encrypted_storage.EncryptedStorageMixin` + `FileSystemStorage`, `base_location = settings.<APP>_PRIVATE_ROOT`, `base_url=None`, `.url()` solleva → download via view protetta. Root setting in `base.py` (`*_PRIVATE_ROOT = Path(env(..., BASE_DIR/"media_private"))`).

### Test
`config.settings.test`. Comando scoped: `python django_app\manage.py test django_app.<app> --settings=config.settings.test --keepdb`.

---

## ASSUMPTIONS

- **A1** — `Specifica.revisione` come `CharField` (non int): le specifiche cliente usano revisioni alfanumeriche; l'incremento (F3) prova int+1 se numerica, altrimenti append. Reversibile.
- **A2** — Aggiunti a `Specifica` i campi `cliente` (CharField, blank, idx) e `tag` (CharField, blank, idx) non esplicitati in §5 ma richiesti dai filtri F7 ("filtro per stato/cliente/tag/tipo"). `tag` è anche il target della classificazione AI a livello specifica (le righe MOD.133 mantengono `tag_processo`). Reversibile.
- **A3** — `ConfigPresaVisione` implementato come **modello** (non settings): `tipo_documento` + `reparto` (FK nullable = "tutti") → `richiesta` Bool; più coerente col repo (admin-editable) e con la decisione F0 #3 (configurabile per tipo+reparto).
- **A4** — Storage allegati con `EncryptedStorageMixin` (come `assets`) per coerenza/sicurezza; root `GESTIONE_SPECIFICHE_PRIVATE_ROOT` default `media_private`.
- **A5** — django-fsm-2 e django-ninja installati nel venv e aggiunti a requirements; sono pure-Python e compatibili mssql-django (FSMField = CharField).

## DECISIONS

- **D1** — Usate le librerie reali `django-fsm-2`/`django-ninja` (rete disponibile) invece di shim locali. Coerente con decisione F0 #6 e F7.
- **D2** — Stati FSM memorizzati come codici snake_case (`bozza`, `flow_down`, `in_validita`, `superato`, `sospeso`, `annullato`, `duplicato`, `respinto`, `errore_tecnico`).
- **D3** — App come **modulo isolato** (decisione F0 #9): hook `commessa_ref`/`famiglia_ref` come CharField indicizzati nullable, nessuna FK verso commesse/asset.
- **D4 (gotcha django-fsm)** — `Specifica.stato` è FSMField `protected` ⇒ `instance.refresh_from_db()` solleva `AttributeError` (django-fsm vieta la setattr diretta). Nel codice/test **non** usare `refresh_from_db()` su `Specifica`: ri-fetchare con `Specifica.objects.get(pk=...)`. Le transizioni che falliscono una guardia (ValidationError) **non** emettono `post_transition` ⇒ nessun evento spurio.

## BLOCKERS

- **B1 (non bloccante per il codice)** — Registro **OFI / MOD.174** inesistente nel portale. `RigaMOD133.ofi` e `AzioneOFI.ofi` usano `PositiveIntegerField(null=True)` come riferimento al numero OFI legacy. Quando il registro MOD.174 verrà modellato in Django, sostituire con FK nullable (migrazione additiva). **Domanda all'umano**: esiste una tabella SQL legacy OFI/MOD.174 a cui agganciarsi (nome tabella/PK)?
- **B2** — Ruoli di processo (DM, IN1, RDD, MSM, MSO, MSA, SGI, IT Admin): da mappare ai `Ruolo` legacy esistenti. In attesa di conferma nomi, il bootstrap concede i permessi ai ruoli `admin`/`amministrazione` e propone i nomi mancanti (nessuna creazione gruppi AD senza OK — guardrail §8).

## TEST

- **F3** — `gestione_specifiche` **43/43 verdi** (+17 F3): incremento revisione, creazione/eredità revisione, avvio flow-down (crea MOD.133), formset righe + claim implicito, obbligatorietà condizionale documenti, add riga HTMX, flusso completo S1→S2→S3 da UI, guardia stesso-utente (resta S2), respingi→S8, render template GET (dettaglio/nuova/modifica/approva/compila/lista).
- **F2** — `gestione_specifiche` **26/26 verdi** (9 F1 + 17 F2): happy path S1→S2→S3 + data_verifica, guardie esito/compilatore≠approvatore, superamento revisione automatico, sospendi/ripristina S2↔S5 e S3↔S5, annulla multi-sorgente, duplicato richiede master, errore_tecnico + ripristino, un-evento-per-transizione, TransitionNotAllowed, ACL nega utente senza permesso (superuser ok).
- **F1** — `gestione_specifiche` 9/9 verdi (`manage.py test gestione_specifiche --settings=config.settings.test --keepdb`): default stato/`__str__`, snapshot metadati, PROTECT revisione precedente, immutabilità EventoSpecifica (create ok / update+delete bloccati), default `modo_approvazione` da settings, M2M `Distribuzione`↔`anagrafica.Reparto`. `manage.py check` pulito. Bootstrap ACL verificato a runtime: 8 PermissionDefinition, 1 NavigationItem, 2 RoutePermissionBinding.

## CHANGELOG (commit principali)

- **[F1]** `feat(spec): [F1] app gestione_specifiche — modelli, migrazioni, admin, ACL v2, navigation`
- **[F2]** `feat(spec): [F2] macchina a stati django-fsm-2 + audit immutabile (post_transition)`
- **[F3]** `feat(spec): [F3] flusso MOD.133 UI HTMX (creazione/revisione, formset, claim, approvazione)`

## NOTE STEP 0 (ruoli reali)

Ruoli legacy presenti in dev: `admin, amministrazione, caporeparto, HR, qualita, utente`.
Mappatura di default applicata (create-only, rifinibile in /admin-portale/acl-canonico/):
admin+amministrazione+qualita = tutti i permessi; caporeparto = view/claim/compila.
