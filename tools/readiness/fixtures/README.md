# Frozen upgrade fixtures (isolated CI only)

`thermann_shadow_0_2_0/` is a byte-for-byte copy of
`custom_components/thermann_shadow` at commit `863ee65` (Shadow Planner 0.2.0,
the version the owner installed). `shadow_ha_checks.upgrade_from_0_2_0` loads it
in a network-less HA Core container, saves options and an entity rename to real
HA storage, stops HA, then starts the current component over the same storage to
prove entity IDs, unique IDs and saved options survive the 0.3.0 upgrade.

Never edit these files and never install them. Ruff excludes this folder so the
frozen copy stays identical to what shipped.
