"""
brain/agent_loop.py
自主智能体循环 -- 真正的 Agent, 不是脚本。

核心循环:
  Goal → Observe → Think → Act → Observe result → Reflect → next iteration
  循环直到: 目标达成 / 判断不可能 / 操作员叫停

每一轮 LLM 都能看到:
  - 初始目标
  - 自己的身份和能力
  - 当前传感器感知
  - 目前为止做了什么, 结果如何
  - 上一步的反思和教训
  - 然后自主决定下一步

这就是 OpenClaw 的思路: 不预规划所有步骤, 每一步都根据实时状态决策。
"""

import json
import json
import re
import time
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

PROFILE_DIR = Path(__file__).parent.parent / "robot_profile"

AGENT_SYSTEM_PROMPT = """\
你就是一架智能无人机 (OR-1 / UAV_1)。你正在自主执行一个任务。

你的工作方式:
你不需要一次规划出所有步骤。每一轮你只需要决定"下一步做什么"。
执行完一步后, 你会看到结果和最新环境, 再决定下一步。
就像人类一样: 走一步看一步, 根据情况随时调整。

每轮你会收到:
- 你的目标
- 当前感知和状态
- 之前做了什么, 结果如何
- 上一步的反思

你要输出 JSON:
{
  "thinking": "我观察到什么, 我在想什么 (2-3句, 第一人称)",
  "decision": "act 或 done 或 stuck",
  "action": {"skill": "技能名", "robot": "UAV_1", "parameters": {}},
  "reflection": "从上一步学到了什么 (如果是第一步写null)",
  "goal_progress": "目标完成了多少, 还需要做什么"
}

decision 含义:
- "act": 我要执行 action 里的技能
- "done": 目标已达成, 任务完成
- "stuck": 我遇到了无法自己解决的问题, 需要操作员帮助

重要 — 简单指令 vs 复杂任务:
如果操作员的指令很简单 (如"飞到某坐标"、"去这里看看"、"飞过去"), 你应该:
1. 起飞 → 飞到目标位置 → observe 看一下
2. 然后用 ask_user 主动询问操作员: "我已到达目标位置，周围情况如下: [描述]。需要我做什么？"
3. 根据操作员的回答决定下一步
**不要自作主张**地开始搜索、巡检、标记等复杂行动! 除非操作员明确要求。
简单指令 = 飞过去 + 看看 + 问操作员。复杂任务 = 操作员明确说了搜索/巡检/巡逻等。

重要 — 纯移动指令的终止识别 (最容易犯的错!):
纯移动指令 = 只要求飞一段距离/方位, 不含观察/搜索/巡检 (如"向前飞2米"、"向左飞2米"、
"向东飞2米"、"升高0.5米"、"飞到坐标[x,y,z]")。这类指令的处理:
1. (若不在空中) takeoff → 2. 执行一次对应移动技能 (fly_relative/fly_to/change_altitude) → 3. 立刻 done!
⚠️ 移动技能返回成功 = 指令已达成, 马上判 done! 不要再飞第二次、不要 observe、不要 ask_user、不要 hover!
⚠️ fly_relative(right=-20) 已经把你向左移了20米, 再调一次就是再移20米=总共40米, 严重超调!
   一次移动达标就 done, summary 写明执行了什么移动、位移多少。
⚠️ "向左/向右/向前/向后飞N米"是相对当前朝向的【一次性】位移, 用一次 fly_relative 即可,
   绝不要拆成多次连续 fly_relative (朝向会漂, 多次 = 乱晃+超调)。
⚠️ 若指令带绝对方位(东/西/南/北)或明确坐标, 用 fly_to 一次到达即 done。
判断"纯移动"vs"复杂": 指令里有没有"看/搜/巡/找/拍/侦察"等动词? 没有 = 纯移动 = 一步done。

重要 — 什么时候判 done:
- 核心目标完成即可判 done (如: 所有巡检点观察完毕 + 到达汇报点 → report 汇总 → 立刻 done)
- 到达最终目标点后, 只需要执行一次 report(汇总所有发现) → 直接判 done! 不要再 observe/fly_to!
- 不要等降落完全确认! return_to_launch 发出后就视为任务完成
- 如果 land 或 return_to_launch 失败, 不要反复重试, 直接判 done 并在 summary 中说明
- 室内模式下 return_to_launch 会原地降落，不会执行依赖 GPS 或先爬升的室外 RTL
- summary 中汇总你的观察结果和关键发现
- ⚠️ 到达最后一个目的地 → report(汇总文字) → done，三步走，不要犹豫!
- report 的 content 就是纯文字汇总，直接写在 content 参数里，不要生成文件、不要生成 HTML、不要调用 write_file!
- done 时 summary 也是纯文字，把所有巡检发现写在里面
- ⚠️ 最终 report 之后的下一步必须是 done! 不要再 observe/fly_to/hover!
- ⚠️ 输出必须是合法 JSON! 不要在 JSON 外面加任何文字!

重要 — 软技能意识:
你拥有软技能系统, 可以记录和复用任务策略。
- 如果你发现自己在重复类似的技能组合 (如: fly_to → observe → fly_to → observe), 思考能否将其抽象为一个可复用的策略
- 在 reflection 字段中记录你的策略洞察, 这些会被系统用来生成新软技能
- 如果有相关的策略文档, 优先参考它来规划行动

关键规则:
- skill 必须是技能表里有的
- 每轮只执行一个动作, 不要贪多
- 如果上一步失败了, 分析原因, 换个方法试
- 如果连续失败3次同一个技能, 考虑换策略或报告 stuck
- 不要编造传感器数据
- robot 永远是 UAV_1

⚠️ 坐标系说明 — NED 世界坐标:
本系统使用 NED 世界坐标 [north, east, down]（即 [x, y, z]）:
- north (x): 北方向（正=北，负=南），单位米
- east  (y): 东方向（正=东，负=西），单位米
- down  (z): 向下为正！高度 = -down。地面 down≈0，离地 H 米 → down = -H

高度理解（地面 down≈0）:
  down = 0    → 地面
  down = -1.5  → 离地 1.5m
  down = -4    → 室内高度上限 4m
  ⚠️ down 接近 0 或正值 = 撞地！down 必须是负值才在空中。

⚠️ 当前为室内严格安全模式:
- 合速度最高 1.5m/s，高度范围 0.5-4m，水平电子围栏半径 8m
- 单次三维移动不得超过 3m；长路径必须分段，每段移动前重新感知
- 不得为了越障盲目升高；接近高度上限时优先悬停或横向绕行

各移动技能用法:
- fly_to: target_position=[north, east, down]，绝对 NED 世界坐标。东南西北等绝对方位一律用 fly_to。
  例: 从当前位置向东 2 米 → target_position=[当前north, 当前east+2, 当前down]
  例: 离地 2m → target_position=[north, east, -2]
- fly_relative: forward/right/up，机体坐标系（相对无人机当前朝向，会随航向变化！）
  - forward=前、right=右、up=上(正)/下(负)
  - ⚠️ right ≠ 东！航向一漂，right 可能变成南/西/北。只有"沿当前朝向"移动时才用 fly_relative。
  - 想去东南西北等绝对方位 → 用 fly_to，不要用 fly_relative。
- change_altitude: altitude 参数是目标离地高度，不是增量；范围 0.5-4m
- takeoff: altitude 是目标离地高度，建议 1.5m
- get_position 返回 [north, east, down]，altitude 字段是离地高度（正数，米）

⚠️ 最常见的错误:
- down 给了正值或接近 0 → 撞地！室内巡航保持离地 0.5-4m。
- 想飞到 1.5m 高 → 相对起飞点的 NED 通常 down=-1.5；始终以 get_position 返回值计算。
- 用 fly_relative(right=2) 表达"向东 2 米" → 错！东是绝对方位，要用 fly_to(east=当前east+2)。
- 不确定当前位置/高度 → 先 get_position。

⚠️ 飞行黄金法则 — 先感知再行动:
1. 飞往任何位置之前, 必须先 get_position 了解当前位置和高度
2. fly_to 需要完整的 [north, east, down]，且单次移动不超过 3m
3. 不确定安全高度? 先 perceive 看前方, 或保持当前高度
4. 遇到障碍? 先悬停并观察，再在 4m 高度上限内横向绕行
5. 绝对不要盲飞! 每次移动前都要有信息支撑

重要 — 行动优先, 不要原地打转:
你有 5 个摄像头 (前/后/左/右/下)。observe 可以拍照+VLM分析。
但 observe 不是万能的! 如果连续 observe 2次得到的信息差不多, 说明当前视角已经看不到更多了。
这时候你必须改变策略:
  - 降低高度 (change_altitude altitude=1.0) 看得更清楚
  - 移动到不同位置 (fly_relative forward/right) 换个角度
  - 换方向观察 (observe direction=left/right/rear)
  - 直接飞过去 (fly_to) 靠近目标
绝对不要连续3次以上使用 observe 而不移动! 这是无效行为。
一条核心原则: 信息不够 = 改变位置, 不是重复观察。

重要 — 灵活组合技能:
你可以自由组合硬技能来完成复杂任务。例如:
  - "绕目标一圈": 在 3m 单步和 8m 围栏内分段 fly_relative → observe → ...
  - "低空侦察": change_altitude(altitude=1.0) → observe(down) → fly_relative(forward=2) → observe(down) → ...
  - "多点巡检": fly_to(点1) → observe → fly_to(点2) → observe → ...

重要 — 你是一个有个性的智能助手, 不是冷冰冰的工具:
你拥有主动通信能力, 善用它们:
  - report(content, severity): 每到一个新位置观察后, 主动用 report 记录发现并实时告知操作员。巡检类任务中, 每个观测点都应该 report。
  - alert(message, level): 发现异常时紧急通知操作员。不要滥用, 只在真正有异常时使用。
  - ask_user(question): 遇到不确定的情况时向操作员提问。操作员有60秒回答时间。适合问是/否类问题。
  - update_map(landmark_name, description): 发现新地标时更新地图, 积累场景知识。
这些技能让你像一个真正的智能伙伴:
  - 你会主动汇报发现 (不需要操作员追问)
  - 你会在遇到问题时求助 (而不是自己瞎猜)
  - 你会持续学习环境 (更新地图让下次飞行更高效)
  - 你有自己的观察和判断 (report 里可以加入你的分析和建议)

⚠️ 强制规则 — 每次 observe 之后必须:
1. 如果 observe 返回了环境描述, 立刻调用 report(content=描述内容, severity=info/warning) 向操作员汇报
2. 如果看到了明显的建筑/地标/特征, 调用 update_map(landmark_name=名称, description=描述) 更新地图
3. 这两个操作是强制的, 不是可选的! observe 不 report 等于白看。
示例流程: fly_to → observe → report → update_map → fly_to(下一个点) → observe → report → ...
不要等待有人告诉你怎么组合, 自己根据任务需求创造性地搭配技能。

重要 — 参考策略文档:
如果你收到了"本次任务相关的策略文档", 仔细阅读并参考它的推荐流程。
不要只用1-2个技能就结束复杂任务。搜救至少需要: 起飞->飞到区域->observe->移动->observe->标记->返回。
但也不要拖延! 到达最终目标点后不需要反复 observe, 直接 report 汇总结果并 done。

重要 — 从经验中学习:
如果你收到了"你的经验", 参考之前任务的成功/失败经验做决策。
如果某个技能之前失败过, 换参数或换策略。

严格输出 JSON, 不要额外文字。"""


