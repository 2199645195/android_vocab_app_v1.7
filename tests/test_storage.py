import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import storage

W = {'en':'ability','zh':'能力','pos':['n.'],'family':''}
def zipped(files, fmt='vocabtrainer-v17', listed=None):
    b = io.BytesIO()
    with zipfile.ZipFile(b, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('manifest.json', json.dumps({'format':fmt,'files':list(files) if listed is None else listed}))
        for k,v in files.items(): z.writestr(k,v if isinstance(v,bytes) else json.dumps(v))
    return b.getvalue()

class StorageTests(unittest.TestCase):
    def test_roundtrip_and_pre_restore_copy(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'progress.json'; p.write_text('{"old":7}')
            self.assertEqual(storage.restore(d,zipped({'progress.json':{'new':3}})),1)
            self.assertEqual(json.loads(p.read_text()),{'new':3})
            self.assertEqual(json.loads(zipfile.ZipFile(Path(d)/'before_restore.zip').read('progress.json')),{'old':7})
            self.assertEqual(storage.read_backup(storage.backup(d))['progress.json'],p.read_bytes())
    def test_legacy_missing_optional_files(self):
        self.assertIn('progress.json',storage.read_backup(zipped({'progress.json':{}},'vocabtrainer-v14',list(storage.FILES))))
    def test_reject_bad_inputs_before_writes(self):
        bad = [zipped({'../progress.json':{}}), zipped({'favorites.json':{}}),
               zipped({'review_schedule.json':{'x':{'word':W,'due':'bad'}}}),
               zipped({'progress.json':{'x':-1}}),zipped({'progress.json':{'x':True}}),
               zipped({'progress.json':{'x':1.2}}),zipped({'custom_units.json':{'Unit 1':[{'en':'bad'}]}}),
               zipped({'word_details.json':{'ability':{'ipa':[]}}}),
               zipped({'study_activity.json':{'2026-10-29':{'unique':{}}}}),
               zipped({'learning_settings.json':{'count':'unknown'}}), zipped({'learning_settings.json':{'unit':[]}}), zipped({'word_details.json':{'ability':{'manual_fields':7}}}), zipped({},listed=[]),
               zipped({'progress.json':{}},listed=[]),zipped({'progress.json':{}},fmt='other'),
               zipped({'wrong_words.jsonl':b'{broken'}),zipped({'stats.json':{'x':float('nan')}})]
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'progress.json';p.write_text('{"keep":9}')
            for payload in bad:
                with self.subTest(payload_size=len(payload)):
                    with self.assertRaises((ValueError,KeyError)):storage.restore(d,payload)
                    self.assertEqual(p.read_text(),'{"keep":9}')
                    self.assertFalse((Path(d)/'before_restore.zip').exists())
    def test_duplicate_entry(self):
        b=io.BytesIO(zipped({'progress.json':{}}))
        with zipfile.ZipFile(b,'a') as z:z.writestr('progress.json','{}')
        with self.assertRaises(ValueError):storage.read_backup(b.getvalue())
    def test_oversize(self):
        payload=zipped({'progress.json':b' '*(storage.MAX_FILE+1)})
        with self.assertRaises(ValueError):storage.read_backup(payload)
    def test_transaction_rolls_back_on_disk_failure(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ('progress.json','stats.json'):(Path(d)/name).write_text('{"old":1}')
            original=os.replace; calls=[]
            def fail_once(src,dst):
                if str(dst)==str(Path(d)/'stats.json') and not calls:
                    calls.append(1);raise OSError('simulated disk failure')
                return original(src,dst)
            with patch('storage.os.replace',side_effect=fail_once):
                with self.assertRaises(OSError):storage.restore(d,zipped({'progress.json':{'new':2},'stats.json':{'new':2}}))
            for name in ('progress.json','stats.json'): self.assertEqual(json.loads((Path(d)/name).read_text()),{'old':1})
    def test_atomic_write_failure_keeps_original(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x';p.write_bytes(b'old')
            with patch('storage.os.replace',side_effect=OSError('full')):
                with self.assertRaises(OSError):storage.atomic_write(str(p),b'new')
            self.assertEqual(p.read_bytes(),b'old');self.assertEqual(len(list(Path(d).iterdir())),1)

if __name__=='__main__':unittest.main(verbosity=2)
