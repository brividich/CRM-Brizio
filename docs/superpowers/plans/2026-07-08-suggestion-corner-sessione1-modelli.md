# Suggestion Corner — Sessione 1: Modelli + Migrations + Admin base

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Creare l'app Django `suggestion_corner` con il data layer completo (modelli + migrations) e l'admin base, così che le sessioni successive (FSM, ACL, form pubblico, notifiche, migrazione, AI, dashboard) abbiano fondamenta stabili e testate.

**Architecture:** Nuova app top-level `suggestion_corner` (isola il futuro endpoint pubblico). Il record principale `SuggestionCorner` porta un `FSMField` (default `INSERITA`, `protected=True`) — le `@transition` arrivano in sessione 2, seguendo il pattern maturo di `gestione_specifiche`. Le scadenze DO/CHECK sono `@property` calcolate a runtime (non colonne, per evitare disallineamenti). Modelli di supporto: allegati, storico audit, config singleton, mapping processi-liberi→ProcessoQualificato (Δ2). Admin base con `stato` readonly e storico immutabile.

**Tech Stack:** Django 5.2, Python 3.11+, `django-fsm-2==4.2.4` (già in requirements), SQLite in dev / SQL Server in test-prod. Test runner Django (`manage.py test`).

## Global Constraints

- Nessun file dati reale (CSV/PDF/xlsx) committato. Solo codice.
- FK persone → `settings.AUTH_USER_MODEL`. FK reparto → `anagrafica.Reparto`. FK processo → `anagrafica.ProcessoQualificato` (nullable, `SET_NULL`).
- `stato` è `FSMField(protected=True)` → readonly in admin; nessuna transizione definita in questa sessione.
- Scadenze DO/CHECK = `@property`, MAI colonne.
- Test scoped, dalla root repo, con venv: `.venv\Scripts\python.exe django_app\manage.py test suggestion_corner --keepdb --settings=config.settings.test` — label app **`suggestion_corner`** (NON `django_app.suggestion_corner`).
- CHANGELOG.md aggiornato a fine sessione (sezione `[Unreleased]`), con tutti i file toccati.
- La nuova app va registrata in `config/settings/base.py` INSTALLED_APPS **e** in `core/module_registry.py` `MODULE_DEFINITIONS` (altrimenti Setup Wizard salta il migrate → 500 in prod).
- Pattern di riferimento da imitare: `gestione_specifiche/` (models FSMField, admin, apps.ready).

---

### Task 1: Scaffold app `suggestion_corner` + registrazione

**Files:**
- Create: `django_app/suggestion_corner/__init__.py`
- Create: `django_app/suggestion_corner/apps.py`
- Create: `django_app/suggestion_corner/models.py` (vuoto con solo import iniziale)
- Create: `django_app/suggestion_corner/admin.py` (vuoto placeholder)
- Create: `django_app/suggestion_corner/migrations/__init__.py`
- Create: `django_app/suggestion_corner/tests/__init__.py`
- Modify: `django_app/config/settings/base.py:453` (aggiungere alla lista INSTALLED_APPS)
- Modify: `django_app/core/module_registry.py` (aggiungere entry a `MODULE_DEFINITIONS`)

**Interfaces:**
- Produces: app label `suggestion_corner`; `SuggestionCornerConfig(AppConfig)` con `name = "suggestion_corner"`.

- [ ] **Step 1: Creare i file scaffold vuoti**

`django_app/suggestion_corner/__init__.py`: file vuoto.

`django_app/suggestion_corner/migrations/__init__.py`: file vuoto.

`django_app/suggestion_corner/tests/__init__.py`: file vuoto.

`django_app/suggestion_corner/models.py`:
```python
"""Modelli del modulo Suggestion Corner (SMS — Sistema di Miglioramento/Segnalazione).

Vedi docs/superpowers/specs/2026-07-08-suggestion-corner-design.md e
docs/BUILD_SPEC_suggestion_corner.md.
"""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone
from django_fsm import FSMField
```

`django_app/suggestion_corner/admin.py`:
```python
"""Admin Django per suggestion_corner."""
from __future__ import annotations

from django.contrib import admin  # noqa: F401  (registrazioni aggiunte nei task successivi)
```

