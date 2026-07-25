# AGY-QQ Bridge System Boundary

*Generated: 2026-06-27T11:30:00Z | Rule: facts only*

---

## 1. AGY 能做什么（事实）

- 接收并处理来自 tmux send-keys 的文本输入
- 通过 PLANNER_RESPONSE 输出结构化结果到 transcript.jsonl
- 执行工具调用（run_command, view_file, replace_file_content 等）
- 维持长时间 tmux 会话（已运行 48h+）
- 在沙箱环境中自动批准部分操作（trusted permission level）
- 输出 CLI 格式回复（含分隔线、> prompt、ASCII 图标）
- 记录完整内部 chain-of-thought 到 transcript（thinking 字段）
- 支持 --dangerously-skip-permissions 参数完全跳过审批

---

## 2. AGY 不能做什么（事实）

- 不在 transcript.jsonl 中记录 PENDING/WAITING/APPROVAL 中间状态
- 不提供事件钩子（event hook）接口用于外部拦截
- 不通过 transcript 发出审批等待信号
- 不区分"审批前的执行确认"和"审批完成后的执行结果"
- 不提供外部程序可读的审批 TUI 结构化数据
- AGY（Antigravity CLI）无公开 GitHub 仓库
- 审批流程不可在 AGY 内部被外部程序截断

---

## 3. 外部系统能控制什么（QQ 桥）

- 向 AGY 发送输入（通过 tmux send-keys）
- 读取 AGY 执行结果（通过 transcript.jsonl / capture-pane）
- 检测 AGY 终端屏幕上的审批 TUI 文本特征（capture-pane 末尾行）
- 在检测到审批 TUI 时向 QQ 推送审批按钮卡片
- 通过用户点击按钮发送 keystroke（y/a/p/n）到 tmux
- 读取 transcript 内容作为 AGY 回复
- 过滤和控制字符清理
- 多用户权限隔离（master openid 验证）

---

## 4. 外部系统无法控制什么（QQ 桥）

- 无法在 AGY 执行流程中插入事件拦截点
- 无法修改 AGY 的沙箱审批等级
- 无法在 AGY 自动批准前获知"即将有审批"
- 无法区分"AGY 自动批准后的 TUI 残留"和"真实等待审批的 TUI"
- 无法控制 AGY 的 CLI 输出格式（分隔线长度、ASCII 图标等）
- 无法阻止 AGY 在 trusted 环境中自动批准后执行命令
- 无法获得审批 TUI 消失的精确事件信号（只能轮询猜测）
- 无法在 transcript 中找到"此操作需要审批"的前置事件
