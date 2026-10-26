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
LETTORI_WINDOWS = 4
LETTORI_PC = 8
PC_OGNI_MINUTI = 10  # ogni PC acceso si rilegge ogni 10 minuti
PC_SPENTO_MINUTI = 15  # un PC spento si riprova dopo 15 minuti
SESSIONI_MAX = 100000  # accessi di rete ricordati per sapere da quale PC arriva chi apre un file
SPAZIO_MINIMO_MB = 2048
SCRITTURA_TENTATIVI_INTERRUZIONE = 30  # ~1 minuto di errori prima dell'interruzione
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
        self._errore_syslog = ""
        self._scarti: dict[int, int] = {}
        self._in_lettura: dict[int, object] = {}
        self._in_lettura_pc: dict[int, object] = {}
        self._lettori = None
        self._lettori_pc = None
        self.raccoglitori: set[str] = set()
        self.cartelle: dict[int, list] = {}
        self._sessioni: dict[tuple[str, str], str] = {}
        self.avviato_il = timezone.now()

    # ── configurazione ──────────────────────────────────────────────────────
    def carica(self) -> None:
        import getpass

        from .models import FonteLog, Impostazioni

        self.imp = Impostazioni.corrente()
        fonti = {f.pk: f for f in FonteLog.objects.filter(attiva=True)}
        self.fonti = fonti
        self.ip_fonte = {ip: f.pk for f in fonti.values() if f.tipo == FonteLog.TIPO_SYSLOG for ip in f.lista_ip()}
        self.cartelle = {f.pk: f.lista_cartelle() for f in fonti.values() if f.cartelle_file}
        self.raccoglitori = self.imp.lista_raccoglitori()
        try:
            self.raccoglitori.add(getpass.getuser().lower())  # l'account con cui gira questo raccoglitore
        except Exception:  # noqa: BLE001 - senza nome utente si usa solo l'elenco delle impostazioni
            pass
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
            quando = regole.quando_syslog(dati, ricevuto)
            if dati.get("t"):
                self._scarti[fonte.pk] = int((ricevuto - quando).total_seconds())
            idx = regole.classifica_syslog(dati)
            host, canale, event_id = dati.get("host") or dati.get("ip") or "", dati.get("app", "")[:80], None
        else:
            host, canale, event_id = dati.get("pc", ""), dati.get("canale", ""), dati.get("id")
            self._ricorda_sessione(host, dati)
            idx = regole.classifica_windows(
                dati, self.privilegiati, livello_file=getattr(fonte, "audit_file", "") or "",
                usb=bool(getattr(fonte, "audit_usb", False)), cartelle=self.cartelle.get(getattr(fonte, "pk", None)),
                raccoglitori=self.raccoglitori)
            quando = regole.quando_windows(dati) or ricevuto
            if idx is not None and idx.categoria.startswith("file_") and not idx.ip_origine:
                # Sul file server il 4663 non dice da quale PC: lo dice l'accesso di rete con lo stesso ID di sessione.
                idx.ip_origine = self._sessioni.get((host.lower(), (dati.get("dati") or {}).get("SubjectLogonId", "")), "")
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
            oggetto=(idx.oggetto or "")[:500], quantita=idx.quantita,
            fuori_orario=bool(imp and regole.fuori_orario(quando, imp.orario_inizio, imp.orario_fine)),
            archivio_giorno=giorno, archivio_riga=n,
        )

    def _ricorda_sessione(self, host: str, dati: dict) -> None:
        """4624: ID di sessione → PC di provenienza (IP o nome), per i 4663 che seguono sullo stesso server."""
        if dati.get("id") != 4624:
            return
        x = dati.get("dati") or {}
        da = regole._ip(x.get("IpAddress", "")) or (x.get("WorkstationName") or "").strip("-\\ ")
        sessione = x.get("TargetLogonId", "")
        if not (da and sessione):
            return
        if len(self._sessioni) >= SESSIONI_MAX:
            self._sessioni = dict(list(self._sessioni.items())[SESSIONI_MAX // 2:])  # via le più vecchie
        self._sessioni[(host.lower(), sessione)] = da[:64]

    def _scrivi_lotto(self, eventi: list, segnalibri: list, contatori: dict) -> None:
        from .models import EventoRegistro, FonteLog, Postazione

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
        for fonte_id, scarto in self._scarti.items():
            FonteLog.objects.filter(pk=fonte_id).update(scarto_orologio_s=scarto)
        self._scarti = {}
        for tipo, chi, canale, valore in segnalibri:
            modello = Postazione if tipo == "segnalibro_pc" else FonteLog
            attuali = modello.objects.filter(pk=chi).values_list("segnalibri", flat=True).first()
            if attuali is not None and valore is not None:
                s = dict(attuali or {})
                s[canale] = int(valore)
                modello.objects.filter(pk=chi).update(segnalibri=s)

    def ciclo_scrittore(self) -> None:
        from .models import FonteLog

        eventi, segnalibri, contatori = [], [], {}
        ultimo_flush = time.monotonic()
        righe_dal_flush = 0
        pendente, tentativi = None, 0
        while not (self._fermo.is_set() and self.coda.empty() and pendente is None):
            if pendente is not None:
                voce, pendente = pendente, None
            else:
                try:
                    voce = self.coda.get(timeout=0.5)
                except queue.Empty:
                    voce = None
            scritta = False
            try:
                if voce is not None:
                    tipo = voce[0]
                    if tipo in ("segnalibro", "segnalibro_pc"):
                        segnalibri.append(voce)
                        righe_dal_flush = FLUSH_RIGHE  # forza il salvataggio: le righe lette sono su disco
                    else:
                        if tipo == "syslog":
                            _, fonte_id, raw, ip, ricevuto = voce
                            dati = regole.parse_syslog(raw, ip)
                        else:  # ("windows", fonte_id, dati, ricevuto)
                            _, fonte_id, dati, ricevuto = voce
                        fonte = self.fonti.get(fonte_id) or FonteLog.objects.filter(pk=fonte_id).first()
                        if tipo == "windows":
                            dati = minimizza(dati, fonte)
                        giorno, n = self.scrittore.scrivi(fonte_id, dati, ricevuto)
                        scritta = True
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
                if tentativi:
                    chiudi_interruzioni(None, "errore_scrittura")
                tentativi = 0
                self._errore_scrittore = ""
            except Exception as exc:  # noqa: BLE001 - lo scrittore non deve morire né perdere la riga
                # La voce si riprova finché non va (disco pieno, cartella di rete giù): niente righe perse.
                if voce is not None and not voce[0].startswith("segnalibro") and not scritta:
                    pendente = voce  # già nel file: non si riscrive (il lotto per il database resta in memoria)
                tentativi += 1
                self._errore_scrittore = f"Scrittura dell'archivio non riuscita: {type(exc).__name__}: {exc}"[:300]
                if tentativi == 1:
                    logger.exception("Registro accessi: errore dello scrittore")
                if tentativi == SCRITTURA_TENTATIVI_INTERRUZIONE:
                    try:
                        apri_interruzione(None, "errore_scrittura", self._errore_scrittore)
                    except Exception:  # noqa: BLE001 - anche il database può essere giù
                        pass
                if self._fermo.is_set() and tentativi > 15:
                    break  # in uscita: le righe non scritte si rileggono dal segnalibro al riavvio
                time.sleep(2)
        if eventi or segnalibri or contatori:
            self._scrivi_lotto(eventi, segnalibri, contatori)
        self.scrittore.chiudi()

    # ── Windows ─────────────────────────────────────────────────────────────
    def leggi_windows(self) -> None:
        """Avvia in parallelo la lettura delle fonti Windows libere e non in pausa dopo errori.

        Un server lento o spento occupa un solo lettore: gli altri e il segnale di vita vanno avanti.
        """
        from concurrent.futures import ThreadPoolExecutor

        from .models import FonteLog

        if self._lettori is None:
            self._lettori = ThreadPoolExecutor(max_workers=LETTORI_WINDOWS, thread_name_prefix="registro-windows")
        ora = timezone.now()
        pause = dict(FonteLog.objects.filter(pk__in=list(self.fonti)).values_list("pk", "riprova_dopo"))
        for fonte in list(self.fonti.values()):
            if fonte.tipo == FonteLog.TIPO_DOMINIO and not self._fermo.is_set():
                self.leggi_postazioni(fonte, ora)
                continue
            if fonte.tipo not in (FonteLog.TIPO_WINDOWS, FonteLog.TIPO_WEF) or self._fermo.is_set():
                continue
            in_corso = self._in_lettura.get(fonte.pk)
            if in_corso is not None and not in_corso.done():
                continue
            if pause.get(fonte.pk) and pause[fonte.pk] > ora:
                continue
            self._in_lettura[fonte.pk] = self._lettori.submit(self._leggi_fonte_isolata, fonte)

    def _leggi_fonte_isolata(self, fonte) -> None:
        try:
            self.leggi_fonte(fonte)
        except Exception:  # noqa: BLE001 - un lettore non deve morire
            logger.exception("Registro accessi: lettura di %s non riuscita", fonte)
        finally:
            connections.close_all()  # connessioni di questo filo

    def leggi_fonte(self, fonte) -> None:
        from .models import FonteLog

        host = "" if fonte.tipo == FonteLog.TIPO_WEF else fonte.host.strip()
        canali = ["ForwardedEvents"] if fonte.tipo == FonteLog.TIPO_WEF else fonte.lista_canali()
        tutto = fonte.tipo == FonteLog.TIPO_WEF or fonte.eventi == FonteLog.EVENTI_TUTTO
        fresca = FonteLog.objects.filter(pk=fonte.pk).values_list("segnalibri", flat=True).first() or {}
        errori = []
        for canale in canali:
            try:
                esito = windows.leggi_canale(canale, host, fresca.get(canale), tutto=tutto,
                                             file=bool(fonte.audit_file), usb=fonte.audit_usb)
            except Exception as exc:  # noqa: BLE001 - errore della fonte, si annota e si va avanti
                errori.append(f"{canale}: {exc}")
                continue
            ricevuto = timezone.now()
            for dati in esito.eventi:
                self.coda.put(("windows", fonte.pk, dati, ricevuto))
            self.coda.put(("segnalibro", fonte.pk, canale, esito.segnalibro))
            nota = nota_eventi_persi(canale, esito)
            if nota:
                apri_interruzione(fonte, "eventi_persi", nota, chiudi_subito=True)
        aggiorna_stato_fonte(fonte, errori)

    # ── PC del dominio ──────────────────────────────────────────────────────
    def leggi_postazioni(self, fonte, ora) -> None:
        """Mette in lettura i PC della fonte da rileggere: accesi da più di 10 minuti, non esclusi, non in pausa."""
        from concurrent.futures import ThreadPoolExecutor

        from .models import Postazione

        if self._lettori_pc is None:
            self._lettori_pc = ThreadPoolExecutor(max_workers=LETTORI_PC, thread_name_prefix="registro-pc")
        limite = ora - timedelta(minutes=PC_OGNI_MINUTI)
        da_leggere = (Postazione.objects.filter(fonte_id=fonte.pk, in_ad=True, esclusa=False)
                      .exclude(riprova_dopo__gt=ora).exclude(ultima_lettura_il__gt=limite)
                      .order_by("ultima_lettura_il"))
        for pc in da_leggere:
            in_corso = self._in_lettura_pc.get(pc.pk)
            if (in_corso is not None and not in_corso.done()) or self._fermo.is_set():
                continue
            self._in_lettura_pc[pc.pk] = self._lettori_pc.submit(self._leggi_pc_isolato, fonte, pc)

    def _leggi_pc_isolato(self, fonte, pc) -> None:
        try:
            self.leggi_pc(fonte, pc)
        except Exception:  # noqa: BLE001 - un lettore non deve morire
            logger.exception("Registro accessi: lettura del PC %s non riuscita", pc)
        finally:
            connections.close_all()

    def leggi_pc(self, fonte, pc) -> None:
        from .models import FonteLog, Postazione

        ora = timezone.now()
        if not windows.acceso(pc.host):
            Postazione.objects.filter(pk=pc.pk).update(stato=Postazione.STATO_SPENTO,
                                                       riprova_dopo=ora + timedelta(minutes=PC_SPENTO_MINUTI))
            return
        fresca = Postazione.objects.filter(pk=pc.pk).values_list("segnalibri", flat=True).first() or {}
        errori, note, righe = [], [], 0
        for canale in fonte.lista_canali():
            try:
                esito = windows.leggi_canale(canale, pc.host, fresca.get(canale), tutto=fonte.eventi == FonteLog.EVENTI_TUTTO,
                                             file=bool(fonte.audit_file), usb=fonte.audit_usb)
            except Exception as exc:  # noqa: BLE001 - errore del PC, si annota e si va avanti
                errori.append(f"{canale}: {exc}")
                continue
            ricevuto = timezone.now()
            for dati in esito.eventi:
                self.coda.put(("windows", fonte.pk, dati, ricevuto))
            self.coda.put(("segnalibro_pc", pc.pk, canale, esito.segnalibro))
            righe += len(esito.eventi)
            nota = nota_eventi_persi(canale, esito)
            if nota:
                note.append(nota)  # sui PC resta sulla riga del PC: non è un'interruzione del registro
        oggi = timezone.localdate()
        attuale = Postazione.objects.filter(pk=pc.pk).values("righe_oggi", "giorno_conteggio", "errori_consecutivi").first() or {}
        base = attuale.get("righe_oggi", 0) if attuale.get("giorno_conteggio") == oggi else 0
        campi = {"ultima_lettura_il": ora, "ultimo_contatto_il": ora, "righe_oggi": base + righe, "giorno_conteggio": oggi}
        if errori:
            n = attuale.get("errori_consecutivi", 0) + 1
            campi.update(stato=Postazione.STATO_ERRORE, ultimo_errore="; ".join(errori)[:500], errori_consecutivi=n,
                         riprova_dopo=ora + pausa_dopo_errori(n))
        else:
            campi.update(stato=Postazione.STATO_OK, ultimo_errore="; ".join(note)[:500], errori_consecutivi=0, riprova_dopo=None)
            FonteLog.objects.filter(pk=fonte.pk).update(stato=FonteLog.STATO_OK, ultima_lettura_il=ora, ultimo_errore="")
        Postazione.objects.filter(pk=pc.pk).update(**campi)

    # ── segnale di vita e manutenzione ───────────────────────────────────────
    def battito(self) -> None:
        from .models import StatoRaccoglitore

        close_old_connections()
        spazio = archivio.spazio_libero_mb(self.scrittore.base)
        avviso = self._errore_scrittore or self._errore_syslog
        if spazio is None:
            avviso = avviso or "Cartella dell'archivio non raggiungibile."
        elif spazio < SPAZIO_MINIMO_MB:
            avviso = avviso or f"Spazio quasi esaurito sul disco dell'archivio: {spazio} MB liberi."
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
            "errore": avviso[:500], "spazio_libero_mb": spazio, "coda": self.coda.qsize(),
        })

    def ciclo_battito(self) -> None:
        """Segnale di vita su un filo suo: non aspetta letture lente né la coda."""
        while not self._fermo.is_set():
            try:
                self.battito()
            except Exception:  # noqa: BLE001 - riprova al giro dopo
                logger.exception("Registro accessi: segnale di vita non scritto")
            finally:
                connections.close_all()
            self._fermo.wait(GIRO_SECONDI)

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
                self._errore_syslog = f"Syslog non in ascolto sulla porta {imp.syslog_porta}: {exc}"[:300]
                logger.error("Registro accessi: %s", self._errore_syslog)
            else:
                self._errore_syslog = ""

    def ferma(self) -> None:
        self._fermo.set()

    def esegui(self, *, controlla_uscita=None) -> None:
        """Gira finché ``ferma()`` o finché ``controlla_uscita()`` non dice di uscire."""
        self.carica()
        filo = threading.Thread(target=self.ciclo_scrittore, name="registro-scrittore", daemon=True)
        filo.start()
        threading.Thread(target=self.ciclo_battito, name="registro-battito", daemon=True).start()
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
                if controlla_uscita and controlla_uscita():
                    break
                self._fermo.wait(max(1.0, GIRO_SECONDI - (time.monotonic() - inizio)))
        finally:
            self._fermo.set()
            if self.ricevitore is not None:
                self.ricevitore.ferma()
            for lettori in (self._lettori, self._lettori_pc):
                if lettori is not None:
                    lettori.shutdown(wait=False, cancel_futures=True)
            filo.join(timeout=60)


