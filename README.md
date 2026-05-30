# SEM6000 ThingsBoard MQTT Bridge

Bridge en Python per integrar un endoll/mesurador Voltcraft SEM6000 amb ThingsBoard mitjancant MQTT en mode gateway.

El programa corre normalment en una Raspberry Pi, es connecta al SEM6000 per Bluetooth Low Energy, publica telemetria a ThingsBoard i accepta ordres RPC des del dashboard.

## Que fa

- Publica telemetria periodica del SEM6000 a ThingsBoard:
  - potencia instantania (`power_w`)
  - estat ON/OFF (`plug_on`)
  - tensio, corrent, frequencia i energia acumulada quan estan disponibles
- Permet controlar l'endoll des de ThingsBoard amb RPC:
  - encendre/apagar
  - llegir mesures
  - sincronitzar hora
  - configurar night mode, limit de potencia, preus i franja reduida
  - configurar timer, random mode i schedulers
  - consultar historics de consum
- Funciona com a servei `systemd`, amb arrencada automatica i reinici si falla.
- Permet tenir diversos endolls definits en un TOML i escollir quin es l'actiu.

Important: el token MQTT es el del dispositiu gateway de ThingsBoard, per exemple `Rasp`. Les dades del SEM6000 es publiquen en un dispositiu fill, per exemple `sem6000-b30000003043`.

## Elements necessaris

Hardware:

- Raspberry Pi o Linux amb Bluetooth Low Energy.
- Endoll Voltcraft SEM6000.
- PIN del SEM6000, normalment `0000`.
- Connexio a internet.

ThingsBoard:

- Instancia ThingsBoard Cloud o Server.
- Un dispositiu gateway, per exemple `Rasp`.
- Access token del gateway.
- Dashboard amb alias apuntant al dispositiu fill del SEM6000.

Software a la Raspberry:

- Python 3.11 o superior.
- `git`.
- `python3-venv` i `pip`.
- Bluetooth/BlueZ.
- Dependencies per compilar `bluepy`.

En Debian/Raspberry Pi OS:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip bluetooth bluez build-essential python3-dev libglib2.0-dev
```

## Instal.lacio

1. Clona aquest repo a la Raspberry:

```bash
cd /home/pau
git clone <URL_DEL_TEU_REPO> Codis
cd /home/pau/Codis
```

2. Executa l'instal.lador:

```bash
bash codis/deploy/install_sem6000_bridge.sh
```

L'script fa aquestes tasques:

- crea o actualitza `.venv`;
- descarrega la llibreria `python3-voltcraft-sem6000` si no existeix;
- instal.la `paho-mqtt` i `bluepy`;
- crea `/etc/sem6000-bridge/config.toml` si encara no existeix;
- crea i habilita el servei `systemd` `sem6000-bridge`.

3. Edita la configuracio real:

```bash
sudoedit /etc/sem6000-bridge/config.toml
```

Config minima:

```toml
active_device = "endoll_taula"

[thingsboard]
host = "mqtt.eu.thingsboard.cloud"
gateway_access_token = "POSA_AQUI_EL_TOKEN_DEL_GATEWAY_RASP"
client_id = "sem6000-rpi2b"
tls_mode = "fallback"

[runtime]
telemetry_interval_on_seconds = 1
off_heartbeat_seconds = 30
enable_extended_measurements = false
admin_rpc_enabled = false

[devices.endoll_taula]
address = "b3:00:00:00:30:43"
pin = "0000"
child_device_name = "sem6000-b30000003043"
child_device_type = "Voltcraft SEM6000"
```

4. Valida la configuracio sense connectar BLE ni MQTT:

```bash
/home/pau/Codis/.venv/bin/python /home/pau/Codis/codis/usa_sem6000_thingsboard_mqtt.py \
  --config /etc/sem6000-bridge/config.toml \
  --check-config
