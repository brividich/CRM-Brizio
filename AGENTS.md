# AGENTS.md

Le regole operative per tutti gli agenti (Claude, Codex e altri) sono in [`CLAUDE.md`](CLAUDE.md): leggilo per primo. Il contesto lungo è in `docs/ai/` ([indice](docs/ai/00_INDEX.md)): apri solo il file che serve al compito.

## Uso dei tool

- Per trovare simboli, classi, funzioni o configurazioni usa una ricerca testuale (`rg`, `git grep`, `Select-String`) invece di leggere file interi; dei file grandi leggi solo il contesto attorno al punto trovato.
- Non esplorare file estranei alla richiesta.
- Dopo un errore non ripetere la stessa chiamata identica: cambia parametri o strategia. Dopo 2 errori sullo stesso file, cambia approccio.

## File delicati

Settings, middleware, ACL, autenticazione, routing e navigazione globale incidono su tutto il portale:

- toccali solo se serve al compito, mai per formattazione o refactor non richiesti;
- non cancellare codice legacy e non aggiungere dipendenze senza autorizzazione di Brizio;
- segnala ogni modifica a questi file nel riepilogo finale e nel `CHANGELOG.md`; se è dubbia o invasiva, chiedi conferma prima.
