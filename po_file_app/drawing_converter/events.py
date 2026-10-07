"""Subscribe to ActiveX events, including events without generated Qt signals."""


def connect_events(viewer, handlers, connect):
    """Return subscriptions so their callbacks remain alive until printing ends.

    Qt's generic COM signal supplies event identity even when an event's argument
    types prevent a named signal from being generated. Its raw VARIANT pointer
    is deliberately left untouched; these callbacks only need event identity.
    """
    meta = viewer.metaObject()
    signatures = [bytes(meta.method(i).methodSignature()).decode()
                  for i in range(meta.methodCount())]
    pending = {}
    subscriptions = []
    for name, handler in handlers.items():
        signature = next((s for s in signatures if s.startswith(name + '(')), None)
        if signature and connect(signature, handler):
            subscriptions.append(handler)
        else:
            pending[name.casefold()] = handler
    if pending:
        generic = next((s for s in signatures if s.startswith('signal(QString,int,')), None)
        if generic is None:
            raise RuntimeError('Cannot subscribe to eDrawings document events: neither named '
                               'events nor the generic Qt COM event signal are available. '
                               'Repair the eDrawings installation and check its ActiveX support.')

        def dispatch(name, argc, argv):
            event = str(name).split('(', 1)[0].casefold()
            handler = pending.get(event)
            if handler:
                handler()

        if not connect(generic, dispatch):
            raise RuntimeError('Cannot subscribe to the generic eDrawings COM event signal.')
        subscriptions.append(dispatch)
    return subscriptions
