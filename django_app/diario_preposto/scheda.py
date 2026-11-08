"""Infografica della singola segnalazione: percorso, controlli, contesto.

Parte dalla storyline (``storyline.costruisci_storyline``) per non contare due
volte gli stessi fatti:
- ``percorso``: le tappe Fatto → Registrata → Documentata → Notificata → Oggi
  (o Eliminata), con i giorni trascorsi dal fatto e lo stato di ogni tappa;
- ``controlli``: verifiche sì/no sulla tenuta del record (tempi, allegati,
  impronte, download, notifiche, dati, presenza nel registro);
- ``contesto_preposto``: le altre segnalazioni dello stesso preposto, sul
  queryset che l'utente può vedere (ruoli già applicati dalla vista).
"""
from __future__ import annotations

from datetime import date

from django.utils import timezone

from .cruscotto import GIORNI_RITARDO_REGISTRAZIONE, MESI_ANDAMENTO, MESI_BREVI, _barre, _primo_del_mese

# Stati: ok | avviso | critico | assente (tappa non raggiunta / controllo non applicabile)


def _locale(dt):
    return timezone.localtime(dt) if dt and timezone.is_aware(dt) else dt


def _giorno(dt) -> date | None:
    dt = _locale(dt)
    return dt.date() if dt else None


def _dopo(giorni: int | None) -> str:
    if giorni is None:
        return ""
    if giorni <= 0:
        return "stesso giorno"
    return f"dopo {giorni} giorn{'o' if giorni == 1 else 'i'}"


def percorso(segnalazione, storyline: dict, *, oggi: date | None = None) -> list[dict]:
    oggi = oggi or timezone.localdate()
    eventi = storyline["eventi"]
    r = storyline["riepilogo"]
    g_fatto = _giorno(segnalazione.data_segnalazione)

    def giorni(dt):
        g = _giorno(dt)
        return (g - g_fatto).days if g and g_fatto else None

    tappe = [{
        "chiave": "fatto", "titolo": "Fatto", "quando": segnalazione.data_segnalazione,
        "stato": "ok", "nota": segnalazione.preposto or segnalazione.chi_segnala or "", "dopo": "giorno 0",
    }]

    tappe.append({
        "chiave": "registrata", "titolo": "Registrata", "quando": segnalazione.created_at,
        "stato": "avviso" if r["ritardo_avviso"] else "ok",
        "nota": f"oltre i {GIORNI_RITARDO_REGISTRAZIONE} giorni" if r["ritardo_avviso"] else "nei tempi",
        "dopo": _dopo(giorni(segnalazione.created_at)),
    })

    primo_allegato = next((e for e in eventi if e.tipo == "allegato"), None)
    if r["allegati"] and primo_allegato:
        tappe.append({
            "chiave": "documentata", "titolo": "Documentata", "quando": primo_allegato.quando, "stato": "ok",
            "nota": f"{r['allegati']} allegat{'o' if r['allegati'] == 1 else 'i'}",
            "dopo": _dopo(giorni(primo_allegato.quando)),
        })
    else:
        tappe.append({
            "chiave": "documentata", "titolo": "Documentata", "quando": None, "stato": "avviso",
            "nota": "allegati tutti rimossi" if r["allegati_rimossi"] else "nessun allegato", "dopo": "",
        })

    mail_ok = next((e for e in eventi if e.tipo == "mail" and e.stato != "critico"), None)
    if r["mail_ko"]:
        tappe.append({
            "chiave": "notificata", "titolo": "Notificata", "quando": mail_ok.quando if mail_ok else None,
            "stato": "critico",
            "nota": f"{r['mail_ko']} notific{'a' if r['mail_ko'] == 1 else 'he'} non partit{'a' if r['mail_ko'] == 1 else 'e'}",
            "dopo": _dopo(giorni(mail_ok.quando)) if mail_ok else "",
        })
    elif mail_ok:
        tappe.append({
            "chiave": "notificata", "titolo": "Notificata", "quando": mail_ok.quando, "stato": "ok",
            "nota": f"{r['mail_ok']} mail inviat{'a' if r['mail_ok'] == 1 else 'e'}",
            "dopo": _dopo(giorni(mail_ok.quando)),
        })
    else:
        tappe.append({
            "chiave": "notificata", "titolo": "Notificata", "quando": None, "stato": "assente",
            "nota": "nessuna mail registrata", "dopo": "",
        })

    if segnalazione.is_eliminata:
        tappe.append({
            "chiave": "eliminata", "titolo": "Eliminata", "quando": segnalazione.eliminata_il, "stato": "critico",
            "nota": segnalazione.motivo_eliminazione or "", "dopo": _dopo(giorni(segnalazione.eliminata_il)),
        })
    else:
        g = (oggi - g_fatto).days if g_fatto else None
        tappe.append({
            "chiave": "oggi", "titolo": "Oggi", "quando": None, "stato": "ok",
            "nota": f"{r['modifiche']} modific{'a' if r['modifiche'] == 1 else 'he'}",
            "dopo": "" if g is None else f"{g} giorn{'o' if g == 1 else 'i'} dal fatto",
        })
    return tappe


