# Auto-approvazione MOD.133 "umanizzata" — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rendere l'auto-approvazione del MOD.133 indistinguibile da un'approvazione manuale nella UI utente (approvatore MSO, data plausibile ~1 giorno lavorativo dopo la compilazione), preservando la traccia automatica nelle sole viste admin e senza falsificare l'audit immutabile.

**Architecture:** Un helper stateless calcola il primo giorno lavorativo dopo la compilazione (weekend + festivi IT). `_auto_approva_se_configurata` scrive questa data su `mod.data_approvazione` (campo documento) lasciando intatto l'evento di audit. Le viste utente nascondono l'evento marcatore `auto_approvazione` e, per la sola riga di approvazione, mostrano `data_approvazione` al posto del timestamp reale. Il timbro RICEVUTO usa la data reale di ingresso.

**Tech Stack:** Django 5.2, Python 3.11+, PyMuPDF (fitz) per i timbri, unittest (Django TestCase).

## Global Constraints

- Comandi test (SQL Server non richiesto in test): `python django_app\manage.py test django_app.gestione_specifiche.tests.<module> --settings=config.settings.test --keepdb`.
- **Nessuna nuova dipendenza**: la Pasqua si calcola con il computus (stdlib).
- **Non usare `.update()` sul `timestamp` di `EventoSpecifica`**: l'audit è immutabile per design; la data fittizia vive solo su `mod.data_approvazione` e come rendering.
- **Attributi helper nei template Django senza underscore iniziale** (es. `ts_display`, non `_ts_display`).
- **Preservare il lavoro non committato nel working tree** (feature timbri in corso): `composito.py`, `models.py`, `timbri_overlay.py`, `timbri_views.py`, `migrations/0011_timbroapplicazione.py`, `templates/.../applica_timbri.html`, `mod133_compila.html`, `urls.py`. Le modifiche di questo piano si innestano su quei file senza annullare le modifiche esistenti.
- Commit dopo ogni task (autorizzazione autonoma già concessa; verificare che nessun file dati `.xlsx/.csv/.pdf/.json` sia staged).
- Spec di riferimento: `docs/specs/gestione_specifiche/AUTO_APPROVAZIONE_UMANIZZATA.md`.

---

## File Structure

- **Create** `django_app/gestione_specifiche/date_utils.py` — festivi IT + `next_business_datetime`. Zero dipendenze dal resto dell'app.
- **Create** `django_app/gestione_specifiche/timeline.py` — costruzione della timeline "umanizzata" per le viste utente.
- **Modify** `django_app/gestione_specifiche/views.py` — `_auto_approva_se_configurata` (data fittizia + payload); `dettaglio` e `scheda_storico` (usano `timeline.eventi_umanizzati`).
- **Modify** `django_app/gestione_specifiche/composito.py` — helper `_data_ricevuto(spec)`; `_risolvi_timbri` e `_risolvi_placements` lo usano al posto di `now()`.
- **Modify** `templates/gestione_specifiche/dettaglio.html` — timeline usa `ts_display`; card MOD.133 mostra "Approvato il".
- **Modify** `templates/gestione_specifiche/scheda_storico.html` — timeline usa `ts_display`.
- **Modify** `templates/gestione_specifiche/admin/auto_approva.html` — nota "marcatore automatico" → chiarisce che è solo admin-side.
- **Test** nuovi/estesi: `tests/test_date_utils.py`, `tests/test_timeline.py`, `tests/test_admin.py` (estensione), `tests/test_composito.py` (estensione).
- **Docs** finali: `CHANGELOG.md`, `README.md`.

---

## Task 1: Helper date lavorative (`date_utils.py`)

**Files:**
- Create: `django_app/gestione_specifiche/date_utils.py`
- Test: `django_app/gestione_specifiche/tests/test_date_utils.py`

