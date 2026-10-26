"""Raccoglitore del Registro accessi (processo sempre acceso, come il qcluster).

    python manage.py registro_log            # gira finché non lo si ferma
    python manage.py registro_log --prova    # stato, fonti e prova di lettura, senza archiviare
    python manage.py registro_log --ciclo    # un giro del controllo (sigilli, interruzioni, SOC) e basta

Avvio come servizio: ``deployment/start_registro_log.ps1``, registrato in Windows da
``deployment/scripts/install-registro-log-task.ps1`` (stesso account del qcluster). Quando si
attiva una release nuova il comando esce da solo e il launcher lo riavvia col codice nuovo.
"""
from __future__ import annotations

import os
import signal

from django.core.management.base import BaseCommand


def cartella_release() -> str:
    return os.path.realpath(os.getcwd())


class Command(BaseCommand):
    help = "Raccoglitore del Registro accessi: log di Windows e syslog in un archivio sigillato."

    def add_arguments(self, parser):
        parser.add_argument("--prova", action="store_true", help="Stato e prova delle fonti Windows, senza archiviare.")
        parser.add_argument("--ciclo", action="store_true", help="Esegue una volta il ciclo di controllo e esce.")

    def handle(self, *args, **options):
        from registro_log import archivio, ciclo
        from registro_log.models import FonteLog, Impostazioni
        from registro_log.sorgenti import windows

        if options["ciclo"]:
            self.stdout.write(str(ciclo.esegui()))
            return
        imp = Impostazioni.corrente()
        if options["prova"]:
            self.stdout.write(f"Registro accessi {'ACCESO' if imp.attivo else 'SPENTO'} · archivio: {archivio.cartella()}")
            b = ciclo.battito()
            self.stdout.write(f"Ultimo segnale del raccoglitore: {b['at'] or 'mai'}{' (vivo)' if b['vivo'] else ''}")
            for f in FonteLog.objects.filter(attiva=True):
                self.stdout.write(f"- {f.nome} ({f.get_tipo_display()})")
                if f.tipo == FonteLog.TIPO_WINDOWS:
                    for riga in windows.prova(f.host, f.lista_canali()):
                        self.stdout.write(f"    {riga}")
                elif f.tipo == FonteLog.TIPO_WEF:
                    for riga in windows.prova("", ["ForwardedEvents"]):
                        self.stdout.write(f"    {riga}")
                else:
                    self.stdout.write(f"    indirizzi ammessi: {', '.join(f.lista_ip()) or 'nessuno'}")
            return

        from registro_log.raccoglitore import Raccoglitore

        r = Raccoglitore()
        partenza = cartella_release()
        uscita = {"release": False}

        def controlla():
            if cartella_release() != partenza:
                uscita["release"] = True
                return True
            return False

        def fermati(*_):
            r.ferma()

        signal.signal(signal.SIGINT, fermati)
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, fermati)
        self.stdout.write(f"Raccoglitore avviato (archivio: {archivio.cartella()}). CTRL+C per fermarlo.")
        r.esegui(controlla_uscita=controlla)
        if uscita["release"]:
            self.stdout.write("Attivata una release nuova: il raccoglitore esce e il launcher lo riavvia col codice nuovo.")
        else:
            self.stdout.write("Raccoglitore fermato.")
