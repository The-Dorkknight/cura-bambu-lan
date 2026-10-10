# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
#
# A simulated Bambu Lab printer for the tests: a TLS MQTT broker and an
# implicit-FTPS server on localhost. It enforces the behaviour that matters:
# access code login, the serial-number topics, TLS session reuse on the FTPS
# data channel, busy/SD-card state, and per-model print URLs.
# Test certificates are generated on the fly with the `openssl` command.

import json
import os
import socket
import ssl
import struct
import subprocess
import threading
import time

SERIAL = "01P00A123456789"
CODE = "12345678"

VERSIONS = {
    # older A1 firmware: model only visible through hw_ver + project_name
    "A1_old": [{"name": "ota", "sw_ver": "01.04.02.00", "hw_ver": "OTA", "sn": SERIAL},
               {"name": "esp32", "sw_ver": "01.04.02.00", "hw_ver": "AP05", "project_name": "N2S", "sn": SERIAL}],
    "A1_new": [{"name": "ota", "sw_ver": "01.06.01.00", "product_name": "Bambu Lab A1", "sn": SERIAL}],
    "H2D": [{"name": "ota", "sw_ver": "01.02.00.00", "product_name": "Bambu Lab H2D", "sn": SERIAL}],
}


def _openssl(*args, cwd):
    subprocess.run(["openssl"] + list(args), cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def make_certs(folder):
    """Create a test CA, a printer certificate issued to SERIAL by that CA,
    and a self-signed 'rogue' certificate with the same name."""
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "ca.ext"), "w") as f:
        f.write("basicConstraints=critical,CA:TRUE\nkeyUsage=critical,keyCertSign,cRLSign\n")
    _openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "ca.key", "-out", "ca.pem",
             "-days", "30", "-subj", "/C=CN/O=Test/CN=Test CA",
             "-addext", "basicConstraints=critical,CA:TRUE",
             "-addext", "keyUsage=critical,keyCertSign,cRLSign", cwd=folder)
    _openssl("req", "-newkey", "rsa:2048", "-nodes", "-keyout", "leaf.key", "-out", "leaf.csr",
             "-subj", "/CN=" + SERIAL, cwd=folder)
    _openssl("x509", "-req", "-in", "leaf.csr", "-CA", "ca.pem", "-CAkey", "ca.key",
             "-CAcreateserial", "-out", "leaf.pem", "-days", "30", cwd=folder)
    _openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", "rogue.key", "-out", "rogue.pem",
             "-days", "30", "-subj", "/CN=" + SERIAL, cwd=folder)
    return os.path.join(folder, "ca.pem")


