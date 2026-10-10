# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
#
# Bambu Lab LAN protocol client — no Cura imports, standard library only.
#
# Talks to a Bambu printer in LAN-only + Developer Mode:
#   * FTPS, implicit TLS, port 990, user "bblp" / LAN access code  -> upload
#   * MQTT over TLS, port 8883, same credentials                    -> start print
# Protocol reference: https://github.com/Doridian/OpenBambuAPI

import ftplib
import hashlib
import io
import json
import os
import random
import re
import select
import socket
import ssl
import struct
import tempfile
import time
import zipfile

CA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bambu_ca.pem")
MQTT_PORT = 8883
FTP_PORT = 990
USER = "bblp"

FILAMENT_EXTERNAL = -1  # external spool (no AMS)


class BambuError(Exception):
    """An error with a message that is safe to show to the user."""


# ---------------------------------------------------------------- TLS

def make_context(verify=True):
    if verify:
        ctx = ssl.create_default_context(cafile=CA_FILE)
        # Bambu's certificates are not strict-X509 compliant.
        ctx.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)
    else:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _cn_from_der(der):
    """Read the common name out of a DER certificate (for unverified mode)."""
    pem = ssl.DER_cert_to_PEM_cert(der)
    fd, path = tempfile.mkstemp(suffix=".pem")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(pem)
        info = ssl._ssl._test_decode_cert(path)  # CPython helper, present in 3.x
    finally:
        os.unlink(path)
    for rdn in info.get("subject", ()):
        for key, value in rdn:
            if key == "commonName":
                return value
    return ""


def detect_serial(ip, verify=True, timeout=8):
    """The printer's TLS certificate is issued to its serial number, so one
    handshake tells us the serial without the user typing it."""
    ctx = make_context(verify)
    ctx.check_hostname = False  # we don't know the name yet; chain is still checked if verify
    try:
        with socket.create_connection((ip, MQTT_PORT), timeout=timeout) as raw:
            with ctx.wrap_socket(raw) as s:
                if verify:
                    subject = s.getpeercert().get("subject", ())
                    for rdn in subject:
                        for key, value in rdn:
                            if key == "commonName":
                                return value
                    return ""
                return _cn_from_der(s.getpeercert(binary_form=True))
    except ssl.SSLCertVerificationError as e:
        raise BambuError(
            "The printer's certificate isn't signed by Bambu Lab's CA (%s). "
            "If you trust this network, tick 'Skip certificate check'." % e.verify_message)
    except (socket.timeout, TimeoutError):
        raise BambuError("No answer from %s on port %d. Check the IP and that the printer is on." % (ip, MQTT_PORT))
    except ConnectionRefusedError:
        raise BambuError("%s refused the connection on port %d. Is LAN-only mode on?" % (ip, MQTT_PORT))
    except OSError as e:
        raise BambuError("Couldn't reach %s: %s" % (ip, e))


# ---------------------------------------------------------------- MQTT (3.1.1, QoS 0)

def _mqtt_str(s):
    b = s.encode("utf-8")
    return struct.pack("!H", len(b)) + b


def _mqtt_len(n):
    out = bytearray()
    while True:
        byte = n % 128
        n //= 128
        if n:
            byte |= 0x80
        out.append(byte)
        if not n:
            return bytes(out)


CONNACK_REASONS = {
    1: "unsupported protocol version",
    2: "client id rejected",
    3: "MQTT service unavailable",
    4: "wrong access code",
    5: "not authorised — check the access code and that Developer Mode is on",
}


