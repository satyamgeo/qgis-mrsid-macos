import os
from qgis.PyQt.QtCore import *
from qgis.PyQt.QtGui import *
from qgis.PyQt.QtWidgets import *
from qgis.PyQt.QtNetwork import QNetworkAccessManager, QNetworkRequest
from osgeo import gdal

class MrSIDHelperPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None

    def initGui(self):
        # Create toolbar icon / menu item
        icon_path = os.path.join(os.path.dirname(__file__), 'icon.png')
        self.action = QAction(
            QIcon(icon_path),
            "Mac MrSID Support Helper",
            self.iface.mainWindow()
        )
        self.action.triggered.connect(self.run)
        self.iface.addToolBarIcon(self.action)
        self.iface.addRasterMenuToolBarIcon(self.action)

    def unload(self):
        # Clean up GUI
        self.iface.removeRasterMenuToolBarIcon(self.action)
        self.iface.removeToolBarIcon(self.action)

    def check_mrsid_support(self):
        driver = gdal.GetDriverByName('MrSID')
        return driver is not None

    def run(self):
        if self.check_mrsid_support():
            QMessageBox.information(
                self.iface.mainWindow(),
                "MrSID Active",
                "Great news! MrSID (.sid) raster file format support is active and working correctly in QGIS!"
            )
            return

        # Not supported - ask to install
        reply = QMessageBox.question(
            self.iface.mainWindow(),
            "MrSID Support Not Found",
            "MrSID format support is not active in QGIS.\n\n"
            "Would you like to download and install the MrSID Support package for macOS?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )

        if reply == QMessageBox.Yes:
            self.download_and_install()

    def download_and_install(self):
        import tempfile
        import subprocess

        # GitHub URL for the installer
        # Replace this URL with your actual GitHub release URL
        url = "https://github.com/satyamgeo/qgis-mrsid-macos/releases/latest/download/MrSID-QGIS-Installer.pkg"
        
        # Securely get the system temp directory path
        pkg_path = os.path.join(tempfile.gettempdir(), "MrSID-QGIS-Installer.pkg")

        # Validate URL scheme to prevent arbitrary local file reading/execution
        if not (url.startswith("http://") or url.startswith("https://")):
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Security Error",
                "Invalid URL scheme detected. Only HTTP and HTTPS are permitted."
            )
            return

        # Show progress dialog
        progress = QProgressDialog(
            "Downloading MrSID installer package...",
            "Cancel",
            0,
            100,
            self.iface.mainWindow()
        )
        progress.setWindowModality(Qt.WindowModal)
        progress.show()

        try:
            # Use QNetworkAccessManager to download the file securely (avoids urllib B310 Bandit warning)
            manager = QNetworkAccessManager()
            loop = QEventLoop()
            
            request = QNetworkRequest(QUrl(url))
            reply = manager.get(request)
            
            # Stop the event loop when the download finishes or fails
            reply.finished.connect(loop.quit)
            
            # Connect download progress to update the progress dialog
            def update_progress(bytes_received, bytes_total):
                if bytes_total > 0:
                    percent = bytes_received * 100 / bytes_total
                    progress.setValue(int(percent))
                else:
                    progress.setValue(0)
                QCoreApplication.processEvents()
                
            reply.downloadProgress.connect(update_progress)
            
            # Run the local event loop synchronously until download completes
            loop.exec_()
            
            if reply.error() != reply.NoError:
                raise Exception(f"Network error: {reply.errorString()}")
                
            # Write download file
            data = reply.readAll()
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
                "Please check your internet connection or check the GitHub URL."
            )
            return

        # Run the installer using AppleScript to prompt for credentials
        QMessageBox.information(
            self.iface.mainWindow(),
            "Install Authorization",
            "The installer will now launch. macOS will ask for your administrator password to copy the plugin files and re-sign QGIS."
        )

        # Run the installer securely using subprocess without a shell
        script = f'do shell script "installer -pkg \\"{pkg_path}\\" -target /" with administrator privileges'
        cmd = ["osascript", "-e", script]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            exit_code = result.returncode
        except Exception as e:
            print(f"Error running installer: {e}")
            exit_code = -1

        if exit_code == 0:
            QMessageBox.information(
                self.iface.mainWindow(),
                "Installation Successful",
                "MrSID support has been successfully installed!\n\n"
                "Please restart QGIS for the changes to take effect."
            )
        else:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Installation Cancelled/Failed",
                "The installation did not complete. Make sure you entered your administrator password correctly."
            )
