import Network
import SwiftUI
import TuxPaneCore

final class MachinesModel: ObservableObject {
    @Published private(set) var machines: [Machine] = []
    @Published private(set) var online: [UUID: Bool] = [:]
    var onConnect: ((Machine) -> Void)?
    var onAdd: (() -> Void)?
    var onCheckForUpdates: (() -> Void)?
    private let store: MachineStore
    private var timer: Timer?

    init(store: MachineStore) {
        self.store = store
        reload()
    }

    func reload() { machines = store.machines }

    func setPreset(_ preset: ResolutionPreset, for machine: Machine) {
        var updated = machine
        updated.preset = preset
        store.update(updated)
        reload()
    }

    func remove(_ machine: Machine) {
        store.remove(machine.id)
        reload()
    }

    func startMonitoring() {
        stopMonitoring()
        checkAll()
        let timer = Timer(timeInterval: 10, repeats: true) { [weak self] _ in self?.checkAll() }
        RunLoop.main.add(timer, forMode: .common)
        self.timer = timer
    }

    func stopMonitoring() {
        timer?.invalidate()
        timer = nil
    }

    /// Online = TCP port 7300 answers on any saved address within 2 s (no sign-in, no video).
    private func checkAll() {
        for machine in machines {
            for host in machine.hosts {
                guard let port = NWEndpoint.Port(rawValue: machine.port) else { continue }
                let connection = NWConnection(host: NWEndpoint.Host(host), port: port, using: .tcp)
                var settled = false
                connection.stateUpdateHandler = { [weak self, weak connection] state in
                    guard !settled else { return }
                    if case .ready = state {
                        settled = true
                        self?.online[machine.id] = true
                        connection?.cancel()
                    }
                }
                connection.start(queue: .main)
                DispatchQueue.main.asyncAfter(deadline: .now() + 2) { [weak self] in
                    if !settled {
                        settled = true
                        if self?.online[machine.id] != true { self?.online[machine.id] = false }
                    }
                    connection.cancel()
                }
            }
        }
    }
}

struct MachinesView: View {
    @ObservedObject var model: MachinesModel
    @State private var pendingRemoval: Machine?

    var body: some View {
        HStack(spacing: 0) {
            BrandPanel(current: nil) {
                Button("Check for updates") { model.onCheckForUpdates?() }
                    .buttonStyle(.link).font(.system(size: 11)).foregroundStyle(.white.opacity(0.7))
            }
            VStack(alignment: .leading, spacing: 14) {
                Text("Your machines").font(.system(size: 23, weight: .semibold))
                Text("Double-click to connect. TuxPane reconnects automatically when you open it.")
                    .foregroundStyle(.secondary)
                if model.machines.isEmpty {
                    Text("No machines yet. Add one to get started.").foregroundStyle(.secondary).padding(.top, 20)
                }
                ScrollView {
                    VStack(spacing: 8) {
                        ForEach(model.machines) { machine in row(machine) }
                    }
                }
                HStack {
                    Button {
                        model.onAdd?()
                    } label: {
                        Label("Add Machine", systemImage: "plus")
                    }
                    Spacer()
                    Link(
                        "Help",
                        destination: URL(
                            string: "https://github.com/vinoth12940/tuxpane/blob/main/docs/troubleshooting.md")!)
                }
            }
            .padding(EdgeInsets(top: 44, leading: 32, bottom: 24, trailing: 32))
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .background(Color(nsColor: .windowBackgroundColor))
        }
        .frame(width: 760, height: 470)
        .onAppear { model.startMonitoring() }
        .onDisappear { model.stopMonitoring() }
        .confirmationDialog(
            "Remove \(pendingRemoval?.name ?? "")?",
            isPresented: Binding(get: { pendingRemoval != nil }, set: { if !$0 { pendingRemoval = nil } })
        ) {
            Button("Remove", role: .destructive) {
                if let machine = pendingRemoval { model.remove(machine) }
                pendingRemoval = nil
            }
        } message: {
            Text("To add it again, run `tuxpane pair` on that machine.")
        }
    }

    private func row(_ machine: Machine) -> some View {
        let online = model.online[machine.id]
        return HStack(spacing: 12) {
            Image(systemName: "desktopcomputer").font(.system(size: 22))
                .foregroundStyle(online == true ? Color.accentColor : Color.secondary)
            VStack(alignment: .leading, spacing: 2) {
                Text(machine.name).font(.headline)
                HStack(spacing: 5) {
                    Circle().fill(online == true ? Color.green : online == false ? Color.secondary : Color.orange)
                        .frame(width: 7, height: 7)
                    Text(online == true ? "Online" : online == false ? "Offline" : "Checking…")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            Spacer()
            Picker(
                "Resolution", selection: Binding(get: { machine.preset }, set: { model.setPreset($0, for: machine) })
            ) {
                ForEach(ResolutionPreset.allCases, id: \.self) { Text($0.title).tag($0) }
            }
            .labelsHidden().frame(width: 130)
            Button("Connect") { model.onConnect?(machine) }
            Button {
                pendingRemoval = machine
            } label: {
                Image(systemName: "trash")
            }
            .buttonStyle(.borderless).help("Remove this machine")
        }
        .padding(12)
        .background(RoundedRectangle(cornerRadius: 10).fill(Color(nsColor: .controlBackgroundColor)))
        .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Color.secondary.opacity(0.2)))
        .contentShape(Rectangle())
        .onTapGesture(count: 2) { model.onConnect?(machine) }
    }
}
