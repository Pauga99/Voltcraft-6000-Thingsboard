import importlib.util
import logging
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = (
    Path(__file__).resolve().parents[1] / "usa_sem6000_thingsboard_mqtt.py"
)
MODULE_SPEC = importlib.util.spec_from_file_location(
    "usa_sem6000_thingsboard_mqtt",
    MODULE_PATH,
)
MODULE = importlib.util.module_from_spec(MODULE_SPEC)
assert MODULE_SPEC is not None and MODULE_SPEC.loader is not None
sys.modules[MODULE_SPEC.name] = MODULE
MODULE_SPEC.loader.exec_module(MODULE)


class DummyMeasurement:
    def __init__(
        self,
        power_in_milliwatt=1234,
        is_power_active=True,
        voltage_in_volt=230.2,
        current_in_milliampere=142,
        frequency_in_hertz=49.97,
        total_consumption_in_kilowatt_hour=12.345678,
    ):
        self.power_in_milliwatt = power_in_milliwatt
        self.is_power_active = is_power_active
        self.voltage_in_volt = voltage_in_volt
        self.current_in_milliampere = current_in_milliampere
        self.frequency_in_hertz = frequency_in_hertz
        self.total_consumption_in_kilowatt_hour = total_consumption_in_kilowatt_hour


class DummySettings:
    def __init__(
        self,
        is_reduced_period=True,
        normal_price_in_cent=31,
        reduced_period_price_in_cent=12,
        reduced_period_start_isotime="23:00",
        reduced_period_end_isotime="06:30",
        is_nightmode_active=False,
        power_limit_in_watt=3680,
    ):
        self.is_reduced_period = is_reduced_period
        self.normal_price_in_cent = normal_price_in_cent
        self.reduced_period_price_in_cent = reduced_period_price_in_cent
        self.reduced_period_start_isotime = reduced_period_start_isotime
        self.reduced_period_end_isotime = reduced_period_end_isotime
        self.is_nightmode_active = is_nightmode_active
        self.power_limit_in_watt = power_limit_in_watt


class DummyTimerStatus:
    def __init__(
        self,
        is_active=True,
        is_action_turn_on=True,
        target_isodatetime="2026-04-13T18:30:00",
        original_timer_length_in_seconds=300,
    ):
        self.is_active = is_active
        self.is_action_turn_on = is_action_turn_on
        self.target_isodatetime = target_isodatetime
        self.original_timer_length_in_seconds = original_timer_length_in_seconds


class DummyRandomModeStatus:
    def __init__(
        self,
        is_active=True,
        active_on_weekdays=None,
        start_isotime="18:00",
        end_isotime="23:00",
    ):
        self.is_active = is_active
        self.active_on_weekdays = [1, 3, 5] if active_on_weekdays is None else active_on_weekdays
        self.start_isotime = start_isotime
        self.end_isotime = end_isotime


class DummyScheduler:
    def __init__(
        self,
        is_active=True,
        is_action_turn_on=True,
        repeat_on_weekdays=None,
        isodatetime="2026-05-01T08:30",
    ):
        self.is_active = is_active
        self.is_action_turn_on = is_action_turn_on
        self.repeat_on_weekdays = [] if repeat_on_weekdays is None else repeat_on_weekdays
        self.isodatetime = isodatetime


class DummySchedulerEntry:
    def __init__(self, slot_id, scheduler):
        self.slot_id = slot_id
        self.scheduler = scheduler


class DummySchedulerNotification:
    def __init__(self, scheduler_entries):
        self.scheduler_entries = scheduler_entries
        self.number_of_schedulers = len(scheduler_entries)


class DummyConsumption23Hours:
    def __init__(self, values=None):
        self.consumption_n_hours_ago_in_watt_hour = [50, None, 25] if values is None else values


class DummyConsumption30Days:
    def __init__(self, values=None):
        self.consumption_n_days_ago_in_watt_hour = [120, 95, None] if values is None else values


class DummyConsumption12Months:
    def __init__(self, values=None):
        self.consumption_n_months_ago_in_watt_hour = [900, None, 640] if values is None else values


class CapturePublish:
    def __init__(self):
        self.calls = []

    def __call__(self, topic, payload, qos):
        self.calls.append((topic, payload, qos))


