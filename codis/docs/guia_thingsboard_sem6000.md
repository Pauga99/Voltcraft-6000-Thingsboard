# Guia operativa de ThingsBoard per al bridge MQTT SEM6000

Data de l'actualitzacio: 2026-04-29

Aquest document resumeix, des del punt de vista de ThingsBoard, tot el que avui es pot fer amb `codis/usa_sem6000_thingsboard_mqtt.py` i quines configuracions exactes s'han de posar als widgets, dashboards o proves RPC.

## 1. Configuracio efectiva del bridge

Els valors seguents son els que fa servir el bridge si no s'han sobreescrit variables d'entorn:

| Camp | Valor per defecte |
| --- | --- |
| Host MQTT ThingsBoard | `mqtt.eu.thingsboard.cloud` |
| Port TLS | `8883` |
| Port plain | `1883` |
| Mode TLS | `fallback` |
| Access token del gateway | `PgcsA0leXeslOFsDO2Lk` |
| MQTT client id del gateway | `sem6000-rpi2b` |
| Device address del SEM6000 | `b3:00:00:00:30:43` |
| Nom del dispositiu fill | `sem6000-b30000003043` |
| Tipus del dispositiu fill | `Voltcraft SEM6000` |
| Interval de telemetria amb endoll actiu | `1` segon |
| Heartbeat amb endoll apagat | `30` segons |
| QoS de control | `1` |
| QoS de telemetria | `0` |

Variables que poden canviar aquests valors:

- `THINGSBOARD_MQTT_HOST`
- `THINGSBOARD_CLIENT_ID`
- `THINGSBOARD_CHILD_DEVICE_NAME`
- `THINGSBOARD_CHILD_DEVICE_TYPE`
- `THINGSBOARD_TLS_MODE`
- `THINGSBOARD_MQTT_PORT_TLS`
- `THINGSBOARD_MQTT_PORT_PLAIN`
- `THINGSBOARD_CONTROL_QOS`
- `THINGSBOARD_TELEMETRY_QOS`
- `TELEMETRY_INTERVAL_ON_SECONDS`
- `OFF_HEARTBEAT_SECONDS`
- `ENABLE_EXTENDED_MEASUREMENTS`

## 2. Que surt a ThingsBoard

El bridge treballa en mode gateway MQTT i crea dos nivells de dades:

### 2.1 Gateway

Es el dispositiu autenticat amb el token MQTT. Aqui hi surten diagnostics i metadades del bridge.

Atributs del gateway:

- `bridge`
- `child_device_name`
- `child_device_type`
- `sem6000_address`

Telemetria del gateway:

- `mqtt_connected`
- `ble_connected`
- `rpc_queue_depth`
- `last_ble_op_ms`
- `last_rpc_total_ms`

### 2.2 Dispositiu fill SEM6000

Es el dispositiu que s'ha de fer servir per a gairebe tots els widgets de control i visualitzacio del consum.

Nom per defecte:

- `sem6000-b30000003043`

Tipus per defecte:

- `Voltcraft SEM6000`

## 3. Que s'ha de fer servir a ThingsBoard

Regla practica:

- Per controlar l'endoll o consultar configuracio del SEM6000, fes els widgets sobre el dispositiu fill.
- Per veure salut del bridge, fes els widgets sobre el gateway.
- No intentis controlar el SEM6000 escrivint atributs des de ThingsBoard: el bridge ignora els updates entrants a `v1/gateway/attributes`.
- Per a ordres sota demanda, fes servir RPC. Per a visualitzacio d'estat, fes servir telemetria i client attributes.

### 3.1 Preparacio minima del dashboard

Abans de crear widgets, deixa resolts aquests punts:

1. Crea o obre un dashboard i entra en mode edicio.
2. Crea un alias `sem6000_device` de tipus `Single entity` apuntant al dispositiu fill `sem6000-b30000003043`, o al nom real definit a `THINGSBOARD_CHILD_DEVICE_NAME`.
3. Crea un alias `sem6000_gateway` de tipus `Single entity` apuntant al dispositiu gateway autenticat amb el token `PgcsA0leXeslOFsDO2Lk`.
4. Desa els aliases abans d'afegir widgets.

Com identificar el gateway correcte si no recordes el nom:

- Busca el dispositiu que tingui atributs com `bridge=raspberry-sem6000-gw`.
- Comprova que tambe hi surtin `child_device_name=sem6000-b30000003043` i `child_device_type=Voltcraft SEM6000`.

### 3.2 Regles de configuracio que et faran estalviar temps

- `Latest values`: fes-los servir per mostrar l'ultim valor de telemetria o de client attributes.
- `Time series`: fes-los servir nomes per claus de telemetria historica com `power_w` o `energy_total_kwh`.
- `Control widgets`: fes-los servir per enviar RPC al dispositiu fill.
- `Time series` no es el tipus correcte per a atributs com `device_name`, `timer_action` o `random_mode_weekdays`.
- Per a operacions amb resposta, configura els widgets RPC en mode de dues vies si la teva versio de ThingsBoard ho permet.
- Si un widget de control no et deixa construir un JSON de `params` com cal, es millor usar un `RPC Button` amb payload fix o un widget personalitzat.
- Els noms visuals de menus, bundles o pestanyes poden variar lleugerament segons versio CE, Cloud o PE. El que no canvia es l'alias objectiu, la clau de dada i el `method/params`.

## 4. Telemetria i atributs disponibles al dispositiu fill

