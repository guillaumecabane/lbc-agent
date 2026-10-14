#!/usr/bin/env python3
import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path

SPEC=importlib.util.spec_from_file_location('watch',Path(__file__).resolve().parent/'leboncoin_event_watch.py')
watch=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(watch)
CUTOFF=datetime(2026,9,29,11,36,tzinfo=timezone.utc)


def snap(conv=None,ads=None):
    return {'captured_at':'2026-09-29T12:00:00+00:00','conversations':conv or {},'ads':ads or {}}


def conv(at='2026-09-29T11:54:02Z',out=False,msg='m2',text='Je veux l’écran',preview=None):
    return {'last_message_at':at,'preview':preview or text,'unseen':0,'latest_outgoing':out,'latest_message_id':msg,'latest_type':'ApiTextMessage','latest_text':text,'title':'Example item','partner':'Buyer'}

class WatchDiffTests(unittest.TestCase):
    def test_first_baseline_reports_only_post_audit_incoming(self):
        cur=snap({'new':conv(),'old':conv(at='2026-09-29T11:20:00Z',msg='m1')})
        out=watch.diff_events(cur,None,CUTOFF)
        self.assertEqual([e['conversation_id'] for e in out],['new'])

    def test_outgoing_message_is_ignored(self):
        prev=snap({'c':conv(at='2026-09-29T11:20:00Z',out=True,msg='m1')})
        cur=snap({'c':conv(out=True,msg='m2',text='Notre réponse')})
        self.assertEqual(watch.diff_events(cur,prev,CUTOFF),[])

    def test_new_incoming_message_is_reported(self):
        prev=snap({'c':conv(at='2026-09-29T11:20:00Z',msg='m1')})
        cur=snap({'c':conv(msg='m2')})
        out=watch.diff_events(cur,prev,CUTOFF)
        self.assertEqual(len(out),1); self.assertEqual(out[0]['text'],'Je veux l’écran')

    def test_same_latest_message_not_duplicated(self):
        prev=snap({'c':conv(at='2026-09-29T11:53:00Z',msg='m2',preview='old summary')})
        cur=snap({'c':conv(msg='m2',preview='new summary')})
        self.assertEqual(watch.diff_events(cur,prev,CUTOFF),[])

    def test_listing_status_change_and_removal_are_reported(self):
        prev=snap(ads={'1':{'title':'One','status':'active'},'2':{'title':'Two','status':'active'}})
        cur=snap(ads={'1':{'title':'One','status':'paused'}})
        out=watch.diff_events(cur,prev,CUTOFF)
        self.assertEqual(len(out),2)
        self.assertTrue(any('active → paused' in e['text'] for e in out))
        self.assertTrue(any('plus dans le catalogue' in e['text'] for e in out))

    def test_reappearing_old_conversation_is_not_replayed(self):
        prev=snap({})
        cur=snap({'c':conv(at='2026-09-29T10:00:00Z',msg='m1')})
        self.assertEqual(watch.diff_events(cur,prev,CUTOFF),[])

    def test_new_conversation_after_previous_snapshot_is_reported(self):
        prev=snap({})
        cur=snap({'c':conv(at='2026-09-29T12:05:00Z',msg='m1')})
        self.assertEqual(len(watch.diff_events(cur,prev,CUTOFF)),1)

    def test_render_is_silent_without_events(self):
        self.assertEqual(watch.render_alerts([]),'')

if __name__=='__main__': unittest.main(verbosity=2)
