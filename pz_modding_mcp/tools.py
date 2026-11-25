"""The tools, as plain functions (server.py registers them with MCP; the tests call them directly).

Every answer is short plain text, cut to a few thousand characters, so small local models keep their context.
Read-only: nothing here writes outside the index cache.
"""
import contextlib
import functools
import io
import os
import re
import subprocess

from . import indexes, paths, pzcheck

CAP = 4000
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
IDX = indexes.Indexes()
SHOW = ("DisplayName", "DisplayCategory", "ItemType", "BodyLocation", "CanBeEquipped", "Weight", "MaxDamage",
        "MinDamage", "MaxRange", "ConditionMax", "Capacity", "WeightReduction", "HungerChange", "DaysFresh", "Tags")
NO_PZ = "PZ folder not found. Set PZ_DIR to the folder that holds projectzomboid.jar (see pz_status)."


def _cut(text, cap=CAP):
    return text if len(text) <= cap else text[:cap] + f"\n... ({len(text) - cap} more characters cut)"


def _guard(fn):
    """Turn setup errors into a short answer instead of a stack trace."""
    @functools.wraps(fn)
    def wrapped(*a, **k):
        if not paths.pz_dir():
            return NO_PZ
        try:
            return fn(*a, **k)
        except (OSError, RuntimeError, ValueError) as e:
            return f"(error: {e})"
    return wrapped


# ---------------- status ----------------
def pz_status() -> str:
    """Setup check: which PZ folder is used, whether the indexes are built, and whether pz_source is on.
    Call it first if another tool says something is missing."""
    pz = paths.pz_dir()
    st = IDX.status()
    out = [f"PZ folder: {pz or 'NOT FOUND (set PZ_DIR)'}",
           f"index cache: {st['cache']} ({'fresh' if st['fresh'] else 'built, but stale' if st['built'] else 'not built yet'})",
           f"pz_source: {'on' if paths.cfr_jar() and paths.java_exe() else 'off (set PZ_MCP_CFR to a CFR jar)'}",
           "show_lua_function may read: " + "; ".join(paths.readable_roots())]
    if pz and not st["fresh"]:
        out.append("The indexes build on first use (about 10-30 s), or call pz_rebuild_indexes now.")
    return "\n".join(out)


@_guard
def pz_rebuild_indexes() -> str:
    """Rebuild the Java API and item indexes from the installed game. Only needed after a PZ update if a tool
    seems out of date: the tools rebuild by themselves when the game files change."""
    classes, items, recipes = IDX.rebuild()
    return f"rebuilt: {classes} classes, {items} items, {recipes} recipes"


# ---------------- pzcheck ----------------
_JAR = {}


def _jar():
    jp = paths.jar_path()
    if jp not in _JAR:
        _JAR.clear()
        _JAR[jp] = pzcheck.Jar(jp)
    return _JAR[jp]


@_guard
def pz_check(query: str) -> str:
    """Is a Project Zomboid name real? Answers YES or NO, with the real signature. query = a command and its
    names: "method IsoPlayer getStats", "field IsoPlayer x", "class ItemContainer" (also says if Lua can see it),
    "members IsoPlayer Stat", "find getModData", "event OnZombieDead", "global getPlayer",
    "lua ISTimedActionQueue.add", "grep sendClientCommand(", "script item Hammer".
    If it says NO, do not use that name."""
    parts = query.split()
    if len(parts) < 2 or parts[0] not in pzcheck.COMMANDS:
        return ('give a command and a name, e.g. "method IsoPlayer getStats". Commands: '
                + ", ".join(pzcheck.COMMANDS))
    if parts[0] in ("grep", "script"):
        parts = [parts[0], query.split(None, 1)[1]]
    fn, n_args = pzcheck.COMMANDS[parts[0]]
    if len(parts) - 1 < n_args:
        return f"{parts[0]} needs {n_args} name(s)"
    extra = 1 if parts[0] == "members" and len(parts) > 2 else 0
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = fn(_jar(), paths.pz_dir(), *parts[1:1 + n_args + extra])
    text = buf.getvalue().strip()
    return _cut(text or ("YES" if code == 0 else "NO"))


# ---------------- Java API ----------------
def _short_names(api):
    short = {}
    for c in api:
        short.setdefault(c.rsplit(".", 1)[-1], []).append(c)
    return short


def _member_name(line, cls):
    return line[len(cls) + 1:].split("(")[0].split(":")[0]


