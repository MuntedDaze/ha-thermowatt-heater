"""MyThermowatt bridge: cloud opt-in, persistent auth guard, observed MQTT state."""

import hashlib
import json
import logging
import math
import os
from pathlib import Path
import queue
import re
import signal
import tempfile
import threading
import time
import uuid

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion
import requests

LOG = logging.getLogger("thermowatt")
_APP_API_KEY = "YVjArWssxKH631jv1dnnWOTr6gijsSAGz7rQJ4hJoUNRffxYvbQaMbePBEZalena"


class CloudError(Exception):
    """Only fixed, non-sensitive diagnostic codes are allowed."""


class AuthBlocked(CloudError):
    pass


def safe_diagnostic(code):
    """Never interpolate arbitrary exception messages, paths or response content."""
    fixed = {
        "guard_storage_unavailable",
        "auth_locked_operator_action_required",
        "auth_retry_wait",
        "auth_retry_exhausted",
        "cloud_disabled",
        "missing_credentials",
        "missing_refresh_token",
        "auth_tls_error",
        "auth_transient",
        "auth_timeout",
        "auth_connection_error",
        "auth_transport_unrecognised",
        "auth_response_unrecognised",
        "authentication_not_ready",
        "cloud_backoff",
        "cloud_tls_error",
        "cloud_timeout",
        "cloud_connection_error",
        "cloud_network_error",
        "cloud_invalid_json",
        "cloud_envelope_not_object",
        "cloud_success_false",
        "cloud_error_nonempty",
        "cloud_result_missing",
        "cloud_result_wrong_type",
        "device_list_unrecognised",
        "status_fields_missing",
        "status_values_non_numeric",
        "status_values_non_finite",
        "status_temperature_out_of_range",
        "status_mode_invalid",
        "status_heater_state_invalid",
        "command_rejected",
        "cloud_refresh_cooldown",
        "operator_required",
        "storage_invalid",
        "interrupted_auth",
        "account_changed",
        "unexpected_internal_error",
        "diagnostic_complete",
        "diagnostic_transient_no_retry",
    }
    if isinstance(code, str) and (
        code in fixed or re.fullmatch(r"(?:auth|cloud)_http_[1-5][0-9]{2}", code)
    ):
        return code
    return "cloud_error_unclassified"


