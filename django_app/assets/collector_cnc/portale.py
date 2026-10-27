"""
portale.py - Invio al NOVICROM HUB dello stato delle CNC lette dal collector OPC UA.

Cosa manda (solo HTTPS/HTTP verso il portale, nessuna scrittura sulle macchine):
  - stato, programma, modalita', pezzi e allarmi attivi -> /api/assets/contatori/ingest/stato/
    a ogni cambio (entro INVIO_CAMBI secondi) e comunque ogni BATTITO secondi, cosi' il portale
    sa che il dato e' fresco (oltre 15 minuti senza invii lo mostra «non aggiornato»);
  - contatori Ore (ore di lavoro) e Cicli (pezzi totali) -> /api/assets/contatori/ingest/
    ogni OGNI_CONTATORI secondi (il portale li registra sui contatori dei piani di manutenzione).

Le macchine da leggere arrivano dal portale (Asset › Configurazione › Macchine collegate):
GET /api/assets/contatori/ingest/config/ all'avvio e ogni AGGIORNA_ELENCO secondi.

Configurazione solo da variabili d'ambiente (mai nel codice):
  PORTALE_URL    es. https://portale.dominio.local   (senza / finale)
  PORTALE_TOKEN  token del collector (Asset › Configurazione › Macchine collegate › Collector)
  PORTALE_CA     facoltativo: certificato della CA interna (file .pem) se HTTPS non e' pubblico
Senza PORTALE_URL o PORTALE_TOKEN il collector lavora come prima, senza inviare nulla.

Le macchine scritte a mano in machines.json (senza portale) vanno al portale solo se hanno "asset_tag"
e non sono in "ombra".

Store-and-forward: ogni cambio di stato o di allarmi diventa un evento nella coda ``outbox`` di
machines.db (``collega(db)``), insieme alle letture dei contatori; la coda si svuota in ordine e un
record si cancella solo quando il portale l'ha ricevuto. Ogni evento porta la chiave ``evento``
(``<istanza del database>:<numero progressivo>``): il portale scarta quelli gia' applicati, quindi un
reinvio non duplica niente. Se il portale non risponde si riprova con attesa crescente fino a 5 minuti.
Il battito (tutte le macchine ogni minuto) parte solo a coda vuota e porta la chiave dell'ultimo
evento consegnato: aggiorna l'«ultimo segnale» senza poter scavalcare eventi non ancora arrivati.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import ssl
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

log = logging.getLogger("collector.portale")

URL_STATO = "/api/assets/contatori/ingest/stato/"
URL_CONTATORI = "/api/assets/contatori/ingest/"
URL_CONFIG = "/api/assets/contatori/ingest/config/"
AGGIORNA_ELENCO = 300    # s - ogni quanto si riscarica l'elenco delle macchine dal portale
INVIO_CAMBI = 5          # s - ogni quanto si guarda se qualche macchina e' cambiata
BATTITO = 60             # s - invio di tutte le macchine anche senza cambi
OGNI_CONTATORI = 3600    # s - invio dei contatori
TIMEOUT = 15             # s
RIPROVA = 60             # s - prima attesa dopo un invio non riuscito (poi raddoppia)
RIPROVA_MAX = 300        # s - attesa massima tra due tentativi
LOTTO = 200              # record della coda per ogni invio
# Unita' delle ore lette dalla CNC scelta nel portale ("hours_unit"); vuota = quella del modello dati.
UNITA_ORE = {"h": 1.0, "min": 1 / 60, "s": 1 / 3600}


def iso_utc(d: dt.datetime | None) -> str | None:
    """datetime naive in UTC (come nel collector) -> ISO 8601 con fuso."""
    return d.replace(tzinfo=dt.timezone.utc).isoformat() if d else None


def fattore_ore(m: Any) -> float | None:
    """Moltiplicatore valore letto -> ore: l'unita' scelta nel portale vince su quella del modello dati."""
    fattore: float | None = UNITA_ORE.get(getattr(m, "hours_unit", "") or "") or (m.spec or {}).get("hours_factor")
    return fattore


def _normalizzato(m: Any, metodo: str, mappa: str, chiave: str) -> str:
    """Modalita'/esecuzione: dal metodo della macchina se c'e', altrimenti dalla mappa del modello dati."""
    funzione = getattr(m, metodo, None)
    if callable(funzione):
        return str(funzione())
    return str((m.spec or {}).get(mappa, {}).get(m.values.get(chiave), ""))


