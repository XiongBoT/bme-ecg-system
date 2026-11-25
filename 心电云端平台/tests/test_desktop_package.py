"""Delivery checks for the Windows real-cloud launcher (no live credentials)."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'win32', 'Windows compiler required')
class DesktopPackageTests(unittest.TestCase):
    def test_launcher_connection_and_window_boundaries(self):
        compiler=Path(os.environ.get('WINDIR',r'C:\Windows'))/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        if not compiler.is_file():
            compiler=Path(os.environ.get('WINDIR',r'C:\Windows'))/'Microsoft.NET/Framework/v4.0.30319/csc.exe'
        with tempfile.TemporaryDirectory(prefix='ecg-launcher-tests-') as directory:
            executable=Path(directory)/'launcher-tests.exe'
            compile_result=subprocess.run([str(compiler),'/nologo','/target:exe','/utf8output','/codepage:65001',
                '/reference:System.Drawing.dll','/reference:System.Net.Http.dll','/reference:System.Web.Extensions.dll','/out:'+str(executable),
                str(ROOT/'deploy/desktop/LauncherCore.cs'),
                *[str(path) for path in sorted((ROOT/'deploy/desktop').glob('Update*.cs'))],
                str(ROOT/'tests/desktop_launcher_tests.cs'),str(ROOT/'tests/desktop_update_tests.cs')],capture_output=True,text=True,encoding='utf-8',errors='replace')
            self.assertEqual(compile_result.returncode,0,compile_result.stdout+compile_result.stderr)
            result=subprocess.run([str(executable)],capture_output=True,text=True,timeout=20,encoding='utf-8',errors='replace')
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_build_extract_and_verify_delivery_allowlist(self):
        with tempfile.TemporaryDirectory(prefix='心电 解压验证 ') as directory:
            output = Path(directory) / '带空格 output'
            result = subprocess.run(
                [sys.executable, str(ROOT / 'deploy/package_desktop.py'), '--output', str(output)],
                capture_output=True, text=True, encoding='utf-8', errors='replace',
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            archive = output / '心电工作台-Windows免安装.zip'
            expected = {'心电工作台.exe', '连接与快捷方式.cmd', '浏览器备用入口.url', '使用说明.txt', '文件校验.sha256'}
            with zipfile.ZipFile(archive) as bundle:
                self.assertIsNone(bundle.testzip())
                self.assertEqual(set(bundle.namelist()), {'心电工作台/' + p for p in expected})
                folder = Path(directory) / '中文 解压后'
                bundle.extractall(folder)
            app = folder / '心电工作台'
            self.assertTrue((app / '心电工作台.exe').read_bytes().startswith(b'MZ'))
            helper=(app/'连接与快捷方式.cmd').read_text(encoding='utf-8')
            self.assertIn('chcp 65001 >nul',helper)
            self.assertIn('"%~dp0心电工作台.exe" --connection',helper)
            shortcut = (app / '浏览器备用入口.url').read_text(encoding='ascii')
            self.assertIn('URL=https://62.234.150.104/', shortcut)
            for entry in (app / '文件校验.sha256').read_text(encoding='utf-8-sig').splitlines():
                digest, name = entry.split('  ', 1)
                self.assertEqual(hashlib.sha256((app / name).read_bytes()).hexdigest(), digest)
            self.assertEqual(
                (output / (archive.name + '.sha256')).read_text(encoding='utf-8-sig').split()[0],
                hashlib.sha256(archive.read_bytes()).hexdigest(),
            )


if __name__ == '__main__':
    unittest.main()
