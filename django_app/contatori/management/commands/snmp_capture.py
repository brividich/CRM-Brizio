"""Cattura un walk SNMP completo (read-only) per verificare gli OID dei preset.

Esempi:
  manage.py snmp_capture --list-communities
  manage.py snmp_capture --host 10.0.0.10 --v2c --community-id 3 --out D:\\snmp\\switch.snmprec
  manage.py snmp_capture --sanitize-from D:\\snmp\\switch.snmprec --out contatori\\fixtures\\snmp\\aruba.snmprec

Il walk grezzo contiene dati reali di rete: va salvato FUORI dal repository.
Solo le fixture prodotte con --sanitize/--sanitize-from possono stare nel repo.
"""
import os
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from contatori import snmp_capture as cap

REPO_ROOT = Path(__file__).resolve().parents[4]


class Command(BaseCommand):
    help = "Walk SNMP completo in formato .snmprec (snmpsim) + .txt leggibile; solo GETNEXT/GETBULK"

    def add_arguments(self, parser):
        parser.add_argument("--host", help="IP del dispositivo")
        parser.add_argument("--port", type=int, default=161)
        versione = parser.add_mutually_exclusive_group()
        versione.add_argument("--v1", dest="version", action="store_const", const="v1")
        versione.add_argument("--v2c", dest="version", action="store_const", const="v2c")
        versione.add_argument("--v3", dest="version", action="store_const", const="v3")
        parser.add_argument("--community-id", type=int,
                            help="community dal catalogo cifrato (consigliato)")
        parser.add_argument("--community-env", help="nome della variabile d'ambiente con la community")
        parser.add_argument("--community", help="community in chiaro (finisce nella cronologia della shell)")
        parser.add_argument("--v3-user")
        parser.add_argument("--v3-auth", choices=["md5", "sha1"])
        parser.add_argument("--v3-auth-key-env", help="variabile d'ambiente con la chiave di autenticazione")
        parser.add_argument("--v3-priv", choices=["aes", "des"])
        parser.add_argument("--v3-priv-key-env", help="variabile d'ambiente con la chiave di cifratura")
        parser.add_argument("--root", default="1", help="sottoalbero da percorrere (default: tutto)")
        parser.add_argument("--max-repetitions", type=int, default=25)
        parser.add_argument("--timeout", type=int, default=3, help="secondi per richiesta")
        parser.add_argument("--retries", type=int, default=2)
        parser.add_argument("--max-rows", type=int, default=200_000)
        parser.add_argument("--max-duration", type=int, default=900, help="secondi totali")
        parser.add_argument("--out", help="file .snmprec di destinazione (il .txt viene affiancato)")
        parser.add_argument("--sanitize", action="store_true",
                            help="pseudonimizza IP/MAC/nomi ed esclude tabelle sensibili")
        parser.add_argument("--sanitize-from", help="converte un .snmprec grezzo gia' catturato in fixture")
        parser.add_argument("--list-communities", action="store_true",
                            help="elenca il catalogo community (solo id e nome)")

    def handle(self, *args, **opt):
        if opt["list_communities"]:
            return self._list_communities()
        if not opt["out"]:
            raise CommandError("Indicare --out.")
        out = Path(opt["out"]).resolve()
        if out.suffix != ".snmprec":
            raise CommandError("Il file di destinazione deve avere estensione .snmprec.")
        sanitize = opt["sanitize"] or bool(opt["sanitize_from"])
        if not sanitize and (out == REPO_ROOT or REPO_ROOT in out.parents):
            raise CommandError(
                "Il walk grezzo contiene dati reali di rete: salvarlo fuori dal repository "
                "oppure usare --sanitize."
            )
        if opt["sanitize_from"]:
            return self._sanitize_file(Path(opt["sanitize_from"]), out)
        return self._capture(opt, out, sanitize)

    def _list_communities(self):
        from contatori.models import CommunitySNMP

        for c in CommunitySNMP.objects.order_by("ordine", "nome"):
            stato = "" if c.attiva else " (disattivata)"
            self.stdout.write(f"{c.pk:>4}  {c.nome}  {c.versione or '-'}{stato}")

    def _secret(self, opt):
        if opt["community_id"]:
            from contatori.credential_crypto import decifra
            from contatori.models import CommunitySNMP

            c = CommunitySNMP.objects.filter(pk=opt["community_id"]).first()
            if c is None:
                raise CommandError("Community del catalogo non trovata.")
            try:
                return decifra(c.segreto_cifrato)
            except ValueError as exc:
                raise CommandError("Community del catalogo non decifrabile.") from exc
        if opt["community_env"]:
            value = os.environ.get(opt["community_env"], "")
            if not value:
                raise CommandError(f"Variabile d'ambiente {opt['community_env']} vuota.")
            return value
        return opt["community"] or ""

    def _env(self, name):
        if not name:
            return ""
        value = os.environ.get(name, "")
        if not value:
            raise CommandError(f"Variabile d'ambiente {name} vuota.")
        return value

    def _capture(self, opt, out, sanitize):
        if not opt["host"]:
            raise CommandError("Indicare --host.")
        version = opt["version"] or "v2c"
        community = auth_key = priv_key = ""
        if version == "v3":
            auth_key = self._env(opt["v3_auth_key_env"])
            priv_key = self._env(opt["v3_priv_key_env"])
            if opt["v3_auth"] and not auth_key:
                raise CommandError("Indicare --v3-auth-key-env.")
        else:
            community = self._secret(opt)
            if not community:
                raise CommandError("Indicare --community-id, --community-env o --community.")
        try:
            credentials = cap.build_credentials(
                version=version, community=community, v3_user=opt["v3_user"] or "",
                v3_auth=opt["v3_auth"] or "", v3_auth_key=auth_key,
                v3_priv=opt["v3_priv"] or "", v3_priv_key=priv_key,
            )
            result = cap.capture(
                opt["host"], credentials, port=opt["port"], timeout=opt["timeout"],
                retries=opt["retries"], root=opt["root"].strip().lstrip("."),
                version=version, max_repetitions=opt["max_repetitions"],
                max_rows=opt["max_rows"], max_duration=opt["max_duration"],
            )
        except cap.CaptureError as exc:
            raise CommandError(str(exc)) from exc
        secrets = [community, auth_key, priv_key]
        redacted = cap.redact_secret(result.records, secrets)
        records = result.records
        if sanitize:
            records = cap.Sanitizer().apply(records)
        if not records:
            motivo = f" ({result.stop_reason})" if result.stop_reason else ""
            raise CommandError(f"Nessun OID letto{motivo}: verificare IP, versione, "
                               "credenziali e ACL SNMP del device.")
        header = [
            f"snmp_capture {datetime.now():%Y-%m-%d %H:%M}",
            f"host: {'(pseudonimizzato)' if sanitize else opt['host']}  versione: {version}  root: {opt['root']}",
            f"righe: {len(records)}  richieste: {result.requests}  durata: {result.duration:.1f}s",
            f"esclusi: {result.dropped}  segreti oscurati: {redacted}  tipi ignoti: {result.unknown_types}",
            "COMPLETO" if result.complete else f"INCOMPLETO: {result.stop_reason}",
        ]
        self._write(out, records, header)
        style = self.style.SUCCESS if result.complete else self.style.WARNING
        self.stdout.write(style(" | ".join(header[2:])))

    def _sanitize_file(self, source, out):
        try:
            records = cap.parse_snmprec(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            raise CommandError(f"File non leggibile: {source.name}") from exc
        except cap.CaptureError as exc:
            raise CommandError(str(exc)) from exc
        records = cap.Sanitizer().apply(
            [r for r in records if not cap.in_subtree(r.oid, cap.DROP_ALWAYS)])
        header = [f"fixture da {source.name} (pseudonimizzata)", f"righe: {len(records)}"]
        self._write(out, records, header)
        self.stdout.write(self.style.SUCCESS(f"{len(records)} righe -> {out.name}"))

    def _write(self, out, records, header):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(cap.render_snmprec(records), encoding="utf-8", newline="\n")
        out.with_suffix(".txt").write_text(cap.render_text(records, header), encoding="utf-8",
                                           newline="\n")
