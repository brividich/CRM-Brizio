# Procedure Refresh · Lista unica + sync che segnala + Bacheca — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (inline). Steps use checkbox (`- [ ]`) syntax.

**Goal:** Unificare la lista documenti (badge AI+Presa visione coesistono), aprire il picker campagna a tutti i documenti, far sì che il sync notturno aggiorni e segnali le revisioni cambiate con un log append-only, e rendere i documenti procedura consultabili dentro la Bacheca (esclusi i sensibili) con apertura anche dei file-server.

**Architecture:** SSR Django + template + JS vanilla. Nessun nuovo endpoint API. Builder Bacheca in `procedure_refresh`, chiamato dalle view `dashboard` (core resta indipendente). Log sync come modello append-only.

**Tech Stack:** Django 5.2, SQL Server (SQLite dev), test `config.settings.test`.

## Global Constraints

- Test: `.venv\Scripts\python.exe manage.py test procedure_refresh --keepdb --settings=config.settings.test` (label app top-level, no `django_app.`).
- Email sempre su `email_notifica` (mai `email` legacy). Nessun dato reale nei test.
- Deny-list sensibili = `escludi_dal_rag=True` OR keyword deny-list, rispettata in Bacheca e `document_open`.
- SQL-Server-safe: no indici parziali/condition/unique nullable.
- Commit mirati al modulo (`git add` esplicito), no push (WIP concorrente sul branch).
- CHANGELOG.md + README.md a fine lavoro.

---

### Task 1: Lista unica + picker campagna aperto + toggle relabel

**Files:**
- Modify: `django_app/procedure_refresh/views.py` (`document_list`, `campaign_detail.available_revisions`, `document_toggle_ack` messaggi)
- Modify: `django_app/procedure_refresh/templates/procedure_refresh/pages/document_list.html`
- Modify: `django_app/procedure_refresh/templates/procedure_refresh/pages/campaign_detail.html` (ricerca picker)
- Test: `django_app/procedure_refresh/tests.py`

**Interfaces:**
- Produces: `document_list` context ora sempre `documents` = tutti (con filtro chip `?filtro=tutti|pv|ai|sensibili`), niente più partizione esclusiva `vista=pv|rag`. `available_revisions` non filtra su `requires_acknowledgement`.

- [ ] **Step 1 — Test rosso:** in `AclAndUxTests` aggiungi:

```python
def test_lista_unica_mostra_tutti_con_badge(self):
    self.client.force_login(self.manager)
    resp = self.client.get(reverse("procedure_refresh:document_list"))
    codes = {d.code for d in resp.context["documents"]}
    self.assertIn("MT-PV-001", codes)
    self.assertIn("MT-RAG-001", codes)  # ora coesistono nella stessa lista

def test_picker_mostra_anche_non_presa_visione(self):
    campaign = ProcedureCampaign.objects.create(
        name="P", status=CampaignStatus.DRAFT,
        start_date=date(2026, 1, 1), due_date=date(2026, 12, 31), created_by=self.manager,
    )
    self.client.force_login(self.manager)
    resp = self.client.get(reverse("procedure_refresh:campaign_detail", kwargs={"pk": campaign.pk}))
    rev_docs = {r.document.code for r in resp.context["available_revisions"]}
    self.assertIn("MT-PV-001", rev_docs)
    self.assertIn("MT-RAG-001", rev_docs)  # non più escluso
```

Rimuovi/aggiorna i vecchi test che assumevano l'esclusività (`test_document_list_default_vista_presa_visione`, `test_document_list_vista_rag`, `test_campaign_picker_only_presa_visione_current`, `test_toggle_*`): il picker ora include tutti; adegua le asserzioni (il toggle cambia solo il badge, non l'inclusione nel picker).

- [ ] **Step 2 — Run:** `... test procedure_refresh.tests.AclAndUxTests` → FAIL.

- [ ] **Step 3 — Implementazione `document_list`:** una sola lista con filtro chip opzionale:

