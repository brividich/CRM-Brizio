"""PDF del Security Center: report periodico, scheda incidente, registro incidenti.

Grafica dal branding HUB (``core.pdf``). I font standard di reportlab (Helvetica) non
hanno frecce, spunte e simboli matematici: escono come quadratini neri. Ogni testo passa
da ``_txt`` che li sostituisce.
"""
from __future__ import annotations

import io
from html import escape

from django.utils import timezone
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, Spacer

from core.pdf import PdfTheme, build_styles, data_table, header_footer_callback, make_document, section_heading

_GLYPHS = {"→": "->", "←": "<-", "✓": "si", "✗": "no", "≤": "<=", "≥": ">=", "…": "...", "•": "-"}


def _txt(value) -> str:
    text = "" if value is None else str(value)
    for glyph, plain in _GLYPHS.items():
        text = text.replace(glyph, plain)
    return escape(text).replace("\n", "<br/>")


_BACKUP_STATUS = {"failed": "Fallito", "warning": "Con avvisi", "completed": "Completato"}


def _sev(value):
    from security.services.periodic_report import SEVERITY_LABELS

    return SEVERITY_LABELS.get(value, value)


def _num(value, decimals=1):
    """Decimali con la virgola, come nel resto del portale."""
    return f"{value:.{decimals}f}".replace(".", ",")


def _dt(value, fmt="%d/%m/%Y %H:%M"):
    if not value:
        return "-"
    if hasattr(value, "tzinfo") and timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.strftime(fmt)


class _Doc:
    def __init__(self, title, subtitle="", landscape=False):
        self.theme = PdfTheme.from_branding()
        self.styles = build_styles(self.theme)
        self.buffer = io.BytesIO()
        self.doc = make_document(self.buffer, title=title, landscape=landscape)
        self.title, self.subtitle = title, subtitle
        self.elements: list = []
        self.width = self.doc.pagesize[0] - self.doc.leftMargin - self.doc.rightMargin

    def section(self, text):
        self.elements += section_heading(_txt(text), self.theme, self.styles)

    def para(self, text, style="body"):
        self.elements.append(Paragraph(_txt(text), self.styles[style]))

    def space(self, height=3):
        self.elements.append(Spacer(1, height * mm))

    def table(self, headers, rows, widths=None, empty="Nessun dato nel periodo."):
        if not rows:
            self.para(empty)
            return
        cells = [[Paragraph(_txt(h), self.styles["table_header"]) for h in headers]]
        cells += [[Paragraph(_txt(value), self.styles["cell"]) for value in row] for row in rows]
        if widths:
            total = sum(widths)
            widths = [self.width * w / total for w in widths]
        self.elements.append(data_table(cells, self.theme, col_widths=widths, repeat_rows=1,
                                        extra_style=[("VALIGN", (0, 0), (-1, -1), "TOP")]))
        self.space()

    def facts(self, pairs, columns=2):
        """Coppie etichetta/valore in griglia."""
        rows, row = [], []
        for label, value in pairs:
            row += [Paragraph(_txt(label), self.styles["label"]), Paragraph(_txt(value), self.styles["body"])]
            if len(row) == columns * 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row + [""] * (columns * 2 - len(row)))
        if rows:
            unit = self.width / (columns * 5)
            widths = [unit * 2, unit * 3] * columns
            self.elements.append(data_table(rows, self.theme, col_widths=widths, header=False,
                                            extra_style=[("VALIGN", (0, 0), (-1, -1), "TOP")]))
            self.space()

    def build(self):
        callback = header_footer_callback(self.theme, title=self.title, subtitle=self.subtitle)
        self.doc.build(self.elements or [Paragraph("Nessun contenuto.", self.styles["body"])],
                       onFirstPage=callback, onLaterPages=callback)
        return self.buffer.getvalue()


def _sev_list(items):
    return ", ".join(f"{item['label']} {item['count']}" for item in items) or "nessuno"


