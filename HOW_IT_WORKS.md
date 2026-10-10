# How Bambu LAN Print works

Plain-English notes on what the plugin does on your computer and on the network.

## What it reads, changes, and never does

| | |
|---|---|
| **Reads** | The G-code Cura has produced for the current plate; status and version messages from the printer. |
| **Sends** | One `.gcode.3mf` file to the printer's SD card, and a small set of commands: *report your version*, *send a full status*, *print this file*. |
| **Stores** | Per Cura printer: IP, access code, optional serial and your print options (in Cura's machine settings). One Cura preference records that you accepted the notice. |
| **Never** | Contacts Bambu's cloud or any internet service, downloads files from the printer, runs anything the printer sends, moves axes or heats anything by itself, or listens for connections except during **Find printers**. |

## The protocol

Bambu printers expose two services on the local network, both protected by TLS and the printer's 8-character **access code** (user name `bblp`). The commands were reverse-engineered and documented by the community in [OpenBambuAPI](https://github.com/Doridian/OpenBambuAPI).

| Service | Port | Used for |
|---|---|---|
| **MQTT** over TLS | 8883 | Commands to `device/<serial>/request`, replies and status on `device/<serial>/report`. |
| **FTPS**, implicit TLS | 990 | Uploading the job to the SD card. |
| **SSDP** broadcasts (UDP) | 2021 / 1990 | The printer announces its IP, serial, model and name every few seconds. Only used by **Find printers**. |

The plugin contains its own small MQTT 3.1.1 client (about 150 lines, QoS 0 only), so it needs no extra libraries.

## What happens when you click Print over LAN

1. **Get the G-code.** Cura's own G-code writer produces the file, with any post-processing scripts applied.
2. **Wrap it.** Bambu printers run jobs from a 3MF container. The plugin makes a minimal one: `Metadata/plate_1.gcode` plus `Metadata/plate_1.gcode.md5`.
3. **Connect.** If no serial number is set, it's read from the printer's TLS certificate (the certificate is issued to the serial). Then an MQTT login.
4. **Ask the printer about itself.** `info.get_version` gives the model and firmware. Older firmware reports the model through hardware codes (`AP05` + `N2S` = A1); newer firmware gives a product name. Both are understood.
5. **Check it's ready.** `pushall` returns the state. If it's already printing, or reports no SD card, the plugin stops before uploading.
6. **Upload** over FTPS. The data connection reuses the control connection's TLS session, which the printer requires.
7. **Start.** A `print.project_file` command names the file. The address differs by model:
   - `file:///sdcard/<name>` on A1, A1 mini, P1P, P1S and X1 series,
   - `ftp:///<name>` on newer models such as the H2 series.

   This is the same split the [Home Assistant Bambu integration](https://github.com/greghesp/ha-bambulab) uses. If the printer refuses one form, the plugin tries the other once.
8. **Wait for confirmation.** For up to 25 seconds it watches for the printer to report `PREPARE` or `RUNNING`, or a refusal with a reason.

All network work runs on a background thread, so Cura stays responsive; messages are passed back to Cura's main thread.

## Firmware and "Authorization Control"

In 2025 Bambu added an *Authorization Control System* to its firmware. On firmware that has it, the printer ignores print commands from third-party software unless **Developer Mode** is on (which requires LAN-only mode). The versions that introduced it:

| Model | Version |
|---|---|
| A1, A1 mini | 01.05.00.00 |
| P1P, P1S | 01.08.02.00 |
| X1, X1C, X1E | 01.08.03.00 |
| H2D, P2 series | from launch |

Firmware older than these accepts LAN commands with just the access code. **Test connection** compares your firmware with this table and says which applies.

## Security design

- **TLS is always on.** Certificates are checked against Bambu Lab's certificate authorities (`BambuLAN/bambu_ca.pem`, public certificates from OpenBambuAPI) and the host name is checked against the printer's serial. A device that isn't a genuine Bambu printer never gets your access code. *Skip certificate check* turns this off for unusual firmware.
- **Only outgoing connections.** Your computer always starts the connection, so a firewall that blocks incoming traffic doesn't affect printing. The only listener is the UDP discovery socket, open for 8 seconds when you click **Find printers**.
- **Printer data is treated as untrusted.** MQTT payloads are parsed with `json.loads` only. Text from the printer (error reasons, names) is shown as plain text, never as markup. Nothing is downloaded, saved or executed.
- **Python's standard library** does the networking (`ssl`, `socket`, `ftplib`, `zipfile`), so there are no third-party packages to audit.
- **The printer itself** runs closed firmware. Keeping it on a network without internet access, and away from devices you care about, is the most effective protection. The plugin works fine that way.

## Files

| File | Purpose |
|---|---|
| `BambuLAN/__init__.py` | Registers the output device and the menu with Cura. |
| `BambuLAN/BambuLANPlugin.py` | Cura side: the **Print over LAN** button, progress messages, settings storage, setup dialog backend, About. |
| `BambuLAN/BambuSetup.qml` | The setup dialog. |
| `BambuLAN/bambu_lan.py` | Everything network: TLS, the MQTT client, FTPS upload, 3MF wrapping, discovery, model detection. No Cura imports. |
| `BambuLAN/bambu_ca.pem` | Bambu Lab's public CA certificates, used to verify the printer. |
| `tests/fake_printer.py` | A simulated printer (TLS MQTT broker + FTPS server) for tests. |
| `tests/test_protocol.py` | Protocol tests against the simulator. |
| `tools/build_curapackage.py` | Builds the `.curapackage` for a release. |

Run the tests with `python3 -m unittest discover -s tests -v` (Python 3.8+ and the `openssl` command, which Linux and macOS include).
