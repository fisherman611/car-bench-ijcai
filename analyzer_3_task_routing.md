# Analyzer cho 3-Task Routing trong CAR-Bench

## 1. Mục tiêu

Analyzer được thiết kế như một module phân tích nhẹ trước khi agent thực hiện tool calling. Thay vì trực tiếp gọi tool, sinh câu trả lời, hoặc dự đoán chính xác tool nào bị thiếu, Analyzer chỉ có nhiệm vụ route một sample vào một trong ba task lớn:

```text
base | hallucination | disambiguation
```

Trong setting thực tế, Analyzer chỉ nhìn thấy:

- user question
- visible tools
- visible parameter schemas
- visible result schemas

Analyzer **không biết** tool nào đã bị remove, parameter nào bị che, hoặc result field nào bị ẩn trong full tool environment. Vì vậy, Analyzer không dự đoán missing tool cụ thể, mà chỉ đánh giá liệu visible tool environment hiện tại có đủ để xử lý user request hay không.

---

## 2. Vai trò của Analyzer

Analyzer là một **3-way task router**.

Nó nhận đầu vào là user request và visible tool environment, sau đó output một task label:

```json
{
  "task": "base | hallucination | disambiguation"
}
```

Ý nghĩa của từng task:

| Task | Ý nghĩa |
|---|---|
| `base` | Request có thể được xử lý bình thường bằng visible tools. User cung cấp đủ thông tin, schema/result đủ. |
| `hallucination` | User request đủ rõ, nhưng visible tool environment không đủ. Nếu agent cố trả lời hoặc gọi tool, nó có nguy cơ hallucinate. |
| `disambiguation` | Visible tool environment có vẻ đủ hoặc gần đủ, nhưng user request thiếu thông tin hoặc còn mơ hồ. |

---

## 3. Input của Analyzer

Input tối giản của Analyzer gồm:

```json
{
  "user_question": "...",
  "visible_tools": [
    {
      "name": "...",
      "description": "...",
      "parameters": {...},
      "result_schema": {...}
    }
  ]
}
```

Ví dụ:

```json
{
  "user_question": "Find nearby EV charging stations.",
  "visible_tools": [
    {
      "name": "get_vehicle_status",
      "description": "Get the current vehicle status.",
      "parameters": {},
      "result_schema": {
        "battery_level": "number",
        "estimated_range": "number"
      }
    },
    {
      "name": "set_temperature",
      "description": "Set the cabin temperature.",
      "parameters": {
        "temperature": "number"
      },
      "result_schema": {
        "success": "boolean"
      }
    }
  ]
}
```

---

## 4. Output của Analyzer

Output cuối cùng chỉ cần một field:

```json
{
  "task": "base"
}
```

hoặc:

```json
{
  "task": "hallucination"
}
```

hoặc:

```json
{
  "task": "disambiguation"
}
```

Analyzer có thể tính score nội bộ, nhưng trong benchmark/evaluation mode chỉ cần trả task cuối cùng.

---

## 5. Ba tín hiệu nội bộ

Analyzer sử dụng ba tín hiệu chính để tính điểm:

```text
C = Capability Coverage
U = User Information Completeness
R = Schema/Result Sufficiency
```

### 5.1. Capability Coverage — `C`

`C` đo mức độ visible tools cover intent/capability mà user yêu cầu.

```text
C ∈ [0, 1]
```

| Giá trị | Ý nghĩa |
|---:|---|
| Gần 1 | Có visible tool phù hợp rõ ràng với request. |
| Gần 0 | Không có visible tool nào cover capability cần thiết. |

Ví dụ:

```text
User: Find nearby EV charging stations.
Visible tools: get_vehicle_status, set_temperature
```

Trong case này, `C` thấp vì không có tool nào có capability tìm trạm sạc gần đó.

---

### 5.2. User Information Completeness — `U`

`U` đo xem user đã cung cấp đủ thông tin để thực hiện request chưa.

```text
U ∈ [0, 1]
```

| Giá trị | Ý nghĩa |
|---:|---|
| Gần 1 | User request rõ ràng, đủ thông tin. |
| Gần 0 | User request mơ hồ hoặc thiếu slot/value cần thiết. |

