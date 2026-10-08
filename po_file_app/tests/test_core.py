import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import parse_po, find_files, copy_new, validate_destination, idt_folder

class CoreTests(unittest.TestCase):
    def parse_text(self, *pages):
        with patch('core.PdfReader') as reader:
            reader.return_value.pages = [SimpleNamespace(extract_text=lambda text=text, **kwargs:text) for text in pages]
            return parse_po(io.BytesIO(b''))

    def test_po_layout_multi_page(self):
        class Page:
            def __init__(self, text): self.text = text
            def extract_text(self, **kwargs): return self.text
        with patch('core.PdfReader') as reader:
            reader.return_value.pages = [Page('PO # 1530\n 1 50 PC C13030 10/9/2026\n Qty: 8 for 2026099-2'), Page('PO#: 1530\n 2 AS C15732_001 3 10/9/2026')]
            number, items = parse_po(io.BytesIO(b''))
        self.assertEqual(number, '1530')
        self.assertEqual([(i.quantity, i.part) for i in items], [('50', 'C13030'), ('3', 'C15732_001')])

    def test_process_labels_are_ignored_for_c_and_m_parts(self):
        number,items=self.parse_text('''PO # 1926
 1 PC C16913 - Machine 1             $0.00 $0.00
   Machine - DEPOSIT PLATE (1 X 3, ONE SHOT)
   Qty: 1 for 2026193-1
 2 PC M16915_001 - Anodize Type II Class 2 12.5       10/23/2026 $0.00 $0.00
   Use fixture C99999 and tool M99999
   Qty: 12.5 for 2026193-1
 3 20 PC M16917 - Powder Coat          10/23/2026 $0.00 $0.00
 4 PC C16918 7 - Anodize Type II Class 2             $0.00 $0.00
''')
        self.assertEqual(number,'1926')
        self.assertEqual([(i.number,i.quantity,i.unit,i.part) for i in items],
                         [(1,'1','PC','C16913'),(2,'12.5','PC','M16915_001'),(3,'20','PC','M16917'),(4,'7','PC','C16918')])

    def test_quantity_is_not_taken_from_due_date_or_price(self):
        _,items=self.parse_text('''PO # 9999
 1 PC C12345 50       10/9/2026       $65.00 $3,250.00
 2 AS M12346_002 - Heat Treat 2 30       11/12/2026 $10.00 $300.00
''')
        self.assertEqual([i.quantity for i in items],['50','30'])

    def test_missing_quantity_on_last_item_is_not_silently_skipped(self):
        with self.assertRaisesRegex(ValueError,'quantity for line 2'):
            self.parse_text('PO # 9999\n1 PC C12345 - Machine 1 $0.00 $0.00\n2 PC M12346 - Anodize $0.00 $0.00')

    def test_only_exact_c_and_m_identifiers_are_accepted(self):
        _,items=self.parse_text('PO # 9999\n1 pc m12345_001 - custom process 3 $0.00 $0.00')
        self.assertEqual((items[0].part,items[0].unit),('M12345_001','PC'))
        for part in ('C123456','M12345X','M12345_bad','A12345'):
            with self.assertRaisesRegex(ValueError,'No CXXXXX or MXXXXX'):
                self.parse_text(f'PO # 9999\n1 PC {part} - Machine 3 $0.00 $0.00')

    def test_process_po_parts_find_exact_c_and_m_files(self):
        _,items=self.parse_text('PO # 9999\n1 PC C16913 - Machine 1 $0.00 $0.00\n2 PC M16915_001 - Anodize 3 $0.00 $0.00')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for name in ['IDT C16000/C16913.sldprt','IDT C16000/C16913.slddrw',
                         'IDT M16000/M16915_001.sldprt','IDT M16000/M16915_002.sldprt',
                         'IDT M16000/M16915.sldprt']:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.touch()
            matches=find_files(root,[i.part for i in items],grouped=True)
            self.assertEqual([p.name for p in matches['C16913']],['C16913.slddrw','C16913.sldprt'])
            self.assertEqual([p.name for p in matches['M16915_001']],['M16915_001.sldprt'])
            self.assertEqual(idt_folder('M16915_001'),'IDT M16000')

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
