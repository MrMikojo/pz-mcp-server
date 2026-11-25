#!/usr/bin/env python3
"""pzcheck: look up Project Zomboid (Build 42) names before you write mod code.

It reads PZ's own projectzomboid.jar (class files) and media/lua. Python 3.8+, standard library only.
It prints YES or NO, and for YES the real name and signature. It never prints PZ code.

Usage (PZ folder: --pz <dir>, or the PZ_DIR environment variable, or the Steam default is tried):
  python pzcheck.py class   IsoPlayer                   does the class exist? full name, parent, Lua-exposed?
  python pzcheck.py method  IsoPlayer getStats          does the method exist (also in parent classes)? signatures
  python pzcheck.py field   IsoPlayer x                 does the field exist? type, public or not
  python pzcheck.py members IsoPlayer [text]            list the public methods (optionally containing text)
  python pzcheck.py find    getStats                    which classes have a method with this exact name
  python pzcheck.py event   OnPlayerUpdate              is this a real Lua event? plus an example from PZ's Lua
  python pzcheck.py global  getPlayer                   is this a real Lua global function? signature
  python pzcheck.py lua     ISTimedActionQueue.add      is this function defined in PZ's Lua? file:line + its line
  python pzcheck.py grep    "OnClientCommand"           show up to 20 lines of PZ's Lua that contain the text
  python pzcheck.py script  "item Hammer"               show up to 20 lines of PZ's scripts (media/scripts) with the text

Exit code: 0 = found (YES), 1 = not found (NO), 2 = usage or setup error.
"""
import os
import re
import struct
import sys
import zipfile

DEFAULT_DIRS = [
    r"C:\Program Files (x86)\Steam\steamapps\common\ProjectZomboid",
    os.path.expanduser("~/.steam/steam/steamapps/common/ProjectZomboid"),
    os.path.expanduser("~/.local/share/Steam/steamapps/common/ProjectZomboid"),
    os.path.expanduser("~/Library/Application Support/Steam/steamapps/common/ProjectZomboid/Project Zomboid.app/Contents/Java"),
]
ACC_PUBLIC, ACC_STATIC = 0x0001, 0x0008
PRIM = {"B": "byte", "C": "char", "D": "double", "F": "float", "I": "int", "J": "long", "S": "short", "Z": "boolean", "V": "void"}


# ---------------- class files ----------------
def parse_class(data):
    count = struct.unpack_from(">H", data, 8)[0]
    cp, pos, i = [None] * count, 10, 1
    while i < count:
        tag = data[pos]
        if tag == 1:
            n = struct.unpack_from(">H", data, pos + 1)[0]
            cp[i] = (1, data[pos + 3:pos + 3 + n].decode("utf-8", "replace"))
            pos += 3 + n
        elif tag in (3, 4):
            pos += 5
        elif tag in (5, 6):
            pos += 9
            i += 1
        elif tag in (7, 8, 16, 19, 20):
            cp[i] = (tag, struct.unpack_from(">H", data, pos + 1)[0])
            pos += 3
        elif tag in (9, 10, 11, 12, 17, 18):
            cp[i] = (tag,) + struct.unpack_from(">HH", data, pos + 1)
            pos += 5
        elif tag == 15:
            pos += 4
        else:
            raise ValueError("unknown constant tag %d" % tag)
        i += 1
    utf = lambda k: cp[k][1]
    cname = lambda k: utf(cp[k][1])
    access, this_i, super_i, n_if = struct.unpack_from(">HHHH", data, pos)
    supers = ([cname(super_i)] if super_i else []) + [cname(struct.unpack_from(">H", data, pos + 8 + 2 * k)[0])
                                                     for k in range(n_if)]
    pos += 8 + 2 * n_if
    class_refs, strings = set(), []
    for e in cp:
        if e and e[0] == 7:
            class_refs.add(utf(e[1]))
        elif e and e[0] == 8:
            strings.append(utf(e[1]))
    members = []
    for kind in ("F", "M"):
        n = struct.unpack_from(">H", data, pos)[0]
        pos += 2
        for _ in range(n):
            flags, name_i, desc_i, n_attr = struct.unpack_from(">HHHH", data, pos)
            pos += 8
            lua_name = None
            for _ in range(n_attr):
                a_name, a_len = utf(struct.unpack_from(">H", data, pos)[0]), struct.unpack_from(">I", data, pos + 2)[0]
                if a_name == "RuntimeVisibleAnnotations":
                    lua_name = read_lua_name(data, pos + 6, utf) or lua_name
                pos += 6 + a_len
            members.append((kind, utf(name_i), utf(desc_i), flags, lua_name))
    return {"name": cname(this_i), "access": access, "supers": supers, "members": members,
            "class_refs": class_refs, "strings": strings}


