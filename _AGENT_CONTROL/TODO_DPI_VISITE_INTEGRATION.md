# TODO — Integrazione DPI consegnati + Visite mediche nello spazio del dipendente

> Stato vivente del task. Aggiornato ad ogni step.
>
> **Piano completo**: `C:\Users\l.bova\.claude\plans\vectorized-floating-lampson.md`
> **Avviato**: 2026-05-21 · **Completato (impl. + test)**: 2026-05-21
> **Branch**: `main`

---

## Stato globale

- [x] Plan mode → piano approvato dall'utente
- [x] Esplorazione modelli/views (DPI, anagrafica, settings, storage)
- [x] Implementazione completa
- [x] Test (14/14 verdi)
- [x] Documentazione (CHANGELOG, README, AI docs)
- [ ] Quality gates finali + UI manual smoke test

Legenda stato: `[ ]` pending · `[~]` in corso · `[x]` completato · `[!]` bloccato.

---

## Riepilogo cosa è stato fatto

### Backend
- `config/settings/base.py` → `ANAGRAFICA_PRIVATE_ROOT` (default `media_private/`).
- `anagrafica/storage.py` → `PrivateAnagraficaStorage` (no URL pubblico).
- `anagrafica/models.py`:
  - Helper `_add_months` Python-only (sostituisce `dateutil.relativedelta` — il pacchetto NON è installato nel venv).
  - `DocumentoDipendente` (tipo: `DPI_CONSEGNA`/`VISITA_MEDICA_REFERTO`/`ALTRO`).
  - `TipoVisitaMedica` (durata_mesi, M2M `ruoli_operativi`).
  - `VisitaMedica` (esito, prescrizioni, referto FK opzionale; `save()` calcola `data_scadenza`).
  - `AnagraficaVisiteMedichePermission` (singleton, default `ADMIN`).
- `anagrafica/admin.py`: i 4 nuovi modelli registrati.
- `anagrafica/migrations/0018_documentodipendente_visitamedica.py` (auto-gen).
- `anagrafica/migrations/0019_seed_tipi_visita.py` (RunPython: 6 tipi seed, `obbligatoria=False`).
- `anagrafica/services/visite.py`: `stato_visite`, `tipi_visita_richiesti_per_dipendente`, `ultime_visite_per_tipo`, `visite_storico` (subquery `Max` SQL Server-safe).
- `anagrafica/services/dpi_ingresso.py`: `proposta_righe_iniziali`, `crea_consegne_iniziali`, `archivia_pdf_cumulativo` (atomic + fail-soft).
- `anagrafica/forms.py`: `VisitaMedicaForm` (con `referto_file` separato).
- `anagrafica/views.py`:
  - Helper `_can_view_visite_mediche`, `_parse_dpi_iniziali_post`, `_ensure_admin`.
  - Hook in `dipendente_create`: ruoli operativi multiselect + DPI iniziali (formset POST con prefisso `dpi_*`).
  - `dipendente_visita_add` / `_edit` / `_delete` (ACL: `_can_view_visite_mediche`; delete: solo admin).
  - `documento_dipendente_download` (FileResponse, ACL per tipo, audit).
  - `documento_dipendente_delete` (solo admin).
  - `dipendente_dpi_iniziali_proposti` (partial HTMX).
  - `impostazioni_permessi_save` salva anche `AnagraficaVisiteMedichePermission`.
  - `dipendente_detail` arricchito con: `dpi_consegna_doc_map`, `can_view_visite`, `visite_stato_list`, `visite_storico_list`, `tipi_visita_attivi`, `documenti_dipendente`, `visita_esiti`.
- `anagrafica/urls.py`: nuove route visite/documenti/htmx.
- `anagrafica/management/commands/send_visite_expiry_reminders.py`: dry-run testato OK.
- `anagrafica/templatetags/anagrafica_extras.py`: filtro `dictlookup` per template.
- `dpi/pdf.py`: `render_modulo_consegna_dpi[_multipla]` con reportlab (firma base64 → Image Platypus).
- `dpi/views.py::consegna_richiesta`: hook `_archivia_pdf_consegna` (idempotente, fail-soft).

### Templates
- `anagrafica/pages/dipendente_create.html`:
  - Multiselect "Ruoli operativi" (`ruoli_operativi_ids`, hx-get → htmx_dpi_iniziali).
  - Card "📦 DPI consegnati all'ingresso" con target `#dpi-iniziali-righe`.
- `anagrafica/partials/_dpi_iniziali_righe.html` (formset righe: `dpi_indici`, `dpi_consegnato_<i>`, `dpi_categoria_id_<i>`, `dpi_modello_id_<i>`, `dpi_taglia_id_<i>`, `dpi_quantita_<i>`).
- `anagrafica/pages/dipendente_detail.html`:
  - `{% load anagrafica_extras %}`.
  - Riga DPI: link `📄 PDF` se `dpi_consegna_doc_map|dictlookup:r.consegna.id`.
  - Nuova card "🏥 Visite mediche" con stato + storico + form add (gating `can_view_visite`).
  - Nuova card "📄 Documenti" (lista + scarica/elimina).
