"""Controllo di un OP a blocchi di seriali: lettura, regole di modifica e mail.

Ogni anomalia resta UNA riga della tabella legacy ``anomalie`` (stato, RDC,
segnalazione al cliente e chiusura restano per singola anomalia, come le gestisce
il capocommessa). ``AnomaliaControllo`` e ``AnomaliaBlocco`` le raggruppano:
il controllo è la sessione dell'operatore su un OP, il blocco è l'insieme di
seriali su cui sono state riscontrate una o più anomalie.

La mail al capocommessa con il link di decisione parte una sola volta, a
«Termina controllo» (modalità ``fine``, l'unica per i nuovi controlli). Se dopo
i minuti di promemoria dall'ultimo salvataggio la mail non è ancora partita, il
controllore riceve un promemoria (notifica nel portale + mail con il riepilogo
e il link per riprendere il controllo e inviarla). Se non la manda nemmeno così,
il task periodico la invia da solo dopo i minuti di invio automatico. I due
tempi si impostano in Configurazione → Notifiche (``escalation_config.tempi_controllo``;
default 15 e 60 minuti). I blocchi sono nel DB a ogni «Salva blocco» e quello
ancora in scrittura si salva da solo come bozza (``AnomaliaControllo.bozza``).

La modalità storica ``subito`` (mail qualche minuto dopo ogni salvataggio) resta
solo per i controlli aperti prima del 16/10/2026.
"""
from __future__ import annotations

import logging
import re
from datetime import timedelta

from django.db import connections
from django.utils import timezone

logger = logging.getLogger(__name__)

DEBOUNCE_MINUTI = 5
MAX_BOZZA_BYTES = 200_000
TIPO_NOTIFICA_PROMEMORIA = "anomalie_controllo_da_inviare"
MAX_TENTATIVI_MAIL = 5
SCADENZA_LINK_ORE = 72

_SUP_RE = re.compile(r"^\s*Stato superficie:\s*([^\n]*)\n*", re.IGNORECASE)
_STATI_LIBERI = {"", "in attesa"}


def componi_descrizione(testo: str, stato_superficie: list[str]) -> str:
    """Testo della colonna legacy ``descrizione``: lo stato superficie va in testa,
    nel formato che la pagina mail e la gestione già riconoscono."""
    testo = str(testo or "").strip()
    stati = [str(s).strip() for s in stato_superficie or [] if str(s).strip()]
    if stati:
        return f"Stato superficie: {', '.join(stati)}\n\n{testo}"
    return testo


def separa_descrizione(descrizione: str) -> tuple[list[str], str]:
    """Inverso di ``componi_descrizione``."""
    raw = str(descrizione or "")
    m = _SUP_RE.match(raw)
    if not m:
        return [], raw.strip()
    stati = [s.strip() for s in m.group(1).split(",") if s.strip()]
    return stati, raw[m.end():].strip()


def riga_gestita(row: dict) -> bool:
    """True se il capocommessa ha già deciso qualcosa sulla riga: da quel momento
    l'operatore non può più modificarla dal controllo."""
    if not row:
        return False
    if row.get("chiudere") or row.get("aprire_rdc") or row.get("segnalare_cliente"):
        return True
    if str(row.get("note_capocommessa") or "").strip():
        return True
    return str(row.get("avanzamento") or "").strip().lower() not in _STATI_LIBERI


def controllo_di_anomalia(anomalia_id) -> int | None:
    """Id del controllo OP che ha creato l'anomalia, se c'è (mai bloccante)."""
    try:
        anomalia_id = int(anomalia_id)
    except (TypeError, ValueError):
        return None
    try:
        from .quality_models import AnomaliaSegnalazioneMeta

        return (
            AnomaliaSegnalazioneMeta.objects.filter(anomalia_id=anomalia_id, controllo__isnull=False)
            .values_list("controllo_id", flat=True)
            .first()
        )
    except Exception:
        logger.warning("controllo: lookup controllo per anomalia %s fallito", anomalia_id, exc_info=True)
        return None


def seriali_ripetuti(controllo, voci: list[str], *, escludi_blocco_id=None) -> dict[str, int]:
    """S/N del nuovo blocco già presenti in altri blocchi dello stesso controllo
    (token minuscolo → ordine del blocco). Ammesso — può essere voluto — ma tracciato."""
    from .seriali import espandi_voce

    def _tokens(items) -> list[str]:
        return [t for item in items or [] for t in espandi_voce(item)]

    nuovi = {t.lower() for t in _tokens(voci)}
    out: dict[str, int] = {}
    for blocco in controllo.blocchi.all().order_by("ordine", "id"):
        if escludi_blocco_id and blocco.pk == escludi_blocco_id:
            continue
        for t in _tokens(blocco.seriali if isinstance(blocco.seriali, list) else []):
            if t.lower() in nuovi:
                out.setdefault(t, blocco.ordine)
    return out


def seriali_senza_anomalia(voci_blocco, coperture) -> list[str]:
    """S/N del blocco su cui non c'è nessuna anomalia, nell'ordine del blocco.

    ``coperture``: per ogni anomalia l'elenco dei S/N su cui è presente, oppure
    ``None`` se vale per tutti i seriali del blocco. Senza anomalie non c'è niente
    da segnalare (quel caso ha già il suo errore).
    """
    from .seriali import espandi_voce

    coperture = list(coperture or [])
    if not coperture or any(c is None for c in coperture):
        return []
    coperti = {t.lower() for c in coperture for v in c or [] for t in espandi_voce(v)}
    out: list[str] = []
    visti: set[str] = set()
    for voce in voci_blocco or []:
        for t in espandi_voce(voce):
            k = t.lower()
            if k not in coperti and k not in visti:
                visti.add(k)
                out.append(t)
    return out


def carica_righe(ids: list[int]) -> dict[int, dict]:
    """Righe legacy per id, con i campi che servono al controllo."""
    ids = [int(i) for i in ids if i is not None]
    if not ids:
        return {}
    placeholders = ",".join(["%s"] * len(ids))
    try:
        with connections["default"].cursor() as cur:
            cur.execute(
                "SELECT id, ex_op_nominativo, seriale, descrizione, note_capocommessa, avanzamento,"
                " aprire_rdc, segnalare_cliente, chiudere"
                f" FROM anomalie WHERE id IN ({placeholders})",
                ids,
            )
            cols = [c[0] for c in cur.description]
            return {int(r[0]): dict(zip(cols, r)) for r in cur.fetchall()}
    except Exception:
        logger.exception("controllo: lettura righe anomalie fallita ids=%s", ids)
        return {}