```python
filtro = request.GET.get("filtro", "tutti").strip()
qs = ProcedureDocument.objects.prefetch_related("revisions").annotate(
    n_open_change_requests=Count("change_requests", filter=Q(
        change_requests__status__in=[ChangeRequestStatus.APERTA, ChangeRequestStatus.IN_CARICO]))
).order_by("document_type", "code")
if filtro == "pv":
    qs = qs.filter(requires_acknowledgement=True)
elif filtro == "ai":
    qs = qs.filter(escludi_dal_rag=False)
elif filtro == "sensibili":
    qs = qs.filter(escludi_dal_rag=True)
if query:
    qs = qs.filter(Q(code__icontains=query) | Q(title__icontains=query))
# context: documents, filtro, query, n_pv, n_ai, n_sensibili, n_tot
```

- [ ] **Step 4 — Implementazione picker:** in `campaign_detail`, togli `document__requires_acknowledgement=True`:

```python
available_revisions = (
    ProcedureRevision.objects.filter(document__is_active=True, is_current=True)
    .exclude(id__in=already_in)
    .select_related("document")
    .order_by("document__document_type", "document__code", "-revision_date")
)
```

- [ ] **Step 5 — Template `document_list.html`:** sostituisci i due tab con chip filtro (Tutti/Presa visione/Corpus AI/Sensibili) su `?filtro=`; per riga mostra badge `AI` (se non `doc.escludi_dal_rag`) e `Presa visione` (se `doc.requires_acknowledgement`). Aggiorna copy del toggle: «Marca presa visione» / «Smarca» (togli la frase «non sarà più selezionabile nelle campagne»).

- [ ] **Step 6 — Template `campaign_detail.html`:** aggiungi un `<input>` di ricerca client-side che filtra le `<option>`/righe del picker per testo (sono centinaia).

- [ ] **Step 7 — Run** suite `procedure_refresh` → PASS. **Commit:** `feat(procedure_refresh): lista documenti unica + picker campagna aperto a tutti i documenti`.

---

### Task 2: Modello SgiSyncLog + migration + pagina admin

**Files:**
- Modify: `django_app/procedure_refresh/models.py` (`SgiSyncAction`, `SgiSyncLog`)
- Create: `django_app/procedure_refresh/migrations/0007_sgisynclog.py` (via makemigrations)
- Modify: `django_app/procedure_refresh/admin.py` (registra `SgiSyncLog`)
- Modify: `django_app/procedure_refresh/urls.py` (`admin/sync-log/`)
- Modify: `django_app/procedure_refresh/views.py` (`sync_log_list`)
- Create: `django_app/procedure_refresh/templates/procedure_refresh/pages/sync_log_list.html`
- Modify: `django_app/procedure_refresh/templates/procedure_refresh/components/subnav.html` (voce «Log sync»)
- Test: `django_app/procedure_refresh/tests.py`

**Interfaces:**
- Produces: `SgiSyncLog(run_id, azione, document_code, revision_old, revision_new, note, origine, created_at)`; `SgiSyncAction` ∈ {NUOVO_DOC, NUOVA_REVISIONE, DOC_SPARITO}; helper `log_sgi_change(*, run_id, azione, document_code, revision_old="", revision_new="", note="", origine="auto")`.

- [ ] **Step 1 — Test rosso:**

```python
class SgiSyncLogTests(TestCase):
    def test_log_append_only_e_query(self):
        from procedure_refresh.models import SgiSyncLog, SgiSyncAction
        from procedure_refresh.tasks import log_sgi_change
        log_sgi_change(run_id="r1", azione=SgiSyncAction.NUOVA_REVISIONE,
                       document_code="MT CN 06", revision_old="20", revision_new="21")
        row = SgiSyncLog.objects.get()
        self.assertEqual(row.azione, SgiSyncAction.NUOVA_REVISIONE)
        self.assertEqual(row.revision_new, "21")
```

- [ ] **Step 2 — Run** → FAIL (import error).

- [ ] **Step 3 — Modello** in `models.py`:

