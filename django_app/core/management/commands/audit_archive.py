"""Archiviazione e pulizia dello storico dell'audit (BUILD_SPEC R0.3/R0.4).

Uso:
  manage.py audit_archive                       # = --plan (dry-run, nessuna modifica)
  manage.py audit_archive --plan [--json]
  manage.py audit_archive --run --archive-dir \\\\nas\\audit [--before 2026-10-01]
                          [--batch 20000] [--max-minutes 60] [--checkpoint]
  manage.py audit_archive --category business --older-than-months 60 [--run --archive-dir ...]
  manage.py audit_archive --restore <manifest.json|part-*.jsonl.gz> [--into-table core_auditlog_restored]
  manage.py audit_archive --prune-archives --archive-dir ... [--run]

In produzione ``--run`` lo esegue solo Brizio, dopo aver rivisto l'output di ``--plan``.
Ordine: deploy della politica → --plan → revisione → --run → backup FULL. Mai SHRINK.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core import audit_archive as svc
from core import audit_policy


class Command(BaseCommand):
    help = "Archivia e pulisce le righe di audit che la politica corrente non scriverebbe più (dry-run di default)."

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--plan", action="store_true", help="Dry-run: riepilogo per categoria/modello (default).")
        mode.add_argument("--run", action="store_true", help="Esegue archiviazione e pulizia.")
        mode.add_argument("--restore", metavar="FILE", help="Rilegge un manifest o una parte in una tabella separata.")
        parser.add_argument("--prune-archives", action="store_true",
                            help="Conservazione archivi: elenca (con --run elimina) i mesi oltre --keep-months.")
        parser.add_argument("--archive-dir", help="Cartella (UNC o locale) dell'archivio.")
        parser.add_argument("--category", choices=["policy", "business"], default="policy")
        parser.add_argument("--older-than-months", type=int, default=svc.BUSINESS_MIN_MONTHS,
                            help=f"Solo --category business (minimo {svc.BUSINESS_MIN_MONTHS}).")
        parser.add_argument("--before", help="Solo righe create prima di questa data (YYYY-MM-DD).")
        parser.add_argument("--batch", type=int, default=20000)
        parser.add_argument("--max-minutes", type=float, default=None)
        parser.add_argument("--checkpoint", action="store_true",
                            help="CHECKPOINT tra i lotti se il DB è in recovery SIMPLE (SQL Server).")
        parser.add_argument("--no-resume", action="store_true", help="Ignora lo stato di ripresa salvato.")
        parser.add_argument("--into-table", default="core_auditlog_restored")
        parser.add_argument("--keep-months", type=int, default=svc.ARCHIVE_KEEP_MONTHS)
        parser.add_argument("--json", action="store_true", help="Output JSON.")

    def handle(self, *args, **opts):
        try:
            if opts["restore"]:
                return self._restore(opts)
            if opts["prune_archives"]:
                return self._prune(opts)
            before = self._before(opts)
            if opts["run"]:
                return self._run(opts, before)
            return self._plan(opts, before)
        except svc.ArchiveError as exc:
            raise CommandError(str(exc)) from exc

    # ── helpers ──────────────────────────────────────────────────────────────

    def _before(self, opts):
        if opts["category"] == "business":
            cutoff = svc.business_cutoff(opts["older_than_months"])
            if opts["before"]:
                explicit = self._parse_date(opts["before"])
                cutoff = min(cutoff, explicit)
            return cutoff
        return self._parse_date(opts["before"]) if opts["before"] else None

    @staticmethod
    def _parse_date(text):
        try:
            return timezone.make_aware(datetime.strptime(text, "%Y-%m-%d"))
        except ValueError as exc:
            raise CommandError(f"--before non valido (atteso YYYY-MM-DD): {text}") from exc

    def _archive_dir(self, opts) -> Path:
        if not opts["archive_dir"]:
            raise CommandError("--archive-dir è obbligatorio per questa operazione.")
        return Path(opts["archive_dir"])

    def _emit(self, opts, payload: dict, lines: list[str]):
        if opts["json"]:
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        else:
            for line in lines:
                self.stdout.write(line)

    # ── modalità ─────────────────────────────────────────────────────────────

    def _plan(self, opts, before):
        stats = svc.plan(opts["category"], before, opts["batch"])
        rows = stats.as_rows()
        payload = {
            "mode": "plan",
            "category": opts["category"],
            "before": before.isoformat() if before else None,
            "policy_version": audit_policy.AUDIT_POLICY_VERSION,
            "righe_lette": stats.righe_lette,
            "righe_interessate": sum(r["righe"] for r in rows),
            "mb_stimati": round(sum(r["mb_stimati"] for r in rows), 2),
            "gruppi": rows,
        }
        lines = [
            f"audit_archive --plan (dry-run, nessuna modifica) · categoria={opts['category']} · "
            f"politica v{audit_policy.AUDIT_POLICY_VERSION}"
            + (f" · prima di {before.date()}" if before else ""),
            f"Righe lette: {stats.righe_lette} · interessate: {payload['righe_interessate']} · "
            f"MB stimati: {payload['mb_stimati']}",
            "",
            f"{'categoria':<13} {'modulo':<18} {'modello':<30} {'righe':>9} {'MB':>9}  intervallo",
        ]
        for r in rows:
            lines.append(
                f"{r['categoria']:<13} {r['modulo'][:18]:<18} {r['modello'][:30]:<30} "
                f"{r['righe']:>9} {r['mb_stimati']:>9.2f}  {(r['da'] or '')[:10]} → {(r['a'] or '')[:10]}"
            )
        if opts["category"] == "policy":
            lines += ["", "Azioni: tecnico/update_nullo → archiviate e cancellate; "
                          "contenuti → archiviate e ridotte a soli metadati. Classe A mai toccata."]
        self._emit(opts, payload, lines)

    def _run(self, opts, before):
        archive_dir = self._archive_dir(opts)
        res = svc.run(
            archive_dir,
            category=opts["category"],
            before=before,
            batch=opts["batch"],
            max_minutes=opts["max_minutes"],
            checkpoint=opts["checkpoint"],
            resume=not opts["no_resume"],
        )
        payload = {"mode": "run", "category": opts["category"], **res.__dict__}
        stato = "completato" if res.completato else "interrotto per tempo (rilanciare per riprendere)"
        self._emit(opts, payload, [
            f"audit_archive --run: {stato}",
            f"Lette {res.righe_lette} · archiviate {res.archiviate} in {res.parti} parti · "
            f"cancellate {res.cancellate} · ridotte a metadati {res.ridotte} · ultimo id {res.last_id}",
            "Prossimo passo: backup FULL del database (non fare SHRINK).",
        ])

    def _restore(self, opts):
        n = svc.restore(Path(opts["restore"]), opts["into_table"])
        self._emit(opts, {"mode": "restore", "righe": n, "tabella": opts["into_table"]},
                   [f"Ripristinate {n} righe in {opts['into_table']} (core_auditlog non toccata)."])

    def _prune(self, opts):
        archive_dir = self._archive_dir(opts)
        esiti = svc.prune_archives(archive_dir, keep_months=opts["keep_months"], apply=opts["run"])
        lines = [f"Conservazione archivi: {opts['keep_months']} mesi · "
                 + ("ESECUZIONE" if opts["run"] else "dry-run")]
        for e in esiti:
            stato = "eliminato" if e["eliminato"] else ("da eliminare" if e["verificato"] else "NON verificato: conservato")
            lines.append(f"  {e['mese']}: {stato} {'; '.join(e['errori'])}")
        if not esiti:
            lines.append("  nessun mese oltre la soglia")
        self._emit(opts, {"mode": "prune", "apply": opts["run"], "mesi": esiti}, lines)
