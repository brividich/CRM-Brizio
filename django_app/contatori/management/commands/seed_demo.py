"""Carica i 3 trimestri reali (Q4-2025, Q1-2026, Q2-2026) per una demo completa."""
import datetime as dt
from django.core.management.base import BaseCommand
from contatori.models import Macchina, LetturaContatori, Fattura, RigaFattura

MACCHINE = [
    ("AMMINISTRAZIONE", "2YM19959", "iR-ADV DX C5840i", "2022/181", "BASE"),
    ("PRESETTING",      "26Y06144", "iR-ADV DX C3822i", "2022/182", "BASE"),
    ("LOGISTICA",       "2YM19974", "iR-ADV DX C5840i", "2022/180", "BASE"),
    ("CQI",             "2KE28443", "iR-ADV C5535i",    "2020/124", "BASE"),
    ("CQF",             "2KE28486", "iR-ADV C5535i",    "2020/124", "BASE"),
]
# letture interne [a4_bn, a3_bn, a4_col, a3_col]
NS = {
 "2025-Q4": {"2YM19959":[110149,1244,10767,1043],"26Y06144":[18634,891,11981,6431],
             "2YM19974":[160478,580,6172,354],"2KE28443":[53772,1235,15789,200],
             "2KE28486":[149534,3312,83073,2862]},
 "2026-Q1": {"2YM19959":[119721,1331,11845,1086],"26Y06144":[20242,936,13420,7338],
             "2YM19974":[174798,594,8207,539],"2KE28443":[55048,1290,16381,226],
             "2KE28486":[152372,3324,91110,3117]},
 "2026-Q2": {"2YM19959":[129240,1457,13445,1146],"26Y06144":[21657,969,14565,7544],
             "2YM19974":[189476,605,9215,366],"2KE28443":[56037,1303,17516,248],
             "2KE28486":[155251,3343,100138,3332]},
}
NS_DATE = {"2025-Q4": dt.date(2026,1,3), "2026-Q1": dt.date(2026,4,4), "2026-Q2": dt.date(2026,7,6)}
# righe fattura per unità di fatturazione [a4_bn,a3_bn,a4_col,a3_col] alla chiusura
FORN = {
 "2025-Q4": {"2020/124":[203269,4547,98858,3062],"2022/180":[160474,580,6172,354],
             "2022/181":[110149,1244,10767,1043],"2022/182":[18634,891,11981,6431]},
 "2026-Q1": {"2020/124":[207080,4610,106939,3321],"2022/180":[173500,592,8084,359],
             "2022/181":[119014,1306,11830,1086],"2022/182":[20136,927,13382,7297]},
 "2026-Q2": {"2020/124":[210798,4646,116934,3574],"2022/180":[187917,605,9132,365],
             "2022/181":[128041,1436,13170,1139],"2022/182":[21520,965,14380,7494]},
}
FATT = {"2025-Q4":("8658/V1",dt.date(2025,12,31)),
        "2026-Q1":("1762/V1",dt.date(2026,3,31)),
        "2026-Q2":("4095/V1",dt.date(2026,6,30))}
DESCR = {"2020/124":"CQF+CQI (pool)","2022/180":"Logistica","2022/181":"Amministrazione","2022/182":"Presetting"}


class Command(BaseCommand):
    help = "Carica dati demo reali dei 3 trimestri"

    def handle(self, *args, **opts):
        LetturaContatori.objects.all().delete(); RigaFattura.objects.all().delete()
        Fattura.objects.all().delete(); Macchina.objects.all().delete()

        mac = {}
        for rep, mat, mod, contr, forn in MACCHINE:
            mac[mat] = Macchina.objects.create(reparto=rep, matricola=mat, modello=mod,
                                               contratto=contr, fornitore=forn)
        for trim, letture in NS.items():
            for mat, v in letture.items():
                LetturaContatori.objects.create(
                    macchina=mac[mat], trimestre=trim, data=NS_DATE[trim],
                    a4_bn=v[0], a3_bn=v[1], a4_col=v[2], a3_col=v[3], fonte="MANUALE")
        for trim, unita in FORN.items():
            num, al = FATT[trim]
            f = Fattura.objects.create(numero=num, data=al, fornitore="BASE",
                                       trimestre=trim, periodo_al=al)
            for contr, v in unita.items():
                RigaFattura.objects.create(fattura=f, contratto=contr, descrizione=DESCR[contr],
                                           a4_bn=v[0], a3_bn=v[1], a4_col=v[2], a3_col=v[3])
        self.stdout.write(self.style.SUCCESS(
            f"Demo caricata: {Macchina.objects.count()} macchine, "
            f"{LetturaContatori.objects.count()} letture, {Fattura.objects.count()} fatture."))
