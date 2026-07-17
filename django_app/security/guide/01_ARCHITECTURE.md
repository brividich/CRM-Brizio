# Architettura

Il Security Center è costruito attorno a un **motore core** condiviso e a **moduli** specifici per vendor. Il core non sa nulla di WatchGuard o Defender: conosce solo report, metriche, finding, regole, alert, evidenze, ticket e KPI. I moduli forniscono i parser e le regole per una sorgente concreta.

## Flusso dei dati

```
report/email/upload
      -> ingestione (mailbox o upload manuale)
      -> motore parser        (report -> metriche + finding)
      -> motore regole         (metriche -> alert, con dedup e soppressione)
      -> contenitore evidenze  (raccoglie prove a supporto dell'alert)
      -> ticket di remediation (aggrega alert/CVE correlati)
      -> dashboard / KPI / audit
```

Ogni passo è osservabile e ripetibile: la pipeline si può rilanciare a mano dalla pagina `/soc/pipeline/` senza perdere idempotenza.

## Componenti e responsabilità

| Componente | Responsabilità |
| --- | --- |
| Sorgenti | Da dove arrivano i report; pattern mittente/oggetto; cadenza attesa. |
| Parser | Trasformano un report in metriche e finding strutturati. |
| Regole alert | Condizioni su metriche che generano alert, con severità. |
| Soppressioni | Silenziano eventi noti/rumorosi prima che diventino alert. |
| Evidenze | Raccolgono le prove (eventi, report) a supporto di un alert. |
| Ticket | Aggregano alert/CVE correlati in un'unità di remediation. |
| Notifiche | Recapitano gli alert/ticket via email, Teams o dashboard. |
| KPI | Fotografano lo stato nel tempo (snapshot giornalieri). |
| Audit | Traccia ogni modifica di configurazione. |

## Due garanzie importanti

- **Deduplica a livello database.** Un indice unico parziale garantisce **un solo alert (e un solo ticket) attivo** per coppia `(sorgente, dedup_hash)`. Se lo stesso finding arriva due volte in contemporanea, il database fa da arbitro: niente doppioni. Un alert chiuso non blocca la riapertura futura dello stesso finding.
- **Heartbeat delle sorgenti.** L'assenza di un report oltre la cadenza attesa (`expected_every_hours`) genera essa stessa un alert. Così si distingue "nessun dato perché tutto è a posto" da "lo scheduler è fermo".

## Dove vive il codice

Il modulo è `django_app/security/`. La documentazione che stai leggendo vive in `django_app/security/guide/` (non in `docs/`, per un vincolo di pacchettizzazione: vedi la [Guida sviluppo](/soc/docs/10-developer-guide/)).
