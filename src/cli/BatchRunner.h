// Copyright (C) 2026. Distributed under the GNU GPLv3 license.
#pragma once
#include <QJsonObject>
#include <atomic>

namespace cli {
extern std::atomic<bool> cancelled;
void emitEvent(const QJsonObject& event);
// Options are validated by main. The runner owns a directory lock and writes
// checkpoints using QSaveFile. A result is reusable only with matching hashes.
int run(const QJsonObject& options);
}
