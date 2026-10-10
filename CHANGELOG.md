# Changelog

All notable changes are listed here. Versions follow [Semantic Versioning](https://semver.org/).

## [1.1.0-beta.1] - 2026-09-30

First public release, as a **pre-release**: tested inside Cura 5.13.0 against a simulated printer, not yet on real Bambu hardware.

### Added
- Reads the printer's **model and firmware** (older and newer version formats) and shows them in **Test connection**, with whether Developer Mode is needed.
- Model-aware print command: `file:///sdcard/` on A1, A1 mini, P1 and X1; `ftp:///` on newer models. If the printer refuses one form, the other is tried once.
- First-use notice in the setup dialog that must be accepted before saving.
- **Extensions → Bambu LAN → About** with version, copyright and licence.
- Test suite with a simulated printer, `tools/build_curapackage.py`, and a GitHub Actions workflow that tests and publishes a `.curapackage` for each tag.

### Fixed
- Opening the setup dialog or **About** crashed Cura: a helper method named `_version` clashed with an attribute Cura's plugin base class already uses. Found by running the plugin inside a real Cura 5.13.0.
- 1.0.0 always used `ftp:///`, which A1 / P1 / X1 printers may reject.
- Text coming from the printer is shown as plain text, never as markup.
- External-spool jobs send `ams_mapping: [0]` as other LAN clients do.

## [1.0.0] - 2026-09-28

Private test version, not published.

### Added
- **Print over LAN** output device: upload over FTPS and start over MQTT, no cloud.
- Setup dialog: network discovery, connection test, serial number read from the printer's certificate, AMS slot, plate, levelling, calibration and timelapse options.
- TLS verification against Bambu Lab's CA certificates.
- Busy and missing-SD-card checks before uploading.

[1.1.0-beta.1]: https://github.com/The-Dorkknight/cura-bambu-lan/releases/tag/v1.1.0-beta.1
