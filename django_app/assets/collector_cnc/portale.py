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

Le macchine scritte a mano in machines.json (senza portale) vanno al portale solo se hanno "asset_tag".
"""
import asyncio
import datetime as dt
import json
import logging
import os
import ssl
import urllib.error
import urllib.request

log = logging.getLogger("collector.portale")

URL_STATO = "/api/assets/contatori/ingest/stato/"
URL_CONTATORI = "/api/assets/contatori/ingest/"
URL_CONFIG = "/api/assets/contatori/ingest/config/"
AGGIORNA_ELENCO = 300    # s - ogni quanto si riscarica l'elenco delle macchine dal portale
INVIO_CAMBI = 5          # s - ogni quanto si guarda se qualche macchina e' cambiata
BATTITO = 60             # s - invio di tutte le macchine anche senza cambi
OGNI_CONTATORI = 3600    # s - invio dei contatori
TIMEOUT = 15             # s
RIPROVA = 60             # s - attesa dopo un invio non riuscito
# Unita' delle ore lette dalla CNC scelta nel portale ("hours_unit"); vuota = quella del modello dati.
UNITA_ORE = {"h": 1.0, "min": 1 / 60, "s": 1 / 3600}


def iso_utc(d):
    """datetime naive in UTC (come nel collector) -> ISO 8601 con fuso."""
    return d.replace(tzinfo=dt.timezone.utc).isoformat() if d else None


def fattore_ore(m):
    """Moltiplicatore valore letto -> ore: l'unita' scelta nel portale vince su quella del modello dati."""
    return UNITA_ORE.get(getattr(m, "hours_unit", "") or "") or (m.spec or {}).get("hours_factor")


class Portale:
    def __init__(self, base, token, machines, prog_name, ca=None):
        self.base = base.rstrip("/")
        self.prog_name = prog_name
        self.token = token
        self.machines = [m for m in machines if m.asset_tag]
        self.ctx = ssl.create_default_context(cafile=ca) if ca else None
        self.ultimo_errore = None

    @classmethod
    def da_ambiente(cls, machines, prog_name):
        base, token = os.environ.get("PORTALE_URL", "").strip(), os.environ.get("PORTALE_TOKEN", "").strip()
        if not base or not token:
            return None
        return cls(base, token, machines, prog_name, os.environ.get("PORTALE_CA", "").strip() or None)

    # ---------------- HTTP ----------------
    def _post(self, path, body):
        req = urllib.request.Request(
            self.base + path, data=json.dumps(body).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"})
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=self.ctx) as resp:
            return json.loads(resp.read().decode("utf-8") or "{}")

    def scarica_macchine(self):
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

    async def invia(self, path, body):
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

    def _errore(self, msg):
        if msg != self.ultimo_errore:
            log.warning("%s: riprovo al prossimo giro", msg)
            self.ultimo_errore = msg

    # ---------------- contenuti ----------------
    def riga_stato(self, m):
        if m.state is None:
            return None
        spec = m.spec or {}
        allarmi = [{"codice": a["code"], "testo": a.get("message") or "", "severita": a.get("severity") or 0,
                    "dal": iso_utc(a.get("since"))} for a in m.alarms.values()]
        online = m.state != "OFFLINE"
        return {
            "asset_tag": m.asset_tag,
            "stato": m.state,
            "dal": iso_utc(m.state_since),
            "programma": self.prog_name(m.values.get("program")) if online else "",
            "modalita": spec.get("mode_map", {}).get(m.values.get("mode"), "") if online else "",
            "esecuzione": spec.get("exec_map", {}).get(m.values.get("exec"), "") if online else "",
            "pezzi": m.values.get("cnt_part_counter") if online else None,
            "allarmi": allarmi,
            # per il portale: valore delle ore come lo da' la CNC (da confrontare col display), matricola e modello
            "ore_lette": m.values.get("cnt_operation_time") if online else None,
            "matricola": getattr(m, "found_serial", "") or "",
            "modello": getattr(m, "data_model", "") or "",
        }

    @staticmethod
    def righe_contatori(m):
        if not m.counters_at or m.state == "OFFLINE":
            return []
        read_at, out = iso_utc(m.counters_at), []
        ore = m.values.get("cnt_operation_time")
        fattore = fattore_ore(m)
        if ore is not None and fattore:
            out.append({"asset_tag": m.asset_tag, "meter_type": "HOURS", "value": round(float(ore) * fattore, 2), "read_at": read_at})
        pezzi = m.values.get("cnt_parts_overall")
        if pezzi is not None:
            out.append({"asset_tag": m.asset_tag, "meter_type": "CYCLES", "value": int(pezzi), "read_at": read_at})
        return out

    # ---------------- ciclo ----------------
    async def run(self):
        log.info("portale: invio a %s", self.base)
        loop = asyncio.get_running_loop()
        t_battito = t_contatori = pausa = 0.0
        while True:
            t0 = loop.time()
            if not self.machines:
                await asyncio.sleep(INVIO_CAMBI)
                continue
            sporche = [m for m in self.machines if m.portale_cambiata]
            if t0 >= pausa and (sporche or t0 >= t_battito):
                scelte = self.machines if t0 >= t_battito else sporche
                righe = [r for r in (self.riga_stato(m) for m in scelte) if r]
                if not righe or await self.invia(URL_STATO, {"macchine": righe}):
                    for m in scelte:
                        m.portale_cambiata = False
                    if t0 >= t_battito:
                        t_battito = t0 + BATTITO
                else:
                    # Portale giu': si riprova tra un minuto con tutte le macchine, senza martellarlo.
                    pausa = t_battito = t0 + RIPROVA
            if t0 >= t_contatori:
                righe = [r for m in self.machines for r in self.righe_contatori(m)]
                ok = not righe or await self.invia(URL_CONTATORI, {"readings": righe})
                t_contatori = t0 + (OGNI_CONTATORI if ok else RIPROVA)
            await asyncio.sleep(INVIO_CAMBI)
