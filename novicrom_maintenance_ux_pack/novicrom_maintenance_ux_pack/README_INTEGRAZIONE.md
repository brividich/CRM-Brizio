# Novicrom HUB — Maintenance UX v2

Questo pacchetto e' una **proposta di integrazione UX**, non un set di file da sovrascrivere alla cieca.
I template `_v2.html` usano i nomi delle variabili Django gia' presenti nei template forniti e mostrano la nuova gerarchia visiva proposta nei mockup.

## Obiettivo

Semplificare l'uso quotidiano senza ridurre la tracciabilita':

1. **Cosa richiede attenzione adesso** sempre in alto.
2. **Azione primaria** evidente e azioni secondarie spostate nel dettaglio/collassabili.
3. Separare chiaramente:
   - lavoro operativo;
   - pianificazione;
   - configurazione;
   - storico/audit;
   - report.
4. Nessuna eliminazione di dati o storico: la semplificazione e' di presentazione.

## File

- `assets/components/maintenance_ux_v2_styles.html`: componenti UI condivisi, namespace `ux-`.
- `assets/pages/maintenance_hub_v2.html`: proposta per il Centro manutenzione.
- `assets/pages/maintenance_schedule_v2.html`: proposta per Prossime manutenzioni / Scadenzario.
- `assets/pages/workorder_detail_v2.html`: proposta per Dettaglio intervento.
- `assets/pages/maintenance_impostazioni_v2.html`: proposta per Catalogo e piani.
- `docs/ux/*.png`: mockup visivi di riferimento.
- `CLAUDE_CODE_PROMPT.md`: prompt consigliato per l'integrazione nel repository reale.

## Regole di integrazione importanti

### Non perdere funzionalita'
I template v2 sono soprattutto una proposta di **information architecture + UI**. Durante il merge vanno conservati dal codice esistente:

- tutti i controlli permessi (`can_manage_*`, `is_admin`, ecc.);
- tutti i POST con `{% csrf_token %}`;
- HTMX della checklist;
- creazione/chiusura OdL;
- registrazione manuale esecuzioni;
- upload/allegati;
- log e storico;
- integrazione Outlook/Graph;
- eventi calendario gia' creati;
- filtri e querystring;
- dark mode;
- responsive;
- tutte le URL Django esistenti.

### Nota specifica `maintenance_schedule_v2.html`
La v2 rende intenzionalmente piu' leggera la tabella principale. Il template produzione attuale contiene azioni avanzate che **non devono sparire**, in particolare:

- `record_maintenance_rule_execution`;
- form di registrazione esecuzione e allegati;
- creazione evento Outlook;
- visualizzazione eventi Outlook esistenti;
- scelta mailbox/utente calendario;
- controlli `can_manage_assets` / `can_manage_outlook_calendar`;
- gestione contatore stale;
- link alla scheda stampabile.

Claude deve reinserire queste funzioni come **azioni secondarie/collassabili o drawer**, non eliminarle.

## Ordine consigliato

1. `workorder_detail.html` — rischio basso, benefici UX immediati.
2. `maintenance_hub.html` — nuova home operativa.
3. `maintenance_schedule.html` — intervento piu' delicato, conservare tutte le azioni avanzate.
4. `maintenance_impostazioni.html` — semplificare terminologia Catalogo/Piani/Copertura.
5. Solo dopo, valutare un refactor di `base_shell.html` per estrarre CSS condiviso.

## Concetti UX da mantenere

- Dashboard: **attenzione > lavoro > agenda > registri**.
- Scadenzario: **asset/attivita > stato > data > responsabile/copertura > azione**.
- Dettaglio intervento: **panoramica > checklist > note > materiali/allegati > cronologia**.
- Catalogo: l'utente deve capire prima `Attivita'` e `Piano`; `Rule` e `Template` possono restare nomi tecnici nel backend.
