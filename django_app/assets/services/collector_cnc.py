"""Collector OPC UA delle CNC gestito dal portale: token, rete ammessa, macchine da leggere.

Due modalità, scelte nella stessa pagina (``modalita``): **sul server del portale** il collector gira
dentro il portale (``manage.py collector_cnc``, attività di Windows all'avvio) e scrive direttamente
nel database; **su un PC dell'officina** parla con il portale via HTTP con il suo token. Una esclude
l'altra: con il collector sul server, l'elenco dato al PC è vuoto.

Tutto da «Asset › Configurazione › Macchine collegate» (amministratori del modulo Asset):

- **token del collector** (``MeterIngestClient``): creato o rigenerato qui, mostrato una volta
  sola; a DB solo l'hash. Ogni collector ha i suoi **IP ammessi** (oltre a quelli del .env);
- **macchine** (``CollegamentoMTConnect`` con fonte ``collector_opcua``): host e porta OPC UA,
  codice breve (es. DM6), utente e password OPC UA facoltativi (password cifrata con
  ``secret_box``). Il collector le scarica da ``GET /api/assets/contatori/ingest/config/``:
  sul suo PC restano solo indirizzo del portale e token;
- **ricerca in rete** (``cerca_macchine``), **unità delle ore** della CNC (il portale converte dal valore
  grezzo), **avviso a ore** non bloccante e asset **CNC da sistemare** (senza scheda macchina).
"""
from __future__ import annotations

import ipaddress
import re
from decimal import Decimal

from django.utils import timezone

PURPOSE_OPCUA = "opcua-collector"
_HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]{0,252}$")
_CODICE_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,40}$")


# --- password OPC UA ---------------------------------------------------------------------------

def cifra(password: str) -> str:
    from security.services import secret_box

    return secret_box.encrypt(password, PURPOSE_OPCUA) if password else ""


def decifra(valore: str) -> str:
    from security.services import secret_box

    return secret_box.decrypt(valore, PURPOSE_OPCUA) if valore else ""


# --- validazioni -------------------------------------------------------------------------------

def valida_ips(testo: str) -> tuple[list[str], list[str]]:
    """(voci valide, errori) da un elenco di IP o reti CIDR separati da virgole, spazi o a capo."""
    voci, errori = [], []
    for voce in [v for v in re.split(r"[\s,;]+", testo or "") if v]:
        try:
            ipaddress.ip_network(voce, strict=False) if "/" in voce else ipaddress.ip_address(voce)
        except ValueError:
            errori.append(f"«{voce}» non è un IP o una rete (es. 192.168.23.50 o 192.168.23.0/24).")
            continue
        voci.append(voce)
    return voci[:50], errori


def avvisi_ips(voci) -> list[str]:
    """Voci valide ma probabilmente sbagliate: un indirizzo che finisce per .0 senza «/24» ammette solo sé stesso."""
    avvisi = []
    for voce in voci:
        if "/" not in voce and voce.count(".") == 3 and voce.endswith(".0"):
            avvisi.append(f"«{voce}» senza «/24» ammette solo quell'indirizzo, che di solito è quello della rete: "
                          f"per tutta la rete scrivi {voce}/24.")
    return avvisi


def valida_macchina(host: str, porta, codice: str) -> list[str]:
    errori = []
    if not _HOST_RE.match(host or ""):
        errori.append("Indirizzo OPC UA non valido: IP o nome della macchina (es. 192.168.23.115).")
    try:
        if not 1 <= int(porta) <= 65535:
            raise ValueError
    except (TypeError, ValueError):
        errori.append("Porta OPC UA non valida (di solito 4840).")
    if codice and not _CODICE_RE.match(codice):
        errori.append("Codice non valido: lettere, cifre, punto, trattino (es. DM6).")
    return errori


# --- token -------------------------------------------------------------------------------------

def nuovo_token(client) -> str:
    """Genera e imposta un token nuovo; ritorna quello in chiaro (da mostrare una volta sola)."""
    token = client.issue_token()
    client.set_token(token)
    return token


# --- configurazione per il collector -------------------------------------------------------------

def nome_macchina(coll) -> str:
    return coll.codice or (coll.asset.internal_number or "").strip() or coll.asset.asset_tag


