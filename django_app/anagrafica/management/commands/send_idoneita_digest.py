"""Digest "idoneità alla mansione": dipendenti non idonei o idonei con riserve.

Job schedulato (NON regola del designer): pattern di ``send_visite_mediche_digest`` /
``send_dpi_expiry_reminders``. Destina a RSPP / medico competente / HR i dipendenti
i cui requisiti di mansione (DPI / formazione / visite) risultano scaduti (non idoneo)
o mancanti (idoneo con riserve), riusando la lente ``idoneita`` del servizio conformità.

    python manage.py send_idoneita_digest [--only-ko] [--dry-run] [--recipients a@x b@y]

Privacy: nessun dato clinico (le visite restano in forma generica "Visita richiesta").
Lo scadenzario per-scadenza vive già nello Scadenzario Globale C5 (``collect_hr``).
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from anagrafica.services import conformita as conformita_service
from anagrafica.services.email_digest import digest_fragment
from anagrafica.services.reminders import get_reminder_recipients

CONFIG_KEY = "idoneita_reminder_emails"


class Command(BaseCommand):
    help = "Digest idoneità alla mansione (non idonei / con riserve) per RSPP / medico competente / HR."

    def add_arguments(self, parser):
        parser.add_argument("--only-ko", action="store_true",
                            help="Solo non idonei (requisito scaduto), escludi 'con riserve'.")
        parser.add_argument("--recipients", nargs="*", help="Email destinatari (override).")
        parser.add_argument("--dry-run", action="store_true", help="Stampa senza inviare.")

    def handle(self, *args, **options):
        from core.legacy_anagrafica import fetch_anagrafica_rows

        today = timezone.localdate()
        only_ko = bool(options.get("only_ko"))
        dry_run = bool(options.get("dry_run"))

        rows = [r for r in fetch_anagrafica_rows(deduplicate=True) if r.get("attivo")]
        dip_map = {int(r["id"]): r for r in rows if r.get("id")}
        mansioni = {
            lid: str(d.get("mansione") or "").strip()
            for lid, d in dip_map.items() if str(d.get("mansione") or "").strip()
        }
        if not mansioni:
            self.stdout.write("Nessun dipendente con mansione valorizzata: niente da valutare.")
            return

        stati = conformita_service.stato_conformita_batch(
            list(dip_map), mansioni_per_legacy=mansioni
        )
        ko, warn = [], []
        for lid, s in stati.items():
            idn = s.get("idoneita", {})
            if idn.get("esito") == conformita_service.ESITO_KO:
                ko.append((lid, idn))
            elif idn.get("esito") == conformita_service.ESITO_WARN:
                warn.append((lid, idn))
        if only_ko:
            warn = []

        if not ko and not warn:
            self.stdout.write("Tutti i dipendenti valutati risultano idonei: nessun digest.")
            return

        def _nome(lid):
            d = dip_map.get(lid, {})
            return f"{str(d.get('cognome') or '').strip()} {str(d.get('nome') or '').strip()}".strip() or f"#{lid}"

        def _blocco(titolo, items):
            out = [titolo, "-" * 60]
            for lid, idn in sorted(items, key=lambda x: _nome(x[0]).casefold()):
                gap = list(idn.get("scaduti", [])) + list(idn.get("mancanti", []))
                rep = str(dip_map.get(lid, {}).get("reparto") or "").strip()
                out.append(f"  {_nome(lid)}{(' [' + rep + ']') if rep else ''}: " + "; ".join(gap))
            out.append("")
            return out

        lines = [f"NOVICROM HUB - Idoneità alla mansione - {today:%d-%m-%Y}", "=" * 60, ""]
        if ko:
            lines += _blocco(f"NON IDONEI - requisito scaduto ({len(ko)}):", ko)
        if warn:
            lines += _blocco(f"IDONEI CON RISERVE - requisito mancante ({len(warn)}):", warn)
        body = "\n".join(lines)
        subject = f"[Idoneità] {len(ko)} non idonei, {len(warn)} con riserve - {today:%d-%m-%Y}"

        recipients = get_reminder_recipients(CONFIG_KEY, options.get("recipients") or None)
        if dry_run:
            self.stdout.write(self.style.WARNING("[DRY-RUN] Nessuna email inviata."))
            self.stdout.write(f"Destinatari: {recipients}")
            self.stdout.write(body)
            return
        if not recipients:
            self.stdout.write(self.style.ERROR("Nessun destinatario configurato (idoneita_reminder_emails)."))
            return

        def _card(lid, idn, non_idoneo):
            gap = list(idn.get("scaduti", [])) + list(idn.get("mancanti", []))
            rep = str(dip_map.get(lid, {}).get("reparto") or "").strip()
            return {
                "title": _nome(lid),
                "subtitle": rep or None,
                "badge": ("Non idoneo", "danger") if non_idoneo else ("Con riserve", "warning"),
                "note": "; ".join(gap),
                "accent": "#dc2626" if non_idoneo else "#f59e0b",
            }

        ko_cards = [_card(lid, idn, True)
                    for lid, idn in sorted(ko, key=lambda x: _nome(x[0]).casefold())]
        warn_cards = [_card(lid, idn, False)
                      for lid, idn in sorted(warn, key=lambda x: _nome(x[0]).casefold())]
        fragment = digest_fragment([
            (f"Non idonei — requisito scaduto ({len(ko)})", ko_cards),
            (f"Idonei con riserve — requisito mancante ({len(warn)})", warn_cards),
        ])
        from core.email_utils import send_hub_mail
        send_hub_mail(
            subject, body, recipients,
            email_type="Anagrafica HR", section_label="Idoneità alla mansione",
            body_html_fragment=fragment, fail_silently=False,
        )
        self.stdout.write(self.style.SUCCESS(
            f"Digest idoneità inviato a {len(recipients)} destinatari ({len(ko)} non idonei, {len(warn)} con riserve)."
        ))
