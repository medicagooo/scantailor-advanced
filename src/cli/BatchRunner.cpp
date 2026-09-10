// Copyright (C) 2026. Distributed under the GNU GPLv3 license.
#include "BatchRunner.h"
#include "ProjectSession.h"
#include <core/CompositeTaskFactory.h>
#include <core/DefaultParams.h>
#include <core/DefaultParamsProvider.h>
#include <core/ImageFileInfo.h>
#include <core/ImageMetadataLoader.h>
#include <core/ImageLoader.h>
#include <core/PageSelectionAccessor.h>
#include <core/ProjectPages.h>
#include <core/ProjectReader.h>
#include <core/ProjectWriter.h>
#include <core/StageSequence.h>
#include <core/ThumbnailPixmapCache.h>
#include <core/TiffWriter.h>
#include <core/filters/output/Settings.h>
#include <core/filters/output/Utils.h>
#include <core/filters/select_content/Settings.h>
#include <core/filters/page_layout/Settings.h>
#include <core/filters/page_layout/Params.h>
#include <core/filters/fix_orientation/Settings.h>
#include <QCoreApplication>
#include <QCryptographicHash>
#include <QDir>
#include <QDomDocument>
#include <QFile>
#include <QImageReader>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLockFile>
#include <QSaveFile>
#include <QThread>
#include <QUrl>
#include <QRegularExpression>
#include <QCollator>
#include <QLocale>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <future>
#include <stdexcept>

