"""Vista semplice di «Struttura»: ogni dato con la sua etichetta, niente di superfluo.

Parte dal contesto di ``esplora_struttura.costruisci`` (stessi dati, stesse persone, stessi
indirizzi) e ne ricava quattro colonne (centro di costo → reparto → ruolo → mansione) più la
scheda del punto scelto: campi «etichetta: valore», le competenze richieste dalla mansione e
le persone che la hanno. La vista completa di prima (numeri, costi, carichi, altre strade)
resta a un clic.
"""
from __future__ import annotations

from django.urls import reverse

from ..models import SkillMatrixConfig
from ..models_skillmatrix import LivelloSkm
from . import esplora_struttura as es
from . import mansionario_competenze as mc
from . import mansionario_struttura, struttura_vista

SEMPLICE, COMPLETA = "semplice", "completa"
PAROLE_LIVELLO = {codice: etichetta.lower() for codice, etichetta in LivelloSkm.choices}
LEGENDA = [{"codice": c, "parola": p} for c, p in PAROLE_LIVELLO.items()]
_TONI = {mc.ABILITATO: "ok", mc.IN_ADDESTRAMENTO: "info", mc.NON_ABILITATO: "warning"}


def vista_scelta(request) -> str:
    """Semplice di default; la scelta fatta con ``?vista=`` resta per la sessione."""
    chiesta = request.GET.get("vista")
    if chiesta in (SEMPLICE, COMPLETA):
        request.session["esplora_vista"] = chiesta
    return COMPLETA if request.session.get("esplora_vista") == COMPLETA else SEMPLICE


PRIMA, ULTIMA = "prima", "ultima"


def posizione_mansioni(request) -> str:
    """Dove sta la colonna «Mansioni»: per ultima di default; la scelta fatta con ``?mansioni=`` resta per la sessione."""
    chiesta = request.GET.get("mansioni")
    if chiesta in (PRIMA, ULTIMA):
        request.session["esplora_mansioni"] = chiesta
    return PRIMA if request.session.get("esplora_mansioni") == PRIMA else ULTIMA


def _con_prima(url: str) -> str:
    """Il link porta con sé la posizione della colonna: l'indirizzo dice tutto, anche alla copia in memoria della pagina."""
    if not url or "mansioni=" in url:
        return url
    return f"{url}{'&' if '?' in url else '?'}mansioni={PRIMA}"


def _colonna_mansioni(d, m) -> dict:
    """Tutte le mansioni, in ordine di nome: con la colonna per prima si parte da qui."""
    voci = [es._voce(x.pk, x.nome, url_=es.url(mansione=x.pk), scelta=m is not None and x.pk == m.pk)
            for x in sorted(d.mansioni, key=lambda x: x.nome.casefold())]
    return {"livello": "mansione", "titolo": "Mansioni", "attesa": "", "voci": voci, "corrente": m is None}


def livello(codice: str) -> dict | None:
    codice = (codice or "").strip().upper()
    return {"codice": codice, "parola": PAROLE_LIVELLO.get(codice, "")} if codice else None


def _campo(etichetta: str, valore, url: str = "") -> dict:
    return {"etichetta": etichetta, "valore": valore, "url": url}


def _nome_centro(ctx) -> str:
    s, centro = ctx["scelti"], ctx["centro_obj"]
    if centro is not None:
        return centro.nome
    return es.ETICHETTE_SENZA["centro"] if s["centro"] is not None else ""


def _nome_area(ctx) -> str:
    s, area = ctx["scelti"], ctx["area_obj"]
    if area is not None:
        return area.nome
    return es.ETICHETTE_SENZA["area"] if s["area"] is not None else ""


def _nome_ruolo(ctx) -> str:
    s, ruolo = ctx["scelti"], ctx["ruolo_obj"]
    if ruolo is not None:
        return es._etichetta_ruolo(ruolo)
    return es.ETICHETTE_SENZA["ruolo"] if s["ruolo"] is not None else ""


def _responsabile(ctx) -> str:
    area = ctx["area_obj"]
    if area is None:
        return ""
    ids = es._responsabili(ctx["dati"], area)
    nomi = struttura_vista._nomi(ids)
    return ", ".join(nomi.get(i) or f"#{i}" for i in ids)


def _url_scheda(legacy_id: int) -> str:
    return reverse("anagrafica:dipendente_detail", args=[legacy_id])


