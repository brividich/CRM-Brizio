"""Catalogo report del modulo asset (PROMPT 06 - D).

Ogni report e' una funzione ``esegui(filtri) -> RisultatoReport`` con intestazioni,
righe e una riga di totali calcolata dalle stesse righe: pagina, Excel e PDF usano
lo stesso risultato, quindi i totali coincidono per costruzione (e un test lo verifica).

Il catalogo elenca anche i report gia' esistenti nel modulo, con il loro link.
"""
from __future__ import annotations

import logging
import re
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone

MAX_RIGHE = 5000
logger = logging.getLogger(__name__)


@dataclass
class Filtro:
    nome: str
    etichetta: str
    tipo: str = "text"  # text | date | month | select
    scelte: list = field(default_factory=list)
    default: str = ""


@dataclass
class RisultatoReport:
    titolo: str
    intestazioni: list[str]
    righe: list[list]
    totali: list | None = None
    note: list[str] = field(default_factory=list)
    troncato: bool = False
    #: Colonne sommate quando la ricerca libera restringe le righe (i totali si ricalcolano).
    somma: tuple = ()
    #: Riquadri in testa alla pagina: [(etichetta, valore)], dalle righe mostrate.
    riepilogo: list = field(default_factory=list)
    #: Grafico a barre: {"titolo": str, "barre": [{"etichetta", "valore", "testo", "pct"}]}.
    grafico: dict | None = None
    #: Indici (sulle intestazioni originali) delle colonne mostrate, nell'ordine.
    colonne_idx: list = field(default_factory=list)
    #: Tutte le intestazioni del report, anche quelle nascoste (per la scelta colonne).
    intestazioni_tutte: list = field(default_factory=list)


#: Aree del catalogo, nell'ordine in cui compaiono.
AREE = ("Inventario", "IT e rete", "Manutenzione e scadenze", "Officina", "Qualità e PART 145", "Stampanti e contatori")


@dataclass
class DefinizioneReport:
    code: str
    titolo: str
    descrizione: str
    esempio: str
    filtri: list[Filtro]
    esegui: callable
    area: str = "Inventario"
    #: ``sintesi(righe) -> (riepilogo, grafico)`` sulle righe mostrate.
    sintesi: callable | None = None


def _num(valore) -> str:
    """Numero leggibile all'italiana (1.234 / 1.234,50) per i riquadri di riepilogo."""
    if isinstance(valore, float) and not valore.is_integer():
        return f"{valore:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{int(valore):,}".replace(",", ".")


def _barre(titolo: str, coppie, *, euro: bool = False, max_barre: int = 12) -> dict | None:
    """Grafico a barre orizzontali dai valori più alti; None se non c'è niente da disegnare."""
    coppie = sorted(((str(e) or "—", v) for e, v in coppie if v), key=lambda c: (-c[1], c[0].lower()))
    if not coppie:
        return None
    massimo = coppie[0][1] or 1
    barre = [{"etichetta": e, "valore": v, "testo": _num(v) + (" €" if euro else ""),
              "pct": max(2, round(100 * v / massimo))} for e, v in coppie[:max_barre]]
    if len(coppie) > max_barre:
        titolo += f" (primi {max_barre} di {len(coppie)})"
    return {"titolo": titolo, "barre": barre}


def _conta(righe, idx) -> dict:
    out: dict = defaultdict(int)
    for r in righe:
        out[r[idx] if r[idx] not in (None, "") else "—"] += 1
    return out


def _d(raw, default=None):
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw)[:10]) if raw else default
    except ValueError:
        return default


def _mese(raw, default=None):
    if not raw:
        return default
    try:
        y, m = str(raw)[:7].split("-")
        return date(int(y), int(m), 1)
    except ValueError:
        return default


def _status_choices():
    from ..models import Asset

    return [("", "Tutti")] + list(Asset.STATUS_CHOICES)


# ── 1. Inventario per stato e reparto ────────────────────────────────────────


def _inventario(filtri: dict) -> RisultatoReport:
    from ..models import Asset

    qs = Asset.objects.all()
    if filtri.get("reparto"):
        qs = qs.filter(reparto__icontains=filtri["reparto"])
    if filtri.get("asset_type"):
        qs = qs.filter(asset_type=filtri["asset_type"])
    if filtri.get("stato"):
        qs = qs.filter(status=filtri["stato"])
    stati = list(Asset.STATUS_CHOICES)
    pivot: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    # .order_by() vuoto: SQL Server rifiuta ORDER BY su colonne fuori dal GROUP BY (8127).
    for row in qs.order_by().values("reparto", "status").annotate(n=Count("id")):
        pivot[(row["reparto"] or "").strip() or "Senza reparto"][row["status"]] += row["n"]
    righe = []
    for reparto in sorted(pivot, key=str.lower):
        valori = [pivot[reparto].get(code, 0) for code, _ in stati]
        righe.append([reparto, *valori, sum(valori)])
    totali = ["Totale", *[sum(r[i + 1] for r in righe) for i in range(len(stati))], sum(r[-1] for r in righe)]
    return RisultatoReport("Inventario per stato e reparto", ["Reparto", *[l for _, l in stati], "Totale"], righe, totali,
                           somma=tuple(range(1, len(stati) + 2)))


def _sintesi_inventario(righe):
    from ..models import Asset

    stati = list(Asset.STATUS_CHOICES)
    riepilogo = [("Asset", _num(sum(r[-1] for r in righe)))]
    riepilogo += [(label, _num(sum(r[i + 1] for r in righe))) for i, (_, label) in enumerate(stati)]
    return riepilogo, _barre("Asset per reparto", [(r[0], r[-1]) for r in righe])


# ── 2. MFC: pagine e consumabili ─────────────────────────────────────────────


def _mfc(filtri: dict) -> RisultatoReport:
    from contatori.models import LetturaMensileContatori, Macchina
    from contatori.services import stato_consumabili

    from .mfc_stats import pagine_per_mese

    oggi = timezone.localdate()
    al = _mese(filtri.get("al"), oggi.replace(day=1) - timedelta(days=1)).replace(day=1)
    dal = _mese(filtri.get("dal"), (al - timedelta(days=31 * 2)).replace(day=1))
    if dal > al:
        dal, al = al, dal
    macchine = Macchina.objects.filter(attiva=True).select_related("asset").order_by("reparto", "matricola")
    if filtri.get("reparto"):
        macchine = macchine.filter(reparto__icontains=filtri["reparto"])
    macchine = list(macchine[:MAX_RIGHE])
    ids = [m.pk for m in macchine]
    letture: dict[int, list[dict]] = defaultdict(list)
    # La lettura del 1° del mese successivo chiude il mese "al": serve anche quella.
    fine = (al + timedelta(days=32)).replace(day=1)
    for start in range(0, len(ids), 1000):
        for row in (LetturaMensileContatori.objects.filter(macchina_id__in=ids[start:start + 1000], mese__gte=dal, mese__lte=fine)
                    .order_by("macchina_id", "mese").values("macchina_id", "mese", "a4_bn", "a3_bn", "a4_col", "a3_col")):
            letture[row["macchina_id"]].append(row)
    consumabili = {}
    for start in range(0, len(macchine), 1000):
        consumabili.update(stato_consumabili(macchine[start:start + 1000]))
    righe = []
    for m in macchine:
        serie = [s for s in pagine_per_mese(letture.get(m.pk, [])) if dal <= s["mese"] <= al]
        validi = [s for s in serie if s["totale"] is not None]
        mesi_periodo = (al.year - dal.year) * 12 + al.month - dal.month + 1
        bn = sum(s["bn"] for s in validi)
        col = sum(s["col"] for s in validi)
        stato = consumabili.get(m.pk)
        peggiore = stato["peggiore"] if stato else None
        righe.append([
            m.reparto, m.matricola, m.modello or "", m.asset.asset_tag if m.asset_id else "non collegato",
            bn, col, bn + col, mesi_periodo - len(validi),
            f"{peggiore['nome']} {peggiore['pct']}%" if peggiore else "",
            (peggiore or {}).get("giorni") if peggiore and peggiore.get("giorni") is not None else "",
            timezone.localtime(stato["rilevata_il"]).strftime("%d/%m/%Y") if stato else "mai letta",
        ])
    totali = ["Totale", "", "", "", sum(r[4] for r in righe), sum(r[5] for r in righe), sum(r[6] for r in righe),
              sum(r[7] for r in righe), "", "", ""]
    return RisultatoReport(
        f"MFC: pagine {dal:%m/%Y}–{al:%m/%Y} e consumabili",
        ["Reparto", "Matricola", "Modello", "Asset", "Pagine B/N", "Pagine colore", "Totale pagine",
         "Mesi non calcolabili", "Consumabile più basso", "Giorni stimati", "Ultima lettura consumabili"],
        righe, totali,
        note=["Pagine del mese = differenza fra letture mensili consecutive; un mese mancante o un contatore "
              "azzerato non viene stimato (colonna «Mesi non calcolabili»)."],
        troncato=len(macchine) >= MAX_RIGHE,
        somma=(4, 5, 6, 7),
    )


