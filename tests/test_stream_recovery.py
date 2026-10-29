import copy
import io
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch
from app_state import StateStore
from stream_checkpoint import StreamCheckpoint,fresh_stream
from transfer_state import RestartRequired
from terabox import Cancelled
from test_website_stream import PLAYER,MANIFEST,BODY,Response
from website_stream import WebsiteStream

class RecoveryTests(unittest.TestCase):
 def test_restart_only_fetches_missing_segment_and_checks_hashes(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);saved=[fresh_stream('binding')];hits=[]
   def commit(r):saved[0]=copy.deepcopy(r);return True
   def client(stop=None,interrupt=False):
    c=WebsiteStream(cancel=stop)
    def opened(url):
     if interrupt and url.endswith('second.ts'):raise Cancelled('Synthetic interrupt after first commit')
     hits.append(url.split('/')[-1]);return Response(MANIFEST if url.endswith('synthetic.vdo') else BODY)
    c.open=opened;return c
   c=client(interrupt=True);video=c.find_videos(PLAYER)[0]
   state=StreamCheckpoint(saved[0],root,video.name,0,'binding',commit,threading.Event())
   with self.assertRaises(Cancelled):c.download(video,root,checkpoint=state)
   # Cancellation between transfer and checkpoint cannot commit an incomplete segment;
   # the complete durable first segment is recorded before the next read.
   self.assertEqual(len(saved[0]['segments']),1)
   c=client();video=c.find_videos(PLAYER)[0]
   restored=StreamCheckpoint(saved[0],root,video.name,0,'binding',commit,threading.Event())
   with patch('website_stream.assemble',side_effect=lambda parts,durations,target,client:target.write_bytes(b''.join(p.read_bytes() for p in parts))):
    target=c.download(video,root,checkpoint=restored)
   self.assertEqual(target.read_bytes(),BODY*2)
   self.assertEqual(hits.count('first.ts'),1);self.assertEqual(hits.count('second.ts'),1)
   self.assertFalse(restored.path.exists())

 def test_changed_manifest_and_corrupt_segment_are_preserved(self):
  with tempfile.TemporaryDirectory() as folder:
   state=StreamCheckpoint(fresh_stream('binding'),folder,'movie.ts',0,'binding',lambda _:True,threading.Event())
   state.prepare('a'*64);part=state.path/'part00000.ts';part.write_bytes(BODY);state.segment(0,part)
   with self.assertRaises(RestartRequired):state.prepare('b'*64)
   part.write_bytes(BODY[:-1])
   with self.assertRaises(RestartRequired):state.verify(lambda:None,lambda _:None)
   self.assertTrue(part.exists())
   part.write_bytes(bytes([BODY[0]^1])+BODY[1:])
   with self.assertRaises(RestartRequired):state.verify(lambda:None,lambda _:None)

 def test_ready_rename_crash_is_reconciled_without_overwrite(self):
  with tempfile.TemporaryDirectory() as folder:
   state=StreamCheckpoint(fresh_stream('binding'),folder,'movie.ts',0,'binding',lambda _:True,threading.Event())
   state.prepare('a'*64);joined=state.path/'joined.ts';joined.write_bytes(BODY)
   state.ready(joined);joined.rename(state.target)
   self.assertEqual(state.reconcile(),state.target);self.assertEqual(state.target.read_bytes(),BODY)

 def test_migration_backup_and_provenance_encryption(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder)
   with StateStore(root) as store:
    store.db.execute('PRAGMA user_version=1')
    store.save_jobs([dict(id='job',link=PLAYER,origin_share='https://terabox.com/s/1private',status='pending')])
   with StateStore(root) as store:
    self.assertEqual(store.db.execute('PRAGMA user_version').fetchone()[0],2)
    self.assertEqual(store.load_jobs()[0]['origin_share'],'https://terabox.com/s/1private')
   self.assertTrue((root/'queue.before-v2.sqlite').is_file())
   self.assertNotIn(b'1private',(root/'queue.sqlite').read_bytes())


 def test_real_queue_exit_restore_keeps_committed_segment(self):
  import time
  from queue_manager import QueueManager
  from terabox import Cancelled
  entered=threading.Event();hits=[]
  class Local(WebsiteStream):
   block=True
   def open(self,url):
    if self.block and url.endswith('second.ts'):
     entered.set();self.cancel.wait(8);raise Cancelled('Synthetic shutdown')
    hits.append(url.split('/')[-1]);return Response(MANIFEST if url.endswith('synthetic.vdo') else BODY)
  with tempfile.TemporaryDirectory() as folder,patch('website_stream.assemble',side_effect=lambda parts,durations,target,client:target.write_bytes(b''.join(p.read_bytes() for p in parts))):
   root=Path(folder);manager=QueueManager(root/'state',Local)
   try:
    manager.request('download_now',links=[PLAYER],folder=str(root/'videos'),profile=None)
    self.assertTrue(entered.wait(5));manager.post('close');self.assertTrue(manager.closed.wait(5))
    Local.block=False;before=len(hits)
    manager=QueueManager(root/'state',Local)
    snapshot=manager.request('snapshot');self.assertFalse(snapshot['running']);self.assertEqual(len(hits),before)
    self.assertEqual(snapshot['jobs'][0]['checkpoint']['offset'],len(BODY))
    self.assertEqual(snapshot['jobs'][0]['cycle_attempts'],0)
    manager.request('start');end=time.monotonic()+5
    while time.monotonic()<end:
     snapshot=manager.request('snapshot')
     if snapshot['jobs'][0]['status']=='completed':break
     time.sleep(.01)
    self.assertEqual(snapshot['jobs'][0]['status'],'completed')
    self.assertEqual(hits.count('first.ts'),1);self.assertEqual(hits.count('second.ts'),1)
    self.assertEqual(snapshot['run_state']['bytes'],len(BODY)*2)
   finally:
    manager.post('close');self.assertTrue(manager.closed.wait(5))

 def test_refresh_once_and_ambiguous_source_holds(self):
  import time
  from queue_manager import QueueManager
  from terabox import DownloadError
  for ambiguous in (False,True):
   class Local(WebsiteStream):
    reads=0
    def find_videos(self,link):
     type(self).reads+=1
     if self.reads==2:raise DownloadError('Rejected test link',kind='expired',retry_after=0)
     return super().find_videos(link)
    def open(self,url):return Response(MANIFEST if url.endswith('synthetic.vdo') else BODY)
   with tempfile.TemporaryDirectory() as folder,patch('edge_helper.resolve_shares',return_value=[PLAYER,PLAYER] if ambiguous else [PLAYER]) as resolver,patch('website_stream.assemble',side_effect=lambda parts,durations,target,client:target.write_bytes(b''.join(p.read_bytes() for p in parts))):
    root=Path(folder);manager=QueueManager(root/'state',Local)
    try:
     manager.request('download_now',links=[PLAYER],origins={PLAYER:'https://terabox.com/s/1synthetic'},folder=str(root/'videos'),profile=None)
     end=time.monotonic()+6
     while time.monotonic()<end:
      snapshot=manager.request('snapshot')
      if snapshot['jobs'] and snapshot['jobs'][0]['status'] in ('completed','restart','failed'):break
      time.sleep(.01)
     self.assertEqual(snapshot['jobs'][0]['status'],'restart' if ambiguous else 'completed')
     resolver.assert_called_once()
     self.assertEqual(snapshot['jobs'][0]['cycle_attempts'],2)
    finally:
     manager.post('close');self.assertTrue(manager.closed.wait(5))


 def test_website_retry_budget_stays_bounded(self):
  from recovery import can_retry
  record={'kind':'website','offset':len(BODY),'phase':'partial'}
  self.assertTrue(can_retry('expired',1,record))
  self.assertFalse(can_retry('expired',2,record))
  self.assertFalse(can_retry('storage',1,record))

 def test_disk_full_preserves_completed_segments(self):
  from terabox import DownloadError
  with tempfile.TemporaryDirectory() as folder:
   c=WebsiteStream();c.open=lambda url:Response(MANIFEST if url.endswith('synthetic.vdo') else BODY)
   video=c.find_videos(PLAYER)[0]
   state=StreamCheckpoint(fresh_stream('binding'),folder,video.name,0,'binding',lambda _:True,threading.Event())
   state.prepare(c.manifest);part=state.path/'part00000.ts';part.write_bytes(BODY);state.segment(0,part)
   with patch('review_storage.available_space',return_value=0):
    with self.assertRaises(DownloadError) as error:c.download(video,folder,checkpoint=state)
   self.assertEqual(error.exception.kind,'storage');self.assertEqual(part.read_bytes(),BODY)
   self.assertEqual(state.record['offset'],len(BODY));self.assertFalse((state.path/'incomplete').exists())

if __name__=='__main__':unittest.main()
