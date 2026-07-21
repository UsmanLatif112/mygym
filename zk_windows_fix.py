"""Windows-only: keep ZK ping, but stop the flashing CMD window."""

import os
import sys


_PATCHED = False


def silence_zk_ping_console():
    """
    pyzk runs `ping` before connect. On Windows that briefly opens a console.
    Replaces test_ping so ping still runs, without a visible CMD window.
    Sync speed / ping behavior stay the same.
    """
    global _PATCHED
    if _PATCHED or os.name != "nt":
        return

    import subprocess
    from zk.base import ZK_helper

    def test_ping(self):
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        try:
            return (
                subprocess.call(
                    ["ping", "-n", "1", str(self.ip)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creationflags,
                )
                == 0
            )
        except Exception:
            return False

    ZK_helper.test_ping = test_ping
    _PATCHED = True
