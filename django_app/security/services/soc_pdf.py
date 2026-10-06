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
from reportlab.platypus import Paragraph, Spacer

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
