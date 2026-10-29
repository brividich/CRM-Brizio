"""Guida d'uso del Registro Timbri (MOD.130-RTF-Rev.2).

Un solo contenuto per due uscite: la pagina guida del modulo (`?guida=1`
sull'elenco) e il PDF scaricabile (`?guida=pdf`). Testo semplice, niente HTML:
il template lo mostra con l'autoescape e il PDF lo passa da `escape()`.

Blocchi di una sezione: ("p", testo) paragrafo, ("ul", [voci]) elenco,
("nota", testo) riquadro di attenzione, ("def", [(termine, spiegazione)]) elenco
di definizioni. Le etichette citate sono quelle visibili nelle pagine: se ne
cambia una, va aggiornata anche qui.
"""
from __future__ import annotations

from io import BytesIO
from xml.sax.saxutils import escape

DOC_CODICE = "MOD.130-RTF-Rev.2"
DOC_TITOLO = "Registro Timbri"
DOC_NOME = f"{DOC_TITOLO} {DOC_CODICE}"

SEZIONI: list[dict] = [
    {
        "id": "scopo",
        "titolo": "A cosa serve il registro",
        "blocchi": [
            ("p", "Il Registro Timbri raccoglie i timbri, le firme e le sigle assegnati al personale. "
                  "Per ogni assegnazione tiene un record con codice, qualifica, tipo, date di consegna e "
                  "ritiro, stato e le immagini PNG del timbro, della firma e della sigla."),
            ("p", "Il registro è agganciato all'anagrafica centrale: i dipendenti non si creano qui. "
                  "Dal registro si aggiungono e si gestiscono i record dei dipendenti già presenti in anagrafica."),
            ("def", [
                ("Record", "una singola assegnazione (un timbro, una firma o una sigla) a un dipendente."),
                ("Codice timbro", "il codice inciso o assegnato, per esempio «CNO Q101»."),
                ("Qualifica", "la qualifica a cui il timbro si riferisce."),
                ("Storico", "i record non più in uso: superati, sospesi o archiviati. Restano consultabili."),
            ]),
        ],
    },
    {
        "id": "permessi",
        "titolo": "Chi può fare cosa",
        "blocchi": [
            ("p", "Con la configurazione predefinita i permessi sono questi. Gli amministratori possono "
                  "cambiarli da Accessi e, per copia e download delle immagini, da Impostazioni → Permessi."),
            ("def", [
                ("Consultare il registro", "ruoli admin, amministrazione, caporeparto e HR."),
                ("Creare, modificare e archiviare record", "ruoli admin e amministrazione."),
                ("Copiare un'immagine (pulsante «Copia»)", "chi ha «Copiare» per il suo ruolo, nell'ambito scelto: "
                 "Propri (solo i suoi timbri), Propri e del team (anche quelli delle persone che coordina) o Tutti."),
                ("Scaricare il file PNG (pulsante «Scarica»)", "chi ha «Scaricare» per il suo ruolo, con gli stessi tre ambiti. "
                 "Copiare non dà il permesso di scaricare e viceversa."),
                ("Impostazioni del modulo", "chi può modificare i record."),
                ("Reset del registro", "solo i superutenti."),
            ]),
        ],
    },
    {
        "id": "elenco",
        "titolo": "L'elenco dei dipendenti",
        "blocchi": [
            ("p", "La pagina iniziale mostra i dipendenti dell'anagrafica con il numero di record attivi e di storico."),
            ("ul", [
                "Le tessere in alto riassumono il registro: Dipendenti, Con timbri, Record attivi, Da gestire. "
                "Un clic su «Record attivi» filtra l'elenco.",
                "La ricerca trova nome, matricola, reparto e codice timbro. Il codice si trova anche scritto "
                "senza spazi: «cnoq101» trova «CNO Q101».",
                "I filtri Reparto e Qualifica restringono l'elenco; «Filtra» li applica, «Reset» li toglie.",
                "I filtri rapidi: Tutti, Con record attivi, Solo storico, Senza timbri.",
                "Un clic sulla riga apre l'anteprima dei timbri attivi senza lasciare la pagina, con i pulsanti "
                "«Copia» e «Scarica» per chi ha i rispettivi permessi.",
                "Il pulsante «Timbri» apre la scheda timbri del dipendente; l'icona con le persone apre la sua scheda anagrafica.",
                "«Esporta» scarica l'elenco in Excel o PDF con i filtri attivi, compresi i codici dei timbri attivi. "
                "Ogni esportazione viene registrata nel log.",
            ]),
            ("p", "La sezione «Da gestire», in fondo, elenca le righe dei vecchi import CSV non caricate perché "
                  "il dipendente non è stato trovato in anagrafica. «Cerca» apre la ricerca in anagrafica per sistemarle."),
        ],
    },
    {
        "id": "scheda",
        "titolo": "La scheda timbri del dipendente",
        "blocchi": [
            ("p", "La scheda mostra i dati del dipendente e tutti i suoi record."),
            ("ul", [
                "«Nuovo record» registra un timbro; «+ Firma» e «+ Sigla» aprono il modulo già impostato su firma o sigla.",
                "«Report completo» apre un riepilogo stampabile con i dati e i record attivi; «Solo anagrafica» lo stampa senza i timbri. "
                "Dal report «Stampa / Salva PDF» lo salva.",
                "I record attivi sono divisi nelle schede Timbri, Firme e Sigle, con le immagini visibili.",
                "Lo storico mostra i record non più in uso; le immagini si aprono con la freccia a destra della riga.",
                "«Copia» mette l'immagine negli appunti, pronta da incollare in un documento. Compare solo a chi ha il permesso.",
                "«Modifica» apre il record. Compare solo a chi può modificare.",
            ]),
            ("p", "Gli stessi record si vedono anche nella scheda del dipendente in Anagrafica, alla voce Timbri."),
        ],
    },
    {
        "id": "record",
        "titolo": "Registrare o modificare un record",
        "blocchi": [
            ("def", [
                ("Codice, qualifica e tipo", "il tipo è uno tra Fisico, Digitale, Fisico e digitale, Altro, Solo firma, Solo sigla."),
                ("Abilitazione MOD.128 collegata", "facoltativa: il processo qualificato a cui il timbro è legato. "
                 "Si possono scegliere solo le abilitazioni del dipendente."),
                ("Consegna e stato", "data di consegna, data di ritiro e la casella «Record attivo (in uso)»."),
                ("Note e firma", "note operative e testo o note della firma."),
                ("Timbro, firma e sigla", "le tre immagini del record."),
            ]),
            ("ul", [
                "Le immagini devono essere file PNG di al massimo 20 MB. Si caricano con il pulsante o trascinando il file sul riquadro; "
                "prima di salvare si vede l'anteprima. Un file non PNG viene rifiutato subito.",
                "Le immagini già presenti restano invariate finché non se ne carica una nuova.",
                "Un record attivo non può avere una data di ritiro: per ritirare un timbro si toglie la spunta "
                "«Record attivo (in uso)» e si indica la data di ritiro.",
                "«Archivia» chiude il record e imposta come data di ritiro la data di oggi, dopo una conferma.",
                "«Salva» registra le modifiche; «Annulla» torna alla scheda senza salvare.",
            ]),
        ],
    },
    {
        "id": "stati",
        "titolo": "Gli stati di un record",
        "blocchi": [
            ("def", [
                ("Attivo", "il timbro è in uso."),
                ("Sospeso", "il timbro non si può usare per un periodo. Il riquadro della sospensione indica "
                 "le date, il motivo e, se è automatica, la dicitura «automatica da MOD.128»."),
                ("Superato", "il record non è più attivo, per esempio perché il timbro è stato ritirato o sostituito."),
                ("Archiviato", "il record è chiuso con «Archivia»."),
            ]),
            ("p", "Solo i record attivi compaiono nelle schede Timbri, Firme e Sigle; tutti gli altri finiscono nello storico."),
        ],
    },
    {
        "id": "mod128",
        "titolo": "Collegamento al MOD.128 e sospensione automatica",
        "blocchi": [
            ("p", "Un timbro collegato a un'abilitazione MOD.128 segue lo stato di quell'abilitazione."),
            ("ul", [
                "Se l'abilitazione viene revocata, sospesa o dismessa, oppure il processo qualificato è scaduto, "
                "il timbro viene sospeso automaticamente con la data di sospensione e il motivo.",
                "Quando l'abilitazione torna operativa, il timbro torna attivo da solo.",
                "Le sospensioni decise a mano non vengono mai annullate in automatico.",
                "La regola si applica quando si salva il record e a ogni aggiornamento MOD.128 lanciato dall'amministratore. "
                "Le sospensioni automatiche vengono segnalate per email a MSM/Qualità.",
                "Nella riga del record, accanto al codice, compare il processo MOD.128 collegato; se l'abilitazione non è attiva, compare il suo stato in rosso.",
            ]),
        ],
    },
    {
        "id": "riservatezza",
        "titolo": "Immagini e riservatezza",
        "blocchi": [
            ("p", "Le immagini di timbri e firme sono dati riservati."),
            ("ul", [
                "Sono salvate in un'area privata del server e si aprono solo dal portale, con i permessi giusti.",
                "Ogni visualizzazione, copia e download viene registrato nel log, compresi i tentativi senza permesso.",
                "I pulsanti «Copia» e «Scarica» compaiono solo sui timbri che rientrano nel tuo ambito; il portale "
                "ricontrolla comunque ogni immagine, anche se qualcuno prova ad aprire il collegamento a mano.",
                "Le immagini non vanno inoltrate né salvate fuori dai documenti a cui servono.",
            ]),
        ],
    },
    {
        "id": "impostazioni",
        "titolo": "Impostazioni (amministratori)",
        "blocchi": [
            ("p", "La pagina Impostazioni ha quattro schede."),
            ("def", [
                ("Permessi", "per ogni ruolo del portale, le colonne «Copiare» e «Scaricare» con le scelte "
                 "«Non deciso (no)», «No», «Propri», «Propri e del team», «Tutti»; «Salva permessi» le registra. "
                 "Se una persona ha più ruoli vale il più ampio. Le cambia solo l'amministratore del portale; "
                 "gli altri le vedono in sola lettura. Sono le stesse celle della matrice in Ruoli e permessi. "
                 "Con il sistema dei ruoli spento la scheda mostra invece gli interruttori storici per ruolo e le eccezioni per utente."),
                ("Registro copie e download", "chi ha copiato o scaricato quale immagine e quando: esito (Copia, Download, "
                 "Copia negata, Download negato), titolare del timbro, codice, immagine (timbro, firma o sigla), ambito e indirizzo IP. "
                 "Si filtra per esito e per utente; mostra le ultime 300 righe."),
                ("Operazioni", "«Bonifica ora» ricollega all'anagrafica gli operatori rimasti senza collegamento ed elimina quelli vuoti; "
                 "«Export CSV locale» scarica l'intero registro; «Reset tabella» cancella tutti i record."),
                ("Log audit", "lo storico delle operazioni sul registro, con filtro."),
            ]),
            ("nota", "Il reset è riservato ai superutenti e chiede di scrivere RESET per conferma. Prima di cancellare, "
                     "il portale salva una copia CSV del registro nella cartella di backup; se la copia non riesce, il reset non parte."),
        ],
    },
    {
        "id": "faq",
        "titolo": "Domande frequenti",
        "blocchi": [
            ("def", [
                ("Non trovo un dipendente.", "Il registro mostra solo i dipendenti dell'anagrafica centrale: va prima inserito lì."),
                ("Non vedo il pulsante «Copia» o «Scarica».", "Il tuo ruolo non ha «Copiare» o «Scaricare», oppure il timbro "
                 "non rientra nel tuo ambito (per esempio hai «Propri» e il timbro è di un collega): chiedilo a un amministratore."),
                ("Un timbro è sospeso e non so perché.", "Apri la scheda: il riquadro della sospensione indica motivo e date. "
                 "Se è «automatica da MOD.128», va regolarizzata l'abilitazione nel MOD.128."),
                ("Come ritiro un timbro?", "Con «Archivia» (data di ritiro = oggi) oppure togliendo «Record attivo (in uso)» e indicando la data di ritiro."),
                ("Che cosa sono le righe «Da gestire»?", "Righe dei vecchi import CSV con un dipendente non trovato in anagrafica: vanno controllate e sistemate."),
            ]),
        ],
    },
]


