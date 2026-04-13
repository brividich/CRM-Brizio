"""Genera GUIDA_GESTIONE_RELEASE.pdf nella cartella deployment/."""
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
    TableStyle, HRFlowable, KeepTogether, PageBreak)
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from datetime import datetime
from pathlib import Path

BRAND      = colors.HexColor('#1a56db')
BRAND_DARK = colors.HexColor('#1e429f')
GREEN      = colors.HexColor('#16a34a')
GREEN_BG   = colors.HexColor('#f0fdf4')
GREEN_BD   = colors.HexColor('#86efac')
YELLOW_BG  = colors.HexColor('#fffbeb')
YELLOW_TX  = colors.HexColor('#92400e')
BLUE_BG    = colors.HexColor('#eff6ff')
BLUE_BD    = colors.HexColor('#93c5fd')
CODE_BG    = colors.HexColor('#0d1117')
CODE_FG    = colors.HexColor('#c9d1d9')
GRAY50     = colors.HexColor('#f9fafb')
GRAY100    = colors.HexColor('#f3f4f6')
GRAY200    = colors.HexColor('#e5e7eb')
GRAY400    = colors.HexColor('#9ca3af')
GRAY500    = colors.HexColor('#6b7280')
GRAY600    = colors.HexColor('#4b5563')
GRAY700    = colors.HexColor('#374151')
GRAY800    = colors.HexColor('#1f2937')
GRAY900    = colors.HexColor('#111827')
WHITE      = colors.white
SF  = 'Helvetica'
SFB = 'Helvetica-Bold'
MONO = 'Courier'
W, H = A4

def get_project_version():
    """Legge la versione dalla root del repository."""
    try:
        version_file = Path(__file__).parent.parent / "VERSION"
        return version_file.read_text().strip()
    except Exception:
        return "0.9.15"  # Fallback coerente con CLAUDE.md

def make_styles():
    return {
        'h1':   ParagraphStyle('h1',  fontName=SFB, fontSize=22, textColor=GRAY900, spaceAfter=4),
        'h2':   ParagraphStyle('h2',  fontName=SFB, fontSize=14, textColor=GRAY900, spaceAfter=4, spaceBefore=6),
        'h3':   ParagraphStyle('h3',  fontName=SFB, fontSize=10, textColor=GRAY800, spaceAfter=3, spaceBefore=10),
        'body': ParagraphStyle('body',fontName=SF,  fontSize=9,  textColor=GRAY700, spaceAfter=5, leading=14),
        'sub':  ParagraphStyle('sub', fontName=SF,  fontSize=10, textColor=GRAY500, spaceAfter=14),
        'code': ParagraphStyle('code',fontName=MONO,fontSize=8,  textColor=CODE_FG, backColor=CODE_BG,
                                leftIndent=8, rightIndent=8, spaceAfter=8, spaceBefore=4, leading=12),
        'li':   ParagraphStyle('li',  fontName=SF,  fontSize=9,  textColor=GRAY700, spaceAfter=3,
                                leftIndent=14, leading=13),
        'ci':   ParagraphStyle('ci',  fontName=SF,  fontSize=9,  textColor=colors.HexColor('#1d4ed8'),
                                backColor=BLUE_BG, leftIndent=8, rightIndent=8, borderPad=6, spaceAfter=6, leading=13),
        'co':   ParagraphStyle('co',  fontName=SF,  fontSize=9,  textColor=colors.HexColor('#166534'),
                                backColor=GREEN_BG,leftIndent=8, rightIndent=8, borderPad=6, spaceAfter=6, leading=13),
        'cw':   ParagraphStyle('cw',  fontName=SF,  fontSize=9,  textColor=YELLOW_TX,
                                backColor=YELLOW_BG,leftIndent=8,rightIndent=8, borderPad=6, spaceAfter=6, leading=13),
        'foot': ParagraphStyle('ft',  fontName=SF,  fontSize=8,  textColor=GRAY400, alignment=TA_CENTER),
    }

def section(text, s):
    return [Paragraph(text, s['h2']),
            HRFlowable(width='100%', thickness=1, color=GRAY200, spaceAfter=6)]

