# cae-lanes

**Verified automation lanes for AI agents to drive COMSOL, Abaqus and Creo Parametric — from Python and MCP.**

Every lane in this library was battle-tested against real engineering failures (wrong wave-number branches, silently empty selections, meshes that "solve" garbage, jar file locks, GUI popups on every API call...). The result is not a wrapper around the vendors' APIs — it is **the subset of those APIs that actually works**, with the pitfalls turned into built-in guardrails.

```
your script / AI session
   │
   │  Python library + CLI (judge keywords for CI/queue lanes)
   ▼
cae_lanes.comsol / comsol3d / abaqus / creo      ← guardrails inside
   │
   ├─ COMSOL:  Java templates → javac → comsolbatch (analytic-verified to 1e-9)
   ├─ Abaqus:  staged deck pipeline, py2.7 static checks, log-text judging
   └─ Creo:    creoson (J-Link async REST) → headless Creo, zero popups
```

## Lanes

| Module | What it drives | Highlight guardrails |
|---|---|---|
| `comsol` | 2D parametric acoustics, A/B wave decomposition, result-health checks | correct `k` branch per COMSOL convention, `A==1.0000` pathological-solution detection, ≤20 numbers per stdout line |
| `comsol3d` | 3D straight/stepped ducts, `EvalGlobal` result extraction, STL geometry import | `run("wp1")` before Extrude, `dom3d` assertion, `java_import_geom()` (STL works without the CAD Import module) |
| `abaqus` | gen → run → extract → analyze command building | rc-is-not-truth log judging, py2.7 `flush=`/non-GBK static checks, disk quota guard |
| `creo` | creoson REST client: open / set-dims / regenerate / mass-props / export STEP+PDF, plus OTK tools | 31-char name check, filename/dirname split, headless `-g:no_graphics` (zero popups), `otk-api` signature lookup without javap, `kill` for the jar-lock zombie loop |
| `builder` | build123d/OCCT parametric modeling: boxes-between, side holes, counter-bores, slot arrays, volume assertions, STEP+STL dual export | `export_stl` **silently fails on non-ASCII paths** (returns False, no file) — handled via ASCII temp + rename |

## Quick start

```bash
pip install creopyson          # for the creo lane (requests)
# config: edit cae_lanes/config.py or set CAE_* env vars

cd cae_lanes
python creo.py smoke           # CREO-SMOKE-DONE
python comsol.py --name demo --L 0.75 --H 0.15 --freqs 150,450,900
```

Every CLI ends with an ASCII judge keyword (`CREO-SMOKE-DONE`, `SIMLIB_*_DONE`, ...) — designed for queue/CI lanes that judge by log text, not exit codes.

## MCP server (stdio, zero dependencies)

`cae_lanes/mcp_server.py` exposes 12 tools (`comsol_k`, `comsol_eval_snippet`, `comsol_health`, `creo_cmd`, `creo_status`, `abaqus_cmd`, `judge_log`, ...). Heavy jobs are never executed in-process — the tools **build the command + judge keyword** and hand it to your job queue.

```json
{ "mcpServers": { "cae-lanes": { "command": "python", "args": ["cae_lanes/mcp_server.py"] } } }
```

## Prerequisites per lane

- **COMSOL**: local install (tested 6.4), Java toolchain ships with it. STL import is free; STEP import needs the CAD Import module (not assumed).
- **Abaqus**: Abaqus 2022-style command line; `abaqus python` is Python 2.7 — the static checker enforces that.
- **Creo**: Creo Parametric 2.0+ with the free J-Link component, plus [creoson](https://github.com/SimplifiedLogic/creoson) deployed locally (see `creo.py` docstrings).

## Why "lanes"?

Because "it works on my machine" is not a lane. Each lane here is: a verified path, a judge keyword, a smoke test, and a list of documented dead ends. If your agent drives CAE software, this library is the part of the manual that the vendor forgot to write.

License: MIT.
