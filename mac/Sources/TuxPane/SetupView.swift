import AppKit
import ApplicationServices
import SwiftUI
import TuxPaneCore

final class SetupModel: ObservableObject {
    enum Page { case welcome, install, choose, confirm, pasteCode, keyboard }

    static let installCommand =
        "curl -fsSL https://github.com/vinoth12940/tuxpane/releases/latest/download/install.sh | bash"
    static let terminalHelp = URL(
        string: "https://github.com/vinoth12940/tuxpane/blob/main/docs/setup.md#opening-a-terminal-or-ssh")!

    @Published var page: Page { didSet { pageChanged(from: oldValue) } }
    @Published var copied = false
    @Published var accessibilityGranted = AXIsProcessTrusted()
    // Choose
    @Published var discovered: [DiscoveredMachine] = []
    @Published var selected: DiscoveredMachine?
    @Published var manualAddress = ""
    // Confirm
    @Published var pairingName = ""
    @Published var code: String?
    @Published var waitingForLinux = false
    @Published var pairingError: String?
    // Paste a pairing code (fallback)
    @Published var pastedCode = ""
    @Published var checking = false
    @Published var parseError: String?
    @Published var problem: ConnectOutcome?
    @Published var checklist = PairingChecklist()

    var onFinished: ((Machine) -> Void)?
    var onWillProbe: ((PairingInfo) -> Void)?
    private let store: MachineStore
    private let browser = DiscoveryBrowser()
    private var client: PairingClient?
    private var probe: Connection?
    private var paired: Machine?
    private var timer: Timer?

    var trackerStep: SetupStep {
        switch page {
        case .welcome: return .welcome
        case .install: return .install
        case .choose, .confirm, .pasteCode: return .pair
        case .keyboard: return .keyboard
        }
    }

    init(store: MachineStore, startAt page: Page) {
        self.store = store
        self.page = page
        browser.onChange = { [weak self] machines in
            guard let self else { return }
            self.discovered = machines
            if self.selected == nil { self.selected = machines.first }
        }
        let timer = Timer(timeInterval: 1, repeats: true) { [weak self] _ in
            self?.accessibilityGranted = AXIsProcessTrusted()
        }
        RunLoop.main.add(timer, forMode: .common)
        self.timer = timer
        if page == .choose { browser.start() }
    }

    deinit {
        timer?.invalidate()
        browser.stop()
        client?.cancel()
        probe?.stop()
    }

    private func pageChanged(from old: Page) {
        if page == .choose { browser.start() } else if old == .choose { browser.stop() }
    }

    func copyInstallCommand() {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(Self.installCommand, forType: .string)
        copied = true
    }

    // MARK: Discovery pairing

    func pairSelected() {
        if let selected { startPairing(host: selected.host, name: selected.name, port: selected.pairingPort) }
    }

    func pairManually() {
        let host = manualAddress.trimmingCharacters(in: .whitespacesAndNewlines)
        if !host.isEmpty { startPairing(host: host, name: host, port: PairingProtocol.port) }
    }

    private func startPairing(host: String, name: String, port: UInt16) {
        client?.cancel()
        pairingName = name
        code = nil
        waitingForLinux = false
        pairingError = nil
        page = .confirm
        let client = PairingClient(host: host, port: port)
        self.client = client
        client.onCode = { [weak self] in self?.code = $0 }
        client.onFinished = { [weak self] outcome in self?.pairingFinished(outcome) }
        client.start()
    }

    func cancelPairing() {
        client?.cancel()
        client = nil
        page = .choose
    }

    func codesMatch() {
        waitingForLinux = true
        client?.confirm()
    }

    func codesDiffer() {
        client?.abort()
        client = nil
        pairingError =
            "Pairing cancelled. If the codes really differed, another device may be imitating your Linux machine. "
            + "Try again, or pair over Tailscale."
    }

    private func pairingFinished(_ outcome: PairingClient.Outcome) {
        waitingForLinux = false
        switch outcome {
        case let .paired(info):
            guard waitingForLinux else {  // only a pairing the user confirmed here may be saved
                pairingError = "Pairing stopped: the Linux machine answered before you confirmed the code."
                return
            }
            do {
                paired = try store.add(info)
                page = .keyboard
            } catch {
                pairingError = "Couldn't save the pairing in your Keychain: \(error.localizedDescription)"
            }
        case let .rejected(reason):
            if pairingError != nil { return }  // we cancelled it ourselves
            switch reason {
            case "declined on Linux": pairingError = "Pairing was declined on the Linux machine."
            case "busy": pairingError = "That machine is already pairing with another Mac. Try again in a moment."
            default: pairingError = "Pairing didn't complete (\(reason)). Run `tuxpane pair` on Linux and try again."
            }
        case let .failed(message):
            pairingError = message
        }
    }

