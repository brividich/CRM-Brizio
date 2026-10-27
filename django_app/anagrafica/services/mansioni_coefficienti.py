"""Classificazione e coefficiente delle mansioni di una persona (ottobre 2026).

Su ogni mansione svolta (persona × mansione, ``AbilitazioneMacchina``):

- **classificazione**: Diretto o Indiretto, su 1 turno (1T) o su 2 turni (2T).
  Due persone con lo stesso ruolo e la stessa mansione possono averne una
  diversa. Una persona di solito lavora sempre sullo stesso numero di turni:
  1T e 2T insieme si segnalano come «turni misti» (avviso, non blocco).
- **coefficiente**: quanto pesa la mansione sul tempo della persona. Le
  mansioni in lista e attive di una persona sommano sempre **1**.

Quando una mansione entra o esce dalla lista i coefficienti si ripartiscono da
soli (la nuova prende 1/n, le altre si riducono in proporzione; una tolta lascia
il suo peso alle altre) e la persona resta «da rivedere» finché qualcuno non
salva i coefficienti a mano. I segnali sono in fondo al file.
"""
from __future__ import annotations

from collections import Counter
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from ..models import AbilitazioneMacchina, ProfiloMansioniPersona
from ..models_skillmatrix import CLASSIFICAZIONE_CHOICES

CLASSIFICAZIONI = dict(CLASSIFICAZIONE_CHOICES)
UNO = Decimal("1")
PASSO = Decimal("0.0001")
TOLLERANZA = Decimal("0.001")


# ── Classificazione ────────────────────────────────────────────────────────────

def turno(codice: str) -> str:
    """«1T» o «2T» (vuoto se non classificata)."""
    return codice[1:] if codice in CLASSIFICAZIONI else ""


def leggi_classificazione(valore) -> str:
    """Codice da un testo libero: «D1T», «diretto 1t», «Indiretto 2T»… («» se vuoto)."""
    t = "".join(str(valore or "").split()).upper()
    if not t:
        return ""
    if t in CLASSIFICAZIONI:
        return t
    for codice, etichetta in CLASSIFICAZIONI.items():
        if t == "".join(etichetta.split()).upper():
            return codice
    raise ValueError(f"classificazione «{valore}» non valida: usa {', '.join(CLASSIFICAZIONI)}")


def leggi_coefficiente(valore) -> Decimal | None:
    """Decimale tra 0 e 1 da «0,25», «0.25», «25%» o un numero (None se vuoto)."""
    if valore in (None, ""):
        return None
    t = str(valore).strip().replace(",", ".")
    if not t:
        return None
    try:
        d = Decimal(t[:-1]) / 100 if t.endswith("%") else Decimal(t)
    except InvalidOperation as exc:
        raise ValueError(f"coefficiente «{valore}» non è un numero") from exc
    if d < 0 or d > 1:
        raise ValueError(f"coefficiente «{valore}»: deve stare tra 0 e 1")
    return d.quantize(PASSO, rounding=ROUND_HALF_UP)


def prevalente(legacy_id: int) -> str:
    """Classificazione da proporre: quella scelta per la persona, se no la più usata."""
    scelta = (ProfiloMansioniPersona.objects.filter(legacy_anagrafica_id=legacy_id)
              .values_list("classificazione_prevalente", flat=True).first())
    if scelta:
        return scelta
    usate = Counter(c for c in AbilitazioneMacchina.objects.filter(legacy_anagrafica_id=legacy_id)
                    .exclude(classificazione="").values_list("classificazione", flat=True))
    return usate.most_common(1)[0][0] if usate else ""


# ── Coefficienti ──────────────────────────────────────────────────────────────

def conteggiate(legacy_id: int):
    """Le mansioni che contano per il coefficiente: in lista, attive, del catalogo."""
    return AbilitazioneMacchina.objects.filter(legacy_anagrafica_id=legacy_id, in_lista=True,
                                               stato=AbilitazioneMacchina.STATO_ATTIVA,
                                               competenza__isnull=False)


def _conta(ab: AbilitazioneMacchina) -> bool:
    return bool(ab.in_lista and ab.stato == AbilitazioneMacchina.STATO_ATTIVA and ab.competenza_id)


def arrotonda_a_uno(valori: list[Decimal]) -> list[Decimal]:
    """Quattro decimali con somma esatta 1: il resto dell'arrotondamento va al più grande."""
    if not valori:
        return []
    out = [v.quantize(PASSO, rounding=ROUND_HALF_UP) for v in valori]
    resto = UNO - sum(out)
    if resto:
        i = max(range(len(out)), key=lambda k: (out[k], -k))
        out[i] += resto
    return out


def ripartisci(pesi: list[Decimal | None]) -> list[Decimal]:
    """Coefficienti nuovi: le righe senza peso prendono 1/n, le altre si riducono in proporzione."""
    n = len(pesi)
    if not n:
        return []
    esistenti = [p for p in pesi if p is not None and p > 0]
    if not esistenti:
        return arrotonda_a_uno([UNO / n] * n)
    nuove = sum(1 for p in pesi if p is None)
    resta = UNO - Decimal(nuove) / n
    totale = sum(esistenti)
    grezzi = [UNO / n if p is None else (p / totale * resta if p > 0 else Decimal(0)) for p in pesi]
    return arrotonda_a_uno(grezzi)


