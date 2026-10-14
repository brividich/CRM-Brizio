# Sistema unico dei permessi: ruoli, matrice, visibilità dei dati

Sede del codice: `django_app/core/permessi/`. Pagina di gestione:
`/admin-portale/ruoli-portale/` («Ruoli e permessi»). Test: `core/tests_permessi.py`,
`core/tests_permessi_moduli.py`.

## Il modello in una pagina

- **Ruolo** = `core.AccessGroup` (gruppi già esistenti). `priority` è l'**ordine** del ruolo.
  Flag: `amministratore` (vede e fa tutto, vale come admin legacy ovunque),
  `vede_tutto` (vede ed esporta ogni modulo, anche futuro, senza modificare: Direzione),
  `preset` (da quale preset nasce).
- **Persona → ruoli**: `AccessGroupMembership` (N ruoli per persona), assegnati **a mano**
  dalla scheda «Persone». Il ruolo base `dipendente` vale per tutti senza iscrizione.
- **Matrice**: `core.RuoloPermessoModulo` = ruolo × modulo × azione → `consentito` +
  `ambito` (`propri` / `team` / `tutti`). Riga assente = il ruolo **tace**.
- **Precedenza**: superuser e amministratori → tutto. Poi, fra i ruoli della persona,
  decide quello con **ordine più alto che si esprime** sull'azione. A parità d'ordine
  vince il «no»; fra due «sì» la visibilità più ampia. Nessuno si esprime → **negato**.
- **Team** = organigramma per ruolo (`anagrafica.RuoloOperativo.riporta_a` +
  `DipendenteRuoloOperativo` attive): chi ricopre un ruolo ha nel team chi ricopre ruoli
  che gli riportano, anche indirettamente. Stesso ruolo = collega, non team.
  `core/permessi/team.py`, cache invalidata dai segnali su ruoli e assegnazioni.
- **Azioni standard**: `vedere`, `creare`, `modificare`, `approvare`, `gestire`
  (chiudere/gestire, impostazioni), `esportare`, `cancellare`. Un modulo può aggiungerne
  di sue (`azioni_extra`), dichiarate nel registro.
- **Interruttore** (`SiteConfig permessi.sistema_ruoli_attivo`, scheda «Sistema»):
  - spento → valgono le regole storiche dei moduli (liste di utenti, ruolo legacy);
    la matrice si prepara senza effetti, salvo i ruoli già assegnati che concedono pagine;
  - acceso → ruolo base implicito per tutti, `RolePermissionGrant`/tabella `permessi`
    e fallback legacy **ignorati**, pagine senza binding **negate**, i moduli collegati
    usano `puo_fare`.

## API (sempre da qui, mai controlli scritti a mano)

```python
from core.permessi import puo_fare, decisione, utenti_visibili, sistema_ruoli_attivo
from core.permessi.negato import risposta_negata

puo_fare(request, "ticket_it", "creare")            # domanda generale
puo_fare(request, "ticket_it", "vedere", ticket)     # sul record: applica propri/team/tutti
decisione(request, "assenze", "approvare")           # .consentito, .ambito, .ruolo, .motivo
utenti_visibili(request, "diario_preposto")          # None = tutti; frozenset di utenti.id; vuoto = nulla
return risposta_negata(request, "testo chiaro", pagina="Nome modulo")  # 403 HTML o JSON
```

Fail-closed ovunque: modulo non registrato, azione non dichiarata, errore DB, record
senza proprietario determinabile (visibile solo con ambito «tutti»).

