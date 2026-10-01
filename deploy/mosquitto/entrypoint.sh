#!/bin/sh
# Generates the broker password file from WA_MQTT_USER / WA_MQTT_PASS on every start.
set -eu
: "${WA_MQTT_PASS:?WA_MQTT_PASS is required}"
mosquitto_passwd -c -b /mosquitto/data/passwd "${WA_MQTT_USER:-wheres_allie}" "$WA_MQTT_PASS"
chown mosquitto:mosquitto /mosquitto/data/passwd
chmod 0600 /mosquitto/data/passwd
exec mosquitto -c /mosquitto/config/mosquitto.conf
