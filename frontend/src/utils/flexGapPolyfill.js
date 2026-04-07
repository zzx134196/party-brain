/**
 * Flex Gap Polyfill (增强版 v3 — 信创浏览器专项优化)
 *
 * Chrome < 84 不支持 flex 容器的 gap 属性。
 * Chrome < 84 不支持 Grid 容器的标准 gap 属性（需使用 grid-gap）。
 *
 * v3 改进：
 * - 排除 ant-upload 相关元素，避免干扰上传组件的点击交互
 * - 支持 CSS Grid 的 gap → grid-gap 兼容
 * - 支持 flex-wrap 场景下的 row-gap → margin-top 转换
 * - 处理 Ant Design 动态注入样式的 gap
 * - 优化 MutationObserver 回调，减少抖动
 * - 缓存检测结果，避免每次都检测
 */

var _flexGapSupported = null

function supportsFlexGap() {
  if (_flexGapSupported !== null) return _flexGapSupported
  try {
    var flex = document.createElement('div')
    flex.style.display = 'flex'
    flex.style.flexDirection = 'column'
    flex.style.rowGap = '1px'
    flex.appendChild(document.createElement('div'))
    flex.appendChild(document.createElement('div'))
    document.body.appendChild(flex)
    _flexGapSupported = flex.scrollHeight === 1
    document.body.removeChild(flex)
  } catch (e) {
    _flexGapSupported = false
  }
  return _flexGapSupported
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
    var num = parseFloat(val)
    return isNaN(num) ? 0 : num
  }

  function isUploadElement(el) {
    if (!el || !el.className) return false
    var cls = typeof el.className === 'string' ? el.className : ''
    if (cls.indexOf('ant-upload') !== -1) return true
    var parent = el.parentElement
    for (var depth = 0; depth < 5 && parent; depth++) {
      var parentCls = typeof parent.className === 'string' ? parent.className : ''
      if (parentCls.indexOf('ant-upload') !== -1) return true
      parent = parent.parentElement
    }
    return false
  }

  function fixElement(el) {
    if (!el || el.nodeType !== 1) return
    if (el.getAttribute('data-gap-fixed')) return
    if (isUploadElement(el)) return

    var display = getComputedProp(el, 'display')

    // Grid gap → grid-gap
    if (display === 'grid' || display === 'inline-grid' || display === '-ms-grid') {
      var gridGapVal = el.style.gap || getComputedProp(el, 'gap')
      var gridGap = parseGapValue(gridGapVal)
      if (gridGap > 0) {
        el.style.gridGap = gridGap + 'px'
        el.style.gap = ''
        el.setAttribute('data-gap-fixed', '1')
      }
      return
    }

    // Flex gap
    if (display !== 'flex' && display !== 'inline-flex' &&
        display !== '-webkit-flex' && display !== '-webkit-inline-flex') return

    var rowGap = parseGapValue(getComputedProp(el, 'rowGap') || getComputedProp(el, 'row-gap'))
    var colGap = parseGapValue(getComputedProp(el, 'columnGap') || getComputedProp(el, 'column-gap'))

    if (rowGap === 0 && colGap === 0) {
      var inlineGap = el.style.gap
      if (inlineGap) {
        var parts = inlineGap.trim().split(/\s+/)
        rowGap = parseGapValue(parts[0])
        colGap = parseGapValue(parts[1] || parts[0])
      }
      if (rowGap === 0 && colGap === 0) return
    }

    var direction = getComputedProp(el, 'flexDirection') || 'row'
    var isColumn = direction.indexOf('column') !== -1
    var isWrap = getComputedProp(el, 'flexWrap')
    var wrapping = isWrap === 'wrap' || isWrap === 'wrap-reverse'

    el.style.gap = '0px'
    el.style.rowGap = '0px'
    el.style.columnGap = '0px'
    el.setAttribute('data-gap-fixed', '1')

    var children = el.children
    if (isColumn) {
      for (var i = 0; i < children.length; i++) {
        var child = children[i]
        if (child.tagName === 'INPUT' && child.type === 'file') continue
        if (getComputedProp(child, 'display') === 'none') continue
        if (i > 0 && rowGap > 0) child.style.marginTop = rowGap + 'px'
        if (wrapping && colGap > 0 && i > 0) child.style.marginLeft = colGap + 'px'
      }
    } else {
      if (wrapping) {
        for (var j = 0; j < children.length; j++) {
          var wChild = children[j]
          if (wChild.tagName === 'INPUT' && wChild.type === 'file') continue
          if (getComputedProp(wChild, 'display') === 'none') continue
          if (colGap > 0) wChild.style.marginRight = colGap + 'px'
          if (rowGap > 0) wChild.style.marginBottom = rowGap + 'px'
        }
        el.style.marginRight = '-' + colGap + 'px'
        el.style.marginBottom = '-' + rowGap + 'px'
      } else {
        for (var k = 0; k < children.length; k++) {
          var rChild = children[k]
          if (rChild.tagName === 'INPUT' && rChild.type === 'file') continue
          if (getComputedProp(rChild, 'display') === 'none') continue
          if (k > 0 && colGap > 0) rChild.style.marginLeft = colGap + 'px'
        }
      }
    }
  }

  var _fixTimer = null
  function scheduleFixAll() {
    if (_fixTimer) return
    _fixTimer = setTimeout(function () {
      _fixTimer = null
      fixAll()
    }, 100)
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
