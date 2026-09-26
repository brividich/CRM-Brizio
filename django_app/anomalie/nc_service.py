"""Non conformita' per OP (ISO 9001 §10.2): ciclo di vita, stato calcolato, azioni.

Regole concordate:

- **Una NC per OP**, creata alla prima anomalia dell'OP. Finche' e' aperta, le nuove
  anomalie dell'OP vi si aggiungono; se la NC dell'OP e' chiusa, la nuova anomalia
  apre una nuova NC collegata alla precedente come *ricaduta*.
- **Tutte le sezioni sono facoltative** (contenimento, analisi delle cause, azioni
  correttive, verifica di efficacia). Lo stato non si sceglie: e' calcolato da quello
  che e' compilato e dall'avanzamento che il capocommessa da' alle anomalie.
- **Chi chiude** e' configurabile (``SiteConfig`` ``anomalie_nc_chiusura``). Una
  verifica di efficacia positiva registrata da chi puo' chiudere chiude la NC.

I controlli di permesso restano nelle view (dipendono dalla request); qui arrivano
gia' come booleani.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from .quality_models import AnomaliaNC as NC
from .quality_models import AnomaliaNCAllegato, AnomaliaNCAzione, AnomaliaNCEvento
from .quality_models import AnomaliaSchedaQualita as Scheda

logger = logging.getLogger(__name__)

TIPO_NOTIFICA_AZIONE = "anomalia_nc_azione"
GIORNI_PREAVVISO_AZIONE = 2

# ── Opzione modulo: chi puo' chiudere una NC ───────────────────────────────

KEY_CHIUSURA = "anomalie_nc_chiusura"
CHIUSURA_GESTORI = "GESTORI"
CHIUSURA_GESTORI_CC = "GESTORI_CC"
CHIUSURA_MODIFICA = "MODIFICA"
CHIUSURA_CHOICES = [
    (CHIUSURA_GESTORI, "Solo chi gestisce le NC (permesso «Anomalie - Gestione NC»)"),
    (CHIUSURA_GESTORI_CC, "Chi gestisce le NC e il capocommessa dell'OP"),
    (CHIUSURA_MODIFICA, "Chiunque può modificare le anomalie dell'OP (anche CAR)"),
]


def get_chiusura_mode() -> str:
    from core.models import SiteConfig

    val = str(SiteConfig.get(KEY_CHIUSURA, "") or "").strip().upper()
    return val if val in dict(CHIUSURA_CHOICES) else CHIUSURA_GESTORI


def set_chiusura_mode(value: str) -> bool:
    from core.models import SiteConfig

    val = str(value or "").strip().upper()
    if val not in dict(CHIUSURA_CHOICES):
        return False
    return bool(SiteConfig.set(KEY_CHIUSURA, val, "Anomalie: chi può chiudere una non conformità."))


def puo_chiudere(*, gestore: bool, capocommessa: bool, modifica_op: bool) -> bool:
    mode = get_chiusura_mode()
    if gestore:
        return True
    if mode == CHIUSURA_GESTORI_CC:
        return capocommessa
    if mode == CHIUSURA_MODIFICA:
        return modifica_op
    return False


# ── Creazione e aggancio ───────────────────────────────────────────────────


def prossimo_protocollo(anno: int) -> str:
    prefisso = f"NC-{anno}-"
    ultimo = 0
    for prot in NC.objects.filter(protocollo__startswith=prefisso).values_list("protocollo", flat=True):
        coda = prot[len(prefisso):]
        if coda.isdigit():
            ultimo = max(ultimo, int(coda))
    return f"{prefisso}{ultimo + 1:04d}"


def responsabili_op(op_titolo: str) -> dict:
    """{"capocommessa": str, "car": str} dai nominativi dell'OP (fail-safe)."""
    out = {"capocommessa": "", "car": ""}
    if not op_titolo:
        return out
    try:
        from automazioni.services import _resolve_op_recipients

        for rec in _resolve_op_recipients(op_titolo):
            role = str(rec.get("role") or "").upper()
            nome = str(rec.get("display") or "").strip()
            key = "capocommessa" if role == "CC" else ("car" if role == "CAR" else "")
            if key and nome and not out[key]:
                out[key] = nome[:200]
    except Exception:
        logger.debug("nc: responsabili OP non risolti op=%s", op_titolo, exc_info=True)
    if not (out["capocommessa"] and out["car"]):
        # Ripiego: i nominativi come scritti sull'OP (gli stessi della pagina gestione).
        try:
            from .views import _report_op_row, _row_capocommessa

            row = _report_op_row(None, op_titolo) or {}
            out["capocommessa"] = out["capocommessa"] or str(_row_capocommessa(row) or "").strip()[:200]
            out["car"] = out["car"] or str(row.get("incaricato") or "").strip()[:200]
        except Exception:
            logger.debug("nc: OP non leggibile op=%s", op_titolo, exc_info=True)
    return out


