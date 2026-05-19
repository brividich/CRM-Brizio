import os, sys, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings.dev'
sys.path.insert(0, 'django_app')
django.setup()
from core.models import NavigationItem, ModuleCategory

# 1. Crea categoria "Compliance" se non esiste
compliance, created = ModuleCategory.objects.get_or_create(
    key='compliance',
    defaults=dict(label='Compliance', topbar_color='#6b21a8', order=35)
)
print(f"{'[CREA]' if created else '[OK]'} categoria compliance")

# 2. Recupera categorie
cat_manutenzione = ModuleCategory.objects.get(key='manutenzione')
cat_hr = ModuleCategory.objects.get(key='hr')
cat_sicurezza = ModuleCategory.objects.get(key='sicurezza')

# 3. Assegnazioni corrette
ASSIGNMENTS = {
    # manutenzione
    'tickets':               (cat_manutenzione, 10),
    'assets':                (cat_manutenzione, 20),
    'gestione-attrezzatura': (cat_manutenzione, 30),
    'vrf-kick-off':          (cat_manutenzione, 40),
    # hr
    'assenze':               (cat_hr, 10),
    'timbri':                (cat_hr, 20),
    'anagrafica':            (cat_hr, 30),
    'notizie':               (cat_hr, 40),
    # sicurezza
    'diario_preposto':       (cat_sicurezza, 10),
    'segnalazionisicurezza': (cat_sicurezza, 20),
    'dpi':                   (cat_sicurezza, 30),
    'procedure_refresh':     (cat_sicurezza, 40),
    'gestione_anomalie':     (cat_sicurezza, 50),
    # compliance
    'rentri':                (compliance, 10),
    # standalone (nessuna categoria)
    'accessi':               (None, 60),
}

for code, (cat, order) in ASSIGNMENTS.items():
    n = NavigationItem.objects.filter(code=code).update(category=cat, order=order)
    status = '[OK]' if n else '[MISS]'
    print(f"  {status} {code:40} -> {cat.key if cat else 'standalone':15} order={order}")

print("\nDone.")
