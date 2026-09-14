// Copyright (C) 2026. Distributed under the GNU GPLv3 license.
#include "ProcessingConfiguration.h"
#include <dewarping/DewarpingPointMapper.h>
#include <QCryptographicHash>
#include <QDomDocument>
#include <QJsonArray>
#include <QJsonDocument>
#include <QPainterPath>
#include <QRegularExpression>
#include <algorithm>
#include <cmath>
#include <stdexcept>
#include "ImageEncoding.h"
#include "ImageTransformation.h"
#include "PageSequence.h"
#include "ProcessingPreview.h"
#include "ProjectPages.h"
#include "PropertySet.h"
#include "StageSequence.h"
#include "filters/deskew/Settings.h"
#include "filters/fix_orientation/Settings.h"
#include "filters/output/FillColorProperty.h"
#include "filters/output/OutputGenerator.h"
#include "filters/output/PictureLayerProperty.h"
#include "filters/output/Settings.h"
#include "filters/output/Utils.h"
#include "filters/output/ZoneCategoryProperty.h"
#include "filters/page_layout/Guide.h"
#include "filters/page_layout/Params.h"
#include "filters/page_layout/Settings.h"
#include "filters/page_layout/Utils.h"
#include "filters/page_split/Settings.h"
#include "filters/select_content/Settings.h"
#include "zones/ZoneSet.h"
namespace processing {
namespace {
void check(bool ok, const QString& message) {
  if (!ok)
    throw std::invalid_argument(message.toStdString());
}
QJsonObject object(std::initializer_list<std::pair<QString, QJsonValue>> fields) {
  QJsonObject result;
  for (const auto& f : fields)
    result[f.first] = f.second;
  return result;
}
QJsonObject number(double lo, double hi, bool integer = false) {
  return {{"type", integer ? "integer" : "number"}, {"minimum", lo}, {"maximum", hi}};
}
QJsonObject boolean() {
  return {{"type", "boolean"}};
}
QJsonObject text() {
  return {{"type", "string"}, {"minLength", 1}};
}
QJsonObject choice(const QString& values) {
  return {{"type", "string"}, {"enum", QJsonArray::fromStringList(values.split('|'))}};
}
QJsonObject array(const QJsonObject& item, int lo = 0, int hi = 100000) {
  return {{"type", "array"}, {"items", item}, {"minItems", lo}, {"maxItems", hi}};
}
QJsonObject record(const QJsonObject& properties, const QStringList& required = {}) {
  return {{"type", "object"},
          {"properties", properties},
          {"additionalProperties", false},
          {"required", QJsonArray::fromStringList(required)}};
}
QJsonObject point() {
  return array(number(-10000000, 10000000), 2, 2);
}
QJsonObject rect() {
  return array(number(-10000000, 10000000), 4, 4);
}
QJsonObject dpi() {
  return array(number(72, 1200, true), 2, 2);
}
struct Field {
  QString name, path, type;
  double lo = 0, hi = 0;
  QString values;
};
// Explicit public field -> existing output::Params XML mapping. Keeping a single
// table drives schema, readback and writes; unmentioned XML fields stay intact.
const std::vector<Field>& outputFields() {
  static const std::vector<Field> fields = {
      {"mode", "color-params/@colorMode", "enum", 0, 0, "bw|colorOrGray|mixed"},
      {"fill_offcut", "color-params/color-or-grayscale/@fillOffcut", "boolean"},
      {"fill_outside_page", "color-params/color-or-grayscale/@fillOutsidePageBox", "boolean"},
      {"fill_margins", "color-params/color-or-grayscale/@fillMargins", "boolean"},
      {"fill_color", "color-params/color-or-grayscale/@fillingColor", "enum", 0, 0, "background|white|black"},
      {"normalize_color", "color-params/color-or-grayscale/@normalizeIlluminationColor", "boolean"},
      {"wiener_coefficient", "color-params/color-or-grayscale/@wienerCoef", "number", 0, 1},
      {"wiener_window", "color-params/color-or-grayscale/@wienerWinSize", "integer", 3, 9999},
      {"posterize", "color-params/color-or-grayscale/posterization-options/@enabled", "boolean"},
      {"posterize_level", "color-params/color-or-grayscale/posterization-options/@level", "integer", 2, 256},
      {"posterize_normalize", "color-params/color-or-grayscale/posterization-options/@normalizationEnabled", "boolean"},
      {"posterize_force_bw", "color-params/color-or-grayscale/posterization-options/@forceBlackAndWhite", "boolean"},
      {"threshold_method", "color-params/bw/@binarizationMethod", "enum", 0, 0,
       "otsu|sauvola|wolf|fox|window|bradley|grad|edgeplus|blurdiv|edgediv"},
      {"threshold", "color-params/bw/@thresholdAdj", "integer", -100, 100},
      {"normalize_bw", "color-params/bw/@normalizeIlluminationBW", "boolean"},
      {"savitzky_golay", "color-params/bw/@savitzkyGolaySmoothing", "boolean"},
      {"morphological_smoothing", "color-params/bw/@morphologicalSmoothing", "boolean"},
      {"threshold_window", "color-params/bw/@windowSize", "integer", 3, 10000},
      {"sauvola_coefficient", "color-params/bw/@sauvolaCoef", "number", 0, 1},
      {"wolf_coefficient", "color-params/bw/@wolfCoef", "number", 0, 1},
      {"wolf_lower", "color-params/bw/@wolfLowerBound", "integer", 0, 255},
      {"wolf_upper", "color-params/bw/@wolfUpperBound", "integer", 0, 255},
      {"color_segmentation", "color-params/bw/color-segmenter-options/@enabled", "boolean"},
      {"segment_noise", "color-params/bw/color-segmenter-options/@noiseReduction", "integer", 0, 999},
      {"segment_red", "color-params/bw/color-segmenter-options/@redThresholdAdjustment", "integer", -100, 100},
      {"segment_green", "color-params/bw/color-segmenter-options/@greenThresholdAdjustment", "integer", -100, 100},
      {"segment_blue", "color-params/bw/color-segmenter-options/@blueThresholdAdjustment", "integer", -100, 100},
      {"picture_shape", "picture-shape-options/@pictureShape", "enum", 0, 0, "off|free|rectangular"},
      {"picture_sensitivity", "picture-shape-options/@sensitivity", "integer", 0, 1000},
      {"picture_high_sensitivity", "picture-shape-options/@higherSearchSensitivity", "boolean"},
      {"split_output", "splitting/@splitOutput", "boolean"},
      {"foreground", "splitting/@splittingMode", "enum", 0, 0, "bw|color"},
      {"original_background", "splitting/@originalBackground", "boolean"},
      {"despeckle", "@despeckleLevel", "number", 0, 9},
      {"black_on_white", "@blackOnWhite", "boolean"},
      {"dewarp", "dewarping-options/@mode", "enum", 0, 0, "off|auto|manual|marginal"},
      {"post_deskew", "dewarping-options/@postDeskew", "boolean"},
      {"post_deskew_angle", "dewarping-options/@postDeskewAngle", "number", -45, 45},
      {"depth", "@depthPerception", "number", 1, 3}};
  return fields;
}
QJsonObject settingsSchema() {
  QJsonObject out{{"dpi", dpi()}};
  for (const auto& f : outputFields())
    out[f.name] = f.type == "boolean" ? boolean()
                  : f.type == "enum"  ? choice(f.values)
                                      : number(f.lo, f.hi, f.type == "integer");
  const auto spline = array(record({{"point", point()}, {"tension", number(-1, 1)}}, {"point", "tension"}), 2, 10000);
  out["distortion_model"] = record({{"space", choice("source")},
                                    {"top", array(point(), 2, 10000)},
                                    {"bottom", array(point(), 2, 10000)},
                                    {"top_spline", spline},
                                    {"bottom_spline", spline}},
                                   {"space"});
  const auto trim = record({{"enabled", boolean()},
                            {"left", number(0, 1000000, true)},
                            {"top", number(0, 1000000, true)},
                            {"right", number(0, 1000000, true)},
                            {"bottom", number(0, 1000000, true)}});
  const auto split = record({{"layout", choice("auto|single|cut|two")},
                             {"mode", choice("auto|manual")},
                             {"space", choice("oriented")},
                             {"cutters", array(array(point(), 2, 2), 1, 2)}});
  const auto skew = record({{"mode", choice("auto|manual|off")},
                            {"angle", number(-45, 45)},
                            {"oblique_mode", choice("auto|manual|off")},
                            {"oblique_angle", number(-45, 45)}});
  const auto content = record({{"page_mode", choice("auto|manual|off")},
                               {"content_mode", choice("auto|manual|off")},
                               {"fine_tune", boolean()},
                               {"space", choice("deskew")},
                               {"basis", text()},
                               {"page_rect", rect()},
                               {"content_rect", rect()}});
  const auto margins = record(
      {{"left", number(0, 100)}, {"top", number(0, 100)}, {"right", number(0, 100)}, {"bottom", number(0, 100)}});
  const auto layout = record({{"margins_mm", margins},
                              {"auto_margins", boolean()},
                              {"match_size", boolean()},
                              {"horizontal", choice("left|center|right|auto|original")},
                              {"vertical", choice("top|center|bottom|auto|original")}});
  const auto picture = record({{"space", choice("source")},
                               {"points", array(point(), 3, 10000)},
                               {"layer", choice("noop|erase-auto|picture|erase-all|foreground|background")},
                               {"category", choice("manual|auto")}},
                              {"space", "points", "layer"});
  const auto fill = record({{"space", choice("source")}, {"points", array(point(), 3, 10000)}, {"color", text()}},
                           {"space", "points", "color"});
  return record({{"input", record({{"dpi", dpi()}})},
                 {"orientation", record({{"rotation", number(0, 270, true)}, {"trim", trim}})},
                 {"split", split},
                 {"deskew", skew},
                 {"content", content},
                 {"layout", layout},
                 {"output", record(out)},
                 {"picture_zones", array(picture)},
                 {"fill_zones", array(fill)}});
}
void validateValue(const QJsonValue& value, const QJsonObject& spec, const QString& path) {
  const auto type = spec["type"].toString();
  if (type == "object") {
    check(value.isObject(), path + " must be an object");
    const auto obj = value.toObject(), properties = spec["properties"].toObject();
    for (const auto& required : spec["required"].toArray())
      check(obj.contains(required.toString()), path + "." + required.toString() + " is required");
    for (auto it = obj.begin(); it != obj.end(); ++it) {
      check(properties.contains(it.key()), "Unknown field: " + path + "." + it.key());
      validateValue(it.value(), properties[it.key()].toObject(), path + "." + it.key());
    }
  } else if (type == "array") {
    check(value.isArray(), path + " must be an array");
    const auto values = value.toArray();
    check(values.size() >= spec["minItems"].toInt() && values.size() <= spec["maxItems"].toInt(),
          path + " has invalid item count");
    for (int i = 0; i < values.size(); ++i)
      validateValue(values[i], spec["items"].toObject(), path + "[" + QString::number(i) + "]");
  } else if (type == "boolean")
    check(value.isBool(), path + " must be boolean");
  else if (type == "string") {
    check(value.isString(), path + " must be a string");
    if (spec.contains("enum"))
      check(spec["enum"].toArray().contains(value), path + " has an unsupported value");
    else
      check(!value.toString().isEmpty(), path + " must not be empty");
  } else {
    const double v = value.toDouble();
    check(value.isDouble() && std::isfinite(v) && v >= spec["minimum"].toDouble() && v <= spec["maximum"].toDouble()
              && (type != "integer" || std::floor(v) == v),
          path + " is not a valid " + type + " in range");
  }
}
QDomElement childPath(QDomElement el, const QString& path, QString* attr) {
  auto parts = path.split('/');
  *attr = parts.takeLast().mid(1);
  for (const auto& part : parts) {
    auto child = el.firstChildElement(part);
    if (child.isNull()) {
      child = el.ownerDocument().createElement(part);
      el.appendChild(child);
    }
    el = child;
  }
  return el;
}
QJsonArray pair(double a, double b) {
  return {a, b};
}
QJsonArray box(const QRectF& r) {
  return {r.x(), r.y(), r.width(), r.height()};
}
QRectF rectangle(const QJsonValue& v) {
  auto a = v.toArray();
  return {a[0].toDouble(), a[1].toDouble(), a[2].toDouble(), a[3].toDouble()};
}
QPolygonF polygon(const QJsonValue& value) {
  QPolygonF result;
  for (const auto& v : value.toArray()) {
    const auto a = v.toArray();
    result << QPointF(a[0].toDouble(), a[1].toDouble());
  }
  return result;
}
QJsonArray polygonJson(const QPolygonF& points) {
  QJsonArray a;
  for (const auto& p : points)
    a.append(pair(p.x(), p.y()));
  return a;
}
AutoManualMode mode(const QJsonValue& v) {
  return v == "auto" ? MODE_AUTO : v == "off" ? MODE_DISABLED : MODE_MANUAL;
}
QString modeName(AutoManualMode m) {
  return m == MODE_AUTO ? "auto" : m == MODE_DISABLED ? "off" : "manual";
}
QString subpage(const PageInfo& page) {
  return page.id().subPage() == PageId::LEFT_PAGE    ? "left"
         : page.id().subPage() == PageId::RIGHT_PAGE ? "right"
                                                     : "single";
}
const QStringList layers{"noop", "erase-auto", "picture", "erase-all", "foreground", "background"};
QJsonObject outputSnapshot(const output::Params& params) {
  QDomDocument doc;
  auto el = params.toXml(doc, "params");
  QJsonObject result;
  for (const auto& f : outputFields()) {
    QString attr;
    const auto value = childPath(el, f.path, &attr).attribute(attr);
    result[f.name] = f.type == "boolean" ? QJsonValue(value == "1")
                     : f.type == "enum"  ? QJsonValue(value)
                                         : QJsonValue(value.toDouble());
  }
  result["dpi"] = pair(params.outputDpi().horizontal(), params.outputDpi().vertical());
  if (params.distortionModel().isValid()) {
    QJsonArray top, bottom;
    for (const auto& p : params.distortionModel().topCurve().polyline())
      top.append(pair(p.x(), p.y()));
    for (const auto& p : params.distortionModel().bottomCurve().polyline())
      bottom.append(pair(p.x(), p.y()));
    QJsonObject model{{"space", "source"}};
    auto curve = [&](const QString& name, const dewarping::Curve& c, const QJsonArray& polyline) {
      const auto& spline = c.xspline();
      if (spline.numControlPoints() < 2) {
        model[name] = polyline;
        return;
      }
      QJsonArray controls;
      for (int i = 0; i < spline.numControlPoints(); ++i) {
        auto p = spline.controlPointPosition(i);
        controls.append(QJsonObject{{"point", pair(p.x(), p.y())}, {"tension", spline.controlPointTension(i)}});
      }
      model[name + "_spline"] = controls;
    };
    curve("top", params.distortionModel().topCurve(), top);
    curve("bottom", params.distortionModel().bottomCurve(), bottom);
    result["distortion_model"] = model;
  }
  return result;
}
void noteOrigins(const QJsonObject& patch, const QString& prefix, const QString& source, QJsonObject& origins) {
  for (auto it = patch.begin(); it != patch.end(); ++it) {
    const auto key = prefix.isEmpty() ? it.key() : prefix + "." + it.key();
    if (it.value().isObject())
      noteOrigins(it.value().toObject(), key, source, origins);
    else
      origins[key] = source;
  }
}
}  // namespace
QJsonObject schema() {
  const auto selector = record({{"pages", array(number(1, 1000000, true), 1)},
                                {"images", array(number(1, 1000000, true), 1)},
                                {"ids", array(text(), 1)},
                                {"image_ids", array(text(), 1)},
                                {"parity", choice("odd|even")},
                                {"side", choice("single|left|right")}});
  const auto project
      = record({{"reading_direction", choice("ltr|rtl")},
                {"deskew_algorithm", choice("content|top-edge")},
                {"page_detection_size_mm", array(number(0, 10000), 2, 2)},
                {"page_detection_tolerance", number(0, 1)},
                {"freeze_layout", boolean()},
                {"frozen_size_mm", array(number(0.001, 10000), 2, 2)},
                {"show_middle_rect", boolean()},
                {"guides",
                 array(record({{"orientation", choice("horizontal|vertical")}, {"position", number(-1000000, 1000000)}},
                              {"orientation", "position"}))}});
  auto result = record(
      {{"image_encoding", record({{"format", choice("png|tiff|jpeg")},
                                  {"png_compression", number(0, 9, true)},
                                  {"tiff_compression", choice("none|lzw|deflate")},
                                  {"jpeg_quality", number(1, 100, true)}})},
       {"schema_version", number(2, 2, true)},
       {"preset", choice("physics-safe")},
       {"project", project},
       {"defaults", settingsSchema()},
       {"rules", array(record({{"select", selector}, {"settings", settingsSchema()}}, {"select", "settings"}))}},
      {"schema_version"});
  result["$schema"] = "https://json-schema.org/draft/2020-12/schema";
  result["title"] = "ScanTailor processing configuration v2";
  return result;
}
void validateSettings(const QJsonObject& settings) {
  validateValue(settings, settingsSchema(), "settings");
  const auto model = settings["output"].toObject()["distortion_model"].toObject();
  if (!model.isEmpty())
    for (const auto& name : {QString("top"), QString("bottom")})
      check(model.contains(name) != model.contains(name + "_spline"),
            "Each dewarping curve requires exactly one polyline or spline");
  const QJsonValue rotation = settings.value("orientation").toObject().value("rotation");
  if (!rotation.isUndefined())
    check(rotation.toInt() % 90 == 0, "orientation.rotation must be a multiple of 90");
  const auto skew = settings["deskew"].toObject();
  for (const auto& key : {QString("angle"), QString("oblique_angle")})
    if (skew.contains(key)) {
      const auto modeKey = key == "angle" ? "mode" : "oblique_mode";
      check(!skew.contains(modeKey) || skew[modeKey] == "manual", "An explicit angle requires manual mode");
    }
  const auto split = settings["split"].toObject();
  if (split.contains("cutters")) {
    check(split["space"] == "oriented", "split.cutters requires space=oriented");
    check(split["layout"] == "cut" || split["layout"] == "two", "Manual cutters require layout=cut or two");
    check(!split.contains("mode") || split["mode"] == "manual", "Manual cutters conflict with auto mode");
    check(split["cutters"].toArray().size() == (split["layout"] == "cut" ? 2 : 1), "Incorrect number of cutters");
    for (const auto& line : split["cutters"].toArray()) {
      auto p = polygon(line);
      check(p[0] != p[1], "Cutter endpoints must differ");
    }
  }
  const auto c = settings["content"].toObject();
  for (const auto& key : {QString("page_rect"), QString("content_rect")})
    if (c.contains(key)) {
      check(c["space"] == "deskew", "Manual rectangles require space=deskew (as exported by analyze)");
      check(rectangle(c[key]).isValid(), "Manual rectangle must have positive dimensions");
      const auto mk = key == "page_rect" ? "page_mode" : "content_mode";
      check(!c.contains(mk) || c[mk] == "manual", "Manual rectangle conflicts with automatic/disabled mode");
    }
  for (const auto& zone : settings["fill_zones"].toArray()) {
    const auto color = zone.toObject()["color"].toString();
    check(QRegularExpression("^#[0-9a-fA-F]{6}$").match(color).hasMatch(), "Fill color must be #RRGGBB");
  }
}
void validateConfiguration(const QJsonObject& config) {
  validateValue(config, schema(), "config");
  ImageEncoding::fromJson(config["image_encoding"].toObject());
  validateSettings(config["defaults"].toObject());
  for (const auto& rule : config["rules"].toArray()) {
    const auto r = rule.toObject(), selector = r["select"].toObject(), settings = r["settings"].toObject();
    validateSettings(settings);
    if (settings.contains("input") || settings.contains("orientation") || settings.contains("split"))
      check(
          !selector.contains("pages") && !selector.contains("ids") && !selector.contains("side")
              && !selector.contains("parity"),
          "Source-image settings require image selectors; a logical page cannot independently rotate/crop its sibling");
  }
}
QJsonObject merge(const QJsonObject& base, const QJsonObject& patch) {
  QJsonObject result = base;
  for (auto it = patch.begin(); it != patch.end(); ++it)
    result[it.key()]
        = it.value().isObject() ? QJsonValue(merge(result[it.key()].toObject(), it.value().toObject())) : it.value();
  return result;
}
QString pageId(const ProjectPages& pages, const PageInfo& page) {
  return pages.stableImageId(page.imageId()) + ":" + subpage(page);
}
bool matches(const QJsonObject& s, const ProjectPages& pages, const PageInfo& page, int pageNumber, int imageNumber) {
  auto contains = [&](const QString& key, const QJsonValue& value) {
    return !s.contains(key) || s[key].toArray().contains(value);
  };
  return contains("pages", pageNumber) && contains("images", imageNumber) && contains("ids", pageId(pages, page))
         && contains("image_ids", pages.stableImageId(page.imageId()))
         && (!s.contains("side") || s["side"] == subpage(page))
         && (!s.contains("parity") || s["parity"] == (pageNumber % 2 ? "odd" : "even"));
}
QJsonObject resolve(const QJsonObject& config,
                    const ProjectPages& pages,
                    const PageInfo& page,
                    int pageNumber,
                    int imageNumber,
                    QJsonObject* origins) {
  QJsonObject result = config["defaults"].toObject(), trace;
  noteOrigins(result, {}, "config.defaults", trace);
  int i = 0;
  for (const auto& item : config["rules"].toArray()) {
    const auto rule = item.toObject();
    if (matches(rule["select"].toObject(), pages, page, pageNumber, imageNumber)) {
      result = merge(result, rule["settings"].toObject());
      noteOrigins(rule["settings"].toObject(), {}, "config.rules[" + QString::number(i) + "]", trace);
    }
    ++i;
  }
  if (origins)
    *origins = trace;
  validateSettings(result);
  return result;
}
void applyProject(const QJsonObject& config,
                  const std::shared_ptr<StageSequence>& stages,
                  const std::shared_ptr<ProjectPages>& pages) {
  const auto p = config["project"].toObject();
  if (p.contains("reading_direction"))
    pages->setLayoutDirection(p["reading_direction"] == "rtl" ? Qt::RightToLeft : Qt::LeftToRight);
  if (p.contains("deskew_algorithm"))
    stages->deskewFilter()->processingSettings()->setAlgoContentBased(p["deskew_algorithm"] == "content");
  auto content = stages->selectContentFilter()->processingSettings();
  if (p.contains("page_detection_size_mm")) {
    auto a = p["page_detection_size_mm"].toArray();
    content->setPageDetectionBox({a[0].toDouble(), a[1].toDouble()});
  }
  if (p.contains("page_detection_tolerance"))
    content->setPageDetectionTolerance(p["page_detection_tolerance"].toDouble());
  auto layout = stages->pageLayoutFilter()->processingSettings();
  if (p.contains("frozen_size_mm")) {
    const auto a = p["frozen_size_mm"].toArray();
    layout->setFrozenAggregateHardSizeMM({a[0].toDouble(), a[1].toDouble()});
  }
  if (p.contains("freeze_layout")) {
    if (p["freeze_layout"].toBool()) {
      check(layout->getAggregateHardSizeMM().width() > 0 && layout->getAggregateHardSizeMM().height() > 0,
            "Analyze layout before freezing its dimensions");
      if (!p.contains("frozen_size_mm"))
        layout->setAggregateHardSizeFrozen(true);
    } else
      layout->setAggregateHardSizeFrozen(false);
  }
  if (p.contains("show_middle_rect"))
    layout->enableShowingMiddleRect(p["show_middle_rect"].toBool());
  if (p.contains("guides")) {
    layout->guides().clear();
    for (const auto& value : p["guides"].toArray()) {
      auto g = value.toObject();
      layout->guides().emplace_back(g["orientation"] == "horizontal" ? Qt::Horizontal : Qt::Vertical,
                                    g["position"].toDouble());
    }
  }
}
QJsonObject inspectProject(const StageSequence& s, const ProjectPages& pages) {
  auto content = s.selectContentFilter()->processingSettings();
  auto layout = s.pageLayoutFilter()->processingSettings();
  QJsonArray guides;
  for (const auto& g : layout->guides())
    guides.append(QJsonObject{{"orientation", g.getOrientation() == Qt::Horizontal ? "horizontal" : "vertical"},
                              {"position", g.getPosition()}});
  QJsonObject result{
      {"reading_direction", pages.layoutDirection() == Qt::RightToLeft ? "rtl" : "ltr"},
      {"deskew_algorithm", s.deskewFilter()->processingSettings()->algoContentBased() ? "content" : "top-edge"},
      {"page_detection_size_mm", pair(content->pageDetectionBox().width(), content->pageDetectionBox().height())},
      {"page_detection_tolerance", content->pageDetectionTolerance()},
      {"freeze_layout", layout->isAggregateHardSizeFrozen()},
      {"show_middle_rect", layout->isShowingMiddleRectEnabled()},
      {"guides", guides}};
  if (layout->isAggregateHardSizeFrozen())
    result["frozen_size_mm"]
        = pair(layout->getAggregateHardSizeMM().width(), layout->getAggregateHardSizeMM().height());
  return result;
}
namespace {
ImageTransformation geometry(const StageSequence& s, const PageInfo& page, bool deskew = true, bool splitOnly = false) {
  ImageTransformation xform(QRectF(QPointF(0, 0), page.metadata().size()), page.metadata().dpi());
  auto orientation = s.fixOrientationFilter()->processingSettings();
  xform.setPreRotation(orientation->getRotationFor(page.imageId()));
  const auto trim = orientation->getTrim(page.imageId());
  if (trim.enabled)
    xform.setPreCropArea(xform.origRectToPreCropSpace(QRectF(trim.toInnerRect(page.metadata().size()))));
  if (!deskew)
    return xform;
  const auto split = s.pageSplitFilter()->processingSettings()->getPageRecord(page.imageId());
  if (split.params()) {
    QPainterPath original, cut;
    original.addPolygon(xform.preCropArea());
    cut.addPolygon(split.params()->pageLayout().pageOutline(page.id().subPage()));
    const auto intersection = original.intersected(cut);
    if (!intersection.isEmpty())
      xform.setPreCropArea(intersection.toFillPolygon());
  }
  if (splitOnly)
    return xform;
  const auto params = s.deskewFilter()->processingSettings()->getPageParams(page.id());
  if (params) {
    xform.setPostRotation(params->deskewAngle());
    xform.setPostOblique(params->obliqueAngle());
  }
  return xform;
}
QJsonObject geometryInfo(const StageSequence& s, const PageInfo& page) {
  const auto x = geometry(s, page);
  const auto t = x.transform();
  QJsonObject result{{"space", "deskew"},
                     {"source_size", pair(page.metadata().size().width(), page.metadata().size().height())},
                     {"source_dpi", pair(page.metadata().dpi().horizontal(), page.metadata().dpi().vertical())},
                     {"source_to_stage", QJsonArray{t.m11(), t.m12(), t.m21(), t.m22(), t.dx(), t.dy()}},
                     {"bounds", box(x.resultingRect())},
                     {"outline", polygonJson(x.resultingPreCropArea())}};
  result["basis"] = QString::fromLatin1(
      QCryptographicHash::hash(QJsonDocument(result).toJson(QJsonDocument::Compact), QCryptographicHash::Sha256)
          .toHex());
  return result;
}
QJsonArray zonesSnapshot(const ZoneSet& zones, bool picture) {
  QJsonArray result;
  for (const auto& zone : zones) {
    QJsonObject item{{"space", "source"}, {"points", polygonJson(zone.spline().toPolygon())}};
    if (picture) {
      auto layer = zone.properties().locate<output::PictureLayerProperty>();
      item["layer"] = layers[int(layer ? layer->layer() : output::PictureLayerProperty::ZONENOOP)];
      auto category = zone.properties().locate<output::ZoneCategoryProperty>();
      item["category"] = category && category->zoneCategory() == output::ZoneCategoryProperty::AUTO ? "auto" : "manual";
    } else {
      auto color = zone.properties().locate<output::FillColorProperty>();
      item["color"] = color ? color->color().name() : "#ffffff";
    }
    result.append(item);
  }
  return result;
}
ZoneSet zonesFromJson(const QJsonArray& array, bool picture, const QSize& size) {
  ZoneSet result;
  for (const auto& value : array) {
    auto item = value.toObject();
    auto points = polygon(item["points"]);
    for (const auto& p : points)
      check(QRectF(QPointF(0, 0), size).contains(p), "Zone point lies outside source image");
    QPainterPath path;
    path.addPolygon(points);
    check(!path.simplified().isEmpty() && path.boundingRect().isValid(), "Zone must have nonzero area");
    PropertySet properties;
    if (picture) {
      properties.locateOrCreate<output::PictureLayerProperty>()->setLayer(
          static_cast<output::PictureLayerProperty::Layer>(layers.indexOf(item["layer"].toString())));
      properties.locateOrCreate<output::ZoneCategoryProperty>()->setZoneCategory(
          item["category"] == "auto" ? output::ZoneCategoryProperty::AUTO : output::ZoneCategoryProperty::MANUAL);
    } else
      properties.locateOrCreate<output::FillColorProperty>()->setColor(QColor(item["color"].toString()));
    Zone zone(SerializableSpline(points), properties);
    check(zone.isValid(), "Invalid zone");
    result.add(zone);
  }
  return result;
}
}  // namespace
namespace {
ImageTransformation stageTransformation(const StageSequence& s,
                                        const PageInfo& page,
                                        const QString& space,
                                        QPolygonF* physicalContent = nullptr) {
  auto x = geometry(s, page, space != "oriented" && space != "orientation", space == "split");
  if (space == "layout" || space == "output") {
    const auto layout = s.pageLayoutFilter()->processingSettings();
    const auto l = layout->getPageParams(page.id());
    check(l && l->pageRect().isValid(), "Analyze through layout before mapping layout/output coordinates");
    const auto contentPhys
        = x.transformBack().map(QPolygonF(page_layout::Utils::adaptContentRect(x, l->contentRect())));
    const auto pagePhys = page_layout::Utils::calcPageRectPhys(x, contentPhys, *l, layout->getAggregateHardSizeMM());
    x.setPostCropArea(page_layout::Utils::shiftToRoundedOrigin(x.transform().map(pagePhys)));
    if (physicalContent)
      *physicalContent = contentPhys;
    if (space == "output")
      x.postScaleToDpi(s.outputFilter()->processingSettings()->getParams(page.id()).outputDpi());
  }
  return x;
}
}  // namespace
QJsonObject stagePreviewGeometry(const StageSequence& s, const PageInfo& page, const QString& stage) {
  return processingPreviewGeometry(stageTransformation(s, page, stage));
}
QImage stagePreview(const StageSequence& s, const PageInfo& page, const QString& stage, const QImage& source) {
  return processingPreview(source, stageTransformation(s, page, stage));
}
QJsonObject mapGeometry(const StageSequence& s, const ProjectPages& pages, const QJsonObject& request) {
  const auto spaces = choice("source|oriented|split|deskew|content|layout|output");
  validateValue(request,
                record({{"schema_version", number(1, 1, true)},
                        {"id", text()},
                        {"from", spaces},
                        {"to", spaces},
                        {"points", array(point(), 1, 10000)}},
                       {"schema_version", "id", "from", "to", "points"}),
                "geometry");
  const auto sequence = pages.toPageSequence(PAGE_VIEW);
  // Extract the validated string explicitly: Qt5 cannot compare QString with QJsonValue.
  const QString requestedId = request["id"].toString();
  auto found = std::find_if(sequence.begin(), sequence.end(),
                            [&](const PageInfo& p) { return pageId(pages, p) == requestedId; });
  check(found != sequence.end(), "Unknown geometry page ID");
  const auto& page = *found;
  auto map = [&](const QPointF& point, const QString& space, bool inverse) {
    if (space == "source")
      return point;
    const auto params = s.outputFilter()->processingSettings()->getParams(page.id());
    QPolygonF contentPhys;
    auto x = stageTransformation(s, page, space, &contentPhys);
    if (space == "output" && params.dewarpingOptions().dewarpingMode() != output::OFF) {
      check(params.distortionModel().isValid(), "Process output first to resolve automatic dewarping geometry");
      // Same mapper and post-rotation used by the GUI FillZoneEditor in output::Task.
      const output::OutputGenerator generator(x, contentPhys);
      const auto post
          = output::Utils::rotate(params.dewarpingOptions().getPostDeskewAngle(), x.resultingRect().toRect());
      dewarping::DewarpingPointMapper mapper(params.distortionModel(), params.depthPerception().value(), x.transform(),
                                             generator.outputContentRect(), post);
      return inverse ? mapper.mapToWarpedSpace(point) : mapper.mapToDewarpedSpace(point);
    }
    return inverse ? x.transformBack().map(point) : x.transform().map(point);
  };
  QJsonArray mapped;
  for (const auto& p : polygon(request["points"])) {
    const auto v = map(map(p, request["from"].toString(), true), request["to"].toString(), false);
    check(std::isfinite(v.x()) && std::isfinite(v.y()), "Point is outside the valid transform domain");
    mapped.append(pair(v.x(), v.y()));
  }
  auto result = request;
  result["points"] = mapped;
  result["basis"] = geometryInfo(s, page)["basis"];
  return result;
}
void apply(const QJsonObject& settings,
           const std::shared_ptr<StageSequence>& s,
           const std::shared_ptr<ProjectPages>& pages,
           const PageInfo& originalPage,
           Scope scope) {
  validateSettings(settings);
  for (const auto& filter : s->filters())
    filter->loadDefaultSettings(originalPage);
  auto page = originalPage;
  auto metadata = page.metadata();
  const auto id = page.id();
  if (scope != Scope::Logical) {
    const auto input = settings["input"].toObject();
    if (input.contains("dpi")) {
      auto d = input["dpi"].toArray();
      metadata.setDpi(Dpi(d[0].toInt(), d[1].toInt()));
      pages->updateImageMetadata(page.imageId(), metadata);
      page = PageInfo(id, metadata, page.imageSubPages(), page.leftHalfRemoved(), page.rightHalfRemoved());
    }
    const auto o = settings["orientation"].toObject();
    auto orientation = s->fixOrientationFilter()->processingSettings();
    if (o.contains("rotation")) {
      OrthogonalRotation r;
      for (int i = 0; i < o["rotation"].toInt() / 90; ++i)
        r.nextClockwiseDirection();
      orientation->applyRotation(page.imageId(), r);
    }
    if (o.contains("trim")) {
      auto trim = orientation->getTrim(page.imageId());
      auto patch = o["trim"].toObject();
      if (patch.contains("enabled"))
        trim.enabled = patch["enabled"].toBool();
      if (patch.contains("left"))
        trim.left = patch["left"].toInt();
      if (patch.contains("right"))
        trim.right = patch["right"].toInt();
      if (patch.contains("top"))
        trim.top = patch["top"].toInt();
      if (patch.contains("bottom"))
        trim.bottom = patch["bottom"].toInt();
      check(!trim.enabled
                || (metadata.size().width() - trim.left - trim.right >= fix_orientation::kMinTrimInnerSide
                    && metadata.size().height() - trim.top - trim.bottom >= fix_orientation::kMinTrimInnerSide),
            "Trim must retain at least 32 pixels on each side");
      orientation->setTrim(page.imageId(), trim);
    }
    const auto split = settings["split"].toObject();
    if (!split.isEmpty()) {
      auto store = s->pageSplitFilter()->processingSettings();
      const auto old = store->getPageRecord(page.imageId());
      auto type = old.combinedLayoutType();
      if (split.contains("layout")) {
        const auto v = split["layout"].toString();
        type = v == "auto"  ? page_split::AUTO_LAYOUT_TYPE
               : v == "two" ? page_split::TWO_PAGES
               : v == "cut" ? page_split::PAGE_PLUS_OFFCUT
                            : page_split::SINGLE_PAGE_UNCUT;
      }
      page_split::Settings::UpdateAction action;
      action.setLayoutType(type);
      if (split.contains("cutters")) {
        const auto rect = geometry(*s, page, false).resultingRect();
        auto cutters = split["cutters"].toArray();
        auto p = polygon(cutters[0]);
        QLineF first(p[0], p[1]);
        page_split::PageLayout layout(rect, first);
        if (type == page_split::PAGE_PLUS_OFFCUT) {
          p = polygon(cutters[1]);
          layout = page_split::PageLayout(rect, first, QLineF(p[0], p[1]));
        }
        check(type == page_split::TWO_PAGES || layout.singlePageOutline().boundingRect().isValid(),
              "Cutters leave no page");
        if (type == page_split::TWO_PAGES)
          check(layout.leftPageOutline().boundingRect().isValid() && layout.rightPageOutline().boundingRect().isValid(),
                "Splitter must intersect the page");
        action.setParams(page_split::Params(
            layout, page_split::Dependencies(metadata.size(), orientation->getRotationFor(page.imageId()), type),
            MODE_MANUAL));
      } else if (split["mode"] == "auto" || split["layout"] == "auto")
        action.clearParams();
      else if (split["mode"] == "manual") {
        check(old.params(), "Manual splitting requires cutters or previously analyzed split geometry");
        auto params = *old.params();
        params.setSplitLineMode(MODE_MANUAL);
        action.setParams(params);
      }
      store->updatePage(page.imageId(), action);
      if (type != page_split::AUTO_LAYOUT_TYPE)
        pages->setLayoutTypeFor(page.imageId(), type == page_split::TWO_PAGES ? ProjectPages::TWO_PAGE_LAYOUT
                                                                              : ProjectPages::ONE_PAGE_LAYOUT);
    }
  }
  if (scope == Scope::Source)
    return;
  const auto skew = settings["deskew"].toObject();
  if (!skew.isEmpty()) {
    auto store = s->deskewFilter()->processingSettings();
    const auto old = store->getPageParams(id);
    double angle = old->deskewAngle(), oblique = old->obliqueAngle();
    auto rotationMode = old->mode(), obliqueMode = old->obliqueMode();
    if (skew.contains("mode")) {
      rotationMode = skew["mode"] == "auto" ? MODE_AUTO : MODE_MANUAL;
      if (skew["mode"] == "off")
        angle = 0;
    }
    if (skew.contains("angle")) {
      angle = skew["angle"].toDouble();
      rotationMode = MODE_MANUAL;
    }
    if (skew.contains("oblique_mode")) {
      obliqueMode = skew["oblique_mode"] == "auto" ? MODE_AUTO : MODE_MANUAL;
      if (skew["oblique_mode"] == "off")
        oblique = 0;
    }
    if (skew.contains("oblique_angle")) {
      oblique = skew["oblique_angle"].toDouble();
      obliqueMode = MODE_MANUAL;
    }
    store->setPageParams(id, deskew::Params(angle, oblique, old->dependencies(), rotationMode, obliqueMode));
    if (skew.contains("oblique_mode") || skew.contains("oblique_angle"))
      store->setPendingAutoOblique(id, obliqueMode == MODE_AUTO);
  }
  const auto c = settings["content"].toObject();
  if (!c.isEmpty()) {
    auto store = s->selectContentFilter()->processingSettings();
    auto p = store->getPageParams(id);
    if (c.contains("basis"))
      check(c["basis"] == geometryInfo(*s, page)["basis"],
            "Content geometry basis changed; analyze and update manual rectangles");
    if (c.contains("page_mode"))
      p->setPageDetectionMode(mode(c["page_mode"]));
    if (c.contains("content_mode"))
      p->setContentDetectionMode(mode(c["content_mode"]));
    if (c.contains("fine_tune"))
      p->setFineTuneCornersEnabled(c["fine_tune"].toBool());
    if (c.contains("page_rect")) {
      p->setPageRect(rectangle(c["page_rect"]));
      p->setPageDetectionMode(MODE_MANUAL);
    }
    if (c.contains("content_rect")) {
      p->setContentRect(rectangle(c["content_rect"]));
      p->setContentDetectionMode(MODE_MANUAL);
    }
    if (p->pageDetectionMode() == MODE_MANUAL)
      check(p->pageRect().isValid(), "Manual page detection requires a rectangle");
    if (p->contentDetectionMode() == MODE_MANUAL)
      check(p->contentRect().isValid(), "Manual content detection requires a rectangle");
    p->setDependencies(select_content::Dependencies());
    store->setPageParams(id, *p);
  }
  const auto l = settings["layout"].toObject();
  if (!l.isEmpty()) {
    auto store = s->pageLayoutFilter()->processingSettings();
    auto old = store->getPageParams(id);
    auto m = old->hardMarginsMM();
    const auto margins = l["margins_mm"].toObject();
    if (margins.contains("left"))
      m.setLeft(margins["left"].toDouble());
    if (margins.contains("right"))
      m.setRight(margins["right"].toDouble());
    if (margins.contains("top"))
      m.setTop(margins["top"].toDouble());
    if (margins.contains("bottom"))
      m.setBottom(margins["bottom"].toDouble());
    auto a = old->alignment();
    if (l.contains("match_size"))
      a.setNull(!l["match_size"].toBool());
    if (l.contains("horizontal"))
      a.setHorizontal(static_cast<page_layout::Alignment::Horizontal>(
          QStringList{"left", "center", "right", "auto", "original"}.indexOf(l["horizontal"].toString())));
    if (l.contains("vertical"))
      a.setVertical(static_cast<page_layout::Alignment::Vertical>(
          QStringList{"top", "center", "bottom", "auto", "original"}.indexOf(l["vertical"].toString())));
    store->setPageParams(
        id, page_layout::Params(m, old->pageRect(), old->contentRect(), old->contentSizeMM(), a,
                                l.contains("auto_margins") ? l["auto_margins"].toBool() : old->isAutoMarginsEnabled()));
  }
  auto store = s->outputFilter()->processingSettings();
  const auto out = settings["output"].toObject();
  if (!out.isEmpty()) {
    QDomDocument doc;
    auto old = store->getParams(id);
    auto el = old.toXml(doc, "params");
    for (const auto& f : outputFields())
      if (out.contains(f.name)) {
        QString attr;
        auto node = childPath(el, f.path, &attr);
        const auto value = out[f.name];
        node.setAttribute(attr, f.type == "boolean" ? (value.toBool() ? "1" : "0")
                                : f.type == "enum"  ? value.toString()
                                                    : QString::number(value.toDouble(), 'g', 17));
      }
    output::Params p(el);
    if (out.contains("dpi")) {
      auto d = out["dpi"].toArray();
      p.setOutputDpi(Dpi(d[0].toInt(), d[1].toInt()));
    }
    if (out.contains("distortion_model")) {
      const auto model = out["distortion_model"].toObject();
      auto curve = [&](const QString& name) {
        if (model.contains(name)) {
          auto points = polygon(model[name]);
          return dewarping::Curve(std::vector<QPointF>(points.begin(), points.end()));
        }
        XSpline spline;
        for (const auto& v : model[name + "_spline"].toArray()) {
          const auto control = v.toObject();
          const auto point = control["point"].toArray();
          spline.appendControlPoint(QPointF(point[0].toDouble(), point[1].toDouble()), control["tension"].toDouble());
        }
        check(!dewarping::Curve::splineHasLoops(spline), "Dewarping spline must not loop");
        return dewarping::Curve(spline);
      };
      dewarping::DistortionModel d;
      d.setTopCurve(curve("top"));
      d.setBottomCurve(curve("bottom"));
      check(d.isValid(), "Invalid dewarping curves (endpoints must form a convex quadrilateral)");
      p.setDistortionModel(d);
    }
    check(p.colorParams().blackWhiteOptions().getWolfLowerBound()
              <= p.colorParams().blackWhiteOptions().getWolfUpperBound(),
          "wolf_lower exceeds wolf_upper");
    check(p.dewarpingOptions().dewarpingMode() != output::MANUAL || p.distortionModel().isValid(),
          "Manual dewarp requires a valid distortion_model");
    check(!p.splittingOptions().isSplitOutput() || p.colorParams().colorMode() == output::MIXED,
          "Split output requires mixed mode");
    store->setParams(id, p);
    store->removeOutputParams(id);
    auto processing = store->getOutputProcessingParams(id);
    if (out.contains("black_on_white"))
      processing.setBlackOnWhiteSetManually(true);
    if (out.contains("picture_shape") || out.contains("picture_sensitivity")
        || out.contains("picture_high_sensitivity"))
      processing.setAutoZonesFound(false);
    store->setOutputProcessingParams(id, processing);
  }
  if (settings.contains("picture_zones"))
    store->setPictureZones(id, zonesFromJson(settings["picture_zones"].toArray(), true, metadata.size()));
  if (settings.contains("fill_zones"))
    store->setFillZones(id, zonesFromJson(settings["fill_zones"].toArray(), false, metadata.size()));
}
QJsonObject inspect(const StageSequence& s, const PageInfo& page) {
  auto orientation = s.fixOrientationFilter()->processingSettings();
  const auto trim = orientation->getTrim(page.imageId());
  QJsonObject result{
      {"input", QJsonObject{{"dpi", pair(page.metadata().dpi().horizontal(), page.metadata().dpi().vertical())}}},
      {"orientation", QJsonObject{{"rotation", orientation->getRotationFor(page.imageId()).toDegrees()},
                                  {"trim", QJsonObject{{"enabled", trim.enabled},
                                                       {"left", trim.left},
                                                       {"top", trim.top},
                                                       {"right", trim.right},
                                                       {"bottom", trim.bottom}}}}}};
  const auto split = s.pageSplitFilter()->processingSettings()->getPageRecord(page.imageId());
  const auto type = split.combinedLayoutType();
  QJsonObject sp{{"layout", type == page_split::AUTO_LAYOUT_TYPE   ? "auto"
                            : type == page_split::TWO_PAGES        ? "two"
                            : type == page_split::PAGE_PLUS_OFFCUT ? "cut"
                                                                   : "single"}};
  if (split.params()) {
    sp["mode"] = modeName(split.params()->splitLineMode());
    QJsonArray cutters;
    const auto& p = split.params()->pageLayout();
    for (int i = 0; i < p.numCutters(); ++i)
      cutters.append(QJsonArray{pair(p.cutterLine(i).x1(), p.cutterLine(i).y1()),
                                pair(p.cutterLine(i).x2(), p.cutterLine(i).y2())});
    if (sp["mode"] == "manual" && !cutters.empty()) {
      sp["cutters"] = cutters;
      sp["space"] = "oriented";
    }
  }
  result["split"] = sp;
  const auto d = s.deskewFilter()->processingSettings()->getPageParams(page.id());
  if (d)
    result["deskew"] = QJsonObject{{"mode", modeName(d->mode())},
                                   {"angle", d->deskewAngle()},
                                   {"oblique_mode", modeName(d->obliqueMode())},
                                   {"oblique_angle", d->obliqueAngle()}};
  const auto c = s.selectContentFilter()->processingSettings()->getPageParams(page.id());
  if (c) {
    QJsonObject content{{"page_mode", modeName(c->pageDetectionMode())},
                        {"content_mode", modeName(c->contentDetectionMode())},
                        {"fine_tune", c->isFineTuningEnabled()},
                        {"space", "deskew"}};
    if (c->pageDetectionMode() == MODE_MANUAL && c->pageRect().isValid())
      content["page_rect"] = box(c->pageRect());
    if (c->contentDetectionMode() == MODE_MANUAL && c->contentRect().isValid())
      content["content_rect"] = box(c->contentRect());
    result["content"] = content;
  }
  const auto l = s.pageLayoutFilter()->processingSettings()->getPageParams(page.id());
  if (l) {
    const auto m = l->hardMarginsMM();
    const auto a = l->alignment();
    result["layout"] = QJsonObject{
        {"margins_mm", QJsonObject{{"left", m.left()}, {"top", m.top()}, {"right", m.right()}, {"bottom", m.bottom()}}},
        {"auto_margins", l->isAutoMarginsEnabled()},
        {"match_size", !a.isNull()},
        {"horizontal", QStringList{"left", "center", "right", "auto", "original"}[int(a.horizontal())]},
        {"vertical", QStringList{"top", "center", "bottom", "auto", "original"}[int(a.vertical())]}};
  }
  auto out = s.outputFilter()->processingSettings();
  result["output"] = outputSnapshot(out->getParams(page.id()));
  result["picture_zones"] = zonesSnapshot(out->pictureZonesForPage(page.id()), true);
  result["fill_zones"] = zonesSnapshot(out->fillZonesForPage(page.id()), false);
  result["_geometry"] = geometryInfo(s, page);
  if (result["content"].toObject().contains("page_rect") || result["content"].toObject().contains("content_rect")) {
    auto content = result["content"].toObject();
    content["basis"] = result["_geometry"].toObject()["basis"];
    result["content"] = content;
  }
  if (c)
    result["_detected"] = QJsonObject{{"page_rect", box(c->pageRect())}, {"content_rect", box(c->contentRect())}};
  return result;
}
}  // namespace processing
