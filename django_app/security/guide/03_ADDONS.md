# Moduli

Il Security Center separa il **core** (motore condiviso) dai **moduli** (integrazioni per vendor). Questa separazione fa sì che aggiungere una nuova sorgente non richieda di toccare il motore.

## Core e modulo

- Il **core** conosce concetti generici: report, metriche, finding, regole, alert, evidenze, ticket, KPI. Non sa cosa sia un firewall o un antivirus.
- Un **modulo** porta la conoscenza di una sorgente concreta: parser specifici, configurazione seed, regole tipiche, metriche, e la relativa documentazione.

## Moduli attuali

| Modulo | Sorgente | Cosa produce |
| --- | --- | --- |
| WatchGuard | Firewall/UTM | Metriche di traffico/minacce, alert su anomalie |
| Microsoft Defender | Email vulnerabilità | Finding CVE, evidenze, ticket di remediation |
| Backup/NAS | Synology Active Backup | Stato job, rilevazione backup mancanti/anomali |

## Come si innesta un modulo

Un modulo tipicamente fornisce:

1. Uno o più **parser** che leggono il formato del vendor.
2. Una **configurazione seed** (sorgenti, regole, aspettative) applicata dall'autoconfigurazione (`/soc/admin/autoconfig/` o `seed_security_center_config`).
3. Le **regole alert** e le metriche di riferimento.
4. La documentazione dedicata (come questa).

Per i dettagli di sviluppo di un parser vedi la [Guida sviluppo](/soc/docs/10-developer-guide/). Per i singoli moduli:

- [Modulo WatchGuard](/soc/docs/04-watchguard-addon/)
- [Modulo Microsoft Defender](/soc/docs/05-defender-addon/)
- [Modulo Backup/NAS](/soc/docs/06-backup-addon/)
