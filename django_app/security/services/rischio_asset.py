"""Il rischio di un PC o server in una riga: CVE, sistema operativo, backup, dotazione, amministratori, hardware.

Niente punteggio: un livello e l'elenco dei motivi, così si capisce da dove viene e cosa fare. I numeri
vengono dalle stesse funzioni delle altre pagine (``cve_pannello``, ``software_catalog``, ``software_dotazione``,
``accessi_admin``, ``hardware_vita``).

Fine del supporto: ``windows_build.BUILD_RELEASE`` tiene la data più lunga (LTSC, ESU), che serve a non
escludere CVE. Qui serve la data che vale davvero per il PC, quindi Home e Pro hanno la propria.
"""
from __future__ import annotations

from datetime import date, timedelta

from django.utils import timezone

from security.models import SecurityAssetSignal, SoftwareInstallation
from security.services import windows_build as wb

# Fine degli aggiornamenti per Home e Pro. Fonte: Microsoft Lifecycle, da aggiornare a ogni nuova release.
FINE_HOME_PRO = {
    19045: date(2025, 10, 14),  # Windows 10 22H2 (oltre, solo con ESU)
    22000: date(2023, 10, 10),
    22621: date(2024, 10, 8),
    22631: date(2025, 11, 11),
    26100: date(2026, 10, 13),
    26200: date(2027, 10, 12),
}
GIORNI_PREAVVISO = 90
_EDIZIONE_HOME_PRO = (" home", " pro")
_NON_HOME_PRO = (" pro education", " pro for workstations")

ALTO, MEDIO, NESSUNO, NON_VALUTABILE = "alto", "medio", "nessuno", "non_valutabile"
ETICHETTE = {ALTO: "Rischio alto", MEDIO: "Rischio medio", NESSUNO: "Nessun problema noto", NON_VALUTABILE: "Non valutabile"}


def _fine_supporto(famiglia, build, prodotto):
    voce = wb.BUILD_RELEASE.get(famiglia, {}).get(build)
    if famiglia == wb.CLIENT and build in FINE_HOME_PRO:
        nome = f" {' '.join(str(prodotto or '').lower().split())}"
        if any(e in nome for e in _EDIZIONE_HOME_PRO) and not any(e in nome for e in _NON_HOME_PRO):
            return FINE_HOME_PRO[build]
    return voce[2] if voce else None


def stato_sistema(installazioni, oggi=None):
    """Il sistema operativo fra le installazioni di un PC: tra più righe vale la fine del supporto più vicina.

    ``None`` se non c'è un Windows riconoscibile. ``fuori``: scaduto; ``in_scadenza``: entro 90 giorni.
    """
    oggi = oggi or timezone.localdate()
    migliore = None
    for inst in installazioni:
        famiglia = wb.famiglia_installazione(inst)
        if famiglia is None:
            continue
        build = wb.build_da_versione(inst.version_raw)
        fine = _fine_supporto(famiglia, build, inst.product)
        riga = {"nome": wb.nome_release(famiglia, build), "fine": fine, "fuori": bool(fine and fine < oggi),
                "in_scadenza": bool(fine and oggi <= fine <= oggi + timedelta(days=GIORNI_PREAVVISO))}
        if migliore is None or (fine and (migliore["fine"] is None or fine < migliore["fine"])):
            migliore = riga
    return migliore


def sistemi_per_host(oggi=None):
    """{host: stato del sistema} per tutti i PC: la colonna e il filtro di Dispositivi."""
    per_host = {}
    for inst in SoftwareInstallation.objects.filter(still_detected=True, product__istartswith="windows ").only("host", "product", "version_raw"):
        per_host.setdefault(inst.host, []).append(inst)
    out = {}
    for host, righe in per_host.items():
        stato = stato_sistema(righe, oggi)
        if stato:
            out[host] = stato
    return out


def _backup(asset, oggi):
    """(stato, testo): «ko», «vecchio», «ok» o «assente», dall'ultimo backup dei dispositivi collegati."""
    from security.services.backup_center import stale_days

    ultimo = (SecurityAssetSignal.objects.filter(asset__hub_asset=asset, kind=SecurityAssetSignal.KIND_BACKUP)
              .order_by("-occurred_at").first())
    if ultimo is None:
        return "assente", ""
    quando = timezone.localtime(ultimo.occurred_at).strftime("%d/%m/%Y")
    if ultimo.status == "failed":
        return "ko", quando
    if ultimo.occurred_at.date() < oggi - timedelta(days=stale_days()):
        return "vecchio", quando
    return "ok", quando