def _sintesi_mfc(righe):
    per_reparto: dict = defaultdict(int)
    for r in righe:
        per_reparto[r[0] or "Senza reparto"] += r[6]
    riepilogo = [("Macchine", _num(len(righe))), ("Pagine totali", _num(sum(r[6] for r in righe))),
                 ("B/N", _num(sum(r[4] for r in righe))), ("Colore", _num(sum(r[5] for r in righe))),
                 ("Mai lette", _num(sum(1 for r in righe if r[10] == "mai letta")))]
    return riepilogo, _barre("Pagine per reparto", per_reparto.items())


# ── 3. Scadenze: manutenzione, amministrative, garanzie ───────────────────────


def _scadenze(filtri: dict) -> RisultatoReport:
    from ..models import AssetAdministrativeDeadline, AssistanceContract, MaintenanceOccurrence

    oggi = timezone.localdate()
    dal = _d(filtri.get("dal"), oggi - timedelta(days=30))
    al = _d(filtri.get("al"), oggi + timedelta(days=90))
    tipo = filtri.get("tipo") or ""
    reparto = (filtri.get("reparto") or "").strip()
    righe = []

    def stato(giorno):
        return "Scaduta" if giorno < oggi else ("In scadenza" if giorno <= oggi + timedelta(days=30) else "Pianificata")

    if tipo in ("", "manutenzione"):
        qs = MaintenanceOccurrence.objects.filter(status=MaintenanceOccurrence.STATUS_OPEN, due_date__range=(dal, al))
        if reparto:
            qs = qs.filter(asset__reparto__icontains=reparto)
        for o in qs.select_related("asset", "plan").order_by("due_date", "asset__name")[:MAX_RIGHE]:
            righe.append([o.due_date, "Manutenzione", o.asset.asset_tag, o.asset.name, o.asset.reparto, o.plan.label, stato(o.due_date)])
    if tipo in ("", "amministrativa"):
        qs = AssetAdministrativeDeadline.objects.filter(is_active=True, due_date__range=(dal, al))
        if reparto:
            qs = qs.filter(asset__reparto__icontains=reparto)
        for s in qs.select_related("asset").order_by("due_date")[:MAX_RIGHE]:
            righe.append([s.due_date, "Amministrativa", s.asset.asset_tag, s.asset.name, s.asset.reparto, s.title, stato(s.due_date)])
    if tipo in ("", "garanzia"):
        qs = AssistanceContract.objects.filter(is_active=True, contract_type=AssistanceContract.TYPE_WARRANTY,
                                               end_date__range=(dal, al))
        if reparto:
            qs = qs.filter(Q(asset__reparto__icontains=reparto) | Q(asset__isnull=True))
        for c in qs.select_related("asset", "asset_category").order_by("end_date")[:MAX_RIGHE]:
            asset_tag = c.asset.asset_tag if c.asset_id else ""
            asset_nome = c.asset.name if c.asset_id else (f"Categoria {c.asset_category}" if c.asset_category_id else "")
            righe.append([c.end_date, "Garanzia", asset_tag, asset_nome, c.asset.reparto if c.asset_id else "",
                          c.title, stato(c.end_date)])
    righe.sort(key=lambda r: (r[0], r[1], r[2]))
    conteggi = OrderedDict((k, sum(1 for r in righe if r[1] == k)) for k in ("Manutenzione", "Amministrativa", "Garanzia"))
    totali = [f"Totale {len(righe)}", " · ".join(f"{k} {v}" for k, v in conteggi.items()), "", "", "", "",
              f"Scadute {sum(1 for r in righe if r[6] == 'Scaduta')}"]
    for r in righe:
        r[0] = r[0].strftime("%d/%m/%Y")
    return RisultatoReport(f"Scadenze dal {dal:%d/%m/%Y} al {al:%d/%m/%Y}",
                           ["Data", "Tipo", "Asset", "Nome", "Reparto", "Descrizione", "Stato"], righe, totali,
                           troncato=len(righe) >= MAX_RIGHE)


def _sintesi_scadenze(righe):
    stati = _conta(righe, 6)
    riepilogo = [("Scadenze", _num(len(righe))), ("Scadute", _num(stati.get("Scaduta", 0))),
                 ("Entro 30 giorni", _num(stati.get("In scadenza", 0))), ("Pianificate", _num(stati.get("Pianificata", 0)))]
    return riepilogo, _barre("Scadenze per tipo", _conta(righe, 1).items())


# ── 4. Modifiche rete e assegnazioni (dallo storico campi) ────────────────────


def _modifiche(filtri: dict) -> RisultatoReport:
    from ..models import AssetFieldHistory
    from .storico_asset import ETICHETTE, GRUPPI, _visualizza

    oggi = timezone.localdate()
    dal = _d(filtri.get("dal"), oggi - timedelta(days=30))
    al = _d(filtri.get("al"), oggi)
    gruppo = filtri.get("gruppo") or ""
    from .storico_asset import inizio_giorno

    qs = AssetFieldHistory.objects.exclude(fonte=AssetFieldHistory.FONTE_BASELINE).filter(
        cambiato_il__gte=inizio_giorno(dal), cambiato_il__lt=inizio_giorno(al + timedelta(days=1)))
    if gruppo in ("rete", "assegnazione", "stato"):
        qs = qs.filter(campo__in=GRUPPI[gruppo])
    else:
        qs = qs.filter(campo__in=GRUPPI["rete"] + GRUPPI["assegnazione"])
    if filtri.get("fonte"):
        qs = qs.filter(fonte=filtri["fonte"])
    if filtri.get("reparto"):
        qs = qs.filter(asset__reparto__icontains=filtri["reparto"])
    fonti = dict(AssetFieldHistory.FONTE_CHOICES)
    righe = [
        [timezone.localtime(h.cambiato_il).strftime("%d/%m/%Y %H:%M"), h.asset.asset_tag, h.asset.name,
         ETICHETTE.get(h.campo, h.campo), h.endpoint_label, _visualizza(h.campo, h.valore_prima),
         _visualizza(h.campo, h.valore_dopo), (h.autore_display or "").upper(), fonti.get(h.fonte, h.fonte)]
        for h in qs.select_related("asset").order_by("-cambiato_il", "-id")[:MAX_RIGHE]
    ]
    asset_distinti = len({r[1] for r in righe})
    totali = [f"Totale {len(righe)} modifiche", f"{asset_distinti} asset", "", "", "", "", "", "", ""]
    return RisultatoReport(f"Modifiche rete e assegnazioni dal {dal:%d/%m/%Y} al {al:%d/%m/%Y}",
                           ["Quando", "Asset", "Nome", "Campo", "Punto rete", "Prima", "Dopo", "Chi", "Fonte"],
                           righe, totali, troncato=len(righe) >= MAX_RIGHE)


def _sintesi_modifiche(righe):
    riepilogo = [("Modifiche", _num(len(righe))), ("Asset", _num(len({r[1] for r in righe}))),
                 ("Autori", _num(len({r[7] for r in righe if r[7]})))]
    return riepilogo, _barre("Modifiche per campo", _conta(righe, 3).items())


# ── 5. Parco IT e rete (interfacce, IP, switch e porte) ───────────────────────


def _switch_choices():
    from .rete_switch import switch_disponibili

    return [("", "Tutti")] + [(str(s["id"]), s["etichetta"]) for s in switch_disponibili()]


PROBLEMI_RETE = [("", "Nessun controllo"), ("senza_ip", "Senza IP"), ("senza_switch", "Switch non riconosciuto"),
                 ("senza_mac", "Senza MAC"), ("ip_duplicato", "IP usato da più interfacce"),
                 ("senza_rete", "Dispositivi IT senza interfacce")]


