"""Invia promemoria email per contratti a termine e periodi di prova in scadenza.

Pattern speculare a ``send_visite_expiry_reminders``: digest unico ai
destinatari HR (SiteConfig ``contratti_reminder_emails`` → ADMINS → superuser).

Fonti dati:
- ``StoricoContratto``: per ogni dipendente NON cessato viene considerato solo
  l'ultimo contratto (``data_inizio`` più recente). Se ha ``data_fine``
  valorizzata è un contratto a termine: finisce nel digest se la data ricade
  nella finestra ``--days`` (in scadenza) o è già passata (scaduto ma
  dipendente ancora in forza = anomalia da segnalare).
- ``DipendenteAnagraficaAziendale.prova_data_fine``: periodi di prova in
  chiusura entro ``--prova-days`` giorni.
- Fallback censimento: dipendenti attivi con ``tipologia_contratto`` a termine
  ma senza alcun rigo in ``StoricoContratto`` (data fine non determinabile).

La scelta di guardare ``data_fine`` dell'ultimo contratto — e non il testo
libero ``tipologia_contratto`` dello storico (popolato da import CSV) — rende
il criterio indipendente dalle sigle usate nei file paga.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from anagrafica.models import DipendenteAnagraficaAziendale, StoricoContratto
from anagrafica.services.email_digest import digest_fragment, scadenza_badge
from anagrafica.services.reminders import get_reminder_recipients

# Tipologie dell'anagrafica aziendale considerate "a termine" per il fallback
# senza storico contrattuale importato.
TIPOLOGIE_A_TERMINE = (
    DipendenteAnagraficaAziendale.CONTRATTO_DETERMINATO,
    DipendenteAnagraficaAziendale.CONTRATTO_APPRENDISTATO,
    DipendenteAnagraficaAziendale.CONTRATTO_SOMMINISTRAZIONE,
    DipendenteAnagraficaAziendale.CONTRATTO_COLLABORAZIONE,
    DipendenteAnagraficaAziendale.CONTRATTO_STAGE,
)

CONFIG_KEY = "contratti_reminder_emails"


def _nomi_dipendenti() -> dict[int, str]:
    """Mappa legacy_id → nominativo dal DB legacy; vuota se non raggiungibile."""
    try:
        from core.legacy_anagrafica import fetch_anagrafica_rows
        rows = fetch_anagrafica_rows(deduplicate=True)
        return {
            int(r["id"]): f"{r.get('cognome', '') or ''} {r.get('nome', '') or ''}".strip()
            for r in rows
            if r.get("id")
        }
    except Exception:
        return {}


class Command(BaseCommand):
    help = "Digest email dei contratti a termine e periodi di prova in scadenza."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days", type=int, default=60,
            help="Giorni di anticipo per contratti in scadenza (default: 60).",
        )
        parser.add_argument(
            "--prova-days", type=int, default=15,
            help="Giorni di anticipo per fine periodo di prova (default: 15).",
        )
        parser.add_argument(
            "--recipients", nargs="*",
            help="Email destinatari (sovrascrive SiteConfig/ADMINS).",
        )
        parser.add_argument("--dry-run", action="store_true", help="Stampa senza inviare email.")

    def handle(self, *args, **options):
        today = timezone.localdate()
        days = max(1, int(options.get("days") or 60))
        prova_days = max(1, int(options.get("prova_days") or 15))
        dry_run = bool(options.get("dry_run"))
        recipients = get_reminder_recipients(CONFIG_KEY, options.get("recipients") or [])

        soglia_contratti = today + timedelta(days=days)
        soglia_prova = today + timedelta(days=prova_days)

        attivi = {
            az.legacy_anagrafica_id: az
            for az in DipendenteAnagraficaAziendale.objects.filter(data_cessazione__isnull=True)
        }
        nomi = _nomi_dipendenti()

        def label(legacy_id: int) -> str:
            nome = nomi.get(legacy_id, "")
            return f"{nome} (#{legacy_id})" if nome else f"dipendente #{legacy_id}"

        # ── Ultimo contratto per dipendente attivo ──────────────────────────
        ultimo_per_dip: dict[int, StoricoContratto] = {}
        contratti = (
            StoricoContratto.objects
            .filter(legacy_anagrafica_id__in=attivi.keys())
            .order_by("legacy_anagrafica_id", "-data_inizio", "-created_at")
        )
        for c in contratti:
            ultimo_per_dip.setdefault(c.legacy_anagrafica_id, c)

        scaduti: list[tuple[int, StoricoContratto]] = []
        in_scadenza: list[tuple[int, StoricoContratto]] = []
        for legacy_id, contratto in sorted(ultimo_per_dip.items()):
            if contratto.data_fine is None:
                continue  # contratto in corso senza termine (indeterminato)
            if contratto.data_fine < today:
                scaduti.append((legacy_id, contratto))
            elif contratto.data_fine <= soglia_contratti:
                in_scadenza.append((legacy_id, contratto))

        # ── Periodi di prova in chiusura ────────────────────────────────────
        prove: list[tuple[int, DipendenteAnagraficaAziendale]] = [
            (legacy_id, az)
            for legacy_id, az in sorted(attivi.items())
            if az.prova_data_fine and today <= az.prova_data_fine <= soglia_prova
        ]

        # ── Fallback: tipologia a termine senza storico contrattuale ────────
        senza_storico: list[tuple[int, DipendenteAnagraficaAziendale]] = [
            (legacy_id, az)
            for legacy_id, az in sorted(attivi.items())
            if az.tipologia_contratto in TIPOLOGIE_A_TERMINE and legacy_id not in ultimo_per_dip
        ]

        if not scaduti and not in_scadenza and not prove and not senza_storico:
            self.stdout.write("Nessun contratto o periodo di prova in scadenza.")
            return

        tipologie_labels = dict(DipendenteAnagraficaAziendale.CONTRATTO_CHOICES)
        lines = [
            f"NOVICROM HUB - Promemoria contratti e periodi di prova del {today:%d-%m-%Y}",
            "=" * 60,
            "",
        ]

        if scaduti:
            lines.append(f"CONTRATTI SCADUTI con dipendente ancora in forza ({len(scaduti)}):")
            for legacy_id, c in scaduti:
                days_over = (today - c.data_fine).days
                tip = c.tipologia_contratto or "tipologia n/d"
                lines.append(
                    f"  [{days_over}gg fa] {label(legacy_id)} - {tip}"
                    f" - scaduto il {c.data_fine:%d-%m-%Y} (verificare rinnovo/cessazione)"
                )
            lines.append("")

        if in_scadenza:
            lines.append(f"CONTRATTI IN SCADENZA entro {days} giorni ({len(in_scadenza)}):")
            for legacy_id, c in in_scadenza:
                days_left = (c.data_fine - today).days
                tip = c.tipologia_contratto or "tipologia n/d"
                lines.append(
                    f"  [{days_left}gg] {label(legacy_id)} - {tip}"
                    f" - scadenza {c.data_fine:%d-%m-%Y}"
                )
            lines.append("")

        if prove:
            lines.append(f"PERIODI DI PROVA in chiusura entro {prova_days} giorni ({len(prove)}):")
            for legacy_id, az in prove:
                days_left = (az.prova_data_fine - today).days
                lines.append(
                    f"  [{days_left}gg] {label(legacy_id)}"
                    f" - fine prova {az.prova_data_fine:%d-%m-%Y}"
                )
            lines.append("")

        if senza_storico:
            lines.append(
                f"CONTRATTI A TERMINE SENZA STORICO IMPORTATO ({len(senza_storico)})"
                " - data fine non determinabile:"
            )
            for legacy_id, az in senza_storico:
                tip = tipologie_labels.get(az.tipologia_contratto, az.tipologia_contratto)
                lines.append(f"  {label(legacy_id)} - {tip}")
            lines.append("")

        body = "\n".join(lines)
        subject = (
            f"[CONTRATTI] {len(scaduti)} scaduti + {len(in_scadenza)} in scadenza"
            f" + {len(prove)} fine prova - {today:%d-%m-%Y}"
        )

        if dry_run:
            self.stdout.write(self.style.WARNING("[DRY-RUN] Nessuna email inviata."))
            self.stdout.write(f"Destinatari: {recipients}")
            self.stdout.write(body)
            return

        if not recipients:
            self.stdout.write(self.style.ERROR(
                f"Nessun destinatario configurato (SiteConfig '{CONFIG_KEY}' / ADMINS vuoti)."
            ))
            return

        scaduti_cards = [{
            "title": label(legacy_id),
            "subtitle": (c.tipologia_contratto or "tipologia n/d"),
            "badge": scadenza_badge((today - c.data_fine).days, scaduto=True, label_scaduto="Scaduto"),
            "note": f"Scaduto il {c.data_fine:%d-%m-%Y} — verificare rinnovo/cessazione",
            "accent": "#dc2626",
        } for legacy_id, c in scaduti]
        inscad_cards = [{
            "title": label(legacy_id),
            "subtitle": (c.tipologia_contratto or "tipologia n/d"),
            "badge": scadenza_badge((c.data_fine - today).days),
            "note": f"Scadenza {c.data_fine:%d-%m-%Y}",
            "accent": "#f59e0b",
        } for legacy_id, c in in_scadenza]
        prove_cards = [{
            "title": label(legacy_id),
            "subtitle": "Periodo di prova",
            "badge": scadenza_badge((az.prova_data_fine - today).days, label_scadenza="Fine prova"),
            "note": f"Fine prova {az.prova_data_fine:%d-%m-%Y}",
            "accent": "#f59e0b",
        } for legacy_id, az in prove]
        senza_cards = [{
            "title": label(legacy_id),
            "subtitle": tipologie_labels.get(az.tipologia_contratto, az.tipologia_contratto),
            "badge": ("Data fine n/d", "neutral"),
            "note": "Contratto a termine senza storico importato",
            "accent": "#64748b",
        } for legacy_id, az in senza_storico]
        fragment = digest_fragment([
            (f"Contratti scaduti, dipendente in forza ({len(scaduti)})", scaduti_cards),
            (f"Contratti in scadenza entro {days} giorni ({len(in_scadenza)})", inscad_cards),
            (f"Periodi di prova in chiusura entro {prova_days} giorni ({len(prove)})", prove_cards),
            (f"Contratti a termine senza storico ({len(senza_storico)})", senza_cards),
        ])
        from core.email_utils import send_hub_mail
        send_hub_mail(
            subject, body, recipients,
            email_type="Anagrafica HR",
            section_label="Reminder contratti e periodi di prova",
            body_html_fragment=fragment,
            fail_silently=False,
        )
        self.stdout.write(self.style.SUCCESS(
            f"Email inviata a {len(recipients)} destinatari."
            f" Scaduti={len(scaduti)} In_scadenza={len(in_scadenza)}"
            f" Prove={len(prove)} Senza_storico={len(senza_storico)}"
        ))