class StubSem:
    def __init__(
        self,
        measurement_result=None,
        settings_result=None,
        device_name="SEM Plug",
        device_serial="ML01D10012000000",
        timer_status_result=None,
        random_mode_result=None,
        scheduler_result=None,
        consumption23h_result=None,
        consumption30d_result=None,
        consumption12m_result=None,
    ):
        self.set_power_calls = []
        self.measurement_calls = 0
        self.measurement_result = measurement_result
        self.sync_time_calls = []
        self.settings_result = settings_result
        self.request_settings_calls = 0
        self.set_night_mode_calls = []
        self.set_power_limit_calls = []
        self.set_prices_calls = []
        self.set_reduced_period_calls = []
        self.request_device_name_calls = 0
        self.change_device_name_calls = []
        self.request_device_serial_calls = 0
        self.device_name = device_name
        self.device_serial = device_serial
        self.timer_status_result = timer_status_result
        self.request_timer_status_calls = 0
        self.activate_timer_at_calls = []
        self.reset_timer_calls = 0
        self.random_mode_result = random_mode_result
        self.request_random_mode_status_calls = 0
        self.change_random_mode_calls = []
        self.reset_random_mode_calls = 0
        self.scheduler_result = scheduler_result
        self.request_scheduler_calls = 0
        self.add_onetime_scheduler_calls = []
        self.edit_onetime_scheduler_calls = []
        self.add_repeated_scheduler_calls = []
        self.edit_repeated_scheduler_calls = []
        self.remove_scheduler_calls = []
        self.consumption23h_result = consumption23h_result
        self.consumption30d_result = consumption30d_result
        self.consumption12m_result = consumption12m_result
        self.request_consumption_of_last_23_hours_calls = 0
        self.request_consumption_of_last_30_days_calls = 0
        self.request_consumption_of_last_12_months_calls = 0
        self.reset_consumption_calls = 0
        self.change_pin_calls = []
        self.reset_pin_calls = 0
        self.factory_reset_calls = 0

    def set_power(self, target_on):
        self.set_power_calls.append(target_on)

    def request_measurement(self):
        self.measurement_calls += 1
        if self.measurement_result is None:
            raise AssertionError("BLE measurement should not be called in this test")
        return self.measurement_result

    def sync_time(self, iso_datetime):
        self.sync_time_calls.append(iso_datetime)

    def request_settings(self):
        self.request_settings_calls += 1
        if self.settings_result is None:
            raise AssertionError("request_settings should not be called in this test")
        return self.settings_result

    def set_night_mode(self, enabled):
        self.set_night_mode_calls.append(enabled)

    def set_power_limit(self, power_limit_w):
        self.set_power_limit_calls.append(power_limit_w)

    def set_prices(self, normal_price_cent, reduced_price_cent):
        self.set_prices_calls.append((normal_price_cent, reduced_price_cent))

    def set_reduced_period(self, enabled, start_isotime, end_isotime):
        self.set_reduced_period_calls.append((enabled, start_isotime, end_isotime))

    def request_device_name(self):
        self.request_device_name_calls += 1
        return SimpleNamespace(device_name=self.device_name)

    def change_device_name(self, device_name):
        self.change_device_name_calls.append(device_name)

    def request_device_serial(self):
        self.request_device_serial_calls += 1
        return SimpleNamespace(serial=self.device_serial)

    def request_timer_status(self):
        self.request_timer_status_calls += 1
        if self.timer_status_result is None:
            raise AssertionError("request_timer_status should not be called in this test")
        return self.timer_status_result

    def activate_timer_at(self, turn_on, target_isodatetime):
        self.activate_timer_at_calls.append((turn_on, target_isodatetime))

    def reset_timer(self):
        self.reset_timer_calls += 1

    def request_random_mode_status(self):
        self.request_random_mode_status_calls += 1
        if self.random_mode_result is None:
            raise AssertionError(
                "request_random_mode_status should not be called in this test"
            )
        return self.random_mode_result

    def change_random_mode(self, weekdays, start_isotime, end_isotime):
        self.change_random_mode_calls.append((weekdays, start_isotime, end_isotime))

    def reset_random_mode(self):
        self.reset_random_mode_calls += 1

    def request_scheduler(self):
        self.request_scheduler_calls += 1
        if self.scheduler_result is None:
            raise AssertionError("request_scheduler should not be called in this test")
        return self.scheduler_result

    def add_onetime_scheduler(self, enabled, turn_on, target_isodatetime):
        self.add_onetime_scheduler_calls.append((enabled, turn_on, target_isodatetime))

    def edit_onetime_scheduler(self, slot_id, enabled, turn_on, target_isodatetime):
        self.edit_onetime_scheduler_calls.append(
            (slot_id, enabled, turn_on, target_isodatetime)
        )

    def add_repeated_scheduler(self, enabled, turn_on, weekdays, isotime):
        self.add_repeated_scheduler_calls.append((enabled, turn_on, weekdays, isotime))

    def edit_repeated_scheduler(self, slot_id, enabled, turn_on, weekdays, isotime):
        self.edit_repeated_scheduler_calls.append(
            (slot_id, enabled, turn_on, weekdays, isotime)
        )

    def remove_scheduler(self, slot_id):
        self.remove_scheduler_calls.append(slot_id)

    def request_consumption_of_last_23_hours(self):
        self.request_consumption_of_last_23_hours_calls += 1
        if self.consumption23h_result is None:
            raise AssertionError(
                "request_consumption_of_last_23_hours should not be called in this test"
            )
        return self.consumption23h_result

    def request_consumption_of_last_30_days(self):
        self.request_consumption_of_last_30_days_calls += 1
        if self.consumption30d_result is None:
            raise AssertionError(
                "request_consumption_of_last_30_days should not be called in this test"
            )
        return self.consumption30d_result

    def request_consumption_of_last_12_months(self):
        self.request_consumption_of_last_12_months_calls += 1
        if self.consumption12m_result is None:
            raise AssertionError(
                "request_consumption_of_last_12_months should not be called in this test"
            )
        return self.consumption12m_result

    def reset_consumption(self):
        self.reset_consumption_calls += 1

    def change_pin(self, new_pin):
        self.change_pin_calls.append(new_pin)

    def reset_pin(self):
        self.reset_pin_calls += 1

    def factory_reset(self):
        self.factory_reset_calls += 1


class StubTelemetry:
    def __init__(self):
        self.calls = []

    def publish(self, values, timestamp_ms=None):
        self.calls.append((values, timestamp_ms))


class StubAttributes:
    def __init__(self):
        self.calls = []

    def publish(self, attributes):
        self.calls.append(attributes)


class ParseBooleanValueTests(unittest.TestCase):
    def test_parse_boolean_true_values(self):
        self.assertTrue(MODULE.parse_boolean_value(True))
        self.assertTrue(MODULE.parse_boolean_value(1))
        self.assertTrue(MODULE.parse_boolean_value("ON"))
        self.assertTrue(MODULE.parse_boolean_value({"enabled": "true"}))

    def test_parse_boolean_false_values(self):
        self.assertFalse(MODULE.parse_boolean_value(False))
        self.assertFalse(MODULE.parse_boolean_value(0))
        self.assertFalse(MODULE.parse_boolean_value("off"))
        self.assertFalse(MODULE.parse_boolean_value({"state": "0"}))

    def test_parse_boolean_invalid(self):
        self.assertIsNone(MODULE.parse_boolean_value("maybe"))
        self.assertIsNone(MODULE.parse_boolean_value({"value": "unknown"}))


class Sem6000NotificationCompletionTests(unittest.TestCase):
    def test_history_message_waits_for_declared_length_even_if_chunk_ends_with_suffix(self):
        # Payload 0x0b00 + 120 bytes. Fem que el primer fragment acabi amb ff ff
        # per simular el cas problematic dels historics llargs.
        payload = b"\x0b\x00" + (b"\x00" * 14) + b"\xff\xff" + (b"\x00" * 104)
        checksum = ((1 + sum(payload)) & 0xFF).to_bytes(1, "big")
        full_message = b"\x0f\x7b" + payload + checksum + b"\xff\xff"

        first_chunk = full_message[:20]
        remaining_chunks = [full_message[20:80], full_message[80:]]

        self.assertTrue(first_chunk.endswith(b"\xff\xff"))
        self.assertFalse(
            MODULE.sem6000_raw_notifications_complete([first_chunk], hardware_version=2)
        )
        self.assertTrue(
            MODULE.sem6000_raw_notifications_complete(
                [first_chunk, *remaining_chunks],
                hardware_version=2,
            )
        )

    def test_history_message_with_invalid_checksum_is_not_considered_complete(self):
        payload = b"\x0b\x00" + (b"\x00" * 120)
        wrong_checksum = b"\x19"
        full_message = b"\x0f\x7b" + payload + wrong_checksum + b"\xff\xff"

        self.assertFalse(
            MODULE.sem6000_raw_notifications_complete([full_message], hardware_version=2)
        )

    def test_hw3_daily_history_accepts_known_device_checksum_anomaly(self):
        full_message = bytes.fromhex(
            "0f7b0b0000000000000000000000000000000000000000000000000000003c"
            "000000000000000000000000000000000000000000000007000000000000"
            "000000000000000000000000000000000000000000000000000000000000"
            "000000070000000000000000000000000000005a00000000000000000000"
            "0000006dffff"
        )

        self.assertTrue(
            MODULE.sem6000_raw_notifications_complete([full_message], hardware_version=3)
        )

    def test_wait_for_notifications_keeps_polling_while_message_is_partial(self):
        payload = b"\x0b\x00" + (b"\x00" * 120)
        checksum = ((1 + sum(payload)) & 0xFF).to_bytes(1, "big")
        full_message = b"\x0f\x7b" + payload + checksum + b"\xff\xff"
        first_chunk = full_message[:20]
        remaining = full_message[20:]

        class FakeDelegate:
            def __init__(self):
                self.hardware_version = 2
                self._raw_notifications = []

            def has_final_raw_notification(self):
                return MODULE.sem6000_raw_notifications_complete(
                    self._raw_notifications,
                    self.hardware_version,
                )

        class FakeClock:
            def __init__(self):
                self.now = 0.0

            def monotonic(self):
                return self.now

            def advance(self, seconds):
                self.now += seconds

        delegate = FakeDelegate()
        clock = FakeClock()
        wait_calls = []
        original_monotonic = MODULE.time.monotonic

        def fake_wait(timeout):
            wait_calls.append(timeout)
            clock.advance(timeout)
            if len(wait_calls) == 1:
                delegate._raw_notifications.append(first_chunk)
                return True
            if len(wait_calls) == 2:
                return False
            if len(wait_calls) == 3:
                delegate._raw_notifications.append(remaining)
                return True
            return False

        try:
            MODULE.time.monotonic = clock.monotonic
            MODULE.wait_for_sem6000_notifications(
                fake_wait,
                delegate,
                timeout_seconds=5.0,
            )
        finally:
            MODULE.time.monotonic = original_monotonic

        self.assertTrue(delegate.has_final_raw_notification())
        self.assertEqual(3, len(wait_calls))
        self.assertEqual(5.0, wait_calls[0])
        self.assertLess(wait_calls[1], wait_calls[0])
        self.assertLess(wait_calls[2], wait_calls[0])