def _parco_it(filtri: dict) -> RisultatoReport:
    from ..forms import IT_DEVICE_TYPES
    from ..models import Asset, AssetEndpoint
    from .rete_switch import switch_per_endpoint

    tipi = dict(Asset.TYPE_CHOICES)
    qs = Asset.objects.exclude(status=Asset.STATUS_RETIRED)
    if filtri.get("asset_type"):
        qs = qs.filter(asset_type=filtri["asset_type"])
    else:
        qs = qs.filter(Q(asset_type__in=IT_DEVICE_TYPES) | Q(endpoints__isnull=False)).distinct()
    if filtri.get("reparto"):
        qs = qs.filter(reparto__icontains=filtri["reparto"])
    assets = list(qs.order_by("asset_tag").only("id", "asset_tag", "name", "asset_type", "reparto", "assignment_to")[:MAX_RIGHE])
    endpoints: dict[int, list] = defaultdict(list)
    ids = [a.pk for a in assets]
    for start in range(0, len(ids), 1000):
        for ep in AssetEndpoint.objects.filter(asset_id__in=ids[start:start + 1000]).order_by("asset_id", "endpoint_name", "id"):
            endpoints[ep.asset_id].append(ep)
    tutti = [ep for lista in endpoints.values() for ep in lista]
    switch = switch_per_endpoint(tutti)
    # IP duplicati sull'intero censimento, non solo nelle righe filtrate.
    ip_usati: dict[str, int] = defaultdict(int)
    for ip in AssetEndpoint.objects.exclude(ip__isnull=True).exclude(ip="").values_list("ip", flat=True):
        ip_usati[ip.strip()] += 1
    vlan = (filtri.get("vlan") or "").strip()
    switch_id = filtri.get("switch") or ""
    problema = filtri.get("problema") or ""
    righe = []
    for a in assets:
        base = [a.asset_tag, a.name, tipi.get(a.asset_type, a.asset_type), a.reparto, a.assignment_to]
        lista = endpoints.get(a.pk, [])
        if not lista:
            if not (vlan or switch_id) and problema in ("", "senza_rete") and a.asset_type in IT_DEVICE_TYPES:
                righe.append([*base, "", "", "", "", "", "", "", "Nessuna interfaccia di rete"])
            continue
        if problema == "senza_rete":
            continue
        for ep in lista:
            sw, da_prefisso = switch.get(ep.id, (None, False))
            ip = (ep.ip or "").strip()
            note = []
            if ip and ip_usati.get(ip, 0) > 1:
                note.append("IP duplicato")
            if sw is None and (ep.switch_name or ep.switch_port):
                note.append("switch non riconosciuto")
            elif da_prefisso:
                note.append("switch dal prefisso porte")
            if vlan and str(ep.vlan or "") != vlan:
                continue
            if switch_id and (sw is None or str(sw.pk) != switch_id):
                continue
            if problema == "senza_ip" and ip:
                continue
            if problema == "senza_switch" and sw is not None:
                continue
            if problema == "senza_mac" and ep.mac:
                continue
            if problema == "ip_duplicato" and "IP duplicato" not in note:
                continue
            righe.append([*base, ep.endpoint_name, ip, ep.mac, ep.vlan if ep.vlan is not None else "",
                          sw.asset_tag if sw else (ep.switch_name or ""), ep.switch_port, ep.punto, ", ".join(note)])
    asset_distinti = len({r[0] for r in righe})
    totali = [f"Totale {len(righe)} righe", f"{asset_distinti} asset", "", "", "", "", "", "", "", "", "", "", ""]
    return RisultatoReport(
        "Parco IT e rete",
        ["Asset", "Nome", "Tipo", "Reparto", "Assegnatario", "Interfaccia", "IP", "MAC", "VLAN", "Switch", "Porta",
         "Punto rete", "Note"],
        righe, totali,
        note=["Una riga per interfaccia di rete. Lo switch è quello indicato nel punto rete oppure, se manca, "
              "quello che ha il prefisso della porta (es. A0 per A0.1.12). Gli asset dismessi sono esclusi."],
        troncato=len(assets) >= MAX_RIGHE,
    )


def _sintesi_parco_it(righe):
    con_rete = [r for r in righe if r[5] or r[6] or r[10]]
    per_switch: dict = defaultdict(int)
    for r in con_rete:
        if r[9]:
            per_switch[r[9]] += 1
    riepilogo = [("Asset", _num(len({r[0] for r in righe}))), ("Interfacce", _num(len(con_rete))),
                 ("Senza IP", _num(sum(1 for r in con_rete if not r[6]))),
                 ("Switch non riconosciuto", _num(sum(1 for r in righe if "switch non riconosciuto" in r[12]))),
                 ("IP duplicati", _num(sum(1 for r in righe if "IP duplicato" in r[12]))),
                 ("Senza interfacce", _num(sum(1 for r in righe if r[12] == "Nessuna interfaccia di rete")))]
    return riepilogo, _barre("Interfacce per switch", per_switch.items())


# ── 6. Licenze software ──────────────────────────────────────────────────────


def _licenze(filtri: dict) -> RisultatoReport:
    from ..models import SoftwareLicense

    oggi = timezone.localdate()
    categorie = dict(SoftwareLicense.CATEGORY_CHOICES)
    qs = SoftwareLicense.objects.select_related("asset")
    stato_filtro = filtri.get("stato") or ""
    if stato_filtro != "tutte":
        qs = qs.filter(is_active=True)
    if filtri.get("categoria"):
        qs = qs.filter(category=filtri["categoria"])
    if filtri.get("reparto"):
        qs = qs.filter(Q(asset__reparto__icontains=filtri["reparto"]) | Q(assigned_reparto__icontains=filtri["reparto"]))

    def stato(lic):
        if not lic.is_active:
            return "Disattivata"
        if lic.expiry_date and lic.expiry_date < oggi:
            return "Scaduta"
        if lic.expiry_date and lic.expiry_date <= oggi + timedelta(days=60):
            return "In scadenza"
        return "Attiva"

    righe = []
    for lic in qs.order_by("category", "vendor", "product_name", "id")[:MAX_RIGHE]:
        s = stato(lic)
        if stato_filtro == "scadute" and s != "Scaduta":
            continue
        if stato_filtro == "in_scadenza" and s != "In scadenza":
            continue
        if lic.asset_id:
            assegnata, reparto = f"{lic.asset.asset_tag} — {lic.asset.name}", lic.asset.reparto
        else:
            assegnata, reparto = lic.assignment_label, lic.assigned_reparto
        righe.append([categorie.get(lic.category, lic.category), lic.product_name, lic.edition, lic.vendor,
                      lic.license_reference, assegnata, reparto, lic.seats_used or 0,
                      lic.seats_total if lic.seats_total is not None else "",
                      lic.expiry_date.strftime("%d/%m/%Y") if lic.expiry_date else "",
                      "Sì" if lic.auto_renew else "No", s])
    totali = [f"Totale {len(righe)} licenze", "", "", "", "", "", "", sum(r[7] for r in righe),
              sum(r[8] for r in righe if r[8] != ""), "", "", f"Scadute {sum(1 for r in righe if r[11] == 'Scaduta')}"]
    return RisultatoReport("Licenze software", ["Categoria", "Prodotto", "Edizione", "Produttore", "Riferimento",
                                                "Assegnata a", "Reparto", "Posti usati", "Posti totali", "Scadenza",
                                                "Rinnovo automatico", "Stato"],
                           righe, totali, somma=(7, 8), troncato=len(righe) >= MAX_RIGHE,
                           note=["«In scadenza» = entro 60 giorni. Le licenze disattivate compaiono solo con Stato «Tutte»."])


def _sintesi_licenze(righe):
    stati = _conta(righe, 11)
    per_prodotto: dict = defaultdict(int)
    for r in righe:
        per_prodotto[r[1]] += r[7]
    riepilogo = [("Licenze", _num(len(righe))), ("Posti usati", _num(sum(r[7] for r in righe))),
                 ("Scadute", _num(stati.get("Scaduta", 0))), ("Entro 60 giorni", _num(stati.get("In scadenza", 0)))]
    return riepilogo, _barre("Posti usati per prodotto", per_prodotto.items())


# ── 7. Costi e ore di manutenzione (OdL chiusi) ──────────────────────────────

RAGGRUPPA_COSTI = [("asset", "Asset"), ("reparto", "Reparto"), ("tipo", "Tipo di intervento"),
                   ("fornitore", "Fornitore"), ("mese", "Mese di chiusura")]


def _costi(filtri: dict) -> RisultatoReport:
    from decimal import Decimal

    from ..models import WorkOrder

    oggi = timezone.localdate()
    dal = _d(filtri.get("dal"), oggi.replace(month=1, day=1))
    al = _d(filtri.get("al"), oggi)
    if dal > al:
        dal, al = al, dal
    raggruppa = filtri.get("raggruppa") or "asset"
    from .storico_asset import inizio_giorno

    qs = WorkOrder.objects.filter(status=WorkOrder.STATUS_DONE, closed_at__gte=inizio_giorno(dal),
                                  closed_at__lt=inizio_giorno(al + timedelta(days=1)))
    if filtri.get("reparto"):
        qs = qs.filter(asset__reparto__icontains=filtri["reparto"])
    if filtri.get("kind"):
        qs = qs.filter(kind=filtri["kind"])
    tipi = dict(WorkOrder.KIND_CHOICES)
    gruppi: dict = OrderedDict()
    zero = Decimal("0")
    for wo in qs.select_related("asset", "supplier").order_by("closed_at", "id")[:50000]:
        if raggruppa == "reparto":
            chiave = wo.asset.reparto or "Senza reparto"
        elif raggruppa == "tipo":
            chiave = tipi.get(wo.kind, wo.kind)
        elif raggruppa == "fornitore":
            chiave = str(wo.supplier) if wo.supplier_id else "Interno / senza fornitore"
        elif raggruppa == "mese":
            chiave = timezone.localtime(wo.closed_at).strftime("%Y-%m")
        else:
            chiave = f"{wo.asset.asset_tag} — {wo.asset.name}"
        g = gruppi.setdefault(chiave, {"n": 0, "prev": 0, "corr": 0, "contratto": 0, "min": 0, "fermo": 0,
                                       "lab": zero, "mat": zero, "tot": zero})
        g["n"] += 1
        g["prev"] += wo.kind == WorkOrder.KIND_PREVENTIVE
        g["corr"] += wo.kind == WorkOrder.KIND_CORRECTIVE
        g["contratto"] += bool(wo.covered_by_contract)
        g["min"] += wo.intervention_duration_minutes or 0
        g["fermo"] += wo.downtime_minutes or 0
        g["lab"] += wo.labor_cost_eur or zero
        g["mat"] += wo.materials_cost_eur or zero
        g["tot"] += wo.resolved_total_cost_eur or zero

    def euro(v):
        return float(round(v, 2))

    righe = [[k, g["n"], g["prev"], g["corr"], g["contratto"], round(g["min"] / 60, 1), round(g["fermo"] / 60, 1),
              euro(g["lab"]), euro(g["mat"]), euro(g["tot"])] for k, g in gruppi.items()]
    if raggruppa == "mese":
        righe.sort(key=lambda r: r[0])
    else:
        righe.sort(key=lambda r: (-r[9], str(r[0]).lower()))
    somma = tuple(range(1, 10))
    totali = ["Totale", *[round(sum(r[i] for r in righe), 2) for i in somma]]
    etichetta = dict(RAGGRUPPA_COSTI).get(raggruppa, "Asset")
    return RisultatoReport(
        f"Costi e ore di manutenzione dal {dal:%d/%m/%Y} al {al:%d/%m/%Y}",
        [etichetta, "Interventi", "Preventivi", "Correttivi", "Coperti da contratto", "Ore intervento", "Ore fermo",
         "Manodopera €", "Materiali €", "Totale €"],
        righe, totali, somma=somma,
        note=["Ordini di lavoro chiusi nel periodo. Il totale è il costo indicato in chiusura oppure, se manca, "
              "manodopera + materiali."],
    )


