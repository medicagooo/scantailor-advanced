# macOS GUI、CLI 与 PDF 批处理

macOS 第一阶段支持 GUI 和普通 CLI；`menu` 交互工作台仍仅支持 Windows。
版本号与其他平台统一，来自 `version.h.in`。当前 macOS 包以 macOS 15 为最低目标；
ARM64 和 Intel x64 分别原生构建，不是 Universal 包。更低系统版本未经支持验证。

## 下载与运行

选择与电脑架构一致的 `macos-arm64` 或 `macos-x64` ZIP/DMG。
将 `ScanTailor Advanced.app` 复制到 Applications。CLI 与图像库一起位于应用内部：

```text
/Applications/ScanTailor Advanced.app/Contents/MacOS/scantailor-cli
```

终端调用时给包含空格的路径加引号，并附加 `--help`、`--version`、`doctor` 或
`process` 等命令。GUI 可从 Finder 打开。CLI 不需要 Python，仍需要随应用分发的
Qt/图像动态库，因此不要单独拷走 CLI 文件。

包使用临时（ad-hoc）代码签名，不包含 Apple Developer ID 签名或公证。
macOS 可能阻止下载应用直接打开；正式公开分发前应接入 Developer ID 签名和公证。
本流程不关闭或绕过 Gatekeeper。GitHub 构建成功不等同于已通过公证。

## PDF 批处理

PDF 包装脚本包含在应用的 `Contents/MacOS/process_pdf_folder.py` 中。
第一阶段不内嵌 Python。安装 Python 3.12，创建独立虚拟环境，然后用该环境的
Python 运行下列命令（路径包含空格时保留引号）：

```text
python3 -m venv ~/scantailor-python
~/scantailor-python/bin/python -m pip install -r "/Applications/ScanTailor Advanced.app/Contents/MacOS/requirements-pdf.txt"
~/scantailor-python/bin/python "/Applications/ScanTailor Advanced.app/Contents/MacOS/process_pdf_folder.py" --help
```

执行批处理时，使用脚本的 `--cli` 参数指定应用内的 CLI 路径。
PyMuPDF/Pillow 版本固定在同目录的 requirements 文件；依赖仅安装在用户虚拟环境，
不要往签名后的应用包内安装或修改文件。

## 构建与验证边界

CI 使用 GitHub `macos-15`（ARM64）和 `macos-15-intel`（x64），Qt 官方预编译 Qt 6.8.3、
Apple Clang；CMake/Ninja、Boost 和图像库由 Homebrew 提供。Homebrew 包随源更新；最低系统兼容性还
受依赖自身目标版本限制，实际二进制需在对应系统验证。

CI 执行 C++、CLI/PDF/图像编码测试及 GUI 项目 roundtrip，然后部署临时 app 做
动态库审计、CLI 启动和部署后 CLI/PDF/图像编码测试，不生成发布压缩包或上传资产。
Release 仅手动触发，`macos-arm64` / `macos-x64` 可单选，`all` 包含两个 macOS 架构。
发布时 `macdeployqt` 部署 Qt，`relocate_macos.py` 递归复制非系统 dylib、重写引用，
检查架构及依赖是否留在应用内，再签名、检查 CLI 启动与实际图片处理，生成 ZIP/DMG 和校验文件。

原生 macOS 编译、签名、打包只能在 macOS 上验证。Windows 本地的契约测试和代码
审查不能替代真实 runner 的结果；首次成功运行前视为待验证支持。
