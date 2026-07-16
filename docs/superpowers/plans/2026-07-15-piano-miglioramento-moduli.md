# Piano di miglioramento — segnalazioni docs/MODULO ASSET.md

> **Nota di metodo:** le segnalazioni coprono **9 moduli indipendenti**. Questo è il
> piano direttore (priorità, dipendenze, pacchetti di lavoro). Ogni pacchetto, una
> volta approvato, diventa un piano di implementazione dettagliato ed eseguibile a sé
> (branch/worktree dedicato, test scoped, commit).

**Obiettivo:** chiudere tutte le segnalazioni del 2026-07-15 con il minimo rischio,
ordinandole per dipendenza tecnica: prima la bonifica trasversale dei reparti legacy,
poi la riforma dei ruoli (che sblocca assenze e, in futuro, la semplificazione ACL),
in parallelo i quick win indipendenti.

---

## Diagnosi (cosa ho verificato nel codice)

| # | Segnalazione | Riscontro nel codice |
|---|---|---|
| 1 | Asset: max file 50MB | `assets/views.py:205` `ASSET_DOCUMENT_MAX_BYTES` è **già 50MB**. Limiti minori altrove: planimetria 10MB (`assets/forms.py:2132`), un check 2MB (`forms.py:2432`), logo 512KB. Probabile vero blocco in prod: **IIS `maxAllowedContentLength` (default ~30MB)** nel web.config — che NON viene rideployato da deploy-release.ps1 |
| 2 | Asset: foto targhetta in header | Nessun campo immagine sull'Asset; header in `asset_detail.html`. Serve campo + upload + media protetta (pattern token già usato per i documenti asset) |
| 3 | Organigramma non aggiornato | `anagrafica/views.py:13056`: matcha dipendenti su **testo libero legacy** `row["reparto"]` vs `Reparto.nome`. Il FK `area_aziendale` (models.py:1015) esiste ma non è usato qui |
| 4 | Tabelle anagrafica con vecchi reparti | 19 file usano ancora la colonna legacy; il tool `report_reparti_orfani` (--reassign/--apply) esiste già |
| 5 | E-learning: wizard + 50MB | Materiale e-learning **già 50MB** (`views.py:14814`); altri limiti documenti a 15/20MB. Creazione corso oggi è form singolo, non wizard |
| 6 | Scadenziari raggruppati per tipo | 3 scadenzari: `scadenzario.html`, `skm_scadenzario.html`, `qualifiche_scadenzario.html` — liste piatte |
| 7 | Gerarchia capireparto (Bellucci) | Nessuna nozione di "superiore" nei ruoli; `Reparto.caporeparto_legacy_id` è l'unico legame |
| 8 | Unire ruoli aziendali + operativi | Due cataloghi separati (`ruoli_aziendali_list.html`, `ruoli_operativi.html`, helper `core/operational_roles.py`); nessun campo certificazione |
| 9 | Timbri: colonna reparto | `timbri/models.py` ha reparto testuale legacy |
| 10 | Assenze: caporeparto bloccato | Oggi selezionabile; il legame autoritativo esiste già: `DipendenteAnagraficaAziendale.caporeparto_legacy_id` (`assenze/views.py:486-510`). L'escalation "se assente → superiore" richiede la gerarchia ruoli (#7) |
| 11 | Procedure refresh: campagna→sessione, wizard | 71 occorrenze "campagna" in 18 file (modello, template, URL). Wizard esiste ma UX caricamento procedure e assegnazione utenti da rifare |
| 12 | SMS/KICK-OFF: dropdown nome cognome | Dropdown mostrano username (48 occorrenze in suggestion_corner; analoghe in tasks) |
| 13 | Diario preposto: PDF col template portale | Export PDF non usa `core/table_pdf.py` (lo standard del portale, già usato dai 29 export anagrafica) |
| 14 | Segn. sicurezza: reparti legacy | `rilevazione_incidenti/models.py:49`: `reparto = CharField` testo libero, filtri sul testo |

---

