"""Synthetic MQTT publisher/observer running only on an internal Docker network."""

import json
from pathlib import Path
import threading
import time

import paho.mqtt.client as mqtt

connected = threading.Event()
evidence = Path("/evidence/mqtt.jsonl")
client = mqtt.Client(
    mqtt.CallbackAPIVersion.VERSION2, client_id="smoke-observer", protocol=mqtt.MQTTv5
)
client.username_pw_set("synthetic-mqtt", "SYNTHETIC_MQTT_PASSWORD")


def on_connect(client, userdata, flags, reason_code, properties):
    assert reason_code == 0
    client.subscribe("#")
    connected.set()


def on_message(client, userdata, msg):
    payload = msg.payload.decode()
    with evidence.open("a") as stream:
        stream.write(json.dumps({"topic": msg.topic, "payload": payload}) + "\n")
    if msg.topic == "thermowatt/bridge/availability" and payload == "online":
        # Wait for the bridge's cached-device subscription to be active.
        for mode in ("Manual", "off", "Eco", "Auto", "Holiday"):
            client.publish("P/SYNTHETIC123/CMD/MODE", mode, qos=1)
        client.publish("P/SYNTHETIC123/CMD/TEMP", "65", qos=1)
        client.publish("P/SYNTHETIC123/refresh", "refresh", qos=1)
        client.publish("P/SYNTHETIC123/refresh", "refresh", qos=1, retain=True)


client.on_connect = on_connect
client.on_message = on_message
client.connect("mqtt", 1883)
client.loop_start()
assert connected.wait(15), "Observer MQTT connection failed"
while True:
    time.sleep(1)
