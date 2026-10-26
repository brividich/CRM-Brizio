"""Processo del raccoglitore (``manage.py registro_log``): riceve, archivia, indicizza.

Fili di lavoro:

- **scrittore** (uno solo): prende dalla coda, scrive la riga nell'archivio del giorno,
  riconosce gli eventi importanti e li salva nell'indice a gruppi (ogni 2 secondi o 500
  righe). I segnalibri dei registri Windows si salvano solo dopo che le righe lette sono
  già su disco: un arresto a metà non perde eventi (al massimo li rilegge).
- **syslog**: UDP e TCP, vedi ``sorgenti/syslog.py``.
- **principale**: ogni minuto legge le fonti Windows, lascia il segnale di vita, ricarica
  le fonti cambiate dal portale, annota le interruzioni (righe riparate, messaggi scartati).
"""
from __future__ import annotations

import logging
import os
import queue
import socket
import threading
import time
from datetime import timedelta

from django.db import connections
from django.utils import timezone

from . import archivio, regole
from .sorgenti import windows

logger = logging.getLogger(__name__)

GIRO_SECONDI = 60
RICARICA_SECONDI = 300
FLUSH_SECONDI = 2
FLUSH_RIGHE = 500
DEDUP_MINUTI = 10


def close_old_connections() -> None:
    """Come quella di Django, ma non tocca una connessione dentro una transazione (test, blocchi atomic)."""
    for conn in connections.all(initialized_only=True):
        if not conn.in_atomic_block:
            conn.close_if_unusable_or_obsolete()


def privilegiati() -> set[str]:
    """Account (minuscoli, senza dominio) da trattare come amministratori: AD privilegiati + elenco AdS."""
    from .models import AccountAD, AmministratoreSistema

    nomi = {a.sam.lower() for a in AccountAD.objects.exclude(gruppi_privilegiati=[]).only("sam", "gruppi_privilegiati")
            if a.gruppi_privilegiati}
    for ads in AmministratoreSistema.objects.all():
        if ads.attivo:
            nomi.update(a.split("\\")[-1].split("@")[0].lower() for a in ads.lista_account())
    return nomi