def _sintesi_costi(righe):
    n = sum(r[1] for r in righe)
    tot = round(sum(r[9] for r in righe), 2)
    riepilogo = [("Interventi chiusi", _num(n)), ("Costo totale", _num(float(tot)) + " €"),
                 ("Costo medio", (_num(round(tot / n, 2)) + " €") if n else "—"),
                 ("Ore di fermo", _num(round(sum(r[6] for r in righe), 1)))]
    return riepilogo, _barre("Costo totale", [(r[0], r[9]) for r in righe], euro=True)


# ── Officina: utilizzo delle CNC dai periodi di stato ─────────────────────────

RAGGRUPPA_UTILIZZO = [("macchina", "Macchina"), ("giorno", "Macchina e giorno"), ("settimana", "Macchina e settimana"),
                      ("mese", "Macchina e mese")]
#: Colonne delle ore, nell'ordine, e gli stati del collegamento che finiscono in ognuna.
COLONNE_UTILIZZO = (
    ("In lavoro h", ("in_lavoro",)),
    ("MDI/manuale h", ("setup",)),
    ("Ferma h", ("pronta",)),
    ("Interrotta h", ("ferma",)),
    ("Allarme/emergenza h", ("allarme", "emergenza")),
    ("Offline h", ("spenta", "non_raggiungibile", "non_leggibile", "mai")),
)


def _secchi(inizio, fine, raggruppa):
    """Intervalli [(chiave, da, a)] in ora locale che coprono [inizio, fine)."""
    from .storico_asset import inizio_giorno

    if raggruppa not in ("giorno", "settimana", "mese"):
        return [("", inizio, fine)]
    giorno = timezone.localtime(inizio).date()
    if raggruppa == "settimana":
        giorno -= timedelta(days=giorno.weekday())
    elif raggruppa == "mese":
        giorno = giorno.replace(day=1)
    out = []
    while True:
        da = inizio_giorno(giorno)
        if da >= fine:
            break
        if raggruppa == "giorno":
            dopo = giorno + timedelta(days=1)
        elif raggruppa == "settimana":
            dopo = giorno + timedelta(days=7)
        else:
            dopo = (giorno.replace(day=28) + timedelta(days=4)).replace(day=1)
        out.append((giorno, max(da, inizio), min(inizio_giorno(dopo), fine)))
        giorno = dopo
    return out


def _etichetta_secchio(chiave, raggruppa, dal, al) -> str:
    if raggruppa == "giorno":
        return f"{chiave:%d/%m/%Y}"
    if raggruppa == "settimana":
        return f"Settimana {chiave.isocalendar()[1]} (dal {chiave:%d/%m/%Y})"
    if raggruppa == "mese":
        return f"{chiave:%m/%Y}"
    return f"{dal:%d/%m/%Y} – {al:%d/%m/%Y}"


def _utilizzo(filtri: dict) -> RisultatoReport:
    from bisect import bisect_right

    from ..models import CollegamentoMTConnect, PeriodoStatoMacchina
    from .storico_asset import inizio_giorno

    oggi = timezone.localdate()
    dal = _d(filtri.get("dal"), oggi - timedelta(days=6))
    al = _d(filtri.get("al"), oggi)
    if dal > al:
        dal, al = al, dal
    raggruppa = filtri.get("raggruppa") or "macchina"
    adesso = timezone.now()
    inizio, fine = inizio_giorno(dal), min(inizio_giorno(al + timedelta(days=1)), adesso)
    colonna_di = {stato: i for i, (_n, stati) in enumerate(COLONNE_UTILIZZO) for stato in stati}

    collegamenti = CollegamentoMTConnect.objects.select_related("asset").order_by("asset__name", "asset__asset_tag")
    if filtri.get("reparto"):
        collegamenti = collegamenti.filter(asset__reparto__icontains=filtri["reparto"])
    if filtri.get("macchina"):
        q = filtri["macchina"]
        collegamenti = collegamenti.filter(Q(asset__name__icontains=q) | Q(asset__asset_tag__icontains=q) | Q(codice__icontains=q))
    collegamenti = list(collegamenti[:500])
    secchi = {}  # collegamento -> [(chiave, da, a)]
    ore = {}     # (collegamento, chiave) -> [secondi per colonna]
    for coll in collegamenti:
        da_quando = max(inizio, coll.creato_il) if coll.creato_il else inizio
        secchi[coll.pk] = _secchi(da_quando, fine, raggruppa) if da_quando < fine else []
        for chiave, _da, _a in secchi[coll.pk]:
            ore[(coll.pk, chiave)] = [0.0] * len(COLONNE_UTILIZZO)
    inizi = {pk: [s[1] for s in elenco] for pk, elenco in secchi.items()}
    periodi = (PeriodoStatoMacchina.objects.filter(collegamento_id__in=list(secchi), dal__lt=fine)
               .filter(Q(al__isnull=True) | Q(al__gt=inizio)).values_list("collegamento_id", "stato", "dal", "al"))
    for coll_id, stato, p_dal, p_al in periodi.iterator():
        elenco = secchi.get(coll_id) or []
        colonna = colonna_di.get(stato)
        if colonna is None or not elenco:
            continue
        p_dal, p_al = max(p_dal, inizio), min(p_al or adesso, fine)
        i = max(bisect_right(inizi[coll_id], p_dal) - 1, 0)
        while i < len(elenco) and p_dal < p_al:
            chiave, s_da, s_a = elenco[i]
            pezzo = (min(p_al, s_a) - max(p_dal, s_da)).total_seconds()
            if pezzo > 0:
                ore[(coll_id, chiave)][colonna] += pezzo
            i += 1

    righe = []
    for coll in collegamenti:
        nome = f"{coll.asset.asset_tag} — {coll.asset.name}"
        for chiave, s_da, s_a in secchi[coll.pk]:
            secondi = ore[(coll.pk, chiave)]
            senza_dati = max((s_a - s_da).total_seconds() - sum(secondi), 0)
            h = [round(s / 3600, 1) for s in (*secondi, senza_dati)]
            accese = sum(secondi[:5])
            uso = round(100 * secondi[0] / accese, 1) if accese else 0.0
            righe.append([nome, _etichetta_secchio(chiave, raggruppa, dal, al), *h, uso])
        if len(righe) >= MAX_RIGHE:
            righe = righe[:MAX_RIGHE]
            break
    somma = tuple(range(2, 2 + len(COLONNE_UTILIZZO) + 1))
    totali = ["Totale", "", *[round(sum(r[i] for r in righe), 1) for i in somma]]
    accese_tot = sum(totali[2:7])
    totali.append(round(100 * totali[2] / accese_tot, 1) if accese_tot else 0.0)
    return RisultatoReport(
        f"Utilizzo delle CNC dal {dal:%d/%m/%Y} al {al:%d/%m/%Y}",
        ["Macchina", "Periodo", *[n for n, _s in COLONNE_UTILIZZO], "Senza dati h", "Utilizzo %"],
        righe, totali, somma=somma, troncato=len(righe) >= MAX_RIGHE,
        note=["Ore per stato dalle macchine collegate (collector OPC UA o agent MTConnect), divise ai confini del periodo. "
              "«Senza dati»: collector spento o macchina non ancora collegata. «Utilizzo %» = ore in lavoro sulle ore "
              "con la macchina accesa (escluse Offline e Senza dati)."],
    )


