# CI 与手动 Release

仓库只有 `.github/workflows/ci.yml` 和 `release.yml` 两个工作流。
原 CMake、Lint 的检查职责合入 CI；独立 Flatpak 工作流删除，保留 Flatpak
源码配置供自行构建。CI 和 Release 均使用 GitHub 官方构建机。

## CI：检查，不发布

推送 `master/main` 或向它们提交 PR 时运行：

- 分支登记校验、Python 与 PowerShell 语法检查、离线发布流程测试。
- 使用 clang-format 18 检查本次变更的 C++ 文件，排除已删除文件。
- Windows x64 和 Linux x64 编译 GUI、CLI，运行 C++ 测试和 CLI/PDF 集成测试。
  Windows 额外运行工作台、恢复、完成界面和语言测试。任何测试失败会使 CI 失败。

CI 不制作发布包、不创建 Release、不上传 Actions artifacts。
GUI 专用 roundtrip harness 未单独构建，对应集成测试可能跳过；这不是完整 GUI 自动化验收。

## Release：手动选平台、编译并发布

将本次配置推送到默认分支 `master` 后，在 **Actions → Release → Run workflow** 填写：

| 参数 | 含义 |
| --- | --- |
| `tag` | 可选。填写时使用已有远端标签；留空则读取所选运行代码的 `version.h.in` 中 `VERSION`，自动使用 `v版本号`。 |
| `platform` | `windows`、`linux` 或 `all`（默认）。 |
| `draft` | 默认勾选，完成后保留草稿；取消则在所有所选平台成功后公开发布。 |

推送分支或标签不会自动触发 Release。留空时，若版本标签不存在，Prepare 会在本次运行的确定 commit 上创建标签；若已存在，必须指向同一 commit，否则要求升级版本号或显式指定已有标签。不会移动或覆盖已有标签。
Release 负责编译、打包、基础运行环境校验与发布，不重复运行 CI 回归测试；
选择的标签应指向已经通过 CI 的代码。

| 平台 | GitHub 构建机 | Release 附件 |
| --- | --- | --- |
| Windows x64 | `windows-2022` | `ScanTailor-<tag>-windows-x64.zip`、`SHA256SUMS-windows.txt` |
| Linux x64 | `ubuntu-24.04` | `ScanTailor-<tag>-linux-x64.deb`、`ScanTailor-<tag>-linux-x64.AppImage`、`SHA256SUMS-linux.txt` |

Windows ZIP 包含 GUI、CLI、DLL、脚本、三语言工作台资源、Python 3.12.10 和
`scripts/requirements-pdf.txt` 锁定的 PyMuPDF/Pillow。完整解压后使用。
Linux 包含原生 GUI/CLI 和安装规则中的脚本；PDF 包装层需要另行安装上述 Python
依赖，Windows 终端工作台不作为 Linux 功能承诺。本流程不提供 macOS、ARM、RPM、Flatpak 发行包。

## 构建与发布契约

`.github/actions/native-build/action.yml` 是复用的本地 composite action，不是第三个工作流。
它安装依赖并调用 `scripts/Build-Actions.ps1`：CI 开启测试，Release 关闭测试。
Windows 使用同一 MSYS2 MINGW64 包源的 Qt5、GCC、Boost 和图像库，复用
`Build-Windows.ps1`；Linux 使用 Ubuntu 24.04 的开发包。系统库随包源更新，
不承诺位级可重现构建。Python 固定为 3.12.10，Python 库按 requirements 固定。

`Release-Actions.ps1` 的 Prepare 解析可选标签（GUI、CLI 和默认发布版本统一来自 `version.h.in` 的 `VERSION`，当前沿用 CLI 版本 `3.4.0`），输出确定的 tag、commit SHA 和平台矩阵。打包、上传和完成步骤统一使用这些输出。
各平台只构建该 SHA。`Package-Actions.ps1` 调用 Windows 打包器，或 Linux CPack/
linuxdeploy；生成包及 SHA256 文件。标签版本写入构建副本的统一版本模板，GUI、CLI
和包元数据同步使用该版本，不提交版本变更回仓库。后续升级只需修改 `version.h.in` 的 `VERSION`。

附件直接上传 GitHub Release，**不使用 Actions artifact 上传或中转**。
Prepare 先创建草稿，平台任务向草稿上传各自附件；Finalize 仅在全部所选任务成功、
标签 SHA 未变化且预期附件完整时决定保留草稿或公开发布。

## 失败与重试

多平台上传可能部分成功。任一编译、打包、上传失败时不公开发布，保留草稿和已经
上传的附件，不自动删除。重新手动运行相同标签可恢复；只允许继续带有相同源 SHA
记录的草稿，同名附件会被本次所选平台覆盖，其他平台附件保留。
若第一次选 `all` 后某平台失败，仍建议选 `all` 重试，以对两个平台完成统一验收。
已有公开 Release 禁止由本工作流修改；标签移动也会阻止继续发布。

Release 使用仓库级 concurrency 串行执行，避免留空与显式标签并发发布同一版本。取消运行也可能留下草稿和部分附件。
`draft=true` 并不表示本次构建已经完整成功，仍需查看 Actions 的最终结果。

本地校验包括 actionlint、PowerShell 解析和离线发布契约测试；GitHub 构建机的真实
安装、编译、测试和打包结果须以实际运行记录为准。

参考：[GitHub 手动运行工作流](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow)、
[MSYS2 setup action](https://github.com/msys2/setup-msys2)、
[GitHub CLI Release](https://cli.github.com/manual/gh_release_create)。
