"""Viste anagrafica — Struttura organizzativa: aree, ruoli, mansioni, organigramma.

Spacchettamento di ``anagrafica/views.py`` (18/10/2026): le funzioni condivise stanno in
``_helpers`` e si chiamano ``_helpers.nome`` così i test patchano un solo punto.
"""
from __future__ import annotations

import logging
from datetime import date

from django.contrib import messages
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
# Alias esplicito: in questo file `timezone` è già importato dentro varie
# funzioni (come `tz`/`_tz`) e `datetime.timezone` è un'altra cosa ancora.
from django.views.decorators.http import require_POST

from django.contrib.auth.decorators import login_required
from core import naming
from core.legacy_anagrafica import (
    ensure_anagrafica_schema,
    fetch_anagrafica_rows,
)
from core.legacy_utils import get_legacy_user

from ..models import (
    AreaAziendale,
    Reparto,
    DipendenteAnagraficaAziendale,
    DipendenteRuoloOperativo,
    Mansione,
    AmbitoRuolo,
    RuoloOperativo,
    RuoloQualifica,
    TipoQualifica,
    TipoVisitaMedica,
)
from ..services import mansionario as mansionario_service


from . import _helpers  # noqa: E402

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Ruoli operativi — gestione catalogo
# ---------------------------------------------------------------------------

def _parse_role_id(raw) -> int | None:
    """Interpreta l'id di un ruolo da POST (``None`` se assente/non valido)."""
    try:
        value = int(str(raw or "").strip())
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _riporta_a_valido(ruolo_id: int | None, riporta_a_id: int | None) -> bool:
    """True se assegnare ``riporta_a`` non crea un ciclo (né un self-loop).

    Risale la catena ``riporta_a`` a partire dal candidato: se incontra
    ``ruolo_id`` la relazione chiuderebbe un ciclo → non valida.
    """
    if not riporta_a_id:
        return True
    if riporta_a_id == ruolo_id:
        return False
    seen: set[int] = set()
    current = RuoloOperativo.objects.filter(pk=riporta_a_id).select_related("riporta_a").first()
    while current is not None and current.pk not in seen:
        if current.pk == ruolo_id:
            return False
        seen.add(current.pk)
        current = current.riporta_a
    return True


def _parse_int(raw, default: int) -> int:
    raw = (raw or "").strip()
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _parse_ambito_id(raw) -> int | None:
    """Id dell'ambito scelto nel form, o ``None`` per «Non classificato»."""
    raw = (raw or "").strip()
    if not raw.isdigit():
        return None
    return int(raw) if AmbitoRuolo.objects.filter(pk=int(raw)).exists() else None


def _parse_ambito_filtro(request) -> int | None:
    """``?ambito=<id>`` per l'organigramma; ``?ambito=senza`` = ruoli non classificati.

    ``None`` (parametro assente) significa «tutti gli ambiti insieme», che resta
    la vista di default: l'organizzazione completa.
    """
    raw = (request.GET.get("ambito") or "").strip()
    if raw == "senza":
        return 0
    if raw.isdigit() and AmbitoRuolo.objects.filter(pk=int(raw)).exists():
        return int(raw)
    return None


def _ambito_filtro_context(ambito_id: int | None) -> dict:
    return {
        "ambiti_filtro": list(AmbitoRuolo.objects.filter(is_active=True)),
        "ambito_sel": "senza" if ambito_id == 0 else (str(ambito_id) if ambito_id else ""),
    }


@login_required
def ruoli_operativi_list(request):
    legacy_user = get_legacy_user(request.user)
    is_admin = _helpers._is_anagrafica_admin(request)

    ruoli = list(
        RuoloOperativo.objects
        .annotate(n_assegnati=Count("assegnazioni"))
        .select_related("riporta_a", "ambito")
        .order_by("nome")
    )
    # Ordinamento per ambito in Python: su SQL Server un ORDER BY su colonne
    # della tabella collegata insieme all'annotate finisce in errore 8127.
    ruoli.sort(key=lambda r: (
        r.ambito.ordine if r.ambito_id else 9999,
        (r.ambito.nome if r.ambito_id else "").casefold(),
        (r.nome or "").casefold(),
    ))
    _da_scheda = _helpers._ruoli_conteggio_da_scheda()
    for _r in ruoli:
        _r.n_da_scheda = _da_scheda.get((_r.nome or "").strip().casefold(), 0)
    # Qualifiche attese dal ruolo: l'associazione si costruisce a mano dal
    # portale (l'export del gestionale è arrivato senza la matrice skill).
    _qualifiche_per_ruolo: dict[int, list] = {}
    for _rq in RuoloQualifica.objects.select_related("qualifica").order_by("qualifica__nome"):
        _qualifiche_per_ruolo.setdefault(_rq.ruolo_id, []).append(_rq)
    for _r in ruoli:
        _r.qualifiche = _qualifiche_per_ruolo.get(_r.id, [])
    qualifiche_catalogo = list(
        TipoQualifica.objects.filter(is_active=True).order_by("categoria", "nome")
    )
    # Catalogo per il dropdown «riporta a» (tutti i ruoli, incluso lo storico).
    ruoli_catalogo = list(RuoloOperativo.objects.order_by("nome").values("id", "nome"))
    ruoli_suggeriti = [
        "Preposto", "RSPP", "ASPP", "RLS",
        "Squadra antincendio", "Squadra primo soccorso",
        "Addetto emergenze", "Rappresentante sicurezza",
    ]
    return render(request, "anagrafica/pages/ruoli_operativi.html", {
        "ruoli": ruoli,
        "qualifiche_catalogo": qualifiche_catalogo,
        "ruoli_catalogo": ruoli_catalogo,
        "is_admin": is_admin,
        "ruoli_suggeriti": ruoli_suggeriti,
        **_helpers._ambiti_context(ruoli),
    })


