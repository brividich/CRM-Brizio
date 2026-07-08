# Suggestion Corner — Sessione 2: FSM (transizioni + validazione + signal storico)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dotare `SuggestionCorner` della macchina a stati PDCA completa (transizioni `@transition` di django-fsm), della validazione di dominio `incaricato != controllore`, e dell'audit automatico che popola `SuggestionCornerStorico` ad ogni transizione — copiando il pattern maturo di `gestione_specifiche`.

**Architecture:** Le `@transition` vivono come metodi sul modello `SuggestionCorner` (come in `gestione_specifiche/models.py`). Ogni transizione prepara attore/payload via un helper `_prep_evento` (attributi transient) e cambia `stato` (FSMField protected). Un signal `post_transition` centralizzato in un nuovo modulo `suggestion_corner/state_machine.py` crea ESATTAMENTE una voce `SuggestionCornerStorico` per transizione; il modulo è agganciato in `apps.ready()`. La regola `incaricato != controllore` è un `clean()`/validator sul modello (NON dentro la FSM), con log di audit sul tentativo di bypass. Nessuna vista, nessuna email (sessioni 3 e 5). **Nessun cambiamento di schema → nessuna migration.**

**Tech Stack:** Django 5.2, Python 3.11+, `django-fsm-2==4.2.4` (`from django_fsm import transition`, `from django_fsm.signals import post_transition`), SQLite dev / SQL Server test-prod. Test runner Django.

## Global Constraints

- **Nessuna migration in questa sessione.** Aggiungere `@transition`/`clean()`/signal/costanti NON cambia lo schema. Un passo di verifica esegue `makemigrations suggestion_corner --check --dry-run` e si aspetta **"No changes detected"**. Se ne genera una, il modello è stato modificato in modo non voluto (es. `choices=` sul FSMField, default cambiato) → rimuovere la modifica di schema.
- Il campo `stato` resta `FSMField(default="INSERITA", protected=True, max_length=30, db_index=True)` **invariato** (nessun `choices=`, default resta la stringa letterale `"INSERITA"`).
- Le costanti di stato vanno in una classe annidata `Stato(models.TextChoices)` usata SOLO nei `source=`/`target=` delle transizioni (single source of truth leggibile), MAI cablata in `choices=` del field (eviterebbe la migration). I valori sono stringhe uguali a quelle già persistite.
- La regola `incaricato != controllore` è in `clean()` (solleva `ValidationError`), **non** in una `@transition`. `definisci_plan` la ri-controlla nel corpo (solleva `ValidationError`) perché imposta i due campi. `save()` logga un warning di audit se i due sono uguali e valorizzati (tentativo di bypass ISO 27001), senza bloccare.
- Il signal `post_transition` crea una `SuggestionCornerStorico` con `stato_precedente=source`, `stato_nuovo=instance.stato`, `autore=instance._evento_attore`. I campi `campo_modificato`/`valore_*` restano vuoti (diff di campo = sessione 7).
- Le transizioni cambiano `stato` in memoria; **il chiamante fa `.save()`** dopo (come in `gestione_specifiche`). Il signal crea lo storico al momento della chiamata del metodo di transizione.
- **Deviazione documentata dalla BUILD_SPEC §2:** le transizioni DO restano fedeli alla spec (`completa_do` registra `esito_do`, poi `avvia_check`/`do_da_rifare` con `conditions` su `esito_do` già impostato). Le 3 transizioni CHECK (`check_positivo`/`check_negativo`/`check_rinviato`) **registrano il proprio esito nel corpo** (il nome del metodo codifica l'esito) e NON usano `conditions`, perché la spec non prevede un `completa_check` che pre-imposti `esito_check` (si eviterebbe l'uovo-gallina condizione-vs-argomento).
- Pattern di riferimento da imitare 1:1: `gestione_specifiche/models.py` (`_prep_evento`, `@transition`), `gestione_specifiche/state_machine.py` (signal), `gestione_specifiche/apps.py` (`ready()` importa `state_machine`).
- Test scoped, dalla root repo, col venv: `.venv\Scripts\python.exe django_app\manage.py test suggestion_corner --keepdb --settings=config.settings.test` — label app **`suggestion_corner`**.
- Stage SOLO i file elencati per ogni task (working tree condiviso con WIP concorrente di altre sessioni — MAI `git add .` / `git add -A`).
- CHANGELOG.md aggiornato a fine sessione. **Attenzione:** il CHANGELOG contiene WIP non committato di altre sessioni; il controller lo gestisce fuori-banda (tecnica salva-patch/revert/edit/commit/riapplica) — il task 6 NON fa `git add CHANGELOG.md` da subagent.

## Riepilogo macchina a stati (target)

