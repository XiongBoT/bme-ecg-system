"""Build an installable, signed APK using the official SDK, without Gradle downloads."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parent
PROJECT=ROOT.parent
WEB=PROJECT/'web'
ASSETS=('applications.js','health.js','health_core.js','health.css','navigation.css','index.html','app.js','workspace.js','devices.js','measurement.js','mobile.js',
        'heartlife_core.js','heartlife-connect.html','heartlife-connect.js','heartlife-connect.css',
        'workflow_core.js','review.js','tasks.html','operations.html','workflow-page.js','workflow.css',
        'annotations.js','annotations.css','backup-schedule.js',
        'physiology.js','physiology.css','experience_core.js','experience.js','experience.css',
        'connection.js','desktop_core.js','desktop.js','desktop.css',
        'style.css','workspace.css','measurement.css','mobile.css','pwa.css',
        'device-manager.html','device-manager.js','device-manager.css',
        'database-manager.html','database-manager.js','database-manager.css',
        'admin-common.js','admin.css',
        'icons/icon-192.png','icons/icon-512.png','icons/icon-maskable.png','icons/apple-touch-icon.png')

def prepare_assets(destination: Path):
    for name in ASSETS:
        source=WEB/name
        target=destination/'web'/name
        target.parent.mkdir(parents=True,exist_ok=True)
        if name.endswith('.html'):
            html=source.read_text(encoding='utf-8')
            html=html.replace('<html lang="zh-CN">','<html lang="zh-CN" data-native-app="android">')
            html=re.sub(r'<script src="/assets/pwa.js" defer></script>','',html)
            html=re.sub(r'<link rel="manifest"[^>]*>','',html)
            html=html.replace('</head>','<style>.app-access,#account-install,#login-download,#nav-download{display:none!important}</style></head>')
            target.write_text(html,encoding='utf-8',newline='\n')
        else: shutil.copyfile(source,target)
    # Ensure no linked asset is missing. Do not package data, credentials or fixtures.
    for name in ('index.html','device-manager.html','heartlife-connect.html'):
        for linked in re.findall(r'(?:src|href)="/assets/([^"?#]+)"',(destination/'web'/name).read_text(encoding='utf-8')):
            if not (destination/'web'/linked).is_file(): raise ValueError('Unpackaged asset: '+linked)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk',type=Path,default=os.getenv('ANDROID_HOME'))
    parser.add_argument('--jdk',type=Path,default=os.getenv('JAVA_HOME'))
    parser.add_argument('--build-tools',default='35.0.0')
    parser.add_argument('--api',default='35')
    parser.add_argument('--build-root',type=Path,help='ASCII temporary path for Windows Android tools')
    parser.add_argument('--signing-dir',type=Path,help='Reuse the existing private signing pair without copying it into a worktree')
    parser.add_argument('--prepare-only',action='store_true')
    args=parser.parse_args()
    work=args.build_root or (args.sdk.resolve()/'app-build' if os.name=='nt' and args.sdk else ROOT/'work')
    if os.name=='nt' and not args.prepare_only and not str(work).isascii():
        parser.error('Windows Android tools need an ASCII --build-root, for example D:/workspace/bme-android-build')
    work.mkdir(parents=True,exist_ok=True)
    build=Path(tempfile.mkdtemp(prefix='build-',dir=work))
    assets=build/'assets';prepare_assets(assets)
    if args.prepare_only:
        print('Prepared exact app assets:',assets)
        return
    if not args.sdk or not args.jdk: parser.error('Provide --sdk and --jdk (or ANDROID_HOME/JAVA_HOME)')
    tools=args.sdk/'build-tools'/args.build_tools
    android=args.sdk/'platforms'/('android-'+args.api)/'android.jar'
    suffix='.exe' if os.name=='nt' else ''
    aapt=tools/('aapt2'+suffix);align=tools/('zipalign'+suffix)
    java=args.jdk/'bin'/('java'+suffix); javac=args.jdk/'bin'/('javac'+suffix)
    keytool=args.jdk/'bin'/('keytool'+suffix)
    for path in (aapt,align,android,java,javac,keytool,tools/'lib/d8.jar',tools/'lib/apksigner.jar'):
        if not path.is_file(): parser.error('Missing build tool: '+str(path))
    def run(*command,env=None):
        result=subprocess.run([str(s) for s in command],cwd=build,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace')
        if result.returncode: raise RuntimeError(result.stdout+'\n'+result.stderr)
        return result.stdout+result.stderr
    res=build/'res';shutil.copytree(ROOT/'res',res)
    manifest=build/'AndroidManifest.xml';shutil.copyfile(ROOT/'AndroidManifest.xml',manifest)
    sources=build/'src';shutil.copytree(ROOT/'src',sources)
    (res/'drawable').mkdir(exist_ok=True)
    shutil.copyfile(WEB/'icons/icon-192.png',res/'drawable/app_icon.png')
    run(aapt,'compile','--dir',res,'-o',build/'resources.zip')
    apk=build/'unsigned.apk'
    run(aapt,'link','-o',apk,'-I',android,'--manifest',manifest,
        '-A',assets,'--min-sdk-version','26','--target-sdk-version','35',build/'resources.zip')
    classes=build/'classes';classes.mkdir()
    # javac needs the JDK's LambdaMetafactory while compiling Java 8 lambdas;
    # Android's platform stubs alone do not contain that compiler entry point.
    run(javac,'-J-Duser.language=en','-J-Duser.country=US','-encoding','UTF-8','--release','8','-classpath',android,
        '-d',classes,*sorted(sources.rglob('*.java')))
    dex=build/'dex';dex.mkdir()
    run(java,'-cp',tools/'lib/d8.jar','com.android.tools.r8.D8','--release','--min-api','26',
        '--lib',android,'--output',dex,*sorted(classes.rglob('*.class')))
    with zipfile.ZipFile(apk,'a',compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(dex.glob('*.dex')): archive.write(path,path.name)
    aligned=build/'aligned.apk';run(align,'-f','-p','4',apk,aligned)
    signing=args.signing_dir or ROOT/'work'/'signing'
    if args.signing_dir and not all((signing/name).is_file() for name in ('ecg-release.jks','store-password.txt')):
        raise ValueError('Explicit signing directory must contain the existing key/password pair.')
    signing.mkdir(parents=True,exist_ok=True)
    key=signing/'ecg-release.jks';password=signing/'store-password.txt'
    if key.exists() != password.exists(): raise ValueError('Incomplete signing pair; restore original key/password. Never replace an existing release key.')
    if not key.exists():
        password.write_text(secrets.token_urlsafe(48),encoding='ascii')
        try:
            run(keytool,'-genkeypair','-keystore',key,'-storetype','JKS','-alias','ecg-release',
                '-keyalg','RSA','-keysize','3072','-validity','10000',
                '-dname','CN=ECG Records, OU=Biomedical Engineering Project',
                '-storepass:file',password,'-keypass:file',password,'-noprompt')
        except Exception:
            if not key.exists(): password.unlink()
            raise
    output=ROOT/'dist';output.mkdir(exist_ok=True)
    signed=build/'ecg-records-1.1.1.apk'
    signing_env=os.environ.copy()
    signing_env['ECG_APK_SIGNING_PASSWORD']=password.read_text(encoding='ascii').strip()
    run(java,'-jar',tools/'lib/apksigner.jar','sign','--ks',key,'--ks-key-alias','ecg-release',
        '--ks-pass','env:ECG_APK_SIGNING_PASSWORD','--key-pass','env:ECG_APK_SIGNING_PASSWORD',
        '--v1-signing-enabled','true','--v2-signing-enabled','true','--out',signed,aligned,env=signing_env)
    verification=run(java,'-jar',tools/'lib/apksigner.jar','verify','--verbose','--print-certs',signed)
    metadata=run(aapt,'dump','badging',signed)
    run(align,'-c','-p','4',signed)
    with zipfile.ZipFile(signed) as archive:
        names=archive.namelist()
        assert 'classes.dex' in names and 'AndroidManifest.xml' in names
        assert not any('fixture' in n or 'preview' in n or 'credentials' in n for n in names)
        assert 'assets/web/mobile.js' in names
        assert 'assets/web/pwa.js' not in names
    final=output/signed.name
    shutil.copyfile(signed,final)
    digest=hashlib.sha256(final.read_bytes()).hexdigest()
    (output/(final.name+'.sha256')).write_text(digest+'  '+final.name+'\n',encoding='ascii')
    (output/'verification.txt').write_text(verification+'\n'+metadata,encoding='utf-8')
    (output/'build-info.json').write_text(json.dumps({'apk':final.name,'sha256':digest,'bytes':final.stat().st_size,'api':args.api,'build_tools':args.build_tools,'origin':'https://62.234.150.104','assets':list(ASSETS)},ensure_ascii=False,indent=2),encoding='utf-8')
    print('APK:',final)
    print('SHA256:',digest)
    print('Signature, alignment, manifest and asset checks passed. Device installation still requires testing.')

if __name__=='__main__':main()
