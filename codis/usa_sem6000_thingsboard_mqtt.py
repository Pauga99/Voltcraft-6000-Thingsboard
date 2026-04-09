"""Passarella MQTT entre un SEM6000 i ThingsBoard en mode gateway."""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import signal
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Deque, Dict, Optional, Protocol

try:
    import paho.mqtt.client as mqtt
except ModuleNotFoundError:
    mqtt = None

FIXED_SEM6000_DEVICE_ADDRESS = "b3:00:00:00:30:43"
FIXED_THINGSBOARD_GATEWAY_ACCESS_TOKEN = "PgcsA0leXeslOFsDO2Lk"

TOPIC_GATEWAY_CONNECT = "v1/gateway/connect"
TOPIC_GATEWAY_DISCONNECT = "v1/gateway/disconnect"
TOPIC_GATEWAY_TELEMETRY = "v1/gateway/telemetry"
TOPIC_GATEWAY_ATTRIBUTES = "v1/gateway/attributes"
TOPIC_GATEWAY_RPC = "v1/gateway/rpc"

TOPIC_GATEWAY_SELF_TELEMETRY = "v1/devices/me/telemetry"
TOPIC_GATEWAY_SELF_ATTRIBUTES = "v1/devices/me/attributes"

POWER_METRIC_KEY = "power_w"
POWER_STATE_KEY = "plug_on"

BRIDGE_NAME = "raspberry-sem6000-gw"
DEFAULT_DIAGNOSTICS_INTERVAL_SECONDS = 30.0

POWER_MUTATING_METHODS = {
    "setpower",
    "setswitch",
    "setrelay",
    "power",
    "poweron",
    "poweroff",
    "on",
    "off",
}


def utc_ms() -> int:
    """Retorna el timestamp actual en milisegons."""
    return int(time.time() * 1000)


def compact_json(payload: Any) -> str:
    """Serialitza JSON sense espais sobrers per reduir la mida del missatge MQTT."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def normalize_method(value: str) -> str:
    """Normalitza noms de metode RPC per comparar-los de forma estable."""
    return str(value).strip().lower()


def default_child_device_name(device_address: str) -> str:
    """Construeix un nom de dispositiu fill deterministic a partir de la MAC."""
    normalized = "".join(ch for ch in str(device_address).lower() if ch.isalnum())
    suffix = normalized or "unknown"
    return f"sem6000-{suffix}"


def coalesce_key_for_method(method_name: str) -> Optional[str]:
    """Agrupa ordres RPC mutadores per aplicar la politica "l'ultima guanya"."""
    if normalize_method(method_name) in POWER_MUTATING_METHODS:
        return "power_set"
    return None


def parse_boolean_value(value: Any) -> Optional[bool]:
    """Accepta bools, numeros, strings i objectes habituals i els converteix a boolea."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {
            "1",
            "true",
            "on",
            "yes",
            "enabled",
            "enable",
            "encen",
            "ences",
        }:
            return True
        if normalized in {
            "0",
            "false",
            "off",
            "no",
            "disabled",
            "disable",
            "apagat",
            "apaga",
        }:
            return False
        return None
    if isinstance(value, dict):
        for key in ("enabled", "on", "state", "power", "value"):
            if key in value:
                return parse_boolean_value(value[key])
    return None


def _to_float(value: Any) -> Optional[float]:
    """Converteix un valor arbitrari a float o retorna None si no es pot."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def map_measurement_to_values(
    measurement: Any,
    include_extended: bool,
) -> Dict[str, Any]:
    """Tradueix una lectura del SEM6000 a claus de telemetria de ThingsBoard."""
    values: Dict[str, Any] = {}

    power_mw = _to_float(getattr(measurement, "power_in_milliwatt", None))
    if power_mw is not None:
        values[POWER_METRIC_KEY] = round(power_mw / 1000.0, 3)

    plug_state = getattr(measurement, "is_power_active", None)
    if plug_state is not None:
        values[POWER_STATE_KEY] = bool(plug_state)

    if include_extended:
        voltage = _to_float(getattr(measurement, "voltage_in_volt", None))
        if voltage is not None:
            values["voltage_v"] = round(voltage, 3)

        current_ma = _to_float(getattr(measurement, "current_in_milliampere", None))
        if current_ma is not None:
            values["current_a"] = round(current_ma / 1000.0, 3)

        frequency = _to_float(getattr(measurement, "frequency_in_hertz", None))
        if frequency is not None:
            values["frequency_hz"] = round(frequency, 3)

        total_kwh = _to_float(
            getattr(measurement, "total_consumption_in_kilowatt_hour", None)
        )
        if total_kwh is not None:
            values["energy_total_kwh"] = round(total_kwh, 6)

    return values


def should_include_extended_measurements(
    measurement: Any,
    force_extended: bool,
) -> bool:
    """Decideix si cal publicar les mesures esteses per a una lectura concreta."""
    if force_extended:
        return True
    return bool(getattr(measurement, "is_power_active", False))


class CommandError(Exception):
    """Error funcional retornable a ThingsBoard amb un codi controlat."""

    def __init__(self, message: str, code: str = "command_error"):
        super().__init__(message)
        self.code = code


def parse_env_bool(name: str, default: bool) -> bool:
    """Llegeix una variable d'entorn booleana reutilitzant el parser generic."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    parsed = parse_boolean_value(raw_value)
    if parsed is None:
        raise SystemExit(
            f"Valor invalid per {name}: {raw_value}. Usa true/false, on/off o 1/0."
        )
    return parsed


