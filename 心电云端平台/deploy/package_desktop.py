"""Build an allowlisted Windows launcher. End users need no Python runtime."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
NAME = '心电工作台-Windows免安装.zip'


def build(output: Path) -> tuple[Path, str]:
    if os.name != 'nt':
        raise RuntimeError('Build on Windows using the .NET Framework compiler.')
    windows = Path(os.environ.get('WINDIR', r'C:\Windows'))
    compilers = [windows / 'Microsoft.NET' / directory / 'v4.0.30319/csc.exe'
                 for directory in ('Framework64', 'Framework')]
    compiler = next((path for path in compilers if path.is_file()), None)
    if compiler is None:
        raise RuntimeError('Windows .NET Framework 4.x compiler was not found.')
    source = ROOT / 'deploy/desktop'
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ecg-desktop-build-') as temporary:
        stage = Path(temporary)
        # Windows Vista+ supports PNG images inside ICO; reuse the project icon.
        png = (ROOT / 'web/icons/icon-192.png').read_bytes()
        icon = stage / 'app.ico'
        icon.write_bytes(struct.pack('<HHH', 0, 1, 1) +
                         struct.pack('<BBBBHHII', 192, 192, 0, 0, 1, 32, len(png), 22) + png)
        executable = stage / '心电工作台.exe'
        subprocess.run([
            str(compiler), '/nologo', '/target:winexe', '/platform:anycpu',
            '/optimize+', '/utf8output', '/codepage:65001',
            '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll', '/reference:System.Net.Http.dll',
            '/reference:System.Web.Extensions.dll',
            '/win32icon:' + str(icon), '/out:' + str(executable), str(source / 'Launcher.cs'), str(source / 'LauncherCore.cs'),
            str(source / 'UpdateCore.cs'),
        ], check=True)
        contents = {
            '心电工作台.exe': executable.read_bytes(),
            '使用说明.txt': ('\ufeff' + (source / '使用说明.txt').read_text(encoding='utf-8')).replace('\r\n', '\n').replace('\n', '\r\n').encode('utf-8'),
            '浏览器备用入口.url': b'[InternetShortcut]\r\nURL=https://62.234.150.104/\r\n',
            '连接与快捷方式.cmd': ('@echo off\r\nchcp 65001 >nul\r\nstart "" "%~dp0心电工作台.exe" --connection\r\n').encode('utf-8'),
        }
    manifest = ''.join(f'{hashlib.sha256(body).hexdigest()}  {name}\n'
                       for name, body in sorted(contents.items()))
    contents['文件校验.sha256'] = manifest.encode('utf-8-sig')
    archive = output / NAME
    with tempfile.NamedTemporaryFile(dir=output, suffix='.zip.tmp', delete=False) as handle:
        pending = Path(handle.name)
    try:
        with zipfile.ZipFile(pending, 'w', compression=zipfile.ZIP_DEFLATED) as bundle:
            for name, body in sorted(contents.items()):
                bundle.writestr('心电工作台/' + name, body)
        with zipfile.ZipFile(pending) as bundle:
            if bundle.testzip() is not None:
                raise RuntimeError('ZIP integrity verification failed.')
            if set(bundle.namelist()) != {'心电工作台/' + name for name in contents}:
                raise RuntimeError('Unexpected file in desktop package.')
        pending.replace(archive)
    finally:
        pending.unlink(missing_ok=True)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    (output / (NAME + '.sha256')).write_text(f'{digest}  {NAME}\n', encoding='utf-8-sig')
    return archive, digest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'deploy/dist/desktop')
    args = parser.parse_args()
    archive, digest = build(args.output.resolve())
    print(f'Archive: {archive}\nSHA256: {digest}')