def callout(text, kind, s):
    style_key = {'info':'ci','ok':'co','warn':'cw'}.get(kind,'ci')
    bd = {'info':BLUE_BD,'ok':GREEN_BD,'warn':colors.HexColor('#fcd34d')}.get(kind,BLUE_BD)
    t = Table([[Paragraph(text, s[style_key])]], colWidths=[W-4*cm])
    t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(0,0), s[style_key].backColor),
        ('LINEBEFORE', (0,0),(0,0), 4, bd),
        ('TOPPADDING',(0,0),(0,0),8),('BOTTOMPADDING',(0,0),(0,0),8),
        ('LEFTPADDING',(0,0),(0,0),12),('RIGHTPADDING',(0,0),(0,0),8),
    ]))
    return t

def make_table(headers, rows, col_widths=None):
    data = [headers] + rows
    t = Table(data, colWidths=col_widths)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0),(-1,0), GRAY900),
        ('TEXTCOLOR',  (0,0),(-1,0), WHITE),
        ('FONTNAME',   (0,0),(-1,0), SFB),
        ('FONTSIZE',   (0,0),(-1,-1),8.5),
        ('FONTNAME',   (0,1),(-1,-1),SF),
        ('TEXTCOLOR',  (0,1),(-1,-1),GRAY700),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[WHITE,GRAY50]),
        ('GRID',       (0,0),(-1,-1),0.3,GRAY200),
        ('TOPPADDING', (0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5),
        ('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING', (0,0),(-1,-1),8),
        ('VALIGN',     (0,0),(-1,-1),'MIDDLE'),
    ]))
    return t

def step_row(num, title, desc, s):
    num_p  = Paragraph(f'<b>{num}</b>', ParagraphStyle('sn',fontName=SFB,fontSize=10,
                        textColor=WHITE,alignment=TA_CENTER))
    body   = [Paragraph(f'<b>{title}</b>', ParagraphStyle('st',fontName=SFB,fontSize=9,
                         textColor=GRAY900,spaceAfter=2)),
              Paragraph(desc, s['body'])]
    t = Table([[num_p, body]], colWidths=[0.7*cm, W-4.7*cm])
    t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(0,0),BRAND),
        ('VALIGN',(0,0),(-1,-1),'TOP'),
        ('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6),
        ('LEFTPADDING',(0,0),(0,0),4),('RIGHTPADDING',(0,0),(0,0),4),
        ('LEFTPADDING',(1,0),(1,0),10),
        ('LINEBELOW',(0,0),(-1,-1),0.3,GRAY100),
    ]))
    return t

def flow_row(items):
    cells, widths = [], []
    for i,(lbl,sub,bg,fg) in enumerate(items):
        cells.append(Paragraph(f'<b>{lbl}</b><br/><font size=7>{sub}</font>',
            ParagraphStyle('fl',fontName=SFB,fontSize=9,textColor=fg,alignment=TA_CENTER,leading=13)))
        widths.append(3.5*cm)
        if i < len(items)-1:
            cells.append(Paragraph('>', ParagraphStyle('ar',fontName=SF,fontSize=14,
                textColor=GRAY400,alignment=TA_CENTER)))
            widths.append(0.5*cm)
    t = Table([cells], colWidths=widths)
    style_cmds = [('VALIGN',(0,0),(-1,-1),'MIDDLE'),
                  ('TOPPADDING',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),8)]
    for i,(lbl,sub,bg,fg) in enumerate(items):
        col = i*2
        style_cmds += [('BACKGROUND',(col,0),(col,0),bg),
                        ('BOX',(col,0),(col,0),1,GRAY200)]
    t.setStyle(TableStyle(style_cmds))
    return t

def code_block(lines, s):
    text = '<br/>'.join(
        ln.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace(' ','&nbsp;')
        for ln in lines)
    return Paragraph(text, s['code'])

# ── BUILD ─────────────────────────────────────────────────────
out = Path(__file__).parent / 'GUIDA_GESTIONE_RELEASE.pdf'
doc = SimpleDocTemplate(str(out), pagesize=A4,
    leftMargin=2*cm, rightMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)
