#!/usr/bin/env python3
"""Hermes — minimal event bus for Snow Gloves OS.

Endpoints:
  POST /publish      { "channel": "...", "event": {...} }   -> append + log
  GET  /events       ?since=ISO                              -> list
  GET  /healthz                                              -> ok
  POST /test/e2e                                             -> publishes a synthetic
                                                                event, routes it through
                                                                Chief of Staff, returns
                                                                routing decision.

Run:
  python3 scripts/hermes.py
  python3 scripts/hermes.py --test     # one-shot end-to-end smoke
"""
import json, os, sys, time, threading, http.server, socketserver, urllib.request
sys_path_added = True
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent))
from lib.redact import redact
from pathlib import Path
from datetime import datetime, timezone
import yaml, fnmatch, argparse

ROOT = Path(__file__).resolve().parent.parent
CONF = yaml.safe_load((ROOT / "config" / "snowgloves.yaml").read_text())
HOST = CONF["hermes"]["host"]
PORT = int(CONF["hermes"]["port"])
CHANNEL = CONF["hermes"]["channel"]
LOG = ROOT / "_audit" / "hermes-events.jsonl"
LOG.parent.mkdir(exist_ok=True)
HOOKS = yaml.safe_load((ROOT / "workflows" / "skill-hooks.yaml").read_text())

def route(task):
    """Chief of Staff routing — match task to agent + hook + skills."""
    text = " ".join([
        task.get("title", ""),
        " ".join(task.get("tags", []) or []),
        task.get("brief", ""),
    ]).lower()
    matches = []
    for agent, cfg in HOOKS["routing"].items():
        for hook in cfg.get("hooks", []) or []:
            for glob in hook.get("globs", []):
                if fnmatch.fnmatch(text, glob.lower()):
                    matches.append({
                        "agent": agent, "hook": hook["id"],
                        "skills": hook["skills"], "matched_glob": glob,
                    })
                    break
    if not matches:
        # Fallback to CEO/CTO escalation rules
        matches.append({
            "agent": "chief-of-staff", "hook": "default-fallback",
            "skills": [], "matched_glob": None,
            "escalation": "cto" if any(k in text for k in ["bug","arch","build","deploy"]) else "ceo",
        })
    return matches

def append(event):
    rec = {"ts": datetime.now(timezone.utc).isoformat(), **redact(event)}
    with LOG.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    return rec

class H(http.server.BaseHTTPRequestHandler):
    def _json(self, code, body):
        b = json.dumps(body).encode()
        self.send_response(code); self.send_header("Content-Type","application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def log_message(self, *a, **k): pass

    def do_GET(self):
        if self.path.startswith("/healthz"):
            return self._json(200, {"ok": True, "channel": CHANNEL, "port": PORT})
        if self.path.startswith("/events"):
            evs = [json.loads(l) for l in LOG.read_text().splitlines()] if LOG.exists() else []
            return self._json(200, {"count": len(evs), "events": evs[-100:]})
        return self._json(404, {"error": "not found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length", "0") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if self.path == "/publish":
            rec = append({"kind": "publish", **body})
            return self._json(200, {"accepted": True, "record": rec})
        if self.path == "/test/e2e":
            task = body.get("task") or {
                "title": "launch new referral program for tenant",
                "tags": ["growth","referral"],
                "brief": "Design a viral referral program with leaderboard.",
            }
            decision = route(task)
            rec = append({"kind": "e2e-test", "task": task, "routing": decision})
            return self._json(200, {"ok": True, "task": task, "routing": decision, "audit": rec})
        return self._json(404, {"error": "not found"})

def serve():
    with socketserver.TCPServer((HOST, PORT), H) as httpd:
        import sys as _sys; print(f"[hermes] listening on http://{HOST}:{PORT}  channel={CHANNEL}", file=_sys.stderr, flush=True)
        httpd.serve_forever()

def one_shot_test():
    """Spawn server in background, fire an e2e event, print result, exit."""
    t = threading.Thread(target=serve, daemon=True); t.start(); time.sleep(0.4)
    req = urllib.request.Request(f"http://{HOST}:{PORT}/test/e2e",
        data=json.dumps({}).encode(), headers={"Content-Type":"application/json"})
    print(json.dumps(json.loads(urllib.request.urlopen(req).read()), indent=2))

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()
    one_shot_test() if a.test else serve()
