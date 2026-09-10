# CLI 2 business coverage and maintenance map

Request: `.branch-records/0910-cli-full/events.jsonl` / `req-full-01` (2026-09-10).
Scope: all processing settings and project operations listed in the approved P0–P5 plan.
The CLI uses `ProjectSession`, `ProcessingConfiguration`, and the existing `CompositeTaskFactory`.
GUI widgets continue to edit the same Settings/Params; we did not replace GUI controls with CLI code.

## Coverage

`F` below means `tests/cli_full_integration.py`; `L` means inherited `tests/cli_integration.py`.
Tests validate representative interactions, preservation and outputs; the parameter readback test covers every scalar output field.
The generated `config schema` is the exact supported field/type/range contract.

| GUI / business operation | CLI / schema 2 interface | Shared code and .scan storage | Evidence |
|---|---|---|---|
| New/open/save/Save As | project create/inspect/apply; --save/--overwrite; process --save-project | ProjectSession; ProjectReader/Writer, QSaveFile | F full_parameter_project_roundtrip; actual_gui_project_roundtrip; L identity_pixels_and_project_replay |
| Directory/ordered import, multipage TIFF | --input / --manifest; input.dpi [x,y] | ProjectPages, ImageMetadataLoader; images metadata | F freeze_restore_and_multipage_dpi |
| Insert/remove/restore/reorder/relink | project edit --operations; stable source/logical IDs | ProjectSession::edit, ProjectPages; stableId optional image attribute | F project_operations_preserve_identity; freeze_restore_and_multipage_dpi |
| Left/right reading order | project.reading_direction ltr/rtl | ProjectPages::layoutDirection, ProjectWriter root | F full_parameter_project_roundtrip; actual_gui_project_roundtrip |
| Global/group/page application | defaults + ordered rules + selectors | ProcessingConfiguration::resolve/apply; stage Settings | F strict_validation_and_source_scope; protected_destinations_flags_and_preset_precedence |
| Rotation/initial trimming | orientation.rotation; trim.enabled,left,top,right,bottom | fix_orientation::Settings / Params, trim in source pixels | F full_parameter_project_roundtrip; split_geometry_manual_rectangles_and_preview |
| Single/cut/spread, auto/manual lines | split.layout/mode/space/cutters | page_split::Settings, Params, PageLayout; chosen layout persists even without analyzed Params | F split_geometry_manual_rectangles_and_preview; review_fixes_split_aggregate_and_final_previews |
| Deskew and oblique/shear | deskew.mode,angle,oblique_mode,oblique_angle; project.deskew_algorithm | deskew::Settings/Params and pending auto-oblique | F full_parameter_project_roundtrip; L auto_deskew_and_fallback |
| Paper/content box and corner refinement | content.page_mode/content_mode/fine_tune/page_rect/content_rect; project.page_detection_size_mm/tolerance | select_content::Settings/Params; explicit deskew coordinate basis | F split_geometry_manual_rectangles_and_preview; full_parameter_project_roundtrip |
| Margins/alignment/size matching | layout.margins_mm/auto_margins/match_size/horizontal/vertical | page_layout::Settings/Params/Utils | F full_parameter_project_roundtrip; review_fixes_split_aggregate_and_final_previews |
| Freeze reference size and guides | project.freeze_layout/frozen_size_mm/guides/show_middle_rect | page_layout::Settings + Filter save/load; optional frozenWidthMM/frozenHeightMM | F freeze_restore_and_multipage_dpi; actual_gui_project_roundtrip |
| Output mode/DPI/polarity/filling | output.mode,dpi,black_on_white,fill_offcut,fill_outside_page,fill_margins,fill_color | output::Params/ColorParams/ColorCommonOptions | F full_parameter_project_roundtrip; L identity_pixels_and_project_replay |
| All 10 binarizers and tuning | threshold_method,threshold,threshold_window,sauvola_coefficient,wolf_coefficient,wolf_lower,wolf_upper | output::BlackWhiteOptions; Otsu/Sauvola/Wolf/Fox/Window/Bradley/Grad/EdgePlus/BlurDiv/EdgeDiv | F all_binarization_methods_and_output_layers |
| Image cleanup | normalize_color,normalize_bw,wiener_coefficient,wiener_window,savitzky_golay,morphological_smoothing,despeckle | output::ColorCommonOptions/BlackWhiteOptions/Params | F full_parameter_project_roundtrip; all_binarization_methods_and_output_layers |
| Segmentation/posterization | color_segmentation,segment_noise,segment_red/green/blue,posterize,posterize_level/normalize/force_bw | ColorSegmenterOptions, PosterizationOptions | F full_parameter_project_roundtrip |
| Automatic/manual picture regions | picture_shape/sensitivity/high_sensitivity; picture_zones space/points/layer/category | PictureShapeOptions, ZoneSet, PictureLayerProperty, ZoneCategoryProperty | F all_binarization_methods_and_output_layers; full_parameter_project_roundtrip |
| Fill regions | fill_zones space/points/color | ZoneSet, SerializableSpline, FillColorProperty | F all_binarization_methods_and_output_layers; actual_gui_project_roundtrip |
| Dewarp/off/auto/manual/marginal | dewarp,depth,post_deskew,post_deskew_angle,distortion_model | DewarpingOptions, DistortionModel, Curve, XSpline; optional tension on saved control points | F curves_geometry_and_dewarped_layers |
| Foreground/background/original background | split_output,foreground,original_background | SplittingOptions; OutputGenerator and Task; mask retained through final use | F all_binarization_methods_and_output_layers; curves_geometry_and_dewarped_layers |
| Stage runs, selection and previews | analyze --through; preview --stage/--pages; process --pages | BatchRunner phase boundaries; logical-page stageTransformation; layout cleanup | F review_fixes_split_aggregate_and_final_previews; split_geometry_manual_rectangles_and_preview |
| Geometry import/export/conversion | config export; geometry map | ProcessingConfiguration::mapGeometry; ImageTransformation, page_layout::Utils, DewarpingPointMapper | F curves_geometry_and_dewarped_layers; split_geometry_manual_rectangles_and_preview |
| Review and corrections | review --html; project apply then process; preserve/report policy | BatchRunner metrics and artifacts; stable ID rules | L auto_deskew_and_fallback; F PDF recovery, selection and geometry tests |
| Cancellation/resume/output verification | --resume, --overwrite, JSONL and exit codes | BatchRunner hashes/locks/checkpoints; PDF wrapper source generation hash | L cancel_and_resume; resume_tamper_and_changed_input; F layer tampering |
| PDF single/spread assembly/navigation | Process-PdfFolder.ps1; -PageSize original/processed | process_pdf_folder.py source_to_output; original source page is recovery unit | F pdf_split_mapping_and_stable_ids; pdf_spread_recovery_and_processed_dimensions; L pdf_page_order_size_and_resume |
| GUI navigation/zoom/sort/theme/language | pages list, previews, metrics/review; GUI retained in package | No effect on processing data; GUI display preferences isolated from CLI | GUI roundtrip and same-package GUI startup; no CLI theme emulation |

