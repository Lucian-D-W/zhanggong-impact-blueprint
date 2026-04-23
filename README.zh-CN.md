# 张工的施工图.skill

[English](README.md) | [简体中文](README.zh-CN.md)

## 背景消息

> 张工是我的一个朋友。早年是工地上画施工图的土木老哥，后来一拍大腿转行写代码。干着干着发现，那些 AI Agent 改起代码来跟拆迁队似的：这儿敲一块，那儿补一锤，毫无大局观。张工一拍键盘：“得，我给你们当总工！”从此他把自己封装成一个 skill，专门给各路 agent 输出详细施工图。现在公司里所有 Agent 干活前，都得先找张工要图纸。

张工的施工图 / ZhangGong Impact Blueprint 是一个面向 agent 驱动改动的、仓库本地化的影响图谱与验证护栏。
完整规则和详细行为说明请看 [`.agents/skills/zhanggong-impact-blueprint/SKILL.md`](E:/AA-HomeforAI/CodeAccounting/.agents/skills/zhanggong-impact-blueprint/SKILL.md:1)。
如果你更习惯中文审阅，可以看中文版说明：[`.agents/skills/zhanggong-impact-blueprint/SKILL.zh-CN.md`](E:/AA-HomeforAI/CodeAccounting/.agents/skills/zhanggong-impact-blueprint/SKILL.zh-CN.md:1)。

## 这是什么

- 一个可复制的 skill 文件夹
- 一个在改动前给出影响阅读面、在改动后保留结构化证据的轻量工作流

## 有什么用

- 核心就是给 AI 立规矩：别一上来就瞎改。尤其上下文不够时，能少犯“漏看链路、反复 debug、打几个补丁然后死循环”的毛病。让agent明白“今日隐患视而不见，明日事故必来相见”的重要道理。
- 短期会多花点 token 和步骤，但中长期有复利——项目更耐造、好交接，不用每次换个 AI 就从零讲起。
- 对上下文不足的 AI 特别友好，能把它从“局部糊墙 + 死循环排障”的坑里拽出来，逼它先看影响再动手。

## 怎么使用

1. 把 `zhanggong-impact-blueprint` 文件夹复制到你要使用的仓库里，放到 `./.agents/skills/` 下面。
2. 放好之后，目标路径应该是 `./.agents/skills/zhanggong-impact-blueprint/`。
3. 之后你和 AI 交互时，直接在对话里明确要求它使用这个 skill 就可以了。
4. 你真正需要做的事情，主要是描述你要改什么；至于什么时候 `analyze`、什么时候 `finish`，应该由使用这个 skill 的 AI 按规则自己执行。

如果只是正常使用，你一般不需要手动去跑这些命令行。命令行更偏向维护、排障或验证这个 skill 本身时使用。

## 先安装 GitNexus

Stage 20 在第一次跑真实仓库前，最好先把 GitNexus 装好。

1. 安装 GitNexus CLI：
   `npm install -g gitnexus`
2. 验证命令可用：
   `gitnexus --version`
3. 日常仍然使用 `zhanggong` 这条主流程：
   `setup --minimal -> calibrate -> analyze -> finish`

当 GitNexus 可用时，zhanggong 会把它当成默认 graph provider。
当 GitNexus 对当前仓库还没准备好时，zhanggong 会继续用 internal provider，把流程跑完。

## 适合什么场景

- 当你已经把 AI 当成了日常搭子，而不是偶尔拿来查个报错的小工具
- 当你的项目不再是一个跑完就扔的临时脚本，而是得长期伺候、反复改来改去的老代码
- 当你发现 AI 经常因为记不住上下文，乱删代码、瞎改逻辑，或者越修bug越多
- 当你希望换了个AI、换了轮对话，接手的人（或机器）还不至于一脸懵逼、啥都从头讲
- 当你想把“动代码之前先看影响面，改完留个验证记录”这件事，刻进DNA里

## 更新说明

### Stage 20 / v0.20.0-rc1

重点变化：

- 增加 provider 抽象层
- 接入更强的 gitnexus 分析
- 默认 `graph_provider = gitnexus`
- `GitNexus` 失败时自动 fallback 到 internal provider

### Stage 18.1 / v0.18.1-rc1

修掉的重点问题包括：

- 修复 Windows 下 `.sh` 测试入口预检漏判
- 修复 GBK / Windows 终端下“测试已过但 CLI 因输出编码失败”
- 支持 Python 项目使用 `test/` 目录
- 修复 baseline / no_regression 的 flaky 判断
- 修复 `finish` 成功后 handoff 残留旧错误
- 修复 seed 未选定时 `next-action` 误推荐 `finish`
- 修复 trust explanation 自相矛盾
- 修复 repo config 中 list-form `test_command` 被忽略

## 致谢

Stage 20 形态下，本项目默认使用 GitNexus 作为图谱 provider。
感谢 [GitNexus](https://github.com/abhigyanpatwari/GitNexus) 提供更强的本地图谱、上下游影响和流程链路视角。