## Struttura del piano — 5 pacchetti

### Fase 0 — Quick win indipendenti (basso rischio, si fanno subito)

**P0.1 — Upload 50MB coerente (asset + e-learning + infrastruttura)**
- Audit di tutti i limiti upload (asset, anagrafica `_MAX_DOC_SIZE` 20MB, documenti corso 15MB) e portare a 50MB dove ha senso il caricamento documenti; lasciare limiti bassi dove è corretto (logo, planimetria immagine). -- Eventualmente sistemare diciture nella pagna html --
- **Punto critico infra:** verificare/portare `maxAllowedContentLength` ≥ 50MB in `configure-iis-site.ps1` (il web.config NON è toccato dal deploy normale → serve passaggio esplicito in prod).
- Messaggi d'errore e hint UI ("max 50MB") aggiornati ovunque.

**P0.2 — Foto targhetta in header asset**
- Campo immagine `foto_targhetta` su Asset (migrazione), upload dal form con validazione (jpg/png, limite dimensione), storage nel percorso protetto già usato dai documenti asset.
- Render nell'header di `/assets/view/<id>`: riquadro a dimensione fissa uguale per tutti; se vuoto non si vede nulla (nessun placeholder).

**P0.3 — Dropdown "Nome Cognome" in Suggestion Corner e KICK-OFF**
- `label_from_instance` / helper condiviso che risolve username → "Cognome Nome" (fonte: anagrafica); fallback a username se non mappato.
- Applicato a tutti i dropdown persona dei due moduli.

**P0.4 — PDF Diario preposto con template portale**
- Rifare gli export PDF del diario su `core/table_pdf.py` (lo standard: intestazione, logo, stile coerente).
- Già che ci siamo: censimento degli altri PDF fuori standard ("devono essere tutti così") → lista, e allineamento di quelli a portata; gli altri entrano nel backlog.

### Fase 1 — Bonifica trasversale REPARTI (il debito che genera 4 segnalazioni)

Un solo pacchetto perché la causa è unica: la colonna legacy testo-libero sopravvive in più moduli.

**P1.1 — Censimento e fonte unica**
- Censire tutti i punti che leggono il reparto legacy (19 file già individuati) e definire la fonte unica: coppia **Reparto (FK) + AreaAziendale (FK)** dal dipendente.
- Helper condiviso di risoluzione (dipendente → reparto/area canonici) usato da tutti i moduli.

**P1.2 — Organigramma**
- Riscrivere il match di `organigramma()`: dal testo legacy al FK canonico; il bucket "Non mappati" resta come spia dei residui.
- Mostrare la gerarchia reparto → aree aziendali → membri come da nuova struttura.

**P1.3 — Tabelle/filtri nei moduli**
- Anagrafica: tutte le viste tabellari e gli export che mostrano il vecchio reparto passano al canonico.
- Timbri: colonna reparto + filtri dal canonico.
- Segn. sicurezza (`rilevazione_incidenti`): il campo per le NUOVE segnalazioni diventa scelta dal catalogo canonico; i record storici conservano il testo com'era (audit trail), i filtri offrono i valori canonici + storico.

**P1.4 — Rimozione legacy**
- Bonifica dei residui con `report_reparti_orfani --reassign/--apply`, poi rimozione della colonna/lettura legacy dove non più referenziata. Rimozione fisica solo a censimento verde — mai prima.

### Fase 2 — Riforma RUOLI (fondazione per assenze e ACL)

**P2.1 — Catalogo ruoli unificato**
- Unire RUOLI AZIENDALI e RUOLI OPERATIVI in un catalogo unico in anagrafica (fonte unica, come da linea già tracciata con `core/operational_roles.py`).
- Nuovo campo opzionale **"certificazione di competenza"** per ruolo.
- Migrazione dati dai due cataloghi esistenti con report dei duplicati/conflitti da farti validare.

