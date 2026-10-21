from __future__ import annotations

import shutil

from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction

from anomalie.automation_models import AnomalieAutomazioneMarker
from anomalie.mail_action_models import AnomaliaActionLog, AnomaliaMailActionToken, AnomaliaPendingNotification
from anomalie.mail_log_models import AnomalieEmailLog
from anomalie.quality_models import (
    AnomaliaBlocco,
    AnomaliaControllo,
    AnomaliaDescrizione,
    AnomaliaDescrizioneAllegato,
    AnomaliaNC,
    AnomaliaNCAllegato,
    AnomaliaNCAzione,
    AnomaliaNCEvento,
    AnomaliaSchedaQualita,
    AnomaliaSegnalazioneMeta,
)
from anomalie.views import _anomalie_attachments_root, _fetch_all_dict, _has_table
from core.audit import log_action

# Ordine di cancellazione: prima i figli, poi i padri (le FK CASCADE/SET_NULL le
# gestisce comunque Django, l'ordine serve solo a rendere leggibili i conteggi).
MODELLI_DATI = [
    ("Allegati NC", AnomaliaNCAllegato),
    ("Eventi NC", AnomaliaNCEvento),
    ("Azioni NC", AnomaliaNCAzione),
    ("Allegati descrizioni", AnomaliaDescrizioneAllegato),
    ("Descrizioni", AnomaliaDescrizione),
    ("Segnalazioni (meta)", AnomaliaSegnalazioneMeta),
    ("Schede qualità", AnomaliaSchedaQualita),
    ("Blocchi controllo", AnomaliaBlocco),
    ("Controlli", AnomaliaControllo),
    ("Non conformità", AnomaliaNC),
    ("Registro azioni", AnomaliaActionLog),
    ("Token azioni via mail", AnomaliaMailActionToken),
    ("Notifiche in coda", AnomaliaPendingNotification),
    ("Registro email", AnomalieEmailLog),
    ("Marcatori automazioni", AnomalieAutomazioneMarker),
]

# Tabelle legacy (non gestite da Django): anomalie prima, poi gli OP.
TABELLE_LEGACY = ["anomalie", "ordini_produzione"]


class Command(BaseCommand):
    help = (
        "Svuota TUTTI i dati operativi di Gestione anomalie (anomalie, OP, NC, controlli, schede qualità, "
        "log mail/azioni, allegati). Le tabelle di configurazione (tipi difetto, ruoli, regole di accesso, "
        "impostazioni) restano intatte. Default: solo conteggio; usa --esegui per cancellare."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--esegui",
            action="store_true",
            help="Cancella realmente (default: prova a secco con i soli conteggi).",
        )
        parser.add_argument(
            "--mantieni-op",
            action="store_true",
            help="Non svuotare la tabella ordini_produzione (OP).",
        )

    def handle(self, *args, **options):
        esegui = bool(options.get("esegui"))
        tabelle = [t for t in TABELLE_LEGACY if not (options.get("mantieni_op") and t == "ordini_produzione")]
        tabelle = [t for t in tabelle if _has_table(t)]
        if "anomalie" not in tabelle:
            raise CommandError("Tabella anomalie non disponibile.")

        conteggi: dict[str, int] = {}
        for etichetta, modello in MODELLI_DATI:
            conteggi[etichetta] = modello.objects.count()
        for tabella in tabelle:
            conteggi[f"Tabella {tabella}"] = int(
                (_fetch_all_dict(f"SELECT COUNT(*) AS n FROM {self._q(tabella)}") or [{"n": 0}])[0]["n"]
            )

        root = _anomalie_attachments_root()
        cartelle = self._cartelle_allegati(root)
        conteggi["Cartelle allegati"] = len(cartelle)

        self.stdout.write(f"Cartella allegati: {root}")
        for etichetta, n in conteggi.items():
            self.stdout.write(f"  {etichetta}: {n}")

        if not esegui:
            self.stdout.write(self.style.WARNING("Prova a secco: nulla è stato cancellato (usa --esegui)."))
            return

        with transaction.atomic():
            for _etichetta, modello in MODELLI_DATI:
                modello.objects.all().delete()
            with connections["default"].cursor() as cursor:
                for tabella in tabelle:
                    cursor.execute(f"DELETE FROM {self._q(tabella)}")

        falliti = 0
        for path in cartelle:
            try:
                shutil.rmtree(path)
            except OSError as exc:
                falliti += 1
                self.stderr.write(f"Errore eliminazione {path}: {exc}")

        log_action(None, "svuota_anomalie", "anomalie", {"conteggi": conteggi, "cartelle_fallite": falliti})

        if falliti:
            raise CommandError(f"Dati cancellati, ma {falliti} cartelle allegati non sono state eliminate.")
        self.stdout.write(self.style.SUCCESS("Gestione anomalie svuotata."))

    @staticmethod
    def _q(nome: str) -> str:
        return connections["default"].ops.quote_name(nome)

    @staticmethod
    def _cartelle_allegati(root):
        """Solo le cartelle per anomalia (<id>/) e per NC (nc/<id>/): nient'altro nella root."""
        if not root.is_dir():
            return []
        cartelle = [p for p in root.iterdir() if p.is_dir() and p.name.isdigit()]
        nc_root = root / "nc"
        if nc_root.is_dir():
            cartelle += [p for p in nc_root.iterdir() if p.is_dir() and p.name.isdigit()]
        return sorted(cartelle)
