/* eslint-disable */
/* GENERATO da tools/build_anomalie_apertura.js da src/apertura_segnalazione.jsx: non modificare a mano. */
"use strict";

var _excluded = ["key"];
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
function _objectWithoutProperties(e, t) { if (null == e) return {}; var o, r, i = _objectWithoutPropertiesLoose(e, t); if (Object.getOwnPropertySymbols) { var n = Object.getOwnPropertySymbols(e); for (r = 0; r < n.length; r++) o = n[r], -1 === t.indexOf(o) && {}.propertyIsEnumerable.call(e, o) && (i[o] = e[o]); } return i; }
function _objectWithoutPropertiesLoose(r, e) { if (null == r) return {}; var t = {}; for (var n in r) if ({}.hasOwnProperty.call(r, n)) { if (-1 !== e.indexOf(n)) continue; t[n] = r[n]; } return t; }
function _typeof(o) { "@babel/helpers - typeof"; return _typeof = "function" == typeof Symbol && "symbol" == typeof Symbol.iterator ? function (o) { return typeof o; } : function (o) { return o && "function" == typeof Symbol && o.constructor === Symbol && o !== Symbol.prototype ? "symbol" : typeof o; }, _typeof(o); }
function _toConsumableArray(r) { return _arrayWithoutHoles(r) || _iterableToArray(r) || _unsupportedIterableToArray(r) || _nonIterableSpread(); }
function _nonIterableSpread() { throw new TypeError("Invalid attempt to spread non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); }
function _iterableToArray(r) { if ("undefined" != typeof Symbol && null != r[Symbol.iterator] || null != r["@@iterator"]) return Array.from(r); }
function _arrayWithoutHoles(r) { if (Array.isArray(r)) return _arrayLikeToArray(r); }
function _slicedToArray(r, e) { return _arrayWithHoles(r) || _iterableToArrayLimit(r, e) || _unsupportedIterableToArray(r, e) || _nonIterableRest(); }
function _nonIterableRest() { throw new TypeError("Invalid attempt to destructure non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method."); }
function _unsupportedIterableToArray(r, a) { if (r) { if ("string" == typeof r) return _arrayLikeToArray(r, a); var t = {}.toString.call(r).slice(8, -1); return "Object" === t && r.constructor && (t = r.constructor.name), "Map" === t || "Set" === t ? Array.from(r) : "Arguments" === t || /^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(t) ? _arrayLikeToArray(r, a) : void 0; } }
function _arrayLikeToArray(r, a) { (null == a || a > r.length) && (a = r.length); for (var e = 0, n = Array(a); e < a; e++) n[e] = r[e]; return n; }
function _iterableToArrayLimit(r, l) { var t = null == r ? null : "undefined" != typeof Symbol && r[Symbol.iterator] || r["@@iterator"]; if (null != t) { var e, n, i, u, a = [], f = !0, o = !1; try { if (i = (t = t.call(r)).next, 0 === l) { if (Object(t) !== t) return; f = !1; } else for (; !(f = (e = i.call(t)).done) && (a.push(e.value), a.length !== l); f = !0); } catch (r) { o = !0, n = r; } finally { try { if (!f && null != t["return"] && (u = t["return"](), Object(u) !== u)) return; } finally { if (o) throw n; } } return a; } }
function _arrayWithHoles(r) { if (Array.isArray(r)) return r; }
function ownKeys(e, r) { var t = Object.keys(e); if (Object.getOwnPropertySymbols) { var o = Object.getOwnPropertySymbols(e); r && (o = o.filter(function (r) { return Object.getOwnPropertyDescriptor(e, r).enumerable; })), t.push.apply(t, o); } return t; }
function _objectSpread(e) { for (var r = 1; r < arguments.length; r++) { var t = null != arguments[r] ? arguments[r] : {}; r % 2 ? ownKeys(Object(t), !0).forEach(function (r) { _defineProperty(e, r, t[r]); }) : Object.getOwnPropertyDescriptors ? Object.defineProperties(e, Object.getOwnPropertyDescriptors(t)) : ownKeys(Object(t)).forEach(function (r) { Object.defineProperty(e, r, Object.getOwnPropertyDescriptor(t, r)); }); } return e; }
function _defineProperty(e, r, t) { return (r = _toPropertyKey(r)) in e ? Object.defineProperty(e, r, { value: t, enumerable: !0, configurable: !0, writable: !0 }) : e[r] = t, e; }
function _toPropertyKey(t) { var i = _toPrimitive(t, "string"); return "symbol" == _typeof(i) ? i : i + ""; }
function _toPrimitive(t, r) { if ("object" != _typeof(t) || !t) return t; var e = t[Symbol.toPrimitive]; if (void 0 !== e) { var i = e.call(t, r || "default"); if ("object" != _typeof(i)) return i; throw new TypeError("@@toPrimitive must return a primitive value."); } return ("string" === r ? String : Number)(t); }
function _regenerator() { /*! regenerator-runtime -- Copyright (c) 2014-present, Facebook, Inc. -- license (MIT): https://github.com/babel/babel/blob/main/packages/babel-helpers/LICENSE */ var e, t, r = "function" == typeof Symbol ? Symbol : {}, n = r.iterator || "@@iterator", o = r.toStringTag || "@@toStringTag"; function i(r, n, o, i) { var c = n && n.prototype instanceof Generator ? n : Generator, u = Object.create(c.prototype); return _regeneratorDefine2(u, "_invoke", function (r, n, o) { var i, c, u, f = 0, p = o || [], y = !1, G = { p: 0, n: 0, v: e, a: d, f: d.bind(e, 4), d: function d(t, r) { return i = t, c = 0, u = e, G.n = r, a; } }; function d(r, n) { for (c = r, u = n, t = 0; !y && f && !o && t < p.length; t++) { var o, i = p[t], d = G.p, l = i[2]; r > 3 ? (o = l === n) && (u = i[(c = i[4]) ? 5 : (c = 3, 3)], i[4] = i[5] = e) : i[0] <= d && ((o = r < 2 && d < i[1]) ? (c = 0, G.v = n, G.n = i[1]) : d < l && (o = r < 3 || i[0] > n || n > l) && (i[4] = r, i[5] = n, G.n = l, c = 0)); } if (o || r > 1) return a; throw y = !0, n; } return function (o, p, l) { if (f > 1) throw TypeError("Generator is already running"); for (y && 1 === p && d(p, l), c = p, u = l; (t = c < 2 ? e : u) || !y;) { i || (c ? c < 3 ? (c > 1 && (G.n = -1), d(c, u)) : G.n = u : G.v = u); try { if (f = 2, i) { if (c || (o = "next"), t = i[o]) { if (!(t = t.call(i, u))) throw TypeError("iterator result is not an object"); if (!t.done) return t; u = t.value, c < 2 && (c = 0); } else 1 === c && (t = i["return"]) && t.call(i), c < 2 && (u = TypeError("The iterator does not provide a '" + o + "' method"), c = 1); i = e; } else if ((t = (y = G.n < 0) ? u : r.call(n, G)) !== a) break; } catch (t) { i = e, c = 1, u = t; } finally { f = 1; } } return { value: t, done: y }; }; }(r, o, i), !0), u; } var a = {}; function Generator() {} function GeneratorFunction() {} function GeneratorFunctionPrototype() {} t = Object.getPrototypeOf; var c = [][n] ? t(t([][n]())) : (_regeneratorDefine2(t = {}, n, function () { return this; }), t), u = GeneratorFunctionPrototype.prototype = Generator.prototype = Object.create(c); function f(e) { return Object.setPrototypeOf ? Object.setPrototypeOf(e, GeneratorFunctionPrototype) : (e.__proto__ = GeneratorFunctionPrototype, _regeneratorDefine2(e, o, "GeneratorFunction")), e.prototype = Object.create(u), e; } return GeneratorFunction.prototype = GeneratorFunctionPrototype, _regeneratorDefine2(u, "constructor", GeneratorFunctionPrototype), _regeneratorDefine2(GeneratorFunctionPrototype, "constructor", GeneratorFunction), GeneratorFunction.displayName = "GeneratorFunction", _regeneratorDefine2(GeneratorFunctionPrototype, o, "GeneratorFunction"), _regeneratorDefine2(u), _regeneratorDefine2(u, o, "Generator"), _regeneratorDefine2(u, n, function () { return this; }), _regeneratorDefine2(u, "toString", function () { return "[object Generator]"; }), (_regenerator = function _regenerator() { return { w: i, m: f }; })(); }
function _regeneratorDefine2(e, r, n, t) { var i = Object.defineProperty; try { i({}, "", {}); } catch (e) { i = 0; } _regeneratorDefine2 = function _regeneratorDefine(e, r, n, t) { function o(r, n) { _regeneratorDefine2(e, r, function (e) { return this._invoke(r, n, e); }); } r ? i ? i(e, r, { value: n, enumerable: !t, configurable: !t, writable: !t }) : e[r] = n : (o("next", 0), o("throw", 1), o("return", 2)); }, _regeneratorDefine2(e, r, n, t); }
function asyncGeneratorStep(n, t, e, r, o, a, c) { try { var i = n[a](c), u = i.value; } catch (n) { return void e(n); } i.done ? t(u) : Promise.resolve(u).then(r, o); }
function _asyncToGenerator(n) { return function () { var t = this, e = arguments; return new Promise(function (r, o) { var a = n.apply(t, e); function _next(n) { asyncGeneratorStep(a, r, o, _next, _throw, "next", n); } function _throw(n) { asyncGeneratorStep(a, r, o, _next, _throw, "throw", n); } _next(void 0); }); }; }
/* eslint-disable */
/* SORGENTE del bundle UI «Controllo anomalie» (apertura_segnalazione).
   Estratto dallo <script type="text/babel"> inline (prima Babel nel browser a ogni apertura)
   e transpilato offline (solo JSX) con tools/build_anomalie_ui.ps1 in
   anomalie/static/anomalie/js/apertura_segnalazione.bundle.js. Modificare QUI, poi ricompilare. */
var _React = React,
  useState = _React.useState,
  useEffect = _React.useEffect,
  useRef = _React.useRef;
var API = window._AP_API || {
  db_ordini: '/api/anomalie/db/ordini',
  db_ordini_crea: '/api/anomalie/db/ordini/crea',
  salva: '/api/anomalie/salva',
  notifica_op: '/api/anomalie/notifica-op',
  seriali_op: '/api/anomalie/seriali-op',
  allegati_upload: '/api/anomalie/allegati/upload',
  copilota: '/api/anomalie/copilota',
  controlli: '/api/anomalie/controlli',
  controllo_apri: '/api/anomalie/controlli/apri',
  controlli_sospesi: '/api/anomalie/controlli/sospesi',
  controllo_prendi: '/api/anomalie/controlli/0/prendi',
  controllo_dettaglio: '/api/anomalie/controlli/0',
  controllo_impostazioni: '/api/anomalie/controlli/0/impostazioni',
  controllo_blocco: '/api/anomalie/controlli/0/blocco',
  controllo_termina: '/api/anomalie/controlli/0/termina',
  controllo_cambia_op: '/api/anomalie/controlli/0/cambia-op',
  controllo_bozza: '/api/anomalie/controlli/0/bozza',
  controllo_destinatari: '/api/anomalie/controlli/destinatari',
  controllo_persone: '/api/anomalie/controlli/persone',
  clona: '/api/anomalie/clona',
  allegati_copia: '/api/anomalie/allegati/copia',
  report_cmm: '/api/anomalie/report-cmm/leggi',
  elimina: '/api/anomalie/elimina',
  sposta: '/api/anomalie/sposta'
};

/* Clonazione da Gestione anomalie: ?clona_da=<OP>&anomalie=<id,id,…> */
var CLONA_PARAMS = function () {
  var q = new URLSearchParams(window.location.search);
  var da = (q.get('clona_da') || '').trim();
  var ids = (q.get('anomalie') || '').split(',').map(function (x) {
    return x.trim();
  }).filter(function (x) {
    return /^\d+$/.test(x);
  });
  return da && ids.length ? {
    da: da,
    ids: ids
  } : null;
}();
var contaClona = function contaClona(c) {
  return c ? c.blocchi.reduce(function (n, b) {
    return n + b.anomalie.length;
  }, 0) : 0;
};
var cfgLists = window._AP_CONFIG_LISTS || {};
var CFG_CAPI_REPARTO = Array.isArray(cfgLists.capi_reparto) ? cfgLists.capi_reparto : [];
var CFG_CAPI_COMMESSA = Array.isArray(cfgLists.capi_commessa) ? cfgLists.capi_commessa : [];
var CFG_CAUSALI_DOC = Array.isArray(cfgLists.causali_doc) && cfgLists.causali_doc.length ? cfgLists.causali_doc : ['OP', 'OG'];
var CFG_STATI_SUPERFICIE = Array.isArray(cfgLists.stati_superficie) && cfgLists.stati_superficie.length ? cfgLists.stati_superficie : ['Finito macchinato', 'Con sovrametallo', 'Finito trattato'];

/* ── CSRF ── */
var getCsrf = function getCsrf() {
  return (document.cookie.split(';').find(function (c) {
    return c.trim().startsWith('csrftoken=');
  }) || '').split('=')[1] || '';
};
var parseJsonSafe = /*#__PURE__*/function () {
  var _ref = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee(resp) {
    var fallback,
      _args = arguments,
      _t;
    return _regenerator().w(function (_context) {
      while (1) switch (_context.p = _context.n) {
        case 0:
          fallback = _args.length > 1 && _args[1] !== undefined ? _args[1] : null;
          _context.p = 1;
          _context.n = 2;
          return resp.json();
        case 2:
          return _context.a(2, _context.v);
        case 3:
          _context.p = 3;
          _t = _context.v;
          return _context.a(2, fallback);
      }
    }, _callee, null, [[1, 3]]);
  }));
  return function parseJsonSafe(_x) {
    return _ref.apply(this, arguments);
  };
}();
var parseJsonStrict = /*#__PURE__*/function () {
  var _ref2 = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee2(resp, context) {
    var ct, txt, _t2;
    return _regenerator().w(function (_context2) {
      while (1) switch (_context2.p = _context2.n) {
        case 0:
          ct = String(resp.headers.get('content-type') || '').toLowerCase();
          if (ct.includes('application/json')) {
            _context2.n = 3;
            break;
          }
          _context2.n = 1;
          return resp.text();
        case 1:
          txt = _context2.v;
          if (!/<!doctype html/i.test(txt || '')) {
            _context2.n = 2;
            break;
          }
          throw new Error("".concat(context, ": risposta HTML (login/sessione/404)"));
        case 2:
          throw new Error("".concat(context, ": risposta non JSON (HTTP ").concat(resp.status, ")"));
        case 3:
          _context2.p = 3;
          _context2.n = 4;
          return resp.json();
        case 4:
          return _context2.a(2, _context2.v);
        case 5:
          _context2.p = 5;
          _t2 = _context2.v;
          throw new Error("".concat(context, ": JSON non valido"));
        case 6:
          return _context2.a(2);
      }
    }, _callee2, null, [[3, 5]]);
  }));
  return function parseJsonStrict(_x2, _x3) {
    return _ref2.apply(this, arguments);
  };
}();
var formatBytes = function formatBytes(value) {
  var bytes = Number(value || 0);
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B';
  var units = ['B', 'KB', 'MB', 'GB'];
  var idx = 0;
  var n = bytes;
  while (n >= 1024 && idx < units.length - 1) {
    n /= 1024;
    idx += 1;
  }
  return "".concat(n.toFixed(n >= 10 || idx === 0 ? 0 : 1), " ").concat(units[idx]);
};
var ALLEGATI_ALLOWED_EXT = new Set(['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.xlsm', '.csv']);
var ALLEGATI_MAX_MB = window._AP_UPLOAD_MAX_MB || 100;
var ALLEGATI_MAX_SIZE = ALLEGATI_MAX_MB * 1024 * 1024;

/* ── Step 1: Selezione OP ── */
var makeNewOpDraft = function makeNewOpDraft() {
  return {
    causale_doc: CFG_CAUSALI_DOC[0] || 'OP',
    anno: String(new Date().getFullYear()),
    numero: '',
    fase: '',
    pn: '',
    capocommessa: '',
    car: '',
    collaudo_benestare: false,
    note: ''
  };
};

/* Bozza del nuovo OP dai dati dell'OP clonato: resta da scrivere il numero. */
var newOpDaClona = function newOpDaClona(c) {
  var base = makeNewOpDraft();
  if (!c) return base;
  var parti = String(c.op.id || '').split('/');
  return _objectSpread(_objectSpread({}, base), {}, {
    causale_doc: parti.length === 3 && parti[0] ? parti[0] : base.causale_doc,
    pn: c.op.pn || '',
    capocommessa: c.op.capo || '',
    car: c.op.car || '',
    collaudo_benestare: String(c.op.stato || '').toLowerCase().includes('benestare')
  });
};
var ClonaBanner = function ClonaBanner(_ref3) {
  var clona = _ref3.clona,
    children = _ref3.children;
  return /*#__PURE__*/React.createElement("div", {
    className: "clona-banner"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("strong", null, "Copia da ", clona.op.id), clona.op.pn ? " \xB7 P/N ".concat(clona.op.pn) : '', ": ", contaClona(clona), " anomali", contaClona(clona) === 1 ? 'a' : 'e', " in ", clona.blocchi.length, " blocch", clona.blocchi.length === 1 ? 'o' : 'i', "."), children && /*#__PURE__*/React.createElement("div", {
    className: "field-hint"
  }, children));
};
var Step1SelectOP = function Step1SelectOP(_ref4) {
  var onSelect = _ref4.onSelect,
    clona = _ref4.clona;
  var _useState = useState([]),
    _useState2 = _slicedToArray(_useState, 2),
    ordini = _useState2[0],
    setOrdini = _useState2[1];
  var _useState3 = useState(true),
    _useState4 = _slicedToArray(_useState3, 2),
    loading = _useState4[0],
    setLoading = _useState4[1];
  var _useState5 = useState(''),
    _useState6 = _slicedToArray(_useState5, 2),
    err = _useState6[0],
    setErr = _useState6[1];
  var _useState7 = useState(''),
    _useState8 = _slicedToArray(_useState7, 2),
    search = _useState8[0],
    setSearch = _useState8[1];
  var _useState9 = useState(!!clona),
    _useState0 = _slicedToArray(_useState9, 2),
    showCreate = _useState0[0],
    setShowCreate = _useState0[1];
  var _useState1 = useState(false),
    _useState10 = _slicedToArray(_useState1, 2),
    creating = _useState10[0],
    setCreating = _useState10[1];
  var _useState11 = useState(''),
    _useState12 = _slicedToArray(_useState11, 2),
    createErr = _useState12[0],
    setCreateErr = _useState12[1];
  var _useState13 = useState(function () {
      return newOpDaClona(clona);
    }),
    _useState14 = _slicedToArray(_useState13, 2),
    newOp = _useState14[0],
    setNewOp = _useState14[1];
  var loadOrdini = function loadOrdini() {
    setLoading(true);
    setErr('');
    fetch(API.db_ordini, {
      credentials: 'same-origin'
    }).then(/*#__PURE__*/function () {
      var _ref5 = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee3(r) {
        var data;
        return _regenerator().w(function (_context3) {
          while (1) switch (_context3.n) {
            case 0:
              _context3.n = 1;
              return parseJsonSafe(r, []);
            case 1:
              data = _context3.v;
              if (r.ok) {
                _context3.n = 2;
                break;
              }
              throw new Error(data && data.error || 'HTTP ' + r.status);
            case 2:
              return _context3.a(2, data);
          }
        }, _callee3);
      }));
      return function (_x4) {
        return _ref5.apply(this, arguments);
      };
    }()).then(function (data) {
      setOrdini(Array.isArray(data) ? data : []);
      setLoading(false);
    })["catch"](function (e) {
      setErr(e.message || 'Errore caricamento ordini');
      setLoading(false);
    });
  };
  useEffect(function () {
    loadOrdini();
  }, []);
  var filtered = ordini.filter(function (op) {
    if (!search.trim()) return true;
    var q = search.toLowerCase();
    return (op.id || '').toLowerCase().includes(q) || (op.pn || '').toLowerCase().includes(q) || (op.capo || '').toLowerCase().includes(q) || (op.car || '').toLowerCase().includes(q);
  });
  var capocommessaOptions = Array.from(new Set([].concat(_toConsumableArray(CFG_CAPI_COMMESSA), _toConsumableArray(ordini.map(function (op) {
    return String(op.capo || '').trim();
  }).filter(function (v) {
    return v && v !== '—';
  })))));
  var carOptions = Array.from(new Set([].concat(_toConsumableArray(CFG_CAPI_REPARTO), _toConsumableArray(ordini.map(function (op) {
    return String(op.car || '').trim();
  }).filter(function (v) {
    return v && v !== '—';
  })))));
  var updateNewOp = function updateNewOp(field, value) {
    setNewOp(function (prev) {
      return _objectSpread(_objectSpread({}, prev), {}, _defineProperty({}, field, value));
    });
  };

  // Sblocco progressivo: P/N -> dati OP (anno/numero/fase) -> Capocommessa/CAR.
  var opUnlocked = !!newOp.pn.trim();
  var ccCarUnlocked = opUnlocked && !!newOp.anno.trim() && !!newOp.numero.trim();
  var newOpValid = ccCarUnlocked && !!newOp.capocommessa.trim() && !!newOp.car.trim();
  var validateNewOp = function validateNewOp() {
    if (!newOp.pn.trim()) return 'P/N obbligatorio.';
    if (!newOp.anno.trim()) return 'Anno obbligatorio.';
    if (!newOp.numero.trim()) return 'Numero obbligatorio.';
    if (!newOp.capocommessa.trim()) return 'Capocommessa obbligatorio.';
    if (!newOp.car.trim()) return 'CAR obbligatorio.';
    return '';
  };
  var handleCreateOp = /*#__PURE__*/function () {
    var _ref6 = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee4() {
      var vErr, csrf, r, j, _t3;
      return _regenerator().w(function (_context4) {
        while (1) switch (_context4.p = _context4.n) {
          case 0:
            vErr = validateNewOp();
            if (!vErr) {
              _context4.n = 1;
              break;
            }
            setCreateErr(vErr);
            return _context4.a(2);
          case 1:
            setCreateErr('');
            setCreating(true);
            _context4.p = 2;
            csrf = getCsrf(); // Solo verifica: l'OP si crea davvero al primo «Salva blocco» (Step 2).
            _context4.n = 3;
            return fetch(API.db_ordini_crea, {
              method: 'POST',
              headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrf
              },
              body: JSON.stringify(_objectSpread(_objectSpread({}, newOp), {}, {
                verifica: true
              })),
              credentials: 'same-origin'
            });
          case 3:
            r = _context4.v;
            _context4.n = 4;
            return parseJsonSafe(r, {});
          case 4:
            j = _context4.v;
            if (!(!r.ok || !j.success)) {
              _context4.n = 5;
              break;
            }
            throw new Error(j.error || 'Errore verifica OP (HTTP ' + r.status + ')');
          case 5:
            if (!(!j.op || !j.op.id)) {
              _context4.n = 6;
              break;
            }
            throw new Error('Risposta verifica OP non valida.');
          case 6:
            setShowCreate(false);
            setNewOp(newOpDaClona(clona));
            onSelect(_objectSpread(_objectSpread({}, j.op), {}, {
              item_id: null,
              daCreare: _objectSpread({}, newOp)
            }));
            _context4.n = 8;
            break;
          case 7:
            _context4.p = 7;
            _t3 = _context4.v;
            setCreateErr(_t3.message || 'Errore creazione OP');
          case 8:
            _context4.p = 8;
            setCreating(false);
            return _context4.f(8);
          case 9:
            return _context4.a(2);
        }
      }, _callee4, null, [[2, 7, 8, 9]]);
    }));
    return function handleCreateOp() {
      return _ref6.apply(this, arguments);
    };
  }();
  var handleCancelCreate = function handleCancelCreate() {
    if (creating) return;
    setShowCreate(false);
    setCreateErr('');
    setNewOp(newOpDaClona(clona));
  };
  return /*#__PURE__*/React.createElement("div", {
    className: "step-card"
  }, /*#__PURE__*/React.createElement("div", {
    className: "step-header"
  }, /*#__PURE__*/React.createElement("div", {
    className: "step-num"
  }, "1"), /*#__PURE__*/React.createElement("h2", null, "Seleziona Ordine di Produzione")), !window._AP_HAS_ORDINI && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '24px 28px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "error-msg"
  }, "Tabella ", /*#__PURE__*/React.createElement("code", null, "ordini_produzione"), " non disponibile nel database.")), clona && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '16px 28px 0'
    }
  }, /*#__PURE__*/React.createElement(ClonaBanner, {
    clona: clona
  }, "P/N, capocommessa e CAR sono gi\xE0 copiati: scrivi il ", /*#__PURE__*/React.createElement("strong", null, "numero"), " del nuovo OP e premi \xABContinua\xBB (l\u2019OP si crea solo quando salvi il primo blocco). Se il nuovo OP esiste gi\xE0, sceglilo dall\u2019elenco sotto. Le anomalie arriveranno gi\xE0 divise in blocchi, da controllare prima di salvarle.")), window._AP_HAS_ORDINI && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    className: "create-op-wrap"
  }, /*#__PURE__*/React.createElement("button", {
    className: "btn-primary create-op-btn",
    onClick: function onClick() {
      setShowCreate(function (v) {
        return !v;
      });
      setCreateErr('');
    },
    disabled: creating
  }, showCreate ? 'Chiudi inserimento nuovo OP' : '+ Nuovo OP'), /*#__PURE__*/React.createElement("div", {
    className: "create-op-hint"
  }, "Prima scelta: puoi inserire un nuovo OP e passare direttamente alla segnalazione; l\u2019OP si crea solo quando salvi il primo blocco di anomalie. Compila prima il ", /*#__PURE__*/React.createElement("strong", null, "P/N"), ", poi i dati dell'OP (anno e numero), infine Capocommessa e CAR: i campi si sbloccano in ordine."), showCreate && /*#__PURE__*/React.createElement("div", {
    className: "create-op-panel"
  }, /*#__PURE__*/React.createElement("div", {
    className: "create-grid"
  }, /*#__PURE__*/React.createElement("div", {
    className: "field-group"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "P/N ", /*#__PURE__*/React.createElement("span", {
    className: "req"
  }, "*")), /*#__PURE__*/React.createElement("input", {
    className: "text-input",
    type: "text",
    placeholder: "Part number",
    value: newOp.pn,
    onChange: function onChange(e) {
      return updateNewOp('pn', e.target.value);
    },
    autoFocus: !clona
  })), /*#__PURE__*/React.createElement("div", {
    className: "field-group"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "Causale doc."), /*#__PURE__*/React.createElement("input", {
    className: "text-input",
    type: "text",
    value: newOp.causale_doc,
    onChange: function onChange(e) {
      return updateNewOp('causale_doc', e.target.value);
    },
    list: "causale-doc-options",
    disabled: !opUnlocked
  }), /*#__PURE__*/React.createElement("datalist", {
    id: "causale-doc-options"
  }, CFG_CAUSALI_DOC.map(function (v) {
    return /*#__PURE__*/React.createElement("option", {
      key: v,
      value: v
    });
  }))), /*#__PURE__*/React.createElement("div", {
    className: "field-group"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "Anno ", /*#__PURE__*/React.createElement("span", {
    className: "req"
  }, "*")), /*#__PURE__*/React.createElement("input", {
    className: "text-input",
    type: "text",
    inputMode: "numeric",
    placeholder: "2026",
    value: newOp.anno,
    onChange: function onChange(e) {
      return updateNewOp('anno', e.target.value);
    },
    disabled: !opUnlocked
  })), /*#__PURE__*/React.createElement("div", {
    className: "field-group"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "Numero ", /*#__PURE__*/React.createElement("span", {
    className: "req"
  }, "*")), /*#__PURE__*/React.createElement("input", {
    className: "text-input",
    type: "text",
    placeholder: "123",
    value: newOp.numero,
    onChange: function onChange(e) {
      return updateNewOp('numero', e.target.value);
    },
    disabled: !opUnlocked
  })), /*#__PURE__*/React.createElement("div", {
    className: "field-group"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "Fase"), /*#__PURE__*/React.createElement("input", {
    className: "text-input",
    type: "text",
    placeholder: "Opzionale",
    value: newOp.fase,
    onChange: function onChange(e) {
      return updateNewOp('fase', e.target.value);
    },
    disabled: !opUnlocked
  })), /*#__PURE__*/React.createElement("div", {
    className: "field-group"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "Capocommessa ", /*#__PURE__*/React.createElement("span", {
    className: "req"
  }, "*")), /*#__PURE__*/React.createElement("input", {
    className: "text-input",
    type: "text",
    value: newOp.capocommessa,
    onChange: function onChange(e) {
      return updateNewOp('capocommessa', e.target.value);
    },
    list: "capocommessa-options",
    disabled: !ccCarUnlocked
  }), /*#__PURE__*/React.createElement("datalist", {
    id: "capocommessa-options"
  }, capocommessaOptions.map(function (v) {
    return /*#__PURE__*/React.createElement("option", {
      key: v,
      value: v
    });
  }))), /*#__PURE__*/React.createElement("div", {
    className: "field-group"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "CAR ", /*#__PURE__*/React.createElement("span", {
    className: "req"
  }, "*")), /*#__PURE__*/React.createElement("input", {
    className: "text-input",
    type: "text",
    value: newOp.car,
    onChange: function onChange(e) {
      return updateNewOp('car', e.target.value);
    },
    list: "car-options",
    disabled: !ccCarUnlocked
  }), /*#__PURE__*/React.createElement("datalist", {
    id: "car-options"
  }, carOptions.map(function (v) {
    return /*#__PURE__*/React.createElement("option", {
      key: v,
      value: v
    });
  }))), /*#__PURE__*/React.createElement("div", {
    className: "field-group full"
  }, /*#__PURE__*/React.createElement("label", {
    className: "create-op-checkbox"
  }, /*#__PURE__*/React.createElement("input", {
    type: "checkbox",
    checked: newOp.collaudo_benestare,
    onChange: function onChange(e) {
      return updateNewOp('collaudo_benestare', e.target.checked);
    },
    disabled: !ccCarUnlocked
  }), /*#__PURE__*/React.createElement("span", null, "Collaudo di benestare"))), /*#__PURE__*/React.createElement("div", {
    className: "field-group full"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "Note"), /*#__PURE__*/React.createElement("textarea", {
    className: "textarea-input",
    rows: 2,
    placeholder: "Note opzionali OP",
    value: newOp.note,
    onChange: function onChange(e) {
      return updateNewOp('note', e.target.value);
    },
    disabled: !ccCarUnlocked
  }))), createErr && /*#__PURE__*/React.createElement("div", {
    className: "error-msg"
  }, createErr), /*#__PURE__*/React.createElement("div", {
    className: "create-actions"
  }, /*#__PURE__*/React.createElement("button", {
    className: "btn-secondary",
    onClick: handleCancelCreate,
    disabled: creating
  }, "Annulla"), /*#__PURE__*/React.createElement("button", {
    className: "btn-primary",
    onClick: handleCreateOp,
    disabled: creating || !newOpValid
  }, creating ? 'Verifica OP...' : 'Continua')))), /*#__PURE__*/React.createElement("div", {
    className: "search-wrap"
  }, /*#__PURE__*/React.createElement("input", {
    className: "search-input",
    type: "text",
    placeholder: "Cerca per titolo OP, P/N, capocommessa, CAR...",
    value: search,
    onChange: function onChange(e) {
      return setSearch(e.target.value);
    },
    autoFocus: true
  })), loading && /*#__PURE__*/React.createElement("div", {
    className: "loading-msg"
  }, "Caricamento ordini in corso..."), err && /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '12px 28px'
    }
  }, /*#__PURE__*/React.createElement("div", {
    className: "error-msg"
  }, err)), !loading && !err && filtered.length === 0 && /*#__PURE__*/React.createElement("div", {
    className: "empty-msg"
  }, "Nessun ordine trovato."), !loading && !err && filtered.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "op-list"
  }, filtered.map(function (op, idx) {
    var _op$item_id;
    return /*#__PURE__*/React.createElement("div", {
      key: (_op$item_id = op.item_id) !== null && _op$item_id !== void 0 ? _op$item_id : idx,
      className: "op-row",
      onClick: function onClick() {
        return onSelect(op);
      }
    }, /*#__PURE__*/React.createElement("div", {
      className: "op-row-title"
    }, op.id || '—'), /*#__PURE__*/React.createElement("div", {
      className: "op-row-meta"
    }, op.pn && /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("span", {
      className: "meta-label"
    }, "P/N"), op.pn), op.capo && /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("span", {
      className: "meta-label"
    }, "Capo"), op.capo), op.car && /*#__PURE__*/React.createElement("span", null, /*#__PURE__*/React.createElement("span", {
      className: "meta-label"
    }, "CAR"), op.car), op.anomalie_count > 0 && /*#__PURE__*/React.createElement("span", {
      className: "badge"
    }, op.anomalie_count, " anomali", op.anomalie_count === 1 ? 'a' : 'e')));
  }))));
};