@_guard
def pz_api(name: str, max_hits: int = 40) -> str:
    """Project Zomboid's Java API, from the installed game's jar: the public methods and fields Lua can call on
    PZ objects, with argument and return types. name = a class ("IsoPlayer": its members and its parents'),
    "Class.member" ("IsoPlayer.getStats", parents count too), or a member name alone ("getModData": every class
    that has it). Lua calls methods with a colon: player:getStats()."""
    api = IDX.api()
    q = name.strip().replace(":", ".")
    max_hits = max(1, min(int(max_hits), 200))
    short = _short_names(api)
    if q in api or q in short:
        options = [q] if q in api else short[q]
        cls, out, seen = options[0], [], 0
        if len(options) > 1:
            out.append(f"({len(options)} classes are named {q}: {', '.join(options[:8])}. Showing the first; "
                       "ask with the full name for another.)")
        while cls in api and seen < 10:
            parent, members = api[cls]
            out.append(f"== {cls}" + (f" (extends {parent})" if parent else "") + f": {len(members)} public members")
            out += members[:max_hits]
            if len(members) > max_hits:
                out.append(f"... {len(members) - max_hits} more: ask for one as {cls.rsplit('.', 1)[-1]}.<name>")
            cls, seen = parent, seen + 1
        return _cut("\n".join(out), 6000)
    if "." in q:
        c, m = q.rsplit(".", 1)
        starts = [c] if c in api else short.get(c, [])
        if not starts:
            return f"no PZ class named {c} (try pz_api(\"{m}\") to find classes with that member)"
        hits = []
        for start in starts:
            cls, seen = start, 0
            while cls in api and seen < 10:
                found = [ln for ln in api[cls][1] if _member_name(ln, cls) == m]
                if found:
                    hits += found if cls == start else [f"(inherited from {cls})"] + found
                    break
                cls, seen = api[cls][0], seen + 1
        return _cut("\n".join(hits)) if hits else (
            f"NO: no public member {m} on {c} or its parents. Java interfaces are not followed: "
            f"try pz_api(\"{m}\") or pz_check(\"find {m}\").")
    hits = [ln for cls, (_p, ms) in api.items() for ln in ms if _member_name(ln, cls) == q]
    if not hits:
        near = [ln for _p, ms in api.values() for ln in ms if q.lower() in ln.lower()][:max_hits]
        return _cut("(no exact name; lines that contain it)\n" + "\n".join(near)) if near else \
            f"NO: '{name}' is not in PZ's Java API"
    more = f"\n... {len(hits) - max_hits} more" if len(hits) > max_hits else ""
    return _cut("\n".join(hits[:max_hits]) + more)


# ---------------- PZ's Lua ----------------
@_guard
def pz_lua_search(text: str, max_hits: int = 15, folder: str = "lua") -> str:
    """Search the game's own files for text (plain text, not a regex) and get file:line plus the line.
    folder = "lua" (media/lua, default), "scripts" (media/scripts) or "all" (all of media).
    Use it to see how PZ itself uses a function or event; then show_lua_function to read one function."""
    sub = {"lua": "lua", "scripts": "scripts", "all": ""}.get(folder)
    if sub is None:
        return 'folder must be "lua", "scripts" or "all"'
    if not text.strip():
        return "give some text to search for"
    pz = paths.pz_dir()
    root = os.path.join(pz, "media", sub) if sub else os.path.join(pz, "media")
    max_hits = max(1, min(int(max_hits), 100))
    hits = []
    for r, dirs, files in os.walk(root):
        dirs.sort()
        for f in sorted(files):
            if not f.endswith((".lua", ".txt")):
                continue
            p = os.path.join(r, f)
            try:
                with open(p, encoding="utf-8", errors="replace") as fh:
                    for no, line in enumerate(fh, 1):
                        if text in line:
                            hits.append(f"{os.path.relpath(p, pz)}:{no}: {line.strip()[:160]}")
                            if len(hits) >= max_hits:
                                return _cut("\n".join(hits) + "\n(more hits not shown)")
            except OSError:
                continue
    return "\n".join(hits) if hits else f"'{text}' is not in PZ's {folder} files. If it is a method, try pz_api."


_STARTS = re.compile(r"^(local\s+function\s|function\s|[\w.:]+\s*=\s*\{|[\w.:]+\s*=\s*function|--\s*-{8,})")