def read_lua_name(data, pos, utf):
    """The name="..." of a @LuaMethod annotation (the name Lua uses), else None."""
    n = struct.unpack_from(">H", data, pos)[0]
    pos += 2
    found = None
    for _ in range(n):
        t, pairs = struct.unpack_from(">HH", data, pos)
        pos += 4
        is_lua = utf(t).endswith("/LuaMethod;")
        for _ in range(pairs):
            ename = utf(struct.unpack_from(">H", data, pos)[0])
            pos += 2
            val, pos = read_element(data, pos, utf)
            if is_lua and ename == "name":
                found = val
    return found


def read_element(data, pos, utf):
    tag = chr(data[pos])
    pos += 1
    if tag in "BCDFIJSZsc":
        k = struct.unpack_from(">H", data, pos)[0]
        return (utf(k) if tag in "sc" else None), pos + 2
    if tag == "e":
        return None, pos + 4
    if tag == "@":
        pos += 2
        pairs = struct.unpack_from(">H", data, pos)[0]
        pos += 2
        for _ in range(pairs):
            _, pos = read_element(data, pos + 2, utf)
        return None, pos
    if tag == "[":
        n = struct.unpack_from(">H", data, pos)[0]
        pos += 2
        for _ in range(n):
            _, pos = read_element(data, pos, utf)
        return None, pos
    raise ValueError("bad annotation tag " + tag)


def type_name(desc, i=0):
    dims = 0
    while desc[i] == "[":
        dims, i = dims + 1, i + 1
    if desc[i] == "L":
        j = desc.index(";", i)
        name, i = desc[i + 1:j].split("/")[-1].replace("$", "."), j + 1
    else:
        name, i = PRIM[desc[i]], i + 1
    return name + "[]" * dims, i


def readable(name, desc):
    if not desc.startswith("("):
        return type_name(desc)[0] + " " + name
    args, i = [], 1
    while desc[i] != ")":
        t, i = type_name(desc, i)
        args.append(t)
    return "%s %s(%s)" % (type_name(desc, i + 1)[0], name, ", ".join(args))


class Jar:
    def __init__(self, path):
        self.z = zipfile.ZipFile(path)
        self.names = [n[:-6] for n in self.z.namelist() if n.endswith(".class")]
        self.cache = {}

    def get(self, c):
        if c not in self.cache:
            try:
                self.cache[c] = parse_class(self.z.read(c + ".class"))
            except KeyError:
                self.cache[c] = None
        return self.cache[c]

    def resolve(self, name):
        """Full class names that match a simple or full name (dots or slashes)."""
        n = name.replace(".", "/")
        if n in self.names:
            return [n]
        simple = name.split(".")[-1].split("/")[-1]
        return sorted((c for c in self.names if c.split("/")[-1] == simple or c.split("/")[-1].replace("$", ".") == name or c.split("$")[-1] == simple),
                      key=lambda c: (not c.startswith("zombie/"), "$" in c, c))

    def chain(self, c):
        """The class and its PZ parent classes and interfaces, nearest first."""
        out, todo = [], [c]
        while todo:
            k = todo.pop(0)
            if k in out or self.get(k) is None:
                continue
            out.append(k)
            todo.extend(self.get(k)["supers"])
        return out

    def exposed(self):
        info = self.get("zombie/Lua/LuaManager$Exposer")
        return info["class_refs"] if info else set()


