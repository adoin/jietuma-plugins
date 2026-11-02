# 截图妈插件

这里开发和打包截图妈的独立扩展。所有插件使用统一的程序级扩展协议 v2；旧协议包不能安装到此版本的截图妈。

在 Windows 安装 Rust MSVC 工具链与 Python 3 后运行：

```powershell
python scripts/package.py
```

生成的 `.jtbplugin` 文件位于 `dist/`。在截图妈系统托盘右键菜单或剪贴板窗口的设置菜单选择“安装插件”。插件以当前用户权限运行，只应安装信任的来源。

每个插件的版本独立维护，以其 `plugins/<id>/plugin.json` 的 `version` 为准；`Cargo.toml` 是共享构建工具的版本，不要求与插件一致。单独发布时只修改目标插件版本，提交后推送 `<插件ID>/v<版本>` 标签，例如 `code-highlight/v1.0.1`，工作流只打包并发布该插件。需要一次发布全部插件时使用 `v<批次版本>` 标签，各插件保留自己的版本。预发布使用版本后缀，如 `code-highlight/v1.1.0-beta.1`。分支推送和 Pull Request 只运行检查，不发布。

可以用 `python scripts/package.py --plugin code-highlight` 只构建一个插件；不传参数构建全部插件。

## 能力和串联

统一清单使用 `api_version: 2`、`type: "extension"` 和 `contributes` 声明命令、事件钩子、工具栏栏位及剪贴板能力。一个插件可以组合多种能力。`pipeline` 按顺序调用不同插件的命令，上一命令的图片或文本输出成为下一命令的输入。

截图事件包括 `screenshot.started`、`screenshot.selection_confirmed`、`screenshot.before_export`、`screenshot.exported`、`screenshot.cancelled` 和 `screenshot.ended`。剪贴板采集过滤器声明 `clipboard.before_capture`；预览、动作、条目元数据和备份分别在 `contributes.clipboard` 下声明。完整的清单格式、数据类型、生命周期边界和大小限制见截图妈主项目的 `docs/plugins.md`。

## 已实现的插件

- JSON、Markdown、RTF 预览和原始格式检查。
- JSON 格式化及可配置 Rhai 文本脚本。
- 敏感内容过滤和指定应用排除。
- 条目备注与标签。
- 剪贴板加密备份与恢复，使用 age 密码加密。

采集过滤是启发式保护，可能漏掉秘密或跳过相似的示例文本。来源应用排除依赖系统能识别来源进程。加密备份密码不会保存，丢失后无法恢复备份。

## 电子表格和代码高亮

需要截图妈 2.2.5 或更新版本提供的插件类型、选择字段和多格式粘贴接口，旧版宿主不能安装这两个新包。

- `spreadsheet`：识别已存储的 XML Spreadsheet、HTML 表格或 TSV，网格预览支持行列标签、公式显示和横向合并；设置中可调整预览行列上限、公式显示和默认粘贴方式。条目右键菜单提供按设置粘贴、原格式、仅值、公式与值（不带源样式）、转置数值。原格式回放该历史实际保存的格式；其余操作生成新的 SpreadsheetML，未调用 Office 原生 PasteSpecial；目标程序如何应用目标样式需实测。跨工作簿外链、对象、条件格式等不保证等效；没有保存 XML 公式的条目不能生成公式粘贴。
- `code-highlight`：在文本条目右侧 `</>` 菜单选择语言，同一条目会同时留在“文本”和“代码”标签中。选“普通文本”移除代码分类。手动标记不会修改原始内容或剪贴板格式。不默认猜测任意文字，避免误判。代码文件按扩展名预览。设置包含高亮主题、行号、预览行数和字符上限；超限只截断显示，不截断原始数据。支持 Python、JavaScript、TypeScript、JSON、Rust、C/C++、C#、Java、Go、SQL、HTML、XML、CSS、YAML、TOML、Shell、PowerShell、Markdown。TypeScript 使用 JavaScript 基础语法并补充类型关键字；高亮不等于语法校验。

预览在后台执行，HTML 由宿主限制外部资源加载；插件不会连接云端判断代码，也不会调用 Excel/WPS 的全局键鼠。


### 表格公式粘贴（spreadsheet 1.0.1）

普通历史粘贴默认先调用表格插件的“自动保留公式”模式。有已保存的 XML 公式时优先写回 SpreadsheetML，保留源样式与 R1C1 相对／绝对／混合引用；Excel 可按目标单元格解析原始 XML；对于优先采用文本剪贴板的 WPS，插件只读目标窗口的单元格坐标，将 R1C1 引用转换为该目标位置的 A1 公式后正常粘贴，不接管键鼠或直接修改工作簿。目标窗口、选区或自动化接口不可用时停止公式转换并提示。WPS 的文本路径不保证保留源格式。例如 D2 的 `=SUM(B2:C2)` 粘贴到 D8 后为 `=SUM(B8:C8)`，`$B$2` 保持不变。支持 WPS 的 GBK 编码 XML。关闭“公式优先粘贴（自动调整相对引用）”后恢复已保存的原格式粘贴，不执行公式优先处理；该开关不是把相对引用改成绝对引用。也可明确选择“仅粘贴值”。宿主关闭带格式粘贴时仍按纯文本粘贴。

公式只存在于已保存的 XML 时才能恢复，只有计算结果的旧记录无法逆推出公式。普通粘贴自动调用需要本次新增 `action.default_for_paste` 接口的宿主。


### 插件图标

各插件目录包含 `icon.svg` 源文件、`icon.png` 列表图标及 `plugin.ico` Windows 多尺寸图标，清单顶层 `icon` 指向 `icon.png`。修改图标时安装 Pillow 并运行 `python scripts/generate_icons.py`；发布构建直接打包提交的资产，不需要 Pillow。打包器把 `plugin.ico` 作为安装包文件头，后面连接标准 ZIP 内容，并在 ZIP 内保留原始图标资产。Windows 文件关联可直接显示文件头图标；支持图标头的新版截图妈会验证图标边界并读取 ZIP 内容。
