"""
Management command: check_rentri_scadenze

Controlla i record RENTRI non confermati o non inviati entro X giorni
e invia notifiche email agli amministratori.

Uso:
  python manage.py check_rentri_scadenze
  python manage.py check_rentri_scadenze --giorni 14
  python manage.py check_rentri_scadenze --email admin@example.com --dry-run

Destinatari: --email se indicato, altrimenti i referenti delle Impostazioni
RENTRI, altrimenti DEFAULT_FROM_EMAIL. La mail riporta anche i conteggi della
verifica di coerenza (``rentri.verifica``).
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from rentri.models import RegistroRifiuti

logger = logging.getLogger(__name__)


_TIPO_LABEL = {
    "C": "C - Carico",
    "O": "O - Scarico originale",
    "M": "M - Scarico effettivo",
    "R": "R - Rettifica scarico",
}

_TIPO_COLOR = {
    "C": "#2296D0",
    "O": "#E8996C",
    "M": "#86BA31",
    "R": "#FFD251",
}


class Command(BaseCommand):
    help = (
        "Verifica le registrazioni RENTRI non confermate o non inviate "
        "entro N giorni dalla creazione e invia un alert email."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--giorni",
            type=int,
            default=30,
            help="Soglia in giorni: segnala le registrazioni create più di N giorni fa e non completate. (default: 30)",
        )
        parser.add_argument(
            "--email",
            dest="email",
            default=None,
            help="Indirizzo email destinatario. Se omesso: referenti delle Impostazioni RENTRI, poi DEFAULT_FROM_EMAIL.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Stampa i record in scadenza senza inviare email.",
        )

    def handle(self, *args, **options):
        giorni: int = options["giorni"]
        dry_run: bool = options["dry_run"]
        destinatari = _destinatari(options["email"])

        soglia = timezone.now() - timedelta(days=giorni)

        # 1. Non salvate/confermate (salva=False) oltre la soglia
        non_salvate = list(
            RegistroRifiuti.objects.attivi().filter(
                salva=False,
                created_at__lt=soglia,
            ).order_by("-created_at")
        )

        # 2. Non inviate a RENTRI (rentri_si_no=False) ma confermate (salva=True) oltre la soglia
        non_inviate = list(
            RegistroRifiuti.objects.attivi().filter(
                salva=True,
                rentri_si_no=False,
                created_at__lt=soglia,
            ).order_by("-created_at")
        )

        from rentri.verifica import verifica_registro

        anomalie = [(s["label"], len(s["righe"])) for s in verifica_registro() if s["righe"]]
        totale = len(non_salvate) + len(non_inviate) + sum(n for _, n in anomalie)

        if totale == 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f"[check_rentri_scadenze] Nessuna anomalia trovata (soglia: {giorni} giorni)."
                )
            )
            return

        # Riepilogo a terminale
        self.stdout.write(
            self.style.WARNING(
                f"[check_rentri_scadenze] {totale} record in scadenza "
                f"(soglia: {giorni} giorni): "
                f"{len(non_salvate)} non salvate, {len(non_inviate)} non inviate a RENTRI."
            )
        )
        for r in non_salvate + non_inviate:
            self.stdout.write(
                f"  id={r.pk} tipo={r.tipo} data={r.data} "
                f"id_reg={r.id_registrazione} codice={r.codice} "
                f"salva={r.salva} rentri={r.rentri_si_no} "
                f"creato={r.created_at.strftime('%Y-%m-%d')}"
            )

        if dry_run:
            self.stdout.write("[dry-run] Email NON inviata.")
            return

        for label, n in anomalie:
            self.stdout.write(f"  Verifica · {label}: {n}")

        if not destinatari:
            self.stderr.write(
                "Nessun destinatario email configurato. "
                "Usa --email, indica i referenti nelle Impostazioni RENTRI o imposta DEFAULT_FROM_EMAIL."
            )
            return

        # Costruisci email HTML
        subject = f"[RENTRI] {totale} registrazioni in scadenza — soglia {giorni} giorni"
        body_text = _build_body_text(non_salvate, non_inviate, giorni, anomalie)
        body_html = _build_body_html(non_salvate, non_inviate, giorni, anomalie)

        try:
            from core.email_utils import render_hub_email_html
            wrapped_html = render_hub_email_html(
                body_html,
                email_type="RENTRI",
                section_label="Scadenze registrazioni",
            )
            from django.core.mail import EmailMultiAlternatives
            msg = EmailMultiAlternatives(
                subject=subject,
                body=body_text,
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", destinatari[0]),
                to=destinatari,
            )
            msg.attach_alternative(wrapped_html, "text/html")
            sent = msg.send(fail_silently=False)
            if sent:
                self.stdout.write(
                    self.style.SUCCESS(f"Email inviata a {', '.join(destinatari)} — {totale} segnalazioni.")
                )
            else:
                self.stderr.write("Email non inviata (send() ha restituito 0).")
        except Exception as exc:  # noqa: BLE001
            logger.exception("check_rentri_scadenze: errore invio email")
            self.stderr.write(f"Errore invio email: {exc}")


def _destinatari(email_opzione: str | None) -> list[str]:
    if email_opzione:
        return [email_opzione]
    from rentri.models import RentriImpostazioni

    cfg = RentriImpostazioni.get_singleton()
    email = [
        str(p.get("email") or "").strip()
        for p in (cfg.responsabili or []) if isinstance(p, dict)
    ]
    email.append((cfg.responsabile_email or "").strip())
    email = list(dict.fromkeys(e for e in email if e))
    if email:
        return email
    fallback = getattr(settings, "DEFAULT_FROM_EMAIL", "")
    return [fallback] if fallback else []


# ── Builders testo/HTML ────────────────────────────────────────────────────────

def _build_body_text(non_salvate: list, non_inviate: list, giorni: int, anomalie: list | None = None) -> str:
    lines = [
        f"Alert RENTRI — registrazioni in scadenza (soglia: {giorni} giorni)",
        "",
    ]
    if non_salvate:
        lines.append(f"NON SALVATE/CONFERMATE ({len(non_salvate)}):")
        for r in non_salvate:
            lines.append(
                f"  [{r.tipo}] {r.id_registrazione or '—'} | {r.data} | "
                f"Codice: {r.codice or '—'} | Inserito: {r.created_at.strftime('%Y-%m-%d')}"
            )
        lines.append("")
    if non_inviate:
        lines.append(f"NON INVIATE A RENTRI ({len(non_inviate)}):")
        for r in non_inviate:
            lines.append(
                f"  [{r.tipo}] {r.id_registrazione or '—'} | {r.data} | "
                f"Codice: {r.codice or '—'} | Inserito: {r.created_at.strftime('%Y-%m-%d')}"
            )
    if anomalie:
        lines.append("")
        lines.append("VERIFICA DI COERENZA (dettaglio in RENTRI > Verifica):")
        for label, n in anomalie:
            lines.append(f"  {label}: {n}")
    return "\n".join(lines)


def _build_body_html(non_salvate: list, non_inviate: list, giorni: int, anomalie: list | None = None) -> str:
    def _rows(records: list, badge_color: str = "#e2e8f0", text_color: str = "#0f172a") -> str:
        rows = []
        for r in records:
            tipo_color = _TIPO_COLOR.get(r.tipo, "#64748b")
            rows.append(
                f"""<tr style="border-bottom:1px solid #e2e8f0;">
                  <td style="padding:8px 10px;">
                    <span style="display:inline-block;padding:2px 8px;border-radius:6px;
                          font-size:11px;font-weight:700;background:{tipo_color};
                          color:{'#fff' if r.tipo != 'R' else '#333'};">
                      {_TIPO_LABEL.get(r.tipo, r.tipo)}
                    </span>
                  </td>
                  <td style="padding:8px 10px;font-size:13px;">{r.id_registrazione or "—"}</td>
                  <td style="padding:8px 10px;font-size:13px;">{r.data}</td>
                  <td style="padding:8px 10px;font-size:13px;">{r.codice or "—"}</td>
                  <td style="padding:8px 10px;font-size:13px;">{r.inserito_da or "—"}</td>
                  <td style="padding:8px 10px;font-size:13px;color:#64748b;">{r.created_at.strftime('%Y-%m-%d')}</td>
                </tr>"""
            )
        return "".join(rows)

    def _section(title: str, badge_bg: str, records: list) -> str:
        if not records:
            return ""
        return f"""
        <h3 style="font-size:14px;font-weight:700;color:#0f172a;margin:24px 0 8px;">
          <span style="display:inline-block;padding:3px 10px;border-radius:6px;
                background:{badge_bg};color:#fff;font-size:12px;margin-right:8px;">
            {len(records)}
          </span>{title}
        </h3>
        <table style="width:100%;border-collapse:collapse;background:#fff;border-radius:10px;overflow:hidden;
                      border:1px solid #e2e8f0;font-family:system-ui,sans-serif;">
          <thead>
            <tr style="background:#f8fafc;">
              <th style="padding:8px 10px;text-align:left;font-size:11px;color:#64748b;font-weight:700;text-transform:uppercase;">Tipo</th>
              <th style="padding:8px 10px;text-align:left;font-size:11px;color:#64748b;font-weight:700;text-transform:uppercase;">ID Reg.</th>
              <th style="padding:8px 10px;text-align:left;font-size:11px;color:#64748b;font-weight:700;text-transform:uppercase;">Data</th>
              <th style="padding:8px 10px;text-align:left;font-size:11px;color:#64748b;font-weight:700;text-transform:uppercase;">Codice</th>
              <th style="padding:8px 10px;text-align:left;font-size:11px;color:#64748b;font-weight:700;text-transform:uppercase;">Inserito da</th>
              <th style="padding:8px 10px;text-align:left;font-size:11px;color:#64748b;font-weight:700;text-transform:uppercase;">Creato il</th>
            </tr>
          </thead>
          <tbody>{_rows(records)}</tbody>
        </table>"""

    return f"""<!DOCTYPE html>