class Raccoglitore:
    def __init__(self, *, coda_max: int = 50000):
        self.coda: queue.Queue = queue.Queue(maxsize=coda_max)
        self.scrittore = archivio.Scrittore()
        self.fonti: dict[int, object] = {}
        self.ip_fonte: dict[str, int] = {}
        self.privilegiati: set[str] = set()
        self.imp = None
        self.ricevitore = None
        self._dedup: dict[str, float] = {}
        self._fermo = threading.Event()
        self._errore_scrittore = ""
        self.avviato_il = timezone.now()

    # ── configurazione ──────────────────────────────────────────────────────
    def carica(self) -> None:
        from .models import FonteLog, Impostazioni

        self.imp = Impostazioni.corrente()
        fonti = {f.pk: f for f in FonteLog.objects.filter(attiva=True)}
        self.fonti = fonti
        self.ip_fonte = {ip: f.pk for f in fonti.values() if f.tipo == FonteLog.TIPO_SYSLOG for ip in f.lista_ip()}
        try:
            self.privilegiati = privilegiati()
        except Exception as exc:  # noqa: BLE001 - senza elenco si indicizzano solo gli accessi interattivi
            logger.warning("Registro accessi: elenco degli amministratori non letto: %s", exc)

    def fonte_per_ip(self, ip: str):
        return self.ip_fonte.get(ip)

    # ── scrittore ───────────────────────────────────────────────────────────
    def _indice(self, fonte, dati: dict, giorno, n: int, ricevuto) -> object | None:
        from .models import EventoRegistro

        if fonte is not None and fonte.tipo == "syslog":
            idx = regole.classifica_syslog(dati)
            quando = regole.quando_syslog(dati, ricevuto)
            host, canale, event_id = dati.get("host") or dati.get("ip") or "", dati.get("app", "")[:80], None
        else:
            idx = regole.classifica_windows(dati, self.privilegiati)
            quando = regole.quando_windows(dati) or ricevuto
            host, canale, event_id = dati.get("pc", ""), dati.get("canale", ""), dati.get("id")
        if idx is None:
            return None
        if idx.dedup:
            chiave = f"{fonte.pk if fonte else ''}|{host}|{idx.dedup}".lower()
            ora = time.monotonic()
            if ora - self._dedup.get(chiave, -1e9) < DEDUP_MINUTI * 60:
                return None
            self._dedup[chiave] = ora
            if len(self._dedup) > 20000:
                limite = ora - DEDUP_MINUTI * 60
                self._dedup = {k: v for k, v in self._dedup.items() if v >= limite}
        account = (idx.account or "")[:150]
        nome = account.split("\\")[-1].split("@")[0].lower()
        etichetta, gravita = regole.CATEGORIE.get(idx.categoria, (idx.categoria, "info"))
        imp = self.imp
        return EventoRegistro(
            quando=quando, ricevuto_il=ricevuto, fonte_id=fonte.pk if fonte else None,
            fonte_nome=(fonte.nome if fonte else "")[:120], host=host[:255], canale=canale[:80], event_id=event_id,
            categoria=idx.categoria, esito=idx.esito, gravita=idx.gravita or gravita, account=account,
            dominio=(idx.dominio or "")[:120], account_target=(idx.account_target or "")[:255],
            ip_origine=(idx.ip_origine or "")[:64], tipo_accesso=(idx.tipo_accesso or "")[:40],
            descrizione=(idx.descrizione or etichetta)[:400], privilegiato=nome in self.privilegiati,
            fuori_orario=bool(imp and regole.fuori_orario(quando, imp.orario_inizio, imp.orario_fine)),
            archivio_giorno=giorno, archivio_riga=n,
        )

    def _scrivi_lotto(self, eventi: list, segnalibri: list, contatori: dict) -> None:
        from .models import EventoRegistro, FonteLog

        self.scrittore.flush()
        close_old_connections()
        if eventi:
            EventoRegistro.objects.bulk_create(eventi, batch_size=200)
        oggi = timezone.localdate()
        for fonte_id, (righe, ultimo) in contatori.items():
            f = FonteLog.objects.filter(pk=fonte_id).only("giorno_conteggio", "righe_oggi").first()
            if f is None:
                continue
            base = f.righe_oggi if f.giorno_conteggio == oggi else 0
            FonteLog.objects.filter(pk=fonte_id).update(righe_oggi=base + righe, giorno_conteggio=oggi, ultimo_evento_il=ultimo)
        for fonte_id, canale, valore in segnalibri:
            f = FonteLog.objects.filter(pk=fonte_id).first()
            if f is not None and valore is not None:
                s = dict(f.segnalibri or {})
                s[canale] = int(valore)
                FonteLog.objects.filter(pk=fonte_id).update(segnalibri=s)

    def ciclo_scrittore(self) -> None:
        from .models import FonteLog

        eventi, segnalibri, contatori = [], [], {}
        ultimo_flush = time.monotonic()
        righe_dal_flush = 0
        while not (self._fermo.is_set() and self.coda.empty()):
            try:
                voce = self.coda.get(timeout=0.5)
            except queue.Empty:
                voce = None
            try:
                if voce is not None:
                    tipo = voce[0]
                    if tipo == "segnalibro":
                        segnalibri.append(voce[1:])
                        righe_dal_flush = FLUSH_RIGHE  # forza il salvataggio: le righe lette sono su disco
                    else:
                        if tipo == "syslog":
                            _, fonte_id, raw, ip, ricevuto = voce
                            dati = regole.parse_syslog(raw, ip)
                        else:  # ("windows", fonte_id, dati, ricevuto)
                            _, fonte_id, dati, ricevuto = voce
                        fonte = self.fonti.get(fonte_id) or FonteLog.objects.filter(pk=fonte_id).first()
                        giorno, n = self.scrittore.scrivi(fonte_id, dati, ricevuto)
                        righe_dal_flush += 1
                        ev = self._indice(fonte, dati, giorno, n, ricevuto)
                        if ev is not None:
                            eventi.append(ev)
                        c = contatori.get(fonte_id, (0, None))
                        contatori[fonte_id] = (c[0] + 1, ricevuto)
                if righe_dal_flush and (righe_dal_flush >= FLUSH_RIGHE or time.monotonic() - ultimo_flush >= FLUSH_SECONDI):
                    self._scrivi_lotto(eventi, segnalibri, contatori)
                    eventi, segnalibri, contatori = [], [], {}
                    righe_dal_flush, ultimo_flush = 0, time.monotonic()
                    self._errore_scrittore = ""
            except Exception as exc:  # noqa: BLE001 - lo scrittore non deve morire: errore nel segnale di vita
                logger.exception("Registro accessi: errore dello scrittore")
                self._errore_scrittore = f"{type(exc).__name__}: {exc}"[:300]
                time.sleep(2)
        if eventi or segnalibri or contatori:
            self._scrivi_lotto(eventi, segnalibri, contatori)
        self.scrittore.chiudi()

    # ── Windows ─────────────────────────────────────────────────────────────
    def leggi_windows(self) -> None:
        from .models import FonteLog

        for fonte in list(self.fonti.values()):
            if fonte.tipo not in (FonteLog.TIPO_WINDOWS, FonteLog.TIPO_WEF) or self._fermo.is_set():
                continue
            host = "" if fonte.tipo == FonteLog.TIPO_WEF else fonte.host.strip()
            canali = ["ForwardedEvents"] if fonte.tipo == FonteLog.TIPO_WEF else fonte.lista_canali()
            tutto = fonte.tipo == FonteLog.TIPO_WEF or fonte.eventi == FonteLog.EVENTI_TUTTO
            fresca = FonteLog.objects.filter(pk=fonte.pk).values_list("segnalibri", flat=True).first() or {}
            errori = []
            for canale in canali:
                try:
                    esito = windows.leggi_canale(canale, host, fresca.get(canale), tutto=tutto)
                except Exception as exc:  # noqa: BLE001 - errore della fonte, si annota e si va avanti
                    errori.append(f"{canale}: {exc}")
                    continue
                ricevuto = timezone.now()
                for dati in esito.eventi:
                    self.coda.put(("windows", fonte.pk, dati, ricevuto))
                self.coda.put(("segnalibro", fonte.pk, canale, esito.segnalibro))
                if esito.persi:
                    apri_interruzione(fonte, "eventi_persi", f"{canale}: circa {esito.persi} record sovrascritti sul server "
                                      "prima della lettura (registro troppo piccolo o raccoglitore fermo a lungo).",
                                      chiudi_subito=True)
            aggiorna_stato_fonte(fonte, errori)

    # ── segnale di vita e manutenzione ───────────────────────────────────────
    def battito(self) -> None:
        from .models import StatoRaccoglitore

        close_old_connections()
        for testo in self.scrittore.riparazioni:
            apri_interruzione(None, "file_riparato", testo, chiudi_subito=True)
        self.scrittore.riparazioni = []
        if self.ricevitore is not None:
            scartati, sconosciuti = self.ricevitore.preleva_contatori()
            for ip, quanti in scartati.items():
                fonte = self.fonti.get(self.ip_fonte.get(ip))
                apri_interruzione(fonte, "sovraccarico", f"{quanti} messaggi da {ip} scartati nell'ultimo minuto "
                                  "(troppi al secondo o coda piena).", chiudi_subito=True)
            if sconosciuti:
                registra_sconosciuti(sconosciuti)
        StatoRaccoglitore.objects.update_or_create(pk=1, defaults={
            "battito_il": timezone.now(), "avviato_il": self.avviato_il, "host": socket.gethostname()[:120],
            "pid": os.getpid(), "giorno_corrente": self.scrittore.giorno or timezone.localdate(),
            "righe_oggi": self.scrittore.n if self.scrittore.giorno == timezone.localdate() else 0,
            "syslog_in_ascolto": self.ricevitore.in_ascolto if self.ricevitore else "",
            "errore": self._errore_scrittore,
        })

    def avvia_syslog(self) -> None:
        from .sorgenti.syslog import Ricevitore

        imp = self.imp
        voluto = bool(imp and imp.attivo and imp.syslog_attivo)
        attuale = self.ricevitore
        firma = (imp.syslog_indirizzo, imp.syslog_porta, imp.syslog_tcp) if imp else None
        if attuale is not None and (not voluto or (attuale.indirizzo, attuale.porta, attuale.tcp) != firma):
            attuale.ferma()
            self.ricevitore = None
        if voluto and self.ricevitore is None:
            r = Ricevitore(imp.syslog_indirizzo, imp.syslog_porta, imp.syslog_tcp, self.coda, self.fonte_per_ip)
            try:
                r.avvia()
                self.ricevitore = r
            except OSError as exc:
                self._errore_scrittore = f"Syslog non in ascolto su {imp.syslog_porta}: {exc}"[:300]
                logger.error("Registro accessi: %s", self._errore_scrittore)

    def ferma(self) -> None:
        self._fermo.set()

    def esegui(self, *, controlla_uscita=None) -> None:
        """Gira finché ``ferma()`` o finché ``controlla_uscita()`` non dice di uscire."""
        self.carica()
        filo = threading.Thread(target=self.ciclo_scrittore, name="registro-scrittore", daemon=True)
        filo.start()
        ultima_ricarica = time.monotonic()
        try:
            while not self._fermo.is_set():
                inizio = time.monotonic()
                if inizio - ultima_ricarica >= RICARICA_SECONDI:
                    close_old_connections()
                    self.carica()
                    ultima_ricarica = inizio
                self.avvia_syslog()
                if self.imp and self.imp.attivo:
                    self.leggi_windows()
                self.battito()
                if controlla_uscita and controlla_uscita():
                    break
                self._fermo.wait(max(1.0, GIRO_SECONDI - (time.monotonic() - inizio)))
        finally:
            self._fermo.set()
            if self.ricevitore is not None:
                self.ricevitore.ferma()
            filo.join(timeout=60)


