"""The brand's own 3D models: checks, reading, the library, the asset agent's picks, the logo's symbol."""

import io
import json
import re
import struct

import pytest

from kinetry import brand3d
from kinetry.branding import DEFAULT_KIT, BrandPack
from kinetry.design.plan import Beat, Design, Effects, Scene, VideoPlan2


def glb(
    name="Thing", mesh="Thing", material="Paint", color=(0.0, 0.25, 0.75, 1.0), anims=0, extra=None, pad=0
) -> bytes:
    """A real, minimal GLB: one triangle, one material, optional animations."""
    pos = struct.pack("<9f", 0, 0, 0, 2, 0, 0, 0, 1, 0)
    times = struct.pack("<2f", 0, 1)
    rots = struct.pack("<8f", 0, 0, 0, 1, 0, 0.7071, 0, 0.7071)
    binary = pos + times + rots + b"\0" * pad
    g = {
        "asset": {"version": "2.0", "generator": "test"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"name": name, "mesh": 0}],
        "meshes": [{"name": mesh, "primitives": [{"attributes": {"POSITION": 0}, "material": 0}]}],
        "materials": [{"name": material, "pbrMetallicRoughness": {"baseColorFactor": list(color)}}],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 36},
            {"buffer": 0, "byteOffset": 36, "byteLength": 8},
            {"buffer": 0, "byteOffset": 44, "byteLength": 32},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3", "min": [0, 0, 0], "max": [2, 1, 0]},
            {"bufferView": 1, "componentType": 5126, "count": 2, "type": "SCALAR", "min": [0], "max": [1]},
            {"bufferView": 2, "componentType": 5126, "count": 2, "type": "VEC4"},
        ],
    }
    if anims:
        g["animations"] = [
            {
                "name": f"Spin{i}",
                "samplers": [{"input": 1, "output": 2}],
                "channels": [{"sampler": 0, "target": {"node": 0, "path": "rotation"}}],
            }
            for i in range(anims)
        ]
    g.update(extra or {})
    js = json.dumps(g).encode()
    js += b" " * (-len(js) % 4)
    binary += b"\0" * (-len(binary) % 4)
    body = struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(binary), 0x004E4942) + binary
    return b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body


def test_a_glb_is_checked_and_read():
    f = brand3d.check_glb(glb(name="ElectricScooter", mesh="Scooter_Body", material="Brand_Blue", anims=1))
    assert f["triangles"] == 1 and f["size"] == [2.0, 1.0, 0.0]
    assert f["meshes"] == ["Scooter_Body"] and f["materials"] == ["Brand_Blue"] and f["animations"] == ["Spin0"]
    assert re.fullmatch(r"#[0-9a-f]{6}", f["colors"][0])
    for data, msg in [
        (b"PK\x03\x04" + b"\0" * 40, "not a binary glTF"),
        (glb(extra={"extensionsRequired": ["KHR_draco_mesh_compression"]}), "needs a decoder"),
        (glb(extra={"buffers": [{"byteLength": 76, "uri": "https://example.com/x.bin"}]}), "external file"),
        (glb(extra={"images": [{"uri": "tex.png"}]}), "embedded textures"),
        (glb(extra={"meshes": []}), "no meshes"),
    ]:
        with pytest.raises(brand3d.AssetError, match=msg):
            brand3d.check_glb(data)
    with pytest.raises(brand3d.AssetError, match="25 MB"):
        brand3d.check_glb(b"glTF" + b"\0" * (brand3d.MAX_GLB_BYTES + 1))


def test_the_agent_describes_a_model_from_the_names_inside_it():
    f = brand3d.check_glb(glb(name="DeliveryDrone", mesh="Drone_Propeller.001", material="Mat_Default"))
    about, tags, role = brand3d.describe("", f)
    assert tags[0] == "drone" and set(tags[1:3]) == {"delivery", "propeller"} and role == "prop"
    assert about.startswith("Drone")
    assert brand3d.describe("Acme logo", brand3d.check_glb(glb()))[2] == "logo"

    class Fake:  # a model's reading wins, but its answer is still checked
        def invoke(self, messages):
            return type("M", (), {"content": '{"about": "A drone.", "tags": ["Drone", "air!"], "role": "boss"}'})()

    about, tags, role = brand3d.describe("x", f, llm=Fake())
    assert about == "A drone." and tags == ["drone", "air"] and role == "prop"


