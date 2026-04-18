"""Genera doc/anagrafica_utenti_dipendenti_schema.pdf"""
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, PageBreak
)
from reportlab.lib.enums import TA_LEFT
from datetime import date

OUTPUT = "doc/anagrafica_utenti_dipendenti_schema.pdf"

doc = SimpleDocTemplate(
    OUTPUT,
    pagesize=A4,
    rightMargin=2*cm, leftMargin=2*cm,
    topMargin=2*cm, bottomMargin=2*cm,
)

styles = getSampleStyleSheet()

H1  = ParagraphStyle("H1",  parent=styles["Heading1"], fontSize=18, spaceAfter=6,  textColor=colors.HexColor("#1e3a5f"))
H2  = ParagraphStyle("H2",  parent=styles["Heading2"], fontSize=13, spaceBefore=14, spaceAfter=4,  textColor=colors.HexColor("#2563eb"))
H3  = ParagraphStyle("H3",  parent=styles["Heading3"], fontSize=10, spaceBefore=8,  spaceAfter=3,  textColor=colors.HexColor("#374151"))
BODY = ParagraphStyle("BODY", parent=styles["Normal"], fontSize=9,  leading=13, textColor=colors.HexColor("#1f2937"))
SMALL= ParagraphStyle("SMALL",parent=styles["Normal"], fontSize=8,  leading=11, textColor=colors.HexColor("#6b7280"))
NOTE = ParagraphStyle("NOTE", parent=styles["Normal"], fontSize=8.5, leading=12,
                      textColor=colors.HexColor("#92400e"), backColor=colors.HexColor("#fffbeb"),
                      leftIndent=8, rightIndent=8, spaceBefore=4, spaceAfter=4)

COL_HEADER   = colors.HexColor("#1e3a5f")
COL_ROW_ODD  = colors.HexColor("#f8fafc")
COL_ROW_EVEN = colors.white
COL_BORDER   = colors.HexColor("#cbd5e1")

def mktable(headers, rows, col_widths=None):
    hrow = [Paragraph("<b>%s</b>" % h,
                       ParagraphStyle("TH", parent=BODY, fontSize=8.5, textColor=colors.white))
            for h in headers]
    data = [hrow]
    for row in rows:
        data.append([Paragraph(str(c), SMALL) for c in row])
    style = TableStyle([
        ("BACKGROUND",   (0,0), (-1,0),  COL_HEADER),
        ("ROWBACKGROUNDS",(0,1),(-1,-1), [COL_ROW_ODD, COL_ROW_EVEN]),
        ("GRID",         (0,0), (-1,-1), 0.4, COL_BORDER),
        ("FONTNAME",     (0,0), (-1,0),  "Helvetica-Bold"),
        ("FONTSIZE",     (0,0), (-1,0),  8.5),
        ("TOPPADDING",   (0,0), (-1,-1), 4),
        ("BOTTOMPADDING",(0,0), (-1,-1), 4),
        ("LEFTPADDING",  (0,0), (-1,-1), 5),
        ("RIGHTPADDING", (0,0), (-1,-1), 5),
        ("VALIGN",       (0,0), (-1,-1), "TOP"),
    ])
    return Table(data, colWidths=col_widths, style=style, repeatRows=1)

story = []
COLS4 = [4.5*cm, 3.5*cm, 2.2*cm, 6.1*cm]

# ── Cover ───────────────────────────────────────────────────────────────────
story.append(Spacer(1, 1.5*cm))
story.append(Paragraph("NOVICROM HUB",
    ParagraphStyle("BRAND", parent=H1, fontSize=10, textColor=colors.HexColor("#6b7280"), spaceAfter=2)))
story.append(Paragraph("Schema Database<br/>Modulo Anagrafica &mdash; Utenti &amp; Dipendenti", H1))
story.append(Spacer(1, 0.3*cm))
story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#2563eb")))
story.append(Spacer(1, 0.3*cm))
story.append(Paragraph("Data generazione: %s  &middot;  Versione app: 1.0.0" % date.today().strftime("%d/%m/%Y"), SMALL))
story.append(Spacer(1, 1*cm))

