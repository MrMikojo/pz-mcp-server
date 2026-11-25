"""Two indexes, built from the user's own PZ install and cached on disk (never shipped: they hold game data).

api.txt     every public class, method and field under zombie.* in projectzomboid.jar, one per line:
                class zombie.inventory.types.Clothing extends zombie.inventory.InventoryItem
                zombie.inventory.types.Clothing.getBodyLocation() -> String
                zombie.characters.IsoGameCharacter.x: float  [static]
items.json  every item, craftRecipe, evolvedrecipe and fixing block in media/scripts, with file:line.

They are rebuilt when projectzomboid.jar or media/scripts changes (a game update).
"""
import json
import os
import re
import struct
import zipfile

from . import paths

INDEX_VERSION = 2
PUBLIC, STATIC, SYNTH, BRIDGE = 0x0001, 0x0008, 0x1000, 0x0040
PRIM = {"B": "byte", "C": "char", "D": "double", "F": "float", "I": "int", "J": "long", "S": "short", "Z": "boolean",
        "V": "void"}


# ---------------- Java API ----------------
def _type(desc, i=0):
    dims = 0
    while desc[i] == "[":
        dims, i = dims + 1, i + 1
    c = desc[i]
    if c == "L":
        j = desc.index(";", i)
        name = desc[i + 1:j].replace("/", ".").replace("$", ".")
        if name.startswith(("java.", "se.krka.")):
            name = name.rsplit(".", 1)[-1]
        return name + "[]" * dims, j + 1
    return PRIM[c] + "[]" * dims, i + 1


def method_sig(desc):
    """'(Ljava/lang/String;I)Z' -> ('String, int', 'boolean')."""
    args, i = [], 1
    while desc[i] != ")":
        t, i = _type(desc, i)
        args.append(t)
    return ", ".join(args), _type(desc, i + 1)[0]


def parse_class(data):
    """(name, super, access, [(kind, static, name, sig)]) from one class file, or None."""
    if data[:4] != b"\xca\xfe\xba\xbe":
        return None
    pos, count = 10, struct.unpack(">H", data[8:10])[0]
    pool, k = [None] * count, 1
    while k < count:
        tag = data[pos]
        if tag == 1:
            n = struct.unpack(">H", data[pos + 1:pos + 3])[0]
            pool[k] = data[pos + 3:pos + 3 + n].decode("utf-8", "replace")
            pos += 3 + n
        elif tag in (3, 4):
            pos += 5
        elif tag in (5, 6):
            pos += 9
            k += 1
        elif tag == 7:
            pool[k] = ("class", struct.unpack(">H", data[pos + 1:pos + 3])[0])
            pos += 3
        elif tag in (8, 16, 19, 20):
            pos += 3
        elif tag == 15:
            pos += 4
        elif tag in (9, 10, 11, 12, 17, 18):
            pos += 5
        else:
            return None
        k += 1

    def cls(idx):
        e = pool[idx]
        return pool[e[1]].replace("/", ".") if e else ""
    access, this, sup = struct.unpack(">HHH", data[pos:pos + 6])
    pos += 6
    name, supname = cls(this), (cls(sup) if sup else "")
    n_if = struct.unpack(">H", data[pos:pos + 2])[0]
    pos += 2 + 2 * n_if
    members = []
    for kind in ("field", "method"):
        n = struct.unpack(">H", data[pos:pos + 2])[0]
        pos += 2
        for _ in range(n):
            acc, ni, di, na = struct.unpack(">HHHH", data[pos:pos + 8])
            pos += 8
            for _a in range(na):
                pos += 6 + struct.unpack(">I", data[pos + 2:pos + 6])[0]
            mname = pool[ni]
            if not (acc & PUBLIC) or acc & (SYNTH | BRIDGE) or mname in ("<init>", "<clinit>"):
                continue
            if kind == "method":
                a, r = method_sig(pool[di])
                members.append((kind, bool(acc & STATIC), mname, f"({a}) -> {r}"))
            else:
                members.append((kind, bool(acc & STATIC), mname, ": " + _type(pool[di])[0]))
    return name, supname, access, members


def build_api(jar, out):
    lines, classes = [], 0
    with zipfile.ZipFile(jar) as z:
        for entry in sorted(z.namelist()):
            if not entry.startswith("zombie/") or not entry.endswith(".class"):
                continue
            base = entry.rsplit("/", 1)[-1][:-6]
            if "$" in base and base.split("$")[-1].isdigit():        # anonymous classes
                continue
            got = parse_class(z.read(entry))
            if not got or not got[2] & PUBLIC:
                continue
            name, sup, _acc, members = got
            classes += 1
            name = name.replace("$", ".")
            lines.append(f"class {name}" + (f" extends {sup.replace('$', '.')}" if sup and sup != "java.lang.Object" else ""))
            for _kind, static, m, sig in members:
                lines.append(f"{name}.{m}{sig}" + ("  [static]" if static else ""))
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return classes


def load_api(path):
    """{class: (parent, [member lines])}."""
    api = {}
    with open(path, encoding="utf-8") as f:
        for ln in f:
            ln = ln.rstrip("\n")
            if ln.startswith("class "):
                parts = ln[6:].split(" extends ")
                api[parts[0]] = (parts[1] if len(parts) > 1 else "", [])
            elif ln:
                cls = ln.split("(")[0].split(":")[0].rsplit(".", 1)[0]
                if cls in api:
                    api[cls][1].append(ln)
    return api


