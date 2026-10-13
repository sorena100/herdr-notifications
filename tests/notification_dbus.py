#!/usr/bin/env python3
"""Exercise the real binary's D-Bus actions without touching the user's desktop.

Linux prerequisites: dbus-run-session, python-dbus, PyGObject.
Run after cargo build --release --locked:
  dbus-run-session -- /usr/bin/python tests/notification_dbus.py
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

DBusGMainLoop(set_as_default=True)
BUS_NAME = "org.freedesktop.Notifications"
bus = dbus.SessionBus()
# Never replace or interact with an existing desktop notification server.
assert not bus.name_has_owner(BUS_NAME), "Run this test under dbus-run-session"
name = dbus.service.BusName(BUS_NAME, bus, do_not_queue=True)


class Notifications(dbus.service.Object):
    def __init__(self):
        super().__init__(bus, "/org/freedesktop/Notifications")
        self.response = "default"
        self.received = []

    @dbus.service.method(BUS_NAME, in_signature="", out_signature="ssss")
    def GetServerInformation(self):
        return ("Isolated test daemon", "herdr-notifications tests", "1", "1.2")

    @dbus.service.method(BUS_NAME, in_signature="", out_signature="as")
    def GetCapabilities(self):
        return ["actions", "body"]

    @dbus.service.method(BUS_NAME, in_signature="susssasa{sv}i", out_signature="u")
    def Notify(self, app, replaces, icon, summary, body, actions, hints, timeout):
        self.received.append([str(action) for action in actions])
        response = self.response

        def respond():
            if response == "dismiss":
                self.NotificationClosed(1, 2)
            else:
                self.ActionInvoked(1, response)
            return False

        # Allow notify-rust to install the signal match before simulating a click.
        GLib.timeout_add(300, respond)
        return dbus.UInt32(1)

    @dbus.service.method(BUS_NAME, in_signature="u", out_signature="")
    def CloseNotification(self, notification_id):
        self.NotificationClosed(notification_id, 3)

    @dbus.service.signal(BUS_NAME, signature="us")
    def ActionInvoked(self, notification_id, action):
        pass

    @dbus.service.signal(BUS_NAME, signature="uu")
    def NotificationClosed(self, notification_id, reason):
        pass


def run_case(server, root, response):
    state = root / response
    state.mkdir()
    (state / "herdr-notifications-state.json").write_text('{"w1:p7":"working"}')
    focus_log = state / "focus.json"
    stub = root / "herdr-stub"
    stub.write_text(
        '#!/usr/bin/python\n'
        'import json, os, sys\n'
        'if sys.argv[1:3] == ["agent", "focus"]:\n'
        '    with open(os.environ["TEST_FOCUS_LOG"], "w") as f:\n'
        '        json.dump(sys.argv[1:], f)\n'
        'print(json.dumps({"result":{"panes":[],"tabs":[],"workspaces":[]}}))\n'
    )
    stub.chmod(0o700)
    env = dict(os.environ)
    env.update(
        HERDR_BIN_PATH=str(stub),
        HERDR_PLUGIN_STATE_DIR=str(state),
        HERDR_NOTIFICATIONS_STARTUP_QUIET_SECS="0",
        HERDR_NOTIFICATIONS_RAISE_HOST="0",
        HERDR_NOTIFICATIONS_CLICK_ON_DISMISS="0",
        TEST_FOCUS_LOG=str(focus_log),
        HERDR_PLUGIN_EVENT_JSON=json.dumps({"data": {
            "type": "pane_agent_status_changed", "pane_id": "w1:p7",
            "workspace_id": "w1", "agent_status": "done", "agent": "pi"
        }}),
    )
    server.response = response
    server.received.clear()
    binary = Path(__file__).resolve().parents[1] / "target/release/herdr-notifications"
    proc = subprocess.Popen([binary, "event"], env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    loop = GLib.MainLoop()
    deadline = time.monotonic() + 10

    def poll():
        if proc.poll() is not None or time.monotonic() > deadline:
            loop.quit()
            return False
        return True

    GLib.timeout_add(50, poll)
    try:
        loop.run()
        assert proc.poll() is not None, "Notification callback timed out"
        stdout, stderr = proc.communicate(timeout=2)
        assert proc.returncode == 0, (stdout, stderr)
        assert server.received == [["default", "Open in Herdr", "close", "Close"]]
        if response == "default":
            assert json.loads(focus_log.read_text()) == ["agent", "focus", "w1:p7"]
        else:
            assert not focus_log.exists(), "Dismissal/close must not focus a pane"
        print(f"PASS: {response}")
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()


server = Notifications()
with tempfile.TemporaryDirectory(prefix="herdr-notification-dbus-") as directory:
    for response in ("default", "close", "dismiss"):
        run_case(server, Path(directory), response)
