# Asset "Prodotto chimico" + Numero interno opt-in — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rendere il numero interno degli asset opt-in (bottone "Assegna progressivo", vuoto = nessuno) e introdurre un tipo asset "Prodotto chimico" collegato 1:1 al `ProdottoChimico`/SDS di `schede_sicurezza`, con schermata dedicata.

**Architecture:** Due interventi in `assets`. (A) si toglie l'auto-assegnazione da `Asset.save()` e si espone un endpoint AJAX per il prossimo progressivo. (B) si aggiunge `Asset.TYPE_CHEMICAL` + `OneToOneField` verso `schede_sicurezza.ProdottoChimico`, con form/viste/template dedicati sul modello del pattern `WORK_MACHINE` già esistente; `schede_sicurezza` resta fonte unica dei dati chimici. Doppio ingresso: creazione/aggancio sia da `assets` sia da `schede_sicurezza`.

**Tech Stack:** Django 5.2, Python 3.11+, SSR templates + HTMX, test runner Django su SQL Server/SQLite (`config.settings.test`).

## Global Constraints

- Modifiche e commit SOLO nel worktree `C:\Dev\pn-asset-chimici` (branch `feature/assets-prodotti-chimici`). Mai nel checkout condiviso.
- Test solo degli app toccati, con `--keepdb`:
  `python django_app\manage.py test django_app.assets django_app.schede_sicurezza --keepdb --settings=config.settings.test`.
- Le view test che verificano un gate devono usare `@override_settings(LEGACY_AUTH_ENABLED=False)`, altrimenti l'ACL middleware nega tutto ai non-superuser (403 dal middleware, non dal gate testato).
- Endpoint API/AJAX protetti → risposta JSON `401/403`, mai redirect HTML.
- Ogni nuova rotta `/assets/...` va aggiunta a `_PULSANTI_DEFINITIONS` in `assets/acl_bootstrap.py` **e** va bumpata la cache key `_BOOTSTRAP_CACHE_KEY` (`assets_acl_bootstrap_v6` → `v7`), altrimenti in strict-mode la rotta è negata.
- `core/numbering.py` è condiviso con `anagrafica` (codice corso): NON modificarlo.
- Il PDF SDS non va mai copiato: si linka lo storage privato cifrato esistente.
- A fine lavoro: aggiornare `CHANGELOG.md` (sotto `[Unreleased]`, tutti i file) e `README.md` (catalogo/sezione assets). Obbligatorio.

---

## PART A — Numero interno opt-in

### Task 1: Togliere l'auto-assegnazione del numero interno da `Asset.save()`

**Files:**
- Modify: `django_app/assets/models.py:166-179`
- Test: `django_app/assets/tests_numbering_p3.py`

**Interfaces:**
- Produces: dopo questo task, `Asset.objects.create(...)` senza `internal_number` lascia il campo `""`.

- [ ] **Step 1: Aggiornare i test esistenti al nuovo comportamento**

In `django_app/assets/tests_numbering_p3.py` sostituire il test di auto-assegnazione:

```python
def test_internal_number_vuoto_resta_vuoto_alla_creazione(self):
    a1 = Asset.objects.create(asset_tag="NUM-1", name="A1")
    a2 = Asset.objects.create(asset_tag="NUM-2", name="A2")
    self.assertEqual(a1.internal_number, "")
    self.assertEqual(a2.internal_number, "")

def test_internal_number_esplicito_non_sovrascritto(self):
    a = Asset.objects.create(asset_tag="NUM-3", name="A3", internal_number="ABC-99")
    self.assertEqual(a.internal_number, "ABC-99")
```

Rimuovere `test_internal_number_progressivo_alla_creazione` e
`test_internal_number_ignora_legacy_alfanumerico` (non più validi: nessuna
auto-assegnazione).

- [ ] **Step 2: Eseguire il test — deve FALLIRE**

Run: `python django_app\manage.py test django_app.assets.tests_numbering_p3 --keepdb --settings=config.settings.test`
Expected: FAIL — oggi `save()` assegna "1"/"2", quindi `assertEqual(..., "")` fallisce.

- [ ] **Step 3: Rimuovere il blocco di auto-assegnazione in `Asset.save()`**

In `django_app/assets/models.py`, dentro `save()`, eliminare:

