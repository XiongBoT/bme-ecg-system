"""Exercise APK asset preparation without Android SDK, network or real records."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import io
from contextlib import redirect_stdout
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('ecg_android_build',ROOT/'android/build.py')
builder=importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)
sdk_spec=importlib.util.spec_from_file_location('ecg_android_sdk',ROOT/'android/install_sdk.py')
installer=importlib.util.module_from_spec(sdk_spec)
sdk_spec.loader.exec_module(installer)

class AndroidPackageTests(unittest.TestCase):
    def test_combined_mobile_and_desktop_navigation_has_unique_targets(self):
        class Elements(HTMLParser):
            def __init__(self):super().__init__();self.ids=[]
            def handle_starttag(self,tag,attrs):
                value=dict(attrs).get('id')
                if value:self.ids.append(value)
        page=Elements();page.feed((ROOT/'web/index.html').read_text(encoding='utf-8'))
        self.assertEqual(len(page.ids),len(set(page.ids)))
        for target in ('nav-records','nav-devices','nav-account','devices-heading','desktop-nav-records','desktop-nav-account','nav-device','nav-tasks','account-admin-group','account-security-group','filter-panel','filters-toggle','account-heading','results-heading','preview-report','report-dialog','report-print'):
            self.assertIn(target,page.ids)
        self.assertNotIn('nav-results',page.ids)

    def test_sdk_zero_exit_with_skipped_packages_is_a_failure_and_confirmation_has_no_bom(self):
        scratch=ROOT/'android/work';scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as folder:
            with patch.object(installer.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=b'Skipping packages: license not accepted')) as run:
                with redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError,'did not install'):
                    installer.install(Path(folder),Path(folder)/'install.log')
                sent=run.call_args.kwargs['input']
                self.assertTrue(sent.startswith(b'y\n'))
                self.assertNotIn(b'\xef\xbb\xbf',sent)

    def test_existing_complete_sdk_does_not_download_or_prompt_again(self):
        scratch=ROOT/'android/work';scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as folder:
            sdk=Path(folder)
            for name in installer.REQUIRED:
                target=sdk/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b'fixture')
            with patch.object(installer.subprocess,'run') as run, redirect_stdout(io.StringIO()):
                installer.install(sdk,sdk/'install.log')
                run.assert_not_called()

    def test_prepared_assets_use_native_save_and_do_not_register_a_worker(self):
        scratch=ROOT/'android/work';scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as folder:
            destination=Path(folder);builder.prepare_assets(destination)
            index=(destination/'web/index.html').read_text(encoding='utf-8')
            self.assertIn('data-native-app="android"',index)
            self.assertNotIn('src="/assets/pwa.js"',index)
            self.assertNotIn('rel="manifest"',index)
            self.assertEqual((destination/'web/app.js').read_bytes(),(ROOT/'web/app.js').read_bytes())
            self.assertEqual({p.relative_to(destination/'web').as_posix() for p in destination.rglob('*') if p.is_file()},set(builder.ASSETS))
            self.assertFalse(any(p.suffix in ('.sqlite','.jks','.json','.bin','.npz') for p in destination.rglob('*') if p.is_file()))

    def test_android_manifest_has_only_network_permission_and_no_backups(self):
        manifest=ET.parse(ROOT/'android/AndroidManifest.xml').getroot()
        ns='{http://schemas.android.com/apk/res/android}'
        self.assertEqual([p.get(ns+'name') for p in manifest.findall('uses-permission')],['android.permission.INTERNET'])
        app=manifest.find('application')
        self.assertEqual(app.get(ns+'usesCleartextTraffic'),'false')
        self.assertEqual(app.get(ns+'allowBackup'),'false')
        self.assertEqual(app.get(ns+'debuggable'),'false')
        self.assertEqual(manifest.find('uses-sdk').get(ns+'minSdkVersion'),'26')

if __name__=='__main__':unittest.main()
