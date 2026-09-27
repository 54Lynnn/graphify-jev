<p align="center">
  <h1 align="center">🚀 Graphify-Jev</h1>
  <p align="center"><b>AI 代码智能导航仪与上帝类重构向导 (Code GPS & Refactoring Co-pilot)</b></p>
  <p align="center">
    告别只能看不能用的被动代码地图。融合本地零成本 Tree-sitter AST 与 TypeSafe Jev 150ms 连续决策直出，<br>
    为 Coding Agent 提供语义穿透寻种、因果拓扑修枝、恶性上帝类体检、自动化双模战情大屏与 ComfyUI 风格激光卷帘对比。
  </p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=flat&logo=python" alt="Python 3.10+"/>
  <img src="https://img.shields.io/badge/Decision%20Engine-Jev%20System%20One%20(150ms)-ef4444?style=flat" alt="Jev"/>
  <img src="https://img.shields.io/badge/Visual%20Engine-Pure%20Canvas%2060FPS-38bdf8?style=flat" alt="Canvas 60FPS"/>
  <img src="https://img.shields.io/badge/Comparison-ComfyUI%20Curtain%20Swipe-a855f7?style=flat" alt="ComfyUI Swipe"/>
  <img src="https://img.shields.io/badge/License-Apache--2.0-green?style=flat" alt="License"/>
  <img src="https://img.shields.io/badge/Agent%20Ready-ZCode%20%7C%20Claude%20%7C%20Cursor-purple?style=flat" alt="Agent"/>
</p>

---

## 💡 为什么需要 Graphify-Jev？

传统代码知识图谱工具（包括原版 Graphify）通常只是为项目提供了一张**“被动的静态航拍地图”**：
- **搜不准**：依赖死板的 Jieba 分词或关键词硬匹配，开发者用口语大白话提问极易搜空；
- **杂草多**：BFS 机械扩散遍历时，抓出一堆 `logger`、时间格式化等打杂工具节点，浪费 50% 以上的上下文 Token；
- **看不懂**：面对上万个节点，开发者不知道系统单点故障在哪里；
- **缺导航**：虽然标出了“高频节点”，但不知道如何解耦，更给不出重构代码；
- **无获得感**：改动前后缺少直观、震撼的架构对比感知。

**Graphify-Jev 把地图升级为“实时代码导航仪（Code GPS）”**：
由 **Jev（连续决策模型，150ms 前向直出，输出 Token 免费）** 充当极速心电图，在本地物理图谱中实施两阶段穿透寻种并确诊高危病灶；再由宿主 **Coding Agent** 就地开具可落地的代码解耦与分步重构处方；最终通过 **ComfyUI 风格激光卷帘对比大屏** 见证上帝类瓦解，让架构成果看得见、摸得着！

---

## ⚡ 核心代差对比 (Graphify vs Graphify-Jev)

| 核心维度 | 官方原版 Graphify | **Graphify-Jev (独立满血版)** |
| :--- | :--- | :--- |
| **代码语义寻种** | 纯关键词 / Jieba 分词硬匹配，语义提问容易脱靶 | **两阶段 Jev 决策穿透**（阶段1选社区 ➔ 阶段2选符号，大白话精准直达） |
| **图谱扩散纯度** | 盲目 BFS 机械扩散，带出大量日志/配置杂草 | **Jev 智能拓扑修枝**（斩断无关打杂分支，因果调用链纯度 100%） |
| **改动影响面分析** | 需人工翻找引用关系 | **Blast Radius 全自动逆向追踪**（自动分级直接波及与间接雪崩链路） |
| **架构异味诊断** | 仅输出冷冰冰的度数统计（如 Degree: 25） | **Jev 架构健康雷达**（精准确诊恶性病灶，安全放行良性基础设施） |
| **重构行动力** | 静态图谱，用户无从下手 | **Skill 动态解耦向导**（Agent 现场生成设计模式、迁移路径与代码 Diff） |
| **术前大屏呈现** | vis.js 挤压扁平铁饼图 | **ECharts 5 顶级暗黑星云大屏**（同心圆雷达核芯，点击一键复制重构指令） |
| **术后对比获得感** | 零对比机制，用户无感知 | **ComfyUI 风格无限画布激光卷帘大屏**（鼠标左右滑动平滑揭开 Before/After，双层同频锁死） |

