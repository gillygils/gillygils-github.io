import io
import json
import shutil
from datetime import datetime
from pathlib import Path

import streamlit as st
from native_part.backend import native_diagnostics, convert_part_native
from drawing_converter.backend import drawing_capability, convert_drawing
from core import parse_po, find_files, validate_destination, copy_new, add_converted_exports

def clear_po_after_download():
    st.session_state.last_download = st.session_state.completed_job
    st.session_state.upload_generation = st.session_state.get('upload_generation', 0) + 1
    for state_key in list(st.session_state):
        if state_key in {'matches', 'search_key', 'completed_job', 'review_ack'} or state_key.startswith('file_choice:'):
            del st.session_state[state_key]


def zip_download(completed, clear_po=False):
    with open(completed['archive'], 'rb') as archive_file:
        st.download_button(
            'Download PO files ZIP' if clear_po else 'Download last ZIP again', archive_file,
            file_name=f'PO {completed["report"]["po"]} Parts.zip',
            mime='application/zip',
            on_click=clear_po_after_download if clear_po else 'ignore',
            type='primary',
        )


st.set_page_config(page_title='PO File Packager', page_icon='📁', layout='wide')
st.title('PO File Packager')
st.write('Package engineering files from a purchase order, or upload parts directly for local STEP conversion.')
st.caption('Run this app on your Windows PC with access to Z:. Copy native files and any existing PDF or STEP exports into a PO folder.')
with st.sidebar:
    st.header('Folders')
    root = st.text_input('Source folder', value='Z:\\', help='Use the exact folder containing your IDT folders. A UNC path also works.')
    destination = st.text_input('Output parent folder', help='Choose a folder outside the source tree. Each run creates a new PO folder.')
    grouped = st.checkbox('Search only matching IDT folders (faster)', value=True, help='C13030 searches IDT C13000; C15732_001 searches IDT C15000. Turn off to search the entire source folder if your files use a different layout.')
    st.caption('Files on the source drive are copied. Existing output files are never overwritten.')
    step_provider = st.selectbox('STEP converter', ['Independent native reader (experimental)', 'Convert3D adapter (optional legacy)'])
    if step_provider.startswith('Independent'):
        diagnostics = native_diagnostics()
        step_convert = convert_part_native
        st.caption('Our Python reader runs locally with OpenCascade. No Convert3D, Node or internet is needed for conversion. Verified with 11 supplied parts; other formats and geometry may be unsupported.')
    else:
        from local_converter import converter_diagnostics, convert_part
        diagnostics = converter_diagnostics()
        step_convert = convert_part
        st.caption('Optional vendor reader. Install separately using install_convert3d_windows.bat. This selection uses Convert3D code.')
    ready = diagnostics['ready']
    auto_step = st.checkbox('Convert copied part files to STEP locally', value=ready, disabled=not ready, key=f'auto_step:{step_provider}', help='Exports the most recently saved configuration, preserving all supported solid bodies. Unsupported files are reported as failures. No automatic fallback to another converter.')
    if not ready:
        st.caption('The converter is not ready in this running app. Expand STEP converter diagnostics below.')
    with st.expander('STEP converter diagnostics'):
        st.json(diagnostics)
    drawing_control, drawing_status = drawing_capability()
    auto_pdf = st.checkbox('Automatically print drawings to PDF (experimental)', value=False, disabled=drawing_control is None,
                           help='Uses your installed eDrawings and Microsoft Print to PDF. Requires a signed-in Windows desktop and a first-run test.')
    pdf_paper = 'Tabloid'
    pdf_landscape = True
    if auto_pdf:
        pdf_paper = st.selectbox('Drawing PDF paper size', ['Tabloid', 'Letter', 'A3', 'A4'])
        pdf_landscape = st.checkbox('Landscape drawing PDFs', value=True)
        st.caption('All sheets are printed, scaled to fit the selected paper. Review the first PDF for correct views, sheets and sizing.')
    else:
        st.caption(drawing_status)
    st.caption('Parts can convert locally. Drawings can use eDrawings PDF printing. Referenced dependencies are not bundled automatically.')

