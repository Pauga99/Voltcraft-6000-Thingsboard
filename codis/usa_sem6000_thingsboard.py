from __future__ import annotations

import json
import os
import time
from urllib import error, parse, request

from usa_sem6000 import DEVICE_ADDRESS, connect_device, read_power_in_watt


# Legacy: aquest script usa HTTP i long polling RPC.
# Es manté nomes per referencia i no es recomana per produccio ni per latencia curta.
# El runtime principal per Raspberry + ThingsBoard ha de ser usa_sem6000_thingsboard_mqtt.py.

# Permet canviar l'adreca del dispositiu sense tocar el codi.
SEM6000_DEVICE_ADDRESS = os.getenv("SEM6000_DEVICE_ADDRESS", DEVICE_ADDRESS)
# URL base del servidor de ThingsBoard.
# Canvia aquest valor pel domini real de la teva plataforma.
THINGSBOARD_URL = os.getenv("THINGSBOARD_URL", "https://eu.thingsboard.cloud")
# Token del dispositiu creat a ThingsBoard.
# S'ha deixat fix al codi per no dependre de variables d'entorn.
THINGSBOARD_ACCESS_TOKEN = "fnlfkoy74vrpsnfe28w4"
# Nom de la metrica que apareixera al dashboard.
THINGSBOARD_METRIC_KEY = os.getenv("THINGSBOARD_METRIC_KEY", "power_w")
# Nom de la metrica booleana per reflectir si l'endoll esta encas o apagat.
THINGSBOARD_POWER_STATE_KEY = os.getenv("THINGSBOARD_POWER_STATE_KEY", "plug_on")
# Interval entre enviaments, en segons.
SEND_INTERVAL_SECONDS = float(os.getenv("THINGSBOARD_SEND_INTERVAL", "1"))
# Temps maxim del long polling de RPC.
RPC_POLL_TIMEOUT_MS = int(os.getenv("THINGSBOARD_RPC_TIMEOUT_MS", "1000"))


def validate_configuration():
    """Comprova que hi hagi la configuracio minima per poder enviar dades."""
    # Sense token, ThingsBoard no pot identificar a quin dispositiu pertanyen les dades.
    if not THINGSBOARD_ACCESS_TOKEN:
        raise SystemExit(
            "Falta el token de ThingsBoard.\n"
            "Edita la constant THINGSBOARD_ACCESS_TOKEN del fitxer."
        )


def build_device_api_endpoint(base_url, access_token, suffix):
    """Construeix un endpoint de l'API de dispositiu de ThingsBoard."""
    # Elimina la barra final per evitar URL duplicades com //api/v1.
    normalized_url = base_url.rstrip("/")
    clean_suffix = suffix.lstrip("/")
    return f"{normalized_url}/api/v1/{access_token}/{clean_suffix}"


def build_telemetry_endpoint(base_url, access_token):
    """Construeix l'endpoint HTTP per publicar telemetria del dispositiu."""
    # Endpoint on s'envien lectures temporals com la potencia instantania.
    return build_device_api_endpoint(base_url, access_token, "telemetry")


def build_attributes_endpoint(base_url, access_token):
    """Construeix l'endpoint per publicar atributs del dispositiu."""
    # Endpoint per enviar estat persistent, per exemple si l'endoll esta encas o apagat.
    return build_device_api_endpoint(base_url, access_token, "attributes")


def build_rpc_poll_endpoint(base_url, access_token, timeout_ms):
    """Construeix l'endpoint de long polling per rebre RPC del dashboard."""
    # El timeout es passa a la URL perque el servidor mantingui la connexio oberta
    # fins que arribi una ordre o s'esgoti el temps d'espera.
    query = parse.urlencode({"timeout": timeout_ms})
    rpc_endpoint = build_device_api_endpoint(base_url, access_token, "rpc")
    return f"{rpc_endpoint}?{query}"


def build_rpc_response_endpoint(base_url, access_token, request_id):
    """Construeix l'endpoint per respondre a una peticio RPC concreta."""
    # Cada ordre RPC te un identificador i la resposta s'ha d'enviar al seu endpoint propi.
    return build_device_api_endpoint(base_url, access_token, f"rpc/{request_id}")


def build_payload(power_in_watt=None, plug_is_on=None):
    """Prepara el JSON que ThingsBoard desara com a telemetria."""
    # S'envia timestamp en milisegons perque la serie temporal quedi ben datada.
    timestamp_ms = int(time.time() * 1000)
    values = {}

    # Afegeix nomes les metriques que realment tenim disponibles en aquest moment.
    if power_in_watt is not None:
        values[THINGSBOARD_METRIC_KEY] = round(power_in_watt, 3)
    if plug_is_on is not None:
        values[THINGSBOARD_POWER_STATE_KEY] = plug_is_on
    if not values:
        raise ValueError("Cal enviar almenys una metrica a ThingsBoard.")

    return {
        "ts": timestamp_ms,
        "values": values,
    }