@login_required
@require_POST
def ruolo_operativo_create(request):
    legacy_user = get_legacy_user(request.user)
    if not _helpers._is_anagrafica_admin(request):
        messages.error(request, "Non hai i permessi per creare ruoli operativi.")
        return _helpers._back_to_caller(request, "anagrafica:ruoli_operativi_list")

    nome = (request.POST.get("nome") or "").strip()[:100]
    if not nome:
        messages.error(request, "Il nome del ruolo è obbligatorio.")
        return _helpers._back_to_caller(request, "anagrafica:ruoli_operativi_list")

    ruolo, created = RuoloOperativo.objects.get_or_create(
        nome__iexact=nome,
        defaults={
            "nome": nome,
            "descrizione": (request.POST.get("descrizione") or "").strip(),
            "colore": (request.POST.get("colore") or "#64748b").strip()[:7],
            "icona": (request.POST.get("icona") or "").strip()[:10],
            "certificazione_competenza": (request.POST.get("certificazione_competenza") or "").strip()[:200],
            "ambito_id": _parse_ambito_id(request.POST.get("ambito")),
        },
    )
    if created:
        riporta_a_id = _parse_role_id(request.POST.get("riporta_a"))
        if riporta_a_id and _riporta_a_valido(ruolo.pk, riporta_a_id):
            ruolo.riporta_a_id = riporta_a_id
            ruolo.save(update_fields=["riporta_a"])
        messages.success(request, f'Ruolo "{nome}" creato.')
    else:
        messages.warning(request, f'Esiste già un ruolo con il nome "{nome}".')
    return _helpers._back_to_caller(request, "anagrafica:ruoli_operativi_list")


@login_required
@require_POST
def ruolo_operativo_edit(request, ruolo_id: int):
    legacy_user = get_legacy_user(request.user)
    if not _helpers._is_anagrafica_admin(request):
        messages.error(request, "Non hai i permessi per modificare ruoli operativi.")
        return _helpers._back_to_caller(request, "anagrafica:ruoli_operativi_list")

    ruolo = get_object_or_404(RuoloOperativo, pk=ruolo_id)
    nome = (request.POST.get("nome") or "").strip()[:100]
    if not nome:
        messages.error(request, "Il nome del ruolo è obbligatorio.")
        return _helpers._back_to_caller(request, "anagrafica:ruoli_operativi_list")

    if nome != ruolo.nome:
        # Il «Ruolo aziendale» delle schede è un testo abbinato per nome: la rinomina lo riscrive
        # e tiene il nome di prima fra i nomi precedenti.
        from ..services.struttura_ruoli import rinomina

        try:
            rinomina(ruolo, nome, user=request.user)
        except ValueError as exc:
            messages.error(request, str(exc))
            return _helpers._back_to_caller(request, "anagrafica:ruoli_operativi_list")
    ruolo.descrizione = (request.POST.get("descrizione") or "").strip()
    ruolo.colore = (request.POST.get("colore") or "#64748b").strip()[:7]
    ruolo.icona = (request.POST.get("icona") or "").strip()[:10]
    ruolo.certificazione_competenza = (request.POST.get("certificazione_competenza") or "").strip()[:200]
    ruolo.ambito_id = _parse_ambito_id(request.POST.get("ambito"))
    riporta_a_id = _parse_role_id(request.POST.get("riporta_a"))
    if riporta_a_id and _riporta_a_valido(ruolo.pk, riporta_a_id):
        ruolo.riporta_a_id = riporta_a_id
    else:
        if riporta_a_id and not _riporta_a_valido(ruolo.pk, riporta_a_id):
            messages.warning(request, "Relazione «riporta a» ignorata: creerebbe un ciclo nella gerarchia.")
        ruolo.riporta_a = None
    ruolo.is_active = request.POST.get("is_active") == "1"
    ruolo.save()
    messages.success(request, f'Ruolo "{ruolo.nome}" aggiornato.')
    return _helpers._back_to_caller(request, "anagrafica:ruoli_operativi_list")


@login_required
@require_POST
def ruolo_operativo_delete(request, ruolo_id: int):
    legacy_user = get_legacy_user(request.user)
    if not _helpers._is_anagrafica_admin(request):
        messages.error(request, "Non hai i permessi per eliminare ruoli operativi.")
        return _helpers._back_to_caller(request, "anagrafica:ruoli_operativi_list")

    ruolo = get_object_or_404(RuoloOperativo, pk=ruolo_id)
    n_uso = ruolo.assegnazioni.count()
    if n_uso:
        if ruolo.is_active:
            ruolo.is_active = False
            ruolo.save(update_fields=["is_active"])
            messages.warning(request, f'"{ruolo.nome}" è in uso ({n_uso} assegnazioni): disattivato (non eliminato) per preservare lo storico. Puoi riattivarlo dalla modifica.')
        else:
            messages.error(request, f'"{ruolo.nome}" ha {n_uso} assegnazioni: non eliminabile (già disattivo).')
        return _helpers._back_to_caller(request, "anagrafica:ruoli_operativi_list")
    nome = ruolo.nome
    ruolo.delete()
    messages.success(request, f'Ruolo "{nome}" eliminato.')
    return _helpers._back_to_caller(request, "anagrafica:ruoli_operativi_list")


@login_required
@require_POST
def ruolo_qualifica_aggiungi(request, ruolo_id: int):
    """Associa una qualifica attesa al ruolo (dal catalogo, a mano).

    L'associazione dichiara *cosa serve* per ricoprire il ruolo: non certifica
    nessuno — chi la possiede davvero lo dicono le qualifiche del dipendente.
    """
    if not _helpers._is_anagrafica_admin(request):
        messages.error(request, "Non hai i permessi per gestire le qualifiche dei ruoli.")
        return _helpers._back_to_caller(request, "anagrafica:ruoli_operativi_list")

    ruolo = get_object_or_404(RuoloOperativo, pk=ruolo_id)
    qualifica_id = _parse_role_id(request.POST.get("qualifica_id"))
    if not qualifica_id:
        messages.error(request, "Scegli la qualifica da associare.")
        return _helpers._back_to_caller(request, "anagrafica:ruoli_operativi_list")

    qualifica = get_object_or_404(TipoQualifica, pk=qualifica_id)
    _, creata = RuoloQualifica.objects.get_or_create(
        ruolo=ruolo, qualifica=qualifica,
        defaults={
            "livello": (request.POST.get("livello") or "").strip()[:50],
            "obbligatoria": request.POST.get("obbligatoria") != "0",
            "note": (request.POST.get("note") or "").strip()[:200],
        },
    )
    if creata:
        messages.success(request, f'"{qualifica.nome}" ora è richiesta dal ruolo "{ruolo.nome}".')
    else:
        messages.info(request, f'"{qualifica.nome}" era già associata a "{ruolo.nome}".')
    return _helpers._back_to_caller(request, "anagrafica:ruoli_operativi_list")


