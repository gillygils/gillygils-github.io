import io
import json
import shutil
from datetime import datetime
from pathlib import Path

import streamlit as st
from core import parse_po, find_files, validate_destination, copy_new

st.set_page_config(page_title='PO File Packager', page_icon='📁', layout='wide')
st.title('PO File Packager')
st.write('Upload a purchase order, review matching engineering files, then create a folder with copies and exports.')
st.caption('Run this app on your Windows PC with access to Z:. Copy native files and any existing PDF or STEP exports into a PO folder.')
with st.sidebar:
    st.header('Folders')
    root = st.text_input('Source folder', value='Z:\\', help='Use the exact folder containing your IDT folders. A UNC path also works.')
    destination = st.text_input('Output parent folder', help='Choose a folder outside the source tree. Each run creates a new PO folder.')
    grouped = st.checkbox('Search only matching IDT folders (faster)', value=True, help='C13030 searches IDT C13000; C15732_001 searches IDT C15000. Turn off to search the entire source folder if your files use a different layout.')
    st.caption('Files on the source drive are copied. Existing output files are never overwritten.')
    st.caption('SolidWorks conversion is skipped. Referenced dependencies are not bundled automatically.')
upload = st.file_uploader('Purchase order PDF', type=['pdf'])
if upload is None:
    st.info('Upload a text-based PO PDF to begin. Scanned documents need OCR before uploading.')
    st.stop()
try:
    number, items = parse_po(io.BytesIO(upload.getvalue()))
except Exception as exc:
    st.error(str(exc))
    st.stop()
st.subheader(f'PO {number} · {len(items)} line items')
st.dataframe([{'Line': i.number, 'Part': i.part, 'Quantity': i.quantity, 'Unit': i.unit} for i in items], hide_index=True, use_container_width=True)
st.warning('Review every extracted part number and quantity against the PO before processing. Suffixed parts such as C15732_001 are matched separately; they are not assumed to be configurations of C15732.')
key = (upload.getvalue(), root, grouped)
if st.session_state.get('search_key') != key:
    st.session_state.pop('matches', None)
    st.session_state.pop('completed_job', None)
if st.button('Search source folder', type='primary'):
    try:
        meter = st.progress(0, text='Starting search…')
        def update_progress(done, total, folder, scanned):
            meter.progress(done / max(total, 1), text=f'{done}/{total} search folders complete · {scanned} directories checked · {folder}')
        with st.spinner('Searching engineering folders…'):
            st.session_state.matches = find_files(root, list(dict.fromkeys(i.part for i in items)), grouped=grouped, progress=update_progress)
            st.session_state.search_key = key
        st.success('Search complete. Review part and drawing matches for every PO line.')
    except Exception as exc:
        st.error(str(exc))
if 'matches' not in st.session_state:
    st.stop()
if grouped:
    st.caption('Fast search checked only the relevant IDT folders, including their subfolders. If a part is missing or your grouping differs, turn off the fast-search option and search again.')
selected = {}
missing = []
for part, files in st.session_state.matches.items():
    with st.expander(f'{part} · {len(files)} matching files', expanded=True):
        chosen = []
        for label, suffix in [('Part', '.sldprt'), ('Drawing', '.slddrw'), ('Assembly', '.sldasm'), ('PDF', '.pdf'), ('STEP', '.step'), ('STEP (.stp)', '.stp')]:
            options = [str(p) for p in files if p.suffix.lower() == suffix]
            if options:
                option = st.selectbox(label, ['Skip'] + options, index=1 if len(options) == 1 else 0, key=f'{key[1]}-{part}-{suffix}')
                if len(options) > 1:
                    st.warning(f'Multiple {label.lower()} matches: select the correct file or leave it skipped.')
                if option != 'Skip':
                    chosen.append(Path(option))
        if not chosen:
            missing.append(part)
            st.warning('No files selected for this part.')
        selected[part] = chosen
ack = st.checkbox('I checked the PO lines and selected the correct files. Process selected files even if some lines have no files.')
if st.button('Create PO folder and process files', disabled=not ack):
    if not destination.strip():
        st.error('Enter an output parent folder.')
        st.stop()
    if not any(selected.values()):
        st.error('Select at least one source file.')
        st.stop()
    try:
        output = validate_destination(root, destination)
        job = output / f'PO {number} - {datetime.now():%Y%m%d-%H%M%S-%f}'
        job.mkdir(parents=True, exist_ok=False)
    except Exception as exc:
        st.error(str(exc))
        st.stop()
    results = []
    try:
        with (job / 'purchase-order.pdf').open('xb') as f:
            f.write(upload.getvalue())
        with st.status('Processing files…', expanded=True) as status:
            for part, paths in selected.items():
                if not paths:
                    results.append({'part': part, 'status': 'Missing or skipped'})
                for source in paths:
                    result = {'part': part, 'source': str(source), 'copy': '', 'status': ''}
                    results.append(result)
                    try:
                        folder = job / part
                        copied = copy_new(source, folder / source.name)
                        result['copy'] = str(copied)
                        result['status'] = 'Copied'
                        st.write(f'{part}: {result["status"]}')
                    except Exception as exc:
                        result['status'] = f'Failed: {exc}'
                        st.error(f'{part}: {exc}')
            status.update(label='Processing finished — review the report', state='complete')
    except Exception as exc:
        results.append({'status': f'Job failed: {exc}'})
        st.error(str(exc))
    finally:
        report = {'po': number, 'items': [vars(i) for i in items], 'results': results}
        try:
            (job / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        except Exception as exc:
            st.error(f'Could not save report: {exc}. Download it below.')
    archive = None
    try:
        archive = shutil.make_archive(str(job), 'zip', root_dir=job.parent, base_dir=job.name)
    except Exception as exc:
        st.error(f'Files were saved, but ZIP creation failed: {exc}')
    st.session_state.completed_job = {
        'folder': str(job), 'archive': archive, 'report': report,
    }

if 'completed_job' in st.session_state:
    completed = st.session_state.completed_job
    st.subheader('Download collected files')
    st.write(f'Output folder: {completed["folder"]}')
    report = completed['report']
    st.dataframe(report['results'], use_container_width=True)
    if any(result['status'] != 'Copied' for result in report['results']):
        st.warning('Some files were missing, skipped, or failed. The ZIP contains the collected files; check the report for incomplete items.')
    if completed['archive']:
        try:
            with open(completed['archive'], 'rb') as archive_file:
                st.download_button(
                    'Download PO files ZIP', archive_file,
                    file_name=Path(completed['archive']).name,
                    mime='application/zip', on_click='ignore', type='primary',
                )
        except OSError as exc:
            st.error(f'Cannot read ZIP: {exc}. The copied files remain in the output folder.')
    st.download_button('Download processing report', json.dumps(report, indent=2), file_name=f'PO-{report["po"]}-report.json', mime='application/json', on_click='ignore')
