# Project Context

This file preserves long-form project context moved out of root CLAUDE.md.

Important: Do not read all docs automatically. Open only the files relevant to the current task.

## Original Context Header

# CLAUDE.md - Portale Novicrom

Documento di contesto per AI coding assistant. Aggiornato continuamente con il progetto.
Versione app corrente: **1.0.1** (2026-04-28)

---


## Configurazione globale - SiteConfig
`SiteConfig` (in `core/models.py`) ÃƒÆ’Ã‚Â¨ una tabella key-value Django per personalizzare il portale senza toccare il codice (titolo sito, moduli abilitati, temi login, ecc.).

- Accesso: `SiteConfig.get_many(defaults)` ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â restituisce dict con fallback
- Usato da: `setup_wizard`, `hub_tools` (Module Manager), `context_processors`
- Branding globale portale: chiavi `portal_name`, `portal_subtitle`, `brand_logo_full`, `brand_logo_compact`, `brand_favicon`, `brand_primary_color`, `brand_accent_color`, `brand_background_color`; si gestiscono da `/admin-portale/hub/categorie/`, con upload validato MIME in `media/portal_branding/` o fallback via URL assoluto/relativo.
- Non usare `settings.py` per configurazioni modificabili a runtime ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â usare `SiteConfig`

---


## Ricerca Globale (Ctrl+K)

- Endpoint: `GET /api/search/?q=<query>` â†’ `core/views.py:api_global_search` â†’ `core/urls.py`
- Attivazione: `Ctrl+K` (o `Cmd+K` su Mac) oppure click sull'icona ðŸ” nella topbar
- Modelli interrogati (max 5 risultati per gruppo): `AnagraficaDipendente`, `Asset`, `Ticket`, `Project`, `Task`, `ProcedureDocument`
- I modelli di altre app vanno importati localmente dentro la funzione per evitare import circolari
- Risposta: `{"results": [{tipo, label, sub, url}, ...], "query": "..."}` con risultati raggruppati per tipo
- UI: overlay spotlight in `topnav.html` con navigazione da tastiera (frecce, Enter, Esc), debounce 220ms; in modalita sidebar il trigger rapido vive anche in `core/components/sidebar.html` come card scura integrata con hint `Ctrl+K` e resa icon-only quando `sb-collapsed` e attivo
- CSS: classi `.gs-*` in `theme.css`; ogni tipo di risultato ha la sua classe colore `.gs-tipo-<tipo>`
- Query minima: 2 caratteri; gestione errori per app non disponibili tramite `try/except` silenzioso

---

## Audit Trail

- Funzione: `core/audit.py` ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ `log_action(request, azione, modulo, dettaglio)`
- Scrive su `core.models.AuditLog` (tabella Django, con migration)
- Fire-and-forget: gli errori DB sono loggati ma non propagati alla view
- Traccia automaticamente se l'azione ÃƒÆ’Ã‚Â¨ eseguita in impersonation (aggiunge `_impersonation` nel payload)
- App che giÃƒÆ’Ã‚Â  usano audit log: `admin_portale`, `anomalie`, `assenze`, `assets`, `core`
- **Da usare** per ogni operazione CRUD rilevante (creazione/modifica/cancellazione di entitÃƒÆ’Ã‚Â )

---


## Wizard di primo accesso (Onboarding)

- Modello: `core.UserOnboarding` (OneToOne su Django User) â€” migration `0043_useronboarding`
- URL: `/onboarding/` (view `onboarding_wizard`, name `onboarding_wizard`)
- Intercettazione: `ACLMiddleware` (dopo check autenticazione) â†’ redirect a `/onboarding/` se `UserOnboarding.is_done()` Ã¨ `False`
- Accesso pagina: `/onboarding/` resta sempre apribile a qualsiasi utente autenticato, senza grant ACL legacy/canonico dedicati
- Superusers bypass il check onboarding
- Reset API: `POST /api/onboarding/<django_user_id>/reset` (name `api_onboarding_reset`) â€” azioni: `reset` (riproponi wizard) o `skip` (esenta utente); solo admin legacy o superuser
- Admin UI: scheda utente in Admin Portale â†’ tab Checklist â†’ card "Wizard primo accesso"
- Step correnti wizard: `Benvenuto` â†’ `Contatti` â†’ `Interfaccia` â†’ `Notifiche` â†’ `Riepilogo`
- Preferenze UI raccolte: `nav_mode`, `font_scale`, `sidebar_collapsed`, `sidebar_footer_actions` (persistite in `core.UserUiPreference`)
- Notifiche email: il wizard deve mostrare solo i moduli effettivamente visibili al ruolo corrente; i tipi nascosti vanno persistiti come disabilitati per evitare preferenze fuorvianti
- Dati raccolti onboarding: `email_contatto`, `cellulare_contatto`, `notifiche_config` (JSON tipo â†’ bool, es. `assenze`, `comunicazioni`, `scadenzari`, `ticket`)
- Azioni tracciate in AuditLog: `onboarding_completato`, `onboarding_reset`, `onboarding_esentato`

---

## Logging

- File log in `django_app/logs/`: `app.log`, `app-{hostname}.log`, `sql.log`
- Handler custom `SafeTimedRotatingFileHandler` in `core/logging_handlers.py` (rotazione giornaliera, safe per multi-process)
- SQL logging configurabile via env `SQL_LOG_ENABLED` e `SQL_LOG_LEVEL`
- In produzione non usare `print()` ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â usare sempre `logging.getLogger(__name__)`

---

## Compatibility layer Flask

- `core/legacy_flask_views.py`: 62 route Flask coperte (27 native, 35 redirect/410)
- Non modificare senza capire prima quale route Flask copre

---

## Debito tecnico noto (non toccare senza discussione)

1. SQL raw inline in `core/context_processors.py` e alcune views
2. Cache Graph primitiva (`Lock + dict`) ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â non sicura su multi-process (wsgi multi-worker)
3. `planimetria/models.py` ÃƒÆ’Ã‚Â¨ vuoto (solo commento) ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â non aggiungere logica
4. `module_registry.py`: solo `assets` registrato, gli altri moduli non sono brandizzabili

---

## Cache in produzione (IIS multi-worker)

Con 2+ worker IIS usare `DatabaseCache` (SQL Server) ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â condivisa tra processi:

- Configurata automaticamente da `config/settings/prod.py`
- **Setup una-tantum dopo ogni deploy su server vergine:** `python manage.py createcachetable`
- Tabella: `django_cache` (override con env `DJANGO_CACHE_TABLE`)
- `bump_legacy_cache_version()` usa `cache.incr()` atomico ÃƒÂ¢Ã¢â‚¬Â Ã¢â‚¬â„¢ invalidazione ACL immediata su tutti i worker
- Dev usa `LocMemCache` (default Django) ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â nessuna configurazione aggiuntiva

---

