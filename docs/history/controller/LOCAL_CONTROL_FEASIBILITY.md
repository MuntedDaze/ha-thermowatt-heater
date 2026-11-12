# Local-only control — feasibility (read-only research)

**Short answer: no supported local network control has been found.** The
initial controller stays cloud-based, through the Thermowatt bridge. Nothing
was tested against the device or network.

## Evidence

- **Manual.** The Thermann Installer's Manual & Owner's Guide says modes are
  available **only through the Thermann Control app**. Pairing joins the
  heater to home Wi-Fi via a 5-minute pairing mode after a power cycle; remote
  control needs internet connectivity. A phone hotspot can stand in for the
  home router, but that is still cloud. There is no local API, LAN protocol or
  local-control setting.
- **"Demand response."** The manual mentions demand-response tariffs "if
  permissions have been granted" while in Off/Holiday. It describes no physical
  demand-response terminal.
- **Community bridges.** All reviewed bridges (four public forks plus this
  repository) use the vendor cloud (`myapp-connectivity.com`); none implements
  local control.

## Options

| Option | Realistic? | Notes |
| --- | --- | --- |
| Vendor-supported local API | Unknown | Ask Thermann support (question below). Do not invent one. |
| **Mains power gating** by an electrician-installed contactor driven by HA (controlled-load style; Manual 70 always) | **Technically possible, local, but with real drawbacks** | The manual supports Manual mode on a controlled load, and saved settings survive power loss. But every power-up enters 5-min pairing mode (no control), may trigger an antibacterial heat "within a few hours", and frost protection needs power. Thermostat and cut-outs stay intact. Needs a licensed electrician, a correctly rated contactor and safe failure behaviour. A separate design and approval would be needed. |
| Demand-response terminal (AS/NZS 4755 style) | Not documented for this model | Ask Thermann whether one exists. |
| LAN traffic interception, firmware changes, opening the unit | **Rejected** | Security, warranty and safety risks; against the owner's constraints. |
| Passive check of whether the module offers any local service | Possible later, owner-approved only | For example the router's client list or connection logs, without scanning or probing the heater. |

## Recommended next step

Send Thermann support a short question (the owner, not the agent): "Does the
Thermann Smart Electric (firmware 07.00.09.06) offer any local network control
or demand-response interface, and what happens to its programme and thermostat
when the internet or cloud is unavailable?"

Revisit power gating only if cloud reliability proves inadequate in operation.