def _allegati(local_id: int) -> list[dict]:
    try:
        from .views import _list_attachments_for_local

        return [
            {"file_id": a["file_id"], "name": a["name"], "size": a["size"], "is_image": a.get("is_image")}
            for a in _list_attachments_for_local(local_id)
        ]
    except Exception:
        logger.warning("controllo: allegati non leggibili id=%s", local_id, exc_info=True)
        return []


def serializza_controllo(controllo, *, con_allegati: bool = True) -> dict:
    from .quality_models import AnomaliaSegnalazioneMeta

    metas = list(
        AnomaliaSegnalazioneMeta.objects.filter(controllo=controllo)
        .order_by("blocco_id", "ordine_nel_blocco", "id")
    )
    righe = carica_righe([m.anomalia_id for m in metas])
    per_blocco: dict[int, list] = {}
    for meta in metas:
        row = righe.get(meta.anomalia_id)
        if row is None:
            continue
        stati, testo = separa_descrizione(row.get("descrizione"))
        per_blocco.setdefault(meta.blocco_id, []).append({
            "local_id": meta.anomalia_id,
            "testo": testo,
            "avanzamento": str(row.get("avanzamento") or ""),
            "chiusa": bool(row.get("chiudere")),
            "aprire_rdc": bool(row.get("aprire_rdc")),
            "segnalare": bool(row.get("segnalare_cliente")),
            "note_capocommessa": str(row.get("note_capocommessa") or ""),
            "gestita": riga_gestita(row),
            "allegati": _allegati(meta.anomalia_id) if con_allegati else [],
            "_seriale": str(row.get("seriale") or ""),
        })
    blocchi = []
    for blocco in controllo.blocchi.all().order_by("ordine", "id"):
        anomalie = per_blocco.get(blocco.pk, [])
        for a in anomalie:
            a.update(seriali_anomalia(a.pop("_seriale", ""), blocco))
        voci_blocco = blocco.seriali if isinstance(blocco.seriali, list) else []
        scoperti = seriali_senza_anomalia(voci_blocco, [None if a["tutti"] else a["seriali"] for a in anomalie])
        blocchi.append({
            "id": blocco.pk,
            "ordine": blocco.ordine,
            "fase": blocco.fase,
            "seriali": blocco.seriali if isinstance(blocco.seriali, list) else [],
            "seriale_label": blocco.seriale_label,
            "stato_superficie": blocco.stato_superficie if isinstance(blocco.stato_superficie, list) else [],
            "anomalie": anomalie,
            # S/N del blocco senza nessuna anomalia (salvati con conferma dell'operatore).
            "seriali_scoperti": scoperti,
            "bloccato": any(a["gestita"] for a in anomalie),
        })
    return {
        "id": controllo.pk,
        "op_id": controllo.op_id,
        "op_item_id": controllo.op_item_id,
        "fase": controllo.fase,
        "mail_mode": controllo.mail_mode,
        "operatore": controllo.operatore_display,
        "passaggi": controllo.passaggi if isinstance(controllo.passaggi, list) else [],
        "created_at": controllo.created_at.isoformat() if controllo.created_at else "",
        "terminato": controllo.terminato_at is not None,
        "da_notificare": len(controllo.da_notificare or []),
        "ultima_mail_at": controllo.ultima_mail_at.isoformat() if controllo.ultima_mail_at else "",
        "mail_errore": controllo.mail_errore,
        "bozza": controllo.bozza if isinstance(controllo.bozza, dict) else {},
        # OP nuovo non ancora creato (si crea al primo «Salva blocco»).
        "op_nuovo": controllo.op_nuovo if isinstance(controllo.op_nuovo, dict) else {},
        "bozza_at": controllo.bozza_at.isoformat() if controllo.bozza_at else "",
        "destinatari_extra": [
            {"email": d.get("email", ""), "nome": d.get("nome", "")}
            for d in (controllo.destinatari_extra or []) if isinstance(d, dict)
        ],
        "blocchi": blocchi,
    }


# ─── Gruppo qualità: controlli condivisi fra colleghi ────────────────────────
# Chi ha uno di questi ruoli (preset di «Ruoli e permessi») vede i controlli
# aperti dei colleghi dello stesso gruppo e può prenderli in carico: una
# segnalazione corposa iniziata a fine turno la finisce il collega dopo.
PRESET_GRUPPO_QUALITA = frozenset({"controllo-qualita", "qualita"})
GIORNI_CONTROLLI_SOSPESI = 14


def _legacy_id_utente(user) -> int | None:
    try:
        return int(user.profile.legacy_user_id)
    except Exception:
        return None


def nel_gruppo_qualita(user, _memo: dict | None = None) -> bool:
    """True se l'utente ha il ruolo Controllo qualità o Qualità (anche da organigramma)."""
    if user is None or not getattr(user, "pk", None):
        return False
    if _memo is not None and user.pk in _memo:
        return _memo[user.pk]
    esito = False
    legacy_id = _legacy_id_utente(user)
    if legacy_id:
        try:
            from core.permessi.motore import ruoli_della_persona

            esito = any(
                getattr(g, "preset", "") in PRESET_GRUPPO_QUALITA
                for g in ruoli_della_persona(legacy_id, includi_base=False)
            )
        except Exception:
            logger.warning("gruppo qualita': ruoli non leggibili per %s", user.pk, exc_info=True)
    if _memo is not None:
        _memo[user.pk] = esito
    return esito


def colleghi_del_gruppo(user, controllo, _memo: dict | None = None) -> bool:
    """Il controllo è di un collega del gruppo qualità dell'utente (e non dell'utente)."""
    if controllo.operatore_id == getattr(user, "pk", None) or controllo.operatore is None:
        return False
    return nel_gruppo_qualita(user, _memo) and nel_gruppo_qualita(controllo.operatore, _memo)


