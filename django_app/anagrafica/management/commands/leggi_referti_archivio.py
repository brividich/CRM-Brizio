"""Legge i referti dell'archivio HR TOOLS: visite svolte, requisiti, certificati oculistici.

Usa la stessa lettura dell'acquisizione referti (OCR, estrazione campi, alias,
registrazione) con una differenza sostanziale: **di chi è il referto lo si sa
già**, perché lo dice la cartella da cui è stato importato. Il nominativo e la
data di nascita letti sul certificato non servono a cercare la persona ma a
**confermarla**: se smentiscono l'anagrafica, il referto va in revisione.

Per ogni certificato di idoneità (vedi ``services.referti_registrazione``):
  - **una sola visita**, la riga «Visita Medica» del protocollo, con data ed esito
    del giudizio;
  - **tutte le righe del protocollo come requisiti** del dipendente (l'ultimo
    certificato è quello in vigore);
Si registra da solo solo ciò che è certo: identità confermata, «Visita Medica» e
giudizio riconosciuti. Un requisito non a catalogo non blocca: viene segnalato.

I **certificati oculistici** hanno data, nome ed esito scritti a mano: vanno tutti
nella coda di revisione, dove si inseriscono guardando la scansione.

Due sorgenti:
  - default: i referti importati nel fascicolo (``importa_archivio_hr``);
  - ``--cartella``: la cartella «VISITE MEDICHE» dell'estrazione, per una prova
    **prima** dell'import (solo dry-run: non c'è un documento da agganciare).

Esempi:
    python manage.py leggi_referti_archivio --cartella "C:\\...\\VISITE MEDICHE" --report prova.csv
    python manage.py leggi_referti_archivio --report prova.csv
    python manage.py leggi_referti_archivio --apply
"""
from __future__ import annotations

import csv
import hashlib
import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

logger = logging.getLogger(__name__)

MAX_PAGINE = 40

AUTO = "REGISTRA"
REVISIONE = "REVISIONE"
OCULISTICA = "OCULISTICA_CODA"
NON_CERTIFICATO = "NON_CERTIFICATO"
ERRORE = "ERRORE"
GIA_LETTO = "GIA_LETTO"


@dataclass
class Sorgente:
    """Un PDF da leggere, con il dipendente a cui appartiene."""

    etichetta: str
    nome_file: str
    legacy_id: int | None
    leggi: callable
    documento: object = None
    motivo_persona: str = ""


@dataclass
class Lettura:
    sorgente: Sorgente
    pagina: int
    decisione: str
    motivo: str = ""
    campi: object = None
    piano: object = None
    punteggio: int = 0
    conferma_nascita: bool = False
    visita: str = ""                 # tipo della visita che si registrerebbe
    visita_presente: bool = False
    requisiti: list[str] = field(default_factory=list)


