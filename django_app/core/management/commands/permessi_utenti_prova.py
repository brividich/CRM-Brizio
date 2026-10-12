"""Un utente di prova per ogni ruolo preset, per i controlli manuali prima di un rilascio.

    python manage.py permessi_utenti_prova --password <pwd> [--elimina]

Crea ``prova.<ruolo>`` (utente legacy + utente Django + appartenenza al ruolo).
Rifiuta di girare con DEBUG spento: gli utenti di prova non devono esistere in
produzione. Dati sintetici, nessuna persona reale.
"""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

PREFISSO = "prova."
DOMINIO = "example.local"


class Command(BaseCommand):
    help = "Crea (o elimina) un utente di prova per ogni ruolo preset. Solo sviluppo/test."

    def add_arguments(self, parser):
        parser.add_argument("--password", default="", help="Password degli utenti di prova.")
        parser.add_argument("--elimina", action="store_true", help="Elimina gli utenti di prova.")
        parser.add_argument("--forza", action="store_true", help="Consente l'esecuzione con DEBUG spento (UAT).")

    def handle(self, *args, **opts):
        if not settings.DEBUG and not opts["forza"]:
            raise CommandError("DEBUG spento: gli utenti di prova non si creano in produzione (usa --forza solo in UAT).")

        from django.contrib.auth import get_user_model

        from core.legacy_models import Ruolo, UtenteLegacy
        from core.legacy_utils import sync_django_user_from_legacy
        from core.models import AccessGroup, AccessGroupMembership
        from core.permessi.cache import invalida_permessi
        from core.permessi.preset import PRESETS

        if opts["elimina"]:
            legacy = UtenteLegacy.objects.filter(email__startswith=PREFISSO)
            ids = list(legacy.values_list("id", flat=True))
            AccessGroupMembership.objects.filter(legacy_user_id__in=ids).delete()
            get_user_model().objects.filter(profile__legacy_user_id__in=ids).delete()
            legacy.delete()
            invalida_permessi()
            self.stdout.write(f"Eliminati {len(ids)} utenti di prova.")
            return

        if not opts["password"]:
            raise CommandError("Indica --password.")

        ruolo_base = Ruolo.objects.filter(nome__iexact="utente").first()
        for preset in PRESETS:
            gruppo = AccessGroup.objects.filter(code=preset.codice).first()
            if gruppo is None:
                self.stdout.write(self.style.WARNING(f"Ruolo {preset.codice} assente: lancia permessi_ruoli --preset."))
                continue
            email = f"{PREFISSO}{preset.chiave}@{DOMINIO}"
            legacy, _ = UtenteLegacy.objects.get_or_create(
                email=email,
                defaults={
                    "nome": f"Prova {preset.nome}",
                    "password": "*TEST*",
                    "ruolo": "utente",
                    "attivo": True,
                    "deve_cambiare_password": False,
                    "ruolo_id": ruolo_base.id if ruolo_base else None,
                },
            )
            user = sync_django_user_from_legacy(legacy)
            user.set_password(opts["password"])
            user.save()
            if preset.chiave != "dipendente":
                AccessGroupMembership.objects.get_or_create(
                    group=gruppo, legacy_user_id=legacy.id, defaults={"note": "utente di prova"}
                )
            self.stdout.write(f"{user.get_username():<40} -> {preset.nome}")
        invalida_permessi()