# ---------------- items and recipes ----------------
HEAD = re.compile(r"^\s*(item|craftRecipe|evolvedrecipe|fixing)\s+([A-Za-z0-9_.\- ]+?)\s*(\{)?\s*$")
MODULE = re.compile(r"^\s*module\s+([A-Za-z0-9_]+)")
FIELD = re.compile(r"^\s*([A-Za-z0-9_]+)\s*=\s*(.*?)\s*,?\s*$")


def _strip_comments(lines):
    out, block = [], False
    for ln in lines:
        s = ln
        if block:
            end = s.find("*/")
            if end < 0:
                out.append("")
                continue
            s, block = s[end + 2:], False
        while "/*" in s:
            a = s.index("/*")
            b = s.find("*/", a + 2)
            if b < 0:
                s, block = s[:a], True
                break
            s = s[:a] + s[b + 2:]
        out.append(s.split("//")[0] if "//" in s and "://" not in s else s)
    return out


def parse_scripts(text, rel, items, recipes):
    """Add the item and recipe blocks of one script file. Item fields are the block's own lines only: nested
    blocks (component FluidContainer { ... }) do not leak their keys into the item."""
    raw = text.splitlines()
    lines = _strip_comments(raw)
    module, i = "Base", 0
    while i < len(lines):
        m = MODULE.match(lines[i])
        if m:
            module = m.group(1)
        h = HEAD.match(lines[i])
        brace_here = bool(h and h.group(3))
        if h and (brace_here or (i + 1 < len(lines) and lines[i + 1].strip().startswith("{"))):
            kind, name, start = h.group(1), h.group(2).strip(), i
            j = i if brace_here else i + 1
            depth, body, own = 0, [], {}
            while j < len(lines):
                ln = lines[j]
                before = depth
                depth += ln.count("{") - ln.count("}")
                if j > start:
                    body.append(raw[j])
                if kind == "item" and before == 1 and "{" not in ln and "}" not in ln:
                    fm = FIELD.match(ln)
                    if fm:
                        own[fm.group(1)] = fm.group(2).rstrip(",").strip()
                if depth <= 0 and (j > start or brace_here and "}" in ln):
                    break
                j += 1
            where = f"{rel}:{start + 1}"
            if kind == "item":
                items.append({"id": f"{module}.{name}", "module": module, "name": name, "where": where, "f": own})
            else:
                recipes.append({"kind": kind, "name": name, "module": module, "where": where,
                                "text": "\n".join(x.rstrip() for x in body[:80] if x.strip())})
            i = j
        i += 1


def build_items(pz, out):
    root = os.path.join(pz, "media", "scripts")
    items, recipes = [], []
    for r, _d, files in os.walk(root):
        for fn in sorted(files):
            if fn.endswith(".txt"):
                p = os.path.join(r, fn)
                with open(p, encoding="utf-8", errors="replace") as f:
                    parse_scripts(f.read(), os.path.relpath(p, pz).replace("\\", "/"), items, recipes)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"items": items, "recipes": recipes}, f)
    return len(items), len(recipes)


# ---------------- cache ----------------
def _scripts_stamp(pz):
    n, newest = 0, 0.0
    for r, _d, files in os.walk(os.path.join(pz, "media", "scripts")):
        for fn in files:
            if fn.endswith(".txt"):
                n += 1
                newest = max(newest, os.path.getmtime(os.path.join(r, fn)))
    return [n, int(newest)]


def _stamp(pz):
    jar = os.path.join(pz, "projectzomboid.jar")
    st = os.stat(jar)
    return {"version": INDEX_VERSION, "pz": os.path.realpath(pz), "jar": [st.st_size, int(st.st_mtime)],
            "scripts": _scripts_stamp(pz)}


class Indexes:
    """Loads the cached indexes, building them first when missing or stale."""

    def __init__(self):
        self._api = None
        self._items = None

    def _files(self):
        d = paths.cache_dir()
        return os.path.join(d, "api.txt"), os.path.join(d, "items.json"), os.path.join(d, "meta.json")

    def status(self):
        api, items, meta = self._files()
        try:
            with open(meta, encoding="utf-8") as f:
                m = json.load(f)
        except (OSError, ValueError):
            m = None
        pz = paths.pz_dir()
        fresh = bool(m and pz and m == _stamp(pz) and os.path.exists(api) and os.path.exists(items))
        return {"cache": os.path.dirname(meta), "built": m is not None, "fresh": fresh, "meta": m}

    def rebuild(self):
        pz = paths.pz_dir()
        if not pz:
            raise RuntimeError("PZ folder not found: set PZ_DIR to the folder with projectzomboid.jar")
        api, items, meta = self._files()
        classes = build_api(os.path.join(pz, "projectzomboid.jar"), api)
        n_items, n_recipes = build_items(pz, items)
        with open(meta, "w", encoding="utf-8") as f:
            json.dump(_stamp(pz), f)
        self._api = self._items = None
        return classes, n_items, n_recipes

    def _ensure(self):
        if not self.status()["fresh"]:
            self.rebuild()

    def api(self):
        if self._api is None:
            self._ensure()
            self._api = load_api(self._files()[0])
        return self._api

    def items(self):
        if self._items is None:
            self._ensure()
            with open(self._files()[1], encoding="utf-8") as f:
                self._items = json.load(f)
        return self._items
