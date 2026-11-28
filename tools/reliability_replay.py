"""Run the same synthetic bridge and policy scenarios against two checkouts."""

from collections import Counter
from datetime import timedelta
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

from pytest import MonkeyPatch

sys.path.insert(0, str(Path.cwd() / "tests"))
from test_cloud_outage_recovery import (  # noqa: E402
    AvailabilityRig,
    CLOUD_SUCCESS_FALSE,
    advance,
    evaluate,
    make_evening_peak_rig,
)
from test_integration_0_9_0 import MON, SERIAL, hobart  # noqa: E402
from conftest import response  # noqa: E402


def simulate(tmp, patch, case):
    if case == "overnight":
        rig = AvailabilityRig(tmp, patch, hobart(MON, 0), mode="Manual", setpoint=45)
        rig.enable()
        advance(rig, hobart(MON, 8, 10))
        return rig

    if case == "stable_transient":
        rig = AvailabilityRig(tmp, patch, hobart(MON, 1), mode="Manual", setpoint=45)
        rig.enable()
        outage = hobart(MON, 2)
        advance(rig, outage - timedelta(seconds=20))
        rig.bridge.next_background[SERIAL] = outage.timestamp()
        rig.bridge.next_poll = outage.timestamp()
        rig.bridge.next_cloud = outage.timestamp()
        # Explicitly inject the failure at this otherwise quiet time.
        rig.bridge.poll_schedule.clear()
    else:
        rig = make_evening_peak_rig(tmp, patch, hobart(MON, 21, 28), cloud_polling="smart")
        outage = hobart(MON, 21, 58)

    recovery = outage + timedelta(hours=3 if case == "parked_persistent" else 1)

    def cloud(method, url, **kwargs):
        if url.endswith("/status") and rig.now() < recovery:
            return response(body=CLOUD_SUCCESS_FALSE)
        return rig.cloud(method, url, **kwargs)

    rig.bridge.session.request.side_effect = cloud
    rig.t = outage.timestamp()
    rig.bridge.tick()
    evaluate(rig)
    advance(rig, recovery + timedelta(minutes=3))
    return rig


if __name__ == "__main__":
    for case in ("overnight", "stable_transient", "parked_transient", "parked_persistent"):
        with TemporaryDirectory() as root, MonkeyPatch.context() as patch:
            rig = simulate(Path(root), patch, case)
            counts = Counter(
                f"{call.args[0]} {call.args[1].rsplit('/', 1)[-1]}"
                for call in rig.bridge.session.request.call_args_list
            )
            print(
                json.dumps(
                    dict(
                        case=case,
                        calls=counts,
                        commands=rig.commands(),
                        final=rig.executor.controller.state,
                        notifications=rig.notifications,
                    )
                )
            )