def macchine_per(client) -> list[dict]:
    """Le macchine che il collector deve leggere, nel formato di machines.json (client None = tutte)."""
    from assets.models import CollegamentoMTConnect

    qs = (CollegamentoMTConnect.objects.filter(fonte=CollegamentoMTConnect.FONTE_COLLECTOR, attivo=True)
          .exclude(opcua_host="").select_related("asset").order_by("codice", "asset__name"))
    if client is not None and not client.all_meter_assets:
        qs = qs.filter(asset__in=client.allowed_assets.all())
    out = []
    for coll in qs:
        asset = coll.asset
        out.append({
            "name": nome_macchina(coll),
            "ip": coll.opcua_host,
            "port": coll.opcua_porta or 4840,
            # la matricola che il server ha già dichiarato vince su quella dell'asset (a volte diversa)
            "serial": coll.matricola_opcua or asset.serial_number or "",
            "hours_unit": coll.unita_ore or "",
            "model": asset.model or "",
            "department": asset.reparto or "",
            "asset_tag": asset.asset_tag,
            "username": coll.opcua_utente or "",
            "password": decifra(coll.opcua_password),
        })
    return out


def crea_contatori(asset) -> list[str]:
    """Crea i contatori Ore e Cicli che mancano sull'asset; ritorna i nomi di quelli creati."""
    from assets.models import AssetMeter

    creati = []
    for tipo, unita, nome in ((AssetMeter.METER_HOURS, "h", "Ore"), (AssetMeter.METER_CYCLES, "pezzi", "Cicli")):
        _meter, nuovo = AssetMeter.objects.get_or_create(
            asset=asset, meter_type=tipo,
            defaults={"unit_label": unita, "source": AssetMeter.SOURCE_OPCUA,
                      "notes": "Creato da Macchine collegate: lo aggiorna il collector OPC UA."})
        if nuovo:
            creati.append(nome)
    return creati


def formato_ore(valore) -> str:
    """6284.07 -> «6.284,1» (una cifra decimale solo se serve)."""
    numero = round(float(valore), 1)
    testo = f"{numero:,.1f}" if not numero.is_integer() else f"{int(numero):,}"
    return testo.replace(",", "X").replace(".", ",").replace("X", ".")


# --- ore lette dalla CNC -----------------------------------------------------------------------

# Come ``hours_factor`` di MODELS in collector_cnc/collector.py (un test lo verifica).
FATTORE_MODELLO = {"umati": Decimal(1), "bds": Decimal(1) / Decimal(3600)}
FATTORE_UNITA = {"h": Decimal(1), "min": Decimal(1) / Decimal(60), "s": Decimal(1) / Decimal(3600)}
UNITA_LABEL = {"h": "ore", "min": "minuti", "s": "secondi"}
MODELLO_LABEL = {"umati": "umati", "bds": "BasicDataSet"}


def unita_effettiva(coll) -> str:
    """Unità con cui il portale legge le ore della CNC: quella scelta o quella del modello dati."""
    if coll.unita_ore:
        return coll.unita_ore
    return {"umati": "h", "bds": "s"}.get(coll.modello_dati, "")


def contatore_ore(coll):
    from assets.models import AssetMeter

    return coll.contatore_ore or AssetMeter.objects.filter(asset_id=coll.asset_id, meter_type=AssetMeter.METER_HOURS).order_by("id").first()


def ore_dalla_cnc(coll) -> Decimal | None:
    """Il valore letto dalla CNC convertito in ore con l'unità effettiva (None se non c'è)."""
    unita = unita_effettiva(coll)
    if coll.ore_grezzo is None or unita not in FATTORE_UNITA:
        return None
    return (coll.ore_grezzo * FATTORE_UNITA[unita]).quantize(Decimal("0.01"))


def ricalcola_ore(coll, user=None) -> str:
    """Dopo un cambio di unità: il contatore Ore riparte dal valore della CNC convertito, con una nota.
    Ritorna il messaggio per l'utente ("" se non c'è niente da ricalcolare)."""
    from .meters import MeterReadingError, record_meter_reading

    meter, ore = contatore_ore(coll), ore_dalla_cnc(coll)
    if meter is None or ore is None or ore == meter.current_value:
        return ""
    from assets.models import AssetMeter

    try:
        record_meter_reading(meter, ore, read_at=timezone.now(), source=AssetMeter.SOURCE_MANUAL, user=user,
                             is_reset=ore < meter.current_value,
                             note=f"Unità delle ore della CNC: {UNITA_LABEL.get(unita_effettiva(coll), '?')} (Macchine collegate)")
    except MeterReadingError as exc:
        return f"Contatore Ore non ricalcolato: {exc}"
    return f"Contatore Ore ricalcolato: {formato_ore(ore)} h."