`django_app/suggestion_corner/apps.py`:
```python
from django.apps import AppConfig


class SuggestionCornerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "suggestion_corner"
    verbose_name = "Suggestion Corner"
```

- [ ] **Step 2: Registrare l'app in INSTALLED_APPS**

In `django_app/config/settings/base.py`, dopo la riga `"procedure_refresh.apps.ProcedureRefreshConfig",` (riga 453) aggiungere:
```python
    "suggestion_corner.apps.SuggestionCornerConfig",
```

- [ ] **Step 3: Registrare il modulo nel registry**

In `django_app/core/module_registry.py`, dentro il dict `MODULE_DEFINITIONS`, aggiungere una entry (adattare `order` a un valore libero, es. 95, per collocarlo tra i moduli operativi):
```python
    "suggestion_corner": ModuleDefinition(
        key="suggestion_corner",
        default_label="Suggestion Corner",
        icon="lightbulb",
        order=95,
        route_name="suggestion_corner:home",
        route_namespace="suggestion_corner",
        permission_namespace="suggestion_corner",
        navigation_codes=("suggestion_corner",),
        default_short_label="SMS",
        default_menu_label="Suggestion Corner",
        default_dashboard_label="Suggestion Corner",
    ),
```
Nota: la route `suggestion_corner:home` non esiste ancora (arriva in sessione 3). La definizione nel registry è dichiarativa e non rompe `check`; il menu resterà inerte finché la route non esiste.

- [ ] **Step 4: Verificare che il progetto carichi**

Run: `.venv\Scripts\python.exe django_app\manage.py check --settings=config.settings.test`
Expected: `System check identified no issues` (0 errori). Se compare un errore su `route_name` inesistente, ignorabile solo se è un warning; se è un errore, rimuovere temporaneamente `route_name`/`route_namespace` dalla entry e rimetterli in sessione 3.

- [ ] **Step 5: Commit**

```bash
git add django_app/suggestion_corner/__init__.py django_app/suggestion_corner/apps.py django_app/suggestion_corner/models.py django_app/suggestion_corner/admin.py django_app/suggestion_corner/migrations/__init__.py django_app/suggestion_corner/tests/__init__.py django_app/config/settings/base.py django_app/core/module_registry.py
git commit -m "feat(suggestion_corner): scaffold app + registrazione INSTALLED_APPS/module_registry"
```

---

### Task 2: Modello `SuggestionCorner` (record principale)

**Files:**
- Modify: `django_app/suggestion_corner/models.py`
- Create: `django_app/suggestion_corner/tests/test_models.py`
- Create (auto): `django_app/suggestion_corner/migrations/0001_initial.py`

**Interfaces:**
- Produces: `SuggestionCorner` con enum interni `StatoSMS`, `EsitoAttivita`, `EsitoCheck`; `stato = FSMField(default="INSERITA", protected=True)`; `@property scaduto_do`, `@property scaduto_check`.
- Consumes: `anagrafica.Reparto`, `anagrafica.ProcessoQualificato`, `settings.AUTH_USER_MODEL`.

- [ ] **Step 1: Scrivere il test che fallisce**

`django_app/suggestion_corner/tests/test_models.py`:
```python
from __future__ import annotations

import datetime

from django.test import TestCase
from django.utils import timezone

from anagrafica.models import Reparto
from suggestion_corner.models import SuggestionCorner


class SuggestionCornerModelTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="TORNI")

    def _base(self, **kw):
        defaults = dict(
            reparto_provenienza=self.reparto,
            opportunity="Migliorare l'illuminazione del reparto.",
        )
        defaults.update(kw)
        return SuggestionCorner.objects.create(**defaults)

    def test_stato_default_inserita(self):
        s = self._base()
        self.assertEqual(s.stato, "INSERITA")
        self.assertEqual(s.stato_sms, SuggestionCorner.StatoSMS.DA_GESTIRE)
        self.assertTrue(s.da_portale)
        self.assertFalse(s.anonima)

    def test_scaduto_do_true_quando_limite_passato_e_non_eseguito(self):
        ieri = timezone.now().date() - datetime.timedelta(days=1)
        s = self._base(data_limite_esecuzione=ieri, do_eseguito=False)
        self.assertTrue(s.scaduto_do)

    def test_scaduto_do_false_se_eseguito(self):
        ieri = timezone.now().date() - datetime.timedelta(days=1)
        s = self._base(data_limite_esecuzione=ieri, do_eseguito=True)
        self.assertFalse(s.scaduto_do)

    def test_scaduto_do_false_senza_limite(self):
        s = self._base()
        self.assertFalse(s.scaduto_do)

    def test_scaduto_check_true_quando_limite_passato_e_non_eseguito(self):
        ieri = timezone.now().date() - datetime.timedelta(days=1)
        s = self._base(data_limite_controllo=ieri, check_eseguito=False)
        self.assertTrue(s.scaduto_check)
```

