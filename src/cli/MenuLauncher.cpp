// Copyright (C) 2026. Distributed under the GNU GPLv3 license.
#include "MenuLauncher.h"
#include <QCoreApplication>
#include <QFileInfo>
#include <QProcess>
#include <QStandardPaths>
#include <cstdio>
#ifdef _WIN32
#include <windows.h>
#endif
namespace cli {
bool interactiveConsole() {
#ifdef _WIN32
  DWORD input, output;
  return GetConsoleMode(GetStdHandle(STD_INPUT_HANDLE), &input) && GetConsoleMode(GetStdHandle(STD_OUTPUT_HANDLE), &output);
#else
  return false;
#endif
}
int launchMenu(const QStringList& arguments) {
  if (!interactiveConsole()) { std::fputs("Menu requires an interactive Windows console. Use existing commands for redirected input/output.\n",stderr); return 2; }
  auto rest = arguments; QString python;
  const int option = rest.indexOf("--python");
  if (option >= 0) {
    if (option + 1 >= rest.size()) { std::fputs("--python requires a path\n",stderr); return 2; }
    python = rest[option+1]; rest.removeAt(option+1); rest.removeAt(option);
  }
  const auto root = QCoreApplication::applicationDirPath();
  if (python.isEmpty() && QFileInfo::exists(root + "/python/python.exe")) python = root + "/python/python.exe";
  if (python.isEmpty()) python = QStandardPaths::findExecutable("python");
  const auto script = root + "/menu.py";
  if (python.isEmpty() || !QFileInfo::exists(script)) { std::fputs("Menu runtime missing: use the complete portable package or menu --python <python.exe>.\n",stderr); return 3; }
  // The controller owns keyboard/mouse input; workers run separately and send
  // JSONL to it. No shell command string is constructed from user paths.
  QProcess process; process.setProcessChannelMode(QProcess::ForwardedChannels); process.setInputChannelMode(QProcess::ForwardedInputChannel);
  process.start(python, QStringList{script,"--cli",QCoreApplication::applicationFilePath()} + rest);
  if (!process.waitForStarted()) { std::fputs("Cannot start menu runtime\n",stderr); return 3; }
  process.waitForFinished(-1);
  return process.exitStatus() == QProcess::NormalExit ? process.exitCode() : 3;
}
}
