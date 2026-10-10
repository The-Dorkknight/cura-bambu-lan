# Contributing

Thanks for helping. Reports from real printers (model, firmware, what happened) are the most useful thing right now.

## Licence of contributions

By sending a pull request, patch or other contribution you agree that it is licensed under the same terms as the rest of the project, the [PolyForm Noncommercial License 1.0.0](LICENSE.md), and that the Required Notice (Copyright Matthew Armstrong) continues to cover the project. Only contribute work you have the right to give.

## Reporting a bug

Use **Issues → New issue → Bug report**. Please include:

- the plugin version (**Extensions → Bambu LAN → About**),
- your Cura version and operating system,
- the full **Test connection** report (it shows model and firmware; the serial number can be blanked out),
- the exact error message,
- the `Bambu LAN` lines from `cura.log` (**Help → Show Configuration Folder**).

**Never post your access code.** For security problems, don't open an issue; see [SECURITY.md](SECURITY.md).

## Changing the code

1. Fork, then make a branch.
2. Keep `BambuLAN/bambu_lan.py` free of Cura imports so it stays testable.
3. If you change how the printer is spoken to, teach `tests/fake_printer.py` the same behaviour and add a test.
4. Run the tests: `python3 -m unittest discover -s tests -v` (needs the `openssl` command).
5. Build and try it in Cura: `python3 tools/build_curapackage.py`, then drag `dist/*.curapackage` onto Cura.
6. Add a line to [CHANGELOG.md](CHANGELOG.md) and open a pull request saying which printer and firmware you tested on, if any.

New source files start with:

```
# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
```