- [ ] **Step 2: Eseguire il test — deve fallire**

Run: `.venv\Scripts\python.exe django_app\manage.py test suggestion_corner.tests.test_models --settings=config.settings.test`
Expected: FAIL — `ImportError`/`AttributeError` perché `SuggestionCorner` non è ancora definito (o non ha i campi).

- [ ] **Step 3: Implementare il modello**

Appendere a `django_app/suggestion_corner/models.py` (dopo gli import del Task 1):
```python
class SuggestionCorner(models.Model):
    class StatoSMS(models.TextChoices):
        DA_GESTIRE = "DA_GESTIRE", "Da gestire"
        SMS_SI = "SMS_SI", "SMS Sì"
        SMS_NO = "SMS_NO", "SMS No"

    class EsitoAttivita(models.TextChoices):
        SI = "SI", "Sì"
        NO = "NO", "No"

    class EsitoCheck(models.TextChoices):
        POSITIVO = "POSITIVO", "Positivo"
        NEGATIVO = "NEGATIVO", "Negativo"
        RINVIATO = "RINVIATO", "Rinviato"

    # Identificazione / provenienza
    legacy_sharepoint_id = models.IntegerField(null=True, blank=True, unique=True, db_index=True)
    da_portale = models.BooleanField(default=True)  # True = nuovo, False = migrato
    anonima = models.BooleanField(default=False)

    data_segnalazione = models.DateField(auto_now_add=True)
    reparto_provenienza = models.ForeignKey(
        "anagrafica.Reparto", on_delete=models.PROTECT,
        related_name="segnalazioni_provenienza",
    )
    reparto_destinazione = models.ForeignKey(
        "anagrafica.Reparto", on_delete=models.PROTECT, null=True, blank=True,
        related_name="segnalazioni_destinazione",
    )
    processo = models.ForeignKey(
        "anagrafica.ProcessoQualificato", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="segnalazioni",
    )
    processo_libero = models.CharField(max_length=255, blank=True)

    opportunity = models.TextField()

    # PLAN
    plan_testo = models.TextField(blank=True)
    plan_eseguito = models.BooleanField(default=False)
    incaricato = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="suggestioncorner_do",
    )
    controllore = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name="suggestioncorner_check",
    )
    data_limite_esecuzione = models.DateField(null=True, blank=True)
    data_limite_controllo = models.DateField(null=True, blank=True)

    # DO
    do_testo = models.TextField(blank=True)
    do_eseguito = models.BooleanField(default=False)
    data_esecuzione_do = models.DateField(null=True, blank=True)
    esito_do = models.CharField(max_length=8, choices=EsitoAttivita.choices, blank=True)

    # CHECK
    check_testo = models.TextField(blank=True)
    check_eseguito = models.BooleanField(default=False)
    data_esecuzione_check = models.DateField(null=True, blank=True)
    esito_check = models.CharField(max_length=10, choices=EsitoCheck.choices, blank=True)

    # ACT
    vuoi_inserire_act = models.BooleanField(default=False)
    act_testo = models.TextField(blank=True)
    act_eseguito = models.BooleanField(default=False)
    nuova_segnalazione_da_act = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="generata_da",
    )

    # Stato FSM (transizioni in sessione 2)
    stato = FSMField(default="INSERITA", protected=True, max_length=30, db_index=True)
    stato_sms = models.CharField(
        max_length=10, choices=StatoSMS.choices, default=StatoSMS.DA_GESTIRE,
    )

    # Reminder tracking (§3) — flag per soglia, la scadenza è calcolata a runtime
    sollecito_do_30 = models.BooleanField(default=False)
    sollecito_do_15 = models.BooleanField(default=False)
    sollecito_do_5 = models.BooleanField(default=False)
    sollecito_check_30 = models.BooleanField(default=False)
    sollecito_check_15 = models.BooleanField(default=False)
    sollecito_check_5 = models.BooleanField(default=False)
    escalation_do_inviata = models.BooleanField(default=False)
    escalation_check_inviata = models.BooleanField(default=False)

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )

    class Meta:
        verbose_name = "Segnalazione Suggestion Corner"
        verbose_name_plural = "Segnalazioni Suggestion Corner"
        ordering = ["-data_segnalazione", "-id"]

    def __str__(self) -> str:
        return f"SC#{self.pk} — {self.opportunity[:40]}"

    @property
    def scaduto_do(self) -> bool:
        return bool(
            self.data_limite_esecuzione
            and not self.do_eseguito
            and self.data_limite_esecuzione < timezone.now().date()
        )

    @property
    def scaduto_check(self) -> bool:
        return bool(
            self.data_limite_controllo
            and not self.check_eseguito
            and self.data_limite_controllo < timezone.now().date()
        )
```

