# Scheda asset IT — proposta e checklist di attuazione

Data: 02/10/2026. Autore: Codex. Base analizzata: `f4bd2118`.
Stato: **profili PC/portatile, server, VM e stampante implementati con dati esistenti; arricchimenti e policy ancora aperti**.
Richiesta: ripensare la pagina di un asset IT, ridurre le informazioni poco pertinenti e integrare SOC e altre informazioni utili. Dopo la proposta, l'utente ha autorizzato la prima versione PC/portatile con dati esistenti. Questo documento è il passaggio di consegne per Claude; pubblicazione e deploy restano separati.

## 1. Scelta consigliata

Una scheda IT deve rispondere subito a quattro domande: **che dispositivo è, chi lo gestisce, quali problemi richiedono attenzione, quanto sono aggiornate le informazioni**.

Propongo una **panoramica compatta con schede di approfondimento e profili per categoria**. Conservare l'identità unica dell'asset e i moduli già esistenti. Il SOC mantiene eventi, alert e valutazioni; Contatori mantiene la telemetria SNMP; la pagina asset ne mostra una sintesi contestuale autorizzata.

| Soluzione | Cosa cambia | Vantaggi | Limiti / impegno relativo |
| --- | --- | --- | --- |
| A — Riordinare la pagina attuale | Card SOC in alto, metriche pertinenti, nascondere sezioni non applicabili | Primo miglioramento rapido; riuso elevato | Resta una pagina lunga; personalizzazione per categoria da verificare. Impegno basso/medio |
| **B — Panoramica + schede per profilo (raccomandata)** | Sintesi comune; dettagli IT, sicurezza, gestione e storico; contenuti specifici per famiglia | Buon equilibrio fra leggibilità, evoluzione e riuso | Serve una regola esplicita di classificazione e gestione layout. Impegno medio |
| C — CMDB con relazioni estese | Servizi, dipendenze, host/VM, apparati di rete, impatto dei guasti | Utile per infrastruttura e continuità | Richiede dati mantenuti e processi dedicati; introdurre dopo B. Impegno alto |

Percorso: realizzare A come primo incremento della B; aggiungere relazioni della C solo dove servono. Gli impegni sono valutazioni relative, non preventivi.

## 2. Stato reale del repository

Ricognizione statica del codice; nessun accesso a database aziendali o report privati, nessuna verifica visuale del portale in questa sessione.

| Elemento esistente | Dove | Conseguenza per il progetto |
| --- | --- | --- |
| Identità, categoria, stato, acquisto, assegnazione, ubicazione, campi extra | `django_app/assets/models.py`, `Asset` | Riutilizzare; non creare una seconda anagrafica IT |
| OS, CPU, RAM, disco; flag dominio, EDR, AD360, MFA Office, password BIOS; riferimento vault | `AssetITDetails` nello stesso file | Separare configurazione dichiarata da stato osservato; i booleani attuali non esprimono “non verificato” |
| IP, VLAN, switch, porta, punto rete e nome endpoint | `AssetEndpoint` | Rete già parzialmente modellata; prevedere più interfacce |
| Licenze, contratti, documenti, timeline, ticket e manutenzioni | Modelli Assets e relazioni già usate in `assets/views.py` | Riorganizzare i contenuti esistenti |
| Campi, sezioni e categorie configurabili | `AssetDetailField`, `AssetDetailSectionLayout`, `AssetCategoryField` | Valutare compatibilità prima di introdurre un altro motore di layout; non presumere che supportino già tutti i profili proposti |
| Pagina comune con metriche e card | `assets/templates/assets/pages/asset_detail.html`; `asset_detail`, `_build_asset_detail_section_cards` in `assets/views.py` | Il percorso non WorkMachine propone anche batteria, CPU, disco; verificare tutte le categorie prima di cambiare i default |
| SOC in fondo, dopo il calendario | `{% security_asset_card asset %}` nel template dettaglio | La sicurezza non è attualmente il primo livello di lettura |
| Collegamento SOC → inventario | `security/models.py`, `SecurityAsset.hub_asset` | Più identità SOC possono puntare allo stesso asset HUB |
| Segnali backup, rilevamenti e minacce | `SecurityAssetSignal`, `security/services/asset_signals.py` | Già disponibili per i dispositivi riconosciuti nei report; non equivalgono a telemetria completa EDR |
| Card SOC: ultimo backup e ultimi 10 segnali | `signals_for_hub_asset`; `security/templates/security/partials/asset_card.html` | Espandere il servizio esistente; oggi il backup è l'ultimo globale dell'asset, non una valutazione per ogni job |
| Protezione card lato server | `security/templatetags/security_asset.py`, `can_view_security_center` | Conservare anche per sintesi, conteggi, schede e richieste HTMX |
| Suggerimento collegamento per nome identico univoco | `suggest_hub_asset` in `security/services/asset_signals.py` | Il codice esaminato propone solo il nome, anche se l'help text del modello menziona IP; evitare assunzioni basate sull'help text |
| Collegamenti a Contatori/SNMP e card esistente | `contatori/models.py`, blocco SNMP nel template asset | Riusare rilevazioni, stato e timestamp; non interrogare la rete all'apertura della scheda |

