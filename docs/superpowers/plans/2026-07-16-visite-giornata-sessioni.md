# Visite mediche — "Giornata visite" reattiva, sessioni salvate e proposte di rinnovo — Piano

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** trasformare `/anagrafica/visite-mediche/nuova-sessione/` in una "Giornata visite" reattiva (HTMX) multi-tipo, con un modello `VisitaSessione` salvato (lista+dettaglio+aggiungi-dopo), un hub di proposte di rinnovo, e un pulsante "↻ Rinnovo" per gruppo nello scadenzario — tutti convergenti sul deep-link `?tipo=<id>`.

**Architecture:** modello additivo `VisitaSessione` + FK nullable `VisitaMedica.sessione` (pattern `QualificaSessione`). Il builder giornata **riusa** `_build_candidati_sessione(tipo, oggi)` (già vetato: ruoli+MOD.128, cessati, storico, preselect) iterando i tipi attivi e producendo righe `(persona, tipo)`. La pagina è reattiva via HTMX come `qualifica_sessione_candidati`. Nessuna riscrittura della logica candidati.

**Tech Stack:** Django 5.2, Python 3.11+, HTMX (già in uso), template SSR con stili inline, test `django.test.TestCase` + `RequestFactory`/`Client`. DB prod SQL Server: ORM SQL-Server-safe.

**Spec:** `docs/superpowers/specs/2026-07-16-visite-giornata-sessioni-design.md` (nel checkout `C:\Dev\Portale Novicrom`).

## Global Constraints

- **Worktree dedicato** (Session Isolation CLAUDE.md): mai lavorare/committare nel checkout condiviso `C:\Dev\Portale Novicrom`. Task 1 crea `C:\Dev\pn-visite-giornata` su branch `feature/anagrafica-visite-giornata` da `origin/main`.
- **Mai `git add -A` / `git commit -a`**: staging con percorsi espliciti.
- **Venv**: usare sempre `& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe"` (il worktree non ha `.venv`).
- **Test DB**: `config.settings.test` usa SQLite per-PID sotto `.tmp_tests`. La **prima** run dopo una nuova migrazione richiede DB fresco (**senza `--keepdb`**, ~6-8 min di migrazione); le run successive con `--keepdb` sono **istantanee** (2-3s). Regola: dopo il task del modello, prima run senza `--keepdb`; poi sempre `--keepdb`.
- Comando test (dalla radice del worktree):
  `& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" django_app\manage.py test anagrafica.tests_visite_sessione --settings=config.settings.test --keepdb --verbosity 1`
- **Timeout test ≥ 600000 ms**. Non lanciare la suite intera se non nel task di regressione finale (label `anagrafica`).
- **PowerShell** (Windows): `&` per invocare l'exe quotato; `Set-Location` alla radice del worktree.
- Nuovi test in **`django_app/anagrafica/tests_visite_sessione.py`** (già esistente, si estende).
- **Template Django**: `{# #}` commenta UNA riga; mai chiavi/variabili con `_` iniziale.
- **HTMX progressive enhancement**: il deep-link `?tipo=` rende i candidati lato server (funziona senza JS); HTMX è solo miglioramento.
- **Privacy**: ogni vista gated `_can_view_visite_mediche`. Nessun esito/prescrizione in log/audit (solo conteggi + id sessione).
- **SQL-Server-safe**: niente window function.
- **CHANGELOG.md** + **README.md** obbligatori (Task finale). **Niente version bump** (il repo accumula sotto `[Unreleased]`).
- Riuso obbligatorio (non riscrivere): `_build_candidati_sessione`, `_requisiti_tipo_visita`, `_cessati_legacy_ids`, `_salva_referto_visita`, `ultime_visite_correnti_ids`, `_build_nomi_map`, `_add_months`.

## Ordine di esecuzione e dipendenze (VINCOLANTE)