def test_the_library_lives_in_the_brand_pack(tmp_path):
    d = tmp_path / "brand"
    BrandPack(DEFAULT_KIT.model_copy()).save(d)
    a = brand3d.add_asset(d, glb(name="Kettle", anims=2), name="Kettle")
    assert a.id == "kettle" and a.tags == ["kettle", "paint"] and a.animations == ["Spin0", "Spin1"]
    assert brand3d.add_asset(d, glb(name="Kettle", anims=2), name="Kettle").id == "kettle"  # same file, one copy
    b = brand3d.add_asset(d, glb(name="Kettle", pad=4), name="Kettle", tags=["Tea"], role="hero")
    assert b.id == "kettle-2" and b.tags == ["tea"] and b.role == "hero"
    pack = BrandPack.load(d)
    assert [x.id for x in pack.assets3d] == ["kettle", "kettle-2"] and pack.home == d
    pack.save(tmp_path / "copy")  # saving elsewhere takes the models along
    assert [x.id for x in BrandPack.load(tmp_path / "copy").assets3d] == ["kettle", "kettle-2"]
    assert brand3d.remove_asset(d, "kettle") and not brand3d.remove_asset(d, "kettle")
    assert len(list((d / "assets3d").glob("*.glb"))) == 1


def plan(*says, models="auto"):
    scenes = [Scene(type="title", data={"headline": "Hi"}, beats=[Beat(say="Welcome to the team.")])]
    scenes += [Scene(type="definition", data={"term": "x"}, beats=[Beat(say=s)]) for s in says]
    scenes.append(Scene(type="closer", data={"headline": "Bye"}, beats=[Beat(say="Thanks for watching.")]))
    return VideoPlan2(title="t", design=Design(effects=Effects(depth="subtle", depth_models=models)), scenes=scenes)


def test_the_agent_picks_models_for_scenes():
    from kinetry.design.depth import scene_models

    A = brand3d.Asset3D
    items = [
        A(id="kettle", file="a.glb", name="Kettle", tags=["kettle", "tea"]),
        A(id="mug", file="b.glb", name="Mug", tags=["mug", "coffee"]),
        A(id="press", file="d.glb", name="Coffee press", tags=["press"], role="hero"),
        A(id="logo", file="c.glb", name="Logo", role="logo"),
    ]
    p = plan("Fill the kettle first.", "Pour the tea into two mugs.", "Wipe the counter.")
    picks, spare = scene_models(p, items, {0, 4})
    assert picks[0] == ["press"] and picks[4] == ["logo"]  # products open, the logo closes
    assert picks[1] == ["kettle"] and picks[2] == ["mug", "kettle"] and 3 not in picks  # plurals match too
    assert spare == ["kettle", "mug"]
    # without a logo model, the closing scene is left to the brand's mark
    no_logo = [a for a in items if a.id != "logo"]
    assert 4 not in scene_models(p, no_logo, {0, 4}, has_mark=True)[0]
    assert scene_models(p, no_logo, {0, 4})[0][4] == ["press"]
    assert scene_models(plan("Kettle.", models="off"), items, {0}) == ({}, [])
    picked = scene_models(plan("Kettle.", models={"2": "mug", "9": "mug", "1": "nope"}), items, {0})
    assert picked == ({1: ["mug"]}, [])
    assert scene_models(p, [], {0}) == ({}, [])


