"""Check di integrita' delle scadenze HR (visite, formazione, qualifiche, DPI). SOLA LETTURA.

Uso:
    python manage.py verifica_scadenze_hr
    python manage.py verifica_scadenze_hr --area formazione --area dpi --righe 0
    python manage.py verifica_scadenze_hr --legacy-id 42
    python manage.py verifica_scadenze_hr --settings=config.settings.prod_readonly

I controlli stanno in ``anagrafica.services.integrita_scadenze``. Non scrive
nulla; per ogni anomalia indica il rimedio. Esce con codice 1 se trova errori
(utile in script), 0 se ci sono solo avvisi o niente.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Verifica (sola lettura) la coerenza delle scadenze HR: visite, formazione, qualifiche, DPI."
    aree_predefinite: tuple[str, ...] | None = None

    def add_arguments(self, parser) -> None:
        from anagrafica.services.integrita_scadenze import AREE

        if self.aree_predefinite is None:
            parser.add_argument("--area", action="append", dest="aree", choices=AREE,
                                help="Solo quest'area (ripetibile). Default: tutte.")
        parser.add_argument("--legacy-id", type=int, action="append", dest="legacy_ids",
                            help="Solo questa persona (ripetibile).")
        parser.add_argument("--righe", type=int, default=20,
                            help="Righe di dettaglio per controllo (default 20, 0 = tutte).")
        parser.add_argument("--vuote", action="store_true", help="Mostra anche i controlli senza anomalie.")

    def handle(self, *args, **options) -> None:
        from anagrafica.services.integrita_scadenze import AREE, verifica

        aree = self.aree_predefinite or options.get("aree") or AREE
        sezioni = verifica(aree, options["legacy_ids"])
        limite = options["righe"]
        stili = {"errore": self.style.ERROR, "avviso": self.style.WARNING, "info": self.style.HTTP_INFO}
        area_corrente = None
        totali = {"errore": 0, "avviso": 0, "info": 0}
        for s in sezioni:
            totali[s.gravita] += len(s.righe)
            if not s.righe and not options["vuote"]:
                continue
            if s.area != area_corrente:
                area_corrente = s.area
                self.stdout.write("")
                self.stdout.write(self.style.MIGRATE_HEADING(f"== {s.area.upper()} =="))
            stile = stili[s.gravita] if s.righe else self.style.SUCCESS
            self.stdout.write(stile(f"[{s.gravita}] {s.titolo}: {len(s.righe)}"))
            if s.righe and s.rimedio:
                self.stdout.write(f"    rimedio: {s.rimedio}")
            mostrate = s.righe if limite <= 0 else s.righe[:limite]
            for riga in mostrate:
                self.stdout.write(f"  - {riga}")
            if len(mostrate) < len(s.righe):
                self.stdout.write(f"  ... altre {len(s.righe) - len(mostrate)} (usa --righe 0)")

        self.stdout.write("")
        self.stdout.write(f"Aree: {', '.join(aree)} · errori {totali['errore']} · avvisi {totali['avviso']} "
                          f"· informativi {totali['info']}")
        if totali["errore"]:
            self.stdout.write(self.style.ERROR("Anomalie da correggere."))
            raise SystemExit(1)
        self.stdout.write(self.style.SUCCESS("Nessun errore."))
