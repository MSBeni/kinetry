"""Output quality presets reach `hyperframes render`; bad values fail before any work starts."""

import json
from pathlib import Path

import pytest

import kinetry.graph as g
import kinetry.hf as hf
from kinetry import Kinetry
from kinetry.jobs import JobManager
from kinetry.voice import Clip

FEEDBACK = json.loads((Path(__file__).parent.parent / "examples" / "plans" / "feedback-that-lands.json").read_text())


def test_presets_and_crf_numbers():
    assert hf.quality_args(None) == hf.quality_args("standard") == ["--crf", str(hf.STANDARD_CRF)]
    assert hf.quality_args("high") == []  # HyperFrames' own default, unchanged output
    assert hf.quality_args("DRAFT") == ["--quality", "draft"]
    assert hf.quality_args(20) == hf.quality_args("20") == ["--crf", "20"]
    for bad in ("ultra", 52, -1, "crf20"):
        with pytest.raises(ValueError):
            hf.quality_args(bad)


def test_render_command_line(monkeypatch, tmp_path):
    seen = []

    class R:
        returncode, stdout, stderr = 0, "", ""

    def run(settings, args, cwd, timeout):
        seen.append(args)
        Path(args[args.index("--output") + 1]).write_bytes(b"mp4")
        return R()

    monkeypatch.setattr(hf, "_run", run)
    s = hf.Settings()
    hf.render(tmp_path, tmp_path / "a.mp4", s, quality="high")
    hf.render(tmp_path, tmp_path / "b.mp4", s, quality=26)
    s.quality = "draft"
    hf.render(tmp_path, tmp_path / "c.mp4", s)  # the settings default applies when the call doesn't say
    assert "--crf" not in seen[0] and seen[1][seen[1].index("--crf") + 1] == "26"
    assert seen[2][seen[2].index("--quality") + 1] == "draft"


def test_pipeline_passes_quality_and_logs_size(tmp_path, monkeypatch):
    got = []

    class HF:
        check = staticmethod(lambda *a: {"ok": True, "errors": []})
        snapshot = staticmethod(lambda *a: [])

        @staticmethod
        def render(project, out, settings, quality=None):
            got.append(quality)
            Path(out).write_bytes(b"x" * 2_500_000)
            return Path(out)

    monkeypatch.setattr(
        g, "voice_plan", lambda plan, voices, d: [[Clip(None, 2.0) for _ in s.beats] for s in plan.scenes]
    )
    monkeypatch.setattr(g, "compose_project", lambda *a, **k: None)
    monkeypatch.setattr(g, "measure", lambda *a, **k: {"fields": [], "stages": []})
    monkeypatch.setattr(g, "hf", HF)
    tf = Kinetry(workdir=tmp_path)
    res = tf.render(FEEDBACK, out=tmp_path / "v.mp4", quality="high")
    assert res.status == "done" and got == ["high"]
    step = next(e for e in res.log if e["step"] == "render")
    assert step["quality"] == "high" and step["mb"] == 2.5
    tf.render(FEEDBACK, out=tmp_path / "w.mp4")
    assert got[-1] == "standard"  # Settings default
    with pytest.raises(ValueError):
        tf.render(FEEDBACK, out=tmp_path / "x.mp4", quality="best")


def test_service_rejects_bad_quality(tmp_path):
    with pytest.raises(ValueError, match="quality"):
        JobManager(data_dir=tmp_path).start(plan=FEEDBACK, quality="best")
