"""Elabora a mano la cartella di acquisizione dei fogli firme.

Lo stesso lavoro che gira ogni 5 minuti, lanciabile dal server: serve a provare
la configurazione appena impostata (la share si raggiunge? l'utente del servizio
ci arriva?) senza aspettare il giro successivo, e a smaltire un arretrato.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Legge le scansioni dei fogli firme depositate nella cartella di acquisizione."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limite", type=int, default=None,
            help="Quanti file elaborare al massimo (default: quello configurato).",
        )
        parser.add_argument(
            "--forza", action="store_true",
            help="Elabora anche se l'acquisizione risulta spenta nelle impostazioni.",
        )

    def handle(self, *args, **opzioni):
        from anagrafica.models_formazione import TrainingScanIntakeConfig
        from anagrafica.services.intake_scansioni import elabora_cartella

        config = TrainingScanIntakeConfig.load()
        if not config.attiva and not opzioni["forza"]:
            self.stdout.write(self.style.WARNING(
                "Acquisizione spenta nelle impostazioni. Usa --forza per elaborare comunque."
            ))
            return

        if not config.attiva:
            config.attiva = True  # solo in memoria: non tocca le impostazioni

        self.stdout.write(f"Cartella: {config.cartella or '(non configurata)'}")
        esito = elabora_cartella(config, limite=opzioni["limite"])

        for riga in esito.get("dettagli") or []:
            self.stdout.write(f"  {riga}")

        riepilogo = esito.get("riepilogo") or ""
        stile = self.style.SUCCESS if esito.get("letti") else self.style.WARNING
        self.stdout.write(stile(riepilogo))

        if esito.get("presenze_scritte"):
            self.stdout.write(self.style.SUCCESS(
                f"Presenze registrate automaticamente: {esito['presenze_scritte']}"
            ))
