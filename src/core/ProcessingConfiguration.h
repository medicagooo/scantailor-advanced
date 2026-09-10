// Copyright (C) 2026. Distributed under the GNU GPLv3 license.
#ifndef SCANTAILOR_PROCESSING_CONFIGURATION_H_
#define SCANTAILOR_PROCESSING_CONFIGURATION_H_
#include <QJsonObject>
#include <memory>
class StageSequence;
class ProjectPages;
class PageInfo;
class QImage;
namespace processing {
enum class Scope { Source, Logical, All };
// Versioned, strict adapter over the same Params/Settings and XML serializers
// used by the GUI. Call only while workers are stopped. No GUI preferences.
QJsonObject schema();
void validateConfiguration(const QJsonObject& config);
void validateSettings(const QJsonObject& settings);
QJsonObject merge(const QJsonObject& base, const QJsonObject& patch);
QString pageId(const ProjectPages& pages, const PageInfo& page);
bool matches(const QJsonObject& selector, const ProjectPages& pages, const PageInfo& page,
             int pageNumber, int imageNumber);
QJsonObject resolve(const QJsonObject& config, const ProjectPages& pages, const PageInfo& page,
                    int pageNumber, int imageNumber, QJsonObject* origins = nullptr);
void applyProject(const QJsonObject& config, const std::shared_ptr<StageSequence>& stages,
                  const std::shared_ptr<ProjectPages>& pages);
QJsonObject inspectProject(const StageSequence& stages, const ProjectPages& pages);
void apply(const QJsonObject& settings, const std::shared_ptr<StageSequence>& stages,
           const std::shared_ptr<ProjectPages>& pages, const PageInfo& page, Scope scope = Scope::All);
QJsonObject inspect(const StageSequence& stages, const PageInfo& page);
QJsonObject mapGeometry(const StageSequence& stages, const ProjectPages& pages, const QJsonObject& request);
QJsonObject stagePreviewGeometry(const StageSequence& stages, const PageInfo& page, const QString& stage);
QImage stagePreview(const StageSequence& stages, const PageInfo& page, const QString& stage, const QImage& source);
}
#endif