def post_json(endpoint, payload, timeout=10):
    """Envia un JSON a un endpoint de ThingsBoard per HTTP."""
    # Serialitza el diccionari Python a JSON per enviar-lo al servidor.
    body = json.dumps(payload).encode("utf-8")
    http_request = request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(http_request, timeout=timeout) as response:
            # ThingsBoard sol respondre 200 OK quan la peticio s'ha processat.
            return response.status
    except error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"ThingsBoard ha respost amb HTTP {exc.code}: {response_body}"
        ) from exc
    except error.URLError as exc:
        raise RuntimeError(
            f"No s'ha pogut connectar amb ThingsBoard: {exc.reason}"
        ) from exc


def send_telemetry(endpoint, payload, timeout=10):
    """Envia un paquet de telemetria a ThingsBoard per HTTP."""
    # Aquesta funcio encapsula l'enviament de mesures temporals.
    return post_json(endpoint, payload, timeout=timeout)


def send_attributes(endpoint, payload, timeout=10):
    """Publica atributs de client perque el dashboard conegui l'estat."""
    # Els atributs serveixen per reflectir l'estat actual fora de la serie temporal.
    return post_json(endpoint, payload, timeout=timeout)


def send_rpc_response(endpoint, payload, timeout=10):
    """Respon al widget RPC amb el resultat de l'ordre executada."""
    # ThingsBoard espera una resposta per saber si l'ordre s'ha completat correctament.
    return post_json(endpoint, payload, timeout=timeout)


def poll_rpc_request(endpoint, timeout_ms):
    """Espera una ordre RPC del dashboard i la retorna si n'hi ha."""
    # Es fa una peticio GET que pot quedar oberta uns segons esperant una ordre.
    http_request = request.Request(endpoint, method="GET")
    client_timeout = max(5, (timeout_ms / 1000) + 5)

    try:
        with request.urlopen(http_request, timeout=client_timeout) as response:
            body = response.read().decode("utf-8", errors="replace").strip()
            if not body:
                return None

            rpc_request = json.loads(body)
            if not isinstance(rpc_request, dict):
                return None

            # En alguns entorns el request id pot venir al body; en altres, a capcaleres.
            if "id" not in rpc_request:
                request_id = (
                    response.headers.get("X-Request-Id")
                    or response.headers.get("Request-Id")
                )
                if request_id:
                    rpc_request["id"] = request_id

            if "method" not in rpc_request:
                return None
            # Si hi ha un metode, ja tenim una ordre valida per processar.
            return rpc_request
    except error.HTTPError as exc:
        # En el long polling d'RPC, un 408/504 indica normalment que no hi havia
        # cap ordre pendent dins del temps d'espera configurat.
        if exc.code in {408, 504}:
            return None
        response_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"ThingsBoard ha respost amb HTTP {exc.code}: {response_body}"
        ) from exc
    except error.URLError as exc:
        raise RuntimeError(
            f"No s'ha pogut connectar amb ThingsBoard: {exc.reason}"
        ) from exc


def parse_boolean_value(value):
    """Converteix diversos formats habituals a boolea."""
    # Accepta diferents formats per fer el widget mes flexible.
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "on", "encen", "ences", "poweron"}:
            return True
        if normalized in {"0", "false", "off", "apagat", "apaga", "poweroff"}:
            return False
        return None
    if isinstance(value, dict):
        for key in ("enabled", "value", "power", "state", "on"):
            if key in value:
                return parse_boolean_value(value[key])
    return None


def execute_power_rpc(device, rpc_request, current_power_state):
    """Executa una ordre RPC de ThingsBoard i retorna l'estat actualitzat."""
    # El nom del metode arriba des del widget del dashboard.
    method_name = str(rpc_request.get("method", "")).strip()
    method_key = method_name.lower()
    params = rpc_request.get("params")

    if method_key == "poweron":
        target_power_state = True
    elif method_key == "poweroff":
        target_power_state = False
    elif method_key in {"setpower", "setswitch", "setrelay"}:
        target_power_state = parse_boolean_value(params)
        if target_power_state is None:
            raise ValueError(
                "Els metodes setPower/setSwitch/setRelay necessiten un parametre boolea."
            )
    elif method_key in {"getpowerstate", "getswitchstate"}:
        return current_power_state, {
            "success": True,
            THINGSBOARD_POWER_STATE_KEY: current_power_state,
        }
    else:
        raise ValueError(
            f"Metode RPC no suportat: {method_name}. "
            "Fes servir setPower, setSwitch, powerOn o powerOff."
        )

    # Traduccio directa de l'ordre remota a l'accio Bluetooth sobre l'endoll.
    if target_power_state:
        device.power_on()
    else:
        device.power_off()

    return target_power_state, {
        "success": True,
        THINGSBOARD_POWER_STATE_KEY: target_power_state,
    }


