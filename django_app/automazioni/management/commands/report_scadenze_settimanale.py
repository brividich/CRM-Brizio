"""
Management command: report_scadenze_settimanale

Check schedulato (lunedi 6:00 via django-q, schedule_type='C') delle scadenze
che "maturano nel tempo" e che il motore automazioni event-driven non puo'
intercettare (nessun insert/update sul record genera l'evento alla scadenza):

  - Visite mediche (sorveglianza sanitaria) con data_scadenza nei prossimi N giorni
  - Contratti a tempo determinato (StoricoContratto.data_fine) nei prossimi N giorni
  - Periodi di prova (DipendenteAnagraficaAziendale.prova_data_fine) nei prossimi N giorni

Invia UNA email riepilogativa per categoria a referenti fissi configurabili via
SiteConfig (fallback DEFAULT_FROM_EMAIL). Nessun dato sanitario di dettaglio: solo
ID dipendente, nominativo e data, coerente con il pattern degli AU esistenti.

Utilizzo:
    python manage.py report_scadenze_settimanale
    python manage.py report_scadenze_settimanale --giorni 30 --dry-run
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.management.base import BaseCommand
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.safestring import mark_safe

from monitoring.automation import monitored_automation
from monitoring.models import AutomationExecution

from automazioni.scadenze_config import DEFAULT_GIORNI, get_scadenze_config


def _nominativi(legacy_ids: list[int]) -> dict[int, str]:
    """Risolve {legacy_id: 'Cognome Nome'} dalla tabella legacy AnagraficaDipendente."""
    from core.legacy_models import AnagraficaDipendente

    out: dict[int, str] = {}
    if not legacy_ids:
        return out
    for r in AnagraficaDipendente.objects.filter(id__in=legacy_ids).values("id", "cognome", "nome"):
        cognome = str(r.get("cognome") or "").strip()
        nome = str(r.get("nome") or "").strip()
        out[r["id"]] = f"{cognome} {nome}".strip() or f"#{r['id']}"
    return out


def _righe_html(righe: list[dict]) -> str:
    """Tabella HTML compatta coerente con base_email.html."""
    head = (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'style="width:100%;border-collapse:collapse;background:#f6f9fc;border:1px solid #d8e1ec;'
        'border-radius:10px;overflow:hidden;">'
        '<tr style="background:#eef3f8;">'
        '<th style="text-align:left;padding:9px 14px;color:#64748b;font-size:12px;text-transform:uppercase;letter-spacing:.04em;">Dipendente</th>'
        '<th style="text-align:left;padding:9px 14px;color:#64748b;font-size:12px;text-transform:uppercase;letter-spacing:.04em;">Dettaglio</th>'
        '<th style="text-align:left;padding:9px 14px;color:#64748b;font-size:12px;text-transform:uppercase;letter-spacing:.04em;">Scadenza</th>'
        '</tr>'
    )
    body = ""
    for r in righe:
        body += (
            '<tr>'
            f'<td style="padding:9px 14px;border-top:1px solid #e2e8f0;color:#182232;font-size:14px;">{r["dipendente"]}</td>'
            f'<td style="padding:9px 14px;border-top:1px solid #e2e8f0;color:#475569;font-size:14px;">{r["dettaglio"]}</td>'
            f'<td style="padding:9px 14px;border-top:1px solid #e2e8f0;color:#182232;font-size:14px;font-weight:700;">{r["scadenza"]}</td>'
            '</tr>'
        )
    return head + body + '</table>'


def _invia(*, destinatari: list[str], section_label: str, titolo: str,
           intro: str, righe: list[dict], dry_run: bool) -> dict:
    """Compone e invia (o simula) la email riepilogativa per una categoria."""
    if not righe:
        return {"sent": False, "reason": "nessuna_scadenza", "count": 0, "to": destinatari}
    if not destinatari:
        return {"sent": False, "reason": "destinatari_mancanti", "count": len(righe), "to": []}

    body_content = mark_safe(
        f'<p style="margin:0 0 14px;color:#475569;font-size:15px;line-height:1.65;">{intro}</p>'
        + _righe_html(righe)
    )
    html_body = render_to_string("core/email/base_email.html", {
        "email_type": "Automazioni",
        "badge": f"{len(righe)} in scadenza",
        "section_label": section_label,
        "title": titolo,
        "body_content": body_content,
    })
    text_lines = [intro, ""]
    for r in righe:
        text_lines.append(f"- {r['dipendente']} | {r['dettaglio']} | scade il {r['scadenza']}")
    text_lines.append("\nMessaggio automatico generato da NOVICROM HUB.")
    text_body = "\n".join(text_lines)
    subject = f"[Scadenze] {titolo} ({len(righe)})"

    if dry_run:
        return {"sent": False, "reason": "dry_run", "count": len(righe), "to": destinatari}

    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "") or None
    message = EmailMultiAlternatives(subject=subject, body=text_body, from_email=from_email, to=destinatari)
    message.attach_alternative(html_body, "text/html")
    message.send(fail_silently=False)
    return {"sent": True, "count": len(righe), "to": destinatari}


def _raccogli_visite(oggi, limite):
    from anagrafica.models import VisitaMedica

    qs = (
        VisitaMedica.objects
        .filter(data_scadenza__isnull=False, data_scadenza__gte=oggi, data_scadenza__lte=limite)
        .values("legacy_anagrafica_id", "data_scadenza", "tipo__nome")
        .order_by("data_scadenza")
    )
    rows = list(qs)
    nomi = _nominativi([r["legacy_anagrafica_id"] for r in rows])
    return [
        {
            "dipendente": nomi.get(r["legacy_anagrafica_id"], f"#{r['legacy_anagrafica_id']}"),
            "dettaglio": f"Visita medica — {r['tipo__nome'] or 'periodica'}",
            "scadenza": r["data_scadenza"].strftime("%d-%m-%Y"),
        }
        for r in rows
    ]


def _raccogli_contratti(oggi, limite):
    from anagrafica.models import DipendenteAnagraficaAziendale, StoricoContratto

    righe: list[dict] = []
    legacy_ids: set[int] = set()

    contratti = list(
        StoricoContratto.objects
        .filter(data_fine__isnull=False, data_fine__gte=oggi, data_fine__lte=limite)
        .values("legacy_anagrafica_id", "data_fine", "tipologia_contratto")
        .order_by("data_fine")
    )
    prove = list(
        DipendenteAnagraficaAziendale.objects
        .filter(prova_data_fine__isnull=False, prova_data_fine__gte=oggi, prova_data_fine__lte=limite,
                data_cessazione__isnull=True)
        .values("legacy_anagrafica_id", "prova_data_fine")
        .order_by("prova_data_fine")
    )
    legacy_ids.update(c["legacy_anagrafica_id"] for c in contratti if c["legacy_anagrafica_id"])
    legacy_ids.update(p["legacy_anagrafica_id"] for p in prove if p["legacy_anagrafica_id"])
    nomi = _nominativi(list(legacy_ids))

    for c in contratti:
        lid = c["legacy_anagrafica_id"]
        tipo = (c["tipologia_contratto"] or "").strip() or "Tempo determinato"
        righe.append({
            "dipendente": nomi.get(lid, f"#{lid}"),
            "dettaglio": f"Fine contratto — {tipo}",
            "scadenza": c["data_fine"].strftime("%d-%m-%Y"),
            "_sort": c["data_fine"],
        })
    for p in prove:
        lid = p["legacy_anagrafica_id"]
        righe.append({
            "dipendente": nomi.get(lid, f"#{lid}"),
            "dettaglio": "Fine periodo di prova",
            "scadenza": p["prova_data_fine"].strftime("%d-%m-%Y"),
            "_sort": p["prova_data_fine"],
        })

    righe.sort(key=lambda r: r["_sort"])
    for r in righe:
        r.pop("_sort", None)
    return righe


@monitored_automation(
    job_code="automazioni_report_scadenze_settimanale",
    job_name="Report scadenze settimanale",
    module_name="automazioni",
    critical=False,
    description="Check schedulato delle visite mediche e dei contratti in scadenza; invio email riepilogative ai referenti.",
    schedule_hint="Lunedi 06:00",
    expected_max_interval_minutes=60 * 24 * 8,
    expected_max_duration_seconds=120,
    alert_after_consecutive_failures=2,
    re_raise=False,
)
def _esegui_report(*, giorni: int | None, dry_run: bool, forza: bool) -> dict:
    """Logica condivisa. Legge la config UI (SiteConfig); rispetta flag e categorie.

    - Se il report e' disattivato in UI e non si forza (es. test manuale), non invia.
    - 'giorni' override esplicito da CLI; altrimenti il valore configurato in UI.
    """
    cfg = get_scadenze_config()

    if not cfg["attivo"] and not forza:
        return {
            "disattivato": True,
            "visite": {"sent": False, "reason": "report_disattivato", "count": 0, "to": []},
            "contratti": {"sent": False, "reason": "report_disattivato", "count": 0, "to": []},
            "monitoring_message": "[skip] report scadenze disattivato da Impostazioni.",
            "monitoring_payload": {"attivo": False, "dry_run": dry_run},
        }

    giorni_eff = int(giorni) if giorni else int(cfg["giorni"])
    giorni_eff = max(giorni_eff, 1)
    oggi = timezone.localdate()
    limite = oggi + timedelta(days=giorni_eff)

    if cfg["includi_visite"]:
        visite = _raccogli_visite(oggi, limite)
        res_visite = _invia(
            destinatari=cfg["email_visite"],
            section_label="Sorveglianza sanitaria",
            titolo="Visite mediche in scadenza",
            intro=f"Le seguenti visite mediche risultano in scadenza nei prossimi {giorni_eff} giorni. "
                  f"Pianificare per tempo i rinnovi della sorveglianza sanitaria.",
            righe=visite,
            dry_run=dry_run,
        )
    else:
        res_visite = {"sent": False, "reason": "categoria_disattivata", "count": 0, "to": []}

    if cfg["includi_contratti"]:
        contratti = _raccogli_contratti(oggi, limite)
        res_contratti = _invia(
            destinatari=cfg["email_contratti"],
            section_label="Personale / Contratti",
            titolo="Contratti e periodi di prova in scadenza",
            intro=f"I seguenti rapporti di lavoro risultano in scadenza nei prossimi {giorni_eff} giorni "
                  f"(fine contratto o fine periodo di prova). Verificare proroghe, rinnovi o conferme.",
            righe=contratti,
            dry_run=dry_run,
        )
    else:
        res_contratti = {"sent": False, "reason": "categoria_disattivata", "count": 0, "to": []}

    return {
        "disattivato": False,
        "monitoring_message": (
            f"[{'dry-run' if dry_run else 'run'}] giorni={giorni_eff} "
            f"visite={res_visite.get('count', 0)}(sent={res_visite.get('sent')}) "
            f"contratti={res_contratti.get('count', 0)}(sent={res_contratti.get('sent')})"
        ),
        "monitoring_payload": {
            "giorni": giorni_eff,
            "dry_run": dry_run,
            "visite": res_visite,
            "contratti": res_contratti,
        },
        "visite": res_visite,
        "contratti": res_contratti,
    }


@monitored_automation(
    job_code="automazioni_report_scadenze_settimanale",
    job_name="Report scadenze settimanale",
    module_name="automazioni",
    critical=False,
    description="Check schedulato delle visite mediche e dei contratti in scadenza; invio email riepilogative ai referenti.",
    schedule_hint="Lunedi 06:00",
    expected_max_interval_minutes=60 * 24 * 8,
    expected_max_duration_seconds=120,
    alert_after_consecutive_failures=2,
    re_raise=False,
)
def _monitored_report(*, giorni: int | None = None, dry_run: bool = False, forza: bool = False) -> dict:
    return _esegui_report(giorni=giorni, dry_run=dry_run, forza=forza)


class Command(BaseCommand):
    help = "Invia il report settimanale delle visite mediche e dei contratti in scadenza."

    def add_arguments(self, parser):
        parser.add_argument("--giorni", type=int, default=None,
                            help=f"Override finestra di anticipo (default: valore configurato in UI o {DEFAULT_GIORNI}).")
        parser.add_argument("--dry-run", action="store_true",
                            help="Calcola le scadenze senza inviare email.")
        parser.add_argument("--forza", action="store_true",
                            help="Esegui anche se il report è disattivato in Impostazioni (test manuale).")
        parser.add_argument("--no-monitoring", action="store_true",
                            help="Salta la registrazione monitoring (utile per test/debug).")

    def handle(self, *args, **options):
        giorni = options.get("giorni")
        dry_run = bool(options.get("dry_run"))
        forza = bool(options.get("forza"))
        no_monitoring = bool(options.get("no_monitoring"))

        if no_monitoring:
            summary = _esegui_report(giorni=giorni, dry_run=dry_run, forza=forza)
        else:
            summary = _monitored_report(
                giorni=giorni,
                dry_run=dry_run,
                forza=forza,
                monitoring_trigger_type=AutomationExecution.TriggerType.SCHEDULER,
            ) or {}

        if summary.get("disattivato"):
            self.stdout.write("[skip] Report scadenze disattivato in Impostazioni (usa --forza per testarlo).")
            return

        v = summary.get("visite", {})
        c = summary.get("contratti", {})
        mode = "dry-run" if dry_run else "run"
        self.stdout.write(
            f"[{mode}] visite: {v.get('count', 0)} (sent={v.get('sent')}, {v.get('reason', 'ok')}) | "
            f"contratti: {c.get('count', 0)} (sent={c.get('sent')}, {c.get('reason', 'ok')})"
        )