def parse_env_qos(name: str, default: int) -> int:
    """Valida que el QoS llegit de l'entorn sigui 0, 1 o 2."""
    raw_value = os.getenv(name)
    qos = default if raw_value is None else int(raw_value)
    if qos not in {0, 1, 2}:
        raise SystemExit(f"Valor invalid per {name}: {qos}. Usa 0, 1 o 2.")
    return qos


def build_gateway_connect_payload(device_name: str, device_type: str) -> Dict[str, Any]:
    """Payload que dona d'alta el dispositiu fill al gateway MQTT."""
    return {"device": device_name, "type": device_type}


def build_gateway_disconnect_payload(device_name: str) -> Dict[str, Any]:
    """Payload que informa ThingsBoard que el dispositiu fill deixa d'estar present."""
    return {"device": device_name}


def build_child_telemetry_payload(
    device_name: str,
    values: Dict[str, Any],
    timestamp_ms: Optional[int] = None,
) -> Dict[str, Any]:
    """Empaqueta telemetria del fill en el format esperat per ThingsBoard gateway."""
    ts = timestamp_ms if timestamp_ms is not None else utc_ms()
    return {device_name: [{"ts": ts, "values": values}]}


def build_child_attributes_payload(
    device_name: str,
    attributes: Dict[str, Any],
) -> Dict[str, Any]:
    """Empaqueta atributs del dispositiu fill per publicar-los via gateway."""
    return {device_name: attributes}


def build_gateway_rpc_response_payload(
    device_name: str,
    request_id: Any,
    data: Dict[str, Any],
) -> Dict[str, Any]:
    """Construeix la resposta estandard a una RPC de gateway."""
    return {"device": device_name, "id": request_id, "data": data}


@dataclass(frozen=True)
class AppConfig:
    """Configuracio immutable carregada des de variables d'entorn."""

    sem6000_device_address: str
    sem6000_pin: str
    sem6000_timeout_seconds: float
    sem6000_debug: bool
    tb_host: str
    tb_gateway_access_token: str
    tb_client_id: str
    tb_control_qos: int
    tb_telemetry_qos: int
    tb_keepalive: int
    tb_tls_mode: str
    tb_tls_port: int
    tb_plain_port: int
    tb_child_device_name: str
    tb_child_device_type: str
    telemetry_interval_on_seconds: float
    off_heartbeat_seconds: float
    rpc_queue_size: int
    mqtt_connect_timeout_seconds: float
    enable_extended_measurements: bool
    log_level: str

    @classmethod
    def from_env(cls) -> "AppConfig":
        tls_mode = os.getenv("THINGSBOARD_TLS_MODE", "fallback").strip().lower()
        if tls_mode not in {"required", "disabled", "fallback"}:
            raise SystemExit(
                "THINGSBOARD_TLS_MODE invalid. Valors permesos: required, disabled, fallback."
            )

        device_address = FIXED_SEM6000_DEVICE_ADDRESS
        child_name = os.getenv(
            "THINGSBOARD_CHILD_DEVICE_NAME",
            default_child_device_name(device_address),
        ).strip()
        child_type = os.getenv(
            "THINGSBOARD_CHILD_DEVICE_TYPE",
            "Voltcraft SEM6000",
        ).strip()

        access_token = FIXED_THINGSBOARD_GATEWAY_ACCESS_TOKEN

        telemetry_interval_on = float(
            os.getenv("TELEMETRY_INTERVAL_ON_SECONDS", "1")
        )
        if telemetry_interval_on <= 0:
            raise SystemExit("TELEMETRY_INTERVAL_ON_SECONDS ha de ser > 0.")

        off_heartbeat = float(os.getenv("OFF_HEARTBEAT_SECONDS", "30"))
        if off_heartbeat <= 0:
            raise SystemExit("OFF_HEARTBEAT_SECONDS ha de ser > 0.")

        queue_size = int(os.getenv("RPC_QUEUE_SIZE", "128"))
        if queue_size <= 0:
            raise SystemExit("RPC_QUEUE_SIZE ha de ser > 0.")
        if not child_name:
            raise SystemExit("THINGSBOARD_CHILD_DEVICE_NAME no pot ser buit.")
        if not child_type:
            raise SystemExit("THINGSBOARD_CHILD_DEVICE_TYPE no pot ser buit.")

        return cls(
            sem6000_device_address=device_address,
            sem6000_pin=os.getenv("SEM6000_PIN", "0000").strip(),
            sem6000_timeout_seconds=float(os.getenv("SEM6000_TIMEOUT_SECONDS", "3")),
            sem6000_debug=parse_env_bool("SEM6000_DEBUG", False),
            tb_host=os.getenv("THINGSBOARD_MQTT_HOST", "mqtt.eu.thingsboard.cloud").strip(),
            tb_gateway_access_token=access_token,
            tb_client_id=os.getenv("THINGSBOARD_CLIENT_ID", "sem6000-rpi2b").strip(),
            tb_control_qos=parse_env_qos("THINGSBOARD_CONTROL_QOS", 1),
            tb_telemetry_qos=parse_env_qos("THINGSBOARD_TELEMETRY_QOS", 0),
            tb_keepalive=int(os.getenv("THINGSBOARD_KEEPALIVE", "30")),
            tb_tls_mode=tls_mode,
            tb_tls_port=int(os.getenv("THINGSBOARD_MQTT_PORT_TLS", "8883")),
            tb_plain_port=int(os.getenv("THINGSBOARD_MQTT_PORT_PLAIN", "1883")),
            tb_child_device_name=child_name,
            tb_child_device_type=child_type,
            telemetry_interval_on_seconds=telemetry_interval_on,
            off_heartbeat_seconds=off_heartbeat,
            rpc_queue_size=queue_size,
            mqtt_connect_timeout_seconds=float(
                os.getenv("MQTT_CONNECT_TIMEOUT_SECONDS", "10")
            ),
            enable_extended_measurements=parse_env_bool(
                "ENABLE_EXTENDED_MEASUREMENTS", False
            ),
            log_level=os.getenv("LOG_LEVEL", "INFO").strip(),
        )


