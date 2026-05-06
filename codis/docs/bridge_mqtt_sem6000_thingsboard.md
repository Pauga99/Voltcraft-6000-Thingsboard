# Auditoria del bridge MQTT SEM6000 -> ThingsBoard

Data de l'actualitzacio: 2026-04-13

Aquest document resumeix l'estat real del bridge MQTT cap a ThingsBoard i s'usa com a referencia de quines funcionalitats del SEM6000 ja estan exposades, quines continuen pendents i quina ha de ser la prioritat del seguent bloc.

## 1. Estat actual del bridge

Fitxer principal auditat: `codis/usa_sem6000_thingsboard_mqtt.py`

### 1.1 Capacitats base del bridge

- Connexio MQTT en mode gateway amb ThingsBoard.
- Registre i desregistre del dispositiu fill.
- Publicacio de telemetria periodica del SEM6000.
- Publicacio d'atributs del dispositiu fill i diagnostics del gateway.
- Cua RPC amb coalescing per a ordres de potencia.
- Reconnexio BLE amb un reintent en cas d'error transitori.

### 1.2 RPCs suportats actualment

#### Control de potencia

- `setPower`
- `setSwitch`
- `setRelay`
- `power`
- `powerOn`
- `powerOff`
- `on`
- `off`
- `getPowerState`
- `getSwitchState`

#### Mesura i rellotge

- `getMeasurement`
- `measure`
- `syncTime`
- `setTime`

#### Configuracio

- `getSettings`
- `setNightMode`
- `setPowerLimit`
- `setPrices`
- `setReducedPeriod`

#### Identitat

- `getDeviceName`
- `setDeviceName`
- `getDeviceSerial`

#### Timer

- `getTimer`
- `setTimer`
- `resetTimer`

#### Random mode

- `getRandomMode`
- `setRandomMode`
- `resetRandomMode`

#### Placeholders pendents

- `getScheduler`
- `addScheduler`
- `editScheduler`
- `removeScheduler`
- `getConsumption23h`
- `getConsumption30d`
- `getConsumption12m`

### 1.3 Dades publicades avui

Telemetria periodica:

- `power_w`
- `plug_on`
- `voltage_v`
- `current_a`
- `frequency_hz`
- `energy_total_kwh`

Atributs estatics del dispositiu fill:

- `sem6000_address`
- `bridge`
- `gateway_client_id`

Atributs de configuracio i identitat:

- `night_mode`
- `power_limit_w`
- `price_normal_cent`
- `price_reduced_cent`
- `reduced_period_enabled`
- `reduced_period_start`
- `reduced_period_end`
- `device_name`

Atributs de timer:

- `timer_active`
- `timer_action`
- `timer_target_isodatetime`
- `timer_original_length_seconds`

Atributs de random mode:

- `random_mode_enabled`
- `random_mode_weekdays`
- `random_mode_start`
- `random_mode_end`

Diagnostics del gateway:

- `mqtt_connected`
- `ble_connected`
- `rpc_queue_depth`
- `last_ble_op_ms`
- `last_rpc_total_ms`

### 1.4 Estat de validacio

- Suite automatica actual: `47 tests OK`
- Fitxer de proves principal: `codis/tests/test_usa_sem6000_thingsboard_mqtt.py`

Cobertura funcional actual:

- normalitzacio de payloads i valors
- publicacio MQTT de telemetria, atributs i respostes RPC
- cua RPC i coalescing de potencia
- handlers de potencia, mesura, configuracio i identitat
- handlers de timer i random mode
- validacio d'errors `invalid_params`

### 1.5 Limitacions actuals detectades

- `ScheduleHandler` continua retornant `not_implemented`.
- `ConsumptionHandler` continua retornant `not_implemented`.
- No hi ha encara handlers per a operacions administratives sensibles com PIN o factory reset.
- `getDeviceSerial` es retorna per RPC, pero no es persisteix com a atribut.

## 2. Funcionalitats disponibles a la llibreria base del SEM6000

Font: `github2/python3-voltcraft-sem6000/sem6000/sem6000.py`

### 2.1 Identitat i seguretat

- `request_device_name`
- `change_device_name`
- `request_device_serial`
- `authorize`
- `change_pin`
- `reset_pin`

### 2.2 Configuracio del dispositiu

- `nightmode_on`
- `nightmode_off`
- `change_date_and_time`
- `request_settings`
- `change_power_limit`
- `change_prices`
- `change_reduced_period`

### 2.3 Control i mesura

- `request_measurement`
- `power_on`
- `power_off`

### 2.4 Timer i automatitzacio

- `request_timer_status`
- `activate_timer`
- `activate_timer_at`
- `reset_timer`
- `request_scheduler`
- `add_onetime_scheduler`
- `edit_onetime_scheduler`
- `add_repeated_scheduler`
- `edit_repeated_scheduler`
- `remove_scheduler`
- `request_random_mode_status`
- `change_random_mode`
- `reset_random_mode`

### 2.5 Historics i manteniment

- `request_consumption_of_last_23_hours`
- `request_consumption_of_last_30_days`
- `request_consumption_of_last_12_months`
- `reset_consumption`

## 3. Bretxa actual entre la llibreria i el bridge

### 3.1 Ja cobert al bridge

- Potencia on/off i lectura d'estat.
- Lectura puntual de mesures instantanies.
- Sincronitzacio de temps.
- Settings basics del dispositiu.
- Identitat del dispositiu.
- Timer.
- Random mode.
- Telemetria periodica i diagnostics.

### 3.2 Disponible a la llibreria pero encara no exposat al bridge