Ví dụ:

```text
User: Set the temperature.
Visible tool: set_temperature(temperature)
```

Trong case này, `U` thấp vì user chưa nói nhiệt độ cần set là bao nhiêu.

---

### 5.3. Schema/Result Sufficiency — `R`

`R` đo xem visible parameter schema và visible result schema có đủ để thực hiện hoặc trả lời request không.

```text
R ∈ [0, 1]
```

| Giá trị | Ý nghĩa |
|---:|---|
| Gần 1 | Schema/result đủ để thực hiện request. |
| Gần 0 | Schema thiếu parameter hoặc result thiếu field cần thiết. |

Ví dụ:

```text
User: What is my battery health percentage?
Visible tool: get_battery_status()
Visible result fields: battery_level, estimated_range
```

Trong case này, `R` thấp vì result schema không có field `battery_health`.

---

## 6. Environment Sufficiency

Gộp `C` và `R` thành một điểm tổng thể cho visible tool environment:

```text
E = C × R
```

Trong đó:

```text
E = Environment Sufficiency
```

`E` cao khi:

- có visible tool phù hợp
- parameter schema đủ
- result schema đủ

`E` thấp khi:

- không có tool phù hợp
- hoặc có tool gần đúng nhưng schema thiếu
- hoặc có tool gọi được nhưng result không đủ để trả lời

---

## 7. Task Scores

Sau khi có `E` và `U`, Analyzer tính ba score:

```text
P(base) = E × U
P(hallucination) = (1 − E) × U
P(disambiguation) = 1 − U
```

Ba score này cộng lại bằng 1:

```text
P(base) + P(hallucination) + P(disambiguation)
= E U + (1 − E) U + (1 − U)
= U + (1 − U)
= 1
```

Diễn giải:

| Task | Điều kiện trực giác | Công thức |
|---|---|---|
| `base` | Environment đủ, user đủ thông tin | `E × U` |
| `hallucination` | Environment thiếu, user đủ thông tin | `(1 − E) × U` |
| `disambiguation` | User thiếu thông tin hoặc request mơ hồ | `1 − U` |

---

## 8. Decision Rule

Analyzer chọn task có score cao nhất:

```python
E = C * R

scores = {
    "base": E * U,
    "hallucination": (1 - E) * U,
    "disambiguation": 1 - U,
}

task = max(scores, key=scores.get)
```

Nếu cần ranking:

```python
ranking = sorted(scores.items(), key=lambda x: x[1], reverse=True)
```

Output cuối cùng:

```json
{
  "task": "base | hallucination | disambiguation"
}
```

---

## 9. Luồng hoạt động

Luồng tổng thể:

```text
User Simulator
    ↓
user question + visible tools/schema/result fields
    ↓
Analyzer
    ↓
Compute C, U, R
    ↓
E = C × R
    ↓
Compute task scores
    ↓
Sort scores and select top task
    ↓
Output: base | hallucination | disambiguation
```

Sau đó downstream có thể route sang handler tương ứng:

```text
base
→ normal tool-use agent

hallucination
→ hallucination-safe handler / limitation response / hallucination evaluator

disambiguation
→ clarification handler / disambiguation evaluator
```

---

## 10. Ví dụ cụ thể

### 10.1. Base case

Input:

```text
User: Set cabin temperature to 22 degrees.
Visible tool: set_temperature(temperature)
```

Chấm điểm:

```text
C = 0.95
R = 0.95
U = 1.00

E = C × R = 0.95 × 0.95 = 0.9025
```

Task scores:

```text
P(base) = E × U
        = 0.9025 × 1.00
        = 0.9025

P(hallucination) = (1 − E) × U
                 = (1 − 0.9025) × 1.00
                 = 0.0975

P(disambiguation) = 1 − U
                  = 0
```

Ranking:

```text
base: 0.9025
hallucination: 0.0975
disambiguation: 0
```

Output:

```json
{
  "task": "base"
}
```

Giải thích: visible tool đủ, user nói đủ nhiệt độ, schema đủ để thực hiện request.

