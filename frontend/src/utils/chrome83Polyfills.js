/**
 * Chrome 83 Polyfills
 * 
 * 为信创浏览器(Chrome 83)补充缺失的 JS API。
 * 必须在所有业务代码之前加载。
 */

// Object.hasOwn — Chrome 93+
if (typeof Object.hasOwn !== 'function') {
  Object.hasOwn = function (obj, prop) {
    return Object.prototype.hasOwnProperty.call(obj, prop)
  }
}

// structuredClone — Chrome 98+
if (typeof globalThis.structuredClone !== 'function') {
  globalThis.structuredClone = function (value) {
    return JSON.parse(JSON.stringify(value))
  }
}

// String.prototype.replaceAll — Chrome 85+
if (typeof String.prototype.replaceAll !== 'function') {
  String.prototype.replaceAll = function (search, replacement) {
    if (search instanceof RegExp) {
      if (!search.global) {
        throw new TypeError('String.prototype.replaceAll called with a non-global RegExp argument')
      }
      return this.replace(search, replacement)
    }
    return this.split(search).join(replacement)
  }
}

// Array.prototype.at — Chrome 92+
if (typeof Array.prototype.at !== 'function') {
  Array.prototype.at = function (index) {
    var n = Math.trunc(index) || 0
    if (n < 0) n += this.length
    if (n < 0 || n >= this.length) return undefined
    return this[n]
  }
}

// String.prototype.at — Chrome 92+
if (typeof String.prototype.at !== 'function') {
  String.prototype.at = function (index) {
    var n = Math.trunc(index) || 0
    if (n < 0) n += this.length
    if (n < 0 || n >= this.length) return undefined
    return this.charAt(n)
  }
}

// Array.prototype.findLast — Chrome 97+
if (typeof Array.prototype.findLast !== 'function') {
  Array.prototype.findLast = function (fn, thisArg) {
    for (var i = this.length - 1; i >= 0; i--) {
      if (fn.call(thisArg, this[i], i, this)) return this[i]
    }
    return undefined
  }
}

// Array.prototype.findLastIndex — Chrome 97+
if (typeof Array.prototype.findLastIndex !== 'function') {
  Array.prototype.findLastIndex = function (fn, thisArg) {
    for (var i = this.length - 1; i >= 0; i--) {
      if (fn.call(thisArg, this[i], i, this)) return i
    }
    return -1
  }
}

// globalThis — Chrome 71+ (safe but included for completeness)
if (typeof globalThis === 'undefined') {
  (function () {
    if (typeof self !== 'undefined') { self.globalThis = self }
    else if (typeof window !== 'undefined') { window.globalThis = window }
  })()
}
