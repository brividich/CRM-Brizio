# Profili SNMP multi-produttore

## Scopo

Il catalogo in **Contatori → Profili SNMP** evita di inserire OID nel codice per ogni nuovo apparato. Comprende preset iniziali per stampanti/MFC, firewall, rete, server/hypervisor, NAS/storage e UPS dei produttori più diffusi. I prefissi enterprise derivano dal registro PEN IANA; le colonne comuni usano MIB standard.

## Flusso consigliato

1. Creare il dispositivo da **Monitor SNMP → Dispositivo** indicando almeno nome e IP.
2. Lasciare vuoto il profilo e premere **Interroga ora**: il portale legge `sysObjectID`, `sysDescr`, `sysName` e seriale, poi applica il profilo solo se il match è univoco.
3. Se l'autodetect non è conclusivo, scegliere il profilo nella scheda e premere **Applica**.
4. Gia' nella stessa interrogazione vengono lette e storicizzate le colonne del profilo. Gli apparati esistenti con profilo ma senza sonde vengono completati automaticamente al prossimo polling, preservando le sonde personalizzate o disattivate.

Per le stampanti (incluse le Kyocera TASKalfa 5054ci), la scheda dispositivo mostra automaticamente **Contatori e consumabili**: contatori cumulativi e livelli toner restituiti dalla Printer-MIB. Non occorre creare una seconda anagrafica MFC. Funziona anche con il polling pianificato esistente. Gli indici delle tabelle vengono scoperti dal dispositivo: ogni toner resta distinto e piu' motori di stampa non vengono sommati. Zero indica esaurito; valore sconosciuto o solo presenza non diventano percentuali inventate. Il blocco mostra data e dati dell'ultima interrogazione e uno storico delle ultime 20; dopo un errore non ripropone un vecchio livello come corrente. Le tabelle opzionali possono essere assenti e gli errori sono visibili senza nascondere gli altri dati.

Il supporto standard e' basato su [Printer-MIB, RFC 3805](https://www.rfc-editor.org/rfc/rfc3805.html); disponibilita' e dettaglio dipendono dalle tabelle esposte dal firmware, non dalla sola risposta SNMP. I contatori standard non separano automaticamente copie/stampe o A3/A4 e colore/BN.

I profili possono impostare versione, porta e timeout. Gli override del singolo apparato hanno precedenza ed è disponibile anche una community read-only dedicata; la community non viene mai inclusa nei preset.

## Profili precaricati

- Stampanti/MFC: Canon, Kyocera, HP, Ricoh, Xerox, Brother, Lexmark, Epson, Sharp, Konica Minolta, Toshiba, OKI, Samsung e Zebra.
- Firewall: Fortinet, Palo Alto Networks, Sophos, Check Point e SonicWall.
- Rete: Cisco, Juniper, MikroTik, Ubiquiti e HPE Aruba.
- Server/hypervisor: Dell, HPE, Lenovo, Supermicro, VMware, Microsoft e Net-SNMP/Linux.
- Storage: Synology, QNAP e NetApp.
- UPS: APC/Schneider, Eaton e Vertiv/Liebert.

Le colonne iniziali includono totale impressioni Printer-MIB, traffico IF-MIB, indicatori Host-Resources-MIB e batteria UPS-MIB. Il portale supporta `GET` su OID esatto e `WALK` su colonne, ridotte tramite primo valore, massimo, minimo o somma.

## MFC e contatori contrattuali

Il totale Printer-MIB non equivale automaticamente ai quattro contatori A4 BN, A3 BN, A4 colore e A3 colore. Per evitare errori di fatturazione, una MFC entra nelle letture mensili soltanto quando il profilo contiene una colonna esplicita per ciascuna chiave.

Il profilo Canon iR-ADV è già completo. Il profilo Kyocera generale riconosce la macchina e legge identità, seriale, consumabili e totale standard; per la ripartizione contrattuale occorre aggiungere al profilo del modello gli OID verificati sul dispositivo e assegnare a ciascuno la relativa chiave MFC.

## Creare o estendere un profilo

Da **Profili SNMP → Nuovo profilo** indicare produttore, categoria e almeno un criterio tra prefisso `sysObjectID` e pattern `sysDescr`. Aggiungere le colonne con OID numerico, tipo, modalità, aggregazione, unità e fattore. Per i contatori MFC scegliere anche la destinazione A4/A3 B/N/colore.

Applicare un profilo aggiorna o crea le sonde corrispondenti senza cancellare le sonde personalizzate estranee al profilo.

## Diagnostica

```powershell
python manage.py snmp_discover --host 192.0.2.10 --snmp-version v2c --timeout 10 --settings=config.settings.prod
```

Il comando mostra identità, seriale, profilo suggerito e, per le stampanti, il totale Printer-MIB. Con `--consumabili` legge anche la tabella consumabili. Una community errata in SNMPv1/v2c normalmente appare come timeout.

## Deploy

```powershell
python manage.py migrate contatori --settings=config.settings.prod
```

Le migrazioni 0008-0012 creano il catalogo e caricano i preset; la 0013 aggiunge lo snapshot stampante allo storico SNMP. Non servono nuove dipendenze né nuovi task Windows. Dopo il deploy riavviare web e qcluster esistenti e premere Interroga ora sulla Kyocera gia' configurata (oppure attendere il polling programmato).
