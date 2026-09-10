// Copyright (C) 2026. Distributed under the GNU GPLv3 license.
#pragma once
#include "ImageTransformation.h"
#include <QImage>
#include <QPainter>
#include <QPainterPath>
#include <QJsonObject>
#include <QJsonArray>
#include <algorithm>
#include <cmath>
// Preview rendering shares the stage's exact affine transform. It is explicitly
// a scaled inspection image, not the output algorithm or an OCR representation.
inline QJsonObject processingPreviewGeometry(const ImageTransformation& xform) {
  const QRectF bounds = xform.resultingRect();
  const double scale = std::min(1.0, 1600.0 / std::max({1.0, bounds.width(), bounds.height()}));
  QTransform view; view.scale(scale, scale); view.translate(-bounds.left(), -bounds.top());
  const auto t = xform.transform() * view;
  return {{"source_to_preview", QJsonArray{t.m11(), t.m12(), t.m21(), t.m22(), t.dx(), t.dy()}},
          {"size", QJsonArray{std::max(1, int(std::ceil(bounds.width()*scale))), std::max(1, int(std::ceil(bounds.height()*scale)))}},
          {"scale", scale}};
}
inline QImage processingPreview(const QImage& source, const ImageTransformation& xform) {
  const auto info = processingPreviewGeometry(xform); const auto dims = info["size"].toArray();
  QImage image(dims[0].toInt(), dims[1].toInt(), QImage::Format_RGB32); image.fill(Qt::white);
  QPainter painter(&image); painter.setRenderHint(QPainter::SmoothPixmapTransform);
  const auto m = info["source_to_preview"].toArray();
  painter.setTransform(QTransform(m[0].toDouble(), m[1].toDouble(), m[2].toDouble(), m[3].toDouble(), m[4].toDouble(), m[5].toDouble()));
  QPainterPath clip; clip.addPolygon(xform.transformBack().map(xform.resultingPreCropArea())); painter.setClipPath(clip);
  painter.drawImage(QPointF(0,0), source); return image;
}
