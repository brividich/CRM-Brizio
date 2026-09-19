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
anagrafico diverso apre un certificato nuovo; le pagine senza un nuovo blocco
sono continuazioni e vengono lette insieme alla prima. Il PDF originale resta
intero e viene allegato una sola volta. Se lo scanner salva ``pagina 1`` e
``pagina 2`` come file separati, il lotto li ricompone prima dell'OCR.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import time
from pathlib import Path

logger = logging.getLogger(__name__)

__all__ = [
    "combina_pdf_pagine",
    "elabora_contenuto",
    "elabora_documenti",
    "elabora_cartella",
    "ESTENSIONI_ACCETTATE",
]

ESTENSIONI_ACCETTATE = {".pdf"}

# Un file appena depositato può essere ancora in scrittura: la fotocopiatrice
# scrive a pezzi e leggerlo a metà darebbe un errore inventato.
ATTESA_STABILITA_SECONDI = 2.0

# Oltre questo numero di pagine si smette di cercare altri certificati: una
# scansione con centinaia di pagine è un errore di chi l'ha prodotta, e leggerle
# tutte bloccherebbe il giro per tutti gli altri.
MAX_PAGINE_PER_FILE = 40

# Alcuni scanner producono un PDF per pagina invece di un PDF multipagina. Si
# uniscono solo nomi espliciti ("... pagina 1.pdf", "... pag-2.pdf",
# "... page_3.pdf"): numeri generici, date e progressivi restano file distinti.
_PAGINA_NEL_NOME = re.compile(
    r"^(?P<base>.+?)[\s._-]+(?:pagina|pag|page)[\s._-]*0*(?P<numero>[1-9]\d*)$",
    re.IGNORECASE,
)


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


def _pagina_da_nome(nome_file: str) -> tuple[str, int] | None:
    """Base e numero per file dichiaratamente nominati come pagine."""
    stem = Path(nome_file or "").stem
    match = _PAGINA_NEL_NOME.match(stem)
    if not match:
        return None
    base = match.group("base").rstrip(" ._-")
    return (base, int(match.group("numero"))) if base else None


def _unisci_pdf(parti: list[tuple[int, str, bytes]]) -> bytes:
    """Crea un PDF unico, mantenendo l'ordine dichiarato nel nome dei file."""
    import fitz

    unito = fitz.open()
    try:
        for _numero, _nome, contenuto in sorted(parti):
            sorgente = fitz.open(stream=contenuto, filetype="pdf")
            try:
                unito.insert_pdf(sorgente)
            finally:
                sorgente.close()
        return unito.tobytes(garbage=3, deflate=True)
    finally:
        unito.close()


def combina_pdf_pagine(documenti: list[tuple[str, bytes]]) -> list[tuple[str, bytes, list[str]]]:
    """Riunisce i file ``pagina N`` dello stesso referto prima dell'OCR.

    Ritorna ``(nome finale, contenuto, nomi sorgente)``. Un gruppo viene unito
    soltanto se parte da pagina 1, non ha doppioni ed e' consecutivo: davanti a
    una nomenclatura ambigua la scelta prudente e' lasciare i file separati.
    """
    gruppi: dict[str, list[tuple[int, int, str, str, bytes]]] = {}
    singoli: list[tuple[int, str, bytes, list[str]]] = []
    for posizione, (nome, contenuto) in enumerate(documenti):
        pagina = _pagina_da_nome(nome)
        if pagina is None:
            singoli.append((posizione, nome, contenuto, [nome]))
            continue
        base, numero = pagina
        gruppi.setdefault(base.casefold(), []).append(
            (posizione, numero, base, nome, contenuto)
        )

    risultati = list(singoli)
    for elementi in gruppi.values():
        ordinati = sorted(elementi, key=lambda e: e[1])
        numeri = [e[1] for e in ordinati]
        consecutivi = len(elementi) > 1 and numeri == list(range(1, len(numeri) + 1))
        if not consecutivi:
            risultati.extend((p, n, c, [n]) for p, _num, _base, n, c in elementi)
            continue
        try:
            contenuto_unito = _unisci_pdf([
                (num, nome, contenuto) for _, num, _, nome, contenuto in ordinati
            ])
        except Exception:
            logger.exception(
                "Referti: impossibile unire le pagine nominate %s",
                ", ".join(e[3] for e in ordinati),
            )
            risultati.extend((p, n, c, [n]) for p, _num, _base, n, c in elementi)
            continue
        risultati.append((
            min(e[0] for e in ordinati),
            f"{ordinati[0][2]}.pdf",
            contenuto_unito,
            [e[3] for e in ordinati],
        ))

    return [(nome, contenuto, sorgenti) for _, nome, contenuto, sorgenti in sorted(risultati)]


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


