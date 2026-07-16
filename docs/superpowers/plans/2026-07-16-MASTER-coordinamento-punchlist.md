# MASTER — Coordinamento punch-list ANAGRAFICA & moduli (6 stream paralleli)

> Documento di regia per eseguire in parallelo la punch-list del capo
> (`docs/ANAGRAFICA - PERSONE.md`) su più sessioni Opus. Ogni stream ha una sua
> **spec** + un suo **plan TDD** dedicati; questo file dice **come lanciarli**,
> **dove si toccano** e **in che ordine mergiare** su `main`.

Data: 2026-07-16 · Base: `origin/main`

---

## 1. Gli stream

| # | Stream | App / superficie | Worktree | Branch | Plan |
|---|--------|------------------|----------|--------|------|
| 0 | **Visite — Giornata visite** (già pianificato) | `anagrafica` (visite + scadenzario) | `C:\Dev\pn-visite-giornata` | `feature/anagrafica-visite-giornata` | `2026-07-16-visite-giornata-sessioni.md` |
| 1 | **Scadenzario & Formazione-sessione** | `anagrafica` (scadenzario, formazione) | `C:\Dev\pn-anag-scadenzario` | `feature/anagrafica-scadenzario-layout` | `2026-07-16-anagrafica-scadenzario-layout.md` |
| 2 | **Organigramma & Report** | `anagrafica` (organigramma, report, caporeparto) | `C:\Dev\pn-anag-organigramma` | `feature/anagrafica-organigramma-report` | `2026-07-16-anagrafica-organigramma-report.md` |
| 3 | **Formazione/Compliance UI & Impostazioni** | `anagrafica` (popup, qualifiche, sidebar) | `C:\Dev\pn-anag-formazione-ui` | `feature/anagrafica-formazione-ui-settings` | `2026-07-16-anagrafica-formazione-ui-settings.md` |
| 4 | **Assenze — regole durata** | `assenze` | `C:\Dev\pn-assenze-regole` | `feature/assenze-regole-durata` | `2026-07-16-assenze-regole-durata.md` |
| 5 | **Polish multi-app** (timbri, procedure_refresh, assets, kickoff) | 4 app distinte | `C:\Dev\pn-polish-multiapp` | `feature/polish-multiapp` | `2026-07-16-polish-multiapp.md` |
| 6 | **GCM — bug Gantt weekend** | `gcm` | `C:\Dev\pn-gcm-weekend` | `feature/gcm-gantt-weekend` | `2026-07-16-gcm-gantt-weekend-fix.md` |

Ogni plan ha la sua spec omonima in `docs/superpowers/specs/…-design.md`.

---

## 2. Matrice di conflitto (quali stream si toccano)

La regola: **app diversa ⇒ file disgiunti ⇒ nessun conflitto**. Il rischio è
concentrato nell'app `anagrafica`, condivisa da stream 0/1/2/3.

| File caldo | 0 | 1 | 2 | 3 | Rischio |
|---|:-:|:-:|:-:|:-:|---|
| `anagrafica/views.py` | ✎ | ✎ | ✎ | ✎ | **Alto** — funzioni diverse ma stesso file |
| `anagrafica/urls.py` | ✎ | ✎ | ✎ | ✎ | **Alto** — nuove `path()` in coda |
| `anagrafica/models.py` + migrazioni | ✎ (VisitaSessione) | forse (SessioneFormazione) | — | forse (choices qualifiche) | **Medio** — migrazioni concorrenti |
| `templates/.../scadenzario.html` | ✎ (↻ per gruppo) | ✎ (collapse/vista/↻ per visita) | — | — | **Alto** — 0 e 1 sullo stesso template |
| `CHANGELOG.md` / `README.md` | ✎ | ✎ | ✎ | ✎ | Basso (append, merge banale) |

- **Assenze (4)**, **polish (5)**, **GCM (6)**: nessuna intersezione con gli altri → paralleli puri.
- **Migrazioni anagrafica**: se 0/1/3 generano migrazioni, i numeri progressivi (`00NN_…`) collideranno. Non è un errore di merge git ma un conflitto di *dipendenza migrazioni*. Mitigazione in §4.

---

## 3. Come lanciare ogni sessione Opus

Per ciascuno stream, aprire una sessione Opus **dedicata** e darle:

```
Leggi ed esegui il plan `docs/superpowers/plans/<PLAN>.md`.
Usa lo skill superpowers:executing-plans (o subagent-driven-development).
Il Task 1 del plan crea il worktree dedicato: lavora SOLO lì, mai nel checkout
condiviso C:\Dev\Portale Novicrom. Venv assoluto:
& "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe".
A fine plan: commit su branch feature + push. NON mergiare in main da solo:
il merge lo coordina la sessione di regia.
```