@login_required
@require_POST
def ruolo_qualifica_rimuovi(request, ruolo_id: int, assoc_id: int):
    if not _helpers._is_anagrafica_admin(request):
        messages.error(request, "Non hai i permessi per gestire le qualifiche dei ruoli.")
        return _helpers._back_to_caller(request, "anagrafica:ruoli_operativi_list")

    assoc = get_object_or_404(RuoloQualifica, pk=assoc_id, ruolo_id=ruolo_id)
    nome = assoc.qualifica.nome
    assoc.delete()
    messages.success(request, f'"{nome}" non è più richiesta dal ruolo.')
    return _helpers._back_to_caller(request, "anagrafica:ruoli_operativi_list")


# ---------------------------------------------------------------------------
# Ambiti dei ruoli — produttivo, esecutivo, ISO 45001, ISO 27001, …
# ---------------------------------------------------------------------------

@login_required
@require_POST
def ambito_ruolo_create(request):
    if not _helpers._is_anagrafica_admin(request):
        messages.error(request, "Non hai i permessi per gestire gli ambiti dei ruoli.")
        return _helpers._back_to_caller(request, "anagrafica:ruoli_operativi_list")

    nome = (request.POST.get("nome") or "").strip()[:100]
    if not nome:
        messages.error(request, "Il nome dell'ambito è obbligatorio.")
        return _helpers._back_to_caller(request, "anagrafica:ruoli_operativi_list")

    if AmbitoRuolo.objects.filter(nome__iexact=nome).exists():
        messages.warning(request, f'Esiste già un ambito "{nome}".')
        return _helpers._back_to_caller(request, "anagrafica:ruoli_operativi_list")

    ambito = AmbitoRuolo(
        nome=nome,
        descrizione=(request.POST.get("descrizione") or "").strip(),
        colore=(request.POST.get("colore") or "#64748b").strip()[:7],
        icona=(request.POST.get("icona") or "").strip()[:10],
        ordine=_parse_int(request.POST.get("ordine"), 100),
        alimenta_scheda=request.POST.get("alimenta_scheda") == "1",
    )
    ambito.save()
    messages.success(request, f'Ambito "{ambito.nome}" creato.')
    return _helpers._back_to_caller(request, "anagrafica:ruoli_operativi_list")


@login_required
@require_POST
def ambito_ruolo_edit(request, ambito_id: int):
    if not _helpers._is_anagrafica_admin(request):
        messages.error(request, "Non hai i permessi per gestire gli ambiti dei ruoli.")
        return _helpers._back_to_caller(request, "anagrafica:ruoli_operativi_list")

    ambito = get_object_or_404(AmbitoRuolo, pk=ambito_id)
    nome = (request.POST.get("nome") or "").strip()[:100]
    if not nome:
        messages.error(request, "Il nome dell'ambito è obbligatorio.")
        return _helpers._back_to_caller(request, "anagrafica:ruoli_operativi_list")

    ambito.nome = nome
    ambito.descrizione = (request.POST.get("descrizione") or "").strip()
    ambito.colore = (request.POST.get("colore") or "#64748b").strip()[:7]
    ambito.icona = (request.POST.get("icona") or "").strip()[:10]
    ambito.ordine = _parse_int(request.POST.get("ordine"), ambito.ordine)
    ambito.is_active = request.POST.get("is_active") == "1"
    chiesto_scheda = request.POST.get("alimenta_scheda") == "1"
    # Togliere la spunta all'unico ambito che alimenta la scheda lascerebbe il
    # «Ruolo aziendale» senza sorgente: si cambia scegliendone un altro.
    if not chiesto_scheda and ambito.alimenta_scheda:
        messages.warning(
            request,
            "L'ambito che alimenta il «Ruolo aziendale» resta questo: per cambiarlo, "
            "spunta la casella su un altro ambito.",
        )
    else:
        ambito.alimenta_scheda = chiesto_scheda
    ambito.save()
    messages.success(request, f'Ambito "{ambito.nome}" aggiornato.')
    return _helpers._back_to_caller(request, "anagrafica:ruoli_operativi_list")


@login_required
@require_POST
def ambito_ruolo_delete(request, ambito_id: int):
    if not _helpers._is_anagrafica_admin(request):
        messages.error(request, "Non hai i permessi per gestire gli ambiti dei ruoli.")
        return _helpers._back_to_caller(request, "anagrafica:ruoli_operativi_list")

    ambito = get_object_or_404(AmbitoRuolo, pk=ambito_id)
    n_ruoli = ambito.ruoli.count()
    if n_ruoli:
        messages.error(
            request,
            f'"{ambito.nome}" non si elimina: {n_ruoli} ruol{"o" if n_ruoli == 1 else "i"} '
            "lo usano. Spostali in un altro ambito prima.",
        )
        return _helpers._back_to_caller(request, "anagrafica:ruoli_operativi_list")
    if ambito.alimenta_scheda:
        messages.error(
            request,
            f'"{ambito.nome}" alimenta il «Ruolo aziendale» della scheda: '
            "assegna quel compito a un altro ambito prima di eliminarlo.",
        )
        return _helpers._back_to_caller(request, "anagrafica:ruoli_operativi_list")

    nome = ambito.nome
    ambito.delete()
    messages.success(request, f'Ambito "{nome}" eliminato.')
    return _helpers._back_to_caller(request, "anagrafica:ruoli_operativi_list")


