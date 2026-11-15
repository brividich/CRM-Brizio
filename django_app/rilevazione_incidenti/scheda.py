"""Storia e infografica della singola rilevazione, come nel Diario del preposto.

Tutto parte dal dict dei campi (``f``, nomi SharePoint) così funziona sia con i
dati nel database del portale sia con la lista SharePoint; storico (audit) e
mail ci sono solo per i record del database del portale.

- ``costruisci_storyline``: fatto, inserimento, modifiche campo per campo,
  valutazione RLS, chiusura RSPP/ASPP, azioni CAPA, mail automatiche;
- ``infografica``: percorso Fatto → Registrata → Notificata → Valutata RLS →
  Chiusa, controlli sì/no sulla tenuta della scheda, confronto col reparto.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time

from django.utils import timezone

from diario_preposto.cruscotto import MESI_ANDAMENTO, MESI_BREVI, _barre, _primo_del_mese

# Oltre questi giorni fra il fatto e l'inserimento la rilevazione è registrata in ritardo.
GIORNI_RITARDO_REGISTRAZIONE = 2
# Oltre questi giorni dal fatto una rilevazione ancora aperta va sollecitata.
GIORNI_CHIUSURA = 30

CAMPI_WHY = ("x31__x0020_WHY", "x32__x0020_WHY", "x33__x0020_WHY", "x34__x0020_WHY", "x35__x0020_WHY")
CAMPO_DESCRIZIONE = "Descrizione_x0020_avvenimento"
CAMPO_DESCRIZIONE_QI = "Descrizione_x0020_avvenimento_x0020__x0022_Quasi_x0020_incidente_x0022_"
CAMPO_MISURE = "Quali_x0020_misure_x0020_adottare"


@dataclass
class Evento:
    quando: datetime
    tipo: str            # fatto | registrata | modifica | rls | chiusura | capa | mail
    titolo: str
    chi: str = ""
    stato: str = ""      # "" | avviso | critico
    solo_data: bool = False
    righe: list = field(default_factory=list)   # [{"campo","prima","dopo"}]
    note: list = field(default_factory=list)


def _locale(dt):
    return timezone.localtime(dt) if dt and timezone.is_aware(dt) else dt


def _giorno(dt) -> date | None:
    if isinstance(dt, datetime):
        return _locale(dt).date()
    return dt if isinstance(dt, date) else None


def data_ora(valore) -> datetime | None:
    """ISO (anche solo data) → datetime aware; None se vuoto o non leggibile."""
    if not valore:
        return None
    if isinstance(valore, datetime):
        dt = valore
    else:
        try:
            dt = datetime.fromisoformat(str(valore).replace("Z", "+00:00"))
        except ValueError:
            return None
    return timezone.make_aware(dt) if timezone.is_naive(dt) else dt


def solo_data(valore) -> datetime | None:
    try:
        g = date.fromisoformat(str(valore or "")[:10])
    except ValueError:
        return None
    return timezone.make_aware(datetime.combine(g, time.min))


def _testo(f: dict, chiave: str) -> str:
    return str(f.get(chiave) or "").strip()


def descrizione(f: dict) -> str:
    return _testo(f, CAMPO_DESCRIZIONE) or _testo(f, CAMPO_DESCRIZIONE_QI)


def _pk_locale(sp_id) -> int | None:
    try:
        return int(sp_id)
    except (TypeError, ValueError):
        return None


def costruisci_storyline(f: dict, sp_id, *, locale: bool, capa_items=()) -> dict:
    eventi: list[Evento] = []
    fatto = data_ora(f.get("Data_e_ora_rilevazione"))
    if fatto:
        eventi.append(Evento(fatto, "fatto", "Evento rilevato", chi=_testo(f, "Nominativo")))

    ritardo_giorni = None
    n_modifiche = 0
    pk = _pk_locale(sp_id) if locale else None
    if pk is not None:
        from core.audit import storico_leggibile, storico_oggetto

        voci = storico_leggibile(storico_oggetto(oggetto_tipo="rilevazione_incidenti.rilevazioneincidente",
                                                 oggetto_id=str(pk), limit=300))
        for voce in voci:
            if voce.azione == "auto_insert":
                registrata = Evento(voce.created_at, "registrata", f"Registrata nel portale come n. {pk}",
                                    chi=voce.utente_display or _testo(f, "Nominativo"))
                if fatto:
                    ritardo_giorni = (_giorno(voce.created_at) - _giorno(fatto)).days
                    if ritardo_giorni > GIORNI_RITARDO_REGISTRAZIONE:
                        registrata.stato = "avviso"
                        registrata.note.append(f"Inserita {ritardo_giorni} giorni dopo il fatto.")
                eventi.append(registrata)
            elif voce.azione == "auto_update" and voce.righe:
                n_modifiche += 1
                eventi.append(Evento(voce.created_at, "modifica",
                                     "Modificata: " + ", ".join(r["campo"].lower() for r in voce.righe),
                                     chi=voce.utente_display, righe=voce.righe))

    esito_rls = _testo(f, "Approvazione_RLS")
    quando_rls = solo_data(f.get("Data_approvazione_RLS"))
    if esito_rls and quando_rls:
        approvata = esito_rls.lower() == "approvato"
        eventi.append(Evento(quando_rls, "rls", f"Valutata dall'RLS: {esito_rls}", solo_data=True,
                             stato="" if approvata else "avviso"))
    quando_chiusura = solo_data(f.get("Data_chiusura_RSPP"))
    if f.get("Chiusura_RSPP") and quando_chiusura:
        eventi.append(Evento(quando_chiusura, "chiusura", "Chiusa da RSPP/ASPP", solo_data=True))

    capa = list(capa_items)
    for a in capa:
        ev = Evento(a.created_at, "capa", f"Azione {a.get_tipo_display().lower()}: {a.titolo}",
                    chi=(a.responsabile.get_full_name() or a.responsabile.get_username()) if a.responsabile_id else "",
                    note=[f"Stato: {a.get_stato_display()}"])
        eventi.append(ev)

    mail_ok = mail_ko = 0
    if pk is not None:
        try:
            from automazioni.models import EmailInviata

            for m in EmailInviata.objects.filter(sorgente="rilevazione_incidenti", record_id=str(pk)).order_by("inviata_il"):
                destinatari = ", ".join(x.strip() for x in (m.destinatari or "").replace(";", ",").split(",") if x.strip())
                if m.esito == EmailInviata.ESITO_ERRORE:
                    mail_ko += 1
                    eventi.append(Evento(m.inviata_il, "mail", f"Notifica NON partita: {m.oggetto or '-'}",
                                         stato="critico", note=[f"A: {destinatari}" if destinatari else "", (m.errore or "")[:200]]))
                else:
                    mail_ok += 1
                    eventi.append(Evento(m.inviata_il, "mail", f"Notifica inviata: {m.oggetto or '-'}",
                                         note=[f"A: {destinatari}"] if destinatari else []))
        except Exception:
            pass

    for ev in eventi:
        ev.note = [n for n in ev.note if n]
    eventi.sort(key=lambda e: (e.quando, 0 if e.tipo == "fatto" else 1))

    oggi = timezone.localdate()
    ultima = max((e for e in eventi if e.tipo != "fatto"), key=lambda e: e.quando, default=None)
    capa_aperte = sum(1 for a in capa if a.stato not in a.STATI_CONCLUSI)
    return {
        "eventi": eventi,
        "riepilogo": {
            "giorni_dal_fatto": (oggi - _giorno(fatto)).days if fatto else None,
            "ritardo_giorni": ritardo_giorni,
            "ritardo_avviso": ritardo_giorni is not None and ritardo_giorni > GIORNI_RITARDO_REGISTRAZIONE,
            "why": sum(1 for c in CAMPI_WHY if _testo(f, c)),
            "capa": len(capa),
            "capa_aperte": capa_aperte,
            "modifiche": n_modifiche,
            "storico": pk is not None,
            "mail_ok": mail_ok,
            "mail_ko": mail_ko,
            "ultima_attivita": ultima.quando if ultima else None,
            "ultima_attivita_solo_data": bool(ultima and ultima.solo_data),
            "ultima_attivita_chi": ultima.chi if ultima else "",
        },
    }


def _dopo(giorni: int | None) -> str:
    if giorni is None:
        return ""
    if giorni <= 0:
        return "stesso giorno"
    return f"dopo {giorni} giorn{'o' if giorni == 1 else 'i'}"


def percorso(f: dict, storyline: dict, *, oggi: date | None = None) -> list[dict]:
    oggi = oggi or timezone.localdate()
    eventi = storyline["eventi"]
    r = storyline["riepilogo"]
    fatto = data_ora(f.get("Data_e_ora_rilevazione"))
    g_fatto = _giorno(fatto)

    def giorni(dt):
        g = _giorno(dt)
        return (g - g_fatto).days if g and g_fatto else None

    tappe = [{"titolo": "Fatto", "quando": fatto, "stato": "ok" if fatto else "assente",
              "nota": _testo(f, "Nominativo"), "dopo": "giorno 0" if fatto else ""}]

    registrata = next((e for e in eventi if e.tipo == "registrata"), None)
    if registrata:
        tappe.append({"titolo": "Registrata", "quando": registrata.quando,
                      "stato": "avviso" if r["ritardo_avviso"] else "ok",
                      "nota": f"oltre i {GIORNI_RITARDO_REGISTRAZIONE} giorni" if r["ritardo_avviso"] else "nei tempi",
                      "dopo": _dopo(giorni(registrata.quando))})
    else:
        tappe.append({"titolo": "Registrata", "quando": None, "stato": "assente",
                      "nota": "data di inserimento non registrata", "dopo": ""})

    mail_ok = next((e for e in eventi if e.tipo == "mail" and e.stato != "critico"), None)
    if r["mail_ko"]:
        tappe.append({"titolo": "Notificata", "quando": mail_ok.quando if mail_ok else None, "stato": "critico",
                      "nota": f"{r['mail_ko']} notific{'a' if r['mail_ko'] == 1 else 'he'} non partit{'a' if r['mail_ko'] == 1 else 'e'}",
                      "dopo": _dopo(giorni(mail_ok.quando)) if mail_ok else ""})
    elif mail_ok:
        tappe.append({"titolo": "Notificata", "quando": mail_ok.quando, "stato": "ok",
                      "nota": f"{r['mail_ok']} mail inviat{'a' if r['mail_ok'] == 1 else 'e'}",
                      "dopo": _dopo(giorni(mail_ok.quando))})
    else:
        tappe.append({"titolo": "Notificata", "quando": None, "stato": "assente",
                      "nota": "nessuna mail registrata", "dopo": ""})

    rls = next((e for e in eventi if e.tipo == "rls"), None)
    esito_rls = _testo(f, "Approvazione_RLS")
    if rls:
        tappe.append({"titolo": "Valutata RLS", "quando": rls.quando, "solo_data": True,
                      "stato": "ok" if esito_rls.lower() == "approvato" else "avviso",
                      "nota": esito_rls, "dopo": _dopo(giorni(rls.quando))})
    else:
        tappe.append({"titolo": "Valutata RLS", "quando": None, "stato": "assente",
                      "nota": esito_rls or "in attesa", "dopo": ""})

    chiusura = next((e for e in eventi if e.tipo == "chiusura"), None)
    if f.get("Chiusura_RSPP"):
        tappe.append({"titolo": "Chiusa", "quando": chiusura.quando if chiusura else None, "solo_data": True,
                      "stato": "ok", "nota": "RSPP/ASPP",
                      "dopo": _dopo(giorni(chiusura.quando)) if chiusura else ""})
    else:
        g = (oggi - g_fatto).days if g_fatto else None
        in_ritardo = g is not None and g > GIORNI_CHIUSURA
        tappe.append({"titolo": "Chiusa", "quando": None, "stato": "avviso" if in_ritardo else "assente",
                      "nota": f"oltre i {GIORNI_CHIUSURA} giorni" if in_ritardo else "ancora aperta",
                      "dopo": ""})
        tappe.append({"titolo": "Oggi", "quando": None, "stato": "ok",
                      "nota": f"{r['modifiche']} modific{'a' if r['modifiche'] == 1 else 'he'}" if r["storico"] else "",
                      "dopo": "" if g is None else f"{g} giorn{'o' if g == 1 else 'i'} dal fatto"})
    return tappe


def controlli(f: dict, storyline: dict) -> dict:
    r = storyline["riepilogo"]
    voci = []

    def voce(titolo, stato, dettaglio):
        voci.append({"titolo": titolo, "stato": stato, "dettaglio": dettaglio})

    if r["ritardo_giorni"] is None:
        voce("Registrata in tempo", "assente", "data del fatto o dell'inserimento mancante")
    elif r["ritardo_avviso"]:
        voce("Registrata in tempo", "avviso",
             f"inserita {r['ritardo_giorni']} giorni dopo il fatto (soglia {GIORNI_RITARDO_REGISTRAZIONE})")
    else:
        voce("Registrata in tempo", "ok", f"entro {GIORNI_RITARDO_REGISTRAZIONE} giorni dal fatto")

    mancanti = [nome for nome, valore in (
        ("nominativo", _testo(f, "Nominativo")),
        ("reparto", _testo(f, "Reparto") or _testo(f, "Reparto_txt")),
        ("descrizione", descrizione(f)),
    ) if not valore]
    if mancanti:
        voce("Dati completi", "avviso", "manca " + ", ".join(mancanti))
    else:
        voce("Dati completi", "ok", "nominativo, reparto e descrizione presenti")

    if r["why"]:
        voce("Analisi 5WHY", "ok", f"{r['why']} perché su 5 compilati")
    else:
        voce("Analisi 5WHY", "avviso", "nessun perché compilato")

    if _testo(f, CAMPO_MISURE):
        voce("Misure individuate", "ok", "indicate le misure da adottare")
    else:
        voce("Misure individuate", "avviso", "nessuna misura indicata")

    if r["mail_ko"]:
        voce("Notifiche partite", "critico", f"{r['mail_ko']} non partit{'a' if r['mail_ko'] == 1 else 'e'}")
    elif r["mail_ok"]:
        voce("Notifiche partite", "ok", f"{r['mail_ok']} inviat{'a' if r['mail_ok'] == 1 else 'e'}")
    else:
        voce("Notifiche partite", "assente", "nessuna mail registrata per la rilevazione")

    esito_rls = _testo(f, "Approvazione_RLS")
    if esito_rls.lower() == "approvato":
        voce("Valutazione RLS", "ok", "approvata")
    elif esito_rls:
        voce("Valutazione RLS", "avviso", esito_rls.lower())
    else:
        voce("Valutazione RLS", "assente", "in attesa")

    if f.get("Chiusura_RSPP"):
        voce("Chiusa da RSPP/ASPP", "ok", "chiusura registrata")
    elif r["giorni_dal_fatto"] is not None and r["giorni_dal_fatto"] > GIORNI_CHIUSURA:
        voce("Chiusa da RSPP/ASPP", "avviso",
             f"aperta da {r['giorni_dal_fatto']} giorni (soglia {GIORNI_CHIUSURA})")
    else:
        voce("Chiusa da RSPP/ASPP", "assente", "ancora aperta")

    if r["capa_aperte"]:
        voce("Azioni correttive", "avviso",
             f"{r['capa_aperte']} di {r['capa']} ancora da concludere")
    elif r["capa"]:
        voce("Azioni correttive", "ok", f"{r['capa']} collegat{'a' if r['capa'] == 1 else 'e'}, tutte concluse")
    else:
        voce("Azioni correttive", "assente", "nessuna azione collegata")

    valutati = [v for v in voci if v["stato"] != "assente"]
    return {
        "voci": voci,
        "superati": sum(1 for v in valutati if v["stato"] == "ok"),
        "valutati": len(valutati),
        "critici": sum(1 for v in voci if v["stato"] == "critico"),
        "avvisi": sum(1 for v in voci if v["stato"] == "avviso"),
    }


def contesto_reparto(items_visibili: list[dict], f: dict, sp_id, *, oggi: date | None = None) -> dict | None:
    """Le rilevazioni dello stesso reparto che l'utente può vedere."""
    reparto = _testo(f, "Reparto") or _testo(f, "Reparto_txt")
    if not reparto:
        return None
    oggi = oggi or timezone.localdate()
    righe = []
    for it in items_visibili:
        campi = it.get("fields") or {}
        if (_testo(campi, "Reparto") or _testo(campi, "Reparto_txt")).lower() != reparto.lower():
            continue
        righe.append((str(it.get("id")), data_ora(campi.get("Data_e_ora_rilevazione")),
                      campi.get("Tipo_evento_label") or _testo(campi, "Tipologia_scheda")))
    minimo = timezone.make_aware(datetime(1900, 1, 1))
    righe.sort(key=lambda x: (x[1] or minimo, _pk_locale(x[0]) or 0, x[0]))

    inizio = _primo_del_mese(oggi, MESI_ANDAMENTO - 1)
    per_mese: dict[tuple[int, int], int] = {}
    for _id, dt, _t in righe:
        g = _giorno(dt)
        if g and g >= inizio:
            per_mese[(g.year, g.month)] = per_mese.get((g.year, g.month), 0) + 1

    g_questa = _giorno(data_ora(f.get("Data_e_ora_rilevazione")))
    mesi, chiavi = [], []
    for i in range(MESI_ANDAMENTO - 1, -1, -1):
        m = _primo_del_mese(oggi, i)
        n = per_mese.get((m.year, m.month), 0)
        etichetta = MESI_BREVI[m.month - 1]
        mesi.append((etichetta, n, f"{etichetta} {m.year}: {n} rilevazion{'e' if n == 1 else 'i'} in {reparto}"))
        chiavi.append((m.year, m.month, f"{etichetta} {m.year}"))
    andamento = _barre(mesi)
    for barra, (anno, mese, nome) in zip(andamento, chiavi):
        barra["mese"] = nome
        barra["questa"] = bool(g_questa) and (anno, mese) == (g_questa.year, g_questa.month)

    ids = [i for i, _d, _t in righe]
    posizione = ids.index(str(sp_id)) if str(sp_id) in ids else None
    precedente = successiva = None
    if posizione is not None:
        if posizione > 0:
            i, dt, t = righe[posizione - 1]
            precedente = {"id": i, "quando": dt, "tipo": t}
        if posizione < len(righe) - 1:
            i, dt, t = righe[posizione + 1]
            successiva = {"id": i, "quando": dt, "tipo": t}

    stesso_mese = sum(1 for _i, dt, _t in righe if g_questa and _giorno(dt)
                      and (_giorno(dt).year, _giorno(dt).month) == (g_questa.year, g_questa.month))
    return {
        "reparto": reparto,
        "totale": len(righe),
        "ultimi_12_mesi": sum(b["valore"] for b in andamento),
        "stesso_mese": stesso_mese,
        "numero": (posizione + 1) if posizione is not None else None,
        "precedente": precedente,
        "successiva": successiva,
        "andamento": andamento,
        "in_finestra": any(b["questa"] for b in andamento),
    }


def infografica(f: dict, sp_id, storyline: dict, items_visibili: list[dict], *, oggi: date | None = None) -> dict:
    return {
        "percorso": percorso(f, storyline, oggi=oggi),
        "controlli": controlli(f, storyline),
        "contesto": contesto_reparto(items_visibili, f, sp_id, oggi=oggi),
    }
