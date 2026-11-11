"""Catalogo delle specifiche allineato alla cartella della share (sola lettura).

Ogni 15 minuti :func:`esegui` elenca i PDF sotto ``GESTIONE_SPECIFICHE_SHARE_ROOTS``
(escluse le cartelle ``_SUPERATO``) e, se l'impronta (percorso, dimensione, data) è
cambiata, allinea il database:

- PDF già collegato a una specifica (``percorso_esterno``): niente da fare;
- stesso codice e stessa revisione di una specifica esistente non collegata (o col file
  sparito): la collega al file (riallineamento);
- stesso codice con revisione nuova: crea la nuova revisione (``revisione_precedente``
  = l'ultima) in **bozza**, da portare in flow-down come quelle inserite a mano;
- codice nuovo: crea la specifica in **bozza**, cliente = cartella del cliente.

Il primo giro (``gs_sync_cartelle_base`` vuoto) fotografa l'archivio: i PDF già presenti
diventano specifiche **in validità** (la più recente per codice; le precedenti superate),
senza avvisi, come l'import dello storico. Dal giro dopo i file nuovi arrivano in bozza e
chi prende in carico le specifiche riceve l'avviso.

La share non viene mai scritta. Fail-safe: un errore su un file non ferma il giro.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, time

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import constants as C

logger = logging.getLogger(__name__)

FLAG = "gs_sync_cartelle_attivo"          # "0" spegne; vuoto = acceso
BASE = "gs_sync_cartelle_base"            # data del primo giro (fotografia dell'archivio)
IMPRONTA = "gs_sync_cartelle_impronta"
ESITO = "gs_sync_cartelle_esito"
ULTIMO = "gs_sync_cartelle_ultimo"
TRIGGER = "sync_cartella"
MAX_AVVISI_SINGOLI = 10
# MOD.133 compilati e simili salvati accanto alla specifica: non sono specifiche.
_NON_SPECIFICA = re.compile(r"(?i)\bmod[\s._-]*13[34]\b")
_REV_FINE = re.compile(r"(?i)[\s._-]*REV\.?\s*([A-Za-z0-9][A-Za-z0-9\-]*)\s*$")


@dataclass
class FilePdf:
    path: str
    rel: str          # relativo alla radice, separatore «\»
    cartella: str     # cartella di primo livello ('' se il file sta nella radice)
    nome: str
    codice: str
    revisione: str
    mtime: float


def attivo() -> bool:
    from core.models import SiteConfig

    return str(SiteConfig.get(FLAG, "") or "").strip().lower() not in {"0", "false", "off", "no"}


def _esclusi() -> set[str]:
    return {str(s).strip().lower() for s in getattr(settings, "GESTIONE_SPECIFICHE_SHARE_EXCLUDE", []) if str(s).strip()}


def _radici() -> list[str]:
    from .share_link import radici_consentite

    return radici_consentite()


def chiave_rel(path: str) -> str:
    """Percorso relativo alla radice, minuscolo: confronta i percorsi anche se la radice è scritta diversamente."""
    p = str(path or "").replace("/", "\\")
    pl = p.lower()
    for root in _radici():
        r = str(root).replace("/", "\\").rstrip("\\").lower()
        if pl.startswith(r + "\\"):
            return pl[len(r) + 1:]
    # Radice scritta in altro modo (nome server, lettera di unità): ultime due parti.
    parti = [s for s in pl.split("\\") if s]
    return "\\".join(parti[-2:]) if len(parti) >= 2 else pl


def codice_e_revisione(nome_file: str) -> tuple[str, str]:
    """``15500 REV.0.pdf`` → (``15500``, ``0``); senza «REV» la revisione è vuota."""
    base = re.sub(r"(?i)\.pdf$", "", str(nome_file or "")).strip()
    m = _REV_FINE.search(base)
    if not m:
        return base.strip(" ._-"), ""
    return base[: m.start()].strip(" ._-") or base, m.group(1).upper()


def norm_codice(codice: str) -> str:
    return re.sub(r"[\s._-]+", "", str(codice or "").upper())


def ordine_revisione(rev: str):
    """Chiave d'ordine: numeri come numeri, lettere come lettere (A < B < … < Z < AA)."""
    r = str(rev or "").strip().upper()
    if not r:
        return (-1, 0, "")
    if r.isdigit():
        return (1, int(r), "")
    if r.isalpha():
        n = 0
        for ch in r:
            n = n * 26 + (ord(ch) - 64)
        return (1, n, "")
    m = re.match(r"^(\d+)", r)
    return (1, int(m.group(1)), r) if m else (0, 0, r)


