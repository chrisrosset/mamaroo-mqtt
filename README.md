# mamaroo-mqtt
MQTT-based mamaRoo4 adapter for Home Assistant

## HAOS Setup Notes

Unfortunately, this project is not available as a HA add-on (PRs welcome!).
Troubleshooting is going to be difficult if you don't have experience with
Docker.

1. You need to have the MQTT integration enabled. If you don't have a broker set
   up already, you can install one through the add-on store ("Mosquitto
   broker").
2. You need to discover the MAC address of your Mamaroo. If I remember
   correctly, you'll need to put it into pairing mode and then use a BLE scanner
   to find it. You can install a BLE scanner app on your phone and put it right
   against the Mamaroo.
3. You need to have the "SSH & Web Terminal" add-on (not "Terminal & SSH"!)
   installed and set up. Note that "Protection mode" needs to be disabled.
4. Open the add-on page and click "Open Web UI"
5. Clone (copy) the code from Github with this command:
   ```sh
   git clone https://github.com/chrisrosset/mamaroo-mqtt
   ```
6. Change the current directory to the project's:
   ```sh
   cd mamaroo-mqtt
   ```
7. Build the docker image with this command (this might take a while):
   ```sh
   docker build -t mamaroo .
   ```
8. Create and start a container. Replace the XXs with the MAC you found before:
   ```sh
   docker run -d --name mamaroo --restart=unless-stopped \
       -v /var/run/dbus:/var/run/dbus mamaroo --broker core-mosquitto \
       --username "your-user-here" --password "your-password-here"  XX:XX:XX:XX:XX:XX
   ```

If everything goes well, you should should see new entities appear (2 selects
and 1 switch) in Home Assistant.
