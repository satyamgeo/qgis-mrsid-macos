import os
import sys

from qgis.PyQt.QtCore import Qt, QUrl, QEventLoop, QCoreApplication
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
        ver = Qgis.QGIS_VERSION  # e.g. "3.40.3-Bratislava"
        parts = ver.split("-")[0].split(".")
        return tuple(int(p) for p in parts[:3])
    except Exception:
        return (3, 0, 0)


class MrSIDHelperPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None

    def initGui(self):
        icon_path = os.path.join(os.path.dirname(__file__), 'icon.png')
        self.action = QAction(
            QIcon(icon_path),
            "Mac MrSID Support Helper",
            self.iface.mainWindow()
        )
        self.action.triggered.connect(self.run)

        # addToolBarIcon is available in all QGIS versions
        self.iface.addToolBarIcon(self.action)

        # addRasterToolBarIcon was removed in some QGIS 4.x builds — guard it
        if hasattr(self.iface, 'addRasterToolBarIcon'):
            try:
                self.iface.addRasterToolBarIcon(self.action)
            except Exception:
                pass

        # Also add to the Plugins menu for visibility
        self.iface.addPluginToRasterMenu("&Mac MrSID Support Helper", self.action)

    def unload(self):
        self.iface.removePluginRasterMenu("&Mac MrSID Support Helper", self.action)
        self.iface.removeToolBarIcon(self.action)
        if hasattr(self.iface, 'removeRasterToolBarIcon'):
            try:
                self.iface.removeRasterToolBarIcon(self.action)
            except Exception:
                pass

    def check_mrsid_support(self):
        if not _GDAL_AVAILABLE:
            return False
        driver = gdal.GetDriverByName('MrSID')
        return driver is not None

    def run(self):
        if self.check_mrsid_support():
            QMessageBox.information(
                self.iface.mainWindow(),
                "MrSID Active",
                "Great news! MrSID (.sid) raster file format support is active "
                "and working correctly in QGIS!"
            )
            return

        qver = _qgis_version_tuple()
        ver_str = ".".join(str(x) for x in qver)

        reply = QMessageBox.question(
            self.iface.mainWindow(),
            "MrSID Support Not Found",
            f"MrSID format support is not active in QGIS {ver_str}.\n\n"
            "Would you like to download and install the MrSID Support package for macOS?\n\n"
            "The installer supports QGIS 3.0 – 4.x on Intel and Apple Silicon.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )

        if reply == QMessageBox.Yes:
            self.download_and_install()

    def download_and_install(self):
        import tempfile
        import subprocess

        url = (
            "https://github.com/satyamgeo/qgis-mrsid-macos"
            "/releases/latest/download/MrSID-QGIS-Installer.pkg"
        )
        pkg_path = os.path.join(tempfile.gettempdir(), "MrSID-QGIS-Installer.pkg")

        if not (url.startswith("http://") or url.startswith("https://")):
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Security Error",
                "Invalid URL scheme detected. Only HTTP and HTTPS are permitted."
            )
            return

        progress = QProgressDialog(
            "Downloading MrSID installer package…",
            "Cancel",
            0,
            100,
            self.iface.mainWindow()
        )
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.show()
        QCoreApplication.processEvents()

        try:
            manager = QNetworkAccessManager()
            loop = QEventLoop()

            request = QNetworkRequest(QUrl(url))

            # Qt5 vs Qt6 redirect attribute name
            try:
                # Qt6 / QGIS 3.28+
                from qgis.PyQt.QtNetwork import QNetworkRequest as _NR
                attr = _NR.Attribute.RedirectPolicyAttribute
                request.setAttribute(attr, True)
            except AttributeError:
                try:
                    # Qt5 older QGIS
                    request.setAttribute(
                        QNetworkRequest.FollowRedirectsAttribute, True
                    )
                except AttributeError:
                    pass  # Redirect following not available — not fatal

            net_reply = manager.get(request)
            net_reply.finished.connect(loop.quit)

            def update_progress(bytes_received, bytes_total):
                if progress.wasCanceled():
                    net_reply.abort()
                    loop.quit()
                    return
                if bytes_total > 0:
                    progress.setValue(int(bytes_received * 100 / bytes_total))
                else:
                    # Unknown size — pulse
                    progress.setValue(min(progress.value() + 1, 95))
                QCoreApplication.processEvents()

            net_reply.downloadProgress.connect(update_progress)
            loop.exec_()

            if progress.wasCanceled():
                QMessageBox.information(
                    self.iface.mainWindow(),
                    "Cancelled",
                    "Download was cancelled."
                )
                return

            if net_reply.error() != net_reply.NoError:
                raise Exception(f"Network error: {net_reply.errorString()}")

            status_code = net_reply.attribute(
                QNetworkRequest.HttpStatusCodeAttribute
            )
            if status_code and status_code != 200:
                raise Exception(
                    f"HTTP {status_code}: Failed to download installer."
                )

            data = net_reply.readAll()
            if len(data) < 1024:
                raise Exception(
                    "Downloaded file is too small — the URL may be incorrect "
                    "or the release has not been published yet."
                )

            with open(pkg_path, "wb") as f:
                f.write(data)

            progress.setValue(100)
            progress.close()

        except Exception as e:
            progress.close()
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Download Error",
                f"Failed to download installer package:\n{e}\n\n"
                "Please check your internet connection or visit:\n"
                "https://github.com/satyamgeo/qgis-mrsid-macos/releases"
            )
            return

        QMessageBox.information(
            self.iface.mainWindow(),
            "Launch Installer",
            "The MrSID Support installer package will now open.\n\n"
            "Please follow the installation steps and enter your administrator "
            "password when prompted.\n\n"
            "Once installation completes, RESTART QGIS for the changes to take effect."
        )

        try:
            result = subprocess.run(
                ["open", pkg_path],
                capture_output=True,
                text=True,
                check=False
            )
            exit_code = result.returncode
        except Exception as e:
            print(f"[MrSID Helper] Error opening installer: {e}")
            exit_code = -1

        if exit_code != 0:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Could Not Open Installer Automatically",
                f"The installer could not be opened automatically.\n\n"
                f"You can find the downloaded installer at:\n{pkg_path}\n\n"
                "Please double-click it in Finder to install manually.\n\n"
                "If macOS blocks it, go to:\n"
                "System Settings → Privacy & Security → Open Anyway"
            )

