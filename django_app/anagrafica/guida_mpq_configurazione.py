"""Guida passo passo: configurare un processo qualificato (MOD.128) con la sua sezione dedicata.

Contenuto per ``core.guida_pdf.render_guida_pdf`` (stessa forma di ``anomalie/guida.py``).
Le etichette sono quelle delle pagine: se cambia un pulsante, va cambiato anche qui.
Esempio ricorrente: P11TF12, foratura su particolari critici (MT CN 69).
"""
from __future__ import annotations

TITOLO = "Configurare un processo qualificato"
SOTTOTITOLO = "Processi qualificati (MOD.128) e sezione dedicata · esempio: P11TF12, foratura su particolari critici"

SEZIONI: list[dict] = [
    {"id": "dove", "titolo": "Dove si trova", "blocchi": [
        ("def", [
            ("Pagina con le persone in testa", "Anagrafica › Competenze › Qualifiche › voce con la sigla (es. "
                                               "«P11TF12 – Foratura su particolari critici»)."),
            ("Pagina con macchine e utensili", "modulo Asset › menu a sinistra › voce con la sigla (sotto «PART 145»)."),
            ("Pagina del processo", "Competenze › Qualifiche › Processi qualificati › «Registro processi "
                                    "qualificati» › nome del processo. Il bollino viola con la sigla apre la "
                                    "sezione dedicata."),
            ("Ricerca veloce", "Ctrl+K in qualsiasi pagina, poi scrivi la sigla (es. p11tf12)."),
        ]),
        ("nota", "Le pagine della sezione dedicata sono da consultare. I dati si inseriscono nella pagina del "
                 "processo: in cima il riquadro «Configurazione del processo» dice cosa manca e porta dove si "
                 "sistema; sparisce quando è tutto a posto."),
    ]},
    {"id": "prima", "titolo": "Prima di iniziare (una volta sola, amministratore)", "blocchi": [
        ("passi", [
            "Dopo un aggiornamento del portale: Admin portale › Ruoli portale › «Sincronizza i permessi delle pagine».",
            "Chi inserisce i dati ha il permesso «Processi qualificati MOD.128 - Gestisci»; per vedere persone e "
            "formazione basta «Visualizza».",
        ]),
    ]},
    {"id": "processo", "titolo": "1. Il processo e la sezione dedicata", "blocchi": [
        ("passi", [
            "Competenze › Qualifiche › Processi qualificati. Se il processo c'è già, aprilo e premi «Modifica»; "
            "altrimenti «Nuovo processo». Se esiste un processo simile, il portale lo segnala prima di salvare.",
            "Riquadro «Processo»: Cliente, Nome (es. «Foratura su particolari critici»), Regime (di solito "
            "«Cliente-specifico»).",
            "Riquadro «Validità e scadenza»: tipo di validità e scadenza dell'approvazione; «Ripeti la qualifica "
            "macchine ogni (mesi)» come da istruzione tecnica (vuoto = la qualifica macchina non scade); "
            "facoltativo «Riesame dopo mesi senza attività».",
            "Riquadro «Sezione dedicata»: spunta «Crea sezione dedicata», sigla (es. P11TF12), titolo della pagina, "
            "dove compare (Qualifiche e Asset).",
            "Riquadro «Stato»: Attivo. «Salva»: le voci di menu compaiono subito.",
        ]),
    ]},
    {"id": "riferimenti", "titolo": "2. Documenti di riferimento", "blocchi": [
        ("passi", [
            "Pagina del processo › «Dati del processo» › «Riferimenti / codici di approvazione».",
            "Un codice alla volta, con il tipo, poi «+ Aggiungi». Per P11TF12: MT CN 69, MOD.161, MOD.176 "
            "(Specifica) e il codice di approvazione del cliente (Approvazione).",
        ]),
        ("p", "Nella sezione dedicata, parte «Documenti di riferimento», compare la revisione in vigore presa dal "
              "registro SGI."),
    ]},
    {"id": "macchine", "titolo": "3. Macchine qualificate (MOD.161)", "blocchi": [
        ("passi", [
            "Riquadro «Macchine qualificate» › «+ Collega attrezzatura»: ogni macchina usata per il processo.",
            "Per ogni macchina apri la qualifica e premi «Registra verifica»: data, esito, parametri confrontati "
            "con le tolleranze del processo (MOD.161).",
            "Riquadro «Cosa serve a una macchina» › «+ Aggiungi»: manutenzioni e controlli richiesti dal processo.",
            "Dopo un intervento correttivo la macchina torna «Da valutare»: serve una nuova verifica.",
        ]),
    ]},
    {"id": "utensili", "titolo": "4. Utensili critici e Technical Plan", "blocchi": [
        ("passi", [
            "Pagina del processo › «Utensili e Technical Plan» › «+ Nuovo utensile critico»: codice, descrizione e "
            "geometria, tipo, materiale, diametro, fornitore certificato dal cliente, riaffilature ammesse.",
            "«+ Nuovo Technical Plan»: uno per ogni P/N e tipologia di foro critico.",
            "Nel Technical Plan, «Passi del processo» › «Aggiungi»: operazione, utensile, velocità, avanzamento, "
            "refrigerante, pressione minima, TCP (punto di cambio) e criteri di cambio.",
            "Quando il cliente approva: «Registra approvazione». Senza revisione approvata il Technical Plan non si "
            "usa in produzione. Per cambiarlo: «Nuova revisione».",
        ]),
    ]},
    {"id": "persone", "titolo": "5. Persone qualificate", "blocchi": [
        ("passi", [
            "Riquadro «Persone qualificate» › «+ Aggiungi persona»: persona e ruoli (Ingegneria, Programmazione, "
            "Operatore…).",
            "Riquadro «Cosa serve a una persona» › «+ Aggiungi requisito persona»: per esempio il corso di "
            "consapevolezza ogni 12 mesi, con i ruoli a cui si applica.",
            "La colonna «Qualifica sul processo» dice se la persona è in regola.",
        ]),
    ]},
    {"id": "officina", "titolo": "6. In officina: registro utensili (MOD.176)", "blocchi": [
        ("passi", [
            "Dal Technical Plan approvato: «Apri MOD.176» quando si monta un utensile o un kit.",
            "Competenze › Qualifiche › «MOD.176 in officina» (pagina adatta al tablet): cerca il kit o il P/N, "
            "scrivi P/N, OP, matricola e quantità e premi «Registra». Il portale avvisa al TCP.",
            "Al punto di cambio: nella pagina del registro, «Chiudi e consegna a IN1».",
        ]),
    ]},
    {"id": "controllo", "titolo": "7. Controllo finale", "blocchi": [
        ("ul", [
            "Il riquadro «Configurazione del processo» non compare più: è tutto inserito.",
            "Nella sezione dedicata «Da sistemare» è vuota e i riquadri sono verdi.",
            "Scadenze: rosso = già scaduta, giallo = entro 30 giorni.",
            "Per l'audit: «Scarica PDF» o «Scarica Excel» (sezione dedicata o pagina del processo).",
        ]),
    ]},
]
