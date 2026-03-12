# Workflow Git del progetto Brizio-CRM

## Regole generali
- Non lavorare mai direttamente su `main`
- Base branch di sviluppo: `develop`
- Ogni attività va fatta su branch dedicato:
  - `feature/<nome>`
  - `fix/<nome>`
  - `hotfix/<nome>`

## Commit
Usare commit message nel formato:
- `feat(scope): descrizione`
- `fix(scope): descrizione`
- `refactor(scope): descrizione`
- `docs(scope): descrizione`
- `test(scope): descrizione`
- `chore(scope): descrizione`

Esempi:
- `feat(asset): aggiunge gestione asset inventory`
- `fix(acl): corregge controllo accessi topbar`
- `docs(release): aggiorna changelog 0.5.0-dev`

## Versioning
Usare:
- `MAJOR.MINOR.PATCH-dev` durante sviluppo
- `MAJOR.MINOR.PATCH` per release stabile

Regole:
- bugfix piccoli -> incrementa PATCH
- nuova funzione importante -> incrementa MINOR
- cambi strutturali/incompatibili -> incrementa MAJOR

## CHANGELOG
Aggiornare sempre `CHANGELOG.md` quando:
- viene completata una feature
- viene corretto un bug rilevante
- viene preparata una release

## Flusso operativo standard
1. Aggiorna `develop`
2. Crea nuovo branch
3. Implementa modifiche
4. Esegui test
5. Aggiorna `CHANGELOG.md`
6. Se richiesto, aggiorna `VERSION`
7. Crea commit
8. Esegui push del branch
9. Non fare merge su `main` senza conferma esplicita

## Regole di sicurezza
- Mai committare segreti, password, token, chiavi API
- Mai cancellare file massivamente senza conferma
- Mai eseguire merge su `main` senza conferma
- Mai fare push forzato senza conferma