class Command(BaseCommand):
    help = "Legge i referti dell'archivio HR TOOLS: visite, requisiti, oculistici in coda (dry-run di default)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Scrive davvero. Default: dry-run.")
        parser.add_argument("--cartella", help="Cartella «VISITE MEDICHE» dell'estrazione (solo dry-run).")
        parser.add_argument("--mappa", help="Con --cartella: CSV 'cartella;legacy_id' come per l'import.")
        parser.add_argument("--limite", type=int, default=0, help="Legge al massimo N file (0 = tutti).")
        parser.add_argument("--report", help="CSV con quanto letto e deciso, pagina per pagina.")

    # ------------------------------------------------------------------

    def handle(self, *args, **opts):
        from anagrafica.models_sorveglianza import RefertoIntakeConfig
        from anagrafica.services.referti_ocr import disponibile

        apply = bool(opts["apply"])
        if apply and opts.get("cartella"):
            raise CommandError("--cartella serve solo per la prova: con --apply si leggono i referti del fascicolo.")
        if not disponibile():
            raise CommandError("Tesseract non disponibile su questo server: impossibile leggere i referti.")

        try:
            config = RefertoIntakeConfig.load()
        except DatabaseError:
            if apply:
                raise
            # Solo per la prova: un DB non ancora migrato non deve impedire di vedere
            # cosa si legge. Valori di fabbrica (OCR 200 dpi, soglie standard).
            self.stdout.write(self.style.WARNING(
                "Configurazione referti non leggibile (migrazioni mancanti?): uso i valori predefiniti."
            ))
            config = RefertoIntakeConfig()
        nominativi, nascite = self._anagrafica()
        sorgenti = (
            self._da_cartella(Path(opts["cartella"]), opts.get("mappa"))
            if opts.get("cartella") else self._da_fascicolo()
        )
        # L'ordine dei file non conta: quale protocollo è in vigore lo decide la
        # data del certificato (``aggiorna_requisiti``), non chi viene letto per ultimo.
        if opts["limite"]:
            sorgenti = sorgenti[: opts["limite"]]
        self.stdout.write(f"File da leggere: {len(sorgenti)} ({'APPLY' if apply else 'DRY-RUN'})")

        letture: list[Lettura] = []
        for n, sorgente in enumerate(sorgenti, start=1):
            letture.extend(self._leggi_file(sorgente, config, nominativi, nascite, apply))
            if n % 25 == 0:
                self.stdout.write(f"  ... {n}/{len(sorgenti)}")
                self.stdout.flush()

        if opts.get("report"):
            self._scrivi_report(Path(opts["report"]), letture, nominativi)
        self._riepilogo(letture, apply)

    # ------------------------------------------------------------------ sorgenti

    def _anagrafica(self):
        from anagrafica.management.commands.importa_archivio_hr import Command as Import
        from anagrafica.models import DipendenteAnagraficaCivile

        _indice, nominativi, _cessati = Import()._indice_dipendenti()
        nascite = dict(
            DipendenteAnagraficaCivile.objects.exclude(data_nascita=None)
            .values_list("legacy_anagrafica_id", "data_nascita")
        )
        return nominativi, nascite

    def _da_fascicolo(self) -> list[Sorgente]:
        from anagrafica.management.commands.importa_archivio_hr import RIFERIMENTO_TIPO
        from anagrafica.models import DocumentoDipendente

        docs = (
            DocumentoDipendente.objects
            .filter(tipo=DocumentoDipendente.Tipo.VISITA_MEDICA_REFERTO,
                    oggetto_riferimento_tipo=RIFERIMENTO_TIPO,
                    nome_originale__iendswith=".pdf")
            .order_by("legacy_anagrafica_id", "id")
        )

        def lettore(doc):
            def leggi():
                with doc.file.open("rb") as handle:
                    return handle.read()
            return leggi

        return [
            Sorgente(etichetta=str(doc.legacy_anagrafica_id), nome_file=doc.nome_originale,
                     legacy_id=doc.legacy_anagrafica_id, leggi=lettore(doc), documento=doc)
            for doc in docs
        ]

    def _da_cartella(self, radice: Path, mappa_path) -> list[Sorgente]:
        from anagrafica.management.commands.importa_archivio_hr import Command as Import

        if not radice.is_dir():
            raise CommandError(f"Cartella non trovata: {radice}")
        importer = Import()
        indice, _nominativi, cessati = importer._indice_dipendenti()
        mappa = importer._leggi_mappa(mappa_path)

        sorgenti = []
        for dir_persona in sorted(p for p in radice.iterdir() if p.is_dir()):
            esito = importer._abbina(dir_persona.name, indice, mappa, cessati)
            # Un solo glob con filtro sul suffisso: su Windows "*.pdf" e "*.PDF"
            # trovano gli stessi file e ogni referto verrebbe letto due volte.
            pdf = (p for p in dir_persona.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf")
            for file in sorted(pdf):
                sorgenti.append(Sorgente(
                    etichetta=dir_persona.name, nome_file=file.name,
                    legacy_id=esito["legacy_id"], leggi=file.read_bytes,
                    motivo_persona=esito["motivo"],
                ))
        return sorgenti

    # ------------------------------------------------------------------ lettura

    def _leggi_file(self, sorgente: Sorgente, config, nominativi, nascite, apply) -> list[Lettura]:
        from anagrafica.services.referti_ocr import ErroreLettura, conta_pagine, testo_pagina
        from anagrafica.services.referti_parsing import TIPO_OCULISTICA, analizza_testo

        try:
            contenuto = sorgente.leggi()
        except Exception as exc:
            return [Lettura(sorgente, 1, ERRORE, f"File non leggibile: {exc.__class__.__name__}")]
        if not contenuto:
            return [Lettura(sorgente, 1, ERRORE, "File vuoto.")]

        sha = hashlib.sha256(contenuto).hexdigest()
        pagine = conta_pagine(contenuto)
        if not pagine:
            return [Lettura(sorgente, 1, ERRORE, "Il file non è un PDF leggibile.")]

        letture = []
        for pagina in range(min(pagine, MAX_PAGINE)):
            if apply and self._gia_letto(sha, pagina + 1):
                letture.append(Lettura(sorgente, pagina + 1, GIA_LETTO, "Pagina già elaborata."))
                continue
            try:
                campi = analizza_testo(testo_pagina(contenuto, pagina, config))
            except ErroreLettura as exc:
                lettura = Lettura(sorgente, pagina + 1, ERRORE, str(exc))
            except Exception as exc:
                logger.exception("Referto archivio: lettura fallita (%s p.%s)", sorgente.nome_file, pagina + 1)
                lettura = Lettura(sorgente, pagina + 1, ERRORE, f"Errore imprevisto: {exc.__class__.__name__}")
            else:
                if campi.tipo_referto == TIPO_OCULISTICA:
                    lettura = Lettura(
                        sorgente, pagina + 1, OCULISTICA,
                        "Certificato oculistico: data, tipo ed esito da inserire nella coda di revisione.",
                        campi,
                    )
                elif not campi.e_certificato:
                    # Pagina di continuazione o altro documento: resta nel fascicolo e basta.
                    letture.append(Lettura(sorgente, pagina + 1, NON_CERTIFICATO, "", campi))
                    continue
                else:
                    lettura = self._decidi(sorgente, pagina + 1, campi, config, nominativi, nascite)
            letture.append(lettura)
            if apply and lettura.decisione in (AUTO, REVISIONE, OCULISTICA):
                self._scrivi(lettura, sha, contenuto)
        return letture

    def _decidi(self, sorgente, pagina, campi, config, nominativi, nascite) -> Lettura:
        from anagrafica.models import VisitaMedica
        from anagrafica.services.referti_match import somiglianza
        from anagrafica.services.referti_registrazione import prepara_registrazione

        lettura = Lettura(sorgente, pagina, REVISIONE, campi=campi)
        lettura.piano = piano = prepara_registrazione(campi)
        lettura.requisiti = [
            (tipo.nome if tipo else f"{voce.get('esame', '')} (non a catalogo)")
            for tipo, voce in piano.requisiti
        ]
        ostacoli = []

        legacy_id = sorgente.legacy_id
        if not legacy_id:
            ostacoli.append(f"Cartella persona non abbinata ({sorgente.motivo_persona}).")
        if not campi.minimo_utile:
            ostacoli.append("Nominativo o data del giudizio non leggibili.")

        if legacy_id:
            nascita_anagrafica = nascite.get(legacy_id)
            if campi.nominativo:
                lettura.punteggio = somiglianza(campi.nominativo, nominativi.get(legacy_id, ""))
            lettura.conferma_nascita = bool(
                campi.data_nascita and nascita_anagrafica and campi.data_nascita == nascita_anagrafica
            )
            soglia = int(config.soglia_senza_data_nascita or 92)
            if campi.data_nascita and nascita_anagrafica and not lettura.conferma_nascita:
                ostacoli.append(
                    f"Data di nascita letta ({campi.data_nascita:%d-%m-%Y}) diversa dall'anagrafica."
                )
            elif not lettura.conferma_nascita:
                if campi.nominativo_da_ripiego:
                    ostacoli.append("Nominativo letto dalla riga di firma e data di nascita non confermata.")
                elif lettura.punteggio < soglia:
                    ostacoli.append(
                        f"Data di nascita non confermata e nominativo poco somigliante ({lettura.punteggio}%)."
                    )

        ostacoli.extend(piano.ostacoli)

        if piano.visita_tipo is not None:
            lettura.visita = piano.visita_tipo.nome
            if legacy_id and campi.data_giudizio:
                lettura.visita_presente = VisitaMedica.objects.filter(
                    legacy_anagrafica_id=legacy_id, data_svolgimento=campi.data_giudizio,
                    tipo=piano.visita_tipo,
                ).exists()

        if ostacoli:
            lettura.motivo = " ".join(ostacoli)
        else:
            lettura.decisione = AUTO
        return lettura

    # ------------------------------------------------------------------ scrittura

    def _gia_letto(self, sha: str, pagina: int) -> bool:
        from anagrafica.models_sorveglianza import RefertoIntakeRiga

        return RefertoIntakeRiga.objects.filter(sha256=sha, pagina=pagina).exists()

    def _scrivi(self, lettura: Lettura, sha: str, contenuto: bytes):
        from anagrafica.models_sorveglianza import RefertoIntakeRiga
        from anagrafica.services.referti_registrazione import ErroreRegistrazione, registra

        sorgente, campi = lettura.sorgente, lettura.campi
        doc = sorgente.documento
        oculistica = lettura.decisione == OCULISTICA
        riga = RefertoIntakeRiga(
            nome_file=sorgente.nome_file[:255],
            percorso=(doc.file.name if doc and doc.file else "")[:500],
            dimensione=len(contenuto),
            sha256=sha,
            pagina=lettura.pagina,
            origine="CARTELLA",
            tipo_referto=(RefertoIntakeRiga.TIPO_OCULISTICA if oculistica else RefertoIntakeRiga.TIPO_IDONEITA),
            esito=RefertoIntakeRiga.ESITO_DA_RIVEDERE,
            messaggio=(lettura.motivo or "")[:2000],
            letto_nominativo=(campi.nominativo or "")[:200],
            nominativo_da_ripiego=campi.nominativo_da_ripiego,
            letto_data_nascita=campi.data_nascita,
            letto_data_giudizio=campi.data_giudizio,
            letto_esito_testo=(campi.esito_testo or "")[:200],
            letto_mansione=(campi.mansione or "")[:200],
            letto_protocollo=campi.protocollo,
            date_trovate=campi.date_trovate,
            legacy_anagrafica_id_proposto=sorgente.legacy_id,
            punteggio=lettura.punteggio,
            data_nascita_conferma=lettura.conferma_nascita,
            divergenze=lettura.piano.divergenze if lettura.piano else [],
            documento=doc,
        )
        riga.save()
        if lettura.decisione != AUTO:
            return
        try:
            registra(riga, legacy_id=sorgente.legacy_id)
        except ErroreRegistrazione as exc:
            riga.esito = RefertoIntakeRiga.ESITO_DA_RIVEDERE
            riga.messaggio = str(exc)
            riga.save(update_fields=["esito", "messaggio"])
            lettura.decisione, lettura.motivo = REVISIONE, str(exc)
        except Exception:
            logger.exception("Referto archivio: registrazione fallita (riga %s)", riga.pk)
            riga.esito = RefertoIntakeRiga.ESITO_DA_RIVEDERE
            riga.messaggio = "Registrazione automatica fallita: lasciata alla conferma manuale."
            riga.save(update_fields=["esito", "messaggio"])
            lettura.decisione, lettura.motivo = REVISIONE, riga.messaggio

    # ------------------------------------------------------------------ report

    def _scrivi_report(self, path: Path, letture: list[Lettura], nominativi):
        campi_csv = [
            "cartella", "legacy_id", "nominativo_anagrafica", "file", "pagina", "decisione", "motivo",
            "nominativo_letto", "somiglianza", "nascita_confermata", "data_giudizio", "giudizio_letto",
            "esito", "visita", "visita_gia_presente", "requisiti", "requisiti_non_a_catalogo",
        ]
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=campi_csv, delimiter=";")
            writer.writeheader()
            for l in letture:
                c, p = l.campi, l.piano
                writer.writerow({
                    "cartella": l.sorgente.etichetta,
                    "legacy_id": l.sorgente.legacy_id or "",
                    "nominativo_anagrafica": nominativi.get(l.sorgente.legacy_id, ""),
                    "file": l.sorgente.nome_file,
                    "pagina": l.pagina,
                    "decisione": l.decisione,
                    "motivo": l.motivo,
                    "nominativo_letto": getattr(c, "nominativo", ""),
                    "somiglianza": l.punteggio or "",
                    "nascita_confermata": "sì" if l.conferma_nascita else "",
                    "data_giudizio": c.data_giudizio.strftime("%d/%m/%Y") if c and c.data_giudizio else "",
                    "giudizio_letto": getattr(c, "esito_testo", ""),
                    "esito": p.esito if p else "",
                    "visita": l.visita,
                    "visita_gia_presente": "sì" if l.visita_presente else "",
                    "requisiti": " | ".join(l.requisiti),
                    "requisiti_non_a_catalogo": " | ".join(p.esami_ignoti) if p else "",
                })
        self.stdout.write(f"Report scritto in {path}")

    def _riepilogo(self, letture: list[Lettura], apply: bool):
        w = self.stdout.write
        certificati = [l for l in letture if l.decisione in (AUTO, REVISIONE)]
        w("")
        w(self.style.SUCCESS(f"=== Referti archivio HR TOOLS ({'APPLY' if apply else 'DRY-RUN'}) ==="))
        w(f"  File letti: {len({id(l.sorgente) for l in letture})}   pagine: {len(letture)}")
        for decisione, n in Counter(l.decisione for l in letture).most_common():
            w(f"    {decisione:18s} {n}")
        auto = [l for l in certificati if l.decisione == AUTO]
        verbo = "sono state" if apply else "verrebbero"
        w(f"  Visite che {verbo} create: {sum(1 for l in auto if not l.visita_presente)} "
          f"(già presenti: {sum(1 for l in auto if l.visita_presente)}) — una per certificato di idoneità")
        w(f"  Requisiti dai protocolli dei certificati registrati: {sum(len(l.requisiti) for l in auto)}")
        oculistici = sum(1 for l in letture if l.decisione == OCULISTICA)
        if oculistici:
            w(f"  Certificati oculistici {'messi' if apply else 'da mettere'} in coda "
              f"(data, tipo ed esito scritti a mano): {oculistici}")

        anni = Counter(l.campi.data_giudizio.year for l in certificati if l.campi and l.campi.data_giudizio)
        if anni:
            w("  Certificati per anno del giudizio: "
              + ", ".join(f"{a}: {n}" for a, n in sorted(anni.items())))

        motivi = Counter()
        for l in letture:
            if l.decisione == REVISIONE:
                for pezzo in l.motivo.split(". "):
                    motivi[pezzo.split(":")[0].split("(")[0].strip().rstrip(".")] += 1
        if motivi:
            w("  Motivi di revisione:")
            for motivo, n in motivi.most_common(12):
                w(f"    {n:4d}  {motivo}")

        from anagrafica.services.referti_registrazione import ripulisci_esame, ripulisci_giudizio

        # Raggruppati per nome ripulito + periodicità: è la forma in cui vanno
        # inseriti gli alias (una riga per esame e cadenza).
        requisiti_ignoti = Counter()
        for l in certificati:
            if not l.piano:
                continue
            for tipo, voce in l.piano.requisiti:
                if tipo is None:
                    requisiti_ignoti[f"{ripulisci_esame(voce.get('esame', ''))} — {voce.get('periodicita') or '?'}"] += 1
        if requisiti_ignoti:
            w(self.style.WARNING(
                "  Esami del protocollo NON a catalogo (esame — periodicità). Per la «Visita Medica» "
                "bloccano, per i requisiti no (si registrano senza tipo):"
            ))
            for esame, n in requisiti_ignoti.most_common():
                w(f"    {n:4d}  {esame}")
        giudizi = Counter(
            ripulisci_giudizio(l.campi.esito_testo or "") or "—"
            for l in certificati if l.piano and not l.piano.esito
        )
        if giudizi:
            w(self.style.WARNING("  Giudizi NON riconosciuti (da mappare negli alias):"))
            for giudizio, n in giudizi.most_common():
                w(f"    {n:4d}  {giudizio}")
        errori = Counter(l.motivo for l in letture if l.decisione == ERRORE)
        if errori:
            w("  Errori di lettura:")
            for motivo, n in errori.most_common(8):
                w(f"    {n:4d}  {motivo}")
        w("")
        if not apply:
            w(self.style.NOTICE("DRY-RUN: nessuna scrittura. Rilancia con --apply per registrare."))
