#!/usr/bin/env python3
"""Emit a customer-safe subset of the AegionAI Guard OpenAPI spec.

Reads aegion-guard-api.openapi.yaml (the full internal reference) and writes
aegion-guard-api.customer.openapi.yaml with every operation marked `x-internal: true`
removed — plus any path/tag/component that becomes orphaned as a result. Hand the
generated file to customers; keep the full one for internal teams.

    python build_customer_openapi.py
    python build_customer_openapi.py --audience customer-integration   # tighter: integration only

Requires PyYAML (pip install pyyaml).
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

try:
    import yaml
except ImportError:
    sys.exit("PyYAML required: pip install pyyaml")

HERE = pathlib.Path(__file__).resolve().parent
SRC = HERE / "aegion-guard-api.openapi.yaml"
DST = HERE / "aegion-guard-api.customer.openapi.yaml"

_METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--audience",
        default=None,
        help="Keep ONLY operations whose x-audience is in this comma list "
        "(e.g. 'customer-integration,customer-reporting'). Default: drop x-internal only.",
    )
    ap.add_argument("--out", default=str(DST))
    args = ap.parse_args()
    keep_audiences = set(args.audience.split(",")) if args.audience else None

    spec = yaml.safe_load(SRC.read_text())

    def keep_op(op: dict) -> bool:
        if op.get("x-internal") is True:
            return False
        if keep_audiences is not None and op.get("x-audience") not in keep_audiences:
            return False
        return True

    # 1. Filter operations; drop paths that end up with no operations.
    new_paths = {}
    for path, item in (spec.get("paths") or {}).items():
        kept = {k: v for k, v in item.items() if k not in _METHODS or keep_op(v)}
        if any(m in kept for m in _METHODS):
            new_paths[path] = kept
    spec["paths"] = new_paths

    # 2. Keep only tags still referenced by a surviving operation.
    used_tags = {t for item in new_paths.values() for m, op in item.items()
                 if m in _METHODS for t in (op.get("tags") or [])}
    if "tags" in spec:
        spec["tags"] = [t for t in spec["tags"] if t.get("name") in used_tags]

    # 3. Prune components ($ref'd schemas/responses/params) no longer referenced ANYWHERE.
    #    A component's `$ref` string appears only at use sites (its own definition key does not),
    #    so "ref string absent from the whole serialized spec" == unused. Iterate to convergence so a
    #    schema used only by an already-removed schema also drops.
    components = spec.get("components") or {}
    while True:
        blob = yaml.safe_dump(spec)
        removed = False
        for kind in ("schemas", "responses", "parameters"):
            comps = components.get(kind, {})
            for name in list(comps):
                if f"#/components/{kind}/{name}" not in blob:
                    del comps[name]
                    removed = True
        if not removed:
            break
    for kind in ("schemas", "responses", "parameters"):
        if kind in components and not components[kind]:
            del components[kind]

    # 4. Note the provenance in the title/description.
    spec["info"]["title"] = spec["info"]["title"] + " (Customer Edition)"
    spec["info"]["description"] = (
        "> Customer-facing subset — internal operations omitted. Generated from the full spec by "
        "build_customer_openapi.py.\n\n" + spec["info"].get("description", "")
    )

    out = pathlib.Path(args.out)
    out.write_text(yaml.safe_dump(spec, sort_keys=False, width=100))
    n_ops = sum(1 for item in new_paths.values() for m in item if m in _METHODS)
    print(f"wrote {out.name}: {len(new_paths)} paths, {n_ops} operations"
          + (f" (audiences: {sorted(keep_audiences)})" if keep_audiences else " (x-internal removed)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
