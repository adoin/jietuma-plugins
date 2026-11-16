"""Shared validation for immutable plugin packages and marketplace snapshots."""
from __future__ import annotations
from functools import total_ordering
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import struct
import zipfile
from urllib.parse import quote, unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
IDENTITY = re.compile(r'[a-z0-9][a-z0-9._-]{0,63}\Z')
VERSION = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?\Z')
PLATFORMS = {'windows-x86_64': 'x86_64-pc-windows-msvc', 'windows-arm64': 'aarch64-pc-windows-msvc'}

@total_ordering
class Version:
    def __init__(self, value: str):
        match = VERSION.fullmatch(value) if isinstance(value,str) and len(value)<=128 else None
        if not match: raise ValueError(f'Invalid SemVer: {value}')
        self.numbers = tuple(int(match[i]) for i in (1,2,3))
        self.pre = tuple(match[4].split('.')) if match[4] else ()
        if any(p.isdigit() and len(p)>1 and p[0]=='0' for p in self.pre): raise ValueError('Leading zero in prerelease')
    def __eq__(self, other): return isinstance(other,Version) and (self.numbers,self.pre)==(other.numbers,other.pre)
    def __lt__(self, other):
        if self.numbers!=other.numbers:return self.numbers<other.numbers
        if not self.pre:return False
        if not other.pre:return True
        for a,b in zip(self.pre,other.pre):
            if a==b:continue
            if a.isdigit() and b.isdigit():return int(a)<int(b)
            if a.isdigit()!=b.isdigit():return a.isdigit()
            return a<b
        return len(self.pre)<len(other.pre)

def valid_host(value: str) -> bool:
    if not isinstance(value,str) or not value or len(value)>512 or len(value.split(','))>8:return False
    try:
        for part in value.split(','):
            match=re.fullmatch(r'(>=|<=|>|<|=)?\s*(\S+)',part.strip())
            if not match:return False
            Version(match[2])
        return True
    except ValueError:return False

def configuration(root=ROOT):
    data=json.loads((root/'market-config.json').read_text(encoding='utf-8'))
    if data.get('schema_version')!=2 or not valid_host(data.get('default_host')) or set(data.get('platforms',[]))!=set(PLATFORMS):raise ValueError('Invalid marketplace configuration')
    if any(not IDENTITY.fullmatch(x) for x in data.get('removed_plugin_ids',[])):raise ValueError('Invalid retired plugin identity')
    return data

def manifests(root=ROOT):
    config=configuration(root);result={}
    for path in sorted((root/'plugins').glob('*/plugin.json')):
        value=json.loads(path.read_text(encoding='utf-8'));identity=value.get('id','');Version(value.get('version',''))
        if not IDENTITY.fullmatch(identity) or identity!=path.parent.name or identity in result or value.get('api_version')!=2 or value.get('type')!='extension':raise ValueError(f'Invalid plugin manifest: {path}')
        value['host']=value.get('host',config['default_host'])
        if not valid_host(value['host']):raise ValueError(f'Invalid host requirement: {identity}')
        result[identity]=value
    if not result:raise ValueError('No plugin manifests')
    return result

def source_digest(identity: str, root=ROOT):
    paths=[root/'Cargo.toml',root/'Cargo.lock',root/'market-config.json',*sorted((root/'src').rglob('*.rs')),*sorted((root/'plugins'/identity).rglob('*'))]
    sha=hashlib.sha256()
    for path in paths:
        if path.is_file():sha.update(path.relative_to(root).as_posix().encode());sha.update(path.read_bytes())
    return sha.hexdigest()

