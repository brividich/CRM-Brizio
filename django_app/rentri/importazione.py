"""Import del registro da CSV esportato dalla lista SharePoint RENTRI.

Un solo parser per la pagina (anteprima + conferma) e per il comando
``import_rentri_csv``. L'import è **tutto o niente**: una transazione sola, se
una riga fallisce non resta mezzo registro caricato. I numeri di
registrazione del file restano quelli del file.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime
from decimal import Decimal

from django.db import transaction

from .catena import split_rif_op
from .models import RegistroRifiuti


_IMPORT_TIPO_MAP = {
    "C - Carico": "C",
    "O - Scarico originario": "O",
    "M - Scarico effettivo": "M",
    "R - Rettifica scarico": "R",
}


def _parse_num_it(raw: str):
    """Converte numero in formato italiano (1.234 → 1234) in float o None."""
    s = raw.strip().replace(".", "").replace(",", ".")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _split_sp_multivalue_csv(raw: str) -> list[str]:
    """Spezza un campo multi-valore SharePoint (formato ``valore;#id;#valore;#id``)."""
    raw = raw.strip()
    if not raw:
        return []
    return [p.lstrip("#").strip() for p in raw.split(";") if p.lstrip("#").strip()]


def _parse_pericolosita_csv(raw: str) -> str:
    """Estrae codici HP (HP04, HP05…) dal campo multi-valore SharePoint o dall'export a lista JSON."""
    codes = list(dict.fromkeys(re.findall(r"HP\d+", raw)))
    if codes:
        return ", ".join(codes)[:100]
    return raw.strip()[:100]


def _detect_csv_delimiter(content: str) -> str:
    """Rileva il delimitatore (';' o ',') dalla riga di intestazione del CSV."""
    header_line = content.splitlines()[0] if content else ""
    try:
        return csv.Sniffer().sniff(header_line, delimiters=";,").delimiter
    except csv.Error:
        return ";"


def _parse_rif_op_csv(raw: str) -> str:
    """Estrae i riferimenti (ID Registrazione) dal campo lookup multi-valore SharePoint."""
    parts = _split_sp_multivalue_csv(raw)
    refs = [p for p in parts if "/" in p]
    if refs:
        return ", ".join(refs)[:200]
    return raw.strip()[:200]


def _parse_csv_rows(content: str) -> tuple[list[dict], list[dict]]:
    """Analizza il contenuto CSV; restituisce (righe_ok, errori)."""
    rows: list[dict] = []
    errors: list[dict] = []

    reader = csv.reader(io.StringIO(content), delimiter=_detect_csv_delimiter(content))
    try:
        next(reader)  # salta intestazione
    except StopIteration:
        return [], [{"riga": 0, "msg": "File vuoto o senza intestazione"}]

    # Colonne 10-11 ("Elemento";"Lists/RENTRI") sono metadati SharePoint
    # (tipo di contenuto e percorso lista), non dati: ignorate.
    for line_no, row in enumerate(reader, start=2):
        if not any(cell.strip() for cell in row):
            continue
        if len(row) < 10:
            errors.append({"riga": line_no, "msg": f"Colonne insufficienti ({len(row)})"})
            continue
        try:
            data_raw = row[0].strip()
            try:
                data = datetime.strptime(data_raw, "%d/%m/%Y").date()
            except ValueError:
                errors.append({"riga": line_no, "msg": f"Data non valida: '{data_raw}'"})
                continue

            tipo_raw = row[6].strip()
            tipo = _IMPORT_TIPO_MAP.get(tipo_raw)
            if not tipo:
                errors.append({"riga": line_no, "msg": f"Tipo sconosciuto: '{tipo_raw}'"})
                continue

            id_reg = row[1].strip()
            codice = " ".join(row[2].split())[:100]
            pericolosita = _parse_pericolosita_csv(row[3])
            quantita = _parse_num_it(row[4])
            rettifica = _parse_num_it(row[5])
            note = row[7].strip()
            # Il CSV non ha una colonna "Rentri SI/NO" dedicata: resta al default (False).
            rentri_si_no = False
            # Il testo libero contiene il riferimento FIR solo per gli scarichi (O/M);
            # se presente lo si duplica anche in arrivo_fir (letto dallo scadenzario).
            arrivo_fir = note if "FIR" in note.upper() else ""
            inserito_da = row[8].strip()
            rif_op = _parse_rif_op_csv(row[9])

            esiste = RegistroRifiuti.objects.filter(id_registrazione=id_reg, tipo=tipo).exists()

            rows.append({
                "riga": line_no,
                "data": data.strftime("%d-%m-%Y"),
                "_data_iso": data.isoformat(),
                "tipo": tipo,
                "id_reg": id_reg,
                "codice": codice,
                "quantita": str(quantita) if quantita is not None else "",
                "rettifica": str(rettifica) if rettifica is not None else "",
                "pericolosita": pericolosita,
                "note": note,
                "rentri_si_no": rentri_si_no,
                "arrivo_fir": arrivo_fir,
                "inserito_da": inserito_da,
                "rif_op": rif_op,
                "esiste": esiste,
            })
        except Exception as exc:
            errors.append({"riga": line_no, "msg": str(exc)})

    return rows, errors


class ImportAnnullato(Exception):
    """Una riga non si è potuta scrivere: l'intero import è stato annullato."""

    def __init__(self, errori: list[dict]):
        self.errori = errori
        super().__init__(f"{len(errori)} righe in errore")


def importa_righe(rows: list[dict], *, utente: str = "", dry_run: bool = False) -> dict:
    """Scrive le righe analizzate da :func:`_parse_csv_rows`, tutto o niente.

    Le righe già presenti (stesso numero e tipo) si saltano. Ritorna i conteggi
    e gli ``avvisi`` sui riferimenti ``rif_op`` che dopo l'import non portano a
    nessun movimento: non bloccano (lo storico può citare movimenti mai
    importati) ma vanno controllati.
    """
    created = skipped = 0
    errori: list[dict] = []
    visti: set[tuple[str, str]] = set()
    with transaction.atomic():
        for r in rows:
            chiave = (r["id_reg"], r["tipo"])
            if r["esiste"] or chiave in visti:
                skipped += 1
                continue
            visti.add(chiave)
            try:
                with transaction.atomic():
                    registro = RegistroRifiuti(
                        tipo=r["tipo"],
                        data=datetime.fromisoformat(r["_data_iso"]).date(),
                        id_registrazione=r["id_reg"],
                        codice=r["codice"],
                        quantita=Decimal(r["quantita"]) if r["quantita"] else None,
                        rettifica_scarico=Decimal(r["rettifica"]) if r["rettifica"] else None,
                        carico_scarico=r["tipo"],
                        pericolosita=r["pericolosita"],
                        note_rentri=r["note"],
                        rentri_si_no=r["rentri_si_no"],
                        arrivo_fir=r["arrivo_fir"],
                        rif_op=r["rif_op"],
                        inserito_da=r["inserito_da"] or utente,
                        origine="import",
                    )
                    registro.save()
                    if registro.id_registrazione != r["id_reg"]:
                        RegistroRifiuti.objects.filter(pk=registro.pk).update(id_registrazione=r["id_reg"])
                created += 1
            except Exception as exc:  # noqa: BLE001 - riportato riga per riga
                errori.append({"riga": r["riga"], "msg": str(exc)[:300]})
        if errori:
            raise ImportAnnullato(errori)
        avvisi = _avvisi_riferimenti(rows)
        if dry_run:
            transaction.set_rollback(True)
    return {"created": created, "skipped": skipped, "avvisi": avvisi}


def _avvisi_riferimenti(rows: list[dict]) -> list[dict]:
    refs = {rid for r in rows for rid in split_rif_op(r["rif_op"])}
    if not refs:
        return []
    presenti = set(RegistroRifiuti.objects.filter(id_registrazione__in=refs).values_list("id_registrazione", flat=True))
    avvisi = []
    for r in rows:
        mancanti = [rid for rid in split_rif_op(r["rif_op"]) if rid not in presenti]
        if mancanti:
            avvisi.append({"riga": r["riga"], "msg": f"Rif. Op non trovato nel registro: {', '.join(mancanti)}"})
    return avvisi
