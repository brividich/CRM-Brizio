# AGENTS.md

This project uses Claude-style configuration.

Read `CLAUDE.md` first for the lightweight operational rules.

Do not read all docs automatically. Open only the `docs/ai/*.md` files relevant to the current task.

## Shared Workspace Agent Protocol

Questo progetto può essere usato in modalità cartella condivisa, senza Git e senza GitHub.

Le modifiche ai file sono reali, immediate e visibili agli altri utenti/agenti.

La modalità raccomandata è aprire VS Code tramite:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\open-agent-workspace.ps1 -Owner "Collega HR" -Agent "Claude" -Area "django_app/anagrafica"
```

Non aprire direttamente VS Code quando si lavora in modalità agente condivisa.

Prima di modificare qualsiasi file, l'agente deve leggere:

- `session_checkpoint.md` se presente, poi solo il delta di `CHANGELOG.md` e `_AGENT_CONTROL/AGENT_CHANGELOG.md` rispetto al checkpoint
- `_AGENT_CONTROL/ACTIVE_SESSION.md`
- `_AGENT_CONTROL/WORK_LOCKS.md`
- `_AGENT_CONTROL/CRITICAL_FILES.md`
- `_AGENT_CONTROL/CRITICAL_CHANGE_REQUESTS.md`
- `_AGENT_CONTROL/AGENT_CHANGELOG.md`

Regole:

1. Non modificare file se esiste una sessione attiva incompatibile.
2. Non modificare aree bloccate in WORK_LOCKS.md.
3. Vedere sezione **File critici** per la policy sui file critici.
4. Non cancellare codice legacy senza autorizzazione.
5. Non riscrivere interi file senza motivo.
6. Non formattare file non correlati.
7. Non modificare .env, segreti, certificati, database locali, media privati.
8. Non introdurre nuove dipendenze senza autorizzazione.
9. Aggiornare sempre `_AGENT_CONTROL/AGENT_CHANGELOG.md` a fine sessione.
10. Aggiornare `session_checkpoint.md` a fine sessione con le nuove voci viste o aggiunte.
11. Aggiornare README.md e CHANGELOG.md quando cambia il comportamento operativo del progetto.

## File critici

I file elencati in `_AGENT_CONTROL/CRITICAL_FILES.md` sono considerati critici perché possono impattare sicurezza, routing, ACL, configurazione, navigazione globale o comportamento generale del portale.

Gli agenti possono modificarli solo se strettamente necessario per completare il lavoro richiesto.

Ogni modifica a file critici deve essere documentata obbligatoriamente in:

- `_AGENT_CONTROL/AGENT_CHANGELOG.md`

La documentazione deve indicare:

- file critico modificato
- motivo tecnico
- descrizione precisa della modifica
- impatto previsto
- eventuali rischi residui
- test/check eseguiti
- note per l'altro agente o per Brizio

Se la modifica riguarda ACL, middleware, settings, routing globale, autenticazione, permessi o navigazione globale, l'agente deve evidenziarlo anche nel riepilogo finale.

Se la modifica è dubbia, invasiva o rischiosa, l'agente deve chiedere conferma verbale a Brizio prima di procedere.

È vietato modificare file critici di passaggio, per sola formattazione, refactor non richiesto o pulizia non necessaria.

Perimetro Collega HR:

- `django_app/anagrafica/**`

Qualsiasi modifica a core, config, admin_portale, assenze, timbri, assets, ACL, middleware, navigazione globale o settings richiede autorizzazione esplicita.

Output finale obbligatorio per ogni sessione agente:

- riepilogo modifiche
- file modificati
- file critici modificati (con dettagli)
- backup creati
- README aggiornato sì/no
- CHANGELOG aggiornato sì/no
- AGENT_CHANGELOG aggiornato sì/no
- test/check eseguiti
- esito
- rischi residui
- note per altro agente

## Recupero sessione bloccata

Se `agent-session.ps1 status` mostra `| Stato | IN_CORSO |` ma VS Code è stato chiuso o la sessione non è più reale:

```powershell
cd "Y:\Portale Novicrom"
.\scripts\agent-session.ps1 force-end -Owner "Brizio" -Force
```

Per reset d'emergenza (solo se `ACTIVE_SESSION.md` è incoerente):

```powershell
.\scripts\agent-session.ps1 reset -Force
```

Il comando `status` rileva automaticamente sessioni stale (avvio > 8 ore: avviso rosso; > 2 ore: avviso giallo) ma non chiude mai la sessione in modo autonomo.
