"""Spazio e manutenzione del Registro accessi: quanto pesano database e archivio, e le operazioni.

Le letture qui sono veloci (statistiche del database, elenco dei file dell'archivio); le
operazioni (backup, copia, conservazione, catalogo) girano nel qcluster con
:func:`esegui_operazione` e restano in :class:`~registro_log.models.OperazioneManutenzione`.
"""
from __future__ import annotations

import logging
import os
from datetime import timedelta

from django.conf import settings
from django.db import connections
from django.utils import timezone

from . import archivio
from .router import alias

logger = logging.getLogger(__name__)

MB = 1024 * 1024
MESI_MINIMI_CATALOGO = 1
GIORNI_MASSIMI_RICATALOGO = 31


def nome_database() -> str:
    return str(settings.DATABASES.get(alias(), {}).get("NAME", ""))


def database() -> dict:
    """Dimensione del database del registro e delle sue tabelle. Mai un'eccezione: in caso d'errore lo dice."""
    from .models import EventoRegistro

    info = {"nome": nome_database(), "a_parte": alias() != "default", "motore": "", "dati_mb": None, "log_mb": None,
            "tabelle": [], "errore": "", "primo": None, "ultimo": None, "eventi": 0}
    conn = connections[alias()]
    info["motore"] = conn.vendor
    try:
        with conn.cursor() as cur:
            if conn.vendor == "microsoft":
                cur.execute("SELECT type_desc, SUM(CAST(size AS bigint)) * 8 / 1024.0 FROM sys.database_files GROUP BY type_desc")
                for tipo, mb in cur.fetchall():
                    if tipo == "ROWS":
                        info["dati_mb"] = round(float(mb), 1)
                    elif tipo == "LOG":
                        info["log_mb"] = round(float(mb), 1)
                cur.execute(
                    "SELECT o.name, SUM(CASE WHEN s.index_id IN (0, 1) THEN s.row_count ELSE 0 END), "
                    "SUM(s.reserved_page_count) * 8 / 1024.0 FROM sys.dm_db_partition_stats s "
                    "JOIN sys.objects o ON o.object_id = s.object_id WHERE o.name LIKE 'registro\\_log\\_%' ESCAPE '\\' "
                    "GROUP BY o.name ORDER BY 3 DESC")
                info["tabelle"] = [{"nome": n, "righe": int(r or 0), "mb": round(float(m or 0), 1)} for n, r, m in cur.fetchall()]
            elif conn.vendor == "sqlite":
                percorso = str(conn.settings_dict.get("NAME") or "")
                if percorso and os.path.exists(percorso):
                    info["dati_mb"] = round(os.path.getsize(percorso) / MB, 1)
                for modello in _modelli():
                    info["tabelle"].append({"nome": modello._meta.db_table, "righe": modello.objects.count(), "mb": None})
    except Exception as exc:  # noqa: BLE001 - permessi o motore diverso: la pagina resta in piedi
        logger.warning("Registro accessi: dimensione del database non letta: %s", exc)
        info["errore"] = f"Dimensioni non lette: {type(exc).__name__}: {str(exc)[:200]}"
    try:
        info["eventi"] = EventoRegistro.objects.count()
        primo = EventoRegistro.objects.order_by("quando").values_list("quando", flat=True).first()
        ultimo = EventoRegistro.objects.order_by("-quando").values_list("quando", flat=True).first()
        info["primo"], info["ultimo"] = primo, ultimo
    except Exception as exc:  # noqa: BLE001
        info["errore"] = info["errore"] or f"Catalogo non letto: {exc}"
    if info["dati_mb"] is not None:
        info["totale_mb"] = round((info["dati_mb"] or 0) + (info["log_mb"] or 0), 1)
    return info


def _modelli():
    from django.apps import apps

    return list(apps.get_app_config("registro_log").get_models())


