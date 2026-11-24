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
    append = next(tool for tool in tools if tool.name == 'append_media')
    schema = getattr(append, 'inputSchema', None) or getattr(append, 'input_schema', None)
    assert 'media_type' in schema['properties'], schema
    assert {'preview_timeline','compare_timelines','project_health','bridge_capabilities','review_silence','apply_silence_cuts','render_status','inspect_fusion'} <= names
    payload = json.dumps({'ok': True, 'result': {'format':'png','image_base64':base64.b64encode(b'image-fixture').decode(),'width':1,'height':1}})
    with patch.object(server, '_result', return_value=payload):
        result = server.timeline_frame()
        assert isinstance(result[1], ImageContent)
        mime = getattr(result[1], 'mime_type', None) or getattr(result[1], 'mimeType', None)  # mcp 2.x / 1.x
        assert mime == 'image/png', mime
        assert 'image_base64' not in result[0].text
        # Exercise FastMCP's serialization too, not just the Python function.
        converted = await server.mcp.call_tool('timeline_frame', {})
        content = converted[0] if isinstance(converted, tuple) else getattr(converted, 'content', converted)
        assert any(isinstance(part, ImageContent) for part in content), converted
    with patch.object(server, '_result', return_value=json.dumps({'ok':False,'error':'offline'})):
        assert isinstance(server.timeline_frame()[0], TextContent)
    marker = next(tool for tool in tools if tool.name == 'add_marker')
    schema = getattr(marker, 'inputSchema', None) or getattr(marker, 'input_schema', None)
    assert 'timeline_frame' in schema['properties'], schema
    with patch.object(server, '_result', return_value='{}') as result:
        server.add_marker('Onset', timeline_frame=86424)
        assert result.call_args[0][1]['timeline_frame'] == 86424, result.call_args
        server.delete_marker(timeline_frame=86424)
        assert result.call_args[0][1] == {'frame': None, 'timeline_frame': 86424}, result.call_args
        # Long audio ranges get proportionally more time than the old fixed 120 s.
        server.timeline_audio(max_duration_seconds=3600)
        assert result.call_args[1]['timeout'] == 480, result.call_args
        server.timeline_audio()
        assert result.call_args[1]['timeout'] == 150, result.call_args
asyncio.run(check())
'''
        with tempfile.TemporaryDirectory() as home:
            result=subprocess.run([sys.executable,'-c',source],cwd=Path(__file__).resolve().parents[1],env=dict(os.environ,RESOLVE_AI_BRIDGE_HOME=home,PYTHONDONTWRITEBYTECODE='1'),capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
