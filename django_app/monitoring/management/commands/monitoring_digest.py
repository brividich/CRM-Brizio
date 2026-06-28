from django.core.management.base import BaseCommand

from monitoring.digest import build_system_digest, render_system_digest


class Command(BaseCommand):
    help = "Digest 'stato portale' (servizi/AI/automazioni/issue) su stdout; --email per inviarlo agli admin."

    def add_arguments(self, parser):
        parser.add_argument("--email", action="store_true",
                            help="Invia il digest via email agli admin del monitoring.")

    def handle(self, *args, **options):
        digest = build_system_digest()
        _subject, body = render_system_digest(digest)
        self.stdout.write(body)

        if options.get("email"):
            from monitoring.tasks import run_system_digest

            result = run_system_digest()
            if result.get("sent"):
                self.stdout.write(self.style.SUCCESS("\nDigest inviato via email agli admin."))
            else:
                self.stdout.write(self.style.WARNING(
                    "\nDigest NON inviato (nessun destinatario o invio disattivato)."
                ))
