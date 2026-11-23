"""Import massivo degli ospiti da Excel e allegati delle visite.

Un gruppo (una classe in gita, i partecipanti a un evento) si carica con un solo file: ogni riga diventa
un partecipante dell'invito del capogruppo (esistente o creato qui) o della visita di chi è già dentro, ed
entra ed esce con lui (``reception.gruppi``). I cartellini sono facoltativi (di base senza). Un errore in
qualunque riga ferma tutto l'import.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import PurePath

from django.db import transaction

from . import servizi
from .models import AllegatoVisita, PartecipanteGruppo, Visita

MAX_RIGHE = 500
MAX_ALLEGATO_MB = 10
ESTENSIONI_ALLEGATO = {".pdf", ".xlsx", ".xls", ".csv", ".docx", ".doc", ".odt", ".ods", ".jpg", ".jpeg", ".png", ".txt"}

# Intestazioni del modello; in lettura bastano Cognome e Nome, le altre sono facoltative.
COLONNE = ("Cognome", "Nome", "Azienda / scuola", "Email", "Telefono")
SINONIMI = {
    "cognome": "cognome", "nome": "nome",
    "azienda / scuola": "azienda", "azienda": "azienda", "scuola": "azienda", "ente": "azienda", "società": "azienda",
    "email": "email", "e-mail": "email", "mail": "email",
    "telefono": "telefono", "cellulare": "telefono", "tel": "telefono",
}
LUNGHEZZE = {"cognome": 100, "nome": 100, "azienda": 255, "email": 255, "telefono": 50}


class ImportNonValido(Exception):
    """Il messaggio (ed eventualmente l'elenco ``righe``) si mostra all'operatore."""

    def __init__(self, messaggio: str, righe: list[str] | None = None):
        super().__init__(messaggio)
        self.righe = righe or []


@dataclass
class Esito:
    aggiunti: int = 0
    entrati: int = 0
    gia_dentro: int = 0
    doppi: list[str] = field(default_factory=list)


def modello_xlsx() -> bytes:
    """Il modello da compilare: foglio «Ospiti» con le intestazioni e foglio «Istruzioni»."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.worksheet.table import Table, TableStyleInfo

    wb = Workbook()
    ws = wb.active
    ws.title = "Ospiti"
    ws.append(list(COLONNE))
    for cella in ws[1]:
        cella.font = Font(bold=True, color="FFFFFF")
        cella.fill = PatternFill("solid", fgColor="1F4E79")
    for lettera, larghezza in zip("ABCDE", (24, 22, 30, 32, 18)):
        ws.column_dimensions[lettera].width = larghezza
    ws.freeze_panes = "A2"
    tabella = Table(displayName="Ospiti", ref="A1:E2")
    tabella.tableStyleInfo = TableStyleInfo(name="TableStyleLight9", showRowStripes=True)
    ws.add_table(tabella)

    info = wb.create_sheet("Istruzioni")
    info.column_dimensions["A"].width = 110
    for riga in (
        "Come compilare il modello",
        "",
        "Una persona per riga nel foglio «Ospiti», a partire dalla riga 2. Non cambiare le intestazioni.",
        "Cognome e Nome sono obbligatori; Azienda / scuola, Email e Telefono sono facoltativi.",
        "Se l'email c'è già nel portale con un altro nome, l'import si ferma e indica la riga da correggere.",
        f"Al massimo {MAX_RIGHE} righe per file. Le righe vuote vengono ignorate.",
        "",
        "In Reception → Oggi → «Importa elenco»: collega il file a un invito (anche nuovo) o a chi è già dentro.",
        "Le persone entrano con il capogruppo (codice dell'invito o registrazione al chiosco) ed escono con lui.",
        "Da dentro contano tra i presenti in azienda, anche per l'emergenza.",
        "I cartellini non vengono assegnati, a meno di spuntare «Assegna i cartellini».",
        "Ricaricando un elenco aggiornato, chi c'è già nel gruppo (stesso cognome e nome) viene saltato.",
    ):
        info.append([riga])
    info["A1"].font = Font(bold=True, size=13)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _testo(valore) -> str:
    if valore is None:
        return ""
    if isinstance(valore, float) and valore.is_integer():
        valore = int(valore)  # telefoni scritti come numero
    return " ".join(str(valore).split())


def leggi_xlsx(file) -> list[dict]:
    """Le righe del primo foglio con almeno Cognome o Nome. L'intestazione può stare in una delle prime 10 righe."""
    from openpyxl import load_workbook

    try:
        wb = load_workbook(file, read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - qualunque file non leggibile
        raise ImportNonValido("Il file non è un Excel leggibile (.xlsx). Usa il modello scaricabile da questa pagina.") from exc
    try:
        ws = wb.worksheets[0]
        righe = ws.iter_rows(values_only=True)
        mappa: dict[int, str] = {}
        n_riga = 0
        for n_riga, valori in enumerate(righe, start=1):
            prova = {i: SINONIMI.get(_testo(v).lower()) for i, v in enumerate(valori or ())}
            prova = {i: c for i, c in prova.items() if c}
            if {"cognome", "nome"} <= set(prova.values()):
                mappa = prova
                break
            if n_riga >= 10:
                break
        if not mappa:
            raise ImportNonValido("Nel primo foglio non trovo le colonne «Cognome» e «Nome». Usa il modello scaricabile da questa pagina.")
        dati = []
        for n, valori in enumerate(righe, start=n_riga + 1):
            riga = {c: _testo(valori[i]) if i < len(valori) else "" for i, c in mappa.items()}
            if not any(riga.values()):
                continue
            riga["n"] = n
            dati.append(riga)
            if len(dati) > MAX_RIGHE:
                raise ImportNonValido(f"Il file ha più di {MAX_RIGHE} persone: dividilo in più file.")
        return dati
    finally:
        wb.close()


def controlla(righe: list[dict]) -> list[str]:
    """Gli errori riga per riga (vuoto = tutto a posto)."""
    errori = []
    viste = {}
    for r in righe:
        n = r["n"]
        if not r.get("cognome") or not r.get("nome"):
            errori.append(f"Riga {n}: mancano cognome o nome.")
            continue
        for campo, massimo in LUNGHEZZE.items():
            if len(r.get(campo, "")) > massimo:
                errori.append(f"Riga {n}: {campo} troppo lungo (massimo {massimo} caratteri).")
        email = r.get("email", "").lower()
        if email:
            if "@" not in email:
                errori.append(f"Riga {n}: email «{email}» non valida.")
                continue
            if email in viste:
                errori.append(f"Riga {n}: email uguale alla riga {viste[email]}.")
                continue
            viste[email] = n
            o = servizi.trova_ospite_per_email(email)
            if o and (o.nome.strip().lower(), o.cognome.strip().lower()) != (r["nome"].lower(), r["cognome"].lower()):
                errori.append(f"Riga {n}: l'email {email} è già di {o.nome_completo}.")
    return errori


def salva_partecipanti(righe: list[dict], *, preregistrazione=None, visita_capo: Visita | None = None,
                       con_cartellini: bool = False, autore: str = "") -> Esito:
    """Aggiunge le righe al gruppo di un invito o di chi è già dentro. Chi c'è già nel gruppo (stesso
    cognome e nome) si salta; con ``visita_capo`` i nuovi entrano subito. Un errore annulla tutto."""
    from .gruppi import entra_gruppo, partecipanti_di

    if (preregistrazione is None) == (visita_capo is None):
        raise ImportNonValido("Scegli un invito oppure chi è già dentro.")
    errori = controlla(righe)
    if errori:
        raise ImportNonValido("Nessuno è stato aggiunto: correggi il file e ricaricalo.", errori)
    if not righe:
        raise ImportNonValido("Il file non contiene persone.")
    if visita_capo is not None and visita_capo.stato != Visita.DENTRO:
        raise ImportNonValido("Il capogruppo non risulta più dentro.")
    gruppo = partecipanti_di(preregistrazione=preregistrazione, visita_capo=visita_capo)
    presenti = {(p.cognome.lower(), p.nome.lower()) for p in gruppo}
    esito = Esito()
    with transaction.atomic():
        nuovi = []
        for r in righe:
            chiave = (r["cognome"].lower(), r["nome"].lower())
            if chiave in presenti:
                esito.doppi.append(f"{r['cognome']} {r['nome']}")
                continue
            presenti.add(chiave)
            nuovi.append(PartecipanteGruppo.objects.create(
                preregistrazione=preregistrazione, visita_capo=visita_capo, cognome=r["cognome"], nome=r["nome"],
                azienda=r.get("azienda", ""), email=r.get("email", "").lower(), telefono=r.get("telefono", ""),
                con_cartellino=con_cartellini, creato_da=(autore or "")[:150],
            ))
        esito.aggiunti = len(nuovi)
        if visita_capo is not None and nuovi:
            if con_cartellini and len(servizi.cartellini_liberi()) < len(nuovi):
                raise ImportNonValido(f"Ci sono {len(servizi.cartellini_liberi())} cartellini liberi per {len(nuovi)} persone: "
                                      "togli la spunta «Assegna i cartellini» o liberane altri.")
            ingresso = entra_gruppo(visita_capo, PartecipanteGruppo.objects.filter(pk__in=[p.pk for p in nuovi]))
            esito.entrati, esito.gia_dentro = ingresso["entrati"], ingresso["gia_dentro"]
    return esito

def controlla_allegato(file) -> str:
    """Messaggio d'errore per l'operatore, vuoto se il file va bene."""
    if file is None:
        return "Scegli un file."
    estensione = PurePath(file.name or "").suffix.lower()
    if estensione not in ESTENSIONI_ALLEGATO:
        return f"Tipo di file non ammesso. Ammessi: {', '.join(sorted(e.lstrip('.') for e in ESTENSIONI_ALLEGATO))}."
    if file.size > MAX_ALLEGATO_MB * 1024 * 1024:
        return f"Il file supera {MAX_ALLEGATO_MB} MB."
    from core.upload_mime import UploadMimeValidationError, valida_per_estensione

    try:  # contenuto reale, non solo il nome (audit [56])
        valida_per_estensione(file, ESTENSIONI_ALLEGATO, max_bytes=MAX_ALLEGATO_MB * 1024 * 1024, label="Allegato")
    except UploadMimeValidationError as exc:
        return str(exc)
    return ""


def allega(visita: Visita, file, *, autore: str) -> AllegatoVisita:
    nome = PurePath(file.name or "allegato").name[:255]
    allegato = AllegatoVisita(visita=visita, nome=nome, dimensione=file.size or 0, caricato_da=(autore or "")[:150])
    allegato.file.save(nome, file, save=False)
    allegato.save()
    return allegato


def elimina_allegato(allegato: AllegatoVisita) -> None:
    allegato.file.delete(save=False)
    allegato.delete()


def elimina_file_delle_visite(ids: list[int]) -> int:
    """Per la pulizia della conservazione: il CASCADE toglie le righe, i file vanno tolti a mano."""
    n = 0
    for allegato in AllegatoVisita.objects.filter(visita_id__in=ids):
        try:
            allegato.file.delete(save=False)
        except OSError:
            pass
        n += 1
    return n