- [ ] **Step 4: Generare la migration**

Run: `.venv\Scripts\python.exe django_app\manage.py makemigrations suggestion_corner --settings=config.settings.test`
Expected: crea `0001_initial.py` con `SuggestionCorner`. Verificare che il file NON contenga riferimenti a modelli inesistenti.

- [ ] **Step 5: Eseguire i test — devono passare**

Run: `.venv\Scripts\python.exe django_app\manage.py test suggestion_corner.tests.test_models --settings=config.settings.test`
Expected: PASS (5 test).

- [ ] **Step 6: Commit**

```bash
git add django_app/suggestion_corner/models.py django_app/suggestion_corner/tests/test_models.py django_app/suggestion_corner/migrations/0001_initial.py
git commit -m "feat(suggestion_corner): modello SuggestionCorner + property scadenze DO/CHECK"
```

---

### Task 3: Modello `SuggestionCornerAllegato`

**Files:**
- Modify: `django_app/suggestion_corner/models.py`
- Modify: `django_app/suggestion_corner/tests/test_models.py`
- Create (auto): `django_app/suggestion_corner/migrations/0002_*.py`

**Interfaces:**
- Consumes: `SuggestionCorner` (Task 2).
- Produces: `SuggestionCornerAllegato` con `segnalazione` FK (related_name `allegati`), `file`, `link_esterno`.

- [ ] **Step 1: Scrivere il test che fallisce**

Appendere a `django_app/suggestion_corner/tests/test_models.py`:
```python
class SuggestionCornerAllegatoTest(TestCase):
    def test_allegato_link_esterno(self):
        from suggestion_corner.models import SuggestionCornerAllegato

        reparto = Reparto.objects.create(nome="CNC")
        seg = SuggestionCorner.objects.create(
            reparto_provenienza=reparto, opportunity="Test allegato.",
        )
        a = SuggestionCornerAllegato.objects.create(
            segnalazione=seg,
            link_esterno=r"\\novisrv\Area Qualita\SMS_Suggestion Corner\2024",
        )
        self.assertEqual(seg.allegati.count(), 1)
        self.assertIn("novisrv", a.link_esterno)
```

- [ ] **Step 2: Eseguire il test — deve fallire**

Run: `.venv\Scripts\python.exe django_app\manage.py test suggestion_corner.tests.test_models.SuggestionCornerAllegatoTest --settings=config.settings.test`
Expected: FAIL — `ImportError` su `SuggestionCornerAllegato`.

- [ ] **Step 3: Implementare il modello**

Appendere a `django_app/suggestion_corner/models.py`:
```python
class SuggestionCornerAllegato(models.Model):
    segnalazione = models.ForeignKey(
        SuggestionCorner, on_delete=models.CASCADE, related_name="allegati",
    )
    file = models.FileField(upload_to="suggestion_corner/%Y/", blank=True)
    link_esterno = models.URLField(blank=True, max_length=500)
    caricato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
    )
    caricato_il = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Allegato segnalazione"
        verbose_name_plural = "Allegati segnalazione"

    def __str__(self) -> str:
        return self.file.name or self.link_esterno or f"Allegato #{self.pk}"
```
Nota: `link_esterno` è `URLField` con `max_length=500`; i path UNC `\\novisrv\...` sono testo tecnico salvato per recupero manuale (§1.2), la validazione URL non viene applicata perché il valore arriva dallo script di migrazione, non da un form. Se un test dovesse fallire su validazione URL, sostituire con `models.CharField(max_length=500, blank=True)`.

