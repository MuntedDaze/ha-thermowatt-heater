#!/usr/bin/with-contenv bashio
set -euo pipefail
umask 077

# Supervisor resolves options/secrets in /data/options.json. Never put credentials
# on the process command line or log account identifiers.
MQTT_HOST="$(bashio::services mqtt host)" || MQTT_HOST="core-mosquitto"
MQTT_PORT="$(bashio::services mqtt port)" || MQTT_PORT="1883"
MQTT_USER="$(bashio::services mqtt username)" || MQTT_USER=""
MQTT_PASSWORD="$(bashio::services mqtt password)" || MQTT_PASSWORD=""
export MQTT_HOST MQTT_PORT MQTT_USER MQTT_PASSWORD

bashio::log.info "Starting Thermowatt bridge with cloud safety controls."
exec /opt/venv/bin/python3 -u /thermowatt_bridge.py
