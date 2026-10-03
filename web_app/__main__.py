"""Run the local UI and, when available, its Hermes gateway."""

import argparse
import json
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


def hermes_api_key(executable):
    """Use a profile credential so Hermes's scoped gateway can read the key."""
    environment = os.environ.copy()
    environment.pop("API_SERVER_KEY", None)
    environment.pop("API_SERVER_ENABLED", None)
    options = {"cwd": ROOT, "env": environment, "capture_output": True,
               "text": True, "encoding": "utf-8", "errors": "replace", "timeout": 20}
    try:
        current = subprocess.run([executable, "config", "get", "API_SERVER_KEY", "--json", "--raw"],
                                 **options)
        if current.returncode == 0:
            key = json.loads(current.stdout)
            if not isinstance(key, str) or len(key) < 16:
                raise RuntimeError("مفتاح Hermes الموجود غير صالح؛ تحقق من إعداد API_SERVER_KEY.")
        elif "Config key not set" in current.stderr + current.stdout:
            key = secrets.token_urlsafe(32)
            saved = subprocess.run([executable, "config", "set", "API_SERVER_KEY", key], **options)
            if saved.returncode:
                raise RuntimeError("تعذّر حفظ مفتاح API في إعدادات Hermes.")
            print("تم إعداد مفتاح API محلي في Hermes.", flush=True)
        else:
            raise RuntimeError("تعذّر قراءة إعداد API_SERVER_KEY من Hermes.")
        enabled = subprocess.run([executable, "config", "get", "API_SERVER_ENABLED", "--json"], **options)
        if enabled.returncode or json.loads(enabled.stdout) not in (True, "true", "True", "1"):
            saved = subprocess.run([executable, "config", "set", "API_SERVER_ENABLED", "true"], **options)
            if saved.returncode:
                raise RuntimeError("تعذّر تفعيل Hermes API في الإعدادات.")
        return key
    except (subprocess.TimeoutExpired, ValueError, OSError) as exc:
        raise RuntimeError("تعذّر إعداد Hermes API؛ راجع تثبيت Hermes وإعداداته.") from exc


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local student follow-up browser UI")
    parser.add_argument("--port", type=int, default=8000, help="local UI port (default 8000)")
    parser.add_argument("--no-hermes", action="store_true", help="show dashboard without starting chat")
    args = parser.parse_args(argv)
    child = None
    server.gateway_process = None
    server.gateway_problem = None
    if not args.no_hermes:
        executable = hermes_executable()
        try:
            key = hermes_api_key(executable) if executable else None
        except RuntimeError as exc:
            key = None
            server.gateway_problem = str(exc)
        if key and not port_open(8642):
            environment = os.environ.copy()
            environment["HERMES_ENABLE_PROJECT_PLUGINS"] = "true"
            environment["API_SERVER_ENABLED"] = "true"
            environment["API_SERVER_HOST"] = "127.0.0.1"
            environment["API_SERVER_PORT"] = "8642"
            environment["API_SERVER_KEY"] = key
            os.environ["API_SERVER_KEY"] = key
            # Run in the foreground so the UI can stop its child on exit.
            child = subprocess.Popen([executable, "gateway", "run"], cwd=ROOT, env=environment)
            server.gateway_process = child
            print("جارٍ تشغيل Hermes المحلي. إذا لم تتصل المحادثة، تحقق من تفعيل student-followup.", flush=True)
        elif key and port_open(8642):
            os.environ["API_SERVER_KEY"] = key
            print("سيُستخدم خادم Hermes الموجود على المنفذ 8642.", flush=True)
        else:
            if not server.gateway_problem:
                server.gateway_problem = "تعذّر العثور على Hermes؛ تحقق من تثبيته في LOCALAPPDATA أو من HERMES_EXE."
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
