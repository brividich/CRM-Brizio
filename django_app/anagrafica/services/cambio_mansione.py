"""Cambio mansione: cosa cambia per la persona e cosa va fatto prima di spostarla.

Confronta i requisiti della mansione attuale con quelli della mansione di
destinazione usando il motore unico (:mod:`anagrafica.services.requisiti`):

- **rischi** acquisiti e persi (fattori di rischio della mansione / area);
- **formazione** dovuta in più (e quella non più dovuta);
- **visite** dovute in più, o con periodicità più stretta (ricalcolo prudente);
- **DPI** da consegnare;
- **schede di sicurezza** dei prodotti della nuova mansione ancora da leggere.

Da qui nasce il **piano di adeguamento** (``AdempimentoCambioMansione``): una
riga per ogni cosa non ancora a posto, da chiudere entro la decorrenza dello
spostamento. Riferimenti: D.Lgs. 81/2008 art. 41 c. 2 lett. d (visita in
occasione del cambio della mansione), art. 37 c. 4 lett. b (formazione al
cambiamento di mansioni), art. 77 (DPI). Gli adempimenti si chiudono da soli
quando il requisito risulta soddisfatto (:func:`aggiorna_piani`), oppure a mano
come «non necessario» con un motivo.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from . import mansionario, requisiti

logger = logging.getLogger(__name__)

# Una visita registrata fino a 30 giorni prima della registrazione dello spostamento
# vale come «visita al cambio mansione» (spesso si fa prima e si registra dopo).
TOLLERANZA_VISITA_GIORNI = 30
VISITA_CAMBIO = "Visita medica al cambio mansione (D.Lgs. 81/2008 art. 41 c. 2 lett. d)"
FORMAZIONE_RISCHI = "Informazione e formazione sui rischi della nuova mansione (D.Lgs. 81/2008 artt. 36-37)"


@dataclass
class Confronto:
    mansione_attuale: str
    mansione_nuova: str
    rischi_acquisiti: list = field(default_factory=list)
    rischi_persi: list = field(default_factory=list)
    corsi_nuovi: list = field(default_factory=list)          # VoceFormazione sulla nuova mansione
    corsi_non_piu_dovuti: list = field(default_factory=list)  # TrainingCourse
    visite_nuove: list = field(default_factory=list)          # VoceVisita sulla nuova mansione
    visite_non_piu_dovute: list = field(default_factory=list)  # TipoVisitaMedica
    dpi_nuovi: list = field(default_factory=list)              # (CategoriaDPI, consegnato: bool)
    dpi_non_piu_dovuti: list = field(default_factory=list)
    sds_da_leggere: list = field(default_factory=list)
    # (dominio, pk) -> origine strutturata nella mansione di destinazione
    origini_dopo: dict = field(default_factory=dict)

    @property
    def cambia_qualcosa(self) -> bool:
        return any((self.rischi_acquisiti, self.rischi_persi, self.corsi_nuovi, self.corsi_non_piu_dovuti,
                    self.visite_nuove, self.visite_non_piu_dovute, self.dpi_nuovi, self.dpi_non_piu_dovuti,
                    self.sds_da_leggere))

    def as_dict(self, *, include_visite_dettaglio: bool) -> dict:
        def _visita(v):
            nome = v.tipo_da_mostrare.nome if include_visite_dettaglio else "Visita medica richiesta"
            if v.ultima is None:
                return f"{nome}: mai registrata"
            if v.scadenza and v.scadenza < timezone.localdate():
                return f"{nome}: scaduta il {v.scadenza:%d/%m/%Y}"
            return f"{nome}: in regola fino al {v.scadenza:%d/%m/%Y}" if v.scadenza else f"{nome}: in regola"

        def _corso(v):
            stato = {"MAI_FREQUENTATO": "mai frequentato", "SCADUTO": "scaduto"}.get(v.stato, "in regola")
            return f"{v.corso.titolo}: {stato}"

        return {
            "mansione_attuale": self.mansione_attuale,
            "mansione_nuova": self.mansione_nuova,
            "rischi_acquisiti": [f.nome for f in self.rischi_acquisiti],
            "rischi_persi": [f.nome for f in self.rischi_persi],
            "corsi_nuovi": [_corso(v) for v in self.corsi_nuovi],
            "corsi_non_piu_dovuti": [c.titolo for c in self.corsi_non_piu_dovuti],
            "visite_nuove": [_visita(v) for v in self.visite_nuove],
            "visite_non_piu_dovute": ([t.nome for t in self.visite_non_piu_dovute] if include_visite_dettaglio
                                      else (["Visite non più dovute: " + str(len(self.visite_non_piu_dovute))]
                                            if self.visite_non_piu_dovute else [])),
            "dpi_nuovi": [f"{c.nome}: {'già consegnato' if ok else 'da consegnare'}" for c, ok in self.dpi_nuovi],
            "dpi_non_piu_dovuti": [c.nome for c in self.dpi_non_piu_dovuti],
            "sds_da_leggere": [getattr(getattr(s, "prodotto", None), "nome", "") or str(s) for s in self.sds_da_leggere],
            "cambia_qualcosa": self.cambia_qualcosa,
        }


def _dettaglio_mansione(persona, data=None) -> dict:
    return mansionario.requisiti_dipendenti_dettaglio(
        [persona.id], mansioni_per_legacy={persona.id: persona.mansione},
        aree_per_legacy={persona.id: persona.area_aziendale_id}, data=data,
    ).get(persona.id) or {"requisiti": mansionario.requisiti_vuoti(), "origini": {}}


def _dpi_consegnati(legacy_ids: list[int]) -> set[int]:
    """Categorie DPI con una consegna in corso di validita' (qualunque id della persona)."""
    try:
        from dpi.models import ConsegnaDPI, StatoRichiesta
    except Exception:
        return set()
    oggi = timezone.localdate()
    out = set()
    for consegna in ConsegnaDPI.objects.filter(
        richiesta__richiedente_legacy_id__in=legacy_ids, richiesta__stato=StatoRichiesta.CONSEGNATA,
    ).select_related("richiesta"):
        if consegna.data_scadenza_stimata is None or consegna.data_scadenza_stimata >= oggi:
            out.add(consegna.richiesta.categoria_id)
    return out


