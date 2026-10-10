#!/usr/bin/env python3
# Required Notice: Copyright Matthew Armstrong (https://github.com/The-Dorkknight)
# Licensed under the PolyForm Noncommercial License 1.0.0. No warranty.
#
# Builds dist/<PluginId>-<version>.curapackage from the plugin folder.
# Usage: python3 tools/build_curapackage.py [--version 1.2.3]
# The version defaults to plugin.json; --version (e.g. from a git tag) overrides
# it in both plugin.json inside the package and package.json.

import argparse
import json
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PLUGIN_ID = "BambuLAN"
DISPLAY_NAME = "Bambu LAN Print"
REPO = "https://github.com/The-Dorkknight/cura-bambu-lan"

SKIP_DIRS = {"__pycache__"}
SKIP_EXT = {".pyc", ".pyo"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", help="override version (a leading 'v' is removed)")
    ap.add_argument("--out", default=os.path.join(ROOT, "dist"))
    args = ap.parse_args()

    src = os.path.join(ROOT, PLUGIN_ID)
    with open(os.path.join(src, "plugin.json"), encoding="utf-8") as f:
        plugin = json.load(f)
    version = (args.version or plugin["version"]).lstrip("v")
    plugin["version"] = version

    package = {
        "package_id": PLUGIN_ID,
        "package_type": "plugin",
        "display_name": DISPLAY_NAME,
        "description": plugin["description"],
        "package_version": version,
        "sdk_version": 8,
        "sdk_version_semver": "8.0.0",
        "website": REPO,
        "author": {
            "author_id": "The-Dorkknight",
            "display_name": "Matthew Armstrong",
            "website": "https://github.com/The-Dorkknight",
        },
        "license": "PolyForm-Noncommercial-1.0.0",
    }

    os.makedirs(args.out, exist_ok=True)
    out = os.path.join(args.out, "%s-%s.curapackage" % (PLUGIN_ID, version))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("package.json", json.dumps(package, indent=4) + "\n")
        for extra in ("LICENSE.md", "README.md"):
            path = os.path.join(ROOT, extra)
            if os.path.exists(path):
                z.write(path, "files/plugins/%s/%s" % (PLUGIN_ID, extra))
        for dirpath, dirnames, filenames in os.walk(src):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
            for name in sorted(filenames):
                if os.path.splitext(name)[1] in SKIP_EXT:
                    continue
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, src).replace(os.sep, "/")
                arc = "files/plugins/%s/%s" % (PLUGIN_ID, rel)
                if rel == "plugin.json":
                    z.writestr(arc, json.dumps(plugin, indent=4) + "\n")
                else:
                    z.write(full, arc)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
