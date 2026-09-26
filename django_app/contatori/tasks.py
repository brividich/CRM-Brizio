"""Job per lo scheduler django-q2 esistente del portale."""
from datetime import date

from django.core.cache import cache
from django.utils import timezone
from django_q.tasks import async_task

from .models import DispositivoSNMP, LetturaMensileContatori, Macchina, StatoSNMP
from .services import interroga_dispositivo, leggi_mensile_macchina


def _enqueue(func, pk, *args):
    # Lock della coda: impedisce di accumulare lo stesso apparato a ogni tick.
    key = f"contatori:queued:{func}:{pk}"
    if not cache.add(key, True, timeout=3600):
        return False
    try:
        async_task(func, pk, *args, q_options={"timeout": 110})
    except Exception:
        cache.delete(key)
        raise
    return True


def run_poll_snmp():
    """Smista i dispositivi in job indipendenti entro il timeout del cluster."""
    queued = sum(
        _enqueue("contatori.tasks.poll_dispositivo", pk)
        for pk in DispositivoSNMP.objects.filter(attivo=True).values_list("pk", flat=True)
    )
    return {"accodati": queued}


def poll_dispositivo(pk):
    key = f"contatori:queued:contatori.tasks.poll_dispositivo:{pk}"
    try:
        dispositivo = DispositivoSNMP.objects.filter(pk=pk, attivo=True).first()
        if dispositivo is None:
            return {"saltato": True}
        rilevazione = interroga_dispositivo(dispositivo)
        if rilevazione.stato == StatoSNMP.ERROR:
            # Dettagli nello storico del dispositivo; errore visibile anche in django-q.
            raise RuntimeError(f"Polling SNMP fallito per dispositivo {pk}; consultare il monitor.")
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
    return {"mese": mese.isoformat(), "accodati": queued}


def leggi_mensile(pk, mese):
    key = f"contatori:queued:contatori.tasks.leggi_mensile:{pk}"
    try:
        macchina = Macchina.objects.filter(pk=pk, attiva=True).first()
        if macchina is None or not macchina.host:
            return {"saltato": True}
        lettura, creata = leggi_mensile_macchina(macchina, mese=date.fromisoformat(mese))
        return {"lettura_id": lettura.pk, "creata": creata}
    finally:
        cache.delete(key)
