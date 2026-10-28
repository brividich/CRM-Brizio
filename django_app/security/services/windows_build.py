"""Release di Windows riconosciuta dalla build: abbina i PC Windows ai criteri NVD per release.

Il problema
-----------
L'NVD descrive Windows **per release**: un criterio per ``windows_10_21h2``, uno per
``windows_11_24h2``, uno per ``windows_server_2022``… L'inventario invece dice il nome del
sistema («windows 11», «Windows 11 Pro 64 bits Version 25H2») e la **build** completa
(``10.0.26200.6899``). Senza abbinamento ogni criterio di ogni CVE di Windows marcava tutti i PC
Windows «da verificare» (in produzione il 97% dei «da verificare»), e nessuna CVE di Windows
poteva risultare chiusa.

L'algoritmo (per ogni CVE)
--------------------------
1. **Criteri Windows**: i criteri ``microsoft:windows_10_*``, ``windows_11_*``,
   ``windows_server_*``. Per ognuno: *famiglia* (client o server) dal nome del CPE e *build*
   della release presa dalla versione limite del criterio stesso (``end_excluding
   10.0.22631.5472`` → 22631); se il criterio non ha versioni, dalla tabella ``BUILD_RELEASE``.
2. **PC Windows**: le installazioni del sistema operativo (nome che inizia per «windows 10»,
   «windows 11» o «windows server» con versione ``10.0.<build>.<revisione>``). La famiglia viene dal
   nome (client/server: la stessa build 17763 è Windows 10 1809 *e* Server 2019); la release dalla
   build, che è la fonte affidabile (il nome può non dire la release, «windows 11»).
3. **Abbinamento**: un PC è confrontato **solo** con i criteri della sua famiglia e della sua build.
   - criterio trovato → confronto della versione completa col range della CVE (stesso confronto
     di tutti gli altri programmi): impatta / non impatta / da verificare;
   - nessun criterio per la sua build, tutti i criteri della famiglia hanno una build nota e la
     release è **ancora supportata** da Microsoft → **non impatta**: l'NVD elenca le release
     colpite e la sua non c'è;
   - release **fuori supporto** non elencata → **da verificare** («va aggiornata»): Microsoft e l'NVD
     non elencano più le release fuori supporto anche quando sono vulnerabili;
   - build non leggibile o fuori tabella, o qualche criterio della famiglia senza build nota →
     **da verificare**, con il motivo.
4. Nel dubbio resta «da verificare», mai «sicuro». Le mappature messe a mano (``SoftwareCpeMapping``
   confermate o «non applicabile») restano rispettate.

Si accende in Impostazioni › Avvisi e automatismi › «Impatto CVE sugli asset» (``cve.windows.per_build``).
``anteprima()`` dice prima cosa cambierebbe, senza scrivere niente.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

CLIENT = "client"
SERVER = "server"

# Build → (CPE della release, nome, fine del supporto Microsoft).
# - Il CPE serve per i criteri senza versioni; la build del criterio NVD, se c'è, ha sempre la precedenza.
# - La fine del supporto è la più lunga disponibile alle aziende (LTSC/LTSB, ESU commerciali): Microsoft e
#   l'NVD smettono di elencare le release fuori supporto anche quando sono vulnerabili, quindi per una
#   release non elencata si conclude «non impatta» solo se è ancora supportata (passo 3).
#   None = data non ancora fissata (release recente). Fonte: Microsoft Lifecycle; da aggiornare quando
#   Microsoft annuncia nuove release o proroghe.
BUILD_RELEASE = {
    CLIENT: {
        10240: ("windows_10_1507", "Windows 10 1507 (LTSB 2015)", date(2025, 10, 14)),
        10586: ("windows_10_1511", "Windows 10 1511", date(2017, 10, 10)),
        14393: ("windows_10_1607", "Windows 10 1607 (LTSB 2016)", date(2026, 10, 13)),
        15063: ("windows_10_1703", "Windows 10 1703", date(2019, 10, 8)),
        16299: ("windows_10_1709", "Windows 10 1709", date(2020, 10, 13)),
        17134: ("windows_10_1803", "Windows 10 1803", date(2021, 5, 11)),
        17763: ("windows_10_1809", "Windows 10 1809 (LTSC 2019)", date(2029, 1, 9)),
        18362: ("windows_10_1903", "Windows 10 1903", date(2020, 12, 8)),
        18363: ("windows_10_1909", "Windows 10 1909", date(2022, 5, 10)),
        19041: ("windows_10_2004", "Windows 10 2004", date(2021, 12, 14)),
        19042: ("windows_10_20h2", "Windows 10 20H2", date(2023, 5, 9)),
        19043: ("windows_10_21h1", "Windows 10 21H1", date(2022, 12, 13)),
        19044: ("windows_10_21h2", "Windows 10 21H2 (LTSC 2021)", date(2027, 1, 12)),
        19045: ("windows_10_22h2", "Windows 10 22H2 (ESU)", date(2028, 10, 10)),
        22000: ("windows_11_21h2", "Windows 11 21H2", date(2024, 10, 8)),
        22621: ("windows_11_22h2", "Windows 11 22H2", date(2025, 10, 14)),
        22631: ("windows_11_23h2", "Windows 11 23H2", date(2026, 11, 10)),
        26100: ("windows_11_24h2", "Windows 11 24H2", date(2029, 10, 9)),
        26200: ("windows_11_25h2", "Windows 11 25H2", date(2028, 10, 10)),
        26300: ("windows_11_26h2", "Windows 11 26H2", None),
        28000: ("windows_11_26h1", "Windows 11 26H1", None),
    },
    SERVER: {
        6003: ("windows_server_2008", "Windows Server 2008", date(2023, 1, 10)),
        7601: ("windows_server_2008_r2", "Windows Server 2008 R2", date(2024, 1, 9)),
        9200: ("windows_server_2012", "Windows Server 2012", date(2026, 10, 13)),
        9600: ("windows_server_2012_r2", "Windows Server 2012 R2", date(2026, 10, 13)),
        14393: ("windows_server_2016", "Windows Server 2016", date(2027, 1, 12)),
        17763: ("windows_server_2019", "Windows Server 2019", date(2029, 1, 9)),
        20348: ("windows_server_2022", "Windows Server 2022", date(2031, 10, 14)),
        25398: ("windows_server_2022_23h2", "Windows Server 23H2", date(2025, 10, 24)),
        26100: ("windows_server_2025", "Windows Server 2025", date(2034, 11, 4)),
    },
}
# Le stesse release lette dal nome del CPE (per i criteri senza versioni).
CPE_BUILD = {voce[0]: build for fam in BUILD_RELEASE.values() for build, voce in fam.items()}

_CPE_WINDOWS = re.compile(r"^windows_(10|11|server)(_|$)")
_NOME_CLIENT = re.compile(r"^windows (10|11)\b")
_NOME_SERVER = re.compile(r"^windows server\b")
# 10.0.<build>.<revisione> (Windows 10/11, Server 2016 e successivi); 6.x.<build> (Server 2008/2012).
_VERSIONE = re.compile(r"^(?:10\.0|6\.[0-3])\.(\d{4,6})(?:\.(\d+))?")


@dataclass(frozen=True)
class CriterioWindows:
    criterio: dict
    famiglia: str
    build: int | None  # None = release non riconoscibile: niente conclusioni «non impatta» per la famiglia


def famiglia_cpe(product: str) -> str | None:
    """``client``/``server`` per un prodotto CPE di Windows, None per tutto il resto."""
    m = _CPE_WINDOWS.match(str(product or "").lower())
    if not m:
        return None
    return SERVER if m.group(1) == "server" else CLIENT


def build_da_versione(versione: str) -> int | None:
    """``10.0.26200.6899`` → 26200, ``6.2.9200.25000`` → 9200; None se non è una versione di Windows."""
    m = _VERSIONE.match(str(versione or "").strip())
    return int(m.group(1)) if m else None


def build_criterio(criterio: dict) -> int | None:
    """Build della release del criterio: dalle versioni limite se concordano, altrimenti dalla tabella."""
    builds = {build_da_versione(criterio.get(k)) for k in ("start_including", "start_excluding", "end_including", "end_excluding")
              if criterio.get(k)}
    if criterio.get("version") not in (None, "", "*", "-"):
        builds.add(build_da_versione(criterio.get("version")))
    builds.discard(None)
    if len(builds) == 1:
        return builds.pop()
    if len(builds) > 1:
        return None  # range che attraversa più release: non si deduce niente
    product = str(criterio.get("product") or "").lower()
    # «windows_server_2008» con versione «r2» è la 2008 R2 (così la scrive l'NVD).
    if str(criterio.get("version") or "").lower() == "r2" and f"{product}_r2" in CPE_BUILD:
        return CPE_BUILD[f"{product}_r2"]
    return CPE_BUILD.get(product)


def criteri_windows(configurations) -> list[CriterioWindows]:
    out = []
    for c in configurations or []:
        if str(c.get("vendor") or "").lower() != "microsoft":
            continue
        fam = famiglia_cpe(c.get("product"))
        if fam:
            out.append(CriterioWindows(c, fam, build_criterio(c)))
    return out


def famiglia_installazione(install) -> str | None:
    """Famiglia del sistema operativo installato, solo se nome e versione sono quelli di Windows."""
    if build_da_versione(install.version_raw) is None:
        return None
    nome = " ".join(str(install.product or "").lower().split())
    if _NOME_SERVER.match(nome):
        return SERVER
    if _NOME_CLIENT.match(nome):
        return CLIENT
    return None


def supportata(famiglia: str, build: int | None, oggi: date | None = None) -> bool | None:
    """La release è ancora supportata da Microsoft? None se la build non è in tabella (non si sa)."""
    voce = BUILD_RELEASE.get(famiglia, {}).get(build) if build else None
    if voce is None:
        return None
    if voce[2] is None:
        return True
    if oggi is None:
        from django.utils import timezone

        oggi = timezone.localdate()
    return oggi <= voce[2]


def nome_release(famiglia: str, build: int | None) -> str:
    voce = BUILD_RELEASE.get(famiglia, {}).get(build) if build else None
    if voce:
        return voce[1]
    return f"Windows {'Server ' if famiglia == SERVER else ''}build {build}" if build else "Windows (build non leggibile)"


def abbina(criteri: list[CriterioWindows], famiglia: str, build: int | None, oggi: date | None = None):
    """Passo 3: (criteri della stessa release, motivo se non si può concludere «non impatta»).

    Torna ``(lista, None)`` con i criteri da confrontare; ``([], None)`` = la release non è colpita;
    ``([], motivo)`` = da verificare.
    """
    della_famiglia = [c for c in criteri if c.famiglia == famiglia]
    if not della_famiglia:
        return [], None
    if build is None:
        return [], "versione di Windows non leggibile"
    stessi = [c for c in della_famiglia if c.build == build]
    if stessi:
        return stessi, None
    ignoti = [c for c in della_famiglia if c.build is None]
    if ignoti:
        nomi = ", ".join(sorted({c.criterio.get("product", "") for c in ignoti}))
        return [], f"la CVE ha criteri di cui non si riconosce la release ({nomi})"
    # La release non è fra quelle elencate: vale solo se Microsoft la supporta ancora.
    stato = supportata(famiglia, build, oggi)
    if stato is None:
        return [], f"build {build} non presente nella tabella delle release: aggiornare services/windows_build.py"
    if not stato:
        fine = BUILD_RELEASE[famiglia][build][2]
        return [], (f"release fuori supporto Microsoft dal {fine:%d/%m/%Y}: le CVE non la elencano più anche se è "
                    "vulnerabile, va aggiornata")
    return [], None


def anteprima(today=None) -> dict:
    """Cosa cambierebbe accendendo ``cve.windows.per_build``: solo letture, niente viene scritto.

    Per ogni CVE con criteri Windows confronta l'esito di oggi (in archivio) con quello calcolato con
    l'abbinamento per build. Conta i passaggi di esito, le release dei PC e le CVE che aprirebbero un
    alert (PC che diventano «impatta» su CVE critiche o sfruttate).
    """
    from collections import Counter

    from security.models import SecurityCveImpact, SecurityCveRecord
    from security.services import cve_impact

    ctx = cve_impact.Contesto(windows_per_build=True)
    passaggi, release, motivi = Counter(), Counter(), Counter()
    cve_con_alert, cve_toccate = set(), 0
    for record in SecurityCveRecord.objects.all():
        if not criteri_windows(record.configurations):
            continue
        cve_toccate += 1
        oggi = dict(record.impacts.values_list("host", "outcome"))
        per_host, _ = cve_impact.evaluate(record, today, ctx)
        for host, (esito, testi, _install, _data) in per_host.items():
            prima = oggi.get(host, "assente")
            if prima != esito:
                passaggi[(prima, esito)] += 1
                if esito == SecurityCveImpact.IMPACTS and prima != SecurityCveImpact.IMPACTS and cve_impact.alert_worthy(record):
                    cve_con_alert.add(record.cve_id)
            if esito == SecurityCveImpact.TO_VERIFY:
                testo = " ".join(testi)
                motivi["release fuori supporto Microsoft" if "fuori supporto" in testo else
                       "build fuori tabella" if "non presente nella tabella" in testo else
                       "release non riconoscibile" if "non si riconosce la release" in testo else
                       "versione non leggibile" if "non leggibile" in testo else
                       "inventario vecchio" if "Inventario vecchio" in testo else "altro"] += 1
    for _install, famiglia, build in ctx.windows:
        release[nome_release(famiglia, build)] += 1
    return {
        "cve": cve_toccate,
        "pc_windows": len({i.host for i, _f, _b in ctx.windows}),
        "release": release.most_common(),
        "passaggi": sorted(passaggi.items(), key=lambda kv: -kv[1]),
        "da_verificare_motivi": motivi.most_common(),
        "cve_con_nuovo_alert": sorted(cve_con_alert),
    }
