"""Il collector dentro il portale: stesse righe di ``Portale`` (stato, contatori), scritte direttamente
nel database invece che inviate via HTTP. Lo usa ``manage.py collector_cnc``.

Legge le macchine solo con la modalità «Sul server del portale» (pagina Macchine collegate); con
«Su un PC dell'officina» l'elenco è vuoto e il servizio resta acceso senza leggere niente.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from collections.abc import Callable
from typing import Any

from .portale import URL_CONTATORI, URL_STATO, Portale

log = logging.getLogger("collector.portale")


def _connessione_pulita() -> None:
    """Nei thread di lavoro del servizio: via le connessioni scadute (riavvio di SQL Server).
    Nel thread principale no: è quello dei test e del comando --prova."""
    if threading.current_thread() is not threading.main_thread():
        from django.db import close_old_connections

        close_old_connections()


class PortaleDiretto(Portale):
    def __init__(self, prog_name: Callable[[Any], str]) -> None:
        super().__init__("portale://interno", "", [], prog_name)

    def scarica_macchine(self) -> list[dict[str, Any]] | None:
        from assets.services.collector_cnc import macchine_per, modalita

        _connessione_pulita()
        try:
            elenco: list[dict[str, Any]] = macchine_per(None) if modalita() == "server" else []
            return elenco
        except Exception as e:  # noqa: BLE001 - database momentaneamente non disponibile: si tiene l'elenco attuale
            self._errore(f"elenco delle macchine non letto dal database ({type(e).__name__}: {e})")
            return None

    @staticmethod
    def scrivi(path: str, body: dict[str, Any]) -> dict[str, Any]:
        """Quello che via HTTP farebbe l'endpoint, direttamente con l'ORM (in un thread di lavoro)."""
        from assets.services.collector_cnc import applica_letture, applica_stati

        _connessione_pulita()
        if path == URL_STATO:
            esito: dict[str, Any] = applica_stati(body["macchine"])
            return esito
        if path == URL_CONTATORI:
            letture: dict[str, Any] = applica_letture(body["readings"], nota="Collector integrato nel portale")
            return letture
        return {}

    async def invia(self, path: str, body: dict[str, Any]) -> bool:
        try:
            esito = await asyncio.to_thread(self.scrivi, path, body)
        except Exception as e:  # noqa: BLE001 - database momentaneamente non disponibile: si riprova
            self._errore(f"scrittura nel database non riuscita ({type(e).__name__}: {e})")
            return False
        if self.ultimo_errore:
            log.info("database di nuovo raggiungibile")
            self.ultimo_errore = None
        for r in esito.get("results", []):
            if r.get("status") == "rejected":
                log.warning("portale: %s scartata (%s)", r.get("asset_tag"), r.get("reason"))
        return True