def _ora_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class Portale:
    def __init__(self, base: str, token: str, machines: list[Any], prog_name: Callable[[Any], str],
                 ca: str | None = None) -> None:
        self.base = base.rstrip("/")
        self.prog_name = prog_name
        self.token = token
        self.machines = [m for m in machines if m.asset_tag and not getattr(m, "ombra", False)]
        self.ctx = ssl.create_default_context(cafile=ca) if ca else None
        self.ultimo_errore: str | None = None
        self.db: Any = None          # machines.db (outbox), da collega()
        self.ultimo_evento: dict[str, str] = {}   # asset_tag -> chiave dell'ultimo evento consegnato
        self.inviati = 0
        self.tentativi = 0

    def collega(self, db: Any) -> None:
        """Coda persistente in machines.db; riprende le chiavi degli ultimi eventi consegnati."""
        self.db = db
        for chiave, valore in db.q("SELECT chiave, valore FROM meta WHERE chiave LIKE 'evento:%'"):
            self.ultimo_evento[chiave[len("evento:"):]] = valore

    @classmethod
    def da_ambiente(cls, machines: list[Any], prog_name: Callable[[Any], str]) -> Portale | None:
        base, token = os.environ.get("PORTALE_URL", "").strip(), os.environ.get("PORTALE_TOKEN", "").strip()
        if not base or not token:
            return None
        return cls(base, token, machines, prog_name, os.environ.get("PORTALE_CA", "").strip() or None)

    # ---------------- HTTP ----------------
    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(
            self.base + path, data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"})
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=self.ctx) as resp:
            esito: dict[str, Any] = json.loads(resp.read().decode("utf-8") or "{}")
            return esito

    def scarica_macchine(self) -> list[dict[str, Any]] | None:
        """Elenco delle macchine scritto nel portale (formato di machines.json), None se non si riesce."""
        req = urllib.request.Request(self.base + URL_CONFIG, headers={"Authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=self.ctx) as resp:
                dati = json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            self._errore(f"il portale ha risposto {e.code} sull'elenco delle macchine"
                         + (" (token o rete non ammessi)" if e.code in (401, 403) else ""))
            return None
        except Exception as e:  # noqa: BLE001 - rete, certificato, portale fermo: si usa l'ultimo elenco
            self._errore(f"elenco delle macchine non scaricato ({type(e).__name__}: {e})")
            return None
        macchine = dati.get("machines")
        return [m for m in macchine if isinstance(m, dict)] if isinstance(macchine, list) else None

    async def invia(self, path: str, body: dict[str, Any]) -> bool:
        """True se il portale ha risposto; gli errori si scrivono una volta sola finche' durano."""
        try:
            esito = await asyncio.to_thread(self._post, path, body)
        except urllib.error.HTTPError as e:
            self._errore(f"il portale ha risposto {e.code} su {path}"
                         + (" (token o rete non ammessi)" if e.code in (401, 403) else ""))
            return False
        except Exception as e:  # noqa: BLE001 - rete, certificato, portale fermo: si riprova
            self._errore(f"portale non raggiungibile ({type(e).__name__}: {e})")
            return False
        if self.ultimo_errore:
            log.info("portale di nuovo raggiungibile")
            self.ultimo_errore = None
        for r in esito.get("results", []):
            if r.get("status") == "rejected":
                log.warning("portale: %s scartata (%s)", r.get("asset_tag"), r.get("reason"))
        return True

    def _errore(self, msg: str) -> None:
        if msg != self.ultimo_errore:
            log.warning("%s: riprovo al prossimo giro", msg)
            self.ultimo_errore = msg

    # ---------------- contenuti ----------------
    def riga_stato(self, m: Any) -> dict[str, Any] | None:
        if m.state is None:
            return None
        allarmi = [{"codice": a["code"], "testo": a.get("message") or "", "severita": a.get("severity") or 0,
                    "dal": iso_utc(a.get("since"))} for a in m.alarms.values()]
        online = m.state not in ("OFFLINE", "NON_LEGGIBILE")
        programma = m.programma() if callable(getattr(m, "programma", None)) else self.prog_name(m.values.get("program"))
        return {
            "asset_tag": m.asset_tag,
            "stato": m.state,
            "dal": iso_utc(m.state_since),
            "programma": programma if online else "",
            "modalita": _normalizzato(m, "modalita", "mode_map", "mode") if online else "",
            "esecuzione": _normalizzato(m, "esecuzione", "exec_map", "exec") if online else "",
            "pezzi": m.values.get("cnt_part_counter") if online else None,
            "allarmi": allarmi,
            # per il portale: valore delle ore come lo da' la CNC (da confrontare col display), matricola e modello
            "ore_lette": m.values.get("cnt_operation_time") if online else None,
            "matricola": getattr(m, "found_serial", "") or "",
            "modello": getattr(m, "data_model", "") or "",
            "errore": (getattr(m, "errore", "") or "")[:300] if not online else "",
        }

    @staticmethod
    def righe_contatori(m: Any) -> list[dict[str, Any]]:
        if not m.counters_at or m.state == "OFFLINE":
            return []
        read_at = iso_utc(m.counters_at)
        out: list[dict[str, Any]] = []
        ore = m.values.get("cnt_operation_time")
        fattore = fattore_ore(m)
        if ore is not None and fattore:
            out.append({"asset_tag": m.asset_tag, "meter_type": "HOURS", "value": round(float(ore) * fattore, 2), "read_at": read_at})
        pezzi = m.values.get("cnt_parts_overall")
        if pezzi is not None:
            out.append({"asset_tag": m.asset_tag, "meter_type": "CYCLES", "value": int(pezzi), "read_at": read_at})
        return out

    # ---------------- coda ----------------
    def accoda_stato(self, m: Any) -> None:
        """Evento di una macchina cambiata: in coda subito, con lo stato di questo istante."""
        riga = self.riga_stato(m)
        if riga is None or self.db is None:
            m.portale_cambiata = True
            return
        self.db.accoda(URL_STATO, m.asset_tag, json.dumps(riga), _ora_utc())
        m.portale_cambiata = False

    def accoda_contatori(self) -> None:
        righe = [r for m in self.machines for r in self.righe_contatori(m)]
        if righe and self.db is not None:
            self.db.accoda(URL_CONTATORI, "*", json.dumps(righe), _ora_utc())

    async def svuota(self) -> bool:
        """Manda la coda in ordine, a lotti; True se e' vuota alla fine, False al primo invio non riuscito."""
        if self.db is None:
            return True
        self.db.pota_outbox()
        while True:
            righe = self.db.da_inviare(LOTTO)
            if not righe:
                return True
            path = righe[0][1]
            lotto: list[tuple[int, str, str, str]] = []
            for r in righe:   # record consecutivi dello stesso tipo, nell'ordine della coda
                if r[1] != path:
                    break
                lotto.append(r)
            if path == URL_STATO:
                eventi: list[dict[str, Any]] = []
                for id_, _p, _m, corpo in lotto:
                    riga = json.loads(corpo)
                    riga["evento"] = f"{self.db.istanza}:{id_:012d}"
                    eventi.append(riga)
                body = {"macchine": eventi}
            else:
                body = {"readings": [x for _i, _p, _m, corpo in lotto for x in json.loads(corpo)]}
            if not await self.invia(path, body):
                return False
            self.db.inviati(lotto[-1][0])
            self.inviati += len(lotto)
            if path == URL_STATO:
                for riga in body["macchine"]:
                    self.ultimo_evento[riga["asset_tag"]] = riga["evento"]
                    self.db.imposta_meta(f"evento:{riga['asset_tag']}", riga["evento"])

    def battito(self) -> list[dict[str, Any]]:
        """Lo stato di tutte le macchine, con la chiave dell'ultimo evento gia' consegnato."""
        righe = []
        for m in self.machines:
            riga = self.riga_stato(m)
            if riga is None:
                continue
            if m.asset_tag in self.ultimo_evento:
                riga["evento"] = self.ultimo_evento[m.asset_tag]
            righe.append(riga)
        return righe

    # ---------------- ciclo ----------------
    async def run(self) -> None:
        log.info("portale: invio a %s", self.base)
        loop = asyncio.get_running_loop()
        t_battito = t_contatori = pausa = 0.0
        while True:
            t0 = loop.time()
            if t0 >= t_contatori:
                if self.db is None:
                    righe = [r for m in self.machines for r in self.righe_contatori(m)]
                    ok = not righe or await self.invia(URL_CONTATORI, {"readings": righe})
                    t_contatori = t0 + (OGNI_CONTATORI if ok else RIPROVA)
                else:
                    self.accoda_contatori()
                    t_contatori = t0 + OGNI_CONTATORI
            if self.db is None and any(m.portale_cambiata for m in self.machines):
                t_battito = 0.0   # senza coda (uso diretto): le macchine cambiate partono subito
            if t0 >= pausa:
                if await self.svuota():
                    self.tentativi = 0
                    if t0 >= t_battito:
                        righe = self.battito()
                        if not righe or await self.invia(URL_STATO, {"macchine": righe}):
                            for m in self.machines:
                                m.portale_cambiata = False
                            t_battito = t0 + BATTITO
                else:
                    # Portale giu': i record restano in coda; si riprova con attesa crescente fino a 5 minuti.
                    self.tentativi += 1
                    pausa = t0 + min(RIPROVA * 2 ** (self.tentativi - 1), RIPROVA_MAX)
            await asyncio.sleep(INVIO_CAMBI)