```

5. Arrenca el servei:

```bash
sudo systemctl start sem6000-bridge
sudo systemctl status sem6000-bridge --no-pager -l
```

6. Mira els logs:

```bash
journalctl -u sem6000-bridge -f
```

Si tot va be, hauries de veure missatges com:

```text
MQTT connectat. Mode TLS actiu: True
MQTT connectat i gateway inicialitzat.
```

## Tutorial d'inici a ThingsBoard

1. Crea o obre el dispositiu gateway, per exemple `Rasp`.
2. Copia el seu access token i posa'l a `gateway_access_token`.
3. Arrenca el servei `sem6000-bridge`.
4. ThingsBoard hauria de crear o actualitzar el dispositiu fill indicat a `child_device_name`.
5. Al dashboard, crea un alias `sem6000_device` que apunti al dispositiu fill.
6. Afegeix widgets de tipus Latest values o Time series amb aquestes claus:

```text
power_w
plug_on
voltage_v
current_a
frequency_hz
energy_total_kwh
```

7. Per controlar l'endoll, afegeix widgets RPC sobre el dispositiu fill:

```text
powerOn
powerOff
setPower
getMeasurement
syncTime
getSettings
getTimer
getSchedulers
getConsumption23h
```

La guia completa de widgets i RPCs esta a [codis/docs/guia_thingsboard_sem6000.md](codis/docs/guia_thingsboard_sem6000.md).

## Com canviar d'endoll

Pots definir diversos SEM6000 al mateix fitxer i canviar `active_device`:

```toml
active_device = "endoll_cuina"

[devices.endoll_taula]
address = "b3:00:00:00:30:43"
pin = "0000"
child_device_name = "sem6000-taula"

[devices.endoll_cuina]
address = "aa:bb:cc:dd:ee:ff"
pin = "0000"
child_device_name = "sem6000-cuina"
```

Despres reinicia el servei:

```bash
sudo systemctl restart sem6000-bridge
```

## Descobrir SEM6000 visibles

```bash
/home/pau/Codis/.venv/bin/python /home/pau/Codis/codis/usa_sem6000_thingsboard_mqtt.py --discover
```

Amb un adaptador Bluetooth diferent:

```bash
/home/pau/Codis/.venv/bin/python /home/pau/Codis/codis/usa_sem6000_thingsboard_mqtt.py \
  --discover \
  --bluetooth-device hci1
```

## Ordres utils

```bash
sudo systemctl start sem6000-bridge
sudo systemctl stop sem6000-bridge
sudo systemctl restart sem6000-bridge
sudo systemctl status sem6000-bridge --no-pager -l
journalctl -u sem6000-bridge -f
```

## Problemes habituals

No s'actualitza el dashboard:

- Comprova que el dashboard apunti al dispositiu fill (`child_device_name`), no al gateway `Rasp`.
- Revisa `journalctl -u sem6000-bridge -n 80 --no-pager`.
- Executa `--check-config` i mira quin `tb_child_device_name` surt.

Error MQTT:

- El token ha de ser el del dispositiu gateway.
- Revisa `host`, `tls_mode`, ports i internet de la Raspberry.

Error BLE:

- Comprova que la MAC del SEM6000 sigui correcta.
- Prova `--discover`.
- Assegura't que el servei corre amb permisos Bluetooth.

Les RPC administratives no funcionen:

- Estan desactivades per defecte. Activa-les nomes si cal:

```toml
[runtime]
admin_rpc_enabled = true
```

## Estructura del repo

```text
codis/usa_sem6000_thingsboard_mqtt.py   Bridge principal MQTT/BLE
codis/config/sem6000-bridge.example.toml Config d'exemple
codis/deploy/install_sem6000_bridge.sh  Instal.lador Raspberry/systemd
codis/deploy/sem6000-bridge.service     Exemple d'unitat systemd
codis/docs/guia_thingsboard_sem6000.md  Guia de dashboard i RPCs
codis/tests/                           Tests unitaris
```

## Seguretat

- No publiquis mai `/etc/sem6000-bridge/config.toml` amb un token real.
- L'exemple del repo ha de conservar `gateway_access_token = "CHANGE_ME"`.
- Si un token s'ha publicat accidentalment, genera'n un de nou a ThingsBoard.
