// Copyright (C) 2026. Distributed under the GNU GPLv3 license.
#include <core/Application.h>
#include <core/ColorSchemeFactory.h>
#include <core/ColorSchemeManager.h>
#include <core/IconProvider.h>
#include <core/StyledIconPack.h>
#include <core/PageSequence.h>
#include <QSettings>
#include <QTemporaryDir>
#include <QFileInfo>
#include <cstdio>
#include "MainWindow.h"

int main(int argc, char** argv) {
  qputenv("QT_QPA_PLATFORM", "offscreen");
  QTemporaryDir settings;
  Application app(argc,argv,false);
  QCoreApplication::setOrganizationName("ScanTailorRoundtripTest");
  QCoreApplication::setApplicationName("GuiRoundtripTest");
  QSettings::setDefaultFormat(QSettings::IniFormat);
  QSettings::setPath(QSettings::IniFormat,QSettings::UserScope,settings.path());
  QSettings::setPath(QSettings::IniFormat,QSettings::SystemScope,settings.path());
  const auto args = app.arguments();
  if (args.size() != 2 || !QFileInfo(args[1]).isFile()) return 2;
  auto scheme = ColorSchemeFactory().create("light");
  ColorSchemeManager::instance().setColorScheme(*scheme);
  IconProvider::getInstance().setIconPack(StyledIconPack::createDefault());
  MainWindow window;
  window.openProject(args[1]);
  if (window.allPages().numPages() == 0) return 3;
  if (!QMetaObject::invokeMethod(&window,"toggleTwoPageSpreadReadingOrder",Qt::DirectConnection)) return 4;
  if (!QMetaObject::invokeMethod(&window,"saveProjectTriggered",Qt::DirectConnection)) return 5;
  std::puts("GUI open, reading-order edit and save completed");
  return 0;
}
