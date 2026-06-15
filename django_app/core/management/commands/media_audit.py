"""Audit dei file in MEDIA_ROOT alla ricerca di contenuti potenzialmente sensibili.

MEDIA_ROOT e' servita da IIS senza autenticazione (vedi MIDDLEWARE_EXEMPT_PREFIXES
e la mappatura statica /media/): ogni file che finisce li' e' di fatto pubblico
per chiunque raggiunga il portale. I documenti con dati personali devono stare
negli storage privati (*_PRIVATE_ROOT, serviti da view con ACL). Questo command
segnala i file in MEDIA_ROOT che, per nome o estensione, sembrano documenti
personali/sensibili finiti nella cartella sbagliata.

Euristica, non verdetto: un match va verificato a mano prima di spostare/eliminare.

Uso:
    python manage.py media_audit
    python manage.py media_audit --json
    python manage.py media_audit --fail-on-findings   # exit 1 se trova match (CI/release guard)
    python manage.py media_audit --allow anomalie_logo --allow loghi
"""
from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

# Parole chiave nel nome file/cartella che suggeriscono dati personali (lowercase).
SENSITIVE_NAME_KEYWORDS = (
    "certificat",
    "referto",
    "medic",
    "visita",
    "malattia",
    "sanitar",
    "infortun",
    "disciplinar",
    "contratt",
    "busta",
    "cedolino",
    "paga",
    "stipendio",
    "curriculum",
    "carta_identita",
    "cartaidentita",
    "carta-identita",
    "patente",
    "passaporto",
    "codice_fiscale",
    "codicefiscale",
    "iban",
    "privacy",
    "gdpr",
    "consenso",
    "firma",
    "timbro",
    "dipendente",
)

# Estensioni documento: in MEDIA_ROOT ci si aspettano quasi solo asset grafici
# (loghi, immagini UI). Un PDF/Office/archivio e' sospetto a prescindere dal nome.
DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".csv",
    ".txt",
    ".rtf",
    ".odt",
    ".msg",
    ".eml",
    ".p7m",
    ".zip",
    ".7z",
    ".rar",
}

# Sottocartelle di MEDIA_ROOT note come legittimamente pubbliche.
DEFAULT_ALLOWED_PREFIXES = ("anomalie_logo",)


class Command(BaseCommand):
    help = "Segnala file potenzialmente sensibili in MEDIA_ROOT (cartella servita senza autenticazione)."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="Output JSON machine-readable.")
        parser.add_argument(
            "--fail-on-findings",
            action="store_true",
            help="Esce con codice 1 se trova almeno un file sospetto (per CI/release guard).",
        )
        parser.add_argument(
            "--allow",
            action="append",
            default=[],
            metavar="PREFIX",
            help=(
                "Sottocartella di MEDIA_ROOT da considerare pubblica e saltare "
                f"(ripetibile; default sempre inclusi: {', '.join(DEFAULT_ALLOWED_PREFIXES)})."
            ),
        )
        parser.add_argument(
            "--max-list",
            type=int,
            default=100,
            help="Numero massimo di file elencati nel report testuale (default 100).",
        )

    def handle(self, *args, **options):
        media_root = Path(settings.MEDIA_ROOT)
        as_json: bool = options["json"]
        fail_on_findings: bool = options["fail_on_findings"]
        max_list: int = max(1, options["max_list"])
        allowed_prefixes = tuple(
            str(p).strip().strip("/\\").lower()
            for p in (*DEFAULT_ALLOWED_PREFIXES, *options["allow"])
            if str(p).strip()
        )

        if not media_root.exists():
            payload = {
                "media_root": str(media_root),
                "exists": False,
                "scanned": 0,
                "findings": [],
            }
            if as_json:
                self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                self.stdout.write(self.style.SUCCESS(f"MEDIA_ROOT non esiste ({media_root}): nulla da verificare."))
            return

        scanned = 0
        findings: list[dict] = []
        for path in sorted(media_root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(media_root).as_posix()
            rel_lower = rel.lower()
            scanned += 1

            if any(rel_lower == p or rel_lower.startswith(p + "/") for p in allowed_prefixes):
                continue

            reasons: list[str] = []
            ext = path.suffix.lower()
            if ext in DOCUMENT_EXTENSIONS:
                reasons.append(f"estensione documento ({ext})")
            matched_keywords = [k for k in SENSITIVE_NAME_KEYWORDS if k in rel_lower]
            if matched_keywords:
                reasons.append("keyword nel percorso: " + ", ".join(matched_keywords))

            if reasons:
                try:
                    size = path.stat().st_size
                except OSError:
                    size = None
                findings.append({"path": rel, "size_bytes": size, "reasons": reasons})

        payload = {
            "media_root": str(media_root),
            "exists": True,
            "scanned": scanned,
            "allowed_prefixes": list(allowed_prefixes),
            "findings_count": len(findings),
            "findings": findings,
        }

        if as_json:
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            self.stdout.write(f"MEDIA_ROOT: {media_root}")
            self.stdout.write(f"File esaminati: {scanned} (esclusi prefissi pubblici: {', '.join(allowed_prefixes)})")
            if not findings:
                self.stdout.write(self.style.SUCCESS("Nessun file sospetto trovato."))
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"{len(findings)} file potenzialmente sensibili in cartella PUBBLICA (verificare e "
                        "spostare negli storage privati *_PRIVATE_ROOT se contengono dati personali):"
                    )
                )
                for item in findings[:max_list]:
                    size = item["size_bytes"]
                    size_txt = f"{size:,} B" if isinstance(size, int) else "?"
                    self.stdout.write(f"  - {item['path']} [{size_txt}] — {'; '.join(item['reasons'])}")
                if len(findings) > max_list:
                    self.stdout.write(f"  … e altri {len(findings) - max_list} (usa --max-list o --json).")

        if findings and fail_on_findings:
            raise CommandError(f"media_audit: {len(findings)} file sospetti in MEDIA_ROOT.")
