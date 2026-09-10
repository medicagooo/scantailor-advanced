// Copyright (C) 2026. Distributed under the GNU GPLv3 license.
#include "BatchRunner.h"
#include <core/Application.h>
#include <core/ColorSchemeFactory.h>
#include <core/ColorSchemeManager.h>
#include <core/IconProvider.h>
#include <core/StyledIconPack.h>
#include <QCommandLineParser>
#include <QFile>
#include <QImageReader>
#include <QJsonDocument>
#include <QSettings>
#include <QTemporaryDir>
#include <cmath>
#include <csignal>
#include <cstdio>
#include <iostream>
#ifdef _WIN32
#include <windows.h>
#endif

namespace {
void onSignal(int) { cli::cancelled.store(true); }
#ifdef _WIN32
BOOL WINAPI onConsole(DWORD event) {
  if (event == CTRL_C_EVENT || event == CTRL_BREAK_EVENT) {
    cli::cancelled.store(true);
    return TRUE;
  }
  return FALSE;
}
#endif
void fail(const QString& text) { throw std::invalid_argument(text.toStdString()); }
}

int main(int argc, char** argv) {
  // Legacy diagnostic streams must not corrupt the JSONL protocol.
  std::cout.rdbuf(std::cerr.rdbuf());
  // Qt Widgets is retained by the shared filters, but no window is shown.
  // A private settings directory prevents GUI preferences changing CLI output.
  qputenv("QT_QPA_PLATFORM", "offscreen");
  QTemporaryDir settingsDir;
  Application app(argc, argv, false);
  QCoreApplication::setApplicationName("scantailor-cli");
  QCoreApplication::setOrganizationName("ScanTailorCLI");
  QCoreApplication::setApplicationVersion("1.0.0");
  QSettings::setDefaultFormat(QSettings::IniFormat);
  QSettings::setPath(QSettings::IniFormat, QSettings::UserScope, settingsDir.path());
  QSettings::setPath(QSettings::IniFormat, QSettings::SystemScope, settingsDir.path());
  std::signal(SIGINT, onSignal);
  std::signal(SIGTERM, onSignal);
#ifdef _WIN32
  SetConsoleCtrlHandler(onConsole, TRUE);
#endif
  QCommandLineParser parser;
  parser.setApplicationDescription("Unattended ScanTailor image processing. JSONL events on stdout; diagnostics on stderr.");
  parser.addHelpOption();
  parser.addVersionOption();
  parser.addPositionalArgument("command", "process or doctor");
  const QStringList paths = {"input", "output", "project", "save-project", "config"};
  for (const auto& name : paths) parser.addOption({name, name + " path", "path"});
  const QStringList strings = {"preset", "deskew", "page-detection", "content-detection", "color-mode", "dewarp"};
  for (const auto& name : strings) parser.addOption({name, name + " setting (see docs/CLI.md)", "value"});
  const QStringList numbers = {"dpi", "output-dpi", "rotate", "deskew-angle", "margin-mm", "jobs", "max-angle", "min-page-ratio"};
  for (const auto& name : numbers) parser.addOption({name, name + " numeric value", "number"});
  const QStringList booleans = {"fill-margins", "fill-offcut"};
  for (const auto& name : booleans) parser.addOption({name, name + " true or false", "boolean"});
  parser.addOption({"resume", "Reuse verified completed outputs from this job."});
  parser.addOption({"overwrite", "Allow replacing outputs belonging to this job."});
  try {
    if (!parser.parse(app.arguments())) fail(parser.errorText());
    if (parser.isSet("help")) { std::fputs(parser.helpText().toUtf8().constData(), stdout); return 0; }
    if (parser.isSet("version")) { std::puts("scantailor-cli 1.0.0"); return 0; }
    if (parser.positionalArguments().size() != 1) fail("Specify process or doctor; use --help.");
    const QString command = parser.positionalArguments().first();
    if (command == "doctor") {
      QStringList formats;
      for (const auto& f : QImageReader::supportedImageFormats()) formats << QString::fromLatin1(f);
      cli::emitEvent({{"event", "doctor"}, {"cli_version", "1.0.0"}, {"qt_version", qVersion()},
                      {"platform", "offscreen"}, {"qt_image_formats", formats.join(",")},
                      {"core_image_formats", "png,jpeg,tiff"}, {"status", "ok"}});
      return 0;
    }
    if (command != "process") fail("Unknown command: " + command);
    QJsonObject options;
    if (parser.isSet("config")) {
      QFile file(parser.value("config"));
      if (!file.open(QIODevice::ReadOnly)) fail("Cannot read configuration.");
      QJsonParseError error;
      const auto doc = QJsonDocument::fromJson(file.readAll(), &error);
      if (error.error != QJsonParseError::NoError || !doc.isObject()) fail("Configuration must be a JSON object.");
      options = doc.object();
      if (options.take("schema_version").toInt() != 1) fail("Configuration schema_version must be 1.");
    }
    QStringList allowed = paths + strings + numbers + booleans + QStringList{"resume", "overwrite"};
    allowed.removeAll("config");
    for (const auto& key : options.keys()) if (!allowed.contains(key)) fail("Unknown configuration key: " + key);
    for (const auto& key : paths + strings) {
      if (parser.isSet(key) && key != "config") options[key] = parser.value(key);
    }
    for (const auto& key : numbers) {
      if (parser.isSet(key)) {
        bool ok = false;
        const double value = parser.value(key).toDouble(&ok);
        if (!ok || !std::isfinite(value)) fail("Invalid number: " + key);
        options[key] = value;
      }
      if (options.contains(key) && !options[key].isDouble()) fail("Expected a number: " + key);
    }
    for (const auto& key : booleans) {
      if (parser.isSet(key)) {
        const auto value = parser.value(key);
        if (value != "true" && value != "false") fail("Expected true or false: " + key);
        options[key] = value == "true";
      }
    }
    for (const auto& key : QStringList{"resume", "overwrite"}) if (parser.isSet(key)) options[key] = true;
    for (const auto& key : booleans + QStringList{"resume", "overwrite"})
      if (options.contains(key) && !options[key].isBool()) fail("Expected a boolean: " + key);
    for (const auto& key : paths + strings)
      if (options.contains(key) && !options[key].isString()) fail("Expected a string: " + key);
    auto range = [&](const QString& key, double lo, double hi, bool integer = false) {
      if (!options.contains(key)) return;
      double v = options[key].toDouble();
      if (!std::isfinite(v) || v < lo || v > hi || (integer && std::floor(v) != v)) fail("Out of range: " + key);
    };
    range("dpi", 72, 1200, true); range("output-dpi", 72, 1200, true);
    range("jobs", 1, 16, true); range("margin-mm", 0, 100);
    range("max-angle", 0, 45); range("deskew-angle", -45, 45); range("min-page-ratio", 0.1, 1);
    range("rotate", 0, 270, true);
    if (options.contains("rotate") && options["rotate"].toInt() % 90) fail("rotate must be 0, 90, 180 or 270.");
    auto choice = [&](const QString& key, const QStringList& values) {
      if (options.contains(key) && !values.contains(options[key].toString())) fail("Invalid value: " + key);
    };
    choice("preset", {"physics-safe"}); choice("deskew", {"auto", "off", "manual"});
    choice("page-detection", {"auto", "off"}); choice("content-detection", {"auto", "off"});
    choice("color-mode", {"color-grayscale", "black-white", "mixed"}); choice("dewarp", {"off", "auto"});
    if (options.contains("deskew-angle")) {
      if (options.contains("deskew") && options["deskew"] != "manual") fail("deskew-angle requires manual deskew.");
      options["deskew"] = "manual";
    }
    if (options.value("deskew") == "manual" && !options.contains("deskew-angle")) fail("manual deskew requires deskew-angle.");
    if (options.value("input").toString().isEmpty() == options.value("project").toString().isEmpty())
      fail("Specify exactly one of --input and --project.");
    if (options.value("output").toString().isEmpty()) fail("--output is required.");
    auto scheme = ColorSchemeFactory().create("light");
    ColorSchemeManager::instance().setColorScheme(*scheme);
    IconProvider::getInstance().setIconPack(StyledIconPack::createDefault());
    return cli::run(options);
  } catch (const std::invalid_argument& error) {
    cli::emitEvent({{"event", "error"}, {"message", QString::fromUtf8(error.what())}, {"exit_code", 2}});
    return 2;
  } catch (const std::exception& error) {
    cli::emitEvent({{"event", "error"}, {"message", QString::fromUtf8(error.what())}, {"exit_code", 3}});
    return 3;
  }
}
