"""Read backup files without modifying them; optional isolated restore verification."""
import argparse
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database_backup import digest_file, restore_backup


def plain_path(path):
    path = Path(path).absolute()
    if any(p.is_symlink() or (hasattr(p, 'is_junction') and p.is_junction())
           for p in (path, *path.parents)):
        raise ValueError('符号链接或目录联接不允许用于检查')
    return path


def audit(paths, keep_newest=0, verify=False, scratch=None):
    if type(keep_newest) is not int or keep_newest < 0:
        raise ValueError('keep_newest must be a nonnegative integer; zero keeps all')
    entries, seen = [], set()
    def inspect(path):
        key = str(Path(path).absolute())
        if key in seen: return
        seen.add(key)
        row = {'filename':Path(path).name,'status':'error','bytes':0,'candidate':False}
        entries.append(row)
        try:
            path = plain_path(path)
            if not path.is_file(): raise FileNotFoundError('备份文件缺失或不是普通文件')
            before = path.stat()
            row.update(bytes=before.st_size, modified=before.st_mtime, sha256=digest_file(path))
            if verify:
                # The established restore verifier checks manifest, chunks and SQLite,
                # and revokes credentials only in a new, disposable restored copy.
                with tempfile.TemporaryDirectory(prefix='ecg-backup-audit-', dir=scratch) as temp:
                    result = restore_backup(path, Path(temp)/'restored')
                    row['chunks_checked'] = result['chunks']
            after = path.stat()
            if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
                raise ValueError('检查期间备份发生变化，请重试')
            row['status'] = 'verified' if verify else 'not_verified'
        except Exception as error:
            # Public summary never includes absolute paths or database contents.
            row['error'] = type(error).__name__
            if isinstance(error, ValueError): row['reason'] = str(error)[:160]
    for original in paths:
        try:
            path = plain_path(original)
            if path.is_dir():
                files = sorted(path.glob('*.zip'))
                if not files: raise ValueError('目录中没有备份压缩包')
                for file in files: inspect(file)
            else: inspect(path)
        except (OSError, ValueError) as error:
            entries.append({'filename':Path(original).name,'status':'error','error':type(error).__name__,'bytes':0,'candidate':False})
    verified = sorted((r for r in entries if r['status']=='verified'), key=lambda r:(r['modified'],r['filename']), reverse=True)
    if keep_newest:
        for row in verified[keep_newest:]: row['candidate']=True
    return {'schema':1,'ok':bool(entries) and all(r['status']!='error' for r in entries),
            'verified':bool(entries) and all(r['status']=='verified' for r in entries),
            'retention':'keep_all' if not keep_newest else 'preview_only',
            'bytes':sum(r['bytes'] for r in entries),'candidate_bytes':sum(r['bytes'] for r in entries if r['candidate']),
            'files':entries,'deleted':0}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('paths', nargs='+', type=Path)
    parser.add_argument('--verify', action='store_true', help='Restore into disposable scratch and validate full contents')
    parser.add_argument('--keep-newest', type=int, default=0, help='Preview only; zero keeps all; only verified archives considered')
    parser.add_argument('--scratch', type=Path, help='Existing scratch directory with enough space for one uncompressed backup')
    args=parser.parse_args()
    if args.keep_newest < 0: parser.error('--keep-newest must be nonnegative')
    result=audit(args.paths,args.keep_newest,args.verify,args.scratch)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['ok'] else 1


if __name__=='__main__': raise SystemExit(main())
