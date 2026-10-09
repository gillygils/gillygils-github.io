"""Experimental native drawing uploads and downloads, separate from PO jobs."""
import hashlib
import io
import json
import tempfile
import zipfile
from pathlib import Path, PureWindowsPath
from native_drawing.archive import MAX_FILE


def prepare_upload(upload, suffix):
    name = getattr(upload, 'name', '')
    if (not name or Path(name).name != name or PureWindowsPath(name).name != name
            or Path(name).suffix.lower() != suffix or not Path(name).stem
            or any(c in name for c in '<>:"|?*\0') or name.endswith((' ', '.'))):
        raise ValueError(f'Choose a plain {suffix} filename without folders or special characters.')
    if getattr(upload, 'size', 0) > MAX_FILE:
        raise ValueError('Each drawing or part must be at most 64 MiB.')
    data = upload.getvalue()
    if not data or len(data) > MAX_FILE:
        raise ValueError('Each drawing or part must be nonempty and at most 64 MiB.')
    return name, data


def convert_upload(drawing, part=None, dwg=False, converter=None):
    if converter is None:
        from native_drawing.backend import convert_drawing_native
        converter = convert_drawing_native
    suffix = Path(getattr(drawing,'name','')).suffix.lower()
    if suffix not in ('.slddrw','.dwg'):
        raise ValueError('Choose a .slddrw or .dwg drawing.')
    drawing_name, drawing_data = prepare_upload(drawing, suffix)
    if suffix == '.dwg' and (part or dwg):
        raise ValueError('DWG input creates PDF and DXF without a matching part or DWG re-export.')
    part_input = prepare_upload(part, '.sldprt') if part else None
    if part_input and Path(part_input[0]).stem.casefold() != Path(drawing_name).stem.casefold():
        raise ValueError('Choose the matching part with the same filename stem as the drawing.')
    outputs = {}
    with tempfile.TemporaryDirectory(prefix='uploaded-drawing-') as temp:
        root = Path(temp)
        source = root/drawing_name
        source.write_bytes(drawing_data)
        part_path = None
        if part_input:
            part_path = root/part_input[0]
            part_path.write_bytes(part_input[1])
        output = root/'exports'
        report = converter(source, output, part=part_path, dwg=dwg)
        for entry in report['exports'].values():
            if 'file' in entry:
                name = entry['file']
                if Path(name).name != name or PureWindowsPath(name).name != name:
                    raise ValueError('Invalid export filename.')
                outputs[name] = (output/name).read_bytes()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in outputs.items():
            archive.writestr(name, data)
        archive.writestr('drawing-report.json', json.dumps(report, indent=2))
    return {'outputs': outputs, 'report': report, 'zip': buffer.getvalue(),
            'zip_name': Path(drawing_name).stem+'-EXPERIMENTAL drawing exports.zip'}


