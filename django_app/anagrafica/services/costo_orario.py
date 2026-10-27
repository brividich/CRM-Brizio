"""Costo orario dei dipendenti, mese per mese (ottobre 2026).

costo orario = RML ÷ giorni ÷ ore (di regola 26 e 6,66, cioè RML ÷ 173,16).

L'RML è la voce retributiva «RML» del mese che arriva con l'import CSV dello
studio paghe; per ogni mese vale l'importazione più recente e la voce corretta
a mano da HR vince (stessa regola della scheda e della vista «Cedolini»). Il
risultato si salva in ``CostoOrarioMensile`` (uno per codice fiscale e mese),
così resta lo storico e i report non rifanno il calcolo.

Si ricalcola da solo dopo ogni import, quando HR corregge una voce RML e quando
cambiano i divisori nelle Impostazioni. Dato retributivo: si mostra solo a chi
ha il permesso HR riservato.
"""
from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from ..models import CostoOrarioMensile, DipendenteAnagraficaCivile, VoceRetributiva

VOCE_RML = "rml"
CONFIG_GIORNI = "costo_orario.divisore_giorni"
CONFIG_ORE = "costo_orario.divisore_ore"
GIORNI_DEFAULT = Decimal("26")
ORE_DEFAULT = Decimal("6.66")


def _numero(valore, default: Decimal) -> Decimal:
    try:
        d = Decimal(str(valore).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        return default
    return d if d > 0 else default


def divisori() -> tuple[Decimal, Decimal]:
    """(giorni, ore) dalle Impostazioni, con 26 e 6,66 se mancano o non sono validi."""
    from core.models import SiteConfig

    return (_numero(SiteConfig.get(CONFIG_GIORNI, "") or "", GIORNI_DEFAULT),
            _numero(SiteConfig.get(CONFIG_ORE, "") or "", ORE_DEFAULT))


def imposta_divisori(giorni, ore) -> tuple[Decimal, Decimal]:
    from core.models import SiteConfig

    valori = []
    for nome, v in (("giorni", giorni), ("ore", ore)):
        try:
            d = Decimal(str(v).strip().replace(",", "."))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"Il divisore «{nome}» non è un numero.") from exc
        if d <= 0 or d > 1000:
            raise ValueError(f"Il divisore «{nome}» deve essere maggiore di zero.")
        valori.append(d)
    for chiave, d, testo in ((CONFIG_GIORNI, valori[0], "giorni del mese"), (CONFIG_ORE, valori[1], "ore al giorno")):
        SiteConfig.objects.update_or_create(
            chiave=chiave, defaults={"valore": f"{d.normalize():f}",
                                     "descrizione": f"Costo orario: {testo} (anagrafica.services.costo_orario)"})
    return valori[0], valori[1]


def calcola(rml: Decimal, giorni: Decimal, ore: Decimal) -> Decimal:
    return (Decimal(rml) / giorni / ore).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def rml_effettive(voci) -> dict[tuple[str, date], tuple[Decimal, bool, int | None]]:
    """(codice fiscale, mese) → (RML, manuale, legacy_id) con la regola di merge dei cedolini.

    ``voci``: dict con tax_code, data_competenza, importo, manuale, legacy_anagrafica_id,
    importazione_id e data dell'importazione (``data_importazione``).
    """
    per_chiave: dict[tuple[str, date], list[dict]] = {}
    for v in voci:
        cf = (v["tax_code"] or "").strip().upper()
        if not cf:
            continue
        mese = v["data_competenza"].replace(day=1)
        per_chiave.setdefault((cf, mese), []).append(v)
    out = {}
    for chiave, gruppo in per_chiave.items():
        manuali = [v for v in gruppo if v["manuale"]]
        scelta = None
        if manuali:
            scelta = max(manuali, key=lambda v: v["pk"])
        else:
            ultima = max(gruppo, key=lambda v: (v["data_importazione"], v["importazione_id"]))
            scelta = max((v for v in gruppo if v["importazione_id"] == ultima["importazione_id"]),
                         key=lambda v: v["pk"])
        lid = next((v["legacy_anagrafica_id"] for v in gruppo if v["legacy_anagrafica_id"]), None)
        out[chiave] = (scelta["importo"], bool(scelta["manuale"]), lid)
    return out