def confronta(legacy_id: int, mansione_nuova: str, *, area_nuova_id: int | None = None,
              mansione_attuale: str | None = None, area_attuale_id: int | None = None,
              data=None) -> Confronto:
    """Confronto fra la mansione attuale (o quella indicata) e la nuova, per la persona."""
    from .conformita import _persone

    ctx, richiesti = _persone([legacy_id])
    persona = richiesti[legacy_id]
    prima = replace(persona,
                    mansione=(mansione_attuale if mansione_attuale is not None else persona.mansione).strip(),
                    area_aziendale_id=area_attuale_id if area_attuale_id is not None else persona.area_aziendale_id)
    dopo = replace(persona, mansione=(mansione_nuova or "").strip(),
                   area_aziendale_id=area_nuova_id if area_nuova_id is not None else prima.area_aziendale_id)
    out = Confronto(mansione_attuale=prima.mansione, mansione_nuova=dopo.mansione)
    if not dopo.mansione:
        return out

    det_prima, det_dopo = _dettaglio_mansione(prima, data), _dettaglio_mansione(dopo, data)
    out.origini_dopo = det_dopo.get("origini_strutturate") or {}
    fattori_prima = {f.pk: f for f in det_prima["requisiti"].get("fattori") or []}
    fattori_dopo = {f.pk: f for f in det_dopo["requisiti"].get("fattori") or []}
    out.rischi_acquisiti = [f for pk, f in fattori_dopo.items() if pk not in fattori_prima]
    out.rischi_persi = [f for pk, f in fattori_prima.items() if pk not in fattori_dopo]

    corsi_prima = {v.corso.pk for v in requisiti.formazione(ctx, {prima.id: prima}) if v.obbligatorio}
    corsi_dopo = [v for v in requisiti.formazione(ctx, {dopo.id: dopo}) if v.obbligatorio]
    out.corsi_nuovi = [v for v in corsi_dopo if v.corso.pk not in corsi_prima]
    ids_dopo = {v.corso.pk for v in corsi_dopo}
    if corsi_prima - ids_dopo:
        from anagrafica.models_formazione import TrainingCourse
        out.corsi_non_piu_dovuti = list(TrainingCourse.objects.filter(pk__in=corsi_prima - ids_dopo).order_by("titolo"))

    visite_prima = {requisiti._famiglia(v.tipo): v for v in requisiti.visite(ctx, {prima.id: prima}) if v.richiesta}
    visite_dopo = [v for v in requisiti.visite(ctx, {dopo.id: dopo}) if v.richiesta]
    for v in visite_dopo:
        precedente = visite_prima.get(requisiti._famiglia(v.tipo))
        # Nuova famiglia, oppure stessa famiglia con periodicita' piu' stretta (scadenza anticipata).
        if precedente is None or (v.scadenza and precedente.scadenza and v.scadenza < precedente.scadenza):
            out.visite_nuove.append(v)
    famiglie_dopo = {requisiti._famiglia(v.tipo) for v in visite_dopo}
    out.visite_non_piu_dovute = [v.tipo for fam, v in visite_prima.items() if fam not in famiglie_dopo]

    dpi_prima = {c.pk: c for c in det_prima["requisiti"].get("dpi") or []}
    dpi_dopo = {c.pk: c for c in det_dopo["requisiti"].get("dpi") or []}
    consegnati = _dpi_consegnati(list(persona.tutti_gli_id)) if dpi_dopo else set()
    out.dpi_nuovi = [(c, pk in consegnati) for pk, c in dpi_dopo.items() if pk not in dpi_prima]
    out.dpi_non_piu_dovuti = [c for pk, c in dpi_prima.items() if pk not in dpi_dopo]

    if dopo.mansione.casefold() != prima.mansione.casefold():
        try:
            from schede_sicurezza.services.assegnazioni import sds_da_leggere_per_dipendente
            out.sds_da_leggere = list(sds_da_leggere_per_dipendente(persona.id, dopo.mansione).da_leggere)
        except Exception:
            logger.warning("cambio mansione: schede di sicurezza non leggibili", exc_info=True)
    return out


