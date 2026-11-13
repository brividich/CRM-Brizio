"""MOD.128 — persone qualificate: requisiti per ruolo e scadenza della persona.

Una persona è qualificata sul processo quando soddisfa i requisiti che valgono
per i suoi ruoli. Ogni requisito ha la sua ricorrenza (una tantum o ogni N mesi),
quindi la scadenza della persona è indipendente da quella del processo.

Fonti (nessun doppione):
- corsi → ``TrainingDeadline.data_ultimo_completamento`` (Formazione);
- visite → ``VisitaMedica`` (Visite mediche);
- test visivo, esami, ore, affiancamenti, certificati → ``EvidenzaRequisitoPersona``;
- i requisiti «storici» del processo (corsi/visite/DPI M2M, requisiti tipizzati,
  certificazioni individuali) restano letti da ``mpq_conformita.verifica_requisiti``.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

SOGLIA_IN_SCADENZA = 30

_ESITO_LABEL = {
    "ok": "Qualificata",
    "warn": "In scadenza",
    "incompleto": "Incompleta",
    "ko": "Non qualificata",
    "nessuno": "Nessun requisito",
}


def requisiti_per_abilitazione(abilitazione, requisiti=None):
    """Requisiti persona attivi che valgono per i ruoli dell'abilitazione.

    Un requisito senza ruoli vale per tutti; uno con ruoli vale solo per chi ha
    almeno uno di quei ruoli. ``requisiti`` (già con ``ruoli`` prefetchati) evita
    una query per persona quando si elabora un processo intero.
    """
    if requisiti is None:
        requisiti = list(
            abilitazione.processo.requisiti_persona.filter(attivo=True)
            .select_related("corso", "tipo_visita").prefetch_related("ruoli")
        )
    ruoli_persona = {r.pk for r in abilitazione.ruoli_processo.all()}
    out = []
    for req in requisiti:
        ruoli_req = {r.pk for r in req.ruoli.all()}
        if not ruoli_req or ruoli_req & ruoli_persona:
            out.append(req)
    return out


def corsi_visite_richiesti(abilitazione, requisiti=None):
    """(corsi, tipi visita) dei requisiti persona **bloccanti** che valgono per la persona.

    Alimentano Formazione (copertura, scadenze, «Iscrivi chi manca») e il semaforo
    idoneità come obblighi reali; i requisiti non bloccanti restano informativi.
    """
    corsi, visite = [], []
    for req in requisiti_per_abilitazione(abilitazione, requisiti):
        if not req.bloccante:
            continue
        if req.tipo == req.TIPO_CORSO and req.corso_id:
            corsi.append(req.corso)
        elif req.tipo == req.TIPO_VISITA and req.tipo_visita_id:
            visite.append(req.tipo_visita)
    return corsi, visite


def _stato_da_scadenza(scadenza, oggi):
    if scadenza is None:
        return "ok"
    if scadenza < oggi:
        return "scaduto"
    if (scadenza - oggi).days <= SOGLIA_IN_SCADENZA:
        return "in_scadenza"
    return "ok"


def _voce_corso(req, legacy_id, oggi, deadlines):
    d = deadlines.get(req.corso_id) if req.corso_id else None
    ultima = getattr(d, "data_ultimo_completamento", None)
    if not req.corso_id:
        return {"stato": "mancante", "scadenza": None, "ultima": None}
    if ultima is None:
        return {"stato": "mancante", "scadenza": None, "ultima": None}
    # Ricorrenza del processo se dichiarata, altrimenti la scadenza del corso.
    scadenza = req.scadenza_da(ultima) if req.is_ricorrente else getattr(d, "data_scadenza", None)
    if req.ricorrenza == req.RICORRENZA_UNA_TANTUM:
        scadenza = None
    return {"stato": _stato_da_scadenza(scadenza, oggi), "scadenza": scadenza, "ultima": ultima}


def _voce_visita(req, oggi, visite):
    v = visite.get(req.tipo_visita_id) if req.tipo_visita_id else None
    if v is None:
        return {"stato": "mancante", "scadenza": None, "ultima": None}
    ultima = getattr(v, "data_svolgimento", None)
    scadenza = req.scadenza_da(ultima) if req.is_ricorrente else getattr(v, "data_scadenza", None)
    return {"stato": _stato_da_scadenza(scadenza, oggi), "scadenza": scadenza, "ultima": ultima}


def _voce_evidenza(req, evidenze, oggi):
    """Evidenze proprie (test visivo, esame, ore…): l'ultima superata decide."""
    mie = [e for e in evidenze if e.requisito_id == req.pk]
    if req.tipo == req.TIPO_ESPERIENZA and req.ore_minime:
        ore = sum((e.ore or Decimal("0")) for e in mie if e.esito == e.ESITO_SUPERATO)
        ultima = max((e.data_esecuzione for e in mie), default=None)
        stato = "ok" if ore >= req.ore_minime else "mancante"
        return {"stato": stato, "scadenza": None, "ultima": ultima,
                "dettaglio": f"{ore:g} / {req.ore_minime:g} ore", "evidenza": mie[0] if mie else None}
    superate = [e for e in mie if e.esito == e.ESITO_SUPERATO]
    if not superate:
        stato = "scaduto" if mie else "mancante"  # c'è solo un esito negativo
        return {"stato": stato, "scadenza": None, "ultima": mie[0].data_esecuzione if mie else None,
                "evidenza": mie[0] if mie else None}
    e = superate[0]  # ordinate per data decrescente
    scadenza = e.scadenza_effettiva
    return {"stato": _stato_da_scadenza(scadenza, oggi), "scadenza": scadenza,
            "ultima": e.data_esecuzione, "evidenza": e}


