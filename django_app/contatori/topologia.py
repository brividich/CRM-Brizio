"""Topologia della rete degli apparati: pannello delle porte e albero dei collegamenti.

Fonte unica: ``PortaApparato`` (le porte che chi gestisce descrive su firewall e switch). Un collegamento da una porta
a un apparato del modulo (dispositivo SNMP o MFC) è un ramo dell'albero; un collegamento a un testo («Internet»,
«Fibra provider») diventa un nodo descrittivo: su una porta WAN sta sopra l'apparato, sulle altre è una foglia.

Leggero: tre query (dispositivi, MFC, porte), nessuna interrogazione SNMP. La tabella MAC degli switch
(``contatori.tabella_mac``) serve solo a **proporre** collegamenti nell'editor delle porte, mai a scriverli.
"""
from __future__ import annotations

import re

from django.urls import reverse

from .presentazione import TIPI

PORTE_DEFAULT = {"FIREWALL": 8, "RETE": 24}
TONI = {"OK": "ok", "WARNING": "warn", "ERROR": "danger", "MAI": "muted"}
ORDINE_RADICI = {"FIREWALL": 0, "RETE": 1, "SERVER": 2, "STORAGE": 3, "UPS": 4, "TVCC_NVR": 5, "MFC": 7}


def numero_porta(testo):
    """Il numero di una porta dal suo nome: «Gi1/0/12» → 12, «port 3» → 3, «12» → 12."""
    numeri = re.findall(r"\d+", str(testo or ""))
    return int(numeri[-1]) if numeri else None


def porte_pannello(dispositivo, porte=None):
    """Le porte da disegnare (numero, tipo, nome, collegato, tono): quelle descritte e le libere fino al totale."""
    porte = list(porte if porte is not None else dispositivo.porte_disegnate.select_related("collegato_dispositivo", "collegato_macchina"))
    per_numero = {p.numero: p for p in porte}
    totale = dispositivo.porte_totali or max([*per_numero, PORTE_DEFAULT.get(dispositivo.categoria, 0)])
    out = []
    for n in range(1, totale + 1):
        p = per_numero.get(n)
        collegato = p.collegato if p else None
        out.append({
            "numero": n, "nome": p.nome if p else "", "tipo": p.tipo if p else "LAN", "vlan": p.vlan if p else "",
            "collegato": p.collegato_label if p else "", "nota": p.nota if p else "",
            "url": _url(collegato) if collegato else "",
            "occupata": bool(p and (p.collegato_label or p.nome)),
            "tono": "danger" if collegato is not None and getattr(collegato, "snmp_stato", "") == "ERROR" else (
                "wan" if p and p.tipo == "WAN" else ("on" if p and (p.collegato_label or p.nome) else "off")),
        })
    return out


def _url(oggetto):
    from .models import Macchina

    if isinstance(oggetto, Macchina):
        return reverse("contatori:macchina", args=[oggetto.pk])
    return reverse("contatori:snmp_dispositivo", args=[oggetto.pk])


def _nodo(oggetto, *, mfc=False):
    if mfc:
        return {"chiave": f"m{oggetto.pk}", "nome": oggetto.reparto, "sigla": "MFC", "tipo": "MFC", "host": oggetto.host or "",
                "tono": TONI.get(oggetto.snmp_stato, "muted"), "url": reverse("contatori:macchina", args=[oggetto.pk]),
                "anteprima": reverse("contatori:anteprima", args=["mfc", oggetto.pk]), "figli": []}
    cfg = TIPI.get(oggetto.categoria, TIPI["ALTRO"])
    return {"chiave": f"d{oggetto.pk}", "nome": oggetto.nome, "sigla": "MFC" if oggetto.categoria == "STAMPANTE" else cfg["sigla"],
            "tipo": oggetto.categoria, "host": oggetto.host or "", "tono": TONI.get(oggetto.snmp_stato, "muted"),
            "url": reverse("contatori:snmp_dispositivo", args=[oggetto.pk]),
            "anteprima": reverse("contatori:anteprima", args=["snmp", oggetto.pk]), "figli": []}