def ultimo_backup():
    """Ultimo backup completo che comprende il database del registro (motore di backup del portale)."""
    nome = nome_database()
    if not nome or alias() == "default":
        return None
    try:
        from monitoring.models import BackupRun

        return BackupRun.objects.filter(kind="full", database__icontains=nome).order_by("-started_at").first()
    except Exception:  # noqa: BLE001
        return None


def archivio_info() -> dict:
    """Dimensione dell'archivio, per mese, spazio libero e giorni da copiare o da eliminare."""
    from .models import Impostazioni, SigilloGiorno

    base = archivio.cartella()
    info = {"cartella": str(base), "esiste": base.exists(), "totale_mb": 0.0, "file": 0, "mesi": [], "oggi_mb": None,
            "libero_mb": archivio.spazio_libero_mb(base), "errore": ""}
    if info["esiste"]:
        mesi: dict[str, dict] = {}
        oggi = archivio.percorso(timezone.localdate(), base)
        try:
            for p in base.glob("*/*/registro-*"):
                dim = p.stat().st_size
                chiave = f"{p.parent.parent.name}/{p.parent.name}"
                m = mesi.setdefault(chiave, {"mese": chiave, "file": 0, "mb": 0.0})
                m["file"] += 1
                m["mb"] += dim / MB
                info["file"] += 1
                info["totale_mb"] += dim / MB
                if p == oggi:
                    info["oggi_mb"] = round(dim / MB, 1)
        except OSError as exc:
            info["errore"] = f"Cartella non leggibile: {exc}"
        info["mesi"] = [dict(m, mb=round(m["mb"], 1)) for m in sorted(mesi.values(), key=lambda x: x["mese"], reverse=True)]
        info["totale_mb"] = round(info["totale_mb"], 1)
    imp = Impostazioni.corrente()
    mesi_cons = max(6, int(imp.conservazione_mesi or 12))
    limite = timezone.localdate() - timedelta(days=round(mesi_cons * 30.44))
    info.update({
        "conservazione_mesi": mesi_cons,
        "oltre_conservazione": SigilloGiorno.objects.filter(giorno__lt=limite, eliminato_il__isnull=True).count(),
        "da_copiare": SigilloGiorno.objects.filter(copia_il__isnull=True, eliminato_il__isnull=True).count(),
        "copia_configurata": bool((imp.copia_cartella or "").strip() or imp.copia_sharepoint),
        "ultima_copia": SigilloGiorno.objects.filter(copia_il__isnull=False).order_by("-copia_il")
        .values_list("copia_il", flat=True).first(),
        "giorni_sigillati": SigilloGiorno.objects.filter(eliminato_il__isnull=True).count(),
    })
    return info


# ── Operazioni ─────────────────────────────────────────────────────────────


def avvia(tipo: str, utente: str, parametri: dict | None = None):
    """Registra l'operazione e la mette in coda al qcluster. Una sola alla volta per tipo."""
    from .models import OperazioneManutenzione

    if OperazioneManutenzione.objects.filter(tipo=tipo, stato__in=("attesa", "in_corso"),
                                             avviata_il__gte=timezone.now() - timedelta(hours=6)).exists():
        return None
    op = OperazioneManutenzione.objects.create(tipo=tipo, parametri=parametri or {}, avviata_da=utente[:150])
    try:
        from django_q.tasks import async_task

        async_task("registro_log.tasks.run_manutenzione", op.pk, task_name=f"registro_log_{tipo}_{op.pk}")
    except Exception as exc:  # noqa: BLE001 - senza coda la si esegue qui
        logger.warning("Registro accessi: coda non disponibile, operazione %s eseguita subito: %s", op.pk, exc)
        esegui_operazione(op.pk)
    return op


