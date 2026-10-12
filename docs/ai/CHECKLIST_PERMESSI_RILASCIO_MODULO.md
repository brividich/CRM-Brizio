# Checklist permessi prima di rilasciare un modulo

Da fare in UAT con gli utenti di prova (`manage.py permessi_utenti_prova --password <pwd> --forza`,
uno per ruolo: `prova.<ruolo>@example.local`). Dati sintetici, mai persone reali.

## Prima
- [ ] Il modulo ha `registro_permessi.py` e `core.tests_permessi` è verde.
- [ ] I record salvano il proprietario (`utenti.id`); lo storico senza proprietario è stato valutato.
- [ ] Matrice compilata per i ruoli che devono usarlo (scheda «Matrice dei ruoli»).
- [ ] «Sincronizza i permessi delle pagine» eseguito dopo il deploy.
- [ ] Voce di menu configurata nel Navigation Builder.

## Per ogni ruolo coinvolto (entra come `prova.<ruolo>`)
- [ ] La voce di menu compare solo ai ruoli previsti.
- [ ] La lista mostra solo i record giusti: propri / del team / tutti.
- [ ] Aprendo a mano l'URL di un record non visibile → «Accesso negato» con l'invito a contattare il reparto IT.
- [ ] I pulsanti di azioni non concesse non compaiono, e la POST diretta all'URL risponde 403.
- [ ] Le API del modulo rispondono JSON 401/403, mai una pagina HTML.
- [ ] Esportazioni (CSV, Excel, PDF): negate a chi non può esportare; chi può esporta solo i record che vede.
- [ ] Ricerca globale, conteggi della home e notifiche non mostrano record non visibili.
- [ ] L'Assistente AI, interrogato sul modulo, risponde solo nei limiti del ruolo (e rifiuta per `prova.dipendente` se non vede il modulo).

## Casi da provare sempre
- [ ] `prova.dipendente` (nessun ruolo): solo i propri dati.
- [ ] `prova.direzione`: vede ed esporta tutto, nessun pulsante di modifica.
- [ ] Persona con due ruoli: decide quello con ordine più alto (scheda «Cosa vede questa persona»).
- [ ] Responsabile/Preposto con un team d'organigramma: vede il team, non gli altri reparti.

## Dopo
- [ ] Scheda «Registro modifiche»: le modifiche fatte risultano con autore e data.
- [ ] `manage.py permessi_utenti_prova --elimina --forza` in UAT.
