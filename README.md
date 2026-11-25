# pz-modding-mcp

An MCP server for **Project Zomboid Build 42 modding**. It lets an AI coding tool (Claude Code, Claude Desktop,
OpenCode, or any MCP client) check PZ names against **your installed game** instead of guessing them.

AI models often invent PZ methods and events, or remember Build 41 names. This server reads `projectzomboid.jar`
and the game's `media/` folder on your PC and answers with short YES/NO results and real signatures. Short answers
suit small local models (such as qwen3 through Ollama) as well as large ones.

- Runs locally over stdio. No network access, no telemetry.
- Read-only. It writes only to its own cache folder.
- Ships **no game files**. The indexes are built on your PC from your own install, and rebuilt after a game update.

## Tools
| Tool | What it answers | Example |
|---|---|---|
| `pz_check` | Is a class, method, field, event or global real? YES/NO with the signature | `method IsoPlayer getStats`, `event OnZombieDead`, `global getPlayer` |
| `pz_api` | A class's public methods and fields, including its parents' | `IsoPlayer`, `IsoPlayer.getStats`, `getModData` |
| `pz_items` | Items and recipes from the game's scripts, searchable | `Base.Axe`, `ItemType=base:weapon sort=MaxDamage`, `recipe RipClothing` |
| `pz_lua_search` | Where the game's own Lua (or scripts) uses some text, with file:line | `sendClientCommand(` |
| `show_lua_function` | One Lua function from your mod or from the game, not the whole file | `ISBaseTimedAction:isValid` |
| `pz_source` | Optional: decompiled Java for one method, made locally with CFR | `IsoPlayer`, `getStats` |
| `pz_status` | Setup check: the PZ folder, the index state, what is on | |
| `pz_rebuild_indexes` | Rebuild the indexes by hand (they also rebuild by themselves) | |

`pz_check` is the same checker as the `pzcheck.py` script in the pz-modding skill. The server runs it in-process
and keeps the jar loaded between calls.

## Requirements
- Python 3.10 or newer.
- Project Zomboid Build 42 installed. Tested with **42.22.2** on Windows.
- For `pz_source` only: Java (PZ's own `jre64` is used if found) and a [CFR](https://github.com/leibnitz27/cfr)
  jar that you download yourself.

## Install
```bash
git clone <this repository> pz-modding-mcp
cd pz-modding-mcp
python -m pip install .
```
Check the setup without a client:
```bash
python -m pz_modding_mcp --check
```
It prints the PZ folder it found, the index state, and which folders `show_lua_function` may read. The first tool
call builds the indexes (about 15 to 30 seconds). Later calls are fast.

## Connect a client
The server starts with `python -m pz_modding_mcp` (or the `pz-modding-mcp` command after install). Use the Python
that has the package installed. Example configs are in `config/`.

**Claude Code**
```bash
claude mcp add pz-modding -e PZ_DIR="C:/Program Files (x86)/Steam/steamapps/common/ProjectZomboid" -- python -m pz_modding_mcp
```
Or copy `config/claude-code.mcp.json` into your mod's folder as `.mcp.json`.

**Claude Desktop**: add the block from `config/claude-desktop.json` to `claude_desktop_config.json`.

**OpenCode**: add the `mcp` block from `config/opencode.json` to your `opencode.json`.

Start the client in your mod's folder, so that `show_lua_function` can read your mod's files.

## Settings (environment variables)
| Variable | Meaning | Default |
|---|---|---|
| `PZ_DIR` | the folder with `projectzomboid.jar` | the usual Steam folders on Windows, Linux and macOS |
| `PZ_MCP_CACHE` | where the indexes go | `%LOCALAPPDATA%\pz-modding-mcp`, `~/.cache/pz-modding-mcp`, `~/Library/Caches/pz-modding-mcp` |
| `PZ_MCP_WORKSPACE` | folders `show_lua_function` may read (separated by `;` on Windows, `:` elsewhere) | the folder the server starts in |
| `PZ_MCP_CFR` | path to a CFR jar. `pz_source` is off without it | not set |
| `PZ_MCP_JAVA` | Java to run CFR with | PZ's `jre64`, then `java` on PATH |

`show_lua_function` reads only files inside the workspace folders and the game's `media` folder.

## What the indexes hold
- `api.txt`: every public class, method and field under `zombie.*` in the jar (names and types only).
- `items.json`: every `item`, `craftRecipe`, `evolvedrecipe` and `fixing` block in `media/scripts`, with file:line.
  Item fields come from the item block itself; nested blocks such as `component FluidContainer` are not merged in.

They are rebuilt when the jar or the script files change.

## Game files and decompiled code
- This repository holds no Project Zomboid files, indexes or decompiled code. Do not add them.
- `pz_source` decompiles single classes on your PC, into the cache folder, so you can understand what a method
  does. Do not publish that output or copy it into a mod. Check The Indie Stone's terms before you use it.

## Tests
```bash
python -m pip install ".[test]"
python -m pytest -q
```
`tests/test_offline.py` needs no game. `tests/test_stdio.py` starts the server over stdio and calls two tools; it
is skipped when PZ is not found.

## Known limits
- Build 42 only. Build 41 jars may work for `pz_api` and `pz_check`, but this is not tested.
- `pz_api` follows parent classes, not Java interfaces. `pz_check method` covers interfaces.
- `pz_source` needs CFR. The bracket matching that cuts out one method is simple, and it may cut a method short
  when a string holds `{` or `}`.
- Linux and macOS paths are included but not tested.

## Related
The **pz-modding skill** (a `SKILL.md` with reference pages and the same `pzcheck.py`) teaches a model the Build 42
rules: mod folders, Lua load order, multiplayer commands, sandbox options and translations. This server provides the
lookups. They work well together, and each works alone.

## License
MIT. See `LICENSE`. Project Zomboid is a trademark of The Indie Stone. This project is not affiliated with them.
