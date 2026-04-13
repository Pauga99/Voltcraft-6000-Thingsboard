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


class CapturePublish:
    def __init__(self):
        self.calls = []

    def __call__(self, topic, payload, qos):
        self.calls.append((topic, payload, qos))


class StubSem:
    def __init__(self, measurement_result=None):
        self.set_power_calls = []
        self.measurement_calls = 0
        self.measurement_result = measurement_result
        self.sync_time_calls = []

    def set_power(self, target_on):
        self.set_power_calls.append(target_on)

    def request_measurement(self):
        self.measurement_calls += 1
        if self.measurement_result is None:
            raise AssertionError("BLE measurement should not be called in this test")
        return self.measurement_result

    def sync_time(self, iso_datetime):
        self.sync_time_calls.append(iso_datetime)


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


if __name__ == "__main__":
    unittest.main()
