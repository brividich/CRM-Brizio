"""Organigramma ufficiale in firma (MT CN 08 §7.2.1): Redazione di chi invia, Approvazione di RDD.

La revisione nasce solo dopo l'ultima firma, dalla copia congelata della bozza
inviata in firma. Finché il documento è in firma la bozza non si modifica.
"""
from __future__ import annotations

from datetime import date

from timbri import firme

CHIAVE = "organigramma_ufficiale"

CASELLE_DI_SERIE = [
    {"etichetta": "Redazione", "mittente": True, "varianti": ["FIRMA", "SIGLA"]},
    {"etichetta": "Approvazione", "ruolo_sigla": "RDD", "varianti": ["FIRMA", "TIMBRO"]},
]


def _al_firmato(doc, user) -> None:
    from anagrafica.models import OrganigrammaUfficiale

    from . import organigramma_ufficiale as svc

    org = OrganigrammaUfficiale.objects.get(pk=doc.oggetto_id)
    c = doc.contenuto or {}
    try:
        emissione = date.fromisoformat(c.get("data_emissione") or "")
    except ValueError:
        emissione = date.today()
    ultima = [x for x in doc.caselle.all() if x.stato == x.STATO_FIRMATA][-1]
    approvato = ultima.nome_firmatario + (f" ({ultima.ruolo.sigla})" if ultima.ruolo_id and ultima.ruolo.sigla else "")
    rev = svc.pubblica(org, nota=c.get("nota") or doc.nota, approvato_da=approvato, data_emissione=emissione,
                       user=user, dati=c.get("dati"))
    doc.esito_id = rev.pk
    doc.save(update_fields=["esito_id"])


firme.registra_tipo(CHIAVE, firme.TipoDocumento(
    nome="Organigramma ufficiale", caselle_di_serie=CASELLE_DI_SERIE, al_firmato=_al_firmato,
))


def contenuto(org, *, nota: str, data_emissione: date) -> dict:
    from . import organigramma_ufficiale as svc

    return {"dati": svc.normalizza(org.bozza), "nota": nota, "data_emissione": data_emissione.isoformat(),
            "nome": org.nome}
