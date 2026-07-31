"""Export the OpenAPI fragment for the two search/browse endpoints (design doc §3.2).

This is the artifact P3 hands to P2 (T282737780) to merge into the source-of-truth
OpenAPI 3.1 spec — which is in turn what P1's SDK codegen consumes. Keeping only the
/v1/listings paths + the schemas they reference avoids dumping unrelated app internals.

Run:  uv run python export_openapi.py   ->   openapi/listings.json
"""

from __future__ import annotations

import json
import pathlib

from app.main import app

KEEP_PATHS = {"/v1/listings", "/v1/listings/search"}


def build_fragment() -> dict:
    spec = app.openapi()
    paths = {p: spec["paths"][p] for p in KEEP_PATHS if p in spec["paths"]}

    # collect referenced component schemas transitively
    schemas = spec.get("components", {}).get("schemas", {})
    wanted: set[str] = set()

    def visit(node) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
                name = ref.split("/")[-1]
                if name not in wanted:
                    wanted.add(name)
                    visit(schemas.get(name, {}))
            for v in node.values():
                visit(v)
        elif isinstance(node, list):
            for v in node:
                visit(v)

    visit(paths)
    return {
        "openapi": spec.get("openapi", "3.1.0"),
        "info": {"title": "Bazaar Search & Discovery (P3 fragment)", "version": "0.1.0"},
        "paths": paths,
        "components": {"schemas": {n: schemas[n] for n in sorted(wanted) if n in schemas}},
    }


if __name__ == "__main__":
    out = pathlib.Path("openapi/listings.json")
    out.parent.mkdir(exist_ok=True)
    fragment = build_fragment()
    out.write_text(json.dumps(fragment, indent=2) + "\n")
    print(f"Wrote {out} — {len(fragment['paths'])} paths, "
          f"{len(fragment['components']['schemas'])} schemas")