# ---------------- PZ folder and Lua ----------------
def find_pz(args):
    if "--pz" in args:
        i = args.index("--pz")
        d = args[i + 1]
        del args[i:i + 2]
        return d
    for d in ([os.environ["PZ_DIR"]] if os.environ.get("PZ_DIR") else []) + DEFAULT_DIRS:
        if os.path.exists(os.path.join(d, "projectzomboid.jar")):
            return d
    return None


def lua_files(pz):
    root = os.path.join(pz, "media", "lua")
    for r, _d, files in os.walk(root):
        for f in files:
            if f.endswith(".lua"):
                yield os.path.join(r, f)


def lua_lines(pz, sub="lua", ext=".lua"):
    root = os.path.join(pz, "media", sub)
    paths = (os.path.join(r, f) for r, _d, files in os.walk(root) for f in files if f.endswith(ext))
    for path in paths:
        with open(path, encoding="utf-8", errors="replace") as f:
            for no, line in enumerate(f, 1):
                yield os.path.relpath(path, pz), no, line.rstrip()


# ---------------- commands ----------------
def one_class(jar, name):
    found = jar.resolve(name)
    if not found:
        print("NO: no class named %s in projectzomboid.jar" % name)
        return None
    if len(found) > 1:
        print("several classes are named %s; using the first. Others: %s" % (name, ", ".join(f.replace("/", ".") for f in found[1:6])))
    return found[0]


def cmd_class(jar, pz, name):
    c = one_class(jar, name)
    if not c:
        return 1
    info = jar.get(c)
    print("YES: class %s" % c.replace("/", "."))
    print("  parent: %s" % (info["supers"][0].replace("/", ".") if info["supers"] else "-"))
    if len(info["supers"]) > 1:
        print("  interfaces: %s" % ", ".join(s.replace("/", ".") for s in info["supers"][1:]))
    exp = jar.exposed()
    via = [k for k in jar.chain(c) if k in exp]
    print("  exposed to Lua: %s" % ("yes" if c in exp else ("through parent " + via[0].replace("/", ".") if via else
                                                            "NOT in LuaManager's exposed list (Lua may not see its methods)")))
    print("  public methods: %d (see: members %s)" % (sum(1 for m in info["members"] if m[0] == "M" and m[3] & ACC_PUBLIC
                                                         and not m[1].startswith("<")), name))
    return 0


def cmd_member(jar, pz, cname, mname, kind):
    c = one_class(jar, cname)
    if not c:
        return 1
    hits = []
    for k in jar.chain(c):
        for m in jar.get(k)["members"]:
            if m[0] == kind and m[1] == mname:
                hits.append((k, m))
    if not hits:
        word = "method" if kind == "M" else "field"
        print("NO: %s has no %s named %s (parents checked: %s)" % (c.split("/")[-1], word, mname,
                                                                    (", ".join(k.split("/")[-1] for k in jar.chain(c)[1:7]) + (", ..." if len(jar.chain(c)) > 7 else "")) or "none"))
        near = sorted({m[1] for k in jar.chain(c) for m in jar.get(k)["members"]
                       if m[0] == kind and mname.lower()[:5] in m[1].lower()})[:12]
        if near:
            print("  similar names: " + ", ".join(near))
        return 1
    print("YES: %s.%s" % (c.split("/")[-1], mname))
    for k, m in hits:
        tags = ("public" if m[3] & ACC_PUBLIC else "NOT public (Lua cannot use it)") + (", static" if m[3] & ACC_STATIC else "")
        where = "" if k == c else "  (from %s)" % k.split("/")[-1].replace("$", ".")
        print("  %s   [%s]%s" % (readable(m[1], m[2]), tags, where))
    if kind == "M":
        if any(m[3] & ACC_STATIC for _k, m in hits):
            print("  Lua call (static): %s.%s(...)" % (c.split("/")[-1], mname))
        else:
            print("  Lua call: obj:%s(...)   (a colon, on an object you already have)" % mname)
    return 0


