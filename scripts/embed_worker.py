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
import yaml

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

def nvidia_embed(texts: list[str]) -> list[list[float]]:
    payload = {"input": texts, "model": MODEL, "input_type": "passage"}
    req = urllib.request.Request(NVIDIA_URL,
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {os.environ['NVIDIA_API_KEY']}",
            "Content-Type": "application/json",
        })
    r = json.loads(urllib.request.urlopen(req, timeout=30).read())
    return [d["embedding"] for d in r["data"]]

def embed(texts: list[str]) -> list[list[float]]:
    return nvidia_embed(texts) if BACKEND == "nvidia" else stub_embed(texts)

def run(tenant: str, limit: int | None = None) -> dict:
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
    a = ap.parse_args()
    print(json.dumps(run(a.tenant, a.limit), indent=2))
