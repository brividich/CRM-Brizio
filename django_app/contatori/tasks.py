"""Job per lo scheduler django-q2 esistente del portale."""
import logging
from datetime import date, timedelta

from django.core.cache import cache
from django.utils import timezone
from django_q.tasks import async_task

from .models import (
    DispositivoSNMP, ImpostazioniSNMP, LetturaMensileContatori, Macchina, RilevazioneSNMP, StatoSNMP,
)
from .services import interroga_dispositivo, leggi_mensile_macchina
from .snmp import SNMPError

logger = logging.getLogger(__name__)

# Audit S9: poco oltre il timeout del task (110 s) e un'attesa in coda ragionevole.
# Con 3600 s un worker ucciso lasciava l'apparato senza letture per un'ora.
_QUEUE_LOCK_SECONDS = 240


def _enqueue(func, pk, *args):
    # Lock della coda: impedisce di accumulare lo stesso apparato a ogni tick.
    key = f"contatori:queued:{func}:{pk}"
    if not cache.add(key, True, timeout=_QUEUE_LOCK_SECONDS):
        return False
    try:
        async_task(func, pk, *args, q_options={"timeout": 110})
    except Exception:
        cache.delete(key)
        raise
    return True


# Tolleranza sull'intervallo TVCC: il giro parte ogni 5 minuti ma non al secondo,
# senza margine una telecamera a 30 minuti verrebbe letta ogni 35.
_TOLLERANZA_INTERVALLO = timedelta(seconds=150)


def _dispositivi_da_interrogare(adesso=None):
    """Dispositivi attivi dovuti in questo giro: i TVCC rispettano il proprio intervallo."""
    adesso = adesso or timezone.now()
    cfg = ImpostazioniSNMP.get_solo()
    intervalli = {
        DispositivoSNMP.Categoria.TVCC_NVR: cfg.tvcc_intervallo_nvr,
        DispositivoSNMP.Categoria.TVCC_TELECAMERA: cfg.tvcc_intervallo_telecamere,
    }
    dovuti = []
    for pk, categoria, ultimo in DispositivoSNMP.objects.filter(attivo=True).values_list(
        "pk", "categoria", "snmp_ultimo_controllo",
    ):
        minuti = intervalli.get(categoria)
        if minuti and ultimo and ultimo > adesso - timedelta(minutes=minuti) + _TOLLERANZA_INTERVALLO:
            continue
        dovuti.append(pk)
    return dovuti


def _mfc_da_leggere(adesso=None):
    """MFC a contratto con IP la cui lettura completa (avvisi, cassetti, toner) è più vecchia di 15 minuti."""
    from django.db.models import Q

    from .stampanti import INTERVALLO_MFC_MINUTI

    adesso = adesso or timezone.now()
    limite = adesso - timedelta(minutes=INTERVALLO_MFC_MINUTI) + _TOLLERANZA_INTERVALLO
    pks = Macchina.objects.filter(attiva=True, host__isnull=False).filter(
        Q(dati_stampante_il__isnull=True) | Q(dati_stampante_il__lte=limite)).values_list("pk", flat=True)
    # Una MFC spenta (la notte) si riprova dopo 15 minuti, non a ogni giro di 5.
    return [pk for pk in pks if not cache.get(f"contatori:mfc_ko:{pk}")]


def run_poll_snmp():
    """Smista dispositivi e MFC in job indipendenti entro il timeout del cluster."""
    queued = sum(
        _enqueue("contatori.tasks.poll_dispositivo", pk)
        for pk in _dispositivi_da_interrogare()
    )
    mfc = sum(_enqueue("contatori.tasks.poll_stampante_mfc", pk) for pk in _mfc_da_leggere())
    return {"accodati": queued, **({"mfc": mfc} if mfc else {})}


def poll_stampante_mfc(pk):
    from .stampanti import INTERVALLO_MFC_MINUTI, leggi_stato_mfc

    key = f"contatori:queued:contatori.tasks.poll_stampante_mfc:{pk}"
    try:
        macchina = Macchina.objects.filter(pk=pk, attiva=True).first()
        if macchina is None or not macchina.host:
            return {"saltato": True}
        dati = leggi_stato_mfc(macchina)
        if dati is None:
            cache.add(f"contatori:mfc_ko:{pk}", True, timeout=INTERVALLO_MFC_MINUTI * 60)
        return {"macchina_id": pk, "letta": dati is not None}
    finally:
        cache.delete(key)


_BLOCCO_PULIZIA = 500