@login_required
def ruolo_operativo_dipendenti(request, ruolo_id: int):
    """Partial: chi ricopre un ruolo del catalogo unico.

    Due fonti, entrambe legittime finché il ruolo aziendale resta un campo
    testuale: l'assegnazione esplicita (``DipendenteRuoloOperativo``) e il
    «Ruolo aziendale» scritto nella scheda. Chi compare in entrambe è mostrato
    una volta sola, con tutte e due le provenienze.
    """
    ruolo = get_object_or_404(
        RuoloOperativo.objects.select_related("ambito"), pk=ruolo_id
    )

    periodi = {
        a.legacy_anagrafica_id: (a.data_inizio, a.data_fine, a.get_tipologia_display() if a.tipologia else "")
        for a in DipendenteRuoloOperativo.objects.filter(ruolo=ruolo)
    }
    ids_assegnati = set(periodi)
    ids_scheda = set(
        DipendenteAnagraficaAziendale.objects
        .filter(ruolo_aziendale__iexact=ruolo.nome)
        .values_list("legacy_anagrafica_id", flat=True)
    )
    tutti = {int(v) for v in (ids_assegnati | ids_scheda) if int(v or 0) > 0}

    righe: list[dict] = []
    if tutti:
        cessati = _helpers._cessati_legacy_ids()
        for row in fetch_anagrafica_rows(ids=sorted(tutti), deduplicate=True):
            legacy_id = int(row.get("id") or 0)
            if legacy_id <= 0:
                continue
            nome = str(row.get("nome") or "").strip()
            cognome = str(row.get("cognome") or "").strip()
            fonti = []
            if legacy_id in ids_assegnati:
                fonti.append("Assegnato")
            if legacy_id in ids_scheda:
                fonti.append("Da scheda")
            righe.append({
                "legacy_id": legacy_id,
                "label": naming.nome_completo(nome, cognome) or f"#{legacy_id}",
                "reparto": str(row.get("reparto") or "").strip(),
                "mansione": str(row.get("mansione") or "").strip(),
                "fonti": fonti,
                "cessato": legacy_id in cessati,
                "dal": periodi.get(legacy_id, (None, None, ""))[0],
                "al": periodi.get(legacy_id, (None, None, ""))[1],
                "tipologia": periodi.get(legacy_id, (None, None, ""))[2],
            })
        righe.sort(key=lambda r: r["label"].casefold())

    return render(request, "anagrafica/partials/_ruolo_dipendenti.html", {
        "ruolo": ruolo,
        "righe": righe,
    })


@login_required
def mansioni_list(request):
    legacy_user = get_legacy_user(request.user)
    is_admin = _helpers._is_anagrafica_admin(request)
    can_view_requisiti = _helpers._can_view_formazione(request)

    filtro_rischio = (request.GET.get("rischio") or "").strip().upper()
    if filtro_rischio not in dict(Mansione.LIVELLO_RISCHIO_CHOICES):
        filtro_rischio = ""
    solo_rischio = request.GET.get("solo_rischio") == "1"
    q_text = (request.GET.get("q") or "").strip()

    mansioni = list(
        Mansione.objects.all()
        .order_by("nome")
        .prefetch_related("visite_richieste", "dpi_richiesti")
    )

    # Conta dipendenti per mansione dal DB legacy
    mansione_counts: dict[str, int] = {}
    try:
        from django.db import connections
        conn_name = "legacy" if "legacy" in connections else "default"
        with connections[conn_name].cursor() as cur:
            cur.execute(
                "SELECT LOWER(mansione), COUNT(*) FROM anagrafica_dipendenti "
                "WHERE mansione IS NOT NULL AND mansione != '' GROUP BY LOWER(mansione)"
            )
            for row in cur.fetchall():
                mansione_counts[row[0]] = row[1]
    except Exception:
        pass

    # Schede di sicurezza dovute per mansione: bridge fail-open verso il modulo
    # Schede di sicurezza (una query per l'intero catalogo, non una per riga).
    sds_counts: dict[int, int] = {}
    try:
        from schede_sicurezza.services.assegnazioni import conteggio_sds_per_mansione
        sds_counts = conteggio_sds_per_mansione([m.pk for m in mansioni])
    except Exception:
        logger.warning("Conteggio SDS per mansione non disponibile", exc_info=True)

    for m in mansioni:
        m.n_dipendenti = mansione_counts.get(m.nome.lower(), 0)
        # Contatori requisiti (usano la cache di prefetch_related → nessuna query extra)
        m.n_visite = len(m.visite_richieste.all())
        try:
            m.n_dpi = len(m.dpi_richiesti.all())
        except Exception:
            m.n_dpi = 0
        m.n_sds = sds_counts.get(m.pk, 0)
        m.livello_label = m.get_livello_rischio_display() if m.livello_rischio else ""
        # L'esposizione a prodotti chimici è essa stessa un rischio della
        # mansione: una mansione con SDS dovute conta tra quelle "di rischio".
        m.is_rischio = bool(m.livello_rischio or m.n_dpi or m.n_visite or m.n_sds)

    n_rischio_tot = sum(1 for m in mansioni if m.is_rischio)

    # Filtri (livello rischio, solo mansioni di rischio, ricerca nome)
    def _match(m) -> bool:
        if q_text and q_text.casefold() not in m.nome.casefold():
            return False
        if filtro_rischio and m.livello_rischio != filtro_rischio:
            return False
        if solo_rischio and not m.is_rischio:
            return False
        return True

    if filtro_rischio or solo_rischio or q_text:
        mansioni = [m for m in mansioni if _match(m)]

    # Raggruppa per categoria nell'ordine definito
    cat_order = [c for c, _ in Mansione.CATEGORIA_CHOICES]
    cat_labels = dict(Mansione.CATEGORIA_CHOICES)
    # Le mansioni senza categoria vanno in "Altro"
    grouped: list[tuple[str, str, list]] = []
    seen_cats: set[str] = set()
    for cat_code in cat_order:
        items = [m for m in mansioni if (m.categoria or Mansione.CAT_ALTRO) == cat_code]
        if items:
            grouped.append((cat_code, cat_labels[cat_code], items))
            seen_cats.add(cat_code)
    # Mansioni senza categoria classificate come "Altro"
    senza_cat = [m for m in mansioni if not m.categoria and Mansione.CAT_ALTRO not in seen_cats]
    if senza_cat:
        altro_label = cat_labels.get(Mansione.CAT_ALTRO, "Altro")
        grouped.append((Mansione.CAT_ALTRO, altro_label, senza_cat))

    from ..models_mansioni_rischio import ConfigSicurezzaOperativa

    return render(request, "anagrafica/pages/mansioni_list.html", {
        "mansioni": mansioni,
        "mansioni_grouped": grouped,
        "is_admin": is_admin,
        "can_view_requisiti": can_view_requisiti,
        "config_sicurezza": ConfigSicurezzaOperativa.load(),
        "CATEGORIA_CHOICES": Mansione.CATEGORIA_CHOICES,
        "LIVELLO_RISCHIO_CHOICES": Mansione.LIVELLO_RISCHIO_CHOICES,
        "filtro_rischio": filtro_rischio,
        "solo_rischio": solo_rischio,
        "q_text": q_text,
        "n_rischio_tot": n_rischio_tot,
        "n_visibili": len(mansioni),
    })


