# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
#
# Bambu LAN Print for Cura: send prints to Bambu Lab printers over the local network.

from . import BambuLANPlugin


def getMetaData():
    return {}


def register(app):
    devices = BambuLANPlugin.BambuOutputDevicePlugin()
    return {
        "output_device": devices,
        "extension": BambuLANPlugin.BambuSetup(devices),
    }
