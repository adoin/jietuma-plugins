"""Tag-only marketplace planning and idempotent, immutable GitHub publishing."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from urllib.parse import quote
from market_protocol import *

class GitHub:
    def __init__(self, repository):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repository):raise ValueError('Invalid repository')
        self.repository=repository
        self.info=self.json(f'repos/{repository}')
    def json(self,path):return json.loads(subprocess.check_output(['gh','api',path],encoding='utf-8'))
    def binary(self,asset):
        value=subprocess.check_output(['gh','api',f'repos/{self.repository}/releases/assets/{asset["id"]}','-H','Accept: application/octet-stream'])
        if len(value)>4*1024**2:raise ValueError('Market metadata is too large')
        if asset.get('digest') and asset['digest']!='sha256:'+hashlib.sha256(value).hexdigest():raise ValueError('GitHub metadata digest mismatch')
        return value
    def tag_object(self,tag):
        result=subprocess.run(['gh','api',f'repos/{self.repository}/git/ref/tags/{quote(tag,safe="")}'],capture_output=True,text=True,encoding='utf-8')
        if result.returncode:
            if 'HTTP 404' in result.stderr:return None
            raise RuntimeError('Could not resolve release tag: '+result.stderr.strip())
        return json.loads(result.stdout)['object']
    def create_tag(self,tag,revision):
        subprocess.run(['gh','api','--method','POST',f'repos/{self.repository}/git/refs','-f','ref=refs/tags/'+tag,'-f','sha='+revision],check=True,stdout=subprocess.DEVNULL)
    def releases(self):
        result=[]
        for page in range(1,11):
            rows=self.json(f'repos/{self.repository}/releases?per_page=100&page={page}');result+=rows
            if len(rows)<100:break
        return result
    def command(self,*args):subprocess.run(['gh',*args,'--repo',self.repository],check=True)

def metadata_asset(release,name):
    values=[a for a in release.get('assets',[]) if a['name']==name]
    if len(values)>1:raise ValueError('Duplicate release asset')
    return values[0] if values else None

def latest_catalog(api,releases):
    candidates=sorted((r for r in releases if not r['draft'] and not r['prerelease'] and metadata_asset(r,'plugin-market.json')),
                      key=lambda r:(r.get('published_at',''),r['id']),reverse=True)
    return validate_catalog(json.loads(api.binary(metadata_asset(candidates[0],'plugin-market.json'))),api.info['id']) if candidates else None

def selected_plugins(tag,items):
    from check_release_version import validate
    plugin,version=validate(tag,{key:value['version'] for key,value in items.items()})
    selected=[plugin] if plugin else list(items)
    if Version(version).pre and any(not Version(items[key]['version']).pre for key in selected):raise ValueError('Preview tags require prerelease versions in each selected plugin manifest')
    return selected

def package_entries(api,release,item,allow_missing=False):
    meta=metadata_asset(release,'plugin-build.json')
    if not meta:
        if allow_missing:return None
        raise ValueError(f'Published {release["tag_name"]} lacks immutable build metadata; publish a new version')
    record=json.loads(api.binary(meta))
    if record.get('id')!=item['id'] or record.get('version')!=item['version'] or not re.fullmatch('[a-f0-9]{64}',record.get('source_digest','')):raise ValueError('Plugin build identity mismatch')
    result=[]
    for entry in record.get('packages',[]):
        if entry.get('id')!=item['id'] or entry.get('version')!=item['version']:raise ValueError('Plugin package record identity mismatch')
        asset=metadata_asset(release,entry['asset'])
        if not asset or asset['size']!=entry['size'] or (asset.get('digest') and asset['digest']!='sha256:'+entry['sha256']):raise ValueError('Published plugin asset was changed')
        result.append(entry|{'asset_id':asset['id'],'download_url':asset['browser_download_url'],'release_tag':release['tag_name']})
    if {p['platform'] for p in result}!=set(PLATFORMS):raise ValueError('Plugin release has incomplete platforms')
    validate_catalog({'schema_version':2,'repository_id':api.info['id'],'revision':record['revision'],'plugins':result},api.info['id'])
    return record,result

def plan(api,tag,revision,root=ROOT):
    if not re.fullmatch('[a-f0-9]{40}',revision):raise ValueError('Invalid source revision')
    items=manifests(root);selected=selected_plugins(tag,items);releases=api.releases();by_tag={r['tag_name']:r for r in releases}
    snapshot=snapshot_tag(revision,tag)
    if snapshot in by_tag and not by_tag[snapshot]['draft']:
        existing=validate_catalog(json.loads(api.binary(metadata_asset(by_tag[snapshot],'plugin-market.json'))),api.info['id'])
        if existing['revision']!=revision or existing.get('source_tag')!=tag:raise ValueError('Snapshot identity conflict')
        return {'tag':tag,'revision':revision,'repository_id':api.info['id'],'builds':[],'selected':selected,'complete':True}
    previous=latest_catalog(api,releases)
    builds=[]
    for identity in selected:
        item=items[identity];version=Version(item['version'])
        prior=[Version(e['version']) for e in (previous or {}).get('plugins',[]) if e['id']==identity and (version.pre or not Version(e['version']).pre)]
        if prior and version<max(prior):raise ValueError(f'Version downgrade rejected: {identity}')
        release=by_tag.get(f'{identity}/v{item["version"]}')
        if release and not release['draft']:
            record,_=package_entries(api,release,item)
            if record['source_digest']!=source_digest(identity,root):print(f'Warning: {identity} source changed without a version bump; reusing its published package')
        else:builds.append(identity)
    return {'tag':tag,'revision':revision,'repository_id':api.info['id'],'builds':builds,'selected':selected,'complete':False}

def ensure_release(api,tag,revision,prerelease=False):
    release=next((r for r in api.releases() if r['tag_name']==tag),None)
    if release and not release['draft']:return release
    obj=api.tag_object(tag)
    if obj is None:
        api.create_tag(tag,revision);obj=api.tag_object(tag)
    for _ in range(4):
        if obj['type']!='tag':break
        obj=api.json(f'repos/{api.repository}/git/tags/{obj["sha"]}')['object']
    if obj['type']!='commit' or obj['sha']!=revision:raise ValueError('Existing tag points to another revision; publish a new version')
    if not release:
        api.command('release','create',tag,'--verify-tag','--draft','--title',tag,'--notes','Plugin package release.' if not tag.startswith('market/') else 'Complete plugin marketplace snapshot.')
        release=api.json(f'repos/{api.repository}/releases/tags/{quote(tag,safe="")}')
    return release


def upload_draft(api,release,path):
    asset=metadata_asset(release,path.name)
    if asset:
        if not release['draft']:
            if asset.get('digest')!='sha256:'+digest(path):raise ValueError('Refusing to overwrite a published asset')
            return
        # Only an unpublished draft may be repaired after an interrupted upload.
        subprocess.run(['gh','api','--method','DELETE',f'repos/{api.repository}/releases/assets/{asset["id"]}'],check=True)
    api.command('release','upload',release['tag_name'],str(path))

def publish(api,request,directory,root=ROOT):
    if request['repository_id']!=api.info['id']:raise ValueError('Publishing repository identity mismatch')
    tag=request['tag'];revision=request['revision'];items=manifests(root);snapshot=snapshot_tag(revision,tag)
    rows=api.releases();already=next((r for r in rows if r['tag_name']==snapshot and not r['draft']),None)
    if already:
        value=validate_catalog(json.loads(api.binary(metadata_asset(already,'plugin-market.json'))),api.info['id'])
        if value.get('revision')!=revision or value.get('source_tag')!=tag:raise ValueError('Existing snapshot does not match this tag')
        print('Marketplace snapshot was already published; leaving latest unchanged');return
    packaged={}
    for path in directory.rglob('packaged-*.json'):
        for entry in json.loads(path.read_text(encoding='utf-8')):
            key=(entry['id'],entry['platform'])
            if key in packaged:raise ValueError('Duplicate packaged platform')
            archive=path.parent/entry['asset']
            verify_archive(archive,entry)
            if entry['id'] not in request['builds'] or entry['version']!=items[entry['id']]['version'] or entry['host']!=items[entry['id']]['host']:raise ValueError('Built package does not match release plan')
            packaged[key]=(entry,archive)
    for identity in request['selected']:
        item=items[identity];version=item['version'];release=ensure_release(api,f'{identity}/v{version}',revision)
        if not release['draft']:
            package_entries(api,release,item);continue
        entries=[]
        for platform in PLATFORMS:
            if (identity,platform) not in packaged:raise ValueError(f'Missing built package: {identity} {platform}')
            entry,archive=packaged[identity,platform];entries.append(entry);upload_draft(api,release,archive)
        record={'id':identity,'version':version,'revision':revision,'source_digest':source_digest(identity,root),'packages':entries}
        info=directory/f'{identity}-build-info'/ 'plugin-build.json';info.parent.mkdir(parents=True,exist_ok=True);info.write_bytes(canonical_bytes(record));upload_draft(api,release,info)
        prerelease=bool(Version(version).pre)
        api.command('release','edit',release['tag_name'],'--draft=false','--prerelease='+str(prerelease).lower(),'--latest=false')
    # Read the current market only after package publishing; partial successes remain reusable.
    rows=api.releases();previous=latest_catalog(api,rows);entries={(e['id'],e['version'],e['platform']):e for e in (previous or {}).get('plugins',[])}
    icons=(previous or {}).get('icons',{}).copy()
    for identity in request['selected']:
        item=items[identity];release=next(r for r in rows if r['tag_name']==f'{identity}/v{item["version"]}')
        _,published=package_entries(api,release,item)
        for entry in published:entries[entry['id'],entry['version'],entry['platform']]=entry
        icon=root/'plugins'/identity/'icon.png'
        if icon.is_file():
            import base64
            raw=icon.read_bytes()
            if len(raw)>65536:raise ValueError('Market icon is too large')
            icons[identity]=base64.b64encode(raw).decode()
    removed=set(configuration(root).get('removed_plugin_ids',[]))
    value={'schema_version':2,'repository_id':api.info['id'],'revision':revision,'source_tag':tag,
           'plugins':[entry for key,entry in sorted(entries.items()) if key[0] not in removed],
           'icons':{key:icon for key,icon in icons.items() if key not in removed}}
    validate_catalog(value,api.info['id']);body=canonical_bytes(value)
    if len(body)>4*1024**2:raise ValueError('Market snapshot exceeds client size limit')
    path=directory/'market-output'/'plugin-market.json';path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(body)
    release=ensure_release(api,snapshot,revision);upload_draft(api,release,path)
    checksum=path.with_suffix('.json.sha256');checksum.write_text(hashlib.sha256(body).hexdigest()+'  plugin-market.json\n',encoding='utf-8');upload_draft(api,release,checksum)
    api.command('release','edit',snapshot,'--draft=false','--latest')
    print(f'Published marketplace: {snapshot}')

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['plan','publish'])
    parser.add_argument('--repo',default=os.environ.get('GITHUB_REPOSITORY'));parser.add_argument('--tag',default=os.environ.get('GITHUB_REF_NAME'))
    parser.add_argument('--revision',default=os.environ.get('GITHUB_SHA'));parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--directory',type=Path);parser.add_argument('--github-output',type=Path);args=parser.parse_args();api=GitHub(args.repo)
    if args.command=='plan':
        value=plan(api,args.tag,args.revision);args.plan.write_bytes(canonical_bytes(value))
        if args.github_output:
            with args.github_output.open('a',encoding='utf-8') as out:out.write('build='+str(bool(value['builds'])).lower()+'\n')
        print(json.dumps(value,ensure_ascii=False))
    else:
        value=json.loads(args.plan.read_text(encoding='utf-8'))
        head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,encoding='utf-8').strip()
        if head!=value['revision'] or (args.revision and args.revision!=head):raise ValueError('Checkout differs from the release plan')
        if args.tag and args.tag!=value['tag']:raise ValueError('Trigger tag differs from the release plan')
        publish(api,value,args.directory)

if __name__=='__main__':main()
