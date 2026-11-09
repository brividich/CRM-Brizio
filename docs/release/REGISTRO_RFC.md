# Registro delle Request For Change (MOD.172) del NOVICROM HUB

Una riga per RFC. Stati: aperta -> valutata (CISO) -> autorizzata (Governance) -> rilasciata -> chiusa; «respinta» o «annullata» chiudono senza rilascio. Per i cambi urgenti la riga nasce già «rilasciata» e va completata entro un giorno lavorativo. Nessun nome di persona: solo ruoli.

| RFC | Categoria | Versione | Commit in PROD | Aperta | Autorizzata | Rilasciata | Chiusa | Stato | Note |
|---|---|---|---|---|---|---|---|---|---|
| RFC 2026_11_09 - HUB | Normale, registrata come urgente (par. 9.3.7) | 1.9.1 (regolarizza 1.7.0-1.9.0) | `a0ae6a68` (tag `prod-v1.9.1`) | 09/11/2026 | in attesa: sezione CISO del MOD.172 da compilare | 09/11/2026 14:35, pacchetto `portale-novicrom-v1.9.1-20261109_142558.zip` | - | rilasciata | Primo rilascio con RFC. Collaudo eseguito direttamente in PROD perché TEST su NOVISQL non esiste (vedi AMBIENTE_TEST.md): da sanare con autorizzazione a posteriori e riesame post-rilascio entro il 12/11/2026. Tolte le righe `APP_VERSION` dal `.env` di PROD: la versione ora viene dal file `VERSION` del pacchetto. |

## Come si aggiorna

- **Apertura**: compila il MOD.172 in OneDrive (`Documenti/Portale Novicrom/ISO27001_Change_Management_HUB`) e aggiungi la riga con stato «aperta».
- **Autorizzazione**: data e riferimento (mail o firma sul MOD.172); stato «autorizzata».
- **Rilascio**: commit di `current\BUILD_INFO.json`, nome del pacchetto, data e ora; stato «rilasciata»; tag `prod-vX.Y.Z` pushato.
- **Chiusura**: dopo tre giorni lavorativi senza anomalie bloccanti, allega il riesame post-rilascio; stato «chiusa».
