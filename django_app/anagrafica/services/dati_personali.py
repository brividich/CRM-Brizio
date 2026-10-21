"""«Scarica i miei dati»: copia dei dati personali del dipendente (GDPR art. 15 e 20).

Un archivio ZIP con ``dati.json`` (tutto, leggibile da un programma), un CSV per
sezione (apribile con Excel) e ``LEGGIMI.txt``. Stessa scelta del titolare di
«La mia scheda»: delle visite escono tipo, date e giudizio; referti, prescrizioni
e note del medico si chiedono all'ufficio HR o al medico competente.
La persona e' sempre quella collegata all'utente: nessun parametro sceglie di chi.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import zipfile
from datetime import date, datetime
from decimal import Decimal

from django.utils import timezone

logger = logging.getLogger(__name__)

LEGGIMI = """Copia dei tuoi dati personali dal portale NOVICROM HUB
Generata il {quando} per {nome}.

dati.json      tutte le sezioni in un unico file (formato aperto, leggibile da un programma)
<sezione>.csv  una tabella per sezione, apribile con Excel (separatore punto e virgola)

Sezioni: {sezioni}.

Non contiene: i file dei documenti (contratti, referti, attestati), le prescrizioni e
le note del medico competente. Per averli, o per correggere un dato, usa
«Segnala un dato errato» in La mia scheda oppure scrivi all'ufficio HR.
Il file contiene dati personali: conservalo con cura.
"""


def _valore(v):
    if isinstance(v, datetime):
        return timezone.localtime(v).isoformat() if timezone.is_aware(v) else v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    if hasattr(v, "name") and hasattr(v, "storage"):  # FieldFile
        return v.name or ""
    return v


def _riga(obj, escludi: tuple[str, ...] = ()) -> dict:
    return {
        f.name: _valore(getattr(obj, f.attname if f.is_relation else f.name))
        for f in obj._meta.concrete_fields
        if f.name not in escludi
    }


def _sezione(nome: str, funzione, sezioni: dict) -> None:
    """Una sezione che fallisce non blocca le altre: resta vuota e si annota."""
    try:
        sezioni[nome] = funzione()
    except Exception:
        logger.warning("Esportazione dati: sezione %s non disponibile", nome, exc_info=True)
        sezioni[nome] = [{"nota": "sezione non disponibile, chiedi all'ufficio HR"}]


def raccogli(request, lid: int) -> tuple[str, dict]:
    from anagrafica import models as m
    from anagrafica.models_formazione import TrainingEmployeeRecord
    from core import naming
    from core.legacy_anagrafica import fetch_anagrafica_rows

    persona = next(iter(fetch_anagrafica_rows(ids=[lid])), {}) or {}
    nome = naming.nome_completo(persona.get("nome"), persona.get("cognome"))
    user = request.user
    s: dict[str, list] = {}

    _sezione("persona", lambda: [{k: _valore(v) for k, v in persona.items()}], s)
    _sezione("account", lambda: [{
        "username": user.get_username(), "email": user.email, "nome": user.first_name, "cognome": user.last_name,
        "creato_il": _valore(user.date_joined), "ultimo_accesso": _valore(user.last_login),
    }], s)
    _sezione("anagrafica_civile", lambda: [
        _riga(o, ("id", "updated_by")) for o in m.DipendenteAnagraficaCivile.objects.filter(legacy_anagrafica_id=lid)], s)
    _sezione("figli_a_carico", lambda: [
        _riga(o, ("id", "anagrafica")) for o in m.FiglioACarico.objects.filter(anagrafica__legacy_anagrafica_id=lid)], s)
    _sezione("rapporto_di_lavoro", lambda: [
        _riga(o, ("id", "updated_by", "utente_id_pre_offboarding"))
        for o in m.DipendenteAnagraficaAziendale.objects.filter(legacy_anagrafica_id=lid)], s)
    _sezione("visite_mediche", lambda: [{
        "tipo": v.tipo.nome, "fatta_il": _valore(v.data_svolgimento), "scade_il": _valore(v.data_scadenza),
        "giudizio": v.esito, "nota_scadenza": v.scadenza_nota,
    } for v in m.VisitaMedica.objects.filter(legacy_anagrafica_id=lid).select_related("tipo").order_by("-data_svolgimento")], s)
    _sezione("formazione", lambda: [
        {**_riga(r, ("id",)), "corso": str(r.corso) if r.corso_id else ""}
        for r in TrainingEmployeeRecord.objects.filter(legacy_anagrafica_id=lid).select_related("corso")], s)
    _sezione("voci_cedolino", lambda: [
        _riga(o, ("id", "importazione", "updated_by"))
        for o in m.VoceRetributiva.objects.filter(legacy_anagrafica_id=lid).order_by("-data_competenza", "pay_item")], s)
    _sezione("saldi_ferie_permessi", lambda: [
        _riga(o, ("id", "importazione"))
        for o in m.SaldoCedolino.objects.filter(legacy_anagrafica_id=lid).order_by("-data_competenza")], s)
    _sezione("documenti", lambda: [{
        "tipo": d.get_tipo_display(), "nome_file": d.nome_originale, "caricato_il": _valore(d.created_at),
        "conservare_fino_al": _valore(d.retention_until),
    } for d in m.DocumentoDipendente.objects.filter(legacy_anagrafica_id=lid).order_by("-created_at")], s)
    _sezione("assenze", lambda: _assenze(lid), s)
    _sezione("dpi", lambda: _dpi(request), s)
    _sezione("richieste_di_rettifica", lambda: [
        _riga(o, ("id", "utente", "gestita_da"))
        for o in m.RichiestaRettifica.objects.filter(legacy_anagrafica_id=lid)], s)
    return nome, s


def _assenze(lid: int) -> list[dict]:
    from assenze.availability import assenze_per_anagrafica

    oggi = timezone.localdate()
    righe = assenze_per_anagrafica([lid], date(2000, 1, 1), date(oggi.year + 1, 12, 31)).get(lid, [])
    return [{k: _valore(v) for k, v in r.items()} for r in righe]


def _dpi(request) -> list[dict]:
    from dpi.models import RichiestaDPI
    from dpi.views import _own_richiesta_filter

    return [
        {**_riga(r, ("id",)), "categoria": str(r.categoria) if r.categoria_id else "",
         "tipo_dpi": str(r.tipo_dpi) if r.tipo_dpi_id else ""}
        for r in RichiestaDPI.objects.filter(_own_richiesta_filter(request)).select_related("categoria", "tipo_dpi")
    ]


def _csv(righe: list[dict]) -> str:
    chiavi: list[str] = []
    for r in righe:
        for k in r:
            if k not in chiavi:
                chiavi.append(k)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=chiavi or ["vuoto"], delimiter=";", extrasaction="ignore")
    w.writeheader()
    for r in righe:
        w.writerow({k: ("" if v is None else v) for k, v in r.items()})
    return "﻿" + buf.getvalue()  # BOM: Excel riconosce UTF-8


def archivio_zip(nome: str, sezioni: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("dati.json", json.dumps(sezioni, ensure_ascii=False, indent=2, default=str))
        for nome_sezione, righe in sezioni.items():
            z.writestr(f"{nome_sezione}.csv", _csv(righe))
        z.writestr("LEGGIMI.txt", LEGGIMI.format(
            quando=timezone.localtime().strftime("%d/%m/%Y %H:%M"), nome=nome or "te",
            sezioni=", ".join(sezioni)))
    return buf.getvalue()
