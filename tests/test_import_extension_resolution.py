"""Tests for #716 — TypeScript bare-path imports, Svelte 5 rune file imports
(`from './foo.svelte'` for a `.svelte.ts` file), and directory/index.ts
imports must resolve to the actual file's node id, not a phantom.

Before #716, `_import_js` only rewrote `.js → .ts` and `.jsx → .tsx`. Every
other shape (bare path, `.svelte → .svelte.ts`, `./foo` directory imports)
produced an id like `..._foo` while the real file's node id was `..._foo_ts`,
so `build_from_json` dropped the edge as external.
"""

from pathlib import Path

from graphify.extract import (
    _make_id,
    _resolve_with_extensions,
    extract_js,
    extract_svelte,
)


def _write(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _import_targets(result: dict) -> set[str]:
    return {str(e.get("target") or "") for e in result["edges"]
            if e.get("relation") in ("imports", "imports_from")}


# ── _resolve_with_extensions unit tests ──────────────────────────────────────


def test_resolve_returns_existing_path_unchanged(tmp_path):
    p = _write(tmp_path / "foo.ts", "export const x = 1")
    assert _resolve_with_extensions(p) == p


def test_resolve_bare_path_to_ts(tmp_path):
    target = _write(tmp_path / "foo.ts", "export const x = 1")
    bare = tmp_path / "foo"
    assert _resolve_with_extensions(bare) == target


def test_resolve_bare_path_to_tsx(tmp_path):
    target = _write(tmp_path / "Component.tsx", "export const x = 1")
    bare = tmp_path / "Component"
    assert _resolve_with_extensions(bare) == target


def test_resolve_bare_path_to_svelte(tmp_path):
    target = _write(tmp_path / "Card.svelte", "<div></div>")
    bare = tmp_path / "Card"
    assert _resolve_with_extensions(bare) == target


def test_resolve_prefers_ts_over_svelte_when_both_exist(tmp_path):
    """Vite resolver order: .ts wins over .svelte for ambiguous bare paths."""
    ts_target = _write(tmp_path / "foo.ts", "export const x = 1")
    _write(tmp_path / "foo.svelte", "<div></div>")
    bare = tmp_path / "foo"
    assert _resolve_with_extensions(bare) == ts_target


def test_resolve_directory_to_index_ts(tmp_path):
    pkg = tmp_path / "queue"
    target = _write(pkg / "index.ts", "export const x = 1")
    assert _resolve_with_extensions(pkg) == target


def test_resolve_directory_prefers_index_ts_over_index_js(tmp_path):
    pkg = tmp_path / "queue"
    target = _write(pkg / "index.ts", "export const x = 1")
    _write(pkg / "index.js", "module.exports = {}")
    assert _resolve_with_extensions(pkg) == target


def test_resolve_svelte_to_svelte_ts_for_rune_files(tmp_path):
    """Svelte 5: `from './foo.svelte'` may actually point at `foo.svelte.ts`
    (a rune-only TypeScript file with no .svelte file). The resolver must
    APPEND .ts to the full filename, not swap suffixes."""
    target = _write(tmp_path / "is-mobile.svelte.ts",
                    "export const isMobile = () => true")
    written_as = tmp_path / "is-mobile.svelte"
    resolved = _resolve_with_extensions(written_as)
    assert resolved == target, (
        f"Expected resolution to is-mobile.svelte.ts; got {resolved}"
    )


def test_resolve_js_to_ts_when_real_file_is_ts(tmp_path):
    """TS ESM convention: imports written as .js but the actual file is .ts."""
    target = _write(tmp_path / "foo.ts", "export const x = 1")
    written_as = tmp_path / "foo.js"
    assert _resolve_with_extensions(written_as) == target


def test_resolve_jsx_to_tsx_when_real_file_is_tsx(tmp_path):
    target = _write(tmp_path / "Component.tsx", "export const x = 1")
    written_as = tmp_path / "Component.jsx"
    assert _resolve_with_extensions(written_as) == target


def test_resolve_returns_unchanged_when_nothing_matches(tmp_path):
    """External / truly missing paths fall back to the input — preserves
    pre-#716 behavior of becoming an external phantom edge."""
    nothing = tmp_path / "does_not_exist"
    assert _resolve_with_extensions(nothing) == nothing


def test_resolve_real_js_stays_js_when_ts_does_not_exist(tmp_path):
    """If `.js` exists and `.ts` does not, keep the `.js` rewrite from
    triggering — return the existing file."""
    target = _write(tmp_path / "foo.js", "module.exports = 1")
    assert _resolve_with_extensions(target) == target


# ── End-to-end: bare-path imports in pure TS files ───────────────────────────


def test_bare_path_import_resolves_in_ts_file(tmp_path):
    """The #716 reproducer: TS file imports a sibling without an extension."""
    target = _write(tmp_path / "type-helpers.ts",
                    "export type GetNestedType<T> = T")
    importer = _write(tmp_path / "page.ts",
                      "import type { GetNestedType } from './type-helpers'\n")
    result = extract_js(importer)
    expected = _make_id(str(target))
    assert expected in _import_targets(result), (
        f"Bare-path .ts import must resolve to target node id; "
        f"expected {expected}; got {_import_targets(result)}"
    )


def test_directory_import_resolves_to_index_ts(tmp_path):
    """`from './queue'` must resolve to `./queue/index.ts`."""
    target = _write(tmp_path / "queue" / "index.ts",
                    "export const enqueue = () => {}")
    importer = _write(tmp_path / "page.ts",
                      "import { enqueue } from './queue'\n")
    result = extract_js(importer)
    expected = _make_id(str(target))
    assert expected in _import_targets(result), (
        f"Directory import must resolve to ./queue/index.ts; "
        f"expected {expected}; got {_import_targets(result)}"
    )


# ── End-to-end: .svelte → .svelte.ts (Svelte 5 rune files) ───────────────────


def test_dot_svelte_import_resolves_to_dot_svelte_ts(tmp_path):
    """Svelte 5 rune file: import written as .svelte, real file is .svelte.ts."""
    target = _write(tmp_path / "is-mobile.svelte.ts",
                    "export const isMobile = () => true")
    importer = _write(tmp_path / "page.ts",
                      "import { isMobile } from './is-mobile.svelte'\n")
    result = extract_js(importer)
    expected = _make_id(str(target))
    assert expected in _import_targets(result), (
        f".svelte → .svelte.ts resolution failed; "
        f"expected {expected}; got {_import_targets(result)}"
    )


# ── Regression guards: existing behavior preserved ───────────────────────────


def test_explicit_ts_import_still_works(tmp_path):
    """The most common case — import with explicit .ts extension — must
    continue to work after the resolver change."""
    target = _write(tmp_path / "foo.ts", "export const x = 1")
    importer = _write(tmp_path / "page.ts",
                      "import { x } from './foo.ts'\n")
    result = extract_js(importer)
    expected = _make_id(str(target))
    assert expected in _import_targets(result), (
        f"Explicit .ts imports must still resolve; "
        f"expected {expected}; got {_import_targets(result)}"
    )


def test_explicit_svelte_import_still_works(tmp_path):
    """Real .svelte file imports must still resolve when the .svelte file
    exists (i.e. don't accidentally redirect to a non-existent .svelte.ts)."""
    target = _write(tmp_path / "Card.svelte", "<div></div>")
    importer = _write(tmp_path / "page.ts",
                      "import Card from './Card.svelte'\n")
    result = extract_js(importer)
    expected = _make_id(str(target))
    assert expected in _import_targets(result), (
        f"Existing .svelte imports must resolve to the .svelte node, "
        f"not get redirected; expected {expected}; "
        f"got {_import_targets(result)}"
    )


def test_external_module_unchanged(tmp_path):
    """Bare module specifiers (no leading dot, no alias match) must still
    fall through to the external/last-segment path — don't accidentally
    treat 'lodash' as a relative path."""
    importer = _write(tmp_path / "page.ts",
                      "import _ from 'lodash-es'\n")
    result = extract_js(importer)
    targets = _import_targets(result)
    # The target should be the bare module name, not a resolved file path
    assert "lodash_es" in targets or any("lodash" in t for t in targets), (
        f"External module specifier should still produce an external "
        f"reference; got {targets}"
    )


# ── End-to-end: alias-resolved imports go through the same resolver ─────────


def test_alias_import_with_bare_path_resolves(tmp_path):
    """`$lib/foo` (alias + bare path) — both layers must work together."""
    src = tmp_path / "src"
    target = _write(src / "lib" / "type-helpers.ts",
                    "export type X = string")
    _write(tmp_path / "tsconfig.json",
           '{"compilerOptions":{"paths":{"$lib":["./src/lib"],'
           '"$lib/*":["./src/lib/*"]}}}')
    importer_dir = src / "routes"
    importer = _write(importer_dir / "page.ts",
                      "import type { X } from '$lib/type-helpers'\n")
    result = extract_js(importer)
    expected = _make_id(str(target))
    assert expected in _import_targets(result), (
        f"Alias + bare-path resolution failed; "
        f"expected {expected}; got {_import_targets(result)}"
    )


# ── End-to-end: dynamic_import in .svelte regex pass uses resolver ──────────


def test_dynamic_import_bare_path_resolves(tmp_path):
    """The regex pass for `import('...')` in .svelte files must also use
    the new resolver — otherwise dynamic imports of bare paths still
    produce phantom edges."""
    target = _write(tmp_path / "Heavy.svelte.ts",
                    "export const heavy = () => 1")
    importer = _write(tmp_path / "page.svelte", """\
<script>
  const lazy = () => import('./Heavy.svelte')
</script>
""")
    result = extract_svelte(importer)
    dyn_targets = {str(e.get("target") or "") for e in result["edges"]
                   if e.get("relation") == "dynamic_import"}
    expected = _make_id(str(target))
    assert expected in dyn_targets, (
        f"dynamic_import of .svelte that's actually .svelte.ts must "
        f"resolve through the new resolver; "
        f"expected {expected}; got {dyn_targets}"
    )
