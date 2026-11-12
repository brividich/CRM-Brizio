"""Uscite non timbrate: giornate con timbrature da sistemare.

Si controllano tutte le timbrature del giorno (``solari.analizza_giornata``): uscita
mancante, uscita timbrata col verso sbagliato, due entrate o due uscite di fila. I turni
a cavallo della mezzanotte non sono segnalati.

Per ogni giornata trovata il capo della persona (``anagrafica.services.capo_team``,
la stessa regola del flusso assenze) riceve una notifica in-app e una mail: deve
far regolarizzare la timbratura o inserire l'assenza. Ogni giornata si segnala
una volta sola (``AvvisoUscitaMancante``).
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from django.urls import reverse
from django.utils import timezone

from . import impostazioni, services, solari

logger = logging.getLogger(__name__)

GIORNI_INDIETRO = 3  # il lunedì copre anche venerdì e sabato


def elenco(dal: date, al: date) -> list[dict]:
    """Righe ``solari.leggi_uscite_mancanti`` agganciate all'anagrafica del portale."""
    righe = solari.leggi_uscite_mancanti(dal, al)
    for r in righe:
        r["entrata"] = r["entrata"].strftime("%H:%M")
    return services.collega_anagrafica(righe)


def _utente_e_email(legacy_anagrafica_id: int) -> tuple[int | None, str]:
    from core.legacy_models import AnagraficaDipendente

    d = AnagraficaDipendente.objects.filter(id=legacy_anagrafica_id).values("utente_id", "email_notifica").first()
    if not d:
        return None, ""
    return d["utente_id"], (d["email_notifica"] or "").strip()


def invia_avvisi(oggi: date | None = None) -> dict:
    """Avvisa i capi delle uscite non timbrate degli ultimi giorni. Ritorna i contatori.

    Un solo messaggio per capo con tutte le giornate nuove della sua squadra. Solo le
    **uscite mancanti**: verso sbagliato e sequenze irregolari (problemi di timbratura)
    restano nella pagina, senza notifica né mail.
    """
    from anagrafica.services.capo_team import mappa_capi
    from core.email_utils import send_hub_mail
    from core.notifiche import invia_notifica

    from .models import AvvisoUscitaMancante

    esito = {"trovate": 0, "capi_avvisati": 0, "gia_segnalate": 0, "senza_capo": 0, "solo_pagina": 0}
    if not impostazioni.attivo("presenti_avviso_uscite_attivo"):
        esito["disattivato"] = True
        return esito
    oggi = oggi or timezone.localdate()
    righe = elenco(oggi - timedelta(days=GIORNI_INDIETRO), oggi - timedelta(days=1))
    esito["trovate"] = len(righe)
    gia = set(AvvisoUscitaMancante.objects.filter(
        giorno__gte=oggi - timedelta(days=GIORNI_INDIETRO)).values_list("solari_id", "giorno"))
    capi = mappa_capi()
    per_capo: dict[int, list[dict]] = {}
    for r in righe:
        if r.get("tipo", "uscita_mancante") != "uscita_mancante":
            esito["solo_pagina"] += 1
            continue
        if (r["solari_id"], r["giorno"]) in gia:
            esito["gia_segnalate"] += 1
            continue
        capo = capi.get(r["legacy_id"]) if r.get("legacy_id") else None
        capo_id = getattr(capo, "legacy_id", None)
        if capo_id:
            per_capo.setdefault(int(capo_id), []).append(r)
            continue
        esito["senza_capo"] += 1
        AvvisoUscitaMancante.objects.get_or_create(
            solari_id=r["solari_id"], giorno=r["giorno"],
            defaults={"legacy_anagrafica_id": r.get("legacy_id"),
                      "esito": "capo non trovato in organigramma" if r.get("legacy_id")
                      else "persona non collegata all'anagrafica"},
        )

    url = reverse("presenti:uscite")
    for capo_id, voci in per_capo.items():
        utente_id, email = _utente_e_email(capo_id)
        elenco_txt = "\n".join(
            f"- {v['cognome']} {v['nome']}, {v['giorno']:%d/%m/%Y}: {v.get('problema') or 'manca uscita'}\n"
            f"  timbrature del giorno: {v.get('timbrature') or 'E ' + v['entrata']}"
            for v in voci)
        breve = (f"Uscita non timbrata: {voci[0]['cognome']} {voci[0]['nome']} il {voci[0]['giorno']:%d/%m/%Y}"
                 if len(voci) == 1 else f"{len(voci)} uscite non timbrate nella tua squadra")
        invia_notifica(legacy_user_id=utente_id, tipo="generico",
                       messaggio=f"{breve}. Fai regolarizzare la timbratura o inserire l'assenza.", url_azione=url)
        nota = "notifica" if utente_id else ""
        if email:
            try:
                send_hub_mail(
                    f"[NOVICROM HUB] {breve}",
                    "Queste giornate risultano chiuse con un'entrata e senza uscita:\n\n"
                    f"{elenco_txt}\n\nFai regolarizzare la timbratura o inserire l'assenza. "
                    "L'elenco completo è in NOVICROM HUB, Persone › Presenti in azienda › Uscite non timbrate.",
                    [email], title="Uscite non timbrate", email_type="Presenze", section_label="Presenti in azienda",
                )
                nota = (nota + " + mail").strip(" +")
            except Exception:
                logger.exception("Mail uscite non timbrate non inviata al capo %s", capo_id)
                nota = (nota + " · mail non inviata").strip(" ·")
        esito["capi_avvisati"] += 1
        for v in voci:
            AvvisoUscitaMancante.objects.get_or_create(
                solari_id=v["solari_id"], giorno=v["giorno"],
                defaults={"legacy_anagrafica_id": v.get("legacy_id"), "capo_legacy_anagrafica_id": capo_id,
                          "esito": nota or "capo senza utente né email"},
            )
    return esito
