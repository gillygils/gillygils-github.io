import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import parse_po, find_files, copy_new, validate_destination, idt_folder

class CoreTests(unittest.TestCase):
    def test_po_layout_multi_page(self):
        class Page:
            def __init__(self, text): self.text = text
            def extract_text(self, **kwargs): return self.text
        with patch('core.PdfReader') as reader:
            reader.return_value.pages = [Page('PO # 1530\n 1 50 PC C13030 10/9/2026\n Qty: 8 for 2026099-2'), Page('PO#: 1530\n 2 AS C15732_001 3 10/9/2026')]
            number, items = parse_po(io.BytesIO(b''))
        self.assertEqual(number, '1530')
        self.assertEqual([(i.quantity, i.part) for i in items], [('50', 'C13030'), ('3', 'C15732_001')])

    def test_scanned_pdf_rejected(self):
        with patch('core.PdfReader') as reader:
            reader.return_value.pages = []
            with self.assertRaises(ValueError): parse_po(io.BytesIO(b''))

    def test_exact_lookup_duplicates_and_suffixes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ['IDT C13000/C13030.SLDPRT', 'IDT C13000/C13030 - rail.pdf', 'backup/C13030.sldprt', 'IDT C15000/C15732_001.sldprt', 'IDT C15000/C15732_002.sldprt', 'IDT C15000/C15732.sldprt', 'IDT C13000/C130300.sldprt']:
                p = root / name; p.parent.mkdir(parents=True, exist_ok=True); p.touch()
            result = find_files(root, ['C13030', 'C15732_001', 'C15732', 'C99999'])
            self.assertEqual(len(result['C13030']), 3)
            self.assertEqual(len(result['C15732_001']), 1)
            self.assertEqual(len(result['C15732']), 1)
            self.assertEqual(result['C99999'], [])

    def test_grouped_search_skips_unrelated_folders_and_reports_completion(self):
        import os
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ['IDT C13000/C13030.sldprt', 'IDT C13000/sub/C13039.slddrw', 'IDT C15000/C15732_001.sldprt', 'unrelated/C13030.sldprt']:
                p = root / name; p.parent.mkdir(parents=True, exist_ok=True); p.touch()
            progress = []
            with patch('os.scandir', wraps=os.scandir) as scan:
                matches = find_files(root, ['C13030', 'C13039', 'C15732_001', 'C99999'], grouped=True, progress=lambda *args: progress.append(args))
            self.assertEqual(len(matches['C13030']), 1)
            self.assertEqual(len(matches['C13039']), 1)
            self.assertEqual(len(matches['C15732_001']), 1)
            self.assertEqual(matches['C99999'], [])
            visited = [Path(call.args[0]) for call in scan.call_args_list]
            self.assertNotIn(root / 'unrelated', visited)
            self.assertEqual(visited.count(root / 'IDT C13000'), 1)
            self.assertEqual(progress[-1][:3], (3, 3, 'Search complete'))
            self.assertEqual(idt_folder('C13030'), 'IDT C13000')
            self.assertEqual(idt_folder('C15732_001'), 'IDT C15000')
            self.assertEqual(idt_folder('A00001'), 'IDT A00000')

    def test_grouped_search_direct_idt_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'IDT C13000'; root.mkdir()
            (root / 'C13030.sldprt').touch()
            self.assertEqual(len(find_files(root, ['C13030'], grouped=True)['C13030']), 1)

    def test_copy_content_and_no_overwrites(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source = root / 'source.sldprt'; source.write_bytes(b'part-content')
            output = root / 'output' / source.name
            copy_new(source, output)
            self.assertEqual(output.read_bytes(), source.read_bytes())
            with self.assertRaises(FileExistsError): copy_new(source, output)
            self.assertEqual(source.read_bytes(), b'part-content')

    def test_destination_not_inside_source(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaises(ValueError): validate_destination(root, root / 'output')
            with self.assertRaises(ValueError): validate_destination(root, root)
            self.assertEqual(validate_destination(root / 'source', root / 'output'), root / 'output')

if __name__ == '__main__': unittest.main()
