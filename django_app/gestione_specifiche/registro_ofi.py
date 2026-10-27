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
    "sistema_gestione": "Sistema di gestione / Audit",
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


_SEPARATORI_CODICE = (" ", "-", "–", ":", "·", "/", ",")


def processo_da_testo(testo: str, processi=None):
    """Processo del catalogo SGI indicato dal testo «Processo/area», se è uno solo.

    Vale il codice esatto, il nome esatto, oppure il codice in testa seguito da un
    separatore («PRC-07 - Produzione»). Più processi o nessuno: None (resta il testo).
    """
    testo = (testo or "").strip().lower()
    if not testo:
        return None
    if processi is None:
        try:
            from sistema_gestione.models import Processo
        except Exception:  # pragma: no cover - sistema_gestione non installata
            return None
        processi = Processo.objects.only("pk", "codice", "nome")
    trovati = {}
    for p in processi:
        codice = (p.codice or "").strip().lower()
        nome = (p.nome or "").strip().lower()
        if testo in (codice, nome, f"{codice} - {nome}") or (
                codice and testo.startswith(codice) and testo[len(codice):len(codice) + 1] in _SEPARATORI_CODICE):
            trovati[p.pk] = p
    return next(iter(trovati.values())) if len(trovati) == 1 else None


def collega_processo(voce) -> bool:
    """Allinea processo del catalogo e testo «Processo/area» della voce (senza salvare).

    Con il processo scelto e il testo vuoto il testo diventa «codice - nome»; senza
    processo lo si ricava dal testo. Ritorna True se ha cambiato qualcosa.
    """
    if voce.processo_sgi_id:
        if not (voce.processo or "").strip():
            voce.processo = str(voce.processo_sgi)[:200]
            return True
        return False
    trovato = processo_da_testo(voce.processo)
    if trovato is None:
        return False
    voce.processo_sgi = trovato
    return True


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

    spec = riga.mod133.specifica
    fields = dict(
        data_apertura=oggi, tipo=RegistroOFI.TIPO_OFI,
        norma_en9100=True, ref=spec.codice,
        processo=riga.tag_processo or "",
        opportunita=(riga.descrizione_impatto or riga.descrizione_modifiche or "")[:5000],
        modulo_origine="gestione_specifiche",
        content_type=ct, object_id=riga.id,
    )
    fixed = numero if numero is not None else riga.ofi
    if fixed:
        voce = RegistroOFI.objects.create(numero=fixed, **fields)
    else:
        # Audit S8: numero calcolato -> retry su collisione con un inserimento concorrente.
        from core.numbering_retry import save_with_next_number

        stato = {}

        def assign():
            stato["numero"] = prossimo_numero()

        voce = save_with_next_number(
            assign, lambda: RegistroOFI.objects.create(numero=stato["numero"], **fields))
    registra_evento(voce, "CREATA", a=voce.get_fase_display(), nota=f"Dalla specifica {spec.codice} (MOD.133)")
    return voce


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
        .select_related("responsabile")
        .filter(reminder_attivo=True, reminder_inviato=False,
                data_richiesta__isnull=False, data_richiesta__lte=limite,
                data_chiusura__isnull=True)
        .exclude(fase=RegistroOFI.FASE_CHIUSO)
        .order_by("data_richiesta", "numero")
    )


def _destinatari_reminder(voce=None) -> list[str]:
    """Destinatari del reminder OFI (best-effort, fail-safe): il responsabile della
    voce, se è un utente con email, più gli indirizzi configurati per la Qualità."""
    cfg = getattr(settings, "GESTIONE_SPECIFICHE", {}) or {}
    dest = cfg.get("OFI_REMINDER_EMAILS") or []
    if isinstance(dest, str):
        dest = [e.strip() for e in dest.replace(";", ",").split(",") if e.strip()]
    dest = list(dest)
    email = (getattr(getattr(voce, "responsabile", None), "email", "") or "").strip()
    if email and email.lower() not in {d.lower() for d in dest}:
        dest.insert(0, email)
    return dest


from automazioni.managed_flows import event_flow


@event_flow("gs_ofi_reminder", skipped_result={})
def invia_reminder_ofi(*, oggi=None, giorni: int = 0, dry_run: bool = False) -> dict:
    """Solleciti per le voci OFI in scadenza/scadute. Best-effort: l'email non
    deve mai bloccare (fail-safe); marca ``reminder_inviato`` sulle voci trattate.
    Ritorna ``{candidate, inviati, dry_run}``.
    """
    voci = voci_da_sollecitare(oggi=oggi, giorni=giorni)
    if dry_run:
        return {"candidate": len(voci), "inviati": 0, "dry_run": True}

    inviati = 0
    for v in voci:
        destinatari = _destinatari_reminder(v)
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
                           ("Responsabile", _nome_utente(v.responsabile)
                            or v.owner_processo or v.proprietario or "—")],
                )
            except Exception:  # pragma: no cover - il reminder non deve bloccare
                pass
        v.reminder_inviato = True
        v.save(update_fields=["reminder_inviato", "updated_at"])
        registra_evento(v, "SOLLECITO", nota=", ".join(destinatari) if destinatari else "nessun destinatario")
        inviati += 1
    return {"candidate": len(voci), "inviati": inviati, "dry_run": False}