def elenca_pdf() -> list[FilePdf]:
    esclusi = _esclusi()
    out: list[FilePdf] = []
    for root in _radici():
        if not os.path.isdir(root):
            continue
        root_abs = os.path.abspath(root)
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d.lower() not in esclusi and not d.startswith("~")]
            for fn in filenames:
                if not fn.lower().endswith(".pdf") or fn.startswith("~$"):
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, root_abs).replace("/", "\\")
                segs = rel.split("\\")
                try:
                    mtime = os.stat(full).st_mtime
                except OSError:
                    continue
                codice, rev = codice_e_revisione(fn)
                out.append(FilePdf(full, rel, segs[0] if len(segs) > 1 else "", fn, codice, rev, mtime))
    return out


def impronta(files: list[FilePdf]) -> str:
    h = hashlib.sha1(usedforsecurity=False)
    for f in sorted(files, key=lambda x: x.rel.lower()):
        h.update(f"{f.rel.lower()}|{int(f.mtime)};".encode("utf-8", "replace"))
    return h.hexdigest()


def cliente_per_cartella(cartella: str) -> str:
    """Il cliente collegato alla cartella in «Mappatura cliente-cartella», se c'è; altrimenti il nome della cartella."""
    from .models import ClienteCartellaShare

    if not cartella:
        return ""
    for m in ClienteCartellaShare.objects.filter(attivo=True):
        if (m.cartella or "").replace("/", "\\").split("\\")[0].strip().lower() == cartella.lower():
            return m.cliente
    return cartella


def _crea(f: FilePdf, *, stato: str, precedente=None, nota: str) -> object:
    from .models import EventoSpecifica, Specifica

    campi = {}
    if precedente is not None:
        campi = {k: getattr(precedente, k) for k in ("titolo", "tipo", "fonte", "cliente", "tag", "commessa_ref", "famiglia_ref")}
    spec = Specifica.objects.create(
        codice=(precedente.codice if precedente is not None else f.codice)[:100],
        revisione=f.revisione[:30],
        titolo=campi.pop("titolo", None) or f.codice[:300] or f.nome[:300],
        cliente=campi.pop("cliente", None) or cliente_per_cartella(f.cartella)[:200],
        percorso_esterno=f.path[:500],
        revisione_precedente=precedente,
        note=nota,
        **campi,
    )
    aggiorna = {}
    if stato != C.STATO_BOZZA:
        aggiorna["stato"] = stato
    if stato == C.STATO_IN_VALIDITA:
        giorno = datetime.fromtimestamp(f.mtime).date()
        aggiorna["data_inserimento"] = timezone.make_aware(datetime.combine(giorno, time(12, 0)))
    if aggiorna:
        Specifica.objects.filter(pk=spec.pk).update(**aggiorna)
        spec = Specifica.objects.get(pk=spec.pk)  # lo stato è protetto (FSM): si rilegge, non si riassegna
    EventoSpecifica.objects.create(
        specifica=spec, stato_da="", stato_a=spec.stato, trigger=TRIGGER,
        payload={"snapshot": spec.snapshot_metadati(), "file": f.rel, "sync_cartella": True},
    )
    return spec