def in_sospeso(controllo) -> bool:
    """Qualcosa da finire: blocco scritto e non salvato, blocchi copiati da caricare
    o anomalie salvate non ancora comunicate al capocommessa."""
    return bool(bozza_piena(controllo.bozza) or controllo.da_notificare)


def riassunto_sospeso(controllo, user) -> dict:
    """Riga per l'elenco dei controlli in sospeso (pagina «Apertura segnalazione»)."""
    bozza = controllo.bozza if isinstance(controllo.bozza, dict) else {}
    in_bozza = len([a for a in (bozza.get("anomalie") or []) if isinstance(a, dict)])
    coda = [b for b in (bozza.get("coda") or []) if isinstance(b, dict)]
    ultimo = max([d for d in (controllo.bozza_at, controllo.ultimo_salvataggio_at, controllo.created_at) if d])
    return {
        "id": controllo.pk,
        "op_id": controllo.op_id,
        "op_nuovo": bool(controllo.op_nuovo),
        "fase": controllo.fase,
        "operatore": controllo.operatore_display,
        "mio": controllo.operatore_id == getattr(user, "pk", None),
        "anomalie_in_bozza": in_bozza,
        "blocchi_da_copiare": len(coda),
        "da_notificare": len(controllo.da_notificare or []),
        "ultimo_at": ultimo.isoformat() if ultimo else "",
        "passaggi": controllo.passaggi if isinstance(controllo.passaggi, list) else [],
    }


def controlli_sospesi(user, *, op_id: str = "", limite: int = 30) -> list:
    """Controlli aperti con qualcosa in sospeso visibili all'utente: i suoi e, se è
    nel gruppo qualità, quelli dei colleghi del gruppo. Dal più recente."""
    from .quality_models import AnomaliaControllo

    qs = AnomaliaControllo.objects.filter(
        terminato_at__isnull=True,
        created_at__gte=timezone.now() - timedelta(days=GIORNI_CONTROLLI_SOSPESI),
    ).select_related("operatore")
    if op_id:
        qs = qs.filter(op_id__iexact=op_id)
    memo: dict = {}
    gruppo = nel_gruppo_qualita(user, memo)
    out = []
    for c in qs.order_by("-id")[:300]:
        if c.operatore_id != user.pk and not (gruppo and colleghi_del_gruppo(user, c, memo)):
            continue
        out.append(c)
    return out[:limite]


def prendi_in_carico(controllo, user, nome: str) -> dict:
    """Passa il controllo al collega: da qui in avanti bozza, blocchi, promemoria e
    «Termina» sono suoi. Il passaggio resta in ``passaggi``; chi lo aveva viene avvisato."""
    da_nome = controllo.operatore_display or ""
    da_user = controllo.operatore
    passaggio = {"da": da_nome, "a": nome, "at": timezone.now().isoformat()}
    controllo.passaggi = [*(controllo.passaggi if isinstance(controllo.passaggi, list) else []), passaggio]
    controllo.operatore = user
    controllo.operatore_display = nome[:200]
    # Il promemoria della bozza riparte per il nuovo titolare.
    controllo.promemoria_bozza_at = None
    controllo.save(update_fields=["passaggi", "operatore", "operatore_display", "promemoria_bozza_at", "updated_at"])
    legacy_da = _legacy_id_utente(da_user) if da_user is not None else None
    if legacy_da:
        try:
            from core.models import Notifica

            Notifica.objects.create(
                legacy_user_id=legacy_da,
                tipo=TIPO_NOTIFICA_PROMEMORIA,
                messaggio=(f"{nome} ha preso in carico il tuo controllo su OP {controllo.op_id} "
                           f"(fase {controllo.fase}) e lo prosegue.")[:500],
                url_azione=url_controllo(controllo),
            )
        except Exception:
            logger.warning("controllo %s: notifica passaggio non creata", controllo.pk, exc_info=True)
    return passaggio


def seriali_anomalia(seriale_riga: str, blocco) -> dict:
    """Seriali di una riga rispetto al suo blocco: tutti, oppure solo una parte.

    Il flag non ha una colonna sua: la colonna legacy ``seriale`` della riga è la
    fonte. Uguale all'etichetta del blocco (o non leggibile) = tutti i seriali.
    """
    from .seriali import comprimi_seriali, espandi_seriale_composito, espandi_voce

    seriale_riga = str(seriale_riga or "").strip()
    label = str(getattr(blocco, "seriale_label", "") or "")
    voci_blocco = blocco.seriali if isinstance(getattr(blocco, "seriali", None), list) else []
    tutti = {"tutti": True, "seriali": list(voci_blocco), "seriale_label": label}
    if not seriale_riga or seriale_riga == label:
        return tutti
    blocco_tokens = [t for v in voci_blocco for t in espandi_voce(v)]
    riga_lower = {t.lower() for t in espandi_seriale_composito(seriale_riga)}
    subset = [t for t in blocco_tokens if t.lower() in riga_lower]
    if not subset or len({t.lower() for t in subset}) >= len({t.lower() for t in blocco_tokens}):
        return tutti
    return {"tutti": False, "seriali": comprimi_seriali(subset), "seriale_label": seriale_riga}


def accoda_notifica(controllo, ids: list[int]) -> None:
    pending = [int(i) for i in (controllo.da_notificare or [])]
    for i in ids:
        if int(i) not in pending:
            pending.append(int(i))
    controllo.da_notificare = pending
    controllo.ultimo_salvataggio_at = timezone.now()
    controllo.promemoria_at = None
    controllo.save(update_fields=["da_notificare", "ultimo_salvataggio_at", "promemoria_at", "updated_at"])