story.append(Paragraph("Indice tabelle", H2))
for section, items in [
    ("Tabelle legacy SQL Server (fonte primaria dipendenti)", [
        "utenti &mdash; account di accesso al portale",
        "anagrafica_dipendenti &mdash; dati anagrafici dipendenti",
    ]),
    ("Tabelle Django &mdash; app anagrafica", [
        "Fornitore", "FornitoreDocumento", "FornitoreOrdine", "FornitoreValutazione",
        "FornitoreAsset", "RuoloOperativo", "DipendenteRuoloOperativo",
        "DipendenteStatLayout", "AnagraficaStatPermission (singleton)",
        "Mansione", "TipoQualifica", "DipendenteQualifica",
    ]),
]:
    story.append(Paragraph("<b>%s</b>" % section, BODY))
    for item in items:
        story.append(Paragraph("&nbsp;&nbsp;&bull; %s" % item, SMALL))
story.append(PageBreak())

# ══════════════════════════════════════════════════════════════════════════════
# 1. TABELLE LEGACY
# ══════════════════════════════════════════════════════════════════════════════
story.append(Paragraph("1. Tabelle Legacy SQL Server", H2))
story.append(Paragraph(
    "Non gestite da Django migrations. Il modello Django e' in sola lettura "
    "(migration 0029 applicata con <code>--fake</code>). "
    "Le scritture avvengono tramite SQL raw in <code>core/legacy_anagrafica.py</code>.",
    BODY))
story.append(Spacer(1, 0.3*cm))

# utenti
story.append(Paragraph("1.1 &mdash; Tabella: utenti", H3))
story.append(Paragraph("Modello Django: core.UtenteLegacy  &middot;  db_table: utenti", SMALL))
story.append(Spacer(1, 0.15*cm))
story.append(mktable(
    ["Campo", "Tipo DB", "Nullable", "Note"],
    [
        ["id",                    "INT (PK)",        "NO",  "Chiave primaria auto-increment"],
        ["nome",                  "NVARCHAR(200)",   "NO",  "Nome visualizzato (puo' contenere nome+cognome unificati)"],
        ["email",                 "NVARCHAR(200)",   "Si'", "UPN Active Directory usato come login_id (es. l.bova@cnovicrom.local)"],
        ["password",              "NVARCHAR(500)",   "NO",  "Hash password (non usata in prod con AD)"],
        ["ruolo",                 "NVARCHAR(100)",   "Si'", "Stringa nome ruolo (denormalizzata)"],
        ["attivo",                "BIT",             "NO",  "1=attivo, 0=disabilitato; default 1"],
        ["deve_cambiare_password","BIT",             "NO",  "Flag reset password; default 0"],
        ["ruolo_id",              "INT (FK->ruoli)", "Si'", "FK verso tabella ruoli"],
    ],
    col_widths=[3.8*cm, 3.2*cm, 1.8*cm, 7.5*cm],
))
story.append(Spacer(1, 0.1*cm))
story.append(Paragraph(
    "ATTENZIONE: il campo email non e' l'indirizzo mail reale ma il login UPN "
    "(es. l.bova@cnovicrom.local). Per le notifiche usare anagrafica_dipendenti.email_notifica.",
    NOTE))
story.append(Spacer(1, 0.5*cm))