<html lang="it"><head><meta charset="UTF-8"></head>
<body style="font-family:system-ui,-apple-system,sans-serif;background:#f1f5f9;margin:0;padding:24px;">
  <div style="max-width:800px;margin:0 auto;background:#fff;border-radius:14px;overflow:hidden;
              box-shadow:0 4px 20px rgba(0,0,0,.08);">
    <div style="background:#1e3a5f;padding:24px 28px;color:#fff;">
      <div style="font-size:22px;font-weight:900;letter-spacing:-.02em;">RENTRI — Alert Scadenze</div>
      <div style="font-size:13px;opacity:.7;margin-top:4px;">
        Soglia: {giorni} giorni — {len(non_salvate) + len(non_inviate)} record richiedono attenzione
      </div>
    </div>
    <div style="padding:24px 28px;">
      {_section("Non salvate / non confermate", "#dc2626", non_salvate)}
      {_section("Non inviate a RENTRI", "#d97706", non_inviate)}
      {_anomalie_html(anomalie or [])}
      <p style="font-size:11px;color:#94a3b8;margin-top:24px;border-top:1px solid #e2e8f0;padding-top:12px;">
        Generato automaticamente da Portale Novicrom — check_rentri_scadenze
      </p>
    </div>
  </div>
</body></html>"""


def _anomalie_html(anomalie: list) -> str:
    if not anomalie:
        return ""
    from html import escape

    righe = "".join(
        f'<tr><td style="padding:6px 10px;font-size:13px;">{escape(label)}</td>'
        f'<td style="padding:6px 10px;font-size:13px;font-weight:700;text-align:right;">{n}</td></tr>'
        for label, n in anomalie
    )
    return (
        '<h3 style="font-size:14px;font-weight:700;color:#0f172a;margin:24px 0 8px;">'
        "Verifica di coerenza del registro</h3>"
        '<table style="width:100%;border-collapse:collapse;border:1px solid #e2e8f0;">'
        f"{righe}</table>"
        '<p style="font-size:12px;color:#64748b;">Dettaglio in RENTRI → Verifica.</p>'
    )
