# Audit interni (`sistema_gestione`) — Gap analysis (PROMPT 08)

Data: 2026-10-11. Base: `origin/release/prod` `02bae987`. Ricognizione con 4 subagent Explore (programma, esecuzione, rapporto/KPI, integrazione NC/OFI).

Input di Brizio:
- Norme: ISO 9001 + EN 9100, ISO 45001, ISO 14001, ISO 27001, requisiti cliente (RAI).
- Ruoli: RSGI/Qualità pianifica, l'auditor esegue, l'RDD approva, il responsabile di funzione chiude le azioni.

## Stato attuale in sintesi

Il modulo c'è ed è solido su piano MOD.035A, checklist EN 9100 "Folder B", autosave con optimistic lock, evidenze cifrate con SHA-256, CAR MT CN 11 con verifica di efficacia e rapporto MOD.035B. Rispetto a un software di audit professionale ha però queste lacune:

| Obiettivo | Cosa c'è | Lacune principali |
| --- | --- | --- |
| A Programma | Programma **annuale** a revisioni (BOZZA→PROPOSTA→APPROVATO→SUPERATO); matrice processo × 12 mesi; priorità `priorita-v1` (criticità, ultimo audit, NC 24 mesi, efficacia, revisione scheda); copertura dei punti norma | Nessun ciclo triennale; frequenza statica 1–12 mesi; priorità senza OFI, reclami e requisiti cliente; niente calendario; niente avviso "non auditato da N mesi"; `approva_programma` non cambia stato; nessun rifiuto con motivo; nessuna separazione proponente/approvatore |
| A Indipendenza | Conflitto per reparto/responsabile **sempre bloccante** (scelta MT CN 12); qualifica (requisiti + 4 audit) | Nessun override motivato da un terzo (il log della deroga è codice morto); qualifica senza scadenza e senza abilitazione per norma |
| B Preparazione | Form unico a 4 sezioni; checklist da `ChecklistProcesso` + Folder B; apertura/chiusura automatiche; invio con `.ics` scritto a mano; preparazione AI con avviso "va verificato" | Non è un wizard; nessuna domanda generata dai rilievi aperti precedenti; `.ics` senza ATTENDEE/SEQUENCE; `meeting_outlook.py` legato al KickOff (riusabile `core/outlook_calendar.py`); nessuna conferma degli auditati; lo storico AI non filtra per ACL; provenienza AI non salvata |
| C Esecuzione | Editor domanda per domanda, autosave 900 ms, 401/403/409 JSON, `beforeunload` | Esiti solo CONFORME/OFI/NC/NA (manca NC maggiore/minore, osservazione, punto di forza); niente clausola strutturata; nessuna evidenza obbligatoria per NC; niente tablet né fotocamera; nessun retry/coda offline; "prossima" non sequenziale |
| D Rilievi → azioni | NC e OFI → MOD.174 (`RegistroOFI`) idempotente; CAR 1:1 con analisi a 1 mese e chiusura a 3 mesi, proroga, approvazione, verificatore ≠ responsabile; `AuditVerificaEfficacia` | **Nessun collegamento con un registro azioni del modulo qualità**; causa in testo libero; nessun sollecito o escalation (nessun job); la chiusura dell'audit non verifica le CAR; manca il link MOD.174 → audit |
| E Rapporto / KPI | MOD.035B ReportLab con firme nel portale; `AuditRapportoVersione` solo in caso di revisione | Struttura fissa EN 9100; nessuna anteprima o filigrana BOZZA; **il PDF emesso si rigenera ogni volta** (non immutabile, nessun hash); copia firmata sostituibile; convalida ente e riepilogo non stampati; nessun export xlsx dei rilievi; nessun cruscotto in-app (KPI parziali solo in `report_conformita`, con N+1) |
| Sicurezza | 4 permessi view/edit/esegui/approva; esecuzione solo da assegnato | Nessun ruolo **auditato**: chi ha `audit.view` vede tutti i rilievi; download evidenze senza controllo per oggetto; convalida ente legata all'email; stesso utente firma come Lead e come Direzione |

## Integrazione NC/CAPA (vincolo "riusa, non duplicare")

