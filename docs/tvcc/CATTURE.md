# TVCC — Catture SNMP (FASE 1, 14/10/2026)

Letture fatte dal PC del Reparto IT, solo GET / GETNEXT / GETBULK (nessuna SET).
Community e indirizzi reali non sono riportati qui. Fixture sanificate:
`django_app/contatori/fixtures/snmp/tvt_nvr_td3364h8.snmprec` e `tvt_ipc_generica.snmprec`.

## NVR TVT TD-3364H8-A3H-B (firmware 2.1.0.76943B250408)

- SNMP risponde solo sulla scheda della VLAN 23; sulla scheda della VLAN 24 no (v1/v2c/v3).
- Agent non conforme:
  - GET: risponde per gli OID che conosce. Per gli altri dà error-status 2 con varbind malformato
    (la libreria segnala «cannot unpack non-iterable Null object»).
  - GETNEXT: risposta con varbind vuoto, quindi `snmp_capture` (walk) non è possibile.
  - GETBULK: ignorato (timeout).
- Esposti: sysDescr (firmware), sysObjectID **come OCTET STRING** con il modello, sysUpTime,
  ifNumber = 2, ifDescr/ifType/ifSpeed/ifOperStatus/ifInOctets/ifOutOctets di eth0 (.1) ed eth1 (.2).
- Non esposti: sysContact/Name/Location, ifPhysAddress (MAC), errori/discard, ifXTable,
  ipAddrTable, HOST-RESOURCES, UCD (niente dischi, RAM o CPU).
- Fixture costruita dai valori GET (uptime arrotondato) e passata da `snmp_capture --sanitize-from`.

## Telecamere IP TVT

- SNMP spento di fabbrica; abilitato per la prova su una telecamera (v2c + v3).
- Il firewall lascia passare UDP 161 verso la VLAN 24 (risposta alla discovery SNMPv3).
- Agent net-snmp conforme (GETNEXT/GETBULK funzionano): walk completo in 0,1 s, 66 righe.
- sysDescr «Customer's IPCamera», sysObjectID `1.3.6.1.4.1.8072.3.2.10` (net-snmp Linux generico),
  sysName `localhost`, sysContact predefinito di net-snmp (oscurato nella fixture).
- sysUpTime = da quando è attivo il servizio SNMP, non dalla accensione della telecamera.
- Solo gruppi system, snmp, SNMP-FRAMEWORK/MPD/VACM: **nessuna IF-MIB** (niente MAC, velocità,
  stato del collegamento), nessuna risorsa.

## Decisioni conseguenti

- `tvt-nvr`: solo colonne GET verificate (velocità e stato di eth0/eth1, soglia «non attiva» = Attenzione).
- `tvt-ipc`: nessuna colonna, controllo di raggiungibilità ogni 30 minuti (decisione utente 14/10:
  pallino di stato nella lista asset e nel Monitor SNMP).
- Confronto MAC letto/dichiarato non applicabile agli apparati TVT (non espongono il MAC).
- Credenziali consigliate sulle telecamere: v3 `auth, priv` (SHA/AES) per l'esercizio; utente o
  community di scrittura diversi da quelli di lettura, lunghi e casuali, o non configurati.