def _uno(valore) -> str:
    """Una cifra decimale all'italiana (1.234,5; 52 senza «,0»)."""
    valore = round(float(valore), 1)
    return _num(int(valore)) if valore.is_integer() else f"{valore:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _sintesi_utilizzo(righe):
    lavoro = sum(r[2] for r in righe)
    accese = sum(r[i] for r in righe for i in range(2, 7))
    per_macchina: dict = defaultdict(float)
    for r in righe:
        per_macchina[r[0]] += r[2]
    riepilogo = [("Ore in lavoro", _uno(lavoro)), ("Utilizzo sulle ore accese", f"{_uno(100 * lavoro / accese)} %" if accese else "—"),
                 ("Ore in allarme", _uno(sum(r[6] for r in righe))), ("Macchine", _num(len(per_macchina)))]
    return riepilogo, _barre("Ore in lavoro", [(k, round(v, 1)) for k, v in per_macchina.items()])


# ── 8. Qualità dei dati (schede incomplete) ──────────────────────────────────


def _qualita(filtri: dict) -> RisultatoReport:
    from django.db.models import Prefetch

    from ..forms import IT_DEVICE_TYPES
    from ..models import Asset, AssetCategoryField, AssetEndpoint

    tipi = dict(Asset.TYPE_CHOICES)
    stati = dict(Asset.STATUS_CHOICES)
    qs = Asset.objects.exclude(status=Asset.STATUS_RETIRED).select_related("asset_category")
    if filtri.get("asset_type"):
        qs = qs.filter(asset_type=filtri["asset_type"])
    if filtri.get("reparto"):
        qs = qs.filter(reparto__icontains=filtri["reparto"])
    qs = qs.prefetch_related(Prefetch("asset_category__category_fields",
                                      queryset=AssetCategoryField.objects.filter(is_active=True, is_required=True)))
    assets = list(qs.order_by("asset_tag")[:MAX_RIGHE])
    con_ip = set(AssetEndpoint.objects.exclude(ip__isnull=True).exclude(ip="").values_list("asset_id", flat=True).distinct())
    manca = (filtri.get("manca") or "").strip()
    righe = []
    for a in assets:
        campi = list(a.asset_category.category_fields.all()) if a.asset_category_id else []
        esito = a.completeness(category_fields=campi)
        mancanti = list(esito["missing"])
        if a.asset_type in IT_DEVICE_TYPES and a.pk not in con_ip:
            mancanti.append("Indirizzo IP")
        if not a.asset_category_id:
            mancanti.append("Categoria")
        if not mancanti or (manca and manca not in mancanti):
            continue
        righe.append([a.asset_tag, a.name, tipi.get(a.asset_type, a.asset_type), a.reparto,
                      stati.get(a.status, a.status), esito["pct"], len(mancanti), ", ".join(mancanti)])
    righe.sort(key=lambda r: (-r[6], r[0]))
    totali = [f"Totale {len(righe)} asset", f"su {len(assets)} controllati", "", "", "", "",
              sum(r[6] for r in righe), ""]
    return RisultatoReport(
        "Qualità dei dati: schede incomplete",
        ["Asset", "Nome", "Tipo", "Reparto", "Stato", "Completezza %", "Dati mancanti", "Cosa manca"],
        righe, totali, somma=(6,), troncato=len(assets) >= MAX_RIGHE,
        note=["Controlla nome, numero di serie, produttore, modello, reparto, data acquisto, assegnatario, "
              "categoria, i campi obbligatori della categoria e, per i dispositivi IT, l'indirizzo IP. "
              "Gli asset dismessi sono esclusi."],
    )


def _sintesi_qualita(righe):
    per_dato: dict = defaultdict(int)
    for r in righe:
        for voce in r[7].split(", "):
            if voce:
                per_dato[voce] += 1
    riepilogo = [("Schede incomplete", _num(len(righe))), ("Dati mancanti", _num(sum(r[6] for r in righe))),
                 ("Completezza media", (_num(round(sum(r[5] for r in righe) / len(righe))) + "%") if righe else "—")]
    return riepilogo, _barre("Asset per dato mancante", per_dato.items())


MANCA_CHOICES = [("", "Qualsiasi dato"), ("Numero di serie", "Numero di serie"), ("Assegnatario", "Assegnatario"),
                 ("Reparto", "Reparto"), ("Produttore", "Produttore"), ("Modello", "Modello"),
                 ("Data acquisto", "Data acquisto"), ("Categoria", "Categoria"), ("Indirizzo IP", "Indirizzo IP")]


def _fonte_choices():
    from ..models import AssetFieldHistory

    return [("", "Tutte")] + [c for c in AssetFieldHistory.FONTE_CHOICES if c[0] != AssetFieldHistory.FONTE_BASELINE]


def _type_choices():
    from ..models import Asset

    return [("", "Tutti")] + list(Asset.TYPE_CHOICES)


def _categoria_licenze_choices():
    from ..models import SoftwareLicense

    return [("", "Tutte")] + list(SoftwareLicense.CATEGORY_CHOICES)


def _kind_choices():
    from ..models import WorkOrder

    return [("", "Tutti")] + list(WorkOrder.KIND_CHOICES)


# ── Qualità e PART 145 ────────────────────────────────────────────────────────
# Gli stessi dati del Dossier PART 145 (services/part145_dossier.py), senza dati del
# personale: il catalogo è aperto a chi vede gli asset, i nominativi MOD.128 no.

ESITI_TARATURA = [("", "Qualsiasi"), ("Scaduta", "Scaduta"), ("Entro 30 giorni", "Entro 30 giorni"),
                  ("Valida", "Valida"), ("Nessuna taratura pianificata", "Nessuna taratura pianificata")]


def _part145_tarature(filtri: dict) -> RisultatoReport:
    from .part145_dossier import CLASSE_A_VISTA, CLASSE_MANUTENZIONE, CLASSE_TARATURA, _stato_scadenza, solo_attrezzature

    dati = solo_attrezzature()
    oggi = dati["oggi"]
    reparto = (filtri.get("reparto") or "").strip().lower()
    classe = filtri.get("classe") or ""
    esito = filtri.get("esito") or ""
    righe = []
    for a in dati["attrezzature"]:
        c = dati["controlli"][a.pk]
        if reparto and reparto not in (a.reparto or "").lower():
            continue
        if classe and c["classe"] != classe:
            continue
        stato = (_stato_scadenza(c["prossima"], oggi) if c["prossima"]
                 else ("Nessuna taratura pianificata" if c["classe"] == CLASSE_TARATURA else ""))
        if esito and stato != esito:
            continue
        righe.append([a.asset_tag, a.name, a.reparto, dati["stati_asset"].get(a.status, a.status), a.serial_number or "",
                      c["classe"], ", ".join(c["enti"]), c["ultima"], c["prossima"], stato])
    note = [f"Classi come il MOE §2.4: «{CLASSE_TARATURA}» (piano di taratura), «{CLASSE_MANUTENZIONE}» (altri piani), "
            f"«{CLASSE_A_VISTA}» (nessun piano: esame visivo prima dell'uso). Dismessi esclusi."]
    return RisultatoReport("Tarature attrezzature PART 145",
                           ["Asset", "Nome", "Reparto", "Stato", "Seriale", "Controllo", "Ente taratura", "Ultima taratura",
                            "Prossima taratura", "Esito"], righe[:MAX_RIGHE], note=note, troncato=len(righe) > MAX_RIGHE)


def _sintesi_part145_tarature(righe):
    scadute = sum(1 for r in righe if r[9] == "Scaduta")
    tarate = sum(1 for r in righe if r[5] == "Taratura")
    riepilogo = [("Attrezzature", _num(len(righe))), ("Con taratura", _num(tarate)), ("Tarature scadute", _num(scadute))]
    per_ente: dict = defaultdict(int)
    for r in righe:
        if r[5] == "Taratura":
            per_ente[r[6] or "Ente non indicato"] += 1
    return riepilogo, _barre("Strumenti per ente di taratura", per_ente.items())


def _part145_sezione(codice: str, filtri: dict):
    from .part145_dossier import costruisci

    giorni = int(filtri.get("giorni") or 90) if str(filtri.get("giorni") or "90").isdigit() else 90
    dati = costruisci(con_personale=False, giorni=max(1, min(giorni, 365)))
    return next(s for s in dati["sezioni"] if s.codice == codice)


def _part145_da_sistemare(filtri: dict) -> RisultatoReport:
    sezione = _part145_sezione("aperte", filtri)
    priorita = filtri.get("priorita") or ""
    tipo = (filtri.get("tipo") or "").strip().lower()
    righe = [r for r in sezione.righe if (not priorita or r[0] == priorita) and (not tipo or tipo in r[1].lower())]
    return RisultatoReport("PART 145 — da sistemare", sezione.intestazioni, righe,
                           note=["Le stesse situazioni aperte del Dossier PART 145, senza i dati del personale MOD.128."])


def _sintesi_part145_da_sistemare(righe):
    alte = sum(1 for r in righe if r[0] == "Alta")
    riepilogo = [("Situazioni aperte", _num(len(righe))), ("Priorità alta", _num(alte)), ("Priorità media", _num(len(righe) - alte))]
    return riepilogo, _barre("Situazioni per tipo", _conta(righe, 1).items())


