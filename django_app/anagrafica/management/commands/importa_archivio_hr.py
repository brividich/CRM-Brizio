"""Importa nel fascicolo documentale l'archivio esportato dal vecchio gestionale (HR TOOLS).

Struttura attesa della cartella sorgente::

    <radice>/<Categoria>/<COGNOME_NOME>/<file>

La categoria (Contratti, DPI, VISITE MEDICHE, ...) diventa una cartella **di primo
livello** dello scheletro documentale, come se i documenti fossero stati caricati a
mano: se una cartella con quel nome esiste già si usa quella, senza toccarne le
impostazioni. Le categorie riservate (Richiami, Infortuni) nascono riservate; se
esiste già una cartella omonima **non** riservata, quei file non si importano
finché non la si rende riservata. La cartella persona si abbina al dipendente per
nominativo. L'abbinamento è **esatto** (stesse parole, in qualunque ordine, senza
accenti né punteggiatura): niente somiglianze di stringhe. Un nome che non trova
esattamente una persona non si importa e finisce nel report, dove si risolve con
``--mappa``.

Dry-run di default: senza ``--apply`` non scrive nulla. Rieseguibile: un file già
importato (stesso dipendente, nome e dimensione) viene saltato; se si trova in
un'altra cartella (per esempio sotto la vecchia «Archivio HR TOOLS») viene spostato.

Esempi:
    python manage.py importa_archivio_hr "C:\\...\\Estrazione HR TOOLS"
    python manage.py importa_archivio_hr "C:\\...\\Estrazione HR TOOLS" --report report.csv
    python manage.py importa_archivio_hr "C:\\...\\Estrazione HR TOOLS" --mappa mappa.csv --apply
"""
from __future__ import annotations

import csv
import mimetypes
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from anagrafica.models import CartellaDocumentoDipendente, DocumentoDipendente

RIFERIMENTO_TIPO = "archivio.hrtools"
AUTORE = "Importazione archivio storico"
MAX_BYTES = 50 * 1024 * 1024  # stesso limite dell'upload manuale

ESTENSIONI_AMMESSE = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".jpg", ".jpeg", ".png", ".webp", ".msg", ".html",
}
MIME_EXTRA = {".msg": "application/vnd.ms-outlook"}
FILE_DI_SISTEMA = {"thumbs.db", "desktop.ini", ".ds_store"}


@dataclass(frozen=True)
class Categoria:
    cartella: str
    tipo: str
    solo_admin: bool = False


# Chiave = nome della cartella sorgente normalizzato (vedi ``_norm``).
CATEGORIE: dict[str, Categoria] = {
    "CONTRATTI": Categoria("Contratti", DocumentoDipendente.Tipo.MANUALE),
    "DOCUMENTI PERSONALI": Categoria("Documenti personali", DocumentoDipendente.Tipo.MANUALE),
    "COMUNICAZIONI VARIE SICUREZZA": Categoria("Comunicazioni sicurezza", DocumentoDipendente.Tipo.MANUALE),
    # Provvedimenti disciplinari e infortuni: cartelle riservate.
    "RICHIAMI": Categoria("Richiami", DocumentoDipendente.Tipo.MANUALE, solo_admin=True),
    "DOCUMENTI PERSONALI RICHIAMI": Categoria("Richiami", DocumentoDipendente.Tipo.MANUALE, solo_admin=True),
    "INFORTUNI": Categoria("Infortuni", DocumentoDipendente.Tipo.MANUALE, solo_admin=True),
    "DPI": Categoria("DPI", DocumentoDipendente.Tipo.DPI_CONSEGNA),
    # Tipo referto: la scheda li nasconde a chi non ha il permesso visite mediche.
    "VISITE MEDICHE": Categoria("Visite mediche", DocumentoDipendente.Tipo.VISITA_MEDICA_REFERTO),
}


def _norm(value) -> str:
    """Maiuscolo, senza accenti, solo lettere separate da uno spazio."""
    testo = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^A-Za-z]+", " ", testo).upper().split())


