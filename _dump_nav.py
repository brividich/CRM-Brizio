import os, sys, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings.dev'
sys.path.insert(0, 'django_app')
django.setup()
from core.models import NavigationItem

print("=== TOPBAR items - route_name e url_path ===")
items = NavigationItem.objects.filter(section='topbar').order_by('order')
for i in items:
    print(f"  {i.code:40} | route={i.route_name or '-':40} | url={i.url_path or '-'}")
