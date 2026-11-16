"""Build selected independent plugins and emit .jtbplugin packages for a target platform."""
from __future__ import annotations
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import struct
import subprocess
import zipfile
from market_protocol import ROOT, PLATFORMS, asset_name, canonical_bytes, manifests


def package_plugin(manifest, executable, destination, notices, platform, root=ROOT):
    identity=manifest['id'];folder=root/'plugins'/identity
    data=dict(manifest);data['platform']=platform
    if executable is not None:
        pe=executable.read_bytes()
        if len(pe)<64 or pe[:2]!=b'MZ':raise ValueError('Invalid plugin executable')
        offset=struct.unpack_from('<I',pe,60)[0]
        if offset+6>len(pe) or pe[offset:offset+4]!=b'PE\0\0' or struct.unpack_from('<H',pe,offset+4)[0]!=(0xAA64 if platform=='windows-arm64' else 0x8664):raise ValueError('Executable architecture does not match platform')
    archive_bytes=io.BytesIO()
    with zipfile.ZipFile(archive_bytes,'w') as archive:
        written=set()
        def member(name,value,stored=False):
            path=PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:raise ValueError('Unsafe package path')
            if name.casefold() in written:return
            written.add(name.casefold())
            info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0));info.external_attr=0o100644<<16
            archive.writestr(info,value,compress_type=zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED)
        member('plugin.json',canonical_bytes(data))
        for name in dict.fromkeys(('icon.png','icon.svg','plugin.ico',manifest.get('icon','icon.png'))):
            path=folder/name
            if path.is_file():
                if path.is_symlink():raise ValueError('Linked plugin asset')
                member(name,path.read_bytes(),name=='plugin.ico')
        if executable is not None:member(manifest['command'],executable.read_bytes())
        seen=set()
        for entry in manifest.get('contributes',{}).get('toolbar',[]):
            name=entry.get('icon')
            if name and name not in seen:
                path=folder.joinpath(*PurePosixPath(name).parts)
                if not path.resolve().is_relative_to(folder.resolve()) or path.is_symlink():raise ValueError('Unsafe toolbar asset')
                member(name,path.read_bytes());seen.add(name)
        member('licenses/jietuma-plugins-LICENSE',(root/'LICENSE').read_bytes())
        member('licenses/THIRD_PARTY_LICENSES.txt',notices.encode('utf-8'))
    icon=folder/'plugin.ico';prefix=icon.read_bytes() if icon.is_file() else b''
    if len(prefix)>1024*1024:raise ValueError('Package icon exceeds limit')
    payload=prefix+archive_bytes.getvalue()
    if len(payload)>64*1024**2:raise ValueError('Package exceeds host limit')
    destination.mkdir(parents=True,exist_ok=True)
    name=asset_name(identity,manifest['version'],platform);(destination/name).write_bytes(payload)
    return {key:data[key] for key in ('id','version','name','host','platform')} | {
        'name_i18n':data.get('name_i18n',{}),'description':data.get('description',''),
        'description_i18n':data.get('description_i18n',{}),'asset':name,
        'sha256':hashlib.sha256(payload).hexdigest(),'size':len(payload)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plugin',action='append',default=[])
    parser.add_argument('--arch',choices=['x64','arm64'],default='x64')
    parser.add_argument('--plan',type=Path)
    args=parser.parse_args();items=manifests();ids=args.plugin or list(items)
    if args.plan:ids=json.loads(args.plan.read_text(encoding='utf-8'))['builds']
    if any(identity not in items for identity in ids):parser.error('Unknown plugin ID')
    if not ids:return
    platform='windows-arm64' if args.arch=='arm64' else 'windows-x86_64';target=PLATFORMS[platform]
    command=['cargo','build','--release','--locked','--target',target]
    for identity in ids:
        binary=items[identity].get('command')
        if binary:
            if PurePosixPath(binary).name!=binary or not binary.endswith('.exe'):raise ValueError('Official plugin command must be a root executable')
            command+=['--bin',Path(binary).stem]
    subprocess.run(command,cwd=ROOT,check=True)
    metadata=json.loads(subprocess.check_output(['cargo','metadata','--format-version','1','--locked'],cwd=ROOT))
    licenses=[]
    for crate in metadata['packages']:
        if not crate.get('source'):continue
        for path in sorted(Path(crate['manifest_path']).parent.glob('LICENSE*')):
            if path.is_file():licenses.append((path,f"{crate['name']} {crate['version']} / {path.name}"))
    notices='\n\n'.join(f"===== {name} =====\n{path.read_text(encoding='utf-8',errors='replace')}" for path,name in licenses)
    destination=ROOT/'dist'/platform;entries=[]
    for identity in ids:
        manifest=items[identity];executable=ROOT/'target'/target/'release'/manifest['command'] if manifest.get('command') else None
        entry=package_plugin(manifest,executable,destination,notices,platform);entries.append(entry);print(destination/entry['asset'])
    (destination/f'packaged-{platform}.json').write_bytes(canonical_bytes(entries))


if __name__=='__main__':main()