class MiniMQTT:
    """Just enough MQTT to talk to one Bambu printer."""

    def __init__(self, ip, serial, access_code, verify=True, timeout=10):
        self.serial = serial
        self._timeout = timeout
        ctx = make_context(verify)
        try:
            raw = socket.create_connection((ip, MQTT_PORT), timeout=timeout)
            self.sock = ctx.wrap_socket(raw, server_hostname=serial if verify else None)
        except ssl.SSLCertVerificationError as e:
            raise BambuError("Certificate check failed (%s). Is the serial number right?" % e.verify_message)
        except OSError as e:
            raise BambuError("Couldn't open MQTT connection to %s: %s" % (ip, e))
        self._buf = b""
        self._seq = random.randint(1000, 9000)
        self._connect(access_code)

    # low level
    def _send(self, header, body=b""):
        self.sock.sendall(bytes([header]) + _mqtt_len(len(body)) + body)

    def _read_exact(self, n, deadline):
        while len(self._buf) < n:
            left = deadline - time.monotonic()
            if left <= 0:
                raise socket.timeout()
            if not self.sock.pending():
                r, _, _ = select.select([self.sock], [], [], left)
                if not r:
                    raise socket.timeout()
            chunk = self.sock.recv(65536)
            if not chunk:
                raise BambuError("The printer closed the MQTT connection.")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _read_packet(self, deadline):
        header = self._read_exact(1, deadline)[0]
        mult, length = 1, 0
        while True:
            b = self._read_exact(1, deadline)[0]
            length += (b & 0x7F) * mult
            if not b & 0x80:
                break
            mult *= 128
        return header, self._read_exact(length, deadline)

    def _connect(self, access_code):
        client_id = "cura-bambulan-%06x" % random.getrandbits(24)
        body = (_mqtt_str("MQTT") + bytes([4, 0xC2]) + struct.pack("!H", 60)
                + _mqtt_str(client_id) + _mqtt_str(USER) + _mqtt_str(access_code))
        self._send(0x10, body)
        try:
            header, payload = self._read_packet(time.monotonic() + self._timeout)
        except socket.timeout:
            raise BambuError("The printer didn't answer the MQTT login.")
        if header >> 4 != 2 or len(payload) < 2:
            raise BambuError("Unexpected reply to MQTT login.")
        if payload[1] != 0:
            raise BambuError("Printer refused login: %s." % CONNACK_REASONS.get(payload[1], "code %d" % payload[1]))
        # subscribe to reports
        topic = "device/%s/report" % self.serial
        self._send(0x82, struct.pack("!H", 1) + _mqtt_str(topic) + b"\x00")
        deadline = time.monotonic() + self._timeout
        while True:
            try:
                header, payload = self._read_packet(deadline)
            except socket.timeout:
                raise BambuError("The printer didn't confirm the subscription.")
            if header >> 4 == 9:
                if payload[2:3] == b"\x80":
                    raise BambuError("The printer rejected the subscription. Is the serial number right?")
                return

    # high level
    def publish(self, message):
        self._seq += 1
        for section in message.values():
            if isinstance(section, dict):
                section.setdefault("sequence_id", str(self._seq))
        body = _mqtt_str("device/%s/request" % self.serial) + json.dumps(message).encode("utf-8")
        self._send(0x30, body)

    def messages(self, seconds):
        """Yield decoded report dicts until `seconds` pass."""
        deadline = time.monotonic() + seconds
        last_ping = time.monotonic()
        while time.monotonic() < deadline:
            if time.monotonic() - last_ping > 20:
                self._send(0xC0)
                last_ping = time.monotonic()
            try:
                header, payload = self._read_packet(min(deadline, time.monotonic() + 5))
            except socket.timeout:
                continue
            if header >> 4 != 3:
                continue
            qos = (header >> 1) & 3
            tlen = struct.unpack("!H", payload[:2])[0]
            start = 2 + tlen + (2 if qos else 0)
            try:
                yield json.loads(payload[start:].decode("utf-8", "replace"))
            except ValueError:
                continue

    def status(self, seconds=6):
        """Ask for a full status push and return the 'print' section (may be partial)."""
        self.publish({"pushing": {"command": "pushall", "version": 1, "push_target": 1}})
        state = {}
        for msg in self.messages(seconds):
            p = msg.get("print")
            if isinstance(p, dict):
                state.update(p)
                if "gcode_state" in p:
                    return state
        return state

    def version(self, seconds=5):
        """Return (model, firmware) from info.get_version, or ("", "")."""
        self.publish({"info": {"command": "get_version"}})
        for msg in self.messages(seconds):
            info = msg.get("info")
            if isinstance(info, dict) and isinstance(info.get("module"), list):
                return model_from_modules(info["module"]), firmware_from_modules(info["module"])
        return "", ""

    def close(self):
        try:
            self._send(0xE0)
            self.sock.close()
        except OSError:
            pass


# ---------------------------------------------------------------- FTPS (implicit, session reuse)