**Interfaces:**
- Produces:
  - `festivi_it(anno: int) -> set[date]` — festivi nazionali italiani + Pasquetta dell'anno.
  - `next_business_datetime(base: datetime) -> datetime` — primo giorno lavorativo dopo `base.date()`, ora casuale in `[9:00, 17:00)`, `datetime` *aware* nella timezone corrente.

- [ ] **Step 1: Write the failing tests**

Create `django_app/gestione_specifiche/tests/test_date_utils.py`:

```python
"""Test helper date lavorative per l'auto-approvazione umanizzata."""
from datetime import date, datetime

from django.test import TestCase
from django.utils import timezone

from gestione_specifiche.date_utils import festivi_it, next_business_datetime


class FestiviItTest(TestCase):
    def test_pasquetta_2026(self):
        # Pasqua 2026 = 5 aprile → Pasquetta 6 aprile.
        self.assertIn(date(2026, 4, 6), festivi_it(2026))

    def test_pasquetta_2025(self):
        # Pasqua 2025 = 20 aprile → Pasquetta 21 aprile.
        self.assertIn(date(2025, 4, 21), festivi_it(2025))

    def test_fissi_presenti(self):
        f = festivi_it(2026)
        for d in (date(2026, 1, 1), date(2026, 1, 6), date(2026, 4, 25),
                  date(2026, 5, 1), date(2026, 6, 2), date(2026, 8, 15),
                  date(2026, 11, 1), date(2026, 12, 8), date(2026, 12, 25),
                  date(2026, 12, 26)):
            self.assertIn(d, f)


class NextBusinessDatetimeTest(TestCase):
    def _base(self, y, m, d):
        return timezone.make_aware(datetime(y, m, d, 12, 0))

    def test_salta_weekend(self):
        # venerdì 2026-07-03 → +1 = sabato → lunedì 2026-07-06.
        r = next_business_datetime(self._base(2026, 7, 3))
        self.assertEqual(r.date(), date(2026, 7, 6))

    def test_salta_festivo(self):
        # lunedì 2026-01-05 → +1 = martedì 06/01 (Epifania) → mercoledì 2026-01-07.
        r = next_business_datetime(self._base(2026, 1, 5))
        self.assertEqual(r.date(), date(2026, 1, 7))

    def test_ora_in_orario_ufficio(self):
        r = next_business_datetime(self._base(2026, 7, 3))
        self.assertGreaterEqual(r.hour, 9)
        self.assertLess(r.hour, 17)

    def test_risultato_aware(self):
        r = next_business_datetime(self._base(2026, 7, 3))
        self.assertIsNotNone(r.tzinfo)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python django_app\manage.py test django_app.gestione_specifiche.tests.test_date_utils --settings=config.settings.test --keepdb`
Expected: FAIL — `ModuleNotFoundError` / `ImportError: cannot import name 'festivi_it'`.

- [ ] **Step 3: Write the implementation**

Create `django_app/gestione_specifiche/date_utils.py`:

```python
"""Date lavorative per l'auto-approvazione "umanizzata" del MOD.133.

`festivi_it` calcola i festivi nazionali italiani (fissi + Pasquetta) senza dipendenze
esterne; `next_business_datetime` restituisce il primo giorno lavorativo dopo una data,
con un'ora casuale in orario ufficio. Nessun festivo locale/patronale.
"""
from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta

from django.utils import timezone

# Festivi nazionali a data fissa (giorno, mese).
_FISSI = [(1, 1), (6, 1), (25, 4), (1, 5), (2, 6), (15, 8), (1, 11), (8, 12), (25, 12), (26, 12)]


def _pasqua(anno: int) -> date:
    """Domenica di Pasqua (computus di Gauss/Meeus, calendario gregoriano)."""
    a = anno % 19
    b = anno // 100
    c = anno % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mese = (h + l - 7 * m + 114) // 31
    giorno = ((h + l - 7 * m + 114) % 31) + 1
    return date(anno, mese, giorno)


def festivi_it(anno: int) -> set[date]:
    """Festivi nazionali italiani dell'anno: fissi + Pasquetta (lunedì dopo Pasqua)."""
    giorni = {date(anno, mese, giorno) for giorno, mese in _FISSI}
    giorni.add(_pasqua(anno) + timedelta(days=1))  # Pasquetta
    return giorni


def _e_lavorativo(d: date) -> bool:
    return d.weekday() < 5 and d not in festivi_it(d.year)


def next_business_datetime(base: datetime) -> datetime:
    """Primo giorno lavorativo dopo `base`, con ora casuale in [9:00, 17:00).

    Salta sabato, domenica e festivi nazionali (Pasquetta inclusa). Ritorna un
    `datetime` *aware* nella timezone corrente.
    """
    giorno = base.date() + timedelta(days=1)
    while not _e_lavorativo(giorno):
        giorno += timedelta(days=1)
    ora = time(hour=random.randint(9, 16), minute=random.randint(0, 59), second=random.randint(0, 59))
    return timezone.make_aware(datetime.combine(giorno, ora))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python django_app\manage.py test django_app.gestione_specifiche.tests.test_date_utils --settings=config.settings.test --keepdb`
