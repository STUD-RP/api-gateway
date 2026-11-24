"""Vérifie les contrats OpenAPI STUD'RP sans accès réseau.

- YAML valide, toutes les $ref résolues (y compris entre fichiers)
- chaque exemple (requêtes, réponses, paramètres) validé contre son schéma (JSON Schema 2020-12)
- conventions : operationId unique, summary/description/tags, exemple sur les 2xx,
  paramètres de chemin déclarés, pas de DELETE sur les ressources comptables,
  propriétés en camelCase, montants suffixés Cents, erreurs en problem+json.
Usage : python3 -I check_contracts.py <dossier contracts>
"""
import copy
import os
import re
import sys

import jsonschema
import yaml

ROOT = os.path.abspath(sys.argv[1])
errors, warnings = [], []
_cache = {}


def load(path):
    path = os.path.abspath(path)
    if path not in _cache:
        with open(path, encoding="utf-8") as fh:
            _cache[path] = yaml.safe_load(fh)
    return _cache[path]


def pointer(doc, frag):
    node = doc
    for part in [p for p in frag.lstrip("/").split("/") if p]:
        part = part.replace("~1", "/").replace("~0", "~")
        node = node[part]
    return node


def resolve_ref(ref, base_file):
    file_part, _, frag = ref.partition("#")
    target = os.path.normpath(os.path.join(os.path.dirname(base_file), file_part)) if file_part else base_file
    if not os.path.exists(target):
        raise KeyError(f"fichier introuvable {target}")
    return pointer(load(target), frag), target


def deref(node, base_file, stack=()):
    """Inline toutes les $ref (les frères d'une $ref sont fusionnés, comme en 3.1)."""
    if isinstance(node, dict):
        if "$ref" in node and isinstance(node["$ref"], str):
            key = (base_file, node["$ref"])
            if key in stack:
                raise RecursionError(f"cycle {node['$ref']}")
            try:
                target, tfile = resolve_ref(node["$ref"], base_file)
            except (KeyError, TypeError) as exc:
                raise KeyError(f"$ref non résolue {node['$ref']} depuis {os.path.relpath(base_file, ROOT)} ({exc})")
            out = deref(copy.deepcopy(target), tfile, stack + (key,))
            siblings = {k: deref(v, base_file, stack) for k, v in node.items() if k != "$ref"}
            if siblings and isinstance(out, dict):
                out = {**out, **siblings}
            return out
        return {k: deref(v, base_file, stack) for k, v in node.items()}
    if isinstance(node, list):
        return [deref(v, base_file, stack) for v in node]
    return node


def strip_oas(schema):
    """Retire les mots-clés OpenAPI non JSON Schema qui gêneraient la validation."""
    if isinstance(schema, dict):
        return {k: strip_oas(v) for k, v in schema.items() if k not in ("example", "discriminator", "xml", "externalDocs")}
    if isinstance(schema, list):
        return [strip_oas(v) for v in schema]
    return schema


def check_example(where, schema, value):
    s = strip_oas(schema)
    validator = jsonschema.Draft202012Validator(s, format_checker=jsonschema.FormatChecker())
    for err in sorted(validator.iter_errors(value), key=lambda e: list(e.path)):
        loc = "/".join(str(p) for p in err.absolute_path) or "(racine)"
        errors.append(f"{where}: exemple invalide à {loc} : {err.message[:160]}")


def examples_of(media):
    out = []
    if "example" in media:
        out.append(("example", media["example"]))
    for name, ex in (media.get("examples") or {}).items():
        if "value" in ex:
            out.append((name, ex["value"]))
    return out


CAMEL = re.compile(r"^[a-z][a-zA-Z0-9]*$")
MONEY_WORD = re.compile(r"(amount|price|total|balance|fee|salary|bonus|limit)$", re.I)
LEDGER = re.compile(r"(accounting|stock|sales|payments|purchases|movements)")


def walk_properties(schema, where, seen):
    if isinstance(schema, dict):
        if id(schema) in seen:
            return
        seen.add(id(schema))
        for name, sub in (schema.get("properties") or {}).items():
            if not CAMEL.match(name):
                errors.append(f"{where}: propriété '{name}' pas en camelCase")
            types = sub.get("type") if isinstance(sub, dict) else None
            numeric = types in ("integer", "number") or (isinstance(types, list) and {"integer", "number"} & set(types))
            if MONEY_WORD.search(name) and numeric and not name.endswith("Cents"):
                errors.append(f"{where}: montant '{name}' doit se terminer par Cents")
        for v in schema.values():
            walk_properties(v, where, seen)
    elif isinstance(schema, list):
        for v in schema:
            walk_properties(v, where, seen)