def albero():
    """{radici, scollegati, collegamenti}: l'albero della rete dalle porte descritte, senza cicli."""
    from .models import DispositivoSNMP, Macchina, PortaApparato
    from .services import dispositivi_senza_doppioni

    nodi = {}
    for d in dispositivi_senza_doppioni(DispositivoSNMP.objects.filter(attivo=True)):
        nodi[f"d{d.pk}"] = _nodo(d)
    for m in Macchina.objects.filter(attiva=True):
        nodi[f"m{m.pk}"] = _nodo(m, mfc=True)
    figli_di, padre_di, testi = {}, {}, []
    porte = list(PortaApparato.objects.filter(dispositivo__attivo=True).select_related("dispositivo").order_by("dispositivo_id", "numero"))
    # Prima le porte dei firewall, poi degli switch…: chi sta a monte diventa padre, un cavo «di ritorno» non lo ribalta.
    porte.sort(key=lambda p: (ORDINE_RADICI.get(p.dispositivo.categoria, 6), p.dispositivo_id, p.numero))

    def antenato(chi, di):
        while di in padre_di:
            di = padre_di[di]
            if di == chi:
                return True
        return False

    for p in porte:
        padre = f"d{p.dispositivo_id}"
        if padre not in nodi:
            continue
        etichetta = f"porta {p.numero}" + (f" · {p.nome}" if p.nome else "") + (f" · VLAN {p.vlan}" if p.vlan else "")
        figlio = f"d{p.collegato_dispositivo_id}" if p.collegato_dispositivo_id else (f"m{p.collegato_macchina_id}" if p.collegato_macchina_id else "")
        if figlio and figlio in nodi and figlio != padre and figlio not in padre_di and not antenato(figlio, padre):
            padre_di[figlio] = padre
            figli_di.setdefault(padre, []).append((etichetta, figlio))
        elif not figlio and p.collegato_testo:
            testi.append((padre, p, etichetta))
    # Nodi descrittivi: sulla WAN stanno sopra l'apparato (es. Internet → firewall), altrove sono foglie.
    sopra = {}
    for padre, p, etichetta in testi:
        chiave = f"t{p.pk}"
        nodi[chiave] = {"chiave": chiave, "nome": p.collegato_testo, "sigla": "WAN" if p.tipo == "WAN" else "•", "tipo": "TESTO",
                        "host": "", "tono": "muted", "url": "", "anteprima": "", "figli": [], "descrittivo": True}
        if p.tipo == "WAN" and padre not in padre_di:
            sopra.setdefault(p.collegato_testo.strip().lower(), (chiave, []))[1].append((etichetta, padre))
        else:
            figli_di.setdefault(padre, []).append((etichetta, chiave))

    def costruisci(chiave, visti):
        nodo = dict(nodi[chiave])
        nodo["figli"] = [{"porta": et, "nodo": costruisci(f, visti | {f})} for et, f in figli_di.get(chiave, []) if f not in visti]
        nodo["discendenti"] = sum(1 + c["nodo"]["discendenti"] for c in nodo["figli"])
        return nodo

    radici, usati = [], set()
    for chiave_testo, sotto in sopra.values():
        nodo = dict(nodi[chiave_testo])
        # Più porte WAN dello stesso apparato verso lo stesso «Internet»: l'apparato compare una volta, con tutte le porte.
        per_padre = {}
        for et, padre in sotto:
            per_padre.setdefault(padre, []).append(et)
        nodo["figli"] = [{"porta": " + ".join(ets), "nodo": costruisci(padre, {padre})} for padre, ets in per_padre.items()]
        nodo["discendenti"] = sum(1 + c["nodo"]["discendenti"] for c in nodo["figli"])
        radici.append(nodo)
        usati.update(padre for _et, padre in sotto)
    collegati = set(padre_di) | set(figli_di) | usati
    for chiave in sorted((k for k in nodi if k in collegati and k not in padre_di and k not in usati and not k.startswith("t")),
                         key=lambda k: (ORDINE_RADICI.get(nodi[k]["tipo"], 6), nodi[k]["nome"].casefold())):
        radici.append(costruisci(chiave, {chiave}))
    scollegati = sorted((n for k, n in nodi.items() if k not in collegati and not k.startswith("t")),
                        key=lambda n: (ORDINE_RADICI.get(n["tipo"], 6), n["nome"].casefold()))
    return {"radici": radici, "scollegati": scollegati, "collegamenti": len(padre_di) + len(testi)}


def proposte_da_tabella_mac(dispositivo):
    """{numero porta: testo} dalla tabella MAC dello switch: l'apparato del modulo o l'asset visto su quella porta."""
    if dispositivo.categoria != "RETE":
        return {}
    from .models import DispositivoSNMP, Macchina
    from .tabella_mac import collegati_allo_switch

    righe = collegati_allo_switch(dispositivo)
    asset_ids = {r["asset"].pk for r in righe if r["asset"]}
    apparati = {d.asset_id: ("d", d) for d in DispositivoSNMP.objects.filter(asset_id__in=asset_ids, attivo=True)}
    apparati.update({m.asset_id: ("m", m) for m in Macchina.objects.filter(asset_id__in=asset_ids, attiva=True)})
    out = {}
    for r in righe:
        n = numero_porta(r["porta"])
        if not n or n in out or not r["asset"]:
            continue
        tipo, obj = apparati.get(r["asset"].pk, ("", None))
        out[n] = {"valore": f"{tipo}:{obj.pk}" if obj else "", "testo": (obj.nome if tipo == "d" else f"MFC {obj.reparto}") if obj else str(r["asset"]),
                  "vlan": str(r["vlan"] or "")}
    return out
