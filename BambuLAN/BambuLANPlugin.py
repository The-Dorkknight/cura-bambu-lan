# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
#
# Cura glue for Bambu LAN Print: the "Print over LAN" output device and the
# setup dialog. All network work lives in bambu_lan.py.

import html
import io
import json
import os
import threading

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from UM.Application import Application
from UM.Extension import Extension
from UM.Logger import Logger
from UM.Message import Message
from UM.OutputDevice import OutputDeviceError
from UM.OutputDevice.OutputDevice import OutputDevice
from UM.OutputDevice.OutputDevicePlugin import OutputDevicePlugin
from UM.PluginRegistry import PluginRegistry

from . import bambu_lan

META_KEY = "bambu_lan"  # per-printer settings stored on the Cura machine (global stack)
PREF_ACCEPTED = "bambu_lan/disclaimer_accepted"
COPYRIGHT = "Copyright Matthew Armstrong (https://github.com/The-Dorkknight)"
REPO_URL = "https://github.com/The-Dorkknight/cura-bambu-lan"
DEFAULTS = {
    "ip": "", "access_code": "", "serial": "", "insecure": False,
    "start": True, "filament": -1, "bed_levelling": True, "flow_cali": False,
    "timelapse": False, "bed_type": "auto",
}


def load_config(stack=None):
    stack = stack or Application.getInstance().getGlobalContainerStack()
    cfg = dict(DEFAULTS)
    if stack is not None:
        raw = stack.getMetaDataEntry(META_KEY)
        if raw:
            try:
                cfg.update(json.loads(raw))
            except ValueError:
                Logger.log("w", "Bambu LAN: bad stored config, ignoring")
    return cfg


def is_configured(cfg):
    return bool(cfg.get("ip") and cfg.get("access_code"))


def machine_name():
    stack = Application.getInstance().getGlobalContainerStack()
    return stack.getName() if stack is not None else ""


# ============================================================= output device

class BambuOutputDevice(OutputDevice):
    def __init__(self):
        super().__init__("bambu_lan")
        self._busy = False
        self.refresh()
        self.setIconName("print")
        self.setPriority(3)  # above Save to Disk, so it becomes the main button

    def refresh(self):
        cfg = load_config()
        start = cfg.get("start", True)
        self.setName("Bambu LAN (%s)" % cfg.get("ip", ""))
        self.setShortDescription("Print over LAN" if start else "Upload over LAN")
        self.setDescription("%s to %s at %s" % ("Print" if start else "Upload", machine_name(), cfg.get("ip", "")))

    def requestWrite(self, nodes, file_name=None, limit_mimetypes=False, file_handler=None,
                     filter_by_machine=False, **kwargs):
        if self._busy:
            raise OutputDeviceError.DeviceBusyError()
        cfg = load_config()
        if not Application.getInstance().getPreferences().getValue(PREF_ACCEPTED):
            raise OutputDeviceError.WriteRequestFailedError(
                "Open Extensions → Bambu LAN → Set up this printer… and accept the notice first.")
        if not is_configured(cfg):
            raise OutputDeviceError.WriteRequestFailedError(
                "Set up this printer first: Extensions → Bambu LAN → Set up this printer.")

        # Let Cura's own writer produce the G-code (post-processing already applied).
        writer = PluginRegistry.getInstance().getPluginObject("GCodeWriter")
        buf = io.StringIO()
        if not writer.write(buf, None):
            raise OutputDeviceError.WriteRequestFailedError("Slice the model before sending it.")
        gcode = buf.getvalue()

        job_name = file_name
        try:
            job_name = Application.getInstance().getPrintInformation().jobName or file_name
        except Exception:
            pass

        self._busy = True
        self.writeStarted.emit(self)
        msg = Message("Connecting…", title="Bambu LAN — %s" % machine_name(),
                      lifetime=0, dismissable=False, progress=-1)
        msg.show()
        app = Application.getInstance()

        def stage(text):
            app.callLater(msg.setText, text + "…")

        def progress(sent, total):
            pct = int(sent * 100 / max(total, 1))
            app.callLater(msg.setProgress, pct)
            app.callLater(msg.setText, "Uploading… %d%% of %.1f MB" % (pct, total / 1e6))

        def work():
            try:
                result = bambu_lan.send_print(cfg, gcode, job_name, progress, stage)
                app.callLater(self._done, msg, True, result)
            except bambu_lan.BambuError as e:
                app.callLater(self._done, msg, False, str(e))
            except Exception as e:
                Logger.logException("e", "Bambu LAN: unexpected error")
                app.callLater(self._done, msg, False, "Unexpected error: %s" % e)

        threading.Thread(target=work, name="BambuLANSend", daemon=True).start()

    def _done(self, progress_msg, ok, text):
        self._busy = False
        progress_msg.hide()
        # Text can contain strings from the printer; show it as plain text, never markup.
        Message(html.escape(text), title="Bambu LAN — %s" % ("sent" if ok else "failed"),
                lifetime=0 if not ok else 15).show()
        self.writeFinished.emit(self)
        (self.writeSuccess if ok else self.writeError).emit(self)


