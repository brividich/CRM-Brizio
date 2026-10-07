"""Verifica OID su un apparato reale e proposta delle colonne di profilo.

Un elenco di OID (da un catalogo, da una MIB, da un'AI esterna) vale solo per
quello che l'apparato risponde davvero. Qui ogni OID viene interrogato in sola
lettura: GET se e' un valore singolo, WALK (con le righe raggruppate per
colonna) se e' una tabella o un ramo. All'AI interna arrivano solo gli OID che
hanno risposto, con i loro valori: puo' dare nomi, unita' e soglie, non puo'
aggiungere OID. Nessuna community/chiave entra nei risultati o nel prompt.
"""
from __future__ import annotations

import asyncio
import functools
import json
import logging
import re
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from time import monotonic

from .models import ColonnaProfiloSNMP, ImpostazioniSNMP

logger = logging.getLogger(__name__)

MAX_OID = 40                # OID estratti dal testo incollato
MAX_RIGHE_RAMO = 200        # foglie lette per ogni WALK
MAX_CANDIDATI = 120         # righe nella tabella dei risultati
BUDGET = 45.0               # secondi complessivi per la verifica
_OID_TESTO = re.compile(r"(?<![\d.])\.?(1\.3\.6\.1(?:\.\d+)+)(?![\d.]*\d)")

# Rami standard (RFC) letti da «Esplora rami noti»: validi su qualunque marca.
RAMI_STANDARD = (
    ("1.3.6.1.2.1.25.3.3.1.2", "HOST-RESOURCES carico CPU"),
    ("1.3.6.1.2.1.25.2.3.1", "HOST-RESOURCES memoria e dischi"),
    ("1.3.6.1.4.1.2021.4", "UCD memoria"),
    ("1.3.6.1.4.1.2021.10.1.3", "UCD carico medio"),
    ("1.3.6.1.4.1.2021.11", "UCD CPU"),
    ("1.3.6.1.2.1.2.2.1.8", "IF-MIB stato porte"),
    ("1.3.6.1.2.1.31.1.1.1.6", "IF-MIB traffico ricevuto 64 bit"),
    ("1.3.6.1.2.1.31.1.1.1.10", "IF-MIB traffico trasmesso 64 bit"),
    ("1.3.6.1.2.1.2.2.1.14", "IF-MIB errori in ingresso"),
    ("1.3.6.1.2.1.105.1.3.1.1", "POWER-ETHERNET consumo PoE"),
    ("1.3.6.1.2.1.99.1.1.1.4", "ENTITY-SENSOR valori sensori"),
    ("1.3.6.1.2.1.33.1.2", "UPS-MIB batteria"),
)

# Rami dalle MIB pubbliche dei produttori, per prefisso sysObjectID. Sono solo
# punti di partenza: entra nel risultato unicamente cio' che l'apparato risponde.
RAMI_PRODUTTORE = {
    "1.3.6.1.4.1.11.2.3.7.11": (   # HPE Aruba / ProCurve (ArubaOS-Switch)
        ("1.3.6.1.4.1.11.2.14.11.5.1.9.6", "HP STATISTICS CPU"),
        ("1.3.6.1.4.1.11.2.14.11.5.1.1.2.1.1.1", "HP NETSWITCH memoria"),
        ("1.3.6.1.4.1.11.2.14.11.1.2.6.1", "HP ICF sensori ventole/alimentatori/temperatura"),
    ),
    "1.3.6.1.4.1.47196": (          # Aruba AOS-CX
        ("1.3.6.1.4.1.47196.4.1.1.3.11", "Aruba CX sottosistemi"),
    ),
    "1.3.6.1.4.1.9.6.1": (          # Cisco Small Business (SG/CBS 2xx/3xx)
        ("1.3.6.1.4.1.9.6.1.101.1", "Cisco SB CPU"),
        ("1.3.6.1.4.1.9.6.1.101.53", "Cisco SB ambiente (ventole, temperatura)"),
        ("1.3.6.1.4.1.9.6.1.101.83", "Cisco SB ambiente"),
    ),
    "1.3.6.1.4.1.9.1": (            # Cisco IOS
        ("1.3.6.1.4.1.9.9.109.1.1.1.1", "Cisco CPU"),
        ("1.3.6.1.4.1.9.9.48.1.1.1", "Cisco memoria"),
        ("1.3.6.1.4.1.9.9.13.1", "Cisco ambiente"),
    ),
    "1.3.6.1.4.1.3097": (           # WatchGuard Fireware
        ("1.3.6.1.4.1.3097.6.3", "WatchGuard statistiche di sistema"),
        ("1.3.6.1.4.1.3097.6.6", "WatchGuard stato del cluster"),
    ),
    "1.3.6.1.4.1.41112": (          # Ubiquiti UniFi
        ("1.3.6.1.4.1.41112.1.6", "UniFi AP"),
    ),
    "1.3.6.1.4.1.6876": (           # VMware ESXi
        ("1.3.6.1.4.1.6876.1", "VMware sistema"),
    ),
    "1.3.6.1.4.1.232": (            # HPE iLO
        ("1.3.6.1.4.1.232.6.1", "HPE salute generale"),
        ("1.3.6.1.4.1.232.6.2.6", "HPE temperature e ventole"),
    ),
    "1.3.6.1.4.1.8072": (           # net-snmp (Synology, Linux, MSA)
        ("1.3.6.1.4.1.6574.1", "Synology sistema"),
    ),
}


