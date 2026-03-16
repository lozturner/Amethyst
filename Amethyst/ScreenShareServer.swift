//
//  ScreenShareServer.swift
//  Amethyst
//
//  A lightweight local HTTP server that lets you see and control your Mac
//  from any browser on the same machine (or local network).
//
//  Open:  http://localhost:9999
//
//  Endpoints:
//    GET  /           — HTML dashboard with live screenshot + controls
//    GET  /screenshot — Current screen as JPEG (auto-refreshes every 2s)
//    POST /command    — JSON command, e.g. {"command":"cycleLayoutForward"}
//

import Cocoa
import Foundation
import Darwin

final class ScreenShareServer {
    static let port: UInt16 = 9999

    private var serverSocket: Int32 = -1
    private var source: DispatchSourceRead?

    private weak var windowManager: WindowManager?
    private weak var userConfiguration: UserConfiguration?

    init(windowManager: WindowManager, userConfiguration: UserConfiguration) {
        self.windowManager = windowManager
        self.userConfiguration = userConfiguration
    }

    // MARK: - Start / Stop

    func start() {
        serverSocket = socket(AF_INET, SOCK_STREAM, 0)
        guard serverSocket >= 0 else {
            LogManager.log?.error("ScreenShareServer: failed to create socket")
            return
        }

        var reuse: Int32 = 1
        setsockopt(serverSocket, SOL_SOCKET, SO_REUSEADDR, &reuse, socklen_t(MemoryLayout<Int32>.size))

        var addr = sockaddr_in()
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_port = UInt16(ScreenShareServer.port).bigEndian
        addr.sin_addr = in_addr(s_addr: INADDR_ANY)

        let bindResult = withUnsafePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                bind(serverSocket, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }

        guard bindResult == 0 else {
            LogManager.log?.error("ScreenShareServer: failed to bind on port \(ScreenShareServer.port)")
            close(serverSocket)
            serverSocket = -1
            return
        }

        guard listen(serverSocket, 10) == 0 else {
            LogManager.log?.error("ScreenShareServer: failed to listen")
            close(serverSocket)
            serverSocket = -1
            return
        }

        source = DispatchSource.makeReadSource(fileDescriptor: serverSocket, queue: DispatchQueue.global(qos: .utility))
        source?.setEventHandler { [weak self] in self?.acceptConnection() }
        source?.setCancelHandler { [weak self] in
            if let fd = self?.serverSocket, fd >= 0 { close(fd) }
        }
        source?.resume()

        LogManager.log?.info("ScreenShareServer: listening at http://localhost:\(ScreenShareServer.port)")
    }

    func stop() {
        source?.cancel()
        source = nil
    }

    // MARK: - Accept

    private func acceptConnection() {
        let client = accept(serverSocket, nil, nil)
        guard client >= 0 else { return }
        DispatchQueue.global(qos: .utility).async { self.handleClient(client) }
    }

    // MARK: - HTTP handling

    private func handleClient(_ socket: Int32) {
        defer { close(socket) }

        var buf = [UInt8](repeating: 0, count: 16384)
        let n = recv(socket, &buf, buf.count - 1, 0)
        guard n > 0 else { return }

        let request = String(bytes: buf.prefix(n), encoding: .utf8) ?? ""
        let lines = request.components(separatedBy: "\r\n")
        guard let requestLine = lines.first else { return }
        let parts = requestLine.components(separatedBy: " ")
        guard parts.count >= 2 else { return }

        let method = parts[0]
        let path = parts[1]

        if method == "GET" && path == "/screenshot" {
            serveScreenshot(socket)
        } else if method == "GET" {
            serveDashboard(socket)
        } else if method == "POST" && path == "/command" {
            // Find body after blank line
            let separator = "\r\n\r\n"
            if let range = request.range(of: separator) {
                let body = String(request[range.upperBound...])
                handleCommand(body, socket: socket)
            } else {
                sendResponse(socket, status: "400 Bad Request", contentType: "text/plain", body: "Bad Request")
            }
        } else {
            sendResponse(socket, status: "404 Not Found", contentType: "text/plain", body: "Not Found")
        }
    }

    // MARK: - Screenshot

