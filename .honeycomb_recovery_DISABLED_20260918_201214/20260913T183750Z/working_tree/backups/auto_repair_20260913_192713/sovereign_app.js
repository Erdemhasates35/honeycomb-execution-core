#!/usr/bin/env node
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
globalThis.__filename = require('url').fileURLToPath(import.meta.url);
globalThis.__dirname = require('path').dirname(globalThis.__filename);

var __create = Object.create;
var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __getProtoOf = Object.getPrototypeOf;
var __hasOwnProp = Object.prototype.hasOwnProperty;

var __commonJS = (cb, mod2) => function __require2() {
  return mod2 || (0, cb[__getOwnPropNames(cb)[0]])((mod2 = { exports: {} }).exports, mod2), mod2.exports;
};

// React Production Core Initialization
var require_react_production = __commonJS({
  "node_modules/react/cjs/react.production.js"(exports2) {
    "use strict";
    var REACT_ELEMENT_TYPE = Symbol.for("react.transitional.element");
    var REACT_PORTAL_TYPE = Symbol.for("react.portal");
    var REACT_FRAGMENT_TYPE = Symbol.for("react.fragment");

    function ReactElement(type, key, props) {
      return { $$typeof: REACT_ELEMENT_TYPE, type, key, ref: props.ref || null, props };
    }

    exports2.createElement = function(type, config2, children) {
      var propName, props = {}, key = null;
      if (null != config2) {
        for (propName in config2) {
          if (Object.prototype.hasOwnProperty.call(config2, propName) && propName !== "key") {
            props[propName] = config2[propName];
          }
        }
      }
      var childrenLength = arguments.length - 2;
      if (childrenLength === 1) props.children = children;
      else if (childrenLength > 1) {
        var childArray = Array(childrenLength);
        for (var i = 0; i < childrenLength; i++) childArray[i] = arguments[i + 2];
        props.children = childArray;
      }
      return ReactElement(type, key, props);
    };
    exports2.version = "19.2.0";
  }
});

var react = require_react_production();

// Application Core Runtime Entry Point
console.log("==================================================");
console.log("[NEXUS OS] Sovereign Node Engine Initialized");
console.log("[RUNTIME] Engine: Node.js " + process.version);
console.log("[REACT CORE] Loaded React Version: " + react.version);
console.log("==================================================");