Due anomalie semantiche da includere nel lavoro: il fallback attuale di `metric_storage` può usare `it_details.disco` come spazio libero; nelle specifiche la data acquisto può ripiegare su `created_at`. Capacità disco e spazio libero, acquisto e censimento devono rimanere concetti distinti.

## 3. Confronto con altri prodotti

Fonti ufficiali consultate il 02/10/2026. Le applicazioni al nostro portale sono proposte progettuali, non funzionalità già implementate. Nessuna valutazione commerciale o di licenza.

| Prodotto | Pratica documentata | Cosa riprendere in NOVICROM HUB |
| --- | --- | --- |
| **Snipe-IT** | Fieldset associati ai modelli; campi con ordine, obbligatorietà e validazione configurabili | Profili di compilazione: IMEI per telefoni, batteria per portatili, firmware per apparati. [Documentazione campi personalizzati](https://snipe-it.readme.io/docs/custom-fields) |
| **GLPI** | Schede per OS, componenti, software, rete, gestione; relazioni e analisi impatto; protezione dei campi modificati manualmente dai successivi inventari automatici | Separare gestione amministrativa e stato tecnico; mostrare collegamenti; definire precedenza fra dato manuale e importato. [Documentazione computer](https://help.glpi-project.org/documentation/modules/assets/computers) |
| **Microsoft Defender for Endpoint** | Pagina dispositivo orientata a indagine, timeline, valutazioni di sicurezza e contesto del dispositivo | Mettere in evidenza problemi e cronologia, indicando il significato delle date di aggiornamento. Le azioni di risposta del prodotto non sono implicitamente disponibili nel nostro SOC. [Documentazione indagine dispositivi](https://learn.microsoft.com/en-us/defender-endpoint/investigate-machines) |

Sintesi progettuale: campi pertinenti per categoria come Snipe-IT, organizzazione e relazioni come GLPI, lettura operativa della sicurezza ispirata a Defender. Evitare una pagina che mostri tutte le possibili metriche su ogni dispositivo.

## 4. Struttura della pagina proposta

### Intestazione persistente

Nome leggibile + hostname separato, tag asset, categoria, modello, stato inventariale. Subito sotto: assegnatario o servizio, referente IT, sede/reparto e criticità aziendale. “In uso” non significa “online” e non significa “protetto”.

Azioni: **Apri ticket**, Modifica (se permesso), menu con assegnazione, documenti, etichetta e collegamenti ai moduli. “Apri nel SOC” solo se autorizzato. Nessun pulsante remoto distruttivo aggiunto in questa fase.

### Panoramica iniziale

```text
NB-DEMO-042 · Portatile · In uso              [Apri ticket] [Modifica]
Tag IT-0042 · Reparto dimostrativo · Referente IT · Criticità media

[Sicurezza: da verificare] [Backup: non previsto] [Monitoraggio: dato vecchio]
Ogni indicatore mostra fonte e data; non applicabile non è un errore.

DA CONTROLLARE                         IDENTITÀ E RESPONSABILITÀ
- 1 alert aperto → SOC                Modello / seriale / sede
- Garanzia in scadenza → Gestione     Assegnatario / referente IT
- Inventario da verificare            Servizio supportato

Panoramica | Tecnica e rete | Sicurezza e backup | Gestione | Storico
```

Esempio interamente sintetico; gli stati non descrivono un dispositivo reale.

Al massimo tre/quattro indicatori pertinenti. Per un server: sicurezza, backup, disponibilità monitorata, scadenze. Per una stampante: monitoraggio, consumabili, ticket e contratto. Le informazioni riservate non devono comparire neppure come conteggi a chi non può leggerle.

### Schede di approfondimento

| Scheda | Contenuti | Regole |
| --- | --- | --- |
| **Panoramica** | Problemi prioritari, identità, responsabilità, prossime scadenze, link operativi | Punto di ingresso; evitare grafici decorativi e valori duplicati |
| **Tecnica e rete** | Hardware, OS/versione, interfacce IP/MAC/VLAN, dominio/gestione, firmware; relazioni e telemetria se presenti | Separare capacità statiche e misurazioni; data/fonte per la telemetria |
| **Sicurezza e backup** | Alert aperti, eventi, protezioni osservate, copertura fonti, backup per job e recuperabilità | Visibilità SOC lato server; “non collegato” per autorizzati; stati ignoti espliciti |
| **Gestione** | Assegnazioni, garanzia, supporto, licenze, contratti, ticket, interventi e documenti | Sottosezioni/ancore, tabelle paginate; eventuale scheda autonoma Ticket solo se i volumi lo richiedono |
| **Storico** | Modifiche inventario, assegnazioni, interventi; eventi SOC per autorizzati | Filtri per origine; rimando al dettaglio originale; non duplicare payload dei report |

Su mobile schede accessibili tramite menu o elenco; ordine del contenuto coerente anche da tastiera. Mantenere URL del dettaglio e deep link stabili; SSR e HTMX per gli approfondimenti, senza nuovo framework.

## 5. Cosa mantenere, ridurre o aggiungere

| Informazione | Scelta | Motivazione |
| --- | --- | --- |
| Tag, seriale, produttore/modello, categoria, stato | Sempre disponibili | Identificazione e ciclo di vita |
| Assegnatario, reparto, posizione | In panoramica | Responsabilità e localizzazione; per server distinguere referente tecnico e servizio utilizzatore |
| Ticket e interventi | Evidenziare aperti; storico in Gestione | Utile anche per IT; conservare collegamenti esistenti |
| Acquisto, garanzia, supporto e rinnovi | Gestione; avvisi in panoramica se prossimi | Non richiedono spazio fisso al centro della pagina |
| Foto targhetta e QR | Compatti o menu/documenti | Utili all'inventario, raramente prioritari per diagnosi IT |
| Calendario | Riepilogo prossime attività, esteso su richiesta | Evitare un calendario grande su ogni scheda |
| Corse XYZ, mandrino, precisione, TCR | Esclusi dal profilo IT | Informazioni della macchina industriale, da conservare sui profili corretti |
| PART 145, verifiche e manutenzione periodica | Solo quando applicabili | Non rimuovere un obbligo reale solo perché il bene è IT; mantenere override e storico |
| Batteria | Portatili/UPS se dato misurato | Non pertinente a VM, firewall o stampanti; dati UPS distinti da salute batteria notebook |
| Carico CPU e spazio libero | Solo con misura, unità e timestamp | Nessun “N/D” decorativo; capacità disco non è spazio libero |
| Hostname/FQDN, ID sorgenti, alias | Aggiungere come identità strutturata se mancante | `Asset.name` può essere descrittivo; hostname non sempre unico nel tempo |
| OS build, firmware, fine supporto | Integrare | Versioni utili a manutenzione e sicurezza; fine supporto con fonte e verifica |
| Criticità, referente IT, servizio | Integrare | L'impatto aziendale non coincide con la gravità di un alert |
| Cifratura, gestione MDM/EDR, patch | Integrare progressivamente | Solo con copertura per dispositivo e fonte disponibile; altrimenti verifica manuale datata |
| MFA Office | Riformulare | È principalmente proprietà dell'identità/account; il flag legacy non dimostra che ogni account del dispositivo abbia MFA |
| Password BIOS, vault | Solo stato/verifica e riferimento autorizzato | Nessuna password, chiave di recupero, token o community SNMP nella scheda |
| Dismissione | Aggiungere checklist | Restituzione, revoca gestione/licenze e attestazione cancellazione dati; azioni manuali tracciate |

### Differenze per famiglia

| Famiglia | Priorità | Solo quando pertinenti |
| --- | --- | --- |
| PC / portatile | Assegnazione, OS, EDR, cifratura, patch, garanzia | Batteria portatile; backup secondo policy, non presunto obbligatorio |
| Server fisico / VM | Servizio, referente, criticità, OS, backup, restore, risorse | Hardware/garanzia sul fisico; hypervisor/host della VM e dipendenze |
| Firewall / switch / access point | Ruolo, firmware, supporto, interfacce, VLAN, monitoraggio | Backup configurazione, HA, licenze; EDR desktop normalmente non applicabile |
| Stampante / MFC | IP/sede, stato SNMP, consumabili, contatori, assistenza | Distinguere contatori generici e contrattuali; niente CPU/RAM in evidenza |
| NAS / storage / UPS | Ruolo, capacità/salute o autonomia, monitoraggio, supporto | NAS destinazione backup non implica che i suoi dati siano protetti; UPS usa metriche dedicate |
| Telefonia / mobile / CCTV | Assegnazione o ubicazione, firmware, supporto | IMEI/SIM/MDM per mobile; retention e storage per CCTV dove disponibili |
| IT/OT di macchina industriale | Identità e collegamento alla macchina; segmentazione e manutenzione | Conservare informazioni industriali e finestre operative; mai riclassificare in automatico |

I tipi `HW`, `OTHER`, `CCTV`, `FONIA` richiedono classificazione esplicita per categoria; non sono automaticamente tutti PC. I tipi dedicati a switch, NAS, UPS e mobile non risultano nelle costanti `Asset.TYPE_*` esaminate: valutare prima categorie/profili, senza moltiplicare i tipi legacy.

## 6. SOC, backup e attendibilità dei dati

### Contenuti disponibili e contenuti da costruire

| Contenuto | Disponibilità verificata | Evoluzione proposta |
| --- | --- | --- |
| Ultimo backup e segnali minacce/rilevamenti | Segnali già associabili all'asset | Vista per job, filtri, provenienza e collegamenti al report autorizzato |
| Alert/eventi sul dispositivo | `SecurityEventRecord.asset`; gli alert referenziano l'evento tramite `SecurityAlert.event` | Usare `event__asset__hub_asset`, non un campo diretto dell'alert; rispettare stati, deduplica e permessi del SOC |
| Protezione EDR attuale | Flag manuale e segnali non bastano a garantirla | Indicatore osservato solo quando una fonte per endpoint lo dimostra |
| CVE/patch specifiche del bene | Non dimostrate dalla ricognizione del collegamento asset | Verificare sorgenti e identità prima di promettere un conteggio per asset |
| Disponibilità e risorse | Dati SNMP già presenti per apparati collegati | Esporre solo misure supportate; non dedurre disponibilità continua da una singola risposta |
| RPO/RTO e ultimo restore | Da definire/modellare | Obiettivi manuali approvati e prove tracciate; nessuna garanzia dedotta da backup “riuscito” |

### Regole non negoziabili della proposta

- Distinguere stato inventariale, operativo, sicurezza e backup. Nessun unico semaforo che nasconda un dato sconosciuto.
- Stati leggibili: **in regola rispetto ai controlli disponibili**, attenzione, problema, non verificato, dato vecchio, non applicabile. “Nessun alert” è diverso da “sicuro”.
- Per ogni dato osservato conservare fonte, identità sorgente, data del fatto e data di acquisizione. Non chiamare “ultimo contatto” la data in cui è arrivata una mail.
- Freschezza per sorgente e cadenza attesa; soglie configurate e documentate. Un report settimanale non diventa vecchio dopo un giorno. Nessuna soglia universale inventata.
- Separare “non collegato”, “fonte senza dati”, “fonte ferma”, “dato vecchio” e “non applicabile”. Per utenti privi di permesso SOC omettere il contenuto senza rivelare lo stato nascosto.
- Ultimo backup per job/dataset: mostrare ultimo tentativo, ultimo successo, esito e data. Un job riuscito non copre il fallimento di un altro. Distinguere esito globale del job da esito individuale del dispositivo quando il report non lo fornisce.
- L'assenza di backup genera avviso solo se una policy attiva lo richiede e la raccolta è sufficiente a valutarlo. RPO (perdita dati tollerata), RTO (tempo obiettivo di ripristino) e prova restore sono tre informazioni diverse.
- Non attribuire statistiche aggregate WatchGuard o KPI aziendali al singolo dispositivo. Un accesso VPN dell'utente assegnatario non prova che sia stato effettuato da questo asset.
- Collegamenti fra sorgenti e asset confermati/auditati. Nome o IP suggeriscono candidati; omonimie, DHCP, reinstallazioni e riuso del nome richiedono verifica. Nessun merge silenzioso.
- Duplicati della stessa fonte vanno deduplicati; fatti simili da fonti diverse non si sommano indiscriminatamente e non si fondono senza una chiave affidabile. Conservare provenienza e incertezza.
- Configurazione dichiarata e dato osservato restano distinguibili. Un report non sovrascrive silenziosamente un campo manuale. I booleani legacy `False` non diventano automaticamente “assenza confermata”: preservare il valore legacy e introdurre separatamente verifica/fonte/data.
- Riutilizzare i permessi effettivi di Assets, SOC, ticket e Contatori lato server. Stesse regole su HTML, HTMX, export, timeline e cache. Nessun dato SOC aggiunto alla superficie QR pubblica.
- La GET della scheda non lancia scansioni, polling o sincronizzazioni remote. Riutilizzare snapshot persistenti e aggiornamenti espliciti già autorizzati.

## 7. Checklist eseguibile e criteri di completamento

Legenda: `[x]` lavoro svolto in questa sessione; `[ ]` da fare. P0 = prima consegna, P1 = consolidamento, P2 = estensione. Spuntare solo con evidenza, aggiungendo data, autore, commit e test nel registro finale.

### Analisi e scelta — completato / da validare

- [x] A01 — Ricognizione statica di pagina, modelli IT, card SOC e collegamenti SNMP.
- [x] A02 — Confronto con tre prodotti tramite documentazione ufficiale e link.
- [x] A03 — Proposta di architettura pagina, matrice campi e differenze per famiglia.
- [x] A04 — Distinzione fra dati già disponibili e integrazioni future.
- [x] A05 — Utente ha autorizzato B incrementale, primo incremento A per PC/portatili, dati esistenti e approfondimenti espandibili. Server/VM e nuove integrazioni successivi.
- [ ] A06 — Confermare referente IT, criteri criticità, policy backup e cadenze delle sorgenti. La UI deve funzionare con “non definito” finché mancano.

### P0 — Prima scheda utile, con dati esistenti

- [x] P01 — Regole e delta riletti; base applicativa invariata f4bd2118, sopra documento 06f08d22. Worktree dedicato pulito; file controllo sessione/lock assenti. Corretto riferimento alert: relazione tramite evento.
- [x] P02 — Resolver conservativo PC/NOTEBOOK/SERVER/VM/STAMPANTE; WorkMachine prevale sempre sul tipo importato. CNC, firewall generico, OTHER e altre famiglie mantengono layout precedente; nessuna riclassificazione. Resolver esteso per categoria rimane P19.
- [x] P03 — Anteprima Django PC/portatile, server, VM, stampante e regressione CNC verificata. Desktop 1440/mobile 390, scuro, ancore/apertura dettagli; contatori mensili separati da Printer-MIB, toner 0% distinto da ignoto. Limiti anteprima statica sotto.
- [ ] P04 — Parziale: panoramica PC/portatile riordinata, foto compatta, QR e sezioni gestionali espandibili; calendario già limitato a CNC/WorkMachine nel codice iniziale. Manutenzioni conservate e richiudibili; visibilità condizionale per obblighi/categoria ancora da definire.
- [x] P05 — Nuova proiezione SOC sui cinque tipi IT, gate esistente prima delle query; casi autorizzato collegato/non collegato e non autorizzato verificati. Stampanti senza collegamento SOC omettono la card. Card legacy conservata sui profili non IT.
- [x] P06 — Per tutti i cinque tipi IT corretti fallback computed/default: capacità non diventa spazio libero, censimento non diventa acquisto. Aggiornamento inventario distinto dal sync. Profili industriali conservati.
- [ ] P07 — Parziale: SOC con fonte/date e backup per job nel campione esplicito; nuova proiezione SNMP con ACL, date e ultima rilevazione senza ripiegare su un successo precedente. Nessun verde su dati ignoti. Restano freschezza per dispositivo, cadenze attese e policy backup.
- [x] P08 — Ticket IT con permesso nativo e asset precompilato; licenze, contratti, documenti e interventi esistenti conservati. Regressioni rendering ticket/licenze/documenti e layout verificate; nessun archivio parallelo.
- [x] P09 — Campi, visibilità e ordine configurati conservati; test profilo nascosto e custom, oltre a regressioni esistenti. Nessuna riscrittura dei seed.
- [x] P10 — Primo incremento: 36 test mirati, 10 regressioni, system check e nessun drift migrazioni; QA desktop/mobile/scuro e permessi, documenti/registri aggiornati. Commit feature locale; collaudo SQL Server e rilascio separati.

### P1 — Dati strutturati e lettura operativa

- [ ] P11 — Definire hostname/FQDN/alias, referente tecnico, servizio e criticità con fonte autorevole. Esito: nessuna duplicazione del nome descrittivo o dell'assegnatario.
- [ ] P12 — Definire stato osservato/verifica manuale/fonte/data per EDR, dominio, cifratura, gestione e patch. Esito: migrazione conservativa e stato sconosciuto gestito.
- [ ] P13 — Portare alert aperti ed eventi pertinenti nella scheda, con filtri server e paginazione. Esito: identità multiple dello stesso bene gestite e nessun KPI globale attribuito al bene.
- [ ] P14 — Modellare policy backup per ambito/job, RPO/RTO e prove restore solo dopo validazione IT. Esito: test su due job, report tardivo, fonte ferma, backup non previsto.
- [ ] P15 — Aggiungere rinnovi/garanzie/fine supporto con origine e verifica. Esito: nessuna data presunta; riuso scadenze/licenze/contratti.
- [ ] P16 — Esporre qualità del collegamento sorgenti e flusso di riconciliazione. Esito: omonimie e cambio IP non assegnano automaticamente il dispositivo sbagliato; link/unlink auditati.
- [ ] P17 — Storico aggregato con origine e filtri, senza copiare dati riservati in timeline meno protette. Esito: permessi identici al modulo sorgente, anche negli export.

### P2 — Estensioni selettive

- [ ] P18 — Relazioni server→VM, dispositivo→servizio, switch→endpoint e backup→destinazione. Esito: relazioni tipizzate, aggiornabili e non dedotte dal solo nome.
- [ ] P19 — Profili NAS/UPS/rete/mobile/CCTV e metriche specifiche. Esito: nessun campo EDR/batteria notebook universale; dati SNMP supportati dal profilo.
- [ ] P20 — Inventario software/versioni distinto dalle licenze possedute. Esito: fonte di raccolta individuata; assenza di licenza non dedotta dal solo inventario.
- [ ] P21 — Connettori aggiuntivi solo dopo verifica API, copertura e permessi: MDM/EDR/inventario. Esito: import idempotente, precedenza dei dati e storico documentati; nessuna dipendenza nuova implicita.
- [ ] P22 — Checklist dismissione e ripristino; eventuale analisi impatto. Esito: attività assegnate e confermate, nessuna cancellazione remota automatica.

## 8. Indicazioni tecniche per Claude

Punti d'ingresso verificati: `django_app/assets/views.py` (`asset_detail`, `_build_asset_detail_section_cards`, `_build_configured_asset_detail_sections`), `assets/models.py`, `assets/templates/assets/pages/asset_detail.html`; `security/services/asset_signals.py`, `security/templatetags/security_asset.py`, `security/templates/security/partials/asset_card.html`, `security/tests/test_asset_signals.py`; relazioni asset in `contatori/models.py`.

Questi sono riferimenti per iniziare, non l'elenco finale dei file da modificare. Cercare form, test, export e configurazioni interessati tramite `rg` prima di editarli. Non riscrivere l'intero `assets/views.py` o template dettaglio: estrarre partial e servizi locali solo dove necessari.

Prima fase: composizione di lettura dei dati esistenti. Per nuovi dati stabili e interrogabili privilegiare campi/relazioni tipizzati; per attributi specifici di categoria riusare il sistema dinamico se adatto. Non riversare eventi e payload SOC in `Asset.extra_columns`.

Per prestazioni: prefetch/select_related mirati, limiti e paginazione; evitare query per ogni riga dello storico e richieste remote. Misurare query/tempo con fixture ripetibile prima di stabilire un budget, senza inventare obiettivi di produzione non misurati.

ACL, nuove route o variazioni della navigazione vanno valutate secondo le regole dei file critici e documentate. Nessun ampliamento dei permessi necessario solo per far apparire una card. Le verifiche su SQL Server si fanno in ambiente di test, senza dati aziendali.

### Matrice minima di accettazione futura

| Scenario | Risultato atteso |
| --- | --- |
| PC completo / PC senza `it_details` | Rendering valido; ignoti espliciti, niente metriche inventate |
| Server con due job, uno fallito | Fallimento visibile; ultimo successo distinto per job |
| Asset senza link SOC / con più identità SOC | Stato di collegamento corretto; dati pertinenti senza duplicazione ingenua |
| Sorgente vecchia / in errore / report arrivato tardi | Freschezza distinta dall'esito e dalla data ingestione |
| Utente Assets senza SOC | Nessun segnale/conteggio SOC in HTML, HTMX, timeline, export o cache |
| QR pubblico | Nessun nuovo dato IT/SOC riservato |
| Stampante / UPS / firewall | Metriche e campi del profilo; nessun fallback da notebook |
| CNC / macchina con obblighi / IT-OT | Funzioni, personalizzazioni e storico preesistenti conservati |
| Omonimi / IP DHCP / identità riutilizzata | Nessuna correlazione automatica ambigua |
| Modifica manuale + import successivo | Precedenza esplicita, traccia e nessuna sovrascrittura silenziosa |
| Mobile 390 px / desktop / scuro / tastiera | Nessun overflow pagina; tabelle contenute, focus e indicatori testuali |
| Apertura scheda ripetuta | Nessuna scansione o polling remoto, nessun effetto collaterale |

Eseguire solo test delle aree modificate, system check e verifiche migrazioni quando introdotte; mai suite completa senza richiesta. Per questa proposta documentale non servono test Django.

## 9. Ripresa e registro avanzamento

Documento nel worktree `C:/Dev/pn-asset-it-proposta`, branch `feature/assets-it-checklist`; checkout condiviso lasciato invariato. Le istruzioni locali richiedono worktree isolati. Non assumere che questo documento sia già in `release/prod` o sul server.

**Prima azione di Claude:** leggere questo documento e le regole di sessione, verificare lo stato Git e il delta rispetto al commit di implementazione, poi riprendere le voci aperte. La prima versione PC/portatile è autorizzata; policy e nuove integrazioni richiedono le decisioni A06.

### Primo incremento PC/portatile — limiti intenzionali

Le note di questa sezione descrivono il primo commit `5d1212af`; il secondo incremento estende il perimetro come indicato sotto.

- Selettore conservativo: solo tipi PC/NOTEBOOK senza estensione WorkMachine né prodotto chimico. Nessuna riclassificazione o migrazione; gli altri profili restano invariati.
- Panoramica assegnazione e SOC sopra i dettagli; collegamento Apri ticket IT con permesso nativo; navigazione locale e sezioni espandibili, utilizzabili senza JavaScript. Layout personalizzati conservati; specifiche spostate in Tecnica e rete.
- SOC letto solo dopo `can_view_security_center`, nessuna modifica al permesso. Alert attivi collegati via evento; al massimo 5 righe per gravità. Include rinviati/silenziati, come la definizione SOC di attivi. Nessun dato nuovo su QR o export.
- Backup: massimo 200 esecuzioni recenti, raggruppate per fonte/identità/job, massimo 12 gruppi visualizzati; il successo è il più recente **nel campione**, non una garanzia sullo storico completo. Campione e troncamenti espliciti. Job non identificati non fusi. L'esito può riguardare il job globale, non il singolo dispositivo: la UI lo dichiara.
- Freschezza per dispositivo, copertura EDR e policy backup non ancora valutate. Nessun semaforo verde o soglia arbitraria. Fonte, data del fatto e acquisizione mostrate per i segnali; data di modifica inventario distinta.
- Nuovi servizi di sola lettura, query SOC costanti (quattro per proiezione, più conteggio collegamenti/permesso), nessuna rete o lavoro in coda all'apertura. Ordine legacy delle sezioni mantenuto.
- Versione in Unreleased per bump coordinato al rilascio; nessuna modifica ai file `.env` o al wizard.

### Secondo incremento — server, VM, stampanti

- `it_profile` e `it_context` in `assets/services/it_presentation.py`: cinque tipi IT espliciti, priorità all'estensione industriale. Server/VM mostrano assegnazione censita, senza promuoverla a referente tecnico; VM non mostra la dichiarazione BIOS fisico né deduce l'hypervisor dall'IP.
- Stampanti: monitoraggio prima del SOC, che appare solo se il dispositivo è collegato e l'utente autorizzato. Niente flag EDR/AD360/BIOS nel profilo stampante. I campi generici CPU/RAM/OS/disco/batteria/schermo sono esclusi solo per seed non modificati; campi custom, categoria e seed personalizzati restano disponibili.
- `assets/services/it_monitoring.py` legge snapshot senza chiamare servizi SNMP: ACL identica al middleware mediante `acl_allows_path`, prima sulla centrale e poi sui singoli dettagli; errore DB = negazione. Il gate sostituisce la card SNMP diretta anche sui PC/portatili. Nessuna modifica a binding, grant, middleware o route globali.
- Massimo 10 apparati e 10 MFC collegati, massimo 20 contatori/20 consumabili per rilevazione. Quattro query dati con collegamenti presenti, oltre alle verifiche ACL. Si consulta la centrale per la lista completa; nessun totale ottenuto sommando apparati diversi.
- Ultima rilevazione selezionata per data/id: un fallimento non riusa dati di un vecchio successo. Data ultimo controllo e data snapshot esplicite; monitoraggio disattivato dichiarato. Nessuno stato “Operativo” dedotto da una vecchia risposta. Cadenze/freschezza restano non valutate.
- Printer-MIB e contatori mensili MFC separati; lettura mensile = valore cumulativo, non consumo del mese. Percentuale 0 preservata, valori ignoti/invalidi non diventano zero. Errori grezzi e community non esposti; SQL seleziona i soli campi necessari degli apparati.
- I consumabili delle MFC legacy richiedono la lettura esplicita già presente nel modulo Contatori: la GET asset non la avvia. Nessuna nuova migrazione o integrazione esterna.

| Data / autore | Attività | Evidenza | Prossimo passo |
| --- | --- | --- | --- |
| 02/10/2026 — Codex | A01–A04 completate, documento pronto | Ricognizione statica dei file citati; tre fonti ufficiali consultate; nessun codice modificato | A05/A06, poi P01–P10 |
| 02/10/2026 — Codex | Primo incremento autorizzato PC/portatile | 36 test mirati e 10 regressioni passati; system check e drift assets/security verdi. QA su HTML Django sintetico desktop 1440 e mobile 390, scuro, ancore/apertura, backup distinti, utente senza SOC e CNC | A06; completare P03/P04/P07 su ulteriori famiglie prima di P11–P22 |
| 02/10/2026 — Codex | Proseguimento server/VM/stampante con SNMP autorizzato | 50 test IT/SOC e 16 regressioni Assets/Printer-MIB verdi (66 totali); check/drift verdi. QA desktop/mobile/scuro dei tre profili, contatori distinti, 0% e ignoti | A06 per policy; P04 visibilità manutenzioni; P11–P16 per dati strutturati e freschezza; P18/P19 altre relazioni e famiglie |

Nota QA: anteprima statica dei template realmente renderizzati da Django; API globali notifiche/preferenze tabella e pannelli HTMX non serviti dall'anteprima restituiscono 404 attesi. Non equivale a collaudo delle integrazioni reali. Test HTTP di dettaglio eseguiti separatamente tramite Django Client. Screenshot nel worktree sotto `django_app/.tmp_tests/it_qa/`, non versionati.

Per ogni incremento aggiungere qui commit, voci completate, test realmente eseguiti, limiti e prossimo passo. Non spuntare un'integrazione solo perché esiste il campo o perché il layout è pronto.
