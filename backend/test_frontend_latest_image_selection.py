from pathlib import Path


FRONTEND_SRC = Path(__file__).parents[1] / "frontend" / "src"


def test_last_image_actions_skip_video_gallery_items() -> None:
    source = (FRONTEND_SRC / "newUi.tsx").read_text(encoding="utf-8")

    assert source.count("gallery.find((item) => item.mediaType === 'image')") >= 2
    assert source.count("historyItems.find((item) => item.mediaType === 'image')") >= 2
    assert "dockImage?.mediaType === 'image' ? dockImage : undefined" in source
    assert "visibleResultUrl || gallery[0]?.url || dockImage?.url || historyItems[0]?.url" not in source


def test_outpaint_prompt_forbids_subject_duplication() -> None:
    source = (FRONTEND_SRC / "studio" / "studioImageProcessing.ts").read_text(encoding="utf-8")

    assert "Treat the unmasked source as fixed." in source
    assert "Do not copy, repeat, mirror, move or recreate any existing subject or object" in source
