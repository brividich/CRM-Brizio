"""Chi entra da amministratore su un PC: gli accessi di account privilegiati letti dal Registro log.

Il modulo Registro log legge gli accessi di Windows (``registro_log.EventoRegistro``) e sa quali account sono
privilegiati (membri dei gruppi di amministratori di Active Directory, ``registro_log.AccountAD``). Qui i due dati
si incrociano con l'asset: su quale PC entrano gli amministratori, quante volte, e se quegli account hanno una
password che non scade o appartengono a una persona cessata.

Perché conta: ogni accesso di un amministratore di dominio su una postazione lascia le sue credenziali in memoria
su quel PC; se il PC è compromesso, lo è il dominio. Su un server è normale, su un PC d'ufficio è da sapere.
Il riquadro Rischio della scheda asset usa ``per_asset``; nessun alert nuovo: gli alert sugli accessi li fa già il
Registro log (fuori orario, raffiche, gruppi privilegiati).
"""
from __future__ import annotations

from collections import Counter
from datetime import timedelta

from django.utils import timezone

GIORNI = 30
CATEGORIE_ACCESSO = ("accesso", "accesso_privilegiato")


def _norm(nome) -> str:
    return (nome or "").strip().casefold().split(".")[0]


def _sam(account) -> str:
    """«DOMINIO\\utente» e «utente@dominio» → «utente»."""
    a = (account or "").strip()
    if "\\" in a:
        a = a.split("\\", 1)[1]
    return a.split("@", 1)[0].casefold()


def nomi_host(asset) -> set[str]:
    """I nomi con cui le fonti chiamano questo asset (inventario, report SOC, Intune, nome del registro)."""
    from security.models import SecurityAsset, SoftwareInstallation

    nomi = {_norm(asset.name)}
    nomi.update(_norm(h) for h in SoftwareInstallation.objects.filter(hub_asset=asset).values_list("host", flat=True).distinct())
    nomi.update(_norm(h) for h in SecurityAsset.objects.filter(hub_asset=asset).values_list("hostname", flat=True))
    try:
        nomi.update(_norm(d.nome) for d in asset.dispositivi_intune.all())
    except Exception:  # noqa: BLE001 - senza Intune non cambia niente
        pass
    nomi.discard("")
    return nomi


def disponibile() -> bool:
    from registro_log.models import EventoRegistro

    return EventoRegistro.objects.filter(privilegiato=True).exists()


def per_asset(asset, giorni=GIORNI, oggi=None) -> dict | None:
    """Accessi di account privilegiati su questo asset negli ultimi ``giorni`` giorni, o ``None`` senza Registro log.

    ``{"giorni", "accessi", "account": [{"sam","accessi","gruppi","password_non_scade","cessato","ultimo"}]}``.
    """
    from registro_log.models import AccountAD, EventoRegistro

    nomi = nomi_host(asset)
    if not nomi or not disponibile():
        return None
    adesso = oggi or timezone.now()
    da = adesso - timedelta(days=giorni)
    conteggi, ultimo = Counter(), {}
    for host, account, quando in (EventoRegistro.objects.filter(quando__gte=da, privilegiato=True, categoria__in=CATEGORIE_ACCESSO)
                                  .exclude(esito="ko").values_list("host", "account", "quando").iterator()):
        if _norm(host) not in nomi:
            continue
        sam = _sam(account)
        if not sam:
            continue
        conteggi[sam] += 1
        if sam not in ultimo or quando > ultimo[sam]:
            ultimo[sam] = quando
    if not conteggi:
        return {"giorni": giorni, "accessi": 0, "account": []}
    schede = {a.sam.casefold(): a for a in AccountAD.objects.filter(sam__in=list(conteggi))}
    account = []
    for sam, n in conteggi.most_common():
        scheda = schede.get(sam)
        account.append({
            "sam": sam, "accessi": n, "ultimo": ultimo[sam],
            "gruppi": list(scheda.gruppi_privilegiati or []) if scheda else [],
            "password_non_scade": bool(scheda and scheda.password_non_scade),
            "cessato": bool(scheda and scheda.persona_cessata),
            "nome": scheda.anagrafica_nome or scheda.nome if scheda else "",
        })
    return {"giorni": giorni, "accessi": sum(conteggi.values()), "account": account}
