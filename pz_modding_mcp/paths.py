"""Where things are: the PZ install, the index cache, the folders show_lua_function may read, and the decompiler.

Every setting is an environment variable, so any MCP client can set it in its config:
  PZ_DIR             the folder that holds projectzomboid.jar (else the default Steam folders are tried)
  PZ_MCP_CACHE       where the indexes are stored (default: a per-user cache folder)
  PZ_MCP_WORKSPACE   extra folders show_lua_function may read, separated by os.pathsep (default: the start folder)
  PZ_MCP_CFR         path to a CFR decompiler jar; pz_source is off without it
  PZ_MCP_JAVA        java to run CFR with (default: PZ's own jre64, then java on PATH)
"""
import os
import shutil
import sys

from . import pzcheck


def pz_dir():
    """The PZ folder (with projectzomboid.jar), or None."""
    return pzcheck.find_pz([])


def jar_path():
    d = pz_dir()
    return os.path.join(d, "projectzomboid.jar") if d else None


def cache_dir():
    if os.environ.get("PZ_MCP_CACHE"):
        d = os.environ["PZ_MCP_CACHE"]
    elif sys.platform == "win32":
        d = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "pz-modding-mcp")
    elif sys.platform == "darwin":
        d = os.path.expanduser("~/Library/Caches/pz-modding-mcp")
    else:
        d = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "pz-modding-mcp")
    os.makedirs(d, exist_ok=True)
    return d


def readable_roots():
    """Folders show_lua_function may read: the workspace folders and PZ's own media folder."""
    roots = [os.getcwd()]
    if os.environ.get("PZ_MCP_WORKSPACE"):
        roots = [r for r in os.environ["PZ_MCP_WORKSPACE"].split(os.pathsep) if r]
    pz = pz_dir()
    if pz:
        roots.append(os.path.join(pz, "media"))
    return [os.path.realpath(r) for r in roots]


def is_readable(path):
    real = os.path.realpath(path)
    for root in readable_roots():
        try:
            if os.path.commonpath([real, root]) == root:
                return True
        except ValueError:          # another drive on Windows
            continue
    return False


def cfr_jar():
    p = os.environ.get("PZ_MCP_CFR", "")
    return p if p and os.path.isfile(p) else None


def java_exe():
    if os.environ.get("PZ_MCP_JAVA") and os.path.isfile(os.environ["PZ_MCP_JAVA"]):
        return os.environ["PZ_MCP_JAVA"]
    pz = pz_dir()
    if pz:
        for name in ("java.exe", "java"):
            p = os.path.join(pz, "jre64", "bin", name)
            if os.path.isfile(p):
                return p
    return shutil.which("java")
