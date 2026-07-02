# Valutazione approfondita `gestione_specifiche` — modello Fable (2026-07-01)

> **Aggiornamento 2026-07-02 — RISOLTI**: **A1** (API django-ninja portata sotto ACL v2: gate
> middleware + controllo permesso per-azione in `transizione_specifica`), **A2** (enforcement di
> stato server-side su claim/compila/chiudi/riga_add/approva/distribuzione/OFI + congelamento
> MOD.133 post-approvazione) e **M4** (approvazione atomica); **M2** (slot `stato_pre_errore`
> dedicato → niente più intrappolamento S5↔S9) e **M1** (unicità `(codice,revisione)` app-level +
> comando `specifiche_duplicati`; vincolo DB dopo dedup prod); **M3** (pausa timer S9), **M6**
> (numerazione OFI serializzata), **M7** (azione OFI non ribaltabile), **M8** (audit-log a warning),
> **M10** (delete Specifica disabilitata in admin), **M11** (owner-pw vuota rifiutata), **M12** (no 500
> su filtri data); **A3** (ricerca semantica: pre-filtro lessicale + re-ranking sulla sola shortlist
> con embedding cache-ati → niente più N+1 HTTP). **Restano aperti**: **M1b** (UniqueConstraint DB
> dopo dedup prod), gli affinamenti F7 (UI master-picker, PERM_DEROGA, reminder S1) e le voci BASSE
> (B1-B9). **Nota**: A1/A2/M1a/M2/M3/M4/M6/M7/M8/M10/M11/M12/A3 = tutto il grosso backlog è risolto.

> Revisione **in sola lettura** condotta da un agente sul modello Fable (claude-fable-5): letti per
> intero models/state_machine/views/api/forms/acl_bootstrap/ai_copilota/share_link/share_write/
> pdf_compose/mod133_render/composito/distribuzione/ofi/scadenze/storage/import + tutti i management
> command, i 18 file di test, i template e i doc d'intento, più i punti di contatto con `core`.
> Percorsi relativi a `django_app/gestione_specifiche/` salvo diversa indicazione.

---

## 1. Panoramica architetturale
Modulo a **strati ben separati** (dominio/FSM · servizi puri testabili · pipeline PDF-share a mattoni
indipendenti · interfacce SSR+HTMX/API/CLI/AI), disciplina superiore alla media del repo. Dipendenze
esterne contenute (`anagrafica.Reparto`, `core` ACL/notifiche/storage, `ai_assistant` Ollama on-prem,
`automazioni` schedules). **Giudizio**: architettura solida; i mattoni puri (share, PDF, FSM) sono di
qualità alta e ben testati. I punti deboli stanno nelle **cuciture**: autorizzazione API ninja,
enforcement di stato nelle view, atomicità delle operazioni, unicità/integrità.

## 2. Punti di forza
1. `share_link.py` (55-109): anti-traversal Windows a strati (ADS `:`, spazio/punto finale, `..`
   mascherati, realpath+commonpath), **testato avversarialmente** (junction NTFS reale).
2. Deposito F2 con piano/rollback LIFO, dry-run, move-mai-delete, collisione idempotente per hash;
   rollback testato con audit che fallisce (`test_share_write.py:219-231`).
3. Audit FSM centralizzato (un solo evento per transizione, snapshot metadati).
4. Copilota AI disciplinato: "propone, non salva" **verificato dai test**; fail-safe; diff `difflib`
   pre-LLM; output sanitizzato/troncato; escaping JS.
5. Separazione compilatore≠approvatore su due livelli (modello + view), testata.
6. Suite ampia sulla logica pura (timer pausa/ripresa, renderer, protezione PDF, import idempotente).
7. Storage privato cifrato fuori webroot; download solo via view ACL.
8. CLI dry-run-first ovunque.

## 3. Debolezze / rischi

### ALTA
- **A1 — API django-ninja fuori dal perimetro ACL v2.** `/gestione-specifiche/api/` non ha binding in
  `acl_bootstrap` né in `core/middleware.API_ACL_GATE_PATHS`. In **prod strict** → l'intera API (incl.
  **transizioni di stato**) è **feature morta (403)** per i non-superuser; in **non-strict** → chi ha
  `gs_view` può **eseguire transizioni** via `POST /api/specifiche/{id}/transizione` scavalcando
  `PERM_APPROVA/SOSPENDI/ANNULLA`. I test non lo scoprono perché usano solo superuser. *(È il pitfall
  già annotato in memoria di progetto su API_ACL_GATE_PATHS.)*