def _requisito(voce) -> str:
    if voce.corso_id:
        return f"corso «{voce.corso.titolo}»"
    if voce.qualifica_id:
        return f"qualifica «{voce.qualifica.nome}»"
    if voce.processo_mpq_id:
        return f"qualifica MOD.128 «{voce.processo_mpq.nome}»"
    return ""


def _competenze(m, voce_scelta) -> list[dict]:
    return [{"nome": v.nome, "livello": livello(v.livello_minimo), "bloccante": v.bloccante,
             "requisito": _requisito(v), "scelta": voce_scelta is not None and v.pk == voce_scelta.pk}
            for v in mc.competenze(m)]


def _persone_mansione(d, m) -> list[dict]:
    """Chi ha la mansione: livello registrato e stato con la stessa regola del Mansionario."""
    persone = [p for p in mansionario_struttura.persone(m) if p["legacy_id"] in d.in_forza]
    if not persone:
        return []
    voci = list(mc.competenze(m))
    requisiti = mc.Requisiti([p["legacy_id"] for p in persone], voci)
    config = SkillMatrixConfig.get_instance()
    righe = []
    for p in persone:
        if p["sospesa"]:
            stato, tono = "Sospesa", "neutral"
        else:
            esito = mc.valuta(p["abilitazione"], voci=voci, config=config, requisiti=requisiti).esito
            stato, tono = mc.ESITI_LABEL[esito], _TONI[esito]
        righe.append({"nome": p["nome"], "url": _url_scheda(p["legacy_id"]), "livello": livello(p["livello"]),
                      "stato": stato, "tono": tono})
    return righe


def _richieste_aperte(m) -> int:
    from ..models_richieste import RichiestaCompetenze

    return RichiestaCompetenze.objects.filter(mansione=m, stato__in=RichiestaCompetenze.STATI_APERTI).count()


def _altre_mansione(m, persone: list[dict]) -> list[dict]:
    """Altri dati sulla mansione scelta: stesse regole e stessi elenchi delle pagine a cui portano."""
    abilitate = sum(1 for p in persone if p["stato"] == mc.ESITI_LABEL[mc.ABILITATO])
    aperte = _richieste_aperte(m)
    return [
        _campo("Persone abilitate", f"{abilitate} su {len(persone)}" if persone else "Nessuna persona"),
        _campo("Abilitazione con scadenza", "Sì" if m.abilitazione_con_scadenza else "No"),
        _campo("Richieste aperte", str(aperte), f"{reverse('anagrafica:richieste')}?mansione={m.pk}" if aperte else ""),
    ]


def _persone_punto(det: dict) -> list[dict]:
    return [{"nome": p["nome"], "url": _url_scheda(p["id"]), "ruoli": p.get("ruoli") or [],
             "area": p.get("area") or "", "mansioni": p.get("mansioni") or []}
            for p in det.get("persone") or []]