Id delle persone: i permessi lavorano su `utenti.id`. Se il modulo salva l'id
**anagrafica** (DPI, visite, formazione, ruoli d'organigramma) usare
`core.permessi.identita.utente_da_anagrafica` / `anagrafiche_di_utenti`, mai confondere i due.

## Come si aggiunge un modulo nuovo (procedura obbligatoria)

1. **Dichiararlo**: crea `<app>/registro_permessi.py`:

   ```python
   from core.permessi.registro import ModuloPermessi, registra_modulo

   def proprietario(obj):                # utenti.id del proprietario (o set di id), None se ignoto
       return obj.creato_da_legacy_id

   registra_modulo(ModuloPermessi(
       chiave="mio_modulo",               # chiave stabile, usata in matrice e codice
       nome="Mio modulo",
       descrizione="Cosa fa, in una riga.",
       area="Produzione",                 # raggruppamento in matrice
       app="mio_app",                     # app label Django
       moduli_acl=("mio_app",),           # PermissionDefinition.module delle sue pagine
       codici_acl=(),                     # code singoli di altri moduli che gli appartengono
       proprietario=proprietario,         # serve per «propri / team»
       domini_ai=(),                      # tool dell'assistente che leggono i suoi dati
   ))
   ```

   Il file viene caricato da solo (autodiscover). Il test
   `RegistroModuliTests.test_ogni_app_del_progetto_dichiara_un_modulo` **fallisce** se
   un'app del progetto non si dichiara.
2. **Salvare il proprietario** dei record (`utenti.id` di chi crea): senza, «propri» e
   «team» non funzionano e i record restano solo per chi ha «tutti».
3. **Usare `puo_fare` / `utenti_visibili`** in view, API, export, conteggi, notifiche:
   filtrare le query con `utenti_visibili`, controllare il singolo record con
   `puo_fare(..., oggetto)`, rispondere con `risposta_negata`. Finché il sistema può
   essere spento, mettere i controlli sotto `if sistema_ruoli_attivo():` mantenendo
   la regola storica nell'`else`.
4. **Assistente AI**: se un tool legge i dati del modulo, aggiungerlo a
   `ai_assistant/tools.py::TOOL_MODULI` (il test lo controlla).
5. **Permessi di pagina**: le rotte nuove hanno il loro `RoutePermissionBinding`
   (`bootstrap_acl_v2`). Dopo il deploy: «Sincronizza i permessi delle pagine» (scheda
   Sistema) o `manage.py permessi_ruoli --sincronizza`. Se la classificazione automatica
   sbaglia un permesso, correggilo con `capacita_forzate` nella dichiarazione.
6. **Matrice**: il modulo nasce senza permessi per nessuno (solo Amministratore e
   Direzione lo vedono). Le celle si assegnano dalla pagina; se serve un default per
   tutti i nuovi ambienti, aggiungerlo ai preset in `core/permessi/preset.py`.
7. **Visibilità nel menu**: dal Navigation Builder. Il menu non è un controllo di
   sicurezza.

## Come la matrice diventa permessi di pagina

`core/permessi/sync.py`: per ogni ruolo, le azioni concesse accendono i
`GroupPermissionGrant` (nota «matrice ruoli») dei permessi di pagina del modulo, in base
alla capacità del permesso: vedere/esportare → lettura; creare/modificare/cancellare →
modifica; approvare → approvazione; gestire → amministrazione e non classificati. La
capacità si legge dalle rotte che il permesso governa davvero, non dal suffisso del code
(`dpi.approva.view` è un'approvazione). I grant messi a mano non vengono toccati, e
non si scrive mai `enabled=False`.

Il verso inverso e' **in sola lettura**: `stato_pagine_ruolo(ruolo)` dice, per ogni cella
(modulo, azione standard), quante pagine dell'azione il ruolo ha davvero (`pieno` /
`parziale` / `vuoto`) e quali sono state accese o tolte a mano dalla pagina Accessi
(`a_mano`, `tolte_a_mano`). La matrice lo mostra come badge «pagine N/M» sotto la cella,
Accessi segna «da matrice» i grant con `NOTA_MATRICE`. Una modifica fatta in Accessi non
riscrive la cella: al prossimo salvataggio della matrice le pagine tolte a mano tornano,
quelle aggiunte a mano restano.
`dati_anteprima_ruolo(ruolo)` passa alla pagina pagine, capacita' e grant non governati
dalla matrice: il JS della matrice ripete lo stesso calcolo per mostrare i badge «→ X/M · da
salvare» prima del salvataggio. Se cambia la logica di `codici_desiderati`/`sincronizza_ruolo`,
aggiornare anche lo script in `ruoli_portale.html` (test `test_anteprima_prevede_il_risultato_del_salvataggio`).

## Comandi

```powershell
python django_app\manage.py permessi_ruoli --riepilogo
python django_app\manage.py permessi_ruoli --preset [--reset] [--solo hr,preposto]
python django_app\manage.py permessi_ruoli --sincronizza [--dry-run]
python django_app\manage.py permessi_utenti_prova --password <pwd> [--elimina]   # solo DEBUG / UAT con --forza
```

## Moduli già collegati a `puo_fare`

Ticket IT e Manutenzione (moduli distinti, lista/dettaglio/allegati/PDF/ricerca globale),
Diario preposto (lista, dettaglio, modifica, elimina, export, allegati, ispezioni),
Segnalazione incidenti (lista, dettaglio, modifica, elimina, statistiche, heatmap, export;
autore in `segnalato_da_legacy_id`), Assenze (flag storici derivati dalla matrice, perimetro
del capo = team d'organigramma), Assistente AI (`tool_consentito`).

Secondo giro:
- **DPI**: «gestire» = consegne/magazzino/catalogo, «approvare» = approvazione sul perimetro
  (team d'organigramma), nessuno approva la propria richiesta; dashboard e dettaglio per
  visibilità. `richiedente_legacy_id` è un id **anagrafica**: conversioni in
  `core/permessi/identita.py` (anche le notifiche al richiedente, prima inviate all'id sbagliato).
- **Anagrafica**: elenco ed export filtrati per visibilità (`build_dipendenti_rows`), scheda
  negata fuori perimetro. Le sezioni globali (gestione, dati riservati, dashboard visite,
  formazione) richiedono ambito **tutti**: chi ha «team» non le apre. Azione propria
  `dati_riservati` (IBAN, CF, contratti, documenti riservati).
- **KICK-OFF** (`tasks/access.py`): codici d'azione dalla matrice, `tasks_admin` = gestire su
  tutti; visibilità tutti / partecipazione + team / sola partecipazione.
- **Assets**: «gestire» su tutti = amministratore del modulo. Elenco non filtrato per
  propri/team (preset sempre «tutti»).
- **Anomalie**: livello globale dalla matrice (modificare tutti = EDIT_ALL, vedere tutti =
  READ_ALL); niente whitelist per nome; restano i ruoli per OP (capocommessa/CAR).
- **Timbri, Notizie, Procedure**: cancelli dalla matrice invece che dal nome del ruolo legacy.

I moduli che nei cancelli interni usano già codici canonici (`request_has_permission_code`:
RENTRI, Checklist, Schede sicurezza, Sistema di gestione, Specifiche, Contatori, SOC,
Suggestion Corner, configurazione Anomalie) seguono la matrice tramite la sincronizzazione dei
permessi di pagina: il permesso di gestione si accende con «gestire».

## Checklist manuale prima di rilasciare un modulo

Vedi [CHECKLIST_PERMESSI_RILASCIO_MODULO.md](CHECKLIST_PERMESSI_RILASCIO_MODULO.md).
