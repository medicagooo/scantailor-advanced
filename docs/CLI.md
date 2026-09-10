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
默认单页打印尺寸保持原 PDF 的可见页面尺寸；双页和 processed 尺寸模式见下文。处理图等比例适配该尺寸，必要时增加白边，
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

`--input`、`--manifest` 与 `--project` 三选一，`--output` 必填。输入目录读取 PNG/TIFF/JPEG/BMP，
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
| `--config` | JSON 文件，必须有 `schema_version: 1` 或 `2`，未知字段报错 |
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

GUI 项目 XML 保持旧版兼容读取，并扩展可选元数据。CLI 2 的配置、检查和中间阶段报告使用 schema 2；state 和最终处理报告兼容 schema 1。

## CLI 2：完整项目工作流

CLI 2.0 保留上面的 v1 标量选项，新增 schema_version=2 配置。以下命令输出 UTF-8 JSON：

```powershell
.\scantailor-cli.exe capabilities --json
.\scantailor-cli.exe config schema > schema.json
.\scantailor-cli.exe project create --manifest inputs.json --save book.scan
.\scantailor-cli.exe project inspect --project book.scan
.\scantailor-cli.exe pages list --project book.scan
.\scantailor-cli.exe project apply --project book.scan --config settings.json --save edited.scan --dry-run
.\scantailor-cli.exe project apply --project book.scan --config settings.json --save edited.scan
.\scantailor-cli.exe config export --project edited.scan --save effective.json
.\scantailor-cli.exe analyze --project edited.scan --through content --output analysis
.\scantailor-cli.exe preview --project analysis/project.scan --pages 1-4 --stage layout --output preview
.\scantailor-cli.exe process --project edited.scan --pages odd --output out --html
.\scantailor-cli.exe review --output out --html
```

`analyze`、`preview`、`process` 均需专用 `--output`；六阶段顺序是 `orientation / split / deskew / content / layout / output`。
`analyze` 默认止于 layout，`preview` 默认 output；process 也可用 `--through` 停在中间阶段。
选页使用从 1 开始的当前逻辑页序号、`1-3,7`、`odd`、`even`、`all` 或稳定 ID，可用逗号合并。
为保证尺寸匹配正确，分析仍覆盖整本；仅生成所选页面的最终输出／阶段预览。
未选输出标为 `not_selected`。阶段报告使用 schema 2；最终处理报告保留 schema 1 并增加字段。

### 清单、身份与项目编辑

输入清单 schema 1 示例：`{"schema_version":1,"files":["pages/001.png",{"path":"pages/002.png","stable_id":"source-002"}]}`。
清单相对路径以清单目录为基准；其他命令／配置中的路径以当前工作目录为基准。
`--input / --manifest / --project` 三选一。清单保持给定文件顺序，多页 TIFF 展开成内部页。

每个源图片内部页有 `image_id`，逻辑页 ID 是 `<image_id>:single / :left / :right`。
未提供稳定 ID 时由初始绝对源路径及 TIFF 内部页号计算；存入 `.scan` 后重新关联或排序不变。
显式 manifest ID 在多页 TIFF 上附加内部页号。单页文件的 `image_page=0`，多页 TIFF 从 1 开始。
JSON 导出的稳定 ID 只适用于同一组源图；不要用当前页码代替长期身份。

```powershell
.\scantailor-cli.exe project edit --project book.scan --operations edits.json --save edited.scan
```

`edits.json` 使用 `{"schema_version":1,"operations":[...]}`，按数组顺序在内存中执行，全部成功后才保存：