class FakePrinter:
    def __init__(self, certs, cert="leaf", state="IDLE", sdcard=True, refuse_job=False,
                 never_confirm=False, model=None):
        self.state, self.sdcard = state, sdcard
        self.refuse_job, self.never_confirm, self.model = refuse_job, never_confirm, model
        self.files, self.requests, self.reused = {}, [], []
        self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.ctx.load_cert_chain(os.path.join(certs, cert + ".pem"), os.path.join(certs, cert + ".key"))
        self._servers = []
        self.mqtt_port = self._listen(self._mqtt_client)
        self.ftp_port = self._listen(self._ftp_client)

    def _listen(self, handler):
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", 0))
        s.listen(5)
        self._servers.append(s)
        threading.Thread(target=self._accept, args=(s, handler), daemon=True).start()
        return s.getsockname()[1]

    def _accept(self, s, handler):
        while True:
            try:
                c, _ = s.accept()
            except OSError:
                return
            threading.Thread(target=self._safe, args=(handler, c), daemon=True).start()

    def _safe(self, handler, c):
        try:
            handler(self.ctx.wrap_socket(c, server_side=True))
        except Exception:
            pass

    def stop(self):
        for s in self._servers:
            s.close()

    def jobs(self):
        return [m["print"] for _, m in self.requests if m.get("print", {}).get("command") == "project_file"]

    # ------------------------------------------------------------ MQTT
    def _mqtt_client(self, s):
        f = s.makefile("rb")

        def packet():
            h = f.read(1)
            if not h:
                raise EOFError
            mult, n = 1, 0
            while True:
                b = f.read(1)[0]
                n += (b & 0x7F) * mult
                if not b & 0x80:
                    break
                mult *= 128
            return h[0], f.read(n)

        def send(h, body):
            n, lb = len(body), bytearray()
            while True:
                b, n = n % 128, n // 128
                lb.append(b | (0x80 if n else 0))
                if not n:
                    break
            s.sendall(bytes([h]) + bytes(lb) + body)

        def string(b, i):
            n = struct.unpack("!H", b[i:i + 2])[0]
            return b[i + 2:i + 2 + n].decode(), i + 2 + n

        def report(obj):
            t = ("device/%s/report" % SERIAL).encode()
            send(0x30, struct.pack("!H", len(t)) + t + json.dumps(obj).encode())

        h, b = packet()
        assert h >> 4 == 1
        i = 10
        _client_id, i = string(b, i)
        user, i = string(b, i)
        password, i = string(b, i)
        if user != "bblp" or password != CODE:
            send(0x20, b"\x00\x05")
            return
        send(0x20, b"\x00\x00")
        while True:
            h, b = packet()
            kind = h >> 4
            if kind == 8:  # SUBSCRIBE
                topic, _ = string(b, 2)
                send(0x90, b[:2] + (b"\x00" if topic == "device/%s/report" % SERIAL else b"\x80"))
            elif kind == 3:  # PUBLISH
                topic, i = string(b, 0)
                msg = json.loads(b[i:])
                self.requests.append((topic, msg))
                if topic != "device/%s/request" % SERIAL:
                    continue
                report({"print": {"command": "push_status", "wifi_signal": "-40dBm"}})  # noise, like a real printer
                if msg.get("info", {}).get("command") == "get_version":
                    if self.model in VERSIONS:
                        report({"info": {"command": "get_version", "module": VERSIONS[self.model], "result": "success"}})
                elif "pushing" in msg:
                    st = {"command": "push_status", "gcode_state": self.state}
                    if self.sdcard is not None:
                        st["sdcard"] = self.sdcard
                    report({"print": st})
                elif msg.get("print", {}).get("command") == "project_file":
                    self._job(msg["print"], report)
            elif kind == 12:  # PINGREQ
                send(0xD0, b"")
            elif kind == 14:  # DISCONNECT
                return

    def _job(self, p, report):
        seq = p["sequence_id"]
        if self.refuse_job:
            report({"print": {"command": "project_file", "result": "FAIL", "reason": "file not found", "sequence_id": seq}})
            return
        want = {"H2D": "ftp:///", "A1_old": "file:///sdcard/", "A1_new": "file:///sdcard/"}.get(self.model)
        if want and not p["url"].startswith(want):
            report({"print": {"command": "project_file", "result": "FAIL", "reason": "url not supported", "sequence_id": seq}})
            return
        report({"print": {"command": "project_file", "result": "success", "sequence_id": seq}})
        if not self.never_confirm:
            time.sleep(0.3)
            report({"print": {"command": "push_status", "gcode_state": "PREPARE", "gcode_file": p["file"]}})

    # ------------------------------------------------------------ FTPS
    def _ftp_client(self, s):
        f = s.makefile("rb")

        def say(text):
            s.sendall((text + "\r\n").encode())

        say("220 fake bambu ftp")
        user, authed, pasv = None, False, None
        while True:
            line = f.readline().decode().strip()
            if not line:
                return
            cmd, _, arg = line.partition(" ")
            cmd = cmd.upper()
            if cmd == "USER":
                user = arg
                say("331 password please")
            elif cmd == "PASS":
                authed = user == "bblp" and arg == CODE
                say("230 ok" if authed else "530 Login incorrect.")
            elif not authed:
                say("530 login first")
            elif cmd in ("PBSZ", "PROT", "TYPE"):
                say("200 ok")
            elif cmd == "PWD":
                say('257 "/"')
            elif cmd == "PASV":
                pasv = socket.socket()
                pasv.bind(("127.0.0.1", 0))
                pasv.listen(1)
                port = pasv.getsockname()[1]
                say("227 Entering Passive Mode (127,0,0,1,%d,%d)." % (port // 256, port % 256))
            elif cmd == "STOR":
                say("150 ok")
                c, _ = pasv.accept()
                d = self.ctx.wrap_socket(c, server_side=True)
                self.reused.append(d.session_reused)
                if not d.session_reused:  # the printer's vsftpd requires session reuse
                    d.close()
                    say("522 SSL connection failed: session reuse required")
                    continue
                data = b""
                while True:
                    chunk = d.recv(65536)
                    if not chunk:
                        break
                    data += chunk
                d.close()
                self.files[arg] = data
                say("226 Transfer complete.")
            elif cmd == "QUIT":
                say("221 bye")
                return
            else:
                say("502 not implemented")
