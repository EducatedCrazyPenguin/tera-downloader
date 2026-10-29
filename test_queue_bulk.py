from dataclasses import asdict
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from app_state import StateStore
from queue_manager import Job,QueueManager
from tera_gui import queue_visible
from terabox import DownloadError

def jobs():
 return [Job(str(i),'https://terabox.com/s/1synthetic'+str(i),video={'name':f'video{i}.mp4','size':1,'fid':str(i)}) for i in range(5)]

class BulkTests(unittest.TestCase):
 def manager(self):
  manager=QueueManager.__new__(QueueManager);manager.jobs=jobs();manager.active=None;manager.review_active=None
  manager._save=Mock();manager._discard=Mock();manager.review_requested=set();manager.quick_requested=set()
  return manager

 def test_move_group_up_down_preserves_group_order(self):
  m=self.manager();m._handle('move',dict(job_ids=['2','3'],direction=-1))
  self.assertEqual([j.id for j in m.jobs],['0','2','3','1','4'])
  m._handle('move',dict(job_ids=['2','3'],direction=1))
  self.assertEqual([j.id for j in m.jobs],['0','1','2','3','4'])

 def test_move_next_precedes_waiting_retry_without_interrupting_active(self):
  m=self.manager();m.active='0';m.jobs[0].status='downloading';m.jobs[1].status='retry_wait'
  m._handle('move_next',dict(job_ids=['4','3']))
  self.assertEqual([j.id for j in m.jobs],['0','3','4','1','2'])
  self.assertEqual(m.active,'0');self.assertEqual(m.jobs[0].status,'downloading')

 def test_mixed_or_invalid_selection_changes_nothing(self):
  for action in ('move','move_next','remove'):
   m=self.manager();m.active='0';m.jobs[0].status='downloading'
   with self.assertRaises(DownloadError):m._handle(action,dict(job_ids=['2','0'],direction=-1))
   self.assertEqual([j.id for j in m.jobs],['0','1','2','3','4']);m._save.assert_not_called();m._discard.assert_not_called()
   with self.assertRaises(DownloadError):m._handle(action,dict(job_ids=['2','missing'],direction=-1))
   m._discard.assert_not_called()

 def test_bulk_remove_discards_only_selected_owned_state(self):
  m=self.manager();m._handle('remove',dict(job_ids=['1','3','1']))
  self.assertEqual([j.id for j in m.jobs],['0','2','4']);self.assertEqual(m._discard.call_count,2)

 def test_filters_are_view_only_and_keep_queue_order(self):
  data=[asdict(j) for j in jobs()];data[0]['status']='downloading';data[2]['status']='attention';data[3]['status']='retry_wait'
  self.assertEqual([j['id'] for j in queue_visible(data,'VIDEO','Pending','0')],['1','4'])
  self.assertEqual([j['id'] for j in queue_visible(data,'','Active','0')],['0'])
  self.assertEqual([j['id'] for j in queue_visible(data,'','Needs attention','0')],['2'])
  self.assertEqual([j['id'] for j in queue_visible(data,'','Waiting','0')],['3'])
  self.assertEqual([j['id'] for j in data],['0','1','2','3','4'])

 def test_real_queue_bulk_order_and_removal_survive_restart(self):
  with tempfile.TemporaryDirectory() as folder:
   with StateStore(folder) as store:store.save_jobs([asdict(j) for j in jobs()])
   m=QueueManager(Path(folder))
   try:
    m.request('move_next',job_ids=['3','4']);m.request('remove',job_ids=['1','2'])
   finally:m.post('close');self.assertTrue(m.closed.wait(5))
   m=QueueManager(Path(folder))
   try:
    state=m.request('snapshot');self.assertFalse(state['running'])
    self.assertEqual([j['id'] for j in state['jobs']],['3','4','0'])
   finally:m.post('close');self.assertTrue(m.closed.wait(5))

if __name__=='__main__':unittest.main()
