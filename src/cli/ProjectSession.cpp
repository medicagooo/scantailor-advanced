// Copyright (C) 2026. Distributed under the GNU GPLv3 license.
#include "ProjectSession.h"
#include "BatchRunner.h"
#include <core/StageSequence.h>
#include <core/ProjectPages.h>
#include <core/ProjectReader.h>
#include <core/ProjectWriter.h>
#include <core/ImageFileInfo.h>
#include <core/ImageInfo.h>
#include <core/ImageMetadataLoader.h>
#include <core/DefaultParams.h>
#include <core/DefaultParamsProvider.h>
#include <core/PageSelectionAccessor.h>
#include <core/PageSequence.h>
#include <core/AbstractRelinker.h>
#include <core/RelinkablePath.h>
#include <core/filters/page_layout/Settings.h>
#include <core/filters/output/Settings.h>
#include <QFile>
#include <QDir>
#include <QDomDocument>
#include <QJsonDocument>
#include <QSaveFile>
#include <QCollator>
#include <QLockFile>
#include <QRegularExpression>
#include <QCryptographicHash>
#include <algorithm>
#include <set>
#include <stdexcept>
#include <functional>
namespace cli {
namespace {
void ensure(bool ok, const QString& error) { if (!ok) throw std::invalid_argument(error.toStdString()); }
class Selection final : public PageSelectionProvider {
 public:
  explicit Selection(std::shared_ptr<ProjectPages> p) : pages(std::move(p)) {}
  PageSequence allPages() const override { return pages->toPageSequence(PAGE_VIEW); }
  std::set<PageId> selectedPages() const override { return allPages().selectAll(); }
  std::vector<PageRange> selectedRanges() const override { return {}; }
 private: std::shared_ptr<ProjectPages> pages;
};
QString pathKey(const QString& path) {
  const auto canonical = QFileInfo(path).canonicalFilePath();
  return (canonical.isEmpty() ? absolutePath(path) : canonical).toCaseFolded();
}
QByteArray fileHash(const QString& path) {
  QFile file(path); ensure(file.open(QIODevice::ReadOnly), "Cannot read protected input: " + path);
  QCryptographicHash hash(QCryptographicHash::Sha256); ensure(hash.addData(&file), "Cannot hash input: " + path); return hash.result();
}
void keys(const QJsonObject& object, const QStringList& allowed) {
  for (const auto& key : object.keys()) ensure(allowed.contains(key), "Unknown operation field: " + key);
}
std::vector<ImageFileInfo> readFiles(const QStringList& paths, int overrideDpi, QJsonArray* errors = nullptr) {
  std::vector<ImageFileInfo> files; std::set<QString> seen;
  for (const auto& name : paths) {
    const auto path = absolutePath(name);
    ensure(seen.insert(pathKey(path)).second, "Duplicate input image: " + path);
    std::vector<ImageMetadata> images;
    const auto result = ImageMetadataLoader::load(path, [&](const ImageMetadata& m) { images.push_back(m); });
    if (result != ImageMetadataLoader::LOADED || images.empty()) {
      if (!errors) throw std::invalid_argument(("Cannot read image: " + path).toStdString());
      QJsonObject error{{"event", "import_error"}, {"input", path}, {"status", "error"}, {"message", "Cannot read image metadata"}};
      errors->append(error); emitEvent(error); continue;
    }
    bool valid = true;
    for (auto& m : images) { if (overrideDpi) m.setDpi(Dpi(overrideDpi, overrideDpi)); if (!m.isDpiOK()) valid = false; }
    // A v2 per-image DPI override may fix metadata after import. Processing
    // validates final metadata after applying the complete configuration.
    Q_UNUSED(valid);
    files.emplace_back(QFileInfo(path), images);
  }
  return files;
}
}
QString absolutePath(const QString& path) { return QDir::cleanPath(QFileInfo(path).absoluteFilePath()); }
QJsonObject loadJsonObject(const QString& path) {
  QFile file(path); ensure(file.open(QIODevice::ReadOnly), "Cannot open JSON: " + path);
  QJsonParseError error; auto doc = QJsonDocument::fromJson(file.readAll(), &error);
  ensure(error.error == QJsonParseError::NoError && doc.isObject(), "Invalid JSON object: " + path); return doc.object();
}
void saveJsonObject(const QString& path, const QJsonObject& value) {
  QSaveFile file(path); ensure(file.open(QIODevice::WriteOnly), "Cannot open output: " + path);
  const auto bytes = QJsonDocument(value).toJson(); ensure(file.write(bytes) == bytes.size() && file.commit(), "Cannot save: " + path);
}
ProjectSession::ProjectSession(const QJsonObject& args, const QString& outputDir)
    : newProject(args.value("project").toString().isEmpty()), config(args.value("configuration").toObject()), options(args) {
  if (!config.isEmpty()) processing::validateConfiguration(config);
  auto defaults = std::make_unique<DefaultParams>();
  auto split = defaults->getPageSplitParams(); split.setLayoutType(page_split::SINGLE_PAGE_UNCUT); defaults->setPageSplitParams(split);
  DefaultParamsProvider::getInstance().setParams(std::move(defaults), "CLI");
  disambiguator = std::make_shared<FileNameDisambiguator>();
  if (!newProject) {
    const auto path = absolutePath(args["project"].toString()); QFile file(path);
    ensure(file.open(QIODevice::ReadOnly), "Cannot open project: " + path);
    const auto bytes = file.readAll(); originalProjectHash = QCryptographicHash::hash(bytes, QCryptographicHash::Sha256);
    QDomDocument doc; ensure(bool(doc.setContent(bytes)), "Invalid project XML");
    reader = std::make_unique<ProjectReader>(doc, path); ensure(reader->success(), "Unsupported or empty project");
    pages = reader->pages(); disambiguator = reader->namingDisambiguator();
  } else {
    QStringList paths;
    QMap<QString, QString> explicitIds;
    if (args.contains("manifest")) {
      const auto path = absolutePath(args["manifest"].toString()); const auto manifest = loadJsonObject(path);
      keys(manifest, {"schema_version", "files"}); ensure(manifest["schema_version"] == 1 && manifest["files"].isArray(), "Manifest requires schema_version=1 and files array");
      for (const auto& value : manifest["files"].toArray()) {
        QString fileName;
        if (value.isString()) fileName = value.toString();
        else {
          ensure(value.isObject(), "Manifest files must be strings or {path, stable_id} objects");
          const auto item = value.toObject(); keys(item, {"path", "stable_id"});
          ensure(item["path"].isString(), "Manifest path must be a string"); fileName = item["path"].toString();
          ensure(item["stable_id"].isString() && QRegularExpression("^[A-Za-z0-9_-]{1,128}$").match(item["stable_id"].toString()).hasMatch(), "Invalid stable_id");
          explicitIds[pathKey(QDir(QFileInfo(path).absolutePath()).absoluteFilePath(fileName))] = item["stable_id"].toString();
        }
        ensure(!fileName.isEmpty(), "Manifest path must not be empty");
        paths << QDir(QFileInfo(path).absolutePath()).absoluteFilePath(fileName);
      }
    } else {
      ensure(args.contains("input"), "Specify --input, --manifest or --project");
      const auto input = absolutePath(args["input"].toString()); ensure(QFileInfo(input).isDir(), "Input must be an image directory");
      auto files = QDir(input).entryInfoList({"*.png", "*.tif", "*.tiff", "*.jpg", "*.jpeg", "*.bmp"}, QDir::Files);
      QCollator collator(QLocale::c()); collator.setNumericMode(true); collator.setCaseSensitivity(Qt::CaseInsensitive);
      std::sort(files.begin(), files.end(), [&](const QFileInfo& a, const QFileInfo& b) { auto n = collator.compare(a.fileName(), b.fileName()); return n ? n < 0 : a.fileName() < b.fileName(); });
      for (const auto& f : files) paths << f.absoluteFilePath();
    }
    ensure(!paths.empty(), "No supported input images");
    const auto files = readFiles(paths, args["dpi"].toInt(), &importErrors); ensure(!files.empty(), "No readable images");
    pages = std::make_shared<ProjectPages>(files, ProjectPages::ONE_PAGE, Qt::LeftToRight);
    for (const auto& page : pages->toPageSequence(IMAGE_VIEW)) {
      disambiguator->registerFile(page.imageId().filePath());
      const auto stable = explicitIds.value(pathKey(page.imageId().filePath()));
      if (!stable.isEmpty()) pages->setStableImageId(page.imageId(), stable + (page.imageId().page() ? "-" + QString::number(page.imageId().page()) : ""));
    }
  }
  auto selection = std::make_shared<Selection>(pages);
  stages = std::make_shared<StageSequence>(pages, PageSelectionAccessor(selection));
  if (reader) reader->readFilterSettings(stages->filters());
  if (reader) for (const auto& p : pages->toPageSequence(PAGE_VIEW)) {
    const auto settings = processing::inspect(*stages,p), content = settings["content"].toObject();
    if (content["page_mode"] == "manual" || content["content_mode"] == "manual")
      originalManualGeometry[processing::pageId(*pages,p)] = settings["_geometry"].toObject()["basis"];
  }
  if (args.contains("dpi")) for (const auto& p : pages->toPageSequence(IMAGE_VIEW)) {
    auto m = p.metadata(); m.setDpi(Dpi(args["dpi"].toInt(), args["dpi"].toInt())); pages->updateImageMetadata(p.imageId(), m);
  }
  auto base = (newProject || config.contains("preset") || args.contains("preset")) ? physicsPreset() : QJsonObject();
  if (config.contains("preset") || args.contains("preset")) base["preset"] = "physics-safe";
  for (const auto& p : pages->toPageSequence(PAGE_VIEW)) configureLegacyPage(stages, p, base, newProject);
  auto projectConfig = config;
  auto projectSettings = config["project"].toObject(); projectSettings.remove("freeze_layout"); projectConfig["project"] = projectSettings;
  processing::applyProject(projectConfig, stages, pages);
  Q_UNUSED(outputDir);
  validateIdentities();
}
ProjectSession::~ProjectSession() = default;
OutputFileNameGenerator ProjectSession::names(const QString& outputDir) const { return {disambiguator, outputDir, pages->layoutDirection()}; }
void ProjectSession::validateIdentities() const {
  std::set<QString> ids, paths;
  for (const auto& p : pages->toPageSequence(IMAGE_VIEW)) {
    ensure(QRegularExpression("^[A-Za-z0-9_-]{1,128}$").match(pages->stableImageId(p.imageId())).hasMatch(), "Invalid stable image ID in project");
    ensure(ids.insert(pages->stableImageId(p.imageId())).second, "Duplicate stable image ID in project");
    ensure(paths.insert(pathKey(p.imageId().filePath()) + "#" + QString::number(p.imageId().page())).second, "Duplicate image in project");
  }
}
QJsonObject ProjectSession::settingsFor(const PageInfo& page, QJsonObject* origins) const {
  int pageNumber = 0, imageNumber = 0, n = 0;
  for (const auto& p : pages->toPageSequence(PAGE_VIEW)) { ++n; if (p.id() == page.id()) pageNumber = n; }
  n = 0; for (const auto& p : pages->toPageSequence(IMAGE_VIEW)) { ++n; if (p.imageId() == page.imageId()) imageNumber = n; }
  return processing::resolve(config, *pages, page, pageNumber, imageNumber, origins);
}
void ProjectSession::validateSelectors() const {
  const auto logical = pages->toPageSequence(PAGE_VIEW), images = pages->toPageSequence(IMAGE_VIEW);
  QJsonArray pageNumbers, imageNumbers, ids, imageIds;
  int i = 0; for (const auto& p : logical) { pageNumbers.append(++i); ids.append(processing::pageId(*pages, p)); }
  i = 0; for (const auto& p : images) { imageNumbers.append(++i); imageIds.append(pages->stableImageId(p.imageId())); }
  const QJsonObject available{{"pages", pageNumbers}, {"images", imageNumbers}, {"ids", ids}, {"image_ids", imageIds}};
  int ruleNumber = 0;
  for (const auto& value : config["rules"].toArray()) {
    const auto selector = value.toObject()["select"].toObject();
    for (const auto& key : available.keys()) for (const auto& v : selector[key].toArray())
      ensure(available[key].toArray().contains(v), "Unknown selector in rule " + QString::number(ruleNumber) + ": " + key);
    bool matched = false; int pageNumber = 0;
    for (const auto& p : logical) {
      int imageNumber = 0, n = 0; for (const auto& image : images) { ++n; if (image.imageId() == p.imageId()) imageNumber = n; }
      if (processing::matches(selector, *pages, p, ++pageNumber, imageNumber)) matched = true;
    }
    ensure(matched, "Selector matches no pages in rule " + QString::number(ruleNumber)); ++ruleNumber;
  }
}
void ProjectSession::validateManualGeometry() const {
  for (const auto& page : pages->toPageSequence(PAGE_VIEW)) {
    const auto id = processing::pageId(*pages,page); if (!originalManualGeometry.contains(id)) continue;
    const auto settings = processing::inspect(*stages,page);
    if (originalManualGeometry[id] == settings["_geometry"].toObject()["basis"]) continue;
    const auto content = settings["content"].toObject(), replacement = settingsFor(page)["content"].toObject();
    // A saved rectangle belongs to its original stage geometry, not just its page ID.
    // Source-space zones/curves do not need this guard because their pixels remain stable.
    if (content["page_mode"] == "manual") ensure(replacement.contains("page_rect"), "Manual page rectangle became stale for " + id + "; analyze through deskew and supply a new rectangle");
    if (content["content_mode"] == "manual") ensure(replacement.contains("content_rect"), "Manual content rectangle became stale for " + id + "; analyze through deskew and supply a new rectangle");
  }
}
void ProjectSession::applyConfiguration(processing::Scope scope, const QStringList& sections) {
  const auto sequence = pages->toPageSequence(scope == processing::Scope::Source ? IMAGE_VIEW : PAGE_VIEW);
  for (const auto& p : sequence) {
    auto settings = settingsFor(p);
    if (!sections.isEmpty()) for (const auto& key : settings.keys()) if (!sections.contains(key)) settings.remove(key);
    // Per-source v2 DPI may repair missing metadata after initial import. New
    // logical outputs inherit that final DPI unless explicitly overridden below.
    if (newProject && scope == processing::Scope::Logical && (sections.empty() || sections.contains("output")))
      stages->outputFilter()->processingSettings()->setDpi(p.id(),p.metadata().dpi());
    processing::apply(settings, stages, pages, p, scope);
    // Explicit v1 CLI arguments remain the final override. Applied before
    // source configuration too, then input DPI is finalized here.
    if (scope == processing::Scope::Source) {
      QJsonObject sourceArgs; if (options.contains("rotate")) sourceArgs["rotate"] = options["rotate"];
      configureLegacyPage(stages, p, sourceArgs, false);
      if (options.contains("dpi")) { auto m = p.metadata(); m.setDpi(Dpi(options["dpi"].toInt(), options["dpi"].toInt())); pages->updateImageMetadata(p.imageId(), m); }
    } else {
      auto legacy = options;
      legacy.remove("preset"); // Presets are the base layer, before v2 defaults and page rules.
      if (!sections.isEmpty()) {
        if (!sections.contains("deskew")) { legacy.remove("deskew"); legacy.remove("deskew-angle"); }
        if (!sections.contains("content")) { legacy.remove("page-detection"); legacy.remove("content-detection"); }
        if (!sections.contains("layout")) legacy.remove("margin-mm");
        if (!sections.contains("output")) for (const auto& k : {"output-dpi", "color-mode", "dewarp", "fill-margins", "fill-offcut", "preset"}) legacy.remove(k);
      }
      configureLegacyPage(stages, p, legacy, false);
    }
  }
}
QJsonObject ProjectSession::inspect(bool exportConfig) const {
  QJsonArray list, rules; int n = 0;
  for (const auto& p : pages->toPageSequence(PAGE_VIEW)) {
    auto settings = processing::inspect(*stages, p); QJsonObject origins; settingsFor(p, &origins);
    QJsonObject sources;
    std::function<void(const QJsonObject&,const QString&)> inherited = [&](const QJsonObject& object,const QString& prefix) {
      for (auto i = object.begin(); i != object.end(); ++i) {
        if (i.key().startsWith('_')) continue;
        const auto key = prefix.isEmpty() ? i.key() : prefix + "." + i.key();
        if (i->isObject()) inherited(i->toObject(),key); else sources[key] = newProject ? "new-project-default" : "project";
      }
    };
    inherited(settings,{});
    const QMap<QString,QStringList> legacyFields{
      {"dpi",{"input.dpi"}}, {"rotate",{"orientation.rotation"}}, {"deskew",{"deskew.mode","deskew.angle","deskew.oblique_mode","deskew.oblique_angle"}},
      {"deskew-angle",{"deskew.mode","deskew.angle"}}, {"page-detection",{"content.page_mode"}}, {"content-detection",{"content.content_mode"}},
      {"margin-mm",{"layout.margins_mm.left","layout.margins_mm.right","layout.margins_mm.top","layout.margins_mm.bottom","layout.match_size","layout.auto_margins","layout.horizontal","layout.vertical"}},
      {"output-dpi",{"output.dpi"}}, {"color-mode",{"output.mode"}}, {"dewarp",{"output.dewarp","output.post_deskew","output.post_deskew_angle"}},
      {"fill-margins",{"output.fill_margins","output.fill_color"}}, {"fill-offcut",{"output.fill_offcut","output.fill_outside_page","output.fill_color"}}};
    if (newProject || config.contains("preset") || options.contains("preset")) {
      for (const auto& key : physicsPreset().keys()) for (const auto& field : legacyFields.value(key)) sources[field] = "preset:physics-safe";
      for (const auto& field : {"output.normalize_color","output.wiener_coefficient","output.posterize","output.despeckle","output.split_output","output.foreground","output.original_background"}) sources[field] = "preset:physics-safe";
    }
    for (auto i = origins.begin(); i != origins.end(); ++i) sources[i.key()] = i.value();
    for (const auto& key : legacyFields.keys()) if (options.contains(key)) for (const auto& field : legacyFields[key]) sources[field] = "cli-or-v1:" + key;
    list.append(QJsonObject{{"number", ++n}, {"id", processing::pageId(*pages, p)}, {"image_id", pages->stableImageId(p.imageId())}, {"input", p.imageId().filePath()}, {"image_page", p.imageId().page()}, {"settings", settings}, {"overrides", origins}, {"setting_sources",sources}});
    if (exportConfig) {
      settings.remove("_geometry"); settings.remove("_detected");
      auto skew = settings["deskew"].toObject(); if (skew["mode"] == "auto") skew.remove("angle"); if (skew["oblique_mode"] == "auto") skew.remove("oblique_angle"); settings["deskew"] = skew;
      QJsonObject source;
      for (const auto& key : {"input", "orientation", "split"}) { source[key] = settings.take(key); }
      // Source entries are emitted once per image by export below.
      rules.append(QJsonObject{{"select", QJsonObject{{"ids", QJsonArray{processing::pageId(*pages, p)}}}}, {"settings", settings}});
    }
  }
  if (exportConfig) {
    for (const auto& p : pages->toPageSequence(IMAGE_VIEW)) {
      auto settings = processing::inspect(*stages, p); QJsonObject source;
      for (const auto& key : {"input", "orientation", "split"}) source[key] = settings[key];
      rules.append(QJsonObject{{"select", QJsonObject{{"image_ids", QJsonArray{pages->stableImageId(p.imageId())}}}}, {"settings", source}});
    }
    QJsonObject result{{"schema_version", 2}, {"project", processing::inspectProject(*stages, *pages)}, {"rules", rules}};
    if (config.contains("image_encoding")) result["image_encoding"] = config["image_encoding"];
    return result;
  }
  return {{"schema_version", 2}, {"project", processing::inspectProject(*stages, *pages)}, {"pages", list}, {"import_errors", importErrors}};
}
void ProjectSession::validateSaveTarget(const QString& path, bool projectFile) const {
  for (const auto& p : pages->toPageSequence(IMAGE_VIEW)) ensure(pathKey(path) != pathKey(p.imageId().filePath()), "Cannot overwrite a source image");
  for (const auto& key : {"manifest", "operations", "geometry", "_config_path", "project"}) {
    const auto input = options[key].toString();
    if (!input.isEmpty() && !(projectFile && QString(key) == "project"))
      ensure(pathKey(path) != pathKey(input), "Cannot overwrite input: " + QString(key));
  }
}
void ProjectSession::save(const QString& path, const QString& outputDir, bool overwrite) const {
  const auto target = absolutePath(path);
  validateSaveTarget(target, true);
  ensure(QDir().mkpath(QFileInfo(target).absolutePath()), "Cannot create project parent");
  QLockFile lock(target + ".lock"); lock.setStaleLockTime(0); ensure(lock.tryLock(), "Project is locked");
  ensure(!QFileInfo::exists(target) || overwrite, "Project exists; choose another --save or specify --overwrite");
  if (!newProject && pathKey(target) == pathKey(options["project"].toString()))
    ensure(fileHash(target) == originalProjectHash, "Project changed during processing; save to another path");
  ensure(ProjectWriter(pages, SelectedPage(), names(outputDir)).write(target, stages->filters()), "Cannot write project");
}
void ProjectSession::insert(const QJsonObject& op) {
  keys(op, {"type", "files", "before_image", "after_image", "dpi"});
  ensure(op["files"].isArray() && !op["files"].toArray().empty(), "insert requires files");
  ensure(!(op.contains("before_image") && op.contains("after_image")), "Choose before_image or after_image");
  QStringList paths; for (const auto& v : op["files"].toArray()) { ensure(v.isString(), "files must contain strings"); paths << v.toString(); }
  const auto anchor = op.contains("before_image") ? op["before_image"] : op["after_image"];
  ImageId existing;
  for (const auto& p : pages->toPageSequence(IMAGE_VIEW)) if (pages->stableImageId(p.imageId()) == anchor.toString()) existing = p.imageId();
  ensure(anchor.isUndefined() || !existing.isNull(), "Unknown insertion image ID");
  int d = op["dpi"].toInt(); ensure(!op.contains("dpi") || (op["dpi"].isDouble() && d >= 72 && d <= 1200 && d == op["dpi"].toDouble()), "Invalid insert DPI");
  const auto files = readFiles(paths, d);
  auto inserted = std::make_shared<ProjectPages>(files, ProjectPages::ONE_PAGE, pages->layoutDirection());
  std::set<QString> known;
  for (const auto& p : pages->toPageSequence(IMAGE_VIEW)) known.insert(pathKey(p.imageId().filePath()));
  auto seq = inserted->toPageSequence(IMAGE_VIEW); std::vector<PageInfo> ordered(seq.begin(), seq.end());
  if (op.contains("after_image")) std::reverse(ordered.begin(), ordered.end());
  for (const auto& p : ordered) {
    ensure(!known.count(pathKey(p.imageId().filePath())), "Image file already belongs to project");
    pages->insertImage(ImageInfo(p.imageId(), p.metadata(), 1, false, false), op.contains("after_image") ? AFTER : BEFORE, existing, IMAGE_VIEW);
    disambiguator->registerFile(p.imageId().filePath());
    configureLegacyPage(stages, p, physicsPreset(), true);
  }
}
void ProjectSession::edit(const QJsonObject& ops) {
  keys(ops, {"schema_version", "operations"}); ensure(ops["schema_version"] == 1 && ops["operations"].isArray(), "Operations require schema_version=1 and operations array");
  for (const auto& value : ops["operations"].toArray()) {
    ensure(value.isObject(), "Operation must be an object"); auto op = value.toObject(); auto type = op["type"].toString();
    if (type == "insert") insert(op);
    else if (type == "remove") {
      keys(op, {"type", "ids"}); ensure(op["ids"].isArray() && !op["ids"].toArray().empty(), "remove requires ids"); std::set<PageId> selected;
      for (const auto& id : op["ids"].toArray()) {
        bool found = false; for (const auto& p : pages->toPageSequence(PAGE_VIEW)) if (processing::pageId(*pages, p) == id.toString()) { selected.insert(p.id()); found = true; }
        ensure(found, "Unknown logical page ID: " + id.toString());
      }
      ensure(selected.size() < size_t(pages->toPageSequence(PAGE_VIEW).numPages()), "Cannot remove every page"); pages->removePages(selected);
    } else if (type == "restore-half") {
      keys(op, {"type", "image_id", "side"}); ensure(op["side"] == "left" || op["side"] == "right", "restore-half side must be left or right"); bool found = false;
      for (const auto& p : pages->toPageSequence(IMAGE_VIEW)) if (pages->stableImageId(p.imageId()) == op["image_id"].toString()) {
        ensure(!pages->unremovePage(PageId(p.imageId(), op["side"] == "left" ? PageId::LEFT_PAGE : PageId::RIGHT_PAGE)).isNull(), "Half cannot be restored"); found = true; break;
      }
      ensure(found, "Unknown image ID");
    } else if (type == "reorder") {
      keys(op, {"type", "image_ids"}); ensure(op["image_ids"].isArray(), "reorder requires image_ids"); std::vector<ImageId> order;
      for (const auto& id : op["image_ids"].toArray()) {
        bool found = false; for (const auto& p : pages->toPageSequence(IMAGE_VIEW)) if (pages->stableImageId(p.imageId()) == id.toString()) { order.push_back(p.imageId()); found = true; }
        ensure(found, "Unknown image ID in order");
      }
      ensure(pages->reorderImages(order), "Order must contain every image exactly once");
    } else if (type == "relink") {
      keys(op, {"type", "from", "to"}); ensure(op["from"].isString() && op["to"].isString(), "relink requires from and to");
      class Relinker final : public AbstractRelinker {
       public: QString from, to;
        QString substitutionPathFor(const RelinkablePath& p) const override { return pathKey(p.normalizedPath()) == pathKey(from) ? to : p.normalizedPath(); }
      } relinker;
      relinker.from = absolutePath(op["from"].toString()); relinker.to = absolutePath(op["to"].toString());
      ensure(QFileInfo(relinker.to).isFile(), "Relink target does not exist"); bool found = false;
      for (const auto& p : pages->toPageSequence(IMAGE_VIEW)) { if (pathKey(p.imageId().filePath()) == pathKey(relinker.from)) found = true;
        else ensure(pathKey(p.imageId().filePath()) != pathKey(relinker.to), "Relink would combine different sources"); }
      ensure(found, "Relink source does not belong to project");
      const auto info = readFiles({relinker.to}, 0); ensure(!info.empty(), "Invalid relink target");
      for (const auto& p : pages->toPageSequence(IMAGE_VIEW)) if (pathKey(p.imageId().filePath()) == pathKey(relinker.from)) {
        ensure((info[0].imageInfo().size() > 1) == (p.imageId().page() > 0), "Relink cannot change single/multipage identity");
        const int index = info[0].imageInfo().size() > 1 ? p.imageId().page() - 1 : 0;
        ensure(index >= 0 && index < int(info[0].imageInfo().size()) && info[0].imageInfo()[index].size() == p.metadata().size(), "Relink target dimensions/page count differ; import as new images instead");
      }
      pages->performRelinking(relinker); stages->performRelinking(relinker); disambiguator->performRelinking(relinker);
    } else ensure(false, "Unknown operation type: " + type);
  }
  validateIdentities();
}
int projectCommand(const QString& command, const QJsonObject& options) {
  const auto target = options["save"].toString(options["save-project"].toString());
  const auto output = absolutePath(options["output"].toString(QFileInfo(target.isEmpty() ? options["project"].toString() : target).absolutePath() + "/out"));
  ProjectSession session(options, output);
  if (options.contains("operations")) session.edit(loadJsonObject(options["operations"].toString()));
  session.applyConfiguration(processing::Scope::Source);
  session.stages->pageLayoutFilter()->processingSettings()->removePagesMissingFrom(session.pages->toPageSequence(PAGE_VIEW));
  session.validateSelectors();
  session.applyConfiguration(processing::Scope::Logical);
  session.validateManualGeometry();
  if (session.config["project"].toObject().contains("freeze_layout")) processing::applyProject(session.config, session.stages, session.pages);
  if (command == "project create" || command == "project apply" || command == "project edit") {
    ensure(!target.isEmpty(), "--save is required");
    if (!options["dry-run"].toBool()) session.save(target, output, options["overwrite"].toBool());
    auto report = session.inspect(); report["event"] = options["dry-run"].toBool() ? "project_plan" : "project_saved"; report["saved_project"] = absolutePath(target); emitEvent(report);
  } else {
    auto report = command == "geometry map" ? processing::mapGeometry(*session.stages, *session.pages, loadJsonObject(options["geometry"].toString())) : session.inspect(command == "config export");
    if (!target.isEmpty()) {
      session.validateSaveTarget(target, false);
      QLockFile lock(absolutePath(target) + ".lock"); lock.setStaleLockTime(0); ensure(lock.tryLock(), "Export is locked");
      ensure(!QFileInfo::exists(target) || options["overwrite"].toBool(), "Export exists"); saveJsonObject(target, report);
    }
    emitEvent(report);
  }
  return session.importErrors.empty() ? 0 : 1;
}
}