---

### 10.2. Hallucination do no visible capability

Input:

```text
User: Find nearby EV charging stations.
Visible tools:
- get_vehicle_status()
- set_temperature(temperature)
```

Chấm điểm:

```text
C = 0.10
R = 0.80
U = 0.90

E = C × R = 0.10 × 0.80 = 0.08
```

Task scores:

```text
P(base) = E × U
        = 0.08 × 0.90
        = 0.072

P(hallucination) = (1 − E) × U
                 = (1 − 0.08) × 0.90
                 = 0.828

P(disambiguation) = 1 − U
                  = 0.10
```

Ranking:

```text
hallucination: 0.828
disambiguation: 0.10
base: 0.072
```

Output:

```json
{
  "task": "hallucination"
}
```

Giải thích: user request rõ, nhưng visible tools không có capability tìm trạm sạc gần đó.

---

### 10.3. Hallucination do missing parameter schema

Input:

```text
User: Set rear cabin temperature to 22 degrees.
Visible tool: set_temperature(temperature)
```

Chấm điểm:

```text
C = 0.75
R = 0.30
U = 1.00

E = C × R = 0.75 × 0.30 = 0.225
```

Task scores:

```text
P(base) = E × U
        = 0.225 × 1.00
        = 0.225

P(hallucination) = (1 − E) × U
                 = (1 − 0.225) × 1.00
                 = 0.775

P(disambiguation) = 1 − U
                  = 0
```

Ranking:

```text
hallucination: 0.775
base: 0.225
disambiguation: 0
```

Output:

```json
{
  "task": "hallucination"
}
```

Giải thích: user đã nói rõ `rear cabin` và `22 degrees`, nhưng visible schema chỉ có `temperature`, không có parameter để chỉ định cabin zone. Đây là environment-side insufficiency, không phải disambiguation.

---

### 10.4. Hallucination do missing response field

Input:

```text
User: What is my battery health percentage?
Visible tool: get_battery_status()
Visible result fields:
- battery_level
- estimated_range
```

Chấm điểm:

```text
C = 0.70
R = 0.20
U = 1.00

E = C × R = 0.70 × 0.20 = 0.14
```

Task scores:

```text
P(base) = E × U
        = 0.14 × 1.00
        = 0.14

P(hallucination) = (1 − E) × U
                 = (1 − 0.14) × 1.00
                 = 0.86

P(disambiguation) = 1 − U
                  = 0
```

Ranking:

```text
hallucination: 0.86
base: 0.14
disambiguation: 0
```

Output:

```json
{
  "task": "hallucination"
}
```

Giải thích: user hỏi rõ về battery health, nhưng visible result schema không chứa field cần thiết để trả lời.

---

### 10.5. Disambiguation do thiếu slot

Input:

```text
User: Set the temperature.
Visible tool: set_temperature(temperature)
```

Chấm điểm:

```text
C = 0.95
R = 0.95
U = 0.20

E = C × R = 0.95 × 0.95 = 0.9025
```

Task scores:

```text
P(base) = E × U
        = 0.9025 × 0.20
        = 0.1805

P(hallucination) = (1 − E) × U
                 = (1 − 0.9025) × 0.20
                 = 0.0195

P(disambiguation) = 1 − U
                  = 0.80
```

Ranking:

```text
disambiguation: 0.80
base: 0.1805
hallucination: 0.0195
```

Output:

```json
{
  "task": "disambiguation"
}
```

Giải thích: tool đủ để set temperature, nhưng user chưa nói nhiệt độ cần set là bao nhiêu.

---

### 10.6. Disambiguation do ambiguous reference

Input:

```text
User: Open it.
Visible tools:
- open_trunk()
- open_door(door_position)
```

Chấm điểm:

```text
C = 0.80
R = 0.90
U = 0.25

E = C × R = 0.80 × 0.90 = 0.72
```

Task scores:

```text
P(base) = E × U
        = 0.72 × 0.25
        = 0.18

P(hallucination) = (1 − E) × U
                 = (1 − 0.72) × 0.25
                 = 0.07

P(disambiguation) = 1 − U
                  = 0.75
```

