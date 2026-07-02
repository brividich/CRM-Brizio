"""Comando F6b-2: deposita (o simula) il composito controllato sulla share per una Specifica.

DRY-RUN di default (mostra la forma corrente e il target senza scrivere). ``--apply`` per scrivere
davvero (richiede owner-password nel .env + permesso di Modifica sulla share). Serve a provare il
deposito su UNA specifica prima di attivare l'aggancio automatico.
"""
from django.core.management.base import BaseCommand, CommandError

from gestione_specifiche.composito_deposito import deposita
from gestione_specifiche.models import Specifica


class Command(BaseCommand):
    help = "Deposita il composito controllato sulla share per una specifica (dry-run di default)."

    def add_arguments(self, parser):
        parser.add_argument("spec", help="pk numerico oppure codice della specifica")
        parser.add_argument("--cartella", default=None,
                            help="cartella share di destinazione ESISTENTE (default: quella del file collegato)")
        parser.add_argument("--apply", action="store_true", help="esegue il deposito (default: dry-run)")

    def handle(self, *args, **opts):
        ident = str(opts["spec"]).strip()
        spec = Specifica.objects.filter(pk=int(ident)).first() if ident.isdigit() else None
        if spec is None:
            spec = Specifica.objects.filter(codice=ident).first()
        if spec is None:
            raise CommandError(f"Specifica non trovata: {ident}")

        piano = deposita(spec, cartella=opts["cartella"], dry_run=not opts["apply"])
        modo = "APPLY" if opts["apply"] else "DRY-RUN"
        self.stdout.write(f"[{modo}] specifica {spec.pk} {spec.codice} REV.{spec.revisione or '-'}")
        for riga in piano.descrizione():
            self.stdout.write(riga)
        if not opts["apply"] and piano.esito == "ok":
            self.stdout.write("  (dry-run: nessuna scrittura. Rilancia con --apply per depositare.)")
