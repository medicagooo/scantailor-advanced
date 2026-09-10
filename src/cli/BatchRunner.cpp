// Copyright (C) 2026. Distributed under the GNU GPLv3 license.
#include "BatchRunner.h"
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

QJsonObject preset() {
  // Preserve diagrams by disabling content-box trimming and image enhancement.
  // Page detection still removes scanner surroundings; doubtful pages fall back.
  return {{"deskew", "auto"}, {"rotate", 0}, {"content-detection", "off"},
          {"page-detection", "auto"}, {"color-mode", "color-grayscale"},
          {"dewarp", "off"}, {"fill-margins", true}, {"fill-offcut", true}, {"margin-mm", 0}};
}
void configurePage(const std::shared_ptr<StageSequence>& stages, const PageInfo& page,
                   const QJsonObject& overrides, bool newProject) {
  for (const auto& filter : stages->filters()) filter->loadDefaultSettings(page);
  const auto id = page.id();
  if (overrides.contains("rotate")) {
    OrthogonalRotation rotation;
    for (int n = 0; n < overrides["rotate"].toInt() / 90; ++n) rotation.nextClockwiseDirection();
    stages->fixOrientationFilter()->processingSettings()->applyRotation(id.imageId(), rotation);
  }
  if (overrides.contains("deskew")) {
    const auto mode = overrides["deskew"].toString();
    auto settings = stages->deskewFilter()->processingSettings();
    auto old = settings->getPageParams(id);
    const double angle = mode == "manual" ? overrides["deskew-angle"].toDouble() : 0;
    settings->setPageParams(id, deskew::Params(angle, 0, old->dependencies(),
                              mode == "auto" ? MODE_AUTO : MODE_MANUAL, MODE_MANUAL));
    settings->setPendingAutoOblique(id, false);
  }
  if (overrides.contains("page-detection") || overrides.contains("content-detection")) {
    auto settings = stages->selectContentFilter()->processingSettings();
    auto params = settings->getPageParams(id);
    if (overrides.contains("page-detection"))
      params->setPageDetectionMode(overrides["page-detection"] == "auto" ? MODE_AUTO : MODE_DISABLED);
    if (overrides.contains("content-detection"))
      params->setContentDetectionMode(overrides["content-detection"] == "auto" ? MODE_AUTO : MODE_DISABLED);
    params->setDependencies(select_content::Dependencies());
    settings->setPageParams(id, *params);
  }
  if (overrides.contains("margin-mm")) {
    const double mm = overrides["margin-mm"].toDouble();
    auto settings = stages->pageLayoutFilter()->processingSettings();
    const auto old = settings->getPageParams(id);
    // Null alignment disables matching the largest page size across the book.
    settings->setPageParams(id, page_layout::Params(Margins(mm, mm, mm, mm),
        old->pageRect(), old->contentRect(), old->contentSizeMM(), page_layout::Alignment(), false));
  }
  auto outputSettings = stages->outputFilter()->processingSettings();
  auto params = outputSettings->getParams(id);
  if (newProject || overrides.contains("output-dpi")) {
    params.setOutputDpi(overrides.contains("output-dpi")
        ? Dpi(overrides["output-dpi"].toInt(), overrides["output-dpi"].toInt()) : page.metadata().dpi());
  }
  auto colors = params.colorParams();
  if (overrides.contains("color-mode")) {
    const auto mode = overrides["color-mode"].toString();
    colors.setColorMode(mode == "black-white" ? output::BLACK_AND_WHITE :
                        mode == "mixed" ? output::MIXED : output::COLOR_GRAYSCALE);
  }
  auto common = colors.colorCommonOptions();
  if (newProject || overrides.contains("preset")) {
    common.setNormalizeIllumination(false);
    common.setWienerCoef(0);
    auto poster = common.getPosterizationOptions(); poster.setEnabled(false);
    common.setPosterizationOptions(poster);
    params.setDespeckleLevel(0);
    params.setSplittingOptions(output::SplittingOptions());
  }
  if (overrides.contains("fill-margins")) common.setFillMargins(overrides["fill-margins"].toBool());
  if (overrides.contains("fill-offcut")) {
    common.setFillOffcut(overrides["fill-offcut"].toBool());
    common.setFillOutsidePageBox(overrides["fill-offcut"].toBool());
  }
  if (newProject || overrides.contains("fill-margins") || overrides.contains("fill-offcut"))
    common.setFillingColor(output::FILL_WHITE);
  colors.setColorCommonOptions(common);
  params.setColorParams(colors);
  if (overrides.contains("dewarp"))
    params.setDewarpingOptions(output::DewarpingOptions(overrides["dewarp"] == "auto" ? output::AUTO : output::OFF, false));
  outputSettings->setParams(id, params);
}

