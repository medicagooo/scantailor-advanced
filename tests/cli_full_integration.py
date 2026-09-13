"""Business-contract tests for complete CLI projects, geometry and PDF mapping."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

from PIL import Image, ImageChops
import pymupdf
import cli_integration as legacy

CLI = None
ARTIFACTS = None
GUI = None


class FullCliTests(legacy.CliTests):
    # Keep the seven v1 contract tests in this suite as well.
    def setUp(self):
        legacy.CLI = CLI
        legacy.ARTIFACTS = ARTIFACTS
        super().setUp()

    def config(self, **fields):
        path = self.root / f"config-{len(list(self.root.glob('config-*')))}.json"
        path.write_text(json.dumps({"schema_version": 2, **fields}), encoding="utf-8")
        return path

    def json_file(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def project(self, config=None):
        if not list(self.inputs.iterdir()):
            legacy.fixture(self.inputs / "001.png")
        path = self.root / "book.scan"
        args = ["project", "create", "--input", self.inputs, "--save", path]
        if config:
            args += ["--config", config]
        self.invoke(*args)
        return path

    def inspect(self, project):
        return self.invoke("project", "inspect", "--project", project)[-1]

    def test_full_parameter_project_roundtrip(self):
        output = {
            "mode": "mixed", "dpi": [180, 160], "fill_offcut": False, "fill_outside_page": True,
            "fill_margins": False, "fill_color": "black", "normalize_color": True,
            "wiener_coefficient": .2, "wiener_window": 7, "posterize": True,
            "posterize_level": 5, "posterize_normalize": True, "posterize_force_bw": False,
            "threshold_method": "wolf", "threshold": 12, "normalize_bw": False,
            "savitzky_golay": False, "morphological_smoothing": False, "threshold_window": 51,
            "sauvola_coefficient": .4, "wolf_coefficient": .35, "wolf_lower": 4, "wolf_upper": 240,
            "color_segmentation": True, "segment_noise": 5, "segment_red": -12,
            "segment_green": 10, "segment_blue": 3, "picture_shape": "rectangular",
            "picture_sensitivity": 75, "picture_high_sensitivity": True, "split_output": True,
            "foreground": "color", "original_background": True, "despeckle": .8,
            "black_on_white": False, "dewarp": "off", "post_deskew": False,
            "post_deskew_angle": 1.25, "depth": 2.3,
        }
        config = self.config(project={"reading_direction": "rtl", "deskew_algorithm": "top-edge",
            "page_detection_size_mm": [170, 240], "page_detection_tolerance": .2,
            "guides": [{"orientation": "horizontal", "position": 12}], "show_middle_rect": True},
            defaults={"output": output, "orientation": {"rotation": 90, "trim": {"enabled": True, "left": 10, "right": 20}},
                "deskew": {"mode": "manual", "angle": 1.5, "oblique_mode": "manual", "oblique_angle": -.75},
                "layout": {"margins_mm": {"left": 5, "right": 8, "top": 9, "bottom": 12}, "auto_margins": False, "match_size": True, "horizontal": "right", "vertical": "bottom"}})
        project = self.project(config)
        info = self.inspect(project)
        for key, value in output.items():
            actual = info["pages"][0]["settings"]["output"][key]
            if isinstance(value, float): self.assertAlmostEqual(actual, value)
            else: self.assertEqual(actual, value, key)
        self.assertEqual(info["project"]["deskew_algorithm"], "top-edge")
        self.assertEqual(info["pages"][0]["settings"]["orientation"]["trim"]["right"], 20)
        exported = self.root / "export.json"
        self.invoke("config", "export", "--project", project, "--save", exported)
        replay = self.root / "replay.scan"
        self.invoke("project", "apply", "--project", project, "--config", exported, "--save", replay)
        again = self.inspect(replay)
        self.assertEqual(again["pages"][0]["id"], info["pages"][0]["id"])
        self.assertEqual(again["pages"][0]["settings"], info["pages"][0]["settings"])
        self.assertEqual(again["project"], info["project"])

    def test_strict_validation_and_source_scope(self):
        project = self.project()
        for settings in ({"output": {"typo": True}}, {"orientation": {"rotation": 45}},
                         {"output": {"dpi": [150, "150"]}}, {"output": {"wolf_lower": 250, "wolf_upper": 4}},
                         {"output": {"split_output": True}}, {"output": {"dewarp": "manual"}}):
            self.invoke("project", "apply", "--project", project, "--config", self.config(defaults=settings),
                        "--save", self.root / "invalid.scan", accepted=(2,))
            self.assertFalse((self.root / "invalid.scan").exists())
        config = self.config(rules=[{"select": {"side": "left"}, "settings": {"orientation": {"rotation": 90}}}])
        self.invoke("project", "apply", "--project", project, "--config", config, "--save", self.root / "invalid.scan", accepted=(2,))
        self.invoke("project", "apply", "--project", project, "--config", self.config(defaults={"output": {"threshold": 1}}),
                    "--save", self.root / "dry.scan", "--dry-run")
        self.assertFalse((self.root / "dry.scan").exists())

    def test_project_operations_preserve_identity(self):
        legacy.fixture(self.inputs / "001.png")
        legacy.fixture(self.inputs / "002.png")
        project = self.project()
        info = self.inspect(project)
        ids = [p["image_id"] for p in info["pages"]]
        new_image = self.root / "insert.png"
        legacy.fixture(new_image)
        relocated = self.root / "relocated.png"
        shutil.copyfile(self.inputs / "001.png", relocated)
        ops = self.json_file("operations.json", {"schema_version": 1, "operations": [
            {"type": "reorder", "image_ids": ids[::-1]},
            {"type": "insert", "files": [str(new_image)], "after_image": ids[1]},
            {"type": "relink", "from": str(self.inputs / "001.png"), "to": str(relocated)}]})
        edited = self.root / "edited.scan"
        self.invoke("project", "edit", "--project", project, "--operations", ops, "--save", edited)
        result = self.inspect(edited)["pages"]
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["image_id"], ids[1])
        self.assertEqual(result[2]["image_id"], ids[0])
        self.assertEqual(Path(result[2]["input"]), relocated)
        self.assertTrue((self.inputs / "001.png").exists())
        remove = self.json_file("remove.json", {"schema_version": 1, "operations": [{"type": "remove", "ids": [result[1]["id"]]}]})
        self.invoke("project", "edit", "--project", edited, "--operations", remove, "--save", self.root / "removed.scan")
        self.assertEqual(len(self.inspect(self.root / "removed.scan")["pages"]), 2)
        self.assertTrue(new_image.exists())

    def test_split_geometry_manual_rectangles_and_preview(self):
        image = Image.new("RGB", (1000, 700), "white")
        image.paste("red", (80, 100, 430, 600)); image.paste("blue", (580, 100, 930, 600))
        image.save(self.inputs / "spread.png", dpi=(150,150))
        config = self.config(defaults={"split": {"layout": "two", "mode": "manual", "space": "oriented", "cutters": [[[500,0],[500,700]]]},
            "deskew": {"mode": "off", "oblique_mode": "off"}, "content": {"page_mode": "off", "content_mode": "off"}},
            rules=[{"select": {"side": "right"}, "settings": {"layout": {"margins_mm": {"left": 5}}}}])
        out = self.root / "analyze"
        self.invoke("preview", "--input", self.inputs, "--output", out, "--config", config, "--stage", "content", "--html")
        report = json.loads((out / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(len(report["pages"]), 2)
        for p in report["pages"]:
            self.assertTrue(Path(p["preview"]).exists())
            self.assertEqual(len(p["preview_geometry"]["source_to_preview"]), 6)
        left = report["pages"][0]
        geometry = left["settings"]["_geometry"]
        bounds = geometry["bounds"]
        rectangle = [bounds[0]+20, bounds[1]+20, bounds[2]-40, bounds[3]-40]
        patch = self.config(rules=[{"select": {"ids": [left["id"]]}, "settings": {"content": {
            "space": "deskew", "basis": geometry["basis"], "page_rect": rectangle, "content_rect": rectangle}}}])
        edited = self.root / "manual.scan"
        self.invoke("project", "apply", "--project", out / "project.scan", "--config", patch, "--save", edited)
        final = self.root / "final"
        self.invoke("process", "--project", edited, "--output", final, "--pages", "1")
        result = json.loads((final / "report.json").read_text(encoding="utf-8"))
        self.assertEqual([p["status"] for p in result["pages"]], ["complete", "not_selected"])
        bad = self.config(defaults={"orientation": {"rotation": 90}}, rules=[{"select": {"ids": [left["id"]]},
            "settings": {"content": {"space": "deskew", "basis": geometry["basis"], "page_rect": rectangle}}}])
        self.invoke("project", "apply", "--project", edited, "--config", bad, "--save", self.root / "stale.scan", accepted=(2,))
        no_replacement = self.config(defaults={"orientation":{"rotation":90}})
        self.invoke("project","apply","--project",edited,"--config",no_replacement,"--save",self.root / "stale-without-basis.scan",accepted=(2,))

    def test_all_binarization_methods_and_output_layers(self):
        legacy.fixture(self.inputs / "001.png")
        for method in ("otsu", "sauvola", "wolf", "fox", "window", "bradley", "grad", "edgeplus", "blurdiv", "edgediv"):
            config = self.config(defaults={"deskew": {"mode": "off"}, "content": {"page_mode": "off"},
                "output": {"mode": "bw", "threshold_method": method, "threshold_window": 31, "normalize_bw": False}})
            self.process(self.root / method, "--config", config)
            with Image.open(self.root / method / "001.png") as image:
                self.assertEqual(image.size, (1000,1400))
                # PNG may encode the same two colors as a 1-bit palette.
                self.assertIn(image.mode, ("1", "P"))
                self.assertEqual(Path(image.filename).read_bytes()[24], 1)
                self.assertTrue(set(image.convert("L").getdata()) <= {0,255})
        config = self.config(defaults={"deskew": {"mode": "off"}, "content": {"page_mode": "off"},
            "output": {"mode": "mixed", "split_output": True, "original_background": True, "picture_shape": "off"},
            "picture_zones": [{"space": "source", "layer": "picture", "points": [[80,1080],[720,1080],[720,1250],[80,1250]]}],
            "fill_zones": [{"space": "source", "color": "#00ff00", "points": [[0,0],[40,0],[40,40],[0,40]]}]})
        output = self.root / "layers"
        self.process(output, "--config", config)
        report = json.loads((output / "report.json").read_text(encoding="utf-8"))
        artifacts = report["pages"][0]["artifacts"]
        self.assertEqual(len(artifacts), 4)
        for artifact in artifacts: self.assertTrue(Path(artifact["path"]).is_file())
        Path(artifacts[1]["path"]).write_bytes(b"damaged")
        self.process(output, "--config", config, "--resume")
        with Image.open(artifacts[1]["path"]) as image: image.load()

    def test_pdf_split_mapping_and_stable_ids(self):
        pdf_dir = self.root / "pdfs"; pdf_dir.mkdir()
        source = pdf_dir / "spread.pdf"
        with pymupdf.open() as pdf:
            for color in ((1,0,0), (0,0,1)):
                page = pdf.new_page(width=400,height=240)
                page.draw_rect(pymupdf.Rect(20,20,180,220), color=color, fill=color)
                page.draw_rect(pymupdf.Rect(220,20,380,220), color=(0,1,0), fill=(0,1,0))
            pdf.set_toc([[1,"first",1],[1,"second",2]])
            pdf.save(source)
        config = self.config(defaults={"split": {"layout": "two"}, "deskew": {"mode": "off", "oblique_mode": "off"},
                                     "content": {"page_mode": "off", "content_mode": "off"}})
        output = self.root / "pdf-output"
        wrapper = legacy.ROOT / "scripts/process_pdf_folder.py"
        command = [sys.executable,str(wrapper),"--pdf-dir",str(pdf_dir),"--cli",str(CLI),"--output-dir",str(output),"--dpi","100","--config",str(config)]
        result = subprocess.run(command,capture_output=True,text=True,encoding="utf-8")
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        with pymupdf.open(output / "spread.deskew.pdf") as pdf:
            self.assertEqual(pdf.page_count,4)
            self.assertEqual(pdf.get_toc(), [[1,"first",1],[1,"second",3]])
            self.assertAlmostEqual(pdf[0].rect.width,200)
            self.assertAlmostEqual(pdf[0].rect.height,240)
        report = json.loads((output / "batch-report.json").read_text(encoding="utf-8"))["results"][0]
        ids = [p["logical_id"] for p in report["pages"]]
        modified = json.loads(config.read_text(encoding="utf-8")); modified["defaults"]["output"]={"fill_margins":False}; config.write_text(json.dumps(modified))
        result = subprocess.run(command+["--resume"],capture_output=True,text=True,encoding="utf-8")
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        again = json.loads((output / "batch-report.json").read_text(encoding="utf-8"))["results"][0]
        self.assertEqual([p["logical_id"] for p in again["pages"]],ids)

    def test_curves_geometry_and_dewarped_layers(self):
        legacy.fixture(self.inputs / "001.png")
        model = {"space":"source", "top_spline":[{"point":[0,0],"tension":0},{"point":[500,20],"tension":-.5},{"point":[1000,0],"tension":0}],
                 "bottom_spline":[{"point":[0,1400],"tension":0},{"point":[500,1380],"tension":-.5},{"point":[1000,1400],"tension":0}]}
        config = self.config(defaults={"deskew":{"mode":"off"},"content":{"page_mode":"off","content_mode":"off"},
            "output":{"mode":"mixed","split_output":True,"original_background":True,"dewarp":"manual","distortion_model":model}})
        project = self.project(config)
        self.assertEqual(self.inspect(project)["pages"][0]["settings"]["output"]["distortion_model"],model)
        output = self.root / "curves"
        self.invoke("process","--project",project,"--output",output)
        report = json.loads((output / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(len(report["pages"][0]["artifacts"]),4)
        page_id = report["pages"][0]["id"]
        source_points = [[200,300],[600,900]]
        for space in ("oriented","split","deskew","content","layout","output"):
            request = {"schema_version":1,"id":page_id,"from":"source","to":space,"points":source_points}
            file = self.json_file("map.json",request)
            mapped = self.invoke("geometry","map","--project",output / "project.scan","--geometry",file)[-1]
            request.update({"from":space,"to":"source","points":mapped["points"]}); self.json_file("map.json",request)
            back = self.invoke("geometry","map","--project",output / "project.scan","--geometry",file)[-1]
            for actual, expected in zip(back["points"],source_points):
                for a,b in zip(actual,expected): self.assertAlmostEqual(a,b,places=4)
        for mode in ("auto","marginal"):
            patch = self.config(defaults={"output":{"dewarp":mode}})
            self.invoke("process","--project",project,"--config",patch,"--output",self.root / mode,accepted=(0,1))
            r = json.loads((self.root / mode / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(r["errors"],0)

    def test_freeze_restore_and_multipage_dpi(self):
        first = Image.new("RGB",(600,800),"white"); second = Image.new("RGB",(600,800),"gray")
        first.save(self.inputs / "pages.tif",save_all=True,append_images=[second],dpi=(150,150))
        config = self.config(defaults={"input":{"dpi":[180,160]},"split":{"layout":"two"},
            "deskew":{"mode":"off"},"content":{"page_mode":"off","content_mode":"off"},"layout":{"match_size":True}},
            project={"freeze_layout":True,"frozen_size_mm":[120,150]})
        project = self.project(config); pages = self.inspect(project)["pages"]
        self.assertEqual(len(pages),4)
        self.assertEqual({p["image_page"] for p in pages},{1,2})
        self.assertTrue(all(p["settings"]["input"]["dpi"] == [180,160] for p in pages))
        remove = self.json_file("remove.json",{"schema_version":1,"operations":[{"type":"remove","ids":[pages[0]["id"]]}]})
        removed = self.root / "removed.scan"; self.invoke("project","edit","--project",project,"--operations",remove,"--save",removed)
        restore = self.json_file("restore.json",{"schema_version":1,"operations":[{"type":"restore-half","image_id":pages[0]["image_id"],"side":"left"}]})
        restored = self.root / "restored.scan"; self.invoke("project","edit","--project",removed,"--operations",restore,"--save",restored)
        self.assertEqual([p["id"] for p in self.inspect(restored)["pages"]],[p["id"] for p in pages])
        self.invoke("process","--project",restored,"--config",config,"--output",self.root / "freeze")
        saved = self.inspect(self.root / "freeze/project.scan")
        self.assertTrue(saved["project"]["freeze_layout"])
        self.assertEqual(saved["project"]["frozen_size_mm"],[120,150])

    def test_protected_destinations_flags_and_preset_precedence(self):
        project = self.project(); before = legacy.digest(project)
        self.invoke("config","export","--project",project,"--save",project,"--overwrite",accepted=(2,))
        self.assertEqual(legacy.digest(project),before)
        image = self.inputs / "001.png"; digest = legacy.digest(image)
        self.invoke("pages","list","--project",project,"--save",image,"--overwrite",accepted=(2,))
        self.assertEqual(legacy.digest(image),digest)
        self.invoke("project","inspect","--project",project,"--resume",accepted=(2,))
        self.invoke("doctor","--output",self.root,accepted=(2,))
        self.invoke("project","edit","--project",project,"--save",self.root / "missing.scan",accepted=(2,))
        patch = self.config(defaults={"output":{"despeckle":1.5,"normalize_color":True}})
        edited = self.root / "precedence.scan"
        self.invoke("project","apply","--project",project,"--preset","physics-safe","--config",patch,"--save",edited)
        out = self.inspect(edited)["pages"][0]["settings"]["output"]
        self.assertEqual(out["despeckle"],1.5); self.assertTrue(out["normalize_color"])
        unknown = self.config(rules=[{"select":{"pages":[99]},"settings":{"output":{"despeckle":2}}}])
        self.invoke("project","apply","--project",project,"--config",unknown,"--save",self.root / "bad.scan",accepted=(2,))

    def test_missing_metadata_dpi_repaired_by_v2(self):
        Image.new("RGB",(600,800),"white").save(self.inputs / "001.png")
        config = self.config(defaults={"input":{"dpi":[180,160]},"deskew":{"mode":"off"},"content":{"page_mode":"off","content_mode":"off"}})
        project = self.project(config); info = self.inspect(project)["pages"][0]["settings"]
        self.assertEqual(info["input"]["dpi"],[180,160]); self.assertEqual(info["output"]["dpi"],[180,160])
        self.invoke("process","--project",project,"--output",self.root / "dpi-output")
        with Image.open(self.root / "dpi-output/001.png") as image: self.assertEqual(image.size,(600,800))

    def test_review_fixes_split_aggregate_and_final_previews(self):
        image = Image.new("RGB",(1200,800),"white"); image.paste("red",(0,0,600,800)); image.paste("blue",(600,0,1200,800))
        image.save(self.inputs / "001.png",dpi=(150,150))
        base = self.config(defaults={"deskew":{"mode":"off"},"content":{"page_mode":"off","content_mode":"off"},"layout":{"match_size":True}})
        original = self.root / "single"
        self.invoke("analyze","--input",self.inputs,"--config",base,"--output",original)
        split = self.config(defaults={"split":{"layout":"two","mode":"manual","space":"oriented","cutters":[[[600,0],[600,800]]]},
            "deskew":{"mode":"off"},"content":{"page_mode":"off","content_mode":"off"},"layout":{"match_size":True,"margins_mm":{"left":0,"right":0,"top":0,"bottom":0}}})
        output = self.root / "split-layout"
        self.invoke("preview","--project",original / "project.scan","--config",split,"--stage","layout","--output",output)
        report = json.loads((output / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(len(report["pages"]),2)
        for index,page in enumerate(report["pages"]):
            with Image.open(page["preview"]) as preview:
                self.assertLess(preview.width,650) # old single's 1200px width must leave the aggregate
                r,g,b = preview.convert("RGB").getpixel((preview.width//2,preview.height//2))
                self.assertGreater(r if index == 0 else b,200)
                self.assertLess(b if index == 0 else r,50)
        split_preview = self.root / "split-preview"
        self.invoke("preview","--project",output / "project.scan","--stage","split","--output",split_preview)
        r = json.loads((split_preview / "report.json").read_text(encoding="utf-8"))
        self.assertNotEqual(r["pages"][0]["preview"],r["pages"][1]["preview"])
        for page in r["pages"]:
            with Image.open(page["preview"]) as preview: self.assertLess(preview.width,650)
        margins = self.config(defaults={"layout":{"margins_mm":{"left":10,"right":10},"match_size":False}})
        enlarged = self.root / "margins"
        self.invoke("preview","--project",output / "project.scan","--config",margins,"--stage","layout","--output",enlarged)
        r = json.loads((enlarged / "report.json").read_text(encoding="utf-8"))
        with Image.open(r["pages"][0]["preview"]) as preview: self.assertGreater(preview.width,700)

    def test_actual_gui_project_roundtrip(self):
        if not GUI or not GUI.is_file(): self.skipTest("Build with BUILD_TESTS and pass --gui for actual GUI roundtrip")
        legacy.fixture(self.inputs / "001.png")
        config = self.config(defaults={"split":{"layout":"two"},"deskew":{"mode":"off"},
            "content":{"page_mode":"off","content_mode":"off"},"output":{"mode":"mixed","despeckle":1.2},
            "fill_zones":[{"space":"source","points":[[0,0],[20,0],[20,20],[0,20]],"color":"#00ff00"}]},
            project={"freeze_layout":True,"frozen_size_mm":[100,140]})
        project = self.project(config); before = self.inspect(project)
        result = subprocess.run([str(GUI),str(project)],capture_output=True,text=True,encoding="utf-8",timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        after = self.inspect(project)
        self.assertEqual(after["project"]["reading_direction"],"rtl")
        self.assertEqual(after["project"]["frozen_size_mm"],[100,140])
        self.assertEqual({p["id"]:p["settings"] for p in after["pages"]},{p["id"]:p["settings"] for p in before["pages"]})

    def test_pdf_spread_recovery_and_processed_dimensions(self):
        directory = self.root / "spread-pdfs"; directory.mkdir()
        source = directory / "blank.pdf"
        with pymupdf.open() as pdf:
            pdf.new_page(width=400,height=240); pdf.set_toc([[1,"blank",1]]); pdf.save(source)
        source_hash = legacy.digest(source)
        config = self.config(defaults={"split":{"layout":"two"}})
        wrapper = legacy.ROOT / "scripts/process_pdf_folder.py"
        output = self.root / "recovery"
        args = [sys.executable,str(wrapper),"--pdf-dir",str(directory),"--cli",str(CLI),"--output-dir",str(output),"--dpi","100","--config",str(config)]
        result = subprocess.run(args,capture_output=True,text=True,encoding="utf-8")
        self.assertEqual(result.returncode,1,result.stdout+result.stderr)
        with pymupdf.open(output / "blank.deskew.pdf") as pdf:
            self.assertEqual(pdf.page_count,1)
            self.assertEqual(pdf.get_toc(),[[1,"blank",1]])
            self.assertEqual(tuple(pdf[0].rect), (0,0,400,240))
        self.assertEqual(legacy.digest(source),source_hash)
        config = self.config(defaults={"split":{"layout":"two"},"orientation":{"rotation":90},
            "deskew":{"mode":"off","oblique_mode":"off"},"content":{"page_mode":"off","content_mode":"off"},
            "layout":{"margins_mm":{"left":10,"right":10}},"output":{"dpi":[100,100]}})
        args[-1] = str(config); args[args.index("--output-dir")+1] = str(self.root / "processed-size")
        result = subprocess.run(args+["--page-size","processed"],capture_output=True,text=True,encoding="utf-8")
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        with pymupdf.open(self.root / "processed-size/blank.deskew.pdf") as pdf:
            self.assertEqual(pdf.page_count,2)
            # 120pt rotated half + 20mm horizontal margins (rounding below 2px).
            self.assertAlmostEqual(pdf[0].rect.width,120+20*72/25.4,delta=1.5)
            self.assertAlmostEqual(pdf[0].rect.height,400,delta=1.5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cli",type=Path,required=True)
    parser.add_argument("--artifacts",type=Path)
    parser.add_argument("--gui",type=Path)
    options, rest = parser.parse_known_args()
    CLI = options.cli.resolve(); ARTIFACTS = options.artifacts
    GUI = options.gui.resolve() if options.gui else None
    if ARTIFACTS: ARTIFACTS.mkdir(parents=True,exist_ok=True)
    unittest.main(argv=[sys.argv[0],*rest])