Expected: PASS (7 test).

- [ ] **Step 5: Commit**

```bash
git add django_app/gestione_specifiche/date_utils.py django_app/gestione_specifiche/tests/test_date_utils.py
git commit -m "feat(gestione_specifiche): helper date lavorative (festivi IT + next_business_datetime)"
```

---

## Task 2: Data fittizia nell'auto-approvazione (`_auto_approva_se_configurata`)

**Files:**
- Modify: `django_app/gestione_specifiche/views.py:406-440`
- Test: `django_app/gestione_specifiche/tests/test_admin.py`

**Interfaces:**
- Consumes: `date_utils.next_business_datetime` (Task 1).
- Produces: `mod.data_approvazione` = primo giorno lavorativo dopo `data_chiusura_compilazione`; evento `auto_approvazione` con `data_approvazione` nel payload; evento `approva_flow_down` con **timestamp reale**.

- [ ] **Step 1: Write the failing test**

Aggiungi in `django_app/gestione_specifiche/tests/test_admin.py`, dentro la classe `AdminSectionTest` (dopo `test_auto_approvazione_al_procedi`):

```python
    def test_auto_approvazione_data_fittizia(self):
        from datetime import timedelta

        from gestione_specifiche.date_utils import festivi_it

        cfg = AutoApprovazioneConfig.get_config()
        cfg.attiva = True
        cfg.approvatore = self.mso
        cfg.save()
        spec = self._spec_flow_down("SP-FITT")
        self.client.post(reverse("gestione_specifiche:mod133_chiudi", args=[spec.pk]), {"vai": "approva"})
        mod = MOD133.objects.get(specifica=spec)

        # data_approvazione valorizzata, strettamente dopo la compilazione, in giorno lavorativo
        self.assertIsNotNone(mod.data_approvazione)
        self.assertGreater(mod.data_approvazione, mod.data_chiusura_compilazione)
        d = mod.data_approvazione.date()
        self.assertLess(d.weekday(), 5)
        self.assertNotIn(d, festivi_it(d.year))
        # è il PRIMO giorno lavorativo dopo la compilazione (nessun giorno feriale saltato)
        self.assertGreaterEqual((d - mod.data_chiusura_compilazione.date()), timedelta(days=1))

        # audit onesto: l'evento di transizione mantiene il timestamp reale (≈ adesso, non futuro)
        ev = EventoSpecifica.objects.get(specifica=spec, trigger="approva_flow_down")
        self.assertLess(ev.timestamp, mod.data_approvazione)
        # il marcatore interno porta la data fittizia nel payload
        auto = EventoSpecifica.objects.get(specifica=spec, trigger="auto_approvazione")
        self.assertIn("data_approvazione", auto.payload)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python django_app\manage.py test django_app.gestione_specifiche.tests.test_admin.AdminSectionTest.test_auto_approvazione_data_fittizia --settings=config.settings.test --keepdb`