def atomic_json(path, value):
    """Durably replace a private file before allowing network I/O."""
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        if os.name == "posix":
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class AuthGuard:
    """Persist intent before auth. Interrupted requests fail closed on restart."""

    MAX_ATTEMPTS = 3
    RETRY_DELAYS = (60, 300)
    REFRESH_COOLDOWN = 300

    def __init__(self, path, generation, account, clock=time.time):
        self.path = Path(path)
        self.clock = clock
        self.failed_storage = False
        self.state = self._empty()
        try:
            if self.path.exists():
                self.state = json.loads(self.path.read_text(encoding="utf-8"))
                self._validate()
                os.chmod(self.path, 0o600)
            if self.state["mode"] == "in_flight":
                self.block("interrupted_auth")
            if self.state.get("account") != account and self.state["mode"] != "blocked":
                self.block("account_changed")
            if generation > self.state["generation"]:
                self.state = self._empty()
                self.state.update(generation=generation, mode="ready", account=account)
            self._save()
        except (OSError, ValueError, TypeError, KeyError):
            # Corruption cannot consume an already-configured reset twice.
            self.state = self._empty()
            self.state.update(generation=generation, reason="storage_invalid")
            self._save()

    @staticmethod
    def _empty():
        return {
            "version": 1,
            "generation": 0,
            "mode": "blocked",
            "reason": "operator_required",
            "attempts": 0,
            "next_retry": 0,
            "action": "login",
            "account": None,
            "access_token": None,
            "refresh_token": None,
        }

    def _validate(self):
        s = self.state
        if not isinstance(s, dict) or s.get("version") != 1:
            raise ValueError
        if set(s) != set(self._empty()):
            raise ValueError
        reasons = {
            None,
            "operator_required",
            "storage_invalid",
            "interrupted_auth",
            "account_changed",
            "auth_retry_exhausted",
            "auth_transient",
            "missing_credentials",
            "missing_refresh_token",
            "auth_tls_error",
            "auth_transport_unrecognised",
            "auth_response_unrecognised",
            "cloud_tls_error",
            "unexpected_internal_error",
            "diagnostic_complete",
            "diagnostic_transient_no_retry",
        }
        reason = s["reason"]
        if not isinstance(reason, (str, type(None))):
            raise ValueError
        if reason not in reasons and not re.fullmatch(r"(?:auth|cloud)_http_[1-5][0-9]{2}", reason):
            raise ValueError
        if s.get("mode") not in {"blocked", "ready", "retry", "in_flight", "authorized"}:
            raise ValueError
        if type(s.get("generation")) is not int or s["generation"] < 0:
            raise ValueError
        if type(s.get("attempts")) is not int or not 0 <= s["attempts"] <= self.MAX_ATTEMPTS:
            raise ValueError
        if type(s.get("next_retry")) not in (int, float) or not math.isfinite(s["next_retry"]):
            raise ValueError
        if s.get("action") not in {"login", "refresh"}:
            raise ValueError
        if s["mode"] == "authorized" and not all(
            isinstance(s.get(k), str) and s[k].strip()
            for k in ("access_token", "refresh_token", "account")
        ):
            raise ValueError

    def _save(self):
        if self.failed_storage:
            raise AuthBlocked("guard_storage_unavailable")
        try:
            atomic_json(self.path, self.state)
        except OSError:
            self.failed_storage = True
            self.state["mode"] = "blocked"
            self.state["access_token"] = self.state["refresh_token"] = None
            raise AuthBlocked("guard_storage_unavailable") from None

    def check(self):
        if self.failed_storage or self.state["mode"] in {"blocked", "in_flight"}:
            raise AuthBlocked("auth_locked_operator_action_required")

    def begin(self, action):
        self.check()
        if self.clock() < self.state["next_retry"]:
            raise CloudError("auth_retry_wait")
        if self.state["attempts"] >= self.MAX_ATTEMPTS:
            self.block("auth_retry_exhausted")
            raise AuthBlocked("auth_retry_exhausted")
        self.state.update(mode="in_flight", action=action, attempts=self.state["attempts"] + 1)
        self._save()

    def success(self, access, refresh):
        self.state.update(
            mode="authorized",
            reason=None,
            attempts=0,
            # Reuse the existing persisted deadline; normal reads remain allowed.
            next_retry=(self.clock() + self.REFRESH_COOLDOWN)
            if self.state["action"] == "refresh"
            else 0,
            access_token=access,
            refresh_token=refresh,
        )
        self._save()

    def transient(self):
        attempts = self.state["attempts"]
        if attempts >= self.MAX_ATTEMPTS:
            self.block("auth_retry_exhausted")
        else:
            self.state.update(
                mode="retry",
                reason="auth_transient",
                next_retry=self.clock() + self.RETRY_DELAYS[attempts - 1],
            )
            self._save()

    def block(self, reason):
        self.state.update(mode="blocked", reason=reason, access_token=None, refresh_token=None)
        self._save()