---

## 🌟 用户视角黄金工作流 (The Golden 5-Step Flow)

用户无需记忆任何复杂的命令行参数，人类开发者负责用自然语言掌控全局，底层驱动全由 Agent 自动化调度：

```text
 ┌────────────────────────────────────────────────────────────────────────┐
 │ Step 1: 环境一次性准备 (git clone & pip install -e .)                   │
 └──────────────────────────────────┬─────────────────────────────────────┘
                                    │
                                    ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │ Step 2: 注册 Agent Skill (graphify-jev install)                        │
 └──────────────────────────────────┬─────────────────────────────────────┘
                                    │
                                    ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │ Step 3: 大白话下达扫描任务 ("用 graphify-jev 扫描我的 XX 项目")          │
 │         • 本地 AST 毫秒级建图 + Jev 150ms 连续决策健康扫描              │
 │         • 🌐 自动拉起并展示 Before 架构战情大屏 (localhost:8899/radar)   │
 └──────────────────────────────────┬─────────────────────────────────────┘
                                    │
                                    ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │ Step 4: 专家现场开具处方 ("针对查出的上帝节点，给我分步解耦计划与代码") │
 │         • 提取上下游调用拓扑切片，输出单一职责成因与目标设计模式        │
 │         • 提供分步实施路径与前后对比代码骨架 Diff                       │
 └──────────────────────────────────┬─────────────────────────────────────┘
                                    │
                                    ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │ Step 5: 隔离开刀 ➔ 全量测试 ➔ 自动呈上 Before+After 激光卷帘大屏       │
 │         • 严格在独立 Worktree 下开刀重构，测试 100% 绿灯后合入 main     │
 │         • ↔ 自动合成 ComfyUI 风格激光卷帘对比 (curtain_compare.html)   │
 │         • 左右滑动鼠标见证上帝病灶平滑解构为健康微模块，获得感拉满！    │
 └────────────────────────────────────────────────────────────────────────┘
```

---

## 🩺 工业级实战案例：真实业务项目中的两大战役

> **真正的工业级产品敢于吃自己的狗粮 (Dogfooding)，并在真实复杂业务中经受检验。**

### 战役一：全栈商业客户端 `fullstack-project` (Go + Python + JS，2400+ 节点) 深度重构
- **扫描规模**：193 个源码文件，2,467 个实体节点，8,204 条关系边，94 个功能社群；
- **战果一（前端巨石瓦解）**：Jev 架构雷达一眼确诊前端恶性病灶 `app.js`（连接度 68，2542 行单体脚本），指导开发者拆分为 5 个清晰领域子模块，22 项契约测试 100% 绿灯；
- **战果二（后端隐蔽解耦）**：扩大扫描至 Top 30 核心中枢，Jev 敏锐捕捉到 `handlers.go`（连接度 62）隐蔽强耦合了直连转发与 300 行流式状态机，指导开发者瘦身 62% 抽离 `stream.go`；
- **最终成果**：全库 Top 30 恶性上帝病灶彻底清零（0 Malignant Gods），所有测试无缝通过！详细复盘见 [docs/DOGFOOD-REPORT-FULLSTACK-PROJECT.md](docs/DOGFOOD-REPORT-FULLSTACK-PROJECT.md)。

### 战役二：Graphify-Jev 自身 400 行怪兽函数的治愈
- **确诊病灶**：自身核心 `build_from_json()`（度数 246，牵连 53 个文件）；
- **解耦重构**：引入**管道-过滤器模式**，新建 `graphify/build_pipeline.py` 拆解为 `ExtractionPreflight`、`GhostNodeResolver` 与 `GraphAssembler` 三大处理器；
- **成效验收**：核心函数瘦身为 25 行极简门面（Facade），**96 个测试用例 100% 一次性全绿通过**，对外 227 处调用零破坏兼容！

---

## 🚀 快速上手 (Quickstart)

### 1. 安装与配置