    // MARK: Paste-a-code fallback

    func pairWithCode() {
        parseError = nil
        problem = nil
        let info: PairingInfo
        do {
            info = try PairingCode.parse(pastedCode)
        } catch {
            parseError = error.localizedDescription
            return
        }
        checking = true
        onWillProbe?(info)
        checklist.start()
        let connection = Connection(
            machine: Machine(pairing: info), token: info.token, requestedSize: (0, 0), reconnect: false)
        probe = connection
        connection.onSecured = { [weak self] in self?.checklist.secured() }
        connection.onOutcome = { [weak self] outcome in
            if outcome == .connected { self?.checklist.signedIn() } else { self?.finishProbe(outcome, info: nil) }
        }
        connection.onMessage = { [weak self] message in
            guard case .video = message, let self, self.checking else { return }
            self.checklist.receivedVideo()
            self.finishProbe(.connected, info: info)
        }
        connection.start()
        DispatchQueue.main.asyncAfter(deadline: .now() + 20) { [weak self, weak connection] in
            guard let self, let connection, connection === self.probe else { return }
            self.finishProbe(.captureFailed("capture failed: no video arrived within 20 seconds"), info: nil)
        }
    }

    private func finishProbe(_ outcome: ConnectOutcome, info: PairingInfo?) {
        guard checking else { return }
        checking = false
        probe?.stop()
        probe = nil
        guard outcome == .connected, let info else {
            checklist.failed(outcome)
            problem = outcome
            return
        }
        do {
            paired = try store.add(info)
            page = .keyboard
        } catch {
            problem = .serverError("Couldn't save the pairing in your Keychain: \(error.localizedDescription)")
        }
    }

    // MARK: Keyboard

    func openAccessibilitySettings() {
        let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
        _ = AXIsProcessTrustedWithOptions(options)
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility") {
            NSWorkspace.shared.open(url)
        }
    }

    func finish() {
        if let paired { onFinished?(paired) }
    }
}

struct SetupView: View {
    @ObservedObject var model: SetupModel

    var body: some View {
        HStack(spacing: 0) {
            BrandPanel(current: model.trackerStep)
            Group {
                switch model.page {
                case .welcome: welcome
                case .install: install
                case .choose: choose
                case .confirm: confirm
                case .pasteCode: pasteCode
                case .keyboard: keyboard
                }
            }
            .background(Color(nsColor: .windowBackgroundColor))
        }
        .frame(width: 760, height: 470)
    }

    // MARK: Pages

    private var welcome: some View {
        SetupPage(
            title: "Welcome to TuxPane",
            subtitle: "Use your Linux computer as if it were part of this Mac. Setup takes about two minutes."
        ) {
            LazyVGrid(
                columns: [GridItem(.flexible(), alignment: .top), GridItem(.flexible(), alignment: .top)], spacing: 14
            ) {
                Feature(symbol: "command", title: "Every shortcut", detail: "⌘C, ⌘Tab and ⌘Space work on Linux")
                Feature(symbol: "play.rectangle", title: "Smooth & sharp", detail: "Hardware video up to 60 fps")
                Feature(
                    symbol: "doc.on.clipboard", title: "Shared clipboard", detail: "Copy on one, paste on the other")
                Feature(
                    symbol: "lock.shield", title: "Private by design",
                    detail: "Encrypted, home network & Tailscale only")
            }
            Note(
                symbol: "info.circle",
                text:
                    "You'll need a Linux machine with an X11 desktop, on the same network as this Mac or on Tailscale.")
        } actions: {
            Spacer()
            Button("Get Started") { model.page = .install }.keyboardShortcut(.defaultAction).controlSize(.large)
        }
    }

    private var install: some View {
        SetupPage(
            title: "Install on your Linux machine",
            subtitle: "In a terminal on Linux, signed in as the desktop user, run:"
        ) {
            HStack(spacing: 10) {
                Text(SetupModel.installCommand)
                    .font(.system(size: 12, design: .monospaced)).lineLimit(1).truncationMode(.middle)
                    .textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
                Button(model.copied ? "Copied" : "Copy") { model.copyInstallCommand() }
            }
            .padding(10)
            .background(RoundedRectangle(cornerRadius: 9).fill(Color(nsColor: .controlBackgroundColor)))
            .overlay(RoundedRectangle(cornerRadius: 9).strokeBorder(Color.secondary.opacity(0.25)))
            VStack(alignment: .leading, spacing: 6) {
                NumberedLine(number: 1, text: "It checks your desktop, packages and graphics.")
                NumberedLine(number: 2, text: "It installs a small background service.")
                NumberedLine(number: 3, text: "It waits for this Mac. Leave it open and click Continue.")
            }
            Link("How do I open a terminal or use SSH?", destination: SetupModel.terminalHelp).font(.callout)
        } actions: {
            Button("Back") { model.page = .welcome }
            Spacer()
            Button("Continue") { model.page = .choose }.keyboardShortcut(.defaultAction).controlSize(.large)
        }
    }

