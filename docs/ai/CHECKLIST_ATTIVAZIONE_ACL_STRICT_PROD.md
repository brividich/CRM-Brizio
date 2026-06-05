# Checklist attivazione ACL strict-mode in produzione

**Creata:** 2026-06-04
**Contesto:** Fase 3 dismissione doppio sistema ACL — vedi
[PIANO_ACL_FASE2_DISMISSIONE_LEGACY.md](PIANO_ACL_FASE2_DISMISSIONE_LEGACY.md).
**Promemoria pulizia codice:** 2026-06-19 (15 giorni dopo l'attivazione prevista).

Obiettivo: spegnere il fallback legacy (`ACL_STRICT_CANONICAL=True`) in modo
reversibile e verificato, dopo aver consolidato la UI permessi su un'unica
schermata canonica.

---

## Pre-requisiti (già fatti su dev, da riconfermare in prod)

- [x] UI permessi legacy reindirizza a `/admin-portale/acl-canonico/` (default).
- [x] Comando `acl_strict_readiness` disponibile.
- [x] Su dev: 0 route dipendono dal fallback legacy (tutti i 6 ruoli).
- [x] Branch `feat/acl-chiusura-migrazione-fase1` **mergiato** e **rilasciato in prod** (release aggiornata il 2026-06-05).
- [ ] Setting `ACL_LEGACY_PERMESSI_UI_ENABLED` presente in `config/settings/base.py`
      (potrebbe essere rimasto nel working tree alla convergenza — verificare).

---

## Passo 1 — Misura di prontezza su PROD (read-only, nessun rischio)

```powershell
# Su prod (Y), con account runtime/DB:
python django_app\manage.py acl_strict_readiness --settings=config.settings.prod
```

- [x] Output: "Accessi consentiti SOLO via fallback legacy: **0**".
      Misurato in prod il 2026-06-05 dopo l'aggiornamento della release:
      833 route applicative verificate, 0 via fallback su tutti i 9 ruoli
      (portal_superadmin, caporeparto, HR, qualita, amministrazione, utente,
      Manutenzione, admin, Direzione).
- [ ] Se > 0: NON attivare strict. Per ogni route elencata, decidere:
      - se è una route applicativa reale → creare il binding canonico
        (`bootstrap_acl_v2 --apps <app_label> --import-legacy --apply`) e
        allineare i grant (`acl_sync_legacy_grants --app <app_label> --apply`);
      - se è una superficie speciale/per-utente → lasciarla, ma documentarla.
      - Ripetere la misura finché non torna 0.

> Nota: su prod ci sono più utenti/grant che su dev. Il risultato dev (0) è
> incoraggiante ma NON sostituisce questa misura.

---

## Passo 2 — Osservazione passiva (consigliata, ~giorni)

`ACL_LOG_LEGACY_FALLBACK=True` è già il default: il middleware logga ogni uso
reale del fallback (`core.acl` logger).

- [ ] Lasciar girare la prod qualche giorno e controllare i log per messaggi
      "ACL legacy fallback in uso". Idealmente: nessuno (o solo route note
      escluse: notifiche, hub/home, assistente-ai, 2fa, approval-actions).
- [ ] Annotare eventuali route inattese e gestirle come nel Passo 1.

---

## Passo 3 — Attivazione in UAT/test (prima della prod)

- [ ] In `config/test/.env` (o staging): `ACL_STRICT_CANONICAL=True`.
- [ ] Riavviare l'app / riciclare App Pool.
- [ ] Smoke test con utenti rappresentativi (uno per ruolo): le funzioni
      operative quotidiane funzionano (tickets, assenze, anagrafica, dpi…).
- [ ] In caso di 403 imprevisto: `acl_diagnose --user <x> --path <y>` per capire
      quale binding/grant manca.

---

## Passo 4 — Attivazione in PROD

- [ ] In `config/prod/.env` (persistente, su `C:\PortaleNovicrom\prod\config\.env`
      — vedi nota deploy): `ACL_STRICT_CANONICAL=True`.
- [ ] Riciclare App Pool/IIS.
- [ ] Verifica immediata: login con un utente non-admin e accesso a una pagina
      di lavoro tipica (es. /tickets/, /assenze/).
- [ ] Tenere `ACL_LOG_LEGACY_FALLBACK=True` per cogliere deny imprevisti.

### Rollback (immediato, reversibile)
- [ ] Se emergono regressioni: rimettere `ACL_STRICT_CANONICAL=False` in `.env`
      e riciclare App Pool. Nessuna perdita dati (è solo una decisione runtime).

---

## Passo 5 — Pulizia codice (NON prima del 2026-06-19, e solo se strict stabile)

Eseguire solo dopo ~2 settimane di strict-mode stabile in prod senza rollback:

- [ ] Rimuovere il ramo di fallback legacy in `core/acl_v2.py`
      (`resolve_acl_access`, blocco `legacy_fallback`) e la logica
      `evaluate_legacy_permission_code_compat` se non più referenziata.
- [ ] Rimuovere il corpo legacy della view `permessi` (`admin_portale/views.py`)
      e il flag `ACL_LEGACY_PERMESSI_UI_ENABLED` (o lasciarlo come no-op).
- [ ] Valutare la rimozione del template `permessi.html` e delle API legacy
      di scrittura permessi (già protette da 409 sui moduli canonici).
- [ ] Pianificare la dismissione della tabella legacy `permessi` (migrazione
      dati/DDL separata, con backup).
- [ ] Aggiornare CHANGELOG/README e questo documento.

---

## Stato

| Data | Evento |
|---|---|
| 2026-06-04 | Strumenti Fase 3 pronti (UI redirect, readiness). Misura dev = 0. |
| 2026-06-05 | Release `feat/acl-chiusura-migrazione-fase1` rilasciata in prod. Misura prod = **0** via fallback (833 route, 9 ruoli). Passo 1 superato: strict attivabile senza regressioni. |
| _da compilare_ | Osservazione passiva log (Passo 2), attivazione UAT (Passo 3), attivazione prod (Passo 4). |
