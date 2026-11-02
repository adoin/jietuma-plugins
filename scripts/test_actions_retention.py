import unittest
import re
from pathlib import Path
from actions_retention import deletion_ids


class RetentionTests(unittest.TestCase):
    def test_keeps_exactly_three_newest_completed_runs(self):
        runs = [{'id': i, 'status': 'completed'} for i in range(1, 7)]
        self.assertEqual(deletion_ids(runs), [3, 2, 1])

    def test_never_deletes_current_or_unfinished_runs(self):
        runs = [{'id': i, 'status': 'completed'} for i in range(1, 8)]
        runs[1]['status'] = 'in_progress'
        runs[2]['status'] = 'waiting'
        self.assertEqual(deletion_ids(runs, current=1), [4])

    def test_handles_short_histories_duplicates_and_failed_runs(self):
        self.assertEqual(deletion_ids([]), [])
        self.assertEqual(deletion_ids([{'id': 1, 'status': 'completed'}]*4), [])
        runs = [{'id': i, 'status': 'completed', 'conclusion': 'failure'} for i in range(5)]
        self.assertEqual(deletion_ids(runs), [1, 0])

    def test_rejects_nonpositive_retention(self):
        with self.assertRaises(ValueError):
            deletion_ids([], keep=0)

    def test_workflows_have_one_tag_only_entry_point(self):
        directory=Path(__file__).resolve().parents[1]/'.github'/'workflows'
        entries=0
        for path in directory.glob('*.yml'):
            text=path.read_text(encoding='utf-8')
            header=re.search(r'^on:\s*\n(.*?)(?=^\S|\Z)',text,re.M|re.S)
            self.assertIsNotNone(header,path.name)
            events=set(re.findall(r'^  ([a-z_]+):',header.group(1),re.M))
            self.assertTrue(events <= {'push','workflow_call'},(path.name,events))
            if 'push' in events:
                entries+=1
                self.assertIn('\n    tags:', '\n'+header.group(1))
                self.assertNotIn('\n    branches:', '\n'+header.group(1))
        self.assertEqual(entries,1)


if __name__ == '__main__':
    unittest.main()