## Contracts and boundaries

- New source imports default to physics-safe. Existing project values survive absent overrides. Explicit presets precede v2 defaults/rules; legacy CLI scalar flags are last. `setting_sources` labels the current session's inherited/default/config/legacy source, not a historical audit trail.
- Settings are mutated only with no workers active. Source structure is resolved once per image; logical settings follow splitting. Layout analysis covers all pages even when only some outputs are requested.
- Removing/changing logical pages clears absent entries from aggregate layout. Failed images remain in the saved project; invalid layout sizes do not contaminate valid outputs.
- Manual content rectangles use explicit deskew coordinates. Export includes a geometry basis; submitting stale basis rejects the change. When omitted on an explicit replacement, the caller owns coordinate freshness. Updating a saved project with changed upstream geometry and no replacement for a manual rectangle is rejected before save/content processing. Regions and distortion curves use original source coordinates, so rotation alone does not relocate their source pixels.
- Imported images require valid effective DPI before processing. Multi-page identities and source dimensions must remain compatible across relinking. Relinking does not resample a replacement file.
- JSON arrays replace entire arrays; omit to preserve, use [] to clear zones. Unknown fields/types and incompatible combinations reject the operation. GUI range/serialization choices define output options.
- Geometry mapping uses layout/output state from the saved project. Automatic dewarping must be resolved by processing first. Points outside a transform's valid domain can fail; converting a rectangle through nonlinear geometry requires sampling its boundary.
- Preview PNGs are scaled inspection views, not lossless output. Source and final output images remain separately available. Layout preview uses final aggregate size, not progressive per-worker values.
- Split PDF fallback preserves the original source page exactly once, even if both halves fail. Processed PDF pages are raster images; original text layers/interactive objects do not survive successful raster processing.
- The `.scan` version remains readable by old code. New optional stable IDs/frozen dimensions/tensions need this version's GUI to survive subsequent saves. Missing tension fields retain the old endpoint/interior defaults.
- The actual GUI test compiles the real MainWindow sources, opens a CLI-created project, toggles reading order through its original slot, saves through its original slot, then compares IDs/settings with CLI inspection. It does not claim manual GUI screenshot QA or exhaustive visual validation of every filter combination.

## Review and repairs

Independent reviewer `bugbot` (generic review agent; dedicated Bugbot service unavailable) reported two P2 findings:

1. Early-stage previews used GUI editing transforms, so split and layout outputs did not show final geometry. Repaired by computing previews from stable logical-page settings after structural and aggregate processing; GUI updater contracts remain unchanged.
2. Removed single-page dimensions remained in aggregate layout after splitting. Repaired with the same `removePagesMissingFrom` cleanup invoked by GUI filter selection, both in processing and project editing.

Additional local regressions/debugging fixed: original-background output read a released binary mask; temporary JSON object access left a dangling QJsonValueRef; unprocessed explicit split layouts were not serialized; spline tensions were not serialized; output/export destination protection and concurrent same-project save checks; preset precedence; manual-angle false review warnings; failed unselected layout exclusion; and split record identity propagation.

Run `tests/cli_full_integration.py --cli <exe> --gui <scantailor-gui-roundtrip.exe> -v` after an offline `Build-Windows.ps1 -WithTests` build.