@login_required
@require_POST
def mansione_create(request):
    legacy_user = get_legacy_user(request.user)
    if not _helpers._is_anagrafica_admin(request):
        messages.error(request, "Non hai i permessi per creare mansioni.")
        return _helpers._back_to_caller(request, "anagrafica:mansioni_list")

    nome = (request.POST.get("nome") or "").strip()[:100]
    if not nome:
        messages.error(request, "Il nome della mansione è obbligatorio.")
        return _helpers._back_to_caller(request, "anagrafica:mansioni_list")

    _lr = (request.POST.get("livello_rischio") or "").strip().upper()
    _lr = _lr if _lr in dict(Mansione.LIVELLO_RISCHIO_CHOICES) else ""
    _, created = Mansione.objects.get_or_create(
        nome__iexact=nome,
        defaults={
            "nome": nome,
            "categoria": (request.POST.get("categoria") or "").strip()[:20],
            "descrizione": (request.POST.get("descrizione") or "").strip(),
            "colore": (request.POST.get("colore") or "#64748b").strip()[:7],
            "livello_rischio": _lr,
        },
    )
    if created:
        messages.success(request, f'Mansione "{nome}" creata.')
    else:
        messages.warning(request, f'Esiste già una mansione con il nome "{nome}".')
    return _helpers._back_to_caller(request, "anagrafica:mansioni_list")


@login_required
@require_POST
def mansione_edit(request, mansione_id: int):
    legacy_user = get_legacy_user(request.user)
    if not _helpers._is_anagrafica_admin(request):
        messages.error(request, "Non hai i permessi per modificare mansioni.")
        return _helpers._back_to_caller(request, "anagrafica:mansioni_list")

    mansione = get_object_or_404(Mansione, pk=mansione_id)
    nome = (request.POST.get("nome") or "").strip()[:100]
    if not nome:
        messages.error(request, "Il nome della mansione è obbligatorio.")
        return _helpers._back_to_caller(request, "anagrafica:mansioni_list")

    _lr = (request.POST.get("livello_rischio") or "").strip().upper()
    from ..services.mansionario import rinomina as rinomina_mansione

    try:
        # Il vecchio nome resta fra i precedenti: le persone, legate per nome, non si perdono.
        rinomina_mansione(mansione, nome)
    except ValueError as exc:
        messages.error(request, str(exc))
        return _helpers._back_to_caller(request, "anagrafica:mansioni_list")
    mansione.categoria = (request.POST.get("categoria") or "").strip()[:20]
    mansione.descrizione = (request.POST.get("descrizione") or "").strip()
    mansione.colore = (request.POST.get("colore") or "#64748b").strip()[:7]
    mansione.livello_rischio = _lr if _lr in dict(Mansione.LIVELLO_RISCHIO_CHOICES) else ""
    mansione.is_active = request.POST.get("is_active") == "1"
    mansione.save()
    messages.success(request, f'Mansione "{mansione.nome}" aggiornata.')
    return _helpers._back_to_caller(request, "anagrafica:mansioni_list")


@login_required
@require_POST
def mansione_delete(request, mansione_id: int):
    legacy_user = get_legacy_user(request.user)
    if not _helpers._is_anagrafica_admin(request):
        messages.error(request, "Non hai i permessi per eliminare mansioni.")
        return _helpers._back_to_caller(request, "anagrafica:mansioni_list")

    mansione = get_object_or_404(Mansione, pk=mansione_id)
    nome = mansione.nome
    mansione.delete()
    messages.success(request, f'Mansione "{nome}" eliminata.')
    return _helpers._back_to_caller(request, "anagrafica:mansioni_list")


@login_required
def mansione_requisiti(request, mansione_id: int):
    """Profilo "mansione di rischio": DPI / visite / formazione richiesti.

    GET mostra i requisiti **diretti** (modificabili) della mansione, quelli
    **ereditati** dai fattori di rischio esposti (read-only) e il riepilogo dei
    requisiti effettivi (unione). POST salva i M2M diretti ``dpi_richiesti`` e
    ``visite_richieste``. Gate: visualizzazione/edit formazione (dominio Safety).
    """
    if not _helpers._can_view_formazione(request):
        messages.error(request, "Non hai i permessi per i requisiti mansione.")
        return redirect("anagrafica:index")
    is_editor = _helpers._can_edit_formazione(request)
    mansione = get_object_or_404(Mansione, pk=mansione_id)

    if request.method == "POST":
        if not is_editor:
            messages.error(request, "Permessi insufficienti per modificare i requisiti.")
            return redirect("anagrafica:mansione_requisiti", mansione_id=mansione.pk)
        _lr = (request.POST.get("livello_rischio") or "").strip().upper()
        mansione.livello_rischio = _lr if _lr in dict(Mansione.LIVELLO_RISCHIO_CHOICES) else ""
        mansione.dvr_revisione = (request.POST.get("dvr_revisione") or "").strip()[:30]
        try:
            _dvr = (request.POST.get("dvr_data") or "").strip()
            mansione.dvr_data = date.fromisoformat(_dvr) if _dvr else None
        except ValueError:
            messages.warning(request, "Data revisione DVR non valida: non salvata.")
        mansione.save(update_fields=["livello_rischio", "dvr_revisione", "dvr_data"])
        # Protocollo sanitario: si modifica solo con il permesso visite (decisione
        # 10/10/2026, prima applicata al vecchio catalogo MansioneRischio). Senza
        # il permesso il form non lo invia e il server lo conserva.
        if _helpers._can_view_visite_mediche(request):
            visite_ids = [int(v) for v in request.POST.getlist("visite_richieste") if str(v).isdigit()]
            mansione.visite_richieste.set(
                TipoVisitaMedica.objects.filter(pk__in=visite_ids, is_active=True)
            )
        try:
            from dpi.models import CategoriaDPI
            dpi_ids = [int(v) for v in request.POST.getlist("dpi_richiesti") if str(v).isdigit()]
            mansione.dpi_richiesti.set(CategoriaDPI.objects.filter(pk__in=dpi_ids, is_active=True))
        except Exception:
            logger.warning("Salvataggio DPI mansione fallito (modulo dpi?)", exc_info=True)
        messages.success(request, f'Requisiti della mansione "{mansione.nome}" aggiornati.')
        return redirect("anagrafica:mansione_requisiti", mansione_id=mansione.pk)

    # Requisiti effettivi (unione diretti + ereditati) per il riepilogo.
    requisiti = mansionario_service.requisiti_mansione(mansione)

    # Cataloghi per i selettori dei requisiti diretti.
    # Ordinate per categoria (le senza-categoria in fondo) cosi' il template
    # puo' raggrupparle con {% regroup %}, che richiede la lista gia' ordinata
    # sulla chiave di raggruppamento.
    from django.db.models import Case, When
    visite_opts = list(
        TipoVisitaMedica.objects.filter(is_active=True)
        .order_by(Case(When(categoria="", then=1), default=0), "categoria", "nome")
    )
    sel_visite_ids = set(mansione.visite_richieste.values_list("pk", flat=True))
    dpi_opts: list = []
    sel_dpi_ids: set[int] = set()
    try:
        from dpi.models import CategoriaDPI
        dpi_opts = list(CategoriaDPI.objects.filter(is_active=True).order_by("order_index", "nome"))
        sel_dpi_ids = set(mansione.dpi_richiesti.values_list("pk", flat=True))
    except Exception:
        dpi_opts = []

    # Prodotti chimici della mansione con la SDS corrente: la presa visione è un
    # obbligo informativo della mansione al pari di DPI e visite, e va letta
    # qui accanto a loro. Bridge fail-open: senza il modulo la sezione sparisce.
    sds_righe: list = []
    try:
        from schede_sicurezza.services.assegnazioni import prodotti_sds_per_mansione
        sds_righe = prodotti_sds_per_mansione(mansione.pk)
    except Exception:
        logger.warning("Elenco SDS della mansione non disponibile", exc_info=True)

    return render(request, "anagrafica/pages/mansione_requisiti.html", {
        "mansione": mansione,
        "is_editor": is_editor,
        "puo_protocollo": _helpers._can_view_visite_mediche(request),
        "requisiti": requisiti,
        "sds_righe": sds_righe,
        "n_sds_senza_scheda": sum(1 for riga in sds_righe if riga["stato"] == "bad"),
        "visite_opts": visite_opts,
        "sel_visite_ids": sel_visite_ids,
        "dpi_opts": dpi_opts,
        "sel_dpi_ids": sel_dpi_ids,
        "livello_choices": Mansione.LIVELLO_RISCHIO_CHOICES,
    })


