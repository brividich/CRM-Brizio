"""
Importa immagini timbri dalla share di rete \\Novisrv\\area it\\_FIRME E TIMBRI.

Struttura cartelle: <COGNOME> <INIZIALE NOME>  (es. "Bova L")
File riconosciuti per variante:
  TIMBRO : contiene "timbro" ma non "firma" né "sigla"
  FIRMA  : contiene "timbro" e "firma", oppure solo "firma"
  SIGLA  : contiene "timbro" e "sigla", oppure solo "sigla"

Logica:
  - Trova il RegistroTimbro attivo (is_attivo=True) per ogni operatore
  - Di default filtra codice_timbro__icontains="CNO" (timbri personali)
  - Con --tutti: include tutti i timbri attivi (anche RICEVUTO, RIESAME, ecc.)
  - Se ha già tutte le varianti -> salta (idempotente)
  - Salva i file nello storage privato (TIMBRI_PRIVATE_ROOT)
  - Non sovrascrive immagini già presenti per la stessa variante

Utilizzo:
    # Dry-run (default): mostra cosa farebbe senza toccare nulla
    python manage.py import_timbri_da_share

    # Applica (solo timbri CNO)
    python manage.py import_timbri_da_share --apply

    # Applica anche timbri non-CNO (RICEVUTO, RIESAME, ecc.)
    python manage.py import_timbri_da_share --apply --tutti

    # Solo un dipendente (per test)
    python manage.py import_timbri_da_share --apply --cognome "BOVA"
"""
from __future__ import annotations

import io
import re
import unicodedata
from pathlib import Path

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.utils import timezone

SHARE_ROOT = Path("//Novisrv/area it/_FIRME E TIMBRI")

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".bmp"}

# Cartelle da ignorare (non sono dipendenti)
SKIP_DIRS = {
    "!censimento timbri giugno 2023",
    "_nuovi timbri_nov.2019",
    "_timbri distribuzione permanente",
    "_timbri_superati",
    "nuova cartella",
    "nuova cartella (2)",
    "nuova cartella (3)",
    "nuovi",
    "timbri ricevuti installati sui pc",
}


def _normalizza(s: str) -> str:
    """Lowercase, rimuove accenti e caratteri non ASCII."""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.lower().strip()


def _classifica_file(nome: str) -> str | None:
    """Restituisce 'TIMBRO', 'FIRMA', 'SIGLA' o None se non riconoscibile."""
    n = _normalizza(nome)
    ha_timbro = "timbro" in n
    ha_firma = "firma" in n
    ha_sigla = "sigla" in n

    if ha_timbro and ha_firma:
        return "FIRMA"
    if ha_timbro and ha_sigla:
        return "SIGLA"
    if ha_timbro:
        return "TIMBRO"
    # File solo firma/sigla (senza "timbro" nel nome)
    if ha_firma and not ha_sigla:
        return "FIRMA"
    if ha_sigla and not ha_firma:
        return "SIGLA"
    return None


def _cartella_key(nome_dir: str) -> tuple[str, str]:
    """Restituisce (cognome_norm, iniziale_norm) dalla cartella 'Bova L'."""
    parti = nome_dir.strip().split()
    if not parti:
        return ("", "")
    cognome = _normalizza(parti[0])
    iniziale = _normalizza(parti[1][0]) if len(parti) > 1 and parti[1] else ""
    return (cognome, iniziale)


