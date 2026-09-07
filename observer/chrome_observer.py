#!/usr/bin/env python3
"""Silent read-only Chrome co-observer for a live walkthrough of your app.

Attaches to a debug-profile Chrome over CDP and logs, per screen, the technical bugs a
human narrator can't easily see: console errors, uncaught JS exceptions, failed network
calls (4xx/5xx + load failures), and every route change. Read-only: it never clicks,
navigates, or injects anything.

Configuration (env):
  OBSERVER_URL         The app to observe, and capture_start.sh's default Chrome launch
                        URL. Default: http://localhost:3000
  OBSERVER_URL_FILTER   Substring match against tab URLs to decide which tabs to attach to.
                        Default: derived from OBSERVER_URL's host, so the observer only
                        attaches to tabs on your app, not every open tab.
  OBSERVER_CDP_PORT    Chrome's remote-debugging port. Default: 9222
  HOMEBASE_ROOT        Where to write output. Default: this repo's root.

Output: JSONL at <homebase>/.chrome-observer/observe-<stamp>.jsonl
Stop it with: kill $(cat <homebase>/.chrome-observer/observer.pid)
"""
from __future__ import annotations
import json, os, sys, threading, time, urllib.request
from pathlib import Path
from urllib.parse import urlparse
from datetime import datetime, timezone

try:
    import websocket  # websocket-client
except Exception:
    print("websocket-client missing", file=sys.stderr); sys.exit(1)

CDP_PORT = os.environ.get("OBSERVER_CDP_PORT", "9222")
CDP = f"http://localhost:{CDP_PORT}"
OBSERVER_URL = os.environ.get("OBSERVER_URL", "http://localhost:3000")
OBSERVER_URL_FILTER = os.environ.get("OBSERVER_URL_FILTER") or (urlparse(OBSERVER_URL).netloc or OBSERVER_URL)

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent
HOMEBASE = Path(os.environ.get("HOMEBASE_ROOT", str(_REPO_ROOT)))
OUTDIR = HOMEBASE / ".chrome-observer"
OUTDIR.mkdir(exist_ok=True)
STAMP = os.environ.get("OBS_STAMP") or datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
LOG = OUTDIR / f"observe-{STAMP}.jsonl"
(OUTDIR / "observer.pid").write_text(str(os.getpid()))
(OUTDIR / "current.log").write_text(str(LOG))

_lock = threading.Lock()
_attached: set[str] = set()

def now() -> str:
    return datetime.now(timezone.utc).isoformat()

def emit(kind: str, **fields):
    rec = {"ts": now(), "kind": kind, **fields}
    with _lock:
        with LOG.open("a") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

def list_observed_targets():
    try:
        tabs = json.load(urllib.request.urlopen(f"{CDP}/json", timeout=3))
    except Exception:
        return []
    return [t for t in tabs if t.get("type") == "page"
            and OBSERVER_URL_FILTER in (t.get("url") or "")
            and t.get("webSocketDebuggerUrl")]

def watch_target(t):
    url = t["webSocketDebuggerUrl"]; tid = t["id"]
    try:
        ws = websocket.create_connection(url, max_size=None, timeout=30,
                                         suppress_origin=True)
    except Exception as e:
        emit("attach_error", target=tid, error=str(e))
        _attached.discard(tid); return
    _mid = [0]
    def cmd(method, params=None):
        _mid[0] += 1
        ws.send(json.dumps({"id": _mid[0], "method": method, "params": params or {}}))
    for m in ("Page.enable", "Runtime.enable", "Log.enable",
              "Network.enable", "Runtime.consoleAPIEnabled"):
        try: cmd(m)
        except Exception: pass
    emit("attached", target=tid, url=t.get("url"), title=t.get("title"))
    try:
        while True:
            raw = ws.recv()
            if not raw:
                break
            try: msg = json.loads(raw)
            except Exception: continue
            method = msg.get("method"); p = msg.get("params", {})
            if method == "Runtime.exceptionThrown":
                d = p.get("exceptionDetails", {})
                txt = d.get("exception", {}).get("description") or d.get("text")
                emit("js_exception", text=(txt or "")[:600],
                     url=d.get("url"), line=d.get("lineNumber"))
            elif method == "Runtime.consoleAPICalled":
                lvl = p.get("type")
                if lvl in ("error", "warning", "assert"):
                    args = " ".join(str(a.get("value", a.get("description", "")))
                                    for a in p.get("args", []))[:600]
                    emit("console", level=lvl, text=args)
            elif method == "Log.entryAdded":
                e = p.get("entry", {})
                if e.get("level") in ("error", "warning"):
                    emit("log", level=e.get("level"), text=(e.get("text") or "")[:600],
                         url=e.get("url"), source=e.get("source"))
            elif method == "Network.responseReceived":
                r = p.get("response", {}); st = r.get("status", 0)
                if st >= 400:
                    emit("http_error", status=st, url=(r.get("url") or "")[:400],
                         method=(p.get("type")))
            elif method == "Network.loadingFailed":
                if not p.get("canceled"):
                    emit("net_failed", error=p.get("errorText"),
                         blocked=p.get("blockedReason"))
            elif method == "Page.frameNavigated":
                fr = p.get("frame", {})
                if not fr.get("parentId"):
                    emit("navigate", url=fr.get("url"), kind_detail="document")
            elif method == "Page.navigatedWithinDocument":
                emit("navigate", url=p.get("url"), kind_detail="spa-route")
    except Exception as e:
        emit("detached", target=tid, error=str(e))
    finally:
        try: ws.close()
        except Exception: pass
        _attached.discard(tid)

def main():
    emit("observer_start", log=str(LOG), pid=os.getpid())
    while True:
        for t in list_observed_targets():
            if t["id"] not in _attached:
                _attached.add(t["id"])
                threading.Thread(target=watch_target, args=(t,), daemon=True).start()
        time.sleep(3)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        emit("observer_stop")
