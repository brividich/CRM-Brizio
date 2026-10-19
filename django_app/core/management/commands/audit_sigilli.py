"""Sigilli mensili dell'audit (``core.audit_sigilli``).

    python manage.py audit_sigilli                # elenco dei sigilli con esito di verifica ed export
    python manage.py audit_sigilli --sigilla      # sigilla i mesi conclusi mancanti
    python manage.py audit_sigilli --verifica     # ricalcola righe e catena (exit 1 se rotta)
    python manage.py audit_sigilli --esporta      # carica su SharePoint i sigilli non esportati
    python manage.py audit_sigilli --file 2026-09 --out C:\\tmp   # salva i due file di un mese in locale
    python manage.py audit_sigilli --cartella-sharepoint "<link della cartella>"   # imposta la destinazione dell'export
"""
from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core import audit_sigilli as svc
from core.models import AuditSigillo


class Command(BaseCommand):
    help = "Sigilla, verifica ed esporta l'audit mese per mese (catena di hash)."

    def add_arguments(self, parser):
        parser.add_argument("--sigilla", action="store_true")
        parser.add_argument("--verifica", action="store_true")
        parser.add_argument("--esporta", action="store_true")
        parser.add_argument("--file", default="", help="Mese AAAA-MM di cui salvare i file di export in locale.")
        parser.add_argument("--out", default="", help="Cartella per --file.")
        parser.add_argument(
            "--cartella-sharepoint", default="",
            help="Link della cartella SharePoint (barra degli indirizzi o «Copia collegamento»): "
                 "ricava raccolta e percorso, prova a scrivere il LEGGIMI e salva la destinazione.",
        )

    def handle(self, *args, **opts):
        if opts["cartella_sharepoint"]:
            from core.sharepoint_upload import SharePointUploadError, configura_da_link

            try:
                esito = configura_da_link(opts["cartella_sharepoint"])
            except SharePointUploadError as exc:
                raise CommandError(f"Cartella non impostata: {exc}")
            self.stdout.write(self.style.SUCCESS(
                f"Cartella impostata: {esito['cartella']} (LEGGIMI {esito['leggimi']}).\n  {esito['web_url']}\n"
                "  Ora: audit_sigilli --esporta per caricare i mesi in attesa."
            ))
            return
        if opts["sigilla"]:
            creati = svc.sigilla_mancanti()
            self.stdout.write(self.style.SUCCESS(f"Sigillati: {', '.join(s.mese for s in creati) or 'nessun mese nuovo'}"))
        if opts["verifica"]:
            esiti = svc.verifica()
            for e in esiti:
                stile = self.style.SUCCESS if e["stato"] == "ok" else (self.style.ERROR if e["stato"] == "rotto" else self.style.WARNING)
                self.stdout.write(stile(f"  {e['mese']}: {e['stato']} ({e['righe']} righe) {e.get('motivo', '')}".rstrip()))
            if any(e["stato"] == "rotto" for e in esiti):
                raise CommandError("Catena dei sigilli ROTTA: vedi i mesi segnati sopra.")
            self.stdout.write(self.style.SUCCESS(f"Catena integra ({len(esiti)} sigilli)."))
        if opts["esporta"]:
            self.stdout.write(str(svc.esporta_mancanti()))
        if opts["file"]:
            s = AuditSigillo.objects.filter(mese=opts["file"]).first()
            if s is None:
                raise CommandError(f"Nessun sigillo per {opts['file']}.")
            out = Path(opts["out"] or ".")
            out.mkdir(parents=True, exist_ok=True)
            righe, meta = svc.file_export(s)
            (out / f"audit-{s.mese}.jsonl.gz").write_bytes(righe)
            (out / f"audit-{s.mese}.sigillo.json").write_bytes(meta)
            self.stdout.write(self.style.SUCCESS(f"Scritti in {out}"))
        if not any(opts[k] for k in ("sigilla", "verifica", "esporta", "file")):
            from core.sharepoint_upload import destinazione

            _drive, cartella = destinazione()
            self.stdout.write(f"Destinazione export: {cartella or 'non impostata (usa --cartella-sharepoint)'}")
            for s in AuditSigillo.objects.order_by("mese"):
                verifica = {None: "mai verificato", True: "verificato", False: "ROTTO"}[s.verifica_ok]
                export = "esportato" if s.export_ok else f"da esportare ({s.export_errore or '-'})"
                self.stdout.write(f"{s.mese}: {s.righe} righe · {s.hash_sigillo[:16]}… · {verifica} · {export}")
