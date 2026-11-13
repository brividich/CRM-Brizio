"""Le risposte delle API PHP del chiosco, calcolate qui. ``fornitori.chiosco`` non vede differenze."""
from __future__ import annotations

from django.utils import timezone

from . import informativa, servizi
from .models import CategoriaVisita, ContattoDitta, DittaAccreditata, Ospite, Preregistrazione, Referente, Visita


def _ingresso_ok(visita: Visita) -> tuple[int, dict]:
    return 200, {"success": True, "visit_id": visita.pk, "badge_number": visita.cartellino,
                 "guest_name": visita.ospite.nome_completo, "host_employee": visita.referente_nome}


def _esegui_ingresso(funzione) -> tuple[int, dict]:
    try:
        return _ingresso_ok(funzione())
    except servizi.GiaDentro:
        return 409, {"success": False, "already_in": True}
    except servizi.CartelliniFiniti:
        return 503, {"success": False, "no_badges": True}
    except servizi.EmailDiAltri:
        return 422, {"success": False, "email_conflict": True}


def foto_versioni(dipendenti_ids) -> dict[int, str]:
    """Versione della foto dell'anagrafica per dipendente (``anagrafica_dipendenti.id``): solo chi ha una foto."""
    ids = [i for i in dipendenti_ids if i]
    if not ids:
        return {}
    from anagrafica.models import DipendenteAnagraficaCivile
    from anagrafica.views.dipendenti import _foto_versione

    return {lid: _foto_versione(nome) for lid, nome in DipendenteAnagraficaCivile.objects
            .filter(legacy_anagrafica_id__in=ids).exclude(foto="").values_list("legacy_anagrafica_id", "foto")}


def _employees(_dati, _ip):
    referenti = list(Referente.objects.filter(attivo=True))
    try:
        foto = foto_versioni(r.dipendente_id for r in referenti)
    except Exception:  # noqa: BLE001 - senza foto il chiosco mostra le iniziali
        foto = {}
    return 200, {"success": True, "data": [
        {"EmployeeID": r.pk, "FullName": r.nome_elenco, "Email": r.email, "Department": r.reparto,
         "Photo": foto.get(r.dipendente_id, ""), "LegacyID": r.dipendente_id}
        for r in referenti
    ]}


def _guest_lookup(dati, _ip):
    o = servizi.trova_ospite_per_email(dati.get("email"))
    if o is None:
        return 200, {"found": False}
    return 200, {"found": True, "guest": {"FirstName": o.nome, "LastName": o.cognome, "Email": o.email,
                                          "Phone": o.telefono, "Company": o.azienda}}


def _checkin_submit(dati, ip):
    def fatto():
        noto = Ospite.objects.filter(pk=dati.get("guest_id"), anonimizzato=False).first() if dati.get("guest_id") else None
        if noto is not None:
            if dati.get("gdpr_consent") is not False or not informativa.gia_accettata(noto):
                noto.save(update_fields=[*informativa.registra(noto, ip), "aggiornato_il"])
            return servizi.registra_ingresso(noto, referente_nome=dati["host_employee"],
                                             referente_email=dati.get("host_email", ""), motivo=dati.get("purpose", ""))
        ospite = servizi.ospite_da_dati(nome=dati["first_name"], cognome=dati["last_name"], email=dati.get("email", ""),
                                        telefono=dati.get("phone", ""), azienda=dati.get("company", ""), ip=ip)
        return servizi.registra_ingresso(ospite, referente_nome=dati["host_employee"],
                                         referente_email=dati.get("host_email", ""), motivo=dati.get("purpose", ""))
    return _esegui_ingresso(fatto)


def _supplier_lookup(dati, _ip):
    if dati.get("action") == "suppliers":
        return 200, {"success": True, "suppliers": [
            {"SupplierID": d.pk, "CompanyName": d.nome} for d in DittaAccreditata.objects.filter(attiva=True)
        ]}
    return 200, {"success": True, "contacts": [
        {"ContactID": c.pk, "FirstName": c.nome, "LastName": c.cognome}
        for c in ContattoDitta.objects.filter(ditta_id=dati.get("supplier_id"), attivo=True)
    ]}