def asset_name(identity,version,platform):return f'{identity}-{version}-{platform}.jtbplugin'
def snapshot_tag(revision,tag):return 'market/'+revision+'-'+hashlib.sha256(tag.encode()).hexdigest()[:12]
def canonical_bytes(data):return (json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode('utf-8')
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def verify_archive(path,entry):
    raw=Path(path).read_bytes()
    if len(raw)!=entry['size'] or hashlib.sha256(raw).hexdigest()!=entry['sha256']:raise ValueError('Archive digest mismatch')
    if raw[:4]==b'\0\0\1\0':
        count=struct.unpack_from('<H',raw,4)[0]
        if not 1<=count<=64 or len(raw)<6+16*count:raise ValueError('Invalid ICO prefix')
        end=6+16*count
        for i in range(count):
            size,offset=struct.unpack_from('<II',raw,6+16*i+8)
            if not size or offset<6+16*count or offset+size>1024*1024:raise ValueError('Invalid ICO bounds')
            end=max(end,offset+size)
        if raw[end:end+4]!=b'PK\3\4':raise ValueError('Invalid ZIP prefix')
    with zipfile.ZipFile(path) as archive:
        if len(archive.infolist())>128 or sum(x.file_size for x in archive.infolist())>128*1024**2:raise ValueError('Oversized package')
        seen=set()
        for info in archive.infolist():
            name=info.filename;parts=PurePosixPath(name).parts
            if not parts or name.startswith('/') or '..' in parts or '\\' in name or ':' in name or any(ord(c)<32 for c in name) or name.casefold() in seen or ((info.external_attr>>16)&0o170000)==0o120000:raise ValueError('Unsafe archive path')
            if len(parts)==1 and name.casefold() in ('.market-source.json','market-source.json','.disabled','disabled','.capture-filter','capture-filter'):raise ValueError('Reserved archive path')
            seen.add(name.casefold())
        value=json.loads(archive.read('plugin.json'))
        for key in ('id','version','host','platform'):
            if value.get(key)!=entry.get(key):raise ValueError('Archive manifest identity mismatch')
        if value.get('api_version')!=2 or value.get('type')!='extension':raise ValueError('Invalid package protocol')
        if value.get('command'):
            binary=archive.read(value['command'])
            if len(binary)<64 or binary[:2]!=b'MZ':raise ValueError('Invalid executable')
            offset=struct.unpack_from('<I',binary,60)[0]
            if offset+6>len(binary) or binary[offset:offset+4]!=b'PE\0\0' or struct.unpack_from('<H',binary,offset+4)[0]!=(0xAA64 if entry['platform']=='windows-arm64' else 0x8664):raise ValueError('Executable architecture mismatch')
    return value

def validate_catalog(data,repository_id):
    if data.get('schema_version')!=2 or data.get('repository_id')!=repository_id or not re.fullmatch('[a-f0-9]{40}',data.get('revision','')):raise ValueError('Marketplace repository identity mismatch')
    entries=data.get('plugins');seen=set()
    if not isinstance(entries,list) or len(entries)>4096:raise ValueError('Invalid marketplace entries')
    for entry in entries:
        identity=entry.get('id','');version=entry.get('version','');Version(version);platform=entry.get('platform')
        if not IDENTITY.fullmatch(identity) or platform not in PLATFORMS or not valid_host(entry.get('host')):raise ValueError('Invalid marketplace package')
        key=identity,version,platform
        if key in seen:raise ValueError('Duplicate marketplace package')
        seen.add(key)
        if entry.get('release_tag')!=f'{identity}/v{version}' or entry.get('asset')!=asset_name(*key):raise ValueError('Package tag or filename mismatch')
        if not isinstance(entry.get('asset_id'),int) or entry['asset_id']<=0 or not isinstance(entry.get('size'),int) or not 0<entry['size']<=64*1024**2 or not re.fullmatch('[a-f0-9]{64}',entry.get('sha256','')):raise ValueError('Invalid package checksum or identity')
        url=urlparse(entry.get('download_url',''))
        prefix='/releases/download/'
        if url.scheme!='https' or url.hostname!='github.com' or url.username or url.password or url.port not in (None,443) or url.query or url.fragment or prefix not in url.path:raise ValueError('Invalid package URL')
        owner_path,tail=unquote(url.path).split(prefix,1)
        if not re.fullmatch(r'/[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}',owner_path) or tail!=entry['release_tag']+'/'+entry['asset']:raise ValueError('Invalid package URL identity')
    return data
