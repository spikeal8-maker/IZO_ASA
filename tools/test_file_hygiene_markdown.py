"""Reference syntax and target-regression cases; all data is temporary."""
import unittest

from tools.file_hygiene import assess
from tools.file_hygiene_markdown import parse
from tools.test_file_hygiene import RepositoryCase, run


class MarkdownCases(RepositoryCase, unittest.TestCase):
    def test_cyrillic_duplicates_and_explicit_html_anchors(self):
        self.put("docs/target.md", '# Пример **текста**\n# Пример **текста**\n<a id="custom"></a>\n')
        self.put("docs/read.md", '[a](target.md#пример-текста) [b](target.md#пример-текста-1) [c](target.md#custom)\n')
        self.assertTrue(self.assess()["passed"])

    def test_removed_heading_breaks_unchanged_incoming_link(self):
        self.put("docs/target.md", "# Kept\n# Removed\n")
        self.put("README.md", "[a](docs/target.md#removed)\n")
        self.base = self.commit()
        self.put("docs/target.md", "# Kept\n")
        self.assertEqual(self.assess()["findings"][0]["code"], "BROKEN_LOCAL_ANCHOR")

    def test_code_path_survives_root_relative_resolution(self):
        self.put("docs/a.md", "Read `docs/target.md`.\n")
        self.put("docs/target.md", "# Target\n")
        self.assertTrue(self.assess()["passed"])
        self.base = run(self.root, "rev-parse", "HEAD")
        (self.root / "docs/target.md").unlink()
        self.assertFalse(self.assess()["passed"])

    def test_code_example_and_remote_url_are_not_local_files(self):
        self.put("docs/a.md", "```python\n[x](missing.md)\n```\n[remote](https://example.invalid/file.md#other)\n")
        self.assertTrue(self.assess()["passed"])

    def test_reference_style_and_nested_image(self):
        self.put("docs/image.png", "temporary image marker")
        self.put("docs/a.md", "[![alt](image.png)][target]\n\n[target]: missing.md\n")
        self.assertFalse(self.assess()["passed"])
        self.put("docs/missing.md", "# Created\n")
        self.assertTrue(self.assess()["passed"])

    def test_renamed_old_link_debt_is_not_new_location_authority(self):
        self.put("docs/a.md", "[broken](absent.md)\n")
        self.base = self.commit()
        self.put("docs/a.md", "[broken](absent.md)\nClarification.\n")
        result = self.assess()
        self.assertTrue(result["passed"])
        self.assertEqual(result["historicalReferenceDebt"], 1)

    def test_active_pointer_in_ops_is_checked(self):
        self.put("ops/README.md", "[procedure](../docs/procedure.md)\n")
        self.put("docs/procedure.md", "# Procedure\n")
        self.base = self.commit()
        (self.root / "docs/procedure.md").unlink()
        self.assertFalse(self.assess()["passed"])

    def test_absolute_repo_path_and_filename_with_spaces(self):
        self.put("docs/my guide.md", "# Guide\n")
        self.put("README.md", "[a](/docs/my%20guide.md) [b](<docs/my guide.md>)\n")
        self.assertTrue(self.assess()["passed"])

    def test_html_href_checked_but_fenced_html_not_executed(self):
        self.put("docs/a.md", '<a href="missing.md">link</a>\n')
        self.assertFalse(self.assess()["passed"])
        self.put("docs/a.md", '```html\n<a href="missing.md">link</a>\n```\n')
        self.assertTrue(self.assess()["passed"])

    def test_frontmatter_does_not_create_fake_heading(self):
        _, ids = parse("---\nstatus: active\n---\n# Real\n")
        self.assertEqual(ids, {"real"})

    def test_path_traversal_is_rejected_without_reading_host(self):
        self.put("docs/a.md", "[x](../../etc/passwd)\n")
        self.assertFalse(self.assess()["passed"])

    def test_branch_comparison_mode_is_explicit(self):
        self.put("docs/old.md", "line\n" * 240)
        common = self.commit()
        primary = run(self.root, "branch", "--show-current")
        run(self.root, "checkout", "-qb", "feature")
        self.put("docs/new.md", "# New\n")
        head = self.commit()
        run(self.root, "checkout", "-q", primary)
        self.put("docs/old.md", "line\n" * 100)
        base = self.commit()
        result = assess(self.root, base, head)
        self.assertEqual(result["base"], common)
        self.assertEqual(result["requestedBase"], base)
        self.assertTrue(result["passed"])
        self.assertFalse(assess(self.root, base, head, comparison="direct")["passed"])
