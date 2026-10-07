"""Alias storico: il motore di requisiti e scadenze e' ``anagrafica.services.requisiti``."""
from anagrafica.services.requisiti import *  # noqa: F401,F403
from anagrafica.services.requisiti import (  # noqa: F401  (nomi privati usati dai chiamanti)
    ORIGINE_FREQUENTATO, ORIGINE_VISITA_REGISTRATA, VoceFormazione, VoceVisita,
)
