# `checklist_operativa`

Area **Sicurezza** · URL `/checklist-operativa/` · codice [`django_app/checklist_operativa/`](../../django_app/checklist_operativa/)

[← Catalogo moduli nel README](../../README.md#-catalogo-moduli)

## Sintesi

**Checklist Operativa**: digitalizza la checklist di chiusura aziendale (ferie/Natale...), ex file Excel. **Configurazione** (ACL `checklist_operativa.configurazione.manage`) per mansioni template + responsabile, **vice responsabili** (anche più di uno, coprono il titolare assente) e **reparto scelto dal catalogo anagrafica**, con il form che si apre in **popup** sulla pagina stessa (HTMX, stessa view e stessa validazione della pagina intera), e per creare **eventi di chiusura** storicizzati (generano subito le voci dai template attivi, vice compresi); **Gestione**, aperta a chiunque sia loggato, dove responsabile **e suoi vice** confermano i task assegnati (la voce di cui si è vice è marcata come tale, e `confermato_da` registra chi ha agito davvero) e si possono proporre nuove voci (coda di revisione); **Riepilogo** storico con % completamento e dettaglio conferme. Promemoria automatico (soglie 7/3/1/0 giorni) via django-q su **due canali**: notifica in-app per voce + **una sola email per responsabile** con l'elenco delle sue voci mancanti (a `email_notifica`; `--solo-notifiche` per il comportamento storico). Riepilogo di ogni chiusura **esportabile in PDF** per l'archiviazione. Un evento **chiuso è archiviato**: non riceve voci nuove e le sue conferme non si annullano più (il registro diventa storico), ma è **riapribile** dalla scheda evento, dietro lo stesso ACL e con traccia in audit; una proposta si decide una volta sola