# anagrafica_dipendenti
story.append(Paragraph("1.2 &mdash; Tabella: anagrafica_dipendenti", H3))
story.append(Paragraph("Modello Django: core.AnagraficaDipendente  &middot;  db_table: anagrafica_dipendenti", SMALL))
story.append(Spacer(1, 0.15*cm))
story.append(mktable(
    ["Campo", "Tipo DB", "Nullable", "Note"],
    [
        ["id",             "INT (PK)",             "NO",  "Chiave primaria auto-increment"],
        ["aliasusername",  "NVARCHAR(200)",         "Si'", "Username breve normalizzato (es. l.bova); derivato da email UPN"],
        ["nome",           "NVARCHAR(200)",         "Si'", "Nome dipendente"],
        ["cognome",        "NVARCHAR(200)",         "Si'", "Cognome dipendente"],
        ["mansione",       "NVARCHAR(200)",         "Si'", "Job title [*aggiunto da ensure_anagrafica_schema]"],
        ["reparto",        "NVARCHAR(200)",         "Si'", "Reparto aziendale"],
        ["ruolo",          "NVARCHAR(200)",         "Si'", "Ruolo testuale legacy [*aggiunto da ensure_anagrafica_schema]"],
        ["matricola",      "NVARCHAR(100)",         "Si'", "Matricola aziendale [*aggiunto da ensure_anagrafica_schema]"],
        ["attivo",         "BIT",                   "Si'", "1=attivo; NULL trattato come attivo [*aggiunto da ensure_anagrafica_schema]"],
        ["email",          "NVARCHAR(200)",         "Si'", "Login ID copiato da utenti.email; solo per match legacy, NON per notifiche"],
        ["email_notifica", "NVARCHAR(200)",         "Si'", "Email reale notifiche (es. l.bova@gmail.com) [*aggiunto da ensure_anagrafica_schema]"],
        ["utente_id",      "INT (FK->utenti, 1:1)", "Si'", "OneToOne verso utenti.id [*aggiunto da ensure_anagrafica_schema]"],
    ],
    col_widths=[3.8*cm, 3.4*cm, 1.6*cm, 7.5*cm],
))
story.append(Spacer(1, 0.1*cm))
story.append(Paragraph(
    "[*] Colonne aggiunte automaticamente alla prima esecuzione se mancanti (ALTER TABLE idempotente "
    "in ensure_anagrafica_schema()). In ambienti nuovi possono non esistere prima del primo avvio.",
    NOTE))
story.append(Spacer(1, 0.3*cm))

story.append(Paragraph("Logica deduplicazione", H3))
story.append(Paragraph(
    "fetch_anagrafica_rows(deduplicate=True) aggrega i duplicati per chiave "
    "(nome+cognome normalizzato) o aliasusername. "
    "Score di preferenza: utente_id presente > nome non-ALLCAPS > cognome non-ALLCAPS > "
    "aliasusername presente > attivo > id maggiore. "
    "I campi vuoti del record preferito vengono completati dai duplicati (merge).",
    BODY))
story.append(Spacer(1, 0.2*cm))
story.append(Paragraph("Risoluzione email notifica (runtime, non modifica il DB):", H3))
story.append(mktable(
    ["Priorita'", "Campo", "Fonte", "Uso"],
    [
        ["1 (alta)",     "email_notifica", "anagrafica_dipendenti", "Email reale notifiche"],
        ["2 (fallback)", "email",          "anagrafica_dipendenti", "UPN login; usato solo se email_notifica vuota"],
        ["3 (runtime)",  "email_notifica (sovrascritto)", "fetch_anagrafica_rows()", "Normalizzato nel dict di ritorno; non scritto su DB"],
    ],
    col_widths=[2.5*cm, 3.5*cm, 4*cm, 6.3*cm],
))
story.append(PageBreak())

# ══════════════════════════════════════════════════════════════════════════════
# 2. TABELLE DJANGO
# ══════════════════════════════════════════════════════════════════════════════
story.append(Paragraph("2. Tabelle Django &mdash; app anagrafica", H2))
story.append(Paragraph(
    "Tabelle gestite da Django ORM con migrations standard. "
    "I dipendenti non hanno un modello Django nativo: sono sempre referenziati tramite "
    "legacy_anagrafica_id (FK logica verso anagrafica_dipendenti.id).",
    BODY))
story.append(Spacer(1, 0.3*cm))