### 4.1 Telemetria del dispositiu fill

| Clau | Tipus | Quan s'actualitza |
| --- | --- | --- |
| `power_w` | `float` | A cada lectura periodica. Si l'endoll es considera apagat, publica `0.0` sense llegir BLE. |
| `plug_on` | `bool` | A cada lectura periodica i tambe just despres de canvis de potencia. |
| `voltage_v` | `float` | Nomes quan l'endoll esta actiu, o sempre si `ENABLE_EXTENDED_MEASUREMENTS=true`. |
| `current_a` | `float` | Mateixa regla que `voltage_v`. |
| `frequency_hz` | `float` | Mateixa regla que `voltage_v`. |
| `energy_total_kwh` | `float` | Mateixa regla que `voltage_v`. |

### 4.2 Client attributes del dispositiu fill

Atributs estatics:

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

Nota important:

- `getDeviceSerial` retorna el serial per RPC, pero avui no el desa com a atribut.
- `plug_on` es publica com a atribut quan canvia l'estat i com a telemetria quan hi ha lectura o canvi immediat.
- `schedulers`, historics de consum i operacions administratives tampoc no es persisteixen com a atributs: es resolen nomes com a resposta RPC sota demanda.

## 5. Format RPC exacte que espera el bridge

El bridge processa RPCs de gateway amb aquesta estructura:

```json
{
  "device": "sem6000-b30000003043",
  "data": {
    "id": 7,
    "method": "setPower",
    "params": true
  }
}
```

Resposta correcta del bridge:

```json
{
  "device": "sem6000-b30000003043",
  "id": 7,
  "data": {
    "success": true,
    "data": {
      "plug_on": true
    }
  }
}
```

Resposta d'error:

```json
{
  "device": "sem6000-b30000003043",
  "id": 7,
  "data": {
    "success": false,
    "error": "El metode necessita un parametre boolea.",
    "code": "invalid_params"
  }
}
```

Per a la part de ThingsBoard, la configuracio practica es:

- Entitat objectiu: el dispositiu fill `sem6000-b30000003043`, o el nom que tinguis realment configurat a `THINGSBOARD_CHILD_DEVICE_NAME`.
- Mode recomanat: RPC amb resposta, per poder veure l'objecte retornat o els errors funcionals.
- `method`: exactament un dels noms de la taula de la seccio 6.
- `params`: exactament el JSON indicat a la taula de la seccio 6.

## 6. RPCs disponibles avui

### 6.1 Control de potencia

| Objectiu | Method | Params exactes | Resposta funcional |
| --- | --- | --- | --- |
| Posar ON/OFF | `setPower` | `true` o `false` | `{ "plug_on": bool }` |
| Alias de `setPower` | `setSwitch` | `true` o `false` | `{ "plug_on": bool }` |
| Alias de `setPower` | `setRelay` | `true` o `false` | `{ "plug_on": bool }` |
| Alias generic | `power` | `true` o `false` | `{ "plug_on": bool }` |
| Forcar ON | `powerOn` | `null` o `{}` | `{ "plug_on": true }` |
| Forcar OFF | `powerOff` | `null` o `{}` | `{ "plug_on": false }` |
| Alias curt ON | `on` | `null` o `{}` | `{ "plug_on": true }` |
| Alias curt OFF | `off` | `null` o `{}` | `{ "plug_on": false }` |
| Llegir estat | `getPowerState` | `null` o `{}` | `{ "plug_on": bool|null }` |
| Alias lectura estat | `getSwitchState` | `null` o `{}` | `{ "plug_on": bool|null }` |

`setPower`, `setSwitch`, `setRelay` i `power` admeten aquests formats de boolea:

- `true` / `false`
- `1` / `0`
- `"true"` / `"false"`
- `"on"` / `"off"`
- `"yes"` / `"no"`
- `"enabled"` / `"disabled"`
- `"encen"` / `"apagat"`
- `{ "enabled": true }`
- `{ "on": true }`
- `{ "state": "off" }`
- `{ "power": 1 }`
- `{ "value": false }`

Exemples de `params`:

```json
true
```

```json
{ "enabled": false }
```

Configuracio practica recomanada a ThingsBoard:

- Toggle d'endoll: `method=setPower`
- Boto ON: `method=powerOn`
- Boto OFF: `method=powerOff`
- Indicador d'estat: llegeix `plug_on` com a latest telemetry o client attribute

### 6.2 Mesura i rellotge

| Objectiu | Method | Params exactes | Resposta funcional |
| --- | --- | --- | --- |
| Mesura instantania | `getMeasurement` | `null` o `{}` | Claus de mesura disponibles |
| Alias mesura | `measure` | `null` o `{}` | Claus de mesura disponibles |
| Sincronitzar rellotge | `syncTime` | `null` o `{}` | `{ "device_time": "YYYY-MM-DDTHH:MM:SS" }` |
| Alias sync hora | `setTime` | `null` o `{}` | `{ "device_time": "YYYY-MM-DDTHH:MM:SS" }` |

Resposta tipica de `getMeasurement`:

```json
{
  "power_w": 1.234,
  "plug_on": true,
  "voltage_v": 230.2,
  "current_a": 0.142,
  "frequency_hz": 49.97,
  "energy_total_kwh": 12.345678
}
```

Nota:

