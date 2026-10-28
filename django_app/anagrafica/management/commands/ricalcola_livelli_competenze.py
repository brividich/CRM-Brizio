"""Riallinea i livelli sulle mansioni con competenze (gira anche dopo ogni salvataggio e ogni notte).

    python manage.py ricalcola_livelli_competenze               # prova: elenca, non scrive
    python manage.py ricalcola_livelli_competenze --applica
    python manage.py ricalcola_livelli_competenze --legacy-id 42 --applica
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Ricalcola il livello sulle mansioni con competenze (requisiti, regole, scadenze)."

    def add_arguments(self, parser):
        parser.add_argument("--applica", action="store_true", help="Scrive i cambi (senza: solo prova).")
        parser.add_argument("--legacy-id", dest="legacy_ids", type=int, action="append",
                            help="Solo questa persona (ripetibile).")

    def handle(self, *args, **options):
        from anagrafica.services.competenze_ricalcolo import ricalcola

        esito = ricalcola(options["legacy_ids"], motivo="comando ricalcola_livelli_competenze",
                          applica=options["applica"])
        for lid, mansione, prima, dopo in esito["cambi"]:
            self.stdout.write(f"  #{lid} {mansione}: {prima or '—'} → {dopo}")
        verbo = "riallineati" if options["applica"] else "da riallineare (prova, niente scritto)"
        self.stdout.write(self.style.SUCCESS(
            f"{esito['valutate']} abilitazioni valutate, {esito['cambiate']} livelli {verbo}."))
