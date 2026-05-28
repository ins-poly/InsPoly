from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import threading
import traceback
from typing import Callable

from app.browser_desktop import ArchiveResearchBrowserApp, BrowserDesktopApp
from app.browser_static_assets import VENDOR_BROWSER_ROOT
from app.config import (
    FUNDING_TRACE_MODE_CACHE_ONLY,
    FUNDING_TRACE_MODE_DISABLED,
    FUNDING_TRACE_MODE_LIVE_RPC,
    funding_trace_mode,
    normalize_funding_trace_mode,
    repository_root,
)
from app.event_forensic_desktop import EventForensicBrowserApp
from app.local_server import LocalServerHandle, open_local_path
from app.macos_power import MacSleepAssertion


ModeFactory = Callable[[], object]

MODE_FACTORIES: dict[str, ModeFactory] = {
    "recent": BrowserDesktopApp,
    "archive": ArchiveResearchBrowserApp,
    "event": EventForensicBrowserApp,
}

MODE_LABELS = {
    "recent": "Recent Scanner",
    "archive": "Archive Researcher",
    "event": "Event Forensic Analyzer",
}


START_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>InsPoly</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f3f6f5;
      --panel: #ffffff;
      --text: #182126;
      --muted: #58646b;
      --line: #d8dee2;
      --accent: #166c72;
      --accent-strong: #0f5257;
      --danger: #a33a2a;
      --ok: #24724c;
      --warn: #936c17;
    }
    * { box-sizing: border-box; }
    html, body { height: 100%; }
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text);
      overflow: hidden;
    }
    .shell {
      height: 100%;
      display: grid;
      grid-template-rows: auto 1fr;
    }
    .topbar {
      background: var(--panel);
      border-bottom: 1px solid var(--line);
      padding: 18px 20px 16px;
      display: grid;
      grid-template-columns: auto 1fr;
      gap: 16px;
      align-items: start;
    }
    .mark {
      width: 44px;
      height: 44px;
      border-radius: 8px;
      background: var(--accent);
      color: white;
      display: grid;
      place-items: center;
      font-weight: 750;
      letter-spacing: 0;
      font-size: 18px;
    }
    h1 {
      margin: 0;
      font-size: 22px;
      line-height: 1.2;
      letter-spacing: 0;
    }
    .subtitle, .status-line {
      margin: 4px 0 0;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
    }
    .actions {
      display: grid;
      grid-template-columns: 1fr;
      gap: 8px;
      margin-top: 14px;
    }
    button {
      border: 1px solid var(--line);
      border-radius: 6px;
      background: white;
      color: var(--text);
      min-height: 38px;
      padding: 0 13px;
      font-size: 13px;
      font-weight: 650;
      cursor: pointer;
      white-space: nowrap;
    }
    button.primary {
      border-color: var(--accent);
      background: var(--accent);
      color: white;
    }
    button:hover { border-color: var(--accent); }
    button.primary:hover { background: var(--accent-strong); }
    button:disabled {
      opacity: 0.55;
      cursor: default;
    }
    .controls {
      display: flex;
      flex-wrap: wrap;
      gap: 8px 12px;
      align-items: center;
      margin-top: 12px;
    }
    label {
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.4;
    }
    input[type="checkbox"] {
      width: 16px;
      height: 16px;
      accent-color: var(--accent);
      flex: 0 0 auto;
    }
    select {
      min-height: 34px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: white;
      color: var(--text);
      padding: 0 10px;
      font-size: 13px;
    }
    .status-line.error { color: var(--danger); }
    .status-line.running { color: var(--ok); }
    .status-line.warning { color: var(--warn); }
    .workspace {
      min-height: 0;
      display: grid;
      background: #ffffff;
    }
    #empty-state {
      place-self: center;
      width: min(560px, calc(100vw - 48px));
      text-align: center;
      color: var(--muted);
      line-height: 1.5;
    }
    #empty-state strong {
      display: block;
      color: var(--text);
      font-size: 19px;
      margin-bottom: 8px;
    }
    #workspace-frame {
      width: 100%;
      height: 100%;
      border: 0;
      display: none;
      background: white;
    }
    .workspace.active #workspace-frame { display: block; }
    .workspace.active #empty-state { display: none; }
    @media (min-width: 720px) {
      .actions { grid-template-columns: repeat(3, 1fr); }
    }
  </style>