- Si l'endoll esta apagat i `ENABLE_EXTENDED_MEASUREMENTS=false`, la resposta pot no incloure `voltage_v`, `current_a`, `frequency_hz` ni `energy_total_kwh`.
- `syncTime` i `setTime` no llegeixen un valor del `params`; agafen l'hora actual del sistema on corre el bridge.

### 6.3 Configuracio del dispositiu

| Objectiu | Method | Params exactes | Resposta funcional |
| --- | --- | --- | --- |
| Llegir settings | `getSettings` | `null` o `{}` | Objecte settings normalitzat |
| Night mode | `setNightMode` | `true`, `false` o `{ "enabled": bool }` | `{ "night_mode": bool }` |
| Limit de potencia | `setPowerLimit` | `2500` o `{ "power_limit_w": 2500 }` | `{ "power_limit_w": 2500 }` |
| Preus | `setPrices` | `{ "normal_price_cent": 22, "reduced_price_cent": 7 }` | `{ "prices": { ... } }` |
| Franja reduida | `setReducedPeriod` | `{ "enabled": true, "start": "23:00", "end": "06:30" }` | `{ "reduced_period": { ... } }` |

Resposta de `getSettings`:

```json
{
  "night_mode": false,
  "power_limit_w": 3680,
  "prices": {
    "normal_price_cent": 31,
    "reduced_price_cent": 12
  },
  "reduced_period": {
    "enabled": true,
    "start": "23:00",
    "end": "06:30"
  }
}
```

Validacions exactes:

- `setPowerLimit`: `power_limit_w` ha de ser enter `> 0`.
- `setPrices`: `normal_price_cent` i `reduced_price_cent` han de ser enters `>= 0`.
- `setReducedPeriod`: sempre necessita `enabled`, `start` i `end`.
- `start` i `end` han d'anar en format `HH:MM` o `HH:MM:SS`. El bridge els normalitza a `HH:MM`.

Client attributes que s'actualitzen despres de cada operacio:

- `night_mode`
- `power_limit_w`
- `price_normal_cent`
- `price_reduced_cent`
- `reduced_period_enabled`
- `reduced_period_start`
- `reduced_period_end`

### 6.4 Identitat del dispositiu

| Objectiu | Method | Params exactes | Resposta funcional |
| --- | --- | --- | --- |
| Llegir nom visible | `getDeviceName` | `null` o `{}` | `{ "device_name": "..." }` |
| Canviar nom visible | `setDeviceName` | `"Desk Plug"` o `{ "device_name": "Desk Plug" }` | `{ "device_name": "Desk Plug" }` |
| Llegir serial | `getDeviceSerial` | `null` o `{}` | `{ "device_serial": "..." }` |

Validacions exactes:

- `device_name` no pot ser buit.
- `device_name` no pot superar `18` caracters.

Client attribute actualitzat:

- `device_name`

Limitacio:

- `device_serial` avui nomes es retorna per RPC.

### 6.5 Timer

| Objectiu | Method | Params exactes | Resposta funcional |
| --- | --- | --- | --- |
| Llegir timer | `getTimer` | `null` o `{}` | Objecte timer normalitzat |
| Crear o substituir timer | `setTimer` | `{ "action": "on", "target_isodatetime": "2026-04-13T18:30:00" }` | Objecte timer normalitzat |
| Reset timer | `resetTimer` | `null` o `{}` | Objecte timer normalitzat |

Resposta normalitzada:

```json
{
  "timer_active": true,
  "action": "on",
  "target_isodatetime": "2026-04-13T18:30:00",
  "original_timer_length_seconds": 300
}
```

Validacions exactes:

- `action` ha de ser `on` o `off`.
- Tambe admet `true`, `false`, `1` i `0`, pero el valor normalitzat sempre torna com `on` o `off`.
- `target_isodatetime` es obligatori i ha d'anar en format `YYYY-MM-DDTHH:MM[:SS]`.
- El bridge el normalitza sempre a segons, per exemple `2026-04-13T18:30` passa a `2026-04-13T18:30:00`.

Client attributes que s'actualitzen:

- `timer_active`
- `timer_action`
- `timer_target_isodatetime`
- `timer_original_length_seconds`

### 6.6 Random mode

| Objectiu | Method | Params exactes | Resposta funcional |
| --- | --- | --- | --- |
| Llegir random mode | `getRandomMode` | `null` o `{}` | Objecte random mode normalitzat |
| Configurar random mode | `setRandomMode` | `{ "weekdays": "Mon,Wed,Fri", "start": "18:00", "end": "23:00" }` | Objecte random mode normalitzat |
| Reset random mode | `resetRandomMode` | `null` o `{}` | Objecte random mode normalitzat |

Resposta normalitzada:

```json
{
  "enabled": true,
  "weekdays": "Mon,Wed,Fri",
  "start": "18:00",
  "end": "23:00"
}
```

Formats acceptats per `weekdays`:

- String CSV: `"Mon,Wed,Fri"`
- Llista JSON: `["Mon", "Wed", "Fri"]`
- Noms llargs: `"Monday,Wednesday,Friday"`
- Indexos: `"1,3,5"`

Mapa valid de dies:

- `0` o `Sun`
- `1` o `Mon`
- `2` o `Tue`
- `3` o `Wed`
- `4` o `Thu`
- `5` o `Fri`
- `6` o `Sat`

Validacions exactes:

- `weekdays`, `start` i `end` son obligatoris.
- `start` i `end` han d'anar en format `HH:MM` o `HH:MM:SS`.
- El bridge elimina duplicats i retorna sempre el format canonic tipus `Mon,Wed,Fri`.

