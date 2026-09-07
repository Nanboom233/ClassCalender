# 暨南大学课表转换

运行脚本生成 ICS，或直接导入 Google Calendar。
API 导入会设置提前 15 分钟提醒，并将目标日历设为橘红色。

## 安装

需要 Python 3.14、uv 和浏览器。在 Windows PowerShell 中执行：

1. 安装 uv：`winget install --id astral-sh.uv --exact`。
2. 重新打开 PowerShell，进入项目目录。
3. 执行以下命令：

```powershell
uv python install 3.14
uv venv --python 3.14
uv sync --locked
```

其他系统按 [uv 安装说明](https://docs.astral.sh/uv/getting-started/installation/)安装。

## 准备 Cookie

1. 登录教务系统。
2. 打开[课表页面](https://jw.jnu.edu.cn/jwapp/sys/wdkb/*default/index.do)。
3. 等待课表加载完成。
4. 使用 Cookie 导出工具，将该页面的 Cookie 导出为 JSON。
5. 将文件放入项目根目录，命名为 `cookies.json`。

必须从上述课表页面导出。其他页面的 Cookie 可能导致 HTTP 403。
支持 Cookie 数组、包含 `cookies` 数组的对象，以及名称到值的映射。

## 配置 Google 授权

只需要 ICS 文件时，跳过本节。

1. 在 [Google Cloud Console](https://console.cloud.google.com/) 创建或选择项目。
2. 在该项目中[启用 Google Calendar API](https://console.cloud.google.com/flows/enableapi?apiid=calendar-json.googleapis.com)。
3. 打开 **Google Auth platform → Branding**。
4. 填写应用名称、支持邮箱和联系邮箱。
5. 使用个人 Google 账号时，在 **Audience** 中选择 **External**。
6. 保持 **Testing** 状态，在 **Test users** 中添加你的 Google 账号。
7. 在 **Data Access** 中添加以下两项权限：

```text
https://www.googleapis.com/auth/calendar.events
https://www.googleapis.com/auth/calendar.calendarlist
```

8. 打开 **Clients → Create client**。
9. 将应用类型设为 **Desktop app**，填写名称并创建。
10. 下载 JSON，放入项目根目录并命名为 `credentials.json`。

无需部署网站或配置公网回调地址。
每次导入都会重新授权，不保存 `token.json`。
浏览器和脚本都需要访问 Google。授权时允许浏览器访问本机回调地址。
回调使用 `http://127.0.0.1:9028/a_very_long_path_to_prevent_token_leak_and_you_should_never_screenshare_this/`。
授权前请确保本机端口 `9028` 可用。

详细页面说明见 [Google 官方教程](https://developers.google.com/workspace/calendar/api/quickstart/python)。

## 运行与导入

1. 执行 `uv run main.py`。
2. 输入教学第 1 周的周一日期，例如 `2026-09-07`。
3. 如果出现未知地点，输入完整地点。
4. 文件生成后，输入 `y` 导入 Google，或回车仅保留 ICS。
5. 在浏览器中选择账号，并在 3 分钟内同意两项权限。
6. 返回终端，输入目标日历编号。输入 `0` 可取消。
7. 遇到重复课程时，按下表选择。
8. 检查终端的导入结果，再打开 Google Calendar 核对。

| 输入 | 操作 |
|---|---|
| `s` 或回车 | 跳过已有课程 |
| `o` | 用当前课表覆盖课程内容、时间、重复规则和提醒 |
| `f` | 仅修复提前 15 分钟提醒 |
| `sa` | 跳过当前及后续全部冲突 |
| `oa` | 覆盖当前及后续全部冲突 |
| `fa` | 修复当前及后续全部冲突的提醒 |

带 `a` 的选择仅用于本次导入。已处理的课程不变，新课程仍正常导入。

所选日历使用 Tangerine（柑橘橘）预设。请优先选择专用课表日历。
已有课程若有单独颜色，请在 Google 中恢复为日历默认颜色。
日期或排课变化后，请检查是否有旧课程需要手动删除。

跨午休或晚饭时间的课程会拆成多个日程，各自设置提醒。
例如第 10–11 节拆为 17:15–18:00 和 19:00–19:45。
已有课表重新导入时，选择 `o` 或 `oa`，更新原日程并补入拆分时段。

脚本按输入日期选择学期：2 月 15 日起为春季，9 月 1 日起为秋季。
输入日期同时决定教学周的起点。脚本不处理节假日调课。
作息变化时，修改 `main.py` 中的 `PERIODS`，并核对[学校作息表](https://cybsec.jnu.edu.cn/2023/1117/c39719a781573/page.htm)。

## 手动导入 ICS

1. 在 Google Calendar 网页打开 **设置 → 导入和导出**。
2. 选择 `calendar.ics` 和目标日历。
3. 点击导入。
4. 将目标日历颜色选为 Tangerine（柑橘橘）。
5. 核对课程提醒。缺少提醒时，添加提前 15 分钟通知。

Google 手动导入不保证保留文件中的提醒和颜色。建议使用 API 导入。
重复导入前先检查旧课程，避免重复。

## 遇到问题

| 问题 | 操作 |
|---|---|
| 教务 HTTP 403 | 从指定课表页面重新导出 Cookie |
| Google 拒绝测试用户 | 在 Audience → Test users 添加当前账号 |
| Google 提示未验证应用 | 核对是否为你创建的应用，再决定是否继续 |
| Google API HTTP 403 | 启用 API，同意两项权限，并选择可写日历 |
| 找不到凭据或类型错误 | 下载 Desktop app JSON，命名为 `credentials.json` |
| 授权超时或浏览器未打开 | 检查默认浏览器、Google 网络连接和本机端口，再重试 |
| 已有课程没有提醒 | 重新导入，对重复课程选择 `f` |
| 设置了提醒但没有通知 | 开启浏览器或手机的通知权限 |
| 导入部分失败 | 查看报告后重新运行，对重复课程选择相应操作 |
| 首周课程缺失 | 重新导入并选择 `o` 或 `oa`，恢复首个已取消时段 |

生成的 ICS 会替换同名文件。API 失败或取消时，ICS 和已完成的远端修改仍会保留。

不要提交或分享 Cookie、OAuth 凭据。
Git 已忽略凭据、生成的日历及 `docs/example_output.json`。
`docs/` 仅存放参考资料，脚本运行时不读取。
