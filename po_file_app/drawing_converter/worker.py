"""Windows eDrawings ActiveX print worker; run in a separate GUI process."""
import argparse
import json
import sys
import time
import uuid
from pathlib import Path

if __package__:
    from .events import connect_events
else:
    from events import connect_events

PAPERS = {'Letter': 1, 'Tabloid': 3, 'A4': 9, 'A3': 8}


def print_drawing(source, output, control_id, paper, landscape):
    from PySide6.QtAxContainer import QAxWidget
    from PySide6.QtCore import QTimer, QObject, SIGNAL
    from PySide6.QtWidgets import QApplication
    from pypdf import PdfReader

    app = QApplication([])
    viewer = QAxWidget()
    viewer.resize(1000, 750)
    viewer.setWindowTitle('PO File Packager — printing drawing PDF')
    state = {'error': None, 'sheets': None, 'printing_finished': False, 'pdf_ready': False, 'pdf_problem': None}
    started = time.monotonic()
    queue_name = 'PO-Packager-' + uuid.uuid4().hex

    def fail(message):
        if state['error'] is None:
            state['error'] = str(message)
        app.quit()

    def invoke(name, arguments):
        meta = viewer.metaObject()
        signatures = [bytes(meta.method(i).methodSignature()).decode() for i in range(meta.methodCount())]
        signature = next((signature for signature in signatures if signature.startswith(name + '(')), None)
        if signature is None:
            raise RuntimeError(f'Installed eDrawings control does not expose {name}.')
        result = viewer.dynamicCall(signature, arguments)
        if state['error']:
            raise RuntimeError(state['error'])
        return result

    def loaded(*args):
        if state['sheets'] is not None or state['error']:
            return
        try:
            count = viewer.property('SheetCount')
            if not isinstance(count, int) or isinstance(count, bool) or count <= 0:
                raise RuntimeError('eDrawings did not report a positive drawing sheet count.')
            state['sheets'] = count
            invoke('SetPageSetupOptions', [2 if landscape else 1, PAPERS[paper], 0, 0, 1, 7,
                                         'Microsoft Print to PDF', 0, 0, 0, 0])
            # Silent, regular quality, all sheets, scale-to-fit, explicit output path.
            invoke('Print5', [False, queue_name, False, False, True, 1, 1.0, 0, 0, True, 1, count, str(output)])
        except Exception as exc:
            fail(exc)

    def finished(*args):
        state['printing_finished'] = True

    def poll_pdf():
        if time.monotonic() - started > 120:
            detail = f' Last output check: {state["pdf_problem"]}.' if state['pdf_problem'] else ''
            fail('eDrawings/PDF printing exceeded 120 seconds.' + detail + ' Close any unexpected print dialog and use the manual PDF workflow.')
            return
        if not state['printing_finished'] or not output.is_file():
            return
        try:
            reader = PdfReader(output)
            if reader.is_encrypted or len(reader.pages) != state['sheets']:
                state['pdf_problem'] = f'PDF is encrypted or has {len(reader.pages)} pages; expected {state["sheets"]}'
                return
            if not all(page.get_contents() is not None and page.get_contents().get_data() for page in reader.pages):
                state['pdf_problem'] = 'PDF has empty page content'
                return
            state['pdf_ready'] = True
            app.quit()
        except Exception as exc:
            state['pdf_problem'] = str(exc)
            # The spooler can still be flushing the output file. Wait for a complete PDF.
            return

    if not viewer.setControl(control_id):
        raise RuntimeError('Cannot host the registered eDrawings ActiveX control. Check installation and Python/eDrawings bitness.')
    try:
        subscriptions = connect_events(viewer, {
            'OnFinishedLoadingDocument': loaded,
            'OnFailedLoadingDocument': lambda *args: fail('eDrawings failed to load the drawing.'),
            'OnFinishedPrintingDocument': finished,
            'OnFailedPrintingDocument': lambda *args: fail('eDrawings failed to send the drawing to Microsoft Print to PDF.'),
        }, lambda signature, handler: QObject.connect(viewer, SIGNAL(signature), handler))
        viewer.exception.connect(lambda code, source, description, help_text: fail(f'eDrawings COM error {code}: {description}'))
        timer = QTimer()
        timer.timeout.connect(poll_pdf)
        timer.start(250)
        # A desktop session and message pump are required by the ActiveX viewer.
        viewer.show()
        QTimer.singleShot(0, lambda: open_drawing())

        def open_drawing():
            try:
                invoke('OpenDoc', [str(source), False, False, True, ''])
            except Exception as exc:
                fail(exc)

        app.exec()
        if state['error']:
            raise RuntimeError(state['error'])
        if not state['pdf_ready']:
            raise RuntimeError('No complete PDF was produced.')
        return {'success': True, 'sheets': state['sheets'], 'printer': 'Microsoft Print to PDF',
                'paper': paper, 'orientation': 'Landscape' if landscape else 'Portrait', 'scale': 'Fit to page'}
    finally:
        viewer.clear()
        viewer.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--control', required=True)
    parser.add_argument('--paper', choices=PAPERS, default='Tabloid')
    parser.add_argument('--portrait', action='store_true')
    args = parser.parse_args()
    if sys.platform != 'win32':
        raise RuntimeError('eDrawings PDF automation requires Windows.')
    if args.source.suffix.lower() != '.slddrw' or not args.source.is_file():
        raise ValueError('Supply an existing SolidWorks drawing.')
    if args.output.exists():
        raise FileExistsError('Output already exists; it will not be overwritten.')
    result = print_drawing(args.source.resolve(), args.output.resolve(), args.control, args.paper, not args.portrait)
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr, flush=True)
        sys.exit(1)