@dataclass(frozen=True)
class RpcTask:
    """Ordre RPC ja validada i preparada per entrar a la cua interna."""

    request_id: Any
    device_name: str
    method: str
    params: Any
    coalesce_key: Optional[str]


def parse_gateway_rpc_payload(payload: Any, expected_device_name: str) -> RpcTask:
    """Valida l'estructura RPC del gateway i en retorna una tasca interna."""
    if not isinstance(payload, dict):
        raise CommandError(
            "El payload RPC ha de ser un objecte JSON.",
            code="invalid_request",
        )

    device_name = str(payload.get("device", "")).strip()
    if not device_name:
        raise CommandError(
            "Falta el camp device al payload RPC.",
            code="invalid_request",
        )
    if device_name != expected_device_name:
        raise CommandError(
            f"RPC adrecat a un altre dispositiu fill: {device_name}.",
            code="wrong_device",
        )

    data = payload.get("data")
    if not isinstance(data, dict):
        raise CommandError(
            "Falta l'objecte data al payload RPC.",
            code="invalid_request",
        )

    request_id = data.get("id")
    if request_id in {None, ""}:
        raise CommandError(
            "Falta el camp id al payload RPC.",
            code="invalid_request",
        )

    method_name = str(data.get("method", "")).strip()
    if not method_name:
        raise CommandError(
            "Falta el camp method al payload RPC.",
            code="invalid_request",
        )

    return RpcTask(
        request_id=request_id,
        device_name=device_name,
        method=method_name,
        params=data.get("params"),
        coalesce_key=coalesce_key_for_method(method_name),
    )


@dataclass
class AgentState:
    """Estat runtime compartit entre callbacks MQTT i fils de treball."""

    plug_is_on: Optional[bool] = None
    last_power_w: Optional[float] = None
    last_telemetry_ts_ms: Optional[int] = None
    mqtt_connected: bool = False
    last_rpc_total_ms: Optional[float] = None


class RpcTaskQueue:
    """Cua thread-safe amb coalescing i limit de mida."""

    def __init__(self, maxsize: int):
        self._maxsize = maxsize
        self._queue: Deque[RpcTask] = deque()
        self._condition = threading.Condition()

    def put(self, task: RpcTask) -> tuple[list[RpcTask], list[RpcTask]]:
        with self._condition:
            superseded: list[RpcTask] = []
            dropped: list[RpcTask] = []

            if task.coalesce_key is not None:
                filtered: Deque[RpcTask] = deque()
                for existing in self._queue:
                    if existing.coalesce_key == task.coalesce_key:
                        superseded.append(existing)
                    else:
                        filtered.append(existing)
                self._queue = filtered

            while len(self._queue) >= self._maxsize:
                dropped.append(self._queue.popleft())

            self._queue.append(task)
            self._condition.notify()
            return superseded, dropped

    def get(self, timeout: float) -> Optional[RpcTask]:
        deadline = time.monotonic() + timeout
        with self._condition:
            while not self._queue:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._condition.wait(timeout=remaining)
            return self._queue.popleft()

    def size(self) -> int:
        with self._condition:
            return len(self._queue)