Expected: FAIL — `data_approvazione` è `now()` (uguale a `data_chiusura_compilazione`), quindi `assertGreater` fallisce; e `auto.payload` non contiene `data_approvazione`.

- [ ] **Step 3: Modify `_auto_approva_se_configurata`**

In `django_app/gestione_specifiche/views.py`, nel corpo di `_auto_approva_se_configurata` (attuale blocco `views.py:412-429`), sostituisci:

```python
    cfg = AutoApprovazioneConfig.get_config()
    if not cfg.attiva or not cfg.approvatore_id:
        return False
    nome = cfg.approvatore.get_full_name() or cfg.approvatore.username
    try:
        with transaction.atomic():
            mod.approvatore_id = cfg.approvatore_id
            mod.esito = C.ESITO_APPROVATO
            mod.data_approvazione = timezone.now()
            mod.save(update_fields=["approvatore", "esito", "data_approvazione", "updated_at"])
            spec.approva_flow_down(attore=cfg.approvatore)
            spec.save()
            EventoSpecifica.objects.create(
                specifica=spec, stato_da=C.STATO_FLOW_DOWN, stato_a=spec.stato, attore=request.user,
                trigger="auto_approvazione",
                payload={"auto": True, "per_conto_di": nome,
                         "avviata_da": (request.user.get_full_name() or request.user.username)},
            )
```

con:

```python
    cfg = AutoApprovazioneConfig.get_config()
    if not cfg.attiva or not cfg.approvatore_id:
        return False
    nome = cfg.approvatore.get_full_name() or cfg.approvatore.username
    # Data di approvazione "umanizzata": primo giorno lavorativo dopo la compilazione,
    # ora casuale in orario ufficio. Vive SOLO sul campo documento (mod.data_approvazione):
    # l'audit immutabile EventoSpecifica NON viene toccato.
    from .date_utils import next_business_datetime

    base = mod.data_chiusura_compilazione or timezone.now()
    data_appr = next_business_datetime(base)
    try:
        with transaction.atomic():
            mod.approvatore_id = cfg.approvatore_id
            mod.esito = C.ESITO_APPROVATO
            mod.data_approvazione = data_appr
            mod.save(update_fields=["approvatore", "esito", "data_approvazione", "updated_at"])
            spec.approva_flow_down(attore=cfg.approvatore)
            spec.save()
            EventoSpecifica.objects.create(
                specifica=spec, stato_da=C.STATO_FLOW_DOWN, stato_a=spec.stato, attore=request.user,
                trigger="auto_approvazione",
                payload={"auto": True, "per_conto_di": nome,
                         "avviata_da": (request.user.get_full_name() or request.user.username),
                         "data_approvazione": data_appr.isoformat()},
            )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python django_app\manage.py test django_app.gestione_specifiche.tests.test_admin.AdminSectionTest.test_auto_approvazione_data_fittizia --settings=config.settings.test --keepdb`
Expected: PASS.

- [ ] **Step 5: Run the existing auto-approval tests (no regression)**

Run: `python django_app\manage.py test django_app.gestione_specifiche.tests.test_admin --settings=config.settings.test --keepdb`
Expected: PASS (inclusi `test_auto_approvazione_al_procedi`, `test_procedi_senza_auto_va_alla_pagina_approva`).

- [ ] **Step 6: Commit**

```bash
git add django_app/gestione_specifiche/views.py django_app/gestione_specifiche/tests/test_admin.py
git commit -m "feat(gestione_specifiche): auto-approvazione con data +1 giorno lavorativo (audit onesto)"
```

---

## Task 3: Timeline utente "umanizzata" (nasconde `auto_approvazione`, mostra data fittizia)

**Files:**
- Create: `django_app/gestione_specifiche/timeline.py`
- Modify: `django_app/gestione_specifiche/views.py:241` (dettaglio) e `views.py:689` (scheda_storico)
- Modify: `django_app/gestione_specifiche/templates/gestione_specifiche/dettaglio.html:287`
- Modify: `django_app/gestione_specifiche/templates/gestione_specifiche/scheda_storico.html:47`
- Test: `django_app/gestione_specifiche/tests/test_timeline.py`

