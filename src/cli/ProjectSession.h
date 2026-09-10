// Copyright (C) 2026. Distributed under the GNU GPLv3 license.
#pragma once
#include <core/ProcessingConfiguration.h>
#include <core/OutputFileNameGenerator.h>
#include <core/PageInfo.h>
#include <QJsonArray>
#include <memory>
class ProjectReader;
class StageSequence;
class ProjectPages;
namespace cli {
QJsonObject physicsPreset();
void configureLegacyPage(const std::shared_ptr<StageSequence>& stages, const PageInfo& page,
                         const QJsonObject& overrides, bool newProject);
QJsonObject loadJsonObject(const QString& path);
void saveJsonObject(const QString& path, const QJsonObject& value);
QString absolutePath(const QString& path);
class ProjectSession {
 public:
  ProjectSession(const QJsonObject& options, const QString& outputDir);
  ~ProjectSession();
  std::shared_ptr<ProjectPages> pages;
  std::shared_ptr<StageSequence> stages;
  std::shared_ptr<FileNameDisambiguator> disambiguator;
  QJsonArray importErrors;
  bool newProject;
  QJsonObject config;
  QJsonObject options;
  OutputFileNameGenerator names(const QString& outputDir) const;
  void applyConfiguration(processing::Scope scope, const QStringList& sections = {});
  QJsonObject settingsFor(const PageInfo& page, QJsonObject* origins = nullptr) const;
  QJsonObject inspect(bool exportConfig = false) const;
  void edit(const QJsonObject& operations);
  void save(const QString& path, const QString& outputDir, bool overwrite) const;
  void validateIdentities() const;
  void validateSelectors() const;
  void validateManualGeometry() const;
  void validateSaveTarget(const QString& path, bool projectFile) const;
 private:
  std::unique_ptr<ProjectReader> reader;
  QByteArray originalProjectHash;
  QJsonObject originalManualGeometry;
  void insert(const QJsonObject& operation);
};
int projectCommand(const QString& command, const QJsonObject& options);
}