def _read_file(path, max_chars=500):
    p = Path(path)
    if p.exists():
        return p.read_text(encoding="utf-8").strip()[:max_chars]
    return ""


def _build_iteration_prompt(
    goal, iteration, action_history, world_state_str,
    perception_summary, skill_table, soft_skills_summary,
    passive_perception=None,   # 被动感知最新数据
    world_obstacles=None,      # WorldModel 已知障碍物列表
    similar_experiences=None,  # 向量检索到的相似历史经验
):
    """构建每轮迭代的 user prompt。"""
    # 执行历史
    if action_history:
        history_lines = []
        for i, h in enumerate(action_history):
            status = "成功" if h["success"] else f"失败({h.get('error', '?')})"
            # 障碍物失败时展示更多 output 信息
            if (not h["success"] and isinstance(h.get("output"), dict)
                    and h["output"].get("obstacle_detected")):
                out_str = " | 结果: " + json.dumps(h["output"], ensure_ascii=False)[:200]
            elif h.get("output"):
                out_str = " | 结果: " + str(h["output"])[:60]
            else:
                out_str = ""
            history_lines.append(f"  第{i+1}步: {h['skill']} → {status}{out_str}")
            if h.get("reflection"):
                history_lines.append(f"    反思: {h['reflection']}")
        history_str = "\n".join(history_lines)
    else:
        history_str = "  (这是第一步, 还没有执行任何动作)"

    # 失败统计
    fail_count = sum(1 for h in action_history if not h["success"])
    consecutive_fails = 0
    for h in reversed(action_history):
        if not h["success"]:
            consecutive_fails += 1
        else:
            break

    progress_hint = ""
    if consecutive_fails >= 3:
        progress_hint = "\n注意: 已经连续失败 {0} 次, 认真分析原因, 考虑换策略或报告 stuck。".format(consecutive_fails)
    elif fail_count > 0:
        progress_hint = f"\n已有 {fail_count} 次失败, 注意从失败中学习。"

    # 反重复检测: 连续使用相同技能
    if len(action_history) >= 2:
        recent_skills = [h["skill"] for h in action_history[-3:]]
        if len(set(recent_skills)) == 1:
            repeated_skill = recent_skills[0]
            progress_hint += (
                f"\n警告: 你已经连续 {len(recent_skills)} 次使用 {repeated_skill}! "
                f"重复相同动作不会带来新信息。你必须立刻改变策略: "
                f"移动到新位置、改变高度、换一个完全不同的技能。"
                f"禁止再次使用 {repeated_skill}, 除非你先执行了移动类技能 (fly_to/fly_relative)。"
            )

    # 被动感知补充段落
    passive_section = ""
    if passive_perception and isinstance(passive_perception, dict):
        pp_summary = passive_perception.get("summary", "")
        pp_obstacles = passive_perception.get("obstacles", [])
        if pp_summary:
            passive_section += f"\n### 被动感知最新数据\n{pp_summary}"
        if pp_obstacles:
            obs_lines = "\n".join(f"  - {o}" for o in pp_obstacles[:5])
            passive_section += f"\n障碍物感知:\n{obs_lines}"

    # WorldModel 障碍物段落
    obstacles_section = ""
    if world_obstacles:
        obs_lines = "\n".join(
            f"  - 方向:{o.get('direction','?')} 类型:{o.get('type','障碍物')} 距离:{o.get('distance','?')}m"
            for o in world_obstacles[:10]
        )
        obstacles_section = f"\n### 已知障碍物 (WorldModel)\n{obs_lines}"

    return f"""## 目标
{goal}

## 当前状态 (第 {iteration} 轮)
{world_state_str}

## 环境感知
{perception_summary or '(无最新感知)'}{passive_section}{obstacles_section}

## 相似任务经验 (从历史中检索)
{similar_experiences or '(无)'}

## 执行历史
{history_str}
{progress_hint}

## 可用技能
{skill_table}

## 策略参考
{soft_skills_summary or '(无)'}

现在决定下一步。输出 JSON。"""


