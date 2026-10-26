"""Archivio dei log: un file al giorno, catena di hash riga per riga, sigillo giornaliero.

Formato di una riga (JSON, chiavi ordinate, una per riga)::

    {"d": <dati della riga>, "f": <id fonte>, "n": <numero riga>, "r": "<ricevuto il, ISO>", "x": "<hash>"}

``x`` = SHA-256 di ``hash della riga prima`` + ``la riga senza x`` (JSON canonico). La
prima riga di ogni giorno parte da ``seme(giorno)``. Una riga cambiata, tolta o aggiunta
rompe la catena da lì in avanti.

Chiusura del giorno (:func:`sigilla_mancanti`, dal ciclo del qcluster): il file viene
compresso (``.jsonl.gz``), riletto per ricalcolare la catena e chiuso da un
:class:`~registro_log.models.SigilloGiorno`::

    hash_sigillo = SHA-256("v1|giorno|righe|hash_ultima_riga|sha256_file|hash_precedente")

dove ``hash_precedente`` è il sigillo del giorno prima: i giorni sono legati tra loro come
le righe dentro il giorno. Anche i giorni senza righe hanno un sigillo (continuità).

Le copie (cartella di rete e/o SharePoint) portano anche ``<giorno>.sigillo.json`` con
le regole per rifare il calcolo senza il portale.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

ZERO = "0" * 64
VERSIONE = "v1"
COME_VERIFICARE = (
    "Ogni riga e' JSON con chiavi ordinate. Togliere la chiave x, riscrivere la riga con chiavi "
    "ordinate e separatori ',' ':' (UTF-8, senza escape ASCII): x = SHA-256(x della riga prima + riga). "
    "La prima riga parte da SHA-256('registro_log|AAAA-MM-GG'). "
    "hash_sigillo = SHA-256('v1|AAAA-MM-GG|righe|hash_ultima_riga|sha256_file|hash_precedente')."
)


def cartella() -> Path:
    from .models import Impostazioni

    scelta = (Impostazioni.corrente().cartella_archivio or "").strip()
    return Path(scelta) if scelta else Path(settings.PRIVATE_ATTACHMENTS_ROOT) / "registro_log" / "archivio"


def percorso(giorno: date, base: Path | None = None) -> Path:
    base = base or cartella()
    return base / f"{giorno:%Y}" / f"{giorno:%m}" / f"registro-{giorno:%Y-%m-%d}.jsonl"


def percorso_gz(giorno: date, base: Path | None = None) -> Path:
    return percorso(giorno, base).with_suffix(".jsonl.gz")


def seme(giorno: date) -> str:
    return hashlib.sha256(f"registro_log|{giorno:%Y-%m-%d}".encode()).hexdigest()


def canonica(corpo: dict) -> str:
    return json.dumps(corpo, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def hash_riga(precedente: str, corpo: dict) -> str:
    return hashlib.sha256((precedente + canonica(corpo)).encode("utf-8")).hexdigest()


def hash_sigillo(giorno: date, righe: int, ultima: str, sha_file: str, precedente: str) -> str:
    testo = f"{VERSIONE}|{giorno:%Y-%m-%d}|{righe}|{ultima}|{sha_file}|{precedente}"
    return hashlib.sha256(testo.encode("utf-8")).hexdigest()


# ── Scrittura (solo il processo del raccoglitore) ─────────────────────────────


class Scrittore:
    """Scrive le righe del giorno in corso. Un solo scrittore per cartella (il raccoglitore)."""

    def __init__(self, base: Path | None = None):
        self.base = base or cartella()
        self.giorno: date | None = None
        self._fh = None
        self.n = 0
        self.ultimo = ZERO
        self.riparazioni: list[str] = []

    def _apri(self, giorno: date) -> None:
        self.chiudi()
        p = percorso(giorno, self.base)
        p.parent.mkdir(parents=True, exist_ok=True)
        self.giorno, self.n, self.ultimo = giorno, 0, seme(giorno)
        if p.exists():
            self._riprendi(p)
        self._fh = open(p, "a", encoding="utf-8", newline="\n")

    def _riprendi(self, p: Path) -> None:
        """Riapertura nello stesso giorno (riavvio): riparte dall'ultima riga intera.

        Una riga tagliata a metà (arresto durante la scrittura) viene tolta dal file e
        annotata: finisce tra le interruzioni, così la verifica la ritrova spiegata.
        """
        dati = p.read_bytes()
        buone = dati if dati.endswith(b"\n") or not dati else dati[: dati.rfind(b"\n") + 1]
        if len(buone) != len(dati):
            with open(p, "r+b") as fh:
                fh.truncate(len(buone))
            self.riparazioni.append(f"{p.name}: tolta una riga incompleta di {len(dati) - len(buone)} byte")
        righe = buone.decode("utf-8", errors="replace").splitlines()
        if righe:
            ultima = json.loads(righe[-1])
            self.n, self.ultimo = int(ultima["n"]), str(ultima["x"])

    def scrivi(self, fonte_id: int | None, dati: dict, ricevuto: datetime | None = None) -> tuple[date, int]:
        ricevuto = ricevuto or timezone.now()
        giorno = timezone.localdate(ricevuto)
        if giorno != self.giorno or self._fh is None:
            self._apri(giorno)
        n = self.n + 1
        corpo = {"d": dati, "f": fonte_id, "n": n, "r": ricevuto.isoformat(timespec="milliseconds")}
        x = hash_riga(self.ultimo, corpo)
        try:
            self._fh.write(canonica({**corpo, "x": x}) + "\n")
        except Exception:
            # Riga forse scritta a metà: si chiude il file, alla prossima scrittura _riprendi la toglie.
            fh, self._fh = self._fh, None
            try:
                fh.close()
            except Exception:  # noqa: BLE001
                pass
            raise
        self.n, self.ultimo = n, x
        return giorno, n

    def flush(self) -> None:
        if self._fh is not None:
            self._fh.flush()
            os.fsync(self._fh.fileno())

    def chiudi(self) -> None:
        if self._fh is not None:
            try:
                self.flush()
            finally:
                self._fh.close()
                self._fh = None


# ── Lettura e verifica ───────────────────────────────────────────────────────


def _apri_lettura(giorno: date, base: Path | None = None):
    gz = percorso_gz(giorno, base)
    if gz.exists():
        return gzip.open(gz, "rt", encoding="utf-8")
    p = percorso(giorno, base)
    if p.exists():
        return open(p, encoding="utf-8")
    return None


def leggi_riga(giorno: date, numero: int) -> dict | None:
    """La riga ``numero`` del giorno (per il dettaglio di un evento). None se il file non c'è più."""
    fh = _apri_lettura(giorno)
    if fh is None:
        return None
    with fh:
        for testo in fh:
            if f'"n":{numero},' in testo:
                riga = json.loads(testo)
                if int(riga.get("n", -1)) == numero:
                    return riga
    return None


