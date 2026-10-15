"""Guida d'uso dell'Assistente AI (pagina ``/assistente-ai/guida/``).

Testo semplice, niente HTML: il template lo mostra con l'autoescape. Blocchi di una
sezione: ("p", testo), ("ul", [voci]), ("nota", testo), ("def", [(termine, spiegazione)]).
Le etichette citate sono quelle visibili nella pagina della chat: se ne cambia una,
va aggiornata anche qui. La stessa guida è indicizzata nel RAG (``guide_portale``),
quindi l'assistente sa spiegare come si usa.
"""
from __future__ import annotations

from django.conf import settings


def _giorni() -> int:
    try:
        return max(1, int(getattr(settings, "AI_CHAT_HISTORY_RETENTION_DAYS", 90) or 90))
    except (TypeError, ValueError):
        return 90


def sezioni() -> list[dict]:
    giorni = _giorni()
    return [
        {
            "id": "scopo",
            "titolo": "A cosa serve l'assistente",
            "blocchi": [
                ("p", "L'Assistente AI risponde in italiano su come si usa il portale, sulle procedure del Sistema "
                      "di Gestione e sui dati dei moduli che puoi già vedere. Non scrive nulla nei moduli e non "
                      "prende decisioni: propone, e la decisione resta tua."),
                ("def", [
                    ("Come si fa", "«come inserisco un nuovo timbro?», «come chiudo un audit?»: risponde con i passi "
                     "e i pulsanti delle guide dei moduli e ti dà il link alla guida completa."),
                    ("Procedure", "«in che MT si parla dei timbri?»: cita codice, revisione e paragrafo del documento."),
                    ("I tuoi dati", "«quanti ticket ho aperto questo mese?», «chi è assente domani?»: legge i dati "
                     "del modulo con i tuoi permessi. Per ticket, attività, DPI e anomalie capisce il periodo "
                     "(«oggi», «questa settimana», «questo mese», il nome di un mese) e alle domande «quanti» "
                     "risponde subito con il totale. Per chi gestisce l'anagrafica: «dipendenti con più di 100 ore "
                     "di ferie» (anche «almeno 10 giorni», «meno di 8 ore di ROL») elenca tutti quelli oltre la "
                     "soglia; «dipendenti con mansione addetto uffici» filtra per mansione. Un elenco più lungo di "
                     "30 righe viene detto («ne mostro 30 su 42»): quello completo è nel modulo."),
                    ("I tuoi permessi", "«posso inserire un nuovo timbro?», «perché non vedo il pulsante Copia?»: "
                     "controlla i permessi che hai davvero sul modulo nominato e risponde sì o no per ogni azione. "
                     "Se manca un permesso, va chiesto a un amministratore del portale."),
                ]),
            ],
        },
        {
            "id": "domanda",
            "titolo": "Fare una domanda",
            "blocchi": [
                ("ul", [
                    "Scrivi nel riquadro in basso e premi Invio (o «Invia»). Ctrl+Enter va a capo.",
                    "«Stop» interrompe una risposta lunga: resta il testo già scritto.",
                    "Sotto ogni risposta: «Copia» la copia negli appunti, «Rigenera» la riscrive.",
                    "Le domande suggerite sotto la risposta si inviano con un clic.",
                    "Puoi fare domande di seguito («e come lo inserisco nel modulo?»): l'assistente tiene conto "
                    "degli ultimi messaggi della conversazione.",
                ]),
                ("p", "Le etichette sotto la risposta sono le fonti: verdi i dati letti dai moduli (tool:…), "
                      "blu i documenti e le guide."),
            ],
        },
        {
            "id": "conversazioni",
            "titolo": "Le tue conversazioni",
            "blocchi": [
                ("p", "Ogni conversazione viene salvata dopo la prima risposta e compare in «Le tue conversazioni», "
                      "sopra la chat. La vedi solo tu: gli amministratori vedono solo quante conversazioni ci sono, "
                      "mai il contenuto."),
                ("ul", [
                    "Un clic sul titolo riapre la conversazione e puoi continuarla da dove eri rimasto.",
                    "«Nuova chat» inizia una conversazione nuova: quella attuale resta nell'elenco.",
                    "× accanto a una conversazione la elimina; «Elimina tutte» cancella tutto il tuo storico.",
                    f"Una conversazione senza messaggi nuovi si cancella da sola dopo {giorni} giorni.",
                ]),
                ("nota", "Non scrivere password, token o dati personali non necessari: le conversazioni restano "
                         "salvate fino alla cancellazione."),
            ],
        },
        {
            "id": "fonti",
            "titolo": "Da dove prende le risposte",
            "blocchi": [
                ("def", [
                    ("Dati dei moduli", "ticket, assenze, attività, asset, DPI, anomalie e altri: sempre filtrati "
                     "con i tuoi permessi, come se aprissi il modulo."),
                    ("Guide dei moduli", "le guide che apri con «? Guida» nelle pagine; l'assistente usa solo "
                     "quelle dei moduli che puoi aprire."),
                    ("Documenti del Sistema di Gestione", "procedure e specifiche in vigore, con le stesse "
                     "regole di accesso dei moduli Procedure e Gestione specifiche."),
                    ("FAQ curate", "risposte approvate dagli amministratori."),
                ]),
                ("p", "Se il dato non è in queste fonti, l'assistente lo dice invece di inventarlo."),
            ],
        },
        {
            "id": "personalizza",
            "titolo": "Personalizzazione, report e feedback",
            "blocchi": [
                ("ul", [
                    "«Personalizzazione risposte e limiti»: scegli Operativo, Sintetico o Dettagliato. La scelta "
                    "resta salvata in questo browser.",
                    "«Report PDF» genera un PDF sull'argomento scritto nel riquadro (o sull'ultima domanda), "
                    "con le fonti. È una bozza da verificare.",
                    "👍 e 👎 sotto la risposta: con 👎 puoi scrivere la risposta corretta. Gli amministratori "
                    "raccolgono le domande simili, fanno preparare all'AI una risposta dalle guide dei moduli e, "
                    "dopo averla controllata, la attivano come FAQ: da quel momento l'assistente la usa per tutti.",
                    "Sotto una risposta senza fonti compare un invito a premere 👎: è il modo per segnalare che "
                    "manca una risposta.",
                ]),
            ],
        },
        {
            "id": "faq",
            "titolo": "Domande frequenti",
            "blocchi": [
                ("def", [
                    ("Dice che non trova il dato.", "Il modulo non ha un collegamento per l'assistente o non hai "
                     "il permesso di vederlo: apri il modulo dal menu."),
                    ("Ha risposto una cosa sbagliata.", "Usa 👎 e scrivi la risposta corretta."),
                    ("Non vedo «Le tue conversazioni».", "Lo storico è stato spento dagli amministratori."),
                    ("Ho cancellato una conversazione per errore.", "Non si può recuperare."),
                ]),
            ],
        },
    ]