def estrai_oid(testo: str) -> list[str]:
    """OID numerici trovati nel testo (anche dentro tabelle o frasi), senza doppioni."""
    trovati = [m.group(1) for m in _OID_TESTO.finditer(testo or "")]
    return list(dict.fromkeys(trovati))[:MAX_OID]


def rami_noti(sys_object_id: str) -> list[tuple[str, str]]:
    oid = (sys_object_id or "").strip().lstrip(".")
    rami = []
    for prefisso, elenco in RAMI_PRODUTTORE.items():
        if oid == prefisso or oid.startswith(prefisso + "."):
            rami.extend(elenco)
    return rami + list(RAMI_STANDARD)


def _valore(v):
    """(tipo, testo leggibile, numero o None) per un valore puresnmp."""
    if isinstance(v, bool):
        v = int(v)
    if isinstance(v, int):
        return ColonnaProfiloSNMP.TipoValore.NUMERO, str(v), Decimal(v)
    if isinstance(v, timedelta):
        secondi = int(v.total_seconds())
        return ColonnaProfiloSNMP.TipoValore.TIMETICKS, f"{secondi} s", Decimal(secondi * 100)
    if isinstance(v, bytes):
        testo = v.decode("utf-8", "replace") if v.isascii() or _utf8(v) else v.hex(" ")
    else:
        testo = str(v)
    testo = testo.strip().replace("\x00", "")
    try:
        numero = Decimal(testo)
        if numero.is_finite() and re.fullmatch(r"-?\d+(\.\d+)?", testo):
            return ColonnaProfiloSNMP.TipoValore.NUMERO, testo, numero
    except InvalidOperation:
        pass
    return ColonnaProfiloSNMP.TipoValore.TESTO, testo, None


def _utf8(b: bytes) -> bool:
    try:
        b.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def _candidato_get(oid, valore, origine):
    tipo, testo, _ = _valore(valore)
    return {"oid": oid, "modalita": "GET", "righe": 1, "tipo": tipo,
            "campione": testo[:120], "min": "", "max": "", "origine": origine}


def _candidato_walk(oid, valori, origine):
    letti = [_valore(v) for v in valori]
    tipi = {t for t, _, _ in letti}
    tipo = tipi.pop() if len(tipi) == 1 else ColonnaProfiloSNMP.TipoValore.TESTO
    numeri = [n for _, _, n in letti if n is not None]
    campione = ", ".join(t[:30] for _, t, _ in letti[:4]) + (" …" if len(letti) > 4 else "")
    return {"oid": oid, "modalita": "WALK", "righe": len(letti), "tipo": tipo,
            "campione": campione[:160],
            "min": str(min(numeri)) if numeri and len(numeri) == len(letti) else "",
            "max": str(max(numeri)) if numeri and len(numeri) == len(letti) else "",
            "origine": origine}


def raggruppa_ramo(foglie, origine):
    """Righe di un WALK -> candidati: le foglie con lo stesso genitore sono una colonna."""
    gruppi: dict[str, list] = {}
    for oid, valore in foglie:
        genitore = oid.rsplit(".", 1)[0]
        gruppi.setdefault(genitore, []).append((oid, valore))
    candidati = []
    for genitore, righe in gruppi.items():
        if len(righe) == 1:
            oid, valore = righe[0]
            candidati.append(_candidato_get(oid, valore, origine))
        else:
            candidati.append(_candidato_walk(genitore, [v for _, v in righe], origine))
    return candidati


_ERRORI_FATALI = {16}  # authorizationError: inutile insistere sugli altri OID