# ═══════════════════════════════════════════════════════════════════════════
# Piano di adeguamento
# ═══════════════════════════════════════════════════════════════════════════

def _voci_piano(confronto: Confronto, entro_il: date) -> list[dict]:
    voci: list[dict] = []
    rischi_sorveglianza = [f for f in confronto.rischi_acquisiti if getattr(f, "richiede_visita_medica", False)]
    for v in confronto.visite_nuove:
        if v.ultima is not None and (v.scadenza is None or v.scadenza >= entro_il):
            continue  # gia' in regola alla decorrenza
        voci.append({"tipo": "VISITA", "riferimento_id": v.tipo_da_mostrare.pk,
                     "descrizione": f"Visita: {v.tipo_da_mostrare.nome}",
                     "motivo": "; ".join(v.origini)[:300]})
    if rischi_sorveglianza and not voci:
        voci.append({"tipo": "VISITA", "riferimento_id": None, "descrizione": VISITA_CAMBIO,
                     "motivo": "Nuovi rischi: " + ", ".join(f.nome for f in rischi_sorveglianza)})
    for v in confronto.corsi_nuovi:
        if v.stato not in ("MAI_FREQUENTATO", "SCADUTO") and (v.scadenza is None or v.scadenza >= entro_il):
            continue
        voci.append({"tipo": "FORMAZIONE", "riferimento_id": v.corso.pk, "descrizione": f"Corso: {v.corso.titolo}",
                     "motivo": "; ".join(v.origini)[:300]})
    if confronto.rischi_acquisiti and not any(x["tipo"] == "FORMAZIONE" for x in voci) and not confronto.corsi_nuovi:
        voci.append({"tipo": "FORMAZIONE", "riferimento_id": None, "descrizione": FORMAZIONE_RISCHI,
                     "motivo": "Nuovi rischi: " + ", ".join(f.nome for f in confronto.rischi_acquisiti)})
    for categoria, consegnato in confronto.dpi_nuovi:
        if not consegnato:
            voci.append({"tipo": "DPI", "riferimento_id": categoria.pk, "descrizione": f"DPI: {categoria.nome}",
                         "motivo": f"Richiesto dalla mansione «{confronto.mansione_nuova}»"})
    if confronto.sds_da_leggere:
        voci.append({"tipo": "SDS", "riferimento_id": None,
                     "descrizione": f"Presa visione schede di sicurezza ({len(confronto.sds_da_leggere)})",
                     "motivo": f"Prodotti della mansione «{confronto.mansione_nuova}»"})
    return voci


def chiave_voce(tipo: str, riferimento_id: int | None) -> str:
    """Chiave stabile di un requisito del piano: «TIPO:riferimento» (0 = generico)."""
    return f"{tipo}:{riferimento_id or 0}"


