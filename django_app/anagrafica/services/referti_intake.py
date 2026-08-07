"""Acquisizione dei referti: dal file alla riga in coda.

IL GESTO CHE SPARISCE

La segreteria oggi passa i certificati per uno strumento a parte, guarda i nomi
proposti, conferma, e poi ricarica i file nel portale a mano. Con una cartella di
rete la fotocopiatrice ci scrive dentro premendo «Scansione» e il portale se li
prende da solo: quello che resta da fare è l'unica cosa che richiede davvero una
testa, cioè guardare i casi dubbi.

PERCHÉ NON SI CONFERMA DA SOLO (QUASI MAI)

Il foglio firme della formazione si identifica con un QR: il documento dice da sé
di quale foglio si tratta. Un referto no — va riconosciuto, e un riconoscimento è
una probabilità. Qui si tratta di attribuire un giudizio di idoneità a una
persona: sbagliare significa scrivere nella cartella sanitaria di Tizio quello che
riguarda Caio. Perciò la conferma automatica è spenta di default e, anche accesa,
si ferma davanti a tutto ciò che non è certo.

REGOLE DI PRUDENZA

Il file si archivia **sempre**, prima ancora di provare a leggerlo: su una lettura
fallita è l'unica cosa che permetta di capire perché. Un file ancora in arrivo non
si tocca. Un file già visto — stessa impronta — non si rielabora. E un guasto su
un file non ferma gli altri: la cartella si svuota comunque.

PIÙ CERTIFICATI IN UN PDF SOLO

Capita di scansionare la pila tutta insieme. Ogni pagina che contiene un blocco
anagrafico è un certificato a sé, e diventa una riga sua; le pagine che non lo
contengono sono la continuazione della precedente e si ignorano.
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import time
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = ["elabora_contenuto", "elabora_cartella", "ESTENSIONI_ACCETTATE"]

ESTENSIONI_ACCETTATE = {".pdf"}

# Un file appena depositato può essere ancora in scrittura: la fotocopiatrice
# scrive a pezzi e leggerlo a metà darebbe un errore inventato.
ATTESA_STABILITA_SECONDI = 2.0

# Oltre questo numero di pagine si smette di cercare altri certificati: una
# scansione con centinaia di pagine è un errore di chi l'ha prodotta, e leggerle
# tutte bloccherebbe il giro per tutti gli altri.
MAX_PAGINE_PER_FILE = 40


class _Esito:
    """Contatori del passaggio, per il riepilogo mostrato in pagina."""

    def __init__(self):
        self.esaminati = 0
        self.letti = 0
        self.registrati = 0
        self.in_coda = 0
        self.duplicati = 0
        self.rifiutati = 0
        self.errori = 0
        self.dettagli: list[str] = []

    def come_dizionario(self) -> dict:
        return {
            "esaminati": self.esaminati, "letti": self.letti,
            "registrati": self.registrati, "in_coda": self.in_coda,
            "duplicati": self.duplicati, "rifiutati": self.rifiutati,
            "errori": self.errori, "dettagli": self.dettagli,
        }

    def riepilogo(self) -> str:
        if not self.esaminati:
            return "Nessun file da elaborare."
        parti = [f"{self.esaminati} file esaminati"]
        if self.registrati:
            parti.append(f"{self.registrati} registrati")
        if self.in_coda:
            parti.append(f"{self.in_coda} da rivedere")
        if self.duplicati:
            parti.append(f"{self.duplicati} già presenti")
        if self.rifiutati:
            parti.append(f"{self.rifiutati} non riconosciuti")
        if self.errori:
            parti.append(f"{self.errori} in errore")
        return " · ".join(parti)


def _impronta(contenuto: bytes) -> str:
    return hashlib.sha256(contenuto or b"").hexdigest()


def _gia_visto(sha: str, pagina: int) -> bool:
    from ..models_sorveglianza import RefertoIntakeRiga

    if not sha:
        return False
    return RefertoIntakeRiga.objects.filter(sha256=sha, pagina=pagina).exists()


def _file_stabile(percorso: Path) -> bool:
    """Il file ha finito di arrivare?"""
    try:
        prima = percorso.stat().st_size
        time.sleep(ATTESA_STABILITA_SECONDI)
        return percorso.stat().st_size == prima
    except OSError:
        return False


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
        logger.exception("Spostamento del referto fallito (%s)", percorso)
        return ""


def _archivia(contenuto: bytes, nome_file: str) -> tuple[str, int]:
    """Il file nell'archivio privato cifrato, sotto la cartella dei referti."""
    from datetime import datetime

    from django.core.files.base import ContentFile

    from ..storage import PrivateAnagraficaStorage
    from .archivio_scansioni import _nome_sicuro

    adesso = datetime.now()
    percorso = "sorveglianza/referti/{:%Y/%m}/{:%Y%m%d-%H%M%S}-{}".format(
        adesso, adesso, _nome_sicuro(nome_file)
    )
    try:
        salvato = PrivateAnagraficaStorage().save(percorso, ContentFile(contenuto))
    except Exception:
        logger.exception("Archiviazione referto fallita (%s)", nome_file)
        return "", len(contenuto or b"")
    return salvato, len(contenuto or b"")


