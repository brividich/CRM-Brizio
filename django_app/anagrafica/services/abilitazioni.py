"""Abilitazioni delle persone (carrellista, PLE, BLS-D, primo soccorso, antincendio…): un solo calcolo.

L'abilitazione è la voce del catalogo ``TipoQualifica``; chi la possiede lo dicono le
``DipendenteQualifica`` (vale la corrente: la conseguita per ultima). Qui si risponde a tre domande,
sempre con le stesse regole, per scheda persona, «Il mio team», elenco per reparto, scheda del
mezzo e «Presenti in azienda»:

- **a chi serve** (:func:`richieste`): ruolo che la richiede, mansione di rischio, mansione della
  skill matrix, processo qualificato MOD.128;
- **com'è messa una persona** (:func:`quadro`): valida, in scadenza, scaduta, mancante;
- **chi può usare un mezzo** (:func:`abilitati_asset`): persone con l'abilitazione chiesta dalla
  categoria del mezzo.

Solo persone in forza (``in_forza.cessati_ids``). Soglia «in scadenza»: ``scadenze_soglie``.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.utils import timezone

from ..scadenze_soglie import GIORNI_PREAVVISO

VALIDA, IN_SCADENZA, SCADUTA, MANCANTE = "valida", "in_scadenza", "scaduta", "mancante"
ETICHETTE = {VALIDA: "Valida", IN_SCADENZA: "In scadenza", SCADUTA: "Scaduta", MANCANTE: "Mancante"}
TONI = {VALIDA: "ok", IN_SCADENZA: "warning", SCADUTA: "danger", MANCANTE: "neutral"}
_ORDINE = {MANCANTE: 0, SCADUTA: 1, IN_SCADENZA: 2, VALIDA: 3}
COLORE_BOLLINO = "#0f766e"


def stato_di(scadenza: date | None, oggi: date) -> str:
    if scadenza is None:
        return VALIDA
    if scadenza < oggi:
        return SCADUTA
    if scadenza <= oggi + timedelta(days=GIORNI_PREAVVISO):
        return IN_SCADENZA
    return VALIDA


def in_forza_ids() -> set[int]:
    from ..models import DipendenteAnagraficaAziendale
    from .in_forza import cessati_ids

    tutti = set(DipendenteAnagraficaAziendale.objects.values_list("legacy_anagrafica_id", flat=True))
    return {int(i) for i in tutti if i} - set(cessati_ids())


def _aggiungi(motivi: dict, lid, tipo_id: int, testo: str) -> None:
    if not lid:
        return
    voci = motivi.setdefault(int(lid), {}).setdefault(tipo_id, [])
    if testo not in voci:
        voci.append(testo)


def persone_per_mansione_rischio(legacy_ids) -> dict[str, set[int]]:
    """{nome della mansione di rischio (minuscolo): persone che ce l'hanno}; regola del Mansionario."""
    from .mansionario import nomi_mansioni_rischio

    out: dict[str, set[int]] = {}
    for lid, nomi in nomi_mansioni_rischio(list(legacy_ids)).items():
        for nome in nomi:
            out.setdefault(nome.strip().casefold(), set()).add(int(lid))
    return out


def richieste(tipi=None, *, oggi: date | None = None) -> dict[int, dict[int, list[str]]]:
    """{persona: {abilitazione: [perché le serve]}} per le persone in forza."""
    from ..models import TipoQualifica
    from . import qualifica_mancanti as qm

    oggi = oggi or timezone.localdate()
    if tipi is None:
        tipi = list(TipoQualifica.objects.filter(is_active=True))
    forza = in_forza_ids()
    motivi: dict[int, dict[int, list[str]]] = {}

    con_mansioni = {}
    for t in tipi:
        nomi = [(m.nome, {m.nome.strip().casefold(), *(n.strip().casefold() for n in (m.nomi_precedenti or "").splitlines() if n.strip())})
                for m in t.mansioni_rischio.all() if m.is_active]
        if nomi:
            con_mansioni[t.pk] = nomi
    if con_mansioni:
        per_mansione = persone_per_mansione_rischio(forza)
        for tipo_id, mansioni in con_mansioni.items():
            for nome, chiavi in mansioni:
                for chiave in chiavi:
                    for lid in per_mansione.get(chiave, ()):
                        _aggiungi(motivi, lid, tipo_id, f"Mansione di rischio «{nome}»")

    for t in tipi:
        parziale: dict[int, list[str]] = {}
        for fonte in (qm._da_processi, qm._da_mansioni):
            try:
                fonte(t, parziale)
            except Exception:  # pragma: no cover - modulo non migrato: la fonte resta fuori
                continue
        try:
            qm._da_ruoli(t, parziale, oggi)
        except Exception:  # pragma: no cover
            pass
        for lid, voci in parziale.items():
            for testo in voci:
                _aggiungi(motivi, lid, t.pk, testo)
    return {lid: v for lid, v in motivi.items() if lid in forza}


def correnti(tipo_ids=None, legacy_ids=None) -> dict[tuple[int, int], object]:
    """{(persona, abilitazione): DipendenteQualifica corrente} (la conseguita per ultima)."""
    from ..models import DipendenteQualifica

    qs = DipendenteQualifica.objects.select_related("tipo")
    if tipo_ids is not None:
        qs = qs.filter(tipo_id__in=list(tipo_ids))
    if legacy_ids is not None:
        qs = qs.filter(legacy_anagrafica_id__in=list(legacy_ids))
    out: dict[tuple[int, int], object] = {}
    for q in qs.order_by("data_conseguimento", "pk"):
        chiave = (q.legacy_anagrafica_id, q.tipo_id)
        attuale = out.get(chiave)
        if attuale is None or (q.data_conseguimento or date.min, q.pk) >= (attuale.data_conseguimento or date.min, attuale.pk):
            out[chiave] = q
    return out


def corsi_per_tipo(tipi) -> dict[int, dict[str, object]]:
    """{abilitazione: {"BASE": corso, "AGGIORNAMENTO": corso}} fra i corsi attivi collegati."""
    from ..models_formazione import TrainingCourse

    out: dict[int, dict[str, object]] = {}
    for c in (TrainingCourse.objects.filter(qualifica_id__in=[t.pk for t in tipi], is_active=True, stato="ATTIVO")
              .order_by("titolo")):
        out.setdefault(c.qualifica_id, {}).setdefault(c.qualifica_effetto, c)
    return out


def corso_per(corsi: dict, stato: str):
    """A chi manca il corso base, a chi scade l'aggiornamento; se ce n'è uno solo, quello."""
    if not corsi:
        return None
    prima, poi = ("BASE", "AGGIORNAMENTO") if stato == MANCANTE else ("AGGIORNAMENTO", "BASE")
    return corsi.get(prima) or corsi.get(poi)


def quadro(legacy_ids=None, *, oggi: date | None = None, solo_richieste: bool = False) -> dict[int, list[dict]]:
    """{persona: [voce]} con le abilitazioni possedute e quelle che le servono.

    Voce: ``tipo``, ``nome``, ``stato``, ``etichetta``, ``tono``, ``scadenza``, ``conseguita``,
    ``motivi``, ``richiesta``, ``corso`` (da proporre se manca o scade), ``qualifica``.
    """
    from ..models import TipoQualifica

    oggi = oggi or timezone.localdate()
    tipi = list(TipoQualifica.objects.filter(is_active=True).prefetch_related("mansioni_rischio"))
    per_id = {t.pk: t for t in tipi}
    servono = richieste(tipi, oggi=oggi)
    ids = set(in_forza_ids() if legacy_ids is None else (int(i) for i in legacy_ids))
    possedute = correnti(per_id.keys(), None if legacy_ids is None else ids)
    corsi = corsi_per_tipo(tipi)

    out: dict[int, list[dict]] = {}
    for (lid, tipo_id), q in possedute.items():
        if lid not in ids:
            continue
        motivi = servono.get(lid, {}).get(tipo_id, [])
        if solo_richieste and not motivi:
            continue
        stato = stato_di(q.data_scadenza, oggi)
        out.setdefault(lid, []).append(_voce(per_id[tipo_id], stato, q, motivi, corsi))
    for lid, per_tipo in servono.items():
        if lid not in ids:
            continue
        for tipo_id, motivi in per_tipo.items():
            if (lid, tipo_id) not in possedute:
                out.setdefault(lid, []).append(_voce(per_id[tipo_id], MANCANTE, None, motivi, corsi))
    for voci in out.values():
        voci.sort(key=lambda v: (_ORDINE[v["stato"]], v["nome"].casefold()))
    return out


def _voce(tipo, stato: str, q, motivi: list[str], corsi: dict) -> dict:
    return {
        "tipo": tipo, "nome": tipo.nome, "stato": stato, "etichetta": ETICHETTE[stato], "tono": TONI[stato],
        "scadenza": q.data_scadenza if q else None, "conseguita": q.data_conseguimento if q else None,
        "motivi": list(motivi), "richiesta": bool(motivi), "qualifica": q,
        "corso": corso_per(corsi.get(tipo.pk, {}), stato) if stato != VALIDA else None,
    }


def riepilogo(voci_per_persona: dict[int, list[dict]]) -> dict[str, int]:
    """Conteggi per stato, sulle stesse voci mostrate in pagina."""
    conta = {VALIDA: 0, IN_SCADENZA: 0, SCADUTA: 0, MANCANTE: 0}
    for voci in voci_per_persona.values():
        for v in voci:
            conta[v["stato"]] += 1
    return conta


# ── Mezzi: chi può usarli ────────────────────────────────────────────────────

def _categorie_con_antenati(categoria) -> list[int]:
    ids, visti = [], set()
    while categoria is not None and categoria.pk not in visti:
        visti.add(categoria.pk)
        ids.append(categoria.pk)
        categoria = categoria.parent
    return ids


def tipi_del_mezzo(asset) -> list:
    """Abilitazioni chieste dalla categoria del mezzo (o da una categoria che la contiene)."""
    from ..models import TipoQualifica

    categoria = getattr(asset, "asset_category", None)
    if categoria is None:
        return []
    return list(TipoQualifica.objects.filter(is_active=True, categorie_asset__in=_categorie_con_antenati(categoria))
                .distinct().order_by("nome"))


def abilitati_asset(asset, *, oggi: date | None = None, nomi: dict | None = None) -> dict | None:
    """``{"tipi", "persone", "n_validi"}`` per la scheda del mezzo; None se il mezzo non chiede nulla.

    Una persona può usare il mezzo se ha valide **tutte** le abilitazioni chieste. In elenco anche
    chi ne ha una scaduta, segnato, così si vede chi rinnovare.
    """
    tipi = tipi_del_mezzo(asset)
    if not tipi:
        return None
    oggi = oggi or timezone.localdate()
    forza = in_forza_ids()
    possedute = correnti([t.pk for t in tipi])
    per_persona: dict[int, list] = {}
    for (lid, _tipo_id), q in possedute.items():
        if lid in forza:
            per_persona.setdefault(lid, []).append(q)
    nomi = nomi or {}
    persone = []
    for lid, qs in per_persona.items():
        stati = [stato_di(q.data_scadenza, oggi) for q in qs]
        completo = len(qs) == len(tipi)
        if SCADUTA in stati:
            stato = SCADUTA
        elif not completo:
            stato = MANCANTE
        elif IN_SCADENZA in stati:
            stato = IN_SCADENZA
        else:
            stato = VALIDA
        scadenze = [q.data_scadenza for q in qs if q.data_scadenza]
        persone.append({"legacy_id": lid, "nome": nomi.get(lid, f"#{lid}"), "stato": stato,
                        "etichetta": "Incompleta" if stato == MANCANTE else ETICHETTE[stato], "tono": TONI[stato],
                        "scadenza": min(scadenze) if scadenze else None, "puo": stato in (VALIDA, IN_SCADENZA)})
    persone.sort(key=lambda p: (not p["puo"], p["nome"].casefold()))
    return {"tipi": tipi, "persone": persone, "n_validi": sum(1 for p in persone if p["puo"])}


# ── Presenti in azienda ──────────────────────────────────────────────────────

def bollini_presenti(oggi: date | None = None) -> dict[int, list[dict]]:
    """{persona: [{nome, colore}]} delle abilitazioni valide da mostrare in «Presenti in azienda»."""
    from ..models import TipoQualifica

    oggi = oggi or timezone.localdate()
    tipi = {t.pk: t for t in TipoQualifica.objects.filter(is_active=True, mostra_in_presenti=True)}
    if not tipi:
        return {}
    out: dict[int, list[dict]] = {}
    for (lid, tipo_id), q in correnti(tipi.keys()).items():
        if stato_di(q.data_scadenza, oggi) == SCADUTA:
            continue
        t = tipi[tipo_id]
        out.setdefault(lid, []).append({"nome": t.nome, "colore": t.colore or COLORE_BOLLINO})
    for voci in out.values():
        voci.sort(key=lambda v: v["nome"].casefold())
    return out


def incarichi_scoperti(oggi: date | None = None) -> dict[int, set[str]]:
    """{persona: {nomi dei ruoli}} dove il ruolo chiede un'abilitazione che la persona non ha valida.

    Vale solo per i ruoli con una qualifica obbligatoria: senza quella scelta il ruolo non è toccato.
    """
    from ..models import DipendenteRuoloOperativo, RuoloQualifica

    oggi = oggi or timezone.localdate()
    richieste_ruolo: dict[int, list[int]] = {}
    for ruolo_id, tipo_id in RuoloQualifica.objects.filter(obbligatoria=True, qualifica__is_active=True).values_list(
            "ruolo_id", "qualifica_id"):
        richieste_ruolo.setdefault(ruolo_id, []).append(tipo_id)
    if not richieste_ruolo:
        return {}
    possedute = correnti({t for ids in richieste_ruolo.values() for t in ids})
    out: dict[int, set[str]] = {}
    for a in DipendenteRuoloOperativo.objects.filter(ruolo_id__in=list(richieste_ruolo)).select_related("ruolo"):
        if (a.data_fine and a.data_fine < oggi) or (a.data_inizio and a.data_inizio > oggi):
            continue
        for tipo_id in richieste_ruolo[a.ruolo_id]:
            q = possedute.get((a.legacy_anagrafica_id, tipo_id))
            if q is None or stato_di(q.data_scadenza, oggi) == SCADUTA:
                out.setdefault(int(a.legacy_anagrafica_id), set()).add(a.ruolo.nome)
    return out
