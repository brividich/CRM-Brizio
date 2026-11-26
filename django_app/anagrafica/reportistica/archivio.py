"""Archivio dei documenti generati: chi vede cosa, filtri, conservazione.

- Chi gestisce i modelli (``anagrafica.reportistica.manage``) vede l'archivio di tutti;
  gli altri vedono solo i documenti che hanno generato loro.
- Un documento si riscarica (o si rigenera) solo se oggi lo si potrebbe rigenerare:
  sezioni e colonne riservate ricontrollate con i permessi di adesso.
- I file con dati personali si cancellano dopo ``REPORTISTICA_ARCHIVIO_MESI`` mesi
  (di serie 12; 0 = mai): resta la riga con impronta, chi, quando e per chi.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from . import sezioni as catalogo
from .permessi import can_manage

MESI_PREDEFINITI = 12
PER_PAGINA = 25


def mesi_conservazione() -> int:
    try:
        return max(0, int(getattr(settings, "REPORTISTICA_ARCHIVIO_MESI", MESI_PREDEFINITI)))
    except (TypeError, ValueError):
        return MESI_PREDEFINITI


def visibili(request):
    """Documenti dell'archivio che ``request`` puo' vedere (senza il file)."""
    from anagrafica.models import ReportGenerato

    qs = ReportGenerato.objects.defer("contenuto").select_related("generato_da", "modello")
    if can_manage(request):
        return qs
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return qs.none()
    return qs.filter(generato_da=user)


def consentito(request, doc) -> bool:
    """Riscaricabile solo se oggi si potrebbe rigenerarlo (sezioni e colonne riservate)."""
    parametri = doc.parametri or {}
    for chiave in parametri.get("sezioni") or []:
        sezione = catalogo.get(chiave)
        if sezione is not None and not sezione.consentita(request):
            return False
    for voce in parametri.get("colonne_riservate") or []:
        chiave, _sep, colonna = str(voce).partition(":")
        sezione = catalogo.get(chiave)
        if sezione is None or colonna not in dict(sezione.colonne_per(request)):
            return False  # fail-closed: sezione sparita o colonna non piu' permessa
    return True


def scadi_vecchi(oggi: datetime | None = None) -> int:
    """Cancella i file con dati personali oltre la conservazione. Idempotente, una UPDATE."""
    from anagrafica.models import ReportGenerato

    mesi = mesi_conservazione()
    if not mesi:
        return 0
    adesso = oggi or timezone.now()
    soglia = adesso - timedelta(days=round(mesi * 30.44))
    return ReportGenerato.objects.filter(
        contiene_dati_personali=True, contenuto_eliminato_il__isnull=True, generato_il__lt=soglia,
    ).update(contenuto=b"", contenuto_eliminato_il=adesso)


def _data(raw) -> date | None:
    try:
        return date.fromisoformat(str(raw)[:10]) if raw else None
    except ValueError:
        return None


FILTRI_RAPIDI = {
    "30g": "Generati negli ultimi 30 giorni",
    "dati_personali": "Con dati personali",
    "miei": "Generati da me",
}


def filtra(qs, get, request) -> tuple:
    """Applica i filtri della querystring; ritorna (queryset, valori correnti per il form)."""
    valori = {
        "q": (get.get("q") or "").strip(),
        "filtro": get.get("filtro") if get.get("filtro") in FILTRI_RAPIDI else "",
        "modello": (get.get("modello") or "").strip(),
        "formato": get.get("formato") if get.get("formato") in ("pdf", "xlsx") else "",
        "autore": (get.get("autore") or "").strip(),
        "dal": _data(get.get("dal")),
        "al": _data(get.get("al")),
    }
    if valori["q"]:
        q = valori["q"]
        qs = qs.filter(Q(titolo__icontains=q) | Q(destinatario__icontains=q) | Q(modello_nome__icontains=q)
                       | Q(note__icontains=q))
    if valori["filtro"] == "30g":
        qs = qs.filter(generato_il__gte=timezone.now() - timedelta(days=30))
    elif valori["filtro"] == "dati_personali":
        qs = qs.filter(contiene_dati_personali=True)
    elif valori["filtro"] == "miei":
        qs = qs.filter(generato_da=request.user)
    if valori["modello"]:
        qs = qs.filter(modello_nome=valori["modello"])
    if valori["formato"]:
        qs = qs.filter(formato=valori["formato"])
    if valori["autore"].isdigit():
        qs = qs.filter(generato_da_id=int(valori["autore"]))
    tz = timezone.get_current_timezone()
    if valori["dal"]:
        qs = qs.filter(generato_il__gte=datetime.combine(valori["dal"], time.min, tzinfo=tz))
    if valori["al"]:
        qs = qs.filter(generato_il__lt=datetime.combine(valori["al"] + timedelta(days=1), time.min, tzinfo=tz))
    valori["attivi"] = any(valori[k] for k in ("q", "filtro", "modello", "formato", "autore", "dal", "al"))
    return qs, valori


def scelte_filtri(qs_visibili) -> dict:
    """Valori delle tendine, solo fra i documenti che l'utente vede."""
    modelli = sorted({m for m in qs_visibili.values_list("modello_nome", flat=True) if m}, key=str.casefold)
    autori = {}
    for uid, nome, cognome, username in (qs_visibili.exclude(generato_da=None)
                                         .values_list("generato_da_id", "generato_da__first_name",
                                                      "generato_da__last_name", "generato_da__username")
                                         .distinct()):
        autori[uid] = " ".join(x for x in (nome, cognome) if x).strip() or username
    return {"modelli": modelli, "autori": sorted(autori.items(), key=lambda kv: kv[1].casefold())}
