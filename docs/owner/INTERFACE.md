# Thermowatt interface and diagnostics

The existing seven-view energy dashboard is unchanged. The separate optional
`homeowner/thermowatt.yaml` uses built-in Home Assistant cards only, with five
responsive views: Home, Controls, Heating preferences, Electricity and optimisation,
and Advanced and diagnostics. No custom card, CSS override or core frontend patch
is required. Long help is in full-width markdown/cards and native Configure forms.

## Install a separate dashboard

In **Settings → Dashboards → Add dashboard**, choose a new dashboard you manage,
name it Thermowatt, and open it. Use **⋮ → Edit dashboard → ⋮ → Raw configuration
editor**. For a new blank dashboard, paste the contents of
`homeowner/thermowatt.yaml` and save. If HA asks to take control of that new
dashboard, do so. Do not paste over the whole-home dashboard. Existing personalised
entity IDs may need dashboard-only reference edits; do not recreate entities.

Advanced YAML-managed dashboard users can copy the file to
`/config/dashboards/thermowatt.yaml` and add the following to their existing
`lovelace.dashboards` mapping, keeping other entries. Never replace the whole
`configuration.yaml` with this example:

```yaml
lovelace:
  dashboards:
    thermowatt-owner:
      mode: yaml
      title: Thermowatt
      show_in_sidebar: true
      filename: dashboards/thermowatt.yaml
```

## Settings are explained where you use them

Open **Settings → Devices & services → Thermann Controller → Configure**.
Hot Water contains everyday target/peak/boost settings. Electricity Tariffs
contains prices, clocks and guided periods. Solar & Meters contains source
mappings, forecasts, weekend preferences and experimental CT-free setup.
Advanced/System retains equipment, cloud timing, qualifications and quotas.
Every configurable field has inline help, examples, units and consequences.
Protected changes require Automatic OFF; invalid changes save nothing.
[The complete setting index](../SETTINGS.md) matches these screens.

## Copy diagnostic report

The dashboard's prominent report button opens the integration page. Choose
**Configure → Copy diagnostic report**. In the native multiline text field,
select all and copy (Ctrl+A/Ctrl+C on a computer; touch/hold → Select all → Copy
on a phone). Paste once into support. Close report discards all edits without
saving options or sending commands. Reopen for a fresh snapshot.

This is the explicitly supported copyable-view alternative: it does not pretend
to automatically access the clipboard. No decorative MQTT button or unknown
frontend service is used. The report is JSON-formatted readable text, containing
typed temperatures, time/zone, status age evidence, selected policy/plan, tariffs,
meter source references and freshness, forecasts, prior/target/result, pending/
protective exit, cloud/auth categories, HTTP counts and recent bounded events.
Unknown/unallowlisted external text is omitted rather than copied blindly.

**Download detailed diagnostics:** integration's three-dot menu → Download
diagnostics uses HA's authenticated standard endpoint and the same allowlist.
The component does not copy the config entry, raw attributes/HTTP bodies,
passwords/tokens, topics or serials into its report. Source names are short
correlation hashes. HA adds a surrounding system/custom-integration metadata
wrapper; review it before sharing. Do not upload private App data or credentials.

## Names, states and More Info

Friendly display names improve the significant sensors while retaining historical
entity IDs and unique IDs; owner registry-name overrides remain theirs. Raw state
codes remain compatible with automations. The Home plan uses readable text;
selected sensors include an explanatory attribute. Native `SensorEntityDescription`
and translation mechanisms are used, not a fabricated universal description field.
Home Assistant's standard sensor More Info dialog does not offer a supported
arbitrary rich-text help panel or integration-controlled column widening. The
dedicated dashboard, inline forms and linked handbook supply that context.

The heartbeat now publishes a genuine completed evaluation timestamp at most
15 minutes apart, or when its supervision state changes. Exact internal evaluation
still advances normally and appears in reports. No command, local solar or fault
evaluation is throttled. The existing30-minute watchdog remains conservative;
do not lower its threshold below the documented publication cadence. Significant
measurements/transitions still record; this is not a blanket Recorder exclusion.

## Frontend verification

CI runs official HA2026.10.4/2026.11.1 frontends with Playwright at1280px desktop
and390px phone widths, isolated from external networking and with all service
commands denied. It opens actual Configure menus/fields/help, verifies unchanged
save values/IDs, exercises native report selection/close and renders all five
Lovelace views. Generated YAML alone is not called visual verification. Final
screenshots and their inspected commit are recorded in [evidence](../history/next-major/EVIDENCE.md).
Actual owner theme/renamed entities, phone clipboard gestures, keyboard focus and
accessibility still merit a quick owner check after installation.
