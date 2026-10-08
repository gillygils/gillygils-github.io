"""Upload and convert parts without a PO or a file-server search."""
import hashlib
import io
import json
import tempfile
import zipfile
from pathlib import Path, PureWindowsPath

from native_drawing.archive import MAX_FILE


def prepare_uploads(uploads):
    inputs=[]
    names=set()
    for upload in uploads:
        name=upload.name
        if (not name or Path(name).name!=name or PureWindowsPath(name).name!=name
                or Path(name).suffix.lower()!='.sldprt' or not Path(name).stem
                or any(character in name for character in '<>:"|?*\0')
                or name.endswith((' ','.'))):
            raise ValueError(f'Use a plain .sldprt filename without folders or special characters: {name!r}')
        target=Path(name).with_suffix('.step').name.casefold()
        if target in names:
            raise ValueError(f'Two uploads would create the same STEP filename: {name}. Rename one or select it separately.')
        names.add(target)
        if getattr(upload,'size',0)>MAX_FILE:
            raise ValueError(f'{name} exceeds the 64 MiB part limit.')
        data=upload.getvalue()
        if len(data)>MAX_FILE:
            raise ValueError(f'{name} exceeds the 64 MiB part limit.')
        inputs.append((name,data))
    return inputs


def convert_batch(inputs, converter, progress=None):
    outputs={}
    results=[]
    with tempfile.TemporaryDirectory(prefix='uploaded-parts-') as temp:
        root=Path(temp)
        source_dir,output_dir=root/'inputs',root/'outputs'
        source_dir.mkdir();output_dir.mkdir()
        for index,(name,data) in enumerate(inputs):
            if progress:progress(index,len(inputs),name,'Converting')
            result={'file':name,'status':'Failed'}
            try:
                source=source_dir/name
                source.write_bytes(data)
                target=output_dir/Path(name).with_suffix('.step').name
                metrics=converter(source,target)
                outputs[target.name]=target.read_bytes()
                result.update(status='Converted STEP',output=target.name,validation=metrics)
            except Exception as exc:
                result['error']=str(exc)
            results.append(result)
            if progress:progress(index+1,len(inputs),name,result['status'])
    report={'workflow':'standalone-part-conversion','results':results}
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        for name,data in outputs.items():archive.writestr(name,data)
        archive.writestr('report.json',json.dumps(report,indent=2))
    return {'outputs':outputs,'report':report,'zip':buffer.getvalue()}


def render_standalone(converter, ready, provider):
    import streamlit as st
    st.subheader('Convert parts to STEP')
    st.write('Upload one or more SolidWorks part files, convert them locally, then download the STEP files. No purchase order is needed.')
    st.caption('Choose files from your PC or Z: drive. The most recently saved configuration is exported, including all supported solid bodies. Your browser chooses where downloads are saved.')
    uploads=st.file_uploader('SolidWorks part files',type=['sldprt'],accept_multiple_files=True,key='standalone_parts')
    try:
        inputs=prepare_uploads(uploads or [])
    except ValueError as exc:
        st.session_state.pop('standalone_result',None)
        st.error(str(exc))
        return
    signature=(provider,tuple((name,hashlib.sha256(data).hexdigest()) for name,data in inputs))
    completed=st.session_state.get('standalone_result')
    if completed and completed['signature']!=signature:
        st.session_state.pop('standalone_result',None)
        completed=None
    if not ready:
        st.info('Install the selected STEP converter before converting. See the sidebar diagnostics.')
    if st.button('Convert uploaded parts to STEP',disabled=not inputs or not ready,type='primary'):
        meter=st.progress(0,text=f'0/{len(inputs)} parts complete')
        with st.status('Converting uploaded parts…',expanded=True) as status:
            def progress(done,total,name,state):
                meter.progress(done/total,text=f'{done}/{total} parts complete · {name} · {state}')
                if state!='Converting':st.write(f'{name}: {state}')
            completed=convert_batch(inputs,converter,progress)
            completed['signature']=signature
            st.session_state.standalone_result=completed
            count=len(completed['outputs'])
            status.update(label=f'Finished: {count}/{len(inputs)} parts converted',state='complete' if count==len(inputs) else 'error')
    if completed:
        results=completed['report']['results']
        st.dataframe([{'File':r['file'],'Status':r['status'],'Details':r.get('error',r.get('output',''))} for r in results],hide_index=True,use_container_width=True)
        if any(r['status']=='Failed' for r in results):
            st.warning('Some parts failed. Downloads contain only successful conversions; check the report for each failure.')
        if completed['outputs']:
            st.download_button('Download STEP files ZIP',completed['zip'],file_name='Converted STEP files.zip',mime='application/zip',on_click='ignore',type='primary')
            for name,data in completed['outputs'].items():
                st.download_button(f'Download {name}',data,file_name=name,mime='application/octet-stream',on_click='ignore',key=f'standalone_download:{name}')
        st.download_button('Download conversion report',json.dumps(completed['report'],indent=2),file_name='STEP conversion report.json',mime='application/json',on_click='ignore')
