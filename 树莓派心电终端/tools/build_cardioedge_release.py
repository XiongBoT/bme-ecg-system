"""Package current runtime + tests explicitly; never bundle private sessions or old models."""
from pathlib import Path
import argparse,hashlib,json,tarfile,io
from build_waveform_release import RUNTIME_FILES,TEST_FILES,SUPPORT_FILES
ROOT=Path(__file__).resolve().parents[1]
FILES=set(RUNTIME_FILES+TEST_FILES+SUPPORT_FILES)|{
    'device.py','start-device.sh','tools/configure_device_boot.py','tools/preview_device_ui.py',
    'tests/test_device_mode.py','tests/test_device_boot.py','docs/设备待机与日常使用.md',
    'cloud/__init__.py','cloud/service.py','cloud/uploader.py','cloud/protocol.py','cloud/remote_measurement.py',
    'ui/render_cache.py','ui/cloud_dialog.py','docs/自动连接与云端分析.txt',
    'tests/test_cloud.py','tests/test_cloud_ui.py','tools/ui_latency_probe.py',
    'classification_review.py','tests/test_classification_review.py','tests/test_classification_ui.py',
    'tests/test_classification_markers.py','tests/test_classification_presentation.py',
    'tools/preview_classification_ui.py','docs/分类呈现与复核说明.txt',
    'session_management.py','settings_store.py','storage_monitor.py','time_sync.py',
    'tests/test_session_management.py','tests/test_settings_store.py','tests/test_storage_monitor.py',
    'tests/test_time_sync.py','tests/test_storage_integration.py','tests/test_storage_ui.py',
    'tools/preview_storage_ui.py','docs/数据管理与设置说明.txt',
    'tests/test_cardioedge.py','tools/verify_cardioedge_board.py','tools/validate_cardioedge_stream.py',
    'tools/preview_interface.py','docs/三分类实时接入说明.txt',
    'cardioedge/__init__.py','cardioedge/stream.py','cardioedge/service.py','cardioedge/numpy_candidate.py',
    'cardioedge/portable_weights.npz','cardioedge/pi_parity_vectors.npz',
    'cardioedge/LICENSE.txt','cardioedge/LICENSE-LiteRT.txt','cardioedge/THIRD_PARTY_NOTICES.txt'}
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'dist/ecg-cardioedge-standby.tar.gz')
    output=parser.parse_args().output
    output.parent.mkdir(parents=True,exist_ok=True)
    contents={p:(ROOT/p).read_bytes() for p in sorted(FILES)}
    manifest={p:hashlib.sha256(b).hexdigest() for p,b in contents.items()}
    contents['CARDIOEDGE_MANIFEST.json']=json.dumps(manifest,indent=2).encode()
    with tarfile.open(output,'w:gz') as arc:
        for name,data in contents.items():
            info=tarfile.TarInfo('ecg_terminal/'+name);info.size=len(data);info.mode=0o644
            arc.addfile(info,io.BytesIO(data))
    print(output,output.stat().st_size,hashlib.sha256(output.read_bytes()).hexdigest())
