"""Indirect dispatch edges.

A function passed BY NAME as a call argument (`executor.submit(fn)`, `Thread(target=fn)`) is a
real dependency, but the callee-only call scan never recorded it — so `affected` (blast radius)
dropped those callers. These tests pin that such calls now emit a distinct `indirect_call` edge
(leaving the precise `calls` relation untouched) and that `affected` picks them up.

They also pin the soundness guards: an argument that is a PARAMETER or a LOCAL binding of the
enclosing function is a local value, not the module-level function it shares a name with, and a
non-callable same-named node is never a dispatch target — neither may manufacture an edge.
"""
import os
from pathlib import Path

import networkx as nx

from graphify.affected import affected_nodes
from graphify.extract import extract, extract_python

SRC = '''\
import threading


def handler(x):
    return x * 2


def direct():
    return handler(1)                          # direct call -> `calls`


def via_submit(pool):
    pool.submit(handler, 1)                    # indirect: positional arg


def via_thread():
    threading.Thread(target=handler).start()   # indirect: keyword arg


def via_map(xs):
    return map(handler, xs)                    # indirect: map(fn, xs)
'''


def _build(tmp_path):
    (tmp_path / "dispatch.py").write_text(SRC)
    r = extract_python(tmp_path / "dispatch.py")
    nid = {n["label"].rstrip("()"): n["id"] for n in r["nodes"]}   # labels are "handler()"
    return r, nid


def _rels(r, relation):
    return {(e["source"], e["target"]) for e in r["edges"] if e["relation"] == relation}


def test_emits_indirect_call_edges_and_keeps_calls_precise(tmp_path):
    r, nid = _build(tmp_path)
    calls = _rels(r, "calls")
    indirect = _rels(r, "indirect_call")
    handler = nid["handler"]

    # the direct caller stays a `calls` edge — precise relation not regressed
    assert (nid["direct"], handler) in calls
    # the indirect callers are captured, and under the DISTINCT relation
    assert (nid["via_submit"], handler) in indirect
    assert (nid["via_thread"], handler) in indirect
    assert (nid["via_map"], handler) in indirect
    # ...and never leak into the strict `calls` relation
    assert (nid["via_submit"], handler) not in calls
    assert (nid["via_thread"], handler) not in calls
    assert (nid["via_map"], handler) not in calls

    for e in (e for e in r["edges"] if e["relation"] == "indirect_call"):
        assert e["context"] == "argument" and e["confidence"] == "INFERRED"


def test_affected_includes_indirect_callers(tmp_path):
    r, nid = _build(tmp_path)
    g = nx.DiGraph()
    for n in r["nodes"]:
        g.add_node(n["id"], **n)
    for e in r["edges"]:
        g.add_edge(e["source"], e["target"], **e)

    affected = {h.node_id for h in affected_nodes(g, nid["handler"])}
    # blast radius of `handler` now includes the dispatchers it used to drop
    assert nid["via_submit"] in affected
    assert nid["via_thread"] in affected
    assert nid["via_map"] in affected


# ── Soundness: the guards that kill the PR's false positives ──────────────────

def _extract(tmp_path, src):
    (tmp_path / "m.py").write_text(src)
    r = extract_python(tmp_path / "m.py")
    nid = {n["label"].rstrip("()"): n["id"] for n in r["nodes"]}
    return r, nid


PARAM_SHADOW = '''\
def handler():
    return 1


def via(pool, handler):
    pool.submit(handler)        # `handler` is a PARAMETER, not the module fn
'''


def test_param_shadow_emits_no_indirect_call(tmp_path):
    r, nid = _extract(tmp_path, PARAM_SHADOW)
    indirect = _rels(r, "indirect_call")
    assert (nid["via"], nid["handler"]) not in indirect
    # nothing else snuck an edge in to the module-level handler either
    assert all(t != nid["handler"] for _s, t in indirect)


LOCAL_SHADOW = '''\
def handler():
    return 1


def make():
    return lambda: None


def via(pool):
    handler = make()            # `handler` is a LOCAL binding, not the module fn
    pool.submit(handler)
'''


def test_local_assignment_shadow_emits_no_indirect_call(tmp_path):
    r, nid = _extract(tmp_path, LOCAL_SHADOW)
    indirect = _rels(r, "indirect_call")
    assert (nid["via"], nid["handler"]) not in indirect
    assert all(t != nid["handler"] for _s, t in indirect)


