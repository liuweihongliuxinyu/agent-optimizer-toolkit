# 电商 Agent 完整示例

> 优化前：曾因未校验优惠券金额，生成万元优惠券，造成直接经济损失
> 优化后：Pre-call Validation 拦截所有不合规参数，此类事故归零

---

## 一、工具列表（三段式）

### 工具1: search_products

#### 何时调用（What for）
- 用户搜索商品、浏览品类、找特定产品时
- 用户描述需求但未指定具体商品名时

#### 不调边界（When not）
- 用户已明确指定了商品ID ← 应直接调 get_product
- 用户只是在闲聊或咨询售后政策
- 搜索词为空或仅包含"的""了""吗"等虚词

#### 参数示例
```json
{
  "query": "无线蓝牙耳机",
  "category": "electronics",
  "price_min": 100,
  "price_max": 500,
  "page": 1,
  "page_size": 20
}
```

---

### 工具2: create_order

#### 何时调用（What for）
- 用户明确说"下单""购买""结算"并确认了商品和数量
- 用户确认收货地址后

#### 不调边界（When not）
- 用户只是在询价、比价 ← 不应创建订单
- 库存不足时 ← 应先提示用户
- 用户尚未确认收货地址
- 优惠券码格式不对或已过期

#### 参数示例
```json
{
  "product_id": "P_BT880_WH",
  "quantity": 1,
  "amount": 299.00,
  "coupon_code": "VIP2024",
  "coupon_discount": 50.00,
  "address_id": "addr_12345"
}
```

#### 校验规则（关键！）
```
- amount > 0（金额必须为正）
- coupon_discount ≤ amount * 0.5（优惠券面额不能超过订单金额的50%）
- coupon_discount ≤ 1000（单张优惠券上限1000元）
- quantity ≥ 1 且 ≤ 999
- address_id 必须已验证
```

---

### 工具3: check_inventory

#### 何时调用（What for）
- 用户下单前，必须确认库存
- 用户询问是否有货时

#### 不调边界（When not）
- 纯信息查询类问题（如"这个耳机是什么牌子的"）
- 用户已明确表示"只是看看"

#### 参数示例
```json
{
  "product_id": "P_BT880_WH",
  "warehouse_id": "WH_GZ_01"
}
```

---

## 二、完整交互示例

### 优化前（无校验，出事故）

```
用户: 帮我下单 蓝牙耳机P_BT880，用券 VIP2024

Agent: 好的，帮您下单。
  → create_order(product_id="P_BT880_WH", quantity=1, amount=299,
                  coupon_code="VIP2024", coupon_discount=5000.00)
  → ❌ 订单创建成功！实付 -4701 元（倒贴钱）
```

### 优化后（五技法全开）

```
用户: 帮我下单 蓝牙耳机P_BT880，用券 VIP2024

Thought: 用户要下单。但我需要先：
1. 确认库存 → check_inventory
2. 确认收货地址 → 上下文里有 addr_12345
3. 优惠券 VIP2024 的面额是多少？→ 需要调 verify_coupon
4. 所有信息确认后再调 create_order

Step 1: 查库存
Action: check_inventory(product_id="P_BT880_WH")

Observation: {"in_stock": true, "quantity_available": 50}

Step 2: 验优惠券
Action: verify_coupon(code="VIP2024", product_id="P_BT880_WH")

Observation: {"valid": true, "discount": 50.00, "min_order": 200}

Thought: 优惠券面额 50 元，最低消费 200，订单金额 299 满足。
所有参数校验通过：
✅ product_id 有效
✅ quantity=1 在范围内
✅ amount=299 > 0
✅ coupon_discount=50 ≤ 1000，且 ≤ 299*0.5
✅ address_id 已验证
✅ 库存充足

现在可以下单了。

Action: create_order(product_id="P_BT880_WH", quantity=1, amount=299.00,
                     coupon_code="VIP2024", coupon_discount=50.00,
                     address_id="addr_12345")

Observation: {"order_id": "ORD_20240618_001", "status": "confirmed",
              "final_amount": 249.00}

【自检】
✅ 完整性：已回答用户下单请求
✅ 正确性：所有参数校验通过
✅ 一致性：库存、优惠券、地址信息一致
✅ 冲突检测：无冲突
✅ 体验：可告知物流预计时间

最终回复:
您的订单已确认！订单号 ORD_20240618_001
- 商品：蓝牙耳机 P_BT880 ×1
- 原价：¥299.00
- 优惠券：VIP2024 减 ¥50.00
- 实付：¥249.00
- 预计 2-3 天送达
```

---

## 三、事故教训

```
原因：未校验 coupon_discount 参数，直接透传用户/系统填入的值
修复：加 Pre-call Validation，coupon_discount 上限硬编码为 1000 元
长期方案：优惠券面额必须从 verify_coupon 工具返回，不允许手动传入
```