# ── funzioni condivise con il ciclo del qcluster ─────────────────────────────


def apri_interruzione(fonte, motivo: str, dettaglio: str, *, chiudi_subito: bool = False):
    """Apre (o lascia aperta) un'interruzione. Con ``chiudi_subito`` è un fatto puntuale già concluso."""
    from .models import Interruzione

    ora = timezone.now()
    fonte_id = getattr(fonte, "pk", None)
    if not chiudi_subito:
        aperta = Interruzione.objects.filter(fonte_id=fonte_id, motivo=motivo, al__isnull=True).first()
        if aperta:
            return aperta
    return Interruzione.objects.create(
        fonte_id=fonte_id, fonte_nome=getattr(fonte, "nome", "")[:120], motivo=motivo, dal=ora,
        al=ora if chiudi_subito else None, dettaglio=dettaglio[:500],
    )


def chiudi_interruzioni(fonte, motivo: str, quando=None) -> int:
    from .models import Interruzione

    return Interruzione.objects.filter(fonte_id=getattr(fonte, "pk", None), motivo=motivo, al__isnull=True).update(
        al=quando or timezone.now())


def aggiorna_stato_fonte(fonte, errori: list[str]) -> None:
    from .models import FonteLog

    ora = timezone.now()
    if errori:
        FonteLog.objects.filter(pk=fonte.pk).update(stato=FonteLog.STATO_ERRORE, ultimo_errore="\n".join(errori)[:2000],
                                                    ultima_lettura_il=ora)
        apri_interruzione(fonte, "errore_lettura", errori[0])
    else:
        FonteLog.objects.filter(pk=fonte.pk).update(stato=FonteLog.STATO_OK, ultimo_errore="", ultima_lettura_il=ora)
        chiudi_interruzioni(fonte, "errore_lettura", ora)


def registra_sconosciuti(conteggi) -> None:
    """Indirizzi che mandano syslog senza essere in nessuna fonte (ultimi 7 giorni, in SiteConfig)."""
    import json

    from core.models import SiteConfig

    chiave = "registro_log.syslog_sconosciuti"
    try:
        dati = json.loads(SiteConfig.get(chiave, "") or "{}")
    except ValueError:
        dati = {}
    ora = timezone.now()
    limite = (ora - timedelta(days=7)).isoformat()
    dati = {ip: v for ip, v in dati.items() if v.get("ultimo", "") >= limite}
    for ip, quanti in conteggi.items():
        v = dati.get(ip, {"messaggi": 0})
        dati[ip] = {"messaggi": int(v.get("messaggi", 0)) + int(quanti), "ultimo": ora.isoformat()}
    SiteConfig.objects.update_or_create(chiave=chiave, defaults={"valore": json.dumps(dati)[:20000]})