_DOMINIO_PER_TIPO = {"VISITA": "visite", "FORMAZIONE": "corsi", "DPI": "dpi"}
_TIPO_PER_DOMINIO = {v: k for k, v in _DOMINIO_PER_TIPO.items()}


def _origine(voce: dict, origini_dopo: dict) -> dict:
    """Origine strutturata della voce (mansione di rischio / override), se nota."""
    dominio = _DOMINIO_PER_TIPO.get(voce["tipo"])
    origine = origini_dopo.get((dominio, voce["riferimento_id"])) if dominio and voce["riferimento_id"] else None
    if not origine:
        return {"origine_tipo": "ALTRO" if voce["riferimento_id"] is None else "MANSIONE"}
    return {
        "origine_tipo": origine.get("tipo", "ALTRO"),
        "origine_mansione_rischio_id": origine.get("mansione_rischio_id"),
        "origine_override_id": origine.get("override_id"),
    }


@transaction.atomic
def genera_piano(assegnazione, *, mansione_precedente: str, area_precedente_id: int | None = None,
                 user=None) -> list:
    """Allinea il piano di adeguamento dello spostamento al delta dei requisiti.

    Idempotente: ogni requisito ha una ``chiave`` stabile. Rieseguire con gli
    stessi dati non crea doppioni; le voci aperte ancora dovute si aggiornano,
    quelle non più dovute passano a «non più dovuto» (con traccia, non
    cancellate), quelle già chiuse (fatte o «non necessarie») restano storia.
    L'assegnazione è bloccata (``select_for_update``) per evitare che due
    rigenerazioni concorrenti si sovrappongano. Ritorna le voci create.
    """
    from ..models import AdempimentoCambioMansione as A, DipendenteAssegnazione
    from . import eventi_sicurezza

    DipendenteAssegnazione.objects.select_for_update().filter(pk=assegnazione.pk).first()
    confronto = confronta(assegnazione.legacy_anagrafica_id, assegnazione.mansione,
                          area_nuova_id=assegnazione.area_aziendale_id,
                          mansione_attuale=mansione_precedente, area_attuale_id=area_precedente_id,
                          data=assegnazione.data_inizio)
    voci = {chiave_voce(v["tipo"], v["riferimento_id"]): v for v in _voci_piano(confronto, assegnazione.data_inizio)}
    esistenti = {a.chiave: a for a in assegnazione.adempimenti.filter(attivo=True)}
    adesso = timezone.now()
    creati, aggiornati, non_piu_dovuti = [], 0, 0

    for chiave, voce in voci.items():
        origine = _origine(voce, confronto.origini_dopo)
        attuale = esistenti.get(chiave)
        if attuale is None:
            creati.append(A.objects.create(
                assegnazione=assegnazione, legacy_anagrafica_id=assegnazione.legacy_anagrafica_id,
                entro_il=assegnazione.data_inizio, chiave=chiave, **voce, **origine,
            ))
            continue
        if attuale.stato != A.STATO_APERTO:
            continue  # gia' chiusa: e' storia, non si riapre da sola
        campi = {"descrizione": voce["descrizione"], "motivo": voce["motivo"],
                 "entro_il": assegnazione.data_inizio, **origine}
        cambiati = [k for k, v in campi.items() if getattr(attuale, k) != v]
        if cambiati:
            for k in cambiati:
                setattr(attuale, k, campi[k])
            attuale.save(update_fields=cambiati)
            aggiornati += 1

    # Requisiti ancora dovuti alla persona (mansione di destinazione + override +
    # area + esposizioni dirette): una voce nata da un override o da un
    # riallineamento sta sulla stessa card e non va chiusa solo perché il delta
    # dello spostamento non la contiene.
    dovuti = mansionario.requisiti_dipendente(
        assegnazione.legacy_anagrafica_id, mansione_nome=assegnazione.mansione,
        area_id=assegnazione.area_aziendale_id, data=max(timezone.localdate(), assegnazione.data_inizio),
    )
    ancora = {chiave_voce(t, getattr(o, "pk", o)) for d, t in _TIPO_PER_DOMINIO.items() for o in dovuti.get(d) or []}
    for chiave, attuale in esistenti.items():
        if chiave in voci or chiave in ancora or attuale.stato != A.STATO_APERTO:
            continue
        attuale.stato = A.STATO_NON_PIU_DOVUTO
        attuale.attivo = False
        attuale.chiuso_il = adesso
        attuale.chiuso_da = user if getattr(user, "is_authenticated", False) else None
        attuale.chiusura_nota = "Non più dovuto: i requisiti della mansione di destinazione sono cambiati"
        attuale.save(update_fields=["stato", "attivo", "chiuso_il", "chiuso_da", "chiusura_nota"])
        non_piu_dovuti += 1

    if creati or aggiornati or non_piu_dovuti:
        eventi_sicurezza.registra(
            assegnazione.legacy_anagrafica_id, "PIANO_AGGIORNATO",
            f"Piano di adeguamento per «{assegnazione.mansione}»: {len(creati)} nuovi, "
            f"{aggiornati} aggiornati, {non_piu_dovuti} non più dovuti",
            user=user, data_effetto=assegnazione.data_inizio, oggetto=assegnazione,
            payload={"assegnazione_id": assegnazione.pk, "mansione": assegnazione.mansione,
                     "mansione_precedente": mansione_precedente, "creati": len(creati),
                     "aggiornati": aggiornati, "non_piu_dovuti": non_piu_dovuti},
        )
    if creati:
        legacy_id, pk = assegnazione.legacy_anagrafica_id, assegnazione.pk
        transaction.on_commit(lambda: _notifica_piano_dopo_commit(legacy_id, pk))
    return creati