class ImplicitFTPS(ftplib.FTP_TLS):
    """Implicit FTPS with the data channel reusing the control channel's TLS
    session — the printer's vsftpd refuses data connections otherwise."""

    def __init__(self, context, server_name):
        super().__init__(context=context)
        self._server_name = server_name

    def connect(self, host="", port=FTP_PORT, timeout=30, source_address=None):
        self.host, self.port, self.timeout = host, port, timeout
        raw = socket.create_connection((host, port), timeout)
        self.sock = self.context.wrap_socket(raw, server_hostname=self._server_name)
        self.af = self.sock.family
        self.file = self.sock.makefile("r", encoding=self.encoding)
        self.welcome = self.getresp()
        return self.welcome

    def ntransfercmd(self, cmd, rest=None):
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p:
            conn = self.context.wrap_socket(conn, server_hostname=self._server_name,
                                            session=self.sock.session)
        return conn, size

    def store(self, name, data, progress=None, blocksize=32768):
        """STOR without the TLS unwrap at the end (the printer hangs on it)."""
        self.voidcmd("TYPE I")
        conn = self.transfercmd("STOR " + name)
        total, sent = len(data), 0
        try:
            view = memoryview(data)
            while sent < total:
                n = conn.send(view[sent:sent + blocksize])
                sent += n
                if progress:
                    progress(sent, total)
        finally:
            conn.close()
        return self.voidresp()


def ftp_open(ip, serial, access_code, verify=True):
    ctx = make_context(verify)
    ftp = ImplicitFTPS(ctx, serial if verify else None)
    try:
        ftp.connect(ip, FTP_PORT, timeout=30)
    except ssl.SSLCertVerificationError as e:
        raise BambuError("FTPS certificate check failed (%s)." % e.verify_message)
    except OSError as e:
        raise BambuError("Couldn't open FTPS to %s:%d: %s" % (ip, FTP_PORT, e))
    try:
        ftp.login(USER, access_code)
        ftp.prot_p()
    except ftplib.error_perm as e:
        ftp.close()
        raise BambuError("FTPS login refused (%s). Check the access code." % str(e).strip())
    return ftp


# ---------------------------------------------------------------- packaging

def build_3mf(gcode_text, plate=1):
    """Wrap plain G-code in the minimal .gcode.3mf the printer will run."""
    gcode = gcode_text.encode("utf-8")
    name = "Metadata/plate_%d.gcode" % plate
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(name, gcode)
        z.writestr(name + ".md5", hashlib.md5(gcode).hexdigest().upper())
    return buf.getvalue()


def safe_filename(name):
    base = re.sub(r"\.(gcode|3mf|stl|obj|ufp)$", "", (name or "cura_print").strip(), flags=re.I)
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base)
    base = re.sub(r"_+", "_", base).strip("._") or "cura_print"
    return base[:60] + ".gcode.3mf"


# ---------------------------------------------------------------- model / firmware

# The print command's "url" differs by model. These older models want the file
# addressed on the SD card; newer ones (H2 series etc.) want ftp:///.
# Same split the Home Assistant Bambu integration uses.
SDCARD_URL_MODELS = {"A1", "A1 mini", "P1P", "P1S", "X1", "X1C", "X1E"}

# Firmware that introduced the Authorization Control System (needs Developer Mode after it).
AUTH_FIRMWARE = {"A1": "01.05.00.00", "A1 mini": "01.05.00.00",
                 "P1P": "01.08.02.00", "P1S": "01.08.02.00",
                 "X1": "01.08.03.00", "X1C": "01.08.03.00", "X1E": "01.08.03.00"}

PRODUCT_NAMES = {"Bambu Lab A1": "A1", "Bambu Lab A1 mini": "A1 mini", "Bambu Lab P1P": "P1P",
                 "Bambu Lab P1S": "P1S", "Bambu Lab P2S": "P2S", "Bambu Lab H2D": "H2D",
                 "Bambu Lab H2D Pro": "H2D Pro", "Bambu Lab H2S": "H2S", "Bambu Lab H2C": "H2C",
                 "Bambu Lab X1 Carbon": "X1C", "Bambu Lab X1E": "X1E", "Bambu Lab A2L": "A2L",
                 "Bambu Lab X2D": "X2D"}