- [ ] **Step 4: Generare la migration + eseguire i test**

Run: `.venv\Scripts\python.exe django_app\manage.py makemigrations suggestion_corner --settings=config.settings.test`
Run: `.venv\Scripts\python.exe django_app\manage.py test suggestion_corner.tests.test_models --settings=config.settings.test`
Expected: PASS. Se il test fallisce per validazione `URLField` su path UNC, applicare la nota dello Step 3 (CharField) e rigenerare la migration.

- [ ] **Step 5: Commit**

```bash
git add django_app/suggestion_corner/models.py django_app/suggestion_corner/tests/test_models.py django_app/suggestion_corner/migrations/0002_*.py
git commit -m "feat(suggestion_corner): modello allegati (file + link_esterno per path UNC)"
```

---

### Task 4: Modello `SuggestionCornerStorico` (audit trail)

**Files:**
- Modify: `django_app/suggestion_corner/models.py`
- Modify: `django_app/suggestion_corner/tests/test_models.py`
- Create (auto): `django_app/suggestion_corner/migrations/0003_*.py`

**Interfaces:**
- Consumes: `SuggestionCorner`.
- Produces: `SuggestionCornerStorico` (related_name `storico`) con `stato_precedente`, `stato_nuovo`, `campo_modificato`, `valore_precedente`, `valore_nuovo`, `autore`, `timestamp`. Il popolamento automatico (signal/pre_save) è sessione 7 — qui solo lo schema.

- [ ] **Step 1: Scrivere il test che fallisce**

Appendere a `django_app/suggestion_corner/tests/test_models.py`:
```python
class SuggestionCornerStoricoTest(TestCase):
    def test_storico_voce_manuale(self):
        from suggestion_corner.models import SuggestionCornerStorico

        reparto = Reparto.objects.create(nome="PRESETTING")
        seg = SuggestionCorner.objects.create(
            reparto_provenienza=reparto, opportunity="Test storico.",
        )
        v = SuggestionCornerStorico.objects.create(
            segnalazione=seg, stato_precedente="INSERITA", stato_nuovo="DA_CLASSIFICARE",
        )
        self.assertEqual(seg.storico.count(), 1)
        self.assertEqual(v.stato_nuovo, "DA_CLASSIFICARE")
```

- [ ] **Step 2: Eseguire il test — deve fallire**

Run: `.venv\Scripts\python.exe django_app\manage.py test suggestion_corner.tests.test_models.SuggestionCornerStoricoTest --settings=config.settings.test`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implementare il modello**

Appendere a `django_app/suggestion_corner/models.py`:
```python
class SuggestionCornerStorico(models.Model):
    segnalazione = models.ForeignKey(
        SuggestionCorner, on_delete=models.CASCADE, related_name="storico",
    )
    stato_precedente = models.CharField(max_length=30)
    stato_nuovo = models.CharField(max_length=30)
    campo_modificato = models.CharField(max_length=50, blank=True)
    valore_precedente = models.TextField(blank=True)
    valore_nuovo = models.TextField(blank=True)
    autore = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
    )
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Voce storico segnalazione"
        verbose_name_plural = "Storico segnalazione"
        ordering = ["-timestamp", "-id"]

    def __str__(self) -> str:
        return f"SC#{self.segnalazione_id}: {self.stato_precedente}→{self.stato_nuovo}"
```

- [ ] **Step 4: Generare la migration + eseguire i test**

Run: `.venv\Scripts\python.exe django_app\manage.py makemigrations suggestion_corner --settings=config.settings.test`
Run: `.venv\Scripts\python.exe django_app\manage.py test suggestion_corner.tests.test_models --settings=config.settings.test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add django_app/suggestion_corner/models.py django_app/suggestion_corner/tests/test_models.py django_app/suggestion_corner/migrations/0003_*.py
git commit -m "feat(suggestion_corner): modello storico audit trail (schema)"
```

