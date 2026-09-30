"""Interroga i dispositivi generici registrati nella centrale SNMP."""

from django.core.management.base import BaseCommand, CommandError

from contatori.models import DispositivoSNMP, StatoSNMP
from contatori.services import interroga_dispositivo


class Command(BaseCommand):
    help = "Interroga i dispositivi attivi della centrale SNMP e storicizza le sonde"

    def add_arguments(self, parser):
        parser.add_argument(
            "--device-id", type=int, action="append", dest="device_ids",
            help="limita l'interrogazione a uno o piu' ID (ripetibile)",
        )
        parser.add_argument(
            "--include-inactive", action="store_true",
            help="include anche i dispositivi disattivati",
        )

    def handle(self, *args, **options):
        dispositivi = DispositivoSNMP.objects.all()
        if not options["include_inactive"]:
            dispositivi = dispositivi.filter(attivo=True)
        if options["device_ids"]:
            dispositivi = dispositivi.filter(pk__in=options["device_ids"])
        dispositivi = list(dispositivi)
        if options["device_ids"] and len(dispositivi) != len(set(options["device_ids"])):
            trovati = {d.pk for d in dispositivi}
            mancanti = sorted(set(options["device_ids"]) - trovati)
            raise CommandError(f"Dispositivi non trovati o esclusi: {mancanti}")

        conteggi = {StatoSNMP.OK: 0, StatoSNMP.WARNING: 0, StatoSNMP.ERROR: 0}
        for dispositivo in dispositivi:
            rilevazione = interroga_dispositivo(dispositivo)
            conteggi[rilevazione.stato] = conteggi.get(rilevazione.stato, 0) + 1
            metodo = self.style.SUCCESS if rilevazione.stato == StatoSNMP.OK else self.style.WARNING
            dettaglio = rilevazione.errore or f"{rilevazione.tempo_risposta_ms} ms"
            self.stdout.write(metodo(
                f"[{rilevazione.stato}] {dispositivo.nome} ({dispositivo.host}) · {dettaglio}"
            ))

        self.stdout.write(
            f"\n{len(dispositivi)} dispositivi: {conteggi[StatoSNMP.OK]} operativi, "
            f"{conteggi[StatoSNMP.WARNING]} in attenzione, "
            f"{conteggi[StatoSNMP.ERROR]} errori."
        )
