import unittest
from pathlib import Path


class WorkflowTests(unittest.TestCase):
    def test_reusable_workflow_checks_out_its_exact_source(self):
        workflow = (
            Path(__file__).parents[1] / '.github/workflows/publish.yml'
        ).read_text()

        self.assertIn('repository: ${{ job.workflow_repository }}', workflow)
        self.assertIn('ref: ${{ job.workflow_sha }}', workflow)
        self.assertNotIn('ref: main', workflow)


if __name__ == '__main__':
    unittest.main()
