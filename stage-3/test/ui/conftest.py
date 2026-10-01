import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest
from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(__file__))
from common import BASE, reset, fixture  # noqa: E402

STAGE1 = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "stage-1"))


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        yield b
        b.close()


@pytest.fixture()
def page(browser):
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    p = ctx.new_page()
    p.set_default_timeout(8000)
    yield p
    ctx.close()


@pytest.fixture()
def phone(browser):
    ctx = browser.new_context(viewport={"width": 375, "height": 800})
    p = ctx.new_page()
    p.set_default_timeout(8000)
    yield p
    ctx.close()


@pytest.fixture(autouse=True)
def clean_state():
    reset()
    yield


@pytest.fixture(scope="session")
def stage1():
    """A real stage-1 service (from ../stage-1) on a free port, used as the upgrade source."""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    proc = subprocess.Popen(["node", "src/index.js"], cwd=STAGE1, env={**os.environ, "PORT": str(port)}, stdout=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(base + "/health")
            break
        except Exception:
            time.sleep(0.05)
    yield base
    proc.kill()
