# Li 元素框选问题修复说明

## 问题描述

`<li data-val="29">招标公告和资格预审公告</li>` 没有被 SoM (Set-of-Mark) 系统框选。

## 根本原因

1. **缺少相关选择器**：原始的 `strictSelectors` 列表中没有包含 `li[data-val]` 等选择器
2. **data 属性检测不完整**：`hasExplicitClickHandler` 和 `hasEventAttributes` 函数只检查了 `data-click` 和 `data-action`，没有检测 `data-val`、`data-value` 等常见的列表项标识属性

## 修复方案

### 1. 扩展严格选择器 (第 13-43 行)

添加了以下选择器：
```javascript
'li[data-val]',
'li[data-value]',
'li[data-id]',
'div[data-val]',
'span[data-val]',
```

### 2. 增强 `hasExplicitClickHandler` 方法 (第 131-170 行)

改进了 data 属性检测逻辑：
- 检测更多交互相关属性名：`click`, `action`, `handler`, `event`
- 特殊处理 `li`, `div`, `span` 元素的 `data-val`, `data-value`, `data-id`, `data-key` 属性
- 额外验证：确保元素有合理的文本内容（0-200 字符）

### 3. 同步更新 `hasEventAttributes` 方法 (第 260-297 行)

为了保持一致性，在 `ClickabilityValidator.hasEventAttributes` 中应用了相同的逻辑。

## 测试结果

运行 `test_li_detection.py` 后：

```
✅ 测试成功：带有 data-val 的 li 元素已被正确识别！

找到的可交互元素数量: 6

标记 ID: 2
  标签: li
  文本: 招标公告和资格预审公告
  角色: None
  可点击原因: event-attribute
  置信度: 0.95
  ✓ 找到目标元素！
```

## 支持的场景

修复后，以下类型的 `li` 元素都能被正确识别：

1. ✅ `<li data-val="29">...</li>`
2. ✅ `<li data-value="29">...</li>`
3. ✅ `<li data-id="29">...</li>`
4. ✅ `<li data-key="29">...</li>`
5. ✅ `<li onclick="...">...</li>`
6. ✅ `<li style="cursor: pointer;">...</li>`
7. ✅ `<li role="button">...</li>`

同时也支持具有相同属性的 `div` 和 `span` 元素。

## 影响范围

- 文件：`d:\autospider\src\autospider\som\inject.js`
- 版本：v2.3
- 向后兼容：✅ 是（只添加了新的检测逻辑，不影响原有功能）

## 后续建议

如果在实际使用中发现某些特定的 `data-*` 属性没有被识别，可以在以下位置添加：

1. `CONFIG.strictSelectors` 数组（第 13-43 行）- 添加新的 CSS 选择器
2. `hasExplicitClickHandler` 方法（第 131-170 行）- 添加新的属性名检测逻辑
3. `hasEventAttributes` 方法（第 260-297 行）- 保持与上面一致
