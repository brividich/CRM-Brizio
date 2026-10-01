"""Build the public, synthetic-only PDF runbook with existing ReportLab."""
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "deployment/docs/Guida_deploy_qcluster.pdf"
FONT_DIR = Path("C:/Windows/Fonts")
for alias, name in [("Guide", "arial.ttf"), ("GuideBold", "arialbd.ttf"), ("GuideMono", "consola.ttf")]:
    pdfmetrics.registerFont(TTFont(alias, str(FONT_DIR / name)))
pdfmetrics.registerFontFamily("Guide", normal="Guide", bold="GuideBold", italic="Guide", boldItalic="GuideBold")

NAVY = colors.HexColor("#16324F")
ORANGE = colors.HexColor("#E86518")
GRAY = colors.HexColor("#48586A")
PALE = colors.HexColor("#F1F5F9")
WIDTH = A4[0] - 92
styles = {
    "title": ParagraphStyle("title", fontName="GuideBold", fontSize=24, leading=28, textColor=NAVY, spaceAfter=14),
    "h": ParagraphStyle("h", fontName="GuideBold", fontSize=12, leading=16, textColor=NAVY, spaceBefore=12, spaceAfter=5),
    "body": ParagraphStyle("body", fontName="Guide", fontSize=10.4, leading=15, textColor=GRAY, spaceAfter=7),
    "small": ParagraphStyle("small", fontName="Guide", fontSize=9, leading=13, textColor=GRAY, spaceAfter=5),
    "code": ParagraphStyle("code", fontName="GuideMono", fontSize=8.3, leading=11.7, textColor=NAVY, alignment=TA_LEFT),
}
story = []


def p(text, kind="body"):
    story.append(Paragraph(text, styles[kind]))


def title(number, name, subtitle):
    p(f"{number:02d} / PROCEDURA OPERATIVA", "small")
    p(name, "title")
    p(subtitle)


def section(name, text):
    story.append(KeepTogether([Paragraph(name, styles["h"]), Paragraph(text, styles["body"])]))


def code(text):
    lines = text.strip().splitlines()
    assert all(len(line) <= 98 for line in lines), "Wrap long command lines explicitly"
    block = Paragraph("<br/>".join(escape(line).replace(" ", "&#160;") for line in lines), styles["code"])
    table = Table([[block]], colWidths=[WIDTH])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PALE),
        ("BOX", (0, 0), (-1, -1), .4, colors.HexColor("#CBD5E1")),
        ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    story.extend([table, Spacer(1, 8)])


def callout(text):
    table = Table([[Paragraph(text, styles["body"])]], colWidths=[WIDTH])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#FFF4E8")),
        ("LINEBEFORE", (0, 0), (0, 0), 3, ORANGE),
        ("LEFTPADDING", (0, 0), (-1, -1), 12), ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.extend([table, Spacer(1, 6)])


title(1, "Deploy e controllo<br/>del qcluster", "NOVICROM HUB · Edizione 1 ottobre 2026 · Guida per l’operatore")
p("Obiettivo: distribuire la release, avviare un solo worker e attivare un controllo esterno capace di segnalare arresti anche a coda vuota.")
section("Percorso consigliato", "Prima collauda in <b>TEST</b>, poi ripeti in <b>PROD</b>. Apri PowerShell come amministratore sul server. Il menu mostra sempre ambiente e radice: controllali prima di confermare.")
code(r'''
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\deployment\scripts\qcluster-console.ps1 `
  -Environment test -PortaleRoot C:\PortaleNovicrom
''')
p("Per PROD cambia soltanto <b>-Environment prod</b>. Puoi avviare lo script da una copia del nuovo pacchetto: prima del deploy la vecchia release potrebbe non contenerlo.")
section("Tre momenti, in quest’ordine", "<b>Menu 2</b> — Preparazione: backup launcher/task, pausa e arresto.<br/><b>Wizard abituale</b> — Distribuisci e attiva il nuovo pacchetto, mantenendo la finestra di manutenzione.<br/><b>Menu 9</b> — Completamento: configurazione, launcher, watchdog e riavvio verificato.")
callout("<b>La console non distribuisce lo ZIP, non esegue il backup SQL e non gestisce la manutenzione IIS.</b> Queste operazioni restano nella procedura aziendale. Non dichiara concluso un passo che fallisce.")
section("Se devi anche recuperare la vecchia coda", "Dopo il deploy usa <b>3 → 7 → 8 → 4 → 5 → 6</b>, verificando l’anteprima prima dell’opzione 8. Il recupero non fa parte del percorso automatico 9. Dettagli a pagina 5.")
p("File da conservare insieme: questa guida, il runbook docs/QCLUSTER_WATCHDOG.md e lo script qcluster-console.ps1. Codice del watchdog introdotto con cdf002fe; usare una release che lo includa insieme alla console.", "small")
story.append(PageBreak())

