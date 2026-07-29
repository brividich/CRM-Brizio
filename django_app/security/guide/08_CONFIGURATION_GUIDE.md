# Guida alla configurazione

Questa è la guida di riferimento per configurare il Security Center. Copre il seed iniziale, ogni sezione della Configuration Studio con i campi principali e i valori consigliati, i permessi e l'audit. Tutti gli esempi sono **sintetici**.

## Seed iniziale (autoconfigurazione)

Il seed popola impostazioni generali, sorgenti, parser, regole, aspettative di backup, notifiche e ticketing con una base sensata. È **idempotente**: rilanciarlo non duplica nulla.

Due strade, stessa fonte di verità (`security/services/autoconfig.py`):

- **Da browser** — `/soc/admin/autoconfig/`. Mostra prima il piano (quanto manca, quanto è difforme dai default, quanto è già allineato) e poi applica. È **additiva**: crea ciò che manca e non tocca mai i valori che hai personalizzato. Il riallineamento ai default è un'azione separata ed esplicita ("Riallinea ai default").
- **Da shell** — `python manage.py seed_security_center_config`. Opzioni: `--dry-run` (solo piano), `--only <sezione>`, `--no-overwrite` (non riallinea i valori personalizzati), `--reset` (svuota la sezione e riparte dai default).

Sezioni: `general`, `sources`, `parsers`, `alert_rules`, `notifications`, `ticketing`, `backups`.

Ogni scrittura finisce nel registro audit (`autoconfig_create` / `autoconfig_align`) con l'utente che l'ha lanciata.

### Correzioni suggerite

La stessa pagina espone come pulsante le correzioni che la diagnostica sa risolvere da sola: riattivare sorgenti o parser disattivati, creare il canale notifiche di dashboard o la configurazione ticketing mancante, riabilitare i ticket automatici sulle regole critiche Defender, disattivare le soppressioni scadute. Compaiono **solo** quando il relativo controllo diagnostico non è "ok" e nessuna di esse cancella dati.

Dopo il seed, apri `/soc/admin/config/` e rivedi le 9 sezioni. Il seed è un punto di partenza, non la configurazione definitiva: le soglie vanno tarate sul tuo ambiente.

## Sorgenti

Una sorgente descrive un flusso di report. Campi principali:

| Campo | Significato | Valore d'esempio |
| --- | --- | --- |
| Tipo | email / pdf / csv / api / manuale | email |
| Vendor | Produttore del sistema | watchguard |
| Pattern mittente | Domini/indirizzi ammessi | alerts@vendor.example |
| Pattern oggetto | Filtri sull'oggetto | Weekly Security Report |
| Parser | Parser associato | watchguard_weekly |
| Cadenza attesa | Ogni quante ore è atteso un report | 168 (settimanale) |

La **cadenza attesa** abilita l'heartbeat: se il report non arriva in tempo, il sistema genera un alert di "sorgente silente". Provala prima di fidarti con la pagina Diagnostica.

## Parser

| Campo | Significato | Nota |
| --- | --- | --- |
| Nome parser | Identificativo univoco | Deve combaciare col parser sulla sorgente |
| Stato | Attivo/disattivo | Disattivo = nessuna metrica prodotta |
| Priorità | Ordine di valutazione | Valore più basso valutato prima |
| Tipo sorgente | Su quali sorgenti si applica | |

## Regole alert

| Campo | Significato | Valore d'esempio |
| --- | --- | --- |
| Metrica | Nome della metrica valutata | open_critical_vulns |
| Operatore | maggiore, minore, uguale, contiene, regex, deviazione baseline | maggiore-uguale |
| Soglia | Valore di confronto | 1 |
| Severità | info / low / medium / warning / high / critical | high |
| Cooldown | Minuti di silenzio dopo lo scatto | 60 |
| Finestra dedup | Minuti entro cui non ri-allertare lo stesso finding | 1440 |
| Crea ticket | Se generare in automatico un ticket | sì per le CVE |

Il pulsante **Test** accetta un campione di metriche in JSON (es. `{"value": 1}`) e mostra se la regola scatterebbe, **senza** creare alert.

## Soppressioni

| Campo | Significato | Consiglio |
| --- | --- | --- |
| Tipo evento | Evento da silenziare | Sii specifico |
| Severità | Limita a una severità | |
| Condizioni | Match sul payload | Chiave/valore |
| Inizio / Scadenza | Validità temporale | Imposta sempre una scadenza |
| Motivo | Perché è stata creata | Obbligatorio per l'audit |

Una soppressione riduce il rumore ma può nascondere un segnale reale: vanno riviste periodicamente.

## Backup

| Campo | Significato | Valore d'esempio |
| --- | --- | --- |
| Nome job | Identificativo del job | backup-notturno-nas1 |
| Dispositivo / NAS | Su quale device gira | nas1 |
| Giorni attesi | Giorni in cui è atteso | lun-ven |
| Ore limite mancante | Dopo quante ore senza esito è "mancante" | 30 |
| Critico | Se l'assenza deve allertare subito | sì per i job vitali |
| Durata max / Dimensione | Soglie di anomalia (opzionali) | |

Gli interruttori consentono di allertare selettivamente su: mancante, fallito, durata anomala, dimensione anomala.

## Notifiche

| Campo | Significato | Valore d'esempio |
| --- | --- | --- |
| Tipo canale | email / webhook Teams / dashboard | email |
| Severità minima | Da quale severità notificare | warning |
| Destinatari | Elenco email | soc@example.org |
| Cooldown | Minuti tra invii sullo stesso alert | 60 |
| Eventi | nuovo alert / ticket creato / violazione SLA | tutti |

Il segreto del webhook Teams non si vede in chiaro: lasciandolo vuoto si conserva quello esistente. Prova un canale prima di affidartici:

```
python manage.py send_security_test_notification
```

Ogni invio è tracciato con esito **inviato**, **fallito** o **soppresso da cooldown**: un sistema di sicurezza deve poter rispondere alla domanda "siamo stati avvisati, e quando?".

## Ticketing

| Campo | Significato | Valore d'esempio |
| --- | --- | --- |
| Strategia aggregazione | Come raggruppare gli alert | per prodotto |
| Assegnatario / Gruppo | Destinatari di default | team-it |
| Riapertura su ricorrenza | Riaprire se il problema torna | sì |
| SLA per severità | Tempi attesi per severità | critical: 24h |

## Permessi e ACL

L'accesso alla configurazione è governato dall'ACL v2:

- **`security.config.view`** — permesso canonico applicato dal middleware alle rotte `/soc/admin/config/`.
- **`security.manage_security_configuration`** — permesso Django, valido per compatibilità.
- **`is_staff`** — fallback.

La sola visibilità in navigazione non è un confine di sicurezza: la decisione autorevole è sempre lato server.

## Audit

Ogni modifica di configurazione è registrata in `/soc/admin/config/audit/`: attore, oggetto, campo, valore vecchio/nuovo, data. È la fonte di verità per capire cosa è cambiato e per gli audit di conformità.

## Verifiche

Dopo le modifiche, controlla lo stato con la diagnostica e il check del database:

```
python manage.py security_center_diagnostics
python manage.py security_db_check
```
