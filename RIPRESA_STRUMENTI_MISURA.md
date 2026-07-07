# RIPRESA — Modulo Strumenti di Misura (handoff conversazione)

**Ultimo aggiornamento:** 2026-07-06
**Scopo:** riprendere il lavoro sul modulo "Gestione Strumenti di Misura" da dove si è interrotto, senza rileggere tutta la conversazione. Il documento di merito è **[FATTIBILITA_STRUMENTI_MISURA.md](FATTIBILITA_STRUMENTI_MISURA.md)** (fattibilità completa, FSM proposta, effort, appendici A/B).

**Come riprendere:** aprire una sessione e dire — *«Riprendi il modulo strumenti di misura da RIPRESA_STRUMENTI_MISURA.md; il materiale è in `<cartella>`»* — indicando dove è stato depositato il materiale dell'Appendice B.

---

## Dove siamo

- ✅ **Analisi di fattibilità COMPLETATA** (2026-07-05): verdetto FATTIBILE, effort complessivo **L**, rischio tecnico basso, rischi di dominio concentrati su procedura/Codhex. Nessun codice scritto.
- ⏳ **In attesa del materiale** dall'utente (era atteso il 2026-07-06): checklist completa in **Appendice B** della fattibilità. I file vanno depositati **FUORI dal repo** (es. OneDrive `Documenti Portale Novicrom\strumenti_misura\`) — contengono dati reali, mai committarli.

## Decisioni già prese (NON rimetterle in discussione)

1. **Rapporti interni + archivio certificati esterni accreditati** (Brizio, 2026-07-05) — Novicrom NON emette certificati accreditati; l'ente taratore interno verifica e crea l'attestato. Un solo template di generazione; gli esterni si caricano e si validano. (§3.1 della fattibilità)
2. **Istruzioni operative / budget di incertezza NON esistono** (2026-07-06) — attestato v1 con campo incertezza facoltativo/vuoto; niente valori inventati. (§3.10)
3. **Etichette di taratura IN SCOPE** (2026-07-06) — area f), effort S: riusa il motore `AssetLabelTemplate` già in assets; regole proposte: ristampa a ogni taratura conforme, stampa bloccata fuori dallo stato `in_servizio`. (§2.f)

## Domande ancora aperte (da chiudere col materiale o a voce)

- **Firma**: attestato con firma singola o doppia (esecutore + responsabile)? Il portale deve imporre esecutore≠firmatario? Chi è l'ente taratore interno e coincide con i livelli U/O su «Taratura strumenti» della skill matrix? (§3.2)
- **Perimetro**: quali famiglie di strumenti e quanti (Codhex vs assets)? (§3.3)
- **FSM**: gli 8 stati proposti (§2.b) vanno **collimati su MT CN 68 Rev.7** — il testo non è nel repo, è nel corpus SGI sulla share. (§3.4)
- **Codhex**: discovery tecnica — checklist in **Appendice A**. Zero informazioni nel repo. (§3.5)
- **Automatismo sospensione a scadenza** sì/no (§3.6) · **regola decisionale conformità** (§3.7) · **NC retroattiva** (§3.8) · **numerazione attestati** (§3.11) · **storico: tutto o solo ultima taratura** (Appendice B).
- **Coordinamento**: refactor fusione `asset_category`+`asset_type` in corso in altra sessione → il modulo si aggancia via OneToOne, NON alla classificazione asset. (§3.9)

## Prossimi passi alla consegna del materiale (in quest'ordine)

1. **Leggere MT CN 68 Rev.7** → collimare la FSM 8 stati proposta (§2.b) e i campi obbligatori dell'attestato (§2.c); aggiornare la fattibilità dove diverge.
2. **Esaminare attestato interno reale + certificato esterno LAT** → congelare i campi dei template.
3. **Aprire l'export Codhex** → censimento incrociato Codhex↔`assets.Asset` (quanti strumenti già censiti, qualità dei codici) → **chiudere la forchetta L–XL** dell'area d) import.
4. **Etichette**: foto bollino + stampante → confermare effort S e formato di stampa.
5. Solo dopo: proporre **BUILD_SPEC** con fasi (convenzione `docs/specs/<modulo>/BUILD_SPEC.md + BUILD_LOG.md`, come gestione_specifiche e skill matrix). **Niente codice prima del BUILD_SPEC approvato.**

## Riferimenti tecnici chiave (per la prossima sessione)

- **Fattibilità completa**: [FATTIBILITA_STRUMENTI_MISURA.md](FATTIBILITA_STRUMENTI_MISURA.md) — ricognizione §1, modellazione §2.a, FSM §2.b, certificati §2.c, Codhex §2.d, ACL/report §2.e, etichette §2.f, effort §4.
- **Footprint riusabile già individuato**: `WorkOrder` KIND_CALIBRATION "Taratura" ([assets/models.py:1786](django_app/assets/models.py#L1786)); `PeriodicVerification` ([assets/models.py:1320](django_app/assets/models.py#L1320)); `AssetLabelTemplate` ([assets/models.py:1562](django_app/assets/models.py#L1562)); competenza «Taratura strumenti» I/L/U/O nella skill matrix (resolver read-only `anagrafica/services/skillmatrix_resolver.py`); pattern import con preview (`attrezzature` ImportBatch/ImportRow); FSM di riferimento `gestione_specifiche` (django-fsm-2, audit post_transition) **con i fix di ANALISI_02 F1/F2/F3 da incorporare dal giorno 1**.
- **Analisi collegate**: ANALISI_01_CORE_ACL.md (F4: IDOR download documenti asset — da sistemare prima di appoggiarci i certificati), ANALISI_02_MODULI_OPERATIVI.md (lezioni FSM/concorrenza).
- **Memoria di sessione**: `strumenti_misura_fattibilita.md` (indice memoria) — allineata a questo documento.

---

*Documento di solo handoff: nessun codice, nessuna modifica ai moduli esistenti.*
