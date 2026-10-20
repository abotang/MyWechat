# 实机控件校准与验收

本项目没有假定微信 4.x 的控件类名或自动化 ID。所有选择器均需来自当前登录客户端的 probe 输出；没有取得真实树之前不能宣布驱动适配完成。

## 配置结构

复制 `config/profile.example.json` 为 `config/profile.json`，填当前微信主窗口 PID、精确窗口选择器。窗口筛选同时限定进程，PID 在客户端重启后可能改变，必须重新核对。

每个选择器支持 `name`、`automation_id`、`control_type`、`class_name` 任意非空组合，均为精确匹配，必须唯一。值来自 probe 同名字段，不是 Win32 句柄，也不是 UIA 树的数组序号。不使用坐标或第一个匹配结果兜底。

```json
{
  "schema": 1,
  "calibrated": false,
  "process_id": 12345,
  "window": {"name": "真实窗口标题", "class_name": "真实窗口类名"},
  "selectors": {
    "chat_title": {"automation_id": "实际标题ID", "control_type": "Text"},
    "input_edit": {"automation_id": "实际输入框ID", "control_type": "Edit"},
    "file_dialog": {"scope": "process", "match": {"name": "实际对话框标题", "control_type": "Window"}}
  },
  "message": {},
  "friend": {}
}
```

这是结构说明，不是有效微信映射。`scope=process` 可用于同进程的独立文件对话框/弹窗，其余选择器默认在主窗口后代中查找。子控件参数有 root 时在 root 内查找。若客户端文件对话框由其他进程承载，该路径当前不支持，应保留为未适配，不能扩大到任意桌面窗口匹配。

## 各阶段必填选择器

| 阶段 | selectors 键 | 说明 |
| --- | --- | --- |
| 消息读取 | chat_title, messages | 当前会话标题、消息容器 |
| 会话切换 | search_edit, search_results | 搜索输入、结果容器；结果内 name 与白名单 title 精确匹配 |
| 私聊/群聊发送 | input_edit, send_button | 输入框必须支持 UIA set_edit_text；无支持则需继续开发输入适配 |
| 联系人 | contacts_list | 手工打开的列表容器 |
| 群聊 @ | mention_popup | 输入 @ 后真实成员候选弹窗；成员 name 唯一 |
| 图片/GIF | attach_button, file_dialog, file_name_edit, file_open_button, media_preview, media_send_button | 文件名/打开按钮在文件对话框内；预览及发送按钮必须能精确匹配 |
| 好友申请 | friend_requests | 手工打开的新的朋友容器 |
| 接受确认 | friend_confirm_button | 只有 requires_confirm=true 时必填 |
| 主动加人 | add_friend_search, add_friend_search_button, add_friend_result_id, add_friend_button, friend_greeting, friend_request_send | 结果账号控件文字必须等于输入的准确微信号/手机号 |

`verify-profile` 只验证当前界面能否唯一匹配已填选择器，不会打开弹窗或发送。尚未展开的控件会返回未匹配，这是正常现象。请在对应界面分别检查。所有需要操作的控件还需通过实机验证支持实际调用模式。

## 消息方向与身份

message.row 在 messages 后代中选择每一条消息；body、sender、outgoing_marker 相对于消息行匹配。body 和 sender 均须唯一，body 是纯正文、sender 是显示名称。outgoing_marker 需要匹配**只在自己的消息行中存在**的控件；不存在则该行被认作收到的消息。请同时检测一条自己发送和一条好友发送的消息验证方向，错误配置会导致自我回复。

如果昵称、时间和正文被合并成一个不可分控件，此通用适配不能直接工作，需根据实机信息开发消息解析器；不能编造 sender 字段。系统消息/图片若无法匹配 body/sender，会使当前读取失败；当前只有文本消息解析，不能解析语音、图片内容或撤回通知。

id_source 可选 automation_id 或 runtime_id。只有每条消息行 automation_id 唯一且稳定时才能选前者；runtime_id 只在 UIA 实例存活期间有效。重启后首次快照不回复；轮询中找不到上次最后一条的标识时重新建立基线，会牺牲部分新消息以降低重复发送风险。既不承诺全量监听，也不将显示文字哈希视作唯一消息 ID。

mention_pattern 是实际收到 @ 自己时正文的正则，可使用准确显示名和边界，例如在实机确认格式后设置 `@胡锦程(?:\\s|$)`（JSON 中反斜杠需要转义）。纯文本伪造 @ 也可能匹配；它只是参与候选条件，不能当作身份鉴权。若客户端正文不暴露 @，需要继续适配，当前不得声称支持检测。

## 好友申请配置

friend 对象的 row/name/detail/accept 是真实选择器，前者在 friend_requests 下，后三者在每条申请行下；detail 应包括验证说明或可帮助人工核对身份的信息。requires_confirm 依据实机按钮行为填 true/false，不能猜测。申请 ID 由行控件标识、姓名、详情共同计算，内容/控件变化后旧申请 ID 不再有效。

## 实机验收顺序

按用户要求逐项完成，前一阶段失败先修复；不要直接打开无人值守回复。

1. **读取**：私聊双方各发三条，包括相同文本、中文、Emoji，核对 sender/outgoing/id，重复读取不出现重复 ID；核对联系人唯一备注。
2. **私聊**：先 DRY_RUN 审批预演，再真实发送一条，由收到方核实。更换会话、保留草稿、打开另一应用时应拒绝错误操作。确认提交记录与送达结果的区别。
3. **群聊**：至少两成员各发消息，核对发送者；验证真实 @ 提醒、同名成员拒绝、无关话题跳过、被 @ 时生成待审批动作。
4. **媒体**：分别 PNG 和 GIF 预演、审批、实发，核对接收端是否以期望方式显示/播放。另测文件缺失、预览控件缺失及审批后改文件内容。未确认播放前保持 GIF 未验证。
5. **好友**：由测试账号发申请，手工核对说明，审批后接受；用准确测试微信号发送申请，确认始终需要审批，标识不符不得提交。客户端安全确认由人处理。
6. **AI**：先用离线 demo，再配真实 API、白名单和 --ai-consent，REQUIRE_APPROVAL=true 运行；验证各私聊记忆独立、群聊不随意插话、同一条消息不重复回复、冷却保留待处理消息、429 后退避。
7. **停止**：在待审批、冷却、网络等待、输入前测试 F12/stop/Ctrl+C；重启不能自动重发 uncertain 动作，人工核对 resolve 后才能继续。

每次记录微信版本、Windows 版本、Python 版本、显示缩放、探测日期、profile 摘要、具体测试结果。通过后才设置 calibrated=true 并保留对应实机记录；此标志是操作者声明，程序不会自动把模拟测试当作实机通过。
