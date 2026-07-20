"""Re-apply BrowserTestClient changes to test files, preserving UTF-8 encoding."""
import re
from pathlib import Path

BACKEND = Path(r"C:\IZO_ASA\releases\85051df1a54f510d63fa60323da0211190cf3c6b\backend")

IMPORT_LINE = "from test_support.browser_client import BrowserTestClient\n"
TESTCLIENT_IMPORT = "from fastapi.testclient import TestClient\n"

files_with_browser_origin = {
    "test_admin_v2.py",
    "test_cookie_session.py",
}


def process_file(filepath: Path) -> bool:
    """Add BrowserTestClient import and replace TestClient(main.app)."""
    original = filepath.read_text("utf-8")
    content = original

    # Add import after TestClient import
    if IMPORT_LINE not in content and TESTCLIENT_IMPORT in content:
        content = content.replace(
            TESTCLIENT_IMPORT,
            TESTCLIENT_IMPORT + IMPORT_LINE,
        )

    # Replace TestClient(main.app) -> BrowserTestClient(main.app)
    content = content.replace(
        "TestClient(main.app)",
        "BrowserTestClient(main.app)",
    )

    # For files that had manual BROWSER_ORIGIN, remove redundant headers
    if filepath.name in files_with_browser_origin:
        # Remove lines that pass headers=BROWSER_ORIGIN (with optional trailing comma)
        content = re.sub(
            r",?\s*headers\s*=\s*BROWSER_ORIGIN\s*,?\s*",
            "",
            content,
        )

    if content != original:
        filepath.write_text(content, "utf-8")
        return True
    return False


def main():
    test_files = sorted(BACKEND.glob("test_*.py"))
    modified = 0
    for fp in test_files:
        if fp.name == "test_browser_client.py" or fp.name == "test_csrf_origin.py":
            continue
        if process_file(fp):
            modified += 1
            print(f"  MODIFIED: {fp.name}")
    print(f"\nTotal modified: {modified}")


if __name__ == "__main__":
    main()