# --- avviso a ore (non bloccante) --------------------------------------------------------------

def avviso_ore(coll, ore=None) -> dict | None:
    """Avviso ogni N ore di lavoro: ``{testo, prossimo, mancano, livello, messaggio}``; None se non impostato.

    Solo un avviso nelle pagine: nessuna scadenza, nessun ordine di lavoro. ``livello``: ok, warn
    (mancano meno del 10% dell'intervallo), danger (superato), muted (manca il contatore Ore)."""
    if not coll.avviso_ore_ogni:
        return None
    testo = coll.avviso_ore_testo or "Avviso a ore"
    if ore is None:
        meter = contatore_ore(coll)
        ore = meter.current_value if meter is not None else None
    if ore is None:
        return {"testo": testo, "livello": "muted", "messaggio": f"{testo}: manca il contatore Ore."}
    ogni = coll.avviso_ore_ogni
    prossimo = (coll.avviso_ore_da or Decimal(0)) + ogni
    mancano = prossimo - Decimal(ore)
    if mancano <= 0:
        livello, messaggio = "danger", f"{testo}: superato di {formato_ore(-mancano)} h"
    elif mancano <= ogni / 10:
        livello, messaggio = "warn", f"{testo}: tra {formato_ore(mancano)} h"
    else:
        livello, messaggio = "ok", f"{testo}: tra {formato_ore(mancano)} h"
    return {"testo": testo, "prossimo": formato_ore(prossimo), "mancano": mancano, "livello": livello,
            "messaggio": f"{messaggio} (a {formato_ore(prossimo)} h, ogni {formato_ore(ogni)} h)"}


def fatto_ore(coll) -> Decimal | None:
    """«Fatto»: l'avviso riparte dalle ore attuali del contatore. Ritorna il nuovo punto di partenza."""
    meter = contatore_ore(coll)
    if meter is None:
        return None
    coll.avviso_ore_da = meter.current_value
    coll.save(update_fields=["avviso_ore_da", "aggiornato_il"])
    return meter.current_value


# --- CNC che non si possono collegare ------------------------------------------------------------

def cnc_da_sistemare():
    """Asset che sembrano CNC ma non hanno la scheda macchina: non compaiono in «Collega una macchina»."""
    from django.db.models import Q

    from assets.models import Asset

    macchina = Asset.TYPE_WORK_MACHINE
    # Tipo CNC o macchina di lavoro senza scheda: compaiono gia' nel menu (vedi views_mtconnect._macchine).
    return (Asset.objects.filter(work_machine__isnull=True).exclude(status=Asset.STATUS_RETIRED)
            .exclude(asset_type__in=[Asset.TYPE_CNC, macchina])
            .filter(Q(asset_category__base_asset_type=macchina)
                    | Q(asset_category__children__base_asset_type=macchina) | Q(asset_category__label__icontains="cnc"))
            .select_related("asset_category").distinct().order_by("name", "asset_tag"))


# --- cerca le macchine in rete -------------------------------------------------------------------

_CODICE_DA_TAG = re.compile(r"^[A-Za-z]{1,4}\d{1,4}$")
_MATRICOLA_RE = re.compile(r"^[A-Za-z0-9._\-]{0,60}$")
MAX_CREDENZIALI = 3


def normalizza_matricola(valore) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(valore or "").upper()).lstrip("0")


def codice_proposto(asset) -> str:
    """Il codice breve dal codice asset: «CNC-DM6-000060148189» -> «DM6»."""
    for parte in re.split(r"[\s\-_/]+", asset.asset_tag or ""):
        if _CODICE_DA_TAG.match(parte):
            return parte.upper()
    return ""


def rete_proposta() -> str:
    """La /24 della prima macchina già collegata al collector (vuoto se nessuna)."""
    from assets.models import CollegamentoMTConnect

    for host in (CollegamentoMTConnect.objects.filter(fonte=CollegamentoMTConnect.FONTE_COLLECTOR)
                 .exclude(opcua_host="").order_by("id").values_list("opcua_host", flat=True)):
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            continue
        if ip.version == 4 and ip.is_private:
            return str(ipaddress.ip_network(f"{host}/24", strict=False))
    return ""


