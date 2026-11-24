"""Scheda semplice di una persona per «Il mio team»: ogni dato con la sua etichetta.

Campi «etichetta: valore», le mansioni con livello e stato e le competenze con il livello
della persona accanto a quello richiesto. Stesse regole del Mansionario
(``mansionario_competenze.scheda_persona``), stesse parole della vista semplice di
«Esplora la struttura» (``esplora_semplice``). Nessun dato sanitario e nessun dato di contratto.
"""
from __future__ import annotations

from django.db.models import Q
from django.utils import timezone

from ..models import AbilitazioneMacchina, DipendenteRuoloOperativo
from . import esplora_semplice as es
from . import mansionario_competenze as mc


def _ruoli(legacy_id: int) -> list[str]:
    oggi = timezone.localdate()
    qs = (DipendenteRuoloOperativo.objects.filter(legacy_anagrafica_id=legacy_id)
          .filter(Q(data_fine__isnull=True) | Q(data_fine__gte=oggi)).select_related("ruolo"))
    return sorted({a.ruolo.nome for a in qs}, key=str.casefold)


def costruisci(riga: dict, *, matricola: str = "") -> dict:
    """``riga`` è la riga della persona in «Il mio team» (id, nome, area, centro)."""
    legacy_id = riga["id"]
    campi = [es._campo("Persona", riga["nome"])]
    if matricola:
        campi.append(es._campo("Matricola", matricola))
    campi.append(es._campo("Reparto", riga.get("area") or riga.get("reparto") or "Nessuno"))
    campi.append(es._campo("Ruolo", ", ".join(_ruoli(legacy_id)) or "Nessuno"))
    campi.append(es._campo("Centro di costo", riga.get("centro") or "Nessuno"))

    mansioni, competenze = [], []
    for r in mc.scheda_persona(legacy_id)["righe"]:
        abil, val = r["abilitazione"], r["valutazione"]
        if abil.stato == AbilitazioneMacchina.STATO_SOSPESA:
            stato, tono = "Sospesa", "neutral"
        else:
            stato, tono = val.esito_label, es._TONI[val.esito]
        mansioni.append({"nome": r["mansione"].nome, "livello": es.livello(abil.livello), "stato": stato, "tono": tono})
        for v in val.voci:
            competenze.append({"nome": v["voce"].nome, "mansione": r["mansione"].nome, "livello": es.livello(v["livello"]),
                               "richiesto": es.livello(v["minimo"]), "sotto": v["sotto"],
                               "manca": v["requisito"]})
    from django.urls import reverse

    from .storico_persona_pdf import sessioni_persona

    sessioni = []
    for s in sessioni_persona(legacy_id)[:20]:
        tutte = list(s.righe.all())
        sessioni.append({"codice": s.codice, "oggetto": s.richiesta.oggetto, "stato": s.get_stato_display(),
                         "tono": {"positiva": "ok", "negativa": "danger", "in_corso": "warning"}.get(s.stato, "info"),
                         "fatte": sum(1 for r in tutte if r.fatta), "totale": len(tutte),
                         "url": reverse("anagrafica:sessione", args=[s.pk])})
    return {"campi": campi, "mansioni": mansioni, "competenze": competenze, "legenda": es.LEGENDA, "sessioni": sessioni,
            "url_storico": reverse("anagrafica:storico_competenze_pdf", args=[legacy_id])}
