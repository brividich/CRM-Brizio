# Collegamento anagrafica lavorativa ↔ nuova gerarchia Reparto/AreaAziendale (Fase 2)

**Data**: 2026-07-08
**Modulo**: `django_app/anagrafica` (form/viste/template anagrafica lavorativa del dipendente + `services/training_eligibility.py`)
**Branch**: `feature/skill-matrix-mod187` (branch di prod)
**Stato**: design approvato in sessione, in attesa di revisione spec

## Contesto e problema

Con [[2026-07-08-inversione-reparto-area-aziendale-design]] la gerarchia è stata invertita: `Reparto` è ora il contenitore di primo livello (con `caporeparto_legacy_id`), `AreaAziendale` la sua sotto-articolazione (FK `reparto`, `SET_NULL`). Quella spec rimandava esplicitamente a "Fase 2" l'assegnazione dell'Area aziendale al dipendente, perché un Reparto può avere più Aree e quindi non è più derivabile in automatico da un singolo Reparto.

Stato attuale verificato (questa sessione):
- `DipendenteAnagraficaAziendale.area` (CharField, label "Reparto", `models.py:1008`) è già collegato al catalogo `Reparto` per nome, con sincronizzazione di `caporeparto_legacy_id` via `_sync_aziendale_from_reparto` (`views.py:5412-5432`) — **funziona correttamente**, nessuna azione richiesta.
- La catena caporeparto → assenze (`assenze/views.py`: `_anagrafica_employee_ids_for_capo`, `_resolve_anagrafica_hr_effective_capo_ids`) usa solo `DipendenteAnagraficaAziendale.caporeparto_legacy_id` con fallback su `Reparto.caporeparto_legacy_id` — **già coerente** con la nuova gerarchia, nessun riferimento residuo alla vecchia. Nessuna azione richiesta.
- `DipendenteAnagraficaAziendale.area_aziendale_nome` (CharField, `models.py:1009-1015`) è **escluso dal form** (`forms.py:146`) e non viene scritto da nessun punto del codice dall'inversione in poi (nessun write-site trovato).
- **Bug concreto scoperto**: `services/training_eligibility.py:120-132` fa matching delle `TrainingRequirementRule` con target "area aziendale" (`models_formazione.py:458-461`, FK `anagrafica.AreaAziendale`) confrontando il nome contro `area_aziendale_nome` — che essendo sempre vuoto rende **silenziosamente inefficace ogni regola formativa scoped per area aziendale** dall'inversione in poi.
- `dipendente_detail.html:891-900` mostra "Area aziendale" in sola lettura (sempre "Non assegnata"); `dipendente_detail.html:955-959` ha un input readonly "autofill" ormai morto, con didascalia esplicita "Non assegnata automaticamente in questa fase".

## Decisioni prese con l'utente

- **Storage**: FK vera `area_aziendale` su `DipendenteAnagraficaAziendale` (non un CharField denormalizzato) — più robusto, integrità referenziale, e permette match per ID in `training_eligibility.py` invece che per nome.
- **UI cascading**: filtro client-side in JavaScript (nessuna chiamata HTMX/server aggiuntiva) — tutte le Aree aziendali attive raggruppate per Reparto vengono renderizzate una volta in pagina come blob JSON, e un piccolo script ricostruisce le opzioni della select "Area aziendale" quando cambia la select "Reparto".
- **Dove si modifica**: sia nel mini-form rapido "✏ Cambia reparto" (`dipendente_reparto_set`) sia nel form completo "Modifica dati aziendali" (`dipendente_anagrafica_aziendale_save`/`AnagraficaAziendaleForm`) — entrambi i punti oggi permettono di cambiare il Reparto, quindi entrambi devono permettere di impostare l'Area aziendale coerente.
- **Coerenza reparto↔area**: nessuna validazione bloccante lato utente. L'invariante ("l'Area aziendale assegnata deve appartenere al Reparto assegnato") è garantita centralmente da `_sync_aziendale_from_reparto`, che azzera silenziosamente un'Area incoerente (es. Reparto cambiato altrove, o JS disabilitato/manomesso) invece di rifiutare il salvataggio.
- **Dati storici / regole di formazione**: nessun backfill automatico dei dipendenti in questa fase (i dipendenti restano con `area_aziendale = NULL` finché non vengono riassegnati manualmente da UI). In compenso, questa fase include un management command di sola lettura che elenca le `TrainingRequirementRule` con target "area aziendale" oggi configurate, per dare visibilità su cosa aspetta una riassegnazione.

## Modello dati

