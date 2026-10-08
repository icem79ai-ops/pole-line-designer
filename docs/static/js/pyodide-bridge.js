/* pyodide-bridge.js - Lets the static build (docs/) serve the /api/* backend
   entirely in-browser by running line_engine.py through Pyodide.
   Only activates when window.__STATIC_HOST__ is set (injected by build_static.py).
   In normal Flask mode this file is inert, so it is safe to ship in web/static. */
(function () {
  "use strict";

  if (!window.__STATIC_HOST__) return;

  var PYODIDE_VERSION = "0.29.5";
  var PYODIDE_URL = "https://cdn.jsdelivr.net/pyodide/v" + PYODIDE_VERSION + "/full/";

  var nativeFetch = window.fetch.bind(window);
  var enginePromise = null;
  var apiHandle = null;

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = src;
      s.onload = resolve;
      s.onerror = function () { reject(new Error("โหลด Pyodide ไม่สำเร็จ: " + src)); };
      document.head.appendChild(s);
    });
  }

  /* Python mirror of the Flask routes in app.py. Returns a JSON envelope
     {status, body, headers}. Uses the engine functions already imported onto
     the Pyodide globals by runPython(line_engine source). */
  var PY_SHIM = [
    "import json",
    "",
    "def _envelope(status, body, ctype, extra_headers=None):",
    "    headers = {'Content-Type': ctype}",
    "    if extra_headers:",
    "        headers.update(extra_headers)",
    "    return json.dumps({'status': status, 'body': body, 'headers': headers}, ensure_ascii=False)",
    "",
    "def _err(status, message):",
    "    return _envelope(status, json.dumps({'error': message}, ensure_ascii=False), 'application/json; charset=utf-8')",
    "",
    "def handle_api(method, path, query_string, body_text):",
    "    try:",
    "        if path == '/api/health':",
    "            if method != 'GET':",
    "                return _err(405, 'Method Not Allowed')",
    "            return _envelope(200, json.dumps({",
    "                'status': 'ok',",
    "                'engine': 'line_engine',",
    "                'row_offset_m': ROW_OFFSET,",
    "                'tangent_max_span_m': MAX_TANGENT_SPAN,",
    "                'slack_span_max_m': MAX_SLACK_SPAN,",
    "                'road_width_m': ROAD_WIDTH,",
    "                'road_clearance_m': ROAD_CLEARANCE,",
    "                'angle_break_min_deg': ANGLE_BREAK_MIN,",
    "            }, ensure_ascii=False), 'application/json; charset=utf-8')",
    "        if path == '/api/standards':",
    "            if method != 'GET':",
    "                return _err(405, 'Method Not Allowed')",
    "            ref = standards_reference()",
    "            ref['tangent_max_span_m'] = MAX_TANGENT_SPAN",
    "            ref['min_spacing_m'] = MIN_SPACING",
    "            return _envelope(200, json.dumps(ref, ensure_ascii=False), 'application/json; charset=utf-8')",
    "        if path == '/api/sample':",
    "            if method != 'GET':",
    "                return _err(405, 'Method Not Allowed')",
    "            centerline = sample_centerline()",
    "            result = design(centerline)",
    "            payload = to_payload(result)",
    "            payload['source'] = 'sample'",
    "            payload['points'] = centerline",
    "            return _envelope(200, json.dumps(payload, ensure_ascii=False), 'application/json; charset=utf-8')",
    "        if path not in ('/api/design', '/api/export/csv'):",
    "            return _err(404, 'not found')",
    "        if method != 'POST':",
    "            return _err(405, 'Method Not Allowed')",
    "        payload = None",
    "        if body_text and body_text.strip():",
    "            try:",
    "                payload = json.loads(body_text)",
    "            except ValueError:",
    "                payload = None",
    "        args = parse_request(payload or {})",
    "        result = design(",
    "            args['points'],",
    "            offset=args['offset'],",
    "            use_break_poles=args['use_break_poles'],",
    "            road_width=args['road_width'],",
    "            road_clearance=args['road_clearance'],",
    "        )",
    "        if path == '/api/design':",
    "            return _envelope(200, json.dumps(to_payload(result), ensure_ascii=False), 'application/json; charset=utf-8')",
    "        filename = 'poles.csv'",
    "        for part in (query_string or '').split('&'):",
    "            if part.startswith('filename='):",
    "                filename = part.split('=', 1)[1]",
    "        return _envelope(200, poles_to_csv(result.poles), 'text/csv; charset=utf-8', {",
    "            'Content-Disposition': 'attachment; filename=\"' + filename + '\"',",
    "            'X-Design-Status': 'PASS' if result.ok else 'FAIL',",
    "        })",
    "    except ValueError as e:",
    "        return _err(400, str(e))",
    "    except Exception as e:",
    "        return _err(500, str(e))",
    "",
  ].join("\n");

  function ensureEngine() {
    if (enginePromise) return enginePromise;
    enginePromise = (async function () {
      if (typeof window.loadPyodide !== "function") {
        await loadScript(PYODIDE_URL + "pyodide.js");
      }
      var pyodide = await window.loadPyodide({ indexURL: PYODIDE_URL });
      await pyodide.loadPackage("numpy");
      /* Relative to the page URL: works on GitHub Pages sub-path too. */
      var engineUrl = new URL("line_engine.py", document.baseURI).href;
      var resp = await nativeFetch(engineUrl);
      if (!resp.ok) throw new Error("ไม่พบ line_engine.py (HTTP " + resp.status + ")");
      var source = await resp.text();
      pyodide.runPython(source);
      pyodide.runPython(PY_SHIM);
      apiHandle = pyodide.globals.get("handle_api");
      return pyodide;
    })();
    enginePromise.catch(function () { enginePromise = null; });
    return enginePromise;
  }

  async function bridgeFetch(input, init) {
    var url = typeof input === "string" ? new URL(input, document.baseURI) : new URL(input.url, document.baseURI);
    try {
      await ensureEngine();
      var method = init && init.method ? init.method : (input && input.method) || "GET";
      var bodyText = init && typeof init.body === "string" ? init.body : "";
      var query = url.search ? url.search.replace(/^\?/, "") : "";
      var envelope = JSON.parse(apiHandle(method, url.pathname, query, bodyText));
      return new Response(envelope.body, {
        status: envelope.status,
        headers: envelope.headers
      });
    } catch (err) {
      var msg = err && err.message ? err.message : String(err);
      return new Response(JSON.stringify({ error: msg }), {
        status: 500,
        headers: { "Content-Type": "application/json; charset=utf-8" }
      });
    }
  }

  var wrapped = window.fetch;
  window.fetch = function (input, init) {
    var url = typeof input === "string" ? new URL(input, document.baseURI) : new URL(input.url, document.baseURI);
    if (url.pathname.indexOf("/api/") === 0) return bridgeFetch(input, init);
    return wrapped.apply(window, arguments);
  };
})();