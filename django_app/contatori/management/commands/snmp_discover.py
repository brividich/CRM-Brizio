"""Diagnostica SNMP: interroga un host e mostra cosa risponde davvero.

Due usi:
  (a) capire perche' una macchina NON risponde. Attenzione: in SNMPv1/v2c una
      community sbagliata non produce un errore di autenticazione, produce un
      TIMEOUT — indistinguibile da "host irraggiungibile". Questo comando permette
      di provare host/community/versione diversi in fretta.
  (b) ricavare i numeri contatore di un modello NUOVO prima di aggiungerlo a
      snmp.COUNTER_MAP (mai mappare a occhio: contatori sbagliati = riconciliazione
      fatture sbagliata).

Esempi:
  manage.py snmp_discover --host 10.0.0.155
  manage.py snmp_discover --host 10.0.0.155 --community public
  manage.py snmp_discover --host 10.0.0.155 --version v2c --timeout 10
  manage.py snmp_discover --host 10.0.0.212 --consumabili
"""
from django.core.management.base import BaseCommand, CommandError

from contatori.models import ImpostazioniSNMP
from contatori.snmp import COUNTER_MAP, SNMPError, _consumabili_raw, _tabella

_SUGGERIMENTO = (
    "\nUna community SBAGLIATA in SNMPv1/v2c non da' errore di auth: da' TIMEOUT, "
    "identico a un host irraggiungibile. Verifica in ordine:\n"
    "  1) l'IP e' davvero quello della macchina (pannello Canon: Rete > TCP/IP);\n"
    "  2) sulla stampante SNMPv1 e' abilitato e il nome community coincide;\n"
    "  3) la stampante non ha un filtro IP che blocca il server del portale;\n"
    "  4) UDP/161 non e' bloccato tra server e stampante.\n"
    "Confronta con una macchina che funziona: stessa community/versione dal medesimo server."
)


class Command(BaseCommand):
    help = "Prova SNMP su un host e stampa i contatori grezzi (diagnostica / discover modello)"

    def add_arguments(self, parser):
        parser.add_argument("--host", required=True, help="IP della stampante")
        parser.add_argument("--community", default=None, help="default: quella configurata")
        parser.add_argument("--version", default=None, choices=["v1", "v2c"])
        parser.add_argument("--port", type=int, default=None)
        parser.add_argument("--timeout", type=int, default=None, help="secondi")
        parser.add_argument("--consumabili", action="store_true",
                            help="mostra anche toner/tamburi (Printer-MIB standard)")

    def handle(self, *args, **opts):
        cfg = ImpostazioniSNMP.get_solo()
        host = opts["host"]
        community = opts["community"] or cfg.community
        version = opts["version"] or cfg.version
        port = opts["port"] or cfg.port
        timeout = opts["timeout"] or cfg.timeout

        self.stdout.write(
            f"host={host}  community={community!r}  version={version}  port={port}  timeout={timeout}s"
        )

        try:
            tabella = _tabella(host, community, port, timeout, version)
        except SNMPError as exc:
            raise CommandError(f"{exc}{_SUGGERIMENTO}")

        if not tabella:
            raise CommandError(
                "SNMP risponde ma la tabella contatori Canon e' vuota: "
                "o non e' una Canon iR-ADV, o l'OID contatori non e' esposto." + _SUGGERIMENTO
            )

        self.stdout.write(self.style.SUCCESS(f"OK — {len(tabella)} contatori letti"))
        for num in sorted(tabella):
            self.stdout.write(f"  contatore {num:>4} = {tabella[num]}")

        self.stdout.write(
            "\nPer mappare un modello NUOVO in snmp.COUNTER_MAP servono i numeri di:\n"
            "  a4_bn  = Total Black/Small     a3_bn  = Total Black/Large\n"
            "  a4_col = Total Color/Small     a3_col = Total Color/Large\n"
            "Sui iR-ADV Gen3 gia' verificati sono 113 / 112 / 123 / 122.\n"
            f"Modelli attualmente mappati: {', '.join(sorted(COUNTER_MAP))}"
        )

        if opts["consumabili"]:
            self.stdout.write("\nConsumabili (Printer-MIB):")
            try:
                for _idx, nome, livello, massimo in _consumabili_raw(host, community, port, timeout, version):
                    self.stdout.write(f"  {nome}: {livello}/{massimo}")
            except SNMPError as exc:
                self.stdout.write(self.style.WARNING(f"  non leggibili: {exc}"))