```python
        # 3.3: N. interno progressivo assegnato alla creazione se lasciato vuoto.
        # ...
        if self._state.adding and not (self.internal_number or "").strip():
            from core.numbering import next_numeric
            self.internal_number = str(
                next_numeric(type(self).objects.values_list("internal_number", flat=True))
            )
```

Lasciare intatto il resto di `save()` (source_key, qr token, asset_tag).

- [ ] **Step 4: Eseguire il test — deve PASSARE**

Run: `python django_app\manage.py test django_app.assets.tests_numbering_p3 --keepdb --settings=config.settings.test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add django_app/assets/models.py django_app/assets/tests_numbering_p3.py
git commit -m "feat(assets): numero interno opt-in — niente auto-assegnazione alla creazione"
```

---

### Task 2: Endpoint "prossimo progressivo" + registrazione ACL

**Files:**
- Modify: `django_app/assets/views.py` (nuova view `asset_internal_number_next`)
- Modify: `django_app/assets/urls.py` (nuova path)
- Modify: `django_app/assets/acl_bootstrap.py` (nuova definizione + bump cache key)
- Test: `django_app/assets/tests.py` (o `tests_numbering_p3.py`)

**Interfaces:**
- Produces: `GET /assets/internal-number/next/` → JSON `{"next": <int>}`; nome url `assets:internal_number_next`.

- [ ] **Step 1: Scrivere il test della view**

In `django_app/assets/tests.py` (con `@override_settings(LEGACY_AUTH_ENABLED=False)` sulla classe):

```python
def test_internal_number_next_returns_max_plus_one(self):
    Asset.objects.create(asset_tag="N-1", name="a", internal_number="188")
    self.client.force_login(self.superuser)
    resp = self.client.get(reverse("assets:internal_number_next"))
    self.assertEqual(resp.status_code, 200)
    self.assertEqual(resp.json()["next"], 189)
```

- [ ] **Step 2: Eseguire — FALLISce** (NoReverseMatch)

Run: `python django_app\manage.py test django_app.assets.tests -k internal_number_next --keepdb --settings=config.settings.test`
Expected: FAIL.

- [ ] **Step 3: Implementare la view**

In `django_app/assets/views.py` (accanto ad `asset_create`):

```python
from django.http import JsonResponse
from core.numbering import next_numeric

@login_required
def asset_internal_number_next(request: HttpRequest) -> JsonResponse:
    value = next_numeric(Asset.objects.values_list("internal_number", flat=True))
    return JsonResponse({"next": value})
```

- [ ] **Step 4: Registrare la URL**

In `django_app/assets/urls.py`, prima di `path("assets/view/", ...)`:

```python
    path("assets/internal-number/next/", views.asset_internal_number_next, name="internal_number_next"),
```

- [ ] **Step 5: Registrare la rotta in ACL e bumpare la cache key**

In `django_app/assets/acl_bootstrap.py`: cambiare `_BOOTSTRAP_CACHE_KEY = "assets_acl_bootstrap_v6"` in `"assets_acl_bootstrap_v7"` e aggiungere a `_PULSANTI_DEFINITIONS`:

```python
    {"modulo": "assets", "codice": "assets_internal_number_next", "label": "Assets - Prossimo numero interno", "url": "/assets/internal-number/next/", "hide": True},
```

- [ ] **Step 6: Eseguire — PASSA**

Run: `python django_app\manage.py test django_app.assets.tests -k internal_number_next --keepdb --settings=config.settings.test`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add django_app/assets/views.py django_app/assets/urls.py django_app/assets/acl_bootstrap.py django_app/assets/tests.py
git commit -m "feat(assets): endpoint prossimo numero interno progressivo (ACL registrata)"
```

---

### Task 3: Bottone "Assegna progressivo" nel form asset

**Files:**
- Modify: `django_app/assets/templates/assets/pages/asset_form.html` (campo `internal_number`)
- Test: `django_app/assets/tests.py`

**Interfaces:**
- Consumes: `assets:internal_number_next` (Task 2).

- [ ] **Step 1: Test di rendering**

```python
def test_asset_form_shows_assegna_progressivo_button(self):
    self.client.force_login(self.superuser)
    resp = self.client.get(reverse("assets:asset_create"))
    self.assertContains(resp, "Assegna progressivo")
    self.assertContains(resp, reverse("assets:internal_number_next"))
