"""Questionario di gradimento a fine corso e legame con la valutazione di efficacia.

Due misure diverse, lette insieme nel cruscotto:

- **gradimento** (reazione del discente subito dopo il corso): domande da 1 a 5
  configurate in Impostazioni e-learning, più un commento libero; facoltativo,
  uno per completamento;
- **efficacia** (``TrainingEfficacia``, verifica sul campo del preposto a
  distanza di mesi): aperta al completamento se il corso la prevede.

Nel cruscotto si vedono solo medie e commenti senza nome.
"""
from __future__ import annotations

from decimal import Decimal

from django.db import IntegrityError, transaction

MAX_DOMANDE = 10
MAX_COMMENTO = 1000


class GradimentoNonValido(Exception):
    pass


def domande(cfg=None) -> list[str]:
    from ..models_formazione import ElearningConfig

    cfg = cfg or ElearningConfig.get_instance()
    righe = [r.strip() for r in (cfg.gradimento_domande or "").splitlines() if r.strip()]
    return [r[:300] for r in righe[:MAX_DOMANDE]]


def record_da_valutare(corso, legacy_id: int):
    """Il completamento più recente del discente su quel corso ancora senza gradimento."""
    from ..models_formazione import ElearningConfig, TrainingElearningEnrollment

    cfg = ElearningConfig.get_instance()
    if not cfg.gradimento_attivo or not domande(cfg) or not legacy_id:
        return None
    enr = (TrainingElearningEnrollment.objects
           .filter(corso=corso, legacy_anagrafica_id=legacy_id, stato="COMPLETATO",
                   record_completamento__isnull=False)
           .select_related("record_completamento").order_by("-ciclo").first())
    if enr is None:
        return None
    from ..models_elearning import TrainingElearningGradimento

    record = enr.record_completamento
    if TrainingElearningGradimento.objects.filter(record=record).exists():
        return None
    return record


def salva(record, voti: list, commento: str = ""):
    """Registra il gradimento (una volta sola per completamento)."""
    from ..models_elearning import TrainingElearningGradimento

    elenco = domande()
    try:
        voti = [int(v) for v in voti]
    except (TypeError, ValueError):
        raise GradimentoNonValido("Rispondi a tutte le domande con un voto da 1 a 5.")
    if len(voti) != len(elenco) or any(v < 1 or v > 5 for v in voti):
        raise GradimentoNonValido("Rispondi a tutte le domande con un voto da 1 a 5.")
    media = Decimal(sum(voti)) / Decimal(len(voti))
    try:
        with transaction.atomic():
            return TrainingElearningGradimento.objects.create(
                record=record, corso_id=record.corso_id, legacy_anagrafica_id=record.legacy_anagrafica_id,
                domande_json=elenco, voti_json=voti, media=media.quantize(Decimal("0.01")),
                commento=(commento or "").strip()[:MAX_COMMENTO],
            )
    except IntegrityError:
        raise GradimentoNonValido("Hai già lasciato il tuo giudizio su questo corso.")


def per_corso(corso_ids=None) -> dict[int, dict]:
    """corso_id → {"media": Decimal, "n": int}."""
    from django.db.models import Avg, Count

    from ..models_elearning import TrainingElearningGradimento

    qs = TrainingElearningGradimento.objects.all()
    if corso_ids is not None:
        qs = qs.filter(corso_id__in=list(corso_ids))
    return {r["corso_id"]: {"media": round(r["m"], 1), "n": r["n"]}
            for r in qs.values("corso_id").annotate(m=Avg("media"), n=Count("id")).order_by()}


def commenti_recenti(limite: int = 10, corso_id: int | None = None) -> list[dict]:
    """Ultimi commenti, **senza nome**: corso, data, media."""
    from ..models_elearning import TrainingElearningGradimento

    qs = TrainingElearningGradimento.objects.exclude(commento="").select_related("corso")
    if corso_id:
        qs = qs.filter(corso_id=corso_id)
    return [{"corso": g.corso.titolo, "data": g.creato_il, "media": g.media, "commento": g.commento}
            for g in qs.order_by("-creato_il")[:limite]]


def efficacia_per_corso(corso_ids=None) -> dict[int, dict]:
    """corso_id → valutazioni di efficacia aperte dai completamenti: attese, compilate, efficaci."""
    from ..models_formazione import TrainingEfficacia

    qs = TrainingEfficacia.objects.all()
    if corso_ids is not None:
        qs = qs.filter(record__corso_id__in=list(corso_ids))
    out: dict[int, dict] = {}
    for corso_id, valutata, esito in qs.values_list("record__corso_id", "valutata_il", "esito"):
        voce = out.setdefault(corso_id, {"aperte": 0, "compilate": 0, "efficaci": 0})
        voce["aperte"] += 1
        if valutata:
            voce["compilate"] += 1
            voce["efficaci"] += esito == "EFFICACE"
    for voce in out.values():
        voce["pct_efficaci"] = round(voce["efficaci"] * 100 / voce["compilate"]) if voce["compilate"] else None
    return out
