"""Riallinea i piani di manutenzione allo scadenziario X-MINE.

Di default e' un DRY-RUN: calcola e stampa cosa cambierebbe, senza scrivere
(gira anche col profilo di sola lettura sulla produzione). Scrive solo con
``--applica``, in un'unica transazione.

    python manage.py riallinea_manutenzioni_xmine "SCADENZE X-MINE.xls" --report riallineamento.xlsx
    python manage.py riallinea_manutenzioni_xmine "SCADENZE X-MINE.xls" --mappa mappa.csv --applica

Mappatura manuale (CSV ``centro;macchina;asset_tag``) per le macchine che il
numero interno non abbina in modo univoco: le trovi nel foglio «Abbinamenti
macchine» del report.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from assets.services import xmine_alignment as xa


class Command(BaseCommand):
    help = "Riallinea i piani di manutenzione per singolo asset dallo scadenziario X-MINE (dry-run di default)."

    def add_arguments(self, parser):
        parser.add_argument("file", help="Export «SCADENZE X-MINE» (.xls o .xlsx)")
        parser.add_argument("--mappa", help="CSV centro;macchina;asset_tag per gli abbinamenti manuali")
        parser.add_argument("--report", help="Scrive il dettaglio in un file Excel")
        parser.add_argument(
            "--codici-a",
            default=",".join(sorted(xa.DEFAULT_A_CODES)),
            help="Codici test A* da includere (default: A16). Gli altri A* restano fuori.",
        )
        parser.add_argument("--applica", action="store_true", help="Esegue davvero le modifiche (senza: dry-run)")
        parser.add_argument(
            "--genera",
            action="store_true",
            help="Dopo --applica genera subito le scadenze entrate nel preavviso (altrimenti lo fa lo scheduler).",
        )

    def handle(self, *args, **options):
        try:
            rows = xa.read_xmine(options["file"])
            mapping = xa.read_mapping(options.get("mappa"))
        except (xa.XmineFileError, OSError) as exc:
            raise CommandError(str(exc)) from exc
        a_codes = frozenset(code.strip().upper() for code in (options["codici_a"] or "").split(",") if code.strip())

        plan = xa.build_plan(rows, mapping=mapping, a_codes=a_codes)
        mode = "APPLICAZIONE" if options["applica"] else "DRY-RUN (nessuna modifica)"
        self.stdout.write(self.style.MIGRATE_HEADING(f"Riallineamento X-MINE — {mode}"))
        for key, value in plan.summary().items():
            self.stdout.write(f"  {key}: {value}")

        problems = [m for m in plan.matches.values() if m.problem]
        if problems:
            self.stdout.write(self.style.WARNING(f"\nMacchine non abbinate ({len(problems)}):"))
            for m in sorted(problems, key=lambda m: (m.center, m.machine)):
                self.stdout.write(f"  {m.center}/{m.machine} {m.label} -> {m.problem}")

        if options.get("report"):
            path = xa.write_report(plan, options["report"])
            self.stdout.write(self.style.SUCCESS(f"\nReport: {path}"))

        if not options["applica"]:
            self.stdout.write(self.style.NOTICE("\nDry-run: nessuna modifica. Rilancia con --applica per eseguire."))
            return

        counts = xa.apply_plan(plan)
        self.stdout.write(self.style.SUCCESS("\nApplicato:"))
        for key, value in sorted(counts.items()):
            self.stdout.write(f"  {key}: {value}")
        if options["genera"]:
            from assets.services.maintenance_domain import generate_occurrences

            result = generate_occurrences(plan_ids={pair.plan.id for pair in plan.pairs})
            self.stdout.write(f"  scadenze generate: {result['created']}")