/* ── Step 2: controllo dell'OP a blocchi di seriali ──
   Un blocco = un gruppo di seriali (singoli, liste, range) con una o più anomalie.
   Ogni anomalia diventa una riga a sé: il capocommessa decide su ciascuna. */
var STATI_SUPERFICIE = CFG_STATI_SUPERFICIE;
var MSG_SUP = 'Indica lo stato superficie del blocco.';
var MSG_SN_ANOM = 'Scegli su quali seriali è presente l’anomalia';
var SN_PATTERN = /^[A-Za-z]{3}\d{5}$/;
var MAX_RANGE = 1000;
// La mail al capocommessa parte solo con «Termina controllo»; dopo 15 minuti dall'ultimo
// salvataggio senza invio arriva un promemoria al controllore, dopo 4 ore parte da sola.
// I due tempi si impostano in Configurazione → Notifiche.
var TEMPI = window._AP_TEMPI || {
  promemoria: 15,
  invio_auto: 60
};
var durata = function durata(min) {
  var h = Math.floor(min / 60),
    m = min % 60;
  var parti = [];
  if (h) parti.push("".concat(h, " or").concat(h === 1 ? 'a' : 'e'));
  if (m || !h) parti.push("".concat(m, " minut").concat(m === 1 ? 'o' : 'i'));
  return parti.join(' e ');
};
var MAIL_FINE_HINT = "La mail parte quando premi \xABTermina controllo\xBB. Se ".concat(durata(TEMPI.promemoria), " dopo l\u2019ultimo salvataggio non \xE8 ancora partita ricevi un promemoria per inviarla; dopo ").concat(durata(TEMPI.invio_auto), " parte da sola.");
var urlFor = function urlFor(tpl, id) {
  return String(tpl).replace('/controlli/0', "/controlli/".concat(id));
};
var postJson = /*#__PURE__*/function () {
  var _ref7 = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee5(url, body, context) {
    var r, j, err;
    return _regenerator().w(function (_context5) {
      while (1) switch (_context5.n) {
        case 0:
          _context5.n = 1;
          return fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': getCsrf()
            },
            body: JSON.stringify(body || {})
          });
        case 1:
          r = _context5.v;
          _context5.n = 2;
          return parseJsonStrict(r, context);
        case 2:
          j = _context5.v;
          if (!(!r.ok && r.status !== 207)) {
            _context5.n = 3;
            break;
          }
          err = new Error(j.error || "".concat(context, ": HTTP ").concat(r.status));
          err.data = j;
          throw err;
        case 3:
          return _context5.a(2, j);
      }
    }, _callee5);
  }));
  return function postJson(_x5, _x6, _x7) {
    return _ref7.apply(this, arguments);
  };
}();
var getJson = /*#__PURE__*/function () {
  var _ref8 = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee6(url, context) {
    var r, j;
    return _regenerator().w(function (_context6) {
      while (1) switch (_context6.n) {
        case 0:
          _context6.n = 1;
          return fetch(url, {
            credentials: 'same-origin'
          });
        case 1:
          r = _context6.v;
          _context6.n = 2;
          return parseJsonStrict(r, context);
        case 2:
          j = _context6.v;
          if (r.ok) {
            _context6.n = 3;
            break;
          }
          throw new Error(j.error || "".concat(context, ": HTTP ").concat(r.status));
        case 3:
          return _context6.a(2, j);
      }
    }, _callee6);
  }));
  return function getJson(_x8, _x9) {
    return _ref8.apply(this, arguments);
  };
}();

/* Seriali: stessa logica di anomalie/seriali.py */
var parseVoce = function parseVoce(raw) {
  var voce = String(raw || '').trim().replace(/\s*-\s*/g, '-');
  if (!voce) return null;
  var m = voce.match(/^(.*?)(\d+)-(.*?)(\d+)$/);
  if (m && (!m[3] || m[3].toLowerCase() === m[1].toLowerCase())) {
    var a = parseInt(m[2], 10),
      b = parseInt(m[4], 10);
    if (a <= b && b - a <= MAX_RANGE) {
      var tokens = [];
      for (var i = a; i <= b; i += 1) tokens.push("".concat(m[1]).concat(String(i).padStart(m[2].length, '0')));
      return {
        voce: voce,
        range: true,
        da: tokens[0],
        a: tokens[tokens.length - 1],
        tokens: tokens
      };
    }
  }
  return {
    voce: voce,
    range: false,
    tokens: [voce]
  };
};
var splitSerialText = function splitSerialText(text) {
  return String(text || '').replace(/\s*-\s*/g, '-').split(/[\s,;]+/).map(function (v) {
    return v.trim();
  }).filter(Boolean);
};
var tokensOf = function tokensOf(voci) {
  var seen = new Set();
  var out = [];
  (voci || []).forEach(function (v) {
    var p = parseVoce(v);
    (p ? p.tokens : []).forEach(function (t) {
      var k = t.toLowerCase();
      if (!seen.has(k)) {
        seen.add(k);
        out.push(t);
      }
    });
  });
  return out;
};
var labelVoci = function labelVoci(voci) {
  var n = tokensOf(voci).length;
  var txt = (voci || []).join(', ');
  return n > 1 ? "".concat(txt, " (").concat(n, " pezzi)") : txt;
};
var fileExt = function fileExt(name) {
  var dot = String(name || '').lastIndexOf('.');
  return dot >= 0 ? String(name).slice(dot).toLowerCase() : '';
};
var isImageFile = function isImageFile(f) {
  return /^image\//.test(String(f.type || '')) || ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'].includes(fileExt(f.name));
};
var stamp = function stamp() {
  var d = new Date();
  var p = function p(n) {
    return String(n).padStart(2, '0');
  };
  return "".concat(d.getFullYear()).concat(p(d.getMonth() + 1)).concat(p(d.getDate()), "-").concat(p(d.getHours())).concat(p(d.getMinutes())).concat(p(d.getSeconds()));
};
/* Le immagini incollate dagli appunti arrivano come "image.png": nome leggibile e univoco. */
var nameClipboardFiles = function nameClipboardFiles(files) {
  return files.map(function (f, i) {
    var ext = fileExt(f.name) || (String(f.type || '').split('/')[1] ? ".".concat(String(f.type).split('/')[1]) : '.png');
    if (f.name && !/^image\.\w+$/i.test(f.name)) return f;
    try {
      return new File([f], "appunti-".concat(stamp(), "-").concat(i + 1).concat(ext === '.jpeg' ? '.jpg' : ext), {
        type: f.type || 'image/png'
      });
    } catch (_) {
      return f;
    }
  });
};
var validateFiles = function validateFiles(files) {
  var ok = [];
  var errors = [];
  files.forEach(function (f) {
    if (!ALLEGATI_ALLOWED_EXT.has(fileExt(f.name))) errors.push("".concat(f.name || 'file', ": formato non supportato"));else if (Number(f.size || 0) <= 0) errors.push("".concat(f.name || 'file', ": file vuoto"));else if (Number(f.size || 0) > ALLEGATI_MAX_SIZE) errors.push("".concat(f.name || 'file', ": supera ").concat(ALLEGATI_MAX_MB, " MB"));else ok.push(f);
  });
  return {
    ok: ok,
    errors: errors
  };
};
var _uid = 0;
var uid = function uid() {
  return "n".concat(Date.now(), "_").concat(_uid += 1);
};

/* Dati strutturati facoltativi dell'anomalia: stessa logica di anomalie/dettaglio_controllo.py. */
var DETT = window._AP_DETTAGLIO || {};
var CARATT = DETT.caratteristiche || [];
var CARATT_BY = Object.fromEntries(CARATT.map(function (c) {
  return [c.codice, c];
}));
var GENERI = DETT.generi || [];
var GENERI_BY = Object.fromEntries(GENERI.map(function (g) {
  return [g.codice, g];
}));
var DOC_LIST = DETT.documenti || [];
var TIPI_DIFETTO = DETT.tipi_difetto || [];
// Parti accese da Configurazione → «Campi del blocco del controllore» (di serie tutte).
// Regole «Visibile se» (Configurazione → «Campi del blocco del controllore»): persone e ruoli
// li valuta il server; fase del controllo e tipo di difetto dell'anomalia si valutano qui.
var CAMPI = window._AP_CAMPI || {};
var campoVisibile = function campoVisibile(chiave) {
  var ctx = arguments.length > 1 && arguments[1] !== undefined ? arguments[1] : {};
  var r = CAMPI[chiave];
  if (!r) return true;
  if (!r.visibile) return false;
  var fase = String(ctx.fase || '').toLowerCase();
  if ((r.fasi || []).length && !r.fasi.some(function (f) {
    return fase.includes(String(f).toLowerCase());
  })) return false;
  if ((r.tipi || []).length && !r.tipi.includes(ctx.tipo || '')) return false;
  return true;
};
var TUTTI_I_CASI = [['misura', 'Misura fuori tolleranza'], ['difetto', 'Difetto sul pezzo'], ['documenti', 'Marcatura / documenti']];
var casiVisibili = function casiVisibili(ctx) {
  return campoVisibile('caso', ctx) ? TUTTI_I_CASI.filter(function (_ref9) {
    var _ref0 = _slicedToArray(_ref9, 1),
      k = _ref0[0];
    return campoVisibile("caso_".concat(k), ctx);
  }) : [];
};
// Tipo di difetto dell'anomalia per le regole: quello scelto, altrimenti quello proposto.
var codiceTipoAnomalia = function codiceTipoAnomalia(d, testo) {
  var scelto = d && d.tipoDifettoId ? TIPI_DIFETTO.find(function (t) {
    return t.id === d.tipoDifettoId;
  }) : null;
  return scelto ? scelto.codice : codiceSuggerito(d, testo);
};
var SIMBOLI = ['Ø', '±', '°', '⊥', '∥', '◎', '⌖', '⌯', '⏥', '○', '⌒', '↗', '≤', '≥', 'µm', 'Ra'];
var emptyMisura = function emptyMisura() {
  return {
    key: uid(),
    car: 'diametro',
    nome: '',
    modo: 'minmax',
    nom: '',
    a: '',
    b: '',
    ril: '',
    dove: ''
  };
};
var emptyDett = function emptyDett() {
  return {
    tipo: '',
    misure: [],
    difetto: {},
    documenti: {
      docs: []
    },
    rif: {},
    rifAperto: false,
    tipoDifettoId: null
  };
};
var dettDaServer = function dettDaServer(d, tipoDifettoId) {
  var x = d && _typeof(d) === 'object' ? d : {};
  var rif = x.rif || {};
  return {
    tipo: x.tipo || '',
    misure: (x.misure || []).map(function (m) {
      return _objectSpread(_objectSpread(_objectSpread({}, emptyMisura()), m), {}, {
        key: uid()
      });
    }),
    difetto: x.difetto || {},
    documenti: _objectSpread({
      docs: []
    }, x.documenti || {}),
    rif: rif,
    rifAperto: !!(rif.disegno || rif.sezione || rif.fase),
    tipoDifettoId: tipoDifettoId || null
  };
};
var dettPayload = function dettPayload(d) {
  if (!d) return {};
  var out = {};
  if (d.tipo) out.tipo = d.tipo;
  if (d.tipo === 'misura') out.misure = (d.misure || []).map(function (_ref1) {
    var key = _ref1.key,
      m = _objectWithoutProperties(_ref1, _excluded);
    return m;
  });
  if (d.tipo === 'difetto') out.difetto = d.difetto || {};
  if (d.tipo === 'documenti') out.documenti = d.documenti || {};
  if (d.rif && (d.rif.disegno || d.rif.sezione || d.rif.fase)) out.rif = d.rif;
  return out;
};
var numero = function numero(v) {
  var t = String(v == null ? '' : v).trim().replace(',', '.').replace('−', '-').replace('±', '');
  if (!t) return null;
  var n = Number(t);
  return Number.isFinite(n) ? n : null;
};
var fmtNum = function fmtNum(v) {
  var t = (Math.round(v * 10000) / 10000).toString();
  return t === '-0' ? '0' : t;
};
var esitoMisura = function esitoMisura(m) {
  var ril = numero(m.ril),
    nom = numero(m.nom),
    a = numero(m.a),
    b = numero(m.b);
  var lo = null,
    hi = null;
  if (m.modo === 'minmax') {
    lo = a;
    hi = b;
    if (lo != null && hi != null && lo > hi) {
      var _ref10 = [hi, lo];
      lo = _ref10[0];
      hi = _ref10[1];
    }
  } else if (m.modo === 'pm' && nom != null && a != null) {
    lo = nom - Math.abs(a);
    hi = nom + Math.abs(b != null ? b : a);
  } else if (m.modo === 'max') {
    hi = a;
  }
  if (ril == null || lo == null && hi == null) return {
    fuori: null,
    scarto: null
  };
  if (hi != null && ril > hi) return {
    fuori: true,
    scarto: Math.round((ril - hi) * 10000) / 10000
  };
  if (lo != null && ril < lo) return {
    fuori: true,
    scarto: Math.round((ril - lo) * 10000) / 10000
  };
  return {
    fuori: false,
    scarto: 0
  };
};
var fraseMisura = function fraseMisura(m) {
  var c = CARATT_BY[m.car] || {
    simbolo: '',
    nome: 'Misura'
  };
  var nome = m.nome || c.nome;
  var testa = (c.simbolo === 'Ø' || c.simbolo === 'R') && !m.nome ? c.simbolo : "".concat(c.simbolo || '', " ").concat(nome).trim();
  var tol;
  if (m.modo === 'minmax') tol = "".concat(m.a || '?', "/").concat(m.b || '?');else if (m.modo === 'pm') tol = !m.b || m.b === m.a ? "".concat(m.nom || '?', " \xB1").concat(m.a || '?') : "".concat(m.nom || '?', " \u2212").concat(m.a, "/+").concat(m.b);else tol = "max ".concat(m.a || '?');
  var parti = ["".concat(testa, " ").concat(tol).trim()];
  if (m.ril) parti.push("rilevato ".concat(m.ril));
  var e = esitoMisura(m);
  if (e.fuori) parti.push("(".concat(e.scarto > 0 ? '+' : '−').concat(fmtNum(Math.abs(e.scarto)), ")"));
  return parti.join(' ') + (m.dove ? " \xB7 ".concat(m.dove) : '');
};
var misuraUtile = function misuraUtile(m) {
  return !!(m.nom || m.a || m.b || m.ril || m.dove || m.nome);
};
var frasiDett = function frasiDett(d) {
  if (!d) return [];
  var out = [];
  if (d.tipo === 'misura') (d.misure || []).filter(misuraUtile).forEach(function (m) {
    return out.push(fraseMisura(m));
  });else if (d.tipo === 'difetto') {
    var x = d.difetto || {};
    if (x.genere || x.dove || x.lung || x.larg || x.prof || x.est) {
      var dim = [['lung', 'lunghezza'], ['larg', 'larghezza/altezza'], ['prof', 'profondità'], ['est', 'estensione']].filter(function (_ref11) {
        var _ref12 = _slicedToArray(_ref11, 1),
          k = _ref12[0];
        return x[k];
      }).map(function (_ref13) {
        var _ref14 = _slicedToArray(_ref13, 2),
          k = _ref14[0],
          l = _ref14[1];
        return "".concat(l, " ").concat(x[k]);
      });
      out.push(((GENERI_BY[x.genere] || {}).nome || 'Difetto') + (x.dove ? " \xB7 ".concat(x.dove) : '') + (dim.length ? " \xB7 ".concat(dim.join(', ')) : ''));
    }
  } else if (d.tipo === 'documenti') {
    var _x0 = d.documenti || {};
    var parti = [];
    if (_x0.trovato) parti.push("sul pezzo ".concat(_x0.trovato));
    if (_x0.atteso) parti.push("atteso ".concat(_x0.atteso));
    if ((_x0.docs || []).length) parti.push("documenti: ".concat(_x0.docs.join(', ')));
    if (parti.length) out.push('Marcatura/documenti non coincidenti · ' + parti.join(' · '));
  }
  var r = d.rif || {};
  var pezzi = [r.disegno, r.sezione ? "sez. ".concat(r.sezione) : '', r.fase].filter(Boolean);
  if (pezzi.length) out.push('Rif.: ' + pezzi.join(' · '));
  return out;
};
var PAROLE = [[/\bbav[ae]\b|spigol/i, 'bave-spigoli'], [/marcat|ddt|cartellino/i, 'marcatura-documenti'], [/concentricit|simmetri|posizione|planarit|perpendicolar|parallelis|circolarit|oscillazion/i, 'geometria'], [/filett/i, 'filettatura'], [/rugosit|\bRa\b/i, 'rugosita'], [/testimone|porosit|fusione|graff|ammacc|impront/i, 'difetto-superficiale'], [/Ø|diametr|quota|lunghezz|smusso|\bOT\b|fuori toll|rilevat|risulta/i, 'fuori-tolleranza']];
var codiceSuggerito = function codiceSuggerito(d, testo) {
  if (d && d.tipo === 'misura') {
    var m = (d.misure || [])[0];
    return m ? (CARATT_BY[m.car] || {}).famiglia || 'fuori-tolleranza' : 'fuori-tolleranza';
  }
  if (d && d.tipo === 'difetto') return (GENERI_BY[(d.difetto || {}).genere] || {}).famiglia || 'difetto-superficiale';
  if (d && d.tipo === 'documenti') return 'marcatura-documenti';
  var hit = PAROLE.find(function (_ref15) {
    var _ref16 = _slicedToArray(_ref15, 1),
      re = _ref16[0];
    return re.test(testo || '');
  });
  return hit ? hit[1] : '';
};
/* Testo effettivo dell'anomalia: la descrizione o, se vuota, le frasi dei dati strutturati. */
var testoAnomalia = function testoAnomalia(a) {
  return (a.testo || '').trim() || frasiDett(a.dett).join('\n');
};
/* Inserisce un simbolo nel campo di testo attivo (React: setter nativo + evento input). */
var inserisciNelCampo = function inserisciNelCampo(el, testo) {
  if (!el || !('value' in el) || el.disabled || el.readOnly) return false;
  var start = el.selectionStart != null ? el.selectionStart : el.value.length;
  var end = el.selectionEnd != null ? el.selectionEnd : el.value.length;
  var nuovo = el.value.slice(0, start) + testo + el.value.slice(end);
  var proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, nuovo);
  el.dispatchEvent(new Event('input', {
    bubbles: true
  }));
  var pos = start + testo.length;
  try {
    el.setSelectionRange(pos, pos);
  } catch (e) {/* input number */}
  return true;
};

/* Pulsanti dei simboli: scrivono nel campo dove si trova il cursore (di serie la descrizione). */
var BarraSimboli = function BarraSimboli(_ref17) {
  var disabled = _ref17.disabled,
    fallbackRef = _ref17.fallbackRef;
  return /*#__PURE__*/React.createElement("div", {
    className: "sym-bar",
    role: "group",
    "aria-label": "Simboli"
  }, /*#__PURE__*/React.createElement("span", {
    className: "sym-bar__lbl"
  }, "Simboli:"), SIMBOLI.map(function (sym) {
    return /*#__PURE__*/React.createElement("button", {
      key: sym,
      type: "button",
      className: "sym-btn",
      disabled: disabled,
      title: "Inserisci ".concat(sym),
      onMouseDown: function onMouseDown(e) {
        return e.preventDefault();
      },
      onClick: function onClick() {
        var el = document.activeElement;
        var card = fallbackRef.current && fallbackRef.current.closest('.anom-card');
        var target = el && card && card.contains(el) && ['TEXTAREA', 'INPUT'].includes(el.tagName) && el.type !== 'checkbox' ? el : fallbackRef.current;
        if (target) {
          target.focus();
          inserisciNelCampo(target, sym);
        }
      }
    }, sym);
  }));
};

/* «Incolla dal report ZEISS»: screenshot di righe del protocollo -> misure proposte da confermare.
   L'immagine va solo alla lettura (OCR sul server) e non diventa un allegato. */