- `anomalie.AnomaliaNC` **non è adatta**: è vincolata all'OP (`op_titolo` obbligatorio, permessi e responsabili dall'OP). Collegarla richiederebbe migrazioni e permessi nuovi in `anomalie`.
- `core.ActionItem` (CAPA trasversale) ha già `source_code`/`source_pk`/`source_url`, l'etichetta origine `"audit"`, la notifica al responsabile, il pannello `_capa_panel.html` e lo scadenzario della dashboard. **Nessuna migrazione fuori da `sistema_gestione`.**
- **Proposta:** il MOD.174 resta il registro unico dei rilievi e la CAR resta 1:1. All'approvazione della CAR si crea o aggiorna un `ActionItem` collegato in entrambe le direzioni. In `gestione_specifiche` si aggiunge solo un link (template/view) dal MOD.174 all'audit.
- Analisi cause: campi `analisi_metodo`/`analisi_perche`/`analisi_ishikawa` sulla CAR, **con lo stesso schema di `AnomaliaNC`** (5 perché / Ishikawa 6M).

## Piano proposto, per priorità

| Fase | Contenuto | Migrazioni | Stima |
| --- | --- | --- | --- |
| 1 Integrità e sicurezza | Rapporto emesso immutabile: PDF congelato alla chiusura + SHA-256 + versione 1; copia firmata vincolata; convalida ente e riepilogo nel PDF; anteprima con filigrana BOZZA; download evidenze con controllo per audit; firme Lead ≠ Direzione; AI con storico filtrato e provenienza salvata | sg 0009 | M |
| 2 Rilievi e azioni | Esiti NC maggiore/minore, osservazione, punto di forza (mappati su MOD.174); clausola strutturata; evidenza obbligatoria per NC; analisi 5 perché/Ishikawa sulla CAR; collegamento `ActionItem`; link MOD.174 → audit; chiusura audit condizionata (configurabile); job solleciti CAR/efficacia con escalation RSGI | sg 0010 | M–L |
| 3 Programma | Ciclo triennale (programma con anno inizio/fine, celle anno+mese); frequenza calcolata da rischio + esiti + NC/OFI + cambi + requisiti cliente; "non auditato da N mesi"; calendario; rifiuto con motivo e separazione dei ruoli; qualifica con scadenza e norme abilitate; deroga d'indipendenza **configurabile** (default = blocco MT CN 12) | sg 0011 | L |
| 4 Esecuzione tablet | Layout tablet, precedente/successiva, fotocamera (`capture`, HEIC→JPEG), upload asincrono, retry con backoff + bozza locale e ripresa | — | M |
| 5 Preparazione e inviti | Wizard a step; domande di follow-up dai rilievi aperti precedenti; inviti Graph con conferma degli auditati (`core/outlook_calendar.py`); annullamento audit; numerazione per tipo (RAIS/RAI/STR) | sg 0012 | M–L |
| 6 Report e cruscotto | Export xlsx dei rilievi; cruscotto in-app (avanzamento pianificati/eseguiti/in ritardo, rilievi per processo/clausola/gravità nel tempo, tempo medio di chiusura CAR, % efficacia, ricorrenti, copertura clausole per norma); struttura PDF a sezioni configurabili | — / sg 0013 | M–L |
| 7 Ruolo auditato | Utente collegato ad `AuditPersona`, vista "i miei rilievi" in sola lettura | sg 0014 | M |

## Decisioni richieste prima di implementare

1. **Registro azioni delle NC:** `core.ActionItem` (consigliato, zero migrazioni altrove) oppure estendere `anomalie.AnomaliaNC` (migrazioni in un altro modulo).
2. **Indipendenza:** mantenere il blocco assoluto MT CN 12, oppure deroga motivata approvata da un terzo (RDD). Proposta: configurabile, default = blocco.
3. **Chiusura audit:** solo con il piano azioni approvato per tutte le NC (ISO 19011, proposta) oppure anche con l'efficacia verificata.
4. **Ordine delle fasi** e quante farne in questo branch (oltre circa 1.500 righe nette si propone lo split per fase).
