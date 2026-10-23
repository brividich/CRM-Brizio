"""Collector OPC UA delle CNC dentro il portale (modalità «Sul server del portale»).

    python manage.py collector_cnc            # gira finché non lo si ferma (attività di Windows all'avvio)
    python manage.py collector_cnc --prova    # dice modalità, macchine da leggere e ultimo segnale, senza leggere

Legge le macchine scritte in Asset › Configurazione › Macchine collegate (fonte «Collector OPC UA»)
e scrive stato, allarmi e contatori direttamente nel database. Il registro dettagliato dei segnali
resta in ``<PRIVATE_ATTACHMENTS_ROOT>/collector_cnc/machines.db``. Ogni minuto lascia un segnale
di vita (pagina Macchine collegate, controllo infrastruttura). Avvio come servizio:
``deployment/start_collector_cnc.ps1``, registrato in Windows da
``deployment/scripts/install-collector-cnc-task.ps1``. Quando si attiva una release nuova
(il junction ``current`` cambia cartella) il comando esce da solo e il launcher lo riavvia
col codice nuovo.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

BATTITO_SECONDI = 60


def cartella_release() -> str:
    """Cartella vera da cui gira il codice: il launcher parte da ``<ambiente>/current/django_app``.

    Il junction ``current`` passa a un'altra cartella quando si attiva una release nuova:
    il percorso vero cambia anche se il processo ha ancora in memoria il codice vecchio.
    """
    return os.path.realpath(os.getcwd())


class ReleaseCambiata(Exception):
    """È stata attivata una release nuova: si esce e il launcher riparte col codice nuovo."""


class Command(BaseCommand):
    help = "Collector OPC UA delle CNC integrato nel portale (sola lettura delle macchine)."

    def add_arguments(self, parser):
        parser.add_argument("--prova", action="store_true", help="Mostra modalità e macchine da leggere, senza leggere.")
        parser.add_argument("--debug", action="store_true")

    def handle(self, *args, **options):
        from assets.services import collector_cnc as svc

        if options["prova"]:
            self.stdout.write(f"Modalità: {svc.MODALITA[svc.modalita()]}")
            macchine = svc.macchine_per(None)
            for m in macchine:
                self.stdout.write(f"  {m['name']}: {m['ip']}:{m['port']} (asset {m['asset_tag']})")
            self.stdout.write(f"Macchine con fonte Collector OPC UA: {len(macchine)}"
                              + ("" if svc.modalita() == "server" else " (lette dal PC dell'officina, non da qui)"))
            b = svc.battito()
            self.stdout.write(f"Ultimo segnale del collector integrato: {b['at'] or 'mai'}{' (vivo)' if b['vivo'] else ''}")
            return
        try:
            from assets.collector_cnc import collector
        except ImportError as exc:
            raise CommandError("Manca la libreria asyncua: pip install -r requirements.txt nel venv del portale.") from exc
        from assets.collector_cnc.diretto import PortaleDiretto

        collector.configura_log(options["debug"])
        cartella = Path(settings.PRIVATE_ATTACHMENTS_ROOT) / "collector_cnc"
        cartella.mkdir(parents=True, exist_ok=True)
        portale = PortaleDiretto(collector.prog_name)
        partenza = cartella_release()

        async def battiti():
            from django.db import close_old_connections

            while True:
                if cartella_release() != partenza:
                    raise ReleaseCambiata

                def scrivi():
                    close_old_connections()
                    svc.registra_battito(len(portale.machines), portale.ultimo_errore or "")

                try:
                    await asyncio.to_thread(scrivi)
                except Exception as exc:  # noqa: BLE001 - il segnale manca: lo vede la pagina, il collector va avanti
                    collector.log.warning("segnale di vita non scritto: %s", exc)
                await asyncio.sleep(BATTITO_SECONDI)

        async def tutto():
            await asyncio.gather(collector.avvia(portale, str(cartella / "machines.db")), battiti())

        self.stdout.write(f"Collector integrato avviato (modalità: {svc.MODALITA[svc.modalita()]}). CTRL+C per fermarlo.")
        try:
            asyncio.run(tutto())
        except ReleaseCambiata:
            self.stdout.write("Attivata una release nuova: il collector esce e il launcher lo riavvia col codice nuovo.")
        except KeyboardInterrupt:
            self.stdout.write("Collector fermato.")
