"""Quiz e-learning con set servito e token, corretto solo lato server.

- ``apri_tentativo``: sotto lock dell'iscrizione verifica che il quiz sia
  disponibile (slide, tempo, tentativi, attesa), estrae le domande (a caso se la
  regola lo chiede), mescola le opzioni e salva **cosa è stato servito**
  (``domande_servite_json``) con un token. Un tentativo aperto e non scaduto
  viene riproposto invece di aprirne un altro (ricaricare non regala tentativi).
- ``domande_servite``: domande e opzioni nell'ordine servito, senza il campo
  ``corretta`` (il template non lo riceve mai).
- ``correggi``: per token, discente e stato APERTO; si correggono solo le domande
  e le opzioni servite (gli id estranei si ignorano); scaduto → SCADUTO.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .elearning_regole import Regola


class QuizNonDisponibile(Exception):
    pass


VERO, FALSO = "Vero", "Falso"


def problema_domanda(d) -> str:
    """Perché la domanda non può andare nel quiz (stringa vuota = valida).

    Una domanda mal costruita sarebbe impossibile da superare o ambigua: resta
    fuori dal quiz finché l'autore non la sistema (l'editor mostra il motivo)."""
    opzioni = list(d.opzioni.all())
    giuste = sum(1 for o in opzioni if o.corretta)
    tipo = getattr(d, "tipo", "") or "SINGOLA"
    if tipo == "VERO_FALSO":
        if len(opzioni) != 2 or giuste != 1:
            return "Vero/falso: indica se l'affermazione è vera o falsa."
        return ""
    if tipo == "SINGOLA" and giuste != 1:
        return ("Risposta singola: segna una sola opzione corretta."
                if giuste else "Nessuna risposta corretta selezionata.")
    if not giuste:
        return "Nessuna risposta corretta selezionata."
    return ""


def domande_valide(corso) -> list:
    domande = list(corso.quiz_domande.filter(is_active=True).prefetch_related("opzioni").order_by("ordine", "pk"))
    return [d for d in domande if not problema_domanda(d)]


def imposta_vero_falso(domanda, vera: bool) -> None:
    """Riduce le opzioni di una domanda vero/falso esattamente a «Vero» e «Falso»."""
    from ..models_formazione import TrainingQuizOption

    domanda.opzioni.exclude(testo__in=(VERO, FALSO)).delete()
    for ordine, testo in ((1, VERO), (2, FALSO)):
        opzione = domanda.opzioni.filter(testo=testo).order_by("pk").first()
        if opzione is None:
            opzione = TrainingQuizOption(domanda=domanda, testo=testo)
        opzione.ordine = ordine
        opzione.corretta = (testo == VERO) == vera
        opzione.save()
        domanda.opzioni.filter(testo=testo).exclude(pk=opzione.pk).delete()


def blocco(enr, regola: Regola, ordini: list[int], *, adesso=None) -> str:
    """Motivo per cui il quiz non si può aprire ora (stringa vuota = disponibile)."""
    from ..models_formazione import TrainingQuizAttempt

    if enr.stato == "COMPLETATO":
        return "Hai già completato questo corso."
    if regola.richiede_tutte_slide and not tutte_completate(enr):
        return "Il quiz si apre dopo aver completato tutte le slide."
    if regola.tempo_minimo_minuti and (enr.secondi_accreditati or 0) < regola.tempo_minimo_minuti * 60:
        mancano = regola.tempo_minimo_minuti - (enr.secondi_accreditati or 0) // 60
        return f"Mancano circa {mancano} minuti di fruizione effettiva prima del quiz."
    massimo = regola.max_tentativi + int(enr.tentativi_extra or 0) if regola.max_tentativi else 0
    if massimo and (enr.n_tentativi or 0) >= massimo:
        return "Hai esaurito i tentativi disponibili: chiedi a HR lo sblocco."
    if regola.attesa_minuti:
        # Anche un tentativo lasciato scadere fa partire l'attesa (dall'apertura).
        ultimo = (TrainingQuizAttempt.objects.filter(enrollment=enr, stato__in=("INVIATO", "SCADUTO"))
                  .exclude(iniziato_il__isnull=True, inviato_il__isnull=True)
                  .order_by("-iniziato_il", "-inviato_il").values_list("iniziato_il", flat=True).first())
        adesso = adesso or timezone.now()
        if ultimo and adesso < ultimo + timedelta(minutes=regola.attesa_minuti):
            minuti = int((ultimo + timedelta(minutes=regola.attesa_minuti) - adesso).total_seconds() // 60) + 1
            return f"Puoi riprovare il quiz fra {minuti} minuti."
    return ""


def _scadi(enr, tentativo) -> None:
    """Un tentativo lasciato scadere CONSUMA un tentativo: altrimenti, facendo
    scadere i quiz, si vedrebbe tutta la banca domande senza limiti."""
    tentativo.stato = "SCADUTO"
    tentativo.save(update_fields=["stato"])
    enr.n_tentativi = (enr.n_tentativi or 0) + 1
    enr.save(update_fields=["n_tentativi", "updated_at"])


def tutte_completate(enr) -> bool:
    """Tutte le slide attive completate (anche quelle aggiunte dopo l'inizio del corso)."""
    from ..models_elearning import TrainingElearningSlideView
    attive = set(enr.corso.slides.filter(is_active=True).values_list("pk", flat=True))
    fatte = set(TrainingElearningSlideView.objects.filter(
        enrollment=enr, completata=True, slide_id__in=attive).values_list("slide_id", flat=True))
    return bool(attive) and attive <= fatte


def tentativi_rimasti(enr, regola: Regola):
    massimo = regola.max_tentativi + int(enr.tentativi_extra or 0) if regola.max_tentativi else 0
    return max(massimo - (enr.n_tentativi or 0), 0) if massimo else None


def apri_tentativo(enr, regola: Regola, ordini: list[int], *, user=None):
    from ..models_formazione import TrainingElearningEnrollment, TrainingQuizAttempt

    with transaction.atomic():
        enr = TrainingElearningEnrollment.objects.select_for_update().select_related("corso").get(pk=enr.pk)
        adesso = timezone.now()
        aperto = (TrainingQuizAttempt.objects.filter(enrollment=enr, stato="APERTO").order_by("-iniziato_il").first())
        if aperto is not None:
            if aperto.scade_il is None or aperto.scade_il > adesso:
                return aperto
            _scadi(enr, aperto)
        motivo = blocco(enr, regola, ordini, adesso=adesso)
        if motivo:
            raise QuizNonDisponibile(motivo)
        domande = domande_valide(enr.corso)
        if not domande:
            raise QuizNonDisponibile("Il quiz non è ancora pronto.")
        rnd = random.SystemRandom()
        if regola.domande_estratte and regola.domande_estratte < len(domande):
            domande = rnd.sample(domande, regola.domande_estratte)
        elif regola.mescola:
            rnd.shuffle(domande)
        servite = []
        for d in domande:
            opzioni = [o.pk for o in d.opzioni.all()]
            if regola.mescola and d.tipo != "VERO_FALSO":  # «Vero» resta sempre primo
                rnd.shuffle(opzioni)
            # Le risposte giuste si fotografano ora: se l'autore modifica la domanda
            # mentre il tentativo è aperto, si corregge su ciò che è stato servito.
            servite.append({"id": d.pk, "tipo": d.tipo, "opzioni": opzioni,
                            "corrette": sorted(o.pk for o in d.opzioni.all() if o.corretta)})
        return TrainingQuizAttempt.objects.create(
            corso=enr.corso, enrollment=enr, legacy_anagrafica_id=enr.legacy_anagrafica_id,
            stato="APERTO", iniziato_il=adesso, domande_servite_json=servite,
            scade_il=adesso + timedelta(minutes=regola.tempo_quiz_minuti) if regola.tempo_quiz_minuti else None,
            n_totali=len(servite), utente=user if getattr(user, "is_authenticated", False) else None,
        )


@dataclass
class DomandaServita:
    id: int
    testo: str
    opzioni: list  # [(id, testo)]
    tipo: str = "SINGOLA"

    @property
    def multipla(self) -> bool:
        return self.tipo == "MULTIPLA"


def domande_servite(tentativo) -> list[DomandaServita]:
    from ..models_formazione import TrainingQuizOption, TrainingQuizQuestion

    ids = [d["id"] for d in tentativo.domande_servite_json]
    domande = {d.pk: d for d in TrainingQuizQuestion.objects.filter(pk__in=ids)}
    opzioni = {o.pk: o for o in TrainingQuizOption.objects.filter(domanda_id__in=ids)}
    out = []
    for voce in tentativo.domande_servite_json:
        d = domande.get(voce["id"])
        if d is None:
            continue
        # Il tipo è quello servito: se l'autore lo cambia a tentativo aperto, il
        # discente continua a vedere la domanda com'era.
        out.append(DomandaServita(d.pk, d.testo, [(oid, opzioni[oid].testo) for oid in voce["opzioni"] if oid in opzioni],
                                  voce.get("tipo") or d.tipo))
    return out


def correggi(enr, token: str, risposte: dict[int, set[int]], regola: Regola):
    """Corregge il tentativo aperto ``token`` del discente. Ritorna il tentativo inviato."""
    from ..models_formazione import TrainingElearningEnrollment, TrainingQuizAttempt, TrainingQuizOption

    errore = ""
    with transaction.atomic():
        enr = TrainingElearningEnrollment.objects.select_for_update().get(pk=enr.pk)
        tentativo = (TrainingQuizAttempt.objects.select_for_update()
                     .filter(token=token, enrollment=enr, stato="APERTO").first())
        adesso = timezone.now()
        if tentativo is None:
            errore = "Tentativo non valido o già inviato."
        elif tentativo.scade_il and adesso > tentativo.scade_il:
            # Si registra la scadenza e si esce DOPO il commit: un'eccezione qui
            # dentro annullerebbe anche il passaggio a SCADUTO.
            _scadi(enr, tentativo)
            errore = "Il tempo del quiz è scaduto."
        else:
            return _correggi_aperto(enr, tentativo, risposte, regola, adesso)
    raise QuizNonDisponibile(errore)


def _correggi_aperto(enr, tentativo, risposte, regola, adesso):
    from ..models_formazione import TrainingQuizOption, TrainingQuizQuestion
    testi = dict(TrainingQuizQuestion.objects.filter(
        pk__in=[v["id"] for v in tentativo.domande_servite_json]).values_list("pk", "testo"))
    # Una domanda cancellata dopo il servizio non è stata mostrata: fuori dal totale.
    servite = {v["id"]: set(v["opzioni"]) for v in tentativo.domande_servite_json if v["id"] in testi}
    corrette_db = {v["id"]: set(v["corrette"]) for v in tentativo.domande_servite_json if "corrette" in v}
    mancano = [did for did in servite if did not in corrette_db]
    for o in TrainingQuizOption.objects.filter(domanda_id__in=mancano, corretta=True):
        corrette_db.setdefault(o.domanda_id, set()).add(o.pk)
    n_corrette = 0
    snapshot = []
    for did, ammesse in servite.items():
        scelte = (risposte.get(did) or set()) & ammesse  # id estranei ignorati
        corrette = corrette_db.get(did, set())
        giusta = bool(corrette) and scelte == corrette
        n_corrette += giusta
        snapshot.append({"domanda_id": did, "domanda": testi.get(did, ""), "scelte": sorted(scelte),
                         "corrette": sorted(corrette), "giusta": giusta})
    n_totali = len(servite)
    punteggio = Decimal(str(round(n_corrette / n_totali * 100, 2))) if n_totali else Decimal("0")
    tentativo.n_corrette, tentativo.n_totali = n_corrette, n_totali
    tentativo.punteggio_pct = punteggio
    tentativo.superato = punteggio >= regola.soglia_pct
    tentativo.risposte_json = {"risposte": snapshot}
    tentativo.stato = "INVIATO"
    tentativo.inviato_il = adesso
    tentativo.save()
    enr.n_tentativi = (enr.n_tentativi or 0) + 1
    if enr.best_punteggio_pct is None or punteggio > enr.best_punteggio_pct:
        enr.best_punteggio_pct = punteggio
    campi = ["n_tentativi", "best_punteggio_pct", "updated_at"]
    if not tentativo.superato and enr.stato != "COMPLETATO":
        enr.stato = "NON_SUPERATO"
        campi.append("stato")
    enr.save(update_fields=campi)
    return tentativo