def costruisci(ctx: dict, *, puo_gestire: bool = False, puo_chiedere: bool = False, mansioni_prima: bool = False,
              strade=(), appena_spostata: bool = False) -> dict:
    """Che cosa mostra la vista semplice per il punto scelto (``ctx`` = contesto della pagina, con ``dati``)."""
    d, s, det = ctx["dati"], ctx["scelti"], ctx["dettaglio"]
    m, voce = ctx["mansione_obj"], ctx["voce_obj"]

    colonne = [dict(c) for c in ctx["colonne"] if c["livello"] != "competenza"]
    if not any(c["corrente"] for c in colonne):
        colonne[-1]["corrente"] = True

    briciole = [dict(b, url_corrente=False) for b in ctx["briciole"] if b.get("livello") != "Competenza"]
    briciole[-1]["url_corrente"] = True

    if mansioni_prima:
        # La colonna delle mansioni passa davanti e le elenca tutte; le altre tre restano nel loro ordine
        # e mostrano dove sta la mansione scelta. Ogni link porta con sé la posizione.
        altre = [c for c in colonne if c["livello"] != "mansione"]
        for c in altre:
            c["corrente"] = False
            c["voci"] = [dict(v, url=_con_prima(v["url"])) for v in c["voci"]] if c["voci"] is not None else None
        prima = _colonna_mansioni(d, m)
        prima["voci"] = [dict(v, url=_con_prima(v["url"])) for v in prima["voci"]]
        if m is not None:
            altre[-1]["corrente"] = True
        colonne = [prima, *altre]
        briciole = [dict(b, url=_con_prima(b.get("url") or "")) for b in briciole]
        scelta = next((b for b in briciole if b.get("livello") == "Mansione"), None)
        if scelta is not None:
            briciole.remove(scelta)
            briciole.insert(1, scelta)
        # Si parte dalle mansioni: la radice del percorso lo dice.
        briciole[0]["nome"] = "Tutte le mansioni"

    out = {"colonne": colonne, "briciole": briciole, "legenda": LEGENDA, "scheda": None,
           "mansioni_prima": mansioni_prima, "appena_spostata": appena_spostata,
           "collegate": [{"nome": x["nome"], "url": x["url"], "spiega": x.get("sotto") or ""} for x in strade]}
    centro, area, ruolo = _nome_centro(ctx), _nome_area(ctx), _nome_ruolo(ctx)

    if m is not None:
        campi = [_campo("Mansione", m.nome), _campo("Ruolo", ruolo or "Nessuno"),
                 _campo("Reparto", area or "Nessuno"), _campo("Responsabile del reparto", _responsabile(ctx) or "Nessuno"),
                 _campo("Centro di costo", centro or "Nessuno")]
        if m.asset_id:
            campi.append(_campo("Macchina", str(m.asset)))
        if m.processo_sgi_id:
            campi.append(_campo("Processo", str(m.processo_sgi)))
        rischi = [x.nome for x in m.mansioni_rischio.all()]
        if rischi:
            campi.append(_campo("Mansioni di rischio", ", ".join(rischi)))
        azioni = []
        if puo_chiedere:
            azioni.append({"nome": "Nuova richiesta per questa mansione", "principale": True,
                           "url": f"{reverse('anagrafica:richiesta_nuova')}?mansione={m.pk}"})
        azioni.append({"nome": "Persone e valutazioni", "url": reverse("anagrafica:mansionario_mansione", args=[m.pk])})
        if puo_gestire:
            azioni.append({"nome": "Modifica la mansione",
                           "url": reverse("anagrafica:mansionario_struttura_mansione", args=[m.pk])})
        out["scheda"] = {"titolo": "Mansione scelta", "campi": campi, "azioni": azioni}
        out["competenze"] = _competenze(m, voce)
        out["persone_mansione"] = _persone_mansione(d, m)
        out["altre"] = _altre_mansione(m, out["persone_mansione"])
        url_richieste = f"{reverse('anagrafica:richieste')}?mansione={m.pk}"
        out["collegate"].insert(0, {"nome": "Richieste su questa mansione", "url": url_richieste,
                                    "spiega": "Assegnazioni, sospensioni e rimozioni",
                                    "attesa": _richieste_aperte(m)})
    elif ctx["ruolo_obj"] is not None or s["ruolo"] is not None:
        campi = [_campo("Ruolo", ruolo), _campo("Reparto", area or "Nessuno"), _campo("Centro di costo", centro or "Nessuno")]
        sopra = next((x for x in det.get("gerarchia") or [] if x["sotto"] == "riporta a"), None)
        if sopra:
            campi.append(_campo("Riporta a", sopra["nome"], sopra["url"]))
        out["scheda"] = {"titolo": "Ruolo scelto", "campi": campi, "azioni": []}
        out["persone"] = {"titolo": "Persone con questo ruolo nel reparto", "ruolo": False, "reparto": False,
                          "righe": _persone_punto(det)}
    elif s["area"] is not None:
        campi = [_campo("Reparto", area), _campo("Responsabile del reparto", _responsabile(ctx) or "Nessuno"),
                 _campo("Centro di costo", centro or "Nessuno")]
        out["scheda"] = {"titolo": "Reparto scelto", "campi": campi, "azioni": []}
        out["persone"] = {"titolo": "Persone del reparto", "ruolo": True, "reparto": False,
                          "righe": _persone_punto(det)}
    elif s["centro"] is not None:
        campi = [_campo("Centro di costo", centro)]
        if ctx["centro_obj"] is not None and ctx["centro_obj"].descrizione:
            campi.append(_campo("Descrizione", ctx["centro_obj"].descrizione))
        out["scheda"] = {"titolo": "Centro di costo scelto", "campi": campi, "azioni": []}
        out["reparti"] = [{"nome": r["nome"], "url": r["url"], "responsabili": r["responsabili"], "persone": r["persone"]}
                          for r in det.get("reparti") or []]
    return out