def riallinea_responsabili(nc) -> None:
    """Rilegge capocommessa/CAR dall'OP sulle NC aperte (es. NC nate dalla migrazione)."""
    if nc.is_chiusa:
        return
    resp = responsabili_op(nc.op_titolo)
    campi = [k for k, v in resp.items() if v and v != getattr(nc, k)]
    for k in campi:
        setattr(nc, k, resp[k])
    if campi:
        nc.save(update_fields=[*campi, "updated_at"])


def nc_aperta_per_op(op_titolo: str):
    return (NC.objects.filter(op_titolo__iexact=op_titolo)
            .exclude(stato=NC.Stato.CHIUSA).order_by("-id").first())


def crea_nc(op_titolo: str, *, part_number: str = "", anno: int | None = None):
    anno = anno or timezone.localdate().year
    precedente = (NC.objects.filter(op_titolo__iexact=op_titolo, stato=NC.Stato.CHIUSA)
                  .order_by("-id").first())
    resp = responsabili_op(op_titolo)
    for _ in range(3):
        try:
            with transaction.atomic():
                nc = NC.objects.create(
                    protocollo=prossimo_protocollo(anno), op_titolo=op_titolo[:100],
                    part_number=part_number[:120], precedente=precedente, **resp,
                )
            testo = "NC aperta alla prima anomalia dell'OP"
            if precedente:
                testo += f" (ricaduta di {precedente.protocollo})"
            registra_evento(nc, "apertura", testo)
            return nc
        except IntegrityError:
            continue  # protocollo preso da una richiesta concorrente: si riprova
    raise RuntimeError(f"protocollo NC non assegnabile per OP {op_titolo}")


def aggancia_a_nc(scheda: Scheda, row: dict | None = None):
    """Aggancia la scheda alla NC aperta del suo OP (creandola se serve)."""
    from .qualita_service import anno_di

    if scheda.nc_id:
        if not scheda.nc.is_chiusa:
            if not (scheda.nc.capocommessa or scheda.nc.car):
                riallinea_responsabili(scheda.nc)
            ricalcola_stato(scheda.nc)
        return scheda.nc
    op = (scheda.op_titolo or "").strip()
    if not op:
        return None
    nc = nc_aperta_per_op(op)
    if nc is None:
        nc = crea_nc(op, part_number=scheda.part_number,
                     anno=anno_di((row or {}).get("created_datetime")))
    scheda.nc = nc
    scheda.save(update_fields=["nc", "updated_at"])
    sn = str((row or {}).get("seriale") or "").strip()
    registra_evento(nc, "anomalia", f"Anomalia aggiunta{f' (S/N {sn})' if sn else ''}")
    ricalcola_stato(nc)
    return nc


# ── Anomalie della NC e stato calcolato ────────────────────────────────────


