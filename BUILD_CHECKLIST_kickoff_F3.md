# Checklist operativa condivisa — KICK-OFF F3

Ultimo aggiornamento: 2026-09-02 — Codex

Branch condiviso: `feature/kickoff-f3-fruibilita`  
Worktree Codex: `C:\Dev\pn-kickoff-f3`  
Spec sorgente: `C:\Dev\Portale Novicrom\BUILD_SPEC_kickoff_F3.md`

## Regole di coordinamento

- Aggiornare questa checklist nello stesso commit del blocco completato.
- Prima di iniziare una voce, indicare `IN CORSO — <agente>` e verificare `git status`/ultimi commit.
- Non lavorare contemporaneamente sugli stessi file; le sessioni F3 restano sequenziali.
- Un commit separato per ciascuna sessione/fase della spec.
- Non modificare `vrf_catalog.py`, modelli/campi DB, dipendenze, ACL globali o aree fuori `django_app/tasks/` salvo la documentazione obbligatoria.
- Non modificare i test esistenti: i nuovi test F3 vanno nei tre file dedicati previsti dalla spec.

## Sessione 1 — RECON e coordinamento

- [x] Verificato `Project.save()` e retry `IntegrityError`.
- [x] Verificato `ProjectKickoffForm.clean()` e match `__iexact`.
- [x] Verificati scope ACL, shell context e `_can_manage_project()`.
- [x] Verificati readiness, `da_gestire`, tab e datalist sale.
- [x] Verificata parità attesa con normalizzatore `attrezzature`.
- [x] Annotate le divergenze in `RECON.md` temporaneo.
- [x] Creato branch/worktree dedicato.
- [x] Creata questa checklist condivisa.
- Stato: COMPLETATA — Codex.

## Sessione 2 — Fase A: identità normalizzata

- [x] `tasks/identity.py`: normalizzatori puri.
- [x] `Project.save()`: normalizzazione come primo blocco, retry invariato.
- [x] Data migration idempotente, bulk/chunk, report collisioni.
- [x] `identity_suggest`: scope ACL, limite 20, JSON 401/403.
- [x] Datalist Cliente/P/N in `project_create.html`.
- [x] `tests_identity.py`: parità, save, retry, ACL endpoint, migration.
- [x] Test mirati Fase A verdi (11 test).
- Stato: COMPLETATA — Codex.

## Sessione 3 — Struttura view nuove

- [x] Creato `views_projects.py` e inserita `identity_suggest`; le altre due view arriveranno nelle rispettive fasi.
- [x] Nessuna estrazione `view_helpers.py` necessaria per la view Fase A.
- [ ] Registrare le tre route in ordine sicuro.
- [ ] `manage.py check` verde.
- Stato: DA FARE — non assegnata.

## Sessione 4 — Fase B: registro azioni

- [ ] `action_register.py` con tre collector difensivi e ordinamento unico.
- [ ] View `project_actions` e filtro `closed=1`.
- [ ] Template `project_actions.html` senza CSS inline.
- [ ] `tests_action_register.py`, incluso budget query.
- [ ] Test mirati Fase B verdi.
- Stato: DA FARE — non assegnata.

## Sessione 5 — Fase C: panoramica commessa

- [ ] View/route `project_overview` come landing commessa.
- [ ] Template `project_overview.html` senza CSS inline.
- [ ] Cinque tab e conteggio azioni aperte.
- [ ] Aggiornare tutti gli `active` delle view con tab progetto.
- [ ] Ridirezionare gli ingressi generici alla Panoramica.
- [ ] `tests_project_overview.py`.
- [ ] Test mirati Fase C verdi.
- Stato: DA FARE — non assegnata.

## Sessione 6 — Chiusura funzionale

- [ ] Suite `tasks` completa verde.
- [ ] Django `check` verde.
- [ ] `makemigrations --check --dry-run` verde.
- [ ] `secret_hygiene_check` verde.
- [ ] Verifica manuale dei quattro scenari della spec.
- [ ] Documentazione, changelog e registri agente aggiornati.
- Stato: DA FARE — non assegnata.

## Sessione 7 — UI Passata 1

- [ ] Hero piatta e adozione token `--hub-*`.
- [ ] Rimozione scala `--ts-radius-*` nel perimetro previsto.
- [ ] Verifica pagine richieste in tema chiaro/scuro.
- Stato: DA FARE — non assegnata.

## Sessione 8 — UI Passata 2

- [ ] Restyle card portfolio e rimozione copertine/gradienti.
- [ ] `annotate_open_action_counts(projects_qs)` senza N+1.
- [ ] Test query budget su almeno 10 commesse.
- Stato: DA FARE — non assegnata.

## Sessione 9 — UI Passata 3

- [ ] Spostare CSS inline in `tasks.css`, un componente/commit per volta.
- [ ] Grep finali della spec tutti conformi.
- [ ] Suite `tasks` finale verde.
- Stato: DA FARE — non assegnata.

## Note e decisioni condivise

- Il decorator `task_permissions_required()` è HTML-oriented. L'endpoint `identity_suggest` deve usare un gate dedicato che restituisca JSON `401`/`403` senza cambiare il comportamento delle view esistenti.
- Il pulsante esplicitamente denominato `Gantt` nel footer portfolio resta diretto al piano; il nome commessa diventerà l'ingresso generico alla Panoramica nella Fase C.
- `RECON.md` è temporaneo e non va committato; le divergenze durature sono replicate qui.

## Registro verifiche

- 2026-09-02 — Codex — Fase A: 11 test `tasks.tests_identity` verdi; 5 regressioni esistenti su `Project`/creazione kickoff verdi; `manage.py check`, `makemigrations --check --dry-run`, `secret_hygiene_check` e `git diff --check` verdi.