def render_period_report_pdf(report) -> bytes:
    pdf = _Doc("Report Security Center", f"Periodo: {report['label']}")
    a, b, v, vpn, t, inc, ing = (report[k] for k in ("alerts", "backup", "vulnerabilities", "vpn", "tickets", "incidents", "ingestion"))

    pdf.section("Sintesi")
    pdf.facts([
        ("Periodo", f"{report['start']:%d/%m/%Y} - {report['end']:%d/%m/%Y} ({report['days']} giorni)"),
        ("Generato il", _dt(report["generated_at"])),
        ("Alert creati", f"{a['created']} ({_sev_list(a['by_severity'])})"),
        ("Alert ancora aperti", a["open_now"]),
        ("Backup riusciti", f"{_num(b['success_rate'])}%" if b["success_rate"] is not None else "nessun job"),
        ("Incidenti registrati", f"{inc['total']} (significativi NIS2: {inc['significant']})"),
        ("CVE aperte con dispositivi esposti", v["open_now"]),
        ("Report elaborati", f"{ing['reports']} (in errore: {ing['failed']})"),
    ])

    pdf.section("Postura attuale")
    pdf.para("Indici calcolati al momento della generazione del report (0-100).", "label")
    pdf.table(["Area", "Indice", "Giudizio", "Come è calcolato"],
              [[p["label"], p["score"] if p["score"] is not None else "n.d.", p["grade"], p["detail"]] for p in report["posture"]],
              widths=[2, 1, 1.4, 8])

    pdf.section("Alert")
    pdf.facts([
        ("Creati nel periodo", a["created"]),
        ("Chiusi nel periodo", a["closed"]),
        ("Tempo medio di chiusura", f"{_num(a['mean_hours_to_close'])} ore" if a["mean_hours_to_close"] is not None else "-"),
        ("Per gravità", _sev_list(a["by_severity"])),
    ])
    pdf.table(["Alert più frequenti", "Volte"], [[row["title"], row["count"]] for row in a["top_titles"]], widths=[8, 1])

    pdf.section("Backup")
    pdf.facts([
        ("Job nel periodo", b["total"]),
        ("Completati", b["completed"]),
        ("Con avvisi", b["warning"]),
        ("Falliti", b["failed"]),
    ])
    pdf.table(["Job", "Dispositivo", "Esito", "Quando"],
              [[p["job"], p["device"] or "-", _BACKUP_STATUS.get(p["status"], p["status"]), _dt(p["when"])] for p in b["problems"]],
              widths=[4, 3, 1.5, 2], empty="Nessun job fallito o con avvisi.")

    pdf.section("Vulnerabilità")
    pdf.facts([
        ("CVE aperte con dispositivi esposti", f"{v['open_now']} ({_sev_list(v['open_by_severity'])})"),
        ("Nuove nel periodo", v["new_in_period"]),
    ])
    pdf.table(["CVE", "Prodotto", "CVSS", "Dispositivi"],
              [[f["cve"], f["product"], _num(f["cvss"]), f["devices"]] for f in v["top"]],
              widths=[2, 5, 1, 1.3], empty="Nessuna CVE critica o alta aperta.")

    pdf.section("Accessi VPN")
    pdf.facts([
        ("Accessi consentiti", vpn["allowed"]),
        ("Tentativi negati", vpn["denied"]),
        ("Utenti distinti", vpn["distinct_users"]),
    ])

    pdf.section("Ticket e incidenti")
    pdf.facts([
        ("Ticket aperti nel periodo", t["opened"]),
        ("Ticket chiusi nel periodo", t["closed"]),
        ("Ticket ancora aperti", t["open_now"]),
        ("Incidenti con dati personali", inc["personal_data"]),
    ])
    pdf.table(["Codice", "Incidente", "Rilevato", "Stato", "NIS2", "Scadenze mancate"],
              [[r["code"], r["title"], _dt(r["detected_at"]), r["status"], "sì" if r["significant"] else "no", r["late"]] for r in inc["rows"]],
              widths=[1.6, 5, 2, 1.4, 0.8, 1.4], empty="Nessun incidente registrato nel periodo.")

    pdf.section("Elaborazione dei report")
    pdf.table(["Sorgente", "Report"], [[row["source"], row["count"]] for row in ing["by_source"]], widths=[6, 1])
    return pdf.build()


def _deadline_rows(incident):
    from security.services.incidents import deadlines

    return [[d["label"], _dt(d["due_at"]), _dt(d["done_at"]), d["state_label"]] for d in deadlines(incident)]


