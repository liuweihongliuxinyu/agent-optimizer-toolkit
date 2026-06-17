# 预约 Agent 完整示例

> 优化前：预约时间冲突率 11%（同一时间段重复预约、医生已排满仍接受预约）
> 优化后：Pre-call Validation + Self-reflection → 冲突率降至 1.5%

---

## 一、工具列表（三段式）

### 工具1: book_appointment

#### 何时调用（What for）
- 用户明确说要预约、挂号、约时间
- 用户说"帮我安排一下""定个时间"

#### 不调边界（When not）
- 用户只是在咨询医生信息或医院地址
- 用户还没有选定医生或服务类型
- 用户说的时间是过去的时间

#### 参数示例
```json
{
  "user_id": "u_001",
  "service_type": "consultation",
  "doctor_id": "dr_zhang",
  "appointment_time": "2026-06-22T14:30:00",
  "duration_minutes": 30
}
```

#### 校验规则
```
- appointment_time 必须是未来时间
- 不能与用户已有预约冲突（同一用户不能在同一时段有2个预约）
- 医生该时段必须为空闲
- duration_minutes ≥ 15 且 ≤ 240
- service_type 必须在允许列表中
```

---

### 工具2: check_availability

#### 何时调用（What for）
- 预约前必须检查医生排期
- 用户问"张医生周三下午有空吗"

#### 不调边界（When not）
- 用户还没指定医生
- 用户还没指定大致时间段

#### 参数示例
```json
{
  "doctor_id": "dr_zhang",
  "date": "2026-06-22",
  "time_range": "afternoon"
}
```

---

### 工具3: check_user_schedule

#### 何时调用（What for）
- 预约前检查用户自己是否已有其他预约
- 用户说"看看我还有没有空档"

#### 不调边界（When not）
- 新用户（无历史预约记录）

#### 参数示例
```json
{
  "user_id": "u_001",
  "date": "2026-06-22"
}
```

---

## 二、完整交互示例

### 优化前（时间冲突）

```
用户: 帮我约下周三张医生的咨询

Agent: 好的。
  → book_appointment(user_id="u_001", doctor_id="dr_zhang",
       service_type="consultation",
       appointment_time="2026-06-22T14:00:00")
  → ✅ 预约成功！6月22日 14:00 张医生咨询

❌ 问题：用户在同一时段已有一个预约，两个预约时间重叠！
```

### 优化后（五技法全开）

```
用户: 帮我约下周三张医生的咨询

Thought: 用户要预约。
需要做以下检查（Pre-call Validation）：
1. 先查用户6/22是否已有预约 → check_user_schedule
2. 查张医生6/22下午的排期 → check_availability
3. 确认不冲突后再预约 → book_appointment

Step 1: 查用户日程
Action: check_user_schedule(user_id="u_001", date="2026-06-22")

Observation: {
  "existing_appointments": [
    {"time": "2026-06-22T10:00:00", "end": "2026-06-22T11:00:00",
     "doctor": "dr_li", "service": "checkup"}
  ]
}

Thought: 用户6/22已有10:00-11:00的检查预约。预约14:00没有冲突。

Step 2: 查医生排期
Action: check_availability(doctor_id="dr_zhang", date="2026-06-22")

Observation: {
  "available_slots": [
    "09:00-09:30", "11:00-11:30", "14:00-14:30",
    "14:30-15:00", "16:00-16:30"
  ]
}

Thought: 14:00-14:30 有空。
所有参数校验：
✅ appointment_time 是未来时间
✅ 用户该时段空闲（与10:00预约不冲突）
✅ 张医生14:00-14:30为空闲
✅ service_type="consultation" 在允许列表
✅ duration=30 在15-240范围

可以预约。

Step 3: 创建预约
Action: book_appointment(
  user_id="u_001",
  doctor_id="dr_zhang",
  service_type="consultation",
  appointment_time="2026-06-22T14:00:00",
  duration_minutes=30
)

Observation: {"booking_id": "BKG_001", "status": "confirmed"}

【自检】
✅ 完整性：已回答预约请求
✅ 正确性：所有校验通过
✅ 一致性：时间与用户日程和医生排期一致
✅ 冲突检测：无时间冲突 ✓
✅ 体验：可提醒用户当天有2个预约

最终回复:
预约成功！
📅 6月22日（周三）
🕑 14:00-14:30 — 张医生 咨询
🕙 10:00-11:00 — 李医生 检查（已有）

当天共2个预约，请注意时间安排。

---

## 三、另一种被 Self-reflection 拦截的场景

用户: 约张医生明天下午3点

[Agent 正常流程执行，但 check_availability 返回明天下午全部约满]

Observation: {"available_slots": ["08:00-08:30"]}  // 只有早上8点有空

Thought: 用户要下午，但下午无空位。

最终回复:
很抱歉，张医生明天下午已全部约满。目前仅剩：
- 早上 8:00-8:30

建议：
1. 接受明天早上8:00的时段
2. 换到后天（6月23日），张医生下午有多个空位
3. 换李医生，明天下午有空

您想怎么选？

【自检】
✅ 完整性：诚实告知无空位 + 提供替代方案
✅ 正确性：排期数据准确
✅ 体验：主动给出3个替代方案 ← 这就是 Self-reflection 带来的体验提升
```

---

## 四、关键设计点

### Self-reflection 在预约场景的特殊检查项

```
通用自检之外，预约场景额外检查：
1. 时间冲突检测：新预约 vs 用户已有预约 vs 医生已有预约
2. 服务时长合理性：咨询30分钟、手术2小时，不能反着来
3. 医生资质匹配：服务类型必须在医生的执业范围内
4. 提前预约限制：某些服务需要提前N天预约
5. 节假日检测：预约时间不能是医院休息日
```

### 冲突率为什么会从 11% 降到 1.5%？

```
11% 的冲突来源：
- 60%：未查用户已有预约就直接创建（Pre-call Validation 解决）
- 25%：未查医生排期（ReAct 强制先查后排期解决）
- 10%：参数填错（Tool Description 三段式解决）
- 5%：其他边界情况

1.5% 残留：合法的边缘情况（如医生临时调班、紧急插队导致冲突）
         → 这类需要人工处理，自检会标记 [NEEDS_HUMAN_REVIEW]
```
