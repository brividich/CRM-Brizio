# Modulo WatchGuard

Il modulo WatchGuard elabora i report periodici del firewall/UTM e li trasforma in metriche e alert.

## Input supportati

Report ricorrenti (tipicamente via email) con i dati di sintesi del dispositivo: volumi di traffico, minacce bloccate, tentativi di intrusione, stato dei servizi. Gli esempi sotto sono **sintetici**.

## Metriche prodotte

| Metrica | Significato |
| --- | --- |
| threats_blocked | Minacce bloccate nel periodo |
| intrusion_attempts | Tentativi di intrusione rilevati |
| top_sources | Sorgenti più attive |
| service_health | Stato dei servizi del dispositivo |

## Regole tipiche

- Alert se `intrusion_attempts` supera una soglia rispetto alla baseline.
- Alert se `service_health` segnala un servizio degradato.
- Alert di **sorgente silente** se il report atteso non arriva (heartbeat).

## Riduzione del rumore

I firewall generano molti eventi ripetitivi. Usa:

- **Cooldown** e **deduplica** sulle regole per evitare raffiche.
- **Soppressioni** per eventi noti e benigni (es. scansioni note), con una scadenza.

## Limiti

Il modulo lavora sui report di sintesi, non sui log grezzi in tempo reale: è complementare alla console del vendor, non la sostituisce.
