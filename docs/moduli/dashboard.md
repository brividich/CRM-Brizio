# `dashboard` — home KPI personalizzabile

Area **Core** · URL `/` · codice [`django_app/dashboard/`](../../django_app/dashboard/)

[← Catalogo moduli nel README](../../README.md#-catalogo-moduli)

## Sintesi

Home "Bacheca" info-hub: News + **Documenti & Collegamenti** (gestibili da admin), KPI, "Cose da fare", launcher moduli

## Dettaglio

Workspace personale dell'utente autenticato. Widget multi-modulo con layout salvato per utente.

- **Home "Bacheca" (info-hub)** — redesign 2026-07: saluto + 4 KPI prioritari, poi la **Bacheca a 2 colonne** (News aziendali · **Documenti & Collegamenti**), "Cose da fare", Brief AI e un launcher moduli piatto. La sezione **Documenti & Collegamenti** (pagina `/dashboard/bacheca/`, gestione admin in `/admin-portale/bacheca/`) raccoglie **documenti caricati** (storage privato cifrato fuori webroot, download con ACL + audit), **collegamenti esterni** e **scorciatoie interne**, organizzati per **categoria** e con **visibilità per ruolo** (nessun ruolo assegnato = visibile a tutti). Modelli `HubLinkCategory`/`HubLink`/`HubLinkRoleAccess` in `core`
- **Widget KPI cross-modulo** (assenze in attesa, ticket aperti, scadenze asset, anomalie…)
- **Cockpit "Le mie attività"** — blocco principale **in cima alla home, sopra i pulsanti dei moduli**: aggregato cross-modulo di tutto ciò che richiede un'azione dall'utente loggato (approvazioni assenze, ticket aperti correlati, anomalie dei propri OP, procedure da leggere, richieste DPI in corso), con conteggio e link al modulo. Sostituisce i vecchi pannelli d'azione separati (ticket/anomalie/approvazioni); con il redesign "Bacheca" le news vivono nella sezione Documenti & Collegamenti e i pannelli *presenze* / *KPI sicurezza* / *stato sistema* sono stati rimossi dalla home. Logica condivisa `build_cose_da_gestire()` (riusata anche dalla pagina dedicata `/mie-attivita`). Versione attuale: solo elenco + link (no azioni bulk dalla home)
- **Moduli del portale**: la griglia della home mostra solo i moduli disponibili per il ruolo/utente corrente; i moduli non accessibili non vengono renderizzati nella pagina.
- **Scadenzario Globale Unificato** (`/scadenze`): vista cross-modulo di tutte le scadenze entro 60 giorni — personale (qualifiche/visite/formazione/contratti), asset (scadenze amministrative), DPI (vita utile), RENTRI (FIR mancanti), **azioni CAPA** aperte — con filtri sorgente/stato/reparto, KPI ed export CSV. Architettura a **provider condivisi** (`dashboard/scadenze_providers.py`): ogni sorgente rispetta l'ACL del proprio modulo e l'aggregatore isola i provider in errore. Pagina ACL-shared (link "Scadenzario" in cima alla home)
- **Drag & drop** dei widget con persistenza `UserDashboardConfig`
- **Template iniziale globale** definibile dagli admin + ripristino rapido
- **Shell viewport-aware** a tutta altezza, no bande vuote in fondo al viewport
- Route legacy `/scheda-dipendente` mantenuto come alias compat
