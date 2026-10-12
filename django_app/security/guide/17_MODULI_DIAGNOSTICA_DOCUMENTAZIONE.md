# Moduli, diagnostica e documentazione

Tre pagine di controllo per chi configura il SOC: servono a capire se ogni fonte di dati è collegata bene e, quando qualcosa non arriva, dove si è fermato. Si aprono solo con il permesso di configurazione. Da **Config** e da **Autoconfig** si arriva alla diagnostica; dalla pagina **Moduli** si arriva a diagnostica e documentazione.

## Moduli

La pagina **Moduli gestiti** elenca le fonti di dati del SOC, una scheda per ciascuna: WatchGuard, Microsoft Defender, Backup/NAS, Microsoft 365, Caricamento manuale, Email generica. È in sola lettura: si guarda qui, si corregge in **Config**.

Ogni scheda ha uno stato:

| Stato | Cosa vuol dire |
| --- | --- |
| **OK** | C'è almeno una sorgente attiva, un parser attivo e le regole alert del modulo |
| **Attenzione** | Il modulo è configurato a metà: manca la sorgente o il parser attivo, oppure c'è un avviso |
| **Disattivato** | Nessuna sorgente e nessun parser attivi: il modulo non riceve dati |
| **Configurazione errata** | Qualcosa è incoerente e va corretto, per esempio un parser che non esiste più |

Sotto lo stato c'è il motivo in chiaro: è la prima cosa da leggere.

### La scheda del modulo

Aprendo un modulo si vede tutto quello che lo riguarda, nell'ordine in cui i dati passano:

1. **Sorgenti**: da dove arrivano i report e ogni quanto dovrebbero arrivare (**Frequenza attesa**).
2. **Parser**: chi legge il report e lo trasforma in dati, con la priorità se più parser possono leggere lo stesso report.
3. **Regole alert**: su quale metrica scattano, con quale soglia e gravità, e se aprono il ticket da sole.
4. **Soppressioni che influenzano questo modulo**: le regole che fermano alert di questo modulo, con scadenza e quante volte hanno fermato qualcosa.
5. **Riepilogo alert** e **Riepilogo ticket** ancora aperti.
6. **Job backup attesi** (solo Backup/NAS): i job che devono girare e dopo quanto tempo senza esito vengono segnalati come mancanti.
7. **Ultimi report** arrivati, con l'esito della lettura.
8. **Avvisi e configurazioni errate**: l'elenco completo di cosa non va.

In fondo c'è il capitolo della guida dedicato al modulo.

## Diagnostica

La **Diagnostica** controlla tutta la catena in un colpo solo. Va aperta dopo il primo setup, dopo una modifica a parser, regole o notifiche, e prima di fidarsi di una sorgente nuova.

### Controllo salute

In alto dieci riquadri, ognuno con stato **OK**, **Attenzione** o **Errore**:

| Riquadro | Cosa controlla |
| --- | --- |
| Database e Migrations | Il database risponde e le tabelle del SOC sono aggiornate |
| Security config seeded | La configurazione di base è stata caricata (se no: **Autoconfig**) |
| Parser registry | Ogni parser presente nel codice ha la sua configurazione |
| Alert rules | Esistono le regole per gli allarmi critici |
| Suppression rules | Non ci sono soppressioni scadute ancora attive |
| Backup expectations | Sono configurati i job di backup attesi |
| Notification channels | I canali di notifica hanno i dati necessari |
| Recent parser errors | Report arrivati di recente che non si è riusciti a leggere |
| Recent alert generation | Il motore sta creando alert, cioè la catena è viva |

Sotto, la tabella **Diagnostica** riporta tutti i controlli, con il messaggio e l'**Azione suggerita**. Si parte dalle righe in **Errore**.

### Le tabelle di dettaglio

- **Diagnostica registro parser**: per ogni parser, se è configurato, l'ultima lettura riuscita e l'ultima fallita, quanti report ha letto, con quanti avvisi ed errori. La colonna **Flag** segnala i casi strani, per esempio un parser spento mentre arrivano report che dovrebbe leggere.
- **Diagnostica regole alert**: per ogni regola, quando è scattata l'ultima volta, quante volte, cooldown e deduplica, se apre il ticket.
- **Diagnostica soppressioni**: responsabile, scadenza e occorrenze di ogni soppressione, con i flag. Tra i controlli generali, una soppressione troppo larga sugli allarmi critici viene segnalata.
- **Diagnostica backup** e **Diagnostica notifiche**: job attesi e canali, con i loro flag.
- **Attività recente**: gli ultimi report, messaggi e file arrivati, con lo stato.

### Provare se una mail viene riconosciuta

**Matching sorgenti** risponde alla domanda «se arriva questa mail, il SOC la riconosce?». Scrivi **Mittente** e **Oggetto** (e se serve un pezzo del **Corpo**) di una mail di esempio, poi **Test corrispondenza**. La tabella mostra per ogni sorgente se corrisponde e perché: il pattern sul mittente, quello sull'oggetto, oppure nessuno. Il test non salva nulla e non crea alert.

Se nessuna sorgente corrisponde, correggi i pattern della sorgente in **Config › Sorgenti** o in **Caselle mail**. Per i casi più comuni vedi [Risoluzione problemi](/soc/docs/09-troubleshooting/).

## Documentazione

La pagina **Documentazione** elenca tutti i capitoli della guida del SOC, con l'argomento e quando usarli: architettura, guida admin, moduli, configurazione, risoluzione problemi, runbook. Un clic apre il capitolo.

Le guide d'uso per chi lavora nel SOC ogni giorno sono in cima alla pagina **Guida** del menu. Da ogni pagina del SOC il pulsante **?** apre il paragrafo che spiega quella pagina.
