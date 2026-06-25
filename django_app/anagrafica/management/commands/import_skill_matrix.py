"""F2b — Import baseline Skill Matrix MOD.187 dai CSV seed.

**Dry-run di default**: stampa il piano e NON scrive. Scrive la baseline solo con
``--apply``. ⛔ Prerequisito: il match competenza→asset deve essere **confermato**
(gate F2a, in portale o via report); le macchine senza match confermato vengono
elencate come **bloccate** e non importate.

Esempi:
    python manage.py import_skill_matrix                 # dry-run (piano)
    python manage.py import_skill_matrix --apply         # scrive la baseline
    python manage.py import_skill_matrix --base-dir <dir>
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from anagrafica.services.skillmatrix_importer import importa_skill_matrix


class Command(BaseCommand):
    help = "F2b: import baseline Skill Matrix MOD.187 (dry-run di default, --apply per scrivere)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Scrive la baseline (default: dry-run).")
        parser.add_argument("--base-dir", default="", help="Cartella dei CSV seed (default: docs/anagrafica/skillmatrix).")
        parser.add_argument("--baseline", default="2026-04-30", help="Snapshot baseline (default 2026-04-30).")

    def handle(self, *args, **opts):
        stats = importa_skill_matrix(
            base_dir=opts["base_dir"] or None,
            apply=opts["apply"],
            baseline=opts["baseline"],
        )
        if stats.get("errore"):
            self.stderr.write(self.style.ERROR(stats["errore"]))
            return

        prefix = "" if opts["apply"] else "[DRY-RUN] "
        op = stats["operatori"]
        ab = stats["abilitazioni"]
        self.stdout.write(self.style.SUCCESS(
            f"{prefix}Operatori: {op['risolti']}/{op['totale']} risolti "
            f"({len(op['non_risolti'])} non risolti, {len(op['ambigui'])} ambigui)."
        ))
        self.stdout.write(
            f"{prefix}Abilitazioni (baseline {stats['baseline']}): "
            f"{ab['in_lista']} in lista → create {ab['create']}, aggiornate {ab['aggiornate']}. "
            f"Storico: {stats['storico']['scatti']} scatti {stats['storico']['snapshots']}. "
            f"Contatori: {stats['contatori']}."
        )
        if stats["macchine_bloccate"]:
            self.stdout.write(self.style.WARNING(
                f"BLOCCATE (no match asset confermato): {', '.join(stats['macchine_bloccate'])}"
            ))
        if stats["processi_saltati"]:
            self.stdout.write(
                f"Righe processo non importate nello strato macchina (gestite via qualifiche): "
                f"{stats['processi_saltati']}."
            )
        if stats["competenze_sconosciute"]:
            self.stdout.write(self.style.WARNING(
                f"Competenze sconosciute (assenti dal catalogo): {', '.join(stats['competenze_sconosciute'])}"
            ))
        if stats["operatori"]["non_risolti"]:
            self.stdout.write(self.style.WARNING(
                f"Nomi non risolti: {', '.join(stats['operatori']['non_risolti'])}"
            ))
        coe = stats["coerenza_storico"]
        if coe["mismatch"]:
            self.stdout.write(self.style.WARNING(
                f"Coerenza storico: {len(coe['mismatch'])} mismatch su {coe['verificate']} verificate."
            ))
        else:
            self.stdout.write(f"Coerenza storico: OK ({coe['verificate']} verificate).")

        if not opts["apply"]:
            self.stdout.write(self.style.NOTICE(
                "STOP F2b: dry-run. Rivedere il piano, poi rilanciare con --apply per scrivere la baseline."
            ))
