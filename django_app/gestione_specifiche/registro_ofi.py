"""Registro OFI centralizzato (PDCA, allineato MOD.174) — servizio (4.2).

Numerazione condivisa con l'OFI legacy (``RigaMOD133.ofi``/``AzioneOFI.ofi``) più
il registro: un unico spazio di numeri. Le voci nascono dalle righe MOD.133 con
impatto (idempotenti per riga) e restano agganciabili da altri moduli via
riferimento generico. Contatori PDCA e reminder per le voci in scadenza.
"""
from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

_OFI_BASE = 1000  # coerente con gestione_specifiche.ofi._OFI_BASE

# Etichette leggibili dei moduli d'origine (registro trasversale multi-modulo).
# Estendibile quando altri moduli inizieranno a generare OFI.
MODULO_LABELS = {
    "gestione_specifiche": "Specifiche / MOD.133",
}


def modulo_label(key: str) -> str:
    """Etichetta leggibile del modulo d'origine (fallback alla chiave)."""
    return MODULO_LABELS.get(key or "", key or "—")


def moduli_presenti() -> list[tuple[str, str]]:
    """[(chiave, etichetta)] dei moduli con almeno una voce, per il filtro."""
    from .models import RegistroOFI
    # .order_by() azzera l'ordinamento di Meta (-numero): su SQL Server un DISTINCT
    # con ORDER BY su una colonna non selezionata è errore (8127).
    chiavi = (RegistroOFI.objects
              .exclude(modulo_origine="")
              .order_by()
              .values_list("modulo_origine", flat=True).distinct())
    return [(k, modulo_label(k)) for k in sorted(set(chiavi))]


def prossimo_numero() -> int:
    """Prossimo numero di registro OFI, senza collisione con l'OFI legacy."""
    from .models import AzioneOFI, RegistroOFI, RigaMOD133
    massimo = max(
        RigaMOD133.objects.aggregate(m=models.Max("ofi"))["m"] or 0,
        AzioneOFI.objects.aggregate(m=models.Max("ofi"))["m"] or 0,
        RegistroOFI.objects.aggregate(m=models.Max("numero"))["m"] or 0,
    )
    return max(massimo, _OFI_BASE) + 1


def registro_da_riga(riga, *, numero: int | None = None, oggi=None):
    """Crea (o riusa) la voce di registro per una riga MOD.133 (idempotente per riga)."""
    from django.contrib.contenttypes.models import ContentType
    from .models import RegistroOFI, RigaMOD133

    oggi = oggi or timezone.localdate()
    ct = ContentType.objects.get_for_model(RigaMOD133)
    esistente = RegistroOFI.objects.filter(content_type=ct, object_id=riga.id).first()
    if esistente is not None:
        return esistente

    numero = numero if numero is not None else (riga.ofi or prossimo_numero())
    spec = riga.mod133.specifica
    return RegistroOFI.objects.create(
        numero=numero, data_apertura=oggi, tipo=RegistroOFI.TIPO_OFI,
        norma_en9100=True, ref=spec.codice,
        processo=riga.tag_processo or "",
        opportunita=(riga.descrizione_impatto or riga.descrizione_modifiche or "")[:5000],
        modulo_origine="gestione_specifiche",
        content_type=ct, object_id=riga.id,
    )


def conta_pdca(qs=None) -> dict:
    """Contatori P/D/C/A + chiuso + totale del registro (per l'header della lista)."""
    from .models import RegistroOFI
    if qs is None:
        qs = RegistroOFI.objects.all()
    out = {"plan": 0, "do": 0, "check": 0, "act": 0, "chiuso": 0, "tot": 0}
    mapping = {
        RegistroOFI.FASE_PLAN: "plan", RegistroOFI.FASE_DO: "do",
        RegistroOFI.FASE_CHECK: "check", RegistroOFI.FASE_ACT: "act",
        RegistroOFI.FASE_CHIUSO: "chiuso",
    }
    # .order_by() azzera l'ordinamento di Meta (-numero): su SQL Server una GROUP BY
    # (values+annotate) con ORDER BY su colonna non raggruppata è errore (8127).
    for row in qs.order_by().values("fase").annotate(n=models.Count("id")):
        key = mapping.get(row["fase"])
        if key:
            out[key] = row["n"]
        out["tot"] += row["n"]
    return out