def allinea(files: list[FilePdf], *, prima_volta: bool, apply: bool = True) -> dict:
    """Confronta i PDF con il database e crea/collega le specifiche. Ritorna l'esito del giro."""
    from .models import EventoSpecifica, Specifica

    esito = {"pdf": len(files), "collegati": 0, "riallineati": 0, "nuove": 0, "nuove_revisioni": 0,
             "esclusi": [], "create": []}
    specs = list(Specifica.objects.only("pk", "codice", "revisione", "percorso_esterno", "stato", "cliente", "titolo",
                                        "tipo", "fonte", "tag", "commessa_ref", "famiglia_ref", "data_inserimento"))
    per_path = {chiave_rel(s.percorso_esterno): s for s in specs if s.percorso_esterno}
    per_codice: dict[str, list] = {}
    for s in specs:
        per_codice.setdefault(norm_codice(s.codice), []).append(s)

    # Prima i file più vecchi per revisione: le catene di revisioni si creano in ordine.
    candidati = []
    for f in files:
        if chiave_rel(f.path) in per_path:
            esito["collegati"] += 1
            continue
        if _NON_SPECIFICA.search(f.nome):
            esito["esclusi"].append({"file": f.rel, "motivo": "MOD.133/MOD.134 compilato: non è una specifica"})
            continue
        if not f.codice:
            esito["esclusi"].append({"file": f.rel, "motivo": "nome senza codice"})
            continue
        candidati.append(f)
    candidati.sort(key=lambda f: (norm_codice(f.codice), ordine_revisione(f.revisione)))

    ultimi_per_codice: dict[str, FilePdf] = {}
    for f in candidati:
        ultimi_per_codice[norm_codice(f.codice)] = f  # l'ultimo in ordine = revisione più alta

    for f in candidati:
        k = norm_codice(f.codice)
        esistenti = per_codice.get(k, [])
        stessa = next((s for s in esistenti if (s.revisione or "").strip().upper() == f.revisione), None)
        try:
            if stessa is not None:
                vecchio = stessa.percorso_esterno
                if vecchio and os.path.exists(vecchio):
                    esito["esclusi"].append({"file": f.rel, "motivo": f"{stessa.codice} rev.{stessa.revisione or '—'} è già collegata a un altro file"})
                    continue
                if apply:
                    Specifica.objects.filter(pk=stessa.pk).update(percorso_esterno=f.path[:500])
                    EventoSpecifica.objects.create(
                        specifica=stessa, stato_da=stessa.stato, stato_a=stessa.stato, trigger=TRIGGER,
                        payload={"collegato": f.rel, "prima": vecchio},
                    )
                stessa.percorso_esterno = f.path
                per_path[chiave_rel(f.path)] = stessa
                esito["riallineati"] += 1
                continue
            precedente = max(esistenti, key=lambda s: (ordine_revisione(s.revisione), s.data_inserimento or timezone.now())) if esistenti else None
            if precedente is not None and ordine_revisione(f.revisione) <= ordine_revisione(precedente.revisione):
                esito["esclusi"].append({"file": f.rel, "motivo": f"revisione {f.revisione or '—'} non più recente di {precedente.revisione or '—'} già in catalogo"})
                continue
            if prima_volta:
                stato = C.STATO_IN_VALIDITA if ultimi_per_codice.get(k) is f else C.STATO_SUPERATO
                nota = "Creata dalla prima lettura della cartella delle specifiche."
            else:
                stato = C.STATO_BOZZA
                nota = "Creata dalla cartella delle specifiche: da portare in flow-down."
            if not apply:
                esito["nuove_revisioni" if precedente else "nuove"] += 1
                continue
            with transaction.atomic():
                spec = _crea(f, stato=stato, precedente=precedente, nota=nota)
                if prima_volta and stato == C.STATO_IN_VALIDITA and precedente is not None and precedente.stato in C.STATI_ATTIVI:
                    # Fotografia dell'archivio: la revisione della cartella sostituisce quella vecchia in catalogo.
                    Specifica.objects.filter(pk=precedente.pk).update(stato=C.STATO_SUPERATO)
                    EventoSpecifica.objects.create(
                        specifica=precedente, stato_da=precedente.stato, stato_a=C.STATO_SUPERATO, trigger=TRIGGER,
                        payload={"superata_da": spec.pk, "file": f.rel},
                    )
                    per_codice[k] = [x for x in per_codice.get(k, []) if x.pk != precedente.pk] + [Specifica.objects.get(pk=precedente.pk)]
            per_codice.setdefault(k, []).append(spec)
            per_path[chiave_rel(f.path)] = spec
            esito["nuove_revisioni" if precedente else "nuove"] += 1
            if stato == C.STATO_BOZZA:
                esito["create"].append(spec.pk)
        except Exception:
            logger.exception("Sync cartella specifiche: file non elaborato %s", f.rel)
            esito["esclusi"].append({"file": f.rel, "motivo": "errore durante l'elaborazione"})
    return esito


