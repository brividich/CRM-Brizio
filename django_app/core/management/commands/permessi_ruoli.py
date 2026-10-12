"""Ruoli del portale da riga di comando: preset, sincronizzazione, riepilogo.

    python manage.py permessi_ruoli --riepilogo
    python manage.py permessi_ruoli --preset [--reset] [--solo hr,preposto]
    python manage.py permessi_ruoli --sincronizza [--dry-run]

``--sincronizza`` traduce la matrice in permessi di pagina (GroupPermissionGrant
con nota «matrice ruoli»). Va rilanciata dopo un deploy che aggiunge pagine
nuove: le rotte nuove ricevono i permessi solo quando la matrice viene
sincronizzata. Senza ``--dry-run`` scrive.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Ruoli del portale: applica i preset, sincronizza la matrice, mostra il riepilogo."

    def add_arguments(self, parser):
        parser.add_argument("--preset", action="store_true", help="Crea i ruoli e le celle dei preset mancanti.")
        parser.add_argument("--reset", action="store_true", help="Con --preset: riporta i ruoli al preset.")
        parser.add_argument("--solo", default="", help="Con --preset: chiavi separate da virgola.")
        parser.add_argument("--sincronizza", action="store_true", help="Matrice -> permessi di pagina.")
        parser.add_argument("--dry-run", action="store_true", help="Con --sincronizza: mostra senza scrivere.")
        parser.add_argument("--riepilogo", action="store_true", help="Ruoli, persone e celle.")

    def handle(self, *args, **opts):
        if not (opts["preset"] or opts["sincronizza"] or opts["riepilogo"]):
            opts["riepilogo"] = True

        if opts["preset"]:
            from core.permessi.preset import applica_preset

            chiavi = [c.strip() for c in opts["solo"].split(",") if c.strip()] or None
            for esito in applica_preset(chiavi=chiavi, reset=opts["reset"]):
                stato = "creato" if esito["creato"] else ("ripristinato" if opts["reset"] else "esistente")
                self.stdout.write(f"{esito['ruolo'].label}: {stato}, celle nuove {esito['celle_create']}")

        if opts["sincronizza"]:
            from core.permessi.sync import sincronizza_tutti

            for esito in sincronizza_tutti(dry_run=opts["dry_run"]):
                self.stdout.write(
                    f"{esito.ruolo}: +{esito.accesi} -{esito.spenti} (invariati {esito.invariati}, "
                    f"governati {esito.governati})"
                )
            if opts["dry_run"]:
                self.stdout.write(self.style.WARNING("Dry-run: nessuna scrittura."))

        if opts["riepilogo"]:
            from core.models import AccessGroup
            from core.permessi.motore import sistema_ruoli_attivo

            self.stdout.write(f"Sistema dei ruoli attivo: {'SI' if sistema_ruoli_attivo() else 'NO'}")
            for ruolo in AccessGroup.objects.all().order_by("-priority", "label"):
                flags = []
                if ruolo.amministratore:
                    flags.append("amministratore")
                if ruolo.vede_tutto:
                    flags.append("vede tutto")
                if not ruolo.is_active:
                    flags.append("disattivo")
                self.stdout.write(
                    f"{ruolo.priority:>5}  {ruolo.label:<40} persone={ruolo.memberships.count():>3} "
                    f"celle={ruolo.permessi_modulo.count():>3} {' '.join(flags)}"
                )