`DipendenteAnagraficaAziendale` (`anagrafica/models.py`):
- **rimosso**: `area_aziendale_nome` (CharField, mai più scritto dall'inversione, dato sempre vuoto — rimozione sicura, nessuna perdita).
- **nuovo**: `area_aziendale = models.ForeignKey("anagrafica.AreaAziendale", null=True, blank=True, on_delete=models.SET_NULL, related_name="dipendenti_assegnati", verbose_name="Area aziendale")`.
- Migration additiva standard (no data migration necessaria, verificare comunque in dev/test che `area_aziendale_nome` sia vuoto ovunque prima di applicare in prod, per coerenza con la policy "nessuna perdita silenziosa").

## Backend

**`_sync_aziendale_from_reparto`** (`views.py:5412-5432`) — firma estesa:

```python
def _sync_aziendale_from_reparto(
    legacy_id: int, reparto_nome: str, *, area_aziendale_id: int | None = None, saved_by
) -> None:
```

Logica aggiunta: risolto il `Reparto` per nome (già esistente), se `area_aziendale_id` è valorizzato si verifica che l'`AreaAziendale` corrispondente esista, sia attiva e abbia `reparto_id` coincidente con il Reparto risolto; in caso contrario (area inesistente, disattivata, di un altro reparto, o reparto non risolto/vuoto) il valore salvato è `None`. Questa è l'unica funzione che scrive `area_aziendale`, chiamata da entrambi i punti di ingresso sotto — nessuna logica di validazione duplicata altrove.

**`dipendente_reparto_set`** (`views.py:3192-3236`): legge il nuovo `request.POST.get("area_aziendale")` (id), lo passa a `_sync_aziendale_from_reparto`.

**`dipendente_anagrafica_aziendale_save`** (`views.py:4026-4062`): `AnagraficaAziendaleForm` include ora `area_aziendale` come campo normale (ModelForm); dopo `obj.save()`, la chiamata esistente a `_sync_aziendale_from_reparto` passa anche `area_aziendale_id=obj.area_aziendale_id` per la correzione finale — stesso pattern "save grezzo poi correggi" già in uso per il caporeparto.

**`AnagraficaAziendaleForm`** (`forms.py:140-184`):
- tolto `area_aziendale_nome` dall'`exclude` (il campo sparisce, sostituito dalla FK) — `area_aziendale` resta escluso `False` di default, quindi Django lo genera come `ModelChoiceField`.
- in `__init__`, stesso trattamento già riservato a `area`/`ruolo_aziendale`: queryset limitato alle `AreaAziendale.objects.filter(is_active=True)` con inclusione del valore corrente anche se disattivato, widget `Select` con classe `dp-input`.

**`services/training_eligibility.py:120-132`**: il blocco "3) regole per area aziendale" passa da confronto testuale a confronto diretto sugli ID:

```python
area_ids = {r.area_id for r in rules if r.area_id}
if area_ids:
    ids.update(
        int(lid) for lid in DipendenteAnagraficaAziendale.objects
        .filter(area_aziendale_id__in=area_ids)
        .values_list("legacy_anagrafica_id", flat=True)
    )
```

## Frontend

**Dati condivisi in pagina** (`dipendente_detail` view + template): un blob JSON `aree_by_reparto` — mappa `{nome_reparto: [{id, nome}, ...]}` delle Aree aziendali attive, costruito una volta nella vista e serializzato in uno `<script type="application/json">` nel template. Una funzione JS condivisa `syncAreaAziendaleOptions(repartoSelectEl, areaSelectEl, currentAreaId)` ricostruisce le `<option>` di `areaSelectEl` leggendo dal blob in base al valore corrente di `repartoSelectEl`, invocata `on change` del select Reparto e una volta al caricamento pagina per entrambi i punti sotto.

**Mini-form "✏ Cambia reparto"** (`dipendente_detail.html:843-864`): aggiunta `<select name="area_aziendale">` accanto alla select `reparto`, popolata via JS, preselezionata su `aziendale.area_aziendale_id` se presente.

**Form completo "Modifica dati aziendali"** (`dipendente_detail.html:942-959`): il campo `area_aziendale` del form iterato (`{% for field in form_aziendale %}`) sostituisce l'input readonly morto; stesso script di cascading applicato al suo select `reparto` (campo `area`, già presente nel form).

**Riquadro sola lettura "Area aziendale"** (`dipendente_detail.html:891-900`): `aziendale.area_aziendale_nome` → `aziendale.area_aziendale.nome` (con `default:"—"` già presente nello stile del resto della card).

## Report regole di formazione per area

Nuovo management command in sola lettura, `anagrafica/management/commands/report_regole_formazione_area.py`: elenca le `TrainingRequirementRule` attive (`is_active=True`) con `area_id` valorizzato, con corso/piano collegato, nome area/reparto e conteggio dipendenti attualmente matchati tramite la nuova FK `area_aziendale`. Nessuna scrittura, solo stampa tabellare su stdout — pensato per dare visibilità immediata su quali regole aspettano una riassegnazione manuale dei dipendenti dopo il deploy.

## Non in scope (questa fase)

- Riassegnazione massiva/backfill delle Aree aziendali sui dipendenti esistenti (resta attività operativa da UI, dopo il deploy).
- Wiring di `AreaAziendale.responsabile_legacy_id` in automazioni/digest (già fuori scope nella spec di inversione).
- Riconfigurazione di `gestione_specifiche.NotificaConfig.reparto_in1` (già segnalato come effetto collaterale non bloccante nella spec di inversione, resta indipendente da questa fase).

## Test

- `_sync_aziendale_from_reparto`: area valida mantenuta, area incoerente (reparto diverso, disattivata, inesistente) azzerata silenziosamente, nessuna eccezione.
- `dipendente_reparto_set`: salvataggio combo reparto+area valida; combo incoerente salvata con area azzerata (no 500, nessun errore utente bloccante).
- `dipendente_anagrafica_aziendale_save` / `AnagraficaAziendaleForm`: stesso comportamento del punto sopra passando dal form completo; queryset limitato alle aree attive più il valore corrente.
- `training_eligibility`: regola con `area_id` matcha solo i dipendenti con `area_aziendale_id` uguale, non più per nome.
- Nuovo management command: output corretto su un dataset di test con almeno una regola per area e dipendenti assegnati/non assegnati.
- Seguire `docs/ai/06_TESTING_AND_QUALITY_GATES.md` per il checklist di version-bump (comportamento utente-visibile cambia: CHANGELOG + README obbligatori).
