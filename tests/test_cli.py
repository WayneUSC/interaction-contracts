import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

from interaction_contracts.cli import main, read_events
from interaction_contracts.core import TraceFormatError, audit

TRACES = Path(__file__).resolve().parents[1] / 'examples/traces'


class CliTests(unittest.TestCase):
    def run_cli(self, *args, stdin=''):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), patch('sys.stdin',io.StringIO(stdin)):
            code = main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_corpus_expectations(self):
        for case in json.loads((TRACES/'manifest.json').read_text()):
            with self.subTest(case=case['file']):
                with (TRACES/case['file']).open() as stream:
                    report = audit(read_events(stream))
                self.assertEqual(report.status,case['status'])
                codes = {f.code for f in report.findings}
                self.assertTrue(set(case['required_codes']) <= codes)

    def test_json_and_exit_codes(self):
        for name, expected in [('parallel_mapped',0),('parallel_ambiguous',1),('pending_only',2)]:
            with self.subTest(name=name):
                code,out,_=self.run_cli(str(TRACES/(name+'.jsonl')),'--format','json')
                self.assertEqual(code,expected)
                self.assertEqual(len(json.loads(out)['results']),1)

    def test_strict_warns_without_changing_report(self):
        path=str(TRACES/'duplicate_prompt.jsonl')
        self.assertEqual(self.run_cli(path)[0],0)
        code,out,_=self.run_cli(path,'--strict','--format','json')
        self.assertEqual(code,1)
        self.assertEqual(json.loads(out)['results'][0]['report']['status'],'pass')

    def test_invalid_json_and_duplicate_keys_rejected(self):
        for payload in ['{', '[]', '{"type":"snapshot","type":"resume"}', '{"value":NaN}']:
            with self.subTest(payload=payload):
                code,out,err=self.run_cli('-','--format','json',stdin=payload)
                self.assertEqual(code,2)
                self.assertIn('error',json.loads(out)['results'][0])
                self.assertEqual(err,'')

    def test_empty_input_is_inconclusive(self):
        self.assertEqual(self.run_cli('-',stdin='\n')[0],2)

    def test_deep_json_returns_invalid_and_junit(self):
        payload='{"type":"snapshot","thread_id":"d","revision":"r","pending":[],"metadata":{"deep":'+'['*160+'0'+']'*160+'}}'
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)/'report.xml'
            code,out,_=self.run_cli('-','--format','json','--junit',str(target),stdin=payload)
            self.assertEqual(code,2)
            self.assertIn('error',json.loads(out)['results'][0])
            self.assertEqual(ET.parse(target).getroot().attrib['errors'],'1')

    def test_missing_file_is_machine_readable(self):
        with tempfile.TemporaryDirectory() as td:
            code,out,_=self.run_cli(str(Path(td)/'missing.jsonl'),'--format','json')
        self.assertEqual(code,2)
        self.assertIn('error',json.loads(out)['results'][0])

    def test_junit_success_failure_skip_and_invalid(self):
        with tempfile.TemporaryDirectory() as td:
            target=Path(td)/'results.xml'
            code,_,_=self.run_cli(str(TRACES/'parallel_mapped.jsonl'),str(TRACES/'parallel_ambiguous.jsonl'),str(TRACES/'pending_only.jsonl'),str(Path(td)/'missing.jsonl'),'--junit',str(target))
            self.assertEqual(code,2)
            root=ET.parse(target).getroot()
            self.assertEqual(root.attrib['tests'],'4')
            self.assertEqual(root.attrib['failures'],'1')
            self.assertEqual(root.attrib['errors'],'1')
            self.assertEqual(root.attrib['skipped'],'1')

    def test_independent_files_do_not_share_thread_state(self):
        with tempfile.TemporaryDirectory() as td:
            only_reply=Path(td)/'reply.jsonl'
            only_reply.write_text('{"type":"resume","thread_id":"demo","revision":"v1","value":true}\n')
            code,out,_=self.run_cli(str(TRACES/'pending_only.jsonl'),str(only_reply),'--format','json')
            self.assertEqual(code,2)
            self.assertEqual(json.loads(out)['results'][1]['report']['status'],'fail')

    def test_junit_cannot_replace_trace(self):
        source=str(TRACES/'parallel_mapped.jsonl')
        before=Path(source).read_bytes()
        with self.assertRaises(SystemExit):
            self.run_cli(source,'--junit',source)
        self.assertEqual(before,Path(source).read_bytes())


if __name__ == '__main__':
    unittest.main()
