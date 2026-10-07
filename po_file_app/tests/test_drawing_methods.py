import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from drawing_converter.methods import method_signature


class MethodTests(unittest.TestCase):
    def viewer(self, signatures):
        meta = SimpleNamespace(methodCount=lambda: len(signatures), method=lambda i:
                               SimpleNamespace(methodSignature=lambda: signatures[i].encode()))
        return SimpleNamespace(metaObject=lambda: meta)

    def test_open_doc_missing_from_qt_metadata_uses_documented_prototype(self):
        self.assertEqual(method_signature(self.viewer([]), 'OpenDoc'),
                         'OpenDoc(QString,bool,bool,bool,QString)')

    def test_control_specific_prototype_takes_precedence(self):
        self.assertEqual(method_signature(self.viewer(['OpenDoc(QString,bool,bool,bool,QString&)']),
                                         'OpenDoc'), 'OpenDoc(QString,bool,bool,bool,QString&)')

    def test_undocumented_methods_cannot_be_invented(self):
        with self.assertRaisesRegex(RuntimeError, 'No documented'):
            method_signature(self.viewer([]), 'SaveAsPdf')
