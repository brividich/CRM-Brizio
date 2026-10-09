"""Cattura un walk SNMP completo (read-only) per verificare gli OID dei preset.

Esempi:
  manage.py snmp_capture --list-communities
  manage.py snmp_capture --host 10.0.0.10 --v2c --community-id 3 --out D:\\snmp\\switch.snmprec
  manage.py snmp_capture --sanitize-from D:\\snmp\\switch.snmprec --out contatori\\fixtures\\snmp\\aruba.snmprec

Il walk grezzo contiene dati reali di rete: va salvato FUORI dal repository.
Solo le fixture prodotte con --sanitize/--sanitize-from possono stare nel repo.
"""
import os
import re
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from contatori import snmp_capture as cap

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_OUT_DIR = r"C:\snmp_capture"
# Solo la community di fabbrica: le community aziendali vanno passate o prese dal catalogo cifrato.
DEFAULT_COMMUNITIES = ("public",)


def _slug(descr):
    """Nome file leggibile dalla sysDescr, senza dati oltre a quelli del file stesso."""
    parole = re.sub(r"[^A-Za-z0-9]+", "-", descr or "").strip("-")
    return (parole[:40].rstrip("-") or "sconosciuto").lower()


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
        parser.add_argument("--only", help="con --sanitize-from: tiene solo questi sottoalberi (separati da virgola)")
        parser.add_argument("--list-communities", action="store_true",
                            help="elenca il catalogo community (solo id e nome)")
        parser.add_argument("--network", help="scansiona una rete (es. 10.0.0.0/24) e cattura ogni apparato")
        parser.add_argument("--out-dir", help=f"cartella dei walk in modalita' rete (default {DEFAULT_OUT_DIR})")
        parser.add_argument("--parallel", type=int, default=4, help="catture contemporanee (max 8)")
        parser.add_argument("--overwrite", action="store_true", help="ricattura anche i file gia' presenti")

    def handle(self, *args, **opt):
        if opt["list_communities"]:
            return self._list_communities()
        if opt["network"]:
            return self._network(opt)
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
            only = tuple(p.strip().strip(".") for p in (opt["only"] or "").split(",") if p.strip())
            return self._sanitize_file(Path(opt["sanitize_from"]), out, only)
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
        if opt["community"]:
            return opt["community"]
        # Nessuna fonte indicata: chiede la community a video senza mostrarla.
        import getpass

        try:
            return getpass.getpass("Community SNMP (non viene mostrata mentre scrivi): ").strip()
        except (EOFError, KeyboardInterrupt) as exc:
            raise CommandError("Community non inserita.") from exc

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
            result, header = self._capture_one(
                opt["host"], version, credentials, [community, auth_key, priv_key],
                out, opt, sanitize,
            )
        except cap.CaptureError as exc:
            raise CommandError(str(exc)) from exc
        style = self.style.SUCCESS if result.complete else self.style.WARNING
        self.stdout.write(style(" | ".join(header[2:])))

    def _capture_one(self, host, version, credentials, secrets, out, opt, sanitize):
        """Cattura e salva un apparato; solleva CaptureError se non legge nulla."""
        result = cap.capture(
            host, credentials, port=opt["port"], timeout=opt["timeout"],
            retries=opt["retries"], root=opt["root"].strip().lstrip("."),
            version=version, max_repetitions=opt["max_repetitions"],
            max_rows=opt["max_rows"], max_duration=opt["max_duration"],
        )
        redacted = cap.redact_secret(result.records, secrets)
        records = result.records
        if sanitize:
            records = cap.Sanitizer().apply(records)
        if not records:
            motivo = f" ({result.stop_reason})" if result.stop_reason else ""
            raise cap.CaptureError(f"Nessun OID letto{motivo}: verificare IP, versione, "
                                   "credenziali e ACL SNMP del device.")
        header = [
            f"snmp_capture {datetime.now():%Y-%m-%d %H:%M}",
            f"host: {'(pseudonimizzato)' if sanitize else host}  versione: {version}  root: {opt['root']}",
            f"righe: {len(records)}  richieste: {result.requests}  durata: {result.duration:.1f}s",
            f"esclusi: {result.dropped}  segreti oscurati: {redacted}  tipi ignoti: {result.unknown_types}",
            "COMPLETO" if result.complete else f"INCOMPLETO: {result.stop_reason}",
        ]
        self._write(out, records, header)
        return result, header

    def _communities(self, opt):
        """Community da provare nella scansione: elenco separato da virgole."""
        if opt["community_env"] or opt["community"]:
            raw = self._env(opt["community_env"]) if opt["community_env"] else opt["community"]
        else:
            import getpass

            try:
                raw = getpass.getpass(
                    "Community da provare, separate da virgola (non vengono mostrate; "
                    f"Invio = {', '.join(DEFAULT_COMMUNITIES)}): ")
            except (EOFError, KeyboardInterrupt) as exc:
                raise CommandError("Community non inserite.") from exc
        valori = [c.strip() for c in raw.split(",") if c.strip()]
        return list(dict.fromkeys(valori or DEFAULT_COMMUNITIES))[:8]

    def _network(self, opt):
        from concurrent.futures import ThreadPoolExecutor, as_completed

        from contatori.snmp import SNMPError, hosts_rete, scansiona_hosts

        out_dir = Path(opt["out_dir"] or DEFAULT_OUT_DIR).resolve()
        if out_dir == REPO_ROOT or REPO_ROOT in out_dir.parents:
            raise CommandError("I walk grezzi vanno salvati fuori dal repository.")
        try:
            hosts = hosts_rete(opt["network"])
        except SNMPError as exc:
            raise CommandError(str(exc)) from exc
        communities = self._communities(opt)
        versions = [opt["version"]] if opt["version"] in ("v1", "v2c") else ["v2c", "v1"]
        self.stdout.write(f"Scansione di {len(hosts)} indirizzi con {len(communities)} community "
                          f"({', '.join(versions)})...")
        trovati = {}
        for version in versions:
            restanti = [h for h in hosts if h not in trovati]
            if not restanti:
                break
            try:
                righe = scansiona_hosts(restanti, communities=communities, version=version,
                                        timeout=2, concurrency=32, max_duration=300)
            except SNMPError as exc:
                raise CommandError(str(exc)) from exc
            for row in righe:
                trovati[row["host"]] = (version, communities[row["community_index"] - 1], row["descr"])
            if getattr(righe, "incompleta", False):
                self.stdout.write(self.style.WARNING(f"Scansione {version} incompleta: rilanciare per i mancanti."))
        if not trovati:
            raise CommandError("Nessun apparato ha risposto: verificare community e rete.")
        self.stdout.write(f"{len(trovati)} apparati rispondono. Cattura in corso "
                          f"(fino a {opt['parallel']} insieme)...\n")

        def lavoro(host, version, community, descr):
            out = out_dir / f"{host}_{_slug(descr)}.snmprec"
            if out.exists() and not opt["overwrite"]:
                return host, descr, out, None, "gia' presente, saltato"
            credentials = cap.build_credentials(version=version, community=community)
            try:
                result, _ = self._capture_one(host, version, credentials, communities, out, opt, False)
            except cap.CaptureError as exc:
                return host, descr, out, None, str(exc)
            return host, descr, out, result, ""

        indice = []
        with ThreadPoolExecutor(max_workers=max(1, min(8, opt["parallel"]))) as pool:
            futures = [pool.submit(lavoro, h, *trovati[h]) for h in sorted(
                trovati, key=lambda ip: tuple(int(p) for p in ip.split(".")))]
            for future in as_completed(futures):
                host, descr, out, result, errore = future.result()
                if result is None:
                    esito = errore
                    self.stdout.write(self.style.WARNING(f"  {host:<15} {esito}"))
                else:
                    esito = (f"{len(result.records)} righe, {result.duration:.0f}s, "
                             + ("COMPLETO" if result.complete else f"INCOMPLETO: {result.stop_reason}"))
                    style = self.style.SUCCESS if result.complete else self.style.WARNING
                    self.stdout.write(style(f"  {host:<15} {out.name}  {esito}"))
                indice.append((host, trovati[host][0], descr[:80], out.name, esito))
        indice.sort(key=lambda r: tuple(int(p) for p in r[0].split(".")))
        (out_dir / "indice.txt").write_text(
            "".join(" | ".join(r) + "\n" for r in indice), encoding="utf-8")
        self.stdout.write(f"\nFile in {out_dir} (elenco in indice.txt).")

    def _sanitize_file(self, source, out, only=()):
        try:
            records = cap.parse_snmprec(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            raise CommandError(f"File non leggibile: {source.name}") from exc
        except cap.CaptureError as exc:
            raise CommandError(str(exc)) from exc
        records = [r for r in records if not cap.in_subtree(r.oid, cap.DROP_ALWAYS)
                   and (not only or cap.in_subtree(r.oid, only))]
        records = cap.Sanitizer().apply(records)
        header = [f"fixture da {source.name} (pseudonimizzata)", f"righe: {len(records)}"]
        self._write(out, records, header)
        self.stdout.write(self.style.SUCCESS(f"{len(records)} righe -> {out.name}"))

    def _write(self, out, records, header):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(cap.render_snmprec(records), encoding="utf-8", newline="\n")
        out.with_suffix(".txt").write_text(cap.render_text(records, header), encoding="utf-8",
                                           newline="\n")
