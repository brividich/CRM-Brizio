"""Aggancia i dipendenti all'area aziendale partendo dall'etichetta di testo.

Il reparto di una persona vive in tre posti: la colonna legacy
`anagrafica_dipendenti.reparto`, il campo testo `DipendenteAnagraficaAziendale.area`
(etichettato "Reparto" nella UI) e la FK `area_aziendale` -> AreaAziendale -> Reparto.
Solo la terza e' una relazione: i report che ragionano per reparto (copertura DPI,
matrice di presa visione delle schede di sicurezza) possono usare quella e nient'altro,
perche' un prodotto o un corso e' agganciato al *record* Reparto, non a una stringa.

Questo comando riempie la FK dove e' vuota, leggendo l'etichetta di testo. Non
indovina: risolve solo per corrispondenza di nome o tramite le due tabelle di alias
dichiarate qui sotto, e riporta senza toccare nulla tutto cio' che resta ambiguo.

    manage.py aggancia_area_da_testo                      # anteprima, non scrive
    manage.py aggancia_area_da_testo --reparto "AGG/MONT" # anteprima di un reparto
    manage.py aggancia_area_da_testo --applica            # scrive
    manage.py aggancia_area_da_testo --applica --crea-aree
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

# Etichette che sono un refuso, una sigla o una variante di un'area esistente.
# chiave: etichetta normalizzata -> valore: nome dell'AreaAziendale reale.
# Se l'area indicata non esiste, la voce viene ignorata e si prosegue con le
# regole successive: una riga qui non puo' rompere il comando.
ALIAS_AREA: dict[str, str] = {
    "CNC5G": "CN5G",              # refuso di CN5G
    "AGG": "Aggiustaggio",        # sigle delle aree di AGG/MONT
    "MONT": "Montaggio",
    "VERNICIATURA-ST": "Verniciatura",
}

# Etichette di cui si conosce il reparto ma non l'area: dentro quel reparto il
# comando cerca un'area con il nome dell'etichetta, poi una con il nome del
# reparto. Se non trova ne' l'una ne' l'altra, la crea solo con --crea-aree.
# chiave: etichetta normalizzata -> valore: nome del Reparto.
ALIAS_REPARTO: dict[str, str] = {
    "AGG": "AGG/MONT",
    "MONT": "AGG/MONT",
    "MONT/AGG": "AGG/MONT",
    "AGG/MONT": "AGG/MONT",
    "CONTROLLO": "CONTROLLO",
    "CNC": "CNC",
    "UT": "UT",
    "CNC5 - ALESATRICI": "CNC5 - ALESATRICI",
}


def normalizza(valore: str) -> str:
    """Maiuscolo, senza spazi ai bordi e con gli spazi interni compattati.

    "cnc5  -  alesatrici" e "CNC5 - ALESATRICI" sono la stessa etichetta scritta
    da due persone diverse.
    """
    return re.sub(r"\s+", " ", (valore or "").strip()).upper()


class Command(BaseCommand):
    help = "Riempie DipendenteAnagraficaAziendale.area_aziendale partendo dal campo testo `area`."

    def add_arguments(self, parser):
        parser.add_argument(
            "--applica", action="store_true",
            help="Scrive le assegnazioni. Senza questo flag il comando e' di sola lettura.",
        )
        parser.add_argument(
            "--crea-aree", action="store_true",
            help="Crea l'area aziendale mancante sotto il reparto indicato da ALIAS_REPARTO.",
        )
        parser.add_argument(
            "--reparto", default="",
            help="Limita l'operazione ai dipendenti la cui etichetta risolve a questo reparto.",
        )

    def handle(self, *args, **options):
        from anagrafica.models import AreaAziendale, DipendenteAnagraficaAziendale, Reparto

        applica = options["applica"]
        crea_aree = options["crea_aree"]
        solo_reparto = normalizza(options["reparto"])

        aree = {normalizza(a.nome): a for a in AreaAziendale.objects.select_related("reparto")}
        reparti = {normalizza(r.nome): r for r in Reparto.objects.all()}

        dipendenti = list(
            DipendenteAnagraficaAziendale.objects.filter(
                area_aziendale__isnull=True,
                data_cessazione__isnull=True,
            ).exclude(area="")
        )

        risolti: dict[int, AreaAziendale] = {}
        per_area: Counter[str] = Counter()
        irrisolti: dict[str, int] = defaultdict(int)
        da_creare: dict[str, Reparto] = {}

        for dip in dipendenti:
            etichetta = normalizza(dip.area)
            area = self._risolvi(etichetta, aree, reparti, da_creare)
            if area is None and etichetta not in da_creare:
                irrisolti[etichetta] += 1
                continue

            reparto_nome = normalizza(
                area.reparto.nome if area is not None else da_creare[etichetta].nome
            )
            if solo_reparto and reparto_nome != solo_reparto:
                continue

            if area is None:
                # Area da creare: rimandata alla fase di scrittura, sotto.
                per_area[f"{etichetta} (da creare)"] += 1
                risolti[dip.pk] = None  # type: ignore[assignment]
                continue

            risolti[dip.pk] = area
            per_area[f"{area.nome} -> {area.reparto.nome}"] += 1

        self._stampa_anteprima(per_area, irrisolti, da_creare, crea_aree)

        if not applica:
            self.stdout.write(self.style.WARNING(
                "\nAnteprima: nessuna modifica scritta. Rilancia con --applica."
            ))
            return

        scritti = 0
        with transaction.atomic():
            for etichetta, reparto in da_creare.items():
                if not crea_aree:
                    continue
                esistente = aree.get(etichetta)
                if esistente is not None and esistente.reparto_id not in (None, reparto.id):
                    # Un'area con questo nome esiste gia' sotto un altro reparto:
                    # dirottarla e' una decisione umana, non un automatismo.
                    continue
                if esistente is None:
                    esistente = AreaAziendale.objects.create(nome=etichetta.title(), reparto=reparto)
                elif esistente.reparto_id is None:
                    esistente.reparto = reparto
                    esistente.save(update_fields=["reparto"])
                aree[normalizza(esistente.nome)] = esistente

            for dip in dipendenti:
                if dip.pk not in risolti:
                    continue
                area = risolti[dip.pk]
                if area is None:
                    etichetta = normalizza(dip.area)
                    area = aree.get(etichetta)
                    if area is None:
                        continue  # area non creata (manca --crea-aree)
                dip.area_aziendale = area
                dip.save(update_fields=["area_aziendale"])
                scritti += 1

        self.stdout.write(self.style.SUCCESS(f"\nAgganciati {scritti} dipendenti."))

    # ------------------------------------------------------------------
    def _risolvi(self, etichetta, aree, reparti, da_creare):
        """Area per l'etichetta, o None se non risolvibile senza una decisione umana."""
        if etichetta in ALIAS_AREA:
            area = aree.get(normalizza(ALIAS_AREA[etichetta]))
            if area is not None:
                return area

        area = aree.get(etichetta)
        if area is not None and area.reparto_id is not None:
            return area

        nome_reparto = ALIAS_REPARTO.get(etichetta)
        if not nome_reparto:
            return None
        reparto = reparti.get(normalizza(nome_reparto))
        if reparto is None:
            return None

        # Dentro il reparto: prima un'area con il nome dell'etichetta, poi una
        # con il nome del reparto (il caso LOGISTICA/AMMINISTRAZIONE, dove
        # l'area omonima esiste gia').
        for candidato in (etichetta, normalizza(reparto.nome)):
            area = aree.get(candidato)
            if area is not None and area.reparto_id == reparto.id:
                return area

        da_creare[etichetta] = reparto
        return None

    def _stampa_anteprima(self, per_area, irrisolti, da_creare, crea_aree):
        self.stdout.write(self.style.MIGRATE_HEADING("\nAssegnazioni previste"))
        if not per_area:
            self.stdout.write("  nessuna")
        for chiave, n in per_area.most_common():
            self.stdout.write(f"  {n:4d}  {chiave}")

        if da_creare:
            titolo = "Aree da creare" if crea_aree else "Aree mancanti (servono --crea-aree)"
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n{titolo}"))
            for etichetta, reparto in sorted(da_creare.items()):
                self.stdout.write(f"  {etichetta.title()}  ->  reparto {reparto.nome}")

        if irrisolti:
            self.stdout.write(self.style.MIGRATE_HEADING(
                "\nEtichette non risolvibili (aggiungerle a ALIAS_REPARTO o ALIAS_AREA)"
            ))
            for etichetta, n in sorted(irrisolti.items(), key=lambda kv: -kv[1]):
                self.stdout.write(f"  {n:4d}  {etichetta}")
