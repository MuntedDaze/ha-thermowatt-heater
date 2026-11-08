"""Smoke-test-only Python guard, mounted at runtime; never copied into the image."""

import json
import os
from pathlib import Path
import socket

import requests

AUDIT = Path("/data/network-audit.jsonl")


def record(kind):
    with AUDIT.open("a") as stream:
        stream.write(json.dumps({"kind": kind}) + "\n")


def forbidden_http(*args, **kwargs):
    record("forbidden_http")
    raise AssertionError("HTTP prohibited during disabled-cloud smoke test")


original_connect = socket.socket.connect
original_resolve = socket.getaddrinfo
allowed_ip = os.environ["SMOKE_MQTT_IP"]


def limited_connect(sock, address):
    if sock.family in (socket.AF_INET, socket.AF_INET6):
        if address[0] != allowed_ip or address[1] != 1883:
            record("forbidden_socket")
            raise AssertionError("External socket prohibited during smoke test")
        record("mqtt_connect")
    return original_connect(sock, address)


def limited_resolve(host, *args, **kwargs):
    if host not in ("mqtt", allowed_ip):
        record("forbidden_dns")
        raise AssertionError("External DNS prohibited during smoke test")
    return original_resolve(host, *args, **kwargs)


requests.Session.request = forbidden_http
socket.socket.connect = limited_connect
socket.getaddrinfo = limited_resolve
record("guard_loaded")
