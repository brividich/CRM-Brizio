from django.core.management.base import BaseCommand, CommandError

from security.services.autoconfig import (
    SECTION_KEYS,
    apply_autoconfig,
    plan_autoconfig,
    reset_sections,
)


class Command(BaseCommand):
    """Wrapper CLI dell'autoconfig.

    I default vivono in ``security.services.autoconfig``, condivisi con la
    pagina /soc/admin/autoconfig/: una sola fonte per shell e interfaccia.
    """

    help = "Seed persistent Security Center AI admin configuration defaults."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--reset", action="store_true")
        parser.add_argument("--only", choices=SECTION_KEYS)
        parser.add_argument(
            "--no-overwrite",
            action="store_true",
            help="Crea solo cio' che manca, senza riallineare ai default i record esistenti.",
        )

    def handle(self, *args, **options):
        sections = [options["only"]] if options.get("only") else None
        try:
            if options["dry_run"]:
                for row in plan_autoconfig(sections):
                    self.stdout.write(
                        f"{row['key']}: {len(row['to_create'])} da creare, "
                        f"{len(row['to_align'])} difformi dai default, {len(row['aligned'])} allineati"
                    )
                return
            if options["reset"]:
                deleted = reset_sections(sections)
                self.stdout.write(f"reset: {deleted} righe eliminate")
            result = apply_autoconfig(sections, overwrite=not options["no_overwrite"])
        except ValueError as exc:
            raise CommandError(str(exc))
        for row in result["sections"]:
            self.stdout.write(
                f"{row['key']}: {len(row['created'])} creati, {len(row['updated'])} riallineati, "
                f"{len(row['skipped'])} lasciati invariati"
            )