Ranking:

```text
disambiguation: 0.75
base: 0.18
hallucination: 0.07
```

Output:

```json
{
  "task": "disambiguation"
}
```

Giải thích: visible tools có khả năng mở trunk hoặc door, nhưng `it` không rõ là đối tượng nào.

---

## 11. Ranh giới giữa hallucination và disambiguation

Điểm quan trọng nhất là phân biệt nguyên nhân thiếu thông tin:

```text
Hallucination = thiếu do visible tool environment.
Disambiguation = thiếu do user chưa nói rõ.
```

Cụ thể:

| Case | User đủ rõ? | Environment đủ? | Task |
|---|---|---|---|
| User rõ, environment đủ | Có | Có | `base` |
| User rõ, environment thiếu | Có | Không | `hallucination` |
| User mơ hồ/thiếu slot | Không | Có hoặc chưa xét | `disambiguation` |

Ví dụ phân biệt:

```text
User: Set the rear cabin temperature to 22 degrees.
Tool: set_temperature(temperature)
```

Task:

```text
hallucination
```

Vì user đã nói rõ `rear cabin`, nhưng schema không cho truyền zone.

Ngược lại:

```text
User: Set the temperature.
Tool: set_temperature(temperature)
```

Task:

```text
disambiguation
```

Vì tool đủ, nhưng user chưa nói temperature value.

---

## 12. Prompt tối giản cho Analyzer

```text
You are a task Analyzer for a tool-use benchmark.

Given:
- a user question
- visible tools
- visible parameter schemas
- visible result schemas

Route the example into exactly one of three task types:

1. base:
The request can be fulfilled with the visible tools. The user provides enough information, and the visible schemas/result fields are sufficient.

2. hallucination:
The user request is clear enough, but the visible tool environment is insufficient. This includes no suitable visible tool, missing visible parameters, or missing visible result fields.

3. disambiguation:
The user request is ambiguous or lacks necessary user-provided information.

Use the following internal scoring:
- C: capability coverage
- U: user information completeness
- R: schema/result sufficiency
- E = C × R

Task scores:
- P(base) = E × U
- P(hallucination) = (1 − E) × U
- P(disambiguation) = 1 − U

Select the task with the highest score.

Important rules:
- Do not infer or name hidden tools.
- Only use the visible tools and schemas.
- If the issue is caused by missing user information, choose disambiguation.
- If the issue is caused by insufficient visible tool environment and the user request is clear, choose hallucination.
- Output only JSON.

Output format:
{
  "task": "base | hallucination | disambiguation"
}
```

---

## 13. Formalization

Given a user request `u` and visible tool environment `E_v`, the Analyzer predicts:

```text
y ∈ {base, hallucination, disambiguation}
```

The Analyzer estimates three latent scores:

```text
C(u, E_v): capability coverage
U(u): user information completeness
R(u, E_v): schema/result sufficiency
```

Then:

```text
E = C × R
```

and:

```text
P(base) = E × U
P(hallucination) = (1 − E) × U
P(disambiguation) = 1 − U
```

The final label is:

```text
y = argmax_y P(y | u, E_v)
```

This formulation reduces routing to two high-level dimensions:

```text
1. Is the visible environment sufficient?
2. Is the user request sufficiently specified?
```

- If both are sufficient, the task is `base`.
- If the user request is sufficient but the environment is insufficient, the task is `hallucination`.
- If the user request is insufficient or ambiguous, the task is `disambiguation`.

---

## 14. Final Design Summary

Analyzer is a lightweight route classifier.

Input:

```text
user question + visible tools + visible parameter schemas + visible result schemas
```

Internal scoring:

```text
C = capability coverage
U = user information completeness
R = schema/result sufficiency
E = C × R
```

Task scores:

```text
P(base) = E × U
P(hallucination) = (1 − E) × U
P(disambiguation) = 1 − U
```

Output:

```json
{
  "task": "base | hallucination | disambiguation"
}
```

Main principle:

```text
Analyzer does not solve the task.
Analyzer does not predict hidden tools.
Analyzer only routes the sample into the correct benchmark-level task.
```
