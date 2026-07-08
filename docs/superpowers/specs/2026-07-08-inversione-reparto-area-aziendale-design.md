# Inversione gerarchia Reparto ↔ Area Aziendale

**Data**: 2026-07-08
**Modulo**: `django_app/anagrafica` (+ tocco mirato a `dashboard/views_home_portale.py`)
**Branch**: `feature/skill-matrix-mod187` (branch di prod)
**Stato**: design approvato a voce in sessione, in attesa di revisione spec

## Contesto e problema

Oggi in `anagrafica/models.py` (introdotto con la migration `0034_area_aziendale_reparto_hierarchy`, v1.1.1) la gerarchia è:

- **AreaAziendale** (padre): `nome`, `descrizione`, `colore`, `is_active` — raggruppamento di alto livello (es. "Produzione", "Uffici").
- **Reparto** (figlio, FK `area_aziendale` → AreaAziendale): `nome`, `descrizione`, `caporeparto_legacy_id`, `is_active` — unità operativa specifica (es. "Assemblaggio", "Magazzino"), db_table storica `anagrafica_areaaziendale`.

Nella realtà organizzativa è il contrario: il **Reparto è il contenitore** (es. "UT" — Ufficio Tecnico) e l'**Area aziendale è la sua sotto-articolazione** (es. IN1, IN2, IT, DM). Il caporeparto è responsabile di un intero reparto e, transitivamente, di tutte le aree aziendali che contiene — questo deve abilitare filtri tipo "tutti i dipendenti del caporeparto X" risalendo dal dipendente al reparto. Caso reale noto: solo per UT esiste una distinzione tra le aree "qualità" (sotto un dirigente) e l'area "produzione" (sotto un altro dirigente) — quindi il modello deve poter esprimere, in modo opzionale, un responsabile anche a livello di singola area.

I dati oggi presenti in "Aree & Reparti" sono nella forma vecchia (sbagliata) e **possono essere cancellati senza problemi** — nessun dato reale da migrare 1:1.

## Decisioni prese con l'utente

- **Reparto** diventa il livello padre (nessun genitore); **AreaAziendale** diventa il livello figlio (FK verso Reparto). Un Reparto può avere più Aree aziendali; un'Area aziendale appartiene a un solo Reparto.
- Il **caporeparto** resta su Reparto (invariato: guida `RepartoCapoMapping`, assenze, automazioni, digest — tutti verificati compatibili).
- Nuovo campo **opzionale** `responsabile_legacy_id` su AreaAziendale, per coprire casi come UT (aree qualità/produzione con dirigenti diversi). Solo metadato in questa fase: non alimenta automazioni/mapping finché la direzione non decide come comporre le due responsabilità.
- **Colore** si sposta da AreaAziendale a Reparto (Reparto è ora il raggruppamento "a banda" nella UI di gestione).
- Migration a "taglio netto": si cancellano i record esistenti (forma sbagliata) prima di alterare lo schema, niente rename-in-place come fece la 0034.
- **Assegnazione Area aziendale sul dipendente**: rimandata, la direzione deve ancora decidere la UX. Vedi "Fase 2" più sotto per le opzioni proposte.
- **Auto-fill `area_aziendale_nome`** sul dipendente: oggi deriva il nome del genitore da un Reparto singolo (deterministico). Dopo l'inversione un Reparto ha più figli, quindi non è più derivabile in questo modo — smette di autopopolarsi in Fase 1. Il caporeparto continua ad autopopolarsi normalmente (resta univoco per Reparto).

## Modello dati (Fase 1)

**Reparto** (nuovo padre, es. "UT")
- `nome` (unique), `descrizione`, `is_active`, `created_at` — invariati
- `colore` — **nuovo qui** (spostato da AreaAziendale)
- `caporeparto_legacy_id` — invariato
- **rimosso**: campo/FK `area_aziendale`

**AreaAziendale** (nuovo figlio, es. "IN1", "IN2", "IT", "DM")
- `nome` (unique), `descrizione`, `is_active`, `created_at` — invariati
- **nuovo**: `reparto` — FK verso Reparto, `on_delete=SET_NULL`, `null=True, blank=True` (ammette aree "orfane" temporaneamente, stesso pattern di oggi per i reparti senza area)
- **nuovo**: `responsabile_legacy_id` — `IntegerField`, `null=True, blank=True`, opzionale, solo metadato in questa fase
- **rimosso**: `colore` (eredita quello del Reparto nella UI)

## Superficie di codice impattata