var LetturaReport = function LetturaReport(_ref18) {
  var opId = _ref18.opId,
    disabled = _ref18.disabled,
    onAggiungi = _ref18.onAggiungi;
  var _useState15 = useState(''),
    _useState16 = _slicedToArray(_useState15, 2),
    stato = _useState16[0],
    setStato = _useState16[1]; // '' | 'lettura' | errore
  var _useState17 = useState(null),
    _useState18 = _slicedToArray(_useState17, 2),
    proposte = _useState18[0],
    setProposte = _useState18[1];
  var _useState19 = useState([]),
    _useState20 = _slicedToArray(_useState19, 2),
    testoLetto = _useState20[0],
    setTestoLetto = _useState20[1];
  var _useState21 = useState({}),
    _useState22 = _slicedToArray(_useState21, 2),
    scelte = _useState22[0],
    setScelte = _useState22[1];
  var _useState23 = useState(false),
    _useState24 = _slicedToArray(_useState23, 2),
    over = _useState24[0],
    setOver = _useState24[1];
  var fileRef = useRef(null);
  var leggi = /*#__PURE__*/function () {
    var _ref19 = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee7(file) {
      var form, r, j, righe, _t4;
      return _regenerator().w(function (_context7) {
        while (1) switch (_context7.p = _context7.n) {
          case 0:
            if (!(!file || disabled)) {
              _context7.n = 1;
              break;
            }
            return _context7.a(2);
          case 1:
            if (/^image\//.test(file.type || '')) {
              _context7.n = 2;
              break;
            }
            setStato('Serve un\'immagine: cattura le righe del report e incollale qui.');
            return _context7.a(2);
          case 2:
            setStato('lettura');
            setProposte(null);
            _context7.p = 3;
            form = new FormData();
            form.append('op_id', opId || '');
            form.append('immagine', file, file.name || 'report.png');
            _context7.n = 4;
            return fetch(API.report_cmm, {
              method: 'POST',
              headers: {
                'X-CSRFToken': getCsrf()
              },
              body: form,
              credentials: 'same-origin'
            });
          case 4:
            r = _context7.v;
            _context7.n = 5;
            return parseJsonStrict(r, 'Lettura del report');
          case 5:
            j = _context7.v;
            if (!(!r.ok || !j.success)) {
              _context7.n = 6;
              break;
            }
            throw new Error(j.error || "HTTP ".concat(r.status));
          case 6:
            righe = j.righe || [];
            setTestoLetto(j.testo || []);
            if (righe.length) {
              _context7.n = 7;
              break;
            }
            setStato('Nessuna riga di misura riconosciuta: cattura le righe con valori (Actual, Nominal, tolleranze) e riprova, magari ingrandendo il PDF.');
            return _context7.a(2);
          case 7:
            setProposte(righe);
            setScelte(Object.fromEntries(righe.map(function (x, i) {
              return [i, !!x.fuori];
            })));
            setStato('');
            _context7.n = 9;
            break;
          case 8:
            _context7.p = 8;
            _t4 = _context7.v;
            setStato(_t4.message);
          case 9:
            return _context7.a(2);
        }
      }, _callee7, null, [[3, 8]]);
    }));
    return function leggi(_x1) {
      return _ref19.apply(this, arguments);
    };
  }();
  var onPaste = function onPaste(e) {
    var items = Array.from(e.clipboardData && e.clipboardData.items || []);
    var file = items.filter(function (it) {
      return it.kind === 'file';
    }).map(function (it) {
      return it.getAsFile();
    }).find(Boolean);
    if (!file) return;
    e.preventDefault();
    e.stopPropagation();
    leggi(file);
  };
  var nScelte = proposte ? proposte.filter(function (_, i) {
    return scelte[i];
  }).length : 0;
  return /*#__PURE__*/React.createElement("div", {
    className: "dett"
  }, /*#__PURE__*/React.createElement("div", {
    className: "cmm-box".concat(over ? ' is-over' : ''),
    tabIndex: disabled ? -1 : 0,
    onPaste: onPaste,
    onDragOver: function onDragOver(e) {
      e.preventDefault();
      setOver(true);
    },
    onDragLeave: function onDragLeave() {
      return setOver(false);
    },
    onDrop: function onDrop(e) {
      e.preventDefault();
      e.stopPropagation();
      setOver(false);
      leggi((e.dataTransfer.files || [])[0]);
    },
    onClick: function onClick(e) {
      return e.currentTarget.focus();
    },
    "aria-label": "Incolla qui lo screenshot del report ZEISS"
  }, /*#__PURE__*/React.createElement("input", {
    ref: fileRef,
    type: "file",
    accept: "image/*",
    hidden: true,
    onChange: function onChange(e) {
      var f = (e.target.files || [])[0];
      e.target.value = '';
      leggi(f);
    }
  }), /*#__PURE__*/React.createElement("div", {
    className: "cmm-box__hint"
  }, "\uD83D\uDCCB ", /*#__PURE__*/React.createElement("strong", null, "Dal report ZEISS:"), " cattura le righe del protocollo (Win+Maiusc+S), clicca qui e premi ", /*#__PURE__*/React.createElement("kbd", null, "Ctrl"), "+", /*#__PURE__*/React.createElement("kbd", null, "V"), ' ', "oppure ", /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "link-btn",
    disabled: disabled,
    onClick: function onClick(e) {
      e.stopPropagation();
      fileRef.current && fileRef.current.click();
    }
  }, "scegli l\u2019immagine"), ".", /*#__PURE__*/React.createElement("span", null, "L\u2019immagine non viene allegata: serve solo a proporre le misure.")), stato === 'lettura' && /*#__PURE__*/React.createElement("div", {
    className: "field-hint"
  }, "Lettura del report in corso\u2026"), stato && stato !== 'lettura' && /*#__PURE__*/React.createElement("div", {
    className: "error-msg"
  }, stato)), proposte && /*#__PURE__*/React.createElement("div", {
    className: "dett-panel"
  }, /*#__PURE__*/React.createElement("div", {
    className: "dett-panel__head"
  }, "Righe lette dal report ", /*#__PURE__*/React.createElement("small", null, "\u2014 spunta quelle da aggiungere (gi\xE0 spuntate le fuori tolleranza)")), /*#__PURE__*/React.createElement("div", {
    className: "cmm-prop"
  }, proposte.map(function (p, i) {
    var e = esitoMisura(p);
    return /*#__PURE__*/React.createElement("label", {
      key: i
    }, /*#__PURE__*/React.createElement("input", {
      type: "checkbox",
      checked: !!scelte[i],
      onChange: function onChange(ev) {
        return setScelte(function (prev) {
          return _objectSpread(_objectSpread({}, prev), {}, _defineProperty({}, i, ev.target.checked));
        });
      }
    }), e.fuori === true ? /*#__PURE__*/React.createElement("span", {
      className: "mis-esito is-ko"
    }, "Fuori ", e.scarto > 0 ? '+' : '−', fmtNum(Math.abs(e.scarto))) : e.fuori === false ? /*#__PURE__*/React.createElement("span", {
      className: "mis-esito is-ok"
    }, "Dentro") : null, /*#__PURE__*/React.createElement("span", {
      className: "mis-frase"
    }, fraseMisura(p)), p.da_verificare && /*#__PURE__*/React.createElement("span", {
      className: "pill-verifica",
      title: "Lo scostamento letto non tornava con misurato \u2212 nominale: controlla i valori"
    }, "da verificare"));
  })), /*#__PURE__*/React.createElement("details", {
    className: "field-hint"
  }, /*#__PURE__*/React.createElement("summary", null, "Lette ", proposte.length, " righe. Ne manca qualcuna? Testo letto dall\u2019immagine"), /*#__PURE__*/React.createElement("pre", {
    style: {
      whiteSpace: 'pre-wrap',
      margin: '6px 0 0',
      fontSize: 11
    }
  }, testoLetto.join('\n')), /*#__PURE__*/React.createElement("div", null, "Se mancano righe o i valori sono sbagliati: ingrandisci il PDF (almeno 125%) e cattura di nuovo, anche a pezzi.")), /*#__PURE__*/React.createElement("div", {
    className: "dett-actions"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn-outline",
    disabled: !nScelte,
    onClick: function onClick() {
      onAggiungi(proposte.filter(function (_, i) {
        return scelte[i];
      }));
      setProposte(null);
    }
  }, "Aggiungi ", nScelte, " misur", nScelte === 1 ? 'a' : 'e'), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "link-btn",
    onClick: function onClick() {
      return setProposte(null);
    }
  }, "Annulla"), /*#__PURE__*/React.createElement("span", {
    className: "field-hint"
  }, "I valori restano modificabili nelle righe qui sopra: controllali sul report."))));
};

/* «Che cosa hai trovato?»: una scelta facoltativa apre solo i campi di quel caso. */
var DettaglioAnomalia = function DettaglioAnomalia(_ref20) {
  var dett = _ref20.dett,
    testo = _ref20.testo,
    disabled = _ref20.disabled,
    onChange = _ref20.onChange,
    onCopiaNelTesto = _ref20.onCopiaNelTesto,
    opId = _ref20.opId,
    fase = _ref20.fase;
  var d = dett || emptyDett();
  var upd = function upd(patch) {
    return onChange(_objectSpread(_objectSpread({}, d), patch));
  };
  var scegli = function scegli(tipo) {
    if (d.tipo === tipo) {
      upd({
        tipo: ''
      });
      return;
    }
    var patch = {
      tipo: tipo
    };
    if (tipo === 'misura' && !(d.misure || []).length) patch.misure = [emptyMisura()];
    upd(patch);
  };
  var updMisura = function updMisura(k, patch) {
    return upd({
      misure: d.misure.map(function (m) {
        return m.key === k ? _objectSpread(_objectSpread({}, m), patch) : m;
      })
    });
  };
  var dif = d.difetto || {};
  var doc = d.documenti || {
    docs: []
  };
  var rif = d.rif || {};
  var frasi = frasiDett(d);
  var ctx = {
    fase: fase,
    tipo: codiceTipoAnomalia(d, testo)
  };
  var DETT_TIPI = casiVisibili(ctx);
  var casoAcceso = function casoAcceso(tipo) {
    return DETT_TIPI.some(function (_ref21) {
      var _ref22 = _slicedToArray(_ref21, 1),
        k = _ref22[0];
      return k === tipo;
    });
  };
  var vede = function vede(chiave) {
    return campoVisibile(chiave, ctx);
  };
  var suggerito = codiceSuggerito(d, testo);
  var tipoSugg = TIPI_DIFETTO.find(function (t) {
    return t.codice === suggerito;
  });
  var tipoSel = d.tipoDifettoId ? TIPI_DIFETTO.find(function (t) {
    return t.id === d.tipoDifettoId;
  }) : null;
  var f = function f(label, value, onCh) {
    var extra = arguments.length > 3 && arguments[3] !== undefined ? arguments[3] : {};
    return /*#__PURE__*/React.createElement("label", {
      className: "dett-f"
    }, /*#__PURE__*/React.createElement("span", null, label), /*#__PURE__*/React.createElement("input", _extends({
      className: "text-input",
      value: value || '',
      disabled: disabled,
      spellCheck: true,
      lang: "it",
      onChange: function onChange(e) {
        return onCh(e.target.value);
      }
    }, extra)));
  };
  return /*#__PURE__*/React.createElement("div", {
    className: "dett"
  }, DETT_TIPI.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "dett-ask"
  }, /*#__PURE__*/React.createElement("strong", null, "Che cosa hai trovato?"), /*#__PURE__*/React.createElement("span", null, "(facoltativo: apre i campi giusti)"), /*#__PURE__*/React.createElement("div", {
    className: "sup-chips"
  }, DETT_TIPI.map(function (_ref23) {
    var _ref24 = _slicedToArray(_ref23, 2),
      k = _ref24[0],
      l = _ref24[1];
    return /*#__PURE__*/React.createElement("button", {
      key: k,
      type: "button",
      className: "sup-chip".concat(d.tipo === k ? ' is-on' : ''),
      "aria-pressed": d.tipo === k,
      disabled: disabled,
      onClick: function onClick() {
        return scegli(k);
      }
    }, d.tipo === k ? '✓ ' : '', l);
  }))), d.tipo === 'misura' && casoAcceso('misura') && /*#__PURE__*/React.createElement("div", {
    className: "dett-panel"
  }, /*#__PURE__*/React.createElement("div", {
    className: "dett-panel__head"
  }, "\uD83D\uDCCF Misure fuori tolleranza ", /*#__PURE__*/React.createElement("small", null, "\u2014 una riga per misura")), (d.misure || []).map(function (m, mi) {
    var e = esitoMisura(m);
    return /*#__PURE__*/React.createElement(React.Fragment, {
      key: m.key
    }, mi > 0 && /*#__PURE__*/React.createElement("hr", {
      className: "mis-sep"
    }), /*#__PURE__*/React.createElement("div", {
      className: "dett-grid dett-grid--mis"
    }, /*#__PURE__*/React.createElement("label", {
      className: "dett-f"
    }, /*#__PURE__*/React.createElement("span", null, "Caratteristica"), /*#__PURE__*/React.createElement("select", {
      className: "text-input",
      value: m.car,
      disabled: disabled,
      onChange: function onChange(ev) {
        return updMisura(m.key, {
          car: ev.target.value,
          modo: (CARATT_BY[ev.target.value] || {}).famiglia === 'geometria' || ev.target.value === 'rugosita' ? 'max' : m.modo === 'max' ? 'minmax' : m.modo
        });
      }
    }, CARATT.map(function (c) {
      return /*#__PURE__*/React.createElement("option", {
        key: c.codice,
        value: c.codice
      }, c.simbolo ? "".concat(c.simbolo, " ") : '', c.nome);
    })), m.car === 'altro' && /*#__PURE__*/React.createElement("input", {
      className: "text-input",
      value: m.nome || '',
      disabled: disabled,
      placeholder: "Che misura?",
      "aria-label": "Che misura",
      onChange: function onChange(ev) {
        return updMisura(m.key, {
          nome: ev.target.value
        });
      }
    })), /*#__PURE__*/React.createElement("label", {
      className: "dett-f"
    }, /*#__PURE__*/React.createElement("span", null, "Tolleranza", /*#__PURE__*/React.createElement("span", {
      className: "seg-mini"
    }, [['minmax', 'min/max'], ['pm', '±'], ['max', 'max']].map(function (_ref25) {
      var _ref26 = _slicedToArray(_ref25, 2),
        k = _ref26[0],
        l = _ref26[1];
      return /*#__PURE__*/React.createElement("button", {
        key: k,
        type: "button",
        className: m.modo === k ? 'is-on' : '',
        disabled: disabled,
        onClick: function onClick() {
          return updMisura(m.key, {
            modo: k
          });
        }
      }, l);
    }))), /*#__PURE__*/React.createElement("div", {
      className: "dett-tol"
    }, m.modo === 'pm' && /*#__PURE__*/React.createElement("input", {
      className: "text-input",
      inputMode: "decimal",
      disabled: disabled,
      value: m.nom || '',
      placeholder: "nominale",
      "aria-label": "Nominale",
      onChange: function onChange(ev) {
        return updMisura(m.key, {
          nom: ev.target.value
        });
      }
    }), /*#__PURE__*/React.createElement("input", {
      className: "text-input",
      inputMode: "decimal",
      disabled: disabled,
      value: m.a || '',
      placeholder: m.modo === 'minmax' ? 'min' : m.modo === 'pm' ? '±' : 'max',
      "aria-label": "Tolleranza",
      onChange: function onChange(ev) {
        return updMisura(m.key, {
          a: ev.target.value
        });
      }
    }), m.modo !== 'max' && /*#__PURE__*/React.createElement("input", {
      className: "text-input",
      inputMode: "decimal",
      disabled: disabled,
      value: m.b || '',
      placeholder: m.modo === 'minmax' ? 'max' : '+ (se diverso)',
      "aria-label": "Tolleranza superiore",
      onChange: function onChange(ev) {
        return updMisura(m.key, {
          b: ev.target.value
        });
      }
    }))), f('Rilevato', m.ril, function (v) {
      return updMisura(m.key, {
        ril: v
      });
    }, {
      inputMode: 'decimal'
    }), f('Dove (quota / zona)', m.dove, function (v) {
      return updMisura(m.key, {
        dove: v
      });
    }, {
      placeholder: 'Es. sez. H-H, lato piano M'
    }), /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: "dett-x",
      title: "Togli misura",
      disabled: disabled,
      onClick: function onClick() {
        return upd({
          misure: d.misure.filter(function (x) {
            return x.key !== m.key;
          })
        });
      }
    }, "\xD7")), misuraUtile(m) && /*#__PURE__*/React.createElement("div", {
      className: "mis-out"
    }, e.fuori === true && /*#__PURE__*/React.createElement("span", {
      className: "mis-esito is-ko"
    }, "Fuori tolleranza ", e.scarto > 0 ? '+' : '−', fmtNum(Math.abs(e.scarto))), e.fuori === false && /*#__PURE__*/React.createElement("span", {
      className: "mis-esito is-ok"
    }, "Dentro la tolleranza"), /*#__PURE__*/React.createElement("span", {
      className: "mis-frase"
    }, fraseMisura(m))));
  }), /*#__PURE__*/React.createElement("div", {
    className: "dett-actions"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "link-btn",
    disabled: disabled,
    onClick: function onClick() {
      return upd({
        misure: [].concat(_toConsumableArray(d.misure || []), [emptyMisura()])
      });
    }
  }, "+ Aggiungi misura")), !disabled && vede('report_zeiss') && /*#__PURE__*/React.createElement(LetturaReport, {
    opId: opId,
    disabled: disabled,
    onAggiungi: function onAggiungi(righe) {
      var nuove = righe.map(function (_ref27) {
        var car = _ref27.car,
          nome = _ref27.nome,
          modo = _ref27.modo,
          nom = _ref27.nom,
          a = _ref27.a,
          b = _ref27.b,
          ril = _ref27.ril,
          dove = _ref27.dove;
        return _objectSpread(_objectSpread({}, emptyMisura()), {}, {
          car: car,
          nome: nome,
          modo: modo,
          nom: nom,
          a: a,
          b: b,
          ril: ril,
          dove: dove
        });
      });
      var tenute = (d.misure || []).filter(misuraUtile);
      upd({
        misure: [].concat(_toConsumableArray(tenute), _toConsumableArray(nuove))
      });
    }
  })), d.tipo === 'difetto' && casoAcceso('difetto') && /*#__PURE__*/React.createElement("div", {
    className: "dett-panel"
  }, /*#__PURE__*/React.createElement("div", {
    className: "dett-panel__head"
  }, "\uD83D\uDD0E Difetto sul pezzo"), /*#__PURE__*/React.createElement("div", {
    className: "dett-grid dett-grid--dif"
  }, /*#__PURE__*/React.createElement("label", {
    className: "dett-f"
  }, /*#__PURE__*/React.createElement("span", null, "Che difetto"), /*#__PURE__*/React.createElement("select", {
    className: "text-input",
    value: dif.genere || '',
    disabled: disabled,
    onChange: function onChange(ev) {
      return upd({
        difetto: _objectSpread(_objectSpread({}, dif), {}, {
          genere: ev.target.value
        })
      });
    }
  }, /*#__PURE__*/React.createElement("option", {
    value: ""
  }, "\u2014 scegli \u2014"), GENERI.map(function (g) {
    return /*#__PURE__*/React.createElement("option", {
      key: g.codice,
      value: g.codice
    }, g.nome);
  }))), f('Dove sul pezzo', dif.dove, function (v) {
    return upd({
      difetto: _objectSpread(_objectSpread({}, dif), {}, {
        dove: v
      })
    });
  }, {
    placeholder: 'Es. smusso adiacente piano B, diametro AY sez. S17'
  })), /*#__PURE__*/React.createElement("div", {
    className: "dett-grid dett-grid--dim"
  }, f('Lunghezza', dif.lung, function (v) {
    return upd({
      difetto: _objectSpread(_objectSpread({}, dif), {}, {
        lung: v
      })
    });
  }), f('Larghezza / altezza', dif.larg, function (v) {
    return upd({
      difetto: _objectSpread(_objectSpread({}, dif), {}, {
        larg: v
      })
    });
  }), f('Profondità', dif.prof, function (v) {
    return upd({
      difetto: _objectSpread(_objectSpread({}, dif), {}, {
        prof: v
      })
    });
  }), f('Estensione', dif.est, function (v) {
    return upd({
      difetto: _objectSpread(_objectSpread({}, dif), {}, {
        est: v
      })
    });
  }, {
    placeholder: 'Es. 45°'
  }))), d.tipo === 'documenti' && casoAcceso('documenti') && /*#__PURE__*/React.createElement("div", {
    className: "dett-panel"
  }, /*#__PURE__*/React.createElement("div", {
    className: "dett-panel__head"
  }, "\uD83C\uDFF7\uFE0F Marcatura / documenti che non coincidono"), /*#__PURE__*/React.createElement("div", {
    className: "dett-grid dett-grid--doc"
  }, f('Sul pezzo c’è', doc.trovato, function (v) {
    return upd({
      documenti: _objectSpread(_objectSpread({}, doc), {}, {
        trovato: v
      })
    });
  }, {
    placeholder: 'Es. marcato AW340'
  }), f('Atteso (documenti)', doc.atteso, function (v) {
    return upd({
      documenti: _objectSpread(_objectSpread({}, doc), {}, {
        atteso: v
      })
    });
  }, {
    placeholder: 'Es. AW341'
  })), /*#__PURE__*/React.createElement("div", {
    className: "dett-ask"
  }, /*#__PURE__*/React.createElement("span", null, "Documenti coinvolti:"), /*#__PURE__*/React.createElement("div", {
    className: "doc-chips"
  }, DOC_LIST.map(function (x) {
    var on = (doc.docs || []).includes(x);
    return /*#__PURE__*/React.createElement("button", {
      key: x,
      type: "button",
      className: "anom-sn__chip".concat(on ? ' is-on' : ''),
      disabled: disabled,
      onClick: function onClick() {
        return upd({
          documenti: _objectSpread(_objectSpread({}, doc), {}, {
            docs: on ? doc.docs.filter(function (y) {
              return y !== x;
            }) : [].concat(_toConsumableArray(doc.docs || []), [x])
          })
        });
      }
    }, x);
  })))), !vede('riferimento') ? null : d.rifAperto || rif.disegno || rif.sezione || rif.fase ? /*#__PURE__*/React.createElement("div", {
    className: "dett-grid dett-grid--rif"
  }, f('Disegno / revisione', rif.disegno, function (v) {
    return upd({
      rif: _objectSpread(_objectSpread({}, rif), {}, {
        disegno: v
      })
    });
  }), f('Sezione / vista', rif.sezione, function (v) {
    return upd({
      rif: _objectSpread(_objectSpread({}, rif), {}, {
        sezione: v
      })
    });
  }), f('Fase del ciclo / F.OP', rif.fase, function (v) {
    return upd({
      rif: _objectSpread(_objectSpread({}, rif), {}, {
        fase: v
      })
    });
  }, {
    placeholder: 'Es. Fase 80, pag. 1/1'
  })) : !disabled && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "link-btn",
    onClick: function onClick() {
      return upd({
        rifAperto: true
      });
    }
  }, "+ Riferimento (disegno, sezione, fase del ciclo)")), vede('tipo_difetto') && d.tipo && casoAcceso(d.tipo) && TIPI_DIFETTO.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "dett-tipo"
  }, /*#__PURE__*/React.createElement("span", {
    className: "field-label"
  }, "Tipo di difetto"), /*#__PURE__*/React.createElement("select", {
    className: "text-input",
    disabled: disabled,
    value: d.tipoDifettoId || (tipoSugg ? tipoSugg.id : ''),
    onChange: function onChange(ev) {
      return upd({
        tipoDifettoId: ev.target.value ? Number(ev.target.value) : null
      });
    }
  }, /*#__PURE__*/React.createElement("option", {
    value: ""
  }, "\u2014 non indicato \u2014"), TIPI_DIFETTO.map(function (t) {
    return /*#__PURE__*/React.createElement("option", {
      key: t.id,
      value: t.id
    }, t.nome);
  })), !tipoSel && tipoSugg && /*#__PURE__*/React.createElement("span", {
    className: "pill-auto"
  }, "proposto")), vede('copia_testo') && frasi.length > 0 && !disabled && /*#__PURE__*/React.createElement("div", {
    className: "dett-actions"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "link-btn",
    onClick: function onClick() {
      return onCopiaNelTesto(frasi);
    }
  }, "\u2193 Copia nella descrizione"), /*#__PURE__*/React.createElement("span", {
    className: "field-hint"
  }, "Se lasci vuota la descrizione, al salvataggio si usano queste righe.")));
};

// tutti: l'anomalia vale per tutti i seriali del blocco (default); altrimenti sel = S/N scelti.
var newAnomalia = function newAnomalia() {
  return {
    key: uid(),
    localId: null,
    testo: '',
    files: [],
    existing: [],
    gestita: false,
    avanzamento: '',
    tutti: true,
    sel: [],
    dett: emptyDett()
  };
};
// confermaScoperti: S/N senza anomalia già confermati dall'operatore (chiave = elenco), vale solo se l'elenco non cambia.
var newEditor = function newEditor() {
  return {
    bloccoId: null,
    voci: [],
    stati: [],
    dovePezzi: '',
    anomalie: [newAnomalia()],
    attiva: 0,
    bloccato: false,
    confermaRipetuti: false,
    confermaScoperti: ''
  };
};
var editorFromBlocco = function editorFromBlocco(b) {
  return {
    bloccoId: b.id,
    voci: _toConsumableArray(b.seriali || []),
    stati: _toConsumableArray(b.stato_superficie || []),
    dovePezzi: b.dove_pezzi || '',
    anomalie: (b.anomalie || []).map(function (a) {
      return {
        key: "s".concat(a.local_id),
        localId: a.local_id,
        testo: a.testo || '',
        files: [],
        existing: a.allegati || [],
        gestita: !!a.gestita,
        avanzamento: a.avanzamento || '',
        autoreId: a.autore_id || null,
        modificabile: a.modificabile !== false,
        tutti: a.tutti !== false,
        sel: a.tutti === false ? tokensOf(a.seriali) : [],
        dett: dettDaServer(a.dettaglio, a.tipo_difetto_id)
      };
    }),
    attiva: -1,
    bloccato: !!b.bloccato,
    confermaRipetuti: false,
    confermaScoperti: ''
  };
};
/* Bozza del blocco in scrittura, salvata in automatico sul server (senza gli allegati). */
var bozzaDa = function bozzaDa(ed) {
  return {
    bloccoId: ed.bloccoId,
    voci: ed.voci,
    stati: ed.stati,
    dovePezzi: ed.dovePezzi || '',
    anomalie: ed.anomalie.filter(function (a) {
      return a.localId || testoAnomalia(a) || a.files.length || a.dett && a.dett.tipo;
    }).map(function (a) {
      return {
        localId: a.localId,
        testo: a.testo,
        tutti: a.tutti,
        sel: a.sel,
        allegati: a.files.length,
        dett: a.dett ? _objectSpread(_objectSpread({}, dettPayload(a.dett)), {}, {
          tipoDifettoId: a.dett.tipoDifettoId || null
        }) : null,
        origineId: a.origineId || null,
        allegatiOrigine: a.allegatiOrigine || 0,
        copiaAllegati: !!a.copiaAllegati
      };
    }),
    daClona: !!ed.daClona
  };
};
var bozzaPiena = function bozzaPiena(bz) {
  return !!bz && ((bz.voci || []).length > 0 || (bz.stati || []).length > 0 || (bz.anomalie || []).length > 0 || !!bz.bloccoId);
};
var editorDaBozza = function editorDaBozza(bz, blocchi) {
  var blocco = bz.bloccoId ? (blocchi || []).find(function (b) {
    return b.id === bz.bloccoId;
  }) : null;
  if (bz.bloccoId && !blocco) return newEditor();
  var base = blocco ? editorFromBlocco(blocco) : newEditor();
  var daBozza = bz.anomalie || [];
  var perId = {};
  daBozza.forEach(function (a) {
    if (a.localId) perId[a.localId] = a;
  });
  var esistenti = blocco ? base.anomalie.map(function (a) {
    var b = perId[a.localId];
    return b && !a.gestita ? _objectSpread(_objectSpread({}, a), {}, {
      testo: b.testo || '',
      tutti: b.tutti !== false,
      sel: b.sel || [],
      dett: b.dett ? dettDaServer(b.dett, b.dett.tipoDifettoId) : a.dett
    }) : a;
  }) : [];
  var nuove = daBozza.filter(function (a) {
    return !a.localId;
  }).map(function (a) {
    return _objectSpread(_objectSpread({}, newAnomalia()), {}, {
      testo: a.testo || '',
      tutti: a.tutti !== false,
      sel: a.sel || [],
      dett: a.dett ? dettDaServer(a.dett, a.dett.tipoDifettoId) : emptyDett()
    }, a.origineId ? {
      origineId: a.origineId,
      allegatiOrigine: a.allegatiOrigine || 0,
      copiaAllegati: !!a.copiaAllegati
    } : {});
  });
  var anomalie = [].concat(_toConsumableArray(esistenti), _toConsumableArray(nuove));
  return _objectSpread(_objectSpread({}, base), {}, {
    voci: base.bloccato ? base.voci : _toConsumableArray(bz.voci || []),
    stati: _toConsumableArray(bz.stati || base.stati),
    dovePezzi: bz.dovePezzi != null ? bz.dovePezzi : base.dovePezzi || '',
    anomalie: anomalie.length ? anomalie : [newAnomalia()],
    attiva: anomalie.length ? anomalie.length - 1 : 0,
    daClona: !!bz.daClona
  });
};
/* S/N del blocco senza nessuna anomalia (stessa regola di controllo_service.seriali_senza_anomalia). */
var serialiScoperti = function serialiScoperti(tokens, anomalie) {
  var piene = (anomalie || []).filter(function (a) {
    return a.localId || a.testo.trim() || a.files.length;
  });
  if (tokens.length <= 1 || !piene.length || piene.some(function (a) {
    return a.tutti;
  })) return [];
  var coperti = new Set();
  piene.forEach(function (a) {
    return a.sel.forEach(function (t) {
      return coperti.add(t.toLowerCase());
    });
  });
  return tokens.filter(function (t) {
    return !coperti.has(t.toLowerCase());
  });
};
/* Singoli S/N -> voci, con i consecutivi in range (come seriali.comprimi_seriali). */
var comprimiTokens = function comprimiTokens(tokens) {
  var out = [];
  var run = null;
  var chiudi = function chiudi() {
    if (!run) return;
    var da = "".concat(run.p).concat(String(run.a).padStart(run.w, '0'));
    out.push(run.a === run.b ? da : "".concat(da, "-").concat(run.p).concat(String(run.b).padStart(run.w, '0')));
    run = null;
  };
  tokens.forEach(function (t) {
    var m = String(t).match(/^(.*?)(\d+)$/);
    if (!m) {
      chiudi();
      out.push(t);
      return;
    }
    var n = parseInt(m[2], 10);
    if (run && run.p.toLowerCase() === m[1].toLowerCase() && run.w === m[2].length && n === run.b + 1) {
      run.b = n;
      return;
    }
    chiudi();
    run = {
      p: m[1],
      w: m[2].length,
      a: n,
      b: n
    };
  });
  chiudi();
  return out;
};
var editorDirty = function editorDirty(ed) {
  return !!ed && (ed.bloccoId !== null || ed.voci.length > 0 || ed.stati.length > 0 || ed.anomalie.some(function (a) {
    return a.testo.trim() || a.files.length;
  }));
};
var StatoPill = function StatoPill(_ref28) {
  var a = _ref28.a;
  if (a.chiusa) return /*#__PURE__*/React.createElement("span", {
    className: "pill pill-ok"
  }, "Chiusa");
  if (a.gestita) return /*#__PURE__*/React.createElement("span", {
    className: "pill pill-info"
  }, a.avanzamento || 'Gestita');
  return /*#__PURE__*/React.createElement("span", {
    className: "pill pill-wait"
  }, "In attesa del capocommessa");
};

