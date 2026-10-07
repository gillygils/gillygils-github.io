import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from drawing_converter.events import connect_events


class Viewer:
    def __init__(self, signatures):
        self.signatures = signatures

    def metaObject(self):
        return SimpleNamespace(
            methodCount=lambda: len(self.signatures),
            method=lambda i: SimpleNamespace(methodSignature=lambda: self.signatures[i].encode()))


class EventTests(unittest.TestCase):
    def test_missing_named_events_route_generic_notifications_in_order(self):
        callbacks = {}
        events = []
        def connect(signature, handler):
            callbacks[signature] = handler
            return True
        handlers = {name: (lambda n=name: events.append(n)) for name in (
            'OnFinishedLoadingDocument', 'OnFailedLoadingDocument',
            'OnFinishedPrintingDocument', 'OnFailedPrintingDocument')}
        subscriptions = connect_events(Viewer(['signal(QString,int,void*)']), handlers, connect)
        self.assertTrue(subscriptions)
        dispatch = callbacks['signal(QString,int,void*)']
        dispatch('OnProgress', 1, object())
        self.assertEqual(events, [])
        dispatch('OnFinishedLoadingDocument', 1, object())
        dispatch('OnFinishedPrintingDocument', 1, object())
        dispatch('OnFailedLoadingDocument', 3, object())
        dispatch('OnFailedPrintingDocument', 1, object())
        self.assertEqual(events, list(handlers)[:1] + ['OnFinishedPrintingDocument',
                         'OnFailedLoadingDocument', 'OnFailedPrintingDocument'])

    def test_mixed_named_and_generic_events_do_not_deliver_twice(self):
        callbacks = {}
        events = []
        def connect(signature, handler):
            callbacks[signature] = handler
            return True
        connect_events(Viewer(['OnFinishedLoadingDocument(QString)', 'signal(QString,int,void*)']), {
            'OnFinishedLoadingDocument': lambda *args: events.append('loaded'),
            'OnFinishedPrintingDocument': lambda *args: events.append('printed'),
        }, connect)
        callbacks['OnFinishedLoadingDocument(QString)']('drawing')
        callbacks['signal(QString,int,void*)']('OnFinishedLoadingDocument', 1, None)
        callbacks['signal(QString,int,void*)']('OnFinishedPrintingDocument', 1, None)
        self.assertEqual(events, ['loaded', 'printed'])

    def test_unavailable_or_rejected_event_subscription_fails_before_opening(self):
        with self.assertRaisesRegex(RuntimeError, 'neither named'):
            connect_events(Viewer([]), {'OnFinishedLoadingDocument': lambda: None}, lambda *a: True)
        with self.assertRaisesRegex(RuntimeError, 'generic eDrawings'):
            connect_events(Viewer(['signal(QString,int,void*)']),
                           {'OnFinishedLoadingDocument': lambda: None}, lambda *a: False)