```

- [ ] **Step 2: Eseguire — FALLISce**

Run: `python django_app\manage.py test django_app.assets.tests -k assegna_progressivo --keepdb --settings=config.settings.test`
Expected: FAIL.

- [ ] **Step 3: Aggiungere il bottone accanto al campo**

Individuare nel template come è reso `internal_number` (campo base). Affiancare un bottone che chiama l'endpoint e riempie l'input. JS inline minimale (nessun submit):

```html
<button type="button" class="af-btn af-btn-ghost" id="assign-internal-number"
        data-url="{% url 'assets:internal_number_next' %}">Assegna progressivo</button>
<script>
  document.getElementById("assign-internal-number")?.addEventListener("click", async (e) => {
    const r = await fetch(e.target.dataset.url, {headers: {"X-Requested-With": "XMLHttpRequest"}});
    if (!r.ok) return;
    const data = await r.json();
    const input = document.querySelector('[name="internal_number"]');
    if (input) input.value = data.next;
  });
</script>
```

Il campo resta vuoto se non si clicca (default già garantito dal Task 1).

- [ ] **Step 4: Eseguire — PASSA**

Run: `python django_app\manage.py test django_app.assets.tests -k assegna_progressivo --keepdb --settings=config.settings.test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add django_app/assets/templates/assets/pages/asset_form.html django_app/assets/tests.py
git commit -m "feat(assets): bottone 'Assegna progressivo' per il numero interno"
```

---

## PART B — Asset "Prodotto chimico"

### Task 4: Modello — tipo asset + link 1:1 al ProdottoChimico

**Files:**
- Modify: `django_app/assets/models.py` (TYPE_CHEMICAL, TYPE_CHOICES, campo `prodotto_chimico`)
- Create: `django_app/assets/migrations/0075_asset_prodotto_chimico.py` (via makemigrations)
- Test: `django_app/assets/tests.py`

**Interfaces:**
- Produces: `Asset.TYPE_CHEMICAL == "PRODOTTO_CHIMICO"`; `Asset.prodotto_chimico` (OneToOne, nullable); reverse `ProdottoChimico.asset_container`.

- [ ] **Step 1: Test del modello**

```python
from schede_sicurezza.models import ProdottoChimico
from anagrafica.models import Reparto

def test_asset_can_link_prodotto_chimico(self):
    rep = Reparto.objects.create(nome="Chimica")  # verificare campi obbligatori Reparto
    p = ProdottoChimico.objects.create(nome="Acetone", reparto=rep)
    a = Asset.objects.create(asset_tag="CHEM-1", name="Acetone",
                             asset_type=Asset.TYPE_CHEMICAL, prodotto_chimico=p)
    self.assertEqual(p.asset_container, a)
```

- [ ] **Step 2: Eseguire — FALLISce** (AttributeError TYPE_CHEMICAL)

Run: `python django_app\manage.py test django_app.assets.tests -k link_prodotto_chimico --keepdb --settings=config.settings.test`
Expected: FAIL.

- [ ] **Step 3: Aggiungere tipo e campo**

In `django_app/assets/models.py`: aggiungere `TYPE_CHEMICAL = "PRODOTTO_CHIMICO"` accanto agli altri TYPE_*, la coppia `(TYPE_CHEMICAL, "Prodotto chimico")` in `TYPE_CHOICES`, e il campo:

```python
    prodotto_chimico = models.OneToOneField(
        "schede_sicurezza.ProdottoChimico",
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name="asset_container",
    )
