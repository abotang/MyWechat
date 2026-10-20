# MyWeChat — Windows 微信 4.x AI Agent

Python 3.12 项目。自研 UI Automation 驱动，使用 pywinauto、Win32 和 SQLite，未使用 wxauto/wxautox4，未注入进程或使用微信私有协议。

**交付状态：源码、模拟测试和离线演示已在 Python 3.12.7 下通过，尚未完成真实微信客户端适配验收。** 当前未检测到微信进程，PyPI DNS 解析失败导致 pywinauto/pywin32 安装受阻。没有真实控件树，不能提供已验证的微信 4.x 通用选择器；`profile.example.json` 是校准结构，不是即装即用映射。请先执行检测和校准。真实微信读取、发送、@、图片/GIF、好友管理及真实 AI API 均未经本次现场验证。

## 安装与离线验证

在 Windows 桌面交互会话安装 Python 3.12 x64，使用与微信相同权限级别的 PowerShell。不能在锁屏、服务或无桌面的会话中运行驱动。

```powershell
cd <项目目录>
.\scripts\setup.ps1
.\scripts\run.ps1 doctor
.\.venv\Scripts\python.exe -m mywechat.demo
.\scripts\test.ps1
```

默认使用 PATH 中的 `python`。指定 Python 安装位置：`.\scripts\setup.ps1 -Python 'C:\Python312\python.exe'`。安装脚本会拒绝非 3.12 版本。PowerShell 脚本受本机执行策略限制时，可直接执行脚本中对应的 Python 命令；不需要管理员权限。`scripts/run.cmd` 也可作为入口。程序从项目根目录运行，安装脚本会创建 `.env` 和 `config/profile.json`，不会覆盖已有配置。

无网络且已有 httpx 时，也能运行 `python -m unittest discover -s tests -v` 与 `python -m mywechat.demo`。模拟测试不依赖 pywinauto/pywin32，不访问微信或远端 API。HTTP 契约测试需要 httpx。

## 第一步：先检测实际控件

1. 手工启动并登录微信，打开一个测试私聊。
2. 执行顶层窗口清单检测：

```powershell
.\scripts\run.ps1 probe --output data/windows.json
```

3. 查看 `windows.json`，找到微信主窗口的 `process_id`（也可由任务管理器确认）。指定该 PID 再检测：

```powershell
.\scripts\run.ps1 probe --pid 12345 --depth 10 --limit 8000 --output data/private-tree.json
```

4. 分别手工打开群聊、@成员弹窗、媒体预览、新的朋友、添加朋友界面，重复探测保存对应树。检测器只读，不聚焦、不点击。`truncated=true` 表示树未完整，可在允许范围内增加 depth/limit。控件树含聊天和联系人信息，请保存在本地，分享前脱敏。
5. 按 [CALIBRATION.md](CALIBRATION.md) 填写 `config/profile.json`。**不能把示例中的中文占位符当作控件 ID。** 如果微信没有暴露可区分消息内容、发送者或消息方向的 UIA 控件，此版本不能安全工作，需要继续开发基于实际界面证据的适配器。当前不包含 OCR/坐标猜测兜底。

## 第二步：读取与私聊

手工给测试好友/群设置唯一备注或标题，在 `config/chats.json` 写白名单。`key` 是本地独立记忆标识；`title` 必须精确匹配聊天标题和搜索结果。

```json
[
  {"key": "friend_test", "title": "机器人测试好友", "kind": "private"},
  {"key": "group_test", "title": "机器人测试群", "kind": "group"}
]
```

```powershell
.\scripts\run.ps1 verify-profile
.\scripts\run.ps1 read friend_test
.\scripts\run.ps1 contacts
.\scripts\run.ps1 send friend_test '你好 😀'
.\scripts\run.ps1 actions --state pending
.\scripts\run.ps1 approve <动作ID>
.\scripts\run.ps1 execute <动作ID>
```

