"""Riallinea il nome dei KICK-OFF storici allo schema «Cliente · P/N · KICK-OFF n».

I progetti creati prima della proposta automatica si chiamano «KICK-OFF 12»:
negli elenchi e negli oggetti delle email non dicono di chi sia la commessa.
Il comando ricompone quel nome con `Project.default_name()`.

Tocca SOLO i nomi che sono ancora la vecchia proposta automatica («KICK-OFF n»,
eventualmente vuota): un nome scritto a mano e' una decisione di qualcuno e resta
dov'e'. Di default non scrive nulla: serve `--apply`.
"""
from __future__ import annotations

import re

from django.core.management.base import BaseCommand
from django.db import transaction

from tasks.models import Project

# «KICK-OFF 12», «kick off 12», «KICKOFF 12»: le varianti nate a mano negli anni.
AUTO_NAME = re.compile(r"^kick[\s_-]*off\s*\d*$", re.IGNORECASE)


class Command(BaseCommand):
    help = "Rinomina i KICK-OFF storici come «Cliente · P/N · KICK-OFF n» (default: dry-run)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Scrive le modifiche. Senza questo flag il comando mostra soltanto cosa farebbe.",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Rinomina anche i progetti con nome personalizzato (sovrascrive scelte fatte a mano).",
        )

    def handle(self, *args, **options):
        apply_changes = bool(options["apply"])
        anche_personalizzati = bool(options["all"])

        rinominati = 0
        saltati_manuali = 0
        gia_allineati = 0

        for project in Project.objects.order_by("kickoff_number", "pk").iterator():
            nome_attuale = (project.name or "").strip()
            automatico = not nome_attuale or bool(AUTO_NAME.match(nome_attuale))
            if not automatico and not anche_personalizzati:
                saltati_manuali += 1
                continue

            nuovo = project.default_name()
            if nuovo == nome_attuale:
                gia_allineati += 1
                continue

            self.stdout.write(f"  #{project.pk}: «{nome_attuale}» -> «{nuovo}»")
            rinominati += 1
            if apply_changes:
                with transaction.atomic():
                    Project.objects.filter(pk=project.pk).update(name=nuovo)

        self.stdout.write("")
        self.stdout.write(f"Da rinominare: {rinominati}")
        self.stdout.write(f"Gia' allineati: {gia_allineati}")
        self.stdout.write(f"Con nome personalizzato, non toccati: {saltati_manuali}")
        if rinominati and not apply_changes:
            self.stdout.write(self.style.WARNING("Dry-run: rilancia con --apply per scrivere."))
        elif apply_changes:
            self.stdout.write(self.style.SUCCESS("Nomi aggiornati."))
