# Prompt per Claude Code

Copia questo testo in Claude Code dopo aver messo la cartella `novicrom_maintenance_ux_pack` nella root del repository, ad esempio in `docs/novicrom_maintenance_ux_pack/`.

---

Devi integrare nel modulo Assets/Manutenzione il redesign UX presente in `docs/novicrom_maintenance_ux_pack/`.

Prima di modificare qualsiasi file:

1. Leggi `docs/novicrom_maintenance_ux_pack/README_INTEGRAZIONE.md`.
2. Guarda i quattro mockup in `docs/novicrom_maintenance_ux_pack/docs/ux/`.
3. Confronta i template `_v2.html` con i template produzione attuali:
   - `assets/base_shell.html`
   - `assets/pages/maintenance_hub.html`
   - `assets/pages/maintenance_schedule.html`
   - `assets/pages/workorder_detail.html`
   - `assets/pages/maintenance_impostazioni.html`
   - `assets/components/workorder_checklist.html`
4. Individua view, context variables, forms POST, permessi, HTMX, JavaScript e URL usati da queste pagine.

## Obiettivo

Integra la nuova gerarchia visiva dei file `_v2.html`, **senza riscrivere il backend e senza perdere alcuna funzionalita' esistente**.

La regola fondamentale e':

> interfaccia semplice davanti, tracciabilita' completa dietro.

Non eliminare dati, form, storico, audit, allegati o azioni soltanto perche' non sono presenti nei mockup.

## Vincoli

- Mantieni tutte le variabili Django e i flussi attuali compatibili.
- Mantieni i nomi URL esistenti.
- Mantieni tutti i `{% csrf_token %}`.
- Mantieni HTMX della checklist.
- Mantieni permessi e conditional rendering (`can_manage_*`, `is_admin`, ecc.).
- Mantieni dark mode e responsive.
- Non introdurre dipendenze frontend nuove se non strettamente necessario.
- Preferisci CSS/HTML semantico e JavaScript vanilla gia' coerente con il progetto.
- Non modificare model o migration per ottenere solo un effetto grafico.
- Se un elemento del mockup richiede dati che oggi la view non fornisce, NON inventare valori. Riutilizza i dati disponibili o proponi una piccola estensione della view separatamente.

## Ordine di lavoro

### Fase 1 — Dettaglio intervento
Integra `workorder_detail_v2.html` in `assets/pages/workorder_detail.html`.
Deve diventare la schermata operativa principale dell'OdL:
- stato e contesto immediatamente leggibili;
- panoramica compatta;
- checklist centrale;
- riepilogo tempi/costi/copertura a destra;
- allegati accessibili;
- note operative semplici;
- cronologia/log separata in fondo.

Preserva integralmente il comportamento di `assets/components/workorder_checklist.html`.

### Fase 2 — Centro manutenzione
Integra `maintenance_hub_v2.html` in `assets/pages/maintenance_hub.html`.
La pagina deve rispondere prima di tutto a "cosa devo gestire oggi?".
Mantieni accessibili ticket MAN, scadenze, verifiche, storico e piani, ma evita di mostrarli tutti contemporaneamente come registri estesi.

### Fase 3 — Scadenzario
Integra `maintenance_schedule_v2.html` in `assets/pages/maintenance_schedule.html`.
Questa e' la fase piu' delicata.

La tabella/lista principale deve essere piu' leggibile, ma devi CONSERVARE dal template attuale tutte le funzioni avanzate, tra cui:
- registrazione esecuzione manuale;
- allegati dell'esecuzione;
- checklist steps;
- `record_maintenance_rule_execution`;
- Outlook / Graph calendar;
- eventi Outlook gia' presenti;
- scelta utente/mailbox;
- worksheet stampabile;
- copertura contrattuale;
- segnalazione contatore stale;
- viste Lista / Board / Per macchina;
- sezioni scadenze amministrative e lookahead 90 giorni.

Sposta le azioni meno frequenti dentro un menu "Altre azioni", `<details>`, drawer o pannello secondario: NON eliminarle.

### Fase 4 — Catalogo e piani
Integra `maintenance_impostazioni_v2.html` in `assets/pages/maintenance_impostazioni.html`.
Nell'interfaccia usa soprattutto i concetti:
- Attivita' = cosa fare;
- Piano di manutenzione = dove/quando/chi;
- Copertura = salute/applicazione dei piani.

I nomi tecnici `MaintenanceRule` e `MaintenanceTemplate` possono continuare a esistere nel codice, ma non devono dominare l'UX dell'utente normale.

## CSS

Usa `assets/components/maintenance_ux_v2_styles.html` come base di design. Durante l'integrazione puoi:
- mantenerlo come partial condiviso; oppure
- spostarlo nello static CSS del modulo se il progetto ha una collocazione migliore.

Non duplicare centinaia di righe di CSS tra i template.

## Verifica finale

Dopo ogni fase:
1. esegui i test Django esistenti relativi ad Assets/Manutenzione;
2. esegui `python manage.py check`;
3. verifica che i template compilino;
4. cerca URL/POST/azioni presenti nel vecchio template e assicurati che non siano stati persi;
5. mostra `git diff --stat` e una sintesi di cosa hai cambiato;
6. non procedere alla fase successiva se emergono regressioni funzionali.

Prima di iniziare a scrivere codice, fammi una breve mappa di:
- template -> view -> context principale;
- funzionalita' che rischierebbero di essere perse con una sostituzione diretta;
- piano concreto delle modifiche.

Poi inizia dalla Fase 1.

---
