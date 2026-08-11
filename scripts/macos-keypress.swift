import AppKit
import CoreGraphics
import Foundation

enum KeypressError: Error, LocalizedError {
  case usage
  case unsupportedCombo(String)
  case applicationNotFound(String)

  var errorDescription: String? {
    switch self {
    case .usage:
      return "Usage: macos-keypress --bundle <bundle-id> (--activate | --click <x,y> | --state | --combo <modifier→key>)"
    case let .unsupportedCombo(combo):
      return "Unsupported U.S. ANSI combo: \(combo)"
    case let .applicationNotFound(bundle):
      return "Could not find foreground application bundle: \(bundle)"
    }
  }
}

let keyCodes: [String: CGKeyCode] = [
  "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7,
  "c": 8, "v": 9, "b": 11, "q": 12, "w": 13, "e": 14, "r": 15,
  "y": 16, "t": 17, "1": 18, "2": 19, "3": 20, "4": 21, "6": 22,
  "5": 23, "=": 24, "9": 25, "7": 26, "-": 27, "8": 28, "0": 29,
  "]": 30, "o": 31, "u": 32, "[": 33, "i": 34, "p": 35, "l": 37,
  "j": 38, "'": 39, "k": 40, ";": 41, ",": 43, "/": 44, "n": 45,
  "m": 46, ".": 47, "`": 50
]

let modifiers: [String: (code: CGKeyCode, flag: CGEventFlags)] = [
  "meta": (55, .maskCommand),
  "alt": (58, .maskAlternate),
  "ctrl": (59, .maskControl)
]

func argument(_ name: String) -> String? {
  guard let index = CommandLine.arguments.firstIndex(of: name), index + 1 < CommandLine.arguments.count else {
    return nil
  }
  return CommandLine.arguments[index + 1]
}

func post(_ source: CGEventSource, code: CGKeyCode, isDown: Bool, flags: CGEventFlags) {
  guard let event = CGEvent(keyboardEventSource: source, virtualKey: code, keyDown: isDown) else { return }
  event.flags = flags
  event.post(tap: .cghidEventTap)
}

do {
  guard let bundle = argument("--bundle") else {
    throw KeypressError.usage
  }
  guard let application = NSRunningApplication.runningApplications(withBundleIdentifier: bundle).first else {
    throw KeypressError.applicationNotFound(bundle)
  }

  if CommandLine.arguments.contains("--state") {
    let state: [String: Any] = [
      "isActive": application.isActive,
      "isHidden": application.isHidden,
      "processIdentifier": application.processIdentifier
    ]
    let data = try JSONSerialization.data(withJSONObject: state, options: [.sortedKeys])
    FileHandle.standardOutput.write(data)
    exit(0)
  }

  if CommandLine.arguments.contains("--activate") {
    application.activate()
    usleep(300_000)
    exit(0)
  }

  if let point = argument("--click") {
    let coordinates = point.split(separator: ",").compactMap { Double($0) }
    guard coordinates.count == 2 else {
      throw KeypressError.usage
    }
    application.activate()
    usleep(300_000)
    let location = CGPoint(x: coordinates[0], y: coordinates[1])
    let source = CGEventSource(stateID: .hidSystemState)!
    CGEvent(mouseEventSource: source, mouseType: .leftMouseDown, mouseCursorPosition: location, mouseButton: .left)!
      .post(tap: .cghidEventTap)
    CGEvent(mouseEventSource: source, mouseType: .leftMouseUp, mouseCursorPosition: location, mouseButton: .left)!
      .post(tap: .cghidEventTap)
    exit(0)
  }

  guard let combo = argument("--combo") else {
    throw KeypressError.usage
  }
  let pieces = combo.split(separator: "→", maxSplits: 1).map(String.init)
  guard pieces.count == 2,
        let modifier = modifiers[pieces[0]],
        let keyCode = keyCodes[pieces[1]] else {
    throw KeypressError.unsupportedCombo(combo)
  }
  let source = CGEventSource(stateID: .hidSystemState)!
  post(source, code: modifier.code, isDown: true, flags: modifier.flag)
  post(source, code: keyCode, isDown: true, flags: modifier.flag)
  post(source, code: keyCode, isDown: false, flags: modifier.flag)
  post(source, code: modifier.code, isDown: false, flags: [])
} catch {
  FileHandle.standardError.write(Data("\(error.localizedDescription)\n".utf8))
  exit(2)
}
