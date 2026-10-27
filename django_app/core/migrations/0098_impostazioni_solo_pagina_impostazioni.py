"""«Impostazioni» apre solo la pagina Impostazioni del modulo e le sue sotto-pagine.

0096/0097 avevano messo sotto «impostazioni» anche pagine che non lo sono: per le
assenze i due permessi della gestione interna (che aprono anche certificazione
presenza, area HR e gestione admin), per l'anagrafica rettifiche, skill matrix,
mansioni e rischi e i widget, per la formazione il catalogo dei corsi e-learning.

- assenze: la pagina Impostazioni ha un permesso suo, ``assenze.impostazioni.manage``;
- le rotte tolte tornano al permesso di prima (o perdono il binding creato da 0097);
- i permessi tolti tornano a «gestire»: sui ruoli gia' sincronizzati dalla matrice
  si accendono dove «gestire» e' concesso e si spengono dove non lo e'.
"""
from django.db import migrations

NOTA = "[CORE_0098] impostazioni solo pagina"
NOTA_0097 = "[CORE_0097]"
NOTA_MATRICE = "matrice ruoli"
AZIONE = "impostazioni"

ASSENZE_CODICE = "assenze.impostazioni.manage"
ASSENZE_ROTTA = "assenze_impostazioni"

# Rotte che 0097 aveva legato alle impostazioni e che non lo sono.
ROTTE_TOLTE = (
    "anagrafica:rettifiche",
    "anagrafica:skm_impostazioni",
    "anagrafica:sicurezza_operativa_config",
    "anagrafica:elearning_impostazioni_corsi",
)

# (modulo della matrice, permessi tornati a «gestire»)
TORNANO_A_GESTIRE = (
    ("assenze", ("assenze.assenze.manage", "legacy.assenze.admin_assenze")),
    ("anagrafica", ("anagrafica.widget_permissions.view",)),
)


def _sincronizzati(GroupGrant):
    return set(GroupGrant.objects.filter(note=NOTA_MATRICE).values_list("group_id", flat=True))


def avanti(apps, schema_editor):
    Permission = apps.get_model("core", "PermissionDefinition")
    Binding = apps.get_model("core", "RoutePermissionBinding")
    Cella = apps.get_model("core", "RuoloPermessoModulo")
    GroupGrant = apps.get_model("core", "GroupPermissionGrant")
    RoleGrant = apps.get_model("core", "RolePermissionGrant")
    sincronizzati = _sincronizzati(GroupGrant)

    # 1) Assenze: permesso proprio della pagina Impostazioni.
    Permission.objects.get_or_create(code=ASSENZE_CODICE, defaults={
        "label": "Assenze · impostazioni", "module": "assenze", "is_active": True,
        "description": "Pagina Impostazioni delle assenze: la apre l'azione «impostazioni» della matrice.",
    })
    binding = Binding.objects.filter(route_name=ASSENZE_ROTTA, path_pattern="").first()
    vecchio = binding.permission_id if binding else ""
    if binding is None:
        Binding.objects.create(
            route_name=ASSENZE_ROTTA, path_pattern="", match_strategy="exact", permission_id=ASSENZE_CODICE,
            source_app="assenze", note=NOTA, priority=80, is_active=True,
        )
    elif vecchio != ASSENZE_CODICE:
        binding.permission_id = ASSENZE_CODICE
        binding.is_active = True
        binding.note = ((binding.note or "") + f" {NOTA} (era {vecchio})").strip()[:255]
        binding.save(update_fields=["permission", "is_active", "note"])
    for vecchio_code in {vecchio, "legacy.assenze.admin_assenze"} - {"", ASSENZE_CODICE}:
        for g in RoleGrant.objects.filter(permission_id=vecchio_code, enabled=True):
            RoleGrant.objects.get_or_create(
                legacy_role_id=g.legacy_role_id, permission_id=ASSENZE_CODICE,
                defaults={"enabled": True, "note": NOTA},
            )
    for ruolo_id in Cella.objects.filter(
        modulo="assenze", azione=AZIONE, consentito=True, ruolo_id__in=sincronizzati
    ).values_list("ruolo_id", flat=True):
        GroupGrant.objects.get_or_create(
            group_id=ruolo_id, permission_id=ASSENZE_CODICE, defaults={"enabled": True, "note": NOTA_MATRICE},
        )

    # 2) Rotte tolte: binding di prima, o nessun binding se l'aveva creato 0097.
    for rotta in ROTTE_TOLTE:
        binding = Binding.objects.filter(route_name=rotta, path_pattern="").first()
        if binding is None or NOTA_0097 not in (binding.note or ""):
            continue
        note = binding.note or ""
        if "(era " in note:
            prima = note.rsplit("(era ", 1)[1].split(")", 1)[0].strip()
            if prima and Permission.objects.filter(code=prima).exists():
                binding.permission_id = prima
                binding.note = note.split(NOTA_0097, 1)[0].strip()[:255]
                binding.save(update_fields=["permission", "note"])
                continue
        if note.startswith(NOTA_0097):
            binding.delete()

    # 3) Permessi tornati a «gestire» sui ruoli gia' sincronizzati.
    for modulo, codici in TORNANO_A_GESTIRE:
        esistenti = set(Permission.objects.filter(code__in=codici).values_list("code", flat=True))
        gestire = set(Cella.objects.filter(
            modulo=modulo, azione="gestire", consentito=True
        ).values_list("ruolo_id", flat=True))
        for ruolo_id in sincronizzati:
            for code in esistenti:
                if ruolo_id in gestire:
                    GroupGrant.objects.get_or_create(
                        group_id=ruolo_id, permission_id=code, defaults={"enabled": True, "note": NOTA_MATRICE},
                    )
                else:
                    GroupGrant.objects.filter(group_id=ruolo_id, permission_id=code, note=NOTA_MATRICE).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0097_impostazioni_moduli_azione_propria")]
    operations = [migrations.RunPython(avanti, migrations.RunPython.noop)]