</head>
<body>
  <main class="shell">
    <section class="topbar" aria-label="InsPoly launcher">
      <div class="mark" aria-hidden="true">IP</div>
      <div>
        <h1>InsPoly</h1>
        <p class="subtitle" id="mode-label">Choose a workspace.</p>
        <section class="actions" aria-label="InsPoly modes">
          <button class="primary" type="button" data-mode="recent">Recent Scanner</button>
          <button class="primary" type="button" data-mode="archive">Archive Researcher</button>
          <button class="primary" type="button" data-mode="event">Event Forensic Analyzer</button>
        </section>
        <section class="controls" aria-label="InsPoly controls">
          <label>
            <input id="keep-awake" type="checkbox" checked>
            <span>Keep Mac awake while analysis is running</span>
          </label>
          <label>
            <span>Funding trace mode</span>
            <select id="funding-mode">
              <option value="disabled" selected>Disabled</option>
              <option value="cache_only">Cache only</option>
              <option value="live_rpc">Live RPC</option>
            </select>
          </label>
          <button type="button" id="stop-button">Stop analysis</button>
          <button type="button" id="outputs-button">Open outputs</button>
          <button type="button" id="logs-button">Open logs</button>
        </section>
        <p class="status-line" id="status" role="status" aria-live="polite">Ready.</p>
      </div>
    </section>
    <section class="workspace" id="workspace">
      <div id="empty-state">
        <strong>Ready for local analysis.</strong>
        No workspace open.
      </div>
      <iframe id="workspace-frame" title="InsPoly workspace"></iframe>
    </section>
  </main>
  <script>
    const statusNode = document.getElementById('status');
    const modeLabel = document.getElementById('mode-label');
    const buttons = Array.from(document.querySelectorAll('button[data-mode]'));
    const keepAwake = document.getElementById('keep-awake');
    const fundingMode = document.getElementById('funding-mode');
    const workspace = document.getElementById('workspace');
    const frame = document.getElementById('workspace-frame');
    const stopButton = document.getElementById('stop-button');
    const outputsButton = document.getElementById('outputs-button');
    const logsButton = document.getElementById('logs-button');

    function setBusy(isBusy) {
      buttons.forEach((button) => { button.disabled = isBusy; });
    }

    function setStatus(message, tone = '') {
      statusNode.textContent = message;
      statusNode.className = 'status-line' + (tone ? ' ' + tone : '');
    }

    function setModeLabel(label) {
      modeLabel.textContent = label ? 'Current workspace: ' + label : 'Choose a workspace.';
    }

    window.loadWorkspace = function(url, label) {
      frame.src = url;
      workspace.classList.add('active');
      setModeLabel(label || '');
      setStatus((label || 'Workspace') + ' is ready.', 'running');
      setBusy(false);
    };

    function applyStatus(result) {
      if (!result || !result.ok) return;
      keepAwake.checked = Boolean(result.keepAwake);
      if (result.fundingTraceMode) fundingMode.value = result.fundingTraceMode;
      setModeLabel(result.label || '');
      if (result.mode) {
        setStatus(result.running ? result.label + ' is running.' : result.label + ' is ready.', result.running ? 'running' : '');
      } else {
        setStatus('Ready.');
      }
    }

    buttons.forEach((button) => {
      button.addEventListener('click', async () => {
        setBusy(true);
        setStatus('Starting ' + button.textContent + '...');
        try {
          await window.pywebview.api.set_funding_trace_mode(fundingMode.value);
          const result = await window.pywebview.api.launch_mode(button.dataset.mode, keepAwake.checked);
          if (!result.ok) {
            setStatus(result.error || 'Unable to start this mode.', 'error');
            setBusy(false);
          } else {
            applyStatus(result);
          }
        } catch (error) {
          setStatus(String(error), 'error');
          setBusy(false);
        }
      });
    });

    keepAwake.addEventListener('change', async () => {
      try {
        applyStatus(await window.pywebview.api.set_keep_awake(keepAwake.checked));
      } catch (error) {
        setStatus(String(error), 'error');
      }
    });

    fundingMode.addEventListener('change', async () => {
      try {
        applyStatus(await window.pywebview.api.set_funding_trace_mode(fundingMode.value));
      } catch (error) {
        setStatus(String(error), 'error');
      }
    });

    stopButton.addEventListener('click', async () => {
      try {
        const result = await window.pywebview.api.stop_current_analysis();
        setStatus(result.ok ? (result.message || 'Stop requested.') : (result.error || 'Unable to stop analysis.'), result.ok ? 'warning' : 'error');
      } catch (error) {
        setStatus(String(error), 'error');
      }
    });

    outputsButton.addEventListener('click', async () => {
      try {
        const result = await window.pywebview.api.open_current_outputs();
        if (!result.ok) setStatus(result.error || 'Unable to open outputs.', 'error');
      } catch (error) {
        setStatus(String(error), 'error');
      }
    });

    logsButton.addEventListener('click', async () => {
      try {
        const result = await window.pywebview.api.open_current_log();
        if (!result.ok) setStatus(result.error || 'Unable to open logs.', 'error');
      } catch (error) {
        setStatus(String(error), 'error');
      }
    });

    setInterval(async () => {
      if (!window.pywebview || !window.pywebview.api) return;
      try {
        applyStatus(await window.pywebview.api.status());
      } catch (_error) {
      }
    }, 2500);
  </script>