```python
class SgiSyncAction(models.TextChoices):
    NUOVO_DOC = "nuovo_doc", "Nuovo documento"
    NUOVA_REVISIONE = "nuova_revisione", "Nuova revisione"
    DOC_SPARITO = "doc_sparito", "Documento sparito dalla share"

class SgiSyncLog(models.Model):
    run_id = models.CharField(max_length=64, db_index=True)
    azione = models.CharField(max_length=20, choices=SgiSyncAction.choices, db_index=True)
    document_code = models.CharField(max_length=50, db_index=True)
    revision_old = models.CharField(max_length=50, blank=True, default="")
    revision_new = models.CharField(max_length=50, blank=True, default="")
    note = models.CharField(max_length=300, blank=True, default="")
    origine = models.CharField(max_length=10, default="auto")  # auto | manuale
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Log sincronizzazione SGI"
        verbose_name_plural = "Log sincronizzazioni SGI"
```

- [ ] **Step 4 — Helper** in `tasks.py`:

```python
def log_sgi_change(*, run_id, azione, document_code, revision_old="", revision_new="", note="", origine="auto"):
    from procedure_refresh.models import SgiSyncLog
    return SgiSyncLog.objects.create(
        run_id=run_id, azione=azione, document_code=document_code,
        revision_old=revision_old, revision_new=revision_new, note=note, origine=origine)
```

- [ ] **Step 5 — Migration:** `... makemigrations procedure_refresh` → `0007_sgisynclog`. Run test → PASS.

- [ ] **Step 6 — Admin + view + url + template + subnav:** `sync_log_list` (gate `_can_manage`, ultime 500 righe, filtro `?azione=`), rotta `admin/sync-log/`, template tabellare, voce subnav «Log sync». Test: GET 200 per manager, redirect per non-manager.

- [ ] **Step 7 — Run + Commit:** `feat(procedure_refresh): log append-only sincronizzazioni SGI + pagina admin`.

---

### Task 3: Sync aggiorna revisioni dei doc in presa visione + scrive log + badge nuova-rev

**Files:**
- Modify: `django_app/procedure_refresh/management/commands/import_sgi_da_share.py` (`filter_auto_safe`)
- Modify: `django_app/procedure_refresh/tasks.py` (`run_sgi_auto_sync`, `sgi_sync_now` path scrive log)
- Modify: `django_app/procedure_refresh/views.py` (`document_list` annota badge nuova-rev)
- Modify: `django_app/procedure_refresh/templates/procedure_refresh/pages/document_list.html`
- Test: `django_app/procedure_refresh/tests.py`

**Interfaces:**
- Consumes: `log_sgi_change`, `SgiSyncAction` (Task 2).
- Produces: `filter_auto_safe` include update-rev su doc PV; `run_sgi_auto_sync` scrive `SgiSyncLog`; context `document_list` con `doc.badge_nuova_rev` (revision_new o None).

- [ ] **Step 1 — Test rosso** (`AutoSyncSafeSubsetTests`): un doc PV esistente con una revisione più recente sulla share è nel sottoinsieme SAFE (prima era escluso); un doc con nome fallback resta escluso.

```python
def test_update_rev_su_doc_presa_visione_e_safe(self):
    from procedure_refresh.management.commands.import_sgi_da_share import filter_auto_safe
    doc = ProcedureDocument.objects.create(code="MT CN 06", title="Manuale",
        is_active=True, requires_acknowledgement=True)
    ProcedureRevision.objects.create(document=doc, revision_code="20",
        revision_date=date(2026,1,1), effective_date=date(2026,1,1),
        source_type=SourceType.FILESERVER, source_path="C:/s/MT.pdf", file_name="MT.pdf", is_current=True)
    cand = [{"code": "MT CN 06", "revision": "21", "title": "Manuale", "fallback": False,
             "path": "C:/s/MT21.pdf", "file_name": "MT CN 06 Rev.21.pdf",
             "document_type": "MT", "category": ""}]
    safe, excluded = filter_auto_safe(cand)
    self.assertEqual([c["code"] for c in safe], ["MT CN 06"])
```

