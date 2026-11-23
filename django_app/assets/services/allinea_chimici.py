"""Allineamento tra Schede di sicurezza (``ProdottoChimico``) e inventario asset.

Fonte di verità: il prodotto in Schede di sicurezza. Per ogni prodotto:

- attivo senza asset → si crea l'asset «Prodotto chimico» nella categoria chimica;
- nome diverso → l'asset prende il nome del prodotto;
- prodotto disattivato → l'asset collegato viene dismesso;
- prodotto riattivato → l'asset dismesso torna «In uso».

Gli asset senza prodotto non si toccano. Ogni cambio di stato passa dallo storico
asset. Usato dal pulsante «Allinea con l'inventario asset» e dal salvataggio del
prodotto.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Differenze:
    da_creare: list = field(default_factory=list)  # prodotti
    da_rinominare: list = field(default_factory=list)  # (asset, nuovo_nome)
    da_dismettere: list = field(default_factory=list)  # asset
    da_riattivare: list = field(default_factory=list)  # asset

    @property
    def totale(self) -> int:
        return len(self.da_creare) + len(self.da_rinominare) + len(self.da_dismettere) + len(self.da_riattivare)


def _nome(value) -> str:
    return " ".join(str(value or "").split())


def _differenze_prodotto(prodotto, asset, out: Differenze) -> None:
    from ..models import Asset

    if asset is None:
        if prodotto.attivo:
            out.da_creare.append(prodotto)
        return
    nome = _nome(prodotto.nome)[:200]
    if nome and _nome(asset.name) != nome:
        out.da_rinominare.append((asset, nome))
    if not prodotto.attivo and asset.status != Asset.STATUS_RETIRED:
        out.da_dismettere.append(asset)
    elif prodotto.attivo and asset.status == Asset.STATUS_RETIRED:
        out.da_riattivare.append(asset)


def differenze(prodotti=None) -> Differenze:
    """Cosa cambierebbe l'allineamento (senza scrivere). ``prodotti``: queryset/lista, default tutti."""
    from schede_sicurezza.models import ProdottoChimico

    from ..models import Asset

    if prodotti is None:
        prodotti = ProdottoChimico.objects.all()
    prodotti = list(prodotti)
    assets = {
        a.prodotto_chimico_id: a
        for a in Asset.objects.filter(prodotto_chimico_id__in=[p.pk for p in prodotti]).only(
            "id", "name", "status", "prodotto_chimico_id"
        )
    }
    out = Differenze()
    for prodotto in prodotti:
        _differenze_prodotto(prodotto, assets.get(prodotto.pk), out)
    return out


def allinea(prodotti=None, *, utente=None, dettaglio: str = "Allineamento con Schede di sicurezza") -> Differenze:
    """Applica le differenze e le restituisce (per il messaggio all'utente)."""
    from ..models import Asset, AssetFieldHistory
    from .storico_asset import traccia

    diff = differenze(prodotti)
    if not diff.totale:
        return diff
    esistenti = [a.pk for a, _ in diff.da_rinominare] + [a.pk for a in diff.da_dismettere + diff.da_riattivare]
    with traccia(esistenti, fonte=AssetFieldHistory.FONTE_JOB, utente=utente, dettaglio=dettaglio) as storico:
        categoria = Asset.default_chemical_category() if diff.da_creare else None
        for prodotto in diff.da_creare:
            nuovo = Asset.objects.create(
                name=_nome(prodotto.nome)[:200] or f"Prodotto {prodotto.pk}",
                asset_type=Asset.TYPE_CHEMICAL,
                prodotto_chimico=prodotto,
                asset_category=categoria,
            )
            storico.aggiungi(nuovo.pk)
        for asset, nome in diff.da_rinominare:
            Asset.objects.filter(pk=asset.pk).update(name=nome)
        if diff.da_dismettere:
            Asset.objects.filter(pk__in=[a.pk for a in diff.da_dismettere]).update(status=Asset.STATUS_RETIRED)
        if diff.da_riattivare:
            Asset.objects.filter(pk__in=[a.pk for a in diff.da_riattivare]).update(status=Asset.STATUS_IN_USE)
    return diff


def riepilogo(diff: Differenze) -> str:
    """Frase breve per il messaggio dopo l'allineamento."""
    parti = []
    if diff.da_creare:
        parti.append(f"{len(diff.da_creare)} asset creati")
    if diff.da_rinominare:
        parti.append(f"{len(diff.da_rinominare)} rinominati")
    if diff.da_dismettere:
        parti.append(f"{len(diff.da_dismettere)} dismessi")
    if diff.da_riattivare:
        parti.append(f"{len(diff.da_riattivare)} riattivati")
    return ", ".join(parti) if parti else "Già allineati: nessuna modifica."