def gruppi_per_blocco(anomalie_rows: list[dict]) -> list[dict]:
    """Raggruppa righe anomalia per blocco di seriali (ordine di comparsa).

    Le righe nate fuori da un controllo restano gruppi da una riga sola.
    Arricchisce ogni riga con ``fase``, ``blocco_id``, ``blocco_label``.
    """
    from .quality_models import AnomaliaSegnalazioneMeta

    ids = []
    for row in anomalie_rows:
        try:
            ids.append(int(row.get("id")))
        except (TypeError, ValueError):
            continue
    metas = {
        m.anomalia_id: m
        for m in AnomaliaSegnalazioneMeta.objects.filter(anomalia_id__in=ids).select_related("blocco", "controllo")
    }
    gruppi: list[dict] = []
    per_chiave: dict[str, dict] = {}
    for row in anomalie_rows:
        try:
            meta = metas.get(int(row.get("id")))
        except (TypeError, ValueError):
            meta = None
        stati, testo = separa_descrizione(row.get("descrizione"))
        row["testo"] = testo
        row["stato_superficie"] = ", ".join(stati)
        row["fase"] = meta.fase if meta else row.get("fase", "")
        if meta and meta.blocco_id:
            chiave = f"b{meta.blocco_id}"
            titolo = meta.blocco.seriale_label or row.get("seriale") or ""
            controllo = meta.controllo
            sottotitolo = " · ".join(filter(None, [
                f"Fase {meta.blocco.fase}" if meta.blocco.fase else "",
                f"controllo di {controllo.operatore_display}" if controllo and controllo.operatore_display else "",
                timezone.localtime(controllo.created_at).strftime("%d/%m/%Y") if controllo and controllo.created_at else "",
            ]))
        else:
            chiave = f"r{row.get('id')}"
            titolo = row.get("seriale") or ""
            sottotitolo = f"Fase {row['fase']}" if row.get("fase") else ""
        row["blocco_id"] = meta.blocco_id if meta else None
        # Anomalia presente solo su una parte dei seriali del blocco.
        row["seriali_parziali"] = ""
        if meta and meta.blocco_id:
            info = seriali_anomalia(row.get("seriale"), meta.blocco)
            if not info["tutti"]:
                row["seriali_parziali"] = info["seriale_label"]
        gruppo = per_chiave.get(chiave)
        if gruppo is None:
            gruppo = {"chiave": chiave, "titolo": titolo, "sottotitolo": sottotitolo, "righe": []}
            per_chiave[chiave] = gruppo
            gruppi.append(gruppo)
        gruppo["righe"].append(row)
    return gruppi


def _destinatari(op_id: str) -> tuple[dict | None, dict | None]:
    """(principale, copia): capocommessa e CAR; per i collaudi di benestare il CAR
    è il principale (stessa regola dell'automazione AU51)."""
    from automazioni.services import _resolve_op_recipients

    from .views import _op_is_benestare

    recipients = _resolve_op_recipients(op_id) or []
    cc_rec = next((r for r in recipients if r.get("role") == "CC" and r.get("email")), None)
    car_rec = next((r for r in recipients if r.get("role") == "CAR" and r.get("email")), None)
    if _op_is_benestare(op_id):
        primary = car_rec or cc_rec
    else:
        primary = cc_rec or car_rec
    secondary = None
    for rec in (cc_rec, car_rec):
        if rec and rec is not primary and (not primary or rec["email"].lower() != primary["email"].lower()):
            secondary = rec
    return primary, secondary


def _lista_config_persone(key: str) -> list[dict]:
    """Indirizzi di una lista di Configurazione → Notifiche, col nome se in anagrafica."""
    try:
        from .mail_action_service import _resolve_lista_config

        emails = _resolve_lista_config(key)
    except Exception:
        logger.warning("controllo: lista %s non leggibile", key, exc_info=True)
        return []
    out, visti = [], set()
    for email in emails:
        if email.lower() in visti:
            continue
        visti.add(email.lower())
        persona = persona_da_email(email)
        out.append({"email": email, "nome": persona["nome"] if persona else email})
    return out


def destinatari_display(op_id: str, extra: list | None = None) -> dict:
    """Chi riceverà le mail del controllo, per l'operatore: capocommessa/CAR
    risolti dall'OP più le persone aggiunte a mano (mail con il link), e le liste
    fisse di Configurazione → Notifiche che ricevono il riepilogo senza link
    (sempre «Riepilogo modifiche»; «RDC / segnalazione cliente» solo se serve)."""
    extra_out = [{"email": d.get("email", ""), "nome": d.get("nome", "")} for d in (extra or []) if isinstance(d, dict)]
    liste = {
        "riepilogo": _lista_config_persone("conferma_aggiornamenti"),
        "riepilogo_rdc": _lista_config_persone("rdc_segnalazione"),
    }
    try:
        primary, secondary = _destinatari(op_id)
    except Exception:
        logger.warning("controllo: destinatari non risolti op=%s", op_id, exc_info=True)
        return {"to": "", "cc": "", "to_email": "", "cc_email": "", "extra": extra_out, **liste}
    nome = lambda rec: (rec.get("display") or rec.get("email") or "") if rec else ""  # noqa: E731
    return {
        "to": nome(primary),
        "cc": nome(secondary),
        "to_email": primary.get("email", "") if primary else "",
        "cc_email": secondary.get("email", "") if secondary else "",
        "extra": extra_out,
        **liste,
    }


# ── Destinatari aggiuntivi ────────────────────────────────────────────────────
# Ricevono la stessa mail (con il link di decisione) in copia: per questo si
# accettano solo indirizzi di persone presenti in anagrafica, mai indirizzi liberi.

MAX_DESTINATARI_EXTRA = 10
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _persona_row(a) -> dict | None:
    from core import naming

    email = str(a.email_notifica or "").strip()
    if not _EMAIL_RE.match(email):
        return None
    return {"email": email, "nome": naming.nome_completo(a.nome, a.cognome) or email}


def _solo_attivi(qs):
    """Esclude i dipendenti cessati: la colonna legacy ``attivo`` non è nel modello."""
    try:
        from core.legacy_utils import legacy_table_columns

        if "attivo" in (legacy_table_columns("anagrafica_dipendenti") or set()):
            return qs.extra(where=["attivo = 1"])
    except Exception:
        logger.warning("controllo: colonne anagrafica non leggibili", exc_info=True)
    return qs


