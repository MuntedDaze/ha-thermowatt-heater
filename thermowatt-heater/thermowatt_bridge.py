"""MyThermowatt bridge: cloud opt-in, persistent auth guard, observed MQTT state."""

import hashlib
from datetime import datetime, timezone
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

from thermowatt_read_only import RequestUsage, daily_limit, poll_seconds

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
        "cloud_daily_limit",
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


# MODE payloads that name the only acceptable Manual target. 70 °C is the
# owner-approved storage target; nothing else is accepted in guarded form.
GUARDED_PAYLOADS = {"Manual:70": 70}
PLAIN_PAYLOADS = {"off", "Off", "Eco", "Auto", "Manual"}
# Command policy. "automation" (the default) accepts EXACTLY the two operations
# the hot-water controller needs; every other command (temperature writes, Eco,
# Auto/Schedule, plain Manual, Holiday, malformed payloads) is refused before
# any cloud request. "legacy" restores the full 1.3.8 command set and must be
# chosen explicitly. Read-only monitoring is identical under both.
COMMAND_POLICIES = ("automation", "legacy")
# Three-state transitions (1.3.13): "<target>@<prior>". The controller states
# the exact state it expects to leave; the FRESH status (<= 60 s) must show it,
# or the command is refused with no request (an owner change in the app is
# never overwritten). Targets: software OFF, Manual 45 °C, Manual 70 °C.
TRANSITIONS = {
    "off@45": ("off", 45),
    "off@70": ("off", 70),
    "Manual:45@off": (45, "off"),
    "Manual:45@70": (45, 70),
    "Manual:70@off": (70, "off"),
    "Manual:70@45": (70, 45),
}
# The 1.3.11 forms stay accepted for the installed controller: Manual:70 from
# OFF only, off from Manual 70 only.
AUTOMATION_COMMANDS = {("MODE", "Manual:70"), ("MODE", "off")} | {
    ("MODE", payload) for payload in TRANSITIONS
}
# Software OFF. Cmd 8 is what the owner's heater actually reports when switched
# OFF from Manual (observed in T3, 1.3.10). Cmd 16 was the original assumption
# and is retained for compatibility; it may be OFF entered from another mode but
# has not been observed. Any other code is never treated as OFF.
OFF_CODES = frozenset({8, 16})
# Freshness of the confirmed status required to authorise a heater command.
STATUS_MAX_AGE = 60
# A queued command must be at most this old when it is taken from the queue...
COMMAND_MAX_AGE = 30
# ...and at most this old after a pre-command status refresh, just before POST.
COMMAND_MAX_AGE_AFTER_REFRESH = 75
# Bounded command confirmation (1.3.11). The cloud may report a command's new
# mode some time after the POST is accepted, so the immediate read showing the
# OLD mode is not a failure. After it, at most these follow-up reads are made
# (seconds after the POST); every other status read (a background poll) is also
# checked. The POST itself is NEVER repeated. With no confirmation by the
# deadline the command ends as not_confirmed_within_limit (owner action).
CONFIRM_FOLLOWUPS = (60, 300)
CONFIRM_DEADLINE = CONFIRM_FOLLOWUPS[-1] + 60
COMMAND_STATE_VERSION = 1
# 1.3.13: no status read immediately after the POST. In T3b, T3c and Stage C it
# always showed the OLD mode (the cloud applies a change after about 2-63 s), so
# it cost a request and proved nothing. The 60 s follow-up is the first read.
# Clock-aligned background polls (1.3.13): due at multiples of the interval
# (with 30 minutes, :00 and :30; Tasmania's UTC offset is a whole number of
# hours). A due poll is skipped, and the schedule NOT moved, when any status
# read of that heater happened within this many seconds (a command refresh, a
# confirmation or an on-demand read): it already supplied the reading.
POLL_REUSE_SECONDS = 180
# Proactive token refresh (1.3.13; authentication change, owner approval). The
# access token lasts under 30 minutes (every 30-minute poll in 1.3.11 was GET
# 401 -> refresh -> GET). A request made when the token is at least this old
# refreshes FIRST, saving the doomed 401 GET. The guard, its retry limits and
# the 5-minute refresh cooldown are unchanged; a 401 still refreshes once.
PROACTIVE_REFRESH_AGE = 1200