def render_po():
    generation = st.session_state.get('upload_generation', 0)
    upload = st.file_uploader('Purchase order PDF', type=['pdf'], key=f'po_upload:{generation}')
    if upload is None:
        if 'last_download' in st.session_state:
            previous = st.session_state.last_download
            st.success(f'PO {previous["report"]["po"]} cleared after the download was requested. Ready for the next PO.')
            st.caption(f'A local copy is saved at {previous["archive"]}. You can download it again if needed.')
            try:
                zip_download(previous)
            except OSError as exc:
                st.warning(f'The previous ZIP is no longer available: {exc}')
        st.info('Upload a text-based PO PDF to begin. Scanned documents need OCR before uploading.')
        return
    try:
        number, items = parse_po(io.BytesIO(upload.getvalue()))
    except Exception as exc:
        st.error(str(exc))
        return
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
        return
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
                    option = st.selectbox(label, ['Skip'] + options, index=1 if len(options) == 1 else 0, key=f'file_choice:{generation}:{key[1]}:{part}:{suffix}')
                    if len(options) > 1:
                        st.warning(f'Multiple {label.lower()} matches: select the correct file or leave it skipped.')
                    if option != 'Skip':
                        chosen.append(Path(option))
            if not chosen:
                missing.append(part)
                st.warning('No files selected for this part.')
            selected[part] = chosen
    ack = st.checkbox('I checked the PO lines and selected the correct files. Process selected files even if some lines have no files.', key='review_ack')
    if st.button('Create PO folder and process files', disabled=not ack):
        if not destination.strip():
            st.error('Enter an output parent folder.')
            return
        if not any(selected.values()):
            st.error('Select at least one source file.')
            return
        try:
            output = validate_destination(root, destination)
            job = output / f'PO {number} Parts - {datetime.now():%Y%m%d-%H%M%S-%f}'
            job.mkdir(parents=True, exist_ok=False)
        except Exception as exc:
            st.error(str(exc))
            return
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
                            copied = copy_new(source, job / source.name)
                            result['copy'] = str(copied)
                            result['status'] = 'Copied'
                            st.write(f'{part}: {result["status"]}')
                        except Exception as exc:
                            result['status'] = f'Failed: {exc}'
                            st.error(f'{part}: {exc}')
                if auto_step:
                    existing_names = {p.name.casefold() for p in job.iterdir()}
                    for entry in list(results):
                        if entry['status'] != 'Copied' or Path(entry.get('copy', '')).suffix.lower() != '.sldprt':
                            continue
                        source = Path(entry['copy'])
                        if any((source.stem + extension).casefold() in existing_names for extension in ('.step', '.stp')):
                            st.write(f'{entry["part"]}: existing STEP was copied; conversion skipped.')
                            continue
                        target = job / (source.stem + '.step')
                        conversion = {'part': entry['part'], 'source': str(source), 'copy': '', 'status': ''}
                        results.append(conversion)
                        try:
                            st.write(f'{entry["part"]}: converting to STEP locally…')
                            metrics = step_convert(source, target)
                            conversion.update(copy=str(target), status='Converted STEP', validation=metrics)
                            existing_names.add(target.name.casefold())
                            st.write(f'{entry["part"]}: STEP created and solid geometry validated.')
                        except Exception as exc:
                            conversion['status'] = f'Conversion failed: {exc}'
                            st.error(f'{entry["part"]}: {exc}')
                if auto_pdf:
                    pdf_failure = None
                    existing_names = {p.name.casefold() for p in job.iterdir()}
                    for entry in list(results):
                        if entry['status'] != 'Copied' or Path(entry.get('copy', '')).suffix.lower() != '.slddrw':
                            continue
                        source = Path(entry['source'])
                        if (source.stem + '.pdf').casefold() in existing_names:
                            st.write(f'{entry["part"]}: existing PDF was copied; printing skipped.')
                            continue
                        target = job / (source.stem + '.pdf')
                        printing = {'part': entry['part'], 'source': str(source), 'copy': '', 'status': ''}
                        results.append(printing)
                        if pdf_failure:
                            printing['status'] = 'PDF printing skipped: an earlier drawing failed; use the manual PDF workflow.'
                            continue
                        try:
                            st.write(f'{entry["part"]}: printing all drawing sheets to PDF…')
                            metrics = convert_drawing(source, target, paper=pdf_paper, landscape=pdf_landscape)
                            printing.update(copy=str(target), status='Printed PDF', validation=metrics)
                            existing_names.add(target.name.casefold())
                            st.write(f'{entry["part"]}: PDF created, {metrics["pages"]} pages verified.')
                        except Exception as exc:
                            pdf_failure = str(exc)
                            printing['status'] = f'PDF printing failed: {exc}'
                            st.warning('Automatic PDF printing stopped for this batch. Remaining drawings are copied; existing PDFs are kept. Use the manual print/upload workflow for missing PDFs.')
                            st.error(f'{entry["part"]}: {exc}')
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
            archive = shutil.make_archive(str(job), 'zip', root_dir=job)
        except Exception as exc:
            st.error(f'Files were saved, but ZIP creation failed: {exc}')
        st.session_state.completed_job = {
            'folder': str(job), 'archive': archive, 'report': report,
        }

    if 'completed_job' in st.session_state:
        completed = st.session_state.completed_job
        st.subheader('Add drawing PDFs or other STEP exports (optional)')
        st.write('The selected files and any successful local STEP conversions are collected. Any failed or unprocessed drawings can still be printed manually in eDrawings. You can add these PDFs and any manually converted STEP files below.')
        st.markdown('1. For any unsupported parts, create STEP exports using another CAD tool if available.\n2. Open each copied `.slddrw` in **eDrawings**, choose **Print → Microsoft Print to PDF**, and include all required sheets. Check the PDF for missing views or cut-off content.\n3. Name each export after its exact PO part number, such as `C15999.step` or `C15999.pdf` (keep suffixes such as `_001`). Upload the exports here and click **Add exports and update ZIP**.')
        native_results = [r for r in completed['report']['results'] if r.get('copy') and Path(r['copy']).suffix.lower() in {'.sldprt', '.slddrw'}]
        if native_results:
            st.dataframe([{'Part': r['part'], 'File to convert': r['copy']} for r in native_results], hide_index=True, use_container_width=True)
        exports = st.file_uploader('Converted STEP and drawing PDF files', type=['step', 'stp', 'pdf'], accept_multiple_files=True, key=f'exports:{generation}:{completed["folder"]}')
        if st.button('Add exports and update ZIP', disabled=not exports):
            try:
                with st.spinner('Adding exports and rebuilding ZIP…'):
                    completed = add_converted_exports(completed, exports)
                    st.session_state.completed_job = completed
                st.success('Exports added. Your ZIP and processing report are updated.')
            except Exception as exc:
                st.error(f'Could not add exports: {exc}')
        st.subheader('Download collected files')
        st.write(f'Output folder: {completed["folder"]}')
        report = completed['report']
        st.dataframe(report['results'], use_container_width=True)
        if any(result['status'] not in {'Copied', 'Added export', 'Converted STEP', 'Printed PDF'} for result in report['results']):
            st.warning('Some files were missing, skipped, or failed. The ZIP contains the collected files; check the report for incomplete items.')
        if completed['archive']:
            try:
                st.caption('Downloading the ZIP clears the current PO and search results. Your folder settings and saved files stay available.')
                zip_download(completed, clear_po=True)
            except OSError as exc:
                st.error(f'Cannot read ZIP: {exc}. The copied files remain in the output folder.')
        st.download_button('Download processing report', json.dumps(report, indent=2), file_name=f'PO-{report["po"]}-report.json', mime='application/json', on_click='ignore')


from standalone import render_standalone

po_tab, part_tab = st.tabs(['Purchase orders', 'Part to STEP'])
with po_tab:
    render_po()
with part_tab:
    render_standalone(step_convert, ready, step_provider)