def minimizza(dati: dict, fonte) -> dict:
    """Prima di archiviare: il nome del documento stampato si tiene solo se la fonte lo prevede."""
    if dati.get("id") == 307 and "printservice" in (dati.get("prov") or "").lower() and not getattr(fonte, "stampe_nomi", False):
        interni = dict(dati.get("dati") or {})
        if interni.get("Param2"):
            interni["Param2"] = regole.DOCUMENTO_NASCOSTO
            dati = {**dati, "dati": interni}
    return dati


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


def nota_eventi_persi(canale: str, esito) -> str:
    """Testo per i record che non si sono potuti leggere (registro sovrascritto o svuotato da un altro programma)."""
    if esito.ricominciato:
        return (f"{canale}: il registro è stato svuotato sul server e la numerazione è ripartita: letto da capo; "
                "gli eventi tra l'ultima lettura e lo svuotamento possono mancare (es. BusinessLog con «Cancella "
                "Registro» attivo).")
    if esito.persi:
        return (f"{canale}: circa {esito.persi} record non letti perché già cancellati sul server (registro troppo "
                "piccolo, raccoglitore fermo a lungo o registro svuotato da un altro programma, es. BusinessLog con "
                "«Cancella Registro» attivo).")
    return ""


def pausa_dopo_errori(n: int) -> timedelta:
    """1, 2, 4, 8, 16, 30 minuti: un server spento non viene interrogato ogni minuto."""
    return timedelta(minutes=min(30, 2 ** max(0, n - 1)))


def aggiorna_stato_fonte(fonte, errori: list[str]) -> None:
    from .models import FonteLog

    ora = timezone.now()
    if errori:
        n = (FonteLog.objects.filter(pk=fonte.pk).values_list("errori_consecutivi", flat=True).first() or 0) + 1
        FonteLog.objects.filter(pk=fonte.pk).update(stato=FonteLog.STATO_ERRORE, ultimo_errore="\n".join(errori)[:2000],
                                                    ultima_lettura_il=ora, errori_consecutivi=n,
                                                    riprova_dopo=ora + pausa_dopo_errori(n))
        apri_interruzione(fonte, "errore_lettura", errori[0])
    else:
        FonteLog.objects.filter(pk=fonte.pk).update(stato=FonteLog.STATO_OK, ultimo_errore="", ultima_lettura_il=ora,
                                                    errori_consecutivi=0, riprova_dopo=None)
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