def _notifica_piano_dopo_commit(legacy_id: int, assegnazione_id: int) -> None:
    try:
        from .notifiche_cambio_mansione import notifica_piano_cambio_mansione
        notifica_piano_cambio_mansione(legacy_id, assegnazione_id)
    except Exception:
        logger.warning("notifica piano cambio mansione fallita (assegnazione %s)", assegnazione_id, exc_info=True)


@transaction.atomic
def annulla_piano(assegnazione, *, motivo: str, user=None) -> int:
    """Annulla (non cancella) gli adempimenti di uno spostamento annullato.

    Le voci aperte diventano ANNULLATO con il motivo; quelle già chiuse restano
    com'erano. Va chiamata PRIMA di eliminare l'assegnazione: dopo, il
    collegamento va a NULL (SET_NULL) e la riga resta nella storia.
    """
    from ..models import AdempimentoCambioMansione as A

    motivo = (motivo or "").strip()[:300] or "Spostamento programmato annullato"
    adesso = timezone.now()
    annullati = 0
    for adempimento in assegnazione.adempimenti.select_for_update().filter(stato=A.STATO_APERTO):
        adempimento.stato = A.STATO_ANNULLATO
        adempimento.attivo = False
        adempimento.annullato_il = adesso
        adempimento.annullato_da = user if getattr(user, "is_authenticated", False) else None
        adempimento.annullato_motivo = motivo
        adempimento.save(update_fields=["stato", "attivo", "annullato_il", "annullato_da", "annullato_motivo"])
        annullati += 1
    return annullati


def _soddisfatto(adempimento, ctx, persona) -> str:
    """Motivo di chiusura automatica, o stringa vuota se l'adempimento e' ancora da fare."""
    return requisito_soddisfatto(
        adempimento.tipo, adempimento.riferimento_id, ctx=ctx, persona=persona,
        # Retroattivo registrato tardi: la tolleranza parte dalla decorrenza, non
        # dalla data di registrazione (vale la piu' vecchia delle due).
        dal=min(adempimento.assegnazione.created_at.date(), adempimento.assegnazione.data_inizio),
        mansione=adempimento.assegnazione.mansione, entro=adempimento.entro_il,
    )