class Sem6000SessionTimeoutTests(unittest.TestCase):
    def test_30d_history_uses_longer_timeout_and_restores_device_timeout(self):
        class FakeDevice:
            def __init__(self):
                self.timeout = 3.0
                self.timeouts_seen = []

            def request_consumption_of_last_30_days(self):
                self.timeouts_seen.append(self.timeout)
                return DummyConsumption30Days()

        fake_device = FakeDevice()
        session = MODULE.Sem6000Session(
            address="b3:00:00:00:30:43",
            pin="0000",
            timeout_seconds=3.0,
            history_timeout_seconds=12.0,
            debug=False,
            log=logging.getLogger("test"),
        )
        session._new_device = lambda: fake_device

        result = session.request_consumption_of_last_30_days()

        self.assertIsInstance(result, DummyConsumption30Days)
        self.assertEqual([12.0], fake_device.timeouts_seen)
        self.assertEqual(3.0, fake_device.timeout)


class RpcQueueTests(unittest.TestCase):
    def test_coalesces_power_commands(self):
        queue = MODULE.RpcTaskQueue(maxsize=10)
        first_power = MODULE.RpcTask(
            request_id=1,
            device_name="sem6000-aabb",
            method="setPower",
            params=True,
            coalesce_key="power_set",
        )
        other = MODULE.RpcTask(
            request_id=2,
            device_name="sem6000-aabb",
            method="getPowerState",
            params=None,
            coalesce_key=None,
        )
        second_power = MODULE.RpcTask(
            request_id=3,
            device_name="sem6000-aabb",
            method="powerOff",
            params=None,
            coalesce_key="power_set",
        )

        superseded, dropped = queue.put(first_power)
        self.assertEqual([], superseded)
        self.assertEqual([], dropped)

        superseded, dropped = queue.put(other)
        self.assertEqual([], superseded)
        self.assertEqual([], dropped)

        superseded, dropped = queue.put(second_power)
        self.assertEqual([first_power], superseded)
        self.assertEqual([], dropped)

        self.assertEqual(other, queue.get(timeout=0.01))
        self.assertEqual(second_power, queue.get(timeout=0.01))

    def test_drops_oldest_when_full(self):
        queue = MODULE.RpcTaskQueue(maxsize=1)
        first = MODULE.RpcTask(1, "sem6000-aabb", "getPowerState", None, None)
        second = MODULE.RpcTask(2, "sem6000-aabb", "getPowerState", None, None)

        superseded, dropped = queue.put(first)
        self.assertEqual([], superseded)
        self.assertEqual([], dropped)

        superseded, dropped = queue.put(second)
        self.assertEqual([], superseded)
        self.assertEqual([first], dropped)

        self.assertEqual(second, queue.get(timeout=0.01))


class MappingAndRegistryTests(unittest.TestCase):
    def test_map_measurement_minimal(self):
        values = MODULE.map_measurement_to_values(
            DummyMeasurement(),
            include_extended=False,
        )
        self.assertEqual(1.234, values["power_w"])
        self.assertEqual(True, values["plug_on"])
        self.assertNotIn("voltage_v", values)

    def test_map_measurement_extended(self):
        values = MODULE.map_measurement_to_values(
            DummyMeasurement(),
            include_extended=True,
        )
        self.assertEqual(230.2, values["voltage_v"])
        self.assertEqual(0.142, values["current_a"])
        self.assertEqual(49.97, values["frequency_hz"])
        self.assertEqual(12.345678, values["energy_total_kwh"])

    def test_normalize_settings_notification(self):
        values = MODULE.normalize_settings_notification(DummySettings())
        self.assertEqual(False, values["night_mode"])
        self.assertEqual(3680, values["power_limit_w"])
        self.assertEqual(31, values["prices"]["normal_price_cent"])
        self.assertEqual(12, values["prices"]["reduced_price_cent"])
        self.assertEqual(True, values["reduced_period"]["enabled"])
        self.assertEqual("23:00", values["reduced_period"]["start"])
        self.assertEqual("06:30", values["reduced_period"]["end"])

    def test_normalize_action_label(self):
        self.assertEqual("on", MODULE._normalize_action_label("on", field_name="action"))
        self.assertEqual("off", MODULE._normalize_action_label(False, field_name="action"))

    def test_normalize_action_label_rejects_invalid(self):
        with self.assertRaises(MODULE.CommandError) as ctx:
            MODULE._normalize_action_label("later", field_name="action")

        self.assertEqual("invalid_params", ctx.exception.code)

    def test_normalize_isodatetime_seconds(self):
        self.assertEqual(
            "2026-04-13T18:30:00",
            MODULE._normalize_isodatetime_seconds(
                "2026-04-13T18:30",
                field_name="target_isodatetime",
            ),
        )

    def test_normalize_isodatetime_seconds_rejects_invalid(self):
        with self.assertRaises(MODULE.CommandError) as ctx:
            MODULE._normalize_isodatetime_seconds(
                "13/04/2026 18:30",
                field_name="target_isodatetime",
            )

        self.assertEqual("invalid_params", ctx.exception.code)

    def test_normalize_weekdays_string(self):
        self.assertEqual(
            "Mon,Wed,Fri",
            MODULE._normalize_weekdays_string("mon, Wednesday, fri", field_name="weekdays"),
        )

    def test_normalize_weekdays_string_rejects_invalid(self):
        with self.assertRaises(MODULE.CommandError) as ctx:
            MODULE._normalize_weekdays_string("mon,holiday", field_name="weekdays")

        self.assertEqual("invalid_params", ctx.exception.code)

    def test_normalize_timer_status_notification(self):
        values = MODULE.normalize_timer_status_notification(DummyTimerStatus())
        self.assertEqual(True, values["timer_active"])
        self.assertEqual("on", values["action"])
        self.assertEqual("2026-04-13T18:30:00", values["target_isodatetime"])
        self.assertEqual(300, values["original_timer_length_seconds"])

    def test_normalize_random_mode_notification(self):
        values = MODULE.normalize_random_mode_notification(DummyRandomModeStatus())
        self.assertEqual(True, values["enabled"])
        self.assertEqual("Mon,Wed,Fri", values["weekdays"])
        self.assertEqual("18:00", values["start"])
        self.assertEqual("23:00", values["end"])

    def test_should_include_extended_measurements(self):
        self.assertTrue(
            MODULE.should_include_extended_measurements(
                DummyMeasurement(is_power_active=True),
                force_extended=False,
            )
        )
        self.assertFalse(
            MODULE.should_include_extended_measurements(
                DummyMeasurement(is_power_active=False),
                force_extended=False,
            )
        )
        self.assertTrue(
            MODULE.should_include_extended_measurements(
                DummyMeasurement(is_power_active=False),
                force_extended=True,
            )
        )

    def test_command_registry_resolves_handler(self):
        registry = MODULE.CommandRegistry()
        power_handler = MODULE.PowerHandler()
        registry.register(power_handler)

        resolved = registry.resolve("setPower")
        self.assertIs(resolved, power_handler)

    def test_coalesce_key_for_method(self):
        self.assertEqual("power_set", MODULE.coalesce_key_for_method("setPower"))
        self.assertEqual("power_set", MODULE.coalesce_key_for_method("powerOff"))
        self.assertIsNone(MODULE.coalesce_key_for_method("getPowerState"))


