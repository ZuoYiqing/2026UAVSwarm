"""Generated local fixtures only; no real server, model, or flight."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from uavswarm_llm_lab.cli import main
from uavswarm_llm_lab.local_model_client import ModelError


class CliEvidenceTest(unittest.TestCase):
    def test_incomplete_output_is_saved_but_rejected_and_never_overwritten(self):
        module = Path(__file__).resolve().parents[1]
        generated = module / 'artifacts' / 'tests'
        generated.mkdir(parents=True, exist_ok=True)
        evidence = {'choices': [{'finish_reason': 'length',
                                'message': {'content': '{"unfinished":'}}]}
        with TemporaryDirectory(dir=generated, prefix='cli-evidence-') as temporary:
            output = Path(temporary) / 'failed.json'
            argv = ['infer', str(module / 'examples' / 'three_uav_inspection.json'),
                    '--base-url', 'http://127.0.0.1:18080/v1', '--model', 'fixture',
                    '--output', str(output)]
            with patch('uavswarm_llm_lab.cli.LocalModelClient'), \
                 patch('uavswarm_llm_lab.cli.plan_with_client',
                       side_effect=ModelError('MODEL_RESPONSE_INCOMPLETE',
                                              response_evidence=evidence)) as planner, \
                 redirect_stdout(io.StringIO()):
                self.assertEqual(main(argv), 2)
                saved = json.loads(output.read_text(encoding='utf-8'))
                self.assertEqual(saved['response_evidence'], evidence)
                self.assertFalse(saved['accepted'])
                self.assertFalse(saved['execution_authorized'])
                self.assertIsNone(saved['proposal'])
                original = output.read_bytes()
                self.assertEqual(main(argv), 2)
                self.assertEqual(output.read_bytes(), original)
                self.assertEqual(planner.call_count, 1)
