"""LMS packages: captions, chapters, transcript, grounded quiz, SCORM manifests. No model, no browser."""

import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile

import pytest

from kinetry.package import Quiz, QuizQuestion, build_package, captions_vtt, chapters_vtt, grounded, transcript_text

SOURCE = """Give feedback that helps. A good comment has three parts: what you saw, the effect it had, and one next step.
Describe a concrete moment of the work, not a judgment about the person. Before you send it, check that it is concrete."""


def timing():
    return {
        "version": 1,
        "title": "Feedback that helps",
        "lang": "en",
        "format": "16:9",
        "duration": 12.0,
        "scenes": [
            {
                "index": 0,
                "type": "title",
                "label": "Start",
                "start": 0.0,
                "end": 5.0,
                "beats": [
                    {
                        "start": 0.8,
                        "end": 4.2,
                        "say": "Give feedback that helps.",
                        "caption": "Give feedback that helps.",
                        "voice": "narrator",
                        "speaker": "",
                    }
                ],
            },
            {
                "index": 1,
                "type": "dialogue",
                "label": "Example",
                "start": 5.0,
                "end": 12.0,
                "beats": [
                    {
                        "start": 5.4,
                        "end": 8.0,
                        "say": "Can I give you a note?",
                        "caption": "Can I give you a note?",
                        "voice": "a",
                        "speaker": "Mateo",
                    },
                    {
                        "start": 8.3,
                        "end": 11.0,
                        "say": "Sure, go ahead.",
                        "caption": "Sure, go ahead.",
                        "voice": "b",
                        "speaker": "Lucía",
                    },
                ],
            },
        ],
        "cues": [
            {
                "id": "cap1-1-1",
                "start": 0.8,
                "end": 4.32,
                "text": "Give feedback that helps.",
                "scene": 0,
                "beat": 0,
                "voice": "narrator",
            },
            {
                "id": "cap2-1-1",
                "start": 5.4,
                "end": 8.12,
                "text": "Can I give you a note?",
                "scene": 1,
                "beat": 0,
                "voice": "a",
            },
            {
                "id": "cap2-2-1",
                "start": 8.3,
                "end": 11.12,
                "text": "Sure, go ahead.",
                "scene": 1,
                "beat": 1,
                "voice": "b",
            },
        ],
    }


def quiz(quote="A good comment has three parts: what you saw, the effect it had"):
    return Quiz(
        questions=[
            QuizQuestion(
                question="How many parts does a good comment have?",
                options=["Two", "Three", "Five"],
                answer=1,
                why="What you saw, its effect, and a next step.",
                quote=quote,
            ),
        ]
    )


@pytest.fixture
def run(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg needed to make a tiny test video")
    rd = tmp_path / "run"
    rd.mkdir()
    vid = rd / "video.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=320x180:d=2", "-pix_fmt", "yuv420p", str(vid)],
        check=True,
    )
    (rd / "timing.json").write_text(json.dumps(timing()))
    (rd / "report.json").write_text(
        json.dumps(
            {"video": str(vid), "brand": {"accent": "#2e5bff", "background": "#ffffff", "accent_ink": "#ffffff"}}
        )
    )
    (rd / "source.md").write_text(SOURCE)
    return rd


def test_captions_name_dialogue_speakers():
    vtt = captions_vtt(timing())
    assert vtt.startswith("WEBVTT")
    assert "00:00:00.800 --> 00:00:04.320" in vtt
    assert "<v Mateo>Can I give you a note?" in vtt and "<v Lucía>Sure, go ahead." in vtt
    assert "\nGive feedback that helps.\n" in vtt  # the narrator is not tagged


def test_chapters_and_transcript():
    ch = chapters_vtt(timing())
    assert "00:00:05.000 --> 00:00:12.000\nExample" in ch
    tr = transcript_text(timing())
    assert "[0:05] Example" in tr and "Mateo: Can I give you a note?" in tr


def test_quiz_quote_must_be_in_the_source():
    kept, notes = grounded(quiz(), SOURCE)
    assert kept and len(kept.questions) == 1
    q = kept.questions[0]
    assert q.options[q.answer] == "Three"  # options may rotate; the answer follows
    dropped, notes = grounded(quiz(quote="Feedback should always be given in writing within a day"), SOURCE)
    assert dropped is None and "quote not found" in notes[0]


def test_quiz_with_duplicate_options_is_dropped():
    bad = Quiz(
        questions=[
            QuizQuestion(
                question="Q?",
                options=["A", "a", "B"],
                answer=0,
                why="w",
                quote="what you saw, the effect it had, and one next step",
            )
        ]
    )
    assert grounded(bad, SOURCE)[0] is None


