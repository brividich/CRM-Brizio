"""Copia il database MySQL del GuestPortal nelle tabelle dell'HUB, con gli stessi id.

Di default è una prova: legge, confronta e non scrive. Con ``--apply`` scrive. Si può rilanciare: le
righe già presenti si aggiornano, quindi prima del passaggio si fa una prova e all'ultimo un giro finale.
Stampa solo conteggi, mai dati di persone. Serve SELECT sulle tabelle in ``docs/integrazioni/guestportal/README.md``.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from fornitori import guestportal as gp
from reception.models import (
    Cartellino,
    CategoriaVisita,
    ContattoDitta,
    DittaAccreditata,
    EventoVisita,
    Ospite,
    Preregistrazione,
    Referente,
    Visita,
)


def _ora(valore):
    if valore is None:
        return None
    return timezone.make_aware(valore) if timezone.is_naive(valore) else valore


def _tempo(valore):
    """MySQL TIME arriva da PyMySQL come timedelta."""
    if isinstance(valore, timedelta):
        return (datetime.min + valore).time()
    return valore


def _testo(valore) -> str:
    return "" if valore is None else str(valore).strip()


# Tabella → (modello, query, funzione riga → (pk, campi)). L'ordine rispetta le chiavi esterne.
def _ospite(r):
    return r["GuestID"], {
        "nome": _testo(r["FirstName"])[:100], "cognome": _testo(r["LastName"])[:100],
        "email": _testo(r["Email"]).lower()[:255], "telefono": _testo(r["Phone"])[:50],
        "azienda": _testo(r["Company"])[:255], "informativa_letta_il": _ora(r["ConsentDate"]),
        "informativa_ip": _testo(r["ConsentIP"])[:45], "anonimizzato": bool(r["IsAnonymized"]),
    }


def _referente(r):
    return r["EmployeeID"], {
        "nome": _testo(r["FirstName"])[:100], "cognome": _testo(r["LastName"])[:100], "email": _testo(r["Email"])[:255],
        "reparto": _testo(r["Department"])[:100], "telefono": _testo(r["Phone"])[:50], "attivo": bool(r["IsActive"]),
    }


def _categoria(r):
    return r["CategoryID"], {"nome": _testo(r["Name"])[:100], "icona": _testo(r["IconEmoji"])[:10],
                             "ordine": r["SortOrder"] or 0, "attiva": bool(r["IsActive"])}


def _cartellino(r):
    return r["BadgeID"], {"numero": _testo(r["BadgeNumber"])[:20], "disponibile": bool(r["IsAvailable"]),
                          "ultima_assegnazione": _ora(r["LastAssigned"]), "ultima_restituzione": _ora(r["LastReturnedAt"])}


def _ditta(r):
    return r["SupplierID"], {"nome": _testo(r["CompanyName"])[:200], "note": _testo(r["Notes"])[:500], "attiva": bool(r["IsActive"])}


def _contatto(r):
    return r["ContactID"], {"ditta_id": r["SupplierID"], "nome": _testo(r["FirstName"])[:100],
                            "cognome": _testo(r["LastName"])[:100], "attivo": bool(r["IsActive"])}


def _visita(r):
    return r["VisitID"], {
        "ospite_id": r["GuestID"], "cartellino": _testo(r["BadgeNumber"])[:20] or Visita.SENZA_CARTELLINO,
        "referente_nome": _testo(r["HostEmployee"])[:255], "referente_email": _testo(r["HostEmail"])[:255],
        "motivo": _testo(r["Purpose"])[:500], "ingresso": _ora(r["CheckInTime"]), "uscita": _ora(r["CheckOutTime"]),
        "stato": _testo(r["Status"]) or Visita.USCITO, "tipo": _testo(r["VisitType"]) or Visita.NORMALE,
        "ditta_id": r["SupplierID"], "contatto_id": r["ContactID"], "creata_da": _testo(r["CreatedBy"])[:50],
        # Le mail già partite o da mandare restano al GuestPortal: al passaggio non si rimanda niente.
        "mail_stato": Visita.MAIL_INVIATA, "note": _testo(r["Notes"])[:1000],
    }


def _prereg(r):
    return r["PreRegID"], {
        "codice": _testo(r["Code"])[:8], "ospite_nome": _testo(r["GuestName"])[:200], "ospite_email": _testo(r["GuestEmail"])[:255],
        "ospite_azienda": _testo(r["GuestCompany"])[:200], "referente_nome": _testo(r["HostEmployee"])[:255],
        "referente_email": _testo(r["HostEmail"])[:255], "motivo": _testo(r["Purpose"])[:500], "creata_da": _testo(r["CreatedBy"])[:100],
        "scade_il": _ora(r["ExpiresAt"]), "usata_il": _ora(r["UsedAt"]), "visita_id": r["VisitID"],
        "data_visita": r.get("VisitDate"), "ora_inizio": _tempo(r.get("VisitTimeStart")), "ora_fine": _tempo(r.get("VisitTimeEnd")),
    }


def _evento(r):
    return r["LogID"], {
        "visita_id_rif": r["RecordID"], "azione": _testo(r["Action"])[:50], "autore": _testo(r["PerformedBy"])[:255],
        "ip": _testo(r["IPAddress"])[:45], "dettaglio": _testo(r["Details"]), "quando": _ora(r["PerformedAt"]),
    }


PASSI = [
    ("Ospiti", Ospite, "SELECT * FROM Guests", _ospite),
    ("Referenti", Referente, "SELECT * FROM Employees", _referente),
    ("Motivi", CategoriaVisita, "SELECT * FROM VisitCategories", _categoria),
    ("Cartellini", Cartellino, "SELECT * FROM Badges", _cartellino),
    ("Ditte", DittaAccreditata, "SELECT * FROM Suppliers", _ditta),
    ("Nominativi", ContattoDitta, "SELECT * FROM SupplierContacts", _contatto),
    ("Visite", Visita, "SELECT * FROM Visits", _visita),
    ("Pre-registrazioni", Preregistrazione, "SELECT * FROM PreRegistrations", _prereg),
    ("Correzioni", EventoVisita, "SELECT * FROM AuditLog WHERE TableName = 'Visits' AND RecordID IS NOT NULL", _evento),
]


class Command(BaseCommand):
    help = "Copia il database del GuestPortal nelle tabelle dell'HUB (prova, con --apply scrive)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Scrive davvero. Senza, è una prova.")

    def handle(self, *args, **opzioni):
        if not all(getattr(settings, n, "") for n in ("GUESTPORTAL_DB_HOST", "GUESTPORTAL_DB_USER")):
            raise CommandError("GUESTPORTAL_DB_* non configurato: niente da cui leggere.")
        scrivi = opzioni["apply"]
        self.stdout.write("Scrittura vera." if scrivi else "Prova: non scrivo niente. Con --apply scrivo.")
        # Le righe si leggono prima: una tabella che manca o un permesso assente fermano tutto, senza copie a metà.
        lette = []
        for etichetta, modello, query, converti in PASSI:
            righe = gp._esegui(query, [])
            lette.append((etichetta, modello, [converti(r) for r in righe]))
        with transaction.atomic():
            for etichetta, modello, righe in lette:
                presenti = set(modello.objects.values_list("pk", flat=True))
                nuove = [(pk, c) for pk, c in righe if pk not in presenti]
                gia = [(pk, c) for pk, c in righe if pk in presenti]
                self.stdout.write(json.dumps({"tabella": etichetta, "lette": len(righe), "nuove": len(nuove),
                                              "da_aggiornare": len(gia), "solo_hub": len(presenti - {pk for pk, _ in righe})},
                                             ensure_ascii=False))
                if not scrivi:
                    continue
                # Una riga alla volta: su SQL Server l'id esplicito passa da IDENTITY_INSERT per ogni tabella.
                for pk, campi in nuove:
                    modello(pk=pk, **campi).save(force_insert=True)
                for pk, campi in gia:
                    modello.objects.filter(pk=pk).update(**campi)
        self.stdout.write(self.style.SUCCESS("Finito." if scrivi else "Prova finita, niente scritto."))
