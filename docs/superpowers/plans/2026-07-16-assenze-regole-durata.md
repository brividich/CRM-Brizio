# Assenze — Regole durata + rimozione "Riconciliazione" dalla topnav — Piano

> **For agentic workers:** REQUIRED SUB-SKILL: usa superpowers:subagent-driven-development
> (consigliato) o superpowers:executing-plans per eseguire questo piano task-by-task. Gli step
> usano checkbox (`- [ ]`) per il tracking.

**Goal:** rendere autorevoli lato server le regole di durata della richiesta assenza —
**Permesso** 30min–8h nello stesso giorno; **Ferie** più di 1 giorno; **durata rapida** che
consente di cambiare solo la data (orario bloccato sul preset, un solo giorno);
**personalizzato** con orario libero entro i vincoli del tipo — e rimuovere la voce
**"Riconciliazione"** dalla topnav (subnav) del modulo.

**Architecture:** l'unica funzione di validazione condivisa `_validate_business_rules`
(`django_app/assenze/views.py:1009`) viene estesa con il parametro `shortcut` e con le nuove
regole; le costanti (preset + limiti) vivono in `django_app/assenze/constants.py`. Il campo
`shortcut` (già nel form, oggi ignorato) viene letto in `invio_placeholder` e passato alla
validazione. L'enforcement UI (blocco campi orario) è un enhancement non autorevole. La voce
di topnav è un `<a>` hardcodato in `templates/assenze/components/subnav.html` (non un
`NavigationItem`): si rimuove il markup.

**Tech Stack:** Django 5.2, Python 3.11+, SSR + HTMX, SQL Server prod / SQLite test. Test
`django.test.TestCase`/`SimpleTestCase` + `Client`/`RequestFactory`. ORM/SQL SQL-Server-safe.

**Spec:** `docs/superpowers/specs/2026-07-16-assenze-regole-durata-design.md`
(nel checkout `C:\Dev\Portale Novicrom`).

## Global Constraints

- **Worktree dedicato** (Session Isolation CLAUDE.md): mai lavorare/committare nel checkout
  condiviso `C:\Dev\Portale Novicrom`. Task 1 crea `C:\Dev\pn-assenze-regole` su branch
  `feature/assenze-regole-durata` da `origin/main`. Tutti i task hanno cwd = radice del worktree.
- **Mai `git add -A` / `git commit -a`**: staging con percorsi espliciti (il working tree
  condiviso ospita WIP di altre sessioni). **Non committare durante la stesura** se non nei
  passi "Commit" dei task.
- **Venv assoluto**: usare sempre `& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe"`
  (il worktree non ha `.venv`).
- **Nessuna modifica ai modelli → nessuna migrazione** in questo stream. Il DB di test
  `config.settings.test` (SQLite per-PID) è già migrato: usare **sempre `--keepdb`** (run
  istantanee). *Non serve* la prima run senza `--keepdb`.
- Comando test standard (dalla radice del worktree):
  `& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" django_app\manage.py test assenze.tests.<Classe> --settings=config.settings.test --keepdb --verbosity 1`
- **Timeout test ≥ 600000 ms.** Non lanciare la suite intera se non nel task di regressione
  finale (label `assenze`).
- **PowerShell** (Windows): `&` per invocare l'exe quotato; `Set-Location` alla radice del worktree.
- Nuovi test nella classe indicata, in coda a **`django_app/assenze/tests.py`** (esistente).
- **Template Django**: `{# #}` commenta UNA riga; mai attributi/variabili con `_` iniziale.
- **Topnav non hardcodata come regola generale**, ma qui la voce Riconciliazione **è** un `<a>`
  hardcodato in `subnav.html` (non un `NavigationItem`): la rimozione è una edit del template.