def credenziali_salvate() -> list[tuple[str, str, int]]:
    """Utente e password OPC UA già salvati (diversi tra loro), da provare dopo l'accesso anonimo."""
    from assets.models import CollegamentoMTConnect

    viste, out = set(), []
    for coll in CollegamentoMTConnect.objects.exclude(opcua_utente="").order_by("id"):
        coppia = (coll.opcua_utente, decifra(coll.opcua_password))
        if coppia not in viste:
            viste.add(coppia)
            out.append((*coppia, coll.pk))
        if len(out) >= MAX_CREDENZIALI:
            break
    return out


def cerca_macchine(rete: str, porta: int, macchine) -> list[dict]:
    """Cerca i server OPC UA della rete e abbina ognuno a una macchina del portale.

    ``macchine``: le macchine di lavoro collegabili (stesso elenco di «Collega una macchina»).
    Abbinamento: matricola già dichiarata dal server, poi indirizzo già collegato, poi numero di
    serie dell'asset. Solleva ValueError (rete non valida) o RuntimeError (asyncua mancante)."""
    import asyncio

    from assets.models import Asset, CollegamentoMTConnect

    try:
        from assets.collector_cnc import cerca
    except ImportError as exc:
        raise RuntimeError("Sul server manca la libreria asyncua (requirements.txt): la ricerca non si può fare.") from exc
    cerca.indirizzi(rete)  # ValueError prima di aprire connessioni
    trovati = asyncio.run(cerca.cerca(rete, porta, [(u, p, k) for u, p, k in credenziali_salvate()]))

    collegamenti = list(CollegamentoMTConnect.objects.select_related("asset"))
    per_matricola = {normalizza_matricola(c.matricola_opcua): c for c in collegamenti if c.matricola_opcua}
    per_host = {c.opcua_host: c for c in collegamenti if c.fonte == CollegamentoMTConnect.FONTE_COLLECTOR and c.opcua_host}
    per_asset = {c.asset_id: c for c in collegamenti}
    collegabili = {a.pk: a for a in macchine}
    per_serie: dict[str, list] = {}
    for asset in Asset.objects.exclude(status=Asset.STATUS_RETIRED).exclude(serial_number__isnull=True).exclude(serial_number=""):
        per_serie.setdefault(normalizza_matricola(asset.serial_number), []).append(asset)

    righe = []
    for t in sorted(trovati, key=lambda t: ipaddress.ip_address(t["ip"])):
        riga = {**t, "modello_label": MODELLO_LABEL.get(t["modello"], ""), "asset": None, "collegamento": None,
                "collegabile": False, "spunta": False, "codice": "", "livello": "muted", "esito": ""}
        righe.append(riga)
        if t["errore"] == "accesso":
            coll = per_host.get(t["ip"])
            riga.update(collegamento=coll, asset=coll.asset if coll else None,
                        esito="Chiede utente e password OPC UA: scrivili in «Collega una macchina»." if not coll
                        else "Già collegata (il server chiede utente e password).", livello="warn" if not coll else "ok")
            continue
        if t["errore"]:
            riga["esito"] = f"Risponde sulla porta ma {t['errore']}."
            continue
        if not t["dmg"]:
            riga["esito"] = "Server OPC UA che non è una DMG MORI: il collector legge solo le DMG MORI."
            continue
        candidati = per_serie.get(normalizza_matricola(t["matricola"])) or []
        coll = per_matricola.get(normalizza_matricola(t["matricola"])) or per_host.get(t["ip"])
        if coll is None and len(candidati) == 1:
            coll = per_asset.get(candidati[0].pk)
        if coll is not None:
            riga.update(collegamento=coll, asset=coll.asset, codice=coll.codice or codice_proposto(coll.asset))
            if coll.fonte == CollegamentoMTConnect.FONTE_MTCONNECT and coll.attivo:
                riga["esito"] = "Già letta da un agent MTConnect."
            elif coll.fonte == CollegamentoMTConnect.FONTE_COLLECTOR and coll.opcua_host == t["ip"]:
                riga.update(esito="Già collegata.", livello="ok")
            else:
                riga.update(esito=f"Collegata con un altro indirizzo ({coll.opcua_host or 'nessuno'}): l'IP è cambiato?",
                            livello="warn", collegabile=coll.asset_id in collegabili, spunta=True)
            continue
        if len(candidati) == 1 and candidati[0].pk in collegabili:
            riga.update(asset=candidati[0], codice=codice_proposto(candidati[0]), esito="Trovato l'asset con lo stesso numero di serie.",
                        livello="warn", collegabile=True, spunta=True)
        elif len(candidati) == 1 and candidati[0].pk not in collegabili:
            riga.update(asset=candidati[0], livello="danger",
                        esito="L'asset con questa matricola non è una macchina di lavoro: vedi «CNC da sistemare».")
        else:
            riga.update(esito="Nessun asset con questa matricola: scegli la macchina.", livello="warn", collegabile=True)
    return righe


