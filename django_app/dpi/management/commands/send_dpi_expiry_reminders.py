"""Invia promemoria email per DPI scaduti o in scadenza.

Destinatari:
- digest completo ogni mattina ai referenti DPI (Impostazioni DPI: responsabili +
  email aggiuntive) e a ``SiteConfig dpi_reminder_emails``; ripiego ADMINS/superuser;
- al responsabile/preposto del dipendente (stessa regola di approvazione di
  ``dpi.flusso.approvatori_di``) solo i DPI della sua squadra, e solo nei giorni
  «di soglia» (vedi :func:`_giorno_di_avviso`) per non scrivergli ogni mattina;
- al dipendente una notifica in-app negli stessi giorni di soglia.
Le consegne gia' sostituite da una nuova non contano piu'.
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import SiteConfig
from core.notifiche import invia_notifica
from core.permessi.identita import utente_da_anagrafica
from dpi.models import ConsegnaDPI, StatoRichiesta


def _split_emails(raw: str) -> list[str]:
    cleaned = raw.replace("\r", "\n").replace(",", "\n").replace(";", "\n")
    return [email.strip() for email in cleaned.split("\n") if email.strip()]


def _get_recipients(override: list[str] | None) -> list[str]:
    if override:
        return [email.strip() for email in override if email.strip()]

    from dpi.flusso import destinatari_referenti

    recipients: list[str] = list(destinatari_referenti())
    recipients.extend(_split_emails(SiteConfig.get("dpi_reminder_emails", "")))

    if not recipients:
        admins = getattr(settings, "ADMINS", ()) or ()
        recipients.extend(str(email).strip() for _name, email in admins if str(email).strip())

    if not recipients:
        User = get_user_model()
        recipients.extend(
            User.objects.filter(is_active=True, is_superuser=True)
            .exclude(email="")
            .values_list("email", flat=True)
            .distinct()
        )

    return sorted(set(recipients))


def _giorno_di_avviso(giorni_mancanti: int, anticipo: int) -> bool:
    """Giorni in cui avvisare dipendente e responsabile: a ``anticipo`` giorni, a 7,
    a 1, il giorno della scadenza; scaduto, il giorno dopo e poi ogni 7 giorni."""
    if giorni_mancanti >= 0:
        return giorni_mancanti in {anticipo, 7, 1, 0}
    return (-giorni_mancanti) % 7 == 1


def _riga(consegna, today) -> str:
    r = consegna.richiesta
    sc = consegna.data_scadenza_stimata
    if sc < today:
        return f"  [{(today - sc).days}gg] {r.numero} - {r.richiedente_nome} - {r.categoria.nome} - scaduto il {sc:%d-%m-%Y}"
    return f"  [{(sc - today).days}gg] {r.numero} - {r.richiedente_nome} - {r.categoria.nome} - scadenza {sc:%d-%m-%Y}"


def _avvisa_responsabili(consegne, today, days, *, dry_run, stdout) -> int:
    """Una mail per responsabile/preposto con i DPI della sua squadra, solo se almeno
    uno e' in un giorno di soglia oggi. Ritorna le mail inviate."""
    from core.email_utils import send_hub_mail
    from dpi.flusso import _email_persona, approvatori_di

    per_capo: dict[str, list] = {}
    con_soglia: set[str] = set()
    cache: dict[int, set[int]] = {}
    for c in consegne:
        legacy = c.richiesta.richiedente_legacy_id
        if not legacy:
            continue
        if legacy not in cache:
            cache[legacy] = approvatori_di(legacy)
        soglia = _giorno_di_avviso((c.data_scadenza_stimata - today).days, days)
        for capo in cache[legacy]:
            email = _email_persona(capo)
            if not email:
                continue
            per_capo.setdefault(email.lower(), []).append(c)
            if soglia:
                con_soglia.add(email.lower())

    inviate = 0
    for email in sorted(con_soglia):
        voci = per_capo[email]
        righe = [
            f"NOVICROM HUB - DPI della tua squadra del {today:%d-%m-%Y}",
            "=" * 60,
            "",
            "Sei responsabile o preposto di questi dipendenti: verifica che usino DPI in corso di validita'",
            "e, se serve, fai la richiesta di sostituzione (DPI > Nuova richiesta, per conto del dipendente).",
            "",
        ] + [_riga(c, today) for c in voci]
        oggetto = f"[DPI] DPI scaduti o in scadenza nella tua squadra ({len(voci)}) - {today:%d-%m-%Y}"
        if dry_run:
            stdout.write(f"[DRY-RUN] Responsabile {email}: {len(voci)} voci")
            continue
        send_hub_mail(
            oggetto, "\n".join(righe), [email],
            email_type="DPI", section_label="Reminder scadenze", fail_silently=True,
        )
        inviate += 1
    return inviate