- **ACL invariata**: nessun cambiamento ai gate/decoratori; gli endpoint API restano JSON `400/403`.
- **File disgiunti dagli altri stream**: questo stream tocca solo `django_app/assenze/*`
  (+ `CHANGELOG.md`/`README.md` condivisi, append-only, staging esplicito nell'ultimo task).
  Lo stream "visite-giornata" tocca `django_app/anagrafica/*`: **nessun conflitto atteso.**
- **CHANGELOG.md** + **README.md** obbligatori (Task finale). **Niente version bump.**

## Ordine di esecuzione e dipendenze (VINCOLANTE)

Le regole autorevoli vivono in `_validate_business_rules`; il wiring del `shortcut` e la UI le
consumano. Ordine:

1. **Task 1** (worktree) → 2. **Task 2** (costanti + regole in `_validate_business_rules`,
   con i suoi unit test) → 3. **Task 3** (wiring `shortcut` in `invio_placeholder` + fix del
   test ferie preesistente) → 4. **Task 4** (enforcement UI nel template) → 5. **Task 5**
   (rimozione voce topnav) → 6. **Task 6** (CHANGELOG/README + chiusura).

Il Task 3 **dipende** dal Task 2 (la firma estesa e i messaggi d'errore devono esistere). Il
Task 3 **deve** aggiornare `AssenzeSubmitTokenTests.test_invio_ferie_forces_full_day_times`
(`tests.py:616`), che oggi invia una Ferie mono-giorno e diventerà rossa con la regola "Ferie
> 1 giorno". Task 4 e 5 sono indipendenti tra loro ma vanno dopo il 3.

---

### Task 1: Setup worktree

**Files:** solo git.

**Interfaces:**
- Produces: worktree `C:\Dev\pn-assenze-regole` su `feature/assenze-regole-durata`
  (base `origin/main`), cwd di tutti i task.

- [ ] **Step 1: Crea il worktree**

```powershell
Set-Location "C:\Dev\Portale Novicrom"
git fetch origin
git worktree add C:\Dev\pn-assenze-regole -B feature/assenze-regole-durata origin/main
Set-Location C:\Dev\pn-assenze-regole
git status
```

Atteso: `On branch feature/assenze-regole-durata`, tree clean.

- [ ] **Step 2: Verifica venv**

```powershell
& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" --version
```

Atteso: `Python 3.11+`.

---

### Task 2: Costanti + regole durata in `_validate_business_rules`

**Files:**
- Modify: `django_app/assenze/constants.py` (aggiunta costanti)
- Modify: `django_app/assenze/views.py` (`_validate_business_rules`, ~riga 1009: nuova firma
  `shortcut=None` + regole Permesso 30min–8h, Ferie >1 giorno, durata rapida lock-orario)
- Test: `django_app/assenze/tests.py` (nuova classe `AssenzeRegoleDurataTests`)

**Interfaces:**
- Consumes: `constants.SHORTCUT_PRESETS`, `SHORTCUT_CUSTOM`, `PERMESSO_MIN_MINUTES`,
  `PERMESSO_MAX_HOURS`.
- Produces: `_validate_business_rules(..., shortcut=None)`. Il percorso Flessibilità (che
  interroga il DB via `_count_flessibilita_week`) resta invariato; i nuovi test coprono
  Permesso/Ferie/durata rapida che **non** toccano il DB → `SimpleTestCase`.

- [ ] **Step 1: Scrivi i test (nuova classe in coda a `tests.py`)**

Nota: `_validate_business_rules` è già importabile da `assenze.views`. Usare `datetime`.

```python
from datetime import datetime
from django.test import SimpleTestCase
from .views import _validate_business_rules


class AssenzeRegoleDurataTests(SimpleTestCase):
    def _dt(self, s):
        return datetime.strptime(s, "%Y-%m-%d %H:%M")

    # --- Permesso: 30min–8h, stesso giorno -------------------------------
    def test_permesso_oltre_8h_respinto(self):
        err, _ = _validate_business_rules(
            tipo="Permesso",
            dt_start=self._dt("2026-03-10 08:00"),
            dt_end=self._dt("2026-03-10 17:00"),  # 9h
        )
        self.assertTrue(err)
        self.assertIn("8 ore", err)

    def test_permesso_sotto_30min_respinto(self):
        err, _ = _validate_business_rules(
            tipo="Permesso",
            dt_start=self._dt("2026-03-10 08:00"),
            dt_end=self._dt("2026-03-10 08:20"),  # 20min
        )
        self.assertTrue(err)

    def test_permesso_4h_ok(self):
        err, _ = _validate_business_rules(
            tipo="Permesso",
            dt_start=self._dt("2026-03-10 08:00"),
            dt_end=self._dt("2026-03-10 12:00"),
        )
        self.assertEqual(err, "")

    def test_permesso_multi_giorno_respinto(self):
        err, _ = _validate_business_rules(
            tipo="Permesso",
            dt_start=self._dt("2026-03-10 08:00"),
            dt_end=self._dt("2026-03-11 09:00"),
        )
        self.assertTrue(err)

    # --- Ferie: più di 1 giorno -----------------------------------------
    def test_ferie_un_giorno_respinta(self):
        err, _ = _validate_business_rules(
            tipo="Ferie",
            dt_start=self._dt("2026-03-12 00:00"),
            dt_end=self._dt("2026-03-12 23:59"),
        )
        self.assertTrue(err)
        self.assertIn("un giorno", err)

    def test_ferie_due_giorni_ok(self):
        err, _ = _validate_business_rules(
            tipo="Ferie",
            dt_start=self._dt("2026-03-12 00:00"),
            dt_end=self._dt("2026-03-13 23:59"),
        )
        self.assertEqual(err, "")

    # --- Durata rapida: solo la data ------------------------------------
    def test_durata_rapida_orario_alterato_respinto(self):
        err, _ = _validate_business_rules(
            tipo="Permesso",
            dt_start=self._dt("2026-03-10 06:00"),
            dt_end=self._dt("2026-03-10 15:00"),  # preset mattina = 06:00-14:00
            shortcut="mattina",
        )
        self.assertTrue(err)
        self.assertIn("solo la data", err)

    def test_durata_rapida_solo_data_ok(self):
        err, _ = _validate_business_rules(
            tipo="Permesso",
            dt_start=self._dt("2026-03-10 06:00"),
            dt_end=self._dt("2026-03-10 14:00"),  # combacia col preset mattina (8h)
            shortcut="mattina",
        )
        self.assertEqual(err, "")

    def test_durata_rapida_multi_giorno_respinto(self):
        err, _ = _validate_business_rules(
            tipo="Permesso",
            dt_start=self._dt("2026-03-10 06:00"),
            dt_end=self._dt("2026-03-11 14:00"),
            shortcut="mattina",
        )
        self.assertTrue(err)

    def test_custom_permesso_orario_libero_ok(self):
        err, _ = _validate_business_rules(
            tipo="Permesso",
            dt_start=self._dt("2026-03-10 09:15"),
            dt_end=self._dt("2026-03-10 13:45"),  # 4h30
            shortcut="custom",
        )
        self.assertEqual(err, "")
```

- [ ] **Step 2: Run test → FALLISCE**

```powershell
& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" django_app\manage.py test assenze.tests.AssenzeRegoleDurataTests --settings=config.settings.test --keepdb --verbosity 1
```

Atteso: `TypeError` (kwarg `shortcut` sconosciuto) e/o assert falliti (permesso 9h oggi
passa, ferie 1 giorno oggi passa).

- [ ] **Step 3: Implementa costanti + regole**

(a) In `constants.py`, in coda, aggiungi:

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

# Limiti Permesso (stesso giorno). "0.30h" = 30 minuti (vedi spec).
PERMESSO_MIN_MINUTES = 30
PERMESSO_MAX_HOURS = 8
```

(b) In `views.py`, estendi l'import esistente da `.constants`:

```python
from .constants import (
    TIPI_ASSENZA_STORAGE, TIPI_ASSENZA_UI,
    SHORTCUT_PRESETS, SHORTCUT_CUSTOM, PERMESSO_MIN_MINUTES, PERMESSO_MAX_HOURS,
)
```

(c) In `_validate_business_rules` (`~riga 1009`), aggiungi il kwarg `shortcut=None` alla
firma e inserisci i blocchi **dopo** i controlli obbligatori esistenti (dopo il check
`dt_end <= dt_start`), prima/attorno ai rami per-tipo:

```python
    # Durata rapida: l'utente può cambiare solo la data, non l'orario.
    shortcut_key = str(shortcut or "").strip().lower()
    if shortcut_key and shortcut_key != SHORTCUT_CUSTOM:
        preset = SHORTCUT_PRESETS.get(shortcut_key)
        if preset is None:
            return "Durata rapida non valida.", ""
        if dt_start.date() != dt_end.date():
            return "Con una durata rapida la richiesta deve restare nello stesso giorno.", ""
        if (dt_start.strftime("%H:%M"), dt_end.strftime("%H:%M")) != preset:
            return "Con una durata rapida puoi modificare solo la data, non l'orario.", ""
```

Nel ramo `tipo_ui == "Permesso"` (che oggi controlla solo lo stesso giorno) aggiungi il
limite durata:

```python
    if tipo_ui == "Permesso":
        if dt_start.date() != dt_end.date():
            return "Il permesso deve iniziare e finire nello stesso giorno.", ""
        minutes = (dt_end - dt_start).total_seconds() / 60.0
        if minutes < PERMESSO_MIN_MINUTES or minutes > PERMESSO_MAX_HOURS * 60:
            return "Il permesso deve durare tra 30 minuti e 8 ore.", ""
```

Nel ramo `tipo_ui == "Ferie"` sostituisci il check `dt_end.date() < dt_start.date()` con lo
span > 1 giorno (mantenendo il vincolo orari interi 00:00–23:59 già presente):

```python
    if tipo_ui == "Ferie":
        if dt_end.date() <= dt_start.date():
            return "Le ferie devono coprire più di un giorno.", ""
        if (dt_start.hour, dt_start.minute, dt_end.hour, dt_end.minute) != (0, 0, 23, 59):
            return "Le ferie devono coprire giornate intere: orario 00:00-23:59.", ""
```

Flessibilità: invariata.

- [ ] **Step 4: Run test → PASSA**

Comando standard su `assenze.tests.AssenzeRegoleDurataTests`. Atteso: `OK`, 10 test.

- [ ] **Step 5: Commit**

```powershell
git add django_app/assenze/constants.py django_app/assenze/views.py django_app/assenze/tests.py
git commit -m "feat(assenze): regole durata autorevoli - Permesso 30min-8h, Ferie >1 giorno, durata rapida lock-orario"
```

---

### Task 3: Wiring `shortcut` in `invio_placeholder` + fix test ferie preesistente

**Files:**
- Modify: `django_app/assenze/views.py` (`invio_placeholder`, ~riga 4412: leggere `shortcut`
  dal POST e passarlo a `_validate_business_rules`, ~riga 4486)
- Modify: `django_app/assenze/tests.py` (nuova classe integrazione + fix del test ferie mono-giorno)

**Interfaces:**
- Consumes: `_validate_business_rules(..., shortcut=...)` (Task 2).
- Produces: creazione richiesta che rifiuta i payload fuori regola anche via HTTP.

- [ ] **Step 1: Scrivi i test (integrazione, in coda a `tests.py`)**

Riusa lo stesso harness di `AssenzeSubmitTokenTests` (`Client` + `_build_submit_token` +
mock dei permessi e dei resolver). Nuova classe:

```python
class AssenzeInvioRegoleDurataTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="assenze-regole-user", password="pass12345")
        UserOnboarding.objects.create(user=self.user, completed=True, completed_at=timezone.now())

    def _token(self):
        session = self.client.session
        request = type("Req", (), {"user": self.user, "session": session})()
        return _build_submit_token(request, "assenze_invio")

    @patch("assenze.views._render_richiesta", return_value=HttpResponse("error"))
    @patch("assenze.views._insert_assenza", return_value=1)
    @patch("assenze.views._table_exists", return_value=True)
    @patch("assenze.views._assenze_permissions", return_value={"can_insert": True, "can_skip_approval": False})
    def test_invio_durata_rapida_orario_manomesso_respinto(
        self, _mock_perms, _mock_table_exists, mock_insert, mock_render,
    ):
        self.client.force_login(self.user)
        resp = self.client.post(reverse("assenze_invio"), {
            "submit_token": self._token(),
            "tipoassenza": "Permesso",
            "motivazione": "Motivo",
            "shortcut": "mattina",          # preset 06:00-14:00
            "date_start": "2026-03-10",
            "date_end": "2026-03-10",
            "time_start": "06:00",
            "time_end": "15:00",            # orario alterato
            "caporeparto": "",
        })
        self.assertEqual(resp.status_code, 200)
        mock_insert.assert_not_called()
        self.assertIn("solo la data", mock_render.call_args.kwargs["error"])

    @patch("assenze.views._render_richiesta", return_value=HttpResponse("error"))
    @patch("assenze.views._insert_assenza", return_value=1)
    @patch("assenze.views._table_exists", return_value=True)
    @patch("assenze.views._assenze_permissions", return_value={"can_insert": True, "can_skip_approval": False})
    def test_invio_permesso_oltre_8h_respinto(
        self, _mock_perms, _mock_table_exists, mock_insert, mock_render,
    ):
        self.client.force_login(self.user)
        resp = self.client.post(reverse("assenze_invio"), {
            "submit_token": self._token(),
            "tipoassenza": "Permesso",
            "motivazione": "Motivo",
            "shortcut": "custom",
            "date_start": "2026-03-10",
            "date_end": "2026-03-10",
            "time_start": "08:00",
            "time_end": "17:00",            # 9h
            "caporeparto": "",
        })
        self.assertEqual(resp.status_code, 200)
        mock_insert.assert_not_called()
        self.assertIn("8 ore", mock_render.call_args.kwargs["error"])
```

(Import necessari — `HttpResponse`, `patch`, `reverse`, `timezone`, `get_user_model`,
`UserOnboarding`, `_build_submit_token` — sono già in testa a `tests.py`.)

- [ ] **Step 2: Run test → FALLISCE**

Comando standard su `assenze.tests.AssenzeInvioRegoleDurataTests`. Atteso: FAIL — oggi
`invio_placeholder` ignora `shortcut` (l'orario manomesso passa) e non applica il limite 8h.

- [ ] **Step 3: Wiring in `invio_placeholder`**

In `invio_placeholder` (`~riga 4426`), leggi il preset dal POST:

```python
    shortcut = str(request.POST.get("shortcut") or "").strip()
```

e nella chiamata a `_validate_business_rules` (`~riga 4486`) aggiungi `shortcut=shortcut`:

```python
    err_msg, warn_msg = _validate_business_rules(
        tipo=tipo,
        dt_start=dt_start,
        dt_end=dt_end,
        person_name=display_name,
        person_email=email,
        shortcut=shortcut,
    )
```

(Non toccare `api_evento_update`/`api_mia_assenza_update`: restano senza `shortcut` → percorso
custom, ma ora ereditano comunque le nuove regole Permesso/Ferie.)

- [ ] **Step 4: Aggiorna il test ferie mono-giorno preesistente (ora rosso)**

In `AssenzeSubmitTokenTests.test_invio_ferie_forces_full_day_times` (`tests.py:616`), il POST
invia `date_start` = `date_end` = `2026-03-12`. Con la regola "Ferie > 1 giorno" verrebbe
respinto. Cambia `"date_end": "2026-03-12"` → `"date_end": "2026-03-13"`. Le asserzioni
(orari forzati a `00:00`/`23:59`) restano valide: `data_fine` = 13/03 23:59.

- [ ] **Step 5: Run test → PASSA (nuovi + ferie fix + regressione della classe token)**

```powershell
& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" django_app\manage.py test assenze.tests.AssenzeInvioRegoleDurataTests assenze.tests.AssenzeSubmitTokenTests --settings=config.settings.test --keepdb --verbosity 1
```

Atteso: `OK`. In particolare `test_invio_ferie_forces_full_day_times` e
`test_invio_rejects_permesso_across_multiple_days` restano verdi.

- [ ] **Step 6: Commit**

```powershell
git add django_app/assenze/views.py django_app/assenze/tests.py
git commit -m "feat(assenze): invio legge shortcut e applica lock-orario durata rapida; fix test ferie a periodo >1 giorno"
```

---

### Task 4: Enforcement UI — blocco campi orario su durata rapida

**Files:**
- Modify: `django_app/assenze/templates/assenze/pages/richiesta_assenze.html` (handler radio
  `shortcut` ~righe 1346-1359 e/o `applyTypeDefaults` ~righe 1075-1095; mirror regole nel
  submit handler ~righe 1387-1485)
- Test: `django_app/assenze/tests.py` (render check, in coda alla classe token o nuova classe)

**Interfaces:**
- Consumes: nulla di nuovo lato server (UX non autorevole; il server è già a posto dal Task 3).
- Produces: quando è selezionato un preset (≠ `custom`), i campi `time_start`/`time_end`
  diventano `readOnly`; con `custom` tornano editabili.

- [ ] **Step 1: Scrivi il test (render, in coda a `tests.py`)**

Il comportamento è JS: si verifica in modo leggero che la pagina esponga il radio `shortcut`
e i campi orario (aggancio JS presente), senza testare il DOM runtime.

```python
class AssenzeRichiestaShortcutRenderTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="assenze-ui-user", password="pass12345")
        UserOnboarding.objects.create(user=self.user, completed=True, completed_at=timezone.now())

    @patch("assenze.views._template_perm_context", return_value={})
    @patch("assenze.views._load_motivazioni_local", return_value=["Motivo"])
    @patch("assenze.views._graph_get_motivazioni", return_value=[])
    @patch("assenze.views._load_capi_options", return_value=[])
    @patch("assenze.views._resolve_default_capo_for_user", return_value="")
    @patch("assenze.views._legacy_identity", return_value=("Mario Rossi", "mario@example.com", 77))
    @patch("assenze.views._assenze_permissions", return_value={"can_insert": True, "can_skip_approval": False})
    def test_form_espone_shortcut_e_campi_orario(self, *_mocks):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("assenze_richiesta"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'name="shortcut"')
        self.assertContains(resp, 'id="time_start"')
        self.assertContains(resp, 'id="time_end"')