title(2, "Prima del deploy", "La preparazione si esegue mentre il pacchetto è già pronto, ma prima di sostituire la release attiva.")
section("1. Pacchetto e finestra operativa", "Produci il pacchetto dal commit di <b>release/prod</b> previsto, con i normali controlli. Non riutilizzare ZIP vecchi e non forzare il packaging di una cartella sporca. Concorda la finestra di manutenzione e impedisci nuove operazioni del portale.")
section("2. Backup SQL e task legacy", "Completa il backup SQL aziendale e annotane il riferimento nel registro di rilascio. Individua e ferma/disabilita gli eventuali task legacy process_automation_queue e process_approval_mailbox, oltre agli avvii manuali. Non chiudere indiscriminatamente tutti i processi Python.")
section("3. Menu 1: verifica destinazione", "Controlla ambiente, account, stato del worker e percorso del launcher. Il task deve essere <b>\\PortaleNovicrom\\QCluster_TEST</b> o <b>QCluster_PROD</b>, con una sola azione PowerShell che avvia start_qcluster.ps1. Se il controllo salute fallisce prima della prima installazione delle migrazioni, non significa che la console abbia modificato qualcosa.")
section("4. Menu 2: prepara", "La console richiede di digitare TEST o PROD. Copia launcher e definizione XML del task in <b>ENV/logs/qcluster-deploy-backups/data_ora</b>, imposta due ore di manutenzione watchdog, disabilita/ferma il worker e verifica i processi residui. Solo dopo questi passaggi mostra Preparato=True.")
callout("Se restano processi del worker o non è possibile identificarli, la preparazione si interrompe. Verificali manualmente e ripeti il punto 2 del menu. La console non termina automaticamente processi aziendali.")
section("5. Distribuisci con il wizard abituale", "Lascia aperta la console. Distribuisci e <b>attiva</b> il pacchetto: deve diventare la nuova directory current. Non saltare migrate/collectstatic e mantieni il portale in manutenzione fino alle verifiche finali.")
section("6. Ricontrolla i legacy dopo il deploy", "Lo script di deploy esistente può registrare nuovamente il poller legacy. Verifica che sia ancora disabilitato e che non stia elaborando eventi prima di proseguire con le operazioni sui dati. Non avviare ancora il qcluster.")
story.append(PageBreak())

title(3, "Dopo il deploy", "Percorso ordinario: scegli 9. Per controllare separatamente ciascuna fase usa 3, 4, 5 e 6.")
section("Menu 3 · Configurazione e controlli", "La console verifica la presenza della nuova release con il watchdog, rinnova la pausa, esegue migrate su tutti i moduli, applica i trigger, installa/aggiorna pianificazioni e flussi gestiti, esegue check e controlla che non restino migrazioni pendenti. Ogni comando deve terminare correttamente.")
code(r'''
# Equivalente manuale, da ENV\current\django_app
$portalPython = "C:\PortaleNovicrom\prod\venv\Scripts\python.exe"
& $portalPython manage.py migrate --settings=config.settings.prod
& $portalPython manage.py apply_sql_triggers --settings=config.settings.prod
& $portalPython manage.py setup_q_schedules --settings=config.settings.prod
& $portalPython manage.py check --settings=config.settings.prod
& $portalPython manage.py migrate --check --settings=config.settings.prod
''')
callout("<b>Controlla $LASTEXITCODE dopo ogni comando manuale e fermati se è diverso da 0.</b> Anche nell’ambiente TEST distribuito si usa config.settings.prod. config.settings.test è riservato ai test automatici SQLite.")
section("Migrazione da trovare", "In showmigrations automazioni deve risultare applicata <b>[X] 0027_clusterheartbeat_clusterwatchdogstate</b>. Usa migrate completo, perché la release può includere anche altre migrazioni.")
section("Menu 4 · Launcher effettivo", "La console ricava il percorso dall’azione del task, ne crea un backup, copia il nuovo start_qcluster.ps1 dalla release attiva e confronta gli hash. Aggiornare solo il file dentro current non basta se il task usa una copia in shared/scripts.")
section("Identità della release", "Se current cambia dopo la verifica, la console impedisce di proseguire: ripeti l’opzione 3. Le verifiche appartengono alla sessione del menu; se chiudi e riapri, riparti dalla preparazione. Nessun riavvio è implicito all’uscita.")
story.append(PageBreak())