def _part145_scadenze(filtri: dict) -> RisultatoReport:
    sezione = _part145_sezione("scadenze", filtri)
    tipo = filtri.get("tipo") or ""
    righe = [r for r in sezione.righe if not tipo or r[1] == tipo]
    return RisultatoReport(sezione.titolo.replace("Scadenze", "PART 145 — scadenze", 1), sezione.intestazioni, righe,
                           note=["Processi, contratti e requisiti, tarature e manutenzioni delle attrezzature PART 145."])


def _sintesi_part145_scadenze(righe):
    scadute = sum(1 for r in righe if r[4] == "Scaduta")
    riepilogo = [("Scadenze", _num(len(righe))), ("Già scadute", _num(scadute)),
                 ("Entro 30 giorni", _num(sum(1 for r in righe if r[4] == "Entro 30 giorni")))]
    return riepilogo, _barre("Scadenze per tipo", _conta(righe, 1).items())


GIORNI_CHOICES = [("90", "90 giorni"), ("30", "30 giorni"), ("60", "60 giorni"), ("180", "180 giorni"), ("365", "Un anno")]
TIPI_SCADENZA_CHOICES = [("", "Qualsiasi"), ("Contratto", "Contratto"), ("Processo", "Processo"),
                         ("Requisito di processo", "Requisito di processo"), ("Taratura", "Taratura"),
                         ("Manutenzione", "Manutenzione")]
PRIORITA_CHOICES = [("", "Qualsiasi"), ("Alta", "Alta"), ("Media", "Media")]
CLASSI_CHOICES = [("", "Qualsiasi"), ("Taratura", "Taratura"), ("Manutenzione periodica", "Manutenzione periodica"),
                  ("A vista", "A vista")]


def definizioni() -> "OrderedDict[str, DefinizioneReport]":
    return OrderedDict((d.code, d) for d in (
        DefinizioneReport(
            "inventario-stato-reparto", "Inventario per stato e reparto",
            "Quanti asset ci sono in ogni reparto, divisi per stato (in uso, in riparazione, in magazzino, dismessi).",
            "CED · In uso 42 · In riparazione 1 · In magazzino 3 · Dismesso 0 · Totale 46",
            [Filtro("reparto", "Reparto contiene"), Filtro("asset_type", "Tipo", "select", _type_choices()),
             Filtro("stato", "Stato", "select", _status_choices())],
            _inventario, "Inventario", _sintesi_inventario,
        ),
        DefinizioneReport(
            "qualita-dati", "Qualità dei dati: schede incomplete",
            "Gli asset a cui mancano dati (numero di serie, assegnatario, reparto, categoria, campi obbligatori, "
            "IP per i dispositivi IT), dal più incompleto: la lista di cose da sistemare.",
            "PC-0042 · Notebook ufficio · Completezza 63% · 3 dati mancanti · Numero di serie, Assegnatario, Indirizzo IP",
            [Filtro("asset_type", "Tipo", "select", _type_choices()), Filtro("reparto", "Reparto contiene"),
             Filtro("manca", "Manca", "select", MANCA_CHOICES)],
            _qualita, "Inventario", _sintesi_qualita,
        ),
        DefinizioneReport(
            "part145-tarature", "PART 145 — tarature delle attrezzature",
            "Le attrezzature PART 145 con la classe di controllo del MOE §2.4 (taratura, manutenzione periodica, a "
            "vista), l'ente che le tara, l'ultima e la prossima taratura: anche l'elenco da comunicare "
            "all'organizzazione di manutenzione.",
            "P145-0007 · Chiave dinamometrica · Aggiustaggio · Taratura · Laboratorio LAT · 12/11/2025 · 12/11/2026 · Valida",
            [Filtro("reparto", "Reparto contiene"), Filtro("classe", "Controllo", "select", CLASSI_CHOICES),
             Filtro("esito", "Esito", "select", ESITI_TARATURA)],
            _part145_tarature, "Qualità e PART 145", _sintesi_part145_tarature,
        ),
        DefinizioneReport(
            "part145-da-sistemare", "PART 145 — da sistemare",
            "Le situazioni aperte del Dossier PART 145, prima quelle a priorità alta: tarature e contratti scaduti, "
            "processi senza scadenza o senza persone, attrezzature in riparazione o incomplete, OdL aperti.",
            "Alta · Taratura scaduta · P145-0007 — Chiave dinamometrica · scaduta il 17/10/2026",
            [Filtro("priorita", "Priorità", "select", PRIORITA_CHOICES), Filtro("tipo", "Tipo contiene")],
            _part145_da_sistemare, "Qualità e PART 145", _sintesi_part145_da_sistemare,
        ),
        DefinizioneReport(
            "part145-scadenze", "PART 145 — scadenze",
            "Tutto quello che scade nella finestra scelta (e quello già scaduto): contratto quadro e requisiti dei "
            "processi, processi, tarature e manutenzioni delle attrezzature.",
            "31/12/2026 · Contratto · Contratto quadro · Riparazione componenti · Entro 90 giorni",
            [Filtro("giorni", "Finestra", "select", GIORNI_CHOICES, "90"),
             Filtro("tipo", "Tipo", "select", TIPI_SCADENZA_CHOICES)],
            _part145_scadenze, "Qualità e PART 145", _sintesi_part145_scadenze,
        ),
        DefinizioneReport(
            "parco-it-rete", "Parco IT e rete",
            "Un elenco di tutte le interfacce di rete: IP, MAC, VLAN, switch e porta di ogni dispositivo IT, con i "
            "problemi trovati (IP duplicati, switch non riconosciuto, dispositivi senza rete).",
            "PC-0042 · Notebook ufficio · CED · 192.0.2.10 · VLAN 10 · IT-SW-01 · A0.1.12",
            [Filtro("reparto", "Reparto contiene"), Filtro("asset_type", "Tipo", "select", _type_choices()),
             Filtro("switch", "Switch", "select", _switch_choices()), Filtro("vlan", "VLAN"),
             Filtro("problema", "Controllo", "select", PROBLEMI_RETE)],
            _parco_it, "IT e rete", _sintesi_parco_it,
        ),
        DefinizioneReport(
            "licenze-software", "Licenze software",
            "Licenze con assegnazione, posti usati e totali, scadenza e stato (attiva, in scadenza entro 60 giorni, "
            "scaduta).",
            "Office · Microsoft 365 Business · PC-0042 · 1/1 posti · 31/12/2026 · Attiva",
            [Filtro("categoria", "Categoria", "select", _categoria_licenze_choices()),
             Filtro("stato", "Stato", "select", [("", "Attive"), ("in_scadenza", "In scadenza (60 giorni)"),
                                                 ("scadute", "Scadute"), ("tutte", "Tutte, anche disattivate")]),
             Filtro("reparto", "Reparto contiene")],
            _licenze, "IT e rete", _sintesi_licenze,
        ),
        DefinizioneReport(
            "costi-manutenzione", "Costi e ore di manutenzione",
            "Ordini di lavoro chiusi nel periodo raggruppati per asset, reparto, tipo di intervento, fornitore o mese: "
            "numero di interventi, ore di intervento e di fermo, costi di manodopera e materiali.",
            "Officina · 14 interventi · 9 preventivi · 5 correttivi · 21,5 ore fermo · 3.240,00 €",
            [Filtro("dal", "Dal", "date"), Filtro("al", "Al", "date"),
             Filtro("raggruppa", "Raggruppa per", "select", RAGGRUPPA_COSTI),
             Filtro("kind", "Tipo di intervento", "select", _kind_choices()), Filtro("reparto", "Reparto contiene")],
            _costi, "Manutenzione e scadenze", _sintesi_costi,
        ),
        DefinizioneReport(
            "utilizzo-cnc", "Utilizzo delle CNC",
            "Per ogni macchina collegata (collector OPC UA o agent MTConnect): ore in lavoro, in MDI/manuale, ferma, "
            "interrotta, in allarme, offline e senza dati nel periodo, e l'utilizzo sulle ore con la macchina accesa. "
            "Per macchina oppure giorno per giorno, per settimana o per mese.",
            "CNC-DM6 — Fresa DMC 125 · 31,5 h in lavoro · 2,0 h MDI · 4,0 h ferma · 0,5 h in allarme · utilizzo 83,6%",
            [Filtro("dal", "Dal", "date"), Filtro("al", "Al", "date"),
             Filtro("raggruppa", "Raggruppa per", "select", RAGGRUPPA_UTILIZZO),
             Filtro("macchina", "Macchina contiene"), Filtro("reparto", "Reparto contiene")],
            _utilizzo, "Officina", _sintesi_utilizzo,
        ),
        DefinizioneReport(
            "mfc-pagine-consumabili", "MFC: pagine stampate e consumabili",
            "Per ogni multifunzione: pagine B/N e colore nel periodo dalle letture mensili, consumabile più basso, "
            "giorni stimati all'esaurimento e data dell'ultima lettura.",
            "Amministrazione · MAT-123 · 4.210 B/N · 380 colore · Toner nero 12% · ~9 giorni",
            [Filtro("dal", "Dal mese", "month"), Filtro("al", "Al mese", "month"), Filtro("reparto", "Reparto contiene")],
            _mfc, "Stampanti e contatori", _sintesi_mfc,
        ),
        DefinizioneReport(
            "scadenze", "Scadenze di manutenzione, amministrative e garanzie",
            "Manutenzioni aperte, scadenze amministrative attive e garanzie in scadenza nel periodo, con stato.",
            "15/11/2026 · Garanzia · PC-0042 · Notebook ufficio · Garanzia 36 mesi · In scadenza",
            [Filtro("dal", "Dal", "date"), Filtro("al", "Al", "date"), Filtro("reparto", "Reparto contiene"),
             Filtro("tipo", "Tipo", "select", [("", "Tutti"), ("manutenzione", "Manutenzione"),
                                               ("amministrativa", "Amministrativa"), ("garanzia", "Garanzia")])],
            _scadenze, "Manutenzione e scadenze", _sintesi_scadenze,
        ),
        DefinizioneReport(
            "modifiche-rete-assegnazioni", "Modifiche di rete e assegnazioni",
            "Cosa è cambiato nel periodo (IP, switch, porte, patch panel, assegnatario, ubicazione), "
            "con autore e fonte, dallo storico campi degli asset.",
            "09/10/2026 14:02 · PC-0042 · IP · 192.0.2.10 → 192.0.2.11 · Rossi · Utente (scheda)",
            [Filtro("dal", "Dal", "date"), Filtro("al", "Al", "date"),
             Filtro("gruppo", "Gruppo", "select", [("", "Rete e assegnazioni"), ("rete", "Rete"),
                                                   ("assegnazione", "Assegnazione"), ("stato", "Stato")]),
             Filtro("fonte", "Fonte", "select", _fonte_choices()), Filtro("reparto", "Reparto contiene")],
            _modifiche, "IT e rete", _sintesi_modifiche,
        ),
    ))