class GatewayPayloadTests(unittest.TestCase):
    def test_telemetry_publisher_uses_gateway_format(self):
        capture = CapturePublish()
        publisher = MODULE.TelemetryPublisher("sem6000-aabb", capture, qos=0)

        publisher.publish({"power_w": 1.234, "plug_on": True}, timestamp_ms=123)

        self.assertEqual(
            [
                (
                    MODULE.TOPIC_GATEWAY_TELEMETRY,
                    {
                        "sem6000-aabb": [
                            {
                                "ts": 123,
                                "values": {"power_w": 1.234, "plug_on": True},
                            }
                        ]
                    },
                    0,
                )
            ],
            capture.calls,
        )

    def test_attributes_publisher_uses_gateway_format(self):
        capture = CapturePublish()
        publisher = MODULE.AttributesPublisher("sem6000-aabb", capture, qos=1)

        publisher.publish({"plug_on": False, "bridge": "raspberry-sem6000-gw"})

        self.assertEqual(
            [
                (
                    MODULE.TOPIC_GATEWAY_ATTRIBUTES,
                    {
                        "sem6000-aabb": {
                            "plug_on": False,
                            "bridge": "raspberry-sem6000-gw",
                        }
                    },
                    1,
                )
            ],
            capture.calls,
        )

    def test_rpc_responder_formats_gateway_response(self):
        capture = CapturePublish()
        responder = MODULE.RpcResponder(capture, qos=1)

        responder.success("sem6000-aabb", 7, {"plug_on": True})
        responder.error("sem6000-aabb", 8, "bad", code="invalid_request")

        self.assertEqual(
            (
                MODULE.TOPIC_GATEWAY_RPC,
                {
                    "device": "sem6000-aabb",
                    "id": 7,
                    "data": {"success": True, "data": {"plug_on": True}},
                },
                1,
            ),
            capture.calls[0],
        )
        self.assertEqual(
            (
                MODULE.TOPIC_GATEWAY_RPC,
                {
                    "device": "sem6000-aabb",
                    "id": 8,
                    "data": {
                        "success": False,
                        "error": "bad",
                        "code": "invalid_request",
                    },
                },
                1,
            ),
            capture.calls[1],
        )

    def test_gateway_diagnostics_payload_format(self):
        capture = CapturePublish()
        publisher = MODULE.GatewayDiagnosticsPublisher(
            capture,
            control_qos=1,
            telemetry_qos=0,
        )

        publisher.publish_attributes({"bridge": "raspberry-sem6000-gw"})
        publisher.publish_telemetry({"mqtt_connected": True}, timestamp_ms=321)

        self.assertEqual(
            (
                MODULE.TOPIC_GATEWAY_SELF_ATTRIBUTES,
                {"bridge": "raspberry-sem6000-gw"},
                1,
            ),
            capture.calls[0],
        )
        self.assertEqual(
            (
                MODULE.TOPIC_GATEWAY_SELF_TELEMETRY,
                {"ts": 321, "values": {"mqtt_connected": True}},
                0,
            ),
            capture.calls[1],
        )


class GatewayRpcParsingTests(unittest.TestCase):
    def test_parse_gateway_rpc_payload(self):
        task = MODULE.parse_gateway_rpc_payload(
            {
                "device": "sem6000-aabb",
                "data": {"id": 7, "method": "setPower", "params": True},
            },
            expected_device_name="sem6000-aabb",
        )

        self.assertEqual(7, task.request_id)
        self.assertEqual("sem6000-aabb", task.device_name)
        self.assertEqual("setPower", task.method)
        self.assertEqual(True, task.params)
        self.assertEqual("power_set", task.coalesce_key)

    def test_parse_gateway_rpc_payload_rejects_other_device(self):
        with self.assertRaises(MODULE.CommandError) as ctx:
            MODULE.parse_gateway_rpc_payload(
                {
                    "device": "other-device",
                    "data": {"id": 7, "method": "setPower", "params": True},
                },
                expected_device_name="sem6000-aabb",
            )

        self.assertEqual("wrong_device", ctx.exception.code)