def _riga_base(nome_file: str, percorso: str, dimensione: int, sha: str,
               pagina: int, origine: str, utente=None):
    from ..models_sorveglianza import RefertoIntakeRiga

    return RefertoIntakeRiga(
        nome_file=(nome_file or "")[:255],
        percorso=(percorso or "")[:500],
        dimensione=max(0, int(dimensione or 0)),
        sha256=sha,
        pagina=pagina,
        origine=origine,
        creato_da=utente if getattr(utente, "is_authenticated", False) else None,
    )


def _elabora_pagina(contenuto: bytes, nome_file: str, pagina: int, *,
                    config, origine: str, utente=None, percorso: str = "",
                    dimensione: int = 0, sha: str = ""):
    """Una pagina che si suppone essere un certificato. Ritorna la riga salvata."""
    from ..models_sorveglianza import RefertoIntakeRiga
    from .referti_match import cerca_dipendente
    from .referti_ocr import ErroreLettura, testo_pagina
    from .referti_parsing import analizza_testo
    from .referti_registrazione import ErroreRegistrazione, prepara_registrazione, registra

    riga = _riga_base(nome_file, percorso, dimensione, sha, pagina + 1, origine, utente)

    try:
        testo = testo_pagina(contenuto, pagina, config)
    except ErroreLettura as exc:
        riga.esito = RefertoIntakeRiga.ESITO_ERRORE
        riga.messaggio = str(exc)
        riga.save()
        return riga

    campi = analizza_testo(testo)
    # `testo` esce di scena qui: il contenuto grezzo dell'OCR non viene salvato
    # da nessuna parte. Sopravvivono solo i campi riconosciuti.

    if not campi.e_certificato:
        riga.esito = RefertoIntakeRiga.ESITO_RIFIUTATO
        riga.messaggio = (
            "Non sembra un certificato di idoneità: nessuna delle diciture attese "
            "è stata riconosciuta. Il file resta archiviato e consultabile."
        )
        riga.save()
        return riga

    riga.letto_nominativo = (campi.nominativo or "")[:200]
    riga.nominativo_da_ripiego = campi.nominativo_da_ripiego
    riga.letto_data_nascita = campi.data_nascita
    riga.letto_data_giudizio = campi.data_giudizio
    riga.letto_esito_testo = (campi.esito_testo or "")[:200]
    riga.letto_mansione = (campi.mansione or "")[:200]
    riga.letto_protocollo = campi.protocollo
    riga.date_trovate = campi.date_trovate

    if not campi.minimo_utile:
        mancano = []
        if not campi.nominativo:
            mancano.append("il nominativo")
        if campi.data_giudizio is None:
            mancano.append("la data del giudizio")
        riga.esito = RefertoIntakeRiga.ESITO_DA_RIVEDERE
        riga.messaggio = (
            "Non si è riusciti a leggere " + " né ".join(mancano)
            + ". Vanno inseriti a mano guardando la scansione."
        )
        riga.save()
        return riga

    match = cerca_dipendente(
        campi.nominativo, campi.data_nascita,
        da_ripiego=campi.nominativo_da_ripiego, config=config,
    )
    if match.scelto is not None:
        riga.legacy_anagrafica_id_proposto = match.scelto.legacy_id
        riga.punteggio = match.scelto.punteggio
        riga.data_nascita_conferma = match.scelto.conferma_data_nascita
    riga.candidati = [c.come_dizionario() for c in match.candidati]

    piano = prepara_registrazione(campi)
    riga.divergenze = piano.divergenze

    ostacoli = []
    if match.motivo:
        ostacoli.append(match.motivo)
    if piano.esami_ignoti:
        ostacoli.append(
            "Esami non presenti a catalogo: " + ", ".join(piano.esami_ignoti) + "."
        )
    if not piano.esito:
        ostacoli.append(
            f"Giudizio «{campi.esito_testo or '—'}» non riconosciuto."
        )

    if ostacoli or not match.automatico or not config.conferma_automatica:
        riga.esito = RefertoIntakeRiga.ESITO_DA_RIVEDERE
        riga.messaggio = " ".join(ostacoli) or (
            "Riconoscimento riuscito: attende conferma."
            if not config.conferma_automatica else
            "Attende conferma."
        )
        riga.save()
        return riga

    riga.save()
    try:
        registra(riga, utente=utente)
    except ErroreRegistrazione as exc:
        riga.esito = (
            RefertoIntakeRiga.ESITO_DUPLICATO
            if "già registrate" in str(exc) else RefertoIntakeRiga.ESITO_DA_RIVEDERE
        )
        riga.messaggio = str(exc)
        riga.save(update_fields=["esito", "messaggio"])
    except Exception:
        logger.exception("Registrazione automatica del referto fallita (riga %s)", riga.pk)
        riga.esito = RefertoIntakeRiga.ESITO_DA_RIVEDERE
        riga.messaggio = "Registrazione automatica fallita: lasciata alla conferma manuale."
        riga.save(update_fields=["esito", "messaggio"])
    return riga


