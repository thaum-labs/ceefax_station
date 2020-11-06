_N_E = (window.webpackJsonp_N_E = window.webpackJsonp_N_E || []).push([
    [5], {
        0: function(t, e, r) {
            r("J5xr"), t.exports = r("nOHt")
        },
        "1OyB": function(t, e, r) {
            "use strict";

            function n(t, e) {
                if (!(t instanceof e)) throw new TypeError("Cannot call a class as a function")
            }
            r.d(e, "a", (function() {
                return n
            }))
        },
        "8Bbg": function(t, e, r) {
            t.exports = r("B5Ud")
        },
        B5Ud: function(t, e, r) {
            "use strict";
            var n = r("o0o1"),
                o = r("lwsE"),
                u = r("W8MJ"),
                c = r("7W2i"),
                i = r("a1gu"),
                a = r("Nsbk"),
                s = r("yXPU");

            function f(t) {
                var e = function() {
                    if ("undefined" === typeof Reflect || !Reflect.construct) return !1;
                    if (Reflect.construct.sham) return !1;
                    if ("function" === typeof Proxy) return !0;
                    try {
                        return Date.prototype.toString.call(Reflect.construct(Date, [], (function() {}))), !0
                    } catch (t) {
                        return !1
                    }
                }();
                return function() {
                    var r, n = a(t);
                    if (e) {
                        var o = a(this).constructor;
                        r = Reflect.construct(n, arguments, o)
                    } else r = n.apply(this, arguments);
                    return i(this, r)
                }
            }
            var l = r("TqRt");
            e.__esModule = !0, e.Container = function(t) {
                0;
                return t.children
            }, e.createUrl = h, e.default = void 0;
            var p = l(r("q1tI")),
                m = r("g/15");

            function b(t) {
                return _.apply(this, arguments)
            }

            function _() {
                return (_ = s(n.mark((function t(e) {
                    var r, o, u;
                    return n.wrap((function(t) {
                        for (;;) switch (t.prev = t.next) {
                            case 0:
                                return r = e.Component, o = e.ctx, t.next = 3, (0, m.loadGetInitialProps)(r, o);
                            case 3:
                                return u = t.sent, t.abrupt("return", {
                                    pageProps: u
                                });
                            case 5:
                            case "end":
                                return t.stop()
                        }
                    }), t)
                })))).apply(this, arguments)
            }
            e.AppInitialProps = m.AppInitialProps, e.NextWebVitalsMetric = m.NextWebVitalsMetric;
            var y = function(t) {
                c(r, t);
                var e = f(r);

                function r() {
                    return o(this, r), e.apply(this, arguments)
                }
                return u(r, [{
                    key: "componentDidCatch",
                    value: function(t, e) {
                        throw t
                    }
                }, {
                    key: "render",
                    value: function() {
                        var t = this.props,
                            e = t.router,
                            r = t.Component,
                            n = t.pageProps,
                            o = t.__N_SSG,
                            u = t.__N_SSP;
                        return p.default.createElement(r, Object.assign({}, n, o || u ? {} : {
                            url: h(e)
                        }))
                    }
                }]), r
            }(p.default.Component);

            function h(t) {
                var e = t.pathname,
                    r = t.asPath,
                    n = t.query;
                return {
                    get query() {
                        return n
                    },
                    get pathname() {
                        return e
                    },
                    get asPath() {
                        return r
                    },
                    back: function() {
                        t.back()
                    },
                    push: function(e, r) {
                        return t.push(e, r)
                    },
                    pushTo: function(e, r) {
                        var n = r ? e : "",
                            o = r || e;
                        return t.push(n, o)
                    },
                    replace: function(e, r) {
                        return t.replace(e, r)
                    },
                    replaceTo: function(e, r) {
                        var n = r ? e : "",
                            o = r || e;
                        return t.replace(n, o)
                    }
                }
            }
            e.default = y, y.origGetInitialProps = b, y.getInitialProps = b
        },
        J5xr: function(t, e, r) {
            (window.__NEXT_P = window.__NEXT_P || []).push(["/_app", function() {
                return r("YNMu")
            }])
        },
        JX7q: function(t, e, r) {
            "use strict";

            function n(t) {
                if (void 0 === t) throw new ReferenceError("this hasn't been initialised - super() hasn't been called");
                return t
            }
            r.d(e, "a", (function() {
                return n
            }))
        },
        Ji7U: function(t, e, r) {
            "use strict";

            function n(t, e) {
                return (n = Object.setPrototypeOf || function(t, e) {
                    return t.__proto__ = e, t
                })(t, e)
            }

            function o(t, e) {
                if ("function" !== typeof e && null !== e) throw new TypeError("Super expression must either be null or a function");
                t.prototype = Object.create(e && e.prototype, {
                    constructor: {
                        value: t,
                        writable: !0,
                        configurable: !0
                    }
                }), e && n(t, e)
            }
            r.d(e, "a", (function() {
                return o
            }))
        },
        YNMu: function(t, e, r) {
            "use strict";

            function n() {
                return (n = Object.assign || function(t) {
                    for (var e = 1; e < arguments.length; e++) {
                        var r = arguments[e];
                        for (var n in r) Object.prototype.hasOwnProperty.call(r, n) && (t[n] = r[n])
                    }
                    return t
                }).apply(this, arguments)
            }
            r.r(e);
            var o = r("1OyB"),
                u = r("vuIU"),
                c = r("Ji7U"),
                i = r("md7G"),
                a = r("foSv"),
                s = r("q1tI"),
                f = r.n(s),
                l = (r("xv65"), r("8Bbg")),
                p = r.n(l),
                m = r("8Kt/"),
                b = r.n(m),
                _ = "/thaum-master-mainthaum-master-main/pages/_app.jsx",
                y = f.a.createElement;

            function h(t) {
                var e = function() {
                    if ("undefined" === typeof Reflect || !Reflect.construct) return !1;
                    if (Reflect.construct.sham) return !1;
                    if ("function" === typeof Proxy) return !0;
                    try {
                        return Date.prototype.toString.call(Reflect.construct(Date, [], (function() {}))), !0
                    } catch (t) {
                        return !1
                    }
                }();
                return function() {
                    var r, n = Object(a.a)(t);
                    if (e) {
                        var o = Object(a.a)(this).constructor;
                        r = Reflect.construct(n, arguments, o)
                    } else r = n.apply(this, arguments);
                    return Object(i.a)(this, r)
                }
            }
            var v = function(t) {
                Object(c.a)(r, t);
                var e = h(r);

                function r() {
                    return Object(o.a)(this, r), e.apply(this, arguments)
                }
                return Object(u.a)(r, [{
                    key: "render",
                    value: function() {
                        var t = this.props,
                            e = t.Component,
                            r = t.pageProps;
                        return y("div", {
                            __self: this,
                            __source: {
                                fileName: _,
                                lineNumber: 10,
                                columnNumber: 13
                            }
                        }, y(b.a, {
                            __self: this,
                            __source: {
                                fileName: _,
                                lineNumber: 11,
                                columnNumber: 17
                            }
                        }, y("title", {
                            __self: this,
                            __source: {
                                fileName: _,
                                lineNumber: 12,
                                columnNumber: 21
                            }
                        }, "Gracias por tu labor!"), y("script", {
                            src: "https://cdnjs.cloudflare.com/ajax/libs/jquery/2.1.3/jquery.min.js",
                            __self: this,
                            __source: {
                                fileName: _,
                                lineNumber: 13,
                                columnNumber: 21
                            }
                        }), y("script", {
                            src: "https://ricostacruz.com/jquery.transit/jquery.transit.min.js",
                            __self: this,
                            __source: {
                                fileName: _,
                                lineNumber: 14,
                                columnNumber: 21
                            }
                        }), y("script", {
                            src: "//cdnjs.cloudflare.com/ajax/libs/axios/0.18.0/axios.js",
                            __self: this,
                            __source: {
                                fileName: _,
                                lineNumber: 15,
                                columnNumber: 21
                            }
                        }), y("link", {
                            rel: "shortcut icon",
                            href: "../favicon.ico",
                            __self: this,
                            __source: {
                                fileName: _,
                                lineNumber: 16,
                                columnNumber: 21
                            }
                        })), y(e, n({}, r, {
                            __self: this,
                            __source: {
                                fileName: _,
                                lineNumber: 18,
                                columnNumber: 17
                            }
                        })))
                    }
                }]), r
            }(p.a);
            e.default = v
        },
        foSv: function(t, e, r) {
            "use strict";

            function n(t) {
                return (n = Object.setPrototypeOf ? Object.getPrototypeOf : function(t) {
                    return t.__proto__ || Object.getPrototypeOf(t)
                })(t)
            }
            r.d(e, "a", (function() {
                return n
            }))
        },
        md7G: function(t, e, r) {
            "use strict";

            function n(t) {
                return (n = "function" === typeof Symbol && "symbol" === typeof Symbol.iterator ? function(t) {
                    return typeof t
                } : function(t) {
                    return t && "function" === typeof Symbol && t.constructor === Symbol && t !== Symbol.prototype ? "symbol" : typeof t
                })(t)
            }
            r.d(e, "a", (function() {
                return u
            }));
            var o = r("JX7q");

            function u(t, e) {
                return !e || "object" !== n(e) && "function" !== typeof e ? Object(o.a)(t) : e
            }
        },
        vuIU: function(t, e, r) {
            "use strict";

            function n(t, e) {
                for (var r = 0; r < e.length; r++) {
                    var n = e[r];
                    n.enumerable = n.enumerable || !1, n.configurable = !0, "value" in n && (n.writable = !0), Object.defineProperty(t, n.key, n)
                }
            }

            function o(t, e, r) {
                return e && n(t.prototype, e), r && n(t, r), t
            }
            r.d(e, "a", (function() {
                return o
            }))
        },
        xv65: function(t, e, r) {}
    },
    [
        [0, 0, 2, 1, 3]
    ]
]);