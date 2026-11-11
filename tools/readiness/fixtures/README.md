# Frozen upgrade fixtures (isolated CI only)

- `thermann_shadow_0_2_0/` — byte-for-byte copy of
  `custom_components/thermann_shadow` at commit `863ee65` (Shadow Planner 0.2.0).
- `thermann_shadow_0_3_0/` — byte-for-byte copy at commit `bd95f04` (Shadow
  Planner 0.3.0, the version the owner has installed; the installed files were
  hash-verified against this commit in `audit/thermann_shadow/installed_component_match.json`).

`shadow_ha_checks.upgrade_from_*` loads each in a network-less HA Core container,
saves options and an entity rename to real HA storage, stops HA, then starts the
current component over the same storage. It proves that entity IDs, unique IDs and
saved options survive the upgrade. The only change made is the documented
40 → 42 °C migration of the untouched old morning threshold, and the four retired
0.3.0 simulation sensors are no longer provided.

Never edit these files and never install them. Ruff excludes this folder so the
frozen copies stay identical to what shipped.
