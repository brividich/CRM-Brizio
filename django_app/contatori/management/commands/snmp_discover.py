"""Diagnostica SNMP generica e discovery dei profili del catalogo."""
from django.core.management.base import BaseCommand, CommandError

from contatori import services
from contatori.models import ImpostazioniSNMP
from contatori.snmp import (
    COUNTER_MAP,
    PRT_SERIAL,
    SNMPError,
    SYS_DESCR,
    SYS_NAME,
    SYS_OBJECT_ID,
    _consumabili_raw,
    _tabella,
    _testo,
    aggrega_colonna,
    leggi_colonna,
    leggi_oids,
)

_SUGGERIMENTO = (
    "\nUna community sbagliata in SNMPv1/v2c produce normalmente un timeout, "
    "come un host irraggiungibile. Verifica IP, community read-only, versione, "
    "filtro IP del dispositivo e UDP/161 dal server del portale."
)


class Command(BaseCommand):
    help = "Prova SNMP, identifica il produttore e mostra profilo e contatori disponibili"

    def add_arguments(self, parser):
        parser.add_argument("--host", required=True, help="IP del dispositivo")
        parser.add_argument("--community", default=None, help="default: quella configurata")
        parser.add_argument(
            "--snmp-version", dest="version", default=None,
            choices=["v1", "v2c"], help="versione SNMP (default: quella configurata)",
        )
        parser.add_argument("--port", type=int, default=None)
        parser.add_argument("--timeout", type=int, default=None, help="secondi")
        parser.add_argument(
            "--consumabili", action="store_true",
            help="mostra anche toner/tamburi Printer-MIB",
        )

    def handle(self, *args, **opts):
        cfg = ImpostazioniSNMP.get_solo()
        host = opts["host"]
        community = opts["community"] or cfg.community
        version = opts["version"] or cfg.version
        port = opts["port"] or cfg.port
        timeout = opts["timeout"] or cfg.timeout
        self.stdout.write(
            f"host={host}  community={community!r}  version={version}  "
            f"port={port}  timeout={timeout}s"
        )

        try:
            probe_oids = services.oid_riconoscimento_attivi()
            identita, _ = leggi_oids(
                host, [SYS_DESCR, SYS_OBJECT_ID, SYS_NAME, PRT_SERIAL, *probe_oids],
                community=community, port=port, timeout=timeout, version=version,
            )
        except SNMPError as exc:
            raise CommandError(f"{exc}{_SUGGERIMENTO}")

        descr = _testo(identita.get(SYS_DESCR))
        object_id = _testo(identita.get(SYS_OBJECT_ID))
        self.stdout.write(self.style.SUCCESS("OK - il dispositivo risponde via SNMP"))
        self.stdout.write(f"  sysName:     {_testo(identita.get(SYS_NAME)) or '-'}")
        self.stdout.write(f"  sysDescr:    {descr or '-'}")
        self.stdout.write(f"  sysObjectID: {object_id or '-'}")
        self.stdout.write(f"  seriale:     {_testo(identita.get(PRT_SERIAL)) or '-'}")
        profilo = services.trova_profilo_snmp(
            sys_object_id=object_id, sys_description=descr,
            valori_riconoscimento={oid: identita.get(oid) for oid in probe_oids if oid in identita},
        )
        self.stdout.write(f"  profilo:     {profilo or 'nessun profilo rilevato'}")

        try:
            totale = aggrega_colonna(
                leggi_colonna(
                    host, "1.3.6.1.2.1.43.10.2.1.4",
                    community=community, port=port, timeout=timeout,
                    version=version,
                ),
                "MASSIMO",
            )
            self.stdout.write(f"  Printer-MIB totale impressioni: {totale}")
        except SNMPError as exc:
            self.stdout.write(self.style.WARNING(f"  Printer-MIB non disponibile: {exc}"))

        if object_id.lstrip(".").startswith("1.3.6.1.4.1.1602"):
            try:
                tabella = _tabella(host, community, port, timeout, version)
            except SNMPError as exc:
                self.stdout.write(self.style.WARNING(f"Tabella Canon non leggibile: {exc}"))
                tabella = {}
            if tabella:
                self.stdout.write(f"\nCanon: {len(tabella)} contatori proprietari letti")
                for num in sorted(tabella):
                    self.stdout.write(f"  contatore {num:>4} = {tabella[num]}")

        self.stdout.write(
            "\nPer una MFC contrattuale servono A4 BN, A3 BN, A4 colore e A3 colore.\n"
            "Il totale Printer-MIB non viene attribuito automaticamente a queste colonne.\n"
            f"Modelli Canon legacy mappati: {', '.join(sorted(COUNTER_MAP))}\n"
            "Gli altri profili si gestiscono da Contatori > Profili SNMP."
        )

        if opts["consumabili"]:
            self.stdout.write("\nConsumabili (Printer-MIB):")
            try:
                for _idx, nome, livello, massimo in _consumabili_raw(
                    host, community, port, timeout, version,
                ):
                    self.stdout.write(f"  {nome}: {livello}/{massimo}")
            except SNMPError as exc:
                self.stdout.write(self.style.WARNING(f"  non leggibili: {exc}"))
