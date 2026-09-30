"""Carica la planimetria (PDF vettoriale) di un tipo di verifica periodica.

    manage.py import_periodic_layout "Verifica illuminazione di emergenza" planimetria.pdf \\
        --exclude "465.6,975.5,813.7,1136.3"            # prova a vuoto: punti trovati
    ... --apply                                          # crea la nuova versione attiva

Stessa operazione del riquadro «Planimetria» nella pagina della verifica. I punti
si riconoscono dal riquadro rosso con la X e dal numero rosso accanto. ``--exclude``
(ripetibile) copre sul foglio una zona della planimetria, es. il vecchio cartiglio
«non funzionanti / bassa autonomia», che resta anche fuori dalla lettura.
"""
from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from assets.models import PeriodicCheckType
from assets.services import periodic_checks as checks
from assets.services import periodic_layout


class Command(BaseCommand):
    help = "Carica la planimetria di un tipo di verifica periodica (default: prova a vuoto)."

    def add_arguments(self, parser):
        parser.add_argument("check_type", help="Nome o id del tipo di verifica.")
        parser.add_argument("pdf", help="Planimetria in PDF vettoriale.")
        parser.add_argument("--exclude", action="append", default=[], help="Zona da coprire: x0,y0,x1,y1 (punti PDF).")
        parser.add_argument("--apply", action="store_true", help="Scrive davvero.")

    def handle(self, *args, **options):
        ref = options["check_type"]
        qs = PeriodicCheckType.objects.filter(pk=int(ref)) if ref.isdigit() else PeriodicCheckType.objects.filter(name=ref)
        check_type = qs.first()
        if check_type is None:
            raise CommandError(f"Tipo di verifica non trovato: {ref}")
        path = Path(options["pdf"])
        if not path.is_file():
            raise CommandError(f"File non trovato: {path}")
        try:
            areas = [[float(v) for v in item.split(",")] for item in options["exclude"]]
        except ValueError as exc:
            raise CommandError("--exclude vuole quattro numeri separati da virgola") from exc
        if any(len(a) != 4 for a in areas):
            raise CommandError("--exclude vuole quattro numeri separati da virgola")
        data = path.read_bytes()
        points = periodic_layout.extract_points(data)
        self.stdout.write(f"{check_type.name}: {len(points)} punti ({', '.join(p['code'] for p in points)})")
        if not options["apply"]:
            self.stdout.write(self.style.SUCCESS("Prova a vuoto: nulla e' stato scritto (usa --apply)."))
            return
        try:
            layout = checks.create_layout(check_type, data, name=path.name, exclude_areas=areas)
        except checks.LayoutError as exc:
            raise CommandError(str(exc)) from exc
        if check_type.method != PeriodicCheckType.METHOD_LAYOUT:
            check_type.method = PeriodicCheckType.METHOD_LAYOUT
            check_type.save(update_fields=["method", "updated_at"])
        self.stdout.write(self.style.SUCCESS(f"Planimetria v{layout.version} attiva con {layout.points.count()} punti."))