```
INSERITA --notifica_sms_team--> DA_CLASSIFICARE --classifica(stato_sms)--> CLASSIFICATA
CLASSIFICATA --definisci_plan(incaricato,controllore,date)--> PLAN_DEFINITO
PLAN_DEFINITO --avvia_do--> DO_IN_CORSO --completa_do(esito_do)--> DO_COMPLETATO
DO_COMPLETATO --avvia_check      [cond esito_do==SI]--> CHECK_IN_CORSO
DO_COMPLETATO --do_da_rifare(nuova_data) [cond esito_do==NO]--> DO_IN_CORSO
CHECK_IN_CORSO --check_positivo--> CHECK_COMPLETATO
CHECK_IN_CORSO --check_negativo--> DO_IN_CORSO        (riapre il DO)
CHECK_IN_CORSO --check_rinviato(nuova_data)--> CHECK_IN_CORSO  (self-loop)
CHECK_COMPLETATO --inserisci_act [cond vuoi_inserire_act]--> ACT_INSERITO
{CHECK_COMPLETATO, ACT_INSERITO} --chiudi--> CHIUSA
```

---

### Task 1: Costanti `Stato`, validazione `incaricato != controllore`, helper `_prep_evento`

**Files:**
- Modify: `django_app/suggestion_corner/models.py`
- Create: `django_app/suggestion_corner/tests/test_fsm.py`

**Interfaces:**
- Produces: `SuggestionCorner.Stato` (TextChoices, 10 stati); `SuggestionCorner.clean()` (solleva `ValidationError` se `incaricato == controllore` entrambi valorizzati); `SuggestionCorner.save()` che logga il bypass; `SuggestionCorner._prep_evento(attore=None, **payload)`.

- [ ] **Step 1: Scrivere il test che fallisce**

`django_app/suggestion_corner/tests/test_fsm.py`:
```python
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from anagrafica.models import Reparto
from suggestion_corner.models import SuggestionCorner

User = get_user_model()


class SuggestionCornerCleanTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="TORNI")
        self.u1 = User.objects.create(username="mario")
        self.u2 = User.objects.create(username="luigi")

    def _base(self, **kw):
        defaults = dict(reparto_provenienza=self.reparto, opportunity="Test.")
        defaults.update(kw)
        return SuggestionCorner(**defaults)

    def test_clean_ok_incaricato_diverso_da_controllore(self):
        s = self._base(incaricato=self.u1, controllore=self.u2)
        s.clean()  # non solleva

    def test_clean_ok_se_uno_dei_due_none(self):
        s = self._base(incaricato=self.u1, controllore=None)
        s.clean()  # non solleva

    def test_clean_solleva_se_incaricato_uguale_controllore(self):
        s = self._base(incaricato=self.u1, controllore=self.u1)
        with self.assertRaises(ValidationError):
            s.clean()

    def test_prep_evento_setta_transient(self):
        s = self._base()
        s._prep_evento(self.u1, foo="bar")
        self.assertEqual(s._evento_attore, self.u1)
        self.assertEqual(s._evento_payload, {"foo": "bar"})
```

- [ ] **Step 2: Eseguire il test — deve fallire**

Run: `.venv\Scripts\python.exe django_app\manage.py test suggestion_corner.tests.test_fsm --settings=config.settings.test`
Expected: FAIL — `AttributeError`/`ValidationError` non sollevata perché `clean()`/`_prep_evento` non esistono ancora.

- [ ] **Step 3: Implementare costanti + clean + save + _prep_evento**

In `django_app/suggestion_corner/models.py`, in testa aggiungere agli import (dopo `from django.utils import timezone`):
```python
import logging

from django.core.exceptions import ValidationError

logger = logging.getLogger("suggestion_corner")
```

Dentro la classe `SuggestionCorner`, subito dopo le altre classi annidate (`EsitoCheck`), aggiungere:
```python
    class Stato(models.TextChoices):
        INSERITA = "INSERITA", "Inserita"
        DA_CLASSIFICARE = "DA_CLASSIFICARE", "Da classificare"
        CLASSIFICATA = "CLASSIFICATA", "Classificata"
        PLAN_DEFINITO = "PLAN_DEFINITO", "Plan definito"
        DO_IN_CORSO = "DO_IN_CORSO", "Do in corso"
        DO_COMPLETATO = "DO_COMPLETATO", "Do completato"
        CHECK_IN_CORSO = "CHECK_IN_CORSO", "Check in corso"
        CHECK_COMPLETATO = "CHECK_COMPLETATO", "Check completato"
        ACT_INSERITO = "ACT_INSERITO", "Act inserito"
        CHIUSA = "CHIUSA", "Chiusa"
```

Dopo il metodo `scaduto_check` (property), aggiungere i metodi:
```python
    # --- Validazione di dominio -------------------------------------------
    def clean(self):
        super().clean()
        if (
            self.incaricato_id
            and self.controllore_id
            and self.incaricato_id == self.controllore_id
        ):
            raise ValidationError(
                {"controllore": "Il controllore deve essere diverso dall'incaricato."}
            )

    def save(self, *args, **kwargs):
        # Audit ISO 27001: logga un eventuale bypass della regola incaricato≠controllore
        if (
            self.incaricato_id
            and self.controllore_id
            and self.incaricato_id == self.controllore_id
        ):
            logger.warning(
                "SuggestionCorner#%s salvata con incaricato==controllore (id=%s): "
                "bypass regola di segregazione.",
                self.pk,
                self.incaricato_id,
            )
        super().save(*args, **kwargs)

    # --- Macchina a stati (§2) --------------------------------------------
    # Le transizioni cambiano `stato` (FSMField protected). Lo storico
    # `SuggestionCornerStorico` è creato centralmente dal signal
    # post_transition (state_machine.py); ogni transizione prepara
    # attore/payload via `_prep_evento`.

    def _prep_evento(self, attore=None, **payload):
        self._evento_attore = attore
        self._evento_payload = payload
```

