from django.core.management.base import BaseCommand

from security.services.vpn_history import riallinea_storico


class Command(BaseCommand):
    help = (
        "Storico VPN: rilegge il fuso orario di ogni report dalla mail WatchGuard, corregge gli orari "
        "e toglie gli accessi doppi (stesso accesso da due report programmati, sfalsato di un'ora). "
        "Senza --apply mostra soltanto i conteggi."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Applica le correzioni (altrimenti solo conteggio).")

    def handle(self, *args, **options):
        result = riallinea_storico(apply=options["apply"])
        days = result["days"]
        self.stdout.write(
            f"Accessi letti: {result['rows']} | report con fuso ricavato: {result['reports_with_tz']} | "
            f"doppioni: {result['doubles']} | righe da correggere: {result['changed']} | "
            f"giorni toccati: {len(days)}" + (f" ({days[0]} - {days[-1]})" if days else "")
        )
        if options["apply"]:
            self.stdout.write(self.style.SUCCESS("Correzioni applicate e KPI VPN dei giorni toccati ricalcolati."))
        else:
            self.stdout.write("Prova a vuoto: rilanciare con --apply per applicare.")