def _resolve_caporeparto_id(raw: str | None) -> int | None:
    """Normalizza il valore POST del caporeparto in un legacy_id valido o None."""
    if not raw:
        return None
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _mansione_capo_da_post(raw: str | None):
    """Mansione del capo scelta nel form (vuota = default del reparto / segue il reparto)."""
    from anagrafica.models_skillmatrix import CompetenzaSkm

    mid = _resolve_caporeparto_id(raw)
    return CompetenzaSkm.objects.filter(pk=mid).first() if mid else None


# ── Area Aziendale CRUD (ora il livello FIGLIO) ─────────────────────────────
# Il responsabile non si sceglie più qui: è chi ha la mansione dell'area
# (services.capi_mansione), assegnata dalla pagina «Reparti, aree e capi».

@login_required
@require_POST
def area_aziendale_create(request):
    legacy_user = get_legacy_user(request.user)
    if not _helpers._is_anagrafica_admin(request):
        messages.error(request, "Non hai i permessi per creare aree aziendali.")
        return _helpers._back_to_caller(request, "anagrafica:aree_list")
    nome = (request.POST.get("nome") or "").strip()[:100]
    if not nome:
        messages.error(request, "Il nome dell'area aziendale è obbligatorio.")
        return _helpers._back_to_caller(request, "anagrafica:aree_list")
    reparto_id = request.POST.get("reparto_id") or None
    reparto = None
    if reparto_id:
        try:
            reparto = Reparto.objects.get(pk=int(reparto_id))
        except (Reparto.DoesNotExist, ValueError):
            pass
    obj, created = AreaAziendale.objects.get_or_create(
        nome__iexact=nome,
        defaults={
            "nome": nome,
            "descrizione": (request.POST.get("descrizione") or "").strip(),
            "reparto": reparto,
            "mansione_capo": _mansione_capo_da_post(request.POST.get("mansione_capo")),
        },
    )
    if created:
        messages.success(request, f'Area aziendale "{nome}" creata.')
    else:
        messages.warning(request, f'Esiste già un\'area aziendale con il nome "{nome}".')
    return _helpers._back_to_caller(request, "anagrafica:aree_list")


@login_required
@require_POST
def area_aziendale_edit(request, area_id: int):
    legacy_user = get_legacy_user(request.user)
    if not _helpers._is_anagrafica_admin(request):
        messages.error(request, "Non hai i permessi per modificare aree aziendali.")
        return _helpers._back_to_caller(request, "anagrafica:aree_list")
    area = get_object_or_404(AreaAziendale, pk=area_id)
    nome = (request.POST.get("nome") or "").strip()[:100]
    if not nome:
        messages.error(request, "Il nome dell'area aziendale è obbligatorio.")
        return _helpers._back_to_caller(request, "anagrafica:aree_list")
    reparto_id = request.POST.get("reparto_id") or None
    reparto = None
    if reparto_id:
        try:
            reparto = Reparto.objects.get(pk=int(reparto_id))
        except (Reparto.DoesNotExist, ValueError):
            pass
    area.nome = nome
    area.descrizione = (request.POST.get("descrizione") or "").strip()
    area.reparto = reparto
    area.mansione_capo = _mansione_capo_da_post(request.POST.get("mansione_capo"))
    area.is_active = request.POST.get("is_active") == "1"
    area.save()  # segnali_capi: con la regola accesa riallinea capi e schede
    messages.success(request, f'Area aziendale "{area.nome}" aggiornata.')
    return _helpers._back_to_caller(request, "anagrafica:aree_list")


@login_required
@require_POST
def area_aziendale_delete(request, area_id: int):
    legacy_user = get_legacy_user(request.user)
    if not _helpers._is_anagrafica_admin(request):
        messages.error(request, "Non hai i permessi per eliminare aree aziendali.")
        return _helpers._back_to_caller(request, "anagrafica:aree_list")
    area = get_object_or_404(AreaAziendale, pk=area_id)
    nome = area.nome
    area.delete()
    messages.success(request, f'Area aziendale "{nome}" eliminata.')
    return _helpers._back_to_caller(request, "anagrafica:aree_list")