def cerca_persone(q: str, limit: int = 15) -> list[dict]:
    """Persone in anagrafica con un'email di notifica, per nome, cognome o email."""
    q = str(q or "").strip()
    if len(q) < 2:
        return []
    from django.db.models import Q

    from core.legacy_models import AnagraficaDipendente

    filtro = Q(email_notifica__icontains=q)
    for parola in q.split()[:3]:
        filtro |= Q(nome__icontains=parola) | Q(cognome__icontains=parola)
    risultati, visti = [], set()
    try:
        qs = (
            _solo_attivi(AnagraficaDipendente.objects.filter(filtro))
            .exclude(email_notifica__isnull=True).exclude(email_notifica="")
            .order_by("cognome", "nome")[: limit * 2]
        )
        for a in qs:
            row = _persona_row(a)
            if row and row["email"].lower() not in visti:
                visti.add(row["email"].lower())
                risultati.append(row)
            if len(risultati) >= limit:
                break
    except Exception:
        logger.warning("controllo: ricerca persone non riuscita q=%s", q, exc_info=True)
    return risultati


def persona_da_email(email: str) -> dict | None:
    """La persona in anagrafica con questa email di notifica (o login), None se sconosciuta."""
    email = str(email or "").strip()
    if not _EMAIL_RE.match(email):
        return None
    from django.db.models import Q

    from core.legacy_models import AnagraficaDipendente

    try:
        for a in _solo_attivi(AnagraficaDipendente.objects.filter(
            Q(email_notifica__iexact=email) | Q(email__iexact=email)
        )).order_by("id")[:5]:
            row = _persona_row(a)
            if row:
                return row
    except Exception:
        logger.warning("controllo: lookup persona non riuscito", exc_info=True)
    return None


def _norm_nome(text) -> str:
    return " ".join(str(text or "").split()).casefold()


def capi_commessa_persone() -> list[dict]:
    """I capicommessa della configurazione (lista «Capi commessa») con la loro email
    di notifica, per «Aggiungi altro capocommessa». Chi non ha email resta fuori."""
    try:
        from .views import _load_anomalie_lists

        nomi = _load_anomalie_lists().get("capi_commessa") or []
    except Exception:
        logger.warning("controllo: lista capi commessa non leggibile", exc_info=True)
        return []
    if not nomi:
        return []
    from core.legacy_models import AnagraficaDipendente

    per_nome: dict[str, dict] = {}
    try:
        qs = _solo_attivi(
            AnagraficaDipendente.objects.exclude(email_notifica__isnull=True).exclude(email_notifica="")
        ).only("nome", "cognome", "email_notifica")
        for a in qs:
            row = _persona_row(a)
            if not row:
                continue
            for chiave in (_norm_nome(f"{a.nome} {a.cognome}"), _norm_nome(f"{a.cognome} {a.nome}")):
                per_nome.setdefault(chiave, row)
    except Exception:
        logger.warning("controllo: anagrafica capi commessa non leggibile", exc_info=True)
        return []
    out, visti = [], set()
    for nome in nomi:
        row = per_nome.get(_norm_nome(nome))
        if row and row["email"].lower() not in visti:
            visti.add(row["email"].lower())
            out.append(row)
    return sorted(out, key=lambda r: r["nome"].casefold())


def normalizza_destinatari_extra(raw) -> tuple[list[dict], list[str]]:
    """Valida l'elenco inviato dalla pagina: (destinatari validi, email rifiutate).
    Nome ed email vengono sempre riletti dall'anagrafica, mai presi dal client."""
    if not isinstance(raw, list):
        return [], []
    validi, rifiutati, visti = [], [], set()
    for item in raw[: MAX_DESTINATARI_EXTRA * 2]:
        email = str((item.get("email") if isinstance(item, dict) else item) or "").strip()[:200]
        if not email:
            continue
        persona = persona_da_email(email)
        if persona is None:
            rifiutati.append(email)
            continue
        chiave = persona["email"].lower()
        if chiave in visti:
            continue
        visti.add(chiave)
        validi.append(persona)
    return validi[:MAX_DESTINATARI_EXTRA], rifiutati


def stati_superficie_configurati() -> bool:
    """True se la configurazione liste prevede scelte di stato superficie."""
    try:
        from .views import _load_anomalie_lists

        return bool(_load_anomalie_lists().get("stati_superficie"))
    except Exception:
        logger.warning("controllo: liste anomalie non leggibili", exc_info=True)
        return False


def invia_mail_controllo(controllo) -> dict:
    """Manda al capocommessa (in copia il CAR) la mail con il link di decisione per
    le anomalie del controllo non ancora comunicate. Idempotente: svuota la coda
    solo a invio riuscito."""
    from .mail_action_service import (
        _alert_admins_send_failure,
        send_anomalie_action_email,
        send_anomalie_update_confirmation,
    )

    ids = [int(i) for i in (controllo.da_notificare or [])]
    if not ids:
        return {"sent": False, "reason": "nessuna_anomalia"}
    righe = carica_righe(ids)
    rows = [righe[i] for i in ids if i in righe and not righe[i].get("chiudere")]
    if not rows:
        controllo.da_notificare = []
        controllo.save(update_fields=["da_notificare", "updated_at"])
        return {"sent": False, "reason": "nessuna_anomalia"}

    primary, secondary = _destinatari(controllo.op_id)
    cc = [secondary["email"]] if secondary else []
    gia = {e.lower() for e in cc} | ({primary["email"].lower()} if primary else set())
    extra = []
    for d in controllo.destinatari_extra or []:
        email = str((d or {}).get("email") or "").strip() if isinstance(d, dict) else ""
        if email and email.lower() not in gia:
            gia.add(email.lower())
            cc.append(email)
            extra.append(d.get("nome") or email)
    try:
        if not primary:
            raise ValueError("Capocommessa e CAR dell'OP non hanno un indirizzo email risolvibile.")
        send_anomalie_action_email(
            recipient_email=primary["email"],
            recipient_display=primary.get("display") or primary["email"],
            op_id=controllo.op_id,
            op_nominativo=controllo.op_id,
            anomalie_rows=rows,
            action="aggiorna_avanzamento",
            expires_hours=SCADENZA_LINK_ORE,
            source_automation=f"controllo:{controllo.pk}",
            created_by=controllo.operatore,
            cc=cc or None,
        )
    except Exception as exc:
        controllo.mail_tentativi = int(controllo.mail_tentativi or 0) + 1
        controllo.mail_errore = str(exc)[:2000]
        fields = ["mail_tentativi", "mail_errore", "updated_at"]
        if controllo.mail_tentativi >= MAX_TENTATIVI_MAIL:
            controllo.da_notificare = []
            fields.append("da_notificare")
            _alert_admins_send_failure(
                context="mail controllo OP al capocommessa",
                op_id=controllo.op_id,
                detail=f"Invio non riuscito dopo {controllo.mail_tentativi} tentativi: {controllo.mail_errore}",
            )
        controllo.save(update_fields=fields)
        logger.warning("controllo %s: mail al capocommessa non inviata: %s", controllo.pk, exc)
        return {"sent": False, "reason": "errore", "error": controllo.mail_errore}

    controllo.da_notificare = []
    controllo.ultima_mail_at = timezone.now()
    controllo.mail_tentativi = 0
    controllo.mail_errore = ""
    controllo.save(update_fields=["da_notificare", "ultima_mail_at", "mail_tentativi", "mail_errore", "updated_at"])

    # Copia di riepilogo (senza link) al segnalante e alla lista fissa «conferma
    # aggiornamenti», come per ogni altro salvataggio; CC/CAR hanno già la mail sopra.
    try:
        send_anomalie_update_confirmation(
            op_id=controllo.op_id,
            op_nominativo=controllo.op_id,
            anomalie_rows=rows,
            updates_summary=[
                {
                    "id": r["id"],
                    "seriale": r.get("seriale") or "",
                    "avanzamento": r.get("avanzamento") or "",
                    "descrizione": r.get("descrizione") or "",
                }
                for r in rows
            ],
            source_label=f"Controllo OP · fase {controllo.fase} · {controllo.operatore_display}",
            include_op_recipients=False,
        )
    except Exception:
        logger.warning("controllo %s: riepilogo al segnalante non inviato", controllo.pk, exc_info=True)

    return {
        "sent": True,
        "to": primary.get("display") or primary["email"],
        "cc": (secondary.get("display") or secondary["email"]) if secondary else "",
        "extra": extra,
        "n": len(rows),
    }


