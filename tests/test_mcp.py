import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

@unittest.skipUnless(importlib.util.find_spec('mcp'), 'Install requirements.txt to run MCP SDK checks')
class MCPTests(unittest.TestCase):
    def test_native_image_and_tool_schemas(self):
        source = '''
import asyncio, base64, json
from unittest.mock import patch
from bridge import server
from mcp.types import ImageContent, TextContent
async def check():
    tools = await server.mcp.list_tools()
    names = {tool.name for tool in tools}
    assert {'preview_timeline','compare_timelines','project_health','bridge_capabilities','review_silence','apply_silence_cuts'} <= names
    payload = json.dumps({'ok': True, 'result': {'format':'png','image_base64':base64.b64encode(b'image-fixture').decode(),'width':1,'height':1}})
    with patch.object(server, '_result', return_value=payload):
        result = server.timeline_frame()
        assert isinstance(result[1], ImageContent)
        assert result[1].mimeType == 'image/png'
        assert 'image_base64' not in result[0].text
        # Exercise FastMCP's serialization too, not just the Python function.
        converted = await server.mcp.call_tool('timeline_frame', {})
        content = converted[0] if isinstance(converted, tuple) else converted
        assert any(isinstance(part, ImageContent) for part in content), converted
    with patch.object(server, '_result', return_value=json.dumps({'ok':False,'error':'offline'})):
        assert isinstance(server.timeline_frame()[0], TextContent)
asyncio.run(check())
'''
        with tempfile.TemporaryDirectory() as home:
            result=subprocess.run([sys.executable,'-c',source],cwd=Path(__file__).resolve().parents[1],env=dict(os.environ,RESOLVE_AI_BRIDGE_HOME=home,PYTHONDONTWRITEBYTECODE='1'),capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