def definizioni_per_area() -> list[tuple[str, list]]:
    gruppi: dict = OrderedDict((a, []) for a in AREE)
    for d in definizioni().values():
        gruppi.setdefault(d.area, []).append(d)
    for r in report_esistenti():
        gruppi.setdefault(r["area"], []).append(r)
    return [(area, voci) for area, voci in gruppi.items() if voci]


def report_esistenti() -> list[dict]:
    """Report gia' presenti nel modulo, censiti nel catalogo (link, filtri, output)."""
    return [
        {"titolo": "Reportistica manutenzione", "url": reverse("assets:reports"),
         "descrizione": "KPI di manutenzione (PM compliance, budget, costi per categoria).", "filtri": "Ambito, mese",
         "output": "Pagina con grafici", "area": "Manutenzione e scadenze"},
        {"titolo": "Archivio report programmati", "url": reverse("assets:reporting_archive"),
         "descrizione": "Snapshot inventario pianificati dalle Impostazioni, con PDF/Excel immutabili e trend.",
         "filtri": "Tipo, categoria, reparto, SNMP", "output": "PDF, Excel", "area": "Inventario"},
        {"titolo": "Scadenzario manutenzione", "url": reverse("assets:maintenance_scadenze"),
         "descrizione": "Scadenze di manutenzione per finestra, piano, gruppo, fornitore.",
         "filtri": "Finestra, piano, gruppo, asset, reparto, tipo, fornitore", "output": "Pagina, Excel, PDF", "area": "Manutenzione e scadenze"},
        {"titolo": "Dossier PART 145", "url": reverse("assets:part_145_list"),
         "descrizione": "Processi del perimetro, contratti, attrezzature con tarature, personale e formazione "
                        "(MOD.128), audit, NC Part 145, scadenze, situazioni da sistemare e documenti SGI.",
         "filtri": "Ricerca libera", "output": "Pagina, Excel (un foglio per sezione), PDF", "area": "Qualità e PART 145"},
        {"titolo": "Controllo semestrale attrezzature PART 145", "url": reverse("assets:part_145_export_controllo"),
         "descrizione": "Una pagina per reparto con le attrezzature da controllare a gennaio e giugno, da timbrare e "
                        "firmare (MT CN 17, Mod.072).",
         "filtri": "Nessuno", "output": "PDF", "area": "Qualità e PART 145"},
        {"titolo": "Export elenco asset", "url": reverse("assets:asset_list"),
         "descrizione": "Elenco asset con i filtri della lista (pulsante Esporta).",
         "filtri": "Ricerca, tipo, categoria, reparto, VLAN, IP", "output": "Excel", "area": "Inventario"},
        {"titolo": "Scheda asset PDF", "url": "", "descrizione": "Report del singolo asset dalla sua scheda.",
         "filtri": "Asset", "output": "PDF", "area": "Inventario"},
        {"titolo": "Manutenzione mensile macchine", "url": "",
         "descrizione": "PDF mensile delle manutenzioni macchine di lavoro (dalla Reportistica).", "filtri": "Mese",
         "output": "PDF", "area": "Manutenzione e scadenze"},
    ]


def filtri_da_richiesta(definizione: DefinizioneReport, data) -> dict:
    out = {}
    for f in definizione.filtri:
        valore = (data.get(f.nome) or "").strip()[:120]
        if f.tipo == "select" and valore not in {c[0] for c in f.scelte}:
            valore = ""
        if valore:
            out[f.nome] = valore
    return out


def etichetta_filtri(definizione: DefinizioneReport, filtri: dict) -> str:
    parti = []
    for f in definizione.filtri:
        if f.nome in filtri:
            valore = filtri[f.nome]
            if f.tipo == "select":
                valore = dict(f.scelte).get(valore, valore)
            parti.append(f"{f.etichetta}: {valore}")
    return " · ".join(parti) or "Nessun filtro"


# ── Vista: ricerca libera, ordinamento e colonne (uguali in pagina ed export) ──


def vista_da_richiesta(data) -> dict:
    """Ricerca, colonne e ordinamento da querystring/POST o dal report salvato (chiave ``_vista``)."""
    if data is None:
        return {}
    colonne = data.getlist("col") if hasattr(data, "getlist") else (data.get("col") or [])
    vista = {
        "cerca": str(data.get("cerca") or "").strip()[:120],
        "col": sorted({int(c) for c in colonne if str(c).isdigit() and len(str(c)) < 4}),
        "ordina": int(data["ordina"]) if str(data.get("ordina") or "").isdigit() and len(str(data["ordina"])) < 4 else None,
        "verso": "desc" if data.get("verso") == "desc" else "asc",
    }
    return {k: v for k, v in vista.items() if v not in ("", [], None) and not (k == "verso" and v == "asc")}


def ha_vista(data) -> bool:
    return any(k in data for k in ("cerca", "col", "ordina", "verso"))


_DATA_IT = re.compile(r"^(\d{2})/(\d{2})/(\d{4})(?: (\d{2}):(\d{2}))?$")


def _chiave(valore):
    if isinstance(valore, bool):
        return (1, 0, str(valore))
    if isinstance(valore, (int, float, Decimal)):
        return (0, float(valore), "")
    if isinstance(valore, date):
        return (0, float(valore.toordinal()), "")
    testo = str(valore)
    m = _DATA_IT.match(testo)
    if m:
        g, mese, anno, ora, minuto = m.groups()
        return (0, float(f"{anno}{mese}{g}{ora or '00'}{minuto or '00'}"), "")
    return (1, 0, testo.casefold())


def applica_vista(definizione: DefinizioneReport, risultato: RisultatoReport, vista: dict) -> RisultatoReport:
    n = len(risultato.intestazioni)
    righe = list(risultato.righe)
    totali = list(risultato.totali) if risultato.totali else None
    cerca = (vista.get("cerca") or "").casefold()
    if cerca:
        parole = cerca.split()
        righe = [r for r in righe if all(any(p in str(v).casefold() for v in r) for p in parole)]
        totali = [""] * n
        totali[0] = f"Totale {len(righe)} righe"
        for i in risultato.somma:
            totali[i] = round(sum(r[i] for r in righe if isinstance(r[i], (int, float, Decimal))), 2)
    riepilogo, grafico = definizione.sintesi(righe) if definizione.sintesi else ([], None)
    ordina = vista.get("ordina")
    if ordina is not None and 0 <= ordina < n:
        piene = [r for r in righe if r[ordina] not in (None, "")]
        vuote = [r for r in righe if r[ordina] in (None, "")]
        piene.sort(key=lambda r: _chiave(r[ordina]), reverse=vista.get("verso") == "desc")
        righe = piene + vuote
    idx = [i for i in (vista.get("col") or []) if 0 <= i < n] or list(range(n))
    righe = [[r[i] for i in idx] for r in righe]
    numeriche = [pos for pos, i in enumerate(idx)
                 if any(isinstance(r[pos], (int, float, Decimal)) and not isinstance(r[pos], bool) for r in righe)]
    return RisultatoReport(
        titolo=risultato.titolo, intestazioni=[risultato.intestazioni[i] for i in idx], righe=righe,
        totali=[totali[i] for i in idx] if totali else None, note=risultato.note, troncato=risultato.troncato,
        somma=risultato.somma, riepilogo=riepilogo, grafico=grafico, colonne_idx=idx,
        intestazioni_tutte=list(risultato.intestazioni),
    ), numeriche