def salva_bozza(controllo, bozza) -> bool:
    """Salva (o svuota, con un dict vuoto) la bozza del blocco in scrittura."""
    import json

    if not isinstance(bozza, dict):
        bozza = {}
    if len(json.dumps(bozza, ensure_ascii=False)) > MAX_BOZZA_BYTES:
        return False
    controllo.bozza = bozza
    controllo.bozza_at = timezone.now() if bozza else None
    controllo.save(update_fields=["bozza", "bozza_at", "updated_at"])
    return True


def flush_controlli() -> dict:
    """Task periodico: manda le mail dei controlli pronti."""
    from .quality_models import AnomaliaControllo

    from .escalation_config import tempi_controllo

    tempi = tempi_controllo()
    now = timezone.now()
    # Niente filtri sul JSONField (su SQL Server i confronti JSON sono fragili):
    # si guardano i controlli recenti e si verifica la coda in Python.
    candidati = AnomaliaControllo.objects.filter(ultimo_salvataggio_at__gte=now - timedelta(days=14))
    inviati = promemoria = 0
    for controllo in candidati:
        if not controllo.da_notificare:
            continue
        fermo = now - controllo.ultimo_salvataggio_at
        if controllo.mail_mode == AnomaliaControllo.MailMode.FINE:
            pronto = controllo.terminato_at is not None or fermo >= timedelta(minutes=tempi["invio_auto"])
        else:
            pronto = fermo >= timedelta(minutes=DEBOUNCE_MINUTI)
        if pronto:
            if invia_mail_controllo(controllo).get("sent"):
                inviati += 1
            continue
        if (
            controllo.mail_mode == AnomaliaControllo.MailMode.FINE
            and controllo.terminato_at is None
            and controllo.promemoria_at is None
            and fermo >= timedelta(minutes=tempi["promemoria"])
            and invia_promemoria_controllore(controllo, invio_auto_minuti=tempi["invio_auto"])
        ):
            promemoria += 1
    return {"controlli_inviati": inviati, "controlli_promemoria": promemoria,
            "bozze_promemoria": promemoria_bozze(now, tempi["promemoria"])}


def promemoria_bozze(now, minuti: int) -> int:
    """Bozze ferme da ``minuti`` (blocco scritto e mai salvato, anche su un OP nuovo
    non ancora creato) senza anomalie salvate da inviare: promemoria al controllore,
    uno per pausa. Con anomalie da inviare ci pensa il promemoria del controllo."""
    from .quality_models import AnomaliaControllo

    inviati = 0
    for controllo in AnomaliaControllo.objects.filter(
        terminato_at__isnull=True, bozza_at__isnull=False,
        bozza_at__gte=now - timedelta(days=14), bozza_at__lte=now - timedelta(minutes=minuti),
    ):
        if controllo.da_notificare or not bozza_piena(controllo.bozza):
            continue
        if controllo.promemoria_bozza_at and controllo.promemoria_bozza_at >= controllo.bozza_at:
            continue
        if invia_promemoria_bozza(controllo):
            inviati += 1
    return inviati


def bozza_piena(bozza) -> bool:
    """Stessa regola della pagina: seriali, stati, anomalie o blocchi copiati da caricare."""
    if not isinstance(bozza, dict):
        return False
    return bool(bozza.get("voci") or bozza.get("stati") or bozza.get("anomalie") or bozza.get("coda"))


def righe_bozza(bozza) -> list[str]:
    """Testo leggibile della bozza per la mail: seriali, anomalie, blocchi copiati in coda."""
    out: list[str] = []
    voci = [str(v) for v in (bozza.get("voci") or []) if str(v).strip()]
    anomalie = [a for a in (bozza.get("anomalie") or []) if isinstance(a, dict)]
    if voci or anomalie:
        out.append(f"  S/N {', '.join(voci) or '—'}")
        for a in anomalie:
            testo = str(a.get("testo") or "").strip() or "(senza descrizione)"
            allegati = int(a.get("allegati") or 0)
            out.append(f"    • {testo}" + (f" (+{allegati} allegati da ricaricare)" if allegati else ""))
    coda = [b for b in (bozza.get("coda") or []) if isinstance(b, dict)]
    if coda:
        n = sum(len(b.get("anomalie") or []) for b in coda)
        out.append(f"  Da copiare ancora: {len(coda)} blocc{'o' if len(coda) == 1 else 'hi'} con {n} anomali{'a' if n == 1 else 'e'}")
        for b in coda:
            out.append(f"    S/N {', '.join(str(v) for v in (b.get('seriali') or [])) or '—'}")
    return out


