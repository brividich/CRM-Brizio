"""Porta nel portale lo storico delle verifiche periodiche archiviato su share.

    manage.py import_periodic_checks "\\\\novisrv\\privman"            # prova a vuoto
    manage.py import_periodic_checks "\\\\novisrv\\privman" --apply    # scrive

La radice e' la cartella che contiene ``_Impianto Elettrico``, ``_Antincendio``...;
la mappa cartella -> tipo di verifica e' nel catalogo
(``assets/services/periodic_checks_catalog.py``). Prima lanciare
``seed_periodic_checks --apply``: i tipi devono esistere.

Ogni verifica importata e' confermata, con esito «Da documento (storico)», i
documenti come allegati (storage privato cifrato) e nelle note la precisione della
data e i percorsi d'origine. Ripetibile: le verifiche gia' importate si saltano.
Alla fine la prossima scadenza di ogni tipo e' ricalcolata dall'ultima verifica.
"""
from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from assets.models import PeriodicCheckType
from assets.services import periodic_checks_import as importer
from assets.services.periodic_checks_catalog import CATALOG


class Command(BaseCommand):
    help = "Importa lo storico delle verifiche periodiche dall'archivio (default: prova a vuoto)."

    def add_arguments(self, parser):
        parser.add_argument("root", help="Radice dell'archivio (es. \\\\novisrv\\privman).")
        parser.add_argument("--apply", action="store_true", help="Scrive davvero (senza: solo elenco).")
        parser.add_argument("--show-skipped", action="store_true", help="Elenca anche i file scartati.")

    def handle(self, *args, **options):
        root = Path(options["root"])
        if not root.is_dir():
            raise CommandError(f"Cartella non raggiungibile: {root}")
        report = importer.scan(root, CATALOG)

        for folder in report.missing_folders:
            self.stdout.write(self.style.WARNING(f"! cartella mancante: {folder}"))
        current = None
        for planned in report.sessions:
            label = f"{planned.catalog.system} / {planned.catalog.name}"
            if label != current:
                self.stdout.write(f"\n{label}")
                current = label
            names = ", ".join(p.name for p in planned.files)
            self.stdout.write(f"  {planned.performed_on:%d/%m/%Y} ({planned.precision:6}) {names}")
        self.stdout.write(
            f"\n{len(report.sessions)} verifiche da {sum(len(s.files) for s in report.sessions)} documenti; "
            f"{len(report.skipped)} file scartati."
        )
        if options.get("show_skipped"):
            for path, reason in report.skipped:
                self.stdout.write(f"  - {path.relative_to(root)}: {reason}")

        if not options.get("apply"):
            self.stdout.write(self.style.SUCCESS("Prova a vuoto: nulla e' stato scritto (usa --apply)."))
            return

        types = {
            (t.system.name, t.name): t
            for t in PeriodicCheckType.objects.select_related("system")
        }
        missing = {(s.catalog.system, s.catalog.name) for s in report.sessions} - set(types)
        if missing:
            raise CommandError(
                "Tipi di verifica mancanti (lancia prima seed_periodic_checks --apply): "
                + "; ".join(f"{a} / {b}" for a, b in sorted(missing))
            )
        created, existing = importer.apply(report, types, root=root)
        self.stdout.write(self.style.SUCCESS(f"Importate {created} verifiche ({existing} gia' presenti)."))