/* Campo seriali a «chip»: Invio, virgola o spazio confermano; si incollano anche elenchi. */
var SerialInput = function SerialInput(_ref29) {
  var voci = _ref29.voci,
    onChange = _ref29.onChange,
    disabled = _ref29.disabled,
    inputRef = _ref29.inputRef;
  var _useState25 = useState(''),
    _useState26 = _slicedToArray(_useState25, 2),
    text = _useState26[0],
    setText = _useState26[1];
  var add = function add(parts) {
    if (!parts.length) return;
    var next = _toConsumableArray(voci);
    parts.forEach(function (p) {
      var v = p.replace(/\s*-\s*/g, '-');
      if (!next.some(function (x) {
        return x.toLowerCase() === v.toLowerCase();
      })) next.push(v);
    });
    onChange(next);
  };
  var commit = function commit() {
    var parts = splitSerialText(text);
    setText('');
    add(parts);
  };
  return /*#__PURE__*/React.createElement("div", {
    className: "sn-field".concat(disabled ? ' is-disabled' : ''),
    onClick: function onClick() {
      return inputRef && inputRef.current && inputRef.current.focus();
    }
  }, voci.map(function (v) {
    var p = parseVoce(v);
    return /*#__PURE__*/React.createElement("span", {
      key: v,
      className: "sn-chip".concat(p && p.range ? ' is-range' : '')
    }, p && p.range ? /*#__PURE__*/React.createElement(React.Fragment, null, p.da, /*#__PURE__*/React.createElement("span", {
      className: "sn-chip__arrow"
    }, "\u2192"), p.a, /*#__PURE__*/React.createElement("span", {
      className: "sn-chip__n"
    }, p.tokens.length, " pz")) : v, !disabled && /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: "sn-chip__x",
      "aria-label": "Rimuovi ".concat(v),
      onClick: function onClick(e) {
        e.stopPropagation();
        onChange(voci.filter(function (x) {
          return x !== v;
        }));
      }
    }, "\xD7"));
  }), !disabled && /*#__PURE__*/React.createElement("input", {
    ref: inputRef,
    className: "sn-field__input",
    type: "text",
    value: text,
    placeholder: voci.length ? 'Aggiungi altri seriali…' : 'Es. LCN00001 · LCN00005-LCN00010 · più seriali separati da virgola',
    onChange: function onChange(e) {
      return setText(e.target.value);
    },
    onKeyDown: function onKeyDown(e) {
      if (e.key === 'Enter' || e.key === ',' || e.key === ';' || e.key === ' ' && !/-\s*$/.test(text)) {
        if (text.trim()) {
          e.preventDefault();
          commit();
        } else if (e.key === 'Enter') e.preventDefault();
      } else if (e.key === 'Backspace' && !text && voci.length) {
        onChange(voci.slice(0, -1));
      }
    },
    onBlur: commit,
    onPaste: function onPaste(e) {
      var t = e.clipboardData ? e.clipboardData.getData('text') : '';
      if (t && /[\s,;]/.test(t.trim())) {
        e.preventDefault();
        add(splitSerialText(t));
      }
    }
  }));
};
var ORDINI_CACHE = null;
/* Cambio OP dalla pagina di inserimento: si clicca su OP o P/N in alto. */
var CambiaOpPanel = function CambiaOpPanel(_ref30) {
  var opAttuale = _ref30.opAttuale,
    nSalvate = _ref30.nSalvate,
    busy = _ref30.busy,
    err = _ref30.err,
    onScegli = _ref30.onScegli,
    onCancel = _ref30.onCancel;
  var _useState27 = useState(ORDINI_CACHE || []),
    _useState28 = _slicedToArray(_useState27, 2),
    ordini = _useState28[0],
    setOrdini = _useState28[1];
  var _useState29 = useState(''),
    _useState30 = _slicedToArray(_useState29, 2),
    q = _useState30[0],
    setQ = _useState30[1];
  var _useState31 = useState(null),
    _useState32 = _slicedToArray(_useState31, 2),
    sel = _useState32[0],
    setSel = _useState32[1];
  useEffect(function () {
    if (ORDINI_CACHE) return;
    getJson(API.db_ordini, 'Elenco OP').then(function (d) {
      ORDINI_CACHE = Array.isArray(d) ? d : [];
      setOrdini(ORDINI_CACHE);
    })["catch"](function () {});
  }, []);
  var t = q.trim().toLowerCase();
  var lista = ordini.filter(function (o) {
    return String(o.id || '') !== String(opAttuale || '');
  }).filter(function (o) {
    return !t || [o.id, o.pn, o.capo, o.car].some(function (v) {
      return String(v || '').toLowerCase().includes(t);
    });
  }).slice(0, 30);
  return /*#__PURE__*/React.createElement("div", {
    className: "cambia-op"
  }, /*#__PURE__*/React.createElement("div", {
    className: "dett-panel__head"
  }, "Cambia OP / P/N ", /*#__PURE__*/React.createElement("small", null, "(ora: ", opAttuale, ")")), /*#__PURE__*/React.createElement("input", {
    className: "text-input",
    autoFocus: true,
    value: q,
    disabled: busy,
    placeholder: "Cerca per OP, P/N, capocommessa o CAR\u2026",
    onChange: function onChange(e) {
      setQ(e.target.value);
      setSel(null);
    }
  }), /*#__PURE__*/React.createElement("div", {
    className: "cambia-op__list"
  }, !ordini.length && /*#__PURE__*/React.createElement("small", null, "Caricamento degli OP\u2026"), ordini.length > 0 && !lista.length && /*#__PURE__*/React.createElement("small", null, "Nessun OP trovato."), lista.map(function (o) {
    var _o$item_id;
    return /*#__PURE__*/React.createElement("button", {
      type: "button",
      key: (_o$item_id = o.item_id) !== null && _o$item_id !== void 0 ? _o$item_id : o.id,
      className: "cambia-op__row".concat(sel && sel.id === o.id ? ' is-sel' : ''),
      disabled: busy,
      onClick: function onClick() {
        return setSel(o);
      }
    }, /*#__PURE__*/React.createElement("strong", null, o.id), /*#__PURE__*/React.createElement("span", null, "P/N ", o.pn || '—'), /*#__PURE__*/React.createElement("small", null, [o.capo, o.car].filter(function (v) {
      return v && v !== '—';
    }).join(' · ')));
  })), err && /*#__PURE__*/React.createElement("div", {
    className: "error-msg"
  }, err), /*#__PURE__*/React.createElement("div", {
    className: "cambia-op__foot"
  }, /*#__PURE__*/React.createElement("span", null, nSalvate ? "".concat(nSalvate === 1 ? "L'anomalia già salvata passa" : "Le ".concat(nSalvate, " anomalie gi\xE0 salvate passano"), " all'OP scelto (solo se nessuna \xE8 stata ancora gestita); il blocco che stai scrivendo resta com'\xE8.") : 'Il controllo prosegue sull’OP scelto; quello che stai scrivendo resta com’è.'), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn-secondary",
    disabled: busy,
    onClick: onCancel
  }, "Annulla"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn-primary",
    disabled: busy || !sel,
    onClick: function onClick() {
      return onScegli(sel);
    }
  }, busy ? 'Sposto…' : sel ? "Passa a ".concat(sel.id) : 'Scegli un OP')));
};

/* «Taglia»: sposta un'anomalia salvata su un altro S/N (stesso OP o un altro OP). */
var TagliaPanel = function TagliaPanel(_ref31) {
  var anomalia = _ref31.anomalia,
    opCorrente = _ref31.opCorrente,
    onDone = _ref31.onDone,
    onCancel = _ref31.onCancel;
  var _useState33 = useState(opCorrente || ''),
    _useState34 = _slicedToArray(_useState33, 2),
    opId = _useState34[0],
    setOpId = _useState34[1];
  var _useState35 = useState(''),
    _useState36 = _slicedToArray(_useState35, 2),
    sn = _useState36[0],
    setSn = _useState36[1];
  var _useState37 = useState(ORDINI_CACHE || []),
    _useState38 = _slicedToArray(_useState37, 2),
    ordini = _useState38[0],
    setOrdini = _useState38[1];
  var _useState39 = useState([]),
    _useState40 = _slicedToArray(_useState39, 2),
    seriali = _useState40[0],
    setSeriali = _useState40[1];
  var _useState41 = useState(false),
    _useState42 = _slicedToArray(_useState41, 2),
    busy = _useState42[0],
    setBusy = _useState42[1];
  var _useState43 = useState(''),
    _useState44 = _slicedToArray(_useState43, 2),
    err = _useState44[0],
    setErr = _useState44[1];
  useEffect(function () {
    if (ORDINI_CACHE) return;
    getJson(API.db_ordini, 'Elenco OP').then(function (d) {
      ORDINI_CACHE = Array.isArray(d) ? d : [];
      setOrdini(ORDINI_CACHE);
    })["catch"](function () {});
  }, []);
  useEffect(function () {
    var op = opId.trim();
    setSeriali([]);
    if (!op) return undefined;
    var t = setTimeout(function () {
      getJson("".concat(API.seriali_op, "?op_id=").concat(encodeURIComponent(op)), 'Seriali OP').then(function (d) {
        return setSeriali(Array.isArray(d.seriali) ? d.seriali : []);
      })["catch"](function () {});
    }, 300);
    return function () {
      return clearTimeout(t);
    };
  }, [opId]);
  var altroOp = opId.trim().toLowerCase() !== String(opCorrente || '').toLowerCase();
  var conferma = /*#__PURE__*/function () {
    var _ref32 = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee8() {
      var sel, j, _t5;
      return _regenerator().w(function (_context8) {
        while (1) switch (_context8.p = _context8.n) {
          case 0:
            if (opId.trim()) {
              _context8.n = 1;
              break;
            }
            setErr('Indica l’OP.');
            return _context8.a(2);
          case 1:
            if (sn.trim()) {
              _context8.n = 2;
              break;
            }
            setErr('Indica il S/N di destinazione.');
            return _context8.a(2);
          case 2:
            sel = ordini.find(function (o) {
              return String(o.id || '').toLowerCase() === opId.trim().toLowerCase();
            });
            setBusy(true);
            setErr('');
            _context8.p = 3;
            _context8.n = 4;
            return postJson(API.sposta, {
              local_id: anomalia.localId,
              op_id: opId.trim(),
              op_item_id: sel ? sel.item_id : null,
              seriali: splitSerialText(sn)
            }, 'Taglia');
          case 4:
            j = _context8.v;
            onDone(j);
            _context8.n = 6;
            break;
          case 5:
            _context8.p = 5;
            _t5 = _context8.v;
            setErr(_t5.message);
            setBusy(false);
          case 6:
            return _context8.a(2);
        }
      }, _callee8, null, [[3, 5]]);
    }));
    return function conferma() {
      return _ref32.apply(this, arguments);
    };
  }();
  return /*#__PURE__*/React.createElement("div", {
    className: "anom-taglia"
  }, /*#__PURE__*/React.createElement("div", {
    className: "dett-panel__head"
  }, "\u2702 Taglia: sposta l\u2019anomalia #", anomalia.localId, " su un altro S/N"), /*#__PURE__*/React.createElement("div", {
    className: "anom-taglia__row"
  }, /*#__PURE__*/React.createElement("label", null, "OP", /*#__PURE__*/React.createElement("input", {
    className: "text-input",
    list: "taglia-op",
    value: opId,
    disabled: busy,
    onChange: function onChange(e) {
      return setOpId(e.target.value);
    },
    placeholder: "Stesso OP o un altro"
  }), /*#__PURE__*/React.createElement("datalist", {
    id: "taglia-op"
  }, ordini.slice(0, 500).map(function (o) {
    var _o$item_id2;
    return /*#__PURE__*/React.createElement("option", {
      key: (_o$item_id2 = o.item_id) !== null && _o$item_id2 !== void 0 ? _o$item_id2 : o.id,
      value: o.id
    });
  }))), /*#__PURE__*/React.createElement("label", null, "S/N di destinazione", /*#__PURE__*/React.createElement("input", {
    className: "text-input",
    list: "taglia-sn",
    value: sn,
    disabled: busy,
    autoFocus: true,
    onChange: function onChange(e) {
      return setSn(e.target.value);
    },
    placeholder: "Es. LCN00012 o LCN00012-LCN00015",
    onKeyDown: function onKeyDown(e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        conferma();
      }
    }
  }), /*#__PURE__*/React.createElement("datalist", {
    id: "taglia-sn"
  }, seriali.slice(0, 500).map(function (s) {
    return /*#__PURE__*/React.createElement("option", {
      key: s,
      value: s
    });
  })))), err && /*#__PURE__*/React.createElement("div", {
    className: "error-msg",
    role: "alert"
  }, err), /*#__PURE__*/React.createElement("div", {
    className: "anom-taglia__foot"
  }, /*#__PURE__*/React.createElement("small", null, altroOp ? 'Esce da questo controllo e passa all’OP indicato: il suo capocommessa la trova nel riepilogo delle modifiche.' : 'Resta in questo controllo: va nel blocco che ha già quel S/N, altrimenti in un blocco nuovo.'), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn-secondary",
    disabled: busy,
    onClick: onCancel
  }, "Annulla"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn-primary",
    disabled: busy,
    onClick: conferma
  }, busy ? 'Sposto…' : 'Sposta qui')));
};

/* Allegati di una anomalia: trascina, sfoglia o incolla (Ctrl+V) dagli appunti. */
var AttachmentZone = function AttachmentZone(_ref33) {
  var files = _ref33.files,
    existing = _ref33.existing,
    onAdd = _ref33.onAdd,
    onRemove = _ref33.onRemove,
    disabled = _ref33.disabled;
  var _useState45 = useState(false),
    _useState46 = _slicedToArray(_useState45, 2),
    over = _useState46[0],
    setOver = _useState46[1];
  var inputRef = useRef(null);
  var previews = React.useMemo(function () {
    return files.map(function (f) {
      return isImageFile(f) ? URL.createObjectURL(f) : '';
    });
  }, [files]);
  useEffect(function () {
    return function () {
      return previews.forEach(function (u) {
        return u && URL.revokeObjectURL(u);
      });
    };
  }, [previews]);
  return /*#__PURE__*/React.createElement("div", {
    className: "drop-zone".concat(over ? ' is-over' : '').concat(disabled ? ' is-disabled' : ''),
    onDragOver: function onDragOver(e) {
      if (disabled) return;
      e.preventDefault();
      setOver(true);
    },
    onDragLeave: function onDragLeave() {
      return setOver(false);
    },
    onDrop: function onDrop(e) {
      if (disabled) return;
      e.preventDefault();
      setOver(false);
      onAdd(Array.from(e.dataTransfer.files || []));
    }
  }, /*#__PURE__*/React.createElement("input", {
    ref: inputRef,
    type: "file",
    multiple: true,
    hidden: true,
    accept: ".jpg,.jpeg,.png,.gif,.bmp,.webp,.pdf,.doc,.docx,.xls,.xlsx,.xlsm,.csv",
    onChange: function onChange(e) {
      var sel = Array.from(e.target.files || []);
      e.target.value = '';
      onAdd(sel);
    }
  }), !disabled && /*#__PURE__*/React.createElement("div", {
    className: "drop-zone__hint"
  }, /*#__PURE__*/React.createElement("svg", {
    width: "18",
    height: "18",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "2",
    strokeLinecap: "round",
    strokeLinejoin: "round",
    "aria-hidden": "true"
  }, /*#__PURE__*/React.createElement("path", {
    d: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"
  }), /*#__PURE__*/React.createElement("polyline", {
    points: "17 8 12 3 7 8"
  }), /*#__PURE__*/React.createElement("line", {
    x1: "12",
    y1: "3",
    x2: "12",
    y2: "15"
  })), /*#__PURE__*/React.createElement("span", null, "Trascina qui foto e documenti, ", /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "link-btn",
    onClick: function onClick() {
      return inputRef.current && inputRef.current.click();
    }
  }, "sfoglia"), " oppure incolla con ", /*#__PURE__*/React.createElement("kbd", null, "Ctrl"), "+", /*#__PURE__*/React.createElement("kbd", null, "V"))), (existing.length > 0 || files.length > 0) && /*#__PURE__*/React.createElement("div", {
    className: "thumbs"
  }, existing.map(function (f) {
    return /*#__PURE__*/React.createElement("div", {
      key: f.file_id,
      className: "thumb is-saved",
      title: "".concat(f.name, " \xB7 gi\xE0 caricato")
    }, /*#__PURE__*/React.createElement("span", {
      className: "thumb__ext"
    }, fileExt(f.name).replace('.', '').toUpperCase() || 'FILE'), /*#__PURE__*/React.createElement("span", {
      className: "thumb__name"
    }, f.name));
  }), files.map(function (f, i) {
    return /*#__PURE__*/React.createElement("div", {
      key: "".concat(f.name, "-").concat(f.size, "-").concat(i),
      className: "thumb",
      title: "".concat(f.name, " \xB7 ").concat(formatBytes(f.size))
    }, previews[i] ? /*#__PURE__*/React.createElement("img", {
      src: previews[i],
      alt: ""
    }) : /*#__PURE__*/React.createElement("span", {
      className: "thumb__ext"
    }, fileExt(f.name).replace('.', '').toUpperCase() || 'FILE'), /*#__PURE__*/React.createElement("span", {
      className: "thumb__name"
    }, f.name), !disabled && /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: "thumb__x",
      "aria-label": "Rimuovi ".concat(f.name),
      onClick: function onClick() {
        return onRemove(i);
      }
    }, "\xD7"));
  })));
};

/* Blocco già salvato: sola lettura, compatto. */
var BloccoCongelato = function BloccoCongelato(_ref34) {
  var b = _ref34.b,
    index = _ref34.index,
    onEdit = _ref34.onEdit,
    canEdit = _ref34.canEdit;
  var _useState47 = useState(false),
    _useState48 = _slicedToArray(_useState47, 2),
    open = _useState48[0],
    setOpen = _useState48[1];
  return /*#__PURE__*/React.createElement("div", {
    className: "blk is-frozen"
  }, /*#__PURE__*/React.createElement("div", {
    className: "blk-head"
  }, /*#__PURE__*/React.createElement("div", {
    className: "blk-num"
  }, index + 1), /*#__PURE__*/React.createElement("div", {
    className: "blk-head__main"
  }, /*#__PURE__*/React.createElement("div", {
    className: "blk-sn"
  }, b.seriale_label), /*#__PURE__*/React.createElement("div", {
    className: "blk-meta"
  }, "Fase ", b.fase, " \xB7 ", tokensOf(b.seriali).length, " pezz", tokensOf(b.seriali).length === 1 ? 'o' : 'i', " \xB7 ", b.anomalie.length, " anomali", b.anomalie.length === 1 ? 'a' : 'e', b.stato_superficie.map(function (s) {
    return /*#__PURE__*/React.createElement("span", {
      key: s,
      className: "pill pill-sup",
      style: {
        marginLeft: 6
      }
    }, s);
  }))), /*#__PURE__*/React.createElement("span", {
    className: "blk-lock",
    title: "Blocco salvato"
  }, /*#__PURE__*/React.createElement("svg", {
    width: "14",
    height: "14",
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: "2.4",
    strokeLinecap: "round",
    strokeLinejoin: "round",
    "aria-hidden": "true"
  }, /*#__PURE__*/React.createElement("rect", {
    x: "3",
    y: "11",
    width: "18",
    height: "11",
    rx: "2"
  }), /*#__PURE__*/React.createElement("path", {
    d: "M7 11V7a5 5 0 0 1 10 0v4"
  })), "Salvato")), /*#__PURE__*/React.createElement("ol", {
    className: "blk-list"
  }, b.anomalie.map(function (a, i) {
    return /*#__PURE__*/React.createElement("li", {
      key: a.local_id,
      className: "blk-item"
    }, /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: "blk-item__btn",
      onClick: function onClick() {
        return setOpen(open === a.local_id ? false : a.local_id);
      },
      "aria-expanded": open === a.local_id
    }, /*#__PURE__*/React.createElement("span", {
      className: "blk-item__n"
    }, i + 1), /*#__PURE__*/React.createElement("span", {
      className: "blk-item__txt".concat(open === a.local_id ? ' is-open' : '')
    }, a.testo), a.tutti === false && /*#__PURE__*/React.createElement("span", {
      className: "pill pill-parz",
      title: "Solo sui S/N: ".concat(a.seriale_label)
    }, "Solo ", a.seriale_label), a.allegati.length > 0 && /*#__PURE__*/React.createElement("span", {
      className: "blk-item__att"
    }, "\uD83D\uDCCE ", a.allegati.length), /*#__PURE__*/React.createElement(StatoPill, {
      a: a
    })), open === a.local_id && a.note_capocommessa && /*#__PURE__*/React.createElement("div", {
      className: "blk-item__note"
    }, /*#__PURE__*/React.createElement("strong", null, "Capocommessa:"), " ", a.note_capocommessa));
  })), (b.seriali_scoperti || []).length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "sn-warn"
  }, "\u26A0 S/N senza anomalia: ", comprimiTokens(b.seriali_scoperti).join(', ')), canEdit && /*#__PURE__*/React.createElement("div", {
    className: "blk-foot"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn-secondary btn-sm",
    onClick: onEdit
  }, "Modifica o aggiungi anomalie")));
};

/* S/N presenti in più blocchi dello stesso controllo. */
var serialiMultiBlocco = function serialiMultiBlocco(blocchi) {
  var map = {};
  (blocchi || []).forEach(function (b, i) {
    return tokensOf(b.seriali).forEach(function (t) {
      var k = t.toLowerCase();
      (map[k] = map[k] || {
        token: t,
        blocchi: []
      }).blocchi.push(i + 1);
    });
  });
  return Object.values(map).filter(function (x) {
    return x.blocchi.length > 1;
  });
};

/* Riepilogo del controllo: prima di terminare (da confermare) e dopo (da stampare). */
/* Destinatari della mail: capocommessa/CAR risolti dall'OP + persone aggiunte in copia.
   Si aggiungono solo persone dell'anagrafica (ricerca per nome o email): il server
   rifiuta gli indirizzi non collegati a nessuno, perché la mail porta il link di decisione. */
