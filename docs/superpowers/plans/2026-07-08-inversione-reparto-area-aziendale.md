# Inversione gerarchia Reparto ↔ Area Aziendale — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Invertire la gerarchia tra `Reparto` e `AreaAziendale` in `anagrafica`: `Reparto` diventa il contenitore di primo livello (con `colore` e `caporeparto_legacy_id`), `AreaAziendale` diventa la sua sotto-articolazione (con FK `reparto` e `responsabile_legacy_id` opzionale), in tutta la superficie di codice che ne dipende.

**Architecture:** Migration "a taglio netto" (cancella i dati esistenti nella forma vecchia, poi altera lo schema — nessun rename di modello, solo spostamento di campi tra le due classi esistenti). Ogni consumer che accede a `rep.area_aziendale`/`.area_aziendale.nome` (che smette di esistere) viene aggiornato a leggere la nuova FK inversa `AreaAziendale.reparto` / `Reparto.aree_aziendali`. L'assegnazione Area aziendale sul dipendente resta fuori scope (Fase 2, spec).

**Tech Stack:** Django 5.2 ORM/migrations, template Django server-rendered, test `TestCase` (SQLite in `config.settings.test`).

## Global Constraints

- Spec di riferimento: `docs/superpowers/specs/2026-07-08-inversione-reparto-area-aziendale-design.md`.
- Dati esistenti in `Reparto`/`AreaAziendale`: cancellabili senza preservare valori (confermato dall'utente).
- `caporeparto_legacy_id` resta esclusivamente su `Reparto` in questa fase; `responsabile_legacy_id` su `AreaAziendale` è solo metadato (non alimenta `RepartoCapoMapping`/automazioni).
- Assegnazione dell'Area aziendale sul dipendente: NON toccare in questo piano (Fase 2, rimandata).
- Ogni task Python usa `python django_app\manage.py test anagrafica.<Label> --settings=config.settings.test --keepdb -v 2` da eseguire dalla root del repo (`C:\Dev\Portale Novicrom`) col python del venv: `.venv\Scripts\python.exe`.
- Dopo l'ultimo task: aggiornare `CHANGELOG.md` (sezione `[Unreleased]`) e `README.md` — obbligatorio per ogni modifica di codice secondo `CLAUDE.md`. Bump di versione pieno (VERSION, setup_wizard, doc multipli) esplicitamente FUORI scope di questo piano — è una decisione di rilascio separata.
- Nessuna modifica a `urls.py` (i nomi delle route restano stabili: `area_aziendale_create/edit/delete` gestiscono ora il modello figlio `AreaAziendale`, `area_create/edit/delete` gestiscono ora il modello padre `Reparto` — stesso schema URL di oggi, cambia solo cosa fanno).

---

### Task 1: Modello dati — Reparto (padre) / AreaAziendale (figlia) + migration

**Files:**
- Modify: `django_app/anagrafica/models.py:724-780`
- Create: `django_app/anagrafica/migrations/0080_reparto_area_aziendale_inversione.py`
- Test: `django_app/anagrafica/tests.py` (nuova classe `RepartoAreaAziendaleModelTests`, in fondo al file)

**Interfaces:**
- Produces: `Reparto(nome, descrizione, colore, caporeparto_legacy_id, is_active, created_at)`, nessuna FK verso l'alto. `AreaAziendale(nome, descrizione, reparto=FK→Reparto null/blank SET_NULL related_name="aree_aziendali", responsabile_legacy_id, is_active, created_at)`. Consumato da Task 2+.

- [ ] **Step 1: Scrivi il test che fallisce (nuova forma del modello)**

Apri `django_app/anagrafica/tests.py`, vai in fondo al file e aggiungi:

```python
# ---------------------------------------------------------------------------
# Inversione gerarchia Reparto (padre) / AreaAziendale (figlia)
# ---------------------------------------------------------------------------

class RepartoAreaAziendaleModelTests(TestCase):
    """Reparto e' il contenitore di primo livello; AreaAziendale la sua
    sotto-articolazione (FK verso Reparto, non viceversa)."""

    def test_reparto_ha_colore_e_caporeparto_nessun_genitore(self):
        from .models import Reparto
        rep = Reparto.objects.create(
            nome="UT", colore="#1d4ed8", caporeparto_legacy_id=401,
        )
        self.assertFalse(hasattr(rep, "area_aziendale"))
        self.assertEqual(rep.colore, "#1d4ed8")
        self.assertEqual(rep.caporeparto_legacy_id, 401)

    def test_area_aziendale_appartiene_a_un_reparto_e_ha_responsabile_opzionale(self):
        from .models import AreaAziendale, Reparto
        rep = Reparto.objects.create(nome="UT")
        area = AreaAziendale.objects.create(
            nome="IN1", reparto=rep, responsabile_legacy_id=402,
        )
        self.assertEqual(area.reparto_id, rep.pk)
        self.assertEqual(area.responsabile_legacy_id, 402)
        self.assertFalse(hasattr(area, "colore"))

    def test_un_reparto_puo_avere_piu_aree_aziendali(self):
        from .models import AreaAziendale, Reparto
        rep = Reparto.objects.create(nome="UT")
        AreaAziendale.objects.create(nome="IN1", reparto=rep)
        AreaAziendale.objects.create(nome="IN2", reparto=rep)
        self.assertEqual(rep.aree_aziendali.count(), 2)

    def test_area_aziendale_senza_reparto_ammessa(self):
        from .models import AreaAziendale
        area = AreaAziendale.objects.create(nome="ORFANA")
        self.assertIsNone(area.reparto_id)

    def test_eliminando_reparto_area_aziendale_resta_orfana(self):
        from .models import AreaAziendale, Reparto
        rep = Reparto.objects.create(nome="UT")
        area = AreaAziendale.objects.create(nome="IN1", reparto=rep)
        rep.delete()
        area.refresh_from_db()
        self.assertIsNone(area.reparto_id)
```

- [ ] **Step 2: Esegui i test per verificare che falliscano**

```powershell
.venv\Scripts\python.exe django_app\manage.py test anagrafica.tests.RepartoAreaAziendaleModelTests --settings=config.settings.test --keepdb -v 2
```

Atteso: FAIL — `AreaAziendale.objects.create(nome="IN1", reparto=rep, ...)` solleva `TypeError` (il campo `reparto` non esiste ancora su `AreaAziendale`), oppure `hasattr(rep, "area_aziendale")` è `True` (il vecchio campo esiste ancora).

- [ ] **Step 3: Riscrivi i due modelli in `models.py`**

In `django_app/anagrafica/models.py`, sostituisci le righe 724-780 (dal commento `# Aree aziendali...` fino alla fine della classe `Reparto`, `def __str__`) con:

```python
# ---------------------------------------------------------------------------
# Reparti (contenitore di primo livello: es. "UT" - Ufficio Tecnico)
# La tabella DB mantiene il nome storico ``anagrafica_areaaziendale`` per
# compatibilità con migrazioni esistenti.
# ---------------------------------------------------------------------------

class Reparto(models.Model):
    nome = models.CharField(max_length=100, unique=True)
    descrizione = models.TextField(blank=True, default="")
    colore = models.CharField(max_length=7, default="#64748b", help_text="Colore esadecimale es. #1d4ed8")
    caporeparto_legacy_id = models.IntegerField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Caporeparto",
        help_text="ID legacy del dipendente assegnato come caporeparto.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "anagrafica_areaaziendale"
        ordering = ["nome"]
        verbose_name = "Reparto"
        verbose_name_plural = "Reparti"

    def __str__(self) -> str:
        return self.nome


# ---------------------------------------------------------------------------
# Aree aziendali (sotto-articolazione di un reparto, es. "IN1", "IN2", "IT",
# "DM"). Un reparto può avere più aree aziendali; un'area aziendale
# appartiene a un solo reparto. Il "responsabile" è opzionale e distinto dal
# caporeparto: copre casi come UT, dove aree diverse (es. qualità vs
# produzione) possono avere un dirigente diverso — solo metadato in questa
# fase, non alimenta RepartoCapoMapping/automazioni.
# ---------------------------------------------------------------------------

class AreaAziendale(models.Model):
    nome = models.CharField(max_length=100, unique=True)
    descrizione = models.TextField(blank=True, default="")
    reparto = models.ForeignKey(
        Reparto,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="aree_aziendali",
        verbose_name="Reparto",
    )
    responsabile_legacy_id = models.IntegerField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Responsabile",
        help_text="ID legacy del dipendente responsabile di quest'area (opzionale, es. dirigente qualità/produzione).",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "anagrafica_area_aziendale"
        ordering = ["nome"]
        verbose_name = "Area aziendale"
        verbose_name_plural = "Aree aziendali"

    def __str__(self) -> str:
        return self.nome
```

- [ ] **Step 4: Genera e rivedi la migration**

```powershell
.venv\Scripts\python.exe django_app\manage.py makemigrations anagrafica --settings=config.settings.test
```

Aspettati che Django proponga di rinominare `AreaAziendale`→`Reparto` (interpretazione errata per somiglianza di campi): **rispondi "N"** a qualunque prompt di rename e lascia che generi `RemoveField`/`AddField` distinti. Se il comando è non-interattivo o genera comunque un file con `RenameModel`, **non usarlo**: cancella il file generato e crea a mano `django_app/anagrafica/migrations/0080_reparto_area_aziendale_inversione.py` con questo contenuto esatto:

```python
from django.db import migrations, models
import django.db.models.deletion


def cancella_dati_vecchia_gerarchia(apps, schema_editor):
    """Taglio netto: i dati esistenti sono nella forma vecchia (sbagliata,
    confermato dall'utente in sessione 2026-07-08) e vengono ricreati da UI
    con la nuova gerarchia dopo il deploy."""
    Reparto = apps.get_model("anagrafica", "Reparto")
    AreaAziendale = apps.get_model("anagrafica", "AreaAziendale")
    Reparto.objects.all().delete()
    AreaAziendale.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0079_processoqualificato_corsi_richiesti_and_more"),
    ]

    operations = [
        migrations.RunPython(cancella_dati_vecchia_gerarchia, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="reparto",
            name="area_aziendale",
        ),
        migrations.AddField(
            model_name="reparto",
            name="colore",
            field=models.CharField(default="#64748b", help_text="Colore esadecimale es. #1d4ed8", max_length=7),
        ),
        migrations.RemoveField(
            model_name="areaaziendale",
            name="colore",
        ),
        migrations.AddField(
            model_name="areaaziendale",
            name="reparto",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="aree_aziendali",
                to="anagrafica.reparto",
                verbose_name="Reparto",
            ),
        ),
        migrations.AddField(
            model_name="areaaziendale",
            name="responsabile_legacy_id",
            field=models.IntegerField(
                blank=True,
                db_index=True,
                help_text="ID legacy del dipendente responsabile di quest'area (opzionale, es. dirigente qualità/produzione).",
                null=True,
                verbose_name="Responsabile",
            ),
        ),
    ]
```

- [ ] **Step 5: Applica la migration sul DB di test/dev e verifica `makemigrations --check`**

```powershell
.venv\Scripts\python.exe django_app\manage.py migrate anagrafica --settings=config.settings.test
.venv\Scripts\python.exe django_app\manage.py makemigrations --check --settings=config.settings.test
```

Atteso: `migrate` applica `0080` senza errori; `makemigrations --check` non propone altre modifiche (schema e modello allineati).

- [ ] **Step 6: Esegui i test e verifica che passino**

```powershell
.venv\Scripts\python.exe django_app\manage.py test anagrafica.tests.RepartoAreaAziendaleModelTests --settings=config.settings.test --keepdb -v 2
```

Atteso: 5/5 PASS.

- [ ] **Step 7: Commit**

```bash
git add django_app/anagrafica/models.py django_app/anagrafica/migrations/0080_reparto_area_aziendale_inversione.py django_app/anagrafica/tests.py
git commit -m "feat(anagrafica): inverte gerarchia Reparto/AreaAziendale nel modello dati

Reparto diventa il contenitore di primo livello (colore+caporeparto),
AreaAziendale la sua sotto-articolazione (FK reparto+responsabile
opzionale). Migration a taglio netto: i dati esistenti (forma vecchia)
vengono cancellati prima di alterare lo schema."
```

---

### Task 2: CRUD "Aree & Reparti" — views.py invertito

**Files:**
- Modify: `django_app/anagrafica/views.py:5413-5634` (`_sync_aziendale_from_reparto`, `aree_list`, CRUD `area_aziendale_*`/`area_*`)
- Modify: `django_app/anagrafica/views.py:2004-2018` (`dipendente_detail`: `reparti_catalog`/`reparto_autofill_json`)
- Modify: `django_app/anagrafica/views.py:1033-1035` (`dipendente_create`: `reparti_catalogo`)
- Modify: `django_app/anagrafica/views.py:8076-8082` (`impostazioni`: blocco "Reparti")
- Test: `django_app/anagrafica/tests.py` (nuova classe `AreeRepartiCrudTests`)

**Interfaces:**
- Consumes: `Reparto`, `AreaAziendale` da Task 1 (campi `colore`/`caporeparto_legacy_id` su Reparto, `reparto`/`responsabile_legacy_id` su AreaAziendale, related_name `aree_aziendali`).
- Produces: view `aree_list` con contesto `{"reparti": [...], "aree_senza_reparto": [...], "is_admin": bool, "dipendenti_picker": [...]}` (consumato da Task 3). View `impostazioni` continua a passare `{"aree": <Reparto list>, "aree_aziendali": <AreaAziendale list>}` (nomi invariati, consumato da Task 4).

- [ ] **Step 1: Scrivi i test CRUD che falliscono**

Aggiungi in fondo a `django_app/anagrafica/tests.py`:

```python
class AreeRepartiCrudTests(TestCase):
    """CRUD di Reparto (padre) e AreaAziendale (figlia) dopo l'inversione."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="aree_crud_admin", email="aree_crud_admin@x.local", password="x"
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def test_crea_reparto_con_colore_e_caporeparto(self):
        from .models import Reparto
        resp = self.client.post(reverse("anagrafica:area_create"), {
            "nome": "UT", "descrizione": "Ufficio tecnico", "colore": "#1f87cd",
            "caporeparto_legacy_id": "401",
        })
        self.assertEqual(resp.status_code, 302)
        rep = Reparto.objects.get(nome="UT")
        self.assertEqual(rep.colore, "#1f87cd")
        self.assertEqual(rep.caporeparto_legacy_id, 401)

    def test_crea_area_aziendale_assegnata_a_reparto(self):
        from .models import AreaAziendale, Reparto
        rep = Reparto.objects.create(nome="UT")
        resp = self.client.post(reverse("anagrafica:area_aziendale_create"), {
            "nome": "IN1", "descrizione": "Ingegneria 1", "reparto_id": str(rep.pk),
            "responsabile_legacy_id": "402",
        })
        self.assertEqual(resp.status_code, 302)
        area = AreaAziendale.objects.get(nome="IN1")
        self.assertEqual(area.reparto_id, rep.pk)
        self.assertEqual(area.responsabile_legacy_id, 402)

    def test_modifica_area_aziendale_cambia_reparto(self):
        from .models import AreaAziendale, Reparto
        rep1 = Reparto.objects.create(nome="UT")
        rep2 = Reparto.objects.create(nome="MAG")
        area = AreaAziendale.objects.create(nome="IN1", reparto=rep1)
        resp = self.client.post(reverse("anagrafica:area_aziendale_edit", args=[area.pk]), {
            "nome": "IN1", "descrizione": "", "reparto_id": str(rep2.pk),
            "responsabile_legacy_id": "", "is_active": "1",
        })
        self.assertEqual(resp.status_code, 302)
        area.refresh_from_db()
        self.assertEqual(area.reparto_id, rep2.pk)

    def test_elimina_reparto_con_aree_associate_bloccata(self):
        from .models import AreaAziendale, Reparto
        rep = Reparto.objects.create(nome="UT")
        AreaAziendale.objects.create(nome="IN1", reparto=rep)
        resp = self.client.post(reverse("anagrafica:area_delete", args=[rep.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Reparto.objects.filter(pk=rep.pk).exists())

    def test_elimina_area_aziendale_non_richiede_guardia(self):
        from .models import AreaAziendale, Reparto
        rep = Reparto.objects.create(nome="UT")
        area = AreaAziendale.objects.create(nome="IN1", reparto=rep)
        resp = self.client.post(reverse("anagrafica:area_aziendale_delete", args=[area.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(AreaAziendale.objects.filter(pk=area.pk).exists())
        self.assertTrue(Reparto.objects.filter(pk=rep.pk).exists())

    def test_aree_list_mostra_reparto_come_contenitore(self):
        from .models import AreaAziendale, Reparto
        rep = Reparto.objects.create(nome="UT", colore="#1f87cd")
        AreaAziendale.objects.create(nome="IN1", reparto=rep)
        resp = self.client.get(reverse("anagrafica:aree_list"))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn("UT", content)
        self.assertIn("IN1", content)
```

- [ ] **Step 2: Esegui i test per verificare che falliscano**

```powershell
.venv\Scripts\python.exe django_app\manage.py test anagrafica.tests.AreeRepartiCrudTests --settings=config.settings.test --keepdb -v 2
```

Atteso: FAIL — `area_aziendale_create` non accetta `reparto_id`/`responsabile_legacy_id` (ancora `colore`), `area_create` non accetta `colore` (ancora `area_aziendale_id`), `area_delete` non ha la guardia su aree associate.

- [ ] **Step 3: Riscrivi `_sync_aziendale_from_reparto` e il blocco CRUD in `views.py`**

Sostituisci in `django_app/anagrafica/views.py` le righe 5413-5634 (da `def _sync_aziendale_from_reparto` fino alla fine di `area_delete`) con:

```python
def _sync_aziendale_from_reparto(legacy_id: int, reparto_nome: str, *, saved_by) -> None:
    """Aggiorna caporeparto_legacy_id su DipendenteAnagraficaAziendale in base
    al Reparto assegnato. Chiamato ogni volta che il reparto cambia.

    L'area aziendale non si autopopola più: con l'inversione della gerarchia
    un Reparto può avere più Aree aziendali figlie, quindi non è più
    derivabile in automatico da un singolo Reparto (Fase 2 nello spec).
    """
    capo_id = None
    if reparto_nome:
        rep = Reparto.objects.filter(nome__iexact=reparto_nome, is_active=True).first()
        if rep:
            capo_id = rep.caporeparto_legacy_id
    az, _ = DipendenteAnagraficaAziendale.objects.get_or_create(
        legacy_anagrafica_id=legacy_id,
        defaults={"updated_by": saved_by},
    )
    az.area = reparto_nome
    az.caporeparto_legacy_id = capo_id
    az.updated_by = saved_by
    az.save(update_fields=["area", "caporeparto_legacy_id", "updated_by", "updated_at"])


@login_required
def aree_list(request):
    legacy_user = get_legacy_user(request.user)
    is_admin = request.user.is_superuser or is_legacy_admin(legacy_user)
    reparti = list(Reparto.objects.prefetch_related("aree_aziendali").order_by("nome"))
    aree_senza_reparto = list(AreaAziendale.objects.filter(reparto__isnull=True).order_by("nome"))
    dipendenti = _dipendenti_picker_rows()
    dip_map = {item["id"]: item["label"] for item in dipendenti}
    for rep in reparti:
        rep.caporeparto_label = dip_map.get(rep.caporeparto_legacy_id or 0, "")
        for area in rep.aree_aziendali.all():
            area.responsabile_label = dip_map.get(area.responsabile_legacy_id or 0, "")
    for area in aree_senza_reparto:
        area.responsabile_label = dip_map.get(area.responsabile_legacy_id or 0, "")
    return render(request, "anagrafica/pages/aree_list.html", {
        "reparti": reparti,
        "aree_senza_reparto": aree_senza_reparto,
        "is_admin": is_admin,
        "dipendenti_picker": dipendenti,
    })


# ── Area Aziendale CRUD (ora il livello FIGLIO) ─────────────────────────────

@login_required
@require_POST
def area_aziendale_create(request):
    legacy_user = get_legacy_user(request.user)
    if not (request.user.is_superuser or is_legacy_admin(legacy_user)):
        messages.error(request, "Non hai i permessi per creare aree aziendali.")
        return _back_to_caller(request, "anagrafica:aree_list")
    nome = (request.POST.get("nome") or "").strip()[:100]
    if not nome:
        messages.error(request, "Il nome dell'area aziendale è obbligatorio.")
        return _back_to_caller(request, "anagrafica:aree_list")
    reparto_id = request.POST.get("reparto_id") or None
    reparto = None
    if reparto_id:
        try:
            reparto = Reparto.objects.get(pk=int(reparto_id))
        except (Reparto.DoesNotExist, ValueError):
            pass
    obj, created = AreaAziendale.objects.get_or_create(
        nome__iexact=nome,
        defaults={
            "nome": nome,
            "descrizione": (request.POST.get("descrizione") or "").strip(),
            "reparto": reparto,
            "responsabile_legacy_id": _resolve_caporeparto_id(request.POST.get("responsabile_legacy_id")),
        },
    )
    if created:
        messages.success(request, f'Area aziendale "{nome}" creata.')
    else:
        messages.warning(request, f'Esiste già un\'area aziendale con il nome "{nome}".')
    return _back_to_caller(request, "anagrafica:aree_list")


@login_required
@require_POST
def area_aziendale_edit(request, area_id: int):
    legacy_user = get_legacy_user(request.user)
    if not (request.user.is_superuser or is_legacy_admin(legacy_user)):
        messages.error(request, "Non hai i permessi per modificare aree aziendali.")
        return _back_to_caller(request, "anagrafica:aree_list")
    area = get_object_or_404(AreaAziendale, pk=area_id)
    nome = (request.POST.get("nome") or "").strip()[:100]
    if not nome:
        messages.error(request, "Il nome dell'area aziendale è obbligatorio.")
        return _back_to_caller(request, "anagrafica:aree_list")
    reparto_id = request.POST.get("reparto_id") or None
    reparto = None
    if reparto_id:
        try:
            reparto = Reparto.objects.get(pk=int(reparto_id))
        except (Reparto.DoesNotExist, ValueError):
            pass
    area.nome = nome
    area.descrizione = (request.POST.get("descrizione") or "").strip()
    area.reparto = reparto
    area.responsabile_legacy_id = _resolve_caporeparto_id(request.POST.get("responsabile_legacy_id"))
    area.is_active = request.POST.get("is_active") == "1"
    area.save()
    messages.success(request, f'Area aziendale "{area.nome}" aggiornata.')
    return _back_to_caller(request, "anagrafica:aree_list")


@login_required
@require_POST
def area_aziendale_delete(request, area_id: int):
    legacy_user = get_legacy_user(request.user)
    if not (request.user.is_superuser or is_legacy_admin(legacy_user)):
        messages.error(request, "Non hai i permessi per eliminare aree aziendali.")
        return _back_to_caller(request, "anagrafica:aree_list")
    area = get_object_or_404(AreaAziendale, pk=area_id)
    nome = area.nome
    area.delete()
    messages.success(request, f'Area aziendale "{nome}" eliminata.')
    return _back_to_caller(request, "anagrafica:aree_list")


# ── Reparto CRUD (ora il livello PADRE) ─────────────────────────────────────

def _sync_reparto_capo_mapping(rep) -> None:
    """Allinea RepartoCapoMapping al valore di Reparto.caporeparto_legacy_id.

    Chiamata dopo ogni create/edit di un Reparto per mantenere la tabella
    RepartoCapoMapping (usata da assenze e automazioni) in sincronia con la
    fonte di verità in Anagrafica HR.
    """
    from core.caporeparto_utils import canonical_caporeparto_value
    from core.models import RepartoCapoMapping

    reparto_nome = (rep.nome or "").strip()
    if not reparto_nome:
        return

    RepartoCapoMapping.objects.filter(reparto__iexact=reparto_nome).delete()

    if not rep.caporeparto_legacy_id:
        return

    capo_str = canonical_caporeparto_value(legacy_user_id=rep.caporeparto_legacy_id)
    if not capo_str:
        return

    RepartoCapoMapping.objects.create(
        reparto=reparto_nome,
        caporeparto=capo_str,
        is_active=True,
    )


@login_required
@require_POST
def area_create(request):
    legacy_user = get_legacy_user(request.user)
    if not (request.user.is_superuser or is_legacy_admin(legacy_user)):
        messages.error(request, "Non hai i permessi per creare reparti.")
        return _back_to_caller(request, "anagrafica:aree_list")
    nome = (request.POST.get("nome") or "").strip()[:100]
    if not nome:
        messages.error(request, "Il nome del reparto è obbligatorio.")
        return _back_to_caller(request, "anagrafica:aree_list")
    capo_id = _resolve_caporeparto_id(request.POST.get("caporeparto_legacy_id"))
    obj, created = Reparto.objects.get_or_create(
        nome__iexact=nome,
        defaults={
            "nome": nome,
            "descrizione": (request.POST.get("descrizione") or "").strip(),
            "colore": (request.POST.get("colore") or "#64748b").strip()[:7],
            "caporeparto_legacy_id": capo_id,
        },
    )
    if created:
        messages.success(request, f'Reparto "{nome}" creato.')
        _sync_reparto_capo_mapping(obj)
    else:
        messages.warning(request, f'Esiste già un reparto con il nome "{nome}".')
    return _back_to_caller(request, "anagrafica:aree_list")


@login_required
@require_POST
def area_edit(request, area_id: int):
    legacy_user = get_legacy_user(request.user)
    if not (request.user.is_superuser or is_legacy_admin(legacy_user)):
        messages.error(request, "Non hai i permessi per modificare reparti.")
        return _back_to_caller(request, "anagrafica:aree_list")
    rep = get_object_or_404(Reparto, pk=area_id)
    nome = (request.POST.get("nome") or "").strip()[:100]
    if not nome:
        messages.error(request, "Il nome del reparto è obbligatorio.")
        return _back_to_caller(request, "anagrafica:aree_list")
    rep.nome = nome
    rep.descrizione = (request.POST.get("descrizione") or "").strip()
    rep.colore = (request.POST.get("colore") or "#64748b").strip()[:7]
    rep.is_active = request.POST.get("is_active") == "1"
    rep.caporeparto_legacy_id = _resolve_caporeparto_id(request.POST.get("caporeparto_legacy_id"))
    rep.save()
    _sync_reparto_capo_mapping(rep)
    DipendenteAnagraficaAziendale.objects.filter(area__iexact=rep.nome).update(
        caporeparto_legacy_id=rep.caporeparto_legacy_id
    )
    messages.success(request, f'Reparto "{rep.nome}" aggiornato.')
    return _back_to_caller(request, "anagrafica:aree_list")


@login_required
@require_POST
def area_delete(request, area_id: int):
    legacy_user = get_legacy_user(request.user)
    if not (request.user.is_superuser or is_legacy_admin(legacy_user)):
        messages.error(request, "Non hai i permessi per eliminare reparti.")
        return _back_to_caller(request, "anagrafica:aree_list")
    rep = get_object_or_404(Reparto, pk=area_id)
    if rep.aree_aziendali.exists():
        messages.error(request, f'Impossibile eliminare: il reparto "{rep.nome}" ha aree aziendali associate. Riassegna prima le aree.')
        return _back_to_caller(request, "anagrafica:aree_list")
    nome = rep.nome
    rep.delete()
    messages.success(request, f'Reparto "{nome}" eliminato.')
    return _back_to_caller(request, "anagrafica:aree_list")
```

- [ ] **Step 4: Correggi `dipendente_detail` (righe 2004-2018)**

Sostituisci:

```python
    reparti_catalog = list(Reparto.objects.filter(is_active=True).select_related("area_aziendale").order_by("nome"))
    reparto_corrente = (dip.get("reparto") or "").strip()
    reparto_in_catalog = reparto_corrente and any(
        r.nome.strip().casefold() == reparto_corrente.casefold() for r in reparti_catalog
    )
    _dip_picker_map_detail = {item["id"]: item["label"] for item in _dipendenti_picker_rows()}
    caporeparto_label = _dip_picker_map_detail.get(aziendale.caporeparto_legacy_id, "") if aziendale and aziendale.caporeparto_legacy_id else ""
    reparto_autofill_json = json.dumps({
        r.nome: {
            "area": r.area_aziendale.nome if r.area_aziendale else "",
            "capo_label": _dip_picker_map_detail.get(r.caporeparto_legacy_id or 0, ""),
        }
        for r in reparti_catalog
    })
```

con:

```python
    reparti_catalog = list(Reparto.objects.filter(is_active=True).order_by("nome"))
    reparto_corrente = (dip.get("reparto") or "").strip()
    reparto_in_catalog = reparto_corrente and any(
        r.nome.strip().casefold() == reparto_corrente.casefold() for r in reparti_catalog
    )
    _dip_picker_map_detail = {item["id"]: item["label"] for item in _dipendenti_picker_rows()}
    caporeparto_label = _dip_picker_map_detail.get(aziendale.caporeparto_legacy_id, "") if aziendale and aziendale.caporeparto_legacy_id else ""
    reparto_autofill_json = json.dumps({
        r.nome: {
            "capo_label": _dip_picker_map_detail.get(r.caporeparto_legacy_id or 0, ""),
        }
        for r in reparti_catalog
    })
```

- [ ] **Step 5: Correggi `dipendente_create` (righe 1033-1035)**

Sostituisci:

```python
    reparti_catalogo = list(
        Reparto.objects.filter(is_active=True).select_related("area_aziendale").order_by("nome")
    )
```

con:

```python
    reparti_catalogo = list(
        Reparto.objects.filter(is_active=True).order_by("nome")
    )
```

- [ ] **Step 6: Correggi `impostazioni` (righe 8076-8082)**

Sostituisci:

```python
    # --- Reparti ---
    aree = list(Reparto.objects.select_related("area_aziendale").order_by("nome"))
    aree_aziendali = list(AreaAziendale.objects.prefetch_related("reparti").order_by("nome"))
    dipendenti_picker = _dipendenti_picker_rows()
    _dip_picker_map = {item["id"]: item["label"] for item in dipendenti_picker}
    for a in aree:
        a.caporeparto_label = _dip_picker_map.get(a.caporeparto_legacy_id or 0, "")
```

con:

```python
    # --- Reparti e Aree aziendali ---
    aree = list(Reparto.objects.prefetch_related("aree_aziendali").order_by("nome"))
    aree_aziendali = list(AreaAziendale.objects.order_by("nome"))
    dipendenti_picker = _dipendenti_picker_rows()
    _dip_picker_map = {item["id"]: item["label"] for item in dipendenti_picker}
    for a in aree:
        a.caporeparto_label = _dip_picker_map.get(a.caporeparto_legacy_id or 0, "")
    for az in aree_aziendali:
        az.responsabile_label = _dip_picker_map.get(az.responsabile_legacy_id or 0, "")
```

- [ ] **Step 7: Esegui i test e verifica che passino**

```powershell
.venv\Scripts\python.exe django_app\manage.py test anagrafica.tests.AreeRepartiCrudTests anagrafica.tests.RepartoAreaAziendaleModelTests --settings=config.settings.test --keepdb -v 2
.venv\Scripts\python.exe django_app\manage.py check --settings=config.settings.test
```

Atteso: 6/6 PASS (AreeRepartiCrudTests) + 5/5 PASS (RepartoAreaAziendaleModelTests, invariati), `check` pulito. (`aree_list.html`/`impostazioni.html` non sono ancora stati aggiornati — Task 3/4 — quindi `test_aree_list_mostra_reparto_come_contenitore` può fallire su `content` finché non sono fatti; se fallisce solo su quello specifico assert, è atteso e verrà chiuso da Task 3: annota e prosegui.)

- [ ] **Step 8: Commit**

```bash
git add django_app/anagrafica/views.py django_app/anagrafica/tests.py
git commit -m "feat(anagrafica): CRUD Aree & Reparti aggiornato alla gerarchia invertita

_sync_aziendale_from_reparto smette di derivare l'area aziendale (non
piu' univoca); area_aziendale_create/edit gestiscono ora reparto_id +
responsabile_legacy_id; area_create/edit gestiscono ora colore; guardia
di eliminazione spostata su area_delete (Reparto, ora il padre)."
```

---

### Task 3: Template `aree_list.html` — banda invertita

**Files:**
- Modify: `django_app/anagrafica/templates/anagrafica/pages/aree_list.html` (sostituzione completa)

**Interfaces:**
- Consumes: contesto da `aree_list` view (Task 2): `reparti` (Reparto con `.caporeparto_label`, `.aree_aziendali.all`), `aree_senza_reparto` (AreaAziendale con `.responsabile_label`), `is_admin`, `dipendenti_picker`.

- [ ] **Step 1: Sostituisci l'intero contenuto del file**

Sostituisci tutto `django_app/anagrafica/templates/anagrafica/pages/aree_list.html` con:

```html
{% extends "core/base.html" %}
{% load static %}

{% block title %}Aree & Reparti | Anagrafica{% endblock %}

{% block extra_head %}
{% include "anagrafica/components/_hr_restyle.html" %}
<style>
.cat-page { display:flex; flex-direction:column; gap:20px; }
.cat-topbar { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:12px; }
.cat-title { font-size:26px; font-weight:800; color:#0f172a; letter-spacing:-.02em; }
.cat-sub   { font-size:13px; color:#64748b; margin-top:2px; }
.cat-btn { display:inline-flex; align-items:center; gap:6px; padding:9px 16px; border-radius:10px; font-size:13px; font-weight:600; cursor:pointer; text-decoration:none; border:none; transition:background .15s; }
.cat-btn-primary { background:#0c2545; color:#fff; }
.cat-btn-primary:hover { background:#08142d; }
.cat-btn-ghost { background:#f1f5f9; color:#334155; border:1px solid #e2e8f0; }
.cat-btn-ghost:hover { background:#e2e8f0; }
.cat-btn-sm { padding:5px 10px; font-size:12px; border-radius:7px; }
.cat-btn-danger { background:#fef2f2; color:#dc2626; border:1px solid #fca5a5; }
.cat-btn-danger:hover { background:#fee2e2; }
.cat-card { background:#fff; border:1px solid #e2e8f0; border-radius:14px; overflow:hidden; }
.cat-card-head { display:flex; align-items:center; justify-content:space-between; padding:14px 20px; border-bottom:1px solid #f1f5f9; }
.cat-card-title { font-size:15px; font-weight:700; color:#1e293b; }
.cat-table { width:100%; border-collapse:collapse; font-size:13px; }
.cat-table th { padding:10px 16px; text-align:left; font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:.05em; color:#64748b; background:#f8fafc; border-bottom:1px solid #e2e8f0; }
.cat-table td { padding:11px 16px; border-bottom:1px solid #f8fafc; color:#334155; vertical-align:middle; }
.cat-table tr:last-child td { border-bottom:none; }
.cat-table tr:hover td { background:#f8fafc; }
.cat-pill { display:inline-block; padding:3px 9px; border-radius:999px; font-size:11px; font-weight:600; }
.cat-pill-green { background:#dcfce7; color:#166534; }
.cat-pill-gray  { background:#f1f5f9; color:#475569; }
.cat-pill-blue  { background:#dbeafe; color:#1e40af; }
.cat-pill-orange{ background:#ffedd5; color:#9a3412; }
.cat-empty { text-align:center; padding:40px; color:#94a3b8; font-size:14px; }
.cat-add-card { background:#fff; border:1px solid #e2e8f0; border-radius:14px; padding:20px; }
.cat-add-title { font-size:14px; font-weight:700; color:#1e293b; margin-bottom:14px; }
.cat-form-row { display:flex; gap:10px; flex-wrap:wrap; align-items:flex-end; }
.cat-field { display:flex; flex-direction:column; gap:4px; flex:1; min-width:180px; }
.cat-label { font-size:11px; font-weight:700; color:#64748b; text-transform:uppercase; letter-spacing:.05em; }
.cat-input { border:1px solid #e2e8f0; border-radius:8px; padding:8px 12px; font-size:13px; color:#0f172a; background:#f8fafc; outline:none; width:100%; box-sizing:border-box; }
.cat-input:focus { border-color:#1f87cd; background:#fff; }
.cat-select { border:1px solid #e2e8f0; border-radius:8px; padding:8px 12px; font-size:13px; color:#0f172a; background:#f8fafc; outline:none; width:100%; box-sizing:border-box; }
.cat-select:focus { border-color:#1f87cd; background:#fff; }

/* Reparto band — riga colorata per reparto (ora contenitore di primo livello) */
.area-band { background:#f0f7ff; border-left:4px solid var(--area-color, #1f87cd); }
.area-band td { font-weight:700; color:#0f172a; padding:10px 16px; }
.area-badge { display:inline-flex; align-items:center; gap:6px; font-size:13px; font-weight:700; }
.area-badge-dot { width:10px; height:10px; border-radius:50%; flex-shrink:0; }
.reparto-row td { padding:9px 16px 9px 32px; }
.reparto-row td:first-child { padding-left:36px; font-size:12px; color:#475569; }
.reparto-name { font-weight:600; color:#1e293b; }
.senza-area-band { background:#fff8f0; border-left:4px solid #f59e0b; }
.senza-area-band td { color:#92400e; font-size:12px; font-weight:600; }

/* Tabs (prefisso locale cat-* per non collidere con il componente pill hr-tabs di _hr_restyle) */
.cat-tabs { display:flex; gap:2px; border-bottom:2px solid #e2e8f0; margin-bottom:0; }
.cat-tab { padding:10px 18px; font-size:13px; font-weight:600; color:#64748b; cursor:pointer; border:none; background:none; border-bottom:2px solid transparent; margin-bottom:-2px; transition:color .15s,border-color .15s; }
.cat-tab.active { color:#1f87cd; border-bottom-color:#1f87cd; }
.cat-tab-panel { display:none; }
.cat-tab-panel.active { display:block; }

/* Dark */
body.theme-dark .cat-title { color:var(--text); }
body.theme-dark .cat-sub { color:var(--text-light); }
body.theme-dark .cat-btn-ghost { background:var(--surface-alt); color:var(--text-mid); border-color:var(--border); }
body.theme-dark .cat-card, body.theme-dark .cat-add-card { background:var(--surface); border-color:var(--border); }
body.theme-dark .cat-table th { background:var(--thead-bg); color:var(--text-light); border-color:var(--border); }
body.theme-dark .cat-table td { border-color:var(--border); color:var(--text-mid); }
body.theme-dark .cat-table tr:hover td { background:var(--tbody-hover); }
body.theme-dark .area-band { background:rgba(30,92,145,.12); }
body.theme-dark .area-band td { color:var(--text); }
body.theme-dark .cat-add-title { color:var(--text); }
body.theme-dark .cat-label { color:var(--text-light); }
body.theme-dark .cat-input, body.theme-dark .cat-select { background:var(--surface-alt); border-color:var(--border); color:var(--text); }
</style>
{% endblock %}

{% block subnav %}{% include "anagrafica/components/subnav.html" %}{% endblock %}

{% block content %}
<div class="cat-page">

  {% include "anagrafica/components/flash_messages.html" %}

  <div class="cat-topbar">
    <div>
      <div class="cat-title">Aree & Reparti</div>
      <div class="cat-sub">Gerarchia aziendale: reparti con le relative aree aziendali e caporeparti</div>
    </div>
    <a class="cat-btn cat-btn-ghost" href="{% url 'anagrafica:dipendenti_list' %}">&larr; Dipendenti</a>
  </div>

  <!-- ── TAB BAR ── -->
  <div class="cat-card" style="overflow:visible;">
    <div style="padding:0 20px;">
      <div class="cat-tabs">
        <button class="cat-tab active" data-tab="struttura">Struttura gerarchica</button>
        {% if is_admin %}
        <button class="cat-tab" data-tab="add-reparto">+ Reparto</button>
        <button class="cat-tab" data-tab="add-area">+ Area aziendale</button>
        {% endif %}
      </div>
    </div>

    <!-- ── TAB: Struttura ── -->
    <div class="cat-tab-panel active" data-tab-panel="struttura">
      <table class="cat-table" data-table-id="anagrafica.aree.list">
        <thead>
          <tr>
            <th data-col="nome" data-col-label="Nome" data-col-type="text" data-col-sortable="1" data-col-filterable="1" data-col-locked="1">Nome</th>
            <th data-col="descrizione" data-col-label="Descrizione" data-col-type="text" data-col-sortable="1" data-col-filterable="1">Descrizione</th>
            <th data-col="responsabile" data-col-label="Caporeparto / Responsabile" data-col-type="text" data-col-sortable="1" data-col-filterable="1">Caporeparto / Responsabile</th>
            <th data-col="stato" data-col-label="Stato" data-col-type="text" data-col-sortable="1">Stato</th>
            {% if is_admin %}<th style="width:160px;"></th>{% endif %}
          </tr>
        </thead>
        <tbody>
          {% for rep in reparti %}
          <!-- Reparto band -->
          <tr class="area-band" style="--area-color:{{ rep.colore }};">
            <td colspan="{% if is_admin %}5{% else %}4{% endif %}">
              <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;">
                <div class="area-badge">
                  <span class="area-badge-dot" style="background:{{ rep.colore }};"></span>
                  {{ rep.nome }}
                  <span style="font-size:11px;font-weight:400;color:#64748b;">({{ rep.aree_aziendali.count }} area/e)</span>
                  {% if rep.caporeparto_label %}
                    <span class="cat-pill cat-pill-blue">👤 {{ rep.caporeparto_label }}</span>
                  {% endif %}
                </div>
                {% if is_admin %}
                <div style="display:flex;gap:6px;">
                  <button class="cat-btn cat-btn-ghost cat-btn-sm"
                          data-edit-rep-id="{{ rep.pk }}"
                          data-edit-rep-nome="{{ rep.nome }}"
                          data-edit-rep-desc="{{ rep.descrizione }}"
                          data-edit-rep-colore="{{ rep.colore }}"
                          data-edit-rep-capo="{{ rep.caporeparto_legacy_id|default_if_none:'' }}"
                          data-edit-rep-active="{{ rep.is_active|yesno:'1,0' }}">
                    Modifica
                  </button>
                  <form method="post" action="{% url 'anagrafica:area_delete' rep.pk %}" style="display:inline;" onsubmit="return confirm('Eliminare il reparto «{{ rep.nome }}»? Le aree aziendali associate resteranno senza reparto.')">
                    {% csrf_token %}
                    <button type="submit" class="cat-btn cat-btn-danger cat-btn-sm">Elimina</button>
                  </form>
                </div>
                {% endif %}
              </div>
            </td>
          </tr>
          <!-- Aree aziendali di questo reparto -->
          {% for area in rep.aree_aziendali.all %}
          <tr class="reparto-row" {% if not area.is_active %}style="opacity:.6;"{% endif %}>
            <td>
              <span class="reparto-name">↳ {{ area.nome }}</span>
            </td>
            <td style="color:#64748b;">{{ area.descrizione|default:"—" }}</td>
            <td>
              {% if area.responsabile_label %}
                <span class="cat-pill cat-pill-blue">{{ area.responsabile_label }}</span>
              {% else %}
                <span style="color:#94a3b8;">—</span>
              {% endif %}
            </td>
            <td>
              {% if area.is_active %}
                <span class="cat-pill cat-pill-green">Attivo</span>
              {% else %}
                <span class="cat-pill cat-pill-gray">Inattivo</span>
              {% endif %}
            </td>
            {% if is_admin %}
            <td>
              <div style="display:flex;gap:6px;flex-wrap:wrap;">
                <button class="cat-btn cat-btn-ghost cat-btn-sm"
                        data-edit-area-id="{{ area.pk }}"
                        data-edit-area-nome="{{ area.nome }}"
                        data-edit-area-desc="{{ area.descrizione }}"
                        data-edit-area-responsabile="{{ area.responsabile_legacy_id|default_if_none:'' }}"
                        data-edit-area-reparto="{{ rep.pk }}"
                        data-edit-area-active="{{ area.is_active|yesno:'1,0' }}">
                  Modifica
                </button>
                <form method="post" action="{% url 'anagrafica:area_aziendale_delete' area.pk %}" style="display:inline;" onsubmit="return confirm('Eliminare l\'area «{{ area.nome }}»?')">
                  {% csrf_token %}
                  <button type="submit" class="cat-btn cat-btn-danger cat-btn-sm">Elimina</button>
                </form>
              </div>
            </td>
            {% endif %}
          </tr>
          {% empty %}
          <tr class="reparto-row">
            <td colspan="{% if is_admin %}5{% else %}4{% endif %}" style="padding-left:36px;color:#94a3b8;font-size:12px;font-style:italic;">
              Nessuna area aziendale in questo reparto. Crea un'area e associala qui.
            </td>
          </tr>
          {% endfor %}
          {% empty %}
          <tr><td colspan="{% if is_admin %}5{% else %}4{% endif %}" class="cat-empty">Nessun reparto creato. Usa il tab "＋ Reparto" per aggiungerne uno.</td></tr>
          {% endfor %}

          {% if aree_senza_reparto %}
          <!-- Aree aziendali non assegnate ad alcun reparto -->
          <tr class="senza-area-band">
            <td colspan="{% if is_admin %}5{% else %}4{% endif %}">
              <span>⚠ Aree aziendali senza reparto ({{ aree_senza_reparto|length }})</span>
            </td>
          </tr>
          {% for area in aree_senza_reparto %}
          <tr class="reparto-row" {% if not area.is_active %}style="opacity:.6;"{% endif %}>
            <td><span class="reparto-name">↳ {{ area.nome }}</span></td>
            <td style="color:#64748b;">{{ area.descrizione|default:"—" }}</td>
            <td>
              {% if area.responsabile_label %}
                <span class="cat-pill cat-pill-blue">{{ area.responsabile_label }}</span>
              {% else %}
                <span style="color:#94a3b8;">—</span>
              {% endif %}
            </td>
            <td>
              {% if area.is_active %}
                <span class="cat-pill cat-pill-green">Attivo</span>
              {% else %}
                <span class="cat-pill cat-pill-gray">Inattivo</span>
              {% endif %}
            </td>
            {% if is_admin %}
            <td>
              <div style="display:flex;gap:6px;flex-wrap:wrap;">
                <button class="cat-btn cat-btn-ghost cat-btn-sm"
                        data-edit-area-id="{{ area.pk }}"
                        data-edit-area-nome="{{ area.nome }}"
                        data-edit-area-desc="{{ area.descrizione }}"
                        data-edit-area-responsabile="{{ area.responsabile_legacy_id|default_if_none:'' }}"
                        data-edit-area-reparto=""
                        data-edit-area-active="{{ area.is_active|yesno:'1,0' }}">
                  Modifica
                </button>
                <form method="post" action="{% url 'anagrafica:area_aziendale_delete' area.pk %}" style="display:inline;" onsubmit="return confirm('Eliminare l\'area «{{ area.nome }}»?')">
                  {% csrf_token %}
                  <button type="submit" class="cat-btn cat-btn-danger cat-btn-sm">Elimina</button>
                </form>
              </div>
            </td>
            {% endif %}
          </tr>
          {% endfor %}
          {% endif %}
        </tbody>
      </table>
    </div>

    {% if is_admin %}
    <!-- ── TAB: Nuovo reparto ── -->
    <div class="cat-tab-panel" data-tab-panel="add-reparto">
      <div style="padding:20px;">
        <div class="cat-add-title">Nuovo reparto</div>
        <form method="post" action="{% url 'anagrafica:area_create' %}">
          {% csrf_token %}
          <div class="cat-form-row">
            <div class="cat-field">
              <label class="cat-label">Nome <span style="color:#ef4444;">*</span></label>
              <input class="cat-input" type="text" name="nome" maxlength="100" placeholder="Es. UT, Produzione, Magazzino..." required>
            </div>
            <div class="cat-field" style="flex:2;">
              <label class="cat-label">Descrizione</label>
              <input class="cat-input" type="text" name="descrizione" placeholder="Descrizione opzionale">
            </div>
            <div class="cat-field" style="flex:0;min-width:100px;">
              <label class="cat-label">Colore</label>
              <input class="cat-input" type="color" name="colore" value="#1f87cd" style="padding:4px;height:37px;cursor:pointer;">
            </div>
            <div class="cat-field" style="flex:3;min-width:240px;">
              <label class="cat-label">Caporeparto</label>
              <select class="cat-select" name="caporeparto_legacy_id">
                <option value="">— Nessuno —</option>
                {% for dip in dipendenti_picker %}
                  <option value="{{ dip.id }}">{{ dip.label }}</option>
                {% endfor %}
              </select>
            </div>
            <div style="padding-bottom:1px;">
              <button type="submit" class="cat-btn cat-btn-primary">Crea reparto</button>
            </div>
          </div>
        </form>
      </div>
    </div>

    <!-- ── TAB: Nuova area aziendale ── -->
    <div class="cat-tab-panel" data-tab-panel="add-area">
      <div style="padding:20px;">
        <div class="cat-add-title">Nuova area aziendale</div>
        <form method="post" action="{% url 'anagrafica:area_aziendale_create' %}">
          {% csrf_token %}
          <div class="cat-form-row">
            <div class="cat-field">
              <label class="cat-label">Nome <span style="color:#ef4444;">*</span></label>
              <input class="cat-input" type="text" name="nome" maxlength="100" placeholder="Es. IN1, IN2, IT, DM..." required>
            </div>
            <div class="cat-field" style="flex:2;">
              <label class="cat-label">Descrizione</label>
              <input class="cat-input" type="text" name="descrizione" placeholder="Descrizione opzionale">
            </div>
            <div class="cat-field" style="min-width:200px;">
              <label class="cat-label">Reparto</label>
              <select class="cat-select" name="reparto_id">
                <option value="">— Nessuno —</option>
                {% for rep in reparti %}
                  <option value="{{ rep.pk }}">{{ rep.nome }}</option>
                {% endfor %}
              </select>
            </div>
            <div class="cat-field" style="flex:2;min-width:220px;">
              <label class="cat-label">Responsabile</label>
              <select class="cat-select" name="responsabile_legacy_id">
                <option value="">— Nessuno —</option>
                {% for dip in dipendenti_picker %}
                  <option value="{{ dip.id }}">{{ dip.label }}</option>
                {% endfor %}
              </select>
            </div>
            <div style="padding-bottom:1px;">
              <button type="submit" class="cat-btn cat-btn-primary">Crea area</button>
            </div>
          </div>
        </form>
      </div>
    </div>
    {% endif %}
  </div><!-- /cat-card -->

</div><!-- /cat-page -->

{% if is_admin %}
<!-- ── Modal modifica reparto ── -->
<div id="edit-rep-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:1000;align-items:center;justify-content:center;">
  <div style="background:#fff;border-radius:14px;padding:24px;min-width:380px;max-width:560px;width:90%;">
    <div style="font-size:15px;font-weight:700;color:#1e293b;margin-bottom:16px;">Modifica reparto</div>
    <form method="post" id="edit-rep-form">
      {% csrf_token %}
      <div style="display:flex;flex-direction:column;gap:12px;">
        <div class="cat-field">
          <label class="cat-label">Nome <span style="color:#ef4444;">*</span></label>
          <input class="cat-input" type="text" name="nome" id="edit-rep-nome" maxlength="100" required>
        </div>
        <div class="cat-field">
          <label class="cat-label">Descrizione</label>
          <input class="cat-input" type="text" name="descrizione" id="edit-rep-desc">
        </div>
        <div class="cat-field" style="flex:0;min-width:100px;">
          <label class="cat-label">Colore</label>
          <input class="cat-input" type="color" name="colore" id="edit-rep-colore" style="padding:4px;height:37px;cursor:pointer;">
        </div>
        <div class="cat-field">
          <label class="cat-label">Caporeparto</label>
          <select class="cat-select" name="caporeparto_legacy_id" id="edit-rep-capo">
            <option value="">— Nessuno —</option>
            {% for dip in dipendenti_picker %}
              <option value="{{ dip.id }}">{{ dip.label }}</option>
            {% endfor %}
          </select>
        </div>
        <div>
          <label style="display:flex;align-items:center;gap:8px;font-size:13px;color:#334155;cursor:pointer;">
            <input type="checkbox" name="is_active" id="edit-rep-active" value="1"> Reparto attivo
          </label>
        </div>
        <div style="display:flex;gap:8px;padding-top:4px;">
          <button type="submit" class="cat-btn cat-btn-primary">Salva</button>
          <button type="button" class="cat-btn cat-btn-ghost" onclick="closeRepEdit()">Annulla</button>
        </div>
      </div>
    </form>
  </div>
</div>

<!-- ── Modal modifica area aziendale ── -->
<div id="edit-area-modal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.4);z-index:1000;align-items:center;justify-content:center;">
  <div style="background:#fff;border-radius:14px;padding:24px;min-width:380px;max-width:500px;width:90%;">
    <div style="font-size:15px;font-weight:700;color:#1e293b;margin-bottom:16px;">Modifica area aziendale</div>
    <form method="post" id="edit-area-form">
      {% csrf_token %}
      <div style="display:flex;flex-direction:column;gap:12px;">
        <div class="cat-field">
          <label class="cat-label">Nome <span style="color:#ef4444;">*</span></label>
          <input class="cat-input" type="text" name="nome" id="edit-area-nome" maxlength="100" required>
        </div>
        <div class="cat-field">
          <label class="cat-label">Descrizione</label>
          <input class="cat-input" type="text" name="descrizione" id="edit-area-desc">
        </div>
        <div class="cat-field">
          <label class="cat-label">Reparto</label>
          <select class="cat-select" name="reparto_id" id="edit-area-reparto">
            <option value="">— Nessuno —</option>
            {% for rep in reparti %}
              <option value="{{ rep.pk }}">{{ rep.nome }}</option>
            {% endfor %}
          </select>
        </div>
        <div class="cat-field">
          <label class="cat-label">Responsabile</label>
          <select class="cat-select" name="responsabile_legacy_id" id="edit-area-responsabile">
            <option value="">— Nessuno —</option>
            {% for dip in dipendenti_picker %}
              <option value="{{ dip.id }}">{{ dip.label }}</option>
            {% endfor %}
          </select>
        </div>
        <div>
          <label style="display:flex;align-items:center;gap:8px;font-size:13px;color:#334155;cursor:pointer;">
            <input type="checkbox" name="is_active" id="edit-area-active" value="1"> Area attiva
          </label>
        </div>
        <div style="display:flex;gap:8px;padding-top:4px;">
          <button type="submit" class="cat-btn cat-btn-primary">Salva</button>
          <button type="button" class="cat-btn cat-btn-ghost" onclick="closeAreaEdit()">Annulla</button>
        </div>
      </div>
    </form>
  </div>
</div>

<script>
(function() {
  // ── Tab navigation ──
  document.querySelectorAll('.cat-tab').forEach(function(tab) {
    tab.addEventListener('click', function() {
      var key = tab.getAttribute('data-tab');
      document.querySelectorAll('.cat-tab').forEach(function(t) { t.classList.remove('active'); });
      document.querySelectorAll('.cat-tab-panel').forEach(function(p) { p.classList.remove('active'); });
      tab.classList.add('active');
      var panel = document.querySelector('[data-tab-panel="' + key + '"]');
      if (panel) panel.classList.add('active');
    });
  });

  // ── Modal reparto ──
  var repEditBase = "{% url 'anagrafica:area_edit' 0 %}";
  window.closeRepEdit = function() {
    document.getElementById('edit-rep-modal').style.display = 'none';
  };
  document.querySelectorAll('[data-edit-rep-id]').forEach(function(btn) {
    btn.addEventListener('click', function() {
      var id = btn.getAttribute('data-edit-rep-id');
      document.getElementById('edit-rep-form').action = repEditBase.replace('/0/', '/' + id + '/');
      document.getElementById('edit-rep-nome').value = btn.getAttribute('data-edit-rep-nome') || '';
      document.getElementById('edit-rep-desc').value = btn.getAttribute('data-edit-rep-desc') || '';
      document.getElementById('edit-rep-colore').value = btn.getAttribute('data-edit-rep-colore') || '#64748b';
      document.getElementById('edit-rep-capo').value = btn.getAttribute('data-edit-rep-capo') || '';
      document.getElementById('edit-rep-active').checked = btn.getAttribute('data-edit-rep-active') === '1';
      document.getElementById('edit-rep-modal').style.display = 'flex';
    });
  });
  document.getElementById('edit-rep-modal').addEventListener('click', function(e) {
    if (e.target === this) closeRepEdit();
  });

  // ── Modal area aziendale ──
  var areaEditBase = "{% url 'anagrafica:area_aziendale_edit' 0 %}";
  window.closeAreaEdit = function() {
    document.getElementById('edit-area-modal').style.display = 'none';
  };
  document.querySelectorAll('[data-edit-area-id]').forEach(function(btn) {
    btn.addEventListener('click', function() {
      var id = btn.getAttribute('data-edit-area-id');
      document.getElementById('edit-area-form').action = areaEditBase.replace('/0/', '/' + id + '/');
      document.getElementById('edit-area-nome').value = btn.getAttribute('data-edit-area-nome') || '';
      document.getElementById('edit-area-desc').value = btn.getAttribute('data-edit-area-desc') || '';
      document.getElementById('edit-area-reparto').value = btn.getAttribute('data-edit-area-reparto') || '';
      document.getElementById('edit-area-responsabile').value = btn.getAttribute('data-edit-area-responsabile') || '';
      document.getElementById('edit-area-active').checked = btn.getAttribute('data-edit-area-active') === '1';
      document.getElementById('edit-area-modal').style.display = 'flex';
    });
  });
  document.getElementById('edit-area-modal').addEventListener('click', function(e) {
    if (e.target === this) closeAreaEdit();
  });
})();
</script>
{% endif %}
{% endblock %}

{% block extra_scripts %}
{# Tabella agganciata automaticamente da fm-table-enhanced.js (caricato in base.html). #}
{% endblock %}
```

- [ ] **Step 2: Esegui il test dedicato (scritto in Task 2) e verifica che passi**

```powershell
.venv\Scripts\python.exe django_app\manage.py test anagrafica.tests.AreeRepartiCrudTests.test_aree_list_mostra_reparto_come_contenitore --settings=config.settings.test --keepdb -v 2
```

Atteso: PASS (era l'unico assert rimasto in sospeso dal Task 2).

- [ ] **Step 3: Smoke-test manuale in locale**

```powershell
.venv\Scripts\python.exe django_app\manage.py runserver --settings=config.settings.dev
```

Apri `http://127.0.0.1:8000/anagrafica/aree/`, crea un Reparto "UT" con colore, poi un'Area aziendale "IN1" assegnata a "UT" dal tab "+ Area aziendale": verifica che compaia annidata sotto la banda "UT" con colore corretto, e che "Modifica"/"Elimina" funzionino su entrambi i livelli.

- [ ] **Step 4: Commit**

```bash
git add django_app/anagrafica/templates/anagrafica/pages/aree_list.html
git commit -m "feat(anagrafica): redesign Aree & Reparti — banda Reparto invertita

Reparto è ora la banda superiore (colore+caporeparto), le Aree
aziendali sono annidate sotto con eventuale responsabile."
```

---

### Task 4: Template `impostazioni.html` — tab Reparti/Aree aziendali + Capireparto

**Files:**
- Modify: `django_app/anagrafica/templates/anagrafica/pages/impostazioni.html:380-475` (tab "AREE AZIENDALI")
- Modify: `django_app/anagrafica/templates/anagrafica/pages/impostazioni.html:477-612` (tab "REPARTI")
- Modify: `django_app/anagrafica/templates/anagrafica/pages/impostazioni.html:642-665` (blocco "Capireparto designati")

**Interfaces:**
- Consumes: contesto da `impostazioni` view (Task 2): `aree` (Reparto list, `.caporeparto_label`, `.aree_aziendali.count`), `aree_aziendali` (AreaAziendale list, `.reparto`, `.responsabile_label`), `dipendenti_picker`.

- [ ] **Step 1: Sostituisci il blocco "AREE AZIENDALI" (righe 380-475)**

Trova in `django_app/anagrafica/templates/anagrafica/pages/impostazioni.html` il blocco che inizia con `<!-- ============= AREE AZIENDALI ============= -->` (riga 380) e finisce con `</section>` (riga 475, subito prima di `<!-- ============= REPARTI ============= -->`). Sostituiscilo con:

```html
      <!-- ============= AREE AZIENDALI ============= -->
      <section class="imp-panel" data-panel="aree-aziendali" id="tab-aree-aziendali">
        <div class="imp-card">
          <div class="imp-card-head">
            <div>
              <div class="imp-card-title">Aree aziendali</div>
              <div class="imp-card-sub">Sotto-articolazioni di un reparto (es. IN1, IN2, IT, DM)</div>
            </div>
          </div>
          {% if is_admin %}
          <form method="post" action="{% url 'anagrafica:area_aziendale_create' %}" class="imp-add-form">
            {% csrf_token %}
            <input type="hidden" name="next_tab" value="aree-aziendali">
            <div class="imp-field" style="flex:2 1 220px;">
              <label class="imp-label">Nome *</label>
              <input class="imp-input" type="text" name="nome" maxlength="100" required placeholder="Es. IN1">
            </div>
            <div class="imp-field" style="flex:3 1 280px;">
              <label class="imp-label">Descrizione</label>
              <input class="imp-input" type="text" name="descrizione" placeholder="Opzionale">
            </div>
            <div class="imp-field" style="flex:2 1 200px;">
              <label class="imp-label">Reparto</label>
              <select class="imp-select" name="reparto_id">
                <option value="">— Nessuno —</option>
                {% for rep in aree %}
                  <option value="{{ rep.id }}">{{ rep.nome }}</option>
                {% endfor %}
              </select>
            </div>
            <div class="imp-field" style="flex:3 1 240px;">
              <label class="imp-label">Responsabile</label>
              <select class="imp-select" name="responsabile_legacy_id">
                <option value="">— Nessuno —</option>
                {% for dip in dipendenti_picker %}
                  <option value="{{ dip.id }}">{{ dip.label }}</option>
                {% endfor %}
              </select>
            </div>
            <div class="imp-field">
              <button class="imp-btn imp-btn-green" type="submit">+ Aggiungi</button>
            </div>
          </form>
          {% endif %}
        </div>

        <div class="imp-card">
          <div class="imp-list">
            {% for az in aree_aziendali %}
              <div class="imp-row {% if not az.is_active %}inactive{% endif %}">
                <div class="imp-row-main">
                  <div class="imp-row-name">{{ az.nome }}</div>
                  {% if az.descrizione %}<div class="imp-row-meta">{{ az.descrizione }}</div>{% endif %}
                  <div class="imp-row-meta">
                    {% if az.reparto %}
                      <span class="imp-badge imp-badge-blue" style="margin-right:4px;">🏭 {{ az.reparto.nome }}</span>
                    {% else %}
                      <span style="color:#f59e0b;font-size:11px;margin-right:6px;">Nessun reparto</span>
                    {% endif %}
                    {% if az.responsabile_label %}
                      <span class="imp-badge" style="background:#dbeafe;color:#1e40af;">👤 {{ az.responsabile_label }}</span>
                    {% else %}
                      <span style="color:#94a3b8;font-size:12px;">responsabile non assegnato</span>
                    {% endif %}
                  </div>
                  {% if not az.is_active %}<span class="imp-badge imp-badge-gray">disattiva</span>{% endif %}
                </div>
                {% if is_admin %}
                <div class="imp-row-actions">
                  <button type="button" class="imp-btn imp-btn-ghost imp-btn-sm" data-modal="area-az-edit-{{ az.id }}">Modifica</button>
                  <form method="post" action="{% url 'anagrafica:area_aziendale_delete' az.id %}" style="display:inline;"
                        onsubmit="return confirm('Eliminare l\'area &quot;{{ az.nome|escapejs }}&quot;?');">
                    {% csrf_token %}
                    <input type="hidden" name="next_tab" value="aree-aziendali">
                    <button class="imp-btn imp-btn-danger imp-btn-sm" type="submit">Elimina</button>
                  </form>
                </div>
                {% endif %}
              </div>
              {% if is_admin %}
              <div class="imp-modal-overlay" id="modal-area-az-edit-{{ az.id }}">
                <div class="imp-modal">
                  <button class="imp-modal-close" type="button" data-close-modal>×</button>
                  <div class="imp-modal-title">Modifica area aziendale</div>
                  <form method="post" action="{% url 'anagrafica:area_aziendale_edit' az.id %}">
                    {% csrf_token %}
                    <input type="hidden" name="next_tab" value="aree-aziendali">
                    <div class="imp-modal-body">
                      <div class="imp-field">
                        <label class="imp-label">Nome *</label>
                        <input class="imp-input" type="text" name="nome" maxlength="100" required value="{{ az.nome }}">
                      </div>
                      <div class="imp-field">
                        <label class="imp-label">Descrizione</label>
                        <textarea class="imp-textarea" name="descrizione">{{ az.descrizione }}</textarea>
                      </div>
                      <div class="imp-field">
                        <label class="imp-label">Reparto</label>
                        <select class="imp-select" name="reparto_id">
                          <option value="">— Nessuno —</option>
                          {% for rep in aree %}
                            <option value="{{ rep.id }}" {% if az.reparto_id == rep.id %}selected{% endif %}>{{ rep.nome }}</option>
                          {% endfor %}
                        </select>
                      </div>
                      <div class="imp-field">
                        <label class="imp-label">Responsabile</label>
                        <select class="imp-select" name="responsabile_legacy_id">
                          <option value="">— Nessuno —</option>
                          {% for dip in dipendenti_picker %}
                            <option value="{{ dip.id }}" {% if az.responsabile_legacy_id == dip.id %}selected{% endif %}>{{ dip.label }}</option>
                          {% endfor %}
                        </select>
                      </div>
                      <div class="imp-field">
                        <label class="imp-label" style="display:flex;align-items:center;gap:6px;">
                          <input type="checkbox" name="is_active" value="1" {% if az.is_active %}checked{% endif %}>
                          Attiva
                        </label>
                      </div>
                    </div>
                    <div class="imp-modal-footer">
                      <button type="button" class="imp-btn imp-btn-ghost" data-close-modal>Annulla</button>
                      <button type="submit" class="imp-btn imp-btn-primary">Salva</button>
                    </div>
                  </form>
                </div>
              </div>
              {% endif %}
            {% empty %}
              <div class="imp-empty">Nessuna area aziendale registrata.</div>
            {% endfor %}
          </div>
        </div>
      </section>
```

- [ ] **Step 2: Sostituisci il blocco "REPARTI" (righe 477-612 dell'originale)**

Subito dopo la `</section>` appena inserita, trova il blocco che inizia con `<!-- ============= REPARTI ============= -->` e finisce con `</section>` (prima di `<!-- ============= RUOLI AZIENDALI ============= -->`). Sostituiscilo con:

```html
      <!-- ============= REPARTI ============= -->
      <section class="imp-panel" data-panel="aree" id="tab-aree">
        <div class="imp-card">
          <div class="imp-card-head">
            <div>
              <div class="imp-card-title">Reparti</div>
              <div class="imp-card-sub">Contenitori di primo livello, con caporeparto assegnato (selezionato dalla lista dipendenti)</div>
            </div>
            <a class="imp-btn imp-btn-ghost imp-btn-sm" href="{% url 'anagrafica:organigramma' %}">Organigramma →</a>
          </div>
          {% if is_admin %}
          <form method="post" action="{% url 'anagrafica:area_create' %}" class="imp-add-form">
            {% csrf_token %}
            <input type="hidden" name="next_tab" value="aree">
            <div class="imp-field" style="flex:2 1 220px;">
              <label class="imp-label">Nome *</label>
              <input class="imp-input" type="text" name="nome" maxlength="100" required placeholder="Es. UT">
            </div>
            <div class="imp-field" style="flex:3 1 280px;">
              <label class="imp-label">Descrizione</label>
              <input class="imp-input" type="text" name="descrizione" placeholder="Opzionale">
            </div>
            <div class="imp-field" style="flex:0 1 100px;">
              <label class="imp-label">Colore</label>
              <input class="imp-color" type="color" name="colore" value="#64748b">
            </div>
            <div class="imp-field" style="flex:3 1 240px;">
              <label class="imp-label">Caporeparto</label>
              <select class="imp-select" name="caporeparto_legacy_id">
                <option value="">— Nessuno —</option>
                {% for dip in dipendenti_picker %}
                  <option value="{{ dip.id }}">{{ dip.label }}</option>
                {% endfor %}
              </select>
            </div>
            <div class="imp-field">
              <button class="imp-btn imp-btn-green" type="submit">+ Aggiungi</button>
            </div>
          </form>
          {% endif %}
        </div>

        <div class="imp-card">
          <div class="imp-list">
            {% for a in aree %}
              <div class="imp-row {% if not a.is_active %}inactive{% endif %}">
                <span class="imp-dot" style="background:{{ a.colore|default:'#64748b' }};"></span>
                <div class="imp-row-main">
                  <div class="imp-row-name">{{ a.nome }}</div>
                  {% if a.descrizione %}<div class="imp-row-meta">{{ a.descrizione }}</div>{% endif %}
                  <div class="imp-row-meta">
                    {{ a.aree_aziendali.count }} area/e aziendal{{ a.aree_aziendali.count|pluralize:"e,i" }}
                    {% if a.caporeparto_label %}
                      · <span class="imp-badge" style="background:#dbeafe;color:#1e40af;">👤 {{ a.caporeparto_label }}</span>
                    {% else %}
                      · <span style="color:#94a3b8;font-size:12px;">caporeparto non assegnato</span>
                    {% endif %}
                  </div>
                  {% if not a.is_active %}<span class="imp-badge imp-badge-gray">disattivo</span>{% endif %}
                </div>
                {% if is_admin %}
                <div class="imp-row-actions">
                  <button type="button" class="imp-btn imp-btn-ghost imp-btn-sm" data-modal="area-edit-{{ a.id }}">Modifica</button>
                  <form method="post" action="{% url 'anagrafica:area_delete' a.id %}" style="display:inline;"
                        onsubmit="return confirm('Eliminare il reparto &quot;{{ a.nome|escapejs }}&quot;?');">
                    {% csrf_token %}
                    <input type="hidden" name="next_tab" value="aree">
                    <button class="imp-btn imp-btn-danger imp-btn-sm" type="submit">Elimina</button>
                  </form>
                </div>
                {% endif %}
              </div>
              {% if is_admin %}
              <div class="imp-modal-overlay" id="modal-area-edit-{{ a.id }}">
                <div class="imp-modal">
                  <button class="imp-modal-close" type="button" data-close-modal>×</button>
                  <div class="imp-modal-title">Modifica reparto</div>
                  <form method="post" action="{% url 'anagrafica:area_edit' a.id %}">
                    {% csrf_token %}
                    <input type="hidden" name="next_tab" value="aree">
                    <div class="imp-modal-body">
                      <div class="imp-field">
                        <label class="imp-label">Nome *</label>
                        <input class="imp-input" type="text" name="nome" maxlength="100" required value="{{ a.nome }}">
                      </div>
                      <div class="imp-field">
                        <label class="imp-label">Descrizione</label>
                        <textarea class="imp-textarea" name="descrizione">{{ a.descrizione }}</textarea>
                      </div>
                      <div class="imp-field" style="flex-direction:row;align-items:center;gap:8px;">
                        <label class="imp-label" style="margin:0;">Colore</label>
                        <input class="imp-color" type="color" name="colore" value="{{ a.colore|default:'#64748b' }}">
                      </div>
                      <div class="imp-field">
                        <label class="imp-label">Caporeparto</label>
                        <select class="imp-select" name="caporeparto_legacy_id">
                          <option value="">— Nessuno —</option>
                          {% for dip in dipendenti_picker %}
                            <option value="{{ dip.id }}" {% if a.caporeparto_legacy_id == dip.id %}selected{% endif %}>{{ dip.label }}</option>
                          {% endfor %}
                        </select>
                      </div>
                      <div class="imp-field">
                        <label class="imp-label" style="display:flex;align-items:center;gap:6px;">
                          <input type="checkbox" name="is_active" value="1" {% if a.is_active %}checked{% endif %}>
                          Attivo
                        </label>
                      </div>
                    </div>
                    <div class="imp-modal-footer">
                      <button type="button" class="imp-btn imp-btn-ghost" data-close-modal>Annulla</button>
                      <button type="submit" class="imp-btn imp-btn-primary">Salva</button>
                    </div>
                  </form>
                </div>
              </div>
              {% endif %}
            {% empty %}
              <div class="imp-empty">Nessun reparto registrato.</div>
            {% endfor %}
          </div>
        </div>
      </section>
```

- [ ] **Step 3: Correggi il blocco "Capireparto designati"**

Trova (all'interno della sezione "RUOLI AZIENDALI"):

```html
          <div class="imp-list" id="capireparto-list">
            {% for rep in aree %}{% if rep.caporeparto_label %}
              <div class="imp-row">
                <div class="imp-row-main">
                  <div class="imp-row-name">{{ rep.caporeparto_label }}</div>
                  <div class="imp-row-meta">
                    Caporeparto — {{ rep.nome }}
                    {% if rep.area_aziendale %}<span style="color:#94a3b8;"> / {{ rep.area_aziendale.nome }}</span>{% endif %}
                  </div>
                </div>
                <span class="imp-badge imp-badge-blue">Caporeparto</span>
              </div>
            {% endif %}{% endfor %}
            {% if not aree %}<div class="imp-empty">Nessun reparto configurato.</div>{% endif %}
          </div>
```

sostituisci con:

```html
          <div class="imp-list" id="capireparto-list">
            {% for rep in aree %}{% if rep.caporeparto_label %}
              <div class="imp-row">
                <div class="imp-row-main">
                  <div class="imp-row-name">{{ rep.caporeparto_label }}</div>
                  <div class="imp-row-meta">Caporeparto — {{ rep.nome }}</div>
                </div>
                <span class="imp-badge imp-badge-blue">Caporeparto</span>
              </div>
            {% endif %}{% endfor %}
            {% if not aree %}<div class="imp-empty">Nessun reparto configurato.</div>{% endif %}
          </div>
```

- [ ] **Step 4: Smoke-test manuale**

```powershell
.venv\Scripts\python.exe django_app\manage.py check --settings=config.settings.test
.venv\Scripts\python.exe django_app\manage.py runserver --settings=config.settings.dev
```

Apri `http://127.0.0.1:8000/anagrafica/impostazioni/?tab=aree-aziendali` e `?tab=aree`: verifica che entrambi i tab si carichino senza errore 500 e che i form di creazione mostrino i campi corretti (Aree aziendali: Reparto+Responsabile; Reparti: Colore+Caporeparto). Verifica anche il tab "Ruoli aziendali" → sezione "Capireparto designati".

- [ ] **Step 5: Commit**

```bash
git add django_app/anagrafica/templates/anagrafica/pages/impostazioni.html
git commit -m "feat(anagrafica): impostazioni.html — tab Reparti/Aree aziendali invertiti

Seconda UI CRUD (duplicata di aree_list.html, trovata in
approfondimento) allineata alla stessa gerarchia invertita: tab Aree
aziendali ora gestisce reparto+responsabile, tab Reparti gestisce
colore+caporeparto; blocco Capireparto designati non referenzia più
Reparto.area_aziendale."
```

---

### Task 5: Organigramma — vista + template raggruppati per Reparto

**Files:**
- Modify: `django_app/anagrafica/views.py:12821-12896` (`organigramma`)
- Modify: `django_app/anagrafica/templates/anagrafica/pages/organigramma.html` (sostituzione completa)

**Interfaces:**
- Produces: contesto `{"blocchi": [{"reparto": Reparto, "capo": dict|None, "membri": [dict], "aree_aziendali": [AreaAziendale], "n_totale": int}], "non_mappati": [...], "nomi_reparti": [...], "filtro_reparto": str, "n_dipendenti": int, "n_reparti": int, "n_non_mappati": int}` (consumato dal template nello stesso task).

- [ ] **Step 1: Riscrivi la view `organigramma` (righe 12821-12896)**

Sostituisci in `django_app/anagrafica/views.py` dal commento `# Organigramma visuale...` fino alla fine della funzione `organigramma` con:

```python
# ---------------------------------------------------------------------------
# Organigramma visuale — Reparto → Aree aziendali → caporeparto → dipendenti
# ---------------------------------------------------------------------------

@login_required
def organigramma(request):
    """Organigramma navigabile SSR: reparti, aree aziendali, capi e membri.

    Gli stessi dati (nomi/reparti) sono già visibili in `dipendenti_list`,
    quindi basta il login. I disallineamenti emergono di proposito: i
    dipendenti il cui reparto legacy non corrisponde a nessun `Reparto`
    censito finiscono nel bucket "Non mappati".
    """
    ensure_anagrafica_schema()
    filtro_reparto = (request.GET.get("reparto") or "").strip()

    dip_rows = [r for r in fetch_anagrafica_rows(deduplicate=True) if r.get("attivo")]
    dip_map = {int(r["id"]): r for r in dip_rows if r.get("id")}

    reparti = list(
        Reparto.objects.filter(is_active=True)
        .prefetch_related("aree_aziendali")
        .order_by("nome")
    )
    reparto_by_name = {r.nome.strip().casefold(): r for r in reparti}

    membri_per_reparto: dict[int, list[dict]] = {}
    non_mappati: list[dict] = []
    for row in dip_rows:
        nome_rep = str(row.get("reparto") or "").strip()
        rep = reparto_by_name.get(nome_rep.casefold()) if nome_rep else None
        if rep is None:
            non_mappati.append(row)
        else:
            membri_per_reparto.setdefault(rep.id, []).append(row)

    def _sort_key(row: dict):
        return (str(row.get("cognome") or "").casefold(), str(row.get("nome") or "").casefold())

    def _blocco_reparto(rep: Reparto) -> dict:
        capo = dip_map.get(rep.caporeparto_legacy_id or 0)
        membri = sorted(membri_per_reparto.get(rep.id, []), key=_sort_key)
        if capo:
            membri = [m for m in membri if int(m.get("id") or 0) != int(capo.get("id") or 0)]
        return {
            "reparto": rep,
            "capo": capo,
            "membri": membri,
            "aree_aziendali": list(rep.aree_aziendali.filter(is_active=True).order_by("nome")),
            "n_totale": len(membri) + (1 if capo else 0),
        }

    blocchi = [_blocco_reparto(r) for r in reparti]

    nomi_reparti = [r.nome for r in reparti]
    if filtro_reparto:
        blocchi = [b for b in blocchi if b["reparto"].nome.casefold() == filtro_reparto.casefold()]

    non_mappati.sort(key=_sort_key)
    n_dipendenti = len(dip_rows)

    return render(request, "anagrafica/pages/organigramma.html", {
        "blocchi": blocchi,
        "non_mappati": non_mappati,
        "nomi_reparti": nomi_reparti,
        "filtro_reparto": filtro_reparto,
        "n_dipendenti": n_dipendenti,
        "n_reparti": len(reparti),
        "n_non_mappati": len(non_mappati),
    })
```

- [ ] **Step 2: Sostituisci l'intero contenuto di `organigramma.html`**

Sostituisci tutto `django_app/anagrafica/templates/anagrafica/pages/organigramma.html` con:

```html
{% extends "core/base.html" %}
{% load static %}

{% block title %}Organigramma | Anagrafica{% endblock %}

{% block extra_head %}
{% include "anagrafica/components/_hr_restyle.html" %}
<style>
/* ── Layout organigramma ────────────────────────────────────────────────── */
.org-grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(260px, 1fr)); gap:14px; }
.org-rep {
  border:1px solid #e2e8f0; border-radius:12px; background:#fff;
  border-top:3px solid var(--org-color, #64748b);
  overflow:hidden;
}
.org-rep-head { padding:12px 14px 8px; }
.org-rep-name { font-size:14px; font-weight:800; color:#0c2545; }
.org-rep-count { font-size:11.5px; color:#94a3b8; font-weight:600; }
.org-aree { display:flex; flex-wrap:wrap; gap:4px; margin:4px 14px 0; }
.org-area-chip { font-size:10.5px; font-weight:700; color:#1e40af; background:#dbeafe; border-radius:999px; padding:2px 8px; }
.org-capo {
  display:flex; align-items:center; gap:8px;
  margin:8px 14px 10px; padding:7px 10px;
  background:#eff6ff; border:1px solid #dbeafe; border-radius:9px;
}
.org-capo-badge { font-size:10px; font-weight:800; color:#1f87cd; text-transform:uppercase; letter-spacing:.05em; }
.org-capo a { font-size:13px; font-weight:700; color:#0c2545; text-decoration:none; }
.org-capo a:hover { text-decoration:underline; }
.org-capo-missing {
  margin:8px 14px 10px; padding:7px 10px; border-radius:9px;
  background:#fef9c3; border:1px dashed #fde047;
  font-size:11.5px; color:#854d0e; font-weight:600;
}
.org-membri { border-top:1px solid #f1f5f9; }
.org-membri summary {
  cursor:pointer; padding:8px 14px; font-size:12px; font-weight:700; color:#475569;
  list-style:none; display:flex; align-items:center; gap:6px; user-select:none;
}
.org-membri summary::-webkit-details-marker { display:none; }
.org-membri summary::before { content:"▸"; transition:transform .15s; }
.org-membri[open] summary::before { transform:rotate(90deg); }
.org-membri ul { list-style:none; margin:0; padding:0 14px 12px; }
.org-membri li { padding:4px 0; border-bottom:1px solid #f8fafc; font-size:13px; }
.org-membri li a { color:#334155; text-decoration:none; }
.org-membri li a:hover { color:#1f87cd; text-decoration:underline; }
.org-membri .org-mansione { font-size:11px; color:#94a3b8; }

.org-empty-rep { padding:8px 14px 12px; font-size:12px; color:#94a3b8; font-style:italic; }

/* Filtro reparto + bucket "non a catalogo" (niente colori inline: vincono sul dark) */
.org-filter-label { font-size:11px; font-weight:700; color:#64748b; text-transform:uppercase; letter-spacing:.05em; }
.org-select { border:1px solid #e2e8f0; border-radius:9px; padding:8px 12px; font-size:13px; background:#f8fafc; font-family:inherit; }
.org-nm-hint { font-size:12px; color:#94a3b8; }
.org-nm-link { color:#334155; text-decoration:none; }
.org-nm-link:hover { color:#1f87cd; text-decoration:underline; }
.org-nm-rep { font-size:11px; color:#b45309; }

/* ── Dark mode ──────────────────────────────────────────────────────────── */
body.theme-dark .org-filter-label { color:var(--text-light); }
body.theme-dark .org-select { background:var(--surface-alt); border-color:var(--border); color:var(--text); }
body.theme-dark .org-nm-link { color:var(--text-mid); }
body.theme-dark .org-nm-rep { color:#fbbf24; }
body.theme-dark .org-rep { background:var(--surface); border-color:var(--border); }
body.theme-dark .org-rep-name { color:var(--text); }
body.theme-dark .org-area-chip { background:rgba(29,78,216,.22); color:#bfdbfe; }
body.theme-dark .org-capo { background:rgba(29,78,216,.12); border-color:rgba(29,78,216,.3); }
body.theme-dark .org-capo a { color:var(--text); }
body.theme-dark .org-membri summary { color:var(--text-light); }
body.theme-dark .org-membri li { border-color:var(--border); }
body.theme-dark .org-membri li a { color:var(--text-light); }
body.theme-dark .org-membri { border-color:var(--border); }
body.theme-dark .org-capo-missing { background:rgba(133,77,14,.18); border-color:rgba(253,224,71,.4); color:#fde68a; }

/* ── Stampa ─────────────────────────────────────────────────────────────── */
@media print {
  .hr-pagehead a, .org-filters, .core-topnav, .core-sidebar { display:none !important; }
  .org-membri { display:block; }
  .org-membri summary { display:none; }
  .org-membri ul { padding-top:4px; }
  details:not([open]) ul { display:block !important; }
  .org-rep { break-inside:avoid; }
}
</style>
{% endblock %}

{% block subnav %}{% include "anagrafica/components/subnav.html" %}{% endblock %}

{% block content %}
<div style="display:flex;flex-direction:column;gap:20px;">

  {% include "anagrafica/components/flash_messages.html" %}

  <!-- Page header -->
  <div class="hr-pagehead">
    <div>
      <div class="hr-pagehead-eyebrow">Anagrafica HR</div>
      <h1 class="hr-pagehead-title">Organigramma</h1>
      <p class="hr-pagehead-desc">Reparti, aree aziendali, capireparto e dipendenti in forza.</p>
    </div>
    <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
      <button type="button" class="hr-btn hr-btn-outline" onclick="window.print();">🖨 Stampa</button>
      <a class="hr-btn hr-btn-ghost" href="{% url 'anagrafica:index' %}">← Dashboard</a>
    </div>
  </div>

  <!-- KPI -->
  <div class="hr-metric-grid">
    <div class="hr-metric">
      <div class="hr-metric-ico blue">👥</div>
      <div class="hr-metric-body">
        <div class="hr-metric-top"><span class="hr-metric-lbl">Dipendenti attivi</span><span class="hr-metric-val">{{ n_dipendenti }}</span></div>
        <div class="hr-metric-sub">In forza</div>
      </div>
    </div>
    <div class="hr-metric">
      <div class="hr-metric-ico blue">🏭</div>
      <div class="hr-metric-body">
        <div class="hr-metric-top"><span class="hr-metric-lbl">Reparti</span><span class="hr-metric-val">{{ n_reparti }}</span></div>
        <div class="hr-metric-sub">Attivi a catalogo</div>
      </div>
    </div>
    <div class="hr-metric">
      <div class="hr-metric-ico {% if n_non_mappati %}amber{% else %}blue{% endif %}">🧩</div>
      <div class="hr-metric-body">
        <div class="hr-metric-top"><span class="hr-metric-lbl">Non mappati</span><span class="hr-metric-val">{{ n_non_mappati }}</span></div>
        <div class="hr-metric-sub">Reparto legacy non a catalogo</div>
      </div>
    </div>
  </div>

  <!-- Filtro reparto -->
  {% if nomi_reparti %}
  <div class="hr-card org-filters">
    <form method="get" action="" style="display:flex;gap:12px;align-items:flex-end;padding:14px 16px;flex-wrap:wrap;">
      <div style="display:flex;flex-direction:column;gap:4px;min-width:200px;">
        <label for="org-reparto" class="org-filter-label">Reparto</label>
        <select id="org-reparto" name="reparto" class="sc-select org-select" onchange="this.form.submit()">
          <option value="" {% if not filtro_reparto %}selected{% endif %}>Tutti</option>
          {% for nome in nomi_reparti %}
          <option value="{{ nome }}" {% if nome == filtro_reparto %}selected{% endif %}>{{ nome }}</option>
          {% endfor %}
        </select>
      </div>
      <a href="{% url 'anagrafica:organigramma' %}" class="hr-btn hr-btn-outline hr-btn-sm">Azzera</a>
    </form>
  </div>
  {% endif %}

  <!-- Albero organigramma -->
  <div class="hr-card" style="padding:18px 20px;">
    <div class="org-grid">
      {% for b in blocchi %}
      <div class="org-rep" style="--org-color:{{ b.reparto.colore }};">
        <div class="org-rep-head">
          <div class="org-rep-name">{{ b.reparto.nome }}</div>
          <div class="org-rep-count">{{ b.n_totale }} person{{ b.n_totale|pluralize:"a,e" }}</div>
        </div>
        {% if b.aree_aziendali %}
        <div class="org-aree">
          {% for area in b.aree_aziendali %}
          <span class="org-area-chip">{{ area.nome }}</span>
          {% endfor %}
        </div>
        {% endif %}
        {% if b.capo %}
        <div class="org-capo">
          <span class="org-capo-badge">Capo</span>
          <a href="{% url 'anagrafica:dipendente_detail' b.capo.id %}">{{ b.capo.cognome }} {{ b.capo.nome }}</a>
        </div>
        {% else %}
        <div class="org-capo-missing">⚠ Caporeparto non assegnato</div>
        {% endif %}
        {% if b.membri %}
        <details class="org-membri">
          <summary>{{ b.membri|length }} collaborator{{ b.membri|length|pluralize:"e,i" }}</summary>
          <ul>
            {% for m in b.membri %}
            <li>
              <a href="{% url 'anagrafica:dipendente_detail' m.id %}">{{ m.cognome }} {{ m.nome }}</a>
              {% if m.mansione %}<span class="org-mansione"> · {{ m.mansione }}</span>{% endif %}
            </li>
            {% endfor %}
          </ul>
        </details>
        {% elif not b.capo %}
        <div class="org-empty-rep">Nessun dipendente assegnato.</div>
        {% endif %}
      </div>
      {% empty %}
      <div class="hr-empty">
        <div style="font-size:32px;margin-bottom:8px;">🏢</div>
        Nessun reparto a catalogo. Configura reparti e aree dalle <a href="{% url 'anagrafica:impostazioni' %}">impostazioni</a>.
      </div>
      {% endfor %}
    </div>
  </div>

  <!-- Bucket non mappati: visibile di proposito, fa emergere i disallineamenti -->
  {% if non_mappati and not filtro_reparto %}
  <div class="hr-card">
    <div class="hr-card-head">
      <div class="hr-card-title">🧩 Dipendenti con reparto non a catalogo</div>
      <div class="org-nm-hint">Il reparto legacy non corrisponde a nessun reparto censito nelle impostazioni.</div>
    </div>
    <ul style="list-style:none;margin:0;padding:8px 16px 14px;columns:3;column-gap:24px;">
      {% for m in non_mappati %}
      <li style="padding:3px 0;font-size:13px;break-inside:avoid;">
        <a href="{% url 'anagrafica:dipendente_detail' m.id %}" class="org-nm-link">{{ m.cognome }} {{ m.nome }}</a>
        {% if m.reparto %}<span class="org-nm-rep"> · «{{ m.reparto }}»</span>{% endif %}
      </li>
      {% endfor %}
    </ul>
  </div>
  {% endif %}

</div>
{% endblock %}
```

- [ ] **Step 3: Esegui `check` (i test organigramma sono nel Task 6, in arrivo)**

```powershell
.venv\Scripts\python.exe django_app\manage.py check --settings=config.settings.test
```

Atteso: pulito (i vecchi test `OrganigrammaTests` in `tests.py` sono ancora nella forma vecchia e falliranno finché non fai il Task 6 — atteso, non bloccante per questo step).

- [ ] **Step 4: Commit**

```bash
git add django_app/anagrafica/views.py django_app/anagrafica/templates/anagrafica/pages/organigramma.html
git commit -m "feat(anagrafica): organigramma raggruppato per Reparto invece che per Area

Il blocco reparto (con colore proprio, spostato da AreaAziendale) e' ora
il livello di raggruppamento; le aree aziendali del reparto compaiono
come badge informativi senza membri agganciati (Fase 2 rimandata)."
```

---

### Task 6: Riscrivi `OrganigrammaTests`

**Files:**
- Modify: `django_app/anagrafica/tests.py:2706-2760` (classe `OrganigrammaTests`)

**Interfaces:**
- Consumes: view `organigramma` e template da Task 5 (contesto `blocchi`, `nomi_reparti`, `filtro_reparto`).

- [ ] **Step 1: Sostituisci la classe `OrganigrammaTests`**

Sostituisci in `django_app/anagrafica/tests.py` l'intera classe `OrganigrammaTests` (dal commento `# H6 — organigramma visuale` fino alla riga vuota prima di `# H2 — fascicolo conformità`) con:

```python
# ---------------------------------------------------------------------------
# H6 — organigramma visuale
# ---------------------------------------------------------------------------

class OrganigrammaTests(TestCase):
    """Albero reparto → area aziendale (badge) → capo → membri, con bucket disallineamenti."""

    @classmethod
    def setUpTestData(cls):
        from .models import AreaAziendale, Reparto
        _ensure_anagrafica_table()
        cls.admin = User.objects.create_superuser(
            username="org_admin", email="org_admin@x.local", password="x"
        )
        cls.rep_prod = Reparto.objects.create(
            nome="PROD", colore="#1d4ed8", caporeparto_legacy_id=401
        )
        cls.area_in1 = AreaAziendale.objects.create(nome="IN1", reparto=cls.rep_prod)
        cls.area_orfana = AreaAziendale.objects.create(nome="ORFANA")  # senza reparto
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO anagrafica_dipendenti (id, nome, cognome, mansione, reparto, attivo) VALUES "
                "(401, 'Capo', 'Reparto', 'Caporeparto', 'PROD', 1), "
                "(402, 'Mario', 'Verdi', 'Operatore', 'PROD', 1), "
                "(403, 'Luigi', 'Bianchi', 'Operatore', 'INESISTENTE', 1), "
                "(404, 'Anna', 'Cessata', 'Operatore', 'PROD', 0)"
            )

    def setUp(self):
        self.client.force_login(self.admin)

    def test_albero_reparti_capo(self):
        resp = self.client.get(reverse("anagrafica:organigramma"))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn("PROD", content)
        self.assertIn("IN1", content)                     # area aziendale mostrata come badge
        self.assertIn("Reparto Capo", content)             # capo evidenziato
        self.assertIn("Verdi Mario", content)               # membro (capo escluso dai membri)

    def test_non_mappati_visibili(self):
        resp = self.client.get(reverse("anagrafica:organigramma"))
        content = resp.content.decode()
        self.assertIn("Bianchi Luigi", content)
        self.assertIn("non a catalogo", content)

    def test_cessati_esclusi(self):
        resp = self.client.get(reverse("anagrafica:organigramma"))
        self.assertNotContains(resp, "Cessata")

    def test_filtro_reparto(self):
        resp = self.client.get(reverse("anagrafica:organigramma"), {"reparto": "PROD"})
        content = resp.content.decode()
        self.assertIn("PROD", content)
```

- [ ] **Step 2: Esegui i test e verifica che passino**

```powershell
.venv\Scripts\python.exe django_app\manage.py test anagrafica.tests.OrganigrammaTests --settings=config.settings.test --keepdb -v 2
```

Atteso: 4/4 PASS.

- [ ] **Step 3: Esegui l'intera suite `anagrafica` per verificare che non ci siano regressioni**

```powershell
.venv\Scripts\python.exe django_app\manage.py test anagrafica --settings=config.settings.test --keepdb -v 1
```

Atteso: nessuna nuova failure oltre a quella pre-esistente e non correlata `FormazioneFlussoTests.test_corso_form_categoria_e_qualifica` (`quiz_punteggio_minimo`, nota nella memoria di progetto). Se emergono altre failure in `models_formazione`/`models_rischi`/`gestione_specifiche` legate a `AreaAziendale`/`Reparto`, annotale: sono conseguenza attesa del taglio netto sui dati (righe che puntavano a record cancellati) — non richiedono fix di codice in questo piano, sono coperte da "Effetti collaterali noti" nello spec.

- [ ] **Step 4: Commit**

```bash
git add django_app/anagrafica/tests.py
git commit -m "test(anagrafica): riscrive OrganigrammaTests per la gerarchia invertita

Reparto e' ora il livello padre (colore+caporeparto in setUpTestData);
AreaAziendale compare come badge informativo nel blocco reparto; il
filtro passa da area a reparto, sparisce il bucket 'Senza area'."
```

---

### Task 7: Template `dipendente_detail.html`

**Files:**
- Modify: `django_app/anagrafica/templates/anagrafica/pages/dipendente_detail.html:850` (dropdown reparto)
- Modify: `django_app/anagrafica/templates/anagrafica/pages/dipendente_detail.html:894-899` (caption area aziendale)
- Modify: `django_app/anagrafica/templates/anagrafica/pages/dipendente_detail.html:955-959` (caption autofill area)
- Modify: `django_app/anagrafica/templates/anagrafica/pages/dipendente_detail.html:2698-2712` (JS autofill)

**Interfaces:**
- Consumes: `reparti_catalog`, `reparto_autofill_json` da Task 2 (Step 4): `reparto_autofill_json` non contiene più la chiave `"area"`, solo `"capo_label"`.

- [ ] **Step 1: Correggi la select del reparto (riga 850)**

Sostituisci:

```html
                  <option value="{{ rep.nome }}" {% if rep.nome == dip.reparto %}selected{% endif %}>
                    {{ rep.nome }}{% if rep.area_aziendale %} · {{ rep.area_aziendale.nome }}{% endif %}
                  </option>
```

con:

```html
                  <option value="{{ rep.nome }}" {% if rep.nome == dip.reparto %}selected{% endif %}>
                    {{ rep.nome }}
                  </option>
```

- [ ] **Step 2: Correggi la caption "Area aziendale" (righe 894-899)**

Sostituisci:

```html
            {% if aziendale.area_aziendale_nome %}
              {{ aziendale.area_aziendale_nome }}
            {% else %}
              <span style="color:#94a3b8;font-size:12px;">Auto dal reparto</span>
            {% endif %}
```

con:

```html
            {% if aziendale.area_aziendale_nome %}
              {{ aziendale.area_aziendale_nome }}
            {% else %}
              <span style="color:#94a3b8;font-size:12px;">Non assegnata</span>
            {% endif %}
```

- [ ] **Step 3: Correggi la caption del campo autofill (righe 955-959)**

Sostituisci:

```html
            <div class="dp-form-field">
              <label class="dp-form-label">Area aziendale</label>
              <input type="text" id="az-area-autofill" class="dp-input" readonly style="background:#f8fafc;color:#64748b;cursor:default;" value="{{ aziendale.area_aziendale_nome|default:'' }}">
              <span style="font-size:11px;color:#94a3b8;">Compilata automaticamente dal reparto</span>
            </div>
```

con:

```html
            <div class="dp-form-field">
              <label class="dp-form-label">Area aziendale</label>
              <input type="text" id="az-area-autofill" class="dp-input" readonly style="background:#f8fafc;color:#64748b;cursor:default;" value="{{ aziendale.area_aziendale_nome|default:'' }}">
              <span style="font-size:11px;color:#94a3b8;">Non assegnata automaticamente in questa fase</span>
            </div>
```

- [ ] **Step 4: Correggi il JS di autofill (righe 2698-2712)**

Sostituisci:

```javascript
// Auto-fill area aziendale e caporeparto quando si seleziona il reparto
(function() {
  var repartiData = {{ reparto_autofill_json|safe }};
  var sel = document.getElementById('id_area');
  if (!sel) return;
  function fill() {
    var d = repartiData[sel.value] || {};
    var areaEl = document.getElementById('az-area-autofill');
    var capoEl = document.getElementById('az-capo-autofill');
    if (areaEl) areaEl.value = d.area || '';
    if (capoEl) capoEl.value = d.capo_label || '';
  }
  sel.addEventListener('change', fill);
  fill();
})();
```

con:

```javascript
// Auto-fill caporeparto quando si seleziona il reparto (l'area aziendale non
// si autopopola più: un reparto può avere più aree aziendali figlie).
(function() {
  var repartiData = {{ reparto_autofill_json|safe }};
  var sel = document.getElementById('id_area');
  if (!sel) return;
  function fill() {
    var d = repartiData[sel.value] || {};
    var capoEl = document.getElementById('az-capo-autofill');
    if (capoEl) capoEl.value = d.capo_label || '';
  }
  sel.addEventListener('change', fill);
  fill();
})();
```

- [ ] **Step 5: Smoke-test manuale**

```powershell
.venv\Scripts\python.exe django_app\manage.py check --settings=config.settings.test
```

Apri la scheda di un dipendente esistente (`/anagrafica/dipendenti/<id>/`) in dev: verifica che la sezione "Reparto"/"Area aziendale"/"Caporeparto" si carichi senza errore, che cambiare il reparto nel form "Modifica dati aziendali" aggiorni solo il campo Caporeparto (l'Area aziendale resta vuota/"Non assegnata"), e che il dropdown di modifica reparto (matita accanto a "Reparto") non mostri più suffissi area.

- [ ] **Step 6: Commit**

```bash
git add django_app/anagrafica/templates/anagrafica/pages/dipendente_detail.html
git commit -m "fix(anagrafica): dipendente_detail.html — rimuove riferimenti a Reparto.area_aziendale

rep.area_aziendale non esiste più dopo l'inversione; l'autofill JS
smette di popolare l'area (non più derivabile da un reparto singolo),
le caption vengono aggiornate di conseguenza."
```

---

### Task 8: Template `dipendente_create.html`

**Files:**
- Modify: `django_app/anagrafica/templates/anagrafica/pages/dipendente_create.html:164-170`
- Modify: `django_app/anagrafica/templates/anagrafica/pages/dipendente_create.html:228`

**Interfaces:**
- Consumes: `reparti_catalogo` da Task 2 (Step 5).

- [ ] **Step 1: Correggi la select del reparto e la caption (righe 164-171)**

Sostituisci:

```html
                {% for rep in reparti_catalogo %}
                  <option value="{{ rep.nome }}" {% if legacy_form.reparto.value == rep.nome %}selected{% endif %}>
                    {{ rep.nome }}{% if rep.area_aziendale %} · {{ rep.area_aziendale.nome }}{% endif %}
                  </option>
                {% endfor %}
              </select>
              <span style="font-size:11px;color:#94a3b8;">Area aziendale e caporeparto vengono assegnati automaticamente dal catalogo reparti.</span>
```

con:

```html
                {% for rep in reparti_catalogo %}
                  <option value="{{ rep.nome }}" {% if legacy_form.reparto.value == rep.nome %}selected{% endif %}>
                    {{ rep.nome }}
                  </option>
                {% endfor %}
              </select>
              <span style="font-size:11px;color:#94a3b8;">Il caporeparto viene assegnato automaticamente dal catalogo reparti.</span>
```

- [ ] **Step 2: Correggi la nota descrittiva (riga 228)**

Sostituisci:

```html
            Il <strong>reparto</strong> si imposta nella sezione "Dati account" e determina automaticamente l'area aziendale e il caporeparto.
```

con:

```html
            Il <strong>reparto</strong> si imposta nella sezione "Dati account" e determina automaticamente il caporeparto.
```

- [ ] **Step 3: Smoke-test manuale**

```powershell
.venv\Scripts\python.exe django_app\manage.py check --settings=config.settings.test
```

Apri `/anagrafica/dipendenti/nuovo/` in dev: verifica che la select "Reparto" nella sezione "Dati account" mostri solo i nomi dei reparti (nessun suffisso area) e che le note descrittive non menzionino più l'area aziendale come auto-assegnata.

- [ ] **Step 4: Commit**

```bash
git add django_app/anagrafica/templates/anagrafica/pages/dipendente_create.html
git commit -m "fix(anagrafica): dipendente_create.html — rimuove riferimenti a Reparto.area_aziendale"
```

---

### Task 9: `import_dipendenti_xlsx.py` — sync reparto→caporeparto

**Files:**
- Modify: `django_app/anagrafica/management/commands/import_dipendenti_xlsx.py:569-592`

**Interfaces:**
- Consumes: `Reparto` da Task 1 (nessun `.area_aziendale`).

- [ ] **Step 1: Correggi il blocco "3b) Sync reparto → area aziendale + caporeparto"**

Sostituisci in `django_app/anagrafica/management/commands/import_dipendenti_xlsx.py`:

```python
        # 3b) Sync reparto → area aziendale + caporeparto
        reparto_nome = _txt(cell(raw_row, "reparto"))
        if reparto_nome and (created_az or update_existing):
            rep = (
                Reparto.objects
                .filter(nome__iexact=reparto_nome, is_active=True)
                .select_related("area_aziendale")
                .first()
            )
            area_nome = rep.area_aziendale.nome if rep and rep.area_aziendale else ""
            capo_id = rep.caporeparto_legacy_id if rep else None
            update_fields = []
            if aziendale.area != reparto_nome:
                aziendale.area = reparto_nome
                update_fields.append("area")
            if aziendale.area_aziendale_nome != area_nome:
                aziendale.area_aziendale_nome = area_nome
                update_fields.append("area_aziendale_nome")
            if aziendale.caporeparto_legacy_id != capo_id:
                aziendale.caporeparto_legacy_id = capo_id
                update_fields.append("caporeparto_legacy_id")
            if update_fields:
                aziendale.save(update_fields=update_fields)
                stats["aggiornati_reparto"] += 1
```

con:

```python
        # 3b) Sync reparto → caporeparto (l'area aziendale non si autopopola
        # più: con l'inversione della gerarchia un Reparto può avere più
        # Aree aziendali figlie, quindi non è più derivabile da un singolo
        # Reparto — vedi Fase 2 nello spec).
        reparto_nome = _txt(cell(raw_row, "reparto"))
        if reparto_nome and (created_az or update_existing):
            rep = Reparto.objects.filter(nome__iexact=reparto_nome, is_active=True).first()
            capo_id = rep.caporeparto_legacy_id if rep else None
            update_fields = []
            if aziendale.area != reparto_nome:
                aziendale.area = reparto_nome
                update_fields.append("area")
            if aziendale.caporeparto_legacy_id != capo_id:
                aziendale.caporeparto_legacy_id = capo_id
                update_fields.append("caporeparto_legacy_id")
            if update_fields:
                aziendale.save(update_fields=update_fields)
                stats["aggiornati_reparto"] += 1
```

- [ ] **Step 2: Verifica sintattica**

```powershell
.venv\Scripts\python.exe django_app\manage.py check --settings=config.settings.test
.venv\Scripts\python.exe -c "import ast; ast.parse(open(r'django_app\anagrafica\management\commands\import_dipendenti_xlsx.py', encoding='utf-8').read())"
```

Atteso: nessun errore (non esiste una suite di test dedicata a questo comando — verifica proporzionata: sintassi + `check`).

- [ ] **Step 3: Commit**

```bash
git add django_app/anagrafica/management/commands/import_dipendenti_xlsx.py
git commit -m "fix(anagrafica): import_dipendenti_xlsx — rimuove select_related('area_aziendale')

rep.area_aziendale non esiste più su Reparto dopo l'inversione; il
comando continua a sincronizzare area (nome reparto) e caporeparto."
```

---

### Task 10: Dashboard KPI — tile planimetria

**Files:**
- Modify: `django_app/dashboard/views_home_portale.py:399-406`

**Interfaces:**
- Consumes: `Reparto` da Task 1.

- [ ] **Step 1: Correggi il conteggio**

Sostituisci in `django_app/dashboard/views_home_portale.py`:

```python
    # ── PLANIMETRIA ───────────────────────────────────────────────────
    try:
        from anagrafica.models import AreaAziendale
        out["planimetria"] = [
            {"value": AreaAziendale.objects.count(), "unit": "reparti", "tone": "info"},
        ]
    except Exception:
        pass
```

con:

```python
    # ── PLANIMETRIA ───────────────────────────────────────────────────
    try:
        from anagrafica.models import Reparto
        out["planimetria"] = [
            {"value": Reparto.objects.count(), "unit": "reparti", "tone": "info"},
        ]
    except Exception:
        pass
```

- [ ] **Step 2: Verifica**

```powershell
.venv\Scripts\python.exe django_app\manage.py check --settings=config.settings.test
```

Apri la home del portale in dev e verifica che il tile "planimetria" mostri il conteggio corretto (non esiste una suite di test dedicata per questa funzione — verifica manuale proporzionata).

- [ ] **Step 3: Commit**

```bash
git add django_app/dashboard/views_home_portale.py
git commit -m "fix(dashboard): tile planimetria conta Reparto invece di AreaAziendale

AreaAziendale non rappresenta più i 'reparti' dopo l'inversione
gerarchica in anagrafica."
```

---

### Task 11: CHANGELOG.md + README.md

**Files:**
- Modify: `CHANGELOG.md` (sezione `[Unreleased]`, sotto `### Added`)
- Modify: `README.md:382`

**Interfaces:**
- Nessuna (documentazione).

- [ ] **Step 1: Aggiungi la voce in `CHANGELOG.md`**

In `CHANGELOG.md`, subito dopo la riga `### Added` (riga 11) e prima della prima voce esistente, inserisci:

```markdown
- **Anagrafica · Inversione gerarchia Reparto ↔ Area Aziendale** (`django_app/anagrafica/models.py` [Reparto guadagna `colore`+resta padre senza FK verso l'alto; AreaAziendale guadagna FK `reparto`+`responsabile_legacy_id`, perde `colore`], `anagrafica/migrations/0080_reparto_area_aziendale_inversione.py` [nuova, taglio netto — cancella i dati esistenti nella forma vecchia prima di alterare lo schema], `anagrafica/views.py` [`_sync_aziendale_from_reparto` non deriva più l'area aziendale dal reparto; CRUD `area_aziendale_*` gestisce ora il figlio (reparto+responsabile), CRUD `area_*` gestisce ora il padre (colore+caporeparto); `organigramma` raggruppa per Reparto], `templates/anagrafica/pages/aree_list.html` · `organigramma.html` [redesign banda/raggruppamento invertiti] · `impostazioni.html` [tab Aree aziendali/Reparti + blocco Capireparto aggiornati] · `dipendente_detail.html` · `dipendente_create.html` [rimossi riferimenti a `Reparto.area_aziendale`], `anagrafica/management/commands/import_dipendenti_xlsx.py`, `dashboard/views_home_portale.py` [tile planimetria], `anagrafica/tests.py` [+`RepartoAreaAziendaleModelTests`, +`AreeRepartiCrudTests`, `OrganigrammaTests` riscritta]): risponde a «il reparto è il contenitore, l'area aziendale ne fa parte» (es. Reparto "UT" → Aree aziendali "IN1"/"IN2"/"IT"/"DM") — prima era il contrario. Il **caporeparto** resta responsabile dell'intero reparto (invariato: continua a guidare `RepartoCapoMapping`/assenze/automazioni); nuovo campo **opzionale** `responsabile_legacy_id` su AreaAziendale copre casi come UT (aree qualità/produzione con dirigenti diversi), solo metadato in questa fase. L'**assegnazione dell'Area aziendale sul dipendente resta fuori scope** (rimandata a quando la direzione deciderà la UX — 3 opzioni proposte nello spec): il campo "Reparto" del dipendente e il suo dropdown restano invariati, l'auto-fill dell'area aziendale smette di popolarsi (non più derivabile da un reparto con più figli). Superficie di codice verificata con audit esaustivo (65 file classificati: 9 modificati, ~13 compatibili-ma-dati-da-reinserire, ~14 invariati, ~25 non correlati). Spec: `docs/superpowers/specs/2026-07-08-inversione-reparto-area-aziendale-design.md`. Piano: `docs/superpowers/plans/2026-07-08-inversione-reparto-area-aziendale.md`.
```

- [ ] **Step 2: Aggiorna `README.md:382`**

Sostituisci:

```markdown
- **Organigramma visuale** (`/anagrafica/organigramma/`, login): albero Area → Reparto → caporeparto → membri da `AreaAziendale`/`Reparto` + dati legacy. I disallineamenti emergono di proposito (reparti senza area in "Senza area", dipendenti con reparto non a catalogo in "Non mappati"); cessati esclusi; filtro per area.
```

con:

```markdown
- **Organigramma visuale** (`/anagrafica/organigramma/`, login): albero Reparto → Aree aziendali (badge) → caporeparto → membri da `Reparto`/`AreaAziendale` + dati legacy. Il reparto è il contenitore di primo livello (es. "UT"), le aree aziendali (es. "IN1") ne sono la sotto-articolazione. I disallineamenti emergono di proposito (dipendenti con reparto non a catalogo in "Non mappati"); cessati esclusi; filtro per reparto.
```

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md README.md
git commit -m "docs: aggiorna CHANGELOG e README per l'inversione Reparto/AreaAziendale"
```

---

## Note finali per chi esegue il piano

- **Ordine obbligatorio**: Task 1 → 2 → (3, 4 in parallelo se preferito) → 5 → 6 → (7, 8, 9, 10 in parallelo) → 11. Task 3-10 dipendono tutti da Task 1+2.
- **Se il branch è condiviso** (worktree con lavoro concorrente di altre sessioni — vedi memoria di progetto): prima di ogni `git add`, esegui `git status` ed esegui `add` solo sui file elencati in ogni Step, mai `git add -A`/`git add .`.
- **Non toccare** in questo piano: assegnazione Area aziendale sul dipendente (Fase 2), `RegolaObbligoFormazione`/`EsposizioneRischio`/`gestione_specifiche.reparto_in1` (dati da riconfigurare da UI dopo il deploy, non codice).
- A fine piano, esegui l'intera suite `anagrafica` una volta (`--keepdb` per velocità) e verifica lo stato pulito prima di considerare il lavoro concluso:

```powershell
.venv\Scripts\python.exe django_app\manage.py test anagrafica --settings=config.settings.test --keepdb -v 1
.venv\Scripts\python.exe django_app\manage.py check --settings=config.settings.test
```