    private var choose: some View {
        SetupPage(
            title: "Choose your Linux machine", subtitle: "Machines on your network that are ready to pair appear here."
        ) {
            if model.discovered.isEmpty {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text("Looking for machines running the installer or `tuxpane pair`…").foregroundStyle(.secondary)
                }
                .padding(.vertical, 6)
            }
            ForEach(model.discovered) { machine in
                MachineChoice(machine: machine, selected: model.selected == machine) { model.selected = machine }
            }
            HStack(spacing: 8) {
                TextField("Not on the same Wi-Fi? Enter a name or Tailscale address", text: $model.manualAddress)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit { model.pairManually() }
                Button("Connect") { model.pairManually() }
                    .disabled(model.manualAddress.trimmingCharacters(in: .whitespaces).isEmpty)
            }
            Button("Paste a pairing code instead") { model.page = .pasteCode }.buttonStyle(.link).font(.callout)
        } actions: {
            Button("Back") { model.page = .install }
            Spacer()
            Button("Pair") { model.pairSelected() }
                .keyboardShortcut(.defaultAction).controlSize(.large).disabled(model.selected == nil)
        }
    }

    private var confirm: some View {
        SetupPage(
            title: model.code == nil ? "Connecting to \(model.pairingName)…" : "Does Linux show the same code?",
            subtitle: model.code == nil ? nil : "This proves you're pairing with your own machine."
        ) {
            if let code = model.code {
                HStack(spacing: 14) {
                    DeviceLabel(symbol: "laptopcomputer", title: "This Mac")
                    Rectangle().fill(Color.accentColor).frame(width: 90, height: 2).opacity(0.7)
                    DeviceLabel(symbol: "desktopcomputer", title: model.pairingName)
                }
                .frame(maxWidth: .infinity)
                DigitTiles(code: code).frame(maxWidth: .infinity)
                Text(
                    model.waitingForLinux
                        ? "Waiting for you to type y and press Enter on Linux…"
                        : "If they match, type y and press Enter in the Linux terminal, then click They Match."
                )
                .foregroundStyle(.secondary).frame(maxWidth: .infinity)
            } else if model.pairingError == nil {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text("Setting up a secure connection…").foregroundStyle(.secondary)
                }
            }
            if let error = model.pairingError {
                Text(error).foregroundStyle(.red).fixedSize(horizontal: false, vertical: true)
            }
        } actions: {
            if model.pairingError != nil {
                Button("Back") { model.page = .choose }
                Spacer()
            } else {
                if model.code == nil {
                    Button("Cancel") { model.cancelPairing() }
                } else {
                    Button("Codes Don't Match") { model.codesDiffer() }
                }
                Spacer()
                if model.waitingForLinux { ProgressView().controlSize(.small) }
                Button("They Match") { model.codesMatch() }
                    .keyboardShortcut(.defaultAction).controlSize(.large)
                    .disabled(model.code == nil || model.waitingForLinux)
            }
        }
    }

    private var pasteCode: some View {
        SetupPage(
            title: "Paste a pairing code", subtitle: "Run `tuxpane pair --code` on Linux and paste the whole line."
        ) {
            TextEditor(text: $model.pastedCode)
                .font(.system(.callout, design: .monospaced)).frame(height: 76)
                .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color.secondary.opacity(0.4)))
            if let error = model.parseError {
                Text(error).foregroundStyle(.red).fixedSize(horizontal: false, vertical: true)
            }
            if model.checking || model.problem != nil {
                VStack(alignment: .leading, spacing: 5) {
                    ForEach(PairingChecklist.Step.allCases, id: \.self) { step in
                        HStack(spacing: 8) {
                            CheckIcon(state: model.checklist.state(step)).frame(width: 16)
                            Text(step.title)
                        }
                    }
                }
            }
            if let problem = model.problem {
                Text(problem.title).bold().foregroundStyle(.red)
                Text(problem.help).fixedSize(horizontal: false, vertical: true).textSelection(.enabled)
            }
        } actions: {
            Button("Back") { model.page = .choose }
            Spacer()
            Button("Pair") { model.pairWithCode() }
                .keyboardShortcut(.defaultAction).controlSize(.large)
                .disabled(model.checking || model.pastedCode.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        }
    }

    private var keyboard: some View {
        SetupPage(
            title: "Send every shortcut to Linux",
            subtitle: "So ⌘Tab and ⌘Space reach Linux instead of your Mac, macOS needs your permission."
        ) {
            VStack(alignment: .leading, spacing: 6) {
                NumberedLine(number: 1, text: "Click Open System Settings.")
                NumberedLine(number: 2, text: "Switch on TuxPane under Accessibility.")
            }
            HStack(spacing: 12) {
                Image(systemName: model.accessibilityGranted ? "checkmark.circle.fill" : "circle.dashed")
                    .font(.system(size: 24))
                    .foregroundStyle(model.accessibilityGranted ? Color.green : Color.secondary)
                VStack(alignment: .leading, spacing: 2) {
                    Text(model.accessibilityGranted ? "Allowed" : "Not allowed yet").bold()
                    Text("Detected automatically. No restart needed.").font(.caption).foregroundStyle(.secondary)
                }
            }
            .padding(12)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: 10).fill(
                    model.accessibilityGranted ? Color.green.opacity(0.08) : Color.secondary.opacity(0.08)))
        } actions: {
            Button("Open System Settings") { model.openAccessibilitySettings() }
            Spacer()
            if !model.accessibilityGranted { Button("Skip") { model.finish() }.buttonStyle(.link) }
            Button("Start Using TuxPane") { model.finish() }.keyboardShortcut(.defaultAction).controlSize(.large)
        }
    }
}

