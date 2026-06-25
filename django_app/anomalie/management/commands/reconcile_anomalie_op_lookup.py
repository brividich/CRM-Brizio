from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from anomalie.views import OP_ITEM_ID_COL, _fetch_all_dict, _has_table


class Command(BaseCommand):
    help = (
        "Riconcilia le anomalie con op_lookup_id NULL agganciandole all'OP per titolo "
        "(ex_op_nominativo -> ordini_produzione), rendendo op_lookup_id la chiave canonica. "
        "Dry-run di default: scrive solo con --apply. Segnala titoli ambigui (omonimie) e non trovati (refusi)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Esegue gli UPDATE sul DB (default: solo report, nessuna scrittura).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Massimo numero di titoli OP distinti da processare (0 = nessun limite).",
        )

    def handle(self, *args, **options):
        if not (_has_table("anomalie") and _has_table("ordini_produzione")):
            raise CommandError("Tabelle 'anomalie' / 'ordini_produzione' non disponibili.")

        apply = bool(options.get("apply"))
        limit = max(0, int(options.get("limit") or 0))
        is_sqlite = connections["default"].vendor == "sqlite"
        anom_title = "ex_op_nominativo" if is_sqlite else "CAST(ex_op_nominativo AS NVARCHAR(MAX))"
        op_title = "title" if is_sqlite else "CAST(title AS NVARCHAR(MAX))"

        # Anomalie senza chiave OP, raggruppate per titolo lato Python (evita il
        # GROUP BY su NVARCHAR(MAX), non consentito da SQL Server).
        rows = _fetch_all_dict(
            f"SELECT id, {anom_title} AS title FROM anomalie "
            f"WHERE op_lookup_id IS NULL AND ex_op_nominativo IS NOT NULL"
        )
        by_title: dict[str, int] = {}
        for r in rows:
            t = str(r.get("title") or "").strip()
            if t:
                by_title[t] = by_title.get(t, 0) + 1

        if not by_title:
            self.stdout.write(self.style.SUCCESS(
                "Nessuna anomalia con op_lookup_id NULL: niente da riconciliare."
            ))
            return

        titles = sorted(by_title)
        if limit:
            titles = titles[:limit]

        self.stdout.write(
            f"Titoli OP distinti senza chiave: {len(by_title)} "
            f"(anomalie con op_lookup_id NULL: {sum(by_title.values())})"
        )
        if limit:
            self.stdout.write(f"(processo i primi {len(titles)} titoli per --limit={limit})")

        resolved = ambiguous = unmatched = updated_rows = 0
        for t in titles:
            n = by_title[t]
            ids = _fetch_all_dict(
                f"SELECT DISTINCT {OP_ITEM_ID_COL} AS sid FROM ordini_produzione "
                f"WHERE LOWER({op_title}) = LOWER(%s)",
                [t],
            )
            distinct = sorted({
                int(str(x["sid"]).strip())
                for x in ids
                if str(x.get("sid") or "").strip().isdigit()
            })
            if not distinct:
                unmatched += 1
                self.stdout.write(self.style.WARNING(
                    f"  [NON TROVATO] {t!r} ({n} anomalie) - nessun OP con questo titolo"
                ))
                continue
            if len(distinct) > 1:
                ambiguous += 1
                self.stdout.write(self.style.WARNING(
                    f"  [AMBIGUO] {t!r} ({n} anomalie) - {len(distinct)} OP candidati: {distinct}"
                ))
                continue
            sid = distinct[0]
            resolved += 1
            if apply:
                with connections["default"].cursor() as cur:
                    cur.execute(
                        f"UPDATE anomalie SET op_lookup_id = %s "
                        f"WHERE op_lookup_id IS NULL AND LOWER({anom_title}) = LOWER(%s)",
                        [sid, t],
                    )
                    updated_rows += int(cur.rowcount or 0)
                self.stdout.write(self.style.SUCCESS(
                    f"  [OK] {t!r} -> op_lookup_id={sid} ({n} anomalie aggiornate)"
                ))
            else:
                self.stdout.write(f"  [RISOLVIBILE] {t!r} -> op_lookup_id={sid} ({n} anomalie)")

        self.stdout.write("")
        riepilogo = f"Riepilogo: risolvibili={resolved} ambigui={ambiguous} non-trovati={unmatched}"
        if apply:
            self.stdout.write(self.style.SUCCESS(f"{riepilogo} | righe aggiornate={updated_rows}"))
        else:
            self.stdout.write(self.style.WARNING(f"{riepilogo} | DRY-RUN: nessuna scrittura (usa --apply per applicare)"))
