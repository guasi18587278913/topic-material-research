# 素材调研搭档（topic-material-research）

判断选题缺什么材料，整理保留原话、过程、细节和出处的素材包。

随包有 28 个完整方法页面／章节快照。可直接规划调研、整理用户提供的资料；联网搜集需客户端自己的网页工具，平台 API 采集另需使用者账号和预算授权。

完整工作流程见 [SKILL.md](SKILL.md)。

## 安装

需要能读取技能目录的 AI 客户端；GitHub 页面本身不会运行技能。下面命令用于 macOS/Linux 终端，二选一：

```bash
# Codex
mkdir -p ~/.agents/skills
git clone https://github.com/guasi18587278913/topic-material-research.git ~/.agents/skills/topic-material-research
```

```bash
# Claude Code
mkdir -p ~/.claude/skills
git clone https://github.com/guasi18587278913/topic-material-research.git ~/.claude/skills/topic-material-research
```

也可在 GitHub 点击 **Code → Download ZIP**，解压后把包含 `SKILL.md` 的整份目录放到客户端的技能目录，目录名改为 `topic-material-research`。不要只复制入口文件。已有同名目录时先检查本地修改，不直接覆盖；更新用 `git pull --ff-only`，有冲突先处理。客户端未发现技能时重启后再试。

路径依据：[Codex 官方说明](https://learn.chatgpt.com/docs/build-skills)、[Claude Code 官方说明](https://code.claude.com/docs/en/skills)。这些是本机客户端安装方式，不代表自动同步到网页端或云端会话。

## 第一次使用

安装后，在客户端里输入下面的话，再附上自己的材料；也可先用 [合成示例](examples/first-run.md)：

```text
用 $topic-material-research，围绕这份材料判断还缺哪些证据，先只给补料计划，不联网。
```

Codex 可显式使用 `$skill-name`，Claude Code 可用 `/topic-material-research` 或直接说明技能名。收到的材料、快照来源和外部审查状态会分别说明；不会把缺资料当成已经查完。

## 资料来源与连接

默认读仓库内完整方法或用户明确提供的资料，不自动连接作者的私人 Wiki。方法中的来源 slug 是出处标识，不是可公开访问的网址。只有使用者已经配置并选择自己的只读知识库，才核对在线版本；没有连接时继续做本地范围内能完成的工作，缺原文就明确说明，不凭标题补写。

公开内容限于本仓库的技能指令、辅助脚本、选定方法资料及出处记录；不包含整套 Wiki、私人阅读库、账号密钥或个人任务产物。方法中的第三方引文与例子保留原归属，不转成使用者亲历，也不因仓库公开就额外授予第三方内容转载许可；本仓库没有统一开源许可证。

把自己的资料和任务结果放在仓库外的目录。技能不自动发布、发送消息、购买服务或修改知识库。

## 可选能力与运行条件

本地方法读取和已有材料整理不需要 API。需要 TikHub、GetXAPI、AgentKey 时，使用者按 [接口配置](references/providers.md) 提供自己的环境变量或安全存储，并明确本次预算；未配置就报告缺项，不扫描其他项目找密钥。已有网页工具可用于用户允许的免费调研，不要求购买某个服务。

脚本需要 Python 3.9+，使用标准库，不需安装第三方 Python 包。预算锁使用 `fcntl`，采集脚本面向 macOS/Linux；Windows 可用 WSL，未验证 Windows 原生运行。下面命令只做本地演示或验证，不请求付费服务：

```bash
python3 scripts/lookup.py --query '原话' --limit 3
python3 -B -m unittest discover -s tests -p 'test_*.py'
```

## 验证与版本

本次独立使用适配的范围和结果见 [发布验证](docs/portability-validation.md)。原 [上传快照](docs/upload-snapshot.json) 记录第一次导入的来源指纹；它是历史记录，不声称当前修改版仍逐字一致。

文件完整性、脚本测试、合成任务试用和真实用户效果是不同层级；本仓库不以静态检查代替写作质量或平台表现验证。
