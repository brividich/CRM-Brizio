"""Catalogo report del modulo asset (PROMPT 06 - D).

Ogni report e' una funzione ``esegui(filtri) -> RisultatoReport`` con intestazioni,
righe e una riga di totali calcolata dalle stesse righe: pagina, Excel e PDF usano
lo stesso risultato, quindi i totali coincidono per costruzione (e un test lo verifica).

Il catalogo elenca anche i report gia' esistenti nel modulo, con il loro link.
"""
from __future__ import annotations

import logging
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

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


@dataclass
class DefinizioneReport:
    code: str
    titolo: str
    descrizione: str
    esempio: str
    filtri: list[Filtro]
    esegui: callable


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
    return RisultatoReport("Inventario per stato e reparto", ["Reparto", *[l for _, l in stati], "Totale"], righe, totali)


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
    )


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
         _visualizza(h.campo, h.valore_dopo), h.autore_display, fonti.get(h.fonte, h.fonte)]
        for h in qs.select_related("asset").order_by("-cambiato_il", "-id")[:MAX_RIGHE]
    ]
    asset_distinti = len({r[1] for r in righe})
    totali = [f"Totale {len(righe)} modifiche", f"{asset_distinti} asset", "", "", "", "", "", "", ""]
    return RisultatoReport(f"Modifiche rete e assegnazioni dal {dal:%d/%m/%Y} al {al:%d/%m/%Y}",
                           ["Quando", "Asset", "Nome", "Campo", "Punto rete", "Prima", "Dopo", "Chi", "Fonte"],
                           righe, totali, troncato=len(righe) >= MAX_RIGHE)


def _fonte_choices():
    from ..models import AssetFieldHistory

    return [("", "Tutte")] + [c for c in AssetFieldHistory.FONTE_CHOICES if c[0] != AssetFieldHistory.FONTE_BASELINE]


def _type_choices():
    from ..models import Asset

    return [("", "Tutti")] + list(Asset.TYPE_CHOICES)


def definizioni() -> "OrderedDict[str, DefinizioneReport]":
    return OrderedDict((d.code, d) for d in (
        DefinizioneReport(
            "inventario-stato-reparto", "Inventario per stato e reparto",
            "Quanti asset ci sono in ogni reparto, divisi per stato (in uso, in riparazione, in magazzino, dismessi).",
            "CED · In uso 42 · In riparazione 1 · In magazzino 3 · Dismesso 0 · Totale 46",
            [Filtro("reparto", "Reparto contiene"), Filtro("asset_type", "Tipo", "select", _type_choices()),
             Filtro("stato", "Stato", "select", _status_choices())],
            _inventario,
        ),
        DefinizioneReport(
            "mfc-pagine-consumabili", "MFC: pagine stampate e consumabili",
            "Per ogni multifunzione: pagine B/N e colore nel periodo dalle letture mensili, consumabile più basso, "
            "giorni stimati all'esaurimento e data dell'ultima lettura.",
            "Amministrazione · MAT-123 · 4.210 B/N · 380 colore · Toner nero 12% · ~9 giorni",
            [Filtro("dal", "Dal mese", "month"), Filtro("al", "Al mese", "month"), Filtro("reparto", "Reparto contiene")],
            _mfc,
        ),
        DefinizioneReport(
            "scadenze", "Scadenze di manutenzione, amministrative e garanzie",
            "Manutenzioni aperte, scadenze amministrative attive e garanzie in scadenza nel periodo, con stato.",
            "15/11/2026 · Garanzia · PC-0042 · Notebook ufficio · Garanzia 36 mesi · In scadenza",
            [Filtro("dal", "Dal", "date"), Filtro("al", "Al", "date"), Filtro("reparto", "Reparto contiene"),
             Filtro("tipo", "Tipo", "select", [("", "Tutti"), ("manutenzione", "Manutenzione"),
                                               ("amministrativa", "Amministrativa"), ("garanzia", "Garanzia")])],
            _scadenze,
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
            _modifiche,
        ),
    ))


def report_esistenti() -> list[dict]:
    """Report gia' presenti nel modulo, censiti nel catalogo (link, filtri, output)."""
    return [
        {"titolo": "Reportistica manutenzione", "url": reverse("assets:reports"),
         "descrizione": "KPI di manutenzione (PM compliance, budget, costi per categoria).", "filtri": "Ambito, mese",
         "output": "Pagina con grafici"},
        {"titolo": "Archivio report programmati", "url": reverse("assets:reporting_archive"),
         "descrizione": "Snapshot inventario pianificati dalle Impostazioni, con PDF/Excel immutabili e trend.",
         "filtri": "Tipo, categoria, reparto, SNMP", "output": "PDF, Excel"},
        {"titolo": "Scadenzario manutenzione", "url": reverse("assets:maintenance_scadenze"),
         "descrizione": "Occorrenze di manutenzione per finestra, piano, gruppo, fornitore.",
         "filtri": "Finestra, piano, gruppo, asset, reparto, tipo, fornitore", "output": "Pagina, Excel, PDF"},
        {"titolo": "Export elenco asset", "url": reverse("assets:asset_list"),
         "descrizione": "Elenco asset con i filtri della lista (pulsante Esporta).",
         "filtri": "Ricerca, tipo, categoria, reparto, VLAN, IP", "output": "Excel"},
        {"titolo": "Scheda asset PDF", "url": "", "descrizione": "Report del singolo asset dalla sua scheda.",
         "filtri": "Asset", "output": "PDF"},
        {"titolo": "Manutenzione mensile macchine", "url": "",
         "descrizione": "PDF mensile delle manutenzioni macchine di lavoro (dalla Reportistica).", "filtri": "Mese",
         "output": "PDF"},
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
ACCESSI_EXTRA = {"mfc-pagine-consumabili": "contatori:consumabili"}


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
            risultato = definizione.esegui(filtri)
            data, nome, ctype = esporta(definizione, risultato, filtri, salvato.formato, salvato.owner)
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


def esporta(definizione: DefinizioneReport, risultato: RisultatoReport, filtri: dict, formato: str, utente=None) -> tuple[bytes, str, str]:
    """Bytes, nome file e content type. Data di estrazione e filtri stampati nel file."""
    from core.excel_export import build_xlsx_bytes
    from core.table_pdf import render_table_pdf

    estrazione = intestazione_estrazione(utente)
    filtri_txt = etichetta_filtri(definizione, filtri)
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