- **A2 — Nessun enforcement di stato server-side nelle view operative.** La UI nasconde i pulsanti ma
  le URL restano azionabili: `mod133_compila` lascia **modificabili le righe di un MOD.133 approvato**
  (S3/S4) via POST diretto **senza audit**, e il composito F6a legge le righe **live** → un edit
  post-approvazione cambierebbe silenziosamente il documento ufficiale; `distribuzione_nuova`
  registrabile su bozze/superate; `mod133_chiudi` in ogni stato con 0 righe.
- **A3 — `ricerca_semantica` N+1 su HTTP** (ai_copilota.py:279-291): con embeddings attivi, **una**
  chiamata Ollama per **ogni** Specifica → con ~3.300 record la ricerca diventa migliaia di POST
  sincroni. Oggi "regge" solo perché scatta il fallback lessicale quando l'embedding della query
  fallisce.

### MEDIA
- **M1** manca `UniqueConstraint(codice, revisione)` su `Specifica` (rischio integrità 3.300 record).
- **M2** `stato_precedente` è **uno slot unico** condiviso sospensione/errore: S3→sospendi→S5→errore→
  S9→ripristina_da_errore→S5 lascia `stato_precedente='sospeso'` e `ripristina` fallisce → **spec
  intrappolata in S5**.
- **M3** `errore_tecnico` **non mette in pausa il timer** (il doc CONFORMITA §4 dichiara "pausa in S9 ✅":
  divergenza doc↔codice; il tempo in S9 conta verso reminder/escalation).
- **M4** `mod133_approva` **non atomica**: salva esito/approvatore/data **prima** della transizione; se
  questa fallisce restano su DB `esito='approvato'` + data per un flow-down mai approvato (elenco mostra
  "Approvato" con spec in S2). Nessun `transaction.atomic`; non verifica `data_chiusura_compilazione`.
- **M5** supersessione non atomica (prev→S4 dentro la transizione, nuova salvata dopo dal chiamante).
- **M6** numerazione OFI MAX+1 con race (select_for_update sulla riga, non sul contatore) → due OFI
  concorrenti possono ottenere lo stesso numero MOD.174.
- **M7** `approva_azione_ofi` non controlla lo stato → azione già approvata ribaltabile; `esito` default
  "approvata" se il parametro manca; `invia_in_approvazione` è codice morto.
- **M8** audit **fail-open** incoerente: `_log_evento` (ofi/distribuzione/scadenze) inghiotte le
  eccezioni con `logger.debug` → OFI/distribuzioni/timer possono avvenire **senza traccia**; in
  contrasto `share_write` tratta il fallimento audit come fatale.
- **M9** audit `--forza`: `piano.collisione_a` non aggiornato al path anti-collisione reale → payload può
  registrare un percorso inesistente.
- **M10** "audit immutabile" aggirabile: i guard valgono a livello istanza; `queryset.update/delete` e la
  **CASCADE da Specifica** li bypassano; `SpecificaAdmin` non disabilita la delete → cancellare una
  Specifica da admin **distrugge l'audit trail**.
- **M11** `PDF_OWNER_PASSWORD` default `""`: composito "protetto" con owner-pw **vuota** (sbloccabile da
  chiunque) senza warning/rifiuto.
- **M12** 500 su `?dal=`/`?al=` invalidi in `lista` (ValidationError non gestita).

### BASSA
B1 `stato_precedente` fuori dallo snapshot · B2 Content-Disposition da codice utente · B3 catena
revisioni segue solo il primo successore · B4 `attacca_pdf` legge path senza allowlist (CLI) ·
B5 `ChiusuraCompilazioneForm` mai usato · B6 evento audit creato prima del save del chiamante ·
B7 claim TOCTOU · B8 badge da string-matching · B9 query MOD133 ridondante.

## 4. Sicurezza
**Bene**: binding ACL v2 completi per tutte le route SSR; allowlist share usata **coerentemente** da
tutti i lettori (download/copilota/composito/detector/deposito); storage cifrato; CSRF sull'API;
middleware core risponde JSON 401/403; AI on-prem propone-e-non-salva. **Gap**: A1 (dominante),
PERM_DEROGA definito ma non enforced, M10 (cancellazione cascata audit), M11 (owner-pw vuota).

## 5. Pipeline PDF/share (F1-F6a)
F1 detector, F3 toolkit, F4 renderer, F6a composito: **solidi** (read-only garantito, errori espliciti,
rete anti-LayoutError, filigrana best-effort). F2 deposito: rollback **realmente sicuro per i casi
coperti** e testato; restano M9, assenza di lock su depositi concorrenti (accettabile in CLI, **da
risolvere prima di F6b**), e nessun alert operativo se il rollback dell'undo fallisce. Le decisioni
LOCKED del PIANO sono rispettate nel codice.

