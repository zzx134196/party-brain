/**
 * Flex Gap Polyfill (增强版 v2)
 * 
 * Chrome < 84 不支持 flex 容器的 gap 属性。
 * Chrome < 84 不支持 Grid 容器的标准 gap 属性（需使用 grid-gap）。
 * 本 polyfill 扫描所有 DOM 元素（包括 Ant Design CSS-in-JS 生成的），
 * 将 flex gap 转为子元素 margin，将 grid gap 转为 grid-gap。
 * 
 * v2 改进：
 * - 排除 ant-upload 相关元素，避免干扰上传组件的点击交互
 * - 支持 CSS Grid 的 gap → grid-gap 兼容
 * - 优化性能，减少不必要的 DOM 操作
 */

function supportsFlexGap() {
  try {
    var flex = document.createElement('div')
    flex.style.display = 'flex'
    flex.style.flexDirection = 'column'
    flex.style.rowGap = '1px'
    flex.appendChild(document.createElement('div'))
    flex.appendChild(document.createElement('div'))
    document.body.appendChild(flex)
    var isSupported = flex.scrollHeight === 1
    document.body.removeChild(flex)
    return isSupported
  } catch (e) {
    return false
  }
}

function applyGapPolyfill() {
  if (supportsFlexGap()) {
    return
  }

  console.log('[FlexGapPolyfill] 浏览器不支持 flex gap，启用 polyfill')
  document.body.classList.add('no-flex-gap')

  function getComputedProp(el, prop) {
    try {
      return window.getComputedStyle(el)[prop] || ''
    } catch (e) {
      return ''
    }
  }

  function parseGapValue(val) {
    if (!val || val === 'normal' || val === '0' || val === '0px') return 0
    var num = parseInt(val, 10)
    return isNaN(num) ? 0 : num
  }

  /**
   * 检查元素是否属于 Upload 组件或其内部元素
   * Upload 组件不应被 polyfill 处理，否则会干扰点击事件
   */
  function isUploadElement(el) {
    if (!el || !el.className) return false
    var cls = typeof el.className === 'string' ? el.className : ''
    if (cls.indexOf('ant-upload') !== -1) return true
    // 检查父元素（最多往上查 3 层）
    var parent = el.parentElement
    for (var depth = 0; depth < 3 && parent; depth++) {
      var parentCls = typeof parent.className === 'string' ? parent.className : ''
      if (parentCls.indexOf('ant-upload') !== -1) return true
      parent = parent.parentElement
    }
    return false
  }

  function fixElement(el) {
    if (!el || el.nodeType !== 1) return
    if (el.getAttribute('data-gap-fixed')) return
    // 排除 Upload 组件
    if (isUploadElement(el)) return

    var display = getComputedProp(el, 'display')

    // 处理 Grid 容器的 gap
    if (display === 'grid' || display === 'inline-grid' ||
        display === '-ms-grid') {
      var gridGap = parseGapValue(el.style.gap)
      if (gridGap > 0) {
        el.style.gridGap = gridGap + 'px'
        el.style.gap = ''
        el.setAttribute('data-gap-fixed', '1')
      }
      return
    }

    // 处理 Flex 容器的 gap
    if (display !== 'flex' && display !== 'inline-flex' &&
        display !== '-webkit-flex' && display !== '-webkit-inline-flex') return

    var rowGap = parseGapValue(getComputedProp(el, 'rowGap') || getComputedProp(el, 'row-gap'))
    var colGap = parseGapValue(getComputedProp(el, 'columnGap') || getComputedProp(el, 'column-gap'))

    if (rowGap === 0 && colGap === 0) {
      var gap = parseGapValue(el.style.gap)
      if (gap > 0) {
        rowGap = gap
        colGap = gap
      } else {
        return
      }
    }

    var direction = getComputedProp(el, 'flexDirection') || 'row'
    var isColumn = direction.indexOf('column') !== -1

    el.style.gap = '0px'
    el.style.rowGap = '0px'
    el.style.columnGap = '0px'
    el.setAttribute('data-gap-fixed', '1')

    var children = el.children
    for (var i = 0; i < children.length; i++) {
      var child = children[i]
      // 跳过隐藏的 input[type=file]（Upload 组件核心元素）
      if (child.tagName === 'INPUT' && child.type === 'file') continue
      if (isColumn) {
        if (i > 0 && rowGap > 0) child.style.marginTop = rowGap + 'px'
      } else {
        if (i > 0 && colGap > 0) child.style.marginLeft = colGap + 'px'
      }
    }
  }

  var _fixTimer = null
  function scheduleFixAll() {
    if (_fixTimer) return
    _fixTimer = setTimeout(function () {
      _fixTimer = null
      fixAll()
    }, 80)
  }

  function fixAll() {
    try {
      var all = document.querySelectorAll('*')
      for (var i = 0; i < all.length; i++) {
        fixElement(all[i])
      }
    } catch (e) { /* ignore */ }
  }

  fixAll()

  if (typeof MutationObserver !== 'undefined') {
    var observer = new MutationObserver(function (mutations) {
      var needsFix = false
      for (var i = 0; i < mutations.length; i++) {
        var m = mutations[i]
        if (m.type === 'childList' && m.addedNodes.length > 0) {
          needsFix = true
          break
        }
        if (m.type === 'attributes') {
          if (m.target && m.target.nodeType === 1) {
            // 不重置 Upload 组件的标记
            if (!isUploadElement(m.target)) {
              m.target.removeAttribute('data-gap-fixed')
              fixElement(m.target)
            }
          }
        }
      }
      if (needsFix) {
        scheduleFixAll()
      }
    })
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['style', 'class'],
    })
  } else {
    setInterval(fixAll, 2000)
  }
}

export default applyGapPolyfill
