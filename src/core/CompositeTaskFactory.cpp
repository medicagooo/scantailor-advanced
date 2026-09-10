#include "CompositeTaskFactory.h"
#include "StageSequence.h"
#include "LoadFileTask.h"
#include "filters/fix_orientation/Task.h"
#include "filters/page_split/Task.h"
#include "filters/deskew/Task.h"
#include "filters/select_content/Task.h"
#include "filters/page_layout/Task.h"
#include "filters/output/Task.h"
#include <cassert>

BackgroundTaskPtr createCompositeProcessingTask(
    const std::shared_ptr<StageSequence>& stages, const std::shared_ptr<ProjectPages>& pages,
    const std::shared_ptr<ThumbnailPixmapCache>& thumbnails, const OutputFileNameGenerator& output,
    const PageInfo& page, int lastFilterIdx, bool batch, bool debug) {
  std::shared_ptr<fix_orientation::Task> fixOrientationTask;
  std::shared_ptr<page_split::Task> pageSplitTask;
  std::shared_ptr<deskew::Task> deskewTask;
  std::shared_ptr<select_content::Task> selectContentTask;
  std::shared_ptr<page_layout::Task> pageLayoutTask;
  std::shared_ptr<output::Task> outputTask;

  if (batch) {
    debug = false;
  }

  if (lastFilterIdx >= stages->outputFilterIdx()) {
    outputTask = stages->outputFilter()->createTask(page.id(), thumbnails, output, batch, debug);
    debug = false;
  }
  if (lastFilterIdx >= stages->pageLayoutFilterIdx()) {
    pageLayoutTask = stages->pageLayoutFilter()->createTask(page.id(), outputTask, batch, debug);
    debug = false;
  }
  if (lastFilterIdx >= stages->selectContentFilterIdx()) {
    selectContentTask = stages->selectContentFilter()->createTask(page.id(), pageLayoutTask, batch, debug);
    debug = false;
  }
  if (lastFilterIdx >= stages->deskewFilterIdx()) {
    deskewTask = stages->deskewFilter()->createTask(page.id(), selectContentTask, batch, debug);
    debug = false;
  }
  if (lastFilterIdx >= stages->pageSplitFilterIdx()) {
    pageSplitTask = stages->pageSplitFilter()->createTask(page, deskewTask, batch, debug);
    debug = false;
  }
  if (lastFilterIdx >= stages->fixOrientationFilterIdx()) {
    fixOrientationTask = stages->fixOrientationFilter()->createTask(page.id(), pageSplitTask, batch);
    debug = false;
  }
  assert(fixOrientationTask);
  return std::make_shared<LoadFileTask>(batch ? BackgroundTask::BATCH : BackgroundTask::INTERACTIVE, page,
                                        thumbnails, pages, fixOrientationTask);
}