---

### Task 5: Modello `SuggestionCornerConfig` (singleton) + `SuggestionCornerProcessoMapping` (Δ2)

**Files:**
- Modify: `django_app/suggestion_corner/models.py`
- Modify: `django_app/suggestion_corner/tests/test_models.py`
- Create (auto): `django_app/suggestion_corner/migrations/0004_*.py`

**Interfaces:**
- Produces:
  - `SuggestionCornerConfig` singleton (pk forzato a 1) con soglie solleciti/escalation, email responsabile, nome gruppo SMS_TEAM. Classmethod `load()`.
  - `SuggestionCornerProcessoMapping` con `valore_libero` (unique) → `processo` FK (nullable) + `is_default`.

- [ ] **Step 1: Scrivere il test che fallisce**

Appendere a `django_app/suggestion_corner/tests/test_models.py`:
```python
class SuggestionCornerConfigTest(TestCase):
    def test_config_singleton_forza_pk_1(self):
        from suggestion_corner.models import SuggestionCornerConfig

        c1 = SuggestionCornerConfig.load()
        c1.giorni_sollecito_1 = 20
        c1.save()
        c2 = SuggestionCornerConfig.load()
        self.assertEqual(c2.pk, 1)
        self.assertEqual(c2.giorni_sollecito_1, 20)
        self.assertEqual(SuggestionCornerConfig.objects.count(), 1)

    def test_config_default(self):
        from suggestion_corner.models import SuggestionCornerConfig

        c = SuggestionCornerConfig.load()
        self.assertEqual(c.giorni_sollecito_1, 30)
        self.assertEqual(c.giorni_sollecito_2, 15)
        self.assertEqual(c.giorni_sollecito_3, 5)
        self.assertEqual(c.giorni_escalation_oltre_scadenza, 7)
        self.assertEqual(c.sms_team_group_name, "SMS_TEAM")


class SuggestionCornerProcessoMappingTest(TestCase):
    def test_mapping_valore_libero_unique(self):
        from django.db import IntegrityError

        from suggestion_corner.models import SuggestionCornerProcessoMapping

        SuggestionCornerProcessoMapping.objects.create(valore_libero="Tornitura")
        with self.assertRaises(IntegrityError):
            SuggestionCornerProcessoMapping.objects.create(valore_libero="Tornitura")
```

- [ ] **Step 2: Eseguire i test — devono fallire**

Run: `.venv\Scripts\python.exe django_app\manage.py test suggestion_corner.tests.test_models.SuggestionCornerConfigTest suggestion_corner.tests.test_models.SuggestionCornerProcessoMappingTest --settings=config.settings.test`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implementare i modelli**

Appendere a `django_app/suggestion_corner/models.py`:
```python
class SuggestionCornerConfig(models.Model):
    giorni_sollecito_1 = models.PositiveIntegerField(default=30)
    giorni_sollecito_2 = models.PositiveIntegerField(default=15)
    giorni_sollecito_3 = models.PositiveIntegerField(default=5)
    giorni_escalation_oltre_scadenza = models.PositiveIntegerField(default=7)
    email_responsabile_escalation = models.EmailField(blank=True)
    sms_team_group_name = models.CharField(max_length=100, default="SMS_TEAM")

    class Meta:
        verbose_name = "Configurazione Suggestion Corner"
        verbose_name_plural = "Configurazione Suggestion Corner"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "SuggestionCornerConfig":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self) -> str:
        return "Configurazione Suggestion Corner"


class SuggestionCornerProcessoMapping(models.Model):
    """Δ2 — normalizzazione: aggancia un valore `processo_libero` a un
    `ProcessoQualificato` reale (o lo marca come default), curabile da admin."""
    valore_libero = models.CharField(max_length=255, unique=True)
    processo = models.ForeignKey(
        "anagrafica.ProcessoQualificato", on_delete=models.CASCADE, null=True, blank=True,
        related_name="suggestion_mapping",
    )
    is_default = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Mappatura processo"
        verbose_name_plural = "Mappature processi (Suggestion Corner)"
        ordering = ["valore_libero"]

    def __str__(self) -> str:
        return f"{self.valore_libero} → {self.processo or '(default)'}"
```

