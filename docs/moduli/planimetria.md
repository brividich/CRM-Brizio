# `planimetria` — wrapper compatibile

Area **Operations** · URL `/planimetria/` · codice [`django_app/planimetria/`](../../django_app/planimetria/)

[← Catalogo moduli nel README](../../README.md#-catalogo-moduli)

## Sintesi

Wrapper compat di assets per discoverability layout

## Dettaglio

App "ponte" con `models.py` vuoto. Mantenuta solo per **discoverability** e retrocompat delle URL storiche — tutta la logica vive in `assets`.

- Nessuna tabella propria
- Nessun permesso proprio sulle pagine (26/10/2026): `/planimetria/editor/` richiede solo il login e decide il permesso dell'editor di Asset, così non esistono due permessi per la stessa pagina
- Reindirizza a `/assets/` con filtri appropriati