```

- [ ] **Step 2: Run test → PASSA subito** (il markup esiste già)

Comando standard su `assenze.tests.AssenzeRichiestaShortcutRenderTests`. Atteso: `OK`. Questo
test è una **guardia di non-regressione** del markup su cui il JS si aggancia (se un refactor
rimuove i campi, il JS di blocco si rompe silenziosamente).

- [ ] **Step 3: Implementa il blocco orari (JS)**

Nel blocco `<script>` di `richiesta_assenze.html`, aggiungi una funzione che riflette lo stato
del preset sui campi orario e chiamala dall'handler dei radio `shortcut` (e all'init):

```javascript
    function applyShortcutLock() {
      var checked = document.querySelector('input[name="shortcut"]:checked');
      var isCustom = !checked || checked.value === "custom";
      // Ferie gestisce già i propri orari (readOnly) in applyTypeDefaults().
      if (isFerie()) return;
      if (startInput) startInput.readOnly = !isCustom;
      if (endInput) endInput.readOnly = !isCustom;
    }
```

Nell'handler già presente `document.querySelectorAll('input[name="shortcut"]')...change`
(righe ~1346-1359), dopo aver impostato `startInput.value`/`endInput.value`, chiama
`applyShortcutLock();`. Chiama `applyShortcutLock()` anche in coda a `switchForm()` e una volta
all'init (dopo `updateDynamicPreview()`), così lo stato iniziale (default `custom`) è coerente.

(Opzionale UX) nel submit handler, oltre ai check esistenti, aggiungi il mirror non
bloccante-lato-server delle nuove regole (Permesso 30min–8h; Ferie che deve superare 1
giorno) con `evt.preventDefault()` + `window.alert(...)`. La validazione autorevole resta il
server (Task 2/3).

Vincoli template: `{# #}` solo mono-riga; nessun attributo con `_` iniziale.

- [ ] **Step 4: Run test → PASSA** (render invariato; nessuna regressione)

Comando standard su `assenze.tests.AssenzeRichiestaShortcutRenderTests`.

- [ ] **Step 5: Verifica manuale (raccomandata)**

Avvia il dev server e sulla pagina "Nuova richiesta": selezionando `Mattina` i campi Ora
inizio/fine diventano non editabili e cambiando `Personalizzato` tornano editabili.

```powershell
& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" django_app\manage.py runserver --settings=config.settings.dev
```

- [ ] **Step 6: Commit**

```powershell
git add django_app/assenze/templates/assenze/pages/richiesta_assenze.html django_app/assenze/tests.py
git commit -m "feat(assenze): UI - blocca i campi orario quando è attiva una durata rapida (solo la data è modificabile)"
```

---

### Task 5: Rimuovi "Riconciliazione" dalla topnav (subnav)

**Files:**
- Modify: `django_app/assenze/templates/assenze/components/subnav.html` (rimozione blocco
  `{% if assenze_can_reconcile %}` righe 26-30)
- Test: `django_app/assenze/tests.py` (render subnav senza la voce)

**Interfaces:**
- Produces: la subnav non mostra più la voce "Riconciliazione". Route/view `riconciliazione`
  restano (raggiungibili via URL; fuori scope la loro rimozione).

- [ ] **Step 1: Scrivi il test (render diretto del template, in coda a `tests.py`)**

Renderizza la subnav con `assenze_can_reconcile=True`: la voce non deve comparire.

```python
from django.template.loader import render_to_string
from django.test import RequestFactory

class AssenzeSubnavTests(SimpleTestCase):
    def test_subnav_non_mostra_riconciliazione(self):
        rf = RequestFactory()
        request = rf.get("/assenze/")
        html = render_to_string(
            "assenze/components/subnav.html",
            {
                "assenze_can_reconcile": True,
                "assenze_can_view_calendar": True,
                "assenze_can_edit_events": True,
                "assenze_is_admin": True,
            },
            request=request,
        )
        self.assertNotIn("Riconciliazione", html)
        self.assertNotIn("assenze_riconciliazione", html)
```

- [ ] **Step 2: Run test → FALLISCE**

Comando standard su `assenze.tests.AssenzeSubnavTests`. Atteso: FAIL (la voce è ancora presente).

- [ ] **Step 3: Rimuovi il blocco**

In `subnav.html`, elimina le righe 26-30:

```django
  {% if assenze_can_reconcile %}
    <a class="abs-subnav-link{% if current == 'assenze_riconciliazione' %} active{% endif %}" href="{% url 'assenze_riconciliazione' %}">
      <svg aria-hidden="true"><use href="#abs-i-sync"></use></svg>Riconciliazione
    </a>
  {% endif %}
```

(La chiave `assenze_can_reconcile` in `_template_perm_context`, `views.py:939`, resta: diventa
inutilizzata nei template ma la rimozione è fuori scope — annotalo nel commit/CHANGELOG.)

- [ ] **Step 4: Run test → PASSA**

Comando standard su `assenze.tests.AssenzeSubnavTests`. Atteso: `OK`.

- [ ] **Step 5: Commit**

```powershell
git add django_app/assenze/templates/assenze/components/subnav.html django_app/assenze/tests.py
git commit -m "feat(assenze): rimuovi la voce Riconciliazione dalla topnav del modulo (route/view invariate)"
```

---

### Task 6: Regressione + CHANGELOG/README + chiusura

**Files:**
- Modify: `CHANGELOG.md` (condiviso), `README.md` (condiviso) — staging esplicito.

- [ ] **Step 1: Regressione dell'app `assenze`**

```powershell
& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" django_app\manage.py test assenze --settings=config.settings.test --keepdb --verbosity 1
```

Atteso: `OK`. Verifica in particolare le classi preesistenti `AssenzeSubmitTokenTests` e
`AssenzeLegacyTipoSubmitMappingTests` (usano payload Permesso/Ferie/Flessibilità).
Se una prova preesistente diventa rossa per le nuove regole, correggi il **dato di test** (non
allentare la regola) e documenta.

- [ ] **Step 2: Aggiorna CHANGELOG.md** (sezione `[Unreleased]`)

Sotto `[Unreleased]`, elenca i file modificati e la descrizione:
- `django_app/assenze/constants.py`, `views.py`: regole durata autorevoli — Permesso 30min–8h
  stesso giorno; Ferie > 1 giorno; durata rapida = solo la data (orario bloccato sul preset,
  un solo giorno); `invio_placeholder` legge `shortcut`.
- `django_app/assenze/templates/assenze/pages/richiesta_assenze.html`: blocco campi orario su
  durata rapida.
- `django_app/assenze/templates/assenze/components/subnav.html`: rimossa la voce
  "Riconciliazione" dalla topnav del modulo.
- `django_app/assenze/tests.py`: nuovi test regole durata/UI/subnav + fix test ferie mono-giorno.

- [ ] **Step 3: Aggiorna README.md**

Nella sezione del modulo `assenze` (tabella catalogo e/o `<details>`), annota le regole di
durata (Permesso 30min–8h stesso giorno; Ferie > 1 giorno; durata rapida modifica solo la
data) e la rimozione della voce "Riconciliazione" dalla topnav del modulo.

- [ ] **Step 4: Commit (staging esplicito dei file condivisi)**

```powershell
git add CHANGELOG.md README.md
git commit -m "docs(assenze): CHANGELOG/README - regole durata assenze e rimozione voce Riconciliazione dalla topnav"
```

- [ ] **Step 5: Push e chiusura**

```powershell
git push -u origin feature/assenze-regole-durata
```

Poi valuta l'integrazione con superpowers:finishing-a-development-branch (merge/PR). Al
termine, se il worktree non serve più:

```powershell
Set-Location "C:\Dev\Portale Novicrom"
git worktree remove C:\Dev\pn-assenze-regole
```

(Se il path è troppo lungo per git: `cmd /c rmdir /s /q C:\Dev\pn-assenze-regole` + `git worktree prune`.)

---

## Note finali

- **0.30h = 30 minuti**: se il committente intende 0,30 ore decimali (18 min), cambiare
  `PERMESSO_MIN_MINUTES` in `constants.py` (un solo punto). Vedi spec, sezione interpretazione.
- **Preset duplicati JS↔Python**: `SHORTCUT_PRESETS` (Python, autorevole) e i preset nel JS del
  template devono restare allineati. Se in futuro cambiano, aggiornare entrambi; valutare un
  test anti-drift che estrae i preset dal template e li confronta con `constants.SHORTCUT_PRESETS`.
- **`assenze_can_reconcile`** resta in `_template_perm_context` (inutilizzato nei template dopo
  il Task 5): pulizia opzionale fuori scope.
- **Pannello admin assenze** (approva/rifiuta/elimina, `gestione_admin`) **non toccato**.
