"""Genera la documentazione delle automazioni schedulate dalla fonte unica.

Legge ``automazioni.schedules.SCHEDULES`` (struttura) + i commenti che precedono
ogni voce (spiegazione) e produce:
  - ``docs/AUTOMAZIONI.md`` (sempre)
  - ``docs/AUTOMAZIONI.pdf`` (con ``--pdf``, richiede reportlab)

Il documento è **auto-generato**: si rigenera identico a ogni aggiunta di
un'automazione, quindi NON va modificato a mano. Viene rilanciato in automatico
da ``setup_q_schedules`` a ogni deploy.

Uso:
    python manage.py genera_doc_automazioni            # scrive AUTOMAZIONI.md
    python manage.py genera_doc_automazioni --pdf       # anche il PDF
    python manage.py genera_doc_automazioni --check      # verifica che il .md sia allineato (CI)
"""
from __future__ import annotations

import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

# Etichetta leggibile per modulo (prefisso di func) → categoria nel documento.
_CATEGORIE = {
    "anagrafica": "Anagrafica · HR, Formazione e Visite",
    "assets": "Assets · Manutenzione",
    "dpi": "DPI · Sicurezza",
    "rentri": "RENTRI · Ambiente",
    "tickets": "Ticket · Assistenza/Manutenzione",
    "anomalie": "Anomalie qualità",
    "gestione_specifiche": "Gestione Specifiche",
    "procedure_refresh": "Procedure · SGI",
    "monitoring": "Monitoraggio sistema",
    "ai_assistant": "Assistente AI",
    "tasks": "KICK-OFF · Attività",
    "core": "Trasversale (Core)",
    "automazioni": "Motore automazioni",
}
_ORDINE_CATEGORIE = list(_CATEGORIE.values())

_GIORNI = {"0": "dom", "1": "lun", "2": "mar", "3": "mer", "4": "gio", "5": "ven", "6": "sab", "7": "dom"}
_MESI = {"1": "gen", "2": "feb", "3": "mar", "4": "apr", "5": "mag", "6": "giu",
         "7": "lug", "8": "ago", "9": "set", "10": "ott", "11": "nov", "12": "dic"}


def _descr_cron(cron: str) -> str:
    """Traduce un'espressione cron a 5 campi in una frase leggibile (con fallback)."""
    parts = str(cron or "").split()
    if len(parts) != 5:
        return f"cron `{cron}`"
    minute, hour, dom, month, dow = parts
    # orario
    if hour == "*" and minute == "*":
        quando = "in continuazione"
    elif hour == "*":
        quando = f"ogni ora al minuto {minute}"
    else:
        try:
            quando = f"alle {int(hour):02d}:{int(minute):02d}"
        except ValueError:
            quando = f"({minute} {hour})"
    # frequenza
    freq = "ogni giorno"
    if dow != "*":
        if "-" in dow:
            a, b = dow.split("-", 1)
            freq = f"da {_GIORNI.get(a, a)} a {_GIORNI.get(b, b)}"
        else:
            giorni = ", ".join(_GIORNI.get(g, g) for g in dow.split(","))
            freq = f"ogni {giorni}"
    elif dom != "*":
        mesi = ""
        if month != "*":
            mesi = " di " + "/".join(_MESI.get(m, m) for m in month.split(","))
        freq = f"il giorno {dom}{mesi} del mese"
    elif month != "*":
        freq = "nei mesi " + "/".join(_MESI.get(m, m) for m in month.split(","))
    return f"{freq}, {quando}"


def _descr_cadenza(spec: dict) -> str:
    if spec.get("schedule_type") == "C":
        return _descr_cron(spec.get("cron", ""))
    minutes = spec.get("minutes")
    if minutes == 1:
        return "ogni minuto"
    return f"ogni {minutes} minuti"


def _categoria(func: str) -> str:
    modulo = str(func or "").split(".", 1)[0]
    return _CATEGORIE.get(modulo, "Altro")


def _estrai_commenti(source_path: Path) -> dict[str, str]:
    """Mappa nome-schedule → blocco commento che lo precede in schedules.py.

    I commenti stanno tra ``{`` (apertura dict) e la riga ``"name":``. Restituisce il
    testo unito su una riga (frase), pulito dai prefissi ``#``.
    """
    commenti: dict[str, str] = {}
    buffer: list[str] = []
    try:
        righe = source_path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return commenti
    for riga in righe:
        s = riga.strip()
        if s.startswith("{"):
            buffer = []
        elif s.startswith("#"):
            buffer.append(s.lstrip("#").strip())
        else:
            m = re.match(r'"name"\s*:\s*"([^"]+)"', s)
            if m:
                nome = m.group(1)
                if buffer:
                    commenti[nome] = " ".join(x for x in buffer if x)
                buffer = []
    return commenti


