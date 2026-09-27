import AppKit
import SwiftUI
import TuxPaneCore

final class AppDelegate: NSObject, NSApplicationDelegate {
    private static let releasesPage = URL(string: "https://github.com/vinoth12940/tuxpane/releases/latest")!
    private static let latestReleaseAPI = URL(
        string: "https://api.github.com/repos/vinoth12940/tuxpane/releases/latest")!
    private static let troubleshooting = URL(
        string: "https://github.com/vinoth12940/tuxpane/blob/main/docs/troubleshooting.md")!
    private let store = MachineStore(defaults: .standard, secrets: KeychainSecretStore())
    private lazy var machinesModel = MachinesModel(store: store)
    private var capture: InputCapture!
    private var session: RemoteSession?
    private var setupWindow: NSWindow?, machinesWindow: NSWindow?
    private var setupModel: SetupModel?
    private var tapTimer: Timer?
    private var macStyleItem: NSMenuItem!, statsItem: NSMenuItem!
    private var statsVisible = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        let macStyle = UserDefaults.standard.object(forKey: "macStyle") as? Bool ?? true
        capture = InputCapture(macStyle: macStyle)
        buildMenu(macStyle: macStyle)
        machinesModel.onConnect = { [weak self] in self?.connect(to: $0) }
        machinesModel.onAdd = { [weak self] in self?.showSetup() }
        machinesModel.onCheckForUpdates = { [weak self] in self?.checkForUpdates() }
        capture.installEventTap(prompt: false)
        let timer = Timer(timeInterval: 1, repeats: true) { [weak self] _ in
            _ = self?.capture.installEventTap(prompt: false)
        }
        RunLoop.main.add(timer, forMode: .common)
        tapTimer = timer
        switch store.machines.count {
        case 0: showSetup(startAt: .welcome)
        case 1: connect(to: store.machines[0])
        default: showMachines()
        }
        NSApp.activate(ignoringOtherApps: true)
    }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag { showMachines() }
        return true
    }
    func applicationDidBecomeActive(_ notification: Notification) { session?.updateCapture() }
    func applicationDidResignActive(_ notification: Notification) { session?.updateCapture() }

    private func connect(to machine: Machine) {
        guard let token = store.token(for: machine) else {
            alert(
                "Can't connect to \(machine.name)",
                "Its saved key is missing from the Keychain. Remove it and pair again.")
            return
        }
        session?.close()
        machinesWindow?.orderOut(nil)
        let newSession = RemoteSession(machine: machine, token: token, capture: capture, statsVisible: statsVisible)
        newSession.onNeedsPairing = { [weak self] outcome in self?.offerToPairAgain(machine, because: outcome) }
        newSession.onClose = { [weak self, weak newSession] in
            guard let self else { return }
            if self.session === newSession { self.session = nil }
            self.showMachines()
        }
        session = newSession
        newSession.start()
    }
    private func offerToPairAgain(_ machine: Machine, because outcome: ConnectOutcome) {
        let alert = NSAlert()
        alert.messageText = outcome.title
        alert.informativeText =
            "Run `tuxpane pair` on \(machine.name), then choose it in TuxPane and compare the code."
        alert.addButton(withTitle: "Pair Again")
        alert.addButton(withTitle: "Later")
        if alert.runModal() == .alertFirstButtonReturn { showSetup(startAt: .choose) }
    }

    private func showSetup(startAt step: SetupModel.Page = .install) {
        if let setupWindow {
            setupModel?.page = step
            setupWindow.makeKeyAndOrderFront(nil)
            return
        }
        let model = SetupModel(store: store, startAt: store.machines.isEmpty ? .welcome : step)
        model.onWillProbe = { [weak self] info in
            if let session = self?.session, session.matches(info) { session.close() }
        }
        model.onFinished = { [weak self] machine in
            guard let self else { return }
            self.setupWindow?.close()
            self.machinesModel.reload()
            self.connect(to: machine)
        }
        setupModel = model
        let window = makeWindow(title: "Set Up TuxPane", root: SetupView(model: model))
        NotificationCenter.default.addObserver(forName: NSWindow.willCloseNotification, object: window, queue: .main) {
            [weak self] _ in
            self?.setupWindow = nil
            self?.setupModel = nil
        }
        setupWindow = window
    }
    private func showMachines() {
        machinesModel.reload()
        if machinesWindow == nil {
            machinesWindow = makeWindow(title: "TuxPane", root: MachinesView(model: machinesModel))
        }
        machinesWindow?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }
    private func makeWindow<Root: View>(title: String, root: Root) -> NSWindow {
        let window = NSWindow(contentViewController: NSHostingController(rootView: root))
        window.title = title
        window.styleMask = [.titled, .closable, .miniaturizable, .fullSizeContentView]
        window.titlebarAppearsTransparent = true  // the brand panel runs under the traffic lights
        window.titleVisibility = .hidden
        window.isReleasedWhenClosed = false
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        return window
    }
    private func alert(_ title: String, _ message: String) {
        let alert = NSAlert()
        alert.messageText = title
        alert.informativeText = message
        alert.runModal()
    }

    private func buildMenu(macStyle: Bool) {
        let main = NSMenu()
        let appMenu = NSMenu()
        appMenu.addItem(
            withTitle: "About TuxPane", action: #selector(NSApplication.orderFrontStandardAboutPanel(_:)),
            keyEquivalent: "")
        appMenu.addItem(.separator())
        appMenu.addItem(withTitle: "Quit TuxPane", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        addSubmenu(appMenu, to: main)

        // Text fields (e.g. pasting the pairing code) only get ⌘X/⌘C/⌘V/⌘A through an Edit menu.
        let edit = NSMenu(title: "Edit")
        edit.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        let redo = edit.addItem(withTitle: "Redo", action: Selector(("redo:")), keyEquivalent: "z")
        redo.keyEquivalentModifierMask = [.command, .shift]
        edit.addItem(.separator())
        edit.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        addSubmenu(edit, to: main)

        let machines = NSMenu(title: "Machines")
        machines.addItem(withTitle: "Show Machines", action: #selector(showMachinesAction), keyEquivalent: "").target =
            self
        machines.addItem(withTitle: "Add Machine…", action: #selector(addMachineAction), keyEquivalent: "").target =
            self
        addSubmenu(machines, to: main)
        let remote = NSMenu(title: "Remote")
        macStyleItem = remote.addItem(
            withTitle: "Mac-style Shortcuts", action: #selector(toggleMacStyle), keyEquivalent: "")
        macStyleItem.target = self
        macStyleItem.state = macStyle ? .on : .off
        statsItem = remote.addItem(withTitle: "Show Stats", action: #selector(toggleStats), keyEquivalent: "")
        statsItem.target = self
        remote.addItem(withTitle: "Release Keyboard (⌃⌥⎋)", action: #selector(releaseKeyboard), keyEquivalent: "")
            .target = self
        remote.addItem(withTitle: "Toggle Full Screen", action: #selector(toggleFullScreen), keyEquivalent: "").target =
            self
        remote.addItem(withTitle: "Disconnect", action: #selector(disconnect), keyEquivalent: "").target = self
        addSubmenu(remote, to: main)
        let help = NSMenu(title: "Help")
        help.addItem(withTitle: "Troubleshooting", action: #selector(openTroubleshooting), keyEquivalent: "").target =
            self
        help.addItem(withTitle: "Check for Updates…", action: #selector(checkForUpdates), keyEquivalent: "").target =
            self
        addSubmenu(help, to: main)
        NSApp.mainMenu = main
        NSApp.helpMenu = help
    }
    private func addSubmenu(_ menu: NSMenu, to main: NSMenu) {
        let item = NSMenuItem()
        item.submenu = menu
        main.addItem(item)
    }
    @objc private func showMachinesAction() { showMachines() }
    @objc private func addMachineAction() { showSetup() }
    @objc private func releaseKeyboard() { session?.releaseKeyboard() }
    @objc private func toggleFullScreen() { session?.toggleFullScreen() }
    @objc private func disconnect() { session?.close() }
    @objc private func openTroubleshooting() { NSWorkspace.shared.open(Self.troubleshooting) }
    @objc private func toggleMacStyle() {
        capture.resetRemoteKeys()
        capture.translator.macStyle.toggle()
        macStyleItem.state = capture.translator.macStyle ? .on : .off
        UserDefaults.standard.set(capture.translator.macStyle, forKey: "macStyle")
    }
    @objc private func toggleStats() {
        statsVisible.toggle()
        statsItem.state = statsVisible ? .on : .off
        session?.statsVisible = statsVisible
    }
    @objc private func checkForUpdates() {
        URLSession.shared.dataTask(with: Self.latestReleaseAPI) { data, _, _ in
            let tag =
                data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }?["tag_name"] as? String
            DispatchQueue.main.async { self.showUpdateResult(tag) }
        }.resume()
    }
    private func showUpdateResult(_ tag: String?) {
        let current = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0"
        guard let tag else {
            alert("Couldn't check for updates", "GitHub couldn't be reached. Try again later.")
            return
        }
        guard UpdateChecker.isNewer(latestTag: tag, current: current) else {
            alert("TuxPane is up to date", "You have version \(current).")
            return
        }
        let alert = NSAlert()
        alert.messageText = "TuxPane \(tag) is available"
        alert.informativeText =
            "You have \(current). Download the new version, then run `tuxpane update` on your Linux machines."
        alert.addButton(withTitle: "Download")
        alert.addButton(withTitle: "Later")
        if alert.runModal() == .alertFirstButtonReturn { NSWorkspace.shared.open(Self.releasesPage) }
    }
}
