# Asset Assignment + SharePoint Patch Todo

Data: 2026-05-08

> **Obsoleto per la parte SharePoint (2026-08-06).** L'integrazione SharePoint del
> modulo assets e stata rimossa: l'archivio documenti e interamente locale. Le voci
> qui sotto su cartelle/percorsi SharePoint restano solo come traccia storica.
> Restano valide le parti su assegnazione e planimetria.

## Incluso in questa patch

- [x] Assegnazione asset da anagrafica dipendenti, con ricerca client-side nel select.
- [x] Assegnazione alternativa a reparto intero per macchine condivise, CNC, totem e asset non personali.
- [x] Autocompilazione di `assignment_to`, `assignment_reparto`, `assignment_location` da dipendente o reparto.
- [x] Spunta `Inserisci nella piantina` nei form asset/macchine: crea un marker sulla planimetria attiva.
- [x] Modalita `Cartella SharePoint automatica`: il portale calcola il percorso da root configurata, reparto e ID asset.
- [x] Default root SharePoint se mancanti: `Asset/Inventario` e `Macchine`.
- [x] Preview del percorso SharePoint automatico nei form asset/macchine.
- [x] Guida operativa cartelle SharePoint: `docs/assets/SHAREPOINT_CARTELLE_ASSET_GUIDE.md`.
- [x] Test mirati per assegnazione anagrafica, assegnazione reparto, marker planimetria e path SharePoint automatico.

## Da valutare dopo feedback utente

- [ ] Endpoint AJAX dedicato per ricerca dipendenti anagrafica quando l'elenco supera 1000 nominativi.
- [ ] Scelta esplicita della planimetria/area in cui inserire il marker, invece del primo layout attivo.
- [ ] Posizionamento assistito del marker subito dopo il salvataggio, con redirect all'editor planimetria.
- [ ] Comando di riallineamento massivo per compilare cartelle SharePoint automatiche sugli asset esistenti.
- [ ] Coda retry per sync documenti SharePoint falliti temporaneamente.
- [ ] Storage privato dedicato per `AssetDocument`, come proposto in `SHAREPOINT_UPLOAD_REVIEW.md`.