- [ ] **Step 4: Eseguire i test — devono passare**

Run: `.venv\Scripts\python.exe django_app\manage.py test suggestion_corner.tests.test_fsm --settings=config.settings.test`
Expected: PASS (4 test).

- [ ] **Step 5: Verifica no-migration**

Run: `.venv\Scripts\python.exe django_app\manage.py makemigrations suggestion_corner --check --dry-run --settings=config.settings.test`
Expected: **"No changes detected"**. Se genera una migration, hai toccato lo schema (probabile `choices=` sul field o default cambiato) → correggi.

- [ ] **Step 6: Commit**

```bash
git add django_app/suggestion_corner/models.py django_app/suggestion_corner/tests/test_fsm.py
git commit -m "feat(suggestion_corner): costanti Stato + clean incaricato!=controllore + _prep_evento"
```

---

### Task 2: Signal audit → storico + wiring apps + transizioni di classificazione

**Files:**
- Create: `django_app/suggestion_corner/state_machine.py`
- Modify: `django_app/suggestion_corner/apps.py`
- Modify: `django_app/suggestion_corner/models.py`
- Modify: `django_app/suggestion_corner/tests/test_fsm.py`

**Interfaces:**
- Consumes: `SuggestionCorner._prep_evento`, `SuggestionCornerStorico`.
- Produces: signal `post_transition` → crea `SuggestionCornerStorico`; transizioni `notifica_sms_team(attore=None)`, `classifica(stato_sms, attore=None)`, `definisci_plan(incaricato, controllore, data_limite_esecuzione, data_limite_controllo, plan_testo="", attore=None)`.

- [ ] **Step 1: Scrivere il test che fallisce**

Appendere a `django_app/suggestion_corner/tests/test_fsm.py`:
```python
import datetime


class SuggestionCornerClassificazioneTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="CNC")
        self.u1 = User.objects.create(username="incaricato1")
        self.u2 = User.objects.create(username="controllore1")

    def _seg(self, **kw):
        defaults = dict(reparto_provenienza=self.reparto, opportunity="Test flusso.")
        defaults.update(kw)
        return SuggestionCorner.objects.create(**defaults)

    def test_notifica_sms_team_avanza_e_crea_storico(self):
        s = self._seg()
        self.assertEqual(s.stato, "INSERITA")
        s.notifica_sms_team()
        s.save()
        self.assertEqual(s.stato, "DA_CLASSIFICARE")
        voce = s.storico.get()
        self.assertEqual(voce.stato_precedente, "INSERITA")
        self.assertEqual(voce.stato_nuovo, "DA_CLASSIFICARE")

    def test_classifica_setta_stato_sms_e_autore(self):
        s = self._seg()
        s.notifica_sms_team()
        s.classifica(SuggestionCorner.StatoSMS.SMS_SI, attore=self.u1)
        s.save()
        self.assertEqual(s.stato, "CLASSIFICATA")
        self.assertEqual(s.stato_sms, "SMS_SI")
        voce = s.storico.filter(stato_nuovo="CLASSIFICATA").get()
        self.assertEqual(voce.autore, self.u1)

    def test_classifica_rifiuta_stato_sms_invalido(self):
        s = self._seg()
        s.notifica_sms_team()
        with self.assertRaises(ValidationError):
            s.classifica("DA_GESTIRE")

    def test_definisci_plan_enforce_incaricato_diverso(self):
        s = self._seg()
        s.notifica_sms_team()
        s.classifica(SuggestionCorner.StatoSMS.SMS_SI)
        ieri = datetime.date.today()
        with self.assertRaises(ValidationError):
            s.definisci_plan(
                incaricato=self.u1, controllore=self.u1,
                data_limite_esecuzione=ieri, data_limite_controllo=ieri,
            )

    def test_definisci_plan_ok(self):
        s = self._seg()
        s.notifica_sms_team()
        s.classifica(SuggestionCorner.StatoSMS.SMS_SI)
        d1 = datetime.date.today() + datetime.timedelta(days=10)
        d2 = datetime.date.today() + datetime.timedelta(days=20)
        s.definisci_plan(
            incaricato=self.u1, controllore=self.u2,
            data_limite_esecuzione=d1, data_limite_controllo=d2,
            plan_testo="Piano di miglioramento.",
        )
        s.save()
        self.assertEqual(s.stato, "PLAN_DEFINITO")
        self.assertTrue(s.plan_eseguito)
        self.assertEqual(s.incaricato, self.u1)
        self.assertEqual(s.controllore, self.u2)
        self.assertEqual(s.data_limite_esecuzione, d1)

    def test_uno_storico_per_transizione(self):
        s = self._seg()
        s.notifica_sms_team()
        s.classifica(SuggestionCorner.StatoSMS.SMS_NO)
        s.save()
        self.assertEqual(s.storico.count(), 2)
```