Client attributes que s'actualitzen:

- `random_mode_enabled`
- `random_mode_weekdays`
- `random_mode_start`
- `random_mode_end`

### 6.7 Schedulers

| Objectiu | Method | Params exactes | Resposta funcional |
| --- | --- | --- | --- |
| Llegir tots els schedulers | `getSchedulers` | `null` o `{}` | `{ "scheduler_count": int, "schedulers": [...] }` |
| Alias de compatibilitat | `getScheduler` | `null` o `{}` | `{ "scheduler_count": int, "schedulers": [...] }` |
| Alta one-time | `addOnetimeScheduler` | `{ "enabled": true, "action": "off", "target_isodatetime": "2026-05-03T10:15:00" }` | llista actualitzada de schedulers |
| Edicio one-time | `editOnetimeScheduler` | `{ "slot_id": 1, "enabled": true, "action": "on", "target_isodatetime": "2026-05-03T10:15:00" }` | llista actualitzada de schedulers |
| Alta repeated | `addRepeatedScheduler` | `{ "enabled": true, "action": "off", "weekdays": "Mon,Fri", "time": "21:30" }` | llista actualitzada de schedulers |
| Edicio repeated | `editRepeatedScheduler` | `{ "slot_id": 3, "enabled": true, "action": "off", "weekdays": "Mon,Fri", "time": "21:30" }` | llista actualitzada de schedulers |
| Alta generica | `addScheduler` | objecte amb `type=onetime/repeated` | llista actualitzada de schedulers |
| Edicio generica | `editScheduler` | objecte amb `slot_id` i `type=onetime/repeated` | llista actualitzada de schedulers |
| Esborrar un slot | `removeScheduler` | `0` o `{ "slot_id": 0 }` | llista actualitzada de schedulers |

Resposta normalitzada tipica:

```json
{
  "scheduler_count": 2,
  "schedulers": [
    {
      "slot_id": 0,
      "type": "onetime",
      "enabled": true,
      "action": "on",
      "target_isodatetime": "2026-05-02T07:15:00"
    },
    {
      "slot_id": 2,
      "type": "repeated",
      "enabled": false,
      "action": "off",
      "weekdays": "Mon,Wed,Fri",
      "time": "18:45"
    }
  ]
}
```

Validacions exactes:

- `slot_id` ha de ser enter `>= 0`. El slot `0` es valid i correspon al primer slot de la llibreria base.
- En create/edit, el bridge necessita `enabled`. Tambe admet els aliases `active` i `is_active`.
- `action` es pot enviar com `on/off`, `true/false`, `1/0`. Tambe admet els aliases booleans `turn_on` i `is_action_turn_on`.
- `addScheduler` i `editScheduler` necessiten `type` o `scheduler_type`. Els valors recomanats son `onetime` i `repeated`.
- Per a schedulers `onetime`, `target_isodatetime` es obligatori i ha d'anar en format `YYYY-MM-DDTHH:MM[:SS]`.
- Per a schedulers `repeated`, `weekdays` i `time` son obligatoris. `time` tambe pot arribar com `isotime`.
- `weekdays` segueix exactament la mateixa validacio que a `setRandomMode`.
- Despres de qualsevol alta, edicio o esborrat, el bridge retorna la llista completa actualitzada.

Nota practica:

- Els schedulers no es publiquen com a atributs ni com a telemetria periodica. Si vols veure la llista a dashboard, et cal un widget que mostri la resposta RPC JSON o un widget personalitzat.

### 6.8 Historics de consum i reset

| Objectiu | Method | Params exactes | Resposta funcional |
| --- | --- | --- | --- |
| Historic de 23 hores | `getConsumption23h` | `null` o `{}` | objecte `{ "interval": "hour", "samples": [...] }` |
| Historic de 30 dies | `getConsumption30d` | `null` o `{}` | objecte `{ "interval": "day", "samples": [...] }` |
| Historic de 12 mesos | `getConsumption12m` | `null` o `{}` | objecte `{ "interval": "month", "samples": [...] }` |
| Reset del comptador guardat al dispositiu | `resetConsumption` | `null` o `{}` | `{ "consumption_reset": true }` |

Resposta tipica de `getConsumption23h`:

```json
{
  "interval": "hour",
  "unit": "Wh",
  "sample_count": 3,
  "samples": [
    {
      "hours_ago": 0,
      "timestamp_local": "2026-04-29T14:00:00",
      "isotime": "14:00",
      "consumption_wh": 50
    },
    {
      "hours_ago": 1,
      "timestamp_local": "2026-04-29T13:00:00",
      "isotime": "13:00",
      "consumption_wh": null
    }
  ]
}
```

Forma de les respostes:

- `getConsumption23h`: cada mostra inclou `hours_ago`, `timestamp_local`, `isotime` i `consumption_wh`.
- `getConsumption30d`: cada mostra inclou `days_ago`, `date` i `consumption_wh`.
- `getConsumption12m`: cada mostra inclou `months_ago`, `year`, `month`, `year_month` i `consumption_wh`.
- `consumption_wh` pot ser `null` si el dispositiu no te dada per aquell bucket temporal.

Nota practica:

- Aquests historics son respostes RPC, no noves series de telemetria de ThingsBoard. Si vols graficar-los sense fer un widget custom, continua sent mes comode explotar la telemetria historica que ThingsBoard ja desa.