默认 `.env` 为 `DRY_RUN=true`，上述 execute 仅返回 `simulated`，不会发送。校准和模拟测试通过、准备进行真实测试后，将 `DRY_RUN=false`。新建动作并重新审批执行，已经预演的动作不能重放。发送按钮点击后状态为 `submitted`，只表示已提交 UI 操作，**不表示服务端送达或好友已收到**。收到方应人工核对。

`read` 会切换到白名单会话并读取当前可见消息；`contacts` 只读已经手工打开的联系人列表，不获取整个微信通讯录。微信同名好友/群请先设置唯一备注。无法唯一匹配时直接报错，不自动选择第一个结果。

## 第三步：群聊与 @

```powershell
.\scripts\run.ps1 read group_test
.\scripts\run.ps1 send group_test '大家好'
.\scripts\run.ps1 mention group_test '群成员显示名' '你好，有空吗？'
```

mention 会输入 @、选择真实成员弹窗中的唯一成员，再粘贴正文，避免把普通 `@姓名` 字符串当作实际提醒。成员同名、弹窗控件缺失会中止。正文粘贴暂用剪贴板，尽可能保留 OLE 内容；用户同时复制新内容时不覆盖其剪贴板。此路径尚未经真实客户端验证。

## 第四步：Emoji、图片与 GIF

Unicode Emoji 通过 send 发送，显示效果由客户端决定。

```powershell
.\scripts\run.ps1 send friend_test '早上好 ☀️ 😀'
.\scripts\run.ps1 media friend_test 'C:\Images\hello.png'
.\scripts\run.ps1 media group_test 'C:\Images\hello.gif'
```

媒体仅接受 PNG/JPG/JPEG/BMP/GIF，最大 20MB，审批绑定文件 SHA-256 防止审批后换内容。通过客户端附件入口、文件对话框和媒体预览按钮提交；缺少任何已校准控件就中止。不同微信版本可能把 GIF 当作文件/静态图，**尚未验证动图播放和原生收藏表情发送，不保证与表情面板发送相同**。不包含微信内置表情包商店/收藏表情面板适配。

## 第五步：好友管理

手工打开“新的朋友”后读取申请，核对申请者与验证说明，再提交接受动作：

```powershell
.\scripts\run.ps1 friends
.\scripts\run.ps1 accept-friend <申请ID>
.\scripts\run.ps1 actions --state pending
.\scripts\run.ps1 approve <动作ID>
.\scripts\run.ps1 execute <动作ID>
```

主动添加：手工打开已校准的添加朋友界面，提供精确微信号或手机号：

```powershell
.\scripts\run.ps1 add-friend '准确微信号' '你好，我是胡锦程'
```

搜索结果中的账号标识必须与输入精确匹配，无法验证就中止。添加与接受好友**始终需要审批**，即使 `REQUIRE_APPROVAL=false` 也不会自动通过。执行时重新计算并核对申请 ID；重启微信后 runtime_id 可能失效，应重新读取再提交。验证码或客户端风险提示不自动处理，不自动批量加人。新增好友不会自动加入聊天白名单。

## 第六步：AI Agent 与联系人记忆

在 `.env` 填写 `AI_API_KEY`、`AI_BASE_URL`、`AI_MODEL`，支持 OpenAI Chat Completions 兼容 JSON 输出接口。例如 DeepSeek 配置见 `.env.example`；OpenAI 可设置 `AI_BASE_URL=https://api.openai.com/v1` 并填可用模型名。所选模型必须支持 `response_format=json_object`。不要将密钥放入源码或聊天中。

```powershell
# 首轮只建立已有消息基线
.\scripts\run.ps1 run --once --ai-consent
# 持续运行；可能切换会话并占用前台，请使用专用桌面时段
.\scripts\run.ps1 run --ai-consent
```

`--ai-consent` 表示允许将白名单内每个会话最近 30 条文本发送给你配置的 AI 服务。DRY_RUN 仅禁止对外发送消息，**不会禁止读取微信或调用 AI**。无需微信和 API 的纯离线验证请用 `python -m mywechat.demo`。

