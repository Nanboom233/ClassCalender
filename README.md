# 暨南大学课表转换

将教务课表导出为 ICS，或导入 Google Calendar。

## 安装

在 Windows PowerShell 中完成安装。

1. 安装 uv：`winget install --id astral-sh.uv --exact`。
2. 重新打开 PowerShell。
3. 进入项目目录。
4. 安装 Python：`uv python install 3.14`。
5. 创建环境：`uv venv --python 3.14`。
6. 安装依赖：`uv sync --locked`。

其他系统按 [uv 安装说明](https://docs.astral.sh/uv/getting-started/installation/)安装。

## 准备 Cookie

1. 登录教务系统。
2. 打开[课表页面](https://jw.jnu.edu.cn/jwapp/sys/wdkb/*default/index.do)。
3. 等待课表加载完成。
4. 使用 Cookie 导出工具，将该页面的 Cookie 导出为 JSON。
5. 将文件放入项目根目录，命名为 `cookies.json`。

必须从上述课表页面导出 Cookie。
不要分享 `cookies.json`。

## 配置 Google 授权

只需要 ICS 文件时，跳过本节。

1. 在 [Google Cloud Console](https://console.cloud.google.com/) 创建或选择项目。
2. 在该项目中[启用 Google Calendar API](https://console.cloud.google.com/flows/enableapi?apiid=calendar-json.googleapis.com)。
3. 打开 **Google Auth platform → Branding**。
4. 填写应用名称、支持邮箱和联系邮箱。
5. 使用个人 Google 账号时，在 **Audience** 中选择 **External**。
6. 将发布状态设为 **Testing**。
7. 在 **Test users** 中添加你的 Google 账号。
8. 在 **Data Access** 中添加以下两项权限：

```text
https://www.googleapis.com/auth/calendar.events
https://www.googleapis.com/auth/calendar.calendarlist
```

9. 打开 **Clients → Create client**。
10. 将应用类型设为 **Desktop app**。
11. 填写客户端名称。
12. 点击 **Create**。
13. 下载 JSON 文件。
14. 将文件放入项目根目录，命名为 `credentials.json`。

不要分享 `credentials.json`。

详细页面说明见 [Google 官方教程](https://developers.google.com/workspace/calendar/api/quickstart/python)。

## 运行与导入

1. 执行 `uv run main.py`。
2. 输入教学第 1 周的周一日期，例如 `2026-09-07`。
3. 如果出现未知地点，输入完整地点。
4. 文件生成后，输入 `y` 导入 Google Calendar。仅需文件时，直接回车。
5. 在浏览器中选择 Google 账号。
6. 在 3 分钟内同意两项权限。
7. 返回终端，输入目标日历编号。取消导入时，输入 `0`。
8. 遇到重复课程时，按下表选择。
9. 检查终端的导入结果。
10. 在 Google Calendar 中核对课程日期、时间、地点和提醒。

| 输入 | 操作 |
|---|---|
| `s` 或回车 | 跳过已有课程 |
| `o` | 用当前课表覆盖课程内容、时间、重复规则和提醒 |
| `f` | 仅修复提前 15 分钟提醒 |
| `sa` | 跳过当前及后续全部冲突 |
| `oa` | 覆盖当前及后续全部冲突 |
| `fa` | 修复当前及后续全部冲突的提醒 |

请优先选择专用课表日历。
如需更新已有课表，选择 `o` 或 `oa`。
遇到节假日调课，请按学校通知手动调整日程。

## 手动导入 ICS

1. 在 Google Calendar 网页打开 **设置 → 导入和导出**。
2. 选择 `calendar.ics`。
3. 选择目标日历。
4. 点击导入。
5. 将目标日历颜色选为 Tangerine（柑橘橘）。
6. 核对课程提醒。缺少提醒时，添加提前 15 分钟通知。

再次手动导入前，请检查并清理重复课程。

## 遇到问题

| 问题 | 操作 |
|---|---|
| 教务 HTTP 403 | 从指定课表页面重新导出 Cookie |
| Google 拒绝测试用户 | 在 Audience → Test users 添加当前账号 |
| Google 提示未验证应用 | 核对是否为你创建的应用，再决定是否继续 |
| Google API HTTP 403 | 启用 API，同意两项权限，并选择可写日历 |
| 找不到凭据或类型错误 | 下载 Desktop app JSON，命名为 `credentials.json` |
| 授权超时或浏览器未打开 | 检查默认浏览器和 Google 网络连接后重试 |
| 本机回调端口被占用 | 关闭占用端口 `9028` 的程序后重试 |
| 已有课程没有提醒 | 重新导入，对重复课程选择 `f` |
| 设置了提醒但没有通知 | 开启浏览器或手机的通知权限 |
| 导入部分失败 | 查看报告后重新运行，对重复课程选择相应操作 |
| 首周课程缺失 | 重新导入并选择 `o` 或 `oa` |