def html_bozza(controllo, *, op_txt: str, link: str, nuovo: bool) -> str:
    """Corpo HTML della mail promemoria bozza nel layout NOVICROM HUB.

    Stessi contenuti del testo semplice: dati del controllo, una card per blocco
    di seriali con le anomalie scritte, blocchi copiati ancora da caricare e il
    pulsante che riapre il controllo. I testi della bozza sono sempre escapati.
    """
    import html as _html

    from core.email_utils import email_badge, email_cta, email_facts_table, render_hub_email_html

    bozza = controllo.bozza if isinstance(controllo.bozza, dict) else {}

    def _p(testo_html: str, *, colore: str = "#475569", margine: str = "0 0 16px") -> str:
        return (f'<p style="margin:{margine};color:{colore};font-size:15px;line-height:1.6;">'
                f"{testo_html}</p>")

    def _card(seriali, anomalie, *, accento: str, etichetta: str, tono: str) -> str:
        titolo = "S/N " + (", ".join(str(v) for v in seriali if str(v).strip()) or "—")
        righe = []
        for a in anomalie:
            testo = str(a.get("testo") or "").strip() or "(senza descrizione)"
            allegati = int(a.get("allegati") or 0)
            extra = (f' <span style="color:#92400e;">(+{allegati} allegati da ricaricare)</span>'
                     if allegati else "")
            righe.append(
                '<div style="margin-top:6px;font-size:14px;color:#334155;line-height:1.5;">'
                f"&bull; {_html.escape(testo)}{extra}</div>"
            )
        return (
            '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            'style="width:100%;border-collapse:collapse;margin:0 0 10px;background:#f8fafc;'
            'border:1px solid #e2e8f0;border-radius:10px;">'
            f'<tr><td style="width:6px;background:{accento};border-radius:10px 0 0 10px;">&nbsp;</td>'
            '<td style="padding:14px 16px;">'
            f'<div style="font-size:15px;color:#182232;font-weight:700;">{_html.escape(titolo)} '
            f"{email_badge(etichetta, tono)}</div>"
            + "".join(righe)
            + "</td></tr></table>"
        )

    card = []
    voci = [str(v) for v in (bozza.get("voci") or []) if str(v).strip()]
    anomalie = [a for a in (bozza.get("anomalie") or []) if isinstance(a, dict)]
    if voci or anomalie:
        card.append(_card(voci, anomalie, accento="#d97706", etichetta="Da salvare", tono="warning"))
    for b in bozza.get("coda") or []:
        if isinstance(b, dict):
            card.append(_card(
                b.get("seriali") or [], [a for a in (b.get("anomalie") or []) if isinstance(a, dict)],
                accento="#64748b", etichetta="Da copiare ancora", tono="neutral",
            ))

    conseguenza = " e l'OP non viene creato" if nuovo else ""
    corpo = "".join([
        _p("Nel controllo ci sono anomalie <strong>scritte ma non ancora salvate</strong>: finché non premi "
           f"«Salva blocco» non arrivano al capocommessa{conseguenza}."),
        email_facts_table([
            ("OP", str(controllo.op_id) + (" (nuovo, non ancora creato)" if nuovo else "")),
            ("Fase", str(controllo.fase or "—")),
        ]),
        _p("Quello che hai scritto (salvato in automatico):", colore="#182232", margine="22px 0 10px"),
        "".join(card) or _p("—"),
        _p("Gli allegati non si salvano in bozza: vanno ricaricati.", colore="#64748b", margine="6px 0 0"),
    ])
    return render_hub_email_html(
        corpo,
        title="Anomalie non ancora salvate",
        email_type="Anomalie · Promemoria",
        badge=str(controllo.op_id or ""),
        section_label=f"Controllo · fase {controllo.fase}" if controllo.fase else "Controllo",
        cta_buttons=email_cta("Riprendi il controllo", link,
                              note="Poi premi «Salva blocco» e «Termina controllo». Link diretto: " + link),
        footer_note="Messaggio automatico generato da NOVICROM HUB. Non rispondere a questa email.",
        preheader=f"{op_txt}: anomalie scritte ma non salvate. Riprendi il controllo e premi «Salva blocco».",
    )


def invia_promemoria_bozza(controllo) -> bool:
    """Notifica nel portale e mail al controllore con il contenuto della bozza e il
    link che riapre il controllo. ``promemoria_bozza_at`` evita di ripeterlo finché
    la bozza non cambia."""
    controllo.promemoria_bozza_at = timezone.now()
    controllo.save(update_fields=["promemoria_bozza_at", "updated_at"])

    from core.accounts.portal_links import portal_link

    url = url_controllo(controllo)
    link = portal_link(url) or url
    nuovo = bool(controllo.op_nuovo)
    op_txt = f"OP {controllo.op_id}" + (" (nuovo, non ancora creato)" if nuovo else "")
    legacy_id, email = _contatti_operatore(controllo)
    fatto = False
    if legacy_id:
        try:
            from core.models import Notifica

            Notifica.objects.filter(
                legacy_user_id=legacy_id, tipo=TIPO_NOTIFICA_PROMEMORIA, url_azione=url, letta=False,
            ).update(letta=True)
            Notifica.objects.create(
                legacy_user_id=legacy_id,
                tipo=TIPO_NOTIFICA_PROMEMORIA,
                messaggio=(f"{op_txt} · fase {controllo.fase}: hai anomalie scritte ma non salvate. Riprendi il "
                           "controllo e premi «Salva blocco».")[:500],
                url_azione=url,
            )
            fatto = True
        except Exception:
            logger.warning("controllo %s: notifica bozza non creata", controllo.pk, exc_info=True)
    if email:
        try:
            from .mail_action_service import send_and_log_email

            body = "\n".join([
                f"Nel controllo su {op_txt} (fase {controllo.fase}) ci sono anomalie scritte ma non ancora "
                "salvate: finché non premi «Salva blocco» non arrivano al capocommessa"
                + (" e l'OP non viene creato." if nuovo else "."),
                "",
                "Quello che hai scritto (salvato in automatico):",
                *righe_bozza(controllo.bozza),
                "",
                f"Riprendi da qui e premi «Salva blocco», poi «Termina controllo»: {link}",
                "Gli allegati non si salvano in bozza: vanno ricaricati.",
            ])
            try:
                body_html = html_bozza(controllo, op_txt=op_txt, link=link, nuovo=nuovo)
            except Exception:
                logger.warning("controllo %s: HTML promemoria bozza non generato", controllo.pk, exc_info=True)
                body_html = ""
            ok, _log = send_and_log_email(
                kind="promemoria_bozza_controllo",
                subject=f"[Novicrom Hub] {op_txt}: anomalie non ancora salvate",
                body_text=body,
                body_html=body_html,
                to=[email],
                op_id=controllo.op_id,
                context={"controllo_id": controllo.pk, "op_nuovo": nuovo},
                fail_silently=True,
            )
            fatto = fatto or bool(ok)
        except Exception:
            logger.warning("controllo %s: mail bozza non inviata", controllo.pk, exc_info=True)
    return fatto


