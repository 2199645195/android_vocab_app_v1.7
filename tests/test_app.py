"""Real Kivy widgets, with network/audio disabled for repeatable regression tests."""
import os
os.environ.setdefault('KIVY_NO_ARGS','1')
os.environ.setdefault('KIVY_NO_CONSOLELOG','1')
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import main as m
from kivy.core.window import Window
from kivy.clock import Clock
Window.hide()
W={'en':'ability','zh':'能力','pos':['n.'],'family':''}

class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.app_patch=patch.object(m.App,'get_running_app',return_value=SimpleNamespace(user_data_dir=self.temp.name))
        self.app_patch.start()
        self.network=patch.object(m.WordInfoFetcher,'request');self.network.start()
        self.audio=patch.object(m.CachedWordAudio,'speak',return_value=True);self.audio.start()
        self.ui=m.VocabTrainer()
        self.ui.show_popup=lambda *a:None
    def tearDown(self):
        self.ui.clear()
        self.ui.word_info_fetcher.closed=True
        self.ui.word_info_fetcher.executor.shutdown(wait=False)
        Window.unbind(on_keyboard=self.ui._on_keyboard)
        self.audio.stop();self.network.stop();self.app_patch.stop();self.temp.cleanup()
    def test_all_five_pages(self):
        for tab in ('home','library','wrong','stats','settings'):
            self.ui._change_tab(tab);Clock.tick()
            self.assertEqual(self.ui.screen_mode,'menu')
    def test_all_quiz_modes(self):
        for mode in m.SETTINGS['mode']:
            self.ui.ui_mode_text=mode;self.ui.start_quiz()
            for _ in range(8):
                u=self.ui
                self.assertEqual(len(u.current_options),4)
                if u.type_label.text=='词性判断':
                    answer=' / '.join(m.POS_LABELS.get(p,p) for p in u.current_word['pos']);index=u.current_options.index(answer)
                else:index=next(i for i,w in enumerate(u.current_options) if w['en']==u.current_word['en'])
                before=u.total_answered;u.check_answer(index);u.check_answer(index)
                self.assertEqual(u.total_answered,before+1)
                self.assertEqual(u.score,u.total_answered)
                u.next_question()
            u.build_menu()
    def test_meanings_unique(self):
        u=self.ui;u.start_quiz()
        for _ in range(40):
            u.current_word=u.all_words[_%len(u.all_words)];u.build_meaning_question()
            if u.type_label.text=='中文释义':self.assertEqual(len({w['zh'].strip() for w in u.current_options}),4)
    def test_same_meaning_falls_back_to_listening(self):
        u=self.ui;u.start_quiz();u.all_words=[dict(W,en='word'+str(i)) for i in range(4)];u.current_word=u.all_words[0]
        u.build_meaning_question();self.assertEqual(u.type_label.text,'单词听音四选一')
    def test_duplicate_word_import(self):
        parsed=m.parse_vocab_text('\ufeffUnit 1\nability | n. | 能力\nABILITY | n. | 能力\nability | n. | 能力')
        self.assertEqual(len(parsed['Unit 1']),1)
    def test_card_interval_and_reset(self):
        from datetime import date
        u=self.ui
        self.assertEqual(u._card_grade(W,'good',date(2026,10,29))['interval'],1)
        self.assertEqual(u._card_grade(W,'good',date(2026,10,30))['interval'],3)
        self.assertEqual(u._card_grade(W,'again',date(2026,10,31))['repetitions'],0)
        self.assertEqual(u._card_grade(W,'again',date(2026,10,31))['due'],'2026-10-31')
        with self.assertRaises(ValueError):u._card_grade(W,'bad')
    def test_card_limit_repeat_and_activity(self):
        u=self.ui;u.ui_count_text='每天 10 个';u.start_cards()
        self.assertEqual(len(u.card_queue),10);key=u.word_key(u.card_current)
        u.reveal_card();u.rate_card('again')
        self.assertEqual(len(u.card_queue),11)
        self.assertEqual(u.load_json(u.activity_path,{})[m.date.today().isoformat()]['cards'],1)
        self.assertEqual(u.card_attempts[key],1)
    def test_manual_empty_fields_survive_network(self):
        u=self.ui;u.save_json(u.details_path,{'ability':{'example':'','manual_fields':['example'],'source':'用户编辑'}})
        u._on_word_info_result('ability',{'example':'overwritten','ipa':'/x/'},'')
        result=u.load_json(u.details_path,{})['ability'];self.assertEqual(result['example'],'');self.assertEqual(result['ipa'],'/x/')
    def test_cancel_pending_advance_on_exit(self):
        u=self.ui;u.start_quiz();u._advance_event=Clock.schedule_once(lambda *_:self.fail('stale timer'),.1)
        u.build_menu();self.assertIsNone(u._advance_event);self.assertIsNone(u.current_word);self.assertFalse(u.is_answering)
    def test_settings_and_corrupt_local_file(self):
        u=self.ui;u._set_learning_setting('ui_count_text','每天 10 个')
        self.assertEqual(u.load_json(u.settings_path,{})['count'],'每天 10 个')
        Path(u.custom_units_path).write_text('[]');u.load_vocab();self.assertTrue(u.units)
        Path(u.wrong_path).write_text('{broken\n'+json.dumps(W)+'\n')
        self.assertEqual(len(u.load_wrong_words()),1)
    def test_detail_popup(self):
        self.ui.show_word_details(W);Clock.tick()
        self.assertEqual(set(self.ui.detail_inputs),{'ipa','example','example_zh','phrases'})
        self.ui.detail_popup.dismiss();Clock.tick()
    def test_back_exits_quiz(self):
        self.ui.start_quiz();self.assertTrue(self.ui._on_keyboard(Window,27));self.assertEqual(self.ui.screen_mode,'menu')
    def test_ipa_font_coverage(self):
        self.assertTrue(Path(m.IPA_FONT_PATH).exists())

if __name__=='__main__':unittest.main(verbosity=2)
