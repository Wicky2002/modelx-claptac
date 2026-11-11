# ATLAS Hardware: Raspberry Pi Sensor Node

A Raspberry Pi reads physical sensors and sends the readings to ATLAS. There, they arrive as **machine feeds** for A1 Sentinel. The Pi only measures and forwards; deciding whether a reading is an anomaly is A1's job.

```
Sensors ─► Raspberry Pi (sensor_node.py) ─► MQTT broker ─► atlas/ingest/sensors.py ─► A1 Sentinel ─► COP
                                         └─ or HTTP POST /ingest/sensor ─┘
```

## Parts list (1 node)

| Part | Purpose | Notes |
|---|---|---|
| Raspberry Pi 4 or 5 + power supply + microSD (32 GB) | Node | Raspberry Pi OS Lite, 64-bit |
| JSN-SR04T waterproof ultrasonic sensor | Water / river level | Needs a voltage divider on the echo pin |
| Tipping-bucket rain gauge | Rainfall | Reed switch, one GPIO pin |
| BME280 breakout | Temperature, humidity, pressure | I2C |
| Capacitive soil moisture sensor v1.2 *(optional)* | Landslide risk | Analog, so it needs the ADC below |
| ADS1115 ADC *(optional)* | Analog input for the soil sensor | I2C |
| MPU6050 | Slope tilt / movement | `mpu6050_tilt`: degrees from the installed angle (I2C 0x68) |
| 1 kΩ + 2 kΩ resistors, breadboard, jumper wires | Wiring | |

**Order parts in Week 0.** Local stock and shipping are the biggest schedule risk.

## Wiring (BCM pin numbers)

| Sensor | Sensor pin | Pi pin |
|---|---|---|
| JSN-SR04T | VCC / GND | 5V (pin 2) / GND (pin 6) |
| | TRIG | GPIO23 (pin 16) |
| | ECHO | GPIO24 (pin 18) **through a 1k/2k divider (5V → 3.3V)** |
| Rain gauge | two leads | GPIO17 (pin 11) and GND |
| BME280 | VIN / GND | 3.3V (pin 1) / GND (pin 9) |
| | SDA / SCL | GPIO2 (pin 3) / GPIO3 (pin 5) |
| ADS1115 | VDD / GND / SDA / SCL | 3.3V / GND / GPIO2 / GPIO3 (shares the I2C bus) |
| Soil sensor | AOUT | ADS1115 A0 |
| MPU6050 | VCC / GND / SDA / SCL | 3.3V / GND / GPIO2 / GPIO3 (shares the I2C bus, address 0x68) |

> The Pi's GPIO pins are **3.3V only**. Connecting a 5V echo line directly can damage the Pi.

## Pi setup

```bash
sudo raspi-config                     # Interface Options → enable I2C
git clone https://github.com/Wicky2002/modelx-claptac.git ~/modelx-claptac && cd ~/modelx-claptac/hardware/pi
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml    # set node_id, location, broker IP, sensors
i2cdetect -y 1                        # BME280 at 0x76 (or 0x77), MPU6050 at 0x68, ADS1115 at 0x48
python sensor_node.py --config config.yaml
```

To run it on boot:

```bash
sudo cp atlas-sensor.service /etc/systemd/system/
sudo systemctl enable --now atlas-sensor
journalctl -u atlas-sensor -f
```

## Server / laptop side

Start an MQTT broker on the machine that runs ATLAS:

```bash
mosquitto -c hardware/mosquitto/mosquitto.conf
```

Watch the readings coming in:

```bash
mosquitto_sub -h localhost -t "atlas/sensors/#" -v
```

ATLAS subscribes using `atlas.ingest.sensors.run_mqtt_listener`. Nodes can also POST to `/ingest/sensor` on the FastAPI app (`transport.kind: http`).

## Message format

Topic: `atlas/sensors/<node_id>/<type>`

```json
{
  "node_id": "rtp-node-01",
  "sensor_id": "wl-01",
  "type": "water_level",
  "value": 27.5,
  "unit": "cm",
  "timestamp": "2026-09-18T10:00:00+00:00",
  "location": {"lat": 6.6828, "lon": 80.3992, "area_id": "ratnapura-demo-river"}
}
```

`type` must be one of `water_level`, `rainfall`, `soil_moisture`, `temperature`, `humidity`, `pressure`, `tilt`. The server rejects anything else.

## Developing without a Pi

In `config.yaml`, replace the hardware sensors with `driver: mock` entries. They work on any laptop. `scenario: flood_ramp` makes the water level rise smoothly from `baseline` to `peak` over `ramp_seconds`.

## Demo setup (tabletop flood model)

1. Mount the ultrasonic sensor above a clear container that represents the river, with `mount_height_cm` set to the distance from the sensor to the container floor.
2. Put the node's `area_id` on a road edge next to the river in the Ratnapura OSM graph (`data/reference/sensor_map.yaml`).
3. Pour in water. The water level crosses the A1 threshold, A1 emits a trigger, A3 wakes up, and A4 reroutes around the flooded edge. The dashboard shows the live reading and the new route.
4. **Fallback:** if the hardware fails on the day, switch the node to `mock` + `flood_ramp`. The same messages flow through the same pipeline.

## Safety

Keep water well away from the Pi and the breadboard. Only the waterproof JSN-SR04T probe should be anywhere near the container.

## Record a real bench session for replay (H3)

For a software-only rehearsal, use the committed simulated session:

```bash
python -m atlas.ingest.simulator data/scenarios/ratnapura_simulated_bench.json
```

It contains two simulated nodes sampled every 10 seconds for 10 minutes. The
water reading rises within the 0–40 cm tabletop scale, soil moisture rises as
the probe is wetted, and tilt crosses the demo threshold only after a sustained
board movement. A brief sub-threshold vibration is included. The generator is
`python -m atlas.datasets.simulated_bench --output data/scenarios/ratnapura_simulated_bench.json`.
The file is marked `simulated_bench` and contains no hardware measurements; it
cannot satisfy H3's real-recording acceptance check.

On each Pi, set `recording_path: recordings/bench-node-01.jsonl` in `config.yaml`
(use a distinct filename per node). The node appends every measured reading to
that file before sending it; it continues recording if the network is down.
Keep the raw JSONL files out of the repository. During one session, record dry
and wet soil, rising water, and a gently tilted, firmly mounted slope sensor.

Copy the JSONL files to the laptop, then run:

```bash
python -m atlas.datasets.bench_recording bench-node-01.jsonl bench-node-02.jsonl \
  --name ratnapura-bench --output data/scenarios/ratnapura_bench.json
python -m atlas.ingest.simulator data/scenarios/ratnapura_bench.json
```

The converter requires water level, soil moisture, and tilt readings from one
`area_id`, validates units and timestamps, and reports each observed range.
Compare those ranges with `data/reference/sensor_map.yaml` (especially the
tabletop water level's 0–40 cm scale) and record any mismatch in the scenario
before committing it. The scenario says `real: false` and `bench_test`: its
measurements are real, but it is not a recorded landslide. Check that the replay
prints an A1 trigger before marking H3 complete.
