"""Dotazione software attesa: cosa deve esserci sui PC di un tipo o di un reparto, e dove manca.

Le regole stanno in ``SoftwareDotazioneAttesa`` (Catalogo software › Dotazione attesa). Il confronto usa lo stesso
raggruppamento del catalogo (``software_catalog.indice_famiglie``): il programma manca se sul PC non c'è nessun
nome e nessuna release dello stesso programma. Contano solo gli asset **in uso o in riparazione, con un inventario**:
di un PC senza inventario non si sa niente (è nella scheda «PC e server senza inventario»).

Ogni numero (regole, PC mancanti, riquadro Rischio della scheda asset) viene da ``scostamenti`` e
``mancanti_per_asset``: una regola, una funzione.
"""
from __future__ import annotations

from collections import defaultdict

from assets.models import Asset, SoftwareDotazioneAttesa

STATI_ATTIVI = (Asset.STATUS_IN_USE, Asset.STATUS_IN_REPAIR)


def _programmi_per_asset(indice):
    """{asset_id: {chiave canonica dei programmi presenti}} per gli asset con inventario."""
    from security.models import SoftwareInstallation
    from security.services import software_catalog as sc

    canonici = indice[0]
    out = defaultdict(set)
    for asset_id, vendor, product in (SoftwareInstallation.objects.filter(still_detected=True, hub_asset__isnull=False)
                                      .values_list("hub_asset_id", "vendor", "product").distinct()):
        out[asset_id].add(sc.inventory_key(*canonici.get((vendor, product), (vendor, product))))
    return out


def _asset_in_ambito(regola, assets):
    reparto = regola.reparto.strip().casefold()
    return [a for a in assets if a.asset_type in regola.tipi and (not reparto or (a.reparto or "").strip().casefold() == reparto)]


def _chiave(regola, indice):
    from security.services import software_catalog as sc

    return sc.chiave_canonica(regola.programma, indice)


def scostamenti(indice=None, regole=None):
    """Per regola: PC dell'ambito con inventario che non hanno il programma.

    ``[{"regola", "mancanti": [asset], "coperti": n, "senza_inventario": n, "ambito": n}]``, le regole con più mancanti prima.
    """
    from security.services import software_catalog as sc

    regole = list(regole if regole is not None else SoftwareDotazioneAttesa.objects.all())
    if not regole:
        return []
    indice = indice or sc.indice_famiglie()
    presenti = _programmi_per_asset(indice)
    assets = list(Asset.objects.filter(status__in=STATI_ATTIVI, asset_type__in=SoftwareDotazioneAttesa.TIPI_PER_AMBITO[SoftwareDotazioneAttesa.AMBITO_TUTTI])
                  .order_by("name"))
    out = []
    for regola in regole:
        chiave = _chiave(regola, indice)
        ambito = _asset_in_ambito(regola, assets)
        con_inventario = [a for a in ambito if a.pk in presenti]
        mancanti = [a for a in con_inventario if chiave not in presenti[a.pk]]
        out.append({"regola": regola, "chiave": chiave, "mancanti": mancanti, "coperti": len(con_inventario) - len(mancanti),
                    "senza_inventario": len(ambito) - len(con_inventario), "ambito": len(ambito)})
    out.sort(key=lambda r: (-len(r["mancanti"]), str(r["regola"])))
    return out


def mancanti_per_asset(asset, indice=None) -> list[str]:
    """I programmi della dotazione attesa che mancano su questo asset (etichette), per il riquadro Rischio."""
    from security.services import software_catalog as sc

    regole = [r for r in SoftwareDotazioneAttesa.objects.all()
              if asset.asset_type in r.tipi and (not r.reparto or r.reparto.strip().casefold() == (asset.reparto or "").strip().casefold())]
    if not regole or asset.status not in STATI_ATTIVI:
        return []
    indice = indice or sc.indice_famiglie()
    presenti = _programmi_per_asset(indice).get(asset.pk)
    if not presenti:
        return []
    return sorted({(r.etichetta or r.programma) for r in regole if _chiave(r, indice) not in presenti})


def totale_mancanti(indice=None) -> int:
    """Quante coppie (regola, PC) mancano oggi: il numero della scheda «Dotazione attesa»."""
    return sum(len(r["mancanti"]) for r in scostamenti(indice))