def requisito_soddisfatto(tipo_voce: str, riferimento_id: int | None, *, ctx, persona,
                          dal: date, mansione: str, entro: date | None = None) -> str:
    """Verifica condivisa (piano cambio mansione e onboarding): motivo di chiusura
    automatica, o stringa vuota se il requisito e' ancora da soddisfare.

    ``tipo_voce`` e' uno fra VISITA / FORMAZIONE / DPI / SDS; ``dal`` e' la data
    da cui una visita generica conta (nascita della voce, con tolleranza).
    """
    from ..models import AdempimentoCambioMansione as A, TipoVisitaMedica, VisitaMedica

    oggi = timezone.localdate()
    if tipo_voce == A.TIPO_VISITA:
        if riferimento_id is None:
            soglia = dal - timedelta(days=TOLLERANZA_VISITA_GIORNI)
            visita = (VisitaMedica.objects.filter(legacy_anagrafica_id__in=persona.tutti_gli_id,
                                                  data_svolgimento__gte=soglia, superata_il__isnull=True)
                      .order_by("-data_svolgimento").first())
            return f"Visita registrata il {visita.data_svolgimento:%d/%m/%Y}" if visita else ""
        tipo = TipoVisitaMedica.objects.filter(pk=riferimento_id).first()
        if tipo is None:
            return "Tipo di visita non più a catalogo"
        famiglia = requisiti._famiglia(tipo)
        from .visite import ultime_visite_correnti_ids
        for v in VisitaMedica.objects.filter(pk__in=list(ultime_visite_correnti_ids(
                list(persona.tutti_gli_id), includi_cessati=True))).select_related("tipo"):
            if requisiti._famiglia(v.tipo) != famiglia:
                continue
            scadenza = requisiti.scadenza_prudente(v.data_svolgimento, v.tipo.durata_mesi, tipo.durata_mesi)
            # Deve valere fino alla decorrenza, non solo oggi: una visita che
            # scade prima dello spostamento non copre il cambio mansione.
            if scadenza is None or scadenza >= max(oggi, entro or oggi):
                return f"Visita «{v.tipo.nome}» del {v.data_svolgimento:%d/%m/%Y}"
        return ""
    if tipo_voce == A.TIPO_FORMAZIONE:
        if riferimento_id is None:
            return ""  # informazione/formazione generica: si chiude a mano
        ultimo = requisiti.ultimi_completamenti(ctx, {persona.id: persona}).get((persona.id, riferimento_id))
        if ultimo and (ultimo[1] is None or ultimo[1] >= max(oggi, entro or oggi)):
            return f"Corso completato il {ultimo[0]:%d/%m/%Y}"
        return ""
    if tipo_voce == A.TIPO_DPI:
        return "DPI consegnato" if riferimento_id in _dpi_consegnati(list(persona.tutti_gli_id)) else ""
    if tipo_voce == A.TIPO_SDS:
        try:
            from schede_sicurezza.services.assegnazioni import sds_da_leggere_per_dipendente
            dovute = sds_da_leggere_per_dipendente(persona.id, mansione)
        except Exception:
            return ""
        if dovute.legacy_user_id is None:
            return ""  # senza account la presa visione non e' registrabile: non e' «tutto letto»
        return "" if dovute.da_leggere else "Tutte le schede lette"
    return ""


def aggiorna_piani(legacy_ids=None) -> dict[str, int]:
    """Chiude gli adempimenti aperti il cui requisito ora risulta soddisfatto."""
    from ..models import AdempimentoCambioMansione

    aperti = AdempimentoCambioMansione.objects.filter(
        stato=AdempimentoCambioMansione.STATO_APERTO, attivo=True, assegnazione__isnull=False,
    )
    if legacy_ids is not None:
        aperti = aperti.filter(legacy_anagrafica_id__in=[int(i) for i in legacy_ids])
    aperti = list(aperti.select_related("assegnazione"))
    if not aperti:
        return {"controllati": 0, "chiusi": 0}
    ctx = requisiti.ambito()
    tutti = {d.id: d for d in ctx._tutti()}
    chiusi = 0
    for adempimento in aperti:
        persona = tutti.get(ctx.canonico(adempimento.legacy_anagrafica_id))
        if persona is None:
            continue
        try:
            motivo = _soddisfatto(adempimento, ctx, persona)
        except Exception:
            logger.exception("verifica adempimento %s fallita", adempimento.pk)
            continue
        if motivo:
            from . import eventi_sicurezza
            with transaction.atomic():
                aggiornate = AdempimentoCambioMansione.objects.filter(
                    pk=adempimento.pk, stato=AdempimentoCambioMansione.STATO_APERTO,
                ).update(stato=AdempimentoCambioMansione.STATO_COMPLETATO, chiuso_il=timezone.now(),
                         chiusura_automatica=True, chiusura_nota=motivo[:300])
                if not aggiornate:
                    continue  # chiuso nel frattempo da un'altra esecuzione
                eventi_sicurezza.registra(
                    adempimento.legacy_anagrafica_id, "ADEMPIMENTO_CHIUSO",
                    f"{adempimento.get_tipo_display()}: chiuso automaticamente",
                    oggetto=adempimento,
                    payload={"adempimento_id": adempimento.pk, "chiave": adempimento.chiave},
                )
            chiusi += 1
    return {"controllati": len(aperti), "chiusi": chiusi}