Le route delle sessioni si referenziano a vicenda (l'hub linka al dettaglio, il
dettaglio linka all'hub) e il POST della giornata fa `redirect()` al dettaglio.
Django risolve `{% url %}`/`redirect(name)` a runtime → una route mancante fa
fallire il test che rende quel template o esegue quel redirect. Regole:

1. Ogni `path()` aggiunto in `urls.py` deve avere la **view definita nello stesso
   commit** (altrimenti l'import di `urls.py` rompe tutto).
2. **Esegui i Task 7 e 8 come UN UNICO blocco** (hub + dettaglio + aggiungi + elimina,
   con **tutte** le loro route registrate insieme), perché i loro template si
   referenziano reciprocamente. Committa pure in due commit, ma aggiungi **entrambe
   le serie di route prima** di lanciare i test di rendering dei due template.
3. **Ordine consigliato**: Task 1 → 2 → 3 → **8 → 7 (blocco sessioni CRUD)** → 4
   (il POST redirige al dettaglio: la route deve già esistere) → 5 → 6 → 9 → 10 →
   11 → 12.

---

### Task 1: Setup worktree

**Files:** solo git.

**Interfaces:**
- Produces: worktree `C:\Dev\pn-visite-giornata` su `feature/anagrafica-visite-giornata` (base `origin/main`), cwd di tutti i task.

- [ ] **Step 1: Crea il worktree**

```powershell
Set-Location "C:\Dev\Portale Novicrom"
git fetch origin
git worktree add C:\Dev\pn-visite-giornata -B feature/anagrafica-visite-giornata origin/main
Set-Location C:\Dev\pn-visite-giornata
git status
```

Atteso: `On branch feature/anagrafica-visite-giornata`, tree clean.

- [ ] **Step 2: Verifica venv**

```powershell
& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" --version
```

Atteso: `Python 3.11+`.

---

### Task 2: Modello `VisitaSessione` + FK `VisitaMedica.sessione` + migrazione

**Files:**
- Modify: `django_app/anagrafica/models.py` (classe `VisitaMedica` ~riga 2154; aggiungere `VisitaSessione` prima di essa e il FK `sessione` dentro `VisitaMedica`)
- Create: `django_app/anagrafica/migrations/00NN_visitasessione.py` (generata)
- Test: `django_app/anagrafica/tests_visite_sessione.py`

**Interfaces:**
- Produces: `anagrafica.models.VisitaSessione` (campi `data_svolgimento`, `medico_competente`, `luogo`, `note`, `created_by`, `created_at`, `updated_at`); `VisitaMedica.sessione` FK nullable `related_name="visite"`. Consumati da tutti i task successivi.

- [ ] **Step 1: Scrivi il test (in coda a `tests_visite_sessione.py`)**

```python
class VisitaSessioneModelTests(TestCase):
    def setUp(self):
        self.oggi = timezone.localdate()
        self.tipo = TipoVisitaMedica.objects.create(nome="Giornata VDT", durata_mesi=12)

    def test_crea_sessione_e_collega_visita(self):
        from .models import VisitaSessione
        sess = VisitaSessione.objects.create(
            data_svolgimento=self.oggi, medico_competente="Dr. Test",
        )
        v = VisitaMedica.objects.create(
            legacy_anagrafica_id=1, tipo=self.tipo,
            data_svolgimento=self.oggi, sessione=sess,
        )
        self.assertEqual(v.sessione_id, sess.pk)
        self.assertEqual(list(sess.visite.all()), [v])

    def test_elimina_sessione_conserva_visite(self):
        from .models import VisitaSessione
        sess = VisitaSessione.objects.create(
            data_svolgimento=self.oggi, medico_competente="Dr. Test",
        )
        v = VisitaMedica.objects.create(
            legacy_anagrafica_id=2, tipo=self.tipo,
            data_svolgimento=self.oggi, sessione=sess,
        )
        sess.delete()
        v.refresh_from_db()
        self.assertIsNone(v.sessione_id)  # SET_NULL: la visita resta
```

- [ ] **Step 2: Run test → FALLISCE**

```powershell
& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" django_app\manage.py test anagrafica.tests_visite_sessione.VisitaSessioneModelTests --settings=config.settings.test --keepdb --verbosity 1
```

Atteso: `ImportError: cannot import name 'VisitaSessione'`.

- [ ] **Step 3: Implementa il modello**

In `models.py`, subito PRIMA di `class VisitaMedica(models.Model):`, aggiungi:

```python
class VisitaSessione(models.Model):
    """Giornata di visite del medico competente: data + medico + un elenco di
    visite (di tipi anche diversi) registrate insieme. Le ``VisitaMedica`` vi si
    collegano via FK ``sessione`` (nullable): eliminare la sessione NON elimina
    le visite (SET_NULL), lo storico clinico resta."""

    data_svolgimento = models.DateField()
    medico_competente = models.CharField(max_length=200, blank=True, default="")
    luogo = models.CharField(max_length=200, blank=True, default="")
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="visite_sessioni_create",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-data_svolgimento", "-id"]
        verbose_name = "Sessione visite mediche"
        verbose_name_plural = "Sessioni visite mediche"

    def __str__(self) -> str:
        return f"Giornata {self.data_svolgimento} — {self.medico_competente or '—'}"
```

Poi, DENTRO `class VisitaMedica`, subito dopo il campo `referto_documento = models.ForeignKey(...)` (prima di `created_at`), aggiungi:

```python
    sessione = models.ForeignKey(
        VisitaSessione,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="visite",
        help_text="Giornata visite in cui è stata registrata (opzionale).",
    )
```

- [ ] **Step 4: Genera la migrazione**

```powershell
Set-Location C:\Dev\pn-visite-giornata
& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" django_app\manage.py makemigrations anagrafica --settings=config.settings.test
```

Atteso: crea `00NN_visitasessione.py` (CreateModel VisitaSessione + AddField sessione). Annota il nome file.

- [ ] **Step 5: Run test → PASSA (DB FRESCO, senza --keepdb)**

```powershell
& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" django_app\manage.py test anagrafica.tests_visite_sessione.VisitaSessioneModelTests --settings=config.settings.test --verbosity 1
```

Atteso: `OK`, 2 test. (Prima run senza `--keepdb`: rimigra ~6-8 min — normale.)

- [ ] **Step 6: Commit**

```powershell
git add django_app/anagrafica/models.py django_app/anagrafica/migrations/00NN_visitasessione.py django_app/anagrafica/tests_visite_sessione.py
git commit -m "feat(anagrafica): modello VisitaSessione + FK VisitaMedica.sessione (giornata visite)"
```

---

### Task 3: Builder candidati "giornata" (`_build_candidati_giornata`)

**Files:**
- Modify: `django_app/anagrafica/views.py` (aggiungere l'helper subito dopo `_build_candidati_sessione`, che finisce ~riga 10035)
- Test: `django_app/anagrafica/tests_visite_sessione.py`

**Interfaces:**
- Consumes: `_build_candidati_sessione(tipo, oggi)` (esistente; ogni candidato ha `legacy_id, nome, ultima_visita, data_scadenza, status, giorni_a_scadenza, origine`).
- Produces: `_build_candidati_giornata(oggi, tipo_id=None) -> list[dict]` — righe `(persona, tipo)`; ogni dict = candidato + `"tipo": TipoVisitaMedica` + `"preselect": bool`. Consumato da Task 4/6.

- [ ] **Step 1: Scrivi il test (in coda a `tests_visite_sessione.py`)**

```python
class CandidatiGiornataTests(TestCase):
    def setUp(self):
        self.oggi = timezone.localdate()
        self.ruolo = RuoloOperativo.objects.create(nome="Multi")
        self.tipo_a = TipoVisitaMedica.objects.create(nome="VDT", durata_mesi=12)
        self.tipo_b = TipoVisitaMedica.objects.create(nome="Rumore", durata_mesi=12)
        self.tipo_a.ruoli_operativi.add(self.ruolo)
        self.tipo_b.ruoli_operativi.add(self.ruolo)
        # legacy 30 ha il ruolo → entrambi i tipi dovuti (mai effettuati)
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=30, ruolo=self.ruolo)

    def _giornata(self, tipo_id=None):
        from .views import _build_candidati_giornata
        return _build_candidati_giornata(self.oggi, tipo_id=tipo_id)

    def test_persona_con_due_tipi_dovuti_due_righe(self):
        righe = [r for r in self._giornata() if r["legacy_id"] == 30]
        self.assertEqual(len(righe), 2)
        self.assertEqual({r["tipo"].nome for r in righe}, {"VDT", "Rumore"})

    def test_filtro_tipo_id_limita_a_un_tipo(self):
        righe = self._giornata(tipo_id=self.tipo_a.pk)
        self.assertTrue(all(r["tipo"].pk == self.tipo_a.pk for r in righe))
        self.assertEqual({r["legacy_id"] for r in righe}, {30})

    def test_preselect_su_scaduta_e_in_scadenza(self):
        # scaduta per tipo_a
        VisitaMedica.objects.create(
            legacy_anagrafica_id=30, tipo=self.tipo_a,
            data_svolgimento=self.oggi - timedelta(days=400),
        )
        riga_a = next(r for r in self._giornata(tipo_id=self.tipo_a.pk) if r["legacy_id"] == 30)
        self.assertEqual(riga_a["status"], "scaduta")
        self.assertTrue(riga_a["preselect"])

    def test_cessato_escluso(self):
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=30,
            data_cessazione=self.oggi - timedelta(days=10),
        )
        self.assertEqual(self._giornata(), [])
```

- [ ] **Step 2: Run test → FALLISCE**

Comando standard su `anagrafica.tests_visite_sessione.CandidatiGiornataTests` (con `--keepdb`, ora veloce). Atteso: `ImportError`/AttributeError su `_build_candidati_giornata`.

- [ ] **Step 3: Implementa l'helper**

In `views.py`, subito DOPO la fine di `_build_candidati_sessione`:

```python
def _build_candidati_giornata(oggi, tipo_id=None) -> list[dict]:
    """Righe candidate per una "giornata visite" multi-tipo: per ogni tipo di
    visita attivo (o solo ``tipo_id`` se dato) prende i candidati "consoni" da
    ``_build_candidati_sessione`` e li appiattisce in righe ``(persona, tipo)``.
    Chi ha più tipi dovuti compare in più righe (= più visite nel giorno)."""
    if tipo_id:
        tipi = list(TipoVisitaMedica.objects.filter(pk=tipo_id, is_active=True))
    else:
        tipi = list(TipoVisitaMedica.objects.filter(is_active=True).order_by("nome"))

    righe: list[dict] = []
    for tipo in tipi:
        for c in _build_candidati_sessione(tipo, oggi):
            righe.append({
                **c,
                "tipo": tipo,
                "preselect": c["status"] in ("scaduta", "in_scadenza"),
            })
    _status_order = {"in_scadenza": 0, "scaduta": 1, "mai_effettuata": 2}
    righe.sort(key=lambda r: (_status_order.get(r["status"], 9), r["nome"].casefold(), r["tipo"].nome))
    return righe
```

- [ ] **Step 4: Run test → PASSA**

Comando standard. Atteso: `OK`, 4 test.

- [ ] **Step 5: Commit**

```powershell
git add django_app/anagrafica/views.py django_app/anagrafica/tests_visite_sessione.py
git commit -m "feat(anagrafica): _build_candidati_giornata - righe (persona, tipo) multi-tipo per la giornata visite"
```

---

### Task 4: POST giornata — crea `VisitaSessione` + visite collegate multi-tipo

**Files:**
- Modify: `django_app/anagrafica/views.py` (riscrittura del ramo POST di `visite_mediche_nuova_sessione` ~riga 10130)
- Test: `django_app/anagrafica/tests_visite_sessione.py`

**Interfaces:**
- Consumes: `VisitaSessione` (Task 2), `_requisiti_tipo_visita`, `_salva_referto_visita` (esistenti).
- Produces: POST con campi per riga indicizzati per `(legacy_id, tipo_id)`: `sel_<legacy>_<tipo>` (checkbox), `esito_<legacy>_<tipo>`, `prescrizioni_<legacy>_<tipo>`, `note_<legacy>_<tipo>`, file `referto_<legacy>_<tipo>`; campi sessione `data_svolgimento`, `medico_competente`, `luogo`, `note`. Consumato dal template (Task 6).

- [ ] **Step 1: Scrivi il test (in coda a `tests_visite_sessione.py`)**

```python
class GiornataPostTests(TestCase):
    def setUp(self):
        self.user_super = User.objects.create_superuser(
            username="su-giornata", email="su-giornata@test.local", password="x"
        )
        self.oggi = timezone.localdate()
        self.ruolo = RuoloOperativo.objects.create(nome="MultiG")
        self.tipo_a = TipoVisitaMedica.objects.create(nome="VDT-G", durata_mesi=12)
        self.tipo_b = TipoVisitaMedica.objects.create(nome="Rumore-G", durata_mesi=12)
        self.tipo_a.ruoli_operativi.add(self.ruolo)
        self.tipo_b.ruoli_operativi.add(self.ruolo)
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=41, ruolo=self.ruolo)

    def _post(self, data):
        from .views import visite_mediche_nuova_sessione
        rf = RequestFactory()
        request = rf.post("/anagrafica/visite-mediche/nuova-sessione/", data)
        request.user = self.user_super
        request.session = SessionStore()
        request._messages = FallbackStorage(request)
        return visite_mediche_nuova_sessione(request)

    def test_giornata_crea_sessione_e_visite_di_tipi_misti(self):
        from .models import VisitaSessione
        a, b = self.tipo_a.pk, self.tipo_b.pk
        data = {
            "data_svolgimento": (self.oggi - timedelta(days=1)).isoformat(),
            "medico_competente": "Dr. Giornata",
            "luogo": "Infermeria",
            f"sel_41_{a}": "1", f"esito_41_{a}": "IDONEO",
            f"prescrizioni_41_{a}": "DPI", f"note_41_{a}": "",
            f"sel_41_{b}": "1", f"esito_41_{b}": "IDONEO",
            f"prescrizioni_41_{b}": "", f"note_41_{b}": "",
        }
        resp = self._post(data)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(VisitaSessione.objects.count(), 1)
        sess = VisitaSessione.objects.get()
        self.assertEqual(sess.medico_competente, "Dr. Giornata")
        self.assertEqual(sess.visite.count(), 2)
        self.assertEqual(
            {v.tipo_id for v in sess.visite.all()}, {a, b},
        )

    def test_data_futura_respinta_nessuna_sessione(self):
        from .models import VisitaSessione
        a = self.tipo_a.pk
        self._post({
            "data_svolgimento": (self.oggi + timedelta(days=3)).isoformat(),
            "medico_competente": "X",
            f"sel_41_{a}": "1", f"esito_41_{a}": "IDONEO",
        })
        self.assertEqual(VisitaSessione.objects.count(), 0)
        self.assertEqual(VisitaMedica.objects.count(), 0)

    def test_doppione_saltato(self):
        from .models import VisitaSessione
        a = self.tipo_a.pk
        VisitaMedica.objects.create(
            legacy_anagrafica_id=41, tipo=self.tipo_a,
            data_svolgimento=self.oggi - timedelta(days=1),
        )
        self._post({
            "data_svolgimento": (self.oggi - timedelta(days=1)).isoformat(),
            "medico_competente": "X",
            f"sel_41_{a}": "1", f"esito_41_{a}": "IDONEO",
        })
        # la visita doppione non è ricreata; la sessione resta vuota di nuove visite
        self.assertEqual(
            VisitaMedica.objects.filter(legacy_anagrafica_id=41, tipo=self.tipo_a).count(), 1
        )
```

- [ ] **Step 2: Run test → FALLISCE**

Comando standard su `anagrafica.tests_visite_sessione.GiornataPostTests`. Atteso: FAIL (il POST attuale è mono-tipo a 2 step; non crea `VisitaSessione`).

- [ ] **Step 3: Riscrivi il ramo POST**

In `visite_mediche_nuova_sessione`, SOSTITUISCI l'intero ramo `if request.method == "POST" and request.POST.get("step") == "2":` (dal commento `# ---- Step 2: salva i record` fino al `return redirect("anagrafica:visite_mediche_dashboard")`) con:

```python
    # ---- POST: salva la giornata (sessione + visite multi-tipo) -----------
    if request.method == "POST":
        data_str = request.POST.get("data_svolgimento", "").strip()
        medico = request.POST.get("medico_competente", "").strip()
        luogo = request.POST.get("luogo", "").strip()
        note_sess = request.POST.get("note", "").strip()

        try:
            data_svolgimento = date.fromisoformat(data_str)
        except (ValueError, TypeError):
            messages.error(request, "Data non valida.")
            return redirect("anagrafica:visite_mediche_nuova_sessione")
        if data_svolgimento > oggi:
            messages.error(request, "La data di svolgimento non può essere nel futuro.")
            return redirect("anagrafica:visite_mediche_nuova_sessione")

        # Righe selezionate: campo sel_<legacy>_<tipo> presente.
        selezioni: list[tuple[int, int]] = []
        for key in request.POST.keys():
            if not key.startswith("sel_"):
                continue
            parts = key.split("_")
            if len(parts) != 3:
                continue
            try:
                selezioni.append((int(parts[1]), int(parts[2])))
            except (ValueError, TypeError):
                continue
        if not selezioni:
            messages.warning(request, "Nessuna visita selezionata.")
            return redirect("anagrafica:visite_mediche_nuova_sessione")

        from .models import VisitaSessione
        sess = VisitaSessione.objects.create(
            data_svolgimento=data_svolgimento, medico_competente=medico,
            luogo=luogo, note=note_sess, created_by=request.user,
        )

        tipi_cache: dict[int, TipoVisitaMedica] = {}
        creati = 0
        doppioni = 0
        errori = []
        for legacy_id, tipo_id in selezioni:
            tipo = tipi_cache.get(tipo_id)
            if tipo is None:
                tipo = TipoVisitaMedica.objects.filter(pk=tipo_id, is_active=True).first()
                tipi_cache[tipo_id] = tipo
            if tipo is None:
                continue
            esito = request.POST.get(f"esito_{legacy_id}_{tipo_id}", VisitaMedica.Esito.IDONEO)
            if esito not in VisitaMedica.Esito.values:
                esito = VisitaMedica.Esito.IDONEO
            prescrizioni = request.POST.get(f"prescrizioni_{legacy_id}_{tipo_id}", "").strip()
            note = request.POST.get(f"note_{legacy_id}_{tipo_id}", "").strip()
            try:
                if VisitaMedica.objects.filter(
                    legacy_anagrafica_id=legacy_id, tipo=tipo,
                    data_svolgimento=data_svolgimento,
                ).exists():
                    doppioni += 1
                    continue
                visita = VisitaMedica.objects.create(
                    legacy_anagrafica_id=legacy_id, tipo=tipo,
                    data_svolgimento=data_svolgimento, esito=esito,
                    prescrizioni=prescrizioni, note=note, medico_competente=medico,
                    sessione=sess, created_by=request.user, updated_by=request.user,
                )
                referto_file = request.FILES.get(f"referto_{legacy_id}_{tipo_id}")
                if referto_file:
                    _salva_referto_visita(request, visita, referto_file)
                creati += 1
            except Exception:
                logger.exception("Errore creazione VisitaMedica giornata legacy=%s tipo=%s", legacy_id, tipo_id)
                errori.append(f"{legacy_id}/{tipo_id}")

        if creati == 0:
            sess.delete()  # nessuna visita creata: non lasciare sessioni vuote

        try:
            from core.audit import log_action
            log_action(
                request, "VISITA_MEDICA_BATCH_CREATA", "anagrafica",
                f"Giornata visite del {data_svolgimento} (sessione {sess.pk if creati else '—'}): "
                f"{creati} visite registrate, {doppioni} doppioni saltati.",
            )
        except Exception:
            logger.warning("Audit VISITA_MEDICA_BATCH_CREATA fallito", exc_info=True)

        if errori:
            messages.warning(request, f"{creati} visite registrate. Errori: {', '.join(errori)}.")
        elif creati == 0:
            messages.info(request, "Nessuna visita registrata (tutte già presenti in pari data).")
            return redirect("anagrafica:visite_mediche_nuova_sessione")
        else:
            msg = f"Giornata del {data_svolgimento.strftime('%d-%m-%Y')}: {creati} visite registrate."
            if doppioni:
                msg += f" {doppioni} già presenti in pari data: saltate."
            messages.success(request, msg)
        return redirect("anagrafica:visite_mediche_sessione_detail", sessione_id=sess.pk)
```

**IMPORTANTE (dipendenza):** `redirect("anagrafica:visite_mediche_sessione_detail", ...)` chiama `reverse()` a runtime: se quella route non esiste ancora, la view solleva `NoReverseMatch` e i test di questo task falliscono. Perciò **il blocco sessioni CRUD (Task 8+7) va eseguito PRIMA di questo Task 4** (vedi "Ordine di esecuzione e dipendenze"). Non è sufficiente che i test non seguano il redirect: il `reverse()` avviene comunque.

- [ ] **Step 4: Run test → PASSA**

Comando standard su `GiornataPostTests`. Atteso: `OK`, 3 test.

- [ ] **Step 5: Commit**

```powershell
git add django_app/anagrafica/views.py django_app/anagrafica/tests_visite_sessione.py
git commit -m "feat(anagrafica): POST giornata visite - crea VisitaSessione + visite multi-tipo collegate, guardrail"
```

---

### Task 5: Endpoint HTMX `visite_mediche_candidati` + partial

**Files:**
- Modify: `django_app/anagrafica/views.py` (nuova view dopo `visite_mediche_nuova_sessione`)
- Modify: `django_app/anagrafica/urls.py` (~riga 105, dopo `api/cerca-dipendente`)
- Create: `django_app/anagrafica/templates/anagrafica/partials/_visite_candidati.html`
- Test: `django_app/anagrafica/tests_visite_sessione.py`

**Interfaces:**
- Consumes: `_build_candidati_giornata` (Task 3).
- Produces: view `visite_mediche_candidati` + route name `visite_mediche_candidati` (`visite-mediche/candidati/`); partial `_visite_candidati.html` che rende le righe `(persona, tipo)` con i campi `sel_<l>_<t>` ecc. Consumato dal template pagina (Task 6).

- [ ] **Step 1: Scrivi il test (in coda a `tests_visite_sessione.py`)**

```python
class CandidatiHtmxTests(TestCase):
    def setUp(self):
        self.user_super = User.objects.create_superuser(
            username="su-htmx", email="su-htmx@test.local", password="x"
        )
        self.user_plain = User.objects.create_user(
            username="plain-htmx", email="plain-htmx@test.local", password="x"
        )
        self.oggi = timezone.localdate()
        self.ruolo = RuoloOperativo.objects.create(nome="HtmxR")
        self.tipo = TipoVisitaMedica.objects.create(nome="HtmxT", durata_mesi=12)
        self.tipo.ruoli_operativi.add(self.ruolo)
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=55, ruolo=self.ruolo)

    def _get(self, user, **params):
        from .views import visite_mediche_candidati
        rf = RequestFactory()
        request = rf.get("/anagrafica/visite-mediche/candidati/", params)
        request.user = user
        return visite_mediche_candidati(request)

    def test_403_senza_permesso(self):
        # forza ACCESSO_ADMIN (default): plain non vede
        from .models import AnagraficaVisiteMedichePermission
        perm = AnagraficaVisiteMedichePermission.get_instance()
        perm.accesso = AnagraficaVisiteMedichePermission.ACCESSO_ADMIN
        perm.save()
        resp = self._get(self.user_plain, tipo=str(self.tipo.pk))
        self.assertEqual(resp.status_code, 403)

    def test_rende_righe_per_tipo(self):
        resp = self._get(self.user_super, tipo=str(self.tipo.pk))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn(f'name="sel_55_{self.tipo.pk}"', body)
        self.assertIn("HtmxT", body)
```

- [ ] **Step 2: Run test → FALLISCE**

Comando standard su `CandidatiHtmxTests`. Atteso: ImportError su `visite_mediche_candidati`.

- [ ] **Step 3: Implementa view + route + partial**

(a) In `views.py`, dopo `visite_mediche_nuova_sessione`:

```python
@login_required
def visite_mediche_candidati(request):
    """Partial HTMX: righe candidate della giornata per il tipo selezionato
    (o tutti i tipi se ``tipo`` assente). Popola la tabella senza reload."""
    if not _can_view_visite_mediche(request):
        return HttpResponse(status=403)
    from django.utils import timezone as _tz
    raw = (request.GET.get("tipo") or "").strip()
    tipo_id = int(raw) if raw.isdigit() else None
    righe = _build_candidati_giornata(_tz.localdate(), tipo_id=tipo_id)
    return render(request, "anagrafica/partials/_visite_candidati.html", {
        "righe": righe,
        "esiti": VisitaMedica.Esito.choices,
        "esito_default": VisitaMedica.Esito.IDONEO,
        "n_pre": sum(1 for r in righe if r["preselect"]),
    })
```

(b) In `urls.py`, dopo la riga `api/cerca-dipendente`:

```python
    path("visite-mediche/candidati/", views.visite_mediche_candidati, name="visite_mediche_candidati"),
```

(c) Crea `templates/anagrafica/partials/_visite_candidati.html` (riusa gli stili inline della pagina sessione esistente; una riga per `(persona, tipo)`):

```django
{% load anagrafica_extras %}
<tbody id="tbody-candidati">
  {% for r in righe %}
  <tr style="border-bottom:1px solid #f1f5f9;" id="row-{{ r.legacy_id }}-{{ r.tipo.pk }}">
    <td style="padding:8px 10px;text-align:center;">
      <input type="checkbox" name="sel_{{ r.legacy_id }}_{{ r.tipo.pk }}" value="1"
        class="candidato-check"{% if r.preselect %} checked{% endif %}
        style="width:16px;height:16px;cursor:pointer;">
    </td>
    <td style="padding:8px 10px;font-weight:600;color:#1e293b;">
      {{ r.nome }}
      {% if r.origine == "ruolo" %}<span style="margin-left:6px;padding:1px 7px;background:#eff6ff;color:#1d4ed8;border-radius:999px;font-size:10px;font-weight:700;">Ruolo</span>
      {% elif r.origine == "processo" %}<span style="margin-left:6px;padding:1px 7px;background:#ede9fe;color:#5b21b6;border-radius:999px;font-size:10px;font-weight:700;">MOD.128</span>
      {% else %}<span style="margin-left:6px;padding:1px 7px;background:#f1f5f9;color:#64748b;border-radius:999px;font-size:10px;font-weight:700;">Storico</span>{% endif %}
    </td>
    <td style="padding:8px 10px;font-weight:600;color:#0f172a;">{{ r.tipo.nome }}</td>
    <td style="padding:8px 10px;color:#475569;">{% if r.data_scadenza %}{{ r.data_scadenza|date:"d-m-Y" }}{% else %}<span style="color:#94a3b8;">—</span>{% endif %}</td>
    <td style="padding:8px 10px;">
      {% if r.status == "in_scadenza" %}<span style="padding:2px 9px;background:#fff7ed;color:#9a3412;border-radius:999px;font-size:11px;font-weight:700;">In scadenza{% if r.giorni_a_scadenza %} ({{ r.giorni_a_scadenza }}gg){% endif %}</span>
      {% elif r.status == "scaduta" %}<span style="padding:2px 9px;background:#fee2e2;color:#b91c1c;border-radius:999px;font-size:11px;font-weight:700;">Scaduta</span>
      {% else %}<span style="padding:2px 9px;background:#f1f5f9;color:#64748b;border-radius:999px;font-size:11px;font-weight:700;">Mai effettuata</span>{% endif %}
    </td>
    <td style="padding:8px 10px;">
      <select name="esito_{{ r.legacy_id }}_{{ r.tipo.pk }}" style="width:100%;padding:6px 8px;border:1px solid #cbd5e1;border-radius:7px;font-size:13px;background:#fff;color:#1e293b;">
        {% for val, label in esiti %}<option value="{{ val }}"{% if val == esito_default %} selected{% endif %}>{{ label }}</option>{% endfor %}
      </select>
    </td>
    <td style="padding:8px 10px;"><input type="text" name="prescrizioni_{{ r.legacy_id }}_{{ r.tipo.pk }}" placeholder="prescrizioni" style="width:100%;padding:6px 8px;border:1px solid #cbd5e1;border-radius:7px;font-size:13px;box-sizing:border-box;"></td>
    <td style="padding:8px 10px;"><input type="text" name="note_{{ r.legacy_id }}_{{ r.tipo.pk }}" placeholder="note" style="width:100%;padding:6px 8px;border:1px solid #cbd5e1;border-radius:7px;font-size:13px;box-sizing:border-box;"></td>
    <td style="padding:8px 10px;"><input type="file" name="referto_{{ r.legacy_id }}_{{ r.tipo.pk }}" accept=".pdf,image/*" style="width:150px;font-size:11px;color:#475569;"></td>
  </tr>
  {% empty %}
  <tr><td colspan="9" style="padding:16px;text-align:center;color:#94a3b8;font-size:13px;">Nessun dipendente da rinnovare per il filtro scelto.</td></tr>
  {% endfor %}
</tbody>
<div id="n-pre" hx-swap-oob="true" style="display:none;">{{ n_pre }}</div>
```

- [ ] **Step 4: Run test → PASSA**

Comando standard su `CandidatiHtmxTests`. Atteso: `OK`, 2 test.

- [ ] **Step 5: Commit**

```powershell
git add django_app/anagrafica/views.py django_app/anagrafica/urls.py django_app/anagrafica/templates/anagrafica/partials/_visite_candidati.html django_app/anagrafica/tests_visite_sessione.py
git commit -m "feat(anagrafica): endpoint HTMX visite_mediche_candidati + partial righe giornata"
```

---

### Task 6: Pagina "Giornata visite" reattiva (riscrittura template + GET view)

**Files:**
- Modify: `django_app/anagrafica/views.py` (ramo GET di `visite_mediche_nuova_sessione`: context per la pagina)
- Modify: `django_app/anagrafica/templates/anagrafica/pages/visite_mediche_nuova_sessione.html` (riscrittura)
- Test: `django_app/anagrafica/tests_visite_sessione.py`

**Interfaces:**
- Consumes: `_build_candidati_giornata` (Task 3), route `visite_mediche_candidati` (Task 5), `visite_mediche_api_cerca_dipendente` (esistente).
- Produces: pagina con form `enctype="multipart/form-data"`, select tipo con `hx-get` verso `visite_mediche_candidati`, deep-link `?tipo=`, barra sticky.

- [ ] **Step 1: Scrivi il test (in coda a `tests_visite_sessione.py`)**

```python
class GiornataRenderTests(TestCase):
    def setUp(self):
        self.user_super = User.objects.create_superuser(
            username="su-grender", email="su-grender@test.local", password="x"
        )
        self.oggi = timezone.localdate()
        self.ruolo = RuoloOperativo.objects.create(nome="GRR")
        self.tipo = TipoVisitaMedica.objects.create(nome="GRT", durata_mesi=12)
        self.tipo.ruoli_operativi.add(self.ruolo)
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=66, ruolo=self.ruolo)
        VisitaMedica.objects.create(
            legacy_anagrafica_id=66, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=400),
        )

    def _get(self, **params):
        from .views import visite_mediche_nuova_sessione
        rf = RequestFactory()
        request = rf.get("/anagrafica/visite-mediche/nuova-sessione/", params)
        request.user = self.user_super
        request.session = SessionStore()
        request._messages = FallbackStorage(request)
        return visite_mediche_nuova_sessione(request)

    def test_pagina_ha_form_multipart_e_htmx(self):
        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('enctype="multipart/form-data"', body)
        self.assertIn("visite-mediche/candidati", body)  # hx-get target
        self.assertIn("Giornata visite", body)

    def test_deeplink_tipo_rende_candidati_server_side(self):
        resp = self._get(tipo=str(self.tipo.pk))
        body = resp.content.decode()
        self.assertIn(f'name="sel_66_{self.tipo.pk}"', body)
```

- [ ] **Step 2: Run test → FALLISCE**

Comando standard su `GiornataRenderTests`. Atteso: FAIL (template ancora vecchio mono-tipo).

- [ ] **Step 3: GET view — context**

In `visite_mediche_nuova_sessione`, SOSTITUISCI tutto il codice dopo il ramo POST (dal `# ---- Step 1` fino al `return render(...)` finale) con:

```python
    # ---- GET: pagina Giornata visite (reattiva) --------------------------
    pre_tipo_id = (request.GET.get("tipo") or "").strip()
    tipo_pre = None
    if pre_tipo_id.isdigit():
        tipo_pre = TipoVisitaMedica.objects.filter(pk=int(pre_tipo_id), is_active=True).first()
    righe = _build_candidati_giornata(oggi, tipo_id=(tipo_pre.pk if tipo_pre else None)) if (tipo_pre or request.GET.get("all")) else []
    medici_precedenti = list(
        VisitaMedica.objects.exclude(medico_competente="")
        .order_by("medico_competente").values_list("medico_competente", flat=True).distinct()[:20]
    )
    return render(request, "anagrafica/pages/visite_mediche_nuova_sessione.html", {
        "tipi_attivi": tipi_attivi,
        "tipo_pre": tipo_pre,
        "righe": righe,
        "n_pre": sum(1 for r in righe if r["preselect"]),
        "oggi": oggi,
        "esiti": VisitaMedica.Esito.choices,
        "esito_default": VisitaMedica.Esito.IDONEO,
        "medici_precedenti": medici_precedenti,
    })
```

(`tipi_attivi = list(TipoVisitaMedica.objects.filter(is_active=True).order_by("nome"))` è già calcolato a inizio view; mantienilo.)

- [ ] **Step 4: Riscrivi il template**

Sostituisci `visite_mediche_nuova_sessione.html` con la pagina Giornata (mantieni `{% extends %}`, `{% block %}`, gli stili inline nello spirito esistente). Struttura minima richiesta dai test e dalla spec:

```django
{% extends "core/base.html" %}
{% block title %}Giornata visite · {{ INSTANCE_NAME|default:"NOVICROM HUB" }}{% endblock %}
{% block extra_head %}{% include "anagrafica/components/_hr_restyle.html" %}{% endblock %}
{% block subnav %}{% include "anagrafica/components/subnav.html" %}{% endblock %}
{% block content %}
<div style="display:flex;flex-direction:column;gap:16px;margin-top:14px;">
  <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;">
    <h1 style="font-size:24px;font-weight:800;color:#0f172a;margin:0;">Giornata visite</h1>
    <a href="{% url 'anagrafica:visite_mediche_sessioni' %}" style="font-size:13px;color:#1f87cd;font-weight:600;">← Sessioni & proposte</a>
  </div>

  {% include "anagrafica/partials/_messages.html" %}{# se non esiste, riusare il blocco messaggi della vecchia pagina #}

  <form method="post" enctype="multipart/form-data" id="form-giornata">
    {% csrf_token %}
    {# Parametri giornata #}
    <div style="background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:20px;display:grid;grid-template-columns:repeat(4,1fr);gap:16px;align-items:end;">
      <div>
        <label style="display:block;font-size:12px;font-weight:700;color:#475569;margin-bottom:5px;text-transform:uppercase;">Data *</label>
        <input type="date" name="data_svolgimento" value="{{ oggi|date:'Y-m-d' }}" required max="{{ oggi|date:'Y-m-d' }}" style="width:100%;padding:8px 10px;border:1px solid #cbd5e1;border-radius:8px;font-size:14px;box-sizing:border-box;">
      </div>
      <div>
        <label style="display:block;font-size:12px;font-weight:700;color:#475569;margin-bottom:5px;text-transform:uppercase;">Medico competente</label>
        <input type="text" name="medico_competente" list="medici-precedenti" placeholder="es. Dr. Rossi" style="width:100%;padding:8px 10px;border:1px solid #cbd5e1;border-radius:8px;font-size:14px;box-sizing:border-box;">
        <datalist id="medici-precedenti">{% for m in medici_precedenti %}<option value="{{ m }}"></option>{% endfor %}</datalist>
      </div>
      <div>
        <label style="display:block;font-size:12px;font-weight:700;color:#475569;margin-bottom:5px;text-transform:uppercase;">Luogo</label>
        <input type="text" name="luogo" placeholder="es. Infermeria" style="width:100%;padding:8px 10px;border:1px solid #cbd5e1;border-radius:8px;font-size:14px;box-sizing:border-box;">
      </div>
      <div>
        <label style="display:block;font-size:12px;font-weight:700;color:#475569;margin-bottom:5px;text-transform:uppercase;">Filtra per tipo</label>
        <select name="_tipo_filtro"
          hx-get="{% url 'anagrafica:visite_mediche_candidati' %}"
          hx-target="#tbody-candidati" hx-swap="outerHTML"
          hx-trigger="change"
          style="width:100%;padding:8px 10px;border:1px solid #cbd5e1;border-radius:8px;font-size:14px;background:#fff;">
          <option value="">— Tutti i tipi (giornata completa) —</option>
          {% for t in tipi_attivi %}<option value="{{ t.pk }}"{% if tipo_pre and tipo_pre.pk == t.pk %} selected{% endif %}>{{ t.nome }}</option>{% endfor %}
        </select>
      </div>
    </div>

    {# Tabella candidati (server-side se deep-link; altrimenti caricata via HTMX) #}
    <div style="background:#fff;border:1px solid #e2e8f0;border-radius:14px;overflow:hidden;">
      <div style="overflow-x:auto;">
        <table style="width:100%;border-collapse:collapse;font-size:13px;">
          <thead><tr style="border-bottom:2px solid #e2e8f0;background:#f8fafc;">
            <th style="width:44px;padding:9px 10px;font-size:11px;color:#94a3b8;text-transform:uppercase;">Sel.</th>
            <th style="text-align:left;padding:9px 10px;font-size:11px;color:#94a3b8;text-transform:uppercase;">Dipendente</th>
            <th style="text-align:left;padding:9px 10px;font-size:11px;color:#94a3b8;text-transform:uppercase;">Tipo</th>
            <th style="text-align:left;padding:9px 10px;font-size:11px;color:#94a3b8;text-transform:uppercase;">Scadenza</th>
            <th style="text-align:left;padding:9px 10px;font-size:11px;color:#94a3b8;text-transform:uppercase;">Stato</th>
            <th style="text-align:left;padding:9px 10px;font-size:11px;color:#94a3b8;text-transform:uppercase;">Esito</th>
            <th style="text-align:left;padding:9px 10px;font-size:11px;color:#94a3b8;text-transform:uppercase;">Prescrizioni</th>
            <th style="text-align:left;padding:9px 10px;font-size:11px;color:#94a3b8;text-transform:uppercase;">Note</th>
            <th style="text-align:left;padding:9px 10px;font-size:11px;color:#94a3b8;text-transform:uppercase;">Referto</th>
          </tr></thead>
          {% include "anagrafica/partials/_visite_candidati.html" %}
        </table>
      </div>
    </div>

    {# Barra sticky azioni #}
    <div style="position:sticky;bottom:0;background:#fff;border:1px solid #e2e8f0;border-radius:12px;padding:12px 18px;display:flex;justify-content:space-between;align-items:center;gap:12px;box-shadow:0 -4px 12px rgba(0,0,0,.05);">
      <div style="display:flex;gap:8px;">
        <button type="button" onclick="selVisite(true)" style="padding:6px 13px;background:#f1f5f9;border:1px solid #cbd5e1;border-radius:7px;font-size:12px;font-weight:700;cursor:pointer;color:#475569;">Tutti</button>
        <button type="button" onclick="selVisite(false)" style="padding:6px 13px;background:#f1f5f9;border:1px solid #cbd5e1;border-radius:7px;font-size:12px;font-weight:700;cursor:pointer;color:#475569;">Nessuno</button>
      </div>
      <button type="submit" style="padding:10px 24px;background:#059669;color:#fff;border:none;border-radius:8px;font-size:14px;font-weight:700;cursor:pointer;">Registra giornata (<span id="cnt">{{ n_pre }}</span>)</button>
    </div>
  </form>
</div>
<script>
function selVisite(state){document.querySelectorAll('.candidato-check').forEach(function(cb){cb.checked=state;});updCnt();}
function updCnt(){var n=document.querySelectorAll('.candidato-check:checked').length;var el=document.getElementById('cnt');if(el)el.textContent=n;}
document.addEventListener('change',function(e){if(e.target.classList&&e.target.classList.contains('candidato-check'))updCnt();});
document.body.addEventListener('htmx:afterSwap',function(){updCnt();});
</script>
{% endblock %}
```

Nota: se `anagrafica/partials/_messages.html` non esiste, incollare il blocco messaggi della versione precedente della pagina (recuperabile da git history del file). Il picker "+ Aggiungi" con scelta tipo è opzionale in questa iterazione (i candidati proposti coprono il caso 10-15); si può aggiungere dopo riusando `visite_mediche_api_cerca_dipendente` con `tipo_id`.

- [ ] **Step 5: Run test → PASSA**

Comando standard su `GiornataRenderTests`. Atteso: `OK`, 2 test.

- [ ] **Step 6: Commit**

```powershell
git add django_app/anagrafica/views.py django_app/anagrafica/templates/anagrafica/pages/visite_mediche_nuova_sessione.html django_app/anagrafica/tests_visite_sessione.py
git commit -m "feat(anagrafica): pagina Giornata visite reattiva (HTMX) - filtro tipo live, deep-link, barra sticky"
```

---

### Task 7: Hub "Sessioni & Proposte" (`visite_mediche_sessioni`)

**Files:**
- Modify: `django_app/anagrafica/views.py` (nuova view)
- Modify: `django_app/anagrafica/urls.py`
- Create: `django_app/anagrafica/templates/anagrafica/pages/visite_mediche_sessioni.html`
- Test: `django_app/anagrafica/tests_visite_sessione.py`

**Interfaces:**
- Consumes: `ultime_visite_correnti_ids`, `_requisiti_tipo_visita` (esistenti), `VisitaSessione` (Task 2).
- Produces: view `visite_mediche_sessioni` + route (`visite-mediche/sessioni/`). Consumato dai link (Task 6/10).

- [ ] **Step 1: Scrivi il test**

```python
class SessioniHubTests(TestCase):
    def setUp(self):
        self.user_super = User.objects.create_superuser(
            username="su-hub", email="su-hub@test.local", password="x"
        )
        self.oggi = timezone.localdate()
        self.ruolo = RuoloOperativo.objects.create(nome="HubR")
        self.tipo = TipoVisitaMedica.objects.create(nome="HubT", durata_mesi=12)
        self.tipo.ruoli_operativi.add(self.ruolo)
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=77, ruolo=self.ruolo)
        VisitaMedica.objects.create(
            legacy_anagrafica_id=77, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=400),  # scaduta
        )

    def test_hub_mostra_proposta_e_deeplink(self):
        from .views import visite_mediche_sessioni
        rf = RequestFactory()
        request = rf.get("/anagrafica/visite-mediche/sessioni/")
        request.user = self.user_super
        request.session = SessionStore()
        request._messages = FallbackStorage(request)
        resp = visite_mediche_sessioni(request)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("HubT", body)
        self.assertIn(f"nuova-sessione/?tipo={self.tipo.pk}", body)
```

- [ ] **Step 2: Run test → FALLISCE** (ImportError su `visite_mediche_sessioni`).

- [ ] **Step 3: Implementa view + route + template**

(a) `views.py`:

```python
@login_required
def visite_mediche_sessioni(request):
    """Hub: proposte di rinnovo per tipo (da rinnovare = ultima visita corrente
    scaduta/in scadenza) + elenco delle giornate salvate."""
    if not _can_view_visite_mediche(request):
        messages.error(request, "Non hai i permessi per le visite mediche.")
        return redirect("anagrafica:index")
    from django.utils import timezone as _tz
    from .models import VisitaSessione
    oggi = _tz.localdate()
    soglia = oggi + _timedelta(days=60)
    correnti = VisitaMedica.objects.filter(id__in=ultime_visite_correnti_ids())
    proposte = []
    for t in TipoVisitaMedica.objects.filter(is_active=True).order_by("nome"):
        n_scad = correnti.filter(tipo=t, data_scadenza__lt=oggi).count()
        n_insc = correnti.filter(tipo=t, data_scadenza__gte=oggi, data_scadenza__lte=soglia).count()
        if n_scad or n_insc:
            proposte.append({"tipo": t, "n_scadute": n_scad, "n_in_scadenza": n_insc})
    sessioni = list(
        VisitaSessione.objects.annotate(n_visite=Count("visite")).order_by("-data_svolgimento", "-id")[:50]
    )
    return render(request, "anagrafica/pages/visite_mediche_sessioni.html", {
        "proposte": proposte, "sessioni": sessioni, "oggi": oggi,
        "tot_da_rinnovare": sum(p["n_scadute"] + p["n_in_scadenza"] for p in proposte),
    })
```

(b) `urls.py`:

```python
    path("visite-mediche/sessioni/", views.visite_mediche_sessioni, name="visite_mediche_sessioni"),
```

(c) `templates/anagrafica/pages/visite_mediche_sessioni.html`:

```django
{% extends "core/base.html" %}
{% block title %}Sessioni & proposte visite · {{ INSTANCE_NAME|default:"NOVICROM HUB" }}{% endblock %}
{% block extra_head %}{% include "anagrafica/components/_hr_restyle.html" %}{% endblock %}
{% block subnav %}{% include "anagrafica/components/subnav.html" %}{% endblock %}
{% block content %}
<div style="display:flex;flex-direction:column;gap:18px;margin-top:14px;">
  <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;">
    <h1 style="font-size:24px;font-weight:800;color:#0f172a;margin:0;">Sessioni & proposte visite</h1>
    <a href="{% url 'anagrafica:visite_mediche_nuova_sessione' %}" style="padding:9px 18px;background:#1f87cd;color:#fff;border-radius:8px;font-size:14px;font-weight:700;text-decoration:none;">+ Nuova giornata</a>
  </div>

  <div style="background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:18px;">
    <div style="font-size:15px;font-weight:700;color:#1e293b;margin-bottom:12px;">Proposte di rinnovo</div>
    {% if tot_da_rinnovare %}
    <a href="{% url 'anagrafica:visite_mediche_nuova_sessione' %}?all=1" style="display:inline-block;margin-bottom:12px;padding:8px 16px;background:#fef3c7;color:#92400e;border-radius:8px;font-weight:700;font-size:13px;text-decoration:none;">⚡ Giornata completa: {{ tot_da_rinnovare }} da rinnovare →</a>
    {% endif %}
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px;">
      {% for p in proposte %}
      <div style="border:1px solid #e6ecf3;border-radius:10px;padding:14px;display:flex;flex-direction:column;gap:8px;">
        <div style="font-weight:700;color:#0f172a;">{{ p.tipo.nome }}</div>
        <div style="font-size:13px;color:#475569;">🔴 {{ p.n_scadute }} scadute · 🟠 {{ p.n_in_scadenza }} in scadenza</div>
        <a href="{% url 'anagrafica:visite_mediche_nuova_sessione' %}?tipo={{ p.tipo.pk }}" style="align-self:flex-start;padding:6px 14px;background:#059669;color:#fff;border-radius:7px;font-size:12px;font-weight:700;text-decoration:none;">Crea sessione</a>
      </div>
      {% empty %}
      <div style="color:#94a3b8;font-size:13px;">Nessuna visita da rinnovare al momento.</div>
      {% endfor %}
    </div>
  </div>

  <div style="background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:18px;">
    <div style="font-size:15px;font-weight:700;color:#1e293b;margin-bottom:12px;">Giornate registrate</div>
    <table style="width:100%;border-collapse:collapse;font-size:13px;">
      <thead><tr style="border-bottom:2px solid #e2e8f0;"><th style="text-align:left;padding:8px;color:#94a3b8;font-size:11px;text-transform:uppercase;">Data</th><th style="text-align:left;padding:8px;color:#94a3b8;font-size:11px;text-transform:uppercase;">Medico</th><th style="text-align:left;padding:8px;color:#94a3b8;font-size:11px;text-transform:uppercase;">Visite</th></tr></thead>
      <tbody>
        {% for s in sessioni %}
        <tr style="border-bottom:1px solid #f1f5f9;">
          <td style="padding:8px;"><a href="{% url 'anagrafica:visite_mediche_sessione_detail' s.pk %}" style="color:#1f87cd;font-weight:600;text-decoration:none;">{{ s.data_svolgimento|date:"d-m-Y" }}</a></td>
          <td style="padding:8px;color:#475569;">{{ s.medico_competente|default:"—" }}</td>
          <td style="padding:8px;color:#475569;">{{ s.n_visite }}</td>
        </tr>
        {% empty %}
        <tr><td colspan="3" style="padding:14px;text-align:center;color:#94a3b8;">Nessuna giornata registrata.</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
{% endblock %}
```

Nota: il template referenzia `visite_mediche_sessione_detail` (Task 8). Ordine di esecuzione: Task 8 può precedere il render-test di questo template, oppure il test qui non segue i link. Il test fornito verifica solo la presenza della stringa deep-link, non risolve `sessione_detail`; ma `{% url 'anagrafica:visite_mediche_sessione_detail' %}` fallirebbe il rendering se la route non esiste. **Perciò: eseguire Task 8 PRIMA di Task 7, oppure aggiungere la route di Task 8 in questo commit.** Scelta del piano: **spostare la definizione della route `visite_mediche_sessione_detail` in questo task** (solo la `path(...)`, con la view creata in Task 8) NON è pulito. Soluzione adottata: **eseguire Task 8 prima di Task 7** (riordinare). Vedi nota in cima a Task 8.

- [ ] **Step 4: Run test → PASSA** (dopo Task 8). Comando standard su `SessioniHubTests`.

- [ ] **Step 5: Commit**

```powershell
git add django_app/anagrafica/views.py django_app/anagrafica/urls.py django_app/anagrafica/templates/anagrafica/pages/visite_mediche_sessioni.html django_app/anagrafica/tests_visite_sessione.py
git commit -m "feat(anagrafica): hub Sessioni & proposte visite (proposte di rinnovo per tipo + elenco giornate)"
```

---

### Task 8: Dettaglio sessione + aggiungi partecipante + elimina

> **Ordine:** eseguire QUESTO task PRIMA del Task 7 (il template dell'hub referenzia la route `visite_mediche_sessione_detail`). In alternativa, aggiungere qui tutte le route e committare Task 8 prima di Task 7.

**Files:**
- Modify: `django_app/anagrafica/views.py` (3 viste)
- Modify: `django_app/anagrafica/urls.py`
- Create: `django_app/anagrafica/templates/anagrafica/pages/visite_mediche_sessione_detail.html`
- Test: `django_app/anagrafica/tests_visite_sessione.py`

**Interfaces:**
- Consumes: `VisitaSessione`, `_build_nomi_map`, `_ensure_admin`.
- Produces: route `visite_mediche_sessione_detail` (`visite-mediche/sessioni/<int:sessione_id>/`), `visite_mediche_sessione_partecipante_add` (`.../partecipante/aggiungi/`), `visite_mediche_sessione_delete` (`.../elimina/`).

- [ ] **Step 1: Scrivi il test**

```python
class SessioneDetailTests(TestCase):
    def setUp(self):
        self.user_super = User.objects.create_superuser(
            username="su-det", email="su-det@test.local", password="x"
        )
        self.oggi = timezone.localdate()
        self.tipo = TipoVisitaMedica.objects.create(nome="DetT", durata_mesi=12)

    def _mk_sess(self):
        from .models import VisitaSessione
        sess = VisitaSessione.objects.create(data_svolgimento=self.oggi, medico_competente="Dr. Det")
        VisitaMedica.objects.create(
            legacy_anagrafica_id=88, tipo=self.tipo,
            data_svolgimento=self.oggi, sessione=sess,
        )
        return sess

    def test_dettaglio_render(self):
        from .views import visite_mediche_sessione_detail
        sess = self._mk_sess()
        rf = RequestFactory()
        request = rf.get(f"/anagrafica/visite-mediche/sessioni/{sess.pk}/")
        request.user = self.user_super
        request.session = SessionStore()
        request._messages = FallbackStorage(request)
        resp = visite_mediche_sessione_detail(request, sess.pk)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Dr. Det", resp.content.decode())

    def test_aggiungi_partecipante_crea_visita_nella_sessione(self):
        from .views import visite_mediche_sessione_partecipante_add
        sess = self._mk_sess()
        rf = RequestFactory()
        request = rf.post(
            f"/anagrafica/visite-mediche/sessioni/{sess.pk}/partecipante/aggiungi/",
            {"legacy_id": "99", "tipo_id": str(self.tipo.pk), "esito": "IDONEO"},
        )
        request.user = self.user_super
        request.session = SessionStore()
        request._messages = FallbackStorage(request)
        resp = visite_mediche_sessione_partecipante_add(request, sess.pk)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            VisitaMedica.objects.filter(legacy_anagrafica_id=99, sessione=sess).exists()
        )

    def test_elimina_sessione_conserva_visite(self):
        from .views import visite_mediche_sessione_delete
        from .models import VisitaSessione
        sess = self._mk_sess()
        rf = RequestFactory()
        request = rf.post(f"/anagrafica/visite-mediche/sessioni/{sess.pk}/elimina/")
        request.user = self.user_super
        request.session = SessionStore()
        request._messages = FallbackStorage(request)
        visite_mediche_sessione_delete(request, sess.pk)
        self.assertFalse(VisitaSessione.objects.filter(pk=sess.pk).exists())
        self.assertTrue(VisitaMedica.objects.filter(legacy_anagrafica_id=88).exists())
```

- [ ] **Step 2: Run test → FALLISCE** (ImportError sulle 3 viste).

- [ ] **Step 3: Implementa viste + route + template**

(a) `views.py`:

```python
@login_required
def visite_mediche_sessione_detail(request, sessione_id: int):
    if not _can_view_visite_mediche(request):
        messages.error(request, "Non hai i permessi per le visite mediche.")
        return redirect("anagrafica:index")
    from .models import VisitaSessione
    sess = get_object_or_404(VisitaSessione, pk=sessione_id)
    nomi = _build_nomi_map()
    visite = list(sess.visite.select_related("tipo").order_by("tipo__nome"))
    for v in visite:
        v.dipendente_nome = nomi.get(v.legacy_anagrafica_id, f"#{v.legacy_anagrafica_id}")
    _, is_admin = _ensure_admin(request)
    return render(request, "anagrafica/pages/visite_mediche_sessione_detail.html", {
        "sess": sess, "visite": visite, "is_admin": is_admin,
        "tipi_attivi": list(TipoVisitaMedica.objects.filter(is_active=True).order_by("nome")),
        "esiti": VisitaMedica.Esito.choices, "esito_default": VisitaMedica.Esito.IDONEO,
    })


@login_required
@require_POST
def visite_mediche_sessione_partecipante_add(request, sessione_id: int):
    if not _can_view_visite_mediche(request):
        messages.error(request, "Permessi insufficienti.")
        return redirect("anagrafica:visite_mediche_sessione_detail", sessione_id=sessione_id)
    from .models import VisitaSessione
    sess = get_object_or_404(VisitaSessione, pk=sessione_id)
    try:
        legacy_id = int(request.POST.get("legacy_id") or 0)
        tipo = TipoVisitaMedica.objects.get(pk=request.POST.get("tipo_id"), is_active=True)
    except (ValueError, TypeError, TipoVisitaMedica.DoesNotExist):
        messages.error(request, "Dipendente o tipo non validi.")
        return redirect("anagrafica:visite_mediche_sessione_detail", sessione_id=sessione_id)
    esito = request.POST.get("esito", VisitaMedica.Esito.IDONEO)
    if esito not in VisitaMedica.Esito.values:
        esito = VisitaMedica.Esito.IDONEO
    if VisitaMedica.objects.filter(
        legacy_anagrafica_id=legacy_id, tipo=tipo, data_svolgimento=sess.data_svolgimento
    ).exists():
        messages.warning(request, "Visita già presente in pari data: non aggiunta.")
    else:
        VisitaMedica.objects.create(
            legacy_anagrafica_id=legacy_id, tipo=tipo, data_svolgimento=sess.data_svolgimento,
            esito=esito, medico_competente=sess.medico_competente, sessione=sess,
            created_by=request.user, updated_by=request.user,
        )
        messages.success(request, "Partecipante aggiunto alla giornata.")
    return redirect("anagrafica:visite_mediche_sessione_detail", sessione_id=sessione_id)


@login_required
@require_POST
def visite_mediche_sessione_delete(request, sessione_id: int):
    if not _can_view_visite_mediche(request):
        messages.error(request, "Permessi insufficienti.")
        return redirect("anagrafica:visite_mediche_sessioni")
    _, is_admin = _ensure_admin(request)
    if not is_admin:
        messages.error(request, "Solo gli amministratori possono eliminare una giornata.")
        return redirect("anagrafica:visite_mediche_sessione_detail", sessione_id=sessione_id)
    from .models import VisitaSessione
    sess = get_object_or_404(VisitaSessione, pk=sessione_id)
    sess.delete()  # SET_NULL: le visite restano
    messages.success(request, "Giornata eliminata (le visite registrate sono conservate).")
    return redirect("anagrafica:visite_mediche_sessioni")
```

(b) `urls.py`:

```python
    path("visite-mediche/sessioni/<int:sessione_id>/", views.visite_mediche_sessione_detail, name="visite_mediche_sessione_detail"),
    path("visite-mediche/sessioni/<int:sessione_id>/partecipante/aggiungi/", views.visite_mediche_sessione_partecipante_add, name="visite_mediche_sessione_partecipante_add"),
    path("visite-mediche/sessioni/<int:sessione_id>/elimina/", views.visite_mediche_sessione_delete, name="visite_mediche_sessione_delete"),
```

(c) `templates/anagrafica/pages/visite_mediche_sessione_detail.html`:

```django
{% extends "core/base.html" %}
{% block title %}Giornata {{ sess.data_svolgimento|date:"d-m-Y" }} · {{ INSTANCE_NAME|default:"NOVICROM HUB" }}{% endblock %}
{% block extra_head %}{% include "anagrafica/components/_hr_restyle.html" %}{% endblock %}
{% block subnav %}{% include "anagrafica/components/subnav.html" %}{% endblock %}
{% block content %}
<div style="display:flex;flex-direction:column;gap:16px;margin-top:14px;">
  <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;">
    <h1 style="font-size:22px;font-weight:800;color:#0f172a;margin:0;">Giornata visite — {{ sess.data_svolgimento|date:"d-m-Y" }}</h1>
    <a href="{% url 'anagrafica:visite_mediche_sessioni' %}" style="font-size:13px;color:#1f87cd;font-weight:600;">← Sessioni</a>
  </div>
  <div style="font-size:14px;color:#475569;">Medico: <strong>{{ sess.medico_competente|default:"—" }}</strong>{% if sess.luogo %} · Luogo: {{ sess.luogo }}{% endif %}</div>

  <div style="background:#fff;border:1px solid #e2e8f0;border-radius:14px;overflow:hidden;">
    <table style="width:100%;border-collapse:collapse;font-size:13px;">
      <thead><tr style="border-bottom:2px solid #e2e8f0;background:#f8fafc;"><th style="text-align:left;padding:9px;color:#94a3b8;font-size:11px;text-transform:uppercase;">Dipendente</th><th style="text-align:left;padding:9px;color:#94a3b8;font-size:11px;text-transform:uppercase;">Tipo</th><th style="text-align:left;padding:9px;color:#94a3b8;font-size:11px;text-transform:uppercase;">Esito</th><th style="text-align:left;padding:9px;color:#94a3b8;font-size:11px;text-transform:uppercase;">Scadenza</th></tr></thead>
      <tbody>
        {% for v in visite %}
        <tr style="border-bottom:1px solid #f1f5f9;"><td style="padding:8px;font-weight:600;">{{ v.dipendente_nome }}</td><td style="padding:8px;">{{ v.tipo.nome }}</td><td style="padding:8px;color:#475569;">{{ v.get_esito_display }}</td><td style="padding:8px;color:#475569;">{% if v.data_scadenza %}{{ v.data_scadenza|date:"d-m-Y" }}{% else %}—{% endif %}</td></tr>
        {% empty %}
        <tr><td colspan="4" style="padding:14px;text-align:center;color:#94a3b8;">Nessuna visita in questa giornata.</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

  {% if is_admin %}
  <div style="background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:16px;display:flex;flex-wrap:wrap;gap:16px;align-items:flex-end;justify-content:space-between;">
    <form method="post" action="{% url 'anagrafica:visite_mediche_sessione_partecipante_add' sess.pk %}" style="display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap;">
      {% csrf_token %}
      <div><label style="display:block;font-size:11px;color:#475569;font-weight:700;text-transform:uppercase;">ID dipendente</label><input type="number" name="legacy_id" required style="padding:7px 9px;border:1px solid #cbd5e1;border-radius:7px;"></div>
      <div><label style="display:block;font-size:11px;color:#475569;font-weight:700;text-transform:uppercase;">Tipo</label><select name="tipo_id" required style="padding:7px 9px;border:1px solid #cbd5e1;border-radius:7px;">{% for t in tipi_attivi %}<option value="{{ t.pk }}">{{ t.nome }}</option>{% endfor %}</select></div>
      <div><label style="display:block;font-size:11px;color:#475569;font-weight:700;text-transform:uppercase;">Esito</label><select name="esito" style="padding:7px 9px;border:1px solid #cbd5e1;border-radius:7px;">{% for val, label in esiti %}<option value="{{ val }}"{% if val == esito_default %} selected{% endif %}>{{ label }}</option>{% endfor %}</select></div>
      <button type="submit" style="padding:8px 16px;background:#1f87cd;color:#fff;border:none;border-radius:7px;font-weight:700;cursor:pointer;">+ Aggiungi</button>
    </form>
    <form method="post" action="{% url 'anagrafica:visite_mediche_sessione_delete' sess.pk %}" onsubmit="return confirm('Eliminare la giornata? Le visite restano.');">
      {% csrf_token %}
      <button type="submit" style="padding:8px 16px;background:#fee2e2;color:#b91c1c;border:1px solid #fecaca;border-radius:7px;font-weight:700;cursor:pointer;">Elimina giornata</button>
    </form>
  </div>
  {% endif %}
</div>
{% endblock %}
```

- [ ] **Step 4: Run test → PASSA**

Comando standard su `SessioneDetailTests`. Atteso: `OK`, 3 test.

- [ ] **Step 5: Commit**

```powershell
git add django_app/anagrafica/views.py django_app/anagrafica/urls.py django_app/anagrafica/templates/anagrafica/pages/visite_mediche_sessione_detail.html django_app/anagrafica/tests_visite_sessione.py
git commit -m "feat(anagrafica): dettaglio giornata visite + aggiungi partecipante + elimina (conserva le visite)"
```

---

### Task 9: Scadenzario — `tipo_id` sulle voci visite + pulsante "↻ Rinnovo" per gruppo

**Files:**
- Modify: `django_app/anagrafica/views.py` (voce visite in `_build_scadenzario_voci` ~riga 7230; gruppo in `_raggruppa_scadenze_per_tipo`)
- Modify: `django_app/anagrafica/templates/anagrafica/pages/scadenzario.html` (header gruppo ~riga 79; tabella piatta ~riga 142)
- Test: `django_app/anagrafica/tests_visite_sessione.py`

**Interfaces:**
- Consumes: route `visite_mediche_nuova_sessione` (deep-link `?tipo=`).
- Produces: voci visite con `tipo_id`; gruppo con `tipo_id`.

- [ ] **Step 1: Scrivi il test**

```python
class ScadenzarioRinnovoVisiteTests(TestCase):
    def setUp(self):
        from .tests import _ensure_anagrafica_table
        _ensure_anagrafica_table()
        self.user_super = User.objects.create_superuser(
            username="su-scad-rin", email="su-scad-rin@test.local", password="x"
        )
        self.oggi = timezone.localdate()
        self.tipo = TipoVisitaMedica.objects.create(nome="ScadRinT", durata_mesi=12)
        VisitaMedica.objects.create(
            legacy_anagrafica_id=111, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=400),  # scaduta
        )

    def test_voce_visita_porta_tipo_id(self):
        from .views import _build_scadenzario_voci
        rf = RequestFactory()
        request = rf.get("/anagrafica/scadenzario/")
        request.user = self.user_super
        voci = _build_scadenzario_voci(request, filtro_tipo="visita", filtro_stato="", filtro_reparto="")
        vis = [v for v in voci if v["kind"] == "visita"]
        self.assertTrue(vis)
        self.assertEqual(vis[0]["tipo_id"], self.tipo.pk)

    def test_gruppo_visita_ha_pulsante_rinnovo(self):
        self.client.force_login(self.user_super)
        resp = self.client.get(reverse("anagrafica:scadenzario"), {"tipo": "visita"})
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn(f"nuova-sessione/?tipo={self.tipo.pk}", body)
```

- [ ] **Step 2: Run test → FALLISCE** (voce senza `tipo_id`; nessun deep-link visite).

- [ ] **Step 3: Implementa**

(a) In `_build_scadenzario_voci`, nel dict della voce visita (dopo `"tipo_nome": v.tipo.nome,`) aggiungi:

```python
                "tipo_id":      v.tipo_id,
```

(b) In `_raggruppa_scadenze_per_tipo`, nel dict del gruppo aggiungi (dopo `"tipo_nome": tipo_nome,`):

```python
            "tipo_id": gv[0].get("tipo_id"),
```

(c) In `scadenzario.html`, nell'header del gruppo (dopo `<span style="flex:1 1 auto;">{{ g.tipo_nome }}</span>`, ~riga 79) aggiungi:

```django
            {% if g.kind == "visita" and can_view_visite and g.tipo_id %}
              <a href="{% url 'anagrafica:visite_mediche_nuova_sessione' %}?tipo={{ g.tipo_id }}" title="Crea una giornata di rinnovo per questo tipo" style="margin-left:8px;font-size:11px;font-weight:700;color:#059669;text-decoration:none;white-space:nowrap;">↻ Rinnovo</a>
            {% elif g.kind == "qualifica" and is_qual_admin and g.tipo_id %}
              <a href="{% url 'anagrafica:qualifica_sessione_create' %}?tipo={{ g.tipo_id }}" title="Crea una sessione di rinnovo" style="margin-left:8px;font-size:11px;font-weight:700;color:var(--fmd-cyan);text-decoration:none;white-space:nowrap;">↻ Rinnovo</a>
            {% endif %}
```

(d) Nella tabella piatta, accanto al blocco esistente delle qualifiche (~riga 142-144), aggiungi il ramo visite:

```django
                {% if v.kind == "visita" and can_view_visite and v.tipo_id %}
                  <a href="{% url 'anagrafica:visite_mediche_nuova_sessione' %}?tipo={{ v.tipo_id }}" title="Crea una giornata di rinnovo" style="margin-left:8px;font-size:11px;font-weight:700;color:#059669;text-decoration:none;white-space:nowrap;">↻ Rinnova</a>
                {% endif %}
```

Verifica che la view `scadenzario` passi `can_view_visite` al context (già presente): se non lo passa, aggiungerlo (`"can_view_visite": can_view_visite`).

- [ ] **Step 4: Run test → PASSA**

Comando standard su `ScadenzarioRinnovoVisiteTests`. Atteso: `OK`, 2 test.

- [ ] **Step 5: Commit**

```powershell
git add django_app/anagrafica/views.py django_app/anagrafica/templates/anagrafica/pages/scadenzario.html django_app/anagrafica/tests_visite_sessione.py
git commit -m "feat(anagrafica): scadenzario - pulsante Rinnovo per gruppo visite (deep-link giornata) + tipo_id sulle voci"
```

---

### Task 10: Link di navigazione (dashboard visite + subnav)

**Files:**
- Modify: `django_app/anagrafica/templates/anagrafica/pages/visite_mediche_dashboard.html` (aggiungere link all'hub)
- Test: `django_app/anagrafica/tests_visite_sessione.py`

**Interfaces:** nessuna nuova.

- [ ] **Step 1: Scrivi il test**

```python
class DashboardLinkHubTests(TestCase):
    def test_dashboard_linka_hub_sessioni(self):
        user = User.objects.create_superuser(username="su-lnk", email="su-lnk@test.local", password="x")
        self.client.force_login(user)
        resp = self.client.get(reverse("anagrafica:visite_mediche_dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertIn("visite-mediche/sessioni/", resp.content.decode())
```

- [ ] **Step 2: Run test → FALLISCE.**

- [ ] **Step 3: Aggiungi il link**

In `visite_mediche_dashboard.html`, nell'area intestazione/azioni (dove c'è già il link a "nuova sessione" o le CTA), aggiungi:

```django
<a href="{% url 'anagrafica:visite_mediche_sessioni' %}" style="padding:8px 16px;background:#1f87cd;color:#fff;border-radius:8px;font-size:13px;font-weight:700;text-decoration:none;">📋 Sessioni & proposte</a>
```

(Individuare la barra azioni esistente in cima alla dashboard; se assente, aggiungerla sotto l'`<h1>`.)

- [ ] **Step 4: Run test → PASSA.**

- [ ] **Step 5: Commit**

```powershell
git add django_app/anagrafica/templates/anagrafica/pages/visite_mediche_dashboard.html django_app/anagrafica/tests_visite_sessione.py
git commit -m "feat(anagrafica): link alla dashboard visite verso l'hub Sessioni & proposte"
```

---

### Task 11: Aggiornare i test del vecchio flusso + regressione app

**Files:**
- Modify: `django_app/anagrafica/tests_visite_sessione.py` (classi del vecchio POST mono-tipo)

**Interfaces:** nessuna.

- [ ] **Step 1: Rimuovere/riscrivere le classi obsolete**

Il vecchio flusso a 2 step non esiste più. Nel file `tests_visite_sessione.py`:
- **`SessioneBatchPostTests`** e **`SessioneStep2RenderTests`** testano il vecchio POST `step=2` e il vecchio render → **eliminarle** (il nuovo comportamento è coperto da `GiornataPostTests` e `GiornataRenderTests`).
- Le altre classi (`UltimeVisiteCorrentiIdsTests`, `DashboardScadenzeConfermateTests`, `DigestVisiteCorrentiTests`, `CandidatiSessioneTests`, `ApiCercaDipendenteTests`) restano invariate.

- [ ] **Step 2: Regressione — intera app anagrafica (DB fresco per le migrazioni)**

```powershell
Set-Location C:\Dev\pn-visite-giornata
& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" django_app\manage.py test anagrafica --settings=config.settings.test --verbosity 1 2>&1 | Select-Object -Last 20
```

Atteso: `OK` (a parte l'eventuale test cosmetico pre-esistente `ScadenzarioEstesoTests.test_prova_futura_inclusa_prova_passata_esclusa`, non toccato da questo lavoro — se ancora rosso, è pre-esistente; verificare che sia l'UNICO fallimento).

- [ ] **Step 3: Commit**

```powershell
git add django_app/anagrafica/tests_visite_sessione.py
git commit -m "test(anagrafica): sostituiti i test del vecchio flusso sessione mono-tipo con quelli della Giornata"
```

---

### Task 12: CHANGELOG, README, push

**Files:**
- Modify: `CHANGELOG.md`, `README.md`

- [ ] **Step 1: CHANGELOG** — sotto `## [Unreleased]` → `### Added` (creala se assente, in cima):

```markdown
- **Visite mediche · "Giornata visite" reattiva, sessioni salvate e proposte di rinnovo** (`django_app/anagrafica/models.py`, `django_app/anagrafica/migrations/00NN_visitasessione.py` [nuovo], `django_app/anagrafica/views.py`, `django_app/anagrafica/urls.py`, `django_app/anagrafica/templates/anagrafica/pages/visite_mediche_nuova_sessione.html`, `.../visite_mediche_sessioni.html` [nuovo], `.../visite_mediche_sessione_detail.html` [nuovo], `.../partials/_visite_candidati.html` [nuovo], `.../pages/scadenzario.html`, `.../pages/visite_mediche_dashboard.html`, `django_app/anagrafica/tests_visite_sessione.py`). La registrazione sessione diventa una **"Giornata visite" multi-tipo e reattiva**: data + medico + un elenco di persone ciascuna con la propria visita dovuta (tipi misti), coi candidati caricati live via HTMX (filtro tipo senza reload, scorciatoie, barra sticky). Nuovo modello **`VisitaSessione`** (data/medico/luogo/note) con FK nullable `VisitaMedica.sessione` (SET_NULL: eliminando la giornata le visite restano) → **lista + dettaglio consultabili** e **aggiunta partecipanti a posteriori**. Nuovo **hub «Sessioni & proposte»** (`/anagrafica/visite-mediche/sessioni/`) che, per tipo, propone chi è da rinnovare (scaduti/in scadenza sulle visite correnti) e apre la giornata già pre-caricata; più «Giornata completa» con tutti i dovuti. Lo **scadenzario** guadagna un pulsante «↻ Rinnovo» per gruppo (le voci visite ora portano `tipo_id`) che deep-linka alla giornata filtrata su quel tipo; i gruppi qualifiche puntano alla loro sessione di rinnovo esistente. Riuso totale della logica candidati «consona» già vetata (ruoli + MOD.128, cessati esclusi, storico) e dei guardrail (anti-doppione, no date future, prescrizioni/note separate, referto). Migrazione additiva, privacy invariata (gating `_can_view_visite_mediche`). Verifica: suite `anagrafica` verde.
```

- [ ] **Step 2: README** — nel bullet «Visite mediche», dopo la frase sulla sessione batch, aggiungere:

```markdown
La sessione è una **«Giornata visite» reattiva e multi-tipo** (`VisitaSessione`): data+medico e un elenco di persone ciascuna con la propria visita dovuta, candidati live via HTMX; giornate salvate con lista/dettaglio e aggiunta partecipanti a posteriori. **Hub «Sessioni & proposte»** (`/anagrafica/visite-mediche/sessioni/`) con proposte di rinnovo per tipo e «Giornata completa»; punti d'ingresso anche dallo **scadenzario** (pulsante «↻ Rinnovo» per gruppo, deep-link `?tipo=`).
```

- [ ] **Step 3: Commit e push**

```powershell
git add CHANGELOG.md README.md
git commit -m "docs(anagrafica): changelog e readme per la Giornata visite reattiva e le proposte di rinnovo"
git push -u origin feature/anagrafica-visite-giornata
```

- [ ] **Step 4: Riepilogo finale** all'utente: branch, commit, esito test, file toccati; ricordare che il worktree `C:\Dev\pn-visite-giornata` è rimovibile dopo il merge.

---

## Idee future (fuori scope)
Picker "+ Aggiungi persona" in giornata con scelta tipo (riuso `visite_mediche_api_cerca_dipendente` con `tipo_id`); PDF "registro giornata"; notifica al dipendente; stato "programmata/convocazione".
