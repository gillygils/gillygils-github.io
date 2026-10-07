import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from local_converter import convert_part


class LocalConverterTests(unittest.TestCase):
    def test_existing_destination_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp) / 'existing.step'; destination.write_bytes(b'keep')
            with self.assertRaises(FileExistsError): convert_part(Path(temp) / 'part.sldprt', destination)
            self.assertEqual(destination.read_bytes(), b'keep')

    def test_reader_failure_keeps_native_and_no_step(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'part.sldprt';source.write_bytes(b'native')
            destination=Path(temp)/'part.step'
            result=subprocess.CompletedProcess([],1,'','Unsupported part')
            with patch('local_converter.converter_ready',return_value=True), patch('local_converter.node_executable',return_value='node'), patch('local_converter.subprocess.run',return_value=result):
                with self.assertRaisesRegex(RuntimeError,'Unsupported part'): convert_part(source,destination)
            self.assertEqual(source.read_bytes(),b'native')
            self.assertFalse(destination.exists())
            self.assertEqual(set(Path(temp).iterdir()),{source})

    def test_reader_timeout_cleans_working_files(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'part.sldprt';source.write_bytes(b'native')
            destination=Path(temp)/'part.step'
            with patch('local_converter.converter_ready',return_value=True), patch('local_converter.node_executable',return_value='node'), patch('local_converter.subprocess.run',side_effect=subprocess.TimeoutExpired('node',120)):
                with self.assertRaisesRegex(RuntimeError,'120 seconds'): convert_part(source,destination)
            self.assertEqual(set(Path(temp).iterdir()),{source})

    def test_mesh_fallback_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'part.sldprt';source.write_bytes(b'native')
            destination=Path(temp)/'part.step'
            result=subprocess.CompletedProcess([],0,'{"success":true,"geometry_source":"displaylists"}\n','')
            with patch('local_converter.converter_ready',return_value=True), patch('local_converter.node_executable',return_value='node'), patch('local_converter.subprocess.run',return_value=result):
                with self.assertRaisesRegex(RuntimeError,'boundary-representation'): convert_part(source,destination)
            self.assertFalse(destination.exists())