class BambuOutputDevicePlugin(OutputDevicePlugin):
    """Shows the device only while the active Cura printer has LAN settings."""

    def __init__(self):
        super().__init__()
        self._device = None
        self._started = False

    def start(self):
        self._started = True
        Application.getInstance().globalContainerStackChanged.connect(self.update)
        self.update()

    def stop(self):
        self._started = False
        self._remove()

    def update(self):
        if not self._started:
            return
        if is_configured(load_config()):
            if self._device is None:
                self._device = BambuOutputDevice()
                self.getOutputDeviceManager().addOutputDevice(self._device)
            else:
                self._device.refresh()
        else:
            self._remove()

    def _remove(self):
        if self._device is not None:
            self.getOutputDeviceManager().removeOutputDevice(self._device.getId())
            self._device = None


# ============================================================= setup dialog

class BambuSetup(QObject, Extension):
    statusChanged = pyqtSignal(str, bool, arguments=["text", "ok"])
    printersFound = pyqtSignal(str, arguments=["listJson"])
    serialFound = pyqtSignal(str, arguments=["serial"])

    def __init__(self, devices, parent=None):
        QObject.__init__(self, parent)
        Extension.__init__(self)
        self._devices = devices
        self._dialog = None
        Application.getInstance().getPreferences().addPreference(PREF_ACCEPTED, False)
        self.setMenuName("Bambu LAN")
        self.addMenuItem("Set up this printer…", self.showDialog)
        self.addMenuItem("About", self.showAbout)

    def showDialog(self):
        if Application.getInstance().getGlobalContainerStack() is None:
            Message("Add a printer in Cura first.", title="Bambu LAN").show()
            return
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "BambuSetup.qml")
        self._dialog = Application.getInstance().createQmlComponent(path, {"manager": self})
        if self._dialog is not None:
            self._dialog.show()

    def _pluginVersion(self):
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "plugin.json"), encoding="utf-8") as f:
                return json.load(f).get("version", "?")
        except Exception:
            return "?"

    def showAbout(self):
        Message(
            "Bambu LAN Print %s<br>%s<br>Source-available, non-commercial: PolyForm Noncommercial License 1.0.0.<br>"
            "Provided as is, with no warranty and no liability.<br>"
            "Not affiliated with or endorsed by Bambu Lab or UltiMaker.<br>%s"
            % (self._pluginVersion(), COPYRIGHT, REPO_URL),
            title="About Bambu LAN Print", lifetime=0).show()

    @pyqtSlot(result=bool)
    def isAccepted(self):
        return bool(Application.getInstance().getPreferences().getValue(PREF_ACCEPTED))

    @pyqtSlot()
    def accept(self):
        Application.getInstance().getPreferences().setValue(PREF_ACCEPTED, True)

    @pyqtSlot(result=str)
    def aboutLine(self):
        return "Bambu LAN Print %s · %s · PolyForm Noncommercial 1.0.0 · no warranty" % (self._pluginVersion(), COPYRIGHT.split(" (")[0])

    @pyqtSlot(result=str)
    def loadConfig(self):
        cfg = load_config()
        cfg["machine"] = machine_name()
        return json.dumps(cfg)

    @pyqtSlot(str)
    def saveConfig(self, cfg_json):
        cfg = dict(DEFAULTS)
        cfg.update({k: v for k, v in json.loads(cfg_json).items() if k in DEFAULTS})
        stack = Application.getInstance().getGlobalContainerStack()
        if stack is not None:
            stack.setMetaDataEntry(META_KEY, json.dumps(cfg))
        self._devices.update()

    @pyqtSlot()
    def removeConfig(self):
        stack = Application.getInstance().getGlobalContainerStack()
        if stack is not None:
            stack.setMetaDataEntry(META_KEY, "")
        self._devices.update()

    @pyqtSlot()
    def discover(self):
        def work():
            try:
                found = bambu_lan.discover(8)
            except Exception as e:
                Logger.logException("w", "Bambu LAN discovery failed")
                found = []
            self.printersFound.emit(json.dumps(found))
        threading.Thread(target=work, daemon=True).start()

    @pyqtSlot(str)
    def testConnection(self, cfg_json):
        cfg = dict(DEFAULTS)
        cfg.update(json.loads(cfg_json))

        def work():
            try:
                serial, report = bambu_lan.test_connection(cfg)
                if not cfg.get("serial"):
                    self.serialFound.emit(serial)
                self.statusChanged.emit(report, True)
            except bambu_lan.BambuError as e:
                self.statusChanged.emit(str(e), False)
            except Exception as e:
                Logger.logException("e", "Bambu LAN test failed")
                self.statusChanged.emit("Unexpected error: %s" % e, False)
        threading.Thread(target=work, daemon=True).start()