**P2.2 — Gerarchia ruoli in Impostazioni**
- Relazione "riporta a" tra ruoli (es. capireparto → riportano al ruolo di coordinamento, oggi B. Bellucci), configurabile da **Impostazioni → Ruoli**, non hardcodata su una persona.
- L'organigramma la visualizza.
- ⚠️ **Mi serve l'organigramma attuale che hai offerto** per modellare la gerarchia reale prima di scrivere il piano di dettaglio.

*(La semplificazione ACL basata sui ruoli resta fuori scope, come da tua nota: "di questo ce ne occupiamo poi".)*

### Fase 3 — ASSENZE (dipende da Fase 2)

**P3.1 — Caporeparto bloccato**
- In richiesta assenza il campo caporeparto diventa **read-only**, valorizzato dal caporeparto assegnato al dipendente (`caporeparto_legacy_id`, legame già autoritativo in `assenze/views.py:486`).

**P3.2 — Escalation se assente**
- SE e solo SE il caporeparto risulta assente nel giorno della richiesta (verifica su assenze approvate), la richiesta va al suo superiore, dedotto dalla gerarchia ruoli di P2.2. Log dell'escalation per audit.

### Fase 4 — UX moduli (indipendenti tra loro, dopo Fase 1)

**P4.1 — E-learning: wizard creazione corso**
- Percorso guidato multi-step (riuso del componente "percorso" `kp-` già fatto per KICK-OFF): dati corso → materiali (50MB) → quiz → destinatari → riepilogo.

**P4.2 — Scadenzari raggruppati per tipo**
- Tutti e 3 gli scadenzari (formazione, skill matrix, qualifiche): raggruppamento per "tipo" con riga espandibile che mostra i dipendenti (pattern espansione già in uso nelle liste hub). Conteggi e stato peggiore visibili a gruppo chiuso.

**P4.3 — Procedure refresh: "sessione" + wizard**
- Rinomina **Campagna → Sessione**: etichette UI, titoli, email/notifiche (il modello interno può restare `Campaign` per non toccare 18 file di migrazioni/DB — da confermare).
- Wizard configurazione: selezione procedure **multi-scelta** con UI curata (ricerca + selezione multipla, non upload singolo).
- Assegnazione utenti: **per reparto** (canonico, da Fase 1) + lista con checkbox + ricerca.

---

## Ordine di esecuzione e dipendenze

```
Fase 0 (P0.1–P0.4)  ──────────────► subito, indipendenti
Fase 1 (reparti)    ──────────────► subito, indipendente
Fase 2 (ruoli)      ── richiede organigramma da Luca ─► poi
Fase 3 (assenze)    ── dipende da Fase 2 ─► dopo
Fase 4 (UX)         ── P4.3 assegnazione-per-reparto dipende da Fase 1
```

Stima grossolana: Fase 0 = 1 sessione; Fase 1 = 2-3 sessioni (è la più delicata: tocca dati); Fase 2 = 2 sessioni; Fase 3 = 1 sessione; Fase 4 = 2-3 sessioni.

## Domande aperte (bloccano solo le fasi indicate)

1. **[Fase 2]** Passami l'organigramma attuale (gerarchia reale dei ruoli) — l'hai offerto tu.
2. **[Fase 4]** Rinomina campagna→sessione: basta l'interfaccia (etichette/URL) o vuoi rinominato anche il modello dati? Consiglio solo UI: zero rischio migrazioni.
3. **[Fase 1]** Rimozione fisica dei reparti legacy: confermi che dopo la bonifica possiamo eliminare la colonna, o preferisci tenerla in sola lettura per un periodo?

## Regole di ingaggio (valide per ogni pacchetto)

- Worktree dedicato `C:\Dev\pn-<tema>`, branch `feature/<area>-<tema>`, mai il checkout condiviso.
- Test scoped per app con `--keepdb`; CHANGELOG.md + README.md aggiornati a ogni pacchetto.
- Migrazioni dati sempre con dry-run e report prima dell'apply (lezione import formazione).
- Reparto/ruoli: mai usare campi denormalizzati come fonte live senza verificarne la propagazione.