# ── Reparto CRUD (ora il livello PADRE) ─────────────────────────────────────

def _sync_reparto_capo_mapping(rep) -> None:
    """Allinea RepartoCapoMapping al valore di Reparto.caporeparto_legacy_id.

    Chiamata dopo ogni create/edit di un Reparto per mantenere la tabella
    RepartoCapoMapping (usata da assenze e automazioni) in sincronia con la
    fonte di verità in Anagrafica HR.
    """
    from anagrafica.services.capi_mansione import valore_mapping
    from core.models import RepartoCapoMapping

    reparto_nome = (rep.nome or "").strip()
    if not reparto_nome:
        return

    RepartoCapoMapping.objects.filter(reparto__iexact=reparto_nome).delete()

    if not rep.caporeparto_legacy_id:
        return

    capo_str = valore_mapping(rep.caporeparto_legacy_id)
    if not capo_str:
        return

    RepartoCapoMapping.objects.create(
        reparto=reparto_nome,
        caporeparto=capo_str,
        is_active=True,
    )


@login_required
@require_POST
def area_create(request):
    legacy_user = get_legacy_user(request.user)
    if not _helpers._is_anagrafica_admin(request):
        messages.error(request, "Non hai i permessi per creare reparti.")
        return _helpers._back_to_caller(request, "anagrafica:aree_list")
    nome = (request.POST.get("nome") or "").strip()[:100]
    if not nome:
        messages.error(request, "Il nome del reparto è obbligatorio.")
        return _helpers._back_to_caller(request, "anagrafica:aree_list")
    obj, created = Reparto.objects.get_or_create(
        nome__iexact=nome,
        defaults={
            "nome": nome,
            "descrizione": (request.POST.get("descrizione") or "").strip(),
            "colore": (request.POST.get("colore") or "#64748b").strip()[:7],
            "mansione_capo": _mansione_capo_da_post(request.POST.get("mansione_capo")),
        },
    )
    if created:
        messages.success(request, f'Reparto "{nome}" creato.')
    else:
        messages.warning(request, f'Esiste già un reparto con il nome "{nome}".')
    return _helpers._back_to_caller(request, "anagrafica:aree_list")


@login_required
@require_POST
def area_edit(request, area_id: int):
    legacy_user = get_legacy_user(request.user)
    if not _helpers._is_anagrafica_admin(request):
        messages.error(request, "Non hai i permessi per modificare reparti.")
        return _helpers._back_to_caller(request, "anagrafica:aree_list")
    rep = get_object_or_404(Reparto, pk=area_id)
    nome = (request.POST.get("nome") or "").strip()[:100]
    if not nome:
        messages.error(request, "Il nome del reparto è obbligatorio.")
        return _helpers._back_to_caller(request, "anagrafica:aree_list")
    rep.nome = nome
    rep.descrizione = (request.POST.get("descrizione") or "").strip()
    rep.colore = (request.POST.get("colore") or "#64748b").strip()[:7]
    rep.is_active = request.POST.get("is_active") == "1"
    nome_prima = Reparto.objects.filter(pk=rep.pk).values_list("nome", flat=True).first()
    rep.mansione_capo = _mansione_capo_da_post(request.POST.get("mansione_capo"))
    rep.save()  # segnali_capi: con la regola accesa riallinea capi, schede e mapping
    if nome_prima and nome_prima != rep.nome:
        from core.models import RepartoCapoMapping

        RepartoCapoMapping.objects.filter(reparto__iexact=nome_prima).update(reparto=rep.nome)
    messages.success(request, f'Reparto "{rep.nome}" aggiornato.')
    return _helpers._back_to_caller(request, "anagrafica:aree_list")


@login_required
@require_POST
def area_delete(request, area_id: int):
    legacy_user = get_legacy_user(request.user)
    if not _helpers._is_anagrafica_admin(request):
        messages.error(request, "Non hai i permessi per eliminare reparti.")
        return _helpers._back_to_caller(request, "anagrafica:aree_list")
    rep = get_object_or_404(Reparto, pk=area_id)
    if rep.aree_aziendali.exists():
        messages.error(request, f'Impossibile eliminare: il reparto "{rep.nome}" ha aree aziendali associate. Riassegna prima le aree.')
        return _helpers._back_to_caller(request, "anagrafica:aree_list")
    nome = rep.nome
    rep.delete()
    messages.success(request, f'Reparto "{nome}" eliminato.')
    return _helpers._back_to_caller(request, "anagrafica:aree_list")


# ---------------------------------------------------------------------------
# Ruoli aziendali — catalogo dropdown
# ---------------------------------------------------------------------------

@login_required
def ruoli_aziendali_list(request):
    # Fase 2: «Ruoli aziendali» e «Ruoli operativi» sono un catalogo unico.
    # La pagina dedicata è confluita in quella unificata dei Ruoli.
    messages.info(
        request,
        "I ruoli aziendali e operativi sono ora un catalogo unico: gestiscili da qui.",
    )
    return redirect("anagrafica:ruoli_operativi_list")


@login_required
@require_POST
def ruolo_aziendale_create(request):
    # Catalogo unico: la tabella legacy `RuoloAziendale` non viene più scritta,
    # altrimenti tornerebbe a divergere dai Ruoli. Le rotte restano solo per non
    # rompere link/bookmark e rimandano al catalogo unificato.
    return _ruolo_aziendale_legacy_redirect(request)


@login_required
@require_POST
def ruolo_aziendale_edit(request, ruolo_id: int):
    return _ruolo_aziendale_legacy_redirect(request)


@login_required
@require_POST
def ruolo_aziendale_delete(request, ruolo_id: int):
    return _ruolo_aziendale_legacy_redirect(request)


def _ruolo_aziendale_legacy_redirect(request):
    messages.info(
        request,
        "I ruoli aziendali e operativi sono un catalogo unico: gestiscili da qui.",
    )
    return redirect("anagrafica:ruoli_operativi_list")


# ---------------------------------------------------------------------------
# Organigramma visuale — Reparto → Aree aziendali → caporeparto → dipendenti
# ---------------------------------------------------------------------------