def cmd_members(jar, pz, cname, text=""):
    c = one_class(jar, cname)
    if not c:
        return 1
    seen = set()
    for k in jar.chain(c):
        for m in sorted(jar.get(k)["members"], key=lambda m: m[1]):
            if m[0] == "M" and m[3] & ACC_PUBLIC and not m[1].startswith("<") and text.lower() in m[1].lower():
                key = (m[1], m[2])
                if key not in seen:
                    seen.add(key)
                    print("  %s%s" % (readable(m[1], m[2]), "" if k == c else "   (from %s)" % k.split("/")[-1]))
    print("%d public methods%s" % (len(seen), " containing '%s'" % text if text else ""))
    return 0 if seen else 1


def cmd_find(jar, pz, mname):
    out = []
    for c in jar.names:
        if not c.startswith("zombie/"):
            continue
        info = jar.get(c)
        if info and any(m[0] == "M" and m[1] == mname and m[3] & ACC_PUBLIC for m in info["members"]):
            out.append(c.replace("/", "."))
    if not out:
        print("NO: no PZ class has a public method named %s" % mname)
        return 1
    print("YES: %d classes have %s:" % (len(out), mname))
    for c in sorted(out)[:25]:
        print("  " + c)
    if len(out) > 25:
        print("  ... and %d more" % (len(out) - 25))
    return 0


def event_names(jar):
    info = jar.get("zombie/Lua/LuaEventManager")
    return {s for s in info["strings"] if re.fullmatch(r"On[A-Z][A-Za-z0-9_]*|[A-Z][A-Za-z0-9]+", s)} if info else set()


def cmd_event(jar, pz, name):
    names = event_names(jar)
    if name not in names:
        lua_added = [(rel, no) for rel, no, line in lua_lines(pz) if 'LuaEventManager.AddEvent("%s")' % name in line]
        if lua_added:
            print("YES (added by PZ's Lua): event %s, made in %s:%d" % ((name,) + lua_added[0]))
            print("  it exists only after that file loads; if your file may load first, add the same line yourself:")
            print('  LuaEventManager.AddEvent("%s")' % name)
            return 0
        fired = [c for c in jar.names if c.startswith("zombie/") and
                 name.encode() in jar.z.read(c + ".class") and name in (jar.get(c) or {}).get("strings", [])
                 and "zombie/Lua/LuaEventManager" in jar.get(c)["class_refs"]]
        if fired:
            print("YES, BUT: PZ's Java fires %s (in %s), but it is not registered at start." % (name, fired[0].split("/")[-1]))
            print("  Events.%s is nil until PZ fires it the first time. Register it before you add a listener:" % name)
            print('  LuaEventManager.AddEvent("%s")   -- safe: returns the event if it already exists' % name)
            print("  Events.%s.Add(myFunction)" % name)
            return 0
        print("NO: %s is not an event in LuaEventManager" % name)
        near = sorted(n for n in names if name.lower().replace("on", "", 1)[:5] in n.lower())[:12]
        if near:
            print("  similar events: " + ", ".join(near))
        return 1
    print("YES: event %s" % name)
    print("  use: Events.%s.Add(myFunction)" % name)
    pat = re.compile(r"Events\.%s\.Add\(\s*([A-Za-z0-9_.:]+)" % re.escape(name))
    uses = []
    for rel, no, line in lua_lines(pz):
        m = pat.search(line)
        if m:
            uses.append((rel, no, line, m.group(1)))
    shown = len(uses)
    for rel, no, line, _f in uses[:3]:
        print("  PZ uses it: %s:%d  %s" % (rel, no, line.strip()[:110]))
    for rel, _no, _line, func in uses[:10]:
        parts = re.split(r"[.:]", func)
        dpat = def_pattern(".".join(parts[:-1]), parts[-1])
        with open(os.path.join(pz, rel), encoding="utf-8", errors="replace") as f:
            for no, line in enumerate(f, 1):
                m = dpat.search(line)
                if m:
                    print("  arguments (PZ's own listener %s, %s:%d): (%s)" % (func, rel, no, (m.group(1) or m.group(2) or "").strip()))
                    break
            else:
                continue
        break
    if not shown:
        print("  (PZ's own Lua does not use it; print the arguments once to learn them)")
    return 0