**Interfaces:**
- Consumes: `Specifica.eventi` (related manager), `MOD133.data_approvazione`.
- Produces: `timeline.eventi_umanizzati(spec, mod=None, *, limit=None) -> list` — eventi (escluso `auto_approvazione`), ciascuno con l'attributo `ts_display` (datetime da mostrare).

- [ ] **Step 1: Write the failing test**

Create `django_app/gestione_specifiche/tests/test_timeline.py`:

```python
"""Test timeline 'umanizzata': nasconde auto_approvazione, mostra data_approvazione."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from gestione_specifiche import constants as C
from gestione_specifiche.models import AutoApprovazioneConfig, MOD133, Specifica
from gestione_specifiche.timeline import eventi_umanizzati

User = get_user_model()


class TimelineUmanizzataTest(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("tl_su", "s@x.it", "x")
        self.mso = User.objects.create_user("tl_mso", "m@x.it", "x", first_name="Mario", last_name="MSO")
        self.client.force_login(self.su)
        cfg = AutoApprovazioneConfig.get_config()
        cfg.attiva = True
        cfg.approvatore = self.mso
        cfg.save()
        self.spec = Specifica.objects.create(codice="TL-1", titolo="T")
        self.spec.avvia_flow_down(attore=self.su)
        self.spec.save()
        self.client.post(reverse("gestione_specifiche:mod133_chiudi", args=[self.spec.pk]), {"vai": "approva"})
        self.mod = MOD133.objects.get(specifica=self.spec)

    def test_helper_esclude_auto_e_annota_ts_display(self):
        eventi = eventi_umanizzati(self.spec, self.mod)
        trigger = [e.trigger for e in eventi]
        self.assertNotIn("auto_approvazione", trigger)
        appr = next(e for e in eventi if e.trigger == "approva_flow_down")
        # la riga di approvazione mostra la data fittizia (documento), non il timestamp reale
        self.assertEqual(appr.ts_display, self.mod.data_approvazione)
        self.assertNotEqual(appr.ts_display, appr.timestamp)

    def test_dettaglio_non_espone_auto_approvazione(self):
        r = self.client.get(reverse("gestione_specifiche:dettaglio", args=[self.spec.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "auto_approvazione")

    def test_scheda_storico_non_espone_auto_approvazione(self):
        r = self.client.get(reverse("gestione_specifiche:scheda_storico", args=[self.spec.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "auto_approvazione")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python django_app\manage.py test django_app.gestione_specifiche.tests.test_timeline --settings=config.settings.test --keepdb`
Expected: FAIL — `ImportError` su `eventi_umanizzati` (modulo assente).

- [ ] **Step 3: Create the helper module**

Create `django_app/gestione_specifiche/timeline.py`:

```python
"""Timeline eventi 'umanizzata' per le viste utente (dettaglio, scheda storico).

Nasconde il marcatore interno `auto_approvazione` (resta nelle viste admin) e, sulla riga
di approvazione, mostra la data di record `mod.data_approvazione` invece del timestamp reale
dell'evento immutabile. Non modifica il database: annota solo un attributo di comodo
`ts_display` (senza underscore iniziale, richiesto dai template Django).
"""
from __future__ import annotations

from . import constants as C

TRIGGER_AUTO = "auto_approvazione"
TRIGGER_APPROVAZIONE = "approva_flow_down"


def eventi_umanizzati(spec, mod=None, *, limit=None):
    """Eventi della specifica per la timeline utente.

    - esclude gli eventi `auto_approvazione` (traccia interna, solo admin);
    - annota `ts_display`: per la riga di approvazione (`approva_flow_down` verso
      `in_validita`) = `mod.data_approvazione`; per gli altri = `timestamp` reale.
    """
    qs = spec.eventi.exclude(trigger=TRIGGER_AUTO)
    eventi = list(qs[:limit] if limit else qs)
    data_appr = getattr(mod, "data_approvazione", None) if mod is not None else None
    for e in eventi:
        if data_appr and e.trigger == TRIGGER_APPROVAZIONE and e.stato_a == C.STATO_IN_VALIDITA:
            e.ts_display = data_appr
        else:
            e.ts_display = e.timestamp
    return eventi
```