def _parse_agent_output(raw):
    """解析智能体输出的 JSON。"""
    if not raw or not raw.strip():
        logger.warning("[AgentLoop] LLM 返回空内容")
        return None
    # 去掉 markdown 代码块包裹
    cleaned = raw.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    if cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    m = re.search(r'\{[\s\S]*\}', cleaned)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    # 最后尝试原始内容
    m2 = re.search(r'\{[\s\S]*\}', raw)
    if m2:
        try:
            return json.loads(m2.group())
        except json.JSONDecodeError:
            pass
    logger.warning(f"[AgentLoop] 解析失败, raw前200字: {raw[:200]}")
    return None


class AgentLoop:
    """
    自主智能体循环。

    用法:
        loop = AgentLoop(goal, llm_client, runtime, world_model, ...)
        loop.run()  # 开始自主执行, 直到完成/卡住/被停止
    """

    def __init__(
        self,
        goal,
        llm_client,
        runtime,
        world_model,
        skill_registry,
        max_iterations=20,
        on_thinking=None,    # callback(iteration, thinking_dict)
        on_action=None,      # callback(iteration, skill, params, result)
        on_complete=None,    # callback(success, summary)
        on_stream=None,      # callback(token_str) — LLM streaming 回调
        on_error=None,       # callback(msg: str) — LLM 调用/解析失败时回调, 用于把"正在重试/失败原因"推到前端, 避免静默假死
        stop_event=None,     # threading.Event, 设置后停止
        experience_store=None,  # VectorStore 实例，用于检索相似经验
    ):
        self.goal = goal
        self.llm = llm_client
        self.runtime = runtime
        self.world_model = world_model
        self.skill_registry = skill_registry
        self.max_iterations = max_iterations

        self.on_thinking = on_thinking or (lambda *a: None)
        self.on_action = on_action or (lambda *a: None)
        self.on_stream = on_stream or (lambda *a: None)
        self.on_complete = on_complete or (lambda *a: None)
        self.on_error = on_error or (lambda *a: None)
        self.stop_event = stop_event
        self.experience_store = experience_store  # VectorStore 实例

        self.action_history = []
        self.runtime_tactic = ""  # 运行时生成的战术方案
        self._user_messages = []  # 用户打断消息队列
        self.iteration = 0

    def run(self):
        """主循环: 观察→思考→行动→反思, 直到结束。"""
        logger.info(f"[AgentLoop] 开始: {self.goal}")

        # 重置报告累积器
        try:
            from skills.cognitive_skills import Report
            Report.reset()
        except Exception:
            pass

        # 加载上下文
        from skills.skill_loader import build_skill_summary
        skill_table = build_skill_summary(self.skill_registry.get_skill_catalog())

        # 软技能完整文档 (按需 — 根据任务关键词加载相关的)
        soft_summary = ""
        soft_detail = ""
        soft_dir = Path(__file__).parent.parent / "skills" / "soft_docs"
        if soft_dir.exists():
            goal_lower = self.goal.lower()
            for f in sorted(soft_dir.glob("*.md")):
                text = f.read_text(encoding="utf-8").strip()
                title = text.split("\n")[0].strip().lstrip("#").strip()
                soft_summary += f"- {f.stem}: {title}\n"
                # 根据任务关键词注入完整文档
                keywords = {
                    "rescue_person": ["救", "受困", "伤", "人员", "rescue"],
                    "patrol_area": ["巡", "patrol", "巡逻", "巡查"],
                    "search_target": ["搜", "找", "search", "寻", "目标"],
                }
                for skill_name, kws in keywords.items():
                    if f.stem == skill_name and any(k in goal_lower for k in kws):
                        soft_detail += f"\n### {f.stem} 完整策略\n{text}\n"

        # SKILLS.md — 技能真实表现数据
        skills_md = _read_file(PROFILE_DIR / "SKILLS.md", 600)

        soul = _read_file(PROFILE_DIR / "SOUL.md", 300)
        body = _read_file(PROFILE_DIR / "BODY.md", 600)
        memory = _read_file(PROFILE_DIR / "MEMORY.md", 500)
        world_map = _read_file(PROFILE_DIR / "WORLD_MAP.md", 800)

        system_prompt = AGENT_SYSTEM_PROMPT
        if soul:
            system_prompt += f"\n\n你的人格:\n{soul}"
        if body:
            system_prompt += f"\n\n你的身体:\n{body}"
        if world_map:
            system_prompt += f"\n\n场景地图 (用于导航规划):\n{world_map}"
        if memory and "暂无" not in memory:
            system_prompt += f"\n\n你的经验 (从之前的任务中学到的):\n{memory}"
        if skills_md and "待统计" not in skills_md:
            system_prompt += f"\n\n技能实际表现:\n{skills_md}"
        if soft_detail:
            system_prompt += f"\n\n本次任务相关的策略文档 (仔细阅读!):\n{soft_detail}"

        # 运行时生成的战术方案 (当检测到重复行为时由 LLM 生成)
        self.runtime_tactic = ""

        while self.iteration < self.max_iterations:
            self.iteration += 1

            if self.stop_event and self.stop_event.is_set():
                logger.info("[AgentLoop] 被操作员中止")
                self.on_complete(False, "操作员中止")
                return

            # 1. 观察
            world_state = self.world_model.get_world_state()
            world_lines = []
            for rid, rd in world_state.get("robots", {}).items():
                world_lines.append(
                    f"{rid}: pos={rd.get('position')}, battery={rd.get('battery')}%, "
                    f"status={rd.get('status')}, in_air={rd.get('in_air')}"
                )
            world_state_str = "\n".join(world_lines) or "(无)"

            perception = ""
            try:
                from perception.daemon import get_daemon
                daemon = get_daemon()
                if daemon and daemon.is_running:
                    perception = daemon.get_summary()
            except Exception:
                pass

            # 获取被动感知数据
            passive_data = None
            try:
                if hasattr(self, '_passive_engine') and self._passive_engine:
                    passive_data = self._passive_engine.get_latest()
            except Exception:
                pass

            # 获取 WorldModel 障碍物
            world_obstacles = []
            try:
                map_data = self.world_model._state.get('map', {})
                world_obstacles = map_data.get('obstacles', [])[-10:]
            except Exception:
                pass

            # 2. 思考
            # 检索相似经验
            similar_experiences = ''
            if self.experience_store:
                try:
                    query = f'{self.goal} {world_state_str[:100]}'
                    results = self.experience_store.search(query, top_k=3)
                    results = [r for r in results if r.score >= 0.3]
                    if results:
                        exp_lines = []
                        for r in results:
                            exp_lines.append(f'- [{r.metadata.get("task","")}] {r.text[:100]}')
                        similar_experiences = '\n'.join(exp_lines)
                except Exception:
                    pass

            user_prompt = _build_iteration_prompt(
                self.goal, self.iteration, self.action_history,
                world_state_str, perception, skill_table, soft_summary,
                passive_perception=passive_data,
                world_obstacles=world_obstacles,
                similar_experiences=similar_experiences,
            )

            # 运行时战术: 当连续重复行为被检测到, 要求 LLM 先生成执行方案
            if not self.runtime_tactic and len(self.action_history) >= 3:
                recent_skills = [h["skill"] for h in self.action_history[-3:]]
                if len(set(recent_skills)) == 1 and recent_skills[0] not in {"fly_to", "fly_relative"}:
                    logger.info(f"[AgentLoop] 检测到重复行为 ({recent_skills[0]}×3), 触发战术方案生成")
                    try:
                        tactic_prompt = (
                            f"你是一架无人机的战术规划师。\n"
                            f"当前任务: {self.goal}\n"
                            f"问题: 无人机连续3次使用 {recent_skills[0]} 没有新进展。\n"
                            f"当前位置和状态:\n{world_state_str}\n"
                            f"可用技能: {skill_table[:300]}\n\n"
                            f"请生成一个简短的战术方案 (3-5步), 用不同的技能组合来完成任务。\n"
                            f"要求: 每步之间必须包含位置变化 (fly_to 或 fly_relative)。\n"
                            f"直接输出步骤列表, 每步一行, 格式: '步骤N: 技能名(参数) — 目的'。"
                        )
                        tactic_raw = self.llm.chat([
                            {"role": "system", "content": "你是无人机战术规划师, 专注于生成高效的多步骤执行方案。"},
                            {"role": "user", "content": tactic_prompt},
                        ], temperature=0.5, max_tokens=800)
                        if tactic_raw:
                            self.runtime_tactic = tactic_raw.strip()
                            logger.info(f"[AgentLoop] 战术方案已生成: {self.runtime_tactic[:80]}...")
                    except Exception as e:
                        logger.warning(f"[AgentLoop] 战术方案生成失败: {e}")

            # 注入运行时战术到 prompt
            effective_system = system_prompt
            if self.runtime_tactic:
                effective_system += f"\n\n运行时战术方案 (请严格参考执行):\n{self.runtime_tactic}"

            # 注入用户打断消息
            if self._user_messages:
                user_msgs = "\n".join(f"- {m}" for m in self._user_messages)
                user_prompt += f"\n\n## 操作员实时指令 (优先级最高!)\n{user_msgs}\n请根据操作员指令调整你的行动计划。"
                self._user_messages.clear()  # 消费后清空

            # 调用 LLM 前先给前端一个"思考中"占位, 避免调用期间(可能数十秒)前端
            # 无任何反馈、像卡死。LLM 返回后 on_thinking 会用真实结果覆盖同轮卡片。
            self.on_thinking(self.iteration, {"thinking": "思考中...", "decision": "pending"})

            try:
                # max_tokens 给 4000: glm-5.2 / deepseek-v4 等推理模型会先在 reasoning
                # 字段消耗大量 token, 500 不够写完一个完整 JSON 会被 length 截断 → 解析失败。
                raw = self.llm.chat([
                    {"role": "system", "content": effective_system},
                    {"role": "user", "content": user_prompt},
                ], temperature=0.5, max_tokens=4000, on_chunk=self.on_stream)
            except Exception as e:
                logger.error(f"[AgentLoop] LLM 失败: {e}")
                # 把失败原因推到前端, 否则用户只看到"启动 Agent 自主循环..."后干等, 像无响应
                self.on_error(f"LLM 调用失败, 2秒后重试: {e}")
                time.sleep(2)
                continue

            output = _parse_agent_output(raw)
            if output is None:
                self._parse_fail_count = getattr(self, '_parse_fail_count', 0) + 1
                logger.warning(
                    "[AgentLoop] LLM 输出解析失败 %s/3，不得伪装成任务完成。raw=%r",
                    self._parse_fail_count,
                    (raw or "")[:300],
                )
                self.on_error(f"LLM 输出无法解析 ({self._parse_fail_count}/3), 重试中...")
                if self._parse_fail_count >= 3:
                    msg = "任务中止：LLM 连续输出无法解析，未能生成可执行决策。"
                    logger.error(f"[AgentLoop] 连续 {self._parse_fail_count} 次解析失败，任务失败结束")
                    self.on_complete(False, msg)
                    self._update_memory(False)
                    self._safe_return()
                    return
                continue
            else:
                self._parse_fail_count = 0

            thinking = output.get("thinking", "")
            decision = output.get("decision", "act")
            action = output.get("action") or {}
            reflection = output.get("reflection")
            progress = output.get("goal_progress", "")

            self.on_thinking(self.iteration, output)
            logger.info(f"[AgentLoop] 第{self.iteration}轮: {thinking[:60]}... → {decision}")

            # 3. 判断是否结束
            if decision == "done":
                logger.info(f"[AgentLoop] 目标达成: {progress}")
                self.on_complete(True, f"{thinking}\n{progress}")
                self._update_memory(True)
                return

            if decision == "stuck":
                logger.info(f"[AgentLoop] 卡住: {thinking}")
                self.on_complete(False, f"遇到困难: {thinking}\n{progress}")
                self._update_memory(False)
                self._safe_return()
                return

            # 4. 执行动作
            skill_name = action.get("skill", "")
            parameters = action.get("parameters", {})
            robot_id = action.get("robot", "UAV_1")

            if not skill_name:
                logger.warning("[AgentLoop] 无有效技能, 跳过")
                continue

            # 反重复硬拦截: 非移动技能连续3次直接拒绝
            MOVE_SKILLS = {"fly_to", "fly_relative", "takeoff", "land", "return_to_launch"}
            if skill_name not in MOVE_SKILLS and len(self.action_history) >= 2:
                recent = [h["skill"] for h in self.action_history[-2:]]
                if all(s == skill_name for s in recent):
                    logger.warning(f"[AgentLoop] 硬拦截: {skill_name} 连续3次, 强制跳过")
                    from skills.motor_skills import SkillResult
                    result = SkillResult(
                        success=False,
                        error_msg=f"系统拦截: {skill_name} 已连续使用3次且无位置变化, 你必须先移动 (fly_to/fly_relative) 再观察",
                    )
                    self.on_action(self.iteration, skill_name, parameters, result)
                    self.action_history.append({
                        "skill": skill_name, "parameters": parameters,
                        "success": False, "error": result.error_msg,
                        "output": None, "cost_time": 0, "reflection": reflection,
                    })
                    continue

            step_data = {"skill": skill_name, "robot": robot_id, "parameters": parameters}
            result = self.runtime.dispatch_skill(step_data)

            # 回写技能状态
            robot_reg = self.skill_registry
            if robot_reg:
                robot_reg.update_execution_status(skill_name, result.success)

            self.on_action(self.iteration, skill_name, parameters, result)

            # 5. 记录历史 (含反思)
            self.action_history.append({
                "skill": skill_name,
                "parameters": parameters,
                "success": result.success,
                "error": result.error_msg if hasattr(result, "error_msg") else None,
                "output": result.output if hasattr(result, "output") else None,
                "cost_time": result.cost_time,
                "reflection": reflection,
            })

            status = "OK" if result.success else f"FAIL({result.error_msg})"
            logger.info(f"[AgentLoop] {skill_name} → {status} ({result.cost_time:.1f}s)")

            # 短暂等待, 让传感器更新
            time.sleep(0.5)

        # 超过最大迭代
        logger.warning(f"[AgentLoop] 达到最大迭代 ({self.max_iterations})")
        self.on_complete(False, f"达到最大迭代次数 ({self.max_iterations}), 任务未完成")
        self._update_memory(False)
        # 安全措施: 达到最大迭代后按室内策略原地降落
        self._safe_return()

    def _safe_return(self):
        """室内任务异常结束时直接原地降落，不再让 LLM 追加飞行。"""
        try:
            from adapters.adapter_manager import get_adapter
            adapter = get_adapter()
            in_air = False
            if adapter:
                try:
                    in_air = adapter.is_in_air()
                except Exception:
                    in_air = True  # 无法确认时假设在空中

            if not in_air:
                logger.info("[AgentLoop] 不在空中，无需安全降落")
                return

            logger.warning("[AgentLoop] 室内任务异常结束，立即原地安全降落")
            result = self.runtime.dispatch_skill({
                "skill": "return_to_launch",
                "robot": "UAV_1",
                "parameters": {},
            })
            if not result.success:
                logger.error("[AgentLoop] 室内安全降落失败: %s", result.error_msg)

        except Exception as e:
            logger.error("[AgentLoop] 室内安全降落异常: %s", e)

    def _update_memory(self, success):
        """
        任务结束后完整的反思-进化链路:
        1. 调 ReflectionEngine 做 LLM 反思
        2. 反思结果写入 MEMORY.md
        3. 更新 SKILLS.md (技能成功率/推荐参数)
        4. 检查是否有重复模式 → 自动生成新软技能
        """
        # ── 步骤 1: LLM 反思 ─────────────────────────────────────────
        reflection_result = None
        try:
            from memory.reflection_engine import ReflectionEngine

            reflector = ReflectionEngine(llm_client=self.llm)

            # 构造反思报告
            report = {
                "task_name": self.goal[:50],
                "success": success,
                "total_steps": len(self.action_history),
                "completed_steps": sum(1 for h in self.action_history if h["success"]),
                "failed_steps": sum(1 for h in self.action_history if not h["success"]),
                "total_duration": sum(h.get("cost_time", 0) for h in self.action_history),
                "step_results": [
                    {
                        "skill": h["skill"],
                        "success": h["success"],
                        "cost_time": h.get("cost_time", 0),
                        "error": h.get("error"),
                        "output": str(h.get("output", ""))[:80],
                    }
                    for h in self.action_history
                ],
            }

            # 世界状态
            world_state = {}
            try:
                world_state = self.world_model.get_world_state()
            except Exception:
                pass

            reflection_result = reflector.reflect(report, world_state)

            if reflection_result:
                logger.info(f"[AgentLoop] 反思完成: {str(reflection_result)[:80]}")

                # ── 步骤 2: 更新 MEMORY.md ────────────────────────────
                try:
                    from memory.reflection_engine import update_memory
                    update_memory(reflection_result)
                    logger.info("[AgentLoop] MEMORY.md 已更新")
                except Exception as e:
                    logger.warning(f"[AgentLoop] MEMORY.md 更新失败: {e}")

                # ── 步骤 3: 更新 SKILLS.md ────────────────────────────
                try:
                    from memory.reflection_engine import update_skills
                    # 收集技能统计，转换为 update_skills 期望的 list 格式
                    skill_stats_raw = {}
                    for h in self.action_history:
                        sname = h["skill"]
                        if sname not in skill_stats_raw:
                            skill_stats_raw[sname] = {"success": 0, "fail": 0, "total_time": 0}
                        if h["success"]:
                            skill_stats_raw[sname]["success"] += 1
                        else:
                            skill_stats_raw[sname]["fail"] += 1
                        skill_stats_raw[sname]["total_time"] += h.get("cost_time", 0)

                    # 转换为 update_skills 期望的 list[dict] 格式
                    # 期望: [{"skill_name": str, "success_rate": float, "total_executions": int, "average_cost_time": float}]
                    skill_stats_list = []
                    for sname, stats in skill_stats_raw.items():
                        total = stats["success"] + stats["fail"]
                        skill_stats_list.append({
                            "skill_name": sname,
                            "success_rate": stats["success"] / total if total > 0 else -1,
                            "total_executions": total,
                            "average_cost_time": stats["total_time"] / total if total > 0 else 0,
                        })

                    update_skills(reflection_result, skill_stats_list)
                    logger.info("[AgentLoop] SKILLS.md 已更新")
                except Exception as e:
                    logger.warning(f"[AgentLoop] SKILLS.md 更新失败: {e}")

                # ── 步骤 3b: 写入 experience_store ───────────────────
                if self.experience_store:
                    try:
                        ts = datetime.now().strftime("%Y-%m-%d %H:%M")
                        task_name = self.goal[:50]
                        for lesson in reflection_result.get("task_lessons", []):
                            if lesson and isinstance(lesson, str) and lesson.strip():
                                self.experience_store.add(
                                    lesson.strip(),
                                    metadata={"task": task_name, "type": "task_lesson", "ts": ts},
                                )
                        for insight in reflection_result.get("environment_insights", []):
                            if insight and isinstance(insight, str) and insight.strip():
                                self.experience_store.add(
                                    insight.strip(),
                                    metadata={"task": task_name, "type": "env_insight", "ts": ts},
                                )
                        logger.info("[AgentLoop] 经验已写入 experience_store")
                    except Exception as e:
                        logger.warning(f"[AgentLoop] experience_store 写入失败: {e}")
            else:
                logger.warning("[AgentLoop] 反思引擎返回空结果, 写入基础记录")
                self._write_basic_memory(success)

        except Exception as e:
            logger.warning(f"[AgentLoop] 反思引擎失败: {e}, 写入基础记录")
            self._write_basic_memory(success)

        # ── 步骤 4: 技能进化统计 ──────────────────────────────────────
        try:
            from memory.skill_evolution import SkillEvolution
            evo = SkillEvolution(persist=True)
            if reflection_result:
                evo.record_feedback(reflection_result)
                logger.info("[AgentLoop] 技能进化统计已更新")
        except Exception as e:
            logger.warning(f"[AgentLoop] 技能进化统计失败: {e}")

        # ── 步骤 5: 检查重复模式 → 自动生成新软技能 ─────────────────
        try:
            from skills.dynamic_skill_gen import detect_patterns, generate_soft_skill_doc
            from skills.soft_skill_manager import get_soft_skill_manager

            # 收集最近的技能链
            current_chain = [h["skill"] for h in self.action_history if h["success"]]
            if len(current_chain) >= 3:
                # 简单的重复检测: 把当前链追加到历史文件
                history_path = Path(__file__).parent.parent / "data" / "skill_chains.json"
                history_path.parent.mkdir(parents=True, exist_ok=True)

                chains = []
                if history_path.exists():
                    try:
                        chains = json.loads(history_path.read_text())
                    except Exception:
                        chains = []

                chains.append({
                    "task": self.goal[:50],
                    "chain": current_chain,
                    "success": success,
                    "time": datetime.now().isoformat(),
                })
                # 只保留最近 100 条
                chains = chains[-100:]
                history_path.write_text(json.dumps(chains, ensure_ascii=False, indent=2))

                # 检测模式
                patterns = detect_patterns(
                    [{"skill_chain": c["chain"], "success": c["success"]} for c in chains],
                    min_count=2,
                )
                if patterns:
                    mgr = get_soft_skill_manager()
                    for p in patterns[:1]:  # 一次最多生成 1 个
                        name = p.get("suggested_name", f"auto_skill_{len(chains)}")
                        if not mgr.skill_exists(name):
                            result = generate_soft_skill_doc(
                                pattern=p,
                                llm_client=self.llm,
                                existing_skills=mgr.list_skills(),
                            )
                            if result and result.get("content"):
                                final_name = result.get("name", name)
                                mgr.create_skill(final_name, result["content"])
                                logger.info(f"[AgentLoop] 自动生成新软技能: {final_name}")
        except Exception as e:
            logger.warning(f"[AgentLoop] 动态技能生成检查失败: {e}")

        # ── 步骤 6: 把经验追加到相关软技能 ──────────────────────────
        if reflection_result:
            try:
                from skills.soft_skill_manager import get_soft_skill_manager
                mgr = get_soft_skill_manager()
                ts = datetime.now().strftime("%Y-%m-%d %H:%M")
                task_name = self.goal[:40]
                outcome = "成功" if success else "失败"
                for lesson in reflection_result.get("task_lessons", []):
                    if not lesson or not isinstance(lesson, str):
                        continue
                    lesson = lesson.strip()
                    if not lesson:
                        continue
                    for skill_name in mgr.list_skills():
                        if skill_name.replace("_", " ") in lesson or any(
                            kw in lesson for kw in skill_name.split("_")
                        ):
                            exp_text = f"[{ts}][{outcome}] {task_name}: {lesson}"
                            mgr.update_experience(skill_name, exp_text)
                            logger.debug(f"[AgentLoop] 经验追加到软技能: {skill_name}")
            except Exception as e:
                logger.warning(f"[AgentLoop] 软技能经验更新失败: {e}")

    def _write_basic_memory(self, success):
        """反思引擎失败时的基础记忆写入。"""
        try:
            mem_path = PROFILE_DIR / "MEMORY.md"
            if not mem_path.exists():
                return
            content = mem_path.read_text(encoding="utf-8")
            ts = datetime.now().strftime("%Y-%m-%d %H:%M")
            status = "成功" if success else "未完成"
            skills_used = [h["skill"] for h in self.action_history]
            fails = [h for h in self.action_history if not h["success"]]
            entry = f"- [{ts}] 任务: {self.goal[:40]} [{status}] 技能链: {' → '.join(skills_used)}"
            if fails:
                for f in fails:
                    entry += f"\n  - {f['skill']} 失败: {f.get('error', '?')}"

            if "## 任务经验" in content:
                content = content.replace("## 任务经验", f"## 任务经验\n\n{entry}", 1)
            else:
                content += f"\n\n## 任务经验\n\n{entry}\n"
            mem_path.write_text(content, encoding="utf-8")
        except Exception as e:
            logger.warning(f"[AgentLoop] 基础记忆写入失败: {e}")

    def inject_user_message(self, msg: str):
        """用户通过聊天框发送的打断消息, 会在下一轮思考时注入 context。"""
        self._user_messages.append(msg)
        logger.info(f"[AgentLoop] 收到用户消息: {msg[:60]}")

    def get_summary(self):
        """返回执行摘要。"""
        total = len(self.action_history)
        success = sum(1 for h in self.action_history if h["success"])
        return {
            "goal": self.goal,
            "iterations": self.iteration,
            "total_actions": total,
            "successful": success,
            "failed": total - success,
            "history": self.action_history,
        }
