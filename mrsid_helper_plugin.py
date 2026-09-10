import os
import re
import sys
import glob

from qgis.PyQt.QtCore import Qt, QUrl, QEventLoop, QCoreApplication, QTimer
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QAction, QMessageBox, QProgressDialog
)
from qgis.PyQt.QtNetwork import QNetworkAccessManager, QNetworkRequest

try:
    from osgeo import gdal
    _GDAL_AVAILABLE = True
except ImportError:
    _GDAL_AVAILABLE = False


def _qgis_version_tuple():
    """Return (major, minor, patch) of the running QGIS as ints."""
    try:
        from qgis.core import Qgis
        ver = Qgis.QGIS_VERSION  # e.g. "3.44.14-Solothurn"
        parts = ver.split("-")[0].split(".")
        return tuple(int(p) for p in parts[:3])
    except Exception as e:
        print(f"[MrSID Helper] Warning reading QGIS version: {e}")
        return (3, 0, 0)


class MrSIDHelperPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        # Will be set by setup_gdal_driver_path() if ABI mismatch is detected
        self._abi_warning_info = None
        self.setup_gdal_driver_path()

    # ── GDAL ABI compatibility helpers ────────────────────────────────────────

    def _get_driver_gdal_soname(self, driver_so=None):
        """
        Read the GDAL SONAME required by the target gdal_MrSID.so.
        Inspects binary content directly without external processes.
        Returns an int (e.g. 38 or 39) or None.
        """
        if not driver_so:
            driver_so = "/Library/Application Support/MrSID-QGIS/gdalplugins/gdal_MrSID.so"
        if not os.path.exists(driver_so):
            return None
        try:
            with open(driver_so, "rb") as f:
                content = f.read()
            m = re.search(rb'libgdal\.(\d+)\.dylib', content)
            if m:
                return int(m.group(1).decode("ascii"))
        except Exception as e:
            print(f"[MrSID Helper] Could not read driver SONAME for {driver_so}: {e}")
        return None

    def _get_qgis_gdal_soname(self):
        """
        Detect the GDAL major SONAME bundled in the running QGIS installation.
        Searches QGIS.app/Contents/Frameworks/ for libgdal.NN.dylib symlinks.
        Returns an int (e.g. 38 or 39) or None if not determinable.
        """
        qgis_app_candidates = [
            "/Applications/QGIS.app",
            "/Applications/QGIS-LTR.app",
            "/Applications/QGIS-4.0.app",
            "/Applications/QGIS-4.2.app",
            "/Applications/QGIS-4.4.app",
            "/Applications/QGIS-3.44.app",
            "/Applications/QGIS-3.40.app",
            "/Applications/QGIS-3.38.app",
            "/Applications/QGIS-3.36.app",
            "/Applications/QGIS-3.34.app",
            os.path.expanduser("~/Applications/QGIS.app"),
            os.path.expanduser("~/Applications/QGIS-LTR.app"),
        ]
        for p in sorted(glob.glob("/Applications/QGIS*.app")):
            if p not in qgis_app_candidates:
                qgis_app_candidates.append(p)

        for app_path in qgis_app_candidates:
            frameworks = os.path.join(app_path, "Contents", "Frameworks")
            if not os.path.isdir(frameworks):
                continue
            for lib in sorted(glob.glob(os.path.join(frameworks, "libgdal.*.dylib"))):
                m = re.search(r'libgdal\.(\d+)\.dylib$', os.path.basename(lib))
                if m:
                    return int(m.group(1))
        return None

    def _remove_gdal_driver_path(self):
        """
        Remove any MrSID GDAL_DRIVER_PATH entry from QgsSettings.
        """
        try:
            from qgis.core import QgsSettings
            settings = QgsSettings()
            target_base = "/Library/Application Support/MrSID-QGIS/gdalplugins"
            vars_list = settings.value("qgis/customEnvVars", [])
            if not isinstance(vars_list, list):
                vars_list = [vars_list] if vars_list else []

            new_vars = [
                str(item) for item in vars_list
                if not ("GDAL_DRIVER_PATH=" in str(item) and target_base in str(item))
            ]
            settings.setValue("qgis/customEnvVars", new_vars)
        except Exception as e:
            print(f"[MrSID Helper] Error removing customEnvVars: {e}")

    def _show_abi_warning(self):
        """
        Show the GDAL ABI mismatch warning dialog if no compatible driver is available.
        """
        if not self._abi_warning_info:
            return
        driver_v, qgis_v = self._abi_warning_info
        try:
            from qgis.core import QgsSettings
            settings = QgsSettings()
            warned_key = f"mrsid_helper/abi_warning_shown_{driver_v}_{qgis_v}"
            if settings.value(warned_key, False, type=bool):
                return
            settings.setValue(warned_key, True)
        except Exception as e:
            print(f"[MrSID Helper] QgsSettings warning check note: {e}")

        QMessageBox.warning(
            self.iface.mainWindow(),
            "MrSID Driver — GDAL Version Mismatch",
            f"The installed MrSID driver was built for GDAL {driver_v},\n"
            f"but your QGIS uses GDAL {qgis_v}.\n\n"
            "MrSID support has been automatically disabled to prevent\n"
            "QGIS startup errors.\n\n"
            "To fix this, please check for an updated installer at:\n"
            "  https://github.com/satyamgeo/qgis-mrsid-macos/releases\n\n"
            "Or use QGIS LTR which uses an older GDAL version."
        )

    # ── Core setup ────────────────────────────────────────────────────────────

    def setup_gdal_driver_path(self):
        """
        Inject GDAL_DRIVER_PATH into QgsSettings.
        Smartly selects gdal39 (GDAL 3.13 / QGIS 3.44+) or gdal38 (GDAL 3.8 / QGIS 3.28-3.38).
        """
        try:
            base_dir = "/Library/Application Support/MrSID-QGIS/gdalplugins"
            if not os.path.exists(base_dir):
                return

            qgis_gdal = self._get_qgis_gdal_soname()  # e.g. 39 or 38

            target_path = None
            if qgis_gdal == 39 and os.path.exists(os.path.join(base_dir, "gdal39", "gdal_MrSID.so")):
                target_path = os.path.join(base_dir, "gdal39")
            elif qgis_gdal == 38 and os.path.exists(os.path.join(base_dir, "gdal38", "gdal_MrSID.so")):
                target_path = os.path.join(base_dir, "gdal38")
            elif os.path.exists(os.path.join(base_dir, "gdal_MrSID.so")):
                target_path = base_dir

            if not target_path:
                print(f"[MrSID Helper] No MrSID driver directory found for GDAL {qgis_gdal}.")
                return

            driver_so = os.path.join(target_path, "gdal_MrSID.so")
            driver_gdal = self._get_driver_gdal_soname(driver_so)

            if driver_gdal is not None and qgis_gdal is not None:
                if driver_gdal != qgis_gdal:
                    self._remove_gdal_driver_path()
                    self._abi_warning_info = (driver_gdal, qgis_gdal)
                    print(
                        f"[MrSID Helper] ABI mismatch: driver=libgdal.{driver_gdal}, "
                        f"QGIS=libgdal.{qgis_gdal}. GDAL_DRIVER_PATH NOT set."
                    )
                    return

            # Compatible — inject GDAL_DRIVER_PATH
            from qgis.core import QgsSettings
            settings = QgsSettings()
            settings.setValue("qgis/customEnvVarsUse", True)

            expected_entry = f"prepend|GDAL_DRIVER_PATH={target_path}"
            vars_list = settings.value("qgis/customEnvVars", [])
            if not isinstance(vars_list, list):
                vars_list = [vars_list] if vars_list else []

            found = False
            new_vars = []
            for item in vars_list:
                item_str = str(item)
                if "GDAL_DRIVER_PATH=" in item_str:
                    if target_path in item_str:
                        found = True
                        new_vars.append(item_str)
                    else:
                        parts = item_str.split("=", 1)
                        action_var = parts[0]
                        val = parts[1]
                        new_vars.append(f"{action_var}={target_path}:{val}")
                        found = True
                else:
                    new_vars.append(item_str)

            if not found:
                new_vars.append(expected_entry)

            settings.setValue("qgis/customEnvVars", new_vars)

        except Exception as e:
            print(f"[MrSID Helper] Error in setup_gdal_driver_path: {e}")

    def initGui(self):
        """Called by QGIS when plugin is loaded into GUI."""
        if self._abi_warning_info:
            QTimer.singleShot(1500, self._show_abi_warning)

        # Standard plugin action setup
        icon_path = os.path.join(os.path.dirname(__file__), "icon.png")
        if not os.path.exists(icon_path):
            icon_path = ":/images/themes/default/mActionAddRasterLayer.svg"

        self.action = QAction(
            QIcon(icon_path),
            "MrSID Helper — Status & Tools",
            self.iface.mainWindow()
        )
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu("&MrSID Helper", self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        """Called by QGIS when plugin is unloaded/disabled."""
        if self.action:
            self.iface.removePluginMenu("&MrSID Helper", self.action)
            self.iface.removeToolBarIcon(self.action)

    def run(self):
        """Action handler when user clicks the MrSID plugin icon."""
        msg = []
        msg.append("<b>MrSID QGIS Integration Status</b><br><hr>")

        qgis_gdal = self._get_qgis_gdal_soname()
        msg.append(f"<b>Running QGIS GDAL Major:</b> {qgis_gdal or 'Unknown'}<br>")

        if self._abi_warning_info:
            driver_v, qgis_v = self._abi_warning_info
            msg.append(
                f"<br><font color='red'><b>⚠️ GDAL ABI Mismatch Detected</b></font><br>"
                f"Driver requires GDAL {driver_v}, but QGIS uses GDAL {qgis_v}.<br>"
                f"MrSID support is disabled to prevent QGIS startup errors."
            )
        else:
            msg.append("<br><font color='green'><b>✅ MrSID Driver Active & Compatible</b></font>")

        QMessageBox.information(self.iface.mainWindow(), "MrSID Helper", "".join(msg))
