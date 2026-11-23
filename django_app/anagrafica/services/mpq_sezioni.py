"""Sezioni dedicate dei processi qualificati (MOD.128): sigle, indirizzi e voci di menu.

Un processo con la spunta «Crea sezione dedicata» ha una pagina sua in Qualifiche
(``/anagrafica/mod128/sezione/<sigla>/``) e/o in Asset (``/assets/processi/<sigla>/``).
Più processi con la stessa sigla finiscono nella stessa pagina. Le voci di menu nascono
e spariscono al salvataggio del processo (``sincronizza_menu``): due URL parametrici,
quindi nessun permesso nuovo per ogni processo.
"""
from __future__ import annotations

import logging
import re

from django.urls import NoReverseMatch, reverse

logger = logging.getLogger(__name__)

SIGLA_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{1,29}$")
CODICE_BOTTONE = "sezione-"  # prefisso delle voci della sidebar Asset create da qui


def normalizza_sigla(valore) -> str:
    return re.sub(r"\s+", "", str(valore or "")).upper()


def url_qualifiche(sigla: str) -> str:
    try:
        return reverse("anagrafica:mpq_sezione", args=[sigla])
    except NoReverseMatch:
        return f"/anagrafica/mod128/sezione/{sigla}/"


def url_asset(sigla: str) -> str:
    try:
        return reverse("assets:processo_sezione", args=[sigla])
    except NoReverseMatch:
        return f"/assets/processi/{sigla}/"


def _prefisso(funzione) -> str:
    return funzione("X")[:-2]


def codice_bottone(sigla: str) -> str:
    return (CODICE_BOTTONE + re.sub(r"[^a-z0-9_-]", "-", sigla.lower()))[:80]


def processi_della_sigla(sigla: str, Processo=None):
    if Processo is None:
        from anagrafica.models_mpq import ProcessoQualificato as Processo
    return Processo.objects.filter(sezione_dedicata=True, sezione_sigla__iexact=normalizza_sigla(sigla))


def sezioni_attive(Processo=None) -> list[dict]:
    """Una riga per sigla: titolo (del primo processo che lo ha), dove compare, processi."""
    if Processo is None:
        from anagrafica.models_mpq import ProcessoQualificato as Processo
    per_sigla: dict[str, dict] = {}
    for p in (Processo.objects.filter(sezione_dedicata=True).exclude(sezione_sigla="")
              .order_by("sezione_sigla", "nome", "id")):
        sigla = normalizza_sigla(p.sezione_sigla)
        voce = per_sigla.setdefault(sigla, {"sigla": sigla, "titolo": "", "qualifiche": False, "asset": False,
                                            "processi": []})
        voce["titolo"] = voce["titolo"] or (p.sezione_titolo or "").strip()
        voce["qualifiche"] |= p.sezione_dove != "ASSET"
        voce["asset"] |= p.sezione_dove != "QUALIFICHE"
        voce["processi"].append(p.pk)
    for voce in per_sigla.values():
        voce["etichetta"] = f"{voce['sigla']} – {voce['titolo']}" if voce["titolo"] else voce["sigla"]
        voce["url_qualifiche"] = url_qualifiche(voce["sigla"])
        voce["url_asset"] = url_asset(voce["sigla"])
    return list(per_sigla.values())


def etichetta_automatica(etichetta: str, sigla: str) -> bool:
    """L'etichetta è quella scritta da qui (``SIGLA`` o ``SIGLA – titolo``), non una rinominata a mano."""
    testo = (etichetta or "").strip()
    return testo.upper() == sigla.upper() or testo.upper().startswith(f"{sigla.upper()} – ")


def sincronizza_menu(*, Processo=None, Link=None, Bottone=None) -> None:
    """Allinea le voci di menu alle sezioni attive.

    Crea le voci mancanti (accanto a «Processi qualificati» e a «PART 145»), toglie quelle
    di sigle non più attive. Una voce già presente non si sposta; in Qualifiche l'etichetta
    segue il titolo della sezione finché comincia con la sigla (``etichetta_automatica``):
    se qualcuno l'ha rinominata a mano dal menu, resta com'è.
    """
    if Processo is None:
        from anagrafica.models_mpq import ProcessoQualificato as Processo
    if Link is None:
        from anagrafica.models import SubnavLinkAnagrafica as Link
    if Bottone is None:
        from assets.models import AssetSidebarButton as Bottone

    attive = sezioni_attive(Processo)

    # ── Qualifiche (subnav anagrafica) ───────────────────────────────────────
    prefisso = _prefisso(url_qualifiche)
    vogliono = {v["url_qualifiche"]: v for v in attive if v["qualifiche"]}
    esistenti = {lk.url_value: lk for lk in Link.objects.filter(url_value__startswith=prefisso)}
    for url, lk in esistenti.items():
        if url not in vogliono:
            lk.delete()
            continue
        nuova = vogliono[url]["etichetta"][:80]
        if lk.etichetta != nuova and etichetta_automatica(lk.etichetta, vogliono[url]["sigla"]):
            lk.etichetta = nuova
            lk.save(update_fields=["etichetta"])
    vicino = Link.objects.filter(url_value="anagrafica:mpq_cruscotto").order_by("-is_active", "id").first()
    for n, (url, voce) in enumerate(sorted(vogliono.items()), start=1):
        if url in esistenti or vicino is None:
            continue
        Link.objects.create(
            url_value=url, url_type="raw", etichetta=voce["etichetta"][:80], icona="", gruppo=vicino.gruppo,
            categoria=vicino.categoria, ordine=(vicino.ordine or 0) + n, active_view_names="",
            is_active=True, is_sistema=False,
        )

    # ── Asset (sidebar) ──────────────────────────────────────────────────────
    vogliono_b = {codice_bottone(v["sigla"]): v for v in attive if v["asset"]}
    for b in Bottone.objects.filter(code__startswith=CODICE_BOTTONE):
        if b.code not in vogliono_b:
            b.delete()
    gia = set(Bottone.objects.filter(code__in=list(vogliono_b)).values_list("code", flat=True))
    vicina = Bottone.objects.filter(code="part_145_list").first()
    for n, (codice, voce) in enumerate(sorted(vogliono_b.items()), start=1):
        if codice in gia:
            continue
        Bottone.objects.create(
            code=codice, section=vicina.section if vicina else "OPERATIONS",
            parent=vicina.parent if vicina else None, label=voce["sigla"][:80], target_url=voce["url_asset"],
            active_match=voce["url_asset"], is_subitem=vicina.is_subitem if vicina else False,
            sort_order=(vicina.sort_order if vicina else 70) + n, is_visible=True,
        )


def sincronizza_menu_sicuro() -> None:
    """Dal salvataggio del processo: un errore sul menu non blocca il salvataggio."""
    try:
        sincronizza_menu()
    except Exception:
        logger.exception("Sezioni dedicate MOD.128: voci di menu non aggiornate")
