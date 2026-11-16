"""Riallinea il nome dei KICK-OFF all'oggetto «Cliente · P/N rev. X · Descrizione pezzo».

I nomi nati dalla vecchia proposta automatica («KICK-OFF 12», «Cliente · P/N ·
KICK-OFF 12») portano un progressivo che non dice niente. La migrazione 0070 li
ha gia' riallineati; il comando resta per i casi successivi e ricompone il nome
con `Project.default_name()`.

Tocca SOLO i nomi che sono ancora una proposta automatica (`Project.nome_automatico`,
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
    help = "Rinomina i KICK-OFF con nome automatico come «Cliente · P/N rev. X · Descrizione pezzo» (default: dry-run)."

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

        saltati_manuali = 0
        gia_allineati = 0
        da_scrivere: list[tuple[int, str]] = []

        # La lettura si chiude PRIMA di scrivere: con `.iterator()` il cursore
        # resta aperto e SQL Server via ODBC rifiuta l'UPDATE sulla stessa
        # connessione (HY010, «errore nella sequenza della funzione»). I kickoff
        # sono poche decine: tenerli in memoria non costa niente.
        for project in list(Project.objects.order_by("kickoff_number", "pk")):
            nome_attuale = (project.name or "").strip()
            automatico = project.nome_automatico(nome_attuale)
            if not automatico and not anche_personalizzati:
                saltati_manuali += 1
                continue

            nuovo = project.default_name()
            if nuovo == nome_attuale:
                gia_allineati += 1
                continue

            self.stdout.write(f"  #{project.pk}: «{nome_attuale}» -> «{nuovo}»")
            da_scrivere.append((project.pk, nuovo))

        rinominati = len(da_scrivere)
        if apply_changes and da_scrivere:
            # Tutto o niente: una rinomina a meta' lascerebbe l'elenco incoerente
            # e il dry-run successivo non direbbe piu' da dove si era rimasti.
            with transaction.atomic():
                for pk, nuovo in da_scrivere:
                    Project.objects.filter(pk=pk).update(name=nuovo)

        self.stdout.write("")
        self.stdout.write(f"Da rinominare: {rinominati}")
        self.stdout.write(f"Gia' allineati: {gia_allineati}")
        self.stdout.write(f"Con nome personalizzato, non toccati: {saltati_manuali}")
        if rinominati and not apply_changes:
            self.stdout.write(self.style.WARNING("Dry-run: rilancia con --apply per scrivere."))
        elif apply_changes:
            self.stdout.write(self.style.SUCCESS("Nomi aggiornati."))
