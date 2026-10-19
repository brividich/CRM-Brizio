"""Sigillo mensile dell'audit: catena di hash e export su SharePoint.

Ogni mese concluso riceve un sigillo (``core.AuditSigillo``):

    hash_righe   = SHA-256 delle righe del mese, una dopo l'altra in ordine di id,
                   ognuna in JSON canonico (chiavi ordinate, date in UTC)
    hash_sigillo = SHA-256 di «mese|righe|id_min|id_max|hash_righe|hash_precedente»

``hash_precedente`` è il sigillo del mese prima (il primo parte da 64 zeri): una
riga cambiata, aggiunta o tolta in un mese già sigillato non torna più con il suo
sigillo, e la catena si rompe da lì in avanti. ``verifica`` ricalcola tutto.

**Cosa copre**: le azioni esplicite (``log_action``: accessi, approvazioni,
impostazioni, permessi, revoche…), cioè ``azione`` non in ``auto_*``. Le righe
tecniche ``auto_insert/update/delete`` restano fuori: ``core.audit_archive`` le
riduce o le cancella per politica, e un sigillo su di esse si romperebbe per
manutenzione ordinaria. I mesi che l'archiviazione «business» ha tolto dal DB
(oltre 60 mesi) risultano «in archivio» e si verificano sui file d'archivio.

**Export**: per ogni mese sigillato due file nella cartella SharePoint configurata
(``core.sharepoint_upload``): ``audit-AAAA-MM.jsonl.gz`` con le righe e
``audit-AAAA-MM.sigillo.json`` con il sigillo. Senza cartella configurata il
sigillo nasce lo stesso e l'export resta da fare (``export_errore``).
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from datetime import timezone as dt_timezone

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

VERSIONE = 1
GENESI = "0" * 64
AUTO_AZIONI = ("auto_insert", "auto_update", "auto_delete")
CAMPI = ("id", "created_at", "legacy_user_id", "utente_display", "azione", "modulo",
         "dettaglio", "ip_address", "oggetto_tipo", "oggetto_id")


# ── Mesi ─────────────────────────────────────────────────────────────────────

def _mese(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _successivo(mese: str) -> str:
    y, m = (int(x) for x in mese.split("-"))
    return f"{y + (m // 12):04d}-{(m % 12) + 1:02d}"


def _limiti(mese: str) -> tuple[datetime, datetime]:
    y, m = (int(x) for x in mese.split("-"))
    inizio = timezone.make_aware(datetime(y, m, 1))
    ny, nm = (int(x) for x in _successivo(mese).split("-"))
    return inizio, timezone.make_aware(datetime(ny, nm, 1))


def mese_corrente(oggi: date | None = None) -> str:
    return _mese(oggi or timezone.localdate())


# ── Righe e hash ─────────────────────────────────────────────────────────────

def righe_del_mese(mese: str):
    from core.models import AuditLog

    inizio, fine = _limiti(mese)
    return (
        AuditLog.objects.filter(created_at__gte=inizio, created_at__lt=fine)
        .exclude(azione__in=AUTO_AZIONI)
        .order_by("id")
    )


def _canonica(row: dict) -> str:
    out = {}
    for k in CAMPI:
        v = row.get(k)
        if isinstance(v, datetime):
            v = (v if timezone.is_aware(v) else timezone.make_aware(v)).astimezone(dt_timezone.utc).isoformat()
        out[k] = v
    return json.dumps(out, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


@dataclass
class Impronta:
    righe: int
    id_min: int | None
    id_max: int | None
    hash_righe: str


def impronta(mese: str, *, scrivi=None) -> Impronta:
    """Hash delle righe del mese. ``scrivi(riga_json)`` riceve ogni riga (per l'export)."""
    h = hashlib.sha256()
    n, id_min, id_max = 0, None, None
    for row in righe_del_mese(mese).values(*CAMPI).iterator(chunk_size=2000):
        linea = _canonica(row)
        h.update(hashlib.sha256(linea.encode("utf-8")).hexdigest().encode("ascii"))
        h.update(b"\n")
        if scrivi:
            scrivi(linea)
        n += 1
        id_min = row["id"] if id_min is None else min(id_min, row["id"])
        id_max = row["id"] if id_max is None else max(id_max, row["id"])
    return Impronta(n, id_min, id_max, h.hexdigest())


def hash_sigillo(mese: str, imp: Impronta, precedente: str) -> str:
    seme = f"v{VERSIONE}|{mese}|{imp.righe}|{imp.id_min or ''}|{imp.id_max or ''}|{imp.hash_righe}|{precedente}"
    return hashlib.sha256(seme.encode("utf-8")).hexdigest()


# ── Sigillatura ──────────────────────────────────────────────────────────────

def _primo_mese() -> str | None:
    from core.models import AuditLog, AuditSigillo

    ultimo = AuditSigillo.objects.order_by("-mese").first()
    if ultimo:
        return _successivo(ultimo.mese)
    primo = AuditLog.objects.exclude(azione__in=AUTO_AZIONI).order_by("created_at").values_list("created_at", flat=True).first()
    if primo is None:
        return None
    return _mese(timezone.localtime(primo).date())


def sigilla_mancanti(oggi: date | None = None) -> list:
    """Sigilla, in ordine, tutti i mesi conclusi non ancora sigillati."""
    from core.models import AuditSigillo

    corrente = mese_corrente(oggi)
    creati = []
    mese = _primo_mese()
    while mese and mese < corrente:
        with transaction.atomic():
            precedente = AuditSigillo.objects.select_for_update().order_by("-mese").first()
            if precedente and precedente.mese >= mese:
                mese = _successivo(precedente.mese)
                continue
            imp = impronta(mese)
            prev_hash = precedente.hash_sigillo if precedente else GENESI
            creati.append(AuditSigillo.objects.create(
                mese=mese, righe=imp.righe, id_min=imp.id_min, id_max=imp.id_max,
                hash_righe=imp.hash_righe, hash_precedente=prev_hash,
                hash_sigillo=hash_sigillo(mese, imp, prev_hash), versione=VERSIONE,
            ))
        mese = _successivo(mese)
    return creati


# ── Verifica ─────────────────────────────────────────────────────────────────

def _mese_in_archivio(mese: str) -> bool:
    """Mesi che l'archiviazione «business» può aver tolto dal DB (oltre la soglia minima)."""
    from core import audit_archive

    limite = audit_archive.business_cutoff(audit_archive.BUSINESS_MIN_MONTHS)
    return _limiti(mese)[1] <= limite


def verifica(*, aggiorna: bool = True) -> list[dict]:
    """Ricalcola righe e catena. Un esito per sigillo: ok / rotto / in_archivio."""
    from core.models import AuditSigillo

    esiti = []
    atteso_prec = GENESI
    for s in AuditSigillo.objects.order_by("mese"):
        esito = {"mese": s.mese, "righe": s.righe}
        if s.hash_precedente != atteso_prec:
            esito.update(stato="rotto", motivo="catena interrotta: il sigillo precedente non coincide")
        elif hash_sigillo(s.mese, Impronta(s.righe, s.id_min, s.id_max, s.hash_righe), s.hash_precedente) != s.hash_sigillo:
            esito.update(stato="rotto", motivo="il sigillo è stato modificato")
        elif _mese_in_archivio(s.mese):
            esito.update(stato="in_archivio", motivo="righe fuori dal DB per conservazione: verificare sui file d'archivio")
        else:
            imp = impronta(s.mese)
            if (imp.righe, imp.hash_righe) != (s.righe, s.hash_righe):
                esito.update(stato="rotto", motivo=(
                    f"righe del mese aggiunte o tolte ({imp.righe} ora, {s.righe} al sigillo)" if imp.righe != s.righe
                    else "contenuto di almeno una riga del mese modificato"
                ))
            else:
                esito.update(stato="ok")
        esiti.append(esito)
        atteso_prec = s.hash_sigillo
        if aggiorna and esito["stato"] in ("ok", "rotto"):
            AuditSigillo.objects.filter(pk=s.pk).update(verificato_il=timezone.now(), verifica_ok=esito["stato"] == "ok")
    return esiti


# ── Export ───────────────────────────────────────────────────────────────────

def file_export(sigillo) -> tuple[bytes, bytes]:
    """(jsonl.gz delle righe, json del sigillo). Le righe vengono ri-hashate mentre si
    scrivono: se non coincidono con il sigillo l'export si ferma."""
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        imp = impronta(sigillo.mese, scrivi=lambda linea: gz.write((linea + "\n").encode("utf-8")))
    if (imp.righe, imp.hash_righe) != (sigillo.righe, sigillo.hash_righe):
        raise RuntimeError(f"Le righe di {sigillo.mese} non coincidono con il sigillo: export fermato.")
    meta = {
        "mese": sigillo.mese, "versione": sigillo.versione, "righe": sigillo.righe,
        "id_min": sigillo.id_min, "id_max": sigillo.id_max, "hash_righe": sigillo.hash_righe,
        "hash_precedente": sigillo.hash_precedente, "hash_sigillo": sigillo.hash_sigillo,
        "sha256_file_righe": hashlib.sha256(buf.getvalue()).hexdigest(),
        "creato_il": sigillo.creato_il.isoformat() if sigillo.creato_il else "",
        "copre": "azioni esplicite dell'audit (azione non auto_*)",
        "come_verificare": "SHA-256 di ogni riga (JSON canonico), concatenati con \\n -> hash_righe; "
                           "hash_sigillo = SHA-256('v1|mese|righe|id_min|id_max|hash_righe|hash_precedente').",
    }
    return buf.getvalue(), json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8")


def esporta_mancanti() -> dict:
    """Esporta su SharePoint i sigilli non ancora esportati, in ordine."""
    from core import sharepoint_upload as sp
    from core.models import AuditSigillo

    esito = {"esportati": 0, "errori": 0, "configurato": sp.configurato()}
    if not esito["configurato"]:
        AuditSigillo.objects.filter(export_ok=False).update(export_errore="Cartella SharePoint per l'export non configurata.")
        return esito
    for s in AuditSigillo.objects.filter(export_ok=False).order_by("mese"):
        try:
            righe, meta = file_export(s)
            sp.carica(f"audit-{s.mese}.jsonl.gz", righe)
            url = sp.carica(f"audit-{s.mese}.sigillo.json", meta)
            AuditSigillo.objects.filter(pk=s.pk).update(
                export_ok=True, export_il=timezone.now(), export_percorso=url[:500], export_errore="",
            )
            esito["esportati"] += 1
        except Exception as exc:  # noqa: BLE001 - si riprova al giro dopo
            logger.warning("Export sigillo %s non riuscito: %s", s.mese, exc)
            AuditSigillo.objects.filter(pk=s.pk).update(export_errore=str(exc)[:500])
            esito["errori"] += 1
            break  # in ordine: non si esporta un mese dopo uno mancante
    return esito


def ciclo_mensile() -> dict:
    """Sigilla i mesi conclusi, verifica la catena, esporta. Allerta se la catena è rotta."""
    creati = sigilla_mancanti()
    esiti = verifica()
    rotti = [e for e in esiti if e["stato"] == "rotto"]
    if rotti:
        logger.critical("Audit: catena dei sigilli ROTTA: %s", rotti)
        try:
            from django.core.mail import mail_admins

            mail_admins(
                "[AUDIT] Catena dei sigilli rotta",
                "La verifica dei sigilli dell'audit ha trovato mesi alterati:\n\n"
                + "\n".join(f"- {e['mese']}: {e['motivo']}" for e in rotti)
                + "\n\nControllare con: manage.py audit_sigilli --verifica",
            )
        except Exception:  # noqa: BLE001
            logger.exception("Audit: impossibile avvisare gli amministratori")
    return {"sigillati": [s.mese for s in creati], "rotti": len(rotti), "export": esporta_mancanti()}