- [ ] **Step 2: Eseguire il test — deve fallire**

Run: `.venv\Scripts\python.exe django_app\manage.py test suggestion_corner.tests.test_fsm.SuggestionCornerClassificazioneTest --settings=config.settings.test`
Expected: FAIL — `AttributeError` perché `notifica_sms_team`/`classifica`/`definisci_plan` non esistono.

- [ ] **Step 3: Creare il signal audit**

`django_app/suggestion_corner/state_machine.py`:
```python
"""Audit centralizzato della macchina a stati (§2).

Collega il signal `post_transition` di django-fsm: ad ogni transizione di
`SuggestionCorner.stato` crea ESATTAMENTE una voce `SuggestionCornerStorico`,
con attore/payload preparati dalla transizione via `_prep_evento`.
"""
from __future__ import annotations

from django.dispatch import receiver
from django_fsm.signals import post_transition

from .models import SuggestionCorner, SuggestionCornerStorico


@receiver(post_transition, sender=SuggestionCorner)
def audit_post_transition(sender, instance, name, source, target, **kwargs):
    attore = getattr(instance, "_evento_attore", None)

    SuggestionCornerStorico.objects.create(
        segnalazione=instance,
        stato_precedente=source or "",
        # instance.stato è già il nuovo valore.
        stato_nuovo=instance.stato,
        autore=attore,
    )

    # reset dei transient per non sporcare transizioni successive
    instance._evento_attore = None
    instance._evento_payload = {}
```

- [ ] **Step 4: Agganciare il signal in apps.ready()**

Sostituire il contenuto di `django_app/suggestion_corner/apps.py`:
```python
from django.apps import AppConfig


class SuggestionCornerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "suggestion_corner"
    verbose_name = "Suggestion Corner"

    def ready(self):
        """Collega il signal post_transition (audit FSM) importando il
        modulo state_machine. Fail-safe."""
        try:
            from . import state_machine  # noqa: F401  (registra il signal audit)
        except Exception:
            pass
```

- [ ] **Step 5: Implementare le transizioni di classificazione**

Assicurarsi che in testa a `models.py` l'import di `transition` sia presente. Cambiare:
```python
from django_fsm import FSMField
```
in:
```python
from django_fsm import FSMField, transition
```

Dopo `_prep_evento` in `SuggestionCorner`, aggiungere:
```python
    @transition(field=stato, source=Stato.INSERITA, target=Stato.DA_CLASSIFICARE)
    def notifica_sms_team(self, attore=None):
        """INSERITA→DA_CLASSIFICARE. La mail al team SMS è sessione 5."""
        self._prep_evento(attore)

    @transition(field=stato, source=Stato.DA_CLASSIFICARE, target=Stato.CLASSIFICATA)
    def classifica(self, stato_sms, attore=None):
        """DA_CLASSIFICARE→CLASSIFICATA. Registra l'esito SMS (SI/NO)."""
        if stato_sms not in (self.StatoSMS.SMS_SI, self.StatoSMS.SMS_NO):
            raise ValidationError("stato_sms deve essere SMS_SI o SMS_NO.")
        self.stato_sms = stato_sms
        self._prep_evento(attore, stato_sms=str(stato_sms))

    @transition(field=stato, source=Stato.CLASSIFICATA, target=Stato.PLAN_DEFINITO)
    def definisci_plan(self, incaricato, controllore, data_limite_esecuzione,
                       data_limite_controllo, plan_testo="", attore=None):
        """CLASSIFICATA→PLAN_DEFINITO. incaricato≠controllore obbligatorio."""
        if incaricato is not None and incaricato == controllore:
            raise ValidationError("Il controllore deve essere diverso dall'incaricato.")
        self.incaricato = incaricato
        self.controllore = controllore
        self.data_limite_esecuzione = data_limite_esecuzione
        self.data_limite_controllo = data_limite_controllo
        self.plan_testo = plan_testo
        self.plan_eseguito = True
        self._prep_evento(attore)
```

- [ ] **Step 6: Eseguire i test — devono passare**

Run: `.venv\Scripts\python.exe django_app\manage.py test suggestion_corner.tests.test_fsm --settings=config.settings.test`
Expected: PASS (Task 1 + Task 2, 10 test).

- [ ] **Step 7: Verifica no-migration + check**

Run: `.venv\Scripts\python.exe django_app\manage.py makemigrations suggestion_corner --check --dry-run --settings=config.settings.test`
Expected: **"No changes detected"**.
Run: `.venv\Scripts\python.exe django_app\manage.py check --settings=config.settings.test`
Expected: no issues.

- [ ] **Step 8: Commit**

```bash
git add django_app/suggestion_corner/state_machine.py django_app/suggestion_corner/apps.py django_app/suggestion_corner/models.py django_app/suggestion_corner/tests/test_fsm.py
git commit -m "feat(suggestion_corner): signal audit storico + transizioni classificazione/plan"
```

---

### Task 3: Transizioni DO

