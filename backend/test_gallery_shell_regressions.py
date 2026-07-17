from pathlib import Path
import re

from fastapi.testclient import TestClient

import main


GALLERY_DIR = Path(__file__).resolve().parent / "static" / "gallery"
FEED_DIR = Path(__file__).resolve().parent / "static" / "feed"
FRONTEND_SRC = Path(__file__).resolve().parent.parent / "frontend" / "src"


def test_gallery_shell_keeps_sticky_header_and_five_mobile_tabs():
    css = (GALLERY_DIR / "gallery.css").read_text(encoding="utf-8")
    assert "overflow-x:clip" in css
    assert ".iv3.topbar-scope" in css and "position:sticky;top:0;z-index:100" in css
    assert "grid-template-columns:repeat(5,minmax(0,1fr))" in css
    assert "grid-template-columns:repeat(6,minmax(0,1fr))" not in css


def test_feed_shell_uses_all_mobile_width_for_five_tabs():
    page = (FEED_DIR / "index.html").read_text(encoding="utf-8")
    assert page.count("grid-template-columns:repeat(5,minmax(0,1fr))") >= 2
    assert "grid-template-columns:repeat(6,minmax(0,1fr))" not in page


def test_gallery_shell_hydrates_avatar_with_initials_fallback():
    script = (GALLERY_DIR / "gallery.js").read_text(encoding="utf-8")
    page = (GALLERY_DIR / "index.html").read_text(encoding="utf-8")
    assert "profile.avatar_url" in script
    assert "showInitials" in script
    assert "addEventListener('error'" in script
    asset_versions = re.findall(r'/static/gallery/gallery\.(?:css|js)\?v=([^"<>]+)', page)
    assert len(asset_versions) == 2
    assert asset_versions[0] == asset_versions[1]


def test_static_shells_render_compact_token_wallet_from_account_contract():
    gallery_script = (GALLERY_DIR / "gallery.js").read_text(encoding="utf-8")
    gallery_styles = (GALLERY_DIR / "gallery.css").read_text(encoding="utf-8")
    feed_page = (FEED_DIR / "index.html").read_text(encoding="utf-8")

    for source in (gallery_script, feed_page):
        assert "daily_tokens_remaining" in source
        assert "daily_tokens_limit" in source
        assert "token_balance" in source
        assert "balance > 0" in source
        assert "top-token-values" in source

    for source in (gallery_styles, feed_page):
        assert "display:grid;align-content:center" in source
        assert ".top-token-avatar" in source


def test_generator_history_preserves_and_renders_video_media():
    contracts = (FRONTEND_SRC / "runtimeContracts.ts").read_text(encoding="utf-8")
    studio = (FRONTEND_SRC / "newUi.tsx").read_text(encoding="utf-8")

    assert "mediaType: 'image' | 'video'" in contracts
    assert "item.videoUrl || item.viewerSrc" in contracts
    assert "item.mediaType === 'video'" in studio
    assert "<video" in studio
    assert "videoUrl || item.url" in studio


def test_gallery_cards_defer_offscreen_render_and_masonry_reuses_spans():
    script = (GALLERY_DIR / "gallery.js").read_text(encoding="utf-8")
    styles = (GALLERY_DIR / "gallery.css").read_text(encoding="utf-8")
    assert 'loading="lazy" decoding="async"' in script
    assert "masonryLayoutKey" in script
    assert "if(!widthChanged && card.style.getPropertyValue('--masonry-span')) return" in script
    assert "content-visibility:auto" in styles


def test_gallery_videos_only_load_near_the_viewport():
    script = (GALLERY_DIR / "gallery.js").read_text(encoding="utf-8")
    assert "videoLoadObserver = 'IntersectionObserver' in window ? new IntersectionObserver" in script
    assert 'data-src="${escapeHtml(item.viewerSrc)}"' in script
    assert "video.src = src" in script
    assert "hydrateLazyVideos" in script


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
    assert "new AbortController()" in script
    assert "primaryRequestVersion" in script
    assert "secondaryRequestVersion" in script
    assert "err?.name === 'AbortError'" in script


def test_secondary_endpoint_skips_primary_gallery_query():
    source = (GALLERY_DIR.parent.parent / "main.py").read_text(encoding="utf-8")
    secondary_block = source.split("async def gallery_secondary", 1)[1].split("async def _gallery_page_payload", 1)[0]
    assert "secondary_only=True" in secondary_block
    assert "payload = await gallery_page" not in secondary_block


def test_gallery_http_payload_does_not_rescan_every_source_file():
    source = (GALLERY_DIR.parent.parent / "main.py").read_text(encoding="utf-8")
    payload_block = source.split("async def _gallery_page_payload", 1)[1].split("@app.get(\"/api/gallery/page\")", 1)[0]
    assert "reconcile_image_source_availability" not in payload_block


def test_gallery_and_feed_shells_expose_the_shared_favicon():
    expected = '<link rel="icon" type="image/svg+xml" href="/favicon.svg" />'
    gallery = (GALLERY_DIR / "index.html").read_text(encoding="utf-8")
    feed = (FEED_DIR / "index.html").read_text(encoding="utf-8")

    assert expected in gallery
    assert expected in feed


def test_shared_favicon_is_served_by_backend():
    response = TestClient(main.app).get("/favicon.svg")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert response.content.startswith(b"<svg")
