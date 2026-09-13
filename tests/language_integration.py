"""Locale resolution, persistence, UI resources and language-neutral task identity."""
import argparse
import copy
import json
import os
from pathlib import Path
import re
from string import Formatter
import sys
import tempfile
import subprocess
import time
import unittest
from unittest.mock import Mock, patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,os.environ.get('SCANTAILOR_MENU_ROOT',str(ROOT/'scripts')))
from scantailor_menu import i18n
from scantailor_menu.model import Controller
from scantailor_menu.ui import UI, summary
from scantailor_menu.workbench import Workbench
from scantailor_menu.preview import build_viewer
from scantailor_menu.rendering import cells
CLI=None

class LanguageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.m=Controller(CLI,self.root/'settings',language='en')
    def tearDown(self):self.tmp.cleanup()

    def test_missing_or_corrupt_locale_falls_back_to_english(self):
        self.assertEqual(i18n.read_catalog('zh-Hant',self.root),{})
        (self.root/'zh-Hant.json').write_text('{broken')
        self.assertEqual(i18n.read_catalog('zh-Hant',self.root),{})
        with patch.dict(i18n._catalogs,{'zh-Hant':{}}):
            self.m.set_language('zh-Hant')
            self.assertEqual(i18n.tr('msg_000'),'OK')
        with self.assertRaises(RuntimeError): i18n.read_catalog('en',self.root)

    def test_windows_language_mapping_and_priority(self):
        for name,expected in [('en-GB','en'),('zh-CN','zh-Hans'),('zh-SG','zh-Hans'),('zh-TW','zh-Hant'),('zh-HK','zh-Hant'),('zh-MO','zh-Hant'),('zh-Hans-HK','zh-Hans'),('zh-Hant-CN','zh-Hant')]:
            self.assertEqual(i18n.resolve_language('auto',[name]),expected)
        self.assertEqual(i18n.resolve_language('auto',['fr-FR','zh-HK','en-US']),'zh-Hant')
        self.assertEqual(i18n.resolve_language('auto',['de-DE']),'en')
        self.assertEqual(i18n.resolve_language('auto',[]),'en')
        self.assertEqual(i18n.resolve_language('en',['zh-CN']),'en')
        with self.assertRaises(ValueError):i18n.resolve_language('invalid')

    def test_saved_manual_language_and_one_launch_override(self):
        self.m.set_language('zh-Hant')
        loaded=Controller(CLI,self.m.home)
        self.assertEqual(i18n.language(),'zh-Hant')
        self.assertEqual(loaded.language_preference,'zh-Hant')
        overridden=Controller(CLI,self.m.home,language='en')
        overridden.update_options({'jobs':2})
        self.assertEqual(json.loads(overridden.preferences_path.read_text())['ui']['language'],'zh-Hant')
        Controller(CLI,self.m.home)
        self.assertEqual(i18n.language(),'zh-Hant')
        overridden.set_language('zh-Hans')
        self.assertIsNone(overridden.language_override)
        self.assertEqual(i18n.language(),'zh-Hans')

    def test_legacy_and_invalid_preferences_keep_processing_settings(self):
        self.m.apply({'schema_version':2,'defaults':{'output':{'dpi':[600,600]}}})
        saved=json.loads(self.m.preferences_path.read_text());saved.pop('ui')
        self.m.preferences_path.write_text(json.dumps(saved))
        with patch.object(i18n,'preferred_languages',return_value=['zh-HK']):
            loaded=Controller(CLI,self.m.home)
        self.assertEqual(loaded.language_preference,'auto');self.assertEqual(i18n.language(),'zh-Hant')
        saved['ui']={'language':'bad'};self.m.preferences_path.write_text(json.dumps(saved))
        loaded=Controller(CLI,self.m.home)
        self.assertTrue(loaded.preference_error)
        self.assertEqual(loaded.config['defaults']['output']['dpi'],[600,600])

    def test_language_switch_does_not_invalidate_processing(self):
        from PIL import Image
        source=self.root/'source.png';Image.new('RGB',(90,120),'white').save(source,dpi=(100,100))
        self.m.select('images',[source]);self.m.output=str(self.root/'out')
        before=self.m.plan()['identity'];revision=self.m.revision;config=copy.deepcopy(self.m.config)
        self.m.preview=(revision,'existing');self.m.set_language('zh-Hant')
        self.assertEqual(self.m.plan()['identity'],before)
        self.assertEqual(self.m.revision,revision);self.assertEqual(self.m.preview,(revision,'existing'))
        self.assertEqual(self.m.config,config)
        self.assertNotIn('language',self.m.plan()['request']['options'])
        self.assertNotIn('ui',self.m.plan()['request'])

    def test_native_menu_launcher_forwards_language(self):
        startup=subprocess.STARTUPINFO();startup.dwFlags=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=0
        for locale in i18n.NAMES:
            result=self.root/(locale+'.json')
            child=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--cli',str(CLI),'--menu-child',str(result),'--locale',locale],startupinfo=startup,creationflags=subprocess.CREATE_NEW_CONSOLE)
            try:code=child.wait(timeout=35)
            except subprocess.TimeoutExpired:
                child.kill();child.wait();raise
            self.assertEqual(code,0,result.read_text() if result.exists() else 'No child report')
            self.assertTrue(json.loads(result.read_text())['preference_unchanged'])

    def test_failed_save_keeps_current_language(self):
        self.m.set_language('en')
        with patch.object(self.m,'save_preferences',side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):self.m.set_language('zh-Hant')
        self.assertEqual(self.m.language_preference,'en');self.assertEqual(i18n.language(),'en')

    def test_language_setting_available_without_input(self):
        console=Mock();console.choose.side_effect=[5,3]
        ui=UI(console,self.m);bench=Workbench(ui)
        frame,controls=bench.frame(80,25)
        self.assertIn('advanced',controls);bench.advanced()
        self.assertEqual(self.m.language_preference,'zh-Hant')
        self.assertEqual(i18n.language(),'zh-Hant')
        self.assertIn('English',console.choose.call_args.args[1])

    def test_catalog_coverage_placeholders_and_language_layouts(self):
        catalogs={name:i18n.catalog(name) for name in i18n.NAMES}
        # Inspect raw files too: fallback must not hide missing shipped translations.
        raw={name:json.loads((Path(i18n.__file__).parent/'locales'/f'{name}.json').read_text()) for name in i18n.NAMES}
        self.assertEqual(set(raw['en']),set(raw['zh-Hans']));self.assertEqual(set(raw['en']),set(raw['zh-Hant']))
        formatter=Formatter()
        for key,english in catalogs['en'].items():
            if key != 'language.title': self.assertFalse(re.search('[\u4e00-\u9fff]',english),key)
            fields={f for _,f,_,_ in formatter.parse(english) if f}
            for cat in catalogs.values():self.assertEqual(fields,{f for _,f,_,_ in formatter.parse(cat[key]) if f},key)
        for name in i18n.NAMES:
            self.m.set_language(name);bench=Workbench(UI(None,self.m))
            for width,height in [(120,30),(80,25),(54,22)]:
                frame,controls=bench.frame(width,height)
                text='\n'.join(span[2] for row in frame.rows for span in row)
                self.assertNotRegex(text,r'msg_\d{3}')
                if name=='en':self.assertNotRegex(text,'[\u4e00-\u9fff]')
                for x,y,w,h,key in frame.hits:
                    self.assertLessEqual(x+w,frame.width+1);self.assertEqual(frame.hit((x,y)),key)
        self.m.set_language('en');self.assertEqual(i18n.tr('count.files',count=1),'1 file')

    def test_stage_enum_and_summary_use_processing_context(self):
        self.m.set_language('zh-Hant');console=Mock();console.choose.return_value=2
        ui=UI(console,self.m)
        stages=['orientation','split','deskew','content','layout','output']
        self.assertEqual(ui.edit('stage',{'type':'string','enum':stages},'output'),(True,'deskew'))
        self.assertEqual(console.choose.call_args.args[1],[i18n.tr('stage.'+s) for s in stages])
        self.assertEqual(summary('deskew','stage'),i18n.tr('stage.deskew'))
        ui.edit('coordinates',{'type':'string','enum':['source','oriented','deskew']},'source')
        self.assertNotEqual(console.choose.call_args.args[1][2],i18n.tr('stage.deskew'))

    def test_reused_stage_is_localized_when_displayed(self):
        import io
        self.m.set_language('zh-Hant')
        folder=self.root/'job';folder.mkdir()
        process=Mock();process.stdout=io.StringIO(json.dumps({'event':'phase_reused','stage':'deskew','total':3})+'\n');process.wait.return_value=3
        self.m._read(process,{'folder':str(folder),'output':str(folder),'command':'analyze','revision':0})
        self.assertEqual(self.m.progress['stage'],'deskew');self.assertTrue(self.m.progress['reused'])
        self.m.status='running';self.m.process=Mock()
        console=Mock();console.dimensions.return_value=(100,30);console.read.return_value=('escape',None)
        UI(console,self.m).monitor()
        frame=console.draw.call_args.args[0]
        text=''.join(span[2] for row in frame.rows for span in row)
        self.assertIn(i18n.tr('stage.deskew')+i18n.tr('msg_025'),text)

    def test_viewer_has_three_languages_and_escaped_data(self):
        source=self.root/'source.png';source.write_bytes(b'example')
        attack='</script><script>alert(1)</script> __LANGUAGE__ __TRANSLATIONS__ __DATA__'
        (self.root/'report.json').write_text(json.dumps({'pages':[{'input':str(source),'preview':str(source),'message':attack}]}))
        self.m.set_language('zh-Hant');html=build_viewer(self.root).read_text()
        self.assertIn('languages.value="zh-Hant"',html)
        self.assertIn('id="language"',html)
        data=json.JSONDecoder().raw_decode(html.split('const data=',1)[1])[0]
        self.assertEqual(data[0]['message'],attack)
        self.assertNotIn(attack,html);self.assertIn('\\u003c/script>',html)
        for locale in i18n.NAMES:self.assertIn('value="'+locale+'"',html)