DATA_VAR = '''\
def config():
    return {"k": "v"}


def process(x):
    return x


def use():
    config = {"k": "v"}         # local DATA var that happens to match `config()`
    process(config)             # arg resolves to a non-callable local, not the fn
'''


def test_data_var_matching_function_name_emits_no_indirect_call(tmp_path):
    r, nid = _extract(tmp_path, DATA_VAR)
    indirect = _rels(r, "indirect_call")
    # the local `config` must NOT create use -> config()
    assert (nid["use"], nid["config"]) not in indirect


REAL_PASS = '''\
def handler():
    return 1


def via(pool):
    pool.submit(handler)        # genuine module-level fn passed by name
'''


def test_genuine_module_function_still_emits_indirect_call(tmp_path):
    """No recall regression: a real module fn passed by name still emits an edge."""
    r, nid = _extract(tmp_path, REAL_PASS)
    indirect = _rels(r, "indirect_call")
    assert (nid["via"], nid["handler"]) in indirect


# ── Cross-file indirect dispatch ──────────────────────────────────────────────
# The dominant real-world shape: the callback is defined in ANOTHER module and
# imported. The in-file label map can't see it, so it is deferred to the
# cross-file resolver, which emits a distinct INFERRED `indirect_call` only when
# the name resolves to exactly one real callable (the single-definition guard).

def _extract_dir(tmp_path, files: dict[str, str]):
    base = tmp_path / "pkg"
    base.mkdir()
    for name, body in files.items():
        (base / name).write_text(body)
    old = os.getcwd()
    try:
        os.chdir(tmp_path)
        r = extract(
            [Path("pkg") / name for name in files],
            cache_root=Path(".cache"), parallel=False,
        )
    finally:
        os.chdir(old)
    nid = {n["label"].rstrip("()"): n["id"] for n in r["nodes"]}
    return r, nid


def test_cross_file_imported_callback_emits_indirect_call(tmp_path):
    r, nid = _extract_dir(tmp_path, {
        "handlers.py": "def on_event(x):\n    return x\n",
        "scheduler.py": (
            "from handlers import on_event\n\n\n"
            "def schedule(pool):\n"
            "    pool.submit(on_event)\n"   # callback imported from another module
        ),
    })
    indirect = _rels(r, "indirect_call")
    calls = _rels(r, "calls")
    assert (nid["schedule"], nid["on_event"]) in indirect
    # never leaks into the precise `calls` relation
    assert (nid["schedule"], nid["on_event"]) not in calls
    # and it is INFERRED (a referenced value, not an invocation here)
    for e in r["edges"]:
        if e["relation"] == "indirect_call" and e["target"] == nid["on_event"]:
            assert e["confidence"] == "INFERRED"


def test_cross_file_affected_includes_importing_dispatcher(tmp_path):
    r, nid = _extract_dir(tmp_path, {
        "handlers.py": "def on_event(x):\n    return x\n",
        "scheduler.py": (
            "from handlers import on_event\n\n\n"
            "def schedule(pool):\n"
            "    pool.submit(on_event)\n"
        ),
    })
    g = nx.DiGraph()
    for n in r["nodes"]:
        g.add_node(n["id"], **n)
    for e in r["edges"]:
        g.add_edge(e["source"], e["target"], **e)
    affected = {h.node_id for h in affected_nodes(g, nid["on_event"])}
    # editing on_event now flags the cross-module dispatcher — the gap #1565
    # left open (it only saw same-file callbacks).
    assert nid["schedule"] in affected


def test_cross_file_param_shadow_emits_no_indirect_call(tmp_path):
    """Soundness carries across files: an imported name shadowed by a parameter
    is the local value, so no cross-file indirect edge is manufactured."""
    r, nid = _extract_dir(tmp_path, {
        "handlers.py": "def on_event(x):\n    return x\n",
        "scheduler.py": (
            "from handlers import on_event\n\n\n"
            "def schedule(pool, on_event):\n"   # on_event is the PARAMETER here
            "    pool.submit(on_event)\n"
        ),
    })
    indirect = _rels(r, "indirect_call")
    assert (nid["schedule"], nid["on_event"]) not in indirect