- [ ] **Step 2 — Run** → FAIL (attualmente escluso perché `requires_acknowledgement`).

- [ ] **Step 3 — Implementazione `filter_auto_safe`:** un candidato è SAFE se nome riconosciuto (`not fallback` and not `disambiguated_from`) e (codice nuovo OR `_doc_is_import_child(doc)` OR è un **update di revisione** — la revisione candidata non esiste ancora e `_rev_int(cand) > _rev_int(current_db_rev)`). Resta escluso solo il rischio-nome. (Aggiungi helper interno che confronta la revisione candidata con la corrente DB.)

- [ ] **Step 4 — Run** → PASS.

- [ ] **Step 5 — Test log nel task** (`SgiSyncNowViewTests` o nuovo): dopo `run_sgi_auto_sync(force=True)` con un candidato nuovo/updated (mock scan), esiste una riga `SgiSyncLog` con l'azione giusta e `origine="auto"`.

- [ ] **Step 6 — Implementazione `run_sgi_auto_sync`:** genera `run_id` (da `pr_sgi_last_sync` counter o timestamp passato), per ogni candidato applicato scrivi `log_sgi_change` con NUOVO_DOC / NUOVA_REVISIONE (confronta rev pre/post upsert); per i missing del drift scrivi DOC_SPARITO. `sgi_sync_now` usa `origine="manuale"` (passa il flag al task).

- [ ] **Step 7 — Badge nuova-rev:** in `document_list`, per i doc con una riga `SgiSyncLog` NUOVA_REVISIONE negli ultimi `PROCEDURE_REFRESH_NUOVA_REV_BADGE_GIORNI` (default 30) esponi `badge_nuova_rev = revision_new`; il template mostra `⟳ nuova Rev.X`. Test: doc con log recente → context ha il badge; con log vecchio → no.

- [ ] **Step 8 — Run + Commit:** `feat(procedure_refresh): sync aggiorna e segnala le nuove revisioni dei documenti in presa visione + badge`.

---

### Task 4: Documenti nella Bacheca (categoria virtuale) + sensibilità + document_open

**Files:**
- Create: `django_app/procedure_refresh/bacheca.py` (`documento_e_sensibile`, `build_procedure_group`)
- Modify: `django_app/procedure_refresh/views.py` (`document_open`)
- Modify: `django_app/procedure_refresh/urls.py` (`documenti/<rev_pk>/apri/`)
- Modify: `django_app/dashboard/views_bacheca.py` e `views_home_portale.py` (append gruppo virtuale)
- Test: `django_app/procedure_refresh/tests.py`, `django_app/dashboard/tests_bacheca.py`

**Interfaces:**
- Consumes: `ProcedureDocument`, `ProcedureRevision`.
- Produces: `documento_e_sensibile(doc) -> bool`; `build_procedure_group(legacy_role_id, is_admin, preview_limit=None) -> dict | None` (forma `{category, items, total, more}` con item dict `{title, description, kind, kind_label, href, open_in_new_tab}`); view `document_open(request, rev_pk)`.

- [ ] **Step 1 — Test rosso `documento_e_sensibile` + builder:**

```python
class BachecaProcedureTests(TestCase):
    def test_builder_esclude_sensibili(self):
        from procedure_refresh.bacheca import build_procedure_group
        d1 = ProcedureDocument.objects.create(code="MT CN 10", title="Pubblico", is_active=True, escludi_dal_rag=False)
        ProcedureRevision.objects.create(document=d1, revision_code="1", revision_date=date(2026,1,1),
            effective_date=date(2026,1,1), source_type=SourceType.SHAREPOINT,
            source_url="https://x/", file_name="a.pdf", is_current=True)
        d2 = ProcedureDocument.objects.create(code="MT CN 11", title="Roster sensibile", is_active=True, escludi_dal_rag=True)
        ProcedureRevision.objects.create(document=d2, revision_code="1", revision_date=date(2026,1,1),
            effective_date=date(2026,1,1), source_type=SourceType.SHAREPOINT,
            source_url="https://y/", file_name="b.pdf", is_current=True)
        group = build_procedure_group(legacy_role_id=None, is_admin=False)
        titles = {i["title"] for i in group["items"]}
        self.assertTrue(any("MT CN 10" in t for t in titles))
        self.assertFalse(any("MT CN 11" in t for t in titles))
```

