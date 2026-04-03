/**
 * Flex Gap Polyfill
 * 
 * 检测浏览器是否支持 flexbox gap 属性。
 * 如果不支持（如360信创浏览器/Chrome <84），通过 MutationObserver
 * 自动将 inline style 中的 gap 转换为子元素 margin。
 */

function supportsFlexGap() {
  // 创建测试元素检测 flex gap 支持
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
}

function applyGapPolyfill() {
  if (supportsFlexGap()) {
    return // 浏览器原生支持，不需要 polyfill
  }

  console.log('[FlexGapPolyfill] 浏览器不支持 flex gap，启用 polyfill')

  // 给 body 添加标记类
  document.body.classList.add('no-flex-gap')

  function fixGap(element) {
    var style = element.style
    if (!style) return

    var display = style.display
    if (display !== 'flex' && display !== 'inline-flex') return

    var gap = style.gap
    if (!gap || gap === '0' || gap === '0px') return

    // 解析 gap 值
    var gapValue = parseInt(gap, 10)
    if (isNaN(gapValue) || gapValue <= 0) return

    // 确定方向
    var direction = style.flexDirection || 'row'
    var isColumn = direction.indexOf('column') !== -1
    var isWrap = style.flexWrap === 'wrap'

    // 清除 gap（移除不被识别的属性，避免无效属性警告）
    style.gap = ''

    // 给子元素加 margin
    var children = element.children
    for (var i = 0; i < children.length; i++) {
      var child = children[i]
      if (isColumn) {
        if (i > 0) child.style.marginTop = gapValue + 'px'
      } else {
        if (i > 0) child.style.marginLeft = gapValue + 'px'
      }
      if (isWrap && !isColumn) {
        child.style.marginBottom = gapValue + 'px'
      }
    }
  }

  function fixAllGaps() {
    // 修复所有 flex 容器
    var flexElements = document.querySelectorAll('[style]')
    for (var i = 0; i < flexElements.length; i++) {
      fixGap(flexElements[i])
    }
  }

  // 初始修复
  fixAllGaps()

  // 监听 DOM 变化
  if (typeof MutationObserver !== 'undefined') {
    var observer = new MutationObserver(function (mutations) {
      var needsFix = false
      for (var i = 0; i < mutations.length; i++) {
        var mutation = mutations[i]
        if (mutation.type === 'childList' && mutation.addedNodes.length > 0) {
          needsFix = true
          break
        }
        if (mutation.type === 'attributes' && mutation.attributeName === 'style') {
          fixGap(mutation.target)
        }
      }
      if (needsFix) {
        // 延迟修复，让 React 完成渲染
        setTimeout(fixAllGaps, 50)
      }
    })
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['style'],
    })
  } else {
    // 降级：定期检查
    setInterval(fixAllGaps, 1000)
  }
}

export default applyGapPolyfill