def render_guida_pdf(*, generato_da: str = "", generato_il: str = "") -> bytes:
    """PDF della guida con intestazione e piè di pagina del modulo MOD.130."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        KeepTogether, ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    navy = colors.HexColor("#1f3a5f")
    grey = colors.HexColor("#64748b")
    ss = getSampleStyleSheet()
    st_title = ParagraphStyle("gt", parent=ss["Title"], textColor=navy, fontSize=20, leading=24, spaceAfter=2)
    st_code = ParagraphStyle("gc", parent=ss["Normal"], textColor=grey, fontSize=10.5, spaceAfter=4)
    st_meta = ParagraphStyle("gm", parent=ss["Normal"], textColor=grey, fontSize=8.5, spaceAfter=12)
    st_h = ParagraphStyle("gh", parent=ss["Heading2"], textColor=navy, fontSize=13, leading=16, spaceBefore=12, spaceAfter=5)
    st_p = ParagraphStyle("gp", parent=ss["Normal"], fontSize=10, leading=14, spaceAfter=5)
    st_toc = ParagraphStyle("gtoc", parent=st_p, spaceAfter=1)
    st_nota = ParagraphStyle("gn", parent=st_p, fontSize=9.5, textColor=colors.HexColor("#7c2d12"), spaceAfter=0)

    def p(text, style=st_p):
        return Paragraph(escape(text), style)

    story = [
        Paragraph(escape(DOC_TITOLO), st_title),
        Paragraph(escape(f"{DOC_CODICE} · Guida d'uso del modulo nel portale NOVICROM HUB"), st_code),
    ]
    meta = " · ".join(x for x in [f"Generata il {generato_il}" if generato_il else "", f"da {generato_da}" if generato_da else ""] if x)
    if meta:
        story.append(Paragraph(escape(meta), st_meta))
    story.append(Paragraph("<b>Indice</b>", st_p))
    for i, sez in enumerate(SEZIONI, 1):
        story.append(p(f"{i}. {sez['titolo']}", st_toc))
    story.append(Spacer(1, 6))

    for i, sez in enumerate(SEZIONI, 1):
        parts = [Paragraph(escape(f"{i}. {sez['titolo']}"), st_h)]
        for kind, content in sez["blocchi"]:
            if kind == "p":
                parts.append(p(content))
            elif kind == "ul":
                parts.append(ListFlowable(
                    [ListItem(p(item), leftIndent=12, value="circle") for item in content],
                    bulletType="bullet", start="•", leftIndent=12, bulletFontSize=8, spaceAfter=5,
                ))
            elif kind == "def":
                for term, desc in content:
                    parts.append(Paragraph(f"<b>{escape(term)}</b> — {escape(desc)}", st_p))
            elif kind == "nota":
                box = Table([[p(content, st_nota)]], colWidths=[174 * mm])
                box.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fff7ed")),
                    ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#fdba74")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]))
                parts += [Spacer(1, 3), box, Spacer(1, 5)]
        story.append(KeepTogether(parts[:2]))
        story.extend(parts[2:])

    def _decor(canvas, doc):
        canvas.saveState()
        w, h = A4
        canvas.setStrokeColor(navy)
        canvas.setLineWidth(0.6)
        canvas.line(18 * mm, h - 12 * mm, w - 18 * mm, h - 12 * mm)
        canvas.setFont("Helvetica-Bold", 8)
        canvas.setFillColor(navy)
        canvas.drawString(18 * mm, h - 10.5 * mm, DOC_TITOLO)
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(w - 18 * mm, h - 10.5 * mm, DOC_CODICE)
        canvas.setFillColor(grey)
        canvas.drawString(18 * mm, 10 * mm, f"{DOC_NOME} · Guida d'uso")
        canvas.drawRightString(w - 18 * mm, 10 * mm, f"Pagina {doc.page}")
        canvas.restoreState()

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=18 * mm, bottomMargin=17 * mm,
        title=f"{DOC_NOME} - Guida d'uso", author="NOVICROM HUB", subject="Guida d'uso del Registro Timbri",
    )
    doc.build(story, onFirstPage=_decor, onLaterPages=_decor)
    return buf.getvalue()