Verificata con un audit esaustivo (agenti paralleli + verifica manuale mirata) su tutti i file che referenziano `AreaAziendale`/`Reparto`/`.area_aziendale` nel repo — non solo i grep testuali su "reparto" (la maggior parte sono campi liberi scollegati, es. CAPA, incidenti, ticket, timbri, tabella legacy `anagrafica_dipendenti`).

### Va modificato (`needs_code_change`)

| File | Nota |
|---|---|
| `anagrafica/models.py` | Schema Reparto/AreaAziendale (il cambiamento centrale) + nuova migration |
| `anagrafica/views.py` | `_sync_aziendale_from_reparto` (~5413, usa `rep.area_aziendale`), `reparto_autofill_json` (~2005-2020, usa `r.area_aziendale.nome`), `aree_list` (~5434-5453), CRUD `area_aziendale_*`/`area_*` (~5458-5634, kwarg `area_aziendale=`), `organigramma` (~12825-12896, raggruppa per AreaAziendale) |
| `anagrafica/templates/anagrafica/pages/aree_list.html` | Redesign banda invertita (Reparto in alto, Aree sotto) |
| `anagrafica/templates/anagrafica/pages/organigramma.html` | Raggruppamento per Reparto invece che per AreaAziendale |
| `anagrafica/templates/anagrafica/pages/dipendente_detail.html` | `rep.area_aziendale.nome` (riga ~850), `aziendale.area_aziendale_nome` + didascalie "Auto dal reparto" (righe ~894-963) |
| `anagrafica/templates/anagrafica/pages/dipendente_create.html` | `rep.area_aziendale.nome` (riga ~166) nella select Reparto |
| `anagrafica/tests.py` | `OrganigrammaTests` (righe 2706-2749): `setUpTestData` crea `AreaAziendale(colore=...)` + `Reparto(area_aziendale=...)`, e le asserzioni sulla view organigramma assumono la gerarchia attuale |
| `anagrafica/management/commands/import_dipendenti_xlsx.py` | Sezione "3b) Sync reparto → area aziendale" (righe 570-592): `select_related("area_aziendale")` + `rep.area_aziendale.nome` |
| `dashboard/views_home_portale.py` | Tile "planimetria" (~401): `AreaAziendale.objects.count()` etichettato "reparti" → va `Reparto.objects.count()` |

### Compatibile ma dati da re-inserire (`data_reentry_only`)

Il codice resta strutturalmente valido (FK verso Reparto/AreaAziendale, o campo `DipendenteAnagraficaAziendale.area`/`area_aziendale_nome` non toccato), ma **i valori** cambiano di significato e vanno ricreati/riconfigurati da UI dopo il deploy:

`anagrafica/forms.py` (dropdown "Reparto" sorgente `Reparto.objects`) · `anagrafica/models_formazione.py` (`RegolaObbligoFormazione.area` FK a AreaAziendale) · `anagrafica/models_rischi.py` (`EsposizioneRischio.area` FK a AreaAziendale) · `anagrafica/services/training_eligibility.py` (matching su `area_aziendale_nome` denormalizzato — **resta dormiente** finché non esiste l'assegnazione area del dipendente, vedi Fase 2) · `gestione_specifiche/models.py` (FK `Reparto` su `distribuzioni_specifiche`/`config_presa_visione`, **+ `NotificaConfig.reparto_in1`**: valore letterale `"IN1"` da riconfigurare, vedi sotto) · `gestione_specifiche/forms.py` · `anagrafica/templates/.../dipendenti_list.html` · `anagrafica/templates/.../matrice_competenze.html` · `anagrafica/templates/.../dipendenti_report.html` (colonne "Reparto (legacy)"/"Reparto (catalogo)") · `assenze/views.py` · `tasks/views.py` · `config/settings/base.py` · `hub_tools/templates/hub_tools/notifiche.html` (destinatario "per reparto")

### Compatibile, nessuna modifica (`compatible_no_change`)

Usano solo `Reparto.nome`/`Reparto.caporeparto_legacy_id` (invariati) o modelli distinti (es. `RepartoCapoMapping` in `core`, `OptioneConfig`): `anagrafica/models_mpq.py` (M2M `ProcessoQualificato.reparti`) · `anomalie/views.py` · `anagrafica/services/onboarding.py` · `admin_portale/views.py` · `anagrafica/management/commands/sync_reparto_capo_mapping.py` · `anagrafica/management/commands/import_mod128.py` · `anagrafica/management/commands/migra_formazione_export.py` · `anagrafica/tests_impostazioni_guard.py` · `anagrafica/tests_mpq.py` · `anagrafica/tests_skillmatrix_scadenzario.py` · `assenze/tests.py` · `gestione_specifiche/tests/test_distribuzione.py` · `gestione_specifiche/tests/test_models.py` · `tasks/forms.py` · `core/views.py` (`gestione_reparto`/`organigramma`/`rubrica`, tabella legacy raw SQL) · `core/views_capa.py` · `core/management/commands/sync_caporeparto_local_users.py` · `core/management/commands/bootstrap_caporeparto_locale.py` · `core/management/commands/send_caporeparto_morning_digest.py`

### Non correlato (`not_applicable`) — verificato per evitare falsi allarmi futuri

Circa 25 file (template di anagrafica, dpi, timbri, assets, admin_portale, rilevazione_incidenti, dashboard, gestione_carichi_macchina) usano un campo libero "reparto" scollegato dai due modelli (es. CAPA, timbri, incidenti, asset, tabella legacy `anagrafica_dipendenti`). Nessuna modifica necessaria. **Nota particolare**: `planimetria/templates/planimetria/pages/editor.html` ha un proprio concetto di "reparto" (zone disegnate su una planimetria, API `api_save_reparto`) — è **solo un'omonimia**, un modello completamente distinto, non toccare.

## Effetti collaterali noti da comunicare (non bloccanti per questa fase)

1. **`gestione_specifiche.NotificaConfig.reparto_in1`**: oggi filtra i dipendenti con `area == "IN1"` (valore che, nella vecchia gerarchia, era un `Reparto`). Dopo l'inversione "IN1" diventa un'`AreaAziendale` figlia di "UT" — il valore letterale nel campo continuerà a fare match testuale finché qualcuno non aggiorna il campo assegnato ai dipendenti, ma semanticamente andrà rivisto quando si affronta la Fase 2.
2. **`RegolaObbligoFormazione.area` e `EsposizioneRischio.area`** (FK a AreaAziendale): le righe esistenti puntano a record che verranno cancellati nel taglio netto — vanno ricreate dopo, scelta attesa e già concordata.
3. **Regole di formazione "per area aziendale"** (`training_eligibility.py`) restano dormienti (nessun match) finché non esiste un'assegnazione del dipendente a una specifica AreaAziendale — dipende dalla Fase 2.

## Fase 2 (rimandata — proposte per quando la direzione deciderà)

Oggi il dipendente ha un solo campo "Reparto" (dropdown, sorgente `Reparto.objects`). Tre opzioni per l'assegnazione fine quando servirà:

- **A — Cascata Reparto → Area aziendale** (opzione consigliata): si sceglie il Reparto, poi una seconda tendina (filtrata) mostra solo le Aree di quel Reparto; entrambi i valori salvati sul dipendente. Più esplicito, più lavoro UI/dati.
- **B — Solo Area aziendale**, con Reparto auto-derivato: si sceglie direttamente l'Area (es. "IN1"), il Reparto ("UT") si mostra in automatico come oggi mostra l'area. Un solo campo da compilare, ma non copre i Reparti senza sotto-articolazioni (andrebbe previsto un valore "generico" per quei casi).
- **C — Due campi indipendenti opzionali**: Reparto obbligatorio come oggi, Area aziendale facoltativa e slegata (nessuna cascata, nessun vincolo di appartenenza). Il più semplice da implementare, ma perde la garanzia strutturale "un'area appartiene a un solo reparto" nell'assegnazione del dipendente.

## Non in scope (questa fase)

- Assegnazione Area aziendale sul dipendente (Fase 2, sopra).
- Wiring del `responsabile_legacy_id` di AreaAziendale in `RepartoCapoMapping`/automazioni/digest.
- Riconfigurazione dati in `gestione_specifiche` (`reparto_in1`), `RegolaObbligoFormazione`, `EsposizioneRischio` — attesa, da fare da UI dopo il deploy.

## Test

- Riscrivere `OrganigrammaTests` in `anagrafica/tests.py` per la nuova gerarchia (Reparto padre, AreaAziendale figlia, colore su Reparto).
- Nuovi test CRUD per `area_aziendale_*`/`area_*` con i campi invertiti.
- Nessuna modifica ai test elencati in `compatible_no_change` (uso solo di `nome`/`caporeparto_legacy_id`).
- Seguire `docs/ai/06_TESTING_AND_QUALITY_GATES.md` per il checklist di version-bump (comportamento utente-visibile cambia: CHANGELOG + README obbligatori).