var DestinatariMail = function DestinatariMail(_ref35) {
  var destinatari = _ref35.destinatari,
    extra = _ref35.extra,
    onChange = _ref35.onChange,
    disabled = _ref35.disabled,
    compact = _ref35.compact;
  var _useState49 = useState(false),
    _useState50 = _slicedToArray(_useState49, 2),
    aperto = _useState50[0],
    setAperto = _useState50[1]; // false | 'persona' | 'capo'
  var _useState51 = useState(null),
    _useState52 = _slicedToArray(_useState51, 2),
    capi = _useState52[0],
    setCapi = _useState52[1];
  var _useState53 = useState(''),
    _useState54 = _slicedToArray(_useState53, 2),
    q = _useState54[0],
    setQ = _useState54[1];
  var _useState55 = useState([]),
    _useState56 = _slicedToArray(_useState55, 2),
    sug = _useState56[0],
    setSug = _useState56[1];
  var _useState57 = useState(0),
    _useState58 = _slicedToArray(_useState57, 2),
    hi = _useState58[0],
    setHi = _useState58[1];
  var _useState59 = useState(''),
    _useState60 = _slicedToArray(_useState59, 2),
    msg = _useState60[0],
    setMsg = _useState60[1];
  var lista = extra || [];
  var gia = new Set([destinatari && destinatari.to_email, destinatari && destinatari.cc_email].concat(_toConsumableArray(lista.map(function (d) {
    return d.email;
  }))).filter(Boolean).map(function (e) {
    return e.toLowerCase();
  }));
  useEffect(function () {
    if (aperto !== 'capo' || capi) return undefined;
    var alive = true;
    getJson("".concat(API.controllo_persone, "?ruolo=capocommessa"), 'Capicommessa').then(function (j) {
      return alive && setCapi(j.results || []);
    })["catch"](function (e) {
      if (alive) {
        setCapi([]);
        setMsg(e.message);
      }
    });
    return function () {
      alive = false;
    };
  }, [aperto]);
  useEffect(function () {
    if (aperto !== 'capo') return;
    var t = q.trim().toLowerCase();
    setSug((capi || []).filter(function (p) {
      return !gia.has(p.email.toLowerCase()) && (!t || p.nome.toLowerCase().includes(t) || p.email.toLowerCase().includes(t));
    }));
    setHi(0);
  }, [aperto, capi, q, extra]);
  useEffect(function () {
    if (aperto !== 'persona') return undefined;
    var testo = q.trim();
    if (testo.length < 2) {
      setSug([]);
      return undefined;
    }
    var alive = true;
    var t = setTimeout(function () {
      getJson("".concat(API.controllo_persone, "?q=").concat(encodeURIComponent(testo)), 'Ricerca persone').then(function (j) {
        if (!alive) return;
        setSug((j.results || []).filter(function (p) {
          return !gia.has(p.email.toLowerCase());
        }));
        setHi(0);
        setMsg('');
      })["catch"](function (e) {
        return alive && setMsg(e.message);
      });
    }, 220);
    return function () {
      alive = false;
      clearTimeout(t);
    };
  }, [q, aperto]);
  var chiudi = function chiudi() {
    setAperto(false);
    setQ('');
    setSug([]);
    setMsg('');
  };
  var aggiungi = function aggiungi(p) {
    if (!p || gia.has(p.email.toLowerCase())) return;
    onChange([].concat(_toConsumableArray(lista), [{
      email: p.email,
      nome: p.nome
    }]));
    chiudi();
  };
  var onKey = function onKey(e) {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setHi(function (h) {
        return Math.min(h + 1, sug.length - 1);
      });
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setHi(function (h) {
        return Math.max(h - 1, 0);
      });
    } else if (e.key === 'Escape') chiudi();else if (e.key === 'Enter') {
      e.preventDefault();
      if (sug[hi]) aggiungi(sug[hi]);else if (aperto === 'persona' && q.includes('@')) setMsg('Nessuna persona in anagrafica con questo indirizzo: si possono aggiungere solo persone collegate a un utente.');
    }
  };
  var chip = function chip(nome, email, key) {
    return /*#__PURE__*/React.createElement("span", {
      key: key,
      className: "dest-chip",
      title: email
    }, nome);
  };
  return /*#__PURE__*/React.createElement("div", {
    className: "dest-mail".concat(compact ? ' dest-mail--compact' : ''),
    "aria-label": "Destinatari della mail"
  }, /*#__PURE__*/React.createElement("div", {
    className: "dest-mail__row"
  }, /*#__PURE__*/React.createElement("span", {
    className: "dest-mail__lbl"
  }, "A"), destinatari && destinatari.to ? chip(destinatari.to, destinatari.to_email) : /*#__PURE__*/React.createElement("span", {
    className: "copilot-err"
  }, destinatari ? 'Capocommessa e CAR dell’OP senza indirizzo email: la mail non potrà partire, avvisa l’ufficio.' : 'Lettura destinatari…')), /*#__PURE__*/React.createElement("div", {
    className: "dest-mail__row"
  }, /*#__PURE__*/React.createElement("span", {
    className: "dest-mail__lbl"
  }, "In copia"), destinatari && destinatari.cc && chip(destinatari.cc, destinatari.cc_email), lista.map(function (d) {
    return /*#__PURE__*/React.createElement("span", {
      key: d.email,
      className: "dest-chip is-extra",
      title: d.email
    }, d.nome || d.email, /*#__PURE__*/React.createElement("small", null, d.email), !disabled && /*#__PURE__*/React.createElement("button", {
      type: "button",
      "aria-label": "Togli ".concat(d.nome || d.email),
      onClick: function onClick() {
        return onChange(lista.filter(function (x) {
          return x.email !== d.email;
        }));
      }
    }, "\xD7"));
  }), !(destinatari && destinatari.cc) && !lista.length && /*#__PURE__*/React.createElement("span", {
    className: "field-hint"
  }, "nessuno"), !disabled && !aperto && lista.length < 10 && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "link-btn",
    onClick: function onClick() {
      return setAperto('capo');
    }
  }, "+ Aggiungi altro capocommessa"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "link-btn",
    onClick: function onClick() {
      return setAperto('persona');
    }
  }, "+ Aggiungi persona"))), destinatari && (destinatari.riepilogo || []).length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "dest-mail__row",
    title: "Lista \xABRiepilogo modifiche\xBB di Configurazione \u2192 Notifiche"
  }, /*#__PURE__*/React.createElement("span", {
    className: "dest-mail__lbl"
  }, "Riepilogo"), destinatari.riepilogo.map(function (d) {
    return chip(d.nome || d.email, d.email, d.email);
  }), /*#__PURE__*/React.createElement("span", {
    className: "dest-mail__note"
  }, "riepilogo senza link, da Configurazione")), destinatari && (destinatari.riepilogo_rdc || []).length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "dest-mail__row",
    title: "Lista \xABRDC / segnalazione cliente\xBB di Configurazione \u2192 Notifiche"
  }, /*#__PURE__*/React.createElement("span", {
    className: "dest-mail__lbl"
  }, "Se RDC"), destinatari.riepilogo_rdc.map(function (d) {
    return chip(d.nome || d.email, d.email, d.email);
  }), /*#__PURE__*/React.createElement("span", {
    className: "dest-mail__note"
  }, "solo se un\u2019anomalia \xE8 da aprire RDC o da segnalare al cliente")), aperto && !disabled && /*#__PURE__*/React.createElement("div", {
    className: "dest-add"
  }, /*#__PURE__*/React.createElement("input", {
    className: "text-input",
    type: "text",
    autoFocus: true,
    value: q,
    placeholder: aperto === 'capo' ? 'Filtra i capicommessa…' : 'Nome, cognome o email…',
    onFocus: function onFocus() {
      return aperto === 'capo' && setHi(0);
    },
    onChange: function onChange(e) {
      return setQ(e.target.value);
    },
    onKeyDown: onKey,
    "aria-label": aperto === 'capo' ? 'Scegli il capocommessa da aggiungere in copia' : 'Cerca persona da aggiungere in copia'
  }), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn-secondary btn-sm",
    onClick: chiudi
  }, "Chiudi"), sug.length > 0 && /*#__PURE__*/React.createElement("ul", {
    className: "dest-sug",
    role: "listbox"
  }, sug.map(function (p, i) {
    return /*#__PURE__*/React.createElement("li", {
      key: p.email
    }, /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: i === hi ? 'is-hi' : '',
      onMouseDown: function onMouseDown(e) {
        e.preventDefault();
        aggiungi(p);
      }
    }, /*#__PURE__*/React.createElement("strong", null, p.nome), /*#__PURE__*/React.createElement("small", null, p.email)));
  })), aperto === 'capo' && capi === null && /*#__PURE__*/React.createElement("span", {
    className: "field-hint"
  }, "Carico i capicommessa\u2026"), aperto === 'capo' && capi !== null && !sug.length && !msg && /*#__PURE__*/React.createElement("span", {
    className: "field-hint"
  }, "Nessun altro capocommessa con email disponibile."), aperto === 'persona' && q.trim().length >= 2 && !sug.length && !msg && /*#__PURE__*/React.createElement("span", {
    className: "field-hint"
  }, "Nessuna persona trovata.")), msg && /*#__PURE__*/React.createElement("div", {
    className: "copilot-err"
  }, msg));
};
var RiepilogoControllo = function RiepilogoControllo(_ref36) {
  var op = _ref36.op,
    controllo = _ref36.controllo,
    destinatari = _ref36.destinatari,
    onChangeExtra = _ref36.onChangeExtra;
  var blocchi = controllo.blocchi || [];
  var pezzi = new Set();
  blocchi.forEach(function (b) {
    return tokensOf(b.seriali).forEach(function (t) {
      return pezzi.add(t.toLowerCase());
    });
  });
  var nAnom = blocchi.reduce(function (n, b) {
    return n + b.anomalie.length;
  }, 0);
  var nAll = blocchi.reduce(function (n, b) {
    return n + b.anomalie.reduce(function (m, a) {
      return m + (a.allegati || []).length;
    }, 0);
  }, 0);
  var ripetuti = serialiMultiBlocco(blocchi);
  var senzaSup = STATI_SUPERFICIE.length ? blocchi.filter(function (b) {
    return !(b.stato_superficie || []).length;
  }).map(function (b, i) {
    return b.ordine || i + 1;
  }) : [];
  var scoperti = blocchi.map(function (b, i) {
    return {
      n: i + 1,
      sn: b.seriali_scoperti || []
    };
  }).filter(function (x) {
    return x.sn.length;
  });
  return /*#__PURE__*/React.createElement("div", {
    className: "riep"
  }, /*#__PURE__*/React.createElement("div", {
    className: "riep-kpi"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("strong", null, blocchi.length), /*#__PURE__*/React.createElement("span", null, "Blocchi")), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("strong", null, pezzi.size), /*#__PURE__*/React.createElement("span", null, "Pezzi")), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("strong", null, nAnom), /*#__PURE__*/React.createElement("span", null, "Anomalie")), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("strong", null, nAll), /*#__PURE__*/React.createElement("span", null, "Allegati"))), /*#__PURE__*/React.createElement("div", {
    className: "riep-mail"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("strong", null, "OP ", op.id), " \xB7 fase ", /*#__PURE__*/React.createElement("strong", null, controllo.fase), controllo.operatore ? /*#__PURE__*/React.createElement(React.Fragment, null, " \xB7 operatore ", controllo.operatore) : null)), /*#__PURE__*/React.createElement("div", {
    className: "field-group"
  }, /*#__PURE__*/React.createElement("span", {
    className: "field-label"
  }, "Mail al capocommessa con il link di decisione"), /*#__PURE__*/React.createElement(DestinatariMail, {
    destinatari: destinatari,
    extra: controllo.destinatari_extra || [],
    onChange: onChangeExtra || function () {},
    disabled: !onChangeExtra
  })), ripetuti.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "riep-warn"
  }, "S/N in pi\xF9 blocchi (confermato in inserimento): ", ripetuti.slice(0, 10).map(function (r) {
    return "".concat(r.token, " \u2192 blocchi ").concat(r.blocchi.join(', '));
  }).join(' · '), ripetuti.length > 10 ? '…' : ''), senzaSup.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "riep-warn"
  }, "Stato superficie non indicato nei blocchi ", senzaSup.join(', '), "."), scoperti.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "riep-warn"
  }, "S/N senza nessuna anomalia (confermato in inserimento): ", scoperti.map(function (x) {
    return "blocco ".concat(x.n, " \u2192 ").concat(comprimiTokens(x.sn).join(', '));
  }).join(' · ')), blocchi.map(function (b, i) {
    return /*#__PURE__*/React.createElement("div", {
      className: "riep-blk",
      key: b.id
    }, /*#__PURE__*/React.createElement("div", {
      className: "riep-blk__head"
    }, /*#__PURE__*/React.createElement("div", {
      className: "blk-num"
    }, i + 1), /*#__PURE__*/React.createElement("div", {
      className: "blk-sn"
    }, b.seriale_label), (b.stato_superficie || []).map(function (s) {
      return /*#__PURE__*/React.createElement("span", {
        key: s,
        className: "pill pill-sup"
      }, s);
    }), /*#__PURE__*/React.createElement("span", {
      className: "blk-meta"
    }, "Fase ", b.fase)), /*#__PURE__*/React.createElement("ol", {
      className: "riep-list"
    }, b.anomalie.map(function (a, j) {
      return /*#__PURE__*/React.createElement("li", {
        key: a.local_id
      }, /*#__PURE__*/React.createElement("span", {
        className: "blk-item__n"
      }, j + 1), /*#__PURE__*/React.createElement("span", {
        className: "riep-list__txt"
      }, a.testo), /*#__PURE__*/React.createElement("span", {
        className: "riep-list__side"
      }, a.tutti === false && /*#__PURE__*/React.createElement("span", {
        className: "pill pill-parz",
        title: "Solo sui S/N: ".concat(a.seriale_label)
      }, "Solo ", a.seriale_label), /*#__PURE__*/React.createElement("span", {
        className: "blk-meta"
      }, "#", a.local_id), (a.allegati || []).length > 0 && /*#__PURE__*/React.createElement("span", {
        className: "blk-item__att"
      }, "\uD83D\uDCCE ", a.allegati.length), /*#__PURE__*/React.createElement(StatoPill, {
        a: a
      })));
    })));
  }));
};

/* Blocco copiato da un altro OP -> editor: stessi S/N, stato superficie e testi. */
var editorDaClona = function editorDaClona(b) {
  return _objectSpread(_objectSpread({}, newEditor()), {}, {
    voci: _toConsumableArray(b.seriali || []),
    stati: (b.stato_superficie || []).filter(function (st) {
      return STATI_SUPERFICIE.includes(st);
    }),
    anomalie: (b.anomalie || []).map(function (a) {
      return _objectSpread(_objectSpread({}, newAnomalia()), {}, {
        testo: a.testo || '',
        tutti: a.tutti !== false,
        sel: a.tutti === false ? tokensOf(a.seriali || []) : [],
        origineId: a.origine_id,
        allegatiOrigine: a.allegati || 0,
        copiaAllegati: false,
        dett: dettDaServer(a.dettaglio, a.tipo_difetto_id)
      });
    }),
    attiva: -1,
    daClona: true
  });
};
var editorCorrenteBlocco = function editorCorrenteBlocco(ed) {
  return {
    seriali: ed.voci,
    stato_superficie: ed.stati,
    anomalie: ed.anomalie.filter(function (a) {
      return a.testo.trim() || a.origineId;
    }).map(function (a) {
      return {
        origine_id: a.origineId,
        testo: a.testo,
        tutti: a.tutti,
        seriali: a.sel,
        allegati: a.allegatiOrigine || 0,
        dettaglio: dettPayload(a.dett),
        tipo_difetto_id: a.dett ? a.dett.tipoDifettoId : null
      };
    })
  };
};

/* Controlli aperti con qualcosa in sospeso: i propri e, per il gruppo qualità
   (Controllo qualità / Qualità), quelli dei colleghi. Un controllo lungo iniziato a
   fine turno lo prosegue il collega dopo con «Prendi in carico». */