def render_drawings():
    import streamlit as st
    from native_drawing.backend import drawing_diagnostics
    st.subheader('Drawing exports — experimental')
    st.write('Upload a SolidWorks drawing or DWG to create a local vector PDF and DXF. DWG input and optional DWG export use the free LibreDWG tools. No purchase order or eDrawings is needed.')
    st.warning('The native decoder is still incomplete. Compare every export with the original drawing before use. These marked drafts are kept separate from PO packages.')
    st.caption('Currently supports the observed single-sheet drawing layout. Other drawing versions, multiple sheets, tables, section/detail views, fonts, and styles may be unsupported. Unsupported command layouts stop the export.')
    drawing = st.file_uploader('SolidWorks drawing or DWG (.slddrw or .dwg)', type=['slddrw','dwg'], key='native_drawing_upload')
    is_dwg = bool(drawing and Path(getattr(drawing,'name','')).suffix.lower() == '.dwg')
    part = st.file_uploader('Matching part for exact spline curves (optional)', type=['sldprt'], key='native_drawing_part',disabled=is_dwg)
    if is_dwg:
        part=None
        st.caption('DWG model space is fitted to an A3 landscape PDF. Original plot scale is not preserved. PDF and DXF exports require the local DWG tools.')
    st.caption('Use the same filename stem, such as C15999.SLDDRW and C15999.SLDPRT. Without a matching part, unresolved spline curves become marked draft polylines and are listed in the report.')
    diagnostics = drawing_diagnostics()
    dwg = st.checkbox('Also create an experimental DWG', disabled=is_dwg or not diagnostics['dwg_ready'], key='native_dwg') and diagnostics['dwg_ready'] and not is_dwg
    if not diagnostics['dwg_ready']:
        st.caption('To enable DWG input or output on Windows: close the app, run install_dwg_tools.bat once while connected, then restart. SolidWorks drawing PDF and DXF exports do not need it. Conversions run locally after installation.')
    if not diagnostics['ready']:
        st.info('Run run_windows.bat once to install the drawing libraries. ' + '; '.join(diagnostics['problems']))
    def identity(upload):
        return (getattr(upload, 'name', ''), hashlib.sha256(upload.getvalue()).hexdigest()) if upload else None
    signature = (identity(drawing), identity(part), dwg)
    completed = st.session_state.get('native_drawing_result')
    if completed and completed['signature'] != signature:
        st.session_state.pop('native_drawing_result', None)
        completed = None
    if st.button('Create experimental drawing exports', disabled=not drawing or not diagnostics['ready'] or (is_dwg and not diagnostics['dwg_ready']), type='primary'):
        st.session_state.pop('native_drawing_result', None)
        completed = None
        try:
            with st.spinner('Reading DWG and rendering vectors locally…' if is_dwg else 'Decoding saved drawing views and annotations locally…'):
                completed = convert_upload(drawing, part, dwg)
                completed['signature'] = signature
                st.session_state.native_drawing_result = completed
        except Exception as exc:
            st.error(str(exc))
    if completed:
        report = completed['report']
        if is_dwg:
            st.info(f"Experimental vector PDF and DXF ready: {report['geometry']['geometry_primitives']} model-space entities. Review the drawing before use.")
        else:
            st.info(f"Experimental exports ready: {report['views']} views, {report['geometry']['geometry_primitives']} model curves. Review the drawing before use.")
        if report['geometry']['unresolved_splines']:
            st.warning(f"{len(report['geometry']['unresolved_splines'])} spline curves are approximated by polylines. Add the matching part if available; see the report for details.")
        if report['geometry'].get('cached_polylines'):
            st.warning(f"{len(report['geometry']['cached_polylines'])} other curves use saved polyline samples. Review their accuracy; see the drawing report.")
        if (report['geometry'].get('matching_part') or {}).get('unsupported_spline_candidates'):
            st.warning('Some curves in the optional part are unsupported. Unresolved drawing curves retain their saved polylines; see the drawing report.')
        for message in report['exports']['pdf'].get('warnings', []):
            st.warning(message)
        if report.get('decoder_warnings'):
            st.warning('LibreDWG reported decoding warnings. Review the exported drawing and the details in drawing-report.json.')
        if 'error' in report['exports'].get('dwg', {}):
            st.warning('DWG export failed: '+report['exports']['dwg']['error']+'. PDF and DXF remain available.')
        st.download_button('Download experimental drawing ZIP', completed['zip'],
                           file_name=completed['zip_name'], mime='application/zip', on_click='ignore', type='primary')
        for name, data in completed['outputs'].items():
            mime = 'application/pdf' if name.lower().endswith('.pdf') else 'application/octet-stream'
            st.download_button('Download '+name, data, file_name=name, mime=mime,
                               on_click='ignore', key='native_drawing_download:'+name)
        st.download_button('Download drawing report', json.dumps(report, indent=2),
                           file_name='drawing-report.json', mime='application/json', on_click='ignore')