# --- Cronologia, avanzamento PDCA e cruscotto --------------------------------

def _nome_utente(user) -> str:
    if user is None:
        return ""
    return (user.get_full_name() or user.get_username() or "").strip()


def registra_evento(voce, tipo: str, *, utente=None, da: str = "", a: str = "", nota: str = ""):
    """Aggiunge un evento alla cronologia della voce (unico punto di scrittura)."""
    from .models import RegistroOFIEvento
    if utente is not None and not getattr(utente, "is_authenticated", False):
        utente = None
    return RegistroOFIEvento.objects.create(
        voce=voce, tipo=tipo, utente=utente, da=str(da or "")[:150], a=str(a or "")[:150], nota=nota or "")


def fotografia(voce) -> dict:
    """Valori tracciati in cronologia, letti prima di una modifica."""
    return {"fase": voce.fase, "data_richiesta": voce.data_richiesta, "responsabile_id": voce.responsabile_id}


def _fmt_data(d) -> str:
    return d.strftime("%d/%m/%Y") if d else "—"


def registra_modifiche(prima: dict, voce, utente) -> None:
    """Confronta la fotografia ``prima`` con la voce salvata e scrive gli eventi."""
    from .models import RegistroOFI, RegistroOFIEvento as E
    fasi = dict(RegistroOFI.FASE_CHOICES)
    cambiato = False
    if prima["fase"] != voce.fase:
        registra_evento(voce, E.TIPO_FASE, utente=utente, da=fasi.get(prima["fase"], prima["fase"]),
                        a=fasi.get(voce.fase, voce.fase), nota="Dal modulo di modifica")
        cambiato = True
    if prima["data_richiesta"] != voce.data_richiesta:
        registra_evento(voce, E.TIPO_SCADENZA, utente=utente, da=_fmt_data(prima["data_richiesta"]),
                        a=_fmt_data(voce.data_richiesta))
        cambiato = True
    if prima["responsabile_id"] != voce.responsabile_id:
        from django.contrib.auth import get_user_model
        precedente = get_user_model().objects.filter(pk=prima["responsabile_id"]).first()
        registra_evento(voce, E.TIPO_RESPONSABILE, utente=utente, da=_nome_utente(precedente) or "—",
                        a=_nome_utente(voce.responsabile) or "—")
        cambiato = True
    if not cambiato:
        registra_evento(voce, E.TIPO_MODIFICA, utente=utente)


def car_aperta(voce):
    """Azione correttiva (MT CN 11) collegata e non ancora chiusa, se esiste."""
    car = car_collegata(voce)
    return car if car is not None and car.chiusa_il is None else None


def car_collegata(voce):
    """Azione correttiva (MT CN 11) collegata alla voce, aperta o chiusa; None se manca."""
    from django.core.exceptions import ObjectDoesNotExist
    try:
        return voce.car_procedurale
    except (ObjectDoesNotExist, AttributeError):  # nessuna CAR (o sistema_gestione non installata)
        return None


class AvanzamentoNonValido(Exception):
    pass


def avanza_fase(voce, *, utente, testo: str = "", oggi=None) -> str:
    """Porta la voce alla fase successiva del PDCA.

    Per lasciare una fase serve il testo di quella fase (PLAN, DO, CHECK, ACT): si
    può scrivere qui o trovarlo già compilato. Una voce con CAR aperta non si chiude
    dal registro: si chiude chiudendo la CAR. Ritorna la nuova fase.
    """
    from .models import RegistroOFI, RegistroOFIEvento as E
    if voce.is_chiuso:
        raise AvanzamentoNonValido("La voce è già chiusa.")
    campo = voce.campo_fase_corrente
    successiva = voce.fase_successiva
    if not campo or not successiva:
        raise AvanzamentoNonValido("Fase non riconosciuta.")
    testo = (testo or "").strip()
    if testo:
        setattr(voce, campo, testo)
    if not (getattr(voce, campo) or "").strip():
        raise AvanzamentoNonValido(
            f"Per chiudere la fase {voce.get_fase_display()} descrivi cosa è stato fatto.")
    if successiva == RegistroOFI.FASE_CHIUSO and car_aperta(voce) is not None:
        raise AvanzamentoNonValido(
            "C'è un'azione correttiva aperta: la voce si chiude quando si chiude la CAR, "
            "dopo la verifica di efficacia.")
    prima = voce.get_fase_display()
    voce.fase = successiva
    campi = ["fase", campo, "updated_at"]
    if successiva == RegistroOFI.FASE_CHIUSO:
        voce.data_chiusura = oggi or timezone.localdate()
        campi.append("data_chiusura")
    voce.save(update_fields=campi)
    registra_evento(voce, E.TIPO_FASE, utente=utente, da=prima, a=voce.get_fase_display(), nota=testo)
    return successiva


