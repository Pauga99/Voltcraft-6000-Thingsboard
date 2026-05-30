# Desplegament del bridge SEM6000 a Raspberry

## Objectiu

Executar `usa_sem6000_thingsboard_mqtt.py` com a servei `systemd`, sense obrir una sessio SSH per activar el `.venv` i executar el programa a ma.

## 1. Instal.lacio automatitzada

Des de la Raspberry:

```bash
cd /opt/sem6000-bridge
bash codis/deploy/install_sem6000_bridge.sh
```

El script:

- crea o actualitza `.venv`,
- instal.la `paho-mqtt` i les dependencies BLE de la llibreria SEM6000,
- crea `/etc/sem6000-bridge/config.toml` si encara no existeix,
- crea `/etc/systemd/system/sem6000-bridge.service`,
- habilita el servei per arrencar amb la Raspberry.

Si el fitxer de configuracio es nou, edita'l abans d'arrencar:

```bash
sudo nano /etc/sem6000-bridge/config.toml
```

Despres:

```bash
sudo systemctl start sem6000-bridge
```

## 2. Validacio de configuracio

Abans d'arrencar el servei:

```bash
/opt/sem6000-bridge/.venv/bin/python /opt/sem6000-bridge/codis/usa_sem6000_thingsboard_mqtt.py \
  --config /etc/sem6000-bridge/config.toml \
  --check-config
```

Aquesta ordre no connecta ni a BLE ni a MQTT. Nomes valida el TOML i mostra un resum amb el token emmascarat.

## 3. Canviar d'endoll

Defineix tants endolls com vulguis a `/etc/sem6000-bridge/config.toml`:

```toml
active_device = "endoll_taula"

[devices.endoll_taula]
address = "b3:00:00:00:30:43"
pin = "0000"
child_device_name = "sem6000-taula"

[devices.endoll_cuina]
address = "aa:bb:cc:dd:ee:ff"
pin = "0000"
child_device_name = "sem6000-cuina"
```

Per usar l'altre endoll, canvia `active_device` i reinicia:

```bash
sudo systemctl restart sem6000-bridge
```

## 4. Descobrir SEM6000 visibles

```bash
/opt/sem6000-bridge/.venv/bin/python /opt/sem6000-bridge/codis/usa_sem6000_thingsboard_mqtt.py --discover
```

Si uses un adaptador BLE diferent:

```bash
/opt/sem6000-bridge/.venv/bin/python /opt/sem6000-bridge/codis/usa_sem6000_thingsboard_mqtt.py \
  --discover \
  --bluetooth-device hci1
```

## 5. Operacio diaria

```bash
sudo systemctl status sem6000-bridge
journalctl -u sem6000-bridge -f
sudo systemctl restart sem6000-bridge
sudo systemctl stop sem6000-bridge
```

Les RPC administratives (`adminChangePin`, `adminResetPin`, `adminFactoryReset`) estan desactivades per defecte. Per activar-les:

```toml
[runtime]
admin_rpc_enabled = true
```