def render_incident_pdf(incident) -> bytes:
    from security.services.incidents import SIGNIFICANCE_LABELS

    pdf = _Doc(f"Incidente {incident.code}", incident.title[:90])
    pdf.section("Identificazione")
    pdf.facts([
        ("Codice", incident.code),
        ("Stato", incident.get_status_display()),
        ("Categoria", incident.get_category_display()),
        ("Gravità", _sev(incident.severity)),
        ("Rilevato il (conoscenza)", _dt(incident.detected_at)),
        ("Avvenuto il", _dt(incident.occurred_at)),
        ("Risolto il", _dt(incident.resolved_at)),
        ("Responsabile", (incident.owner.get_full_name() or incident.owner.username) if incident.owner else "-"),
    ])
    if incident.description:
        pdf.para(incident.description)
        pdf.space()

    pdf.section("Valutazione NIS2 / GDPR")
    pdf.facts([
        ("Incidente significativo NIS2", "sì" if incident.is_significant else "no"),
        ("Coinvolge dati personali", "sì" if incident.personal_data_breach else "no"),
        ("Sospetto atto illecito o malevolo", "sì" if incident.suspected_malicious else "no"),
        ("Impatto transfrontaliero", "sì" if incident.cross_border else "no"),
        ("Valutato il", _dt(incident.significance_assessed_at)),
        ("Riferimento CSIRT", incident.csirt_reference or "-"),
    ])
    for code in incident.significance_criteria or []:
        pdf.para(f"- {SIGNIFICANCE_LABELS.get(code, code)}")
    pdf.table(["Notifica", "Scadenza", "Inviata il", "Esito"], _deadline_rows(incident), widths=[3, 2, 2, 2],
              empty="Nessuna notifica dovuta (incidente non significativo e senza dati personali).")

    pdf.section("Impatto e gestione")
    for label, value in (
        ("Servizi coinvolti", incident.affected_services),
        ("Utenti coinvolti", incident.affected_users_count),
        ("Impatto", incident.impact_description),
        ("Causa", incident.root_cause),
        ("Misure adottate", incident.actions_taken),
        ("Lezioni apprese", incident.lessons_learned),
    ):
        pdf.para(label, "label")
        pdf.para(value if value not in (None, "") else "-")
        pdf.space(2)

    tickets = list(incident.tickets.order_by("created_at"))
    if tickets:
        pdf.section("Ticket collegati")
        pdf.table(["#", "Ticket", "Stato", "Aperto il"],
                  [[f"#{t.pk}", t.title, t.status, _dt(t.created_at)] for t in tickets], widths=[0.8, 6, 1.5, 2])

    pdf.section("Traccia")
    pdf.table(["Quando", "Chi", "Cosa"],
              [[_dt(entry.created_at), entry.actor, entry.body] for entry in incident.logs.order_by("created_at")],
              widths=[2, 1.6, 8], empty="Nessuna voce.")
    return pdf.build()


def render_incident_register_pdf(incidents, label) -> bytes:
    from security.services.incidents import deadlines

    pdf = _Doc("Registro incidenti di sicurezza", f"Anno: {label}" if label != "completo" else "Registro completo", landscape=True)
    rows = []
    for incident in incidents:
        late = sum(1 for d in deadlines(incident) if d["state"] in {"late", "overdue"})
        notified = ", ".join(
            name for name, value in (
                ("pre-notifica", incident.early_warning_at),
                ("notifica", incident.notification_at),
                ("relazione", incident.final_report_at),
                ("Garante", incident.gdpr_notified_at),
            ) if value
        )
        rows.append([
            incident.code, _dt(incident.detected_at), incident.title, incident.get_category_display(),
            _sev(incident.severity), incident.get_status_display(),
            "sì" if incident.is_significant else "no", "sì" if incident.personal_data_breach else "no",
            notified or "-", late or "-",
        ])
    pdf.table(["Codice", "Rilevato", "Incidente", "Categoria", "Gravità", "Stato", "NIS2", "Dati pers.", "Notifiche inviate", "In ritardo"],
              rows, widths=[2.1, 1.6, 4.2, 2.3, 1.2, 1.1, 0.7, 0.9, 2.4, 0.9], empty="Nessun incidente registrato.")
    return pdf.build()


# --- Pacchetto di evidenze ISO/IEC 27001 (services/iso_pacchetto.py) --------------------------

def _numero(value):
    if isinstance(value, bool):
        return "sì" if value else "no"
    if isinstance(value, float):
        return _num(value)
    if value is None:
        return "—"
    return value


