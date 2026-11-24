"""Tendine di persone: un'unica regola per tutto il portale.

Ogni menu a tendina che elenca persone (dipendenti, utenti, capi, tecnici,
approvatori...) deve:

1. mostrare il nominativo come ``COGNOME NOME`` (``core.naming.nome_completo``);
2. essere in ordine alfabetico per cognome e poi nome;
3. non elencare chi non è più in forza.

«Non più in forza» segue la regola già usata dall'anagrafica (lista dipendenti,
organigramma): ``DipendenteAnagraficaAziendale.data_cessazione`` valorizzata.
Per gli account (``auth.User`` e ``utenti`` legacy) vale anche l'account
disattivato. Il collegamento account → persona è
``Profile.legacy_user_id`` → ``utenti.id`` → ``anagrafica_dipendenti.utente_id``.

Le funzioni lavorano con sottoquery (stesso database), così non c'è il limite di
2100 parametri di SQL Server con elenchi lunghi di cessati.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

from django import forms
from django.db.models import QuerySet

from core import naming


# ── chi non è più in forza ─────────────────────────────────────────────────

def _cessati_anagrafica_qs():
    """Sottoquery degli id ``anagrafica_dipendenti`` con rapporto cessato."""
    from anagrafica.models import DipendenteAnagraficaAziendale

    return DipendenteAnagraficaAziendale.objects.filter(
        data_cessazione__isnull=False, legacy_anagrafica_id__isnull=False
    ).values("legacy_anagrafica_id")


def _cessati_utenti_legacy_qs():
    """Sottoquery degli id ``utenti`` (legacy) la cui persona è cessata."""
    from core.legacy_models import AnagraficaDipendente

    return AnagraficaDipendente.objects.filter(
        id__in=_cessati_anagrafica_qs(), utente_id__isnull=False
    ).values("utente_id")


#: Sottoquery pubbliche, da usare in ``filter(...__in=...)`` / ``exclude(...)``.
cessati_anagrafica_subquery = _cessati_anagrafica_qs
cessati_utenti_legacy_subquery = _cessati_utenti_legacy_qs


def cessati_anagrafica_ids() -> set[int]:
    """Id ``anagrafica_dipendenti`` delle persone non più in forza."""
    return {int(v) for v in _cessati_anagrafica_qs().values_list("legacy_anagrafica_id", flat=True) if v}


def cessati_utenti_legacy_ids() -> set[int]:
    """Id ``utenti`` legacy delle persone non più in forza."""
    return {int(v) for v in _cessati_utenti_legacy_qs().values_list("utente_id", flat=True) if v}


# ── queryset pronti per le tendine ─────────────────────────────────────────

def anagrafica_in_forza(qs: QuerySet | None = None) -> QuerySet:
    """``AnagraficaDipendente`` in forza, in ordine COGNOME NOME."""
    from core.legacy_models import AnagraficaDipendente

    qs = AnagraficaDipendente.objects.all() if qs is None else qs
    return qs.exclude(id__in=_cessati_anagrafica_qs()).order_by("cognome", "nome", "id")


def utenti_legacy_in_forza(qs: QuerySet | None = None) -> QuerySet:
    """``UtenteLegacy`` attivi e in forza, in ordine di nominativo.

    ``utenti.nome`` contiene il nominativo intero (spesso già COGNOME NOME):
    l'ordine finale per cognome lo dà ``ordina_persone`` sull'etichetta.
    """
    from core.legacy_models import UtenteLegacy

    qs = UtenteLegacy.objects.all() if qs is None else qs
    return qs.filter(attivo=True).exclude(id__in=_cessati_utenti_legacy_qs()).order_by("nome", "id")


def utenti_in_forza(qs: QuerySet | None = None) -> QuerySet:
    """``auth.User`` attivi e in forza, in ordine COGNOME NOME.

    Convenzione del portale (``core.apps._user_get_full_name``): gli utenti
    nascono dal displayName AD «Cognome Nome» spezzato in due, quindi
    ``first_name`` contiene il COGNOME. L'ordine giusto è first_name, last_name.
    """
    from django.contrib.auth import get_user_model

    User = get_user_model()
    qs = User.objects.all() if qs is None else qs
    return (
        qs.filter(is_active=True)
        .exclude(profile__legacy_user_id__in=_cessati_utenti_legacy_qs())
        .order_by("first_name", "last_name", "username")
    )


# ── etichette e ordinamento ────────────────────────────────────────────────

def etichetta_utente(user: Any) -> str:
    """Nominativo ``COGNOME NOME`` di un ``auth.User`` (ripiego: username).

    Stessa resa di ``core.form_fields.user_display_label``.
    """
    if user is None:
        return ""
    from core.form_fields import user_display_label

    return user_display_label(user)


def etichetta_persona(obj: Any) -> str:
    """Nominativo ``COGNOME NOME`` di qualunque oggetto persona del portale."""
    if obj is None:
        return ""
    if hasattr(obj, "get_full_name") and hasattr(obj, "get_username"):
        return etichetta_utente(obj)
    if hasattr(obj, "cognome") or hasattr(obj, "nome"):
        testo = naming.nome_completo(getattr(obj, "nome", ""), getattr(obj, "cognome", ""))
        if testo:
            return testo
    return str(obj)


def ordina_persone(righe: Iterable[Any], etichetta: Callable[[Any], str] | None = None) -> list:
    """Ordina righe di persone per etichetta (COGNOME NOME), senza accenti né maiuscole."""
    etichetta = etichetta or etichetta_persona
    return sorted(righe, key=lambda r: naming.chiave_testo(etichetta(r)))


def utenti_legacy_per_tendina(qs: QuerySet | None = None) -> list:
    """``UtenteLegacy`` in forza pronti per una tendina: attributo ``etichetta``
    in formato COGNOME NOME e lista già ordinata.

    ``utenti.nome`` è un campo unico scritto come capitava («Luca Bova»,
    «BOVA LUCA»): quando l'account è collegato a una persona dell'anagrafica
    l'etichetta viene da lì (cognome e nome separati), altrimenti resta il
    nominativo dell'account in maiuscolo, poi l'email.
    """
    from core.legacy_models import AnagraficaDipendente

    base = utenti_legacy_in_forza(qs)
    utenti = list(base)
    nomi = {
        int(r["utente_id"]): naming.nome_completo(r["nome"], r["cognome"])
        for r in AnagraficaDipendente.objects.filter(utente_id__in=base.values("id"))
        .values("utente_id", "nome", "cognome")
        if r["utente_id"]
    } if utenti else {}
    for u in utenti:
        u.etichetta = nomi.get(u.id) or naming.normalizza_parte(u.nome) or (u.email or f"utente {u.id}")
    return ordina_persone(utenti, lambda u: u.etichetta)


# ── campi di form ──────────────────────────────────────────────────────────

class PersonaChoiceField(forms.ModelChoiceField):
    """Tendina di una persona: etichetta COGNOME NOME."""

    def label_from_instance(self, obj):  # noqa: D401
        return etichetta_persona(obj)


class PersoneMultipleChoiceField(forms.ModelMultipleChoiceField):
    """Scelta di più persone: etichetta COGNOME NOME."""

    def label_from_instance(self, obj):  # noqa: D401
        return etichetta_persona(obj)


def tendina_utenti_form(form: forms.BaseForm, nome: str) -> None:
    """Scorciatoia per un campo FK/M2M verso ``auth.User`` di un ModelForm:
    utenti in forza, COGNOME NOME, e il valore già salvato sul record resta."""
    campo = form.fields.get(nome)
    if campo is None or not hasattr(campo, "queryset"):
        return
    tieni: list = []
    istanza = getattr(form, "instance", None)
    if istanza is not None and getattr(istanza, "pk", None):
        if isinstance(campo, forms.ModelMultipleChoiceField):
            try:
                tieni = list(getattr(istanza, nome).values_list("pk", flat=True))
            except Exception:
                tieni = []
        else:
            tieni = [getattr(istanza, f"{nome}_id", None)]
    imposta_tendina_persone(campo, utenti_in_forza(), tieni=tieni)


def imposta_tendina_persone(field: forms.Field, qs: QuerySet, *, tieni: Iterable[Any] = ()) -> None:
    """Applica la regola a un campo di form già esistente (FK/M2M di un ModelForm).

    ``qs`` è già filtrato e ordinato (``utenti_in_forza``, ``anagrafica_in_forza``…).
    ``tieni``: pk da conservare anche se cessati — il valore già salvato su un
    record esistente deve restare visibile e valido nel form di modifica.
    """
    tieni = [pk for pk in tieni if pk]
    if tieni:
        model = qs.model
        qs = (qs | model.objects.filter(pk__in=tieni)).distinct().order_by(*qs.query.order_by)
    field.queryset = qs
    field.label_from_instance = etichetta_persona
