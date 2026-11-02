# 截图妈插件

这里开发和打包截图妈的独立扩展。所有插件使用统一的程序级扩展协议 v2；旧协议包不能安装到此版本的截图妈。

在 Windows 安装 Rust MSVC 工具链与 Python 3 后运行：

```powershell
python scripts/package.py
```

生成的 `.jtbplugin` 文件位于 `dist/`。在截图妈系统托盘右键菜单或剪贴板窗口的设置菜单选择“安装插件”。插件以当前用户权限运行，只应安装信任的来源。

推送分支或创建 Pull Request 只运行检查，不发布。发布时先把 `Cargo.toml` 和每个插件清单的版本更新为同一版本并提交，再对该提交推送 `v<版本>` 标签；例如 `git tag v0.6.0`、`git push origin v0.6.0`。带后缀的标签（如 `v0.6.0-beta.1`）生成预发布。标签可指向包含发布工作流的任意分支提交；标签不匹配版本时不会发布。

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

## 电子表格和代码高亮（0.6.0）

需要截图妈 2.2.5 或更新版本提供的插件类型、选择字段和多格式粘贴接口，旧版宿主不能安装这两个新包。

- `spreadsheet`：识别已存储的 XML Spreadsheet、HTML 表格或 TSV，网格预览支持行列标签、公式显示和横向合并；设置中可调整预览行列上限、公式显示和默认粘贴方式。条目右键菜单提供按设置粘贴、原格式、仅值、公式与值（不带源样式）、转置数值。原格式回放该历史实际保存的格式；其余操作生成新的 SpreadsheetML，未调用 Office 原生 PasteSpecial；目标程序如何应用目标样式需实测。跨工作簿外链、对象、条件格式等不保证等效；没有保存 XML 公式的条目不能生成公式粘贴。
- `code-highlight`：在文本条目右侧 `</>` 菜单选择语言，同一条目会同时留在“文本”和“代码”标签中。选“普通文本”移除代码分类。手动标记不会修改原始内容或剪贴板格式。不默认猜测任意文字，避免误判。代码文件按扩展名预览。设置包含高亮主题、行号、预览行数和字符上限；超限只截断显示，不截断原始数据。支持 Python、JavaScript、TypeScript、JSON、Rust、C/C++、C#、Java、Go、SQL、HTML、XML、CSS、YAML、TOML、Shell、PowerShell、Markdown。TypeScript 使用 JavaScript 基础语法并补充类型关键字；高亮不等于语法校验。

预览在后台执行，HTML 由宿主限制外部资源加载；插件不会连接云端判断代码，也不会调用 Excel/WPS 的全局键鼠。
