"""Discovery a blocchi persistenti sul cluster esistente, senza credenziali in coda."""
from django.db import transaction
from django.utils import timezone
from django_q.tasks import async_task

from .credential_crypto import decifra
from .models import CommunitySNMP, DiscoverySNMP, ImpostazioniSNMP
from .snmp import scansiona_hosts

BATCH_SIZE = 16


def accoda(pk, revisione):
    try:
        async_task("contatori.discovery_jobs.esegui_batch", str(pk), revisione,
                   q_options={"timeout": 60, "ack_failure": True})
    except Exception:
        DiscoverySNMP.objects.filter(pk=pk, revisione=revisione,
                                     stato=DiscoverySNMP.Stato.ATTESA).update(
            stato=DiscoverySNMP.Stato.ERRORE, aggiornata_il=timezone.now(),
            errore="Accodamento non riuscito. Verifica il servizio e premi Riprendi.")


def dopo_commit(scan):
    pk, revisione = scan.pk, scan.revisione
    transaction.on_commit(lambda: accoda(pk, revisione))


def interrompi(scan):
    return DiscoverySNMP.objects.filter(pk=scan.pk, revisione=scan.revisione,
                                        stato__in=[scan.Stato.ATTESA, scan.Stato.CORSO]).update(
        stato=scan.Stato.ANNULLATA, revisione=scan.revisione + 1,
        aggiornata_il=timezone.now(), errore="Interrotta su richiesta; risultati conservati.")


def riprendi(scan):
    if not scan.riprendibile:
        return False
    updated = DiscoverySNMP.objects.filter(pk=scan.pk, revisione=scan.revisione,
                                           stato=scan.stato, aggiornata_il=scan.aggiornata_il).update(
        stato=scan.Stato.ATTESA, revisione=scan.revisione + 1,
        aggiornata_il=timezone.now(), errore="")
    if updated:
        scan.refresh_from_db()
        dopo_commit(scan)
    return bool(updated)


def esegui_batch(pk, revisione):
    # Compare-and-swap: un solo worker puo acquisire la generazione corrente.
    query = DiscoverySNMP.objects.filter(pk=pk, revisione=revisione)
    if not query.filter(stato=DiscoverySNMP.Stato.ATTESA).update(
            stato=DiscoverySNMP.Stato.CORSO, aggiornata_il=timezone.now()):
        return {"saltato": True}
    scan = query.filter(stato=DiscoverySNMP.Stato.CORSO).first()
    if scan is None:  # Interruzione/ripresa fra acquisizione e lettura.
        return {"saltato": True}
    owned = query.filter(stato=DiscoverySNMP.Stato.CORSO)
    try:
        community_id = scan.community_ids[scan.candidata]
        versione, porta = scan.versione, scan.porta
        if community_id == 0:
            credential = ImpostazioniSNMP.get_solo().community
            nome = "Globale"
        else:
            community = CommunitySNMP.objects.get(pk=community_id, attiva=True)
            credential = decifra(community.segreto_cifrato)
            nome = community.nome
            versione = community.versione or versione
            porta = community.porta or porta

        batch = scan.hosts[scan.cursore:scan.cursore + BATCH_SIZE]
        found = {row["host"]: row for row in scan.risultati}
        pending = [host for host in batch if host not in found]
        rows = scansiona_hosts(pending, community=credential, version=versione,
                              port=porta, timeout=scan.timeout,
                              concurrency=BATCH_SIZE, max_duration=35) if pending else []
        for row in rows:
            # Whitelist dei campi: nessun segreto o eccezione del trasporto nel DB.
            found[row["host"]] = {
                key: str(row.get(key, ""))[:2000]
                for key in ("host", "descr", "nome", "matricola")
            }
            found[row["host"]].update(community_nome=nome, community_id=community_id,
                                      community_index=scan.candidata + 1,
                                      versione=versione, porta=porta)

        incomplete = getattr(rows, "incompleta", False)
        if not incomplete:
            if all(host in found for host in batch) or scan.candidata + 1 == len(scan.community_ids):
                scan.cursore += len(batch)
                scan.candidata = 0
            else:
                scan.candidata += 1
        current_batch = scan.hosts[scan.cursore:scan.cursore + BATCH_SIZE]
        completed = scan.cursore + sum(host in found for host in current_batch)
        state = scan.Stato.COMPLETA if scan.cursore == len(scan.hosts) else scan.Stato.ATTESA
        if incomplete:
            state = scan.Stato.ERRORE
        updated = owned.update(
            risultati=list(found.values()), completati=completed,
            cursore=scan.cursore, candidata=scan.candidata,
            stato=state, revisione=revisione + 1, aggiornata_il=timezone.now(),
            errore="Blocco oltre il tempo massimo. Risultati conservati; premi Riprendi." if incomplete else "")
        if updated and state == scan.Stato.ATTESA:
            accoda(pk, revisione + 1)
        return {"salvato": bool(updated), "completati": completed}
    except Exception:
        # Non propagare messaggi del trasporto/decifratura nei log di django-q.
        owned.update(stato=scan.Stato.ERRORE, aggiornata_il=timezone.now(),
                     errore="Blocco non completato. Verifica community attive, parametri e servizio; poi Riprendi.")
        return {"errore": True}
