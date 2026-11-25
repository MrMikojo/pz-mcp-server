"""Tests that need no PZ install: the script parser, the Java index loader, and the path guard."""
import os

from pz_modding_mcp import indexes, paths, tools

SCRIPT = """module MyMod
{
    imports { Base, }

    item Canteen
    {
        DisplayCategory = Water,
        ItemType = base:normal,   /* a comment */
        Weight = 0.5,
        component FluidContainer
        {
            Capacity = 1.0,
        }
        Icon = Canteen,
    }

    item Gadget {
        Weight = 0.2,
    }

    craftRecipe MakeGadget
    {
        time = 40,
        inputs
        {
            item 1 Base.Nails,
        }
    }
}
"""


def test_script_parser_keeps_nested_fields_out():
    items, recipes = [], []
    indexes.parse_scripts(SCRIPT, "media/scripts/x.txt", items, recipes)
    by = {i["id"]: i for i in items}
    assert set(by) == {"MyMod.Canteen", "MyMod.Gadget"}
    assert by["MyMod.Canteen"]["f"] == {"DisplayCategory": "Water", "ItemType": "base:normal", "Weight": "0.5",
                                         "Icon": "Canteen"}
    assert by["MyMod.Gadget"]["f"] == {"Weight": "0.2"}
    assert by["MyMod.Canteen"]["where"] == "media/scripts/x.txt:5"
    assert [r["name"] for r in recipes] == ["MakeGadget"]
    assert "Base.Nails" in recipes[0]["text"]


def test_method_sig():
    assert indexes.method_sig("(Ljava/lang/String;I[F)Z") == ("String, int, float[]", "boolean")
    assert indexes.method_sig("()Lzombie/characters/Stats;") == ("", "zombie.characters.Stats")


API = """class zombie.A
zombie.A.getX() -> float
zombie.A.name: String
class zombie.B extends zombie.A
zombie.B.getY() -> float
class zombie.other.B
zombie.other.B.size() -> int
"""


def test_api_lookups(tmp_path, monkeypatch):
    p = tmp_path / "api.txt"
    p.write_text(API, encoding="utf-8")
    api = indexes.load_api(str(p))
    monkeypatch.setattr(tools.IDX, "api", lambda: api)
    monkeypatch.setattr(paths, "pz_dir", lambda: str(tmp_path))
    out = tools.pz_api("zombie.B.getX")
    assert "inherited from zombie.A" in out and "getX()" in out
    assert "2 classes are named B" in tools.pz_api("B")
    assert "size()" in tools.pz_api("B.size")                 # found on the second class named B
    assert tools.pz_api("A.nothing").startswith("NO")
    assert "zombie.A.name: String" in tools.pz_api("name")


def test_path_guard(tmp_path, monkeypatch):
    monkeypatch.setenv("PZ_MCP_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(paths, "pz_dir", lambda: None)
    inside = tmp_path / "mod.lua"
    inside.write_text("x", encoding="utf-8")
    assert paths.is_readable(str(inside))
    assert not paths.is_readable(os.path.join(str(tmp_path), "..", "elsewhere.lua"))


def test_show_lua_function(tmp_path, monkeypatch):
    monkeypatch.setenv("PZ_MCP_WORKSPACE", str(tmp_path))
    monkeypatch.setattr(paths, "pz_dir", lambda: str(tmp_path))
    (tmp_path / "mod.lua").write_text("-- adds one\nfunction MyMod.add(a)\n    return a + 1\nend\n\n"
                                      "local function other()\nend\n", encoding="utf-8")
    out = tools.show_lua_function("mod.lua", "MyMod.add")
    assert "1: -- adds one" in out and "4: end" in out and "other" not in out
    assert "not defined" in tools.show_lua_function("mod.lua", "MyMod.nope")


def test_java_member_matcher():
    m = tools._MEMBER.match
    assert m("    public Stats getStats() {")
    assert m("        private static void helper(int a) {")
    assert m("    public <T> List<T> all(Class<T> c) {")
    assert not m("        else if (getStats() != null) {")
    assert not m("        return getStats();")
