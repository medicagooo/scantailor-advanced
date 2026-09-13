"""Encoding contract tests against real native CLI and PDF renderer (Windows)."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock
from PIL import Image, ImageChops
import pymupdf
import cli_integration as legacy
sys.path.insert(0, os.environ.get('SCANTAILOR_MENU_ROOT', str(Path(__file__).resolve().parents[1] / 'scripts')))
import image_encoding
from scantailor_menu.model import Controller
from scantailor_menu.workbench import Workbench
CLI = None

class EncodingTests(unittest.TestCase):
    setUp = legacy.CliTests.setUp
    tearDown = legacy.CliTests.tearDown
    invoke = legacy.CliTests.invoke
    process = legacy.CliTests.process

    def config(self, **value):
        path = self.root / ('config-' + str(len(list(self.root.glob('config-*')))) + '.json')
        path.write_text(json.dumps({'schema_version': 2, **value}), encoding='utf-8')
        return path

    def run_image(self, name, *args):
        out = self.root / name
        events = self.process(out, '--deskew', 'off', '--page-detection', 'off', *args)
        return json.loads((out / 'report.json').read_text(encoding='utf-8')), events

    def test_png_levels_pixels_dpi_and_resume(self):
        legacy.fixture(self.inputs / '001.png')
        sizes = []
        for level in (0, 6, 9):
            flags = [] if level == 6 else ['--png-compression', str(level)]
            report, _ = self.run_image('png'+str(level), *flags)
            page = report['pages'][0]
            self.assertEqual(page['image_encoding'], {'format': 'png', 'png_compression': level})
            path = Path(page['output'])
            sizes.append(path.stat().st_size)
            self.assertEqual(path.suffix, '.png')
            with Image.open(path) as result, Image.open(self.inputs/'001.png') as original:
                self.assertEqual(result.format, 'PNG')
                self.assertIsNone(ImageChops.difference(original.convert('RGB'), result.convert('RGB')).getbbox())
                self.assertAlmostEqual(result.info['dpi'][0], 150, delta=.1)
        self.assertGreater(sizes[0], sizes[1]*2)
        out = self.root/'png6'
        events = self.process(out, '--deskew','off','--page-detection','off','--resume')
        self.assertTrue(any(e.get('event') == 'page_reused' for e in events))
        events = self.process(out, '--deskew','off','--page-detection','off','--resume','--png-compression','9')
        self.assertTrue(any(e.get('event') == 'invalidated' for e in events))
        self.assertFalse(any(e.get('event') == 'page_reused' for e in events))

    def test_tiff_codecs_and_bw(self):
        legacy.fixture(self.inputs/'001.png')
        for color in ('color-grayscale','black-white'):
            pixels = None
            for codec, tag in [('none',1),('lzw',5),('deflate',8)]:
                report,_ = self.run_image(color+codec, '--image-format','tiff','--tiff-compression',codec,'--color-mode',color)
                with Image.open(report['pages'][0]['output']) as image:
                    self.assertEqual(image.format, 'TIFF')
                    self.assertEqual(image.tag_v2[259], tag)
                    rgb = image.convert('RGB')
                    if pixels is not None: self.assertIsNone(ImageChops.difference(rgb,pixels).getbbox())
                    pixels = rgb

    def test_jpeg_quality_and_preserve_fallback(self):
        legacy.fixture(self.inputs/'001.png')
        tables=[]
        for quality in (25,95):
            report,_=self.run_image('jpeg'+str(quality),'--image-format','jpeg','--jpeg-quality',str(quality))
            with Image.open(report['pages'][0]['output']) as image:
                self.assertEqual(image.format,'JPEG'); tables.append(image.quantization)
        self.assertNotEqual(tables[0],tables[1])
        legacy.fixture(self.inputs/'001.png',blank=True)
        out=self.root/'review'
        self.process(out,'--image-format','jpeg',accepted=(1,))
        page=json.loads((out/'report.json').read_text(encoding='utf-8'))['pages'][0]
        self.assertTrue(page['fallback_original'])
        self.assertEqual(page['image_encoding']['format'],'png')
        with Image.open(page['output']) as image, Image.open(self.inputs/'001.png') as source:
            self.assertIsNone(ImageChops.difference(image.convert('RGB'),source.convert('RGB')).getbbox())
        events=self.process(out,'--image-format','jpeg','--resume',accepted=(1,))
        self.assertTrue(any(e.get('event')=='page_reused' for e in events))

    def test_config_priority_and_invalid_combinations(self):
        legacy.fixture(self.inputs/'001.png')
        conf=self.config(image_encoding={'format':'tiff','tiff_compression':'lzw'})
        report,_=self.run_image('override','--config',conf,'--image-format','png','--png-compression','0')
        self.assertEqual(report['pages'][0]['image_encoding'],{'format':'png','png_compression':0})
        report,_=self.run_image('saved','--config',conf)
        self.assertEqual(report['pages'][0]['image_encoding'],{'format':'tiff','tiff_compression':'lzw'})
        for flags in [('--png-compression','10'),('--png-compression','2.5'),('--jpeg-quality','95'),('--image-format','jpeg','--png-compression','6')]:
            self.process(self.root/'invalid',*flags,accepted=(2,))
        self.invoke('project','create','--input',self.inputs,'--save',self.root/'bad.scan','--image-format','png',accepted=(2,))

    def test_split_layers_and_gui_cache_format(self):
        legacy.fixture(self.inputs/'001.png')
        conf=self.config(defaults={'split':{'layout':'two'},'output':{'mode':'mixed','split_output':True,'foreground':'bw','original_background':True}})
        report,_=self.run_image('layers','--config',conf)
        self.assertEqual(len(report['pages']),2)
        for page in report['pages']:
            self.assertGreaterEqual(len(page['artifacts']),4)
            for artifact in page['artifacts']:
                with Image.open(artifact['path']) as image:
                    self.assertEqual(image.format,'PNG')
        for path in (self.root/'layers/cache').rglob('*.tif'):
            with Image.open(path) as image: self.assertEqual(image.format,'TIFF')
        self.process(self.root/'jpeg-layers','--config',conf,'--image-format','jpeg',accepted=(2,))

    def test_pdf_render_format_and_invalidation(self):
        source=self.root/'pdf';source.mkdir()
        with pymupdf.open() as pdf:
            page=pdf.new_page(width=240,height=320)
            page.insert_text((20,45),'Format and compression test',fontsize=12)
            pdf.save(source/'test.pdf')
        before=legacy.digest(source/'test.pdf')
        conf=self.config(defaults={'deskew':{'mode':'off'}})
        for fmt in ('png','tiff','jpeg'):
            out=self.root/('pdf-'+fmt)
            cmd=[sys.executable,str(CLI.parent/'process_pdf_folder.py'),'--pdf-dir',str(source),'--cli',str(CLI),'--output-dir',str(out),'--dpi','120','--config',str(conf),'--image-format',fmt]
            result=subprocess.run(cmd,capture_output=True,encoding='utf-8')
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            render=list((out/'.work').glob('*/*/input/*'))
            self.assertEqual(len(render),1)
            with Image.open(render[0]) as image:
                self.assertEqual(image.format,{'png':'PNG','tiff':'TIFF','jpeg':'JPEG'}[fmt])
                self.assertAlmostEqual(image.info['dpi'][0],120,delta=.1)
            if fmt=='png':
                result=subprocess.run(cmd+['--resume','--png-compression','0'],capture_output=True,encoding='utf-8')
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                self.assertEqual(len(list((out/'.work').glob('*/*/input/*.png'))),2)
            with pymupdf.open(out/'test.deskew.pdf') as pdf:
                self.assertEqual(pdf.page_count,1)
                self.assertEqual(tuple(pdf[0].rect),(0,0,240,320))
        self.assertEqual(legacy.digest(source/'test.pdf'),before)

    def test_review_schema1_native_and_pdf_format_override(self):
        legacy.fixture(self.inputs/'001.png')
        config=self.root/'legacy.json'
        config.write_text(json.dumps({'schema_version':1,'image-format':'tiff','tiff-compression':'lzw','deskew':'off'}),encoding='utf-8')
        report,_=self.run_image('legacy','--config',config,'--image-format','png')
        self.assertEqual(report['pages'][0]['image_encoding'],{'format':'png','png_compression':6})
        folder=self.root/'pdf';folder.mkdir()
        with pymupdf.open() as pdf:
            page=pdf.new_page(width=240,height=320);page.insert_text((20,40),'Legacy configuration')
            pdf.save(folder/'legacy.pdf')
        cmd=[sys.executable,str(CLI.parent/'process_pdf_folder.py'),'--pdf-dir',str(folder),'--cli',str(CLI),'--output-dir',str(self.root/'pdf-out'),'--dpi','120','--config',str(config),'--image-format','png']
        result=subprocess.run(cmd,capture_output=True,encoding='utf-8')
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_review_resume_roundtrip_ownership(self):
        legacy.fixture(self.inputs/'001.png')
        out=self.root/'roundtrip'
        for i,fmt in enumerate(('png','tiff','png')):
            extra=['--resume'] if i else []
            self.process(out,'--deskew','off','--image-format',fmt,*extra)
            report=json.loads((out/'report.json').read_text(encoding='utf-8'))
            self.assertEqual(report['pages'][0]['image_encoding']['format'],fmt)
        foreign=out/'001.jpg';foreign.write_bytes(b'user-owned file')
        self.process(out,'--deskew','off','--image-format','jpeg','--resume',accepted=(3,))
        self.assertEqual(foreign.read_bytes(),b'user-owned file')

    def test_review_jpeg_selected_pages_only(self):
        legacy.fixture(self.inputs/'001.png');legacy.fixture(self.inputs/'002.png')
        config=self.config(defaults={'split':{'layout':'single'},'deskew':{'mode':'off'}},rules=[{'select':{'pages':[2]},'settings':{'output':{'mode':'mixed','split_output':True,'foreground':'bw'}}}])
        self.process(self.root/'selected','--config',config,'--pages','1','--image-format','jpeg')
        self.process(self.root/'rejected','--config',config,'--pages','2','--image-format','jpeg',accepted=(2,))

    def test_grayscale_and_effective_color_layers(self):
        legacy.fixture(self.inputs/'001.png')
        with Image.open(self.inputs/'001.png') as image: gray=image.convert('L')
        gray.save(self.inputs/'001.png',dpi=(150,150))
        for fmt in ('png','tiff'):
            report,_=self.run_image('gray-'+fmt,'--image-format',fmt)
            with Image.open(report['pages'][0]['output']) as image:
                self.assertIsNone(ImageChops.difference(gray,image.convert('L')).getbbox())
            config=self.config(defaults={'output':{'mode':'mixed','split_output':True,'foreground':'color','original_background':True}})
            report,_=self.run_image('color-layers-'+fmt,'--image-format',fmt,'--config',config)
            # COLOR_FOREGROUND disables original background in core RenderParams.
            self.assertEqual(len(report['pages'][0]['artifacts']),3)

    def test_workbench_encoding_draft_snapshot_and_load(self):
        model=Controller(CLI,self.root/'jobs')
        model.apply({'schema_version':2,'image_encoding':{'format':'png','png_compression':0}})
        model.preview=(model.revision,'old')
        ui=Mock();ui.m=model
        # Workbench uses ui.m and ui.c; edit/cancel must never mutate input draft.
        ui.c.choose.side_effect=[0,2,2]
        workbench=Workbench(ui)
        original=dict(model.config['image_encoding'])
        chosen=workbench.encoding(original)
        self.assertEqual(original,{'format':'png','png_compression':0})
        self.assertEqual(chosen,{'format':'jpeg','jpeg_quality':95})
        model.apply({'schema_version':2,'image_encoding':chosen})
        self.assertIsNone(model.preview)
        saved=self.root/'preset.json';saved.write_text(json.dumps(model.config),encoding='utf-8')
        other=Controller(CLI,self.root/'jobs2');other.apply(json.loads(saved.read_text(encoding='utf-8')))
        self.assertEqual(other.config,model.config)
        legacy.fixture(self.inputs/'001.png'); model.select('images',[self.inputs/'001.png']); model.output=str(self.root/'menu-output')
        model.launch=Mock();model.start()
        job,args=model.launch.call_args.args
        snapshot=json.loads((Path(job['folder'])/'settings.json').read_text(encoding='utf-8'))
        self.assertEqual(snapshot['image_encoding'],chosen)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--cli',type=Path,required=True)
    opts,rest=parser.parse_known_args(); CLI=opts.cli.resolve();legacy.CLI=CLI
    unittest.main(argv=[sys.argv[0],*rest])