def ricalcola(righe_testo, giorno: date) -> dict:
    """Ricalcola la catena di un giorno. ``{"righe", "ultimo", "errore"}``; errore vuoto se integra."""
    precedente, n = seme(giorno), 0
    for i, testo in enumerate(righe_testo, start=1):
        testo = testo.rstrip("\n")
        if not testo:
            continue
        try:
            riga = json.loads(testo)
            x = riga.pop("x")
        except (ValueError, KeyError):
            return {"righe": n, "ultimo": precedente, "errore": f"riga {i} non leggibile"}
        if int(riga.get("n", -1)) != n + 1:
            return {"righe": n, "ultimo": precedente, "errore": f"riga {i}: numerazione interrotta (attesa {n + 1})"}
        atteso = hash_riga(precedente, riga)
        if atteso != x:
            return {"righe": n, "ultimo": precedente, "errore": f"riga {i}: impronta diversa, il contenuto è stato cambiato"}
        precedente, n = x, n + 1
    return {"righe": n, "ultimo": precedente, "errore": ""}


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for blocco in iter(lambda: fh.read(1 << 20), b""):
            h.update(blocco)
    return h.hexdigest()


def _sigillo_prima(giorno: date):
    from .models import SigilloGiorno

    return SigilloGiorno.objects.filter(giorno__lt=giorno).order_by("-giorno").first()