class HandlerBehaviorTests(unittest.TestCase):
    def test_get_power_state_uses_cached_state_without_ble(self):
        sem = StubSem()
        telemetry = StubTelemetry()
        attributes = StubAttributes()
        state = MODULE.AgentState(plug_is_on=True)
        context = MODULE.CommandContext(
            sem=sem,
            state=state,
            telemetry=telemetry,
            attributes=attributes,
            config=SimpleNamespace(enable_extended_measurements=False),
        )

        response = MODULE.PowerHandler().handle("getPowerState", None, context)

        self.assertEqual({"plug_on": True}, response)
        self.assertEqual([], sem.set_power_calls)
        self.assertEqual([], telemetry.calls)
        self.assertEqual([], attributes.calls)

    def test_handle_telemetry_tick_skips_ble_when_off(self):
        sem = StubSem()
        telemetry = StubTelemetry()
        attributes = StubAttributes()
        state = MODULE.AgentState(plug_is_on=False, last_power_w=None)
        context = MODULE.CommandContext(
            sem=sem,
            state=state,
            telemetry=telemetry,
            attributes=attributes,
            config=SimpleNamespace(enable_extended_measurements=False),
        )
        agent = object.__new__(MODULE.MqttSem6000Agent)
        agent._log = logging.getLogger("test-agent")

        MODULE.MqttSem6000Agent._handle_telemetry_tick(agent, context)

        self.assertEqual(0, sem.measurement_calls)
        self.assertEqual(0.0, state.last_power_w)
        self.assertEqual(
            [({"power_w": 0.0, "plug_on": False}, None)],
            telemetry.calls,
        )
        self.assertEqual([], attributes.calls)
        self.assertIsInstance(state.last_telemetry_ts_ms, int)

    def test_measurement_handler_returns_extended_values_when_plug_is_active(self):
        sem = StubSem(measurement_result=DummyMeasurement(is_power_active=True))
        telemetry = StubTelemetry()
        attributes = StubAttributes()
        state = MODULE.AgentState()
        context = MODULE.CommandContext(
            sem=sem,
            state=state,
            telemetry=telemetry,
            attributes=attributes,
            config=SimpleNamespace(enable_extended_measurements=False),
        )

        response = MODULE.MeasurementHandler().handle("getMeasurement", None, context)

        self.assertEqual(1.234, response["power_w"])
        self.assertEqual(True, response["plug_on"])
        self.assertEqual(230.2, response["voltage_v"])
        self.assertEqual(0.142, response["current_a"])
        self.assertEqual(49.97, response["frequency_hz"])
        self.assertEqual(12.345678, response["energy_total_kwh"])
        self.assertEqual(1, sem.measurement_calls)
        self.assertEqual(True, state.plug_is_on)
        self.assertEqual(1.234, state.last_power_w)

    def test_handle_telemetry_tick_publishes_extended_values_when_plug_is_active(self):
        sem = StubSem(measurement_result=DummyMeasurement(is_power_active=True))
        telemetry = StubTelemetry()
        attributes = StubAttributes()
        state = MODULE.AgentState()
        context = MODULE.CommandContext(
            sem=sem,
            state=state,
            telemetry=telemetry,
            attributes=attributes,
            config=SimpleNamespace(enable_extended_measurements=False),
        )
        agent = object.__new__(MODULE.MqttSem6000Agent)
        agent._log = logging.getLogger("test-agent")

        MODULE.MqttSem6000Agent._handle_telemetry_tick(agent, context)

        self.assertEqual(1, sem.measurement_calls)
        self.assertEqual([{"plug_on": True}], attributes.calls)
        self.assertEqual(
            [
                (
                    {
                        "power_w": 1.234,
                        "plug_on": True,
                        "voltage_v": 230.2,
                        "current_a": 0.142,
                        "frequency_hz": 49.97,
                        "energy_total_kwh": 12.345678,
                    },
                    None,
                )
            ],
            telemetry.calls,
        )
        self.assertEqual(True, state.plug_is_on)
        self.assertEqual(1.234, state.last_power_w)
        self.assertIsInstance(state.last_telemetry_ts_ms, int)

    def test_get_settings_returns_normalized_payload_and_publishes_attributes(self):
        sem = StubSem(settings_result=DummySettings())
        telemetry = StubTelemetry()
        attributes = StubAttributes()
        context = MODULE.CommandContext(
            sem=sem,
            state=MODULE.AgentState(),
            telemetry=telemetry,
            attributes=attributes,
            config=SimpleNamespace(enable_extended_measurements=False),
        )

        response = MODULE.ConfigurationHandler().handle("getSettings", None, context)

        self.assertEqual(1, sem.request_settings_calls)
        self.assertEqual(False, response["night_mode"])
        self.assertEqual(3680, response["power_limit_w"])
        self.assertEqual(
            [
                {
                    "night_mode": False,
                    "power_limit_w": 3680,
                    "price_normal_cent": 31,
                    "price_reduced_cent": 12,
                    "reduced_period_enabled": True,
                    "reduced_period_start": "23:00",
                    "reduced_period_end": "06:30",
                }
            ],
            attributes.calls,
        )
        self.assertEqual([], telemetry.calls)

    def test_set_night_mode_updates_device_and_attributes(self):
        sem = StubSem()
        attributes = StubAttributes()
        context = MODULE.CommandContext(
            sem=sem,
            state=MODULE.AgentState(),
            telemetry=StubTelemetry(),
            attributes=attributes,
            config=SimpleNamespace(enable_extended_measurements=False),
        )

        response = MODULE.ConfigurationHandler().handle(
            "setNightMode",
            {"enabled": "on"},
            context,
        )

        self.assertEqual([True], sem.set_night_mode_calls)
        self.assertEqual({"night_mode": True}, response)
        self.assertEqual([{"night_mode": True}], attributes.calls)

    def test_set_power_limit_updates_device_and_attributes(self):
        sem = StubSem()
        attributes = StubAttributes()
        context = MODULE.CommandContext(
            sem=sem,
            state=MODULE.AgentState(),
            telemetry=StubTelemetry(),
            attributes=attributes,
            config=SimpleNamespace(enable_extended_measurements=False),
        )

        response = MODULE.ConfigurationHandler().handle("setPowerLimit", 2500, context)

        self.assertEqual([2500], sem.set_power_limit_calls)
        self.assertEqual({"power_limit_w": 2500}, response)
        self.assertEqual([{"power_limit_w": 2500}], attributes.calls)

    def test_set_prices_updates_device_and_attributes(self):
        sem = StubSem()
        attributes = StubAttributes()
        context = MODULE.CommandContext(
            sem=sem,
            state=MODULE.AgentState(),
            telemetry=StubTelemetry(),
            attributes=attributes,
            config=SimpleNamespace(enable_extended_measurements=False),
        )

        response = MODULE.ConfigurationHandler().handle(
            "setPrices",
            {"normal_price_cent": 22, "reduced_price_cent": 7},
            context,
        )

        self.assertEqual([(22, 7)], sem.set_prices_calls)
        self.assertEqual(
            {"prices": {"normal_price_cent": 22, "reduced_price_cent": 7}},
            response,
        )
        self.assertEqual(
            [{"price_normal_cent": 22, "price_reduced_cent": 7}],
            attributes.calls,
        )

    def test_set_reduced_period_updates_device_and_attributes(self):
        sem = StubSem()
        attributes = StubAttributes()
        context = MODULE.CommandContext(
            sem=sem,
            state=MODULE.AgentState(),
            telemetry=StubTelemetry(),
            attributes=attributes,
            config=SimpleNamespace(enable_extended_measurements=False),
        )

        response = MODULE.ConfigurationHandler().handle(
            "setReducedPeriod",
            {"enabled": True, "start": "01:30:00", "end": "06:45"},
            context,
        )

        self.assertEqual([(True, "01:30", "06:45")], sem.set_reduced_period_calls)
        self.assertEqual(
            {
                "reduced_period": {
                    "enabled": True,
                    "start": "01:30",
                    "end": "06:45",
                }
            },
            response,
        )
        self.assertEqual(
            [
                {
                    "reduced_period_enabled": True,
                    "reduced_period_start": "01:30",
                    "reduced_period_end": "06:45",
                }
            ],
            attributes.calls,
        )

    def test_get_device_name_returns_name_and_publishes_attribute(self):
        sem = StubSem(device_name="Kitchen Plug")
        attributes = StubAttributes()
        context = MODULE.CommandContext(
            sem=sem,
            state=MODULE.AgentState(),
            telemetry=StubTelemetry(),
            attributes=attributes,
            config=SimpleNamespace(enable_extended_measurements=False),
        )

        response = MODULE.IdentityHandler().handle("getDeviceName", None, context)

        self.assertEqual(1, sem.request_device_name_calls)
        self.assertEqual({"device_name": "Kitchen Plug"}, response)
        self.assertEqual([{"device_name": "Kitchen Plug"}], attributes.calls)

    def test_set_device_name_validates_and_updates_attribute(self):
        sem = StubSem()
        attributes = StubAttributes()
        context = MODULE.CommandContext(
            sem=sem,
            state=MODULE.AgentState(),
            telemetry=StubTelemetry(),
            attributes=attributes,
            config=SimpleNamespace(enable_extended_measurements=False),
        )

        response = MODULE.IdentityHandler().handle(
            "setDeviceName",
            {"device_name": "Desk Plug"},
            context,
        )

        self.assertEqual(["Desk Plug"], sem.change_device_name_calls)
        self.assertEqual({"device_name": "Desk Plug"}, response)
        self.assertEqual([{"device_name": "Desk Plug"}], attributes.calls)

    def test_get_device_serial_returns_serial(self):
        sem = StubSem(device_serial="SERIAL-001")
        context = MODULE.CommandContext(
            sem=sem,
            state=MODULE.AgentState(),
            telemetry=StubTelemetry(),
            attributes=StubAttributes(),
            config=SimpleNamespace(enable_extended_measurements=False),
        )

        response = MODULE.IdentityHandler().handle("getDeviceSerial", None, context)

        self.assertEqual(1, sem.request_device_serial_calls)
        self.assertEqual({"device_serial": "SERIAL-001"}, response)

    def test_set_device_name_rejects_too_long_names(self):
        sem = StubSem()
        context = MODULE.CommandContext(
            sem=sem,
            state=MODULE.AgentState(),
            telemetry=StubTelemetry(),
            attributes=StubAttributes(),
            config=SimpleNamespace(enable_extended_measurements=False),
        )

        with self.assertRaises(MODULE.CommandError) as ctx:
            MODULE.IdentityHandler().handle(
                "setDeviceName",
                {"device_name": "0123456789012345678"},
                context,
            )

        self.assertEqual("invalid_params", ctx.exception.code)
        self.assertEqual([], sem.change_device_name_calls)

    def test_get_timer_returns_normalized_payload_and_publishes_attributes(self):
        sem = StubSem(timer_status_result=DummyTimerStatus())
        attributes = StubAttributes()
        context = MODULE.CommandContext(
            sem=sem,
            state=MODULE.AgentState(),
            telemetry=StubTelemetry(),
            attributes=attributes,
            config=SimpleNamespace(enable_extended_measurements=False),
        )

        response = MODULE.TimerHandler().handle("getTimer", None, context)

        self.assertEqual(1, sem.request_timer_status_calls)
        self.assertEqual(True, response["timer_active"])
        self.assertEqual("on", response["action"])
        self.assertEqual(
            [
                {
                    "timer_active": True,
                    "timer_action": "on",
                    "timer_target_isodatetime": "2026-04-13T18:30:00",
                    "timer_original_length_seconds": 300,
                }
            ],
            attributes.calls,
        )

    def test_set_timer_activates_timer_and_returns_status(self):
        sem = StubSem(timer_status_result=DummyTimerStatus(is_action_turn_on=False))
        attributes = StubAttributes()
        context = MODULE.CommandContext(
            sem=sem,
            state=MODULE.AgentState(),
            telemetry=StubTelemetry(),
            attributes=attributes,
            config=SimpleNamespace(enable_extended_measurements=False),
        )

        response = MODULE.TimerHandler().handle(
            "setTimer",
            {
                "action": "off",
                "target_isodatetime": "2026-04-13T18:30",
            },
            context,
        )

        self.assertEqual(
            [(False, "2026-04-13T18:30:00")],
            sem.activate_timer_at_calls,
        )
        self.assertEqual(1, sem.request_timer_status_calls)
        self.assertEqual(True, response["timer_active"])
        self.assertEqual("off", response["action"])
        self.assertEqual(
            [
                {
                    "timer_active": True,
                    "timer_action": "off",
                    "timer_target_isodatetime": "2026-04-13T18:30:00",
                    "timer_original_length_seconds": 300,
                }
            ],
            attributes.calls,
        )

    def test_reset_timer_resets_timer_and_returns_status(self):
        sem = StubSem(timer_status_result=DummyTimerStatus(is_active=False))
        attributes = StubAttributes()
        context = MODULE.CommandContext(
            sem=sem,
            state=MODULE.AgentState(),
            telemetry=StubTelemetry(),
            attributes=attributes,
            config=SimpleNamespace(enable_extended_measurements=False),
        )

        response = MODULE.TimerHandler().handle("resetTimer", None, context)

        self.assertEqual(1, sem.reset_timer_calls)
        self.assertEqual(1, sem.request_timer_status_calls)
        self.assertEqual(False, response["timer_active"])
        self.assertEqual(
            [
                {
                    "timer_active": False,
                    "timer_action": "on",
                    "timer_target_isodatetime": "2026-04-13T18:30:00",
                    "timer_original_length_seconds": 300,
                }
            ],
            attributes.calls,
        )

    def test_set_timer_rejects_missing_target(self):
        sem = StubSem()
        context = MODULE.CommandContext(
            sem=sem,
            state=MODULE.AgentState(),
            telemetry=StubTelemetry(),
            attributes=StubAttributes(),
            config=SimpleNamespace(enable_extended_measurements=False),
        )

        with self.assertRaises(MODULE.CommandError) as ctx:
            MODULE.TimerHandler().handle(
                "setTimer",
                {"action": "on"},
                context,
            )

        self.assertEqual("invalid_params", ctx.exception.code)
        self.assertEqual([], sem.activate_timer_at_calls)

    def test_get_random_mode_returns_normalized_payload_and_publishes_attributes(self):
        sem = StubSem(random_mode_result=DummyRandomModeStatus())
        attributes = StubAttributes()
        context = MODULE.CommandContext(
            sem=sem,
            state=MODULE.AgentState(),
            telemetry=StubTelemetry(),
            attributes=attributes,
            config=SimpleNamespace(enable_extended_measurements=False),
        )

        response = MODULE.RandomModeHandler().handle("getRandomMode", None, context)

        self.assertEqual(1, sem.request_random_mode_status_calls)
        self.assertEqual(True, response["enabled"])
        self.assertEqual("Mon,Wed,Fri", response["weekdays"])
        self.assertEqual(
            [
                {
                    "random_mode_enabled": True,
                    "random_mode_weekdays": "Mon,Wed,Fri",
                    "random_mode_start": "18:00",
                    "random_mode_end": "23:00",
                }
            ],
            attributes.calls,
        )

    def test_set_random_mode_updates_device_and_attributes(self):
        sem = StubSem(random_mode_result=DummyRandomModeStatus())
        attributes = StubAttributes()
        context = MODULE.CommandContext(
            sem=sem,
            state=MODULE.AgentState(),
            telemetry=StubTelemetry(),
            attributes=attributes,
            config=SimpleNamespace(enable_extended_measurements=False),
        )

        response = MODULE.RandomModeHandler().handle(
            "setRandomMode",
            {"weekdays": "mon,wed,fri", "start": "18:00:00", "end": "23:00"},
            context,
        )

        self.assertEqual(
            [("Mon,Wed,Fri", "18:00", "23:00")],
            sem.change_random_mode_calls,
        )
        self.assertEqual(1, sem.request_random_mode_status_calls)
        self.assertEqual(True, response["enabled"])
        self.assertEqual("Mon,Wed,Fri", response["weekdays"])
        self.assertEqual(
            [
                {
                    "random_mode_enabled": True,
                    "random_mode_weekdays": "Mon,Wed,Fri",
                    "random_mode_start": "18:00",
                    "random_mode_end": "23:00",
                }
            ],
            attributes.calls,
        )

    def test_reset_random_mode_disables_mode_and_returns_status(self):
        sem = StubSem(random_mode_result=DummyRandomModeStatus(is_active=False, active_on_weekdays=[]))
        attributes = StubAttributes()
        context = MODULE.CommandContext(
            sem=sem,
            state=MODULE.AgentState(),
            telemetry=StubTelemetry(),
            attributes=attributes,
            config=SimpleNamespace(enable_extended_measurements=False),
        )

        response = MODULE.RandomModeHandler().handle("resetRandomMode", None, context)

        self.assertEqual(1, sem.reset_random_mode_calls)
        self.assertEqual(1, sem.request_random_mode_status_calls)
        self.assertEqual(False, response["enabled"])
        self.assertEqual(
            [
                {
                    "random_mode_enabled": False,
                    "random_mode_weekdays": "",
                    "random_mode_start": "18:00",
                    "random_mode_end": "23:00",
                }
            ],
            attributes.calls,
        )

    def test_set_random_mode_rejects_missing_weekdays(self):
        sem = StubSem()
        context = MODULE.CommandContext(
            sem=sem,
            state=MODULE.AgentState(),
            telemetry=StubTelemetry(),
            attributes=StubAttributes(),
            config=SimpleNamespace(enable_extended_measurements=False),
        )

        with self.assertRaises(MODULE.CommandError) as ctx:
            MODULE.RandomModeHandler().handle(
                "setRandomMode",
                {"start": "18:00", "end": "23:00"},
                context,
            )

        self.assertEqual("invalid_params", ctx.exception.code)
        self.assertEqual([], sem.change_random_mode_calls)

    def test_set_random_mode_rejects_missing_start(self):
        sem = StubSem()
        context = MODULE.CommandContext(
            sem=sem,
            state=MODULE.AgentState(),
            telemetry=StubTelemetry(),
            attributes=StubAttributes(),
            config=SimpleNamespace(enable_extended_measurements=False),
        )

        with self.assertRaises(MODULE.CommandError) as ctx:
            MODULE.RandomModeHandler().handle(
                "setRandomMode",
                {"weekdays": "Mon,Fri", "end": "23:00"},
                context,
            )

        self.assertEqual("invalid_params", ctx.exception.code)
        self.assertEqual([], sem.change_random_mode_calls)

    def test_get_schedulers_returns_normalized_entries(self):
        scheduler_result = DummySchedulerNotification(
            [
                DummySchedulerEntry(
                    2,
                    DummyScheduler(
                        is_active=False,
                        is_action_turn_on=False,
                        repeat_on_weekdays=[1, 3, 5],
                        isodatetime="2026-05-01T18:45",
                    ),
                ),
                DummySchedulerEntry(
                    0,
                    DummyScheduler(
                        is_active=True,
                        is_action_turn_on=True,
                        repeat_on_weekdays=[],
                        isodatetime="2026-05-02T07:15",
                    ),
                ),
            ]
        )
        sem = StubSem(scheduler_result=scheduler_result)
        context = MODULE.CommandContext(
            sem=sem,
            state=MODULE.AgentState(),
            telemetry=StubTelemetry(),
            attributes=StubAttributes(),
            config=SimpleNamespace(enable_extended_measurements=False),
        )

        response = MODULE.ScheduleHandler().handle("getSchedulers", None, context)

        self.assertEqual(1, sem.request_scheduler_calls)
        self.assertEqual(2, response["scheduler_count"])
        self.assertEqual(
            {
                "slot_id": 0,
                "type": "onetime",
                "enabled": True,
                "action": "on",
                "target_isodatetime": "2026-05-02T07:15:00",
            },
            response["schedulers"][0],
        )
        self.assertEqual(
            {
                "slot_id": 2,
                "type": "repeated",
                "enabled": False,
                "action": "off",
                "weekdays": "Mon,Wed,Fri",
                "time": "18:45",
            },
            response["schedulers"][1],
        )

    def test_add_onetime_scheduler_refreshes_scheduler_list(self):
        sem = StubSem(
            scheduler_result=DummySchedulerNotification(
                [
                    DummySchedulerEntry(
                        1,
                        DummyScheduler(
                            is_active=True,
                            is_action_turn_on=False,
                            isodatetime="2026-05-03T10:15:00",
                        ),
                    )
                ]
            )
        )
        context = MODULE.CommandContext(
            sem=sem,
            state=MODULE.AgentState(),
            telemetry=StubTelemetry(),
            attributes=StubAttributes(),
            config=SimpleNamespace(enable_extended_measurements=False),
        )

        response = MODULE.ScheduleHandler().handle(
            "addOnetimeScheduler",
            {
                "enabled": True,
                "action": "off",
                "target_isodatetime": "2026-05-03T10:15",
            },
            context,
        )

        self.assertEqual(
            [(True, False, "2026-05-03T10:15:00")],
            sem.add_onetime_scheduler_calls,
        )
        self.assertEqual(1, sem.request_scheduler_calls)
        self.assertEqual(1, response["scheduler_count"])
        self.assertEqual("onetime", response["schedulers"][0]["type"])

    def test_add_scheduler_alias_supports_repeated_entries(self):
        sem = StubSem(
            scheduler_result=DummySchedulerNotification(
                [
                    DummySchedulerEntry(
                        3,
                        DummyScheduler(
                            is_active=True,
                            is_action_turn_on=False,
                            repeat_on_weekdays=[1, 5],
                            isodatetime="2026-05-03T21:30",
                        ),
                    )
                ]
            )
        )
        context = MODULE.CommandContext(
            sem=sem,
            state=MODULE.AgentState(),
            telemetry=StubTelemetry(),
            attributes=StubAttributes(),
            config=SimpleNamespace(enable_extended_measurements=False),
        )

        response = MODULE.ScheduleHandler().handle(
            "addScheduler",
            {
                "type": "repeated",
                "active": True,
                "turn_on": False,
                "weekdays": ["Mon", "Fri"],
                "isotime": "21:30:00",
            },
            context,
        )

        self.assertEqual(
            [(True, False, "Mon,Fri", "21:30")],
            sem.add_repeated_scheduler_calls,
        )
        self.assertEqual(1, sem.request_scheduler_calls)
        self.assertEqual("repeated", response["schedulers"][0]["type"])
        self.assertEqual("Mon,Fri", response["schedulers"][0]["weekdays"])

    def test_remove_scheduler_accepts_raw_slot_id(self):
        sem = StubSem(
            scheduler_result=DummySchedulerNotification([]),
        )
        context = MODULE.CommandContext(
            sem=sem,
            state=MODULE.AgentState(),
            telemetry=StubTelemetry(),
            attributes=StubAttributes(),
            config=SimpleNamespace(enable_extended_measurements=False),
        )

        response = MODULE.ScheduleHandler().handle("removeScheduler", 0, context)

        self.assertEqual([0], sem.remove_scheduler_calls)
        self.assertEqual(1, sem.request_scheduler_calls)
        self.assertEqual({"scheduler_count": 0, "schedulers": []}, response)

    def test_get_consumption_23h_returns_normalized_samples(self):
        sem = StubSem(consumption23h_result=DummyConsumption23Hours())
        context = MODULE.CommandContext(
            sem=sem,
            state=MODULE.AgentState(),
            telemetry=StubTelemetry(),
            attributes=StubAttributes(),
            config=SimpleNamespace(enable_extended_measurements=False),
        )

        response = MODULE.ConsumptionHandler().handle("getConsumption23h", None, context)

        self.assertEqual(1, sem.request_consumption_of_last_23_hours_calls)
        self.assertEqual("hour", response["interval"])
        self.assertEqual("Wh", response["unit"])
        self.assertEqual(3, response["sample_count"])
        self.assertEqual(0, response["samples"][0]["hours_ago"])
        self.assertEqual(50, response["samples"][0]["consumption_wh"])
        self.assertIsNone(response["samples"][1]["consumption_wh"])
        self.assertIn("timestamp_local", response["samples"][0])
        self.assertIn("isotime", response["samples"][0])

    def test_get_consumption_30d_returns_date_labels(self):
        sem = StubSem(consumption30d_result=DummyConsumption30Days())
        context = MODULE.CommandContext(
            sem=sem,
            state=MODULE.AgentState(),
            telemetry=StubTelemetry(),
            attributes=StubAttributes(),
            config=SimpleNamespace(enable_extended_measurements=False),
        )

        response = MODULE.ConsumptionHandler().handle("getConsumption30d", None, context)

        self.assertEqual(1, sem.request_consumption_of_last_30_days_calls)
        self.assertEqual("day", response["interval"])
        self.assertEqual("Wh", response["unit"])
        self.assertEqual(3, response["sample_count"])
        self.assertEqual(0, response["samples"][0]["days_ago"])
        self.assertEqual(120, response["samples"][0]["consumption_wh"])
        self.assertRegex(response["samples"][0]["date"], r"^\d{4}-\d{2}-\d{2}$")

    def test_get_consumption_12m_returns_year_month_labels(self):
        sem = StubSem(consumption12m_result=DummyConsumption12Months())
        context = MODULE.CommandContext(
            sem=sem,
            state=MODULE.AgentState(),
            telemetry=StubTelemetry(),
            attributes=StubAttributes(),
            config=SimpleNamespace(enable_extended_measurements=False),
        )

        response = MODULE.ConsumptionHandler().handle("getConsumption12m", None, context)

        self.assertEqual(1, sem.request_consumption_of_last_12_months_calls)
        self.assertEqual("month", response["interval"])
        self.assertEqual(3, response["sample_count"])
        self.assertEqual(0, response["samples"][0]["months_ago"])
        self.assertEqual(900, response["samples"][0]["consumption_wh"])
        self.assertRegex(response["samples"][0]["year_month"], r"^\d{4}-\d{2}$")

    def test_reset_consumption_returns_confirmation(self):
        sem = StubSem()
        context = MODULE.CommandContext(
            sem=sem,
            state=MODULE.AgentState(),
            telemetry=StubTelemetry(),
            attributes=StubAttributes(),
            config=SimpleNamespace(enable_extended_measurements=False),
        )

        response = MODULE.ConsumptionHandler().handle("resetConsumption", None, context)

        self.assertEqual(1, sem.reset_consumption_calls)
        self.assertEqual({"consumption_reset": True}, response)

    def test_admin_change_pin_calls_backend(self):
        sem = StubSem()
        context = MODULE.CommandContext(
            sem=sem,
            state=MODULE.AgentState(),
            telemetry=StubTelemetry(),
            attributes=StubAttributes(),
            config=SimpleNamespace(enable_extended_measurements=False),
        )

        response = MODULE.AdministrativeHandler().handle(
            "adminChangePin",
            {"new_pin": "1234"},
            context,
        )

        self.assertEqual(["1234"], sem.change_pin_calls)
        self.assertEqual({"pin_changed": True}, response)

    def test_admin_change_pin_rejects_invalid_pin(self):
        sem = StubSem()
        context = MODULE.CommandContext(
            sem=sem,
            state=MODULE.AgentState(),
            telemetry=StubTelemetry(),
            attributes=StubAttributes(),
            config=SimpleNamespace(enable_extended_measurements=False),
        )

        with self.assertRaises(MODULE.CommandError) as ctx:
            MODULE.AdministrativeHandler().handle(
                "adminChangePin",
                {"new_pin": "12ab"},
                context,
            )

        self.assertEqual("invalid_params", ctx.exception.code)
        self.assertEqual([], sem.change_pin_calls)

    def test_admin_factory_reset_returns_default_pin_hint(self):
        sem = StubSem()
        context = MODULE.CommandContext(
            sem=sem,
            state=MODULE.AgentState(),
            telemetry=StubTelemetry(),
            attributes=StubAttributes(),
            config=SimpleNamespace(enable_extended_measurements=False),
        )

        response = MODULE.AdministrativeHandler().handle(
            "adminFactoryReset",
            None,
            context,
        )

        self.assertEqual(1, sem.factory_reset_calls)
        self.assertEqual(
            {"factory_reset": True, "active_pin": "0000"},
            response,
        )


if __name__ == "__main__":
    unittest.main()
