"""Unisce gli alert doppi già aperti: uno per mail invece che uno per PC o job, e CVE doppie fra mail e inventario.

Senza ``--apply`` mostra soltanto cosa farebbe. Con ``--rinomina-fonte "VECCHIO" "NUOVO"`` cambia il nome
di una fonte mail (la fonte del SOC e la casella che la alimenta), così alert vecchi e nuovi restano insieme.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from security.services import alert_doppioni


class Command(BaseCommand):
    help = "Unisce gli alert doppi aperti (stesso PC o job, CVE già seguita dall'inventario). Senza --apply è una prova."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Applica (senza: mostra soltanto)")
        parser.add_argument("--rinomina-fonte", nargs=2, metavar=("VECCHIO", "NUOVO"),
                            help="Rinomina una fonte mail del SOC e la sua casella")

    def handle(self, *args, apply=False, rinomina_fonte=None, **opts):
        prova = "" if apply else "[PROVA] "
        gruppi = alert_doppioni.unisci_doppioni(apply=apply)
        uniti = sum(len(g["uniti"]) for g in gruppi)
        self.stdout.write(f"{prova}Alert per PC/job: {len(gruppi)} gruppi, {uniti} alert {'uniti' if apply else 'da unire'}.")
        for g in sorted(gruppi, key=lambda g: -len(g["uniti"]))[:30]:
            self.stdout.write(f"  #{g['tenuto']} {g['titolo'][:90]}  <- {len(g['uniti'])} doppioni")
        cve = alert_doppioni.chiudi_cve_doppie(apply=apply)
        self.stdout.write(f"{prova}CVE della mail Defender già seguite dall'inventario: {len(cve)} alert "
                          f"{'chiusi come doppioni' if apply else 'da chiudere come doppioni'}.")
        for c in cve[:20]:
            self.stdout.write(f"  #{c['alert']} {c['cve']} ({c['inventario']} alert dell'inventario)")
        if rinomina_fonte:
            self._rinomina(*rinomina_fonte, apply=apply)

    def _rinomina(self, vecchio, nuovo, apply):
        from security.models import SecurityMailboxSource, SecuritySource

        fonte = SecuritySource.objects.filter(name=vecchio).first()
        if fonte is None:
            raise CommandError(f"Nessuna fonte «{vecchio}».")
        if SecuritySource.objects.filter(name=nuovo).exclude(pk=fonte.pk).exists():
            raise CommandError(f"Esiste già una fonte «{nuovo}».")
        caselle = SecurityMailboxSource.objects.filter(name=vecchio)
        self.stdout.write(f"{'' if apply else '[PROVA] '}Fonte «{vecchio}» -> «{nuovo}» ({caselle.count()} casella/e).")
        if apply:
            with transaction.atomic():
                fonte.name = nuovo
                fonte.save(update_fields=["name"])
                caselle.update(name=nuovo)