@pytest.mark.parametrize("standard", ["scorm12", "scorm2004", "web"])
def test_package_layout(run, tmp_path, standard):
    pkg = build_package(run, tmp_path / f"{standard}.zip", standard=standard, quiz=quiz())
    assert pkg.questions == 1
    z = zipfile.ZipFile(pkg.path)
    names = set(z.namelist())
    for f in (
        "index.html",
        "player.js",
        "player.css",
        "lms.js",
        "lesson.js",
        "media/video.mp4",
        "media/captions.vtt",
        "media/chapters.vtt",
        "media/transcript.txt",
    ):
        assert f in names, f
    assert z.getinfo("media/video.mp4").compress_type == zipfile.ZIP_STORED
    lesson = json.loads(z.read("lesson.js").decode().split("=", 1)[1].rstrip().rstrip(";"))
    assert lesson["standard"] == standard and lesson["mastery"] == 0.8
    assert "quote" not in lesson["quiz"][0]  # the grounding quote isn't shipped to learners
    assert lesson["scenes"][1]["label"] == "Example"
    if standard == "web":
        assert "imsmanifest.xml" not in names
        return
    root = ET.fromstring(z.read("imsmanifest.xml"))
    ns = {"m": root.tag.split("}")[0][1:]}
    res = root.find(".//m:resource", ns)
    assert res.get("href") == "index.html"
    listed = {f.get("href") for f in res.findall("m:file", ns)}
    assert {"index.html", "media/video.mp4", "lms.js"} <= listed
    xml = z.read("imsmanifest.xml").decode()
    if standard == "scorm12":
        assert "<schemaversion>1.2</schemaversion>" in xml and "<adlcp:masteryscore>80</adlcp:masteryscore>" in xml
    else:
        assert "2004 4th Edition" in xml and "<imsss:minNormalizedMeasure>0.80</imsss:minNormalizedMeasure>" in xml


def test_package_without_quiz(run, tmp_path):
    pkg = build_package(run, tmp_path / "p.zip", quiz=False)
    z = zipfile.ZipFile(pkg.path)
    assert pkg.questions == 0
    assert "masteryscore" not in z.read("imsmanifest.xml").decode()
    lesson = json.loads(z.read("lesson.js").decode().split("=", 1)[1].rstrip().rstrip(";"))
    assert lesson["quiz"] == [] and lesson["mastery"] is None


def test_quiz_without_a_model_is_left_out_with_a_note(run, tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("no model configured")

    monkeypatch.setattr("kinetry.package.make_quiz", boom)
    pkg = build_package(run, tmp_path / "p.zip", quiz=True)
    assert pkg.questions == 0 and "no knowledge check" in pkg.notes[0]


def test_lesson_json_cannot_close_the_script_tag(run, tmp_path):
    t = timing()
    t["scenes"][0]["label"] = "</script><b>x"
    (run / "timing.json").write_text(json.dumps(t))
    z = zipfile.ZipFile(build_package(run, tmp_path / "p.zip", quiz=False).path)
    assert "</script>" not in z.read("lesson.js").decode()


def test_rtl_and_strings_follow_the_language(run, tmp_path):
    t = timing()
    t["lang"] = "ar"
    (run / "timing.json").write_text(json.dumps(t))
    z = zipfile.ZipFile(build_package(run, tmp_path / "p.zip", quiz=False).path)
    assert 'dir="rtl"' in z.read("index.html").decode()
    lesson = json.loads(z.read("lesson.js").decode().split("=", 1)[1].rstrip().rstrip(";"))
    assert lesson["ui"]["chapters"] == "الفصول"


def test_missing_timing_is_a_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="timing.json"):
        build_package(tmp_path, tmp_path / "x.zip")


# ---------------------------------------------------------------- over HTTP
def test_http_package_option(tmp_path, monkeypatch):
    import time

    from fastapi.testclient import TestClient

    from kinetry import service
    from kinetry.jobs import JobManager
    from kinetry.package import Package
    from test_integration import PLAN, FakeKinetry

    class Packs(FakeKinetry):
        def package(self, run, *, out, standard, quiz, questions, mastery, llm=None, **kw):
            self.calls.append({"package": standard, "quiz": quiz, "questions": questions, "mastery": mastery})
            out.write_bytes(b"PK-zip")
            return Package(out, standard, questions if quiz else 0, [])

    jm = JobManager(Packs(tmp_path), data_dir=tmp_path / "data", allow_private_urls=True)
    service.set_job_manager(jm)
    monkeypatch.delenv("KINETRY_API_KEY", raising=False)
    c = TestClient(service.app)
    assert c.post("/v1/videos", json={"plan": PLAN, "package": {"standard": "scorm3"}}).status_code == 400
    assert c.post("/v1/videos", json={"plan": PLAN, "package": {"quiz": 9}}).status_code == 400
    r = c.post("/v1/videos", json={"plan": PLAN, "package": {"standard": "scorm2004", "quiz": 2}})
    assert r.status_code == 202
    jid = r.json()["job_id"]
    for _ in range(100):
        st = c.get(f"/v1/videos/{jid}").json()
        if st["status"] == "done":
            break
        time.sleep(0.05)
    assert st["package_url"].endswith("/package") and "file" not in st["package"]
    assert st["package"]["questions"] == 2 and st["package"]["standard"] == "scorm2004"
    assert c.get(st["package_url"]).content == b"PK-zip"
    assert jm.tf.calls[-1] == {"package": "scorm2004", "quiz": True, "questions": 2, "mastery": 80}


def test_burned_in_captions_are_not_shown_twice(run, tmp_path):
    from kinetry.package import poster_time

    t = timing()
    assert poster_time(t) == 3.0  # no burned captions: a few seconds in
    html = zipfile.ZipFile(build_package(run, tmp_path / "a.zip", quiz=False).path).read("index.html").decode()
    assert 'label="Captions" default' in html
    t["burned_captions"] = True
    assert poster_time(t) == 4.62  # just after the first line ends, before the next one
    (run / "timing.json").write_text(json.dumps(t))
    html = zipfile.ZipFile(build_package(run, tmp_path / "b.zip", quiz=False).path).read("index.html").decode()
    assert 'label="Captions">' in html and "default>" not in html
