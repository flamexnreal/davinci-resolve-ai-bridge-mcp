"""Optional real FFmpeg checks, using generated media only (no Resolve instance)."""
import os
import struct
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch
from bridge.operations import ResolveOperations
from fakes import Clip, Media, Project, Resolve

FFMPEG=ResolveOperations._ffmpeg_path()
@unittest.skipUnless(FFMPEG,'Optional FFmpeg decoder not installed')
class DecoderTests(unittest.TestCase):
    def test_real_trimmed_wav_and_stereo_levels(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'input.wav'
            with wave.open(str(source),'wb') as w:
                w.setnchannels(2);w.setsampwidth(2);w.setframerate(48000)
                w.writeframes(struct.pack('<hh',32767,-32767)*96000)
            clip=Clip(86400,86448,Media(source),kind='audio');project=Project([clip]);timeline=project.current
            timeline.start=86400;timeline.start_tc='01:00:00:00';timeline.current='01:00:01:00'
            op=ResolveOperations(lambda:Resolve(project))
            with patch('tempfile.gettempdir',return_value=directory):
                result=op._op_timeline_audio({'item_id':clip.uid,'action':'analyze'})
                self.assertTrue(result['is_clipping']);self.assertEqual(result['timeline_start_frame'],86424)
                with wave.open(result['wav_path'],'rb') as w:self.assertEqual(w.getnframes()/w.getframerate(),1)
    def test_real_source_image_at_nonzero_start(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'source.mp4'
            subprocess.run([FFMPEG,'-v','error','-y','-f','lavfi','-i','color=c=red:s=320x180:r=24','-t','2','-c:v','mpeg4',str(source)],check=True,capture_output=True,timeout=20)
            clip=Clip(86400,86448,Media(source));project=Project([clip]);timeline=project.current
            timeline.start=86400;timeline.start_tc='01:00:00:00';timeline.current='01:00:01:00'
            op=ResolveOperations(lambda:Resolve(project))
            with patch('tempfile.gettempdir',return_value=directory):
                result=op._op_timeline_frame({'mode':'source','max_width':160})
                self.assertEqual((result['width'],result['height']),(160,90))
                self.assertEqual(result['frame'],86424);self.assertFalse(result['composited'])
                self.assertTrue(Path(result['file_path']).is_file())