def _avvisa(create: list[int]) -> None:
    """Avviso a chi prende in carico: uno per specifica se sono poche, altrimenti un riepilogo."""
    from .models import Specifica
    from .notifiche_gs import notifica_nuova_specifica

    if not create:
        return
    if len(create) <= MAX_AVVISI_SINGOLI:
        for spec in Specifica.objects.filter(pk__in=create):
            try:
                notifica_nuova_specifica(spec)
            except Exception:
                logger.exception("Sync cartella specifiche: avviso non inviato per %s", spec.pk)
        return
    try:
        from .notifiche_gs import notifica_riepilogo_nuove

        notifica_riepilogo_nuove(len(create))
    except Exception:
        logger.exception("Sync cartella specifiche: riepilogo non inviato")


def esegui(*, forza: bool = False) -> dict:
    """Giro di sincronizzazione (schedule ogni 15 minuti e pulsante «Sincronizza ora»). Non solleva mai."""
    from core.models import SiteConfig

    risultato: dict = {"ok": True, "saltato": False}
    try:
        if not forza and not attivo():
            return {**risultato, "saltato": True, "motivo": "sincronizzazione spenta"}
        radici = _radici()
        if not radici or not any(os.path.isdir(r) for r in radici):
            return {**risultato, "saltato": True, "motivo": "cartella delle specifiche non raggiungibile"}
        files = elenca_pdf()
        nuova = impronta(files)
        SiteConfig.set(ULTIMO, timezone.localtime().isoformat(timespec="seconds"), "Specifiche: ultimo controllo della cartella.")
        if not forza and nuova == str(SiteConfig.get(IMPRONTA, "") or ""):
            return {**risultato, "invariata": True, "pdf": len(files)}
        prima_volta = not str(SiteConfig.get(BASE, "") or "").strip()
        esito = allinea(files, prima_volta=prima_volta)
        if prima_volta:
            SiteConfig.set(BASE, timezone.localtime().isoformat(timespec="seconds"), "Specifiche: data della prima lettura della cartella.")
        else:
            _avvisa(esito["create"])
        SiteConfig.set(IMPRONTA, nuova, "Specifiche: impronta della cartella all'ultimo giro.")
        salva = {k: v for k, v in esito.items() if k != "create"}
        salva["esclusi"] = salva["esclusi"][:100]
        salva["at"] = timezone.localtime().isoformat(timespec="seconds")
        salva["prima_volta"] = prima_volta
        SiteConfig.set(ESITO, json.dumps(salva), "Specifiche: esito dell'ultima sincronizzazione con la cartella.")
        return {**risultato, **salva}
    except Exception as exc:
        logger.exception("Sync cartella specifiche fallita")
        return {**risultato, "ok": False, "errore": str(exc)}


def stato() -> dict:
    """Per «Amministrazione»: interruttore, cartella, ultimo controllo, esito e file lasciati fuori."""
    from core.models import SiteConfig

    try:
        esito = json.loads(SiteConfig.get(ESITO, "") or "{}")
    except (ValueError, TypeError):
        esito = {}
    radici = _radici()
    try:
        raggiungibile = bool(radici) and any(os.path.isdir(r) for r in radici)
    except OSError:
        raggiungibile = False
    ultimo = str(SiteConfig.get(ULTIMO, "") or "")
    try:
        ultimo_dt = timezone.localtime(datetime.fromisoformat(ultimo)) if ultimo else None
    except ValueError:
        ultimo_dt = None
    def _dt(raw):
        try:
            return timezone.localtime(datetime.fromisoformat(raw)) if raw else None
        except (ValueError, TypeError):
            return None

    return {
        "attivo": attivo(), "raggiungibile": raggiungibile, "radici": radici,
        "ultimo": ultimo_dt, "esito": esito, "esito_at": _dt(esito.get("at")),
        "base": _dt(str(SiteConfig.get(BASE, "") or "")),
    }