def valida_riga_trovata(matricola: str, modello: str) -> tuple[str, str]:
    """Matricola e modello rimandati dal form della ricerca: solo valori plausibili, altrimenti vuoti."""
    matricola = (matricola or "").strip()
    return (matricola if _MATRICOLA_RE.match(matricola) else ""), (modello if modello in MODELLO_LABEL else "")



# --- dove gira il collector ----------------------------------------------------------------------

MODALITA_KEY = "assets.collector_cnc.modalita"
BATTITO_KEY = "assets.collector_cnc.battito"
MODALITA = {"pc": "Su un PC dell'officina", "server": "Sul server del portale"}
BATTITO_VECCHIO_MINUTI = 5


def modalita() -> str:
    from core.models import SiteConfig

    valore = SiteConfig.objects.filter(chiave=MODALITA_KEY).values_list("valore", flat=True).first()
    return valore if valore in MODALITA else "pc"


def imposta_modalita(valore: str) -> None:
    from core.models import SiteConfig

    if valore not in MODALITA:
        raise ValueError(valore)
    SiteConfig.objects.update_or_create(chiave=MODALITA_KEY, defaults={
        "valore": valore, "descrizione": "Dove gira il collector OPC UA delle CNC (pc | server)"})


def registra_battito(macchine: int, errore: str = "") -> None:
    """Il collector integrato è vivo: lo dice ogni minuto (pagina Macchine collegate, controllo infrastruttura)."""
    import json

    from django.utils import timezone

    from core.models import SiteConfig

    SiteConfig.objects.update_or_create(chiave=BATTITO_KEY, defaults={
        "valore": json.dumps({"at": timezone.now().isoformat(), "macchine": macchine, "errore": errore[:300]}),
        "descrizione": "Ultimo segnale del collector OPC UA integrato nel portale"})


def battito() -> dict:
    """``{"at": datetime|None, "macchine": int, "errore": str, "vivo": bool}`` del collector integrato."""
    import json
    from datetime import timedelta

    from django.utils import timezone
    from django.utils.dateparse import parse_datetime

    from core.models import SiteConfig

    valore = SiteConfig.objects.filter(chiave=BATTITO_KEY).values_list("valore", flat=True).first()
    try:
        dati = json.loads(valore) if valore else {}
    except ValueError:
        dati = {}
    at = parse_datetime(str(dati.get("at") or "")) if dati.get("at") else None
    vivo = bool(at and timezone.now() - at <= timedelta(minutes=BATTITO_VECCHIO_MINUTI))
    return {"at": at, "macchine": int(dati.get("macchine") or 0), "errore": str(dati.get("errore") or ""), "vivo": vivo}


# --- letture e stati: stessa logica per l'API (collector sul PC) e per il collector integrato ------

def _riga(index, row, status, reason="", **extra):
    return {"index": index, "asset_tag": str(row.get("asset_tag") or ""), **extra, "status": status, "reason": reason}


def _assets_e_consentiti(righe, client):
    from assets.models import Asset

    tags = {str(row.get("asset_tag") or "").strip() for row in righe if isinstance(row, dict)}
    assets = {asset.asset_tag: asset for asset in Asset.objects.filter(asset_tag__in=[t for t in tags if t])}
    consentiti = None if client is None or client.all_meter_assets else set(client.allowed_assets.values_list("id", flat=True))
    return assets, consentiti