def sigilla(giorno: date):
    """Comprime il file del giorno (se c'è), ricalcola la catena e crea il sigillo."""
    from .models import SigilloGiorno

    if SigilloGiorno.objects.filter(giorno=giorno).exists():
        return None
    base = cartella()
    p, gz = percorso(giorno, base), percorso_gz(giorno, base)
    if p.exists():
        tmp = gz.with_suffix(".gz.tmp")
        with open(p, "rb") as src, open(tmp, "wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as dst:
                shutil.copyfileobj(src, dst)
            raw.flush()
            os.fsync(raw.fileno())
        os.replace(tmp, gz)
        p.unlink()
    esito = {"righe": 0, "ultimo": "", "errore": ""}
    sha, byte, nome = "", 0, ""
    if gz.exists():
        with gzip.open(gz, "rt", encoding="utf-8") as fh:
            esito = ricalcola(fh, giorno)
        sha, byte, nome = _sha256_file(gz), gz.stat().st_size, str(gz.relative_to(base))
    prima = _sigillo_prima(giorno)
    precedente = prima.hash_sigillo if prima else ZERO
    s = SigilloGiorno.objects.create(
        giorno=giorno, file=nome, righe=esito["righe"], byte=byte, hash_ultima_riga=esito["ultimo"],
        sha256_file=sha, hash_precedente=precedente,
        hash_sigillo=hash_sigillo(giorno, esito["righe"], esito["ultimo"], sha, precedente),
        verificato_il=timezone.now(), verifica_ok=not esito["errore"],
        verifica_esito=esito["errore"] or "Catena integra alla chiusura del giorno.",
    )
    if esito["errore"]:
        logger.critical("Registro accessi: il giorno %s non torna già alla chiusura: %s", giorno, esito["errore"])
    # Seconda àncora: il sigillo finisce anche nell'audit del portale, che ha la sua catena mensile
    # (core.audit_sigilli). Per alterare un giorno andrebbero alterate due catene indipendenti.
    from core.audit import log_action

    log_action(None, "registro_log_sigillo", "registro_log", {
        "giorno": giorno.isoformat(), "righe": s.righe, "sha256_file": s.sha256_file, "hash_sigillo": s.hash_sigillo,
    })
    return s


def sigilla_mancanti(oggi: date | None = None, *, giorno_aperto: date | None = None) -> list:
    """Sigilla, in ordine, i giorni conclusi ancora senza sigillo.

    Si parte dal primo file d'archivio (o dal primo sigillo) fino a ieri; un giorno ancora
    aperto dal raccoglitore (``giorno_aperto``) non si tocca.
    """
    from .models import SigilloGiorno

    oggi = oggi or timezone.localdate()
    ultimo = SigilloGiorno.objects.order_by("-giorno").values_list("giorno", flat=True).first()
    if ultimo:
        inizio = ultimo + timedelta(days=1)
    else:
        giorni = sorted(_giorni_su_disco())
        if not giorni:
            return []
        inizio = giorni[0]
    creati, g = [], inizio
    while g < oggi:
        if giorno_aperto and g >= giorno_aperto:
            break
        s = sigilla(g)
        if s:
            creati.append(s)
        g += timedelta(days=1)
    return creati


def _giorni_su_disco() -> list[date]:
    base = cartella()
    out = []
    if not base.exists():
        return out
    for p in base.glob("*/*/registro-*.jsonl*"):
        try:
            out.append(datetime.strptime(p.name[9:19], "%Y-%m-%d").date())
        except ValueError:
            continue
    return out


def verifica_sigillo(s) -> tuple[bool, str]:
    """Ricontrolla un giorno: file presente, impronta del file, catena delle righe, sigillo."""
    if s.eliminato_il:
        return True, "File eliminato a fine conservazione: resta il sigillo."
    precedente_atteso = ZERO
    prima = _sigillo_prima(s.giorno)
    if prima:
        precedente_atteso = prima.hash_sigillo
    if s.hash_precedente != precedente_atteso:
        return False, "Il collegamento con il giorno prima non torna: la catena dei giorni è rotta."
    if hash_sigillo(s.giorno, s.righe, s.hash_ultima_riga, s.sha256_file, s.hash_precedente) != s.hash_sigillo:
        return False, "Il sigillo non corrisponde ai suoi dati: è stato modificato."
    if not s.file:
        return (s.righe == 0), ("Giorno senza righe." if s.righe == 0 else "Manca il file del giorno.")
    gz = cartella() / s.file
    if not gz.exists():
        return False, "Il file del giorno non c'è più."
    if _sha256_file(gz) != s.sha256_file:
        return False, "Il file del giorno è cambiato dopo la chiusura."
    with gzip.open(gz, "rt", encoding="utf-8") as fh:
        esito = ricalcola(fh, s.giorno)
    if esito["errore"]:
        return False, esito["errore"]
    if (esito["righe"], esito["ultimo"]) != (s.righe, s.hash_ultima_riga):
        return False, "Il numero di righe o l'ultima impronta non coincidono con il sigillo."
    return True, f"Integro: {s.righe} righe."


def verifica(sigilli) -> dict:
    """Verifica e annota i sigilli indicati. ``{"verificati", "rotti": [giorni]}``."""
    from .models import SigilloGiorno

    rotti, n = [], 0
    for s in sigilli:
        ok, testo = verifica_sigillo(s)
        SigilloGiorno.objects.filter(pk=s.pk).update(verificato_il=timezone.now(), verifica_ok=ok, verifica_esito=testo[:500])
        n += 1
        if not ok:
            rotti.append(s.giorno)
    if rotti:
        logger.critical("Registro accessi: archivio NON integro nei giorni %s", rotti)
    return {"verificati": n, "rotti": rotti}


def verifica_a_rotazione(quanti: int = 7) -> dict:
    """Ogni giorno: i sigilli verificati da più tempo (tutto l'archivio ruota in qualche settimana)."""
    from .models import SigilloGiorno

    coda = SigilloGiorno.objects.filter(eliminato_il__isnull=True).order_by("verificato_il", "giorno")[:quanti]
    return verifica(list(coda))


# ── Copie e conservazione ────────────────────────────────────────────────────


def meta_sigillo(s) -> bytes:
    return json.dumps({
        "giorno": f"{s.giorno:%Y-%m-%d}", "versione": VERSIONE, "righe": s.righe, "byte": s.byte,
        "hash_ultima_riga": s.hash_ultima_riga, "sha256_file": s.sha256_file,
        "hash_precedente": s.hash_precedente, "hash_sigillo": s.hash_sigillo,
        "creato_il": s.creato_il.isoformat() if s.creato_il else "", "come_verificare": COME_VERIFICARE,
    }, ensure_ascii=False, indent=2).encode("utf-8")


def copia_mancanti() -> dict:
    """Copia i giorni sigillati nella seconda destinazione (cartella di rete e/o SharePoint)."""
    from .models import Impostazioni, SigilloGiorno

    imp = Impostazioni.corrente()
    dest = (imp.copia_cartella or "").strip()
    sp_on = bool(imp.copia_sharepoint)
    esito = {"copiati": 0, "errori": 0, "configurato": bool(dest or sp_on)}
    if not esito["configurato"]:
        return esito
    for s in SigilloGiorno.objects.filter(copia_il__isnull=True, eliminato_il__isnull=True).order_by("giorno")[:60]:
        try:
            nomi = []
            if s.file:
                nomi.append((Path(s.file).name, (cartella() / s.file).read_bytes()))
            nomi.append((f"registro-{s.giorno:%Y-%m-%d}.sigillo.json", meta_sigillo(s)))
            if dest:
                sotto = Path(dest) / f"{s.giorno:%Y}" / f"{s.giorno:%m}"
                sotto.mkdir(parents=True, exist_ok=True)
                for nome, dati in nomi:
                    (sotto / nome).write_bytes(dati)
            if sp_on:
                from core import sharepoint_upload as sp

                drive, base_sp = sp.destinazione()
                if not (drive and base_sp):
                    raise RuntimeError("Cartella SharePoint dell'audit non configurata (Centrale › Audit).")
                for nome, dati in nomi:
                    try:
                        sp.carica(nome, dati, drive_id=drive, cartella=f"{base_sp}/registro-log/{s.giorno:%Y}")
                    except sp.SharePointUploadError as exc:
                        if "nameAlreadyExists" not in str(exc):  # già caricato in un giro interrotto
                            raise
            SigilloGiorno.objects.filter(pk=s.pk).update(copia_il=timezone.now(), copia_esito="Copiato.")
            esito["copiati"] += 1
        except Exception as exc:  # noqa: BLE001 - si riprova al giro dopo, in ordine
            logger.warning("Registro accessi: copia del %s non riuscita: %s", s.giorno, exc)
            SigilloGiorno.objects.filter(pk=s.pk).update(copia_esito=str(exc)[:500])
            esito["errori"] += 1
            break
    return esito


def applica_conservazione(oggi: date | None = None) -> dict:
    """Elimina i file oltre la conservazione (mai sotto 6 mesi). Il sigillo resta, con la data."""
    from .models import EventoRegistro, Impostazioni, SigilloGiorno

    oggi = oggi or timezone.localdate()
    mesi = max(6, int(Impostazioni.corrente().conservazione_mesi or 12))
    limite = oggi - timedelta(days=round(mesi * 30.44))
    eliminati = 0
    for s in SigilloGiorno.objects.filter(giorno__lt=limite, eliminato_il__isnull=True).order_by("giorno"):
        if s.file:
            try:
                (cartella() / s.file).unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("Registro accessi: file del %s non eliminato: %s", s.giorno, exc)
                continue
        SigilloGiorno.objects.filter(pk=s.pk).update(eliminato_il=timezone.now())
        eliminati += 1
    # A blocchi: una DELETE enorme su SQL Server terrebbe bloccata la tabella a lungo.
    righe = 0
    while True:
        ids = list(EventoRegistro.objects.filter(quando__date__lt=limite).values_list("pk", flat=True)[:5000])
        if not ids:
            break
        righe += EventoRegistro.objects.filter(pk__in=ids).delete()[0]
    return {"giorni_eliminati": eliminati, "eventi_eliminati": righe, "limite": limite.isoformat()}


def spazio_libero_mb(base: Path | None = None) -> int | None:
    """MB liberi sul disco dell'archivio (None se la cartella non è raggiungibile)."""
    base = base or cartella()
    try:
        base.mkdir(parents=True, exist_ok=True)
        return int(shutil.disk_usage(base).free // (1024 * 1024))
    except OSError:
        return None
