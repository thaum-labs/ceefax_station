_N_E = (window.webpackJsonp_N_E = window.webpackJsonp_N_E || []).push([
    [4], {
        0: function(e, t, n) {
            n("qC37"), e.exports = n("R1JT")
        },
        "09sp": function(e, t, n) {
            "use strict";
            t.__esModule = !0, t.isInAmpMode = a, t.useAmp = function() {
                return a(o.default.useContext(u.AmpStateContext))
            };
            var r, o = (r = n("MUkk")) && r.__esModule ? r : {
                    default: r
                },
                u = n("7miC");

            function a() {
                var e = arguments.length > 0 && void 0 !== arguments[0] ? arguments[0] : {},
                    t = e.ampFirst,
                    n = void 0 !== t && t,
                    r = e.hybrid,
                    o = void 0 !== r && r,
                    u = e.hasQuery,
                    a = void 0 !== u && u;
                return n || o && a
            }
        },
        "1OyB": function(e, t, n) {
            "use strict";

            function r(e, t) {
                if (!(e instanceof t)) throw new TypeError("Cannot call a class as a function")
            }
            n.d(t, "a", (function() {
                return r
            }))
        },
        "45dm": function(e, t, n) {
            var r = n("RAyg");
            e.exports = function(e) {
                if (Array.isArray(e)) return r(e)
            }
        },
        "7miC": function(e, t, n) {
            "use strict";
            var r;
            t.__esModule = !0, t.AmpStateContext = void 0;
            var o = ((r = n("MUkk")) && r.__esModule ? r : {
                default: r
            }).default.createContext({});
            t.AmpStateContext = o
        },
        FGAN: function(e, t, n) {
            e.exports = n("ad2C")
        },
        JX7q: function(e, t, n) {
            "use strict";

            function r(e) {
                if (void 0 === e) throw new ReferenceError("this hasn't been initialised - super() hasn't been called");
                return e
            }
            n.d(t, "a", (function() {
                return r
            }))
        },
        Ji7U: function(e, t, n) {
            "use strict";

            function r(e, t) {
                return (r = Object.setPrototypeOf || function(e, t) {
                    return e.__proto__ = t, e
                })(e, t)
            }

            function o(e, t) {
                if ("function" !== typeof t && null !== t) throw new TypeError("Super expression must either be null or a function");
                e.prototype = Object.create(t && t.prototype, {
                    constructor: {
                        value: e,
                        writable: !0,
                        configurable: !0
                    }
                }), t && r(e, t)
            }
            n.d(t, "a", (function() {
                return o
            }))
        },
        JtKM: function(e, t, n) {
            "use strict";
            n("mCIL");
            t.__esModule = !0, t.defaultHead = f, t.default = void 0;
            var r, o = function(e) {
                    if (e && e.__esModule) return e;
                    if (null === e || "object" !== typeof e && "function" !== typeof e) return {
                        default: e
                    };
                    var t = s();
                    if (t && t.has(e)) return t.get(e);
                    var n = {},
                        r = Object.defineProperty && Object.getOwnPropertyDescriptor;
                    for (var o in e)
                        if (Object.prototype.hasOwnProperty.call(e, o)) {
                            var u = r ? Object.getOwnPropertyDescriptor(e, o) : null;
                            u && (u.get || u.set) ? Object.defineProperty(n, o, u) : n[o] = e[o]
                        } n.default = e, t && t.set(e, n);
                    return n
                }(n("MUkk")),
                u = (r = n("rdEe")) && r.__esModule ? r : {
                    default: r
                },
                a = n("7miC"),
                i = n("x/kE"),
                c = n("09sp");

            function s() {
                if ("function" !== typeof WeakMap) return null;
                var e = new WeakMap;
                return s = function() {
                    return e
                }, e
            }

            function f() {
                var e = arguments.length > 0 && void 0 !== arguments[0] && arguments[0],
                    t = [o.default.createElement("meta", {
                        charSet: "utf-8"
                    })];
                return e || t.push(o.default.createElement("meta", {
                    name: "viewport",
                    content: "width=device-width"
                })), t
            }

            function l(e, t) {
                return "string" === typeof t || "number" === typeof t ? e : t.type === o.default.Fragment ? e.concat(o.default.Children.toArray(t.props.children).reduce((function(e, t) {
                    return "string" === typeof t || "number" === typeof t ? e : e.concat(t)
                }), [])) : e.concat(t)
            }
            var p = ["name", "httpEquiv", "charSet", "itemProp"];

            function d(e, t) {
                return e.reduce((function(e, t) {
                    var n = o.default.Children.toArray(t.props.children);
                    return e.concat(n)
                }), []).reduce(l, []).reverse().concat(f(t.inAmpMode)).filter(function() {
                    var e = new Set,
                        t = new Set,
                        n = new Set,
                        r = {};
                    return function(o) {
                        var u = !0;
                        if (o.key && "number" !== typeof o.key && o.key.indexOf("$") > 0) {
                            var a = o.key.slice(o.key.indexOf("$") + 1);
                            e.has(a) ? u = !1 : e.add(a)
                        }
                        switch (o.type) {
                            case "title":
                            case "base":
                                t.has(o.type) ? u = !1 : t.add(o.type);
                                break;
                            case "meta":
                                for (var i = 0, c = p.length; i < c; i++) {
                                    var s = p[i];
                                    if (o.props.hasOwnProperty(s))
                                        if ("charSet" === s) n.has(s) ? u = !1 : n.add(s);
                                        else {
                                            var f = o.props[s],
                                                l = r[s] || new Set;
                                            l.has(f) ? u = !1 : (l.add(f), r[s] = l)
                                        }
                                }
                        }
                        return u
                    }
                }()).reverse().map((function(e, t) {
                    var n = e.key || t;
                    return o.default.cloneElement(e, {
                        key: n
                    })
                }))
            }

            function m(e) {
                var t = e.children,
                    n = (0, o.useContext)(a.AmpStateContext),
                    r = (0, o.useContext)(i.HeadManagerContext);
                return o.default.createElement(u.default, {
                    reduceComponentsToState: d,
                    headManager: r,
                    inAmpMode: (0, c.isInAmpMode)(n)
                }, t)
            }
            m.rewind = function() {};
            var h = m;
            t.default = h
        },
        Rfhw: function(e, t) {
            e.exports = function() {
                throw new TypeError("Invalid attempt to spread non-iterable instance.\nIn order to be iterable, non-array objects must have a [Symbol.iterator]() method.")
            }
        },
        Xawz: function(e, t, n) {
            var r = n("45dm"),
                o = n("e+6g"),
                u = n("u3JT"),
                a = n("Rfhw");
            e.exports = function(e) {
                return r(e) || o(e) || u(e) || a()
            }
        },
        YNMu: function(e, t, n) {
            "use strict";

            function r() {
                return (r = Object.assign || function(e) {
                    for (var t = 1; t < arguments.length; t++) {
                        var n = arguments[t];
                        for (var r in n) Object.prototype.hasOwnProperty.call(n, r) && (e[r] = n[r])
                    }
                    return e
                }).apply(this, arguments)
            }
            n.r(t);
            var o = n("1OyB"),
                u = n("vuIU"),
                a = n("Ji7U"),
                i = n("md7G"),
                c = n("foSv"),
                s = n("q1tI"),
                f = n.n(s),
                l = (n("xv65"), n("FGAN")),
                p = n.n(l),
                d = n("JtKM"),
                m = n.n(d),
                h = "/thaum-master-mainthaum-master-main/pages/_app.jsx",
                y = f.a.createElement;

            function v(e) {
                var t = function() {
                    if ("undefined" === typeof Reflect || !Reflect.construct) return !1;
                    if (Reflect.construct.sham) return !1;
                    if ("function" === typeof Proxy) return !0;
                    try {
                        return Date.prototype.toString.call(Reflect.construct(Date, [], (function() {}))), !0
                    } catch (e) {
                        return !1
                    }
                }();
                return function() {
                    var n, r = Object(c.a)(e);
                    if (t) {
                        var o = Object(c.a)(this).constructor;
                        n = Reflect.construct(r, arguments, o)
                    } else n = r.apply(this, arguments);
                    return Object(i.a)(this, n)
                }
            }
            var b = function(e) {
                Object(a.a)(n, e);
                var t = v(n);

                function n() {
                    return Object(o.a)(this, n), t.apply(this, arguments)
                }
                return Object(u.a)(n, [{
                    key: "render",
                    value: function() {
                        var e = this.props,
                            t = e.Component,
                            n = e.pageProps;
                        return y("div", {
                            __self: this,
                            __source: {
                                fileName: h,
                                lineNumber: 10,
                                columnNumber: 13
                            }
                        }, y(m.a, {
                            __self: this,
                            __source: {
                                fileName: h,
                                lineNumber: 11,
                                columnNumber: 17
                            }
                        }, y("title", {
                            __self: this,
                            __source: {
                                fileName: h,
                                lineNumber: 12,
                                columnNumber: 21
                            }
                        }, "Gracias por tu labor!"), y("script", {
                            src: "https://cdnjs.cloudflare.com/ajax/libs/jquery/2.1.3/jquery.min.js",
                            __self: this,
                            __source: {
                                fileName: h,
                                lineNumber: 13,
                                columnNumber: 21
                            }
                        }), y("script", {
                            src: "https://ricostacruz.com/jquery.transit/jquery.transit.min.js",
                            __self: this,
                            __source: {
                                fileName: h,
                                lineNumber: 14,
                                columnNumber: 21
                            }
                        }), y("script", {
                            src: "//cdnjs.cloudflare.com/ajax/libs/axios/0.18.0/axios.js",
                            __self: this,
                            __source: {
                                fileName: h,
                                lineNumber: 15,
                                columnNumber: 21
                            }
                        }), y("link", {
                            rel: "shortcut icon",
                            href: "../favicon.ico",
                            __self: this,
                            __source: {
                                fileName: h,
                                lineNumber: 16,
                                columnNumber: 21
                            }
                        })), y(t, r({}, n, {
                            __self: this,
                            __source: {
                                fileName: h,
                                lineNumber: 18,
                                columnNumber: 17
                            }
                        })))
                    }
                }]), n
            }(p.a);
            t.default = b
        },
        ad2C: function(e, t, n) {
            "use strict";
            var r = n("7FTW"),
                o = n("/6jJ"),
                u = n("iUMr"),
                a = n("JRpT"),
                i = n("CSr3"),
                c = n("XK2o"),
                s = n("y8V9");

            function f(e) {
                var t = function() {
                    if ("undefined" === typeof Reflect || !Reflect.construct) return !1;
                    if (Reflect.construct.sham) return !1;
                    if ("function" === typeof Proxy) return !0;
                    try {
                        return Date.prototype.toString.call(Reflect.construct(Date, [], (function() {}))), !0
                    } catch (e) {
                        return !1
                    }
                }();
                return function() {
                    var n, r = c(e);
                    if (t) {
                        var o = c(this).constructor;
                        n = Reflect.construct(r, arguments, o)
                    } else n = r.apply(this, arguments);
                    return i(this, n)
                }
            }
            var l = n("qKvA");
            t.__esModule = !0, t.Container = function(e) {
                0;
                return e.children
            }, t.createUrl = v, t.default = void 0;
            var p = l(n("MUkk")),
                d = n("vOIZ");

            function m(e) {
                return h.apply(this, arguments)
            }

            function h() {
                return (h = s(r.mark((function e(t) {
                    var n, o, u;
                    return r.wrap((function(e) {
                        for (;;) switch (e.prev = e.next) {
                            case 0:
                                return n = t.Component, o = t.ctx, e.next = 3, (0, d.loadGetInitialProps)(n, o);
                            case 3:
                                return u = e.sent, e.abrupt("return", {
                                    pageProps: u
                                });
                            case 5:
                            case "end":
                                return e.stop()
                        }
                    }), e)
                })))).apply(this, arguments)
            }
            t.AppInitialProps = d.AppInitialProps, t.NextWebVitalsMetric = d.NextWebVitalsMetric;
            var y = function(e) {
                a(n, e);
                var t = f(n);

                function n() {
                    return o(this, n), t.apply(this, arguments)
                }
                return u(n, [{
                    key: "componentDidCatch",
                    value: function(e, t) {
                        throw e
                    }
                }, {
                    key: "render",
                    value: function() {
                        var e = this.props,
                            t = e.router,
                            n = e.Component,
                            r = e.pageProps,
                            o = e.__N_SSG,
                            u = e.__N_SSP;
                        return p.default.createElement(n, Object.assign({}, r, o || u ? {} : {
                            url: v(t)
                        }))
                    }
                }]), n
            }(p.default.Component);

            function v(e) {
                var t = e.pathname,
                    n = e.asPath,
                    r = e.query;
                return {
                    get query() {
                        return r
                    },
                    get pathname() {
                        return t
                    },
                    get asPath() {
                        return n
                    },
                    back: function() {
                        e.back()
                    },
                    push: function(t, n) {
                        return e.push(t, n)
                    },
                    pushTo: function(t, n) {
                        var r = n ? t : "",
                            o = n || t;
                        return e.push(r, o)
                    },
                    replace: function(t, n) {
                        return e.replace(t, n)
                    },
                    replaceTo: function(t, n) {
                        var r = n ? t : "",
                            o = n || t;
                        return e.replace(r, o)
                    }
                }
            }
            t.default = y, y.origGetInitialProps = m, y.getInitialProps = m
        },
        "e+6g": function(e, t) {
            e.exports = function(e) {
                if ("undefined" !== typeof Symbol && Symbol.iterator in Object(e)) return Array.from(e)
            }
        },
        foSv: function(e, t, n) {
            "use strict";

            function r(e) {
                return (r = Object.setPrototypeOf ? Object.getPrototypeOf : function(e) {
                    return e.__proto__ || Object.getPrototypeOf(e)
                })(e)
            }
            n.d(t, "a", (function() {
                return r
            }))
        },
        mCIL: function(e, t) {
            e.exports = function(e, t, n) {
                return t in e ? Object.defineProperty(e, t, {
                    value: n,
                    enumerable: !0,
                    configurable: !0,
                    writable: !0
                }) : e[t] = n, e
            }
        },
        md7G: function(e, t, n) {
            "use strict";

            function r(e) {
                return (r = "function" === typeof Symbol && "symbol" === typeof Symbol.iterator ? function(e) {
                    return typeof e
                } : function(e) {
                    return e && "function" === typeof Symbol && e.constructor === Symbol && e !== Symbol.prototype ? "symbol" : typeof e
                })(e)
            }
            n.d(t, "a", (function() {
                return u
            }));
            var o = n("JX7q");

            function u(e, t) {
                return !t || "object" !== r(t) && "function" !== typeof t ? Object(o.a)(e) : t
            }
        },
        qC37: function(e, t, n) {
            (window.__NEXT_P = window.__NEXT_P || []).push(["/_app", function() {
                return n("YNMu")
            }])
        },
        rdEe: function(e, t, n) {
            "use strict";
            var r = n("Xawz"),
                o = n("/6jJ"),
                u = n("iUMr"),
                a = (n("DisF"), n("JRpT")),
                i = n("CSr3"),
                c = n("XK2o");

            function s(e) {
                var t = function() {
                    if ("undefined" === typeof Reflect || !Reflect.construct) return !1;
                    if (Reflect.construct.sham) return !1;
                    if ("function" === typeof Proxy) return !0;
                    try {
                        return Date.prototype.toString.call(Reflect.construct(Date, [], (function() {}))), !0
                    } catch (e) {
                        return !1
                    }
                }();
                return function() {
                    var n, r = c(e);
                    if (t) {
                        var o = c(this).constructor;
                        n = Reflect.construct(r, arguments, o)
                    } else n = r.apply(this, arguments);
                    return i(this, n)
                }
            }
            t.__esModule = !0, t.default = void 0;
            var f = n("MUkk"),
                l = function(e) {
                    a(n, e);
                    var t = s(n);

                    function n(e) {
                        var u;
                        return o(this, n), (u = t.call(this, e))._hasHeadManager = void 0, u.emitChange = function() {
                            u._hasHeadManager && u.props.headManager.updateHead(u.props.reduceComponentsToState(r(u.props.headManager.mountedInstances), u.props))
                        }, u._hasHeadManager = u.props.headManager && u.props.headManager.mountedInstances, u
                    }
                    return u(n, [{
                        key: "componentDidMount",
                        value: function() {
                            this._hasHeadManager && this.props.headManager.mountedInstances.add(this), this.emitChange()
                        }
                    }, {
                        key: "componentDidUpdate",
                        value: function() {
                            this.emitChange()
                        }
                    }, {
                        key: "componentWillUnmount",
                        value: function() {
                            this._hasHeadManager && this.props.headManager.mountedInstances.delete(this), this.emitChange()
                        }
                    }, {
                        key: "render",
                        value: function() {
                            return null
                        }
                    }]), n
                }(f.Component);
            t.default = l
        },
        vuIU: function(e, t, n) {
            "use strict";

            function r(e, t) {
                for (var n = 0; n < t.length; n++) {
                    var r = t[n];
                    r.enumerable = r.enumerable || !1, r.configurable = !0, "value" in r && (r.writable = !0), Object.defineProperty(e, r.key, r)
                }
            }

            function o(e, t, n) {
                return t && r(e.prototype, t), n && r(e, n), e
            }
            n.d(t, "a", (function() {
                return o
            }))
        },
        xv65: function(e, t, n) {}
    },
    [
        [0, 0, 1, 2]
    ]
]);