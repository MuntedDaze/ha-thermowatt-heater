# Frozen upgrade fixtures (isolated CI only)

- `thermann_shadow_0_2_0/` — byte-for-byte copy of
  `custom_components/thermann_shadow` at commit `863ee65` (Shadow Planner 0.2.0).
- `thermann_shadow_0_3_0/` — byte-for-byte copy at commit `bd95f04` (Shadow
  Planner 0.3.0, the version the owner has installed; the installed files were
  hash-verified against this commit in `audit/thermann_shadow/installed_component_match.json`).

- `thermann_shadow_0_5_0/` — byte-for-byte copy at commit `8cc4a4d` (Controller
  0.5.0, the version the owner installed in Stage A, disabled).

`shadow_ha_checks.upgrade_from_*` loads each in a network-less HA Core container,
saves options and an entity rename to real HA storage, stops HA, then starts the
current component over the same storage. It proves that entity IDs, unique IDs and
saved options survive the upgrade. The only change made is the documented
40 → 42 °C migration of the untouched old morning threshold, and the four retired
0.3.0 simulation sensors are no longer provided.

Never edit these files and never install them. Ruff excludes this folder so the
frozen copies stay identical to what shipped.

- `thermann_shadow_0_6_0/` — byte-for-byte copy at commit `1b5c1c5` (Controller
  0.6.0, installed by the owner from PR #14 for T3, automatic control off).

- `thermann_shadow_0_6_1/` — byte-for-byte copy at commit `1324a3c` (Controller
  0.6.1, installed on 13 Nov 2026 for T3b, automatic control off; the installed
  files were compared and are identical).

- `thermann_shadow_0_6_2/` — byte-for-byte copy at commit `5fe48e3` (Controller
  0.6.2, the version installed on 13 Nov 2026 and still installed, automatic
  control off; the installed files were compared and are identical).
