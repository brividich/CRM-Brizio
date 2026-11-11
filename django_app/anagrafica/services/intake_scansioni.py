"""Acquisizione delle scansioni da una cartella di rete.

Il gesto che questo modulo elimina è banale e per questo pesante: aprire il
portale, cercare la giornata, caricare il file. Con una cartella condivisa la
fotocopiatrice ci scrive dentro premendo «Scansione» e il portale se lo prende
da solo — chi ha erogato il corso non tocca un computer.

Funziona perché il foglio **si autodescrive**: il QR contiene il token, il token
dice quale foglio, il foglio dice quale giornata e con quale elenco di persone.
Nessuna convenzione sul nome del file, che è la prima cosa che nessuno rispetta.

COSA SUCCEDE A OGNI PASSAGGIO

Per ogni file trovato: si legge il QR, si risolve il foglio, si archivia il file
nell'archivio privato, si misura l'inchiostro cella per cella, si scrive la riga
nel registro letture. Poi il file si sposta in ``elaborati`` o in ``errori``,
così la cartella d'ingresso resta pulita e niente viene letto due volte.

QUELLO CHE NON FA DA SÉ

Di default **non registra le presenze**: prepara la proposta e la lascia lì. La
presenza a un corso è un atto con valore legale e una misura di pixel non è una
firma. L'automatismo esiste, si accende dalle impostazioni, e anche acceso si
ferma davanti alle celle dubbie — perché è lì che serve un occhio.

REGOLE DI PRUDENZA

Un file che sta ancora arrivando non si tocca (la fotocopiatrice scrive a
pezzi): si aspetta che dimensione e data di modifica siano stabili, con una sola
attesa per tutto il lotto. Un file già in archivio non si rielabora: l'impronta
SHA-256 del contenuto si confronta con le letture già registrate, così un
passaggio interrotto fra l'archiviazione e lo spostamento non archivia due volte
e non riapplica le presenze. Due passaggi sulla stessa cartella non si
sovrappongono (lock per cartella, condiviso col pulsante «Prova adesso») e un
giro dura al massimo ``BUDGET_SECONDI``: il resto lo prende il giro dopo. Un
guasto su un file non ferma gli altri.
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import time
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["elabora_cartella", "ESTENSIONI_ACCETTATE", "lock_cartella", "file_stabili"]

ESTENSIONI_ACCETTATE = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}

# Un file appena depositato può essere ancora in scrittura: la fotocopiatrice
# scrive a pezzi e leggerlo a metà darebbe un errore inventato.
ATTESA_STABILITA_SECONDI = 2.0

# Un giro deve stare largamente sotto il timeout del worker (120 s): oltre il
# budget ci si ferma e il resto lo prende il passaggio successivo.
BUDGET_SECONDI = 90.0

# Il lock scade da sé se il worker muore senza rilasciarlo.
LOCK_TTL_SECONDI = 300

# Impronte dei file già elaborati: prima difesa, veloce. La seconda, durevole,
# è il registro letture con il file archiviato.
_CHIAVE_SHA = "anagrafica:intake_scansioni:sha:{}"
_TTL_SHA = 90 * 24 * 3600

MESSAGGIO_IN_CORSO = "Un passaggio sulla cartella è già in corso: l'esito compare tra poco."


@contextmanager
def lock_cartella(ambito: str, cartella: str):
    """Lock per cartella: produce ``True`` se preso, ``False`` se un passaggio è già in corso.

    Condiviso fra lavoro periodico e pulsanti «Prova»/«Leggi ora»: due passaggi
    sulla stessa cartella leggerebbero e archivierebbero due volte lo stesso file.
    """
    from django.core.cache import cache

    impronta = hashlib.sha1((cartella or "").strip().lower().encode("utf-8")).hexdigest()[:16]
    chiave = f"intake:lock:{ambito}:{impronta}"
    try:
        preso = bool(cache.add(chiave, 1, LOCK_TTL_SECONDI))
    except Exception:
        logger.warning("Lock della cartella non disponibile (%s): procedo senza", ambito, exc_info=True)
        preso, chiave = True, ""
    try:
        yield preso
    finally:
        if preso and chiave:
            try:
                cache.delete(chiave)
            except Exception:
                logger.warning("Rilascio del lock fallito (%s)", ambito, exc_info=True)


def _firma_file(percorso: Path):
    try:
        st = percorso.stat()
        return (st.st_size, st.st_mtime)
    except OSError:
        return None


def file_stabili(candidati: list[Path], attesa: float) -> list[Path]:
    """I file che hanno finito di arrivare: una sola attesa per tutto il lotto."""
    if not candidati:
        return []
    prima = {p: _firma_file(p) for p in candidati}
    if attesa:
        time.sleep(attesa)
    return [p for p in candidati if prima[p] is not None and _firma_file(p) == prima[p]]


class _Esito:
    """Contatori del passaggio, per il riepilogo mostrato in pagina."""

    def __init__(self):
        self.esaminati = 0
        self.letti = 0
        self.errori = 0
        self.rifiutati = 0
        self.presenze_scritte = 0
        self.gia_elaborati = 0
        self.rimandati = 0
        self.dettagli: list[str] = []

    def come_dizionario(self) -> dict:
        return {
            "esaminati": self.esaminati, "letti": self.letti,
            "errori": self.errori, "rifiutati": self.rifiutati,
            "presenze_scritte": self.presenze_scritte,
            "gia_elaborati": self.gia_elaborati, "rimandati": self.rimandati,
            "dettagli": self.dettagli,
        }

    def _code(self) -> list[str]:
        parti = []
        if self.gia_elaborati:
            parti.append(f"{self.gia_elaborati} già elaborati in precedenza")
        if self.rimandati:
            parti.append(f"{self.rimandati} rimandati al prossimo giro")
        return parti

    def riepilogo(self) -> str:
        if not self.esaminati:
            return " · ".join(["Nessun file da elaborare.", *self._code()])
        parti = [f"{self.esaminati} file esaminati", f"{self.letti} letti"]
        if self.presenze_scritte:
            parti.append(f"{self.presenze_scritte} presenze registrate")
        if self.rifiutati:
            parti.append(f"{self.rifiutati} non riconosciuti")
        if self.errori:
            parti.append(f"{self.errori} in errore")
        return " · ".join(parti + self._code())


def _sposta(percorso: Path, radice: Path, sottocartella: str) -> str:
    """Sposta il file elaborato. Un fallimento qui non è fatale."""
    try:
        destinazione = radice / sottocartella
        destinazione.mkdir(parents=True, exist_ok=True)
        finale = destinazione / percorso.name
        if finale.exists():
            gambo, estensione = os.path.splitext(percorso.name)
            finale = destinazione / f"{gambo}-{int(time.time())}{estensione}"
        shutil.move(str(percorso), str(finale))
        return str(finale)
    except Exception:
        logger.exception("Spostamento della scansione fallito (%s)", percorso)
        return ""


def _gia_elaborato(sha: str, nome: str, dimensione: int) -> bool:
    """Lo stesso contenuto è già passato di qui?

    La fonte di verità è il registro letture: una riga della cartella con stesso
    nome e dimensione il cui file archiviato ha la stessa impronta. La cache
    risparmia solo la rilettura dell'archivio, e da sola non basta mai: senza la
    riga nel registro il file si rielabora.
    """
    from django.core.cache import cache

    from ..models_formazione import TrainingScanLog
    from .archivio_scansioni import apri_archiviata

    percorsi = list(
        TrainingScanLog.objects
        .filter(origine="CARTELLA", nome_file=nome, dimensione=dimensione,
                esito__in=("OK", "RIFIUTATO"))
        .order_by("-id")
        .values_list("percorso", flat=True)[:5]
    )
    if not percorsi:
        return False
    try:
        if cache.get(_CHIAVE_SHA.format(sha)):
            return True
    except Exception:
        pass
    for percorso in percorsi:
        fh = apri_archiviata(percorso)
        if fh is None:
            continue
        try:
            if hashlib.sha256(fh.read()).hexdigest() == sha:
                return True
        except Exception:
            continue
        finally:
            try:
                fh.close()
            except Exception:
                pass
    return False


def _segna_elaborato(sha: str) -> None:
    from django.core.cache import cache

    try:
        cache.set(_CHIAVE_SHA.format(sha), 1, _TTL_SHA)
    except Exception:
        logger.warning("Impronta della scansione non salvata in cache", exc_info=True)


def _trova_foglio(contenuto: bytes, nome_file: str):
    """Foglio firme corrispondente al QR, e il token letto."""
    from core.qr import leggi_codici

    from ..models_formazione import TrainingSignatureSheet

    for codice in leggi_codici(contenuto, nome_file):
        token = codice.strip().upper()[:16]
        foglio = (
            TrainingSignatureSheet.objects
            .select_related("lezione", "lezione__sessione")
            .filter(token=token)
            .first()
        )
        if foglio is not None:
            return foglio, token
    return None, ""


def _conferma_consentita(config, esito_lettura: dict) -> tuple[bool, str]:
    """La lettura può registrarsi da sola? In caso contrario, perché no."""
    if not config.conferma_automatica:
        return False, ""
    if config.auto_solo_senza_dubbie and esito_lettura.get("n_dubbie"):
        return False, "celle dubbie presenti: lasciata alla conferma manuale"
    if config.auto_solo_se_tutti_firmati:
        righe = esito_lettura.get("righe") or []
        if righe and esito_lettura.get("n_firmati", 0) < len(righe):
            return False, "non tutti gli attesi risultano firmati: lasciata alla conferma manuale"
    return True, ""


def _elabora_file(percorso: Path, radice: Path, config, esito: _Esito) -> None:
    """Un singolo file. Non solleva: un guasto non deve fermare la cartella."""
    from .archivio_scansioni import archivia_scansione, registra_lettura
    from .lettura_foglio_firme import ErroreLettura, analizza_scansione

    nome = percorso.name
    try:
        contenuto = percorso.read_bytes()
    except OSError:
        logger.exception("Scansione non leggibile dalla cartella (%s)", percorso)
        esito.esaminati += 1
        esito.errori += 1
        esito.dettagli.append(f"{nome}: file non leggibile dalla cartella")
        return

    sha = hashlib.sha256(contenuto).hexdigest()
    if _gia_elaborato(sha, nome, len(contenuto)):
        # Passaggio precedente interrotto dopo l'archiviazione: niente seconda
        # copia in archivio, niente presenze riapplicate. Si finisce lo spostamento.
        esito.gia_elaborati += 1
        esito.dettagli.append(f"{nome}: già elaborato in precedenza")
        if config.sposta_elaborati:
            _sposta(percorso, radice, "elaborati")
        return

    esito.esaminati += 1
    archivio, dimensione = archivia_scansione(contenuto, nome)
    comune = {
        "nome_file": nome, "percorso": archivio,
        "dimensione": dimensione, "origine": "CARTELLA",
    }

    foglio, token = _trova_foglio(contenuto, nome)
    if foglio is None:
        motivo = ("Nessun QR di un foglio firme riconosciuto in questa scansione. "
                  "Il file resta archiviato e consultabile dal registro letture.")
        registra_lettura(**comune, esito="RIFIUTATO", messaggio=motivo)
        _segna_elaborato(sha)
        esito.rifiutati += 1
        esito.dettagli.append(f"{nome}: nessun foglio riconosciuto")
        if config.sposta_elaborati:
            _sposta(percorso, radice, "errori")
        return

    lezione = foglio.lezione
    comune.update({"lezione": lezione, "foglio": foglio, "token_letto": token})

    try:
        lettura = analizza_scansione(foglio, contenuto, nome)
    except ErroreLettura as exc:
        registra_lettura(**comune, esito="ERRORE", messaggio=str(exc))
        esito.errori += 1
        esito.dettagli.append(f"{nome}: {exc}")
        if config.sposta_elaborati:
            _sposta(percorso, radice, "errori")
        return
    except Exception:
        logger.exception("Lettura della scansione fallita (%s)", percorso)
        motivo = "Errore imprevisto nella lettura della scansione."
        registra_lettura(**comune, esito="ERRORE", messaggio=motivo)
        esito.errori += 1
        esito.dettagli.append(f"{nome}: errore imprevisto")
        if config.sposta_elaborati:
            _sposta(percorso, radice, "errori")
        return

    scritte = 0
    consentita, perche_no = _conferma_consentita(config, lettura)
    if consentita:
        from .formazione_integrita import EdizioneChiusa
        from .formazione_presenze import applica_firme_lezione

        firme = {
            riga["legacy_id"]: (bool(riga["ingresso"]), bool(riga["uscita"]))
            for riga in lettura["righe"]
        }
        try:
            # Il metodo resta UPLOAD: la firma è arrivata da una scansione, e da
            # dove sia entrata nel portale lo dice già `origine` sul registro.
            scritte = len(applica_firme_lezione(lezione, firme))
        except EdizioneChiusa as exc:
            perche_no = f"{exc} Scansione archiviata, presenze non registrate."
            scritte = 0
        except Exception:
            logger.exception("Registrazione automatica delle presenze fallita (%s)", percorso)
            perche_no = "registrazione automatica fallita: lasciata alla conferma manuale"
            scritte = 0

    registra_lettura(
        **comune, esito="OK", esito_lettura=lettura,
        messaggio=perche_no, presenze_scritte=scritte,
    )
    _segna_elaborato(sha)

    esito.letti += 1
    esito.presenze_scritte += scritte
    coda = f", {scritte} presenze registrate" if scritte else ""
    esito.dettagli.append(
        f"{nome}: foglio {token}, {lettura['n_firmati']}/{len(lettura['righe'])} firmate{coda}"
    )

    if config.sposta_elaborati:
        _sposta(percorso, radice, "elaborati")


def elabora_cartella(config=None, *, limite: int | None = None) -> dict:
    """Passa in rassegna la cartella di acquisizione. Ritorna il riepilogo.

    Non solleva mai: è pensata per girare da un lavoro periodico, dove
    un'eccezione si tradurrebbe in un meccanismo fermo che nessuno nota.
    Se un altro passaggio sulla stessa cartella è in corso ritorna subito con
    ``in_corso=True`` senza toccare l'ultimo esito annotato.
    """
    from ..models_formazione import TrainingScanIntakeConfig

    config = config or TrainingScanIntakeConfig.load()
    esito = _Esito()

    if not config.attiva:
        return {**esito.come_dizionario(), "riepilogo": "Acquisizione da cartella spenta."}

    cartella = (config.cartella or "").strip()
    if not cartella:
        return {**esito.come_dizionario(), "riepilogo": "Nessuna cartella configurata."}

    with lock_cartella("scansioni_formazione", cartella) as preso:
        if not preso:
            return {**esito.come_dizionario(), "riepilogo": MESSAGGIO_IN_CORSO, "in_corso": True}
        return _elabora_radice(config, cartella, esito, limite)


def _elabora_radice(config, cartella: str, esito: _Esito, limite: int | None) -> dict:
    from django.utils import timezone

    inizio = time.monotonic()
    radice = Path(cartella)
    try:
        esiste = radice.is_dir()
    except OSError:
        esiste = False
    if not esiste:
        messaggio = f"Cartella non raggiungibile: {cartella}"
        logger.warning("Acquisizione scansioni: %s", messaggio)
        _annota(config, timezone.now(), messaggio)
        return {**esito.come_dizionario(), "riepilogo": messaggio}

    try:
        candidati = sorted(
            (p for p in radice.iterdir()
             if p.is_file() and p.suffix.lower() in ESTENSIONI_ACCETTATE),
            key=lambda p: p.name,
        )
    except OSError:
        messaggio = f"Cartella non leggibile: {cartella}"
        logger.exception("Acquisizione scansioni: %s", messaggio)
        _annota(config, timezone.now(), messaggio)
        return {**esito.come_dizionario(), "riepilogo": messaggio}

    massimo = limite if limite is not None else (config.max_file_per_giro or 25)
    # I file che stanno ancora arrivando restano lì per il prossimo giro.
    pronti = file_stabili(candidati[:massimo], ATTESA_STABILITA_SECONDI)
    for indice, percorso in enumerate(pronti):
        if time.monotonic() - inizio > BUDGET_SECONDI:
            esito.rimandati += len(pronti) - indice
            break
        try:
            _elabora_file(percorso, radice, config, esito)
        except Exception:
            logger.exception("Elaborazione della scansione fallita (%s)", percorso)
            esito.errori += 1

    _annota(config, timezone.now(), esito.riepilogo())
    return {**esito.come_dizionario(), "riepilogo": esito.riepilogo()}


def _annota(config, quando, riepilogo: str) -> None:
    """Scrive in configurazione com'è andato l'ultimo passaggio."""
    try:
        config.ultima_esecuzione = quando
        config.ultimo_esito = riepilogo
        config.save(update_fields=["ultima_esecuzione", "ultimo_esito"])
    except Exception:
        logger.exception("Annotazione dell'ultimo passaggio fallita")