class Sem6000Session:
    """Encapsula la sessio BLE i serialitza totes les operacions sobre el dispositiu."""

    def __init__(
        self,
        address: str,
        pin: str,
        timeout_seconds: float,
        debug: bool,
        log: logging.Logger,
    ) -> None:
        self._address = address
        self._pin = pin
        self._timeout_seconds = timeout_seconds
        self._debug = debug
        self._log = log

        self._device: Any = None
        self._lock = threading.Lock()
        self._sem6000_module: Any = None
        self._is_connected = False
        self._last_operation_ms: Optional[float] = None

    def _import_sem6000_module(self) -> Any:
        if self._sem6000_module is not None:
            return self._sem6000_module
        try:
            import usa_sem6000 as sem_module
        except BaseException as exc:
            raise CommandError(
                f"No s'ha pogut importar usa_sem6000: {exc}",
                code="ble_dependency_error",
            ) from exc
        self._sem6000_module = sem_module
        return sem_module

    def _new_device(self) -> Any:
        sem_module = self._import_sem6000_module()
        sem6000_mod = sem_module.sem6000
        return sem6000_mod.SEM6000(
            deviceAddr=self._address,
            pin=self._pin,
            timeout=self._timeout_seconds,
            debug=self._debug,
        )

    def _ensure_connected_locked(self) -> None:
        if self._device is None:
            self._device = self._new_device()
            self._is_connected = True

    def _disconnect_locked(self) -> None:
        if self._device is None:
            self._is_connected = False
            return
        try:
            self._device.disconnect()
        except Exception:
            pass
        finally:
            self._device = None
            self._is_connected = False

    def _reconnect_locked(self) -> None:
        self._disconnect_locked()
        self._device = self._new_device()
        self._is_connected = True

    def _run_ble(self, operation_name: str, operation: Callable[[Any], Any]) -> Any:
        with self._lock:
            started_at = time.monotonic()
            try:
                self._ensure_connected_locked()
                result = operation(self._device)
                self._is_connected = True
                return result
            except CommandError:
                raise
            except Exception as first_exc:
                self._is_connected = False
                self._log.warning(
                    "%s ha fallat (%s). Reconnectant i reintentant una vegada.",
                    operation_name,
                    first_exc,
                )
                try:
                    self._reconnect_locked()
                    result = operation(self._device)
                    self._is_connected = True
                    return result
                except Exception as second_exc:
                    self._is_connected = False
                    raise CommandError(
                        f"{operation_name} ha fallat: {second_exc}",
                        code="ble_error",
                    ) from second_exc
            finally:
                self._last_operation_ms = round(
                    (time.monotonic() - started_at) * 1000.0,
                    3,
                )

    def set_power(self, target_on: bool) -> None:
        if target_on:
            self._run_ble("power_on", lambda device: device.power_on())
        else:
            self._run_ble("power_off", lambda device: device.power_off())

    def request_measurement(self) -> Any:
        return self._run_ble(
            "request_measurement",
            lambda device: device.request_measurement(),
        )

    def sync_time(self, iso_datetime: str) -> None:
        self._run_ble(
            "sync_time",
            lambda device: device.change_date_and_time(iso_datetime),
        )

    def last_operation_ms(self) -> Optional[float]:
        with self._lock:
            return self._last_operation_ms

    def is_connected(self) -> bool:
        with self._lock:
            return self._is_connected

    def disconnect(self) -> None:
        with self._lock:
            self._disconnect_locked()


PublishJsonFn = Callable[[str, Dict[str, Any], int], None]


class TelemetryPublisher:
    """Publica telemetria del dispositiu fill amb el format MQTT de gateway."""

    def __init__(self, device_name: str, publish_json: PublishJsonFn, qos: int):
        self._device_name = device_name
        self._publish_json = publish_json
        self._qos = qos

    def publish(self, values: Dict[str, Any], timestamp_ms: Optional[int] = None) -> None:
        if not values:
            return
        payload = build_child_telemetry_payload(
            self._device_name,
            values,
            timestamp_ms=timestamp_ms,
        )
        self._publish_json(TOPIC_GATEWAY_TELEMETRY, payload, self._qos)


class AttributesPublisher:
    """Publica atributs del dispositiu fill."""

    def __init__(self, device_name: str, publish_json: PublishJsonFn, qos: int):
        self._device_name = device_name
        self._publish_json = publish_json
        self._qos = qos

    def publish(self, attributes: Dict[str, Any]) -> None:
        if not attributes:
            return
        payload = build_child_attributes_payload(self._device_name, attributes)
        self._publish_json(TOPIC_GATEWAY_ATTRIBUTES, payload, self._qos)


class RpcResponder:
    """Envia respostes de les RPC al mateix topic de gateway."""

    def __init__(self, publish_json: PublishJsonFn, qos: int):
        self._publish_json = publish_json
        self._qos = qos

    def success(self, device_name: str, request_id: Any, data: Dict[str, Any]) -> None:
        payload = build_gateway_rpc_response_payload(
            device_name,
            request_id,
            {"success": True, "data": data},
        )
        self._publish_json(TOPIC_GATEWAY_RPC, payload, self._qos)

    def error(
        self,
        device_name: str,
        request_id: Any,
        error_message: str,
        code: str,
    ) -> None:
        payload = build_gateway_rpc_response_payload(
            device_name,
            request_id,
            {"success": False, "error": error_message, "code": code},
        )
        self._publish_json(TOPIC_GATEWAY_RPC, payload, self._qos)


class GatewayDiagnosticsPublisher:
    """Publica atributs i telemetria del propi bridge MQTT."""

    def __init__(self, publish_json: PublishJsonFn, control_qos: int, telemetry_qos: int):
        self._publish_json = publish_json
        self._control_qos = control_qos
        self._telemetry_qos = telemetry_qos

    def publish_attributes(self, attributes: Dict[str, Any]) -> None:
        if not attributes:
            return
        self._publish_json(
            TOPIC_GATEWAY_SELF_ATTRIBUTES,
            attributes,
            self._control_qos,
        )

    def publish_telemetry(
        self,
        values: Dict[str, Any],
        timestamp_ms: Optional[int] = None,
    ) -> None:
        if not values:
            return
        payload = {
            "ts": timestamp_ms if timestamp_ms is not None else utc_ms(),
            "values": values,
        }
        self._publish_json(
            TOPIC_GATEWAY_SELF_TELEMETRY,
            payload,
            self._telemetry_qos,
        )


