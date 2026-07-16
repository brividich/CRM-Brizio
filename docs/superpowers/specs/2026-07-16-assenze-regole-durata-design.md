# Assenze — Regole durata (Permesso/Ferie/durata rapida) + rimozione "Riconciliazione" dalla topnav — Design

> Stream 4 della punch-list `docs/ANAGRAFICA - PERSONE.md`, sezione **ASSENZE**.
> Documento di design (spec). Il piano operativo TDD è in
> `docs/superpowers/plans/2026-07-16-assenze-regole-durata.md`.

## Goal

Rendere **autorevoli lato server** le regole di durata della richiesta di assenza e
ripulire la barra di navigazione del modulo:

1. **Permesso**: dentro lo **stesso giorno**, durata compresa tra **0h30 (30 minuti)**
   e **8h** massimo.
2. **Ferie**: **più di 1 giorno** (almeno 2 giornate; niente ferie mono-giorno).
3. **Durata rapida** (`mattina` / `sera` / `normale` / `mezza1` / `mezza2`): l'utente può
   modificare **solo la data**; l'orario resta bloccato sul preset e la richiesta è
   confinata a **un solo giorno** (`data_inizio` = `data_fine`, "limiti data logici").
4. **Personalizzato** (`custom`): l'utente può cambiare **anche l'orario**, ma restano i
   **vincoli del giorno** propri del tipo (per Permesso: stesso giorno + 30min–8h).
5. Rimuovere la voce **"Riconciliazione"** dalla topnav (subnav) del modulo.

La validazione lato client resta come **enhancement UX** (già presente), ma la fonte di
verità è il server: gli endpoint che scrivono assenze devono rifiutare i payload fuori
regola anche se il client viene aggirato.

## Stato attuale (codice reale)

### Validazione server-side — `_validate_business_rules`
`django_app/assenze/views.py:1009-1052`. Firma:

```python
def _validate_business_rules(*, tipo, dt_start, dt_end, person_name="", person_email="", exclude_item_id=None) -> tuple[str, str]:
```

Ritorna `(err_msg, warn_msg)`: `err_msg` non vuoto = richiesta rifiutata. Regole già presenti:
- `dt_start`/`dt_end` obbligatori, `dt_end > dt_start`.
- **Permesso**: `dt_start.date() == dt_end.date()` (stesso giorno). **Nessun limite min/max ore.** ← gap regola 1.
- **Ferie**: `dt_end.date() >= dt_start.date()` e orari `00:00`–`23:59` (giornate intere). **Consente il mono-giorno.** ← gap regola 2.
- **Flessibilità**: 9–10 ore, max 2/settimana (via `_count_flessibilita_week`, `views.py:969`).
- **Non conosce il concetto di "durata rapida"**: la funzione riceve solo `dt_start`/`dt_end`, non il preset scelto. ← gap regole 3/4.

`_validate_business_rules` è l'unico punto condiviso ed è chiamato da **tre** endpoint di scrittura:
- `invio_placeholder` (creazione richiesta) — `views.py:4412`, chiamata a `views.py:4486`.
- `api_evento_update` (modifica CAR/admin dal calendario, JSON) — `views.py:4158`, chiamata a `views.py:4201`.
- `api_mia_assenza_update` (utente modifica la propria richiesta "In attesa", JSON) — `views.py:4330`, chiamata a `views.py:4378`.

Nota: `invio_placeholder` ha anche due controlli **inline** ridondanti prima di
`_validate_business_rules`: forzatura orari ferie a `00:00/23:59` (`views.py:4434`) e blocco
permesso multi-giorno (`views.py:4450`). Restano; le nuove regole si aggiungono nella
funzione condivisa così da valere per tutti e tre gli endpoint.

### Durata rapida — solo lato client, non arriva al server
Template `django_app/assenze/templates/assenze/pages/richiesta_assenze.html`:
- Radio group `name="shortcut"` (`righe 789-796`): valori `mattina`, `sera`, `normale`,
  `mezza1`, `mezza2`, `custom` (default `custom checked`).
- Preset orari duplicati in JS (`righe 990-996`):
  `mattina 06:00–14:00`, `sera 14:00–22:00`, `normale 08:00–17:00`,
  `mezza1 08:00–12:00`, `mezza2 13:00–17:00`.