</body>
</html>
"""


class NativeLauncherApi:
    def __init__(
        self,
        *,
        runtime_root: Path | None = None,
        sleep_assertion: MacSleepAssertion | None = None,
        poll_interval: float = 2.0,
    ) -> None:
        self.window = None
        self.runtime_root = (runtime_root or Path.cwd()).resolve()
        self.keep_awake = True
        self.current_mode: str | None = None
        self.current_app: object | None = None
        self.current_handle: LocalServerHandle | None = None
        self.sleep_assertion = sleep_assertion or MacSleepAssertion()
        self.poll_interval = poll_interval
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._monitor_thread: threading.Thread | None = None

    def launch_mode(self, mode: str, keep_awake: bool = True) -> dict[str, object]:
        normalized_mode = str(mode or "").strip().lower()
        factory = MODE_FACTORIES.get(normalized_mode)
        if factory is None:
            return {
                "ok": False,
                "error": "This InsPoly workspace is not available.",
                "detail": f"Unknown InsPoly mode: {mode}",
            }

        handle: LocalServerHandle | None = None
        try:
            app = factory()
            self._validate_bundled_assets(app)
            handle = app.create_server()
            handle.start_background(thread_name=f"InsPoly {normalized_mode} server")
        except Exception as exc:
            if handle is not None:
                handle.close()
            return self._failure("InsPoly could not start this workspace.", exc)

        with self._lock:
            self._request_stop_current_locked()
            self._close_current_locked()
            self.current_mode = normalized_mode
            self.current_app = app
            self.current_handle = handle
            self.keep_awake = bool(keep_awake)
            self._ensure_monitor_started_locked()

        try:
            self._load_workspace(handle.url, MODE_LABELS[normalized_mode])
        except Exception as exc:
            with self._lock:
                if self.current_handle is handle:
                    self._request_stop_current_locked()
                    self._close_current_locked()
            return self._failure("InsPoly opened the local server, but the native window could not load it.", exc)
        return {
            "ok": True,
            "mode": normalized_mode,
            "label": MODE_LABELS[normalized_mode],
            "url": handle.url,
            "keepAwake": self.keep_awake,
            "fundingTraceMode": funding_trace_mode(),
            "runtimeRoot": str(self.runtime_root),
            "sleepAssertion": self.sleep_assertion.status(),
        }

    def set_keep_awake(self, enabled: bool) -> dict[str, object]:
        with self._lock:
            self.keep_awake = bool(enabled)
        if not self.keep_awake:
            self.sleep_assertion.release()
        return self.status()

    def set_funding_trace_mode(self, mode: str) -> dict[str, object]:
        normalized = normalize_funding_trace_mode(mode, default=FUNDING_TRACE_MODE_DISABLED)
        os.environ["INSPOLY_FUNDING_TRACE_MODE"] = normalized
        return self.status()

    def stop_current_analysis(self) -> dict[str, object]:
        with self._lock:
            if self.current_app is None:
                return {"ok": False, "error": "No InsPoly analysis is currently open."}
            stopped = self._request_stop_current_locked()
        if stopped:
            return {"ok": True, "message": "Stop requested."}
        return {"ok": False, "error": "This workspace is open, but there is no active analysis to stop."}

    def open_current_outputs(self) -> dict[str, object]:
        with self._lock:
            app = self.current_app
        if app is None:
            return self._open_path(self.runtime_root, "InsPoly workspace folder")
        opener = getattr(app, "open_exports_dir", None)
        if callable(opener):
            try:
                result = opener()
            except Exception as exc:
                return self._failure("InsPoly could not open the outputs folder.", exc)
            return dict(result) if isinstance(result, dict) else {"ok": True}
        config = getattr(app, "config", None)
        outputs_dir = getattr(config, "outputs_dir", None)
        if isinstance(outputs_dir, Path):
            return self._open_path(outputs_dir, "outputs folder")
        return self._open_path(self.runtime_root, "InsPoly workspace folder")

    def open_current_log(self) -> dict[str, object]:
        with self._lock:
            app = self.current_app
        if app is None:
            return self._open_path(self.runtime_root, "InsPoly workspace folder")
        performance_log_path = getattr(app, "performance_log_path", None)
        if isinstance(performance_log_path, Path) and performance_log_path.exists():
            return self._open_path(performance_log_path, "latest log")
        config = getattr(app, "config", None)
        data_dir = getattr(config, "data_dir", None)
        if isinstance(data_dir, Path):
            return self._open_path(data_dir, "InsPoly data folder")
        return self._open_path(self.runtime_root, "InsPoly workspace folder")

    def status(self) -> dict[str, object]:
        with self._lock:
            running = self._current_job_running_locked()
            return {
                "ok": True,
                "mode": self.current_mode,
                "label": MODE_LABELS.get(self.current_mode or "", ""),
                "running": running,
                "keepAwake": self.keep_awake,
                "fundingTraceMode": funding_trace_mode(),
                "fundingTraceModes": {
                    "disabled": FUNDING_TRACE_MODE_DISABLED,
                    "cacheOnly": FUNDING_TRACE_MODE_CACHE_ONLY,
                    "liveRpc": FUNDING_TRACE_MODE_LIVE_RPC,
                },
                "runtimeRoot": str(self.runtime_root),
                "sleepAssertion": self.sleep_assertion.status(),
            }

    def shutdown(self, *_args: object) -> None:
        self._stop_event.set()
        with self._lock:
            self._request_stop_current_locked()
            self._close_current_locked()
        self.sleep_assertion.release()
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=3.0)

    def _load_workspace(self, url: str, label: str) -> None:
        if self.window is None:
            return
        script = f"window.loadWorkspace({json.dumps(url)}, {json.dumps(label)});"
        evaluate_js = getattr(self.window, "evaluate_js", None)
        if callable(evaluate_js):
            evaluate_js(script)
            return
        self.window.load_url(url)

    def _open_path(self, path: Path, label: str) -> dict[str, object]:
        try:
            open_local_path(path)
        except Exception as exc:
            return self._failure(f"InsPoly could not open the {label}.", exc)
        return {"ok": True, "path": str(path)}

    def _request_stop_current_locked(self) -> bool:
        app = self.current_app
        if app is None:
            return False
        stopped = False
        for method_name in ("stop_analysis", "stop_scan"):
            method = getattr(app, method_name, None)
            if not callable(method):
                continue
            try:
                result = method()
            except Exception:
                continue
            stopped = True
            if isinstance(result, dict) and result.get("ok") is False:
                stopped = self._current_job_running_locked()
            break
        return stopped

    def _validate_bundled_assets(self, app: object) -> None:
        asset_name = str(getattr(app, "asset_name", "") or "")
        module = sys.modules.get(app.__class__.__module__)
        module_file = Path(str(getattr(module, "__file__", __file__)))
        if asset_name and not module_file.with_name(asset_name).is_file():
            raise FileNotFoundError(f"Missing bundled browser UI asset: {asset_name}")
        if not VENDOR_BROWSER_ROOT.is_dir():
            raise FileNotFoundError(f"Missing bundled browser vendor assets: {VENDOR_BROWSER_ROOT}")

    def _failure(self, message: str, exc: Exception) -> dict[str, object]:
        return {
            "ok": False,
            "error": message,
            "detail": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(limit=4),
        }

    def _ensure_monitor_started_locked(self) -> None:
        if self._monitor_thread and self._monitor_thread.is_alive():
            return
        self._monitor_thread = threading.Thread(
            target=self._monitor_sleep_assertion,
            name="InsPoly sleep assertion monitor",
            daemon=True,
        )
        self._monitor_thread.start()

    def _monitor_sleep_assertion(self) -> None:
        while not self._stop_event.is_set():
            with self._lock:
                running = self._current_job_running_locked()
                keep_awake = self.keep_awake
            if keep_awake and running:
                self.sleep_assertion.acquire()
            else:
                self.sleep_assertion.release()
            self._stop_event.wait(self.poll_interval)
        self.sleep_assertion.release()

    def _current_job_running_locked(self) -> bool:
        app = self.current_app
        if app is None:
            return False
        lock = getattr(app, "_lock", None)
        if lock is None:
            status = getattr(app, "scan_status", {})
            return bool(status.get("running")) if isinstance(status, dict) else False
        with lock:
            status = getattr(app, "scan_status", {})
            return bool(status.get("running")) if isinstance(status, dict) else False

    def _close_current_locked(self) -> None:
        handle = self.current_handle
        self.current_handle = None
        self.current_app = None
        self.current_mode = None
        self.sleep_assertion.release()
        if handle is not None:
            handle.close()


def resolve_native_runtime_root() -> Path:
    configured = os.environ.get("INSPOLY_RUNTIME_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return (Path.home() / "Documents" / "InsPoly").resolve()
    return repository_root().resolve()


def prepare_native_runtime_root(root: Path | None = None) -> Path:
    runtime_root = (root or resolve_native_runtime_root()).resolve()
    try:
        runtime_root.mkdir(parents=True, exist_ok=True)
        os.chdir(runtime_root)
    except OSError as exc:
        raise RuntimeError(f"InsPoly could not prepare its local workspace at {runtime_root}.") from exc
    return runtime_root


def launch_native_macos_app() -> None:
    try:
        runtime_root = prepare_native_runtime_root()
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    try:
        import webview
    except ImportError as exc:
        raise SystemExit(
            "pywebview is required for InsPoly.app. Install it with "
            'python3 -m pip install -e ".[macos-app]".'
        ) from exc

    api = NativeLauncherApi(runtime_root=runtime_root)
    window = webview.create_window(
        "InsPoly",
        html=START_HTML,
        js_api=api,
        width=980,
        height=680,
        min_size=(720, 520),
        text_select=False,
        background_color="#f5f7f8",
    )
    api.window = window
    window.events.closed += api.shutdown
    print(f"InsPoly runtime root: {runtime_root}")
    try:
        webview.start()
    finally:
        api.shutdown()


def main() -> int:
    launch_native_macos_app()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