### 6.9 Operacions administratives

| Objectiu | Method | Params exactes | Resposta funcional |
| --- | --- | --- | --- |
| Canviar PIN actiu | `adminChangePin` | `{ "new_pin": "1234" }` | `{ "pin_changed": true }` |
| Reset del PIN a `0000` | `adminResetPin` | `null` o `{}` | `{ "pin_reset": true, "active_pin": "0000" }` |
| Factory reset | `adminFactoryReset` | `null` o `{}` | `{ "factory_reset": true, "active_pin": "0000" }` |

Validacions exactes:

- `new_pin` ha de ser un PIN numeric de `4` digits.
- Despres de `adminResetPin` i `adminFactoryReset`, el bridge retorna `active_pin=0000`.

Recomanacio operativa:

- No cablegis aquests RPCs en dashboards oberts a usuaris finals. Son operacions sensibles i tenen sentit nomes en dashboards d'administracio o proves controlades.

## 7. Consideracions especials dels nous RPCs

- `schedulers`, historics i admin no creen noves claus de telemetria ni nous client attributes.
- Els widgets `RPC Button` en mode `Two way` son la manera mes simple de provar aquests metodes des de ThingsBoard.
- Les respostes de `getSchedulers` i dels historics son arrays d'objectes. Molts widgets estandard no les renderitzen be; sovint et caldra un widget JSON, una targeta de text o un widget personalitzat.
- Si nomes vols historic operatiu per a dashboards, la telemetria normal de ThingsBoard continua sent la via mes natural.

## 8. Errors i diagnostics que veuras a ThingsBoard

Codis d'error funcionals que pot retornar el bridge:

- `invalid_request`
- `wrong_device`
- `invalid_params`
- `unknown_method`
- `ble_error`
- `ble_dependency_error`
- `internal_error`
- `queue_overflow`
- `superseded`

Els dos casos operatius mes importants:

- Si envies moltes ordres de potencia seguides, el bridge aplica politica "l'ultima guanya". Les ordres anteriors poden acabar amb `superseded`.
- Si la cua RPC s'omple, les ordres velles descartades responen `queue_overflow`.
- En schedulers i admin, la majoria d'errors reals acostumen a ser `invalid_params` per camps com `slot_id`, `type`, `target_isodatetime`, `weekdays`, `time` o `new_pin`.

Per vigilar salut del sistema al dashboard del gateway, posa latest values sobre:

- `mqtt_connected`
- `ble_connected`
- `rpc_queue_depth`
- `last_ble_op_ms`
- `last_rpc_total_ms`

## 9. Dashboards i widgets

### 9.1 Dashboard minim recomanat

Si vols un dashboard funcional des del primer moment, la distribucio mes util es:

- Bloc `Estat actual`: `power_w`, `plug_on`, `energy_total_kwh`.
- Bloc `Salut del bridge`: `mqtt_connected`, `ble_connected`, `rpc_queue_depth`.
- Bloc `Historic`: grafic de `power_w` i, si t'interessa, `voltage_v` o `current_a`.
- Bloc `Control`: ON, OFF, toggle, `getMeasurement`, `syncTime`.
- Bloc `Configuracio`: `device_name`, `power_limit_w`, `night_mode`, `price_normal_cent`, `price_reduced_cent`.
- Bloc `Automatitzacio`: `timer_*` i `random_mode_*`.
- Bloc `Automatitzacio avancada`: `getSchedulers` i presets de `addOnetimeScheduler` o `addRepeatedScheduler`.
- Bloc `Manteniment`: botons per `getConsumption23h`, `getConsumption30d`, `getConsumption12m` i, si realment toca, `resetConsumption`.
- Bloc `Administracio`: `adminChangePin`, `adminResetPin` i `adminFactoryReset`, nomes si el dashboard es intern i controlat.

Separacio recomanada:

- Dashboard 1 `SEM6000 operacio`: widgets sobre `sem6000_device`.
- Dashboard 2 `SEM6000 gateway`: widgets sobre `sem6000_gateway`.

### 9.2 Com configurar un widget de lectura instantania

Cas tipic: mostrar `power_w`, `voltage_v`, `current_a` o `frequency_hz`.

Configuracio:

1. Afegeix un nou widget.
2. Tria un widget de tipus `Latest values`.
3. Pots usar bundles com `Digital gauges`, `Cards`, `Analog Gauges` o qualsevol equivalent visual.
4. A la font de dades, tria l'alias `sem6000_device`.
5. Afegeix la clau de dada exacta, per exemple `power_w`.
6. Configura la unitat visual si toca:
   - `power_w` -> `W`
   - `voltage_v` -> `V`
   - `current_a` -> `A`
   - `frequency_hz` -> `Hz`
   - `energy_total_kwh` -> `kWh`
7. Desa el widget i comprova que apareixen valors.

Notes practiques:

- Si `voltage_v`, `current_a`, `frequency_hz` o `energy_total_kwh` no es veuen sempre, no es un error del widget: el bridge nomes els publica quan l'endoll esta actiu, o si `ENABLE_EXTENDED_MEASUREMENTS=true`.
- Si nomes vols l'ultim estat, no facis servir un widget `Time series`.

### 9.3 Com configurar un widget d'historic

Cas tipic: veure l'evolucio de `power_w` en temps real o historic.

Configuracio:

1. Afegeix un nou widget.
2. Tria un widget de tipus `Time series`, per exemple un line chart.
3. A la font de dades, tria l'alias `sem6000_device`.
4. Afegeix com a clau de telemetria `power_w`.
5. Si vols mes series, afegeix `voltage_v`, `current_a` o `energy_total_kwh`.
6. Configura la finestra temporal:
   - Realtime curt: ultims `5m` o `15m`
   - Historic curt: ultimes `24h`
   - Historic llarg: ultima `1w`
7. Desa el widget.

Important:

- `Time series` es per telemetria. No hi intentis posar `device_name`, `timer_action` o altres atributs.
- `energy_total_kwh` es acumulat, aixi que funciona millor en grafiques lentes o en targetes de valor actual.

### 9.4 Com configurar widgets d'estat i configuracio

Cas tipic: mostrar valors com `plug_on`, `device_name`, `power_limit_w`, `night_mode`, `timer_active` o `random_mode_enabled`.

Configuracio:

1. Afegeix un nou widget de tipus `Latest values`.
2. Tria l'alias `sem6000_device`.
3. Afegeix una de les claus seguents segons el cas:
   - `plug_on`
   - `device_name`
   - `night_mode`
   - `power_limit_w`
   - `price_normal_cent`
   - `price_reduced_cent`
   - `timer_active`
   - `timer_action`
   - `timer_target_isodatetime`
   - `random_mode_enabled`
   - `random_mode_weekdays`
4. Desa el widget.

Recomanacio:

- Per a configuracio i automatitzacio, solen quedar millor targetes de text, taules de latest values o badges d'estat que no pas grafiques.

### 9.5 Com configurar widgets RPC simples que funcionen sempre

Els widgets mes segurs per aquest projecte son els `RPC Button`, perque et deixen fixar `method` i `params` exactes.

Patro recomanat:

1. Afegeix un nou widget.
2. Tria un widget de tipus `Control widget`.
3. Dins dels bundles, prioritza `Control widgets`.
4. Si existeix, tria `RPC Button`.
5. A la font de dades, tria l'alias `sem6000_device`.
6. A les opcions RPC del widget posa:
   - `RPC method`: el metode exacte del bridge
   - `RPC params`: el JSON o valor exacte
7. Si el widget permet `One way` o `Two way`, fes servir `Two way` quan vulguis veure resposta i errors.
8. Si hi ha camp de timeout, posa entre `5000` i `10000` ms.
9. Desa el widget i prova'l.

Exemples de configuracio que funcionen:

- Boto ON:
  - `method=powerOn`
  - `params={}`
- Boto OFF:
  - `method=powerOff`
  - `params={}`
- Boto refresh mesura:
  - `method=getMeasurement`
  - `params={}`
- Boto sync hora:
  - `method=syncTime`
  - `params={}`
- Boto llegir settings:
  - `method=getSettings`
  - `params={}`
- Boto reset timer:
  - `method=resetTimer`
  - `params={}`
- Boto reset random mode:
  - `method=resetRandomMode`
  - `params={}`
- Boto llistar schedulers:
  - `method=getSchedulers`
  - `params={}`
- Boto historic 23h:
  - `method=getConsumption23h`
  - `params={}`
- Boto reset consum:
  - `method=resetConsumption`
  - `params={}`

Nota important:

- Si el widget et deixa el camp de params buit pero realment envia una cadena buida, alguns metodes amb objectes obligatoris fallaran.
- Per a metodes sense parametres, el mes segur es posar `{}`.
- Si la resposta es una llista o un array d'objectes, comprova abans que el widget realment sap mostrar el JSON retornat.

### 9.6 Com configurar un toggle ON/OFF

Opcio recomanada si la teva versio de ThingsBoard ho suporta be:

1. Afegeix un widget de tipus `Control widget`.
2. Tria `Switch Control` o `Round Switch`.
3. Alias objectiu: `sem6000_device`.
4. Estat mostrat: clau `plug_on`.
5. RPC method: `setPower`.
6. Configura el widget per enviar un boolea real `true/false` com a `params`.
7. Activa mode `Two way` si el widget ho permet.
8. Desa i prova el canvi ON/OFF.

Si el widget no et deixa enviar el boolea correctament:

- No intentis forcar-ho amb textos tipus `ON` o `OFF` si no saps exactament que envia el widget.
- Fes servir dos `RPC Button`, un per `powerOn` i un per `powerOff`.

### 9.7 Com configurar widgets per a operacions amb JSON fix

Per a RPCs com `setPowerLimit`, `setPrices`, `setReducedPeriod`, `setTimer` o `setRandomMode`, el millor es crear widgets amb presets clars.

Exemples:

- Boto `Limit 2500 W`
  - `method=setPowerLimit`
  - `params={ "power_limit_w": 2500 }`
- Boto `Night mode ON`
  - `method=setNightMode`
  - `params={ "enabled": true }`
- Boto `Tarifa nit 23:00-06:30`
  - `method=setReducedPeriod`
  - `params={ "enabled": true, "start": "23:00", "end": "06:30" }`
- Boto `Random mode vespre`
  - `method=setRandomMode`
  - `params={ "weekdays": "Mon,Wed,Fri", "start": "18:00", "end": "23:00" }`
- Boto `Apagar avui 23:30`
  - `method=setTimer`
  - `params={ "action": "off", "target_isodatetime": "2026-04-16T23:30:00" }`