def _profilo(legacy_id: int) -> ProfiloMansioniPersona:
    return ProfiloMansioniPersona.objects.get_or_create(legacy_anagrafica_id=legacy_id)[0]


@transaction.atomic
def ribilancia(legacy_id: int, *, motivo: str = "mansioni cambiate") -> bool:
    """Riporta a 1 la somma dopo un cambio di mansioni. True se ha cambiato qualcosa."""
    righe = list(conteggiate(legacy_id).select_for_update().order_by("pk"))
    # Fuori dal conteggio il coefficiente non vale più: si svuota.
    fuori = (AbilitazioneMacchina.objects.filter(legacy_anagrafica_id=legacy_id, coefficiente__isnull=False)
             .exclude(pk__in=[r.pk for r in righe]).update(coefficiente=None))
    attuali = [r.coefficiente for r in righe]
    if righe and attuali and all(a is not None for a in attuali) and abs(sum(attuali) - UNO) <= TOLLERANZA:
        return bool(fuori)
    nuovi = ripartisci(attuali)
    for r, v in zip(righe, nuovi):
        if r.coefficiente != v:
            AbilitazioneMacchina.objects.filter(pk=r.pk).update(coefficiente=v)
    if len(righe) > 1:
        ProfiloMansioniPersona.objects.update_or_create(
            legacy_anagrafica_id=legacy_id,
            defaults={"coefficienti_da_rivedere": True, "motivo": motivo[:200]})
    return True


def _decimale(v) -> Decimal | None:
    return v if v is None or isinstance(v, Decimal) else leggi_coefficiente(v)


@transaction.atomic
def salva(legacy_id: int, righe: dict[int, tuple[str, object]], *, prevalente_scelta: str | None = None,
          user=None) -> None:
    """Salva classificazione e coefficiente di tutte le mansioni della persona.

    ``righe``: id abilitazione → (classificazione, coefficiente). Devono esserci
    tutte le mansioni che contano e i coefficienti devono sommare 1 (tolleranza
    0,001: il resto va sul più grande). Errore = ``ValueError``, niente salvato.
    """
    contano = {r.pk: r for r in conteggiate(legacy_id).select_for_update()}
    tutte = {r.pk: r for r in AbilitazioneMacchina.objects.filter(legacy_anagrafica_id=legacy_id, in_lista=True,
                                                                   competenza__isnull=False)}
    estranee = set(righe) - set(tutte)
    if estranee:
        raise ValueError("Alcune mansioni non sono di questa persona: ricarica la pagina.")
    mancanti = set(contano) - set(righe)
    if mancanti:
        raise ValueError("Mancano alcune mansioni: ricarica la pagina.")
    classi, coeff = {}, {}
    for pk, (classe, valore) in righe.items():
        classi[pk] = leggi_classificazione(classe)
        if pk in contano:
            v = _decimale(valore)
            if v is None:
                raise ValueError(f"Manca il coefficiente di «{tutte[pk].competenza.nome}».")
            coeff[pk] = v
    if contano:
        somma = sum(coeff.values())
        if abs(somma - UNO) > TOLLERANZA:
            raise ValueError(f"I coefficienti sommano {somma.normalize():f}, devono fare 1.")
        ordine = sorted(coeff)
        coeff = dict(zip(ordine, arrotonda_a_uno([coeff[k] for k in ordine])))
    for pk, r in tutte.items():
        if pk not in righe:
            continue
        campi = {}
        if r.classificazione != classi[pk]:
            campi["classificazione"] = classi[pk]
        if pk in coeff and r.coefficiente != coeff[pk]:
            campi["coefficiente"] = coeff[pk]
        if campi:
            AbilitazioneMacchina.objects.filter(pk=pk).update(**campi)
    p = _profilo(legacy_id)
    if prevalente_scelta is not None:
        p.classificazione_prevalente = leggi_classificazione(prevalente_scelta)
    p.coefficienti_da_rivedere = False
    p.motivo = ""
    p.updated_by = user if getattr(user, "pk", None) else None
    p.save()


@transaction.atomic
def imposta_coefficienti(legacy_id: int, valori: dict[int, Decimal], *, user=None) -> bool:
    """Coefficienti di alcune mansioni (gli altri restano): la somma finale deve fare 1.

    Valori uguali a quelli di oggi non cambiano niente (nemmeno «da rivedere»):
    il file Excel ricaricato tale e quale non fa niente. True se ha salvato.
    """
    attuali = list(conteggiate(legacy_id))
    if all(valori.get(r.pk, r.coefficiente) == r.coefficiente for r in attuali):
        return False
    salva(legacy_id, {r.pk: (r.classificazione, valori.get(r.pk, r.coefficiente)) for r in attuali}, user=user)
    return True


