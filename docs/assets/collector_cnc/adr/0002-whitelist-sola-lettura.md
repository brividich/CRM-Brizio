# ADR 0002 — Sola lettura garantita da whitelist, spia e controllo statico

Stato: accettata (27/10/2026)

## Contesto
Le macchine lavorano per aerospace e motorsport: il collector non deve mai scrivere sull'NC
(parametri, variabili, file, programmi, tabelle utensili, segnali PLC, start/stop/reset/selezione).
Una promessa nel README non basta: serve una garanzia verificabile.

## Decisione
1. **Proxy a whitelist** (`drivers/base.py`, `ProxySolaLettura`): ogni oggetto di libreria passa da un
   proxy che lascia leggere solo i nomi di un `frozenset`; il resto (lettura, scrittura o cancellazione
   di attributi) solleva `PermissionError`. Anche gli **oggetti derivati** sono avvolti: nodi OPC UA,
   oggetti dati di pyLSV2 (versioni, stack, override, messaggi), funzioni Fwlib.
   - OPC UA client: `connect`, `disconnect`, `get_namespace_array`, `get_node`, `read_attributes`,
     `read_values`; nodi: `nodeid`, `read_browse_name`, `get_children`, `read_value`. Nessuna
     sottoscrizione e nessun metodo (gli allarmi si leggono a polling): il collector non li usa.
   - LSV2: `connect`, `disconnect`, `versions`, `execution_state`, `program_status`, `program_stack`,
     `override_state`, `get_error_messages`.
   - Fwlib: `cnc_startupprocess`, `cnc_exitprocess` (solo Linux, ciclo di vita del processo),
     `cnc_allclibhndl3`, `cnc_freelibhndl`, `cnc_statinfo`, `cnc_exeprgname`, `cnc_actf`, `cnc_acts`,
     `cnc_rdparam` (il driver legge solo il parametro 6711).
2. **Spia** (`spia()`): nei test registra ogni accesso a un proxy durante esecuzioni complete contro
   i simulatori e verifica che l'insieme sia contenuto nella whitelist.
3. **Controllo statico** (`tests_cnc/test_sola_lettura.py`): identificatori, stringhe e commenti del
   package `drivers/` non contengono nessun nome di `collector_cnc/vietati.py` (`NOMI_VIETATI`,
   `PREFISSI_VIETATI`: `write_*`, `call_method`, `send_file`, `cnc_wr*`, `pmc_wr*`, `cnc_ds*`,
   upload/download…). L'elenco sta fuori da `drivers/` apposta.
4. Un test fissa le whitelist esatte: allargarle richiede di cambiare test e questo ADR.

## Note su pyLSV2
`safe_mode=False` serve solo perché la modalità sicura blocca il login DNC necessario a leggere lo
stato. `connect()` di pyLSV2 fa da sé il login INSPECT e FILETRANSFER (diritti di sessione: nessun file
viene trasferito, le funzioni di file non sono raggiungibili); con `compatibility_mode=True` non manda
i comandi di sistema per buffer e invio sicuro dei file.