    private func captureScreenJPEG() -> Data? {
        guard let screen = NSScreen.main() else { return nil }
        let screenRect = screen.frame

        guard let image = CGWindowListCreateImage(
            screenRect,
            .optionAll,
            kCGNullWindowID,
            [.bestResolution]
        ) else { return nil }

        let bitmapRep = NSBitmapImageRep(cgImage: image)
        return bitmapRep.representation(using: .JPEG, properties: [NSImageCompressionFactor: 0.7])
    }

    private func serveScreenshot(_ socket: Int32) {
        guard let jpeg = captureScreenJPEG() else {
            sendResponse(socket, status: "500 Internal Server Error", contentType: "text/plain", body: "Screenshot failed")
            return
        }

        let header = "HTTP/1.1 200 OK\r\nContent-Type: image/jpeg\r\nContent-Length: \(jpeg.count)\r\nCache-Control: no-cache\r\nAccess-Control-Allow-Origin: *\r\n\r\n"
        let headerData = Array(header.utf8)
        _ = send(socket, headerData, headerData.count, 0)
        jpeg.withUnsafeBytes { ptr in
            _ = send(socket, ptr.baseAddress, jpeg.count, 0)
        }
    }

    // MARK: - Dashboard HTML

    private func windowList() -> [(app: String, title: String)] {
        var result: [(app: String, title: String)] = []
        DispatchQueue.main.sync {
            result = self.windowManager?.windows.compactMap { win -> (String, String)? in
                let title = win.title() ?? "(untitled)"
                let app = win.app()?.localizedName ?? "?"
                return (app, title)
            } ?? []
        }
        return result
    }

    private func currentLayoutName() -> String {
        var name = "Unknown"
        DispatchQueue.main.sync {
            name = self.windowManager?.focusedScreenManager()
                .flatMap { _ in nil as String? } ?? "—"
            // ScreenManager doesn't expose layout name publicly; use display method
        }
        return name
    }