def _elabora_testo(testo: str, nome_file: str, pagina: int, *,
                   config, origine: str, utente=None, percorso: str = "",
                   dimensione: int = 0, sha: str = ""):
    """Un certificato, eventualmente composto da piu' pagine, in una riga."""
    from ..models_sorveglianza import RefertoIntakeRiga
    from .referti_match import cerca_dipendente
    from .referti_parsing import analizza_testo
    from .referti_registrazione import ErroreRegistrazione, prepara_registrazione, registra

    riga = _riga_base(nome_file, percorso, dimensione, sha, pagina + 1, origine, utente)

    campi = analizza_testo(testo)
    # `testo` esce di scena qui: il contenuto grezzo dell'OCR non viene salvato
    # da nessuna parte. Sopravvivono solo i campi riconosciuti.

    if campi.tipo_referto == RefertoIntakeRiga.TIPO_OCULISTICA:
        # Data, nome ed esito sono scritti a mano: si completano in coda guardando
        # la scansione. Nessun riconoscimento automatico da tentare.
        riga.tipo_referto = RefertoIntakeRiga.TIPO_OCULISTICA
        riga.esito = RefertoIntakeRiga.ESITO_DA_RIVEDERE
        riga.messaggio = (
            "Certificato oculistico: data, dipendente ed esito sono scritti a mano. "
            "Inserirli guardando la scansione."
        )
        riga.save()
        return riga

    if not campi.e_certificato:
        riga.esito = RefertoIntakeRiga.ESITO_RIFIUTATO
        riga.messaggio = (
            "Non sembra un certificato di idoneità né un certificato oculistico: nessuna "
            "delle diciture attese è stata riconosciuta. Il file resta archiviato e consultabile."
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
    # Bloccano solo visita non riconosciuta e giudizio: i requisiti non a catalogo
    # si registrano comunque (senza tipo) e vengono segnalati.
    ostacoli.extend(piano.ostacoli)

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


def _identita_pagina(campi) -> tuple[str, object, object] | None:
    """Identita' forte che distingue l'inizio di un certificato dal suo seguito."""
    from .referti_parsing import normalizza

    if not campi.e_certificato or campi.nominativo_da_ripiego:
        return None
    nome = normalizza(campi.nominativo)
    if not nome or campi.data_nascita is None:
        return None
    return nome, campi.data_nascita, campi.data_giudizio


def _stessa_identita(prima, dopo) -> bool:
    if prima[:2] != dopo[:2]:
        return False
    # Se entrambe le pagine dichiarano il giorno del giudizio, una data diversa
    # segnala un altro certificato della stessa persona.
    return prima[2] is None or dopo[2] is None or prima[2] == dopo[2]


def _raggruppa_pagine(testi: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Accorpa le continuazioni e separa solo veri nuovi blocchi anagrafici."""
    from .referti_parsing import analizza_testo

    gruppi: list[tuple[int, str]] = []
    correnti: list[str] = []
    pagina_iniziale = 0
    identita_corrente = None
    corrente_e_referto = False

    def chiudi() -> None:
        nonlocal correnti
        if correnti:
            gruppi.append((pagina_iniziale, "\n\n".join(correnti)))
            correnti = []

    for pagina, testo in testi:
        campi = analizza_testo(testo)
        identita = _identita_pagina(campi)
        nuovo_certificato = False
        if correnti and identita is not None:
            nuovo_certificato = (
                identita_corrente is None
                or not _stessa_identita(identita_corrente, identita)
            )
        elif correnti and not corrente_e_referto and campi.e_referto:
            nuovo_certificato = True

        if nuovo_certificato:
            chiudi()
            pagina_iniziale = pagina
            identita_corrente = None
            corrente_e_referto = False
        elif not correnti:
            pagina_iniziale = pagina

        correnti.append(testo)
        corrente_e_referto = corrente_e_referto or campi.e_referto
        if identita_corrente is None and identita is not None:
            identita_corrente = identita

    chiudi()
    return gruppi


def elabora_contenuto(contenuto: bytes, nome_file: str, *, config=None,
                      origine: str = "WEB", utente=None) -> list:
    """Un file intero: una riga per ogni certificato che contiene.

    Non solleva: chi chiama vuole sapere com'è andata, non gestire eccezioni.
    """
    from ..models_sorveglianza import RefertoIntakeConfig, RefertoIntakeRiga
    from .referti_ocr import ErroreLettura, conta_pagine, testo_pagina

    config = config or RefertoIntakeConfig.load()
    sha = _impronta(contenuto)
    if sha and RefertoIntakeRiga.objects.filter(sha256=sha).exists():
        return []
    percorso, dimensione = _archivia(contenuto, nome_file)

    pagine = conta_pagine(contenuto)
    if not pagine:
        riga = _riga_base(nome_file, percorso, dimensione, sha, 1, origine, utente)
        riga.esito = RefertoIntakeRiga.ESITO_ERRORE
        riga.messaggio = "Il file non è un PDF leggibile."
        riga.save()
        return [riga]

    testi = []
    errori = []
    for pagina in range(min(pagine, MAX_PAGINE_PER_FILE)):
        try:
            testi.append((pagina, testo_pagina(contenuto, pagina, config)))
        except ErroreLettura as exc:
            errori.append((pagina, str(exc)))
        except Exception:
            logger.exception("Referto: OCR pagina %s fallito (%s)", pagina + 1, nome_file)
            errori.append((pagina, "Errore imprevisto nella lettura di questa pagina."))

    righe_raggruppate = []
    for pagina, testo in _raggruppa_pagine(testi):
        try:
            riga = _elabora_testo(
                testo, nome_file, pagina, config=config, origine=origine,
                utente=utente, percorso=percorso, dimensione=dimensione, sha=sha,
            )
        except Exception:
            logger.exception(
                "Referto: elaborazione certificato da pagina %s fallita (%s)",
                pagina + 1, nome_file,
            )
            riga = _riga_base(nome_file, percorso, dimensione, sha, pagina + 1, origine, utente)
            riga.esito = RefertoIntakeRiga.ESITO_ERRORE
            riga.messaggio = "Errore imprevisto nella lettura di questo certificato."
            riga.save()
        righe_raggruppate.append(riga)

    for pagina, messaggio in errori:
        riga = _riga_base(nome_file, percorso, dimensione, sha, pagina + 1, origine, utente)
        riga.esito = RefertoIntakeRiga.ESITO_ERRORE
        riga.messaggio = messaggio
        riga.save()
        righe_raggruppate.append(riga)

    return sorted(righe_raggruppate, key=lambda r: r.pagina)


def elabora_documenti(documenti: list[tuple[str, bytes]], *, config=None,
                       origine: str = "WEB", utente=None) -> list[tuple[list[str], list]]:
    """Elabora un lotto, ricomponendo prima gli eventuali file ``pagina N``."""
    risultati = []
    for nome, contenuto, sorgenti in combina_pdf_pagine(documenti):
        risultati.append((
            sorgenti,
            elabora_contenuto(
                contenuto, nome, config=config, origine=origine, utente=utente,
            ),
        ))
    return risultati


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
    contenuti = []
    percorsi_per_nome = {}
    for percorso in candidati[:massimo]:
        if not _file_stabile(percorso):
            continue  # sta ancora arrivando: al prossimo giro
        esito.esaminati += 1
        try:
            contenuti.append((percorso.name, percorso.read_bytes()))
            percorsi_per_nome[percorso.name] = percorso
        except OSError:
            logger.exception("Referto non leggibile dalla cartella (%s)", percorso)
            esito.errori += 1
            esito.dettagli.append(f"{percorso.name}: file non leggibile dalla cartella")

    for nomi_sorgente, righe in elabora_documenti(
        contenuti, config=config, origine="CARTELLA"
    ):
        etichetta = " + ".join(nomi_sorgente)
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
            esito.dettagli.append(f"{etichetta}: {len(righe)} certificati")
        else:
            esito.dettagli.append(f"{etichetta}: già acquisito in precedenza")
            andata_bene = True

        if config.sposta_elaborati:
            for nome_sorgente in nomi_sorgente:
                percorso = percorsi_per_nome.get(nome_sorgente)
                if percorso is not None:
                    _sposta(percorso, radice, "elaborati" if andata_bene else "errori")

    _annota(config, timezone.now(), esito.riepilogo())
    return {**esito.come_dizionario(), "riepilogo": esito.riepilogo()}