- Boto `Scheduler one-time OFF dema 07:15`
  - `method=addOnetimeScheduler`
  - `params={ "enabled": true, "action": "off", "target_isodatetime": "2026-04-30T07:15:00" }`
- Boto `Scheduler recurrent dilluns/divendres 21:30`
  - `method=addRepeatedScheduler`
  - `params={ "enabled": true, "action": "on", "weekdays": "Mon,Fri", "time": "21:30" }`
- Boto `Eliminar scheduler slot 0`
  - `method=removeScheduler`
  - `params={ "slot_id": 0 }`
- Boto `Canviar PIN a 1234`
  - `method=adminChangePin`
  - `params={ "new_pin": "1234" }`

Per a valors variables introduits per usuari:

- Si tens una versio de ThingsBoard amb widgets d'entrada que deixen editar JSON o camps, els pots usar.
- Si no, et sortira mes a compte fer presets amb diversos botons.
- Per a formularis complets de timer, random mode o schedulers, probablement necessitaras un widget personalitzat.
- Per a historics i llistes de schedulers, sovint et caldra un widget que renderitzi la resposta RPC i no nomes enviarla.

### 9.8 Com configurar un dashboard del gateway

Per monitoritzar el pont MQTT/BLE:

1. Afegeix widgets `Latest values`.
2. Usa l'alias `sem6000_gateway`.
3. Afegeix aquestes claus:
   - `mqtt_connected`
   - `ble_connected`
   - `rpc_queue_depth`
   - `last_ble_op_ms`
   - `last_rpc_total_ms`
4. Desa el dashboard.

Interpretacio rapida:

- `mqtt_connected=false`: el bridge no esta connectat a ThingsBoard.
- `ble_connected=false`: problema amb la connexio al SEM6000.
- `rpc_queue_depth` alt: s'estan acumulant ordres.
- `last_ble_op_ms` o `last_rpc_total_ms` alts: resposta lenta o reintents BLE.

### 9.9 Errors de configuracio habituals

Els errors mes tipics quan un widget "no funciona" son:

- Has posat el widget sobre el gateway en lloc del dispositiu fill.
- Has fet servir un alias amb un altre nom de dispositiu que no coincideix amb `THINGSBOARD_CHILD_DEVICE_NAME`.
- Has intentat visualitzar atributs amb un widget `Time series`.
- Has intentat controlar el dispositiu escrivint atributs en lloc d'enviar RPC.
- El widget envia un `params` buit o mal format quan el metode espera un objecte JSON.
- El widget envia strings quan el metode espera un boolea o un enter.
- Has intentat renderitzar una resposta de `getSchedulers` o dels historics amb un widget que no sap mostrar arrays JSON.
- Has oblidat que `removeScheduler` accepta el slot `0` i que despres de `adminResetPin` o `adminFactoryReset` el PIN actiu torna a `0000`.
- Esperes veure `device_serial` com a atribut, pero nomes surt a la resposta RPC.

### 9.10 Configuracions recomanades de widgets

Els noms exactes de menu poden variar segons la versio de ThingsBoard, pero la configuracio funcional a posar es aquesta:

| Cas d'us | Entitat | Tipus de dada | Configuracio exacta |
| --- | --- | --- | --- |
| Mostrar potencia instantania | Dispositiu fill | Latest/Timeseries | Clau `power_w` |
| Mostrar tensio | Dispositiu fill | Latest/Timeseries | Clau `voltage_v` |
| Mostrar corrent | Dispositiu fill | Latest/Timeseries | Clau `current_a` |
| Mostrar frequencia | Dispositiu fill | Latest/Timeseries | Clau `frequency_hz` |
| Mostrar energia acumulada | Dispositiu fill | Latest/Timeseries | Clau `energy_total_kwh` |
| Mostrar estat ON/OFF | Dispositiu fill | Latest value | Clau `plug_on` |
| Toggle ON/OFF | Dispositiu fill | RPC | `method=setPower`, `params=true/false` |
| Boto ON | Dispositiu fill | RPC | `method=powerOn` |
| Boto OFF | Dispositiu fill | RPC | `method=powerOff` |
| Refrescar mesura puntual | Dispositiu fill | RPC | `method=getMeasurement` |
| Sincronitzar hora del SEM6000 | Dispositiu fill | RPC | `method=syncTime` |
| Consultar settings | Dispositiu fill | RPC | `method=getSettings` |
| Canviar night mode | Dispositiu fill | RPC | `method=setNightMode`, `params={ "enabled": true }` |
| Canviar power limit | Dispositiu fill | RPC | `method=setPowerLimit`, `params={ "power_limit_w": 2500 }` |
| Canviar preus | Dispositiu fill | RPC | `method=setPrices`, `params={ "normal_price_cent": 22, "reduced_price_cent": 7 }` |
| Canviar franja reduida | Dispositiu fill | RPC | `method=setReducedPeriod`, `params={ "enabled": true, "start": "23:00", "end": "06:30" }` |
| Canviar nom del dispositiu | Dispositiu fill | RPC | `method=setDeviceName`, `params={ "device_name": "Desk Plug" }` |
| Consultar serial | Dispositiu fill | RPC | `method=getDeviceSerial` |
| Crear timer | Dispositiu fill | RPC | `method=setTimer`, `params={ "action": "off", "target_isodatetime": "2026-04-16T23:30:00" }` |
| Reset timer | Dispositiu fill | RPC | `method=resetTimer` |
| Configurar random mode | Dispositiu fill | RPC | `method=setRandomMode`, `params={ "weekdays": "Mon,Wed,Fri", "start": "18:00", "end": "23:00" }` |
| Reset random mode | Dispositiu fill | RPC | `method=resetRandomMode` |
| Llistar schedulers | Dispositiu fill | RPC | `method=getSchedulers` |
| Crear scheduler one-time | Dispositiu fill | RPC | `method=addOnetimeScheduler`, `params={ "enabled": true, "action": "off", "target_isodatetime": "2026-04-30T07:15:00" }` |
| Crear scheduler repeated | Dispositiu fill | RPC | `method=addRepeatedScheduler`, `params={ "enabled": true, "action": "on", "weekdays": "Mon,Fri", "time": "21:30" }` |
| Eliminar scheduler | Dispositiu fill | RPC | `method=removeScheduler`, `params={ "slot_id": 0 }` |
| Historic 23h sota demanda | Dispositiu fill | RPC | `method=getConsumption23h` |
| Historic 30d sota demanda | Dispositiu fill | RPC | `method=getConsumption30d` |
| Historic 12m sota demanda | Dispositiu fill | RPC | `method=getConsumption12m` |
| Reset consum del dispositiu | Dispositiu fill | RPC | `method=resetConsumption` |
| Canviar PIN | Dispositiu fill | RPC | `method=adminChangePin`, `params={ "new_pin": "1234" }` |
| Reset PIN a 0000 | Dispositiu fill | RPC | `method=adminResetPin` |
| Factory reset | Dispositiu fill | RPC | `method=adminFactoryReset` |
| Salut del bridge | Gateway | Latest values | Claus `mqtt_connected`, `ble_connected`, `rpc_queue_depth`, `last_ble_op_ms`, `last_rpc_total_ms` |