var ControlliSospesi = function ControlliSospesi() {
  var _useState61 = useState([]),
    _useState62 = _slicedToArray(_useState61, 2),
    righe = _useState62[0],
    setRighe = _useState62[1];
  var _useState63 = useState(false),
    _useState64 = _slicedToArray(_useState63, 2),
    gruppo = _useState64[0],
    setGruppo = _useState64[1];
  useEffect(function () {
    getJson(API.controlli_sospesi, 'Controlli in sospeso').then(function (j) {
      setRighe(j.controlli || []);
      setGruppo(!!j.gruppo);
    })["catch"](function () {});
  }, []);
  if (!righe.length) return null;
  var quando = function quando(iso) {
    return iso ? new Date(iso).toLocaleString('it-IT', {
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit'
    }) : '';
  };
  var cosa = function cosa(r) {
    return [r.anomalie_in_bozza ? "".concat(r.anomalie_in_bozza, " anomali").concat(r.anomalie_in_bozza === 1 ? 'a' : 'e', " scritt").concat(r.anomalie_in_bozza === 1 ? 'a' : 'e', " da salvare") : '', r.blocchi_da_copiare ? "".concat(r.blocchi_da_copiare, " blocch").concat(r.blocchi_da_copiare === 1 ? 'o' : 'i', " da copiare") : '', r.da_notificare ? "".concat(r.da_notificare, " anomali").concat(r.da_notificare === 1 ? 'a' : 'e', " non ancora comunicat").concat(r.da_notificare === 1 ? 'a' : 'e') : ''].filter(Boolean).join(' · ') || 'blocco in scrittura';
  };
  return /*#__PURE__*/React.createElement("div", {
    className: "step-card sospesi-card"
  }, /*#__PURE__*/React.createElement("div", {
    className: "resume-box"
  }, /*#__PURE__*/React.createElement("div", {
    className: "field-label"
  }, gruppo ? 'Controlli in sospeso del gruppo qualità' : 'I tuoi controlli in sospeso'), gruppo && /*#__PURE__*/React.createElement("div", {
    className: "field-hint"
  }, "Li vedono tutti i colleghi con ruolo Controllo qualit\xE0 o Qualit\xE0: chi riprende il controllo di un altro lo prende in carico e lo porta a termine."), righe.map(function (r) {
    return /*#__PURE__*/React.createElement("div", {
      key: r.id,
      className: "resume-row"
    }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("strong", null, "OP ", r.op_id), r.op_nuovo ? ' (nuovo, non ancora creato)' : '', " \xB7 fase ", r.fase, /*#__PURE__*/React.createElement("div", {
      className: "sospesi-meta"
    }, /*#__PURE__*/React.createElement("span", {
      className: "sospesi-chi"
    }, r.mio ? 'Tuo' : r.operatore), " \xB7 ", cosa(r), " \xB7 ultimo aggiornamento ", quando(r.ultimo_at), r.passaggi && r.passaggi.length > 0 && " \xB7 iniziato da ".concat(r.passaggi[0].da))), /*#__PURE__*/React.createElement("a", {
      className: "btn-outline",
      href: "".concat(window.location.pathname, "?controllo=").concat(r.id)
    }, r.mio ? 'Riprendi' : 'Apri'));
  })));
};
var Step2Controllo = function Step2Controllo(_ref37) {
  var op = _ref37.op,
    onBack = _ref37.onBack,
    onDone = _ref37.onDone,
    clona = _ref37.clona,
    onOpCreato = _ref37.onOpCreato,
    riprendiId = _ref37.riprendiId,
    onCambiaOp = _ref37.onCambiaOp;
  // OP nuovo non ancora creato: nasce con il primo «Salva blocco»; uscendo prima non resta niente.
  var opRef = useRef(op);
  var daCreare = !!op.daCreare;
  var _useState65 = useState(true),
    _useState66 = _slicedToArray(_useState65, 2),
    loading = _useState66[0],
    setLoading = _useState66[1];
  var _useState67 = useState(null),
    _useState68 = _slicedToArray(_useState67, 2),
    controllo = _useState68[0],
    setControllo = _useState68[1];
  var _useState69 = useState([]),
    _useState70 = _slicedToArray(_useState69, 2),
    riprendibili = _useState70[0],
    setRiprendibili = _useState70[1];
  // Controllo di un collega del gruppo qualità aperto in lettura: si prosegue solo
  // dopo «Prendi in carico» (mai in automatico: il link del promemoria non lo ruba).
  var _useState71 = useState(null),
    _useState72 = _slicedToArray(_useState71, 2),
    daPrendere = _useState72[0],
    setDaPrendere = _useState72[1];
  var _useState73 = useState([]),
    _useState74 = _slicedToArray(_useState73, 2),
    fasiNote = _useState74[0],
    setFasiNote = _useState74[1];
  var _useState75 = useState(clona ? clona.fase || '' : ''),
    _useState76 = _slicedToArray(_useState75, 2),
    fase = _useState76[0],
    setFase = _useState76[1];
  // Blocchi copiati non ancora caricati nell'editor (in ordine).
  var _useState77 = useState(clona ? clona.blocchi : []),
    _useState78 = _slicedToArray(_useState77, 2),
    coda = _useState78[0],
    setCoda = _useState78[1];
  var editorDopo = function editorDopo(codaAttuale) {
    if (!codaAttuale.length) return newEditor();
    setCoda(codaAttuale.slice(1));
    return editorDaClona(codaAttuale[0]);
  };
  var _useState79 = useState(false),
    _useState80 = _slicedToArray(_useState79, 2),
    editingFase = _useState80[0],
    setEditingFase = _useState80[1];
  var _useState81 = useState(newEditor()),
    _useState82 = _slicedToArray(_useState81, 2),
    editor = _useState82[0],
    setEditor = _useState82[1];
  var _useState83 = useState(false),
    _useState84 = _slicedToArray(_useState83, 2),
    saving = _useState84[0],
    setSaving = _useState84[1];
  // Cambio OP dalla barra in alto: null | { busy, err }.
  var _useState85 = useState(null),
    _useState86 = _slicedToArray(_useState85, 2),
    cambioOp = _useState86[0],
    setCambioOp = _useState86[1];
  var _useState87 = useState(''),
    _useState88 = _slicedToArray(_useState87, 2),
    error = _useState88[0],
    setError = _useState88[1];
  var _useState89 = useState(''),
    _useState90 = _slicedToArray(_useState89, 2),
    notice = _useState90[0],
    setNotice = _useState90[1];
  var _useState91 = useState(''),
    _useState92 = _slicedToArray(_useState91, 2),
    attachErr = _useState92[0],
    setAttachErr = _useState92[1];
  var _useState93 = useState(false),
    _useState94 = _slicedToArray(_useState93, 2),
    confirmTermina = _useState94[0],
    setConfirmTermina = _useState94[1];
  var _useState95 = useState(null),
    _useState96 = _slicedToArray(_useState95, 2),
    esito = _useState96[0],
    setEsito = _useState96[1];
  var _useState97 = useState(false),
    _useState98 = _slicedToArray(_useState97, 2),
    riepilogo = _useState98[0],
    setRiepilogo = _useState98[1];
  var _useState99 = useState(null),
    _useState100 = _slicedToArray(_useState99, 2),
    destinatari = _useState100[0],
    setDestinatari = _useState100[1];
  var _useState101 = useState([]),
    _useState102 = _slicedToArray(_useState101, 2),
    extraAvvio = _useState102[0],
    setExtraAvvio = _useState102[1];
  var _useState103 = useState(''),
    _useState104 = _slicedToArray(_useState103, 2),
    bozzaAt = _useState104[0],
    setBozzaAt = _useState104[1];
  var bozzaRef = useRef({
    salvata: false,
    pending: null
  });
  var _useState105 = useState(null),
    _useState106 = _slicedToArray(_useState105, 2),
    confirmRipetuti = _useState106[0],
    setConfirmRipetuti = _useState106[1];
  var _useState107 = useState({
      seriali: [],
      dettagli: {}
    }),
    _useState108 = _slicedToArray(_useState107, 2),
    serialiAperti = _useState108[0],
    setSerialiAperti = _useState108[1];
  var _useState109 = useState({
      key: '',
      loading: false,
      sug: null,
      err: ''
    }),
    _useState110 = _slicedToArray(_useState109, 2),
    copilot = _useState110[0],
    setCopilot = _useState110[1];
  var snRef = useRef(null);
  // Selezione dei S/N di un'anomalia trascinando sui chip: { anomalia, mode, last }.
  var snDragRef = useRef(null);
  useEffect(function () {
    var fine = function fine() {
      snDragRef.current = null;
    };
    window.addEventListener('pointerup', fine);
    window.addEventListener('pointercancel', fine);
    return function () {
      window.removeEventListener('pointerup', fine);
      window.removeEventListener('pointercancel', fine);
    };
  }, []);
  var impostaSeriali = function impostaSeriali(i, lista, accendi) {
    return setEditor(function (prev) {
      return _objectSpread(_objectSpread({}, prev), {}, {
        anomalie: prev.anomalie.map(function (x, idx) {
          if (idx !== i) return x;
          var chiavi = new Set(lista.map(function (t) {
            return t.toLowerCase();
          }));
          var resto = x.sel.filter(function (s) {
            return !chiavi.has(s.toLowerCase());
          });
          return _objectSpread(_objectSpread({}, x), {}, {
            sel: accendi ? [].concat(_toConsumableArray(resto), _toConsumableArray(lista)) : resto
          });
        })
      });
    });
  };
  var isBenestare = String(op.stato || '').toLowerCase().includes('benestare');
  var loadSerialiAperti = function loadSerialiAperti() {
    if (!op || !op.id || opRef.current.daCreare) return;
    fetch("".concat(API.seriali_op, "?op_id=").concat(encodeURIComponent(op.id)), {
      credentials: 'same-origin'
    }).then(function (r) {
      return r.ok ? r.json() : {
        seriali: [],
        dettagli: {}
      };
    }).then(function (d) {
      return setSerialiAperti({
        seriali: Array.isArray(d.seriali) ? d.seriali : [],
        dettagli: d.dettagli || {}
      });
    })["catch"](function () {});
  };
  useEffect(function () {
    if (riprendiId) riprendi({
      id: riprendiId
    });
    if (opRef.current.daCreare) {
      // OP non ancora creato: destinatari dai nomi scritti, e i controlli lasciati in
      // bozza sullo stesso OP nuovo (per «Riprendi»).
      var benestare = !!opRef.current.daCreare.collaudo_benestare;
      setDestinatari({
        to: benestare ? op.car : op.capo,
        cc: benestare ? op.capo : op.car
      });
      var vivo = true;
      getJson("".concat(API.controlli, "?op_id=").concat(encodeURIComponent(op.id)), 'Controlli in corso').then(function (j) {
        return vivo && setRiprendibili(j.controlli || []);
      })["catch"](function () {})["finally"](function () {
        return vivo && setLoading(false);
      });
      return function () {
        vivo = false;
      };
    }
    var alive = true;
    getJson("".concat(API.controlli, "?op_id=").concat(encodeURIComponent(op.id)), 'Controlli in corso').then(function (j) {
      if (!alive) return;
      setRiprendibili(j.controlli || []);
      setFasiNote(j.fasi || []);
    })["catch"](function (e) {
      return alive && setError(e.message);
    })["finally"](function () {
      return alive && setLoading(false);
    });
    getJson("".concat(API.controllo_destinatari, "?op_id=").concat(encodeURIComponent(op.id)), 'Destinatari mail').then(function (j) {
      return alive && setDestinatari(j.destinatari || {
        to: '',
        cc: ''
      });
    })["catch"](function () {
      return alive && setDestinatari({
        to: '',
        cc: ''
      });
    });
    loadSerialiAperti();
    return function () {
      alive = false;
    };
  }, [op.id]);

  // Avviso se si chiude la pagina con un blocco non salvato o una mail «a fine controllo» in sospeso.
  useEffect(function () {
    var handler = function handler(e) {
      var pendingMail = controllo && controllo.mail_mode === 'fine' && controllo.da_notificare > 0 && !controllo.terminato;
      if (editorDirty(editor) || pendingMail) {
        e.preventDefault();
        e.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', handler);
    return function () {
      return window.removeEventListener('beforeunload', handler);
    };
  }, [editor, controllo]);
  var addFiles = function addFiles(index, rawFiles, fromClipboard) {
    var named = fromClipboard ? nameClipboardFiles(rawFiles) : rawFiles;
    var _validateFiles = validateFiles(named),
      ok = _validateFiles.ok,
      errors = _validateFiles.errors;
    setAttachErr(errors.join(' · '));
    if (!ok.length) return;
    setEditor(function (prev) {
      // Incolla senza un'anomalia aperta: va all'ultima ancora modificabile.
      var idx = index === null ? prev.attiva : index;
      if (idx < 0) idx = prev.anomalie.map(function (a) {
        return !a.gestita;
      }).lastIndexOf(true);
      if (idx < 0 || !prev.anomalie[idx] || prev.anomalie[idx].gestita) return prev;
      return _objectSpread(_objectSpread({}, prev), {}, {
        attiva: idx,
        anomalie: prev.anomalie.map(function (a, i) {
          if (i !== idx) return a;
          var next = _toConsumableArray(a.files);
          ok.forEach(function (f) {
            if (!next.some(function (x) {
              return x.name === f.name && x.size === f.size && x.lastModified === f.lastModified;
            })) next.push(f);
          });
          return _objectSpread(_objectSpread({}, a), {}, {
            files: next
          });
        })
      });
    });
  };

  // Ctrl+V di immagini (screenshot, foto copiate) ovunque nella pagina: va all'anomalia aperta.
  useEffect(function () {
    if (!controllo) return undefined;
    var onPaste = function onPaste(e) {
      if (e.defaultPrevented) return; // già gestito (es. riquadro «Incolla dal report»)
      var items = Array.from(e.clipboardData && e.clipboardData.items || []);
      var files = items.filter(function (it) {
        return it.kind === 'file';
      }).map(function (it) {
        return it.getAsFile();
      }).filter(Boolean);
      if (!files.length) return;
      // Testo copiato da Word/Outlook porta con sé anche un'immagine: in un campo di
      // testo vince il testo.
      var inText = e.target && /^(TEXTAREA|INPUT)$/.test(e.target.tagName);
      if (inText && items.some(function (it) {
        return it.kind === 'string' && it.type === 'text/plain';
      })) return;
      e.preventDefault();
      addFiles(null, files, true);
    };
    document.addEventListener('paste', onPaste);
    return function () {
      return document.removeEventListener('paste', onPaste);
    };
  }, [controllo]);
  var apriControllo = /*#__PURE__*/function () {
    var _ref38 = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee9() {
      var j, _t6;
      return _regenerator().w(function (_context9) {
        while (1) switch (_context9.p = _context9.n) {
          case 0:
            if (fase.trim()) {
              _context9.n = 1;
              break;
            }
            setError('Indica la fase del controllo.');
            return _context9.a(2);
          case 1:
            setError('');
            setSaving(true);
            _context9.p = 2;
            _context9.n = 3;
            return postJson(API.controllo_apri, opRef.current.daCreare ? {
              op_id: op.id,
              op_nuovo: opRef.current.daCreare,
              fase: fase.trim(),
              mail_mode: 'fine',
              destinatari_extra: extraAvvio
            } : {
              op_id: op.id,
              op_item_id: op.item_id,
              fase: fase.trim(),
              mail_mode: 'fine',
              destinatari_extra: extraAvvio
            }, 'Avvio controllo');
          case 3:
            j = _context9.v;
            setControllo(j.controllo);
            setEditor(editorDopo(coda));
            if (coda.length) setNotice("Caricato il primo dei ".concat(coda.length, " blocchi copiati: controlla S/N e testi, poi \xABSalva blocco\xBB."));
            setTimeout(function () {
              return snRef.current && snRef.current.focus();
            }, 50);
            _context9.n = 5;
            break;
          case 4:
            _context9.p = 4;
            _t6 = _context9.v;
            setError(_t6.message);
          case 5:
            _context9.p = 5;
            setSaving(false);
            return _context9.f(5);
          case 6:
            return _context9.a(2);
        }
      }, _callee9, null, [[2, 4, 5, 6]]);
    }));
    return function apriControllo() {
      return _ref38.apply(this, arguments);
    };
  }();
  var riprendi = /*#__PURE__*/function () {
    var _ref39 = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee0(c) {
      var j, _t7;
      return _regenerator().w(function (_context0) {
        while (1) switch (_context0.p = _context0.n) {
          case 0:
            setSaving(true);
            setError('');
            _context0.p = 1;
            _context0.n = 2;
            return getJson(urlFor(API.controllo_dettaglio, c.id), 'Ripresa controllo');
          case 2:
            j = _context0.v;
            if (!(j.mio === false)) {
              _context0.n = 3;
              break;
            }
            setDaPrendere(j.controllo);
            return _context0.a(2);
          case 3:
            applicaRipresa(j);
            _context0.n = 5;
            break;
          case 4:
            _context0.p = 4;
            _t7 = _context0.v;
            setError(_t7.message);
          case 5:
            _context0.p = 5;
            setSaving(false);
            return _context0.f(5);
          case 6:
            return _context0.a(2);
        }
      }, _callee0, null, [[1, 4, 5, 6]]);
    }));
    return function riprendi(_x10) {
      return _ref39.apply(this, arguments);
    };
  }();
  var prendiInCarico = /*#__PURE__*/function () {
    var _ref40 = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee1() {
      var j, _t8;
      return _regenerator().w(function (_context1) {
        while (1) switch (_context1.p = _context1.n) {
          case 0:
            if (daPrendere) {
              _context1.n = 1;
              break;
            }
            return _context1.a(2);
          case 1:
            setSaving(true);
            setError('');
            _context1.p = 2;
            _context1.n = 3;
            return postJson(urlFor(API.controllo_prendi, daPrendere.id), {}, 'Presa in carico');
          case 3:
            j = _context1.v;
            setDaPrendere(null);
            applicaRipresa(j);
            setNotice(function (prev) {
              return "Hai preso in carico il controllo di ".concat(daPrendere.operatore, ": da qui in avanti \xE8 tuo. ").concat(prev || '').trim();
            });
            _context1.n = 5;
            break;
          case 4:
            _context1.p = 4;
            _t8 = _context1.v;
            setError(_t8.message);
          case 5:
            _context1.p = 5;
            setSaving(false);
            return _context1.f(5);
          case 6:
            return _context1.a(2);
        }
      }, _callee1, null, [[2, 4, 5, 6]]);
    }));
    return function prendiInCarico() {
      return _ref40.apply(this, arguments);
    };
  }();
  var applicaRipresa = function applicaRipresa(j) {
    {
      setControllo(j.controllo);
      setDestinatari(j.destinatari || null);
      setFase(j.controllo.fase);
      var bz = j.controllo.bozza;
      // Blocchi copiati ancora da caricare: tornano in coda come erano.
      var codaBozza = bz && Array.isArray(bz.coda) ? bz.coda : null;
      if (codaBozza) setCoda(codaBozza);
      if (bozzaPiena(bz)) {
        setEditor(editorDaBozza(bz, j.controllo.blocchi));
        bozzaRef.current.salvata = true;
        setBozzaAt(j.controllo.bozza_at || '');
        var allegati = (bz.anomalie || []).reduce(function (n, a) {
          return n + (a.allegati || 0);
        }, 0);
        setNotice('Ripristinato il blocco in scrittura (salvato in automatico).' + (allegati ? " Gli allegati non si salvano in bozza: ricarica ".concat(allegati === 1 ? 'il file' : "i ".concat(allegati, " file"), ".") : ''));
      } else {
        setEditor(editorDopo(codaBozza || coda));
        if (codaBozza && codaBozza.length) setNotice("Ripresi i blocchi copiati: ".concat(codaBozza.length === 1 ? 'ne resta 1' : "ne restano ".concat(codaBozza.length), " da caricare."));
      }
    }
  };

  // Salvataggio automatico del blocco in scrittura: 1,5 s dopo l'ultima modifica.
  // Un blocco vuoto cancella la bozza; il salvataggio del blocco la svuota lato server.
  var inviaBozza = function inviaBozza(body, keepalive) {
    return fetch(urlFor(API.controllo_bozza, controllo.id), {
      method: 'POST',
      credentials: 'same-origin',
      keepalive: !!keepalive,
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrf()
      },
      body: JSON.stringify(body)
    });
  };
  useEffect(function () {
    if (!controllo || !controllo.id || controllo.terminato || riepilogo || saving) return undefined;
    var dirty = editorDirty(editor) || coda.length > 0;
    if (!dirty && !bozzaRef.current.salvata) {
      bozzaRef.current.pending = null;
      return undefined;
    }
    var body = {
      bozza: dirty ? _objectSpread(_objectSpread({}, editorDirty(editor) ? bozzaDa(editor) : {}), coda.length ? {
        coda: coda
      } : {}) : {}
    };
    bozzaRef.current.pending = body;
    var t = setTimeout(function () {
      inviaBozza(body).then(function (r) {
        return r.ok ? r.json() : null;
      }).then(function (j) {
        if (!j) return;
        bozzaRef.current.salvata = dirty;
        if (bozzaRef.current.pending === body) bozzaRef.current.pending = null;
        setBozzaAt(dirty ? j.bozza_at || '' : '');
      })["catch"](function () {});
    }, 1500);
    return function () {
      return clearTimeout(t);
    };
  }, [editor, coda, controllo && controllo.id, riepilogo, saving]);
  // Chiudendo la pagina prima dei 1,5 s parte comunque l'ultima bozza.
  useEffect(function () {
    if (!controllo) return undefined;
    var flush = function flush() {
      var b = bozzaRef.current.pending;
      if (b) {
        bozzaRef.current.pending = null;
        inviaBozza(b, true)["catch"](function () {});
      }
    };
    window.addEventListener('pagehide', flush);
    return function () {
      return window.removeEventListener('pagehide', flush);
    };
  }, [controllo && controllo.id]);
  var salvaImpostazioni = /*#__PURE__*/function () {
    var _ref41 = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee10(patch) {
      var j, _t9;
      return _regenerator().w(function (_context10) {
        while (1) switch (_context10.p = _context10.n) {
          case 0:
            setError('');
            _context10.p = 1;
            _context10.n = 2;
            return postJson(urlFor(API.controllo_impostazioni, controllo.id), patch, 'Impostazioni controllo');
          case 2:
            j = _context10.v;
            setControllo(function (prev) {
              return _objectSpread(_objectSpread({}, prev), {}, {
                fase: j.controllo.fase,
                mail_mode: j.controllo.mail_mode,
                destinatari_extra: j.controllo.destinatari_extra || []
              });
            });
            if (patch.fase) setEditingFase(false);
            _context10.n = 4;
            break;
          case 3:
            _context10.p = 3;
            _t9 = _context10.v;
            setError(_t9.message);
          case 4:
            return _context10.a(2);
        }
      }, _callee10, null, [[1, 3]]);
    }));
    return function salvaImpostazioni(_x11) {
      return _ref41.apply(this, arguments);
    };
  }();

  // Descrizione dell'anomalia aperta: i simboli finiscono qui se nessun altro campo ha il cursore.
  var testoRef = useRef(null);
  var updAnomalia = function updAnomalia(i, patch) {
    return setEditor(function (prev) {
      return _objectSpread(_objectSpread({}, prev), {}, {
        anomalie: prev.anomalie.map(function (a, idx) {
          return idx === i ? _objectSpread(_objectSpread({}, a), patch) : a;
        })
      });
    });
  };
  var nuovaAnomalia = function nuovaAnomalia() {
    return setEditor(function (prev) {
      // L'ultima anomalia vuota si riusa invece di aggiungerne un'altra.
      var last = prev.anomalie[prev.anomalie.length - 1];
      if (last && !last.localId && !last.testo.trim() && !last.files.length) return _objectSpread(_objectSpread({}, prev), {}, {
        attiva: prev.anomalie.length - 1
      });
      return _objectSpread(_objectSpread({}, prev), {}, {
        anomalie: [].concat(_toConsumableArray(prev.anomalie), [newAnomalia()]),
        attiva: prev.anomalie.length
      });
    });
  };

  // Elimina / Taglia su un'anomalia già salvata: {key, tipo: 'elimina'|'taglia', busy, err}.
  var _useState111 = useState(null),
    _useState112 = _slicedToArray(_useState111, 2),
    azAnom = _useState112[0],
    setAzAnom = _useState112[1];
  var puoAgireSu = function puoAgireSu(a) {
    return !!(a.localId && !a.gestita && a.modificabile && window._AP_ME && a.autoreId === window._AP_ME);
  };
  var dopoAzioneAnom = /*#__PURE__*/function () {
    var _ref42 = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee11(a, messaggio) {
      var fresh, fb;
      return _regenerator().w(function (_context11) {
        while (1) switch (_context11.n) {
          case 0:
            _context11.n = 1;
            return getJson(urlFor(API.controllo_dettaglio, controllo.id), 'Aggiornamento controllo');
          case 1:
            fresh = _context11.v;
            setControllo(fresh.controllo);
            fb = (fresh.controllo.blocchi || []).find(function (b) {
              return b.id === editor.bloccoId;
            });
            setEditor(function (prev) {
              if (!fb) return newEditor();
              var fa = (fb.anomalie || []).find(function (x) {
                return x.local_id === a.localId;
              });
              var anomalie = fa ? prev.anomalie.map(function (x) {
                return x.key === a.key ? _objectSpread(_objectSpread({}, x), {}, {
                  tutti: fa.tutti !== false,
                  sel: fa.tutti === false ? tokensOf(fa.seriali) : []
                }) : x;
              }) : prev.anomalie.filter(function (x) {
                return x.key !== a.key;
              });
              return _objectSpread(_objectSpread({}, prev), {}, {
                anomalie: anomalie.length ? anomalie : [newAnomalia()],
                attiva: -1
              });
            });
            setAzAnom(null);
            setNotice(messaggio);
          case 2:
            return _context11.a(2);
        }
      }, _callee11);
    }));
    return function dopoAzioneAnom(_x12, _x13) {
      return _ref42.apply(this, arguments);
    };
  }();
  var eliminaAnomalia = /*#__PURE__*/function () {
    var _ref43 = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee12(a) {
      var _t0;
      return _regenerator().w(function (_context12) {
        while (1) switch (_context12.p = _context12.n) {
          case 0:
            setAzAnom({
              key: a.key,
              tipo: 'elimina',
              busy: true,
              err: ''
            });
            _context12.p = 1;
            _context12.n = 2;
            return postJson(API.elimina, {
              local_id: a.localId
            }, 'Elimina anomalia');
          case 2:
            _context12.n = 3;
            return dopoAzioneAnom(a, "Anomalia #".concat(a.localId, " eliminata."));
          case 3:
            _context12.n = 5;
            break;
          case 4:
            _context12.p = 4;
            _t0 = _context12.v;
            setAzAnom({
              key: a.key,
              tipo: 'elimina',
              busy: false,
              err: _t0.message
            });
          case 5:
            return _context12.a(2);
        }
      }, _callee12, null, [[1, 4]]);
    }));
    return function eliminaAnomalia(_x14) {
      return _ref43.apply(this, arguments);
    };
  }();
  var tagliaFatta = /*#__PURE__*/function () {
    var _ref44 = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee13(a, j) {
      var _t1;
      return _regenerator().w(function (_context13) {
        while (1) switch (_context13.p = _context13.n) {
          case 0:
            _context13.p = 0;
            _context13.n = 1;
            return dopoAzioneAnom(a, "Anomalia #".concat(a.localId, ": ").concat(j.nota || 'spostata', "."));
          case 1:
            _context13.n = 3;
            break;
          case 2:
            _context13.p = 2;
            _t1 = _context13.v;
            setAzAnom(null);
            setError(_t1.message);
          case 3:
            return _context13.a(2);
        }
      }, _callee13, null, [[0, 2]]);
    }));
    return function tagliaFatta(_x15, _x16) {
      return _ref44.apply(this, arguments);
    };
  }();
  var rimuoviAnomalia = function rimuoviAnomalia(i) {
    return setEditor(function (prev) {
      var anomalie = prev.anomalie.filter(function (_, idx) {
        return idx !== i;
      });
      return _objectSpread(_objectSpread({}, prev), {}, {
        anomalie: anomalie.length ? anomalie : [newAnomalia()],
        attiva: Math.max(0, Math.min(prev.attiva, anomalie.length - 1))
      });
    });
  };
  var uploadFiles = /*#__PURE__*/function () {
    var _ref45 = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee14(localId, files) {
      var form, r, j;
      return _regenerator().w(function (_context14) {
        while (1) switch (_context14.n) {
          case 0:
            form = new FormData();
            form.append('local_id', String(localId));
            files.forEach(function (f) {
              return form.append('files', f);
            });
            _context14.n = 1;
            return fetch(API.allegati_upload, {
              method: 'POST',
              headers: {
                'X-CSRFToken': getCsrf()
              },
              body: form,
              credentials: 'same-origin'
            });
          case 1:
            r = _context14.v;
            _context14.n = 2;
            return parseJsonStrict(r, 'Caricamento allegati');
          case 2:
            j = _context14.v;
            if (!(Array.isArray(j.errors) && j.errors.length)) {
              _context14.n = 3;
              break;
            }
            throw new Error(j.errors.join(' · '));
          case 3:
            if (r.ok) {
              _context14.n = 4;
              break;
            }
            throw new Error(j.error || "Caricamento allegati: HTTP ".concat(r.status));
          case 4:
            return _context14.a(2);
        }
      }, _callee14);
    }));
    return function uploadFiles(_x17, _x18) {
      return _ref45.apply(this, arguments);
    };
  }();
  var opNuovoAperto = !!(controllo && controllo.op_nuovo && Object.keys(controllo.op_nuovo).length);
  var salvaBlocco = /*#__PURE__*/function () {
    var _ref46 = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee15() {
      var ed, anomalie, vuota, edTokens, selDi, parzialeVuota, scoperti, scopertiOk, opNuovo, cid, j, risultati, uploadErrors, i, res, _i, _res, byKey, fresh, n, restanti, _t10, _t11, _t12;
      return _regenerator().w(function (_context15) {
        while (1) switch (_context15.p = _context15.n) {
          case 0:
            ed = editor;
            anomalie = ed.anomalie.filter(function (a) {
              return a.localId || testoAnomalia(a) || a.files.length;
            });
            if (ed.voci.length) {
              _context15.n = 1;
              break;
            }
            setError('Inserisci almeno un seriale (premi Invio dopo averlo scritto).');
            snRef.current && snRef.current.focus();
            return _context15.a(2, false);
          case 1:
            if (anomalie.length) {
              _context15.n = 2;
              break;
            }
            setError('Descrivi almeno un’anomalia.');
            return _context15.a(2, false);
          case 2:
            if (!(STATI_SUPERFICIE.length && !ed.stati.length && !ed.bloccato)) {
              _context15.n = 3;
              break;
            }
            setError(MSG_SUP);
            return _context15.a(2, false);
          case 3:
            if (!(ripetutiEditor.length && !ed.confermaRipetuti)) {
              _context15.n = 4;
              break;
            }
            setError('');
            setConfirmRipetuti(ripetutiEditor.map(function (r) {
              return {
                seriale: r.token,
                blocco: r.blocco
              };
            }));
            return _context15.a(2, false);
          case 4:
            vuota = ed.anomalie.findIndex(function (a) {
              return (a.files.length || a.localId) && !testoAnomalia(a);
            });
            if (!(vuota >= 0)) {
              _context15.n = 5;
              break;
            }
            setError("L\u2019anomalia ".concat(vuota + 1, " ha allegati ma nessuna descrizione."));
            setEditor(function (prev) {
              return _objectSpread(_objectSpread({}, prev), {}, {
                attiva: vuota
              });
            });
            return _context15.a(2, false);
          case 5:
            edTokens = tokensOf(ed.voci);
            selDi = function selDi(a) {
              var k = new Set(a.sel.map(function (t) {
                return t.toLowerCase();
              }));
              return edTokens.filter(function (t) {
                return k.has(t.toLowerCase());
              });
            };
            parzialeVuota = ed.anomalie.findIndex(function (a) {
              return !a.gestita && (a.localId || a.testo.trim() || a.files.length) && !a.tutti && edTokens.length > 1 && !selDi(a).length;
            });
            if (!(parzialeVuota >= 0)) {
              _context15.n = 6;
              break;
            }
            setError("".concat(MSG_SN_ANOM, " (anomalia ").concat(parzialeVuota + 1, ")."));
            setEditor(function (prev) {
              return _objectSpread(_objectSpread({}, prev), {}, {
                attiva: parzialeVuota
              });
            });
            return _context15.a(2, false);
          case 6:
            scoperti = serialiScoperti(edTokens, ed.anomalie);
            scopertiOk = !scoperti.length || ed.confermaScoperti === scoperti.join('|');
            if (scopertiOk) {
              _context15.n = 7;
              break;
            }
            setError('');
            setConfirmScoperti(scoperti);
            return _context15.a(2, false);
          case 7:
            setError('');
            setNotice('');
            setSaving(true);
            _context15.p = 8;
            opNuovo = opNuovoAperto;
            cid = controllo.id;
            _context15.n = 9;
            return postJson(urlFor(API.controllo_blocco, cid), _objectSpread(_objectSpread({
              blocco_id: ed.bloccoId,
              seriali: ed.voci,
              stato_superficie: ed.stati
            }, campoVisibile('dove_pezzi', {
              fase: controllo && controllo.fase
            }) ? {
              dove_pezzi: (ed.dovePezzi || '').trim()
            } : {}), {}, {
              conferma_seriali_ripetuti: !!ed.confermaRipetuti,
              conferma_seriali_scoperti: scoperti.length > 0 && scopertiOk,
              anomalie: anomalie.map(function (a) {
                var tutti = a.tutti || edTokens.length <= 1;
                return {
                  local_id: a.localId,
                  testo: testoAnomalia(a),
                  tutti: tutti,
                  seriali: tutti ? [] : selDi(a),
                  dettaglio: dettPayload(a.dett),
                  tipo_difetto_id: a.dett ? a.dett.tipoDifettoId : null
                };
              })
            }), 'Salvataggio blocco');
          case 9:
            j = _context15.v;
            // Primo blocco su un OP nuovo: il server ha creato l'OP.
            if (j.op_creato) {
              opRef.current = j.op_creato;
              if (onOpCreato) onOpCreato(j.op_creato);
            }
            risultati = j.risultati || [];
            uploadErrors = [];
            i = 0;
          case 10:
            if (!(i < anomalie.length)) {
              _context15.n = 15;
              break;
            }
            res = risultati[i];
            if (!(res && res.ok && res.local_id && anomalie[i].files.length)) {
              _context15.n = 14;
              break;
            }
            _context15.p = 11;
            _context15.n = 12;
            return uploadFiles(res.local_id, anomalie[i].files);
          case 12:
            _context15.n = 14;
            break;
          case 13:
            _context15.p = 13;
            _t10 = _context15.v;
            uploadErrors.push("anomalia ".concat(i + 1, ": ").concat(_t10.message));
          case 14:
            i += 1;
            _context15.n = 10;
            break;
          case 15:
            _i = 0;
          case 16:
            if (!(_i < anomalie.length)) {
              _context15.n = 21;
              break;
            }
            _res = risultati[_i];
            if (!(_res && _res.ok && _res.local_id && anomalie[_i].origineId && anomalie[_i].copiaAllegati)) {
              _context15.n = 20;
              break;
            }
            _context15.p = 17;
            _context15.n = 18;
            return postJson(API.allegati_copia, {
              da: anomalie[_i].origineId,
              a: _res.local_id
            }, 'Copia allegati');
          case 18:
            _context15.n = 20;
            break;
          case 19:
            _context15.p = 19;
            _t11 = _context15.v;
            uploadErrors.push("anomalia ".concat(_i + 1, ": ").concat(_t11.message));
          case 20:
            _i += 1;
            _context15.n = 16;
            break;
          case 21:
            if (j.success) {
              _context15.n = 22;
              break;
            }
            // Salvataggio parziale: le anomalie riuscite tengono il loro id, così un nuovo
            // tentativo le aggiorna invece di duplicarle.
            byKey = {};
            anomalie.forEach(function (a, i) {
              if (risultati[i] && risultati[i].ok) byKey[a.key] = risultati[i].local_id;
            });
            setEditor(function (prev) {
              return _objectSpread(_objectSpread({}, prev), {}, {
                bloccoId: j.blocco_id || prev.bloccoId,
                anomalie: prev.anomalie.map(function (a) {
                  return byKey[a.key] ? _objectSpread(_objectSpread({}, a), {}, {
                    localId: byKey[a.key],
                    files: []
                  }) : a;
                })
              });
            });
            setControllo(j.controllo);
            setError("Blocco salvato solo in parte: ".concat(j.error));
            return _context15.a(2, false);
          case 22:
            _context15.n = 23;
            return getJson(urlFor(API.controllo_dettaglio, cid), 'Aggiornamento controllo');
          case 23:
            fresh = _context15.v;
            setControllo(fresh.controllo);
            setDestinatari(fresh.destinatari || null);
            setEditor(ed.bloccoId === null ? editorDopo(coda) : newEditor());
            setConfirmRipetuti(null);
            setConfirmScoperti(null);
            loadSerialiAperti();
            n = anomalie.length;
            restanti = ed.bloccoId === null ? coda.length : 0;
            setNotice((opNuovo ? "Creato l\u2019OP ".concat(opRef.current.id, ". ") : '') + "Salvato: ".concat(n, " anomali").concat(n === 1 ? 'a' : 'e', " su ").concat(labelVoci(ed.voci), ".") + (ed.daClona ? restanti ? " Caricato il prossimo blocco copiato (".concat(restanti === 1 ? 'ne resta 1' : "ne restano ".concat(restanti), ").") : ' Copiati tutti i blocchi: controlla e premi «Termina controllo».' : '') + (uploadErrors.length ? " Attenzione, allegati non caricati (".concat(uploadErrors.join('; '), "): riapri il blocco con \xABModifica\xBB e riallegali.") : ''));
            setTimeout(function () {
              return snRef.current && snRef.current.focus();
            }, 50);
            return _context15.a(2, true);
          case 24:
            _context15.p = 24;
            _t12 = _context15.v;
            if (_t12.data && _t12.data.code === 'seriali_ripetuti') {
              setConfirmRipetuti(_t12.data.seriali_ripetuti || []);
              setError('');
            } else if (_t12.data && _t12.data.code === 'seriali_scoperti') {
              setConfirmScoperti(_t12.data.seriali_scoperti || []);
              setError('');
            } else setError(_t12.message);
            return _context15.a(2, false);
          case 25:
            _context15.p = 25;
            setSaving(false);
            return _context15.f(25);
          case 26:
            return _context15.a(2);
        }
      }, _callee15, null, [[17, 19], [11, 13], [8, 24, 25, 26]]);
    }));
    return function salvaBlocco() {
      return _ref46.apply(this, arguments);
    };
  }();

  // Stesso S/N in un altro blocco: ammesso (es. altra fase o altro stato superficie),
  // ma va confermato esplicitamente; poi si risalva con la conferma.
  var _useState113 = useState(false),
    _useState114 = _slicedToArray(_useState113, 2),
    salvaDopoConferma = _useState114[0],
    setSalvaDopoConferma = _useState114[1];
  var confermaESalva = function confermaESalva() {
    setEditor(function (prev) {
      return _objectSpread(_objectSpread({}, prev), {}, {
        confermaRipetuti: true
      });
    });
    setConfirmRipetuti(null);
    setSalvaDopoConferma(true);
  };
  useEffect(function () {
    if (salvaDopoConferma && editor.confermaRipetuti) {
      setSalvaDopoConferma(false);
      salvaBlocco();
    }
  }, [salvaDopoConferma, editor.confermaRipetuti]);

  // S/N del blocco senza nessuna anomalia: si salva solo dopo conferma, oppure
  // togliendoli dal blocco (non se il capocommessa ha già deciso: i seriali sono fermi).
  var _useState115 = useState(null),
    _useState116 = _slicedToArray(_useState115, 2),
    confirmScoperti = _useState116[0],
    setConfirmScoperti = _useState116[1];
  var _useState117 = useState(false),
    _useState118 = _slicedToArray(_useState117, 2),
    salvaDopoScoperti = _useState118[0],
    setSalvaDopoScoperti = _useState118[1];
  var confermaScopertiESalva = function confermaScopertiESalva() {
    var chiave = (confirmScoperti || []).join('|');
    setEditor(function (prev) {
      return _objectSpread(_objectSpread({}, prev), {}, {
        confermaScoperti: chiave
      });
    });
    setConfirmScoperti(null);
    setSalvaDopoScoperti(true);
  };
  var togliScopertiESalva = function togliScopertiESalva() {
    var via = new Set((confirmScoperti || []).map(function (t) {
      return t.toLowerCase();
    }));
    setEditor(function (prev) {
      return _objectSpread(_objectSpread({}, prev), {}, {
        voci: comprimiTokens(tokensOf(prev.voci).filter(function (t) {
          return !via.has(t.toLowerCase());
        })),
        confermaScoperti: ''
      });
    });
    setConfirmScoperti(null);
    setSalvaDopoScoperti(true);
  };
  useEffect(function () {
    if (salvaDopoScoperti) {
      setSalvaDopoScoperti(false);
      salvaBlocco();
    }
  }, [salvaDopoScoperti]);

  // «Termina controllo» passa sempre dal riepilogo: l'operatore vede tutto prima della mail.
  var apriRiepilogo = /*#__PURE__*/function () {
    var _ref47 = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee16(salvaPrima) {
      var fresh, _t13, _t14;
      return _regenerator().w(function (_context16) {
        while (1) switch (_context16.p = _context16.n) {
          case 0:
            _t13 = salvaPrima;
            if (!_t13) {
              _context16.n = 2;
              break;
            }
            _context16.n = 1;
            return salvaBlocco();
          case 1:
            _t13 = !_context16.v;
          case 2:
            if (!_t13) {
              _context16.n = 3;
              break;
            }
            setConfirmTermina(false);
            return _context16.a(2);
          case 3:
            if (!(!salvaPrima && opNuovoAperto && !(controllo && controllo.blocchi || []).length)) {
              _context16.n = 4;
              break;
            }
            // Nessun blocco salvato su un OP nuovo: non c'è niente da comunicare né da creare.
            setConfirmTermina(false);
            setEditor(newEditor());
            setNotice('Blocco scartato: l’OP non è stato creato.');
            return _context16.a(2);
          case 4:
            setConfirmTermina(false);
            setSaving(true);
            setError('');
            _context16.p = 5;
            _context16.n = 6;
            return getJson(urlFor(API.controllo_dettaglio, controllo.id), 'Riepilogo controllo');
          case 6:
            fresh = _context16.v;
            setControllo(fresh.controllo);
            setDestinatari(fresh.destinatari || null);
            setEditor(newEditor());
            setRiepilogo(true);
            window.scrollTo(0, 0);
            _context16.n = 8;
            break;
          case 7:
            _context16.p = 7;
            _t14 = _context16.v;
            setError(_t14.message);
          case 8:
            _context16.p = 8;
            setSaving(false);
            return _context16.f(8);
          case 9:
            return _context16.a(2);
        }
      }, _callee16, null, [[5, 7, 8, 9]]);
    }));
    return function apriRiepilogo(_x19) {
      return _ref47.apply(this, arguments);
    };
  }();
  var termina = /*#__PURE__*/function () {
    var _ref48 = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee17() {
      var j, _t15;
      return _regenerator().w(function (_context17) {
        while (1) switch (_context17.p = _context17.n) {
          case 0:
            setConfirmTermina(false);
            setSaving(true);
            setError('');
            _context17.p = 1;
            _context17.n = 2;
            return postJson(urlFor(API.controllo_termina, controllo.id), {}, 'Termina controllo');
          case 2:
            j = _context17.v;
            setControllo(j.controllo);
            setEditor(newEditor());
            setRiepilogo(false);
            setEsito(j.mail || {});
            _context17.n = 4;
            break;
          case 3:
            _context17.p = 3;
            _t15 = _context17.v;
            setError(_t15.message);
          case 4:
            _context17.p = 4;
            setSaving(false);
            return _context17.f(4);
          case 5:
            return _context17.a(2);
        }
      }, _callee17, null, [[1, 3, 4, 5]]);
    }));
    return function termina() {
      return _ref48.apply(this, arguments);
    };
  }();
  var proponiCopilota = /*#__PURE__*/function () {
    var _ref49 = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee18(a) {
      var r, d, _t16;
      return _regenerator().w(function (_context18) {
        while (1) switch (_context18.p = _context18.n) {
          case 0:
            if (a.testo.trim()) {
              _context18.n = 1;
              break;
            }
            setCopilot({
              key: a.key,
              loading: false,
              sug: null,
              err: 'Scrivi prima la descrizione.'
            });
            return _context18.a(2);
          case 1:
            setCopilot({
              key: a.key,
              loading: true,
              sug: null,
              err: ''
            });
            _context18.p = 2;
            _context18.n = 3;
            return fetch(API.copilota, {
              method: 'POST',
              credentials: 'same-origin',
              headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrf()
              },
              body: JSON.stringify({
                descrizione: a.testo
              })
            });
          case 3:
            r = _context18.v;
            _context18.n = 4;
            return parseJsonSafe(r, {});
          case 4:
            d = _context18.v;
            if (!r.ok || !d.success) setCopilot({
              key: a.key,
              loading: false,
              sug: null,
              err: d && d.error || 'Suggerimento non disponibile.'
            });else if (!d.proposta || !d.proposta.ai_disponibile) setCopilot({
              key: a.key,
              loading: false,
              sug: null,
              err: 'AI non disponibile al momento.'
            });else setCopilot({
              key: a.key,
              loading: false,
              sug: d.proposta,
              err: ''
            });
            _context18.n = 6;
            break;
          case 5:
            _context18.p = 5;
            _t16 = _context18.v;
            setCopilot({
              key: a.key,
              loading: false,
              sug: null,
              err: 'Errore di rete.'
            });
          case 6:
            return _context18.a(2);
        }
      }, _callee18, null, [[2, 5]]);
    }));
    return function proponiCopilota(_x20) {
      return _ref49.apply(this, arguments);
    };
  }();

  /* Avvisi sui seriali digitati: formato, prefisso diverso, anomalie già aperte. */
  // Token dei blocchi già salvati (escluso quello riaperto) → numero del blocco.
  var controlloTokens = React.useMemo(function () {
    var own = new Map();
    (controllo && controllo.blocchi || []).forEach(function (b, i) {
      if (b.id === editor.bloccoId) return;
      tokensOf(b.seriali).forEach(function (t) {
        if (!own.has(t.toLowerCase())) own.set(t.toLowerCase(), i + 1);
      });
    });
    return own;
  }, [controllo, editor.bloccoId]);
  var tokens = tokensOf(editor.voci);
  var fuoriFormato = tokens.filter(function (t) {
    return !SN_PATTERN.test(t);
  });
  var primo = tokens.find(function (t) {
    return SN_PATTERN.test(t);
  });
  var prefissoDiverso = primo ? tokens.filter(function (t) {
    return SN_PATTERN.test(t) && t.slice(0, 3).toUpperCase() !== primo.slice(0, 3).toUpperCase();
  }) : [];
  var ripetutiEditor = tokens.filter(function (t) {
    return controlloTokens.has(t.toLowerCase());
  }).map(function (t) {
    return {
      token: t,
      blocco: controlloTokens.get(t.toLowerCase())
    };
  });
  var scopertiEditor = serialiScoperti(tokens, editor.anomalie);
  var duplicati = function () {
    var exist = new Set((serialiAperti.seriali || []).map(function (x) {
      return x.toLowerCase();
    }));
    var out = [];
    tokens.forEach(function (t) {
      var k = t.toLowerCase();
      if (!exist.has(k) || controlloTokens.has(k)) return;
      var info = serialiAperti.dettagli[k] || {};
      out.push(_objectSpread({
        token: t
      }, info));
    });
    return out.slice(0, 6);
  }();
  var blocchi = controllo && controllo.blocchi || [];
  var dirty = editorDirty(editor);
  var nPezzi = function () {
    var set = new Set();
    blocchi.forEach(function (b) {
      return tokensOf(b.seriali).forEach(function (t) {
        return set.add(t.toLowerCase());
      });
    });
    return set.size;
  }();
  var nAnomalie = blocchi.reduce(function (n, b) {
    return n + b.anomalie.length;
  }, 0);
  if (loading) return /*#__PURE__*/React.createElement("div", {
    className: "step-card"
  }, /*#__PURE__*/React.createElement("div", {
    className: "loading-msg"
  }, "Caricamento\u2026"));
  var cambiaOp = /*#__PURE__*/function () {
    var _ref50 = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee19(nuovo) {
      var b, _t17;
      return _regenerator().w(function (_context19) {
        while (1) switch (_context19.p = _context19.n) {
          case 0:
            if (!(!nuovo || !onCambiaOp)) {
              _context19.n = 1;
              break;
            }
            return _context19.a(2);
          case 1:
            if (!(!controllo || !controllo.id)) {
              _context19.n = 2;
              break;
            }
            onCambiaOp(nuovo, null);
            return _context19.a(2);
          case 2:
            setCambioOp({
              busy: true,
              err: ''
            });
            _context19.p = 3;
            // L'ultima bozza va sul server prima: il controllo si riapre sul nuovo OP.
            b = bozzaRef.current.pending;
            if (!b) {
              _context19.n = 4;
              break;
            }
            bozzaRef.current.pending = null;
            _context19.n = 4;
            return inviaBozza(b);
          case 4:
            _context19.n = 5;
            return postJson(urlFor(API.controllo_cambia_op, controllo.id), {
              op_id: nuovo.id,
              op_item_id: nuovo.item_id
            }, 'Cambio OP');
          case 5:
            onCambiaOp(nuovo, controllo.id);
            _context19.n = 7;
            break;
          case 6:
            _context19.p = 6;
            _t17 = _context19.v;
            setCambioOp({
              busy: false,
              err: _t17.message
            });
          case 7:
            return _context19.a(2);
        }
      }, _callee19, null, [[3, 6]]);
    }));
    return function cambiaOp(_x21) {
      return _ref50.apply(this, arguments);
    };
  }();
  var puoCambiareOp = !!onCambiaOp && !saving && !riepilogo && !(controllo && controllo.terminato);
  var apriCambioOp = function apriCambioOp() {
    if (puoCambiareOp) setCambioOp({
      busy: false,
      err: ''
    });
  };
  var titoloCambio = puoCambiareOp ? 'Clicca per cambiare OP / P/N' : '';
  var opBar = /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
    className: "op-info-bar"
  }, /*#__PURE__*/React.createElement("button", {
    className: "op-info-back",
    onClick: onBack,
    disabled: saving || dirty && !!controllo,
    title: dirty ? 'Salva o svuota il blocco in corso prima di cambiare OP' : ''
  }, "\u2190 Cambio OP"), /*#__PURE__*/React.createElement("div", {
    className: "op-info-items"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "op-info-chip",
    disabled: !puoCambiareOp,
    title: titoloCambio,
    onClick: apriCambioOp
  }, /*#__PURE__*/React.createElement("strong", null, op.id), puoCambiareOp && /*#__PURE__*/React.createElement("span", {
    className: "op-info-chip__edit"
  }, "\u270E")), daCreare && /*#__PURE__*/React.createElement("div", {
    className: "op-info-chip is-nuovo",
    title: "L\u2019OP si crea quando salvi il primo blocco: uscendo prima non resta niente"
  }, "Nuovo \xB7 si crea al primo salvataggio"), op.pn && op.pn !== '—' && /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "op-info-chip",
    disabled: !puoCambiareOp,
    title: titoloCambio,
    onClick: apriCambioOp
  }, /*#__PURE__*/React.createElement("strong", null, "P/N"), " ", op.pn, puoCambiareOp && /*#__PURE__*/React.createElement("span", {
    className: "op-info-chip__edit"
  }, "\u270E")), op.capo && op.capo !== '—' && /*#__PURE__*/React.createElement("div", {
    className: "op-info-chip"
  }, /*#__PURE__*/React.createElement("strong", null, "Capocommessa"), " ", op.capo), op.car && op.car !== '—' && /*#__PURE__*/React.createElement("div", {
    className: "op-info-chip"
  }, /*#__PURE__*/React.createElement("strong", null, "CAR"), " ", op.car), /*#__PURE__*/React.createElement("div", {
    className: "op-info-chip ".concat(isBenestare ? 'is-benestare' : '')
  }, isBenestare ? 'Collaudo di benestare' : 'Altro controllo'))), cambioOp && /*#__PURE__*/React.createElement(CambiaOpPanel, {
    opAttuale: op.id,
    nSalvate: nAnomalie,
    busy: cambioOp.busy,
    err: cambioOp.err,
    onScegli: cambiaOp,
    onCancel: function onCancel() {
      return setCambioOp(null);
    }
  }));

  /* Esito di fine controllo */
  if (esito) {
    return /*#__PURE__*/React.createElement("div", {
      className: "step-card"
    }, opBar, /*#__PURE__*/React.createElement("div", {
      className: "form-body"
    }, /*#__PURE__*/React.createElement("div", {
      className: "esito-card"
    }, /*#__PURE__*/React.createElement("div", {
      className: "esito-card__icon"
    }, "\u2713"), /*#__PURE__*/React.createElement("h2", null, "Controllo terminato"), /*#__PURE__*/React.createElement("p", null, blocchi.length, " blocch", blocchi.length === 1 ? 'o' : 'i', " di seriali, ", blocchi.reduce(function (n, b) {
      return n + b.anomalie.length;
    }, 0), " anomalie registrate sull\u2019OP ", op.id, "."), esito.sent && /*#__PURE__*/React.createElement("p", {
      className: "esito-ok"
    }, "Mail con il link di decisione inviata a ", /*#__PURE__*/React.createElement("strong", null, esito.to), [esito.cc].concat(_toConsumableArray(esito.extra || [])).filter(Boolean).length ? /*#__PURE__*/React.createElement(React.Fragment, null, " (in copia ", [esito.cc].concat(_toConsumableArray(esito.extra || [])).filter(Boolean).join(', '), ")") : null, "."), !esito.sent && esito.reason === 'nessuna_anomalia' && /*#__PURE__*/React.createElement("p", {
      className: "esito-muted"
    }, "Nessuna mail da inviare ora: le anomalie erano gi\xE0 state comunicate al capocommessa."), !esito.sent && esito.reason === 'errore' && /*#__PURE__*/React.createElement("p", {
      className: "error-msg"
    }, "Mail al capocommessa non inviata: ", esito.error, ". Il sistema riprover\xE0 in automatico.")), blocchi.length > 0 && /*#__PURE__*/React.createElement(RiepilogoControllo, {
      op: op,
      controllo: controllo,
      destinatari: destinatari
    }), /*#__PURE__*/React.createElement("div", {
      className: "esito-card no-print"
    }, /*#__PURE__*/React.createElement("div", {
      className: "action-bar"
    }, blocchi.length > 0 && /*#__PURE__*/React.createElement("button", {
      className: "btn-outline",
      onClick: function onClick() {
        return window.print();
      }
    }, "Stampa riepilogo"), /*#__PURE__*/React.createElement("button", {
      className: "btn-secondary",
      onClick: function onClick() {
        return onDone('menu');
      }
    }, "Torna al menu"), /*#__PURE__*/React.createElement("button", {
      className: "btn-outline",
      onClick: function onClick() {
        return onDone('altro_op');
      }
    }, "Controlla un altro OP"), /*#__PURE__*/React.createElement("button", {
      className: "btn-primary",
      onClick: function onClick() {
        return onDone('stesso_op');
      }
    }, "Nuovo controllo su questo OP")))));
  }

  /* Riepilogo prima di terminare: l'operatore controlla tutto e conferma */
  if (riepilogo && controllo) {
    return /*#__PURE__*/React.createElement("div", {
      className: "step-card step-card--wide"
    }, opBar, /*#__PURE__*/React.createElement("div", {
      className: "step-header"
    }, /*#__PURE__*/React.createElement("div", {
      className: "step-num"
    }, "\u2713"), /*#__PURE__*/React.createElement("h2", null, "Riepilogo del controllo")), /*#__PURE__*/React.createElement("div", {
      className: "form-body"
    }, /*#__PURE__*/React.createElement("div", {
      className: "field-hint"
    }, "Controlla blocchi, stato superficie e anomalie. Con \xABConferma e termina\xBB il controllo si chiude", controllo.da_notificare ? ' e parte la mail al capocommessa' : '', "."), blocchi.length === 0 && /*#__PURE__*/React.createElement("div", {
      className: "info-msg"
    }, "Nessun blocco salvato: il controllo si chiude senza anomalie."), /*#__PURE__*/React.createElement(RiepilogoControllo, {
      op: op,
      controllo: controllo,
      destinatari: destinatari,
      onChangeExtra: saving ? null : function (lista) {
        return salvaImpostazioni({
          destinatari_extra: lista
        });
      }
    }), error && /*#__PURE__*/React.createElement("div", {
      className: "error-msg"
    }, error), /*#__PURE__*/React.createElement("div", {
      className: "riep-actions"
    }, /*#__PURE__*/React.createElement("button", {
      className: "btn-secondary",
      onClick: function onClick() {
        return setRiepilogo(false);
      },
      disabled: saving
    }, "\u2190 Torna al controllo"), /*#__PURE__*/React.createElement("button", {
      className: "btn-primary",
      onClick: termina,
      disabled: saving
    }, saving ? 'Chiusura…' : 'Conferma e termina'))));
  }

  /* Avvio: fase + modalità mail, oppure ripresa di un controllo lasciato aperto */
  if (!controllo) {
    return /*#__PURE__*/React.createElement("div", {
      className: "step-card"
    }, opBar, /*#__PURE__*/React.createElement("div", {
      className: "step-header"
    }, /*#__PURE__*/React.createElement("div", {
      className: "step-num"
    }, "2"), /*#__PURE__*/React.createElement("h2", null, "Nuovo controllo")), /*#__PURE__*/React.createElement("div", {
      className: "form-body"
    }, clona && coda.length > 0 && /*#__PURE__*/React.createElement(ClonaBanner, {
      clona: clona
    }, "Conferma la fase", clona.fasi && clona.fasi.length > 1 ? " (sull\u2019OP di origine: ".concat(clona.fasi.join(', '), ")") : '', " e premi \xABInizia controllo\xBB: i blocchi copiati si caricano uno alla volta, pronti da salvare."), daPrendere && /*#__PURE__*/React.createElement("div", {
      className: "prendi-box",
      role: "alert"
    }, /*#__PURE__*/React.createElement("div", {
      className: "field-label"
    }, "Controllo in carico a ", daPrendere.operatore), /*#__PURE__*/React.createElement("div", null, "Fase ", daPrendere.fase, " \xB7 ", daPrendere.blocchi.length, " blocch", daPrendere.blocchi.length === 1 ? 'o' : 'i', " salvat", daPrendere.blocchi.length === 1 ? 'o' : 'i', bozzaPiena(daPrendere.bozza) ? " \xB7 ".concat((daPrendere.bozza.anomalie || []).length, " anomalie scritte da salvare") : '', daPrendere.da_notificare ? " \xB7 ".concat(daPrendere.da_notificare, " non ancora comunicate") : ''), /*#__PURE__*/React.createElement("div", {
      className: "field-hint"
    }, "Prendendolo in carico prosegui tu da dove \xE8 rimasto: blocco in scrittura, salvataggi, mail e \xABTermina controllo\xBB diventano tuoi. ", daPrendere.operatore, " riceve un avviso nel portale e il passaggio resta registrato."), /*#__PURE__*/React.createElement("div", {
      style: {
        display: 'flex',
        gap: 8,
        flexWrap: 'wrap'
      }
    }, /*#__PURE__*/React.createElement("button", {
      className: "btn-primary",
      onClick: prendiInCarico,
      disabled: saving
    }, saving ? 'Presa in carico…' : 'Prendi in carico e prosegui'), /*#__PURE__*/React.createElement("button", {
      className: "btn-secondary",
      onClick: function onClick() {
        return setDaPrendere(null);
      },
      disabled: saving
    }, "Annulla"))), riprendibili.length > 0 && /*#__PURE__*/React.createElement("div", {
      className: "resume-box"
    }, /*#__PURE__*/React.createElement("div", {
      className: "field-label"
    }, riprendibili.some(function (c) {
      return c.mio === false;
    }) ? 'Controlli ancora aperti su questo OP' : 'Hai un controllo ancora aperto su questo OP'), riprendibili.map(function (c) {
      return /*#__PURE__*/React.createElement("div", {
        key: c.id,
        className: "resume-row"
      }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("strong", null, "Fase ", c.fase), c.mio === false ? " \xB7 di ".concat(c.operatore) : '', " \xB7 ", new Date(c.created_at).toLocaleString('it-IT', {
        day: '2-digit',
        month: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
      }), /*#__PURE__*/React.createElement("div", {
        className: "field-hint"
      }, c.blocchi.length, " blocch", c.blocchi.length === 1 ? 'o' : 'i', " salvat", c.blocchi.length === 1 ? 'o' : 'i', c.da_notificare ? " \xB7 ".concat(c.da_notificare, " anomalie non ancora comunicate") : '')), /*#__PURE__*/React.createElement("button", {
        className: "btn-outline",
        onClick: function onClick() {
          return riprendi(c);
        },
        disabled: saving
      }, c.mio === false ? 'Prendi in carico' : 'Riprendi'));
    }), /*#__PURE__*/React.createElement("div", {
      className: "field-hint"
    }, "Riprendi quello aperto invece di aprirne un altro; per un controllo nuovo scrivi la fase qui sotto. I controlli rimasti vuoti si chiudono da soli dopo 24 ore.")), /*#__PURE__*/React.createElement("div", {
      className: "field-group"
    }, /*#__PURE__*/React.createElement("label", {
      className: "field-label",
      htmlFor: "controllo-fase"
    }, "Fase del controllo ", /*#__PURE__*/React.createElement("span", {
      className: "req"
    }, "*")), /*#__PURE__*/React.createElement("input", {
      id: "controllo-fase",
      className: "text-input",
      type: "text",
      list: "fasi-op",
      maxLength: 100,
      autoFocus: true,
      placeholder: "Es. accettazione materiale, lavorazione, collaudo finale\u2026",
      value: fase,
      onChange: function onChange(e) {
        return setFase(e.target.value);
      },
      onKeyDown: function onKeyDown(e) {
        if (e.key === 'Enter') apriControllo();
      }
    }), /*#__PURE__*/React.createElement("datalist", {
      id: "fasi-op"
    }, fasiNote.map(function (f) {
      return /*#__PURE__*/React.createElement("option", {
        key: f,
        value: f
      });
    })), /*#__PURE__*/React.createElement("div", {
      className: "field-hint"
    }, "Vale per tutti i blocchi che salverai; la puoi cambiare durante il controllo.")), /*#__PURE__*/React.createElement("div", {
      className: "field-group"
    }, /*#__PURE__*/React.createElement("span", {
      className: "field-label"
    }, "Mail al capocommessa: una sola, a fine controllo"), /*#__PURE__*/React.createElement(DestinatariMail, {
      destinatari: destinatari,
      extra: extraAvvio,
      onChange: setExtraAvvio,
      disabled: saving
    }), /*#__PURE__*/React.createElement("div", {
      className: "field-hint"
    }, MAIL_FINE_HINT, " Capocommessa e CAR arrivano dall\u2019OP; con \xABAggiungi altro capocommessa\xBB o \xABAggiungi persona\xBB metti in copia altri colleghi, che ricevono la stessa mail con il link di decisione.")), error && /*#__PURE__*/React.createElement("div", {
      className: "error-msg"
    }, error), /*#__PURE__*/React.createElement("div", {
      className: "action-bar"
    }, /*#__PURE__*/React.createElement("button", {
      className: "btn-secondary",
      onClick: function onClick() {
        return onDone('menu');
      },
      disabled: saving
    }, "Esci"), /*#__PURE__*/React.createElement("button", {
      className: "btn-primary",
      onClick: apriControllo,
      disabled: saving || !fase.trim()
    }, saving ? 'Avvio…' : 'Inizia controllo'))));
  }
  var editorCard = /*#__PURE__*/React.createElement("div", {
    className: "blk is-editing".concat(editor.bloccoId ? ' is-reopened' : ''),
    key: "editor"
  }, /*#__PURE__*/React.createElement("div", {
    className: "blk-head"
  }, /*#__PURE__*/React.createElement("div", {
    className: "blk-num is-active"
  }, editor.bloccoId ? blocchi.findIndex(function (b) {
    return b.id === editor.bloccoId;
  }) + 1 : blocchi.length + 1), /*#__PURE__*/React.createElement("div", {
    className: "blk-head__main"
  }, /*#__PURE__*/React.createElement("div", {
    className: "blk-title"
  }, editor.bloccoId ? 'Modifica blocco' : editor.daClona ? "Blocco copiato da ".concat(clona ? clona.op.id : 'altro OP') : 'Nuovo blocco di seriali'), /*#__PURE__*/React.createElement("div", {
    className: "blk-meta"
  }, "Fase ", controllo.fase, bozzaAt ? " \xB7 salvato in automatico alle ".concat(new Date(bozzaAt).toLocaleTimeString('it-IT', {
    hour: '2-digit',
    minute: '2-digit'
  })) : ''))), /*#__PURE__*/React.createElement("div", {
    className: "field-group"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label"
  }, "Seriali ", /*#__PURE__*/React.createElement("span", {
    className: "req"
  }, "*")), /*#__PURE__*/React.createElement(SerialInput, {
    voci: editor.voci,
    disabled: editor.bloccato,
    inputRef: snRef,
    onChange: function onChange(voci) {
      return setEditor(function (prev) {
        return _objectSpread(_objectSpread({}, prev), {}, {
          voci: voci
        });
      });
    }
  }), editor.bloccato ? /*#__PURE__*/React.createElement("div", {
    className: "field-hint"
  }, "Il capocommessa ha gi\xE0 deciso su almeno un\u2019anomalia: i seriali non si possono pi\xF9 cambiare. Puoi aggiungere nuove anomalie.") : /*#__PURE__*/React.createElement("div", {
    className: "field-hint"
  }, "Un seriale, un range (", /*#__PURE__*/React.createElement("code", null, "LCN00005-LCN00010"), ") o pi\xF9 seriali separati da virgola; Invio per confermare.", tokens.length > 1 && /*#__PURE__*/React.createElement(React.Fragment, null, " Totale: ", /*#__PURE__*/React.createElement("strong", null, tokens.length, " pezzi"), ".")), (fuoriFormato.length > 0 || prefissoDiverso.length > 0 || ripetutiEditor.length > 0) && /*#__PURE__*/React.createElement("div", {
    className: "sn-warn"
  }, fuoriFormato.length > 0 && /*#__PURE__*/React.createElement("div", null, "\u26A0 Formato atteso \xABAAA00000\xBB: ", fuoriFormato.slice(0, 8).join(', '), fuoriFormato.length > 8 ? '…' : ''), prefissoDiverso.length > 0 && /*#__PURE__*/React.createElement("div", null, "\u26A0 Prefisso diverso da \xAB", primo.slice(0, 3).toUpperCase(), "\xBB: ", prefissoDiverso.slice(0, 8).join(', ')), ripetutiEditor.length > 0 && /*#__PURE__*/React.createElement("div", null, "\u26A0 Gi\xE0 in un altro blocco di questo controllo: ", ripetutiEditor.slice(0, 8).map(function (r) {
    return "".concat(r.token, " (blocco ").concat(r.blocco, ")");
  }).join(', '), ripetutiEditor.length > 8 ? '…' : '', ".", editor.confermaRipetuti ? ' Confermato: è voluto.' : ' Se è voluto (altra fase o altro stato superficie) puoi salvare: ti chiederò conferma. Altrimenti usa «Modifica» sul blocco esistente.')), duplicati.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "sn-dup-pop",
    role: "status",
    "aria-live": "polite"
  }, /*#__PURE__*/React.createElement("div", {
    className: "sn-dup-pop__head"
  }, /*#__PURE__*/React.createElement("span", {
    className: "sn-dup-pop__icon"
  }, "!"), duplicati.length === 1 ? 'Questo S/N ha già un’anomalia aperta' : 'Questi S/N hanno già anomalie aperte'), duplicati.map(function (d) {
    return /*#__PURE__*/React.createElement("div", {
      className: "sn-dup-card",
      key: d.token
    }, /*#__PURE__*/React.createElement("div", {
      className: "sn-dup-card__top"
    }, /*#__PURE__*/React.createElement("span", {
      className: "sn-dup-card__sn"
    }, d.token), d.avanzamento && /*#__PURE__*/React.createElement("span", {
      className: "sn-dup-card__stato"
    }, d.avanzamento)), /*#__PURE__*/React.createElement("div", {
      className: "sn-dup-card__desc"
    }, d.descrizione || /*#__PURE__*/React.createElement("em", null, "(nessuna descrizione registrata)")), d.autore && /*#__PURE__*/React.createElement("div", {
      className: "sn-dup-card__meta"
    }, "Inserita da ", /*#__PURE__*/React.createElement("strong", null, d.autore)));
  }))), STATI_SUPERFICIE.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "field-group"
  }, /*#__PURE__*/React.createElement("div", {
    className: "field-label",
    id: "sup-label"
  }, "Stato superficie del blocco ", !editor.bloccato && /*#__PURE__*/React.createElement("span", {
    className: "req"
  }, "*")), /*#__PURE__*/React.createElement("div", {
    className: "sup-chips".concat(!editor.bloccato && !editor.stati.length && error === MSG_SUP ? ' is-missing' : ''),
    role: "group",
    "aria-labelledby": "sup-label"
  }, STATI_SUPERFICIE.map(function (s) {
    var on = editor.stati.includes(s);
    return /*#__PURE__*/React.createElement("button", {
      key: s,
      type: "button",
      className: "sup-chip".concat(on ? ' is-on' : ''),
      "aria-pressed": on,
      disabled: editor.bloccato,
      onClick: function onClick() {
        if (error === MSG_SUP) setError('');
        setEditor(function (prev) {
          return _objectSpread(_objectSpread({}, prev), {}, {
            stati: prev.stati.includes(s) ? prev.stati.filter(function (x) {
              return x !== s;
            }) : [].concat(_toConsumableArray(prev.stati), [s])
          });
        });
      }
    }, on ? '✓ ' : '', s);
  })), /*#__PURE__*/React.createElement("div", {
    className: "field-hint"
  }, editor.bloccato ? 'Il capocommessa ha già deciso: lo stato superficie non si può più cambiare.' : 'Vale per tutti i pezzi del blocco. Pezzi in stati diversi? Mettili in blocchi separati.')), campoVisibile('dove_pezzi', {
    fase: controllo && controllo.fase
  }) && /*#__PURE__*/React.createElement("div", {
    className: "field-group"
  }, /*#__PURE__*/React.createElement("label", {
    className: "field-label",
    htmlFor: "dove-pezzi"
  }, "Dove sono i pezzi?"), /*#__PURE__*/React.createElement("input", {
    id: "dove-pezzi",
    className: "text-input",
    maxLength: 200,
    spellCheck: true,
    lang: "it",
    value: editor.dovePezzi || '',
    placeholder: "Es. area pezzi non conformi, reparto rettifica, carrello del collaudo\u2026",
    onChange: function onChange(e) {
      var v = e.target.value;
      setEditor(function (prev) {
        return _objectSpread(_objectSpread({}, prev), {}, {
          dovePezzi: v
        });
      });
    }
  }), /*#__PURE__*/React.createElement("div", {
    className: "field-hint"
  }, "Vale per tutti i pezzi del blocco; il capocommessa lo trova nella mail e in Gestione anomalie.")), /*#__PURE__*/React.createElement("div", {
    className: "field-group"
  }, /*#__PURE__*/React.createElement("div", {
    className: "field-label"
  }, "Anomalie su questi seriali ", /*#__PURE__*/React.createElement("span", {
    className: "req"
  }, "*")), /*#__PURE__*/React.createElement("div", {
    className: "anom-list"
  }, editor.anomalie.map(function (a, i) {
    var attiva = editor.attiva === i;
    var nAll = a.files.length + a.existing.length;
    if (!attiva) {
      return /*#__PURE__*/React.createElement("button", {
        type: "button",
        key: a.key,
        className: "anom-card is-collapsed".concat(a.gestita ? ' is-gestita' : ''),
        onClick: function onClick() {
          return setEditor(function (prev) {
            return _objectSpread(_objectSpread({}, prev), {}, {
              attiva: i
            });
          });
        }
      }, /*#__PURE__*/React.createElement("span", {
        className: "anom-card__n"
      }, i + 1), /*#__PURE__*/React.createElement("span", {
        className: "anom-card__txt"
      }, a.testo.trim() || /*#__PURE__*/React.createElement("em", null, "Anomalia senza descrizione")), !a.tutti && tokens.length > 1 && /*#__PURE__*/React.createElement("span", {
        className: "pill pill-parz"
      }, "Su ", tokens.filter(function (t) {
        return a.sel.some(function (x) {
          return x.toLowerCase() === t.toLowerCase();
        });
      }).length, " di ", tokens.length, " S/N"), nAll > 0 && /*#__PURE__*/React.createElement("span", {
        className: "anom-card__att"
      }, "\uD83D\uDCCE ", nAll), a.origineId && /*#__PURE__*/React.createElement("span", {
        className: "pill pill-info"
      }, "da #", a.origineId, a.copiaAllegati && a.allegatiOrigine ? " \xB7 \uD83D\uDCCE ".concat(a.allegatiOrigine) : ''), a.gestita && /*#__PURE__*/React.createElement("span", {
        className: "pill pill-info"
      }, a.avanzamento || 'Gestita'), /*#__PURE__*/React.createElement("span", {
        className: "anom-card__edit"
      }, a.gestita ? 'Vedi' : 'Apri'));
    }
    return /*#__PURE__*/React.createElement("div", {
      key: a.key,
      className: "anom-card is-active".concat(a.gestita ? ' is-gestita' : '')
    }, /*#__PURE__*/React.createElement("div", {
      className: "anom-card__head"
    }, /*#__PURE__*/React.createElement("span", {
      className: "anom-card__n"
    }, i + 1), /*#__PURE__*/React.createElement("span", {
      className: "anom-card__title"
    }, "Anomalia ", i + 1, a.localId ? " \xB7 #".concat(a.localId) : ''), a.gestita && /*#__PURE__*/React.createElement("span", {
      className: "pill pill-info"
    }, "Gestita dal capocommessa: ", a.avanzamento || 'decisione presa'), a.origineId && /*#__PURE__*/React.createElement("span", {
      className: "pill pill-info"
    }, "Copiata da #", a.origineId), !a.localId && editor.anomalie.length > 1 && /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: "link-btn link-btn--danger",
      onClick: function onClick() {
        return rimuoviAnomalia(i);
      }
    }, "Rimuovi"), puoAgireSu(a) && !azAnom && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: "link-btn",
      title: "Sposta su un altro S/N dello stesso OP o di un altro OP",
      onClick: function onClick() {
        return setAzAnom({
          key: a.key,
          tipo: 'taglia',
          busy: false,
          err: ''
        });
      }
    }, "\u2702 Taglia"), /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: "link-btn link-btn--danger",
      onClick: function onClick() {
        return setAzAnom({
          key: a.key,
          tipo: 'elimina',
          busy: false,
          err: ''
        });
      }
    }, "Elimina")), /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: "link-btn",
      onClick: function onClick() {
        return setEditor(function (prev) {
          return _objectSpread(_objectSpread({}, prev), {}, {
            attiva: -1
          });
        });
      }
    }, "Comprimi")), azAnom && azAnom.key === a.key && azAnom.tipo === 'elimina' && /*#__PURE__*/React.createElement("div", {
      className: "error-msg",
      role: "alert"
    }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("strong", null, "Eliminare l\u2019anomalia #", a.localId, "?"), " Sparisce dall\u2019OP con i suoi dati; gli allegati restano recuperabili dall\u2019amministratore. Non si pu\xF2 annullare."), azAnom.err && /*#__PURE__*/React.createElement("div", {
      style: {
        marginTop: 6
      }
    }, azAnom.err), /*#__PURE__*/React.createElement("div", {
      className: "anom-taglia__foot",
      style: {
        marginTop: 8
      }
    }, /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: "btn-secondary",
      disabled: azAnom.busy,
      onClick: function onClick() {
        return setAzAnom(null);
      }
    }, "Annulla"), /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: "btn-primary",
      style: {
        background: 'var(--danger)'
      },
      disabled: azAnom.busy,
      onClick: function onClick() {
        return eliminaAnomalia(a);
      }
    }, azAnom.busy ? 'Elimino…' : 'Elimina'))), azAnom && azAnom.key === a.key && azAnom.tipo === 'taglia' && /*#__PURE__*/React.createElement(TagliaPanel, {
      anomalia: a,
      opCorrente: controllo ? controllo.op_id : '',
      onCancel: function onCancel() {
        return setAzAnom(null);
      },
      onDone: function onDone(j) {
        return tagliaFatta(a, j);
      }
    }), campoVisibile('simboli', {
      fase: controllo && controllo.fase,
      tipo: codiceTipoAnomalia(a.dett, a.testo)
    }) && /*#__PURE__*/React.createElement(BarraSimboli, {
      disabled: a.gestita,
      fallbackRef: testoRef
    }), /*#__PURE__*/React.createElement("textarea", {
      ref: testoRef,
      className: "textarea-input",
      rows: 4,
      autoFocus: !a.gestita,
      disabled: a.gestita,
      spellCheck: true,
      lang: "it",
      "aria-label": "Descrizione anomalia ".concat(i + 1),
      placeholder: "Cosa hai rilevato, dove si trova sul pezzo, misura rilevata e tolleranza\u2026",
      value: a.testo,
      onChange: function onChange(e) {
        return updAnomalia(i, {
          testo: e.target.value
        });
      }
    }), /*#__PURE__*/React.createElement(DettaglioAnomalia, {
      dett: a.dett,
      testo: a.testo,
      disabled: a.gestita,
      opId: controllo ? controllo.op_id : '',
      fase: controllo ? controllo.fase : '',
      onChange: function onChange(dett) {
        return updAnomalia(i, {
          dett: dett
        });
      },
      onCopiaNelTesto: function onCopiaNelTesto(righe) {
        return updAnomalia(i, {
          testo: [a.testo.trim()].concat(_toConsumableArray(righe)).filter(Boolean).join('\n')
        });
      }
    }), tokens.length > 1 && function () {
      var selSet = new Set(a.sel.map(function (t) {
        return t.toLowerCase();
      }));
      var nSel = tokens.filter(function (t) {
        return selSet.has(t.toLowerCase());
      }).length;
      var missing = !a.tutti && !nSel && error.startsWith(MSG_SN_ANOM);
      return /*#__PURE__*/React.createElement("div", {
        className: "anom-sn".concat(a.tutti ? '' : ' is-parziale').concat(missing ? ' is-missing' : '')
      }, /*#__PURE__*/React.createElement("label", {
        className: "anom-sn__toggle".concat(a.gestita ? ' is-disabled' : '')
      }, /*#__PURE__*/React.createElement("input", {
        type: "checkbox",
        checked: a.tutti,
        disabled: a.gestita,
        onChange: function onChange(e) {
          if (error.startsWith(MSG_SN_ANOM)) setError('');
          updAnomalia(i, {
            tutti: e.target.checked
          });
        }
      }), /*#__PURE__*/React.createElement("span", null, "Presente su tutti i ", tokens.length, " seriali del blocco")), !a.tutti && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("div", {
        className: "anom-sn__chips",
        role: "group",
        "aria-label": "Seriali con l\u2019anomalia ".concat(i + 1),
        onPointerMove: function onPointerMove(e) {
          var d = snDragRef.current;
          if (!d || d.anomalia !== i) return;
          var el = document.elementFromPoint(e.clientX, e.clientY);
          var chip = el && el.closest ? el.closest('[data-sn-idx]') : null;
          if (!chip || !e.currentTarget.contains(chip)) return;
          var idx = Number(chip.getAttribute('data-sn-idx'));
          if (idx === d.last) return;
          // Anche i chip saltati con un movimento veloce: tutto il tratto fra l'ultimo e questo.
          var _ref51 = idx > d.last ? [d.last, idx] : [idx, d.last],
            _ref52 = _slicedToArray(_ref51, 2),
            da = _ref52[0],
            a2 = _ref52[1];
          impostaSeriali(i, tokens.slice(da, a2 + 1), d.mode);
          d.last = idx;
        }
      }, tokens.map(function (t, ti) {
        var on = selSet.has(t.toLowerCase());
        return /*#__PURE__*/React.createElement("button", {
          key: t,
          type: "button",
          className: "anom-sn__chip".concat(on ? ' is-on' : ''),
          "aria-pressed": on,
          disabled: a.gestita,
          "data-sn-idx": ti,
          onPointerDown: function onPointerDown(e) {
            if (e.button !== 0 || a.gestita) return;
            e.preventDefault();
            // Il primo chip decide: spento → si accende tutto il tratto, acceso → si spegne.
            snDragRef.current = {
              anomalia: i,
              mode: !on,
              last: ti
            };
            if (error.startsWith(MSG_SN_ANOM)) setError('');
            impostaSeriali(i, [t], !on);
          },
          onClick: function onClick(e) {
            // Mouse e tocco passano da onPointerDown; qui solo la tastiera (Invio/Spazio).
            if (e.detail !== 0) return;
            if (error.startsWith(MSG_SN_ANOM)) setError('');
            impostaSeriali(i, [t], !on);
          }
        }, /*#__PURE__*/React.createElement("span", {
          className: "anom-sn__ck",
          "aria-hidden": "true"
        }, "\u2713"), t);
      })), /*#__PURE__*/React.createElement("div", {
        className: "anom-sn__foot"
      }, /*#__PURE__*/React.createElement("span", null, nSel ? /*#__PURE__*/React.createElement(React.Fragment, null, "Selezionati ", /*#__PURE__*/React.createElement("strong", null, nSel), " di ", tokens.length) : 'Tocca i seriali su cui hai trovato questa anomalia, oppure trascina per sceglierne più di fila.'), !a.gestita && nSel < tokens.length && /*#__PURE__*/React.createElement("button", {
        type: "button",
        className: "link-btn",
        onClick: function onClick() {
          return updAnomalia(i, {
            sel: _toConsumableArray(tokens)
          });
        }
      }, "Seleziona tutti"), !a.gestita && nSel > 0 && /*#__PURE__*/React.createElement("button", {
        type: "button",
        className: "link-btn",
        onClick: function onClick() {
          return updAnomalia(i, {
            sel: []
          });
        }
      }, "Nessuno"))));
    }(), a.origineId && a.allegatiOrigine > 0 && !a.localId && /*#__PURE__*/React.createElement("label", {
      className: "clona-att"
    }, /*#__PURE__*/React.createElement("input", {
      type: "checkbox",
      checked: !!a.copiaAllegati,
      onChange: function onChange(e) {
        return updAnomalia(i, {
          copiaAllegati: e.target.checked
        });
      }
    }), /*#__PURE__*/React.createElement("span", null, "Copia anche ", a.allegatiOrigine === 1 ? 'l’allegato' : "i ".concat(a.allegatiOrigine, " allegati"), " dell\u2019anomalia #", a.origineId)), /*#__PURE__*/React.createElement(AttachmentZone, {
      files: a.files,
      existing: a.existing,
      disabled: a.gestita,
      onAdd: function onAdd(files) {
        return addFiles(i, files, false);
      },
      onRemove: function onRemove(fi) {
        return updAnomalia(i, {
          files: a.files.filter(function (_, idx) {
            return idx !== fi;
          })
        });
      }
    }), !a.gestita && /*#__PURE__*/React.createElement("div", {
      className: "copilot-inline"
    }, /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: "link-btn",
      onClick: function onClick() {
        return proponiCopilota(a);
      },
      disabled: copilot.loading
    }, copilot.loading && copilot.key === a.key ? 'Analisi…' : 'Suggerimento AI sul triage'), copilot.key === a.key && copilot.err && /*#__PURE__*/React.createElement("span", {
      className: "copilot-err"
    }, copilot.err), copilot.key === a.key && copilot.sug && /*#__PURE__*/React.createElement("div", {
      className: "copilot-sug"
    }, copilot.sug.stato_superficie && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("strong", null, "Stato superficie:"), " ", copilot.sug.stato_superficie), copilot.sug.avanzamento && /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("strong", null, "Avanzamento:"), " ", copilot.sug.avanzamento), /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("strong", null, "Serve RDC/cliente:"), " ", copilot.sug.serve_rdc ? 'sì' : 'no'), copilot.sug.bozza_descrizione && /*#__PURE__*/React.createElement("div", {
      className: "copilot-sug__row"
    }, /*#__PURE__*/React.createElement("strong", null, "Bozza:"), " ", copilot.sug.bozza_descrizione), copilot.sug.motivazione && /*#__PURE__*/React.createElement("div", {
      className: "copilot-sug__row copilot-sug__why"
    }, /*#__PURE__*/React.createElement("em", null, copilot.sug.motivazione)))));
  })), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn-outline anom-add",
    onClick: nuovaAnomalia,
    disabled: saving
  }, "+ Nuova anomalia su questi seriali"), scopertiEditor.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "sn-warn",
    role: "status"
  }, "\u26A0 ", scopertiEditor.length, " di ", tokens.length, " S/N senza nessuna anomalia: ", comprimiTokens(scopertiEditor).slice(0, 8).join(', '), comprimiTokens(scopertiEditor).length > 8 ? '…' : '', ".", ' ', "Assegnali a un\u2019anomalia", editor.bloccato ? '' : ' o toglili dal blocco', "."), attachErr && /*#__PURE__*/React.createElement("div", {
    className: "sn-warn"
  }, "\u26A0 ", attachErr)), confirmScoperti && /*#__PURE__*/React.createElement("div", {
    className: "confirm-box",
    role: "alertdialog",
    "aria-label": "Seriali senza anomalia"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("strong", null, confirmScoperti.length === 1 ? 'Questo seriale del blocco non ha' : "Questi ".concat(confirmScoperti.length, " seriali del blocco non hanno"), " nessuna anomalia:"), " ", comprimiTokens(confirmScoperti).slice(0, 10).join(', '), comprimiTokens(confirmScoperti).length > 10 ? '…' : '', "."), /*#__PURE__*/React.createElement("div", null, "Ogni S/N del blocco dovrebbe avere almeno un\u2019anomalia. Hai dimenticato di selezionarli in un\u2019anomalia, oppure sono pezzi buoni da togliere dal blocco?"), /*#__PURE__*/React.createElement("div", {
    className: "action-bar"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn-secondary",
    onClick: function onClick() {
      return setConfirmScoperti(null);
    }
  }, "Annulla, correggo"), !editor.bloccato && /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn-secondary",
    onClick: togliScopertiESalva,
    disabled: saving
  }, "Togli dal blocco e salva"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn-primary",
    onClick: confermaScopertiESalva,
    disabled: saving
  }, "Salva comunque"))), confirmRipetuti && /*#__PURE__*/React.createElement("div", {
    className: "confirm-box",
    role: "alertdialog",
    "aria-label": "Seriali gi\xE0 in un altro blocco"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("strong", null, "Questi seriali sono gi\xE0 in un altro blocco del controllo:"), " ", confirmRipetuti.slice(0, 10).map(function (r) {
    return "".concat(r.seriale, " (blocco ").concat(r.blocco, ")");
  }).join(', '), confirmRipetuti.length > 10 ? '…' : '', "."), /*#__PURE__*/React.createElement("div", null, "\xC8 voluto? Per esempio lo stesso pezzo in un\u2019altra fase o con un altro stato superficie. Se invece vuoi aggiungere anomalie a quei pezzi, annulla e usa \xABModifica\xBB sul blocco esistente."), /*#__PURE__*/React.createElement("div", {
    className: "action-bar"
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn-secondary",
    onClick: function onClick() {
      return setConfirmRipetuti(null);
    }
  }, "Annulla, correggo"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn-primary",
    onClick: confermaESalva,
    disabled: saving
  }, "S\xEC, \xE8 voluto: salva"))), /*#__PURE__*/React.createElement("div", {
    className: "blk-actions"
  }, editor.bloccoId !== null && /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn-secondary",
    onClick: function onClick() {
      setEditor(newEditor());
      setError('');
    },
    disabled: saving
  }, "Annulla modifiche"), editor.bloccoId === null && editor.daClona && /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn-secondary",
    onClick: function onClick() {
      setEditor(editorDopo(coda));
      setError('');
      setNotice('');
    },
    disabled: saving
  }, "Salta questo blocco"), editor.bloccoId === null && dirty && !editor.daClona && /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn-secondary",
    onClick: function onClick() {
      setEditor(newEditor());
      setError('');
    },
    disabled: saving
  }, "Svuota"), /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "btn-primary",
    onClick: function onClick() {
      return salvaBlocco();
    },
    disabled: saving
  }, saving ? 'Salvataggio…' : editor.bloccoId ? 'Salva modifiche' : 'Salva blocco')));
  return /*#__PURE__*/React.createElement("div", {
    className: "step-card step-card--wide"
  }, opBar, /*#__PURE__*/React.createElement("div", {
    className: "ctl-head"
  }, /*#__PURE__*/React.createElement("div", {
    className: "ctl-head__fase"
  }, /*#__PURE__*/React.createElement("span", {
    className: "field-label"
  }, "Fase"), editingFase ? /*#__PURE__*/React.createElement("span", {
    className: "ctl-head__edit"
  }, /*#__PURE__*/React.createElement("input", {
    className: "text-input",
    type: "text",
    list: "fasi-op",
    maxLength: 100,
    value: fase,
    autoFocus: true,
    onChange: function onChange(e) {
      return setFase(e.target.value);
    },
    onKeyDown: function onKeyDown(e) {
      if (e.key === 'Enter') salvaImpostazioni({
        fase: fase.trim()
      });
    }
  }), /*#__PURE__*/React.createElement("datalist", {
    id: "fasi-op"
  }, fasiNote.map(function (f) {
    return /*#__PURE__*/React.createElement("option", {
      key: f,
      value: f
    });
  })), /*#__PURE__*/React.createElement("button", {
    className: "btn-primary btn-sm",
    onClick: function onClick() {
      return salvaImpostazioni({
        fase: fase.trim()
      });
    },
    disabled: !fase.trim()
  }, "OK"), /*#__PURE__*/React.createElement("button", {
    className: "btn-secondary btn-sm",
    onClick: function onClick() {
      setFase(controllo.fase);
      setEditingFase(false);
    }
  }, "Annulla")) : /*#__PURE__*/React.createElement("span", {
    className: "ctl-head__val"
  }, controllo.fase, " ", /*#__PURE__*/React.createElement("button", {
    type: "button",
    className: "link-btn",
    onClick: function onClick() {
      return setEditingFase(true);
    }
  }, "Cambia"))), blocchi.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "ctl-stats",
    "aria-label": "Avanzamento del controllo"
  }, /*#__PURE__*/React.createElement("span", {
    className: "ctl-stat"
  }, /*#__PURE__*/React.createElement("strong", null, blocchi.length), " blocch", blocchi.length === 1 ? 'o' : 'i'), /*#__PURE__*/React.createElement("span", {
    className: "ctl-stat"
  }, /*#__PURE__*/React.createElement("strong", null, nPezzi), " pezz", nPezzi === 1 ? 'o' : 'i'), /*#__PURE__*/React.createElement("span", {
    className: "ctl-stat"
  }, /*#__PURE__*/React.createElement("strong", null, nAnomalie), " anomali", nAnomalie === 1 ? 'a' : 'e')), /*#__PURE__*/React.createElement("div", {
    className: "ctl-head__mail"
  }, /*#__PURE__*/React.createElement("span", {
    className: "field-label"
  }, "Mail al capocommessa"), /*#__PURE__*/React.createElement("span", {
    className: "ctl-head__val",
    title: MAIL_FINE_HINT
  }, controllo.mail_mode === 'subito' ? 'a ogni blocco' : 'a fine controllo')), /*#__PURE__*/React.createElement(DestinatariMail, {
    compact: true,
    destinatari: destinatari,
    extra: controllo.destinatari_extra || [],
    disabled: saving,
    onChange: function onChange(lista) {
      return salvaImpostazioni({
        destinatari_extra: lista
      });
    }
  })), /*#__PURE__*/React.createElement("div", {
    className: "form-body"
  }, blocchi.map(function (b, i) {
    return editor.bloccoId === b.id ? /*#__PURE__*/React.createElement(React.Fragment, {
      key: b.id
    }, editorCard) : /*#__PURE__*/React.createElement(BloccoCongelato, {
      key: b.id,
      b: b,
      index: i,
      canEdit: !dirty && !saving,
      onEdit: function onEdit() {
        setEditor(editorFromBlocco(b));
        setError('');
        setNotice('');
      }
    });
  }), editor.bloccoId === null && editorCard, coda.length > 0 && /*#__PURE__*/React.createElement("div", {
    className: "clona-coda"
  }, /*#__PURE__*/React.createElement("div", {
    className: "field-label"
  }, "Da copiare ancora (", coda.length, ")"), coda.map(function (b, i) {
    return /*#__PURE__*/React.createElement("div", {
      key: i,
      className: "clona-coda__row"
    }, /*#__PURE__*/React.createElement("span", {
      className: "clona-coda__sn"
    }, labelVoci(b.seriali)), /*#__PURE__*/React.createElement("span", {
      className: "clona-coda__txt"
    }, b.anomalie.length, " anomali", b.anomalie.length === 1 ? 'a' : 'e', " \xB7 ", b.anomalie.map(function (a) {
      return a.testo;
    }).filter(Boolean).join(' · ')), /*#__PURE__*/React.createElement("button", {
      type: "button",
      className: "link-btn",
      disabled: saving || dirty && !editor.daClona || editor.bloccoId !== null,
      title: "Carica ora questo blocco (quello in scrittura torna in coda)",
      onClick: function onClick() {
        var resto = coda.filter(function (_, idx) {
          return idx !== i;
        });
        setCoda(editor.daClona && editorCorrenteBlocco(editor) ? [editorCorrenteBlocco(editor)].concat(_toConsumableArray(resto)) : resto);
        setEditor(editorDaClona(b));
        setError('');
      }
    }, "Carica ora"));
  })), notice && /*#__PURE__*/React.createElement("div", {
    className: "info-msg"
  }, notice), error && /*#__PURE__*/React.createElement("div", {
    className: "error-msg"
  }, error), confirmTermina && /*#__PURE__*/React.createElement("div", {
    className: "confirm-box"
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("strong", null, "Il blocco in corso non \xE8 salvato."), " Vuoi salvarlo prima di vedere il riepilogo?"), /*#__PURE__*/React.createElement("div", {
    className: "action-bar"
  }, /*#__PURE__*/React.createElement("button", {
    className: "btn-secondary",
    onClick: function onClick() {
      return setConfirmTermina(false);
    }
  }, "Annulla"), /*#__PURE__*/React.createElement("button", {
    className: "btn-outline",
    onClick: function onClick() {
      return apriRiepilogo(false);
    }
  }, "Scarta il blocco"), /*#__PURE__*/React.createElement("button", {
    className: "btn-primary",
    onClick: function onClick() {
      return apriRiepilogo(true);
    }
  }, "Salva e vai al riepilogo"))), /*#__PURE__*/React.createElement("div", {
    className: "ctl-footer"
  }, /*#__PURE__*/React.createElement("div", {
    className: "field-hint"
  }, controllo.mail_mode === 'fine' ? controllo.da_notificare ? "".concat(controllo.da_notificare === 1 ? '1 anomalia in attesa: partirà' : "".concat(controllo.da_notificare, " anomalie in attesa: partiranno"), " in un\u2019unica mail con \xABTermina controllo\xBB. Se ti fermi, fra ").concat(durata(TEMPI.promemoria), " ricevi un promemoria.") : 'La mail partirà con «Termina controllo».' : controllo.da_notificare ? "".concat(controllo.da_notificare, " anomalie in coda: la mail parte pochi minuti dopo l\u2019ultimo salvataggio.") : 'Ogni blocco salvato viene comunicato al capocommessa.', controllo.mail_errore && /*#__PURE__*/React.createElement("div", {
    className: "copilot-err"
  }, "Ultimo invio non riuscito: ", controllo.mail_errore)), /*#__PURE__*/React.createElement("button", {
    className: "btn-primary btn-termina",
    onClick: function onClick() {
      return dirty ? setConfirmTermina(true) : apriRiepilogo(false);
    },
    disabled: saving || !blocchi.length && !dirty
  }, "Termina controllo\u2026"))));
};