    private func serveDashboard(_ socket: Int32) {
        let wins = windowList()
        let windowRows = wins.map { w in
            "<tr><td>\(htmlEscape(w.app))</td><td>\(htmlEscape(w.title))</td></tr>"
        }.joined(separator: "\n")

        let html = """
        <!DOCTYPE html>
        <html lang="en">
        <head>
          <meta charset="UTF-8">
          <meta name="viewport" content="width=device-width, initial-scale=1">
          <title>Amethyst Remote</title>
          <style>
            * { box-sizing: border-box; margin: 0; padding: 0; }
            body { font-family: -apple-system, sans-serif; background: #1a1a2e; color: #eee; }
            header { background: #16213e; padding: 14px 20px; display: flex; align-items: center; gap: 12px; }
            header h1 { font-size: 1.2rem; font-weight: 600; }
            .badge { background: #0f3460; color: #e94560; font-size: 0.75rem; padding: 2px 8px; border-radius: 12px; }
            .main { display: grid; grid-template-columns: 1fr 340px; gap: 16px; padding: 16px; height: calc(100vh - 52px); }
            .screen-panel { background: #000; border-radius: 8px; overflow: hidden; position: relative; }
            .screen-panel img { width: 100%; height: 100%; object-fit: contain; display: block; }
            .sidebar { display: flex; flex-direction: column; gap: 12px; overflow-y: auto; }
            .card { background: #16213e; border-radius: 8px; padding: 14px; }
            .card h2 { font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.05em; color: #888; margin-bottom: 10px; }
            .btn-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
            button {
              background: #0f3460; color: #eee; border: none; border-radius: 6px;
              padding: 8px 6px; font-size: 0.8rem; cursor: pointer; transition: background 0.15s;
            }
            button:hover { background: #e94560; }
            button:active { background: #c0303f; }
            .btn-full { grid-column: span 2; }
            table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
            td { padding: 5px 6px; border-bottom: 1px solid #0f3460; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 140px; }
            tr:last-child td { border-bottom: none; }
            .status { font-size: 0.75rem; color: #888; margin-top: 6px; }
          </style>
        </head>
        <body>
          <header>
            <h1>Amethyst Remote</h1>
            <span class="badge">localhost:\(ScreenShareServer.port)</span>
          </header>
          <div class="main">
            <div class="screen-panel">
              <img id="screen" src="/screenshot" alt="Screen">
            </div>
            <div class="sidebar">
              <div class="card">
                <h2>Layout</h2>
                <div class="btn-grid">
                  <button onclick="cmd('cycleLayoutForward')">Next Layout</button>
                  <button onclick="cmd('cycleLayoutBackward')">Prev Layout</button>
                  <button onclick="cmd('displayCurrentLayout')" class="btn-full">Show Current Layout</button>
                </div>
              </div>
              <div class="card">
                <h2>Focus</h2>
                <div class="btn-grid">
                  <button onclick="cmd('focusCCW')">Focus ←</button>
                  <button onclick="cmd('focusCW')">Focus →</button>
                  <button onclick="cmd('focusScreen', {screen:0})">Screen 1</button>
                  <button onclick="cmd('focusScreen', {screen:1})">Screen 2</button>
                </div>
              </div>
              <div class="card">
                <h2>Swap Windows</h2>
                <div class="btn-grid">
                  <button onclick="cmd('swapCCW')">Swap ←</button>
                  <button onclick="cmd('swapCW')">Swap →</button>
                  <button onclick="cmd('swapMain')" class="btn-full">Swap to Main</button>
                  <button onclick="cmd('swapScreenCCW')">Screen ←</button>
                  <button onclick="cmd('swapScreenCW')">Screen →</button>
                </div>
              </div>
              <div class="card">
                <h2>Pane Size</h2>
                <div class="btn-grid">
                  <button onclick="cmd('shrinkMain')">Shrink Main</button>
                  <button onclick="cmd('expandMain')">Expand Main</button>
                  <button onclick="cmd('increaseMain')">+ Main Pane</button>
                  <button onclick="cmd('decreaseMain')">- Main Pane</button>
                </div>
              </div>
              <div class="card">
                <h2>Spaces</h2>
                <div class="btn-grid">
                  <button onclick="cmd('throwSpaceLeft')">Space ←</button>
                  <button onclick="cmd('throwSpaceRight')">Space →</button>
                  <button onclick="cmd('throwSpace', {space:1})">Space 1</button>
                  <button onclick="cmd('throwSpace', {space:2})">Space 2</button>
                  <button onclick="cmd('throwSpace', {space:3})">Space 3</button>
                  <button onclick="cmd('throwSpace', {space:4})">Space 4</button>
                </div>
              </div>
              <div class="card">
                <h2>Tools</h2>
                <div class="btn-grid">
                  <button onclick="cmd('toggleFloat')" class="btn-full">Toggle Float</button>
                  <button onclick="cmd('toggleTiling')" class="btn-full">Toggle Tiling</button>
                  <button onclick="cmd('reevaluateWindows')" class="btn-full">Re-evaluate Windows</button>
                </div>
              </div>
              <div class="card">
                <h2>Open Windows (\(wins.count))</h2>
                <table>
                  <tbody>
                    \(windowRows.isEmpty ? "<tr><td colspan=2>No managed windows</td></tr>" : windowRows)
                  </tbody>
                </table>
              </div>
              <p class="status" id="status">Ready</p>
            </div>
          </div>
          <script>
            // Auto-refresh screenshot every 2 seconds
            const img = document.getElementById('screen');
            setInterval(() => {
              const ts = Date.now();
              img.src = '/screenshot?' + ts;
            }, 2000);

            async function cmd(command, extra) {
              const body = Object.assign({command}, extra || {});
              const status = document.getElementById('status');
              try {
                const res = await fetch('/command', {
                  method: 'POST',
                  headers: {'Content-Type': 'application/json'},
                  body: JSON.stringify(body)
                });
                const json = await res.json();
                status.textContent = json.success
                  ? '✓ ' + command
                  : '✗ ' + (json.error || 'error');
              } catch(e) {
                status.textContent = '✗ ' + e.message;
              }
            }
          </script>
        </body>
        </html>
        """

        sendResponse(socket, status: "200 OK", contentType: "text/html; charset=utf-8", body: html)
    }

    // MARK: - Command handling