def ripartisci_uguale(legacy_id: int, *, user=None) -> None:
    righe = list(conteggiate(legacy_id).order_by("pk"))
    valori = arrotonda_a_uno([UNO / len(righe)] * len(righe)) if righe else []
    salva(legacy_id, {r.pk: (r.classificazione, v) for r, v in zip(righe, valori)}, user=user)


# ── Stato per la scheda, le liste e i report ──────────────────────────────────

def stati(legacy_ids) -> dict[int, dict]:
    """``legacy_id`` → somma, numero di mansioni, in regola, da rivedere, turni misti…"""
    ids = list({int(i) for i in legacy_ids})
    out = {i: {"n": 0, "somma": Decimal(0), "senza_coeff": 0, "senza_classe": 0, "turni": set(),
               "classi": Counter(), "da_rivedere": False, "motivo": "", "prevalente": ""} for i in ids}
    for lid, classe, coeff in (AbilitazioneMacchina.objects
                               .filter(legacy_anagrafica_id__in=ids, in_lista=True,
                                       stato=AbilitazioneMacchina.STATO_ATTIVA, competenza__isnull=False)
                               .values_list("legacy_anagrafica_id", "classificazione", "coefficiente")):
        s = out[lid]
        s["n"] += 1
        if coeff is None:
            s["senza_coeff"] += 1
        else:
            s["somma"] += coeff
        if classe:
            s["turni"].add(turno(classe))
            s["classi"][classe] += 1
        else:
            s["senza_classe"] += 1
    for p in ProfiloMansioniPersona.objects.filter(legacy_anagrafica_id__in=ids):
        out[p.legacy_anagrafica_id].update(da_rivedere=p.coefficienti_da_rivedere, motivo=p.motivo,
                                           prevalente=p.classificazione_prevalente)
    for s in out.values():
        s["in_regola"] = s["n"] == 0 or (not s["senza_coeff"] and abs(s["somma"] - UNO) <= TOLLERANZA)
        s["turni_misti"] = len(s["turni"]) > 1
        s["classe_principale"] = s["classi"].most_common(1)[0][0] if s["classi"] else ""
        s["classe_principale_label"] = CLASSIFICAZIONI.get(s["classe_principale"], "")
        s["da_controllare"] = (not s["in_regola"]) or s["da_rivedere"] or s["turni_misti"]
    return out


def stato(legacy_id: int) -> dict:
    return stati([legacy_id])[int(legacy_id)]


# ── Segnali: la ripartizione automatica ───────────────────────────────────────

@receiver(pre_save, sender=AbilitazioneMacchina, dispatch_uid="mansioni_coefficienti_pre")
def _prima(sender, instance: AbilitazioneMacchina, raw=False, **kwargs):
    if raw:
        return
    instance._contava = False
    if instance.pk:
        prima = (AbilitazioneMacchina.objects.filter(pk=instance.pk)
                 .values("in_lista", "stato", "competenza_id", "coefficiente").first())
        if prima:
            # Il coefficiente si scrive solo da questo servizio (update mirati): un
            # oggetto letto prima di una ripartizione non lo deve riportare indietro.
            instance.coefficiente = prima["coefficiente"]
            instance._contava = bool(prima["in_lista"] and prima["stato"] == AbilitazioneMacchina.STATO_ATTIVA
                                     and prima["competenza_id"])
    # Mansione nuova per la persona: si propone la sua classificazione prevalente.
    if not instance.classificazione and not instance._contava and _conta(instance):
        instance.classificazione = prevalente(instance.legacy_anagrafica_id)
        instance._classe_proposta = bool(instance.classificazione)


@receiver(post_save, sender=AbilitazioneMacchina, dispatch_uid="mansioni_coefficienti_post")
def _dopo(sender, instance: AbilitazioneMacchina, raw=False, **kwargs):
    if raw:
        return
    campi = kwargs.get("update_fields")
    if getattr(instance, "_classe_proposta", False) and campi is not None and "classificazione" not in campi:
        AbilitazioneMacchina.objects.filter(pk=instance.pk).update(classificazione=instance.classificazione)
    instance._classe_proposta = False
    ora = _conta(instance)
    if ora != getattr(instance, "_contava", False):
        nome = getattr(instance.competenza, "nome", "") if instance.competenza_id else ""
        ribilancia(instance.legacy_anagrafica_id,
                   motivo=f"{'aggiunta' if ora else 'tolta'} la mansione «{nome}»" if nome else "mansioni cambiate")
        instance.coefficiente = (AbilitazioneMacchina.objects.filter(pk=instance.pk)
                                 .values_list("coefficiente", flat=True).first())


@receiver(post_delete, sender=AbilitazioneMacchina, dispatch_uid="mansioni_coefficienti_del")
def _cancellata(sender, instance: AbilitazioneMacchina, **kwargs):
    if _conta(instance):
        ribilancia(instance.legacy_anagrafica_id, motivo="mansione cancellata")