def esegui_operazione(op_id: int) -> dict:
    from .models import OperazioneManutenzione

    op = OperazioneManutenzione.objects.filter(pk=op_id).first()
    if op is None or op.stato not in ("attesa", "in_corso"):
        return {}
    OperazioneManutenzione.objects.filter(pk=op.pk).update(stato="in_corso")
    try:
        esito, dettaglio, ok = _esegui(op.tipo, op.parametri or {})
    except Exception as exc:  # noqa: BLE001 - l'errore va nel registro delle operazioni
        logger.exception("Registro accessi: operazione %s non riuscita", op.pk)
        esito, dettaglio, ok = f"{type(exc).__name__}: {exc}", {}, False
    OperazioneManutenzione.objects.filter(pk=op.pk).update(
        stato="ok" if ok else "errore", esito=str(esito)[:1000], dettaglio=dettaglio, finita_il=timezone.now())
    return {"ok": ok, "esito": esito}


def _esegui(tipo: str, parametri: dict) -> tuple[str, dict, bool]:
    if tipo == "backup_db":
        return _backup_db()
    if tipo == "copia":
        r = archivio.copia_mancanti()
        if not r.get("configurato"):
            return "Seconda copia non configurata (Impostazioni: cartella di rete o SharePoint).", r, False
        return f"Copiati {r['copiati']} giorni" + (f", {r['errori']} non riusciti (si riprova al prossimo giro)" if r["errori"] else "")\
            + ".", r, not r["errori"]
    if tipo == "conservazione":
        r = archivio.applica_conservazione()
        return (f"Eliminati i file di {r['giorni_eliminati']} giorni e {r['eventi_eliminati']} voci del catalogo "
                f"prima del {r['limite']} (i sigilli restano)."), r, True
    if tipo == "alleggerisci":
        mesi = max(MESI_MINIMI_CATALOGO, int(parametri.get("mesi") or 0))
        return _alleggerisci(mesi)
    if tipo == "ricataloga":
        giorni = min(GIORNI_MASSIMI_RICATALOGO, max(1, int(parametri.get("giorni") or 1)))
        return _ricataloga(giorni)
    return f"Operazione sconosciuta: {tipo}", {}, False


def _backup_db() -> tuple[str, dict, bool]:
    nome = nome_database()
    if alias() == "default" or not nome:
        return ("Il registro sta nel database del portale: è già nel backup del portale. "
                "Il backup a parte serve con REGISTRO_LOG_DB_NAME."), {}, False
    from core.backup_engine import engine
    from core.backup_engine.config import load_config

    cfg = load_config()
    res = engine.finish(cfg, engine.run_full(cfg, databases=[nome]))
    dettaglio = {"set": res.set_id, "stato": res.status, "byte": res.bytes, "verifica": res.verify_status,
                 "destinazione": str(cfg.env_root)}
    if res.status == "failed":
        return f"Backup non riuscito: {res.error}", dettaglio, False
    mb = round((res.bytes or 0) / MB, 1)
    return f"Backup {res.set_id} salvato e verificato ({mb} MB) in {cfg.env_root}.", dettaglio, True


def _alleggerisci(mesi: int) -> tuple[str, dict, bool]:
    """Toglie dal catalogo le voci più vecchie di ``mesi``: restano nell'archivio sigillato."""
    from .models import EventoRegistro

    limite = timezone.now() - timedelta(days=round(mesi * 30.44))
    righe = 0
    while True:  # a blocchi: una DELETE enorme terrebbe bloccata la tabella
        ids = list(EventoRegistro.objects.filter(quando__lt=limite).values_list("pk", flat=True)[:5000])
        if not ids:
            break
        righe += EventoRegistro.objects.filter(pk__in=ids).delete()[0]
    return (f"Tolte dal catalogo {righe} voci più vecchie di {mesi} mesi (prima del {timezone.localtime(limite):%d/%m/%Y}). "
            "Restano nell'archivio sigillato."), {"mesi": mesi, "righe": righe}, True


def _ricataloga(giorni: int) -> tuple[str, dict, bool]:
    from .raccoglitore import Raccoglitore

    oggi = timezone.localdate()
    elenco = [oggi - timedelta(days=i) for i in range(giorni)]
    r = Raccoglitore()
    r.carica()
    voci = r.ricataloga_giorni(elenco)
    return f"Catalogo rifatto per {giorni} giorni dall'archivio: {voci} voci.", {"giorni": giorni, "voci": voci}, True
