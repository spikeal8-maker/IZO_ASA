"""Keep the repaired instructions, reusable workflow and Docker profiles coherent."""
from __future__ import annotations

import inspect
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SourceAlignmentTests(unittest.TestCase):
    def read(self, path: str) -> str:
        return (ROOT / path).read_text(encoding='utf-8')

    def test_existing_agent_instruction_contracts(self):
        # Reuse, do not weaken or replace, the full repository's existing contract.
        from tools.test_agent_instructions import assert_agent_instruction_contracts
        assert_agent_instruction_contracts()

    def test_existing_windows_ci_contracts(self):
        from tools import test_ci_workflow
        tests = [(name, fn) for name, fn in vars(test_ci_workflow).items()
                 if name.startswith('test_') and inspect.isfunction(fn)]
        self.assertGreaterEqual(len(tests), 10)
        for name, fn in tests:
            with self.subTest(name=name):
                self.assertEqual(len(inspect.signature(fn).parameters), 0)
                fn()

    def test_documented_toml_passes_the_canonical_parser(self):
        from tools.agent_system.package import parse_manifest
        text = self.read('docs/task-contract-guide.md')
        examples = re.findall(r'```toml\n(.*?)\n```', text, re.S)
        self.assertEqual(len(examples), 1)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'tasks' / 'DOC-EXAMPLE-001.toml'
            path.parent.mkdir()
            path.write_text(examples[0], encoding='utf-8')
            manifest = parse_manifest(path)
            self.assertEqual(manifest.id, 'DOC-EXAMPLE-001')
            self.assertEqual(manifest.risk_class, 'low')
        start = self.read('AI_START_HERE.md')
        self.assertNotIn('```yaml', start)
        self.assertIn('docs/task-contract-guide.md', start)

    def test_current_status_does_not_claim_unperformed_docker_acceptance(self):
        now = self.read('docs/NOW.md')
        fields = dict(line.split(':', 1) for line in now.split('---', 2)[1].splitlines() if ':' in line)
        for key in ('source_main_at_status_update', 'last_verified_main', 'production_release_sha', 'candidate_source_sha'):
            self.assertRegex(fields[key].strip(), r'^[0-9a-f]{40}$')
        self.assertRegex(fields['candidate_pr'].strip(), r'^\d+$')
        self.assertNotIn('implementation NOT STARTED', now)
        self.assertIn('last_verified_main', now)
        overview = self.read('docs/system-overview.md')
        self.assertNotIn(' → ', overview.split('## Как найти правильный документ', 1)[1])
        payments = self.read('docs/payments-public-pages-20260715.md')
        self.assertNotIn('`billing-readiness-20260716.md`', payments)
        self.assertIn('(context/billing-payments.md)', payments)

    def test_docker_profiles_preserve_all_acceptance_cases(self):
        text = self.read('docs/docker-delivery-acceptance.md')
        expected = [f'Д{stage}-{number:02d}' for stage, count in ((0, 2), (1, 8), (2, 6), (3, 4), (4, 4))
                    for number in range(1, count + 1)]
        self.assertEqual(re.findall(r'^\| (Д[0-4]-\d{2}) \|', text, re.M), expected)
        self.assertIn('(docker-environments.md)', text)
        self.assertIn('production_change_authorized: false', text)
        profile = self.read('docs/docker-environments.md')
        for value in ('isoas', 'izo-asa-shadow-', 'io.izo.', 'io.isoas.', '48125', '48126', '5200', 'desktop-linux'):
            self.assertIn(value, profile)
        self.assertIn('не подтверждена', profile)

    def test_parser_dependencies_are_separate_and_hash_pinned(self):
        text = self.read('tools/file_hygiene_requirements.txt')
        self.assertRegex(text, r'markdown-it-py==[0-9.]+')
        self.assertRegex(text, r'mdurl==[0-9.]+')
        self.assertEqual(len(re.findall(r'--hash=sha256:[0-9a-f]{64}', text)), 2)
        self.assertNotIn('backend/requirements.txt', self.read('.github/workflows/file-hygiene.yml'))


if __name__ == '__main__':
    unittest.main()
