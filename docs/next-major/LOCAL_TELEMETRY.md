# Local read-only Thermann telemetry: feasibility,17 November2026

No supported local temperature interface was established from the public material
reviewed. This is a research limit, not proof that no vendor interface exists.
No local API is implemented or claimed; all mode commands remain through the one
existing guarded cloud bridge. GoodWe/HK1000 provides local electricity evidence,
not Thermann tank temperature.

The [manufacturer product information](https://www.thermann.com.au/products/smart-electric-storage/)
and [owner guide](https://www.thermann.com.au/thermann-cms/files/Thermann-Smart_Electric-Owners_Guide.pdf)
document the official app/Wi-Fi workflow; initial pairing requirements do not
establish a supported local telemetry protocol. The reviewed public documentation
does not specify local read-only temperature endpoints, authentication, timestamps,
sample limits or compatibility commitments.

The [upstream implementation](https://github.com/waterheater-dev/ha-thermowatt-heater)
and [maintainer discussion](https://community.home-assistant.io/t/smart-immersion-heater-thermowatt/656332)
were checked as primary community implementation/testimony, not manufacturer
protocol guarantees. The upstream description's phrase local control does not
establish a LAN API; the existing project actually uses Thermowatt cloud HTTP.
No manufacturer-supported Matter/Modbus/local MQTT read-only specification was
found for this model in that review. Similar product names are not evidence.

No device scans, credentials, pairing changes, packet interception, encryption
bypass, undocumented probes or alternate commands were attempted. A future local
reader would need official documentation and separately approved validation. It
must expose source/acquisition time, boot/freshness and quality separately from
cloud confirmation, with no second command path or authority to defeat exact-prior
checks. Until then, bounded event-aware cloud reads remain the practical route.

## Unsent manufacturer enquiry

Subject: Supported read-only local temperature/status for Thermann Smart Electric

Hello Thermann/technical support,

I own a Smart Electric315L heater and use the official app. I am developing a
Home Assistant monitoring integration and would like to reduce unnecessary
cloud requests while preserving all appliance protections. Is there a documented,
supported local **read-only** interface for bottom temperature, current mode,
target and element status for this model/firmware?

If available, could you provide its documentation, permission/authentication
requirements, units, original acquisition timestamps, update/rate limits and
supported firmware? If none exists, is there recommended cloud polling and
session-expiry guidance, or a supported notification/subscription interface?
I am not requesting a way to bypass protections or an alternate heater-command
path. Thank you for any guidance.

This enquiry is prepared only. It has not been sent.