def elabora_contenuto(contenuto: bytes, nome_file: str, *, config=None,
                      origine: str = "WEB", utente=None) -> list:
    """Un file intero: una riga per ogni certificato che contiene.

    Non solleva: chi chiama vuole sapere com'è andata, non gestire eccezioni.
    """
    from ..models_sorveglianza import RefertoIntakeConfig, RefertoIntakeRiga
    from .referti_ocr import conta_pagine
    from .referti_parsing import pare_certificato

    config = config or RefertoIntakeConfig.load()
    sha = _impronta(contenuto)
    percorso, dimensione = _archivia(contenuto, nome_file)

    pagine = conta_pagine(contenuto)
    if not pagine:
        riga = _riga_base(nome_file, percorso, dimensione, sha, 1, origine, utente)
        riga.esito = RefertoIntakeRiga.ESITO_ERRORE
        riga.messaggio = "Il file non è un PDF leggibile."
        riga.save()
        return [riga]

    righe = []
    for pagina in range(min(pagine, MAX_PAGINE_PER_FILE)):
        if _gia_visto(sha, pagina + 1):
            continue  # stesso file già passato: non si rilegge
        try:
            riga = _elabora_pagina(
                contenuto, nome_file, pagina, config=config, origine=origine,
                utente=utente, percorso=percorso, dimensione=dimensione, sha=sha,
            )
        except Exception:
            logger.exception("Referto: elaborazione pagina %s fallita (%s)", pagina + 1, nome_file)
            riga = _riga_base(nome_file, percorso, dimensione, sha, pagina + 1, origine, utente)
            riga.esito = RefertoIntakeRiga.ESITO_ERRORE
            riga.messaggio = "Errore imprevisto nella lettura di questa pagina."
            riga.save()
        righe.append(riga)

        # Una pagina che non è un certificato, dopo che almeno uno se n'è trovato,
        # è la continuazione del precedente: non vale la pena leggere il resto.
        if riga.esito == RefertoIntakeRiga.ESITO_RIFIUTATO and pagina == 0 and pagine == 1:
            break

    return righe