def _chiave(value) -> tuple[str, ...]:
    """Chiave d'abbinamento indipendente dall'ordine delle parole."""
    return tuple(sorted(_norm(value).split()))


def _firma_valida(percorso: Path) -> bool:
    from core.upload_mime import check_magic_signature

    with percorso.open("rb") as handle:
        return check_magic_signature(handle, percorso.suffix)


def _mime(percorso: Path) -> str:
    ext = percorso.suffix.lower()
    return MIME_EXTRA.get(ext) or mimetypes.guess_type(percorso.name)[0] or "application/octet-stream"


# Nomi delle cartelle di destinazione: un documento che sta già in una di queste è
# stato messo lì da una categoria dell'archivio, e non va spostato da un'altra.
NOMI_CARTELLE_CATEGORIE = {c.cartella.lower() for c in CATEGORIE.values()}


def _nome_su_disco(nome: str) -> str:
    """Nome breve con cui il file viene salvato nello storage.

    ``DocumentoDipendente.file`` è un FileField senza ``max_length`` (100 caratteri)
    e il percorso generato ne consuma già ~61 prima del nome: con i nomi lunghi
    dell'archivio l'INSERT falliva. Il nome originale resta in ``nome_originale``,
    che è quello mostrato in scheda e usato al download. 24 caratteri di radice +
    estensione + l'eventuale suffisso anti-collisione dello storage stanno nei 100.
    """
    percorso = Path(nome)
    radice = unicodedata.normalize("NFKD", percorso.stem).encode("ascii", "ignore").decode()
    radice = re.sub(r"[^A-Za-z0-9]+", "_", radice).strip("_")[:24]
    return f"{radice or 'documento'}{percorso.suffix.lower()[:5]}"


