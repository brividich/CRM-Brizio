"""AU51 - Digest mattutino per caporeparto (cross-modulo, ambito verificato).

Per ogni caporeparto (fonte autorevole ``Reparto.caporeparto_legacy_id``) invia un
riepilogo del suo reparto con le voci che hanno un legame reparto **pulito e
schedulabile offline**:
  - DPI in attesa (``RichiestaDPI`` INVIATA dai dipendenti del reparto);
  - incidenti aperti (``RilevazioneIncidente`` non chiusa dall'RSPP nel reparto).

Esclusi per design (nessun legame reparto affidabile): assenze da approvare (flusso
SharePoint, collegamento dismesso) e ticket del reparto (modello senza legame
reparto). L'aggregazione vive in ``core.caporeparto_digest`` (testabile).

Schedulare ogni mattina via QCluster. Destinatario: ``email_notifica`` del capo.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.caporeparto_digest import build_caporeparto_digest, capi_legacy_ids


class Command(BaseCommand):
    help = "AU51 - Digest mattutino per caporeparto (DPI in attesa + incidenti aperti del reparto)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--recipients", nargs="*",
            help="Forza i destinatari (email caporeparto) invece di risolverli dall'anagrafica.",
        )
        parser.add_argument("--dry-run", action="store_true", help="Stampa senza inviare email.")

    def handle(self, *args, **options):
        today = timezone.localdate()
        dry_run = bool(options.get("dry_run"))
        forced = [e.strip() for e in (options.get("recipients") or []) if e.strip()]

        capi = capi_legacy_ids()
        if not capi:
            self.stdout.write("Nessun caporeparto assegnato (Reparto.caporeparto_legacy_id).")
            return

        sent = 0
        for capo_id in capi:
            d = build_caporeparto_digest(capo_id)
            if d["totale"] == 0:
                continue

            email = forced[0] if forced else d["email"]
            reparti_txt = ", ".join(d["reparti"]) or "reparto"

            lines = [
                f"NOVICROM HUB - Buongiorno, riepilogo {reparti_txt} ({today:%d-%m-%Y})",
                "=" * 60,
                "",
            ]
            dpi_cards = []
            if d["dpi"]:
                lines.append(f"DPI IN ATTESA ({len(d['dpi'])}):")
                for r in d["dpi"]:
                    lines.append(f"  - {r.numero} · {r.categoria} · richiesto da {r.richiedente_nome}")
                    dpi_cards.append({
                        "title": f"{r.numero} · {r.categoria}",
                        "subtitle": f"Richiesto da {r.richiedente_nome}",
                        "badge": ("In attesa", "warning"),
                        "accent": "#f59e0b",
                    })
                lines.append("")
            inc_cards = []
            if d["incidenti"]:
                lines.append(f"INCIDENTI APERTI ({len(d['incidenti'])}):")
                for i in d["incidenti"]:
                    descr = (getattr(i, "descrizione", "") or "").strip() or f"Incidente #{i.pk}"
                    lines.append(f"  - {i.reparto or reparti_txt}: {descr[:80]}")
                    inc_cards.append({
                        "title": f"Incidente #{i.pk}",
                        "subtitle": i.reparto or reparti_txt,
                        "badge": ("Aperto", "danger"),
                        "note": descr[:140],
                        "accent": "#dc2626",
                    })
                lines.append("")

            body = "\n".join(lines)
            subject = f"[Caporeparto] Riepilogo {reparti_txt} - {today:%d-%m-%Y}"

            if dry_run:
                self.stdout.write(self.style.WARNING(f"[DRY-RUN] -> {email or '(nessuna email)'}"))
                self.stdout.write(body)
                continue

            if not email:
                self.stdout.write(self.style.ERROR(
                    f"Caporeparto #{capo_id}: email_notifica assente, digest non inviato "
                    f"({d['totale']} voci)."
                ))
                continue

            from core.email_utils import email_item_cards, send_hub_mail
            fragment = ""
            if dpi_cards:
                fragment += "<p style='margin:0 0 6px;font-weight:600'>DPI in attesa</p>" + email_item_cards(dpi_cards)
            if inc_cards:
                fragment += "<p style='margin:14px 0 6px;font-weight:600'>Incidenti aperti</p>" + email_item_cards(inc_cards)
            send_hub_mail(
                subject, body, [email],
                email_type="Core",
                section_label="Digest caporeparto",
                body_html_fragment=fragment,
                fail_silently=False,
            )
            sent += 1

        if not dry_run:
            self.stdout.write(self.style.SUCCESS(f"Digest caporeparto inviato a {sent} destinatari."))