def render_pacchetto_iso_pdf(dati) -> bytes:
    """«Evidenze SOC – ISO/IEC 27001 – <periodo>»: copertina, sintesi, un capitolo per controllo, allegati."""
    from security.services.iso27001 import ETICHETTA_STATO

    v = dati["valutazione"]
    c = v["conteggi"]
    pdf = _Doc("Evidenze SOC – ISO/IEC 27001", f"Periodo: {dati['etichetta']}")

    # Copertina
    pdf.elements.append(Spacer(1, 30 * mm))
    pdf.elements.append(Paragraph(_txt("Evidenze SOC – ISO/IEC 27001:2022"), pdf.styles["title"]))
    pdf.elements.append(Paragraph(_txt(f"Periodo: {dati['etichetta']}"), pdf.styles["subtitle"]))
    pdf.space(6)
    pdf.facts([
        ("Periodo", f"{dati['dal']:%d/%m/%Y} - {dati['al']:%d/%m/%Y}"),
        ("Generato il", _dt(dati["generato_il"])),
        ("Controlli verificati", c["totale"]),
        ("Conformi", c["ok"]),
        ("Da guardare", c["attenzione"]),
        ("Non conformi", c["non_conforme"]),
        ("Dato non disponibile", c["non_disponibile"]),
    ])
    pdf.para("Questo pacchetto è generato automaticamente dal Security Center del portale NOVICROM HUB dai dati che il SOC "
             "raccoglie da solo (letture automatiche, registro accessi, backup, vulnerabilità, incidenti). Ogni controllo riporta "
             "cosa si aspetta l'audit, l'esito calcolato, i numeri su cui si basa e le azioni aperte. Il PDF è conservato con la "
             "sua impronta SHA-256 nell'audit del portale: serve al riesame periodico (controlli 9.1 e 9.3).", "body")
    pdf.elements.append(PageBreak())

    pdf.section("Sintesi per controllo")
    pdf.table(["Controllo", "Titolo", "Esito", "In breve"],
              [[x["codice"], x["titolo"], ETICHETTA_STATO[x["stato"]], x["frase"]] for x in v["controlli"]],
              widths=[1, 3.2, 1.6, 6.5])

    for area in v["aree"]:
        pdf.section(area["nome"])
        for x in area["controlli"]:
            pdf.para(f"{x['codice']} · {x['titolo']} — {ETICHETTA_STATO[x['stato']]}", "section")
            pdf.para(f"Cosa si aspetta l'audit: {x['atteso']}", "label")
            pdf.para(x["frase"])
            if x["numeri_semplici"]:
                pdf.facts(x["numeri_semplici"], columns=3)
            for t in x["numeri_tabelle"]:
                pdf.para(t["titolo"], "label")
                pdf.table(t["colonne"], t["righe"])
            if x["azioni"]:
                pdf.para("Cosa fare:", "label")
                for a in x["azioni"]:
                    pdf.para(f"- {a}")
            pdf.space(2)

    pdf.elements.append(PageBreak())
    pdf.section("Allegato A · Vulnerabilità corrette nel periodo")
    pdf.para("Un PC per riga: la CVE non risulta più sul PC perché il programma è stato aggiornato o disinstallato "
             "(evidenza: l'inventario software del PC letto da WatchGuard o Defender).", "label")
    pdf.table(["CVE", "CVSS", "PC", "Programma", "Prima", "Dopo", "Evidenza", "Esposto dal", "Corretto il", "Giorni"],
              [[r["cve"] + (" KEV" if r["kev"] else ""), _num(r["cvss"]) if r["cvss"] is not None else "—", r["host"], r["software"],
                r["versione_prima"], r["versione_dopo"], r["evidenza"], r["aperta_dal"], r["risolta_il"], r["giorni"] if r["giorni"] is not None else "—"]
               for r in dati["correzioni"]],
              widths=[1.9, 0.8, 1.8, 2.4, 1.2, 1.2, 2.6, 1.3, 1.3, 0.8], empty="Nessuna correzione registrata nel periodo.")

    pdf.section("Allegato B · Esposizioni oltre il termine")
    if dati["esposizioni_scadute"] is None:
        pdf.para("Dato non disponibile: il servizio dei tempi di correzione per classe (cve_sla) non è installato in questa versione.")
    else:
        pdf.table(["CVE", "PC", "Classe", "Scadenza", "Giorni di ritardo", "Rischio accettato"],
                  [[e.get("cve"), e.get("host"), e.get("classe"), _numero(e.get("scadenza")), _numero(e.get("giorni_ritardo")),
                    "sì" if e.get("accettata") else "no"] for e in dati["esposizioni_scadute"]],
                  widths=[2, 2.5, 1.5, 1.8, 1.4, 1.4], empty="Nessuna esposizione oltre il termine.")

    pdf.section("Allegato C · Incidenti del periodo e lezioni apprese")
    pdf.table(["Codice", "Incidente", "Categoria", "Stato", "Rilevato", "Risolto", "NIS2", "Dati pers.", "Riesame", "Lezioni apprese"],
              [[i["codice"], i["titolo"], i["categoria"], i["stato"], i["rilevato_il"], i["risolto_il"], i["nis2"], i["dati_personali"],
                i["riesame"], i["lezioni"] or "—"] for i in dati["incidenti"]],
              widths=[1.6, 3.2, 2, 1.2, 1.6, 1.6, 0.7, 0.9, 1.4, 3.5], empty="Nessun incidente rilevato o chiuso nel periodo.")
    return pdf.build()
