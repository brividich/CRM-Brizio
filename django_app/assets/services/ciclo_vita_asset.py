"""Dismissione ed eliminazione di un asset dalla scheda.

«Elimina» serve per gli asset creati per errore: la cancellazione porterebbe via a
cascata ordini di lavoro, scadenze, documenti e storico manutentivo, quindi e'
consentita solo quando l'asset non ha ancora storico. Con storico si usa
«Dismetti» (stato «Dismesso», reversibile con «Riattiva»).

Le relazioni elencate in ``_SENZA_STORICO`` sono dati descrittivi dell'asset
(endpoint, dettagli IT, etichette...) e se ne vanno con lui. Ogni altra relazione,
comprese quelle aggiunte in futuro, blocca l'eliminazione finche' ha righe.
"""
from __future__ import annotations

_SENZA_STORICO = {
    "assets.AssetEndpoint",
    "assets.AssetITDetails",
    "assets.AssetComponent",
    "assets.WorkMachine",
    "assets.PlantLayoutMarker",
    "assets.AssetLabelTemplate",
    "assets.AssetFieldHistory",
    "assets.AssetTimelineHiddenEvent",
    "assets.AssetGroupMembership",
    "assets.AssetGroup",
    "assets.AssetMaintenanceRuleState",
    "assets.MaintenanceRule",
    "assets.MaintenanceRuleAssetOverride",
}


# Nomi leggibili delle relazioni piu' frequenti (molti modelli non hanno verbose_name italiano).
_ETICHETTE = {
    "assets.WorkOrder": "ordini di lavoro",
    "assets.MaintenanceOccurrence": "scadenze di manutenzione",
    "assets.MaintenancePlanAssignment": "piani di manutenzione applicati",
    "assets.AssetAdministrativeDeadline": "scadenze normative",
    "assets.AssetDocument": "documenti",
    "assets.AssetTimelineEntry": "voci di timeline",
    "assets.AssistanceContract": "contratti di assistenza",
    "assets.PeriodicVerification": "verifiche periodiche",
    "assets.PeriodicCheckSystem": "impianti in verifica",
    "assets.AssetMeter": "contatori",
    "assets.AssetCalendarEvent": "eventi di calendario",
    "assets.SoftwareLicense": "licenze software",
    "tickets.Ticket": "ticket",
    "rilevazione_incidenti.RilevazioneIncidente": "segnalazioni di sicurezza",
    "anagrafica.AbilitazioneMacchina": "abilitazioni macchina",
    "anagrafica.AbilitazioneMacchinaStorico": "abilitazioni macchina (storico)",
    "gestione_carichi_macchina.Macchina": "macchine nei carichi macchina",
    "tasks.TaskExtraRef": "riferimenti KICK-OFF",
}


def blocchi_eliminazione(asset) -> list[str]:
    """Cosa impedisce di eliminare l'asset: ``["3 ordini di lavoro", ...]``; vuota se si puo'."""
    blocchi: list[str] = []
    for relazione in asset._meta.related_objects:
        modello = relazione.related_model
        label = modello._meta.label
        if label in _SENZA_STORICO:
            continue
        presenti = modello._base_manager.filter(**{relazione.field.name: asset}).count()
        if presenti:
            blocchi.append(f"{presenti} {_ETICHETTE.get(label, str(modello._meta.verbose_name_plural))}")
    return blocchi
