#!/usr/bin/env python3.9

import argparse
import asyncio
import contextlib
import json
import logging
import subprocess

import asyncio_mqtt
import bleak

UUID = "622d0101-2416-0fa7-e132-2f1495cc2ce0"
MODES = ["", "Car Ride", "Kangaroo", "Tree Swing", "Rock-A-Bye", "Wave"]

logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s', level=logging.INFO)

def base_mqtt_topic(prefix, mac, component="select"):
    return f"{prefix}/{component}/mamaroo/{mac.replace(':', '_')}"

class MqttPoster():
    _mac = None
    _mqtt = None
    _status = None
    _available = False

    def __init__(self, mqtt, mac, prefix):
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

        asyncio.create_task(self._mqtt.publish(
            f"{base_mqtt_topic(self._prefix, self._mac, 'switch')}/state",
            payload=str(status["power"]), retain=True))

        asyncio.create_task(self._mqtt.publish(
            f"{base_mqtt_topic(self._prefix, self._mac)}-mode/state",
            payload=MODES[status["mode"]], retain=True))

        asyncio.create_task(self._mqtt.publish(
            f"{base_mqtt_topic(self._prefix, self._mac)}-speed/state",
            payload=str(status["speed"]), retain=True))

        if not self._available:
            self._available = True
            asyncio.create_task(self._mqtt.publish(
                f"{base_mqtt_topic(self._prefix, self._mac, 'switch')}/availability",
                payload="online", retain=True))

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

async def consume_mqtt(messages, bt, args):
    try:
        async for message in messages:
            payload = message.payload.decode()
            logging.info("Incoming MQTT topic={} message={}".format(message.topic, payload))

            parts = message.topic.split('/')
            component = parts[1]
            if component == "switch":
                speed = 1 if payload == '1' else 0
                await bt.write_gatt_char(UUID, bt_payload_power(speed))
                continue

            entity = parts[3].split('-')

            if len(entity) != 2:
                continue

            if entity[0].replace('_', ':') != args.MAC:
                continue

            if entity[1] == "mode":
                await bt.write_gatt_char(UUID, bt_payload_mode(MODES.index(payload)))
            elif entity[1] == "speed":
                speed = int(payload)
                await bt.write_gatt_char(UUID, bt_payload_power(speed))
                await bt.write_gatt_char(UUID, bt_payload_speed(speed))
                await bt.write_gatt_char(UUID, bt_payload_move(speed))
    except asyncio.CancelledError as e:
        logging.info("Shutting down MQTT consumer on task cancel. e = {}".format(e))
    except bleak.BleakError as e:
        logging.error("Bluetooth error encountered while sending data. e = {}".format(e))
    except Exception as e:
        logging.error("Unknown error while processing MQTT message. e = {}".format(e))

async def publish_autodiscovery_data(mqtt, args):

    mac = args.MAC
    base_topic = base_mqtt_topic(args.prefix, mac)

    device = {
        "name": "mamaroo4 infant seat",
        "manufacturer": "4moms",
        "model": "mamaRoo4",
        "connections": [['mac', args.MAC]],
        "identifiers": [args.MAC]
    }

    if args.serial:
        device["identifiers"].append(args.serial)

    def unique_id(name):
        return f"mamaroo-{mac.replace(':', '-').lower()}-{name}"

    switch_topic = f"{base_mqtt_topic(args.prefix, mac, 'switch')}"
    await mqtt.publish(f"{switch_topic}/config", json.dumps({
        "name": f"Mamaroo {mac} Switch",
        "availability_topic": f"{switch_topic}/availability",
        "command_topic": f"{switch_topic}/command",
        "state_topic": f"{switch_topic}/state",
        "payload_on": "1",
        "payload_off": "0",
        "device": device,
        "icon": "mdi:rocket-launch",
        "unique_id": unique_id('switch')
    }), retain=True)

    mode_topic = f"{base_topic}-mode"
    await mqtt.publish(f"{mode_topic}/config", json.dumps({
        "name": f"Mamaroo {mac} Mode",
        "command_topic": f"{mode_topic}/command",
        "state_topic": f"{mode_topic}/state",
        "options": MODES[1:],
        "device": device,
        "unique_id": unique_id('mode')
    }), retain=True)

    speed_topic = f"{base_topic}-speed"
    await mqtt.publish(f"{speed_topic}/config", json.dumps({
        "name": f"Mamaroo {mac} Speed",
        "command_topic": f"{speed_topic}/command",
        "state_topic": f"{speed_topic}/state",
        "options": ["0", "1", "2", "3", "4", "5"],
        "device": device,
        "icon": "mdi:speedometer",
        "unique_id": unique_id('speed')
    }), retain=True)

    logging.info("Auto-discovery messages published.")

def on_bt_disconnect(client):
    logging.warning("Client with address {} got disconnected!".format(client.address))
    raise Exception(f"{client.address} disconnected")

def create_arg_parser():
    parser = argparse.ArgumentParser(description="mamaRoo4 MQTT Adapter")
    parser.add_argument("--prefix", "-p", type=str,
                        default="homeassistant", help='MQTT auto-discovery prefix')
    parser.add_argument("--broker", "-b", type=str,
                        default="localhost", help='MQTT broker URL')
    parser.add_argument("--serial", "-s", type=str,
                        help='Device serial number')
    parser.add_argument("--verbose", "-v", action="store_true",
                        default=False, help='Verbose mode')
    parser.add_argument('MAC', type=str, help='mamaRoo4 MAC Address')
    return parser

async def bluetooth_keep_alive(bt):
    while bt.is_connected:
        await asyncio.sleep(15)

    raise Exception("Bluetooth disconnected.")

async def run(args):
    async with contextlib.AsyncExitStack() as stack:
        will = asyncio_mqtt.Will(
            f"{base_mqtt_topic(args.prefix, args.MAC, 'switch')}/availability",
            payload="offline",
            retain=True)

        mqtt = asyncio_mqtt.Client(args.broker, will=will)
        await stack.enter_async_context(mqtt)
        logging.info("MQTT connection to {} established.".format(args.broker))

        stack.push_async_callback(
            mqtt.publish, will.topic, payload=will.payload, retain=will.retain)

        bt = bleak.BleakClient(args.MAC, timeout=5)
        await stack.enter_async_context(bt)
        logging.info("Bluetooth connection to {} established.".format(args.MAC))

        messages = await stack.enter_async_context(mqtt.unfiltered_messages())
        mqtt_consumer = asyncio.create_task(consume_mqtt(messages, bt, args))

        poster = MqttPoster(mqtt, args.MAC, args.prefix)

        await asyncio.gather(
            publish_autodiscovery_data(mqtt, args),
            mqtt_consumer,
            mqtt.subscribe(f"{args.prefix}/+/mamaroo/+/command"),
            bt.start_notify(UUID, poster),
            bluetooth_keep_alive(bt))

def main():
    args = create_arg_parser().parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logging.info("Configuration = {}".format(str(args)))

    # If the process crashes it's going to leave an open connection which
    # will prevent a new instance from establishing a new connection. This
    # is a quick way to clear this on startup.
    subprocess.call(['bluetoothctl','disconnect', args.MAC], timeout=10)

    for i in range(100):
        try:
            logging.info("Connection attempt #{}".format(i))
            asyncio.run(run(args))
        except bleak.exc.BleakDBusError as e:
            logging.info("Connection #{} failed. e = {}".format(i, e))

if __name__ == "__main__":
    main()
