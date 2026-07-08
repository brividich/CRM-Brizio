# Design — Modulo `suggestion_corner` (NOVICROM HUB)

**Data:** 2026-07-08
**Basato su:** `docs/BUILD_SPEC_suggestion_corner.md` (spec di riferimento) + verifica assunzioni contro il codice reale + 4 decisioni chiuse in brainstorming.
**App Django:** `suggestion_corner` — nuova, top-level (non dentro `anagrafica`), per isolare l'endpoint pubblico.

Questo documento NON riscrive la BUILD_SPEC: la assume come base (§1–§9) e ne fissa i **4 delta** decisi dopo aver verificato che parte delle assunzioni tecniche della spec non reggeva al contatto col codice.

---

## Verifica assunzioni (fatta prima di questo design)

| Assunzione spec | Realtà codice | Esito |
|---|---|---|
| `anagrafica.Reparto` esiste | ✅ `anagrafica/models.py:730` (`db_table=anagrafica_areaaziendale`) | FK valida |
| `django-fsm-2` installato | ✅ `requirements.txt:19` + **già usato in `gestione_specifiche`** (FSMField protected + `@transition` + signal audit) | pattern di riferimento esistente |
| `ai_assistant/services.py` esiste | ✅ | riuso AI copilot fattibile |
| `core.Notifica` esiste | ✅ `core/models.py:413` con `TIPI` hardcodata | riusabile |
| `anagrafica.Processo` esiste | ❌ non esiste; il modello reale è `ProcessoQualificato` (`models_mpq.py:114`) | **correzione Δ2** |
| `django-ratelimit` "eventualmente in uso" | ❌ non installato | **correzione Δ3** |

---

## Δ1 — Macchina a stati: django-fsm-2 (adottato)

Si usa `FSMField` + `@transition` come da §2 della BUILD_SPEC. **Non è un pattern nuovo**: `gestione_specifiche` lo usa già in modo maturo ed è il **riferimento da copiare**:
- `Specifica.stato = FSMField(..., protected=True, db_index=True)` (`gestione_specifiche/models.py:52`);
- transizioni `@transition(field=stato, source=..., target=...)` con guardie e `GET_STATE`;
- audit centralizzato via signal `post_transition` in `gestione_specifiche/state_machine.py` → crea un evento immutabile con snapshot; le transizioni preparano attore/payload via un helper `_prep_evento(attore, **payload)` che setta transient `_evento_attore`/`_evento_payload`.
- `state_machine` è agganciato nel `AppConfig.ready()` (`gestione_specifiche/apps.py`).

`suggestion_corner` replica questa architettura:
- `SuggestionCornerStorico` popolato via:
  - signal `post_transition` → registra `stato_precedente`/`stato_nuovo` + attore;
  - `pre_save` che diffa i campi PLAN/DO/CHECK/ACT → registra le modifiche di campo fuori transizione.
- Regola **`incaricato != controllore`**: come `clean()`/validator sul modello, **non** dentro la FSM. Eccezione loggata in audit se qualcuno tenta il bypass (utile ISO 27001).
- Enforcement "chi completa il DO deve essere `self.incaricato`": lato view/permission, non FSM.

Stati e transizioni: invariati da §2 BUILD_SPEC (incl. self-loop `check_rinviato`, rami `do_da_rifare`/`check_negativo`, `RINVIATO` come esito valido).

## Δ2 — Campo processo: libero ora, agganciabile dopo

La FK `anagrafica.Processo` della spec non esiste. Decisione:

- `processo_libero` (`CharField`) = **input primario**, popolato da subito.
- `processo` = `ForeignKey("anagrafica.ProcessoQualificato", on_delete=SET_NULL, null=True, blank=True)` — lasciata nel modello per l'aggancio futuro, non vincolante al go-live.
- **Nuova sezione nell'admin del modulo**: UI per mappare i valori `processo_libero` → `ProcessoQualificato` reali (normalizzazione) e/o impostare un default. Nessun vincolo al MPQ (ancora in working tree, non pushato) al go-live; la strada per collegarsi ai processi reali resta aperta e gestibile da interfaccia.

Coerente con la decisione 5.5 della spec ("da valutare in corso d'opera, per ora FK nullable con fallback a testo libero").

## Δ3 — Rate limiting form pubblico: cache-based, nessuna dipendenza

`django-ratelimit` non è installato → non lo si aggiunge.