class Command(BaseCommand):
    help = "Invia un digest email dei DPI scaduti o in scadenza."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=30,
            help="Giorni di anticipo per DPI in scadenza (default: 30).",
        )
        parser.add_argument(
            "--recipients",
            nargs="*",
            help="Email destinatari (sovrascrive impostazioni DPI/SiteConfig/ADMINS).",
        )
        parser.add_argument("--dry-run", action="store_true", help="Stampa senza inviare email.")

    def handle(self, *args, **options):
        today = timezone.localdate()
        days = max(1, int(options.get("days") or 30))
        horizon = today + timedelta(days=days)
        dry_run = bool(options.get("dry_run"))
        recipients = _get_recipients(options.get("recipients") or [])

        scaduti = list(
            ConsegnaDPI.objects.filter(
                richiesta__stato=StatoRichiesta.CONSEGNATA,
                sostituita_da__isnull=True,
                data_scadenza_stimata__isnull=False,
                data_scadenza_stimata__lt=today,
            )
            .select_related("richiesta", "richiesta__categoria", "richiesta__tipo_dpi", "richiesta__modello_dpi", "richiesta__taglia_dpi")
            .order_by("data_scadenza_stimata")
        )
        in_scadenza = list(
            ConsegnaDPI.objects.filter(
                richiesta__stato=StatoRichiesta.CONSEGNATA,
                sostituita_da__isnull=True,
                data_scadenza_stimata__isnull=False,
                data_scadenza_stimata__gte=today,
                data_scadenza_stimata__lte=horizon,
            )
            .select_related("richiesta", "richiesta__categoria", "richiesta__tipo_dpi", "richiesta__modello_dpi", "richiesta__taglia_dpi")
            .order_by("data_scadenza_stimata")
        )

        if not scaduti and not in_scadenza:
            self.stdout.write("Nessun DPI scaduto o in scadenza.")
            return

        lines = [
            f"NOVICROM HUB - Promemoria DPI del {today:%d-%m-%Y}",
            "=" * 60,
            "",
        ]
        if scaduti:
            lines.append(f"DPI SCADUTI ({len(scaduti)}):")
            for consegna in scaduti:
                r = consegna.richiesta
                days_over = (today - consegna.data_scadenza_stimata).days
                lines.append(
                    f"  [{days_over}gg] {r.numero} - {r.richiedente_nome} - "
                    f"{r.categoria.nome} - scaduto il {consegna.data_scadenza_stimata:%d-%m-%Y}"
                )
                if not dry_run and r.richiedente_legacy_id and _giorno_di_avviso(-days_over, days):
                    invia_notifica(
                        utente_da_anagrafica(r.richiedente_legacy_id),
                        "dpi_scadenza",
                        f"DPI scaduto: {r.numero} - {r.categoria.nome} dal {consegna.data_scadenza_stimata:%d-%m-%Y}.",
                        f"/dpi/{r.pk}/",
                    )
            lines.append("")

        if in_scadenza:
            lines.append(f"DPI IN SCADENZA entro {days} giorni ({len(in_scadenza)}):")
            for consegna in in_scadenza:
                r = consegna.richiesta
                days_left = (consegna.data_scadenza_stimata - today).days
                lines.append(
                    f"  [{days_left}gg] {r.numero} - {r.richiedente_nome} - "
                    f"{r.categoria.nome} - scadenza {consegna.data_scadenza_stimata:%d-%m-%Y}"
                )
                if not dry_run and r.richiedente_legacy_id and _giorno_di_avviso(days_left, days):
                    invia_notifica(
                        utente_da_anagrafica(r.richiedente_legacy_id),
                        "dpi_scadenza",
                        f"DPI in scadenza tra {days_left} giorni: {r.numero} - {r.categoria.nome}.",
                        f"/dpi/{r.pk}/",
                    )
            lines.append("")

        body = "\n".join(lines)
        subject = f"[DPI] {len(scaduti)} scaduti + {len(in_scadenza)} in scadenza - {today:%d-%m-%Y}"

        n_capi = _avvisa_responsabili(scaduti + in_scadenza, today, days, dry_run=dry_run, stdout=self.stdout)

        if dry_run:
            self.stdout.write(self.style.WARNING("[DRY-RUN] Nessuna email inviata."))
            self.stdout.write(f"Destinatari: {recipients}")
            self.stdout.write(body)
            return

        if not recipients:
            self.stdout.write(self.style.ERROR("Nessun destinatario configurato per i reminder DPI."))
            return

        from automazioni.mail_config import apply_mail_overrides
        from core.email_utils import send_hub_mail
        subject, body, fragment, footer = apply_mail_overrides(
            "dpi_expiry_reminders", subject=subject, body_text=body)
        send_hub_mail(
            subject, body, recipients,
            email_type="DPI",
            section_label="Reminder scadenze",
            body_html_fragment=fragment,
            footer_note=footer,
            fail_silently=False,
        )
        self.stdout.write(self.style.SUCCESS(
            f"Email inviata a {len(recipients)} destinatari (+{n_capi} responsabili). "
            f"Scaduti={len(scaduti)} In_scadenza={len(in_scadenza)}"
        ))