def main():
    """Llegeix la potencia del SEM6000 i la publica, amb control RPC."""
    validate_configuration()
    # Es preparen tots els endpoints una sola vegada abans d'entrar al bucle principal.
    telemetry_endpoint = build_telemetry_endpoint(
        THINGSBOARD_URL, THINGSBOARD_ACCESS_TOKEN
    )
    attributes_endpoint = build_attributes_endpoint(
        THINGSBOARD_URL, THINGSBOARD_ACCESS_TOKEN
    )

    print(f"Connectant a {SEM6000_DEVICE_ADDRESS}...")
    print(f"Enviant dades a {telemetry_endpoint}")
    print("Esperant ordres RPC del dashboard (setPower/setSwitch/powerOn/powerOff).")

    device = connect_device(SEM6000_DEVICE_ADDRESS)
    # `plug_is_on` es l'ultim estat conegut de l'endoll; comenca desconegut.
    plug_is_on = None
    # Controla quan toca enviar la seguent mostra de telemetria.
    next_send_at = 0.0

    try:
        print("Connexio establerta. Premeu Ctrl+C per aturar l'enviament.")

        while True:
            now = time.monotonic()
            if now >= next_send_at:
                # Si sabem que l'endoll esta apagat, la potencia instantania ha de ser zero.
                if plug_is_on is False:
                    power_in_watt = 0.0
                else:
                    try:
                        # Llegeix la potencia real del dispositiu per enviar-la al dashboard.
                        power_in_watt = read_power_in_watt(device)
                    except Exception as exc:
                        print(f"No s'ha pogut llegir la potencia: {exc}")
                        power_in_watt = None

                if power_in_watt is not None or plug_is_on is not None:
                    # Es genera i envia el paquet amb les dades disponibles.
                    payload = build_payload(
                        power_in_watt=power_in_watt,
                        plug_is_on=plug_is_on,
                    )
                    send_telemetry(telemetry_endpoint, payload)

                    if power_in_watt is None:
                        print("Telemetria enviada sense potencia instantania.")
                    else:
                        print(f"Telemetria enviada: {power_in_watt:.3f} W")

                next_send_at = now + SEND_INTERVAL_SECONDS

            # El temps de l'espera RPC es limita per no retardar el següent enviament de telemetria.
            time_until_next_send = max(0.1, next_send_at - time.monotonic())
            rpc_timeout_ms = min(
                RPC_POLL_TIMEOUT_MS,
                max(100, int(time_until_next_send * 1000)),
            )
            rpc_endpoint = build_rpc_poll_endpoint(
                THINGSBOARD_URL,
                THINGSBOARD_ACCESS_TOKEN,
                rpc_timeout_ms,
            )

            rpc_request = poll_rpc_request(rpc_endpoint, rpc_timeout_ms)
            if not rpc_request:
                continue

            try:
                # Executa l'ordre rebuda i actualitza l'estat local.
                plug_is_on, rpc_response = execute_power_rpc(
                    device, rpc_request, plug_is_on
                )
                if plug_is_on is not None:
                    # Publica l'estat nou com a atribut perque el dashboard el pugui mostrar.
                    send_attributes(
                        attributes_endpoint,
                        {THINGSBOARD_POWER_STATE_KEY: plug_is_on},
                    )
                print(f"Ordre RPC executada. Estat actual: {plug_is_on}")
            except Exception as exc:
                rpc_response = {"success": False, "error": str(exc)}
                print(f"No s'ha pogut executar l'ordre RPC: {exc}")

            request_id = rpc_request.get("id")
            if request_id is not None:
                # Si ThingsBoard ha enviat un id, se li retorna la resposta associada a aquella ordre.
                rpc_response_endpoint = build_rpc_response_endpoint(
                    THINGSBOARD_URL,
                    THINGSBOARD_ACCESS_TOKEN,
                    request_id,
                )
                send_rpc_response(rpc_response_endpoint, rpc_response)
    except KeyboardInterrupt:
        print("\nEnviament aturat.")
    finally:
        # Tanca la connexio Bluetooth encara que el programa acabi per error o Ctrl+C.
        device.disconnect()


if __name__ == "__main__":
    # Punt d'entrada quan el fitxer s'executa directament.
    main()