- [ ] **Step 2 — Run** → FAIL (import error).

- [ ] **Step 3 — `bacheca.py`:** `documento_e_sensibile(doc)` = `doc.escludi_dal_rag or _keyword_denylist(doc.code, doc.title)` (riusa i pattern da settings, stessa logica di `ai_assistant.services._sgi_excluded_by_keyword`; se non riusabile pulito, replica minimale leggendo `settings`). `build_procedure_group`: prende i `ProcedureDocument` attivi con revisione corrente, esclude i sensibili, costruisce item `{title: "CODE Rev.X — Titolo", description: category, kind: "url", kind_label: "Documento", href: reverse("procedure_refresh:document_open", args=[rev.pk]), open_in_new_tab: True}`; ritorna dict con una `HubLinkCategory`-like leggera (namedtuple/oggetto con `name/slug/icon`) o `None` se vuoto.

- [ ] **Step 4 — Run** → PASS.

- [ ] **Step 5 — Test `document_open`:** SharePoint → 302 a source_url; fileserver con path fuori root → 404; documento sensibile → 404. (Per lo stream fileserver usa un file temporaneo sotto una root fittizia impostata in `settings` via `override_settings`.)

- [ ] **Step 6 — `document_open`:** `@login_required`; carica `ProcedureRevision` per `rev_pk`; se `documento_e_sensibile(rev.document)` → `Http404`; se sharepoint e source_url → `redirect(source_url)`; se fileserver → valida `source_path` con helper `_safe_sgi_pdf(path)` (risolve sotto `PROCEDURE_REFRESH_SGI_SHARE_ROOT`, esiste, .pdf) → `FileResponse(open(path,'rb'), content_type="application/pdf")`, altrimenti 404.

- [ ] **Step 7 — Aggancio dashboard:** in `views_bacheca.bacheca` e `views_home_portale` (preview), dopo aver costruito i gruppi, appendi `build_procedure_group(role_id, is_admin, preview_limit)` se non `None`. Test in `dashboard/tests_bacheca.py`: la bacheca contiene il gruppo «Procedure SGI» con il documento pubblico e non quello sensibile.

- [ ] **Step 8 — Run + Commit:** `feat(procedure_refresh): documenti procedura consultabili in Bacheca (esclusi i sensibili) + apertura file-server via stream`.

---

### Task 5: Docs + wrap-up

- [ ] **Step 1:** `CHANGELOG.md` [Unreleased] → voce unica «lista unica + sync segnala + Bacheca» (isola dal WIP concorrente: backup working tree, stage su HEAD, commit, restore).
- [ ] **Step 2:** `README.md` riga `procedure_refresh` + blocco details (modello `SgiSyncLog`, consultazione in Bacheca).
- [ ] **Step 3:** `... manage.py check --settings=config.settings.test` pulito; suite `procedure_refresh` + `dashboard` verdi; migration `0007` applicata a dev.
- [ ] **Step 4:** aggiorna memoria `procedure_refresh_v2_done.md`. Commit docs.

## Self-Review

- Spec coverage: Parte 1 → Task 1; Parte 2 (aggiorna+segnala+log) → Task 2+3; Parte 3 (Bacheca+visibilità+open) → Task 4; docs → Task 5. ✔
- Nessun placeholder: codice test/impl concreto nei task. ✔
- Type consistency: `log_sgi_change`/`SgiSyncAction`/`build_procedure_group`/`documento_e_sensibile`/`document_open` coerenti tra i task. ✔
