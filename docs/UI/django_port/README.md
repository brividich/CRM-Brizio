# NOVICROM HUB — Port Django SSR + HTMX della Home portale

Questa cartella contiene il **port server-side rendered** del prototipo React `ui_kits/novicrom_hub/HomeHub.jsx`.
Tutto è pensato per integrarsi al codebase **`brividich/CRM-Brizio`** estendendo `core/base.html` e usando i pattern HTMX già in uso.

## Mappa file

| Sorgente in questo zip                                | Destinazione nel repo Django                                                  |
|--------------------------------------------------------|--------------------------------------------------------------------------------|
| `templates/core/pages/home_portale.html`              | `django_app/core/templates/core/pages/home_portale.html`                       |
| `templates/core/components/_home_module_tile.html`    | `django_app/core/templates/core/components/_home_module_tile.html`             |
| `templates/core/partials/_home_activity.html`         | `django_app/core/templates/core/partials/_home_activity.html`                  |
| `static/core/css/home_portale.css`                    | `django_app/core/static/core/css/home_portale.css`                             |
| `views/home_portale.py`                               | nuova app `home_portale/views/home_portale.py` (oppure dentro `core/views/`)   |
| `urls.py`                                             | `home_portale/urls.py` (montata in `django_app/urls.py`)                       |

## Wiring rapido (5 step)

1. **Crea app o file**: copia i quattro template e il CSS nei percorsi sopra.
   Copia `views/home_portale.py` e `urls.py` in una nuova app `home_portale` (o nel modulo `core` esistente).

2. **Registra l'URL** in `django_app/urls.py`:
   ```python
   path("hub/home/", include(("home_portale.urls", "home_portale"))),
   ```

3. **Imposta come landing**: in `LOGIN_REDIRECT_URL` (o nella view che ridirige post-login):
   ```python
   LOGIN_REDIRECT_URL = "home_portale:index"
   ```
   In alternativa, aggiungi la voce in `sidebar.html` come prima rotta.

4. **Cabla i dati reali**: in `views/home_portale.py` ogni `_xxx(request)` ritorna placeholder.
   Sostituisci con query ai tuoi modelli (ticket, anomalie, assenze, ecc.).
   Le funzioni sono già pronte e tipizzate per essere riempite — Claude Code può completarle a partire dai modelli del repo.

5. **Permessi**: il template chiama `user_can_access_module(user, "anomalie.view")` ecc.
   Adatta le stringhe agli scope ACL v2 reali del tuo `core/acl_v2.py`.

## Interazioni HTMX già wirate

| Azione                                       | Endpoint                                                 | Swap                         |
|----------------------------------------------|----------------------------------------------------------|------------------------------|
| Toggle "Mostra moduli non accessibili"       | `POST /hub/home/toggle-locked/`                          | none (solo session)          |
| Auto-refresh "Attività recenti" ogni 60s     | `GET /hub/home/activity/recent/`                         | `innerHTML`                  |
| Approva / rifiuta richiesta in coda          | `POST /hub/home/approve/<kind>/<id>/<approve\|reject>/`  | `outerHTML swap:300ms`       |
| Orologio live nell'hero                      | client-side puro (setInterval 30s)                       | —                            |

## Personalizzazione

### CTA dell'hero
Modifica `_header_actions(request)` in `views/home_portale.py`. Ogni voce è:
```python
{"label": "Nuovo ticket", "icon": "core/icons/_plus.svg",
 "href": reverse("ticket:new"), "variant": "primary", "acl": "ticket.create"}
```
Le variant accettate sono `primary` (arancione pieno) e `ghost` (trasparente bordato).
Se vuoi rendere le CTA configurabili da Hub Tools, leggi le voci da un modello `HubHeaderAction` invece che dall'array Python.

### Loghi/icone dei moduli
Ogni voce di `_MODULE_CATALOG` accetta:
- `icon`: path a un SVG incluso via `{% include %}` (default).
- `icon_image`: URL ad un'immagine (logo a colori). Quando presente, il template lo usa al posto dell'SVG.

Per loghi dinamici da DB, sostituisci `_MODULE_CATALOG` con un `ModuleSpec` model e leggi `icon_image_field.url`.

## Note di sicurezza

- Tutti gli endpoint sono `@login_required` + `@require_POST` / `@require_GET`.
- Il template **non mostra mai** tile non accessibili se `show_locked_modules=False`.
- L'approvazione HTMX deve verificare permission per riga lato server (TODO marker in `approval_decide`).
- Le richieste HTMX ereditano il `X-CSRFToken` dal `base.html` già configurato.