启动后各会话首次快照仅保存为基线，不回复历史积压。后续轮询抓取可见消息，SQLite 按消息标识去重，忽略自己发出的消息，并以 chat key 隔离私聊/群聊上下文。标识失去连续性时重新建立基线，避免把旧消息误认为新消息。短时间同一人的多条消息一起决策，冷却期的输入保留到下次处理。

群聊先走本地门控：被 @ 或包含 `.env` 中 `GROUP_TOPICS` 关键词才请求模型；关键词为空时只响应 @。`mention_pattern` 要根据实际 UIA 正文校准真实 @ 表示。模型再判断是否参与，返回 JSON 的 participate/text/reason。聊天内容作为不可信数据，模型没有客户端工具、审批权或加好友能力；AI 只生成文本动作。不要仅依赖模型判断来放开敏感操作。

`REQUIRE_APPROVAL=true` 时，另开终端执行 actions/approve/reject，运行中的 Agent 会执行批准的动作。设为 false 后，只有白名单文本回复会自动获批；群聊门控、冷却、去重与停止机制仍生效。人工 send/mention/media 仍先生成动作，用 execute 或由运行中的 Agent 执行。默认审批期限 300 秒，超期动作在运行循环中失效；没有运行循环时会在审批/执行时检测过期。

## 停止与异常恢复

```powershell
.\scripts\run.ps1 stop
.\scripts\run.ps1 resume
.\scripts\run.ps1 reject <动作ID>
.\scripts\run.ps1 resolve <结果未知的动作ID> --note '已人工核对微信，未重发'
.\scripts\run.ps1 forget friend_test
```

F12、Ctrl+C 或 stop 可停止。stop 写入 STOP 文件，后续动作会拒绝；resume 仅移除 STOP，不自动重启。F12 由后台轮询记录，HTTP 请求在超时前可能仍等待，但返回后会再次检查停止状态再发送。UIA/系统调用已提交后无法撤回，F12 不保证撤销已经点击的发送。

动作状态：pending → approved → executing → submitted；预演转 simulated；拒绝转 rejected；超期转 expired。执行失败或中断转 uncertain，阻止该会话新增动作与自动重发，必须人工核对后 resolve。进程锁防止两个实例同时操作 UI；审批命令可与 Agent 并行。只按提交记录计算冷却，不伪造送达回执。输入框草稿、会话不符、焦点丢失、控件多匹配都中止。

SQLite 默认明文存于 data/，不做云同步；仅传配置的 AI 上下文。日志不写聊天内容、密钥或 API 原始响应。actions/read/friends 命令按需显示私人信息。`forget` 删除本地对应会话记录和动作，不删除微信消息，也不撤回此前已发送到模型服务的数据。首次上线前可将测试数据目录单独备份。

## 架构与验证范围

| 文件 | 作用 |
| --- | --- |
| probe.py | UIA 窗口清单、指定 PID 控件树、遍历预算 |
| driver.py | 精确控件匹配、读取、私聊/群聊/@、媒体、好友管理 |
| store.py | SQLite 独立会话上下文、持久化收件箱与动作状态 |
| ai.py / agent.py | HTTP JSON 契约、群聊参与决策、基线、轮询和退避 |
| service.py / safety.py | 白名单、审批、冷却、媒体指纹、停止与进程锁 |
| cli.py / demo.py | 命令行操作、独立离线端到端演示 |
| tests/ | 标准库 unittest，HTTP 测试使用 httpx.MockTransport |

测试结果与限制见 [VALIDATION.md](VALIDATION.md)。当前监听通过依次打开白名单会话轮询，仅覆盖 UIA 暴露的可见消息，不是完整后台消息流；消息太快、滚动/虚拟化、多个会话切换会漏读。UIA 运行时标识不是微信消息服务端 ID；不承诺全量历史抓取或跨进程精确一次。微信升级后重新 probe 和校准，不要沿用失效映射。

参考： [pywinauto UIA 控件文档](https://pywinauto.readthedocs.io/en/latest/code/pywinauto.controls.uia_controls.html)、[DeepSeek JSON Output](https://api-docs.deepseek.com/zh-cn/guides/json_mode/)。