def check_contract(path):
    rel = os.path.relpath(path, ROOT)
    raw = load(path)
    spec = deref(raw, path)
    if spec.get("openapi") != "3.1.0":
        errors.append(f"{rel}: openapi doit valoir 3.1.0")
    for key in ("info", "paths"):
        if key not in spec:
            errors.append(f"{rel}: '{key}' manquant")
    op_ids = []
    gateway = rel.startswith("gateway")
    for p, item in (spec.get("paths") or {}).items():
        if not gateway and not (p == "/health" or p.startswith("/v1/")):
            errors.append(f"{rel} {p}: chemin hors convention (/health ou /v1/...)")
        if p.startswith("/v1/associations/") and "{association}" not in p:
            errors.append(f"{rel} {p}: doit contenir {{association}}")
        path_params = set(re.findall(r"{([^}]+)}", p))
        common = item.get("parameters", [])
        for method, op in item.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            where = f"{rel} {method.upper()} {p}"
            if method == "delete" and LEDGER.search(p):
                errors.append(f"{where}: DELETE interdit sur une ressource comptable/stock/vente/paiement")
            for k in ("operationId", "summary", "description", "tags", "responses"):
                if k not in op:
                    errors.append(f"{where}: '{k}' manquant")
            op_ids.append(op.get("operationId"))
            params = common + op.get("parameters", [])
            declared = {pr["name"] for pr in params if pr.get("in") == "path"}
            if declared != path_params:
                errors.append(f"{where}: paramètres de chemin {sorted(declared)} ≠ {sorted(path_params)}")
            for pr in params:
                if "example" in pr and "schema" in pr:
                    check_example(f"{where} param {pr['name']}", pr["schema"], pr["example"])
            rb = op.get("requestBody")
            if rb:
                for mt, media in rb.get("content", {}).items():
                    exs = examples_of(media)
                    if not exs:
                        errors.append(f"{where}: requestBody {mt} sans exemple")
                    for name, val in exs:
                        check_example(f"{where} requête[{name}]", media.get("schema", {}), val)
            for code, resp in (op.get("responses") or {}).items():
                content = resp.get("content", {})
                if str(code).startswith(("4", "5")) and "application/problem+json" not in content:
                    errors.append(f"{where} {code}: une erreur doit être en application/problem+json")
                if str(code).startswith("2") and code != "204" and content:
                    has = any(examples_of(m) for m in content.values())
                    if not has:
                        errors.append(f"{where} {code}: réponse sans exemple")
                for mt, media in content.items():
                    for name, val in examples_of(media):
                        check_example(f"{where} {code}[{name}]", media.get("schema", {}), val)
    for name, hook in (spec.get("webhooks") or {}).items():
        for method, op in hook.items():
            if method != "post":
                continue
            op_ids.append(op.get("operationId"))
            media = op.get("requestBody", {}).get("content", {}).get("application/json", {})
            exs = examples_of(media)
            if not exs:
                errors.append(f"{rel} webhook {name}: sans exemple")
            for ex_name, val in exs:
                check_example(f"{rel} webhook {name}[{ex_name}]", media.get("schema", {}), val)
                if isinstance(val, dict) and val.get("type") != name:
                    errors.append(f"{rel} webhook {name}: l'exemple a le type {val.get('type')}")
    walk_properties(spec.get("components", {}).get("schemas", {}), rel, set())
    return op_ids


all_ids = []
contracts = sorted(f for f in os.listdir(ROOT) if f.endswith(".openapi.yaml"))
for f in contracts:
    try:
        ids = check_contract(os.path.join(ROOT, f))
        all_ids += [(f, i) for i in ids]
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{f}: {type(exc).__name__}: {exc}")
for common in ("common/schemas.yaml", "common/events.yaml"):
    try:
        deref(load(os.path.join(ROOT, common)), os.path.join(ROOT, common))
        walk_properties(load(os.path.join(ROOT, common)).get("components", {}).get("schemas", {}), common, set())
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{common}: {exc}")
seen = {}
for f, i in all_ids:
    if i in seen:
        errors.append(f"operationId '{i}' en double ({seen[i]} et {f})")
    seen[i] = f

print(f"Contrats vérifiés : {', '.join(contracts)}")
print(f"Opérations : {len(all_ids)}")
for e in errors:
    print("ERREUR", e)
print("OK" if not errors else f"{len(errors)} erreur(s)")
sys.exit(1 if errors else 0)