- Al `change` del radio, il JS scrive `time_start`/`time_end` (`righe 1346-1359`), ma **non
  blocca** i campi orario (l'utente può poi editarli a mano) e il valore `shortcut` **non
  viene letto dal server** (`grep shortcut` in `views.py` = nessun match).

Campi POST inviati da `invio_placeholder` (`views.py:4426-4429`): `date_start`, `date_end`,
`time_start`, `time_end`, `tipoassenza`, `caporeparto`, `motivazione`, `certificato_medico`,
`salta_approvazione`, `dipendente_id`, `submit_token`. Il radio `shortcut` è già nel form ma
oggi viene ignorato.

### Topnav (subnav) del modulo
`django_app/assenze/templates/assenze/components/subnav.html:26-30`:

```django
{% if assenze_can_reconcile %}
  <a class="abs-subnav-link{% if current == 'assenze_riconciliazione' %} active{% endif %}" href="{% url 'assenze_riconciliazione' %}">
    <svg aria-hidden="true"><use href="#abs-i-sync"></use></svg>Riconciliazione
  </a>
{% endif %}
```

È un `<a>` **hardcodato** nel template della subnav, gated dalla chiave di contesto
`assenze_can_reconcile` (impostata in `_template_perm_context`, `views.py:939`).
**Non è un `NavigationItem`**: la rimozione è una modifica del markup del template, non un
intervento sul dato di navigazione. La subnav è l'unica "topnav" del modulo
(`base_shell.html:653` la include; classe `.abs-subnav`, commento "Topbar modulo").

### Pannello admin assenze (contesto — già esistente)
Verificato: il pannello admin (approva/rifiuta/elimina) esiste davvero:
- View `gestione_admin` — `views.py:4826`, route `assenze_gestione_admin` (`urls.py:34`),
  template `templates/assenze/pages/gestione_admin.html` + partial
  `templates/assenze/partials/_gestione_admin_panel.html`.
- Azioni: `api_car_aggiorna_consenso` (`views.py:3943`, approva/rifiuta),
  `api_admin_assenza_delete` (`views.py:4027`, elimina).
Questo stream **non tocca** il pannello admin: nessuna sovrapposizione.

## Interpretazione di "0.30h" (decisione da confermare)

La punch-list scrive "*da 0.30h a 8h max*". Interpretiamo **0.30h = 0 ore e 30 minuti = 30
minuti** (convenzione oraria italiana `h.mm`), quindi durata minima Permesso = **30 minuti**.
Se invece il capo intende 0,30 ore decimali (18 minuti), basterà cambiare la costante
`PERMESSO_MIN_MINUTES`. La costante isola questa scelta.

## Design della soluzione

### Fonte unica dei preset e dei limiti — `constants.py`
Aggiungere a `django_app/assenze/constants.py`:

```python
# Preset "durata rapida": (ora_inizio, ora_fine) sullo STESSO giorno.
SHORTCUT_PRESETS = {
    "mattina": ("06:00", "14:00"),
    "sera":    ("14:00", "22:00"),
    "normale": ("08:00", "17:00"),
    "mezza1":  ("08:00", "12:00"),
    "mezza2":  ("13:00", "17:00"),
}
SHORTCUT_CUSTOM = "custom"

# Limiti Permesso (stesso giorno).
PERMESSO_MIN_MINUTES = 30      # "0.30h" = 30 minuti (vedi spec)
PERMESSO_MAX_HOURS = 8
```

I preset restano duplicati nel JS del template (necessari per l'UX live); il commento nel
template rimanda a `constants.SHORTCUT_PRESETS` come fonte di verità, e il piano prevede un
test che verifica la coerenza JS↔costanti tramite parsing del template (guardia anti-drift).

### Estensione di `_validate_business_rules` (autorevole)
Nuova firma:

```python
def _validate_business_rules(*, tipo, dt_start, dt_end, person_name="", person_email="",
                             exclude_item_id=None, shortcut=None) -> tuple[str, str]:
```

Ordine dei controlli (dopo gli esistenti "obbligatori" e `dt_end > dt_start`):

1. **Durata rapida** (`shortcut` presente e `!= "custom"`):
   - `shortcut` deve essere in `SHORTCUT_PRESETS`, altrimenti errore "Durata rapida non valida.".
   - Confinamento a un giorno: `dt_start.date() == dt_end.date()`; altrimenti
     "Con una durata rapida la richiesta deve restare nello stesso giorno."
   - Orario bloccato: `(dt_start.strftime('%H:%M'), dt_end.strftime('%H:%M'))` deve essere
     esattamente il preset; altrimenti
     "Con una durata rapida puoi modificare solo la data, non l'orario."
2. **Permesso** (dopo lo stesso-giorno esistente): durata in minuti
   `(dt_end - dt_start)` compresa tra `PERMESSO_MIN_MINUTES` e `PERMESSO_MAX_HOURS*60`;
   altrimenti "Il permesso deve durare tra 30 minuti e 8 ore."
3. **Ferie** (dopo il controllo giornate intere esistente): `dt_end.date() > dt_start.date()`
   (span > 1 giorno); altrimenti "Le ferie devono coprire più di un giorno."
4. **Flessibilità**: invariata.

I controlli 1–2 sono in **AND** (una durata rapida su un Permesso deve rispettare sia il
preset sia i 30min–8h). Es.: preset `normale` (9h) su un Permesso viene respinto dal limite
8h — comportamento corretto: `normale` è un preset a giornata piena, adatto a
Flessibilità, non a Permesso.

### Wiring del `shortcut` negli endpoint
- `invio_placeholder`: leggere `shortcut = request.POST.get("shortcut")` e passarlo a
  `_validate_business_rules(..., shortcut=shortcut)`. È l'unico endpoint con la UI dei preset.
- `api_evento_update` e `api_mia_assenza_update`: **non** espongono i preset (editing dal
  calendario / dalla lista). Chiamano `_validate_business_rules` **senza** `shortcut`
  (default `None` → percorso "custom"), così le nuove regole Permesso 30min–8h e Ferie >1
  giorno valgono comunque anche in modifica, mantenendo coerenza. Nessun `shortcut` sintetico.

### Enforcement UI (non autorevole) in `richiesta_assenze.html`
- Al `change` del radio `shortcut`: se il valore è un preset (≠ `custom`), impostare
  `time_start.readOnly = true` e `time_end.readOnly = true` (orario bloccato, l'utente cambia
  solo la data); se `custom`, rimuovere `readOnly`. Estendere la funzione già presente che
  gestisce Ferie (`applyTypeDefaults`, `righe 1075-1095`) e/o l'handler dei radio
  (`righe 1346-1359`). Ferie continua a forzare `00:00/23:59` readOnly come oggi.
- Il submit handler client (`righe 1387-1485`) aggiunge, come UX, il mirror delle nuove
  regole (Permesso 30min–8h; Ferie >1 giorno) con `alert` non bloccante lato server.
- Non introdurre attributi template con `_` iniziale; commenti `{# #}` mono-riga.

### Rimozione "Riconciliazione" dalla topnav
Eliminare il blocco `{% if assenze_can_reconcile %} … {% endif %}` (`subnav.html:26-30`).
La route `assenze_riconciliazione` (`urls.py:28`) e la view `riconciliazione`
(`views.py:3747`) **restano** (la punch-list chiede solo di toglierla dalla topnav; la
pagina resta raggiungibile via URL diretto). La chiave di contesto `assenze_can_reconcile`
diventa inutilizzata nei template ma resta in `_template_perm_context` (rimozione fuori
scope; nota nel piano).

## Regole di validazione — matrice attesa (TDD)

| # | Caso | Input | Esito atteso |
|---|------|-------|--------------|
| 1 | Permesso troppo lungo | Permesso, 08:00–17:00 (9h), stesso giorno, custom | **respinto** "…tra 30 minuti e 8 ore." |
| 2 | Permesso troppo corto | Permesso, 08:00–08:20 (20min), custom | **respinto** "…tra 30 minuti e 8 ore." |
| 3 | Permesso valido | Permesso, 08:00–12:00 (4h), custom | ok |
| 4 | Permesso multi-giorno | Permesso, giorni diversi | **respinto** (stesso-giorno) |
| 5 | Ferie mono-giorno | Ferie, 12/03→12/03, 00:00–23:59 | **respinto** "…più di un giorno." |
| 6 | Ferie 2 giorni | Ferie, 12/03→13/03, 00:00–23:59 | ok |
| 7 | Durata rapida, orario alterato | shortcut=`mattina`, time 06:00–15:00 | **respinto** "…solo la data, non l'orario." |
| 8 | Durata rapida, solo data | shortcut=`mattina`, time 06:00–14:00, un giorno | ok |
| 9 | Durata rapida multi-giorno | shortcut=`mattina`, date diverse | **respinto** (stesso giorno) |
| 10 | Custom permesso orario libero | Permesso, custom, 09:15–13:45 (4h30) | ok |
| 11 | Subnav senza riconciliazione | render subnav, `assenze_can_reconcile=True` | HTML **non** contiene "Riconciliazione" |

## Sicurezza / ACL
- Nessuna modifica alla catena ACL né ai gate degli endpoint: la validazione è additiva su
  funzioni già gated (`invio_placeholder` richiede `can_insert` + submit token; gli endpoint
  JSON richiedono i rispettivi permessi). Gli endpoint API restano JSON `400/403`.
- La rimozione della voce dalla topnav non è un confine di sicurezza: la view resta protetta
  lato server (visibilità nav ≠ autorizzazione).

## Non-goal
- Rimuovere la view/route/pagina `riconciliazione` (solo la voce di topnav).
- Toccare il pannello admin assenze, la certificazione presenza, il calendario, la sync SharePoint.
- Cambiare i preset di Flessibilità o le sue soglie settimanali.
- Bump di versione.

## File toccati (tutti sotto `django_app/assenze/` → disgiunti dagli altri stream)
- `constants.py` — costanti preset/limiti.
- `views.py` — `_validate_business_rules` + wiring `shortcut` in `invio_placeholder`.
- `templates/assenze/pages/richiesta_assenze.html` — blocco orari su durata rapida + mirror JS.
- `templates/assenze/components/subnav.html` — rimozione voce Riconciliazione.
- `tests.py` — nuovi test + aggiornamento del test ferie mono-giorno preesistente.
- `CHANGELOG.md`, `README.md` — condivisi, append-only, staging esplicito (ultimo task).

Nessuna modifica ai modelli → **nessuna migrazione**.