# Fornitore
story.append(Paragraph("2.1 &mdash; Fornitore", H3))
story.append(Paragraph("Anagrafica fornitori aziendali.", SMALL))
story.append(Spacer(1, 0.1*cm))
story.append(mktable(
    ["Campo", "Tipo", "Obbl.", "Note"],
    [
        ["id",              "AutoField (PK)",  "-",  ""],
        ["ragione_sociale", "CharField(200)",  "Si'",""],
        ["piva",            "CharField(11)",   "No", "P.IVA"],
        ["codice_fiscale",  "CharField(16)",   "No", ""],
        ["indirizzo / citta / cap / provincia", "CharField", "No", ""],
        ["telefono / email / pec / website",    "vari",      "No", ""],
        ["categoria",       "CharField choices","No","MATERIALI SERVIZI ATTREZZATURE LOGISTICA IT MANUTENZIONE ALTRO"],
        ["is_active",       "BooleanField",    "-",  "Default True"],
        ["note",            "TextField",       "No", ""],
        ["created_at / updated_at","DateTimeField","-","Auto"],
    ], col_widths=COLS4))
story.append(Paragraph("Proprieta' calcolate: punteggio_medio (media valutazioni), spesa_totale (somma ordini).", SMALL))
story.append(Spacer(1, 0.35*cm))

# FornitoreDocumento
story.append(Paragraph("2.2 &mdash; FornitoreDocumento", H3))
story.append(Paragraph("Allegati documentali del fornitore.", SMALL))
story.append(Spacer(1, 0.1*cm))
story.append(mktable(
    ["Campo", "Tipo", "Obbl.", "Note"],
    [
        ["fornitore",   "FK -> Fornitore (CASCADE)",  "Si'","related_name: documenti"],
        ["nome",        "CharField(200)",              "Si'",""],
        ["tipo",        "CharField choices",           "Si'","CONTRATTO OFFERTA CERTIFICAZIONE VISURA ALTRO"],
        ["file",        "FileField",                   "Si'","Upload: anagrafica/fornitori/<id>/<ts>_<stem>.<ext>"],
        ["note",        "CharField(255)",              "No", ""],
        ["uploaded_by", "FK -> User (SET_NULL)",       "No", ""],
        ["uploaded_at", "DateTimeField",               "-",  "Auto"],
    ], col_widths=COLS4))
story.append(Paragraph("Regola: cancellazione record -> file fisico rimosso dallo storage (override delete()).", NOTE))
story.append(Spacer(1, 0.35*cm))

# FornitoreOrdine
story.append(Paragraph("2.3 &mdash; FornitoreOrdine", H3))
story.append(Paragraph("Ordini e acquisti legati a un fornitore.", SMALL))
story.append(Spacer(1, 0.1*cm))
story.append(mktable(
    ["Campo", "Tipo", "Obbl.", "Note"],
    [
        ["fornitore",     "FK -> Fornitore (CASCADE)",  "Si'","related_name: ordini"],
        ["numero_ordine", "CharField(50)",               "No", ""],
        ["data_ordine",   "DateField",                   "Si'",""],
        ["importo",       "DecimalField(12,2)",           "Si'",""],
        ["descrizione",   "TextField",                   "No", ""],
        ["stato",         "CharField choices",           "Si'","BOZZA INVIATO CONFERMATO CONSEGNATO ANNULLATO"],
        ["note",          "CharField(255)",              "No", ""],
        ["created_by",    "FK -> User (SET_NULL)",       "No", ""],
        ["created_at / updated_at","DateTimeField",      "-",  "Auto"],
    ], col_widths=COLS4))
story.append(Spacer(1, 0.35*cm))

