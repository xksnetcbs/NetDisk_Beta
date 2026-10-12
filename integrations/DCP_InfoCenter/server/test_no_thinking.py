import ast
import json
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch
import urllib.request

class NoThinking(unittest.TestCase):
    def test_common_request_disables_thinking_without_mutating_input(self):
        tree=ast.parse((Path(__file__).parent/'terminal_backend.py').read_text(encoding='utf-8'))
        function=next(node for node in ast.walk(tree) if isinstance(node,ast.FunctionDef) and node.name=='model_completion')
        namespace={'json':json,'urllib':urllib}
        exec(compile(ast.Module(body=[function],type_ignores=[]),'request-only','exec'),namespace)
        response=MagicMock()
        response.__enter__.return_value.read.return_value=b'{"choices":[{"message":{"content":"ok"}}]}'
        payload={'model':'test','thinking':{'type':'enabled'},'messages':[]}
        with patch('urllib.request.build_opener') as opener:
            opener.return_value.open.return_value=response
            result=namespace['model_completion'](None,{'base_url':'https://example.com/v1'},payload)
            sent=json.loads(opener.return_value.open.call_args.args[0].data)
        self.assertEqual(result,'ok')
        self.assertEqual(sent['thinking'],{'type':'disabled'})
        self.assertEqual(payload['thinking'],{'type':'enabled'})

if __name__=='__main__':unittest.main()
