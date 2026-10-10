# Third-party notices

The PolyForm Noncommercial licence in [LICENSE.md](LICENSE.md) covers **only my own code** in this repository. Everything below belongs to its authors and keeps its own terms. This project is **not affiliated with or endorsed by** Bambu Lab, UltiMaker or any project listed here.

| Item | Used for | Terms |
|---|---|---|
| **Bambu Lab CA certificates** (`BambuLAN/bambu_ca.pem`) | Verifying that the device on the other end is a genuine Bambu printer. These are Bambu Lab's public certificates (public keys, no code), as collected by OpenBambuAPI. | Owned by Bambu Lab. Included only for interoperability. Delete the file and tick *Skip certificate check* if you prefer not to ship it. |
| [OpenBambuAPI](https://github.com/Doridian/OpenBambuAPI) | Community documentation of the LAN protocol (MQTT commands, FTPS details, TLS notes). This plugin is an independent implementation; no text or code is copied from it apart from the public certificates above. | [GNU Free Documentation License 1.3](https://github.com/Doridian/OpenBambuAPI/blob/main/LICENSE.md) |
| [bambulabs_api](https://github.com/BambuTools/bambulabs_api) | Reference for implicit FTPS with TLS session reuse and the print command. Not included. | [MIT](https://github.com/BambuTools/bambulabs_api/blob/main/LICENSE) |
| [ha-bambulab](https://github.com/greghesp/ha-bambulab) (Home Assistant integration) | Reference for which models use `file:///sdcard/` vs `ftp:///` and for reading the model from version messages. Not included. | [MIT](https://github.com/greghesp/ha-bambulab/blob/main/LICENSE) |
| [UltiMaker Cura](https://github.com/Ultimaker/Cura) and [Uranium](https://github.com/Ultimaker/Uranium) | The plugin runs inside Cura and calls its plugin APIs. Nothing from Cura is copied or shipped here. | [LGPL-3.0](https://github.com/Ultimaker/Cura/blob/main/LICENSE) |
| [PyQt6](https://www.riverbankcomputing.com/software/pyqt/) / [Qt](https://www.qt.io/) | Provided by Cura at run time for the dialog; not shipped here. | GPL / LGPL (see their sites). The dialog code imports PyQt6 from Cura, as most Cura plugins do; if you redistribute this plugin commercially together with Qt, check those terms yourself (this is not legal advice). |

Thanks to everyone who reverse-engineered and documented the Bambu LAN protocol; this plugin would not exist without that work.

"Bambu Lab", "UltiMaker" and "Cura" are trademarks of their owners and are used only to say what this plugin works with.