@_guard
def show_lua_function(path: str, name: str) -> str:
    """Print ONE Lua function or table from a file, with line numbers, instead of reading a whole file.
    path = a file in your workspace (your mod) or in PZ's media folder, e.g.
    "media/lua/client/ISUI/ISInventoryPane.lua"; name = "ISInventoryPane:onMouseDown", "MyMod.onTick", "Recipe".
    A short path is searched for under the readable folders (see pz_status)."""
    full = None
    for root in paths.readable_roots():
        cand = path if os.path.isabs(path) else os.path.join(root, path)
        if os.path.isfile(cand) and paths.is_readable(cand):
            full = cand
            break
        if not os.path.isabs(path) and path.startswith("media/"):
            cand = os.path.join(os.path.dirname(root), path)
            if os.path.isfile(cand) and paths.is_readable(cand):
                full = cand
                break
    if full is None and not os.path.isabs(path):
        base = os.path.basename(path)
        for root in paths.readable_roots():
            for r, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                if base in files:
                    full = os.path.join(r, base)
                    break
            if full:
                break
    if full is None:
        return f"no readable file {path} (allowed folders: see pz_status)"
    with open(full, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    esc = re.escape(name)
    pat = re.compile(rf"^\s*(local\s+function\s+{esc}\s*\(|function\s+{esc}\s*\(|(local\s+)?{esc}\s*=\s*\{{|"
                     rf"(local\s+)?{esc}\s*=\s*function)")
    start = next((i for i, ln in enumerate(lines) if pat.search(ln)), None)
    if start is None:
        key = re.split(r"[.:]", name)[-1]
        near = [f"{i + 1}: {ln.strip()[:100]}" for i, ln in enumerate(lines) if key in ln][:12]
        return f"'{name}' is not defined in {os.path.basename(full)}. Lines that mention it:\n" + "\n".join(near)
    while start > 0 and lines[start - 1].lstrip().startswith("--"):
        start -= 1
    end, body = start + 1, False
    while end < len(lines) and end - start < 160:
        ln = lines[end]
        if body and ln and not ln[0].isspace() and _STARTS.match(ln):
            break
        if ln.strip() and not ln.lstrip().startswith("--"):
            body = True
        end += 1
        if ln.rstrip() in ("end", "}", "})"):
            break
    out = [f"{full} lines {start + 1}-{end}:"] + [f"{i + 1}: {lines[i]}" for i in range(start, end)]
    if end - start >= 160:
        out.append("(cut at 160 lines)")
    return _cut("\n".join(out), 9000)


# ---------------- items ----------------
def _num(v):
    try:
        return float(str(v).split()[0])
    except (ValueError, IndexError):
        return None


@_guard
def pz_items(query: str, limit: int = 15) -> str:
    """The game's items and recipes (from the installed game's media/scripts), searchable. Examples:
    "Base.Axe"                              one item, all its fields
    "ItemType=base:weapon sort=MaxDamage"   weapons, highest damage first (= is an exact match)
    "Tags~ripclothing"                      items whose Tags contain that text (~ means contains)
    "poncho"                                items whose name or DisplayName contains it
    "recipe RipClothing"                    one craftRecipe, evolvedrecipe or fixing block
    Use it to see which items exist and their full names (Module.Name) before you use them in code."""
    d = IDX.items()
    q = query.strip()
    limit = max(1, min(int(limit), 100))
    if not q:
        return "give a query, e.g. \"Base.Axe\" or \"recipe RipClothing\""
    if q.lower().startswith("recipe"):
        name = q.split(None, 1)[1].strip() if len(q.split()) > 1 else ""
        exact = [r for r in d["recipes"] if r["name"].lower() == name.lower()]
        hits = exact or [r for r in d["recipes"] if name.lower() in r["name"].lower()]
        if not hits:
            return f"no recipe like {name}"
        if not exact and len(hits) > 1:
            return _cut(f"{len(hits)} recipes: " + ", ".join(f"{r['name']} ({r['kind']})" for r in hits[:40]))
        out = [f"{r['kind']} {r['name']} ({r['where']})\n{r['text']}" for r in hits[:3]]
        return _cut("\n\n".join(out))
    byid = {}
    for it in d["items"]:
        byid.setdefault(it["id"].lower(), it)
    plain = not any(c in q for c in " =~")
    it = byid.get(q.lower()) or (byid.get(f"base.{q.lower()}") if plain and "." not in q else None)
    if it:
        return _cut(f"{it['id']} ({it['where']})\n" + "\n".join(f"  {k} = {v}" for k, v in it["f"].items()))
    rows, sort = d["items"], None
    for term in q.split():
        if term.startswith("sort="):
            sort = term[5:]
        elif "~" in term:
            k, v = term.split("~", 1)
            rows = [i for i in rows if v.lower() in str(i["f"].get(k, "")).lower()]
        elif "=" in term:
            k, v = term.split("=", 1)
            rows = [i for i in rows if str(i["f"].get(k, "")).lower() == v.lower()]
        else:
            t = term.lower()
            rows = [i for i in rows if t in i["id"].lower() or t in i["f"].get("DisplayName", "").lower()]
    if sort:
        rows = sorted((i for i in rows if _num(i["f"].get(sort)) is not None), key=lambda i: -_num(i["f"][sort]))
    if not rows:
        return f"no item matches {query}"
    out = [f"{len(rows)} item(s){' (first ' + str(limit) + ')' if len(rows) > limit else ''}:"]
    for it in rows[:limit]:
        bits = [f"{k}={it['f'][k]}" for k in SHOW if k in it["f"]]
        out.append(f"{it['id']}: " + ", ".join(bits)[:260])
    return _cut("\n".join(out), 5000)


# ---------------- decompiled source (optional) ----------------
_KEYWORDS = ("if", "else", "for", "while", "switch", "catch", "return", "new", "throw", "synchronized", "try", "do")
_MEMBER = re.compile(r"^(?: {4}| {8})(?=\S)(?!(?:%s)\b)[\w@<>\[\], ?.]+\s+\w+\s*\(" % "|".join(_KEYWORDS))


def _src_dir():
    d = os.path.join(paths.cache_dir(), "src")
    os.makedirs(d, exist_ok=True)
    return d


@_guard
def pz_source(cls: str, method: str = "") -> str:
    """What a PZ Java method actually does: its decompiled code, made on your PC from your own game jar with
    CFR (off unless PZ_MCP_CFR is set). cls = "IsoPlayer" or "zombie.characters.IsoPlayer"; method = a name
    (all its overloads) or "" for the class outline. For understanding PZ only: never copy PZ code into a mod."""
    cfr, java = paths.cfr_jar(), paths.java_exe()
    if not (cfr and java):
        return "pz_source is off: set PZ_MCP_CFR to a CFR decompiler jar (and Java on PATH, or PZ's jre64)."
    api = IDX.api()
    n = cls.strip().replace("/", ".")
    full = n if n in api else next(iter(sorted(c for c in api if c.rsplit(".", 1)[-1] == n)), None)
    if not full:
        return f"no PZ class named {cls} (ask pz_api)"
    outer = full
    while "." in outer and outer.rsplit(".", 1)[0] in api:        # an inner class lives in its outer class's file
        outer = outer.rsplit(".", 1)[0]
    src = _src_dir()
    path = os.path.join(src, *outer.split(".")) + ".java"
    if not os.path.exists(path):
        try:
            subprocess.run([java, "-jar", cfr, paths.jar_path(), "--jarfilter", "^" + re.escape(outer) + "$",
                            "--outputdir", src, "--silent", "true"], capture_output=True, timeout=180,
                           creationflags=NOWIN)
        except subprocess.TimeoutExpired:
            return "(the decompiler took over 180 s)"
        if not os.path.exists(path):
            return f"(could not decompile {outer})"
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    if not method:
        keep = [f"{i + 1}: {ln.rstrip()}" for i, ln in enumerate(lines)
                if _MEMBER.match(ln) or re.match(r"^\s{4}(public|protected|private|static|final)\s[^(]*[;=]", ln)]
        return _cut(f"{outer} ({len(lines)} lines), members:\n" + "\n".join(keep), 6000)
    pat = re.compile(r"\b" + re.escape(method) + r"\s*\(")
    out, i = [], 0
    while i < len(lines) and len(out) < 220:
        ln = lines[i]
        if pat.search(ln) and _MEMBER.match(ln) and not ln.rstrip().endswith(";"):
            depth, j, opened = 0, i, False
            while j < len(lines):
                depth += lines[j].count("{") - lines[j].count("}")
                opened = opened or "{" in lines[j]
                out.append(f"{j + 1}: {lines[j]}")
                if opened and depth <= 0:
                    break
                j += 1
            out.append("")
            i = j
        i += 1
    if not out:
        parent, seen = api.get(full, ("", []))[0], 0
        while parent and parent in api and seen < 10:
            if any(_member_name(ln, parent) == method for ln in api[parent][1]):
                return f"({method} is inherited from {parent})\n" + pz_source.__wrapped__(parent, method)
            parent, seen = api[parent][0], seen + 1
        return f"{outer} has no method {method} (ask pz_api(\"{cls}.{method}\"))"
    return _cut(f"{outer}:\n" + "\n".join(out), 7000)


ALL = [pz_status, pz_check, pz_api, pz_lua_search, show_lua_function, pz_items, pz_source, pz_rebuild_indexes]