- [ ] **Step 4: Generare la migration + eseguire i test**

Run: `.venv\Scripts\python.exe django_app\manage.py makemigrations suggestion_corner --settings=config.settings.test`
Run: `.venv\Scripts\python.exe django_app\manage.py test suggestion_corner.tests.test_models --settings=config.settings.test`
Expected: PASS (tutti i test del file).

- [ ] **Step 5: Commit**

```bash
git add django_app/suggestion_corner/models.py django_app/suggestion_corner/tests/test_models.py django_app/suggestion_corner/migrations/0004_*.py
git commit -m "feat(suggestion_corner): config singleton + mapping processi liberi (Δ2)"
```

---

### Task 6: Admin base

**Files:**
- Modify: `django_app/suggestion_corner/admin.py`
- Create: `django_app/suggestion_corner/tests/test_admin.py`

**Interfaces:**
- Consumes: tutti i modelli dei task 2–5.
- Produces: registrazioni admin con `stato` readonly, storico immutabile (no add/change), config singleton, mapping processi editabile.

- [ ] **Step 1: Scrivere il test che fallisce**

`django_app/suggestion_corner/tests/test_admin.py`:
```python
from __future__ import annotations

from django.contrib.admin.sites import site

from django.test import TestCase

from suggestion_corner.models import (
    SuggestionCorner, SuggestionCornerConfig, SuggestionCornerProcessoMapping,
)


class SuggestionCornerAdminTest(TestCase):
    def test_modelli_registrati(self):
        self.assertIn(SuggestionCorner, site._registry)
        self.assertIn(SuggestionCornerConfig, site._registry)
        self.assertIn(SuggestionCornerProcessoMapping, site._registry)

    def test_stato_readonly(self):
        admin_obj = site._registry[SuggestionCorner]
        self.assertIn("stato", admin_obj.get_readonly_fields(request=None))
```

- [ ] **Step 2: Eseguire il test — deve fallire**

Run: `.venv\Scripts\python.exe django_app\manage.py test suggestion_corner.tests.test_admin --settings=config.settings.test`
Expected: FAIL — modelli non registrati / `stato` non readonly.

- [ ] **Step 3: Implementare l'admin**

Sostituire il contenuto di `django_app/suggestion_corner/admin.py`:
```python
"""Admin Django per suggestion_corner.

`stato` è FSMField protected → readonly (si cambia solo via transizioni, sessione 2).
Lo storico è audit immutabile → sola lettura inline.
"""
from __future__ import annotations

from django.contrib import admin

from .models import (
    SuggestionCorner, SuggestionCornerAllegato, SuggestionCornerConfig,
    SuggestionCornerProcessoMapping, SuggestionCornerStorico,
)


class SuggestionCornerAllegatoInline(admin.TabularInline):
    model = SuggestionCornerAllegato
    extra = 0
    fields = ("file", "link_esterno", "caricato_da", "caricato_il")
    readonly_fields = ("caricato_il",)


class SuggestionCornerStoricoInline(admin.TabularInline):
    model = SuggestionCornerStorico
    extra = 0
    can_delete = False
    fields = ("timestamp", "stato_precedente", "stato_nuovo", "campo_modificato", "autore")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(SuggestionCorner)
class SuggestionCornerAdmin(admin.ModelAdmin):
    list_display = ("id", "data_segnalazione", "reparto_provenienza", "stato", "stato_sms", "da_portale")
    list_filter = ("stato", "stato_sms", "da_portale", "reparto_provenienza")
    search_fields = ("opportunity", "processo_libero", "legacy_sharepoint_id")
    readonly_fields = ("stato", "created_at", "updated_at", "data_segnalazione")
    inlines = [SuggestionCornerAllegatoInline, SuggestionCornerStoricoInline]

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields


@admin.register(SuggestionCornerConfig)
class SuggestionCornerConfigAdmin(admin.ModelAdmin):
    list_display = ("__str__", "giorni_sollecito_1", "giorni_escalation_oltre_scadenza", "sms_team_group_name")

    def has_add_permission(self, request):
        return not SuggestionCornerConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(SuggestionCornerProcessoMapping)
class SuggestionCornerProcessoMappingAdmin(admin.ModelAdmin):
    list_display = ("valore_libero", "processo", "is_default")
    list_editable = ("processo", "is_default")
    search_fields = ("valore_libero",)
```