QString pageKey(const PageInfo& page) {
  return absolute(page.imageId().filePath()) + "#" + QString::number(page.imageId().page())
         + ":" + QString::number(int(page.id().subPage()));
}
QJsonObject taskMetrics(const BackgroundTaskPtr& task) {
  QJsonObject obj;
  for (const auto& pair : task->metrics()) if (std::isfinite(pair.second)) obj[QString::fromStdString(pair.first)] = pair.second;
  return obj;
}
}

int run(const QJsonObject& options) {
  const QString outputDir = absolute(options["output"].toString());
  const bool fromProject = !options["project"].toString().isEmpty();
  const QString sourcePath = absolute(options[fromProject ? "project" : "input"].toString());
  require(QFileInfo(sourcePath).exists(), "Input does not exist: " + sourcePath);
  require(fromProject || QFileInfo(sourcePath).isDir(), "--input must be an image directory.");
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

  auto defaults = std::make_unique<DefaultParams>();
  auto split = defaults->getPageSplitParams(); split.setLayoutType(page_split::SINGLE_PAGE_UNCUT); defaults->setPageSplitParams(split);
  DefaultParamsProvider::getInstance().setParams(std::move(defaults), "CLI");
  QJsonObject overrides;
  if (!fromProject || options.contains("preset")) overrides = preset();
  for (auto it = options.begin(); it != options.end(); ++it) overrides[it.key()] = it.value();

  std::shared_ptr<ProjectPages> pages;
  auto disambiguator = std::make_shared<FileNameDisambiguator>();
  std::unique_ptr<ProjectReader> sourceReader;
  QJsonArray importErrors;
  if (fromProject) {
    QFile file(sourcePath); require(file.open(QIODevice::ReadOnly), "Cannot open project.");
    QDomDocument doc; require(bool(doc.setContent(file.readAll())), "Invalid project XML.");
    sourceReader = std::make_unique<ProjectReader>(doc, sourcePath);
    require(sourceReader->success(), "Cannot load project.");
    pages = sourceReader->pages(); disambiguator = sourceReader->namingDisambiguator();
  } else {
    auto files = QDir(sourcePath).entryInfoList({"*.png", "*.tif", "*.tiff", "*.jpg", "*.jpeg", "*.bmp"}, QDir::Files);
    QCollator collator(QLocale::c()); collator.setNumericMode(true); collator.setCaseSensitivity(Qt::CaseInsensitive);
    std::sort(files.begin(), files.end(), [&](const QFileInfo& a, const QFileInfo& b) {
      const int result = collator.compare(a.fileName(), b.fileName());
      return result ? result < 0 : a.fileName() < b.fileName();
    });
    require(!files.empty(), "No supported images in input directory (PDF requires Process-PdfFolder.ps1).");
    std::vector<ImageFileInfo> metadata;
    for (const auto& file : files) {
      if (cancelled) return 130;
      std::vector<ImageMetadata> images;
      const auto status = ImageMetadataLoader::load(file.absoluteFilePath(), [&](const ImageMetadata& m) { images.push_back(m); });
      if (status != ImageMetadataLoader::LOADED || images.empty()) {
        QJsonObject error{{"event", "import_error"}, {"input", file.absoluteFilePath()}, {"status", "error"}, {"message", "Cannot read image metadata"}};
        importErrors.append(error); emitEvent(error); continue;
      }
      bool valid = true;
      for (auto& image : images) {
        if (options.contains("dpi")) image.setDpi(Dpi(options["dpi"].toInt(), options["dpi"].toInt()));
        if (!image.isDpiOK()) valid = false;
      }
      if (!valid) throw std::invalid_argument(("Invalid or missing DPI; specify --dpi for " + file.fileName()).toStdString());
      metadata.emplace_back(file, images);
      disambiguator->registerFile(file.absoluteFilePath());
    }
    require(!metadata.empty(), "No readable input images.");
    pages = std::make_shared<ProjectPages>(metadata, ProjectPages::ONE_PAGE, Qt::LeftToRight);
  }
  if (fromProject && options.contains("dpi")) {
    const auto sequence = pages->toPageSequence(IMAGE_VIEW);
    for (const auto& page : sequence) {
      auto metadata = page.metadata(); metadata.setDpi(Dpi(options["dpi"].toInt(), options["dpi"].toInt()));
      pages->updateImageMetadata(page.imageId(), metadata);
    }
  }
  require(pages->validateDpis(), "Project has invalid DPI; specify --dpi.");
  QJsonObject signature = overrides;
  for (const auto& name : {"resume", "overwrite", "jobs", "save-project"}) signature.remove(name);
  signature["binary_sha256"] = hashFile(QCoreApplication::applicationFilePath());
  if (fromProject) signature["project_sha256"] = hashFile(sourcePath);
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

  auto selection = std::make_shared<Selection>(pages);
  auto stages = std::make_shared<StageSequence>(pages, PageSelectionAccessor(selection));
  if (sourceReader) sourceReader->readFilterSettings(stages->filters());
  const OutputFileNameGenerator names(disambiguator, outputDir, pages->layoutDirection());
  auto thumbs = std::make_shared<ThumbnailPixmapCache>(outputDir + "/cache/thumbs", QSize(200, 200), 2, 100);
  // LoadFileTask and output filters expect a cache root even in unattended mode.
  require(QDir().mkpath(outputDir + "/cache"), "Cannot create cache.");
  for (const auto& page : pages->toPageSequence(PAGE_VIEW)) configurePage(stages, page, overrides, !fromProject);

  QJsonObject records;
  const auto priorRecords = prior["pages"].toObject();
  QJsonObject state{{"schema_version", 1}, {"fingerprint", fingerprint}, {"project", projectPath}, {"inputs", inputHashes}, {"pages", records}};
  auto checkpoint = [&] { state["pages"] = records; writeJson(statePath, state); };
  auto saveProject = [&] {
    require(QDir().mkpath(QFileInfo(projectPath).absolutePath()), "Cannot create project parent.");
    require(ProjectWriter(pages, SelectedPage(), names).write(projectPath, stages->filters()), "Cannot save project.");
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

  auto initial = pages->toPageSequence(PAGE_VIEW);
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
  // First resolve page splitting (existing projects may contain facing pages).
  phase("split", stages->pageSplitFilterIdx(), analyze);
  if (!cancelled) {
    analyze.clear();
    for (const auto& page : pages->toPageSequence(PAGE_VIEW)) {
      const auto path = names.filePathFor(page.id());
      const auto key = pageKey(page);
      if (QFileInfo::exists(path)) {
        const bool owned = priorRecords.contains(key) && priorRecords[key].toObject()["output"].toString() == path;
        require(options["overwrite"].toBool() || (options["resume"].toBool() && owned), "Output already exists: " + path);
      }
      configurePage(stages, page, overrides, !fromProject);
      analyze.push_back(page);
    }
    phase("analysis", stages->pageLayoutFilterIdx(), analyze);
  }
  if (cancelled) { saveProject(); checkpoint(); emitEvent({{"event", "cancelled"}}); return 130; }
  std::vector<PageInfo> outputWork;
  std::set<PageId> failed;
  for (const auto& page : pages->toPageSequence(PAGE_VIEW)) {
    const auto key = pageKey(page);
    auto record = records[key].toObject();
    if (record["status"] != "analyzed") { failed.insert(page.id()); continue; }
    const auto metrics = record["metrics"].toObject();
    QStringList warnings;
    if (metrics.contains("skew_confidence") && metrics["skew_confidence"].toDouble() < metrics["skew_confidence_required"].toDouble())
      warnings << "low_skew_confidence";
    if (std::abs(metrics["deskew_angle"].toDouble()) > options["max-angle"].toDouble(8)) warnings << "large_skew_angle";
    if (metrics.contains("page_retained_ratio") && metrics["page_retained_ratio"].toDouble() < options["min-page-ratio"].toDouble(0.8))
      warnings << "large_page_crop";
    const auto previous = priorRecords[key].toObject();
    const QString outPath = names.filePathFor(page.id());
    if (reuse && (previous["status"] == "complete" || previous["status"] == "review") && QFileInfo::exists(outPath)
        && previous["sha256"].toString() == hashFile(outPath)) {
      record = previous; records[key] = record;
      emitEvent({{"event", "page_reused"}, {"key", key}, {"output", outPath}});
      continue;
    }
    if (!warnings.empty()) {
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
      // New runs must not trust ScanTailor's timestamp-only output cache.
      stages->outputFilter()->processingSettings()->removeOutputParams(page.id());
      outputWork.push_back(page);
    }
  }
  // Failed images cannot contribute unknown dimensions to aggregate layout.
  if (!failed.empty()) pages->removePages(failed);
  if (!outputWork.empty()) {
    require(stages->pageLayoutFilter()->checkReadyForOutput(*pages, nullptr), "Layout is not ready for output.");
    phase("output", stages->outputFilterIdx(), outputWork);
  }
  saveProject(); checkpoint();
  int complete = 0, review = 0, errors = importErrors.size();
  QJsonArray ordered;
  for (const auto& page : analyze) {
    const auto record = records[pageKey(page)].toObject();
    ordered.append(record);
    if (record["status"] == "complete") ++complete;
    else if (record["status"] == "review") ++review;
    else ++errors;
  }
  const int code = cancelled ? 130 : (errors || review ? 1 : 0);
  QJsonObject report{{"schema_version", 1}, {"fingerprint", fingerprint}, {"project", projectPath},
    {"complete", complete}, {"review", review}, {"errors", errors}, {"pages", ordered}, {"import_errors", importErrors}, {"exit_code", code}};
  writeJson(reportPath, report);
  emitEvent({{"event", "finished"}, {"complete", complete}, {"review", review}, {"errors", errors},
             {"report", reportPath}, {"project", projectPath}, {"exit_code", code}});
  return code;
}
}