| type | 字段及语义 |
|---|---|
| insert | `files` 路径数组，选填 `before_image` 或 `after_image` 稳定源 ID、`dpi`；不指定锚点则末尾插入 |
| remove | `ids` 逻辑 ID 数组；仅从项目移除，不删除源文件；不能移除全部页面 |
| restore-half | `image_id`、`side:left/right`；恢复拆分后被隐藏的半页。已保存删除状态的项目不保证保留被移除页的旧设置，应重新应用所需配置 |
| reorder | `image_ids` 必须恰好列出全部源 ID 各一次；源图内部左右顺序由 reading_direction 控制 |
| relink | `from`、`to` 完整源文件路径；目标必须可读、保持内部页身份和图像尺寸，不允许合并两个源 |

`project create/apply/edit` 需要 `--save`，支持 `--dry-run`。覆盖已有项目需 `--overwrite`；保存使用锁、临时文件替换，并检测同名输入项目是否被并发修改。
源图片、清单、配置和编辑指令文件受覆盖保护。导出 JSON 不能覆盖输入项目。
未知字段、无匹配规则、错误类型、越界值和不适用当前命令的选项会报错。

### 配置层级与全部设置

schema 2 示例：

```json
{
  "schema_version": 2,
  "project": {"reading_direction": "ltr", "deskew_algorithm": "content"},
  "defaults": {
    "input": {"dpi": [300, 300]},
    "split": {"layout": "two"},
    "deskew": {"mode": "off", "oblique_mode": "off"},
    "content": {"page_mode": "off", "content_mode": "off"},
    "layout": {"margins_mm": {"left": 5, "right": 5}, "match_size": true},
    "output": {"mode": "mixed", "dpi": [300, 300], "threshold_method": "wolf"}
  },
  "rules": [
    {"select": {"images": [1]}, "settings": {"orientation": {"rotation": 90}}},
    {"select": {"parity": "even"}, "settings": {"layout": {"horizontal": "right"}}}
  ]
}
```

生效顺序：已有项目／新项目默认 → 显式 physics-safe 预设 → defaults → rules 按顺序递归覆盖 → v1／命令行标量覆盖。
数组整体替换，空 zones 数组清空区域。规则的不同选择字段取交集；同一字段的数组取并集。
选择支持 `pages`、`images`（当前序号）、`ids`、`image_ids`、`parity`、`side`。
`input / orientation / split` 属于源级，只允许 `images / image_ids`，避免对一半旋转却暗中改变另一半。
逻辑页级规则在拆页完成后解析。自动拆页尚未分析时，应先 analyze 再使用左右页 ID。
`project inspect` 和 `analysis.json` 提供最终 settings、配置覆盖来源 overrides，以及 setting_sources；重新打开项目时来源为 project，历史命令行来源不写入 GUI 设置。

完整字段、类型和数值范围以 `config schema` 为准；字段清单和 GUI 对应关系见 `CLI-COVERAGE.md`。
output.mode 的 v2 名称是 `bw / colorOrGray / mixed`。`split_output=true` 要求 mixed；手动 dewarp 要求有效曲线。
`project.freeze_layout=true` 可提供 `frozen_size_mm:[宽,高]`；否则必须已完成 layout 且有非零匹配尺寸。仅运行到早期阶段时不会新冻结尚未计算的尺寸。
`project.guides` 的位置遵循 GUI 布局辅助线坐标，影响辅助显示，不绘入 TIFF。

### 手动几何、区域和转换

所有点／矩形单位是相应空间中的像素，矩形写成 `[x,y,width,height]`；边距和冻结尺寸单位是毫米。