def _supplier_checkin(dati, ip):
    def fatto():
        ditta = DittaAccreditata.objects.get(pk=dati["supplier_id"])
        contatto = ContattoDitta.objects.get(pk=dati["contact_id"], ditta=ditta)
        ospite = servizi.ospite_fornitore(nome=dati["first_name"], cognome=dati["last_name"], azienda=ditta.nome, ip=ip,
                                          informativa=dati.get("gdpr_consent") is not False)
        return servizi.registra_ingresso(ospite, referente_nome=dati["host_employee"], referente_email=dati.get("host_email", ""),
                                         motivo=ditta.nome, tipo=Visita.FORNITORE, ditta=ditta, contatto=contatto,
                                         creata_da="FORNITORE")
    return _esegui_ingresso(fatto)


def _checkout_lookup(dati, _ip):
    aperte = Visita.objects.select_related("ospite").filter(stato=Visita.DENTRO)
    if dati.get("badge"):
        trovate = aperte.filter(cartellino=dati["badge"])
    else:
        pre = Preregistrazione.objects.filter(codice=dati.get("code", ""), visita__isnull=False).first()
        trovate = aperte.filter(pk=pre.visita_id) if pre else aperte.none()
    visite = [
        {"visit_id": v.pk, "badge_number": v.cartellino, "guest_name": v.ospite.nome_completo,
         "checkin_time": timezone.localtime(v.ingresso).strftime("%Y-%m-%d %H:%M:%S") if v.ingresso else None}
        for v in trovate.order_by("-ingresso")[:10]
    ]
    return 200, ({"success": True, "visits": visite} if visite else {"success": False})


def _checkout_submit(dati, _ip):
    try:
        v = servizi.registra_uscita(int(dati["visit_id"]), cartellino=str(dati["badge"]))
    except servizi.OperazioneNonValida:
        return 200, {"success": False}
    minuti = max(0, int((v.uscita - v.ingresso).total_seconds() // 60)) if v.ingresso else 0
    durata = " ".join(p for p in (f"{minuti // 60}h" if minuti >= 60 else "", f"{minuti % 60}min" if minuti % 60 else "") if p)
    return 200, {"success": True, "duration": durata or "Meno di 1 min"}


def _prereg_lookup(dati, _ip):
    p = servizi.preregistrazione_valida(dati.get("code"))
    if p is None:
        return 200, {"success": False}
    return 200, {"success": True, "prereg": {"guest_name": p.ospite_nome, "guest_company": p.ospite_azienda,
                                             "host_employee": p.referente_nome, "purpose": p.motivo,
                                             "privacy_ok": informativa.gia_accettata(servizi.ospite_del_codice(p))}}


def _prereg_checkin(dati, ip):
    def fatto():
        visita = servizi.ingresso_da_codice(dati.get("code"), ip=ip, informativa=dati.get("gdpr_consent") is not False)
        if visita is None:
            raise servizi.OperazioneNonValida
        return visita
    try:
        return _esegui_ingresso(fatto)
    except servizi.OperazioneNonValida:
        return 200, {"success": False}


_API = {
    "employees": _employees, "guest_lookup": _guest_lookup, "checkin_submit": _checkin_submit,
    "supplier_lookup": _supplier_lookup, "supplier_checkin": _supplier_checkin,
    "checkout_lookup": _checkout_lookup, "checkout_submit": _checkout_submit,
    "prereg_lookup": _prereg_lookup, "prereg_checkin": _prereg_checkin,
}


def chiama(nome_api: str, dati: dict | None, ip: str = "") -> tuple[int, dict]:
    return _API[nome_api](dati or {}, ip)


def categorie() -> list[dict]:
    return [{"nome": c.nome, "icona": c.icona} for c in CategoriaVisita.objects.filter(attiva=True)]
