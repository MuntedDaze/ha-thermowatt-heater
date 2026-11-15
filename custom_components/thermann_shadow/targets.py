"""Closed bridge-supported physical states, independently of planning roles."""

OFF, BASELINE, NORMAL, BOOST = "off", "baseline", "normal_storage", "storage"
TARGET_C = {BASELINE: 45, NORMAL: 62, BOOST: 70}
STATE_AT = {value: key for key, value in TARGET_C.items()}


def state_at(temperature):
    return STATE_AT[temperature]


def validate_roles(baseline, normal, boost):
    # Equal roles disable an unnecessary intermediate/top-up transition. They
    # remain one physical state, never two ambiguous readback classifications.
    if (
        baseline not in (45, 62)
        or normal not in (62, 70)
        or boost not in (62, 70)
        or not baseline <= normal <= boost
    ):
        raise ValueError("unsupported_target_roles")