def model_from_modules(modules):
    """Work out the model from an info.get_version module list (old and new firmware)."""
    for m in modules:
        name = (m.get("product_name") or "").strip()
        if name in PRODUCT_NAMES:
            return PRODUCT_NAMES[name]
    for m in modules:
        hw, proj = m.get("hw_ver", ""), m.get("project_name", "")
        if not hw.startswith("AP0"):
            continue
        if hw == "AP02":
            return "X1E"
        if proj == "N1":
            return "A1 mini"
        if proj == "N2S":
            return "A1"
        if proj == "C11":
            return "P1P"
        if proj == "C12":
            return "P1S"
        if hw == "AP05" and not proj:
            return "X1C"
    return ""


def firmware_from_modules(modules):
    for key in ("ota", "rv1126", "esp32"):
        for m in modules:
            if m.get("name") == key and m.get("sw_ver"):
                return m["sw_ver"]
    return ""


def _ver(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:4]) or (0,)


def print_urls(model, filename):
    """Preferred URL first, the other as a fallback."""
    sd, ftp = "file:///sdcard/" + filename, "ftp:///" + filename
    return [ftp, sd] if model and model not in SDCARD_URL_MODELS else [sd, ftp]


def firmware_note(model, fw):
    auth = AUTH_FIRMWARE.get(model)
    if not (auth and fw):
        return ""
    if _ver(fw) < _ver(auth):
        return "Firmware predates Authorization Control (%s) — no Developer Mode needed." % auth
    return "Firmware has Authorization Control — Developer Mode must be on."


# ---------------------------------------------------------------- high level

BUSY_STATES = {"RUNNING", "PREPARE", "PAUSE", "SLICING"}


def test_connection(cfg):
    """Returns a multi-line human readable report. Raises BambuError."""
    ip, code, verify = cfg["ip"], cfg["access_code"], not cfg.get("insecure")
    lines = []
    serial = cfg.get("serial") or detect_serial(ip, verify)
    lines.append("Serial: %s%s" % (serial, "" if cfg.get("serial") else " (read from certificate)"))
    lines.append("Certificate: %s" % ("verified against Bambu Lab CA" if verify else "NOT checked"))
    m = MiniMQTT(ip, serial, code, verify)
    try:
        model, fw = m.version()
        st = m.status()
    finally:
        m.close()
    lines.append("MQTT: logged in")
    if model or fw:
        lines.append("Model: %s, firmware %s" % (model or "unknown", fw or "unknown"))
        note = firmware_note(model, fw)
        if note:
            lines.append(note)
    if st:
        lines.append("State: %s" % st.get("gcode_state", "unknown"))
        if "sdcard" in st:
            lines.append("SD card: %s" % ("present" if st["sdcard"] else "MISSING"))
    else:
        lines.append("State: no status report (commands may still work)")
    ftp = ftp_open(ip, serial, code, verify)
    try:
        ftp.pwd()
    finally:
        ftp.close()
    lines.append("FTPS: logged in")
    return serial, "\n".join(lines)


