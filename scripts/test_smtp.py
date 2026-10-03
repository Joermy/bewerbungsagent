from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path

from aiosmtpd.controller import Controller
from aiosmtpd.smtp import AuthResult


class Ablage:
    def __init__(self, ordner: Path):
        self.ordner = ordner
        self.ordner.mkdir(parents=True, exist_ok=True)
        self.zaehler = 0

    async def handle_DATA(self, server, session, envelope):
        self.zaehler += 1
        name = f"{datetime.now():%Y%m%d_%H%M%S}_{self.zaehler:02d}.eml"
        kopf = f"X-Envelope-To: {', '.join(envelope.rcpt_tos)}\r\n".encode()
        (self.ordner / name).write_bytes(kopf + envelope.content)
        print(f"{name}  an {', '.join(envelope.rcpt_tos)}", flush=True)
        return "250 OK (Testserver, nicht zugestellt)"


def main():
    args = argparse.ArgumentParser()
    args.add_argument("--port", type=int, default=2525)
    args.add_argument("--ordner", default="testlauf/smtp_eingang")
    a = args.parse_args()
    controller = Controller(Ablage(Path(a.ordner)), hostname="127.0.0.1", port=a.port,
                            auth_require_tls=False, authenticator=lambda *_: AuthResult(success=True))
    controller.start()
    print(f"Test-SMTP auf 127.0.0.1:{a.port}, Ablage {a.ordner}", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        controller.stop()


if __name__ == "__main__":
    main()
