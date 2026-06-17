def classFactory(iface):
    from .mrsid_helper_plugin import MrSIDHelperPlugin
    return MrSIDHelperPlugin(iface)