```bash
# 从独立产品仓库克隆并安装
git clone https://github.com/54Lynnn/graphify-jev.git
cd graphify-jev
pip install -e .

# 配置 Jev 连续决策引擎（国内推荐 OpenCode Zen 免费版，亦兼容 TypeSafe 官方）
# 支持在 ~/.graphify/.env 全局配置（一次配置，全电脑所有项目免配即用）：
mkdir -p ~/.graphify
cat << 'EOF' > ~/.graphify/.env
OPENCODE_API_KEY="sk-..."
OPENCODE_API_URL="https://opencode.ai/zen/v1/systemone"
OPENCODE_MODEL="jev-1.13-free"
EOF
```

### 2. 注册为全平台 Coding Agent Skill

一行命令自动注册为当前 AI 助手的全局 Skill：
```bash
graphify-jev install
```
支持：**ZCode、Claude Code、Cursor、OpenCode、Kilo Code、Aider、Trae** 等全平台。

---

## 💬 像与真人架构师交流一样自然使用

### 姿势一：自然语言大白话问诊与全自动大屏
在聊天框中对 AI Agent 直接提问：
- **项目全局体检**：“*帮我看看这个仓库有什么架构坏味道？有没有恶性上帝类？*”
  ➔ **Agent 自动执行扫描，并在回答开头附带实时战情大屏链接**：[http://localhost:8899/graph_radar.html](http://localhost:8899/graph_radar.html)
- **针对性解耦开方**：“*我想重构 OrderManager，它承担了什么职责？应该怎么拆分？*”
- **变更影响面追踪**：“*如果我要修改 `verify_token` 的参数，会波及哪些上游控制器？*”
- **完工数字化复查**：
  ➔ **重构完成测试通过后，Agent 自动在完工总结中呈上 ComfyUI 风格激光卷帘对比大屏**：[http://localhost:8899/curtain_compare.html](http://localhost:8899/curtain_compare.html)

### 姿势二：显式 Slash 指令
```bash
/graphify-jev                           # 全量建图并自动生成带《Jev健康雷达》的 GRAPH_REPORT.md
/graphify-jev navigate                  # 快速扫描核心枢纽健康度并拉起战情大屏
/graphify-jev navigate <symbol>         # 提取指定上帝节点的调用切片并开具备选代码处方
```

### 姿势三：后台驱动 CLI 指令 (供 Agent 或高级极客使用)
```bash
graphify-jev extract --code-only <path> # 本地 AST 建图 (位置无关参数)
graphify-jev audit <path> --top 20      # 终端直出红绿健康雷达卡片
graphify-jev audit <path> --json        # Agent 结构化诊断输出
graphify-jev serve <path> --port 8899   # 本地一键拉起战情与卷帘对比大屏服务
```

---

## 🎨 视觉与工程设计原则 (Design Principles)
本项目严格执行不可动摇的视觉美学与性能标准（详细见 [docs/VISUAL-DESIGN-STANDARD.md](docs/VISUAL-DESIGN-STANDARD.md)）：
1. **单一 Canvas 架构**：彻底抛弃双图表实例同步方案，采用原生单 Canvas 物理视口，60 FPS 丝滑长按拖拽平移与滚轮锚点缩放，1000% 绝对镜像同频，绝无黑屏或漂移；
2. **双层嵌套立体小球**：外层高亮发光环包裹内胆实色，呈现饱满圆润的水滴质感；严格控制黄金呼吸间距，杜绝大球挤贴；
3. **纯净无箭头微弧光轨**：0 粗糙箭头，二次贝塞尔微弯光轨（`curveness: 0.12`）；
4. **100% 全量标签覆盖与字色区分**：所有节点无一遗漏标注函数名，Before 统一粉红/红字，After 统一清新翠绿字；
5. **交互意图分流**：长按拖动（位移 > 3px）漫游无限画布；原地短按单击（位移 < 3px）定格画卷，光标自由移出悬停节点查阅详情。

---

## 🛡️ 工业级纪律保障
- **严格 Fail-Open**：未配置 API Key 或网络离线时，100% 优雅降级为纯拓扑启发式分析，绝不阻断建图与查询服务；
- **零隐私泄露**：出站请求仅包含代码符号签名与文件路径元数据，严禁发送源码实现细节；
- **零重型新依赖**：决策层纯基于 Python 标准库 `urllib` 实现，拒绝引入重型第三方包。

---

## 📄 开源许可证
本项目遵循 [Apache-2.0](LICENSE) 开源许可证。
欢迎 Star ⭐️ 关注独立演进版本！
