/**
 * Flex Gap Polyfill (增强版)
 * 
 * Chrome < 84 不支持 flex 容器的 gap 属性。
 * 本 polyfill 扫描所有 DOM 元素（包括 Ant Design CSS-in-JS 生成的），
 * 将 flex gap 转为子元素 margin。
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

  console.log('[FlexGapPolyfill] 浏览器不支持 flex gap，启用增强 polyfill')
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

  function fixElement(el) {
    if (!el || el.nodeType !== 1) return
    if (el.getAttribute('data-gap-fixed')) return

    var display = getComputedProp(el, 'display')
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
            m.target.removeAttribute('data-gap-fixed')
            fixElement(m.target)
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