def applica_letture(readings, client=None, nota: str = "", source: str = "") -> dict:
    """Letture dei contatori ``[{asset_tag, meter_type, value, read_at}]``: esito per riga."""
    from django.utils import timezone
    from django.utils.dateparse import parse_datetime

    from assets.models import AssetMeter

    from .meters import MeterReadingOlder, MeterReadingRejected, record_meter_reading

    from assets.models import CollegamentoMTConnect

    assets, consentiti = _assets_e_consentiti(readings, client)
    tipi = dict(AssetMeter.METER_TYPE_CHOICES)
    source = source or AssetMeter.SOURCE_OPCUA
    # Le ore le converte il portale dal valore letto dalla CNC (unità scelta in Macchine collegate),
    # così un cambio di unità vale subito, senza aspettare che il collector rilegga l'elenco.
    collegamenti = {c.asset_id: c for c in CollegamentoMTConnect.objects.filter(
        asset_id__in=[a.id for a in assets.values()], fonte=CollegamentoMTConnect.FONTE_COLLECTOR)}
    results = []
    for index, row in enumerate(readings):
        if not isinstance(row, dict):
            results.append(_riga(index, {}, "rejected", "riga non valida", meter_type=""))
            continue
        meter_type = str(row.get("meter_type") or "").strip().upper()
        extra = {"meter_type": str(row.get("meter_type") or "")}
        asset = assets.get(str(row.get("asset_tag") or "").strip())
        if asset is None:
            results.append(_riga(index, row, "rejected", "asset sconosciuto", **extra))
            continue
        if consentiti is not None and asset.id not in consentiti:
            results.append(_riga(index, row, "rejected", "asset non consentito a questo collector", **extra))
            continue
        if meter_type not in tipi:
            results.append(_riga(index, row, "rejected", "tipo di contatore non valido", **extra))
            continue
        meter = AssetMeter.objects.filter(asset=asset, meter_type=meter_type).first()
        if meter is None:
            results.append(_riga(index, row, "rejected", "contatore non configurato sull'asset", **extra))
            continue
        read_at = parse_datetime(str(row.get("read_at"))) if row.get("read_at") else None
        if read_at is None or timezone.is_naive(read_at):
            results.append(_riga(index, row, "rejected", "read_at mancante o senza fuso orario (ISO 8601 con offset)", **extra))
            continue
        valore = row.get("value")
        if meter_type == AssetMeter.METER_HOURS and asset.id in collegamenti:
            convertite = ore_dalla_cnc(collegamenti[asset.id])
            valore = convertite if convertite is not None else valore
        try:
            record_meter_reading(meter, valore, read_at=read_at, source=source, user=None, note=nota)
        except MeterReadingOlder as exc:
            results.append(_riga(index, row, "ignored_older", str(exc), **extra))
        except MeterReadingRejected as exc:
            results.append(_riga(index, row, "rejected", str(exc), **extra))
        else:
            results.append(_riga(index, row, "accepted", **extra))
    summary = {status: sum(1 for r in results if r["status"] == status) for status in ("accepted", "ignored_older", "rejected")}
    return {"results": results, **summary}


def applica_stati(macchine, client=None) -> dict:
    """Stato delle CNC ``[{asset_tag, stato, dal, programma, …}]``: esito per riga."""
    from django.utils import timezone
    from django.utils.dateparse import parse_datetime

    from assets.models import CollegamentoMTConnect

    from . import mtconnect

    assets, consentiti = _assets_e_consentiti(macchine, client)
    ora = timezone.now()
    results = []
    for index, row in enumerate(macchine):
        if not isinstance(row, dict):
            results.append(_riga(index, {}, "rejected", "riga non valida"))
            continue
        asset = assets.get(str(row.get("asset_tag") or "").strip())
        if asset is None:
            results.append(_riga(index, row, "rejected", "asset sconosciuto"))
            continue
        if consentiti is not None and asset.id not in consentiti:
            results.append(_riga(index, row, "rejected", "asset non consentito a questo collector"))
            continue
        stato = str(row.get("stato") or "").strip().upper()
        if stato not in mtconnect.STATI_COLLECTOR:
            results.append(_riga(index, row, "rejected", "stato non valido"))
            continue
        dal = parse_datetime(str(row.get("dal") or "")) if row.get("dal") else None
        if dal is not None and timezone.is_naive(dal):
            results.append(_riga(index, row, "rejected", "dal senza fuso orario (ISO 8601 con offset)"))
            continue
        coll = CollegamentoMTConnect.objects.filter(asset=asset).first()
        if coll is None:
            coll = CollegamentoMTConnect(asset=asset, fonte=CollegamentoMTConnect.FONTE_COLLECTOR)
        elif coll.fonte != CollegamentoMTConnect.FONTE_COLLECTOR:
            if coll.attivo:
                results.append(_riga(index, row, "rejected", "macchina letta dal portale via MTConnect"))
                continue
            coll.fonte = CollegamentoMTConnect.FONTE_COLLECTOR
        elif not coll.attivo:
            results.append(_riga(index, row, "ignored", "lettura sospesa nel portale"))
            continue
        mtconnect.applica_stato_collector(coll, {**row, "stato": stato}, dal or ora, ora)
        results.append(_riga(index, row, "accepted"))
    summary = {status: sum(1 for r in results if r["status"] == status) for status in ("accepted", "ignored", "rejected")}
    return {"results": results, **summary}
