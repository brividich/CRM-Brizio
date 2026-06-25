"""F8 — Import storico specifiche (solo "In validità").

Validatore + logica di import idempotente, riusati dal management command
`import_specifiche_storico`. Solo specifiche **In validità** (decisione F0 #5).

`data_inserimento` (auto_now_add) e `stato` (FSMField protected) sono impostati
via `queryset.update()` per preservare la data storica e bypassare la protezione
FSM; l'evento `EventoSpecifica(trigger="import_storico")` traccia l'import.
"""
from __future__ import annotations

from datetime import datetime, time

from django.db import transaction
from django.utils.timezone import make_aware

from . import constants as C
from .models import EventoSpecifica, Specifica

# Colonne attese nel CSV (mappate 1:1 sui campi del modello).
EXPECTED_COLUMNS = [
    "codice", "revisione", "titolo", "tipo", "fonte", "cliente", "tag",
    "data_inserimento", "data_verifica", "note", "stato", "master_codice",
]
REQUIRED_COLUMNS = ["codice", "titolo", "tipo", "fonte"]

_TIPI = dict(C.TIPO_CHOICES)
_FONTI = dict(C.FONTE_CHOICES)


def _val(row: dict, key: str) -> str:
    return (row.get(key) or "").strip()


def _parse_date(value: str):
    value = (value or "").strip()
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def valida_riga(row: dict) -> list[str]:
    """Restituisce la lista di errori per una riga (vuota = valida)."""
    errori: list[str] = []
    for col in REQUIRED_COLUMNS:
        if not _val(row, col):
            errori.append(f"campo obbligatorio mancante: {col}")

    tipo = _val(row, "tipo")
    if tipo and tipo not in _TIPI:
        errori.append(f"tipo non valido: '{tipo}' (ammessi: {', '.join(_TIPI)})")
    fonte = _val(row, "fonte")
    if fonte and fonte not in _FONTI:
        errori.append(f"fonte non valida: '{fonte}' (ammessi: {', '.join(_FONTI)})")

    stato = _val(row, "stato") or C.STATO_IN_VALIDITA
    if stato != C.STATO_IN_VALIDITA:
        errori.append("import consentito solo per specifiche 'in_validita' (decisione F0 #5)")

    for dcol in ("data_inserimento", "data_verifica"):
        v = _val(row, dcol)
        if v:
            try:
                _parse_date(v)
            except ValueError:
                errori.append(f"data non valida in {dcol}: '{v}' (atteso YYYY-MM-DD)")
    return errori


@transaction.atomic
def importa_riga(row: dict, *, apply: bool) -> str:
    """Importa una riga. Ritorna l'esito:
    'creato' | 'duplicato' | 'valido (dry-run)' | 'scartato: <motivi>'."""
    errori = valida_riga(row)
    if errori:
        return "scartato: " + "; ".join(errori)

    codice = _val(row, "codice")
    revisione = _val(row, "revisione") or "0"

    if Specifica.objects.filter(codice=codice, revisione=revisione).exists():
        return "duplicato"
    if not apply:
        return "valido (dry-run)"

    master = None
    master_codice = _val(row, "master_codice")
    if master_codice:
        master = Specifica.objects.filter(codice=master_codice).order_by("-data_inserimento").first()

    spec = Specifica.objects.create(
        codice=codice, revisione=revisione, titolo=_val(row, "titolo"),
        tipo=_val(row, "tipo"), fonte=_val(row, "fonte"),
        cliente=_val(row, "cliente"), tag=_val(row, "tag"),
        note=_val(row, "note"), master=master,
    )

    updates = {"stato": C.STATO_IN_VALIDITA}
    di = _parse_date(_val(row, "data_inserimento"))
    if di:
        # Mezzogiorno locale: evita lo shift di giorno in UTC per le date storiche.
        updates["data_inserimento"] = make_aware(datetime.combine(di, time(12, 0)))
    dv = _parse_date(_val(row, "data_verifica"))
    if dv:
        updates["data_verifica"] = dv
    Specifica.objects.filter(pk=spec.pk).update(**updates)

    spec = Specifica.objects.get(pk=spec.pk)
    EventoSpecifica.objects.create(
        specifica=spec, stato_da="", stato_a=C.STATO_IN_VALIDITA,
        trigger="import_storico",
        payload={"snapshot": spec.snapshot_metadati(), "import_storico": True},
    )
    return "creato"


def importa_righe(rows, *, apply: bool) -> dict:
    """Importa un iterabile di righe (dict). Ritorna il conteggio per esito e i
    dettagli degli scarti (riga, motivo)."""
    counters = {"creato": 0, "duplicato": 0, "valido": 0, "scartato": 0}
    scarti: list[tuple[int, str]] = []
    for idx, row in enumerate(rows, start=2):  # start=2: riga 1 = intestazione
        esito = importa_riga(row, apply=apply)
        if esito.startswith("scartato"):
            counters["scartato"] += 1
            scarti.append((idx, esito))
        elif esito == "duplicato":
            counters["duplicato"] += 1
        elif esito == "creato":
            counters["creato"] += 1
        else:
            counters["valido"] += 1
    return {"counters": counters, "scarti": scarti}


# --- Generazione template ----------------------------------------------------

_ESEMPI = [
    {
        "codice": "SPEC-2023-001", "revisione": "2", "titolo": "Trattamento termico lega X",
        "tipo": C.TIPO_SPECIFICA, "fonte": C.FONTE_CLIENTE, "cliente": "ACME Aerospace",
        "tag": "trattamenti_termici", "data_inserimento": "2023-03-14",
        "data_verifica": "2026-09-14", "note": "Importata da archivio cartaceo",
        "stato": C.STATO_IN_VALIDITA, "master_codice": "",
    },
    {
        "codice": "COM-2024-017", "revisione": "0", "titolo": "Comunicazione requisiti imballo",
        "tipo": C.TIPO_COMUNICAZIONE, "fonte": C.FONTE_GENERICA, "cliente": "",
        "tag": "logistica", "data_inserimento": "2024-01-09", "data_verifica": "",
        "note": "Caratteri accentati: città, però (NVARCHAR)", "stato": C.STATO_IN_VALIDITA,
        "master_codice": "",
    },
]


def scrivi_template_csv(path: str, delimiter: str = ";") -> None:
    import csv

    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=EXPECTED_COLUMNS, delimiter=delimiter)
        writer.writeheader()
        for r in _ESEMPI:
            writer.writerow(r)


def scrivi_template_xlsx(path: str) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "import_specifiche"
    ws.append(EXPECTED_COLUMNS)
    for r in _ESEMPI:
        ws.append([r.get(c, "") for c in EXPECTED_COLUMNS])
    wb.save(path)
