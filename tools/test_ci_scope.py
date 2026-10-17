"""Routing must not discard application coverage or start it for prose-only work."""
from __future__ import annotations

import unittest
from pathlib import Path

from tools.ci_scope import TOOLING_INSTALL_STEP, application_body, route
from tools.test_file_hygiene import RepositoryCase, run


class CiScopeTests(RepositoryCase, unittest.TestCase):
    def result(self):
        return route(self.root, self.base, self.commit())

    def test_docs_only_and_portable_tools_do_not_require_windows(self):
        self.put('docs/topic.md', '# Topic\n')
        self.put('tools/file_hygiene.py', '# bounded tool change\n')
        self.assertFalse(self.result()['applicationRequired'])

    def test_product_unknown_and_dependency_paths_require_windows(self):
        for path in ('backend/app/new.py', 'frontend/src/app.tsx', '.python-version',
                     'backend/requirements.txt', 'unclassified/config.json'):
            with self.subTest(path=path):
                self.put(path, 'changed\n')
                self.assertIn(path, self.result()['applicationPaths'])

    def test_product_rename_into_documentation_is_not_exempt(self):
        self.put('backend/app/live.py', 'print(1)\n')
        self.base = self.commit()
        (self.root / 'docs').mkdir()
        run(self.root, 'mv', 'backend/app/live.py', 'docs/live.md')
        self.assertTrue(self.result()['applicationRequired'])

    def test_workflow_routing_only_preserves_original_steps(self):
        path = '.github/workflows/ci.yml'
        self.put(path, 'jobs:\n  verify:\n    steps:\n      - run: original\n')
        self.base = self.commit()
        self.put(path, 'jobs:\n  quality: reusable\n  verify:\n    steps:\n      - run: original\n')
        self.assertFalse(self.result()['applicationRequired'])
        self.put(path, 'jobs:\n  verify:\n    steps:\n      - run: different\n')
        self.assertTrue(self.result()['applicationRequired'])

    def test_only_exact_tooling_install_is_portable(self):
        path = '.github/workflows/ci.yml'
        old = 'jobs:\n  verify:\n    steps:\n      - run: original\n'
        self.put(path, old)
        self.base = self.commit()
        added = old.replace('      - run: original', TOOLING_INSTALL_STEP + '      - run: original')
        self.put(path, added)
        self.assertFalse(self.result()['applicationRequired'])
        self.put(path, added.replace('--require-hashes', '--no-deps'))
        self.assertTrue(self.result()['applicationRequired'])
        self.assertIsNone(application_body(TOOLING_INSTALL_STEP * 2 + old))

    def test_deleting_or_creating_ci_is_not_exempt(self):
        path = '.github/workflows/ci.yml'
        self.put(path, 'jobs: {}\n')
        self.assertTrue(self.result()['applicationRequired'])
        self.base = self.commit_after_new_change()
        (self.root / path).unlink()
        self.assertTrue(self.result()['applicationRequired'])

    def commit_after_new_change(self):
        self.put('docs/marker.md', 'marker\n')
        return self.commit()

    def test_unavailable_or_short_revision_fails(self):
        with self.assertRaises(ValueError):
            route(self.root, 'HEAD^', self.base)
        with self.assertRaises(ValueError):
            route(self.root, 'f' * 40, self.base)

    def test_route_follows_same_merge_base_as_checker(self):
        self.put('docs/base.md', '# base\n')
        split = self.commit()
        self.put('backend/app/main_only.py', '# other author\n')
        advanced = self.commit()
        run(self.root, 'checkout', '-qb', 'candidate', split)
        self.put('docs/change.md', '# own change\n')
        candidate = self.commit()
        selected = route(self.root, advanced, candidate)
        self.assertEqual(selected['base'], split)
        self.assertFalse(selected['applicationRequired'])
        self.assertTrue(route(self.root, advanced, candidate, 'direct')['applicationRequired'])

    def test_reusable_workflow_requires_success_and_preserves_failures(self):
        root = Path(__file__).resolve().parents[1]
        ci = (root / '.github/workflows/ci.yml').read_text()
        portable = (root / '.github/workflows/file-hygiene.yml').read_text()
        self.assertIn('uses: ./.github/workflows/file-hygiene.yml', ci)
        self.assertIn('needs: quality', ci)
        self.assertIn("needs.quality.outputs.application_required == 'true'", ci)
        self.assertNotIn('always()', ci.split('    steps:\n', 1)[0])
        self.assertIn('workflow_call:', portable)
        self.assertNotIn('  pull_request:', portable)
        self.assertNotIn('  push:', portable)
        self.assertIn('defaults:\n  run:\n    shell: bash', portable)
        self.assertIn('--require-hashes', portable)
        self.assertNotIn('[skip ci]', ci + portable)


if __name__ == '__main__':
    unittest.main()
