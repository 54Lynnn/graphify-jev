<p align="center">
  <h1 align="center">🚀 Graphify-Jev</h1>
  <p align="center"><b>AI 代码智能导航仪与上帝类重构向导 (Code GPS & Refactoring Co-pilot)</b></p>
  <p align="center">
    告别只能看不能用的被动代码地图。融合本地零成本 Tree-sitter AST 与 TypeSafe Jev 150ms 连续决策直出，<br>
    为 Coding Agent 提供语义穿透寻种、因果拓扑修枝、恶性上帝类体检与可落地的架构解耦重构方案。
  </p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=flat&logo=python" alt="Python 3.10+"/>
  <img src="https://img.shields.io/badge/Decision%20Engine-Jev%20System%20One%20(150ms)-ef4444?style=flat" alt="Jev"/>
  <img src="https://img.shields.io/badge/Visual-ECharts%205%20Radar-38bdf8?style=flat" alt="ECharts 5"/>
  <img src="https://img.shields.io/badge/License-Apache--2.0-green?style=flat" alt="License"/>
  <img src="https://img.shields.io/badge/Agent%20Ready-ZCode%20%7C%20Claude%20%7C%20Cursor-purple?style=flat" alt="Agent"/>
</p>

---

## 💡 为什么需要 Graphify-Jev？

传统代码知识图谱工具（包括原版 Graphify）通常只是为项目提供了一张**“被动的静态航拍地图”**：
- **搜不准**：依赖死板的 Jieba 分词或关键词硬匹配，开发者用口语大白话提问极易搜空；
- **杂草多**：BFS 机械扩散遍历时，抓出一堆 `logger`、时间格式化等打杂工具节点，浪费 50% 以上的上下文 Token；
- **看不懂**：面对上万个节点，开发者不知道系统单点故障在哪里；
- **缺导航**：虽然标出了“高频节点”，但不知道如何解耦，更给不出重构代码。

**Graphify-Jev 把地图升级为“实时代码导航仪（Code GPS）”**：
由 **Jev（连续决策模型，150ms 前向直出，输出 Token 免费）** 充当极速心电图，在本地物理图谱中实施两阶段穿透寻种并确诊高危病灶；再由宿主 **Coding Agent** 就地开具可落地的代码解耦与分步重构处方。

---

## ⚡ 核心代差对比 (Graphify vs Graphify-Jev)

| 核心维度 | 官方原版 Graphify | **Graphify-Jev (独立满血版)** |
| :--- | :--- | :--- |
| **代码语义寻种** | 纯关键词 / Jieba 分词硬匹配，语义提问容易脱靶 | **两阶段 Jev 决策穿透**（阶段1选社区 ➔ 阶段2选符号，大白话精准直达） |
| **图谱扩散纯度** | 盲目 BFS 机械扩散，带出大量日志/配置杂草 | **Jev 智能拓扑修枝**（斩断无关打杂分支，因果调用链纯度 100%） |
| **改动影响面分析** | 需人工翻找引用关系 | **Blast Radius 全自动逆向追踪**（自动分级直接波及与间接雪崩链路） |
| **架构异味诊断** | 仅输出冷冰冰的度数统计（如 Degree: 25） | **Jev 架构健康雷达**（精准确诊恶性病灶，安全放行良性基础设施） |
| **重构行动力** | 静态图谱，用户无从下手 | **Skill 动态解耦向导**（Agent 现场生成设计模式、迁移路径与代码 Diff） |
| **Web 可视化大屏** | vis.js 挤压扁平铁饼图 | **ECharts 5 顶级暗黑星云大屏**（同心圆雷达核芯，点击一键复制重构指令） |

---

## 🩺 实战案例：Graphify-Jev 如何诊断并重构自身的 400 行上帝函数

> **真正的工业级产品敢于吃自己的狗粮 (Dogfooding)。**