class Command(BaseCommand):
    help = "Importa nel fascicolo documentale l'archivio HR TOOLS (<Categoria>/<COGNOME_NOME>/file)."

    def add_arguments(self, parser):
        parser.add_argument("radice", help="Cartella dell'estrazione (contiene le categorie).")
        parser.add_argument("--apply", action="store_true", help="Scrive davvero. Default: dry-run.")
        parser.add_argument(
            "--mappa",
            help="CSV 'cartella;legacy_id' per abbinare a mano i nomi non riconosciuti "
                 "(legacy_id vuoto o 0 = ignora la cartella).",
        )
        parser.add_argument("--categoria", action="append", default=[],
                            help="Limita a una categoria (ripetibile), es. --categoria DPI.")
        parser.add_argument("--report", help="Scrive il dettaglio file per file in un CSV.")

    # ------------------------------------------------------------------

    def handle(self, *args, **opts):
        radice = Path(opts["radice"])
        if not radice.is_dir():
            raise CommandError(f"Cartella non trovata: {radice}")
        apply = bool(opts["apply"])
        solo = {_norm(c) for c in opts["categoria"]}
        mappa = self._leggi_mappa(opts.get("mappa"))

        indice, nominativi, cessati = self._indice_dipendenti()
        self.stdout.write(f"Dipendenti in anagrafica: {len(nominativi)}")

        categorie_sconosciute: list[str] = []
        persone: dict[str, dict] = {}  # nome cartella persona -> esito abbinamento
        righe: list[dict] = []
        cartelle_cache: dict[str, CartellaDocumentoDipendente] = {}
        importati_per_dipendente: dict[int, dict[str, int]] = {}

        for dir_cat in sorted(p for p in radice.iterdir() if p.is_dir()):
            chiave_cat = _norm(dir_cat.name)
            if solo and chiave_cat not in solo:
                continue
            categoria = CATEGORIE.get(chiave_cat)
            if categoria is None:
                categorie_sconosciute.append(dir_cat.name)
                continue

            for dir_persona in sorted(p for p in dir_cat.iterdir() if p.is_dir()):
                esito = persone.get(dir_persona.name)
                if esito is None:
                    esito = self._abbina(dir_persona.name, indice, mappa, cessati)
                    persone[dir_persona.name] = esito
                esito["categorie"].add(categoria.cartella)

                for file in sorted(p for p in dir_persona.rglob("*") if p.is_file()):
                    riga = {
                        "categoria": dir_cat.name,
                        "cartella_persona": dir_persona.name,
                        "legacy_id": esito["legacy_id"] or "",
                        "file": str(file.relative_to(dir_persona)),
                        "byte": file.stat().st_size,
                        "esito": "",
                    }
                    righe.append(riga)
                    if not esito["legacy_id"]:
                        riga["esito"] = "persona non abbinata"
                        continue
                    riga["esito"] = self._importa_file(
                        file, esito["legacy_id"], categoria, cartelle_cache, apply,
                    )
                    if riga["esito"] in ("importato", "da importare", "spostato", "da spostare"):
                        conteggio = importati_per_dipendente.setdefault(esito["legacy_id"], {})
                        conteggio[categoria.cartella] = conteggio.get(categoria.cartella, 0) + 1

        if apply:
            self._audit(importati_per_dipendente, str(radice))
        if opts.get("report"):
            self._scrivi_report(Path(opts["report"]), righe)
        self._stampa_riepilogo(persone, righe, categorie_sconosciute, nominativi, apply)

    # ------------------------------------------------------------------

    def _indice_dipendenti(self):
        from core.legacy_anagrafica import fetch_anagrafica_rows

        from anagrafica.models import DipendenteAnagraficaAziendale

        indice: dict[tuple[str, ...], list[int]] = {}
        nominativi: dict[int, str] = {}
        for row in fetch_anagrafica_rows(deduplicate=True):
            legacy_id = int(row.get("id") or 0)
            nominativo = f"{row.get('cognome') or ''} {row.get('nome') or ''}".strip()
            chiave = _chiave(nominativo)
            if not legacy_id or not chiave:
                continue
            nominativi[legacy_id] = nominativo
            indice.setdefault(chiave, []).append(legacy_id)
        cessati = set(
            DipendenteAnagraficaAziendale.objects
            .filter(data_cessazione__isnull=False)
            .values_list("legacy_anagrafica_id", flat=True)
        )
        return indice, nominativi, cessati

    def _leggi_mappa(self, percorso) -> dict[str, int]:
        if not percorso:
            return {}
        path = Path(percorso)
        if not path.is_file():
            raise CommandError(f"Mappa non trovata: {path}")
        mappa: dict[str, int] = {}
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for n, row in enumerate(csv.reader(handle, delimiter=";"), start=1):
                if not row or not row[0].strip() or row[0].strip().startswith("#"):
                    continue
                valore = (row[1].strip() if len(row) > 1 else "") or "0"
                if not valore.isdigit():
                    if n == 1:
                        continue  # intestazione
                    raise CommandError(f"Mappa riga {n}: legacy_id non numerico ({valore!r}).")
                mappa[_norm(row[0])] = int(valore)
        return mappa

    def _abbina(self, nome_cartella: str, indice, mappa, cessati) -> dict:
        esito = {"legacy_id": None, "motivo": "", "cessato": False, "categorie": set()}
        manuale = mappa.get(_norm(nome_cartella))
        if manuale is not None:
            if manuale:
                esito.update(legacy_id=manuale, motivo="mappa", cessato=manuale in cessati)
            else:
                esito["motivo"] = "ignorata da mappa"
            return esito
        candidati = indice.get(_chiave(nome_cartella), [])
        if len(candidati) == 1:
            esito.update(legacy_id=candidati[0], motivo="esatto", cessato=candidati[0] in cessati)
        elif candidati:
            esito["motivo"] = f"ambiguo ({len(candidati)} dipendenti: {sorted(candidati)})"
        else:
            esito["motivo"] = "nessun dipendente con questo nominativo"
        return esito

    def _cartella(self, categoria: Categoria, cache, apply):
        """Cartella di primo livello della categoria: quella esistente o una nuova.

        Una cartella esistente si usa così com'è (nome, riservatezza, retention li
        governa Impostazioni → Documenti). Unica eccezione: una categoria riservata
        non finisce mai in una cartella omonima NON riservata — ritorna la stringa
        col motivo e i file vengono saltati.
        """
        if categoria.cartella in cache:
            return cache[categoria.cartella]
        cartella = (
            CartellaDocumentoDipendente.objects
            .filter(parent=None, nome__iexact=categoria.cartella)
            .order_by("id").first()
        )
        if cartella is not None and categoria.solo_admin and not cartella.solo_admin:
            cartella = (
                f"saltato: la cartella «{cartella.nome}» esiste ma non è riservata "
                "(renderla riservata in Impostazioni e rilanciare)"
            )
        elif cartella is None and apply:
            cartella = CartellaDocumentoDipendente.objects.create(
                nome=categoria.cartella, solo_admin=categoria.solo_admin,
            )
        cache[categoria.cartella] = cartella
        return cartella

    def _importa_file(self, file: Path, legacy_id: int, categoria: Categoria, cache, apply) -> str:
        if file.name.lower() in FILE_DI_SISTEMA or file.name.startswith("~$"):
            return "saltato: file di sistema"
        ext = file.suffix.lower()
        if ext not in ESTENSIONI_AMMESSE:
            return f"saltato: formato non ammesso ({ext or 'senza estensione'})"
        size = file.stat().st_size
        if size <= 0:
            return "saltato: file vuoto"
        if size > MAX_BYTES:
            return "saltato: oltre 50 MB"
        if not _firma_valida(file):
            return "saltato: contenuto non corrisponde all'estensione"

        cartella = self._cartella(categoria, cache, apply)
        if isinstance(cartella, str):
            return cartella
        nome = file.name[:255]

        # Già importato: non si ricarica. Si sposta SOLO se sta nella vecchia
        # struttura (sottocartella di «Archivio HR TOOLS», o cartella eliminata) o
        # se questa categoria è riservata e quella attuale no. Lo stesso file in due
        # categorie non rimbalza più fra le due a seconda dell'ordine: resta dove è,
        # e la cartella riservata vince sempre.
        importato = (
            DocumentoDipendente.objects
            .select_related("cartella")
            .filter(legacy_anagrafica_id=legacy_id, oggetto_riferimento_tipo=RIFERIMENTO_TIPO,
                    nome_originale=nome, dimensione_bytes=size)
            .order_by("id").first()
        )
        if importato is not None:
            if cartella is not None and importato.cartella_id == cartella.pk:
                return "già presente"
            attuale = importato.cartella
            vecchia_struttura = (
                attuale is None or attuale.parent_id is not None
                or attuale.nome.lower() not in NOMI_CARTELLE_CATEGORIE
            )
            verso_riservata = categoria.solo_admin and not (attuale is not None and attuale.solo_admin)
            if not (vecchia_struttura or verso_riservata):
                return "già presente in altra cartella"
            if not apply or cartella is None:
                return "da spostare"
            importato.cartella = cartella
            importato.descrizione = ""
            importato.save(update_fields=["cartella", "descrizione"])
            return "spostato"
        if cartella is not None and DocumentoDipendente.objects.filter(
            legacy_anagrafica_id=legacy_id, cartella=cartella,
            nome_originale=nome, dimensione_bytes=size,
        ).exists():
            return "già presente"
        if not apply:
            return "da importare"

        doc = DocumentoDipendente(
            legacy_anagrafica_id=legacy_id,
            tipo=categoria.tipo,
            cartella=cartella,
            nome_originale=nome,
            tipo_mime=_mime(file),
            dimensione_bytes=size,
            oggetto_riferimento_tipo=RIFERIMENTO_TIPO,
            created_by_display=AUTORE,
        )
        try:
            with file.open("rb") as handle:
                doc.file.save(_nome_su_disco(file.name), File(handle), save=True)
        except Exception as exc:
            if doc.file and doc.file.name and not doc.pk:
                try:
                    doc.file.storage.delete(doc.file.name)
                except Exception:
                    pass
            return f"errore: {exc.__class__.__name__}: {exc}"[:200]
        return "importato"

    def _audit(self, importati: dict[int, dict[str, int]], radice: str):
        from core.audit import log_action

        richiesta = SimpleNamespace(META={}, user=None)
        for legacy_id, per_cartella in importati.items():
            log_action(
                richiesta, "DOCUMENTO_DIPENDENTE_IMPORT_ARCHIVIO", "anagrafica",
                {
                    "legacy_anagrafica_id": legacy_id,
                    "documenti": sum(per_cartella.values()),
                    "per_cartella": per_cartella,
                    "origine": radice,
                },
                oggetto_tipo="anagrafica.dipendente", oggetto_id=str(legacy_id),
            )

    def _scrivi_report(self, path: Path, righe: list[dict]):
        campi = ["categoria", "cartella_persona", "legacy_id", "file", "byte", "esito"]
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=campi, delimiter=";")
            writer.writeheader()
            writer.writerows(righe)
        self.stdout.write(f"Report scritto in {path}")

    def _stampa_riepilogo(self, persone, righe, categorie_sconosciute, nominativi, apply):
        w = self.stdout.write
        w("")
        w(self.style.SUCCESS(f"=== Archivio HR TOOLS ({'APPLY' if apply else 'DRY-RUN'}) ==="))
        abbinate = [n for n, e in persone.items() if e["legacy_id"]]
        w(f"  Cartelle persona: {len(persone)}  abbinate: {len(abbinate)}  "
          f"non abbinate: {len(persone) - len(abbinate)}")

        esiti: dict[str, int] = {}
        for r in righe:
            chiave = r["esito"] if not r["esito"].startswith("errore") else "errore"
            esiti[chiave] = esiti.get(chiave, 0) + 1
        w("  File per esito:")
        for chiave, n in sorted(esiti.items(), key=lambda kv: -kv[1]):
            w(f"    {chiave:55s} {n}")
        errori: dict[str, int] = {}
        for r in righe:
            if r["esito"].startswith("errore"):
                errori[r["esito"][:160]] = errori.get(r["esito"][:160], 0) + 1
        if errori:
            w(self.style.WARNING("  Motivi degli errori (i file in errore si reimportano al rilancio):"))
            for motivo, n in sorted(errori.items(), key=lambda kv: -kv[1])[:5]:
                w(f"    {n:5d}  {motivo}")

        per_cat: dict[str, list[int]] = {}
        for r in righe:
            tot = per_cat.setdefault(r["categoria"], [0, 0])
            tot[0] += 1
            tot[1] += r["esito"] in ("importato", "da importare", "spostato", "da spostare")
        w("  Per categoria (file / importabili):")
        for cat, (tot, ok) in sorted(per_cat.items()):
            w(f"    {cat:40s} {tot:5d} / {ok}")

        if categorie_sconosciute:
            w(self.style.WARNING(
                "  Categorie non previste (saltate, da aggiungere a CATEGORIE): "
                + ", ".join(categorie_sconosciute)
            ))

        non_abbinate = sorted((n, e) for n, e in persone.items() if not e["legacy_id"])
        if non_abbinate:
            w(self.style.WARNING("  Cartelle persona NON abbinate (risolvere con --mappa):"))
            for nome, esito in non_abbinate:
                w(f"    {nome:40s} {esito['motivo']}  [{', '.join(sorted(esito['categorie']))}]")

        cessati = sorted(n for n, e in persone.items() if e["legacy_id"] and e["cessato"])
        if cessati:
            w(f"  Abbinate a dipendenti cessati: {len(cessati)} (importate comunque nel fascicolo)")

        da_mappa = sorted((n, e["legacy_id"]) for n, e in persone.items() if e["motivo"] == "mappa")
        if da_mappa:
            w("  Abbinate da mappa:")
            for nome, lid in da_mappa:
                w(f"    {nome:40s} -> {lid} {nominativi.get(lid, '(id non in anagrafica!)')}")

        w("")
        if not apply:
            w(self.style.NOTICE("DRY-RUN: nessuna scrittura. Rilancia con --apply per importare."))
