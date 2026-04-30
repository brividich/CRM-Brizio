# Gestione Attrezzatura

Patch 1 introduce la fondazione indipendente del modulo `attrezzature`, pensata per sostituire progressivamente il file Excel legacy `Avanzamento attrezzi.xls` senza perdere tracciabilita o codificare assunzioni fragili.

## Scopo business

Gestione Attrezzatura governa lo stato operativo degli attrezzi/fixture necessari alla produzione. Il modulo mantiene record normalizzati (`Attrezzatura`), storico avanzamenti, note operative, task nativi e batch di import legacy.

Il modulo e indipendente da KICK-OFF: puo essere usato direttamente da `/attrezzature/` e puo essere richiamato dalle pagine Kickoff Activity tramite il pannello embedded e i servizi di integrazione.

## Mapping Excel legacy

| Excel | Campo normalizzato |
| --- | --- |
| Codice | `Attrezzatura.codice` |
| Particolare | `Attrezzatura.part_number` |
| N. Pezzi | `numero_pezzi` |
| Avanzamento | `avanzamento_percentuale` |
| Note e consegna | `note_consegna` |
| Data consegna | `data_consegna_prevista` |
| Descrizione | `descrizione` |
| Note Rocco | `note_rocco` |
| Ordine | `stato` e `ordine_visuale` |

`Particolare` significa Part Number / P/N ed e lo stesso identificativo logico usato dal modulo KICK-OFF.

I campi OG non guidano relazioni, deduplica, workflow o business logic. Vengono preservati solo dentro `AttrezzaturaImportRow.payload_originale_json` per audit e ricostruzione storica.

## Pipeline import

Il servizio `attrezzature.services.excel_import` accetta `.xlsx` con `openpyxl` e `.xls` solo se l'ambiente ha dipendenze compatibili (`pandas/xlrd`), legge `ATTREZZI` quando esiste, rileva header sporchi nelle prime righe, normalizza alias, conserva il payload originale e calcola `row_hash`.

La preview dry-run non scrive record. La conferma crea `AttrezzaturaImportBatch`, `AttrezzaturaImportRow`, attrezzature sicure e storico avanzamenti.

Matching, senza usare mai `codice` da solo:

1. `codice + part_number + descrizione`
2. `codice + part_number`
3. `codice + descrizione` solo se il P/N e vuoto

Match multipli o righe non sicure vengono classificate come warning e restano manuali.

## Workflow task

`AttrezzaturaTask` rappresenta l'esecuzione operativa nativa del modulo. Le task possono nascere prima dell'esistenza di un record `Attrezzatura`, per esempio "Creare nuovo attrezzo per P/N X" da una futura Kickoff Activity.

I servizi in `workflow.py` gestiscono avanzamento, disponibilita, conferma pronta produzione, completamento/blocco/riapertura task e generazione deduplicata dei controlli ritardo.

## Confine KICK-OFF

`attrezzature.services.kickoff_integration` non importa modelli KICK-OFF. Usa riferimenti esterni plain string: `external_kickoff_id` e `external_kickoff_activity_id`.

Regola di ownership:

- `KickoffActivity` = contesto/richiesta business
- `AttrezzaturaTask` = record operativo di esecuzione
- `Attrezzatura` = source of truth per stato, avanzamento e readiness

KICK-OFF potra mostrare o mirrorare stato per UX, ma non deve diventare owner del workflow attrezzature.

## Embedded panel

La partial `attrezzature/components/embedded_panel.html` e renderizzabile dalla pagina `/attrezzature/embedded-preview/` e usa `build_kickoff_attrezzatura_context()`.

Il contesto include attrezzature collegate al P/N, task aperte e collegate, refs KICK-OFF esterne e summary disponibilita/readiness/ritardi. Quando il contesto fornisce `action_url`, la partial espone azioni POST per creare task di verifica/creazione, creare una bozza attrezzatura, collegare un tool, aggiornare avanzamento, cambiare disponibilita, aggiungere note, completare/bloccare task e confermare pronta produzione.

Patch 2 integra questa partial nel dettaglio Activity KICK-OFF (`/tasks/<id>/`) quando e disponibile un P/N dal kickoff o dai dati extra dell'attivita. Le POST del pannello terminano in `tasks:attrezzature_action`, ma la view resta solo bridge HTTP: ogni mutazione passa da `attrezzature.services.workflow` o `attrezzature.services.kickoff_integration`.

Il dettaglio Activity non crea record Attrezzatura su semplice GET. Per le Activity salvate con tipo riconoscibile (`creazione_attrezzo`, `verifica_disponibilita`, `aggiorna_avanzamento`, `controllo_ritardo`, `conferma_pronta_produzione`) il salvataggio di creazione/modifica prova a creare o riusare il corrispondente `AttrezzaturaTask` usando refs esterne plain string.

## Navigazione e permessi

La topbar non viene hardcodata. Il comando `python manage.py create_attrezzature_nav` crea/aggiorna in modo sicuro:

- pulsanti legacy per il modulo `attrezzature`;
- righe `permessi` legacy per tutti i ruoli, deny-by-default quando mancano;
- permission code ACL v2 canonici;
- binding route -> permission per le pagine `/attrezzature/` e per il bridge embedded KICK-OFF;
- `NavigationItem` topbar con label `Gestione Attrezzatura`, route `attrezzature:list`, section `topbar`, code `gestione-attrezzatura` e permission `attrezzature.attrezzature.view`;
- accessi ruolo default.

Permessi preparati: `attrezzature_view`, `attrezzature_add`, `attrezzature_change`, `attrezzature_import`, `attrezzature_export`, `attrezzature_task_view`, `attrezzature_task_manage`, `attrezzature_link_kickoff`, `attrezzature_confirm_ready_production`.

Mapping ACL v2:

| Permesso legacy/Django | Permission code ACL v2 |
| --- | --- |
| `attrezzature_view` | `attrezzature.attrezzature.view` |
| `attrezzature_add` | `attrezzature.attrezzature.create` |
| `attrezzature_change` | `attrezzature.attrezzature.edit` |
| `attrezzature_import` | `attrezzature.import.import` |
| `attrezzature_export` | `attrezzature.attrezzature.export` |
| `attrezzature_task_view` | `attrezzature.tasks.view` |
| `attrezzature_task_manage` | `attrezzature.tasks.manage` |
| `attrezzature_link_kickoff` | `attrezzature.kickoff.link` |
| `attrezzature_confirm_ready_production` | `attrezzature.attrezzature.confirm` |

Accessi default applicati dal comando:

- `admin`, `amministrazione`: tutti i permessi Gestione Attrezzatura;
- `caporeparto`: view, create, edit, conferma pronta produzione, task view/manage, link KICK-OFF;
- `qualita`: view, edit, conferma pronta produzione, task view/manage, link KICK-OFF;
- altri ruoli: nessun accesso di default, modificabile da Accessi/ACL canonico.