def controlli(segnalazione, storyline: dict) -> dict:
    eventi = storyline["eventi"]
    r = storyline["riepilogo"]
    voci = []

    def voce(titolo, stato, dettaglio):
        voci.append({"titolo": titolo, "stato": stato, "dettaglio": dettaglio})

    if r["ritardo_giorni"] is None:
        voce("Registrata in tempo", "assente", "data del fatto mancante")
    elif r["ritardo_avviso"]:
        voce("Registrata in tempo", "avviso",
             f"inserita {r['ritardo_giorni']} giorni dopo il fatto (soglia {GIORNI_RITARDO_REGISTRAZIONE})")
    else:
        voce("Registrata in tempo", "ok", f"entro {GIORNI_RITARDO_REGISTRAZIONE} giorni dal fatto")

    if r["allegati"]:
        voce("Documentata con allegati", "ok", f"{r['allegati']} allegat{'o' if r['allegati'] == 1 else 'i'}")
    else:
        voce("Documentata con allegati", "avviso", "nessuna foto o documento")

    if not r["allegati"]:
        voce("Impronta degli allegati", "assente", "nessun allegato da proteggere")
    elif r["allegati_senza_impronta"]:
        voce("Impronta degli allegati", "avviso",
             f"{r['allegati_senza_impronta']} senza impronta (caricati prima dell'08/11/2026)")
    else:
        voce("Impronta degli allegati", "ok", "tutti con impronta SHA-256")

    download = [e for e in eventi if e.tipo == "download"]
    bloccati = sum(1 for e in download if e.stato == "critico")
    if bloccati:
        voce("Allegati integri", "critico", f"{bloccati} download bloccat{'o' if bloccati == 1 else 'i'}: file alterato")
    elif download:
        voce("Allegati integri", "ok", f"verificati a ogni download ({len(download)})")
    else:
        voce("Allegati integri", "assente", "non ancora scaricati: verifica al primo download")

    if r["mail_ko"]:
        voce("Notifiche partite", "critico", f"{r['mail_ko']} non partit{'a' if r['mail_ko'] == 1 else 'e'}")
    elif r["mail_ok"]:
        voce("Notifiche partite", "ok", f"{r['mail_ok']} inviat{'a' if r['mail_ok'] == 1 else 'e'}")
    else:
        voce("Notifiche partite", "assente", "nessuna mail registrata per la segnalazione")

    mancanti = [nome for nome, valore in (
        ("preposto", segnalazione.preposto), ("chi segnala", segnalazione.chi_segnala),
        ("descrizione", (segnalazione.descrizione or "").strip()),
    ) if not valore]
    if mancanti:
        voce("Dati completi", "avviso", "manca " + ", ".join(mancanti))
    else:
        voce("Dati completi", "ok", "preposto, chi segnala e descrizione presenti")

    if segnalazione.is_eliminata:
        voce("Nel registro", "critico", "eliminata: fuori dall'elenco")
    else:
        voce("Nel registro", "ok", "visibile nell'elenco")

    valutati = [v for v in voci if v["stato"] != "assente"]
    return {
        "voci": voci,
        "superati": sum(1 for v in valutati if v["stato"] == "ok"),
        "valutati": len(valutati),
        "critici": sum(1 for v in voci if v["stato"] == "critico"),
        "avvisi": sum(1 for v in voci if v["stato"] == "avviso"),
    }