/* ── App Root ── */
var AperturaSegnalazione = function AperturaSegnalazione() {
  var _useState119 = useState(1),
    _useState120 = _slicedToArray(_useState119, 2),
    step = _useState120[0],
    setStep = _useState120[1];
  var _useState121 = useState(null),
    _useState122 = _slicedToArray(_useState121, 2),
    selectedOp = _useState122[0],
    setSelectedOp = _useState122[1];
  var _useState123 = useState(0),
    _useState124 = _slicedToArray(_useState123, 2),
    formKey = _useState124[0],
    setFormKey = _useState124[1];
  var _useState125 = useState(null),
    _useState126 = _slicedToArray(_useState125, 2),
    clona = _useState126[0],
    setClona = _useState126[1];
  var _useState127 = useState(CLONA_PARAMS ? 'loading' : ''),
    _useState128 = _slicedToArray(_useState127, 2),
    clonaStato = _useState128[0],
    setClonaStato = _useState128[1];
  useEffect(function () {
    if (!CLONA_PARAMS) return;
    getJson("".concat(API.clona, "?op_id=").concat(encodeURIComponent(CLONA_PARAMS.da), "&anomalie=").concat(CLONA_PARAMS.ids.join(',')), 'Anomalie da copiare').then(function (j) {
      if (!j.blocchi || !j.blocchi.length) {
        setClonaStato('Nessuna delle anomalie scelte è stata trovata su questo OP.');
        return;
      }
      setClona(j);
      setClonaStato('');
      // Un ricaricamento non deve ricopiare tutto da capo (OP e blocchi doppi).
      window.history.replaceState(null, '', window.location.pathname);
    })["catch"](function (e) {
      return setClonaStato(e.message || 'Errore nel caricare le anomalie da copiare');
    });
  }, []);
  var handleSelectOp = function handleSelectOp(op) {
    setSelectedOp(op);
    setStep(2);
    setFormKey(function (k) {
      return k + 1;
    });
  };
  // OP nuovo creato al primo salvataggio: da qui in poi si lavora sull'OP vero.
  var handleOpCreato = function handleOpCreato(op) {
    return setSelectedOp(op);
  };
  // Cambio OP dalla barra in alto: il controllo (se c'è) è già stato spostato dal server e si riapre.
  var handleCambiaOp = function handleCambiaOp(op, controlloId) {
    setSelectedOp(op);
    setRiprendiId(controlloId || null);
    setFormKey(function (k) {
      return k + 1;
    });
    if (window.location.search) window.history.replaceState(null, '', window.location.pathname);
  };
  var handleBack = function handleBack() {
    setStep(1);
    setSelectedOp(null);
    setRiprendiId(null);
  };

  // Link del promemoria (?controllo=<id>): riapre quel controllo; per un OP nuovo
  // non ancora creato l'OP si ricostruisce dai dati salvati nel controllo.
  var _useState129 = useState(null),
    _useState130 = _slicedToArray(_useState129, 2),
    riprendiId = _useState130[0],
    setRiprendiId = _useState130[1];
  useEffect(function () {
    var cid = new URLSearchParams(window.location.search).get('controllo');
    if (!cid || !/^\d+$/.test(cid)) return;
    getJson(urlFor(API.controllo_dettaglio, cid), 'Ripresa controllo').then(/*#__PURE__*/function () {
      var _ref53 = _asyncToGenerator(/*#__PURE__*/_regenerator().m(function _callee20(j) {
        var c, nuovo, opSel, list;
        return _regenerator().w(function (_context20) {
          while (1) switch (_context20.n) {
            case 0:
              c = j.controllo || {};
              nuovo = c.op_nuovo && Object.keys(c.op_nuovo).length ? c.op_nuovo : null;
              opSel = null;
              if (!nuovo) {
                _context20.n = 1;
                break;
              }
              opSel = {
                id: c.op_id,
                item_id: null,
                pn: nuovo.pn || '—',
                capo: nuovo.capocommessa || '—',
                car: nuovo.car || '—',
                stato: nuovo.collaudo_benestare ? 'Benestare' : 'Aperto',
                daCreare: nuovo
              };
              _context20.n = 3;
              break;
            case 1:
              _context20.n = 2;
              return getJson(API.db_ordini, 'Ordini')["catch"](function () {
                return [];
              });
            case 2:
              list = _context20.v;
              opSel = (Array.isArray(list) ? list : []).find(function (o) {
                return String(o.id) === String(c.op_id);
              }) || null;
            case 3:
              if (opSel) {
                _context20.n = 4;
                break;
              }
              return _context20.a(2);
            case 4:
              window.history.replaceState(null, '', window.location.pathname);
              setRiprendiId(Number(cid));
              setSelectedOp(opSel);
              setStep(2);
              setFormKey(function (k) {
                return k + 1;
              });
            case 5:
              return _context20.a(2);
          }
        }, _callee20);
      }));
      return function (_x22) {
        return _ref53.apply(this, arguments);
      };
    }())["catch"](function () {});
  }, []);

  // Preselezione OP da query string (?op_id=...): salta direttamente allo Step 2.
  useEffect(function () {
    var qs = new URLSearchParams(window.location.search);
    var preId = qs.get('op_id');
    if (!preId || qs.get('controllo')) return;
    var alive = true;
    fetch(API.db_ordini, {
      credentials: 'same-origin'
    }).then(function (r) {
      return r.ok ? r.json() : [];
    }).then(function (list) {
      if (!alive) return;
      var arr = Array.isArray(list) ? list : [];
      var found = arr.find(function (o) {
        return String(o.id) === String(preId);
      });
      if (found) {
        setSelectedOp(found);
        setStep(2);
      }
    })["catch"](function () {});
    return function () {
      alive = false;
    };
  }, []);
  var handleDone = function handleDone(action) {
    if (action === 'menu') {
      window.location.href = '/anomalie-menu';
      return;
    }
    setClona(null);
    if (action === 'altro_op') {
      handleBack();
      return;
    }
    setFormKey(function (k) {
      return k + 1;
    });
  };
  return /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("div", {
    className: "topbar"
  }, /*#__PURE__*/React.createElement("a", {
    href: "/anomalie-menu",
    className: "topbar-back"
  }, "\u2190 Menu Anomalie"), /*#__PURE__*/React.createElement("div", {
    className: "topbar-sep"
  }), /*#__PURE__*/React.createElement("div", {
    className: "topbar-title"
  }, "Controllo e segnalazione anomalie"), window._AP_CAN_MANAGE_CONFIG && /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("a", {
    href: "/gestione-anomalie/configurazione",
    className: "topbar-back"
  }, "Config Liste"), /*#__PURE__*/React.createElement("div", {
    className: "topbar-sep"
  })), /*#__PURE__*/React.createElement("div", {
    className: "topbar-user"
  }, window._AP_USERNAME)), /*#__PURE__*/React.createElement("div", {
    className: "content"
  }, clonaStato === 'loading' ? /*#__PURE__*/React.createElement("div", {
    className: "step-card"
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      padding: '24px 28px'
    }
  }, "Caricamento delle anomalie da copiare\u2026")) : step === 1 ? /*#__PURE__*/React.createElement(React.Fragment, null, clonaStato && /*#__PURE__*/React.createElement("div", {
    className: "error-msg",
    style: {
      marginBottom: 16
    }
  }, clonaStato), !clona && /*#__PURE__*/React.createElement(ControlliSospesi, null), /*#__PURE__*/React.createElement(Step1SelectOP, {
    onSelect: handleSelectOp,
    clona: clona
  })) : /*#__PURE__*/React.createElement(Step2Controllo, {
    key: formKey,
    op: selectedOp,
    onBack: handleBack,
    onDone: handleDone,
    clona: clona,
    onOpCreato: handleOpCreato,
    riprendiId: riprendiId,
    onCambiaOp: clona ? null : handleCambiaOp
  })));
};
var root = ReactDOM.createRoot(document.getElementById('root'));
root.render(React.createElement(AperturaSegnalazione));
