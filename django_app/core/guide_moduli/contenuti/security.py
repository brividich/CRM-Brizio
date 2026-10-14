GUIDA = {
    "slug": "security",
    "titolo": "Security Center (SOC)",
    "area": "IT e sicurezza informatica",
    "sintesi": "Allarmi di sicurezza informatica, vulnerabilità, backup e incidenti NIS2, letti dai report che arrivano per mail.",
    "parole": "soc sicurezza informatica alert allarme vulnerabilita cve backup antivirus incidente nis2",
    "url": "security:dashboard",
    "prefissi": ("/soc/",),
    "dettaglio": [
        ("Inizia da qui", "/soc/docs/00-start-here/"),
        ("Lavoro quotidiano", "/soc/docs/13-lavoro-quotidiano/"),
        ("Risoluzione problemi", "/soc/docs/09-troubleshooting/"),
    ],
    "uso": [
        {
            "id": "giorno",
            "titolo": "Il controllo di ogni mattina",
            "blocchi": [
                ("passi", [
                    "Apri il Security Center: la «Panoramica IT» dice in una riga se va tutto bene.",
                    "Guarda «Da guardare adesso»: le cose più gravi sono in cima.",
                    "Apri un allarme: «Spiega con l'AI» lo spiega in parole semplici, «Cosa sappiamo» mostra lo storico.",
                    "Decidi: prendi in carico, chiudi come risolto o scarta come falso allarme (scrivendo il perché).",
                ]),
                ("p", "La guida completa del Security Center ha un capitolo per ogni pagina: i collegamenti sono in cima."),
            ],
        },
    ],
    "admin": [
        {
            "id": "fonti",
            "titolo": "Da dove arrivano i dati",
            "blocchi": [
                ("ul", [
                    "Le caselle di posta che ricevono i report (antivirus, firewall, backup) si configurano in «Caselle mail»: creazione, anteprima, lettura manuale, importazione dello storico.",
                    "Il ciclo di lettura gira ogni 15 minuti (lavoro «security_cycle»).",
                    "Regole, soglie e AI si configurano nelle Impostazioni del Security Center (capitolo «Impostazioni e AI» della guida completa).",
                ]),
            ],
        },
    ],
    "problemi": [
        {
            "sintomo": "Il Security Center non mostra dati recenti",
            "fare": [
                "Nella Panoramica guarda la «freschezza» di ogni area: quale fonte è ferma?",
                "«Caselle mail»: prova l'anteprima della casella di quella fonte.",
                "Amministrazione → Monitoring → «Salute degli schedule»: controlla «security_cycle».",
                "Se la lettura della casella dà 401/403 il segreto dell'app Graph è scaduto: rinnovalo su Entra ID e aggiornalo dal Setup Wizard.",
                "Altri casi: capitolo «Risoluzione problemi» della guida completa.",
            ],
        },
    ],
}
