//
//  RemoteControlServer.swift
//  Amethyst
//
//  Created for remote control of Amethyst via Unix domain socket.
//  Allows Claude Code and other tools to control window management remotely.
//
//  Usage:
//    Send a JSON command to /tmp/amethyst.sock:
//      echo '{"command":"cycleLayoutForward"}' | nc -U /tmp/amethyst.sock
//
//  Available commands:
//    cycleLayoutForward, cycleLayoutBackward
//    focusCCW, focusCW
//    swapCCW, swapCW, swapMain
//    swapScreenCCW, swapScreenCW
//    toggleFloat, toggleTiling, toggleFocusFollowsMouse
//    shrinkMain, expandMain, increaseMain, decreaseMain
//    displayCurrentLayout, reevaluateWindows
//    focusScreen  {"command":"focusScreen","screen":0}
//    throwScreen  {"command":"throwScreen","screen":0}
//    throwSpace   {"command":"throwSpace","space":1}
//    throwSpaceLeft, throwSpaceRight
//

import Foundation
import Darwin

final class RemoteControlServer {
    static let socketPath = "/tmp/amethyst.sock"

    private var serverSocket: Int32 = -1
    private var source: DispatchSourceRead?

    private weak var windowManager: WindowManager?
    private weak var userConfiguration: UserConfiguration?

    init(windowManager: WindowManager, userConfiguration: UserConfiguration) {
        self.windowManager = windowManager
        self.userConfiguration = userConfiguration
    }

    func start() {
        unlink(RemoteControlServer.socketPath)

        serverSocket = socket(AF_UNIX, SOCK_STREAM, 0)
        guard serverSocket >= 0 else {
            LogManager.log?.error("RemoteControlServer: failed to create socket")
            return
        }

        var addr = sockaddr_un()
        addr.sun_family = sa_family_t(AF_UNIX)
        withUnsafeMutablePointer(to: &addr.sun_path) { pathPtr in
            pathPtr.withMemoryRebound(to: CChar.self, capacity: MemoryLayout.size(ofValue: addr.sun_path)) { charPtr in
                _ = strlcpy(charPtr, RemoteControlServer.socketPath, MemoryLayout.size(ofValue: addr.sun_path))
            }
        }

        let bindResult = withUnsafePointer(to: &addr) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                bind(serverSocket, $0, socklen_t(MemoryLayout<sockaddr_un>.size))
            }
        }

        guard bindResult == 0 else {
            LogManager.log?.error("RemoteControlServer: failed to bind socket at \(RemoteControlServer.socketPath)")
            close(serverSocket)
            serverSocket = -1
            return
        }

        guard listen(serverSocket, 5) == 0 else {
            LogManager.log?.error("RemoteControlServer: failed to listen on socket")
            close(serverSocket)
            serverSocket = -1
            return
        }

        source = DispatchSource.makeReadSource(fileDescriptor: serverSocket, queue: DispatchQueue.global(qos: .utility))
        source?.setEventHandler { [weak self] in
            self?.acceptConnection()
        }
        source?.setCancelHandler { [weak self] in
            guard let fd = self?.serverSocket, fd >= 0 else { return }
            close(fd)
            unlink(RemoteControlServer.socketPath)
        }
        source?.resume()

        LogManager.log?.info("RemoteControlServer: listening at \(RemoteControlServer.socketPath)")
    }

    func stop() {
        source?.cancel()
        source = nil
    }

    // MARK: - Private

    private func acceptConnection() {
        let clientSocket = accept(serverSocket, nil, nil)
        guard clientSocket >= 0 else { return }

        DispatchQueue.global(qos: .utility).async {
            self.handleConnection(clientSocket)
        }
    }

    private func handleConnection(_ socket: Int32) {
        defer { close(socket) }

        var buffer = [UInt8](repeating: 0, count: 4096)
        let bytesRead = recv(socket, &buffer, buffer.count - 1, 0)
        guard bytesRead > 0 else { return }

        let data = Data(buffer.prefix(bytesRead))
        let response = processCommand(data)

        let responseBytes = Array((response + "\n").utf8)
        _ = send(socket, responseBytes, responseBytes.count, 0)
    }

    private func processCommand(_ data: Data) -> String {
        guard
            let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
            let params = json,
            let command = params["command"] as? String
        else {
            return "{\"success\":false,\"error\":\"Invalid JSON or missing 'command' key\"}"
        }

        var errorMessage: String? = nil

        DispatchQueue.main.sync {
            errorMessage = self.executeCommand(command, params: params)
        }

        if let error = errorMessage {
            return "{\"success\":false,\"error\":\"\(error)\"}"
        }
        return "{\"success\":true,\"command\":\"\(command)\"}"
    }

    /// Executes the command on the main thread. Returns an error string or nil on success.
    private func executeCommand(_ command: String, params: [String: Any]) -> String? {
        guard let wm = windowManager, let config = userConfiguration else {
            return "WindowManager not available"
        }

        switch command {
        case "cycleLayoutForward":
            wm.focusedScreenManager()?.cycleLayoutForward()

        case "cycleLayoutBackward":
            wm.focusedScreenManager()?.cycleLayoutBackward()

        case "focusCCW":
            wm.moveFocusCounterClockwise()

        case "focusCW":
            wm.moveFocusClockwise()

        case "swapCCW":
            wm.swapFocusedWindowCounterClockwise()

        case "swapCW":
            wm.swapFocusedWindowClockwise()

        case "swapMain":
            wm.swapFocusedWindowToMain()

        case "swapScreenCCW":
            wm.swapFocusedWindowScreenCounterClockwise()

        case "swapScreenCW":
            wm.swapFocusedWindowScreenClockwise()

        case "toggleFloat":
            wm.toggleFloatForFocusedWindow()

        case "toggleTiling":
            config.tilingEnabled = !config.tilingEnabled
            wm.markAllScreensForReflowWithChange(.unknown)

        case "toggleFocusFollowsMouse":
            config.toggleFocusFollowsMouse()

        case "shrinkMain":
            wm.focusedScreenManager()?.updateCurrentLayout { layout in
                (layout as? PanedLayout)?.shrinkMainPane()
            }

        case "expandMain":
            wm.focusedScreenManager()?.updateCurrentLayout { layout in
                (layout as? PanedLayout)?.expandMainPane()
            }

        case "increaseMain":
            wm.focusedScreenManager()?.updateCurrentLayout { layout in
                (layout as? PanedLayout)?.increaseMainPaneCount()
            }

        case "decreaseMain":
            wm.focusedScreenManager()?.updateCurrentLayout { layout in
                (layout as? PanedLayout)?.decreaseMainPaneCount()
            }

        case "displayCurrentLayout":
            wm.displayCurrentLayout()

        case "reevaluateWindows":
            wm.reevaluateWindows()

        case "focusScreen":
            guard let screen = params["screen"] as? Int else {
                return "Missing 'screen' parameter (integer)"
            }
            wm.focusScreen(at: screen)

        case "throwScreen":
            guard let screen = params["screen"] as? Int else {
                return "Missing 'screen' parameter (integer)"
            }
            wm.throwToScreenAtIndex(screen)

        case "throwSpace":
            guard let space = params["space"] as? Int, space >= 1 else {
                return "Missing or invalid 'space' parameter (integer >= 1)"
            }
            wm.pushFocusedWindowToSpace(UInt(space))

        case "throwSpaceLeft":
            wm.pushFocusedWindowToSpaceLeft()

        case "throwSpaceRight":
            wm.pushFocusedWindowToSpaceRight()

        default:
            return "Unknown command '\(command)'"
        }

        return nil
    }
}