// MARK: Small building blocks

private struct Feature: View {
    let symbol: String
    let title: String
    let detail: String

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: symbol)
                .font(.system(size: 14, weight: .semibold)).foregroundStyle(Color.accentColor)
                .frame(width: 30, height: 30)
                .background(RoundedRectangle(cornerRadius: 8).fill(Color.accentColor.opacity(0.12)))
            VStack(alignment: .leading, spacing: 2) {
                Text(title).bold()
                Text(detail).font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}

private struct Note: View {
    let symbol: String
    let text: String

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: symbol).foregroundStyle(.secondary)
            Text(text).font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
        }
    }
}

private struct NumberedLine: View {
    let number: Int
    let text: String

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Text("\(number).").monospacedDigit().foregroundStyle(.secondary)
            Text(text).foregroundStyle(.secondary)
        }
    }
}

private struct MachineChoice: View {
    let machine: DiscoveredMachine
    let selected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 12) {
                Image(systemName: "desktopcomputer").font(.system(size: 24)).foregroundStyle(Color.accentColor)
                VStack(alignment: .leading, spacing: 2) {
                    Text(machine.name).font(.headline)
                    Text("\(machine.host) · \(machine.os)").font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Text("Ready to pair")
                    .font(.system(size: 11, weight: .semibold)).foregroundStyle(Color.green)
                    .padding(.horizontal, 9).padding(.vertical, 3)
                    .background(Capsule().fill(Color.green.opacity(0.12)))
            }
            .padding(12)
            .background(RoundedRectangle(cornerRadius: 10).fill(Color(nsColor: .controlBackgroundColor)))
            .overlay(
                RoundedRectangle(cornerRadius: 10)
                    .strokeBorder(
                        selected ? Color.accentColor : Color.secondary.opacity(0.25), lineWidth: selected ? 2 : 1))
        }
        .buttonStyle(.plain)
        .accessibilityLabel("\(machine.name), ready to pair")
    }
}

private struct DeviceLabel: View {
    let symbol: String
    let title: String

    var body: some View {
        VStack(spacing: 4) {
            Image(systemName: symbol).font(.system(size: 22))
            Text(title).font(.caption).foregroundStyle(.secondary).lineLimit(1)
        }
    }
}

private struct DigitTiles: View {
    let code: String

    var body: some View {
        HStack(spacing: 8) {
            ForEach(Array(code.enumerated()), id: \.offset) { _, character in
                if character == " " {
                    Spacer().frame(width: 10)
                } else {
                    Text(String(character))
                        .font(.system(size: 34, weight: .bold, design: .monospaced))
                        .frame(width: 50, height: 64)
                        .background(RoundedRectangle(cornerRadius: 12).fill(Color(nsColor: .controlBackgroundColor)))
                        .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(Color.secondary.opacity(0.25)))
                }
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Code \(code)")
    }
}

struct CheckIcon: View {
    let state: PairingChecklist.State

    var body: some View {
        switch state {
        case .pending: Image(systemName: "circle").foregroundStyle(.secondary)
        case .running: ProgressView().controlSize(.small)
        case .done: Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
        case .failed: Image(systemName: "xmark.circle.fill").foregroundStyle(.red)
        }
    }
}