def _build_markdown(schedules: list[dict], commenti: dict[str, str]) -> str:
    per_cat: dict[str, list[dict]] = {}
    for spec in schedules:
        per_cat.setdefault(_categoria(spec.get("func", "")), []).append(spec)

    out: list[str] = []
    out.append("# Automazioni schedulate — NOVICROM HUB")
    out.append("")
    out.append("> ⚙️ **Documento auto-generato** da `python manage.py genera_doc_automazioni`.")
    out.append("> Fonte unica: `django_app/automazioni/schedules.py`. **Non modificare a mano**:")
    out.append("> si rigenera identico a ogni aggiunta di un'automazione (e a ogni deploy via `setup_q_schedules`).")
    out.append("")
    out.append(f"**Totale automazioni attive:** {len(schedules)}")
    out.append("")
    out.append("Ogni automazione è un task periodico gestito da django-q2 e può essere "
               "**disattivata** dalla Centrale di comando (Monitoring → ScheduleControl) "
               "senza toccare il codice.")
    out.append("")
    out.append("---")
    out.append("")

    categorie_ordinate = [c for c in _ORDINE_CATEGORIE if c in per_cat]
    categorie_ordinate += [c for c in sorted(per_cat) if c not in _ORDINE_CATEGORIE]

    for cat in categorie_ordinate:
        out.append(f"## {cat}")
        out.append("")
        for spec in sorted(per_cat[cat], key=lambda s: s.get("name", "")):
            nome = spec.get("name", "")
            out.append(f"### `{nome}`")
            out.append("")
            out.append(f"- **Quando gira:** {_descr_cadenza(spec)}")
            out.append(f"- **Task eseguito:** `{spec.get('func', '')}`")
            descr = commenti.get(nome)
            if descr:
                out.append(f"- **Cosa fa:** {descr}")
            out.append("")
    out.append("---")
    out.append("")
    out.append("_Legenda cadenza_: le frasi «alle HH:MM / ogni N minuti» derivano "
               "dall'espressione di schedulazione; l'orario è quello del server.")
    out.append("")
    return "\n".join(out)


def _write_pdf(md_text: str, pdf_path: Path) -> None:
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=styles["Heading1"], textColor="#002b5c", fontSize=18)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor="#ff6b00", fontSize=13, spaceBefore=10)
    h3 = ParagraphStyle("h3", parent=styles["Heading3"], fontSize=11)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=9.5, alignment=TA_LEFT, leading=13)

    def esc(t: str) -> str:
        return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def inline(t: str) -> str:
        # `code` → font monospace; **bold** → <b>
        t = re.sub(r"`([^`]+)`", r'<font face="Courier">\1</font>', t)
        t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
        return t

    flow = []
    for raw in md_text.splitlines():
        line = raw.rstrip()
        if not line or line == "---" or line.startswith(">"):
            if line.startswith(">"):
                flow.append(Paragraph("<i>" + inline(esc(line.lstrip("> ").strip())) + "</i>", body))
            else:
                flow.append(Spacer(1, 4))
            continue
        if line.startswith("### "):
            flow.append(Paragraph(inline(esc(line[4:])), h3))
        elif line.startswith("## "):
            flow.append(Paragraph(inline(esc(line[3:])), h2))
        elif line.startswith("# "):
            flow.append(Paragraph(inline(esc(line[2:])), h1))
        elif line.startswith("- "):
            flow.append(Paragraph("• " + inline(esc(line[2:])), body))
        else:
            flow.append(Paragraph(inline(esc(line)), body))

    doc = SimpleDocTemplate(
        str(pdf_path), pagesize=A4,
        leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
        title="Automazioni NOVICROM HUB",
    )
    doc.build(flow)


class Command(BaseCommand):
    help = "Genera docs/AUTOMAZIONI.md (e opzionalmente .pdf) dalla fonte unica SCHEDULES."

    def add_arguments(self, parser):
        parser.add_argument("--pdf", action="store_true", help="Genera anche docs/AUTOMAZIONI.pdf.")
        parser.add_argument("--check", action="store_true",
                            help="Non scrive: esce con errore se il .md su disco è disallineato.")

    def handle(self, *args, **options):
        from automazioni import schedules as sched_mod
        from automazioni.schedules import SCHEDULES

        source_path = Path(sched_mod.__file__)
        # docs/ nella root del repo (…/django_app/automazioni/… → risalgo di 3)
        repo_root = source_path.resolve().parents[2]
        docs_dir = repo_root / "docs"
        docs_dir.mkdir(exist_ok=True)
        md_path = docs_dir / "AUTOMAZIONI.md"

        commenti = _estrai_commenti(source_path)
        md_text = _build_markdown(list(SCHEDULES), commenti)

        if options.get("check"):
            attuale = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
            if attuale.strip() != md_text.strip():
                raise CommandError(
                    "docs/AUTOMAZIONI.md è disallineato da schedules.py. "
                    "Rigenera con: python manage.py genera_doc_automazioni"
                )
            self.stdout.write(self.style.SUCCESS("AUTOMAZIONI.md allineato."))
            return

        md_path.write_text(md_text, encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Scritto {md_path} ({len(SCHEDULES)} automazioni)."))

        if options.get("pdf"):
            pdf_path = docs_dir / "AUTOMAZIONI.pdf"
            try:
                _write_pdf(md_text, pdf_path)
                self.stdout.write(self.style.SUCCESS(f"Scritto {pdf_path}."))
            except Exception as exc:  # pragma: no cover - dipende da reportlab
                raise CommandError(f"Generazione PDF fallita: {exc}")