### 9.11 Widget custom de consums

Si vols integrar dins d'un sol panell els tres historics (`23h`, `30d` i `12m`), tens ja preparat aquest export:

- [sem6000_consumption_history_widget.json](<r:\Codis\codis\docs\sem6000_consumption_history_widget.json>)

Que fa aquest widget:

- capcalera `Consum` amb selector de periode `23h / 30d / 12m`
- refresc RPC sobre el dispositiu fill
- resum de mostres, total, ultim valor i pic
- visualitzacio en barres de mes recent a mes antic
- opcio per amagar files sense dada
- opcio per veure el JSON brut retornat per la RPC

Com importar-lo:

1. Entra a `Widgets library` de ThingsBoard.
2. Crea o obre un bundle de widgets on vulguis guardar-lo.
3. Importa el JSON de [sem6000_consumption_history_widget.json](<r:\Codis\codis\docs\sem6000_consumption_history_widget.json>).
4. Afegeix el widget al dashboard.
5. Assigna-li com a entitat l'alias `sem6000_device`.

Configuracio recomanada:

- `requestTimeout`: `30000`
- `defaultPeriod`: `23h`
- `autoLoadOnInit`: `true`
- `hideEmptyRows`: `true`
- `showRawResponse`: `false`

Limitacions conegudes:

- El widget continua depenent de les RPCs `getConsumption23h`, `getConsumption30d` i `getConsumption12m`; no converteix aquestes dades en telemetria persistent de ThingsBoard.
- Si el dispositiu retorna molts `null`, la visualitzacio pot quedar gairebe buida fins que desmarquis `Amaga files sense dada`.
- Si la teva instancia de ThingsBoard canvia algun detall intern del `controlApi.sendTwoWayCommand`, la part de render del JSON brut es pot haver d'ajustar.

## 10. Referencies oficials de ThingsBoard

La UI pot variar lleugerament segons edicio i versio. Per aquesta part de widgets i dashboards, les referencies oficials mes utiles son:

- Dashboards i entity aliases: <https://thingsboard.io/docs/user-guide/dashboards/>
- Aliases: <https://thingsboard.io/docs/user-guide/ui/aliases/>
- Widgets library i tipus de widget: <https://thingsboard.io/docs/user-guide/ui/widget-library/>
- Guia general de widgets: <https://thingsboard.io/docs/user-guide/widgets/>
- RPC des del dashboard: <https://thingsboard.io/docs/user-guide/rpc/>

Inferencia aplicada en aquest document:

- Els noms exactes d'alguns widgets o pestanyes poden canviar.
- El contracte `method/params`, les claus de telemetria i les claus d'atributs si que provenen del codi real del bridge.

## 11. Resum curt de que es pot fer avui

Des de ThingsBoard avui ja es pot:

- Encendre i apagar l'endoll.
- Llegir estat, potencia i mesures electriques.
- Sincronitzar l'hora del dispositiu.
- Llegir i modificar night mode, limit de potencia, preus i franja reduida.
- Llegir i canviar el nom del dispositiu.
- Llegir el serial.
- Llegir, crear i resetar el timer.
- Llegir, configurar i resetar el random mode.
- Llegir, crear, editar i esborrar schedulers.
- Demanar historics de consum 23h, 30d i 12m per RPC.
- Fer reset del consum acumulat guardat al dispositiu.
- Fer operacions administratives com canvi de PIN, reset de PIN i factory reset.
- Monitoritzar l'estat del bridge MQTT/BLE.

El que continua sent poc natural des de ThingsBoard, fins i tot ara que el bridge ho suporta, es renderitzar be respostes complexes com llistes de schedulers o arrays d'historics sense usar widgets RPC amb resposta visible o widgets personalitzats.
