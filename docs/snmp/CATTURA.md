# Cattura walk SNMP — FASE 1

Il comando `snmp_capture` legge **tutto** l'albero SNMP di un apparato e lo salva in due file:
- `.snmprec`, nel formato di snmpsim, usato per i test offline;
- `.txt` leggibile, con i nomi MIB principali.

Serve una volta per famiglia, per verificare gli OID dei preset. Non fa parte del polling.

## Garanzie

- **Solo lettura.** Invia solo GETBULK (v2c/v3) o GETNEXT (v1). Un test (`ReadOnlyTests`) fallisce se nel modulo compare una SET.
- **Segreti fuori dai file.**
  - La community o le chiavi v3 non vengono mai scritte; se un valore letto contiene il segreto, viene sostituito con `***REDACTED***`.
  - Non vengono salvati: SNMP-COMMUNITY/USM/VACM/TARGET-MIB, argomenti dei processi (`hrSWRunParameters`), utenti Windows LanManager.
- **Limiti di sicurezza**:
  - default: timeout 3 s, 2 retry, max-repetitions 25 (dimezzato automaticamente se l'apparato risponde *tooBig*);
  - massimo 200.000 righe e 15 minuti per cattura;
  - interruzione se l'agente restituisce OID non crescenti.
- **Il walk grezzo non entra nel repository.** Il comando rifiuta un `--out` dentro il repo se manca `--sanitize`.

## Dove e come lanciarlo

Va lanciato da una macchina che raggiunge l'apparato su UDP/161 ed è autorizzata nella sua ACL SNMP.

Dal worktree della feature, con il venv condiviso:

```powershell
cd C:\Dev\pn-snmp-preset\django_app
$py = "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe"
New-Item -ItemType Directory -Force C:\snmp_capture | Out-Null
```

La community va passata in uno di questi modi, in ordine di preferenza:
1. `--community-id N`, dal catalogo cifrato. Richiede accesso al DB del portale: `--list-communities` mostra id e nome.
2. `--community-env SNMP_RO`, da una variabile d'ambiente impostata nella sola sessione:
   ```powershell
   $env:SNMP_RO = Read-Host "community"
   ```
3. `--community X`. Sconsigliato: resta nella cronologia della shell.

Gli esempi qui sotto usano la variabile d'ambiente e `--settings=config.settings.test`, che non richiede `.env` né il DB.

## Comandi per famiglia

Sostituisci `<ip>` con l'indirizzo dell'apparato.

| Famiglia | Comando | Note |
|---|---|---|
| Switch Aruba/HPE ProCurve (stack VSF core) | `& $py manage.py snmp_capture --settings=config.settings.test --host <ip-stack> --v2c --community-env SNMP_RO --out C:\snmp_capture\aruba_vsf.snmprec` | IP di management dello stack: un solo walk espone tutti i membri (ENTITY-MIB). La tabella MAC può essere grande: se la cattura risulta INCOMPLETA, aggiungi `--max-duration 1800`. |
| Switch Cisco SG250 | `… --host <ip> --v2c --community-env SNMP_RO --out C:\snmp_capture\cisco_sg250.snmprec` | Abilitare SNMP dalla GUI (Security → SNMP → Communities, accesso Read Only). |
| Firewall WatchGuard | `… --host <ip-interno> --v2c --community-env SNMP_RO --out C:\snmp_capture\watchguard.snmprec` | Su Fireware: System → SNMP, e una policy che permetta SNMP dall'host di cattura. |
| Host VMware ESXi | `… --host <ip-esxi> --v2c --community-env SNMP_RO --out C:\snmp_capture\esxi.snmprec` | Prima, sull'host: `esxcli system snmp set --communities <community> --enable true` e `esxcli network firewall ruleset set --ruleset-id snmp --enabled true`. |
| NAS Synology | `… --host <ip> --v2c --community-env SNMP_RO --out C:\snmp_capture\synology.snmprec` | DSM: Pannello di controllo → Terminale e SNMP → SNMP. |
| Multifunzione Canon | `… --host <ip> --v1 --community-env SNMP_RO --out C:\snmp_capture\canon_<modello>.snmprec` | v1, come il polling attuale. Una cattura per ogni modello (C5535i, C5840i, C3822i). |
| UPS | `… --host <ip-scheda-rete> --v2c --community-env SNMP_RO --out C:\snmp_capture\ups.snmprec` | Si cattura la scheda di rete dell'UPS; la marca si ricava dal walk (`sysObjectID`). |
| Server Dell iDRAC / HPE iLO | `… --host <ip-idrac-o-ilo> --v2c --community-env SNMP_RO --out C:\snmp_capture\idrac.snmprec` | IP del controller di gestione (BMC), non quello del sistema operativo. iDRAC: iDRAC Settings → Services → SNMP Agent. |
| Linux (net-snmp) | `… --host <ip> --v2c --community-env SNMP_RO --out C:\snmp_capture\linux.snmprec` | La configurazione Debian/Ubuntu di default espone solo `system`: serve una view su `.1` in `snmpd.conf`. |
| Windows Server | `… --host <ip> --v2c --community-env SNMP_RO --out C:\snmp_capture\windows.snmprec` | Servizio SNMP (funzionalità opzionale, deprecata) con community read-only e host autorizzati. |

SNMPv3, solo autenticazione (le chiavi vanno lette dalle variabili d'ambiente):

```powershell
& $py manage.py snmp_capture --settings=config.settings.test --host <ip> --v3 --v3-user <utente> --v3-auth sha1 --v3-auth-key-env SNMP_AUTH --out C:\snmp_capture\x.snmprec
```

`--v3-priv aes` richiede il pacchetto `puresnmp-crypto`, che non è installato: il comando lo dice esplicitamente.

## Esito

L'ultima riga stampata e l'intestazione del `.txt` riportano:
- righe, richieste, durata;
- OID esclusi e segreti oscurati;
- **COMPLETO** oppure **INCOMPLETO: motivo**.

Una cattura INCOMPLETA è comunque utilizzabile, ma conviene ripeterla con limiti più ampi.

## Passaggio dei file

Passa a Claude i `.snmprec` grezzi (restano in `C:\snmp_capture\`, fuori da git). Le fixture versionate si ricavano con:

```powershell
& $py manage.py snmp_capture --settings=config.settings.test --sanitize-from C:\snmp_capture\synology.snmprec --out contatori\fixtures\snmp\synology.snmprec
```

La sanitizzazione:
- **pseudonimizza in modo coerente**, nei valori e negli indici delle tabelle:
  - IP → 192.0.2.x / 198.51.100.x;
  - MAC → 02:00:00:…;
  - email → utente@example.invalid;
  - sysName → device-1;
  - sysContact/sysLocation → valori sintetici;
  - ifAlias, nomi dei vicini LLDP e nome stampante → pseudonimi;
- **esclude**: route, connessioni TCP/UDP, processi, comandi, LanManager e gli indirizzi IPv6 negli indici;
- **lascia intatti** modelli, versioni, seriali e contatori, perché servono a verificare i preset.

Prima del commit ogni fixture va comunque riletta a mano.
