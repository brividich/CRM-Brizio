"""Registro dei tecnici di ogni fornitore, salvato nell'HUB.

Il tecnico si registra da solo quando entra dal GuestPortal per una ditta riconosciuta
(task ogni 10 minuti in ``tasks``) o quando un suo ingresso viene collegato a un
intervento; si può anche aggiungere a mano dalla scheda. Una persona già registrata non
viene toccata: chi è stato disattivato a mano resta disattivato anche se rientra.

Il registro non segue la pulizia GDPR del GuestPortal: il nominativo resta finché
qualcuno non lo elimina dalla scheda, o finché non viene eliminato il fornitore.
"""
from __future__ import annotations

from .models import TecnicoFornitore
from .nomi import chiave_tecnico

NOMI_DA_IGNORARE = {"", "—", "ospite anonimizzato"}


def nome_registrabile(nome: str | None) -> bool:
    return (nome or "").strip().lower() not in NOMI_DA_IGNORARE


def registra(fornitore_id: int, nome: str, *, origine: str, utente=None) -> tuple[TecnicoFornitore | None, bool]:
    """Registra la persona sul fornitore se non c'è già. Ritorna ``(tecnico, creato)``."""
    nome = (nome or "").strip()[:200]
    if not fornitore_id or not nome_registrabile(nome):
        return None, False
    return TecnicoFornitore.objects.get_or_create(
        fornitore_id=fornitore_id,
        chiave=chiave_tecnico(nome),
        defaults={
            "nome": nome,
            "origine": origine,
            "creato_da": utente if getattr(utente, "is_authenticated", False) else None,
        },
    )


def registra_da_accessi(accessi) -> int:
    """Registra chi è entrato dal GuestPortal per una ditta già riconosciuta
    (``accesso.fornitore_id``, vedi ``requisiti.abbina_fornitori``). Ritorna i nuovi registrati."""
    nuovi = 0
    for a in accessi:
        fornitore_id = getattr(a, "fornitore_id", None)
        if fornitore_id and registra(fornitore_id, a.nome, origine=TecnicoFornitore.ORIGINE_GUESTPORTAL)[1]:
            nuovi += 1
    return nuovi