Regole valide per tutte le sessioni (da CLAUDE.md):
- **Worktree dedicato**, mai `git checkout`/`switch` nel checkout condiviso.
- Mai `git add -A` / `git commit -a`: staging con percorsi espliciti.
- Test solo per l'app toccata, `--keepdb`, `--settings=config.settings.test`, timeout ≥ 600000 ms; **prima run dopo una migrazione senza `--keepdb`** (rimigra 6–8 min).
- CHANGELOG.md + README.md aggiornati nel task finale. **Niente version bump** (accumulo sotto `[Unreleased]`).
- Guard `ScheduleWakeup` su ogni lavoro in background.

---

## 4. Ordine di esecuzione e di merge

### Ondata A (partono subito, zero contese) — 4, 5, 6
`assenze`, `polish-multiapp`, `gcm`: app disgiunte. Si eseguono e si mergiano in
`main` appena verdi, in qualsiasi ordine. Nessun coordinamento.

### Ondata B (anagrafica, contesa su file condivisi) — 0, 1, 2, 3
Girano **in parallelo** ma il **merge è serializzato** da questa sessione di regia.
Ordine di merge consigliato (dal meno al più intrecciato sui file caldi):

1. **Stream 2** (organigramma/report) — tocca soprattutto file/template propri; minor intersezione.
2. **Stream 0** (visite giornata) — introduce `VisitaSessione` e il `↻ Rinnovo` **per gruppo** su `scadenzario.html`.
3. **Stream 1** (scadenzario layout) — costruisce SOPRA `scadenzario.html` (collapse/vista/↻ **per visita**): mergiare **dopo** lo 0 così il conflitto su quel template si risolve una volta sola, a favore della versione più ricca.
4. **Stream 3** (formazione UI/settings) — ultimi ritocchi UI; merge in coda.

**Migrazioni anagrafica**: mergiare uno stream alla volta e, dopo ogni merge, se
lo stream successivo aveva generato una migrazione con numero ora occupato,
**rigenerarne il numero** (`makemigrations` sul branch aggiornato, o rinominare la
dipendenza) prima del merge successivo. Non forzare merge di due `00NN` gemelle.

**Regola d'oro del merge:** dopo ogni merge in `main`, la sessione di regia lancia
i test dell'app toccata con `--keepdb` (dopo eventuale migrazione, senza) e procede
al merge successivo solo se verde.

---

## 5. Punti di coordinamento espliciti (da leggere nei plan)

- **`scadenzario.html` — stream 0 vs 1**: entrambi aggiungono un `↻ Rinnovo`
  (0 = per gruppo/tipo, 1 = per singola visita + collapse + toggle vista). Il plan 1
  deve dichiarare la dipendenza e assumere che il `tipo_id` sulle voci scadenza
  (introdotto dallo 0) esista già; se lo 0 non è ancora mergiato, il plan 1 lo
  introduce lui e in merge si tiene una sola versione.
- **Modello sessione formazione — stream 1**: se serve un `SessioneFormazione`,
  modellarlo sul pattern `QualificaSessione`/`VisitaSessione` (FK nullable, SET_NULL,
  additivo). Migrazione additiva, mai distruttiva.
- **`caporeparto` — stream 2**: la risoluzione del responsabile passa dall'area
  aziendale; se esiste un helper condiviso (`core/operational_roles.py`), correggere
  lì e verificare che non regredisca chi lo consuma (skill matrix, report).
- **Categoria "processi qualificati" — stream 3**: se è un `choices` sul model,
  serve migrazione dati/choices; coordinare che non collida con eventuali migrazioni
  di stream 1 (vedi §4).

---

## 6. Checklist di chiusura (sessione di regia)

- [ ] Ondata A mergiata e verde (4, 5, 6).
- [ ] Ondata B mergiata nell'ordine 2 → 0 → 1 → 3, con test verdi dopo ogni merge.
- [ ] `CHANGELOG.md` consolidato (risolti i merge di append).
- [ ] `README.md` catalogo moduli aggiornato dove le funzioni sono cambiate.
- [ ] Test mirati per-app tutti verdi; nessun working tree sporco nei worktree.
- [ ] Worktree rimossi (`git worktree remove` / `rmdir /s /q` + `git worktree prune`).
- [ ] Valutare bump versione unico a fine ondata (da checklist `docs/ai/06`).
- [ ] Deploy: nulla va in produzione finché non è su `release/prod` (packaging da branch).
