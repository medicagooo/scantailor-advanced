// Copyright (C) 2026. Distributed under the GNU GPLv3 license.
#ifndef SCANTAILOR_COMPOSITE_TASK_FACTORY_H_
#define SCANTAILOR_COMPOSITE_TASK_FACTORY_H_

#include "BackgroundTask.h"
#include <memory>
class StageSequence;
class ProjectPages;
class ThumbnailPixmapCache;
class OutputFileNameGenerator;
class PageInfo;

// Shared by MainWindow and the CLI. The caller must complete layout analysis for
// the whole project before requesting output; filters may use aggregate sizes.
BackgroundTaskPtr createCompositeProcessingTask(
    const std::shared_ptr<StageSequence>& stages,
    const std::shared_ptr<ProjectPages>& pages,
    const std::shared_ptr<ThumbnailPixmapCache>& thumbnails,
    const OutputFileNameGenerator& output, const PageInfo& page,
    int lastFilterIdx, bool batch, bool debug);
#endif