def anomalie_della_nc(nc) -> list[dict]:
    """Righe per la UI: scheda di classificazione + dati vivi della riga legacy."""
    from .qualita_service import legacy_rows

    schede = list(nc.schede.select_related("tipo_difetto", "reparto").order_by("anomalia_id"))
    righe = legacy_rows([s.anomalia_id for s in schede])
    out = []
    for s in schede:
        r = righe.get(s.anomalia_id) or {}
        out.append({
            "scheda": s,
            "anomalia_id": s.anomalia_id,
            "seriale": str(r.get("seriale") or ""),
            "descrizione": str(r.get("descrizione") or ""),
            "avanzamento": str(r.get("avanzamento") or ""),
            "chiusa": bool(r.get("chiudere")),
            "rdc": bool(r.get("aprire_rdc")),
            "numero_rdc": str(r.get("numero_rdc") or ""),
            "cliente": bool(r.get("segnalare_cliente")),
            "note": str(r.get("note_capocommessa") or ""),
            "esiste": bool(r),
        })
    return out


def contenimento_capocommessa(righe: list[dict]) -> dict:
    """Quanto ha gia' fatto il capocommessa sulle anomalie (avanzamento/chiusura)."""
    esistenti = [r for r in righe if r["esiste"]]
    gestite = [r for r in esistenti
               if r["chiusa"] or str(r["avanzamento"]).strip().lower() not in ("", "in attesa")]
    return {
        "totale": len(esistenti),
        "gestite": len(gestite),
        "chiuse": sum(1 for r in esistenti if r["chiusa"]),
        "tutte_chiuse": bool(esistenti) and all(r["chiusa"] for r in esistenti),
    }


def analisi_compilata(nc) -> bool:
    return bool(
        (nc.causa_radice or "").strip()
        or (nc.analisi_riferimento or "").strip()
        or any(str(x or "").strip() for x in (nc.analisi_perche or []))
        or any(str(v or "").strip() for v in (nc.analisi_ishikawa or {}).values())
        or nc.allegati.filter(sezione=AnomaliaNCAllegato.Sezione.ANALISI).exists()
    )


def calcola_stato(nc, righe: list[dict] | None = None) -> str:
    if nc.chiusa_il:
        return NC.Stato.CHIUSA
    azioni = list(nc.azioni.all())
    aperte = [a for a in azioni if a.aperta]
    fatte = [a for a in azioni if a.stato == AnomaliaNCAzione.Stato.FATTA]
    if nc.verifica_esito or (fatte and not aperte):
        return NC.Stato.VERIFICA
    if aperte:
        return NC.Stato.AZIONI
    if analisi_compilata(nc):
        return NC.Stato.ANALISI
    righe = righe if righe is not None else anomalie_della_nc(nc)
    if (nc.contenimento or "").strip() or contenimento_capocommessa(righe)["gestite"]:
        return NC.Stato.CONTENIMENTO
    return NC.Stato.APERTA


def ricalcola_stato(nc, righe: list[dict] | None = None) -> str:
    nuovo = calcola_stato(nc, righe)
    if nuovo != nc.stato:
        vecchio = nc.get_stato_display()
        nc.stato = nuovo
        nc.save(update_fields=["stato", "updated_at"])
        registra_evento(nc, "stato", f"Stato: {vecchio} → {nc.get_stato_display()}")
    return nuovo


# ── Storico ────────────────────────────────────────────────────────────────


def _nome_utente(user) -> str:
    if not getattr(user, "is_authenticated", False):
        return "Sistema"
    return (user.get_full_name() or user.username or "")[:150]


def registra_evento(nc, tipo: str, testo: str, user=None) -> None:
    try:
        AnomaliaNCEvento.objects.create(
            nc=nc, tipo=tipo[:40], testo=str(testo)[:500],
            user=user if getattr(user, "is_authenticated", False) else None,
            user_nome=_nome_utente(user),
        )
    except Exception:
        logger.warning("nc: evento non registrato nc=%s", getattr(nc, "pk", None), exc_info=True)


# ── Chiusura / riapertura ──────────────────────────────────────────────────


