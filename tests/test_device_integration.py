import os

import pytest

SERIAL = os.environ.get("ANDROIDHARNESS_DEVICE_SERIAL")

pytestmark = pytest.mark.skipif(
    not SERIAL,
    reason="set ANDROIDHARNESS_DEVICE_SERIAL to run device integration tests",
)


def test_list_devices_includes_target_serial():
    from androidharness.device import list_devices

    serials = [d.serial for d in list_devices()]
    assert SERIAL in serials


def test_dump_hierarchy_returns_non_empty_xml():
    from androidharness.device import UIAutomatorDevice

    device = UIAutomatorDevice.connect(SERIAL)
    xml = device.dump_hierarchy()
    assert xml.strip().startswith("<")
    assert "<hierarchy" in xml