```

- [ ] **Step 4: Generare la migration**

Run: `python django_app\manage.py makemigrations assets --settings=config.settings.dev`
Verificare che crei `0075_asset_prodotto_chimico.py` (AddField + AlterField su asset_type choices).

- [ ] **Step 5: Eseguire — PASSA**

Run: `python django_app\manage.py test django_app.assets.tests -k link_prodotto_chimico --keepdb --settings=config.settings.test`
Expected: PASS. (Se il test lamenta campi obbligatori su `Reparto`, adeguare la fixture ai campi reali del modello.)

- [ ] **Step 6: Commit**

```bash
git add django_app/assets/models.py django_app/assets/migrations/0075_asset_prodotto_chimico.py django_app/assets/tests.py
git commit -m "feat(assets): tipo 'Prodotto chimico' + link 1:1 a schede_sicurezza.ProdottoChimico"
```

---

### Task 5: `ChemicalAssetForm` — aggancio esistente + crea-nuovo inline

**Files:**
- Modify: `django_app/assets/forms.py` (nuova `ChemicalAssetForm`)
- Test: `django_app/assets/tests.py`

**Interfaces:**
- Produces: `ChemicalAssetForm` con campi asset ridotti + `prodotto_chimico` (select) + campi inline (`nuovo_nome`, `nuovo_fornitore`, `nuovo_produttore`, `nuovo_ubicazione`, `nuovo_quantita`, `nuovo_codice`); `save()` crea/aggancia il `ProdottoChimico` e ritorna l'`Asset`.

- [ ] **Step 1: Test — crea nuovo prodotto inline**

```python
def test_chemical_form_creates_new_prodotto_inline(self):
    rep = Reparto.objects.create(nome="Chimica")
    form = ChemicalAssetForm(data={
        "asset_tag": "CHEM-9", "name": "Acetone", "status": Asset.STATUS_IN_STOCK,
        "reparto_id": rep.id, "prodotto_mode": "new", "nuovo_nome": "Acetone 99%",
    })
    self.assertTrue(form.is_valid(), form.errors)
    asset = form.save()
    self.assertEqual(asset.asset_type, Asset.TYPE_CHEMICAL)
    self.assertEqual(asset.prodotto_chimico.nome, "Acetone 99%")
```

(Adeguare i nomi campo assignment/reparto a quelli reali; `reparto` su `ProdottoChimico` è FK PROTECT obbligatoria → il form deve fornirla, riusando il reparto dell'asset.)

- [ ] **Step 2: Eseguire — FALLISce** (ImportError ChemicalAssetForm)

Run: `python django_app\manage.py test django_app.assets.tests -k chemical_form --keepdb --settings=config.settings.test`
Expected: FAIL.

- [ ] **Step 3: Implementare `ChemicalAssetForm`**

In `django_app/assets/forms.py`, una `ModelForm` su `Asset` con `Meta.fields` ridotto (SENZA manufacturer/model/serial/part_145/sharepoint/assignment): `["asset_tag", "internal_number"? no →` escluderlo `, "name", "reparto", "status", "notes", "purchase_date"]`. Aggiungere:
- `prodotto_chimico = forms.ModelChoiceField(queryset=ProdottoChimico.objects.filter(attivo=True), required=False)`;
- `prodotto_mode = forms.ChoiceField(choices=[("existing","Esistente"),("new","Nuovo")])`;
- campi `nuovo_*` (`CharField(required=False)`).
- `clean()`: se `prodotto_mode=="existing"` richiede `prodotto_chimico`; se `"new"` richiede `nuovo_nome`; validare che il `ProdottoChimico` scelto non abbia già un `asset_container` (OneToOne).
- `save(commit=True)`: forza `instance.asset_type = Asset.TYPE_CHEMICAL`; se mode new crea `ProdottoChimico(nome=..., reparto=<reparto asset>, fornitore=..., ...)`; assegna `instance.prodotto_chimico`; salva e ritorna.

- [ ] **Step 4: Eseguire — PASSA**

Run: `python django_app\manage.py test django_app.assets.tests -k chemical_form --keepdb --settings=config.settings.test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add django_app/assets/forms.py django_app/assets/tests.py
git commit -m "feat(assets): ChemicalAssetForm (aggancio esistente o crea-nuovo inline)"
```

---

### Task 6: Viste create/edit chimico + URL + ACL + routing

**Files:**
- Modify: `django_app/assets/views.py` (`chemical_asset_create`, `chemical_asset_edit`; routing in `asset_create`/`asset_edit`)
- Modify: `django_app/assets/urls.py`
- Modify: `django_app/assets/acl_bootstrap.py`
- Create: `django_app/assets/templates/assets/pages/chemical_asset_form.html`
- Test: `django_app/assets/tests.py`

**Interfaces:**
- Produces: url `assets:chemical_create` (`/assets/chimici/new/`), `assets:chemical_edit` (`/assets/chimici/edit/<int:id>/`).

- [ ] **Step 1: Test — POST crea asset chimico**

```python
def test_chemical_create_view_creates_asset(self):
    rep = Reparto.objects.create(nome="Chimica")
    self.client.force_login(self.superuser)
    resp = self.client.post(reverse("assets:chemical_create"), {
        "asset_tag": "CHEM-7", "name": "Diluente", "status": Asset.STATUS_IN_STOCK,
        "reparto": rep.id, "prodotto_mode": "new", "nuovo_nome": "Diluente X",
    })
    self.assertEqual(resp.status_code, 302)
    self.assertTrue(Asset.objects.filter(asset_tag="CHEM-7",
                    asset_type=Asset.TYPE_CHEMICAL).exists())