# FornitoreValutazione
story.append(Paragraph("2.4 &mdash; FornitoreValutazione", H3))
story.append(Paragraph("Rating fornitore su 3 dimensioni (scala 1-5).", SMALL))
story.append(Spacer(1, 0.1*cm))
story.append(mktable(
    ["Campo", "Tipo", "Obbl.", "Note"],
    [
        ["fornitore",     "FK -> Fornitore (CASCADE)",  "Si'","related_name: valutazioni"],
        ["data",          "DateField",                  "Si'","Default oggi"],
        ["qualita",       "IntegerField [1-5]",          "Si'","Validator min=1 max=5"],
        ["puntualita",    "IntegerField [1-5]",          "Si'","Validator min=1 max=5"],
        ["comunicazione", "IntegerField [1-5]",          "Si'","Validator min=1 max=5"],
        ["note",          "TextField",                  "No", ""],
        ["valutato_da",   "FK -> User (SET_NULL)",      "No", ""],
        ["created_at",    "DateTimeField",              "-",  "Auto"],
    ], col_widths=COLS4))
story.append(Paragraph("Proprieta': media = (qualita + puntualita + comunicazione) / 3", SMALL))
story.append(PageBreak())

# FornitoreAsset
story.append(Paragraph("2.5 &mdash; FornitoreAsset", H3))
story.append(Paragraph("Relazione fornitore <-> asset per manutenzione / assistenza / noleggio / fornitura.", SMALL))
story.append(Spacer(1, 0.1*cm))
story.append(mktable(
    ["Campo", "Tipo", "Obbl.", "Note"],
    [
        ["fornitore",   "FK -> Fornitore (CASCADE)",     "Si'","related_name: asset_assegnati"],
        ["asset",       "FK -> assets.Asset (CASCADE)",  "Si'","related_name: fornitori_manutenzione"],
        ["tipo",        "CharField choices",             "Si'","MANUTENZIONE ASSISTENZA NOLEGGIO FORNITURA"],
        ["data_inizio", "DateField",                     "Si'","Default oggi"],
        ["data_fine",   "DateField",                     "No", "null/blank; se assente il contratto e' attivo"],
        ["note",        "CharField(255)",                "No", ""],
        ["created_by",  "FK -> User (SET_NULL)",         "No", ""],
        ["created_at",  "DateTimeField",                 "-",  "Auto"],
    ], col_widths=COLS4))
story.append(Paragraph(
    "Vincolo univoco: unique(fornitore, asset, tipo). "
    "Proprieta': is_attivo -> data_fine is None OR data_fine >= oggi.",
    NOTE))
story.append(Spacer(1, 0.35*cm))

# RuoloOperativo
story.append(Paragraph("2.6 &mdash; RuoloOperativo", H3))
story.append(Paragraph("Catalogo ruoli aziendali (preposto, RSPP, squadra antincendio...).", SMALL))
story.append(Spacer(1, 0.1*cm))
story.append(mktable(
    ["Campo", "Tipo", "Obbl.", "Note"],
    [
        ["nome",        "CharField(100)",  "Si'","unique"],
        ["descrizione", "TextField",       "No", ""],
        ["colore",      "CharField(7)",    "Si'","Hex es. #1d4ed8; default #64748b"],
        ["icona",       "CharField(10)",   "No", "Emoji o testo breve"],
        ["is_active",   "BooleanField",    "-",  "Default True"],
        ["created_at",  "DateTimeField",   "-",  "Auto"],
    ], col_widths=COLS4))
story.append(Spacer(1, 0.35*cm))

# DipendenteRuoloOperativo
story.append(Paragraph("2.7 &mdash; DipendenteRuoloOperativo", H3))
story.append(Paragraph("Assegnazione ruolo operativo a dipendente (ponte verso anagrafica legacy).", SMALL))
story.append(Spacer(1, 0.1*cm))
story.append(mktable(
    ["Campo", "Tipo", "Obbl.", "Note"],
    [
        ["legacy_anagrafica_id","IntegerField (db_index)","Si'","FK logica verso anagrafica_dipendenti.id"],
        ["ruolo",    "FK -> RuoloOperativo (CASCADE)", "Si'","related_name: assegnazioni"],
        ["assegnato_da","FK -> User (SET_NULL)",       "No", ""],
        ["assegnato_il","DateTimeField",               "-",  "Auto"],
    ], col_widths=COLS4))
