"""Le impostazioni SOC devono rispettare il vincolo ISJSON di SQL Server.

In produzione (SQL Server) `seed_security_center_config` e il pulsante
«Completa la configurazione» fallivano con IntegrityError 547 sul vincolo
``CHECK (ISJSON(value) = 1)``: ISJSON accetta solo oggetti e liste, le impostazioni
sono valori semplici. SQLite (test) non ha il vincolo: qui lo si emula leggendo il
valore grezzo della colonna.
"""
import json

from django.db import connection
from django.test import TestCase

from security.models import SCALAR_WRAPPER_KEY, SecurityCenterSetting
from security.services.autoconfig import apply_autoconfig
from security.services.configuration import get_setting, set_setting


def _raw_values():
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT {connection.ops.quote_name('value')} FROM {SecurityCenterSetting._meta.db_table}")
        return [row[0] for row in cursor.fetchall()]


def _isjson_like_sqlserver(raw):
    """ISJSON(x) = 1 su SQL Server: solo oggetto o lista."""
    try:
        return isinstance(json.loads(raw), (dict, list))
    except (TypeError, ValueError):
        return False


class SettingValueSqlServerTest(TestCase):
    def test_autoconfig_general_respects_isjson(self):
        apply_autoconfig(["general"])
        raws = _raw_values()
        self.assertTrue(raws)
        bad = [raw for raw in raws if not _isjson_like_sqlserver(raw)]
        self.assertEqual(bad, [], "valori che SQL Server rifiuterebbe (errore 547)")

    def test_scalars_round_trip_unwrapped(self):
        for key, value in (("s", "NOVICROM HUB"), ("i", 90), ("b", True), ("e", ""), ("n", None)):
            SecurityCenterSetting.objects.create(key=key, value=value, category="t")
            self.assertEqual(SecurityCenterSetting.objects.get(key=key).value, value, key)

    def test_objects_and_lists_stored_as_is(self):
        SecurityCenterSetting.objects.create(key="d", value={"a": 1}, category="t")
        SecurityCenterSetting.objects.create(key="l", value=["x"], category="t")
        self.assertEqual(SecurityCenterSetting.objects.get(key="d").value, {"a": 1})
        self.assertEqual(SecurityCenterSetting.objects.get(key="l").value, ["x"])
        self.assertNotIn(SCALAR_WRAPPER_KEY, "".join(_raw_values()))

    def test_legacy_unwrapped_rows_still_readable(self):
        """Righe scritte prima della correzione (es. SQLite di sviluppo) restano leggibili."""
        setting = SecurityCenterSetting.objects.create(key="old", value={"x": 1}, category="t")
        with connection.cursor() as cursor:
            cursor.execute(
                f"UPDATE {SecurityCenterSetting._meta.db_table} SET {connection.ops.quote_name('value')} = %s WHERE id = %s",
                [json.dumps("vecchio"), setting.pk],
            )
        self.assertEqual(SecurityCenterSetting.objects.get(pk=setting.pk).value, "vecchio")

    def test_set_and_get_setting_api(self):
        set_setting("GRAPH_MAIL_FOLDER", "Report SOC", category="graph")
        self.assertEqual(get_setting("GRAPH_MAIL_FOLDER"), "Report SOC")
        self.assertTrue(all(_isjson_like_sqlserver(raw) for raw in _raw_values()))