def test_depth_spec_ships_the_brand_models(tmp_path):
    from kinetry.design.catalog import load_catalog
    from kinetry.design.icons import Icons
    from kinetry.design.layout import pick_layouts
    from kinetry.design.render import RenderInput, write_project
    from kinetry.timing import build_timeline, silent_clips
    from test_effects import _fake_vendor

    cat = load_catalog()
    p = pick_layouts(plan("Fill the kettle first.", "Wipe the counter."), cat)
    src = tmp_path / "k.glb"
    src.write_bytes(glb(anims=1))
    item = brand3d.Asset3D(id="kettle", file="k.glb", name="Kettle", tags=["kettle"], animations=["Spin0"])
    gsap = tmp_path / "gsap.min.js"
    gsap.write_text("")
    ri = RenderInput(
        plan=p, brand=DEFAULT_KIT, fonts={}, timeline=build_timeline(p, silent_clips(p), None), catalog=cat,
        icons=Icons(None), vendor=_fake_vendor(tmp_path), models=[(item, src)],
    )  # fmt: skip
    out = write_project(ri, tmp_path / "p", gsap)
    html = (out if out.is_file() else out / "index.html").read_text()
    spec = json.loads(re.search(r"window.TF_DEPTH = (.*?);</script>", html).group(1))
    assert spec["models"] == {"kettle": {"src": "assets/3d/kettle.glb", "role": "prop", "anims": 1}}
    assert (
        spec["scenes"][1]["models"] == ["kettle"] and spec["scenes"][2]["models"] == [] and spec["spare"] == ["kettle"]
    )
    assert (tmp_path / "p" / "assets" / "3d" / "kettle.glb").read_bytes() == src.read_bytes()


def _logo_png(symbol=True) -> bytes:
    from PIL import Image, ImageDraw

    im = Image.new("RGBA", (420, 100), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    x = 10
    if symbol:
        d.ellipse((10, 10, 90, 90), fill=(0, 64, 193, 255))
        d.ellipse((35, 35, 65, 65), fill=(0, 0, 0, 0))
        x = 130
    for k in range(5):  # a "wordmark": letters with small gaps
        d.rectangle((x + k * 55, 30, x + k * 55 + 45, 75), fill=(20, 20, 20, 255))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def test_the_symbol_is_cut_out_of_a_logo():
    pytest.importorskip("potrace")
    svg = brand3d.extract_mark(("logo.png", _logo_png()))
    assert svg and svg.startswith(b"<svg") and b"<path" in svg
    w, h = map(float, re.search(rb'viewBox="0 0 (\d+) (\d+)"', svg).groups())
    assert 0.8 < w / h < 1.25  # the round symbol, not the wordmark
    assert brand3d.extract_mark(("logo.png", _logo_png(symbol=False))) is None  # a wordmark alone has no symbol
    assert brand3d.extract_mark(None) is None


def test_http_brand_models(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from kinetry import service
    from kinetry.jobs import JobManager

    jm = JobManager(data_dir=tmp_path / "data")
    service.set_job_manager(jm)
    monkeypatch.setenv("KINETRY_API_KEY", "k")
    monkeypatch.delenv("KINETRY_LLM", raising=False)
    BrandPack(DEFAULT_KIT.model_copy()).save(tmp_path / "data" / "brands" / "b1")
    c = TestClient(service.app)
    h = {"Authorization": "Bearer k"}
    url = "/v1/brands/b1/assets3d"
    assert c.post(url, files={"file": ("x.glb", glb())}).status_code == 401
    r = c.post(url, files={"file": ("Delivery_Drone.glb", glb(name="Drone"))}, data={"role": "hero"}, headers=h)
    assert r.status_code == 200 and r.json()["id"] == "delivery-drone" and r.json()["role"] == "hero"
    assert c.post(url, files={"file": ("x.glb", b"nope")}, headers=h).status_code == 415
    assert c.post("/v1/brands/zz/assets3d", files={"file": ("x.glb", glb())}, headers=h).status_code == 404
    assert [a["id"] for a in c.get(url, headers=h).json()["assets3d"]] == ["delivery-drone"]
    assert c.get("/v1/brands/b1", headers=h).json()["assets3d"][0]["name"] == "Delivery Drone"
    assert c.delete(url + "/delivery-drone", headers=h).status_code == 200
    assert c.delete(url + "/delivery-drone", headers=h).status_code == 404
    svg = b'<svg viewBox="0 0 10 10"><path d="M0 0h10v10z"/></svg>'
    assert c.put("/v1/brands/b1/mark", files={"file": ("m.svg", svg)}, headers=h).json()["mark"] is True
    assert c.put("/v1/brands/b1/mark", files={"file": ("m.svg", b"<svg/>")}, headers=h).status_code == 400