- [ ] **Step 4: Wire the helper into the two views**

In `django_app/gestione_specifiche/views.py`, dentro `dettaglio` (context, attuale `views.py:241`), sostituisci:

```python
        "eventi": spec.eventi.all()[:50],
```

con:

```python
        "eventi": eventi_umanizzati(spec, mod, limit=50),
```

Dentro `scheda_storico` (context, attuale `views.py:689`), sostituisci:

```python
        "eventi": spec.eventi.all(),
```

con:

```python
        "eventi": eventi_umanizzati(spec, mod),
```

Aggiungi l'import in cima a `views.py` (vicino agli altri import locali dell'app):

```python
from .timeline import eventi_umanizzati
```

- [ ] **Step 5: Update the templates to use `ts_display`**

In `templates/gestione_specifiche/dettaglio.html:287` sostituisci:

```html
              <div class="gs-tl__when">{{ e.timestamp|date:"d/m/Y H:i" }}</div>
```

con:

```html
              <div class="gs-tl__when">{{ e.ts_display|date:"d/m/Y H:i" }}</div>
```

In `templates/gestione_specifiche/scheda_storico.html:47` sostituisci:

```html
              <div class="gs-tl__when">{{ e.timestamp|date:"d/m/Y H:i" }}</div>
```

con:

```html
              <div class="gs-tl__when">{{ e.ts_display|date:"d/m/Y H:i" }}</div>
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `python django_app\manage.py test django_app.gestione_specifiche.tests.test_timeline --settings=config.settings.test --keepdb`
Expected: PASS (3 test).

- [ ] **Step 7: Commit**

```bash
git add django_app/gestione_specifiche/timeline.py django_app/gestione_specifiche/views.py django_app/gestione_specifiche/templates/gestione_specifiche/dettaglio.html django_app/gestione_specifiche/templates/gestione_specifiche/scheda_storico.html django_app/gestione_specifiche/tests/test_timeline.py
git commit -m "feat(gestione_specifiche): timeline utente nasconde auto_approvazione e mostra data di record"
```

---

## Task 4: Timbro RICEVUTO con data reale di ingresso

**Files:**
- Modify: `django_app/gestione_specifiche/composito.py` (`_risolvi_timbri` ~riga 135, `_risolvi_placements` ~riga 152; nuovo helper `_data_ricevuto`)
- Test: `django_app/gestione_specifiche/tests/test_composito.py`

**Interfaces:**
- Produces: `composito._data_ricevuto(spec) -> str` — data del timbro RICEVUTO (`spec.data_inserimento`) formattata `%d/%m/%Y`.

- [ ] **Step 1: Write the failing test**

Aggiungi in `django_app/gestione_specifiche/tests/test_composito.py` una classe di test (in coda al file):

```python
class DataRicevutoTest(TestCase):
    def test_usa_data_inserimento(self):
        from datetime import datetime

        from django.utils.timezone import make_aware

        from gestione_specifiche.composito import _data_ricevuto
        from gestione_specifiche.models import Specifica

        spec = Specifica.objects.create(codice="RIC-1", titolo="T")
        # data_inserimento è auto_now_add: la forziamo a una data storica via update
        Specifica.objects.filter(pk=spec.pk).update(
            data_inserimento=make_aware(datetime(2024, 3, 14, 12, 0)))
        spec.refresh_from_db()
        self.assertEqual(_data_ricevuto(spec), "14/03/2024")
```

Nota: se `test_composito.py` non importa già `TestCase`, aggiungi `from django.test import TestCase` fra gli import in cima al file.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python django_app\manage.py test django_app.gestione_specifiche.tests.test_composito.DataRicevutoTest --settings=config.settings.test --keepdb`
Expected: FAIL — `ImportError: cannot import name '_data_ricevuto'`.