def esegui(definizione: DefinizioneReport, filtri: dict, vista: dict | None = None):
    """Esegue il report e applica la vista: ``(risultato, colonne_numeriche)``."""
    return applica_vista(definizione, definizione.esegui(filtri), vista or {})


def etichetta_vista(definizione: DefinizioneReport, vista: dict, risultato: RisultatoReport | None = None) -> str:
    parti = []
    if vista.get("cerca"):
        parti.append(f"Ricerca: «{vista['cerca']}»")
    if vista.get("col") and risultato is not None and len(risultato.intestazioni) < len(risultato.intestazioni_tutte):
        parti.append(f"{len(risultato.intestazioni)} colonne su {len(risultato.intestazioni_tutte)}")
    if vista.get("ordina") is not None and risultato is not None:
        tutte = risultato.intestazioni_tutte or risultato.intestazioni
        nome = tutte[vista["ordina"]] if vista["ordina"] < len(tutte) else ""
        if nome:
            parti.append(f"Ordinato per {nome}{' (decrescente)' if vista.get('verso') == 'desc' else ''}")
    return " · ".join(parti)


def intestazione_estrazione(utente=None, quando: datetime | None = None) -> str:
    quando = timezone.localtime(quando or timezone.now())
    chi = ""
    if utente is not None and getattr(utente, "is_authenticated", False):
        chi = f" da {utente.get_full_name() or utente.get_username()}"
    return f"Estratto il {quando:%d/%m/%Y %H:%M}{chi}"


def ha_accesso(code: str, utente) -> bool:
    """L'utente vede la pagina del report? Stessa politica dell'ACLMiddleware, fail-closed."""
    from core.middleware import acl_allows_path

    if not getattr(utente, "is_active", False):
        return False
    try:
        return bool(acl_allows_path(reverse("assets:report_catalog_run", args=[code]), django_user=utente)) \
            and accesso_extra(code, utente)
    except Exception:
        return False  # un errore ACL non manda dati via email


def destinatario_ammesso(code: str, utente) -> bool:
    return bool((getattr(utente, "email", "") or "").strip()) and ha_accesso(code, utente)


#: Report che mostrano dati di altri moduli: serve anche la consultazione di quel modulo.
ACCESSI_EXTRA = {"mfc-pagine-consumabili": "contatori:consumabili", "licenze-software": "assets:software_license_list",
                 "costi-manutenzione": "assets:wo_list", "utilizzo-cnc": "assets:mtconnect_collegamenti"}


def accesso_extra(code: str, utente) -> bool:
    route = ACCESSI_EXTRA.get(code)
    if not route:
        return True
    from core.middleware import acl_allows_path

    try:
        return bool(acl_allows_path(reverse(route), django_user=utente))
    except Exception:
        return False


def puo_pianificare(utente) -> bool:
    """Il proprietario puo' ancora pianificare invii? Ricontrollato a ogni invio dal job."""
    from types import SimpleNamespace

    from ..views_report_catalog import can_schedule_email

    try:
        return bool(getattr(utente, "is_active", False) and can_schedule_email(SimpleNamespace(user=utente)))
    except Exception:
        return False


def prossimo_invio(frequenza: str, dopo: datetime | None = None) -> datetime | None:
    """Prossimo invio alle 07:00 locali (giornaliero, lunedi', primo del mese)."""
    if not frequenza:
        return None
    adesso = timezone.localtime(dopo or timezone.now())
    base = adesso.replace(hour=7, minute=0, second=0, microsecond=0)
    if frequenza == "DAILY":
        candidato = base if base > adesso else base + timedelta(days=1)
    elif frequenza == "WEEKLY":
        candidato = base + timedelta(days=(7 - base.weekday()) % 7)
        if candidato <= adesso:
            candidato += timedelta(days=7)
    else:
        candidato = base.replace(day=1)
        if candidato <= adesso:
            candidato = (candidato + timedelta(days=32)).replace(day=1)
    return candidato


def invia_report_pianificati(ora: datetime | None = None) -> dict:
    """Job django-q: invia i report salvati in scadenza ai soli destinatari ammessi.

    1) claim breve sotto lock (avanza ``prossimo_invio``: nessun doppio invio anche con
    piu' worker); 2) generazione e invio fuori transazione; 3) esito con un update.
    Un errore su un report non blocca gli altri e non lascia il piano incastrato.
    """
    from django.db import transaction

    from core.email_utils import send_hub_mail

    from ..models import AssetSavedReport

    ora = ora or timezone.now()
    defs = definizioni()
    inviati = errori = 0

    def esito(pk, testo, **extra):
        AssetSavedReport.objects.filter(pk=pk).update(ultimo_esito=testo[:255], **extra)

    for pk in AssetSavedReport.objects.filter(prossimo_invio__lte=ora).exclude(frequenza="").values_list("pk", flat=True)[:50]:
        with transaction.atomic():
            salvato = AssetSavedReport.objects.select_for_update().filter(pk=pk, prossimo_invio__lte=ora).first()
            if salvato is None:
                continue  # preso da un altro worker
            salvato.prossimo_invio = prossimo_invio(salvato.frequenza, ora)
            salvato.ultimo_invio = ora
            salvato.save(update_fields=["prossimo_invio", "ultimo_invio", "updated_at"])
        try:
            definizione = defs.get(salvato.report_code)
            # Anche il proprietario deve avere ancora accesso e permesso di invio.
            if definizione is None or not ha_accesso(salvato.report_code, salvato.owner) \
                    or not puo_pianificare(salvato.owner):
                esito(pk, "Sospeso: report non disponibile, proprietario senza accesso o senza permesso di invio.",
                      frequenza="", prossimo_invio=None)
                errori += 1
                continue
            destinatari = [u for u in salvato.destinatari.all() if destinatario_ammesso(salvato.report_code, u)]
            if not destinatari:
                esito(pk, "Nessun destinatario con accesso al report: invio saltato.")
                continue
            filtri = filtri_da_richiesta(definizione, salvato.filtri or {})
            vista = vista_da_richiesta((salvato.filtri or {}).get("_vista") or {})
            risultato, _ = esegui(definizione, filtri, vista)
            data, nome, ctype = esporta(definizione, risultato, filtri, salvato.formato, salvato.owner, vista)
            send_hub_mail(
                f"Report asset: {salvato.nome}",
                f"In allegato il report «{salvato.nome}» ({definizione.titolo}).\n"
                f"Filtri: {etichetta_filtri(definizione, filtri)}\n{intestazione_estrazione()}",
                [u.email for u in destinatari],
                title=salvato.nome, email_type="Report asset", attachments=[(nome, data, ctype)],
            )
            esito(pk, f"Inviato a {len(destinatari)} destinatari.")
            inviati += 1
        except Exception:
            # Dettagli tecnici (host, indirizzi) solo nel log: l'esito e' visibile a chi vede il report.
            logger.exception("Invio report pianificato %s fallito", pk)
            esito(pk, "Errore durante l'invio: dettagli nel log del portale.")
            errori += 1
    return {"inviati": inviati, "errori": errori}


def _riga_export(riga):
    return [v.strftime("%d/%m/%Y") if isinstance(v, date) else v for v in riga]


def esporta(definizione: DefinizioneReport, risultato: RisultatoReport, filtri: dict, formato: str, utente=None,
            vista: dict | None = None) -> tuple[bytes, str, str]:
    """Bytes, nome file e content type. Data di estrazione, filtri e riepilogo stampati nel file."""
    from core.excel_export import build_xlsx_bytes
    from core.table_pdf import render_table_pdf

    estrazione = intestazione_estrazione(utente)
    filtri_txt = etichetta_filtri(definizione, filtri)
    extra = etichetta_vista(definizione, vista or {}, risultato)
    if extra:
        filtri_txt += f" · {extra}"
    if risultato.riepilogo:
        estrazione += " · " + " · ".join(f"{e}: {v}" for e, v in risultato.riepilogo)
    righe = [_riga_export(r) for r in risultato.righe]
    if risultato.totali:
        righe.append(_riga_export(risultato.totali))
    nome = f"{definizione.code}-{timezone.localdate():%Y%m%d}"
    if formato == "pdf":
        sottotitolo = f"{estrazione} · Filtri: {filtri_txt}"
        if risultato.troncato:
            sottotitolo += f" · Limitato alle prime {MAX_RIGHE} righe"
        data = render_table_pdf(title=risultato.titolo, headers=risultato.intestazioni, rows=righe, subtitle=sottotitolo)
        return data, f"{nome}.pdf", "application/pdf"
    data = build_xlsx_bytes(columns=risultato.intestazioni, rows=righe, sheet_title="Report",
                            title=risultato.titolo, subtitle=estrazione, filters_label=f"Filtri: {filtri_txt}")
    return data, f"{nome}.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