    private func handleCommand(_ body: String, socket: Int32) {
        let trimmed = body.trimmingCharacters(in: .whitespacesAndNewlines)
        guard
            let data = trimmed.data(using: .utf8),
            let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
            let params = json,
            let command = params["command"] as? String
        else {
            sendResponse(socket, status: "400 Bad Request", contentType: "application/json",
                         body: "{\"success\":false,\"error\":\"Invalid JSON or missing 'command'\"}")
            return
        }

        var errorMsg: String? = nil
        DispatchQueue.main.sync {
            errorMsg = self.executeCommand(command, params: params)
        }

        if let err = errorMsg {
            sendResponse(socket, status: "200 OK", contentType: "application/json",
                         body: "{\"success\":false,\"error\":\"\(jsonEscape(err))\"}")
        } else {
            sendResponse(socket, status: "200 OK", contentType: "application/json",
                         body: "{\"success\":true,\"command\":\"\(command)\"}")
        }
    }

    private func executeCommand(_ command: String, params: [String: Any]) -> String? {
        guard let wm = windowManager, let config = userConfiguration else {
            return "WindowManager not available"
        }

        switch command {
        case "cycleLayoutForward":   wm.focusedScreenManager()?.cycleLayoutForward()
        case "cycleLayoutBackward":  wm.focusedScreenManager()?.cycleLayoutBackward()
        case "focusCCW":             wm.moveFocusCounterClockwise()
        case "focusCW":              wm.moveFocusClockwise()
        case "swapCCW":              wm.swapFocusedWindowCounterClockwise()
        case "swapCW":               wm.swapFocusedWindowClockwise()
        case "swapMain":             wm.swapFocusedWindowToMain()
        case "swapScreenCCW":        wm.swapFocusedWindowScreenCounterClockwise()
        case "swapScreenCW":         wm.swapFocusedWindowScreenClockwise()
        case "toggleFloat":          wm.toggleFloatForFocusedWindow()
        case "displayCurrentLayout": wm.displayCurrentLayout()
        case "reevaluateWindows":    wm.reevaluateWindows()
        case "throwSpaceLeft":       wm.pushFocusedWindowToSpaceLeft()
        case "throwSpaceRight":      wm.pushFocusedWindowToSpaceRight()
        case "toggleTiling":
            config.tilingEnabled = !config.tilingEnabled
            wm.markAllScreensForReflowWithChange(.unknown)
        case "toggleFocusFollowsMouse":
            config.toggleFocusFollowsMouse()
        case "shrinkMain":
            wm.focusedScreenManager()?.updateCurrentLayout { ($0 as? PanedLayout)?.shrinkMainPane() }
        case "expandMain":
            wm.focusedScreenManager()?.updateCurrentLayout { ($0 as? PanedLayout)?.expandMainPane() }
        case "increaseMain":
            wm.focusedScreenManager()?.updateCurrentLayout { ($0 as? PanedLayout)?.increaseMainPaneCount() }
        case "decreaseMain":
            wm.focusedScreenManager()?.updateCurrentLayout { ($0 as? PanedLayout)?.decreaseMainPaneCount() }
        case "focusScreen":
            guard let screen = params["screen"] as? Int else { return "Missing 'screen' integer" }
            wm.focusScreen(at: screen)
        case "throwScreen":
            guard let screen = params["screen"] as? Int else { return "Missing 'screen' integer" }
            wm.throwToScreenAtIndex(screen)
        case "throwSpace":
            guard let space = params["space"] as? Int, space >= 1 else { return "Missing 'space' integer >= 1" }
            wm.pushFocusedWindowToSpace(UInt(space))
        default:
            return "Unknown command '\(command)'"
        }

        return nil
    }

    // MARK: - HTTP helpers

    private func sendResponse(_ socket: Int32, status: String, contentType: String, body: String) {
        let bodyData = Array(body.utf8)
        let header = "HTTP/1.1 \(status)\r\nContent-Type: \(contentType)\r\nContent-Length: \(bodyData.count)\r\nAccess-Control-Allow-Origin: *\r\nConnection: close\r\n\r\n"
        let headerBytes = Array(header.utf8)
        _ = send(socket, headerBytes, headerBytes.count, 0)
        _ = send(socket, bodyData, bodyData.count, 0)
    }

    private func htmlEscape(_ str: String) -> String {
        return str
            .replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
    }

    private func jsonEscape(_ str: String) -> String {
        return str
            .replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"")
    }
}