在扫描自身仓库（546 个源码文件、14,596 个节点、31,470 条调用边）时，Jev 架构健康雷达立即确诊了自身全库第一大恶性病灶：
- **确诊病灶**：`build_from_json()`（位于 `graphify/build.py`，度数 246，牵连 53 个文件）；
- **病因分析**：单一函数堆砌了 400 余行代码，同时承担了输入预检、Schema 容错、AST 与 LLM 幽灵孪生节点合并（Pass 1/2/2b）以及 NetworkX 图组装四重异构职责；
- **解耦重构**：我们按照给出的处方，引入**管道-过滤器模式**，新建 `graphify/build_pipeline.py` 将其拆解为三大高内聚处理器：
  - `ExtractionPreflight`：输入防御与规范化；
  - `GhostNodeResolver`：幽灵节点消解器；
  - `GraphAssembler`：纯净拓扑装配器。
- **成效验收**：`build.py` 内部瘦身为 25 行极简门面（Facade），**94 个现有测试用例 100% 一次性全绿通过**，对外 227 处调用零破坏兼容！

---

## 🚀 快速上手 (Quickstart)

### 1. 安装与配置

```bash
# 从独立产品仓库以可编辑模式安装
git clone https://github.com/54Lynnn/graphify-jev.git
cd graphify-jev
pip install -e .

# 配置 Jev 连续决策引擎（国内推荐 OpenCode Zen 免费版，亦兼容 TypeSafe 官方）
# 在当前工程目录的 .env 文件中添加（或直接 export）：
OPENCODE_API_KEY="sk-..."
OPENCODE_API_URL="https://opencode.ai/zen/v1/systemone"
OPENCODE_MODEL="jev-1.13-free"
```

### 2. 注册为全平台 Coding Agent Skill

一行命令自动注册为当前 AI 助手的全局 Skill：
```bash
graphify install
```
支持：**ZCode、Claude Code、Cursor、OpenCode、Kilo Code、Aider、Trae** 等全平台。

---

## 💬 像与真人架构师交流一样自然使用

### 姿势一：自然语言大白话问诊
在聊天框中对 AI Agent 直接提问：
- **项目全局体检**：“*帮我看看这个仓库有什么架构坏味道？有没有恶性上帝类？*”
- **针对性解耦开方**：“*我想重构 OrderManager，它承担了什么职责？应该怎么拆分？*”
- **变更影响面追踪**：“*如果我要修改 `verify_token` 的参数，会波及哪些上游控制器？*”

### 姿势二：显式 Slash 指令
```bash
/graphify-jev                           # 全量建图并自动生成带《Jev健康雷达》的 GRAPH_REPORT.md
/graphify-jev navigate                  # 快速扫描核心枢纽健康度
/graphify-jev navigate <symbol>         # 提取指定上帝节点的调用切片并开具备选代码处方
```

### 姿势三：打开 ECharts 5 战情大屏
建图完成后，在浏览器中直接双击打开项目根目录下的：
```text
graphify-out/graph_radar.html
```
- 🎯 **同心圆雷达核芯**：恶性上帝节点居中高亮发光，外围依赖如星系同心圆扩散；
- 🌊 **强斥力纯净散开**：物理力场彻底舒展，绝无遮挡重叠；
- 📋 **交互抽屉**：点击任何红色节点，一键复制解耦处方指令直接发给 Agent 现场开刀！

---

## 🛡️ 工业级纪律保障
- **严格 Fail-Open**：未配置 API Key 或网络离线时，100% 优雅降级为纯拓扑启发式分析，绝不阻断建图与查询服务；
- **零隐私泄露**：出站请求仅包含代码符号签名与文件路径元数据，严禁发送源码实现细节；
- **零重型新依赖**：决策层纯基于 Python 标准库 `urllib` 实现，拒绝引入重型第三方包。

---

## 📄 开源许可证
本项目遵循 [Apache-2.0](LICENSE) 开源许可证。
欢迎 Star ⭐️ 关注独立演进版本！