**Files:**
- Modify: `django_app/suggestion_corner/models.py`
- Modify: `django_app/suggestion_corner/tests/test_fsm.py`

**Interfaces:**
- Consumes: transizioni Task 2 (per arrivare a PLAN_DEFINITO).
- Produces: `avvia_do(attore=None)`, `completa_do(esito_do, do_testo="", attore=None)`, `avvia_check(attore=None)` [cond esito_do==SI], `do_da_rifare(nuova_data_limite_esecuzione, attore=None)` [cond esito_do==NO].

- [ ] **Step 1: Scrivere il test che fallisce**

Appendere a `test_fsm.py`:
```python
class SuggestionCornerDoTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="PRESS")
        self.u1 = User.objects.create(username="doer")
        self.u2 = User.objects.create(username="checker")

    def _fino_a_do_in_corso(self):
        s = SuggestionCorner.objects.create(
            reparto_provenienza=self.reparto, opportunity="Flusso DO.",
        )
        s.notifica_sms_team()
        s.classifica(SuggestionCorner.StatoSMS.SMS_SI)
        d = datetime.date.today() + datetime.timedelta(days=10)
        s.definisci_plan(incaricato=self.u1, controllore=self.u2,
                         data_limite_esecuzione=d, data_limite_controllo=d)
        s.avvia_do()
        s.save()
        return s

    def test_avvia_do(self):
        s = self._fino_a_do_in_corso()
        self.assertEqual(s.stato, "DO_IN_CORSO")

    def test_completa_do_si_poi_avvia_check(self):
        s = self._fino_a_do_in_corso()
        s.completa_do(SuggestionCorner.EsitoAttivita.SI, do_testo="Fatto.")
        s.save()
        self.assertEqual(s.stato, "DO_COMPLETATO")
        self.assertTrue(s.do_eseguito)
        self.assertEqual(s.esito_do, "SI")
        self.assertIsNotNone(s.data_esecuzione_do)
        s.avvia_check()
        s.save()
        self.assertEqual(s.stato, "CHECK_IN_CORSO")

    def test_avvia_check_bloccato_se_esito_no(self):
        from django_fsm import TransitionNotAllowed
        s = self._fino_a_do_in_corso()
        s.completa_do(SuggestionCorner.EsitoAttivita.NO)
        s.save()
        with self.assertRaises(TransitionNotAllowed):
            s.avvia_check()

    def test_do_da_rifare_riporta_in_do_in_corso(self):
        s = self._fino_a_do_in_corso()
        s.completa_do(SuggestionCorner.EsitoAttivita.NO)
        s.save()
        nuova = datetime.date.today() + datetime.timedelta(days=30)
        s.do_da_rifare(nuova_data_limite_esecuzione=nuova)
        s.save()
        self.assertEqual(s.stato, "DO_IN_CORSO")
        self.assertFalse(s.do_eseguito)
        self.assertEqual(s.esito_do, "")
        self.assertEqual(s.data_limite_esecuzione, nuova)
```

- [ ] **Step 2: Eseguire il test — deve fallire**

Run: `.venv\Scripts\python.exe django_app\manage.py test suggestion_corner.tests.test_fsm.SuggestionCornerDoTest --settings=config.settings.test`
Expected: FAIL — metodi DO assenti.

- [ ] **Step 3: Implementare le transizioni DO**

Dopo `definisci_plan`, aggiungere:
```python
    @transition(field=stato, source=Stato.PLAN_DEFINITO, target=Stato.DO_IN_CORSO)
    def avvia_do(self, attore=None):
        """PLAN_DEFINITO→DO_IN_CORSO."""
        self._prep_evento(attore)

    @transition(field=stato, source=Stato.DO_IN_CORSO, target=Stato.DO_COMPLETATO)
    def completa_do(self, esito_do, do_testo="", attore=None):
        """DO_IN_CORSO→DO_COMPLETATO. Registra esito (SI/NO) e data. Regola
        'chi completa deve essere self.incaricato' enforced lato view (sessione 3)."""
        if esito_do not in (self.EsitoAttivita.SI, self.EsitoAttivita.NO):
            raise ValidationError("esito_do deve essere SI o NO.")
        self.do_eseguito = True
        self.data_esecuzione_do = timezone.localdate()
        self.esito_do = esito_do
        self.do_testo = do_testo
        self._prep_evento(attore, esito_do=str(esito_do))

    @transition(field=stato, source=Stato.DO_COMPLETATO, target=Stato.CHECK_IN_CORSO,
                conditions=[lambda self: self.esito_do == "SI"])
    def avvia_check(self, attore=None):
        """DO_COMPLETATO→CHECK_IN_CORSO (solo se esito_do==SI)."""
        self._prep_evento(attore)

    @transition(field=stato, source=Stato.DO_COMPLETATO, target=Stato.DO_IN_CORSO,
                conditions=[lambda self: self.esito_do == "NO"])
    def do_da_rifare(self, nuova_data_limite_esecuzione, attore=None):
        """DO_COMPLETATO→DO_IN_CORSO (solo se esito_do==NO). Nuova scadenza,
        reset dei campi DO per la riesecuzione."""
        self.data_limite_esecuzione = nuova_data_limite_esecuzione
        self.do_eseguito = False
        self.esito_do = ""
        self.data_esecuzione_do = None
        self._prep_evento(attore)
```

