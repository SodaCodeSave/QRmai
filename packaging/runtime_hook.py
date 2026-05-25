import os
import sys
import ctypes
from pathlib import Path

if sys.platform == "win32" and getattr(sys, 'frozen', False):
    meipass = Path(sys._MEIPASS)
    os.environ["PATH"] = str(meipass) + os.pathsep + os.environ.get("PATH", "")
    for dll_dir in [meipass / "pyzbar", meipass]:
        libiconv = dll_dir / "libiconv.dll"
        libzbar = dll_dir / "libzbar-64.dll"
        if libiconv.exists() and libzbar.exists():
            ctypes.WinDLL(str(libiconv))
            ctypes.WinDLL(str(libzbar))
            break
