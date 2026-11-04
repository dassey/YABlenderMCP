"""The yab-mcp command.

    yab-mcp                 run the MCP server (stdio) - what MCP clients start
    yab-mcp --check         check the server and whether the Blender add-on answers
    yab-mcp install ...     install the add-on into Blender (see yab-mcp install --help)
    yab-mcp uninstall ...   remove it again
    yab-mcp build-addon     write yab-mcp-addon.zip for Blender's Install from Disk
    yab-mcp --version
"""

import sys

from . import __version__


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv and argv[0] in ("install", "uninstall", "build-addon"):
        from . import installer  # no MCP SDK import: install must work before the network guard exists
        sys.exit(installer.main(argv))
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return
    if argv and argv[0] in ("-V", "--version"):
        print(__version__)
        return
    from . import server
    if "--check" in argv:
        sys.exit(server.check())
    server.serve()
