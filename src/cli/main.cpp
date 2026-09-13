// Copyright (C) 2026. Distributed under the GNU GPLv3 license.
#include "BatchRunner.h"
#include "ProjectSession.h"
#include "MenuLauncher.h"
#include <core/ImageEncoding.h>
#include <core/Application.h>
#include <core/ColorSchemeFactory.h>
#include <core/ColorSchemeManager.h>
#include <core/IconProvider.h>
#include <core/StyledIconPack.h>
#include <QCommandLineParser>
#include <QFile>
#include <QImageReader>
#include <QJsonDocument>
#include <QJsonArray>
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
  const auto entryArgs = app.arguments();
  if ((entryArgs.size() == 1 && cli::interactiveConsole()) || entryArgs.value(1) == "menu")
    return cli::launchMenu(entryArgs.mid(2));
  QCoreApplication::setApplicationName("scantailor-cli");
  QCoreApplication::setOrganizationName("ScanTailorCLI");
  QCoreApplication::setApplicationVersion("3.4.0");
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
  parser.addPositionalArgument("command", "menu, process, analyze, preview, review, project create/inspect/apply/edit, pages list, config schema/export, geometry map, capabilities, doctor");
  const QStringList paths = {"input", "output", "project", "save-project", "config", "manifest", "save", "operations", "geometry", "analysis-cache"};
  for (const auto& name : paths) parser.addOption({name, name + " path", "path"});
  const QStringList strings = {"image-format", "tiff-compression", "preset", "deskew", "page-detection", "content-detection", "color-mode", "dewarp", "through", "stage", "source-pages", "pages", "review-policy"};
  for (const auto& name : strings) parser.addOption({name, name + " setting (see docs/CLI.md)", "value"});
  const QStringList numbers = {"png-compression", "jpeg-quality", "dpi", "output-dpi", "rotate", "deskew-angle", "margin-mm", "jobs", "max-angle", "min-page-ratio"};
  for (const auto& name : numbers) parser.addOption({name, name + " numeric value", "number"});
  const QStringList booleans = {"fill-margins", "fill-offcut"};
  for (const auto& name : booleans) parser.addOption({name, name + " true or false", "boolean"});
  parser.addOption({"resume", "Reuse verified completed outputs from this job."});
  parser.addOption({"overwrite", "Allow replacing outputs belonging to this job."});
  parser.addOption({"json", "Emit machine-readable data (default)."});
  parser.addOption({"dry-run", "Validate and show edits without saving."});
  parser.addOption({"html", "Write an HTML review report."});
  try {
    if (!parser.parse(app.arguments())) fail(parser.errorText());
    if (parser.isSet("help")) { std::fputs(parser.helpText().toUtf8().constData(), stdout); return 0; }
    if (parser.isSet("version")) { std::puts("scantailor-cli 3.4.0"); return 0; }
    const QString command = parser.positionalArguments().join(' ');
    if (QStringList{"config schema", "capabilities", "doctor"}.contains(command))
      for (const auto& key : parser.optionNames()) if (key != "json") fail("Option --" + key + " does not apply to " + command);
    if (command == "config schema") { cli::emitEvent(processing::schema()); return 0; }
    if (command == "capabilities") {
      cli::emitEvent({{"schema_version", 2}, {"commands", QJsonArray{"menu", "doctor", "capabilities", "config schema", "config export", "project create", "project inspect", "project apply", "project edit", "pages list", "geometry map", "analyze", "preview", "process", "review"}},
        {"stages", QJsonArray{"orientation", "split", "deskew", "content", "layout", "output"}}, {"configuration", processing::schema()}}); return 0;
    }
    if (command == "doctor") {
      QStringList formats;
      for (const auto& f : QImageReader::supportedImageFormats()) formats << QString::fromLatin1(f);
      cli::emitEvent({{"event", "doctor"}, {"cli_version", "3.4.0"}, {"qt_version", qVersion()},
                      {"platform", "offscreen"}, {"qt_image_formats", formats.join(",")},
                      {"core_image_formats", "png,jpeg,tiff"}, {"status", "ok"}});
      return 0;
    }
    const QStringList management{"project create", "project inspect", "project apply", "project edit", "pages list", "config export", "geometry map"};
    if (command != "process" && command != "analyze" && command != "preview" && command != "review" && !management.contains(command)) fail("Unknown command: " + command);
    QJsonObject options;
    QJsonObject configuration;
    if (parser.isSet("config")) {
      QFile file(parser.value("config"));
      if (!file.open(QIODevice::ReadOnly)) fail("Cannot read configuration.");
      QJsonParseError error;
      const auto doc = QJsonDocument::fromJson(file.readAll(), &error);
      if (error.error != QJsonParseError::NoError || !doc.isObject()) fail("Configuration must be a JSON object.");
      if (doc.object().value("schema_version") == 2) {
        configuration = doc.object(); processing::validateConfiguration(configuration);
      } else {
        options = doc.object();
        if (options.take("schema_version") != 1) fail("Configuration schema_version must be 1 or 2.");
      }
    }
    const QStringList encodingFlags{"image-format", "png-compression", "tiff-compression", "jpeg-quality"};
    auto configuredEncoding = configuration.value("image_encoding").toObject();
    // Schema 1 configuration and explicit flags must remain distinct so a
    // format override drops only inherited (not explicit) codec parameters.
    for (const auto& key : encodingFlags) if (options.contains(key))
      configuredEncoding[key == "image-format" ? "format" : QString(key).replace('-', '_')] = options.take(key);
    ImageEncoding::fromJson(configuredEncoding);
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
    for (const auto& key : QStringList{"resume", "overwrite", "dry-run", "html"}) if (parser.isSet(key)) options[key] = true;
    for (const auto& key : booleans + QStringList{"resume", "overwrite"})
      if (options.contains(key) && !options[key].isBool()) fail("Expected a boolean: " + key);
    for (const auto& key : paths + strings)
      if (options.contains(key) && !options[key].isString()) fail("Expected a string: " + key);
    auto onlyFor = [&](const QString& key, const QStringList& commands) {
      if (options.contains(key) && !commands.contains(command)) fail("Option --" + key + " does not apply to " + command);
    };
    onlyFor("operations", {"project edit"}); onlyFor("geometry", {"geometry map"});
    onlyFor("stage", {"preview"}); onlyFor("through", {"process", "analyze"});
    onlyFor("dry-run", {"project create", "project apply", "project edit"});
    onlyFor("resume", {"process", "analyze", "preview"}); onlyFor("pages", {"process", "analyze", "preview"});
    onlyFor("analysis-cache", {"process", "analyze", "preview"}); onlyFor("source-pages", {"preview"}); onlyFor("html", {"process", "analyze", "preview", "review"}); onlyFor("jobs", {"process", "analyze", "preview"});
    for (const auto& key : {"max-angle", "min-page-ratio", "review-policy"}) onlyFor(key, {"process", "analyze", "preview"});
    onlyFor("save", management);
    if (command == "review") for (const auto& key : options.keys()) if (key != "output" && key != "html") fail("Option --" + key + " does not apply to review");
    if (command == "review" && parser.isSet("config")) fail("review does not accept --config");
    if (command == "project edit" && !options.contains("operations")) fail("project edit requires --operations");
    if (command == "geometry map" && !options.contains("geometry")) fail("geometry map requires --geometry");
    if (options.contains("save") && options.contains("save-project")) fail("Specify only one save destination");
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
    choice("through", {"orientation", "split", "deskew", "content", "layout", "output"});
    choice("stage", {"orientation", "split", "deskew", "content", "layout", "output"});
    choice("review-policy", {"preserve", "report"});
    for (const auto& key : encodingFlags) onlyFor(key, {"process", "analyze", "preview"});
    if (command == "process" || command == "analyze" || command == "preview") {
      auto encoding = configuredEncoding;
      if (options.contains("image-format") && options["image-format"] != encoding.value("format").toString("png")) encoding = {};
      for (const auto& key : encodingFlags) if (options.contains(key)) encoding[key == "image-format" ? "format" : QString(key).replace('-', '_')] = options.take(key);
      options["image_encoding"] = ImageEncoding::fromJson(encoding).json();
    }
    options["command"] = command;
    if (parser.isSet("config")) options["_config_path"] = cli::absolutePath(parser.value("config"));
    if (!configuration.isEmpty()) options["configuration"] = configuration;
    if (command != "review") {
      int inputs = 0; for (const auto& key : {"input", "project", "manifest"}) if (!options.value(key).toString().isEmpty()) ++inputs;
      if (inputs != 1) fail("Specify exactly one of --input, --manifest or --project.");
      if (management.contains(command) && command != "project create" && !options.contains("project")) fail("This command requires --project.");
    }
    if (!management.contains(command) && options.value("output").toString().isEmpty()) fail("--output is required.");
    auto scheme = ColorSchemeFactory().create("light");
    ColorSchemeManager::instance().setColorScheme(*scheme);
    IconProvider::getInstance().setIconPack(StyledIconPack::createDefault());
    if (management.contains(command)) return cli::projectCommand(command, options);
    return cli::run(options);
  } catch (const std::invalid_argument& error) {
    cli::emitEvent({{"event", "error"}, {"message", QString::fromUtf8(error.what())}, {"exit_code", 2}});
    return 2;
  } catch (const std::exception& error) {
    cli::emitEvent({{"event", "error"}, {"message", QString::fromUtf8(error.what())}, {"exit_code", 3}});
    return 3;
  }
}