- [ ] **Step 3: Add the helper and use it in both paths**

In `django_app/gestione_specifiche/composito.py`, aggiungi il nuovo helper vicino a `_dati_mod133`/`_risolvi_timbri` (dopo gli import, prima di `_risolvi_timbri`):

```python
def _data_ricevuto(spec) -> str:
    """Data per il timbro RICEVUTO: la data REALE di ingresso della specifica nel portale
    (`data_inserimento`), formattata gg/mm/aaaa. È la data più vecchia della catena
    ricezione ≤ compilazione ≤ approvazione: NON usare `data_approvazione`."""
    from django.utils import timezone

    d = getattr(spec, "data_inserimento", None) or timezone.now()
    try:
        return d.strftime("%d/%m/%Y")
    except Exception:  # noqa: BLE001
        return ""
```

In `_risolvi_timbri` (blocco `return {...}` con `"data_testo": timezone.now().strftime("%d/%m/%Y")`, attuale `composito.py:135`) sostituisci il valore:

```python
        "data_testo": timezone.now().strftime("%d/%m/%Y"),
```

con:

```python
        "data_testo": _data_ricevuto(spec),
```

In `_risolvi_placements` (attuale `composito.py:152`, `data = timezone.now().strftime("%d/%m/%Y")`) sostituisci:

```python
    data = timezone.now().strftime("%d/%m/%Y")
```

con:

```python
    data = _data_ricevuto(spec)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python django_app\manage.py test django_app.gestione_specifiche.tests.test_composito.DataRicevutoTest --settings=config.settings.test --keepdb`
Expected: PASS.

- [ ] **Step 5: Run the composito/timbri suites (no regression)**

Run: `python django_app\manage.py test django_app.gestione_specifiche.tests.test_composito django_app.gestione_specifiche.tests.test_timbri_overlay --settings=config.settings.test --keepdb`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add django_app/gestione_specifiche/composito.py django_app/gestione_specifiche/tests/test_composito.py
git commit -m "feat(gestione_specifiche): timbro RICEVUTO usa la data reale di ingresso (data_inserimento)"
```

---

## Task 5: "Approvato il" nel dettaglio + nota admin + docs

**Files:**
- Modify: `django_app/gestione_specifiche/templates/gestione_specifiche/dettaglio.html` (card MOD.133, ~riga 164)
- Modify: `django_app/gestione_specifiche/templates/gestione_specifiche/admin/auto_approva.html:14` e `:50`
- Modify: `CHANGELOG.md`, `README.md`
- Test: `django_app/gestione_specifiche/tests/test_timeline.py` (estensione)

- [ ] **Step 1: Write the failing test**

Aggiungi in `django_app/gestione_specifiche/tests/test_timeline.py`, dentro `TimelineUmanizzataTest`:

```python
    def test_dettaglio_mostra_approvato_il(self):
        r = self.client.get(reverse("gestione_specifiche:dettaglio", args=[self.spec.pk]))
        self.assertContains(r, "Approvato il")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python django_app\manage.py test django_app.gestione_specifiche.tests.test_timeline.TimelineUmanizzataTest.test_dettaglio_mostra_approvato_il --settings=config.settings.test --keepdb`
Expected: FAIL — il testo "Approvato il" non è presente nel dettaglio.

- [ ] **Step 3: Add the "Approvato il" field to the MOD.133 card**

In `templates/gestione_specifiche/dettaglio.html`, subito dopo la riga "Chiusura compilazione" (attuale `dettaglio.html:164`):

```html
          <span><span class="gs-eyebrow">Chiusura compilazione</span><div style="font-weight:700; color:#0c2545; margin-top:2px;">{{ mod.data_chiusura_compilazione|date:"d/m/Y H:i"|default:"—" }}</div></span>