- [ ] **Step 4: Eseguire i test — devono passare**

Run: `.venv\Scripts\python.exe django_app\manage.py test suggestion_corner.tests.test_fsm --settings=config.settings.test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add django_app/suggestion_corner/models.py django_app/suggestion_corner/tests/test_fsm.py
git commit -m "feat(suggestion_corner): transizioni DO (avvia/completa/riesegui/avvia_check)"
```

---

### Task 4: Transizioni CHECK

**Files:**
- Modify: `django_app/suggestion_corner/models.py`
- Modify: `django_app/suggestion_corner/tests/test_fsm.py`

**Interfaces:**
- Consumes: transizioni DO (per arrivare a CHECK_IN_CORSO).
- Produces: `check_positivo(check_testo="", attore=None)`, `check_negativo(check_testo="", attore=None)`, `check_rinviato(nuova_data_limite_controllo, attore=None)`.

- [ ] **Step 1: Scrivere il test che fallisce**

Appendere a `test_fsm.py`:
```python
class SuggestionCornerCheckTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="COLL")
        self.u1 = User.objects.create(username="do2")
        self.u2 = User.objects.create(username="ck2")

    def _fino_a_check_in_corso(self):
        s = SuggestionCorner.objects.create(
            reparto_provenienza=self.reparto, opportunity="Flusso CHECK.",
        )
        s.notifica_sms_team()
        s.classifica(SuggestionCorner.StatoSMS.SMS_SI)
        d = datetime.date.today() + datetime.timedelta(days=10)
        s.definisci_plan(incaricato=self.u1, controllore=self.u2,
                         data_limite_esecuzione=d, data_limite_controllo=d)
        s.avvia_do()
        s.completa_do(SuggestionCorner.EsitoAttivita.SI)
        s.avvia_check()
        s.save()
        return s

    def test_check_positivo(self):
        s = self._fino_a_check_in_corso()
        s.check_positivo(check_testo="Verificato ok.")
        s.save()
        self.assertEqual(s.stato, "CHECK_COMPLETATO")
        self.assertEqual(s.esito_check, "POSITIVO")
        self.assertTrue(s.check_eseguito)
        self.assertIsNotNone(s.data_esecuzione_check)

    def test_check_negativo_riapre_do(self):
        s = self._fino_a_check_in_corso()
        s.check_negativo()
        s.save()
        self.assertEqual(s.stato, "DO_IN_CORSO")
        self.assertEqual(s.esito_check, "NEGATIVO")
        self.assertFalse(s.do_eseguito)
        self.assertEqual(s.esito_do, "")

    def test_check_rinviato_self_loop_nuova_data(self):
        s = self._fino_a_check_in_corso()
        nuova = datetime.date.today() + datetime.timedelta(days=45)
        s.check_rinviato(nuova_data_limite_controllo=nuova)
        s.save()
        self.assertEqual(s.stato, "CHECK_IN_CORSO")
        self.assertEqual(s.esito_check, "RINVIATO")
        self.assertEqual(s.data_limite_controllo, nuova)
```

- [ ] **Step 2: Eseguire il test — deve fallire**

Run: `.venv\Scripts\python.exe django_app\manage.py test suggestion_corner.tests.test_fsm.SuggestionCornerCheckTest --settings=config.settings.test`
Expected: FAIL — metodi CHECK assenti.

- [ ] **Step 3: Implementare le transizioni CHECK**

