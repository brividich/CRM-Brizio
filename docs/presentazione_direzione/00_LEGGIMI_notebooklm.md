# Pacchetto presentazione NOVICROM HUB — istruzioni

Questa cartella contiene due deliverable per presentare il portale alla direzione:

1. **`deck_novicrom_hub.html`** — presentazione a schermo, sfogliabile (frecce / spazio / clic
   sulla barra laterale). Aprila con un doppio clic: si apre nel browser, poi metti a schermo
   intero (F11) per presentare. Nessuna installazione, funziona offline.

2. **`01`–`05` (file `.md`)** — il *pacchetto-sorgente* da caricare su **NotebookLM** di Google
   per generare panoramica audio ("podcast"), FAQ e guida allo studio.

---

## Come usare NotebookLM (chiarimento importante)

NotebookLM **non si collega** direttamente a GitHub né a Claude: non esiste un connettore che
sincronizzi il repository. Il flusso corretto è **caricare manualmente** dei documenti come *sorgenti*.
Questi file `.md` sono esattamente quei documenti, già curati e privi di dati sensibili.

### Passi

1. Vai su **notebooklm.google.com** e accedi con un account Google.
2. Crea un nuovo notebook → **"Aggiungi sorgenti"**.
3. NotebookLM accetta: Google Docs/Slides, **PDF**, file di testo, **testo incollato**, URL, YouTube.
   I file `.md` di questa cartella vanno caricati come **testo**:
   - apri ciascun file, **copia tutto** il contenuto e incollalo come nuova sorgente "Testo copiato";
   - *oppure* converti prima i `.md` in PDF (in VS Code: estensione Markdown PDF, o "Stampa → Salva come PDF")
     e carica i PDF.
4. Con le sorgenti caricate, usa i pulsanti di NotebookLM:
   - **Panoramica audio** → genera un dialogo/podcast riassuntivo del portale;
   - **Guida allo studio / FAQ / Sequenza temporale** → materiali di supporto;
   - la **chat** per fare domande ("Quali moduli coprono la sicurezza?", "Cos'è l'ACL v2?").

> ⚠️ **Nota lingua**: chiedi esplicitamente a NotebookLM di produrre l'audio **in italiano**
> (nelle impostazioni della panoramica audio o scrivendolo nella richiesta), altrimenti tende all'inglese.

---

## Sicurezza dei contenuti

Tutti i documenti di questa cartella sono **sintetici e di alto livello**: non contengono credenziali,
dati personali, nomi reali, dump o segreti. Sono quindi caricabili su servizi esterni (NotebookLM)
senza problemi di privacy o GDPR. Non aggiungere a NotebookLM export di dati reali del portale.

---

## Ordine di lettura consigliato dei file

| File | Contenuto |
|---|---|
| `01_panoramica_novicrom_hub.md` | Cos'è, a cosa serve, numeri chiave, architettura in breve |
| `02_moduli_e_aree.md` | I 27 moduli raggruppati nelle 5 aree funzionali |
| `03_sicurezza_governance_compliance.md` | ACL v2, 2FA, audit, GDPR, sicurezza & compliance |
| `04_automazioni_e_ai.md` | Automazioni e Intelligenza Artificiale on-premise |
| `05_valore_direzione_faq.md` | Valore per la direzione + FAQ pronte per l'audio |
