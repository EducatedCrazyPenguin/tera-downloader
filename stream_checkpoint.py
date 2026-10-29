"""Durable website segments; records contain hashes and ownership, never URLs."""
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import re
import stat
import uuid
from transfer_state import RestartRequired
from terabox import Cancelled, safe_name

def fresh_stream(binding):
    return dict(kind='website',version=1,token=uuid.uuid4().hex,binding=binding,offset=0,
                file_id=[],phase='partial',manifest='',segments=[],joined={})

def identity(path):
    info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or path.is_symlink():
        raise RestartRequired('Saved stream ownership cannot be verified.')
    return [info.st_dev,info.st_ino]

def digest(path):
    with path.open('rb') as source:return hashlib.file_digest(source,'sha256').hexdigest()

class StreamCheckpoint:
    def __init__(self,record,folder,name,size,binding,commit,discard):
        self.record=deepcopy(record);self.commit=commit;self.discard=discard
        self.folder=Path(folder).resolve();self.target=self.folder/safe_name(name)
        r=self.record
        if (set(r)!=set(fresh_stream(binding)) or r['kind']!='website' or r['version']!=1
            or not isinstance(r['token'],str) or not re.fullmatch('[a-f0-9]{32}',r['token'])
            or r['binding']!=binding or type(r['offset']) is not int or r['offset']<0
            or r['phase'] not in ('partial','ready') or not isinstance(r['segments'],list)
            or len(r['segments'])>10000 or not isinstance(r['joined'],dict)
            or r['manifest'] and not re.fullmatch('[a-f0-9]{64}',r['manifest'])
            or not isinstance(r['file_id'],list) or len(r['file_id']) not in (0,2)):
            raise RestartRequired('Saved stream checkpoint is invalid.')
        total=0
        for part in r['segments']:
            if (set(part)!={'size','digest','file_id'} or type(part['size']) is not int or part['size']<=0
                or not re.fullmatch('[a-f0-9]{64}',part['digest']) or not isinstance(part['file_id'],list)
                or len(part['file_id'])!=2):raise RestartRequired('Saved segment record is invalid.')
            total+=part['size']
        if total!=r['offset']:raise RestartRequired('Saved stream byte count is invalid.')
        self.path=self.folder/('.tera-stream-'+r['token'])

    def save(self):
        if not self.commit(deepcopy(self.record)):raise Cancelled('Stream checkpoint was not accepted.')

    def owned(self):
        if not self.path.is_dir() or self.path.is_symlink() or self.path.is_junction():return False
        info=self.path.stat()
        return [info.st_dev,info.st_ino]==self.record['file_id']

    def prepare(self,manifest):
        if self.record['manifest'] and self.record['manifest']!=manifest:
            raise RestartRequired('The playlist changed. Saved segments were preserved; choose Restart from zero.')
        if not self.record['file_id']:
            self.folder.mkdir(parents=True,exist_ok=True);self.path.mkdir()
            info=self.path.stat();self.record['file_id']=[info.st_dev,info.st_ino]
            self.record['manifest']=manifest;self.save()
        if not self.owned():raise RestartRequired('Saved stream workspace ownership changed.')

    def verify(self,check,status):
        for index,part in enumerate(self.record['segments']):
            check();status(f'Verifying saved segments: {index+1} / {len(self.record["segments"])}')
            path=self.path/f'part{index:05d}.ts'
            try:valid=identity(path)==part['file_id'] and path.stat().st_size==part['size'] and digest(path)==part['digest']
            except OSError:valid=False
            if not valid:raise RestartRequired('A saved segment changed or is missing. Choose Restart from zero.')

    def segment(self,index,path):
        self.record['segments'].append(dict(size=path.stat().st_size,digest=digest(path),file_id=identity(path)))
        self.record['offset']+=path.stat().st_size;self.save()

    def reconcile(self):
        if self.record['phase']!='ready':return None
        item=self.record['joined']
        if set(item)!={'size','digest','file_id'}:raise RestartRequired('Invalid joined stream record.')
        for candidate in (self.target,self.path/'joined.ts'):
            if not candidate.exists():continue
            if candidate!=self.target and not self.owned():raise RestartRequired()
            if identity(candidate)!=item['file_id'] or candidate.stat().st_size!=item['size'] or digest(candidate)!=item['digest']:
                raise RestartRequired('The completed stream changed. Existing files were preserved.')
            if candidate!=self.target:candidate.rename(self.target)
            self.discard_owned();return self.target
        raise RestartRequired('The joined stream is missing.')

    def ready(self,path):
        self.record['joined']=dict(size=path.stat().st_size,digest=digest(path),file_id=identity(path))
        self.record['phase']='ready';self.save()

    def discard_owned(self):
        if not self.owned():return
        # Never recursively delete an unrecognised file or follow a replacement link.
        for path in self.path.iterdir():
            if not re.fullmatch(r'(part[0-9]{5}\.ts|incomplete|joined\.ts|join\.ffconcat|assembly\.log)',path.name):raise RestartRequired('Unknown file in stream workspace; preserved.')
            identity(path)
        for path in self.path.iterdir():path.unlink()
        self.path.rmdir()
