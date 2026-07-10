from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from anagrafica.models import Fornitore


# Ditte esterne dedotte dalle descrizioni dello storico collaudo (nomi tra parentesi
# associati a verifiche/manutenzioni/impianti). NON persone: i nominativi con iniziale
# di nome (corsi/qualifiche/sanitario) sono esclusi. Da verificare/completare a mano.
DEFAULT_NAMES = [
    "Bruschi",       # impianti elettrici (differenziali, quadri, illuminazione, antintrusione)
    "Zega",          # sicurezza / formazione (accordo stato-regioni, rumore, preposti)
    "Becherini",     # taratura strumenti (calibrazione)
    "Lattanzi",      # formazione antincendio / primo soccorso
    "Gruppo Lupi",   # antincendio (rete idrica)
    "Possenti",      # intercettazione gas
    "Filidei",       # gas fluorurati (F-gas) macchine officina
    "Demag",         # verifiche di sollevamento (carriponte, paranchi)
    "Omis",          # sollevamento
]


class Command(BaseCommand):
    help = (
        "Crea in anagrafica i Fornitore di manutenzione dedotti dallo storico collaudo "
        "(categoria MANUTENZIONE). Dry-run di default, idempotente sul nome (case-insensitive). "
        "Usa --names per una lista personalizzata."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--names",
            default="",
            help="Ragioni sociali separate da virgola (default: elenco dedotto dallo storico).",
        )
        parser.add_argument(
            "--categoria",
            default=Fornitore.CATEGORIA_MANUTENZIONE,
            help="Categoria fornitore (default: MANUTENZIONE).",
        )
        parser.add_argument(
            "--note",
            default="Importato dallo storico manutenzioni collaudo — verificare/completare dati.",
            help="Nota apposta ai fornitori creati.",
        )
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--dry-run", action="store_true", help="Simula senza scrivere.")
        mode.add_argument("--commit", action="store_true", help="Esegue in transaction.atomic().")

    def handle(self, *args, **options):
        dry_run = bool(options.get("dry_run"))
        raw = str(options.get("names") or "").strip()
        names = [n.strip() for n in raw.split(",") if n.strip()] if raw else list(DEFAULT_NAMES)
        categoria = str(options.get("categoria") or "").strip().upper()
        valid_cat = {code for code, _ in Fornitore.CATEGORIA_CHOICES}
        if categoria and categoria not in valid_cat:
            categoria = Fornitore.CATEGORIA_MANUTENZIONE
        note = str(options.get("note") or "")

        created = 0
        skipped = 0
        report: list[str] = []

        def _apply():
            nonlocal created, skipped
            for name in names:
                # Idempotenza fuzzy: salta se esiste già un fornitore con lo stesso nome
                # O che lo contiene (es. "Bruschi" ⊂ "Bruschi di Pino Florio"), per non duplicare.
                existing = Fornitore.objects.filter(
                    Q(ragione_sociale__iexact=name) | Q(ragione_sociale__icontains=name)
                ).first()
                if existing is not None:
                    skipped += 1
                    report.append(f"  = già presente: [{existing.id}] {existing.ragione_sociale}")
                    continue
                if not dry_run:
                    Fornitore.objects.create(
                        ragione_sociale=name,
                        categoria=categoria,
                        note=note,
                        is_active=True,
                    )
                created += 1
                report.append(f"  + creato: {name} (categoria {categoria or '—'})")

        if dry_run:
            _apply()
        else:
            with transaction.atomic():
                _apply()

        self.stdout.write(f"Modalità: {'DRY-RUN' if dry_run else 'COMMIT'}")
        self.stdout.write(f"Nomi: {len(names)} | creati: {created} | già presenti: {skipped}")
        for line in report:
            self.stdout.write(line)
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY-RUN: nessun fornitore creato."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Creati {created} fornitori."))