- `orientation.trim`：enabled 和源图四边整数像素 left/top/right/bottom，裁后至少保留 32×32。
- `split`：`space:"oriented"`，`layout:"two"` 时 cutters 为一条线的两个端点；`layout:"cut"` 时两条线；mode 为 manual。空间已包含方向和初裁切。
- `content`：`space:"deskew"`，可给 page_rect 和 content_rect；均为纠偏／斜切后的逻辑页坐标。分析输出 `_geometry` 提供 bounds、outline、source_to_stage 和 basis。
- 修改手动矩形时带上该页分析所得 basis；前置几何已变时会拒绝旧 basis。省略 basis 意味着调用者负责提供当前坐标。修改已保存项目的前置几何而继续沿用其手动框时，CLI 会拒绝保存／进入正文处理，要求重新分析并显式提供新框。仅分析到 deskew 可取得新坐标；随后必须确认并更新手动框。
- `picture_zones`：对象数组，space=source，points 为多边形，layer 为 noop/erase-auto/picture/erase-all/foreground/background，category 可为 manual/auto。
- `fill_zones`：space=source、points 多边形、color 为 #RRGGBB。
- `output.distortion_model`：space=source；top 和 bottom 是折线；或分别改用 top_spline / bottom_spline 控制点数组，每项为 `{"point":[x,y],"tension":-0.5}`。每条边二选一，张力范围 [-1,1]；曲线不得回环，边界端点须构成有效四边形。

```powershell
.\scantailor-cli.exe geometry map --project out/project.scan --geometry points.json --save mapped.json
```

points.json 示例：`{"schema_version":1,"id":"源ID:left","from":"source","to":"output","points":[[100,200],[300,400]]}`。
支持 source、oriented、split、deskew、content、layout、output 间双向转换。layout/output 要先完成布局；自动展平要先生成输出以确定模型。
转换复用 GUI 填色区域编辑器的非线性映射和展平后旋转。输出预览报告提供 output_to_preview；阶段预览提供 source_to_preview。
变换返回坐标，不把曲线边界间的任意矩形假装成另一空间的轴对齐矩形；跨非线性空间转换区域时应采样边界点。

### 复核、恢复和 PDF 拆页

`--review-policy preserve` 为默认策略：疑难单页保留原图，疑难拆分页标错，由 PDF 层保留原 PDF 页一次。
`--review-policy report` 仍生成处理结果并标记 review，便于检查。显式手动纠偏／框不按自动角度／裁边阈值误报。
`preview / --html` 生成源图与结果 PNG、review.html；layout 预览在整书尺寸确定后生成，split 预览逐半页生成。
复核后使用 stable ID 编写规则，通过 project apply 保存修订，再 process 重跑。旧结果可保留在另一个输出目录。

分层输出的主 TIFF、foreground、background、可选 originalBackground 均列入 artifacts 并校验可读性和 SHA-256。
输出预览也计入逐页 artifacts。恢复总是重新建立分析、项目和报告；只有哈希匹配的最终图层可复用。
如果输入、配置、可执行文件改变，重算全书布局。被移除页面的尺寸不会继续参与匹配；处理失败的源仍保留在项目中。

PDF 现在支持一张源页变为两张逻辑页，保持 CLI 的左右阅读顺序。`batch-report.json` 记录 source_page、logical_id、subpage。
目录指向原源页的第一个结果页；任一半失败或被标记时，整张原 PDF 页只插入一次，不重复源页。
`-PageSize original`（默认）保留单页原可见尺寸，双页各占已旋转源页宽度的一半；适配图像时保持比例。
`-PageSize processed` 根据 TIFF 像素／输出 DPI 使用处理后的物理尺寸；回退页仍保留原 PDF 尺寸。
PDF 渲染输入通过内容哈希生成稳定 ID，不依赖临时处理版本目录；修改配置后可继续定位同一源页。

### 与 GUI 的关系

共享 CompositeTaskFactory、各阶段 Settings/Params、ProjectReader/Writer、布局几何函数和展平映射。
CLI 的 ProcessingConfiguration 是类型校验和设置适配层；GUI 继续使用原编辑控件，调用同一底层设置和处理链。
新增 `.scan` 可选属性 stableId、frozenWidthMM/frozenHeightMM、曲线 point tension；旧项目缺少时按原默认读取。
本版本 GUI 能保留这些字段。更早 GUI 可以读取项目，但再保存时可能丢失新元数据或自定义张力；应使用同包 GUI 往返编辑。
自动检测仍可能需要人工复核，CLI 不承诺自动识别每个公式、细线或书脊边界。