- `anagrafica/components/subnav.html`: aggiornato testo notice scheda dipendente.

### Test
14 nuovi test in `anagrafica/tests.py`, tutti OK:
- `VisitaMedicaScadenzaTests`: 12/24/0 mesi + is_scaduta/in_scadenza.
- `StatoVisiteServiceTests`: vuoto/ruoli/mancante/valida/scaduta.
- `DPIPDFRenderTests`: PDF bytes inizia con `%PDF`, >1000 bytes.
- `VisiteMedichePermissionTests`: superuser OK / user normale blocked.
- `DocumentoDipendenteDownloadACLTests`: referto 403/200 via RequestFactory (bypass middleware).
- `DPIIngressoServiceTests`: crea_consegne_iniziali OK, scadenza da vita_utile.

Comando: `python django_app\manage.py test anagrafica --settings=config.settings.test`.

---

## Estensione (2026-05-21, seconda iterazione)

Su richiesta dell'utente:
1. `/admin/anagrafica/tipovisitamedica/` rimanda ad `adminportale` (comportamento globale del progetto, non modificato).
2. Aggiunta **vista globale "Visite mediche"** `/anagrafica/visite-mediche/`:
   - View: `anagrafica.views.visite_mediche_dashboard` (gating `_can_view_visite_mediche`)
   - Template: `anagrafica/templates/anagrafica/pages/visite_mediche_dashboard.html`
   - URL name: `anagrafica:visite_mediche_dashboard`
   - Subnav: nuova voce "🏥 Visite mediche" tra "Ratei Ferie" e "Impostazioni"
   - Contenuto: KPI (scadute / in scadenza / totali / tipi attivi), tabella scadute o in scadenza con link a dipendente, copertura per tipologia (richiesti/coperti/mancanti calcolati su M2M ruoli), ultime 30 visite con link al referto.
   - Lookup nomi dipendenti: una sola query su `AnagraficaDipendente` (legacy SQL Server) costruisce una mappa `legacy_id → "Cognome Nome"`.
3. Link "Catalogo tipi" nella card "🏥 Visite mediche" della scheda dipendente cambiato da `admin:anagrafica_tipovisitamedica_changelist` (rediretto) a `anagrafica:visite_mediche_dashboard` ("📊 Vista globale").
4. Test: 2 nuovi (`VisiteMedicheDashboardTests`) — 403 per utente normale, 200 + content per superuser. Totale tests verdi: **16/16**.

## Limiti noti / debito

1. **`core.audit.log_action` riceve stringa**: nei nostri `log_action(..., f"…")` viene loggato come ERROR ma `core/audit.py:29` ha `dict(dettaglio or {})` che fallisce con stringa. È **bug pre-esistente** (anche `dpi.views.consegna_richiesta` lo passava stringa). Fail-soft non interrompe il flusso. Fix futuro: o passare dict ovunque, o rendere `log_action` tollerante a stringhe.

2. **`dateutil` NON è installato**: pre-esistente. `anagrafica/views.py:1275` ha `from dateutil.relativedelta import relativedelta` per le qualifiche — runtime fallirebbe se invocato. Per le visite mediche è stato evitato usando `_add_months`. Considerare aggiunta a `requirements.txt` o sostituzione anche in qualifiche.

3. **Categoria DPI ↔ ruolo operativo**: il filtro in `services/dpi_ingresso.categorie_obbligatorie_per_ruoli` accetta `ruoli_ids` come argomento futuro ma **non filtra** ancora: ritorna tutte le `CategoriaDPI.obbligatoria_mansionario=True`. Per filtrare per ruolo serve estendere schema `CategoriaDPI` con M2M `ruoli_operativi` (fase 2).

4. **Cartella `media_private/anagrafica/`**: in prod va creata con permessi corretti (IIS_IUSRS/IUSR non devono leggerla). Documentare nel `deployment/scripts/deploy-release.ps1` se non già coperto dalla cartella generale `media_private/`.

5. **UI manual smoke test**: non eseguito (richiede dev server + browser). Verifica suggerita:
   - `/anagrafica/dipendenti/nuovo/` → seleziona ruolo operativo → carda DPI si popola via HTMX.
   - Consegna DPI da `/dpi/` → PDF appare in scheda dipendente.
   - Registra visita medica → scadenza calcolata correttamente, referto scaricabile.

---

## Per riprendere il task da un'altra chat

1. Leggere `CLAUDE.md` (radice) per stili e vincoli.
2. Leggere questo file + `C:\Users\l.bova\.claude\plans\vectorized-floating-lampson.md`.
3. Eventuale Phase 2: filtro CategoriaDPI per ruolo operativo (M2M dedicato).
4. Eventuale Phase 2: data migration per assegnare i tipi visita seed ai ruoli (oggi M2M vuoto).
5. Per il bug `core.audit`: serve PR separata.
