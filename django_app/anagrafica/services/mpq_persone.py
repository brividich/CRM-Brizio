"""MOD.128 — persone qualificate: requisiti per ruolo e scadenza della persona.

Una persona è qualificata sul processo quando soddisfa i requisiti che valgono
per i suoi ruoli. Ogni requisito ha la sua ricorrenza (una tantum o ogni N mesi),
quindi la scadenza della persona è indipendente da quella del processo.

«Cosa serve a una persona» (``RequisitoPersona``) è l'unico elenco dei requisiti
per persona: i corsi, le visite e i DPI «uguali per tutti» del processo ci sono
stati spostati (migrazione 0225). Fonti (nessun doppione):
- corsi → ``TrainingDeadline`` (Formazione);
- visite → ``VisitaMedica`` (Visite mediche);
- qualifiche → ``DipendenteQualifica`` corrente (Qualifiche);
- DPI → ``ConsegnaDPI`` consegnata (DPI);
- test visivo, esami, ore, affiancamenti, certificati → ``EvidenzaRequisitoPersona``;
- requisiti del processo uguali per tutti (contratto, audit…) → ``mpq_conformita``.

Scadenza di un corso, una visita o una qualifica ricorrente: la più vicina fra
quella propria (attestato, visita, certificato) e ultima data + frequenza del
processo. Il motore della Formazione (``services.requisiti``) applica la stessa
regola, così processo e scadenzario della Formazione dicono la stessa data.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

SOGLIA_IN_SCADENZA = 30
_RELATED = ("corso", "tipo_visita", "tipo_qualifica", "categoria_dpi")

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
            .select_related(*_RELATED).prefetch_related("ruoli")
        )
    ruoli_persona = {r.pk for r in abilitazione.ruoli_processo.all()}
    out = []
    for req in requisiti:
        ruoli_req = {r.pk for r in req.ruoli.all()}
        if not ruoli_req or ruoli_req & ruoli_persona:
            out.append(req)
    return out


def obblighi_richiesti(abilitazione, requisiti=None) -> dict[str, list]:
    """Corsi, tipi visita e categorie DPI dei requisiti persona **bloccanti** della persona.

    Alimentano Formazione (copertura, scadenze, «Iscrivi chi manca»), Visite e il
    semaforo idoneità come obblighi reali; i requisiti non bloccanti restano informativi.
    """
    out: dict[str, list] = {"corsi": [], "visite": [], "dpi": []}
    for req in requisiti_per_abilitazione(abilitazione, requisiti):
        if not req.bloccante:
            continue
        if req.tipo == req.TIPO_CORSO and req.corso_id:
            out["corsi"].append(req.corso)
        elif req.tipo == req.TIPO_VISITA and req.tipo_visita_id:
            out["visite"].append(req.tipo_visita)
        elif req.tipo == req.TIPO_DPI and req.categoria_dpi_id:
            out["dpi"].append(req.categoria_dpi)
    return out


def corsi_visite_richiesti(abilitazione, requisiti=None):
    """(corsi, tipi visita) bloccanti della persona: vedi :func:`obblighi_richiesti`."""
    o = obblighi_richiesti(abilitazione, requisiti)
    return o["corsi"], o["visite"]


def frequenze_corsi(abilitazione, requisiti=None) -> dict[int, tuple[int, bool]]:
    """``{corso_id: (mesi, fine_mese)}``: la frequenza più stretta chiesta dal processo.

    Solo requisiti bloccanti e ricorrenti con una frequenza propria; serve al motore
    della Formazione per accorciare la scadenza dell'attestato.
    """
    out: dict[int, tuple[int, bool]] = {}
    for req in requisiti_per_abilitazione(abilitazione, requisiti):
        if req.bloccante and req.tipo == req.TIPO_CORSO and req.corso_id and req.is_ricorrente:
            att = out.get(req.corso_id)
            if att is None or int(req.frequenza_mesi) < att[0]:
                out[req.corso_id] = (int(req.frequenza_mesi), bool(req.scadenza_fine_mese))
    return out


def _prima(*date_):
    valide = [d for d in date_ if d]
    return min(valide) if valide else None


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
    # La più vicina fra la scadenza dell'attestato e ultima frequenza + frequenza del processo.
    scadenza = _prima(getattr(d, "data_scadenza", None), req.scadenza_da(ultima))
    if req.ricorrenza == req.RICORRENZA_UNA_TANTUM:
        scadenza = None
    return {"stato": _stato_da_scadenza(scadenza, oggi), "scadenza": scadenza, "ultima": ultima}


def _voce_visita(req, oggi, visite):
    v = visite.get(req.tipo_visita_id) if req.tipo_visita_id else None
    if v is None:
        return {"stato": "mancante", "scadenza": None, "ultima": None}
    ultima = getattr(v, "data_svolgimento", None)
    scadenza = _prima(getattr(v, "data_scadenza", None), req.scadenza_da(ultima))
    return {"stato": _stato_da_scadenza(scadenza, oggi), "scadenza": scadenza, "ultima": ultima}


def _voce_qualifica(req, oggi, qualifiche):
    """Qualifica del catalogo: vale la registrazione conseguita per ultima (Qualifiche)."""
    q = qualifiche.get(req.tipo_qualifica_id) if req.tipo_qualifica_id else None
    if q is None:
        return {"stato": "mancante", "scadenza": None, "ultima": None}
    ultima = q.data_conseguimento
    scadenza = _prima(q.data_scadenza, req.scadenza_da(ultima))
    return {"stato": _stato_da_scadenza(scadenza, oggi), "scadenza": scadenza, "ultima": ultima}


def _voce_dpi(req, dpi):
    """DPI: consegnato almeno una volta per la categoria (stessa regola di prima)."""
    if dpi is None:
        return {"stato": "na", "scadenza": None, "ultima": None}
    ok = bool(req.categoria_dpi_id) and req.categoria_dpi_id in dpi
    return {"stato": "ok" if ok else "mancante", "scadenza": None, "ultima": None}


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
    - ``voci``: una per requisito persona (tipo, nome, stato, scadenza, ultima, req, bloccante),
      più i requisiti del processo uguali per tutti (contratto, audit…);
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
        fonti = ctx.get("fonti") or _fonti([legacy_id], reqs)
        deadlines = fonti["deadlines"].get(legacy_id, {})
        visite = fonti["visite"].get(legacy_id, {})
        qualifiche = fonti["qualifiche"].get(legacy_id, {})
        dpi = None if fonti["dpi"] is None else fonti["dpi"].get(legacy_id, set())
        evidenze = (ctx["evidenze"].get(abilitazione.pk, []) if "evidenze" in ctx
                    else list(abilitazione.evidenze.all()))
        for req in reqs:
            if esterno and req.tipo in RequisitoPersona.TIPI_DA_ALTRI_MODULI:
                v = {"stato": "na", "scadenza": None, "ultima": None}
            elif req.tipo == RequisitoPersona.TIPO_CORSO:
                v = _voce_corso(req, legacy_id, oggi, deadlines)
            elif req.tipo == RequisitoPersona.TIPO_VISITA:
                v = _voce_visita(req, oggi, visite)
            elif req.tipo == RequisitoPersona.TIPO_QUALIFICA:
                v = _voce_qualifica(req, oggi, qualifiche)
            elif req.tipo == RequisitoPersona.TIPO_DPI:
                v = _voce_dpi(req, dpi)
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


def _fonti(legacy_ids, requisiti) -> dict:
    """Dati dei moduli collegati per le persone, in poche query.

    ``{"deadlines": {legacy: {corso_id: TrainingDeadline}}, "visite": {legacy: {tipo_id: ultima}},
    "qualifiche": {legacy: {tipo_id: corrente}}, "dpi": {legacy: {categoria_id}} | None}``
    (``dpi`` None = modulo DPI non leggibile: il requisito risulta «non verificabile»).
    """
    from ..models import DipendenteQualifica, TrainingDeadline, VisitaMedica

    ids = [i for i in legacy_ids if i]
    corsi = {r.corso_id for r in requisiti if r.corso_id}
    tipi = {r.tipo_visita_id for r in requisiti if r.tipo_visita_id}
    tipi_q = {r.tipo_qualifica_id for r in requisiti if r.tipo_qualifica_id}
    cat_dpi = {r.categoria_dpi_id for r in requisiti if r.categoria_dpi_id}
    out: dict = {"deadlines": {}, "visite": {}, "qualifiche": {}, "dpi": {}}
    if ids and corsi:
        for d in TrainingDeadline.objects.filter(legacy_anagrafica_id__in=ids, corso_id__in=corsi):
            out["deadlines"].setdefault(d.legacy_anagrafica_id, {})[d.corso_id] = d
    if ids and tipi:
        for v in (VisitaMedica.objects.filter(legacy_anagrafica_id__in=ids, tipo_id__in=tipi)
                  .order_by("-data_svolgimento", "-pk")):
            out["visite"].setdefault(v.legacy_anagrafica_id, {}).setdefault(v.tipo_id, v)
    if ids and tipi_q:
        # Corrente = conseguita per ultima (come Qualifiche e Scadenzario).
        for q in (DipendenteQualifica.objects.filter(legacy_anagrafica_id__in=ids, tipo_id__in=tipi_q)
                  .order_by("legacy_anagrafica_id", "tipo_id", "data_conseguimento", "id")):
            out["qualifiche"].setdefault(q.legacy_anagrafica_id, {})[q.tipo_id] = q
    if ids and cat_dpi:
        try:
            from dpi.models import ConsegnaDPI, StatoRichiesta

            for lid, cat in (ConsegnaDPI.objects
                             .filter(richiesta__richiedente_legacy_id__in=ids,
                                     richiesta__stato=StatoRichiesta.CONSEGNATA,
                                     richiesta__categoria_id__in=cat_dpi)
                             .values_list("richiesta__richiedente_legacy_id", "richiesta__categoria_id")):
                out["dpi"].setdefault(lid, set()).add(cat)
        except Exception:
            out["dpi"] = None
    return out


def _deadlines_visite(legacy_ids, requisiti):
    """Compatibilità: (deadlines, visite) di :func:`_fonti`."""
    f = _fonti(legacy_ids, requisiti)
    return f["deadlines"], f["visite"]


def contesto_processo(processo, abilitazioni):
    """Pre-carica in poche query tutto ciò che serve a :func:`stato_persona`."""
    from ..models_mpq import EvidenzaRequisitoPersona

    requisiti = list(
        processo.requisiti_persona.filter(attivo=True)
        .select_related(*_RELATED).prefetch_related("ruoli")
    )
    ab_ids = [a.pk for a in abilitazioni]
    fonti = _fonti([a.legacy_anagrafica_id for a in abilitazioni], requisiti)
    evidenze: dict[int, list] = {}
    for e in (EvidenzaRequisitoPersona.objects.filter(abilitazione_id__in=ab_ids)
              .select_related("requisito")):
        evidenze.setdefault(e.abilitazione_id, []).append(e)
    certificazioni: dict[int, list] = {}
    for a in abilitazioni:
        certificazioni[a.pk] = list(a.certificazioni.all())
    return {"requisiti": requisiti, "fonti": fonti, "deadlines": fonti["deadlines"],
            "visite": fonti["visite"], "evidenze": evidenze, "certificazioni": certificazioni}


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


def processi_che_richiedono(*, corso=None, tipo_qualifica=None) -> list[dict]:
    """Processi MOD.128 che chiedono il corso o la qualifica in «Cosa serve a una persona».

    Per le schede del corso e della qualifica: ``[{"processo", "ruoli", "quando", "bloccante"}]``.
    """
    from ..models_mpq import RequisitoPersona

    qs = RequisitoPersona.objects.filter(attivo=True).select_related("processo").prefetch_related("ruoli")
    if corso is not None:
        qs = qs.filter(tipo=RequisitoPersona.TIPO_CORSO, corso=corso)
    elif tipo_qualifica is not None:
        qs = qs.filter(tipo=RequisitoPersona.TIPO_QUALIFICA, tipo_qualifica=tipo_qualifica)
    else:
        return []
    out = []
    for r in qs.order_by("processo__nome", "id"):
        if r.ricorrenza == r.RICORRENZA_UNA_TANTUM:
            quando = "Una tantum"
        elif r.is_ricorrente:
            quando = f"Ogni {r.frequenza_mesi} mesi" + (" (a fine mese)" if r.scadenza_fine_mese else "")
        else:
            quando = "Segue la sua scadenza"
        out.append({"processo": r.processo, "ruoli": [x.nome for x in r.ruoli.all()],
                    "quando": quando, "bloccante": r.bloccante})
    return out
