"""Run the local UI and, when available, its Hermes gateway."""

import argparse
import os
import secrets
import shutil
import socket
import subprocess
from pathlib import Path

from . import server
from .server import ROOT, serve


def hermes_executable():
    configured = os.environ.get("HERMES_EXE")
    if configured and Path(configured).is_file():
        return configured
    installed = shutil.which("hermes")
    if installed:
        return installed
    local = os.environ.get("LOCALAPPDATA")
    if local:
        path = Path(local) / "hermes" / "bin" / "hermes.exe"
        if path.is_file():
            return str(path)
    return None


def port_open(port):
    with socket.socket() as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local student follow-up browser UI")
    parser.add_argument("--port", type=int, default=8000, help="local UI port (default 8000)")
    parser.add_argument("--no-hermes", action="store_true", help="show dashboard without starting chat")
    args = parser.parse_args(argv)
    child = None
    if not args.no_hermes:
        executable = hermes_executable()
        if executable and not port_open(8642):
            environment = os.environ.copy()
            environment["HERMES_ENABLE_PROJECT_PLUGINS"] = "true"
            environment["API_SERVER_ENABLED"] = "true"
            environment["API_SERVER_HOST"] = "127.0.0.1"
            environment["API_SERVER_PORT"] = "8642"
            environment["API_SERVER_KEY"] = secrets.token_urlsafe(32)
            os.environ["API_SERVER_KEY"] = environment["API_SERVER_KEY"]
            # `gateway` alone is a command group; `run` starts the foreground server.
            child = subprocess.Popen([executable, "gateway", "run"], cwd=ROOT, env=environment)
            server.gateway_process = child
            print("جارٍ تشغيل Hermes المحلي. إذا لم تتصل المحادثة، تحقق من تفعيل student-followup.", flush=True)
        elif executable and os.environ.get("API_SERVER_KEY"):
            print("سيُستخدم خادم Hermes الموجود على المنفذ 8642.", flush=True)
        else:
            server.gateway_problem = ("المنفذ 8642 مستخدم بالفعل؛ أغلق خادم Hermes الآخر أو زوّد API_SERVER_KEY الخاص به."
                                      if executable and port_open(8642) else
                                      "تعذّر العثور على Hermes؛ تحقق من تثبيته في LOCALAPPDATA أو من HERMES_EXE.")
            print("Hermes غير متاح للمحادثة. لوحة التحليل وقرارات المراجع ستعمل محليًا.", flush=True)
    try:
        serve(args.port)
    except KeyboardInterrupt:
        print("\nتم إيقاف الواجهة.")
    finally:
        if child and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()


if __name__ == "__main__":
    main()
