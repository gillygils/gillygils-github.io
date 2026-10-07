"""Render observed records as a conspicuously incomplete vector research PDF."""
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject


def literal(text):
    raw = text.encode('cp1252',errors='replace')
    return '('+''.join('\\'+chr(c) if c in (40,41,92) else chr(c) if 32 <= c < 127
                      else '\\%03o'%c for c in raw)+')'


def write_draft(display, output):
    if not display['lines']:
        raise ValueError('No supported line records recovered.')
    writer = PdfWriter()
    page = writer.add_blank_page(width=1224,height=792)
    font = DictionaryObject({NameObject('/Type'):NameObject('/Font'),
                             NameObject('/Subtype'):NameObject('/Type1'),
                             NameObject('/BaseFont'):NameObject('/Helvetica'),
                             NameObject('/Encoding'):NameObject('/WinAnsiEncoding')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'):DictionaryObject({
        NameObject('/F1'):writer._add_object(font)})})
    points = [p for line in display['lines'] for p in (line['start'],line['end'])]
    xmin,xmax = min(p[0] for p in points),max(p[0] for p in points)
    ymin,ymax = min(p[1] for p in points),max(p[1] for p in points)
    if xmax <= xmin or ymax <= ymin:
        raise ValueError('No usable planar extent.')
    scale = min(1152/(xmax-xmin),670/(ymax-ymin))
    def xy(point):
        return 36+(point[0]-xmin)*scale,65+(point[1]-ymin)*scale
    commands = ['0 G 0.4 w']
    for line in display['lines']:
        a,b = xy(line['start']),xy(line['end'])
        commands.append(f'{a[0]:.4f} {a[1]:.4f} m {b[0]:.4f} {b[1]:.4f} l S')
    for text in display['texts']:
        if not text['renderable']:
            continue
        x,y = xy(text['origin'])
        size = text['height']*scale*1.35
        for char,advance in zip(text['text'],text['advances']):
            commands.append(f'BT /F1 {size:.4f} Tf 1 0 0 1 {x:.4f} {y:.4f} Tm {literal(char)} Tj ET')
            x += advance*scale
    commands += ['1 0 0 rg', 'BT /F1 18 Tf 36 760 Td '
                 '(INCOMPLETE NATIVE DECODER - NOT FOR MANUFACTURING) Tj ET',
                 'BT /F1 11 Tf 36 32 Td '
                 '(Missing curves, symbols and view transforms. Substituted font. Scale is fitted, not verified.) Tj ET']
    stream = DecodedStreamObject()
    stream.set_data('\n'.join(commands).encode('ascii'))
    page[NameObject('/Contents')] = writer._add_object(stream)
    writer.add_metadata({'/Title':'Incomplete native SolidWorks drawing research draft',
                         '/Subject':'NOT FOR MANUFACTURING. Partial decoder output.'})
    with output.open('xb') as file:
        writer.write(file)
