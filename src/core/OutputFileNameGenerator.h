// Copyright (C) 2019  Joseph Artsimovich <joseph.artsimovich@gmail.com>, 4lex4 <4lex49@zoho.com>
// Use of this source code is governed by the GNU GPLv3 license that can be found in the LICENSE file.

#ifndef SCANTAILOR_CORE_OUTPUTFILENAMEGENERATOR_H_
#define SCANTAILOR_CORE_OUTPUTFILENAMEGENERATOR_H_

#include <QString>
#include <Qt>
#include <memory>

#include "FileNameDisambiguator.h"
#include "ImageEncoding.h"

class PageId;
class AbstractRelinker;

class OutputFileNameGenerator {
  // Member-wise copying is OK.
 public:
  OutputFileNameGenerator();

  OutputFileNameGenerator(std::shared_ptr<FileNameDisambiguator> disambiguator,
                          const QString& outDir,
                          Qt::LayoutDirection layoutDirection);

  // CLI supplies an immutable page-output policy. GUI constructors keep TIFF.
  void setImageEncoding(const ImageEncoding& encoding) { m_encoding = encoding; }
  bool writeImage(const QString& path, const QImage& image) const { return m_encoding.write(path, image); }

  void performRelinking(const AbstractRelinker& relinker);

  void setLayoutDirection(Qt::LayoutDirection dir) { m_layoutDirection = dir; }

  Qt::LayoutDirection layoutDirection() const { return m_layoutDirection; }

  const QString& outDir() const { return m_outDir; }

  FileNameDisambiguator* disambiguator() { return m_disambiguator.get(); }

  const FileNameDisambiguator* disambiguator() const { return m_disambiguator.get(); }

  QString fileNameFor(const PageId& page) const;

  QString filePathFor(const PageId& page) const;

 private:
  std::shared_ptr<FileNameDisambiguator> m_disambiguator;
  QString m_outDir;
  ImageEncoding m_encoding;
  Qt::LayoutDirection m_layoutDirection;
};


#endif  // ifndef SCANTAILOR_CORE_OUTPUTFILENAMEGENERATOR_H_
