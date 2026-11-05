# Scadenzario generale (`scadenzario`)

Lo scadenzario del portale: la pagina `/scadenze` (`dashboard.views_scadenze`) raccoglie le scadenze di tutti i moduli tramite i provider di `dashboard/scadenze_providers.py`; l'app `scadenzario` aggiunge:

- la fonte **Scadenze generiche** (ex app Flask «Scadenzario» sul NAS 10.0.0.222:8080, MySQL `scadenziario` su 10.0.0.7);
- il **pannello di gestione** che decide quali voci compaiono e chi le vede;
- gli **avvisi per mail** delle scadenze generiche;
- l'**import** dal vecchio database.

## URL

| URL | Nome | Cosa |
|---|---|---|
| `/scadenze` | `scadenze_globali` | Scadenzario globale (app `dashboard`): `?vista=mese` (predefinita, `&mese=AAAA-MM`, ±24 mesi), `agenda`, `elenco`; `?format=csv` / `ics` |
| `/scadenze/gestione/` | `scadenzario:gestione` | Pannello: albero voci, impostazioni, regole |
| `/scadenze/generiche/` | `scadenzario:elenco` | Elenco scadenze generiche (+ export Excel `?format=xlsx`) |
| `/scadenze/generiche/nuova/`, `<id>/`, `<id>/modifica/`, `<id>/rinnovo/` | `scadenza_*` | Attività, scheda, rinnovo con allegato |
| `/scadenze/generiche/categorie/` | `scadenzario:categorie` | Categorie |
| `/scadenze/generiche/avvisi/` | `scadenzario:avvisi` | Registro avvisi |

Rotte condivise (prefissi `/scadenze/gestione/` e `/scadenze/generiche/` in `_ACL_SHARED_PREFIXES`): i permessi si decidono nelle view. Voce di menu «Scadenzario» in alto (migrazione `0002`, solo se non esiste già una voce verso `scadenze_globali`).

## Chiavi e regole (`scadenzario/visibilita.py`)

Ogni voce ha il percorso `fonte` → `fonte|tipo` → `fonte|tipo|elemento` (`ScadenzaItem.source/kind/elemento`; l'elemento si normalizza con `slug`). Generiche: `generiche|cat-<id>|s<id>`.

- `VoceConfig(chiave, attiva, modalita)`: campi vuoti ereditano dalla voce superiore. `attiva=False` toglie la voce a tutti; `modalita=REGOLE` la mostra solo a chi è nelle regole (e agli amministratori del pannello).
- `RegolaVisibilita(chiave, ruolo_portale | ruolo_aziendale | persona_legacy_id, livello)`: vale per la voce e i discendenti. Ruolo del portale = `core.AccessGroup` (anche quelli dall'organigramma, `core.permessi.motore.ruoli_della_persona`); ruolo aziendale = `anagrafica.RuoloOperativo` ricoperto oggi (`core.permessi.team._assegnazioni_attive`); persona = `utenti.id`. `GESTISCE` conta solo per le generiche.
- Chiave speciale `__pannello__`: chi gestisce il pannello oltre agli amministratori.
- `collect_all` applica le regole dopo i provider; le voci concesse a chi nel modulo non le vede arrivano da `collect_sistema` (provider con `ctx.sistema=True`, senza gate di modulo; `_build_scadenzario_voci(..., tutte_le_fonti=True)` per l'HR). In errore restano le voci del modulo (non si allarga).
- Il riepilogo personale e il calendario Outlook usano `collect_all`, quindi seguono le stesse regole.

## Catalogo (`scadenzario/catalogo.py`)

Albero dinamico: tipi noti per fonte + voci presenti oggi (scadute e 90 giorni, raccolta di sistema) + tutte le categorie/attività generiche + chiavi già configurate («nessuna voce ora»).

## Fonti dagli altri moduli (`scadenzario/fonti_moduli.py`)

Registrate in `PROVIDERS` (prima di `generiche`) da `dashboard.scadenze_providers._registra_fonti_moduli`. Permesso di partenza = `acl_allows_path` della pagina di gestione (cache per richiesta), saltato con `ctx.sistema`.

| Fonte | Tipi | Pagina che fa da permesso |
|---|---|---|
| `sgi` | sorveglianza, certificato, audit_esterno, risposta_ente (`Certificazione`, `AuditEsterno`) | `sistema_gestione:esterni_elenco` |
| `sgi` | audit_interno, efficacia, auditor, car_analisi, car_chiusura (`Audit`, `AuditVerificaEfficacia`, `Auditor`, `AzioneCorrettivaAudit`) | `sistema_gestione:audit_calendario` (la propria CAR sempre) |
| `sgi` | soa, rischio_ot (revisione `APPROVATA`) | `sistema_gestione:soa` |
| `qualifiche` | processo, processo_revisione, requisito, certificazione_individuale (`models_mpq`) | `anagrafica:mpq_cruscotto` |
| `qualifiche` | abilitazione_macchina (`AbilitazioneMacchina.prossima_revisione`) | `anagrafica:skm_scadenzario` |
| `formazione` | documento_ente, verifica_nc (`TrainingProviderDocument`, `TrainingSession.verifica_nc_dovuta_dal`) | `anagrafica:formazione_sessioni_list` |
| `soc` | azione_correttiva, accettazione_rischio | `security:incidents`, `security:accettazioni_rischio` |
| `gdpr` | ads_revisione (`AmministratoreSistema`) | `security:registro_log_ads` |
| `procedure` | assegnazione (le proprie sempre), campagna | `procedure_refresh:campaign_list` |

Ogni raccolta è isolata (`_sicuro`): un modulo rotto non svuota le altre.

## Scadenze generiche

Modelli: `CategoriaScadenza` (email riepilogo, preavviso/ripetizione predefiniti, `avvisa_dopo_scadenza`), `ScadenzaGenerica` (ultimo controllo + validità → scadenza; responsabile, asset, fornitore facoltativi; `legacy_id`), `RinnovoScadenza` (allegato in `PrivateAttachmentStorage`, cifrato, download `rinnovo_allegato`), `AvvisoInviato`.

Avvisi (`scadenzario/avvisi.py`, task in `automazioni/schedules.py`):

- `scadenzario_avvisi_attivita` ogni giorno 07:15: email dell'attività, entro il preavviso, ripetizione ogni N giorni contando solo gli invii riusciti, anche dopo la scadenza se la categoria lo vuole;
- `scadenzario_riepilogo_mensile` il 1° alle 08:00: email della categoria, scadute + prossimi N giorni.

SiteConfig: `scadenzario_preavviso_giorni` (30), `scadenzario_ripeti_giorni` (7), `scadenzario_riepilogo_giorni` (60).

## Import

```powershell
$env:SCADENZARIO_DB_PASSWORD = "<password utente in sola lettura>"
python django_app\manage.py importa_scadenzario                       # prova
python django_app\manage.py importa_scadenzario --apply --con-avvisi  # import
```

Parametri `--host` (10.0.0.7) `--port` `--database` (scadenziario) `--user` (hub_readonly). Rilanciabile (`legacy_id`). Prerequisito: `GRANT SELECT ON scadenziario.* TO 'hub_readonly'@'10.0.0.7';`. Lo stesso giorno spegnere lo scheduler del vecchio scadenzario sul NAS.

## Test

`scadenzario/tests.py` (regole, catalogo, pannello, generiche, avvisi, import).