- [ ] **Step 4: Eseguire il test — deve passare**

Run: `.venv\Scripts\python.exe django_app\manage.py test suggestion_corner.tests.test_admin --settings=config.settings.test`
Expected: PASS (2 test).

- [ ] **Step 5: Commit**

```bash
git add django_app/suggestion_corner/admin.py django_app/suggestion_corner/tests/test_admin.py
git commit -m "feat(suggestion_corner): admin base (stato readonly, storico immutabile, config singleton, mapping)"
```

---

### Task 7: Verifica finale sessione + CHANGELOG

**Files:**
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: tutto il lavoro dei task 1–6.

- [ ] **Step 1: Eseguire l'intera suite del modulo**

Run: `.venv\Scripts\python.exe django_app\manage.py test suggestion_corner --keepdb --settings=config.settings.test`
Expected: PASS su tutti i test (models + admin).

- [ ] **Step 2: `check` di sistema**

Run: `.venv\Scripts\python.exe django_app\manage.py check --settings=config.settings.test`
Expected: `System check identified no issues`.

- [ ] **Step 3: Applicare le migrations nel checkout locale (dev)**

Run: `.venv\Scripts\python.exe django_app\manage.py migrate suggestion_corner --settings=config.settings.dev`
Expected: applica 0001–0004 senza errori. (Regola HUB: le modifiche devono finire nel checkout locale, non solo su git.)

- [ ] **Step 4: Aggiornare il CHANGELOG**

In `CHANGELOG.md`, sotto `[Unreleased]`, aggiungere una voce `### Added` con:
```markdown
- **Suggestion Corner (sessione 1 — data layer):** nuova app `suggestion_corner` con modelli `SuggestionCorner` (FSMField stato, property scadenze DO/CHECK), `SuggestionCornerAllegato`, `SuggestionCornerStorico` (audit), `SuggestionCornerConfig` (singleton) e `SuggestionCornerProcessoMapping` (normalizzazione processi liberi → ProcessoQualificato). Admin base con `stato` readonly e storico immutabile. Registrazione in INSTALLED_APPS e module_registry. File: django_app/suggestion_corner/{apps,models,admin}.py, migrations 0001-0004, django_app/config/settings/base.py, django_app/core/module_registry.py.
```

- [ ] **Step 5: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs(suggestion_corner): CHANGELOG sessione 1 (data layer + admin)"
```

---

## Self-Review (fatto in fase di stesura)

- **Copertura design §1 (modelli):** `SuggestionCorner` (Task 2), `SuggestionCornerAllegato` (Task 3), `SuggestionCornerStorico` (Task 4), `SuggestionCornerConfig` (Task 5) — tutti presenti. Δ2 mapping processi coperto da `SuggestionCornerProcessoMapping` (Task 5) + admin (Task 6). ✅
- **Fuori scope sessione 1 (rimandato ai piani successivi):** transizioni `@transition` + `state_machine` signal (sess. 2), validatore `incaricato != controllore` (sess. 2), ACL/viste (sess. 3), form pubblico + rate-limit + esclusione gate ACL (sess. 4), notifiche email/in-app (sess. 5–6), popolamento automatico storico (sess. 7), migrazione (sess. 8), AI (sess. 9), dashboard (sess. 10). Il `FSMField` è dichiarato ora ma senza transizioni: è un char field protected, valido e testabile (default `INSERITA`). ✅
- **Type consistency:** related_name usati (`allegati`, `storico`, `segnalazioni_provenienza`, `segnalazioni_destinazione`, `suggestioncorner_do`, `suggestioncorner_check`) coerenti tra modello e test. `SuggestionCornerConfig.load()` usato nei test e definito nel modello. ✅
- **Placeholder scan:** nessun TBD/TODO; ogni step ha codice o comando concreto. ✅
- **Rischio noto:** FK a `anagrafica.ProcessoQualificato` richiede che le migration MPQ (anagrafica 0076-0079) siano applicate al DB locale/test — lo sono su dev (memoria mod128). Se in un ambiente pulito la migration 0001 fallisse per modello mancante, applicare prima `migrate anagrafica`.