def valuta(asset, oggi=None):
    """Livello, motivi (tono, testo) e numeri per la scheda. ``None`` se il SOC non sa niente di questo asset."""
    from assets.models import Asset
    from security.services import cve_pannello, software_catalog

    oggi = oggi or timezone.localdate()
    installazioni = list(SoftwareInstallation.objects.filter(hub_asset=asset, still_detected=True).only("host", "product", "version_raw"))
    backup, backup_data = _backup(asset, oggi)
    if not installazioni and backup == "assente":
        return None
    dati = cve_pannello.per_asset(asset)
    sistema = stato_sistema(installazioni, oggi)
    copertura = software_catalog.copertura_asset(asset)
    alti, medi, note = [], [], []
    if dati["kev"]:
        alti.append(f"{dati['kev']} CVE sfruttate attivamente (CISA KEV)")
    if dati["gravi"]:
        alti.append(f"{dati['gravi']} CVE gravi")
    if sistema and sistema["fuori"]:
        alti.append(f"{sistema['nome']} fuori supporto dal {sistema['fine']:%d/%m/%Y}: niente più aggiornamenti di sicurezza")
    if dati["colpiscono"] and not dati["gravi"]:
        medi.append(f"{dati['colpiscono']} CVE da correggere")
    if sistema and sistema["in_scadenza"]:
        medi.append(f"{sistema['nome']}: supporto fino al {sistema['fine']:%d/%m/%Y}")
    if backup == "ko":
        medi.append(f"Ultimo backup fallito ({backup_data})")
    elif backup == "vecchio":
        medi.append(f"Ultimo backup del {backup_data}: troppo vecchio")
    elif backup == "assente" and asset.asset_type == Asset.TYPE_SERVER:
        medi.append("Server senza backup nei report")
    if dati["da_verificare"]:
        note.append(f"{dati['da_verificare']} CVE da verificare")
    if copertura["non_controllati"]:
        note.append(f"programmi non controllati per le CVE: {copertura['non_controllati']} su {copertura['programmi']}")
    dotazione = _dotazione(asset)
    if dotazione:
        medi.append("manca dalla dotazione attesa: " + ", ".join(dotazione))
    admin = _amministratori(asset)
    if admin and admin["accessi"]:
        nomi = ", ".join(a["sam"] for a in admin["account"][:4]) + (" e altri" if len(admin["account"]) > 4 else "")
        cessati = [a["sam"] for a in admin["account"] if a["cessato"]]
        if cessati:
            alti.append(f"accessi con l'account di una persona cessata: {', '.join(cessati)}")
        testo = f"{admin['accessi']} accessi di account amministratore negli ultimi {admin['giorni']} giorni ({nomi})"
        if asset.asset_type == Asset.TYPE_SERVER:
            note.append(testo)
        else:
            medi.append(testo + ": le credenziali di dominio restano in memoria sul PC")
        if any(a["password_non_scade"] for a in admin["account"]):
            note.append("fra questi, account con password che non scade: " + ", ".join(a["sam"] for a in admin["account"] if a["password_non_scade"]))
    hardware = _hardware(asset, oggi)
    if hardware and hardware["giudizio"] == "sostituire":
        medi.append("hardware da sostituire: " + ", ".join(hardware["motivi"]))
    elif hardware and hardware["giudizio"] == "pianificare":
        note.append("sostituzione da pianificare: " + ", ".join(hardware["motivi"]))
    livello = ALTO if alti else MEDIO if medi else NESSUNO if installazioni else NON_VALUTABILE
    return {
        "livello": livello, "etichetta": ETICHETTE[livello], "alti": alti, "medi": medi, "note": note, "cve": dati["colpiscono"],
        "gravi": dati["gravi"], "sistema": sistema, "backup": backup, "backup_data": backup_data,
        "dotazione": dotazione, "admin": admin, "hardware": hardware,
    }


def _dotazione(asset):
    try:
        from assets.services.software_dotazione import mancanti_per_asset

        return mancanti_per_asset(asset)
    except Exception:  # noqa: BLE001 - un pezzo del riquadro, non il riquadro
        return []


def _amministratori(asset):
    try:
        from security.services.accessi_admin import per_asset

        return per_asset(asset)
    except Exception:  # noqa: BLE001 - senza Registro log il riquadro resta leggibile
        return None


def _hardware(asset, oggi):
    try:
        from assets.services.hardware_vita import valuta as hw

        return hw(asset, oggi)
    except Exception:  # noqa: BLE001
        return None
