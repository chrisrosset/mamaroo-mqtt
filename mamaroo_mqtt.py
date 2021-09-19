#!/usr/bin/env python3.9

import argparse
import asyncio
import json
import sys

import asyncio_mqtt
import bleak

UUID = "622d0101-2416-0fa7-e132-2f1495cc2ce0"
MODES = ["", "Car Ride", "Kangaroo", "Tree Swing", "Rock-A-Bye", "Wave"]

def base_mqtt_topic(prefix, mac, component="select"):
    return f"{prefix}/{component}/mamaroo/{mac.replace(':', '_')}"

class MqttPoster():
    _loop = None
    _mac = None
    _mqtt = None
    _status = None

    def __init__(self, loop, mqtt, mac, prefix):
        self._loop = loop
        self._mac = mac
        self._mqtt = mqtt
        self._prefix = prefix

    def __call__(self, sender, data):
        if data[0] not in [65, 83]:
            return

        status = {"mode": data[1], "speed": data[2], "power": data[5]}

        if status == self._status:
            return

        self._status = status

        self._loop.create_task(self._mqtt.publish(
            f"{base_mqtt_topic(self._prefix, self._mac)}-mode/state",
            payload=MODES[status["mode"]].encode(), retain=True))

        self._loop.create_task(self._mqtt.publish(
            f"{base_mqtt_topic(self._prefix, self._mac)}-speed/state",
            payload=str(status["speed"]).encode(), retain=True))

def clamp(minimum, maximum, value):
    return sorted([minimum, maximum, value])[1]

def bt_payload_power(speed):
    return bytearray([0x43, 0x01, 0x01 if speed > 0 else 0x00])

def bt_payload_move(speed):
    return bytearray([0x43, 0x02, 0x01 if speed > 0 else 0x00])

def bt_payload_speed(speed):
    return bytearray([0x43, 0x06, clamp(0, 5, speed)])

def bt_payload_mode(mode):
    return bytearray([0x43, 0x04, clamp(1, 5, mode)])

def validate_command_message(data):
    return ("mode" in data and isinstance(data["mode"], int)
            and "speed" in data and isinstance(data["speed"], int))

async def run(loop, mqtt, bt, args):
    poster = MqttPoster(loop, mqtt, args.MAC, args.prefix)

    await bt.start_notify(UUID, poster)

    async with mqtt.unfiltered_messages() as messages:
        await mqtt.subscribe(f"homeassistant/select/mamaroo/+/command")
        async for message in messages:
            try:
                entity = message.topic.split('/')[3].split('-')

                if len(entity) != 2:
                    continue

                if entity[0].replace('_', ':') != mac:
                    continue

                value = message.payload.decode()

                if entity[1] == "mode":
                    await bt.write_gatt_char(UUID, bt_payload_mode(MODES.index(value)))
                elif entity[1] == "speed":
                    speed = int(value)
                    await bt.write_gatt_char(UUID, bt_payload_power(speed))
                    await bt.write_gatt_char(UUID, bt_payload_speed(speed))
                    await bt.write_gatt_char(UUID, bt_payload_move(speed))
            except Exception as e:
                print(e)

async def publish_autodiscovery_data(mqtt, args):
    mac = args.MAC
    base_topic = base_mqtt_topic(args.prefix, mac)

    device = {
        "name": "mamaroo4 infant seat",
        "manufacturer": "4moms",
        "model": "mamaRoo4",
    }

    if args.serial:
        device["identifiers"] = args.serial

    mode_topic = f"{base_topic}-mode"
    await mqtt.publish(f"{mode_topic}/config", json.dumps({
        "name": f"Mamaroo {mac} Mode",
        "command_topic": f"{mode_topic}/command",
        "state_topic": f"{mode_topic}/state",
        "options": MODES[1:],
        "device": device
    }), retain=True)

    speed_topic = f"{base_topic}-speed"
    await mqtt.publish(f"{speed_topic}/config", json.dumps({
        "name": f"Mamaroo {mac} Speed",
        "command_topic": f"{speed_topic}/command",
        "state_topic": f"{speed_topic}/state",
        "options": ["0", "1", "2", "3", "4", "5"],
        "device": device,
    }), retain=True)

async def start(loop, args):
    async with asyncio_mqtt.Client(args.broker) as mqtt:

        await publish_autodiscovery_data(mqtt, args)

        async with bleak.BleakClient(args.MAC, timeout=5, loop=loop) as bt:
            try:
                print("Connected")
                await run(loop, mqtt, bt, args)
            except Exception as e:
                raise e
            finally:
                bt.disconnect()

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="mamaRoo4 MQTT Adapter")
    parser.add_argument("--prefix", "-p", type=str,
                        default="homeassistant", help='MQTT auto-discovery prefix')
    parser.add_argument("--broker", "-b", type=str,
                        default="localhost", help='MQTT broker URL')
    parser.add_argument("--serial", "-s", type=str,
                        help='Device serial number')
    parser.add_argument('MAC', type=str, help='mamaRoo4 MAC Address')
    args = parser.parse_args()

    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(start(loop, args))
    except KeyboardInterrupt:
        print("Exiting")
    except bleak.exc.BleakDBusError as e:
        print(e)
