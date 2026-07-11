from pathlib import Path


GALLERY_DIR = Path(__file__).resolve().parent / "static" / "gallery"


def test_gallery_shell_keeps_sticky_header_and_five_mobile_tabs():
    css = (GALLERY_DIR / "gallery.css").read_text(encoding="utf-8")
    assert "overflow-x:clip" in css
    assert ".iv3.topbar-scope" in css and "position:sticky;top:0;z-index:100" in css
    assert "grid-template-columns:repeat(5,minmax(0,1fr))" in css
    assert "grid-template-columns:repeat(6,minmax(0,1fr))" not in css


def test_gallery_shell_hydrates_avatar_with_initials_fallback():
    script = (GALLERY_DIR / "gallery.js").read_text(encoding="utf-8")
    page = (GALLERY_DIR / "index.html").read_text(encoding="utf-8")
    assert "profile.avatar_url" in script
    assert "showInitials" in script
    assert "addEventListener('error'" in script
    assert "gallery-opt-phase1" in page


def test_gallery_defers_secondary_sections_and_uses_small_pages():
    script = (GALLERY_DIR / "gallery.js").read_text(encoding="utf-8")
    assert "? 12 : 24" in script
    assert "feedSectionReady" in script
    assert "uploadsSectionReady" in script
    assert "sectionObserver.observe(feedSection)" in script
    assert "feedImages = (data.feedItems || []).map(normalizeItem)" in script
    assert "userHasScrolled" in script
    assert "window.scrollY < 80" in script
    assert "/api/gallery/items?" in script
    assert "/api/gallery/secondary?" in script
    assert "loadSecondarySections" in script
    assert "appendPrimaryCards" in script
    assert "refreshImageCards" in script
    assert "removeImageCards" in script
    assert "getBoundingClientRect().height" not in script
    assert "bindMasonryImages" not in script