def _annota(config, quando, riepilogo: str) -> None:
    """Scrive in configurazione com'è andato l'ultimo passaggio."""
    try:
        config.ultima_esecuzione = quando
        config.ultimo_esito = riepilogo
        config.save(update_fields=["ultima_esecuzione", "ultimo_esito"])
    except Exception:
        logger.exception("Annotazione dell'ultimo passaggio fallita")


def elabora_cartella(config=None, *, limite: int | None = None) -> dict:
    """Passa in rassegna la cartella dei referti. Ritorna il riepilogo.

    Non solleva mai: è pensata per girare da un lavoro periodico, dove
    un'eccezione si tradurrebbe in un meccanismo fermo che nessuno nota.
    """
    from django.utils import timezone

    from ..models_sorveglianza import RefertoIntakeConfig, RefertoIntakeRiga

    config = config or RefertoIntakeConfig.load()
    esito = _Esito()

    if not config.attiva:
        return {**esito.come_dizionario(), "riepilogo": "Acquisizione referti spenta."}

    cartella = (config.cartella or "").strip()
    if not cartella:
        return {**esito.come_dizionario(), "riepilogo": "Nessuna cartella configurata."}

    radice = Path(cartella)
    try:
        esiste = radice.is_dir()
    except OSError:
        esiste = False
    if not esiste:
        messaggio = f"Cartella non raggiungibile: {cartella}"
        logger.warning("Acquisizione referti: %s", messaggio)
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
        logger.exception("Acquisizione referti: %s", messaggio)
        _annota(config, timezone.now(), messaggio)
        return {**esito.come_dizionario(), "riepilogo": messaggio}

    massimo = limite if limite is not None else (config.max_file_per_giro or 25)
    for percorso in candidati[:massimo]:
        if not _file_stabile(percorso):
            continue  # sta ancora arrivando: al prossimo giro
        esito.esaminati += 1
        try:
            contenuto = percorso.read_bytes()
        except OSError:
            logger.exception("Referto non leggibile dalla cartella (%s)", percorso)
            esito.errori += 1
            esito.dettagli.append(f"{percorso.name}: file non leggibile dalla cartella")
            continue

        try:
            righe = elabora_contenuto(
                contenuto, percorso.name, config=config, origine="CARTELLA"
            )
        except Exception:
            logger.exception("Elaborazione del referto fallita (%s)", percorso)
            esito.errori += 1
            esito.dettagli.append(f"{percorso.name}: errore imprevisto")
            if config.sposta_elaborati:
                _sposta(percorso, radice, "errori")
            continue

        andata_bene = False
        for riga in righe:
            if riga.esito == RefertoIntakeRiga.ESITO_OK:
                esito.registrati += 1
                andata_bene = True
            elif riga.esito == RefertoIntakeRiga.ESITO_DA_RIVEDERE:
                esito.in_coda += 1
                andata_bene = True
            elif riga.esito == RefertoIntakeRiga.ESITO_DUPLICATO:
                esito.duplicati += 1
                andata_bene = True
            elif riga.esito == RefertoIntakeRiga.ESITO_RIFIUTATO:
                esito.rifiutati += 1
            else:
                esito.errori += 1

        if righe:
            esito.letti += 1
            esito.dettagli.append(f"{percorso.name}: {len(righe)} certificati")
        else:
            esito.dettagli.append(f"{percorso.name}: già acquisito in precedenza")
            andata_bene = True

        if config.sposta_elaborati:
            _sposta(percorso, radice, "elaborati" if andata_bene else "errori")

    _annota(config, timezone.now(), esito.riepilogo())
    return {**esito.come_dizionario(), "riepilogo": esito.riepilogo()}
