"""Regola di fruizione effettiva di un corso e-learning (FAD), con i default.

Fonte: ``TrainingCompletionRule`` del corso (campi ``el_*``) se esiste, altrimenti
i default delle impostazioni e-learning. Le regole sono configurabili per corso
e confermate dall'RSPP: nessuna regola di legge è scritta nel codice.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

CAMPI_FAD = (
    "el_tempo_minimo_minuti", "el_richiede_tutte_slide", "el_secondi_minimi_slide", "el_inattivita_secondi",
    "el_richiede_quiz", "el_soglia_pct", "el_max_tentativi", "el_attesa_minuti_tra_tentativi",
    "el_domande_estratte", "el_mescola", "el_tempo_quiz_minuti",
)


@dataclass(frozen=True)
class Regola:
    tempo_minimo_minuti: int = 0
    richiede_tutte_slide: bool = True
    secondi_minimi_slide: int = 0
    inattivita_secondi: int = 120
    richiede_quiz: bool = True
    soglia_pct: Decimal = Decimal("70")
    max_tentativi: int = 0          # 0 = illimitati
    attesa_minuti: int = 0
    domande_estratte: int = 0       # 0 = tutte
    mescola: bool = True
    tempo_quiz_minuti: int = 0      # 0 = senza limite
    confermata_rspp: bool = False
    confermata_il: object = None

    def come_dict(self) -> dict:
        return {k: (str(v) if isinstance(v, Decimal) else (v.isoformat() if hasattr(v, "isoformat") else v))
                for k, v in self.__dict__.items()}


def regola_corso(corso) -> Regola:
    from ..models_formazione import ElearningConfig, TrainingCompletionRule

    cfg = ElearningConfig.get_instance()
    soglia = Decimal(str(corso.quiz_punteggio_minimo or cfg.quiz_punteggio_minimo_default or 70))
    r = TrainingCompletionRule.objects.filter(corso=corso).first()
    if r is None:
        return Regola(soglia_pct=soglia, max_tentativi=int(cfg.max_tentativi_quiz or 0))
    return Regola(
        tempo_minimo_minuti=r.el_tempo_minimo_minuti,
        richiede_tutte_slide=r.el_richiede_tutte_slide,
        secondi_minimi_slide=r.el_secondi_minimi_slide,
        inattivita_secondi=r.el_inattivita_secondi or 120,
        richiede_quiz=r.el_richiede_quiz,
        soglia_pct=Decimal(str(r.el_soglia_pct)) if r.el_soglia_pct is not None else soglia,
        max_tentativi=int(r.el_max_tentativi or cfg.max_tentativi_quiz or 0),
        attesa_minuti=r.el_attesa_minuti_tra_tentativi,
        domande_estratte=r.el_domande_estratte,
        mescola=r.el_mescola,
        tempo_quiz_minuti=r.el_tempo_quiz_minuti,
        confermata_rspp=bool(r.confermata_rspp_il),
        confermata_il=r.confermata_rspp_il,
    )


def secondi_richiesti_slide(slide, regola: Regola) -> int:
    return max(int(slide.durata_minima_secondi or 0), int(regola.secondi_minimi_slide or 0))


def puo_confermare_fad(user) -> bool:
    """Chi può confermare le regole FAD (RSPP): superuser o utenti indicati nelle impostazioni."""
    if getattr(user, "is_superuser", False):
        return True
    from core.legacy_utils import get_legacy_user
    from ..models_formazione import ElearningConfig
    legacy = get_legacy_user(user)
    ids = {int(i) for i in (ElearningConfig.get_instance().conferma_fad_utente_ids or []) if str(i).isdigit()}
    return bool(legacy and legacy.id in ids)