## 6. Copiloti AI
Fail-safe verificato; human-in-the-loop reale (nessun endpoint scrive). Debolezze: le righe proposte
**non sono inseribili con un click** nel formset (l'operatore ricopia a mano → adozione bassa); cap
diff 60 blocchi/6000 char può troncare senza segnalarlo; nessun indice di confidenza/provenienza. Il
problema serio è A3 (performance, non privacy).

## 7. Conformità al workflow (vs CONFORMITA_MATRICE_ARXIVAR.md)
S1-S9 e transizioni ✅, ma il doc **sovrastima** su due punti: la pausa timer in S9 **non esiste** (M3);
la coerenza FSM vale solo per `stato`, **non** per i dati satellite (righe MOD.133/esito/distribuzioni),
che restano modificabili fuori stato (A2/M4/M7) — per un auditor "stato congelato" ≠ "modulo congelato".
Separazione compiti conforme sul MOD.133, **non** sulla deroga copie (PERM_DEROGA non agganciato) né sul
sotto-flusso OFI. Copie controllate: algoritmo+deroga ok, ma manca il **registro per singola copia** e il
blocco distribuzione fuori S3. **Riesame periodico**: `esegui_verifica_periodica` **auto-avanza**
`data_verifica` dopo la sola notifica (attore=None) → è un promemoria, non un riesame firmato (gap non
rilevato dal doc F7).

## 8. UX, test, manutenibilità
UX curata (pill, stepper, timeline, modale OFI, banner deroga progressivo); difetti minori (filtri
data persi nel toggle storico; "Sospendi/Riprendi" in elenco sono link alla scheda; righe senza
supporto tastiera/aria; `specifica_form`/`ricerca` con layout più povero pre-redesign; proposte AI non
inseribili con un click). **Test**: forti sulla logica pura; lacune sistematiche → **tutte le view/API
testate con superuser** (per questo A1 è passato inosservato), nessun test negativo "azione nello stato
sbagliato", nessun test di concorrenza. **Manutenibilità**: buona nei servizi; `views.py` monolitico
(829 righe), CSS inline massiccio, filtro `|cut:"S1 · "` ripetuto in 6 template.

## 9. Raccomandazioni prioritizzate
| # | Azione | Impatto | Sforzo |
|---|--------|---------|--------|
| 1 | **API ninja sotto ACL v2** (A1): prefisso in `API_ACL_GATE_PATHS` + check permesso per azione in `transizione_specifica` + test con utenti non-superuser | Alto (sicurezza + feature oggi morta in prod) | Basso |
| 2 | **Guard di stato server-side + congelamento post-approvazione** (A2): compila/chiudi/claim solo S2, distribuzione solo S3, OFI negli stati previsti; vietare/auditare modifiche righe dopo `data_approvazione` | Alto (EN 9100 + integrità composito F6a) | Medio |
| 3 | **Atomicità approvazione** (M4/M5): `transaction.atomic`, transizione prima della persistenza esito; stesso perimetro per la supersessione | Alto | Basso |
| 4 | **`UniqueConstraint(codice, revisione)`** + validazione form (M1), previa deduplica prod | Medio-alto | Basso-medio |
| 5 | **Fix FSM**: slot separato pre-errore (M2) + pausa timer in `errore_tecnico` (M3) — o correggere il doc | Medio | Basso |
| 6 | **Audit fail-closed** (M8/M10): `_log_evento` a warning+alert (o in transazione); `EventoSpecifica.specifica` `on_delete=PROTECT` o delete disabilitata in admin | Medio | Basso |
| 7 | **Ricerca semantica**: pre-calcolare/cacheare gli embedding, mai N+1 HTTP per richiesta (A3) | Medio | Medio |
| 8 | **Guard `PDF_OWNER_PASSWORD` vuota** (M11) + numerazione OFI serializzata (M6) + stato-guard su `approva_azione_ofi` (M7), prima di F6b | Medio | Basso |

**Sintesi**: i mattoni (share, PDF, FSM, audit, AI) sono di qualità alta e spesso testati
avversarialmente; il rischio vero è che il **perimetro applicativo** (API, stati nelle view, atomicità,
unicità) si affidi oggi più alla UI e alla buona fede che al server — e va rinforzato **prima di F6b**,
che darà al portale il potere di scrivere i documenti ufficiali sulla share.