def cmd_global(jar, pz, name):
    info = jar.get("zombie/Lua/LuaManager$GlobalObject")
    hits = [m for m in info["members"] if m[0] == "M" and m[3] & ACC_PUBLIC and (m[4] or m[1]) == name and m[4]]
    if not hits:
        print("NO: %s is not a Lua global function (LuaManager.GlobalObject)" % name)
        near = sorted({m[4] for m in info["members"] if m[4] and name.lower()[:5] in m[4].lower()})[:12]
        if near:
            print("  similar globals: " + ", ".join(near))
        return 1
    print("YES: global function %s" % name)
    for m in hits:
        print("  " + readable(name, m[2]))
    return 0


def def_pattern(owner, fn):
    """Matches 'function A.b(' / 'function A:b(' / 'A.b = function(' (and plain names without an owner)."""
    full = (re.escape(owner) + r"[.:]" if owner else "") + re.escape(fn)
    return re.compile(r"^\s*(?:local\s+)?(?:function\s+%s\s*\(([^)]*)\)|%s\s*=\s*function\s*\(([^)]*)\))" % (full, full))


def cmd_lua(jar, pz, name):
    parts = re.split(r"[.:]", name)
    pat = def_pattern(".".join(parts[:-1]), parts[-1])
    hits = [(rel, no, line) for rel, no, line in lua_lines(pz) if pat.search(line)]
    if not hits:
        print("NO: %s is not defined in PZ's media/lua (as 'function %s(' or '%s = function(')" % (name, name, name))
        return 1
    print("YES: %s is defined in PZ's Lua" % name)
    for rel, no, line in hits[:5]:
        print("  %s:%d  %s" % (rel, no, line.strip()[:120]))
    return 0


def cmd_script(jar, pz, text):
    return cmd_grep(jar, pz, text, "scripts", ".txt")


def cmd_grep(jar, pz, text, sub="lua", ext=".lua"):
    n = 0
    for rel, no, line in lua_lines(pz, sub, ext):
        if text in line:
            print("  %s:%d  %s" % (rel, no, line.strip()[:120]))
            n += 1
            if n >= 20:
                print("  (first 20 shown)")
                break
    if not n:
        print("NO: no line of PZ's %s files contains %s" % (sub, text))
    return 0 if n else 1


def main(argv):
    args = list(argv)
    pz = find_pz(args)
    if len(args) < 2 or args[0] not in COMMANDS:
        print(__doc__)
        return 2
    if not pz:
        print("PZ folder not found. Pass --pz \"<folder with projectzomboid.jar>\" or set PZ_DIR.")
        return 2
    jar = Jar(os.path.join(pz, "projectzomboid.jar"))
    fn, n_args = COMMANDS[args[0]]
    if len(args) - 1 < n_args:
        print(__doc__)
        return 2
    return fn(jar, pz, *args[1:1 + n_args + (1 if args[0] == "members" and len(args) > 2 else 0)])


COMMANDS = {
    "class": (cmd_class, 1),
    "method": (lambda j, p, c, m: cmd_member(j, p, c, m, "M"), 2),
    "field": (lambda j, p, c, m: cmd_member(j, p, c, m, "F"), 2),
    "members": (cmd_members, 1),
    "find": (cmd_find, 1),
    "event": (cmd_event, 1),
    "global": (cmd_global, 1),
    "lua": (cmd_lua, 1),
    "grep": (cmd_grep, 1),
    "script": (cmd_script, 1),
}

if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    sys.exit(main(sys.argv[1:]))