@dataclass
class CommandContext:
    """Dependencias que un handler RPC necessita per operar."""

    sem: Sem6000Session
    state: AgentState
    telemetry: TelemetryPublisher
    attributes: AttributesPublisher
    config: AppConfig


class RpcHandler(Protocol):
    """Contracte minim per registrar nous metodes RPC."""

    methods: tuple[str, ...]

    def handle(
        self,
        method_name: str,
        params: Any,
        context: CommandContext,
    ) -> Dict[str, Any]:
        ...


class PowerHandler:
    """Gestiona els RPC que consulten o canvien l'estat de l'endoll."""

    methods = (
        "setPower",
        "setSwitch",
        "setRelay",
        "power",
        "powerOn",
        "powerOff",
        "on",
        "off",
        "getPowerState",
        "getSwitchState",
    )

    def handle(self, method_name: str, params: Any, context: CommandContext) -> Dict[str, Any]:
        method_key = normalize_method(method_name)

        if method_key in {"getpowerstate", "getswitchstate"}:
            return {POWER_STATE_KEY: context.state.plug_is_on}

        if method_key in {"setpower", "setswitch", "setrelay", "power"}:
            parsed = parse_boolean_value(params)
            if parsed is None:
                raise CommandError(
                    "El metode necessita un parametre boolea.",
                    code="invalid_params",
                )
            target_state = parsed
        elif method_key in {"poweron", "on"}:
            target_state = True
        elif method_key in {"poweroff", "off"}:
            target_state = False
        else:
            raise CommandError(
                f"Metode RPC no suportat pel PowerHandler: {method_name}",
                code="unknown_method",
            )

        context.sem.set_power(target_state)
        context.state.plug_is_on = target_state
        if target_state is False:
            context.state.last_power_w = 0.0

        context.attributes.publish({POWER_STATE_KEY: target_state})

        immediate_values: Dict[str, Any] = {POWER_STATE_KEY: target_state}
        if target_state is False:
            immediate_values[POWER_METRIC_KEY] = 0.0
        elif context.state.last_power_w is not None:
            immediate_values[POWER_METRIC_KEY] = round(context.state.last_power_w, 3)
        context.telemetry.publish(immediate_values)

        return {POWER_STATE_KEY: target_state}


class MeasurementHandler:
    """Gestiona RPC de lectura de mesures i sincronitzacio de rellotge."""

    methods = (
        "getMeasurement",
        "measure",
        "syncTime",
        "setTime",
    )

    def handle(self, method_name: str, params: Any, context: CommandContext) -> Dict[str, Any]:
        method_key = normalize_method(method_name)

        if method_key in {"synctime", "settime"}:
            now_iso = dt.datetime.now().isoformat(timespec="seconds")
            context.sem.sync_time(now_iso)
            return {"device_time": now_iso}

        if method_key in {"getmeasurement", "measure"}:
            measurement = context.sem.request_measurement()
            include_extended = should_include_extended_measurements(
                measurement,
                force_extended=context.config.enable_extended_measurements,
            )
            values = map_measurement_to_values(
                measurement,
                include_extended=include_extended,
            )
            if POWER_STATE_KEY in values:
                context.state.plug_is_on = bool(values[POWER_STATE_KEY])
            if POWER_METRIC_KEY in values:
                context.state.last_power_w = float(values[POWER_METRIC_KEY])
            return values

        raise CommandError(
            f"Metode RPC no suportat pel MeasurementHandler: {method_name}",
            code="unknown_method",
        )


class ScheduleHandler:
    """Punt d'extensio reservat per futures funcions de programacio."""

    methods = ("getScheduler", "addScheduler", "editScheduler", "removeScheduler")

    def handle(self, method_name: str, params: Any, context: CommandContext) -> Dict[str, Any]:
        raise CommandError(
            f"Metode pendent d'implementar: {method_name}",
            code="not_implemented",
        )


class ConsumptionHandler:
    """Punt d'extensio reservat per historics de consum."""

    methods = ("getConsumption23h", "getConsumption30d", "getConsumption12m")

    def handle(self, method_name: str, params: Any, context: CommandContext) -> Dict[str, Any]:
        raise CommandError(
            f"Metode pendent d'implementar: {method_name}",
            code="not_implemented",
        )


class CommandRegistry:
    """Mapa un metode RPC normalitzat amb el seu handler concret."""

    def __init__(self):
        self._handlers: Dict[str, RpcHandler] = {}

    def register(self, handler: RpcHandler) -> None:
        for method_name in handler.methods:
            key = normalize_method(method_name)
            if key in self._handlers:
                raise RuntimeError(f"Metode RPC duplicat al registre: {method_name}")
            self._handlers[key] = handler

    def resolve(self, method_name: str) -> Optional[RpcHandler]:
        return self._handlers.get(normalize_method(method_name))


