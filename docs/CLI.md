# ScanTailor CLI 与 PDF 文件夹处理

此 fork 增加 `scantailor-cli.exe`。GUI 仍为 `scantailor-advanced.exe`。
CLI 复用 GUI 的六阶段图像处理任务，不执行 OCR、不调用云端模型。

## PDF：推荐入口

在便携包目录打开 PowerShell 7：

```powershell
.\Process-PdfFolder.ps1 -PdfDir 'C:\Users\medic\Downloads\pdf' -ScanTailorDir $PWD.Path
```

也可直接运行脚本，再输入 PDF 文件夹和工具文件夹。默认逐本处理直属 PDF，
结果放在 PDF 文件夹下的 `scantailor-output`。原始 PDF 不覆盖。

```powershell
# 中断后继续，或复用已经验证的结果
.\Process-PdfFolder.ps1 -PdfDir 'D:\书籍' -ScanTailorDir $PWD.Path -Resume

# 配置、输出目录、并发和渲染分辨率
.\Process-PdfFolder.ps1 -PdfDir 'D:\书籍' -ScanTailorDir $PWD.Path -OutputDir 'D:\整理结果' -Dpi 300 -Jobs 2 -Config '.\physics-safe.json'
```

参数：`-Recursive` 递归子目录；`-Overwrite` 显式重新生成已有目标；`-PythonExe` 指定外部 Python。
便携包自带 Python 时不需要安装 Python。源码运行需先在自己的 Python 环境安装
`scripts/requirements-pdf.txt` 中的精确版本。运行与构建不会自动联网安装依赖。

PDF 入口目前统一渲染为 RGB PNG，再处理。默认 300 DPI，可用 `-Dpi` 调整；
它没有自动判断扫描原始 DPI，也不承诺无损提取 PDF 内部扫描图。
打印页面尺寸保持原 PDF 的可见页面尺寸。处理图等比例适配该尺寸，必要时增加白边，
不拉伸、不裁掉适配后的图像。被标记为异常的页面保留原 PDF 页。
页数、顺序、尺寸和可渲染性在最终文件发布前逐页验证。
保留描述性元数据与简单目录；正常处理页会变成图像页，原有文字层、链接、表单等交互对象不保留。
因此本流程针对扫描书，不适用于需要保留交互对象的电子原版 PDF。

输出内容：

- `书名.deskew.pdf`：处理结果。
- `batch-report.json`：每本书的结果、失败原因和复核入口。
- `.work/<书籍ID>/<处理版本>/processed/report.json`：逐页状态与算法指标。
- `.work/<书籍ID>/<处理版本>/review/index.html`：被标记页面的前后对照。
- `.work/…/processed/project.scan`：可用 GUI 打开的项目。
- `.work/…/events.jsonl`：CLI 进度记录。

中间文件用于恢复和复核，会占用额外磁盘空间，程序不自动删除它们。
输出目录使用系统文件锁，进程异常退出后自动释放。

## 图片目录和现有项目

```powershell
.\scantailor-cli.exe --help
.\scantailor-cli.exe doctor
.\scantailor-cli.exe process --input 'D:\扫描图片' --output 'D:\处理结果' --preset physics-safe --dpi 300
.\scantailor-cli.exe process --project 'D:\物理书.scan' --output 'D:\项目输出'
.\scantailor-cli.exe process --input 'D:\扫描图片' --output 'D:\处理结果' --dpi 300 --resume
```

`--input` 与 `--project` 二选一，`--output` 必填。输入目录读取 PNG/TIFF/JPEG/BMP，
支持多页 TIFF，默认自然排序且不递归。新图片项目按单页处理；已有项目沿用其分页。
输出目录必须专用，首次运行须为空。已有任务使用 `--resume` 或 `--overwrite`。
GUI-only 的旧版安装目录不能替代 CLI 便携包。

每次处理都会保存项目，默认 `<output>/project.scan`。使用 `--save-project` 指定其他路径。
不会覆盖输入项目。单页手动修正可在 GUI 修改并保存项目后，再用 `--project` 处理；
不要同时打开同一输出目录中的项目进行 GUI 编辑和 CLI 处理。

## 设置与优先级

新图片项目默认采用 `physics-safe`。加载已有项目时保留已有处理设置，
只有明确提供的设置才覆盖；显式指定 `--preset physics-safe` 会重设该预设覆盖的基础设置。
优先级：显式命令行 > JSON 配置 > 已有项目设置／新项目默认设置。
CLI 使用独立临时设置，不读取或修改 GUI 用户偏好。

| 参数 | 可用值／默认 |
|---|---|
| `--config` | JSON 文件，必须有 `schema_version: 1`，未知字段报错 |
| `--preset` | `physics-safe` |
| `--dpi` | 72–1200 整数；覆盖输入 DPI。未提供时图片必须有有效 DPI |
| `--output-dpi` | 72–1200；新项目默认跟随每页输入 DPI |
| `--rotate` | 0、90、180、270；顺时针整页方向 |
| `--deskew` | `auto`、`off`、`manual`；默认 auto |
| `--deskew-angle` | -45 到 45 度，隐含 manual；沿用 ScanTailor 角度约定 |
| `--page-detection` | `auto`、`off`；预设 auto |
| `--content-detection` | `auto`、`off`；预设 off，避免紧贴正文裁边 |
| `--margin-mm` | 0–100 毫米；预设 0，四边相同，取消跨页尺寸匹配 |
| `--color-mode` | `color-grayscale`、`black-white`、`mixed`；预设 color-grayscale |
| `--dewarp` | `off`、`auto`；预设 off |
| `--fill-margins` | `true`、`false`；预设 true，白色填充 |
| `--fill-offcut` | `true`、`false`；预设 true，包含纸张框外区域 |
| `--max-angle` | 自动复核阈值，默认 8 度 |
| `--min-page-ratio` | 页面框／旋转后整页包围框的面积阈值，默认 0.8 |
| `--jobs` | 1–16，默认 1；高分辨率页面建议从 1–2 开始 |
| `--resume` | 校验后复用已完成输出；仍执行分析以建立完整布局 |
| `--overwrite` | 重算此专用输出目录内的任务结果 |