def url_controllo(controllo) -> str:
    """Pagina del controllo: con ``op_id`` si apre sull'OP con «Riprendi»."""
    from urllib.parse import quote

    from django.urls import reverse

    # ``controllo`` riapre direttamente questo controllo (serve anche per un OP nuovo
    # non ancora creato, che nell'elenco degli OP non c'e').
    return (f"{reverse('apertura_segnalazione')}?op_id={quote(str(controllo.op_id or ''), safe='/')}"
            f"&controllo={controllo.pk}")


def _contatti_operatore(controllo) -> tuple[int | None, str]:
    """(id utente legacy, email di notifica) del controllore."""
    user = controllo.operatore
    if user is None:
        return None, ""
    legacy_id = None
    try:
        legacy_id = int(user.profile.legacy_user_id)
    except Exception:
        legacy_id = None
    email = ""
    if legacy_id:
        try:
            from core.legacy_models import AnagraficaDipendente

            a = AnagraficaDipendente.objects.filter(utente_id=legacy_id).only("email_notifica").first()
            email = str(getattr(a, "email_notifica", "") or "").strip()
        except Exception:
            logger.warning("controllo: email operatore non letta", exc_info=True)
    if not _EMAIL_RE.match(email):
        email = str(user.email or "").strip()
    return legacy_id, (email if _EMAIL_RE.match(email) else "")


def invia_promemoria_controllore(controllo, *, invio_auto_minuti: int | None = None) -> bool:
    """Ricorda al controllore che la mail al capocommessa non è ancora partita:
    notifica nel portale e mail con il riepilogo del controllo e il link per
    riprenderlo e premere «Termina controllo». Uno per pausa (``promemoria_at``)."""
    ids = [int(i) for i in (controllo.da_notificare or [])]
    righe = carica_righe(ids)
    rows = [righe[i] for i in ids if i in righe and not righe[i].get("chiudere")]
    controllo.promemoria_at = timezone.now()
    controllo.save(update_fields=["promemoria_at", "updated_at"])
    if not rows:
        return False

    from core.accounts.portal_links import portal_link

    n = len(rows)
    cosa = f"{n} anomali{'a' if n == 1 else 'e'}"
    url = url_controllo(controllo)
    link = portal_link(url) or url
    legacy_id, email = _contatti_operatore(controllo)
    fatto = False

    if legacy_id:
        try:
            from core.models import Notifica

            Notifica.objects.filter(
                legacy_user_id=legacy_id, tipo=TIPO_NOTIFICA_PROMEMORIA, url_azione=url, letta=False,
            ).update(letta=True)
            Notifica.objects.create(
                legacy_user_id=legacy_id,
                tipo=TIPO_NOTIFICA_PROMEMORIA,
                messaggio=(f"OP {controllo.op_id} · fase {controllo.fase}: {cosa} non ancora inviate al "
                           f"capocommessa. Riprendi il controllo e premi «Termina controllo».")[:500],
                url_azione=url,
            )
            fatto = True
        except Exception:
            logger.warning("controllo %s: notifica promemoria non creata", controllo.pk, exc_info=True)

    if email:
        try:
            from .mail_action_service import send_and_log_email

            gruppi = gruppi_per_blocco(rows)
            righe_testo = []
            for g in gruppi:
                righe_testo.append(f"  S/N {g.get('titolo') or '—'}")
                for r in g.get("righe") or []:
                    _stati, testo = separa_descrizione(r.get("descrizione"))
                    righe_testo.append(f"    • {testo or '—'}")
            from .escalation_config import durata_label, tempi_controllo

            minuti_auto = invio_auto_minuti or tempi_controllo()["invio_auto"]
            bozza_txt = (["", "C'è anche un blocco non ancora salvato (bozza salvata in automatico): lo ritrovi con «Riprendi»."]
                         if controllo.bozza else [])
            body = "\n".join([
                f"Il controllo dell'OP {controllo.op_id} (fase {controllo.fase}) ha {cosa} salvate ma la mail al "
                "capocommessa non è ancora partita.",
                "",
                "Riepilogo salvato:",
                *righe_testo,
                *bozza_txt,
                "",
                f"Riprendi il controllo e premi «Termina controllo» per inviarla: {link}",
                f"Se non lo fai, la mail partirà da sola {durata_label(minuti_auto)} dopo l'ultimo salvataggio.",
            ])
            ok, _log = send_and_log_email(
                kind="promemoria_controllo",
                subject=f"[Novicrom Hub] OP {controllo.op_id}: mail al capocommessa non ancora inviata",
                body_text=body,
                to=[email],
                op_id=controllo.op_id,
                context={"controllo_id": controllo.pk, "anomalie_count": n},
                fail_silently=True,
            )
            fatto = fatto or bool(ok)
        except Exception:
            logger.warning("controllo %s: mail promemoria non inviata", controllo.pk, exc_info=True)
    return fatto
