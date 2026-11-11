"""Sistema gli alert già aperti con le regole di adesso: rumore, doppioni per PC/job/CVE, CVE doppie fra mail e inventario.

1. chiude il rumore (``alert_doppioni.chiudi_rumore``): dispositivi bloccati dalla policy, «oltre il termine» di CVE
   che hanno già l'alert «PC con versione vulnerabile», modifiche di Entra di amministratori fidati;
2. unisce i doppioni: un alert per PC, job (anche i «Retry»), CVE oltre il termine, malware nei backup;
3. chiude come doppioni gli alert della mail Defender su CVE già seguite dall'inventario.

Senza ``--apply`` mostra soltanto cosa farebbe. Con ``--rinomina-fonte "VECCHIO" "NUOVO"`` cambia il nome
di una fonte mail (la fonte del SOC e la casella che la alimenta), così alert vecchi e nuovi restano insieme.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from security.services import alert_doppioni


class Command(BaseCommand):
    help = ("Chiude il rumore e unisce gli alert doppi aperti (PC, job, CVE oltre il termine, CVE già seguita "
            "dall'inventario). Senza --apply è una prova.")

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Applica (senza: mostra soltanto)")
        parser.add_argument("--rinomina-fonte", nargs=2, metavar=("VECCHIO", "NUOVO"),
                            help="Rinomina una fonte mail del SOC e la sua casella")

    def handle(self, *args, apply=False, rinomina_fonte=None, **opts):
        prova = "" if apply else "[PROVA] "
        rumore = alert_doppioni.chiudi_rumore(apply=apply)
        per_regola = {}
        for r in rumore:
            per_regola[r["regola"]] = per_regola.get(r["regola"], 0) + 1
        self.stdout.write(f"{prova}Rumore: {len(rumore)} alert {'chiusi' if apply else 'da chiudere'} "
                          f"({', '.join(f'{k}: {v}' for k, v in sorted(per_regola.items())) or 'nessuno'}).")
        gruppi = alert_doppioni.unisci_doppioni(apply=apply, escludi=[r["alert"] for r in rumore])
        uniti = sum(len(g["uniti"]) for g in gruppi)
        self.stdout.write(f"{prova}Alert per PC/job/CVE: {len(gruppi)} gruppi, {uniti} alert {'uniti' if apply else 'da unire'}.")
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
