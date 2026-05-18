"""NVIDIA embedding worker for Snow Gloves.

Consumes tenants/<t>/ingest-plan.json, chunks each file, computes embeddings via
NVIDIA NIM (or a deterministic local stub for offline runs), and writes a
tenant-scoped vector index at tenants/<t>/vector-index.jsonl.

Real call uses NVIDIA NIM endpoint (configurable). Set NVIDIA_API_KEY to enable.
Set SNOWGLOVES_EMBED_BACKEND=stub for offline development.
"""
from __future__ import annotations
import argparse, hashlib, json, os, sys, urllib.request
from pathlib import Path
import yaml, time, random

CACHE_DIR = None  # set in run()

ROOT = Path(__file__).resolve().parent.parent
CONF = yaml.safe_load((ROOT / "config" / "snowgloves.yaml").read_text())
DIM = int(CONF["embeddings"]["dimension"])
MODEL = CONF["embeddings"]["model"]
BACKEND = os.environ.get("SNOWGLOVES_EMBED_BACKEND",
    "nvidia" if os.environ.get("NVIDIA_API_KEY") else "stub")

NVIDIA_URL = os.environ.get("NVIDIA_NIM_URL",
    "https://integrate.api.nvidia.com/v1/embeddings")

def chunk(text: str, size: int = 800, overlap: int = 100):
    out, i = [], 0
    while i < len(text):
        out.append(text[i:i+size])
        i += size - overlap
    return out

def stub_embed(texts: list[str]) -> list[list[float]]:
    """Deterministic pseudo-embedding (sha256 → float32 sequence). For offline dev only."""
    vecs = []
    for t in texts:
        h = hashlib.sha256(t.encode()).digest()
        # tile bytes to DIM floats in [-1, 1]
        raw = (h * ((DIM // len(h)) + 1))[:DIM]
        vecs.append([(b - 127.5) / 127.5 for b in raw])
    return vecs

def _post_nvidia(texts):
    payload = {"input": texts, "model": MODEL, "input_type": "passage"}
    req = urllib.request.Request(NVIDIA_URL,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {os.environ['NVIDIA_API_KEY']}",
                 "Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())

def nvidia_embed(texts):
    last = None
    for attempt in range(5):
        try:
            r = _post_nvidia(texts)
            return [d["embedding"] for d in r["data"]]
        except Exception as e:
            last = e
            wait = (2 ** attempt) + random.random()
            time.sleep(min(wait, 30))
    raise RuntimeError(f"nvidia embed failed after retries: {last}")

def _cache_path(sha):
    return CACHE_DIR / f"{sha[:2]}" / f"{sha}.json"

def embed(texts):
    if not CACHE_DIR:
        return nvidia_embed(texts) if BACKEND == "nvidia" else stub_embed(texts)
    out, miss_idx, miss_txt = [None]*len(texts), [], []
    for i, t in enumerate(texts):
        sha = hashlib.sha256(t.encode()).hexdigest()
        cp = _cache_path(sha)
        if cp.exists():
            out[i] = json.loads(cp.read_text())["v"]
        else:
            miss_idx.append((i, sha)); miss_txt.append(t)
    if miss_txt:
        vecs = nvidia_embed(miss_txt) if BACKEND == "nvidia" else stub_embed(miss_txt)
        for (i, sha), v in zip(miss_idx, vecs):
            cp = _cache_path(sha); cp.parent.mkdir(parents=True, exist_ok=True)
            cp.write_text(json.dumps({"v": v}))
            out[i] = v
    return out

def run(tenant: str, limit: int | None = None) -> dict:
    global CACHE_DIR
    CACHE_DIR = ROOT / "tenants" / tenant / "_embed_cache"; CACHE_DIR.mkdir(parents=True, exist_ok=True)
    plan_path = ROOT / "tenants" / tenant / "ingest-plan.json"
    if not plan_path.exists():
        return {"error": f"missing {plan_path}", "hint": "run scripts/ingest.py first"}
    plan = json.loads(plan_path.read_text())
    out = ROOT / "tenants" / tenant / "vector-index.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    n_files, n_chunks = 0, 0
    with out.open("w") as f:
        for entry in (plan.get("files") or [])[: (limit or None)]:
            p = Path(entry["path"])
            try:
                txt = p.read_text(errors="ignore")
            except Exception:
                continue
            chunks = chunk(txt)
            if not chunks: continue
            vecs = embed(chunks)
            for i, (c, v) in enumerate(zip(chunks, vecs)):
                f.write(json.dumps({
                    "tenant": tenant, "path": str(p), "chunk": i,
                    "text_sha": hashlib.sha256(c.encode()).hexdigest()[:16],
                    "dim": len(v), "vector": v[:8] + ["…"] if BACKEND == "stub" else v,
                }) + "\n")
            n_files += 1; n_chunks += len(chunks)
    return {"tenant": tenant, "backend": BACKEND, "model": MODEL,
            "files_indexed": n_files, "chunks_indexed": n_chunks, "index": str(out)}

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("tenant")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    r = run(a.tenant, a.limit)
    if not a.quiet: print(json.dumps(r, indent=2))