namespace cli {
std::atomic<bool> cancelled{false};
void emitEvent(const QJsonObject& event) {
  const QByteArray line = QJsonDocument(event).toJson(QJsonDocument::Compact) + '\n';
  std::fwrite(line.constData(), 1, size_t(line.size()), stdout);
  std::fflush(stdout);
}
namespace {
QString absolute(const QString& path) { return QDir::cleanPath(QFileInfo(path).absoluteFilePath()); }
void require(bool condition, const QString& message) {
  if (!condition) throw std::runtime_error(message.toStdString());
}
QString hashFile(const QString& path) {
  QFile file(path);
  require(file.open(QIODevice::ReadOnly), "Cannot hash file: " + path);
  QCryptographicHash hash(QCryptographicHash::Sha256);
  require(hash.addData(&file), "Cannot hash file: " + path);
  return QString::fromLatin1(hash.result().toHex());
}
QJsonObject readJson(const QString& path) {
  QFile file(path);
  if (!file.exists()) return {};
  require(file.open(QIODevice::ReadOnly), "Cannot read: " + path);
  QJsonParseError error;
  const auto doc = QJsonDocument::fromJson(file.readAll(), &error);
  require(error.error == QJsonParseError::NoError && doc.isObject(), "Invalid checkpoint: " + path);
  return doc.object();
}
void writeJson(const QString& path, const QJsonObject& object) {
  QSaveFile file(path);
  require(file.open(QIODevice::WriteOnly), "Cannot write: " + path);
  auto bytes = QJsonDocument(object).toJson();
  require(file.write(bytes) == bytes.size() && file.commit(), "Cannot commit: " + path);
}
class Selection final : public PageSelectionProvider {
 public:
  explicit Selection(std::shared_ptr<ProjectPages> pages) : m_pages(std::move(pages)) {}
  PageSequence allPages() const override { return m_pages->toPageSequence(PAGE_VIEW); }
  std::set<PageId> selectedPages() const override { return allPages().selectAll(); }
  std::vector<PageRange> selectedRanges() const override { return {}; }
 private:
  std::shared_ptr<ProjectPages> m_pages;
};

QString pageKey(const PageInfo& page) {
  return absolute(page.imageId().filePath()) + "#" + QString::number(page.imageId().page())
         + ":" + QString::number(int(page.id().subPage()));
}
QJsonObject taskMetrics(const BackgroundTaskPtr& task) {
  QJsonObject obj;
  for (const auto& pair : task->metrics()) if (std::isfinite(pair.second)) obj[QString::fromStdString(pair.first)] = pair.second;
  return obj;
}
std::set<PageId> selectedPages(const QString& expression, const ProjectPages& pages) {
  const auto sequence = pages.toPageSequence(PAGE_VIEW); std::set<PageId> result;
  if (expression.isEmpty() || expression == "all") return sequence.selectAll();
  for (const auto& token : expression.split(',')) {
    if (token == "odd" || token == "even") {
      int i = 0; for (const auto& p : sequence) { ++i; if ((i % 2 == 1) == (token == "odd")) result.insert(p.id()); } continue;
    }
    const auto match = QRegularExpression("^(\\d+)(?:-(\\d+))?$").match(token);
    if (match.hasMatch()) {
      bool ok = false; int lo = match.captured(1).toInt(&ok); require(ok, "Invalid page selector");
      int hi = match.captured(2).isEmpty() ? lo : match.captured(2).toInt(&ok);
      require(ok && lo >= 1 && hi >= lo && hi <= int(sequence.numPages()), "Page selector is out of range");
      for (int i = lo; i <= hi; ++i) result.insert(sequence.pageAt(size_t(i-1)).id());
    } else {
      bool found = false; for (const auto& p : sequence) if (processing::pageId(pages, p) == token) { result.insert(p.id()); found = true; }
      require(found, "Unknown page ID: " + token);
    }
  }
  return result;
}
QJsonArray outputArtifacts(const QString& main, const output::Params& params) {
  QStringList paths{main}; const QFileInfo info(main); const auto root = info.absolutePath();
  if (params.splittingOptions().isSplitOutput()) {
    paths << QDir(output::Utils::foregroundDir(root)).filePath(info.fileName()) << QDir(output::Utils::backgroundDir(root)).filePath(info.fileName());
    if (params.splittingOptions().isOriginalBackgroundEnabled()) paths << QDir(output::Utils::originalBackgroundDir(root)).filePath(info.fileName());
  }
  QJsonArray result;
  for (const auto& p : paths) {
    require(QFileInfo::exists(p) && !ImageLoader::load(p).isNull(), "Missing or unreadable output artifact: " + p);
    result.append(QJsonObject{{"path", p}, {"sha256", hashFile(p)}});
  }
  return result;
}
bool verifiedArtifacts(const QJsonObject& record) {
  auto artifacts = record["artifacts"].toArray();
  if (artifacts.isEmpty()) artifacts.append(QJsonObject{{"path", record["output"]}, {"sha256", record["sha256"]}});
  for (const auto& value : artifacts) { const auto a = value.toObject(); const auto p = a["path"].toString(); if (!QFileInfo::exists(p) || a["sha256"].toString() != hashFile(p)) return false; }
  return true;
}
void reviewHtml(const QString& directory, const QJsonObject& report) {
  QString html = "<!doctype html><meta charset='utf-8'><title>ScanTailor review</title><style>body{font:16px sans-serif;margin:24px}article{border-top:1px solid #ccc;padding:16px 0}img{max-width:45%;max-height:700px}pre{white-space:pre-wrap}</style><h1>ScanTailor review</h1>";
  for (const auto& value : report["pages"].toArray()) {
    const auto p = value.toObject(); html += "<article><h2>" + p["id"].toString().toHtmlEscaped() + " — " + p["status"].toString().toHtmlEscaped() + "</h2>";
    html += "<p>" + p["input"].toString().toHtmlEscaped() + "</p><pre>" + QString::fromUtf8(QJsonDocument(p["metrics"].toObject()).toJson()).toHtmlEscaped() + p["message"].toString().toHtmlEscaped() + "</pre>";
    for (const auto& key : {"source_preview", "preview"}) if (p.contains(key)) html += "<img src=\"" + QUrl::fromLocalFile(p[key].toString()).toString(QUrl::FullyEncoded).toHtmlEscaped() + "\">";
    html += "</article>";
  }
  QSaveFile file(directory + "/review.html"); require(file.open(QIODevice::WriteOnly), "Cannot write review HTML"); const auto bytes = html.toUtf8(); require(file.write(bytes) == bytes.size() && file.commit(), "Cannot save review HTML");
}
}

int run(const QJsonObject& options) {
  const QString outputDir = absolute(options["output"].toString());
  const auto command = options.value("command").toString("process");
  if (command == "review") {
    const auto report = readJson(outputDir + "/report.json"); require(!report.isEmpty(), "No report in output directory");
    if (options["html"].toBool()) reviewHtml(outputDir, report);
    emitEvent(report); return report["exit_code"].toInt();
  }
  const QStringList stageNames{"orientation", "split", "deskew", "content", "layout", "output"};
  const auto through = command == "preview" ? options.value("stage").toString("output") : options.value("through").toString(command == "analyze" ? "layout" : "output");
  const int lastStage = stageNames.indexOf(through);
  require(lastStage >= 0, "Invalid processing stage");
  const bool makePreview = command == "preview" || options["html"].toBool();
  const bool fromProject = !options["project"].toString().isEmpty();
  const QString sourcePath = absolute(options[fromProject ? "project" : options.contains("manifest") ? "manifest" : "input"].toString());
  require(QFileInfo(sourcePath).exists(), "Input does not exist: " + sourcePath);
  require(fromProject || options.contains("manifest") || QFileInfo(sourcePath).isDir(), "--input must be an image directory.");
  require(fromProject || outputDir.compare(sourcePath, Qt::CaseInsensitive) != 0, "Input and output directories must differ.");
  require(QDir().mkpath(outputDir), "Cannot create output directory.");
  QLockFile lock(outputDir + "/.scantailor.lock");
  lock.setStaleLockTime(0);
  require(lock.tryLock(0), "Output directory is locked by another process.");
  const QString statePath = outputDir + "/state.json";
  const QString reportPath = outputDir + "/report.json";
  QString projectPath = absolute(options["save-project"].toString(outputDir + "/project.scan"));
  if (fromProject && projectPath.compare(sourcePath, Qt::CaseInsensitive) == 0) {
    require(!options.contains("save-project"), "Do not overwrite the input project; choose another --save-project.");
    projectPath = outputDir + "/processed.scan";
  }
  const auto prior = readJson(statePath);
  if (prior.isEmpty()) {
    const auto entries = QDir(outputDir).entryList(QDir::Files | QDir::Dirs | QDir::NoDotAndDotDot | QDir::Hidden);
    for (const auto& entry : entries)
      require(entry == ".scantailor.lock", "Use a dedicated empty output directory: " + outputDir);
  }
  require(prior.isEmpty() || prior["schema_version"].toInt() == 1, "Unsupported checkpoint schema.");
  require(prior.isEmpty() || options["resume"].toBool() || options["overwrite"].toBool(),
          "Existing job: use --resume or --overwrite.");
  if (QFileInfo(projectPath).exists())
    require((!prior.isEmpty() && prior["project"].toString() == projectPath) || options["overwrite"].toBool(),
            "Project output exists; choose another path or --overwrite.");

  ProjectSession session(options, outputDir);
  session.validateSaveTarget(projectPath, false);
  auto pages = session.pages;
  auto stages = session.stages;
  const auto importErrors = session.importErrors;
  session.applyConfiguration(processing::Scope::Source);
  if (!pages->validateDpis()) throw std::invalid_argument("Invalid DPI; specify --dpi or per-image input.dpi.");
  QJsonObject signature = options;
  for (const auto& name : {"resume", "overwrite", "jobs", "save-project"}) signature.remove(name);
  signature["binary_sha256"] = hashFile(QCoreApplication::applicationFilePath());
  if (fromProject) signature["project_sha256"] = hashFile(sourcePath);
  if (options.contains("manifest")) signature["manifest_sha256"] = hashFile(sourcePath);
  QJsonObject inputHashes;
  for (const auto& page : pages->toPageSequence(IMAGE_VIEW)) {
    const auto path = absolute(page.imageId().filePath());
    require(QFileInfo(path).absolutePath().compare(outputDir, Qt::CaseInsensitive) != 0,
            "Output must not be a source image directory.");
    require(path.compare(projectPath, Qt::CaseInsensitive) != 0, "Project output must not overwrite an input image.");
    if (!inputHashes.contains(path)) inputHashes[path] = QFileInfo::exists(path) ? hashFile(path) : "missing";
  }
  signature["inputs"] = inputHashes;
  const QString fingerprint = QString::fromLatin1(QCryptographicHash::hash(QJsonDocument(signature).toJson(QJsonDocument::Compact), QCryptographicHash::Sha256).toHex());
  const bool reuse = options["resume"].toBool() && prior["fingerprint"].toString() == fingerprint;
  if (options["resume"].toBool() && !prior.isEmpty() && !reuse)
    emitEvent({{"event", "invalidated"}, {"reason", "Input, configuration or executable changed; recomputing whole-project layout."}});

  const auto names = session.names(outputDir);
  auto thumbs = std::make_shared<ThumbnailPixmapCache>(outputDir + "/cache/thumbs", QSize(200, 200), 2, 100);
  // LoadFileTask and output filters expect a cache root even in unattended mode.
  require(QDir().mkpath(outputDir + "/cache"), "Cannot create cache.");


  QJsonObject records;
  const auto priorRecords = prior["pages"].toObject();
  QJsonObject state{{"schema_version", 1}, {"fingerprint", fingerprint}, {"project", projectPath}, {"inputs", inputHashes}, {"pages", records}};
  auto checkpoint = [&] { state["pages"] = records; writeJson(statePath, state); };
  auto saveProject = [&] {
    session.save(projectPath, outputDir, true);
  };

  // Stage boundaries are also ownership boundaries: no settings mutation or
  // project serialization while workers are active. The main thread drains Qt
  // events and forwards cancellation to the thread-safe TaskStatus flags.
  auto phase = [&](const QString& label, int stage, const std::vector<PageInfo>& work) {
    struct Active { PageInfo page; BackgroundTaskPtr task; std::future<FilterResultPtr> result; };
    std::vector<Active> active;
    size_t next = 0;
    const size_t jobs = size_t(options["jobs"].toInt(1));
    while (next < work.size() || !active.empty()) {
      while (!cancelled && next < work.size() && active.size() < jobs) {
        const auto page = work[next++];
        const auto task = createCompositeProcessingTask(stages, pages, thumbs, names, page, stage, true, false);
        emitEvent({{"event", "page_started"}, {"stage", label}, {"input", page.imageId().filePath()}, {"key", pageKey(page)}});
        active.push_back({page, task, std::async(std::launch::async, [task] { return (*task)(); })});
      }
      if (cancelled) { for (auto& job : active) job.task->cancel(); next = work.size(); }
      for (auto it = active.begin(); it != active.end();) {
        if (it->result.wait_for(std::chrono::milliseconds(0)) != std::future_status::ready) { ++it; continue; }
        const auto key = pageKey(it->page);
        QJsonObject record = records[key].toObject();
        record["input"] = it->page.imageId().filePath(); record["image_page"] = it->page.imageId().page();
        record["id"] = processing::pageId(*pages, it->page); record["image_id"] = pages->stableImageId(it->page.imageId());
        record["subpage"] = it->page.id().subPage() == PageId::LEFT_PAGE ? "left" : it->page.id().subPage() == PageId::RIGHT_PAGE ? "right" : "single";
        record["output"] = names.filePathFor(it->page.id());
        try {
          const auto result = it->result.get();
          if (cancelled || it->task->isCancelled()) {
            record["status"] = "cancelled";
          } else {
            require(bool(result), "Processing returned no result.");
            require(result->errorString().isEmpty(), result->errorString());
            auto metrics = record["metrics"].toObject();
            const auto updated = taskMetrics(it->task);
            for (auto m = updated.begin(); m != updated.end(); ++m) metrics[m.key()] = m.value();
            record["metrics"] = metrics;
            record["status"] = label == "output" ? "complete" : "analyzed";
            if (label == "output") {
              require(!ImageLoader::load(record["output"].toString()).isNull(), "Output is not a readable image.");
              record["sha256"] = hashFile(record["output"].toString());
              record["artifacts"] = outputArtifacts(record["output"].toString(), stages->outputFilter()->processingSettings()->getParams(it->page.id()));
            }
          }
        } catch (const std::exception& error) {
          record["status"] = "error"; record["message"] = QString::fromUtf8(error.what());
        }
        records[key] = record;
        auto event = record; event["event"] = "page_finished"; event["stage"] = label; event["key"] = key;
        emitEvent(event);
        it = active.erase(it);
        checkpoint();
      }
      QCoreApplication::processEvents();
      if (!active.empty()) QThread::msleep(10);
    }
  };

  auto initial = pages->toPageSequence(IMAGE_VIEW);
  std::vector<PageInfo> analyze;
  for (const auto& page : initial) {
    const auto path = names.filePathFor(page.id());
    const auto key = pageKey(page);
    if (QFileInfo::exists(path)) {
      bool owned = priorRecords.contains(key) && priorRecords[key].toObject()["output"].toString() == path;
      require(options["overwrite"].toBool() || (options["resume"].toBool() && owned), "Output already exists: " + path);
    }
    records[key] = QJsonObject{{"input", page.imageId().filePath()}, {"output", path}, {"status", "pending"}};
    analyze.push_back(page);
  }
  checkpoint();
  // Resolve each source exactly once; split siblings share settings and must
  // not race each other during structural analysis.
  phase(lastStage == 0 ? "orientation" : "split", std::min(1, lastStage), analyze);
  if (!cancelled) {
    analyze.clear();
    for (const auto& page : pages->toPageSequence(PAGE_VIEW)) {
      const auto path = names.filePathFor(page.id());
      const auto key = pageKey(page);
      if (!records.contains(key)) {
        PageInfo source = page; source.setId(PageId(page.imageId(), PageId::SINGLE_PAGE));
        auto record = records[pageKey(source)].toObject(); record["id"] = processing::pageId(*pages, page); record["output"] = path;
        records[key] = record;
      }
      if (QFileInfo::exists(path)) {
        const bool owned = priorRecords.contains(key) && priorRecords[key].toObject()["output"].toString() == path;
        require(options["overwrite"].toBool() || (options["resume"].toBool() && owned), "Output already exists: " + path);
      }
      if (session.newProject || session.config.contains("preset") || options.contains("preset")) {
        auto base = physicsPreset(); base.remove("rotate");
        if (session.config.contains("preset") || options.contains("preset")) base["preset"] = "physics-safe";
        configureLegacyPage(stages, page, base, session.newProject);
      }
      analyze.push_back(page);
    }
    session.validateSelectors();
    // GUI does this when selecting the layout filter; CLI stage execution has no selection event.
    stages->pageLayoutFilter()->processingSettings()->removePagesMissingFrom(pages->toPageSequence(PAGE_VIEW));
    if (lastStage >= 2) { session.applyConfiguration(processing::Scope::Logical, {"deskew"}); phase("deskew", 2, analyze); }
    if (lastStage >= 3 && !cancelled) { session.applyConfiguration(processing::Scope::Logical, {"content"}); session.validateManualGeometry(); phase("content", 3, analyze); }
    if (lastStage >= 4 && !cancelled) { session.applyConfiguration(processing::Scope::Logical, {"layout"}); phase("layout", 4, analyze); }
    if (lastStage >= 4 && !cancelled && session.config["project"].toObject().contains("freeze_layout"))
      processing::applyProject(session.config, stages, pages);
  }
  if (cancelled) { saveProject(); checkpoint(); emitEvent({{"event", "cancelled"}}); return 130; }
  const auto selected = selectedPages(options.value("pages").toString(), *pages);
  if (lastStage < 5) {
    saveProject(); checkpoint(); QJsonArray ordered; int errors = importErrors.size();
    for (const auto& page : analyze) {
      auto record = records[pageKey(page)].toObject(); record["id"] = processing::pageId(*pages, page);
      if (makePreview && record["status"] == "analyzed" && selected.count(page.id())) {
        const auto previewDir = outputDir + "/previews"; require(QDir().mkpath(previewDir), "Cannot create preview directory");
        const auto stem = processing::pageId(*pages,page).replace(':','-'); const auto source = ImageLoader::load(page.imageId());
        const auto path = previewDir + "/" + stem + "-" + through + ".png";
        // Render after all pages and the frozen aggregate are final, using the logical page's result geometry.
        require(processing::stagePreview(*stages,page,through,source).save(path),"Cannot write stage preview");
        record["preview"] = path; record["preview_geometry"] = processing::stagePreviewGeometry(*stages,page,through);
        const auto sourcePath = previewDir + "/" + stem + "-source.png";
        require(source.scaled(1600,1600,Qt::KeepAspectRatio,Qt::SmoothTransformation).save(sourcePath),"Cannot write source preview"); record["source_preview"] = sourcePath;
      }
      record["settings"] = processing::inspect(*stages, page); record["selected"] = selected.count(page.id()) != 0;
      if (record["status"] == "error") ++errors; ordered.append(record);
    }
    QJsonObject report{{"schema_version", 2}, {"stage", through}, {"pages", ordered}, {"errors", errors}, {"project", projectPath}, {"exit_code", errors ? 1 : 0}};
    writeJson(reportPath, report); writeJson(outputDir + "/analysis.json", session.inspect());
    if (options["html"].toBool()) reviewHtml(outputDir, report);
    emitEvent({{"event", "finished"}, {"stage", through}, {"report", reportPath}, {"exit_code", errors ? 1 : 0}}); return errors ? 1 : 0;
  }
  session.applyConfiguration(processing::Scope::Logical, {"output", "picture_zones", "fill_zones"});
  std::vector<PageInfo> outputWork;
  std::set<PageId> failed;
  for (const auto& page : pages->toPageSequence(PAGE_VIEW)) {
    const auto key = pageKey(page);
    auto record = records[key].toObject();
    if (record["status"] != "analyzed") failed.insert(page.id());
    if (!selected.count(page.id())) { record["status"] = "not_selected"; records[key] = record; continue; }
    if (failed.count(page.id())) continue;
    const auto metrics = record["metrics"].toObject();
    QStringList warnings;
    const auto skewParams = stages->deskewFilter()->processingSettings()->getPageParams(page.id());
    if (skewParams && skewParams->mode() == MODE_AUTO && metrics.contains("skew_confidence") && metrics["skew_confidence"].toDouble() < metrics["skew_confidence_required"].toDouble())
      warnings << "low_skew_confidence";
    const auto contentParams = stages->selectContentFilter()->processingSettings()->getPageParams(page.id());
    if (skewParams && skewParams->mode() == MODE_AUTO && std::abs(metrics["deskew_angle"].toDouble()) > options["max-angle"].toDouble(8)) warnings << "large_skew_angle";
    if (contentParams && contentParams->pageDetectionMode() == MODE_AUTO && metrics.contains("page_retained_ratio") && metrics["page_retained_ratio"].toDouble() < options["min-page-ratio"].toDouble(0.8))
      warnings << "large_page_crop";
    const auto previous = priorRecords[key].toObject();
    const QString outPath = names.filePathFor(page.id());
    if (reuse && (previous["status"] == "complete" || previous["status"] == "review") && QFileInfo::exists(outPath)
        && verifiedArtifacts(previous)) {
      record = previous; records[key] = record;
      emitEvent({{"event", "page_reused"}, {"key", key}, {"output", outPath}});
      continue;
    }
    if (!warnings.empty() && options.value("review-policy").toString("preserve") == "preserve") {
      record["warnings"] = QJsonArray::fromStringList(warnings);
      // An uncertain single-page result is copied unchanged. For split pages,
      // whole-image fallback would duplicate facing pages, so require review.
      if (page.id().subPage() == PageId::SINGLE_PAGE) {
        auto image = ImageLoader::load(page.imageId());
        image.setDotsPerMeterX(qRound(page.metadata().dpi().horizontal() / 0.0254));
        image.setDotsPerMeterY(qRound(page.metadata().dpi().vertical() / 0.0254));
        if (!image.isNull() && TiffWriter::writeImage(outPath, image)) {
          record["status"] = "review"; record["fallback_original"] = true; record["sha256"] = hashFile(outPath);
        } else { record["status"] = "error"; record["message"] = "Failed to preserve original page"; }
      } else { record["status"] = "error"; record["message"] = "Uncertain split page requires GUI review"; }
      records[key] = record;
      auto event = record; event["event"] = "review_required"; event["key"] = key; emitEvent(event);
    } else {
      if (!warnings.empty()) { record["warnings"] = QJsonArray::fromStringList(warnings); record["review_required"] = true; records[key] = record; }
      // New runs must not trust ScanTailor's timestamp-only output cache.
      stages->outputFilter()->processingSettings()->removeOutputParams(page.id());
      outputWork.push_back(page);
    }
  }
  // Failed images cannot contribute unknown dimensions to aggregate layout.
  for (const auto& id : failed) stages->pageLayoutFilter()->processingSettings()->invalidateContentSize(id);
  if (!outputWork.empty()) {
    PageSequence valid; for (const auto& p : pages->toPageSequence(PAGE_VIEW)) if (!failed.count(p.id())) valid.append(p);
    require(stages->pageLayoutFilter()->processingSettings()->checkEverythingDefined(valid), "Layout is not ready for output.");
    phase("output", stages->outputFilterIdx(), outputWork);
  }
  saveProject(); checkpoint();
  int complete = 0, review = 0, errors = importErrors.size();
  QJsonArray ordered;
  for (const auto& page : analyze) {
    auto record = records[pageKey(page)].toObject();
    record["id"] = processing::pageId(*pages, page); record["settings"] = processing::inspect(*stages, page);
    if (record["status"] == "complete" && record["review_required"].toBool()) record["status"] = "review";
    if (makePreview && (record["status"] == "complete" || record["status"] == "review")) {
      const auto previewDir = outputDir + "/previews"; require(QDir().mkpath(previewDir),"Cannot create preview directory");
      const auto stem = processing::pageId(*pages,page).replace(':','-');
      const auto outputImage = ImageLoader::load(record["output"].toString());
      const auto preview = outputImage.scaled(1600,1600,Qt::KeepAspectRatio,Qt::SmoothTransformation);
      const auto path = previewDir + "/" + stem + "-output.png"; require(preview.save(path),"Cannot write output preview"); record["preview"] = path;
      record["preview_geometry"] = QJsonObject{{"space","output"},{"output_size",QJsonArray{outputImage.width(),outputImage.height()}},
        {"output_to_preview",QJsonArray{double(preview.width())/outputImage.width(),0,0,double(preview.height())/outputImage.height(),0,0}}};
      const auto sourcePath = previewDir + "/" + stem + "-source.png";
      require(ImageLoader::load(page.imageId()).scaled(1600,1600,Qt::KeepAspectRatio,Qt::SmoothTransformation).save(sourcePath),"Cannot write source preview"); record["source_preview"] = sourcePath;
      auto artifacts = record["artifacts"].toArray();
      if (artifacts.empty()) artifacts.append(QJsonObject{{"path",record["output"]},{"sha256",record["sha256"]}});
      QJsonArray current; for (const auto& a : artifacts) if (a.toObject()["role"] != "preview") current.append(a);
      for (const auto& p : {path,sourcePath}) current.append(QJsonObject{{"path",p},{"sha256",hashFile(p)},{"role","preview"}});
      record["artifacts"] = current;
    }
    records[pageKey(page)] = record;
    ordered.append(record);
    if (record["status"] == "complete") ++complete;
    else if (record["status"] == "review") ++review;
    else if (record["status"] != "not_selected") ++errors;
  }
  const int code = cancelled ? 130 : (errors || review ? 1 : 0);
  checkpoint();
  QJsonObject report{{"schema_version", 1}, {"fingerprint", fingerprint}, {"project", projectPath},
    {"complete", complete}, {"review", review}, {"errors", errors}, {"pages", ordered}, {"import_errors", importErrors}, {"exit_code", code}};
  writeJson(reportPath, report);
  writeJson(outputDir + "/analysis.json", session.inspect());
  if (options["html"].toBool()) reviewHtml(outputDir, report);
  emitEvent({{"event", "finished"}, {"complete", complete}, {"review", review}, {"errors", errors},
             {"report", reportPath}, {"project", projectPath}, {"exit_code", code}});
  return code;
}
}