class MqttSem6000Agent:
    """Coordina la connexio MQTT, els RPC entrants i la telemetria periodica."""

    def __init__(self, config: AppConfig):
        if mqtt is None:
            raise SystemExit(
                "Falta la dependencia 'paho-mqtt'. Installa-la amb: pip install paho-mqtt"
            )

        self._cfg = config
        self._log = logging.getLogger("Sem6000ThingsBoardMqttAgent")

        self._state = AgentState()
        self._stop_event = threading.Event()
        self._telemetry_pending = threading.Event()
        self._publish_lock = threading.Lock()
        self._rpc_queue = RpcTaskQueue(maxsize=config.rpc_queue_size)

        self._client: Optional[mqtt.Client] = None
        self._connected_event = threading.Event()
        self._connect_failed_event = threading.Event()
        self._last_connect_rc: Optional[int] = None
        self._using_tls: Optional[bool] = None

        self._worker_thread: Optional[threading.Thread] = None
        self._telemetry_thread: Optional[threading.Thread] = None

        self._sem = Sem6000Session(
            address=config.sem6000_device_address,
            pin=config.sem6000_pin,
            timeout_seconds=config.sem6000_timeout_seconds,
            debug=config.sem6000_debug,
            log=self._log,
        )

        self._telemetry_publisher = TelemetryPublisher(
            device_name=config.tb_child_device_name,
            publish_json=self._publish_json,
            qos=config.tb_telemetry_qos,
        )
        self._attributes_publisher = AttributesPublisher(
            device_name=config.tb_child_device_name,
            publish_json=self._publish_json,
            qos=config.tb_control_qos,
        )
        self._rpc_responder = RpcResponder(
            publish_json=self._publish_json,
            qos=config.tb_control_qos,
        )
        self._diagnostics_publisher = GatewayDiagnosticsPublisher(
            publish_json=self._publish_json,
            control_qos=config.tb_control_qos,
            telemetry_qos=config.tb_telemetry_qos,
        )

        self._registry = CommandRegistry()
        self._registry.register(PowerHandler())
        self._registry.register(MeasurementHandler())
        self._registry.register(ScheduleHandler())
        self._registry.register(ConsumptionHandler())

    def _build_client(self, use_tls: bool) -> mqtt.Client:
        if hasattr(mqtt, "CallbackAPIVersion"):
            client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
                client_id=self._cfg.tb_client_id,
                clean_session=True,
            )
        else:
            client = mqtt.Client(client_id=self._cfg.tb_client_id, clean_session=True)

        client.username_pw_set(self._cfg.tb_gateway_access_token, password=None)
        client.reconnect_delay_set(min_delay=1, max_delay=30)

        if use_tls:
            client.tls_set()

        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        return client

    @staticmethod
    def _mask_token(token: str) -> str:
        if len(token) <= 8:
            return "*" * len(token)
        return f"{token[:4]}...{token[-4:]}"

    def _build_child_static_attributes(self) -> Dict[str, Any]:
        return {
            "sem6000_address": self._cfg.sem6000_device_address,
            "bridge": BRIDGE_NAME,
            "gateway_client_id": self._cfg.tb_client_id,
        }

    def _build_gateway_static_attributes(self) -> Dict[str, Any]:
        return {
            "bridge": BRIDGE_NAME,
            "child_device_name": self._cfg.tb_child_device_name,
            "child_device_type": self._cfg.tb_child_device_type,
            "sem6000_address": self._cfg.sem6000_device_address,
        }

    def _publish_child_connect(self) -> None:
        payload = build_gateway_connect_payload(
            self._cfg.tb_child_device_name,
            self._cfg.tb_child_device_type,
        )
        self._publish_json(TOPIC_GATEWAY_CONNECT, payload, self._cfg.tb_control_qos)

    def _publish_child_disconnect(self) -> None:
        payload = build_gateway_disconnect_payload(self._cfg.tb_child_device_name)
        self._publish_json(TOPIC_GATEWAY_DISCONNECT, payload, self._cfg.tb_control_qos)

    def _publish_gateway_diagnostics(self) -> None:
        values: Dict[str, Any] = {
            "mqtt_connected": self._state.mqtt_connected,
            "ble_connected": self._sem.is_connected(),
            "rpc_queue_depth": self._rpc_queue.size(),
        }

        last_ble_op_ms = self._sem.last_operation_ms()
        if last_ble_op_ms is not None:
            values["last_ble_op_ms"] = last_ble_op_ms

        if self._state.last_rpc_total_ms is not None:
            values["last_rpc_total_ms"] = self._state.last_rpc_total_ms

        self._diagnostics_publisher.publish_telemetry(values)

    def _attempt_connect(self, use_tls: bool) -> bool:
        self._connected_event.clear()
        self._connect_failed_event.clear()
        self._last_connect_rc = None

        client = self._build_client(use_tls=use_tls)
        self._client = client
        port = self._cfg.tb_tls_port if use_tls else self._cfg.tb_plain_port

        try:
            self._log.info(
                "Connectant MQTT gateway a %s:%s (tls=%s)...",
                self._cfg.tb_host,
                port,
                use_tls,
            )
            client.connect(self._cfg.tb_host, port, keepalive=self._cfg.tb_keepalive)
            client.loop_start()
        except Exception as exc:
            self._log.warning(
                "No s'ha pogut obrir connexio MQTT (tls=%s): %s", use_tls, exc
            )
            if self._client is client:
                self._client = None
            return False

        deadline = time.monotonic() + self._cfg.mqtt_connect_timeout_seconds
        while time.monotonic() < deadline and not self._stop_event.is_set():
            if self._connected_event.is_set():
                self._using_tls = use_tls
                return True
            if self._connect_failed_event.is_set():
                break
            time.sleep(0.05)

        try:
            client.loop_stop()
            client.disconnect()
        except Exception:
            pass
        if self._client is client:
            self._client = None
        return False

    def _connect_mqtt(self) -> None:
        self._log.info(
            "Configuracio MQTT: host=%s, client_id=%s, token=%s, tls_mode=%s, child=%s",
            self._cfg.tb_host,
            self._cfg.tb_client_id,
            self._mask_token(self._cfg.tb_gateway_access_token),
            self._cfg.tb_tls_mode,
            self._cfg.tb_child_device_name,
        )
        self._log.info(
            "Mesures esteses a ThingsBoard: automatiques quan l'endoll esta actiu; forcades per flag=%s",
            self._cfg.enable_extended_measurements,
        )

        mode = self._cfg.tb_tls_mode
        if mode == "required":
            attempts = [True]
        elif mode == "disabled":
            attempts = [False]
        else:
            attempts = [True, False]

        for use_tls in attempts:
            if self._attempt_connect(use_tls=use_tls):
                self._log.info("MQTT connectat. Mode TLS actiu: %s", use_tls)
                return

        rc_info = (
            f" (rc={self._last_connect_rc})"
            if self._last_connect_rc is not None
            else ""
        )
        raise SystemExit(f"No s'ha pogut connectar a MQTT{rc_info}.")

    def _publish_json(self, topic: str, payload: Dict[str, Any], qos: int) -> None:
        with self._publish_lock:
            client = self._client
            if client is None:
                return
            info = client.publish(topic, compact_json(payload), qos=qos)

        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            self._log.warning(
                "No s'ha pogut publicar al topic %s (rc=%s).", topic, info.rc
            )

    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: Dict[str, Any], rc: int) -> None:
        if rc != 0:
            self._last_connect_rc = rc
            self._connect_failed_event.set()
            self._log.error("MQTT connect failed (rc=%s).", rc)
            return

        self._state.mqtt_connected = True
        self._connected_event.set()

        client.subscribe(TOPIC_GATEWAY_RPC, qos=self._cfg.tb_control_qos)
        client.subscribe(TOPIC_GATEWAY_ATTRIBUTES, qos=self._cfg.tb_control_qos)
        self._publish_child_connect()
        self._attributes_publisher.publish(self._build_child_static_attributes())
        self._diagnostics_publisher.publish_attributes(
            self._build_gateway_static_attributes()
        )
        self._publish_gateway_diagnostics()
        self._log.info("MQTT connectat i gateway inicialitzat.")

    def _on_disconnect(self, client: mqtt.Client, userdata: Any, rc: int) -> None:
        self._state.mqtt_connected = False
        if self._stop_event.is_set():
            return
        if rc != 0:
            self._log.warning("MQTT desconnectat (rc=%s). S'intentara reconnectar.", rc)
        else:
            self._log.info("MQTT desconnectat.")

    def _on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        if msg.topic == TOPIC_GATEWAY_ATTRIBUTES:
            self._log.debug("Update d'atributs gateway rebut i ignorat.")
            return
        if msg.topic != TOPIC_GATEWAY_RPC:
            return

        try:
            raw_payload = msg.payload.decode("utf-8", errors="replace")
            request_payload = json.loads(raw_payload)
        except Exception as exc:
            self._log.warning("Payload JSON invalid a gateway/rpc: %s", exc)
            return

        response_device: Optional[str] = None
        response_id: Any = None
        if isinstance(request_payload, dict):
            response_device = str(request_payload.get("device", "")).strip() or None
            request_data = request_payload.get("data")
            if isinstance(request_data, dict):
                response_id = request_data.get("id")

        try:
            task = parse_gateway_rpc_payload(
                request_payload,
                expected_device_name=self._cfg.tb_child_device_name,
            )
        except CommandError as exc:
            if (
                exc.code != "wrong_device"
                and response_device == self._cfg.tb_child_device_name
                and response_id not in {None, ""}
            ):
                self._rpc_responder.error(
                    response_device,
                    response_id,
                    str(exc),
                    code=exc.code,
                )
            else:
                self._log.warning("RPC ignorat: %s", exc)
            return

        superseded, dropped = self._rpc_queue.put(task)
        for old_task in superseded:
            self._rpc_responder.error(
                old_task.device_name,
                old_task.request_id,
                "Ordre substituida per una ordre de potencia mes recent.",
                code="superseded",
            )
        for old_task in dropped:
            self._rpc_responder.error(
                old_task.device_name,
                old_task.request_id,
                "La cua RPC esta plena i l'ordre s'ha descartat.",
                code="queue_overflow",
            )

    def _handle_rpc_task(self, task: RpcTask, context: CommandContext) -> None:
        handler = self._registry.resolve(task.method)
        if handler is None:
            self._rpc_responder.error(
                task.device_name,
                task.request_id,
                f"Metode RPC no suportat: {task.method}",
                code="unknown_method",
            )
            return

        started_at = time.monotonic()
        try:
            response_data = handler.handle(task.method, task.params, context)
            self._rpc_responder.success(task.device_name, task.request_id, response_data)
        except CommandError as exc:
            self._rpc_responder.error(
                task.device_name,
                task.request_id,
                str(exc),
                code=exc.code,
            )
        except Exception as exc:
            self._log.exception("Error intern processant RPC %s", task.method)
            self._rpc_responder.error(
                task.device_name,
                task.request_id,
                f"Error intern: {exc}",
                code="internal_error",
            )
        finally:
            self._state.last_rpc_total_ms = round(
                (time.monotonic() - started_at) * 1000.0,
                3,
            )

    def _handle_telemetry_tick(self, context: CommandContext) -> None:
        if context.state.plug_is_on is False:
            context.state.last_power_w = 0.0
            values = {POWER_METRIC_KEY: 0.0, POWER_STATE_KEY: False}
            context.telemetry.publish(values)
            context.state.last_telemetry_ts_ms = utc_ms()
            return

        try:
            measurement = context.sem.request_measurement()
        except CommandError as exc:
            self._log.warning("No s'ha pogut llegir telemetria: %s", exc)
            return

        include_extended = should_include_extended_measurements(
            measurement,
            force_extended=context.config.enable_extended_measurements,
        )
        values = map_measurement_to_values(
            measurement,
            include_extended=include_extended,
        )
        if not values:
            return

        previous_state = context.state.plug_is_on
        if POWER_STATE_KEY in values:
            new_state = bool(values[POWER_STATE_KEY])
            context.state.plug_is_on = new_state
            if previous_state is None or previous_state != new_state:
                context.attributes.publish({POWER_STATE_KEY: new_state})

        if POWER_METRIC_KEY in values:
            context.state.last_power_w = float(values[POWER_METRIC_KEY])
        elif context.state.last_power_w is not None:
            values[POWER_METRIC_KEY] = round(context.state.last_power_w, 3)

        if POWER_STATE_KEY not in values and context.state.plug_is_on is not None:
            values[POWER_STATE_KEY] = context.state.plug_is_on

        context.telemetry.publish(values)
        context.state.last_telemetry_ts_ms = utc_ms()

    def _worker_loop(self) -> None:
        context = CommandContext(
            sem=self._sem,
            state=self._state,
            telemetry=self._telemetry_publisher,
            attributes=self._attributes_publisher,
            config=self._cfg,
        )

        while not self._stop_event.is_set():
            task = self._rpc_queue.get(timeout=0.1)
            if task is not None:
                self._handle_rpc_task(task, context)
                continue

            if self._telemetry_pending.is_set():
                self._telemetry_pending.clear()
                self._handle_telemetry_tick(context)

    def _current_telemetry_interval(self) -> float:
        if self._state.plug_is_on is False:
            return self._cfg.off_heartbeat_seconds
        return self._cfg.telemetry_interval_on_seconds

    def _telemetry_scheduler_loop(self) -> None:
        next_diagnostics_at = time.monotonic() + DEFAULT_DIAGNOSTICS_INTERVAL_SECONDS

        while not self._stop_event.is_set():
            interval = self._current_telemetry_interval()
            if self._stop_event.wait(interval):
                return

            now = time.monotonic()
            if now >= next_diagnostics_at:
                self._publish_gateway_diagnostics()
                next_diagnostics_at = now + DEFAULT_DIAGNOSTICS_INTERVAL_SECONDS

            if self._rpc_queue.size() > 0:
                continue
            self._telemetry_pending.set()

    def start(self) -> None:
        self._connect_mqtt()
        self._telemetry_pending.set()

        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="sem6000-worker",
            daemon=True,
        )
        self._worker_thread.start()

        self._telemetry_thread = threading.Thread(
            target=self._telemetry_scheduler_loop,
            name="telemetry-scheduler",
            daemon=True,
        )
        self._telemetry_thread.start()

    def stop(self) -> None:
        self._stop_event.set()

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5)
        if self._telemetry_thread and self._telemetry_thread.is_alive():
            self._telemetry_thread.join(timeout=5)

        client = self._client
        if client is not None and self._state.mqtt_connected:
            try:
                self._publish_child_disconnect()
            except Exception:
                pass

        if client is not None:
            try:
                client.loop_stop()
            except Exception:
                pass
            try:
                client.disconnect()
            except Exception:
                pass

        self._state.mqtt_connected = False
        self._sem.disconnect()

    def run_forever(self) -> None:
        self.start()
        self._log.info("Agent gateway en marxa. Ctrl+C per aturar.")
        while not self._stop_event.is_set():
            time.sleep(0.5)


def install_signal_handlers(agent: MqttSem6000Agent) -> None:
    """Instal.la handlers per aturar l'agent amb SIGINT o SIGTERM."""

    def _handle_signal(signum: int, frame: Any) -> None:
        logging.getLogger("Sem6000ThingsBoardMqttAgent").info(
            "Senyal %s rebuda. Aturant agent...", signum
        )
        agent.stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handle_signal)
        except ValueError:
            continue


def main() -> int:
    config = AppConfig.from_env()
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    agent = MqttSem6000Agent(config)
    install_signal_handlers(agent)
    try:
        agent.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        agent.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