```

Aggiungere `@override_settings(LEGACY_AUTH_ENABLED=False)` sulla classe.

- [ ] **Step 2: Eseguire — FALLISce**

Run: `python django_app\manage.py test django_app.assets.tests -k chemical_create_view --keepdb --settings=config.settings.test`
Expected: FAIL.

- [ ] **Step 3: Implementare viste + template + URL + ACL**

- Viste `chemical_asset_create`/`chemical_asset_edit` sul modello di `asset_create`/`asset_edit` ma con `ChemicalAssetForm` e template `chemical_asset_form.html`.
- In `asset_create`: aggiungere, in cima, il redirect come per WORK_MACHINE:
  ```python
  if _clean_string(request.GET.get("asset_type")) == Asset.TYPE_CHEMICAL:
      return redirect("assets:chemical_create")
  ```
  e in `asset_edit`: `if asset.asset_type == Asset.TYPE_CHEMICAL: return redirect("assets:chemical_edit", id=asset.id)`.
- `chemical_asset_form.html`: form snello con toggle "Esistente/Nuovo" (mostra la select oppure i campi `nuovo_*` via piccolo JS), riusa i token del tema.
- URL:
  ```python
  path("assets/chimici/new/", views.chemical_asset_create, name="chemical_create"),
  path("assets/chimici/edit/<int:id>/", views.chemical_asset_edit, name="chemical_edit"),
  ```
- ACL: bump già fatto (v7) al Task 2; aggiungere due definizioni:
  ```python
  {"modulo": "assets", "codice": "assets_chemical_new", "label": "Assets - Nuovo prodotto chimico", "url": "/assets/chimici/new/", "hide": True},
  {"modulo": "assets", "codice": "assets_chemical_edit", "label": "Assets - Modifica prodotto chimico", "url": "/assets/chimici/edit/", "hide": True},
  ```
  (Se il Task 2 è già committato, bumpare di nuovo la cache key a `v8` per forzare il re-seed.)

- [ ] **Step 4: Eseguire — PASSA**

Run: `python django_app\manage.py test django_app.assets.tests -k chemical_create_view --keepdb --settings=config.settings.test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add django_app/assets/views.py django_app/assets/urls.py django_app/assets/acl_bootstrap.py django_app/assets/templates/assets/pages/chemical_asset_form.html django_app/assets/tests.py
git commit -m "feat(assets): viste/URL/ACL create-edit asset prodotto chimico"
```

---

### Task 7: Schermata dettaglio chimico (mostra SDS, nasconde non pertinenti)

**Files:**
- Modify: `django_app/assets/views.py` (`asset_detail`: context `prodotto_chimico` + `scheda_corrente`)
- Modify: `django_app/assets/templates/assets/pages/asset_detail.html` (ramo `PRODOTTO_CHIMICO`)
- Create: `django_app/assets/templates/assets/partials/_chemical_detail.html`
- Test: `django_app/assets/tests.py`

**Interfaces:**
- Consumes: `Asset.prodotto_chimico`, `ProdottoChimico.scheda_corrente()`.

- [ ] **Step 1: Test — dettaglio mostra dati chimici e nasconde i non pertinenti**

```python
def test_chemical_detail_shows_sds_and_hides_maintenance(self):
    rep = Reparto.objects.create(nome="Chimica")
    p = ProdottoChimico.objects.create(nome="Acetone", reparto=rep, ubicazione="Scaffale A")
    a = Asset.objects.create(asset_tag="CHEM-3", name="Acetone",
                             asset_type=Asset.TYPE_CHEMICAL, prodotto_chimico=p)
    self.client.force_login(self.superuser)
    resp = self.client.get(reverse("assets:asset_view") + f"?id={a.id}")  # verificare forma URL reale
    self.assertContains(resp, "Scaffale A")
    self.assertContains(resp, "Pittogrammi")
    self.assertNotContains(resp, "Scadenzario")          # blocco manutenzioni nascosto
    self.assertNotContains(resp, "Contratti di assistenza")
