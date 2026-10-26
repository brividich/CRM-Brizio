"""Task django-q del Registro accessi (schedule in ``automazioni/schedules.py``)."""
from __future__ import annotations


def run_ciclo() -> dict:
    """``registro_log_ciclo`` (5 minuti): raccoglitore vivo, fonti mute, sigilli, copie, invio al SOC."""
    from registro_log import ciclo

    return ciclo.esegui()


def run_ad_sync() -> dict:
    """``registro_log_ad`` (ogni 6 ore): passa dal registro delle letture del SOC (storico ed «Esegui ora»)."""
    from security.services import letture

    return letture.esegui("registro_ad")


def run_infra() -> dict:
    """``registro_log_infra`` (ogni ora): stato di ESXi/vCenter e iLO/iDRAC."""
    from security.services import letture

    return letture.esegui("registro_infra")