def _esito(voci):
    bloccanti = [v["stato"] for v in voci if v.get("bloccante", True)]
    if not voci:
        return "nessuno"
    if "scaduto" in bloccanti:
        return "ko"
    if "mancante" in bloccanti:
        return "incompleto"
    if "in_scadenza" in bloccanti:
        return "warn"
    return "ok"


def stato_persona(abilitazione, *, oggi=None, requisiti=None, contesto=None):
    """Stato di qualifica di una persona sul processo.

    Ritorna ``{"esito", "label", "operativa", "scadenza", "voci", "n_mancanti"}``:
    - ``voci``: una per requisito (tipo, nome, stato, scadenza, ultima, req, bloccante),
      più quelle storiche del processo (corsi/visite/DPI/requisiti tipizzati);
    - ``scadenza``: la prima scadenza fra i requisiti bloccanti e le certificazioni
      individuali attive (None = non scade);
    - ``operativa``: abilitazione ATTIVA ed esito ok/warn/nessuno.
    ``contesto`` (da :func:`contesto_processo`) evita query ripetute per persona.
    """
    from ..models_mpq import AbilitazioneProcesso, CertificazioneIndividuale, RequisitoPersona
    from .mpq_conformita import verifica_requisiti

    oggi = oggi or timezone.localdate()
    legacy_id = abilitazione.legacy_anagrafica_id
    esterno = bool(abilitazione.nominativo_esterno) or not legacy_id
    ctx = contesto or {}
    voci: list[dict] = []

    reqs = requisiti_per_abilitazione(abilitazione, requisiti if requisiti is not None
                                      else ctx.get("requisiti"))
    if reqs:
        if "deadlines" in ctx:
            deadlines = ctx["deadlines"].get(legacy_id, {})
            visite = ctx["visite"].get(legacy_id, {})
        else:
            deadlines, visite = _deadlines_visite([legacy_id], reqs)
            deadlines, visite = deadlines.get(legacy_id, {}), visite.get(legacy_id, {})
        evidenze = (ctx["evidenze"].get(abilitazione.pk, []) if "evidenze" in ctx
                    else list(abilitazione.evidenze.all()))
        for req in reqs:
            if req.tipo == RequisitoPersona.TIPO_CORSO:
                v = ({"stato": "na", "scadenza": None, "ultima": None} if esterno
                     else _voce_corso(req, legacy_id, oggi, deadlines))
            elif req.tipo == RequisitoPersona.TIPO_VISITA:
                v = ({"stato": "na", "scadenza": None, "ultima": None} if esterno
                     else _voce_visita(req, oggi, visite))
            else:
                v = _voce_evidenza(req, evidenze, oggi)
            v.update({
                "tipo": req.get_tipo_display(), "nome": req.etichetta, "req": req,
                "bloccante": req.bloccante, "ricorrenza": req.get_ricorrenza_display(),
                "frequenza_mesi": req.frequenza_mesi if req.is_ricorrente else None,
            })
            voci.append(v)

    if not esterno:
        storiche = verifica_requisiti(abilitazione.processo, legacy_id, oggi=oggi)
        for v in storiche["voci"]:
            voci.append({**v, "bloccante": v.get("obbligatorio", True), "scadenza": None,
                         "ultima": None, "req": None})

    scadenze = [v["scadenza"] for v in voci if v.get("bloccante", True) and v.get("scadenza")]
    certs = (ctx["certificazioni"].get(abilitazione.pk, []) if "certificazioni" in ctx
             else list(abilitazione.certificazioni.all()))
    for c in certs:
        if c.stato == CertificazioneIndividuale.STATO_ATTIVA and c.data_scadenza:
            scadenze.append(c.data_scadenza)
            voci.append({
                "tipo": "Certificazione", "nome": f"{c.schema} {c.numero}".strip(),
                "stato": _stato_da_scadenza(c.data_scadenza, oggi), "scadenza": c.data_scadenza,
                "ultima": None, "req": None, "bloccante": True,
            })

    esito = _esito(voci)
    operativa = (abilitazione.stato == AbilitazioneProcesso.STATO_ATTIVA
                 and esito in ("ok", "warn", "nessuno"))
    return {
        "esito": esito,
        "label": _ESITO_LABEL[esito],
        "operativa": operativa,
        "scadenza": min(scadenze) if scadenze else None,
        "voci": voci,
        "n_mancanti": sum(1 for v in voci if v.get("bloccante", True)
                          and v["stato"] in ("scaduto", "mancante")),
    }


