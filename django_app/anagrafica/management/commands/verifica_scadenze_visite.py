"""Check di integrita' delle scadenze delle sole visite mediche. SOLA LETTURA.

Scorciatoia di ``verifica_scadenze_hr --area visite``:

    python manage.py verifica_scadenze_visite [--legacy-id N] [--righe N]
    python manage.py verifica_scadenze_visite --settings=config.settings.prod_readonly
"""
from __future__ import annotations

from .verifica_scadenze_hr import Command as _VerificaHR


class Command(_VerificaHR):
    help = "Verifica (sola lettura) la coerenza delle scadenze delle visite mediche."
    aree_predefinite = ("visite",)