title(4, "Attiva la sorveglianza", "Verifica i destinatari email prima dell’installazione: il watchdog usa il trasporto del portale, fuori dal qcluster.")
section("Menu 5 · Installa il watchdog", "Registra il task indipendente <b>QClusterWatchdog_TEST/PROD</b> con l’account del worker. Se il tipo di accesso è Password, richiede la credenziale dello stesso account senza salvarla nei file. L’account deve lavorare anche dopo il logout; i principal interattivi non sono accettati.")
p("Gli amministratori destinatari seguono la configurazione esistente: <b>MONITORING_ADMIN_EMAILS → ADMINS → superuser</b>. MONITORING_NOTIFY_CRITICAL_BY_EMAIL non deve disabilitare gli avvisi. S4U può limitare l’accesso alla rete: verificare DB e trasporto email con l’identità reale.")
code(r'''
# Installazione manuale dalla directory della nuova release
.\deployment\scripts\install-qcluster-watchdog.ps1 `
  -Environment prod -PortaleRoot C:\PortaleNovicrom
# Se il task usa Password, aggiungi: -Credential (Get-Credential)
''')
section("Menu 6 · Avvio e verifica", "Riabilita/avvia un solo worker e controlla la salute con tre sonde, ciascuna limitata a 20 secondi, intervallate da 10 secondi. Dopo il controllo toglie la pausa e richiede l’esecuzione del watchdog. Se la salute resta negativa, mostra errore e riattiva comunque la sorveglianza: non riaprire ancora il portale.")
code(r'''
# Controllo manuale in sola lettura, da ENV\current\django_app
& $portalPython manage.py automation_health --settings=config.settings.prod
''')
p("Esito atteso: <b>worker_alive=true</b>, <b>unhealthy=false</b>, <b>reason=ok</b>. Dopo uno o due minuti anche watchdog_stale deve essere false. Un health check sano non invia da solo una email di prova.")
section("Tempi e comportamento", "Heartbeat ogni 15 secondi; allarme dopo 120 secondi senza worker. Coda non vuota senza completamenti da dieci minuti: allarme. Il watchdog controlla ogni minuto, tollera tre minuti all’avvio e tenta al massimo tre riavvii in mezz’ora, solo senza processi residui. Il suo task può risultare Ready tra un controllo e l’altro.")
story.append(PageBreak())

title(5, "Recupero straordinario", "Solo se l’unione dei flussi Assenze e il recupero della vecchia coda sono ancora da eseguire. Non ripeterli come rito a ogni deploy.")
callout("<b>Prerequisiti:</b> backup SQL completato, portale in manutenzione, qcluster e processori legacy realmente fermi, menu 3 concluso. Il flag --workers-stopped è una dichiarazione dell’operatore, non un rilevamento automatico.")
section("Menu 7 · Anteprima", "Mostra ciò che i due comandi propongono. Controlla gli esiti senza applicare modifiche. Se ci sono lock futuri, attendi la loro scadenza a worker fermi e ripeti l’anteprima. Non forzarli e non cancellare manualmente la coda.")
code(r'''
& $portalPython manage.py merge_assenze_flows --settings=config.settings.prod
& $portalPython manage.py recover_automation_broker --settings=config.settings.prod
''')
section("Menu 8 · Applica dopo verifica", "Richiede un’anteprima completata nella sessione e una conferma esplicita TEST/PROD. Applica prima l’unione Assenze, poi il recupero del broker. Se il primo comando fallisce, il secondo non parte. Conserva il batch del recupero nel registro del rilascio.")
code(r'''
& $portalPython manage.py merge_assenze_flows `
  --apply --workers-stopped --settings=config.settings.prod
& $portalPython manage.py recover_automation_broker `
  --apply --workers-stopped --settings=config.settings.prod
''')
section("Cosa viene conservato", "Le regole Assenze originali restano conservate e vengono disattivate; le approvazioni già inviate mantengono i propri snapshot. Il recupero archivia i pacchetti modificati nella stessa transazione e preserva quelli manuali/sconosciuti secondo le regole del comando.")
section("Come proseguire", "Dopo il recupero usa <b>4 → 5 → 6</b>. Verifica nel designer che sia attivo il solo flusso Assenze previsto, che pianificazioni/disattivazioni personalizzate siano conservate e che lo storico riprenda ad avanzare.")
p("Non reinserire indiscriminatamente pacchetti archiviati: potresti ripetere email e operazioni già completate. Il controllo heartbeat non garantisce l’esecuzione esattamente una volta di ogni effetto esterno.", "small")
story.append(PageBreak())

