# Qualifiche & Certificazioni — Roadmap & registro implementazioni

Registro unico del mini-modulo **Qualifiche** (dropdown subnav dedicato in anagrafica).
Tieni qui lo stato delle fasi e le decisioni di design; i dettagli "diffusi" restano in
`CHANGELOG.md` / `README.md` / `LINKS_ANAGRAFICA.md`.

## Principio cardine (non negoziabile)
**Single source, niente duplicazione.** Tutto ruota su 3 modelli esistenti:
`TipoQualifica`, `DipendenteQualifica`, `QualificaSessione` — le stesse fonti usate da
Formazione, `matrice_competenze`, `conformita_report` e dalla scheda dipendente. Ogni
nuova feature *aggrega o arricchisce* questi modelli; ciò che cambia in un punto si
riflette ovunque.

## Stato fasi

| Fase | Contenuto | Stato | Migration |
|---|---|---|---|
| 1 | Cruscotto + Scadenzario dedicato (sole viste di aggregazione) | ✅ fatto | `0064` (dati, subnav) |
| 2a | Evidenza documentale + estremi (n°/livello/ente) + verifica HR | ✅ fatto | `0065` (additiva) |
| 2b | Rinnovo guidato (prefill estremi) | ✅ fatto | nessuna (solo view/UX) |
| 2c | Storico rinnovi esplicito (Opzione 1) | ✅ fatto | `0066` (additiva, 1 tabella) |

Scadenze/promemoria email: **già in `automazioni`** (`report_scadenze_settimanale` +
pacchetto `au12`), non reimplementate.

---

## Fase 2b — Rinnovo guidato ✅ FATTO

Il "↻ Rinnova" nella scheda dipendente ora **precompila** il form con gli estremi della
qualifica corrente (numero/livello/ente via `data-*`), imposta `data_conseguimento = oggi`
e lascia ricalcolare la scadenza da `durata_mesi`. Solo front-end (nessuna migration), il
modello regge già tutto.

**Follow-up ✅ FATTO:** scadenzario e «scadenze urgenti» del cruscotto hanno una colonna
**Azioni** con «↻ Rinnova» (deep-link `?rinnova=<tipo_id>` → la scheda auto-apre il form
prefillato). Nella scheda, per le qualifiche legate a un corso (`TipoQualifica.corsi`),
link «📚 Iscrivi a un'edizione …» verso il dettaglio corso.

---

## Fase 2c — Storico rinnovi esplicito ✅ FATTO (Opzione 1)

Scelta confermata: **Opzione 1 — storico append-only**. Nuova tabella
`DipendenteQualificaStorico` (FK alla qualifica + snapshot: `data_conseguimento`,
`data_scadenza`, `numero`, `livello`, `ente`, `note`, `origine`, `registrato_da/_il`),
scritta da `_upsert_dipendente_qualifica` a ogni rilascio/rinnovo con **dedup** contro
l'ultima riga identica (evita doppioni su re-import idempotenti). `origine` distingue
manuale / sessione / import.

La `DipendenteQualifica` resta **la fonte unica dello stato corrente**:
`matrice_competenze`/`conformita_report`/`import_asr` non sono toccati. La timeline è
visibile nella scheda dipendente sotto ogni qualifica (`<details>` "↻ Storico rinnovi (N)",
mostrato quando ci sono ≥2 eventi).

**Evidenza storicizzata (migration `0067`):** ogni riga di storico conserva anche il **file**
dell'evidenza di quel rinnovo (`documento`/`documento_nome_originale`), associato
condividendo il path del file corrente (nessuna copia fisica). Così quando un rinnovo
successivo sovrascrive l'evidenza del record corrente, il file precedente resta
referenziato dallo storico. Download via `dipendente_qualifica_storico_evidenza`
(ACL admin/HR + audit); link «📎 Evidenza» per riga nella timeline. Il dedup dello storico
considera anche il nome file.

*(Opzione 2 — più record con "corrente=ultimo valido" — scartata: avrebbe toccato
matrice/conformità/upsert/import ovunque, rischio alto senza benefici aggiuntivi.)*

---

## Decisioni registrate
- 2026-06-19 — Scadenze qualifiche: **riuso** del report `automazioni`, non reimplementate.
- 2026-06-19 — Fase 2a: campi su `DipendenteQualifica` (single-source), evidenza su storage
  privato fuori webroot, nuova evidenza azzera la verifica HR.
- 2026-06-19 — Fase 2c: **scelta Opzione 1** (storico append-only). Tabella
  `DipendenteQualificaStorico` scritta dall'upsert con dedup; record corrente resta fonte unica.
- 2026-06-19 — Fase 2b: rinnovo guidato = prefill estremi nel form (front-end), nessuna migration.