@transaction.atomic
def ricalcola(*, mesi=None, tax_codes=None) -> int:
    """Ricalcola i costi orari (tutti, o solo i mesi / codici fiscali indicati). Restituisce quanti."""
    qs = VoceRetributiva.objects.filter(pay_item_key=VOCE_RML)
    if mesi is not None:
        mesi = {m.replace(day=1) for m in mesi}
        if not mesi:
            return 0
        qs = qs.filter(data_competenza__in=mesi)
    if tax_codes is not None:
        tax_codes = {(t or "").strip().upper() for t in tax_codes if t}
        if not tax_codes:
            return 0
        qs = qs.filter(tax_code__in=tax_codes)
    voci = [{**v, "data_importazione": v.pop("importazione__data_importazione")}
            for v in qs.values("pk", "tax_code", "data_competenza", "importo", "manuale", "legacy_anagrafica_id",
                               "importazione_id", "importazione__data_importazione")]
    effettive = rml_effettive(voci)
    giorni, ore = divisori()
    # La voce non sempre ha la persona: si ritrova dal codice fiscale.
    civile = dict(DipendenteAnagraficaCivile.objects.filter(
        codice_fiscale__in={cf for cf, _ in effettive}).values_list("codice_fiscale", "legacy_anagrafica_id"))
    civile = {(k or "").strip().upper(): v for k, v in civile.items()}
    # Via le righe di chiavi senza più RML (voce manuale cancellata e niente CSV).
    vecchie = CostoOrarioMensile.objects.all()
    if mesi is not None:
        vecchie = vecchie.filter(mese__in=mesi)
    if tax_codes is not None:
        vecchie = vecchie.filter(tax_code__in=tax_codes)
    for pk, cf, mese in vecchie.values_list("pk", "tax_code", "mese"):
        if (cf, mese) not in effettive:
            CostoOrarioMensile.objects.filter(pk=pk).delete()
    n = 0
    for (cf, mese), (rml, manuale, lid) in effettive.items():
        if rml is None or rml <= 0:
            CostoOrarioMensile.objects.filter(tax_code=cf, mese=mese).delete()
            continue
        CostoOrarioMensile.objects.update_or_create(
            tax_code=cf, mese=mese,
            defaults={"legacy_anagrafica_id": lid or civile.get(cf), "rml": rml, "rml_manuale": manuale,
                      "divisore_giorni": giorni, "divisore_ore": ore, "costo_orario": calcola(rml, giorni, ore)})
        n += 1
    return n


def ultimi(legacy_ids=None) -> dict[int, CostoOrarioMensile]:
    """``legacy_id`` → costo orario del mese più recente."""
    qs = CostoOrarioMensile.objects.filter(legacy_anagrafica_id__isnull=False)
    if legacy_ids is not None:
        qs = qs.filter(legacy_anagrafica_id__in=list(legacy_ids))
    out: dict[int, CostoOrarioMensile] = {}
    for c in qs.order_by("legacy_anagrafica_id", "-mese"):
        out.setdefault(c.legacy_anagrafica_id, c)
    return out


def storico(legacy_id: int, *, tax_code: str = "", limite: int = 12) -> list[CostoOrarioMensile]:
    from django.db.models import Q

    filtro = Q(legacy_anagrafica_id=legacy_id)
    if tax_code:
        filtro |= Q(tax_code=tax_code.strip().upper())
    return list(CostoOrarioMensile.objects.filter(filtro).order_by("-mese")[:limite])


# ── Voce RML corretta a mano: si ricalcola quel mese di quella persona ────────

def _voce_cambiata(instance: VoceRetributiva) -> None:
    if instance.pay_item_key != VOCE_RML or not instance.data_competenza:
        return
    ricalcola(mesi=[instance.data_competenza], tax_codes=[instance.tax_code])


@receiver(post_save, sender=VoceRetributiva, dispatch_uid="costo_orario_voce_salvata")
def _voce_salvata(sender, instance, raw=False, **kwargs):
    if not raw:
        _voce_cambiata(instance)


@receiver(post_delete, sender=VoceRetributiva, dispatch_uid="costo_orario_voce_cancellata")
def _voce_cancellata(sender, instance, **kwargs):
    _voce_cambiata(instance)
