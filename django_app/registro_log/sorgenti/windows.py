"""Lettura del registro eventi di Windows con ``wevtutil`` (incluso in Windows, niente agent).

Due modi, scelti per fonte:

- **lettura diretta** (``/r:<server>``): il server del portale legge il registro Security e
  System del server indicato. L'account del raccoglitore deve stare nel gruppo «Event Log
  Readers» del server (sui controller di dominio: il gruppo di dominio «Event Log Readers»).
- **eventi inoltrati** (WEF): i server inoltrano a questo server con una sottoscrizione di
  Windows Event Forwarding; qui si legge il registro locale ``ForwardedEvents``.

Si legge solo dopo il segnalibro (``EventRecordID``) di ogni registro, fino all'ultimo record
presente al momento della lettura: se nel frattempo non è arrivato nulla di interessante il
segnalibro avanza comunque, e un registro sovrascritto prima della lettura (``oldestRecordNumber``
oltre il segnalibro) diventa un'interruzione «Eventi sovrascritti prima della lettura».
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field

from defusedxml import ElementTree as SafeET

from registro_log import regole

LOTTO = 500
PAGINE_PER_GIRO = 40
PRIMA_VOLTA_ORE = 24
TIMEOUT = 180


class ErroreLettura(RuntimeError):
    pass


def esegui(args: list[str], timeout: int = TIMEOUT) -> str:
    """Lancia ``wevtutil`` e torna l'output come testo. Errori di wevtutil → :class:`ErroreLettura`."""
    try:
        r = subprocess.run(["wevtutil", *args], capture_output=True, timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except FileNotFoundError as exc:
        raise ErroreLettura("wevtutil non trovato: il raccoglitore deve girare su Windows.") from exc
    except subprocess.TimeoutExpired as exc:
        raise ErroreLettura(f"Il server non ha risposto entro {timeout} secondi.") from exc
    out = _testo(r.stdout)
    if r.returncode != 0:
        errore = (_testo(r.stderr) or out).strip().splitlines()
        raise ErroreLettura(spiega_errore(errore[-1] if errore else f"codice {r.returncode}"))
    return out


def _testo(b: bytes) -> str:
    if not b:
        return ""
    if b[:2] in (b"\xff\xfe", b"\xfe\xff") or (len(b) > 3 and b[1:2] == b"\x00"):
        return b.decode("utf-16", errors="replace")
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        return b.decode("cp850", errors="replace")


def spiega_errore(testo: str) -> str:
    t = testo.lower()
    if "access is denied" in t or "accesso negato" in t:
        return ("Accesso negato al registro eventi: aggiungere l'account del raccoglitore al gruppo "
                "«Event Log Readers» del server (sui controller di dominio, il gruppo di dominio).")
    if "rpc server is unavailable" in t or "server rpc non è disponibile" in t or "rpc" in t and "unavailable" in t:
        return ("Server non raggiungibile per la lettura remota (RPC): verificare nome e firewall "
                "(regola «Gestione remota registro eventi»).")
    if "channel" in t and ("not found" in t or "non trovato" in t) or "could not be found" in t:
        return f"Registro non trovato sul server: {testo.strip()}"
    return testo.strip()[:400]


def _args_remoto(host: str) -> list[str]:
    return [f"/r:{host}"] if host else []


def ultimo_record(canale: str, host: str, timeout: int = TIMEOUT) -> int | None:
    out = esegui(["qe", canale, "/rd:true", "/c:1", "/f:xml", "/e:Events", *_args_remoto(host)], timeout=timeout)
    eventi = _eventi(out)
    return eventi[0]["rec"] if eventi else None


def record_piu_vecchio(canale: str, host: str) -> int | None:
    out = esegui(["gli", canale, *_args_remoto(host)])
    m = re.search(r"oldestRecordNumber:\s*(\d+)", out)
    return int(m.group(1)) if m else None


def _eventi(xml_testo: str) -> list[dict]:
    xml_testo = (xml_testo or "").strip()
    if not xml_testo:
        return []
    if not xml_testo.startswith("<Events"):
        xml_testo = f"<Events>{xml_testo}</Events>"
    radice = SafeET.fromstring(xml_testo)
    return [regole.normalizza_windows(ev) for ev in radice.findall(f"{regole.NS}Event")]


@dataclass
class EsitoCanale:
    canale: str
    eventi: list[dict] = field(default_factory=list)
    segnalibro: int | None = None
    persi: int = 0
    completo: bool = True


def leggi_canale(canale: str, host: str, segnalibro: int | None, *, tutto: bool, file: bool = False,
                 usb: bool = False) -> EsitoCanale:
    """Legge gli eventi nuovi di un registro. Non cambia nulla sul server."""
    esito = EsitoCanale(canale, segnalibro=segnalibro)
    fino_a = ultimo_record(canale, host)
    if fino_a is None:
        return esito
    if segnalibro is not None:
        vecchio = record_piu_vecchio(canale, host)
        if vecchio and vecchio > segnalibro + 1:
            esito.persi = vecchio - segnalibro - 1
            segnalibro = vecchio - 1
        if fino_a <= segnalibro:
            esito.segnalibro = segnalibro
            return esito
    dopo = segnalibro
    for _ in range(PAGINE_PER_GIRO):
        q = regole.xpath(canale, dopo, tutto=tutto, prima_volta_ms=PRIMA_VOLTA_ORE * 3600 * 1000, fino_a=fino_a,
                         file=file, usb=usb)
        pagina = _eventi(esegui(["qe", canale, f"/q:{q}", "/f:xml", f"/c:{LOTTO}", "/e:Events", *_args_remoto(host)]))
        esito.eventi.extend(pagina)
        if len(pagina) < LOTTO:
            esito.segnalibro = fino_a
            return esito
        dopo = max(e["rec"] for e in pagina)
        esito.segnalibro = dopo
    esito.completo = False  # troppi eventi: si continua al giro dopo dal segnalibro
    return esito


def prova(host: str, canali: list[str], timeout: int = 25) -> list[str]:
    """Per il pulsante «Prova»: legge l'ultimo record di ogni registro, senza archiviare nulla."""
    righe = []
    for canale in canali:
        try:
            rec = ultimo_record(canale, host, timeout=timeout)
            righe.append(f"{canale}: raggiungibile, ultimo evento n. {rec}" if rec else f"{canale}: raggiungibile, registro vuoto")
        except ErroreLettura as exc:
            righe.append(f"{canale}: {exc}")
    return righe