story.append(Paragraph("Vincolo: unique_together(legacy_anagrafica_id, ruolo).", NOTE))
story.append(Spacer(1, 0.35*cm))

# DipendenteStatLayout
story.append(Paragraph("2.8 &mdash; DipendenteStatLayout", H3))
story.append(Paragraph("Layout e visibilita' widget statistiche scheda dipendente, per singolo utente viewer.", SMALL))
story.append(Spacer(1, 0.1*cm))
story.append(mktable(
    ["Campo", "Tipo", "Obbl.", "Note"],
    [
        ["viewer_user_id","IntegerField (unique)", "Si'","ID Django User; un record per utente"],
        ["hidden",   "JSONField",                  "-",  "Lista widget_id nascosti; default []"],
        ["order",    "JSONField",                  "-",  "Ordine personalizzato widget_id; default []"],
        ["updated_at","DateTimeField",             "-",  "Auto"],
    ], col_widths=COLS4))
story.append(Spacer(1, 0.35*cm))

# AnagraficaStatPermission
story.append(Paragraph("2.9 &mdash; AnagraficaStatPermission (singleton)", H3))
story.append(Paragraph("Chi puo' vedere la sezione statistiche nella scheda dipendente. Sempre un solo record (pk=1).", SMALL))
story.append(Spacer(1, 0.1*cm))
story.append(mktable(
    ["Campo", "Tipo", "Obbl.", "Note"],
    [
        ["id",       "AutoField (PK)",   "-",  "Sempre pk=1"],
        ["accesso",  "CharField choices","Si'","TUTTI ADMIN RUOLI; default ADMIN"],
        ["ruolo_ids","JSONField",        "-",  "Lista ruolo_id ACL legacy; attivo solo se accesso=RUOLI"],
    ], col_widths=COLS4))
story.append(Paragraph("Accesso: AnagraficaStatPermission.get_instance() -> get_or_create su pk=1.", NOTE))
story.append(Spacer(1, 0.35*cm))

# Mansione
story.append(Paragraph("2.10 &mdash; Mansione", H3))
story.append(Paragraph("Catalogo job title aziendali, pensato per sincronizzarsi con il campo legacy.", SMALL))
story.append(Spacer(1, 0.1*cm))
story.append(mktable(
    ["Campo", "Tipo", "Obbl.", "Note"],
    [
        ["nome",        "CharField(100)",   "Si'","unique"],
        ["categoria",   "CharField choices","No", "OPERAIO IMPIEGATO QUADRO DIRIGENTE ALTRO"],
        ["descrizione", "TextField",        "No", ""],
        ["colore",      "CharField(7)",     "Si'","Hex; default #64748b"],
        ["is_active",   "BooleanField",     "-",  "Default True"],
        ["created_at",  "DateTimeField",    "-",  "Auto"],
    ], col_widths=COLS4))
story.append(PageBreak())

# TipoQualifica
story.append(Paragraph("2.11 &mdash; TipoQualifica", H3))
story.append(Paragraph("Catalogo tipi qualifiche/certificazioni con durata di validita' automatica.", SMALL))
story.append(Spacer(1, 0.1*cm))
story.append(mktable(
    ["Campo", "Tipo", "Obbl.", "Note"],
    [
        ["nome",         "CharField(150)",   "Si'","unique"],
        ["categoria",    "CharField choices","Si'","SICUREZZA PROFESSIONALE GESTIONALE ALTRO"],
        ["durata_mesi",  "PositiveSmallInt", "Si'","0 = nessuna scadenza automatica"],
        ["descrizione",  "TextField",        "No", ""],
        ["is_active",    "BooleanField",     "-",  "Default True"],
        ["created_at",   "DateTimeField",    "-",  "Auto"],
    ], col_widths=COLS4))
story.append(Spacer(1, 0.35*cm))