# Storico delle rilevazioni SNMP degli apparati non TVCC (stampanti, switch, server...).
# Chiave SiteConfig, impostata da Contatori › Impostazioni. 0 = conserva tutto (di serie).
CHIAVE_STORICO_SNMP = "contatori.snmp_retention_giorni"
# Sotto i 60 giorni le stime dei toner (``stampanti.GIORNI_STIME``) perderebbero lo storico.
STORICO_SNMP_MINIMO_GIORNI = 60
# La pulizia notturna non supera questo tempo: quello che resta si cancella la notte dopo.
_BUDGET_PULIZIA_SECONDI = 90.0


def storico_snmp_giorni() -> int:
    """Giorni di storico delle rilevazioni SNMP non TVCC; 0 = conserva tutto."""
    from core.models import SiteConfig

    try:
        giorni = int(str(SiteConfig.get(CHIAVE_STORICO_SNMP, "0") or "0").strip())
    except (TypeError, ValueError):
        return 0
    if giorni <= 0:
        return 0
    return max(giorni, STORICO_SNMP_MINIMO_GIORNI)


def pulisci_rilevazioni_storico(adesso=None, budget=_BUDGET_PULIZIA_SECONDI):
    """Cancella le rilevazioni SNMP non TVCC oltre lo storico impostato (spento di serie).

    L'ultima rilevazione di ogni dispositivo resta sempre (scheda, KPI e monitoraggio la
    leggono). A blocchi e con un tempo massimo: un primo giro su anni di storico prosegue
    nelle notti successive.
    """
    from time import monotonic

    from django.db.models import Max

    giorni = storico_snmp_giorni()
    if not giorni:
        return {"attivo": False, "giorni": 0, "cancellate": 0}
    limite = (adesso or timezone.now()) - timedelta(days=giorni)
    fine = monotonic() + max(0.0, budget)
    ultime = set(RilevazioneSNMP.objects.order_by().values("dispositivo_id").annotate(ultima=Max("pk"))
                 .values_list("ultima", flat=True))
    vecchie = RilevazioneSNMP.objects.exclude(
        dispositivo__categoria__in=DispositivoSNMP.CATEGORIE_TVCC).filter(rilevata_il__lt=limite)
    cancellate, ultimo_pk, completa = 0, 0, True
    while True:
        if monotonic() > fine:
            completa = False
            break
        blocco = list(vecchie.filter(pk__gt=ultimo_pk).order_by("pk").values_list("pk", flat=True)[:_BLOCCO_PULIZIA])
        if not blocco:
            break
        ultimo_pk = blocco[-1]
        da_cancellare = [pk for pk in blocco if pk not in ultime]
        if da_cancellare:
            cancellate += RilevazioneSNMP.objects.filter(pk__in=da_cancellare).delete()[1].get(
                RilevazioneSNMP._meta.label, 0)
    esito = {"attivo": True, "giorni": giorni, "cancellate": cancellate}
    if not completa:
        esito["da_completare"] = "Tempo della pulizia esaurito: il resto si cancella la notte prossima."
    return esito


def pulisci_rilevazioni_tvcc():
    """Cancella le rilevazioni SNMP dei dispositivi TVCC oltre la retention impostata.

    Solo NVR e telecamere; per gli altri apparati c'è lo storico facoltativo
    (``pulisci_rilevazioni_storico``, spento di serie). Lo stato corrente resta sul dispositivo. A blocchi, per non tenere
    una transazione enorme su SQL Server.
    """
    from time import monotonic

    inizio = monotonic()
    giorni = ImpostazioniSNMP.get_solo().tvcc_retention_giorni
    limite = timezone.now() - timedelta(days=giorni)
    vecchie = RilevazioneSNMP.objects.filter(
        dispositivo__categoria__in=DispositivoSNMP.CATEGORIE_TVCC, rilevata_il__lt=limite,
    )
    cancellate = 0
    while True:
        blocco = list(vecchie.order_by("pk").values_list("pk", flat=True)[:_BLOCCO_PULIZIA])
        if not blocco:
            break
        cancellate += RilevazioneSNMP.objects.filter(pk__in=blocco).delete()[1].get(
            RilevazioneSNMP._meta.label, 0)
    esito = {"giorni": giorni, "cancellate": cancellate}
    try:
        # Lo stesso job (timeout 120 s) fa le due pulizie: la seconda usa il tempo che resta.
        storico = pulisci_rilevazioni_storico(budget=_BUDGET_PULIZIA_SECONDI - (monotonic() - inizio))
    except Exception:  # noqa: BLE001 - la pulizia TVCC resta valida anche se l'altra fallisce
        logger.exception("contatori: pulizia storico rilevazioni SNMP non riuscita")
        storico = {"errore": True}
    if storico.get("attivo") or storico.get("errore"):
        esito["storico_altri"] = storico
    return esito


