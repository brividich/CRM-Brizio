GUIDA = {
    "slug": "dati_bi",
    "titolo": "Dati per Power BI e API",
    "area": "Amministrazione del portale",
    "sintesi": "Come Power BI e le altre applicazioni leggono i dati del portale, in sola lettura e senza dati personali.",
    "parole": "power bi report dati api token viste sql bi esportazione powerautomate",
    "url": "scadenze_globali",
    "prefissi": ("/api/v1/",),
    "solo_admin": True,
    "dettaglio": [],
    "uso": [
        {
            "id": "cosa",
            "titolo": "Cosa esce dal portale",
            "blocchi": [
                ("p", "Il portale non manda dati da nessuna parte da solo: sono Power BI o un'altra applicazione a leggerli, "
                      "in sola lettura, nel momento in cui servono. Non ci sono copie da tenere allineate."),
                ("def", [
                    ("Viste bi_*", "tabelle virtuali nel database per Power BI: asset, ordini di lavoro, scadenze di asset/licenze/contratti/verifiche impianti, ticket, consegne DPI, azioni CAPA."),
                    ("API /api/v1/", "indirizzi web per Power BI (connettore Web), Power Automate o un gestionale: asset, ordini di lavoro, scadenze voce per voce e riepiloghi."),
                ]),
                ("nota", "Non escono mai nomi di persone, email o testi liberi. Le scadenze del personale (visite, corsi, qualifiche, contratti) escono solo come numeri per reparto."),
            ],
        },
    ],
    "admin": [
        {
            "id": "power-bi-viste",
            "titolo": "Collegare Power BI al database (viste)",
            "blocchi": [
                ("passi", [
                    "Il DBA crea un utente SQL in sola lettura per Power BI (o usa un gruppo di Active Directory).",
                    "Dal terminale del server: manage.py bi_viste --grant <nome utente>. Stampa i GRANT: il DBA li esegue.",
                    "In Power BI: Recupera dati → SQL Server, server e database del portale, con quell'utente. Si vedono solo le viste bi_*.",
                    "Controllo: manage.py bi_viste mostra quante righe ha ogni vista.",
                ]),
                ("nota", "I giorni alla scadenza si calcolano in Power BI (colonna calcolata sulla data «scadenza»)."),
            ],
        },
        {
            "id": "api-token",
            "titolo": "Dare accesso all'API a un'applicazione",
            "blocchi": [
                ("passi", [
                    "Decidi cosa può leggere: asset, manutenzione, scadenze, personale_aggregato.",
                    "Dal terminale: manage.py dati_api_client crea \"Nome applicazione\" --ambito scadenze --ambito manutenzione. Il token si vede una volta sola: consegnalo a chi configura l'applicazione, mai per mail in chiaro.",
                    "Aggiungi l'IP (o la rete) del computer che chiama a DATI_API_ALLOWED_IPS nel .env e riavvia il sito.",
                    "Prova: GET /api/v1/stato/ con l'intestazione Authorization: Bearer <token> deve rispondere con il nome dell'applicazione.",
                ]),
                ("ul", [
                    "Power BI, connettore Web: URL https://<portale>/api/v1/scadenze/?limit=500; in «Parametri intestazione richiesta HTTP» Authorization = Bearer <token>.",
                    "Elenco e ultimo accesso: manage.py dati_api_client elenco. Revoca: dati_api_client disattiva \"Nome\". Token perso: dati_api_client rigenera \"Nome\".",
                    "L'API è solo per la rete interna: non va pubblicata su Entra Application Proxy.",
                ]),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "L'applicazione riceve 401",
            "fare": [
                "Il token è sbagliato, scaduto per rigenerazione o l'applicazione è disattivata: manage.py dati_api_client elenco.",
                "L'intestazione deve essere esattamente «Authorization: Bearer <token>».",
            ],
        },
        {
            "sintomo": "L'applicazione riceve 403",
            "fare": [
                "«Rete non autorizzata»: l'IP che chiama non è in DATI_API_ALLOWED_IPS (attenzione ai proxy: conta l'IP che arriva al portale).",
                "«Ambito non autorizzato»: aggiungilo con manage.py dati_api_client ambiti \"Nome\" --ambito … (vanno ripetuti tutti quelli voluti).",
            ],
        },
        {
            "sintomo": "Power BI non vede le viste o dà errore su una vista",
            "fare": [
                "manage.py bi_viste: se una vista è «NON LEGGIBILE», esegui manage.py bi_viste --applica.",
                "Dopo un ripristino del database su un'altra istanza, rifai i GRANT (bi_viste --grant).",
            ],
        },
    ],
}