def contesto_preposto(qs_visibili, segnalazione, *, oggi: date | None = None) -> dict | None:
    """Le segnalazioni dello stesso preposto che l'utente può vedere."""
    if not segnalazione.preposto:
        return None
    oggi = oggi or timezone.localdate()
    stesse = qs_visibili.filter(preposto=segnalazione.preposto)
    righe = list(stesse.order_by("data_segnalazione", "pk").values_list("pk", "data_segnalazione", "codice_identificativo"))

    inizio = _primo_del_mese(oggi, MESI_ANDAMENTO - 1)
    per_mese: dict[tuple[int, int], int] = {}
    for _pk, dt, _c in righe:
        g = _giorno(dt)
        if g and g >= inizio:
            per_mese[(g.year, g.month)] = per_mese.get((g.year, g.month), 0) + 1

    g_questa = _giorno(segnalazione.data_segnalazione)
    mesi = []
    chiavi = []
    for i in range(MESI_ANDAMENTO - 1, -1, -1):
        m = _primo_del_mese(oggi, i)
        n = per_mese.get((m.year, m.month), 0)
        etichetta = MESI_BREVI[m.month - 1]
        mesi.append((etichetta, n, f"{etichetta} {m.year}: {n} segnalazion{'e' if n == 1 else 'i'} di {segnalazione.preposto}"))
        chiavi.append((m.year, m.month, f"{etichetta} {m.year}"))
    andamento = _barre(mesi)
    for barra, (anno, mese, nome) in zip(andamento, chiavi):
        barra["mese"] = nome
        barra["questa"] = bool(g_questa) and (anno, mese) == (g_questa.year, g_questa.month)

    pks = [p for p, _d, _c in righe]
    posizione = pks.index(segnalazione.pk) if segnalazione.pk in pks else None
    precedente = successiva = None
    if posizione is not None:
        if posizione > 0:
            precedente = {"pk": righe[posizione - 1][0], "quando": righe[posizione - 1][1], "codice": righe[posizione - 1][2]}
        if posizione < len(righe) - 1:
            successiva = {"pk": righe[posizione + 1][0], "quando": righe[posizione + 1][1], "codice": righe[posizione + 1][2]}

    stesso_mese = sum(1 for _p, dt, _c in righe if g_questa and _giorno(dt)
                      and (_giorno(dt).year, _giorno(dt).month) == (g_questa.year, g_questa.month))
    return {
        "preposto": segnalazione.preposto,
        "totale": len(righe),
        "ultimi_12_mesi": sum(b["valore"] for b in andamento),
        "stesso_mese": stesso_mese,
        "numero": (posizione + 1) if posizione is not None else None,
        "precedente": precedente,
        "successiva": successiva,
        "andamento": andamento,
        "in_finestra": any(b["questa"] for b in andamento),
    }


def infografica(segnalazione, storyline: dict, qs_visibili, *, oggi: date | None = None) -> dict:
    return {
        "percorso": percorso(segnalazione, storyline, oggi=oggi),
        "controlli": controlli(segnalazione, storyline),
        "contesto": contesto_preposto(qs_visibili, segnalazione, oggi=oggi),
    }
