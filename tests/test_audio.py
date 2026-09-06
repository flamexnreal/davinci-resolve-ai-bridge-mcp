import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock, patch
from bridge.operations import ResolveOperations, OperationError
from fakes import Clip, Media, Project, Resolve

class AudioTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.directory=Path(self.tmp.name)
        self.source=self.directory/'input.wav';self.clip=Clip(0,48,Media(self.source),kind='audio')
        self.project=Project([self.clip]);self.op=ResolveOperations(lambda:Resolve(self.project))
        self.write([(0,0)]*96000)
    def write(self,frames,channels=2):
        with wave.open(str(self.source),'wb') as w:
            w.setnchannels(channels);w.setsampwidth(2);w.setframerate(48000)
            w.writeframes(b''.join(struct.pack('<'+'h'*channels,*f) for f in frames))
    def run_audio(self,action,playhead=0,**kw):
        def decode(command,**kwargs):
            # Emulate ffmpeg's range decoding, preserving channel layout.
            start=float(command[command.index('-ss')+1]);duration=float(command[command.index('-t')+1])
            with wave.open(str(self.source),'rb') as src:
                src.setpos(min(src.getnframes(),round(start*src.getframerate())))
                raw=src.readframes(round(duration*src.getframerate()))
                with wave.open(command[-1],'wb') as dst:dst.setparams(src.getparams());dst.writeframes(raw)
            return Mock(returncode=0,stderr=b'')
        with patch('shutil.which',return_value='ffmpeg'),patch('subprocess.run',side_effect=decode),patch('tempfile.gettempdir',return_value=self.tmp.name),patch.object(self.op,'_playhead_frame',return_value=playhead):
            return self.op._op_timeline_audio(dict(action=action,item_id=self.clip.uid,**kw))
    def test_stereo_cancellation_does_not_hide_peak(self):
        self.write([(32767,-32767)]*96000);r=self.run_audio('analyze')
        self.assertGreater(r['peak_dbfs'],-0.01);self.assertTrue(r['is_clipping']);self.assertEqual(len(r['channel_levels']),2)
    def test_loud_single_channel_detected(self):
        self.write([(32767,0)]*96000);r=self.run_audio('analyze');self.assertTrue(r['is_clipping'])
    def test_entire_silent_clip_detected(self):
        r=self.run_audio('silence_cuts');self.assertEqual(len(r['cuts']),1);self.assertEqual(r['cuts'][0]['end_frame'],48)
    def test_trailing_silence_closed(self):
        self.write([(10000,10000)]*48000+[(0,0)]*48000)
        r=self.run_audio('silence_cuts');self.assertEqual(r['cuts'][0]['start_sec'],1);self.assertEqual(r['cuts'][0]['end_sec'],2)
    def test_export_is_trimmed(self):
        r=self.run_audio('export_slice',playhead=24)
        with wave.open(r['wav_path'],'rb') as w:self.assertEqual(w.getnframes()/w.getframerate(),1)
        self.assertEqual(r['duration_sec'],1);self.assertEqual(r['timeline_start_frame'],24)
    def test_absolute_silence_coordinates(self):
        self.clip.start=86400;self.clip.end=86448
        r=self.run_audio('silence_cuts',playhead=86424)
        self.assertEqual(r['cuts'][0]['timeline_start_frame'],86424);self.assertEqual(r['cuts'][0]['timeline_end_frame'],86448)
    def test_duration_cap_is_explicit(self):
        r=self.run_audio('analyze',max_duration_seconds=0.5);self.assertEqual(r['duration_sec'],0.5);self.assertTrue(r['truncated'])
    def test_whole_clip_ignores_playhead_offset(self):
        r=self.run_audio('analyze',playhead=24,whole_clip=True);self.assertEqual(r['duration_sec'],2)
    def test_non_wav_results_cleaned(self):
        self.run_audio('silence_cuts');self.assertFalse(list((self.directory/'resolve-audio-analysis').glob('*.wav')))
    def test_invalid_threshold(self):
        with self.assertRaises(OperationError):self.run_audio('silence_cuts',silence_threshold_db=float('nan'))