```

(Verificare la forma reale della URL di dettaglio: `assets:asset_view` usa querystring `?id=` — vedi `urls.py:64`.)

- [ ] **Step 2: Eseguire — FALLISce**

Run: `python django_app\manage.py test django_app.assets.tests -k chemical_detail --keepdb --settings=config.settings.test`
Expected: FAIL.

- [ ] **Step 3: Context nella view**

In `asset_detail`, dopo il fetch dell'asset, aggiungere al context:

```python
    prodotto_chimico = getattr(asset, "prodotto_chimico", None)
    scheda_corrente = prodotto_chimico.scheda_corrente() if prodotto_chimico else None
```

e passarli al template (`"prodotto_chimico": prodotto_chimico, "scheda_corrente": scheda_corrente`). Aggiungere `select_related("prodotto_chimico")` alla query.

- [ ] **Step 4: Ramo template + partial**

In `asset_detail.html`, avvolgere i blocchi non pertinenti (status band copertura+scadenze ~287/620, scadenze amministrative ~818, costi manutenzione ~898, rami WORK_MACHINE/CNC ~453/1456/1717) con una guardia `{% if asset.asset_type != "PRODOTTO_CHIMICO" %}...{% endif %}`, e aggiungere:

```django
{% if asset.asset_type == "PRODOTTO_CHIMICO" %}
  {% include "assets/partials/_chemical_detail.html" %}
{% endif %}
```

`_chemical_detail.html` rende: pittogrammi (da `scheda_corrente.pittogrammi`), stato scheda (corrente/scaduta), frasi H/P, classificazione CLP, DPI obbligatori (`prodotto_chimico.dpi_obbligatori.all`), primo soccorso, incompatibilità, ubicazione/quantità/codice/fornitore/produttore/famiglia/sottocategoria/`numero_interno`, link PDF `scheda_corrente.pdf.url` + versione + presa visione. Se `prodotto_chimico` è nullo → banner "Prodotto non collegato"; se `scheda_corrente` è nullo → "SDS non disponibile". Riusare i token del tema (nessun namespace CSS nuovo).

- [ ] **Step 5: Eseguire — PASSA**

Run: `python django_app\manage.py test django_app.assets.tests -k chemical_detail --keepdb --settings=config.settings.test`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add django_app/assets/views.py django_app/assets/templates/assets/pages/asset_detail.html django_app/assets/templates/assets/partials/_chemical_detail.html django_app/assets/tests.py
git commit -m "feat(assets): schermata dettaglio dedicata per asset prodotto chimico"
```

---

### Task 8: Doppio ingresso — toggle "Crea anche l'asset" in schede_sicurezza

**Files:**
- Modify: `django_app/schede_sicurezza/views.py` (`prodotto_form`)
- Modify: `django_app/schede_sicurezza/templates/schede_sicurezza/pages/prodotto_form.html`
- Test: `django_app/schede_sicurezza/tests_views.py`

**Interfaces:**
- Consumes: `Asset` (import dentro la view/funzione, non a livello di modulo, per evitare dipendenza dura di import).

- [ ] **Step 1: Test — il toggle crea l'asset collegato**

```python
@override_settings(LEGACY_AUTH_ENABLED=False)
def test_prodotto_form_crea_asset_collegato(self):
    rep = Reparto.objects.create(nome="Chimica")
    self.client.force_login(self.gestore)  # utente con _can_gestire
    resp = self.client.post(reverse("schede_sicurezza:prodotto_create"), {
        "nome": "Acido", "reparto": rep.id, "crea_asset": "on",
    })
    p = ProdottoChimico.objects.get(nome="Acido")
    self.assertIsNotNone(getattr(p, "asset_container", None))
```

(Verificare il nome URL reale del create prodotto in `schede_sicurezza/urls.py`.)

