#include "ImageEncoding.h"
#include "TiffWriter.h"
#include <QImageWriter>
#include <QSaveFile>
#include <QPainter>
#include <QStringList>
#include <cmath>
#include <stdexcept>
namespace {
void require(bool ok, const QString& text) { if (!ok) throw std::invalid_argument(text.toStdString()); }
}
ImageEncoding ImageEncoding::fromJson(const QJsonObject& value) {
  ImageEncoding result;
  result.format = value.value("format").toString("png");
  require(!value.contains("format") || value["format"].isString(), "image_encoding.format must be a string");
  require(QStringList{"png", "tiff", "jpeg"}.contains(result.format), "Invalid image format");
  const QString key = result.format == "png" ? "png_compression" : result.format == "tiff" ? "tiff_compression" : "jpeg_quality";
  for (const auto& k : value.keys()) require(k == "format" || k == key, "image_encoding: unrelated or unknown option " + k);
  if (result.format == "tiff") {
    const auto compression = value.value(key).toString("deflate");
    require(!value.contains(key) || value[key].isString(), "TIFF compression must be a string");
    require(QStringList{"none", "lzw", "deflate"}.contains(compression), "Invalid TIFF compression");
    result.tiffCompression = compression == "none" ? COMPRESSION_NONE : compression == "lzw" ? COMPRESSION_LZW : COMPRESSION_ADOBE_DEFLATE;
  } else {
    const double n = value.value(key).toDouble(result.format == "png" ? 6 : 95);
    require(!value.contains(key) || value[key].isDouble(), "Image compression must be an integer");
    require(std::isfinite(n) && std::floor(n) == n && n >= (result.format == "png" ? 0 : 1) && n <= (result.format == "png" ? 9 : 100), "Image compression out of range");
    if (result.format == "png") result.pngCompression = int(n); else result.jpegQuality = int(n);
  }
  return result;
}
QJsonObject ImageEncoding::json() const {
  QJsonObject result{{"format", format}};
  if (format == "png") result["png_compression"] = pngCompression;
  else if (format == "jpeg") result["jpeg_quality"] = jpegQuality;
  else result["tiff_compression"] = tiffCompression == COMPRESSION_NONE ? "none" : tiffCompression == COMPRESSION_LZW ? "lzw" : "deflate";
  return result;
}
QString ImageEncoding::suffix() const { return format == "tiff" ? ".tif" : format == "jpeg" ? ".jpg" : ".png"; }
bool ImageEncoding::write(const QString& path, const QImage& image) const {
  if (image.isNull()) return false;
  QSaveFile file(path);
  if (!file.open(QIODevice::WriteOnly)) return false;
  bool ok;
  if (format == "tiff") ok = TiffWriter::writeImage(file, image, tiffCompression);
  else {
    QImage encoded = image;
    if (format == "jpeg" && image.hasAlphaChannel()) {
      encoded = QImage(image.size(), QImage::Format_RGB32); encoded.fill(Qt::white);
      QPainter painter(&encoded); painter.drawImage(0, 0, image); painter.end();
      encoded.setDotsPerMeterX(image.dotsPerMeterX()); encoded.setDotsPerMeterY(image.dotsPerMeterY());
    }
    QImageWriter writer(&file, format.toLatin1());
    // Qt 6.8 QPNG maps [0,100] to zlib using (compression * 9) / 91.
    // Invert that mapping so the public 0..9 option is a real zlib level.
    // https://github.com/qt/qtbase/blob/v6.8.3/src/gui/image/qpnghandler.cpp
    if (format == "png") writer.setCompression((pngCompression * 91 + 8) / 9);
    else writer.setQuality(jpegQuality);
    ok = writer.write(encoded);
  }
  if (!ok) { file.cancelWriting(); return false; }
  return file.commit();
}