story = []
s = make_styles()

current_version = get_project_version()

# Copertina
story.append(Spacer(1, 3*cm))
story.append(Table([['']], colWidths=[W-4*cm], rowHeights=[4],
    style=TableStyle([('BACKGROUND',(0,0),(0,0),BRAND)])))
story.append(Spacer(1, 0.5*cm))
story.append(Paragraph('Portale Novicrom', ParagraphStyle('ct',fontName=SFB,fontSize=26,
    textColor=BRAND_DARK,spaceAfter=4)))
story.append(Paragraph('Gestione Release', ParagraphStyle('ct2',fontName=SFB,fontSize=20,
    textColor=GRAY900,spaceAfter=8)))
story.append(Paragraph('Guida completa al flusso DEV &rarr; TEST &rarr; PROD', s['sub']))
story.append(Spacer(1,0.8*cm))
story.append(Table([['']], colWidths=[W-4*cm], rowHeights=[1],
    style=TableStyle([('BACKGROUND',(0,0),(0,0),GRAY200)])))
story.append(Spacer(1,0.5*cm))
meta = [['Versione', current_version],['Data',datetime.now().strftime('%d/%m/%Y')],
        ['Prodotto','Portale Novicrom'],['Azienda','Costruzioni Novicrom SRL']]
mt = Table(meta, colWidths=[4.5*cm,10*cm])
mt.setStyle(TableStyle([('FONTNAME',(0,0),(-1,-1),SF),('FONTSIZE',(0,0),(-1,-1),9),
    ('FONTNAME',(0,0),(0,-1),SFB),('TEXTCOLOR',(0,0),(0,-1),GRAY600),
    ('TEXTCOLOR',(1,0),(1,-1),GRAY800),
    ('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4)]))
story.append(mt)
story.append(PageBreak())

# 1. Introduzione
story += section('1. Cos\'e il Release Manager', s)
story.append(Paragraph(
    'Il <b>Release Manager</b> e una modalita del Setup Wizard che permette di gestire '
    'il ciclo di vita di una release tramite interfaccia grafica, senza usare la riga di '
    'comando o ricordare i parametri degli script PowerShell.', s['body']))
story.append(Spacer(1,0.2*cm))
story.append(make_table(
    ['Operazione','Dove eseguire','Cosa fa'],
    [['Crea Release (DEV)','PC di sviluppo','Crea un file .zip dal codice sorgente'],
     ['Promuovi Release (TEST/PROD)','Server Windows','Deploya il .zip: pip, migrate, junction, IIS']],
    [4*cm,4.5*cm,7.5*cm]))
story.append(Spacer(1,0.2*cm))
story.append(callout('<b>Nota:</b> Il Release Manager non sostituisce il Setup Wizard per la '
    'prima installazione. Configura prima l\'ambiente con avvia_wizard_TEST.bat o '
    'avvia_wizard_PROD.bat, poi usa il Release Manager per le successive promozioni.','info',s))

# 2. Flusso
story += section('2. Flusso DEV &rarr; TEST &rarr; PROD', s)
story.append(Paragraph(
    'La regola d\'oro: <b>un solo artefatto</b> viaggia da DEV a PROD senza essere '
    'ricostruito. Il .zip testato su TEST e lo stesso che vai in produzione.', s['body']))
story.append(Spacer(1,0.3*cm))
story.append(flow_row([
    ('PC Sviluppo','Crea Release',BLUE_BG,colors.HexColor('#1d4ed8')),
    ('.zip','artefatto',GRAY100,GRAY700),
    ('Server TEST','Promuovi',YELLOW_BG,YELLOW_TX),
    ('Server PROD','Stesso .zip',GREEN_BG,colors.HexColor('#166534')),
]))
story.append(Spacer(1,0.4*cm))
for num,title,desc in [
    ('1','Crea Release dal PC di sviluppo',
     'Apri avvia_gestore_release.bat sul PC DEV, seleziona Crea Release, configura cartella sorgente e output.'),
    ('2','Copia il .zip sul server TEST',
     'Copia il file generato in C:\\PortaleNovicrom\\shared\\packages\\ sul server TEST.'),
    ('3','Promuovi su TEST',
     'Sul server TEST apri il Release Manager, seleziona Promuovi Release, scegli il .zip, ambiente TEST.'),
    ('4','Valida su TEST',
     'Verifica il portale, controlla i log, testa i workflow critici.'),
    ('5','Promuovi su PROD (stesso .zip)',
     'Sul server PROD usa lo STESSO .zip gia testato su TEST. Non ripackaggiare mai.'),
]:
    story.append(KeepTogether(step_row(num,title,desc,s)))
    story.append(Spacer(1,0.1*cm))
story.append(callout('<b>Non ripackaggiare mai per PROD.</b> Usare il codice sorgente una seconda volta '
    'introduce il rischio di differenze rispetto a quanto testato su TEST.','warn',s))

# 3. Come avviare
story += section('3. Come avviare il Release Manager', s)
story.append(Paragraph('<b>Metodo 1 - File .bat (raccomandato)</b>', s['h3']))
story.append(make_table(
    ['File','Dove usarlo','Note'],
    [['avvia_gestore_release.bat','PC sviluppo + Server','Auto-elevazione admin. Mostra selezione modalita.']],
    [5.5*cm,4.5*cm,6*cm]))
story.append(Paragraph('<b>Metodo 2 - Riga di comando</b>', s['h3']))
story.append(code_block([
    '# Apre la schermata di selezione modalita',
    'python deployment/setup_wizard.py --mode release',
    '',
    '# Apre direttamente su Crea Release',
    'python deployment/setup_wizard.py --mode create',
    '',
    '# Apre direttamente su Promuovi Release',
    'python deployment/setup_wizard.py --mode promote',
], s))
story.append(callout('<b>Privilegi amministratore richiesti</b> per Promuovi Release '
    '(NTFS junction + riavvio App Pool IIS). Il file .bat gestisce automaticamente la rielevazione.','warn',s))

# 4. Crea Release
story.append(PageBreak())
story += section('4. Crea Release (dal PC di sviluppo)', s)
story.append(Paragraph(
    'Legge il codice sorgente dalla cartella del repository e crea un file .zip compresso, '
    'pronto per essere copiato sui server.', s['body']))
story.append(make_table(
    ['Escluso','Motivo'],
    [['.git/','Storia git non necessaria in produzione'],
     ['.venv/ venv/','Il venv viene ricreato sul server'],
     ['.env','Credenziali: ogni ambiente ha il suo file'],
     ['__pycache__/ *.pyc','Cache compilata, non portabile'],
     ['db.sqlite3','DB locale di sviluppo'],
     ['media/','Upload utenti: rimangono sul server'],
     ['logs/','Log locali'],
     ['staticfiles/','Generati da collectstatic sul server'],
     ['releases/','Release precedenti: non vanno zippate']],
    [4.5*cm,11.5*cm]))
story.append(Spacer(1,0.2*cm))
for num,title,desc in [
    ('1','Apri il Release Manager',
     'Esegui avvia_gestore_release.bat. Seleziona Crea Release e clicca Avanti.'),
    ('2','Configura sorgente e output',
     'Cartella sorgente: radice del repository (es. C:\\Dev\\Portale Novicrom). '
     'Output: dove salvare il .zip (default: C:\\PortaleNovicrom\\shared\\packages\\).'),
    ('3','Clicca Esegui',
     'Il wizard crea portale-novicrom-vX.Y.Z-YYYYMMDD_HHmmss.zip e verifica l\'integrita. '
     'La versione viene letta automaticamente da django_app/config/settings/base.py.'),
]:
    story.append(KeepTogether(step_row(num,title,desc,s)))
    story.append(Spacer(1,0.1*cm))
story.append(code_block([
    '-- Preparazione --',
    '  Versione rilevata: v0.8.3',
    '  Output: C:\\PortaleNovicrom\\shared\\packages\\portale-novicrom-v0.8.3-20260321.zip',
    '-- Creazione portale-novicrom-v0.8.3-20260321_143022.zip --',
    '  [OK] 1247 file - 3.4 MB',
    '-- Verifica integrita zip --',
    '  [OK] Zip integro',
    '  [OK] portale-novicrom-v0.8.3-20260321_143022.zip pronta per il deploy!',
], s))

# 5. Promuovi Release
story.append(PageBreak())
story += section('5. Promuovi Release (su TEST o PROD)', s)
story.append(Paragraph(
    'Prende un file .zip gia creato e lo deploya su un ambiente server, eseguendo automaticamente '
    'tutte le operazioni: pip install, collectstatic, migrate, attivazione junction, riavvio IIS.', s['body']))
story.append(callout('Prerequisito: l\'ambiente deve essere gia configurato con il Setup Wizard '
    '(venv + .env esistenti in ENV\\venv\\ e ENV\\config\\).','warn',s))
story.append(make_table(
    ['#','Operazione','Dettaglio'],
    [['1','Estrazione zip','Estrae in releases\\YYYYMMDD_HHmmss\\'],
     ['2','Copia .env','Copia ENV\\config\\.env nel release estratto'],
     ['3','pip install','Aggiorna le dipendenze Python dal requirements.txt'],
     ['4','collectstatic','Raccoglie i file statici in ENV\\static\\'],
     ['5','Django migrate','Applica le nuove migrazioni al database'],
     ['6','createcachetable','Crea/aggiorna la tabella cache Django'],
     ['7','Attivazione junction','Salva release precedente, aggiorna junction current\\'],
     ['8','Riavvio IIS','Ricicla App Pool e avvia il sito']],
    [0.6*cm,4.5*cm,10.9*cm]))
story.append(Spacer(1,0.2*cm))
for num,title,desc in [
    ('1','Copia il .zip sul server',
     'Copia il file .zip in C:\\PortaleNovicrom\\shared\\packages\\ sul server destinatario.'),
    ('2','Apri il Release Manager come Amministratore',
     'Esegui avvia_gestore_release.bat (auto-elevazione). Seleziona Promuovi Release.'),
    ('3','Seleziona pacchetto e ambiente',
     'Il wizard rileva automaticamente il .zip piu recente in shared\\packages\\. '
     'Seleziona TEST o PROD e verifica la directory base.'),
    ('4','Clicca Esegui e attendi',
     'Il log mostra l\'avanzamento in tempo reale. Non chiudere la finestra.'),
]:
    story.append(KeepTogether(step_row(num,title,desc,s)))
    story.append(Spacer(1,0.1*cm))
story.append(code_block([
    '-- Estrazione pacchetto --',
    '  [OK] Estratto in C:\\PortaleNovicrom\\TEST\\releases\\20260321_143250',
    '-- Copia configurazione .env --',
    '  [OK] .env copiato da C:\\PortaleNovicrom\\TEST\\config\\.env',
    '-- Aggiornamento dipendenze pip -- [OK]',
    '-- collectstatic -- [OK]',
    '-- Django migrate -- [OK]  createcachetable -- [OK]',
    '-- Attivazione release --',
    '  [OK] Release precedente salvata: ...\\releases\\20260318_091200',
    '  [OK] current -> 20260321_143250',
    '-- Riavvio App Pool IIS --',
    '  [OK] App Pool PortaleNovicrom-TEST riciclato',
    '  Release TEST attivata!',
], s))

# 6. Rollback
story += section('6. Rollback', s)
story.append(Paragraph(
    'Il Release Manager salva automaticamente la release precedente in '
    'run\\previous_release.txt prima di ogni attivazione.', s['body']))
story.append(Paragraph('<b>Script PowerShell (piu veloce):</b>', s['h3']))
story.append(code_block([
    '# Rollback TEST',
    'powershell -ExecutionPolicy Bypass -File',
    '  C:\\PortaleNovicrom\\shared\\scripts\\rollback-release.ps1 -Environment test',
    '',
    '# Rollback PROD',
    'powershell -ExecutionPolicy Bypass -File',
    '  C:\\PortaleNovicrom\\shared\\scripts\\rollback-release.ps1 -Environment prod',
], s))
story.append(callout('<b>Rollback in meno di 30 secondi.</b> La junction swap + recycle '
    'dell\'App Pool e immediata. Non c\'e copia di file.','ok',s))

# 7. CLI
story += section('7. Argomenti CLI', s)
story.append(make_table(
    ['Argomento','Valori','Effetto'],
    [['--mode release','-','Apre il Release Manager (selezione modalita)'],
     ['--mode create', '-','Apre direttamente su Crea Release'],
     ['--mode promote','-','Apre direttamente su Promuovi Release'],
     ['--env','dev / test / prod','Preseleziona ambiente nel Setup Wizard (non Release Manager)']],
    [3.5*cm,3.5*cm,9*cm]))

# 8. Struttura
story += section('8. Struttura directory server', s)
story.append(code_block([
    'C:\\PortaleNovicrom\\',
    '|-- shared\\',
    '|   |-- packages\\   <- Dove copiare i .zip da DEV',
    '|   |-- backups\\    <- Backup ambiente',
    '|   +-- scripts\\   <- Script PowerShell',
    '|',
    '|-- TEST\\',
    '|   |-- config\\.env              <- Configurazione (non versionata)',
    '|   |-- venv\\                    <- Virtualenv Python',
    '|   |-- releases\\20260321_143250\\ <- Release attuale',
    '|   |-- current\\                 <- Junction -> releases\\20260321_143250\\',
    '|   |-- static\\  media\\  logs\\',
    '|   +-- run\\previous_release.txt <- Usato dal rollback',
    '|',
    '+-- PROD\\  (struttura identica a TEST)',
], s))

# 9. Prerequisiti
story += section('9. Prerequisiti', s)
story.append(Paragraph('<b>Per Crea Release (PC sviluppo):</b>', s['h3']))
for item in ['Python 3.11+ con tkinter','Accesso in lettura alla cartella del repository',
             'Accesso in scrittura alla cartella output']:
    story.append(Paragraph(f'[ ]  {item}', s['li']))
story.append(Paragraph('<b>Per Promuovi Release (server):</b>', s['h3']))
for item in ['Python 3.11+ con tkinter',
             'Eseguire come Amministratore (junction NTFS + IIS)',
             'IIS installato con HttpPlatformHandler',
             'Ambiente gia configurato con Setup Wizard (venv + .env esistenti)',
             'ODBC Driver 17 o 18 for SQL Server',
             'File .zip copiato in shared\\packages\\']:
    story.append(Paragraph(f'[ ]  {item}', s['li']))

# 10. FAQ
story.append(PageBreak())
story += section('10. FAQ', s)
for q, a in [
    ('Il .zip viene rilevato automaticamente?',
     'Si. Il Release Manager cerca il .zip piu recente in shared\\packages\\ e lo preseleziona.'),
    ('Posso deployare la stessa release piu volte?',
     'Si. Ogni esecuzione crea una nuova directory releases\\YYYYMMDD_HHmmss\\ e aggiorna la junction.'),
    ('Cosa succede se migrate fallisce?',
     'Il processo continua, la junction viene aggiornata. Se il portale non funziona, usa rollback-release.ps1.'),
    ('Come aggiorno il .env dopo un deploy?',
     'Modifica ENV\\config\\.env e poi esegui Promuovi Release con lo stesso .zip.'),
    ('Posso usare il Release Manager senza il Setup Wizard?',
     'No. Il Release Manager richiede che venv e .env esistano gia (configurati dal Setup Wizard).'),
    ('Quante release vengono mantenute?',
     'Tutte, per default. Usa remove-old-releases.ps1 per pulizia automatica (mantiene le ultime 5).'),
]:
    story.append(KeepTogether([
        Paragraph(q, s['h3']),
        Paragraph(a, s['body']),
        Spacer(1,0.1*cm),
    ]))

# Footer
story.append(Spacer(1,1*cm))
story.append(HRFlowable(width='100%',thickness=0.5,color=GRAY200))
story.append(Spacer(1,0.2*cm))
story.append(Paragraph(
    f'Portale Novicrom  |  Gestione Release  |  Costruzioni Novicrom SRL  |  v{current_version}  |  {datetime.now().strftime("%d/%m/%Y")}',
    s['foot']))

doc.build(story)
print('[OK] PDF generato:', out)