- [ ] **Step 2: Eseguire — FALLISce**

Run: `python django_app\manage.py test django_app.schede_sicurezza.tests_views -k crea_asset_collegato --keepdb --settings=config.settings.test`
Expected: FAIL.

- [ ] **Step 3: Implementare toggle + logica**

Nel template `prodotto_form.html`: checkbox `name="crea_asset"` (mostrata solo in creazione, `pk is None`). In `prodotto_form`, dopo `prodotto.save()` (ramo creazione), se `request.POST.get("crea_asset")` e il prodotto non ha già `asset_container`:

```python
        if pk is None and request.POST.get("crea_asset") and not getattr(prodotto, "asset_container", None):
            from assets.models import Asset
            Asset.objects.create(
                name=prodotto.nome,
                asset_type=Asset.TYPE_CHEMICAL,
                prodotto_chimico=prodotto,
            )
```

(`asset_tag` viene autogenerato da `Asset.save()`.)

- [ ] **Step 4: Eseguire — PASSA**

Run: `python django_app\manage.py test django_app.schede_sicurezza.tests_views -k crea_asset_collegato --keepdb --settings=config.settings.test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add django_app/schede_sicurezza/views.py django_app/schede_sicurezza/templates/schede_sicurezza/pages/prodotto_form.html django_app/schede_sicurezza/tests_views.py
git commit -m "feat(schede_sicurezza): toggle 'crea anche l'asset' collegato al prodotto"
```

---

### Task 9: Filtro/ingresso "Prodotti chimici" in assets + docs + suite finale

**Files:**
- Modify: `django_app/assets/templates/...` (voce/filtro per il tipo chimico dove i tipi sono già filtrabili; seguire il pattern esistente dei tipi)
- Modify: `CHANGELOG.md`, `README.md`
- Test: full run degli app toccati

- [ ] **Step 1: Punto d'ingresso**

Aggiungere il tipo "Prodotto chimico" dove gli altri tipi asset sono già offerti in creazione/filtro lista (menu "Nuovo asset" e filtro per tipo nella lista). Seguire il pattern `TYPE_*` esistente; nessun namespace nuovo.

- [ ] **Step 2: CHANGELOG + README**

`CHANGELOG.md` sotto `[Unreleased]`: elencare tutti i file toccati con descrizione (numero interno opt-in; tipo asset prodotto chimico + link SDS + schermata; toggle schede_sicurezza). `README.md`: aggiornare la sezione assets (nuovo tipo + collegamento a schede_sicurezza).

- [ ] **Step 3: Suite finale degli app toccati**

Run: `python django_app\manage.py test django_app.assets django_app.schede_sicurezza --keepdb --settings=config.settings.test`
Expected: PASS (verde). Se rosso, correggere prima di chiudere.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "docs+chore(assets): ingresso tipo chimico, CHANGELOG e README"
```

---

## Self-review (coverage)

- Spec A (opt-in): Task 1 (save), Task 2 (endpoint+ACL), Task 3 (bottone). ✓
- Spec B modello/link 1:1: Task 4. ✓
- Doppio ingresso: Task 5/6 (da assets) + Task 8 (da schede_sicurezza). ✓
- Creazione inline libera: Task 5 (nessun gate SDS). ✓
- Schermata dedicata (mostra SDS / nasconde manutenzione+assistenza+PART145+macchina+SharePoint/responsabile): Task 7. ✓
- ACL rotte nuove + bump cache key: Task 2/6. ✓
- Errori (SDS assente / link nullo): Task 7 Step 4. ✓
- Testing + `LEGACY_AUTH_ENABLED=False`: ogni task view. ✓
- Docs: Task 9. ✓

## Note di verifica durante l'implementazione (non placeholder: punti da confermare col codice reale)

- Campi obbligatori reali di `anagrafica.Reparto` per le fixture di test.
- Tipo del campo `Asset.reparto` (per riusarlo come reparto del `ProdottoChimico` in inline-create).
- Forma esatta della URL di dettaglio (`assets:asset_view` con querystring `?id=`, non kwarg).
- Nome reale della URL di creazione prodotto in `schede_sicurezza/urls.py`.
- Come sono resi i campi nel form asset (`base_field_names`) per posizionare il bottone del Task 3.