def chiudi(nc, *, user, note: str = "") -> None:
    nc.chiusa_il = timezone.now()
    nc.chiusa_da = user if getattr(user, "is_authenticated", False) else None
    nc.note_chiusura = (note or "").strip()
    nc.stato = NC.Stato.CHIUSA
    nc.save(update_fields=["chiusa_il", "chiusa_da", "note_chiusura", "stato", "updated_at"])
    registra_evento(nc, "chiusura", "NC chiusa" + (f": {nc.note_chiusura[:300]}" if nc.note_chiusura else ""), user)


def riapri(nc, *, user, motivo: str = "") -> None:
    nc.chiusa_il = None
    nc.chiusa_da = None
    nc.save(update_fields=["chiusa_il", "chiusa_da", "updated_at"])
    registra_evento(nc, "riapertura", "NC riaperta" + (f": {motivo.strip()[:300]}" if motivo.strip() else ""), user)
    ricalcola_stato(nc)


# ── Azioni ─────────────────────────────────────────────────────────────────


def responsabili_proposti(nc) -> list[dict]:
    """Capocommessa e CAR dell'OP in testa, poi gli utenti attivi del portale."""
    out, visti = [], set()
    try:
        from .mail_action_service import _resolve_op_cc_car_legacy_ids

        ruoli = {v: k for k, v in (("CC", nc.capocommessa), ("CAR", nc.car)) if v}
        for uid, display in _resolve_op_cc_car_legacy_ids(nc.op_titolo):
            etichetta = ruoli.get(display, "")
            out.append({"id": uid, "nome": display, "ruolo": etichetta or "OP"})
            visti.add(uid)
    except Exception:
        logger.debug("nc: CC/CAR non risolti op=%s", nc.op_titolo, exc_info=True)
    try:
        from core.legacy_models import UtenteLegacy

        for u in UtenteLegacy.objects.filter(attivo=True).order_by("nome").only("id", "nome"):
            if u.id not in visti and (u.nome or "").strip():
                out.append({"id": u.id, "nome": u.nome.strip(), "ruolo": ""})
    except Exception:
        logger.debug("nc: utenti legacy non disponibili", exc_info=True)
    return out


def notifica_azioni_in_scadenza(*, oggi=None, giorni: int = GIORNI_PREAVVISO_AZIONE) -> int:
    """Promemoria in-app al responsabile per le azioni aperte in scadenza o scadute.

    Uno al giorno per azione (``promemoria_il``); nessuna email.
    """
    from django.urls import reverse

    from core.models import Notifica

    oggi = oggi or timezone.localdate()
    limite = oggi + timedelta(days=giorni)
    qs = (AnomaliaNCAzione.objects.select_related("nc")
          .filter(stato__in=[AnomaliaNCAzione.Stato.DA_FARE, AnomaliaNCAzione.Stato.IN_CORSO],
                  responsabile_legacy_id__isnull=False, scadenza__isnull=False, scadenza__lte=limite)
          .exclude(nc__stato=NC.Stato.CHIUSA))
    inviate = 0
    for a in qs:
        if a.promemoria_il == oggi:
            continue
        quando = "scaduta" if a.scadenza < oggi else f"in scadenza il {a.scadenza:%d/%m/%Y}"
        try:
            Notifica.objects.create(
                legacy_user_id=a.responsabile_legacy_id, tipo=TIPO_NOTIFICA_AZIONE,
                messaggio=f"{a.nc.protocollo} · OP {a.nc.op_titolo}: azione {quando} — {a.descrizione[:300]}",
                url_azione=reverse("anomalie_nc_dettaglio", args=[a.nc_id]) + "#azioni",
            )
            a.promemoria_il = oggi
            a.save(update_fields=["promemoria_il", "updated_at"])
            inviate += 1
        except Exception:
            logger.warning("nc: promemoria azione %s non inviato", a.pk, exc_info=True)
    return inviate