class MyThermowattBridge:
    API_KEY = _APP_API_KEY  # Existing embedded app identifier; never log it.
    BASE_URL = "https://myapp-connectivity.com/api/v1"
    POLL_INTERVAL = 20
    HTTP_TIMEOUT = (10, 20)
    MAX_BACKOFF = 300
    STATUS_FIELDS = ("T_Avg", "T_SetPoint", "Cmd", "WaterHeaterSts")
    MODES = {9: "Manual", 3: "Eco", 17: "Schedule", 65: "Holiday", 16: "Off"}

    def __init__(
        self,
        options,
        data_dir="/data",
        session=None,
        mqtt_client=None,
        clock=time.time,
        monotonic=time.monotonic,
    ):
        self.options = options
        self.clock = clock
        self.monotonic = monotonic
        self.data_dir = Path(data_dir)
        self.config_path = self.data_dir / "thermowatt_config.json"
        self.config = {"device_uuid": str(uuid.uuid4()), "devices": {}}
        if self.config_path.exists():
            old = json.loads(self.config_path.read_text(encoding="utf-8"))
            self.config["device_uuid"] = str(uuid.UUID(old["device_uuid"]))
            # Cached devices can be announced offline, never commanded before rediscovery.
            for serial, device in old.get("devices", {}).items():
                if self.valid_serial(serial) and isinstance(device, dict):
                    self.config["devices"][serial] = {"name": str(device.get("name", "Boiler"))}
        atomic_json(self.config_path, self.config)  # Removes legacy bearer tokens.
        account = hashlib.sha256(options.get("email", "").encode()).hexdigest()
        self.guard = AuthGuard(
            self.data_dir / "auth_state.json",
            options.get("auth_retry_generation", 0),
            account,
            clock,
        )
        self.session = session if session is not None else requests.Session()
        self.session.trust_env = False  # No implicit proxy/netrc credentials.
        self.mqtt_client = (
            mqtt_client
            if mqtt_client is not None
            else mqtt.Client(CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
        )
        if os.getenv("MQTT_USER"):
            self.mqtt_client.username_pw_set(os.environ["MQTT_USER"], os.getenv("MQTT_PASSWORD"))
        self.mqtt_client.will_set("thermowatt/bridge/availability", "offline", qos=1, retain=True)
        self.mqtt_client.on_connect = self.on_mqtt_connect
        self.mqtt_client.on_disconnect = self.on_mqtt_disconnect
        self.mqtt_client.on_message = self.on_mqtt_message
        self.commands = queue.Queue(maxsize=10)
        self.mqtt_connected = threading.Event()
        self.mqtt_reconnected = threading.Event()
        self.active_devices = set()
        self.confirmed = {}
        self.availability = {}
        self.next_cloud = 0
        self.failures = 0
        self.discovered = False
        self.last_diagnostic = None
        self.operation = "authentication_guard"

    @staticmethod
    def valid_serial(serial):
        return isinstance(serial, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", serial) is not None

    def _headers(self, serial=None, authentication=False):
        headers = {"app": "MyThermowatt", "platform": "iOS", "version": "3.14", "lang": "en"}
        if authentication:
            headers["x-api-key"] = self.API_KEY
        elif self.guard.state.get("access_token"):
            headers["Authorization"] = f"Bearer {self.guard.state['access_token']}"
        if serial:
            headers["seriale"] = serial
        return headers

    def _send(self, method, endpoint, serial=None, authentication=False, **kwargs):
        # Requests' default adapter has zero retries. Never follow credential redirects.
        headers = self._headers(serial, authentication)
        if authentication and endpoint == "/refresh" and self.guard.state.get("access_token"):
            # Preserve the existing refresh contract, including its previous bearer.
            headers["Authorization"] = f"Bearer {self.guard.state['access_token']}"
        if "data" in kwargs:
            headers["Content-Type"] = "text/plain"
        return self.session.request(
            method,
            f"{self.BASE_URL}{endpoint}",
            headers=headers,
            timeout=self.HTTP_TIMEOUT,
            verify=True,
            allow_redirects=False,
            **kwargs,
        )

    def _authenticate(self, action, diagnostic=False):
        self.operation = "password_login" if action == "login" else "token_refresh"
        if not self.options.get("cloud_enabled", False):
            raise AuthBlocked("cloud_disabled")
        self.guard.check()
        if not self.options.get("email") or not self.options.get("password"):
            self.guard.block("missing_credentials")
            raise AuthBlocked("missing_credentials")
        self.guard.begin(action)
        payload = {"username": self.options["email"]}
        if action == "login":
            payload.update(password=self.options["password"], device_id=self.config["device_uuid"])
        else:
            if not self.guard.state.get("refresh_token"):
                self.guard.block("missing_refresh_token")
                raise AuthBlocked("missing_refresh_token")
            payload["refreshToken"] = self.guard.state["refresh_token"]
        try:
            response = self._send("POST", f"/{action}", authentication=True, json=payload)
        except requests.exceptions.SSLError:
            self.guard.block("auth_tls_error")
            raise AuthBlocked("auth_tls_error") from None
        except (requests.Timeout, requests.ConnectionError) as error:
            if diagnostic:
                self.guard.block("diagnostic_transient_no_retry")
            else:
                self.guard.transient()
            code = (
                "auth_timeout" if isinstance(error, requests.Timeout) else "auth_connection_error"
            )
            raise CloudError(code) from None
        except requests.RequestException:
            self.guard.block("auth_transport_unrecognised")
            raise AuthBlocked("auth_transport_unrecognised") from None
        if 500 <= response.status_code <= 599:
            if diagnostic:
                self.guard.block("diagnostic_transient_no_retry")
            else:
                self.guard.transient()
            raise CloudError(f"auth_http_{response.status_code}")
        if response.status_code != 200:
            code = f"auth_http_{response.status_code}"
            self.guard.block(code)
            raise AuthBlocked(code)
        try:
            body = response.json()
            if isinstance(body, dict) and (body.get("success") is False or body.get("error")):
                raise ValueError
            result = body.get("result") if isinstance(body, dict) else None
            if not isinstance(result, dict) or not all(
                isinstance(result.get(k), str)
                and result[k].strip()
                and not any(c in result[k] for c in "\r\n")
                for k in ("accessToken", "refreshToken")
            ):
                raise ValueError
        except (ValueError, TypeError):
            self.guard.block("auth_response_unrecognised")
            raise AuthBlocked("auth_response_unrecognised") from None
        if diagnostic:
            self.guard.block("diagnostic_complete")  # Do not persist diagnostic tokens.
            LOG.info(
                "Diagnostic accepted: login token schema matched. Device compatibility untested."
            )
        else:
            self.guard.success(result["accessToken"], result["refreshToken"])
            LOG.info(
                "Authentication accepted: operation=%s code=%s; tokens stored privately.",
                self.operation,
                "auth_login_accepted" if action == "login" else "auth_refresh_accepted",
            )
        return True

    def diagnose_auth_once(self):
        """Explicit standalone diagnostic: one login, no refresh, MQTT, reads or retries."""
        self.guard.check()
        if self.guard.state["mode"] != "ready" or self.guard.state["attempts"] != 0:
            raise AuthBlocked("diagnostic_requires_new_generation")
        return self._authenticate("login", diagnostic=True)

    def login(self):
        self.guard.check()
        if self.guard.state["mode"] == "authorized":
            return True  # Restart uses tokens, never another password login.
        return self._authenticate(self.guard.state["action"])

    def refresh_session(self):
        return self._authenticate("refresh")

    def request(self, method, endpoint, serial=None, **kwargs):
        self.guard.check()
        if not self.options.get("cloud_enabled", False):
            raise AuthBlocked("cloud_disabled")
        if self.guard.state["mode"] != "authorized":
            raise CloudError("authentication_not_ready")
        if self.clock() < self.next_cloud:
            raise CloudError("cloud_backoff")
        try:
            response = self._send(method, endpoint, serial, **kwargs)
            if response.status_code == 401 and method == "GET":
                if (
                    self.guard.state["action"] == "refresh"
                    and self.clock() < self.guard.state["next_retry"]
                ):
                    # A newly refreshed session should not need another refresh.
                    # Fail closed across polls/restarts rather than refreshing in a loop.
                    self.guard.block("cloud_http_401")
                    raise AuthBlocked("cloud_refresh_cooldown")
                operation = self.operation
                self.refresh_session()
                self.operation = operation
                response = self._send(method, endpoint, serial, **kwargs)
        except requests.exceptions.SSLError:
            self.guard.block("cloud_tls_error")
            raise AuthBlocked("cloud_tls_error") from None
        except requests.Timeout:
            raise CloudError("cloud_timeout") from None
        except requests.ConnectionError:
            raise CloudError("cloud_connection_error") from None
        except requests.RequestException:
            raise CloudError("cloud_network_error") from None
        if response.status_code in (401, 403, 429):
            code = f"cloud_http_{response.status_code}"
            self.guard.block(code)
            raise AuthBlocked(code)
        if not 200 <= response.status_code < 300:
            raise CloudError(f"cloud_http_{response.status_code}")
        return response

    @staticmethod
    def _result(response):
        try:
            body = response.json()
        except ValueError:
            raise CloudError("cloud_invalid_json") from None
        # Preserve the existing acceptance rules and first-failure order.
        if not isinstance(body, dict):
            raise CloudError("cloud_envelope_not_object")
        if body.get("success") is False:
            raise CloudError("cloud_success_false")
        if body.get("error"):
            raise CloudError("cloud_error_nonempty")
        if "result" not in body:
            raise CloudError("cloud_result_missing")
        if not isinstance(body["result"], dict):
            raise CloudError("cloud_result_wrong_type")
        return body["result"]

    def _availability(self, serial, available, force=False):
        if not force and self.availability.get(serial) is available:
            return
        self.availability[serial] = available
        self.mqtt_client.publish(
            f"P/{serial}/availability", "online" if available else "offline", qos=1, retain=True
        )

    def _offline(self):
        self.confirmed.clear()
        for serial in self.config["devices"]:
            self._availability(serial, False)
        while True:
            try:
                self.commands.get_nowait()
            except queue.Empty:
                break

    def publish_discovery(self, serial, name):
        availability = [
            {"topic": "thermowatt/bridge/availability"},
            {"topic": f"P/{serial}/availability"},
        ]
        device = {"identifiers": [f"tw_{serial}"], "manufacturer": "Thermowatt", "name": name}
        payload = {
            "unique_id": f"thermowatt_{serial}_v314",
            "name": f"Boiler {name}",
            "temp_unit": "C",
            "min_temp": 20,
            "max_temp": 75,
            "optimistic": False,
            "availability": availability,
            "availability_mode": "all",
            "current_temperature_topic": f"P/{serial}/STATUS",
            "current_temperature_template": "{{ value_json.result.T_Avg | float }}",
            "temperature_state_topic": f"P/{serial}/STATUS",
            "temperature_state_template": "{{ value_json.result.T_SetPoint | float }}",
            "temperature_command_topic": f"P/{serial}/CMD/TEMP",
            "mode_state_topic": f"P/{serial}/STATUS",
            "mode_state_template": "{{ {'9':'performance','3':'eco','16':'off'}.get(value_json.result.Cmd | int | string, none) }}",
            "mode_command_topic": f"P/{serial}/CMD/MODE",
            "mode_command_template": "{{ {'performance':'Manual','eco':'Eco','off':'off'}[value] }}",
            "modes": ["off", "eco", "performance"],
            "device": device,
        }
        self.mqtt_client.publish(
            f"homeassistant/water_heater/{serial}/config", json.dumps(payload), retain=True
        )
        heating = {
            "unique_id": f"thermowatt_{serial}_heating",
            "name": f"Boiler {name} Heating (unverified)",
            "state_topic": f"P/{serial}/STATUS",
            "device_class": "heat",
            # No verified bit definition exists. Ignore legacy retained booleans too.
            "value_template": "{{ 'None' }}",
            "availability": availability,
            "availability_mode": "all",
            "device": device,
        }
        self.mqtt_client.publish(
            f"homeassistant/binary_sensor/{serial}/heating/config", json.dumps(heating), retain=True
        )
        vendor_mode = {
            "unique_id": f"thermowatt_{serial}_vendor_mode",
            "name": f"Boiler {name} Vendor mode",
            "state_topic": f"P/{serial}/STATUS",
            "value_template": "{{ value_json.result.vendor_mode | default('Unknown') }}",
            "json_attributes_topic": f"P/{serial}/STATUS",
            "json_attributes_template": "{{ {'Cmd': value_json.result.Cmd, 'WaterHeaterSts': value_json.result.WaterHeaterSts, 'heating_status_verified': false} | tojson }}",
            "availability": availability,
            "availability_mode": "all",
            "device": device,
        }
        self.mqtt_client.publish(
            f"homeassistant/sensor/{serial}/vendor_mode/config",
            json.dumps(vendor_mode),
            retain=True,
        )

    def _subscribe(self, serial):
        # MQTT v5 preserves RETAIN on live retained writes as well as replay.
        self.mqtt_client.subscribe(
            f"P/{serial}/CMD/#", options=mqtt.SubscribeOptions(qos=0, retainAsPublished=True)
        )

    def on_mqtt_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            self.mqtt_connected.set()
            self.mqtt_reconnected.set()
            for serial in tuple(self.config["devices"]):
                self._availability(serial, False, force=True)
                self.publish_discovery(serial, self.config["devices"][serial]["name"])
                self._subscribe(serial)
            client.publish("thermowatt/bridge/availability", "online", qos=1, retain=True)

    def on_mqtt_disconnect(self, client, userdata, flags, reason_code, properties):
        self.mqtt_connected.clear()

    def on_mqtt_message(self, client, userdata, msg):
        # Callback thread only queues. It never touches HTTP or authentication.
        if (
            msg.retain
            or not self.options.get("commands_enabled", False)
            or not self.mqtt_connected.is_set()
        ):
            return
        parts = msg.topic.split("/")
        if (
            len(parts) != 4
            or parts[0] != "P"
            or parts[2] != "CMD"
            or parts[3] not in {"TEMP", "MODE"}
        ):
            return
        try:
            payload = msg.payload.decode("utf-8")
            if len(payload) > 32:
                return
            self.commands.put_nowait((self.monotonic(), parts[1], parts[3], payload))
        except (UnicodeError, queue.Full):
            LOG.warning("Command discarded: invalid encoding or queue full.")

    def discover_devices(self):
        self.operation = "device_discovery"
        result = self._result(self.request("GET", "/user-info"))
        devices = result.get("termostati")
        if not isinstance(devices, list) or any(
            not isinstance(d, dict) or not self.valid_serial(d.get("seriale")) for d in devices
        ):
            raise CloudError("device_list_unrecognised")
        active = set()
        for device in devices:
            serial = device["seriale"]
            active.add(serial)
            name = str(device.get("nome", "Boiler"))
            self.config["devices"][serial] = {"name": name}
            self.publish_discovery(serial, name)
            self._availability(serial, False)
            self._subscribe(serial)
        self.active_devices = active
        self.operation = "device_cache_storage"
        atomic_json(self.config_path, self.config)
        self.discovered = True

    def poll_status(self, serial):
        self.operation = "status_poll"
        result = self._result(self.request("GET", "/status", serial))
        if any(key not in result for key in self.STATUS_FIELDS):
            raise CloudError("status_fields_missing")
        try:
            values = {key: float(result[key]) for key in self.STATUS_FIELDS}
        except (TypeError, ValueError, OverflowError):
            raise CloudError("status_values_non_numeric") from None
        if not all(math.isfinite(v) for v in values.values()):
            raise CloudError("status_values_non_finite")
        if not 0 <= values["T_Avg"] <= 100 or not 20 <= values["T_SetPoint"] <= 75:
            raise CloudError("status_temperature_out_of_range")
        if values["Cmd"] < 0 or values["Cmd"] != int(values["Cmd"]):
            raise CloudError("status_mode_invalid")
        if values["WaterHeaterSts"] < 0 or values["WaterHeaterSts"] != int(
            values["WaterHeaterSts"]
        ):
            raise CloudError("status_heater_state_invalid")
        safe = {key: result[key] for key in self.STATUS_FIELDS}
        safe["vendor_mode"] = self.MODES.get(int(values["Cmd"]), "Unknown")
        # WaterHeaterSts is an opaque diagnostic value, not proven element feedback.
        safe["heating"] = None
        self.confirmed[serial] = (self.monotonic(), values)
        self.mqtt_client.publish(f"P/{serial}/STATUS", json.dumps({"result": safe}), retain=True)
        self._availability(serial, True)
        return values

    def process_command(self, command):
        issued, serial, kind, payload = command
        confirmed = self.confirmed.get(serial)
        if (
            not self.options.get("commands_enabled", False)
            or not self.mqtt_connected.is_set()
            or self.monotonic() - issued > 30
            or serial not in self.active_devices
            or not confirmed
            or self.monotonic() - confirmed[0] > 60
        ):
            return
        endpoint, arguments, expected = None, {}, None
        if kind == "TEMP":
            try:
                temperature = float(payload)
            except ValueError:
                return
            if (
                not math.isfinite(temperature)
                or not temperature.is_integer()
                or not 20 <= temperature <= 75
            ):
                return
            # /manual changes mode too: never change temperature from other modes.
            if confirmed[1]["Cmd"] != 9:
                return
            endpoint = "/manual"
            arguments = {"json": {"T_SetPoint": int(temperature)}}
            expected = ("T_SetPoint", temperature)
        elif kind == "MODE":
            endpoint = {
                "off": "/off",
                "Off": "/off",
                "Eco": "/eco",
                "Auto": "/auto",
                "Manual": "/manual",
            }.get(payload)
            # Holiday used to invent a 30-day end date. Never invent schedule writes.
            if not endpoint:
                return
            expected = ("Cmd", {"off": 16, "Off": 16, "Eco": 3, "Auto": 17, "Manual": 9}[payload])
            if payload == "Manual":
                arguments = {"json": {"T_SetPoint": int(confirmed[1]["T_SetPoint"])}}
            else:
                arguments = {"data": ""}
        if not endpoint:
            return
        self.operation = "heater_command"
        self._availability(serial, False)
        response = self.request("POST", endpoint, serial, **arguments)
        try:
            acknowledgement = response.json()
        except ValueError:
            acknowledgement = None  # No documented success envelope; observation still required.
        if isinstance(acknowledgement, dict) and (
            acknowledgement.get("success") is False or acknowledgement.get("error")
        ):
            raise CloudError("command_rejected")
        LOG.info("Command submitted; waiting for observed cloud state.")
        observed = self.poll_status(serial)
        if observed[expected[0]] == expected[1]:
            LOG.info("Requested value observed in cloud status.")
        else:
            LOG.warning("Command not confirmed; published observed state. No retry.")

    def tick(self):
        """One bounded iteration; authentication failure idles instead of exiting."""
        if self.mqtt_reconnected.is_set():
            self.mqtt_reconnected.clear()
            self._offline()
            self.discovered = False
        if not self.options.get("cloud_enabled", False) or not self.mqtt_connected.is_set():
            self._offline()
            return
        try:
            self.operation = "authentication_guard"
            self.guard.check()
            if self.clock() < self.next_cloud:
                return
            self.login()
            if not self.discovered:
                self.discover_devices()
            try:
                command = self.commands.get_nowait()
            except queue.Empty:
                command = None
            if command is not None:
                self.process_command(command)
            for serial in sorted(self.active_devices):
                self.poll_status(serial)
            self.failures = 0
            self.next_cloud = self.clock() + self.POLL_INTERVAL
            if self.last_diagnostic is not None:
                LOG.info("Bridge resumed: code=cloud_cycle_recovered.")
            self.last_diagnostic = None
        except (CloudError, OSError, ValueError, TypeError) as error:
            self._offline()
            self.failures = min(self.failures + 1, 5)
            self.next_cloud = self.clock() + min(self.MAX_BACKOFF, 20 * 2**self.failures)
            if isinstance(error, CloudError):
                code = safe_diagnostic(error.args[0] if error.args else None)
                if code == "auth_locked_operator_action_required":
                    code = safe_diagnostic(self.guard.state["reason"])
            else:
                code = (
                    "private_storage_error"
                    if isinstance(error, OSError)
                    else "internal_value_error"
                )
            diagnostic = (self.operation, code)
            if diagnostic != self.last_diagnostic:
                LOG.warning("Bridge paused: operation=%s code=%s.", *diagnostic)
                self.last_diagnostic = diagnostic

    def run(self, stop=None):
        stop = stop if stop is not None else threading.Event()
        self.mqtt_client.reconnect_delay_set(min_delay=5, max_delay=60)
        self.mqtt_client.connect_async(
            os.getenv("MQTT_HOST", "core-mosquitto"), int(os.getenv("MQTT_PORT", "1883")), 60
        )
        self.mqtt_client.loop_start()
        LOG.info(
            "Bridge running; cloud=%s, commands=%s. No automatic lockout reset.",
            self.options.get("cloud_enabled", False),
            self.options.get("commands_enabled", False),
        )
        try:
            while not stop.is_set():
                try:
                    self.tick()
                except Exception:
                    self._offline()
                    try:
                        self.guard.block("unexpected_internal_error")
                    except CloudError:
                        pass
                    LOG.error("Bridge paused: unexpected_internal_error; operator action required.")
                stop.wait(1)
        finally:
            self._offline()
            self.mqtt_client.publish(
                "thermowatt/bridge/availability", "offline", qos=1, retain=True
            )
            self.mqtt_client.disconnect()
            self.mqtt_client.loop_stop()
            self.session.close()


def load_options(path):
    options = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(options, dict):
        raise ValueError
    for key in ("email", "password"):
        if not isinstance(options.get(key, ""), str):
            raise ValueError
    for key in ("cloud_enabled", "commands_enabled"):
        if type(options.get(key, False)) is not bool:
            raise ValueError
    generation = options.get("auth_retry_generation", 0)
    if type(generation) is not int or generation < 0:
        raise ValueError
    return options


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    try:
        bridge = MyThermowattBridge(load_options("/data/options.json"))
    except Exception:
        LOG.error(
            "Startup paused: configuration or private storage invalid. No cloud requests sent."
        )
        stop.wait()
        return
    bridge.run(stop)


if __name__ == "__main__":
    main()
