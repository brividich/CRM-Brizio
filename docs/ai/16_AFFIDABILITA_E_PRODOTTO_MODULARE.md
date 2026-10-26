# Affidabilità e prodotto modulare — analisi del 25/10/2026

Analisi in sola lettura del codice su `main` (`d02b5dc3`). Tre parti: (A) punti critici di affidabilità, (B) quanto il portale è scomponibile in un prodotto per più aziende, (C) proposta di prodotto con wizard di configurazione, più (D) la tutela della proprietà intellettuale. Percorsi relativi a `django_app/` salvo diversa indicazione. I conteggi vengono da grep e sono approssimati.

---

## Sintesi

- Il portale è **affidabile nelle integrazioni HTTP** (tutte le ~55 chiamate `requests` hanno un timeout; SMTP, LDAP e SNMP pure), ha watchdog del qcluster, backup completo e una CI. I punti deboli sono altrove: **SQL Server è l'unico punto di guasto** di tutto (dati, cache, sessioni, coda), **le query del web non hanno timeout**, **di notte nessuno viene avvisato** e **nessuno controlla il sito da fuori**.
- Come prodotto, oggi **nessuna app si può togliere**: `INSTALLED_APPS` e `config/urls.py` sono statici, le migrazioni legano `core ↔ anagrafica ↔ assets` in un blocco unico, il "toggle moduli" non viene letto da nessuno e ci sono **4 registri moduli incoerenti**. I mattoni per diventarlo però esistono già (registro permessi autodiscover, `acl_bootstrap` per app, ACL v2 per route, navigazione da DB che tollera URL mancanti, `MODULE_REGISTRY` con `depends_on` nel wizard di deploy).
- Il modello HR è ricco e in buona parte già parametrico (`SkillMatrixConfig`, `ConfigSicurezzaOperativa`, `AssenzeImpostazioniHR`, cataloghi in DB), ma alcune regole chiave sono **nel codice**: la mansione di rischio si aggancia **per nome** dal testo legacy, le durate delle assenze sono costanti, i profili assenze e l'approvatore DPI si ricavano **dal nome del ruolo**, esistono **due definizioni di "team"**.
- **Brevetto:** in Europa il software "in quanto tale" non è brevettabile (art. 52 CBE); serve un effetto tecnico ulteriore, difficile da sostenere per un gestionale. La tutela realistica è diritto d'autore + segreto commerciale + marchio. **Attenzione al bando Buone Pratiche (PEC entro il 31/10/2026):** se si vuole tentare un brevetto, la relazione tecnica inviata può valere come divulgazione e distruggere la novità. Vedi parte D.

---

## A. Affidabilità: punti critici

Gravità: **A** alta, **M** media, **B** bassa. Le voci con ✔ sono state verificate a mano sul codice.

### A1. Da correggere subito (poche righe, effetto grande)