def send_print(cfg, gcode_text, job_name, progress=None, stage=None):
    """Upload and start a print. Returns a status string. Raises BambuError.

    cfg keys: ip, access_code, serial(optional), insecure, start (bool),
              filament (-1 external, 0.. AMS slot), bed_levelling, flow_cali,
              timelapse, bed_type
    progress(sent, total) during upload; stage(text) at each step.
    """
    stage = stage or (lambda t: None)
    ip, code, verify = cfg["ip"].strip(), cfg["access_code"].strip(), not cfg.get("insecure")
    if not ip or not code:
        raise BambuError("Set the printer's IP address and access code first.")

    stage("Connecting")
    serial = (cfg.get("serial") or "").strip() or detect_serial(ip, verify)

    mqtt, model = None, ""
    if cfg.get("start", True):
        mqtt = MiniMQTT(ip, serial, code, verify)
        model, _fw = mqtt.version()
        st = mqtt.status()
        if st.get("gcode_state") in BUSY_STATES:
            mqtt.close()
            raise BambuError("The printer is busy (%s)." % st["gcode_state"])
        if st.get("sdcard") is False:
            mqtt.close()
            raise BambuError("No SD card in the printer — LAN printing needs one.")

    try:
        filename = safe_filename(job_name)
        data = build_3mf(gcode_text)
        stage("Uploading")
        ftp = ftp_open(ip, serial, code, verify)
        try:
            reply = ftp.store("/" + filename, data, progress)
        finally:
            try:
                ftp.quit()
            except Exception:
                ftp.close()
        if not reply.startswith("226"):
            raise BambuError("Upload failed: %s" % reply)

        if not mqtt:
            return "Uploaded %s to the printer's SD card." % filename

        stage("Starting print")
        filament = int(cfg.get("filament", FILAMENT_EXTERNAL))
        use_ams = filament >= 0
        refusals = []
        for url in print_urls(model, filename):
            outcome, detail = _start_job(mqtt, {
                "command": "project_file",
                "param": "Metadata/plate_1.gcode",
                "project_id": "0", "profile_id": "0", "task_id": "0", "subtask_id": "0",
                "subtask_name": filename,
                "file": filename,
                "url": url,
                "md5": "",
                "bed_type": cfg.get("bed_type", "auto"),
                "bed_leveling": bool(cfg.get("bed_levelling", True)),
                "bed_levelling": bool(cfg.get("bed_levelling", True)),
                "flow_cali": bool(cfg.get("flow_cali", False)),
                "vibration_cali": bool(cfg.get("flow_cali", False)),
                "layer_inspect": False,
                "timelapse": bool(cfg.get("timelapse", False)),
                "use_ams": use_ams,
                "ams_mapping": [filament] if use_ams else [0],
            })
            if outcome == "printing":
                return "Printing %s" % filename
            if outcome == "unconfirmed":
                return "Sent %s — the printer hasn't confirmed yet; check its screen." % filename
            refusals.append("%s: %s" % (url.split("//")[0], detail))
        raise BambuError("Printer refused the job (%s)." % "; ".join(refusals))
    finally:
        if mqtt:
            mqtt.close()


def _start_job(mqtt, payload):
    """Publish a project_file command. Returns (outcome, detail) where outcome is
    'printing', 'refused' or 'unconfirmed'."""
    mqtt.publish({"print": payload})
    for msg in mqtt.messages(25):
        p = msg.get("print") or {}
        if p.get("command") == "project_file" and "result" in p:
            if str(p["result"]).lower() != "success":
                return "refused", p.get("reason") or p["result"]
        state = p.get("gcode_state")
        if state in BUSY_STATES:
            return "printing", ""
        if state == "FAILED":
            return "refused", "printer reports FAILED"
    return "unconfirmed", ""


# ---------------------------------------------------------------- discovery

def discover(seconds=6):
    """Listen for the SSDP notices Bambu printers broadcast. Returns a list of
    {ip, serial, model, name} dicts. Printers announce every few seconds."""
    found = {}
    socks = []
    for port in (2021, 1990):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                try:
                    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except OSError:
                    pass
            s.bind(("", port))
            socks.append(s)
        except OSError:
            pass
    try:  # also ask, in case the printer only answers searches
        q = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        q.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        msg = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1990\r\nMAN: \"ssdp:discover\"\r\n"
               "MX: 3\r\nST: urn:bambulab-com:device:3dprinter:1\r\n\r\n").encode()
        for addr in (("239.255.255.250", 1990), ("255.255.255.255", 2021)):
            try:
                q.sendto(msg, addr)
            except OSError:
                pass
        socks.append(q)
    except OSError:
        pass

    deadline = time.monotonic() + seconds
    while socks and time.monotonic() < deadline:
        r, _, _ = select.select(socks, [], [], max(0.0, deadline - time.monotonic()))
        for s in r:
            try:
                data, addr = s.recvfrom(4096)
            except OSError:
                continue
            info = parse_ssdp(data.decode("utf-8", "replace"), addr[0])
            if info:
                found[info["serial"] or info["ip"]] = info
    for s in socks:
        s.close()
    return sorted(found.values(), key=lambda d: d["name"])


def parse_ssdp(text, sender_ip):
    headers = {}
    for line in text.split("\r\n")[1:]:
        if ":" in line:
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
    if "bambulab" not in headers.get("nt", "") + headers.get("st", ""):
        return None
    serial = headers.get("usn", "").split("::")[0].replace("uuid:", "")
    return {
        "ip": headers.get("location") or sender_ip,
        "serial": serial,
        "model": headers.get("devmodel.bambu.com", ""),
        "name": headers.get("devname.bambu.com", "") or serial,
    }