# DipendenteQualifica
story.append(Paragraph("2.12 &mdash; DipendenteQualifica", H3))
story.append(Paragraph("Assegnazione qualifica/certificazione a dipendente legacy con tracking scadenza.", SMALL))
story.append(Spacer(1, 0.1*cm))
story.append(mktable(
    ["Campo", "Tipo", "Obbl.", "Note"],
    [
        ["legacy_anagrafica_id","IntegerField (db_index)","Si'","FK logica verso anagrafica_dipendenti.id"],
        ["tipo",          "FK -> TipoQualifica (CASCADE)","Si'","related_name: assegnazioni"],
        ["data_conseguimento","DateField",                "No", "null/blank"],
        ["data_scadenza", "DateField",                    "No", "null/blank; calcolabile da tipo.durata_mesi"],
        ["note",          "CharField(255)",               "No", ""],
        ["assegnato_da",  "FK -> User (SET_NULL)",        "No", ""],
        ["created_at",    "DateTimeField",                "-",  "Auto"],
    ], col_widths=COLS4))
story.append(Paragraph(
    "Proprieta': is_scaduta -> data_scadenza < oggi. "
    "in_scadenza -> scade entro 60 giorni e non ancora scaduta.",
    NOTE))
story.append(PageBreak())

# ══════════════════════════════════════════════════════════════════════════════
# 3. RELAZIONI INTER-APP
# ══════════════════════════════════════════════════════════════════════════════
story.append(Paragraph("3. Relazioni inter-app e note architetturali", H2))
story.append(Spacer(1, 0.2*cm))
story.append(mktable(
    ["Origine", "Destinazione", "Tipo", "Direzione"],
    [
        ["anagrafica.FornitoreAsset",        "assets.Asset",              "FK CASCADE",   "Fornitore -> Asset"],
        ["assets.WorkOrder",                 "anagrafica.Fornitore",      "FK SET_NULL",  "OdL -> Fornitore"],
        ["assets.PeriodicVerification",      "anagrafica.Fornitore",      "FK SET_NULL",  "Verifica -> Fornitore"],
        ["tickets.Ticket",                   "anagrafica.Fornitore",      "FK SET_NULL",  "Ticket -> Fornitore"],
        ["anagrafica.DipendenteRuoloOperativo","anagrafica_dipendenti.id","FK logica",    "RuoloOperativo -> Dipendente"],
        ["anagrafica.DipendenteQualifica",   "anagrafica_dipendenti.id",  "FK logica",    "Qualifica -> Dipendente"],
        ["core.AnagraficaDipendente",        "core.UtenteLegacy (utente_id)","OneToOne SET_NULL","Anagrafica -> Utente login"],
    ],
    col_widths=[4.8*cm, 4.8*cm, 2.6*cm, 4.1*cm],
))
story.append(Spacer(1, 0.4*cm))

story.append(Paragraph("Pattern architetturale &mdash; dipendenti", H3))
story.append(Paragraph(
    "I dipendenti non hanno un modello Django nativo nella app anagrafica. "
    "La fonte di verita' e' la tabella legacy anagrafica_dipendenti su SQL Server. "
    "Tutte le tabelle Django che devono agganciare un dipendente usano il campo "
    "legacy_anagrafica_id (IntegerField con db_index) come FK logica non enforced dal DB. "
    "Questo permette di aggiungere/rimuovere record Django senza dipendere dallo schema legacy.",
    BODY))
story.append(Spacer(1, 0.5*cm))
story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cbd5e1")))
story.append(Spacer(1, 0.2*cm))
story.append(Paragraph(
    "NOVICROM HUB &middot; Schema generato da codice sorgente &middot; %s &middot; "
    "Sorgenti: core/legacy_models.py  core/legacy_anagrafica.py  anagrafica/models.py" % date.today().strftime("%d/%m/%Y"),
    SMALL))

doc.build(story)
print("PDF generato:", OUTPUT)
