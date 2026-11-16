import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import zipfile
import unittest
from unittest.mock import patch
from urllib.parse import quote
import market
from market_protocol import Version, canonical_bytes, source_digest, validate_catalog, verify_archive, snapshot_tag, source_digest_at_revision
from package import package_plugin

class API:
    def __init__(self):
        self.info={'id':7};self.repository='owner/plugins';self.rows=[];self.bytes={};self.commands=[];self.refsha='a'*40
    def releases(self):return self.rows
    def tag_object(self,tag):return {"type":"commit","sha":self.refsha}
    def create_tag(self,tag,revision):self.refsha=revision
    def create_release(self,tag):
        row={'id':99+len(self.rows),'tag_name':tag,'draft':True,'prerelease':False,'assets':[]}
        self.rows.append(row);self.commands.append(('create',row['id']));return row
    def upload_asset(self,release,path):
        row=next(r for r in self.rows if r['id']==release['id']);identity=1000+len(self.bytes);raw=path.read_bytes()
        asset={'id':identity,'name':path.name,'size':len(raw),'digest':'sha256:'+hashlib.sha256(raw).hexdigest(),
            'browser_download_url':'https://github.com/owner/plugins/releases/download/'+quote(row['tag_name'],safe='')+'/'+path.name}
        row['assets'].append(asset);self.bytes[identity]=raw;self.commands.append(('upload',release['id'],path.name));return asset
    def publish_release(self,release,prerelease=False,latest=False):
        row=next(r for r in self.rows if r['id']==release['id']);row.update(draft=False,prerelease=prerelease,published_at='2026-11-16T00:00:00Z')
        self.commands.append(('publish',release['id'],prerelease,latest));return row
    def binary(self,asset):return self.bytes[asset['id']]
    def json(self,path):
        if '/git/ref/tags/' in path:return {'object':{'type':'commit','sha':self.refsha}}
        raise AssertionError('Unexpected API lookup: '+path)

class MarketTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.folder=self.root/'plugins/fixture';self.folder.mkdir(parents=True)
        (self.root/'market-config.json').write_text(json.dumps({'schema_version':2,'default_host':'>=2.3.0,<3.0.0','platforms':['windows-x86_64','windows-arm64']}))
        (self.root/'Cargo.toml').write_text('fixture');(self.root/'Cargo.lock').write_text('fixture');(self.root/'LICENSE').write_text('MIT')
        self.item={'id':'fixture','name':'Fixture','version':'1.0.0','api_version':2,'type':'extension','contributes':{},'host':'>=2.3.0,<3.0.0'}
        (self.folder/'plugin.json').write_text(json.dumps(self.item));self.api=API();self.revision='a'*40
    def published(self,version='1.0.0'):
        item=self.item|{'version':version};entries=[];assets=[]
        for index,platform in enumerate(('windows-x86_64','windows-arm64')):
            entry=package_plugin(item,None,self.root/platform,'notices',platform,self.root);entries.append(entry)
            assets.append({'id':100+index,'name':entry['asset'],'size':entry['size'],'digest':'sha256:'+entry['sha256'],
                'browser_download_url':'https://github.com/owner/plugins/releases/download/'+quote('fixture/v'+version,safe='')+'/'+entry['asset']})
        record={'id':'fixture','version':version,'revision':self.revision,'source_digest':source_digest('fixture',self.root),'packages':entries}
        meta={'id':102,'name':'plugin-build.json'};self.api.bytes[102]=canonical_bytes(record)
        release={'id':1,'tag_name':'fixture/v'+version,'draft':False,'prerelease':False,'assets':assets+[meta]};self.api.rows.append(release)
        return release,entries
    def test_versions_follow_semver_precedence(self):
        self.assertGreater(Version('1.10.0'),Version('1.9.9'))
        self.assertGreater(Version('1.0.0'),Version('1.0.0-rc.9'))
        self.assertLess(Version('1.0.0-rc.9'),Version('1.0.0-rc.10'))
        self.assertEqual(Version('1.0.0+one'),Version('1.0.0+two'))
        for value in ['01.0.0','1.0.0-01','1.0','1.0.0-']:
            with self.assertRaises(ValueError):Version(value)
    def test_fresh_market_builds_current_independent_versions(self):
        value=market.plan(self.api,'v1.0.0',self.revision,self.root)
        self.assertEqual(value['builds'],['fixture']);self.assertFalse(value['complete'])
    def test_unchanged_published_version_is_reused_even_if_source_changed(self):
        self.published();(self.root/'Cargo.toml').write_text('changed without a version bump')
        with contextlib.redirect_stdout(io.StringIO()) as output:value=market.plan(self.api,'v1.0.1',self.revision,self.root)
        self.assertFalse(value['builds']);self.assertIn('without a version bump',output.getvalue())
    def test_published_package_record_cannot_claim_another_identity(self):
        release,_=self.published();value=json.loads(self.api.bytes[102]);value['packages'][0]['id']='another'
        self.api.bytes[102]=canonical_bytes(value)
        with self.assertRaisesRegex(ValueError,'identity mismatch'):market.package_entries(self.api,release,self.item)
    def test_mutated_published_asset_is_rejected(self):
        release,_=self.published();release['assets'][0]['digest']='sha256:'+'f'*64
        with self.assertRaisesRegex(ValueError,'changed'):market.plan(self.api,'v1.0.1',self.revision,self.root)
    def test_old_snapshot_rerun_does_not_roll_back_latest(self):
        value={'schema_version':2,'repository_id':7,'revision':self.revision,'source_tag':'v1.0.0','plugins':[]}
        self.api.bytes[200]=canonical_bytes(value)
        self.api.rows.append({'id':2,'tag_name':snapshot_tag(self.revision,'v1.0.0'),'draft':False,'prerelease':False,'assets':[{'id':200,'name':'plugin-market.json'}]})
        request=market.plan(self.api,'v1.0.0',self.revision,self.root);self.assertTrue(request['complete'])
        with contextlib.redirect_stdout(io.StringIO()):market.publish(self.api,request,self.root/'output',self.root)
        self.assertFalse(self.api.commands)
    def test_separate_tags_on_one_commit_get_distinct_snapshots(self):
        self.assertNotEqual(snapshot_tag(self.revision,'fixture/v1.0.0'),snapshot_tag(self.revision,'another/v1.0.0'))
    def test_existing_tags_are_never_moved_to_a_different_source(self):
        self.api.refsha='b'*40
        with patch('market.source_digest_at_revision',side_effect=['old','new']):
            with self.assertRaisesRegex(ValueError,'another revision'):market.ensure_release(self.api,'fixture/v1.0.0',self.revision)
    def test_newest_catalog_uses_publish_time(self):
        for identity,date in ((1,'2026-01-02T00:00:00Z'),(2,'2026-01-03T00:00:00Z')):
            value={'schema_version':2,'repository_id':7,'revision':str(identity)*40,'plugins':[]}
            self.api.bytes[identity]=canonical_bytes(value)
            self.api.rows.insert(0,{'id':identity,'published_at':date,'tag_name':f'market/{identity}','draft':False,'prerelease':False,'assets':[{'id':identity,'name':'plugin-market.json'}]})
        self.assertEqual(market.latest_catalog(self.api,self.api.rows)['revision'],'2'*40)
    def test_catalog_rejects_foreign_repository_duplicate_or_unsafe_url(self):
        release,entries=self.published();entry=entries[0]|{'asset_id':100,'release_tag':release['tag_name'],'download_url':release['assets'][0]['browser_download_url']}
        value={'schema_version':2,'repository_id':7,'revision':self.revision,'plugins':[entry]};validate_catalog(value,7)
        with self.assertRaises(ValueError):validate_catalog(value,8)
        duplicate=copy.deepcopy(value);duplicate['plugins'].append(entry)
        with self.assertRaises(ValueError):validate_catalog(duplicate,7)
        bad=copy.deepcopy(value);bad['plugins'][0]['download_url']='https://evil.example/plugin'
        with self.assertRaises(ValueError):validate_catalog(bad,7)
    def test_market_failure_preserves_successfully_published_packages(self):
        release,_=self.published();request=market.plan(self.api,'v1.0.0',self.revision,self.root)
        with patch('market.upload_draft',side_effect=RuntimeError('upload failed')):
            with self.assertRaisesRegex(RuntimeError,'upload failed'):market.publish(self.api,request,self.root/'output',self.root)
        self.assertFalse(release['draft']);self.assertIn(release,self.api.rows)
    def test_packaging_shared_icons_does_not_duplicate_zip_members(self):
        (self.folder/'icon.png').write_bytes(b'fixture')
        value=self.item|{'icon':'icon.png','contributes':{'toolbar':[{'icon':'icon.png'}]}}
        entry=package_plugin(value,None,self.root/'built','notices','windows-x86_64',self.root)
        with zipfile.ZipFile(self.root/'built'/entry['asset']) as archive:self.assertEqual(archive.namelist().count('icon.png'),1)
    def test_publisher_rejects_reserved_and_traversal_archive_members(self):
        for name in ('.market-source.json','.capture-filter','../outside'):
            path=self.root/'bad.jtbplugin'
            with zipfile.ZipFile(path,'w') as archive:
                archive.writestr('plugin.json',canonical_bytes(self.item|{'platform':'windows-x86_64'}));archive.writestr(name,b'bad')
            raw=path.read_bytes();entry=self.item|{'platform':'windows-x86_64','size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
            with self.assertRaises(ValueError):verify_archive(path,entry)
    def test_missing_tag_is_created_before_drafting_release(self):
        self.api.refsha=None
        def tag_object(tag):return None if self.api.refsha is None else {'type':'commit','sha':self.api.refsha}
        self.api.tag_object=tag_object
        market.ensure_release(self.api,'fixture/v1.0.0',self.revision)
        self.assertEqual(self.api.refsha,self.revision)
    def test_first_publication_uses_draft_ids_without_tag_lookup(self):
        request=market.plan(self.api,'v1.0.0',self.revision,self.root)
        output=self.root/'output'
        for platform in ('windows-x86_64','windows-arm64'):
            folder=output/platform;entry=package_plugin(self.item,None,folder,'notices',platform,self.root)
            (folder/f'packaged-{platform}.json').write_bytes(canonical_bytes([entry]))
        with contextlib.redirect_stdout(io.StringIO()):market.publish(self.api,request,output,self.root)
        self.assertTrue(all(not row['draft'] for row in self.api.rows))
        value=market.latest_catalog(self.api,self.api.rows);self.assertEqual(len(value['plugins']),2)
        self.assertEqual([c for c in self.api.commands if c[0]=='publish'][-1][-1],True)
        # Completed snapshot retries must neither upload nor reset latest.
        self.api.commands=[]
        with contextlib.redirect_stdout(io.StringIO()):market.publish(self.api,request,output,self.root)
        self.assertFalse(self.api.commands)
    def test_resume_existing_draft_does_not_create_another_release(self):
        draft=self.api.create_release('fixture/v1.0.0');self.api.commands=[]
        result=market.ensure_release(self.api,'fixture/v1.0.0',self.revision,self.root)
        self.assertEqual(result['id'],draft['id']);self.assertFalse(self.api.commands)
    def test_publisher_only_repair_preserves_original_tag_and_source_commit(self):
        def git(*args):return subprocess.check_output(['git',*args],cwd=self.root,stderr=subprocess.PIPE).decode().strip()
        def commit():
            git('add','.');git('-c','user.name=Market Test','-c','user.email=test@example.invalid','commit','-qm','fixture');return git('rev-parse','HEAD')
        (self.root/'src').mkdir();(self.root/'src/fixture.rs').write_text('fn main() {}')
        git('init');old=commit()
        (self.root/'publisher.py').write_text('release repair');new=commit()
        self.assertEqual(source_digest_at_revision('fixture',old,self.root),source_digest_at_revision('fixture',new,self.root))
        self.api.refsha=old;draft=self.api.create_release('fixture/v1.0.0')
        result=market.ensure_release(self.api,'fixture/v1.0.0',new,self.root)
        self.assertEqual(result['_source_revision'],old);self.assertEqual(self.api.refsha,old)
        (self.root/'src/fixture.rs').write_text('fn main() { panic!(); }');changed=commit()
        with self.assertRaisesRegex(ValueError,'different plugin sources'):market.ensure_release(self.api,'fixture/v1.0.0',changed,self.root)
        with self.assertRaisesRegex(ValueError,'another revision'):market.ensure_release(self.api,'market/snapshot',new,self.root)
    def test_payload_architecture_and_manifest_are_validated(self):
        executable=self.root/'fixture.exe';binary=bytearray(96);binary[:2]=b'MZ';struct.pack_into('<I',binary,60,64);binary[64:68]=b'PE\0\0';struct.pack_into('<H',binary,68,0x8664);executable.write_bytes(binary)
        entry=package_plugin(self.item|{'command':'fixture.exe'},executable,self.root/'built','notices','windows-x86_64',self.root)
        path=self.root/'built'/entry['asset'];verify_archive(path,entry)
        wrong=entry|{'host':'>=9.0.0'}
        with self.assertRaises(ValueError):verify_archive(path,wrong)
        with self.assertRaises(ValueError):package_plugin(self.item|{'command':'fixture.exe'},executable,self.root/'arm','notices','windows-arm64',self.root)

if __name__=='__main__':unittest.main()