class MyThermowattBridge:
    API_KEY = _APP_API_KEY  # Existing embedded app identifier; never log it.
    BASE_URL = "https://myapp-connectivity.com/api/v1"
    COMMAND_INTERVAL = 20
    HTTP_TIMEOUT = (10, 20)
    MAX_BACKOFF = 300
    MAX_CLOUD_BACKOFF = 86400
    DEMAND_MIN_SPACING = 300
    STATUS_FIELDS = ("T_Avg", "T_SetPoint", "Cmd", "WaterHeaterSts")
    MODES = {9: "Manual", 3: "Eco", 17: "Schedule", 65: "Holiday", 8: "Off", 16: "Off"}
    # Pre-command status refresh bounds (1.3.10). At most one refresh per
    # command, never sooner than this after any earlier status read of the
    # heater, and at most this many per rolling 24 hours.
    COMMAND_REFRESH_MIN_SPACING = 60
    COMMAND_REFRESH_DAILY_LIMIT = 24

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
        self.poll_interval = poll_seconds(options)
        self.min_cloud_retry = options.get("min_cloud_retry_minutes", 60) * 60
        self.request_counts = {
            kind: 0
            for kind in ("password_login", "token_refresh", "discovery", "status", "command")
        }
        self.clock = clock
        self.monotonic = monotonic
        self.data_dir = Path(data_dir)
        self.usage = RequestUsage(self.data_dir / "request_usage.json", clock, atomic_json)
        self.read_category = "status"
        self.command_refreshes = []  # monotonic times of pre-command refreshes
        # Outcome of the most recent MQTT command (fixed codes only, no payload
        # bodies). Lets a local executor see refusals without another cloud read.
        self.last_command = None
        # The single command whose outcome is not yet known (persisted, so a
        # restart neither forgets nor re-sends it) and the last command refused
        # because of it (kept apart so the pending record is never overwritten).
        self.pending = None
        self.refused_while_pending = None
        self.command_state_path = self.data_dir / "command_state.json"
        self._load_command_state()
        self.last_success = {}
        self.last_error = safe_diagnostic(self.usage.last_error) if self.usage.last_error else None
        self.quota_signal = None
        self.cloud_health = "starting" if options.get("cloud_enabled", False) else "disabled"
        self.next_diagnostics = 0
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
        self.next_poll = 0
        self.next_background = {}
        self.last_status_attempt = {}
        self.refresh_requested = set()
        self.refresh_lock = threading.Lock()
        self.read_this_tick = set()  # serials whose status was read in this tick
        self.failures = self.usage.failures
        if self.usage.cooldown_until > self.clock():
            self.next_cloud = self.next_poll = self.usage.cooldown_until
            self.cloud_health = "backoff"
        self.discovered = False
        self.last_diagnostic = None
        self.operation = "authentication_guard"
        self.token_obtained_at = None  # in memory; see _token_age after a restart
        # Not options: always True / False in the app. Tests written for 1.3.11
        # change them to replay their scripted request sequences.
        self.proactive_refresh = True
        self.immediate_confirmation_read = False

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
        kind = {
            "/login": "password_login",
            "/refresh": "token_refresh",
            "/user-info": "discovery",
            "/status": "status",
        }.get(endpoint, "command")
        self.request_counts[kind] += 1
        usage_category = self.read_category if kind == "status" else kind
        self.usage.record(usage_category)
        LOG.info(
            "Cloud request attempt: kind=%s count_since_start=%s total_since_start=%s. "
            "usage_category=%s lifetime_attempts=%s.",
            kind,
            self.request_counts[kind],
            sum(self.request_counts.values()),
            usage_category,
            self.usage.total,
        )
        self.quota_signal = None
        response = self.session.request(
            method,
            f"{self.BASE_URL}{endpoint}",
            headers=headers,
            timeout=self.HTTP_TIMEOUT,
            verify=True,
            allow_redirects=False,
            **kwargs,
        )
        if response.status_code == 429:
            self.quota_signal = "cloud_http_429"
        else:
            try:
                if daily_limit(response.json()):
                    self.quota_signal = "cloud_daily_limit"
            except (ValueError, TypeError):
                pass
        return response

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
            self.token_obtained_at = self.clock()
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

    def _token_age(self):
        """Seconds since the access token was issued, or None when unknown. After
        a restart it is derived from the persisted refresh cooldown deadline."""
        if self.token_obtained_at is not None:
            return self.clock() - self.token_obtained_at
        state = self.guard.state
        if state["action"] == "refresh" and state["next_retry"] > 0:
            return self.clock() - (state["next_retry"] - AuthGuard.REFRESH_COOLDOWN)
        return None

    def _token_due_for_refresh(self):
        """Refresh BEFORE a request only when the token is old (or of unknown
        age) and the guard's refresh cooldown has passed. Never in a loop: a
        just-refreshed token is never due."""
        if not self.proactive_refresh:
            return False
        if self.guard.state["mode"] != "authorized" or not self.guard.state.get("refresh_token"):
            return False
        if self.clock() < self.guard.state["next_retry"]:
            return False
        age = self._token_age()
        return age is None or age >= PROACTIVE_REFRESH_AGE

    def request(self, method, endpoint, serial=None, **kwargs):
        self.guard.check()
        if not self.options.get("cloud_enabled", False):
            raise AuthBlocked("cloud_disabled")
        if self.guard.state["mode"] != "authorized":
            raise CloudError("authentication_not_ready")
        if self.clock() < self.next_cloud:
            raise CloudError("cloud_backoff")
        if self._token_due_for_refresh():
            operation = self.operation
            self.refresh_session()
            self.operation = operation
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
        if daily_limit(body):
            raise CloudError("cloud_daily_limit")
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
        with self.refresh_lock:
            self.refresh_requested.clear()
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
            "mode_state_template": "{{ {'9':'performance','3':'eco','8':'off','16':'off'}.get(value_json.result.Cmd | int | string, none) }}",
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
        for key, label, extra in (
            ("last_successful_poll", "Last successful poll", {"device_class": "timestamp"}),
            (
                "status_age_seconds",
                "Status age",
                {"device_class": "duration", "unit_of_measurement": "s"},
            ),
            ("cloud_health", "Cloud health", {}),
            ("last_error", "Last cloud error", {}),
            (
                "request_attempts",
                "Cloud request attempts (local lifetime)",
                {"state_class": "total_increasing"},
            ),
        ):
            diagnostic = {
                "unique_id": f"thermowatt_{serial}_{key}",
                "name": label,
                "state_topic": f"P/{serial}/DIAGNOSTICS",
                "value_template": "{{ value_json."
                + key
                + " if value_json."
                + key
                + " is not none else 'None' }}",
                "json_attributes_topic": f"P/{serial}/DIAGNOSTICS",
                "entity_category": "diagnostic",
                "device": device,
                "availability": [{"topic": "thermowatt/bridge/availability"}],
                **extra,
            }
            self._publish_read_only(f"homeassistant/sensor/{serial}/{key}/config", diagnostic)

    def _publish_read_only(self, topic, payload):
        try:
            self.mqtt_client.publish(topic, json.dumps(payload), retain=True)
        except (OSError, ValueError, TypeError, RuntimeError):
            LOG.warning("Read-only diagnostics unavailable: code=mqtt_publish_failed.")

    def publish_diagnostics(self, force=False):
        if not force and self.clock() < self.next_diagnostics:
            return
        self.next_diagnostics = self.clock() + 30
        if not self.options.get("cloud_enabled", False):
            health = "disabled"
        elif self.guard.state["mode"] == "blocked" and self.cloud_health != "quota_limited":
            health = "auth_locked"
        else:
            health = self.cloud_health
        for serial in self.config["devices"]:
            timestamp = self.last_success.get(serial)
            payload = {
                "last_successful_poll": datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
                if timestamp is not None
                else None,
                "status_age_seconds": max(0, int(self.clock() - timestamp))
                if timestamp is not None
                else None,
                "cloud_health": health,
                "last_error": self.last_error or "none",
                "request_attempts": self.usage.total,
                "request_categories": dict(self.usage.counts),
                "accounting_since": self.usage.since,
                "accounting_persistent": self.usage.persistent,
                "accounting_complete": self.usage.complete,
                "auth_guard_mode": self.guard.state["mode"],
                "cooldown_remaining_seconds": max(0, int(self.usage.cooldown_until - self.clock())),
                "consumption_basis": "local_attempts_not_vendor_consumption",
                "poll_interval_seconds": self.poll_interval,
                "consecutive_failures": self.failures,
                "on_demand_refresh_enabled": self.options.get("on_demand_refresh_enabled", False),
                "commands_enabled": bool(self.options.get("commands_enabled", False)),
                "command_policy": self.options.get("command_policy", "automation"),
                "last_command": dict(self.last_command) if self.last_command else None,
                "command_status_refreshes_24h": self._recent_command_refreshes(),
                "command_status_refresh_limit_24h": self.COMMAND_REFRESH_DAILY_LIMIT,
                "command_confirmation_pending": self.pending is not None,
                "command_confirmation_followups_seconds": list(CONFIRM_FOLLOWUPS),
                # 1.3.13: the three-state transitions this bridge accepts (the
                # controller requires them) and the polling schedule.
                "command_transitions": sorted(TRANSITIONS),
                "poll_schedule": "clock_aligned",
                "refused_while_pending": dict(self.refused_while_pending)
                if self.refused_while_pending
                else None,
            }
            self._publish_read_only(f"P/{serial}/DIAGNOSTICS", payload)

    def _subscribe(self, serial):
        # MQTT v5 preserves RETAIN on live retained writes as well as replay.
        self.mqtt_client.subscribe(
            f"P/{serial}/CMD/#", options=mqtt.SubscribeOptions(qos=0, retainAsPublished=True)
        )
        if self.options.get("on_demand_refresh_enabled", False):
            self.mqtt_client.subscribe(
                f"P/{serial}/refresh", options=mqtt.SubscribeOptions(qos=0, retainAsPublished=True)
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
            self.publish_diagnostics(force=True)

    def on_mqtt_disconnect(self, client, userdata, flags, reason_code, properties):
        self.mqtt_connected.clear()

    def on_mqtt_message(self, client, userdata, msg):
        # Callback thread only queues. It never touches HTTP or authentication.
        if msg.retain or not self.mqtt_connected.is_set():
            return
        parts = msg.topic.split("/")
        if len(parts) == 3 and parts[0] == "P" and parts[2] == "refresh":
            serial = parts[1]
            if (
                msg.payload == b"refresh"
                and self._demand_allowed()
                and serial in self.active_devices
                and self.monotonic() - self.last_status_attempt.get(serial, float("-inf"))
                >= self.DEMAND_MIN_SPACING
            ):
                with self.refresh_lock:
                    self.refresh_requested.add(serial)
            return
        if not self.options.get("commands_enabled", False):
            return
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

    def _demand_allowed(self):
        return (
            self.options.get("on_demand_refresh_enabled", False)
            and self.options.get("cloud_enabled", False)
            and self.mqtt_connected.is_set()
            and self.discovered
            and self.guard.state["mode"] == "authorized"
            and not self.guard.failed_storage
            and self.usage.complete
            and self.clock() >= self.usage.cooldown_until
            and self.cloud_health not in {"backoff", "quota_limited"}
        )

    def _take_demand(self):
        with self.refresh_lock:
            pending = self.refresh_requested & self.active_devices
            self.refresh_requested.clear()
        if not self._demand_allowed():
            return set()
        return {
            serial
            for serial in pending
            if self.monotonic() - self.last_status_attempt.get(serial, float("-inf"))
            >= self.DEMAND_MIN_SPACING
        }

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

    def poll_status(self, serial, category=None, operation=None):
        self.last_status_attempt[serial] = self.monotonic()
        if category is None:
            category = "confirmation" if self.operation == "heater_command" else "status"
        self.read_category = category
        self.operation = operation or (
            "command_status_refresh" if category == "command_refresh" else "status_poll"
        )
        try:
            result = self._result(self.request("GET", "/status", serial))
        finally:
            self.read_category = "status"
        if any(key not in result for key in self.STATUS_FIELDS):
            raise CloudError("status_fields_missing")
        try:
            values = {key: float(result[key]) for key in self.STATUS_FIELDS}
        except (TypeError, ValueError, OverflowError):
            raise CloudError("status_values_non_numeric") from None
        if not all(math.isfinite(v) for v in values.values()):
            raise CloudError("status_values_non_finite")
        if values["Cmd"] < 0 or values["Cmd"] != int(values["Cmd"]):
            raise CloudError("status_mode_invalid")
        # While the heater is software OFF (Cmd 8 observed, 16 retained) the
        # cloud's setpoint is not necessarily an operating target (T3 saw 70
        # retained). An out-of-range value then must not fail every poll (that
        # would back the bridge off for hours while the heater stays off). It is
        # published but flagged invalid, and no command may reuse it.
        setpoint_valid = 20 <= values["T_SetPoint"] <= 75
        is_off = int(values["Cmd"]) in OFF_CODES
        if not 0 <= values["T_Avg"] <= 100 or (not setpoint_valid and not is_off):
            raise CloudError("status_temperature_out_of_range")
        if values["WaterHeaterSts"] < 0 or values["WaterHeaterSts"] != int(
            values["WaterHeaterSts"]
        ):
            raise CloudError("status_heater_state_invalid")
        safe = {key: result[key] for key in self.STATUS_FIELDS}
        safe["vendor_mode"] = self.MODES.get(int(values["Cmd"]), "Unknown")
        safe["setpoint_valid"] = setpoint_valid
        # WaterHeaterSts is an opaque diagnostic value, not proven element feedback.
        safe["heating"] = None
        self.confirmed[serial] = (self.monotonic(), values)
        self.read_this_tick.add(serial)
        self.mqtt_client.publish(f"P/{serial}/STATUS", json.dumps({"result": safe}), retain=True)
        self._availability(serial, True)
        self.last_success[serial] = self.clock()
        self.cloud_health = "ok"
        self.publish_diagnostics(force=True)
        # Every fresh read after a command's POST is evidence for its outcome.
        self._observe_pending(serial, values)
        return values

    @staticmethod
    def _safe_payload(payload):
        known = payload in GUARDED_PAYLOADS or payload in PLAIN_PAYLOADS or payload in TRANSITIONS
        return payload if known else "other"

    def _command_result(self, kind, payload, result, refresh=None, error=None, extra=None):
        safe = self._safe_payload(payload)
        self.last_command = {
            "kind": kind if kind in {"MODE", "TEMP"} else "other",
            "payload": safe if kind == "MODE" else "temperature",
            "result": result,
            # Pre-command status read (1.3.10): not_needed (status was fresh),
            # in_progress, refreshed, failed, or refused (no read attempted).
            # None when the command was dropped or refused before status was
            # considered.
            "status_refresh": refresh,
            "at": datetime.fromtimestamp(self.clock(), timezone.utc).isoformat(),
        }
        if error is not None:
            self.last_command["error"] = safe_diagnostic(error)
        if extra:
            self.last_command.update(extra)
        self.publish_diagnostics(force=True)

    # ------------------------------------------------------------------ confirmation
    def _iso(self, moment):
        return datetime.fromtimestamp(moment, timezone.utc).isoformat()

    def _load_command_state(self):
        try:
            if not self.command_state_path.exists():
                return
            if self.command_state_path.stat().st_size > 8192:
                raise ValueError
            data = json.loads(self.command_state_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("version") != COMMAND_STATE_VERSION:
                raise ValueError
            pending, last = data.get("pending"), data.get("last_command")
            if pending is not None:
                if not isinstance(pending, dict) or not self.valid_serial(pending.get("serial")):
                    raise ValueError
                for key in ("posted_at",):
                    if type(pending.get(key)) not in (int, float):
                        raise ValueError
                for key in ("followups_done", "reads", "prior_cmd"):
                    if type(pending.get(key)) is not int:
                        raise ValueError
                if not isinstance(pending.get("expect_cmd"), list):
                    raise ValueError
            if last is not None and not isinstance(last, dict):
                raise ValueError
            self.pending, self.last_command = pending, last
            os.chmod(self.command_state_path, 0o600)
            if pending is not None:
                LOG.warning(
                    "Restart with a command awaiting confirmation: it is never re-sent; "
                    "the next status reads decide its outcome."
                )
        except (OSError, ValueError, TypeError, KeyError):
            LOG.warning("Command state: code=command_state_invalid; ignored.")

    def _save_command_state(self):
        atomic_json(
            self.command_state_path,
            {
                "version": COMMAND_STATE_VERSION,
                "pending": self.pending,
                "last_command": self.last_command,
            },
        )

    def _pending_result(self, result, observed_mode=None, error=None, pending=None):
        pending = pending or self.pending
        extra = {
            "status_reads": pending["reads"],
            "followups_done": pending["followups_done"],
            "posted_at": self._iso(pending["posted_at"]),
            "confirm_by": self._iso(pending["posted_at"] + CONFIRM_DEADLINE),
        }
        if observed_mode is not None:
            extra["observed_mode"] = observed_mode
        self._command_result(
            pending["kind"],
            pending["payload"],
            result,
            refresh=pending["refresh"],
            error=error,
            extra=extra,
        )

    def _finish_pending(self, result, observed_mode=None, error=None):
        # Cleared first, so the published diagnostics never show a terminal
        # outcome with the command still marked pending.
        pending, self.pending = self.pending, None
        self._pending_result(result, observed_mode, error, pending=pending)
        try:
            self._save_command_state()
        except OSError:
            LOG.warning("Command state: code=command_state_storage_unavailable.")
        if result == "observed_in_status":
            LOG.info("Requested value observed in cloud status.")
        else:
            LOG.warning("Command outcome: code=%s. No retry; owner action may be required.", result)

    def _observe_pending(self, serial, values):
        pending = self.pending
        if pending is None or pending["serial"] != serial:
            return
        pending["reads"] += 1
        cmd, setpoint = int(values["Cmd"]), values["T_SetPoint"]
        observed_mode = self.MODES.get(cmd, "Unknown")
        wanted = pending["expect_setpoint"]
        if cmd in pending["expect_cmd"] and (wanted is None or setpoint == wanted):
            self._finish_pending("observed_in_status", observed_mode)
        elif cmd == pending["prior_cmd"] and (
            cmd in OFF_CODES or setpoint == pending["prior_setpoint"]
        ):
            # Still the state before the POST: the cloud may not have applied
            # it YET. Not success, not failure; wait for a bounded follow-up.
            if pending["followups_done"] < len(CONFIRM_FOLLOWUPS):
                LOG.warning(
                    "Command not confirmed yet: status still shows the previous state; "
                    "awaiting a bounded follow-up read. No retry."
                )
                self._pending_result("awaiting_confirmation", observed_mode)
                self._save_command_state_quietly()
            else:
                self._finish_pending("not_confirmed_within_limit", observed_mode)
        else:
            # Neither the old nor the requested state (e.g. an app change).
            self._finish_pending("unexpected_state_after_command", observed_mode)

    def _save_command_state_quietly(self):
        try:
            self._save_command_state()
        except OSError:
            LOG.warning("Command state: code=command_state_storage_unavailable.")

    def _expire_pending(self):
        pending = self.pending
        if pending is not None and self.clock() >= pending["posted_at"] + CONFIRM_DEADLINE:
            self._finish_pending("not_confirmed_within_limit", error=pending.get("error"))

    def _followup_due(self):
        pending = self.pending
        if pending is None or pending["serial"] not in self.active_devices:
            return None
        done = pending["followups_done"]
        if done >= len(CONFIRM_FOLLOWUPS):
            return None
        if self.clock() < pending["posted_at"] + CONFIRM_FOLLOWUPS[done]:
            return None
        return pending["serial"]

    def _recent_command_refreshes(self):
        horizon = self.monotonic() - 86400
        self.command_refreshes = [moment for moment in self.command_refreshes if moment > horizon]
        return len(self.command_refreshes)

    def _status_is_fresh(self, serial):
        confirmed = self.confirmed.get(serial)
        return confirmed is not None and self.monotonic() - confirmed[0] <= STATUS_MAX_AGE

    def _refresh_refusal(self, serial):
        """Why a pre-command status read may NOT be attempted, or None."""
        if self.guard.failed_storage or self.guard.state["mode"] != "authorized":
            return "refused_auth_not_ready"
        if self.cloud_health == "quota_limited":
            return "refused_cloud_quota_limited"
        if self.clock() < self.usage.cooldown_until:
            return "refused_cloud_backoff"
        if (
            self.monotonic() - self.last_status_attempt.get(serial, float("-inf"))
            < self.COMMAND_REFRESH_MIN_SPACING
        ):
            return "refused_status_refresh_too_soon"
        if self._recent_command_refreshes() >= self.COMMAND_REFRESH_DAILY_LIMIT:
            return "refused_status_refresh_limit"
        return None

    @staticmethod
    def _static_command(kind, payload):
        """Validate the command text alone, before any cloud request.

        Returns (endpoint, temperature) or a refusal code string. ``None`` means
        silently ignore (the historic handling of malformed temperatures)."""
        if kind == "TEMP":
            try:
                temperature = float(payload)
            except ValueError:
                return None
            if (
                not math.isfinite(temperature)
                or not temperature.is_integer()
                or not 20 <= temperature <= 75
            ):
                return None
            return ("/manual", temperature)
        if kind == "MODE" and payload in GUARDED_PAYLOADS:
            return ("/manual", GUARDED_PAYLOADS[payload])
        if kind == "MODE" and payload in TRANSITIONS:
            target = TRANSITIONS[payload][0]
            return ("/off", None) if target == "off" else ("/manual", target)
        endpoint = {
            "off": "/off",
            "Off": "/off",
            "Eco": "/eco",
            "Auto": "/auto",
            "Manual": "/manual",
        }.get(payload)
        # Holiday used to invent a 30-day end date. Never invent schedule writes.
        if kind != "MODE" or not endpoint:
            return "refused_invalid_command"
        return (endpoint, None)

    def process_command(self, command):
        """Authorise and execute ONE queued command, never more than once.

        Order: configuration, MQTT, queue age, device identity, command policy
        and command text (no cloud request for any of these); then a fresh
        status (<= 60 s) is required. If the confirmed status is older, at most
        ONE bounded status read is made for this command, only when the cloud
        health, authentication guard and refresh budget allow it. Every target
        and owner-override rule is then evaluated against that fresh status.
        Nothing is ever retried, and a failed or refused read never executes."""
        issued, serial, kind, payload = command
        if not self.options.get("commands_enabled", False):
            return
        if self.pending is not None:
            # One uncertain command at a time. Duplicates (an MQTT redelivery,
            # a repeated publish) and any other command wait for the outcome.
            # Recorded apart from last_command, which keeps the pending record.
            LOG.warning("Command refused: a previous command awaits confirmation. No request.")
            safe = self._safe_payload(payload)
            self.refused_while_pending = {
                "kind": kind if kind in {"MODE", "TEMP"} else "other",
                "payload": safe if kind == "MODE" else "temperature",
                "result": "refused_confirmation_pending",
                "at": self._iso(self.clock()),
            }
            self.publish_diagnostics(force=True)
            return
        reason = None
        if not self.mqtt_connected.is_set():
            reason = "dropped_mqtt_disconnected"
        elif self.monotonic() - issued > COMMAND_MAX_AGE:
            reason = "dropped_command_older_than_30s"
        elif serial not in self.active_devices:
            reason = "dropped_unknown_device"
        if reason:
            self._command_result(kind, payload, reason)
            return
        policy = self.options.get("command_policy", "automation")
        if policy != "legacy" and (kind, payload) not in AUTOMATION_COMMANDS:
            LOG.warning("Command refused by the automation command policy. No request sent.")
            self._command_result(kind, payload, "refused_by_policy")
            return
        static = self._static_command(kind, payload)
        if static is None:
            return
        if isinstance(static, str):
            self._command_result(kind, payload, static)
            return
        endpoint, temperature = static

        refresh = "not_needed"
        if not self._status_is_fresh(serial):
            reason = self._refresh_refusal(serial)
            if reason:
                LOG.warning(
                    "Command refused: status older than %ss and no refresh permitted "
                    "(code=%s). No request sent.",
                    STATUS_MAX_AGE,
                    reason,
                )
                self._command_result(kind, payload, reason, refresh="refused")
                return
            self.command_refreshes.append(self.monotonic())
            LOG.info("Command needs fresh status: one pre-command status read.")
            # Published BEFORE the read: a consumer (the controller) then knows
            # the STATUS that follows is the pre-command read, not an outcome.
            self._command_result(kind, payload, "refreshing_status", refresh="in_progress")
            try:
                self.poll_status(serial, category="command_refresh")
            except CloudError as error:
                code = self.quota_signal or (error.args[0] if error.args else None)
                LOG.warning("Pre-command status read failed. Command not sent. No retry.")
                self._command_result(
                    kind, payload, "refused_status_refresh_failed", refresh="failed", error=code
                )
                raise
            refresh = "refreshed"
            if self.monotonic() - issued > COMMAND_MAX_AGE_AFTER_REFRESH:
                self._command_result(
                    kind, payload, "dropped_command_expired_during_refresh", refresh=refresh
                )
                return
            if not self._status_is_fresh(serial):  # Defensive: never act on old state.
                self._command_result(kind, payload, "refused_status_not_fresh", refresh=refresh)
                return
        status = self.confirmed[serial][1]
        mode, observed = int(status["Cmd"]), status["T_SetPoint"]
        # Automation policy: the controller's view may be up to one poll
        # interval old, so the FRESH status must still show the exact state the
        # command is meant to leave (OFF for Manual:70, Manual 70 for off).
        automation = policy != "legacy"

        arguments, expected = {}, None
        if payload in TRANSITIONS and kind == "MODE":
            target, prior = TRANSITIONS[payload]
            is_off, is_manual = mode in OFF_CODES, mode == 9

            def shows(state):
                return is_off if state == "off" else is_manual and observed == state

            if shows(target):
                self._command_result(kind, payload, "already_in_requested_state", refresh=refresh)
                return
            if not shows(prior):
                # Not the state the controller left the heater in: the owner (or
                # something else) changed it. Never overwritten.
                reason = (
                    "refused_mode_mismatch"
                    if (prior == "off") != is_off or not (is_off or is_manual)
                    else "refused_target_mismatch"
                )
                LOG.warning("Transition refused: heater not in the stated prior state. No request.")
                self._command_result(kind, payload, reason, refresh=refresh)
                return
            if target == "off":
                arguments, expected = {"data": ""}, (OFF_CODES, None)
            else:
                arguments = {"json": {"T_SetPoint": int(target)}}
                expected = ({9}, target)
        elif kind == "TEMP":
            # /manual changes mode too: never change temperature from other modes.
            if mode != 9:
                return
            arguments = {"json": {"T_SetPoint": int(temperature)}}
            expected = ({9}, temperature)
        elif payload in GUARDED_PAYLOADS:
            # Guarded Manual: enter Manual ONLY at the stated target, sent
            # explicitly. Accepted when the fresh observed target already equals
            # it, or when the heater is software OFF and reports NO usable
            # target (outside 20-75 °C). A usable target other than 70 (in any
            # mode, OFF included) may be a deliberate owner setting: it is
            # refused, never silently "corrected" to 70.
            off_without_target = mode in OFF_CODES and not 20 <= observed <= 75
            if observed != temperature and not off_without_target:
                LOG.warning("Guarded Manual refused: observed target differs. No request sent.")
                self._command_result(kind, payload, "refused_target_mismatch", refresh=refresh)
                return
            if mode == 9 and observed == temperature:
                self._command_result(kind, payload, "already_in_requested_state", refresh=refresh)
                return
            if automation and mode not in OFF_CODES:
                # The controller resumes ONLY from OFF. Schedule, Eco, Holiday or
                # an unknown mode at 70 is the owner's choice (perhaps made in
                # the app since the controller last saw the heater): refused.
                LOG.warning("Guarded Manual refused: heater not OFF. No request sent.")
                self._command_result(kind, payload, "refused_mode_mismatch", refresh=refresh)
                return
            arguments = {"json": {"T_SetPoint": int(temperature)}}
            expected = ({9}, temperature)  # confirmed only as Manual AT 70
        else:
            if payload == "off" and mode in OFF_CODES:
                # Already OFF: a second write would only cost a request.
                self._command_result(kind, payload, "already_in_requested_state", refresh=refresh)
                return
            if automation and payload == "off" and (mode != 9 or observed != 70):
                # The controller parks ONLY from Manual 70 °C. Any other mode or
                # target is the owner's choice and is never switched OFF.
                reason = "refused_mode_mismatch" if mode != 9 else "refused_target_mismatch"
                LOG.warning("Park refused: heater not in Manual 70. No request sent.")
                self._command_result(kind, payload, reason, refresh=refresh)
                return
            expected = (
                {
                    "off": OFF_CODES,
                    "Off": OFF_CODES,
                    "Eco": {3},
                    "Auto": {17},
                    "Manual": {9},
                }[payload],
                None,
            )
            if payload == "Manual":
                if not 20 <= observed <= 75:
                    # Plain Manual reuses the observed setpoint; never send an
                    # invalid one (possible only while OFF). Use Manual:70.
                    self._command_result(
                        kind, payload, "refused_setpoint_unavailable", refresh=refresh
                    )
                    return
                arguments = {"json": {"T_SetPoint": int(observed)}}
                expected = ({9}, observed)
            else:
                arguments = {"data": ""}
        # Persist the uncertain command BEFORE the POST: a crash or restart from
        # here on never re-sends it, and the next reads decide its outcome.
        self.pending = {
            "serial": serial,
            "kind": kind,
            "payload": payload,
            "refresh": refresh,
            "expect_cmd": sorted(expected[0]),
            "expect_setpoint": expected[1],
            "prior_cmd": mode,
            "prior_setpoint": observed,
            "posted_at": self.clock(),
            "followups_done": 0,
            "reads": 0,
        }
        try:
            self._pending_result("submitting")
            self._save_command_state()
        except OSError:
            self.pending = None
            self._command_result(
                kind, payload, "refused_command_state_unavailable", refresh=refresh
            )
            LOG.warning("Command refused: command state cannot be stored. No request sent.")
            return
        self.operation = "heater_command"
        self._availability(serial, False)
        try:
            response = self.request("POST", endpoint, serial, **arguments)
        except CloudError as error:
            # Unknown whether the cloud acted (e.g. a timeout after delivery):
            # never re-sent; the bounded reads decide, or the deadline does.
            code = self.quota_signal or (error.args[0] if error.args else None)
            self._pending_result("awaiting_confirmation", error=code)
            self._save_command_state_quietly()
            raise
        try:
            acknowledgement = response.json()
        except ValueError:
            acknowledgement = None  # No documented success envelope; observation still required.
        if isinstance(acknowledgement, dict) and (
            acknowledgement.get("success") is False or acknowledgement.get("error")
        ):
            self._finish_pending("rejected_by_cloud")
            raise CloudError("command_rejected")
        LOG.info("Command submitted; the first confirmation read follows in 60 s.")
        self._pending_result("submitted_awaiting_status")
        self._save_command_state_quietly()
        if self.immediate_confirmation_read:  # pre-1.3.13 sequencing (tests only)
            self.poll_status(serial, category="confirmation")
            return
        # No immediate read (1.3.13): the last confirmed status is still the
        # latest known state, so the heater is available again with it; the
        # pending record tells consumers the outcome is not known yet.
        self._availability(serial, True)

    def tick(self):
        """One bounded iteration; authentication failure idles instead of exiting."""
        self.publish_diagnostics()
        # Needs no request: a command whose confirmation window has passed ends
        # as not confirmed even while the cloud is unreachable or locked.
        self._expire_pending()
        if self.mqtt_reconnected.is_set():
            self.mqtt_reconnected.clear()
            self._offline()
            self.discovered = False
        if not self.options.get("cloud_enabled", False) or not self.mqtt_connected.is_set():
            self._offline()
            return
        polling = False
        self.read_this_tick = set()
        try:
            self.operation = "authentication_guard"
            self.guard.check()
            if self.clock() < self.next_cloud:
                return
            self.login()
            poll_due = self.clock() >= self.next_poll
            polling = poll_due
            if poll_due and not self.discovered:
                self.discover_devices()
            polling = False
            try:
                command = self.commands.get_nowait()
            except queue.Empty:
                command = None
            if command is not None:
                self.process_command(command)
            followup = self._followup_due()
            if followup is not None and followup not in self.read_this_tick:
                self.pending["followups_done"] += 1
                self._save_command_state_quietly()
                LOG.info("Command awaiting confirmation: one bounded follow-up status read.")
                self.poll_status(
                    followup, category="confirmation", operation="command_confirmation"
                )
            targets = self._take_demand()
            due = set()
            if poll_due:
                due = {
                    serial
                    for serial in self.active_devices
                    if self.next_background.get(serial, 0) <= self.clock()
                }
            if poll_due or targets:
                polling = True
                for serial in sorted(targets | due):
                    # A read of this heater in this tick, or within the reuse
                    # window (a command refresh, a confirmation, an on-demand
                    # read), already supplied the reading: no duplicate request.
                    recent = (
                        self.monotonic() - self.last_status_attempt.get(serial, float("-inf"))
                        < POLL_REUSE_SECONDS
                    )
                    if serial not in self.read_this_tick and not (serial in due and recent):
                        self.poll_status(serial)
                    if serial in due:
                        # Only a due background poll moves the schedule, and only
                        # to the next clock slot: extra reads never shift it.
                        self.next_background[serial] = self._next_slot()
                self.next_poll = min(
                    (self.next_background.get(serial, 0) for serial in self.active_devices),
                    default=self.clock() + self.poll_interval,
                )
                self.failures = 0
                self.usage.cooldown(0, 0)
                if self.last_diagnostic is not None:
                    LOG.info("Bridge resumed: code=cloud_cycle_recovered.")
                self.last_diagnostic = None
                self.cloud_health = "ok"
                self.publish_diagnostics(force=True)
            self.next_cloud = min(self.clock() + self.COMMAND_INTERVAL, self.next_poll)
        except (CloudError, OSError, ValueError, TypeError) as error:
            self._offline()
            self.failures = min(self.failures + 1, 5)
            delay = min(self.MAX_BACKOFF, 20 * 2**self.failures)
            # A failed pre-command status read is a failed status read: it gets
            # the ordinary poll backoff, so commands cannot hammer the cloud.
            if polling or self.operation == "command_status_refresh":
                base = max(self.poll_interval, self.min_cloud_retry)
                if self.operation in {"password_login", "token_refresh"}:
                    # Auth retries keep their old timing; ordinary reads still wait.
                    self.next_poll = self.clock() + base
                else:
                    delay = min(self.MAX_CLOUD_BACKOFF, base * 2 ** (self.failures - 1))
                    self.next_poll = self.clock() + delay
                    self.usage.cooldown(self.next_poll, self.failures)
            self.next_cloud = self.clock() + delay
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
            if self.quota_signal:
                code = self.quota_signal
            diagnostic = (self.operation, code, delay)
            if self.pending is not None:
                # Remembered for the command's outcome (e.g. at the deadline).
                self.pending["error"] = code
                self._save_command_state_quietly()
            self.last_error = code
            self.usage.last_error = code
            self.usage.save()
            if code in {"cloud_daily_limit", "cloud_http_429", "auth_http_429"}:
                self.cloud_health = "quota_limited"
            else:
                self.cloud_health = "backoff"
            self.publish_diagnostics(force=True)
            if diagnostic != self.last_diagnostic:
                LOG.warning(
                    "Bridge paused: operation=%s code=%s backoff_seconds=%s "
                    "guard=%s total_requests_since_start=%s.",
                    *diagnostic,
                    self.guard.state["mode"],
                    sum(self.request_counts.values()),
                )
                self.last_diagnostic = diagnostic

    def _next_slot(self):
        """The next clock-aligned poll time strictly after now."""
        now = self.clock()
        return (math.floor(now / self.poll_interval) + 1) * self.poll_interval

    def run(self, stop=None):
        stop = stop if stop is not None else threading.Event()
        self.mqtt_client.reconnect_delay_set(min_delay=5, max_delay=60)
        self.mqtt_client.connect_async(
            os.getenv("MQTT_HOST", "core-mosquitto"), int(os.getenv("MQTT_PORT", "1883")), 60
        )
        self.mqtt_client.loop_start()
        LOG.info(
            "Bridge running; cloud=%s, commands=%s. Poll interval=%s seconds. "
            "Minimum cloud retry=%s minutes. Request counts reset on restart. "
            "No automatic lockout reset.",
            self.options.get("cloud_enabled", False),
            self.options.get("commands_enabled", False),
            self.poll_interval,
            self.min_cloud_retry // 60,
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
    for key in ("cloud_enabled", "commands_enabled", "on_demand_refresh_enabled"):
        if type(options.get(key, False)) is not bool:
            raise ValueError
    if options.get("command_policy", "automation") not in COMMAND_POLICIES:
        raise ValueError
    generation = options.get("auth_retry_generation", 0)
    if type(generation) is not int or generation < 0:
        raise ValueError
    poll_seconds(options)
    for key, default, maximum in (("min_cloud_retry_minutes", 60, 1440),):
        interval = options.get(key, default)
        if type(interval) is not int or not 5 <= interval <= maximum:
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
    except Exception as error:
        if isinstance(error, ValueError) and error.args == ("poll_interval_invalid",):
            LOG.error(
                "Startup paused: code=poll_interval_invalid. Seconds 60-7200; Minutes 1-120. "
                "No cloud requests sent."
            )
            stop.wait()
            return
        LOG.error(
            "Startup paused: configuration or private storage invalid. No cloud requests sent."
        )
        stop.wait()
        return
    bridge.run(stop)


if __name__ == "__main__":
    main()