| # | Problema | Dove | Rimedio |
|---|---|---|---|
| 1 ✔ A | Token Graph richiesto con MSAL **senza timeout e dentro un lock**: se login.microsoftonline è lento, ogni thread Waitress che usa Graph resta in coda dietro al primo | `core/graph_utils.py:60-70`; stesso schema in `core/m365_graph.py:92` | `timeout=` a `ConfidentialClientApplication`, lock con `acquire(timeout=…)`; non mettere `result` intero nel messaggio d'errore |
| 2 ✔ A | **Query del web senza timeout**: `DB_QUERY_TIMEOUT` vale 0, solo il qcluster lo porta a 300. Una query bloccata tiene occupato uno dei 24 thread anche dopo che IIS ha tagliato a 4 minuti | `config/settings/base.py:662`, `deployment/start_qcluster.ps1:178` | `DB_QUERY_TIMEOUT=60` anche per il web (env di prod) |
| 3 ✔ A | **Allarmi muti 14 ore al giorno**: `MONITORING_ALERT_QUIET_START_HOUR=18`, `END=8`. Anche i FAIL gravi non mandano mail di notte | `config/settings/base.py:214-215` | Le ore silenziose valgano solo per WARN; FAIL (DB, qcluster, disco, backup) sempre |
| 4 A | **Nessuna sonda esterna del sito**: `/healthz` e `/readyz` esistono ma nessuno li chiama da fuori. Gli allarmi partono da task del qcluster via SMTP: se cade uno dei due, silenzio | `config/urls.py:33-34`; solo `restore-host.ps1:620` li usa | Attività schedulata sul modello di `deployment/watch_qcluster.ps1` che chiama `/readyz` ogni minuto e manda mail (meglio da un'altra macchina) |
| 5 ✔ A | **Upsert anomalie non atomico**: UPDATE, poi INSERT se nessuna riga, poi `SELECT TOP 1 id FROM anomalie ORDER BY id DESC`. Con due salvataggi contemporanei l'id restituito può essere quello dell'altro | `anomalie/views.py:3048-3088` (riga 3086) | Un solo `transaction.atomic` con `OUTPUT INSERTED.id` e `UPDLOCK` sulla lettura iniziale (`:3031`) |
| 6 ✔ M | **Wizard: il passo "moduli visibili" fallisce sempre** in silenzio: usa `key`/`value` ma `SiteConfig` ha `chiave`/`valore` | `setup_wizard/views.py:622`, `core/models.py:956` | Correggere i nomi; ma vedi B2: il flag non è comunque letto da nessuno |
| 7 M | **Task di riallineamento con timeout 600 > retry 180 e senza lock**: il broker lo riconsegna mentre gira ancora, due esecuzioni parallele creano adempimenti doppi | `anagrafica/services/riallineamento.py:284` | Lock con `cache.add`, come già in `elearning_import.py:207` |
| 8 M | **Errori 500 solo su file**, log ruotati per 5 giorni; nessun `ADMINS`/`mail_admins`, nessun aggregatore | `config/settings/base.py:1058` | Handler che crea un `Issue` in `monitoring` (o mail) al primo 500 di un tipo, con dedup |

### A2. Strutturali (da pianificare)

- **A — SQL Server fa tutto.** Una sola istanza `default` contiene dati, tabelle legacy, cache (`DatabaseCache`, `config/settings/prod.py:94-102`), sessioni, broker django-q, lockout di axes e coda automazioni. Se cade il DB cadono insieme login, ACL, cache e coda. L'alias `legacy` non esiste, quindi `monitoring/health.py:161` dà sempre SKIPPED. Rimedio: alta disponibilità lato SQL (AlwaysOn o log shipping) e, a medio termine, sessioni e cache fuori dal DB. La cache contiene anche ~10k embedding RAG (`MAX_ENTRIES=50000`): ogni `set` fa un COUNT di cull su una tabella grossa e appesantisce i backup → spostare gli embedding in una tabella propria.
- **A — I test girano solo su SQLite** (`config/settings/test.py:25-30`), mentre il codice ha ~70 rami `vendor ==` e ~57 frammenti specifici di SQL Server (`TOP`, `ISNULL`, `READPAST`). Quei rami non sono mai testati in CI. Rimedio: job notturno con SQL Server in container.
- **M — SQL grezzo fuori dall'ORM**: ~320 `cursor.execute`/`connections[` in ~60 file (automazioni/services 40, assenze/_helpers 31, dashboard 26, anomalie 24, admin_portale/_helpers 23). È la principale fonte di bug di concorrenza (vedi A1.5) e il principale ostacolo alla portabilità su altri DB.
- **M — Coda automazioni "almeno una volta"**: `recover_stale_processing_events` (`automazioni/services.py:863-891`) rimette in coda gli eventi rimasti in lavorazione. Se un worker muore dopo aver mandato la mail, la mail parte due volte. Rimedio: chiave di idempotenza per azione (evento + nodo) registrata prima dell'invio.
- **M — Esecuzioni perse in silenzio**: django-q con `catch_up=False` salta i job persi durante un fermo; `detect_missed_jobs` produce solo un WARN. Rimedio: dopo il riavvio, elenco dei job persi in Centrale comando con "esegui ora".
- **M — Trigger SQL sulle tabelle legacy** (`sql/trg_assenze_automation_after_*.sql`, `trg_tickets_automation.sql`): se il trigger fallisce, fallisce l'INSERT dell'assenza o del ticket.
- **M — Graph senza retry/backoff/circuit breaker** e chiamate sincrone nelle view (`rentri/views.py:120-188`, `rilevazione_incidenti/views.py:338-375`, `assenze/views/_helpers.py:124-191`); `_graph_headers`/`_graph_base_url` ridefiniti in 5 moduli con due implementazioni MSAL. Rimedio: un solo client Graph con gestione 429/`Retry-After`.
- **M — Ollama nel thread web** con timeout 180 s (`base.py:300`), vicino al limite IIS di 240 s.
- **M — Eccezioni inghiottite**: ~235 `except …: pass` silenziosi (core 45, anagrafica 38, admin_portale 23, anomalie 18). Il security-gate blocca solo quelli nuovi. Rimedio graduale: `logger.debug(..., exc_info=True)` partendo da `core/views.py` (16), `anomalie/views.py` (14), `hub_tools/views.py` (11), `core/context_processors.py` (7).
- **M — Query a ogni pagina**: `core/context_processors.py:766-777` fa un COUNT grezzo non in cache sulle assenze più il count delle notifiche a ogni render. Rimedio: cache per utente di 60 s.
- **M — Segnali di scadenza N+1** dentro il `save()` (`anagrafica/segnali_scadenze.py:188-194`, `dpi/segnali_scadenze.py:38-67`).
- **M — Due `.env`** (persistente e copia della release, `config/env_config.py:27-45`): una chiave assente nel persistente viene presa dalla copia vecchia. ~255 letture env in `base.py` e ~278 `getattr(settings, …)` nel codice, senza validazione all'avvio salvo `validate_deployment`. Rimedio: un `check` di sistema Django per le chiavi critiche.
- **M — Migrazioni**: 776 (anagrafica 204, assets 153, core 95), numeri duplicati in anagrafica (0071, 0076, 0087, 0090, 0117), tasks 0032, gestione_carichi_macchina 0004; 10 merge. Rimedio: squash periodico di anagrafica e assets (serve anche per la parte B).
- **B — Log di Waitress senza rotazione** (`waitress_stdout.log`, `deployment/setup_wizard.py:4155`). **Backup del log solo 07-21** (`base.py:741`): di notte la perdita dati possibile arriva a ~10 ore; staging sullo stesso host.
- **B — Dimensioni**: 15 view oltre 2.000 righe (le maggiori `anagrafica/views/dipendenti.py` 5.877, `formazione.py` 5.643, `automazioni/views/regole.py` 5.505, `anomalie/views.py` 5.136) e 42 funzioni oltre 250 righe (`_build_action_suggestions` 1.912, `asset_detail` 1.285). Copertura test minima su admin_portale (4 file per ~2.900 righe di view utenti) e tickets (5).
- **Igiene**: nella root del checkout ci sono file non tracciati con dati personali (xlsx/csv) e `ssl/localhost.key`. Non sono in git, ma vanno tolti dalla cartella di lavoro.

### A3. Ordine consigliato

1. Settimana 1: A1.1–A1.4 (timeout MSAL, `DB_QUERY_TIMEOUT`, ore silenziose solo per WARN, sonda esterna). Sono configurazione e poche righe.
2. Settimana 2: A1.5–A1.8 (upsert anomalie, wizard, lock riallineamento, errori 500 → Issue).
3. Mese 1: CI notturna su SQL Server; idempotenza della coda automazioni; client Graph unico.
4. Trimestre: piano HA di SQL Server; cache ed embedding fuori dalla `DatabaseCache`; riduzione del SQL grezzo nelle app più esposte (anomalie, assenze).

---

## B. Scomponibilità: dove siamo

### B1. Dimensioni

36 app, ~435k righe Python (escluse test e migrazioni), ~190k di test. Le grandi: anagrafica 89k (~136 modelli), assets 65k (~80), core 48k (~55), security 42k (~56), automazioni 27k.

### B2. Cosa impedisce di installare un modulo sì e uno no

1. **Migrazioni intrecciate** (il vincolo più duro, verificato): `core/0081` dipende da `anagrafica/0177`, `core/0095` da `assets/0001`; `anagrafica` dipende da assets, dpi, sistema_gestione; `assets` da anagrafica, tickets, contatori, schede_sicurezza; `dati_bi` da 5 app. Anello centrale non separabile oggi: **core ↔ anagrafica ↔ assets**, che si trascinano dpi, sistema_gestione, gestione_specifiche, tickets, contatori e schede_sicurezza.
2. **FK tra app**: `core.Postazione → assets.Asset` (`core/models.py:559`); anagrafica → assets ×5, dpi ×3; assets → anagrafica ×13; security → assets ×6; attrezzature e gestione_carichi_macchina → tasks.
3. **Shell che punta ad app opzionali**: `core/templates/core/base.html` (ai_assistant, monitoring), `topnav.html` (`assenze_car_dashboard`, `ai_assistant:chat`, `anagrafica:mia_scheda`), context processor `monitoring` obbligatorio, `core/context_processors.py:583` importa `assenze.views`, middleware obbligatori di setup_wizard, twofa, monitoring e notizie; mappe di path di anomalie e assenze in `core/middleware.py:18,41-49`.
4. **URL tutti inclusi senza condizioni** (`config/urls.py:27-88`), 8 app montate su prefisso vuoto: rischio di collisioni.
5. **Registri centrali scritti a mano** invece che per app: guide (`core/guide_moduli/__init__.py`), report (`core/report_centro/contenuti/`), scadenze (`dashboard/scadenze_providers.py:473`), widget (`dashboard/views.py:836`), sorgenti automazioni (`automazioni/source_registry.py:56`), tool AI (`ai_assistant/tools.py`, 5.4k righe, importa 23 app).
6. **Quattro registri moduli che non si parlano** ✔: `deployment/setup_wizard.py:120-226` (`MODULE_REGISTRY`, 22 voci, `depends_on` sbagliati: anagrafica dipende davvero da assets/dpi/sistema_gestione, tasks ha FK verso assets), `hub_tools/views.py:577-618` (15 voci), `setup_wizard/views.py:603-623` (12 voci), `core/module_registry.py` (solo etichette; `feature_flags` ed `enabled_by_default` mai letti). Il flag `module_visible_*` è letto solo dalle due pagine che lo scrivono: **è cosmetico**.
7. **Import a livello di modulo** verso app non kernel: `admin_portale.decorators` (usato da 7 app), `automazioni.managed_flows.event_flow` e `system_runlog` (8 app), `tasks/forms.py:19 → attrezzature`.

Attenuante: quasi tutti gli altri import tra app sono *lazy* (dentro funzioni), e la navigazione da DB già gestisce `NoReverseMatch` (`core/context_processors.py:335`).

### B3. Cosa è cablato per Novicrom

- **Branding** (in gran parte già parametrico via `SiteConfig`/env ma con default Novicrom): ~400 occorrenze di "novicrom", ~44 domini `cnovicrom.local`/`@novicrom.*`, ~90 percorsi UNC e host (`\\pclogsys\…`, `C:\PortaleNovicrom\…`), host Entra Proxy in `config/settings/prod.py:40`, residui "BrizioHUB" (11), wizard di deploy con DC, app pool e nomi zip fissi.
- **Dominio di business** (il vero ostacolo multi-cliente): PART 145 / EN 9100 ~530 occorrenze (assets 244); codici SGI "MOD.nnn" ~820, anche nel nome delle app (`timbri` = "Registro Timbri MOD.130") e in template Excel a celle fisse (`tasks/vrf_template/MOD_073_VRF_Rev10.xlsx`); normativa italiana (D.Lgs 81/08, 152/2006, 138/2024, RENTRI); nomi di reparti e lavorazioni; `contatori` pensato per Canon/Kyocera; ~1.300 righe sulle tabelle legacy SQL Server (`utenti`, `ruoli`, `pulsanti`, `anagrafica_dipendenti`, `capi_reparto`, `ordini_produzione`).
- **Integrazioni configurate ma non dietro un'interfaccia**: URL Graph costruiti a mano in 17 file di 10 app; `ldap3` importato direttamente in 7 file; `send_mail` diretto in 9 file (il resto passa da `core.email_utils`, bene); nessuna interfaccia per il provider AI.

### B4. Modello HR: regole fisse da rendere scelte

La catena oggi è:

```
AnagraficaDipendente (mansione TESTO, reparto TESTO)  ← tabella legacy
 ├─ DipendenteAnagraficaAziendale → AreaAziendale → Reparto (caporeparto / responsabili)
 ├─ DipendenteRuoloOperativo (N, principale/secondario/ad interim) → RuoloOperativo ─riporta_a→ RuoloOperativo
 │     ├─ profili_permessi → AccessGroup → RuoloPermessoModulo (ACL)
 │     ├─ RuoloQualifica → TipoQualifica;  TipoVisitaMedica.ruoli_operativi
 │     └─ CompetenzaSkm (mansione lavorativa) → AbilitazioneMacchina (I/L/U/O)
 │             └─ mansioni_rischio → Mansione (DVR)
 ├─ Mansione (DVR) agganciata PER NOME (services/mansionario.mansione_per_nome)
 │     ├─ dpi_richiesti / visite_richieste / TrainingRequirementRule
 │     ├─ EsposizioneRischio → FattoreRischio → visite, DPI, corsi
 │     └─ ProdottoChimico.mansioni (SDS)
 └─ Override individuali (+/−)
```

Regole oggi nel codice (anagrafica salvo diversa indicazione):

| Regola | Dove |
|---|---|
| Persona → mansione di rischio **per nome**, non per FK (rinomina gestita da `nomi_precedenti`) | `models.py:645`, `services/mansionario.py:197` |
| Un solo ambito alimenta il «Ruolo aziendale», campo testo singolo | `models.py:361`, `services/ruoli_sync.py` |
| Ore di formazione per rischio 8/12/16, rinnovo 60 mesi | `models.py:641-642` |
| Le mansioni di rischio si sommano da tutte le fonti | `services/mansionario.py:13-17` |
| Ordine fisso per trovare il capo (eccezione → area → reparto → organigramma) | `services/capo_team.py`, `reparto_canonico.py:100-157` |
| **Due "team" diversi**: per organigramma (ACL) e per perimetro reparto/area (capo); li unisce l'interruttore `capi.regola_unica_attiva` | `core/permessi/team.py`, `services/capo_team.py:220` |
| Scala competenze fissa a 4 livelli I<L<U<O, gate I→L fisso | `models_skillmatrix.py:31-45,166-171` |
| Una sola «Responsabilità del reparto» per reparto | `models_skillmatrix.py:268` |
| Profili assenze dal **nome** del ruolo («amministraz», «caporepart», «car») | `assenze/views/_helpers.py:745-797` |
| Durate assenze costanti (permesso 30 min–8 h, ferie a giornate, flessibilità 9–10 h max 2/settimana) | `assenze/constants.py:33-38`, `_helpers.py:1076-1129` |
| Approvazione ferie a due livelli oltre 10 giorni, con indirizzo aziendale fisso | pacchetto `automazioni/packages/au_assenze_unico_branch_per_tipo…json` |
| Approvatore DPI = ruolo che si chiama «preposto» | `dpi/flusso.py:21-35`, `core/caporeparto_utils.py:109` |
| Monte ore CCNL 24 h / 3 anni; numerazione corsi `YYNNN` | `services/formazione_ccnl.py:29`, `services/formazione_numerazione.py` |
| Elenchi chiusi nei `choices` (contratto, categorie mansione, fattori di rischio, tipi ticket IT/MAN, ruoli NC CC/CAR) | `models.py:1268`, `models_rischi.py:38`, `tickets/models.py:13-60`, `anomalie/models.py:7` |

Già parametrico (da esporre nel wizard così com'è): `SkillMatrixConfig`, `ConfigSicurezzaOperativa`, `AssenzeImpostazioniHR`, `FlessibilitaImpostazioni`, `DPIImpostazioni`, `SicurezzaImpostazioni`, `TicketImpostazioni`, `CategoriaTicket` con SLA, `TipologiaContratto`/`LivelloContrattuale`, chiavi `SiteConfig` (`permessi.sistema_ruoli_attivo`, `capi.regola_unica_attiva`, `anomalie_nc_chiusura`, `assets_wo_overdue_days`…), preset di ruolo in `core/permessi/preset.py`.

Mancanze di dominio per altri clienti: **non esistono turni di lavoro** né **timbrature/presenze** (`timbri` è il registro dei timbri qualità), né il livello **Sede** sopra il reparto.

---

## C. Proposta: «HUB Platform», prodotto modulare

### C1. Principio

Non riscrivere. Si estrae dal portale attuale un **kernel** e una serie di **pacchetti**, in un repository separato, con la strategia "strangler": Novicrom resta il primo cliente e gira sulla stessa base, il suo profilo diventa il primo **Profilo cliente** (dati e configurazione, non codice).

Tre strati, ognuno con la sua forma di variabilità:

| Strato | Cosa contiene | Come varia tra clienti |
|---|---|---|
| **Kernel** | identità e login, ACL v2, navigazione, audit, notifiche, mail, monitoraggio, backup, wizard, Centro guide e report, motore automazioni | non varia; si configura |
| **Pacchetti funzionali** | Persone, Assenze, HSE, Asset/IT, Qualità/SGI, Produzione, SOC, AI | si installano o no (`INSTALLED_APPS` + URL + migrazioni) |
| **Profili e rule pack** | modello organizzativo, regole HR, normativa per paese, settore (es. Aerospace PART 145), codici modulo SGI, branding | dati versionati caricati dal wizard |

### C2. Pacchetti proposti

| Pacchetto | App | Dipende da | Da sciogliere prima |
|---|---|---|---|
| **K0 Kernel** | core, admin_portale, hub_tools, setup_wizard, monitoring, twofa, dashboard (shell), notizie, automazioni (motore) | — | spostare `admin_portale.decorators`, `event_flow`, `system_runlog` nel kernel; FK `Postazione → Asset` via collegamento opzionale; migrazioni core 0081/0095; link della shell condizionati |
| **K1 Persone** | anagrafica (anagrafica, struttura, ruoli, organigramma), fornitori | K0 | FK verso assets/dpi/sistema_gestione; sotto-pacchetto separabile «HSE-HR» (formazione, sorveglianza, mansioni di rischio) |
| **P-Assenze** | assenze, checklist_operativa, suggestion_corner | K1 | tabella legacy `capi_reparto`, SharePoint opzionale, regole da `TipoAssenza` |
| **P-HSE** | dpi, diario_preposto, rilevazione_incidenti, schede_sicurezza, procedure_refresh, rentri (solo IT) | K1 | ciclo dpi ↔ anagrafica; SharePoint come fonte di verità opzionale |
| **P-Asset/IT** | assets, planimetria, tickets, contatori | K0 (+K1 facoltativo) | ciclo assets ↔ tickets ↔ contatori; PART 145 estratto in add-on |
| **P-SOC** | security | P-Asset/IT | 48 import verso assets |
| **P-Qualità/SGI** | sistema_gestione, gestione_specifiche, report_conformita, glossario_tecnico, timbri | K1 | codici MOD.nnn in rule pack |
| **P-Produzione** | anomalie, tasks/KICK-OFF, attrezzature, gestione_carichi_macchina | K1, P-Asset | tabella legacy `ordini_produzione`, template VRF a celle fisse |
| **Add-on** | ai_assistant, dati_bi, Aerospace (PART 145) | i pacchetti che servono | tool AI e viste BI registrati per app |

### C3. Lavori di fondo, in ordine

1. **Un solo registro moduli** (`core/module_registry.py` evoluto): ogni pacchetto dichiara app, URL, dipendenze, versione, tier di licenza, voci di menu, guide, report, scadenze, widget, sorgenti automazioni e tool AI. Pilota `INSTALLED_APPS` (lista da env `HUB_MODULES` o da file di licenza) e gli `include` in `config/urls.py`. Gli altri tre registri spariscono.
2. **Kernel pulito**: decorators, event_flow e runlog in core; segnali di dominio ("persona creata", "mansione cambiata", "asset dismesso") pubblicati dal kernel e ascoltati dai pacchetti, al posto degli import diretti.
3. **Migrazioni per pacchetto**: baseline squash per pacchetto, con le dipendenze solo verso il basso (pacchetto → K1 → K0). Le FK verso pacchetti opzionali diventano tabelle di collegamento nel pacchetto che le usa (es. `assets.PostazioneAsset` invece di `core.Postazione.asset`).
4. **Autodiscover** per guide, report, scadenze, widget, sorgenti automazioni, tool AI (`<app>/hub_module.py`), sul modello di `core/permessi/registro.py`.
5. **Adapter per le integrazioni**: `Directory` (AD/LDAP, Entra ID, solo locale), `DocumentStore` (SharePoint, cartella di rete, DB), `MailTransport` (SMTP, Graph), `LegacyDB` (SQL Server legacy o nessuno), `AIProvider` (Ollama, nessuno). Il wizard sceglie l'implementazione.
6. **Togliere il SQL grezzo** dai pacchetti che devono girare anche senza le tabelle legacy (assenze, anomalie, admin_portale).
7. **Rule pack e profili** come fixture versionate e firmate (vedi C5).

### C4. Wizard di configurazione

Il wizard di oggi configura solo l'infrastruttura. Si aggiunge una seconda metà, «**Modello aziendale**», che produce un **Profilo cliente** (JSON versionato, esportabile e confrontabile) e lo applica: cataloghi iniziali, `SiteConfig`, oggetti `*Impostazioni`, pacchetti di automazione, preset ACL. Ogni scelta è modificabile in seguito dalle Impostazioni, con traccia nell'audit.

**1. Azienda e pacchetti**
- Nome istanza, logo, colori, dominio mail, mittenti e caselle funzionali (oggi `assenza@…` è nel pacchetto automazioni).
- Paese e normativa: Italia (D.Lgs 81/08, RENTRI, CCNL) / altro paese UE (rule pack da fornire).
- Settore: generico / metalmeccanico / aerospazio (attiva add-on PART 145) / servizi.
- Pacchetti da installare, con dipendenze calcolate dal registro unico.
- Sistemi di gestione certificati: ISO 9001, 14001, 45001, 27001, EN 9100 → creano gli `AmbitoRuolo` e le viste preset.

**2. Struttura organizzativa**
- Livelli: Reparto / Reparto + Area / Sede + Reparto + Area (serve il modello Sede).
- Chi è il capo: responsabile della struttura / gerarchia dei ruoli / mista con eccezioni (default: mista con `capi.regola_unica_attiva` acceso, così i due "team" coincidono).
- Più responsabili per struttura con potere di approvazione: sì/no (oggi i co-responsabili sono solo informativi).
- Organigrammi paralleli per norma: nessuno / 45001 / 27001 / altri.

**3. Ruoli, mansioni, competenze** (la regola ruolo → mansione → competenze)
- Ruoli per persona: uno / più con un principale / più alla pari.
- Ruolo → mansione lavorativa: 1:1 / 1:N / N:N.
- Mansione di rischio: collegata con FK al catalogo (default per i clienti nuovi) / testo libero (solo Novicrom finché non si migra).
- Origine delle mansioni di rischio: dalla scheda / dalle mansioni lavorative / da entrambe in somma / solo DVR manuale.
- Proposte di mansione dal portale da confermare all'HSE: sì/no.
- Il ruolo assegna i ruoli del portale (ACL): sì/no (mai amministratore).
- Scala delle competenze: numero di livelli, nomi, soglia operativa, gate formativo (nessuno / primo passaggio / ogni livello), soglia "uomo solo", cadenza refresh. Richiede di trasformare `LivelloSkm` da costante a tabella.

**4. Sicurezza sul lavoro**
- Classi di rischio e ore: ASR B/M/A 8/12/16 h, rinnovo 60 mesi / personalizzate (oggi costanti).
- Visita mancante al cambio mansione: avviso / deroga (max N giorni) / blocco (già in `ConfigSicurezzaOperativa`).
- Scadenza visite quando cambia il requisito: la più vicina / la nuova / la vecchia.
- Approvatore DPI: capo / preposto / magazzino / combinazioni (flag sul ruolo al posto del nome «preposto»).
- SDS legate a mansione, reparto o entrambi.
- Cataloghi di partenza: fattori di rischio, tipi di visita, qualifiche (RSPP, RLS, antincendio, primo soccorso).

**5. Assenze e orari**
- Tipi di assenza attivi e regole di durata (nuovo modello `TipoAssenza` al posto di `constants.py`): minimo e massimo, a ore o a giornate, flessibilità sì/no con orari e massimo settimanale.
- Livelli di approvazione: uno / due oltre N giorni / due sempre; secondo approvatore (HR, ufficio, ruolo).
- Il dipendente può scegliere un altro capo: sì/no. Escalation al superiore se il capo è assente: sì/no, dopo N giorni.
- Chi salta l'approvazione o inserisce per altri: azioni della matrice ACL, non nomi di ruolo.
- Calendario: ore per giornata, sabato, patrono, chiusure; soglia di anonimato nelle statistiche (oggi 5, fissa).
- Monte ore CCNL e tipologie contrattuali da catalogo.

**6. Altri domini**
- Ticket: tipi e categorie da catalogo (oggi `TextChoices` IT/MAN), SLA per categoria, livelli di escalation.
- Non conformità: ruoli del ciclo, chi chiude, preavviso azioni (oggi 2 giorni fissi).
- Numerazione documenti come modello (`{AA}{NNN}`, `{AA}E{n}`, protocollo attestati).
- Codici modulo SGI: tabella codice → documento, al posto dei "MOD.nnn" nel codice.

**7. Integrazioni**
- Directory (AD / Entra ID / solo locale), documenti (SharePoint / cartella / DB), mail (SMTP / Graph), DB legacy (sì/no), AI (Ollama locale / nessuna). Ogni scelta con il test di connessione già presente nel wizard.

### C5. Idee che danno valore al prodotto

1. **Motore di conformità derivata.** Il nucleo distintivo è già qui: dalla posizione organizzativa di una persona (struttura, ruoli, mansioni, esposizioni) il sistema **deriva** obblighi di formazione, visite, DPI, SDS e permessi, con override motivati e tracciati, e ricalcola tutto quando la persona cambia (adempimenti di cambio mansione). Va isolato come servizio del pacchetto Persone con una regola dichiarativa unica (`TrainingRequirementRule` generalizzata a "requisito" di qualunque tipo) e una spiegazione leggibile ("perché devo fare questo corso").
2. **Profilo cliente come dato versionato.** Tutto ciò che il wizard sceglie è un documento JSON con versione, firma e diff. Si può simulare ("cosa cambia se attivo la regola unica dei capi?": persone che cambiano capo, permessi che si aggiungono o tolgono) prima di applicarlo. La simulazione esiste già in piccolo per i permessi.
3. **Rule pack normativi** separati dal codice: "Italia 81/08 + ASR", "RENTRI", "PART 145", "ISO 45001". Aggiornarli diventa una release di dati, non di codice.
4. **Licenza per pacchetto**: file di licenza firmato con pacchetti e tier (il campo `tier` esiste già in `MODULE_REGISTRY`); il registro unico lo legge all'avvio.
5. **Installazione per cliente, non multi-tenant**: un'istanza e un database per cliente, on-premise o ospitata. Coerente con l'architettura attuale (IIS/Waitress/SQL Server) e con la riservatezza dei dati HR e sanitari. Il multi-tenant su DB condiviso costerebbe una riscrittura dell'ACL e dei dati sanitari senza un vero ritorno.
6. **Portabilità del DB**: con il SQL grezzo ridotto, supportare anche PostgreSQL abbassa il costo d'ingresso per clienti senza licenza SQL Server.
7. **Kit di onboarding dati**: import guidati (dipendenti, organigramma, competenze, asset) con mappatura colonne e anteprima, a partire dagli import già presenti.

### C6. Roadmap indicativa

| Fase | Contenuto | Esito verificabile |
|---|---|---|
| 0 (2 settimane) | Correzioni A1; registro moduli unico in sola lettura che descrive le dipendenze reali; grafo delle dipendenze generato in CI | `depends_on` veri, nessuna nuova dipendenza inversa (gate CI) |
| 1 (1-2 mesi) | Kernel pulito, link della shell condizionati, autodiscover dei registri, URL condizionali | un'istanza con solo K0 + K1 si avvia e passa i test |
| 2 (2-3 mesi) | Migrazioni per pacchetto, FK opzionali come collegamenti, adapter integrazioni | installazione da zero di qualunque combinazione ammessa |
| 3 (2 mesi) | Wizard «Modello aziendale», Profilo cliente, `TipoAssenza`, scala competenze a tabella, mansione di rischio per FK | Novicrom ricreata dal suo profilo; un secondo profilo di prova diverso |
| 4 | Rule pack, licenze, documentazione di prodotto, primo cliente pilota | installazione presso terzi |

---

## D. Tutela della proprietà intellettuale

Non è un parere legale: va verificato con un consulente in proprietà industriale prima di qualunque passo.

- **Brevetto.** L'art. 52 della Convenzione sul brevetto europeo (e l'art. 45 del Codice della proprietà industriale) esclude i programmi per elaboratore "in quanto tali" e i metodi commerciali. L'EPO concede brevetti su invenzioni attuate per elaboratore solo se c'è un **effetto tecnico ulteriore** (es. controllo di macchine, miglior uso delle risorse di calcolo). Un sistema che deriva obblighi HR e di sicurezza da regole organizzative è, nella sostanza, un metodo organizzativo: la probabilità di ottenere un brevetto valido è bassa. Parti con più aggancio tecnico, da far valutare: l'acquisizione dati dalle macchine (OPC UA/MTConnect, SNMP) collegata alla manutenzione, e il riconoscimento automatico di documenti (referti, verbali, planimetrie).
- **Novità e bando.** Un brevetto richiede che l'invenzione non sia stata resa accessibile al pubblico prima del deposito. La relazione tecnica del bando Buone Pratiche (PEC entro il **31/10/2026**) ha tra i criteri la "trasferibilità" e le buone pratiche premiate di solito vengono pubblicate. **Se si vuole tenere aperta la strada del brevetto, decidere prima dell'invio** cosa descrivere (risultati e benefici, non il funzionamento interno) o depositare prima una domanda di priorità.
- **Titolarità.** Il software sviluppato da un dipendente nello svolgimento delle mansioni appartiene al datore di lavoro (art. 12-bis L. 633/1941). La decisione su prodotto, licenza e tutela è quindi dell'azienda; conviene formalizzarla, insieme ai contributi esterni.
- **Tutele realistiche, cumulabili.**
  - *Diritto d'autore* sul codice e sulle banche dati: nasce con la creazione; per la prova di data si usa il Registro pubblico speciale per i programmi per elaboratore (SIAE) o un deposito con data certa.
  - *Segreto commerciale* (artt. 98-99 CPI, direttiva UE 2016/943): richiede misure di riservatezza effettive — accesso al repository limitato, accordi di riservatezza, distribuzione ai clienti solo in forma compilata o con licenza che vieti la decompilazione.
  - *Marchio* per il nome del prodotto (oggi «NOVICROM HUB» è legato al nome aziendale: per un prodotto conviene un nome proprio, da verificare e registrare all'EUIPO).
  - *Licenze delle dipendenze*: prima di distribuire, inventario delle licenze (`pip-licenses`) per verificare che nessuna dipendenza imponga obblighi incompatibili con una licenza commerciale.
