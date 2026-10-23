"""Il collector dentro il portale: stesse righe di ``Portale`` (stato, contatori), scritte direttamente
nel database invece che inviate via HTTP. Lo usa ``manage.py collector_cnc``.

Legge le macchine solo con la modalità «Sul server del portale» (pagina Macchine collegate); con
«Su un PC dell'officina» l'elenco è vuoto e il servizio resta acceso senza leggere niente.
"""
import asyncio
import logging
import threading

from .portale import URL_CONTATORI, URL_STATO, Portale

log = logging.getLogger("collector.portale")


def _connessione_pulita():
    """Nei thread di lavoro del servizio: via le connessioni scadute (riavvio di SQL Server).
    Nel thread principale no: è quello dei test e del comando --prova."""
    if threading.current_thread() is not threading.main_thread():
        from django.db import close_old_connections

        close_old_connections()


class PortaleDiretto(Portale):
    def __init__(self, prog_name):
        super().__init__("portale://interno", "", [], prog_name)

    def scarica_macchine(self):
        from assets.services.collector_cnc import macchine_per, modalita

        _connessione_pulita()
        try:
            return macchine_per(None) if modalita() == "server" else []
        except Exception as e:  # noqa: BLE001 - database momentaneamente non disponibile: si tiene l'elenco attuale
            self._errore(f"elenco delle macchine non letto dal database ({type(e).__name__}: {e})")
            return None

    @staticmethod
    def scrivi(path, body) -> dict:
        """Quello che via HTTP farebbe l'endpoint, direttamente con l'ORM (in un thread di lavoro)."""
        from assets.services.collector_cnc import applica_letture, applica_stati

        _connessione_pulita()
        if path == URL_STATO:
            return applica_stati(body["macchine"])
        if path == URL_CONTATORI:
            return applica_letture(body["readings"], nota="Collector integrato nel portale")
        return {}

    async def invia(self, path, body):
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
