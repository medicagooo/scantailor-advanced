// CLI encoding is copied with each output task; GUI defaults remain TIFF.
#ifndef SCANTAILOR_CORE_IMAGEENCODING_H_
#define SCANTAILOR_CORE_IMAGEENCODING_H_
#include <QJsonObject>
#include <QImage>
#include <QString>
struct ImageEncoding {
  QString format = "tiff";
  int pngCompression = 6;
  int tiffCompression = -1; // GUI preferences when no CLI policy was supplied.
  int jpegQuality = 95;
  static ImageEncoding fromJson(const QJsonObject& value);
  QJsonObject json() const;
  QString suffix() const;
  bool write(const QString& path, const QImage& image) const;
};
#endif