def poll_dispositivo(pk):
    key = f"contatori:queued:contatori.tasks.poll_dispositivo:{pk}"
    try:
        dispositivo = DispositivoSNMP.objects.filter(pk=pk, attivo=True).first()
        if dispositivo is None:
            return {"saltato": True}
        rilevazione = interroga_dispositivo(dispositivo)
        if rilevazione.stato == StatoSNMP.ERROR:
            # Apparato spento o irraggiungibile: stato ed errore restano nello storico del
            # dispositivo (monitor). Non è un guasto del task: niente eccezione, che
            # riempiva i «task falliti» del qcluster coprendo i guasti veri.
            return {"dispositivo_id": pk, "stato": rilevazione.stato, "non_raggiungibile": True}
        return {"dispositivo_id": pk, "stato": rilevazione.stato}
    finally:
        cache.delete(key)


def run_letture_mensili():
    mese = timezone.localdate().replace(day=1)
    macchine = Macchina.objects.filter(attiva=True, host__isnull=False)
    presenti = LetturaMensileContatori.objects.filter(mese=mese).values_list("macchina_id", flat=True)
    queued = sum(
        _enqueue("contatori.tasks.leggi_mensile", pk, mese.isoformat())
        for pk in macchine.exclude(pk__in=presenti).values_list("pk", flat=True)
    )
    from .mail_mensile import e_ultimo_giro
    return {"mese": mese.isoformat(), "accodati": queued,
            "mail": _notifica_mensile(mese, ultimo_giro=e_ultimo_giro())}


def _notifica_mensile(mese, *, ultimo_giro=False):
    """Mail di riepilogo delle letture mensili: un errore di invio non fa fallire la lettura."""
    from .mail_mensile import notifica
    try:
        return notifica(mese, ultimo_giro=ultimo_giro)
    except Exception:
        logger.exception("contatori: invio mail letture mensili %s non riuscito", mese)
        return "errore"


def leggi_mensile(pk, mese):
    key = f"contatori:queued:contatori.tasks.leggi_mensile:{pk}"
    try:
        macchina = Macchina.objects.filter(pk=pk, attiva=True).first()
        if macchina is None or not macchina.host:
            return {"saltato": True}
        try:
            lettura, creata = leggi_mensile_macchina(macchina, mese=date.fromisoformat(mese))
        except SNMPError as exc:
            # Spenta o in sospensione: stato ed errore restano sulla macchina,
            # il recupero (ogni 15 minuti fino al giorno 7) la rilegge appena risponde.
            return {"macchina_id": pk, "non_raggiungibile": True, "errore": str(exc)[:200]}
        esito = {"lettura_id": lettura.pk, "creata": creata}
        if creata:
            esito["mail"] = _notifica_mensile(lettura.mese)
        return esito
    finally:
        cache.delete(key)


def run_letture_consumabili():
    """Lettura giornaliera dei consumabili: un job per MFC attiva con IP."""
    queued = sum(
        _enqueue("contatori.tasks.leggi_consumabili", pk)
        for pk in Macchina.objects.filter(attiva=True, host__isnull=False).values_list("pk", flat=True)
    )
    return {"accodati": queued}


def leggi_consumabili(pk):
    from .services import leggi_consumabili_macchina, salva_consumabili

    from .lettura_ora import registra_esito

    key = f"contatori:queued:contatori.tasks.leggi_consumabili:{pk}"
    riuscita = False
    try:
        macchina = Macchina.objects.filter(pk=pk, attiva=True).first()
        if macchina is None or not macchina.host:
            return {"saltato": True}
        consumabili, errore = leggi_consumabili_macchina(macchina)
        if errore:
            # Esito «non riuscita» registrato nel finally e mostrato nella pagina Consumabili.
            return {"macchina_id": pk, "non_raggiungibile": True}
        salvati = salva_consumabili(macchina, consumabili)
        riuscita = True
        return {"macchina_id": pk, "salvati": salvati}
    finally:
        registra_esito(pk, ok=riuscita)
        cache.delete(key)


def run_tabella_mac():
    """Tabella MAC degli switch «Rete» (``contatori.tabella_mac``): su quale porta sta ogni PC."""
    try:
        from security.services import letture
    except ImportError:  # SOC non installato
        from .tabella_mac import run

        return run()
    return letture.esegui("tabella_mac")
