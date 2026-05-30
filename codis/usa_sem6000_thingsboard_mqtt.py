"""Passarella MQTT entre un SEM6000 i ThingsBoard en mode gateway."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import signal
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Deque, Dict, Mapping, Optional, Protocol

try:
    import paho.mqtt.client as mqtt
except ModuleNotFoundError:
    mqtt = None

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None

DEFAULT_CONFIG_PATH = "/etc/sem6000-bridge/config.toml"
DEFAULT_CHILD_DEVICE_TYPE = "Voltcraft SEM6000"
DEFAULT_TB_HOST = "mqtt.eu.thingsboard.cloud"
DEFAULT_TB_CLIENT_ID = "sem6000-rpi2b"
DEFAULT_SEM6000_PIN = "0000"
DEFAULT_SEM6000_TIMEOUT_SECONDS = 3.0
DEFAULT_BLUETOOTH_DEVICE = "hci0"

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
DEFAULT_HISTORY_TIMEOUT_SECONDS = 12.0

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


def _normalize_isotime_minutes(value: Any, *, field_name: str) -> str:
    """Valida una hora ISO i la retorna sempre amb precisio de minuts."""
    if value is None or value == "":
        raise CommandError(
            f"Falta el camp {field_name}.",
            code="invalid_params",
        )
    try:
        parsed = dt.time.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise CommandError(
            f"Valor invalid per {field_name}: {value}. Usa HH:MM o HH:MM:SS.",
            code="invalid_params",
        ) from exc
    return parsed.isoformat(timespec="minutes")


def _normalize_isodatetime_seconds(value: Any, *, field_name: str) -> str:
    """Valida una data-hora ISO i la retorna sempre amb precisio de segons."""
    if value is None or value == "":
        raise CommandError(
            f"Falta el camp {field_name}.",
            code="invalid_params",
        )
    try:
        parsed = dt.datetime.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise CommandError(
            f"Valor invalid per {field_name}: {value}. Usa YYYY-MM-DDTHH:MM[:SS].",
            code="invalid_params",
        ) from exc
    return parsed.isoformat(timespec="seconds")


def _normalize_positive_int(value: Any, *, field_name: str, allow_zero: bool = False) -> int:
    """Valida enters provinents de params RPC i n'assegura el rang."""
    if value is None or value == "":
        raise CommandError(
            f"Falta el camp {field_name}.",
            code="invalid_params",
        )
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise CommandError(
            f"Valor invalid per {field_name}: {value}.",
            code="invalid_params",
        ) from exc
    minimum = 0 if allow_zero else 1
    if parsed < minimum:
        comparator = ">=" if allow_zero else ">"
        threshold = 0 if allow_zero else 0
        raise CommandError(
            f"El camp {field_name} ha de ser {comparator} {threshold}.",
            code="invalid_params",
        )
    return parsed


def _require_dict_params(params: Any, *, method_name: str) -> Dict[str, Any]:
    """Assegura que una RPC que necessita camps nomenats rebi un objecte JSON."""
    if not isinstance(params, dict):
        raise CommandError(
            f"El metode {method_name} necessita un objecte JSON als params.",
            code="invalid_params",
        )
    return params


def _canonical_weekday_from_value(value: Any) -> Optional[str]:
    """Mapeja dies de la setmana de diverses formes a abreviatures canoniques."""
    token = value
    if hasattr(value, "name"):
        token = getattr(value, "name")

    normalized = str(token).strip().lower()
    if normalized.startswith("weekday."):
        normalized = normalized.split(".", 1)[1]

    weekday_map = {
        "0": "Sun",
        "sun": "Sun",
        "sunday": "Sun",
        "1": "Mon",
        "mon": "Mon",
        "monday": "Mon",
        "2": "Tue",
        "tue": "Tue",
        "tuesday": "Tue",
        "3": "Wed",
        "wed": "Wed",
        "wednesday": "Wed",
        "4": "Thu",
        "thu": "Thu",
        "thursday": "Thu",
        "5": "Fri",
        "fri": "Fri",
        "friday": "Fri",
        "6": "Sat",
        "sat": "Sat",
        "saturday": "Sat",
    }
    return weekday_map.get(normalized)


def _format_weekdays(values: Any) -> str:
    """Converteix una llista de weekdays del backend a una string canònica."""
    if values is None:
        return ""

    formatted: list[str] = []
    seen: set[str] = set()
    for value in values:
        canonical = _canonical_weekday_from_value(value)
        if canonical is None or canonical in seen:
            continue
        formatted.append(canonical)
        seen.add(canonical)
    return ",".join(formatted)


def _normalize_weekdays_string(value: Any, *, field_name: str) -> str:
    """Valida una llista de weekdays i la retorna com a string canonica."""
    if value is None or value == "":
        raise CommandError(
            f"Falta el camp {field_name}.",
            code="invalid_params",
        )

    if isinstance(value, str):
        raw_values = [chunk.strip() for chunk in value.split(",")]
    elif isinstance(value, list):
        raw_values = value
    else:
        raise CommandError(
            f"Valor invalid per {field_name}: {value}. Usa una string com Mon,Wed,Fri.",
            code="invalid_params",
        )

    normalized: list[str] = []
    seen: set[str] = set()
    for raw_value in raw_values:
        canonical = _canonical_weekday_from_value(raw_value)
        if canonical is None:
            raise CommandError(
                f"Valor invalid per {field_name}: {raw_value}. Usa dies com Mon,Wed,Fri.",
                code="invalid_params",
            )
        if canonical in seen:
            continue
        normalized.append(canonical)
        seen.add(canonical)

    if not normalized:
        raise CommandError(
            f"Falta almenys un dia valid a {field_name}.",
            code="invalid_params",
        )
    return ",".join(normalized)


def _normalize_action_label(value: Any, *, field_name: str) -> str:
    """Normalitza una accio d'endoll a on/off."""
    if isinstance(value, bool):
        return "on" if value else "off"

    normalized = str(value or "").strip().lower()
    if normalized in {"on", "true", "1"}:
        return "on"
    if normalized in {"off", "false", "0"}:
        return "off"
    raise CommandError(
        f"Valor invalid per {field_name}: {value}. Usa on o off.",
        code="invalid_params",
    )


def _action_label_to_bool(action_label: str) -> bool:
    """Converteix l'etiqueta canonica on/off a boolea."""
    return action_label == "on"


def _action_bool_to_label(is_on: Any) -> str:
    """Converteix un boolea o equivalent del backend a on/off."""
    return "on" if bool(is_on) else "off"


def normalize_settings_notification(settings: Any) -> Dict[str, Any]:
    """Converteix els settings del SEM6000 en un payload estable per a RPC."""
    return {
        "night_mode": bool(getattr(settings, "is_nightmode_active", False)),
        "power_limit_w": int(getattr(settings, "power_limit_in_watt", 0)),
        "prices": {
            "normal_price_cent": int(getattr(settings, "normal_price_in_cent", 0)),
            "reduced_price_cent": int(
                getattr(settings, "reduced_period_price_in_cent", 0)
            ),
        },
        "reduced_period": {
            "enabled": bool(getattr(settings, "is_reduced_period", False)),
            "start": str(getattr(settings, "reduced_period_start_isotime", "00:00")),
            "end": str(getattr(settings, "reduced_period_end_isotime", "00:00")),
        },
    }