title(6, "Verifiche finali e problemi", "Il deploy è concluso quando il servizio funziona e gli avvisi sono stati collaudati, non quando il task accetta il comando di avvio.")
section("Checklist prima della riapertura", "1. Worker sano, ultimo heartbeat recente.<br/>2. Watchdog con controllo recente, senza banner di sorveglianza inattiva.<br/>3. Completamenti che avanzano e coda in diminuzione, se presente.<br/>4. Nessun doppio launcher; task legacy nello stato previsto.<br/>5. Migrazioni completate e release corretta.<br/>6. Allarme e ripristino email ricevuti durante un collaudo in TEST.")
section("Prova del guasto in TEST", "Con il sistema stabile, ferma il task worker senza disabilitarlo e senza pausa manutenzione. Verifica allarme, tentativo di riavvio e ripristino. Se rimangono processi residui, il watchdog deve segnalarli e non creare duplicati. Verifica inoltre funzionamento dopo logout e riavvio Windows.")
section("Dove guardare", "<b>ENV/logs/qcluster.log</b> e file stdout/stderr: avvio worker.<br/><b>ENV/logs/qcluster-watchdog.log</b>: controlli esterni.<br/><b>Event Viewer → Applicazione → NovicromQCluster</b>: 4101 allarme, 4102 richiesta riavvio, 4103 manutenzione/configurazione, 4104 errore controllo/email, 4105 ripristino notificato.")
section("Deploy successivi", "Ripeti menu 2 → wizard → menu 9. Il backup SQL resta manuale. Riesegui l’installer quando cambia il watchdog. Prima di un arresto volontario sospendi sempre il controllo, altrimenti può riavviare il task.")
code(r'''
C:\PortaleNovicrom\shared\scripts\watch_qcluster.ps1 `
  -Environment prod -MaintenanceMinutes 60
# Al termine della manutenzione:
C:\PortaleNovicrom\shared\scripts\watch_qcluster.ps1 `
  -Environment prod -Resume
''')
section("Se qualcosa fallisce", "Non proseguire alla cieca e non riaprire il portale. La console non annulla migrazioni o azioni già completate. Per il rollback arresta i produttori/consumatori, sospendi il watchdog e usa la procedura di ripristino coordinata tra codice, launcher e SQL. Non è sufficiente cambiare cartella release dopo una conversione di dati.")
callout("<b>Limite da conoscere:</b> se il server o Task Scheduler si fermano del tutto, serve un monitor su un’altra macchina. Se DB o SMTP non sono disponibili, resta il canale locale Event Log; la consegna email non è garantita.")


def chrome(canvas, doc):
    canvas.saveState()
    w, h = A4
    canvas.setFillColor(NAVY)
    canvas.setFont("GuideBold", 9)
    canvas.drawString(46, h - 31, "NOVICROM HUB")
    canvas.setFont("Guide", 8)
    canvas.drawRightString(w - 46, h - 31, "OPERAZIONI / QCLUSTER")
    canvas.setStrokeColor(ORANGE)
    canvas.setLineWidth(2)
    canvas.line(46, h - 40, w - 46, h - 40)
    canvas.setFillColor(GRAY)
    canvas.setFont("Guide", 8)
    canvas.drawString(46, 27, "1 ottobre 2026 · TEST prima di PROD · Nessun dato aziendale incluso")
    canvas.drawRightString(w - 46, 27, f"{doc.page} / 6")
    canvas.restoreState()


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(str(OUT), pagesize=A4, leftMargin=46, rightMargin=46,
                                 topMargin=60, bottomMargin=48, title="NOVICROM HUB - Deploy e controllo qcluster",
                                 author="NOVICROM HUB", pageCompression=1)
    document.build(story, onFirstPage=chrome, onLaterPages=chrome)
    print(OUT)