def _deadlines_visite(legacy_ids, requisiti):
    """{legacy: {corso_id: TrainingDeadline}}, {legacy: {tipo_visita_id: ultima VisitaMedica}}."""
    from ..models import TrainingDeadline, VisitaMedica

    ids = [i for i in legacy_ids if i]
    corsi = {r.corso_id for r in requisiti if r.corso_id}
    tipi = {r.tipo_visita_id for r in requisiti if r.tipo_visita_id}
    deadlines: dict[int, dict] = {}
    visite: dict[int, dict] = {}
    if ids and corsi:
        for d in TrainingDeadline.objects.filter(legacy_anagrafica_id__in=ids, corso_id__in=corsi):
            deadlines.setdefault(d.legacy_anagrafica_id, {})[d.corso_id] = d
    if ids and tipi:
        for v in (VisitaMedica.objects.filter(legacy_anagrafica_id__in=ids, tipo_id__in=tipi)
                  .order_by("-data_svolgimento", "-pk")):
            visite.setdefault(v.legacy_anagrafica_id, {}).setdefault(v.tipo_id, v)
    return deadlines, visite


def contesto_processo(processo, abilitazioni):
    """Pre-carica in poche query tutto ciò che serve a :func:`stato_persona`."""
    from ..models_mpq import EvidenzaRequisitoPersona

    requisiti = list(
        processo.requisiti_persona.filter(attivo=True)
        .select_related("corso", "tipo_visita").prefetch_related("ruoli")
    )
    ab_ids = [a.pk for a in abilitazioni]
    deadlines, visite = _deadlines_visite([a.legacy_anagrafica_id for a in abilitazioni], requisiti)
    evidenze: dict[int, list] = {}
    for e in (EvidenzaRequisitoPersona.objects.filter(abilitazione_id__in=ab_ids)
              .select_related("requisito")):
        evidenze.setdefault(e.abilitazione_id, []).append(e)
    certificazioni: dict[int, list] = {}
    for a in abilitazioni:
        certificazioni[a.pk] = list(a.certificazioni.all())
    return {"requisiti": requisiti, "deadlines": deadlines, "visite": visite,
            "evidenze": evidenze, "certificazioni": certificazioni}


def processi_della_persona(legacy_id, *, oggi=None) -> list[dict]:
    """Processi a cui la persona è abilitata, con il suo stato (scheda dipendente)."""
    from ..models_mpq import AbilitazioneProcesso

    oggi = oggi or timezone.localdate()
    out = []
    abilitazioni = (AbilitazioneProcesso.objects
                    .filter(legacy_anagrafica_id=legacy_id, nominativo_esterno="")
                    .exclude(stato=AbilitazioneProcesso.STATO_DISMESSA)
                    .select_related("processo", "processo__cliente")
                    .prefetch_related("ruoli_processo", "certificazioni", "evidenze")
                    .order_by("processo__nome"))
    for ab in abilitazioni:
        stato = stato_persona(ab, oggi=oggi)
        out.append({"abilitazione": ab, "processo": ab.processo, "stato": stato,
                    "ruoli": [r.nome for r in ab.ruoli_processo.all()]})
    return out


def persone_in_scadenza(*, giorni=60, oggi=None) -> list[dict]:
    """Persone (abilitazioni ATTIVE) non qualificate o con scadenza entro ``giorni``."""
    from ..models_mpq import AbilitazioneProcesso, ProcessoQualificato

    oggi = oggi or timezone.localdate()
    limite = oggi + timedelta(days=giorni)
    out = []
    processi = ProcessoQualificato.objects.filter(stato=ProcessoQualificato.STATO_ATTIVO)
    for p in processi:
        abil = list(p.abilitazioni.filter(stato=AbilitazioneProcesso.STATO_ATTIVA)
                    .prefetch_related("ruoli_processo", "certificazioni"))
        if not abil:
            continue
        ctx = contesto_processo(p, abil)
        for ab in abil:
            st = stato_persona(ab, oggi=oggi, contesto=ctx)
            if st["esito"] in ("ko", "incompleto") or (st["scadenza"] and st["scadenza"] <= limite):
                out.append({"processo": p, "abilitazione": ab, "stato": st})
    return out