def menu_child(cli, result, locale):
    import ctypes as C
    from ctypes import wintypes as W
    from scantailor_menu.console import Record, Coord
    home=result.parent/('launcher-'+locale);home.mkdir()
    preferences=home/'settings.json'
    preferences.write_text(json.dumps({'schema_version':1,'config':{'schema_version':2},'options':{},'ui':{'language':'zh-Hans'}}))
    before=preferences.read_bytes()
    api=C.WinDLL('kernel32',use_last_error=True)
    api.GetStdHandle.restype=W.HANDLE
    api.ReadConsoleOutputCharacterW.argtypes=[W.HANDLE,W.LPWSTR,W.DWORD,Coord,C.POINTER(W.DWORD)]
    api.WriteConsoleInputW.argtypes=[W.HANDLE,C.POINTER(Record),W.DWORD,C.POINTER(W.DWORD)]
    output=api.GetStdHandle(-11);input_handle=api.GetStdHandle(-10)
    process=subprocess.Popen([str(cli),'menu','--language',locale,'--state-dir',str(home)])
    try:
        expected={'en':'Inputfiles','zh-Hans':'输入文件','zh-Hant':'輸入檔案'}[locale]
        deadline=time.monotonic()+20
        while True:
            buffer=C.create_unicode_buffer(12000);count=W.DWORD()
            if not api.ReadConsoleOutputCharacterW(output,buffer,11999,Coord(0,0),C.byref(count)):raise C.WinError(C.get_last_error())
            if expected in ''.join(buffer.value.split()):break
            if process.poll() is not None:raise RuntimeError('Menu exited before rendering')
            if time.monotonic()>deadline:raise TimeoutError('Localized menu did not render')
            time.sleep(.05)
        for down in (True,False):
            record=Record();record.type=1;record.event.key.down=down;record.event.key.vk=27;record.event.key.char='\x1b';record.event.key.repeat=1
            if not api.WriteConsoleInputW(input_handle,C.byref(record),1,C.byref(count)):raise C.WinError(C.get_last_error())
        code=process.wait(timeout=10)
        result.write_text(json.dumps({'locale':locale,'exit_code':code,'preference_unchanged':before==preferences.read_bytes()}))
        return code
    except Exception as error:
        result.write_text(json.dumps({'error':str(error)}));return 1
    finally:
        if process.poll() is None:process.terminate();process.wait(timeout=5)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--cli',type=Path,required=True)
    parser.add_argument('--menu-child',type=Path);parser.add_argument('--locale')
    args,rest=parser.parse_known_args();CLI=args.cli.resolve()
    if args.menu_child:raise SystemExit(menu_child(CLI,args.menu_child,args.locale))
    unittest.main(argv=[sys.argv[0],*rest])