class Command(BaseCommand):
    help = "Importa immagini timbri dalla share di rete (una-tantum)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            default=False,
            help="Applica il salvataggio. Senza questo flag: dry-run.",
        )
        parser.add_argument(
            "--cognome",
            default=None,
            help="Limita a un solo cognome (es. BOVA).",
        )
        parser.add_argument(
            "--tutti",
            action="store_true",
            default=False,
            help="Includi tutti i timbri attivi, non solo quelli con codice CNO.",
        )
        parser.add_argument(
            "--share",
            default=str(SHARE_ROOT),
            help=f"Path share. Default: {SHARE_ROOT}",
        )

    def handle(self, *args, **options):
        from timbri.models import OperatoreTimbri, RegistroTimbro, RegistroTimbroImmagine
        from timbri.storage import PrivateTimbriStorage

        apply = options["apply"]
        tutti = options["tutti"]
        filtro_cognome = _normalizza(options["cognome"]) if options["cognome"] else None
        share = Path(options["share"])

        if not apply:
            self.stdout.write(self.style.WARNING("DRY-RUN — usa --apply per salvare."))
        if tutti:
            self.stdout.write(self.style.WARNING("--tutti attivo: include timbri non-CNO."))

        if not share.exists():
            self.stderr.write(self.style.ERROR(f"Share non raggiungibile: {share}"))
            return

        storage = PrivateTimbriStorage()

        # Costruisci indice cartelle: (cognome_norm, iniziale_norm) -> Path
        cartelle: dict[tuple[str, str], Path] = {}
        for d in share.iterdir():
            if not d.is_dir():
                continue
            if _normalizza(d.name) in SKIP_DIRS:
                continue
            key = _cartella_key(d.name)
            if key[0]:
                cartelle[key] = d

        # Indice operatori attivi: (cognome_norm, iniziale_norm) -> lista OperatoreTimbri
        operatori: dict[tuple[str, str], list] = {}
        for op in OperatoreTimbri.objects.filter(is_active_legacy=True).exclude(cognome=""):
            key = (_normalizza(op.cognome), _normalizza(op.nome[0]) if op.nome else "")
            operatori.setdefault(key, []).append(op)

        totale_salvate = 0
        totale_saltate = 0
        totale_senza_cartella = 0
        totale_senza_record = 0
        no_match: list[str] = []

        for key, op_list in sorted(operatori.items()):
            cognome_norm, iniziale_norm = key

            if filtro_cognome and cognome_norm != filtro_cognome:
                continue

            cartella = cartelle.get(key)
            if cartella is None:
                totale_senza_cartella += 1
                no_match.append(f"{op_list[0].cognome} {op_list[0].nome}")
                continue

            # Trova il RegistroTimbro attivo per questi operatori.
            # Di default solo CNO; con --tutti anche RICEVUTO, RIESAME, ecc.
            qs = RegistroTimbro.objects.filter(operatore__in=op_list, is_attivo=True)
            if not tutti:
                qs = qs.filter(codice_timbro__icontains="CNO")
            registro = qs.order_by("-updated_at").first()
            if registro is None:
                totale_senza_record += 1
                self.stdout.write(f"  [NESSUN RECORD] {cartella.name}")
                continue

            # Varianti già presenti
            varianti_esistenti = set(
                RegistroTimbroImmagine.objects.filter(registro=registro).values_list(
                    "variante", flat=True
                )
            )

            # Scansiona i file della cartella
            candidati: dict[str, Path] = {}
            for f in cartella.iterdir():
                if not f.is_file():
                    continue
                if f.suffix.lower() not in IMAGE_EXTS:
                    continue
                if f.name.lower() == "thumbs.db":
                    continue
                variante = _classifica_file(f.stem)
                if variante is None:
                    continue
                # Preferisci file con "timbro" nel nome se già c'è un candidato
                if variante not in candidati or "timbro" in f.stem.lower():
                    candidati[variante] = f

            if not candidati:
                self.stdout.write(f"  [NO FILE] {cartella.name} — nessun file riconoscibile")
                continue

            self.stdout.write(f"\n  {cartella.name} -> registro sp_id={registro.sharepoint_item_id} codice={registro.codice_timbro}")

            for variante, filepath in sorted(candidati.items()):
                if variante in varianti_esistenti:
                    self.stdout.write(f"    [{variante}] già presente — salto")
                    totale_saltate += 1
                    continue

                self.stdout.write(f"    [{variante}] {filepath.name}", ending="")

                if apply:
                    try:
                        data = filepath.read_bytes()
                        nome_salvato = f"{registro.sharepoint_item_id}__{filepath.name}"
                        saved_name = storage.save(nome_salvato, ContentFile(data, name=nome_salvato))
                        RegistroTimbroImmagine.objects.create(
                            registro=registro,
                            variante=variante,
                            image=saved_name,
                            original_filename=filepath.name,
                        )
                    except Exception as exc:
                        self.stdout.write(f" ERRORE: {exc}")
                    else:
                        totale_salvate += 1
                        self.stdout.write(" OK")
                else:
                    self.stdout.write(" [dry-run]")
                    totale_salvate += 1

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            f"{'Salvate' if apply else 'Da salvare'}: {totale_salvate} | "
            f"Già presenti: {totale_saltate} | "
            f"Senza cartella: {totale_senza_cartella} | "
            f"Senza record attivo: {totale_senza_record}"
        ))

        if no_match:
            self.stdout.write(self.style.WARNING(
                f"\nOperatori senza cartella corrispondente ({len(no_match)}):"
            ))
            for n in sorted(no_match):
                self.stdout.write(f"  {n}")
