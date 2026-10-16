"""Perimetro di lettura corrente: anagrafica autorevole, fallback legacy.

Non assegna permessi e non cambia l'approvatore della singola richiesta.
Gli identificativi utente, anagrafica e capi_reparto appartengono a domini diversi.
"""
from core.legacy_utils import legacy_table_columns


def canonical_team_predicates(legacy_user_id, alias="a"):
    """Restituisce (assegnazione nota, assegnazione al capo, parametri).

    EXISTS evita liste IN senza limite e duplicazioni delle assenze. Il legame
    dipendente usa l'account; per le importazioni senza account usa solo email
    esatta e univoca, mai il nominativo o il solo prefisso email.
    """
    from anagrafica.models import AreaAziendale, DipendenteAnagraficaAziendale, Reparto

    if legacy_user_id is None:
        return "", "", []
    employee_cols = legacy_table_columns("anagrafica_dipendenti")
    absence_cols = legacy_table_columns("assenze")
    if not {"id", "utente_id"}.issubset(employee_cols):
        return "", "", []
    az = DipendenteAnagraficaAziendale._meta.db_table
    area = AreaAziendale._meta.db_table
    reparto = Reparto._meta.db_table
    # Queste sono tabelle Django gestite dalle migrazioni, non tabelle legacy.
    links = []
    if "utente_id" in absence_cols:
        links.append(f"({alias}.utente_id IS NOT NULL AND dip.utente_id = {alias}.utente_id)")
    if "email_esterna" in absence_cols and "email" in employee_cols:
        missing_account = f"{alias}.utente_id IS NULL AND " if "utente_id" in absence_cols else ""
        links.append(
            f"({missing_account}NULLIF(LTRIM(RTRIM({alias}.email_esterna)), '') IS NOT NULL "
            f"AND LOWER(dip.email) = LOWER({alias}.email_esterna) "
            "AND NOT EXISTS (SELECT 1 FROM anagrafica_dipendenti dup "
            "WHERE LOWER(dup.email) = LOWER(dip.email) AND dup.id <> dip.id))"
        )
    if not links:
        return "", "", []
    unica = _predicati_regola_unica(legacy_user_id, links)
    if unica is not None:
        return unica
    responsible = "COALESCE(ar.responsabile_legacy_id, rep.caporeparto_legacy_id, az.caporeparto_legacy_id)"
    base = (
        "SELECT 1 FROM anagrafica_dipendenti dip "
        f"JOIN {az} az ON az.legacy_anagrafica_id = dip.id "
        f"LEFT JOIN {area} ar ON ar.id = az.area_aziendale_id "
        f"LEFT JOIN {reparto} rep ON rep.id = ar.reparto_id "
        f"WHERE ({' OR '.join(links)}) AND {responsible} IS NOT NULL"
    )
    known = f"EXISTS ({base})"
    mine = (
        f"EXISTS ({base} AND EXISTS (SELECT 1 FROM anagrafica_dipendenti manager "
        f"WHERE manager.id = {responsible} AND manager.utente_id = %s))"
    )
    return known, mine, [int(legacy_user_id)]


def _predicati_regola_unica(legacy_user_id, links):
    """Gli stessi due predicati con la regola unica capo/team di Anagrafica.

    ``None`` se la regola è spenta. «Nota» = la persona ha un capo; «mia» = il
    capo è chi guarda (team diretto: l'approvazione resta al capo diretto).
    Gli id sono interi letti dal DB, scritti in chiaro nella IN.
    """
    try:
        from anagrafica.services import capo_team

        if not capo_team.regola_unica_attiva():
            return None
        from core.legacy_models import AnagraficaDipendente

        mappa = capo_team.mappa_capi_in_cache()
        miei_id = set(AnagraficaDipendente.objects.filter(utente_id=int(legacy_user_id)).values_list("id", flat=True))
    except Exception:
        return None
    noti = sorted(int(p) for p, c in mappa.items() if c)
    miei = sorted(int(p) for p, c in mappa.items() if c and int(c) in miei_id)

    def _in(ids):
        return f"dip.id IN ({', '.join(str(i) for i in ids)})" if ids else "1 = 0"

    base = f"SELECT 1 FROM anagrafica_dipendenti dip WHERE ({' OR '.join(links)})"
    return f"EXISTS ({base} AND {_in(noti)})", f"EXISTS ({base} AND {_in(miei)})", []
