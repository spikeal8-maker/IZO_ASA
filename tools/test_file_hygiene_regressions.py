"""Regression cases from the independent 2026-10-17 audit.

These assertions protect file quality; they do not execute the IZO application. No expected-failure suppression.
"""
from __future__ import annotations
import json
import tempfile
import unittest
from pathlib import Path
from tools.file_hygiene import assess, category, changes
from tools.test_file_hygiene import run

RESULTS = []

class CriticalAudit(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='izo-hygiene-audit-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        run(self.root, 'init', '-q', '-b', 'main')
        run(self.root, 'config', 'user.name', 'Isolated audit')
        run(self.root, 'config', 'user.email', 'audit@example.invalid')
        self.put('architecture/contract.json', json.dumps({'source_size_policy':
                 {'normal_max_lines': 500, 'soft_max_lines': 750}}))
        self.base = self.commit()
    def put(self, path, text):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding='utf-8')
    def commit(self):
        run(self.root, 'add', '-A')
        run(self.root, 'commit', '-qm', 'audit fixture')
        return run(self.root, 'rev-parse', 'HEAD')
    def probe(self, label, expected_pass, *, base=None, head=None):
        b, h = base or self.base, head or self.commit()
        receipt = assess(self.root, b, h)
        RESULTS.append({'case': label, 'expected_pass': expected_pass,
                        'actual_pass': receipt['passed'],
                        'check_count':len(receipt['checked']),
                        'findings':receipt['findings'],
                        'git_diff': [{'status':c.status,'path':c.path,'previous':c.previous}
                                     for c in changes(self.root,b,h)]})
        self.assertEqual(receipt['passed'],expected_pass,
                         json.dumps(RESULTS[-1],ensure_ascii=False))
    def test_deleted_doc_still_linked_from_root_readme(self):
        self.put('README.md', '[Procedure](docs/procedure.md)\n')
        self.put('docs/procedure.md', '# Procedure\n')
        self.base = self.commit()
        (self.root/'docs/procedure.md').unlink()
        self.probe('Deleting a document leaves an unresolved link in unchanged root README',False)
    def test_relocated_doc_needs_links_reresolved(self):
        self.put('docs/procedure.md', '# Procedure\n[Details](details.md)\n')
        self.put('docs/details.md', '# Details\n')
        self.base = self.commit()
        (self.root/'docs/nested').mkdir()
        run(self.root,'mv','docs/procedure.md','docs/nested/procedure.md')
        self.probe('Moving a document into a subfolder breaks its unchanged relative link',False)
    def test_markdown_reference_style_link(self):
        self.put('docs/procedure.md', '[Details][details]\n\n[details]: missing.md\n')
        self.probe('A new reference-style Markdown link points to a nonexistent file',False)
    def test_anchor_points_to_absent_section(self):
        self.put('docs/details.md','# Existing heading\n')
        self.base = self.commit()
        self.put('docs/procedure.md','[Details](details.md#missing-section)\n')
        self.probe('A new link uses a nonexistent section anchor in an existing file',False)
    def test_valid_filename_with_parentheses(self):
        self.put('docs/feature(v2).md','# Details\n')
        self.put('docs/procedure.md','[Details](feature(v2).md)\n')
        self.probe('A valid inline link to a filename containing parentheses is accepted',True)
    def test_reintroducing_archived_large_document(self):
        self.put('archive/old.md','historical line\n'*1000)
        self.base = self.commit()
        (self.root/'docs').mkdir()
        run(self.root,'mv','archive/old.md','docs/new-guide.md')
        self.probe('Restoring an excluded 1000-line archive as a new active document must obey new-file limits',False)
    def test_invalid_task_manifest_should_not_authorize_size_review(self):
        self.put('tools/test_example.py','assert True\n'*501)
        self.put('tasks/INVALID.toml','[[sizeReviews]]\npath="tools/test_example.py"\nrationale="Any arbitrary description with over twenty characters."\n')
        self.probe('A schema-invalid Task Contract must not authorize an oversized new test',False)
    def test_unrelated_main_cleanup_should_not_be_attributed_to_pr(self):
        self.put('docs/legacy.md','line\n'*240)
        common=self.commit()
        run(self.root,'checkout','-qb','feature')
        self.put('docs/small.md','# Small independent update\n')
        head=self.commit()
        run(self.root,'checkout','-q','main')
        self.put('docs/legacy.md','line\n'*100)
        base=self.commit()
        self.probe('An unrelated PR does not undo an upstream cleanup, but endpoint comparison attributes it to the PR',True,base=base,head=head)
    def test_test_fixture_not_matched_by_test_prefix(self):
        # A coverage limitation: a fixture is not ordinary production source.
        self.put('backend/tests/conftest.py','# '+('x'*40000)+'\n')
        self.probe('An oversized test fixture must not escape the test byte budget merely due to its conventional filename',False)

