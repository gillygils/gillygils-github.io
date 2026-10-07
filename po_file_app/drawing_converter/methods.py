"""Documented eDrawings prototypes for Qt wrappers with incomplete metadata."""
PROTOTYPES = {
    'OpenDoc': 'OpenDoc(QString,bool,bool,bool,QString)',
    'SetPageSetupOptions': 'SetPageSetupOptions(int,int,int,int,int,int,QString,int,int,int,int)',
    'Print5': 'Print5(bool,QString,bool,bool,bool,int,double,int,int,bool,int,int,QString)',
}


def method_signature(viewer, name):
    meta = viewer.metaObject()
    for i in range(meta.methodCount()):
        signature = bytes(meta.method(i).methodSignature()).decode()
        if signature.startswith(name + '('):
            return signature
    try:
        return PROTOTYPES[name]
    except KeyError:
        raise RuntimeError(f'No documented eDrawings prototype is available for {name}.') from None