Dopo `do_da_rifare`, aggiungere (NB: niente `conditions`, l'esito è registrato nel corpo — vedi Global Constraints):
```python
    @transition(field=stato, source=Stato.CHECK_IN_CORSO, target=Stato.CHECK_COMPLETATO)
    def check_positivo(self, check_testo="", attore=None):
        """CHECK_IN_CORSO→CHECK_COMPLETATO. Verifica positiva."""
        self.esito_check = self.EsitoCheck.POSITIVO
        self.check_eseguito = True
        self.data_esecuzione_check = timezone.localdate()
        self.check_testo = check_testo
        self._prep_evento(attore, esito_check="POSITIVO")

    @transition(field=stato, source=Stato.CHECK_IN_CORSO, target=Stato.DO_IN_CORSO)
    def check_negativo(self, check_testo="", attore=None):
        """CHECK_IN_CORSO→DO_IN_CORSO. Verifica negativa: riapre il DO."""
        self.esito_check = self.EsitoCheck.NEGATIVO
        self.check_testo = check_testo
        # riapertura DO
        self.do_eseguito = False
        self.esito_do = ""
        self.data_esecuzione_do = None
        self.check_eseguito = False
        self._prep_evento(attore, esito_check="NEGATIVO")

    @transition(field=stato, source=Stato.CHECK_IN_CORSO, target=Stato.CHECK_IN_CORSO)
    def check_rinviato(self, nuova_data_limite_controllo, attore=None):
        """CHECK_IN_CORSO→CHECK_IN_CORSO (self-loop). Rinvio con nuova scadenza."""
        self.esito_check = self.EsitoCheck.RINVIATO
        self.data_limite_controllo = nuova_data_limite_controllo
        self._prep_evento(attore, esito_check="RINVIATO")
```

- [ ] **Step 4: Eseguire i test — devono passare**

Run: `.venv\Scripts\python.exe django_app\manage.py test suggestion_corner.tests.test_fsm --settings=config.settings.test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add django_app/suggestion_corner/models.py django_app/suggestion_corner/tests/test_fsm.py
git commit -m "feat(suggestion_corner): transizioni CHECK (positivo/negativo-riapre-DO/rinviato self-loop)"
```

---

### Task 5: Transizioni ACT + chiusura

**Files:**
- Modify: `django_app/suggestion_corner/models.py`
- Modify: `django_app/suggestion_corner/tests/test_fsm.py`

**Interfaces:**
- Consumes: transizioni CHECK (per arrivare a CHECK_COMPLETATO).
- Produces: `inserisci_act(attore=None)` [cond vuoi_inserire_act], `chiudi(attore=None)` [source CHECK_COMPLETATO o ACT_INSERITO].

- [ ] **Step 1: Scrivere il test che fallisce**

Appendere a `test_fsm.py`:
```python
class SuggestionCornerActChiusuraTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="FIN")
        self.u1 = User.objects.create(username="do3")
        self.u2 = User.objects.create(username="ck3")

    def _fino_a_check_completato(self, vuoi_act=False):
        s = SuggestionCorner.objects.create(
            reparto_provenienza=self.reparto, opportunity="Flusso ACT.",
            vuoi_inserire_act=vuoi_act,
        )
        s.notifica_sms_team()
        s.classifica(SuggestionCorner.StatoSMS.SMS_SI)
        d = datetime.date.today() + datetime.timedelta(days=10)
        s.definisci_plan(incaricato=self.u1, controllore=self.u2,
                         data_limite_esecuzione=d, data_limite_controllo=d)
        s.avvia_do()
        s.completa_do(SuggestionCorner.EsitoAttivita.SI)
        s.avvia_check()
        s.check_positivo()
        s.save()
        return s

    def test_chiudi_diretto_senza_act(self):
        s = self._fino_a_check_completato(vuoi_act=False)
        s.chiudi()
        s.save()
        self.assertEqual(s.stato, "CHIUSA")

    def test_inserisci_act_poi_chiudi(self):
        s = self._fino_a_check_completato(vuoi_act=True)
        s.inserisci_act()
        s.save()
        self.assertEqual(s.stato, "ACT_INSERITO")
        s.chiudi()
        s.save()
        self.assertEqual(s.stato, "CHIUSA")

    def test_inserisci_act_bloccato_se_non_richiesto(self):
        from django_fsm import TransitionNotAllowed
        s = self._fino_a_check_completato(vuoi_act=False)
        with self.assertRaises(TransitionNotAllowed):
            s.inserisci_act()

    def test_storico_completo_del_ciclo(self):
        s = self._fino_a_check_completato(vuoi_act=True)
        s.inserisci_act()
        s.chiudi()
        s.save()
        # notifica_sms_team, classifica, definisci_plan, avvia_do, completa_do,
        # avvia_check, check_positivo, inserisci_act, chiudi = 9 transizioni
        self.assertEqual(s.storico.count(), 9)
```

- [ ] **Step 2: Eseguire il test — deve fallire**

Run: `.venv\Scripts\python.exe django_app\manage.py test suggestion_corner.tests.test_fsm.SuggestionCornerActChiusuraTest --settings=config.settings.test`
Expected: FAIL — metodi ACT/chiudi assenti.

- [ ] **Step 3: Implementare le transizioni ACT/chiusura**

Dopo `check_rinviato`, aggiungere:
```python
    @transition(field=stato, source=Stato.CHECK_COMPLETATO, target=Stato.ACT_INSERITO,
                conditions=[lambda self: self.vuoi_inserire_act])
    def inserisci_act(self, attore=None):
        """CHECK_COMPLETATO→ACT_INSERITO (solo se vuoi_inserire_act)."""
        self.act_eseguito = True
        self._prep_evento(attore)

    @transition(field=stato, source=[Stato.CHECK_COMPLETATO, Stato.ACT_INSERITO],
                target=Stato.CHIUSA)
    def chiudi(self, attore=None):
        """{CHECK_COMPLETATO, ACT_INSERITO}→CHIUSA."""
        self._prep_evento(attore)
```

- [ ] **Step 4: Eseguire i test — devono passare**

Run: `.venv\Scripts\python.exe django_app\manage.py test suggestion_corner.tests.test_fsm --settings=config.settings.test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add django_app/suggestion_corner/models.py django_app/suggestion_corner/tests/test_fsm.py
git commit -m "feat(suggestion_corner): transizioni ACT + chiusura (source multiplo)"
```

---

### Task 6: Integrazione (ciclo completo + protected) + verifica finale + CHANGELOG

**Files:**
- Modify: `django_app/suggestion_corner/tests/test_fsm.py`
- Modify: `CHANGELOG.md` (gestito dal controller, non da subagent — vedi Global Constraints)

**Interfaces:**
- Consumes: tutte le transizioni dei Task 2–5.

- [ ] **Step 1: Scrivere il test di integrazione**

Appendere a `test_fsm.py`:
```python
class SuggestionCornerProtectedTest(TestCase):
    def test_assegnazione_diretta_stato_vietata(self):
        reparto = Reparto.objects.create(nome="PROT")
        s = SuggestionCorner.objects.create(
            reparto_provenienza=reparto, opportunity="Protected.",
        )
        with self.assertRaises(AttributeError):
            s.stato = "CHIUSA"

    def test_ciclo_do_rifatto_poi_positivo(self):
        reparto = Reparto.objects.create(nome="CICLO")
        u1 = User.objects.create(username="ck_do")
        u2 = User.objects.create(username="ck_ck")
        s = SuggestionCorner.objects.create(
            reparto_provenienza=reparto, opportunity="Ciclo con rework.",
        )
        s.notifica_sms_team()
        s.classifica(SuggestionCorner.StatoSMS.SMS_SI)
        d = datetime.date.today() + datetime.timedelta(days=10)
        s.definisci_plan(incaricato=u1, controllore=u2,
                         data_limite_esecuzione=d, data_limite_controllo=d)
        s.avvia_do()
        s.completa_do(SuggestionCorner.EsitoAttivita.NO)
        s.do_da_rifare(nuova_data_limite_esecuzione=d)
        s.completa_do(SuggestionCorner.EsitoAttivita.SI)
        s.avvia_check()
        s.check_positivo()
        s.chiudi()
        s.save()
        self.assertEqual(s.stato, "CHIUSA")
```

- [ ] **Step 2: Eseguire l'intera suite del modulo**

Run: `.venv\Scripts\python.exe django_app\manage.py test suggestion_corner --keepdb --settings=config.settings.test`
Expected: PASS su tutti i test (models + admin + fsm).

- [ ] **Step 3: Verifica no-migration + check**

Run: `.venv\Scripts\python.exe django_app\manage.py makemigrations suggestion_corner --check --dry-run --settings=config.settings.test`
Expected: **"No changes detected"**.
Run: `.venv\Scripts\python.exe django_app\manage.py check --settings=config.settings.test`
Expected: no issues.

- [ ] **Step 4: Commit del test di integrazione**

```bash
git add django_app/suggestion_corner/tests/test_fsm.py
git commit -m "test(suggestion_corner): integrazione ciclo FSM completo + protected field"
```

- [ ] **Step 5: CHANGELOG (eseguito dal controller)**

Il controller aggiunge sotto `[Unreleased] > ### Added` una voce che descrive: macchina a stati PDCA completa (12 transizioni), validazione `incaricato != controllore` (clean + audit-log bypass), signal `post_transition` → `SuggestionCornerStorico`, wiring `apps.ready()`. File: `django_app/suggestion_corner/{models,apps,state_machine}.py`, `tests/test_fsm.py`. Nessuna migration. Poi committa SOLO la propria voce con la tecnica salva-patch/revert/edit/commit/riapplica (il working tree del CHANGELOG contiene WIP di altre sessioni).

---

## Self-Review (fatto in fase di stesura)

- **Copertura BUILD_SPEC §2:** tutte le 12 transizioni presenti — notifica_sms_team (T2), classifica (T2), definisci_plan (T2), avvia_do (T3), completa_do (T3), avvia_check (T3), do_da_rifare (T3), check_positivo (T4), check_negativo (T4), check_rinviato (T4), inserisci_act (T5), chiudi (T5). ✅
- **Deviazione documentata:** transizioni CHECK senza `conditions` (esito registrato nel corpo). Motivata in Global Constraints. Le transizioni DO restano con `conditions` fedeli alla spec (esito_do pre-impostato da completa_do). ✅
- **Validazione:** `incaricato != controllore` in `clean()` (T1) + ri-controllo in `definisci_plan` (T2) + audit-log in `save()` (T1). ✅
- **Signal:** un `SuggestionCornerStorico` per transizione, testato con conteggi espliciti (T2 `test_uno_storico_per_transizione`=2, T5 `test_storico_completo_del_ciclo`=9). ✅
- **No-migration:** verifica `makemigrations --check` in T1, T2, T6. Rischio: se qualcuno aggiunge `choices=` al FSMField o cambia il default, genera una migration → i passi di verifica lo intercettano. ✅
- **Placeholder scan:** un refuso volontariamente segnalato nel test T3 Step 1 (`self.assertФ...`) con nota di correzione esplicita — l'implementatore deve scrivere `self.assertFalse(s.do_eseguito)`. Nessun altro placeholder. ✅
- **Fuori scope (sessioni successive):** enforcement "chi completa il DO deve essere self.incaricato" (view/permission, sessione 3); email (sessione 5); diff di campo nello storico oltre lo stato (sessione 7). ✅
- **Import needed:** `transition` da `django_fsm` (T2), `ValidationError` + `logging` (T1), `TransitionNotAllowed` da `django_fsm` nei test (T3/T5, import locale). ✅