def flatten_settings_attributes(settings_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Aplana settings per publicar-los com a atributs de ThingsBoard."""
    prices = settings_payload.get("prices", {})
    reduced_period = settings_payload.get("reduced_period", {})
    return {
        "night_mode": settings_payload.get("night_mode"),
        "power_limit_w": settings_payload.get("power_limit_w"),
        "price_normal_cent": prices.get("normal_price_cent"),
        "price_reduced_cent": prices.get("reduced_price_cent"),
        "reduced_period_enabled": reduced_period.get("enabled"),
        "reduced_period_start": reduced_period.get("start"),
        "reduced_period_end": reduced_period.get("end"),
    }


def normalize_timer_status_notification(notification: Any) -> Dict[str, Any]:
    """Converteix l'estat del timer del SEM6000 en un payload estable per a RPC."""
    target = getattr(notification, "target_isodatetime", None)
    payload: Dict[str, Any] = {
        "timer_active": bool(getattr(notification, "is_active", False)),
        "action": _action_bool_to_label(getattr(notification, "is_action_turn_on", False)),
        "target_isodatetime": None,
        "original_timer_length_seconds": int(
            getattr(notification, "original_timer_length_in_seconds", 0)
        ),
    }
    if target not in {None, ""}:
        payload["target_isodatetime"] = _normalize_isodatetime_seconds(
            target,
            field_name="target_isodatetime",
        )
    return payload


def flatten_timer_attributes(timer_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Aplana l'estat del timer per publicar-lo com a atributs."""
    return {
        "timer_active": timer_payload.get("timer_active"),
        "timer_action": timer_payload.get("action"),
        "timer_target_isodatetime": timer_payload.get("target_isodatetime"),
        "timer_original_length_seconds": timer_payload.get(
            "original_timer_length_seconds"
        ),
    }


def normalize_random_mode_notification(notification: Any) -> Dict[str, Any]:
    """Converteix l'estat de random mode en un payload estable per a RPC."""
    return {
        "enabled": bool(getattr(notification, "is_active", False)),
        "weekdays": _format_weekdays(getattr(notification, "active_on_weekdays", [])),
        "start": _normalize_isotime_minutes(
            getattr(notification, "start_isotime", "00:00"),
            field_name="start",
        ),
        "end": _normalize_isotime_minutes(
            getattr(notification, "end_isotime", "00:00"),
            field_name="end",
        ),
    }


def flatten_random_mode_attributes(random_mode_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Aplana l'estat de random mode per publicar-lo com a atributs."""
    return {
        "random_mode_enabled": random_mode_payload.get("enabled"),
        "random_mode_weekdays": random_mode_payload.get("weekdays"),
        "random_mode_start": random_mode_payload.get("start"),
        "random_mode_end": random_mode_payload.get("end"),
    }


def _sem6000_message_payload_length(
    raw_message: bytes,
    hardware_version: Optional[int],
) -> Optional[int]:
    """Calcula la mida declarada pel propi missatge BLE del SEM6000."""
    if len(raw_message) < 4 or raw_message[0:1] != b"\x0f":
        return None

    payload_length = raw_message[1]
    # En HW v3 la lectura instantania declara 2 bytes menys dels reals.
    if raw_message[2:4] == b"\x04\x00" and hardware_version == 3:
        payload_length += 2
    return payload_length


def _sem6000_message_has_valid_checksum(
    raw_message: bytes,
    hardware_version: Optional[int],
) -> bool:
    """Valida el checksum del missatge segons la longitud declarada."""
    payload_length = _sem6000_message_payload_length(raw_message, hardware_version)
    if payload_length is None:
        return False

    payload_end = 2 + payload_length
    if len(raw_message) < payload_end:
        return False

    payload = raw_message[2 : payload_end - 1]
    checksum_received = raw_message[payload_end - 1]
    checksum_actual = (1 + sum(payload)) & 0xFF
    if checksum_received == checksum_actual:
        return True

    # Alguns SEM6000 HW v3 retornen historics amb un checksum que no segueix
    # la formula documentada, tot i que la longitud i el sufix son coherents.
    if hardware_version is not None and hardware_version >= 3:
        return _sem6000_history_payload_has_expected_shape(payload)

    return False


def _sem6000_history_payload_has_expected_shape(payload: bytes) -> bool:
    """Comprova les mides fixes dels tres historics de consum del SEM6000."""
    command = payload[0:2]
    if command == b"\x0a\x00":
        return len(payload) == 2 + (24 * 2)
    if command == b"\x0b\x00":
        return len(payload) == 2 + (30 * 4)
    if command == b"\x0c\x00":
        return len(payload) == 2 + (12 * 4)
    return False


def _parse_sem6000_payload_lenient(data: bytes, hardware_version: Optional[int]) -> bytes:
    """Replica el parser base, amb tolerancia acotada per historics HW v3."""
    if data[0:1] != b"\x0f":
        raise Exception("Invalid response")

    length_of_payload = _sem6000_message_payload_length(data, hardware_version)
    if length_of_payload is None:
        raise Exception("Invalid response")

    if len(data) < 2 + length_of_payload:
        raise Exception("Incomplete notification data")

    payload = data[2 : 2 + length_of_payload - 1]
    checksum_received = data[2 + length_of_payload - 1]
    checksum = (1 + sum(payload)) & 0xFF

    if checksum_received != checksum:
        is_hw3_history = (
            hardware_version is not None
            and hardware_version >= 3
            and _sem6000_history_payload_has_expected_shape(payload)
            and data[2 + length_of_payload : 4 + length_of_payload] == b"\xff\xff"
        )
        if not is_hw3_history:
            raise Exception(
                "Invalid checksum: actual="
                + str(checksum)
                + ", received="
                + str(checksum_received)
            )

    if len(data) > 2 + length_of_payload:
        suffix = data[2 + length_of_payload : 4 + length_of_payload]
        if suffix != b"\xff\xff":
            raise Exception("Invalid suffix " + str(suffix))

    return payload


def sem6000_raw_notifications_complete(
    raw_notifications: Any,
    hardware_version: Optional[int],
) -> bool:
    """Decideix si la resposta BLE acumulada ja te tots els bytes necessaris.

    La llibreria base donava per complet un missatge nomes perque l'ultim fragment
    acabava amb ``ff ff``. Això és fragile per a respostes llargues com els historics
    de consum, on algun fragment intermedi pot acabar en aquests mateixos bytes.
    Aqui fem servir la longitud anunciada pel missatge per validar que realment
    hem rebut tot el payload abans d'intentar parsejar-lo.
    """
    if not raw_notifications:
        return False

    joined = b"".join(
        bytes(chunk) for chunk in raw_notifications if isinstance(chunk, (bytes, bytearray))
    )
    if len(joined) < 4 or joined[0:1] != b"\x0f":
        return False

    payload_length = _sem6000_message_payload_length(joined, hardware_version)
    if payload_length is None:
        return False

    payload_end = 2 + payload_length
    if len(joined) < payload_end:
        return False

    if not _sem6000_message_has_valid_checksum(joined, hardware_version):
        return False

    command = joined[2:4]

    # La lectura instantania no porta sufix ff ff.
    if command == b"\x04\x00":
        return True

    # En HW >= 3, settings porta ff ff 00 00 al final.
    if hardware_version is not None and hardware_version >= 3 and command == b"\x10\x00":
        return len(joined) >= payload_end + 4 and joined[payload_end : payload_end + 4] == b"\xff\xff\x00\x00"

    return len(joined) >= payload_end + 2 and joined[payload_end : payload_end + 2] == b"\xff\xff"


def wait_for_sem6000_notifications(
    wait_for_notifications: Callable[[float], bool],
    delegate: Any,
    timeout_seconds: float,
    should_stop: Optional[Callable[[], bool]] = None,
) -> None:
    """Espera notificacions BLE evitant tallar massa aviat respostes fragmentades.

    La llibreria original deixa d'esperar a la primera finestra ``timeout`` sense
    noves notificacions, encara que ja s'hagi rebut una resposta parcial. Per als
    historics llargs aixÃ² pot deixar el missatge incomplet i acabar en checksum
    invalid. Aqui, un cop hi ha fragments parcials, seguim fent polling curt fins
    que el missatge sigui valid o s'esgoti una gracia addicional.
    """
    timeout = max(float(timeout_seconds or 0.0), 0.1)
    partial_poll_seconds = min(max(timeout / 5.0, 0.2), 1.0)
    partial_grace_seconds = max(timeout, 2.0)
    interrupt_poll_seconds = 0.5
    partial_deadline: Optional[float] = None
    last_raw_length = 0

    while True:
        if should_stop is not None and should_stop():
            return

        if delegate.has_final_raw_notification():
            return

        raw_notifications = getattr(delegate, "_raw_notifications", [])
        has_partial = bool(raw_notifications)
        raw_length = sum(
            len(chunk)
            for chunk in raw_notifications
            if isinstance(chunk, (bytes, bytearray))
        )

        wait_timeout = timeout
        if has_partial:
            if partial_deadline is None:
                partial_deadline = time.monotonic() + partial_grace_seconds
            remaining = partial_deadline - time.monotonic()
            if remaining <= 0:
                return
            wait_timeout = min(partial_poll_seconds, remaining)

        if should_stop is not None:
            wait_timeout = min(wait_timeout, interrupt_poll_seconds)

        if not wait_for_notifications(wait_timeout):
            if has_partial:
                continue
            return

        if should_stop is not None and should_stop():
            return

        raw_notifications = getattr(delegate, "_raw_notifications", [])
        raw_length = sum(
            len(chunk)
            for chunk in raw_notifications
            if isinstance(chunk, (bytes, bytearray))
        )
        if raw_length > last_raw_length:
            partial_deadline = time.monotonic() + partial_grace_seconds
            last_raw_length = raw_length


def _normalize_bool_field(
    params_dict: Dict[str, Any],
    *,
    field_name: str,
    aliases: tuple[str, ...] = (),
) -> bool:
    """Extreu un camp boolea obligatori admetent diversos aliases habituals."""
    for candidate in (field_name, *aliases):
        if candidate not in params_dict:
            continue
        parsed = parse_boolean_value(params_dict.get(candidate))
        if parsed is None:
            raise CommandError(
                f"El camp {candidate} ha de ser boolea.",
                code="invalid_params",
            )
        return parsed
    raise CommandError(
        f"Falta el camp {field_name}.",
        code="invalid_params",
    )


def _normalize_action_field(
    params_dict: Dict[str, Any],
    *,
    field_name: str = "action",
    aliases: tuple[str, ...] = ("turn_on", "is_action_turn_on"),
) -> str:
    """Extreu l'accio on/off d'un payload RPC admetent text o booleans."""
    for candidate in (field_name, *aliases):
        if candidate not in params_dict:
            continue
        raw_value = params_dict.get(candidate)
        if candidate == field_name:
            return _normalize_action_label(raw_value, field_name=candidate)

        parsed = parse_boolean_value(raw_value)
        if parsed is None:
            raise CommandError(
                f"El camp {candidate} ha de ser boolea.",
                code="invalid_params",
            )
        return _action_bool_to_label(parsed)

    raise CommandError(
        f"Falta el camp {field_name}.",
        code="invalid_params",
    )


def _normalize_scheduler_type(value: Any, *, field_name: str = "type") -> str:
    """Normalitza el tipus de scheduler a onetime o repeated."""
    normalized = str(value or "").strip().lower().replace("-", "").replace("_", "")
    scheduler_type_map = {
        "onetime": "onetime",
        "once": "onetime",
        "repeated": "repeated",
        "repeat": "repeated",
        "recurring": "repeated",
    }
    scheduler_type = scheduler_type_map.get(normalized)
    if scheduler_type is None:
        raise CommandError(
            f"Valor invalid per {field_name}: {value}. Usa onetime o repeated.",
            code="invalid_params",
        )
    return scheduler_type


def _normalize_slot_id(value: Any, *, field_name: str = "slot_id") -> int:
    """Valida un slot de scheduler; la llibreria base admet el 0 com a primer slot."""
    return _normalize_positive_int(value, field_name=field_name, allow_zero=True)


def normalize_scheduler_entry(entry: Any) -> Dict[str, Any]:
    """Converteix una entrada de scheduler del backend a un payload RPC estable."""
    scheduler = getattr(entry, "scheduler", None)
    weekdays = _format_weekdays(getattr(scheduler, "repeat_on_weekdays", []))
    target_isodatetime = _normalize_isodatetime_seconds(
        getattr(scheduler, "isodatetime", None),
        field_name="target_isodatetime",
    )
    payload: Dict[str, Any] = {
        "slot_id": int(getattr(entry, "slot_id", 0)),
        "type": "repeated" if weekdays else "onetime",
        "enabled": bool(getattr(scheduler, "is_active", False)),
        "action": _action_bool_to_label(getattr(scheduler, "is_action_turn_on", False)),
    }

    if weekdays:
        target_dt = dt.datetime.fromisoformat(target_isodatetime)
        payload["weekdays"] = weekdays
        payload["time"] = target_dt.time().isoformat(timespec="minutes")
    else:
        payload["target_isodatetime"] = target_isodatetime

    return payload


def normalize_scheduler_notification(notification: Any) -> Dict[str, Any]:
    """Converteix la resposta de scheduler del SEM6000 a una llista ordenada."""
    scheduler_entries = [
        normalize_scheduler_entry(entry)
        for entry in getattr(notification, "scheduler_entries", [])
    ]
    scheduler_entries.sort(key=lambda entry: entry["slot_id"])
    return {
        "scheduler_count": len(scheduler_entries),
        "schedulers": scheduler_entries,
    }


def _normalize_optional_int(value: Any) -> Optional[int]:
    """Converteix enters de la llibreria a int, preservant None."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _year_month_months_ago(reference_date: dt.date, months_ago: int) -> tuple[int, int]:
    """Retorna any i mes absoluts per a una distancia en mesos."""
    month_index = reference_date.year * 12 + (reference_date.month - 1) - months_ago
    return month_index // 12, (month_index % 12) + 1


def normalize_consumption_23h_notification(
    notification: Any,
    *,
    now: Optional[dt.datetime] = None,
) -> Dict[str, Any]:
    """Normalitza l'historic horari amb etiquetes absolutes d'hora local."""
    reference = (now or dt.datetime.now()).replace(minute=0, second=0, microsecond=0)
    samples: list[Dict[str, Any]] = []
    for hours_ago, value in enumerate(
        getattr(notification, "consumption_n_hours_ago_in_watt_hour", [])
    ):
        sample_dt = reference - dt.timedelta(hours=hours_ago)
        samples.append(
            {
                "hours_ago": hours_ago,
                "timestamp_local": sample_dt.isoformat(timespec="seconds"),
                "isotime": sample_dt.time().isoformat(timespec="minutes"),
                "consumption_wh": _normalize_optional_int(value),
            }
        )
    return {
        "interval": "hour",
        "unit": "Wh",
        "sample_count": len(samples),
        "samples": samples,
    }


def normalize_consumption_30d_notification(
    notification: Any,
    *,
    today: Optional[dt.date] = None,
) -> Dict[str, Any]:
    """Normalitza l'historic diari amb dates absolutes."""
    reference_date = today or dt.date.today()
    samples: list[Dict[str, Any]] = []
    for days_ago, value in enumerate(
        getattr(notification, "consumption_n_days_ago_in_watt_hour", [])
    ):
        sample_date = reference_date - dt.timedelta(days=days_ago)
        samples.append(
            {
                "days_ago": days_ago,
                "date": sample_date.isoformat(),
                "consumption_wh": _normalize_optional_int(value),
            }
        )
    return {
        "interval": "day",
        "unit": "Wh",
        "sample_count": len(samples),
        "samples": samples,
    }


def normalize_consumption_12m_notification(
    notification: Any,
    *,
    today: Optional[dt.date] = None,
) -> Dict[str, Any]:
    """Normalitza l'historic mensual amb claus any-mes absolutes."""
    reference_date = today or dt.date.today()
    samples: list[Dict[str, Any]] = []
    for months_ago, value in enumerate(
        getattr(notification, "consumption_n_months_ago_in_watt_hour", [])
    ):
        year, month = _year_month_months_ago(reference_date, months_ago)
        samples.append(
            {
                "months_ago": months_ago,
                "year": year,
                "month": month,
                "year_month": f"{year:04d}-{month:02d}",
                "consumption_wh": _normalize_optional_int(value),
            }
        )
    return {
        "interval": "month",
        "unit": "Wh",
        "sample_count": len(samples),
        "samples": samples,
    }


def _normalize_pin(value: Any, *, field_name: str) -> str:
    """Valida un PIN numeric de 4 digits per a operacions administratives."""
    pin = str(value or "").strip()
    if len(pin) != 4 or not pin.isdigit():
        raise CommandError(
            f"Valor invalid per {field_name}: {value}. Usa un PIN numeric de 4 digits.",
            code="invalid_params",
        )
    return pin


class CommandError(Exception):
    """Error funcional retornable a ThingsBoard amb un codi controlat."""

    def __init__(self, message: str, code: str = "command_error"):
        super().__init__(message)
        self.code = code


def _env_get(env: Mapping[str, str], name: str) -> Optional[str]:
    """Retorna una variable d'entorn normalitzada a string no buida."""
    value = env.get(name)
    if value is None:
        return None
    value = str(value).strip()
    return value if value else None


def _first_env(env: Mapping[str, str], *names: str) -> Optional[str]:
    """Busca el primer nom d'entorn definit d'una llista de candidates."""
    for name in names:
        value = _env_get(env, name)
        if value is not None:
            return value
    return None


def _coalesce_config(*values: Any) -> Any:
    """Retorna el primer valor de configuracio present, preservant false i zero."""
    for value in values:
        if value is not None:
            return value
    return None


def _as_mapping(value: Any, field_name: str, *, required: bool) -> Dict[str, Any]:
    """Valida que una seccio de configuracio sigui un objecte TOML."""
    if value is None:
        if required:
            raise SystemExit(f"Falta la seccio [{field_name}] al fitxer de configuracio.")
        return {}
    if not isinstance(value, dict):
        raise SystemExit(f"La seccio [{field_name}] ha de ser un objecte TOML.")
    return value


def _parse_bool_value(value: Any, field_name: str, default: bool) -> bool:
    """Converteix un valor de configuracio a boolea amb error llegible."""
    if value is None:
        return default
    parsed = parse_boolean_value(value)
    if parsed is None:
        raise SystemExit(
            f"Valor invalid per {field_name}: {value}. Usa true/false, on/off o 1/0."
        )
    return parsed


def _parse_int_value(value: Any, field_name: str, default: int) -> int:
    """Converteix un valor de configuracio a enter."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"Valor invalid per {field_name}: {value}.") from exc


def _parse_float_value(value: Any, field_name: str, default: float) -> float:
    """Converteix un valor de configuracio a float."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"Valor invalid per {field_name}: {value}.") from exc


def _parse_qos_value(value: Any, field_name: str, default: int) -> int:
    """Valida que el QoS sigui 0, 1 o 2."""
    qos = _parse_int_value(value, field_name, default)
    if qos not in {0, 1, 2}:
        raise SystemExit(f"Valor invalid per {field_name}: {qos}. Usa 0, 1 o 2.")
    return qos


def _required_str(value: Any, field_name: str) -> str:
    """Valida un camp de configuracio obligatori de tipus string."""
    parsed = str(value or "").strip()
    if not parsed:
        raise SystemExit(f"Falta el camp obligatori {field_name}.")
    return parsed


def _optional_str(value: Any, default: str) -> str:
    """Retorna un string opcional amb default."""
    parsed = str(value or "").strip()
    return parsed if parsed else default


def _load_toml_file(path: Path) -> Dict[str, Any]:
    """Carrega un fitxer TOML amb errors orientats a operacio."""
    if tomllib is None:
        raise SystemExit("La configuracio TOML necessita Python 3.11 o superior.")
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise SystemExit(f"No existeix el fitxer de configuracio: {path}") from exc
    except OSError as exc:
        raise SystemExit(f"No s'ha pogut llegir el fitxer de configuracio {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise SystemExit(f"TOML invalid a {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise SystemExit(f"El fitxer de configuracio {path} ha de contenir un objecte TOML.")
    return data


def parse_env_bool(name: str, default: bool, env: Optional[Mapping[str, str]] = None) -> bool:
    """Llegeix una variable d'entorn booleana reutilitzant el parser generic."""
    source = os.environ if env is None else env
    raw_value = source.get(name)
    if raw_value is None:
        return default
    return _parse_bool_value(raw_value, name, default)


def parse_env_qos(name: str, default: int, env: Optional[Mapping[str, str]] = None) -> int:
    """Valida que el QoS llegit de l'entorn sigui 0, 1 o 2."""
    source = os.environ if env is None else env
    return _parse_qos_value(source.get(name), name, default)


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
    sem6000_bluetooth_device: str
    sem6000_timeout_seconds: float
    sem6000_history_timeout_seconds: float
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
    admin_rpc_enabled: bool
    log_level: str

    @classmethod
    def from_sources(
        cls,
        config_path: Optional[str] = None,
        env: Optional[Mapping[str, str]] = None,
    ) -> "AppConfig":
        """Carrega configuracio des de TOML si existeix, o nomes entorn com a fallback."""
        source_env = os.environ if env is None else env
        if config_path:
            return cls.from_toml_file(Path(config_path), env=source_env)

        default_path = Path(DEFAULT_CONFIG_PATH)
        if default_path.exists():
            return cls.from_toml_file(default_path, env=source_env)

        return cls.from_env(env=source_env)

    @classmethod
    def from_toml_file(
        cls,
        path: Path,
        env: Optional[Mapping[str, str]] = None,
    ) -> "AppConfig":
        """Carrega el bridge des d'un fitxer TOML i aplica overrides d'entorn."""
        raw_config = _load_toml_file(path)
        source_env = os.environ if env is None else env

        thingsboard = _as_mapping(raw_config.get("thingsboard"), "thingsboard", required=True)
        runtime = _as_mapping(raw_config.get("runtime"), "runtime", required=False)
        devices = _as_mapping(raw_config.get("devices"), "devices", required=True)

        active_device = _optional_str(
            _first_env(source_env, "SEM6000_ACTIVE_DEVICE"),
            _optional_str(raw_config.get("active_device"), ""),
        )
        if not active_device:
            raise SystemExit("Falta el camp obligatori active_device.")

        active_device_config = devices.get(active_device)
        if not isinstance(active_device_config, dict):
            available = ", ".join(sorted(str(name) for name in devices)) or "(cap)"
            raise SystemExit(
                f"L'active_device '{active_device}' no existeix a [devices]. "
                f"Disponibles: {available}."
            )

        device_address = _required_str(
            _coalesce_config(
                _first_env(source_env, "SEM6000_DEVICE_ADDRESS"),
                active_device_config.get("address"),
            ),
            f"devices.{active_device}.address",
        )
        child_name = _optional_str(
            _coalesce_config(
                _first_env(source_env, "THINGSBOARD_CHILD_DEVICE_NAME"),
                active_device_config.get("child_device_name"),
            ),
            default_child_device_name(device_address),
        )
        child_type = _optional_str(
            _coalesce_config(
                _first_env(source_env, "THINGSBOARD_CHILD_DEVICE_TYPE"),
                active_device_config.get("child_device_type"),
            ),
            DEFAULT_CHILD_DEVICE_TYPE,
        )

        access_token = _required_str(
            _coalesce_config(
                _first_env(
                    source_env,
                    "THINGSBOARD_GATEWAY_ACCESS_TOKEN",
                    "THINGSBOARD_ACCESS_TOKEN",
                ),
                thingsboard.get("gateway_access_token"),
            ),
            "thingsboard.gateway_access_token",
        )

        tls_mode = _optional_str(
            _coalesce_config(
                _first_env(source_env, "THINGSBOARD_TLS_MODE"),
                thingsboard.get("tls_mode"),
            ),
            "fallback",
        ).lower()
        if tls_mode not in {"required", "disabled", "fallback"}:
            raise SystemExit(
                "THINGSBOARD_TLS_MODE invalid. Valors permesos: required, disabled, fallback."
            )

        telemetry_interval_on = _parse_float_value(
            _coalesce_config(
                _first_env(source_env, "TELEMETRY_INTERVAL_ON_SECONDS"),
                active_device_config.get("telemetry_interval_on_seconds"),
                runtime.get("telemetry_interval_on_seconds"),
            ),
            "telemetry_interval_on_seconds",
            1.0,
        )
        if telemetry_interval_on <= 0:
            raise SystemExit("TELEMETRY_INTERVAL_ON_SECONDS ha de ser > 0.")

        off_heartbeat = _parse_float_value(
            _coalesce_config(
                _first_env(source_env, "OFF_HEARTBEAT_SECONDS"),
                active_device_config.get("off_heartbeat_seconds"),
                runtime.get("off_heartbeat_seconds"),
            ),
            "off_heartbeat_seconds",
            30.0,
        )
        if off_heartbeat <= 0:
            raise SystemExit("OFF_HEARTBEAT_SECONDS ha de ser > 0.")

        queue_size = _parse_int_value(
            _coalesce_config(
                _first_env(source_env, "RPC_QUEUE_SIZE"),
                runtime.get("rpc_queue_size"),
            ),
            "rpc_queue_size",
            128,
        )
        if queue_size <= 0:
            raise SystemExit("RPC_QUEUE_SIZE ha de ser > 0.")

        if not child_name:
            raise SystemExit("THINGSBOARD_CHILD_DEVICE_NAME no pot ser buit.")
        if not child_type:
            raise SystemExit("THINGSBOARD_CHILD_DEVICE_TYPE no pot ser buit.")

        timeout_seconds = _parse_float_value(
            _coalesce_config(
                _first_env(source_env, "SEM6000_TIMEOUT_SECONDS"),
                active_device_config.get("timeout_seconds"),
                runtime.get("sem6000_timeout_seconds"),
            ),
            "sem6000_timeout_seconds",
            DEFAULT_SEM6000_TIMEOUT_SECONDS,
        )
        history_timeout_seconds = _parse_float_value(
            _coalesce_config(
                _first_env(source_env, "SEM6000_HISTORY_TIMEOUT_SECONDS"),
                active_device_config.get("history_timeout_seconds"),
                runtime.get("sem6000_history_timeout_seconds"),
            ),
            "sem6000_history_timeout_seconds",
            DEFAULT_HISTORY_TIMEOUT_SECONDS,
        )

        return cls(
            sem6000_device_address=device_address,
            sem6000_pin=_optional_str(
                _coalesce_config(
                    _first_env(source_env, "SEM6000_PIN"),
                    active_device_config.get("pin"),
                ),
                DEFAULT_SEM6000_PIN,
            ),
            sem6000_bluetooth_device=_optional_str(
                _coalesce_config(
                    _first_env(source_env, "SEM6000_BLUETOOTH_DEVICE"),
                    active_device_config.get("bluetooth_device"),
                    runtime.get("sem6000_bluetooth_device"),
                ),
                DEFAULT_BLUETOOTH_DEVICE,
            ),
            sem6000_timeout_seconds=timeout_seconds,
            sem6000_history_timeout_seconds=history_timeout_seconds,
            sem6000_debug=_parse_bool_value(
                _coalesce_config(
                    _first_env(source_env, "SEM6000_DEBUG"),
                    active_device_config.get("debug"),
                    runtime.get("sem6000_debug"),
                ),
                "sem6000_debug",
                False,
            ),
            tb_host=_optional_str(
                _coalesce_config(
                    _first_env(source_env, "THINGSBOARD_MQTT_HOST"),
                    thingsboard.get("host"),
                ),
                DEFAULT_TB_HOST,
            ),
            tb_gateway_access_token=access_token,
            tb_client_id=_optional_str(
                _coalesce_config(
                    _first_env(source_env, "THINGSBOARD_CLIENT_ID"),
                    thingsboard.get("client_id"),
                ),
                DEFAULT_TB_CLIENT_ID,
            ),
            tb_control_qos=_parse_qos_value(
                _coalesce_config(
                    _first_env(source_env, "THINGSBOARD_CONTROL_QOS"),
                    thingsboard.get("control_qos"),
                ),
                "thingsboard.control_qos",
                1,
            ),
            tb_telemetry_qos=_parse_qos_value(
                _coalesce_config(
                    _first_env(source_env, "THINGSBOARD_TELEMETRY_QOS"),
                    thingsboard.get("telemetry_qos"),
                ),
                "thingsboard.telemetry_qos",
                0,
            ),
            tb_keepalive=_parse_int_value(
                _coalesce_config(
                    _first_env(source_env, "THINGSBOARD_KEEPALIVE"),
                    thingsboard.get("keepalive"),
                ),
                "thingsboard.keepalive",
                30,
            ),
            tb_tls_mode=tls_mode,
            tb_tls_port=_parse_int_value(
                _coalesce_config(
                    _first_env(source_env, "THINGSBOARD_MQTT_PORT_TLS"),
                    thingsboard.get("tls_port"),
                ),
                "thingsboard.tls_port",
                8883,
            ),
            tb_plain_port=_parse_int_value(
                _coalesce_config(
                    _first_env(source_env, "THINGSBOARD_MQTT_PORT_PLAIN"),
                    thingsboard.get("plain_port"),
                ),
                "thingsboard.plain_port",
                1883,
            ),
            tb_child_device_name=child_name,
            tb_child_device_type=child_type,
            telemetry_interval_on_seconds=telemetry_interval_on,
            off_heartbeat_seconds=off_heartbeat,
            rpc_queue_size=queue_size,
            mqtt_connect_timeout_seconds=_parse_float_value(
                _coalesce_config(
                    _first_env(source_env, "MQTT_CONNECT_TIMEOUT_SECONDS"),
                    thingsboard.get("connect_timeout_seconds"),
                    runtime.get("mqtt_connect_timeout_seconds"),
                ),
                "mqtt_connect_timeout_seconds",
                10.0,
            ),
            enable_extended_measurements=_parse_bool_value(
                _coalesce_config(
                    _first_env(source_env, "ENABLE_EXTENDED_MEASUREMENTS"),
                    active_device_config.get("enable_extended_measurements"),
                    runtime.get("enable_extended_measurements"),
                ),
                "enable_extended_measurements",
                False,
            ),
            admin_rpc_enabled=_parse_bool_value(
                _coalesce_config(
                    _first_env(source_env, "ADMIN_RPC_ENABLED"),
                    active_device_config.get("admin_rpc_enabled"),
                    runtime.get("admin_rpc_enabled"),
                ),
                "admin_rpc_enabled",
                False,
            ),
            log_level=_optional_str(
                _coalesce_config(
                    _first_env(source_env, "LOG_LEVEL"),
                    runtime.get("log_level"),
                ),
                "INFO",
            ),
        )

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "AppConfig":
        source_env = os.environ if env is None else env

        tls_mode = _optional_str(source_env.get("THINGSBOARD_TLS_MODE"), "fallback").lower()
        if tls_mode not in {"required", "disabled", "fallback"}:
            raise SystemExit(
                "THINGSBOARD_TLS_MODE invalid. Valors permesos: required, disabled, fallback."
            )

        device_address = _required_str(
            _first_env(source_env, "SEM6000_DEVICE_ADDRESS"),
            "SEM6000_DEVICE_ADDRESS",
        )
        child_name = _optional_str(
            _first_env(source_env, "THINGSBOARD_CHILD_DEVICE_NAME"),
            default_child_device_name(device_address),
        )
        child_type = _optional_str(
            _first_env(source_env, "THINGSBOARD_CHILD_DEVICE_TYPE"),
            DEFAULT_CHILD_DEVICE_TYPE,
        )

        access_token = _required_str(
            _first_env(
                source_env,
                "THINGSBOARD_GATEWAY_ACCESS_TOKEN",
                "THINGSBOARD_ACCESS_TOKEN",
            ),
            "THINGSBOARD_GATEWAY_ACCESS_TOKEN",
        )

        telemetry_interval_on = _parse_float_value(
            source_env.get("TELEMETRY_INTERVAL_ON_SECONDS"),
            "TELEMETRY_INTERVAL_ON_SECONDS",
            1.0,
        )
        if telemetry_interval_on <= 0:
            raise SystemExit("TELEMETRY_INTERVAL_ON_SECONDS ha de ser > 0.")

        off_heartbeat = _parse_float_value(
            source_env.get("OFF_HEARTBEAT_SECONDS"),
            "OFF_HEARTBEAT_SECONDS",
            30.0,
        )
        if off_heartbeat <= 0:
            raise SystemExit("OFF_HEARTBEAT_SECONDS ha de ser > 0.")

        queue_size = _parse_int_value(source_env.get("RPC_QUEUE_SIZE"), "RPC_QUEUE_SIZE", 128)
        if queue_size <= 0:
            raise SystemExit("RPC_QUEUE_SIZE ha de ser > 0.")
        if not child_name:
            raise SystemExit("THINGSBOARD_CHILD_DEVICE_NAME no pot ser buit.")
        if not child_type:
            raise SystemExit("THINGSBOARD_CHILD_DEVICE_TYPE no pot ser buit.")

        return cls(
            sem6000_device_address=device_address,
            sem6000_pin=_optional_str(source_env.get("SEM6000_PIN"), DEFAULT_SEM6000_PIN),
            sem6000_bluetooth_device=_optional_str(
                source_env.get("SEM6000_BLUETOOTH_DEVICE"),
                DEFAULT_BLUETOOTH_DEVICE,
            ),
            sem6000_timeout_seconds=_parse_float_value(
                source_env.get("SEM6000_TIMEOUT_SECONDS"),
                "SEM6000_TIMEOUT_SECONDS",
                DEFAULT_SEM6000_TIMEOUT_SECONDS,
            ),
            sem6000_history_timeout_seconds=_parse_float_value(
                source_env.get("SEM6000_HISTORY_TIMEOUT_SECONDS"),
                "SEM6000_HISTORY_TIMEOUT_SECONDS",
                DEFAULT_HISTORY_TIMEOUT_SECONDS,
            ),
            sem6000_debug=parse_env_bool("SEM6000_DEBUG", False, env=source_env),
            tb_host=_optional_str(source_env.get("THINGSBOARD_MQTT_HOST"), DEFAULT_TB_HOST),
            tb_gateway_access_token=access_token,
            tb_client_id=_optional_str(source_env.get("THINGSBOARD_CLIENT_ID"), DEFAULT_TB_CLIENT_ID),
            tb_control_qos=parse_env_qos("THINGSBOARD_CONTROL_QOS", 1, env=source_env),
            tb_telemetry_qos=parse_env_qos("THINGSBOARD_TELEMETRY_QOS", 0, env=source_env),
            tb_keepalive=_parse_int_value(
                source_env.get("THINGSBOARD_KEEPALIVE"),
                "THINGSBOARD_KEEPALIVE",
                30,
            ),
            tb_tls_mode=tls_mode,
            tb_tls_port=_parse_int_value(
                source_env.get("THINGSBOARD_MQTT_PORT_TLS"),
                "THINGSBOARD_MQTT_PORT_TLS",
                8883,
            ),
            tb_plain_port=_parse_int_value(
                source_env.get("THINGSBOARD_MQTT_PORT_PLAIN"),
                "THINGSBOARD_MQTT_PORT_PLAIN",
                1883,
            ),
            tb_child_device_name=child_name,
            tb_child_device_type=child_type,
            telemetry_interval_on_seconds=telemetry_interval_on,
            off_heartbeat_seconds=off_heartbeat,
            rpc_queue_size=queue_size,
            mqtt_connect_timeout_seconds=_parse_float_value(
                source_env.get("MQTT_CONNECT_TIMEOUT_SECONDS"),
                "MQTT_CONNECT_TIMEOUT_SECONDS",
                10.0,
            ),
            enable_extended_measurements=parse_env_bool(
                "ENABLE_EXTENDED_MEASUREMENTS",
                False,
                env=source_env,
            ),
            admin_rpc_enabled=parse_env_bool(
                "ADMIN_RPC_ENABLED",
                False,
                env=source_env,
            ),
            log_level=_optional_str(source_env.get("LOG_LEVEL"), "INFO"),
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
        history_timeout_seconds: float,
        debug: bool,
        log: logging.Logger,
        bluetooth_device: str = DEFAULT_BLUETOOTH_DEVICE,
        stop_event: Optional[threading.Event] = None,
    ) -> None:
        self._address = address
        self._pin = pin
        self._bluetooth_device = bluetooth_device
        self._timeout_seconds = timeout_seconds
        self._history_timeout_seconds = max(history_timeout_seconds, timeout_seconds)
        self._debug = debug
        self._log = log
        self._stop_event = stop_event

        self._device: Any = None
        self._lock = threading.Lock()
        self._sem6000_module: Any = None
        self._is_connected = False
        self._last_operation_ms: Optional[float] = None

    def _should_stop(self) -> bool:
        return bool(self._stop_event is not None and self._stop_event.is_set())

    def _patch_sem6000_delegate(self, sem_module: Any) -> None:
        """Aplica pegats per fer mes robust el transport BLE de la llibreria base."""
        sem6000_ns = getattr(sem_module, "sem6000", None)
        delegate_cls = getattr(sem6000_ns, "SEM6000Delegate", None)
        sem_cls = getattr(sem6000_ns, "SEM6000", None)
        parser_cls = getattr(getattr(sem6000_ns, "parser", None), "MessageParser", None)

        if delegate_cls is not None and not getattr(
            delegate_cls, "_codis_completion_patch_applied", False
        ):
            def _patched_has_final_raw_notification(delegate_self: Any) -> bool:
                return sem6000_raw_notifications_complete(
                    getattr(delegate_self, "_raw_notifications", []),
                    getattr(delegate_self, "hardware_version", None),
                )

            delegate_cls.has_final_raw_notification = _patched_has_final_raw_notification
            delegate_cls._codis_completion_patch_applied = True

        if parser_cls is not None and not getattr(
            parser_cls, "_codis_payload_patch_applied", False
        ):
            def _patched_parse_payload(parser_self: Any, data: bytes) -> bytes:
                return _parse_sem6000_payload_lenient(
                    data,
                    getattr(parser_self, "hardware_version", None),
                )

            parser_cls._parse_payload = _patched_parse_payload
            parser_cls._codis_payload_patch_applied = True

        if sem_cls is not None and not getattr(sem_cls, "_codis_wait_patch_applied", False):
            def _patched_wait_for_notifications(device_self: Any) -> None:
                should_stop = getattr(device_self, "_codis_should_stop", None)
                wait_for_sem6000_notifications(
                    getattr(device_self._bluetooth_lowenergy_interface, "wait_for_notifications"),
                    getattr(device_self, "_delegate"),
                    float(getattr(device_self, "timeout", self._timeout_seconds)),
                    should_stop=should_stop if callable(should_stop) else None,
                )

            sem_cls._wait_for_notifications = _patched_wait_for_notifications
            sem_cls._codis_wait_patch_applied = True

        if (
            sem6000_ns is not None
            and sem_cls is not None
            and not getattr(sem_cls, "_codis_history_patch_applied", False)
        ):
            def _request_history_once(
                device_self: Any,
                command_class_name: str,
                notification_class_name: str,
                error_message: str,
            ) -> Any:
                command_cls = getattr(sem6000_ns, command_class_name)
                notification_cls = getattr(sem6000_ns, notification_class_name)
                device_self._send_command(command_cls())
                notification = device_self._consume_notification()
                if not isinstance(notification, notification_cls):
                    raise Exception(error_message)
                return notification

            def _patched_request_consumption_of_last_23_hours(device_self: Any) -> Any:
                return _request_history_once(
                    device_self,
                    "RequestConsumptionOfLast23HoursCommand",
                    "ConsumptionOfLast23HoursRequestedNotification",
                    "Request consumption of last 23 hours failed",
                )

            def _patched_request_consumption_of_last_30_days(device_self: Any) -> Any:
                return _request_history_once(
                    device_self,
                    "RequestConsumptionOfLast30DaysCommand",
                    "ConsumptionOfLast30DaysRequestedNotification",
                    "Request consumption of last 30 days failed",
                )

            def _patched_request_consumption_of_last_12_months(device_self: Any) -> Any:
                return _request_history_once(
                    device_self,
                    "RequestConsumptionOfLast12MonthsCommand",
                    "ConsumptionOfLast12MonthsRequestedNotification",
                    "Request consumption of last 12 months failed",
                )

            sem_cls.request_consumption_of_last_23_hours = (
                _patched_request_consumption_of_last_23_hours
            )
            sem_cls.request_consumption_of_last_30_days = (
                _patched_request_consumption_of_last_30_days
            )
            sem_cls.request_consumption_of_last_12_months = (
                _patched_request_consumption_of_last_12_months
            )
            sem_cls._codis_history_patch_applied = True

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
        self._patch_sem6000_delegate(sem_module)
        self._sem6000_module = sem_module
        return sem_module

    def _new_device(self) -> Any:
        sem_module = self._import_sem6000_module()
        sem6000_mod = sem_module.sem6000
        device = sem6000_mod.SEM6000(
            deviceAddr=self._address,
            pin=self._pin,
            bluetooth_device=self._bluetooth_device,
            timeout=self._timeout_seconds,
            debug=self._debug,
        )
        device._codis_should_stop = self._should_stop
        return device

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

    def _call_device_with_timeout_locked(
        self,
        operation: Callable[[Any], Any],
        timeout_seconds: Optional[float],
    ) -> Any:
        device = self._device
        if timeout_seconds is None or device is None or not hasattr(device, "timeout"):
            return operation(device)

        previous_timeout = getattr(device, "timeout")
        device.timeout = timeout_seconds
        try:
            return operation(device)
        finally:
            device.timeout = previous_timeout

    def _run_ble(
        self,
        operation_name: str,
        operation: Callable[[Any], Any],
        *,
        timeout_seconds: Optional[float] = None,
    ) -> Any:
        with self._lock:
            started_at = time.monotonic()
            try:
                if self._should_stop():
                    raise CommandError(
                        f"{operation_name} cancelada per aturada de l'agent.",
                        code="stopping",
                    )
                self._ensure_connected_locked()
                result = self._call_device_with_timeout_locked(operation, timeout_seconds)
                self._is_connected = True
                return result
            except CommandError:
                raise
            except Exception as first_exc:
                self._is_connected = False
                if self._should_stop():
                    raise CommandError(
                        f"{operation_name} cancelada per aturada de l'agent.",
                        code="stopping",
                    ) from first_exc
                self._log.warning(
                    "%s ha fallat (%s). Reconnectant i reintentant una vegada.",
                    operation_name,
                    first_exc,
                )
                try:
                    self._reconnect_locked()
                    if self._device is not None:
                        self._device._codis_should_stop = self._should_stop
                    result = self._call_device_with_timeout_locked(
                        operation,
                        timeout_seconds,
                    )
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

    def request_settings(self) -> Any:
        return self._run_ble(
            "request_settings",
            lambda device: device.request_settings(),
        )

    def set_night_mode(self, enabled: bool) -> None:
        if enabled:
            self._run_ble("nightmode_on", lambda device: device.nightmode_on())
        else:
            self._run_ble("nightmode_off", lambda device: device.nightmode_off())

    def set_power_limit(self, power_limit_w: int) -> None:
        self._run_ble(
            "set_power_limit",
            lambda device: device.change_power_limit(power_limit_w),
        )

    def set_prices(self, normal_price_cent: int, reduced_price_cent: int) -> None:
        self._run_ble(
            "set_prices",
            lambda device: device.change_prices(
                normal_price_cent,
                reduced_price_cent,
            ),
        )

    def set_reduced_period(self, enabled: bool, start_isotime: str, end_isotime: str) -> None:
        self._run_ble(
            "set_reduced_period",
            lambda device: device.change_reduced_period(
                enabled,
                start_isotime,
                end_isotime,
            ),
        )

    def request_device_name(self) -> Any:
        return self._run_ble(
            "request_device_name",
            lambda device: device.request_device_name(),
        )

    def change_device_name(self, device_name: str) -> None:
        self._run_ble(
            "change_device_name",
            lambda device: device.change_device_name(device_name),
        )

    def request_device_serial(self) -> Any:
        return self._run_ble(
            "request_device_serial",
            lambda device: device.request_device_serial(),
        )

    def request_timer_status(self) -> Any:
        return self._run_ble(
            "request_timer_status",
            lambda device: device.request_timer_status(),
        )

    def activate_timer_at(self, turn_on: bool, target_isodatetime: str) -> None:
        self._run_ble(
            "activate_timer_at",
            lambda device: device.activate_timer_at(turn_on, target_isodatetime),
        )

    def reset_timer(self) -> None:
        self._run_ble(
            "reset_timer",
            lambda device: device.reset_timer(),
        )

    def request_random_mode_status(self) -> Any:
        return self._run_ble(
            "request_random_mode_status",
            lambda device: device.request_random_mode_status(),
        )

    def change_random_mode(self, weekdays: str, start_isotime: str, end_isotime: str) -> None:
        self._run_ble(
            "change_random_mode",
            lambda device: device.change_random_mode(
                weekdays,
                start_isotime,
                end_isotime,
            ),
        )

    def reset_random_mode(self) -> None:
        self._run_ble(
            "reset_random_mode",
            lambda device: device.reset_random_mode(),
        )

    def request_scheduler(self) -> Any:
        return self._run_ble(
            "request_scheduler",
            lambda device: device.request_scheduler(),
        )

    def add_onetime_scheduler(
        self,
        enabled: bool,
        turn_on: bool,
        target_isodatetime: str,
    ) -> None:
        self._run_ble(
            "add_onetime_scheduler",
            lambda device: device.add_onetime_scheduler(
                enabled,
                turn_on,
                target_isodatetime,
            ),
        )

    def edit_onetime_scheduler(
        self,
        slot_id: int,
        enabled: bool,
        turn_on: bool,
        target_isodatetime: str,
    ) -> None:
        self._run_ble(
            "edit_onetime_scheduler",
            lambda device: device.edit_onetime_scheduler(
                slot_id,
                enabled,
                turn_on,
                target_isodatetime,
            ),
        )

    def add_repeated_scheduler(
        self,
        enabled: bool,
        turn_on: bool,
        weekdays: str,
        isotime: str,
    ) -> None:
        self._run_ble(
            "add_repeated_scheduler",
            lambda device: device.add_repeated_scheduler(
                enabled,
                turn_on,
                weekdays,
                isotime,
            ),
        )

    def edit_repeated_scheduler(
        self,
        slot_id: int,
        enabled: bool,
        turn_on: bool,
        weekdays: str,
        isotime: str,
    ) -> None:
        self._run_ble(
            "edit_repeated_scheduler",
            lambda device: device.edit_repeated_scheduler(
                slot_id,
                enabled,
                turn_on,
                weekdays,
                isotime,
            ),
        )

    def remove_scheduler(self, slot_id: int) -> None:
        self._run_ble(
            "remove_scheduler",
            lambda device: device.remove_scheduler(slot_id),
        )

    def request_consumption_of_last_23_hours(self) -> Any:
        return self._run_ble(
            "request_consumption_of_last_23_hours",
            lambda device: device.request_consumption_of_last_23_hours(),
            timeout_seconds=self._history_timeout_seconds,
        )

    def request_consumption_of_last_30_days(self) -> Any:
        return self._run_ble(
            "request_consumption_of_last_30_days",
            lambda device: device.request_consumption_of_last_30_days(),
            timeout_seconds=self._history_timeout_seconds,
        )

    def request_consumption_of_last_12_months(self) -> Any:
        return self._run_ble(
            "request_consumption_of_last_12_months",
            lambda device: device.request_consumption_of_last_12_months(),
            timeout_seconds=self._history_timeout_seconds,
        )

    def reset_consumption(self) -> None:
        self._run_ble(
            "reset_consumption",
            lambda device: device.reset_consumption(),
        )

    def change_pin(self, new_pin: str) -> None:
        self._run_ble(
            "change_pin",
            lambda device: device.change_pin(new_pin),
        )
        with self._lock:
            self._pin = new_pin
            if self._device is not None and hasattr(self._device, "pin"):
                self._device.pin = new_pin

    def reset_pin(self) -> None:
        self._run_ble(
            "reset_pin",
            lambda device: device.reset_pin(),
        )
        with self._lock:
            self._pin = "0000"
            if self._device is not None and hasattr(self._device, "pin"):
                self._device.pin = "0000"

    def factory_reset(self) -> None:
        self._run_ble(
            "factory_reset",
            lambda device: device.factory_reset(),
        )
        with self._lock:
            self._pin = "0000"
            self._disconnect_locked()

    def last_operation_ms(self) -> Optional[float]:
        if not self._lock.acquire(timeout=0.05):
            return self._last_operation_ms
        try:
            return self._last_operation_ms
        finally:
            self._lock.release()

    def is_connected(self) -> bool:
        if not self._lock.acquire(timeout=0.05):
            return self._is_connected
        try:
            return self._is_connected
        finally:
            self._lock.release()

    def disconnect(self, wait_timeout_seconds: float = 1.0) -> bool:
        acquired = self._lock.acquire(timeout=max(float(wait_timeout_seconds), 0.0))
        if not acquired:
            self._log.warning(
                "No s'ha pogut tancar BLE ara mateix: hi ha una operacio en curs."
            )
            return False
        try:
            self._disconnect_locked()
            return True
        finally:
            self._lock.release()


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


class ConfigurationHandler:
    """Gestiona la lectura i mutacio dels settings del SEM6000."""

    methods = (
        "getSettings",
        "setNightMode",
        "setPowerLimit",
        "setPrices",
        "setReducedPeriod",
    )

    def handle(self, method_name: str, params: Any, context: CommandContext) -> Dict[str, Any]:
        method_key = normalize_method(method_name)

        if method_key == "getsettings":
            settings_payload = normalize_settings_notification(context.sem.request_settings())
            context.attributes.publish(flatten_settings_attributes(settings_payload))
            return settings_payload

        if method_key == "setnightmode":
            enabled = parse_boolean_value(params)
            if enabled is None and isinstance(params, dict):
                enabled = parse_boolean_value(params.get("enabled"))
            if enabled is None:
                raise CommandError(
                    "El metode necessita un parametre boolea 'enabled'.",
                    code="invalid_params",
                )
            context.sem.set_night_mode(enabled)
            response = {"night_mode": enabled}
            context.attributes.publish(response)
            return response

        if method_key == "setpowerlimit":
            raw_value = params.get("power_limit_w") if isinstance(params, dict) else params
            power_limit_w = _normalize_positive_int(raw_value, field_name="power_limit_w")
            context.sem.set_power_limit(power_limit_w)
            response = {"power_limit_w": power_limit_w}
            context.attributes.publish(response)
            return response

        if method_key == "setprices":
            params_dict = _require_dict_params(params, method_name=method_name)
            normal_price_cent = _normalize_positive_int(
                params_dict.get("normal_price_cent"),
                field_name="normal_price_cent",
                allow_zero=True,
            )
            reduced_price_cent = _normalize_positive_int(
                params_dict.get("reduced_price_cent"),
                field_name="reduced_price_cent",
                allow_zero=True,
            )
            context.sem.set_prices(normal_price_cent, reduced_price_cent)
            response = {
                "prices": {
                    "normal_price_cent": normal_price_cent,
                    "reduced_price_cent": reduced_price_cent,
                }
            }
            context.attributes.publish(
                {
                    "price_normal_cent": normal_price_cent,
                    "price_reduced_cent": reduced_price_cent,
                }
            )
            return response

        if method_key == "setreducedperiod":
            params_dict = _require_dict_params(params, method_name=method_name)
            enabled = parse_boolean_value(params_dict.get("enabled"))
            if enabled is None:
                raise CommandError(
                    "El camp enabled ha de ser boolea.",
                    code="invalid_params",
                )
            start_isotime = _normalize_isotime_minutes(
                params_dict.get("start"),
                field_name="start",
            )
            end_isotime = _normalize_isotime_minutes(
                params_dict.get("end"),
                field_name="end",
            )
            context.sem.set_reduced_period(enabled, start_isotime, end_isotime)
            response = {
                "reduced_period": {
                    "enabled": enabled,
                    "start": start_isotime,
                    "end": end_isotime,
                }
            }
            context.attributes.publish(
                {
                    "reduced_period_enabled": enabled,
                    "reduced_period_start": start_isotime,
                    "reduced_period_end": end_isotime,
                }
            )
            return response

        raise CommandError(
            f"Metode RPC no suportat pel ConfigurationHandler: {method_name}",
            code="unknown_method",
        )


class IdentityHandler:
    """Gestiona la identitat visible del dispositiu SEM6000."""

    methods = (
        "getDeviceName",
        "setDeviceName",
        "getDeviceSerial",
    )

    def handle(self, method_name: str, params: Any, context: CommandContext) -> Dict[str, Any]:
        method_key = normalize_method(method_name)

        if method_key == "getdevicename":
            notification = context.sem.request_device_name()
            device_name = str(getattr(notification, "device_name", "")).strip()
            response = {"device_name": device_name}
            context.attributes.publish(response)
            return response

        if method_key == "setdevicename":
            raw_name = params.get("device_name") if isinstance(params, dict) else params
            device_name = str(raw_name or "").strip()
            if not device_name:
                raise CommandError(
                    "El camp device_name no pot ser buit.",
                    code="invalid_params",
                )
            if len(device_name) > 18:
                raise CommandError(
                    "El camp device_name no pot superar els 18 caracters.",
                    code="invalid_params",
                )
            context.sem.change_device_name(device_name)
            response = {"device_name": device_name}
            context.attributes.publish(response)
            return response

        if method_key == "getdeviceserial":
            notification = context.sem.request_device_serial()
            return {"device_serial": str(getattr(notification, "serial", "")).strip()}

        raise CommandError(
            f"Metode RPC no suportat pel IdentityHandler: {method_name}",
            code="unknown_method",
        )


class TimerHandler:
    """Gestiona el timer del SEM6000."""

    methods = (
        "getTimer",
        "setTimer",
        "resetTimer",
    )

    def handle(self, method_name: str, params: Any, context: CommandContext) -> Dict[str, Any]:
        method_key = normalize_method(method_name)

        if method_key == "gettimer":
            timer_payload = normalize_timer_status_notification(
                context.sem.request_timer_status()
            )
            context.attributes.publish(flatten_timer_attributes(timer_payload))
            return timer_payload

        if method_key == "settimer":
            params_dict = _require_dict_params(params, method_name=method_name)
            action = _normalize_action_label(
                params_dict.get("action"),
                field_name="action",
            )
            target_isodatetime = _normalize_isodatetime_seconds(
                params_dict.get("target_isodatetime"),
                field_name="target_isodatetime",
            )
            context.sem.activate_timer_at(
                _action_label_to_bool(action),
                target_isodatetime,
            )
            timer_payload = normalize_timer_status_notification(
                context.sem.request_timer_status()
            )
            context.attributes.publish(flatten_timer_attributes(timer_payload))
            return timer_payload

        if method_key == "resettimer":
            context.sem.reset_timer()
            timer_payload = normalize_timer_status_notification(
                context.sem.request_timer_status()
            )
            context.attributes.publish(flatten_timer_attributes(timer_payload))
            return timer_payload

        raise CommandError(
            f"Metode RPC no suportat pel TimerHandler: {method_name}",
            code="unknown_method",
        )


class RandomModeHandler:
    """Gestiona el random mode del SEM6000."""

    methods = (
        "getRandomMode",
        "setRandomMode",
        "resetRandomMode",
    )

    def handle(self, method_name: str, params: Any, context: CommandContext) -> Dict[str, Any]:
        method_key = normalize_method(method_name)

        if method_key == "getrandommode":
            random_mode_payload = normalize_random_mode_notification(
                context.sem.request_random_mode_status()
            )
            context.attributes.publish(
                flatten_random_mode_attributes(random_mode_payload)
            )
            return random_mode_payload

        if method_key == "setrandommode":
            params_dict = _require_dict_params(params, method_name=method_name)
            weekdays = _normalize_weekdays_string(
                params_dict.get("weekdays"),
                field_name="weekdays",
            )
            start_isotime = _normalize_isotime_minutes(
                params_dict.get("start"),
                field_name="start",
            )
            end_isotime = _normalize_isotime_minutes(
                params_dict.get("end"),
                field_name="end",
            )
            context.sem.change_random_mode(weekdays, start_isotime, end_isotime)
            random_mode_payload = normalize_random_mode_notification(
                context.sem.request_random_mode_status()
            )
            context.attributes.publish(
                flatten_random_mode_attributes(random_mode_payload)
            )
            return random_mode_payload

        if method_key == "resetrandommode":
            context.sem.reset_random_mode()
            random_mode_payload = normalize_random_mode_notification(
                context.sem.request_random_mode_status()
            )
            context.attributes.publish(
                flatten_random_mode_attributes(random_mode_payload)
            )
            return random_mode_payload

        raise CommandError(
            f"Metode RPC no suportat pel RandomModeHandler: {method_name}",
            code="unknown_method",
        )


class ScheduleHandler:
    """Exposa la gestio completa de schedulers del SEM6000 via RPC."""

    methods = (
        "getScheduler",
        "getSchedulers",
        "addScheduler",
        "editScheduler",
        "addOnetimeScheduler",
        "editOnetimeScheduler",
        "addRepeatedScheduler",
        "editRepeatedScheduler",
        "removeScheduler",
    )

    @staticmethod
    def _refresh_schedulers(context: CommandContext) -> Dict[str, Any]:
        return normalize_scheduler_notification(context.sem.request_scheduler())

    def handle(self, method_name: str, params: Any, context: CommandContext) -> Dict[str, Any]:
        method_key = normalize_method(method_name)

        if method_key in {"getscheduler", "getschedulers"}:
            return self._refresh_schedulers(context)

        if method_key == "removescheduler":
            raw_slot_id = params.get("slot_id") if isinstance(params, dict) else params
            slot_id = _normalize_slot_id(raw_slot_id)
            context.sem.remove_scheduler(slot_id)
            return self._refresh_schedulers(context)

        params_dict = _require_dict_params(params, method_name=method_name)
        enabled = _normalize_bool_field(
            params_dict,
            field_name="enabled",
            aliases=("active", "is_active"),
        )
        action = _normalize_action_field(params_dict)
        turn_on = _action_label_to_bool(action)

        scheduler_type: Optional[str] = None
        if method_key in {"addscheduler", "editscheduler"}:
            scheduler_type = _normalize_scheduler_type(
                params_dict.get("type", params_dict.get("scheduler_type")),
            )
        elif method_key in {"addonetimescheduler", "editonetimescheduler"}:
            scheduler_type = "onetime"
        elif method_key in {"addrepeatedscheduler", "editrepeatedscheduler"}:
            scheduler_type = "repeated"

        if scheduler_type is None:
            raise CommandError(
                f"Metode RPC no suportat pel ScheduleHandler: {method_name}",
                code="unknown_method",
            )

        slot_id: Optional[int] = None
        if method_key.startswith("edit"):
            slot_id = _normalize_slot_id(params_dict.get("slot_id"))

        if scheduler_type == "onetime":
            target_isodatetime = _normalize_isodatetime_seconds(
                params_dict.get("target_isodatetime"),
                field_name="target_isodatetime",
            )
            if slot_id is None:
                context.sem.add_onetime_scheduler(enabled, turn_on, target_isodatetime)
            else:
                context.sem.edit_onetime_scheduler(
                    slot_id,
                    enabled,
                    turn_on,
                    target_isodatetime,
                )
            return self._refresh_schedulers(context)

        weekdays = _normalize_weekdays_string(
            params_dict.get("weekdays"),
            field_name="weekdays",
        )
        isotime = _normalize_isotime_minutes(
            params_dict.get("time", params_dict.get("isotime")),
            field_name="time",
        )
        if slot_id is None:
            context.sem.add_repeated_scheduler(enabled, turn_on, weekdays, isotime)
        else:
            context.sem.edit_repeated_scheduler(
                slot_id,
                enabled,
                turn_on,
                weekdays,
                isotime,
            )
        return self._refresh_schedulers(context)


class ConsumptionHandler:
    """Exposa historics de consum i reset del comptador intern."""

    methods = (
        "getConsumption23h",
        "getConsumption30d",
        "getConsumption12m",
        "resetConsumption",
    )

    def handle(self, method_name: str, params: Any, context: CommandContext) -> Dict[str, Any]:
        method_key = normalize_method(method_name)

        if method_key == "getconsumption23h":
            return normalize_consumption_23h_notification(
                context.sem.request_consumption_of_last_23_hours()
            )

        if method_key == "getconsumption30d":
            return normalize_consumption_30d_notification(
                context.sem.request_consumption_of_last_30_days()
            )

        if method_key == "getconsumption12m":
            return normalize_consumption_12m_notification(
                context.sem.request_consumption_of_last_12_months()
            )

        if method_key == "resetconsumption":
            context.sem.reset_consumption()
            return {"consumption_reset": True}

        raise CommandError(
            f"Metode RPC no suportat pel ConsumptionHandler: {method_name}",
            code="unknown_method",
        )


class AdministrativeHandler:
    """Exposa operacions administratives sensibles del SEM6000."""

    methods = (
        "adminChangePin",
        "adminResetPin",
        "adminFactoryReset",
    )

    def handle(self, method_name: str, params: Any, context: CommandContext) -> Dict[str, Any]:
        method_key = normalize_method(method_name)

        if method_key == "adminchangepin":
            params_dict = _require_dict_params(params, method_name=method_name)
            new_pin = _normalize_pin(params_dict.get("new_pin"), field_name="new_pin")
            context.sem.change_pin(new_pin)
            return {"pin_changed": True}

        if method_key == "adminresetpin":
            context.sem.reset_pin()
            return {"pin_reset": True, "active_pin": "0000"}

        if method_key == "adminfactoryreset":
            context.sem.factory_reset()
            return {"factory_reset": True, "active_pin": "0000"}

        raise CommandError(
            f"Metode RPC no suportat pel AdministrativeHandler: {method_name}",
            code="unknown_method",
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
            history_timeout_seconds=config.sem6000_history_timeout_seconds,
            debug=config.sem6000_debug,
            log=self._log,
            bluetooth_device=config.sem6000_bluetooth_device,
            stop_event=self._stop_event,
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
        self._registry.register(ConfigurationHandler())
        self._registry.register(IdentityHandler())
        self._registry.register(TimerHandler())
        self._registry.register(RandomModeHandler())
        self._registry.register(ScheduleHandler())
        self._registry.register(ConsumptionHandler())
        if config.admin_rpc_enabled:
            self._registry.register(AdministrativeHandler())

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
        self._log.info(
            "Timeouts BLE: normal=%.1fs, historic=%.1fs",
            self._cfg.sem6000_timeout_seconds,
            self._cfg.sem6000_history_timeout_seconds,
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

    def request_stop(self) -> None:
        self._stop_event.set()

    def stop(self) -> None:
        self._stop_event.set()

        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=1)
        if self._telemetry_thread and self._telemetry_thread.is_alive():
            self._telemetry_thread.join(timeout=1)

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
        worker_busy = bool(self._worker_thread and self._worker_thread.is_alive())
        self._sem.disconnect(wait_timeout_seconds=0.0 if worker_busy else 1.0)

    def run_forever(self) -> None:
        self.start()
        self._log.info("Agent gateway en marxa. Ctrl+C per aturar.")
        while not self._stop_event.is_set():
            time.sleep(0.5)


def install_signal_handlers(agent: MqttSem6000Agent) -> None:
    """Instal.la handlers per aturar l'agent amb SIGINT o SIGTERM."""

    def _handle_signal(signum: int, frame: Any) -> None:
        logging.getLogger("Sem6000ThingsBoardMqttAgent").info(
            "Senyal %s rebuda. Demanant aturada de l'agent...", signum
        )
        agent.request_stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handle_signal)
        except ValueError:
            continue


def build_arg_parser() -> argparse.ArgumentParser:
    """Defineix la CLI operativa del bridge."""
    parser = argparse.ArgumentParser(
        description="Bridge MQTT gateway entre un Voltcraft SEM6000 i ThingsBoard.",
    )
    parser.add_argument(
        "--config",
        help=(
            "Fitxer TOML de configuracio. Si s'omet, s'intenta "
            f"{DEFAULT_CONFIG_PATH} i despres variables d'entorn."
        ),
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="Valida la configuracio i surt sense connectar BLE ni MQTT.",
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Escaneja dispositius SEM6000 visibles per BLE i surt.",
    )
    parser.add_argument(
        "--discover-timeout",
        type=float,
        default=5.0,
        help="Segons d'escaneig BLE per --discover.",
    )
    parser.add_argument(
        "--bluetooth-device",
        help="Adaptador BLE per --discover, per exemple hci0.",
    )
    return parser


def build_config_summary(config: AppConfig) -> Dict[str, Any]:
    """Retorna una vista segura de la configuracio carregada."""
    return {
        "sem6000_device_address": config.sem6000_device_address,
        "sem6000_bluetooth_device": config.sem6000_bluetooth_device,
        "tb_host": config.tb_host,
        "tb_client_id": config.tb_client_id,
        "tb_gateway_access_token": MqttSem6000Agent._mask_token(
            config.tb_gateway_access_token
        ),
        "tb_tls_mode": config.tb_tls_mode,
        "tb_child_device_name": config.tb_child_device_name,
        "tb_child_device_type": config.tb_child_device_type,
        "telemetry_interval_on_seconds": config.telemetry_interval_on_seconds,
        "off_heartbeat_seconds": config.off_heartbeat_seconds,
        "enable_extended_measurements": config.enable_extended_measurements,
        "admin_rpc_enabled": config.admin_rpc_enabled,
    }


def print_config_summary(config: AppConfig) -> None:
    """Mostra una validacio curta apta per usar amb systemd o terminal."""
    print("Configuracio SEM6000 bridge OK:")
    for key, value in build_config_summary(config).items():
        print(f"- {key}: {value}")


def bluetooth_device_hint_from_toml(path: Path) -> str:
    """Llegeix nomes l'adaptador BLE d'un TOML, sense validar MQTT."""
    raw_config = _load_toml_file(path)
    runtime = raw_config.get("runtime")
    if isinstance(runtime, dict):
        bluetooth_device = _optional_str(
            runtime.get("sem6000_bluetooth_device"),
            "",
        )
        if bluetooth_device:
            return bluetooth_device

    active_device = _optional_str(raw_config.get("active_device"), "")
    devices = raw_config.get("devices")
    if active_device and isinstance(devices, dict):
        active_device_config = devices.get(active_device)
        if isinstance(active_device_config, dict):
            bluetooth_device = _optional_str(
                active_device_config.get("bluetooth_device"),
                "",
            )
            if bluetooth_device:
                return bluetooth_device

    return DEFAULT_BLUETOOTH_DEVICE


def run_discover(timeout_seconds: float, bluetooth_device: str) -> int:
    """Escaneja SEM6000 visibles sense arrencar l'agent MQTT."""
    try:
        import usa_sem6000 as sem_module
    except BaseException as exc:
        print(f"No s'ha pogut importar usa_sem6000: {exc}")
        return 1

    try:
        devices = sem_module.sem6000.SEM6000.discover(
            timeout=timeout_seconds,
            bluetooth_device=bluetooth_device,
        )
    except Exception as exc:
        print(f"No s'ha pogut fer l'escaneig BLE: {exc}")
        return 1

    if not devices:
        print("No s'ha trobat cap SEM6000.")
        return 0

    print("Dispositius SEM6000 trobats:")
    for device in devices:
        address = getattr(device, "addr", None) or getattr(device, "address", None)
        name = getattr(device, "name", None) or getattr(device, "localName", None)
        rssi = getattr(device, "rssi", None)
        parts = [str(address or device)]
        if name:
            parts.append(f"name={name}")
        if rssi is not None:
            parts.append(f"rssi={rssi}")
        print("- " + " ".join(parts))
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.discover:
        bluetooth_device = args.bluetooth_device or DEFAULT_BLUETOOTH_DEVICE
        if args.config and args.bluetooth_device is None:
            bluetooth_device = bluetooth_device_hint_from_toml(Path(args.config))
        return run_discover(args.discover_timeout, bluetooth_device)

    config = AppConfig.from_sources(args.config)
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.check_config:
        print_config_summary(config)
        return 0

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
