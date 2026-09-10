// Copyright (C) 2026. Distributed under the GNU GPLv3 license.
#include "ProjectSession.h"
#include <core/StageSequence.h>
#include <core/filters/fix_orientation/Settings.h>
#include <core/filters/deskew/Settings.h>
#include <core/filters/select_content/Settings.h>
#include <core/filters/page_layout/Settings.h>
#include <core/filters/page_layout/Params.h>
#include <core/filters/output/Settings.h>
namespace cli {
QJsonObject physicsPreset() {
  // Preserve diagrams by disabling content-box trimming and image enhancement.
  // Page detection still removes scanner surroundings; doubtful pages fall back.
  return {{"deskew", "auto"}, {"rotate", 0}, {"content-detection", "off"},
          {"page-detection", "auto"}, {"color-mode", "color-grayscale"},
          {"dewarp", "off"}, {"fill-margins", true}, {"fill-offcut", true}, {"margin-mm", 0}};
}
void configureLegacyPage(const std::shared_ptr<StageSequence>& stages, const PageInfo& page,
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


}