def verifica(host, oids, *, community, porta, timeout, versione, rami=()):
    """Interroga ``oids`` (GET, poi WALK se non e' un valore singolo) e ``rami`` (WALK).

    Ritorna ``{"candidati": [...], "assenti": [...], "errore": str}``.
    """
    from puresnmp import Client, PyWrapper
    from puresnmp.transport import send_udp

    from .snmp import NESSUNA_RISPOSTA, costruisci_credenziali, descrivi_errore

    cred = costruisci_credenziali(community, versione)
    esito = {"candidati": [], "assenti": [], "errore": ""}
    scadenza = monotonic() + BUDGET

    async def _walk(client, base):
        foglie = []
        async for vb in client.walk(base):
            oid = str(vb.oid).lstrip(".")
            if not oid.startswith(base + "."):
                break
            foglie.append((oid, vb.value))
            if len(foglie) >= MAX_RIGHE_RAMO:
                break
        return foglie

    async def _run():
        client = PyWrapper(Client(str(host), cred, port=porta,
                                  sender=functools.partial(send_udp, timeout=timeout, retries=1)))
        lavori = [(oid, "elenco") for oid in oids] + [(base, f"ramo: {nome}") for base, nome in rami]
        for oid, origine in lavori:
            resta = scadenza - monotonic()
            if resta <= 0:
                esito["errore"] = "Tempo massimo della verifica superato: verifica meno OID per volta."
                return
            try:
                if origine == "elenco":
                    try:
                        valore = await asyncio.wait_for(client.get(oid), timeout=resta)
                        esito["candidati"].append(_candidato_get(oid, valore, origine))
                        continue
                    except Exception as exc:  # noqa: BLE001 - non e' un valore singolo: prova il ramo
                        if getattr(exc, "error_status", None) != 2:
                            raise
                foglie = await asyncio.wait_for(_walk(client, oid), timeout=max(0.1, scadenza - monotonic()))
                if foglie:
                    esito["candidati"].extend(raggruppa_ramo(foglie, origine))
                elif origine == "elenco":
                    esito["assenti"].append(oid)
            except Exception as exc:  # noqa: BLE001
                stato = getattr(exc, "error_status", None)
                fatale = (stato in _ERRORI_FATALI or isinstance(exc, asyncio.TimeoutError)
                          or type(exc).__name__ == "Timeout")
                if fatale:
                    esito["errore"] = f"{host}: {descrivi_errore(exc, oid)}"
                    return
                if origine == "elenco":
                    esito["assenti"].append(oid)

    try:
        asyncio.run(_run())
    except Exception as exc:  # noqa: BLE001
        esito["errore"] = f"{host}: {descrivi_errore(exc) or NESSUNA_RISPOSTA}"
    visti, unici = set(), []
    for c in esito["candidati"]:
        if c["oid"] not in visti:
            visti.add(c["oid"])
            unici.append(c)
    esito["candidati"] = unici[:MAX_CANDIDATI]
    return esito


def verifica_dispositivo(dispositivo, oids, *, esplora=False):
    from .services import _community_snmp, _parametri_snmp
    from .snmp import SNMPError

    cfg = ImpostazioniSNMP.get_solo()
    porta, timeout, versione = _parametri_snmp(dispositivo, cfg)
    try:
        community = _community_snmp(dispositivo, cfg)
    except SNMPError as exc:
        return {"candidati": [], "assenti": [], "errore": str(exc)}
    rami = rami_noti(dispositivo.sys_object_id) if esplora else ()
    return verifica(dispositivo.host, oids, community=community, porta=porta,
                    timeout=min(timeout or 3, 5), versione=versione, rami=rami)


# --- Proposta con l'AI interna -------------------------------------------------
# Il modello locale ha un limite di token in uscita (OLLAMA_NUM_PREDICT): poche
# righe per volta e una riga per OID, cosi' una risposta troncata conserva comunque
# le righe complete (un JSON troncato andrebbe perso tutto).

MAX_AI_PER_VOLTA = 15

ISTRUZIONI = (
    "Sei un tecnico di rete che configura il monitoraggio SNMP. Ricevi il modello di un apparato e alcuni OID che "
    "hanno RISPOSTO davvero, con modalità (GET valore singolo, WALK colonna di tabella), righe, tipo e valori letti. "
    "Per OGNI OID ricevuto scrivi UNA riga, senza altro testo, nel formato:\n"
    "OID | nome breve in italiano | unità | fattore | aggregazione | avviso sopra | critico sopra | etichette | motivo\n"
    "fattore: numero che moltiplica il valore (0.01 se è in centesimi, altrimenti 1). aggregazione: PRIMO per GET; "
    "per WALK MASSIMO (stati, temperature), MEDIA (CPU) o SOMMA (traffico, errori). Soglie vuote se non servono. "
    "etichette: solo per codici di stato, es. 1=Ok, 2=Guasto (traduci in italiano quelle della MIB). Se c'è la "
    "definizione della MIB ufficiale, basati su quella. motivo: cosa misura, in poche parole; se non riconosci "
    "l'OID scrivi 'da verificare' e deducilo dai valori. Usa solo gli OID ricevuti. Non inventare."
)

