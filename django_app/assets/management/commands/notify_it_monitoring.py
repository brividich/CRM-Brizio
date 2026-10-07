"""Avvisi proattivi dal monitoraggio IT: dispositivi che non rispondono e consumabili bassi.

Pensato per girare una volta al giorno (django-q). Due canali:

- **digest email** con tutti i problemi aperti, ai destinatari di
  ``SiteConfig['assets_it_monitoring_emails']`` (poi ``assets_reminder_emails``,
  poi la cascata standard di ``core.reminder_recipients``);
- **notifica in app** solo per i problemi *nuovi* rispetto al giorno prima
  (dispositivo diventato muto o in errore nelle ultime 24 ore, consumabile appena
  sceso sotto soglia), cosi' lo stesso avviso non si ripete ogni mattina.

Nessun ticket automatico: chi gestisce l'IT decide cosa farne.

Uso:
    python manage.py notify_it_monitoring [--dry-run] [--recipients a@b.it ...]
"""
from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.urls import reverse
from django.utils import timezone

from assets.services.it_coverage import SILENT_AFTER

LOW_TONER_PCT = 15
NEW_WINDOW = timedelta(hours=24)


def _recipients(override):
    from core.models import SiteConfig
    from core.reminder_recipients import resolve_reminder_recipients

    if not override:
        own = SiteConfig.get("assets_it_monitoring_emails", "") or ""
        override = [x.strip() for x in str(own).replace(";", ",").split(",") if x.strip()]
    return resolve_reminder_recipients(config_key="assets_reminder_emails", override=override or None)


def collect_problems(now=None) -> list[dict]:
    """``[{"kind", "title", "detail", "url", "new"}]`` con i problemi aperti."""
    from contatori.models import DispositivoSNMP, LetturaConsumabile, Macchina, RilevazioneSNMP

    now = now or timezone.now()
    problems = []
    devices = [(d, d.nome, reverse("contatori:snmp_dispositivo", args=[d.pk])) for d in DispositivoSNMP.objects.filter(attivo=True)]
    devices += [(m, f"MFC {m.reparto}", reverse("contatori:macchina", args=[m.pk])) for m in Macchina.objects.filter(attiva=True).exclude(host__isnull=True)]
    for obj, name, url in devices:
        last = obj.snmp_ultimo_controllo
        if obj.snmp_stato == "ERROR":
            # Nuovo solo al passaggio in errore: la rilevazione precedente era buona.
            # Le MFC non hanno storico delle rilevazioni: restano nel digest.
            new = False
            if isinstance(obj, DispositivoSNMP):
                states = list(RilevazioneSNMP.objects.filter(dispositivo=obj).order_by("-rilevata_il", "-pk")
                              .values_list("stato", flat=True)[:2])
                new = len(states) == 2 and states[0] == "ERROR" and states[1] != "ERROR"
            problems.append({
                "kind": "errore", "title": f"{name} non risponde al monitoraggio",
                "detail": (obj.snmp_ultimo_errore or "")[:160], "url": url, "new": new,
            })
        elif last is not None and now - last > SILENT_AFTER:
            problems.append({
                "kind": "muto", "title": f"{name}: nessun controllo da {(now - last).days} giorni",
                "detail": "", "url": url,
                "new": now - last <= SILENT_AFTER + NEW_WINDOW,
            })
    # Consumabili: ultima e penultima lettura per macchina e consumabile.
    latest: dict[tuple, list] = {}
    for row in LetturaConsumabile.objects.filter(macchina__attiva=True).select_related("macchina").order_by("-rilevata_il")[:2000]:
        rows = latest.setdefault((row.macchina_id, row.nome), [])
        if len(rows) < 2:
            rows.append(row)
    for rows in latest.values():
        current = rows[0]
        if current.pct is None or current.pct > LOW_TONER_PCT:
            continue
        previous = rows[1] if len(rows) > 1 else None
        problems.append({
            "kind": "consumabile",
            "title": f"MFC {current.macchina.reparto}: {current.nome} al {current.pct}%",
            "detail": "", "url": reverse("contatori:macchina", args=[current.macchina_id]),
            "new": previous is None or previous.pct is None or previous.pct > LOW_TONER_PCT,
        })
    return problems


class Command(BaseCommand):
    help = "Avvisi IT: dispositivi SNMP muti/in errore e consumabili sotto soglia (digest + notifiche nuove)."

    def add_arguments(self, parser):
        parser.add_argument("--recipients", nargs="*", default=[], help="Destinatari espliciti (sostituiscono la configurazione).")
        parser.add_argument("--dry-run", action="store_true", help="Stampa senza inviare.")

    def handle(self, *args, **options):
        problems = collect_problems()
        recipients = _recipients(options.get("recipients") or [])
        new = [p for p in problems if p["new"]]
        lines = [f"Problemi aperti nel monitoraggio IT: {len(problems)} (nuovi: {len(new)})", ""]
        for p in problems:
            lines.append(f"  {'[NUOVO] ' if p['new'] else ''}{p['title']}" + (f" — {p['detail']}" if p["detail"] else ""))
        body = "\n".join(lines)
        if options.get("dry_run"):
            self.stdout.write(f"Destinatari: {recipients}")
            self.stdout.write(body)
            return
        if not problems:
            self.stdout.write("Nessun problema aperto: nessun invio.")
            return
        if not recipients:
            self.stdout.write(self.style.ERROR("Nessun destinatario configurato (SiteConfig 'assets_it_monitoring_emails')."))
            return
        from core.email_utils import send_hub_mail
        from core.notifiche import invia_notifica_email

        send_hub_mail(
            f"[Monitoraggio IT] {len(problems)} problemi aperti — {timezone.localdate():%d-%m-%Y}",
            body, recipients, email_type="Assets", section_label="Monitoraggio IT", fail_silently=False,
        )
        notified = 0
        for email in recipients:
            for p in new:
                notified += invia_notifica_email(email, "generico", f"Monitoraggio IT: {p['title']}", p["url"])
        self.stdout.write(self.style.SUCCESS(
            f"Digest inviato a {len(recipients)} destinatari; {notified} notifiche in app per {len(new)} problemi nuovi."
        ))
