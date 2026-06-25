"""F2a — Report di match competenza-macchina (MOD.187) → ``assets.Asset``.

**Sola lettura**: NON scrive baseline né tocca il DB. Legge il catalogo
competenze (CSV), considera le sole righe ``tipo=macchina`` (i 41 processi NON
si mappano ad asset; il contatore "corsi attivati" è escluso) e produce
``docs/skill-matrix/asset_match_report.csv`` con la confidenza del match.

È il **GATE** prima di qualunque import: il report va validato a mano (i match
``parziale``/``assente`` confermati, gli ``esatto`` sono pre-approvati).

Esempi:
    python manage.py skm_asset_match_report
    python manage.py skm_asset_match_report --catalogo path/al/catalogo.csv --output report.csv
    # Match OFFLINE sui codici esportati dall'ambiente target (vedi skm_export_assets):
    python manage.py skm_asset_match_report --assets-csv docs/skill-matrix/assets_export.csv
"""
from __future__ import annotations

import csv
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from anagrafica.services.skillmatrix_match import (
    COLONNE_REPORT,
    IndiceAssetSkm,
    costruisci_righe_report,
    riepilogo,
)

TIPO_MACCHINA = "macchina"


def _repo_root() -> Path:
    # settings.BASE_DIR == django_app/ ; la repo root è il suo parent.
    return Path(settings.BASE_DIR).parent


class Command(BaseCommand):
    help = "F2a: report di match competenza-macchina MOD.187 -> assets.Asset (sola lettura)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--catalogo", default="",
            help="CSV catalogo competenze (default: docs/anagrafica/skillmatrix/skm_catalogo_competenze.csv).",
        )
        parser.add_argument(
            "--output", default="",
            help="CSV di output (default: docs/skill-matrix/asset_match_report.csv).",
        )
        parser.add_argument(
            "--assets-csv", default="",
            help=(
                "CSV degli asset esportati dall'ambiente target (vedi skm_export_assets). "
                "Se presente, il match è OFFLINE da questo file e il DB NON viene letto."
            ),
        )

    def handle(self, *args, **opts):
        root = _repo_root()
        output = Path(opts["output"]) if opts["output"] else (
            root / "docs" / "skill-matrix" / "asset_match_report.csv"
        )

        if opts["catalogo"]:
            catalogo = Path(opts["catalogo"])
            if not catalogo.exists():
                raise CommandError(f"Catalogo non trovato: {catalogo}")
            competenze = self._leggi_catalogo_macchine(catalogo)
        else:
            default_csv = root / "docs" / "anagrafica" / "skillmatrix" / "skm_catalogo_competenze.csv"
            if default_csv.exists():
                competenze = self._leggi_catalogo_macchine(default_csv)
            else:
                # In prod la cartella docs/ è esclusa dal pacchetto: ripiego sul
                # catalogo impacchettato come modulo Python (stessa fonte del seed).
                competenze = self._competenze_da_modulo()

        if not competenze:
            raise CommandError("Nessuna competenza tipo=macchina nel catalogo.")

        if opts["assets_csv"]:
            assets_path = Path(opts["assets_csv"])
            if not assets_path.exists():
                raise CommandError(f"CSV asset non trovato: {assets_path}")
            assets = self._leggi_assets_csv(assets_path)
            fonte_assets = f"CSV {assets_path}"
        else:
            # Import locale per non legare il modulo all'app assets al caricamento.
            from assets.models import Asset

            assets = list(Asset.objects.all().only("id", "asset_tag", "name", "asset_type"))
            fonte_assets = "DB"

        indice = IndiceAssetSkm.costruisci(assets)
        righe = costruisci_righe_report(competenze, indice)

        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=COLONNE_REPORT, delimiter=";")
            writer.writeheader()
            writer.writerows(righe)

        rep = riepilogo(righe)
        tot = len(righe)
        self.stdout.write(self.style.SUCCESS(f"Report scritto: {output}"))
        self.stdout.write(
            f"Macchine: {tot} | esatti: {rep['esatto']} | "
            f"parziali: {rep['parziale']} | assenti: {rep['assente']} "
            f"| asset ({fonte_assets}): {len(assets)}"
        )
        self.stdout.write(
            "GATE F2a: validare a mano i match parziali/assenti prima di qualunque import. "
            "Gli 'esatto' sono pre-approvati."
        )

    @staticmethod
    def _competenze_da_modulo() -> list[dict]:
        """Catalogo macchine dal modulo Python impacchettato (fallback senza CSV)."""
        from anagrafica.skillmatrix_catalogo import CATALOGO_MOD187

        return [
            {
                "competenza_key": (c.get("competenza_key") or "").strip(),
                "display": (c.get("display") or "").strip(),
                "codice": (c.get("codice") or "").strip(),
            }
            for c in CATALOGO_MOD187
            if (c.get("tipo") or "").strip().lower() == TIPO_MACCHINA
        ]

    @staticmethod
    def _leggi_assets_csv(path: Path) -> list:
        """Legge gli asset esportati (skm_export_assets) come stub per il matcher.

        Accetta delimitatore ``;`` o ``,`` (autodetect). Servono le colonne
        ``asset_tag``, ``name``, ``asset_type`` (``id`` opzionale).
        """
        out: list = []
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            sample = fh.read(4096)
            fh.seek(0)
            delim = ";" if sample.count(";") >= sample.count(",") else ","
            reader = csv.DictReader(fh, delimiter=delim)
            for row in reader:
                tag = (row.get("asset_tag") or "").strip()
                name = (row.get("name") or "").strip()
                if not tag and not name:
                    continue
                out.append(SimpleNamespace(
                    id=(row.get("id") or "").strip() or None,
                    asset_tag=tag,
                    name=name,
                    asset_type=(row.get("asset_type") or "").strip(),
                ))
        return out

    @staticmethod
    def _leggi_catalogo_macchine(path: Path) -> list[dict]:
        out: list[dict] = []
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                if (row.get("tipo") or "").strip().lower() != TIPO_MACCHINA:
                    continue
                out.append({
                    "competenza_key": (row.get("competenza_key") or "").strip(),
                    "display": (row.get("competenza_display") or "").strip(),
                    "codice": (row.get("codice_asset_match") or "").strip(),
                })
        return out