- Lectura, alta, edicio i eliminacio de schedulers.
- Consulta d'historics 23h, 30d i 12m.
- Reset de consum acumulat.
- Operacions administratives de PIN.
- Factory reset.

### 3.3 Conclusio

La llibreria base cobreix gairebe tot el dispositiu i el bridge ja integra les fases 1 i 2 de la planificacio. La feina pendent es concentra ara en `schedulers`, historics de consum i operacions administratives.

## 4. Mapa RPC actual del bridge

L'objectiu del contracte es mantenir noms clars, respostes consistents i parametres senzills per a widgets RPC de ThingsBoard.

### 4.1 RPCs de control i lectura basica

| RPC | Params | Resposta |
| --- | --- | --- |
| `setPower` | `true/false` | `{ "plug_on": bool }` |
| `getPowerState` | cap | `{ "plug_on": bool }` |
| `getMeasurement` | cap | mesures instantanies |
| `syncTime` | cap | `{ "device_time": iso_datetime }` |

### 4.2 RPCs de configuracio

| RPC | Params | Resposta |
| --- | --- | --- |
| `getSettings` | cap | objecte settings normalitzat |
| `setNightMode` | `{ "enabled": bool }` | `{ "night_mode": bool }` |
| `setPowerLimit` | `{ "power_limit_w": int }` | `{ "power_limit_w": int }` |
| `setPrices` | `{ "normal_price_cent": int, "reduced_price_cent": int }` | objecte preus |
| `setReducedPeriod` | `{ "enabled": bool, "start": "HH:MM", "end": "HH:MM" }` | objecte reduced period |
| `getDeviceName` | cap | `{ "device_name": str }` |
| `setDeviceName` | `{ "device_name": str }` | `{ "device_name": str }` |
| `getDeviceSerial` | cap | `{ "device_serial": str }` |

### 4.3 RPCs de timer

| RPC | Params | Resposta |
| --- | --- | --- |
| `getTimer` | cap | `{ "timer_active": bool, "action": "on/off", "target_isodatetime": iso, "original_timer_length_seconds": int }` |
| `setTimer` | `{ "action": "on/off", "target_isodatetime": "YYYY-MM-DDTHH:MM[:SS]" }` | estat actual del timer normalitzat |
| `resetTimer` | cap | estat actual del timer normalitzat |

### 4.4 RPCs de random mode

| RPC | Params | Resposta |
| --- | --- | --- |
| `getRandomMode` | cap | `{ "enabled": bool, "weekdays": "Mon,Wed,Fri", "start": "HH:MM", "end": "HH:MM" }` |
| `setRandomMode` | `{ "weekdays": "Mon,Wed,Fri", "start": "HH:MM", "end": "HH:MM" }` | estat actual de random mode normalitzat |
| `resetRandomMode` | cap | estat actual de random mode normalitzat |

### 4.5 RPCs pendents

| RPC | Estat |
| --- | --- |
| `getSchedulers` i variants detallades | pendent |
| `getConsumption23h` | pendent |
| `getConsumption30d` | pendent |
| `getConsumption12m` | pendent |
| `resetConsumption` | pendent |
| `adminChangePin` | pendent |
| `adminResetPin` | pendent |
| `adminFactoryReset` | pendent |

## 5. Politica de publicacio de dades

### 5.1 Telemetria periodica

S'hi queden nomes les dades amb valor temporal clar per a dashboards:

- `power_w`
- `plug_on`
- `voltage_v`
- `current_a`
- `frequency_hz`
- `energy_total_kwh`

### 5.2 Atributs del dispositiu

S'hi publiquen dades relativament estables o d'estat consultable:

- configuracio basica del dispositiu
- nom visible del dispositiu
- estat actual del timer
- estat actual de random mode
- metadades del bridge i del SEM6000

### 5.3 Respostes RPC

S'hi resolen operacions sota demanda i respostes que no tenen sentit com a telemetria periodica:

- settings complets
- serial del dispositiu
- estat complet del timer
- estat complet de random mode
- futures llistes de schedulers
- futurs historics de consum
- futures operacions administratives

## 6. Prioritats d'implementacio

### Prioritat 1: configuracio basica i identitat

Estat: completada

- `getSettings`
- `setNightMode`
- `setPowerLimit`
- `setPrices`
- `setReducedPeriod`
- `getDeviceName`
- `setDeviceName`
- `getDeviceSerial`

### Prioritat 2: timer i random mode

Estat: completada

- `getTimer`
- `setTimer`
- `resetTimer`
- `getRandomMode`
- `setRandomMode`
- `resetRandomMode`

### Prioritat 3: schedulers

Estat: seguent bloc recomanat

- `getSchedulers`
- `addOnetimeScheduler`
- `editOnetimeScheduler`
- `addRepeatedScheduler`
- `editRepeatedScheduler`
- `removeScheduler`

Motiu: es la seguent funcionalitat gran disponible a la llibreria i la que te mes impacte sobre automatitzacio des de ThingsBoard.

### Prioritat 4: historics i manteniment

Estat: pendent

- `getConsumption23h`
- `getConsumption30d`
- `getConsumption12m`
- `resetConsumption`

### Prioritat 5: operacions administratives sensibles

Estat: pendent

- `adminChangePin`
- `adminResetPin`
- `adminFactoryReset`

## 7. Sortida esperada del seguent bloc

Per donar per tancada la fase seguent, haurien de quedar resolts aquests punts:

- contracte RPC definitiu per a schedulers, amb noms coherents amb ThingsBoard
- lectura de schedulers existents i alta/edicio/esborrat
- validacio de weekday masks, dates i hores
- proves unitaires del nou handler
- actualitzacio de la documentacio per reflectir el nou estat real