- Rate-limit **per IP** implementato sulla cache già configurata (`DatabaseCache` in prod, LocMem in dev), ~30 righe.
- + **honeypot** nascosto via CSS (§5): se compilato, request scartata silenziosamente.
- **Critico — esclusione dal gate ACL** (memoria `acl_middleware_api_gate_paths`): la route `/suggestion-corner/nuova/` va **esplicitamente esclusa** dal gate ACL in `core/middleware.py`, altrimenti `ACL_STRICT_CANONICAL` (attivo in prod) la nega ai non autenticati. È il punto di sicurezza n.1 del modulo: unica superficie pubblica non autenticata, va isolata a livello IIS (path escluso da SSO) e trattata come nuovo perimetro nell'audit di sicurezza in corso.

## Δ4 — Notifiche in-app: riuso infrastruttura esistente

Niente `SuggestionCornerNotificaInApp`. Si riusa quanto già esiste e già enforced:

- Aggiunta dei tipi suggestion_corner a `core.Notifica.TIPI`.
- Integrazione con `core/notifiche_prefs.should_notify` (categoria dedicata), così le notifiche rispettano gli interruttori on/off già attivi — sia in-app sia i 4 reminder email per-utente. Nessun doppione di infrastruttura.

---

## Cosa resta invariato dalla BUILD_SPEC

- **Modelli §1**: `SuggestionCorner` (con `@property scaduto_do`/`scaduto_check` calcolate, non colonne), `SuggestionCornerAllegato` (con `link_esterno` per i path `\\novisrv\...`), `SuggestionCornerStorico` (§1.3), `SuggestionCornerConfig` singleton (§1.4, parametri soglia/escalation da admin).
- **ACL v2 §4**: nuovo gruppo `SMS_TEAM` (vede tutto, classifica, definisce PLAN, ACT, mail cliente); utenti normali vedono solo le proprie segnalazioni + incarichi assegnati; pubblico solo POST creazione. Viste "da gestire"/"riguarda SMS" = queryset filtrati, non permessi separati.
- **Form pubblico §5**: route non-ACL, select reparto (no free text), opzione anonima, submit → `INSERITA` → auto `DA_CLASSIFICARE` + mail SMS Team, QR code.
- **Notifiche email §3**: scheduler django-q2 giornaliero, solleciti 30/15/5, escalation oltre `giorni_escalation_oltre_scadenza` (default 7), email 1:1 dalla procedura.
- **Migrazione §7**: command `import_suggestion_corner_legacy`, 55 record reali, match persone via email, tabelle di normalizzazione manuale reparti (provenienza+destinazione → stessa FK `Reparto`), `RINVIATO` gestito, allegati di rete → `link_esterno`, `da_portale=False`, storico single-entry "Importato da SharePoint", dry-run con report prima della prod, import incrementale idempotente.
- **AI copilot §6**: on-prem via Ollama (`qwen2.5:14b-instruct`) — classificazione SMS_SI/NO (umano conferma sempre), bozza PLAN, dedup semantica ibrida BM25+dense. Riuso `ai_assistant/services.py`.
- **Dashboard KPI §8**: card stile Anagrafica HR, dati veri (no placeholder), stato vuoto onesto se non ci sono dati.

## Ordine di sviluppo (§9 BUILD_SPEC, invariato)

1. Modelli + migrations + admin base (incl. `SuggestionCornerConfig` + sezione mappatura processi Δ2)
2. FSM + validazione (`incaricato != controllore`) + signal storico
3. ACL v2 (`SMS_TEAM`) + viste protette
4. Form pubblico + rate-limit cache-based + esclusione gate ACL
5. Notifiche email (django-q2) + reminder scheduler
6. Notifiche in-app (riuso `core.Notifica` + `notifiche_prefs`)
7. Audit trail (`SuggestionCornerStorico` + signal/pre_save)
8. Script migrazione + dry-run
9. AI copilot (classificazione + dedup)
10. Dashboard KPI
11. Test suite

Ogni punto = una sessione dedicata; `/compact` prima del lancio; nessun subagent parallelo (CLAUDE.md).

## Note operative HUB (non negoziabili)

- Test scoped: `python django_app\manage.py test django_app.suggestion_corner --keepdb --settings=config.settings.test` (mai suite completa).
- Migrazioni sempre applicate nel checkout locale `C:\Dev\Portale Novicrom` (memoria `feedback_modifiche_sempre_in_locale`).
- CHANGELOG.md + README.md aggiornati a ogni modifica (memoria `feedback_changelog_readme`).
- Setup Wizard fa `migrate` selettivo dal MODULE_REGISTRY: la nuova app va registrata lì o si rischia 500 in prod (memoria `setup_wizard_selective_migrate_pitfall`).
- Nessun file dati reale (CSV/PDF/xlsx) committato; PDF e dataset restano fuori repo.