配置使用同名字段，数字和布尔值须用 JSON 对应类型。
路径相对调用者的当前目录解释。
PDF 包装脚本的配置只接受图像处理参数，不允许覆盖任务路径、DPI、并发或恢复控制。

## 保真策略和复核

`physics-safe` 关闭二值化、去斑点、亮度归一化、Wiener 滤波、色阶简化、自动斜切和曲面展平。
保留灰度和颜色，使用现有页面检测来去除纸张之外的扫描背景。

以下情况进入复核：纠偏置信度低于算法阈值、角度超过 `max-angle`、
检测页面面积低于 `min-page-ratio`。单页图片回退为原图；PDF 包装层保留原 PDF 页。
疑难拆分页不直接复制整张扫描图，避免重复左右两页，会报告错误供 GUI 复核。

这些规则是异常筛查，不能证明每个公式、细线或贴边文字完整。
轻微倾斜、纸张边界不清、黑边与正文相连、严重书脊弯曲仍需检查。
空白页可能被低置信度规则标记，但不会删除。

## 程序调用契约

stdout 为 UTF-8 JSONL，stderr 为诊断信息。事件包括 `page_started`、`page_finished`、
`review_required`、`page_reused`、`invalidated`、`finished`、`error`。
逐页报告包含输入、输出、状态、输出 SHA-256、角度／置信度／面积比例（如算法提供）。

| 退出码 | 含义 |
|---|---|
| 0 | 全部完成，无自动标记 |
| 1 | 有复核页或部分失败；应读取报告 |
| 2 | 命令或配置格式错误 |
| 3 | 运行／输入输出／环境错误 |
| 130 | 用户取消 |

Ctrl+C／Ctrl+Break 会请求取消并等待当前原生任务退出，在可保存时写入检查点。
强制结束进程后，使用 `--resume`／`-Resume` 恢复。
恢复检查源文件 SHA-256、有效配置和可执行文件 SHA-256。
原生输出逐个检查 SHA-256；内容／配置变化时重算整批布局，避免跨页尺寸依赖留下旧结果。
PDF 层还检查包装脚本、PyMuPDF 版本、渲染分辨率和最终 PDF 的 SHA-256。
中间图片损坏时重建该图片；成功结果只有通过校验才复用。

## Windows 原生构建

经过验证的依赖组合记录在任务状态／验证报告中。推荐 Qt 6.8.3 配套 MinGW 13.1，
不要混用 Strawberry 的 UCRT 编译器和 Qt 的 MSVCRT 预编译 C++ 运行库。
Strawberry 的图像 C 库作为独立 DLL 使用；打包时递归收集其依赖。
Boost 1.85.0 头文件足够用于应用构建；原有 C++ 单元测试另需 Boost.Test 静态库。

```powershell
.\scripts\Build-Windows.ps1 -QtRoot 'D:\依赖\Qt\6.8.3\mingw_64' -BoostRoot 'D:\依赖\boost_1_85_0' -CompilerRoot 'D:\依赖\Qt\Tools\mingw1310_64' -NativeRoot 'C:\Strawberry\c' -BuildDir '.\build-native'
```

`Build-Windows.ps1` 不下载依赖，关闭本机 CPU 专属优化以便分发，构建 GUI 与 CLI。
`scripts/boost-test/CMakeLists.txt` 可直接从已解压的 Boost 源码构建测试库，无需 batch/Bash。

```powershell
python .\tests\cli_integration.py --cli .\build-native\scantailor-cli.exe -v
```

`Package-Windows.ps1` 接受 Qt、编译器、C 图像库目录和构建目录，输出到新的便携包目录。
可额外传入 Python 3.12.10 嵌入版 ZIP 与已安装依赖的 site-packages 目录，生成自带 Python 的包。
它检查所有 PE 导入依赖，再用仅含 Windows 系统目录的 PATH 运行 doctor。

## 开发关系

- `src/core/CompositeTaskFactory.*`：从原 `MainWindow::createCompositeTask` 抽出的公共任务链；GUI 方法委托给它。
- `src/cli/BatchRunner.cpp`：项目初始化、参数覆盖、阶段调度、并发、锁、指纹、报告。
- `src/cli/main.cpp`：控制台协议、参数验证、独立 Qt 设置和取消信号。
- `TaskStatus::reportMetric` → `BackgroundTask::metrics`：处理线程记录指标，主线程在任务结束后读取。
- `FilterResult::errorString`：无界面读取错误；`LoadFileTask` 和输出任务提供具体错误，原 GUI 更新方法保留。
- Filter 的 `processingSettings()`：仅在任务停止的阶段边界修改，不允许与处理线程同时变更。
- `scripts/process_pdf_folder.py`：按原页序组装；疑难页插回原 PDF 页；最终校验后使用文件替换发布结果。

GUI 项目 XML 格式保持原样。CLI 自己的 `state.json`、`report.json` 和 JSONL 为版本 1。
