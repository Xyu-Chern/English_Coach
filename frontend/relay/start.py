"""Start the phone connector for this WSL session without saving credentials."""

import getpass
import os
from pathlib import Path
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    for name in ("COACH_SITE_ACCESS", "COACH_RELAY_SECRET"):
        if not env.get(name):
            env[name] = getpass.getpass(f"{name} (hidden): ")
        if not env[name]:
            raise SystemExit("Missing connector credentials")
    process = subprocess.Popen(
        [sys.executable, "-m", "frontend.relay.connector"],
        cwd=root,
        env=env,
        start_new_session=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print(f"Started phone connector (PID {process.pid})")


if __name__ == "__main__":
    main()
