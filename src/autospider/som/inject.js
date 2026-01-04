/**
 * SoM (Set-of-Mark) 注入脚本
 * 功能：
 * 1. 枚举视口内可交互元素
 * 2. 检测遮挡（elementFromPoint）
 * 3. 绘制数字边界框（pointer-events: none）
 * 4. 预生成稳定 XPath（优先级降级）
 * 5. 返回 marks 元数据供 Python 使用
 */

(function () {
  'use strict';

  // ========================================================================
  // 配置
  // ========================================================================
  const CONFIG = {
    // 可交互元素选择器（扩展版，覆盖更多中国网站常见元素）
    interactiveSelectors: [
      // 标准链接和按钮
      'a[href]',
      'a',  // 无 href 的 a 标签也可能有点击事件
      'button',
      'input:not([type="hidden"])',
      'textarea',
      'select',
      'option',
      
      // ARIA 角色
      '[role="button"]',
      '[role="link"]',
      '[role="menuitem"]',
      '[role="menuitemcheckbox"]',
      '[role="menuitemradio"]',
      '[role="tab"]',
      '[role="tabpanel"]',
      '[role="checkbox"]',
      '[role="radio"]',
      '[role="switch"]',
      '[role="combobox"]',
      '[role="listbox"]',
      '[role="option"]',
      '[role="treeitem"]',
      '[role="gridcell"]',
      '[role="row"]',
      '[role="searchbox"]',
      '[role="slider"]',
      '[role="spinbutton"]',
      
      // 事件监听
      '[onclick]',
      '[onmousedown]',
      '[onmouseup]',
      '[ontouchstart]',
      '[ng-click]',      // Angular
      '[v-on\\:click]',  // Vue (v-on:click)
      '[@click]',        // Vue (@click) - 可能需要转义
      '[\\(click\\)]',   // Angular ((click))
      
      // 可聚焦元素
      '[tabindex]:not([tabindex="-1"])',
      '[contenteditable="true"]',
      
      // 表单相关
      'label[for]',
      'label',
      'summary',
      'details',
      
      // 列表和导航项（常见于中国政务/电商网站）
      'li',
      'nav li',
      'ul li',
      'ol li',
      '.nav-item',
      '.menu-item',
      '.tab-item',
      '.list-item',
      
      // 带点击样式的元素
      '[class*="click"]',
      '[class*="btn"]',
      '[class*="button"]',
      '[class*="link"]',
      '[class*="tab"]',
      '[class*="nav"]',
      '[class*="menu"]',
      '[class*="item"]',
      '[class*="option"]',
      '[class*="select"]',
      '[class*="dropdown"]',
      '[class*="toggle"]',
      '[class*="switch"]',
      '[class*="check"]',
      '[class*="radio"]',
      '[class*="expand"]',
      '[class*="collapse"]',
      '[class*="more"]',
      '[class*="close"]',
      '[class*="search"]',
      '[class*="filter"]',
      '[class*="sort"]',
      '[class*="page"]',
      '[class*="pagination"]',
      
      // 图标按钮
      'i[class*="icon"]',
      'span[class*="icon"]',
      'svg',
      
      // 带 cursor:pointer 样式的元素（通过 JS 检测）
    ],
    
    // 最小可交互元素尺寸（过滤太小的元素）
    minWidth: 10,
    minHeight: 10,
    
    // 最大标注数量（防止页面元素过多）
    maxMarks: 100,
    // 标签样式
    labelStyle: {
      fontSize: '11px',
      fontWeight: 'bold',
      fontFamily: 'Arial, sans-serif',
      color: '#ffffff',
      backgroundColor: '#ff0000',
      padding: '1px 4px',
      borderRadius: '3px',
      zIndex: '2147483647',
    },
    // 边框样式
    boxStyle: {
      border: '2px solid #ff0000',
      backgroundColor: 'rgba(255, 0, 0, 0.1)',
      zIndex: '2147483646',
    },
    // 文本截断长度
    maxTextLength: 50,
    // 随机 ID 检测正则（排除这些 ID）
    randomIdPattern: /^[a-f0-9]{8,}$|^[a-z0-9]{20,}$|uuid|guid|[0-9]{10,}/i,
  };

  // ========================================================================
  // XPath 生成器
  // ========================================================================
  const XPathGenerator = {
    /**
     * 为元素生成多个 XPath 候选（按稳定性排序）
     */
    generateCandidates(element) {
      const candidates = [];

      // 1. ID（最稳定，但排除随机 ID）
      const id = element.getAttribute('id');
      if (id && !CONFIG.randomIdPattern.test(id)) {
        const xpath = `//*[@id="${this.escapeXPath(id)}"]`;
        if (this.isUnique(xpath, element)) {
          candidates.push({
            xpath,
            priority: 1,
            strategy: 'id',
            confidence: 1.0,
          });
        }
      }

      // 2. data-testid / data-test / data-qa / data-cy
      for (const attr of ['data-testid', 'data-test', 'data-qa', 'data-cy']) {
        const value = element.getAttribute(attr);
        if (value) {
          const xpath = `//*[@${attr}="${this.escapeXPath(value)}"]`;
          if (this.isUnique(xpath, element)) {
            candidates.push({
              xpath,
              priority: 2,
              strategy: 'testid',
              confidence: 1.0,
            });
          }
        }
      }

      // 3. aria-label
      const ariaLabel = element.getAttribute('aria-label');
      if (ariaLabel) {
        const xpath = `//*[@aria-label="${this.escapeXPath(ariaLabel)}"]`;
        if (this.isUnique(xpath, element)) {
          candidates.push({
            xpath,
            priority: 3,
            strategy: 'aria',
            confidence: 0.9,
          });
        }
      }

      // 4. name 属性（用于表单元素）
      const name = element.getAttribute('name');
      if (name) {
        const tag = element.tagName.toLowerCase();
        const xpath = `//${tag}[@name="${this.escapeXPath(name)}"]`;
        if (this.isUnique(xpath, element)) {
          candidates.push({
            xpath,
            priority: 3,
            strategy: 'name',
            confidence: 0.9,
          });
        }
      }

      // 5. placeholder（用于输入框）
      const placeholder = element.getAttribute('placeholder');
      if (placeholder) {
        const tag = element.tagName.toLowerCase();
        const xpath = `//${tag}[@placeholder="${this.escapeXPath(placeholder)}"]`;
        if (this.isUnique(xpath, element)) {
          candidates.push({
            xpath,
            priority: 3,
            strategy: 'placeholder',
            confidence: 0.85,
          });
        }
      }

      // 6. 文本内容（用于按钮/链接等短文本元素）
      const text = this.getVisibleText(element);
      if (text && text.length <= 30) {
        const tag = element.tagName.toLowerCase();
        // 使用 normalize-space 处理空白
        const xpath = `//${tag}[normalize-space(.)="${this.escapeXPath(text)}"]`;
        if (this.isUnique(xpath, element)) {
          candidates.push({
            xpath,
            priority: 4,
            strategy: 'text',
            confidence: 0.7,
          });
        }

        // 备选：contains 方式
        const xpathContains = `//${tag}[contains(normalize-space(.), "${this.escapeXPath(text)}")]`;
        if (candidates.length === 0 || !this.isUnique(candidates[0].xpath, element)) {
          candidates.push({
            xpath: xpathContains,
            priority: 4,
            strategy: 'text-contains',
            confidence: 0.5,
          });
        }
      }

      // 7. 相对路径（兜底）
      const relativePath = this.getRelativePath(element);
      if (relativePath) {
        candidates.push({
          xpath: relativePath,
          priority: 5,
          strategy: 'relative',
          confidence: 0.4,
        });
      }

      // 按优先级排序
      candidates.sort((a, b) => a.priority - b.priority);

      return candidates;
    },

    /**
     * 获取元素的相对路径 XPath
     */
    getRelativePath(element) {
      const parts = [];
      let current = element;
      let depth = 0;
      const maxDepth = 6;

      while (current && current !== document.body && depth < maxDepth) {
        const tag = current.tagName.toLowerCase();

        // 尝试找到稳定锚点
        const id = current.getAttribute('id');
        if (id && !CONFIG.randomIdPattern.test(id)) {
          parts.unshift(`//*[@id="${this.escapeXPath(id)}"]`);
          break;
        }

        // 计算同级索引
        let index = 1;
        let sibling = current.previousElementSibling;
        while (sibling) {
          if (sibling.tagName === current.tagName) {
            index++;
          }
          sibling = sibling.previousElementSibling;
        }

        // 检查是否需要索引
        let needsIndex = false;
        sibling = current.nextElementSibling;
        while (sibling) {
          if (sibling.tagName === current.tagName) {
            needsIndex = true;
            break;
          }
          sibling = sibling.nextElementSibling;
        }
        if (index > 1) {
          needsIndex = true;
        }

        const part = needsIndex ? `${tag}[${index}]` : tag;
        parts.unshift(part);

        current = current.parentElement;
        depth++;
      }

      if (parts.length === 0) {
        return null;
      }

      // 如果没有找到锚点，从 body 开始
      if (!parts[0].startsWith('//*[@id')) {
        parts.unshift('//body');
      }

      return parts.join('/');
    },

    /**
     * 检查 XPath 是否唯一命中该元素
     */
    isUnique(xpath, element) {
      try {
        const result = document.evaluate(
          xpath,
          document,
          null,
          XPathResult.ORDERED_NODE_SNAPSHOT_TYPE,
          null
        );
        return result.snapshotLength === 1 && result.snapshotItem(0) === element;
      } catch (e) {
        return false;
      }
    },

    /**
     * 转义 XPath 特殊字符
     */
    escapeXPath(str) {
      if (!str) return '';
      if (!str.includes("'")) {
        return str;
      }
      if (!str.includes('"')) {
        return str;
      }
      // 包含单引号和双引号，使用 concat
      return str;
    },

    /**
     * 获取元素的可见文本
     */
    getVisibleText(element) {
      const text = (element.innerText || element.textContent || '').trim();
      return text.substring(0, CONFIG.maxTextLength);
    },
  };

  // ========================================================================
  // 遮挡检测器
  // ========================================================================
  const OcclusionDetector = {
    /**
     * 检查元素是否在视口内且未被遮挡
     */
    isVisibleAndUnoccluded(element) {
      const rect = element.getBoundingClientRect();

      // 检查是否在视口内
      if (
        rect.width === 0 ||
        rect.height === 0 ||
        rect.bottom < 0 ||
        rect.top > window.innerHeight ||
        rect.right < 0 ||
        rect.left > window.innerWidth
      ) {
        return { visible: false, reason: 'outside-viewport' };
      }

      // 检查 CSS 可见性
      const style = window.getComputedStyle(element);
      if (
        style.display === 'none' ||
        style.visibility === 'hidden' ||
        style.opacity === '0' ||
        parseFloat(style.opacity) < 0.1
      ) {
        return { visible: false, reason: 'css-hidden' };
      }

      // 检查元素中心点是否被遮挡
      const centerX = rect.left + rect.width / 2;
      const centerY = rect.top + rect.height / 2;

      // 确保中心点在视口内
      if (
        centerX < 0 ||
        centerX > window.innerWidth ||
        centerY < 0 ||
        centerY > window.innerHeight
      ) {
        return { visible: false, reason: 'center-outside-viewport' };
      }

      const topElement = document.elementFromPoint(centerX, centerY);

      if (!topElement) {
        return { visible: false, reason: 'no-element-at-point' };
      }

      // 检查顶层元素是否是目标元素或其子元素
      if (element === topElement || element.contains(topElement) || topElement.contains(element)) {
        return { visible: true, zIndex: this.getZIndex(element) };
      }

      // 被其他元素遮挡
      return { visible: false, reason: 'occluded', occludedBy: topElement.tagName };
    },

    /**
     * 获取元素的 z-index
     */
    getZIndex(element) {
      let zIndex = 0;
      let current = element;
      while (current && current !== document.body) {
        const style = window.getComputedStyle(current);
        const z = parseInt(style.zIndex, 10);
        if (!isNaN(z)) {
          zIndex = Math.max(zIndex, z);
        }
        current = current.parentElement;
      }
      return zIndex;
    },
  };

  // ========================================================================
  // 辅助函数
  // ========================================================================
  
  /**
   * 计算两个边界框的重叠率
   */
  function calculateOverlapRatio(bbox1, bbox2) {
    const x1 = Math.max(bbox1.x, bbox2.x);
    const y1 = Math.max(bbox1.y, bbox2.y);
    const x2 = Math.min(bbox1.x + bbox1.width, bbox2.x + bbox2.width);
    const y2 = Math.min(bbox1.y + bbox1.height, bbox2.y + bbox2.height);
    
    if (x2 <= x1 || y2 <= y1) {
      return 0; // 无重叠
    }
    
    const intersectionArea = (x2 - x1) * (y2 - y1);
    const bbox1Area = bbox1.width * bbox1.height;
    const bbox2Area = bbox2.width * bbox2.height;
    const smallerArea = Math.min(bbox1Area, bbox2Area);
    
    return intersectionArea / smallerArea;
  }

  // ========================================================================
  // SoM 覆盖层管理
  // ========================================================================
  const SoMOverlay = {
    containerId: '__som_overlay_container__',

    /**
     * 创建覆盖层容器
     */
    createContainer() {
      this.clear();

      const container = document.createElement('div');
      container.id = this.containerId;
      container.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        width: 100vw;
        height: 100vh;
        pointer-events: none;
        z-index: 2147483647;
        overflow: hidden;
      `;
      document.body.appendChild(container);
      return container;
    },

    /**
     * 清除覆盖层
     */
    clear() {
      const existing = document.getElementById(this.containerId);
      if (existing) {
        existing.remove();
      }
    },

    /**
     * 绘制标注框和标签
     */
    drawMark(container, mark) {
      const { bbox, mark_id } = mark;

      // 边框
      const box = document.createElement('div');
      box.className = '__som_box__';
      box.style.cssText = `
        position: fixed;
        left: ${bbox.x}px;
        top: ${bbox.y}px;
        width: ${bbox.width}px;
        height: ${bbox.height}px;
        border: ${CONFIG.boxStyle.border};
        background-color: ${CONFIG.boxStyle.backgroundColor};
        pointer-events: none;
        box-sizing: border-box;
        z-index: ${CONFIG.boxStyle.zIndex};
      `;

      // 标签（放在边框右上角外侧，避免遮挡文字）
      const label = document.createElement('div');
      label.className = '__som_label__';
      label.textContent = mark_id;

      // 计算标签位置：右上角外侧
      let labelLeft = bbox.x + bbox.width - 5;
      let labelTop = bbox.y - 16;

      // 边界检查：防止标签超出视口
      if (labelTop < 0) {
        labelTop = bbox.y + 2;
      }
      if (labelLeft + 30 > window.innerWidth) {
        labelLeft = bbox.x + bbox.width - 30;
      }

      label.style.cssText = `
        position: fixed;
        left: ${labelLeft}px;
        top: ${labelTop}px;
        font-size: ${CONFIG.labelStyle.fontSize};
        font-weight: ${CONFIG.labelStyle.fontWeight};
        font-family: ${CONFIG.labelStyle.fontFamily};
        color: ${CONFIG.labelStyle.color};
        background-color: ${CONFIG.labelStyle.backgroundColor};
        padding: ${CONFIG.labelStyle.padding};
        border-radius: ${CONFIG.labelStyle.borderRadius};
        pointer-events: none;
        z-index: ${CONFIG.labelStyle.zIndex};
        white-space: nowrap;
      `;

      container.appendChild(box);
      container.appendChild(label);
    },
  };

  // ========================================================================
  // 主扫描函数
  // ========================================================================
  function scanAndMark() {
    // 用 Set 去重（避免同一元素被多个选择器匹配）
    const elementSet = new Set();
    
    // 1. 通过选择器收集元素
    for (const selector of CONFIG.interactiveSelectors) {
      try {
        const elements = document.querySelectorAll(selector);
        elements.forEach(el => elementSet.add(el));
      } catch (e) {
        // 某些选择器可能无效，忽略
      }
    }
    
    // 2. 额外收集 cursor:pointer 的元素（这些通常是可点击的）
    const allElements = document.querySelectorAll('*');
    for (const el of allElements) {
      try {
        const style = window.getComputedStyle(el);
        if (style.cursor === 'pointer') {
          elementSet.add(el);
        }
      } catch (e) {
        // 忽略无法获取样式的元素
      }
    }
    
    const marks = [];
    let markId = 1;
    
    // 已标记元素的边界框（用于去重重叠元素）
    const markedBboxes = [];
    
    for (const element of elementSet) {
      // 达到最大标注数量时停止
      if (markId > CONFIG.maxMarks) {
        break;
      }
      
      const rect = element.getBoundingClientRect();
      
      // 过滤太小的元素
      if (rect.width < CONFIG.minWidth || rect.height < CONFIG.minHeight) {
        continue;
      }
      
      // 检查可见性和遮挡
      const visibility = OcclusionDetector.isVisibleAndUnoccluded(element);
      if (!visibility.visible) {
        continue;
      }
      
      // 检查是否与已标记的元素高度重叠（避免标记父子元素）
      const newBbox = {
        x: rect.left,
        y: rect.top,
        width: rect.width,
        height: rect.height,
      };
      
      let isDuplicate = false;
      for (const existingBbox of markedBboxes) {
        const overlapRatio = calculateOverlapRatio(newBbox, existingBbox);
        if (overlapRatio > 0.8) {
          // 高度重叠，跳过（保留先标记的，通常是更具体的元素）
          isDuplicate = true;
          break;
        }
      }
      if (isDuplicate) {
        continue;
      }

      // 生成 XPath 候选
      const xpathCandidates = XPathGenerator.generateCandidates(element);

      // 收集元素信息
      const mark = {
        mark_id: markId,
        tag: element.tagName.toLowerCase(),
        role: element.getAttribute('role'),
        text: XPathGenerator.getVisibleText(element),
        aria_label: element.getAttribute('aria-label'),
        placeholder: element.getAttribute('placeholder'),
        href: element.tagName === 'A' ? element.getAttribute('href') : null,
        input_type: element.tagName === 'INPUT' ? element.getAttribute('type') : null,
        bbox: newBbox,
        center_normalized: [
          (rect.left + rect.width / 2) / window.innerWidth,
          (rect.top + rect.height / 2) / window.innerHeight,
        ],
        xpath_candidates: xpathCandidates,
        is_visible: true,
        z_index: visibility.zIndex || 0,
      };

      // 存储元素引用以便后续操作
      element.setAttribute('data-som-id', markId);

      marks.push(mark);
      markedBboxes.push(newBbox);
      markId++;
    }

    // 绘制覆盖层
    const container = SoMOverlay.createContainer();
    for (const mark of marks) {
      SoMOverlay.drawMark(container, mark);
    }

    // 计算页面滚动状态
    const scrollInfo = getScrollInfo();

    return {
      url: window.location.href,
      title: document.title,
      viewport_width: window.innerWidth,
      viewport_height: window.innerHeight,
      marks: marks,
      timestamp: Date.now() / 1000,
      scroll_info: scrollInfo,
    };
  }

  /**
   * 获取页面滚动状态信息
   */
  function getScrollInfo() {
    const scrollTop = window.scrollY || document.documentElement.scrollTop || document.body.scrollTop || 0;
    const scrollHeight = Math.max(
      document.body.scrollHeight,
      document.documentElement.scrollHeight,
      document.body.offsetHeight,
      document.documentElement.offsetHeight,
      document.body.clientHeight,
      document.documentElement.clientHeight
    );
    const clientHeight = window.innerHeight || document.documentElement.clientHeight;
    
    // 计算滚动百分比
    const maxScroll = scrollHeight - clientHeight;
    const scrollPercent = maxScroll > 0 ? Math.round((scrollTop / maxScroll) * 100) : 100;
    
    // 判断滚动位置
    const isAtTop = scrollTop <= 10;
    const isAtBottom = scrollTop + clientHeight >= scrollHeight - 10;
    const canScrollDown = !isAtBottom;
    const canScrollUp = !isAtTop;
    
    return {
      scroll_top: Math.round(scrollTop),
      scroll_height: Math.round(scrollHeight),
      client_height: Math.round(clientHeight),
      scroll_percent: scrollPercent,
      is_at_top: isAtTop,
      is_at_bottom: isAtBottom,
      can_scroll_down: canScrollDown,
      can_scroll_up: canScrollUp,
    };
  }

  /**
   * 根据 mark_id 获取元素
   */
  function getElementByMarkId(markId) {
    return document.querySelector(`[data-som-id="${markId}"]`);
  }

  /**
   * 清除 SoM 覆盖层
   */
  function clearOverlay() {
    SoMOverlay.clear();
  }

  /**
   * 隐藏/显示覆盖层（用于截图后执行动作）
   */
  function setOverlayVisibility(visible) {
    const container = document.getElementById(SoMOverlay.containerId);
    if (container) {
      container.style.display = visible ? 'block' : 'none';
    }
  }

  // 暴露全局 API
  window.__SOM__ = {
    scan: scanAndMark,
    clear: clearOverlay,
    getElement: getElementByMarkId,
    setVisibility: setOverlayVisibility,
  };

  // 返回扫描结果
  return scanAndMark();
})();
