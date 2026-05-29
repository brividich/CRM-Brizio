# Automation package pronti all'import

Questa cartella contiene esempi operativi di file `.automation_package.json`
importabili da NOVICROM HUB in:

`Automazioni -> Regole -> Importa package`

I package sono coerenti con `docs/ai/AUTOMATION_PACKAGE_REFERENCE.md` e vengono
importati dal portale come regole draft/inattive: dopo l'import vanno verificati
nel designer, eventualmente adattando destinatari, template e canali.

## Flussi inclusi

- `assenze_approvazione_caporeparto.automation_package.json`
  - Sorgente: `assenze`
  - Trigger: nuova richiesta assenza non bypassata
  - Azioni: approvazione via email al caporeparto, notifica al dipendente,
    aggiornamento `moderation_status`, log audit.

- `assenze_calendario_avviso_inserimento.automation_package.json`
  - Sorgente: `assenze`
  - Origine: export Power Automate `BCK - Calendario assenze - avviso di inserimento.json`
  - Trigger: nuova richiesta assenza, cambio stato approvazione, casi malattia,
    flessibilita e assemblea sindacale
  - Azioni: approvazione via email, aggiornamento `moderation_status`, email di
    avviso, split multi-giorno con `split_assenza_giornaliera` e log.

- `tickets_notifiche_operativi.automation_package.json`
  - Sorgente: `tickets`
  - Trigger: nuovo ticket critico, nuovo ticket con impatto sicurezza, cambio stato
  - Azioni: email ai gruppi operativi/richiedente e log.

- `dpi_richiesta_stato.automation_package.json`
  - Sorgente: `dpi`
  - Trigger: nuova richiesta DPI e cambio stato
  - Azioni: email a gestori/richiedente e log.

- `offboarding_notifiche_hr_it.automation_package.json`
  - Sorgente: `anagrafica_offboarding`
  - Trigger: apertura pratica e chiusura pratica
  - Azioni: email HR/IT e log.

- `formazione_completamento_hr.automation_package.json`
  - Sorgente: `anagrafica_formazione_record`
  - Trigger: nuovo record completamento corso
  - Azioni: email HR Formazione e log.

- `visite_mediche_esiti_critici.automation_package.json`
  - Sorgente: `anagrafica_visite_mediche`
  - Trigger: nuova visita con esito di non idoneita
  - Azioni: email HR/RSPP e log.

- `rentri_movimenti_da_trasmettere.automation_package.json`
  - Sorgente: `rentri`
  - Trigger: nuovo movimento consolidato da trasmettere
  - Azioni: email HSE/Ambiente e log.

## Note operative

- Gli indirizzi email sono mailbox di ruolo placeholder coerenti col dominio
  aziendale. Prima dell'attivazione verificare destinatari reali e alias.
- I package non contengono segreti, URL webhook o token.
- Le regole vengono importate come draft inattive dal portale: attivarle solo dopo
  dry-run e verifica con payload reale o di test.