@login_required
def organigramma(request):
    """Organigramma navigabile SSR: reparti, aree aziendali, capi e membri.

    Il reparto di ogni dipendente è risolto dalla **fonte unica canonica**
    (`dipendente → area_aziendale → reparto`, via
    :func:`anagrafica.services.reparto_canonico.build_reparto_canonico_map`),
    con fallback al testo legacy finché la copertura canonica non è completa.
    I dipendenti che non si risolvono per nessuna via finiscono nel bucket
    "Non mappati", che resta come spia dei residui da bonificare.
    """
    from anagrafica.services.reparto_canonico import (
        build_area_canonica_map,
        build_reparto_canonico_map,
        resolve_reparto_for_row,
        resolve_responsabile_effettivo,
    )

    ensure_anagrafica_schema()
    filtro_reparto = (request.GET.get("reparto") or "").strip()

    dip_rows = [r for r in fetch_anagrafica_rows(deduplicate=True) if r.get("attivo")]
    dip_map = {int(r["id"]): r for r in dip_rows if r.get("id")}

    reparti = list(
        Reparto.objects.filter(is_active=True)
        .prefetch_related("aree_aziendali")
        .order_by("nome")
    )
    reparto_by_name = {r.nome.strip().casefold(): r for r in reparti}

    legacy_ids = list(dip_map.keys())
    canonico_map = build_reparto_canonico_map(legacy_ids)
    area_map = build_area_canonica_map(legacy_ids)

    membri_per_reparto: dict[int, list[dict]] = {}
    non_mappati: list[dict] = []
    for row in dip_rows:
        rep = resolve_reparto_for_row(row, canonico_map=canonico_map, reparto_by_name=reparto_by_name)
        # Area aziendale canonica del membro (per la vista); None se non assegnata.
        area = area_map.get(int(row.get("id") or 0))
        row["area_aziendale_nome"] = area.nome if area is not None else ""
        if rep is None:
            non_mappati.append(row)
        else:
            membri_per_reparto.setdefault(rep.id, []).append(row)

    def _sort_key(row: dict):
        return (str(row.get("cognome") or "").casefold(), str(row.get("nome") or "").casefold())

    def _blocco_reparto(rep: Reparto) -> dict:
        capo = dip_map.get(rep.caporeparto_legacy_id or 0)
        membri = sorted(membri_per_reparto.get(rep.id, []), key=_sort_key)
        if capo:
            membri = [m for m in membri if int(m.get("id") or 0) != int(capo.get("id") or 0)]
        aree = list(rep.aree_aziendali.filter(is_active=True).order_by("nome"))
        # Responsabile effettivo per AREA: il responsabile dell'area vince sul
        # caporeparto del reparto quando differisce (dominio: "caporeparto
        # dall'area aziendale se differisce"). Il capo del blocco resta il
        # caporeparto del reparto come fallback complessivo.
        for area in aree:
            rid = resolve_responsabile_effettivo(area=area, reparto=rep)
            area.responsabile_effettivo_id = rid
            resp_row = dip_map.get(rid or 0)
            area.responsabile_effettivo_label = (
                naming.nome_completo(resp_row.get("nome"), resp_row.get("cognome"))
                if resp_row else ""
            )
            area.responsabile_distinto = bool(
                area.responsabile_legacy_id
                and area.responsabile_legacy_id != (rep.caporeparto_legacy_id or 0)
            )
        return {
            "reparto": rep,
            "capo": capo,
            "membri": membri,
            "aree_aziendali": aree,
            "n_totale": len(membri) + (1 if capo else 0),
        }

    blocchi = [_blocco_reparto(r) for r in reparti]

    nomi_reparti = [r.nome for r in reparti]
    if filtro_reparto:
        blocchi = [b for b in blocchi if b["reparto"].nome.casefold() == filtro_reparto.casefold()]

    non_mappati.sort(key=_sort_key)
    n_dipendenti = len(dip_rows)

    return render(request, "anagrafica/pages/organigramma.html", {
        "is_anagrafica_admin": _helpers._is_anagrafica_admin(request),
        "blocchi": blocchi,
        "non_mappati": non_mappati,
        "nomi_reparti": nomi_reparti,
        "filtro_reparto": filtro_reparto,
        "n_dipendenti": n_dipendenti,
        "n_reparti": len(reparti),
        "n_non_mappati": len(non_mappati),
    })


@login_required
def organigramma_albero(request):
    """Organigramma ad albero: gerarchia dei RUOLI (RuoloOperativo.riporta_a),
    persone come foglie titolari. Con ?certificazione=<TipoQualifica.pk> mostra
    la copertura ad albero della certificazione (chi la possiede). La gerarchia
    è SEMPRE tra ruoli, mai tra persone."""
    from anagrafica.services.organigramma_albero import (
        build_ruolo_albero, build_certificazione_copertura,
    )
    raw = (request.GET.get("certificazione") or "").strip()
    cert_id = int(raw) if raw.isdigit() else None
    ambito_id = _parse_ambito_filtro(request)
    albero = (
        build_certificazione_copertura(cert_id, ambito_id=ambito_id)
        if cert_id
        else build_ruolo_albero(ambito_id)
    )
    return render(request, "anagrafica/pages/organigramma_albero.html", {
        "albero": albero,
        "cert_id": cert_id,
        "certificazioni": TipoQualifica.objects.filter(is_active=True).order_by("nome"),
        **_ambito_filtro_context(ambito_id),
    })


@login_required
def organigramma_diagramma(request):
    """Organigramma a diagramma: un riquadro per POSIZIONE (ruolo + persona).

    Stessa gerarchia della vista ad albero (sempre tra ruoli, mai tra persone),
    disegnata ad albero genealogico: il riquadro genitore sta al centro e i
    riporti si affiancano sotto, agganciati alla traversa. I ruoli con più
    titolari diventano riquadri fratelli; vedi
    :func:`anagrafica.services.organigramma_albero.build_posizioni_albero`.
    """
    from anagrafica.services.organigramma_albero import build_posizioni_albero

    ambito_id = _parse_ambito_filtro(request)
    albero = build_posizioni_albero(ambito_id)

    def _conta(nodi):
        tot = 0
        for n in nodi:
            tot += 1 + _conta(n["figli"])
        return tot

    return render(request, "anagrafica/pages/organigramma_diagramma.html", {
        "albero": albero,
        "n_posizioni": _conta(albero),
        **_ambito_filtro_context(ambito_id),
    })