AGGREGAZIONI = set(ColonnaProfiloSNMP.Aggregazione.values)


def contesto_ai(dispositivo, candidati) -> str:
    righe = [
        f"Apparato: {(dispositivo.sys_description or dispositivo.modello or dispositivo.nome)[:200]}",
        f"sysObjectID: {dispositivo.sys_object_id or 'n.d.'}",
        "OID che hanno risposto (oid | modalità | righe | tipo | valori | min-max):",
    ]
    from .oid_noti import _da_mib

    for c in candidati[:MAX_AI_PER_VOLTA]:
        intervallo = f"{c['min']}..{c['max']}" if c.get("min") != "" else ""
        mib = _da_mib(c["oid"], c["modalita"])
        nota = f" | MIB ufficiale: {mib['nome']} = {mib['motivo'][:120]}" if mib else ""
        righe.append(f"{c['oid']} | {c['modalita']} | {c['righe']} | {c['tipo']} | {c['campione'][:80]} | {intervallo}{nota}")
    return "\n".join(righe)


def _decimale(v):
    if v in (None, "", "null", "None", "-"):
        return None
    try:
        d = Decimal(str(v).strip().replace(",", "."))
        return d if d.is_finite() and abs(d) < Decimal("1e18") else None
    except InvalidOperation:
        return None


def _testo_num(d):
    return "" if d is None else format(d.normalize(), "f")


def _voce(voce, cand) -> dict:
    aggregazione = str(voce.get("aggregazione") or "").strip().upper()
    if cand["modalita"] == "GET" or aggregazione not in AGGREGAZIONI:
        aggregazione = "PRIMO" if cand["modalita"] == "GET" else "MASSIMO"
    fattore = _decimale(voce.get("fattore")) or Decimal("1")
    return {
        "nome": str(voce.get("nome") or "").strip()[:100],
        "unita": str(voce.get("unita") or "").strip()[:24],
        "fattore": _testo_num(fattore) if fattore != 1 else "1",
        "aggregazione": aggregazione,
        "avviso_sopra": _testo_num(_decimale(voce.get("avviso_sopra"))),
        "critico_sopra": _testo_num(_decimale(voce.get("critico_sopra"))),
        "etichette": str(voce.get("etichette") or "").strip()[:500],
        "motivo": str(voce.get("motivo") or "").strip()[:200],
        "fonte": "ai",
    }


CAMPI_RIGA = ("oid", "nome", "unita", "fattore", "aggregazione", "avviso_sopra", "critico_sopra", "etichette", "motivo")


def leggi_risposta(raw: str, candidati) -> dict:
    """Righe «OID | nome | ...» (o il vecchio JSON) -> {oid: proposta} solo su OID verificati."""
    validi = {c["oid"]: c for c in candidati}
    voci = []
    for riga in (raw or "").splitlines():
        parti = [p.strip().strip("`*") for p in riga.strip().strip("|").split("|")]
        if len(parti) >= 2:
            voci.append(dict(zip(CAMPI_RIGA, parti)))
    if not voci:
        match = re.search(r"\{.*\}", raw or "", re.DOTALL)
        try:
            voci = (json.loads(match.group(0)) if match else {}).get("colonne") or []
        except (ValueError, AttributeError):
            voci = []
    proposte = {}
    for voce in voci:
        if not isinstance(voce, dict):
            continue
        oid = str(voce.get("oid") or "").strip().lstrip(".")
        if oid in validi and oid not in proposte and str(voce.get("nome") or "").strip():
            proposte[oid] = _voce(voce, validi[oid])
    return proposte


def normalizza_proposta(data, candidati) -> dict:
    """Compatibilita': proposta JSON {"colonne": [...]}."""
    return leggi_risposta(json.dumps(data or {}), candidati)


def proponi_con_ai(dispositivo, candidati) -> dict:
    """{oid: proposta} per al massimo MAX_AI_PER_VOLTA candidati; vuoto se l'AI non risponde."""
    candidati = list(candidati)[:MAX_AI_PER_VOLTA]
    if not candidati:
        return {}
    try:
        from ai_assistant.services import chat_with_ollama

        raw = getattr(chat_with_ollama(ISTRUZIONI, runtime_context=contesto_ai(dispositivo, candidati),
                                       timeout=90), "content", "") or ""
    except Exception as exc:  # noqa: BLE001
        logger.info("verifica OID: AI non disponibile: %s", exc)
        return {}
    return leggi_risposta(raw, candidati)


def proposte_catalogo(candidati) -> dict:
    from .oid_noti import proposta_nota

    proposte = {}
    for c in candidati:
        nota = proposta_nota(c["oid"], c["modalita"])
        if nota:
            proposte[c["oid"]] = nota
    return proposte