```

aggiungi:

```html
          <span><span class="gs-eyebrow">Approvato il</span><div style="font-weight:700; color:#0c2545; margin-top:2px;">{{ mod.data_approvazione|date:"d/m/Y H:i"|default:"—" }}</div></span>
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python django_app\manage.py test django_app.gestione_specifiche.tests.test_timeline.TimelineUmanizzataTest.test_dettaglio_mostra_approvato_il --settings=config.settings.test --keepdb`
Expected: PASS.

- [ ] **Step 5: Update the admin note (marcatore solo admin-side)**

In `templates/gestione_specifiche/admin/auto_approva.html:14`, sostituisci il testo:

```html
      <p style="margin:4px 0 0; font-size:12.5px; color:#7c8aa2;">Se attiva, «Procedi con l'approvazione» approva il MOD.133 <strong>automaticamente</strong> a nome dell'MSO — senza attendere un secondo utente. Nel log risulta approvato dall'MSO (con marcatore automatico).</p>
```

con:

```html
      <p style="margin:4px 0 0; font-size:12.5px; color:#7c8aa2;">Se attiva, «Procedi con l'approvazione» approva il MOD.133 <strong>automaticamente</strong> a nome dell'MSO — senza attendere un secondo utente. Per l'utente il MOD.133 risulta approvato dall'MSO con data ~1 giorno lavorativo dopo la compilazione; il <strong>marcatore automatico è visibile solo qui in Amministrazione</strong>.</p>
```

- [ ] **Step 6: Update CHANGELOG.md and README.md**

In `CHANGELOG.md`, sotto `## [Unreleased]`, aggiungi una voce elencando i file toccati:

```markdown
### Changed
- **gestione_specifiche · auto-approvazione MOD.133 "umanizzata"**: l'auto-approvazione ora
  appare all'utente come una normale approvazione dell'MSO, con data ~1 giorno lavorativo
  dopo la compilazione (`data_approvazione`); il marcatore `auto_approvazione` resta solo
  nelle viste Amministrazione (audit immutabile invariato). Il timbro RICEVUTO usa la data
  reale di ingresso (`data_inserimento`). File: `gestione_specifiche/date_utils.py` (nuovo),
  `gestione_specifiche/timeline.py` (nuovo), `gestione_specifiche/views.py`,
  `gestione_specifiche/composito.py`, `templates/.../dettaglio.html`,
  `templates/.../scheda_storico.html`, `templates/.../admin/auto_approva.html`.
```

In `README.md`, nella sezione `<details>` di `gestione_specifiche` (o nella riga del catalogo moduli), aggiorna la descrizione dell'auto-approvazione per riflettere la data "umanizzata" e la traccia solo-admin. (Verifica il testo esistente e adegualo; nessun nuovo URL.)

- [ ] **Step 7: Run the full app suite (scoped)**

Run: `python django_app\manage.py test django_app.gestione_specifiche --settings=config.settings.test --keepdb`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add django_app/gestione_specifiche/templates/gestione_specifiche/dettaglio.html django_app/gestione_specifiche/templates/gestione_specifiche/admin/auto_approva.html django_app/gestione_specifiche/tests/test_timeline.py CHANGELOG.md README.md
git commit -m "feat(gestione_specifiche): dettaglio mostra 'Approvato il' + nota admin + changelog/readme"
```

---

## Definition of Done

- [ ] `python django_app\manage.py test django_app.gestione_specifiche --settings=config.settings.test --keepdb` verde.
- [ ] Nella timeline utente (dettaglio + scheda storico) non compare `auto_approvazione`; l'approvazione mostra l'MSO e una data ~1 giorno lavorativo dopo la compilazione.
- [ ] Viste admin (auto_approva + log) continuano a elencare gli eventi `auto_approvazione` con timestamp reale.
- [ ] Timbro RICEVUTO sul composito riporta la data di `data_inserimento`.
- [ ] `EventoSpecifica` non subisce `.update()` sul timestamp (audit immutabile intatto).
- [ ] CHANGELOG.md e README.md aggiornati.