def conta_pdca_cumulativo(qs=None) -> dict:
    """Contatori CUMULATIVI P/D/C/A + % completamento, fedeli al MOD.174.

    Nell'Excel P/D/C/A sono 4 caselle "X" cumulative (spuntate in ordine) e la
    riga 2 conta per colonna: P = voci arrivate almeno a PLAN (tutte), D = arrivate
    almeno a DO, ecc.; il KPI è ``A/P`` (>=90% = ok). Qui la fase è un enum
    ordinato PLAN<DO<CHECK<ACT(≤CHIUSO), quindi il "raggiunto almeno" si deriva.
    Ritorna ``{p, d, c, a, tot, pct, over90}``.
    """
    from .models import RegistroOFI
    if qs is None:
        qs = RegistroOFI.objects.all()
    per_fase: dict[str, int] = {}
    # .order_by() azzera Meta.ordering (-numero): su SQL Server la GROUP BY con
    # ORDER BY su colonna non raggruppata è errore 8127 (vedi conta_pdca).
    for row in qs.order_by().values("fase").annotate(n=models.Count("id")):
        per_fase[row["fase"]] = row["n"]
    F = RegistroOFI
    tot = sum(per_fase.values())
    d = (per_fase.get(F.FASE_DO, 0) + per_fase.get(F.FASE_CHECK, 0)
         + per_fase.get(F.FASE_ACT, 0) + per_fase.get(F.FASE_CHIUSO, 0))
    c = (per_fase.get(F.FASE_CHECK, 0) + per_fase.get(F.FASE_ACT, 0)
         + per_fase.get(F.FASE_CHIUSO, 0))
    a = per_fase.get(F.FASE_ACT, 0) + per_fase.get(F.FASE_CHIUSO, 0)
    pct = round(a / tot * 100) if tot else 0
    return {"p": tot, "d": d, "c": c, "a": a, "tot": tot, "pct": pct, "over90": pct >= 90}


def voci_da_sollecitare(oggi=None, *, giorni: int = 0):
    """Voci aperte con reminder attivo e scadenza entro ``giorni`` (default: già
    scadute), non ancora sollecitate. Ordinate per scadenza."""
    from .models import RegistroOFI
    oggi = oggi or timezone.localdate()
    limite = oggi + timedelta(days=giorni)
    return list(
        RegistroOFI.objects
        .filter(reminder_attivo=True, reminder_inviato=False,
                data_richiesta__isnull=False, data_richiesta__lte=limite,
                data_chiusura__isnull=True)
        .exclude(fase=RegistroOFI.FASE_CHIUSO)
        .order_by("data_richiesta", "numero")
    )


def _destinatari_reminder() -> list[str]:
    """Destinatari del reminder OFI (best-effort, fail-safe)."""
    cfg = getattr(settings, "GESTIONE_SPECIFICHE", {}) or {}
    dest = cfg.get("OFI_REMINDER_EMAILS") or []
    if isinstance(dest, str):
        dest = [e.strip() for e in dest.replace(";", ",").split(",") if e.strip()]
    return list(dest)


def invia_reminder_ofi(*, oggi=None, giorni: int = 0, dry_run: bool = False) -> dict:
    """Solleciti per le voci OFI in scadenza/scadute. Best-effort: l'email non
    deve mai bloccare (fail-safe); marca ``reminder_inviato`` sulle voci trattate.
    Ritorna ``{candidate, inviati, dry_run}``.
    """
    voci = voci_da_sollecitare(oggi=oggi, giorni=giorni)
    if dry_run:
        return {"candidate": len(voci), "inviati": 0, "dry_run": True}

    destinatari = _destinatari_reminder()
    inviati = 0
    for v in voci:
        if destinatari:
            try:
                from core.email_utils import send_hub_mail
                send_hub_mail(
                    subject=f"[HUB] Reminder OFI {v.numero} — {v.processo or 'MOD.174'}",
                    to=destinatari,
                    intro=(f"L'OFI {v.numero} ({v.get_tipo_display()}) è in scadenza o scaduto "
                           f"(richiesta chiusura entro il {v.data_richiesta:%d/%m/%Y})."),
                    facts=[("Processo", v.processo or "—"), ("Fase", v.get_fase_display()),
                           ("Priorità", v.get_priorita_display()),
                           ("Owner", v.owner_processo or v.proprietario or "—")],
                )
            except Exception:  # pragma: no cover - il reminder non deve bloccare
                pass
        v.reminder_inviato = True
        v.save(update_fields=["reminder_inviato", "updated_at"])
        inviati += 1
    return {"candidate": len(voci), "inviati": inviati, "dry_run": False}
