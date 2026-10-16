"""«Conservazione dei dati»: eliminazione confermata dei dati HR oltre la retention.

Solo amministratori dell'anagrafica. La pagina mostra i documenti dei dipendenti
cessati oltre gli anni di conservazione e i candidati chiusi fermi da oltre 24
mesi (stesso calcolo del report settimanale, ``services/retention.py``). Si
scelgono le righe e si conferma scrivendo ``ELIMINA``: i documenti vengono
eliminati (file compreso), i candidati resi anonimi. Ogni riga è ricontrollata
lato server al momento dell'azione e registrata nel registro attività.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render

from core import naming
from core.legacy_anagrafica import fetch_anagrafica_rows

PAROLA_CONFERMA = "ELIMINA"


def _solo_admin(request) -> bool:
    from anagrafica.views import _ensure_admin

    return bool(_ensure_admin(request)[1])


@login_required
def retention(request):
    from anagrafica.services import retention as svc

    if not _solo_admin(request):
        return HttpResponseForbidden("Solo gli amministratori dell'anagrafica gestiscono la conservazione dei dati.")

    if request.method == "POST":
        azione = request.POST.get("azione", "")
        ids = [i for i in request.POST.getlist("ids") if str(i).isdigit()]
        if request.POST.get("conferma", "").strip().upper() != PAROLA_CONFERMA:
            messages.error(request, f"Per procedere scrivi {PAROLA_CONFERMA} nella casella di conferma.")
        elif not ids:
            messages.error(request, "Nessuna riga selezionata.")
        elif azione == "documenti":
            esito = svc.elimina_documenti(request, ids)
            messages.success(request, f"Documenti eliminati: {esito['eliminati']}"
                                      + (f" · saltati (non più oltre la conservazione): {esito['saltati']}" if esito["saltati"] else "")
                                      + (f" · errori: {esito['errori']}" if esito["errori"] else "") + ".")
        elif azione == "candidati":
            esito = svc.anonimizza_candidati(request, ids)
            messages.success(request, f"Candidati resi anonimi: {esito['anonimizzati']}"
                                      + (f" · saltati: {esito['saltati']}" if esito["saltati"] else "") + ".")
        return redirect("anagrafica:retention")

    documenti = svc.documenti_scaduti().da_eliminare
    ids = sorted({doc.legacy_anagrafica_id for doc, _c in documenti})
    nomi = {int(r["id"]): naming.nome_completo(r.get("nome"), r.get("cognome"))
            for r in fetch_anagrafica_rows(ids=ids)} if ids else {}
    righe_doc = [{
        "id": doc.pk, "persona": nomi.get(doc.legacy_anagrafica_id) or f"#{doc.legacy_anagrafica_id}",
        "tipo": doc.get_tipo_display(), "file": doc.nome_originale or "—",
        "caricato": doc.created_at, "cessazione": cessazione, "retention": doc.retention_until,
    } for doc, cessazione in documenti]
    candidati = list(svc.candidati_scaduti().select_related("posizione"))
    return render(request, "anagrafica/pages/retention.html", {
        "righe_doc": righe_doc,
        "candidati": candidati,
        "mesi_candidati": svc.MESI_CONSERVAZIONE_CANDIDATI,
        "parola": PAROLA_CONFERMA,
    })