def riapri_non_efficace(voce, *, utente, motivo: str) -> None:
    """Verifica non superata: la voce torna in PLAN con il motivo in cronologia."""
    from .models import RegistroOFI, RegistroOFIEvento as E
    motivo = (motivo or "").strip()
    if not motivo:
        raise AvanzamentoNonValido("Scrivi perché la verifica non è superata.")
    if voce.fase not in (RegistroOFI.FASE_CHECK, RegistroOFI.FASE_ACT, RegistroOFI.FASE_CHIUSO):
        raise AvanzamentoNonValido("Si riapre solo una voce in verifica, consolidamento o chiusa.")
    prima = voce.get_fase_display()
    voce.fase = RegistroOFI.FASE_PLAN
    voce.data_chiusura = None
    voce.save(update_fields=["fase", "data_chiusura", "updated_at"])
    registra_evento(voce, E.TIPO_RIAPERTA, utente=utente, da=prima, a=voce.get_fase_display(), nota=motivo)


def _mese(d) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def cruscotto(qs=None, *, oggi=None) -> dict:
    """Numeri del cruscotto del registro, calcolati in Python sulle voci filtrate.

    Il registro ha al massimo poche migliaia di righe: un solo passaggio in memoria
    evita GROUP BY che si comportano diversamente su SQLite e SQL Server.
    """
    from collections import Counter

    from .models import RegistroOFI
    oggi = oggi or timezone.localdate()
    voci = list(qs if qs is not None else RegistroOFI.objects.all())
    aperte = [v for v in voci if not v.is_chiuso]
    chiuse = [v for v in voci if v.is_chiuso and v.data_chiusura]
    anno_fa = oggi - timedelta(days=365)

    fasce = [("Fino a 30 giorni", 0, 30), ("31-90 giorni", 31, 90), ("91-180 giorni", 91, 180),
             ("Oltre 180 giorni", 181, None)]
    anzianita = [{"etichetta": etichetta,
                  "n": sum(1 for v in aperte if v.giorni_aperta >= da and (a is None or v.giorni_aperta <= a))}
                 for etichetta, da, a in fasce]

    chiuse_anno = [v for v in chiuse if v.data_chiusura >= anno_fa]
    con_scadenza = [v for v in chiuse_anno if v.data_richiesta]
    in_tempo = sum(1 for v in con_scadenza if v.data_chiusura <= v.data_richiesta)

    norme = Counter()
    for v in aperte:
        for sigla in v.norme_sigle:
            norme[sigla] += 1

    # Ultimi 12 mesi, dal più vecchio: voci aperte e chiuse in ciascun mese.
    mesi = []
    y, m = oggi.year, oggi.month
    for _ in range(12):
        mesi.append(f"{y:04d}-{m:02d}")
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    mesi.reverse()
    aperte_mese = Counter(_mese(v.data_apertura) for v in voci if v.data_apertura)
    chiuse_mese = Counter(_mese(v.data_chiusura) for v in chiuse)
    andamento = [{"mese": k, "etichetta": f"{k[5:]}/{k[2:4]}", "aperte": aperte_mese.get(k, 0),
                  "chiuse": chiuse_mese.get(k, 0)} for k in mesi]
    massimo = max([1] + [max(r["aperte"], r["chiuse"]) for r in andamento])
    for r in andamento:
        r["h_aperte"] = round(r["aperte"] / massimo * 100)
        r["h_chiuse"] = round(r["chiuse"] / massimo * 100)

    ricorrenti = Counter((v.processo or "").strip() for v in voci
                         if v.data_apertura and v.data_apertura >= anno_fa and (v.processo or "").strip())

    def top(counter, n=10):
        return [{"nome": k, "n": c} for k, c in counter.most_common(n)]

    return {
        "totale": len(voci),
        "aperte": len(aperte),
        "nc_aperte": sum(1 for v in aperte if v.tipo == RegistroOFI.TIPO_NC),
        "scadute": sum(1 for v in aperte if v.is_scaduto),
        "senza_responsabile": sum(1 for v in aperte if v.responsabile_id is None),
        "senza_scadenza": sum(1 for v in aperte if v.data_richiesta is None),
        "per_fase": [{"chiave": key, "nome": label, "n": sum(1 for v in aperte if v.fase == key)}
                     for key, label in RegistroOFI.FASE_CHOICES if key != RegistroOFI.FASE_CHIUSO],
        "anzianita": anzianita,
        "chiuse_anno": len(chiuse_anno),
        "giorni_medi_chiusura": (round(sum(v.giorni_aperta for v in chiuse_anno) / len(chiuse_anno))
                                 if chiuse_anno else None),
        "pct_in_tempo": round(in_tempo / len(con_scadenza) * 100) if con_scadenza else None,
        "per_processo": top(Counter((v.processo or "").strip() or "—" for v in aperte)),
        "per_fonte": top(Counter((v.fonte or "").strip() or "—" for v in aperte)),
        "per_norma": top(norme),
        "ricorrenti": [r for r in top(ricorrenti, 20) if r["n"] >= 3],
        "andamento": andamento,
    }
