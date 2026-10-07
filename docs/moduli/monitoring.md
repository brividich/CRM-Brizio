# `monitoring` — osservabilità interna

Area **Core** · URL `/monitoring/` · codice [`django_app/monitoring/`](../../django_app/monitoring/)

[← Catalogo moduli nel README](../../README.md#-catalogo-moduli)

## Sintesi

Monitoring interno, issue tracking, alert email, segnalazioni utente, monitor automazioni

## Dettaglio

Superficie di monitoring del portale, issue tracking interno e segnalazioni utenti.

- **Issue tracking** interno per bug segnalati dagli utenti
- **Alert email** su eventi di sistema configurabili
- **Monitor automazioni** con health card della queue
- **Segnalazioni utente** dirette all'admin
- **Liveness/readiness probe** runtime (`/healthz`, `/readyz`) con check su DB, cache, Graph, LDAP, SMTP e queue automazioni; risultato memoizzato in cache, IP allowlist via `HEALTHZ_ALLOWED_IPS`. Riusabili da `validate_deployment --with-integration` per coerenza tra deploy validation e runtime
- **Provenienza della build** nella Centrale di comando (`/admin-portale/monitoring/status/`): commit, branch, autore e data letti dal `BUILD_INFO.json` scritto nel pacchetto da `package-release.ps1`, con banner rosso se il codice in esecuzione non corrisponde a un commit pulito del branch di release. Manifest assente = "sviluppo — nessun pacchetto"
- CSS dedicato in `static/monitoring/css/monitoring.css` verificato in `collectstatic`
