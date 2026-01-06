/**
 * SoM (Set-of-Mark) 注入脚本 v2.3
 * 
 * v2.3 改进：
 * - 新增祖先可交互元素检查
 * - 如果元素在可点击的父元素内，跳过子元素，标记父元素
 * - 避免重复标记同一个交互区域
 */

(function () {
  'use strict';

  const CONFIG = {
    strictSelectors: [
      'a[href]',
      'button',
      'input:not([type="hidden"])',
      'textarea',
      'select',
      'summary',
      '[role="button"]',
      '[role="link"]',
      '[role="menuitem"]',
      '[role="tab"]',
      '[role="checkbox"]',
      '[role="radio"]',
      '[role="switch"]',
      '[role="option"]',
      '[role="combobox"]',
      '[role="listbox"]',
      '[role="slider"]',
      '[tabindex="0"]',
      '[contenteditable="true"]',
      '[onclick]',
      '[ng-click]',
      '[v-on\\:click]',
      '[@click]',
    ],

    minWidth: 20,
    minHeight: 16,
    maxMarks: 200,

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

    boxStyle: {
      border: '2px solid #ff0000',
      backgroundColor: 'rgba(255, 0, 0, 0.1)',
      zIndex: '2147483646',
    },

    maxTextLength: 50,
    randomIdPattern: /^[a-f0-9]{8,}$|^[a-z0-9]{20,}$|uuid|guid|[0-9]{10,}/i,
  };

  // ========================================================================
  // 祖先元素检查器（核心新增）
  // ========================================================================
  const AncestorChecker = {
    /**
     * 检查元素是否在一个可交互的祖先元素内部
     * 如果是，返回那个祖先元素；否则返回 null
     */
    findClickableAncestor(element) {
      let current = element.parentElement;
      
      while (current && current !== document.body && current !== document.documentElement) {
        // 检查是否是原生可交互元素
        if (this.isNativeClickable(current)) {
          return current;
        }
        
        // 检查是否有明确的事件属性
        if (this.hasExplicitClickHandler(current)) {
          return current;
        }
        
        // 检查是否有交互性 ARIA 角色
        if (this.hasInteractiveRole(current)) {
          return current;
        }
        
        current = current.parentElement;
      }
      
      return null;
    },

    /**
     * 检查是否是原生可点击元素
     */
    isNativeClickable(element) {
      const tag = element.tagName.toLowerCase();
      
      // 链接
      if (tag === 'a') {
        const href = element.getAttribute('href');
        return href && href !== '#' && !href.startsWith('javascript:');
      }
      
      // 按钮
      if (tag === 'button') return true;
      
      // 可点击的输入类型
      if (tag === 'input') {
        const type = element.getAttribute('type');
        return ['button', 'submit', 'reset', 'checkbox', 'radio'].includes(type);
      }
      
      // summary
      if (tag === 'summary') return true;
      
      // label with for
      if (tag === 'label' && element.getAttribute('for')) return true;
      
      return false;
    },

    /**
     * 检查是否有明确的点击事件处理器
     */
    hasExplicitClickHandler(element) {
      const clickAttrs = [
        'onclick', 'onmousedown', 'ontouchstart',
        'ng-click', 'v-on:click', '@click', '(click)'
      ];
      
      for (const attr of clickAttrs) {
        if (element.hasAttribute(attr)) return true;
      }
      
      // 检查 data 属性
      for (const attr of element.attributes) {
        if (attr.name.startsWith('data-') && 
            (attr.name.includes('click') || attr.name.includes('action'))) {
          return true;
        }
      }
      
      return false;
    },

    /**
     * 检查是否有交互性 ARIA 角色
     */
    hasInteractiveRole(element) {
      const role = element.getAttribute('role');
      if (!role) return false;
      
      const interactiveRoles = [
        'button', 'link', 'menuitem', 'tab', 'checkbox', 
        'radio', 'switch', 'option', 'treeitem'
      ];
      
      return interactiveRoles.includes(role.toLowerCase());
    },

    /**
     * 判断元素是否应该被跳过（因为它在一个可点击的父元素内）
     */
    shouldSkipForAncestor(element) {
      const ancestor = this.findClickableAncestor(element);
      return ancestor !== null;
    },

    /**
     * 获取元素或其可点击祖先
     * 如果元素本身可点击，返回元素本身
     * 如果元素在可点击祖先内，返回祖先
     * 否则返回 null
     */
    getClickableElement(element) {
      // 先检查元素本身是否是原生可点击的
      if (this.isNativeClickable(element) || 
          this.hasExplicitClickHandler(element) ||
          this.hasInteractiveRole(element)) {
        return element;
      }
      
      // 检查是否有可点击的祖先
      const ancestor = this.findClickableAncestor(element);
      if (ancestor) {
        return ancestor;
      }
      
      return null;
    },
  };

  // ========================================================================
  // 可点击性验证器
  // ========================================================================
  const ClickabilityValidator = {
    isClickable(element) {
      const tag = element.tagName.toLowerCase();

      // 1. 原生可交互元素
      if (this.isNativeInteractive(element)) {
        return { clickable: true, reason: 'native-interactive', confidence: 1.0 };
      }

      // 2. 有事件属性
      if (this.hasEventAttributes(element)) {
        return { clickable: true, reason: 'event-attribute', confidence: 0.95 };
      }

      // 3. ARIA 角色
      if (this.hasInteractiveRole(element)) {
        return { clickable: true, reason: 'aria-role', confidence: 0.9 };
      }

      // 4. tabindex >= 0
      const tabindex = element.getAttribute('tabindex');
      if (tabindex !== null && parseInt(tabindex) >= 0) {
        return { clickable: true, reason: 'focusable', confidence: 0.85 };
      }

      // 5. cursor:pointer + 内容 + 合理尺寸 + 不在可点击祖先内
      if (this.hasCursorPointer(element)) {
        // 关键检查：是否在可点击的祖先元素内
        if (AncestorChecker.shouldSkipForAncestor(element)) {
          return { clickable: false, reason: 'inside-clickable-ancestor', confidence: 0 };
        }
        
        if (this.hasValidContent(element) && 
            this.hasReasonableSize(element) &&
            !this.isPureContainer(element)) {
          return { clickable: true, reason: 'cursor-pointer', confidence: 0.7 };
        }
      }

      return { clickable: false, reason: 'not-interactive', confidence: 0 };
    },

    isNativeInteractive(element) {
      const tag = element.tagName.toLowerCase();
      const type = element.getAttribute('type');

      if (tag === 'a') {
        const href = element.getAttribute('href');
        return href && href !== '#' && !href.startsWith('javascript:void') && !href.startsWith('javascript:;');
      }

      if (tag === 'button') return true;
      if (tag === 'input' && type !== 'hidden') return true;
      if (['textarea', 'select', 'option', 'summary'].includes(tag)) return true;

      return false;
    },

    hasEventAttributes(element) {
      const eventAttrs = [
        'onclick', 'onmousedown', 'onmouseup', 'ontouchstart',
        'ng-click', 'v-on:click', '@click', '(click)'
      ];

      for (const attr of eventAttrs) {
        if (element.hasAttribute(attr)) return true;
      }

      return false;
    },

    hasInteractiveRole(element) {
      const role = element.getAttribute('role');
      if (!role) return false;

      const interactiveRoles = [
        'button', 'link', 'menuitem', 'tab', 'checkbox', 
        'radio', 'switch', 'option', 'combobox', 'listbox', 
        'slider', 'treeitem'
      ];

      return interactiveRoles.includes(role.toLowerCase());
    },

    hasCursorPointer(element) {
      try {
        return window.getComputedStyle(element).cursor === 'pointer';
      } catch (e) {
        return false;
      }
    },

    hasValidContent(element) {
      const text = (element.innerText || element.textContent || '').trim();
      if (text.length > 0 && text.length < 500 && !/^[\s\|\·\-\—\•\>\<]+$/.test(text)) {
        return true;
      }

      if (element.getAttribute('aria-label') || element.getAttribute('title')) {
        return true;
      }

      // 有图片或图标
      if (element.querySelector('img, svg, [class*="icon"]')) {
        return true;
      }

      return false;
    },

    hasReasonableSize(element) {
      try {
        const rect = element.getBoundingClientRect();
        return rect.width >= 16 && rect.height >= 16 && 
               rect.width <= 800 && rect.height <= 600;
      } catch (e) {
        return false;
      }
    },

    isPureContainer(element) {
      const children = element.children;
      if (children.length <= 1) return false;
      if (children.length > 15) return true;

      let interactiveCount = 0;
      for (const child of children) {
        if (this.isNativeInteractive(child) || 
            this.hasEventAttributes(child) ||
            this.hasInteractiveRole(child)) {
          interactiveCount++;
        }
      }

      return interactiveCount >= 3;
    },
  };

  // ========================================================================
  // XPath 生成器
  // ========================================================================
  const XPathGenerator = {
    generateCandidates(element) {
      const candidates = [];

      const id = element.getAttribute('id');
      if (id && !CONFIG.randomIdPattern.test(id)) {
        const xpath = `//*[@id='${id}']`;
        if (this.isUnique(xpath, element)) {
          candidates.push({ xpath, priority: 1, strategy: 'id', confidence: 1.0 });
        }
      }

      for (const attr of ['data-testid', 'data-test', 'data-qa', 'data-cy']) {
        const value = element.getAttribute(attr);
        if (value) {
          const xpath = `//*[@${attr}='${value}']`;
          if (this.isUnique(xpath, element)) {
            candidates.push({ xpath, priority: 2, strategy: 'testid', confidence: 1.0 });
          }
        }
      }

      const ariaLabel = element.getAttribute('aria-label');
      if (ariaLabel && ariaLabel !== 'false') {
        const xpath = `//*[@aria-label='${ariaLabel}']`;
        if (this.isUnique(xpath, element)) {
          candidates.push({ xpath, priority: 3, strategy: 'aria', confidence: 0.9 });
        }
      }

      const href = element.getAttribute('href');
      if (href && element.tagName.toLowerCase() === 'a') {
        // 使用 href 的一部分作为定位
        const hrefPart = href.split('?')[0].split('/').pop();
        if (hrefPart && hrefPart.length > 5) {
          const xpath = `//a[contains(@href, '${hrefPart}')]`;
          if (this.isUnique(xpath, element)) {
            candidates.push({ xpath, priority: 3, strategy: 'href', confidence: 0.85 });
          }
        }
      }

      const text = this.getVisibleText(element);
      if (text && text.length > 0 && text.length <= 30) {
        const tag = element.tagName.toLowerCase();
        const xpath = `//${tag}[contains(., '${text.substring(0, 20)}')]`;
        if (this.isUnique(xpath, element)) {
          candidates.push({ xpath, priority: 4, strategy: 'text', confidence: 0.6 });
        }
      }

      const idBasedPath = this.getIdBasedPath(element);
      if (idBasedPath && this.isUnique(idBasedPath, element)) {
        candidates.push({ xpath: idBasedPath, priority: 5, strategy: 'id-relative', confidence: 0.8 });
      }

      const relativePath = this.getFullRelativePath(element);
      if (relativePath && this.isUnique(relativePath, element)) {
        candidates.push({ xpath: relativePath, priority: 6, strategy: 'relative', confidence: 0.4 });
      }

      candidates.sort((a, b) => a.priority - b.priority);
      return candidates;
    },

    getIdBasedPath(element) {
      let idAncestor = null;
      let current = element.parentElement;

      while (current && current !== document.documentElement) {
        const id = current.getAttribute('id');
        if (id && !CONFIG.randomIdPattern.test(id)) {
          idAncestor = current;
          break;
        }
        current = current.parentElement;
      }

      if (!idAncestor) return null;

      const parts = [];
      current = element;

      while (current && current !== idAncestor) {
        const tag = current.tagName.toLowerCase();
        let index = 1;
        let sibling = current.previousElementSibling;
        while (sibling) {
          if (sibling.tagName.toLowerCase() === tag) index++;
          sibling = sibling.previousElementSibling;
        }

        let needsIndex = index > 1;
        if (!needsIndex) {
          sibling = current.nextElementSibling;
          while (sibling) {
            if (sibling.tagName.toLowerCase() === tag) {
              needsIndex = true;
              break;
            }
            sibling = sibling.nextElementSibling;
          }
        }

        parts.unshift(needsIndex ? `${tag}[${index}]` : tag);
        current = current.parentElement;
      }

      return `//*[@id='${idAncestor.getAttribute('id')}']/${parts.join('/')}`;
    },

    getFullRelativePath(element) {
      const parts = [];
      let current = element;

      while (current && current !== document.documentElement) {
        const tag = current.tagName.toLowerCase();
        if (tag === 'html') {
          current = current.parentElement;
          continue;
        }

        let index = 1;
        let sibling = current.previousElementSibling;
        while (sibling) {
          if (sibling.tagName.toLowerCase() === tag) index++;
          sibling = sibling.previousElementSibling;
        }

        let needsIndex = index > 1;
        if (!needsIndex) {
          sibling = current.nextElementSibling;
          while (sibling) {
            if (sibling.tagName.toLowerCase() === tag) {
              needsIndex = true;
              break;
            }
            sibling = sibling.nextElementSibling;
          }
        }

        parts.unshift(needsIndex ? `${tag}[${index}]` : tag);
        current = current.parentElement;
      }

      return parts.length > 0 ? '//' + parts.join('/') : null;
    },

    isUnique(xpath, element) {
      try {
        const result = document.evaluate(xpath, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
        return result.snapshotLength === 1 && result.snapshotItem(0) === element;
      } catch (e) {
        return false;
      }
    },

    getVisibleText(element) {
      const text = (element.innerText || element.textContent || '').trim();
      // 对于长文本，取前50个字符
      return text.substring(0, CONFIG.maxTextLength).replace(/\n+/g, ' ').trim();
    },
  };

  // ========================================================================
  // 遮挡检测器
  // ========================================================================
  const OcclusionDetector = {
    isVisibleAndUnoccluded(element) {
      const rect = element.getBoundingClientRect();

      if (rect.width === 0 || rect.height === 0) {
        return { visible: false, reason: 'zero-size' };
      }

      if (rect.bottom < 0 || rect.top > window.innerHeight ||
          rect.right < 0 || rect.left > window.innerWidth) {
        return { visible: false, reason: 'outside-viewport' };
      }

      const style = window.getComputedStyle(element);
      if (style.display === 'none' || style.visibility === 'hidden' ||
          parseFloat(style.opacity) < 0.1) {
        return { visible: false, reason: 'css-hidden' };
      }

      // 检查是否被裁剪
      if (this.isClippedByParent(element, rect)) {
        return { visible: false, reason: 'clipped' };
      }

      // 多点遮挡检测
      const occlusionResult = this.checkOcclusionMultiPoint(element, rect);
      if (!occlusionResult.visible) {
        return occlusionResult;
      }

      return { visible: true, zIndex: this.getZIndex(element) };
    },

    isClippedByParent(element, rect) {
      let parent = element.parentElement;

      while (parent && parent !== document.body) {
        const parentStyle = window.getComputedStyle(parent);
        const overflow = parentStyle.overflow + parentStyle.overflowX + parentStyle.overflowY;
        
        if (overflow.includes('hidden') || overflow.includes('scroll') || overflow.includes('auto')) {
          const parentRect = parent.getBoundingClientRect();
          
          const visibleWidth = Math.min(rect.right, parentRect.right) - Math.max(rect.left, parentRect.left);
          const visibleHeight = Math.min(rect.bottom, parentRect.bottom) - Math.max(rect.top, parentRect.top);
          const visibleArea = Math.max(0, visibleWidth) * Math.max(0, visibleHeight);
          const totalArea = rect.width * rect.height;

          if (totalArea > 0 && visibleArea / totalArea < 0.3) {
            return true;
          }
        }

        parent = parent.parentElement;
      }

      return false;
    },

    checkOcclusionMultiPoint(element, rect) {
      const testPoints = [
        { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2, weight: 3 },
        { x: rect.left + rect.width * 0.2, y: rect.top + rect.height / 2, weight: 2 },
        { x: rect.left + rect.width * 0.8, y: rect.top + rect.height / 2, weight: 2 },
        { x: rect.left + rect.width / 2, y: rect.top + rect.height * 0.2, weight: 1 },
        { x: rect.left + rect.width / 2, y: rect.top + rect.height * 0.8, weight: 1 },
      ];

      let visibleScore = 0;
      let totalWeight = 0;

      for (const point of testPoints) {
        totalWeight += point.weight;

        if (point.x < 0 || point.x > window.innerWidth ||
            point.y < 0 || point.y > window.innerHeight) {
          continue;
        }

        const topElement = document.elementFromPoint(point.x, point.y);
        if (!topElement) continue;

        // 检查是否命中目标元素或其子元素
        if (element === topElement || element.contains(topElement) || topElement.contains(element)) {
          visibleScore += point.weight;
        }
      }

      return visibleScore / totalWeight >= 0.3 ? { visible: true } : { visible: false, reason: 'occluded' };
    },

    getZIndex(element) {
      let zIndex = 0;
      let current = element;
      while (current && current !== document.body) {
        const z = parseInt(window.getComputedStyle(current).zIndex, 10);
        if (!isNaN(z)) zIndex = Math.max(zIndex, z);
        current = current.parentElement;
      }
      return zIndex;
    },
  };

  // ========================================================================
  // 辅助函数
  // ========================================================================
  function calculateOverlapRatio(bbox1, bbox2) {
    const x1 = Math.max(bbox1.x, bbox2.x);
    const y1 = Math.max(bbox1.y, bbox2.y);
    const x2 = Math.min(bbox1.x + bbox1.width, bbox2.x + bbox2.width);
    const y2 = Math.min(bbox1.y + bbox1.height, bbox2.y + bbox2.height);

    if (x2 <= x1 || y2 <= y1) return 0;

    const intersectionArea = (x2 - x1) * (y2 - y1);
    const smallerArea = Math.min(bbox1.width * bbox1.height, bbox2.width * bbox2.height);
    return smallerArea > 0 ? intersectionArea / smallerArea : 0;
  }

  function getCleanText(element) {
    const text = (element.innerText || element.textContent || '').trim();
    return text.replace(/[\n\r\t]+/g, ' ').replace(/\s+/g, ' ').substring(0, CONFIG.maxTextLength);
  }

  // ========================================================================
  // SoM 覆盖层管理
  // ========================================================================
  const SoMOverlay = {
    containerId: '__som_overlay_container__',

    createContainer() {
      this.clear();
      const container = document.createElement('div');
      container.id = this.containerId;
      container.style.cssText = `
        position: fixed; top: 0; left: 0;
        width: 100vw; height: 100vh;
        pointer-events: none;
        z-index: 2147483647;
        overflow: hidden;
      `;
      document.body.appendChild(container);
      return container;
    },

    clear() {
      const existing = document.getElementById(this.containerId);
      if (existing) existing.remove();
      document.querySelectorAll('[data-som-id]').forEach(el => el.removeAttribute('data-som-id'));
    },

    drawMark(container, mark) {
      const { bbox, mark_id } = mark;

      const box = document.createElement('div');
      box.style.cssText = `
        position: fixed;
        left: ${bbox.x}px; top: ${bbox.y}px;
        width: ${bbox.width}px; height: ${bbox.height}px;
        border: ${CONFIG.boxStyle.border};
        background-color: ${CONFIG.boxStyle.backgroundColor};
        pointer-events: none; box-sizing: border-box;
        z-index: ${CONFIG.boxStyle.zIndex};
      `;

      let labelLeft = bbox.x + bbox.width - 5;
      let labelTop = bbox.y - 16;
      if (labelTop < 0) labelTop = bbox.y + 2;
      if (labelLeft + 30 > window.innerWidth) labelLeft = bbox.x + bbox.width - 30;

      const label = document.createElement('div');
      label.textContent = mark_id;
      label.style.cssText = `
        position: fixed;
        left: ${labelLeft}px; top: ${labelTop}px;
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
    const collectedElements = new Map(); // element -> source

    // 1. 收集严格选择器匹配的元素
    for (const selector of CONFIG.strictSelectors) {
      try {
        document.querySelectorAll(selector).forEach(el => {
          if (!collectedElements.has(el)) {
            collectedElements.set(el, 'strict');
          }
        });
      } catch (e) {}
    }

    // 2. 收集 cursor:pointer 的元素
    document.querySelectorAll('*').forEach(el => {
      try {
        const style = window.getComputedStyle(el);
        if (style.cursor === 'pointer') {
          const rect = el.getBoundingClientRect();
          if (rect.width >= CONFIG.minWidth && rect.width <= 800 &&
              rect.height >= CONFIG.minHeight && rect.height <= 600) {
            if (!collectedElements.has(el)) {
              collectedElements.set(el, 'cursor');
            }
          }
        }
      } catch (e) {}
    });

    // 3. 处理元素：如果在可点击祖先内，替换为祖先
    const processedElements = new Set();
    
    for (const [element, source] of collectedElements) {
      // 检查是否应该被替换为祖先元素
      const clickableAncestor = AncestorChecker.findClickableAncestor(element);
      
      if (clickableAncestor) {
        // 使用祖先元素代替
        processedElements.add(clickableAncestor);
      } else {
        // 使用元素本身
        processedElements.add(element);
      }
    }

    // 4. 验证和生成标注
    const marks = [];
    let markId = 1;
    const markedBboxes = [];

    // 按位置排序
    const sortedElements = Array.from(processedElements).sort((a, b) => {
      const rectA = a.getBoundingClientRect();
      const rectB = b.getBoundingClientRect();
      const yDiff = rectA.top - rectB.top;
      return Math.abs(yDiff) > 10 ? yDiff : rectA.left - rectB.left;
    });

    for (const element of sortedElements) {
      if (markId > CONFIG.maxMarks) break;

      const rect = element.getBoundingClientRect();
      if (rect.width < CONFIG.minWidth || rect.height < CONFIG.minHeight) continue;

      // 可点击性验证
      const clickability = ClickabilityValidator.isClickable(element);
      if (!clickability.clickable) continue;

      // 可见性验证
      const visibility = OcclusionDetector.isVisibleAndUnoccluded(element);
      if (!visibility.visible) continue;

      // 构建边界框
      const newBbox = { x: rect.left, y: rect.top, width: rect.width, height: rect.height };

      // 重叠检测
      let isDuplicate = false;
      let indexToRemove = -1;

      for (let i = 0; i < markedBboxes.length; i++) {
        const overlapRatio = calculateOverlapRatio(newBbox, markedBboxes[i]);
        if (overlapRatio > 0.7) {
          const newArea = newBbox.width * newBbox.height;
          const existingArea = markedBboxes[i].width * markedBboxes[i].height;

          // 保留更大的元素（更完整的交互区域）
          if (newArea > existingArea * 1.1) {
            indexToRemove = i;
            break;
          } else {
            isDuplicate = true;
            break;
          }
        }
      }

      if (indexToRemove !== -1) {
        marks.splice(indexToRemove, 1);
        markedBboxes.splice(indexToRemove, 1);
      }

      if (isDuplicate) continue;

      // 生成标注
      const xpathCandidates = XPathGenerator.generateCandidates(element);
      const text = getCleanText(element);

      const mark = {
        mark_id: markId,
        tag: element.tagName.toLowerCase(),
        role: element.getAttribute('role'),
        text: text,
        aria_label: element.getAttribute('aria-label'),
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
        clickability_reason: clickability.reason,
        clickability_confidence: clickability.confidence,
      };

      element.setAttribute('data-som-id', markId);
      marks.push(mark);
      markedBboxes.push(newBbox);
      markId++;
    }

    // 绘制覆盖层
    const container = SoMOverlay.createContainer();
    marks.forEach(mark => SoMOverlay.drawMark(container, mark));

    return {
      url: window.location.href,
      title: document.title,
      viewport_width: window.innerWidth,
      viewport_height: window.innerHeight,
      marks,
      timestamp: Date.now() / 1000,
      scroll_info: getScrollInfo(),
    };
  }

  function getScrollInfo() {
    const scrollTop = window.scrollY || document.documentElement.scrollTop || 0;
    const scrollHeight = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
    const clientHeight = window.innerHeight;
    const maxScroll = scrollHeight - clientHeight;
    const scrollPercent = maxScroll > 0 ? Math.round((scrollTop / maxScroll) * 100) : 100;

    return {
      scroll_top: Math.round(scrollTop),
      scroll_height: Math.round(scrollHeight),
      client_height: Math.round(clientHeight),
      scroll_percent: scrollPercent,
      is_at_top: scrollTop <= 10,
      is_at_bottom: scrollTop + clientHeight >= scrollHeight - 10,
      can_scroll_down: scrollTop + clientHeight < scrollHeight - 10,
      can_scroll_up: scrollTop > 10,
    };
  }

  // 暴露 API
  window.__SOM__ = {
    scan: scanAndMark,
    clear: () => SoMOverlay.clear(),
    getElement: (id) => document.querySelector(`[data-som-id="${id}"]`),
    setVisibility: (v) => {
      const c = document.getElementById(SoMOverlay.containerId);
      if (c) c.style.display = v ? 'block' : 'none';
    },
    _debug: { 
      ClickabilityValidator, 
      OcclusionDetector, 
      XPathGenerator, 
      AncestorChecker,
      CONFIG 
    },
  };

  return scanAndMark();
})();